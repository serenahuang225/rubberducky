"""Replace tone personalities with the five rubber ducks.

Revision ID: 0012_duck_personalities
Revises: 0011_media_events
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_duck_personalities"
down_revision: str | None = "0011_media_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "personality"
_DUCKS = "personality IN ('vincent', 'zeeshan', 'tony', 'janelle', 'mary')"
_TONES = "personality IN ('gentle', 'matter_of_fact', 'playful', 'mildly_sassy')"


def upgrade() -> None:
    with op.batch_alter_table("tutor_configurations") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
    op.execute(
        sa.text(
            """
            UPDATE tutor_configurations
            SET personality = CASE personality
                WHEN 'gentle' THEN 'janelle'
                WHEN 'matter_of_fact' THEN 'vincent'
                WHEN 'playful' THEN 'tony'
                WHEN 'mildly_sassy' THEN 'zeeshan'
                ELSE personality
            END
            """
        )
    )
    with op.batch_alter_table("tutor_configurations") as batch:
        batch.create_check_constraint(_CONSTRAINT, _DUCKS)


def downgrade() -> None:
    with op.batch_alter_table("tutor_configurations") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
    op.execute(
        sa.text(
            """
            UPDATE tutor_configurations
            SET personality = CASE personality
                WHEN 'janelle' THEN 'gentle'
                WHEN 'vincent' THEN 'matter_of_fact'
                WHEN 'tony' THEN 'playful'
                WHEN 'zeeshan' THEN 'mildly_sassy'
                WHEN 'mary' THEN 'gentle'
                ELSE personality
            END
            """
        )
    )
    with op.batch_alter_table("tutor_configurations") as batch:
        batch.create_check_constraint(_CONSTRAINT, _TONES)
