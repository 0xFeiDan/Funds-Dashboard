import pytest

from app.adapters.bitget import BitgetAdapter


@pytest.mark.asyncio
async def test_bitget_summary_uses_all_account_usdt_valuation_and_keeps_spot_rows():
    adapter=BitgetAdapter("account-1","Bitget",{"product_type":"USDT-FUTURES"})

    async def get(path, _params):
        if path=="/api/v2/mix/account/accounts": return [{"accountEquity":"10","available":"4","unrealizedPL":"1","crossedRiskRate":"0.1"}]
        if path=="/api/v2/account/all-account-balance": return [{"accountType":"spot","usdtBalance":"20"},{"accountType":"futures","usdtBalance":"10"}]
        if path=="/api/v2/mix/position/all-position": return []
        if path=="/api/v2/spot/account/assets": return [{"coin":"USDT","available":"3","frozen":"1","locked":"0"},{"coin":"BTC","available":"0.1","frozen":"0","locked":"0"}]
        raise AssertionError(path)

    adapter._get=get
    summary=await adapter.get_account_summary()
    positions=await adapter.get_positions()
    assert summary.account_equity==30
    assert {position.base_asset for position in positions}=={"USDT","BTC"}
    assert next(position for position in positions if position.base_asset=="BTC").mark_price is None
