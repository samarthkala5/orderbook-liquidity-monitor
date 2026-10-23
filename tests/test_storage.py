import sqlite3

import pytest

from app.storage import (
    METRIC_COLUMNS,
    connect,
    count_snapshots,
    distinct_symbols,
    fetch_history,
    insert_snapshot,
)


def make_metrics(**overrides):
    metrics = {
        "best_bid": 100.0, "best_ask": 100.1, "mid": 100.05, "spread_bps": 9.995,
        "depth_bid_10bps": 100_000.0, "depth_ask_10bps": 100_100.0,
        "imbalance_10bps": -0.00049975,
        "slip_buy_10k_bps": 4.9975, "slip_sell_10k_bps": 4.9975,
        "bid_reach_bps": 4.9975, "ask_reach_bps": 4.9975,
        "depth_is_lower_bound": True,
    }
    metrics.update(overrides)
    return metrics


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


def test_insert_and_read_back_round_trip(conn):
    insert_snapshot(conn, "2026-10-24T10:00:00+00:00", "binance", "BTC", make_metrics())
    row = conn.execute("SELECT * FROM snapshots").fetchone()
    assert row["ts_utc"] == "2026-10-24T10:00:00+00:00"
    assert (row["exchange"], row["symbol"]) == ("binance", "BTC")
    assert row["spread_bps"] == pytest.approx(9.995)
    assert row["depth_is_lower_bound"] == 1  # True is stored as 1


def test_none_slippage_is_stored_as_null(conn):
    insert_snapshot(conn, "2026-10-24T10:00:00+00:00", "coinbase", "SOL",
                    make_metrics(slip_buy_10k_bps=None, slip_sell_10k_bps=None))
    row = conn.execute("SELECT * FROM snapshots").fetchone()
    assert row["slip_buy_10k_bps"] is None and row["slip_sell_10k_bps"] is None


def test_metric_columns_match_table_columns(conn):
    table_columns = [r["name"] for r in conn.execute("PRAGMA table_info(snapshots)")]
    assert table_columns == ["id", "ts_utc", "exchange", "symbol", *METRIC_COLUMNS]


def test_count_and_distinct_symbols(conn):
    for symbol in ("ETH", "BTC", "BTC"):
        insert_snapshot(conn, "2026-10-24T10:00:00+00:00", "binance", symbol, make_metrics())
    assert count_snapshots(conn) == 3
    assert distinct_symbols(conn) == ["BTC", "ETH"]


def test_history_filters_orders_newest_first_and_limits(conn):
    for minute in range(5):
        insert_snapshot(conn, f"2026-10-24T10:0{minute}:00+00:00", "binance", "BTC", make_metrics())
    insert_snapshot(conn, "2026-10-24T10:03:00+00:00", "coinbase", "BTC", make_metrics())  # other exchange
    insert_snapshot(conn, "2026-10-24T10:03:00+00:00", "binance", "ETH", make_metrics())   # other symbol
    rows = fetch_history(conn, "binance", "BTC", "2026-10-24T10:01:00+00:00", limit=3)
    assert [r["ts_utc"][11:16] for r in rows] == ["10:04", "10:03", "10:02"]  # newest first, cut at 3
    older = fetch_history(conn, "binance", "BTC", "2026-10-24T10:03:00+00:00", limit=100)
    assert len(older) == 2  # since is inclusive: 10:03 and 10:04


def test_history_is_empty_for_unknown_pair(conn):
    assert fetch_history(conn, "binance", "DOGE", "2000-01-01T00:00:00+00:00", 10) == []


def test_data_survives_closing_and_reopening_a_file(tmp_path):
    path = str(tmp_path / "test.db")
    first = connect(path)
    insert_snapshot(first, "2026-10-24T10:00:00+00:00", "binance", "BTC", make_metrics())
    first.close()
    second = connect(path)  # connect() must not wipe existing data
    assert count_snapshots(second) == 1
    second.close()


def test_failed_insert_leaves_no_partial_row(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_snapshot(conn, "2026-10-24T10:00:00+00:00", "binance", "BTC",
                        make_metrics(best_bid=None))  # NOT NULL column
    assert count_snapshots(conn) == 0