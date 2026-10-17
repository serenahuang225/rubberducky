"""Learner-scoped repository. Every query is filtered by the authenticated learner.

Routes receive a :class:`ScopedRepository` built from the request's credential, so there is
no code path that reads or writes learner records by a client-supplied learner ID. Records
owned by another learner are indistinguishable from records that do not exist.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, TypeVar

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models import (
    AssessmentRow,
    AttemptRow,
    Base,
    HintRow,
    LearnerRow,
    MemoryEntryRow,
    MisconceptionHypothesisRow,
    ObservationRow,
    SessionRow,
    TutorConfigurationRow,
)
from app.learner.pairing import LearnerScope, new_id
from app.schemas import (
    Assessment,
    Attempt,
    ContractModel,
    Hint,
    Learner,
    MemoryEntry,
    MisconceptionHypothesis,
    Observation,
    Session,
    TutorConfiguration,
)

RowT = TypeVar("RowT", bound=Base)

MAX_HISTORY_ITEMS = 50


class NotInScopeError(LookupError):
    """The record does not exist for this learner (it may exist for someone else)."""


class HistorySnapshot(ContractModel):
    """A bounded, learner-scoped view of recent records, each keeping its provenance."""

    schema_version: Literal["history-snapshot.v1"] = "history-snapshot.v1"
    learner: Learner
    limit: Annotated[int, Field(ge=1, le=MAX_HISTORY_ITEMS)]
    sessions: list[Session]
    attempts: list[Attempt]
    observations: list[Observation]
    hints: list[Hint]
    assessments: list[Assessment]
    hypotheses: list[MisconceptionHypothesis]
    memory_entries: list[MemoryEntry]


@dataclass
class ScopedRepository:
    db: DbSession
    scope: LearnerScope

    @property
    def learner_id(self) -> str:
        return self.scope.learner_id

    def _owned(self, model: type[RowT], record_id: str) -> RowT:
        row = self.db.execute(
            select(model).where(
                model.id == record_id,  # type: ignore[attr-defined]
                model.learner_id == self.learner_id,  # type: ignore[attr-defined]
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotInScopeError(model.__tablename__)
        return row

    def _recent(self, model: type[RowT], order_column: str, limit: int) -> list[RowT]:
        column = getattr(model, order_column)
        return list(
            self.db.execute(
                select(model)
                .where(model.learner_id == self.learner_id)  # type: ignore[attr-defined]
                .order_by(column.desc(), model.id)  # type: ignore[attr-defined]
                .limit(limit)
            ).scalars()
        )

    def learner(self) -> Learner:
        row = self.db.get(LearnerRow, self.learner_id)
        if row is None:
            raise NotInScopeError("learners")
        return Learner.model_validate(row)

    def tutor_configuration(self) -> TutorConfiguration | None:
        row = self.db.execute(
            select(TutorConfigurationRow).where(
                TutorConfigurationRow.learner_id == self.learner_id
            )
        ).scalar_one_or_none()
        return None if row is None else TutorConfiguration.model_validate(row)

    def require_session(self, session_id: str) -> SessionRow:
        """Resolve a (possibly nested) session reference within this learner's scope."""
        return self._owned(SessionRow, session_id)

    def require_attempt(self, attempt_id: str) -> AttemptRow:
        return self._owned(AttemptRow, attempt_id)

    def require_hypothesis(self, hypothesis_id: str) -> MisconceptionHypothesisRow:
        return self._owned(MisconceptionHypothesisRow, hypothesis_id)

    def require_observation(self, observation_id: str) -> ObservationRow:
        return self._owned(ObservationRow, observation_id)

    def get_session(self, session_id: str) -> Session:
        return Session.model_validate(self.require_session(session_id))

    def list_sessions(self, limit: int = MAX_HISTORY_ITEMS) -> list[Session]:
        rows = self._recent(SessionRow, "started_at", min(limit, MAX_HISTORY_ITEMS))
        return [Session.model_validate(row) for row in rows]

    def start_session(self, goal: str | None, now: datetime) -> Session:
        session = Session(
            id=new_id(),
            learner_id=self.learner_id,
            status="active",
            goal=goal,
            revision=0,
            provenance="submitted",
            started_at=now,
        )
        self.db.add(SessionRow(**session.model_dump()))
        self.db.flush()
        return session

    def end_session(self, session_id: str, now: datetime) -> Session:
        row = self.require_session(session_id)
        if row.status == "active":
            row.status = "ended"
            row.ended_at = now
            row.revision += 1
            self.db.flush()
        return Session.model_validate(row)

    def history(self, limit: int = 20) -> HistorySnapshot:
        bounded = max(1, min(limit, MAX_HISTORY_ITEMS))
        return HistorySnapshot(
            learner=self.learner(),
            limit=bounded,
            sessions=[
                Session.model_validate(r) for r in self._recent(SessionRow, "started_at", bounded)
            ],
            attempts=[
                Attempt.model_validate(r) for r in self._recent(AttemptRow, "started_at", bounded)
            ],
            observations=[
                Observation.model_validate(r)
                for r in self._recent(ObservationRow, "observed_at", bounded)
            ],
            hints=[Hint.model_validate(r) for r in self._recent(HintRow, "given_at", bounded)],
            assessments=[
                Assessment.model_validate(r)
                for r in self._recent(AssessmentRow, "assessed_at", bounded)
            ],
            hypotheses=[
                MisconceptionHypothesis.model_validate(r)
                for r in self._recent(MisconceptionHypothesisRow, "created_at", bounded)
            ],
            memory_entries=[
                MemoryEntry.model_validate(r)
                for r in self._recent(MemoryEntryRow, "created_at", bounded)
            ],
        )
