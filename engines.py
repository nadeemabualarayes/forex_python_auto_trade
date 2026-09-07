"""Engine profiles: everything that differs between the trading engines, as plain data.

A profile bundles the magic number, symbols, timeframe, indicator/signal/level callables and the
risk knobs of one engine. `SymbolTrader`, the position manager, the backtester and the reporter
all read these fields instead of module-level config, so adding an engine is adding a profile.
"""
from dataclasses import dataclass
from typing import Callable

import config
from strategy import generate_signal, build_levels
from technicals import compute_indicators, compute_trend, attach_trend


@dataclass(frozen=True)
class Engine:
    name: str                    # "scalper" | "london": logs, journal notes, Telegram, dashboard tag
    magic: int
    comment: str                 # MT5 order comment prefix; the symbol is appended
    symbols: tuple
    timeframe: int               # mt5.TIMEFRAME_*
    lookback: int                # bars fetched on the signal timeframe
    trend_filter: bool           # fetch the H1 series and gate entries on EMA200
    analyse: Callable            # (df, htf_df | None, symbol_info | None) -> df with indicator columns
    signal: Callable             # (closed bar) -> "BUY" | "SELL" | None
    levels: Callable             # (side, ask, bid, closed bar) -> strategy.Levels | None
    risk_usd: float
    max_trades_per_day: int
    max_consecutive_losses: int
    manage: bool
    breakeven_atr: float
    trail_atr: float


# -- Scalper adapters ---------------------------------------------------------------
def scalper_analyse(df, htf=None, info=None):
    """Bollinger/RSI/ATR/candles on the signal frame, plus the H1 EMA when the series is given."""
    df = compute_indicators(df)
    if htf is not None:
        df = attach_trend(df, compute_trend(htf))
    return df


def scalper_levels(side: str, ask: float, bid: float, bar):
    return build_levels(side, ask, bid, float(bar["atr"]))


def scalper_engine() -> Engine:
    return Engine(
        name="scalper", magic=config.MAGIC_NUMBER, comment="AlgoBot",
        symbols=tuple(config.SYMBOLS), timeframe=config.TIMEFRAME, lookback=config.RATES_LOOKBACK,
        trend_filter=config.TREND_FILTER_ENABLED,
        analyse=scalper_analyse, signal=generate_signal, levels=scalper_levels,
        risk_usd=config.RISK_USD_PER_TRADE, max_trades_per_day=config.MAX_TRADES_PER_DAY,
        max_consecutive_losses=config.MAX_CONSECUTIVE_LOSSES,
        manage=config.MANAGE_POSITIONS, breakeven_atr=config.BREAKEVEN_ATR, trail_atr=config.TRAIL_ATR,
    )


def build_engines() -> list:
    """Enabled engines in priority order (scalper first)."""
    return [scalper_engine()]


def engine_names(engines) -> dict:
    return {e.magic: e.name for e in engines}
