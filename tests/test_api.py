"""API tests: no network. Exchanges are replaced by fakes, the database by a temp file."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import app, get_clients, get_db_path
from app.exchanges.base import ExchangeTimeout
from app.metrics import compute_snapshot
from app.models import OrderBook
from app.storage import connect, insert_snapshot, utc_now_iso


class FakeClient:
    """Stands in for BinanceClient/CoinbaseClient."""

    def __init__(self, name, error=None, bids=None, asks=None):
        self.name = name
        self.error = error
        self.bids = bids if bids is not None else [(100.0, 1000.0)]
        self.asks = asks if asks is not None else [(100.1, 1000.0)]

    async def fetch_order_book(self, symbol):
        if self.error:
            raise self.error
        return OrderBook(self.name, symbol, self.bids, self.asks, 0.0)


def minutes_ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


@pytest.fixture
def setup(tmp_path):
    """Returns (client, fakes, db_path). Overrides are removed after each test."""
    db_path = str(tmp_path / "api_test.db")
    connect(db_path).close()  # create the empty database file with the schema
    fakes = {"binance": FakeClient("binance"), "coinbase": FakeClient("coinbase")}
    app.dependency_overrides[get_db_path] = lambda: db_path
    app.dependency_overrides[get_clients] = lambda: fakes
    yield TestClient(app), fakes, db_path
    app.dependency_overrides.clear()


def add_rows(db_path, timestamps, exchange="binance", symbol="BTC"):
    conn = connect(db_path)
    metrics = compute_snapshot(OrderBook(exchange, symbol, [(100.0, 1000.0)], [(100.1, 1000.0)], 0.0))
    for ts in timestamps:
        insert_snapshot(conn, ts, exchange, symbol, metrics)
    conn.close()


# ----- /health and /symbols -----

def test_health_on_empty_database(setup):
    client, _, _ = setup
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "snapshots": 0}


def test_health_counts_stored_rows(setup):
    client, _, db_path = setup
    add_rows(db_path, [utc_now_iso(), minutes_ago(1)])
    assert client.get("/health").json()["snapshots"] == 2


def test_symbols(setup):
    client, _, _ = setup
    assert client.get("/symbols").json() == {
        "exchanges": ["binance", "coinbase"],
        "symbols": ["BTC", "ETH", "SOL"],
    }


# ----- /metrics -----

def test_live_metrics_success(setup):
    client, _, _ = setup
    body = client.get("/metrics/binance/BTC").json()
    assert body["exchange"] == "binance" and body["symbol"] == "BTC"
    assert body["spread_bps"] == pytest.approx(9.995, abs=1e-3)  # 0.1 / 100.05 * 10_000
    assert body["depth_is_lower_bound"] is True


def test_live_metrics_accepts_lowercase_input(setup):
    client, _, _ = setup
    response = client.get("/metrics/Binance/btc")
    assert response.status_code == 200
    assert response.json()["symbol"] == "BTC"


def test_thin_book_returns_null_slippage(setup):
    client, fakes, _ = setup
    fakes["binance"].bids, fakes["binance"].asks = [(100.0, 1.0)], [(100.5, 1.0)]  # far below $10k
    body = client.get("/metrics/binance/BTC").json()
    assert body["slip_buy_10k_bps"] is None and body["slip_sell_10k_bps"] is None


@pytest.mark.parametrize("path", ["/metrics/binance/DOGE", "/metrics/kraken/BTC",
                                  "/history/binance/DOGE", "/history/kraken/BTC", "/compare/DOGE"])
def test_unknown_exchange_or_symbol_is_404(setup, path):
    client, _, _ = setup
    assert client.get(path).status_code == 404


def test_upstream_failure_is_502(setup):
    client, fakes, _ = setup
    fakes["binance"].error = ExchangeTimeout("network down")
    response = client.get("/metrics/binance/BTC")
    assert response.status_code == 502
    assert "binance" in response.json()["detail"]


def test_invalid_book_from_upstream_is_502(setup):
    client, fakes, _ = setup
    fakes["coinbase"].bids, fakes["coinbase"].asks = [(101.0, 1.0)], [(100.0, 1.0)]  # crossed
    assert client.get("/metrics/coinbase/ETH").status_code == 502


# ----- /history -----

def test_history_is_newest_first_and_respects_minutes(setup):
    client, _, db_path = setup
    newest, middle, old = utc_now_iso(), minutes_ago(5), minutes_ago(180)
    add_rows(db_path, [old, newest, middle])
    rows = client.get("/history/binance/BTC", params={"minutes": 60}).json()
    assert [row["ts_utc"] for row in rows] == [newest, middle]  # 3 h old row excluded


def test_history_respects_limit(setup):
    client, _, db_path = setup
    add_rows(db_path, [minutes_ago(m) for m in range(5)])
    assert len(client.get("/history/binance/BTC", params={"limit": 2}).json()) == 2


def test_history_only_returns_the_requested_pair(setup):
    client, _, db_path = setup
    add_rows(db_path, [utc_now_iso()], exchange="binance", symbol="BTC")
    add_rows(db_path, [utc_now_iso()], exchange="coinbase", symbol="BTC")
    rows = client.get("/history/binance/BTC").json()
    assert len(rows) == 1 and rows[0]["exchange"] == "binance"


@pytest.mark.parametrize("params", [
    {"minutes": 0}, {"minutes": 99999}, {"limit": 0}, {"limit": 999999}, {"minutes": "abc"},
])
def test_history_validates_query_params(setup, params):
    client, _, _ = setup
    assert client.get("/history/binance/BTC", params=params).status_code == 422


# ----- /compare -----

def test_compare_returns_both_exchanges_with_note(setup):
    client, _, _ = setup
    body = client.get("/compare/BTC").json()
    assert body["symbol"] == "BTC"
    assert [e["exchange"] for e in body["exchanges"]] == ["binance", "coinbase"]
    assert "USDT" in body["note"]


def test_compare_is_502_if_one_exchange_fails(setup):
    client, fakes, _ = setup
    fakes["coinbase"].error = ExchangeTimeout("slow")
    assert client.get("/compare/BTC").status_code == 502


# ----- contract -----

def test_exactly_five_routes_are_documented():
    assert set(app.openapi()["paths"]) == {
        "/health",
        "/symbols",
        "/metrics/{exchange}/{symbol}",
        "/history/{exchange}/{symbol}",
        "/compare/{symbol}",
    }
from fastapi.testclient import TestClient
from app.api import app

client = TestClient(app)

def test_root_returns_dashboard_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Orderbook Liquidity Monitor</title>" in response.text

def test_openapi_schema_has_exactly_five_endpoints():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema.get("paths", {})
    # Verify exactly 5 API paths are exposed in the documentation schema
    assert len(paths) == 5
    assert set(paths.keys()) == {
        "/health",
        "/symbols",
        "/metrics/{exchange}/{symbol}",
        "/history/{exchange}/{symbol}",
        "/compare/{symbol}",
    }