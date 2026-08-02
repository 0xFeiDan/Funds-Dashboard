import base64,hashlib,hmac,json
import asyncio,json,time
import httpx,websockets
from datetime import datetime,timezone
from .base import ExchangeAdapter
from .errors import AuthenticationError
from .http import ZERO,dec,request,unix_ms
from ..risk import liquidation_distance,risk_level
from ..schemas import DataSource,Exchange,MarginMode,NormalizedAccountSummary,NormalizedPosition,RiskLevel,Side
class BitgetAdapter(ExchangeAdapter):
    base_url="https://api.bitget.com"
    @property
    def product_type(self): return self.credentials.get("product_type","USDT-FUTURES")
    def _headers(self,path:str,query:dict[str,str])->dict[str,str]:
        key,secret,passphrase=(self.credentials.get(k) for k in ("api_key","api_secret","passphrase"))
        if not all((key,secret,passphrase)): raise AuthenticationError("Bitget requires a read-only API key, secret, and passphrase")
        ts=unix_ms(); full=path+("?"+"&".join(f"{k}={v}" for k,v in query.items()) if query else "")
        sign=base64.b64encode(hmac.new(secret.encode(),f"{ts}GET{full}".encode(),hashlib.sha256).digest()).decode()
        return {"ACCESS-KEY":key,"ACCESS-SIGN":sign,"ACCESS-TIMESTAMP":ts,"ACCESS-PASSPHRASE":passphrase,"Content-Type":"application/json","locale":"en-US"}
    async def _get(self,path:str,params:dict[str,str]):
        async with httpx.AsyncClient(base_url=self.base_url,timeout=10) as c:
            data=await request(c,"GET",path,params=params,headers=self._headers(path,params))
        if not isinstance(data,dict) or data.get("code")!="00000": raise AuthenticationError("Bitget rejected the read-only request")
        return data.get("data",[])
    async def _spot_assets(self)->list[dict]:
        data=await self._get("/api/v2/spot/account/assets",{"assetType":"all"})
        return data if isinstance(data,list) else []
    async def _all_account_balances(self)->list[dict]:
        data=await self._get("/api/v2/account/all-account-balance",{})
        return data if isinstance(data,list) else []
    async def stream_account_updates(self):
        key,secret,passphrase=(self.credentials.get(k) for k in ("api_key","api_secret","passphrase"))
        if not all((key,secret,passphrase)): raise AuthenticationError("Bitget requires read-only credentials")
        timestamp=str(int(time.time()*1000)); sign=base64.b64encode(hmac.new(secret.encode(),f"{timestamp}GET/user/verify".encode(),hashlib.sha256).digest()).decode()
        async with websockets.connect("wss://ws.bitget.com/v2/ws/private",ping_interval=None) as ws:
            await ws.send(json.dumps({"op":"login","args":[{"apiKey":key,"passphrase":passphrase,"timestamp":timestamp,"sign":sign}]}))
            reply=json.loads(await asyncio.wait_for(ws.recv(),timeout=10))
            if str(reply.get("code","0")) not in {"0","00000"}: raise AuthenticationError("Bitget WebSocket login rejected")
            await ws.send(json.dumps({"op":"subscribe","args":[{"instType":self.product_type,"channel":"positions","instId":"default"},{"instType":self.product_type,"channel":"account","coin":"default"}]}))
            yield {"_system":"connected"}
            while True:
                try: raw=await asyncio.wait_for(ws.recv(),timeout=25)
                except asyncio.TimeoutError: await ws.send("ping");continue
                if raw=="pong": continue
                event=json.loads(raw)
                if event.get("arg",{}).get("channel") in {"positions","account"}: yield event
    async def health_check(self)->dict: await self._get("/api/v2/mix/account/accounts",{"productType":self.product_type}); return {"ok":True,"transport":"REST"}
    async def get_account_summary(self)->NormalizedAccountSummary:
        rows,all_balances=await asyncio.gather(self._get("/api/v2/mix/account/accounts",{"productType":self.product_type}),self._all_account_balances())
        row=next((x for x in rows if dec(x.get("accountEquity"))!=0),rows[0] if rows else {})
        now=datetime.now(timezone.utc); futures_equity=dec(row.get("accountEquity")); maint=dec(row.get("crossedRiskRate"))
        total_equity=sum((dec(item.get("usdtBalance")) for item in all_balances if isinstance(item,dict)),ZERO)
        equity=total_equity if total_equity>ZERO else futures_equity
        categories=",".join(str(item.get("accountType")) for item in all_balances if isinstance(item,dict))
        return NormalizedAccountSummary(exchange=Exchange.BITGET,account_id=self.account_id,account_name=self.account_name,margin_currency="USDT",wallet_balance=equity,account_equity=equity,available_balance=dec(row.get("available")),unrealized_pnl=dec(row.get("unrealizedPL")),initial_margin=dec(row.get("locked")),maintenance_margin=ZERO,margin_ratio=maint if maint else None,total_position_notional=ZERO,updated_at=now,data_source=DataSource.REST,raw_values={"all_account_types":categories,"all_account_usdt":str(total_equity),**{k:str(row.get(k,"")) for k in ("accountEquity","available","unrealizedPL")}},field_notes={"account_equity":"Bitget all-account USDT valuation when available (spot, futures, funding, earn, bots and margin); falls back to configured futures product equity."})
    async def get_positions(self)->list[NormalizedPosition]:
        rows,spot_assets=await asyncio.gather(self._get("/api/v2/mix/position/all-position",{"productType":self.product_type}),self._spot_assets()); now=datetime.now(timezone.utc); result=[]
        for row in rows:
            size=dec(row.get("total"));
            if not size: continue
            side=Side.LONG if row.get("holdSide","long").lower()=="long" else Side.SHORT; mark=dec(row.get("markPrice")); liq=dec(row.get("liqPrice"))
            result.append(NormalizedPosition(exchange=Exchange.BITGET,account_id=self.account_id,account_name=self.account_name,symbol=row["symbol"].replace("USDT",""),exchange_symbol=row["symbol"],base_asset=row["symbol"].replace("USDT",""),settlement_asset=row.get("marginCoin","USDT"),side=side,quantity=size,position_value=dec(row.get("marketValue")) or size*mark,entry_price=dec(row.get("openPriceAvg")),mark_price=mark,unrealized_pnl=dec(row.get("unrealizedPL")),leverage=dec(row.get("leverage")),margin_mode=MarginMode.ISOLATED if row.get("marginMode")=="isolated" else MarginMode.CROSS,isolated_margin=dec(row.get("isolatedMargin")),position_margin=dec(row.get("margin")),liquidation_price=liq or None,liquidation_distance_percent=liquidation_distance(side,mark,liq or None),risk_level=risk_level(liquidation_distance(side,mark,liq or None)),updated_at=now,raw_data={k:str(v) for k,v in row.items()}))
        for asset in spot_assets:
            coin=str(asset.get("coin") or "UNKNOWN").upper(); quantity=dec(asset.get("available"))+dec(asset.get("frozen"))+dec(asset.get("locked"))
            if quantity<=0: continue
            stable=coin in {"USDT","USDC"}; mark=dec(1) if stable else None
            result.append(NormalizedPosition(exchange=Exchange.BITGET,account_id=self.account_id,account_name=self.account_name,symbol=f"现货 · {coin}",exchange_symbol=coin,base_asset=coin,settlement_asset="USDT",side=Side.LONG,quantity=quantity,position_value=quantity*mark if mark is not None else ZERO,mark_price=mark,margin_mode=MarginMode.UNKNOWN,risk_level=RiskLevel.UNKNOWN,updated_at=now,contract_type="SPOT",raw_data={k:str(v) for k,v in asset.items()}))
        return result
