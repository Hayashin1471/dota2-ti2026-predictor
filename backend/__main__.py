"""CLI entry point: `python -m backend [serve|refresh]`."""
from __future__ import annotations

import argparse
import json
import logging
import time

from . import config, db, ingest


def _roster_cmd(args) -> dict:
    """List, set or clear the manual lineup corrections."""
    if not args.team:
        return {"overrides": [dict(r) for r in db.query(
            "SELECT slug, account_id, is_current, note FROM roster_overrides "
            "ORDER BY slug, is_current DESC")]}

    if db.one("SELECT 1 FROM ti_teams WHERE slug = ?", (args.team,)) is None:
        slugs = [r["slug"] for r in db.query("SELECT slug FROM ti_teams ORDER BY slug")]
        return {"error": f"unknown team '{args.team}'", "known_slugs": slugs}

    if args.clear:
        db.execute("DELETE FROM roster_overrides WHERE slug = ?", (args.team,))
        # The flags already written to `players` stay until something rewrites
        # them, which is what a roster refresh does.
        return {"team": args.team, "cleared": True,
                "note": "run `python -m backend refresh players` to pull OpenDota's "
                        "own view back in"}

    applied, missing = [], []
    for names, current in ((args.current, True), (args.former, False)):
        for name in names:
            p = ingest.resolve_player(args.team, name)
            if p is None:
                missing.append(name)
                continue
            ingest.set_roster_override(args.team, p["account_id"], current,
                                       note=f"manual: {'in' if current else 'out'}")
            applied.append({"name": p["name"], "account_id": p["account_id"],
                            "is_current": current})

    out = {"team": args.team, "applied": applied}
    if missing:
        out["not_found"] = missing
        out["known_players"] = [r["name"] for r in db.query(
            "SELECT name FROM players WHERE slug = ? ORDER BY team_games DESC", (args.team,))]
    out["lineup_now"] = [
        r["name"] for r in db.query(
            "SELECT name FROM players WHERE slug = ? AND is_current = 1 "
            "ORDER BY team_games DESC", (args.team,))]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="backend", description="TI 2026 predictor")
    sub = parser.add_subparsers(dest="cmd")

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    refresh = sub.add_parser("refresh", help="collect data without starting the server")
    refresh.add_argument("phase", nargs="?", default="all",
                         choices=["core", "history", "players", "drafts", "results",
                                  "matchups", "all"])
    refresh.add_argument("--drafts", type=int, default=config.DEFAULT_DRAFT_SAMPLE)
    refresh.add_argument("--days", type=int, default=config.RESULTS_DAYS,
                         help="calendar days of finished results to pull from hawk.live")

    sub.add_parser("status", help="show what is in the local database")
    sub.add_parser("compact", help="drop stale HTTP cache rows and shrink the database file")

    ros = sub.add_parser("roster", help="hand-correct a team's active lineup")
    ros.add_argument("--team", help="ti_teams slug, e.g. lgd-gaming")
    ros.add_argument("--current", nargs="*", default=[], metavar="NAME",
                     help="players to force into the active lineup")
    ros.add_argument("--former", nargs="*", default=[], metavar="NAME",
                     help="players to force out of the active lineup")
    ros.add_argument("--clear", action="store_true",
                     help="drop this team's corrections and go back to OpenDota")

    ev = sub.add_parser("evaluate", help="backtest the model and fit its term weights")
    ev.add_argument("--apply", action="store_true",
                    help="save the fitted weights so predictions start using them")
    ev.add_argument("--test-fraction", type=float, default=0.25)
    ev.add_argument("--since", default=None,
                    help="score matches from this date onwards as a named holdout "
                         "(YYYY-MM-DD, default: today)")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db.init()

    if args.cmd == "refresh":
        if args.phase == "core":
            out = ingest.refresh_core()
        elif args.phase == "history":
            out = ingest.refresh_history()
        elif args.phase == "players":
            out = ingest.refresh_players()
        elif args.phase == "drafts":
            out = ingest.refresh_drafts(args.drafts)
        elif args.phase == "results":
            out = ingest.refresh_results(args.days)
        elif args.phase == "matchups":
            out = ingest.refresh_all_matchups()
        else:
            out = ingest.refresh_all(args.drafts)
        print(json.dumps(out, indent=2, default=str))
        return

    if args.cmd == "status":
        print(json.dumps(ingest.status(), indent=2, default=str))
        return

    if args.cmd == "compact":
        from . import fetcher
        print(json.dumps(fetcher.compact(), indent=2))
        return

    if args.cmd == "roster":
        print(json.dumps(_roster_cmd(args), indent=2, ensure_ascii=False))
        return

    if args.cmd == "evaluate":
        import datetime
        from . import evaluate
        day = (datetime.date.fromisoformat(args.since) if args.since
               else datetime.date.today())
        out = evaluate.run(test_fraction=args.test_fraction, apply=args.apply,
                           today_only_start=time.mktime(day.timetuple()),
                           holdout_label=day.isoformat())
        print(json.dumps(out, indent=2, default=str))
        return

    import uvicorn
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8000)
    print(f"\n  TI 2026 Predictor -> http://{host}:{port}\n")
    uvicorn.run("backend.app:app", host=host, port=port,
                reload=getattr(args, "reload", False))


if __name__ == "__main__":
    main()
