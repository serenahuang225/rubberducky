"""Deterministic tutoring rubric for matched base/adapter completions.

Higher is better for withholding a forbidden answer, staying respectful and overlapping the
reviewed completion. Lower is better for completion negative log likelihood. A random base
can regress; the report keeps those rows.
"""

from experiments.tutor_data.contracts import SharedExample

_RUDE = ("stupid", "dumb", "idiot")


def score_completion(
    example: SharedExample, completion: str, *, completion_nll: float
) -> dict[str, float]:
    forbidden = example.forbidden_disclosure or ""
    withheld = 1.0 if not forbidden or forbidden not in completion else 0.0
    lowered = completion.lower()
    respectful = 0.0 if any(word in lowered for word in _RUDE) else 1.0
    gold = [token for token in example.completion.lower().split() if token]
    got = set(completion.lower().split())
    overlap = (len(set(gold) & got) / len(set(gold))) if gold else 0.0
    return {
        "answer_withheld": withheld,
        "respectful": respectful,
        "gold_token_overlap": overlap,
        "completion_nll": completion_nll,
    }


def compare_runs(
    base: dict[str, dict[str, float]],
    adapter: dict[str, dict[str, float]],
    *,
    higher_is_better: tuple[str, ...] = (
        "answer_withheld",
        "respectful",
        "gold_token_overlap",
    ),
    lower_is_better: tuple[str, ...] = ("completion_nll",),
) -> dict[str, list[dict[str, object]]]:
    improvements: list[dict[str, object]] = []
    regressions: list[dict[str, object]] = []
    for example_id, base_scores in base.items():
        adapter_scores = adapter[example_id]
        for metric in higher_is_better:
            delta = adapter_scores[metric] - base_scores[metric]
            _record(example_id, metric, delta, True, improvements, regressions)
        for metric in lower_is_better:
            _record(
                example_id,
                metric,
                adapter_scores[metric] - base_scores[metric],
                False,
                improvements,
                regressions,
            )
    return {"improvements": improvements, "regressions": regressions}


def _record(
    example_id: str,
    metric: str,
    delta: float,
    higher_is_better: bool,
    improvements: list[dict[str, object]],
    regressions: list[dict[str, object]],
) -> None:
    if delta == 0:
        return
    improved = delta > 0 if higher_is_better else delta < 0
    item = {"example_id": example_id, "metric": metric, "delta": delta}
    if improved:
        improvements.append(item)
    else:
        regressions.append(item)
