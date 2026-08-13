"""dynamic all-shares universe

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "universe_snapshots",
        sa.Column("snapshot_id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument_count", sa.Integer(), nullable=False),
        sa.Column("equity_count", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_universe_snapshots_source_timestamp", "universe_snapshots", ["source_timestamp"]
    )
    op.create_table(
        "universe_symbols",
        sa.Column("symbol", sa.String(16), primary_key=True),
        sa.Column("canonical_symbol", sa.String(16), nullable=False, unique=True),
        sa.Column("company_name", sa.String(240)),
        sa.Column("market", sa.String(100)),
        sa.Column("instrument_type", sa.String(40), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("provider_symbol", sa.String(24), unique=True),
        sa.Column("provider_status", sa.String(40), nullable=False),
        sa.Column("validation_status", sa.String(40), nullable=False),
        sa.Column("latest_provider_timestamp", sa.DateTime(timezone=True)),
        sa.Column("last_probed_at", sa.DateTime(timezone=True)),
    )
    for name, columns in (
        ("ix_universe_symbols_active", ["active"]),
        ("ix_universe_symbols_last_seen", ["last_seen"]),
        ("ix_universe_symbols_provider_status", ["provider_status"]),
        ("ix_universe_symbols_validation_status", ["validation_status"]),
    ):
        op.create_index(name, "universe_symbols", columns)
    op.create_table(
        "universe_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("market", sa.String(100)),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("event", sa.String(30), nullable=False),
        sa.UniqueConstraint("snapshot_id", "symbol", name="uq_universe_snapshot_symbol"),
    )
    op.create_index("ix_universe_memberships_snapshot_id", "universe_memberships", ["snapshot_id"])
    op.create_index("ix_universe_memberships_symbol", "universe_memberships", ["symbol"])


def downgrade() -> None:
    op.drop_table("universe_memberships")
    op.drop_table("universe_symbols")
    op.drop_table("universe_snapshots")
