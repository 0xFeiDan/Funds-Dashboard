from decimal import Decimal

import pytest

from app.adapters import ADAPTERS
from app.adapters.onchain import SolanaAdapter
from app.schemas import Exchange


def token_account(mint: str, amount: str) -> dict:
    return {"account": {"data": {"parsed": {"info": {"mint": mint, "tokenAmount": {"uiAmountString": amount}}}}}}


@pytest.mark.asyncio
async def test_solana_reads_native_sol_and_known_spl_stablecoins():
    class StubSolana(SolanaAdapter):
        async def _price(self):
            return Decimal("150")

        async def _rpc(self, _client, method, params):
            if method == "getBalance":
                return {"value": 1_250_000_000}
            if params[1]["programId"] == self._token_programs[0]:
                return {"value": [token_account("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "12.5"), token_account("UnknownMint111111111111111111111111111111111", "3")]}
            return {"value": [token_account("Es9vMFrzaCERmJfrF4H2FYD8q5jD3S9pB9oszkKCNghB", "7")]}

    balances = await StubSolana("sol-1", "Sol 钱包", {}, "wallet")._balances()

    assert ("SOL", Decimal("1.25"), Decimal("150"), "ONCHAIN_NATIVE") in balances
    assert ("USDC", Decimal("12.5"), Decimal("1"), "SPL") in balances
    assert ("USDT", Decimal("7"), Decimal("1"), "SPL") in balances
    assert any(symbol.startswith("SPL-") and price is None for symbol, _, price, _ in balances)


def test_solana_is_a_public_wallet_adapter():
    assert ADAPTERS[Exchange.SOLANA] is SolanaAdapter
