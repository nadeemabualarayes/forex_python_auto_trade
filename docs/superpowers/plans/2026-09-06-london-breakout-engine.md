# London Breakout Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a second, independent London-open range-breakout engine on EURUSD and GBPUSD under magic 998888 next to the existing pin-bar scalper (which stays on XAUUSD/XAGUSD), sharing one bot loop, one account-wide daily-loss breaker, and per-engine entry caps and loss-streak limits.

**Architecture:** One `SymbolTrader` parameterised by an immutable `Engine` profile (`engines.py`). Phase 1 turns the scalper into profile #1 built from today's config and makes every magic-keyed helper (positions, orders, stats, history, trailing, status, reporting, backtest) engine-aware with zero behaviour change. Phase 2 adds the pure London rule (`london.py`), its `LDN_*` config, the second profile, the backtest `--engine` switch, dashboard/Telegram tags, and simulator coverage.

**Tech Stack:** Python 3.11+, MetaTrader5 package, pandas/numpy, pytest, sqlite3, vanilla JS dashboard (Chart.js). Tests run without a terminal via `tests/conftest.py`.

**Spec:** `docs/superpowers/specs/2026-09-06-london-breakout-engine-design.md`

## Global Constraints

- All clocks are MT5 server time (naive datetime). Server clock is UTC+3 in summer; London open = 10:00 server.
- Every MT5 call that can return `None` is guarded; symbols without a live tick are skipped.
- Pure logic lives in plain functions testable without a terminal; MT5 access stays in `execution.py`, `risk.py`, `position_manager.py`, `history.py`, `main.py`.
- Phase 1 ships with zero behaviour change for the scalper: same journal rows, same orders, same Telegram wording apart from additions listed in tasks.
- Scalper parameters in `config.py` are never changed by this work.
- Magic numbers: scalper `998877` (existing), London `998888`.
- London defaults (verbatim from the spec): `LDN_BOX_START_HOUR = 0`, `LDN_BOX_END_HOUR = 10`, `LDN_WINDOW_END_HOUR = 14`, `LDN_BUFFER_PIPS = 0.0`, `LDN_MAX_BOX_ATR = 0.0`, `LDN_TREND_FILTER = True`, `LDN_SL_MODE = "atr"`, `LDN_SL_ATR = 1.5`, `LDN_TP_R = 2.0`, `LDN_RISK_USD = 5.0`, `LDN_MAX_TRADES_PER_DAY = 2`, `LDN_MAX_CONSECUTIVE_LOSSES = 4`, `LDN_MANAGE_POSITIONS = False`, `LDN_BREAKEVEN_ATR = 1.0`, `LDN_TRAIL_ATR = 2.0`, `LDN_SYMBOLS = ["EURUSD", "GBPUSD"]`, `LDN_TIMEFRAME = mt5.TIMEFRAME_M5`, `LDN_RATES_LOOKBACK = 300`.
- Run the whole suite (`python -m pytest tests -q`) before every commit; 114 tests pass at the start of this plan and none of their assertions may change.
- Windows: use the Write/Edit tools (not Bash heredocs) for file content that contains backslashes; commit the instructions file as `claude.md` (lowercase).
- Commit messages follow the repo style (`feat(scope): ...`, `refactor(scope): ...`, `docs: ...`) and end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility after this plan |
|---|---|
| `engines.py` (new) | `Engine` frozen dataclass; `scalper_engine()`, `london_engine()`, `build_engines()`, `engine_names()`; the scalper's `analyse`/`levels` adapters. Pure. |
| `london.py` (new) | Pure London rule: `pip_size`, `add_box_columns`, `london_signal`, `london_levels`, `london_analyse`. No MT5. |
| `config.py` | Existing knobs untouched; new `LDN_*` block; spread caps for EURUSD/GBPUSD. |
| `strategy.py` | `build_levels` gains explicit multipliers; `trend_allows` gains `enabled`; `SymbolTrader(symbol, engine)` reads timeframe/lookback/analyse/signal/levels/risk/cap/magic from the engine. |
| `execution.py` | `KNOWN_MAGICS` registry; `bot_positions(symbol, magic)`; `send_market_order(..., engine)`; `modify_sl(position, sl, magic)`. |
| `risk.py` | `combine`, `account_breaker`, `engine_breaker`; `breaker_reason` kept for compatibility. |
| `position_manager.py` | `manage_positions(engine)`. |
| `history.py` | `sync_deals(store, magics, include_all)` accepts an int or an iterable. |
| `analytics.py` | `Trade.magic`; `trade_dicts(trades, limit, engine_names)` adds `engine`. |
| `status.py` | `engine_block`; `build_status(..., engines)`; engine tags on positions and traders. |
| `reporting.py` | `Reporter(engine_names)`; engine line on open/close; per-engine heartbeat and summary; pure `daily_summary_text`. |
| `main.py` | `Bot(symbols, web, pages, engines)`: per-engine stats, account breaker, engine pause, per-trader error isolation; `run()` starts every engine. |
| `backtest.py` | `run_backtest(..., signal, levels, max_trades_per_day, max_consecutive_losses, manage, be_atr, trail_atr)`; `load_history(symbol, days, engine)`; `--engine`; `format_report(days, per_symbol, engine_name)`. |
| `simulate.py` | Random mode runs both engines on the scripted symbol; result carries `engines`. |
| `web/index.html` | Engine column in positions/history, engine filter, per-engine day strip. |
| `claude.md` | Architecture diagram and commands mention both engines. |

---

## Phase 1: engine profiles (zero behaviour change)

### Task 1: `Engine` profile and the scalper profile

**Files:**
- Create: `engines.py`
- Modify: `strategy.py:83-88` (`build_levels`)
- Test: `tests/test_engines.py` (new), `tests/test_strategy.py`

**Interfaces:**
- Consumes: `technicals.compute_indicators/compute_trend/attach_trend`, `strategy.generate_signal`, `strategy.build_levels`.
- Produces:
  - `strategy.build_levels(side, ask, bid, atr, sl_mult=None, tp_mult=None) -> Levels` (None = read `config.SL_ATR_MULTIPLIER` / `config.TP_ATR_MULTIPLIER` at call time).
  - `engines.Engine` frozen dataclass with fields `name, magic, comment, symbols, timeframe, lookback, trend_filter, analyse, signal, levels, risk_usd, max_trades_per_day, max_consecutive_losses, manage, breakeven_atr, trail_atr`.
  - `engines.scalper_analyse(df, htf=None, info=None) -> DataFrame`, `engines.scalper_levels(side, ask, bid, bar) -> Levels`.
  - `engines.scalper_engine() -> Engine`, `engines.build_engines() -> list[Engine]` (scalper only until Task 13), `engines.engine_names(engines) -> dict[int, str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_strategy.py`:

```python
class TestLevelMultipliers:
    def test_explicit_multipliers_override_config(self):
        lv = build_levels("BUY", ask=100.0, bid=99.9, atr=2.0, sl_mult=2.0, tp_mult=4.0)
        assert lv.sl == pytest.approx(96.0) and lv.tp == pytest.approx(108.0) and lv.sl_dist == pytest.approx(4.0)

    def test_default_multipliers_read_config_at_call_time(self, monkeypatch):
        monkeypatch.setattr(config, "SL_ATR_MULTIPLIER", 1.0)
        monkeypatch.setattr(config, "TP_ATR_MULTIPLIER", 5.0)
        lv = build_levels("SELL", ask=100.0, bid=99.9, atr=2.0)
        assert lv.sl == pytest.approx(101.9) and lv.tp == pytest.approx(89.9)
```

Create `tests/test_engines.py`:

```python
"""Engine profiles are plain data built from config; the scalper profile mirrors today's settings."""
import pandas as pd
import pytest

import config
from engines import Engine, scalper_engine, build_engines, engine_names, scalper_analyse, scalper_levels
from strategy import generate_signal


def test_scalper_profile_mirrors_config(monkeypatch):
    monkeypatch.setattr(config, "RISK_USD_PER_TRADE", 7.5)
    monkeypatch.setattr(config, "MAX_TRADES_PER_DAY", 3)
    e = scalper_engine()
    assert isinstance(e, Engine)
    assert e.name == "scalper" and e.magic == config.MAGIC_NUMBER and e.comment == "AlgoBot"
    assert e.symbols == tuple(config.SYMBOLS)
    assert e.timeframe == config.TIMEFRAME and e.lookback == config.RATES_LOOKBACK
    assert e.trend_filter == config.TREND_FILTER_ENABLED
    assert e.risk_usd == 7.5 and e.max_trades_per_day == 3
    assert e.max_consecutive_losses == config.MAX_CONSECUTIVE_LOSSES
    assert e.manage == config.MANAGE_POSITIONS
    assert (e.breakeven_atr, e.trail_atr) == (config.BREAKEVEN_ATR, config.TRAIL_ATR)
    assert e.signal is generate_signal and e.analyse is scalper_analyse and e.levels is scalper_levels


def test_profiles_are_immutable():
    e = scalper_engine()
    with pytest.raises(Exception):
        e.magic = 1


def test_build_engines_is_scalper_only_by_default(monkeypatch):
    monkeypatch.setattr(config, "LDN_ENABLED", False, raising=False)
    names = [e.name for e in build_engines()]
    assert names == ["scalper"]
    assert engine_names(build_engines()) == {config.MAGIC_NUMBER: "scalper"}


def test_scalper_analyse_attaches_trend_only_with_htf():
    df = pd.DataFrame({"time": pd.date_range("2026-09-07 08:00", periods=60, freq="5min"),
                       "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    out = scalper_analyse(df.copy())
    assert "atr" in out and "rsi" in out and "trend_ema" not in out
    htf = pd.DataFrame({"time": pd.date_range("2026-09-01", periods=300, freq="1h"), "close": 100.0})
    out = scalper_analyse(df.copy(), htf)
    assert "trend_ema" in out


def test_scalper_levels_use_bar_atr_and_config_multipliers():
    lv = scalper_levels("BUY", 100.0, 99.9, {"atr": 2.0})
    assert lv.entry == 100.0
    assert lv.sl == pytest.approx(100.0 - 2.0 * config.SL_ATR_MULTIPLIER)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_engines.py tests/test_strategy.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'engines'` and `TypeError: build_levels() got an unexpected keyword argument 'sl_mult'`.

- [ ] **Step 3: Extend `build_levels` in `strategy.py`**

Replace `strategy.py:83-88` with:

```python
def build_levels(side: str, ask: float, bid: float, atr: float,
                 sl_mult: float | None = None, tp_mult: float | None = None) -> Levels:
    """ATR-based stop and target. Multipliers default to the scalper's config values at call time."""
    sl_dist = atr * (config.SL_ATR_MULTIPLIER if sl_mult is None else sl_mult)
    tp_dist = atr * (config.TP_ATR_MULTIPLIER if tp_mult is None else tp_mult)
    if side == "BUY":
        return Levels(side, ask, ask - sl_dist, ask + tp_dist, sl_dist)
    return Levels(side, bid, bid + sl_dist, bid - tp_dist, sl_dist)
```

- [ ] **Step 4: Create `engines.py`**

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_engines.py tests/test_strategy.py -q`
Expected: all PASS.

- [ ] **Step 6: Run the whole suite and commit**

Run: `python -m pytest tests -q` (expected: 121 passed)

```bash
git add engines.py strategy.py tests/test_engines.py tests/test_strategy.py
git commit -m "feat(engines): add Engine profile with the scalper as profile one

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Magic-aware positions, orders and stop modification

**Files:**
- Modify: `execution.py:78-81` (`bot_positions`), `execution.py:128-181` (`send_market_order`), `execution.py:183-200` (`modify_sl`)
- Test: `tests/test_execution.py`

**Interfaces:**
- Produces:
  - `execution.KNOWN_MAGICS: set[int]` (initially `{config.MAGIC_NUMBER}`), `execution.set_known_magics(magics)`.
  - `execution.bot_positions(symbol=None, magic=None) -> list`: `magic` is an int, an iterable of ints, or None meaning every magic in `KNOWN_MAGICS`.
  - `execution.send_market_order(action_type, symbol, lot, price, sl, tp, engine=None) -> bool`: with `engine` the request carries `engine.magic` and `f"{engine.comment}-{symbol}"`, the Telegram message shows `engine.risk_usd` and, when `engine.name != "scalper"`, an `Engine:` line; the journal note for non-scalper engines is prefixed `[name] `. With `engine=None` behaviour is exactly today's.
  - `execution.modify_sl(position, new_sl, magic=None) -> bool` (None = `config.MAGIC_NUMBER`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_execution.py`:

```python
from types import SimpleNamespace  # noqa: E402

import MetaTrader5 as mt5  # noqa: E402

import config  # noqa: E402
import execution  # noqa: E402
from engines import Engine, scalper_analyse, scalper_levels  # noqa: E402
from strategy import generate_signal  # noqa: E402


def _engine(name="london", magic=998888, comment="LDN", risk=4.0):
    return Engine(name=name, magic=magic, comment=comment, symbols=("EURUSD",), timeframe=5, lookback=300,
                  trend_filter=True, analyse=scalper_analyse, signal=generate_signal, levels=scalper_levels,
                  risk_usd=risk, max_trades_per_day=2, max_consecutive_losses=4,
                  manage=False, breakeven_atr=1.0, trail_atr=2.0)


def _pos(magic, symbol="XAUUSD"):
    return SimpleNamespace(magic=magic, symbol=symbol, ticket=magic)


class TestBotPositions:
    def test_default_filters_on_every_known_magic(self, monkeypatch):
        monkeypatch.setattr(execution, "KNOWN_MAGICS", {config.MAGIC_NUMBER, 998888})
        monkeypatch.setattr(execution.mt5, "positions_get",
                            lambda symbol=None: (_pos(config.MAGIC_NUMBER), _pos(998888), _pos(1)))
        assert [p.magic for p in execution.bot_positions()] == [config.MAGIC_NUMBER, 998888]

    def test_single_magic_and_iterable(self, monkeypatch):
        monkeypatch.setattr(execution.mt5, "positions_get",
                            lambda symbol=None: (_pos(config.MAGIC_NUMBER), _pos(998888), _pos(1)))
        assert [p.magic for p in execution.bot_positions(magic=998888)] == [998888]
        assert [p.magic for p in execution.bot_positions(magic=[1, 998888])] == [998888, 1]

    def test_none_result_is_empty(self, monkeypatch):
        monkeypatch.setattr(execution.mt5, "positions_get", lambda symbol=None: None)
        assert execution.bot_positions() == []

    def test_set_known_magics(self, monkeypatch):
        monkeypatch.setattr(execution, "KNOWN_MAGICS", {config.MAGIC_NUMBER})
        execution.set_known_magics([998888, config.MAGIC_NUMBER])
        assert execution.KNOWN_MAGICS == {config.MAGIC_NUMBER, 998888}


class TestOrderRequest:
    @pytest.fixture
    def capture(self, monkeypatch):
        sent, msgs, journal = [], [], []
        info = SimpleNamespace(digits=5, filling_mode=1)
        monkeypatch.setattr(execution.mt5, "symbol_info", lambda s: info)
        monkeypatch.setattr(execution.mt5, "order_send",
                            lambda req: sent.append(req) or SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, order=42))
        monkeypatch.setattr(execution, "send_telegram", msgs.append)
        monkeypatch.setattr(execution, "record_trade", lambda *a, **k: journal.append((a, k)))
        return sent, msgs, journal

    def test_engine_stamps_magic_comment_and_risk(self, capture):
        sent, msgs, journal = capture
        assert execution.send_market_order("BUY", "EURUSD", 0.02, 1.1, 1.09, 1.12, engine=_engine())
        assert sent[0]["magic"] == 998888 and sent[0]["comment"] == "LDN-EURUSD"
        assert "Engine:</b> london" in msgs[0] and "$4.00" in msgs[0]
        assert journal[0][1].get("note", "").startswith("[london]")

    def test_without_engine_behaviour_is_unchanged(self, capture):
        sent, msgs, journal = capture
        assert execution.send_market_order("SELL", "XAUUSD", 0.05, 2400.0, 2405.0, 2390.0)
        assert sent[0]["magic"] == config.MAGIC_NUMBER and sent[0]["comment"] == "AlgoBot-XAUUSD"
        assert "Engine:" not in msgs[0] and f"${config.RISK_USD_PER_TRADE:.2f}" in msgs[0]
        assert journal[0][1].get("note", "") == ""

    def test_modify_sl_uses_given_magic(self, monkeypatch):
        sent = []
        monkeypatch.setattr(execution.mt5, "symbol_info", lambda s: SimpleNamespace(digits=2))
        monkeypatch.setattr(execution.mt5, "order_send",
                            lambda req: sent.append(req) or SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE))
        pos = SimpleNamespace(ticket=7, symbol="XAUUSD", tp=2410.0)
        assert execution.modify_sl(pos, 2401.0, magic=998888)
        assert sent[0]["magic"] == 998888
        assert execution.modify_sl(pos, 2401.0)
        assert sent[1]["magic"] == config.MAGIC_NUMBER
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_execution.py -q`
Expected: FAIL (`AttributeError: module 'execution' has no attribute 'KNOWN_MAGICS'`, `TypeError ... unexpected keyword argument 'engine'`).

- [ ] **Step 3: Implement in `execution.py`**

Replace `execution.py:78-81` with:

```python
KNOWN_MAGICS: set = {config.MAGIC_NUMBER}      # every engine's magic; Bot registers them at start-up


def set_known_magics(magics) -> None:
    KNOWN_MAGICS.clear()
    KNOWN_MAGICS.update(int(m) for m in magics)


def bot_positions(symbol=None, magic=None) -> list:
    """Open positions of the bot's engines. magic: int, iterable of ints, or None = every known magic."""
    if magic is None:
        wanted = set(KNOWN_MAGICS)
    elif isinstance(magic, int):
        wanted = {magic}
    else:
        wanted = set(magic)
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return [p for p in (positions or ()) if p.magic in wanted]
```

In `send_market_order`, change the signature to
`def send_market_order(action_type: str, symbol: str, lot: float, price: float, sl: float, tp: float, engine=None) -> bool:`
and, right after the `digits = info.digits` line, add:

```python
    magic = engine.magic if engine is not None else config.MAGIC_NUMBER
    comment_prefix = engine.comment if engine is not None else "AlgoBot"
    risk_usd = engine.risk_usd if engine is not None else config.RISK_USD_PER_TRADE
    tag = f"[{engine.name}] " if engine is not None and engine.name != "scalper" else ""
    engine_line = f"▪ <b>Engine:</b> {engine.name}\n" if tag else ""
```

Then in the request dict use `"magic": magic` and `"comment": f"{comment_prefix}-{symbol}"`. In the three `record_trade(...)` calls prefix the note: `note=f"{tag}order_send None {err}"`, `note=tag` on the ENTRY row (pass `note=tag` there; it is empty for the scalper), and `note=f"{tag}{res.retcode} {res.comment}"`. In the "Trade Opened" Telegram message insert `{engine_line}` before the `▪ <b>Asset:</b>` line and replace `config.RISK_USD_PER_TRADE` with `risk_usd`.

In `modify_sl`, change the signature to `def modify_sl(position, new_sl: float, magic=None) -> bool:` and the request's magic to `"magic": config.MAGIC_NUMBER if magic is None else magic`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_execution.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite and commit**

Run: `python -m pytest tests -q`

```bash
git add execution.py tests/test_execution.py
git commit -m "refactor(execution): make positions, orders and SL modify engine-aware

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Combined stats, account breaker, engine breaker

**Files:**
- Modify: `risk.py:112-117`
- Test: `tests/test_risk.py`

**Interfaces:**
- Produces:
  - `risk.combine(stats_iterable) -> DailyStats`: sums `net_pnl`, `entries`, `wins`, `losses`; `closed` merged and sorted by `(time, ticket)`; `consecutive_losses` = 0.
  - `risk.account_breaker(stats) -> str | None`: daily-loss test only.
  - `risk.engine_breaker(engine, stats) -> str | None`: `stats.consecutive_losses >= engine.max_consecutive_losses`.
  - `risk.breaker_reason(stats)` unchanged in behaviour (kept for existing callers/tests).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_risk.py`:

```python
from types import SimpleNamespace as _NS  # noqa: E402

from risk import combine, account_breaker, engine_breaker  # noqa: E402


def test_combine_sums_and_merges_closed_deals_in_time_order():
    a = DailyStats(net_pnl=5.0, consecutive_losses=2, entries=2, wins=1, losses=1,
                   closed=[deal(30, mt5.DEAL_ENTRY_OUT, -1.0, ticket=3)])
    b = DailyStats(net_pnl=-2.0, consecutive_losses=0, entries=1, wins=0, losses=1,
                   closed=[deal(10, mt5.DEAL_ENTRY_OUT, -2.0, ticket=1), deal(40, mt5.DEAL_ENTRY_OUT, 4.0, ticket=4)])
    c = combine([a, b])
    assert c.net_pnl == pytest.approx(3.0) and c.entries == 3 and c.wins == 1 and c.losses == 2
    assert [d.ticket for d in c.closed] == [1, 3, 4]
    assert c.consecutive_losses == 0
    assert combine([]) == DailyStats()


def test_account_breaker_only_looks_at_daily_loss(monkeypatch):
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_USD", 30.0)
    assert account_breaker(DailyStats(net_pnl=-30.0)) == "daily loss $30.00 >= limit $30.00"
    assert account_breaker(DailyStats(net_pnl=-29.99, consecutive_losses=99)) is None


def test_engine_breaker_uses_the_engine_limit():
    engine = _NS(name="london", max_consecutive_losses=4)
    assert engine_breaker(engine, DailyStats(consecutive_losses=4)) == "4 consecutive losses"
    assert engine_breaker(engine, DailyStats(consecutive_losses=3, net_pnl=-1000)) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_risk.py -q`
Expected: FAIL with `ImportError: cannot import name 'combine'`.

- [ ] **Step 3: Implement in `risk.py`**

Replace `risk.py:112-117` with:

```python
def combine(stats_list) -> DailyStats:
    """Account view across engines: sums, plus every closed deal in time order."""
    out = DailyStats()
    for s in stats_list:
        out.net_pnl += s.net_pnl
        out.entries += s.entries
        out.wins += s.wins
        out.losses += s.losses
        out.closed.extend(s.closed)
    out.closed.sort(key=lambda d: (d.time, d.ticket))
    return out


def account_breaker(stats: DailyStats):
    """Account-wide pause: the combined daily loss limit."""
    if stats.net_pnl <= -config.MAX_DAILY_LOSS_USD:
        return f"daily loss ${abs(stats.net_pnl):.2f} >= limit ${config.MAX_DAILY_LOSS_USD:.2f}"
    return None


def engine_breaker(engine, stats: DailyStats):
    """Per-engine pause: that engine's own loss streak against its own limit."""
    if stats.consecutive_losses >= engine.max_consecutive_losses:
        return f"{stats.consecutive_losses} consecutive losses"
    return None


def breaker_reason(stats: DailyStats):
    """Single-engine rule kept for the backtester and older callers."""
    reason = account_breaker(stats)
    if reason:
        return reason
    if stats.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
        return f"{stats.consecutive_losses} consecutive losses"
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_risk.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add risk.py tests/test_risk.py
git commit -m "feat(risk): combined account stats with separate account and engine breakers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `SymbolTrader` driven by an engine profile

**Files:**
- Modify: `strategy.py:58-64` (`trend_allows`), `strategy.py:92-176` (`SymbolTrader`)
- Test: `tests/test_strategy.py`

**Interfaces:**
- Consumes: `engines.Engine`, `execution.bot_positions(symbol, magic)`, `execution.send_market_order(..., engine)`.
- Produces:
  - `strategy.trend_allows(signal, close, trend_ema, enabled=None) -> bool` (None = `config.TREND_FILTER_ENABLED`).
  - `SymbolTrader(symbol, engine=None)`; attribute `engine`; `analyse()` returns `(df, last_closed_bar)` using `engine.analyse(df, htf, info)`; `step(server_dt, entries_today, news_block=None)` unchanged signature, cap = `engine.max_trades_per_day`, positions filtered by `engine.magic`, levels via `engine.levels` (None -> SKIP row `no valid stop`), lot via `engine.risk_usd`, order via `send_market_order(..., engine=self.engine)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_strategy.py`:

```python
from types import SimpleNamespace  # noqa: E402

import pandas as pd  # noqa: E402

import strategy  # noqa: E402
from engines import Engine, scalper_engine, scalper_analyse  # noqa: E402


def test_trend_allows_explicit_enabled_flag(monkeypatch):
    monkeypatch.setattr(config, "TREND_FILTER_ENABLED", False)
    assert not trend_allows("BUY", 100, 110, enabled=True)
    assert trend_allows("BUY", 100, 110, enabled=False)
    assert trend_allows("BUY", 100, 110)                      # config says disabled


def _frame(n=60, close=100.0):
    return pd.DataFrame({"time": pd.date_range("2026-09-07 08:00", periods=n, freq="5min"),
                         "open": close, "high": close + 1, "low": close - 1, "close": close,
                         "tick_volume": 1, "spread": 3, "real_volume": 0})


def _engine(**over):
    base = dict(name="test", magic=4242, comment="T", symbols=("XAUUSD",), timeframe=5, lookback=60,
                trend_filter=False, analyse=scalper_analyse, signal=lambda bar: "BUY",
                levels=lambda side, ask, bid, bar: strategy.Levels(side, ask, ask - 1.0, ask + 2.0, 1.0),
                risk_usd=5.0, max_trades_per_day=2, max_consecutive_losses=4,
                manage=False, breakeven_atr=1.0, trail_atr=1.0)
    base.update(over)
    return Engine(**base)


@pytest.fixture
def wired(monkeypatch):
    """Stub every MT5-facing helper the trader touches; record what it asks for."""
    calls = {"positions": [], "orders": [], "skips": []}
    monkeypatch.setattr(strategy, "bot_positions", lambda symbol=None, magic=None: calls["positions"].append(magic) or [])
    monkeypatch.setattr(strategy, "spread_points", lambda symbol: 5.0)
    monkeypatch.setattr(strategy, "get_rates", lambda symbol, tf, n=120: _frame(n))
    monkeypatch.setattr(strategy, "calculate_dynamic_lot", lambda symbol, dist, risk: 0.1 if risk > 0 else 0.0)
    monkeypatch.setattr(strategy, "send_market_order",
                        lambda side, symbol, lot, price, sl, tp, engine=None: calls["orders"].append((side, engine.name, engine.magic)) or True)
    monkeypatch.setattr(strategy, "record_trade", lambda *a, **k: calls["skips"].append(k.get("note", "")))
    monkeypatch.setattr(strategy.mt5, "symbol_info_tick", lambda s: SimpleNamespace(ask=100.05, bid=100.0))
    monkeypatch.setattr(strategy.mt5, "symbol_info", lambda s: SimpleNamespace(point=0.01, digits=2))
    monkeypatch.setattr(config, "SESSION_FILTER_ENABLED", False)
    return calls


def test_trader_defaults_to_the_scalper_profile():
    t = strategy.SymbolTrader("XAUUSD")
    assert t.engine.name == "scalper" and t.engine.magic == config.MAGIC_NUMBER


def test_trader_uses_engine_magic_cap_and_order_tag(wired):
    t = strategy.SymbolTrader("XAUUSD", _engine())
    t.step(datetime(2026, 9, 7, 12, 0), entries_today=0)
    assert wired["positions"] == [4242]
    assert wired["orders"] == [("BUY", "test", 4242)]
    t.step(datetime(2026, 9, 7, 12, 0), entries_today=2)       # engine cap reached
    assert len(wired["orders"]) == 1 and t.last_skip_reason == "daily trade cap 2 reached"


def test_trader_skips_when_levels_are_invalid(wired):
    t = strategy.SymbolTrader("XAUUSD", _engine(levels=lambda side, ask, bid, bar: None))
    t.step(datetime(2026, 9, 7, 12, 0), entries_today=0)
    assert wired["orders"] == [] and wired["skips"] == ["no valid stop"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_strategy.py -q`
Expected: FAIL (`TypeError: trend_allows() got an unexpected keyword argument 'enabled'`, `TypeError: SymbolTrader.__init__() takes 2 positional arguments`).

- [ ] **Step 3: Implement**

Replace `strategy.py:58-64` with:

```python
def trend_allows(signal: str, close: float, trend_ema, enabled: bool | None = None) -> bool:
    """H1 EMA gate. `enabled` defaults to the scalper's config flag; other engines pass their own."""
    if not (config.TREND_FILTER_ENABLED if enabled is None else enabled):
        return True
    if trend_ema is None or (isinstance(trend_ema, float) and np.isnan(trend_ema)):
        return False                                    # no trend reading -> stand aside
    return close > trend_ema if signal == "BUY" else close < trend_ema
```

Replace the `SymbolTrader` class (`strategy.py:92-176`) with:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_strategy.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite (the simulator still drives the scalper end to end) and commit**

Run: `python -m pytest tests -q`
Expected: all pass, including `tests/test_simulate.py`.

```bash
git add strategy.py tests/test_strategy.py
git commit -m "refactor(strategy): SymbolTrader reads timeframe, signal, levels and risk from its engine

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Per-engine trailing-stop manager

**Files:**
- Modify: `position_manager.py:32-66`
- Test: `tests/test_position_manager.py`

**Interfaces:**
- Produces: `position_manager.manage_positions(engine=None) -> None`: returns immediately unless `engine.manage`; ATR from `engine.timeframe`; BE/trail from `engine.breakeven_atr`/`engine.trail_atr`; positions via `bot_positions(magic=engine.magic)`; `modify_sl(p, new_sl, magic=engine.magic)`. `engine=None` builds the scalper profile.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_position_manager.py`:

```python
from types import SimpleNamespace  # noqa: E402

import pandas as pd  # noqa: E402

import config  # noqa: E402
import position_manager  # noqa: E402
from engines import scalper_engine  # noqa: E402
from dataclasses import replace  # noqa: E402


def test_manage_is_a_no_op_when_the_engine_does_not_manage(monkeypatch):
    monkeypatch.setattr(position_manager, "bot_positions", lambda *a, **k: (_ for _ in ()).throw(AssertionError("touched MT5")))
    position_manager.manage_positions(replace(scalper_engine(), manage=False))


def test_manage_uses_engine_timeframe_and_magic(monkeypatch):
    engine = replace(scalper_engine(), name="t", magic=4242, timeframe=15, manage=True, breakeven_atr=1.0, trail_atr=1.0)
    asked, modified = [], []
    pos = SimpleNamespace(symbol="XAUUSD", ticket=9, type=0, price_open=100.0, sl=97.0, tp=110.0, volume=0.1)
    monkeypatch.setattr(position_manager, "bot_positions", lambda symbol=None, magic=None: asked.append(magic) or [pos])
    monkeypatch.setattr(position_manager.mt5, "symbol_info", lambda s: SimpleNamespace(point=0.01, digits=2, trade_stops_level=0))
    monkeypatch.setattr(position_manager.mt5, "symbol_info_tick", lambda s: SimpleNamespace(time=1, bid=105.0, ask=105.1))
    frame = pd.DataFrame({"time": pd.date_range("2026-09-07", periods=50, freq="15min"),
                          "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0})
    monkeypatch.setattr(position_manager, "get_rates", lambda symbol, tf, n=0: asked.append(tf) or frame)
    monkeypatch.setattr(position_manager, "modify_sl", lambda p, sl, magic=None: modified.append((round(sl, 2), magic)) or True)
    monkeypatch.setattr(position_manager, "record_trade", lambda *a, **k: None)
    position_manager.manage_positions(engine)
    assert asked == [4242, 15]
    assert modified == [(103.0, 4242)]                  # ATR 2 -> trail 1 ATR behind 105
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_position_manager.py -q`
Expected: FAIL with `TypeError: manage_positions() takes 0 positional arguments but 1 was given`.

- [ ] **Step 3: Implement**

Replace `position_manager.py:32-66` with:

```python
def manage_positions(engine=None) -> None:
    """Breakeven then trail for one engine's open positions, using that engine's timeframe and multiples."""
    if engine is None:
        from engines import scalper_engine              # lazy: engines imports strategy
        engine = scalper_engine()
    if not engine.manage:
        return
    for p in bot_positions(magic=engine.magic):
        info = mt5.symbol_info(p.symbol)
        tick = mt5.symbol_info_tick(p.symbol)
        if info is None or tick is None or tick.time == 0:
            continue
        df = get_rates(p.symbol, engine.timeframe, n=config.ATR_PERIOD * 3)
        if df is None or len(df) < config.ATR_PERIOD + 2:
            continue
        atr = float(compute_indicators(df).iloc[-2]["atr"])
        side = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        price = tick.bid if side == "BUY" else tick.ask
        min_move = max(info.point * 5, atr * 0.05)     # avoid modify spam on tiny ticks
        new_sl = next_stop(side, p.price_open, p.sl, price, atr,
                           engine.breakeven_atr, engine.trail_atr, min_move)
        if new_sl is None:
            continue
        # Respect broker stop level distance from current price.
        stops_dist = info.trade_stops_level * info.point
        if (side == "BUY" and price - new_sl < stops_dist) or (side == "SELL" and new_sl - price < stops_dist):
            continue
        # First move that takes the trade out of risk is BREAKEVEN, later moves are TRAIL.
        old_sl = p.sl
        at_risk = old_sl == 0 or (side == "BUY" and old_sl < p.price_open) or (side == "SELL" and old_sl > p.price_open)
        tag = "BREAKEVEN" if at_risk else "TRAIL"
        if modify_sl(p, new_sl, magic=engine.magic):
            log.info("[%s] %s #%s sl %.*f -> %.*f", p.symbol, tag, p.ticket,
                     info.digits, old_sl, info.digits, new_sl)
            record_trade("SL_MOVE", p.symbol, side, p.volume, round(price, info.digits),
                         round(new_sl, info.digits), p.tp, ticket=p.ticket, note=tag)
```

The scripted simulation sets `config.MANAGE_POSITIONS = True` before the Bot is built, so the scalper profile built in `Bot.__init__` carries `manage=True` and the existing simulate test keeps its `SL_MOVE` rows.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_position_manager.py tests/test_simulate.py -q`
Expected: PASS. (`test_simulate` will still pass because `main.py` calls `manage_positions()` with no argument until Task 7.)

- [ ] **Step 5: Commit**

```bash
git add position_manager.py tests/test_position_manager.py
git commit -m "refactor(position-manager): trail stops per engine profile

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: History sync and trade tagging by engine

**Files:**
- Modify: `history.py:122-138` (`sync_deals`), `analytics.py:25-42` (`Trade`), `analytics.py:53-87` (`pair_trades`), `analytics.py:197-199` (`trade_dicts`)
- Test: `tests/test_history.py`, `tests/test_analytics.py`

**Interfaces:**
- Produces:
  - `history.sync_deals(store, magics, include_all=False) -> int`: `magics` is an int or an iterable of ints.
  - `analytics.Trade` gains trailing field `magic: int = 0` (set from the position's first deal in `pair_trades`).
  - `analytics.trade_dicts(trades, limit, engine_names=None) -> list[dict]`: each dict gains `"engine"` (`engine_names.get(magic, "other")`, or `"other"` when no map).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_history.py`:

```python
def test_sync_accepts_several_magics(tmp_path, monkeypatch):
    s = TradeStore(str(tmp_path / "h.db"))
    monkeypatch.setattr(history.mt5, "history_deals_get", lambda a, b: (
        _deal(1, 1, mt5.DEAL_ENTRY_IN, 5000), _deal(2, 2, mt5.DEAL_ENTRY_IN, 6000, magic=998888),
        _deal(3, 3, mt5.DEAL_ENTRY_IN, 7000, magic=1)))
    assert sync_deals(s, magics=[777, 998888]) == 2
    assert sorted(d.magic for d in s.deals()) == [777, 998888]
```

(Add `import history` next to the existing `from history import ...` at the top of that file if it is not already imported as a module.)

Append to `tests/test_analytics.py`:

```python
from analytics import trade_dicts  # noqa: E402


def test_trades_carry_magic_and_engine_name(trades):
    assert all(t.magic == 777 for t in trades)
    rows = trade_dicts(trades, 10, {777: "scalper"})
    assert rows[0]["engine"] == "scalper"
    assert trade_dicts(trades, 10)[0]["engine"] == "other"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_history.py tests/test_analytics.py -q`
Expected: FAIL (`TypeError: sync_deals() got an unexpected keyword argument 'magics'`, `AttributeError: 'Trade' object has no attribute 'magic'`).

- [ ] **Step 3: Implement**

In `history.py` replace the `sync_deals` signature and filter:

```python
def sync_deals(store: TradeStore, magics, include_all: bool = False) -> int:
    """Pull deals from MT5 into the store. `magics`: one magic number or an iterable of them.
    First run = full history; later runs overlap the last day so amended commission/swap
    values are picked up. Returns rows written."""
    wanted = {magics} if isinstance(magics, int) else set(magics)
    last = store.last_deal_time()
    if last:
        date_from = datetime.fromtimestamp(last, timezone.utc) - timedelta(days=1)
    else:
        date_from = datetime(2000, 1, 1, tzinfo=timezone.utc)
    date_to = datetime.now(timezone.utc) + timedelta(days=2)
    raw = mt5.history_deals_get(date_from, date_to)
    if raw is None:
        return 0
    deals = [Deal.from_mt5(d) for d in raw if include_all or d.magic in wanted]
    n = store.upsert_deals(deals)
    if n:
        log.debug("history: synced %d deals", n)
    return n
```

The existing tests call `sync_deals(s, magic=777)` by keyword at `tests/test_history.py` lines 45, 48, 50 and 57; change each `magic=777` to `magics=777` (assertions unchanged).

In `analytics.py` add `magic: int = 0` as the last field of `Trade` (after `weekday`). In `pair_trades` (`analytics.py:74-82`) the `Trade(...)` constructor already has the entry deals in the local list `ins`; add the keyword `magic=int(ins[0].magic),` after `weekday=entry_dt.weekday(),`. Replace `trade_dicts`:

```python
def trade_dicts(trades, limit: int, engine_names: dict | None = None) -> list[dict]:
    """Newest first, capped, for the history table; each row is tagged with its engine name."""
    names = engine_names or {}
    out = []
    for t in reversed(trades[-limit:]):
        row = asdict(t)
        row["engine"] = names.get(t.magic, "other")
        out.append(row)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_history.py tests/test_analytics.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add history.py analytics.py tests/test_history.py tests/test_analytics.py
git commit -m "feat(history): sync several magics and tag paired trades with their engine

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Status payload with engine blocks and tags

**Files:**
- Modify: `status.py:20-71`
- Test: `tests/test_status.py`

**Interfaces:**
- Produces:
  - `status.engine_block(engine, stats, paused) -> dict` with keys `name, magic, symbols, entries, max_entries, net_pnl, wins, losses, consecutive_losses, max_consecutive_losses, paused`.
  - `status.build_status(..., engines=None)`: `engines` is a list of `engine_block` dicts (default `[]`); `positions[*]["engine"]` from `getattr(p, "magic", None)` via the names map built from `engines`; `traders[*]["engine"]` from `getattr(t, "engine", None).name` or `"scalper"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_status.py`:

```python
from types import SimpleNamespace as _NS  # noqa: E402

from status import engine_block  # noqa: E402


def test_engine_block_and_tags():
    eng = _NS(name="london", magic=998888, symbols=("EURUSD", "GBPUSD"), max_trades_per_day=2, max_consecutive_losses=4)
    blk = engine_block(eng, DailyStats(net_pnl=-3.0, consecutive_losses=1, entries=1, wins=0, losses=1), paused=None)
    assert blk == {"name": "london", "magic": 998888, "symbols": ["EURUSD", "GBPUSD"], "entries": 1, "max_entries": 2,
                   "net_pnl": -3.0, "wins": 0, "losses": 1, "consecutive_losses": 1, "max_consecutive_losses": 4,
                   "paused": None}
    pos = _pos()
    pos.magic = 998888
    trader = _trader("EURUSD")
    trader.engine = _NS(name="london")
    s = build_status(now=datetime(2026, 9, 7, 14, 30), stats=DailyStats(), positions=[pos, _pos()],
                     traders=[trader, _trader("XAUUSD")], breaker=None, symbols=["EURUSD", "XAUUSD"],
                     started_at=0.0, now_mono=1.0, engines=[blk])
    assert s["engines"] == [blk]
    assert [p["engine"] for p in s["positions"]] == ["london", "other"]
    assert [t["engine"] for t in s["traders"]] == ["london", "scalper"]
```

Also update the two existing assertions in `test_build_status_open_market` so the expected position dict includes `"engine": "other"` and each expected trader dict includes `"engine": "scalper"` (the fakes carry no magic/engine).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_status.py -q`
Expected: FAIL with `ImportError: cannot import name 'engine_block'`.

- [ ] **Step 3: Implement in `status.py`**

Add after `_side`:

```python
def engine_block(engine, stats, paused) -> dict:
    """One engine's day for the dashboard strip."""
    return {
        "name": engine.name, "magic": engine.magic, "symbols": list(engine.symbols),
        "entries": stats.entries if stats else 0, "max_entries": engine.max_trades_per_day,
        "net_pnl": round(stats.net_pnl, 2) if stats else 0.0,
        "wins": stats.wins if stats else 0, "losses": stats.losses if stats else 0,
        "consecutive_losses": stats.consecutive_losses if stats else 0,
        "max_consecutive_losses": engine.max_consecutive_losses,
        "paused": paused,
    }
```

Change the `build_status` signature to end with `charts: dict | None = None, news: dict | None = None, engines: list | None = None) -> dict:`; add at the top of the body `engines = engines or []` and `names = {e["magic"]: e["name"] for e in engines}`; add `"engine": names.get(getattr(p, "magic", None), "other")` to each position dict; add `"engine": getattr(getattr(t, "engine", None), "name", "scalper")` to each trader dict; add `"engines": engines,` to the returned dict after `"traders": trd,`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_status.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add status.py tests/test_status.py
git commit -m "feat(status): per-engine day blocks and engine tags on positions and traders

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Reporter with engine names

**Files:**
- Modify: `reporting.py:14-91`
- Test: `tests/test_reporting.py` (new)

**Interfaces:**
- Produces:
  - `Reporter(engine_names=None)`; attribute `engine_names: dict[int, str]` (default `{config.MAGIC_NUMBER: "scalper"}`).
  - `notify_closes(stats)`: unchanged, plus a `▪ Engine: <name>` line when more than one engine is known.
  - `maybe_heartbeat(server_dt, stats, symbols, engine_stats=None)`: `engine_stats` is a list of `(engine, DailyStats)`; when given, one `▪ <name>: entries n/cap · net $x` line per engine replaces the single entries line.
  - `maybe_daily_summary(server_dt, stats, engine_stats=None)` using pure `daily_summary_text(server_dt, stats, engine_stats) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reporting.py`:

```python
"""Telegram texts are built by pure helpers so the wording is testable without MT5."""
from datetime import datetime
from types import SimpleNamespace

import MetaTrader5 as mt5

import config
import reporting
from reporting import Reporter, daily_summary_text
from risk import DailyStats


def _engine(name, cap=6):
    return SimpleNamespace(name=name, max_trades_per_day=cap)


def test_daily_summary_lists_each_engine_and_the_total():
    total = DailyStats(net_pnl=7.5, entries=3, wins=2, losses=1,
                       closed=[SimpleNamespace(profit=5.0, commission=0, swap=0, fee=0),
                               SimpleNamespace(profit=-2.5, commission=0, swap=0, fee=0)])
    text = daily_summary_text(datetime(2026, 9, 7, 23, 0), total,
                              [(_engine("scalper"), DailyStats(net_pnl=10.0, entries=2, wins=2)),
                               (_engine("london", 2), DailyStats(net_pnl=-2.5, entries=1, losses=1))])
    assert "Daily summary 2026-09-07" in text
    assert "scalper: entries 2, net $10.00" in text and "london: entries 1, net $-2.50" in text
    assert "<b>Net: $7.50</b>" in text


def test_daily_summary_without_engines_matches_single_engine_wording():
    text = daily_summary_text(datetime(2026, 9, 7, 23, 0), DailyStats(), None)
    assert text == "\U0001F4CA <b>Daily summary 2026-09-07</b>\nNo trades today."


def test_close_message_names_engine_only_with_several_engines(monkeypatch):
    sent = []
    monkeypatch.setattr(reporting, "send_telegram", sent.append)
    monkeypatch.setattr(reporting, "record_trade", lambda *a, **k: None)
    deal = SimpleNamespace(ticket=1, position_id=1, symbol="EURUSD", type=mt5.DEAL_TYPE_SELL, price=1.1,
                           volume=0.02, profit=2.0, commission=0.0, swap=0.0, fee=0.0, reason=mt5.DEAL_REASON_TP,
                           time=1_800_000_000, magic=998888)
    r = Reporter({config.MAGIC_NUMBER: "scalper", 998888: "london"})
    r.primed = True
    r.notify_closes(DailyStats(closed=[deal]))
    assert "Engine: london" in sent[0]
    single = Reporter()
    single.primed = True
    single.notify_closes(DailyStats(closed=[deal]))
    assert "Engine:" not in sent[1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_reporting.py -q`
Expected: FAIL with `ImportError: cannot import name 'daily_summary_text'`.

- [ ] **Step 3: Implement in `reporting.py`**

Replace the class header and `__init__`:

```python
class Reporter:
    def __init__(self, engine_names: dict | None = None):
        self.engine_names = engine_names or {config.MAGIC_NUMBER: "scalper"}
        self.seen_exit_tickets: set = set()
        self.last_heartbeat: float | None = None      # time.monotonic()
        self.last_summary_date = None
        self.primed = False
```

In `notify_closes`, before `send_telegram(`, add
`engine_line = f"▪ Engine: {self.engine_names.get(getattr(d, 'magic', None), 'other')}\n" if len(self.engine_names) > 1 else ""`
and insert `{engine_line}` as the first line after the `Trade Closed` title (i.e. `f"{emoji} <b>Trade Closed: {opened} {d.symbol}</b>\n{engine_line}"`).

Replace `maybe_heartbeat` with:

```python
    def maybe_heartbeat(self, server_dt: datetime, stats: DailyStats, symbols, engine_stats=None) -> None:
        mono = time.monotonic()
        if self.last_heartbeat is not None and mono - self.last_heartbeat < config.HEARTBEAT_HOURS * 3600:
            return
        self.last_heartbeat = mono
        pos = bot_positions()
        lines = [f"▪ {p.symbol} {'BUY' if p.type == mt5.POSITION_TYPE_BUY else 'SELL'} {p.volume} "
                 f"@ {p.price_open} P/L ${p.profit:.2f}" for p in pos] or ["▪ none"]
        if engine_stats:
            entries = "\n".join(f"▪ {e.name}: entries {s.entries}/{e.max_trades_per_day} · net ${s.net_pnl:.2f}"
                                for e, s in engine_stats)
        else:
            entries = f"▪ Day net: ${stats.net_pnl:.2f} | entries {stats.entries}/{config.MAX_TRADES_PER_DAY}"
        send_telegram(
            f"\U0001F493 <b>Heartbeat</b> {server_dt:%Y-%m-%d %H:%M} server\n"
            f"▪ Symbols: {', '.join(symbols)}\n"
            f"{entries}\n"
            f"<b>Open positions</b>\n" + "\n".join(lines)
        )
        log.info("heartbeat sent")
```

Replace `maybe_daily_summary` with a thin wrapper plus a pure builder:

```python
    def maybe_daily_summary(self, server_dt: datetime, stats: DailyStats, engine_stats=None) -> None:
        if server_dt.hour < config.DAILY_SUMMARY_HOUR or self.last_summary_date == server_dt.date():
            return
        self.last_summary_date = server_dt.date()
        send_telegram(daily_summary_text(server_dt, stats, engine_stats))
        log.info("daily summary sent: net=%.2f closed=%d", stats.net_pnl, stats.closed_count)


def daily_summary_text(server_dt: datetime, stats: DailyStats, engine_stats) -> str:
    """End-of-day message: account totals plus one line per engine when several run."""
    title = f"\U0001F4CA <b>Daily summary {server_dt:%Y-%m-%d}</b>"
    if stats.entries == 0 and stats.closed_count == 0:
        return f"{title}\nNo trades today."
    best = max((deal_net(d) for d in stats.closed), default=0.0)
    worst = min((deal_net(d) for d in stats.closed), default=0.0)
    per_engine = ""
    if engine_stats and len(engine_stats) > 1:
        per_engine = "".join(f"▪ {e.name}: entries {s.entries}, net ${s.net_pnl:.2f}\n" for e, s in engine_stats)
    return (f"{title}\n"
            f"▪ Entries: {stats.entries}\n"
            f"▪ Closed: {stats.closed_count} ({stats.wins}W / {stats.losses}L, {stats.win_rate:.0f}%)\n"
            f"▪ Best: ${best:.2f} | Worst: ${worst:.2f}\n"
            f"{per_engine}"
            f"▪ <b>Net: ${stats.net_pnl:.2f}</b>")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_reporting.py tests/test_simulate.py -q`
Expected: all PASS (the scripted simulation still finds "Daily summary" and "Heartbeat").

- [ ] **Step 5: Commit**

```bash
git add reporting.py tests/test_reporting.py
git commit -m "feat(reporting): name the engine in close, heartbeat and daily summary messages

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Bot loop over engines

**Files:**
- Modify: `main.py` (whole `Bot` class and `run()`)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `engines.build_engines/engine_names`, `execution.set_known_magics/bot_positions`, `risk.combine/account_breaker/engine_breaker/get_daily_stats`, `position_manager.manage_positions(engine)`, `history.sync_deals(store, magics, include_all)`, `analytics.trade_dicts(trades, limit, names)`, `status.build_status(..., engines=)`, `status.engine_block`, `Reporter(engine_names)`.
- Produces:
  - `Bot(symbols, web=None, pages=None, engines=None)`: attributes `engines` (list of `Engine` restricted to available symbols; engines with no symbols dropped with a warning), `symbols` (union, first-appearance order), `traders` (list of `SymbolTrader`), `paused` (dict engine name -> reason), `reporter`.
  - `Bot.tick()` as in the spec: per-engine stats, combined stats, account breaker pauses everything, engine breaker pauses one engine (one log + one Telegram per pause), each `trader.step` isolated by try/except that re-raises when `mt5.terminal_info()` is None.
  - `run()` initialises the union of engine symbols and announces every engine.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
from dataclasses import replace  # noqa: E402
from datetime import datetime  # noqa: E402

import config  # noqa: E402
from engines import scalper_engine  # noqa: E402
from risk import DailyStats  # noqa: E402


class _Trader:
    def __init__(self, symbol, engine):
        self.symbol, self.engine, self.steps = symbol, engine, []
        self.last_skip_reason = None
        self.last_signal_bar = None

    def step(self, now, entries, news_block=None):
        self.steps.append(entries)

    def frame(self, max_age=0):
        return None


def _two_engine_bot(monkeypatch, stats_by_magic):
    scalper = scalper_engine()
    london = replace(scalper, name="london", magic=998888, symbols=("EURUSD",), max_consecutive_losses=2)
    monkeypatch.setattr(main, "SymbolTrader", _Trader)
    monkeypatch.setattr(main, "get_daily_stats", lambda magic, now: stats_by_magic[magic])
    monkeypatch.setattr(main, "manage_positions", lambda engine=None: None)
    monkeypatch.setattr(main, "bot_positions", lambda *a, **k: [])
    monkeypatch.setattr(main.config, "HISTORY_ENABLED", False)
    monkeypatch.setattr(main.config, "WEB_ENABLED", False)
    sent = []
    monkeypatch.setattr(main, "send_telegram", sent.append)
    bot = main.Bot(["XAUUSD", "XAGUSD", "EURUSD"], engines=[scalper, london])
    bot.clock.now = lambda symbols: datetime(2026, 9, 7, 12, 0)
    bot.news.maybe_refresh = lambda *a, **k: False
    bot.news.block_reason = lambda *a, **k: None
    bot.reporter.maybe_heartbeat = lambda *a, **k: None
    bot.reporter.maybe_daily_summary = lambda *a, **k: None
    return bot, sent


def test_bot_builds_one_trader_per_engine_symbol_and_drops_unavailable(monkeypatch):
    scalper = scalper_engine()
    london = replace(scalper, name="london", magic=998888, symbols=("EURUSD", "GBPUSD"))
    monkeypatch.setattr(main, "SymbolTrader", _Trader)
    monkeypatch.setattr(main.config, "HISTORY_ENABLED", False)
    bot = main.Bot(["XAUUSD", "XAGUSD", "EURUSD"], engines=[scalper, london])
    assert [(t.symbol, t.engine.name) for t in bot.traders] == [("XAUUSD", "scalper"), ("XAGUSD", "scalper"), ("EURUSD", "london")]
    assert bot.symbols == ["XAUUSD", "XAGUSD", "EURUSD"]
    assert bot.engines[1].symbols == ("EURUSD",)
    import execution
    assert execution.KNOWN_MAGICS == {config.MAGIC_NUMBER, 998888}


def test_engine_streak_pauses_only_that_engine(monkeypatch):
    bot, sent = _two_engine_bot(monkeypatch, {config.MAGIC_NUMBER: DailyStats(entries=1),
                                              998888: DailyStats(consecutive_losses=2, entries=2)})
    bot.tick()
    steps = {(t.symbol, t.engine.name): t.steps for t in bot.traders}
    assert steps[("XAUUSD", "scalper")] == [1] and steps[("EURUSD", "london")] == []
    assert bot.paused == {"london": "2 consecutive losses"}
    assert len(sent) == 1 and "london" in sent[0]
    bot.tick()
    assert len(sent) == 1                                  # announced once


def test_account_loss_pauses_every_engine(monkeypatch):
    monkeypatch.setattr(config, "MAX_DAILY_LOSS_USD", 30.0)
    bot, sent = _two_engine_bot(monkeypatch, {config.MAGIC_NUMBER: DailyStats(net_pnl=-20.0),
                                              998888: DailyStats(net_pnl=-11.0)})
    assert bot.tick() == config.BREAKER_SLEEP_SECONDS
    assert all(t.steps == [] for t in bot.traders)
    assert "circuit breaker" in sent[0] and "scalper" in sent[0] and "london" in sent[0]


def test_one_failing_trader_does_not_stop_the_others(monkeypatch):
    bot, sent = _two_engine_bot(monkeypatch, {config.MAGIC_NUMBER: DailyStats(), 998888: DailyStats()})
    monkeypatch.setattr(main.mt5, "terminal_info", lambda: object())
    def boom(now, entries, news_block=None):
        raise RuntimeError("bad tick")
    bot.traders[0].step = boom
    bot.tick()
    assert bot.traders[1].steps == [0] and bot.traders[2].steps == [0]
    assert any("bad tick" in m for m in sent)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_main.py -q`
Expected: FAIL with `TypeError: Bot.__init__() got an unexpected keyword argument 'engines'`.

- [ ] **Step 3: Rewrite `Bot` and `run()` in `main.py`**

Replace the imports block's relevant lines so that `main.py` imports:

```python
from dataclasses import replace

from analytics import pair_trades, build_analytics, trade_dicts
from engines import build_engines, engine_names
from execution import init_mt5, bot_positions, trading_blockers, set_known_magics
from history import TradeStore, sync_deals, snapshot_equity
from journal import setup_logging, log
from news import NewsFilter
from position_manager import manage_positions
from reporting import Reporter
from risk import ServerClock, get_daily_stats, combine, account_breaker, engine_breaker
from publisher import PagesPublisher
from status import build_status, with_trades, chart_block, engine_block
from strategy import SymbolTrader
from telegram_notifier import send_telegram
from web import StatusServer
```

Replace the `Bot` class with:

```python
class Bot:
    def __init__(self, symbols, web: StatusServer | None = None, pages: PagesPublisher | None = None,
                 engines=None):
        available = list(symbols)
        self.engines = []
        for e in (engines if engines is not None else build_engines()):
            syms = tuple(s for s in e.symbols if s in available)
            if not syms:
                log.warning("engine %s disabled: none of %s is available", e.name, list(e.symbols))
                continue
            self.engines.append(replace(e, symbols=syms))
        self.symbols = []
        for e in self.engines:
            for s in e.symbols:
                if s not in self.symbols:
                    self.symbols.append(s)
        set_known_magics(e.magic for e in self.engines)
        self.traders = [SymbolTrader(s, e) for e in self.engines for s in e.symbols]
        self.reporter = Reporter(engine_names(self.engines))
        self.clock = ServerClock()
        self.web = web
        self.pages = pages
        self.store = TradeStore() if config.HISTORY_ENABLED else None
        self.last_sync: float | None = None
        self.account: dict | None = None
        self.analytics: dict | None = None
        self.history: list = []
        self.charts: dict = {}
        self.last_chart_refresh: float | None = None
        self.started_at = time.monotonic()
        self.breaker_alerted = False
        self.paused: dict = {}                      # engine name -> pause reason already announced
        self.no_quote_logged = False
        self.news = NewsFilter()
        self.news_alerted: str | None = None        # blackout reason already announced on Telegram

    def _maybe_sync_history(self, now) -> None:
        """Every HISTORY_SYNC_SECONDS: pull deals from MT5, snapshot equity, recompute the
        cached analytics. Runs with or without quotes so equity keeps recording on weekends."""
        if self.store is None:
            return
        mono = time.monotonic()
        if self.last_sync is not None and mono - self.last_sync < config.HISTORY_SYNC_SECONDS:
            return
        self.last_sync = mono
        try:
            n = sync_deals(self.store, [e.magic for e in self.engines], config.HISTORY_INCLUDE_ALL_DEALS)
            epoch = calendar.timegm(now.timetuple()) if now else int(time.time())
            open_pnl = sum(p.profit for p in bot_positions())
            self.account = snapshot_equity(self.store, open_pnl=open_pnl, now_epoch=epoch)
            trades = pair_trades(self.store.deals())
            start_balance = None
            if self.account:
                start_balance = round(self.account["balance"] - sum(t.net for t in trades), 2)
            snapshots = self.store.equity_series(since=epoch - 30 * 86400, step=3600)
            self.analytics = build_analytics(trades, start_balance, snapshots)
            self.history = trade_dicts(trades, config.HISTORY_MAX_TRADES, engine_names(self.engines))
            if n:
                log.info("history: synced %d deals, %d closed trades on record", n, len(trades))
        except Exception as e:
            log.warning("history sync failed: %s", e)

    def _maybe_refresh_charts(self) -> None:
        """Every CHART_REFRESH_SECONDS: rebuild the per-symbol candle panels from each trader's frame."""
        mono = time.monotonic()
        if self.last_chart_refresh is not None and mono - self.last_chart_refresh < config.CHART_REFRESH_SECONDS:
            return
        self.last_chart_refresh = mono
        try:
            positions = bot_positions()
            charts = {}
            for trader in self.traders:
                if trader.symbol in charts:
                    continue                            # first engine listing the symbol draws it
                blk = chart_block(trader.frame(config.CHART_REFRESH_SECONDS), trader.symbol, positions)
                if blk is not None:
                    charts[trader.symbol] = blk
            self.charts = charts
        except Exception as e:
            log.warning("chart refresh failed: %s", e)

    def _publish(self, now, stats, breaker, engine_stats=None) -> None:
        """Push a snapshot to the status page and (on its interval) to GitHub Pages.
        Never allowed to break trading."""
        if self.web is None and self.pages is None:
            return
        try:
            self._maybe_refresh_charts()
            blocks = [engine_block(e, (engine_stats or {}).get(e.name), self.paused.get(e.name))
                      for e in self.engines]
            snap = build_status(now, stats, bot_positions(), self.traders, breaker,
                                self.symbols, self.started_at, time.monotonic(),
                                account=self.account, analytics=self.analytics, history=self.history,
                                charts=self.charts, news=self.news.snapshot(), engines=blocks)
            if self.web is not None:
                self.web.update(snap)
            if self.pages is not None:
                self.pages.maybe_publish(with_trades(snap))
        except Exception as e:
            log.warning("status update failed: %s", e)

    def tick(self) -> float:
        """One pass. Returns how long to sleep before the next one."""
        now = self.clock.now(self.symbols)
        self._maybe_sync_history(now)
        self.news.maybe_refresh()                    # cheap when not due; runs on weekends too
        if now is None:
            if not self.no_quote_logged:
                log.warning("no quotes for %s yet (market closed?)", self.symbols)
                self.no_quote_logged = True
            self._publish(None, None, None)
            return config.LOOP_SLEEP_SECONDS
        self.no_quote_logged = False

        engine_stats = {e.name: get_daily_stats(e.magic, now) for e in self.engines}
        stats = combine(engine_stats.values())
        pairs = [(e, engine_stats[e.name]) for e in self.engines]
        self.reporter.notify_closes(stats)
        for e in self.engines:
            manage_positions(e)
        self.reporter.maybe_heartbeat(now, stats, self.symbols, pairs)
        self.reporter.maybe_daily_summary(now, stats, pairs)

        reason = account_breaker(stats)
        if reason:
            if not self.breaker_alerted:
                per_engine = "".join(f"▪ {e.name}: ${s.net_pnl:.2f}\n" for e, s in pairs)
                msg = (f"⛔ <b>Daily circuit breaker</b>\n▪ {reason}\n"
                       f"▪ Day net: ${stats.net_pnl:.2f}\n{per_engine}"
                       f"<i>Entries paused until next server day.</i>")
                log.warning("BREAKER: %s", reason)
                send_telegram(msg)
                self.breaker_alerted = True
            self._publish(now, stats, reason, engine_stats)
            return config.BREAKER_SLEEP_SECONDS
        self.breaker_alerted = False

        news_block = self.news.block_reason()
        if news_block and news_block != self.news_alerted:
            log.info("NEWS %s: entries paused %d min before / %d min after", news_block,
                     config.NEWS_BLOCK_BEFORE_MIN, config.NEWS_BLOCK_AFTER_MIN)
            send_telegram(f"\U0001F4F0 <b>News blackout</b>\n▪ {news_block}\n"
                          f"<i>No new entries {config.NEWS_BLOCK_BEFORE_MIN} min before / "
                          f"{config.NEWS_BLOCK_AFTER_MIN} min after.</i>")
        self.news_alerted = news_block

        for trader in self.traders:
            e = trader.engine
            es = engine_stats[e.name]
            pause = engine_breaker(e, es)
            if pause:
                if self.paused.get(e.name) != pause:
                    log.warning("[%s] engine paused: %s", e.name, pause)
                    send_telegram(f"⏸ <b>{e.name} paused</b>\n▪ {pause}\n<i>Other engines keep trading.</i>")
                    self.paused[e.name] = pause
                continue
            self.paused.pop(e.name, None)
            try:
                trader.step(now, es.entries, news_block)
            except Exception as exc:
                if mt5.terminal_info() is None:
                    raise                                # terminal gone: let run() reconnect
                log.error("[%s] %s step failed: %s\n%s", trader.symbol, e.name, exc, traceback.format_exc())
                send_telegram(f"⚠️ <b>{e.name} error on {trader.symbol}</b> (bot still running)\n"
                              f"<code>{type(exc).__name__}: {exc}</code>")
        self._publish(now, stats, None, engine_stats)
        return config.LOOP_SLEEP_SECONDS
```

In `run()`, replace the start-up section (from `symbols = init_mt5(config.SYMBOLS)` down to the `bot = Bot(...)` line) with:

```python
    engines = build_engines()
    wanted = []
    for e in engines:
        for s in e.symbols:
            if s not in wanted:
                wanted.append(s)
    symbols = init_mt5(wanted)
    if not symbols:
        log.error("no tradable symbols, exiting with code 1 so the scheduler restarts us")
        return 1

    for e in engines:
        log.info("START engine=%s magic=%s symbols=%s risk=$%.2f/trade cap=%d/day trend=%s",
                 e.name, e.magic, [s for s in e.symbols if s in symbols], e.risk_usd, e.max_trades_per_day, e.trend_filter)
    log.info("START session=%s news=%s", config.SESSION_FILTER_ENABLED, config.NEWS_FILTER_ENABLED)
    send_telegram("\U0001F680 <b>Bot started</b>\n" + "\n".join(
        f"▪ {e.name}: {', '.join(s for s in e.symbols if s in symbols) or 'no symbols'}" for e in engines))
    warn_if_trading_blocked()
    web = StatusServer() if config.WEB_ENABLED else None
    if web and not web.start():
        web = None
    pages = PagesPublisher() if config.PAGES_PUBLISH_ENABLED else None
    if pages and not pages.remote:
        log.warning("pages publishing disabled: no git remote found")
        pages = None
    bot = Bot(symbols, web, pages, engines)
```

`test_run_returns_failure_code_when_mt5_init_fails` and `test_run_checks_permissions_right_after_connecting` keep passing: both monkeypatch `init_mt5` with a one-argument lambda.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_main.py tests/test_simulate.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite and commit**

Run: `python -m pytest tests -q`

```bash
git add main.py tests/test_main.py
git commit -m "feat(main): run every engine profile in one loop with account and engine breakers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Backtester takes engine callables

**Files:**
- Modify: `backtest.py:71-115` (`run_backtest`), `backtest.py:142-159` (`format_report`), `backtest.py:169-197` (`load_history`), `backtest.py:200-233` (`main`)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Produces:
  - `run_backtest(df, symbol, spread_price, tick_size, tick_value, lot_fn, signal=None, levels=None, max_trades_per_day=None, max_consecutive_losses=None, manage=None, be_atr=None, trail_atr=None) -> list[SimTrade]`; every `None` falls back to today's config/scalper behaviour; `levels(side, ask, bid, bar)` may return None (bar skipped).
  - `format_report(days, per_symbol, engine_name="scalper") -> str` (first line becomes `<b>BACKTEST scalper</b> ...`).
  - `load_history(symbol, days, engine=None)` uses `engine.timeframe`, `engine.trend_filter`, `engine.analyse(df, htf, info)`.
  - CLI: `--engine {scalper,london}` (default scalper; `london` resolves once Task 13 adds `engines.london_engine`), `--symbol` defaults to the engine's symbols.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backtest.py`:

```python
def test_run_backtest_accepts_signal_and_levels_callables(no_filters):
    from strategy import Levels
    df = frame([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100), (100, 107, 99.5, 106)])
    df["atr"] = 2.0
    sig = lambda bar: "BUY" if bar["time"].minute == 5 else None            # bar 1 only
    lv = lambda side, ask, bid, bar: Levels(side, ask, ask - 3.0, ask + 6.0, 3.0)
    trades = run_backtest(df, "X", 0.0, 0.01, 0.1, lambda d: 0.1, signal=sig, levels=lv)
    assert len(trades) == 1 and trades[0].tp == 106 and trades[0].reason == "TP"
    none = run_backtest(df, "X", 0.0, 0.01, 0.1, lambda d: 0.1, signal=sig, levels=lambda *a: None)
    assert none == []


def test_engine_cap_and_streak_override_config(no_filters, monkeypatch):
    monkeypatch.setattr(config, "MAX_TRADES_PER_DAY", 99)
    rows = [(100, 101, 99, 100), (99, 99.5, 88, 89), (100, 107, 99.5, 106)] * 3
    df = frame(rows)
    df["atr"], df["lower_band"], df["upper_band"] = 2.0, 90.0, 110.0
    df["rsi"] = [50, 20, 50] * 3
    assert len(run_backtest(df, "X", 0.0, 0.01, 0.1, lambda d: 0.1, max_trades_per_day=1)) == 1


def test_format_report_names_the_engine():
    from backtest import format_report
    assert "<b>BACKTEST london</b>" in format_report(30, {}, engine_name="london")
    assert "<b>BACKTEST scalper</b>" in format_report(30, {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_backtest.py -q`
Expected: FAIL with `TypeError: run_backtest() got an unexpected keyword argument 'signal'`.

- [ ] **Step 3: Implement**

Replace `run_backtest` (`backtest.py:71-115`) with:

```python
def _scalper_levels(side, ask, bid, bar):
    return build_levels(side, ask, bid, float(bar["atr"]))


def run_backtest(df: pd.DataFrame, symbol: str, spread_price: float, tick_size: float,
                 tick_value: float, lot_fn, signal=None, levels=None, max_trades_per_day=None,
                 max_consecutive_losses=None, manage=None, be_atr=None, trail_atr=None) -> list:
    """df must already carry indicators (and trend_ema if the filter is on).

    Entry rule and levels are callables so any engine profile can be replayed; every optional
    parameter left at None uses the scalper's config value."""
    signal = signal or generate_signal
    levels = levels or _scalper_levels
    cap = config.MAX_TRADES_PER_DAY if max_trades_per_day is None else max_trades_per_day
    max_streak = config.MAX_CONSECUTIVE_LOSSES if max_consecutive_losses is None else max_consecutive_losses
    manage = config.MANAGE_POSITIONS if manage is None else manage
    be_atr = config.BREAKEVEN_ATR if be_atr is None else be_atr
    trail_atr = config.TRAIL_ATR if trail_atr is None else trail_atr
    trades = []
    rows = df.to_dict("records")                       # plain dicts: ~10x faster than df.iloc per bar
    times = df["time"].values
    day, entries_today, pnl_today, streak = None, 0, 0.0, 0
    i = 1
    while i < len(df) - 1:
        bar = rows[i]
        i += 1
        if np.isnan(bar["atr"]):
            continue
        t = bar["time"]
        if t.date() != day:
            day, entries_today, pnl_today, streak = t.date(), 0, 0.0, 0
        if not in_session(t):
            continue
        if entries_today >= cap:
            continue
        if pnl_today <= -config.MAX_DAILY_LOSS_USD or streak >= max_streak:
            continue
        side = signal(bar)
        if not side:
            continue

        mid = float(rows[i]["open"])                    # bar after the signal bar
        lv = levels(side, mid + spread_price / 2, mid - spread_price / 2, bar)
        if lv is None:
            continue
        lot = lot_fn(lv.sl_dist)
        if lot <= 0:
            continue
        entries_today += 1
        res = resolve_exit(df, i, side, lv.sl, lv.tp, entry=lv.entry, manage=manage, point=tick_size,
                           be_atr=be_atr, trail_atr=trail_atr)
        if res is None:
            break                                       # still open at end of data
        j, px, reason = res
        move = (px - lv.entry) if side == "BUY" else (lv.entry - px)
        pnl = move / tick_size * tick_value * lot
        trades.append(SimTrade(symbol, side, t, lv.entry, lv.sl, lv.tp, lot,
                               pd.Timestamp(times[j]), px, reason, round(pnl, 2)))
        pnl_today += pnl
        streak = streak + 1 if pnl < 0 else 0
        i = j + 1                                       # next signal bar is the closing bar
    return trades
```

Give `resolve_exit` two trailing keyword parameters `be_atr=None, trail_atr=None` and inside it call `next_stop(side, entry, sl, float(closes[j]), atr, config.BREAKEVEN_ATR if be_atr is None else be_atr, config.TRAIL_ATR if trail_atr is None else trail_atr, max(point * 5, atr * 0.05))`.

Change `format_report` to `def format_report(days: int, per_symbol: dict, engine_name: str = "scalper") -> str:` and its first line to `f"<b>BACKTEST {engine_name}</b> last {days} days (to {datetime.now():%Y-%m-%d})"`.

Replace `load_history`:

```python
def load_history(symbol: str, days: int, engine=None):
    import MetaTrader5 as mt5
    from execution import get_rates_range, lot_for_risk
    if engine is None:
        from engines import scalper_engine
        engine = scalper_engine()

    if not mt5.initialize():
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    mt5.symbol_select(symbol, True)
    info = mt5.symbol_info(symbol)
    if info is None:
        raise SystemExit(f"unknown symbol {symbol}")
    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=days + 1)
    df = get_rates_range(symbol, engine.timeframe, start, end)
    htf = get_rates_range(symbol, config.TREND_TIMEFRAME, start - timedelta(days=45), end) if engine.trend_filter else None
    mt5.shutdown()
    if df is None or len(df) < 100:
        raise SystemExit("not enough signal-TF history (check Max bars in chart in MT5 options)")
    if engine.trend_filter and (htf is None or len(htf) < config.TREND_EMA_PERIOD):
        raise SystemExit("not enough higher-TF history for the trend EMA")
    df = engine.analyse(df, htf, info)
    spread_price = history_spread(df, info.spread, info.point)

    def lot_fn(sl_dist):
        return lot_for_risk(sl_dist, engine.risk_usd, info.trade_tick_size,
                            info.trade_tick_value, info.volume_min, info.volume_max, info.volume_step)

    return df, spread_price, info.trade_tick_size, info.trade_tick_value, lot_fn
```

Replace `main()`:

```python
def main():
    from engines import scalper_engine
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["scalper", "london"], default="scalper")
    ap.add_argument("--symbol", nargs="+", help="one or more symbols (default: the engine's symbols)")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--csv", help="write trade list to this CSV file")
    ap.add_argument("--no-trend", action="store_true", help="disable the trend filter")
    ap.add_argument("--no-session", action="store_true", help="disable the session filter")
    ap.add_argument("--telegram", action="store_true", help="send the summary to the Telegram chat")
    args = ap.parse_args()
    if args.no_trend:
        config.TREND_FILTER_ENABLED = False
        config.LDN_TREND_FILTER = False
    if args.no_session:
        config.SESSION_FILTER_ENABLED = False
    if args.engine == "london":
        from engines import london_engine
        engine = london_engine()
    else:
        engine = scalper_engine()
    symbols = args.symbol or list(engine.symbols)

    all_trades, per_symbol = [], {}
    for symbol in symbols:
        df, spread, tick_size, tick_value, lot_fn = load_history(symbol, args.days, engine)
        print(f"{engine.name} {symbol}: {len(df)} bars {df['time'].iloc[0]} -> {df['time'].iloc[-1]}, "
              f"median spread {spread:.5g}, trend={engine.trend_filter} session={config.SESSION_FILTER_ENABLED}")
        trades = run_backtest(df, symbol, spread, tick_size, tick_value, lot_fn,
                              signal=engine.signal, levels=engine.levels,
                              max_trades_per_day=engine.max_trades_per_day,
                              max_consecutive_losses=engine.max_consecutive_losses,
                              manage=engine.manage, be_atr=engine.breakeven_atr, trail_atr=engine.trail_atr)
        per_symbol[symbol] = summarize(trades)
        for k, v in per_symbol[symbol].items():
            print(f"{k:>14}: {v}")
        all_trades.extend(trades)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(all_trades[0]).keys()) if all_trades else ["symbol"])
            w.writeheader()
            for t in all_trades:
                w.writerow(asdict(t))
        print(f"wrote {len(all_trades)} trades to {args.csv}")
    if args.telegram:
        from telegram_notifier import send_telegram
        send_telegram(format_report(args.days, per_symbol, engine.name))
        print("summary sent to Telegram")
```

Note: `engine.levels` for the scalper is `engines.scalper_levels`, identical to `_scalper_levels`; `--engine london` fails with `ImportError` until Task 13 lands, which is expected in Phase 1.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_backtest.py -q`
Expected: all PASS.

- [ ] **Step 5: Verify the scalper replay is unchanged, then commit**

Run: `python backtest.py --symbol XAUUSD XAGUSD --days 180`
Expected: XAUUSD 58 trades net 68.95, XAGUSD 45 trades net 66.5 (the numbers recorded on 2026-09-06; MT5 must be running).

```bash
git add backtest.py tests/test_backtest.py
git commit -m "refactor(backtest): replay any engine profile through run_backtest

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Phase 2: the London engine

### Task 11: `LDN_*` config and the pure London rule

**Files:**
- Modify: `config.py` (append a block after the "Position management" section, lines 80-84; add EURUSD/GBPUSD to `MAX_ALLOWED_SPREAD_POINTS` at lines 31-35)
- Create: `london.py`
- Test: `tests/test_london.py` (new)

**Interfaces:**
- Produces:
  - `london.pip_size(point, digits) -> float`.
  - `london.add_box_columns(df, buffer_price) -> DataFrame` adding `box_high`, `box_low` (the server day's box edges on every bar of that day; NaN on days without box bars), `in_window`, `first_break` (bool) and `box_break` (`"BUY"`, `"SELL"`, `""`); reads `config.LDN_BOX_START_HOUR`, `LDN_BOX_END_HOUR`, `LDN_WINDOW_END_HOUR`, `LDN_MAX_BOX_ATR`. Breaks are only evaluated inside the entry window, so the edges being known during the box hours is not look-ahead.
  - `london.london_signal(bar) -> str | None`: `bar["box_break"]` gated by `trend_allows(side, close, trend_ema, enabled=config.LDN_TREND_FILTER)`.
  - `london.london_levels(side, ask, bid, bar) -> Levels | None` per `config.LDN_SL_MODE`, `LDN_SL_ATR`, `LDN_TP_R`.
  - `london.london_analyse(df, htf=None, info=None) -> DataFrame`: `compute_indicators` -> `add_box_columns(df, LDN_BUFFER_PIPS * pip_size(info.point, info.digits))` -> `attach_trend` when `htf` given. `info=None` means pip = 0.0001.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_london.py`:

```python
"""London-open range breakout: box edges, first break per day, levels. Pure, no MT5."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

import config
from london import pip_size, add_box_columns, london_signal, london_levels, london_analyse


@pytest.fixture(autouse=True)
def ldn_defaults(monkeypatch):
    for k, v in dict(LDN_BOX_START_HOUR=0, LDN_BOX_END_HOUR=10, LDN_WINDOW_END_HOUR=14, LDN_BUFFER_PIPS=0.0,
                     LDN_MAX_BOX_ATR=0.0, LDN_TREND_FILTER=False, LDN_SL_MODE="atr", LDN_SL_ATR=1.5,
                     LDN_TP_R=2.0).items():
        monkeypatch.setattr(config, k, v, raising=False)


def day_frame(day="2026-09-07", box=(1.1000, 1.1020), after=None, step_min=5):
    """One server day of M5 bars: the box hours trade inside `box`; `after` maps hour -> close."""
    times = pd.date_range(f"{day} 00:00", periods=24 * 60 // step_min, freq=f"{step_min}min")
    lo, hi = box
    closes = []
    for t in times:
        h = t.hour + t.minute / 60
        if h < 10:
            closes.append(lo + (hi - lo) * ((t.minute // 5) % 2))       # alternate within the box
        else:
            closes.append((after or {}).get(t.hour, (lo + hi) / 2))
    df = pd.DataFrame({"time": times, "close": closes})
    df["open"] = df["close"]
    df["high"] = df["close"] + 0.0001
    df["low"] = df["close"] - 0.0001
    df["atr"] = 0.0003
    return df


def test_pip_size():
    assert pip_size(0.00001, 5) == pytest.approx(0.0001)
    assert pip_size(0.001, 3) == pytest.approx(0.01)
    assert pip_size(0.01, 2) == pytest.approx(0.01)


def test_box_edges_and_single_first_break():
    df = add_box_columns(day_frame(after={10: 1.1030, 11: 1.1035, 12: 1.0990}), buffer_price=0.0)
    assert not df.loc[df["time"].dt.hour < 10, "first_break"].any()   # never fires inside the box hours
    window = df[df["time"].dt.hour >= 10]
    assert window["box_high"].iloc[0] == pytest.approx(1.1021)      # box high includes the bar wick
    assert window["box_low"].iloc[0] == pytest.approx(1.0999)
    breaks = df[df["first_break"]]
    assert len(breaks) == 1 and breaks.iloc[0]["time"] == pd.Timestamp("2026-09-07 10:00")
    assert breaks.iloc[0]["box_break"] == "BUY"
    assert (df.loc[df["time"].dt.hour == 12, "box_break"] == "").all()   # later reverse break ignored


def test_buffer_and_window_end_are_respected():
    df = add_box_columns(day_frame(after={10: 1.1022, 13: 1.1040, 14: 1.1050}), buffer_price=0.0005)
    breaks = df[df["first_break"]]
    assert len(breaks) == 1 and breaks.iloc[0]["time"].hour == 13      # 10:00 close is inside the buffer
    late = add_box_columns(day_frame(after={15: 1.1050}), buffer_price=0.0)
    assert not late["first_break"].any()                                # window closed at 14:00


def test_width_filter_skips_wide_boxes(monkeypatch):
    monkeypatch.setattr(config, "LDN_MAX_BOX_ATR", 3.0)               # 3 x 0.0003 = 0.0009 < box 0.0022
    df = add_box_columns(day_frame(after={10: 1.1030}), buffer_price=0.0)
    assert not df["first_break"].any()


def test_first_break_is_per_day():
    a = day_frame("2026-09-07", after={10: 1.1030})
    b = day_frame("2026-09-08", after={11: 1.0980})
    df = add_box_columns(pd.concat([a, b], ignore_index=True), buffer_price=0.0)
    assert list(df.loc[df["first_break"], "box_break"]) == ["BUY", "SELL"]


def test_signal_gates_on_engine_trend_flag(monkeypatch):
    bar = {"box_break": "BUY", "close": 1.1030, "trend_ema": 1.1100}
    assert london_signal(bar) == "BUY"
    monkeypatch.setattr(config, "LDN_TREND_FILTER", True)
    assert london_signal(bar) is None
    assert london_signal({"box_break": "", "close": 1.1, "trend_ema": 1.0}) is None


def test_levels_atr_mode():
    lv = london_levels("BUY", 1.1030, 1.1028, {"atr": 0.0004, "box_high": 1.1020, "box_low": 1.1000})
    assert lv.entry == 1.1030 and lv.sl == pytest.approx(1.1024) and lv.tp == pytest.approx(1.1042)
    assert lv.sl_dist == pytest.approx(0.0006)


def test_levels_box_modes(monkeypatch):
    bar = {"atr": 0.0004, "box_high": 1.1020, "box_low": 1.1000}
    monkeypatch.setattr(config, "LDN_SL_MODE", "box_opposite")
    lv = london_levels("SELL", 1.0992, 1.0990, bar)
    assert lv.entry == 1.0990 and lv.sl == pytest.approx(1.1020) and lv.tp == pytest.approx(1.0990 - 2 * 0.0030)
    monkeypatch.setattr(config, "LDN_SL_MODE", "box_mid")
    lv = london_levels("BUY", 1.1030, 1.1028, bar)
    assert lv.sl == pytest.approx(1.1010) and lv.sl_dist == pytest.approx(0.0020)
    assert london_levels("BUY", 1.1005, 1.1003, bar) is None            # entry below the midpoint
    assert london_levels("BUY", 1.1030, 1.1028, {"atr": 0.0004, "box_high": np.nan, "box_low": np.nan}) is None


def test_analyse_builds_columns_with_symbol_pip():
    from types import SimpleNamespace
    raw = day_frame(after={10: 1.1030}).drop(columns=["atr"])
    raw["tick_volume"], raw["spread"], raw["real_volume"] = 1, 3, 0
    out = london_analyse(raw, None, SimpleNamespace(point=0.00001, digits=5))
    for col in ("atr", "box_high", "box_low", "first_break", "box_break"):
        assert col in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_london.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'london'`.

- [ ] **Step 3: Add the config block**

In `config.py`, add `"EURUSD": 10,` and `"GBPUSD": 15,` inside `MAX_ALLOWED_SPREAD_POINTS` (before `"default"`), and append after the "Position management" block:

```python
# ── London breakout engine (london.py, engines.py) ──────────────────────────
# Second engine: first M5 close beyond the Asian box after the London open, own magic number.
# Hours are server time; this broker's server clock is UTC+3, so the London open is 10:00.
LDN_ENABLED = True
LDN_MAGIC_NUMBER = 998888
LDN_SYMBOLS = ["EURUSD", "GBPUSD"]      # metals opt-in
LDN_TIMEFRAME = mt5.TIMEFRAME_M5
LDN_RATES_LOOKBACK = 300                 # covers box + window from 00:00 to 17:00 server on M5
LDN_BOX_START_HOUR = 0
LDN_BOX_END_HOUR = 10                    # London open on this broker (server clock = UTC+3)
LDN_WINDOW_END_HOUR = 14                 # entries allowed in [BOX_END, WINDOW_END)
LDN_BUFFER_PIPS = 0.0                    # break = close beyond the edge by this many pips (0 tested best)
LDN_MAX_BOX_ATR = 0.0                    # 0 = no box-width filter; else skip days with box > N * ATR(14)
LDN_TREND_FILTER = True                  # H1 EMA200, same helper as the scalper
LDN_SL_MODE = "atr"                      # "atr" | "box_opposite" | "box_mid"
LDN_SL_ATR = 1.5                         # stop distance when LDN_SL_MODE == "atr"
LDN_TP_R = 2.0                           # target = LDN_TP_R x stop distance
LDN_RISK_USD = 5.0
LDN_MAX_TRADES_PER_DAY = 2               # one per pair per day by construction
LDN_MAX_CONSECUTIVE_LOSSES = 4
LDN_MANAGE_POSITIONS = False
LDN_BREAKEVEN_ATR = 1.0
LDN_TRAIL_ATR = 2.0
```

- [ ] **Step 4: Create `london.py`**

```python
"""London-open range breakout, pure functions (no MT5).

Box = high/low of the server day's bars between LDN_BOX_START_HOUR and LDN_BOX_END_HOUR.
Signal = the first closed bar of the day inside [LDN_BOX_END_HOUR, LDN_WINDOW_END_HOUR) whose close
is beyond an edge by the buffer. Exactly one such bar exists per day, so a restart cannot re-enter.
"""
import numpy as np
import pandas as pd

import config
from strategy import Levels, build_levels, trend_allows
from technicals import compute_indicators, compute_trend, attach_trend


def pip_size(point: float, digits: int) -> float:
    """One pip in price units: 10 points on 3- and 5-digit symbols, one point otherwise."""
    return point * 10 if digits in (3, 5) else point


def add_box_columns(df: pd.DataFrame, buffer_price: float) -> pd.DataFrame:
    """Add box_high, box_low, in_window, first_break, box_break. Edges are NaN on days without box bars."""
    t = df["time"]
    day = t.dt.date
    hour = t.dt.hour + t.dt.minute / 60
    in_box = (hour >= config.LDN_BOX_START_HOUR) & (hour < config.LDN_BOX_END_HOUR)
    in_window = (hour >= config.LDN_BOX_END_HOUR) & (hour < config.LDN_WINDOW_END_HOUR)
    df["box_high"] = df["high"].where(in_box).groupby(day).transform("max")
    df["box_low"] = df["low"].where(in_box).groupby(day).transform("min")
    df["in_window"] = in_window
    ok = in_window & df["box_high"].notna() & df["box_low"].notna()
    if config.LDN_MAX_BOX_ATR:
        ok &= (df["box_high"] - df["box_low"]) <= config.LDN_MAX_BOX_ATR * df["atr"]
    up = ok & (df["close"] > df["box_high"] + buffer_price)
    down = ok & (df["close"] < df["box_low"] - buffer_price)
    any_break = up | down
    first = any_break & (any_break.groupby(day).cumsum() == 1)
    df["first_break"] = first
    df["box_break"] = np.where(first & up, "BUY", np.where(first & down, "SELL", ""))
    return df


def london_signal(bar) -> str | None:
    """The day's first break, gated by the H1 trend when LDN_TREND_FILTER is on."""
    side = bar.get("box_break") or ""
    if side not in ("BUY", "SELL"):
        return None
    return side if trend_allows(side, bar["close"], bar.get("trend_ema"), enabled=config.LDN_TREND_FILTER) else None


def london_levels(side: str, ask: float, bid: float, bar) -> Levels | None:
    """Stop by LDN_SL_MODE, target at LDN_TP_R times the stop distance. None when no valid stop exists."""
    atr = float(bar["atr"])
    if config.LDN_SL_MODE == "atr":
        return build_levels(side, ask, bid, atr, config.LDN_SL_ATR, config.LDN_SL_ATR * config.LDN_TP_R)
    hi, lo = float(bar["box_high"]), float(bar["box_low"])
    if np.isnan(hi) or np.isnan(lo):
        return None
    entry = ask if side == "BUY" else bid
    if config.LDN_SL_MODE == "box_opposite":
        sl = lo if side == "BUY" else hi
    else:                                               # "box_mid"
        sl = (hi + lo) / 2
    dist = (entry - sl) if side == "BUY" else (sl - entry)
    if not dist > 0:
        return None
    tp = entry + config.LDN_TP_R * dist if side == "BUY" else entry - config.LDN_TP_R * dist
    return Levels(side, entry, sl, tp, dist)


def london_analyse(df: pd.DataFrame, htf=None, info=None) -> pd.DataFrame:
    """Indicators + box columns (+ H1 EMA when the series is given). `info` supplies point/digits."""
    pip = pip_size(info.point, info.digits) if info is not None else 0.0001
    df = compute_indicators(df)
    df = add_box_columns(df, config.LDN_BUFFER_PIPS * pip)
    if htf is not None:
        df = attach_trend(df, compute_trend(htf))
    return df
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_london.py -q`
Expected: all PASS.

- [ ] **Step 6: Run the whole suite and commit**

Run: `python -m pytest tests -q`

```bash
git add config.py london.py tests/test_london.py
git commit -m "feat(london): pure London-open box breakout rule with LDN_* config

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: London engine profile

**Files:**
- Modify: `engines.py` (`build_engines`, new `london_engine`)
- Test: `tests/test_engines.py`

**Interfaces:**
- Produces: `engines.london_engine() -> Engine` (name `london`, comment `LDN`, callables `london.london_analyse/london_signal/london_levels`, all knobs from `LDN_*`); `build_engines()` appends it when `config.LDN_ENABLED`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_engines.py`:

```python
def test_london_profile_reads_its_own_config(monkeypatch):
    from engines import london_engine
    from london import london_analyse, london_signal, london_levels
    monkeypatch.setattr(config, "LDN_RISK_USD", 3.0, raising=False)
    e = london_engine()
    assert e.name == "london" and e.magic == config.LDN_MAGIC_NUMBER and e.comment == "LDN"
    assert e.symbols == tuple(config.LDN_SYMBOLS) and e.timeframe == config.LDN_TIMEFRAME
    assert e.lookback == config.LDN_RATES_LOOKBACK and e.trend_filter == config.LDN_TREND_FILTER
    assert e.analyse is london_analyse and e.signal is london_signal and e.levels is london_levels
    assert e.risk_usd == 3.0 and e.max_trades_per_day == config.LDN_MAX_TRADES_PER_DAY
    assert e.max_consecutive_losses == config.LDN_MAX_CONSECUTIVE_LOSSES
    assert (e.manage, e.breakeven_atr, e.trail_atr) == (config.LDN_MANAGE_POSITIONS, config.LDN_BREAKEVEN_ATR, config.LDN_TRAIL_ATR)


def test_build_engines_includes_london_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "LDN_ENABLED", True, raising=False)
    engines = build_engines()
    assert [e.name for e in engines] == ["scalper", "london"]
    assert engine_names(engines) == {config.MAGIC_NUMBER: "scalper", config.LDN_MAGIC_NUMBER: "london"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_engines.py -q`
Expected: FAIL with `ImportError: cannot import name 'london_engine'`.

- [ ] **Step 3: Implement in `engines.py`**

Add `from london import london_analyse, london_signal, london_levels` to the imports, then:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_engines.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite and commit**

Run: `python -m pytest tests -q`

```bash
git add engines.py tests/test_engines.py
git commit -m "feat(engines): London breakout profile enabled by LDN_ENABLED

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Backtest `--engine london` end to end

**Files:**
- Test: `tests/test_backtest.py`
- Verify: `backtest.py` (no code change expected; the CLI wiring landed in Task 10)

**Interfaces:**
- Consumes: `engines.london_engine`, `backtest.run_backtest(..., signal=, levels=, ...)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backtest.py`:

```python
def test_london_engine_replays_one_box_break_per_day(monkeypatch):
    from engines import london_engine
    from london import add_box_columns
    for k, v in dict(LDN_BOX_START_HOUR=0, LDN_BOX_END_HOUR=10, LDN_WINDOW_END_HOUR=14, LDN_BUFFER_PIPS=0.0,
                     LDN_MAX_BOX_ATR=0.0, LDN_TREND_FILTER=False, LDN_SL_MODE="atr", LDN_SL_ATR=1.0, LDN_TP_R=2.0,
                     LDN_MAX_TRADES_PER_DAY=2, LDN_MAX_CONSECUTIVE_LOSSES=4, LDN_MANAGE_POSITIONS=False).items():
        monkeypatch.setattr(config, k, v, raising=False)
    monkeypatch.setattr(config, "SESSION_FILTER_ENABLED", False)
    times = pd.date_range("2026-09-07 00:00", periods=24 * 12, freq="5min")     # Monday
    close = pd.Series(1.1000, index=range(len(times)))
    close[times.hour >= 10] = 1.1030                                           # break at 10:00
    close[times.hour >= 11] = 1.1080                                           # runs to the 2R target
    df = pd.DataFrame({"time": times, "open": close, "high": close + 0.0002, "low": close - 0.0002, "close": close})
    df["atr"] = 0.0010
    df = add_box_columns(df, buffer_price=0.0)
    e = london_engine()
    trades = run_backtest(df, "EURUSD", 0.0, 0.00001, 1.0, lambda d: 0.01, signal=e.signal, levels=e.levels,
                          max_trades_per_day=e.max_trades_per_day, max_consecutive_losses=e.max_consecutive_losses,
                          manage=e.manage, be_atr=e.breakeven_atr, trail_atr=e.trail_atr)
    assert len(trades) == 1
    t = trades[0]
    assert t.side == "BUY" and t.entry == pytest.approx(1.1030)
    assert t.sl == pytest.approx(1.1020) and t.tp == pytest.approx(1.1050) and t.reason == "TP"
    assert t.pnl == pytest.approx((1.1050 - 1.1030) / 0.00001 * 1.0 * 0.01)
```

- [ ] **Step 2: Run the test to verify the wiring**

Run: `python -m pytest tests/test_backtest.py -q`
Expected: PASS. If it fails, the likely cause is `add_box_columns` consuming the box on the wrong day or the target arithmetic; fix `london.py`, not the test.

- [ ] **Step 3: Replay the real history and send the digest**

Run (MT5 running): `python backtest.py --engine london --days 180 --telegram --csv logs/backtest_london_180d.csv`
Expected within rounding of the spec's 10:00-14:00 row: EURUSD about 60 trades / +$54, GBPUSD about 63 trades / +$44 (the sliding 180-day window can swap a trade at the first day), and "summary sent to Telegram". Record the actual numbers in the commit message body.

- [ ] **Step 4: Commit**

```bash
git add tests/test_backtest.py
git commit -m "test(backtest): London engine replays one box break per day

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: Dashboard engine tags and per-engine strip

**Files:**
- Modify: `web/index.html:100-110` (tiles), `web/index.html:178-186` (positions table), `web/index.html:190-209` (history filters/table), `web/index.html:362-386` (`renderHistory` + filter listeners), `web/index.html:464-524` (`render`)
- Test: `tests/test_web.py::test_dashboard_scripts_parse` (existing node --check), `tests/test_status.py` (already covers the payload)

**Interfaces:**
- Consumes: `status` JSON fields `engines[]`, `positions[*].engine`, `history[*].engine`, `traders[*].engine`.

- [ ] **Step 1: Add the per-engine strip markup**

After the closing `</div>` of the `.tiles` block (line 110) insert:

```html
  <div id="engine-strip" class="engines"></div>
```

and in the `<style>` block add:

```css
  .engines { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 16px; }
  .engines .eng { border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 12px; color: var(--text-2); }
  .engines .eng b { color: var(--text); }
  .engines .eng.paused { border-color: #c96; }
```

- [ ] **Step 2: Add the engine columns**

Positions table header: insert `<th>Engine</th>` after `<th>Symbol</th>`. History table header: insert `<th class="sort" data-k="engine">Engine</th>` after the Symbol header. History filters: add `<select id="f-engine"><option value="">All engines</option></select>` after the symbol select.

- [ ] **Step 3: Render the new fields**

In `renderHistory`, after `fillSelect("f-reason", ...)` add `fillSelect("f-engine", [...new Set(list.map(t => t.engine || "other"))].sort());`, extend the filter to `&& (!hist.engine || (t.engine || "other") === hist.engine)`, and add `<td><span class="tag">${esc(t.engine || "other")}</span></td>` right after the symbol cell in the row template. Change the listener line to `["symbol", "side", "reason", "engine"].forEach(...)`. Change the state literal at `web/index.html:339` to `const hist = { sortKey: "exit_time", dir: -1, shown: 50, symbol: "", side: "", reason: "", engine: "" };`.

In the positions row template add `<td><span class="tag">${esc(p.engine || "other")}</span></td>` after the symbol cell.

In `render(s)`, after the `$("net-sub").textContent = ...` line, add:

```js
    $("engine-strip").innerHTML = (s.engines || []).map(e => `
      <div class="eng ${e.paused ? "paused" : ""}"><b>${esc(e.name)}</b> · ${esc((e.symbols || []).join(", "))} ·
        entries ${e.entries}/${e.max_entries} · net ${money(e.net_pnl)} · streak ${e.consecutive_losses}/${e.max_consecutive_losses}
        ${e.paused ? " · <b>paused:</b> " + esc(e.paused) : ""}</div>`).join("");
```

and in the symbol cards template show the engine: replace `<div class="name">${esc(t.symbol)} ` with `<div class="name">${esc(t.symbol)} <span class="tag">${esc(t.engine || "scalper")}</span> `.

- [ ] **Step 4: Verify the page script still parses and the suite passes**

Run: `python -m pytest tests/test_web.py tests/test_status.py -q`
Expected: PASS (node --check on the inline script).

Manual check: `python main.py` is not needed; open `web/index.html` against a saved `status.json` if desired. The live check happens in Task 16.

- [ ] **Step 5: Commit**

```bash
git add web/index.html
git commit -m "feat(dashboard): engine tags on positions and history plus a per-engine day strip

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 15: Simulator runs both engines on the scripted symbol

**Files:**
- Modify: `simulate.py:220-262` (`run_simulation`)
- Test: `tests/test_simulate.py`

**Interfaces:**
- Produces: `run_simulation(send_real_telegram=False, log_dir=..., trades=None, seed=1, london=False)`; the result gains `"engines": [names]`. With `london=True` the London engine also runs on `SYMBOL` (`LDN_ENABLED = True`, `LDN_SYMBOLS = [SYMBOL]`); the default keeps `LDN_ENABLED = False` so the two existing tests (scripted counts, four-trade determinism) stay valid. CLI flag `--london`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_simulate.py`:

```python
def test_random_path_can_run_both_engines(tmp_path):
    import config
    result = simulate.run_simulation(send_real_telegram=False, log_dir=str(tmp_path), trades=4, seed=1, london=True)
    assert result["engines"] == ["scalper", "london"]
    magics = {d.magic for d in result["deals"]}
    assert config.MAGIC_NUMBER in magics                    # scalper still trades
    assert magics <= {config.MAGIC_NUMBER, config.LDN_MAGIC_NUMBER}
    outs = [d for d in result["deals"] if d.entry == simulate._real_mt5.DEAL_ENTRY_OUT]
    assert len(outs) >= 4                                   # two engines may close on the same bar


def test_default_run_keeps_the_scalper_alone(tmp_path):
    result = simulate.run_simulation(send_real_telegram=False, log_dir=str(tmp_path))
    assert result["engines"] == ["scalper"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_simulate.py -q`
Expected: FAIL with `TypeError: run_simulation() got an unexpected keyword argument 'london'`.

- [ ] **Step 3: Implement in `simulate.py`**

Change the signature to
`def run_simulation(send_real_telegram: bool = False, log_dir: str = os.path.join("logs", "sim"), trades: int | None = None, seed: int = 1, london: bool = False) -> dict:`
and the overrides to:

```python
    overrides = {"CANDLE_MODE": "off", "NEWS_FILTER_ENABLED": False,     # no network in a dry run
                 "LDN_ENABLED": london, "LDN_SYMBOLS": [SYMBOL]}           # London engine on the scripted symbol
    if not trades:
        overrides.update({"MANAGE_POSITIONS": True, "SESSION_START_HOUR": 0, "SESSION_END_HOUR": 24,
                          "MAX_CONSECUTIVE_LOSSES": 2, "MAX_DAILY_LOSS_USD": 0.1})
    saved = {k: getattr(config, k) for k in overrides}
```

In the return dict add `"engines": [e.name for e in bot.engines]`. In `main_cli` add `ap.add_argument("--london", action="store_true", help="also run the London engine on the simulated symbol")` and pass `london=args.london` to `run_simulation`. The `FakeMT5` needs no change: `positions_get` returns every position and the bot filters by magic; `order_send` already stores `req["magic"]`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_simulate.py -q`
Expected: all PASS (the existing two tests unchanged).

- [ ] **Step 5: Dry-run from the CLI and commit**

Run: `python simulate.py --quiet --trades 40 --london`
Expected: journal prints, some `[london]`-tagged rows may appear, no traceback.

```bash
git add simulate.py tests/test_simulate.py
git commit -m "feat(simulate): random dry run exercises both engines and the combined breaker

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 16: Documentation and demo rollout

**Files:**
- Modify: `claude.md` (Project Overview, architecture diagram, Commands), `docs/superpowers/specs/2026-09-06-london-breakout-engine-design.md` (mark as implemented)
- Deploy: Task Scheduler task `ForexBot`

- [ ] **Step 1: Update `claude.md`**

In "Project Overview" add one sentence: "A second engine, the London-open range breakout (`london.py`, magic 998888, EURUSD/GBPUSD by default), runs in the same loop under its own `Engine` profile (`engines.py`)." In the diagram, replace the `strategy.SymbolTrader.step()` line with:

```text
        └─ engines.build_engines()      Engine profiles: scalper (BB+RSI pin-bar, M5) and london (box breakout, M5)
             └─ strategy.SymbolTrader.step()  per engine x symbol: position? session? news? engine cap? spread? -> signal -> order
                      ├─ scalper: candles.py + technicals.py (M5 BB/RSI/ATR, H1 EMA200)
                      └─ london:  london.py  Asian box 00:00-10:00 server, first break 10:00-14:00, ATR stop, 2R
```

and after the `risk.breaker_reason()` line add `├─ risk.account_breaker / engine_breaker   account-wide daily loss pauses all; loss streak pauses one engine`. In Commands, change the backtest line to:
`python backtest.py [--engine scalper|london] [--symbol XAUUSD ...] --days 60 [--no-trend] [--no-session] [--csv out.csv] [--telegram]`.
Add to Conventions: "Each engine has its own magic number; positions, deals, stats, journal notes and dashboard rows are keyed by it. `execution.KNOWN_MAGICS` lists every running engine."

- [ ] **Step 2: Mark the spec as implemented**

Change the spec's first paragraph from "Draft for review." to "Implemented 2026-09-06 (plan: docs/superpowers/plans/2026-09-06-london-breakout-engine.md)." — adjust the date to the actual day.

- [ ] **Step 3: Run the full suite one last time and commit**

Run: `python -m pytest tests -q`

```bash
git add claude.md docs/superpowers/specs/2026-09-06-london-breakout-engine-design.md
git commit -m "docs: describe the London breakout engine and engine profiles

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 4: Deploy to the demo bot**

Run: `powershell -ExecutionPolicy Bypass -File install_task.ps1 -Restart`
Then within a minute check Telegram for a "Bot started" message listing `scalper: XAUUSD, XAGUSD` and `london: EURUSD, GBPUSD`, and open http://127.0.0.1:8080 to see the engine strip with both engines. Check `logs/bot.log` for the two `START engine=` lines and no `engine london disabled` warning.

- [ ] **Step 5: Start the four-week trial clock**

Note the deployment date in `docs/superpowers/specs/2026-09-06-london-breakout-engine-design.md` section 6. Kill criteria: after 40 closed London trades, profit factor below 0.9 or drawdown above $80 means `LDN_ENABLED = False` and a restart.

---

## Self-review

**Spec coverage:** Section 3.1 (Engine profile) -> Tasks 1, 12. Section 3.2 (rule, config, levels, pip) -> Task 11. Section 3.3 (hybrid risk) -> Tasks 3, 9. Section 3.4 (execution, trailing) -> Tasks 2, 5. Section 3.5 (history, dashboard, reporting) -> Tasks 6, 7, 8, 14. Section 3.6 (backtest, simulation) -> Tasks 10, 13, 15. Section 4 (error isolation) -> Task 9. Section 5 (tests) -> each task's Step 1. Section 6 (rollout) -> Task 16. Spread caps for EURUSD/GBPUSD -> Task 11. Startup message per engine -> Task 9.

**Placeholder scan:** none; every code step carries its code.

**Type consistency:** `Engine` field names (`trend_filter`, `breakeven_atr`, `trail_atr`, `max_trades_per_day`, `max_consecutive_losses`) are used identically in Tasks 1, 2, 4, 5, 9, 10, 12, 13. `bot_positions(symbol=None, magic=None)` in Tasks 2, 4, 5, 9. `sync_deals(store, magics, include_all)` in Tasks 6, 9. `trade_dicts(trades, limit, engine_names)` in Tasks 6, 9. `build_status(..., engines=)` and `engine_block(engine, stats, paused)` in Tasks 7, 9. `Reporter(engine_names)`, `maybe_heartbeat(..., engine_stats)`, `maybe_daily_summary(..., engine_stats)` in Tasks 8, 9. `run_backtest` keyword names in Tasks 10, 13. `analyse(df, htf, info)` in Tasks 1, 4, 10, 11.
