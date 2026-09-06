"""TradeStore round-trips MT5 deals through SQLite; sync is incremental and magic-filtered."""
from datetime import datetime, timedelta, timezone
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
    assert s.upsert_deals([d, d]) == 2
    assert len(s.deals()) == 1
    assert s.last_deal_time() == 1000
    assert s.deals()[0].net == -0.1
    assert s.deals(magic=1) == []
    s.close()


def test_from_mt5_tolerates_missing_optional_fields():
    d = Deal.from_mt5(SimpleNamespace(ticket=5, position_id=5, symbol="XAGUSD", type=1, entry=1, magic=7,
                                      volume=0.5, price=30.0, profit=1.5, time=42))
    assert d.reason == 0 and d.commission == 0.0 and d.comment == "" and d.order_id == 0


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
    assert calls[1] == datetime.fromtimestamp(5000, timezone.utc) - timedelta(days=1)   # overlap window
    assert sync_deals(s, magic=777, include_all=True) == 2
    assert len(s.deals()) == 2


def test_sync_handles_none(tmp_path, monkeypatch):
    s = TradeStore(str(tmp_path / "h.db"))
    monkeypatch.setattr(history.mt5, "history_deals_get", lambda *a: None)
    assert sync_deals(s, magic=777) == 0


def test_equity_snapshot_and_series(tmp_path, monkeypatch):
    s = TradeStore(str(tmp_path / "h.db"))
    monkeypatch.setattr(history.mt5, "account_info", lambda: SimpleNamespace(
        balance=1000.0, equity=1005.0, margin=10.0, margin_free=995.0, currency="USD"))
    row = snapshot_equity(s, open_pnl=5.0, now_epoch=3600)
    assert row["equity"] == 1005.0 and row["currency"] == "USD" and row["open_pnl"] == 5.0
    snapshot_equity(s, now_epoch=3601)                 # same hour bucket -> only the last one is kept
    snapshot_equity(s, now_epoch=7200)
    series = s.equity_series(step=3600)
    assert [r["time"] for r in series] == [3601, 7200]
    assert s.equity_series(since=7000, step=3600) and s.equity_series(since=7000)[0]["time"] == 7200
    monkeypatch.setattr(history.mt5, "account_info", lambda: None)
    assert snapshot_equity(s) is None
