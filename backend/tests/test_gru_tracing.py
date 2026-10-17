"""Causal GRU tracing: shifted history, masks, splits and a real tiny optimizer run.

These tests exercise PyTorch tensors and the common predictor interface. They do not treat a
synthetic loss as calibrated mastery or as evidence that a learner improved.
"""

import math
import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import torch

from app.tracing.contracts import PREDICTION_TARGET, TracingEvent
from app.tracing.gru import (
    GRAPH_FEATURE_DIM,
    CausalConceptGRU,
    ConceptVocabulary,
    GRUModelConfig,
    GRUPredictor,
    load_checkpoint,
    masked_response_loss,
    prerequisite_summary,
    save_checkpoint,
    shifted_previous_responses,
)
from app.tracing.predictor import SnapshotMismatchError
from experiments.tracing.metrics import score_predictions
from experiments.tracing.train import train_synthetic
from experiments.tracing.windows import (
    SequenceExample,
    SequenceWindow,
    build_windows,
    collate_windows,
    split_learners,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _stamp(index: int) -> datetime:
    return START + timedelta(minutes=index)


def _example(
    observation_id: str,
    learner_id: str,
    concept_id: str,
    correct: int,
    index: int,
    *,
    eligible: bool = True,
    problem: str = "problem.p0",
) -> SequenceExample:
    return SequenceExample(
        observation_id=observation_id,
        learner_id=learner_id,
        concept_id=concept_id,
        correct=correct,
        observed_at=_stamp(index),
        opportunity_key=f"{concept_id}|{problem}",
        eligible=eligible,
    )


def _window() -> SequenceWindow:
    return SequenceWindow(
        learner_id="learner.a",
        observation_ids=("obs.0", "obs.1", "obs.2"),
        concept_ids=("concept.c0", "concept.c1", "concept.c0"),
        responses=(1, 0, 1),
        observed_at=(_stamp(0), _stamp(1), _stamp(2)),
    )


def _vocab() -> ConceptVocabulary:
    return ConceptVocabulary(["concept.c0", "concept.c1", "concept.c2"])


def _model(*, graph: bool) -> CausalConceptGRU:
    torch.manual_seed(5)
    config = GRUModelConfig(
        embed_dim=4, hidden_dim=4, num_layers=1, use_graph_features=graph
    )
    return CausalConceptGRU(_vocab().size, config)


def test_shifted_history_excludes_the_target_response() -> None:
    shifted = shifted_previous_responses([1, 0, 1])
    assert shifted == [0, 2, 1]
    assert shifted[0] == 0
    assert shifted[1] == 1 + 1
    assert shifted[2] == 1 + 0


def test_future_and_target_perturbation_do_not_change_earlier_predictions() -> None:
    vocabulary = _vocab()
    model = _model(graph=False)
    model.eval()
    original = _window()
    flipped_target = SequenceWindow(
        learner_id=original.learner_id,
        observation_ids=original.observation_ids,
        concept_ids=original.concept_ids,
        responses=(1, 1, 1),
        observed_at=original.observed_at,
    )
    prerequisites = {"concept.c1": ("concept.c0",), "concept.c0": (), "concept.c2": ()}
    first = collate_windows(
        [original], vocabulary, use_graph_features=False, prerequisites=prerequisites
    )
    second = collate_windows(
        [flipped_target], vocabulary, use_graph_features=False, prerequisites=prerequisites
    )
    # The edited response is the target at index 1. It may enter the NEXT step only.
    assert torch.equal(first.prev_responses[:, :2], second.prev_responses[:, :2])
    assert not torch.equal(first.prev_responses[:, 2], second.prev_responses[:, 2])
    with torch.no_grad():
        logits_first = model(first.concept_ids, first.prev_responses, first.mask)
        logits_second = model(second.concept_ids, second.prev_responses, second.mask)
    assert torch.equal(logits_first[:, :2], logits_second[:, :2])

    longer = SequenceWindow(
        learner_id=original.learner_id,
        observation_ids=(*original.observation_ids, "obs.future"),
        concept_ids=(*original.concept_ids, "concept.c2"),
        responses=(*original.responses, 0),
        observed_at=(*original.observed_at, _stamp(3)),
    )
    future = collate_windows(
        [longer], vocabulary, use_graph_features=False, prerequisites=prerequisites
    )
    with torch.no_grad():
        logits_future = model(future.concept_ids, future.prev_responses, future.mask)
    assert torch.equal(logits_first, logits_future[:, :3])


def test_padding_does_not_change_valid_predictions_or_masked_loss() -> None:
    vocabulary = _vocab()
    model = _model(graph=False)
    model.eval()
    window = _window()
    batch = collate_windows(
        [window], vocabulary, use_graph_features=False, prerequisites={}
    )
    padded_concepts = torch.nn.functional.pad(batch.concept_ids, (0, 3))
    padded_prev = torch.nn.functional.pad(batch.prev_responses, (0, 3))
    padded_targets = torch.nn.functional.pad(batch.targets, (0, 3), value=1.0)
    padded_mask = torch.nn.functional.pad(batch.mask, (0, 3), value=False)
    # Garbage in the padded slots must not matter.
    padded_concepts[:, 3:] = 4
    padded_prev[:, 3:] = 2
    with torch.no_grad():
        short = model(batch.concept_ids, batch.prev_responses, batch.mask)
        long = model(padded_concepts, padded_prev, padded_mask)
        loss_short = masked_response_loss(short, batch.targets, batch.mask)
        loss_long = masked_response_loss(long, padded_targets, padded_mask)
    assert torch.allclose(short, long[:, :3])
    assert torch.allclose(loss_short, loss_long)
    unmasked = torch.nn.functional.binary_cross_entropy_with_logits(long, padded_targets)
    assert not torch.allclose(unmasked, loss_long)


def test_learners_are_split_before_windows_and_stay_chronological() -> None:
    examples = [
        _example("obs.b0", "learner.b", "concept.c0", 1, 0),
        _example("obs.a1", "learner.a", "concept.c1", 0, 1),
        _example("obs.b1", "learner.b", "concept.c1", 0, 2),
        _example("obs.a0", "learner.a", "concept.c0", 1, 3, problem="problem.p1"),
        _example("obs.c0", "learner.c", "concept.c2", 1, 4),
    ]
    # Deliberately out of order for learner.a: index 3 is earlier in time than index 1?
    # observed_at follows the index argument, so obs.a0 is later. Swap times below.
    examples[3] = SequenceExample(
        observation_id="obs.a0",
        learner_id="learner.a",
        concept_id="concept.c0",
        correct=1,
        observed_at=_stamp(0),
        opportunity_key="concept.c0|problem.p1",
        eligible=True,
    )
    split = split_learners(["learner.b", "learner.a", "learner.c"], heldout_count=1, seed=11)
    assert set(split.train_ids).isdisjoint(split.heldout_ids)
    assert set(split.train_ids) | set(split.heldout_ids) == {"learner.a", "learner.b", "learner.c"}
    windows = build_windows(examples, set(split.train_ids), window=8, stride=8)
    assert windows
    assert {window.learner_id for window in windows}.isdisjoint(split.heldout_ids)
    heldout_ids = {row.observation_id for row in examples if row.learner_id in split.heldout_ids}
    assert heldout_ids.isdisjoint(
        {observation_id for window in windows for observation_id in window.observation_ids}
    )
    for window in windows:
        assert window.observed_at == tuple(sorted(window.observed_at))
        assert len({window.learner_id}) == 1
    learner_a = next(window for window in windows if window.learner_id == "learner.a")
    assert learner_a.observation_ids[0] == "obs.a0"


def test_graph_summary_uses_prior_interactions_only_and_is_optional() -> None:
    prerequisites = {"concept.c1": ("concept.c0",), "concept.c0": ()}
    assert prerequisite_summary("concept.c1", [], prerequisites)[0] == 0.0
    seen = prerequisite_summary("concept.c1", [("concept.c0", 1)], prerequisites)
    unseen = prerequisite_summary("concept.c1", [("concept.c2", 1)], prerequisites)
    assert seen[0] == 1.0
    assert unseen[0] == 0.0
    assert len(seen) == GRAPH_FEATURE_DIM

    vocabulary = _vocab()
    window = SequenceWindow(
        learner_id="learner.a",
        observation_ids=("obs.0", "obs.1"),
        concept_ids=("concept.c0", "concept.c1"),
        responses=(1, 0),
        observed_at=(_stamp(0), _stamp(1)),
    )
    flipped = SequenceWindow(
        learner_id=window.learner_id,
        observation_ids=window.observation_ids,
        concept_ids=window.concept_ids,
        responses=(0, 0),
        observed_at=window.observed_at,
    )
    batch = collate_windows(
        [window], vocabulary, use_graph_features=True, prerequisites=prerequisites
    )
    flipped_batch = collate_windows(
        [flipped], vocabulary, use_graph_features=True, prerequisites=prerequisites
    )
    assert batch.graph_features is not None and flipped_batch.graph_features is not None
    assert torch.equal(batch.graph_features[:, 0], flipped_batch.graph_features[:, 0])
    assert not torch.equal(batch.graph_features[:, 1], flipped_batch.graph_features[:, 1])

    model_off = _model(graph=False)
    model_off.eval()
    concepts = torch.tensor([[2, 3]])
    prev = torch.tensor([[0, 2]])
    mask = torch.tensor([[True, True]])
    zeros = torch.zeros(1, 2, GRAPH_FEATURE_DIM)
    ones = torch.ones(1, 2, GRAPH_FEATURE_DIM)
    with torch.no_grad():
        assert torch.equal(
            model_off(concepts, prev, mask, zeros), model_off(concepts, prev, mask, ones)
        )
    torch.manual_seed(5)
    model_on = CausalConceptGRU(
        vocabulary.size, GRUModelConfig(embed_dim=4, hidden_dim=4, use_graph_features=True)
    )
    with torch.no_grad():
        model_on.graph_proj.weight.fill_(0.25)  # type: ignore[union-attr]
        model_on.graph_proj.bias.zero_()  # type: ignore[union-attr]
    model_on.eval()
    with torch.no_grad():
        assert not torch.equal(
            model_on(concepts, prev, mask, zeros), model_on(concepts, prev, mask, ones)
        )
    assert model_on.gru.bidirectional is False
    assert model_off.graph_proj is None


def test_cold_start_unseen_concept_reset_and_checkpoint(tmp_path) -> None:
    vocabulary = _vocab()
    model = _model(graph=False)
    model.eval()
    predictor = GRUPredictor("learner.a", model, vocabulary)
    cold = predictor.predict_before_observation("concept.c0")
    missing = predictor.predict_before_observation("concept.missing")
    assert cold.target == PREDICTION_TARGET
    assert cold.latent_knowledge is None
    assert missing.latent_knowledge is None
    assert predictor.metadata().has_latent_state is False
    assert predictor.metadata().calibrated is False
    assert math.isfinite(cold.p_correct) and math.isfinite(missing.p_correct)
    assert vocabulary.encode("concept.missing") == 1

    event = TracingEvent.model_validate(
        {
            "observation_id": "obs.counted",
            "learner_id": "learner.a",
            "concept_id": "concept.c0",
            "correct": True,
            "source_type": "assessment",
            "source_id": "assessment.counted",
            "assessment_id": "assessment.counted",
            "assessment_kind": "practice_check",
            "problem_id": "problem.p0",
            "opportunity_key": "concept.c0|problem.p0",
            "eligible": True,
            "provenance": "fictional_seed",
            "observed_at": _stamp(0),
        }
    )
    counted = predictor.observe(event)
    assert counted.status == "counted"
    assert counted.prediction is not None and counted.prediction.latent_knowledge is None
    after = predictor.predict_before_observation("concept.c0")
    snapshot = predictor.save()
    predictor.reset()
    assert predictor.predict_before_observation("concept.c0").opportunities_counted == 0
    assert predictor.predict_before_observation("concept.c0").p_correct == cold.p_correct
    predictor.load(snapshot)
    restored = predictor.predict_before_observation("concept.c0")
    assert restored.opportunities_counted == after.opportunities_counted
    assert restored.p_correct == after.p_correct
    with_other = GRUPredictor("learner.b", model, vocabulary)
    try:
        with_other.load(snapshot)
    except SnapshotMismatchError:
        pass
    else:
        raise AssertionError("a snapshot from another learner must be refused")

    save_checkpoint(tmp_path / "gru", model, vocabulary, model.config)
    with torch.no_grad():
        model.output.bias.add_(1.0)
    loaded, loaded_vocab, loaded_config = load_checkpoint(tmp_path / "gru")
    loaded.eval()
    assert loaded_vocab.encode("concept.c0") == vocabulary.encode("concept.c0")
    assert loaded_config.use_graph_features is False
    concepts = torch.tensor([[vocabulary.encode("concept.c0")]])
    prev = torch.zeros(1, 1, dtype=torch.long)
    mask = torch.ones(1, 1, dtype=torch.bool)
    fresh = _model(graph=False)
    fresh.eval()
    with torch.no_grad():
        assert torch.allclose(loaded(concepts, prev, mask), fresh(concepts, prev, mask))


def test_auroc_is_undefined_when_only_one_class_is_present() -> None:
    scores = score_predictions([0.2, 0.8, 0.4], [1, 1, 1])
    assert scores.auroc is None
    assert scores.auroc_status == "undefined"
    assert scores.count == 3
    assert math.isfinite(scores.log_loss) and math.isfinite(scores.brier)
    both = score_predictions([0.1, 0.9], [0, 1])
    assert both.auroc_status == "defined"
    assert both.auroc == 1.0


def test_synthetic_training_updates_parameters_and_matches_bkt_ids(tmp_path) -> None:
    report = train_synthetic(
        tmp_path / "run",
        seed=17,
        epochs=1,
        n_train=2,
        n_heldout=1,
        length=4,
        embed_dim=4,
        hidden_dim=4,
        graph_features=False,
    )
    assert report["execution_status"] == "executed"
    assert report["parameter_l1_delta"] > 0
    assert report["loss_finite"] is True
    assert report["threads"] <= 2
    assert set(report["train_learner_ids"]).isdisjoint(report["heldout_learner_ids"])
    assert report["target_ids_equal"] is True
    assert report["gru"]["target_ids"] == report["bkt"]["target_ids"]
    assert report["gru"]["target_ids"]
    assert "obs.ineligible" not in report["gru"]["target_ids"]
    assert "obs.duplicate" not in report["gru"]["target_ids"]
    assert report["reload"]["matched"] is True
    assert report["reload"]["max_abs_diff"] <= report["reload"]["atol"]
    assert report["gru"]["calibration"]
    assert (tmp_path / "run" / "model.pt").is_file()
    assert (tmp_path / "run" / "config.json").is_file()
    assert (tmp_path / "run" / "vocabulary.json").is_file()
    card = (tmp_path / "run" / "model-card.md").read_text()
    assert "synthetic" in card.lower()
    assert "not calibrated mastery" in card.lower()
