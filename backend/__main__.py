"""CLI entry point: `python -m backend [serve|refresh]`."""
from __future__ import annotations

import argparse
import json
import logging
import time

from . import config, db, ingest


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
