"""professional quant research shadow lab

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_baselines",
        sa.Column("baseline_id", sa.String(80), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("immutable", sa.Boolean(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
    )
    op.create_table(
        "feature_definitions",
        sa.Column("name", sa.String(80), primary_key=True),
        sa.Column("schema_version", sa.String(40), nullable=False, index=True),
        sa.Column("source_timeframe", sa.String(16), nullable=False),
        sa.Column("formula", sa.String(500), nullable=False),
        sa.Column("missing_policy", sa.String(80), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_table(
        "feature_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(120), nullable=False, index=True),
        sa.Column("feature_name", sa.String(80), nullable=False, index=True),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("availability_timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.UniqueConstraint("signal_id", "feature_name", name="uq_feature_observation"),
    )
    op.create_table(
        "data_freshness_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.String(40), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("bar_close_time", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("provider_available_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("persist_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "provider_id", "symbol", "timeframe", "bar_close_time", name="uq_freshness_bar"
        ),
    )
    op.create_table(
        "ml_experiments",
        sa.Column("experiment_id", sa.String(80), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("data_hash", sa.String(64), nullable=False, index=True),
        sa.Column("feature_schema", sa.String(40), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False, index=True),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("hyperparameters", sa.JSON(), nullable=False),
        sa.Column("date_ranges", sa.JSON(), nullable=False),
        sa.Column("prior_trials", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ml_experiments")
    op.drop_table("data_freshness_observations")
    op.drop_table("feature_observations")
    op.drop_table("feature_definitions")
    op.drop_table("research_baselines")
