"""Polite HTTP layer: per-host rate limiting plus an on-disk response cache.

Every outbound request goes through here so we never hammer Liquipedia or
GosuGamers, and so a second refresh in the same hour is nearly free.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import urlsplit

import httpx

from . import config, db

log = logging.getLogger("fetcher")

_host_lock = threading.Lock()
_last_hit: dict[str, float] = {}


class FetchError(RuntimeError):
    pass


def _throttle(host: str) -> None:
    delay = config.RATE_LIMITS.get(host, 0.5)
    while True:
        with _host_lock:
            now = time.monotonic()
            wait = _last_hit.get(host, 0.0) + delay - now
            if wait <= 0:
                _last_hit[host] = now
                return
        time.sleep(min(wait, delay))


def _headers(url: str) -> dict[str, str]:
    host = urlsplit(url).hostname or ""
    if host.endswith("liquipedia.net"):
        # Liquipedia rejects requests without gzip and without a real UA.
        return {
            "User-Agent": config.LIQUIPEDIA_UA,
            "Accept-Encoding": "gzip",
            "Accept": "application/json",
        }
    return {
        "User-Agent": config.BROWSER_UA,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _cache_get(url: str, ttl: float) -> str | None:
    if ttl <= 0:
        return None
    row = db.one("SELECT fetched_at, status, body FROM http_cache WHERE url = ?", (url,))
    if row and row["status"] == 200 and time.time() - row["fetched_at"] < ttl:
        return row["body"]
    return None


def _cache_put(url: str, status: int, body: str) -> None:
    db.execute(
        "INSERT INTO http_cache(url, fetched_at, status, body) VALUES (?,?,?,?) "
        "ON CONFLICT(url) DO UPDATE SET fetched_at=excluded.fetched_at, "
        "status=excluded.status, body=excluded.body",
        (url, time.time(), status, body),
    )


def get_text(url: str, ttl: float = config.TTL_SHORT, retries: int = 2,
             store: bool = True) -> str:
    """Fetch a URL.

    `store=False` skips the response cache.  Use it for large one-shot bodies
    (a single OpenDota match detail is ~300 KB and we only keep a handful of
    fields from it) -- caching those would grow the database by gigabytes.
    """
    if store:
        cached = _cache_get(url, ttl)
        if cached is not None:
            return cached

    host = urlsplit(url).hostname or ""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        _throttle(host)
        try:
            with httpx.Client(timeout=45, follow_redirects=True) as client:
                resp = client.get(url, headers=_headers(url))
            if resp.status_code == 200:
                if store:
                    _cache_put(url, 200, resp.text)
                return resp.text
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise FetchError(f"HTTP {resp.status_code} for {url}")
        except httpx.HTTPError as exc:  # network-level problem
            last_err = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise FetchError(f"{type(exc).__name__}: {exc} for {url}") from exc
    raise FetchError(f"failed to fetch {url}: {last_err}")


def get_json(url: str, ttl: float = config.TTL_SHORT, retries: int = 2, store: bool = True):
    text = get_text(url, ttl=ttl, retries=retries, store=store)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # A bad body should not be cached forever.
        db.execute("DELETE FROM http_cache WHERE url = ?", (url,))
        raise FetchError(f"invalid JSON from {url}: {exc}") from exc


def compact(keep_days: float = 7.0) -> dict:
    """Drop bulky/expired cache rows and reclaim the file on disk."""
    before = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
    cutoff = time.time() - keep_days * 86400
    db.execute("DELETE FROM http_cache WHERE url LIKE ? OR fetched_at < ?",
               (f"{config.OPENDOTA_API}/matches/%", cutoff))
    conn = db.connect()
    conn.commit()
    conn.execute("VACUUM")
    after = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
    return {"before_mb": round(before / 1e6, 1), "after_mb": round(after / 1e6, 1),
            "freed_mb": round((before - after) / 1e6, 1)}


def clear_cache(prefix: str | None = None) -> int:
    if prefix:
        rows = db.query("SELECT COUNT(*) c FROM http_cache WHERE url LIKE ?", (prefix + "%",))
        db.execute("DELETE FROM http_cache WHERE url LIKE ?", (prefix + "%",))
    else:
        rows = db.query("SELECT COUNT(*) c FROM http_cache")
        db.execute("DELETE FROM http_cache")
    return rows[0]["c"] if rows else 0
