import json
import httpx,websockets
from datetime import datetime,timezone
from .base import ExchangeAdapter
from .errors import AuthenticationError,InvalidResponseError
from .http import dec,request
from ..risk import liquidation_distance,risk_level
from ..schemas import DataSource,Exchange,MarginMode,NormalizedAccountSummary,NormalizedPosition,Side
class LighterAdapter(ExchangeAdapter):
    base_url="https://mainnet.zklighter.elliot.ai"
    def _index(self)->str:
        if not self.public_identifier: raise AuthenticationError("Lighter requires account index or public L1 address")
        return self.public_identifier
    async def _account(self):
        query={"by":"index","value":self._index()} if self._index().isdigit() else {"by":"l1_address","value":self._index()}
        async with httpx.AsyncClient(base_url=self.base_url,timeout=10) as c: data=await request(c,"GET","/api/v1/account",params=query)
        if not isinstance(data,dict): raise InvalidResponseError("Lighter account response malformed")
        return data
    async def health_check(self)->dict: await self._account(); return {"ok":True,"transport":"public REST"}
    async def get_account_summary(self)->NormalizedAccountSummary:
        row=await self._account(); now=datetime.now(timezone.utc)
        # Lighter public fields can evolve; exact received values remain in raw_values rather than invented.
        equity=dec(row.get("account_value") or row.get("equity")); balance=dec(row.get("balance") or row.get("collateral"))
        return NormalizedAccountSummary(exchange=Exchange.LIGHTER,account_id=self.account_id,account_name=self.account_name,margin_currency="USDC",wallet_balance=balance,account_equity=equity,available_balance=dec(row.get("available_balance") or row.get("available_margin")),unrealized_pnl=dec(row.get("unrealized_pnl")),initial_margin=dec(row.get("initial_margin")),maintenance_margin=dec(row.get("maintenance_margin")),total_position_notional=dec(row.get("position_value")),updated_at=now,data_source=DataSource.REST,raw_values={k:str(v) for k,v in row.items() if isinstance(v,(str,int,float))},field_notes={"account_equity":"Uses account_value/equity only when returned by official account API. Missing fields remain zero and are not estimated."})
    async def get_positions(self)->list[NormalizedPosition]:
        row=await self._account(); now=datetime.now(timezone.utc); positions=row.get("positions",[]); result=[]
        for p in positions:
            signed=dec(p.get("size") or p.get("position_size"));
            if not signed: continue
            side=Side.LONG if signed>0 else Side.SHORT; mark=dec(p.get("mark_price")); liq=dec(p.get("liquidation_price"))
            result.append(NormalizedPosition(exchange=Exchange.LIGHTER,account_id=self.account_id,account_name=self.account_name,symbol=str(p.get("symbol") or p.get("market_id","")),exchange_symbol=str(p.get("symbol") or p.get("market_id","")),base_asset=str(p.get("base_asset") or p.get("symbol") or p.get("market_id","")),settlement_asset="USDC",side=side,quantity=abs(signed),position_value=dec(p.get("position_value")) or abs(signed)*mark,entry_price=dec(p.get("entry_price")),mark_price=mark or None,unrealized_pnl=dec(p.get("unrealized_pnl")),realized_pnl=dec(p.get("realized_pnl")),leverage=dec(p.get("leverage")) or None,margin_mode=MarginMode.ISOLATED if p.get("margin_mode")=="isolated" else MarginMode.CROSS,position_margin=dec(p.get("margin")),liquidation_price=liq or None,liquidation_distance_percent=liquidation_distance(side,mark,liq or None),risk_level=risk_level(liquidation_distance(side,mark,liq or None)),updated_at=now,raw_data={k:str(v) for k,v in p.items()}))
        return result
    async def stream_account_updates(self):
        account_id=self._index()
        if not account_id.isdigit(): raise AuthenticationError("Use an explicit numeric Lighter account index for realtime public streams")
        async with websockets.connect("wss://mainnet.zklighter.elliot.ai/stream?readonly=true",ping_interval=20,ping_timeout=20) as ws:
            await ws.send(json.dumps({"type":"subscribe","channel":f"account_all/{account_id}"}))
            await ws.send(json.dumps({"type":"subscribe","channel":f"user_stats/{account_id}"}))
            yield {"_system":"connected"}
            while True:
                event=json.loads(await ws.recv())
                if event.get("type") in {"update/account_all","update/account","update/user_stats"}: yield event
