"""Proper scoring rules for next-response probabilities.

AUROC is omitted unless both outcome classes are present. These scores describe a prediction
file; they are not a calibration certificate.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int
    positives: int
    predicted_sum: float

    def to_json(self) -> dict[str, float | int]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "count": self.count,
            "positives": self.positives,
            "predicted_sum": self.predicted_sum,
        }


@dataclass(frozen=True)
class PredictionScores:
    count: int
    log_loss: float
    brier: float
    calibration: tuple[CalibrationBin, ...]
    auroc: float | None
    auroc_status: Literal["defined", "undefined"]
    auroc_reason: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "count": self.count,
            "log_loss": self.log_loss,
            "brier": self.brier,
            "calibration": [item.to_json() for item in self.calibration],
            "auroc": self.auroc,
            "auroc_status": self.auroc_status,
            "auroc_reason": self.auroc_reason,
        }


def score_predictions(
    probabilities: Sequence[float], labels: Sequence[int], *, bins: int = 5
) -> PredictionScores:
    if bins < 1:
        raise ValueError("bins must be positive")
    if len(probabilities) != len(labels) or not probabilities:
        raise ValueError("probabilities and labels must be the same non-empty length")
    eps = 1e-6
    log_loss = 0.0
    brier = 0.0
    pairs: list[tuple[float, int]] = []
    for probability, label in zip(probabilities, labels, strict=True):
        if label not in (0, 1) or not math.isfinite(probability):
            raise ValueError("labels must be 0 or 1 and probabilities must be finite")
        clipped = min(1.0 - eps, max(eps, probability))
        log_loss += -(label * math.log(clipped) + (1 - label) * math.log(1.0 - clipped))
        brier += (probability - label) ** 2
        pairs.append((probability, label))
    count = len(pairs)
    calibration: list[CalibrationBin] = []
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        chosen = [
            (probability, label)
            for probability, label in pairs
            if (lower <= probability < upper) or (index == bins - 1 and probability == upper)
        ]
        calibration.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(chosen),
                positives=sum(label for _probability, label in chosen),
                predicted_sum=sum(probability for probability, _label in chosen),
            )
        )
    if len({label for _probability, label in pairs}) < 2:
        return PredictionScores(
            count=count,
            log_loss=log_loss / count,
            brier=brier / count,
            calibration=tuple(calibration),
            auroc=None,
            auroc_status="undefined",
            auroc_reason="both outcome classes are required",
        )
    return PredictionScores(
        count=count,
        log_loss=log_loss / count,
        brier=brier / count,
        calibration=tuple(calibration),
        auroc=_auroc(pairs),
        auroc_status="defined",
        auroc_reason=None,
    )


def _auroc(pairs: Sequence[tuple[float, int]]) -> float:
    order = sorted(range(len(pairs)), key=lambda index: pairs[index][0])
    ranks = [0.0] * len(pairs)
    cursor = 0
    while cursor < len(order):
        end = cursor
        while end + 1 < len(order) and pairs[order[end + 1]][0] == pairs[order[cursor]][0]:
            end += 1
        average = (cursor + end) / 2.0 + 1.0
        for index in range(cursor, end + 1):
            ranks[order[index]] = average
        cursor = end + 1
    positives = [index for index, (_probability, label) in enumerate(pairs) if label == 1]
    n_pos = len(positives)
    n_neg = len(pairs) - n_pos
    sum_ranks = sum(ranks[index] for index in positives)
    return (sum_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
