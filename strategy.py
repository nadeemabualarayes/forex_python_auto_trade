"""Signal generation and per-symbol trading state."""
from dataclasses import dataclass
from datetime import datetime

import numpy as np

import config
from technicals import compute_indicators, compute_trend, attach_trend
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


def raw_signal(bar) -> str | None:
    """Mean-reversion rule on one closed bar: BB touch + RSI extreme."""
    if bar["close"] <= bar["lower_band"] and bar["rsi"] < config.RSI_OVERSOLD:
        return "BUY"
    if bar["close"] >= bar["upper_band"] and bar["rsi"] > config.RSI_OVERBOUGHT:
        return "SELL"
    return None


def trend_allows(signal: str, close: float, trend_ema) -> bool:
    if not config.TREND_FILTER_ENABLED:
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


def build_levels(side: str, ask: float, bid: float, atr: float) -> Levels:
    sl_dist = atr * config.SL_ATR_MULTIPLIER
    tp_dist = atr * config.TP_ATR_MULTIPLIER
    if side == "BUY":
        return Levels(side, ask, ask - sl_dist, ask + tp_dist, sl_dist)
    return Levels(side, bid, bid + sl_dist, bid - tp_dist, sl_dist)


# -- Per-symbol trader (MT5-facing) ---------------------------------------------
class SymbolTrader:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.last_signal_bar = None
        self.last_skip_reason = None

    def _skip(self, reason: str) -> None:
        # Log a reason only when it changes, so the log stays readable at 10 s polling.
        if reason != self.last_skip_reason:
            log.info("[%s] idle: %s", self.symbol, reason)
            self.last_skip_reason = reason

    def analyse(self):
        """Return (df_with_indicators, last_closed_bar) or (None, None)."""
        df = get_rates(self.symbol, config.TIMEFRAME, n=config.RATES_LOOKBACK)
        if df is None or len(df) < max(config.BB_PERIOD, config.ATR_PERIOD, config.RSI_PERIOD) + 5:
            return None, None
        df = compute_indicators(df)
        if config.TREND_FILTER_ENABLED:
            htf = get_rates(self.symbol, config.TREND_TIMEFRAME, n=config.TREND_EMA_PERIOD * 3)
            if htf is None or len(htf) < config.TREND_EMA_PERIOD:
                return None, None
            df = attach_trend(df, compute_trend(htf))
        return df, df.iloc[-2]                          # last *closed* candle

    def step(self, server_dt: datetime, entries_today: int) -> None:
        """One evaluation pass. Places at most one order, once per closed bar."""
        if bot_positions(self.symbol):
            self._skip("position open")
            return
        if not in_session(server_dt):
            self._skip("outside session")
            return
        if entries_today >= config.MAX_TRADES_PER_DAY:
            self._skip(f"daily trade cap {config.MAX_TRADES_PER_DAY} reached")
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

        signal = generate_signal(last)
        if not signal:
            return

        self.last_signal_bar = last["time"]
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return
        lv = build_levels(signal, tick.ask, tick.bid, float(last["atr"]))
        lot = calculate_dynamic_lot(self.symbol, lv.sl_dist, config.RISK_USD_PER_TRADE)
        if lot <= 0:
            log.info("[%s] SKIP %s on %s: no lot fits risk budget", self.symbol, signal, last["time"])
            record_trade("SKIP", self.symbol, signal, note="no lot fits risk budget")
            return
        log.info("[%s] SIGNAL %s bar=%s close=%.5g rsi=%.1f atr=%.5g ema=%.5g",
                 self.symbol, signal, last["time"], last["close"], last["rsi"], last["atr"],
                 last.get("trend_ema", float("nan")))
        send_market_order(signal, self.symbol, lot, lv.entry, lv.sl, lv.tp)
