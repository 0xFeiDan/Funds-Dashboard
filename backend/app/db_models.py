import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid.uuid4())
class User(Base):
    __tablename__="users"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); username: Mapped[str]=mapped_column(String(64),unique=True); password_hash: Mapped[str]=mapped_column(String(255)); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class ExchangeAccount(Base):
    __tablename__="exchange_accounts"; __table_args__=(UniqueConstraint("user_id","exchange","name",name="uq_account_name"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); user_id: Mapped[str]=mapped_column(ForeignKey("users.id")); exchange: Mapped[str]=mapped_column(String(32)); name: Mapped[str]=mapped_column(String(128)); account_type: Mapped[str]=mapped_column(String(32),default="perpetual"); public_identifier: Mapped[str|None]=mapped_column(String(256),nullable=True); enabled: Mapped[bool]=mapped_column(Boolean,default=True); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class EncryptedCredential(Base):
    __tablename__="encrypted_credentials"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); exchange_account_id: Mapped[str]=mapped_column(ForeignKey("exchange_accounts.id",ondelete="CASCADE"),unique=True); ciphertext: Mapped[bytes]=mapped_column(LargeBinary); nonce: Mapped[bytes]=mapped_column(LargeBinary); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class AccountSnapshot(Base):
    __tablename__="account_snapshots"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); exchange_account_id: Mapped[str]=mapped_column(ForeignKey("exchange_accounts.id",ondelete="CASCADE")); payload: Mapped[dict]=mapped_column(JSON); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class PositionSnapshot(Base):
    __tablename__="positions_snapshots"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); exchange_account_id: Mapped[str]=mapped_column(ForeignKey("exchange_accounts.id",ondelete="CASCADE")); payload: Mapped[dict]=mapped_column(JSON); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class LatestPortfolioState(Base):
    """Durable latest payload used to restore the dashboard after a restart."""
    __tablename__="latest_portfolio_states"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    exchange_account_id: Mapped[str]=mapped_column(ForeignKey("exchange_accounts.id",ondelete="CASCADE"),unique=True)
    payload: Mapped[dict]=mapped_column(JSON)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
class PortfolioHistoryState(Base):
    """An atomic account summary + positions snapshot for historical replay."""
    __tablename__="portfolio_history_states"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    exchange_account_id: Mapped[str]=mapped_column(ForeignKey("exchange_accounts.id",ondelete="CASCADE"))
    payload: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class AuditLog(Base):
    __tablename__="audit_logs"; id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); exchange_account_id: Mapped[str|None]=mapped_column(ForeignKey("exchange_accounts.id",ondelete="CASCADE"),nullable=True); payload: Mapped[dict]=mapped_column(JSON); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class LedgerBase:
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    exchange_account_id: Mapped[str]=mapped_column(ForeignKey("exchange_accounts.id",ondelete="CASCADE"))
    external_id: Mapped[str|None]=mapped_column(String(160),nullable=True)
    occurred_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    payload: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Trade(LedgerBase, Base): __tablename__="trades"; __table_args__=(UniqueConstraint("exchange_account_id","external_id",name="uq_trades_account_external"),)
class Fill(LedgerBase, Base): __tablename__="fills"; __table_args__=(UniqueConstraint("exchange_account_id","external_id",name="uq_fills_account_external"),)
class FundingPayment(LedgerBase, Base): __tablename__="funding_payments"; __table_args__=(UniqueConstraint("exchange_account_id","external_id",name="uq_funding_payments_account_external"),)
class TradingFee(LedgerBase, Base): __tablename__="trading_fees"; __table_args__=(UniqueConstraint("exchange_account_id","external_id",name="uq_trading_fees_account_external"),)
class BalanceMovement(LedgerBase, Base): __tablename__="balance_movements"; __table_args__=(UniqueConstraint("exchange_account_id","external_id",name="uq_balance_movements_account_external"),)
class ConnectionStatus(LedgerBase, Base): __tablename__="connection_status"
class ReconciliationLog(LedgerBase, Base): __tablename__="reconciliation_logs"
class SyncCursor(Base):
    __tablename__="sync_cursors"; __table_args__=(UniqueConstraint("exchange_account_id","stream",name="uq_cursor_account_stream"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid); exchange_account_id: Mapped[str]=mapped_column(ForeignKey("exchange_accounts.id",ondelete="CASCADE")); stream: Mapped[str]=mapped_column(String(40)); cursor: Mapped[str|None]=mapped_column(String(160),nullable=True); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
