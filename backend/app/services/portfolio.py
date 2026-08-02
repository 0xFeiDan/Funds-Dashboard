import asyncio,json
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..adapters import ADAPTERS
from ..config import settings
from ..db_models import AccountSnapshot,ConnectionStatus,EncryptedCredential,ExchangeAccount,LatestPortfolioState,PortfolioHistoryState,PositionSnapshot,ReconciliationLog
from ..risk import effective_leverage
from ..schemas import Exchange,NormalizedAccountSummary,NormalizedPosition
from ..security import decrypt
ZERO=Decimal("0")
def snapshot_changed(previous:dict|None, current:dict)->bool:
    """Ignore refresh timestamps when deciding whether to retain a historical point."""
    if not previous: return True
    def clean(record:dict|None):
        return {k:v for k,v in (record or {}).items() if k not in {"updated_at","is_stale"}}
    return clean(previous.get("summary"))!=clean(current.get("summary")) or [clean(x) for x in previous.get("positions",[])]!=[clean(x) for x in current.get("positions",[])]
def coverage_for(account:ExchangeAccount,payload:dict)->dict:
    """Small, non-sensitive receipt of what this sync actually covered."""
    summary=payload.get("summary") or {}; raw=summary.get("raw_values") or {}; error=str((payload.get("status") or {}).get("error") or "")
    def item(name:str, count:str|None=None, ok:bool=True): return {"name":name,"detail":count or ("已读取" if ok else "未读取"),"state":"READY" if ok else "MISSING"}
    if account.exchange=="hyperliquid":
        items=[item("永续 DEX",raw.get("perp_dexes","0")),item("现货",raw.get("spot_assets","0")),item("Vault",raw.get("vaults","0")),item("HYPE 质押",raw.get("staking_entries","0")),item("子账户","自动发现")]
    elif account.exchange=="binance":
        spot_error=raw.get("spot_sync_error",""); items=[item("USD-M 合约"),item("现货",raw.get("spot_assets","0"),not bool(spot_error))]
    elif account.exchange=="bitget":
        types=raw.get("all_account_types",""); items=[item("账户估值",types or "未返回",bool(types)),item("现货","逐币种读取")]
    elif account.exchange=="bitcoin": items=[item("BTC 原生币","UTXO 余额")]
    elif account.exchange in {"ethereum","arbitrum"}: items=[item("原生 ETH"),item("ERC-20","自动枚举")]
    else: items=[item("永续账户")]
    return {"account_id":account.id,"account_name":account.name,"exchange":account.exchange,"state":"ERROR" if error else "READY","error":error or None,"items":items}
class PortfolioService:
    def __init__(self, session:AsyncSession, redis): self.session,self.redis=session,redis
    async def accounts(self,user_id:str): return (await self.session.scalars(select(ExchangeAccount).where(ExchangeAccount.user_id==user_id,ExchangeAccount.enabled.is_(True)))).all()
    async def adapter(self,account:ExchangeAccount):
        credential=await self.session.scalar(select(EncryptedCredential).where(EncryptedCredential.exchange_account_id==account.id))
        secrets=decrypt(credential.ciphertext,credential.nonce) if credential else {}
        return ADAPTERS[Exchange(account.exchange)](account.id,account.name,secrets,account.public_identifier)
    async def _stored_payload(self, account_id:str)->dict|None:
        row=await self.session.scalar(select(LatestPortfolioState).where(LatestPortfolioState.exchange_account_id==account_id))
        return dict(row.payload) if row else None
    async def _save_latest(self, account_id:str, payload:dict)->None:
        row=await self.session.scalar(select(LatestPortfolioState).where(LatestPortfolioState.exchange_account_id==account_id))
        if row: row.payload=payload
        else: self.session.add(LatestPortfolioState(exchange_account_id=account_id,payload=payload))
    async def _store_history_if_due(self, account_id:str, payload:dict, changed:bool)->None:
        last=await self.session.scalar(select(AccountSnapshot).where(AccountSnapshot.exchange_account_id==account_id).order_by(AccountSnapshot.created_at.desc()).limit(1))
        now=datetime.now(timezone.utc)
        last_at=last.created_at.replace(tzinfo=timezone.utc) if last and last.created_at.tzinfo is None else (last.created_at if last else None)
        due=not last_at or now-last_at>=timedelta(seconds=settings.snapshot_interval_seconds)
        if not (changed or due): return
        self.session.add(AccountSnapshot(exchange_account_id=account_id,payload=payload["summary"]))
        self.session.add_all(PositionSnapshot(exchange_account_id=account_id,payload=p) for p in payload["positions"])
        self.session.add(PortfolioHistoryState(exchange_account_id=account_id,payload={"summary":payload["summary"],"positions":payload["positions"]}))
    async def refresh_account(self,account:ExchangeAccount,reason:str="manual")->dict:
        key=f"portfolio:{account.id}"
        previous_raw=await self.redis.get(key);previous=json.loads(previous_raw) if previous_raw else await self._stored_payload(account.id)
        try:
            adapter=await self.adapter(account); summary,positions=await adapter.reconcile_state()
            payload={"summary":summary.model_dump(mode="json"),"positions":[p.model_dump(mode="json") for p in positions],"status":{"state":"CONNECTED","last_rest_success":datetime.now(timezone.utc).isoformat(),"error":None}}
            changed=snapshot_changed(previous,payload)
            await self._store_history_if_due(account.id,payload,changed)
            await self._save_latest(account.id,payload)
            self.session.add(ReconciliationLog(exchange_account_id=account.id,external_id=None,occurred_at=datetime.now(timezone.utc),payload={"reason":reason,"changed":changed,"positions":len(positions)}))
            self.session.add(ConnectionStatus(exchange_account_id=account.id,external_id=None,occurred_at=datetime.now(timezone.utc),payload=payload["status"]))
            await self.session.commit()
        except Exception as exc:
            payload=previous if previous else {"summary":None,"positions":[]}
            detail=str(exc).replace("\n"," ").strip()
            payload["status"]={"state":"ERROR","last_rest_success":payload.get("status",{}).get("last_rest_success"),"error":f"{exc.__class__.__name__}{': '+detail if detail else ''}"}
            self.session.add(ConnectionStatus(exchange_account_id=account.id,external_id=None,occurred_at=datetime.now(timezone.utc),payload=payload["status"]))
            await self._save_latest(account.id,payload)
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
            stored=await self._stored_payload(account.id) if not raw else None
            payload=json.loads(raw) if raw else stored or {"summary":None,"positions":[],"status":{"state":"DISCONNECTED","error":"No snapshot yet"}}
            if not raw and stored: await self.redis.set(f"portfolio:{account.id}",json.dumps(stored,default=str),ex=3600)
            rows.append({"account":account,"payload":payload})
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
        # A wallet token without a reliable price is not a monitored asset.
        # Keep raw exchange responses server-side, but do not pollute balances,
        # exposure, PnL, or the browser with airdrop/dust tokens.
        monitored=[p for p in positions if p.get("contract_type")=="PERPETUAL" or p.get("mark_price") not in (None, "", "0", "0.0")]
        public_positions=[annotate(p) for p in monitored]
        connections=[]
        coverage=[]
        for row in rows:
            account=row["account"]; payload=row["payload"]
            state={"account_id":account.id,"account_name":account.name,"exchange":account.exchange,**dict(payload.get("status",{}))}; summary=payload.get("summary")
            if summary and state.get("state")=="CONNECTED": state["state"]=annotate(summary)["data_state"]
            connections.append(state)
            coverage.append(coverage_for(account,payload))
        return {"overview":overview,"accounts":public_accounts,"positions":public_positions,"connections":connections,"coverage":coverage,"net_exposure":net_exposure(public_positions,equity)}
def net_exposure(positions:list[dict],total_equity:Decimal)->list[dict]:
    out=defaultdict(lambda:{"long_quantity":ZERO,"short_quantity":ZERO,"long_notional":ZERO,"short_notional":ZERO,"long_unrealized_pnl":ZERO,"short_unrealized_pnl":ZERO,"by_exchange":defaultdict(lambda:ZERO)})
    for p in positions:
        asset="USD" if p["base_asset"] in {"USDT","USDC"} else p["base_asset"]
        row=out[asset]; q=Decimal(p["quantity"]); n=Decimal(p["position_value"]); pnl=Decimal(p["unrealized_pnl"])
        if p["side"]=="LONG":row["long_quantity"]+=q;row["long_notional"]+=n;row["long_unrealized_pnl"]+=pnl
        else:row["short_quantity"]+=q;row["short_notional"]+=n;row["short_unrealized_pnl"]+=pnl
        row["by_exchange"][p["exchange"]]+=n
    return [{"asset":asset,"long_quantity":str(v["long_quantity"]),"short_quantity":str(v["short_quantity"]),"net_quantity":str(v["long_quantity"]-v["short_quantity"]),"long_notional":str(v["long_notional"]),"short_notional":str(v["short_notional"]),"gross_notional":str(v["long_notional"]+v["short_notional"]),"net_notional":str(v["long_notional"]-v["short_notional"]),"total_unrealized_pnl":str(v["long_unrealized_pnl"]+v["short_unrealized_pnl"]),"asset_concentration":str((v["long_notional"]+v["short_notional"])/total_equity if total_equity>ZERO else ZERO),"by_exchange":{k:str(n) for k,n in v["by_exchange"].items()}} for asset,v in out.items()]
