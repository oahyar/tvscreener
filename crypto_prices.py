#!/usr/bin/env python3
"""
Simple utility to retrieve crypto prices using tvscreener (CryptoScreener).

Only fetches data from the BINANCE exchange and displays a clean table
with key columns: Symbol, Price, 24h Volume, and 24h Change%.

Usage examples:
  python crypto_prices.py --top 20
  python crypto_prices.py --symbols BTC,ETH
  python crypto_prices.py --fields symbol,close,volume

Dependencies:
  - tvscreener (pip install tvscreener)
  - tabulate   (pip install tabulate) — optional, for pretty table output
"""

import argparse
import sys
import pandas as pd

# Optional: tabulate provides nice bordered table output.
# Falls back to plain pandas formatting if not installed.
try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

# Import tvscreener — the core library for fetching crypto data from TradingView
try:
    import tvscreener as tvs
except Exception as e:
    print("ERROR: could not import tvscreener. Install the package in your venv (pip install -e . or pip install tvscreener).\n", e)
    sys.exit(1)


from typing import Optional

def detect_symbol_column(df: pd.DataFrame) -> Optional[str]:
    """
    Try to find a reasonable symbol/name column in a screener DataFrame.

    Checks column names for 'symbol' or 'name' keywords first,
    then falls back to heuristic detection based on content patterns
    (looking for short uppercase alphanumeric strings).
    """
    if df is None or df.shape[1] == 0:
        return None

    # First pass: look for columns explicitly named symbol or name
    candidates = [c for c in df.columns if 'symbol' in c.lower() or 'name' in c.lower()]
    if candidates:
        return candidates[0]

    # Second pass: heuristic — find first column with mostly uppercase/alnum strings
    for c in df.columns:
        sample = df[c].astype(str).dropna().head(20).tolist()
        if not sample:
            continue
        upper_frac = sum(1 for s in sample if s.isupper() or s.replace(':', '').replace('-', '').isalnum()) / len(sample)
        if upper_frac > 0.4:
            return c

    # Last resort: just return the first column
    return df.columns[0]


def fmt_number(val):
    """
    Format a numeric value for clean display — avoids scientific notation (e.g. 1.23e+09).

    Formatting rules based on magnitude:
      - >= 1,000,000 : commas, no decimals       (e.g. 1,234,567,890)
      - >= 1         : commas, 2 decimals         (e.g. 68,700.99)
      - >= 0.01      : 4 decimal places            (e.g. 0.1022)
      - < 0.01       : 8 decimal places            (e.g. 0.00452570)
      - integers     : commas only                  (e.g. 1,000,000)
    """
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


def _find_col(df, *keywords):
    """
    Helper to find the first DataFrame column whose name contains any of the given keywords.
    Search is case-insensitive. Returns the column name or None if not found.
    """
    for kw in keywords:
        for c in df.columns:
            if kw in c.lower():
                return c
    return None


def print_df(df, top=50, fields=None):
    """
    Print a DataFrame as a formatted table.

    Args:
        df:     The DataFrame to display.
        top:    Maximum number of rows to show (default 50).
        fields: Optional list of specific column names to display.
                If not provided, auto-selects Symbol, Price, 24h Volume, 24h Chg%.
    """
    if df is None or df.shape[0] == 0:
        print("No rows returned.")
        return

    # --- Custom fields mode: user explicitly chose which columns to show ---
    if fields:
        cols = [c for c in fields if c in df.columns]
        if not cols:
            # Fallback if none of the requested fields exist in the data
            cols = df.columns[:min(len(df.columns), 8)].tolist()
        out = df[cols].head(top) if top else df[cols]
        formatted = out.copy()
        # Format all numeric columns to avoid scientific notation
        for c in formatted.columns:
            if formatted[c].dtype.kind in ('f', 'i'):
                formatted[c] = formatted[c].apply(fmt_number)
    else:
        # --- Default mode: auto-select key columns with clean display names ---
        col_map = {}  # Maps original column name -> short display name

        # Find the best matching column for each display field
        sym = _find_col(df, 'name', 'symbol')
        if sym:
            col_map[sym] = 'Symbol'
        close = _find_col(df, 'close', 'price')
        if close:
            col_map[close] = 'Price'
        vol = _find_col(df, 'volume')
        if vol:
            col_map[vol] = '24h Volume'
        chg = _find_col(df, 'change')
        if chg:
            col_map[chg] = '24h Chg%'

        # Fallback: if no columns matched, just show the first 6
        if not col_map:
            col_map = {c: c for c in df.columns[:6]}

        # Select and rename the columns
        out = df[list(col_map.keys())].head(top) if top else df[list(col_map.keys())]
        formatted = out.rename(columns=col_map).copy()

        # Strip exchange prefix (e.g. "BINANCE:BTCUSDT" -> "BTCUSDT") for cleaner display
        if 'Symbol' in formatted.columns:
            formatted['Symbol'] = formatted['Symbol'].astype(str).str.replace(r'^[A-Z]+:', '', regex=True)

        # Format all numeric columns to avoid scientific notation
        for c in formatted.columns:
            if formatted[c].dtype.kind in ('f', 'i'):
                formatted[c] = formatted[c].apply(fmt_number)

    # --- Output the table ---
    if tabulate:
        # Pretty bordered table via tabulate (pip install tabulate)
        print(tabulate(formatted, headers='keys', tablefmt='simple_grid',
                        showindex=False, numalign='right', stralign='left'))
    else:
        # Fallback: plain pandas string output
        with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 200):
            print(formatted.to_string(index=False))


def main():
    """
    Entry point: parse CLI args, fetch crypto data from BINANCE via tvscreener,
    apply any symbol filters, and print the results as a table.
    """
    # --- Parse command-line arguments ---
    p = argparse.ArgumentParser(description='Retrieve crypto prices using tvscreener')
    p.add_argument('--symbols', help='Comma separated symbols to filter (e.g. BTC,ETH)', default=None)
    p.add_argument('--top', type=int, help='Show top N rows (default: 50)', default=50)
    p.add_argument('--fields', help='Comma-separated raw column names to display (overrides default columns)', default=None)
    args = p.parse_args()

    # --- Fetch data from TradingView CryptoScreener ---
    try:
        ss = tvs.CryptoScreener()
        df = ss.get()
    except Exception as e:
        print('ERROR: failed to fetch screener data:', e)
        sys.exit(2)

    # --- Filter to BINANCE exchange only ---
    # Find the exchange column dynamically, then keep only BINANCE rows
    exchange_col = None
    for c in df.columns:
        if 'exchange' in c.lower():
            exchange_col = c
            break
    if exchange_col:
        df = df[df[exchange_col].astype(str).str.upper() == 'BINANCE']

    # --- Apply optional symbol filter (e.g. --symbols BTC,ETH) ---
    if args.symbols:
        syms = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
        sym_col = detect_symbol_column(df)
        if sym_col and sym_col in df.columns:
            # Build a boolean mask: True for rows matching any of the requested symbols
            mask = pd.Series(False, index=df.index)
            for s in syms:
                mask = mask | df[sym_col].astype(str).str.upper().str.contains(s)
            df = df[mask]

    # --- Display results ---
    fields = [f.strip() for f in args.fields.split(',')] if args.fields else None
    print_df(df, top=args.top, fields=fields)


if __name__ == '__main__':
    main()
