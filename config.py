import os
import MetaTrader5 as mt5

# ── Symbols & timeframe ─────────────────────────────────────────────────────
SYMBOLS = ["XAUUSD", "XAGUSD"]          # every symbol gets its own SymbolTrader
TIMEFRAME = mt5.TIMEFRAME_M5            # signal timeframe
MAGIC_NUMBER = 998877

# ── Risk (account-wide) ────────────────────────────────────────────────────
RISK_USD_PER_TRADE = 5.0                # max loss at SL per trade, account currency
MAX_DAILY_LOSS_USD = 15.0               # net daily loss -> pause until next server day
MAX_CONSECUTIVE_LOSSES = 2              # closed losers in a row -> pause
MAX_TRADES_PER_DAY = 6                  # entries per server day across all symbols
MAX_ALLOWED_SPREAD_POINTS = {           # per-symbol spread cap in points
    "XAUUSD": 35,
    "XAGUSD": 40,
    "default": 30,
}

# ── Indicators ─────────────────────────────────────────────────────────────
ATR_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
SL_ATR_MULTIPLIER = 1.5
TP_ATR_MULTIPLIER = 3.0
RATES_LOOKBACK = 120                    # bars fetched on the signal timeframe

# ── Trend filter (higher timeframe) ────────────────────────────────────────
TREND_FILTER_ENABLED = True
TREND_TIMEFRAME = mt5.TIMEFRAME_H1
TREND_EMA_PERIOD = 200                  # buy only above EMA, sell only below

# ── Session filter (server time) ───────────────────────────────────────────
SESSION_FILTER_ENABLED = True
SESSION_START_HOUR = 7                  # inclusive
SESSION_END_HOUR = 20                   # exclusive
TRADING_WEEKDAYS = (0, 1, 2, 3, 4)      # Mon..Fri

# ── Position management ────────────────────────────────────────────────────
MANAGE_POSITIONS = True
BREAKEVEN_ATR = 1.0                     # move SL to entry after this much ATR in profit
TRAIL_ATR = 1.0                         # then trail SL this far behind price

# ── Reporting ──────────────────────────────────────────────────────────────
HEARTBEAT_HOURS = 4
DAILY_SUMMARY_HOUR = 23                 # server time

# ── Logging ────────────────────────────────────────────────────────────────
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")
TRADE_JOURNAL = os.path.join(LOG_DIR, "trades.csv")

# ── Loop timing ────────────────────────────────────────────────────────────
LOOP_SLEEP_SECONDS = 10
ERROR_SLEEP_SECONDS = 30
BREAKER_SLEEP_SECONDS = 300             # re-check breaker every 5 min while paused

# ── Status page ─────────────────────────────────────────────────────────────
WEB_ENABLED = True
WEB_HOST = "127.0.0.1"                  # "0.0.0.0" to reach it from your phone on the same Wi-Fi
WEB_PORT = 8080
WEB_RECENT_TRADES = 50                  # journal rows shown on the page

# ── Telegram ───────────────────────────────────────────────────────────────
# Preferred: set TELEGRAM_TOKEN / TELEGRAM_CHAT_ID as environment variables.
# The literals below are only a fallback for local runs.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8941980370:AAFUhhvISIJuQ4ls5J_1l3Acgup4UbFp994")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1233013114")


def spread_limit(symbol: str) -> int:
    return MAX_ALLOWED_SPREAD_POINTS.get(symbol, MAX_ALLOWED_SPREAD_POINTS["default"])


#Name     : Name     : auto nadeem
#Type     : Forex Hedged USD
#Server   : MetaQuotes-Demo
#Login    : 5055551748
#Password : Gf*wQg6f
#Investor : W_DcC8If
#