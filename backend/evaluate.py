"""Backtest the model and fit its term weights on real match outcomes.

What this can and cannot do:

* **Can** fit `W_TEAM / W_HERO_WINRATE / W_MATCHUP` by maximising log-likelihood
  over every stored pro match that has a draft, and report out-of-sample
  accuracy on a later time slice.  That is a real fit on ~1500 matches.
* **Cannot** learn anything useful from a single day of TI.  Eighteen games
  cannot identify three weights; asking them to would just fit noise.  Today's
  games are therefore *scored* as a held-out sample, not trained on.

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


def _predict_logit(row: dict, w: dict, bias: float) -> float:
    return bias + sum(w[f] * row[f] for f in FEATURES)


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
# scoring
# --------------------------------------------------------------------------
def score(rows: list[dict], w: dict, bias: float = 0.0,
          line_minutes: float = config.OVER_UNDER_LINE_MIN) -> dict:
    """Win-probability and over/under metrics for a set of matches."""
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
        p = model.sigmoid(_predict_logit(r, w, bias))
        p = min(max(p, 1e-6), 1 - 1e-6)
        y = r["y"]
        ll += y * math.log(p) + (1 - y) * math.log(1 - p)
        brier += (p - y) ** 2
        correct += (p >= 0.5) == (y == 1.0)

        # duration side: baseline shifted by this match's draft and team pace,
        # exactly as `model.predict` does it
        mu = mu_default + r.get("ln_len_shift", 0.0)
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
    """Fit on the earlier matches, score on the later ones and on a holdout."""
    rows = build_dataset()
    if len(rows) < 200:
        return {"error": f"only {len(rows)} matches with full drafts - run "
                         f"`python -m backend refresh drafts` to collect more"}

    split = int(len(rows) * (1 - test_fraction))
    train, test = rows[:split], rows[split:]

    w, bias = fit_weights(train)

    baseline_w = {"x_team": config.W_TEAM, "x_hero": config.W_HERO_WINRATE,
                  "x_matchup": config.W_MATCHUP}

    result = {
        "dataset": {
            "matches": len(rows),
            "train": len(train),
            "test": len(test),
            "from": time.strftime("%Y-%m-%d", time.localtime(rows[0]["start_time"])),
            "to": time.strftime("%Y-%m-%d", time.localtime(rows[-1]["start_time"])),
        },
        "fitted_weights": {"team": round(w["x_team"], 4),
                           "hero": round(w["x_hero"], 4),
                           "matchup": round(w["x_matchup"], 4),
                           "radiant_bias": round(bias, 4)},
        "config_weights": {"team": config.W_TEAM, "hero": config.W_HERO_WINRATE,
                           "matchup": config.W_MATCHUP},
        "train_score": score(train, w, bias),
        "test_score": score(test, w, bias),
        "test_score_with_config_weights": score(test, baseline_w, 0.0),
        "calibration_test": calibration(test, w, bias),
    }

    # a named slice scored as a held-out sample (never trained on)
    if today_only_start:
        recent = [r for r in rows if r["start_time"] >= today_only_start]
        # exactly the main event; the qualifiers carry a " - Regional Qualifier X" suffix
        ti_recent = [r for r in recent if (r["league"] or "").strip() == "The International 2026"]
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
            "team": round(w["x_team"], 4),
            "hero": round(w["x_hero"], 4),
            "matchup": round(w["x_matchup"], 4),
            "radiant_bias": round(bias, 4),
            "fitted_at": time.time(),
            "trained_on": len(train),
        })
        model.invalidate_cache()
        result["applied"] = True

    return result
