import pytest
import httpx

from app.adapters.hyperliquid import HyperliquidAdapter
from app.adapters.http import request


@pytest.mark.asyncio
async def test_hyperliquid_collects_perp_spot_vault_and_subaccounts():
    adapter = HyperliquidAdapter("account-1", "我的 Hyperliquid", {}, "0xmaster")

    async def info(payload, **_kwargs):
        request_type, user, dex = payload["type"], payload.get("user"), payload.get("dex", "")
        if request_type == "perpDexs":
            return [{"name": "xyz"}]
        if request_type == "subAccounts":
            return [{"name": "量化子账户", "subAccountUser": "0xsub"}]
        if request_type == "spotMeta":
            return {
                "tokens": [{"index": 0, "name": "USDC"}, {"index": 1, "name": "HYPE"}],
                "universe": [{"name": "HYPE/USDC", "tokens": [1, 0]}],
            }
        if request_type == "allMids":
            return {"HYPE/USDC": "2"}
        if request_type == "clearinghouseState":
            values = {
                ("0xmaster", ""): ("100", [{"position": {"coin": "BTC", "szi": "0.01", "positionValue": "1000", "entryPx": "99000", "unrealizedPnl": "10", "leverage": {"type": "cross", "value": "2"}, "marginUsed": "500"}}]),
                ("0xmaster", "xyz"): ("20", []),
                ("0xsub", ""): ("10", []),
                ("0xsub", "xyz"): ("0", []),
            }
            equity, positions = values[(user, dex)]
            return {"marginSummary": {"accountValue": equity}, "withdrawable": equity, "assetPositions": positions}
        if request_type == "spotClearinghouseState":
            return {"balances": [{"coin": "USDC", "total": "5"}, {"coin": "HYPE", "total": "10"}]} if user == "0xmaster" else {"balances": []}
        if request_type == "userVaultEquities":
            return [{"vaultAddress": "0xvault", "equity": "25"}] if user == "0xmaster" else []
        if request_type == "delegatorSummary":
            return {"delegated": "3", "undelegated": "1", "totalPendingWithdrawal": "2"} if user == "0xmaster" else {}
        raise AssertionError(payload)

    adapter._info = info
    summary, positions = await adapter.reconcile_state()

    assert summary.account_equity == 192
    assert {position.contract_type for position in positions} == {"PERPETUAL", "SPOT", "VAULT_EQUITY", "STAKING"}
    assert next(position for position in positions if position.base_asset == "HYPE").position_value == 20
    assert next(position for position in positions if position.contract_type == "VAULT_EQUITY").position_value == 25
    assert sum(position.position_value for position in positions if position.contract_type == "STAKING") == 12


@pytest.mark.asyncio
async def test_hyperliquid_allows_empty_optional_vault_and_staking_products():
    adapter = HyperliquidAdapter("account-1", "我的 Hyperliquid", {}, "0xmaster")

    async def info(payload, **_kwargs):
        request_type = payload["type"]
        if request_type == "perpDexs": return []
        if request_type == "subAccounts": return None
        if request_type == "spotMeta": return {"tokens": [], "universe": []}
        if request_type == "allMids": return {}
        if request_type == "clearinghouseState": return {"marginSummary": {"accountValue": "1"}, "withdrawable": "1", "assetPositions": []}
        if request_type == "spotClearinghouseState": return {"balances": []}
        if request_type in {"userVaultEquities", "delegatorSummary"}: return None
        raise AssertionError(payload)

    adapter._info = info
    summary, positions = await adapter.reconcile_state()
    assert summary.account_equity == 1
    assert positions == []


@pytest.mark.asyncio
async def test_optional_json_null_is_not_an_invalid_exchange_response():
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"null", headers={"content-type": "application/json"}))
    async with httpx.AsyncClient(transport=transport) as client:
        assert await request(client, "POST", "https://example.test/info", allow_null=True) is None
