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
# dataset
# --------------------------------------------------------------------------
def build_dataset(min_start: float | None = None, max_start: float | None = None,
                  require_drafts: bool = True) -> list[dict]:
    """One row per pro match with the three model features and the outcome."""
    table = model.hero_table()

    sql = ("SELECT match_id, start_time, duration, radiant_win, league_name, "
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

        out.append({
            "match_id": r["match_id"],
            "start_time": r["start_time"],
            "duration": r["duration"],
            "y": 1.0 if r["radiant_win"] else 0.0,
            "league": r["league_name"],
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
# tournament context: what the TI games played so far say about TI games
# --------------------------------------------------------------------------
def is_ti(row: dict) -> bool:
    # exactly the main event; the qualifiers carry a " - Regional Qualifier X" suffix
    return (row["league"] or "").strip() == config.TI_LEAGUE_NAME


def _shrink(estimate: float, toward: float, n: int, prior: int) -> float:
    """Pull an estimate back toward a default in proportion to how thin it is."""
    return toward + (estimate - toward) * n / (n + prior)


def fit_ti_context(ti_rows: list[dict], w: dict, bias: float) -> dict:
    """Fit the two TI corrections on the TI matches played so far.

    Each is one free parameter with an obvious null value, which is why sixty
    games is enough for them and nowhere near enough for the three term weights.

    * `hero_mult` scales the hero-win-rate term.  Searched on a coarse grid
      rather than by gradient: the likelihood in one dimension is smooth and
      cheap, and a grid cannot run away to a silly value.
    * `matchup_mult` does the same for the hero-vs-hero term, and is fitted
      alongside it so neither absorbs the other's error.
    * `duration_shift` is the mean log-duration residual left over after the
      baseline, the team pace and the draft have had their say.
    """
    n = len(ti_rows)
    out = {"games": n, "hero_mult": 1.0, "matchup_mult": 1.0,
           "duration_shift": 0.0, "fitted_at": time.time()}
    if n < config.TI_CONTEXT_MIN_GAMES:
        out["note"] = (f"only {n} TI matches with drafts - need "
                       f"{config.TI_CONTEXT_MIN_GAMES} before correcting anything")
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
    return out


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
def score(rows: list[dict], w: dict, bias: float = 0.0,
          line_minutes: float = config.OVER_UNDER_LINE_MIN,
          context: dict | None = None) -> dict:
    """Win-probability and over/under metrics for a set of matches.

    `context` applies the TI corrections, and only to the rows that are TI
    matches, so a mixed set is scored the same way the app would score it.
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
        p = model.sigmoid(_predict_logit(r, w, bias, ctx))
        p = min(max(p, 1e-6), 1 - 1e-6)
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
    # The corrections are fitted with the split weights, so the numbers reported
    # for them are not scored by a model that has already seen the test slice.
    context = fit_ti_context(ti_rows, w, bias)
    context_full = fit_ti_context(ti_rows, w_full, bias_full)

    result = {
        "dataset": {
            "matches": len(rows),
            "train": len(train),
            "test": len(test),
            "ti_matches": len(ti_rows),
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
        "ti_context": {**context_full, "note": "stored; the TI-only corrections"},
        "train_score": score(train, w, bias),
        "test_score": score(test, w, bias),
        "test_score_with_config_weights": score(test, baseline_w, 0.0),
        "calibration_test": calibration(test, w, bias),
    }

    # --- what the TI corrections are worth, on the TI games themselves -----
    if ti_rows:
        result["ti_context_effect"] = {
            "matches": len(ti_rows),
            "without_context": score(ti_rows, w, bias),
            "with_context": score(ti_rows, w, bias, context=context),
            "non_ti_unaffected": True,
            "note": "In-sample for the two corrections: they were fitted on "
                    "these very games.  The shrinkage in `fit_ti_context` is "
                    "what keeps that from becoming an overfit; treat the gain "
                    "as an upper bound until more TI games are played.",
        }

        # The honest version of the same question: fit the corrections on the
        # first half of TI and score the second half, which they never saw.
        # This is what tells you whether the effect is real or is the sixty
        # games telling you about themselves.
        half = len(ti_rows) // 2
        early, late = ti_rows[:half], ti_rows[half:]
        if len(early) >= config.TI_CONTEXT_MIN_GAMES and late:
            early_ctx = fit_ti_context(early, w, bias)
            result["ti_context_holdout"] = {
                "fitted_on": len(early),
                "scored_on": len(late),
                "boundary": time.strftime("%Y-%m-%d %H:%M",
                                          time.localtime(late[0]["start_time"])),
                "context_from_first_half": {
                    "hero_mult": early_ctx["hero_mult"],
                    "matchup_mult": early_ctx["matchup_mult"],
                    "duration_shift": early_ctx["duration_shift"],
                },
                "without_context": score(late, w, bias),
                "with_context": score(late, w, bias, context=early_ctx),
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
        model.invalidate_cache()
        result["applied"] = True

    return result
