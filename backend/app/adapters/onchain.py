import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from .base import ExchangeAdapter
from .errors import AuthenticationError, InvalidResponseError
from .http import ZERO, dec, request
from ..config import ankr_bitcoin_blockbook_url, ankr_chain_rpc_url, settings
from ..schemas import DataSource, Exchange, MarginMode, NormalizedAccountSummary, NormalizedPosition, RiskLevel, Side


class OnchainAdapter(ExchangeAdapter):
    chain = ""
    native_symbol = ""
    explorer = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._balances_task: asyncio.Task[list[tuple[str, Decimal, Decimal | None, str]]] | None = None
        self._balances_result: list[tuple[str, Decimal, Decimal | None, str]] | None = None

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

    async def _fetch_balances(self) -> list[tuple[str, Decimal, Decimal | None, str]]:
        raise NotImplementedError

    async def _balances(self) -> list[tuple[str, Decimal, Decimal | None, str]]:
        if self._balances_result is not None:
            return self._balances_result
        if self._balances_task is None:
            self._balances_task = asyncio.create_task(self._fetch_balances())
        task = self._balances_task
        try:
            self._balances_result = await asyncio.shield(task)
            return self._balances_result
        finally:
            if task.done() and self._balances_task is task:
                self._balances_task = None

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

    @property
    def blockbook_url(self) -> str | None:
        return settings.bitcoin_blockbook_url or ankr_bitcoin_blockbook_url()

    async def _fetch_balances(self):
        if self.blockbook_url:
            async with httpx.AsyncClient(base_url=self.blockbook_url, timeout=12) as client:
                data = await request(client, "GET", f"/api/v2/address/{self._address()}", params={"details": "basic"})
            if not isinstance(data, dict):
                raise InvalidResponseError("Bitcoin Blockbook address response malformed")
            confirmed = dec(data.get("balance"))
            pending = dec(data.get("unconfirmedBalance"))
        else:
            async with httpx.AsyncClient(base_url=self.explorer, timeout=12) as client:
                data = await request(client, "GET", f"/api/address/{self._address()}")
            if not isinstance(data, dict): raise InvalidResponseError("Bitcoin address response malformed")
            confirmed = dec(data.get("chain_stats", {}).get("funded_txo_sum")) - dec(data.get("chain_stats", {}).get("spent_txo_sum"))
            pending = dec(data.get("mempool_stats", {}).get("funded_txo_sum")) - dec(data.get("mempool_stats", {}).get("spent_txo_sum"))
        price=await self._price(); rows=[("BTC", confirmed / Decimal("100000000"), price, "ONCHAIN_NATIVE")]
        if pending: rows.append(("BTC（待确认）", pending / Decimal("100000000"), price, "ONCHAIN_NATIVE"))
        return rows


class EvmAdapter(OnchainAdapter):
    token_rpc_url: str | None = None
    chain_rpc_url: str | None = None

    async def _native_rpc_balance(self, address: str) -> Decimal:
        if not self.chain_rpc_url:
            raise InvalidResponseError(f"{self.chain} chain RPC is not configured")
        async with httpx.AsyncClient(base_url=self.chain_rpc_url, timeout=12) as client:
            payload = await request(client, "POST", "/", json={"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance", "params": [address, "latest"]})
        raw = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(raw, str) or not raw.startswith("0x"):
            raise InvalidResponseError(f"{self.chain} native-balance response malformed")
        return Decimal(int(raw, 16)) / Decimal("1000000000000000000")

    async def _ankr_account_balances(self, address: str) -> list[tuple[str, Decimal, Decimal | None, str]]:
        """Use Ankr's indexed token endpoint when a private endpoint is configured.

        A normal EVM RPC can read the native balance, but cannot efficiently
        enumerate every ERC-20 held by an address.  The indexed endpoint does
        both in one paginated request family.
        """
        if not self.token_rpc_url:
            return []
        rows: list[tuple[str, Decimal, Decimal | None, str]] = []
        page_token: str | None = None
        async with httpx.AsyncClient(base_url=self.token_rpc_url, timeout=15) as client:
            while True:
                params: dict[str, object] = {
                    "blockchain": self.chain,
                    "walletAddress": address,
                    "nativeFirst": True,
                    "onlyWhitelisted": True,
                    "pageSize": 100,
                }
                if page_token:
                    params["pageToken"] = page_token
                payload = await request(client, "POST", "/", json={"jsonrpc": "2.0", "id": 1, "method": "ankr_getAccountBalance", "params": params})
                result = payload.get("result") if isinstance(payload, dict) else None
                assets = result.get("assets") if isinstance(result, dict) else None
                if not isinstance(assets, list):
                    raise InvalidResponseError(f"{self.chain} token-balance response malformed")
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    symbol = str(asset.get("tokenSymbol") or asset.get("tokenName") or "ERC-20").upper()
                    quantity = dec(asset.get("balance"))
                    if quantity <= ZERO:
                        continue
                    price = Decimal("1") if symbol in {"USDT", "USDC"} else dec(asset.get("tokenPrice")) or None
                    token_type = str(asset.get("tokenType") or "").upper()
                    kind = "ONCHAIN_NATIVE" if token_type in {"NATIVE", "NATIVE_TOKEN"} else "ERC20"
                    rows.append((symbol, quantity, price, kind))
                next_token = result.get("nextPageToken") if isinstance(result, dict) else None
                if not isinstance(next_token, str) or not next_token or next_token == page_token:
                    break
                page_token = next_token
        return rows

    async def _fetch_balances(self):
        address = self._address()
        if self.token_rpc_url:
            return await self._ankr_account_balances(address)
        async with httpx.AsyncClient(base_url=self.explorer, timeout=15) as client:
            tasks = [request(client, "GET", f"/api/v2/addresses/{address}/token-balances")]
            if self.chain_rpc_url:
                tasks.append(self._native_rpc_balance(address))
            values = await __import__("asyncio").gather(*tasks, return_exceptions=True)
            tokens = values[0]
            native = values[1] if len(values) > 1 else None
            if isinstance(native, Exception) or native is None:
                address_row = await request(client, "GET", f"/api/v2/addresses/{address}")
                native = dec(address_row.get("coin_balance")) / Decimal("1000000000000000000") if isinstance(address_row, dict) else None
        if not isinstance(tokens, list) or not isinstance(native, Decimal): raise InvalidResponseError(f"{self.chain} address response malformed")
        result=[("ETH", native, await self._price(), "ONCHAIN_NATIVE")]
        for row in tokens:
            token = row.get("token", {}) if isinstance(row, dict) else {}; decimals = int(token.get("decimals") or 0); quantity = dec(row.get("value")) / (Decimal(10) ** decimals) if decimals >= 0 else ZERO
            symbol = str(token.get("symbol") or token.get("name") or "ERC-20").upper()
            # Dollar stablecoins are a reporting-currency bucket, not dust.
            result.append((symbol, quantity, Decimal("1") if symbol in {"USDT", "USDC"} else None, "ERC20"))
        return result


class EthereumAdapter(EvmAdapter):
    chain = "ethereum"; native_symbol = "ETH"; explorer = "https://eth.blockscout.com"

    @property
    def token_rpc_url(self) -> str | None:
        return settings.ethereum_token_rpc_url

    @property
    def chain_rpc_url(self) -> str | None:
        return settings.ethereum_rpc_url or ankr_chain_rpc_url("eth")


class ArbitrumAdapter(EvmAdapter):
    chain = "arbitrum"; native_symbol = "ETH"; explorer = "https://arbitrum.blockscout.com"

    @property
    def token_rpc_url(self) -> str | None:
        return settings.arbitrum_token_rpc_url

    @property
    def chain_rpc_url(self) -> str | None:
        return ankr_chain_rpc_url("arbitrum")


class SolanaAdapter(OnchainAdapter):
    """Public-address reader for native SOL and SPL token-account balances."""

    chain = "solana"; native_symbol = "SOL"; explorer = "https://api.mainnet-beta.solana.com"
    _token_programs = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
    _known_tokens = {
        "So11111111111111111111111111111111111111112": ("SOL", None),
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": ("USDC", Decimal("1")),
        "Es9vMFrzaCERmJfrF4H2FYD8q5jD3S9pB9oszkKCNghB": ("USDT", Decimal("1")),
    }

    @property
    def rpc_url(self) -> str:
        return settings.solana_rpc_url or ankr_chain_rpc_url("solana") or self.explorer

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: list[object]) -> object:
        payload = await request(client, "POST", "/", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if not isinstance(payload, dict) or payload.get("error") or "result" not in payload:
            raise InvalidResponseError(f"Solana {method} response malformed")
        return payload["result"]

    async def _fetch_balances(self) -> list[tuple[str, Decimal, Decimal | None, str]]:
        address = self._address()
        options = {"encoding": "jsonParsed", "commitment": "finalized"}
        async with httpx.AsyncClient(base_url=self.rpc_url, timeout=15) as client:
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
