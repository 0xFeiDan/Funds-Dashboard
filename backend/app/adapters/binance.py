import asyncio,json
import httpx,websockets
from datetime import datetime,timezone
from decimal import Decimal
from .base import ExchangeAdapter
from .errors import AuthenticationError
from .http import ZERO,dec,hmac_sha256,request,unix_ms
from ..risk import effective_leverage,liquidation_distance,risk_level
from ..schemas import DataSource,Exchange,MarginMode,NormalizedAccountSummary,NormalizedPosition,RiskLevel,Side

class BinanceAdapter(ExchangeAdapter):
    base_url="https://fapi.binance.com"
    spot_base_url="https://api.binance.com"
    def _signed(self,params:dict[str,object])->dict[str,str]:
        key,secret=self.credentials.get("api_key"),self.credentials.get("api_secret")
        if not key or not secret: raise AuthenticationError("Binance requires a read-only API key and secret")
        payload={**params,"timestamp":unix_ms(),"recvWindow":"5000"}; payload["signature"]=hmac_sha256(secret,payload); return payload
    async def _get(self,path:str,params:dict|None=None):
            async with httpx.AsyncClient(base_url=self.base_url,timeout=10) as c:return await request(c,"GET",path,params=self._signed(params or {}),headers={"X-MBX-APIKEY":self.credentials["api_key"]})
    async def _spot_account(self)->list[dict]:
        async with httpx.AsyncClient(base_url=self.spot_base_url,timeout=10) as c: data=await request(c,"GET","/api/v3/account",params=self._signed({}),headers={"X-MBX-APIKEY":self.credentials["api_key"]})
        return data.get("balances",[]) if isinstance(data,dict) else []
    async def _spot_prices(self)->dict[str,Decimal]:
        async with httpx.AsyncClient(base_url=self.spot_base_url,timeout=10) as c: rows=await request(c,"GET","/api/v3/ticker/price")
        prices={"USDT":Decimal("1"),"USDC":Decimal("1"),"FDUSD":Decimal("1"),"TUSD":Decimal("1")}
        for row in rows if isinstance(rows,list) else []:
            symbol=str(row.get("symbol") or ""); price=dec(row.get("price"))
            for quote in ("USDT","USDC","FDUSD","TUSD"):
                if symbol.endswith(quote) and len(symbol)>len(quote) and price>0: prices.setdefault(symbol[:-len(quote)],price)
        return prices
    async def _spot_snapshot(self)->tuple[list[dict],dict[str,Decimal],str|None]:
        results=await asyncio.gather(self._spot_account(),self._spot_prices(),return_exceptions=True); error=next((x for x in results if isinstance(x,Exception)),None)
        return ([],{},error.__class__.__name__) if error else (results[0],results[1],None)
    async def _listen_key(self)->str:
        key=self.credentials.get("api_key")
        if not key: raise AuthenticationError("Binance requires a read-only API key")
        async with httpx.AsyncClient(base_url=self.base_url,timeout=10) as c:
            data=await request(c,"POST","/fapi/v1/listenKey",headers={"X-MBX-APIKEY":key})
        if not isinstance(data,dict) or not data.get("listenKey"): raise AuthenticationError("Binance did not issue a listen key")
        return str(data["listenKey"])
    async def _keepalive(self,listen_key:str)->None:
        async with httpx.AsyncClient(base_url=self.base_url,timeout=10) as c: await request(c,"PUT","/fapi/v1/listenKey",headers={"X-MBX-APIKEY":self.credentials["api_key"]})
    async def stream_account_updates(self):
        listen_key=await self._listen_key(); last_keepalive=0.0
        async with websockets.connect(f"wss://fstream.binance.com/ws/{listen_key}",ping_interval=20,ping_timeout=20) as ws:
            yield {"_system":"connected"}
            while True:
                try: raw=await asyncio.wait_for(ws.recv(),timeout=30)
                except asyncio.TimeoutError:
                    if asyncio.get_running_loop().time()-last_keepalive>3000: await self._keepalive(listen_key);last_keepalive=asyncio.get_running_loop().time()
                    continue
                event=json.loads(raw)
                if event.get("e") in {"ACCOUNT_UPDATE","ACCOUNT_CONFIG_UPDATE","MARGIN_CALL","listenKeyExpired"}: yield event
    async def get_income_history(self)->list[dict]:
        data=await self._get("/fapi/v1/income",{"limit":"1000"})
        return data if isinstance(data,list) else []
    async def get_trade_history(self)->list[dict]:
        data=await self._get("/fapi/v1/userTrades",{"limit":"1000"})
        return data if isinstance(data,list) else []
    async def health_check(self)->dict:
        await self._get("/fapi/v1/accountConfig"); return {"ok":True,"transport":"REST"}
    async def get_account_summary(self)->NormalizedAccountSummary:
        data,(balances,prices,spot_error)=await asyncio.gather(self._get("/fapi/v3/account"),self._spot_snapshot()); now=datetime.now(timezone.utc)
        equity=dec(data.get("totalMarginBalance")); wallet=dec(data.get("totalWalletBalance")); total=dec(data.get("totalPositionInitialMargin"))
        spot_total=sum(((dec(row.get("free"))+dec(row.get("locked")))*prices.get(str(row.get("asset") or ""),ZERO) for row in balances),ZERO)
        spot_available=sum((dec(row.get("free"))*prices.get(str(row.get("asset") or ""),ZERO) for row in balances),ZERO)
        note="USD-M margin balance plus Spot assets priced from public stable-quote tickers; unpriced Spot remains visible but excluded from USD totals."
        if spot_error: note=f"Spot read failed ({spot_error}); totals contain USD-M futures only."
        return NormalizedAccountSummary(exchange=Exchange.BINANCE,account_id=self.account_id,account_name=self.account_name,margin_currency="USD",wallet_balance=wallet+spot_total,account_equity=equity+spot_total,available_balance=dec(data.get("availableBalance"))+spot_available,unrealized_pnl=dec(data.get("totalUnrealizedProfit")),initial_margin=total,maintenance_margin=dec(data.get("totalMaintMargin")),margin_ratio=(dec(data.get("totalMaintMargin"))/equity if equity>0 else None),total_position_notional=ZERO,updated_at=now,data_source=DataSource.REST,raw_values={"spot_assets":str(len(balances)),"spot_sync_error":spot_error or ""},field_notes={"account_equity":note})
        return NormalizedAccountSummary(exchange=Exchange.BINANCE,account_id=self.account_id,account_name=self.account_name,margin_currency="USD",wallet_balance=wallet,account_equity=equity,available_balance=dec(data.get("availableBalance")),unrealized_pnl=dec(data.get("totalUnrealizedProfit")),initial_margin=total,maintenance_margin=dec(data.get("totalMaintMargin")),margin_ratio=(dec(data.get("totalMaintMargin"))/equity if equity>0 else None),total_position_notional=ZERO,updated_at=now,data_source=DataSource.REST,raw_values={k:str(data.get(k,"")) for k in ("totalWalletBalance","totalMarginBalance","availableBalance")},field_notes={"account_equity":"Binance totalMarginBalance; USDⓈ-M aggregate, do not combine with non-USD accounts."})
    async def get_positions(self)->list[NormalizedPosition]:
        rows,(balances,prices,_)=await asyncio.gather(self._get("/fapi/v3/positionRisk"),self._spot_snapshot()); now=datetime.now(timezone.utc); output=[]
        for row in rows:
            amt=dec(row.get("positionAmt"));
            if not amt: continue
            mark=dec(row.get("markPrice")); liq=dec(row.get("liquidationPrice")); side=Side.LONG if amt>0 else Side.SHORT
            output.append(NormalizedPosition(exchange=Exchange.BINANCE,account_id=self.account_id,account_name=self.account_name,symbol=row["symbol"].replace("USDT",""),exchange_symbol=row["symbol"],base_asset=row["symbol"].removesuffix("USDT").removesuffix("USDC"),quote_asset="USD",settlement_asset="USDT" if row["symbol"].endswith("USDT") else "USDC",side=side,quantity=abs(amt),position_value=abs(amt)*mark,entry_price=dec(row.get("entryPrice")),mark_price=mark,unrealized_pnl=dec(row.get("unRealizedProfit")),leverage=dec(row.get("leverage")),margin_mode=MarginMode.ISOLATED if row.get("isolated") else MarginMode.CROSS,isolated_margin=dec(row.get("isolatedMargin")),position_margin=dec(row.get("isolatedWallet")),maintenance_margin=dec(row.get("maintMargin")),liquidation_price=liq or None,liquidation_distance_percent=liquidation_distance(side,mark,liq or None),risk_level=risk_level(liquidation_distance(side,mark,liq or None)),updated_at=now,raw_data={k:str(v) for k,v in row.items()}))
        for balance in balances:
            asset=str(balance.get("asset") or "UNKNOWN"); quantity=dec(balance.get("free"))+dec(balance.get("locked"))
            if quantity<=0: continue
            mark=prices.get(asset)
            output.append(NormalizedPosition(exchange=Exchange.BINANCE,account_id=self.account_id,account_name=self.account_name,symbol=f"现货 · {asset}",exchange_symbol=asset,base_asset=asset,settlement_asset="USDT",side=Side.LONG,quantity=quantity,position_value=quantity*mark if mark is not None else ZERO,mark_price=mark,margin_mode=MarginMode.UNKNOWN,risk_level=RiskLevel.UNKNOWN,updated_at=now,contract_type="SPOT",raw_data={k:str(v) for k,v in balance.items()}))
        return output
