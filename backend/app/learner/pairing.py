"""Local demo pairing and bearer-credential resolution.

Bearer tokens and pairing codes are random secrets returned exactly once; the database only
stores their SHA-256 digests. A learner's scope is always derived from a presented token,
never from a learner ID supplied by the client. This is a private local prototype, not a
production account or authentication system.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.db.models import CredentialRow, LearnerRow, PairingCodeRow
from app.schemas import Learner

TOKEN_PREFIX = "rdk_"  # noqa: S105 - public prefix, not a secret
MAX_TOKEN_LENGTH = 128
# Unambiguous uppercase alphabet for codes a person may type from a terminal.
PAIRING_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PAIRING_CODE_LENGTH = 12
FICTIONAL_NOTICE = "Fictional demo learner for a private local prototype; not a real person."


@dataclass(frozen=True)
class LearnerScope:
    learner_id: str
    credential_id: str


@dataclass(frozen=True)
class IssuedCredential:
    learner: Learner
    credential_id: str
    access_token: str


class PairingError(Exception):
    pass


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_id() -> str:
    return str(uuid.uuid4())


def _issue_credential(db: DbSession, learner_id: str, label: str, now: datetime) -> tuple[str, str]:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    credential_id = new_id()
    db.add(
        CredentialRow(
            id=credential_id,
            learner_id=learner_id,
            token_hash=digest(token),
            label=label,
            created_at=now,
            revoked_at=None,
        )
    )
    return credential_id, token


def bootstrap_demo_learner(db: DbSession, display_name: str, now: datetime) -> IssuedCredential:
    """Create a new fictional demo learner and its first credential.

    The new learner starts empty; bootstrap never returns or links any existing history.
    """
    learner = Learner(
        id=new_id(),
        display_name=display_name,
        is_fictional=True,
        provenance="submitted",
        created_at=now,
    )
    db.add(LearnerRow(**learner.model_dump()))
    db.flush()
    credential_id, token = _issue_credential(db, learner.id, "demo bootstrap", now)
    return IssuedCredential(learner=learner, credential_id=credential_id, access_token=token)


def issue_pairing_code(db: DbSession, learner_id: str, now: datetime, ttl: timedelta) -> str:
    if db.get(LearnerRow, learner_id) is None:
        raise PairingError("unknown learner")
    code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))
    db.add(
        PairingCodeRow(
            id=new_id(),
            learner_id=learner_id,
            code_hash=digest(code),
            created_at=now,
            expires_at=now + ttl,
            redeemed_at=None,
        )
    )
    return code


def normalize_pairing_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch not in " -")


def redeem_pairing_code(db: DbSession, code: str, now: datetime) -> IssuedCredential:
    normalized = normalize_pairing_code(code)
    # Single conditional UPDATE so two concurrent redemptions cannot both succeed.
    result = db.execute(
        update(PairingCodeRow)
        .where(
            PairingCodeRow.code_hash == digest(normalized),
            PairingCodeRow.redeemed_at.is_(None),
            PairingCodeRow.expires_at > now,
        )
        .values(redeemed_at=now)
        .returning(PairingCodeRow.learner_id)
    )
    learner_id = result.scalar_one_or_none()
    if learner_id is None:
        raise PairingError("invalid, expired or already used pairing code")
    row = db.get(LearnerRow, learner_id)
    if row is None:
        raise PairingError("invalid, expired or already used pairing code")
    credential_id, token = _issue_credential(db, learner_id, "paired device", now)
    return IssuedCredential(
        learner=Learner.model_validate(row), credential_id=credential_id, access_token=token
    )


def resolve_token(db: DbSession, token: str) -> LearnerScope | None:
    if not token.startswith(TOKEN_PREFIX) or len(token) > MAX_TOKEN_LENGTH:
        return None
    row = db.execute(
        select(CredentialRow.id, CredentialRow.learner_id).where(
            CredentialRow.token_hash == digest(token), CredentialRow.revoked_at.is_(None)
        )
    ).one_or_none()
    if row is None:
        return None
    return LearnerScope(learner_id=row.learner_id, credential_id=row.id)


def revoke_credential(db: DbSession, credential_id: str, now: datetime) -> None:
    db.execute(
        update(CredentialRow)
        .where(CredentialRow.id == credential_id, CredentialRow.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_all_for_learner(db: DbSession, learner_id: str, now: datetime) -> int:
    result = db.execute(
        update(CredentialRow)
        .where(CredentialRow.learner_id == learner_id, CredentialRow.revoked_at.is_(None))
        .values(revoked_at=now)
        .returning(CredentialRow.id)
    )
    return len(result.all())
