"""Dry run: drive the real bot loop with a fake MetaTrader5 terminal and a scripted price path.

    python simulate.py            # sends SIMULATION-prefixed alerts to Telegram
    python simulate.py --quiet    # print alerts instead of sending them

Scenario (XAUUSD, Monday, server time): uptrend above the H1 EMA200.
  1. dip -> BUY -> rally through breakeven and trailing stop -> take profit
  2. dip -> BUY -> keeps falling -> stop loss -> re-entry -> stop loss
     (the day net goes negative; the scripted $0.10 daily-loss limit trips the account
     circuit breaker on the second loss, pre-empting the engine-level loss-streak pause)
  3. clock runs to 23:05 -> daily summary
--trades N replaces the script with a seeded random multi-day path and stops after N closed trades.
Each loop pass advances one M5 bar instead of sleeping.
"""
import argparse
import calendar
import csv
import math
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

PREFIX = "\U0001F9EA SIMULATION\n"
BASE = 2400.0
SPREAD = 0.30
SYMBOL = "XAUUSD"

try:
    import MetaTrader5 as _real_mt5
except ImportError:                      # non-Windows: supply the constants ourselves
    _real_mt5 = SimpleNamespace(
        TIMEFRAME_M5=5, TIMEFRAME_H1=16385,
        ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, POSITION_TYPE_BUY=0, POSITION_TYPE_SELL=1,
        DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1,
        DEAL_ENTRY_IN=0, DEAL_ENTRY_OUT=1, DEAL_ENTRY_INOUT=2, DEAL_ENTRY_OUT_BY=3,
        DEAL_REASON_SL=7, DEAL_REASON_TP=8,
        TRADE_ACTION_DEAL=1, TRADE_ACTION_SLTP=6, ORDER_TIME_GTC=0,
        ORDER_FILLING_FOK=0, ORDER_FILLING_IOC=1, ORDER_FILLING_RETURN=2,
        TRADE_RETCODE_DONE=10009,
    )


# -- Scripted price path ----------------------------------------------------------
def _bars(closes, start: datetime, step_min: int, spread_pts: int):
    out, prev = [], closes[0]
    for k, c in enumerate(closes):
        o = prev
        t = start + timedelta(minutes=step_min * k)
        out.append({"time": calendar.timegm(t.timetuple()), "open": o,
                    "high": max(o, c) + 0.2, "low": min(o, c) - 0.2, "close": c,
                    "tick_volume": 100, "spread": spread_pts, "real_volume": 0})
        prev = c
    return out


def build_scenario():
    """Return (m5_bars, h1_bars, warmup_index). Times are server wall-clock epochs."""
    def noise(n, level, phase=0):
        return [level + math.sin((phase + k) / 2.5) for k in range(n)]

    closes = noise(120, BASE)                                    # 00:00 -> 10:00 warm-up
    # episode 1: one-bar dip (signal), then a rally through breakeven, trail, and TP
    lvl = closes[-1]
    closes += [lvl - 6] + [lvl - 6 + k for k in range(1, 9)]     # -5 ... +2
    closes += noise(30, closes[-1], 7)
    # episode 2: dip (signal) then keep falling: first BUY stops out, the re-entry on the
    # next oversold bar stops out too -> day net goes negative -> account circuit breaker
    # (the scripted daily-loss limit is tiny, so it trips before any engine-level streak pause)
    lvl = closes[-1]
    closes += [lvl - 6 - k for k in range(0, 10)]                # -6 ... -15
    # flat until 23:05 so the daily summary fires
    total = 23 * 12 + 2
    closes += noise(total - len(closes), closes[-1], 11)

    monday = datetime(2026, 9, 7, 0, 0)
    m5 = _bars(closes, monday, 5, int(SPREAD * 100))
    h1_closes = [BASE - 200 + 190 * k / 599 for k in range(600)]
    h1 = _bars(h1_closes, monday - timedelta(hours=600), 60, int(SPREAD * 100))
    return m5, h1, 120


def build_random_scenario(days: int = 40, seed: int = 1):
    """Seeded random walk over `days` consecutive weekdays: mean-reverting noise around a slow
    drift plus occasional sharp spikes, so Bollinger touches with RSI extremes keep occurring in
    both directions. H1 history is flat at BASE, so the EMA200 filter lets price pick the side."""
    import random
    rng = random.Random(seed)
    per_day = 24 * 12
    closes, level, prev, spike = [], BASE, BASE, 0
    for _ in range(days * per_day + 120):
        level += rng.gauss(0, 0.05)
        if spike == 0 and rng.random() < 0.02:
            spike = rng.choice([-1, 1]) * rng.randint(4, 8)     # sign = direction, |n| = bars left
        step = rng.gauss(0, 0.5) + 0.03 * (level - prev)
        if spike:
            step += 1.4 * (1 if spike > 0 else -1)
            spike -= 1 if spike > 0 else -1
        prev = round(prev + step, 2)
        closes.append(prev)

    monday = datetime(2026, 9, 7, 0, 0)
    m5 = []
    day = monday
    warm = _bars(closes[:120], monday - timedelta(minutes=600), 5, int(SPREAD * 100))
    m5 += warm
    for d in range(days):
        while day.weekday() > 4:                                 # skip Saturday / Sunday
            day += timedelta(days=1)
        chunk = closes[120 + d * per_day: 120 + (d + 1) * per_day]
        m5 += _bars(chunk, day, 5, int(SPREAD * 100))
        day += timedelta(days=1)
    h1 = _bars([BASE] * 600, monday - timedelta(hours=600), 60, int(SPREAD * 100))
    return m5, h1, 120


# -- Fake terminal ----------------------------------------------------------------
class FakeMT5:
    """Just enough of the MetaTrader5 API for the bot loop. Constants fall through to the real package."""

    def __init__(self, m5, h1, magic):
        self.m5, self.h1, self.magic = m5, h1, magic
        self.i = 0                       # index of the *forming* bar
        self.positions = []
        self.deals = []
        self._ticket = 1000
        self.info = SimpleNamespace(
            name=SYMBOL, digits=2, point=0.01, trade_tick_value=0.1, trade_tick_size=0.01,
            volume_min=0.01, volume_max=100.0, volume_step=0.01, filling_mode=3,
            trade_stops_level=0, trade_contract_size=100.0)

    def __getattr__(self, name):
        return getattr(_real_mt5, name)

    # -- clock / price -----
    @property
    def now(self):
        return self.m5[self.i]["time"]

    @property
    def bid(self):
        return self.m5[self.i]["open"]

    @property
    def ask(self):
        return self.bid + SPREAD

    def advance(self):
        self.i += 1
        self._broker_check()

    def _broker_check(self):
        for p in list(self.positions):
            if p.type == _real_mt5.POSITION_TYPE_BUY:
                hit = ("SL", p.sl) if p.sl and self.bid <= p.sl else ("TP", p.tp) if p.tp and self.bid >= p.tp else None
            else:
                hit = ("SL", p.sl) if p.sl and self.ask >= p.sl else ("TP", p.tp) if p.tp and self.ask <= p.tp else None
            if hit:
                self._close(p, hit[1], hit[0])

    def _close(self, p, price, why):
        sign = 1 if p.type == _real_mt5.POSITION_TYPE_BUY else -1
        profit = sign * (price - p.price_open) / self.info.trade_tick_size * self.info.trade_tick_value * p.volume
        self._ticket += 1
        self.deals.append(SimpleNamespace(
            ticket=self._ticket, position_id=p.ticket, time=self.now, symbol=p.symbol, magic=p.magic,
            entry=_real_mt5.DEAL_ENTRY_OUT,
            type=_real_mt5.DEAL_TYPE_SELL if sign == 1 else _real_mt5.DEAL_TYPE_BUY,
            reason=_real_mt5.DEAL_REASON_SL if why == "SL" else _real_mt5.DEAL_REASON_TP,
            volume=p.volume, price=price, profit=round(profit, 2), commission=0.0, swap=0.0, fee=0.0))
        self.positions.remove(p)

    # -- API surface used by the bot -----
    def initialize(self, *a, **k): return True
    def shutdown(self): return None
    def terminal_info(self): return SimpleNamespace(connected=True)
    def last_error(self): return (0, "ok")
    def symbol_select(self, symbol, enable=True): return symbol == SYMBOL
    def symbol_info(self, symbol): return self.info if symbol == SYMBOL else None

    def symbol_info_tick(self, symbol):
        if symbol != SYMBOL:
            return None
        return SimpleNamespace(time=self.now, time_msc=self.now * 1000, bid=self.bid, ask=self.ask)

    def copy_rates_from_pos(self, symbol, timeframe, start, n):
        if symbol != SYMBOL:
            return None
        if timeframe == _real_mt5.TIMEFRAME_H1:
            return self.h1[-n:]
        return self.m5[max(0, self.i + 1 - n): self.i + 1]

    def positions_get(self, symbol=None):
        return tuple(p for p in self.positions if symbol is None or p.symbol == symbol)

    def history_deals_get(self, date_from, date_to):
        return tuple(self.deals)

    def order_send(self, req):
        if req["action"] == _real_mt5.TRADE_ACTION_SLTP:
            for p in self.positions:
                if p.ticket == req["position"]:
                    p.sl, p.tp = req["sl"], req["tp"]
                    return SimpleNamespace(retcode=_real_mt5.TRADE_RETCODE_DONE, order=p.ticket, comment="done")
            return SimpleNamespace(retcode=10013, order=0, comment="position not found")
        self._ticket += 1
        is_buy = req["type"] == _real_mt5.ORDER_TYPE_BUY
        price = self.ask if is_buy else self.bid
        pos = SimpleNamespace(
            ticket=self._ticket, symbol=req["symbol"], magic=req["magic"],
            type=_real_mt5.POSITION_TYPE_BUY if is_buy else _real_mt5.POSITION_TYPE_SELL,
            price_open=price, sl=req["sl"], tp=req["tp"], volume=req["volume"], profit=0.0)
        self.positions.append(pos)
        self.deals.append(SimpleNamespace(
            ticket=self._ticket, position_id=self._ticket, time=self.now, symbol=req["symbol"],
            magic=req["magic"], entry=_real_mt5.DEAL_ENTRY_IN,
            type=_real_mt5.DEAL_TYPE_BUY if is_buy else _real_mt5.DEAL_TYPE_SELL, reason=0,
            volume=req["volume"], price=price, profit=0.0, commission=0.0, swap=0.0, fee=0.0))
        return SimpleNamespace(retcode=_real_mt5.TRADE_RETCODE_DONE, order=self._ticket, comment="done")


# -- Wiring ---------------------------------------------------------------------------
def run_simulation(send_real_telegram: bool = False, log_dir: str = os.path.join("logs", "sim"),
                   trades: int | None = None, seed: int = 1, london: bool = False) -> dict:
    """Scripted scenario by default; with `trades`, a random multi-day path that stops once
    that many positions have closed (or the path runs out)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config
    config.LOG_DIR = log_dir
    config.LOG_FILE = os.path.join(log_dir, "bot.log")
    config.TRADE_JOURNAL = os.path.join(log_dir, "trades.csv")
    os.makedirs(log_dir, exist_ok=True)
    if os.path.exists(config.TRADE_JOURNAL):
        os.remove(config.TRADE_JOURNAL)

    import journal, telegram_notifier, execution, risk, strategy, position_manager, reporting, main
    journal.setup_logging()

    m5, h1, warmup = build_random_scenario(seed=seed) if trades else build_scenario()
    # The simulator exercises the bot mechanics with the plain BB+RSI rule (synthetic bars have no
    # realistic wicks for candlestick patterns); the scripted day also forces breakeven/trail on
    # and a tiny daily-loss limit so the account circuit breaker trips as soon as the day nets
    # negative -- under the hybrid risk policy a loss streak alone only pauses that one engine,
    # so the account breaker is what demonstrates the circuit-breaker path here.
    overrides = {"CANDLE_MODE": "off", "NEWS_FILTER_ENABLED": False,     # no network in a dry run
                 "LDN_ENABLED": london, "LDN_SYMBOLS": [SYMBOL]}           # London engine on the scripted symbol
    if not trades:
        overrides.update({"MANAGE_POSITIONS": True, "SESSION_START_HOUR": 0, "SESSION_END_HOUR": 24,
                          "MAX_CONSECUTIVE_LOSSES": 2, "MAX_DAILY_LOSS_USD": 0.1})
    saved = {k: getattr(config, k) for k in overrides}
    config.__dict__.update(overrides)
    try:
        fake = FakeMT5(m5, h1, config.MAGIC_NUMBER)
        fake.i = warmup
        for mod in (execution, risk, strategy, position_manager, reporting, main):
            mod.mt5 = fake

        sent = []
        real_send = telegram_notifier.send_telegram

        def sim_send(message: str):
            message = PREFIX + message
            sent.append(message)
            if send_real_telegram:
                real_send(message)
            else:
                journal.log.info("TELEGRAM >> %s", message.replace("\n", " | "))
        for mod in (execution, reporting, main):
            mod.send_telegram = sim_send

        bot = main.Bot([SYMBOL])
        breaker_tripped = False
        def closed():
            return sum(1 for d in fake.deals if d.entry == _real_mt5.DEAL_ENTRY_OUT)

        while fake.i < len(m5) - 1:
            bot.tick()
            breaker_tripped = breaker_tripped or bot.breaker_alerted
            if trades and closed() >= trades:
                break
            fake.advance()
        bot.tick()

        rows = []
        if os.path.exists(config.TRADE_JOURNAL):
            with open(config.TRADE_JOURNAL, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        return {"journal": rows, "telegram": sent, "breaker_tripped": breaker_tripped,
                "deals": fake.deals, "log_dir": log_dir, "engines": [e.name for e in bot.engines]}
    finally:
        config.__dict__.update(saved)


def main_cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true", help="do not send Telegram messages")
    ap.add_argument("--trades", type=int, help="random multi-day path; stop after this many closed trades")
    ap.add_argument("--seed", type=int, default=1, help="random seed for --trades")
    ap.add_argument("--london", action="store_true", help="also run the London engine on the simulated symbol")
    args = ap.parse_args()
    res = run_simulation(send_real_telegram=not args.quiet, trades=args.trades, seed=args.seed, london=args.london)
    print("\n== journal ==")
    for r in res["journal"]:
        print(f"{r['time']}  {r['event']:<9} {r['side']:<4} lot={r['lot']:<5} price={r['price']:<8} "
              f"sl={r['sl']:<8} tp={r['tp']:<8} pnl={r['pnl']:<6} {r['note']}")
    outs = [d for d in res["deals"] if d.entry == _real_mt5.DEAL_ENTRY_OUT]
    wins = [d for d in outs if d.profit > 0]
    print(f"\n== {len(outs)} closed trades: {len(wins)}W / {len(outs) - len(wins)}L, "
          f"net ${sum(d.profit for d in outs):.2f} ==")
    print(f"{len(res['telegram'])} Telegram messages "
          f"{'sent' if not args.quiet else 'printed'}; breaker tripped: {res['breaker_tripped']}")
    print(f"log: {os.path.join(res['log_dir'], 'bot.log')}")


if __name__ == "__main__":
    main_cli()
