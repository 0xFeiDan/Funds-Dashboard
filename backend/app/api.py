import asyncio,time
from collections import defaultdict
from datetime import datetime,timedelta,timezone
import jwt
from fastapi import APIRouter,Depends,HTTPException,Request,Response,status
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import db_session
from .db_models import AuditLog,EncryptedCredential,ExchangeAccount,User
from .schemas import AccountCreate,AccountView,Login
from .security import encrypt,password_hash,unauthorized,verify_password
from .services.portfolio import PortfolioService
from .services.history import equity_history,pnl_attribution,pnl_summary,portfolio_as_of
router=APIRouter(prefix="/api"); bearer=HTTPBearer(auto_error=False); login_attempts=defaultdict(list)
def token(user:User)->str:return jwt.encode({"sub":user.id,"exp":datetime.now(timezone.utc)+timedelta(hours=8)},settings.session_secret,algorithm="HS256")
def current_user(request:Request, credentials:HTTPAuthorizationCredentials|None=Depends(bearer))->str:
    raw=request.cookies.get("session") or (credentials.credentials if credentials else None)
    if not raw: unauthorized()
    try:return jwt.decode(raw,settings.session_secret,algorithms=["HS256"])["sub"]
    except jwt.PyJWTError: unauthorized()
def csrf(request:Request):
    if request.headers.get("x-csrf-token")!=request.cookies.get("csrf"): raise HTTPException(403,"CSRF validation failed")
async def service(session:AsyncSession=Depends(db_session), request:Request=None): return PortfolioService(session,request.app.state.cache)
@router.post("/auth/login")
async def login(body:Login,request:Request,response:Response,session:AsyncSession=Depends(db_session)):
    ip=request.client.host if request.client else "unknown"; cutoff=time.time()-900; login_attempts[ip]=[x for x in login_attempts[ip] if x>cutoff]
    if len(login_attempts[ip])>=5: raise HTTPException(429,"Too many login attempts; retry later")
    user=await session.scalar(select(User).where(User.username==body.username))
    if not user or not verify_password(body.password.get_secret_value(),user.password_hash): login_attempts[ip].append(time.time());raise HTTPException(401,"Invalid credentials")
    session.add(AuditLog(payload={"event":"login_success","user_id":user.id,"ip":ip}));await session.commit()
    csrf_value=jwt.encode({"sub":user.id,"exp":datetime.now(timezone.utc)+timedelta(hours=8)},settings.session_secret,algorithm="HS256")
    response.set_cookie("session",token(user),httponly=True,secure=settings.cookie_secure,samesite="strict",max_age=28800,path="/"); response.set_cookie("csrf",csrf_value,httponly=False,secure=settings.cookie_secure,samesite="strict",max_age=28800,path="/")
    return {"ok":True,"csrf_token":csrf_value}
@router.post("/auth/logout")
async def logout(response:Response,_=Depends(current_user),__=Depends(csrf)): response.delete_cookie("session");response.delete_cookie("csrf");return {"ok":True}
@router.get("/accounts",response_model=list[AccountView])
async def list_accounts(user_id:str=Depends(current_user),session:AsyncSession=Depends(db_session)):
    rows=(await session.scalars(select(ExchangeAccount).where(ExchangeAccount.user_id==user_id))).all();return [AccountView(id=x.id,exchange=x.exchange,name=x.name,public_identifier=x.public_identifier,enabled=x.enabled) for x in rows]
@router.post("/accounts",response_model=AccountView,status_code=201)
async def create_account(body:AccountCreate,user_id:str=Depends(current_user),_:None=Depends(csrf),session:AsyncSession=Depends(db_session)):
    if body.exchange.value in ("binance","bitget") and not (body.api_key and body.api_secret): raise HTTPException(422,"Read-only API key and secret required")
    record=ExchangeAccount(user_id=user_id,exchange=body.exchange.value,name=body.name,public_identifier=body.public_identifier);session.add(record);await session.flush()
    values={k:v for k,x in {"api_key":body.api_key,"api_secret":body.api_secret,"passphrase":body.passphrase}.items() if (v:=x.get_secret_value() if x else None)}
    if body.product_type:values["product_type"]=body.product_type
    if values:
        ciphertext,nonce=encrypt(values);session.add(EncryptedCredential(exchange_account_id=record.id,ciphertext=ciphertext,nonce=nonce))
    session.add(AuditLog(exchange_account_id=record.id,payload={"event":"exchange_account_created","exchange":record.exchange,"name":record.name,"user_id":user_id}))
    await session.commit();return AccountView(id=record.id,exchange=record.exchange,name=record.name,public_identifier=record.public_identifier,enabled=record.enabled)
@router.post("/accounts/{account_id}/refresh")
async def refresh(account_id:str,user_id:str=Depends(current_user),_:None=Depends(csrf),svc:PortfolioService=Depends(service)):
    account=next((a for a in await svc.accounts(user_id) if a.id==account_id),None)
    if not account: raise HTTPException(404,"Account not found")
    return await svc.refresh_account(account)
@router.get("/dashboard")
async def dashboard(refresh:bool=False,user_id:str=Depends(current_user),svc:PortfolioService=Depends(service)): return await svc.dashboard(user_id,refresh)
@router.get("/pnl")
async def pnl(range:str="7d",user_id:str=Depends(current_user),session:AsyncSession=Depends(db_session)):
    days={"1d":1,"7d":7,"30d":30,"all":None}.get(range)
    if days is None and range!="all": raise HTTPException(422,"range must be 1d, 7d, 30d, or all")
    ids=(await session.scalars(select(ExchangeAccount.id).where(ExchangeAccount.user_id==user_id,ExchangeAccount.enabled.is_(True)))).all()
    return await pnl_summary(session,ids,datetime.now(timezone.utc)-timedelta(days=days) if days else None)
@router.get("/history/equity")
async def equity(range:str="30d",user_id:str=Depends(current_user),session:AsyncSession=Depends(db_session)):
    days={"7d":7,"30d":30,"90d":90,"all":None}.get(range)
    if days is None and range!="all": raise HTTPException(422,"range must be 7d, 30d, 90d, or all")
    ids=(await session.scalars(select(ExchangeAccount.id).where(ExchangeAccount.user_id==user_id,ExchangeAccount.enabled.is_(True)))).all()
    return await equity_history(session,ids,datetime.now(timezone.utc)-timedelta(days=days) if days else None)
@router.get("/pnl/attribution")
async def attribution(range:str="30d",user_id:str=Depends(current_user),session:AsyncSession=Depends(db_session)):
    days={"7d":7,"30d":30,"90d":90,"all":None}.get(range)
    if days is None and range!="all": raise HTTPException(422,"range must be 7d, 30d, 90d, or all")
    ids=(await session.scalars(select(ExchangeAccount.id).where(ExchangeAccount.user_id==user_id,ExchangeAccount.enabled.is_(True)))).all()
    return await pnl_attribution(session,ids,datetime.now(timezone.utc)-timedelta(days=days) if days else None)
@router.get("/history/snapshot")
async def historical_snapshot(at:datetime,user_id:str=Depends(current_user),session:AsyncSession=Depends(db_session)):
    ids=(await session.scalars(select(ExchangeAccount.id).where(ExchangeAccount.user_id==user_id,ExchangeAccount.enabled.is_(True)))).all()
    return await portfolio_as_of(session,ids,at.astimezone(timezone.utc))
