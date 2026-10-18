"""Seeded synthetic GRU training and the held-out comparison against BKT.

Training stays in this command. The API process does not import it.
"""

import json
import resource
import time
from pathlib import Path

import torch

from app.tracing.contracts import DEFAULT_PARAMETERS
from app.tracing.gru import (
    RELOAD_ATOL,
    CausalConceptGRU,
    ConceptVocabulary,
    GRUModelConfig,
    GRUPredictor,
    load_checkpoint,
    masked_response_loss,
    save_checkpoint,
)
from app.tracing.predictor import BKTPredictor
from experiments.threads import limit_numerical_threads
from experiments.tracing.card import render_gru_card
from experiments.tracing.metrics import score_predictions
from experiments.tracing.synthetic import (
    SyntheticCorpus,
    SyntheticEvent,
    generate_synthetic_corpus,
    to_sequence_example,
    to_tracing_event,
)
from experiments.tracing.windows import build_windows, collate_windows

LIMITATION = (
    "Synthetic execution only. Not calibrated mastery, not a learning gain, "
    "and not a comparison of educational quality."
)


def train_synthetic(
    output: Path,
    *,
    seed: int,
    epochs: int,
    n_train: int = 4,
    n_heldout: int = 2,
    n_concepts: int = 3,
    length: int = 6,
    embed_dim: int = 8,
    hidden_dim: int = 8,
    graph_features: bool = False,
    learning_rate: float = 0.05,
    threads: int = 2,
) -> dict[str, object]:
    """Train on synthetic train learners and score the same held-out targets as BKT."""

    applied_threads = limit_numerical_threads(threads)
    started = time.perf_counter()
    torch.manual_seed(seed)
    corpus = generate_synthetic_corpus(
        seed=seed,
        n_train=n_train,
        n_heldout=n_heldout,
        n_concepts=n_concepts,
        length=length,
    )
    examples = [to_sequence_example(event) for event in corpus.events]
    # The split already exists. Windows are built only from the training learners.
    train_windows = build_windows(examples, set(corpus.train_ids), window=length, stride=length)
    leaked = [
        window.learner_id
        for window in train_windows
        if window.learner_id in corpus.heldout_ids
    ]
    if leaked:
        raise RuntimeError(f"held-out learners entered training windows: {leaked}")
    vocabulary = ConceptVocabulary(list(corpus.concept_ids))
    config = GRUModelConfig(
        embed_dim=embed_dim, hidden_dim=hidden_dim, use_graph_features=graph_features
    )
    model = CausalConceptGRU(vocabulary.size, config)
    before = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    losses: list[float] = []
    model.train()
    for _epoch in range(epochs):
        batch = collate_windows(
            train_windows,
            vocabulary,
            use_graph_features=graph_features,
            prerequisites=corpus.prerequisites,
        )
        optimizer.zero_grad()
        logits = model(batch.concept_ids, batch.prev_responses, batch.mask, batch.graph_features)
        loss = masked_response_loss(logits, batch.targets, batch.mask)
        if not torch.isfinite(loss):
            raise RuntimeError("GRU loss was not finite")
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()
        losses.append(float(loss.detach()))
    delta = 0.0
    for name, parameter in model.named_parameters():
        delta += float((parameter.detach() - before[name]).abs().sum())
    model.eval()
    output.mkdir(parents=True, exist_ok=True)
    save_checkpoint(output, model, vocabulary, config)
    run = {
        "seed": seed,
        "epochs": epochs,
        "n_train": n_train,
        "n_heldout": n_heldout,
        "n_concepts": n_concepts,
        "length": length,
        "embed_dim": embed_dim,
        "hidden_dim": hidden_dim,
        "graph_features": graph_features,
        "learning_rate": learning_rate,
        "threads": applied_threads,
    }
    (output / "run.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
    reloaded, _, _ = load_checkpoint(output)
    reload_diff = _reload_difference(corpus, model, reloaded, vocabulary, graph_features)
    report = _comparison_report(
        corpus,
        model,
        vocabulary,
        graph_features=graph_features,
        parameter_l1_delta=delta,
        losses=losses,
        reload_diff=reload_diff,
        elapsed_seconds=time.perf_counter() - started,
        threads=applied_threads,
        embed_dim=embed_dim,
        hidden_dim=hidden_dim,
        epochs=epochs,
    )
    (output / "metrics.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (output / "model-card.md").write_text(render_gru_card(report))
    return report


def evaluate_checkpoint(checkpoint: Path, *, threads: int = 2) -> dict[str, object]:
    """Score a saved GRU again. Does not train."""

    limit_numerical_threads(threads)
    run = json.loads((checkpoint / "run.json").read_text())
    model, vocabulary, config = load_checkpoint(checkpoint)
    reloaded, _, _ = load_checkpoint(checkpoint)
    corpus = generate_synthetic_corpus(
        seed=int(run["seed"]),
        n_train=int(run["n_train"]),
        n_heldout=int(run["n_heldout"]),
        n_concepts=int(run["n_concepts"]),
        length=int(run["length"]),
    )
    reloaded_diff = _reload_difference(
        corpus, model, reloaded, vocabulary, bool(config.use_graph_features)
    )
    report = _comparison_report(
        corpus,
        model,
        vocabulary,
        graph_features=bool(config.use_graph_features),
        parameter_l1_delta=None,
        losses=[],
        reload_diff=reloaded_diff,
        elapsed_seconds=0.0,
        threads=threads,
        embed_dim=config.embed_dim,
        hidden_dim=config.hidden_dim,
        epochs=int(run["epochs"]),
    )
    report["execution_status"] = "evaluated"
    return report


def _reload_difference(
    corpus: SyntheticCorpus,
    trained: CausalConceptGRU,
    reloaded: CausalConceptGRU,
    vocabulary: ConceptVocabulary,
    graph_features: bool,
) -> float:
    examples = [to_sequence_example(event) for event in corpus.events]
    windows = build_windows(examples, set(corpus.heldout_ids), window=corpus.length + 2, stride=1)
    if not windows:
        raise RuntimeError("held-out split produced no windows")
    batch = collate_windows(
        windows,
        vocabulary,
        use_graph_features=graph_features,
        prerequisites=corpus.prerequisites,
    )
    trained.eval()
    reloaded.eval()
    with torch.no_grad():
        first = torch.sigmoid(
            trained(batch.concept_ids, batch.prev_responses, batch.mask, batch.graph_features)
        )
        second = torch.sigmoid(
            reloaded(batch.concept_ids, batch.prev_responses, batch.mask, batch.graph_features)
        )
    return float((first - second).abs().max())


def _comparison_report(
    corpus: SyntheticCorpus,
    model: CausalConceptGRU,
    vocabulary: ConceptVocabulary,
    *,
    graph_features: bool,
    parameter_l1_delta: float | None,
    losses: list[float],
    reload_diff: float,
    elapsed_seconds: float,
    threads: int,
    embed_dim: int,
    hidden_dim: int,
    epochs: int,
) -> dict[str, object]:
    gru_ids: list[str] = []
    bkt_ids: list[str] = []
    gru_probabilities: list[float] = []
    bkt_probabilities: list[float] = []
    labels: list[int] = []
    by_learner: dict[str, list[SyntheticEvent]] = {
        learner_id: [] for learner_id in corpus.heldout_ids
    }
    for event in corpus.events:
        if event.learner_id in by_learner:
            by_learner[event.learner_id].append(event)
    for learner_id in corpus.heldout_ids:
        gru = GRUPredictor(
            learner_id, model, vocabulary, prerequisites=corpus.prerequisites
        )
        bkt = BKTPredictor(learner_id, DEFAULT_PARAMETERS)
        ordered = sorted(
            by_learner[learner_id],
            key=lambda item: (item.observed_at, item.observation_id),
        )
        for event in ordered:
            tracing_event = to_tracing_event(event)
            gru_update = gru.observe(tracing_event)
            bkt_update = bkt.observe(tracing_event)
            if gru_update.status != bkt_update.status:
                raise RuntimeError(
                    f"{event.observation_id} status {gru_update.status} != {bkt_update.status}"
                )
            if gru_update.status != "counted":
                continue
            if gru_update.prediction is None or bkt_update.prediction is None:
                raise RuntimeError("counted event is missing a prediction")
            gru_ids.append(event.observation_id)
            bkt_ids.append(event.observation_id)
            gru_probabilities.append(gru_update.prediction.p_correct)
            bkt_probabilities.append(bkt_update.prediction.p_correct)
            labels.append(event.correct)
    gru_scores = score_predictions(gru_probabilities, labels).to_json()
    bkt_scores = score_predictions(bkt_probabilities, labels).to_json()
    gru_scores["target_ids"] = gru_ids
    bkt_scores["target_ids"] = bkt_ids
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "execution_status": "executed",
        "seed": corpus.seed,
        "epochs": epochs,
        "embed_dim": embed_dim,
        "hidden_dim": hidden_dim,
        "graph_features": graph_features,
        "threads": threads,
        "train_learner_ids": list(corpus.train_ids),
        "heldout_learner_ids": list(corpus.heldout_ids),
        "parameter_l1_delta": parameter_l1_delta,
        "losses": losses,
        "loss_finite": all(math_isfinite(value) for value in losses) if losses else False,
        "target_ids_equal": gru_ids == bkt_ids,
        "gru": gru_scores,
        "bkt": bkt_scores,
        "reload": {
            "max_abs_diff": reload_diff,
            "atol": RELOAD_ATOL,
            "matched": reload_diff <= RELOAD_ATOL,
        },
        "elapsed_seconds": elapsed_seconds,
        "max_rss_bytes": rss,
        "limitations": LIMITATION,
    }


def math_isfinite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
