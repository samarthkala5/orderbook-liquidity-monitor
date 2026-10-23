"""Manual live check. Run from the repo root:  python -m scripts.live_check"""
import asyncio

import httpx

from app.exchanges.binance import BinanceClient
from app.exchanges.coinbase import CoinbaseClient


async def main() -> None:
    async with httpx.AsyncClient() as shared:  # one client reused for all 6 calls
        for client in (BinanceClient(client=shared), CoinbaseClient(client=shared)):
            for symbol in ("BTC", "ETH", "SOL"):
                try:
                    book = await client.fetch_order_book(symbol)
                except Exception as exc:  # a check script: show every failure
                    print(f"{client.name:9} {symbol}: FAILED {exc!r}")
                    continue
                bid, ask = book.bids[0][0], book.asks[0][0]
                mid = (bid + ask) / 2
                bid_span = (mid - book.bids[-1][0]) / mid * 10_000
                ask_span = (book.asks[-1][0] - mid) / mid * 10_000
                print(
                    f"{client.name:9} {symbol}: bid={bid} ask={ask} "
                    f"levels={len(book.bids)}/{len(book.asks)} "
                    f"book reaches {bid_span:.1f}/{ask_span:.1f} bps from mid"
                )


if __name__ == "__main__":
    asyncio.run(main())