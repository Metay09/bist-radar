"""intraday signal outcomes and shadow learning"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_feature_snapshots",
        sa.Column("signal_id", sa.String(120), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False, index=True),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("lifecycle", sa.String(24), nullable=False),
        sa.Column("feature_schema_version", sa.String(30), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
    )
    op.create_table(
        "ml_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(120), nullable=False, index=True),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.UniqueConstraint("signal_id", "horizon", name="uq_ml_outcome_horizon"),
    )
    op.create_table(
        "ml_datasets",
        sa.Column("dataset_id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_table(
        "ml_models",
        sa.Column("model_id", sa.String(80), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_type", sa.String(40), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_table(
        "ml_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(120), nullable=False, index=True),
        sa.Column("model_id", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predictions", sa.JSON(), nullable=False),
        sa.UniqueConstraint("signal_id", "model_id", name="uq_ml_prediction"),
    )
    op.create_table(
        "ml_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(80), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "ml_evaluations",
        "ml_predictions",
        "ml_models",
        "ml_datasets",
        "ml_outcomes",
        "ml_feature_snapshots",
    ):
        op.drop_table(table)
