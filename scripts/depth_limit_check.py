"""Compare how far Binance's book reaches at limit=100 vs 500.
Run from repo root:  python -m scripts.depth_limit_check"""
import httpx

URL = "https://api.binance.com/api/v3/depth"


def reach_bps(data: dict) -> tuple:
    """Distance (bps) from mid to the furthest bid and furthest ask returned."""
    bids = [float(row[0]) for row in data["bids"]]  # Binance sends bids high to low
    asks = [float(row[0]) for row in data["asks"]]  # and asks low to high
    mid = (bids[0] + asks[0]) / 2
    return (mid - bids[-1]) / mid * 10_000, (asks[-1] - mid) / mid * 10_000


for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
    for limit in (100, 500):
        data = httpx.get(URL, params={"symbol": symbol, "limit": limit}, timeout=5).json()
        bid, ask = reach_bps(data)
        print(f"{symbol} limit={limit}: levels={len(data['bids'])} reaches {bid:.1f}/{ask:.1f} bps")