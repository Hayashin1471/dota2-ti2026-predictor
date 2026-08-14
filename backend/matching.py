"""Resolving the same team across Liquipedia, GosuGamers and OpenDota.

The three sources spell teams differently ("TEAM VISION" / "VISION",
"LGD Gaming" / "PSG.LGD", "Iron Wing" / "1win Team").  This module normalises
names and resolves them against OpenDota's team table.
"""
from __future__ import annotations

import re
import time
import unicodedata
from difflib import SequenceMatcher

# Words that carry no identity on their own.
_NOISE = {"team", "esports", "esport", "gaming", "club", "the", "e", "sports", "pro"}

# Hand-maintained aliases for cases fuzzy matching cannot get right, keyed by
# normalised name -> list of alternative normalised names to try on OpenDota.
ALIASES: dict[str, list[str]] = {
    "lgd": ["psglgd", "lgd", "lgdgaming"],
    "ironwing": ["1win", "1winteam", "tundra", "tundraesports", "ironwing"],
    "vision": ["vision", "teamvision"],
    "yandex": ["yandex", "teamyandex", "bb", "bbteam"],
    "aurora": ["aurora", "auroragaming"],
    "betboom": ["betboom", "betboomteam", "boomboys"],
    "boomboys": ["boomboys", "betboom", "betboomteam"],
    "nigmagalaxy": ["nigmagalaxy", "nigma"],
    "xtreme": ["xtremegaming", "xtreme", "xg"],
    "spirit": ["teamspirit", "spirit"],
    "falcons": ["teamfalcons", "falcons"],
    "liquid": ["teamliquid", "liquid"],
    "resilience": ["teamresilience", "resilience"],
    "vici": ["vicigaming", "vici", "vg"],
    "huligani": ["huligani", "huligan"],
    "gamerlegion": ["gamerlegion", "gl"],
    "og": ["og"],
}


def normalize(name: str) -> str:
    """Lowercase, strip accents, punctuation and whitespace."""
    if not name:
        return ""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def core_tokens(name: str) -> set[str]:
    """Identity-bearing tokens, e.g. "Team Falcons" -> {"falcons"}."""
    words = re.split(r"[^a-zA-Z0-9]+", name.lower())
    toks = {w for w in words if w and w not in _NOISE}
    return toks or {w for w in words if w}


def core_key(name: str) -> str:
    return "".join(sorted(core_tokens(name))) if core_tokens(name) else normalize(name)


def _candidates(name: str) -> list[str]:
    """Normalised strings worth trying for a given display name."""
    out = [normalize(name), "".join(sorted(core_tokens(name))), "".join(core_tokens(name))]
    for key in (normalize(name), "".join(core_tokens(name))):
        out.extend(ALIASES.get(key, []))
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def resolve(name: str, index: dict[str, dict], min_ratio: float = 0.86) -> tuple[dict | None, str]:
    """Find the OpenDota team for `name`.

    `index` maps normalised name/tag -> team dict.  Returns (team, how).
    """
    for cand in _candidates(name):
        if cand in index:
            return index[cand], "exact"

    # same identity tokens, different decoration: "Iron Wing" / "Iron Wing Esports".
    # Equality only -- a subset match would happily pair "Team Spirit" with
    # "Team Spirit Academy".
    want = core_tokens(name)
    if want:
        for team in index.values():
            if core_tokens(team["name"]) == want:
                return team, "tokens"

    best, best_ratio = None, 0.0
    target = normalize(name)
    for key, team in index.items():
        ratio = SequenceMatcher(None, target, key).ratio()
        if ratio > best_ratio:
            best, best_ratio = team, ratio
    if best is not None and best_ratio >= min_ratio:
        return best, f"fuzzy:{best_ratio:.2f}"
    return None, "unresolved"


def build_index(od_teams: list[dict], active_within_days: int = 400) -> dict[str, dict]:
    """Normalised-name index over OpenDota teams.

    Org names get recycled: OpenDota has two "LGD Gaming" rows, one dormant
    since 2024 and one playing today.  Currently-active teams therefore win a
    name collision, and only then does the higher rating break the tie.
    """
    cutoff = time.time() - active_within_days * 86400
    index: dict[str, dict] = {}
    ranked = sorted(
        od_teams,
        key=lambda t: (0 if (t.get("last_match_time") or 0) >= cutoff else 1,
                       -(t.get("rating") or 0)),
    )
    for team in ranked:
        name = (team.get("name") or "").strip()
        if not name:
            continue
        keys = {normalize(name), "".join(sorted(core_tokens(name)))}
        tag = (team.get("tag") or "").strip()
        if tag:
            keys.add(normalize(tag))
        for key in keys:
            if key and key not in index:
                index[key] = team
    return index


def slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "team"
