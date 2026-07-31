"""realtime sync and historical ledger metadata"""
from alembic import op
import sqlalchemy as sa

revision = "0002_realtime_ledger"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

LEDGER_TABLES = ("trades", "fills", "funding_payments", "trading_fees", "balance_movements", "daily_pnl", "daily_equity", "connection_status", "reconciliation_logs")

def upgrade():
    for table in LEDGER_TABLES:
        op.add_column(table, sa.Column("external_id", sa.String(160), nullable=True))
        op.add_column(table, sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_account_occurred", table, ["exchange_account_id", "occurred_at"])
    for table in ("trades", "fills", "funding_payments", "trading_fees", "balance_movements"):
        op.create_unique_constraint(f"uq_{table}_account_external", table, ["exchange_account_id", "external_id"])
    op.create_table("sync_cursors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("exchange_account_id", sa.String(36), sa.ForeignKey("exchange_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stream", sa.String(40), nullable=False),
        sa.Column("cursor", sa.String(160), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("exchange_account_id", "stream", name="uq_cursor_account_stream"),
    )

def downgrade():
    op.drop_table("sync_cursors")
    for table in ("trades", "fills", "funding_payments", "trading_fees", "balance_movements"):
        op.drop_constraint(f"uq_{table}_account_external", table, type_="unique")
    for table in LEDGER_TABLES:
        op.drop_index(f"ix_{table}_account_occurred", table_name=table)
        op.drop_column(table, "occurred_at")
        op.drop_column(table, "external_id")
