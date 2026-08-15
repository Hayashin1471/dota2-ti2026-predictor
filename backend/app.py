"""FastAPI application: JSON API + the static frontend."""
from __future__ import annotations

import logging
import re
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, ingest, matching, model

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    log.info("database ready at %s", config.DB_PATH)
    yield


app = FastAPI(title="TI 2026 Match Predictor", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """Force the browser to revalidate the frontend files.

    Without an explicit header the browser applies heuristic freshness and can
    serve a stale styles.css/app.js for hours after an edit.  `no-cache` still
    allows a cheap 304 via the ETag StaticFiles already sends.
    """
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# --------------------------------------------------------------------------
# read endpoints
# --------------------------------------------------------------------------
@app.get("/api/status")
def api_status():
    return {
        "tournament": db.get_meta("tournament", {}),
        "sources": {
            "liquipedia": db.get_meta("liquipedia_updated"),
            "gosugamers": db.get_meta("gosugamers_updated"),
        },
        "weights": model.weights(),
        "ti_context": model.ti_context(),
        **ingest.status(),
    }


def _roster(slug: str) -> list[dict]:
    """Pickable players for a team: OpenDota accounts first, then wiki-only names.

    The account id is what the model needs; a Liquipedia name we could not match
    is still listed (flagged `resolved: false`) so the roster does not silently
    lose a player, but it carries no hero statistics.
    """
    wiki = db.query("SELECT role, name, account_id FROM ti_players WHERE slug = ?", (slug,))
    role_by_account = {w["account_id"]: w["role"] for w in wiki if w["account_id"]}
    # The nickname is the same on both sources far more often than not, so it is
    # a good enough fallback while `refresh_players` has not run since the last
    # `refresh_core` rewrote the wiki roster.
    role_by_name = {matching.normalize(w["name"]): w["role"] for w in wiki}

    out: list[dict] = []
    seen: set[str] = set()

    for p in db.query(
            "SELECT account_id, name, is_current, team_games, hero_games FROM players "
            "WHERE slug = ? ORDER BY is_current DESC, team_games DESC", (slug,)):
        key = matching.normalize(p["name"] or "")
        out.append({
            "account_id": p["account_id"], "name": p["name"] or f"#{p['account_id']}",
            "role": role_by_account.get(p["account_id"]) or role_by_name.get(key),
            "current": bool(p["is_current"]),
            "team_games": p["team_games"] or 0,
            # games across every hero: how much history the player term has
            "total_games": p["hero_games"] or 0, "resolved": True,
        })
        seen.add(key)

    for w in wiki:
        if matching.normalize(w["name"]) in seen or re.search(r"coach", w["role"] or "", re.I):
            continue
        out.append({"account_id": None, "name": w["name"], "role": w["role"],
                    "current": True, "team_games": 0, "total_games": 0, "resolved": False})
    return out


@app.get("/api/teams")
def api_teams():
    rows = db.query(
        "SELECT t.slug, t.name, t.team_id, t.qualification, t.region, t.logo_url, t.source, "
        "e.rating, e.games, e.wins FROM ti_teams t LEFT JOIN elo e ON e.team_id = t.team_id "
        "ORDER BY t.name COLLATE NOCASE")
    teams = []
    for r in rows:
        strength = model.team_strength(r["team_id"])
        players = db.query("SELECT role, name FROM ti_players WHERE slug = ?", (r["slug"],))
        teams.append({
            "slug": r["slug"], "name": r["name"], "team_id": r["team_id"],
            "qualification": r["qualification"], "region": r["region"],
            "logo_url": r["logo_url"], "resolved": r["team_id"] is not None,
            "rating": round(strength["rating"], 1),
            "games": strength["games"], "wins": strength["wins"],
            "players": [{"role": p["role"], "name": p["name"]} for p in players],
            "roster": _roster(r["slug"]),
        })
    teams.sort(key=lambda t: -t["rating"])
    return {"teams": teams, "count": len(teams)}


@app.get("/api/roster/{slug}")
def api_roster(slug: str, hero_id: int | None = None):
    """Pickable players for one team.

    With `hero_id`, each player also carries his record on that hero, so the
    lineup picker can show who actually plays it.
    """
    if db.one("SELECT 1 FROM ti_teams WHERE slug = ?", (slug,)) is None:
        raise HTTPException(status_code=404, detail=f"unknown team '{slug}'")

    roster = _roster(slug)
    if hero_id:
        for p in roster:
            info = model.player_hero_edge(p["account_id"], hero_id)
            p["hero_games"] = info["games"]
            p["hero_winrate"] = round(info["winrate"], 4) if info["winrate"] is not None else None
            p["base_winrate"] = round(info["base"], 4) if info["base"] is not None else None
            p["edge"] = round(info["edge"], 4)
    return {"slug": slug, "hero_id": hero_id, "roster": roster}


@app.get("/api/players/{account_id}/heroes")
def api_player_heroes(account_id: int, limit: int = 30):
    """A player's best heroes, for the tooltip in the lineup picker."""
    base = model.player_baseline(account_id)
    rows = db.query(
        "SELECT ph.hero_id, ph.games, ph.wins, ph.last_played, h.localized_name, h.img "
        "FROM player_heroes ph LEFT JOIN heroes h ON h.hero_id = ph.hero_id "
        "WHERE ph.account_id = ? ORDER BY ph.games DESC LIMIT ?",
        (account_id, max(1, min(200, limit))))
    return {
        "account_id": account_id,
        "name": base["name"],
        "games": base["games"],
        "winrate": round(base["winrate"], 4),
        "known": base["known"],
        "heroes": [{
            "hero_id": r["hero_id"], "name": r["localized_name"], "img": r["img"],
            "games": r["games"], "wins": r["wins"],
            "winrate": round(r["wins"] / r["games"], 4) if r["games"] else None,
            "edge": model.player_hero_edge(account_id, r["hero_id"])["edge"],
        } for r in rows],
    }


@app.get("/api/heroes")
def api_heroes():
    table = model.hero_table()
    rows = db.query(
        "SELECT hero_id, localized_name, primary_attr, attack_type, roles, img, icon, "
        "pub_picks, pro_picks, pro_bans FROM heroes ORDER BY localized_name")
    heroes = []
    for r in rows:
        info = table.get(r["hero_id"], {})
        heroes.append({
            "id": r["hero_id"], "name": r["localized_name"],
            "attr": r["primary_attr"], "attack_type": r["attack_type"],
            "roles": (r["roles"] or "").split(",") if r["roles"] else [],
            "img": r["img"], "icon": r["icon"],
            "winrate": round(info.get("winrate", 0.5), 4),
            "pro_games": info.get("pro_games", 0),
            "pro_bans": r["pro_bans"],
            "duration_bias": round(info.get("ln_duration_delta", 0.0), 4),
        })
    return {"heroes": heroes, "count": len(heroes)}


@app.get("/api/schedule")
def api_schedule():
    rows = db.query(
        "SELECT match_key, team_a, team_b, score_a, score_b, status, stage, url "
        "FROM ti_schedule ORDER BY CAST(match_key AS INTEGER) DESC")
    return {"matches": [dict(r) for r in rows], "count": len(rows)}


@app.get("/api/results")
def api_results(scope: str = "ti", team_a: str | None = None, team_b: str | None = None,
                limit: int = 40, line_minutes: float = config.OVER_UNDER_LINE_MIN):
    """Finished-match history.

    scope=ti    - TI 2026 series (hawk.live archive)
    scope=all   - every tournament hawk.live has archived
    scope=teams - individual games for the two selected teams, with durations
                  and how they landed against the over/under line
    """
    limit = max(1, min(200, limit))

    if scope in ("ti", "all"):
        where = "WHERE is_ti = 1" if scope == "ti" else ""
        rows = db.query(
            "SELECT key, played_on, tournament, team_a, team_b, score_a, score_b, url "
            f"FROM series_results {where} "
            # rows from the rolling page have no date; show them first as newest
            "ORDER BY played_on IS NULL DESC, played_on DESC, key DESC LIMIT ?", (limit,))
        return {"scope": scope, "series": [dict(r) for r in rows], "count": len(rows)}

    if scope != "teams":
        raise HTTPException(status_code=400, detail="scope must be ti, all or teams")

    if not team_a or not team_b:
        raise HTTPException(status_code=400, detail="scope=teams needs team_a and team_b")

    a, b = _team_row(team_a), _team_row(team_b)
    line_sec = line_minutes * 60.0

    def games_for(team: dict) -> list[dict]:
        tid = team.get("team_id")
        if not tid:
            return []
        rows = db.query(
            "SELECT m.match_id, m.start_time, m.duration, m.radiant_id, m.radiant_win, "
            "m.league_name, t.name AS opponent FROM matches m "
            "LEFT JOIN teams t ON t.team_id = "
            "  CASE WHEN m.radiant_id = ? THEN m.dire_id ELSE m.radiant_id END "
            "WHERE (m.radiant_id = ? OR m.dire_id = ?) AND m.duration BETWEEN ? AND ? "
            "ORDER BY m.start_time DESC LIMIT ?",
            (tid, tid, tid, model.MIN_DURATION, model.MAX_DURATION, limit))
        out = []
        for r in rows:
            won = bool(r["radiant_win"]) == (r["radiant_id"] == tid)
            out.append({
                "match_id": r["match_id"],
                "start_time": r["start_time"],
                "opponent": r["opponent"] or "—",
                "won": won,
                "duration_min": round(r["duration"] / 60, 1),
                "over": r["duration"] > line_sec,
                "league": r["league_name"],
                "side": "radiant" if r["radiant_id"] == tid else "dire",
            })
        return out

    games_a, games_b = games_for(a), games_for(b)
    combined = games_a + games_b
    overs = sum(1 for g in combined if g["over"])

    return {
        "scope": "teams",
        "line_minutes": line_minutes,
        "a": {"name": a["name"], "games": games_a},
        "b": {"name": b["name"], "games": games_b},
        "over_under_summary": {
            "games": len(combined),
            "over": overs,
            "under": len(combined) - overs,
            "over_rate": round(overs / len(combined), 4) if combined else None,
        },
        "head_to_head": model.head_to_head(a.get("team_id"), b.get("team_id"), limit=15),
    }


# --------------------------------------------------------------------------
# prediction
# --------------------------------------------------------------------------
class PredictRequest(BaseModel):
    team_a: str = Field(..., description="slug of team A from /api/teams")
    team_b: str = Field(..., description="slug of team B from /api/teams")
    heroes_a: list[int] = Field(default_factory=list, max_length=5)
    heroes_b: list[int] = Field(default_factory=list, max_length=5)
    # account ids aligned slot-for-slot with heroes_a / heroes_b; null = unknown
    players_a: list[int | None] = Field(default_factory=list, max_length=5)
    players_b: list[int | None] = Field(default_factory=list, max_length=5)
    line_minutes: float = config.OVER_UNDER_LINE_MIN


def _team_row(slug: str) -> dict:
    row = db.one("SELECT slug, name, team_id, logo_url, qualification, region "
                 "FROM ti_teams WHERE slug = ?", (slug,))
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown team '{slug}'")
    return dict(row)


@app.post("/api/predict")
def api_predict(req: PredictRequest):
    if req.team_a == req.team_b:
        raise HTTPException(status_code=400, detail="pick two different teams")

    a, b = _team_row(req.team_a), _team_row(req.team_b)

    def lineup(heroes: list[int], players: list[int | None]) -> tuple[list[int], list[int | None]]:
        """Drop empty and duplicate hero slots, keeping each hero's player with it."""
        hs: list[int] = []
        ps: list[int | None] = []
        seen: set[int] = set()
        for i, h in enumerate(heroes):
            if not h or h in seen:
                continue
            seen.add(h)
            hs.append(h)
            ps.append(players[i] if i < len(players) else None)
        return hs, ps

    heroes_a, players_a = lineup(req.heroes_a, req.players_a)
    heroes_b, players_b = lineup(req.heroes_b, req.players_b)

    if set(heroes_a) & set(heroes_b):
        raise HTTPException(status_code=400, detail="a hero cannot be picked by both teams")
    for side in (players_a, players_b):
        picked = [p for p in side if p]
        if len(picked) != len(set(picked)):
            raise HTTPException(status_code=400,
                                detail="một tuyển thủ chỉ có thể cầm một hero")

    # Hero-vs-hero records are fetched on demand and cached for a week.
    if heroes_a and heroes_b:
        try:
            ingest.refresh_matchups(sorted(set(heroes_a + heroes_b)))
        except Exception as exc:                               # noqa: BLE001
            log.warning("matchup refresh failed: %s", exc)

    # Same idea for the players on screen: one request each, cached for days.
    accounts = [p for p in players_a + players_b if p]
    if accounts:
        try:
            ingest.refresh_player_heroes(accounts)
        except Exception as exc:                               # noqa: BLE001
            log.warning("player refresh failed: %s", exc)

    return model.predict(a, b, heroes_a, heroes_b, players_a, players_b,
                         line_minutes=req.line_minutes)


# --------------------------------------------------------------------------
# refresh
# --------------------------------------------------------------------------
class RefreshRequest(BaseModel):
    phase: str = Field("core", pattern="^(core|history|players|drafts|results|all)$")
    draft_limit: int = config.DEFAULT_DRAFT_SAMPLE
    result_days: int = config.RESULTS_DAYS


def _run_bg(fn, *args) -> None:
    def wrapper():
        try:
            fn(*args)
        except Exception as exc:                               # noqa: BLE001
            log.exception("refresh failed")
            ingest.JOB.error(str(exc))
            ingest.JOB.finish(f"failed: {exc}")
    threading.Thread(target=wrapper, daemon=True).start()


@app.post("/api/refresh")
def api_refresh(req: RefreshRequest):
    if ingest.JOB.snapshot()["running"]:
        raise HTTPException(status_code=409, detail="a refresh is already running")
    if req.phase == "core":
        _run_bg(ingest.refresh_core)
    elif req.phase == "history":
        _run_bg(ingest.refresh_history)
    elif req.phase == "players":
        _run_bg(ingest.refresh_players)
    elif req.phase == "drafts":
        _run_bg(ingest.refresh_drafts, max(1, min(2000, req.draft_limit)))
    elif req.phase == "results":
        _run_bg(ingest.refresh_results, max(1, min(120, req.result_days)))
    else:
        _run_bg(ingest.refresh_all, max(0, min(2000, req.draft_limit)))
    return {"started": req.phase}


@app.post("/api/refresh/cancel")
def api_refresh_cancel():
    ingest.JOB.update(running=False, message="cancelled by user")
    return {"cancelled": True}


@app.get("/api/refresh/status")
def api_refresh_status():
    return ingest.JOB.snapshot()


# --------------------------------------------------------------------------
# frontend
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="static")
