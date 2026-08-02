from datetime import datetime, timezone
from decimal import Decimal

import httpx

from .base import ExchangeAdapter
from .errors import AuthenticationError, InvalidResponseError
from .http import ZERO, dec, request
from ..schemas import DataSource, Exchange, MarginMode, NormalizedAccountSummary, NormalizedPosition, RiskLevel, Side


class OnchainAdapter(ExchangeAdapter):
    chain = ""
    native_symbol = ""
    explorer = ""

    def _address(self) -> str:
        if not self.public_identifier:
            raise AuthenticationError(f"{self.chain} requires a public address")
        return self.public_identifier.strip()

    async def _price(self) -> Decimal | None:
        symbol = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}.get(self.native_symbol)
        if not symbol:
            return None
        try:
            async with httpx.AsyncClient(base_url="https://api.binance.com", timeout=10) as client:
                row = await request(client, "GET", "/api/v3/ticker/price", params={"symbol": symbol})
            return dec(row.get("price")) if isinstance(row, dict) else None
        except Exception:
            return None

    async def health_check(self) -> dict:
        await self._balances()
        return {"ok": True, "transport": "public chain indexer"}

    async def _balances(self) -> list[tuple[str, Decimal, Decimal | None, str]]:
        raise NotImplementedError

    async def get_account_summary(self) -> NormalizedAccountSummary:
        balances = await self._balances(); equity = sum((quantity * price for _, quantity, price, _ in balances if price is not None), ZERO)
        return NormalizedAccountSummary(exchange=Exchange(self.chain), account_id=self.account_id, account_name=self.account_name, margin_currency="USD", wallet_balance=equity, account_equity=equity, available_balance=equity, updated_at=datetime.now(timezone.utc), data_source=DataSource.REST, raw_values={"assets": str(len(balances))}, field_notes={"account_equity": "Only assets with a public USD price are included; unpriced tokens remain visible."})

    async def get_positions(self) -> list[NormalizedPosition]:
        now = datetime.now(timezone.utc); output=[]
        for symbol, quantity, price, kind in await self._balances():
            if quantity <= 0: continue
            output.append(NormalizedPosition(exchange=Exchange(self.chain), account_id=self.account_id, account_name=self.account_name, symbol=f"{self.chain} · {symbol}", exchange_symbol=symbol, base_asset=symbol, settlement_asset="USD", side=Side.LONG, quantity=quantity, position_value=quantity * price if price is not None else ZERO, mark_price=price, margin_mode=MarginMode.UNKNOWN, risk_level=RiskLevel.UNKNOWN, updated_at=now, contract_type=kind, raw_data={"chain": self.chain}))
        return output


class BitcoinAdapter(OnchainAdapter):
    chain = "bitcoin"; native_symbol = "BTC"; explorer = "https://mempool.space"
    async def _balances(self):
        async with httpx.AsyncClient(base_url=self.explorer, timeout=12) as client:
            data = await request(client, "GET", f"/api/address/{self._address()}")
        if not isinstance(data, dict): raise InvalidResponseError("Bitcoin address response malformed")
        confirmed = dec(data.get("chain_stats", {}).get("funded_txo_sum")) - dec(data.get("chain_stats", {}).get("spent_txo_sum"))
        pending = dec(data.get("mempool_stats", {}).get("funded_txo_sum")) - dec(data.get("mempool_stats", {}).get("spent_txo_sum"))
        price=await self._price(); rows=[("BTC", confirmed / Decimal("100000000"), price, "ONCHAIN_NATIVE")]
        if pending: rows.append(("BTC（待确认）", pending / Decimal("100000000"), price, "ONCHAIN_NATIVE"))
        return rows


class EvmAdapter(OnchainAdapter):
    async def _balances(self):
        address = self._address()
        async with httpx.AsyncClient(base_url=self.explorer, timeout=15) as client:
            address_row, tokens = await __import__("asyncio").gather(request(client, "GET", f"/api/v2/addresses/{address}"), request(client, "GET", f"/api/v2/addresses/{address}/token-balances"))
        if not isinstance(address_row, dict) or not isinstance(tokens, list): raise InvalidResponseError(f"{self.chain} address response malformed")
        native_raw = dec(address_row.get("coin_balance")); native = native_raw / Decimal("1000000000000000000")
        result=[("ETH", native, await self._price(), "ONCHAIN_NATIVE")]
        for row in tokens:
            token = row.get("token", {}) if isinstance(row, dict) else {}; decimals = int(token.get("decimals") or 0); quantity = dec(row.get("value")) / (Decimal(10) ** decimals) if decimals >= 0 else ZERO
            symbol = str(token.get("symbol") or token.get("name") or "ERC-20").upper()
            # Dollar stablecoins are a reporting-currency bucket, not dust.
            result.append((symbol, quantity, Decimal("1") if symbol in {"USDT", "USDC"} else None, "ERC20"))
        return result


class EthereumAdapter(EvmAdapter):
    chain = "ethereum"; native_symbol = "ETH"; explorer = "https://eth.blockscout.com"


class ArbitrumAdapter(EvmAdapter):
    chain = "arbitrum"; native_symbol = "ETH"; explorer = "https://arbitrum.blockscout.com"


class SolanaAdapter(OnchainAdapter):
    """Public-address reader for native SOL and SPL token-account balances."""

    chain = "solana"; native_symbol = "SOL"; explorer = "https://api.mainnet-beta.solana.com"
    _token_programs = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
    _known_tokens = {
        "So11111111111111111111111111111111111111112": ("SOL", None),
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": ("USDC", Decimal("1")),
        "Es9vMFrzaCERmJfrF4H2FYD8q5jD3S9pB9oszkKCNghB": ("USDT", Decimal("1")),
    }

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: list[object]) -> object:
        payload = await request(client, "POST", "/", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if not isinstance(payload, dict) or payload.get("error") or "result" not in payload:
            raise InvalidResponseError(f"Solana {method} response malformed")
        return payload["result"]

    async def _balances(self) -> list[tuple[str, Decimal, Decimal | None, str]]:
        address = self._address()
        options = {"encoding": "jsonParsed", "commitment": "finalized"}
        async with httpx.AsyncClient(base_url=self.explorer, timeout=15) as client:
            native, *token_results = await __import__("asyncio").gather(
                self._rpc(client, "getBalance", [address, {"commitment": "finalized"}]),
                *(self._rpc(client, "getTokenAccountsByOwner", [address, {"programId": program}, options]) for program in self._token_programs),
            )
        if not isinstance(native, dict):
            raise InvalidResponseError("Solana balance response malformed")
        sol_price = await self._price()
        rows: list[tuple[str, Decimal, Decimal | None, str]] = [("SOL", dec(native.get("value")) / Decimal("1000000000"), sol_price, "ONCHAIN_NATIVE")]
        totals: dict[str, Decimal] = {}
        for result in token_results:
            values = result.get("value") if isinstance(result, dict) else None
            if not isinstance(values, list):
                raise InvalidResponseError("Solana token-account response malformed")
            for account in values:
                info = account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}) if isinstance(account, dict) else {}
                amount = info.get("tokenAmount", {}) if isinstance(info, dict) else {}
                mint = str(info.get("mint") or "")
                quantity = dec(amount.get("uiAmountString"))
                if mint and quantity > ZERO:
                    totals[mint] = totals.get(mint, ZERO) + quantity
        for mint, quantity in totals.items():
            symbol, price = self._known_tokens.get(mint, (f"SPL-{mint[:6]}", None))
            rows.append((symbol, quantity, sol_price if mint == "So11111111111111111111111111111111111111112" else price, "SPL"))
        return rows
