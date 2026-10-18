"""Causal GRU next-response predictor.

The probability at step t is P(correct_t | concept_t, interactions before t). The current
response is a target, not an input: ``shifted_previous_responses`` feeds only the previous
outcome into the GRU, and the GRU is not bidirectional. Padding is masked out of the loss
and zeroed before the recurrence so a padded slot cannot change a real prediction.

This module is imported by the offline experiment commands. The tutoring request path does
not import it, and a trained checkpoint is not a mastery estimate.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import torch
from pydantic import Field
from torch import nn

from app.schemas.common import ContractModel, EntityId
from app.tracing.contracts import (
    ELIGIBILITY_VERSION,
    OpportunityKey,
    PredictorMetadata,
    ResponsePrediction,
    TracingEvent,
    TracingUpdate,
)
from app.tracing.predictor import SnapshotMismatchError

GRU_ALGORITHM = "gru"
GRU_ALGORITHM_VERSION = "gru-causal.v1"
GRAPH_FEATURE_DIM = 4
RESPONSE_START = 0
RESPONSE_INCORRECT = 1
RESPONSE_CORRECT = 2
RELOAD_ATOL = 1e-5


class GRUModelConfig(ContractModel):
    """Architecture of one causal GRU. Graph features are an optional scalar summary."""

    schema_version: Literal["gru-model-config.v1"] = "gru-model-config.v1"
    embed_dim: int = Field(ge=1, le=128)
    hidden_dim: int = Field(ge=1, le=128)
    num_layers: int = Field(default=1, ge=1, le=2)
    use_graph_features: bool = False
    graph_feature_dim: int = Field(default=GRAPH_FEATURE_DIM, ge=1, le=16)


class GRUHistoryItem(ContractModel):
    observation_id: EntityId
    concept_id: EntityId
    correct: bool
    opportunity_key: OpportunityKey


class GRUSnapshot(ContractModel):
    """Learner interaction history for one GRU. Weights live in the checkpoint, not here."""

    schema_version: Literal["gru-snapshot.v1"] = "gru-snapshot.v1"
    metadata: PredictorMetadata
    learner_id: EntityId
    history: list[GRUHistoryItem]
    vocabulary_fingerprint: str = Field(min_length=8, max_length=64)
    config_fingerprint: str = Field(min_length=8, max_length=64)


class ConceptVocabulary:
    """Maps concept ids to embedding rows. 0 is padding and 1 is an unseen concept."""

    def __init__(self, concept_ids: Sequence[str]) -> None:
        ordered = list(dict.fromkeys(concept_ids))
        if not ordered or any(not concept_id for concept_id in ordered):
            raise ValueError("concept vocabulary needs at least one non-empty id")
        self.concept_ids = tuple(ordered)
        self._to_index = {concept_id: index + 2 for index, concept_id in enumerate(ordered)}

    @property
    def size(self) -> int:
        return len(self._to_index) + 2

    def encode(self, concept_id: str) -> int:
        return self._to_index.get(concept_id, 1)

    def fingerprint(self) -> str:
        payload = json.dumps(self.concept_ids)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_json(self) -> dict[str, object]:
        return {"concept_ids": list(self.concept_ids)}

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "ConceptVocabulary":
        raw = payload.get("concept_ids")
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ValueError("vocabulary concept_ids must be a list of strings")
        return cls(raw)


def config_fingerprint(config: GRUModelConfig) -> str:
    return hashlib.sha256(config.model_dump_json().encode()).hexdigest()[:16]


def shifted_previous_responses(correct: Sequence[int]) -> list[int]:
    """Previous-response channel aligned with ``correct``.

    Position 0 is the start code. Position t > 0 is the outcome at t-1 (1 incorrect,
    2 correct). The outcome at t is not copied into position t.
    """

    if not correct:
        return []
    shifted = [RESPONSE_START]
    for value in correct[:-1]:
        if value not in (0, 1):
            raise ValueError("correctness values must be 0 or 1")
        shifted.append(RESPONSE_CORRECT if value == 1 else RESPONSE_INCORRECT)
    return shifted


def prerequisite_summary(
    concept_id: str,
    prior: Sequence[tuple[str, int]],
    prerequisites: Mapping[str, Sequence[str]],
) -> list[float]:
    """Four scalars from completed interactions. This is not a graph neural network.

    ``prior`` must already exclude the current outcome and every later interaction.
    """

    required = tuple(prerequisites.get(concept_id, ()))
    if required:
        correct = {name for name, value in prior if value == 1}
        seen = {name for name, _value in prior}
        fraction_correct = sum(name in correct for name in required) / len(required)
        fraction_seen = sum(name in seen for name in required) / len(required)
    else:
        fraction_correct = 0.0
        fraction_seen = 0.0
    repeats = sum(1 for name, _value in prior if name == concept_id)
    last_same = 1.0 if prior and prior[-1][0] == concept_id else 0.0
    return [fraction_correct, fraction_seen, math.tanh(repeats / 5.0), last_same]


class CausalConceptGRU(nn.Module):
    """Unidirectional GRU over concept embeddings and the shifted previous response."""

    def __init__(self, vocab_size: int, config: GRUModelConfig) -> None:
        super().__init__()
        if vocab_size < 2:
            raise ValueError("vocabulary must include padding and unknown rows")
        self.config = config
        self.concept_embed = nn.Embedding(vocab_size, config.embed_dim, padding_idx=0)
        self.response_embed = nn.Embedding(3, config.embed_dim, padding_idx=0)
        self.graph_proj: nn.Linear | None
        if config.use_graph_features:
            self.graph_proj = nn.Linear(config.graph_feature_dim, config.embed_dim)
            input_dim = config.embed_dim * 3
        else:
            self.graph_proj = None
            input_dim = config.embed_dim * 2
        self.gru = nn.GRU(
            input_size=input_dim,
            hidden_size=config.hidden_dim,
            num_layers=config.num_layers,
            batch_first=True,
            bidirectional=False,
        )
        self.output = nn.Linear(config.hidden_dim, 1)

    def forward(
        self,
        concept_ids: torch.Tensor,
        prev_responses: torch.Tensor,
        mask: torch.Tensor,
        graph_features: torch.Tensor | None = None,
    ) -> torch.Tensor:
        pieces = [self.concept_embed(concept_ids), self.response_embed(prev_responses)]
        if self.graph_proj is not None:
            if graph_features is None:
                graph_features = concept_ids.new_zeros(
                    concept_ids.shape[0],
                    concept_ids.shape[1],
                    self.config.graph_feature_dim,
                    dtype=pieces[0].dtype,
                )
            pieces.append(self.graph_proj(graph_features))
        inputs = torch.cat(pieces, dim=-1)
        inputs = inputs * mask.unsqueeze(-1).to(dtype=inputs.dtype)
        hidden, _state = self.gru(inputs)
        logits = self.output(hidden).squeeze(-1)
        if not isinstance(logits, torch.Tensor):
            raise TypeError("GRU output was not a tensor")
        return logits


def masked_response_loss(
    logits: torch.Tensor, targets: torch.Tensor, mask: torch.Tensor
) -> torch.Tensor:
    """Mean binary cross-entropy on real steps. Padded steps contribute nothing."""

    per_step = nn.functional.binary_cross_entropy_with_logits(logits, targets, reduction="none")
    weights = mask.to(dtype=per_step.dtype)
    return (per_step * weights).sum() / weights.sum().clamp(min=1.0)


class GRUPredictor:
    """One learner's causal GRU over the same eligible opportunities BKT would count.

    ``latent_knowledge`` stays unset: the network predicts the next response, it does not
    estimate a latent skill, and the checkpoint is not calibrated.
    """

    def __init__(
        self,
        learner_id: str,
        model: CausalConceptGRU,
        vocabulary: ConceptVocabulary,
        *,
        prerequisites: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self.learner_id = learner_id
        self.model = model
        self.vocabulary = vocabulary
        self.prerequisites = {key: tuple(value) for key, value in (prerequisites or {}).items()}
        self._history: list[tuple[str, str, bool, str]] = []
        self._observed: set[str] = set()
        self._opportunities: dict[str, list[str]] = {}

    def metadata(self) -> PredictorMetadata:
        return PredictorMetadata(
            algorithm=GRU_ALGORITHM,
            algorithm_version=GRU_ALGORITHM_VERSION,
            eligibility_version=ELIGIBILITY_VERSION,
            parameter_version=f"gru.{config_fingerprint(self.model.config)}",
            has_latent_state=False,
            calibrated=False,
        )

    def reset(self) -> None:
        self._history = []
        self._observed = set()
        self._opportunities = {}

    def predict_before_observation(self, concept_id: str) -> ResponsePrediction:
        probability = self._probability(concept_id)
        return ResponsePrediction(
            concept_id=concept_id,
            p_correct=probability,
            latent_knowledge=None,
            algorithm=GRU_ALGORITHM,
            algorithm_version=GRU_ALGORITHM_VERSION,
            parameter_version=self.metadata().parameter_version,
            calibrated=False,
            opportunities_counted=len(self._opportunities.get(concept_id, [])),
        )

    def _probability(self, concept_id: str) -> float:
        concepts = [item[1] for item in self._history] + [concept_id]
        responses = [int(item[2]) for item in self._history] + [0]
        previous = shifted_previous_responses(responses)
        concept_tensor = torch.tensor(
            [[self.vocabulary.encode(concept) for concept in concepts]], dtype=torch.long
        )
        previous_tensor = torch.tensor([previous], dtype=torch.long)
        mask = torch.ones(1, len(concepts), dtype=torch.bool)
        graph_tensor = None
        if self.model.config.use_graph_features:
            prior: list[tuple[str, int]] = []
            rows: list[list[float]] = []
            for _observation_id, concept, correct, _opportunity_key in self._history:
                rows.append(prerequisite_summary(concept, prior, self.prerequisites))
                prior.append((concept, int(correct)))
            rows.append(prerequisite_summary(concept_id, prior, self.prerequisites))
            graph_tensor = torch.tensor([rows], dtype=torch.float)
        self.model.eval()
        with torch.no_grad():
            logits = self.model(concept_tensor, previous_tensor, mask, graph_tensor)
            probability = float(torch.sigmoid(logits[0, -1]).item())
        if not math.isfinite(probability):
            raise RuntimeError("GRU produced a non-finite probability")
        return min(1.0, max(0.0, probability))

    def _no_update(self, event: TracingEvent, status: str, reason: str | None) -> TracingUpdate:
        return TracingUpdate.model_validate(
            {
                "observation_id": event.observation_id,
                "concept_id": event.concept_id,
                "opportunity_key": event.opportunity_key,
                "status": status,
                "reason": reason,
                "observed_correct": event.correct,
            }
        )

    def observe(self, event: TracingEvent) -> TracingUpdate:
        if event.learner_id != self.learner_id:
            raise SnapshotMismatchError("event belongs to a different learner's history")
        if event.observation_id in self._observed:
            return self._no_update(event, "already_observed", "observation already applied")
        if not event.eligible:
            return self._no_update(event, "ineligible", event.ineligible_reason)
        if event.concept_id is None or event.correct is None or event.opportunity_key is None:
            raise ValueError("eligible event lacks concept, correctness or opportunity")
        concept_id = event.concept_id
        if event.opportunity_key in self._opportunities.get(concept_id, []):
            return self._no_update(
                event, "duplicate_opportunity", "opportunity already counted for this concept"
            )
        prediction = self.predict_before_observation(concept_id)
        self._observed.add(event.observation_id)
        self._history.append(
            (event.observation_id, concept_id, event.correct, event.opportunity_key)
        )
        self._opportunities.setdefault(concept_id, []).append(event.opportunity_key)
        return TracingUpdate(
            observation_id=event.observation_id,
            concept_id=concept_id,
            opportunity_key=event.opportunity_key,
            status="counted",
            sequence=len(self._opportunities[concept_id]),
            prediction=prediction,
            observed_correct=event.correct,
        )

    def save(self) -> GRUSnapshot:
        return GRUSnapshot(
            metadata=self.metadata(),
            learner_id=self.learner_id,
            history=[
                GRUHistoryItem(
                    observation_id=observation_id,
                    concept_id=concept_id,
                    correct=correct,
                    opportunity_key=opportunity_key,
                )
                for observation_id, concept_id, correct, opportunity_key in self._history
            ],
            vocabulary_fingerprint=self.vocabulary.fingerprint(),
            config_fingerprint=config_fingerprint(self.model.config),
        )

    def load(self, snapshot: GRUSnapshot) -> None:
        if snapshot.learner_id != self.learner_id:
            raise SnapshotMismatchError("snapshot belongs to a different learner")
        if snapshot.metadata != self.metadata():
            raise SnapshotMismatchError(
                "snapshot algorithm or parameter version differs from this predictor"
            )
        if snapshot.vocabulary_fingerprint != self.vocabulary.fingerprint():
            raise SnapshotMismatchError("snapshot vocabulary does not match this model")
        if snapshot.config_fingerprint != config_fingerprint(self.model.config):
            raise SnapshotMismatchError("snapshot config does not match this model")
        self.reset()
        for item in snapshot.history:
            self._history.append(
                (item.observation_id, item.concept_id, item.correct, item.opportunity_key)
            )
            self._observed.add(item.observation_id)
            self._opportunities.setdefault(item.concept_id, []).append(item.opportunity_key)


def save_checkpoint(
    directory: Path,
    model: CausalConceptGRU,
    vocabulary: ConceptVocabulary,
    config: GRUModelConfig,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), directory / "model.pt")
    (directory / "config.json").write_text(config.model_dump_json(indent=2))
    (directory / "vocabulary.json").write_text(json.dumps(vocabulary.to_json(), indent=2) + "\n")


def load_checkpoint(
    directory: Path,
) -> tuple[CausalConceptGRU, ConceptVocabulary, GRUModelConfig]:
    config = GRUModelConfig.model_validate_json((directory / "config.json").read_text())
    vocabulary = ConceptVocabulary.from_json(
        json.loads((directory / "vocabulary.json").read_text())
    )
    model = CausalConceptGRU(vocabulary.size, config)
    state = torch.load(directory / "model.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.eval()
    return model, vocabulary, config
