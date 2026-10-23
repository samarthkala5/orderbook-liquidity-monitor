import asyncio
import time
from typing import Optional

import httpx

from app.exchanges.base import (
    BaseExchangeClient,
    ExchangeError,
    ExchangeTimeout,
    UnknownSymbolError,
)
from app.models import OrderBook

SYMBOL_MAP = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
}


class CoinbaseClient(BaseExchangeClient):
    BASE_URL = "https://api.exchange.coinbase.com/products"

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 5.0,
        max_retries: int = 3,
    ):
        self.client = client
        self.timeout = timeout
        self.max_retries = max_retries

    async def fetch_order_book(self, symbol: str) -> OrderBook:
        if symbol not in SYMBOL_MAP:
            raise UnknownSymbolError(
                f"Unsupported symbol: '{symbol}'. Supported symbols: {list(SYMBOL_MAP.keys())}"
            )

        product_id = SYMBOL_MAP[symbol]
        url = f"{self.BASE_URL}/{product_id}/book"
        params = {"level": 2}
        headers = {"User-Agent": "OrderbookMonitor/1.0"}

        async_client = (
            self.client
            if self.client is not None
            else httpx.AsyncClient(timeout=self.timeout)
        )
        should_close = self.client is None

        try:
            data = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = await async_client.get(
                        url, params=params, headers=headers
                    )

                    if response.status_code in (400, 404):
                        raise UnknownSymbolError(
                            f"Coinbase rejected symbol '{symbol}' with status {response.status_code}"
                        )

                    response.raise_for_status()
                    data = response.json()
                    break

                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    if attempt == self.max_retries:
                        raise ExchangeTimeout(
                            f"Coinbase request timed out after {self.max_retries} attempts"
                        ) from e
                    await asyncio.sleep(0.2 * (2 ** (attempt - 1)))

                except httpx.HTTPStatusError as e:
                    if e.response.status_code >= 500:
                        if attempt == self.max_retries:
                            raise ExchangeError(
                                f"Coinbase server error {e.response.status_code} after {self.max_retries} attempts"
                            ) from e
                        await asyncio.sleep(0.2 * (2 ** (attempt - 1)))
                    else:
                        raise ExchangeError(
                            f"Coinbase HTTP error: {e.response.status_code}"
                        ) from e

            if data is None:
                raise ExchangeError(
                    "Failed to retrieve data from Coinbase without an explicit exception"
                )

            # Coinbase entries are [price, size, num_orders]
            bids = [
                (float(item[0]), float(item[1])) for item in data.get("bids", [])
            ]
            asks = [
                (float(item[0]), float(item[1])) for item in data.get("asks", [])
            ]

            bids.sort(key=lambda x: x[0], reverse=True)
            asks.sort(key=lambda x: x[0])

            return OrderBook(
                exchange="coinbase",
                symbol=symbol,
                bids=bids,
                asks=asks,
                timestamp=time.time(),
            )

        finally:
            if should_close:
                await async_client.aclose()