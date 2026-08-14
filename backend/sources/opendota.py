"""OpenDota source.

Liquipedia and GosuGamers tell us *who* is at TI 2026 and *when* they play, but
neither publishes machine-readable match durations or hero-level statistics.
OpenDota (free public API over Valve's own match data) supplies the numbers the
prediction model needs: pro match history with durations, drafts, and hero
pick/win rates.
"""
from __future__ import annotations

from .. import config, fetcher

BASE = config.OPENDOTA_API


def heroes() -> list[dict]:
    """Static hero list plus pick/win aggregates."""
    return fetcher.get_json(f"{BASE}/heroStats", ttl=config.TTL_MEDIUM)


def teams() -> list[dict]:
    """Top ~1000 pro teams with OpenDota's own rating."""
    return fetcher.get_json(f"{BASE}/teams", ttl=config.TTL_MEDIUM)


def team_matches(team_id: int) -> list[dict]:
    """Full pro match history for a team (id, duration, opponent, win)."""
    return fetcher.get_json(f"{BASE}/teams/{team_id}/matches", ttl=config.TTL_SHORT)


def team_info(team_id: int) -> dict:
    return fetcher.get_json(f"{BASE}/teams/{team_id}", ttl=config.TTL_MEDIUM)


def team_players(team_id: int) -> list[dict]:
    """Roster history for a team: account_id, nickname, games and wins.

    `is_current_team_member` marks the players OpenDota believes are still on
    the roster; the rest are former members and are kept only so a stand-in can
    still be picked in the UI.
    """
    return fetcher.get_json(f"{BASE}/teams/{team_id}/players", ttl=config.TTL_MEDIUM)


def player_heroes(account_id: int) -> list[dict]:
    """Per-hero games/wins for one player, over every match OpenDota has.

    Includes the player's public games, which is the point: the pro sample
    alone is far too thin to say anything about one player on one hero.
    """
    return fetcher.get_json(f"{BASE}/players/{account_id}/heroes", ttl=config.TTL_MEDIUM)


def pro_matches(less_than_match_id: int | None = None) -> list[dict]:
    url = f"{BASE}/proMatches"
    if less_than_match_id:
        url += f"?less_than_match_id={less_than_match_id}"
    return fetcher.get_json(url, ttl=config.TTL_SHORT)


def match(match_id: int) -> dict:
    """Full match detail — we only keep duration, winner and picks_bans.

    Not cached: the payload is ~300 KB of per-player detail we throw away, and
    `draft_seen` already stops us re-fetching a match we have processed.
    """
    return fetcher.get_json(f"{BASE}/matches/{match_id}", ttl=0, store=False)


def hero_matchups(hero_id: int) -> list[dict]:
    """Games/wins for a hero against every other hero it has faced."""
    return fetcher.get_json(f"{BASE}/heroes/{hero_id}/matchups", ttl=config.TTL_LONG)


def image_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http"):
        return path
    return config.STEAM_CDN + path
