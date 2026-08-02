from decimal import Decimal

import pytest

from app.adapters import ADAPTERS
from app.adapters.onchain import ArbitrumAdapter, OnchainAdapter, SolanaAdapter
from app.config import ankr_bitcoin_blockbook_url, ankr_chain_rpc_url, ankr_token_rpc_url, settings
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


def test_ankr_endpoint_family_is_derived_from_one_server_secret(monkeypatch):
    monkeypatch.setattr(settings, "ankr_rpc_url", "https://rpc.ankr.com/arbitrum/private-key")

    assert ankr_chain_rpc_url("eth") == "https://rpc.ankr.com/eth/private-key"
    assert ankr_chain_rpc_url("solana") == "https://rpc.ankr.com/solana/private-key"
    assert ankr_token_rpc_url() == "https://rpc.ankr.com/multichain/private-key"
    assert ankr_bitcoin_blockbook_url() == "https://rpc.ankr.com/premium-http/btc_blockbook/private-key"


@pytest.mark.asyncio
async def test_ankr_token_indexer_returns_native_and_erc20_assets():
    class StubArbitrum(ArbitrumAdapter):
        @property
        def token_rpc_url(self):
            return "https://example.test"

        async def _ankr_account_balances(self, _address):
            return [("ETH", Decimal("1.5"), Decimal("3000"), "ONCHAIN_NATIVE"), ("USDC", Decimal("24"), Decimal("1"), "ERC20")]

    balances = await StubArbitrum("arb-1", "Arb 钱包", {}, "0xwallet")._balances()

    assert balances == [("ETH", Decimal("1.5"), Decimal("3000"), "ONCHAIN_NATIVE"), ("USDC", Decimal("24"), Decimal("1"), "ERC20")]


@pytest.mark.asyncio
async def test_onchain_reconciliation_reads_balances_once_for_summary_and_positions():
    class CountingWallet(OnchainAdapter):
        chain = "bitcoin"; native_symbol = "BTC"; explorer = "https://example.test"
        calls = 0

        async def _fetch_balances(self):
            self.calls += 1
            return [("BTC", Decimal("1"), Decimal("100"), "ONCHAIN_NATIVE")]

    wallet = CountingWallet("wallet-1", "钱包", {}, "address")
    summary, positions = await wallet.reconcile_state()

    assert wallet.calls == 1
    assert summary.account_equity == 100
    assert positions[0].position_value == 100
