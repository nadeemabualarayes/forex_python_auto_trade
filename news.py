"""Economic-calendar blackout: no new entries around high-impact news releases.

Events come from the Forex Factory weekly JSON feed (this week + next week), filtered to
config.NEWS_CURRENCIES / NEWS_IMPACTS. Times in the feed carry a UTC offset, so everything
here is compared in UTC epoch seconds against the real wall clock: a release happens at a real
moment in time, independent of the broker's server-time convention.

The feed is refreshed every NEWS_REFRESH_MINUTES; on failure the last good copy is kept until
it is older than NEWS_STALE_HOURS, after which NEWS_BLOCK_WHEN_UNAVAILABLE decides whether the
bot trades blind or stands aside. Pure helpers (parse_events, blocking_event, next_event) are
testable without network access.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

import config
from journal import log

FEED_URLS = ("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
             "https://nfs.faireconomy.media/ff_calendar_nextweek.json")


@dataclass(frozen=True)
class Event:
    title: str
    currency: str
    impact: str
    time_utc: int                       # epoch seconds

    def when(self) -> str:
        return datetime.fromtimestamp(self.time_utc, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _to_epoch(value: str) -> int | None:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def parse_events(raw, currencies=None, impacts=None) -> list:
    """Feed rows -> sorted Events, keeping only the wanted currencies / impact levels."""
    currencies = set(currencies if currencies is not None else config.NEWS_CURRENCIES)
    impacts = set(impacts if impacts is not None else config.NEWS_IMPACTS)
    out = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        if row.get("country") not in currencies or row.get("impact") not in impacts:
            continue
        t = _to_epoch(row.get("date", ""))
        if t is None:
            continue
        out.append(Event(str(row.get("title", "")).strip() or "?", row["country"], row["impact"], t))
    return sorted(set(out), key=lambda e: e.time_utc)


def blocking_event(events, now_utc: float, before_s: float, after_s: float):
    """The event whose [time - before, time + after) window contains now_utc, else None."""
    for e in events:
        if e.time_utc - before_s <= now_utc < e.time_utc + after_s:
            return e
    return None


def next_event(events, now_utc: float):
    for e in events:
        if e.time_utc >= now_utc:
            return e
    return None


def _http_fetch(url: str):
    r = requests.get(url, timeout=10, headers={"User-Agent": "forex-python-auto-trade/1.0"})
    r.raise_for_status()
    return r.json()


class NewsFilter:
    def __init__(self, urls=None, fetch=None):
        self.urls = tuple(urls) if urls is not None else config.NEWS_URLS
        self.fetch = fetch or _http_fetch
        self.events: list = []
        self.last_attempt: float | None = None      # time.monotonic()
        self.last_ok: float | None = None           # time.time()
        self.error: str | None = None

    # -- refresh -------------------------------------------------------------------
    def maybe_refresh(self, now_mono: float | None = None) -> bool:
        """Fetch when enabled and the refresh interval has elapsed. Returns True when a fetch ran."""
        if not config.NEWS_FILTER_ENABLED:
            return False
        now = time.monotonic() if now_mono is None else now_mono
        if self.last_attempt is not None and now - self.last_attempt < config.NEWS_REFRESH_MINUTES * 60:
            return False
        self.last_attempt = now
        self.refresh()
        return True

    def refresh(self) -> bool:
        """Synchronous fetch of every feed URL. Keeps the previous events on any failure."""
        try:
            rows = []
            for url in self.urls:
                rows.extend(self.fetch(url))
            self.events = parse_events(rows)
            self.last_ok, self.error = time.time(), None
            nxt = next_event(self.events, time.time())
            log.info("news: %d %s %s events loaded; next %s", len(self.events),
                     "/".join(config.NEWS_CURRENCIES), "/".join(config.NEWS_IMPACTS).lower(),
                     f"{nxt.title} at {nxt.when()}" if nxt else "none scheduled")
            return True
        except Exception as e:                       # network, HTTP, JSON: never break the loop
            self.error = f"{type(e).__name__}: {e}"
            log.warning("news: calendar fetch failed (%s); keeping %d cached events", self.error, len(self.events))
            return False

    # -- queries -------------------------------------------------------------------
    def stale(self, now_utc: float | None = None) -> bool:
        now = time.time() if now_utc is None else now_utc
        return self.last_ok is None or now - self.last_ok > config.NEWS_STALE_HOURS * 3600

    def block_reason(self, now_utc: float | None = None) -> str | None:
        """Why entries are blocked right now, or None."""
        if not config.NEWS_FILTER_ENABLED:
            return None
        now = time.time() if now_utc is None else now_utc
        if self.stale(now):
            return "news calendar unavailable" if config.NEWS_BLOCK_WHEN_UNAVAILABLE else None
        e = blocking_event(self.events, now, config.NEWS_BLOCK_BEFORE_MIN * 60, config.NEWS_BLOCK_AFTER_MIN * 60)
        if e is None:
            return None
        return f"news blackout: {e.title} ({e.currency}) at {e.when()}"

    def snapshot(self, now_utc: float | None = None, upcoming: int = 5) -> dict:
        """JSON-friendly state for the dashboard."""
        now = time.time() if now_utc is None else now_utc
        nxt = next_event(self.events, now)
        return {
            "enabled": bool(config.NEWS_FILTER_ENABLED),
            "blocked": self.block_reason(now),
            "window_minutes": [config.NEWS_BLOCK_BEFORE_MIN, config.NEWS_BLOCK_AFTER_MIN],
            "next": {"title": nxt.title, "currency": nxt.currency, "time": nxt.when(),
                     "minutes_until": int((nxt.time_utc - now) // 60)} if nxt else None,
            "upcoming": [{"title": e.title, "currency": e.currency, "time": e.when()}
                         for e in self.events if e.time_utc >= now][:upcoming],
            "last_ok": datetime.fromtimestamp(self.last_ok, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if self.last_ok else None,
            "stale": self.stale(now),
            "error": self.error,
        }
