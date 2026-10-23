import time

from app.exchanges.base import BaseExchangeClient, UnknownSymbolError, parse_book
from app.models import OrderBook

SYMBOL_MAP = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}


class CoinbaseClient(BaseExchangeClient):
    name = "coinbase"
    BASE_URL = "https://api.exchange.coinbase.com/products"

    async def fetch_order_book(self, symbol: str) -> OrderBook:
        product = SYMBOL_MAP.get(symbol)
        if product is None:
            raise UnknownSymbolError(
                f"Unsupported symbol: '{symbol}'. Supported: {list(SYMBOL_MAP)}"
            )
        data = await self._get_json(
            f"{self.BASE_URL}/{product}/book",
            params={"level": 2},  # level 2 = top 50 aggregated levels per side
            headers={"User-Agent": "OrderbookMonitor/1.0"},
            unknown_symbol_statuses=(404,),  # unknown product
        )
        bids, asks = parse_book(data, name=self.name)
        return OrderBook(self.name, symbol, bids, asks, time.time())