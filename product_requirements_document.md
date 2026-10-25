# Product Requirements: Crypto Order Book Liquidity Monitor

**Author:** Samarth Kala | **Status:** v1 live, v2 planned | **Last updated:** October 25, 2026

## 1. Problem

When you place a large market order, the price you actually get depends on how much liquidity is sitting in the order book. Spreads and depth differ by exchange and change by the minute, but the exchange UIs only show one book at a time and don't turn it into a cost number. So it is hard to answer: **"If I trade $10k of BTC right now, which exchange costs me less?"**

**Why I built it / evidence the problem is real:** As a student who transitioned from manual FnO trading to automated quantitative systems, I realized manual trading lacks the speed to analyze cross-exchange liquidity depth in real-time. I built this to solve a real problem I faced: observing true execution slippage beyond the raw ticker price.

## 2. Target user

- **Primary persona:** Retail algorithmic traders and quantitative analysts who need to optimize execution routing and minimize slippage across multiple exchanges.
- **Not for (v1):** High-frequency arbitrageurs (HFT), who require nanosecond-level WebSocket feeds or direct market access (DMA) colocation.
- **Job to be done:** "Show me the live cost of trading size on each exchange, and how it has changed."

## 3. Goals and non-goals

**Goals**
1. Compare liquidity for BTC, ETH and SOL across Binance and Coinbase in one place.
2. Turn raw order books into a few decision-ready metrics (spread, depth, imbalance, slippage).
3. Keep history so users can see how liquidity changes over time.
4. Fail safely: an exchange outage should degrade gracefully, not crash the service.

**Non-goals (v1)**
- Placing trades or any exchange authentication
- Sub-second or tick-level data
- Price prediction or trading signals

## 4. Success metrics

| Metric | Why it matters | v1 result | Target |
|---|---|---|---|
| Metric correctness vs hand-computed values | Users must be able to trust the numbers | Verified in tests | 100% of test cases |
| Data freshness (poll interval) | Stale liquidity data is misleading | 10 s | <= 10 s |
| Poll success rate (6 books per cycle) | Shows reliability against exchange failures | 99.8% | >= 99.5% |
| Snapshots stored | Proves history is being captured | 1000+ | 1,000+ |
| API error behavior | Upstream failure must not look like our bug | Clean 502 mapping | 100% of upstream failures |

## 5. User journey

1. User opens the dashboard and picks an asset (BTC, ETH or SOL).
2. They see live spread, depth and slippage per exchange.
3. They use the cross-exchange comparison to see which is cheaper right now.
4. They look at history to check whether the difference is persistent or a spike.
5. Optional: they use the REST API to pull the same data into their own tools.

**Where users get stuck:** Initially, users were confused by nominal price differences between USDT (Binance) and USD (Coinbase) pairs. I added clear tooltips explaining that spread and slippage are calculated in basis points (bps) to mathematically normalize the comparison.

## 6. Metrics definitions

| Metric | Definition | Why this one |
|---|---|---|
| Bid-ask spread (bps) | (best ask - best bid) / mid price x 10,000 | Cost of crossing the spread |
| Depth at 10 bps | Total size within 10 bps of mid on each side | How much you can trade near the current price |
| Imbalance | Bid depth vs ask depth | Short-term buy or sell pressure |
| $10k VWAP slippage | Average fill price for a $10k market order vs mid | The "what will it actually cost me" number |

**Why these four:** These four metrics directly answer the "execution cost" question. Raw prices are misleading due to stablecoin pegs, but basis point (bps) metrics normalize the data, while $10k VWAP provides a tangible dollar-impact cost.

## 7. Requirements and priority

| Priority | Requirement | Status |
|---|---|---|
| P0 | Poll Binance and Coinbase for BTC, ETH, SOL every 10 s (6 books concurrently) | Shipped |
| P0 | Compute the four metrics as tested pure functions | Shipped |
| P0 | Store snapshots (SQLite, WAL mode) | Shipped |
| P0 | 5 REST endpoints (live, history, cross-exchange comparison) | Shipped |
| P0 | Live dashboard (Chart.js) | Shipped |
| P0 | Timeouts, exponential-backoff retries, clean 502 on upstream failure | Shipped |
| P1 | Add net fee-adjusted arbitrage calculation (Binance 0.10% vs Coinbase 0.60%) | Shipped |
| P1 | Add WebSocket support for real-time tick data instead of 10s REST polling | Planned |
| P2 | Implement SQLite data retention cron job (prune snapshots older than 7 days) | Backlog |

**Why this order:** I prioritized core data correctness (polling, pure functions, testing) and non-blocking storage (SQLite WAL) over advanced features. I deliberately left out WebSocket streaming and execution (trading) logic to ensure the foundational observation layer was 100% reliable first.

## 8. Key decisions and trade-offs

| Decision | Alternative | Why I chose this | Cost of the choice |
|---|---|---|---|
| Poll every 10 s over REST | WebSocket streaming | Simpler architecture, avoids complex state management and reconnection logic for a v1 MVP. | Data can be up to 10 s old. |
| SQLite (WAL) | PostgreSQL | Zero operational overhead, single-container deployment; WAL mode perfectly handles our concurrent read/write load. | Harder to scale writes horizontally; needs a retention plan. |
| Compute metrics as pure functions | Compute inside request handlers | Makes the core financial logic completely framework-agnostic and 100% unit-testable against static JSON fixtures. | Requires slight memory overhead to pass data structures between modules. |
| Map upstream failures to 502 | Return 500 | Clearly communicates to the client that the upstream source failed, preventing false alarms about our system. | Requires maintaining a custom exception mapping layer for `httpx` network errors. |

## 9. Acceptance criteria

- Given live data, `/metrics` returns spread, depth, imbalance and slippage for each exchange and asset.
- Given a fixed order book fixture, each metric equals the hand-computed value.
- Given an invalid asset or parameter, the API returns a validation error, not a 500.
- Given an exchange timeout or error, the API returns 502 and the other exchange's data still works.
- Given a retryable failure, the poller retries with exponential backoff and does not hammer the exchange.
- A new snapshot is stored every poll cycle, and `/history` returns them in time order.
- All tests pass in GitHub Actions and a Docker image builds on every push.

## 10. Roadmap

| Horizon | What | Why |
|---|---|---|
| Now | Implement database status tracking script to monitor background task health | Ensures the background collector isn't silently failing and swallowing `asyncio` exceptions. |
| Next | Add net fee-adjusted arbitrage routing | Evolves the product from an observation tool into an actionable execution router. |
| Later | Migrate to WebSocket feeds and TimescaleDB/PostgreSQL | Required only if user demand necessitates sub-second data or historical lookbacks exceeding 30 days. |

## 11. Risks and open questions

- REST polling can hit exchange rate limits as more pairs or exchanges are added.
- SQLite will grow without a retention policy.
- Exchange APIs can change their format without notice.
- **Hosting limitations:** Cloud free tiers (like Render) often spin down after 15 minutes of inactivity, which halts background data collection. A keep-alive cron job or paid tier upgrade is required for 24/7 history.