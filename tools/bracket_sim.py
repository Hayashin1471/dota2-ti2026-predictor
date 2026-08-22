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
# Three teams left.  The upper bracket final is decided, so the whole tree is
# now two series: the lower bracket final, then the grand final against the
# team already sitting in it.
STATE = {
    # lower-bracket final and the score so far
    "lower_bracket_final": ("team-yandex", "team-spirit", 0, 0),
    # already through to the grand final, waiting for an opponent
    "grand_final_seed": "team-vision",
}

LABEL = {"team-vision": "TEAM VISION", "team-yandex": "Team Yandex",
         "team-spirit": "Team Spirit"}

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
    la, lb, lwa, lwb = STATE["lower_bracket_final"]
    seed = STATE["grand_final_seed"]

    out = {s: {"champion": 0.0, "final": 0.0, "top3": 0.0} for s in LABEL}

    def land(p: float, first: str, second: str, third: str) -> None:
        out[first]["champion"] += p
        for s in (first, second):
            out[s]["final"] += p
        for s in (first, second, third):
            out[s]["top3"] += p

    for lbf_win, p1 in ((la, p_series(la, lb, 3, lwa, lwb)),
                        (lb, p_series(lb, la, 3, lwb, lwa))):
        lbf_lose = lb if lbf_win == la else la
        for champ, p2 in ((seed, p_series(seed, lbf_win, 5)),
                          (lbf_win, p_series(lbf_win, seed, 5))):
            runner = lbf_win if champ == seed else seed
            land(p1 * p2, champ, runner, third=lbf_lose)
    return out


def main() -> None:
    la, lb, lwa, lwb = STATE["lower_bracket_final"]
    seed = STATE["grand_final_seed"]

    print("=== the series on the board ===")
    s = series(la, lb, 3, lwa, lwb)
    top = s["scorelines"][0]
    print(f"{'Lower bracket final':22s} {LABEL[la]} vs {LABEL[lb]} at {lwa}-{lwb}: "
          f"map {p_map(la, lb):.3f}, series {s['p_series']['a']:.3f}, "
          f"most likely {top['a']}-{top['b']} ({top['p']:.0%})")

    print("\n=== every pairing still reachable ===")
    for a, b, bo in ((la, lb, 3), (seed, la, 5), (seed, lb, 5)):
        srs = series(a, b, bo)
        line = ", ".join(f"{sl['a']}-{sl['b']} {sl['p']:.0%}" for sl in srs["scorelines"][:3])
        print(f"Bo{bo}  {LABEL[a]:14s} vs {LABEL[b]:14s} "
              f"map {p_map(a, b):.3f}  series {p_series(a, b, bo):.3f}  [{line}]")

    print("\n=== where they finish ===")
    table = placings()
    for slug, v in sorted(table.items(), key=lambda kv: -kv[1]["champion"]):
        print(f"{LABEL[slug]:14s} champion {v['champion']:6.1%}  "
              f"grand final {v['final']:6.1%}  top 3 {v['top3']:6.1%}")
    print("\ncheck: champion probabilities sum to",
          round(sum(v["champion"] for v in table.values()), 6))


if __name__ == "__main__":
    main()
