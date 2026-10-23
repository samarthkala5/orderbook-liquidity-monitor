import pytest

from app.collector import collect_one, run_cycle, run_forever
from app.exchanges.base import ExchangeError, ExchangeTimeout
from app.models import OrderBook
from app.storage import connect, count_snapshots, distinct_symbols


class FakeClient:
    """Stands in for BinanceClient/CoinbaseClient: no network."""

    def __init__(self, name, error=None, bids=None, asks=None):
        self.name = name
        self.error = error
        self.bids = bids if bids is not None else [(100.0, 1000.0)]
        self.asks = asks if asks is not None else [(100.1, 1000.0)]
        self.calls = 0

    async def fetch_order_book(self, symbol):
        self.calls += 1
        if self.error:
            raise self.error
        return OrderBook(self.name, symbol, self.bids, self.asks, 0.0)


@pytest.fixture
def conn():
    connection = connect(":memory:")
    yield connection
    connection.close()


async def test_collect_one_stores_a_row(conn):
    assert await collect_one(FakeClient("binance"), "BTC", conn, "2026-10-24T10:00:00+00:00") is True
    assert count_snapshots(conn) == 1


async def test_cycle_stores_every_exchange_symbol_pair(conn):
    clients = [FakeClient("binance"), FakeClient("coinbase")]
    assert await run_cycle(clients, conn) == 6  # 2 exchanges x 3 symbols
    assert distinct_symbols(conn) == ["BTC", "ETH", "SOL"]


async def test_one_exchange_failing_does_not_stop_the_other(conn):
    down = FakeClient("coinbase", error=ExchangeTimeout("network down"))
    up = FakeClient("binance")
    assert await run_cycle([up, down], conn) == 3  # binance rows only
    assert count_snapshots(conn) == 3
    assert down.calls == 3  # it was tried for every symbol, not abandoned after the first


async def test_unexpected_bug_is_survived_not_raised(conn):
    broken = FakeClient("binance", error=KeyError("surprise"))
    assert await collect_one(broken, "BTC", conn, "t") is False  # logged, loop would continue


async def test_invalid_book_is_skipped(conn):
    crossed = FakeClient("binance", bids=[(101.0, 1.0)], asks=[(100.0, 1.0)])
    assert await collect_one(crossed, "BTC", conn, "t") is False
    assert count_snapshots(conn) == 0


async def test_thin_book_still_stores_a_row_with_null_slippage(conn):
    thin = FakeClient("binance", bids=[(100.0, 1.0)], asks=[(100.5, 1.0)])  # far below $10k
    assert await collect_one(thin, "BTC", conn, "t") is True
    row = conn.execute("SELECT slip_buy_10k_bps FROM snapshots").fetchone()
    assert row[0] is None


async def test_run_forever_stops_after_max_cycles(conn):
    client = FakeClient("binance")
    await run_forever([client], conn, interval=0, max_cycles=2)
    assert client.calls == 6  # 2 cycles x 3 symbols
    assert count_snapshots(conn) == 6


async def test_exchange_error_base_class_is_also_survived(conn):
    assert await collect_one(FakeClient("binance", error=ExchangeError("boom")), "BTC", conn, "t") is False