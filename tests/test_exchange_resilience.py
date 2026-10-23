import json
from pathlib import Path

import httpx
import pytest
import respx

from app.exchanges.base import ExchangeError, ExchangeTimeout, UnknownSymbolError
from app.exchanges.binance import BinanceClient
from app.exchanges.coinbase import CoinbaseClient

FIXTURES = Path(__file__).parent / "fixtures"

BOTH = [
    pytest.param(BinanceClient, "https://api.binance.com/api/v3/depth", "binance_btc.json", id="binance_btc"),
    pytest.param(CoinbaseClient, "https://api.exchange.coinbase.com/products/BTC-USD/book", "coinbase_btc.json", id="coinbase_btc"),
]


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("client_cls,url,fixture", BOTH)
@respx.mock
async def test_5xx_is_retried_then_succeeds(client_cls, url, fixture):
    route = respx.get(url).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json=load(fixture))]
    )
    book = await client_cls(backoff=0).fetch_order_book("BTC")
    assert route.call_count == 2
    assert book.bids[0] == (100.0, 2.0)


@pytest.mark.parametrize("client_cls,url,fixture", BOTH)
@respx.mock
async def test_4xx_is_never_retried(client_cls, url, fixture):
    route = respx.get(url).mock(return_value=httpx.Response(403))
    with pytest.raises(ExchangeError):
        await client_cls(backoff=0).fetch_order_book("BTC")
    assert route.call_count == 1  # exactly one call: no retry on 4xx


@pytest.mark.parametrize("client_cls,url,fixture", BOTH)
@respx.mock
async def test_timeout_uses_all_attempts_then_raises(client_cls, url, fixture):
    route = respx.get(url).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(ExchangeTimeout):
        await client_cls(backoff=0, max_attempts=3).fetch_order_book("BTC")
    assert route.call_count == 3


@pytest.mark.parametrize("client_cls,url,fixture", BOTH)
@respx.mock
async def test_non_json_body_raises_exchange_error(client_cls, url, fixture):
    respx.get(url).mock(return_value=httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(ExchangeError):
        await client_cls(backoff=0).fetch_order_book("BTC")


@pytest.mark.parametrize("client_cls,url,fixture", BOTH)
@respx.mock
async def test_missing_keys_raise_exchange_error(client_cls, url, fixture):
    respx.get(url).mock(return_value=httpx.Response(200, json={"oops": 1}))
    with pytest.raises(ExchangeError):
        await client_cls(backoff=0).fetch_order_book("BTC")


@pytest.mark.parametrize("client_cls,url,fixture", BOTH)
@respx.mock
async def test_levels_sorted_even_if_exchange_order_is_wrong(client_cls, url, fixture):
    payload = {
        "bids": [["99.5", "3", "1"], ["100", "2", "1"]],   # wrong order on purpose
        "asks": [["101", "4", "1"], ["100.5", "1", "1"]],  # wrong order on purpose
    }
    respx.get(url).mock(return_value=httpx.Response(200, json=payload))
    book = await client_cls(backoff=0).fetch_order_book("BTC")
    assert [p for p, _ in book.bids] == [100.0, 99.5]   # high to low
    assert [p for p, _ in book.asks] == [100.5, 101.0]  # low to high


@respx.mock
async def test_binance_400_means_unknown_symbol_and_sends_limit_500():
    route = respx.get("https://api.binance.com/api/v3/depth").mock(
        return_value=httpx.Response(400, json={"code": -1121})
    )
    with pytest.raises(UnknownSymbolError):
        await BinanceClient(backoff=0).fetch_order_book("BTC")
    assert route.calls.last.request.url.params["limit"] == "500"
    assert route.calls.last.request.url.params["symbol"] == "BTCUSDT"


@respx.mock
async def test_coinbase_404_means_unknown_symbol():
    respx.get("https://api.exchange.coinbase.com/products/BTC-USD/book").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(UnknownSymbolError):
        await CoinbaseClient(backoff=0).fetch_order_book("BTC")


@pytest.mark.parametrize("client_cls", [BinanceClient, CoinbaseClient])
@respx.mock  # no routes registered: any real HTTP call would make respx raise
async def test_unsupported_symbol_fails_before_any_network_call(client_cls):
    with pytest.raises(UnknownSymbolError):
        await client_cls().fetch_order_book("DOGE")