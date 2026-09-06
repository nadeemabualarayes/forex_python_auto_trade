# Trading Analytics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every bot trade from MT5 deal history in SQLite, compute desk-grade statistics, and show them with charts on the existing local/GitHub Pages dashboard.

**Architecture:** `history.py` owns a SQLite store and the incremental MT5 sync; `analytics.py` is pure (deals -> trades -> metrics); `main.Bot` syncs once a minute, caches the analytics, and `status.build_status` embeds them in the snapshot that `web.py` serves and `publisher.py` pushes. `web/index.html` renders KPI tiles, Chart.js charts, and sortable tables from that JSON.

**Tech Stack:** Python 3.11 stdlib (`sqlite3`, `dataclasses`), MetaTrader5 package, pytest, Chart.js 4.4.1 (pinned, cdnjs), vanilla JS.

**Spec:** `docs/superpowers/specs/2026-09-06-trading-analytics-dashboard-design.md`

## Global Constraints
- All times are MT5 server epochs/naive datetimes (`risk.to_server_dt`).
- Everything MT5 returns may be `None`; guard it.
- Pure logic never imports a live terminal; tests run with `tests/conftest.py`'s fake module.
- Nothing on the page may break trading: sync and analytics failures are logged and skipped.
- Chart script URL: `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js`.

---

### Task 1: `history.py` store and sync

**Files:**
- Create: `history.py`
- Modify: `config.py` (after the `WEB_RECENT_TRADES` line)
- Test: `tests/test_history.py`

**Interfaces:**
- Produces: `Deal` dataclass (`ticket, position_id, symbol, type, entry, magic, reason, volume, price, profit, commission, swap, fee, time, order_id, comment`, property `net`), `Deal.from_mt5(obj)`, `TradeStore(path)` with `upsert_deals(deals) -> int`, `last_deal_time() -> int|None`, `deals(magic=None) -> list[Deal]`, `record_equity(time, balance, equity, margin, free_margin, open_pnl)`, `equity_series(since=None, step=3600) -> list[dict]`, `close()`; `sync_deals(store, magic, include_all=False) -> int`; `snapshot_equity(store, open_pnl=0.0, now_epoch=None) -> dict|None`.

- [ ] **Step 1: Write the failing tests** (`tests/test_history.py`)

```python
from types import SimpleNamespace
import MetaTrader5 as mt5
import history
from history import Deal, TradeStore, sync_deals, snapshot_equity

def _deal(ticket, pos, entry, t, profit=0.0, magic=777, **kw):
    base = dict(ticket=ticket, position_id=pos, symbol="XAUUSD", type=mt5.DEAL_TYPE_BUY, entry=entry,
                magic=magic, reason=0, volume=0.1, price=2400.0, profit=profit, commission=-0.1,
                swap=0.0, fee=0.0, time=t, order=ticket, comment="")
    base.update(kw)
    return SimpleNamespace(**base)

def test_store_roundtrip_and_idempotent(tmp_path):
    s = TradeStore(str(tmp_path / "h.db"))
    d = Deal.from_mt5(_deal(1, 1, mt5.DEAL_ENTRY_IN, 1000))
    assert s.upsert_deals([d, d]) == 2 and len(s.deals()) == 1
    assert s.last_deal_time() == 1000
    assert s.deals()[0].net == -0.1

def test_sync_filters_magic_and_uses_incremental_window(tmp_path, monkeypatch):
    s = TradeStore(str(tmp_path / "h.db"))
    calls = []
    def fake_hist(date_from, date_to):
        calls.append(date_from)
        return (_deal(1, 1, mt5.DEAL_ENTRY_IN, 5000), _deal(2, 2, mt5.DEAL_ENTRY_IN, 6000, magic=1))
    monkeypatch.setattr(history.mt5, "history_deals_get", fake_hist)
    assert sync_deals(s, magic=777) == 1
    assert [d.ticket for d in s.deals()] == [1]
    assert calls[0].year == 2000                       # first sync: full history
    sync_deals(s, magic=777)
    assert calls[1].year > 2000                        # second sync: from last deal - 1 day
    assert sync_deals(s, magic=777, include_all=True) == 2

def test_sync_handles_none(tmp_path, monkeypatch):
    s = TradeStore(str(tmp_path / "h.db"))
    monkeypatch.setattr(history.mt5, "history_deals_get", lambda *a: None)
    assert sync_deals(s, magic=777) == 0

def test_equity_snapshot_and_series(tmp_path, monkeypatch):
    s = TradeStore(str(tmp_path / "h.db"))
    monkeypatch.setattr(history.mt5, "account_info", lambda: SimpleNamespace(
        balance=1000.0, equity=1005.0, margin=10.0, margin_free=995.0, currency="USD"))
    row = snapshot_equity(s, open_pnl=5.0, now_epoch=3600)
    assert row["equity"] == 1005.0 and row["currency"] == "USD"
    snapshot_equity(s, now_epoch=3601)                 # same hour bucket -> replaced in series
    snapshot_equity(s, now_epoch=7200)
    series = s.equity_series(step=3600)
    assert [r["time"] for r in series] == [3601, 7200]
    monkeypatch.setattr(history.mt5, "account_info", lambda: None)
    assert snapshot_equity(s) is None
```

- [ ] **Step 2: Run** `python -m pytest tests/test_history.py -q` — expect ImportError.
- [ ] **Step 3: Implement** `history.py` (schema: `deals` keyed by ticket, `equity` keyed by time; `INSERT OR REPLACE`; `equity_series` keeps the last row per `time // step` bucket) and add to `config.py`:

```python
# ── Trade history & analytics ───────────────────────────────────────────────
HISTORY_ENABLED = True
HISTORY_DB = os.path.join(LOG_DIR, "history.db")
HISTORY_SYNC_SECONDS = 60               # deal sync + equity snapshot cadence
HISTORY_INCLUDE_ALL_DEALS = False       # True: every deal on the account, not only this bot's
HISTORY_MAX_TRADES = 500                # closed trades embedded in the page snapshot
```

- [ ] **Step 4: Run** the file again — expect 4 passed. Then `python -m pytest tests -q` — all green.

### Task 2: `analytics.py` pairing and metrics

**Files:**
- Create: `analytics.py`
- Test: `tests/test_analytics.py`

**Interfaces:**
- Consumes: `history.Deal`.
- Produces: `Trade` dataclass (`position_id, symbol, side, volume, entry_time, entry_price, exit_time, exit_price, gross, commission, swap, net, reason, duration_s, hour, weekday`), `pair_trades(deals) -> list[Trade]` (sorted by exit time), `summary(trades, start_balance=None) -> dict`, `breakdown(trades, key) -> dict[str, dict]` for key in `symbol|side|reason|hour|weekday`, `daily_pnl(trades) -> list[dict]`, `equity_curve(trades) -> list[dict]`, `drawdown(curve, start_balance=None) -> tuple[float, float|None]`, `build_analytics(trades, start_balance=None, equity_snapshots=()) -> dict`.

- [ ] **Step 1: Write the failing tests** — hand-computed set: three closed trades (+10, -4 with partial close in two OUT deals, +6), one open position (IN only, must be ignored). Assert pairing (volume-weighted exit price, summed net, reason `TP`/`SL`/`manual`), `summary` values (`trades=3, wins=2, losses=1, win_rate=66.7, net=12.0, gross_profit=16.0, gross_loss=4.0, profit_factor=4.0, expectancy=4.0, payoff_ratio=2.0, max_win_streak=1, max_loss_streak=1, max_drawdown=4.0`), `max_drawdown_pct` with `start_balance=100` equals `4/110*100`, `breakdown(..., "side")` keys, `daily_pnl` grouping, and `profit_factor is None` with no losers.
- [ ] **Step 2: Run** — ImportError.
- [ ] **Step 3: Implement** `analytics.py`. Reason mapping: `DEAL_REASON_SL -> "SL"`, `DEAL_REASON_TP -> "TP"`, `DEAL_REASON_CLIENT|MOBILE|WEB -> "manual"`, `DEAL_REASON_EXPERT -> "bot"`, `DEAL_REASON_SO -> "stopout"`, else `"other"`. Wins are `net > 0`, losses `net < 0`, `breakeven` counted separately; `win_rate = wins / trades * 100`.
- [ ] **Step 4: Run** — all green.

### Task 3: snapshot payload and bot wiring

**Files:**
- Modify: `status.py` (`build_status` gains keyword args `account=None, analytics=None, history=None`)
- Modify: `main.py` (`Bot.__init__`, new `_maybe_sync_history`, `tick`, `_publish`, `run` closes the store)
- Test: `tests/test_status.py` (new test that the blocks are present and JSON-serialisable)

**Interfaces:**
- Consumes: Task 1 and Task 2 functions.
- Produces: snapshot keys `account`, `analytics`, `history`.

- [ ] **Step 1: Test** — `build_status(..., account={"balance": 1.0}, analytics={"summary": {}}, history=[{"net": 1}])` returns those blocks and `json.dumps` succeeds; without kwargs the blocks are `None`/`[]`.
- [ ] **Step 2: Implement.** In `Bot.tick`, call `self._maybe_sync_history()` right after `now = self.clock.now(...)` (before the no-quote early return) so equity snapshots continue on weekends. `start_balance = account["balance"] - sum(t.net for t in trades)` when the account is known.
- [ ] **Step 3: Run** the suite; run `python simulate.py --quiet --trades 3 --seed 1` to prove the simulator still completes with the store active (it writes `logs/sim/history.db`).

### Task 4: dashboard page

**Files:**
- Modify: `web/index.html` (rewrite)
- Test: `tests/test_web.py` still passes (`status.json` string present); headless Chrome screenshot with sample data via the scratch script.

- [ ] **Step 1:** Load Chart.js from the pinned cdnjs URL before the inline script; guard every chart call with `if (window.Chart)` so tables still render offline.
- [ ] **Step 2:** KPI strip: equity (hero, balance beneath), today net, total net, profit factor, expectancy, win rate, max drawdown, open P&L.
- [ ] **Step 3:** Charts: cumulative net line (accent, soft fill), drawdown area (critical red, 20% alpha) beneath it, daily net bars (green/red by sign), net by hour bars, net by weekday bars, net by exit reason horizontal bars. Chart defaults read `--text-2` and `--border` from computed style; re-render on `prefers-color-scheme` change.
- [ ] **Step 4:** Tables: per-symbol stats (trades, win rate, net, PF, expectancy, avg duration, max DD), open positions, trade history with symbol/side/reason filters and click-to-sort headers, journal.
- [ ] **Step 5:** Screenshot with sample data in light and dark; fix anything unreadable.

### Task 5: docs and rollout

- [ ] Update `README.md` (Status page section: what the analytics cover, where the database lives) and `claude.md` (flow diagram lines for `history.py`/`analytics.py`).
- [ ] Full suite green; restart the bot with `install_task.ps1 -Restart` (user runs it if the harness blocks it); confirm `logs/console.log` shows `history: synced N deals` and the page shows charts.

## Self-review
- Spec coverage: data model (T1), pairing and metrics (T2), payload and caching (T3), page (T4), compatibility with simulator (T3 step 3), docs (T5). MAE/MFE explicitly out of scope.
- Types: `Deal`/`Trade` field names are identical across tasks; `build_analytics` returns exactly the `analytics` block the page reads (`summary, by_symbol, by_side, by_reason, by_hour, by_weekday, daily, equity_curve, equity_snapshots`).
