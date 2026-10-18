"""Learner splits and causal sequence windows.

Learners are assigned to train or held-out before any window is built. A window contains one
learner, in time order. The response at position t is the target; the input channel at t
carries only the response from t-1.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import torch

from app.tracing.gru import (
    GRAPH_FEATURE_DIM,
    ConceptVocabulary,
    prerequisite_summary,
    shifted_previous_responses,
)


@dataclass(frozen=True)
class SequenceExample:
    observation_id: str
    learner_id: str
    concept_id: str
    correct: int
    observed_at: datetime
    opportunity_key: str
    eligible: bool = True


@dataclass(frozen=True)
class LearnerSplit:
    seed: int
    train_ids: tuple[str, ...]
    heldout_ids: tuple[str, ...]


@dataclass(frozen=True)
class SequenceWindow:
    learner_id: str
    observation_ids: tuple[str, ...]
    concept_ids: tuple[str, ...]
    responses: tuple[int, ...]
    observed_at: tuple[datetime, ...]


@dataclass
class TracingBatch:
    concept_ids: torch.Tensor
    prev_responses: torch.Tensor
    targets: torch.Tensor
    mask: torch.Tensor
    graph_features: torch.Tensor | None
    observation_ids: list[list[str]]


def split_learners(
    learner_ids: Sequence[str], *, heldout_count: int, seed: int
) -> LearnerSplit:
    """Shuffle whole learners. Call this before ``build_windows``."""

    unique = sorted(set(learner_ids))
    if heldout_count <= 0 or heldout_count >= len(unique):
        raise ValueError("heldout_count must leave at least one training learner")
    order = np.random.default_rng(seed).permutation(len(unique))
    heldout_indexes = sorted(int(index) for index in order[:heldout_count])
    train_indexes = sorted(int(index) for index in order[heldout_count:])
    return LearnerSplit(
        seed=seed,
        train_ids=tuple(unique[index] for index in train_indexes),
        heldout_ids=tuple(unique[index] for index in heldout_indexes),
    )


def build_windows(
    examples: Sequence[SequenceExample],
    learner_ids: set[str],
    *,
    window: int,
    stride: int,
) -> list[SequenceWindow]:
    """Window only the given learners, after sorting each learner by time."""

    if window < 1 or stride < 1:
        raise ValueError("window and stride must be positive")
    grouped: dict[str, list[SequenceExample]] = {}
    for example in examples:
        if not example.eligible or example.learner_id not in learner_ids:
            continue
        grouped.setdefault(example.learner_id, []).append(example)
    windows: list[SequenceWindow] = []
    for learner_id in sorted(grouped):
        rows = sorted(grouped[learner_id], key=lambda row: (row.observed_at, row.observation_id))
        for start in range(0, len(rows), stride):
            chunk = rows[start : start + window]
            if not chunk:
                break
            windows.append(
                SequenceWindow(
                    learner_id=learner_id,
                    observation_ids=tuple(row.observation_id for row in chunk),
                    concept_ids=tuple(row.concept_id for row in chunk),
                    responses=tuple(row.correct for row in chunk),
                    observed_at=tuple(row.observed_at for row in chunk),
                )
            )
            if start + window >= len(rows):
                break
    return windows


def collate_windows(
    windows: Sequence[SequenceWindow],
    vocabulary: ConceptVocabulary,
    *,
    use_graph_features: bool,
    prerequisites: Mapping[str, Sequence[str]],
) -> TracingBatch:
    if not windows:
        raise ValueError("no windows to collate")
    width = max(len(window.responses) for window in windows)
    count = len(windows)
    concept_ids = torch.zeros(count, width, dtype=torch.long)
    prev_responses = torch.zeros(count, width, dtype=torch.long)
    targets = torch.zeros(count, width, dtype=torch.float)
    mask = torch.zeros(count, width, dtype=torch.bool)
    graph = (
        torch.zeros(count, width, GRAPH_FEATURE_DIM, dtype=torch.float)
        if use_graph_features
        else None
    )
    observation_ids: list[list[str]] = []
    for row, window in enumerate(windows):
        length = len(window.responses)
        concept_ids[row, :length] = torch.tensor(
            [vocabulary.encode(concept_id) for concept_id in window.concept_ids]
        )
        prev_responses[row, :length] = torch.tensor(shifted_previous_responses(window.responses))
        targets[row, :length] = torch.tensor(window.responses, dtype=torch.float)
        mask[row, :length] = True
        observation_ids.append(list(window.observation_ids))
        if graph is not None:
            prior: list[tuple[str, int]] = []
            for column, (concept_id, response) in enumerate(
                zip(window.concept_ids, window.responses, strict=True)
            ):
                graph[row, column] = torch.tensor(
                    prerequisite_summary(concept_id, prior, prerequisites)
                )
                prior.append((concept_id, response))
    return TracingBatch(
        concept_ids=concept_ids,
        prev_responses=prev_responses,
        targets=targets,
        mask=mask,
        graph_features=graph,
        observation_ids=observation_ids,
    )
