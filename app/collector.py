"""Polling loop. Run it with:  python -m app.collector --db C:\data\orderbook.db

Every `interval` seconds: fetch 3 symbols x 2 exchanges concurrently, compute
metrics, insert one row each. A failure on one book is logged and skipped; it
never stops the loop.
"""
import argparse
import asyncio
import logging
import time

import httpx

from app.exchanges.base import ExchangeError
from app.exchanges.binance import BinanceClient
from app.exchanges.coinbase import CoinbaseClient
from app.metrics import InvalidBookError, compute_snapshot
from app.storage import DEFAULT_DB_PATH, connect, count_snapshots, insert_snapshot, utc_now_iso

logger = logging.getLogger("collector")

SYMBOLS = ("BTC", "ETH", "SOL")
INTERVAL_SECONDS = 10.0


async def collect_one(client, symbol: str, conn, ts_utc: str) -> bool:
    """Fetch, compute and store ONE book. Returns True if a row was stored."""
    try:
        book = await client.fetch_order_book(symbol)
        metrics = compute_snapshot(book)
    except (ExchangeError, InvalidBookError) as exc:  # expected trouble: log one line
        logger.warning("%s %s skipped: %s", client.name, symbol, exc)
        return False
    except Exception:  # a bug of ours: log the traceback, but keep the collector alive overnight
        logger.exception("%s %s: unexpected error", client.name, symbol)
        return False
    insert_snapshot(conn, ts_utc, client.name, symbol, metrics)
    return True


async def run_cycle(clients, conn, symbols=SYMBOLS) -> int:
    """One poll of every (client, symbol). Returns how many rows were stored."""
    ts_utc = utc_now_iso()  # one timestamp for the whole cycle: rows can be compared across exchanges
    started = time.monotonic()
    results = await asyncio.gather(
        *(collect_one(client, symbol, conn, ts_utc) for client in clients for symbol in symbols)
    )
    stored = sum(results)
    logger.info("cycle: %d/%d stored in %.2f s", stored, len(results), time.monotonic() - started)
    return stored


async def run_forever(clients, conn, interval: float = INTERVAL_SECONDS, max_cycles=None) -> None:
    """Repeat run_cycle every `interval` seconds, measured start to start."""
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        started = time.monotonic()
        await run_cycle(clients, conn)
        cycles += 1
        await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))


async def _run(db_path: str, interval: float) -> None:
    conn = connect(db_path)
    logger.info("collecting into %s (%d rows so far)", db_path, count_snapshots(conn))
    try:
        async with httpx.AsyncClient() as shared:  # one connection pool for all 6 calls
            clients = [BinanceClient(client=shared), CoinbaseClient(client=shared)]
            await run_forever(clients, conn, interval)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Order book liquidity collector")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite file path")
    parser.add_argument("--interval", type=float, default=INTERVAL_SECONDS, help="seconds between polls")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(_run(args.db, args.interval))
    except KeyboardInterrupt:  # Ctrl+C: the `finally` above has already closed the database
        logger.info("stopped by user")


if __name__ == "__main__":
    main()