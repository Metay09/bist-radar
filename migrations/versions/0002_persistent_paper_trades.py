"""persistent paper trade ledger"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("paper_trades")
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trade_id", sa.String(36), nullable=False, unique=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("active_symbol", sa.String(16), nullable=True),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("position_size", sa.Numeric(20, 8), nullable=False),
        sa.Column("stop_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("target_1", sa.Numeric(20, 8), nullable=False),
        sa.Column("target_2", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("exit_reason", sa.String(80), nullable=True),
        sa.Column("gross_return", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("fees", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("slippage", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("net_return", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.UniqueConstraint("active_symbol", name="uq_paper_trade_active_symbol"),
    )
    op.create_index("ix_paper_trades_symbol", "paper_trades", ["symbol"])
    op.create_index("ix_paper_trades_trade_id", "paper_trades", ["trade_id"], unique=True)


def downgrade() -> None:
    op.drop_table("paper_trades")
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(16)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
