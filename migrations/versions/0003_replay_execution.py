"""replay execution persistence and strategy identity"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_trades", sa.Column("portfolio_id", sa.String(40), nullable=True))
    op.add_column("paper_trades", sa.Column("strategy_id", sa.String(40), nullable=True))
    op.execute("UPDATE paper_trades SET portfolio_id='paper-default', strategy_id='radar-v1'")
    op.alter_column("paper_trades", "portfolio_id", nullable=False)
    op.alter_column("paper_trades", "strategy_id", nullable=False)
    op.drop_constraint("uq_paper_trade_active_symbol", "paper_trades", type_="unique")
    op.create_unique_constraint(
        "uq_paper_trade_scope_active",
        "paper_trades",
        ["portfolio_id", "strategy_id", "active_symbol"],
    )
    op.create_table(
        "replay_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_processed_timestamp", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False, index=True),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )
    op.create_table(
        "replay_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("portfolio_id", sa.String(40), nullable=False),
        sa.Column("strategy_id", sa.String(40), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "replay_equity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("peak_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("drawdown", sa.Numeric(20, 8), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("replay_equity")
    op.drop_table("replay_trades")
    op.drop_table("replay_runs")
    op.drop_constraint("uq_paper_trade_scope_active", "paper_trades", type_="unique")
    op.create_unique_constraint("uq_paper_trade_active_symbol", "paper_trades", ["active_symbol"])
    op.drop_column("paper_trades", "strategy_id")
    op.drop_column("paper_trades", "portfolio_id")
