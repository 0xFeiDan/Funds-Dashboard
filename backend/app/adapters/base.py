from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from .controls import CircuitBreaker,TokenBucket
from .errors import UnsupportedFeatureError
from ..schemas import NormalizedAccountSummary, NormalizedPosition
class ExchangeAdapter(ABC):
    """Read-only boundary. Implementations must never call order/transfer/withdraw endpoints."""
    def __init__(self, account_id:str, account_name:str, credentials:dict[str,str], public_identifier:str|None=None):
        self.account_id,self.account_name,self.credentials,self.public_identifier=account_id,account_name,credentials,public_identifier
        self.limiter=TokenBucket(capacity=20,refill_per_second=2);self.breaker=CircuitBreaker()
    async def guard(self)->None:
        if not self.breaker.allow(): raise UnsupportedFeatureError("Adapter circuit is open after repeated failures")
        await self.limiter.acquire()
    async def connect(self)->None: return None
    async def disconnect(self)->None: return None
    @abstractmethod
    async def health_check(self)->dict: ...
    @abstractmethod
    async def get_account_summary(self)->NormalizedAccountSummary: ...
    @abstractmethod
    async def get_positions(self)->list[NormalizedPosition]: ...
    async def get_open_orders(self)->list[dict]: raise UnsupportedFeatureError("Open order data is not enabled in phase one")
    async def get_funding_history(self)->list[dict]: raise UnsupportedFeatureError("Funding history is phase two")
    async def get_trade_history(self)->list[dict]: raise UnsupportedFeatureError("Trade history is phase two")
    async def get_income_history(self)->list[dict]: raise UnsupportedFeatureError("Income history is phase two")
    async def get_mark_prices(self)->dict[str,str]: raise UnsupportedFeatureError("Market stream is not configured")
    async def stream_account_updates(self)->AsyncIterator[dict]:
        if False: yield {}
        raise UnsupportedFeatureError("Account stream is unavailable for this account type")
    async def stream_market_updates(self)->AsyncIterator[dict]:
        if False: yield {}
        raise UnsupportedFeatureError("Market stream is unavailable")
    async def reconcile_state(self)->tuple[NormalizedAccountSummary,list[NormalizedPosition]]:
        await self.guard()
        try:
            result=await self.get_account_summary(),await self.get_positions()
            self.breaker.success();return result
        except Exception:
            self.breaker.failure();raise
