"""Statistical learner tracing: NumPy BKT behind a common predictor interface.

Only explicit, independent, verified opportunities update the BKT stream; every other raw
event is kept as evidence and reported with the reason it was not counted.
"""

from app.tracing.contracts import (
    ALGORITHM,
    ALGORITHM_VERSION,
    DEFAULT_PARAMETERS,
    ELIGIBILITY_VERSION,
    PREDICTION_TARGET,
    BKTParameters,
    BKTSnapshot,
    ReplayReport,
    ResponsePrediction,
    TracingEvent,
    TracingUpdate,
)
from app.tracing.predictor import BKTPredictor, SnapshotMismatchError, StatisticalPredictor

__all__ = [
    "ALGORITHM",
    "ALGORITHM_VERSION",
    "DEFAULT_PARAMETERS",
    "ELIGIBILITY_VERSION",
    "PREDICTION_TARGET",
    "BKTParameters",
    "BKTPredictor",
    "BKTSnapshot",
    "ReplayReport",
    "ResponsePrediction",
    "SnapshotMismatchError",
    "StatisticalPredictor",
    "TracingEvent",
    "TracingUpdate",
]
