from abc import ABC, abstractmethod
from app.models import OrderBook

class ExchangeError(Exception):
    """Base exception for exchange client errors."""
    pass

class ExchangeTimeout(ExchangeError):
    """Raised when an HTTP request to an exchange times out."""
    pass

class UnknownSymbolError(ExchangeError):
    """Raised when an unsupported or invalid symbol is requested."""
    pass

class BaseExchangeClient(ABC):
    @abstractmethod
    async def fetch_order_book(self, symbol: str) -> OrderBook:
        """Fetch and return the current order book for the given canonical symbol (e.g., 'BTC')."""
        pass