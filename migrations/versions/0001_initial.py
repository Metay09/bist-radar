"""initial schema"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "symbols",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "market_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.UniqueConstraint("symbol", "timestamp", name="uq_bar_symbol_time"),
    )
    for table in (
        "market_snapshots",
        "radar_scores",
        "signals",
        "paper_trades",
        "provider_health",
        "kap_announcements",
        "takas_snapshots",
        "broker_distribution",
    ):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("symbol", sa.String(16), index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
        )
    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event", sa.String(80), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    for table in reversed(
        (
            "market_snapshots",
            "radar_scores",
            "signals",
            "paper_trades",
            "provider_health",
            "kap_announcements",
            "takas_snapshots",
            "broker_distribution",
            "system_events",
            "market_bars",
            "symbols",
        )
    ):
        op.drop_table(table)
