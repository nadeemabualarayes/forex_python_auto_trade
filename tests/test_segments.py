"""Segmented backtest digest: pure helpers over replayed trades."""
import pandas as pd
import pytest

from backtest import SimTrade
from news import Event
from segments import (metrics, segment, cross, session_bucket, direction, month, atr_regime, atr_thresholds,
                      penetration_bucket, news_distance, build_digest, format_digest)


def trade(pnl, side="BUY", when="2026-04-06 09:00", atr=1.0, pen=0.0, r=None):
    return SimTrade("X", side, pd.Timestamp(when), 1.0, 0.0, 2.0, 0.1, pnl=pnl, reason="TP" if pnl > 0 else "SL",
                    atr=atr, penetration=pen, r=pnl if r is None else r)


class TestMetrics:
    def test_full_set_of_fields(self):
        m = metrics([trade(6, r=2.0), trade(-3, r=-1.0), trade(-3, r=-1.0), trade(-3, r=-1.0), trade(9, r=3.0)])
        assert m["trades"] == 5 and m["wins"] == 2 and m["losses"] == 3
        assert m["win_rate"] == 40.0 and m["net"] == 6.0
        assert m["avg_win"] == 7.5 and m["avg_loss"] == -3.0
        assert m["profit_factor"] == pytest.approx(15 / 9, abs=0.01)
        assert m["expectancy"] == 1.2                       # $ per trade
        assert m["expectancy_r"] == pytest.approx(0.4)      # (2 - 1 - 1 - 1 + 3) / 5
        assert m["max_drawdown"] == 9.0
        assert m["max_consecutive_losses"] == 3

    def test_empty(self):
        assert metrics([])["trades"] == 0

    def test_all_winners_has_infinite_pf(self):
        assert metrics([trade(1), trade(2)])["profit_factor"] == float("inf")


class TestLabels:
    def test_session_buckets_are_server_hours(self):
        hours = {"2026-04-06 00:00": "00-07", "2026-04-06 06:59": "00-07", "2026-04-06 07:00": "07-12",
                 "2026-04-06 11:59": "07-12", "2026-04-06 12:00": "12-17", "2026-04-06 17:00": "17-24",
                 "2026-04-06 23:55": "17-24"}
        for when, label in hours.items():
            assert session_bucket(trade(1, when=when)) == label

    def test_direction_and_month(self):
        assert direction(trade(1, side="BUY")) == "LONG" and direction(trade(1, side="SELL")) == "SHORT"
        assert month(trade(1, when="2026-07-30 10:00")) == "2026-07"

    def test_atr_regime_from_thresholds(self):
        assert atr_regime(trade(1, atr=0.5), (1.0, 2.0)) == "LOW"
        assert atr_regime(trade(1, atr=1.0), (1.0, 2.0)) == "NORMAL"
        assert atr_regime(trade(1, atr=2.0), (1.0, 2.0)) == "HIGH"

    def test_atr_thresholds_are_terciles(self):
        assert atr_thresholds([1, 2, 3, 4, 5, 6]) == pytest.approx((2.6667, 4.3333), abs=0.01)
        assert atr_thresholds([]) is None

    def test_penetration_buckets_in_atr_units(self):
        assert penetration_bucket(trade(1, pen=0.0)) == "touch"
        assert penetration_bucket(trade(1, pen=0.09)) == "touch"
        assert penetration_bucket(trade(1, pen=0.2)) == "small"
        assert penetration_bucket(trade(1, pen=0.5)) == "medium"
        assert penetration_bucket(trade(1, pen=0.9)) == "deep"
        assert penetration_bucket(trade(1, pen=None)) == "n/a"

    def test_news_distance_uses_utc_events_against_server_time(self):
        # server clock = UTC+3: a trade at 15:20 server is 12:20 UTC
        release = Event("NFP", "USD", "High", int(pd.Timestamp("2026-04-06 12:30", tz="UTC").timestamp()))
        kw = dict(events=[release], before_s=15 * 60, after_s=15 * 60, near_s=3600, server_offset_s=3 * 3600)
        assert news_distance(trade(1, when="2026-04-06 15:20"), **kw) == "news window"
        assert news_distance(trade(1, when="2026-04-06 14:50"), **kw) == "near news"   # 40 min before
        assert news_distance(trade(1, when="2026-04-06 09:00"), **kw) == "safe"
        assert news_distance(trade(1, when="2026-06-01 09:00"), **kw) == "no calendar"
        assert news_distance(trade(1), events=[], before_s=1, after_s=1) == "no calendar"


class TestSegmentation:
    def test_segment_groups_in_label_order(self):
        ts = [trade(5, side="BUY"), trade(-2, side="SELL"), trade(3, side="SELL")]
        out = segment(ts, direction, order=("LONG", "SHORT"))
        assert list(out) == ["LONG", "SHORT"]
        assert out["LONG"]["trades"] == 1 and out["SHORT"]["net"] == 1.0

    def test_segment_skips_empty_labels_unless_ordered(self):
        out = segment([trade(1, side="BUY")], direction, order=("LONG", "SHORT"))
        assert out["SHORT"]["trades"] == 0
        assert list(segment([trade(1, side="BUY")], direction)) == ["LONG"]

    def test_cross_tab(self):
        ts = [trade(5, side="BUY", when="2026-04-06 08:00"), trade(-2, side="SELL", when="2026-04-06 08:00"),
              trade(3, side="BUY", when="2026-04-06 13:00")]
        out = cross(ts, session_bucket, direction)
        assert out[("07-12", "LONG")]["net"] == 5.0
        assert out[("07-12", "SHORT")]["net"] == -2.0
        assert out[("12-17", "LONG")]["trades"] == 1
        assert ("12-17", "SHORT") not in out


class TestDigest:
    def test_sections_and_thresholds(self):
        ts = [trade(5, atr=0.5, when="2026-04-06 08:00"), trade(-2, atr=1.5, side="SELL", when="2026-05-06 13:00"),
              trade(3, atr=2.5, pen=0.7, when="2026-05-07 20:00")]
        d = build_digest(ts)
        for key in ("overall", "by_session", "by_direction", "by_atr_regime", "by_month", "by_news",
                    "by_penetration", "session_x_direction", "session_x_atr", "direction_x_atr"):
            assert key in d, key
        assert d["overall"]["trades"] == 3
        assert d["atr_thresholds"] == pytest.approx(atr_thresholds([0.5, 1.5, 2.5]))
        assert d["by_atr_regime"]["LOW"]["trades"] == 1 and d["by_atr_regime"]["HIGH"]["trades"] == 1
        assert d["by_month"]["2026-05"]["trades"] == 2
        assert d["by_news"] == {"no calendar": metrics(ts)}
        assert d["by_penetration"]["deep"]["net"] == 3.0

    def test_explicit_atr_thresholds_and_events(self):
        ts = [trade(5, atr=0.5)]
        d = build_digest(ts, atr_thresholds=(1.0, 2.0), events=[Event("x", "USD", "High", 0)])
        assert d["atr_thresholds"] == (1.0, 2.0)
        assert list(d["by_atr_regime"]) == ["LOW", "NORMAL", "HIGH"]

    def test_empty_digest(self):
        d = build_digest([])
        assert d["overall"]["trades"] == 0 and d["by_session"] == {}

    def test_format_is_plain_text_tree(self):
        ts = [trade(5, when="2026-04-06 08:00"), trade(-2, side="SELL", when="2026-04-06 13:00")]
        text = format_digest("XAUUSD", 180, build_digest(ts))
        assert text.startswith("XAUUSD - 180 DAYS")
        for header in ("OVERALL", "BY SESSION", "BY DIRECTION", "BY ATR REGIME", "BY MONTH", "BY NEWS DISTANCE",
                       "BY BB PENETRATION", "SESSION x DIRECTION", "SESSION x ATR", "DIRECTION x ATR"):
            assert header in text, header
        assert "07-12" in text and "LONG" in text and "expR" in text
        assert "<" not in text                              # console/file text, no HTML
