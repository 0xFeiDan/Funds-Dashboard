import asyncio
import pytest
from app.services.sync import reconnecting_stream, stream_rows

def test_hyperliquid_stream_funding_is_normalized_for_ledger():
    rows=stream_rows("hyperliquid",{"channel":"userFundings","data":[{"time":1,"delta":{"usdc":"2"}}]})
    assert rows[0]["kind"]=="FUNDING"

def test_lighter_stream_trade_is_normalized_for_ledger():
    rows=stream_rows("lighter",{"type":"update/account_all","trades":{"1":[{"trade_id":9,"price":"10"}]}})
    assert rows[0]["kind"]=="FILL"

@pytest.mark.asyncio
async def test_reconnect_runs_reconcile_after_disconnect():
    stop=asyncio.Event();calls=[];attempts=0
    async def stream():
        nonlocal attempts
        attempts+=1
        if attempts==1: raise ConnectionError("gone")
        yield {"_system":"connected"}
    async def event(_): return None
    async def reconciled(): calls.append("reconciled");stop.set()
    await reconnecting_stream(stream,event,reconciled,stop)
    assert calls==["reconciled"]
