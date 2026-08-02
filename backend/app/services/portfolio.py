import asyncio,json
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..adapters import ADAPTERS
from ..config import settings
from ..db_models import AccountSnapshot,ConnectionStatus,EncryptedCredential,ExchangeAccount,PositionSnapshot,ReconciliationLog
from ..risk import effective_leverage
from ..schemas import Exchange,NormalizedAccountSummary,NormalizedPosition
from ..security import decrypt
ZERO=Decimal("0")
class PortfolioService:
    def __init__(self, session:AsyncSession, redis): self.session,self.redis=session,redis
    async def accounts(self,user_id:str): return (await self.session.scalars(select(ExchangeAccount).where(ExchangeAccount.user_id==user_id,ExchangeAccount.enabled.is_(True)))).all()
    async def adapter(self,account:ExchangeAccount):
        credential=await self.session.scalar(select(EncryptedCredential).where(EncryptedCredential.exchange_account_id==account.id))
        secrets=decrypt(credential.ciphertext,credential.nonce) if credential else {}
        return ADAPTERS[Exchange(account.exchange)](account.id,account.name,secrets,account.public_identifier)
    async def refresh_account(self,account:ExchangeAccount,reason:str="manual")->dict:
        key=f"portfolio:{account.id}"
        previous_raw=await self.redis.get(key);previous=json.loads(previous_raw) if previous_raw else None
        try:
            adapter=await self.adapter(account); summary,positions=await adapter.reconcile_state()
            payload={"summary":summary.model_dump(mode="json"),"positions":[p.model_dump(mode="json") for p in positions],"status":{"state":"CONNECTED","last_rest_success":datetime.now(timezone.utc).isoformat(),"error":None}}
            self.session.add(AccountSnapshot(exchange_account_id=account.id,payload=payload["summary"]))
            self.session.add_all(PositionSnapshot(exchange_account_id=account.id,payload=p) for p in payload["positions"])
            changed=not previous or previous.get("summary")!=payload["summary"] or previous.get("positions")!=payload["positions"]
            self.session.add(ReconciliationLog(exchange_account_id=account.id,external_id=None,occurred_at=datetime.now(timezone.utc),payload={"reason":reason,"changed":changed,"positions":len(positions)}))
            self.session.add(ConnectionStatus(exchange_account_id=account.id,external_id=None,occurred_at=datetime.now(timezone.utc),payload=payload["status"]))
            await self.session.commit()
        except Exception as exc:
            payload=previous if previous else {"summary":None,"positions":[]}
            detail=str(exc).replace("\n"," ").strip()
            payload["status"]={"state":"ERROR","last_rest_success":payload.get("status",{}).get("last_rest_success"),"error":f"{exc.__class__.__name__}{': '+detail if detail else ''}"}
            self.session.add(ConnectionStatus(exchange_account_id=account.id,external_id=None,occurred_at=datetime.now(timezone.utc),payload=payload["status"]))
            await self.session.commit()
        await self.redis.set(key,json.dumps(payload,default=str),ex=3600)
        await self.redis.publish(f"portfolio:user:{account.user_id}",json.dumps({"event":"portfolio_updated","account_id":account.id,"reason":reason,"at":datetime.now(timezone.utc).isoformat()}))
        return payload
    async def refresh_all(self,user_id:str)->list[dict]: return await asyncio.gather(*(self.refresh_account(a) for a in await self.accounts(user_id)))
    async def dashboard(self,user_id:str,refresh:bool=False)->dict:
        accounts=await self.accounts(user_id)
        if refresh: await asyncio.gather(*(self.refresh_account(a) for a in accounts))
        rows=[]
        for account in accounts:
            raw=await self.redis.get(f"portfolio:{account.id}")
            # Retain configuration identity when the first refresh fails, so a
            # bad wallet address is visible as an error instead of "no assets".
            rows.append({"account":account,"payload":json.loads(raw) if raw else {"summary":None,"positions":[],"status":{"state":"DISCONNECTED","error":"No snapshot yet"}}})
        summaries=[x["payload"]["summary"] for x in rows if x["payload"].get("summary")]; positions=[p for x in rows for p in x["payload"].get("positions",[])]
        now=datetime.now(timezone.utc)
        def D(v): return Decimal(str(v or "0"))
        equity=sum((D(s["account_equity"]) for s in summaries),ZERO); notional=sum((D(p["position_value"]) for p in positions),ZERO)
        overview={"account_equity":str(equity),"available_balance":str(sum((D(s["available_balance"]) for s in summaries),ZERO)),"unrealized_pnl":str(sum((D(s["unrealized_pnl"]) for s in summaries),ZERO)),"total_position_notional":str(notional),"effective_leverage":str(effective_leverage(notional,equity) or ZERO),"updated_at":now.isoformat(),"warning":"Only sums accounts with the displayed USD/USDT/USDC reporting scope; mixed-currency accounts require FX normalization before aggregation."}
        # Raw platform payloads stay in server cache/audit storage, never cross the browser boundary.
        def annotate(record:dict)->dict:
            public={k:v for k,v in record.items() if k not in {"raw_values","field_notes","raw_data"}}
            try: age=(now-datetime.fromisoformat(str(record["updated_at"]))).total_seconds()
            except (KeyError,ValueError): age=float("inf")
            public["is_stale"]=age>=settings.stale_seconds
            public["data_state"]="DISCONNECTED" if age>=settings.disconnected_seconds else "STALE" if age>=settings.stale_seconds else "WARNING" if age>=settings.stale_warning_seconds else "LIVE"
            return public
        public_accounts=[annotate(s) for s in summaries]
        public_positions=[annotate(p) for p in positions]
        connections=[]
        for row in rows:
            account=row["account"]; payload=row["payload"]
            state={"account_id":account.id,"account_name":account.name,"exchange":account.exchange,**dict(payload.get("status",{}))}; summary=payload.get("summary")
            if summary and state.get("state")=="CONNECTED": state["state"]=annotate(summary)["data_state"]
            connections.append(state)
        return {"overview":overview,"accounts":public_accounts,"positions":public_positions,"connections":connections,"net_exposure":net_exposure(public_positions,equity)}
def net_exposure(positions:list[dict],total_equity:Decimal)->list[dict]:
    out=defaultdict(lambda:{"long_quantity":ZERO,"short_quantity":ZERO,"long_notional":ZERO,"short_notional":ZERO,"long_unrealized_pnl":ZERO,"short_unrealized_pnl":ZERO,"by_exchange":defaultdict(lambda:ZERO)})
    for p in positions:
        row=out[p["base_asset"]]; q=Decimal(p["quantity"]); n=Decimal(p["position_value"]); pnl=Decimal(p["unrealized_pnl"])
        if p["side"]=="LONG":row["long_quantity"]+=q;row["long_notional"]+=n;row["long_unrealized_pnl"]+=pnl
        else:row["short_quantity"]+=q;row["short_notional"]+=n;row["short_unrealized_pnl"]+=pnl
        row["by_exchange"][p["exchange"]]+=n
    return [{"asset":asset,"long_quantity":str(v["long_quantity"]),"short_quantity":str(v["short_quantity"]),"net_quantity":str(v["long_quantity"]-v["short_quantity"]),"long_notional":str(v["long_notional"]),"short_notional":str(v["short_notional"]),"gross_notional":str(v["long_notional"]+v["short_notional"]),"net_notional":str(v["long_notional"]-v["short_notional"]),"total_unrealized_pnl":str(v["long_unrealized_pnl"]+v["short_unrealized_pnl"]),"asset_concentration":str((v["long_notional"]+v["short_notional"])/total_equity if total_equity>ZERO else ZERO),"by_exchange":{k:str(n) for k,n in v["by_exchange"].items()}} for asset,v in out.items()]
