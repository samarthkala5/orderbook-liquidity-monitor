"""FastAPI service exposing the liquidity metrics.

Run (from the repo root), pointing at the collector's database:
    $env:ORDERBOOK_DB = "C:\\data\\orderbook.db"
    uvicorn app.api:app --reload
then open http://127.0.0.1:8000/docs

Exactly 5 endpoints: /health, /symbols, /metrics/{exchange}/{symbol},
/history/{exchange}/{symbol}, /compare/{symbol}.
"""
import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
import os

BASE_URL = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query, Path
from fastapi.responses import RedirectResponse  # <-- Add this import
from app.collector import SYMBOLS
from app.exchanges.base import ExchangeError, UnknownSymbolError
from app.exchanges.binance import BinanceClient
from app.exchanges.coinbase import CoinbaseClient
from app.metrics import InvalidBookError, compute_snapshot
from app.storage import DEFAULT_DB_PATH, connect, count_snapshots, fetch_history, utc_now_iso

EXCHANGES = ("binance", "coinbase")
PRICE_NOTE = (
    "Binance quotes in USDT and Coinbase in USD, which are not identical. "
    "Compare spread (bps), depth and slippage, not raw prices."
)


# ---------- response models (these make /docs self-explanatory) ----------

class SnapshotMetrics(BaseModel):
    best_bid: float
    best_ask: float
    mid: float
    spread_bps: float
    depth_bid_10bps: float
    depth_ask_10bps: float
    imbalance_10bps: float
    slip_buy_10k_bps: Optional[float] = None  # null = book too thin to fill $10k
    slip_sell_10k_bps: Optional[float] = None
    bid_reach_bps: float
    ask_reach_bps: float
    depth_is_lower_bound: bool  # true = the book we received ended inside the 10 bps window


class LiveMetrics(SnapshotMetrics):
    exchange: str
    symbol: str
    ts_utc: str


class HistoryRow(SnapshotMetrics):
    id: int
    ts_utc: str
    exchange: str
    symbol: str


class Health(BaseModel):
    status: str
    snapshots: int


class Symbols(BaseModel):
    exchanges: list[str]
    symbols: list[str]


class Comparison(BaseModel):
    symbol: str
    ts_utc: str
    note: str
    exchanges: list[LiveMetrics]


# ---------- app and dependencies ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """One shared HTTP client for the whole service lifetime, closed on shutdown."""
    async with httpx.AsyncClient() as shared:
        app.state.clients = {
            "binance": BinanceClient(client=shared),
            "coinbase": CoinbaseClient(client=shared),
        }
        yield


app = FastAPI(title="Order Book Liquidity Monitor")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


def get_db_path() -> str:
    return DEFAULT_DB_PATH  # tests override this to point at a temporary database


async def get_conn(db_path: str = Depends(get_db_path)):
    """One SQLite connection per request. `async` so it is created and used on the
    same (event-loop) thread: sqlite3 connections must not cross threads."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_clients(request: Request) -> dict:
    return request.app.state.clients  # tests override this with fakes


# ---------- helpers ----------

def _validate(exchange: Optional[str], symbol: str) -> tuple:
    """Normalise case and return 404 for an unknown exchange or symbol."""
    symbol = symbol.upper()
    if exchange is not None:
        exchange = exchange.lower()
        if exchange not in EXCHANGES:
            raise HTTPException(404, f"Unknown exchange '{exchange}'. Supported: {list(EXCHANGES)}")
    if symbol not in SYMBOLS:
        raise HTTPException(404, f"Unknown symbol '{symbol}'. Supported: {list(SYMBOLS)}")
    return exchange, symbol


async def _live_metrics(client, exchange: str, symbol: str) -> LiveMetrics:
    """Fetch one live book and turn it into metrics. Upstream trouble becomes HTTP 502."""
    try:
        book = await client.fetch_order_book(symbol)
        snapshot = compute_snapshot(book)
    except UnknownSymbolError as exc:  # must come before ExchangeError (it is a subclass)
        raise HTTPException(404, str(exc))
    except (ExchangeError, InvalidBookError) as exc:
        raise HTTPException(502, f"{exchange}: {exc}")
    return LiveMetrics(exchange=exchange, symbol=symbol, ts_utc=utc_now_iso(), **snapshot)


# ---------- the 5 endpoints ----------

@app.get("/health", response_model=Health, summary="Service status and stored snapshot count")
async def health(conn: sqlite3.Connection = Depends(get_conn)):
    return Health(status="ok", snapshots=count_snapshots(conn))


@app.get("/symbols", response_model=Symbols, summary="Supported exchanges and pairs")
async def symbols():
    return Symbols(exchanges=list(EXCHANGES), symbols=list(SYMBOLS))


@app.get(
    "/metrics/{exchange}/{symbol}",
    response_model=LiveMetrics,
    summary="Live metrics: fetch the book now, compute, return",
)
async def live_metrics(exchange: str, symbol: str, clients: dict = Depends(get_clients)):
    exchange, symbol = _validate(exchange, symbol)
    return await _live_metrics(clients[exchange], exchange, symbol)


@app.get(
    "/history/{exchange}/{symbol}",
    response_model=list[HistoryRow],
    summary="Stored snapshots, newest first",
)
async def history(
    exchange: str,
    symbol: str,
    minutes: int = Query(60, ge=1, le=1440, description="How far back to look (1 to 1440 minutes)"),
    limit: int = Query(500, ge=1, le=5000, description="Maximum rows to return (1 to 5000)"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    exchange, symbol = _validate(exchange, symbol)
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return fetch_history(conn, exchange, symbol, since, limit)


@app.get(
    "/compare/{symbol}",
    response_model=Comparison,
    summary="Live side-by-side comparison of both exchanges",
)
async def compare(symbol: str, clients: dict = Depends(get_clients)):
    _, symbol = _validate(None, symbol)
    # Both exchanges are fetched at the same time. If either fails the whole call is a 502:
    # a half-empty comparison would be misleading.
    results = await asyncio.gather(*(_live_metrics(clients[name], name, symbol) for name in EXCHANGES))
    return Comparison(symbol=symbol, ts_utc=utc_now_iso(), note=PRICE_NOTE, exchanges=list(results))