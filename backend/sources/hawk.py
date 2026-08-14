"""hawk.live source: a date-indexed archive of finished series.

GosuGamers only exposes "recent results" as one rolling page, so match history
older than a day or two falls off it.  hawk.live keeps a page per calendar day
(`/dota-2/matches/results/YYYY-MM-DD`) with full team names and series scores,
which lets us walk backwards and build a real result archive.

Like GosuGamers the markup uses hashed class names, so we key off the stable
parts: the match URL slug (tournament + both teams) and the anchor text
(`"Team Falcons 2 LGD Gaming 1 2 - 1"`).
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

from .. import config, fetcher

BASE = "https://hawk.live"
MATCH_HREF = re.compile(r"^/dota-2/matches/(?P<tour>[^/]+)/(?P<slug>[^/]+)/?$")
SERIES_SCORE = re.compile(r"(\d+)\s*-\s*(\d+)\s*$")


def _titleize(slug: str) -> str:
    special = {"og": "OG", "lgd": "LGD", "xg": "XG", "vp": "VP", "ti": "TI"}
    words = []
    for w in slug.split("-"):
        if not w:
            continue
        words.append(special.get(w.lower(), w[:1].upper() + w[1:]))
    return " ".join(words)


def _strip_dupe_suffix(slug: str) -> str:
    """hawk.live appends `-2`, `-4`… to disambiguate repeated fixtures."""
    return re.sub(r"-\d+$", "", slug)


def _parse_row(href: str, text: str) -> dict | None:
    m = MATCH_HREF.match(href)
    if not m:
        return None
    slug = _strip_dupe_suffix(m.group("slug"))
    if "-vs-" not in slug:
        return None

    score = SERIES_SCORE.search(text)
    if not score:                       # not a finished series (live / upcoming)
        return None
    score_a, score_b = int(score.group(1)), int(score.group(2))

    left, _, right = slug.partition("-vs-")
    name_a, name_b = _titleize(left), _titleize(right)

    # The anchor text carries the display names, which are better cased than the
    # slug ("TEAM VISION" vs "Team Vision").  Recover them when the shape matches.
    body = SERIES_SCORE.sub("", text).strip()
    pretty = re.match(r"^(?P<a>.+?)\s+\d+\s+(?P<b>.+?)\s+\d+$", body)
    if pretty:
        name_a, name_b = pretty.group("a").strip(), pretty.group("b").strip()

    return {
        "key": f"hawk:{m.group('tour')}/{m.group('slug')}",
        "tournament": _titleize(m.group("tour")),
        "team_a": name_a,
        "team_b": name_b,
        "score_a": score_a,
        "score_b": score_b,
        "url": BASE + href,
    }


def fetch_results(day: date | None = None, ttl: float | None = None) -> list[dict]:
    """Finished series for one day (or the rolling 'latest results' page)."""
    if day is None:
        path, day_str = "/dota-2/matches/results", None
        ttl = config.TTL_SHORT if ttl is None else ttl
    else:
        day_str = day.isoformat()
        path = f"/dota-2/matches/results/{day_str}"
        # a finished day never changes, so cache it for a long time
        ttl = config.TTL_LONG if ttl is None else ttl

    html = fetcher.get_text(BASE + path, ttl=ttl)
    soup = BeautifulSoup(html, "lxml")

    seen: set[str] = set()
    out: list[dict] = []
    for a in soup.select('a[href*="/dota-2/matches/"]'):
        row = _parse_row(a.get("href", ""), a.get_text(" ", strip=True))
        if not row or row["key"] in seen:
            continue
        seen.add(row["key"])
        row["date"] = day_str
        out.append(row)
    return out


def fetch_recent(days: int = 14) -> tuple[list[dict], list[str]]:
    """Walk back `days` calendar days plus the rolling latest-results page."""
    rows: dict[str, dict] = {}
    errors: list[str] = []

    try:
        for row in fetch_results(None):
            rows[row["key"]] = row
    except fetcher.FetchError as exc:
        errors.append(f"latest: {exc}")

    today = date.today()
    for i in range(days):
        d = today - timedelta(days=i)
        try:
            for row in fetch_results(d):
                # a dated page is more authoritative about *when* it happened
                rows[row["key"]] = row
        except fetcher.FetchError as exc:
            errors.append(f"{d.isoformat()}: {exc}")

    ordered = sorted(rows.values(), key=lambda r: (r.get("date") or "9999", r["key"]), reverse=True)
    return ordered, errors
