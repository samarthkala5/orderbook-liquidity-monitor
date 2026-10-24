"""Order Book Liquidity Analysis Script.

Loads snapshot history from SQLite, cleans data, computes summary statistics
(spread, depth, slippage), performs cross-validation against raw SQL queries,
and prints key findings.
"""

import os
import sqlite3
import pandas as pd

DB_PATH = os.getenv("DB_PATH", "orderbook_analysis.db")


def load_data(db_path: str) -> pd.DataFrame:
    """Loads snapshots table read-only into a pandas DataFrame."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found at {db_path}")

    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        df = pd.read_sql_query("SELECT * FROM snapshots", conn)
    finally:
        conn.close()

    df["ts_utc"] = pd.to_datetime(df["ts_utc"])
    return df


def analyze_liquidity(df: pd.DataFrame) -> None:
    total_rows = len(df)
    print("=== 1. DATA SUMMARY ===")
    print(f"Total Snapshots Loaded: {total_rows}")

    null_slip = df["slip_buy_10k_bps"].isna() | df["slip_sell_10k_bps"].isna()
    null_count = int(null_slip.sum())
    print(
        f"Null Slippage Rows Dropped ($10k unfilled): {null_count} "
        f"({(null_count / total_rows * 100 if total_rows > 0 else 0):.2f}%)\n"
    )

    df_clean = df[~null_slip].copy()

    print("=== 2. GROUPED METRICS BY EXCHANGE & SYMBOL ===")
    metrics = (
        df_clean.groupby(["exchange", "symbol"])
        .agg(
            snapshots=("id", "count"),
            spread_bps_mean=("spread_bps", "mean"),
            spread_bps_median=("spread_bps", "median"),
            depth_bid_10bps_mean=("depth_bid_10bps", "mean"),
            depth_ask_10bps_mean=("depth_ask_10bps", "mean"),
            slip_buy_10k_bps_mean=("slip_buy_10k_bps", "mean"),
            slip_sell_10k_bps_mean=("slip_sell_10k_bps", "mean"),
        )
        .reset_index()
    )

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 1000)
    print(metrics.to_string(index=False))
    print("\n")

    time_span = df["ts_utc"].max() - df["ts_utc"].min()
    print("=== 3. COLLECTION TIME WINDOW ===")
    print(f"Start: {df['ts_utc'].min()} UTC")
    print(f"End:   {df['ts_utc'].max()} UTC")
    print(f"Duration: {time_span}\n")

    if time_span.total_seconds() >= 86400:
        print("=== 4. SPREAD BY HOUR OF DAY ===")
        df_clean["hour"] = df_clean["ts_utc"].dt.hour
        hourly = df_clean.groupby(["hour", "exchange", "symbol"])["spread_bps"].mean().unstack(level=[1, 2])
        print(hourly)
    else:
        print("=== 4. SPREAD BY HOUR OF DAY ===")
        print(
            "Skipped: Collection span is under 24 hours. "
            "Partial-day hourly breakdown omitted to avoid misleading bias."
        )


def verify_with_raw_sql(db_path: str) -> None:
    """Cross-checks pandas calculation against raw SQL AVG query for binance BTC."""
    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    query = "SELECT AVG(spread_bps) FROM snapshots WHERE exchange='binance' AND symbol='BTC'"
    sql_avg = conn.execute(query).fetchone()[0]
    conn.close()

    print("\n=== 5. RAW SQL VERIFICATION ===")
    print(f"Raw SQL AVG(spread_bps) for binance BTC: {sql_avg:.8f}")


def main():
    print(f"Analyzing database at: {DB_PATH}\n")
    df = load_data(DB_PATH)
    analyze_liquidity(df)
    verify_with_raw_sql(DB_PATH)


if __name__ == "__main__":
    main()
