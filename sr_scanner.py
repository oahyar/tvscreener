#!/usr/bin/env python3
"""
Multi-coin Support/Resistance Scanner using tvscreener.

Scans all Binance crypto pairs and identifies which coins are currently
near key support or resistance levels (Classic Pivot Points from TradingView).
Sorts by proximity so the most actionable opportunities appear first.

Usage examples:
  python sr_scanner.py --top 10
  python sr_scanner.py --symbols BTC,ETH,SOL
  python sr_scanner.py --threshold 1.5 --sort support

Dependencies:
  - tvscreener (pip install tvscreener)
  - tabulate   (pip install tabulate)
"""

import argparse
import sys
import pandas as pd

# Optional: tabulate for nice bordered table output
try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

# Import tvscreener for fetching crypto data from TradingView
try:
    import tvscreener as tvs
    from tvscreener.field.crypto import CryptoField
except Exception as e:
    print("ERROR: could not import tvscreener.\n", e)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Fields we need from the screener
# ---------------------------------------------------------------------------
# We request only the columns we need for S/R analysis.
# Using 15-minute timeframe pivot points (|15 suffix) for tighter intraday trading.
SR_FIELDS = [
    CryptoField.NAME,
    CryptoField.PRICE,          # current price (maps to 'close')
    CryptoField.EXCHANGE,
    CryptoField.VOLUME,
    CryptoField.CHANGE_PERCENT,
    # Classic Pivot Point levels — 15-minute timeframe, pre-computed by TradingView
    CryptoField.PIVOT_M_CLASSIC_MIDDLE_15,   # Pivot (P)
    CryptoField.PIVOT_M_CLASSIC_S1_15,       # Support 1
    CryptoField.PIVOT_M_CLASSIC_S2_15,       # Support 2
    CryptoField.PIVOT_M_CLASSIC_S3_15,       # Support 3
    CryptoField.PIVOT_M_CLASSIC_R1_15,       # Resistance 1
    CryptoField.PIVOT_M_CLASSIC_R2_15,       # Resistance 2
    CryptoField.PIVOT_M_CLASSIC_R3_15,       # Resistance 3
]


# ---------------------------------------------------------------------------
# Number formatting (reused from crypto_prices.py)
# ---------------------------------------------------------------------------
def fmt_number(val):
    """Format a numeric value: avoid scientific notation, use commas for large numbers."""
    if pd.isna(val):
        return ''
    if isinstance(val, float):
        if abs(val) >= 1_000_000:
            return f'{val:,.0f}'
        elif abs(val) >= 1:
            return f'{val:,.2f}'
        elif abs(val) >= 0.01:
            return f'{val:.4f}'
        else:
            return f'{val:.8f}'
    if isinstance(val, int):
        return f'{val:,}'
    return str(val)


def fmt_pct(val):
    """Format a percentage value with sign and % symbol."""
    if pd.isna(val):
        return ''
    return f'{val:+.2f}%'


# ---------------------------------------------------------------------------
# Core logic: compute proximity to S/R levels
# ---------------------------------------------------------------------------
def compute_sr_proximity(df):
    """
    For each row, compute:
      - nearest_support: the closest support level below current price
      - nearest_resistance: the closest resistance level above current price
      - dist_support_pct: % distance from price to nearest support (negative = below price)
      - dist_resistance_pct: % distance from price to nearest resistance (positive = above price)
      - nearest_level_pct: absolute % distance to whichever level is closest
      - zone: 'Near Support', 'Near Resistance', or 'Mid-Range'
    """
    # Find the column names dynamically by matching label text
    price_col = _find_col(df, 'price', 'close')
    s1_col = _find_col(df, 'classic s1')
    s2_col = _find_col(df, 'classic s2')
    s3_col = _find_col(df, 'classic s3')
    r1_col = _find_col(df, 'classic r1')
    r2_col = _find_col(df, 'classic r2')
    r3_col = _find_col(df, 'classic r3')

    if not all([price_col, s1_col, r1_col]):
        print("ERROR: could not find required price/pivot columns in the data.")
        print("Available columns:", list(df.columns))
        sys.exit(3)

    results = []
    for _, row in df.iterrows():
        price = row[price_col]
        if pd.isna(price) or price == 0:
            continue

        # Gather support levels (below price)
        supports = []
        for col in [s1_col, s2_col, s3_col]:
            if col and not pd.isna(row.get(col)):
                supports.append(row[col])

        # Gather resistance levels (above price)
        resistances = []
        for col in [r1_col, r2_col, r3_col]:
            if col and not pd.isna(row.get(col)):
                resistances.append(row[col])

        # Find nearest support (highest value that's <= price)
        supports_below = [s for s in supports if s <= price]
        nearest_sup = max(supports_below) if supports_below else (min(supports) if supports else None)

        # Find nearest resistance (lowest value that's >= price)
        resistances_above = [r for r in resistances if r >= price]
        nearest_res = min(resistances_above) if resistances_above else (max(resistances) if resistances else None)

        # Calculate % distances
        dist_sup = ((price - nearest_sup) / price * 100) if nearest_sup else None
        dist_res = ((nearest_res - price) / price * 100) if nearest_res else None

        # Determine which level is closer
        abs_sup = abs(dist_sup) if dist_sup is not None else float('inf')
        abs_res = abs(dist_res) if dist_res is not None else float('inf')
        nearest_pct = min(abs_sup, abs_res)

        # Label the zone (Stricter thresholds for tighter intraday trading)
        if nearest_pct <= 0.3:
            zone = '🟢 Near S' if abs_sup <= abs_res else '🔴 Near R'
        elif nearest_pct <= 1.0:
            zone = '🟡 Mid'
        else:
            zone = '⚪ Far'

        results.append({
            'price': price,
            'nearest_sup': nearest_sup,
            'nearest_res': nearest_res,
            'dist_sup': dist_sup,
            'dist_res': dist_res,
            'nearest_pct': nearest_pct,
            'zone': zone,
        })

    return results


def _find_col(df, *keywords):
    """Find the first DataFrame column whose name contains any of the keywords (case-insensitive)."""
    for kw in keywords:
        for c in df.columns:
            if kw in c.lower():
                return c
    return None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def print_sr_table(df, sr_data, top=30):
    """Build and print the final S/R scanner table."""
    if not sr_data:
        print("No data to display.")
        return

    name_col = _find_col(df, 'name', 'symbol')

    rows = []
    for i, sr in enumerate(sr_data):
        idx = df.index[i]
        symbol = str(df.at[idx, name_col]).replace('BINANCE:', '') if name_col else f'Row {i}'
        rows.append({
            'Symbol': symbol,
            'Price': fmt_number(sr['price']),
            'S1': fmt_number(sr['nearest_sup']) if sr['nearest_sup'] else '-',
            'R1': fmt_number(sr['nearest_res']) if sr['nearest_res'] else '-',
            'Dist S': fmt_pct(-sr['dist_sup']) if sr['dist_sup'] is not None else '-',
            'Dist R': fmt_pct(sr['dist_res']) if sr['dist_res'] is not None else '-',
            'Zone': sr['zone'],
        })

    # Sort by nearest_pct (closest to any level first)
    sorted_indices = sorted(range(len(sr_data)), key=lambda i: sr_data[i]['nearest_pct'])
    sorted_rows = [rows[i] for i in sorted_indices]

    # Apply top limit
    sorted_rows = sorted_rows[:top]

    if tabulate:
        print(tabulate(sorted_rows, headers='keys', tablefmt='simple_grid',
                        numalign='right', stralign='left'))
    else:
        out_df = pd.DataFrame(sorted_rows)
        with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 200):
            print(out_df.to_string(index=False))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    """
    Entry point: fetch Binance crypto data with pivot point fields,
    compute proximity to S/R levels, and display sorted results.
    """
    # --- Parse CLI arguments ---
    p = argparse.ArgumentParser(
        description='Scan Binance crypto pairs for support/resistance proximity')
    p.add_argument('--symbols', help='Comma-separated symbols to filter (e.g. BTC,ETH,SOL)', default=None)
    p.add_argument('--top', type=int, help='Show top N results (default: 30)', default=30)
    p.add_argument('--threshold', type=float,
                   help='Only show coins within N%% of a S/R level (default: show all)', default=None)
    args = p.parse_args()

    # --- Fetch data from TradingView with specific pivot point fields ---
    print("Fetching crypto data with pivot points from TradingView...")
    try:
        ss = tvs.CryptoScreener()
        # Select only the fields we need for S/R analysis
        ss.select(*SR_FIELDS)
        df = ss.get()
    except Exception as e:
        print('ERROR: failed to fetch screener data:', e)
        sys.exit(2)

    # --- Filter to BINANCE exchange only ---
    exchange_col = _find_col(df, 'exchange')
    if exchange_col:
        df = df[df[exchange_col].astype(str).str.upper() == 'BINANCE']

    # --- Exclude stablecoin pairs (they barely move, not useful for S/R) ---
    STABLECOINS = ['USDCUSDT', 'BUSDUSDT', 'DAIUSDT', 'TUSDUSDT', 'USDPUSDT',
                   'FDUSDUSDT', 'EURUSDT', 'USTUSDT', 'PAXUSDT']
    name_col = _find_col(df, 'name', 'symbol')
    if name_col:
        stable_mask = df[name_col].astype(str).str.replace(r'^BINANCE:', '', regex=True).isin(STABLECOINS)
        df = df[~stable_mask]

    # --- Keep only perpetual contracts (symbols ending with .P) ---
    if name_col:
        df = df[df[name_col].astype(str).str.endswith('.P')]

    # --- Keep only USDT pairs (exclude USDC duplicates) ---
    if name_col:
        df = df[df[name_col].astype(str).str.contains('USDT', case=False)]

    # --- Apply optional symbol filter ---
    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
        name_col = _find_col(df, 'name', 'symbol')
        if name_col:
            mask = pd.Series(False, index=df.index)
            for s in syms:
                mask = mask | df[name_col].astype(str).str.upper().str.contains(s)
            df = df[mask]

    if df.empty:
        print("No matching coins found.")
        sys.exit(0)

    # --- Reset index so we can iterate cleanly ---
    df = df.reset_index(drop=True)

    # --- Compute S/R proximity for each coin ---
    sr_data = compute_sr_proximity(df)

    # --- Apply threshold filter if specified ---
    if args.threshold is not None:
        filtered_indices = [i for i, sr in enumerate(sr_data) if sr['nearest_pct'] <= args.threshold]
        if not filtered_indices:
            print(f"No coins within {args.threshold}% of a S/R level.")
            sys.exit(0)
        df = df.iloc[filtered_indices].reset_index(drop=True)
        sr_data = [sr_data[i] for i in filtered_indices]

    # --- Display results ---
    print(f"\n📊 S/R Scanner — BINANCE ({len(sr_data)} coins, sorted by proximity)\n")
    print_sr_table(df, sr_data, top=args.top)

    # --- Legend ---
    print("\n🟢 Near S = within 0.3% of support (potential buy)")
    print("🔴 Near R = within 0.3% of resistance (potential sell)")
    print("🟡 Mid    = within 1% of a level")
    print("⚪ Far    = >1% from nearest level")


if __name__ == '__main__':
    main()
