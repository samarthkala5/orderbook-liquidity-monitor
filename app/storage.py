"""SQLite storage for metric snapshots.

We store DERIVED metrics (one row per exchange/symbol/poll), never the raw books:
a Coinbase book has ~20,000 levels per side, which would make the file huge.
"""
import os
import sqlite3
from datetime import datetime, timezone

# One place decides where the database lives. Collector and API both use this,
# so they always look at the same file. Override with the ORDERBOOK_DB env var
# or the collector's --db flag.
DEFAULT_DB_PATH = os.getenv("DB_PATH") or os.getenv("ORDERBOOK_DB") or r"C:\data\orderbook.db"
DB_PATH = DEFAULT_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc               TEXT NOT NULL,   -- ISO 8601 UTC, e.g. 2026-10-24T14:03:10+00:00
    exchange             TEXT NOT NULL,
    symbol               TEXT NOT NULL,
    best_bid             REAL NOT NULL,
    best_ask             REAL NOT NULL,
    mid                  REAL NOT NULL,
    spread_bps           REAL NOT NULL,
    depth_bid_10bps      REAL NOT NULL,
    depth_ask_10bps      REAL NOT NULL,
    imbalance_10bps      REAL NOT NULL,
    slip_buy_10k_bps     REAL,            -- NULL = book too thin to fill $10k
    slip_sell_10k_bps    REAL,
    bid_reach_bps        REAL NOT NULL,   -- how far the book we received extends
    ask_reach_bps        REAL NOT NULL,
    depth_is_lower_bound INTEGER NOT NULL -- 1 = book ended inside the 10 bps window
);
CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
    ON snapshots (exchange, symbol, ts_utc);
"""

# Keys of the dict returned by metrics.compute_snapshot, in table order.
METRIC_COLUMNS = (
    "best_bid", "best_ask", "mid", "spread_bps",
    "depth_bid_10bps", "depth_ask_10bps", "imbalance_10bps",
    "slip_buy_10k_bps", "slip_sell_10k_bps",
    "bid_reach_bps", "ask_reach_bps", "depth_is_lower_bound",
)

_INSERT_SQL = (
    "INSERT INTO snapshots (ts_utc, exchange, symbol, "
    + ", ".join(METRIC_COLUMNS)
    + ") VALUES (?, ?, ?, "
    + ", ".join("?" for _ in METRIC_COLUMNS)
    + ")"
)  # built only from the constant names above, never from user input


def utc_now_iso() -> str:
    """Current time as an ISO 8601 UTC string. Same format everywhere, so text sorting = time sorting."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (and if needed create) the database. Rows come back like dicts."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # lets the API read while the collector writes
    conn.executescript(SCHEMA)
    return conn


def insert_snapshot(conn, ts_utc: str, exchange: str, symbol: str, metrics: dict) -> None:
    """Insert one row. `?` placeholders keep values out of the SQL text (no injection)."""
    values = (ts_utc, exchange, symbol, *(metrics[col] for col in METRIC_COLUMNS))
    with conn:  # commits on success, rolls back on error
        conn.execute(_INSERT_SQL, values)


def count_snapshots(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


def distinct_symbols(conn) -> list:
    rows = conn.execute("SELECT DISTINCT symbol FROM snapshots ORDER BY symbol")
    return [row["symbol"] for row in rows]


def fetch_history(conn, exchange: str, symbol: str, since_ts_utc: str, limit: int) -> list:
    """Newest-first rows (as dicts) for one exchange/symbol at or after `since_ts_utc`."""
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE exchange = ? AND symbol = ? AND ts_utc >= ? "
        "ORDER BY ts_utc DESC LIMIT ?",
        (exchange, symbol, since_ts_utc, limit),
    )
    return [dict(row) for row in rows]