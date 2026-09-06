import os
import MetaTrader5 as mt5


def _load_dotenv(path: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")) -> None:
    """Load KEY=VALUE lines from a local .env file (gitignored). Real environment variables win."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))
    except FileNotFoundError:
        pass


_load_dotenv()

# ── Symbols & timeframe ─────────────────────────────────────────────────────
SYMBOLS = ["XAUUSD", "XAGUSD"]          # every symbol gets its own SymbolTrader
TIMEFRAME = mt5.TIMEFRAME_M5            # signal timeframe
MAGIC_NUMBER = 998877

# ── Risk (account-wide) ────────────────────────────────────────────────────
RISK_USD_PER_TRADE = 5.0                # max loss at SL per trade, account currency
MAX_DAILY_LOSS_USD = 30.0               # net daily loss -> pause until next server day (relaxed for the demo phase, 2026-09-06)
MAX_CONSECUTIVE_LOSSES = 6              # closed losers in a row -> pause (relaxed for the demo phase, 2026-09-06)
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
RSI_OVERSOLD = 30                       # 30/70 with pin-bar confirmation (2026-09-06 candlestick sweep)
RSI_OVERBOUGHT = 70
SL_ATR_MULTIPLIER = 1.5
TP_ATR_MULTIPLIER = 3.0
RATES_LOOKBACK = 120                    # bars fetched on the signal timeframe

# ── Candlestick patterns (candles.py) ─────────────────────────────────────
CANDLE_MODE = "confirm"                 # "off": BB+RSI only | "confirm": BB+RSI setup within CANDLE_LOOKBACK bars
                                        # AND a reversal pattern on the closed bar | "only": pattern + RSI pullback
CANDLE_LOOKBACK = 1                     # confirm mode: bars a BB+RSI setup stays valid (1 = the touch bar itself)
CANDLE_PATTERNS = ("hammer", "inverted_hammer", "shooting_star", "hanging_man")   # None = every pattern (names: candles.BULL/BEAR_PATTERNS)
CANDLE_ONLY_RSI = 50                    # only mode: buy patterns need rsi < this, sell patterns rsi > 100 - this

# ── News filter (news.py) ──────────────────────────────────────────────────
NEWS_FILTER_ENABLED = True              # no new entries around high-impact releases
NEWS_CURRENCIES = ("USD",)              # feed "country" codes to watch
NEWS_IMPACTS = ("High",)                # feed impact levels: High / Medium / Low / Holiday
NEWS_BLOCK_BEFORE_MIN = 15
NEWS_BLOCK_AFTER_MIN = 15
NEWS_REFRESH_MINUTES = 240              # feed re-fetch cadence (Forex Factory asks for low traffic)
NEWS_RETRY_MINUTES = 15                 # re-fetch cadence after a failed attempt (e.g. HTTP 429)
NEWS_CACHE_FILE = "news_cache.json"     # inside LOG_DIR: last good feed, reused across restarts
NEWS_STALE_HOURS = 72                   # cached calendar older than this counts as unavailable
NEWS_BLOCK_WHEN_UNAVAILABLE = False     # True: stand aside when the calendar cannot be fetched
NEWS_URLS = ("https://nfs.faireconomy.media/ff_calendar_thisweek.json",)   # FF week starts Sunday, so the
                                        # weekend copy already covers the coming week; nextweek.json is not always published

# ── Trend filter (higher timeframe) ────────────────────────────────────────
TREND_FILTER_ENABLED = True
TREND_TIMEFRAME = mt5.TIMEFRAME_H1
TREND_EMA_PERIOD = 200                  # buy only above EMA, sell only below

# ── Session filter (server time) ───────────────────────────────────────────
SESSION_FILTER_ENABLED = True
SESSION_START_HOUR = 0                  # inclusive (24h server day, weekdays only; sweep 2026-09-06)
SESSION_END_HOUR = 24                   # exclusive
TRADING_WEEKDAYS = (0, 1, 2, 3, 4)      # Mon..Fri

# ── Position management ────────────────────────────────────────────────────
MANAGE_POSITIONS = False                # trailing stop cut winners in the 2026-09-06 sweep; keep fixed SL/TP
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

# ── Trade history & analytics ───────────────────────────────────────────────
HISTORY_ENABLED = True
HISTORY_DB = "history.db"               # file name inside LOG_DIR
HISTORY_SYNC_SECONDS = 60               # deal sync + equity snapshot cadence
HISTORY_INCLUDE_ALL_DEALS = False       # True: every deal on the account, not only this bot's
HISTORY_MAX_TRADES = 500                # closed trades embedded in the page snapshot
CHART_BARS = 96                         # closed signal-timeframe candles per symbol on the page
CHART_REFRESH_SECONDS = 60              # how often the candle charts are refreshed

# ── Telegram ───────────────────────────────────────────────────────────────
# Set TELEGRAM_TOKEN / TELEGRAM_CHAT_ID in the environment or in a local .env file
# (see .env.example). Never put the literals here: config.py is committed.
# An empty token disables Telegram alerts.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def spread_limit(symbol: str) -> int:
    return MAX_ALLOWED_SPREAD_POINTS.get(symbol, MAX_ALLOWED_SPREAD_POINTS["default"])


# ── GitHub Pages snapshot (publisher.py) ───────────────────────────────────
# Every PAGES_PUBLISH_SECONDS the bot force-pushes web/index.html + status.json as a
# single commit to PAGES_BRANCH, so the dashboard is readable from anywhere.
PAGES_PUBLISH_ENABLED = True
PAGES_REMOTE = None                     # git remote URL for the gh-pages push; None -> this repo's origin
PAGES_BRANCH = "gh-pages"
PAGES_PUBLISH_SECONDS = 300             # minimum seconds between pushes
