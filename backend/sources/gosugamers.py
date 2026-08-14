"""GosuGamers source: TI 2026 schedule, live matches and results.

GosuGamers renders with hashed CSS class names, so instead of relying on the
markup we key off the stable parts: the match URL slug (which carries both team
names) and the anchor's text content (which carries the stage, the score or the
countdown).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import config, fetcher

MATCH_HREF = re.compile(r"^/dota2/tournaments/(?P<tslug>[^/]+)/matches/(?P<mid>\d+)-(?P<slug>.+)$")
SCORE = re.compile(r"(\d+)\s*:\s*(\d+)")
COUNTDOWN = re.compile(r"\b\d+\s*(?:d|h|m)\b", re.I)


def _soup(path: str, ttl: float) -> BeautifulSoup:
    html = fetcher.get_text(config.GOSU_BASE + path, ttl=ttl)
    return BeautifulSoup(html, "lxml")


def _titleize(slug: str) -> str:
    small = {"of", "the", "and"}
    words = []
    for w in slug.split("-"):
        if not w:
            continue
        if w.lower() in {"og", "lgd", "bb", "xg", "ti", "vp", "psg"}:
            words.append(w.upper())
        elif words and w in small:
            words.append(w)
        else:
            words.append(w[:1].upper() + w[1:])
    return " ".join(words)


def _split_versus(slug: str) -> tuple[str, str] | None:
    """`team-falcons-vs-lgd-gaming` -> ("Team Falcons", "LGD Gaming")."""
    if "-vs-" not in slug:
        return None
    left, _, right = slug.partition("-vs-")
    return _titleize(left), _titleize(right)


def find_ti_tournament(ttl: float = config.TTL_MEDIUM) -> str | None:
    """Locate the TI 2026 tournament slug rather than hard-coding an id."""
    for path in ("/dota2/matches", "/dota2/tournaments", "/dota2"):
        try:
            soup = _soup(path, ttl)
        except fetcher.FetchError:
            continue
        for a in soup.select('a[href*="/dota2/tournaments/"]'):
            href = a.get("href", "")
            m = re.match(r"^/dota2/tournaments/([^/]+)", href)
            if m and config.GOSU_TI_SLUG_HINT in m.group(1):
                return m.group(1)
    return None


def _parse_match_anchors(soup: BeautifulSoup, only_tournament: str | None) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for a in soup.select('a[href*="/matches/"]'):
        href = a.get("href", "")
        m = MATCH_HREF.match(href)
        if not m:
            continue
        if only_tournament and m.group("tslug") != only_tournament:
            continue
        key = m.group("mid")
        if key in seen:
            continue
        seen.add(key)

        pair = _split_versus(m.group("slug"))
        if not pair:
            continue
        text = a.get_text(" ", strip=True)

        score_a = score_b = None
        status = "scheduled"
        sm = SCORE.search(text)
        if sm:
            score_a, score_b = int(sm.group(1)), int(sm.group(2))
            status = "finished"
        elif re.search(r"\bLive\b", text, re.I):
            status = "live"
        elif COUNTDOWN.search(text):
            status = "upcoming"

        stage = text
        for marker in (" Data ", " Live ", " VS "):
            stage = stage.split(marker)[0]
        stage = SCORE.split(stage)[0].strip()

        out.append({
            "match_key": key,
            "team_a": pair[0],
            "team_b": pair[1],
            "score_a": score_a,
            "score_b": score_b,
            "status": status,
            "stage": stage[:120],
            "url": config.GOSU_BASE + href,
            "raw": text[:300],
        })
    return out


def fetch_ti_schedule(tournament_slug: str | None = None, ttl: float = config.TTL_SHORT) -> dict:
    """Upcoming + finished TI 2026 matches, plus everything else on the pages."""
    slug = tournament_slug or find_ti_tournament(ttl=config.TTL_MEDIUM)

    matches: dict[str, dict] = {}
    paths = ["/dota2/matches", "/dota2/matches/results"]
    if slug:
        paths.insert(0, f"/dota2/tournaments/{slug}")
        paths.insert(1, f"/dota2/tournaments/{slug}/matches")

    errors: list[str] = []
    for path in paths:
        try:
            soup = _soup(path, ttl)
        except fetcher.FetchError as exc:
            errors.append(f"{path}: {exc}")
            continue
        for row in _parse_match_anchors(soup, slug):
            matches[row["match_key"]] = row

    ordered = sorted(matches.values(), key=lambda r: (r["status"] != "live", r["match_key"]))
    return {"tournament_slug": slug, "matches": ordered, "errors": errors}


def fetch_team_names(schedule: dict) -> list[str]:
    """Distinct team names GosuGamers shows for the tournament."""
    names: set[str] = set()
    for m in schedule.get("matches", []):
        names.add(m["team_a"])
        names.add(m["team_b"])
    return sorted(names)
