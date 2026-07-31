import asyncio,time
from .errors import RateLimitError

class TokenBucket:
    """Per-adapter request budget; no queue growth when an exchange slows down."""
    def __init__(self, capacity:int, refill_per_second:float):
        self.capacity=float(capacity); self.tokens=float(capacity); self.refill=refill_per_second; self.updated=time.monotonic(); self.lock=asyncio.Lock()
    async def acquire(self, cost:float=1)->None:
        async with self.lock:
            now=time.monotonic(); self.tokens=min(self.capacity,self.tokens+(now-self.updated)*self.refill); self.updated=now
            if self.tokens<cost: raise RateLimitError("Local adapter rate budget exhausted; skipped rather than backlog")
            self.tokens-=cost

class CircuitBreaker:
    def __init__(self, failure_limit:int=5, reset_seconds:int=60): self.failures=0;self.failure_limit=failure_limit;self.reset_seconds=reset_seconds;self.opened_at:float|None=None
    def allow(self)->bool:
        if self.opened_at is None:return True
        if time.monotonic()-self.opened_at>=self.reset_seconds:self.failures=0;self.opened_at=None;return True
        return False
    def success(self)->None:self.failures=0;self.opened_at=None
    def failure(self)->None:
        self.failures+=1
        if self.failures>=self.failure_limit:self.opened_at=time.monotonic()
