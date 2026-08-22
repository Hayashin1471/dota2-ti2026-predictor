"""Walk what is left of the TI 2026 main event bracket and price every path.

    python tools/bracket_sim.py

The remaining tree is small enough to enumerate in full, so nothing here is a
Monte Carlo estimate: each number is exactly what the model implies given the
bracket state written in `STATE` below.  Update `STATE` after each series and
run it again.

Each map is priced by `model.predict` with no draft known - team strength only,
which is all a bracket forecast ever has before the game starts.  Series are
then rolled up by `model.series_outcome`, so the carry-over term measured in
`evaluate.fit_series_momentum` applies inside a series exactly as it does in
the app.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import db, model                                  # noqa: E402

# --------------------------------------------------------------------------
# Where the bracket stands.  Edit this, nothing else.
# --------------------------------------------------------------------------
STATE = {
    # lower-bracket quarterfinal still being played, and the score so far
    "lb_quarterfinal": ("nigma-galaxy", "betboom-team", 1, 1),
    "upper_bracket_final": ("team-vision", "team-yandex", 0, 0),
    # already through to the lower-bracket semifinal, waiting for an opponent
    "lb_semifinal_seed": "team-spirit",
}

LABEL = {"team-vision": "TEAM VISION", "team-yandex": "Team Yandex",
         "team-spirit": "Team Spirit", "nigma-galaxy": "Nigma Galaxy",
         "betboom-team": "BoomBoys"}

db.init()
TEAMS = {r["slug"]: dict(r) for r in db.query("SELECT slug, name, team_id FROM ti_teams")}
_cache: dict[tuple, float] = {}


def p_map(a: str, b: str) -> float:
    """A's chance on one map with the series level - team strength only."""
    if (a, b) not in _cache:
        p = float(model.predict(TEAMS[a], TEAMS[b], [], [], best_of=1)
                  ["win_probability"]["a"])
        _cache[(a, b)], _cache[(b, a)] = p, 1.0 - p
    return _cache[(a, b)]


def series(a: str, b: str, best_of: int = 3, wa: int = 0, wb: int = 0) -> dict:
    return model.series_outcome(p_map(a, b), best_of=best_of, wins_a=wa, wins_b=wb)


def p_series(a: str, b: str, best_of: int = 3, wa: int = 0, wb: int = 0) -> float:
    return float(series(a, b, best_of, wa, wb)["p_series"]["a"])


def placings() -> dict[str, dict[str, float]]:
    """Enumerate every remaining path and add up where each team lands."""
    qa, qb, qwa, qwb = STATE["lb_quarterfinal"]
    ua, ub = STATE["upper_bracket_final"][:2]
    seed = STATE["lb_semifinal_seed"]

    out = {s: {"champion": 0.0, "final": 0.0, "top3": 0.0, "top4": 0.0}
           for s in LABEL}

    def land(p: float, first: str, second: str, third: str, fourth: str) -> None:
        out[first]["champion"] += p
        for s in (first, second):
            out[s]["final"] += p
        for s in (first, second, third):
            out[s]["top3"] += p
        for s in (first, second, third, fourth):
            out[s]["top4"] += p

    for lbq_win, p1 in ((qa, p_series(qa, qb, 3, qwa, qwb)),
                        (qb, p_series(qb, qa, 3, qwb, qwa))):
        for ub_win, p2 in ((ua, p_series(ua, ub)), (ub, p_series(ub, ua))):
            ub_lose = ub if ub_win == ua else ua
            for sf_win, p3 in ((seed, p_series(seed, lbq_win)),
                               (lbq_win, p_series(lbq_win, seed))):
                sf_lose = lbq_win if sf_win == seed else seed
                for lbf_win, p4 in ((ub_lose, p_series(ub_lose, sf_win)),
                                    (sf_win, p_series(sf_win, ub_lose))):
                    lbf_lose = sf_win if lbf_win == ub_lose else ub_lose
                    for champ, p5 in ((ub_win, p_series(ub_win, lbf_win, 5)),
                                      (lbf_win, p_series(lbf_win, ub_win, 5))):
                        runner = lbf_win if champ == ub_win else ub_win
                        land(p1 * p2 * p3 * p4 * p5, champ, runner,
                             third=lbf_lose, fourth=sf_lose)
    return out


def main() -> None:
    qa, qb, qwa, qwb = STATE["lb_quarterfinal"]
    ua, ub = STATE["upper_bracket_final"][:2]
    print("=== the two series on the board ===")
    for name, (a, b, wa, wb), bo in (
            ("LB quarterfinal", (qa, qb, qwa, qwb), 3),
            ("Upper bracket final", (ua, ub, 0, 0), 3)):
        s = series(a, b, bo, wa, wb)
        top = s["scorelines"][0]
        print(f"{name:22s} {LABEL[a]} vs {LABEL[b]} at {wa}-{wb}: "
              f"map {p_map(a, b):.3f}, series {s['p_series']['a']:.3f}, "
              f"most likely {top['a']}-{top['b']} ({top['p']:.0%})")

    print("\n=== every pairing still reachable ===")
    for a, b, bo in (("team-spirit", "nigma-galaxy", 3),
                     ("team-spirit", "betboom-team", 3),
                     ("team-vision", "team-spirit", 3),
                     ("team-yandex", "team-spirit", 3),
                     ("team-vision", "nigma-galaxy", 3),
                     ("team-yandex", "nigma-galaxy", 3),
                     ("team-vision", "betboom-team", 3),
                     ("team-yandex", "betboom-team", 3),
                     ("team-vision", "team-yandex", 5)):
        print(f"Bo{bo}  {LABEL[a]:14s} vs {LABEL[b]:14s} "
              f"map {p_map(a, b):.3f}  series {p_series(a, b, bo):.3f}")

    print("\n=== where they finish ===")
    table = placings()
    for slug, v in sorted(table.items(), key=lambda kv: -kv[1]["champion"]):
        print(f"{LABEL[slug]:14s} champion {v['champion']:6.1%}  "
              f"grand final {v['final']:6.1%}  top 3 {v['top3']:6.1%}  "
              f"top 4 {v['top4']:6.1%}")
    print("\ncheck: champion probabilities sum to",
          round(sum(v["champion"] for v in table.values()), 6))


if __name__ == "__main__":
    main()
