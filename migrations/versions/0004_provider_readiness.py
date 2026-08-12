"""provider readiness and data audit tables"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_bars", sa.Column("timeframe", sa.String(8), nullable=True))
    op.add_column("market_bars", sa.Column("provider_id", sa.String(40), nullable=True))
    op.add_column("market_bars", sa.Column("dataset_id", sa.String(36), nullable=True))
    op.add_column(
        "market_bars", sa.Column("received_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_market_bars_symbol_tf_ts", "market_bars", ["symbol", "timeframe", "timestamp"]
    )
    op.create_index("ix_market_bars_provider_ts", "market_bars", ["provider_id", "timestamp"])
    op.create_index("ix_market_bars_dataset", "market_bars", ["dataset_id"])
    op.create_table(
        "providers",
        sa.Column("provider_id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("data_mode", sa.String(20), nullable=False),
        sa.Column("health", sa.String(20), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
    )
    op.create_table(
        "historical_datasets",
        sa.Column("dataset_id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(40), nullable=False, index=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False, index=True),
    )
    op.create_table(
        "data_quality_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.String(40), nullable=False, index=True),
        sa.Column("day", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
    )
    op.create_table(
        "data_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.String(40), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=False),
        sa.Column("new_value", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "quarantined_market_data",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.String(40), nullable=False, index=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "quarantined_market_data",
        "data_revisions",
        "data_quality_metrics",
        "historical_datasets",
        "providers",
    ):
        op.drop_table(table)
    for idx in (
        "ix_market_bars_dataset",
        "ix_market_bars_provider_ts",
        "ix_market_bars_symbol_tf_ts",
    ):
        op.drop_index(idx, table_name="market_bars")
    for col in ("received_at", "dataset_id", "provider_id", "timeframe"):
        op.drop_column("market_bars", col)
