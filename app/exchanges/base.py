import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from app.models import OrderBook


class ExchangeError(Exception):
    """Base exception for exchange client errors."""


class ExchangeTimeout(ExchangeError):
    """Raised when we could not reach the exchange (timeout or network error)."""


class UnknownSymbolError(ExchangeError):
    """Raised when an unsupported or invalid symbol is requested."""


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    name: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 5.0,
    max_attempts: int = 3,
    backoff: float = 0.2,
    unknown_symbol_statuses: tuple = (),
) -> Any:
    """GET a URL and return parsed JSON. The ONE place that holds the retry policy.

    Retried (transient):     timeouts, network errors, HTTP 5xx.
    Never retried (our bug): HTTP 4xx. The same request would get the same answer.
    Sleeps backoff, 2*backoff, 4*backoff ... between attempts (never after the last).
    """
    for attempt in range(1, max_attempts + 1):
        is_last = attempt == max_attempts
        try:
            response = await client.get(
                url, params=params, headers=headers, timeout=timeout
            )
        except httpx.TransportError as exc:  # timeouts, connect/read errors, protocol errors
            if is_last:
                raise ExchangeTimeout(
                    f"{name}: network/timeout error after {attempt} attempts: {exc!r}"
                ) from exc
        else:
            status = response.status_code
            if status in unknown_symbol_statuses:
                raise UnknownSymbolError(f"{name}: HTTP {status}, symbol rejected")
            if 400 <= status < 500:
                raise ExchangeError(f"{name}: HTTP {status} (client error, not retried)")
            if status >= 500:
                if is_last:
                    raise ExchangeError(f"{name}: HTTP {status} after {attempt} attempts")
            else:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ExchangeError(f"{name}: response was not valid JSON") from exc
        await asyncio.sleep(backoff * 2 ** (attempt - 1))
    raise ExchangeError(f"{name}: max_attempts must be at least 1")


def parse_book(data: Any, *, name: str) -> tuple:
    """Turn a raw payload into (bids, asks): lists of (price, qty) floats, sorted by us.

    Works for Binance rows [price, qty] and Coinbase rows [price, size, num_orders].
    We never trust the exchange's ordering.
    """
    try:
        raw_bids, raw_asks = data["bids"], data["asks"]
        bids = [(float(row[0]), float(row[1])) for row in raw_bids]
        asks = [(float(row[0]), float(row[1])) for row in raw_asks]
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ExchangeError(f"{name}: malformed order book payload: {exc!r}") from exc
    bids.sort(key=lambda lv: lv[0], reverse=True)
    asks.sort(key=lambda lv: lv[0])
    return bids, asks


class BaseExchangeClient(ABC):
    name: str = "exchange"

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 5.0,
        max_attempts: int = 3,
        backoff: float = 0.2,
    ):
        self.client = client  # inject one shared client in the collector/API
        self.timeout = timeout
        self.max_attempts = max_attempts  # total tries, not "extra" retries
        self.backoff = backoff  # tests pass 0 so they don't sleep

    @abstractmethod
    async def fetch_order_book(self, symbol: str) -> OrderBook:
        """Fetch the current book for a canonical symbol such as 'BTC'."""

    async def _get_json(self, url, *, params=None, headers=None, unknown_symbol_statuses=()):
        kwargs = dict(
            name=self.name,
            params=params,
            headers=headers,
            timeout=self.timeout,
            max_attempts=self.max_attempts,
            backoff=self.backoff,
            unknown_symbol_statuses=unknown_symbol_statuses,
        )
        if self.client is not None:
            return await get_json(self.client, url, **kwargs)
        async with httpx.AsyncClient() as client:  # opened and always closed here
            return await get_json(client, url, **kwargs)