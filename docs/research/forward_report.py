"""Forward-validation report for the scalp-test bot (read-only research tool, not part of the bot).

    python docs/research/forward_report.py            # run from the scalp-test worktree

Reads logs/history.db (deals), logs/trades.csv (ENTRY/EXIT/SKIP rows) and logs/bot.log (SIGNAL lines,
sizing warnings, errors), reconstructs ATR regime and Bollinger penetration from M1 history at each
signal bar, and prints per-trade rows plus the aggregate breakdowns. Manual "[test]" / "TEST-" orders
are excluded. Trades before the sizing fix restart (FIX_TIME) are labelled pre-fix and reported apart.
"""
import csv
import os
import re
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import MetaTrader5 as mt5                       # noqa: E402
import config                                   # noqa: E402
from analytics import pair_trades               # noqa: E402
from execution import mt5_init_args, lot_for_loss   # noqa: E402
from history import Deal                        # noqa: E402
from technicals import compute_indicators       # noqa: E402

FIX_TIME = datetime(2026, 9, 7, 14, 26, 39)     # server time the terminal-priced sizing went live
SYMBOL = config.SYMBOLS[0]
MAGIC = config.MAGIC_NUMBER
BUDGET = config.RISK_USD_PER_TRADE
REGIME_DAYS = 30                                # ATR terciles come from this much M1 history


def server_dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)


def session_bucket(h: int) -> str:
    return "00-07" if h < 7 else "07-12" if h < 12 else "12-17" if h < 17 else "17-24"


def penetration_bucket(p) -> str:
    if p is None:
        return "n/a"
    return "touch" if p < 0.1 else "small" if p < 0.3 else "medium" if p < 0.6 else "deep"


# -- sources --------------------------------------------------------------------------
def journal_rows():
    path = config.TRADE_JOURNAL
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def log_lines():
    out = []
    for name in sorted(os.listdir(config.LOG_DIR)):
        if name.startswith("bot.log"):
            with open(os.path.join(config.LOG_DIR, name), encoding="utf-8", errors="replace") as f:
                out.extend(f.read().splitlines())
    return out


SIGNAL_RE = re.compile(r"^(\S+ \S+) INFO\s+\[(\w+)\] (\w+) SIGNAL (BUY|SELL) bar=(\S+ \S+) close=(\S+) rsi=(\S+) atr=(\S+)")
EXEC_RE = re.compile(r"^(\S+ \S+) INFO\s+\[(\w+)\] EXECUTED (BUY|SELL) lot=(\S+) entry=(\S+) sl=(\S+) tp=(\S+) ticket=(\d+)")


def signal_context(lines):
    """order ticket -> dict(bar, atr, rsi) from the SIGNAL line that immediately preceded its EXECUTED line."""
    ctx, pending = {}, {}
    for line in lines:
        m = SIGNAL_RE.match(line)
        if m:
            pending[m.group(2)] = dict(bar=datetime.strptime(m.group(5), "%Y-%m-%d %H:%M:%S"),
                                       atr=float(m.group(8)), rsi=float(m.group(7)))
            continue
        m = EXEC_RE.match(line)
        if m and m.group(2) in pending:
            ctx[int(m.group(8))] = pending.pop(m.group(2))
    return ctx


# -- indicator reconstruction ----------------------------------------------------------
def m1_series(days: int):
    end = datetime.now(timezone.utc) + timedelta(days=1)
    rates = mt5.copy_rates_range(SYMBOL, config.TIMEFRAME, end - timedelta(days=days), end)
    if rates is None or len(rates) == 0:
        return None
    import pandas as pd
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return compute_indicators(df)


def bar_context(df, bar_time, side):
    """(atr, penetration in ATR) for the signal bar, or (None, None) when the bar is not in the series."""
    if df is None:
        return None, None
    hit = df.index[df["time"] == np.datetime64(bar_time)]
    if len(hit) == 0:
        return None, None
    row = df.loc[hit[0]]
    atr = float(row["atr"])
    band = float(row["lower_band"] if side == "BUY" else row["upper_band"])
    if np.isnan(atr) or np.isnan(band) or atr <= 0:
        return atr if not np.isnan(atr) else None, None
    beyond = (band - row["close"]) if side == "BUY" else (row["close"] - band)
    return atr, round(max(0.0, float(beyond) / atr), 3)


# -- metrics -----------------------------------------------------------------------------
def metrics(rows):
    if not rows:
        return dict(trades=0, wins=0, losses=0, win_rate=0.0, net=0.0, pf=0.0, exp=0.0, exp_r=0.0, dd=0.0, streak=0)
    pnls = np.array([r["net"] for r in rows])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    eq = np.concatenate([[0.0], np.cumsum(pnls)])
    rs = [r["r"] for r in rows if r["r"] is not None]
    streak = worst = 0
    for p in pnls:
        streak = streak + 1 if p <= 0 else 0
        worst = max(worst, streak)
    gl = -losses.sum()
    return dict(trades=len(rows), wins=int(len(wins)), losses=int(len(losses)),
                win_rate=round(len(wins) / len(rows) * 100, 1), net=round(float(pnls.sum()), 2),
                pf=round(float(wins.sum() / gl), 2) if gl > 0 else float("inf"),
                exp=round(float(pnls.mean()), 2), exp_r=round(float(np.mean(rs)), 2) if rs else 0.0,
                dd=round(float((np.maximum.accumulate(eq) - eq).max()), 2), streak=int(worst))


def mrow(label, m):
    pf = "inf" if m["pf"] == float("inf") else f"{m['pf']:.2f}"
    return (f"{label:<26}{m['trades']:>6}{m['wins']:>5}{m['losses']:>5}{m['win_rate']:>7.1f}{m['net']:>+9.2f}"
            f"{pf:>6}{m['exp']:>+8.2f}{m['exp_r']:>+7.2f}{m['dd']:>8.2f}{m['streak']:>7}")


MHEAD = f"{'':<26}{'trades':>6}{'wins':>5}{'loss':>5}{'win%':>7}{'net':>9}{'PF':>6}{'exp$':>8}{'expR':>7}{'maxDD':>8}{'streak':>7}"


def section(title, groups):
    print(title)
    print(MHEAD)
    for label, rows in groups.items():
        print(mrow(label, metrics(rows)))
    print()


# -- main ----------------------------------------------------------------------------------
def main():
    args, kw = mt5_init_args()
    if not mt5.initialize(*args, **kw):
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    acct = mt5.account_info()
    mt5.symbol_select(SYMBOL, True)
    info = mt5.symbol_info(SYMBOL)
    df = m1_series(REGIME_DAYS)
    raw = mt5.history_deals_get(0, 2**31 - 1) or ()
    mt5.shutdown()
    atr_all = df["atr"].dropna().values if df is not None else np.array([])
    cuts = tuple(np.quantile(atr_all, [1 / 3, 2 / 3])) if len(atr_all) else None

    # Deals straight from the terminal, not the bot's history.db: the bot syncs only deals carrying its magic,
    # so a position closed by hand (mobile/desktop, magic 0 on the OUT deal) never reaches the database and
    # would vanish from the pairing. Keep every deal of a position whose opening deal is the bot's.
    all_deals = [Deal.from_mt5(d) for d in raw if d.symbol == SYMBOL]
    bot_positions = {d.position_id for d in all_deals
                     if d.magic == MAGIC and d.entry == 0 and not d.comment.upper().startswith("TEST")}
    deals = [d for d in all_deals if d.position_id in bot_positions]
    trades = [t for t in pair_trades(deals) if t.symbol == SYMBOL]
    journal = journal_rows()
    entries = {int(r["ticket"]): r for r in journal if r["event"] == "ENTRY" and r["ticket"] and "[test]" not in r["note"]}
    lines = log_lines()
    ctx = signal_context(lines)

    rows = []
    for t in sorted(trades, key=lambda t: t.entry_time):
        when = server_dt(t.entry_time)
        e = entries.get(t.position_id, {})
        sl = float(e["sl"]) if e.get("sl") else None
        stop = abs(t.entry_price - sl) if sl else None
        lot = t.volume
        loss_per_lot = stop * info.trade_contract_size if stop else None          # USD-quoted metal: contract x move
        risk_at_stop = round(loss_per_lot * lot, 2) if loss_per_lot else None
        expected_lot = lot_for_loss(loss_per_lot, BUDGET, info.volume_min, info.volume_max, info.volume_step) if loss_per_lot else None
        prefix = when < FIX_TIME
        source = "field (pre-fix)" if prefix else "terminal"          # post-fix XAUUSD can only be terminal-priced or skipped
        c = ctx.get(t.position_id, {})
        atr, pen = bar_context(df, c.get("bar"), t.side) if c.get("bar") else (c.get("atr"), None)
        regime = ("LOW" if atr < cuts[0] else "HIGH" if atr >= cuts[1] else "NORMAL") if (atr is not None and cuts) else "n/a"
        rows.append(dict(
            when=when, hour=when.hour, side="LONG" if t.side == "BUY" else "SHORT", entry=t.entry_price, stop=stop,
            lot=lot, expected_lot=expected_lot, risk_at_stop=risk_at_stop, net=t.net, reason=t.reason,
            r=round(t.net / risk_at_stop, 2) if risk_at_stop else None, source=source, prefix=prefix,
            atr=atr, regime=regime, pen=pen, pen_bucket=penetration_bucket(pen), session=session_bucket(when.hour),
            sizing_ok=(expected_lot is not None and abs(expected_lot - lot) < 1e-9),
        ))

    since_fix = [ln for ln in lines if ln[:19] >= FIX_TIME.strftime("%Y-%m-%d %H:%M:%S")]
    skips_minlot = [ln for ln in since_fix if "min lot" in ln and "would risk" in ln]
    skips_unavail = [ln for ln in since_fix if "could not price" in ln]
    fallbacks = [ln for ln in since_fix if "tick_value" in ln.lower() and "verified against the terminal" in ln]
    wrong_field = [ln for ln in since_fix if "is wrong" in ln and "sized from the terminal only" in ln]
    errors = [ln for ln in since_fix if " ERROR " in ln or "Traceback" in ln]
    warnings = [ln for ln in since_fix if " WARNING " in ln]
    breaker = [ln for ln in since_fix if "breaker" in ln.lower() or "paused" in ln.lower()]
    journal_skips = [r for r in journal if r["event"] == "SKIP" and r["time"] >= FIX_TIME.strftime("%Y-%m-%d %H:%M:%S")]
    starts = [ln for ln in since_fix if "START engine" in ln]

    now = datetime.now()
    print(f"FORWARD VALIDATION  {SYMBOL}  magic {MAGIC}  account {acct.login}  balance {acct.balance:.2f}  "
          f"generated {now:%Y-%m-%d %H:%M} (local = server on this host)")
    print(f"sizing fix live since {FIX_TIME} server; risk budget ${BUDGET:.2f}; profile: {'M1' if config.TIMEFRAME == 1 else config.TIMEFRAME} "
          f"rsi {config.RSI_OVERSOLD}/{config.RSI_OVERBOUGHT} sl/tp {config.SL_ATR_MULTIPLIER}/{config.TP_ATR_MULTIPLIER} ATR "
          f"trend={config.TREND_FILTER_ENABLED} candles={config.CANDLE_MODE} manage={config.MANAGE_POSITIONS}")
    if cuts:
        print(f"ATR regime cut-offs (terciles of {REGIME_DAYS}-day M1 ATR): LOW below {cuts[0]:.3f}, HIGH from {cuts[1]:.3f}")
    print(f"contract {info.trade_contract_size:g}, tick {info.trade_tick_size:g}, reported tick value {info.trade_tick_value} "
          f"(terminal-priced: {info.trade_contract_size * info.trade_tick_size:g})\n")

    print("PER-TRADE (strategy-generated, manual [test] orders excluded)")
    print(f"{'server time':<17}{'side':<6}{'entry':>9}{'stop':>7}{'lot':>6}{'expLot':>7}{'risk$':>7}{'net$':>8}{'R':>6}"
          f"{'exit':<7}{'source':<16}{'atr':>6}{'regime':<8}{'pen':>6}{'bucket':<8}{'sess':<6}{'sizing'}")
    for r in rows:
        print(f"{r['when']:%Y-%m-%d %H:%M}  {r['side']:<6}{r['entry']:>9.2f}{(r['stop'] or 0):>7.2f}{r['lot']:>6.2f}"
              f"{(r['expected_lot'] if r['expected_lot'] is not None else 0):>7.2f}{(r['risk_at_stop'] or 0):>7.2f}"
              f"{r['net']:>+8.2f}{(r['r'] if r['r'] is not None else 0):>+6.2f} {r['reason']:<7}{r['source']:<16}"
              f"{(r['atr'] or 0):>6.2f} {r['regime']:<8}{(r['pen'] if r['pen'] is not None else -1):>6.2f} {r['pen_bucket']:<8}{r['session']:<6}"
              f"{'ok' if r['sizing_ok'] else 'MISMATCH' if r['expected_lot'] is not None else '?'}")
    if not rows:
        print("  (no strategy-generated closed trades yet)")
    print()

    manual = [r for r in rows if r["reason"] == "manual"]
    post = [r for r in rows if not r["prefix"] and r["reason"] != "manual"]
    pre = [r for r in rows if r["prefix"] and r["reason"] != "manual"]
    print(f"strategy trades: {len(rows)} total = {len(pre)} pre-fix (oversized, excluded from the forward set) "
          f"+ {len(post)} post-fix + {len(manual)} closed by hand (excluded: the exit was not the strategy's)")
    for r in manual:
        print(f"    MANUAL CLOSE {r['when']:%Y-%m-%d %H:%M} {r['side']} entry {r['entry']:.2f} net {r['net']:+.2f}")
    print(f"post-fix sizing: {sum(r['sizing_ok'] for r in post)} of {len(post)} lots equal the terminal-priced lot for ${BUDGET:.2f}; "
          f"risk at stop {[r['risk_at_stop'] for r in post]}")
    print(f"since fix: {len(skips_minlot)} min-lot skips, {len(skips_unavail)} 'could not price' skips, "
          f"{len(journal_skips)} journal SKIP rows, {len(fallbacks)} field-verified lines, {len(wrong_field)} wrong-field warnings, "
          f"{len(starts)} engine starts, {len(errors)} errors/tracebacks, {len(warnings)} warnings, {len(breaker)} breaker/pause lines\n")

    if post:
        section("POST-FIX OVERALL", {"all": post})
        section("BY DIRECTION", OrderedDict((d, [r for r in post if r["side"] == d]) for d in ("LONG", "SHORT")))
        section("BY SESSION", OrderedDict((s, [r for r in post if r["session"] == s]) for s in ("00-07", "07-12", "12-17", "17-24")))
        section("BY ATR REGIME", OrderedDict((g, [r for r in post if r["regime"] == g]) for g in ("LOW", "NORMAL", "HIGH")))
        section("BY PENETRATION", OrderedDict((b, [r for r in post if r["pen_bucket"] == b]) for b in ("touch", "small", "medium", "deep", "n/a")))
        section("17-24 LONG vs OTHER LONG vs 17-24 SHORT", OrderedDict([
            ("17-24 LONG", [r for r in post if r["side"] == "LONG" and r["session"] == "17-24"]),
            ("other LONG", [r for r in post if r["side"] == "LONG" and r["session"] != "17-24"]),
            ("17-24 SHORT", [r for r in post if r["side"] == "SHORT" and r["session"] == "17-24"]),
            ("other SHORT", [r for r in post if r["side"] == "SHORT" and r["session"] != "17-24"])]))
    if pre:
        section("PRE-FIX (for the record only)", {"pre-fix": pre})

    for title, ls in (("sizing / pricing warnings since fix", [ln for ln in warnings if "tick" in ln.lower() or "price" in ln.lower() or "lot" in ln.lower()]),
                      ("errors since fix", errors), ("breaker / pause lines since fix", breaker)):
        print(title + ":")
        for ln in ls[-10:]:
            print("   ", ln[:160])
        if not ls:
            print("    none")
    print()


if __name__ == "__main__":
    main()
