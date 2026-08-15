"""The prediction model.

Three independent signals are combined on the log-odds scale:

1. **Team strength** - an Elo rating computed from every pro match the TI teams
   have played in the last ~21 months (recent games weighted more), blended
   with OpenDota's own long-run team rating for stability.
2. **Hero quality** - each picked hero's win rate, estimated from high-bracket
   public games and shrunk toward the pro sample we have collected.
3. **Draft matchups** - hero-vs-hero head-to-head records, expressed as an edge
   *relative to* each hero's own baseline so the hero's general strength is not
   counted twice.
4. **Player on hero** - how each named player performs on the hero he is given,
   measured against *his own* overall win rate.  Taking the raw number would
   mostly re-measure how good his team is, which term 1 already covers; the
   deviation from his own baseline is what is left, i.e. hero proficiency.

Match length is modelled separately as a lognormal: a global pro-match baseline
shifted by the two teams' historical pace and by the heroes on the board, then
integrated past the 41-minute line to price over/under.

On top of both sits a **tournament context** (`ti_context`): two multipliers and
a duration offset fitted on the TI games already played.  It exists because a TI
game is not a random pro game - the field is sixteen elite teams drafting from
the same prepared pool - and because that difference is only measurable once the
tournament is under way.  See `backend/evaluate.py:fit_ti_context`.
"""
from __future__ import annotations

import math
import threading
import time

from . import config, db

_cache: dict[str, object] = {}
_cache_lock = threading.Lock()

LN10_OVER_400 = math.log(10) / 400.0
MIN_DURATION = 900      # 15 min - discard remakes/forfeits
MAX_DURATION = 6000     # 100 min


def invalidate_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cached(key: str, ttl: float, builder):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[0] < ttl:      # type: ignore[index]
            return entry[1]                             # type: ignore[index]
    value = builder()
    with _cache_lock:
        _cache[key] = (time.time(), value)
    return value


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def logit(p: float, eps: float = 1e-4) -> float:
    p = min(max(p, eps), 1.0 - eps)
    return math.log(p / (1.0 - p))


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# ==========================================================================
# 1. Team strength
# ==========================================================================
def rebuild_ratings() -> int:
    """Run Elo over the stored match history and persist the result."""
    cutoff = time.time() - config.ELO_HISTORY_DAYS * 86400
    rows = db.query(
        "SELECT match_id, start_time, duration, radiant_id, dire_id, radiant_win "
        "FROM matches WHERE start_time > ? AND radiant_id IS NOT NULL AND dire_id IS NOT NULL "
        "AND duration BETWEEN ? AND ? ORDER BY start_time ASC",
        (cutoff, MIN_DURATION, MAX_DURATION),
    )
    if not rows:
        return 0

    now = time.time()
    ratings: dict[int, float] = {}
    games: dict[int, int] = {}
    wins: dict[int, int] = {}
    dur_sum: dict[int, float] = {}
    last: dict[int, int] = {}
    snapshots: list[tuple[float, float, int]] = []

    for r in rows:
        rad, dire = r["radiant_id"], r["dire_id"]
        ra = ratings.get(rad, config.ELO_START)
        rb = ratings.get(dire, config.ELO_START)
        expected = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        actual = 1.0 if r["radiant_win"] else 0.0

        age_days = max(0.0, (now - (r["start_time"] or now)) / 86400.0)
        recency = 0.5 ** (age_days / config.ELO_HALF_LIFE_DAYS)
        k = config.ELO_K * (0.35 + 0.65 * recency)
        # provisional boost: a team's first games move its rating faster
        k_rad = k * (1.8 if games.get(rad, 0) < 10 else 1.0)
        k_dire = k * (1.8 if games.get(dire, 0) < 10 else 1.0)

        # snapshot the ratings the model *would have had* going into this game,
        # so a backtest can score itself without seeing the result first
        snapshots.append((round(ra, 2), round(rb, 2), r["match_id"]))

        ratings[rad] = ra + k_rad * (actual - expected)
        ratings[dire] = rb + k_dire * ((1.0 - actual) - (1.0 - expected))

        for tid, won in ((rad, actual == 1.0), (dire, actual == 0.0)):
            games[tid] = games.get(tid, 0) + 1
            wins[tid] = wins.get(tid, 0) + (1 if won else 0)
            dur_sum[tid] = dur_sum.get(tid, 0.0) + r["duration"]
            last[tid] = max(last.get(tid, 0), r["start_time"] or 0)

    db.executemany(
        "UPDATE matches SET pre_elo_radiant = ?, pre_elo_dire = ? WHERE match_id = ?",
        snapshots)

    db.execute("DELETE FROM elo")
    db.executemany(
        "INSERT INTO elo(team_id,rating,games,wins,avg_duration,last_played) VALUES (?,?,?,?,?,?)",
        [(tid, round(rating, 2), games.get(tid, 0), wins.get(tid, 0),
          dur_sum.get(tid, 0.0) / max(1, games.get(tid, 0)), last.get(tid, 0))
         for tid, rating in ratings.items()],
    )
    invalidate_cache()
    return len(ratings)


def _od_calibration() -> tuple[float, float]:
    """Least-squares map from OpenDota's rating scale onto ours.

    The two scales share a shape but not a spread, so a plain offset would
    overrate weak teams.  Fit `elo ~ a * od + b` on the teams that have both.
    """
    rows = db.query(
        "SELECT e.rating AS elo, t.od_rating AS od FROM elo e "
        "JOIN teams t ON t.team_id = e.team_id "
        "WHERE t.od_rating IS NOT NULL AND e.games >= 10")
    if len(rows) < 15:
        return 1.0, 0.0
    xs = [float(r["od"]) for r in rows]
    ys = [float(r["elo"]) for r in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return 1.0, my - mx
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    slope = min(1.6, max(0.4, slope))       # guard against a degenerate fit
    return slope, my - slope * mx


def team_strength(team_id: int | None) -> dict:
    """Blended rating for a team, plus the pieces that went into it."""
    if not team_id:
        return {"rating": config.ELO_START, "elo": None, "od_rating": None,
                "games": 0, "wins": 0, "avg_duration": None, "known": False}

    e = db.one("SELECT rating, games, wins, avg_duration FROM elo WHERE team_id = ?", (team_id,))
    t = db.one("SELECT od_rating, od_wins, od_losses FROM teams WHERE team_id = ?", (team_id,))
    slope, intercept = _cached("od_calibration", 300, _od_calibration)

    elo = float(e["rating"]) if e else None
    od = slope * float(t["od_rating"]) + intercept if t and t["od_rating"] is not None else None
    games = int(e["games"]) if e else 0

    if elo is not None and od is not None:
        # trust our own Elo more once a team has a real sample behind it
        w = min(0.75, 0.35 + 0.02 * games)
        rating = w * elo + (1 - w) * od
    else:
        rating = elo if elo is not None else (od if od is not None else config.ELO_START)

    return {
        "rating": rating,
        "elo": elo,
        "od_rating": float(t["od_rating"]) if t and t["od_rating"] is not None else None,
        "games": games,
        "wins": int(e["wins"]) if e else 0,
        "avg_duration": float(e["avg_duration"]) if e and e["avg_duration"] else None,
        "known": elo is not None or od is not None,
    }


def recent_form(team_id: int | None, limit: int = 10) -> dict:
    if not team_id:
        return {"results": [], "wins": 0, "losses": 0, "avg_duration_min": None}
    rows = db.query(
        "SELECT duration, radiant_id, radiant_win, start_time FROM matches "
        "WHERE (radiant_id = ? OR dire_id = ?) AND duration BETWEEN ? AND ? "
        "ORDER BY start_time DESC LIMIT ?",
        (team_id, team_id, MIN_DURATION, MAX_DURATION, limit),
    )
    results, durations = [], []
    for r in rows:
        won = bool(r["radiant_win"]) == (r["radiant_id"] == team_id)
        results.append("W" if won else "L")
        durations.append(r["duration"])
    return {
        "results": results,
        "wins": results.count("W"),
        "losses": results.count("L"),
        "avg_duration_min": round(sum(durations) / len(durations) / 60, 1) if durations else None,
    }


def head_to_head(a: int | None, b: int | None, limit: int = 10) -> dict:
    if not a or not b:
        return {"a_wins": 0, "b_wins": 0, "matches": []}
    rows = db.query(
        "SELECT match_id, start_time, duration, radiant_id, radiant_win, league_name "
        "FROM matches WHERE ((radiant_id=? AND dire_id=?) OR (radiant_id=? AND dire_id=?)) "
        "AND duration BETWEEN ? AND ? ORDER BY start_time DESC LIMIT ?",
        (a, b, b, a, MIN_DURATION, MAX_DURATION, limit),
    )
    out, a_wins, b_wins = [], 0, 0
    for r in rows:
        a_won = bool(r["radiant_win"]) == (r["radiant_id"] == a)
        a_wins += a_won
        b_wins += not a_won
        out.append({
            "match_id": r["match_id"],
            "start_time": r["start_time"],
            "duration_min": round(r["duration"] / 60, 1),
            "winner": "A" if a_won else "B",
            "league": r["league_name"],
        })
    return {"a_wins": a_wins, "b_wins": b_wins, "matches": out}


# ==========================================================================
# 2. Hero quality
# ==========================================================================
def hero_table() -> dict[int, dict]:
    """hero_id -> baseline win rate and log-duration effect."""
    def build() -> dict[int, dict]:
        heroes = db.query(
            "SELECT hero_id, localized_name, pub_picks, pub_wins, pro_picks, pro_wins FROM heroes")

        # win/loss from the pro drafts we downloaded ourselves
        pro = {r["hero_id"]: r for r in db.query(
            "SELECT d.hero_id AS hero_id, COUNT(*) AS games, "
            "SUM(CASE WHEN (d.side = 0) = (m.radiant_win = 1) THEN 1 ELSE 0 END) AS wins, "
            "AVG(LN(m.duration)) AS ln_dur "
            "FROM match_drafts d JOIN matches m ON m.match_id = d.match_id "
            "WHERE d.is_pick = 1 AND m.duration BETWEEN ? AND ? GROUP BY d.hero_id",
            (MIN_DURATION, MAX_DURATION))}

        # Hero duration effects must be measured against the *same* pool of
        # games they come from.  Comparing a 450-match recent pro sample with
        # the multi-year baseline made every hero look like a long-game hero.
        sample = draft_sample_stats()
        table: dict[int, dict] = {}
        for h in heroes:
            hid = h["hero_id"]
            pub_n, pub_w = h["pub_picks"] or 0, h["pub_wins"] or 0
            pub_wr = (pub_w + 0.5 * config.HERO_WR_PRIOR_GAMES) / (pub_n + config.HERO_WR_PRIOR_GAMES) \
                if pub_n else 0.5

            p = pro.get(hid)
            pro_n = int(p["games"]) if p else 0
            if pro_n:
                # Shrink the small pro sample toward the huge public sample.
                # A hero's pro win rate is partly "which teams picked it", and
                # team strength is already a separate term, so shrink hard.
                wr = (float(p["wins"]) + config.PRO_WR_SHRINK * pub_wr) / (pro_n + config.PRO_WR_SHRINK)
            else:
                wr = pub_wr

            # log-duration deviation of games this hero was picked in
            delta = 0.0
            if p and p["ln_dur"] is not None and pro_n:
                raw = float(p["ln_dur"]) - sample["mu"]
                delta = raw * (pro_n / (pro_n + config.DURATION_PRIOR_GAMES))

            table[hid] = {
                "name": h["localized_name"],
                "winrate": wr,
                "pub_winrate": pub_wr,
                "pro_games": pro_n,
                "ln_duration_delta": delta,
            }
        return table

    return _cached("hero_table", 120, build)


def matchup_edge(hero_a: int, hero_b: int, table: dict[int, dict]) -> float:
    """Log-odds edge hero A has over hero B, net of A's own baseline."""
    row = db.one(
        "SELECT games, wins FROM hero_matchups WHERE hero_id = ? AND vs_hero_id = ?",
        (hero_a, hero_b))
    if not row or not row["games"]:
        return 0.0
    # OpenDota's matchup table is built from public matches, so it has to be
    # compared against the hero's *public* win rate.  Measuring it against the
    # pro-adjusted rate would fold that adjustment into the matchup edge.
    base = table.get(hero_a, {}).get("pub_winrate", 0.5)
    n, w = int(row["games"]), int(row["wins"])
    k = config.MATCHUP_PRIOR_GAMES
    p = (w + k * base) / (n + k)          # shrink toward the hero's own win rate
    return logit(p) - logit(base)


# ==========================================================================
# 2b. Player proficiency on the hero he is given
# ==========================================================================
def player_baseline(account_id: int) -> dict:
    """A player's own overall win rate, the reference his hero record is judged against."""
    row = db.one("SELECT name, hero_games, hero_wins, heroes_updated FROM players "
                 "WHERE account_id = ?", (account_id,))
    if not row or not row["hero_games"]:
        return {"name": row["name"] if row else None, "games": 0, "winrate": 0.5, "known": False}
    games, wins = int(row["hero_games"]), int(row["hero_wins"])
    return {"name": row["name"], "games": games, "winrate": wins / games,
            "known": bool(row["heroes_updated"])}


def player_hero_edge(account_id: int | None, hero_id: int | None) -> dict:
    """Log-odds this player brings on this hero, net of his own average.

    A player's record on one hero is a small sample (often a few dozen games),
    so it is shrunk toward his overall win rate and then capped: the term is
    meant to separate "his signature hero" from "a hero he never plays", not to
    swing a match on twelve games.
    """
    blank = {"edge": 0.0, "games": 0, "winrate": None, "base": None,
             "name": None, "known": False}
    if not account_id or not hero_id:
        return blank

    base = player_baseline(account_id)
    if not base["known"]:
        return {**blank, "name": base["name"]}

    row = db.one("SELECT games, wins FROM player_heroes WHERE account_id = ? AND hero_id = ?",
                 (account_id, hero_id))
    n = int(row["games"]) if row else 0
    w = int(row["wins"]) if row else 0
    if n < config.PLAYER_MIN_GAMES:
        # Never played it in a tracked game.  That is weak evidence of *nothing*
        # rather than evidence of weakness, so the edge stays at zero.
        return {"edge": 0.0, "games": n, "winrate": (w / n) if n else None,
                "base": base["winrate"], "name": base["name"], "known": True}

    k = config.PLAYER_HERO_PRIOR_GAMES
    p = (w + k * base["winrate"]) / (n + k)
    edge = logit(p) - logit(base["winrate"])
    edge = max(-config.PLAYER_EDGE_CAP, min(config.PLAYER_EDGE_CAP, edge))
    return {"edge": edge, "games": n, "winrate": w / n, "base": base["winrate"],
            "name": base["name"], "known": True}


def lineup_edges(players: list[int | None], heroes: list[int]) -> list[dict]:
    """Per-slot player/hero detail for one side, aligned with `heroes`."""
    out = []
    for i, hero_id in enumerate(heroes):
        account_id = players[i] if players and i < len(players) else None
        info = player_hero_edge(account_id, hero_id)
        out.append({
            "account_id": account_id,
            "hero_id": hero_id,
            "hero": hero_table().get(hero_id, {}).get("name"),
            "player": info["name"],
            "games": info["games"],
            "winrate": round(info["winrate"], 4) if info["winrate"] is not None else None,
            "base_winrate": round(info["base"], 4) if info["base"] is not None else None,
            "edge": round(info["edge"], 4),
            "known": info["known"],
        })
    return out


# ==========================================================================
# 3. Match length
# ==========================================================================
def _lognormal_fit(days: int | None) -> dict | None:
    sql = "SELECT duration FROM matches WHERE duration BETWEEN ? AND ?"
    params: list = [MIN_DURATION, MAX_DURATION]
    if days:
        sql += " AND start_time > ?"
        params.append(time.time() - days * 86400)
    vals = [math.log(r["duration"]) for r in db.query(sql, params)]
    if len(vals) < 250:
        return None
    mu = sum(vals) / len(vals)
    var = sum((v - mu) ** 2 for v in vals) / max(1, len(vals) - 1)
    return {"mu": mu, "sigma": max(0.15, math.sqrt(var)), "n": len(vals), "days": days}


def duration_baseline() -> dict:
    """Lognormal fit over *recent* pro match durations.

    Game length drifts hard with patches - the all-time mean of this database
    is ~37 minutes while the last few months sit at ~41.  Prefer the narrowest
    window that still has a usable sample.
    """
    def build() -> dict:
        for days in config.DURATION_WINDOWS:
            fit = _lognormal_fit(days)
            if fit:
                return fit
        return {"mu": math.log(2460), "sigma": 0.29, "n": 0, "days": None}

    return _cached("duration_baseline", 120, build)


def draft_sample_stats() -> dict:
    """Duration stats over just the matches we have drafts for.

    This is the reference point for hero effects, and its gap from the global
    baseline is the current-meta pace shift.
    """
    def build() -> dict:
        row = db.one(
            "SELECT COUNT(*) AS n, AVG(LN(m.duration)) AS mu FROM matches m "
            "WHERE m.duration BETWEEN ? AND ? "
            "AND EXISTS (SELECT 1 FROM match_drafts d WHERE d.match_id = m.match_id)",
            (MIN_DURATION, MAX_DURATION))
        base = duration_baseline()
        if not row or not row["n"] or row["mu"] is None:
            return {"mu": base["mu"], "n": 0, "shift": 0.0}
        n = int(row["n"])
        mu = float(row["mu"])
        # a thin sample should not move the baseline much
        shift = (mu - base["mu"]) * (n / (n + 250.0))
        return {"mu": mu, "n": n, "shift": shift}

    return _cached("draft_sample_stats", 120, build)


def _pace_reference() -> float:
    """Mean log duration across all teams inside the pace window.

    Team pace has to be measured against games from the same era, otherwise
    every current team looks slow simply because Dota games got longer.
    """
    def build() -> float:
        row = db.one(
            "SELECT AVG(LN(duration)) AS m FROM matches "
            "WHERE duration BETWEEN ? AND ? AND start_time > ?",
            (MIN_DURATION, MAX_DURATION, time.time() - config.PACE_WINDOW_DAYS * 86400))
        if not row or row["m"] is None:
            return duration_baseline()["mu"]
        return float(row["m"])

    return _cached("pace_reference", 120, build)


def team_pace(team_id: int | None) -> float:
    """How much longer/shorter than its peers this team's games run (log scale)."""
    if not team_id:
        return 0.0

    def build() -> float:
        row = db.one(
            "SELECT COUNT(*) AS n, AVG(LN(duration)) AS m FROM matches "
            "WHERE (radiant_id = ? OR dire_id = ?) AND duration BETWEEN ? AND ? "
            "AND start_time > ?",
            (team_id, team_id, MIN_DURATION, MAX_DURATION,
             time.time() - config.PACE_WINDOW_DAYS * 86400))
        if not row or not row["n"] or row["m"] is None:
            return 0.0
        n = int(row["n"])
        return (float(row["m"]) - _pace_reference()) * (n / (n + 25.0))

    return _cached(f"pace:{team_id}", 120, build)


# ==========================================================================
# Prediction
# ==========================================================================
HERO_DELTA_CAP = 0.15       # +/- ~16% on match length from the draft alone
DRAFT_LOGIT_CAP = 0.9       # keep the draft from overwhelming team strength
HERO_DELTA_GAIN = 1.0       # dial the draft's length effect up or down


def weights() -> dict:
    """Term weights, preferring any that `evaluate.fit_weights` has stored.

    `backend/evaluate.py` fits these on historical pro matches and writes the
    result to the `fitted_weights` meta key; until it runs, the hand-set values
    in config apply.
    """
    fitted = db.get_meta("fitted_weights") or {}
    return {
        "team": float(fitted.get("team", config.W_TEAM)),
        "hero": float(fitted.get("hero", config.W_HERO_WINRATE)),
        "matchup": float(fitted.get("matchup", config.W_MATCHUP)),
        # `evaluate.py` cannot fit this one: scoring it on past matches would
        # need each player's hero record *as it stood then*, and we only store
        # today's aggregate.  It stays hand-set in config.
        "player": float(config.W_PLAYER_HERO),
        "source": "fitted" if fitted else "config",
        "fitted_at": fitted.get("fitted_at"),
        "trained_on": fitted.get("trained_on"),
    }


def ti_context() -> dict:
    """Corrections fitted on the TI matches already played, or neutral ones.

    `evaluate.fit_ti_context` writes this after every `--apply` run.  Until TI
    has enough finished games the multipliers stay at 1 and the shift at 0, so
    the model behaves exactly as it did before the tournament started.
    """
    ctx = db.get_meta("ti_context") or {}
    games = int(ctx.get("games", 0))
    # Re-check the threshold on read, not just on write: raising
    # TI_CONTEXT_MIN_GAMES should switch an already-stored correction back off.
    enough = games >= config.TI_CONTEXT_MIN_GAMES * 2
    hero = float(ctx.get("hero_mult", 1.0)) if enough else 1.0
    matchup = float(ctx.get("matchup_mult", 1.0)) if enough else 1.0
    shift = float(ctx.get("duration_shift", 0.0)) if enough else 0.0
    return {
        "hero_mult": hero,
        "matchup_mult": matchup,
        "duration_shift": shift,
        "games": games,
        "fitted_at": ctx.get("fitted_at"),
        "raw": ctx.get("raw"),
        "validation": ctx.get("validation"),
        "note": ctx.get("note"),
        # "active" means something is actually being changed, not merely that a
        # context row exists: `fit_ti_context` neutralises whichever half failed
        # its out-of-sample check, and a neutralised context must not announce
        # itself in the UI as if it were doing something.
        "active": hero != 1.0 or matchup != 1.0 or shift != 0.0,
    }


def predict(team_a: dict, team_b: dict, heroes_a: list[int], heroes_b: list[int],
            players_a: list[int | None] | None = None,
            players_b: list[int | None] | None = None,
            line_minutes: float = config.OVER_UNDER_LINE_MIN,
            ti_mode: bool = True) -> dict:
    """team_a/team_b are rows from ti_teams (dicts with slug, name, team_id).

    `players_a`/`players_b` are OpenDota account ids aligned slot-for-slot with
    `heroes_a`/`heroes_b`; a `None` slot simply contributes no player term.

    `ti_mode` applies the corrections fitted on TI games already played.  It
    defaults to on because every prediction this app is asked for *is* a TI
    game; the backtest turns it off for non-TI matches.
    """
    table = hero_table()
    sa = team_strength(team_a.get("team_id"))
    sb = team_strength(team_b.get("team_id"))

    w = weights()
    ctx = ti_context()
    if not ti_mode:
        ctx = {**ctx, "hero_mult": 1.0, "matchup_mult": 1.0,
               "duration_shift": 0.0, "active": False}

    # --- team strength -----------------------------------------------
    team_logit = w["team"] * (sa["rating"] - sb["rating"]) * LN10_OVER_400

    # --- hero win rates ----------------------------------------------
    # `pub_winrate`, not the pro-adjusted `winrate`: the pro adjustment is
    # derived from the same match sample the weights are fitted on, so using it
    # here would let the hero term score itself on its own answers.  See
    # backend/evaluate.py.
    def hero_sum(ids: list[int]) -> float:
        return sum(logit(table.get(h, {}).get("pub_winrate", 0.5)) for h in ids)

    hero_raw = hero_sum(heroes_a) - hero_sum(heroes_b)
    # At TI both sides draft from the same tiny pool of prepared heroes, so the
    # public win-rate gap between the two drafts carries much less information
    # than it does in an average pro game.  `ctx["hero_mult"]` is what the TI
    # games played so far say about that; it is 1.0 until they say otherwise.
    hero_logit = w["hero"] * hero_raw * ctx["hero_mult"]

    # --- hero vs hero -------------------------------------------------
    matchup_raw = 0.0
    pairs = 0
    for a in heroes_a:
        for b in heroes_b:
            matchup_raw += matchup_edge(a, b, table) - matchup_edge(b, a, table)
            pairs += 1
    if pairs:
        matchup_raw = matchup_raw / pairs * 5.0     # scale to "per hero"
    matchup_logit = w["matchup"] * matchup_raw * ctx["matchup_mult"]

    draft_logit = max(-DRAFT_LOGIT_CAP, min(DRAFT_LOGIT_CAP, hero_logit + matchup_logit))

    # --- player on hero -----------------------------------------------
    lineup_a = lineup_edges(players_a or [], heroes_a)
    lineup_b = lineup_edges(players_b or [], heroes_b)
    player_raw = sum(x["edge"] for x in lineup_a) - sum(x["edge"] for x in lineup_b)
    player_logit = w["player"] * player_raw
    player_logit = max(-config.PLAYER_LOGIT_CAP, min(config.PLAYER_LOGIT_CAP, player_logit))

    total_logit = team_logit + draft_logit + player_logit
    p_a = sigmoid(total_logit)

    # --- match length -------------------------------------------------
    base = duration_baseline()
    sample = draft_sample_stats()
    pace = (team_pace(team_a.get("team_id")) + team_pace(team_b.get("team_id"))) / 2.0

    # Under an additive log-duration model each hero contributes its own shift,
    # so the picks are summed.  The per-hero shrinkage in `hero_table` is what
    # keeps a thin sample from turning estimation noise into a prediction.
    picked = heroes_a + heroes_b
    raw = sum(table.get(h, {}).get("ln_duration_delta", 0.0) for h in picked)
    hero_delta = max(-HERO_DELTA_CAP, min(HERO_DELTA_CAP, raw * HERO_DELTA_GAIN))

    # TI games run longer than the pro pool the baseline is drawn from, even
    # after team pace and the draft are accounted for.  `duration_shift` is the
    # leftover, measured on the TI games already played.
    mu = base["mu"] + sample["shift"] + pace + hero_delta + ctx["duration_shift"]
    sigma = max(0.16, base["sigma"] * 0.97)
    line_sec = line_minutes * 60.0
    p_over = 1.0 - _norm_cdf((math.log(line_sec) - mu) / sigma)

    median_min = math.exp(mu) / 60.0
    mean_min = math.exp(mu + sigma ** 2 / 2) / 60.0

    # --- confidence ---------------------------------------------------
    drafted_matches = (db.one("SELECT COUNT(DISTINCT match_id) c FROM match_drafts") or {"c": 0})["c"]
    team_games = min(sa["games"], sb["games"])
    if team_games >= 30 and drafted_matches >= 200 and sa["known"] and sb["known"]:
        confidence = "high"
    elif team_games >= 10 and sa["known"] and sb["known"]:
        confidence = "medium"
    else:
        confidence = "low"

    notes: list[str] = []
    if not sa["known"]:
        notes.append(f"No rated match history found for {team_a['name']} - using a neutral rating.")
    if not sb["known"]:
        notes.append(f"No rated match history found for {team_b['name']} - using a neutral rating.")
    if drafted_matches < 400:
        notes.append("Hero duration effects use a thin pro sample; run a draft refresh for better numbers.")
    if len(heroes_a) < 5 or len(heroes_b) < 5:
        notes.append("Fewer than 5 heroes picked on one side - the draft signal is partial.")

    assigned = [x for x in lineup_a + lineup_b if x["account_id"]]
    unknown = [x for x in assigned if not x["known"]]
    if unknown:
        notes.append(f"{len(unknown)} tuyển thủ chưa có dữ liệu hero — chạy cập nhật 'players' "
                     f"để thu thập.")
    thin = [x for x in assigned if x["known"] and x["games"] < config.PLAYER_MIN_GAMES]
    if thin:
        notes.append(f"{len(thin)} lượt gán hero có dưới {config.PLAYER_MIN_GAMES} trận của tuyển "
                     f"thủ đó trên hero này — phần đó được tính là trung tính.")
    if not assigned and (heroes_a or heroes_b):
        notes.append("Chưa gán tuyển thủ cho hero nào — yếu tố 'tuyển thủ với hero' đang bằng 0.")
    if ctx["active"]:
        notes.append(
            f"Đã hiệu chỉnh theo {ctx['games']} ván TI 2026 đã đấu: trọng số hero ×"
            f"{ctx['hero_mult']:.2f}, thời lượng {ctx['duration_shift']*100:+.1f}% log.")

    return {
        "win_probability": {
            "a": round(p_a, 4),
            "b": round(1 - p_a, 4),
            "favourite": team_a["name"] if p_a >= 0.5 else team_b["name"],
            "edge": round(abs(p_a - 0.5) * 2, 4),
        },
        "duration": {
            "line_minutes": line_minutes,
            "expected_minutes": round(median_min, 1),
            "mean_minutes": round(mean_min, 1),
            "p_over": round(p_over, 4),
            "p_under": round(1 - p_over, 4),
            "pick": "OVER" if p_over >= 0.5 else "UNDER",
            "sigma_log": round(sigma, 4),
            "baseline_minutes": round(math.exp(base["mu"]) / 60, 1),
            "sample": base["n"],
            "baseline_days": base.get("days"),
        },
        "factors": {
            "team_strength": {
                "a_rating": round(sa["rating"], 1),
                "b_rating": round(sb["rating"], 1),
                "logit": round(team_logit, 4),
            },
            "hero_winrate": {"raw": round(hero_raw, 4), "logit": round(hero_logit, 4)},
            "hero_matchups": {"raw": round(matchup_raw, 4), "logit": round(matchup_logit, 4)},
            "player_heroes": {
                "raw": round(player_raw, 4),
                "logit": round(player_logit, 4),
                "assigned": len(assigned),
                "a": lineup_a,
                "b": lineup_b,
            },
            "draft_total_logit": round(draft_logit, 4),
            "total_logit": round(total_logit, 4),
            "duration_terms": {
                "baseline_log": round(base["mu"], 4),
                "meta_shift_log": round(sample["shift"], 4),
                "team_pace_log": round(pace, 4),
                "hero_draft_log": round(hero_delta, 4),
                "ti_context_log": round(ctx["duration_shift"], 4),
            },
            "ti_context": {
                "active": ctx["active"],
                "games": ctx["games"],
                "hero_mult": round(ctx["hero_mult"], 3),
                "matchup_mult": round(ctx["matchup_mult"], 3),
                "duration_shift": round(ctx["duration_shift"], 4),
            },
        },
        "teams": {
            "a": {**team_a, "strength": sa, "form": recent_form(team_a.get("team_id"))},
            "b": {**team_b, "strength": sb, "form": recent_form(team_b.get("team_id"))},
        },
        "head_to_head": head_to_head(team_a.get("team_id"), team_b.get("team_id")),
        "confidence": confidence,
        "notes": notes,
    }
