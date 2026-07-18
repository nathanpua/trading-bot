"""FastAPI application entrypoint for the Trading Bot Dashboard."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Add bot root to sys.path so we can import alpaca_client, trade_journal, etc.
from .config import BOT_ROOT
_bot_root = str(BOT_ROOT)
if _bot_root not in sys.path:
    sys.path.insert(0, _bot_root)

from .api import portfolio as portfolio_api
from .api import trades as trades_api
from .api import cycles as cycles_api
from .api import analysis as analysis_api
from .api import ai_cycles as ai_cycles_api
from .api import strategies as strategies_api
from .api import performance as performance_api
from .api import universe as universe_api
from .api import health as health_api
from .services import journal_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("dashboard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Trading Bot Dashboard")
    journal_service.init_journal()
    log.info("Journal initialized")
    yield
    log.info("Shutdown complete")


app = FastAPI(
    title="Trading Bot Dashboard",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health_api.router)
app.include_router(portfolio_api.router)
app.include_router(trades_api.router)
app.include_router(cycles_api.router)
app.include_router(analysis_api.router)
app.include_router(ai_cycles_api.router)
app.include_router(strategies_api.router)
app.include_router(performance_api.router)
app.include_router(universe_api.router)

# Serve frontend build if present (production)
_frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
