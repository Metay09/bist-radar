"""research datasets and reports"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_bars", sa.Column("is_adjusted", sa.Boolean(), nullable=True))
    op.add_column("market_bars", sa.Column("adjustment_type", sa.String(40), nullable=True))
    op.add_column("market_bars", sa.Column("quality_flags", sa.JSON(), nullable=True))
    op.drop_constraint("uq_bar_symbol_time", "market_bars", type_="unique")
    op.create_index(
        "uq_bar_provider_symbol_tf_time",
        "market_bars",
        ["provider_id", "symbol", "timeframe", "timestamp"],
        unique=True,
    )
    op.create_table(
        "research_reports",
        sa.Column("report_id", sa.String(36), primary_key=True),
        sa.Column("report_type", sa.String(20), nullable=False, index=True),
        sa.Column("dataset_id", sa.String(36), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("research_reports")
    op.drop_index("uq_bar_provider_symbol_tf_time", table_name="market_bars")
    op.create_unique_constraint("uq_bar_symbol_time", "market_bars", ["symbol", "timestamp"])
    op.drop_column("market_bars", "quality_flags")
    op.drop_column("market_bars", "adjustment_type")
    op.drop_column("market_bars", "is_adjusted")
