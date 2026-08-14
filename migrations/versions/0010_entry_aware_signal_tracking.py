"""entry-aware signal tracking

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signal_audits",
        sa.Column("audit_version", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "signal_audits", sa.Column("entry_hit_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("signal_audits", sa.Column("entry_price", sa.Numeric(20, 8), nullable=True))
    op.add_column(
        "signal_audits",
        sa.Column("highest_target", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("signal_audits", sa.Column("bars_to_entry", sa.Integer(), nullable=True))
    op.add_column(
        "signal_audits",
        sa.Column("bars_after_entry", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "signal_audits", sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    for name in (
        "terminal_at",
        "bars_after_entry",
        "bars_to_entry",
        "highest_target",
        "entry_price",
        "entry_hit_at",
        "audit_version",
    ):
        op.drop_column("signal_audits", name)
