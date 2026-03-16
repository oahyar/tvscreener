import os
import asyncio
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
import pandas as pd
import sys

# Import scanner logic
import tvscreener as tvs
from tvscreener.field.crypto import CryptoField

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ---------------------------------------------------------------------------
# S/R Logic - EXACTLY MATCHING sr_scanner.py
# ---------------------------------------------------------------------------
SR_FIELDS = [
    CryptoField.NAME,
    CryptoField.PRICE,
    CryptoField.EXCHANGE,
    CryptoField.VOLUME,
    CryptoField.CHANGE_PERCENT,
    CryptoField.PIVOT_M_CLASSIC_MIDDLE_15,
    CryptoField.PIVOT_M_CLASSIC_S1_15,
    CryptoField.PIVOT_M_CLASSIC_S2_15,
    CryptoField.PIVOT_M_CLASSIC_S3_15,
    CryptoField.PIVOT_M_CLASSIC_R1_15,
    CryptoField.PIVOT_M_CLASSIC_R2_15,
    CryptoField.PIVOT_M_CLASSIC_R3_15,
]

def fmt_number(val):
    """Format a numeric value: avoid scientific notation, use commas for large numbers."""
    if pd.isna(val): return '-'
    if isinstance(val, float):
        if abs(val) >= 1_000_000: return f'{val:,.0f}'
        elif abs(val) >= 1: return f'{val:,.2f}'
        elif abs(val) >= 0.01: return f'{val:.4f}'
        else: return f'{val:.8f}'
    return str(val)

def _find_col(df, *keywords):
    for kw in keywords:
        for c in df.columns:
            if kw in c.lower(): return c
    return None

def _sync_fetch(symbols):
    try:
        ss = tvs.CryptoScreener()
        ss.select(*SR_FIELDS)
        
        # 1. Fetch data (Matching the broad fetch in sr_scanner.py)
        # We don't use .where() here because sr_scanner.py filters the dataframe AFTER getting it
        df = ss.get()
        
        if df.empty:
            return "❌ No coins found from TradingView."

        # 2. Filter logic - EXACTLY MATCHING sr_scanner.py
        
        # Filter to BINANCE exchange only
        exchange_col = _find_col(df, 'exchange')
        if exchange_col:
            df = df[df[exchange_col].astype(str).str.upper() == 'BINANCE']

        # Exclude stablecoin pairs
        STABLECOINS = ['USDCUSDT', 'BUSDUSDT', 'DAIUSDT', 'TUSDUSDT', 'USDPUSDT',
                       'FDUSDUSDT', 'EURUSDT', 'USTUSDT', 'PAXUSDT']
        name_col = _find_col(df, 'name', 'symbol')
        if name_col:
            stable_mask = df[name_col].astype(str).str.replace(r'^BINANCE:', '', regex=True).isin(STABLECOINS)
            df = df[~stable_mask]

            # Keep only perpetual contracts (ending with .P)
            df = df[df[name_col].astype(str).str.endswith('.P')]

            # Keep only USDT pairs
            df = df[df[name_col].astype(str).str.contains('USDT', case=False)]

            # Apply optional symbol filter
            if symbols:
                syms = [s.strip().upper() for s in symbols.replace(',', ' ').split() if s.strip()]
                mask = pd.Series(False, index=df.index)
                for s in syms:
                    mask = mask | df[name_col].astype(str).str.upper().str.contains(s)
                df = df[mask]

        if df.empty:
            return "❌ No matching Binance USDT.P coins found."

        df = df.reset_index(drop=True)

        # 3. Compute Proximity logic - EXACTLY MATCHING sr_scanner.py
        price_col = _find_col(df, 'price', 'close')
        s1_col = _find_col(df, 'classic s1')
        s2_col = _find_col(df, 'classic s2')
        s3_col = _find_col(df, 'classic s3')
        r1_col = _find_col(df, 'classic r1')
        r2_col = _find_col(df, 'classic r2')
        r3_col = _find_col(df, 'classic r3')

        results = []
        for _, row in df.iterrows():
            price = row[price_col]
            if pd.isna(price) or price == 0: continue

            supports = [row[c] for c in [s1_col, s2_col, s3_col] if c and not pd.isna(row.get(c))]
            resistances = [row[c] for c in [r1_col, r2_col, r3_col] if c and not pd.isna(row.get(c))]

            supports_below = [s for s in supports if s <= price]
            nearest_sup = max(supports_below) if supports_below else (min(supports) if supports else None)

            resistances_above = [r for r in resistances if r >= price]
            nearest_res = min(resistances_above) if resistances_above else (max(resistances) if resistances else None)

            dist_sup = ((price - nearest_sup) / price * 100) if nearest_sup else None
            dist_res = ((nearest_res - price) / price * 100) if nearest_res else None

            abs_sup = abs(dist_sup) if dist_sup is not None else float('inf')
            abs_res = abs(dist_res) if dist_res is not None else float('inf')
            nearest_pct = min(abs_sup, abs_res)

            status = "⚪"
            if nearest_pct <= 0.3:
                status = "🟢" if abs_sup <= abs_res else "🔴"
            elif nearest_pct <= 1.0:
                status = "🟡"

            symbol = str(row[name_col]).replace('BINANCE:', '').replace('.P', '')
            results.append({
                'text': f"{status} *{symbol}*: {fmt_number(price)}\n   └ S:{fmt_number(nearest_sup)} (-{dist_sup:.2f}%)\n   └ R:{fmt_number(nearest_res)} (+{dist_res:.2f}%)",
                'pct': nearest_pct
            })

        results.sort(key=lambda x: x['pct'])
        
        output = "📊 *15m S/R Scanner (BINANCE)*\n\n"
        for r in results[:15]:
            output += r['text'] + "\n"
            
        return output
    except Exception as e:
        return f"❌ Error: {str(e)}"

async def get_scan_results(symbols=None):
    return await asyncio.to_thread(_sync_fetch, symbols)

# ---------------------------------------------------------------------------
# Bot Commands & Security
# ---------------------------------------------------------------------------
# Optional: Add your Telegram User ID here to lock the bot to only you!
WHITELIST_USER_ID = os.environ.get("WHITELIST_USER_ID")
if WHITELIST_USER_ID:
    try:
        WHITELIST_USER_ID = int(WHITELIST_USER_ID)
    except ValueError:
        WHITELIST_USER_ID = None

def is_authorized(update: Update) -> bool:
    """Check if the user is authorized to use the bot."""
    if not WHITELIST_USER_ID:
        return True  # If no whitelist is set, everyone can use it
    return update.effective_user.id == WHITELIST_USER_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ Unauthorized. This is a private bot.")
        return
    await update.message.reply_text(
        "👋 Welcome! I'm your TradingView S/R Bot.\n\n"
        "Commands:\n"
        "/scan - Scan all Binance USDT.P pairs\n"
        "/scan BTC,ETH - Scan specific coins\n"
        "/id - Get your Telegram User ID"
    )

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to help the user find their Telegram ID."""
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your Telegram User ID is: `{user_id}`\n\nAdd this to your `.env` file as `WHITELIST_USER_ID={user_id}` to lock the bot.", parse_mode='Markdown')

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("⛔ Unauthorized. This is a private bot.")
        return
    msg = await update.message.reply_text("🔍 Fetching market data...")
    symbols = " ".join(context.args) if context.args else None
    report = await get_scan_results(symbols)
    try:
        await msg.edit_text(report, parse_mode='Markdown')
    except Exception:
        await msg.edit_text(report)

if __name__ == '__main__':
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        print("ERROR: TELEGRAM_TOKEN not set.")
        sys.exit(1)
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("id", id_command))
    print("Bot is starting...")
    app.run_polling()
