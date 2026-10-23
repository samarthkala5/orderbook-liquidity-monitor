import json
import pathlib
import pytest
import respx
from httpx import Response, TimeoutException

from app.exchanges.base import ExchangeTimeout, UnknownSymbolError
from app.exchanges.binance import BinanceClient
from app.exchanges.coinbase import CoinbaseClient

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def binance_btc_json():
    with open(FIXTURES_DIR / "binance_btc.json") as f:
        return json.load(f)


@pytest.fixture
def coinbase_btc_json():
    with open(FIXTURES_DIR / "coinbase_btc.json") as f:
        return json.load(f)


@pytest.mark.asyncio
@respx.mock
async def test_binance_fetch_success(binance_btc_json):
    respx.get("https://api.binance.com/api/v3/depth").respond(
        status_code=200, json=binance_btc_json
    )

    client = BinanceClient()
    book = await client.fetch_order_book("BTC")

    assert book.exchange == "binance"
    assert book.symbol == "BTC"
    assert book.bids[0] == (100.0, 2.0)
    assert book.asks[0] == (100.5, 1.0)


@pytest.mark.asyncio
@respx.mock
async def test_coinbase_fetch_success(coinbase_btc_json):
    respx.get("https://api.exchange.coinbase.com/products/BTC-USD/book").respond(
        status_code=200, json=coinbase_btc_json
    )

    client = CoinbaseClient()
    book = await client.fetch_order_book("BTC")

    assert book.exchange == "coinbase"
    assert book.symbol == "BTC"
    assert book.bids[0] == (100.0, 2.0)
    assert book.asks[0] == (100.5, 1.0)


@pytest.mark.asyncio
async def test_unknown_symbol_raises():
    client = BinanceClient()
    with pytest.raises(UnknownSymbolError):
        await client.fetch_order_book("DOGE")


@pytest.mark.asyncio
@respx.mock
async def test_binance_timeout_raises():
    respx.get("https://api.binance.com/api/v3/depth").side_effect = TimeoutException(
        "Request timed out"
    )

    client = BinanceClient(max_attempts=2, backoff=0)
    with pytest.raises(ExchangeTimeout):
        await client.fetch_order_book("BTC")