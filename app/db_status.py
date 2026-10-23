"""Show what the collector has stored. Run:  python -m scripts.db_status [path-to-db]"""
import sys

from app.storage import DEFAULT_DB_PATH, connect

conn = connect(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH)
total, first, last = conn.execute("SELECT COUNT(*), MIN(ts_utc), MAX(ts_utc) FROM snapshots").fetchone()
print(f"rows={total}  first={first}  last={last}")
for row in conn.execute(
    "SELECT exchange, symbol, COUNT(*) AS n, SUM(slip_buy_10k_bps IS NULL) AS thin "
    "FROM snapshots GROUP BY exchange, symbol ORDER BY exchange, symbol"
):
    print(f"  {row['exchange']:9} {row['symbol']}: {row['n']} rows ({row['thin']} with NULL slippage)")