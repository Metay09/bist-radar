"""adaptive decision engine

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adaptive_setups",
        sa.Column("setup_id", sa.String(160), primary_key=True),
        sa.Column("signal_id", sa.String(120), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("policy_version", sa.String(40), nullable=False, index=True),
        sa.Column("state", sa.String(40), nullable=False, index=True),
        sa.Column("health", sa.String(24), nullable=False),
        sa.Column("current_plan_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("entry_time", sa.DateTime(timezone=True)),
        sa.Column("entry_price", sa.Numeric(20, 8)),
        sa.Column("initial_stop", sa.Numeric(20, 8)),
        sa.Column("active_stop", sa.Numeric(20, 8)),
        sa.Column("exit_time", sa.DateTime(timezone=True)),
        sa.Column("exit_price", sa.Numeric(20, 8)),
        sa.Column("outcome", sa.String(40), index=True),
        sa.Column("highest_target", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("action", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "adaptive_plan_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("setup_id", sa.String(160), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.UniqueConstraint("setup_id", "version", name="uq_adaptive_plan_version"),
    )
    op.create_table(
        "adaptive_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("setup_id", sa.String(160), nullable=False, index=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("event_type", sa.String(40), nullable=False, index=True),
        sa.Column("state_from", sa.String(40)),
        sa.Column("state_to", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("setup_id", "sequence", name="uq_adaptive_event_seq"),
    )


def downgrade() -> None:
    op.drop_table("adaptive_events")
    op.drop_table("adaptive_plan_versions")
    op.drop_table("adaptive_setups")
