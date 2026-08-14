"""Collect data from Liquipedia / GosuGamers / OpenDota into SQLite.

Three phases, each usable on its own:

  core     ~10 requests  - tournament info, the 16 teams, heroes, schedule
  history  ~16 requests  - full pro match history for every TI team (durations)
  players  ~100 requests - rosters plus each player's per-hero win rate
  drafts   N requests    - hero picks + duration for a sample of pro matches

`core` is enough to use the app; `history` powers the Elo ratings and team
pace; `players` powers the per-player hero term; `drafts` sharpens the hero
duration model and can keep running in the background.
"""
from __future__ import annotations

import logging
import threading
import time

from . import config, db, matching, model
from .sources import gosugamers, hawk, liquipedia, opendota

log = logging.getLogger("ingest")

# proMatches pages are 100 matches each; this caps how far back a single
# drafts refresh will page while looking for matches it has not seen yet.
MAX_PRO_MATCH_PAGES = 40


# --------------------------------------------------------------------------
# job bookkeeping so the UI can show progress
# --------------------------------------------------------------------------
class Job:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = {
            "running": False,
            "phase": "idle",
            "message": "",
            "done": 0,
            "total": 0,
            "started_at": None,
            "finished_at": None,
            "errors": [],
        }

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.state)

    def start(self, phase: str) -> None:
        with self.lock:
            self.state.update(running=True, phase=phase, message="starting",
                             done=0, total=0, started_at=time.time(),
                             finished_at=None, errors=[])

    def update(self, **kw) -> None:
        with self.lock:
            self.state.update(kw)

    def error(self, msg: str) -> None:
        log.warning(msg)
        with self.lock:
            self.state["errors"].append(msg)

    def finish(self, message: str) -> None:
        with self.lock:
            self.state.update(running=False, phase="idle", message=message,
                              finished_at=time.time())


JOB = Job()


# --------------------------------------------------------------------------
# phase 1: core
# --------------------------------------------------------------------------
def refresh_core(job: Job = JOB) -> dict:
    """Tournament + participants + heroes + schedule.  Fast."""
    job.start("core")
    job.update(total=5, message="Liquipedia: tournament page")

    result = {"teams": 0, "heroes": 0, "schedule": 0, "unresolved": []}

    # 1. Liquipedia -------------------------------------------------------
    participants: list[dict] = []
    try:
        liqui = liquipedia.fetch_all()
        db.set_meta("tournament", liqui["overview"])
        participants = liqui["participants"]
        db.set_meta("liquipedia_updated", time.time())
    except Exception as exc:                                   # noqa: BLE001
        job.error(f"Liquipedia: {exc}")

    job.update(done=1, message="OpenDota: heroes")

    # 2. Heroes -----------------------------------------------------------
    try:
        rows = []
        for h in opendota.heroes():
            # brackets 6/7/8 = Divine+/Immortal public games: the closest large
            # sample to how heroes behave in a high-level draft.
            picks = sum(int(h.get(f"{b}_pick") or 0) for b in (6, 7, 8))
            wins = sum(int(h.get(f"{b}_win") or 0) for b in (6, 7, 8))
            if picks == 0:                       # fall back to the whole pub pool
                picks, wins = int(h.get("pub_pick") or 0), int(h.get("pub_win") or 0)
            rows.append((
                h["id"], h.get("name"), h.get("localized_name"), h.get("primary_attr"),
                h.get("attack_type"), ",".join(h.get("roles") or []),
                opendota.image_url(h.get("img")), opendota.image_url(h.get("icon")),
                picks, wins,
                int(h.get("pro_pick") or 0), int(h.get("pro_win") or 0), int(h.get("pro_ban") or 0),
            ))
        db.executemany(
            "INSERT INTO heroes(hero_id,name,localized_name,primary_attr,attack_type,roles,"
            "img,icon,pub_picks,pub_wins,pro_picks,pro_wins,pro_bans) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(hero_id) DO UPDATE SET name=excluded.name,"
            "localized_name=excluded.localized_name,primary_attr=excluded.primary_attr,"
            "attack_type=excluded.attack_type,roles=excluded.roles,img=excluded.img,"
            "icon=excluded.icon,pub_picks=excluded.pub_picks,pub_wins=excluded.pub_wins,"
            "pro_picks=excluded.pro_picks,pro_wins=excluded.pro_wins,pro_bans=excluded.pro_bans",
            rows,
        )
        result["heroes"] = len(rows)
    except Exception as exc:                                   # noqa: BLE001
        job.error(f"OpenDota heroes: {exc}")

    job.update(done=2, message="OpenDota: pro teams")

    # 3. OpenDota team table ---------------------------------------------
    od_index: dict[str, dict] = {}
    try:
        od_teams = opendota.teams()
        db.executemany(
            "INSERT INTO teams(team_id,name,tag,logo_url,od_rating,od_wins,od_losses,last_match_at) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(team_id) DO UPDATE SET name=excluded.name,tag=excluded.tag,"
            "logo_url=excluded.logo_url,od_rating=excluded.od_rating,od_wins=excluded.od_wins,"
            "od_losses=excluded.od_losses,last_match_at=excluded.last_match_at",
            [(t["team_id"], t.get("name") or "", t.get("tag"), t.get("logo_url"),
              t.get("rating"), t.get("wins"), t.get("losses"), t.get("last_match_time"))
             for t in od_teams if t.get("team_id") and t.get("name")],
        )
        od_index = matching.build_index(od_teams)
    except Exception as exc:                                   # noqa: BLE001
        job.error(f"OpenDota teams: {exc}")

    job.update(done=3, message="GosuGamers: schedule")

    # 4. GosuGamers schedule ---------------------------------------------
    gosu_names: list[str] = []
    try:
        schedule = gosugamers.fetch_ti_schedule()
        for err in schedule.get("errors", []):
            job.error(f"GosuGamers {err}")
        db.execute("DELETE FROM ti_schedule")
        db.executemany(
            "INSERT OR REPLACE INTO ti_schedule(match_key,team_a,team_b,score_a,score_b,"
            "status,stage,url,raw) VALUES (?,?,?,?,?,?,?,?,?)",
            [(m["match_key"], m["team_a"], m["team_b"], m["score_a"], m["score_b"],
              m["status"], m["stage"], m["url"], m["raw"]) for m in schedule["matches"]],
        )
        db.set_meta("gosu_tournament_slug", schedule.get("tournament_slug"))
        db.set_meta("gosugamers_updated", time.time())
        gosu_names = gosugamers.fetch_team_names(schedule)
        result["schedule"] = len(schedule["matches"])
    except Exception as exc:                                   # noqa: BLE001
        job.error(f"GosuGamers: {exc}")

    job.update(done=4, message="resolving teams across sources")

    # 5. Merge the three team views --------------------------------------
    # Liquipedia is the authority for who is at TI; GosuGamers fills in if the
    # wiki page could not be read; OpenDota supplies ids, logos and ratings.
    entries: list[dict] = []
    for p in participants:
        entries.append({"name": p["name"], "qualification": p["qualification"],
                        "region": p["region"], "players": p["players"], "source": "liquipedia"})
    if not entries and gosu_names:
        entries = [{"name": n, "qualification": "", "region": "", "players": [],
                    "source": "gosugamers"} for n in gosu_names]

    # The roster tables are rewritten from scratch below, which would throw away
    # the account ids `refresh_players` matched onto them.  Keep them.
    known_accounts = {(r["slug"], r["name"]): r["account_id"] for r in
                      db.query("SELECT slug, name, account_id FROM ti_players "
                               "WHERE account_id IS NOT NULL")}

    if entries:
        db.execute("DELETE FROM ti_teams")
        db.execute("DELETE FROM ti_players")

    team_rows, player_rows = [], []
    for e in entries:
        slug = matching.slugify(e["name"])
        od_team, how = matching.resolve(e["name"], od_index) if od_index else (None, "no-index")
        if od_team is None:
            result["unresolved"].append(e["name"])
        team_rows.append((slug, e["name"], od_team["team_id"] if od_team else None,
                          e["qualification"], e["region"],
                          od_team.get("logo_url") if od_team else None,
                          f"{e['source']}|{how}"))
        for pl in e["players"]:
            player_rows.append((slug, pl["role"], pl["name"],
                                known_accounts.get((slug, pl["name"]))))

    if team_rows:
        db.executemany(
            "INSERT OR REPLACE INTO ti_teams(slug,name,team_id,qualification,region,logo_url,source) "
            "VALUES (?,?,?,?,?,?,?)", team_rows)
        db.executemany("INSERT OR REPLACE INTO ti_players(slug,role,name,account_id) "
                       "VALUES (?,?,?,?)", player_rows)
    result["teams"] = len(team_rows)

    db.set_meta("core_updated", time.time())
    job.update(done=5)
    job.finish(f"core: {result['teams']} teams, {result['heroes']} heroes, "
               f"{result['schedule']} scheduled matches")
    return result


# --------------------------------------------------------------------------
# phase 2: match history -> Elo
# --------------------------------------------------------------------------
def refresh_history(job: Job = JOB) -> dict:
    """Pull each TI team's pro match history, then recompute ratings."""
    job.start("history")
    teams = db.query("SELECT slug, name, team_id FROM ti_teams WHERE team_id IS NOT NULL")
    job.update(total=len(teams) + 1, message="downloading match history")

    inserted = 0
    for i, t in enumerate(teams):
        job.update(done=i, message=f"history: {t['name']}")
        try:
            rows = []
            for m in opendota.team_matches(t["team_id"]):
                if not m.get("duration"):
                    continue
                # `radiant` says whether *this* team was radiant in that game
                if m.get("radiant"):
                    rad, dire = t["team_id"], m.get("opposing_team_id")
                else:
                    rad, dire = m.get("opposing_team_id"), t["team_id"]
                if not rad or not dire:
                    continue
                rows.append((m["match_id"], m.get("start_time"), m.get("duration"),
                             rad, dire, 1 if m.get("radiant_win") else 0,
                             m.get("leagueid"), m.get("league_name")))
            db.executemany(
                "INSERT OR REPLACE INTO matches(match_id,start_time,duration,radiant_id,"
                "dire_id,radiant_win,league_id,league_name) VALUES (?,?,?,?,?,?,?,?)", rows)
            inserted += len(rows)
        except Exception as exc:                               # noqa: BLE001
            job.error(f"history {t['name']}: {exc}")

    job.update(done=len(teams), message="computing Elo ratings")
    rated = model.rebuild_ratings()
    db.set_meta("history_updated", time.time())
    job.update(done=len(teams) + 1)
    job.finish(f"history: {inserted} match rows, {rated} teams rated")
    return {"matches": inserted, "rated_teams": rated}


# --------------------------------------------------------------------------
# phase 2b: rosters -> per-player hero records
# --------------------------------------------------------------------------
# Beyond this many players per team we are pulling stand-ins and ex-members
# nobody will pick; each one costs a request.
ROSTER_LIMIT = 8


def _store_player_heroes(account_id: int) -> int:
    """Download and store one player's per-hero record.  Returns rows stored."""
    rows = []
    total_games = total_wins = 0
    for h in opendota.player_heroes(account_id):
        try:
            hid = int(h.get("hero_id"))            # OpenDota returns this as a string
        except (TypeError, ValueError):
            continue
        games, wins = int(h.get("games") or 0), int(h.get("win") or 0)
        total_games += games
        total_wins += wins
        if games:
            rows.append((account_id, hid, games, wins, h.get("last_played")))

    db.executemany(
        "INSERT OR REPLACE INTO player_heroes(account_id,hero_id,games,wins,last_played) "
        "VALUES (?,?,?,?,?)", rows)
    db.execute(
        "UPDATE players SET hero_games=?, hero_wins=?, heroes_updated=? WHERE account_id=?",
        (total_games, total_wins, time.time(), account_id))
    return len(rows)


def refresh_player_heroes(account_ids: list[int], job: Job | None = None) -> int:
    """Fill in the hero table for players whose copy is missing or stale."""
    fresh_after = time.time() - config.PLAYER_REFRESH_TTL
    todo = []
    for aid in dict.fromkeys(a for a in account_ids if a):
        row = db.one("SELECT heroes_updated FROM players WHERE account_id = ?", (aid,))
        if row is None:
            # A player picked in the UI but never seen by a roster refresh: keep
            # the row so the hero table below has something to hang off.
            db.execute("INSERT OR IGNORE INTO players(account_id) VALUES (?)", (aid,))
        elif row["heroes_updated"] and row["heroes_updated"] > fresh_after:
            continue
        todo.append(aid)

    for aid in todo:
        try:
            _store_player_heroes(aid)
        except Exception as exc:                                   # noqa: BLE001
            log.warning("player heroes %s: %s", aid, exc)
            if job:
                job.error(f"player {aid}: {exc}")
    return len(todo)


def refresh_players(job: Job = JOB) -> dict:
    """Pull each TI team's roster and every listed player's hero record."""
    job.start("players")
    teams = db.query("SELECT slug, name, team_id FROM ti_teams WHERE team_id IS NOT NULL")
    job.update(total=len(teams) * 2 or 1, message="đang tải đội hình")

    # 1. rosters ----------------------------------------------------------
    roster: list[tuple[int, str]] = []          # (account_id, slug)
    for i, t in enumerate(teams):
        job.update(done=i, message=f"đội hình: {t['name']}")
        try:
            people = opendota.team_players(t["team_id"])
        except Exception as exc:                                   # noqa: BLE001
            job.error(f"roster {t['name']}: {exc}")
            continue

        # current members first, then the most-played former members
        people = [p for p in people if p.get("account_id")]
        people.sort(key=lambda p: (0 if p.get("is_current_team_member") else 1,
                                   -(p.get("games_played") or 0)))
        people = people[:ROSTER_LIMIT]

        # A player can show up on two rosters (current on one, former on the
        # other).  The team he actually plays for wins, whichever order the
        # refresh happens to visit them in.
        db.executemany(
            "INSERT INTO players(account_id,name,team_id,slug,team_games,team_wins,is_current) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(account_id) DO UPDATE SET name=COALESCE(excluded.name, name),"
            "team_id=CASE WHEN excluded.is_current=1 OR players.is_current=0 "
            "             THEN excluded.team_id ELSE players.team_id END,"
            "slug=CASE WHEN excluded.is_current=1 OR players.is_current=0 "
            "          THEN excluded.slug ELSE players.slug END,"
            "team_games=CASE WHEN excluded.is_current=1 OR players.is_current=0 "
            "                THEN excluded.team_games ELSE players.team_games END,"
            "team_wins=CASE WHEN excluded.is_current=1 OR players.is_current=0 "
            "               THEN excluded.team_wins ELSE players.team_wins END,"
            "is_current=MAX(excluded.is_current, players.is_current)",
            [(p["account_id"], p.get("name"), t["team_id"], t["slug"],
              p.get("games_played") or 0, p.get("wins") or 0,
              1 if p.get("is_current_team_member") else 0) for p in people])

        # tie the Liquipedia roster (which has the roles) to the account ids
        by_name = {matching.normalize(p.get("name") or ""): p["account_id"] for p in people}
        for pl in db.query("SELECT name FROM ti_players WHERE slug = ?", (t["slug"],)):
            aid = by_name.get(matching.normalize(pl["name"]))
            if aid:
                db.execute("UPDATE ti_players SET account_id = ? WHERE slug = ? AND name = ?",
                           (aid, t["slug"], pl["name"]))

        roster.extend((p["account_id"], t["slug"]) for p in people)

    # 2. per-hero records --------------------------------------------------
    fresh_after = time.time() - config.PLAYER_REFRESH_TTL
    todo = [aid for aid, _ in roster
            if not db.one("SELECT 1 FROM players WHERE account_id=? AND heroes_updated>?",
                          (aid, fresh_after))]
    done = 0
    for i, aid in enumerate(todo):
        if not job.snapshot()["running"]:        # cancelled
            break
        job.update(done=len(teams) + int(i / max(1, len(todo)) * len(teams)),
                   message=f"thành tích hero theo player {i + 1}/{len(todo)}")
        try:
            _store_player_heroes(aid)
            done += 1
        except Exception as exc:                                   # noqa: BLE001
            job.error(f"player {aid}: {exc}")

    db.set_meta("players_updated", time.time())
    model.invalidate_cache()
    covered = (db.one("SELECT COUNT(DISTINCT account_id) c FROM player_heroes") or {"c": 0})["c"]
    job.finish(f"players: {len(roster)} tuyển thủ, +{done} bảng hero mới, tổng {covered} người có dữ liệu")
    return {"players": len(roster), "fetched": done, "covered": covered}


# --------------------------------------------------------------------------
# phase 3: drafts -> hero duration / winrate model
# --------------------------------------------------------------------------
def refresh_drafts(limit: int = config.DEFAULT_DRAFT_SAMPLE, job: Job = JOB) -> dict:
    """Fetch picks + duration for recent pro matches (one request each)."""
    job.start("drafts")
    job.update(total=limit, message="listing recent pro matches")

    # Build a work list: recent pro matches we have not already processed.
    wanted: list[int] = []
    cursor: int | None = None
    try:
        # Bounded: once everything recent is already stored, paging further back
        # would otherwise walk years of history one request at a time.
        for _ in range(MAX_PRO_MATCH_PAGES):
            if len(wanted) >= limit or not job.snapshot()["running"]:
                break
            page = opendota.pro_matches(cursor)
            if not page:
                break
            for m in page:
                mid = m.get("match_id")
                if not mid:
                    continue
                seen = db.one("SELECT ok FROM draft_seen WHERE match_id = ?", (mid,))
                if seen is None:
                    wanted.append(mid)
            ids = [m["match_id"] for m in page if m.get("match_id")]
            if not ids:
                break
            cursor = min(ids)
    except Exception as exc:                                   # noqa: BLE001
        job.error(f"proMatches listing: {exc}")

    wanted = wanted[:limit]
    job.update(total=len(wanted) or 1, message=f"{len(wanted)} new matches to fetch")

    ok = 0
    for i, mid in enumerate(wanted):
        if not job.snapshot()["running"]:      # cancelled
            break
        job.update(done=i, message=f"drafts {i + 1}/{len(wanted)}")
        try:
            detail = opendota.match(mid)
            picks = detail.get("picks_bans") or []
            duration = detail.get("duration")
            if duration and picks:
                db.executemany(
                    "INSERT OR REPLACE INTO match_drafts(match_id,hero_id,side,is_pick) "
                    "VALUES (?,?,?,?)",
                    [(mid, p["hero_id"], int(p.get("team") or 0), 1 if p.get("is_pick") else 0)
                     for p in picks if p.get("hero_id")])
                # Never blank out team ids we already learned from a team's
                # history: some match details come back without them, and a
                # plain REPLACE would drop the match out of the Elo run.
                db.execute(
                    "INSERT INTO matches(match_id,start_time,duration,radiant_id,"
                    "dire_id,radiant_win,league_id,league_name) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(match_id) DO UPDATE SET "
                    "start_time=COALESCE(excluded.start_time, start_time),"
                    "duration=COALESCE(excluded.duration, duration),"
                    "radiant_id=COALESCE(excluded.radiant_id, radiant_id),"
                    "dire_id=COALESCE(excluded.dire_id, dire_id),"
                    "radiant_win=COALESCE(excluded.radiant_win, radiant_win),"
                    "league_id=COALESCE(excluded.league_id, league_id),"
                    "league_name=COALESCE(excluded.league_name, league_name)",
                    (mid, detail.get("start_time"), duration,
                     detail.get("radiant_team_id"), detail.get("dire_team_id"),
                     1 if detail.get("radiant_win") else 0,
                     detail.get("leagueid"), (detail.get("league") or {}).get("name")))
                ok += 1
                db.execute("INSERT OR REPLACE INTO draft_seen(match_id,ok) VALUES (?,1)", (mid,))
            else:
                db.execute("INSERT OR REPLACE INTO draft_seen(match_id,ok) VALUES (?,0)", (mid,))
        except Exception as exc:                               # noqa: BLE001
            # Deliberately *not* marked as seen: a rate limit or a dropped
            # connection is transient, and marking it would retire the match
            # permanently after one bad moment.  Only a successful fetch that
            # genuinely had no picks gets recorded above.
            job.error(f"match {mid}: {exc}")

    db.set_meta("drafts_updated", time.time())
    model.invalidate_cache()
    job.finish(f"drafts: +{ok} matches with picks")
    return {"fetched": ok, "attempted": len(wanted)}


# --------------------------------------------------------------------------
# phase 4: finished-series archive (hawk.live)
# --------------------------------------------------------------------------
def refresh_results(days: int = config.RESULTS_DAYS, job: Job = JOB) -> dict:
    """Walk hawk.live's per-day results pages and store finished series."""
    job.start("results")
    job.update(total=days + 1, message=f"hawk.live: {days} ngày gần nhất")

    try:
        rows, errors = hawk.fetch_recent(days)
    except Exception as exc:                                   # noqa: BLE001
        job.error(f"hawk.live: {exc}")
        job.finish(f"results: failed ({exc})")
        return {"series": 0}

    for err in errors:
        job.error(f"hawk.live {err}")

    now = time.time()
    db.executemany(
        "INSERT INTO series_results(key,source,played_on,tournament,team_a,team_b,"
        "score_a,score_b,url,is_ti,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET "
        # a dated page knows the real date; the rolling page does not
        "played_on=COALESCE(excluded.played_on, played_on),"
        "tournament=excluded.tournament,score_a=excluded.score_a,"
        "score_b=excluded.score_b,is_ti=excluded.is_ti,fetched_at=excluded.fetched_at",
        [(r["key"], "hawk.live", r.get("date"), r["tournament"], r["team_a"], r["team_b"],
          r["score_a"], r["score_b"], r["url"],
          1 if "international 2026" in r["tournament"].lower() else 0, now)
         for r in rows],
    )

    db.set_meta("results_updated", now)
    total = (db.one("SELECT COUNT(*) c FROM series_results") or {"c": 0})["c"]
    ti = (db.one("SELECT COUNT(*) c FROM series_results WHERE is_ti=1") or {"c": 0})["c"]
    job.update(done=days + 1)
    job.finish(f"results: {len(rows)} series mới xử lý, kho hiện có {total} ({ti} của TI)")
    return {"fetched": len(rows), "stored": total, "ti": ti}


def refresh_all_matchups(job: Job = JOB) -> dict:
    """Pull the hero-vs-hero table for every hero (one request each).

    Predictions fetch these lazily for the ten heroes on screen, which is fine
    for play but leaves the table too sparse to fit a matchup weight against.
    """
    job.start("matchups")
    heroes = [r["hero_id"] for r in db.query("SELECT hero_id FROM heroes ORDER BY hero_id")]
    job.update(total=len(heroes), message=f"hero matchups: {len(heroes)} hero")

    done = 0
    for i, hid in enumerate(heroes):
        if not job.snapshot()["running"]:
            break
        job.update(done=i, message=f"matchups {i + 1}/{len(heroes)}")
        done += refresh_matchups([hid], job)

    covered = (db.one("SELECT COUNT(DISTINCT hero_id) c FROM hero_matchups") or {"c": 0})["c"]
    model.invalidate_cache()
    job.finish(f"matchups: +{done} hero, đã có dữ liệu cho {covered}/{len(heroes)} hero")
    return {"fetched": done, "covered": covered, "heroes": len(heroes)}


def refresh_matchups(hero_ids: list[int], job: Job | None = None) -> int:
    """Cache hero-vs-hero records for the given heroes (one request each)."""
    fresh_after = time.time() - config.TTL_LONG
    todo = [h for h in hero_ids
            if not db.one("SELECT 1 FROM hero_matchups WHERE hero_id=? AND updated_at>? LIMIT 1",
                          (h, fresh_after))]
    now = time.time()
    for hid in todo:
        try:
            rows = [(hid, m["hero_id"], m.get("games_played") or 0, m.get("wins") or 0, now)
                    for m in opendota.hero_matchups(hid) if m.get("hero_id")]
            db.executemany(
                "INSERT OR REPLACE INTO hero_matchups(hero_id,vs_hero_id,games,wins,updated_at) "
                "VALUES (?,?,?,?,?)", rows)
        except Exception as exc:                               # noqa: BLE001
            log.warning("matchups %s: %s", hid, exc)
            if job:
                job.error(f"matchups {hid}: {exc}")
    return len(todo)


def refresh_all(draft_limit: int = config.DEFAULT_DRAFT_SAMPLE) -> dict:
    out = {"core": refresh_core()}
    out["history"] = refresh_history()
    out["players"] = refresh_players()
    out["results"] = refresh_results()
    if draft_limit:
        out["drafts"] = refresh_drafts(draft_limit)
    return out


def status() -> dict:
    def count(table: str) -> int:
        row = db.one(f"SELECT COUNT(*) AS c FROM {table}")
        return row["c"] if row else 0

    return {
        "ti_teams": count("ti_teams"),
        "resolved_teams": (db.one("SELECT COUNT(*) c FROM ti_teams WHERE team_id IS NOT NULL") or {"c": 0})["c"],
        "heroes": count("heroes"),
        "matches": count("matches"),
        "matches_with_drafts": (db.one("SELECT COUNT(DISTINCT match_id) c FROM match_drafts") or {"c": 0})["c"],
        "scheduled_matches": count("ti_schedule"),
        "rated_teams": count("elo"),
        "players": count("players"),
        "players_with_heroes": (db.one("SELECT COUNT(DISTINCT account_id) c FROM player_heroes") or {"c": 0})["c"],
        "series_results": count("series_results"),
        "ti_series_results": (db.one("SELECT COUNT(*) c FROM series_results WHERE is_ti=1") or {"c": 0})["c"],
        "updated": {
            "core": db.get_meta("core_updated"),
            "history": db.get_meta("history_updated"),
            "players": db.get_meta("players_updated"),
            "drafts": db.get_meta("drafts_updated"),
            "results": db.get_meta("results_updated"),
        },
        "job": JOB.snapshot(),
    }
