import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import websockets

from .base import ExchangeAdapter
from .errors import AuthenticationError
from .http import dec, request
from ..risk import liquidation_distance, risk_level
from ..schemas import DataSource, Exchange, MarginMode, NormalizedAccountSummary, NormalizedPosition, RiskLevel, Side


class HyperliquidAdapter(ExchangeAdapter):
    """Read every publicly queryable Hyperliquid balance for one master address.

    This includes the master address, discovered subaccounts, the default and
    builder-deployed perp DEXs, spot balances, and user vault equities.
    """

    base_url = "https://api.hyperliquid.xyz"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache: tuple[datetime, dict] | None = None

    def _address(self) -> str:
        if not self.public_identifier:
            raise AuthenticationError("Hyperliquid requires a public wallet or vault address")
        return self.public_identifier.strip()

    async def _info(self, payload: dict):
        async with httpx.AsyncClient(base_url=self.base_url, timeout=12) as client:
            return await request(client, "POST", "/info", json=payload)

    async def health_check(self) -> dict:
        await self._info({"type": "clearinghouseState", "user": self._address()})
        return {"ok": True, "transport": "public REST"}

    async def _perp_dexes(self) -> list[str]:
        raw = await self._info({"type": "perpDexs"})
        names = [""]
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.append(item["name"])
        return list(dict.fromkeys(names))

    async def _addresses(self) -> list[tuple[str, str]]:
        master = self._address()
        rows: list[tuple[str, str]] = [(master, "主账户")]
        raw = await self._info({"type": "subAccounts", "user": master})
        if isinstance(raw, list):
            for index, item in enumerate(raw, start=1):
                if isinstance(item, dict) and isinstance(item.get("subAccountUser"), str):
                    rows.append((item["subAccountUser"], item.get("name") or f"子账户 {index}"))
        return list(dict.fromkeys(rows))

    @staticmethod
    def _spot_prices(meta: object, mids: object) -> dict[str, object]:
        prices: dict[str, object] = {"USDC": dec("1")}
        if not isinstance(meta, dict) or not isinstance(mids, dict):
            return prices
        tokens = {item.get("index"): item.get("name") for item in meta.get("tokens", []) if isinstance(item, dict)}
        for pair in meta.get("universe", []):
            if not isinstance(pair, dict):
                continue
            pair_tokens = pair.get("tokens") or []
            if len(pair_tokens) != 2 or tokens.get(pair_tokens[1]) != "USDC":
                continue
            name, mid = tokens.get(pair_tokens[0]), mids.get(pair.get("name"))
            if isinstance(name, str) and mid not in (None, ""):
                prices[name] = dec(mid)
        return prices

    async def _snapshot(self) -> dict:
        now = datetime.now(timezone.utc)
        if self._cache and now - self._cache[0] < timedelta(seconds=10):
            return self._cache[1]
        addresses, dexs = await asyncio.gather(self._addresses(), self._perp_dexes())
        spot_meta, mids = await asyncio.gather(self._info({"type": "spotMeta"}), self._info({"type": "allMids"}))
        spot_prices = self._spot_prices(spot_meta, mids)
        states: list[dict] = []
        spots: list[dict] = []
        vaults: list[dict] = []
        staking: list[dict] = []
        for address, label in addresses:
            requests = [self._info({"type": "clearinghouseState", "user": address, "dex": dex}) for dex in dexs]
            requests.append(self._info({"type": "spotClearinghouseState", "user": address}))
            requests.append(self._info({"type": "userVaultEquities", "user": address}))
            requests.append(self._info({"type": "delegatorSummary", "user": address}))
            results = await asyncio.gather(*requests)
            for dex, state in zip(dexs, results[:len(dexs)]):
                if isinstance(state, dict):
                    states.append({"address": address, "label": label, "dex": dex, "state": state})
            spot_state = results[-3]
            if isinstance(spot_state, dict):
                spots.append({"address": address, "label": label, "state": spot_state})
            vault_rows = results[-2]
            if isinstance(vault_rows, list):
                vaults.extend({"address": address, "label": label, "row": row} for row in vault_rows if isinstance(row, dict))
            stake = results[-1]
            if isinstance(stake, dict):
                staking.append({"address": address, "label": label, "summary": stake})
        value = {"states": states, "spots": spots, "vaults": vaults, "staking": staking, "spot_prices": spot_prices, "at": now}
        self._cache = now, value
        return value

    def _perp_positions(self, snapshot: dict) -> list[NormalizedPosition]:
        now = snapshot["at"]
        output: list[NormalizedPosition] = []
        for item in snapshot["states"]:
            dex, state = item["dex"], item["state"]
            for wrapped in state.get("assetPositions", []):
                row = wrapped.get("position", {}) if isinstance(wrapped, dict) else {}
                signed = dec(row.get("szi"))
                if not signed:
                    continue
                side = Side.LONG if signed > 0 else Side.SHORT
                value = abs(dec(row.get("positionValue")))
                mark = value / abs(signed) if signed else None
                liq = dec(row.get("liquidationPx")) or None
                leverage_data = row.get("leverage") or {}
                leverage = dec(leverage_data.get("value")) or None
                mode = MarginMode.CROSS if leverage_data.get("type") == "cross" else MarginMode.ISOLATED
                coin = str(row.get("coin") or "UNKNOWN")
                symbol = f"{dex}:{coin}" if dex else coin
                output.append(NormalizedPosition(
                    exchange=Exchange.HYPERLIQUID, account_id=self.account_id,
                    account_name=f"{self.account_name} · {item['label']}", symbol=symbol,
                    exchange_symbol=symbol, base_asset=coin, settlement_asset="USDC", side=side,
                    quantity=abs(signed), position_value=value, entry_price=dec(row.get("entryPx")) or None,
                    mark_price=mark, unrealized_pnl=dec(row.get("unrealizedPnl")), leverage=leverage,
                    margin_mode=mode, position_margin=dec(row.get("marginUsed")), liquidation_price=liq,
                    liquidation_distance_percent=liquidation_distance(side, mark, liq),
                    risk_level=risk_level(liquidation_distance(side, mark, liq)), updated_at=now,
                    contract_type="PERPETUAL", raw_data={k: str(v) for k, v in row.items()},
                ))
        return output

    def _spot_positions(self, snapshot: dict) -> list[NormalizedPosition]:
        now, prices = snapshot["at"], snapshot["spot_prices"]
        output: list[NormalizedPosition] = []
        for item in snapshot["spots"]:
            balances = item["state"].get("balances", [])
            for balance in balances if isinstance(balances, list) else []:
                if not isinstance(balance, dict):
                    continue
                quantity = dec(balance.get("total"))
                if quantity <= 0:
                    continue
                coin, mark = str(balance.get("coin") or "UNKNOWN"), prices.get(balance.get("coin"))
                mark_value = mark if mark is not None else None
                output.append(NormalizedPosition(
                    exchange=Exchange.HYPERLIQUID, account_id=self.account_id,
                    account_name=f"{self.account_name} · {item['label']}", symbol=f"现货 · {coin}",
                    exchange_symbol=coin, base_asset=coin, settlement_asset="USDC", side=Side.LONG,
                    quantity=quantity, position_value=quantity * mark_value if mark_value is not None else dec(0),
                    mark_price=mark_value, margin_mode=MarginMode.UNKNOWN, risk_level=RiskLevel.UNKNOWN,
                    updated_at=now, contract_type="SPOT", raw_data={k: str(v) for k, v in balance.items()},
                ))
        return output

    def _vault_positions(self, snapshot: dict) -> list[NormalizedPosition]:
        now = snapshot["at"]
        output: list[NormalizedPosition] = []
        for item in snapshot["vaults"]:
            row = item["row"]
            equity = dec(row.get("equity"))
            if equity <= 0:
                continue
            address = str(row.get("vaultAddress") or "unknown")
            output.append(NormalizedPosition(
                exchange=Exchange.HYPERLIQUID, account_id=self.account_id,
                account_name=f"{self.account_name} · {item['label']}", symbol=f"Vault · {address[:10]}…",
                exchange_symbol=address, base_asset="VAULT", settlement_asset="USDC", side=Side.LONG,
                quantity=equity, position_value=equity, mark_price=dec(1), margin_mode=MarginMode.UNKNOWN,
                risk_level=RiskLevel.UNKNOWN, updated_at=now, contract_type="VAULT_EQUITY",
                raw_data={"vault_address": address, "equity": str(equity)},
            ))
        return output

    def _staking_positions(self, snapshot: dict) -> list[NormalizedPosition]:
        """Represent staked and pending-unstake HYPE as priced assets."""
        now, hype_price = snapshot["at"], snapshot["spot_prices"].get("HYPE")
        output: list[NormalizedPosition] = []
        for item in snapshot["staking"]:
            summary = item["summary"]
            for field, label in (("delegated", "已质押"), ("undelegated", "待质押"), ("totalPendingWithdrawal", "解除质押中")):
                quantity = dec(summary.get(field))
                if quantity <= 0:
                    continue
                output.append(NormalizedPosition(
                    exchange=Exchange.HYPERLIQUID, account_id=self.account_id,
                    account_name=f"{self.account_name} · {item['label']}", symbol=f"HYPE 质押 · {label}",
                    exchange_symbol="HYPE", base_asset="HYPE", settlement_asset="USDC", side=Side.LONG,
                    quantity=quantity, position_value=quantity * hype_price if hype_price is not None else dec(0),
                    mark_price=hype_price, margin_mode=MarginMode.UNKNOWN, risk_level=RiskLevel.UNKNOWN,
                    updated_at=now, contract_type="STAKING", raw_data={"category": field, "quantity": str(quantity)},
                ))
        return output

    async def get_account_summary(self) -> NormalizedAccountSummary:
        snapshot = await self._snapshot()
        positions = [*self._perp_positions(snapshot), *self._spot_positions(snapshot), *self._vault_positions(snapshot), *self._staking_positions(snapshot)]
        perp_equity = sum((dec(item["state"].get("marginSummary", {}).get("accountValue")) for item in snapshot["states"]), dec(0))
        spot_value = sum((position.position_value for position in positions if position.contract_type == "SPOT"), dec(0))
        vault_value = sum((position.position_value for position in positions if position.contract_type == "VAULT_EQUITY"), dec(0))
        staking_value = sum((position.position_value for position in positions if position.contract_type == "STAKING"), dec(0))
        available = sum((dec(item["state"].get("withdrawable")) for item in snapshot["states"]), dec(0))
        unknown_spot = sum(1 for position in positions if position.contract_type == "SPOT" and not position.mark_price)
        return NormalizedAccountSummary(
            exchange=Exchange.HYPERLIQUID, account_id=self.account_id, account_name=self.account_name,
            margin_currency="USD", wallet_balance=spot_value + vault_value + staking_value, account_equity=perp_equity + spot_value + vault_value + staking_value,
            available_balance=available, unrealized_pnl=sum((position.unrealized_pnl for position in positions), dec(0)),
            initial_margin=sum((position.position_margin or dec(0) for position in positions if position.contract_type == "PERPETUAL"), dec(0)),
            maintenance_margin=sum((dec(item["state"].get("crossMaintenanceMarginUsed")) for item in snapshot["states"]), dec(0)),
            total_position_notional=sum((position.position_value for position in positions if position.contract_type == "PERPETUAL"), dec(0)),
            effective_leverage=None, updated_at=snapshot["at"], data_source=DataSource.REST,
            raw_values={"perp_dexes": str(len(snapshot["states"])), "spot_assets": str(sum(1 for p in positions if p.contract_type == "SPOT")), "vaults": str(sum(1 for p in positions if p.contract_type == "VAULT_EQUITY")), "staking_entries": str(sum(1 for p in positions if p.contract_type == "STAKING"))},
            field_notes={"account_equity": "Perp DEX account values plus priced Spot balances, Vault equities and HYPE staking. Assets without an official mid price are displayed but excluded from USD totals.", "unknown_spot_prices": str(unknown_spot)},
        )

    async def get_positions(self) -> list[NormalizedPosition]:
        snapshot = await self._snapshot()
        return [*self._perp_positions(snapshot), *self._spot_positions(snapshot), *self._vault_positions(snapshot), *self._staking_positions(snapshot)]

    async def stream_account_updates(self):
        address = self._address()
        async with websockets.connect("wss://api.hyperliquid.xyz/ws", ping_interval=20, ping_timeout=20) as ws:
            subscriptions = (
                {"type": "allDexsClearinghouseState", "user": address}, {"type": "spotState", "user": address},
                {"type": "userFundings", "user": address}, {"type": "userFills", "user": address},
                {"type": "userNonFundingLedgerUpdates", "user": address},
            )
            for subscription in subscriptions:
                await ws.send(json.dumps({"method": "subscribe", "subscription": subscription}))
            yield {"_system": "connected"}
            while True:
                event = json.loads(await ws.recv())
                if event.get("channel") in {"allDexsClearinghouseState", "spotState", "userFundings", "userFills", "userNonFundingLedgerUpdates"}:
                    self._cache = None
                    yield event

    async def get_funding_history(self) -> list[dict]:
        data = await self._info({"type": "userFunding", "user": self._address()})
        return data if isinstance(data, list) else []

    async def get_trade_history(self) -> list[dict]:
        data = await self._info({"type": "userFills", "user": self._address()})
        return data if isinstance(data, list) else []

    async def get_income_history(self) -> list[dict]:
        data = await self._info({"type": "userNonFundingLedgerUpdates", "user": self._address()})
        return data if isinstance(data, list) else []
