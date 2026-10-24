@'
# Order Book Liquidity Monitor

![CI](https://github.com/<YOUR_GITHUB_USERNAME>/orderbook-liquidity-monitor/actions/workflows/ci.yml/badge.svg)

An asynchronous order book liquidity collection engine and REST API built with Python, FastAPI, and SQLite WAL. It periodically polls order books across exchanges (Binance, Coinbase) for target trading pairs (BTC, ETH, SOL), computes real-time order book metrics (spreads, depth, imbalance, slippage), and serves aggregated snapshot history over HTTP.

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