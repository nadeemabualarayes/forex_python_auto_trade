"""Signal generation and per-symbol trading state."""
import time
from dataclasses import dataclass
from datetime import datetime

import numpy as np

import config
from execution import get_rates, spread_points, bot_positions, calculate_dynamic_lot, send_market_order
from journal import log, record_trade
import MetaTrader5 as mt5


# -- Pure logic (no MT5) -------------------------------------------------------
def in_session(server_dt: datetime) -> bool:
    if not config.SESSION_FILTER_ENABLED:
        return True
    if server_dt.weekday() not in config.TRADING_WEEKDAYS:
        return False
    return config.SESSION_START_HOUR <= server_dt.hour < config.SESSION_END_HOUR


def _pattern(bar, side: str) -> str:
    """Name of the allowed reversal pattern on this bar for `side`, or ""."""
    name = bar.get("bull_pattern" if side == "BUY" else "bear_pattern") or ""
    if config.CANDLE_PATTERNS is not None and name not in config.CANDLE_PATTERNS:
        return ""
    return name


def raw_signal(bar) -> str | None:
    """Entry rule on one closed bar, per config.CANDLE_MODE:
    off      Bollinger touch + RSI extreme on this bar
    confirm  a touch+RSI setup within the last CANDLE_LOOKBACK bars AND a reversal candlestick on this bar
    only     a reversal candlestick with RSI on the pullback side of CANDLE_ONLY_RSI (trend filter picks the side)
    """
    mode = config.CANDLE_MODE
    if mode == "confirm":
        if bar.get("buy_setup_recent") and _pattern(bar, "BUY"):
            return "BUY"
        if bar.get("sell_setup_recent") and _pattern(bar, "SELL"):
            return "SELL"
        return None
    if mode == "only":
        if bar["rsi"] < config.CANDLE_ONLY_RSI and _pattern(bar, "BUY"):
            return "BUY"
        if bar["rsi"] > 100 - config.CANDLE_ONLY_RSI and _pattern(bar, "SELL"):
            return "SELL"
        return None
    if bar["close"] <= bar["lower_band"] and bar["rsi"] < config.RSI_OVERSOLD:
        return "BUY"
    if bar["close"] >= bar["upper_band"] and bar["rsi"] > config.RSI_OVERBOUGHT:
        return "SELL"
    return None


def trend_allows(signal: str, close: float, trend_ema, enabled: bool | None = None) -> bool:
    """H1 EMA gate. `enabled` defaults to the scalper's config flag; other engines pass their own."""
    if not (config.TREND_FILTER_ENABLED if enabled is None else enabled):
        return True
    if trend_ema is None or (isinstance(trend_ema, float) and np.isnan(trend_ema)):
        return False                                    # no trend reading -> stand aside
    return close > trend_ema if signal == "BUY" else close < trend_ema


def generate_signal(bar) -> str | None:
    """raw_signal gated by trend. `bar` must carry trend_ema when the filter is on."""
    sig = raw_signal(bar)
    if sig is None:
        return None
    return sig if trend_allows(sig, bar["close"], bar.get("trend_ema")) else None


@dataclass
class Levels:
    side: str
    entry: float
    sl: float
    tp: float
    sl_dist: float


def build_levels(side: str, ask: float, bid: float, atr: float,
                 sl_mult: float | None = None, tp_mult: float | None = None) -> Levels:
    """ATR-based stop and target. Multipliers default to the scalper's config values at call time."""
    sl_dist = atr * (config.SL_ATR_MULTIPLIER if sl_mult is None else sl_mult)
    tp_dist = atr * (config.TP_ATR_MULTIPLIER if tp_mult is None else tp_mult)
    if side == "BUY":
        return Levels(side, ask, ask - sl_dist, ask + tp_dist, sl_dist)
    return Levels(side, bid, bid + sl_dist, bid - tp_dist, sl_dist)


# -- Per-symbol trader (MT5-facing) ---------------------------------------------
class SymbolTrader:
    def __init__(self, symbol: str, engine=None):
        if engine is None:
            from engines import scalper_engine          # lazy: engines imports this module
            engine = scalper_engine()
        self.symbol = symbol
        self.engine = engine
        self.last_signal_bar = None
        self.last_skip_reason = None
        self.last_df = None                 # latest indicator frame (for the dashboard candles)
        self.last_df_mono = 0.0

    def _skip(self, reason: str) -> None:
        # Log a reason only when it changes, so the log stays readable at 10 s polling.
        if reason != self.last_skip_reason:
            log.info("[%s] idle: %s", self.symbol, reason)
            self.last_skip_reason = reason

    def analyse(self):
        """Return (df_with_indicators, last_closed_bar) or (None, None)."""
        e = self.engine
        df = get_rates(self.symbol, e.timeframe, n=e.lookback)
        if df is None or len(df) < max(config.BB_PERIOD, config.ATR_PERIOD, config.RSI_PERIOD) + 5:
            return None, None
        htf = None
        if e.trend_filter:
            htf = get_rates(self.symbol, config.TREND_TIMEFRAME, n=config.TREND_EMA_PERIOD * 3)
            if htf is None or len(htf) < config.TREND_EMA_PERIOD:
                return None, None
        df = e.analyse(df, htf, mt5.symbol_info(self.symbol))
        self.last_df, self.last_df_mono = df, time.monotonic()
        return df, df.iloc[-2]                          # last *closed* candle

    def frame(self, max_age: float = 60.0):
        """Latest indicator frame, re-analysed when the cached one is older than max_age seconds."""
        if self.last_df is not None and time.monotonic() - self.last_df_mono < max_age:
            return self.last_df
        df, _ = self.analyse()
        return df

    def step(self, server_dt: datetime, entries_today: int, news_block: str | None = None) -> None:
        """One evaluation pass. Places at most one order, once per closed bar.
        `entries_today` is this engine's entry count; `news_block` the calendar blackout reason or None."""
        e = self.engine
        if bot_positions(self.symbol, magic=e.magic):
            self._skip("position open")
            return
        if not in_session(server_dt):
            self._skip("outside session")
            return
        if news_block:
            self._skip(news_block)
            return
        if entries_today >= e.max_trades_per_day:
            self._skip(f"daily trade cap {e.max_trades_per_day} reached")
            return

        spread = spread_points(self.symbol)
        if spread is None:
            self._skip("no live quote")
            return
        if spread > config.spread_limit(self.symbol):
            self._skip(f"spread {spread:.0f} > {config.spread_limit(self.symbol)}")
            return

        df, last = self.analyse()
        if last is None or np.isnan(last["atr"]):
            self._skip("insufficient data")
            return
        if self.last_signal_bar == last["time"]:
            return                                      # one attempt per candle
        self.last_skip_reason = None

        signal = e.signal(last)
        if not signal:
            return

        self.last_signal_bar = last["time"]
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return
        lv = e.levels(signal, tick.ask, tick.bid, last)
        if lv is None:
            log.info("[%s] SKIP %s on %s: no valid stop", self.symbol, signal, last["time"])
            record_trade("SKIP", self.symbol, signal, note="no valid stop")
            return
        lot = calculate_dynamic_lot(self.symbol, lv.sl_dist, e.risk_usd)
        if lot <= 0:
            log.info("[%s] SKIP %s on %s: no lot fits risk budget", self.symbol, signal, last["time"])
            record_trade("SKIP", self.symbol, signal, note="no lot fits risk budget")
            return
        log.info("[%s] %s SIGNAL %s bar=%s close=%.5g rsi=%.1f atr=%.5g ema=%.5g pattern=%s",
                 self.symbol, e.name, signal, last["time"], last["close"], last.get("rsi", float("nan")),
                 last["atr"], last.get("trend_ema", float("nan")), _pattern(last, signal) or "-")
        send_market_order(signal, self.symbol, lot, lv.entry, lv.sl, lv.tp, engine=e)
