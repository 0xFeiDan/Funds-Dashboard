import json
import httpx,websockets
from datetime import datetime,timezone
from .base import ExchangeAdapter
from .errors import AuthenticationError
from .http import dec,request
from ..risk import liquidation_distance,risk_level
from ..schemas import DataSource,Exchange,MarginMode,NormalizedAccountSummary,NormalizedPosition,Side
class HyperliquidAdapter(ExchangeAdapter):
    base_url="https://api.hyperliquid.xyz"
    def _address(self)->str:
        if not self.public_identifier: raise AuthenticationError("Hyperliquid requires a public wallet or vault address")
        return self.public_identifier
    async def _info(self,payload:dict):
        async with httpx.AsyncClient(base_url=self.base_url,timeout=10) as c:return await request(c,"POST","/info",json=payload)
    async def health_check(self)->dict: await self._info({"type":"clearinghouseState","user":self._address()}); return {"ok":True,"transport":"public REST"}
    async def _state(self): return await self._info({"type":"clearinghouseState","user":self._address()})
    async def get_account_summary(self)->NormalizedAccountSummary:
        state=await self._state(); summary=state.get("marginSummary",{}); now=datetime.now(timezone.utc); equity=dec(summary.get("accountValue")); used=dec(summary.get("totalMarginUsed"))
        return NormalizedAccountSummary(exchange=Exchange.HYPERLIQUID,account_id=self.account_id,account_name=self.account_name,margin_currency="USDC",wallet_balance=dec(summary.get("totalRawUsd")),account_equity=equity,available_balance=dec(state.get("withdrawable")),initial_margin=used,maintenance_margin=dec(state.get("crossMaintenanceMarginUsed")),margin_ratio=(dec(state.get("crossMaintenanceMarginUsed"))/equity if equity>0 else None),total_position_notional=dec(summary.get("totalNtlPos")),effective_leverage=(dec(summary.get("totalNtlPos"))/equity if equity>0 else None),updated_at=now,data_source=DataSource.REST,raw_values={"accountValue":str(summary.get("accountValue","")),"withdrawable":str(state.get("withdrawable",""))},field_notes={"account_equity":"Public clearinghouseState.marginSummary.accountValue for supplied address."})
    async def get_positions(self)->list[NormalizedPosition]:
        state=await self._state(); now=datetime.now(timezone.utc); result=[]
        for item in state.get("assetPositions",[]):
            row=item.get("position",{}); signed=dec(row.get("szi"));
            if not signed: continue
            side=Side.LONG if signed>0 else Side.SHORT; mark=dec(row.get("positionValue"))/abs(signed); liq=dec(row.get("liquidationPx"))
            leverage=dec((row.get("leverage") or {}).get("value")); mode=MarginMode.CROSS if (row.get("leverage") or {}).get("type")=="cross" else MarginMode.ISOLATED
            result.append(NormalizedPosition(exchange=Exchange.HYPERLIQUID,account_id=self.account_id,account_name=self.account_name,symbol=row.get("coin",""),exchange_symbol=row.get("coin",""),base_asset=row.get("coin",""),settlement_asset="USDC",side=side,quantity=abs(signed),position_value=dec(row.get("positionValue")),entry_price=dec(row.get("entryPx")),mark_price=mark,unrealized_pnl=dec(row.get("unrealizedPnl")),leverage=leverage or None,margin_mode=mode,position_margin=dec(row.get("marginUsed")),liquidation_price=liq or None,liquidation_distance_percent=liquidation_distance(side,mark,liq or None),risk_level=risk_level(liquidation_distance(side,mark,liq or None)),updated_at=now,raw_data={k:str(v) for k,v in row.items()}))
        return result
    async def stream_account_updates(self):
        address=self._address()
        async with websockets.connect("wss://api.hyperliquid.xyz/ws",ping_interval=20,ping_timeout=20) as ws:
            for subscription in ({"type":"clearinghouseState","user":address},{"type":"userFundings","user":address},{"type":"userFills","user":address},{"type":"userNonFundingLedgerUpdates","user":address}): await ws.send(json.dumps({"method":"subscribe","subscription":subscription}))
            yield {"_system":"connected"}
            while True:
                event=json.loads(await ws.recv())
                if event.get("channel") in {"clearinghouseState","userFundings","userFills","userNonFundingLedgerUpdates"}: yield event
    async def get_funding_history(self)->list[dict]:
        data=await self._info({"type":"userFunding","user":self._address()})
        return data if isinstance(data,list) else []
    async def get_trade_history(self)->list[dict]:
        data=await self._info({"type":"userFills","user":self._address()})
        return data if isinstance(data,list) else []
    async def get_income_history(self)->list[dict]:
        data=await self._info({"type":"userNonFundingLedgerUpdates","user":self._address()})
        return data if isinstance(data,list) else []
