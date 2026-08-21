"""autonomous evidence accumulation and governance

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_cycles",
        sa.Column("cycle_id", sa.String(120), primary_key=True),
        sa.Column("completed_bar_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, index=True),
        sa.Column("checkpoints", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )
    op.create_table(
        "research_labels",
        sa.Column("signal_id", sa.String(120), primary_key=True),
        sa.Column("policy_version", sa.String(40), nullable=False, index=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_adjusted_r", sa.Float()),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False),
    )
    op.create_table(
        "research_dataset_versions",
        sa.Column("dataset_id", sa.String(80), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("data_hash", sa.String(64), nullable=False, index=True),
        sa.Column("label_count", sa.Integer(), nullable=False),
        sa.Column("feature_schema", sa.String(40), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
    )
    op.create_table(
        "daily_research_snapshots",
        sa.Column("session_date", sa.String(10), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("deltas", sa.JSON(), nullable=False),
    )
    op.create_table(
        "weekly_research_reports",
        sa.Column("week_start", sa.String(10), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("weekly_research_reports")
    op.drop_table("daily_research_snapshots")
    op.drop_table("research_dataset_versions")
    op.drop_table("research_labels")
    op.drop_table("research_cycles")
