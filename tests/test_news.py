"""News filter: feed parsing, blackout window, refresh/caching. No network access."""
import pytest

import config
from news import Event, NewsFilter, parse_events, blocking_event, next_event

T0 = 1_788_000_000                               # arbitrary epoch


def _row(title, date, country="USD", impact="High"):
    return {"title": title, "country": country, "date": date, "impact": impact, "forecast": "", "previous": ""}


@pytest.fixture(autouse=True)
def news_on(monkeypatch):
    monkeypatch.setattr(config, "NEWS_FILTER_ENABLED", True)
    monkeypatch.setattr(config, "NEWS_CURRENCIES", ("USD",))
    monkeypatch.setattr(config, "NEWS_IMPACTS", ("High",))
    monkeypatch.setattr(config, "NEWS_BLOCK_BEFORE_MIN", 15)
    monkeypatch.setattr(config, "NEWS_BLOCK_AFTER_MIN", 15)
    monkeypatch.setattr(config, "NEWS_STALE_HOURS", 72)
    monkeypatch.setattr(config, "NEWS_BLOCK_WHEN_UNAVAILABLE", False)


class TestParse:
    def test_offset_aware_dates_become_utc_epochs(self):
        ev = parse_events([_row("CPI m/m", "2026-09-11T08:30:00-04:00")])
        assert ev == [Event("CPI m/m", "USD", "High", 1_789_129_800)]      # 12:30 UTC

    def test_filters_currency_impact_and_bad_rows(self):
        rows = [_row("CPI", "2026-09-11T08:30:00-04:00"),
                _row("ECB rate", "2026-09-11T08:15:00-04:00", country="EUR"),
                _row("Medium thing", "2026-09-11T08:30:00-04:00", impact="Medium"),
                _row("Bad date", "not-a-date"), "garbage", {"country": "USD"}]
        assert [e.title for e in parse_events(rows)] == ["CPI"]

    def test_sorted_and_deduplicated(self):
        rows = [_row("B", "2026-09-11T10:00:00+00:00"), _row("A", "2026-09-11T09:00:00+00:00"),
                _row("B", "2026-09-11T10:00:00+00:00")]
        assert [e.title for e in parse_events(rows)] == ["A", "B"]


class TestWindow:
    ev = [Event("NFP", "USD", "High", T0), Event("CPI", "USD", "High", T0 + 7200)]

    def test_window_edges(self):
        assert blocking_event(self.ev, T0 - 900, 900, 900).title == "NFP"     # exactly 15 min before
        assert blocking_event(self.ev, T0 - 901, 900, 900) is None
        assert blocking_event(self.ev, T0 + 899, 900, 900).title == "NFP"
        assert blocking_event(self.ev, T0 + 900, 900, 900) is None            # end is exclusive

    def test_next_event(self):
        assert next_event(self.ev, T0 + 1).title == "CPI"
        assert next_event(self.ev, T0 + 99999) is None


class TestFilter:
    def test_refresh_parses_every_url_and_blocks_in_window(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return [_row("NFP", "2026-09-04T08:30:00-04:00")] if "this" in url else [_row("CPI", "2026-09-11T08:30:00-04:00")]

        nf = NewsFilter(urls=("this", "next"), fetch=fetch)
        assert nf.refresh() is True and calls == ["this", "next"]
        assert [e.title for e in nf.events] == ["NFP", "CPI"]
        cpi = 1_789_129_800
        nf.last_ok = cpi - 7200                     # fetched two hours before the release
        assert "CPI" in nf.block_reason(now_utc=cpi - 600)
        assert nf.block_reason(now_utc=cpi + 900) is None
        snap = nf.snapshot(now_utc=cpi - 3600)
        assert snap["next"]["title"] == "CPI" and snap["next"]["minutes_until"] == 60
        assert snap["blocked"] is None and snap["stale"] is False

    def test_failed_fetch_keeps_cache_and_reports_error(self):
        state = {"fail": False}

        def fetch(url):
            if state["fail"]:
                raise ConnectionError("boom")
            return [_row("NFP", "2026-09-04T08:30:00-04:00")]

        nf = NewsFilter(urls=("u",), fetch=fetch)
        assert nf.refresh()
        state["fail"] = True
        assert nf.refresh() is False
        assert len(nf.events) == 1 and "ConnectionError" in nf.error

    def test_unavailable_calendar_policy(self, monkeypatch):
        nf = NewsFilter(urls=("u",), fetch=lambda u: (_ for _ in ()).throw(RuntimeError("down")))
        nf.refresh()
        assert nf.block_reason(now_utc=T0) is None                           # trade blind by default
        monkeypatch.setattr(config, "NEWS_BLOCK_WHEN_UNAVAILABLE", True)
        assert nf.block_reason(now_utc=T0) == "news calendar unavailable"

    def test_maybe_refresh_honours_interval_and_switch(self, monkeypatch):
        monkeypatch.setattr(config, "NEWS_REFRESH_MINUTES", 60)
        n = {"fetches": 0}

        def fetch(url):
            n["fetches"] += 1
            return []

        nf = NewsFilter(urls=("u",), fetch=fetch)
        assert nf.maybe_refresh(now_mono=0.0) is True
        assert nf.maybe_refresh(now_mono=1000.0) is False
        assert nf.maybe_refresh(now_mono=3600.0) is True
        assert n["fetches"] == 2
        monkeypatch.setattr(config, "NEWS_FILTER_ENABLED", False)
        assert nf.maybe_refresh(now_mono=99999.0) is False
        assert nf.block_reason(now_utc=T0) is None

    def test_one_failing_feed_does_not_discard_the_others(self):
        def fetch(url):
            if url == "bad":
                raise RuntimeError("404")
            return [_row("NFP", "2026-09-04T08:30:00-04:00")]

        nf = NewsFilter(urls=("good", "bad"), fetch=fetch)
        assert nf.refresh() is True
        assert [e.title for e in nf.events] == ["NFP"]
        assert "404" in nf.error and nf.last_ok is not None
