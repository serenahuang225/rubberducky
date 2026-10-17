"""Private local demo bootstrap, pairing redemption, credential revocation and profile."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import DbDep, ScopedRepo, SettingsDep
from app.api.errors import ApiError, ErrorEnvelope
from app.clock import utc_now
from app.db.repositories import MAX_HISTORY_ITEMS, HistorySnapshot
from app.learner.pairing import (
    FICTIONAL_NOTICE,
    IssuedCredential,
    PairingError,
    bootstrap_demo_learner,
    redeem_pairing_code,
    revoke_credential,
)
from app.learner.removal import delete_profile
from app.schemas import Learner, TutorConfiguration
from app.schemas.agency import RemovalReceipt

router = APIRouter(tags=["pairing"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    400: {"model": ErrorEnvelope},
}


class BootstrapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Annotated[str, Field(min_length=1, max_length=60)] = "Demo learner"


class RedeemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(min_length=8, max_length=32)]


class PairingResult(BaseModel):
    """Returned once. Store ``access_token`` privately on the device; it is never shown again."""

    schema_version: Literal["pairing-result.v1"] = "pairing-result.v1"
    learner: Learner
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - scheme name, not a secret
    notice: str = FICTIONAL_NOTICE


class MeResponse(BaseModel):
    schema_version: Literal["me.v1"] = "me.v1"
    learner: Learner
    tutor_configuration: TutorConfiguration | None
    notice: str = FICTIONAL_NOTICE


def _result(issued: IssuedCredential) -> PairingResult:
    return PairingResult(learner=issued.learner, access_token=issued.access_token)


@router.post(
    "/demo/bootstrap",
    response_model=PairingResult,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    summary="Create a new, empty fictional demo learner and pair this device",
)
def demo_bootstrap(body: BootstrapRequest, db: DbDep, settings: SettingsDep) -> PairingResult:
    if not settings.demo_bootstrap_enabled:
        raise ApiError(403, "bootstrap_disabled", "Demo bootstrap is disabled on this server.")
    issued = bootstrap_demo_learner(db, body.display_name, utc_now())
    db.commit()
    return _result(issued)


@router.post(
    "/pairing/redeem",
    response_model=PairingResult,
    responses=_ERRORS,
    summary="Redeem a one-time pairing code issued locally by `python -m app.cli pair`",
)
def pairing_redeem(body: RedeemRequest, db: DbDep) -> PairingResult:
    try:
        issued = redeem_pairing_code(db, body.code, utc_now())
    except PairingError as error:
        db.rollback()
        raise ApiError(
            400, "invalid_pairing_code", "The pairing code is invalid, expired or used."
        ) from error
    db.commit()
    return _result(issued)


@router.post(
    "/auth/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
    summary="Revoke the credential used for this request",
)
def auth_revoke(repo: ScopedRepo) -> None:
    revoke_credential(repo.db, repo.scope.credential_id, utc_now())
    repo.db.commit()


@router.get("/me", response_model=MeResponse, responses=_ERRORS, summary="Paired learner profile")
def me(repo: ScopedRepo) -> MeResponse:
    return MeResponse(learner=repo.learner(), tutor_configuration=repo.tutor_configuration())


@router.get(
    "/me/history",
    response_model=HistorySnapshot,
    responses=_ERRORS,
    summary="Bounded recent records for the paired learner, each labeled with provenance",
)
def my_history(
    repo: ScopedRepo, limit: Annotated[int, Query(ge=1, le=MAX_HISTORY_ITEMS)] = 20
) -> HistorySnapshot:
    return repo.history(limit)


@router.delete(
    "/me",
    response_model=RemovalReceipt,
    responses=_ERRORS,
    summary="Delete this learner profile and all of its records; every credential is revoked",
)
def delete_my_profile(
    repo: ScopedRepo,
    confirm: Annotated[Literal["delete-my-profile"], Query()],
) -> RemovalReceipt:
    """Requires ``?confirm=delete-my-profile``. Active local-store deletion only."""
    receipt = delete_profile(repo, utc_now())
    repo.db.commit()
    return receipt
