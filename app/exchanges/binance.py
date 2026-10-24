import os
import time

from app.exchanges.base import BaseExchangeClient, UnknownSymbolError, parse_book
from app.models import OrderBook

# Allow overriding host (e.g. https://data-api.binance.vision for cloud deployments)
BINANCE_HOST = os.getenv("BINANCE_BASE_URL", "https://api.binance.com").rstrip("/")
BINANCE_DEPTH_URL = f"{BINANCE_HOST}/api/v3/depth"

SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}


class BinanceClient(BaseExchangeClient):
    name = "binance"
    BASE_URL = BINANCE_DEPTH_URL
    DEPTH_LIMIT = 500  # levels per side; see context.md for why not 100

    async def fetch_order_book(self, symbol: str) -> OrderBook:
        pair = SYMBOL_MAP.get(symbol)
        if pair is None:
            raise UnknownSymbolError(
                f"Unsupported symbol: '{symbol}'. Supported: {list(SYMBOL_MAP)}"
            )
        data = await self._get_json(
            self.BASE_URL,
            params={"symbol": pair, "limit": self.DEPTH_LIMIT},
            unknown_symbol_statuses=(400,),  # Binance answers 400 for an invalid symbol
        )
        bids, asks = parse_book(data, name=self.name)
        return OrderBook(self.name, symbol, bids, asks, time.time())