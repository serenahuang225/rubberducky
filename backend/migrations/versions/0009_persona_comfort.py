"""Separate comfort-override timestamp so comfort edits never look like a persona change.

Revision ID: 0009_persona_comfort
Revises: 0008_memory_agency
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_persona_comfort"
down_revision: str | None = "0008_memory_agency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tutor_configurations") as batch:
        batch.add_column(sa.Column("comfort_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tutor_configurations") as batch:
        batch.drop_column("comfort_updated_at")
