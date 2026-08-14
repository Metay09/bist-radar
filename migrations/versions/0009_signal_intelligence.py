"""signal intelligence audit state

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signal_audits",
        sa.Column("signal_id", sa.String(120), primary_key=True),
        sa.Column("stop_hit_at", sa.DateTime(timezone=True)),
        sa.Column("target1_hit_at", sa.DateTime(timezone=True)),
        sa.Column("target2_hit_at", sa.DateTime(timezone=True)),
        sa.Column("target3_hit_at", sa.DateTime(timezone=True)),
        sa.Column("ordering", sa.String(24), nullable=False, server_default="NONE"),
        sa.Column("result_classification", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("signal_audits")
