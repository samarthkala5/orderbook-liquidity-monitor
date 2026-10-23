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

# Canonical symbol mapping to Binance market pair
SYMBOL_MAP = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
}


class BinanceClient(BaseExchangeClient):
    BASE_URL = "https://api.binance.com/api/v3/depth"

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

        pair = SYMBOL_MAP[symbol]
        params = {"symbol": pair, "limit": 100}

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
                        self.BASE_URL, params=params
                    )

                    # 4xx client errors (e.g., bad symbol or region block)
                    if response.status_code in (400, 404):
                        raise UnknownSymbolError(
                            f"Binance rejected symbol '{symbol}' with status {response.status_code}"
                        )

                    response.raise_for_status()
                    data = response.json()
                    break

                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    if attempt == self.max_retries:
                        raise ExchangeTimeout(
                            f"Binance request timed out after {self.max_retries} attempts"
                        ) from e
                    await asyncio.sleep(0.2 * (2 ** (attempt - 1)))

                except httpx.HTTPStatusError as e:
                    # Retry on 5xx server errors, fail fast on non-5xx
                    if e.response.status_code >= 500:
                        if attempt == self.max_retries:
                            raise ExchangeError(
                                f"Binance server error {e.response.status_code} after {self.max_retries} attempts"
                            ) from e
                        await asyncio.sleep(0.2 * (2 ** (attempt - 1)))
                    else:
                        raise ExchangeError(
                            f"Binance HTTP error: {e.response.status_code}"
                        ) from e

            if data is None:
                raise ExchangeError(
                    "Failed to retrieve data from Binance without an explicit exception"
                )

            # Convert string prices/quantities to floats
            bids = [
                (float(price), float(qty)) for price, qty in data.get("bids", [])
            ]
            asks = [
                (float(price), float(qty)) for price, qty in data.get("asks", [])
            ]

            # Bids: sorted high to low | Asks: sorted low to high
            bids.sort(key=lambda x: x[0], reverse=True)
            asks.sort(key=lambda x: x[0])

            return OrderBook(
                exchange="binance",
                symbol=symbol,
                bids=bids,
                asks=asks,
                timestamp=time.time(),
            )

        finally:
            if should_close:
                await async_client.aclose()