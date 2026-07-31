"""initial read-only portfolio schema"""
from alembic import op
import sqlalchemy as sa
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("username", sa.String(64), nullable=False, unique=True), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("exchange_accounts", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False), sa.Column("exchange", sa.String(32), nullable=False), sa.Column("name", sa.String(128), nullable=False), sa.Column("account_type", sa.String(32), nullable=False), sa.Column("public_identifier", sa.String(256)), sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("user_id","exchange","name",name="uq_account_name"))
    op.create_table("encrypted_credentials", sa.Column("id",sa.String(36),primary_key=True),sa.Column("exchange_account_id",sa.String(36),sa.ForeignKey("exchange_accounts.id",ondelete="CASCADE"),nullable=False,unique=True),sa.Column("ciphertext",sa.LargeBinary,nullable=False),sa.Column("nonce",sa.LargeBinary,nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    for name in ["account_snapshots","positions_snapshots","current_positions","trades","fills","funding_payments","trading_fees","balance_movements","daily_pnl","daily_equity","connection_status","reconciliation_logs","audit_logs"]:
        op.create_table(name, sa.Column("id",sa.String(36),primary_key=True),sa.Column("exchange_account_id",sa.String(36),sa.ForeignKey("exchange_accounts.id",ondelete="CASCADE"),nullable=True),sa.Column("payload",sa.JSON,nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
        op.create_index(f"ix_{name}_account_created",name,["exchange_account_id","created_at"])
def downgrade():
    for name in ["audit_logs","reconciliation_logs","connection_status","daily_equity","daily_pnl","balance_movements","trading_fees","funding_payments","fills","trades","current_positions","positions_snapshots","account_snapshots","encrypted_credentials","exchange_accounts","users"]: op.drop_table(name)
