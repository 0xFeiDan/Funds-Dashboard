"""Phase-two account-isolated realtime workers.

WebSocket payloads only wake reconciliation. REST remains the source of truth.
"""
import asyncio, logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from sqlalchemy import select
from ..adapters.errors import UnsupportedFeatureError
from ..db import SessionLocal
from ..db_models import ExchangeAccount
from .history import store_income_rows
from .portfolio import PortfolioService
log=logging.getLogger(__name__)

async def reconnecting_stream(stream_factory:Callable[[],AsyncIterator[dict]], on_event:Callable[[dict],Awaitable[None]], on_reconnected:Callable[[],Awaitable[None]], stop:asyncio.Event)->None:
    """Reconnect with exponential backoff then reconcile before trusting new events."""
    delay=1; needs_reconcile=False
    while not stop.is_set():
        try:
            async for event in stream_factory():
                delay=1
                if stop.is_set(): return
                if needs_reconcile:
                    await on_reconnected()
                    needs_reconcile=False
                await on_event(event)
            raise ConnectionError("stream ended")
        except UnsupportedFeatureError as exc:
            log.info("stream_not_supported error=%s",exc)
            return
        except Exception as exc:
            log.warning("exchange_stream_disconnected error=%s",exc.__class__.__name__)
            try: await asyncio.wait_for(stop.wait(),timeout=delay)
            except TimeoutError: pass
            delay=min(delay*2,60)
            if stop.is_set(): return
            needs_reconcile=True

class SyncSupervisor:
    """Discovers enabled accounts; a failure in one account never stops another."""
    def __init__(self, redis, reconcile_interval:int):
        self.redis=redis;self.reconcile_interval=reconcile_interval;self.stop=asyncio.Event();self.tasks:dict[str,asyncio.Task]={};self.discovery:asyncio.Task|None=None
    async def start(self)->None: self.discovery=asyncio.create_task(self._discover_loop(),name="sync-discovery")
    async def close(self)->None:
        self.stop.set()
        for task in [*self.tasks.values(),self.discovery]:
            if task: task.cancel()
        await asyncio.gather(*[task for task in [*self.tasks.values(),self.discovery] if task],return_exceptions=True)
    async def _discover_loop(self)->None:
        while not self.stop.is_set():
            async with SessionLocal() as session:
                ids=(await session.scalars(select(ExchangeAccount.id).where(ExchangeAccount.enabled.is_(True)))).all()
            for account_id in ids:
                if account_id not in self.tasks or self.tasks[account_id].done(): self.tasks[account_id]=asyncio.create_task(self._run_account(account_id),name=f"sync-{account_id}")
            try: await asyncio.wait_for(self.stop.wait(),timeout=60)
            except TimeoutError: pass
    async def _run_account(self, account_id:str)->None:
        last_reconcile=0.0;last_history=0.0
        async def reconcile(reason:str)->None:
            nonlocal last_reconcile,last_history
            now=asyncio.get_running_loop().time()
            if reason=="event" and now-last_reconcile<1: return
            async with SessionLocal() as session:
                account=await session.get(ExchangeAccount,account_id)
                if not account or not account.enabled:return
                service=PortfolioService(session,self.redis)
                await service.refresh_account(account,reason=reason)
                last_reconcile=now
                if now-last_history>=180:
                    await self._history_sync(session,service,account)
                    last_history=now
        async def on_event(event:dict)->None:
            async with SessionLocal() as session:
                account=await session.get(ExchangeAccount,account_id)
                if not account:return
                inserted=await store_income_rows(session,account_id,stream_rows(account.exchange,event))
                if inserted: await session.commit()
            await reconcile("event")
        async def factory():
            async with SessionLocal() as session:
                account=await session.get(ExchangeAccount,account_id)
                if not account: raise UnsupportedFeatureError("Account no longer exists")
                adapter=await PortfolioService(session,self.redis).adapter(account)
            async for event in adapter.stream_account_updates(): yield event
        await reconcile("startup")
        periodic=asyncio.create_task(self._periodic_reconcile(reconcile),name=f"reconcile-{account_id}")
        try:
            await reconnecting_stream(factory,on_event,lambda:reconcile("reconnect"),self.stop)
            # Public-wallet adapters do not have a private event stream. Keep
            # periodic reconciliation alive after that expected condition.
            await self.stop.wait()
        finally:
            periodic.cancel();await asyncio.gather(periodic,return_exceptions=True)
    async def _periodic_reconcile(self, reconcile:Callable[[str],Awaitable[None]])->None:
        while not self.stop.is_set():
            try: await asyncio.wait_for(self.stop.wait(),timeout=self.reconcile_interval)
            except TimeoutError: await reconcile("scheduled")
    async def _history_sync(self, session, service:PortfolioService, account:ExchangeAccount)->None:
        # History is periodic and adapter-isolated. Unsupported methods are a visible partial-data state, not a silent zero.
        adapter=await service.adapter(account)
        rows=[]
        for method in (adapter.get_income_history,adapter.get_funding_history,adapter.get_trade_history):
            try: rows.extend(await method())
            except UnsupportedFeatureError: continue
            except Exception as exc: log.info("history_sync_failed account=%s error=%s",account.id,exc.__class__.__name__)
        if rows and await store_income_rows(session,account.id,rows): await session.commit()

def stream_rows(exchange:str,event:dict)->list[dict]:
    """Extract only documented ledger-like fields. Unknown events do not become fake PnL."""
    channel=event.get("channel")
    data=event.get("data",event)
    if exchange=="hyperliquid":
        values=data if isinstance(data,list) else [data]
        if channel=="userFundings": return [{**x,"change":x.get("change") or (x.get("delta") or {}).get("usdc"),"kind":"FUNDING"} for x in values if isinstance(x,dict)]
        if channel=="userFills": return [{**x,"kind":"FILL"} for x in values if isinstance(x,dict)]
        if channel=="userNonFundingLedgerUpdates": return [{**x,"kind":str(x.get("delta",{}).get("type","LEDGER"))} for x in values if isinstance(x,dict)]
    if exchange=="lighter" and event.get("type") in {"update/account_all","update/account"}:
        result=[]
        for group in (event.get("funding_histories") or {}).values(): result.extend([{**x,"kind":"FUNDING"} for x in (group if isinstance(group,list) else [group]) if isinstance(x,dict)])
        for group in (event.get("trades") or {}).values(): result.extend([{**x,"kind":"FILL"} for x in (group if isinstance(group,list) else [group]) if isinstance(x,dict)])
        return result
    return []
