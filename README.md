PowerShell
@'
# Order Book Liquidity Monitor

![CI](https://github.com/<YOUR_GITHUB_USERNAME>/orderbook-liquidity-monitor/actions/workflows/ci.yml/badge.svg)

An asynchronous order book liquidity collection engine and REST API built with Python, FastAPI, and SQLite WAL. It periodically polls order books across exchanges (Binance, Coinbase) for target trading pairs (BTC, ETH, SOL), computes real-time order book metrics (spreads, depth, imbalance, slippage), and serves aggregated snapshot history over HTTP.

---

## Metric Definitions

1. **Spread (bps)**: $\frac{\text{best\_ask} - \text{best\_bid}}{\text{mid\_price}} \times 10,000$
2. **Depth (10 bps)**: Total USD volume aggregated within 0.10% (10 basis points) of mid price for bids and asks.
3. **Imbalance (10 bps)**: $\frac{\text{bid\_depth\_10bps} - \text{ask\_depth\_10bps}}{\text{bid\_depth\_10bps} + \text{ask\_depth\_10bps}}$ (Ranges from -1.0 to +1.0).
4. **Slippage ($10k in bps)**: Price impact in basis points incurred when walking the order book to execute a $10,000 market buy or sell order. Returns `null` if order book depth is insufficient to fill $10k.

> **USDT vs USD Caveat**: Spread, depth, imbalance, and slippage in basis points (bps) are normalized and directly comparable across exchanges. However, nominal asset prices on Binance (USDT pairs) and Coinbase (USD pairs) reflect minor base currency/stablecoin peg discrepancies.

---

## Architecture Overview

             +-------------------+          +-------------------+
             | Binance REST API  |          | Coinbase REST API |
             +---------+---------+          +---------+---------+
                       |                              |
                       +--------------+---------------+
                                      |
                                      v
                          +-----------------------+
                          |   collector service   |
                          |  (python -m collector)|
                          +-----------+-----------+
                                      |
                                      v Writes snapshots
                    +-----------------------------------+
                    | Named Volume: /data/orderbook.db  |
                    |      (SQLite in WAL Mode)         |
                    +-----------------+-----------------+
                                      ^
                                      | Reads metrics
                          +-----------+-----------+
                          |      api service      |
                          |   (uvicorn app.api)   |
                          +-----------+-----------+
                                      |
                                      v Port 8000
                               +--------------+
                               | HTTP Client  |
                               +--------------+

---

## Key Design Decisions

| Decision | Implementation | Justification |
| :--- | :--- | :--- |
| **Storage Engine** | SQLite in WAL Mode (`PRAGMA journal_mode=WAL`) | Allows concurrent non-blocking reads (API) while continuous writes occur (Collector). |
| **Container Strategy** | Single Image / Dual Services | Shares a single lightweight `python:3.14-slim` base image for both container instances. |
| **Volume Mount** | Named Docker Volume (`orderbook-data`) | Avoids SQLite `-shm` and `-wal` file lock instability on cross-OS host bind mounts. |
| **Layer Caching** | `COPY requirements.txt .` first | Speeds up container build times by isolating dependency installation from code changes. |
| **Security** | `useradd` non-root `appuser` | Restricts container execution privileges to prevent privilege escalation vulnerabilities. |
| **Health Checks** | Standard Library `urllib.request` | Evaluates API availability inside `python:3.14-slim` without requiring `curl` binary dependencies. |

---

## Quickstart & Running

### Using Docker Compose (Recommended)

```bash
# Build and start services in detached mode
docker compose up -d --build

# View real-time collector log output
docker compose logs -f collector

# Check container status and health
docker compose ps

# Tear down containers (data inside /data volume persists)
docker compose down
Local Development
PowerShell
# Activate virtual environment in PowerShell
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run Collector locally
python -m app.collector --db orderbook.db --interval 10

# Run API locally
uvicorn app.api:app --host 127.0.0.1 --port 8001 --reload

---
title: Orderbook Liquidity Monitor
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

Live demo of the Crypto Order Book Liquidity Monitor (FastAPI + SQLite).
Interactive API docs are at `/docs`.

Source code: https://github.com/samarthkala5/orderbook-liquidity-monitor