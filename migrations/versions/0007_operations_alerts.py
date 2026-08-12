"""persistent notification dedup and worker state"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedup_key", sa.String(180), nullable=False, unique=True, index=True),
        sa.Column("alert_type", sa.String(40), nullable=False, index=True),
        sa.Column("symbol", sa.String(16), nullable=True),
        sa.Column("signal_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "worker_state",
        sa.Column("job_name", sa.String(80), primary_key=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_processed_bar", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_state")
    op.drop_table("notification_events")
