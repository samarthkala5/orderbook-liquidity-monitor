"""Stage 2 tests. Expected values were computed BY HAND first (see comments).

Worked-example book (from PROJECT_PLAN.md section 5):
    bids = [(100.0, 2), (99.5, 3)]      asks = [(100.5, 1), (101.0, 4)]
    mid  = (100.0 + 100.5) / 2 = 100.25
"""
import pytest

from app.metrics import (
    InsufficientLiquidityError,
    InvalidBookError,
    book_reach_bps,
    compute_snapshot,
    depth_is_lower_bound,
    depth_within_bps,
    imbalance_within_bps,
    mid_price,
    spread_bps,
    vwap_slippage_bps,
)
from app.models import OrderBook

BIDS = [(100.0, 2.0), (99.5, 3.0)]
ASKS = [(100.5, 1.0), (101.0, 4.0)]


def test_mid_price():
    assert mid_price(BIDS, ASKS) == 100.25


def test_spread_bps():
    # 0.5 / 100.25 * 10_000 = 49.875 (approx)
    assert spread_bps(BIDS, ASKS) == pytest.approx(49.875, abs=1e-3)


def test_depth_within_10_bps_is_zero_for_wide_book():
    # 10 bps of 100.25 is 0.10025, so the window is [100.14975, 100.35025]:
    # neither best bid (100.0) nor best ask (100.5) is inside it.
    assert depth_within_bps(BIDS, ASKS, 10) == (0.0, 0.0)


def test_depth_within_50_bps():
    # window [99.74875, 100.75125]: bid 100.0 in (100*2 = 200), bid 99.5 out;
    # ask 100.5 in (100.5*1 = 100.5), ask 101.0 out.
    assert depth_within_bps(BIDS, ASKS, 50) == (200.0, 100.5)


def test_depth_boundary_level_is_included():
    # mid = (99 + 101) / 2 = 100; 100 bps window -> [99.0, 101.0].
    # Both best levels sit exactly ON the edge, and edge levels count (>= and <=).
    assert depth_within_bps([(99.0, 1.0)], [(101.0, 1.0)], 100) == (99.0, 101.0)


def test_imbalance_within_50_bps():
    # (200 - 100.5) / (200 + 100.5) = 99.5 / 300.5 = 0.3311 (approx)
    assert imbalance_within_bps(BIDS, ASKS, 50) == pytest.approx(0.3311, abs=1e-4)


def test_imbalance_is_zero_when_no_depth_on_either_side():
    assert imbalance_within_bps(BIDS, ASKS, 10) == 0.0


def test_buy_slippage_fills_at_first_level():
    # N = 100 < 100.5 available at 100.5, so avg price = 100.5
    # (100.5 - 100.25) / 100.25 * 10_000 = 24.94 (approx)
    assert vwap_slippage_bps(BIDS, ASKS, "buy", 100) == pytest.approx(24.94, abs=0.01)


def test_buy_slippage_spills_into_second_level():
    # level 1: spend 100.5 for 1.0 base. level 2: spend 99.5 at 101 = 0.98515 base.
    # avg = 200 / 1.98515 = 100.748; slippage = 0.498 / 100.25 * 10_000 = 49.69
    assert vwap_slippage_bps(BIDS, ASKS, "buy", 200) == pytest.approx(49.69, abs=0.01)


def test_sell_slippage_spills_into_second_level():
    # bid 100 holds 200 of value; remaining 100 at 99.5 = 1.00503 base.
    # avg = 300 / 3.00503 = 99.833; slippage = (100.25 - 99.833) / 100.25 * 10_000 = 41.62
    assert vwap_slippage_bps(BIDS, ASKS, "sell", 300) == pytest.approx(41.62, abs=0.01)


def test_order_exactly_equal_to_first_level_fills():
    assert vwap_slippage_bps(BIDS, ASKS, "buy", 100.5) == pytest.approx(24.94, abs=0.01)


def test_insufficient_liquidity_raises():
    # asks hold only 100.5 + 404 = 504.5 of value, far below 10_000
    with pytest.raises(InsufficientLiquidityError):
        vwap_slippage_bps(BIDS, ASKS, "buy", 10_000)


def test_unsorted_input_gives_same_answers_and_is_not_modified():
    bids = [(99.5, 3.0), (100.0, 2.0)]  # wrong order on purpose
    asks = [(101.0, 4.0), (100.5, 1.0)]  # wrong order on purpose
    assert mid_price(bids, asks) == 100.25
    assert depth_within_bps(bids, asks, 50) == (200.0, 100.5)
    assert bids[0] == (99.5, 3.0)  # our function must not reorder the caller's list


@pytest.mark.parametrize(
    "bids,asks",
    [
        ([], ASKS),  # empty bid side
        (BIDS, []),  # empty ask side
        ([(101.0, 1.0)], [(100.0, 1.0)]),  # crossed: bid 101 > ask 100
        ([(100.0, 1.0)], [(100.0, 1.0)]),  # locked: bid == ask
    ],
    ids=["empty_bids", "empty_asks", "crossed", "locked"],
)
def test_invalid_books_raise(bids, asks):
    with pytest.raises(InvalidBookError):
        spread_bps(bids, asks)


def test_single_level_each_side():
    # bid 99, ask 101 -> mid 100, spread 2/100*10_000 = 200 bps
    bids, asks = [(99.0, 5.0)], [(101.0, 5.0)]
    assert spread_bps(bids, asks) == pytest.approx(200.0)
    # buy 101 of value fills entirely at 101: (101 - 100)/100*10_000 = 100 bps
    assert vwap_slippage_bps(bids, asks, "buy", 101) == pytest.approx(100.0)


@pytest.mark.parametrize("side,notional", [("hold", 100), ("buy", 0), ("sell", -5)])
def test_bad_slippage_arguments_raise_value_error(side, notional):
    with pytest.raises(ValueError):
        vwap_slippage_bps(BIDS, ASKS, side, notional)


def test_book_reach_bps():
    # mid 100.25: bids end at 99.5 -> 0.75 / 100.25 * 10_000 = 74.81 bps;
    # asks end at 101.0 -> 0.75 / 100.25 * 10_000 = 74.81 bps
    bid_reach, ask_reach = book_reach_bps(BIDS, ASKS)
    assert bid_reach == pytest.approx(74.81, abs=0.01)
    assert ask_reach == pytest.approx(74.81, abs=0.01)


def test_depth_is_lower_bound_when_book_ends_inside_window():
    assert depth_is_lower_bound(BIDS, ASKS, 10) is False  # book reaches 74.8 bps > 10
    assert depth_is_lower_bound(BIDS, ASKS, 100) is True  # 74.8 bps < 100: may be more beyond


def _deep_book():
    # bid 100 x 1000, ask 100.1 x 1000 -> mid 100.05
    return OrderBook("test", "BTC", [(100.0, 1000.0)], [(100.1, 1000.0)], 0.0)


def test_compute_snapshot_on_a_deep_book():
    snap = compute_snapshot(_deep_book())
    assert snap["best_bid"] == 100.0 and snap["best_ask"] == 100.1
    assert snap["mid"] == pytest.approx(100.05)
    assert snap["spread_bps"] == pytest.approx(9.995, abs=1e-3)  # 0.1/100.05*10_000
    assert snap["depth_bid_10bps"] == pytest.approx(100_000.0)  # 100 * 1000
    assert snap["depth_ask_10bps"] == pytest.approx(100_100.0)  # 100.1 * 1000
    # (100000 - 100100) / 200100 = -0.00049975
    assert snap["imbalance_10bps"] == pytest.approx(-0.00049975, abs=1e-7)
    # buy fills at 100.1: 0.05/100.05*10_000 = 4.9975 ; sell fills at 100.0: same
    assert snap["slip_buy_10k_bps"] == pytest.approx(4.9975, abs=1e-3)
    assert snap["slip_sell_10k_bps"] == pytest.approx(4.9975, abs=1e-3)
    # the book ends 4.9975 bps from mid, inside the 10 bps window -> depth is a lower bound
    assert snap["bid_reach_bps"] == pytest.approx(4.9975, abs=1e-3)
    assert snap["depth_is_lower_bound"] is True


def test_compute_snapshot_gives_none_slippage_when_book_is_too_thin():
    snap = compute_snapshot(OrderBook("test", "BTC", BIDS, ASKS, 0.0))
    assert snap["slip_buy_10k_bps"] is None
    assert snap["slip_sell_10k_bps"] is None
    assert snap["spread_bps"] == pytest.approx(49.875, abs=1e-3)  # rest still computed


def test_compute_snapshot_rejects_invalid_book():
    with pytest.raises(InvalidBookError):
        compute_snapshot(OrderBook("test", "BTC", [], ASKS, 0.0))