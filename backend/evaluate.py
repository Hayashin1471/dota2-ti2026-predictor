"""Backtest the model and fit its term weights on real match outcomes.

What this can and cannot do:

* **Can** fit `W_TEAM / W_HERO_WINRATE / W_MATCHUP` by maximising log-likelihood
  over every stored pro match that has a draft, and report out-of-sample
  accuracy on a later time slice.  That is a real fit on ~1500 matches.
* **Cannot** identify those three weights from a couple of days of TI.  Sixty
  games cannot pin down three free parameters; asking them to would just fit
  noise.  So TI games are *not* what the weights are fitted on.
* **Can**, however, fit *two* things from those sixty games, because each is a
  single number with a strong prior sitting on it: how much the hero-win-rate
  term is worth at TI (`hero_mult`) and how much longer TI games run
  (`duration_shift`).  Both are shrunk toward "no correction" by a pseudo-count,
  so two days nudge and a full tournament decides.  See `fit_ti_context`.

Leakage: the team-strength feature uses `matches.pre_elo_*`, the rating each
side carried *into* that game, so it never sees the result.  The hero win-rate
and matchup tables are current aggregates, so for older matches they do carry a
little hindsight; the reported numbers are mildly optimistic on that term.
"""
from __future__ import annotations

import math
import time

from . import config, db, model

RADIANT = 0
DIRE = 1


# --------------------------------------------------------------------------
# series reconstruction
# --------------------------------------------------------------------------
def series_index() -> dict[int, dict]:
    """match_id -> which series the map belongs to and the score before it.

    Nothing in the data says "these three games were one Bo3", so the series
    are rebuilt from the match log: the same pair of teams, in the same league,
    starting games within `SERIES_MAX_GAP` of each other.

    This walks **every** stored match, not just the ones with drafts.  Rebuild
    it from the drafted subset instead and a series whose first map was never
    downloaded would look like it started at 0-0 on its second map, which is
    exactly the row the carry-over term is measured on.
    """
    rows = db.query(
        "SELECT match_id, start_time, radiant_id, dire_id, radiant_win, league_name "
        "FROM matches WHERE radiant_win IS NOT NULL AND radiant_id IS NOT NULL "
        "AND dire_id IS NOT NULL AND duration BETWEEN ? AND ? ORDER BY start_time ASC",
        (model.MIN_DURATION, model.MAX_DURATION))

    out: dict[int, dict] = {}
    open_series: dict[tuple, dict] = {}
    for r in rows:
        pair = tuple(sorted((r["radiant_id"], r["dire_id"])))
        cur = open_series.get(pair)
        if not (cur and r["league_name"] == cur["league"]
                and (r["start_time"] or 0) - cur["last"] <= config.SERIES_MAX_GAP):
            cur = {"key": f"{pair[0]}-{pair[1]}-{r['match_id']}", "league": r["league_name"],
                   "last": r["start_time"] or 0, "wins": {pair[0]: 0, pair[1]: 0}, "maps": 0}
            open_series[pair] = cur

        # the score is recorded as it stood *before* this map was played
        out[r["match_id"]] = {
            "series_key": cur["key"],
            "map_no": cur["maps"] + 1,
            "lead_radiant": cur["wins"][r["radiant_id"]] - cur["wins"][r["dire_id"]],
        }

        winner = r["radiant_id"] if r["radiant_win"] else r["dire_id"]
        cur["wins"][winner] += 1
        cur["maps"] += 1
        cur["last"] = r["start_time"] or cur["last"]
    return out


# --------------------------------------------------------------------------
# dataset
# --------------------------------------------------------------------------
def build_dataset(min_start: float | None = None, max_start: float | None = None,
                  require_drafts: bool = True) -> list[dict]:
    """One row per pro match with the three model features and the outcome."""
    table = model.hero_table()

    sql = ("SELECT match_id, start_time, duration, radiant_win, league_name, stage, "
           "radiant_id, dire_id, pre_elo_radiant, pre_elo_dire FROM matches "
           "WHERE duration BETWEEN ? AND ? AND radiant_win IS NOT NULL "
           "AND pre_elo_radiant IS NOT NULL AND pre_elo_dire IS NOT NULL")
    params: list = [model.MIN_DURATION, model.MAX_DURATION]
    if min_start:
        sql += " AND start_time >= ?"
        params.append(min_start)
    if max_start:
        sql += " AND start_time < ?"
        params.append(max_start)
    sql += " ORDER BY start_time ASC"

    rows = db.query(sql, params)
    if not rows:
        return []

    series = series_index()

    # picks for every match in one query beats one query per match
    picks: dict[int, dict[int, list[int]]] = {}
    for p in db.query(
            "SELECT match_id, hero_id, side FROM match_drafts WHERE is_pick = 1"):
        picks.setdefault(p["match_id"], {RADIANT: [], DIRE: []})[p["side"]].append(p["hero_id"])

    out: list[dict] = []
    for r in rows:
        draft = picks.get(r["match_id"])
        if require_drafts and (not draft or len(draft[RADIANT]) != 5 or len(draft[DIRE]) != 5):
            continue
        rad = draft[RADIANT] if draft else []
        dire = draft[DIRE] if draft else []

        x_team = (float(r["pre_elo_radiant"]) - float(r["pre_elo_dire"])) * model.LN10_OVER_400

        # public-match win rate only.  The pro-adjusted `winrate` is computed
        # from these very matches, so feeding it in would leak the outcomes.
        def hero_sum(ids):
            return sum(model.logit(table.get(h, {}).get("pub_winrate", 0.5)) for h in ids)

        x_hero = hero_sum(rad) - hero_sum(dire)

        x_match, pairs = 0.0, 0
        for a in rad:
            for b in dire:
                x_match += model.matchup_edge(a, b, table) - model.matchup_edge(b, a, table)
                pairs += 1
        if pairs:
            x_match = x_match / pairs * 5.0

        # the duration side of the model, reproduced per match
        raw = sum(table.get(h, {}).get("ln_duration_delta", 0.0) for h in rad + dire)
        hero_len = max(-model.HERO_DELTA_CAP,
                       min(model.HERO_DELTA_CAP, raw * model.HERO_DELTA_GAIN))
        pace = (model.team_pace(r["radiant_id"]) + model.team_pace(r["dire_id"])) / 2.0

        sr = series.get(r["match_id"]) or {"series_key": None, "map_no": 1, "lead_radiant": 0}
        out.append({
            "match_id": r["match_id"],
            "start_time": r["start_time"],
            "duration": r["duration"],
            "series_key": sr["series_key"],
            "map_no": sr["map_no"],
            "radiant_id": r["radiant_id"],
            "dire_id": r["dire_id"],
            # maps this map's radiant side had already won in the series
            "series_lead": sr["lead_radiant"],
            "y": 1.0 if r["radiant_win"] else 0.0,
            "league": r["league_name"],
            "stage": r["stage"],
            "x_team": x_team,
            "x_hero": x_hero,
            "x_matchup": x_match,
            "ln_len_shift": hero_len + pace,
        })
    return out


# --------------------------------------------------------------------------
# fitting
# --------------------------------------------------------------------------
FEATURES = ("x_team", "x_hero", "x_matchup")


def _predict_logit(row: dict, w: dict, bias: float, context: dict | None = None) -> float:
    mult = {"x_team": 1.0,
            "x_hero": (context or {}).get("hero_mult", 1.0),
            "x_matchup": (context or {}).get("matchup_mult", 1.0)}
    return bias + sum(w[f] * row[f] * mult[f] for f in FEATURES)


def fit_weights(rows: list[dict], l2: float = 2.0, iterations: int = 800,
                lr: float = 0.35) -> tuple[dict, float]:
    """Maximise the L2-penalised log-likelihood by gradient ascent.

    Three features and a bias: batch gradient ascent converges fine and keeps
    the dependency list at zero.  The bias absorbs the radiant-side advantage,
    which the app itself cannot use (the user picks teams, not sides), but
    leaving it out would push that advantage into the other weights.
    """
    if not rows:
        return {f: getattr(config, k) for f, k in
                zip(FEATURES, ("W_TEAM", "W_HERO_WINRATE", "W_MATCHUP"))}, 0.0

    w = {"x_team": config.W_TEAM, "x_hero": config.W_HERO_WINRATE,
         "x_matchup": config.W_MATCHUP}
    bias = 0.0
    n = len(rows)

    for _ in range(iterations):
        g = {f: 0.0 for f in FEATURES}
        gb = 0.0
        for r in rows:
            err = r["y"] - model.sigmoid(_predict_logit(r, w, bias))
            gb += err
            for f in FEATURES:
                g[f] += err * r[f]
        for f in FEATURES:
            w[f] += lr * (g[f] / n - l2 * w[f] / n)
        bias += lr * gb / n

    # a negative weight would mean "the stronger team is less likely to win",
    # which is noise fitting rather than signal
    for f in FEATURES:
        w[f] = max(0.0, min(3.0, w[f]))
    return w, bias


# --------------------------------------------------------------------------
# series carry-over: what being up a map is worth
# --------------------------------------------------------------------------
def fit_series_momentum(rows: list[dict], w: dict, bias: float,
                        test_fraction: float = 0.3) -> dict:
    """How much a map of series lead adds, in log-odds, on top of everything else.

    Only maps played at an uneven series score carry any information about
    this, so the fit runs on those and leaves the rest alone.  The offset is
    the model's own prediction for the map, which means the coefficient
    measures what is left *after* team strength, the draft and - importantly -
    the Elo bump the team already got for winning the previous map.  Half the
    raw carry-over is already priced in there; this is the other half.

    Same discipline as the term weights: fit on the older matches, score the
    newer ones, and only keep a coefficient that beat zero on games it had not
    seen.  Unlike the TI corrections this one has thousands of maps behind it,
    so it usually survives.

    The TI slice is reported but deliberately *not* what decides the outcome.
    Seventy TI maps disagreeing with three thousand pro maps is what a seventy
    game sample looks like, not a discovery about TI.
    """
    informative = [r for r in rows if r.get("series_lead")]
    out: dict = {"coefficient": 0.0, "maps": len(informative), "fitted_at": time.time()}
    if len(informative) < 300:
        out["note"] = (f"only {len(informative)} maps played at an uneven series "
                       f"score - need 300 before measuring carry-over")
        return out

    informative.sort(key=lambda r: r["start_time"])

    def nll(rs: list[dict], c: float) -> float:
        t = 0.0
        for r in rs:
            z = _predict_logit(r, w, bias) + c * r["series_lead"]
            p = min(max(model.sigmoid(z), 1e-9), 1 - 1e-9)
            t += r["y"] * math.log(p) + (1 - r["y"]) * math.log(1 - p)
        return -t / len(rs)

    cap = config.SERIES_MOMENTUM_CAP
    grid = [i / 200.0 for i in range(int(-cap * 200), int(cap * 200) + 1)]

    def best_c(rs: list[dict]) -> float:
        return min(((nll(rs, c), c) for c in grid))[1]

    split = int(len(informative) * (1 - test_fraction))
    train, test = informative[:split], informative[split:]
    c_split = best_c(train)
    plain, fitted = nll(test, 0.0), nll(test, c_split)
    survived = fitted < plain

    # A thin sample should not produce a confident number even when it wins the
    # check, so the value that ships is pulled toward "no carry-over".
    raw = best_c(informative)
    shrunk = _shrink(raw, 0.0, len(informative), config.SERIES_MOMENTUM_PRIOR)
    out.update({
        "coefficient": round(shrunk, 4) if survived else 0.0,
        "raw": round(raw, 4),
        "shrunk": round(shrunk, 4),
        "validation": {
            "fitted_on": len(train),
            "scored_on": len(test),
            "boundary": time.strftime("%Y-%m-%d",
                                      time.localtime(test[0]["start_time"])),
            "trial_coefficient": round(c_split, 4),
            "log_loss": {"without": round(plain, 4), "with": round(fitted, 4),
                         "kept": survived},
        },
    })

    # the TI slice, reported and not acted on
    ti_maps = [r for r in informative if is_ti(r)]
    if ti_maps:
        out["ti_slice"] = {
            "maps": len(ti_maps),
            "log_loss": {"without": round(nll(ti_maps, 0.0), 4),
                         "with": round(nll(ti_maps, out["coefficient"]), 4)},
            "note": "reported only - too few maps to overrule the full sample",
        }

    out["note"] = (f"carry-over of {out['coefficient']:+.3f} log-odds per map of lead"
                   if survived else
                   "carry-over failed its out-of-sample check - maps are treated "
                   "as independent")
    return out


# --------------------------------------------------------------------------
# tournament context: what the TI games played so far say about TI games
# --------------------------------------------------------------------------
def is_ti(row: dict) -> bool:
    # exactly the main event; the qualifiers carry a " - Regional Qualifier X" suffix
    return (row["league"] or "").strip() == config.TI_LEAGUE_NAME


def _shrink(estimate: float, toward: float, n: int, prior: int) -> float:
    """Pull an estimate back toward a default in proportion to how thin it is."""
    return toward + (estimate - toward) * n / (n + prior)


def fit_ti_context(ti_rows: list[dict], w: dict, bias: float,
                   validate: bool = True) -> dict:
    """Fit the TI corrections on the TI matches played so far, and gate them.

    Each is one free parameter with an obvious null value, which is why a
    hundred games is enough for them and nowhere near enough for the three term
    weights.

    * `hero_mult` scales the hero-win-rate term.  Searched on a coarse grid
      rather than by gradient: the likelihood in one dimension is smooth and
      cheap, and a grid cannot run away to a silly value.
    * `matchup_mult` does the same for the hero-vs-hero term, and is fitted
      alongside it so neither absorbs the other's error.
    * `duration_shift` is the mean log-duration residual left over after the
      baseline, the team pace and the draft have had their say.

    **Fitting them is not enough to ship them.**  Shrinkage keeps the numbers
    modest but cannot tell a real effect from a lucky one, and the first version
    of this function shipped whatever it fitted: after two days of TI it had
    learned `hero_mult = 0.50` from what turned out to be noise, and that
    correction then made day three's predictions worse than leaving the model
    alone.  So the corrections now have to earn their place on games they were
    not fitted on - fit on the first half of TI, score the second half, keep
    only what beats doing nothing.  The two halves of the model are gated
    separately because they answer different questions: the draft multipliers on
    win-probability log-loss, the duration shift on over/under Brier.
    """
    n = len(ti_rows)
    out = {"games": n, "hero_mult": 1.0, "matchup_mult": 1.0,
           "duration_shift": 0.0, "fitted_at": time.time()}
    # Validation needs two halves that each clear the minimum, so the threshold
    # to correct anything at all is twice TI_CONTEXT_MIN_GAMES.  An unvalidated
    # correction is exactly the thing that went wrong, so "too early to check"
    # means "too early to apply".
    need = config.TI_CONTEXT_MIN_GAMES * (2 if validate else 1)
    if n < need:
        out["note"] = (f"only {n} TI matches with drafts - need {need} before "
                       f"correcting anything")
        return out

    # --- draft multipliers ------------------------------------------------
    grid = [i / 20 for i in range(0, 31)]        # 0.00 .. 1.50

    def nll(mh: float, mm: float) -> float:
        t = 0.0
        for r in ti_rows:
            z = (bias + w["x_team"] * r["x_team"]
                 + mh * w["x_hero"] * r["x_hero"]
                 + mm * w["x_matchup"] * r["x_matchup"])
            p = min(max(model.sigmoid(z), 1e-6), 1 - 1e-6)
            t += r["y"] * math.log(p) + (1 - r["y"]) * math.log(1 - p)
        return -t / len(ti_rows)

    best = min(((nll(a, b), a, b) for a in grid for b in grid))
    raw_hero, raw_matchup = best[1], best[2]

    def clamp(x: float) -> float:
        return max(config.TI_MULT_FLOOR, min(config.TI_MULT_CEIL, x))

    out["hero_mult"] = round(clamp(_shrink(raw_hero, 1.0, n, config.TI_DRAFT_PRIOR_GAMES)), 4)
    out["matchup_mult"] = round(clamp(_shrink(raw_matchup, 1.0, n, config.TI_DRAFT_PRIOR_GAMES)), 4)

    # --- duration offset ---------------------------------------------------
    base = model.duration_baseline()
    mu_default = base["mu"] + model.draft_sample_stats()["shift"]
    resid = [math.log(r["duration"]) - (mu_default + r["ln_len_shift"]) for r in ti_rows]
    mean_resid = sum(resid) / n
    sd = math.sqrt(sum((x - mean_resid) ** 2 for x in resid) / max(1, n - 1))
    shift = _shrink(mean_resid, 0.0, n, config.TI_DURATION_PRIOR_GAMES)
    out["duration_shift"] = round(max(-config.TI_DURATION_SHIFT_CAP,
                                      min(config.TI_DURATION_SHIFT_CAP, shift)), 4)

    out["raw"] = {
        "hero_mult": raw_hero,
        "matchup_mult": raw_matchup,
        "duration_resid": round(mean_resid, 4),
        "duration_resid_se": round(sd / math.sqrt(n), 4),
        "nll_at_fit": round(best[0], 4),
        "nll_uncorrected": round(nll(1.0, 1.0), 4),
        "median_minutes": round(math.exp(mu_default + mean_resid) / 60, 1),
    }

    if validate:
        out.update(_validate_context(ti_rows, w, bias, out))
    return out


def _validate_context(ti_rows: list[dict], w: dict, bias: float,
                      fitted: dict) -> dict:
    """Refit on the older half of TI, score the newer half, keep what wins.

    Returns the fields to overwrite on the fitted context: whichever half of the
    correction failed is reset to its neutral value, and the numbers behind the
    decision are kept so `evaluate` can print them.
    """
    half = len(ti_rows) // 2
    early, late = ti_rows[:half], ti_rows[half:]
    trial = fit_ti_context(early, w, bias, validate=False)

    plain = score(late, w, bias)
    fixed = score(late, w, bias, context=trial)
    draft_ok = fixed["log_loss"] <= plain["log_loss"]
    dur_ok = fixed["over_under"]["brier"] <= plain["over_under"]["brier"]

    out: dict = {
        "validation": {
            "fitted_on": len(early),
            "scored_on": len(late),
            "boundary": time.strftime("%Y-%m-%d %H:%M",
                                      time.localtime(late[0]["start_time"])),
            "trial_context": {k: trial[k] for k in
                              ("hero_mult", "matchup_mult", "duration_shift")},
            "log_loss": {"without": plain["log_loss"], "with": fixed["log_loss"],
                         "kept": draft_ok},
            "over_under_brier": {"without": plain["over_under"]["brier"],
                                 "with": fixed["over_under"]["brier"],
                                 "kept": dur_ok},
        },
    }
    if not draft_ok:
        out["hero_mult"] = 1.0
        out["matchup_mult"] = 1.0
    if not dur_ok:
        out["duration_shift"] = 0.0

    kept = [name for name, ok in (("draft", draft_ok), ("duration", dur_ok)) if ok]
    out["note"] = ("kept: " + ", ".join(kept)) if kept else \
        ("no correction survived out-of-sample validation - the model runs "
         "exactly as it would without any TI adjustment")
    return out


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
def score(rows: list[dict], w: dict, bias: float = 0.0,
          line_minutes: float = config.OVER_UNDER_LINE_MIN,
          context: dict | None = None, momentum: float = 0.0) -> dict:
    """Win-probability and over/under metrics for a set of matches.

    `context` applies the TI corrections, and only to the rows that are TI
    matches, so a mixed set is scored the same way the app would score it.
    `momentum` adds the series carry-over, which is zero for any map opening a
    series and so only moves the rows played at an uneven score.
    """
    if not rows:
        return {"n": 0}

    base = model.duration_baseline()
    sample = model.draft_sample_stats()
    mu_default = base["mu"] + sample["shift"]
    sigma = max(0.16, base["sigma"] * 0.97)
    line_sec = line_minutes * 60.0

    ll = brier = 0.0
    correct = 0
    ou_correct = 0
    ou_brier = 0.0
    actual_over = 0

    for r in rows:
        ctx = context if (context and is_ti(r)) else None
        z = _predict_logit(r, w, bias, ctx) + momentum * r.get("series_lead", 0)
        p = min(max(model.sigmoid(z), 1e-6), 1 - 1e-6)
        y = r["y"]
        ll += y * math.log(p) + (1 - y) * math.log(1 - p)
        brier += (p - y) ** 2
        correct += (p >= 0.5) == (y == 1.0)

        # duration side: baseline shifted by this match's draft and team pace,
        # exactly as `model.predict` does it
        mu = mu_default + r.get("ln_len_shift", 0.0)
        if ctx:
            mu += ctx.get("duration_shift", 0.0)
        p_over = 1.0 - model._norm_cdf((math.log(line_sec) - mu) / sigma)
        over = 1.0 if r["duration"] > line_sec else 0.0
        actual_over += over
        ou_brier += (p_over - over) ** 2
        ou_correct += (p_over >= 0.5) == (over == 1.0)

    n = len(rows)
    # a coin flip scores 0.693 log-loss / 0.25 Brier; lower is better
    return {
        "n": n,
        "log_loss": round(-ll / n, 4),
        "brier": round(brier / n, 4),
        "accuracy": round(correct / n, 4),
        "baseline_log_loss": round(math.log(2), 4),
        "over_under": {
            "line_minutes": line_minutes,
            "actual_over_rate": round(actual_over / n, 4),
            "accuracy": round(ou_correct / n, 4),
            "brier": round(ou_brier / n, 4),
        },
    }


def score_series(rows: list[dict], w: dict, bias: float = 0.0,
                 momentum: float = 0.0, context: dict | None = None) -> dict:
    """Score the *series* call made before its first map was played.

    The main event asks who wins a Bo3, not who wins a map, and the two are
    different questions: a 55% map favourite is a 57.5% series favourite, and a
    model that is right about maps can still be wrong about brackets.  This
    rebuilds each series from the rows, predicts it from the first map's
    features alone - the only ones that exist before it starts - and scores the
    call against what the series actually did.

    Series that ended level (a drawn Bo2) are dropped: nobody won them, so
    there is nothing to be right or wrong about.
    """
    groups: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("series_key"):
            groups.setdefault(r["series_key"], []).append(r)

    ll = brier = 0.0
    correct = n = 0
    detail = []
    for key, maps in groups.items():
        maps.sort(key=lambda r: r["map_no"])
        if len(maps) < 2:
            continue
        first = maps[0]
        # Sides swap between maps, so `radiant_win` cannot be compared across
        # them directly.  Score the series from the point of view of whichever
        # team started map one on radiant, and follow that team by its id.
        team = first["radiant_id"]
        wins = sum(1 for m in maps
                   if (m["y"] == 1.0) == (m["radiant_id"] == team))
        total = len(maps)
        if wins * 2 == total:
            continue                        # drawn Bo2 - no series winner
        y = 1.0 if wins * 2 > total else 0.0
        best_of = total if total % 2 else total + 1
        ctx = context if (context and is_ti(first)) else None
        p_map = model.sigmoid(_predict_logit(first, w, bias, ctx))
        p = model.series_outcome(p_map, best_of=best_of, momentum=momentum)["p_series"]["a"]
        p = min(max(p, 1e-6), 1 - 1e-6)
        ll += y * math.log(p) + (1 - y) * math.log(1 - p)
        brier += (p - y) ** 2
        correct += (p >= 0.5) == (y == 1.0)
        n += 1
        detail.append({"series": key, "maps": total, "p_map": round(p_map, 3),
                       "p_series": round(p, 3), "won": bool(y),
                       "when": time.strftime("%Y-%m-%d",
                                             time.localtime(first["start_time"]))})

    if not n:
        return {"n": 0}
    return {
        "n": n,
        "log_loss": round(-ll / n, 4),
        "brier": round(brier / n, 4),
        "accuracy": round(correct / n, 4),
        "baseline_log_loss": round(math.log(2), 4),
        "detail": detail,
    }


def calibration(rows: list[dict], w: dict, bias: float = 0.0, buckets: int = 5) -> list[dict]:
    """Predicted vs observed win rate, to see whether the numbers mean anything."""
    edges = [i / buckets for i in range(buckets + 1)]
    out = []
    for i in range(buckets):
        lo, hi = edges[i], edges[i + 1]
        sel = []
        for r in rows:
            p = model.sigmoid(_predict_logit(r, w, bias))
            if lo <= p < hi or (i == buckets - 1 and p == 1.0):
                sel.append((p, r["y"]))
        if not sel:
            continue
        out.append({
            "range": f"{lo:.0%}-{hi:.0%}",
            "n": len(sel),
            "predicted": round(sum(p for p, _ in sel) / len(sel), 4),
            "observed": round(sum(y for _, y in sel) / len(sel), 4),
        })
    return out


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def run(test_fraction: float = 0.25, apply: bool = False,
        today_only_start: float | None = None,
        holdout_label: str = "recent") -> dict:
    """Fit, measure honestly on a later time slice, then refit on everything.

    Two fits happen here and they answer different questions.  The *split* fit
    (old 75% -> new 25%) is the measurement: it is the only number that says
    whether the model generalises.  The *full* fit is what actually gets stored,
    because throwing away the newest quarter of the data - the quarter closest
    to the games being predicted - would be leaving information on the table.
    """
    rows = build_dataset()
    if len(rows) < 200:
        return {"error": f"only {len(rows)} matches with full drafts - run "
                         f"`python -m backend refresh drafts` to collect more"}

    split = int(len(rows) * (1 - test_fraction))
    train, test = rows[:split], rows[split:]

    w, bias = fit_weights(train)                    # measured
    w_full, bias_full = fit_weights(rows)           # stored

    baseline_w = {"x_team": config.W_TEAM, "x_hero": config.W_HERO_WINRATE,
                  "x_matchup": config.W_MATCHUP}

    ti_rows = [r for r in rows if is_ti(r)]
    # Fit the TI corrections on the **group stage** only.  The group phase is a
    # round-robin among all sixteen teams; the bracket that follows is knockout
    # between survivors, which is a different thing being measured.  Keeping the
    # bracket out of the fit also leaves it as a forward test - the one slice of
    # TI the corrections have genuinely never seen.
    group_rows = [r for r in ti_rows if r["stage"] != "playoff"]
    playoff_rows = [r for r in ti_rows if r["stage"] == "playoff"]

    # The corrections are fitted with the split weights, so the numbers reported
    # for them are not scored by a model that has already seen the test slice.
    context = fit_ti_context(group_rows, w, bias)
    context_full = fit_ti_context(group_rows, w_full, bias_full)

    # The carry-over is a property of pro series in general, not of TI, so it
    # is fitted on everything - measured with the split weights, stored with
    # the full ones, the same split the term weights use.
    momentum = fit_series_momentum(train, w, bias)
    momentum_full = fit_series_momentum(rows, w_full, bias_full)
    c = float(momentum["coefficient"])
    c_full = float(momentum_full["coefficient"])

    result = {
        "dataset": {
            "matches": len(rows),
            "train": len(train),
            "test": len(test),
            "ti_matches": len(ti_rows),
            "ti_group": len(group_rows),
            "ti_playoff": len(playoff_rows),
            "from": time.strftime("%Y-%m-%d", time.localtime(rows[0]["start_time"])),
            "to": time.strftime("%Y-%m-%d", time.localtime(rows[-1]["start_time"])),
        },
        "fitted_weights": {"team": round(w_full["x_team"], 4),
                           "hero": round(w_full["x_hero"], 4),
                           "matchup": round(w_full["x_matchup"], 4),
                           "radiant_bias": round(bias_full, 4),
                           "note": "stored; fitted on all matches"},
        "split_weights": {"team": round(w["x_team"], 4),
                          "hero": round(w["x_hero"], 4),
                          "matchup": round(w["x_matchup"], 4),
                          "radiant_bias": round(bias, 4),
                          "note": "measured; fitted on the training slice only"},
        "config_weights": {"team": config.W_TEAM, "hero": config.W_HERO_WINRATE,
                           "matchup": config.W_MATCHUP},
        "ti_context": context_full,
        "series_momentum": momentum_full,
        "train_score": score(train, w, bias),
        "test_score": score(test, w, bias),
        "test_score_with_config_weights": score(test, baseline_w, 0.0),
        "calibration_test": calibration(test, w, bias),
    }

    # --- the series question, which is the one the main event asks ---------
    # Every bracket match is a Bo3 and the final a Bo5, so "who wins the map"
    # is only half an answer.  These are scored on the call made before the
    # first map, the only information a bracket prediction ever has.
    result["series_score"] = {
        "test": {
            "independent_maps": score_series(test, w, bias, momentum=0.0),
            "with_carry_over": score_series(test, w, bias, momentum=c),
        },
        "note": "Series rebuilt from the match log by pairing, league and start "
                "time; drawn Bo2s are excluded because nobody won them.",
    }
    for name, slice_ in (("ti_group", group_rows), ("ti_playoff", playoff_rows)):
        sc = score_series(slice_, w, bias, momentum=c, context=context)
        if sc.get("n"):
            result["series_score"][name] = sc

    # --- the carry-over, on the only rows it can move ---------------------
    # A map opening a series has a lead of zero and is untouched by the term,
    # so scoring it over a whole slice dilutes the effect to nothing.  These
    # are the maps played at 1-0 or better.
    result["carry_over_effect"] = {
        "note": "Only maps played at an uneven series score; every other map is "
                "identical with and without the term.",
        "coefficient": c,
    }
    for name, slice_ in (("test", test), ("ti_group", group_rows),
                         ("ti_playoff", playoff_rows)):
        mid = [r for r in slice_ if r.get("series_lead")]
        if len(mid) < 4:
            continue
        ctx = context if name.startswith("ti") else None
        result["carry_over_effect"][name] = {
            "maps": len(mid),
            "without": score(mid, w, bias, context=ctx)["log_loss"],
            "with": score(mid, w, bias, context=ctx, momentum=c)["log_loss"],
            "accuracy_without": score(mid, w, bias, context=ctx)["accuracy"],
            "accuracy_with": score(mid, w, bias, context=ctx, momentum=c)["accuracy"],
        }

    # --- what the TI corrections are worth, on the games they were fitted on --
    if group_rows:
        result["ti_context_effect"] = {
            "matches": len(group_rows),
            "stage": "group",
            "without_context": score(group_rows, w, bias),
            "with_context": score(group_rows, w, bias, context=context),
            "non_ti_unaffected": True,
            "note": "In-sample for the corrections: they were fitted on these "
                    "very games, so this is an upper bound, not a measurement.",
        }

        # The gate that decided whether any of this ships, reported verbatim.
        if context.get("validation"):
            result["ti_context_holdout"] = context["validation"]

    # --- the bracket: never fitted on, so this one really is a forward test --
    if playoff_rows:
        raw_ctx = {"hero_mult": context["raw"]["hero_mult"],
                   "matchup_mult": context["raw"]["matchup_mult"],
                   "duration_shift": context["raw"]["duration_resid"]} \
            if context.get("raw") else None
        result["playoff_forward_test"] = {
            "matches": len(playoff_rows),
            "plain_model": score(playoff_rows, w, bias),
            "with_group_context": score(playoff_rows, w, bias, context=context),
            # what the model would have done had the raw group-stage fit been
            # shipped unshrunk and ungated - the mistake this file now prevents
            "with_raw_group_fit": score(playoff_rows, w, bias, context=raw_ctx)
            if raw_ctx else None,
            "note": "The bracket is knockout between the surviving teams, so it "
                    "is not a random sample of TI either; a dozen games is an "
                    "anecdote. Read it as a sanity check, not a verdict.",
        }

    # a named slice scored as a held-out sample (never trained on)
    if today_only_start:
        recent = [r for r in rows if r["start_time"] >= today_only_start]
        ti_recent = [r for r in recent if is_ti(r)]
        result["holdout"] = {
            "label": holdout_label,
            "since": time.strftime("%Y-%m-%d %H:%M", time.localtime(today_only_start)),
            "all_pro_matches": score(recent, w, bias),
            "ti_2026_only": score(ti_recent, w, bias),
            "ti_matches": [
                {
                    "match_id": r["match_id"],
                    "time": time.strftime("%H:%M", time.localtime(r["start_time"])),
                    "p_radiant": round(model.sigmoid(_predict_logit(r, w, bias)), 3),
                    "radiant_won": bool(r["y"]),
                    "hit": (model.sigmoid(_predict_logit(r, w, bias)) >= 0.5) == (r["y"] == 1.0),
                    "duration_min": round(r["duration"] / 60, 1),
                }
                for r in ti_recent
            ],
            "inside_test_window": bool(test) and today_only_start >= test[0]["start_time"],
            "note": "Held out: these games are after the fit window. A sample "
                    "this small is an anecdote, not a measurement.",
        }

    if apply:
        db.set_meta("fitted_weights", {
            "team": round(w_full["x_team"], 4),
            "hero": round(w_full["x_hero"], 4),
            "matchup": round(w_full["x_matchup"], 4),
            "radiant_bias": round(bias_full, 4),
            "fitted_at": time.time(),
            "trained_on": len(rows),
        })
        db.set_meta("ti_context", context_full)
        db.set_meta("series_momentum", momentum_full)
        model.invalidate_cache()
        result["applied"] = True

    return result
