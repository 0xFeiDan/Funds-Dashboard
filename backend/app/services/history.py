"""Read-only historical ledger persistence and PnL aggregation."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Type
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db_models import AccountSnapshot, BalanceMovement, ExchangeAccount, FundingPayment, PortfolioHistoryState, Trade, TradingFee

ZERO=Decimal("0")

def parse_time(value:object|None)->datetime:
    if value is None: return datetime.now(timezone.utc)
    if isinstance(value,datetime): return value.astimezone(timezone.utc)
    text=str(value)
    if text.isdigit(): return datetime.fromtimestamp(int(text)/(1000 if len(text)>10 else 1),timezone.utc)
    return datetime.fromisoformat(text.replace("Z","+00:00")).astimezone(timezone.utc)

async def store_unique(session:AsyncSession, model:Type, account_id:str, external_id:str, occurred_at:datetime, payload:dict)->bool:
    exists=await session.scalar(select(model.id).where(model.exchange_account_id==account_id,model.external_id==external_id))
    if exists: return False
    session.add(model(exchange_account_id=account_id,external_id=external_id,occurred_at=occurred_at,payload=payload))
    return True

async def store_income_rows(session:AsyncSession, account_id:str, rows:list[dict])->int:
    stored=0
    for row in rows:
        kind=str(row.get("kind") or row.get("incomeType") or "").upper(); external_id=str(row.get("id") or row.get("tranId") or row.get("funding_id") or f"{kind}:{row.get('time') or row.get('timestamp')}:{row.get('symbol','')}")
        occurred=parse_time(row.get("time") or row.get("timestamp") or row.get("created_at"))
        model=FundingPayment if kind in {"FUNDING_FEE","FUNDING"} else TradingFee if kind in {"COMMISSION","FEE"} else BalanceMovement if kind in {"TRANSFER","DEPOSIT","WITHDRAW","WITHDRAWAL"} else Trade
        stored += await store_unique(session,model,account_id,external_id,occurred,row)
        if model is Trade and row.get("fee") not in (None,""):
            stored += await store_unique(session,TradingFee,account_id,f"{external_id}:fee",occurred,{"fee":row["fee"],"source_trade":external_id})
    return stored

def amount(payload:dict, *fields:str)->Decimal:
    for field in fields:
        if payload.get(field) not in (None,""):
            return Decimal(str(payload[field]))
    return ZERO

async def pnl_summary(session:AsyncSession, account_ids:list[str], start:datetime|None)->dict:
    if not account_ids: return {"realized_pnl":"0","funding_pnl":"0","trading_fee":"0","net_trading_pnl":"0","deposit_withdrawal":"0","data_complete":False,"missing":["No configured accounts"]}
    async def rows(model):
        q=select(model).where(model.exchange_account_id.in_(account_ids))
        if start:q=q.where(model.occurred_at>=start)
        return (await session.scalars(q)).all()
    trades,funding,fees,movements=await rows(Trade),await rows(FundingPayment),await rows(TradingFee),await rows(BalanceMovement)
    realized=sum((amount(x.payload,"realized_pnl","realizedPnl","closedPnl","income","profit","totalProfits") for x in trades),ZERO)
    funding_total=sum((amount(x.payload,"income","change","funding","amount") for x in funding),ZERO)
    fee_total=sum((abs(amount(x.payload,"income","fee","amount")) for x in fees),ZERO)
    movement_total=sum((amount(x.payload,"income","amount","change") for x in movements),ZERO)
    return {"realized_pnl":str(realized),"funding_pnl":str(funding_total),"trading_fee":str(fee_total),"net_trading_pnl":str(realized+funding_total-fee_total),"deposit_withdrawal":str(movement_total),"data_complete":False,"missing":["Unrealized PnL history is not reconstructed from account equity","Adapters without a documented history endpoint report partial history"],"starting_at":start.isoformat() if start else None}

async def equity_history(session:AsyncSession, account_ids:list[str], start:datetime|None)->dict:
    """Daily closing equity from persisted snapshots, never reconstructed from trades."""
    if not account_ids:
        return {"points":[],"change":"0","data_complete":False,"missing":["No configured accounts"]}
    query=select(AccountSnapshot).where(AccountSnapshot.exchange_account_id.in_(account_ids)).order_by(AccountSnapshot.created_at)
    if start: query=query.where(AccountSnapshot.created_at>=start)
    rows=(await session.scalars(query)).all()
    by_day:dict[str,dict[str,AccountSnapshot]]={}
    for row in rows:
        at=row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
        by_day.setdefault(at.date().isoformat(),{})[row.exchange_account_id]=row
    points=[]
    for day,latest in sorted(by_day.items()):
        equity=sum((Decimal(str(row.payload.get("account_equity") or "0")) for row in latest.values()),ZERO)
        points.append({"at":f"{day}T00:00:00+00:00","equity":str(equity),"accounts_reported":len(latest),"expected_accounts":len(account_ids),"complete":len(latest)==len(account_ids)})
    change=Decimal(points[-1]["equity"])-Decimal(points[0]["equity"]) if len(points)>1 else ZERO
    return {"points":points,"change":str(change),"data_complete":bool(points) and all(point["complete"] for point in points),"missing":[] if points else ["No snapshots in selected range"]}

async def pnl_attribution(session:AsyncSession, account_ids:list[str], start:datetime|None)->dict:
    """Attribute only ledger-backed trading PnL; transfers stay out of trading profit."""
    accounts=(await session.scalars(select(ExchangeAccount).where(ExchangeAccount.id.in_(account_ids)))).all()
    account_map={row.id:row for row in accounts}; groups={"by_exchange":{},"by_account":{},"by_asset":{}}
    def add(group:str,key:str,realized:Decimal=ZERO,funding:Decimal=ZERO,fee:Decimal=ZERO):
        row=groups[group].setdefault(key,{"realized_pnl":ZERO,"funding_pnl":ZERO,"trading_fee":ZERO,"net_trading_pnl":ZERO})
        row["realized_pnl"]+=realized;row["funding_pnl"]+=funding;row["trading_fee"]+=fee;row["net_trading_pnl"]+=realized+funding-fee
    async def rows(model):
        query=select(model).where(model.exchange_account_id.in_(account_ids))
        if start:query=query.where(model.occurred_at>=start)
        return (await session.scalars(query)).all()
    for model,kind in ((Trade,"trade"),(FundingPayment,"funding"),(TradingFee,"fee")):
        for row in await rows(model):
            payload=row.payload; account=account_map.get(row.exchange_account_id); exchange=account.exchange if account else "unknown"; account_name=account.name if account else row.exchange_account_id
            asset=str(payload.get("coin") or payload.get("symbol") or payload.get("asset") or "未分类")
            realized=amount(payload,"realized_pnl","realizedPnl","closedPnl","income","profit","totalProfits") if kind=="trade" else ZERO
            funding=amount(payload,"income","change","funding","amount") if kind=="funding" else ZERO
            fee=abs(amount(payload,"income","fee","amount")) if kind=="fee" else ZERO
            for group,key in (("by_exchange",exchange),("by_account",account_name),("by_asset",asset)): add(group,key,realized,funding,fee)
    def render(group:str): return [{"name":key,**{field:str(value) for field,value in values.items()}} for key,values in sorted(groups[group].items(),key=lambda item:abs(item[1]["net_trading_pnl"]),reverse=True)]
    return {"by_exchange":render("by_exchange"),"by_account":render("by_account"),"by_asset":render("by_asset"),"data_complete":False,"missing":["Only synchronized ledger rows are attributed; transfers are excluded from trading PnL."]}

async def portfolio_as_of(session:AsyncSession, account_ids:list[str], at:datetime)->dict:
    """Return the latest full snapshot at or before an instant for every account."""
    result=[]; missing=[]
    for account_id in account_ids:
        row=await session.scalar(select(PortfolioHistoryState).where(PortfolioHistoryState.exchange_account_id==account_id,PortfolioHistoryState.created_at<=at).order_by(PortfolioHistoryState.created_at.desc()).limit(1))
        if not row: missing.append(account_id); continue
        created=row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
        result.append({"account_id":account_id,"captured_at":created.isoformat(),"summary":row.payload.get("summary"),"positions":row.payload.get("positions",[])})
    return {"at":at.isoformat(),"accounts":result,"missing_account_ids":missing,"data_complete":not missing}
