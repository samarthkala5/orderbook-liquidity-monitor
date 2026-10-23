from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class OrderBook:
    exchange: str
    symbol: str
    bids: List[Tuple[float, float]]  # sorted high to low
    asks: List[Tuple[float, float]]  # sorted low to high
    timestamp: float  # Unix timestamp in seconds