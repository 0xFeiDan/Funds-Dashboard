import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from .api import router
from .config import settings
from .db import Base, SessionLocal, engine
from .db_models import User
from .local_cache import LocalCache
from .security import password_hash
from .services.sync import SyncSupervisor
logging.basicConfig(level=logging.INFO,format='{"timestamp":"%(asctime)s","level":"%(levelname)s","component":"%(name)s","event":"%(message)s"}')
app=FastAPI(title="Read-only Perpetual Monitor",docs_url=None,redoc_url=None)
app.include_router(router)
@app.on_event("startup")
async def startup():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app.state.cache=LocalCache()
    async with SessionLocal() as session:
        existing=await session.scalar(select(User).where(User.username==settings.bootstrap_username))
        if not existing: session.add(User(username=settings.bootstrap_username,password_hash=password_hash(settings.bootstrap_password)));await session.commit()
    app.state.sync=SyncSupervisor(app.state.cache,settings.reconcile_interval_seconds)
    await app.state.sync.start()
    logging.getLogger(__name__).info("First-login credentials are in %s", Path(settings.data_dir) / "first-login.txt")
@app.on_event("shutdown")
async def shutdown():
    await app.state.sync.close()
    await engine.dispose()

@app.get("/api/health/live")
async def live(): return {"status":"live"}

@app.get("/api/health/ready")
async def ready():
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status":"ready"}

frontend = Path(settings.frontend_dist)
if frontend.is_dir():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
else:
    logging.getLogger(__name__).warning("Frontend build missing: %s", frontend)
