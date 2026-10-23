"""Liquidity metrics computed from one order-book snapshot.

Pure functions: no network, no database, no globals. Every function takes
`bids` and `asks` as lists of (price, qty) floats and does NOT trust their
order (it sorts a copy first).

Rules we chose (and document in the README):
  * An empty side, or a crossed/locked book (best bid >= best ask), is a bad
    snapshot -> InvalidBookError. The collector logs it and skips the row.
  * A market order the book cannot fill -> InsufficientLiquidityError.
"""
from typing import Optional

DEPTH_BPS = 10  # window for the stored depth/imbalance columns
NOTIONAL = 10_000  # market-order size (quote units) for the stored slippage columns


class InvalidBookError(ValueError):
    """Empty side, or crossed/locked book."""


class InsufficientLiquidityError(ValueError):
    """The book is too thin to fill the requested market order."""


def _prepare(bids, asks):
    """Validate and return (bids high->low, asks low->high). Inputs are not modified."""
    if not bids or not asks:
        raise InvalidBookError("order book has an empty side")
    bids = sorted(bids, key=lambda level: level[0], reverse=True)
    asks = sorted(asks, key=lambda level: level[0])
    if bids[0][0] >= asks[0][0]:
        raise InvalidBookError(
            f"crossed or locked book: best bid {bids[0][0]} >= best ask {asks[0][0]}"
        )
    return bids, asks


def mid_price(bids, asks) -> float:
    """Halfway between the best bid and the best ask."""
    bids, asks = _prepare(bids, asks)
    return (bids[0][0] + asks[0][0]) / 2


def spread_bps(bids, asks) -> float:
    """(best_ask - best_bid) / mid * 10_000. One bps = 0.01 %."""
    bids, asks = _prepare(bids, asks)
    mid = (bids[0][0] + asks[0][0]) / 2
    return (asks[0][0] - bids[0][0]) / mid * 10_000


def depth_within_bps(bids, asks, x_bps: float = 10) -> tuple:
    """(bid_depth, ask_depth): quote value (price * qty) resting within x_bps of mid."""
    if x_bps < 0:
        raise ValueError("x_bps must be >= 0")
    bids, asks = _prepare(bids, asks)
    mid = (bids[0][0] + asks[0][0]) / 2
    bid_floor = mid * (1 - x_bps / 10_000)
    ask_ceiling = mid * (1 + x_bps / 10_000)
    bid_depth = 0.0
    for price, qty in bids:  # sorted, so we can stop at the first level outside
        if price < bid_floor:
            break
        bid_depth += price * qty
    ask_depth = 0.0
    for price, qty in asks:
        if price > ask_ceiling:
            break
        ask_depth += price * qty
    return bid_depth, ask_depth


def imbalance_within_bps(bids, asks, x_bps: float = 10) -> float:
    """(bid_depth - ask_depth) / (bid_depth + ask_depth), from -1 to +1. 0.0 if both are 0."""
    bid_depth, ask_depth = depth_within_bps(bids, asks, x_bps)
    total = bid_depth + ask_depth
    if total == 0:
        return 0.0
    return (bid_depth - ask_depth) / total


def book_reach_bps(bids, asks) -> tuple:
    """(bid_reach, ask_reach): how far from mid (in bps) the LAST level we received lies.

    Binance returns a limited number of levels. If the last level is still inside
    the depth window, depth may be under-counted (we simply did not see more).
    """
    bids, asks = _prepare(bids, asks)
    mid = (bids[0][0] + asks[0][0]) / 2
    return (mid - bids[-1][0]) / mid * 10_000, (asks[-1][0] - mid) / mid * 10_000


def depth_is_lower_bound(bids, asks, x_bps: float = 10) -> bool:
    """True if either side's book ends inside the x_bps window (depth may be under-counted)."""
    bid_reach, ask_reach = book_reach_bps(bids, asks)
    return bid_reach < x_bps or ask_reach < x_bps


def vwap_slippage_bps(bids, asks, side: str, notional: float = 10_000) -> float:
    """Slippage (bps vs mid) of a market order worth `notional` quote units.

    buy walks the asks upward, sell walks the bids downward, spending `notional`
    level by level. avg_price = notional / base_qty_filled (the VWAP).
    buy:  (avg_price - mid) / mid * 10_000      sell: (mid - avg_price) / mid * 10_000
    """
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if notional <= 0:
        raise ValueError("notional must be > 0")
    bids, asks = _prepare(bids, asks)
    mid = (bids[0][0] + asks[0][0]) / 2
    levels = asks if side == "buy" else bids
    remaining = float(notional)
    base_filled = 0.0
    for price, qty in levels:
        spend = min(remaining, price * qty)  # quote value we can take at this level
        base_filled += spend / price
        remaining -= spend
        if remaining <= 1e-9:  # tolerance for float rounding
            break
    if remaining > 1e-9:
        raise InsufficientLiquidityError(
            f"book can fill only {notional - remaining:.2f} of {notional} on the {side} side"
        )
    avg_price = notional / base_filled
    if side == "buy":
        return (avg_price - mid) / mid * 10_000
    return (mid - avg_price) / mid * 10_000


def _slippage_or_none(bids, asks, side, notional) -> Optional[float]:
    try:
        return vwap_slippage_bps(bids, asks, side, notional)
    except InsufficientLiquidityError:
        return None  # stored as NULL: the row is still useful


def compute_snapshot(book) -> dict:
    """Every metric for one OrderBook, as a flat dict ready for storage.

    A side the book cannot fill gives None for that slippage (NULL in SQLite).
    Invalid books (empty, crossed) raise InvalidBookError.
    """
    bids, asks = _prepare(book.bids, book.asks)
    bid_depth, ask_depth = depth_within_bps(bids, asks, DEPTH_BPS)
    bid_reach, ask_reach = book_reach_bps(bids, asks)
    mid = (bids[0][0] + asks[0][0]) / 2
    return {
        "best_bid": bids[0][0],
        "best_ask": asks[0][0],
        "mid": mid,
        "spread_bps": spread_bps(bids, asks),
        "depth_bid_10bps": bid_depth,
        "depth_ask_10bps": ask_depth,
        "imbalance_10bps": imbalance_within_bps(bids, asks, DEPTH_BPS),
        "slip_buy_10k_bps": _slippage_or_none(bids, asks, "buy", NOTIONAL),
        "slip_sell_10k_bps": _slippage_or_none(bids, asks, "sell", NOTIONAL),
        "bid_reach_bps": bid_reach,
        "ask_reach_bps": ask_reach,
        "depth_is_lower_bound": bid_reach < DEPTH_BPS or ask_reach < DEPTH_BPS,
    }