from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pydantic import BaseModel, Field, SecretStr, field_serializer

class Exchange(StrEnum): BINANCE="binance"; BITGET="bitget"; HYPERLIQUID="hyperliquid"; LIGHTER="lighter"; BITCOIN="bitcoin"; ETHEREUM="ethereum"; ARBITRUM="arbitrum"
class Side(StrEnum): LONG="LONG"; SHORT="SHORT"
class MarginMode(StrEnum): CROSS="CROSS"; ISOLATED="ISOLATED"; UNKNOWN="UNKNOWN"
class RiskLevel(StrEnum): SAFE="SAFE"; WATCH="WATCH"; DANGER="DANGER"; CRITICAL="CRITICAL"; UNKNOWN="UNKNOWN"
class DataSource(StrEnum): REST="REST"; WEBSOCKET="WEBSOCKET"; ESTIMATED="ESTIMATED"
class DecimalModel(BaseModel):
    model_config={"use_enum_values":True}
    @field_serializer("*")
    def serialize_decimal(self, value): return format(value,"f") if isinstance(value,Decimal) else value
class NormalizedAccountSummary(DecimalModel):
    exchange: Exchange; account_id: str; account_name: str; account_type: str="perpetual"; margin_currency: str
    wallet_balance: Decimal=Decimal("0"); account_equity: Decimal=Decimal("0"); available_balance: Decimal=Decimal("0"); unrealized_pnl: Decimal=Decimal("0"); realized_pnl: Decimal=Decimal("0"); funding_pnl: Decimal=Decimal("0"); trading_fee: Decimal=Decimal("0"); initial_margin: Decimal=Decimal("0"); maintenance_margin: Decimal=Decimal("0"); margin_ratio: Decimal|None=None; total_position_notional: Decimal=Decimal("0"); effective_leverage: Decimal|None=None; updated_at: datetime; data_source: DataSource=DataSource.REST; is_stale: bool=False; raw_values: dict[str,str]=Field(default_factory=dict); field_notes: dict[str,str]=Field(default_factory=dict)
class NormalizedPosition(DecimalModel):
    exchange: Exchange; account_id: str; account_name: str; symbol: str; exchange_symbol: str; base_asset: str; quote_asset: str="USD"; settlement_asset: str="USDT"; side: Side; quantity: Decimal; position_value: Decimal; entry_price: Decimal|None=None; mark_price: Decimal|None=None; index_price: Decimal|None=None; unrealized_pnl: Decimal=Decimal("0"); realized_pnl: Decimal=Decimal("0"); leverage: Decimal|None=None; effective_leverage: Decimal|None=None; margin_mode: MarginMode=MarginMode.UNKNOWN; isolated_margin: Decimal|None=None; position_margin: Decimal|None=None; maintenance_margin: Decimal|None=None; liquidation_price: Decimal|None=None; liquidation_distance_percent: Decimal|None=None; risk_level: RiskLevel=RiskLevel.UNKNOWN; funding_rate: Decimal|None=None; next_funding_time: datetime|None=None; contract_type: str="PERPETUAL"; updated_at: datetime; is_stale: bool=False; liquidation_price_is_estimated: bool=True; raw_data: dict[str,str]=Field(default_factory=dict)
class AccountCreate(BaseModel):
    exchange: Exchange; name: str=Field(min_length=1,max_length=128); public_identifier: str|None=Field(default=None,max_length=256); api_key: SecretStr|None=None; api_secret: SecretStr|None=None; passphrase: SecretStr|None=None; product_type: str|None=None
class AccountView(BaseModel): id:str; exchange:Exchange; name:str; public_identifier:str|None; enabled:bool
class Login(BaseModel): username:str; password:SecretStr
