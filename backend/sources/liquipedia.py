"""Liquipedia (Dota 2 wiki) source.

Uses the public MediaWiki `action=parse` endpoint to read the raw wikitext of
`The_International/2026` and pulls out the tournament overview plus the
participant list with rosters.  Everything goes through `fetcher`, which sets
the descriptive User-Agent and gzip encoding Liquipedia's API terms require.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from .. import config, fetcher


def _api_url(page: str) -> str:
    return (
        f"{config.LIQUIPEDIA_API}?action=parse&page={quote(page, safe='')}"
        "&prop=wikitext&format=json&formatversion=2"
    )


def fetch_wikitext(page: str = config.LIQUIPEDIA_PAGE, ttl: float = config.TTL_MEDIUM) -> str:
    data = fetcher.get_json(_api_url(page), ttl=ttl)
    if "error" in data:
        raise fetcher.FetchError(f"Liquipedia error for {page}: {data['error'].get('info')}")
    parse = data.get("parse") or {}
    wikitext = parse.get("wikitext")
    if isinstance(wikitext, dict):       # formatversion=1 shape
        wikitext = wikitext.get("*")
    if not wikitext:
        raise fetcher.FetchError(f"no wikitext returned for {page}")
    return wikitext


# --------------------------------------------------------------------------
# tiny wikitext helpers
# --------------------------------------------------------------------------

def _extract_template(text: str, name: str) -> str | None:
    """Return the body of the first `{{name ...}}` template, brace-balanced."""
    start = text.find("{{" + name)
    if start == -1:
        return None
    depth = 0
    i = start
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return text[start:i]
            continue
        i += 1
    return text[start:]


def _split_top_level(body: str) -> list[str]:
    """Split a template body on `|` that are not nested inside {{ }} or [[ ]]."""
    parts, buf, depth, sq = [], [], 0, 0
    i = 0
    inner = body[2:-2] if body.startswith("{{") and body.endswith("}}") else body
    while i < len(inner):
        two = inner[i:i + 2]
        if two == "{{":
            depth += 1; buf.append(two); i += 2; continue
        if two == "}}":
            depth -= 1; buf.append(two); i += 2; continue
        if two == "[[":
            sq += 1; buf.append(two); i += 2; continue
        if two == "]]":
            sq -= 1; buf.append(two); i += 2; continue
        ch = inner[i]
        if ch == "|" and depth == 0 and sq == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts]


def _clean(value: str) -> str:
    """Strip wiki markup down to plain text."""
    value = re.sub(r"<ref[^>]*>.*?</ref>", "", value, flags=re.S)
    value = re.sub(r"<ref[^>]*/>", "", value)
    value = re.sub(r"\{\{!\}\}", "|", value)
    value = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", value)
    value = re.sub(r"\[\[([^\]]*)\]\]", r"\1", value)
    value = re.sub(r"'''?", "", value)
    value = re.sub(r"<br\s*/?>", " / ", value)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _named(parts: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in parts:
        if "=" in p:
            k, _, v = p.partition("=")
            k = k.strip()
            if k and not k.startswith("{{"):
                out[k] = v.strip()
    return out


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

def parse_overview(wikitext: str) -> dict:
    """Tournament header info from the `Infobox league` template."""
    box = _extract_template(wikitext, "Infobox league")
    if not box:
        return {}
    f = _named(_split_top_level(box))
    return {
        "name": _clean(f.get("name", "The International 2026")),
        "short_name": _clean(f.get("shortname", "TI 15")),
        "organizer": " / ".join(
            _clean(f[k]) for k in ("organizer", "organizer2", "organizer3") if f.get(k)
        ),
        "patch": _clean(f.get("patch", "")),
        "country": _clean(f.get("country", "")),
        "city": _clean(f.get("city", "")),
        "venue": _clean(f.get("venue1", "")),
        "team_number": _clean(f.get("team_number", "")),
        "format": _clean(f.get("format", "")),
        "start_date": _clean(f.get("sdate", "")),
        "end_date": _clean(f.get("edate", "")),
        "website": _clean(f.get("website", "")),
        "tier": _clean(f.get("liquipediatier", "")),
    }


_ROLE_LABELS = {
    "1": "Carry", "2": "Mid", "3": "Offlane", "4": "Soft support", "5": "Hard support",
    "coach": "Coach", "head coach": "Head coach", "assistant coach": "Assistant coach",
}

# Liquipedia disambiguates page titles; the display name drops the suffix.
_TITLE_SUFFIX = re.compile(r"\s+(TI\s*20\d\d|\(.*\))$", re.I)


def parse_participants(wikitext: str) -> list[dict]:
    """The 16 TI teams with rosters and how they qualified."""
    block = _extract_template(wikitext, "TeamParticipants")
    if not block:
        return []

    teams: list[dict] = []
    for part in _split_top_level(block):
        if not part.startswith("{{Opponent"):
            continue
        fields = _split_top_level(_extract_template(part, "Opponent") or part)
        # first positional argument is the team name
        positional = [p for p in fields if "=" not in p.split("{{")[0]]
        raw_name = _clean(positional[1]) if len(positional) > 1 else ""
        if not raw_name:
            continue
        named = _named(fields)

        players = []
        for m in re.finditer(r"\{\{Person\|(?P<body>[^{}]*)\}\}", part):
            body = m.group("body")
            if "status=former" in body:          # ex-players stay off the roster
                continue
            role = re.search(r"role=([^|}]*)", body)
            # the player name is the first positional argument
            fields = [f for f in body.split("|") if f and "=" not in f]
            if not fields:
                continue
            role_key = (role.group(1).strip().lower() if role else "")
            players.append({
                "role": _ROLE_LABELS.get(role_key, role_key.title() or "Player"),
                "name": _clean(fields[0]),
            })

        qual_raw = named.get("qualification", "")
        method = re.search(r"method=([^|}]*)", qual_raw)
        region = re.search(r"text=([^|}]*)", qual_raw)
        placement = re.search(r"placement=([^|}]*)", qual_raw)
        method_txt = (method.group(1).strip() if method else "").lower()
        if method_txt == "invite":
            qualification = "Direct invite"
        elif region:
            place = f" #{placement.group(1).strip()}" if placement else ""
            qualification = f"{region.group(1).strip()} qualifier{place}"
        else:
            qualification = method_txt.title() or "Unknown"

        teams.append({
            "page_name": raw_name,
            "name": _TITLE_SUFFIX.sub("", raw_name).strip(),
            "qualification": qualification,
            "region": region.group(1).strip() if region else ("Invited" if method_txt == "invite" else ""),
            "players": players,
        })
    return teams


def parse_main_event(wikitext: str) -> dict:
    """The Main Event bracket: eight teams, and every slot with its round name.

    The bracket template numbers its slots `R1M1`, `R2M3`, ... which says where
    a match sits in the tree but not what the round is called.  The round names
    live in the HTML comments Liquipedia's editors leave above each block
    (`<!-- Upper Bracket Quarterfinals -->`), so each match takes the name of
    the nearest comment above it.

    Only the first round has teams in it; later slots are filled in as the
    bracket resolves, and come back with `opponents: []`.
    """
    sections = [(m.start(), m.group(1).strip())
                for m in re.finditer(r"<!--(.*?)-->", wikitext, re.S)]

    def round_name(pos: int) -> str:
        name = ""
        for start, label in sections:
            if start < pos:
                name = label
            else:
                break
        return name

    dates = _extract_template(wikitext, "HiddenDataBox") or ""
    window = _named(_split_top_level(dates))

    matches: list[dict] = []
    for m in re.finditer(r"\|(R\d+M\d+)=\{\{Match", wikitext):
        # a slot's own body ends where the next one begins
        nxt = wikitext.find("{{Match", m.end())
        body = wikitext[m.end():nxt if nxt != -1 else len(wikitext)]
        opponents = [_clean(o) for o in
                     re.findall(r"opponent\d=\{\{TeamOpponent\|([^|}]+)", body)]
        when = re.search(r"\|date=([^\n|]+)", body)
        matches.append({
            "slot": m.group(1),
            "round": round_name(m.start()),
            "opponents": opponents[:2],
            "date": _clean(when.group(1)).replace("{{Abbr/CST}}", "CST").strip()
            if when else "",
        })

    teams: list[str] = []
    for match in matches:
        for name in match["opponents"]:
            if name not in teams:
                teams.append(name)

    return {
        "start_date": window.get("sdate", ""),
        "end_date": window.get("edate", ""),
        "teams": teams,
        "matches": matches,
    }


def fetch_main_event(page: str | None = None, ttl: float = config.TTL_SHORT) -> dict:
    """Download and parse the Main Event bracket page."""
    return parse_main_event(fetch_wikitext(page or config.LIQUIPEDIA_MAIN_EVENT_PAGE, ttl=ttl))


def fetch_all(ttl: float = config.TTL_MEDIUM) -> dict:
    wikitext = fetch_wikitext(ttl=ttl)
    return {
        "overview": parse_overview(wikitext),
        "participants": parse_participants(wikitext),
    }
