import asyncio,json,logging
from http.cookies import SimpleCookie
import jwt
import redis.asyncio as redis
from fastapi import FastAPI,Request,WebSocket,WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from .api import router
from .config import settings
from .db import SessionLocal
from .db_models import User
from .security import password_hash
from .services.sync import SyncSupervisor
logging.basicConfig(level=logging.INFO,format='{"timestamp":"%(asctime)s","level":"%(levelname)s","component":"%(name)s","event":"%(message)s"}')
app=FastAPI(title="Read-only Perpetual Monitor",docs_url=None,redoc_url=None)
if settings.origins: app.add_middleware(CORSMiddleware,allow_origins=settings.origins,allow_credentials=True,allow_methods=["GET","POST"],allow_headers=["Content-Type","X-CSRF-Token"])
app.include_router(router)
@app.on_event("startup")
async def startup():
    app.state.redis=redis.from_url(settings.redis_url,decode_responses=True)
    async with SessionLocal() as session:
        existing=await session.scalar(select(User).where(User.username==settings.bootstrap_username))
        if not existing: session.add(User(username=settings.bootstrap_username,password_hash=password_hash(settings.bootstrap_password)));await session.commit()
    app.state.sync=SyncSupervisor(app.state.redis,settings.reconcile_interval_seconds)
    await app.state.sync.start()
@app.on_event("shutdown")
async def shutdown():
    await app.state.sync.close()
    await app.state.redis.aclose()
@app.websocket("/ws/dashboard")
async def dashboard_ws(socket:WebSocket):
    cookie=SimpleCookie();cookie.load(socket.headers.get("cookie","")); raw=cookie.get("session")
    try: user_id=jwt.decode(raw.value if raw else "",settings.session_secret,algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        await socket.close(code=4401);return
    await socket.accept(); pubsub=app.state.redis.pubsub();await pubsub.subscribe(f"portfolio:user:{user_id}")
    try:
        while True:
            message=await pubsub.get_message(ignore_subscribe_messages=True,timeout=1.0)
            if message: await socket.send_text(message["data"])
            await asyncio.sleep(0.1)
    except WebSocketDisconnect: pass
    finally:
        await pubsub.unsubscribe(f"portfolio:user:{user_id}");await pubsub.aclose()
