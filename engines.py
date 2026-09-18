"""Engine profiles: everything that differs between the trading engines, as plain data.

A profile bundles the magic number, symbols, timeframe, indicator/signal/level callables and the
risk knobs of one engine. `SymbolTrader`, the position manager, the backtester and the reporter
all read these fields instead of module-level config, so adding an engine is adding a profile.
"""
from dataclasses import dataclass
from typing import Callable

import config
from execution import usd_per_price_unit
from strategy import generate_signal, build_levels, build_dollar_levels
from technicals import compute_indicators, compute_trend, attach_trend
from london import london_analyse, london_signal, london_levels


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
    max_open_positions: int = 1  # per symbol; above 1 a new signal may open while earlier trades still run


# -- Scalper adapters ---------------------------------------------------------------
def scalper_analyse(df, htf=None, info=None):
    """Bollinger/RSI/ATR/candles on the signal frame, plus the H1 EMA when the series is given."""
    df = compute_indicators(df)
    if htf is not None:
        df = attach_trend(df, compute_trend(htf))
    return df


def scalper_levels(side: str, ask: float, bid: float, bar):
    return build_levels(side, ask, bid, float(bar["atr"]))


# -- Fixed-dollar exits (config.EXIT_MODE == "usd") --------------------------------------
def dollar_analyse(df, htf=None, info=None):
    """scalper_analyse plus what the levels need to turn dollars into a price distance: the terminal's value
    of a 1.0 move on the minimum lot, the point, and the broker's minimum stop distance."""
    df = scalper_analyse(df, htf, info)
    value = usd_per_price_unit(info.name, info) if info is not None else None
    df["usd_per_unit"] = float("nan") if value is None else value
    df["point"] = info.point if info is not None else 0.0
    df["stops_dist"] = info.trade_stops_level * info.point if info is not None else 0.0
    return df


def dollar_levels(side: str, ask: float, bid: float, bar):
    return build_dollar_levels(side, ask, bid, config.EXIT_SL_USD, config.EXIT_TP_USD,
                               bar["usd_per_unit"], float(bar["point"]), float(bar["stops_dist"]))


def scalper_engine() -> Engine:
    if config.EXIT_MODE == "usd":
        # The dollar stop is priced for the minimum lot, so it is also the whole risk budget.
        analyse, levels, risk_usd = dollar_analyse, dollar_levels, config.EXIT_SL_USD
    else:
        analyse, levels, risk_usd = scalper_analyse, scalper_levels, config.RISK_USD_PER_TRADE
    return Engine(
        name="scalper", magic=config.MAGIC_NUMBER, comment="AlgoBot",
        symbols=tuple(config.SYMBOLS), timeframe=config.TIMEFRAME, lookback=config.RATES_LOOKBACK,
        trend_filter=config.TREND_FILTER_ENABLED,
        analyse=analyse, signal=generate_signal, levels=levels,
        risk_usd=risk_usd, max_trades_per_day=config.MAX_TRADES_PER_DAY,
        max_consecutive_losses=config.MAX_CONSECUTIVE_LOSSES,
        manage=config.MANAGE_POSITIONS, breakeven_atr=config.BREAKEVEN_ATR, trail_atr=config.TRAIL_ATR,
        max_open_positions=config.MAX_OPEN_POSITIONS,
    )


def london_engine() -> Engine:
    return Engine(
        name="london", magic=config.LDN_MAGIC_NUMBER, comment="LDN",
        symbols=tuple(config.LDN_SYMBOLS), timeframe=config.LDN_TIMEFRAME, lookback=config.LDN_RATES_LOOKBACK,
        trend_filter=config.LDN_TREND_FILTER,
        analyse=london_analyse, signal=london_signal, levels=london_levels,
        risk_usd=config.LDN_RISK_USD, max_trades_per_day=config.LDN_MAX_TRADES_PER_DAY,
        max_consecutive_losses=config.LDN_MAX_CONSECUTIVE_LOSSES,
        manage=config.LDN_MANAGE_POSITIONS, breakeven_atr=config.LDN_BREAKEVEN_ATR, trail_atr=config.LDN_TRAIL_ATR,
    )


def build_engines() -> list:
    """Enabled engines in priority order (scalper first)."""
    engines = [scalper_engine()]
    if getattr(config, "LDN_ENABLED", False):
        engines.append(london_engine())
    return engines


def engine_names(engines) -> dict:
    return {e.magic: e.name for e in engines}
