"""Command line entry point.

    python -m app.cli run           # the morning job: brief + LinkedIn posts
    python -m app.cli discover      # dump what the Explorer actually serves
    python -m app.cli latest        # reprint the most recent output
    python -m app.cli schedule ...  # install/remove the daily local job
"""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from . import schedule as scheduler
from .config import settings
from .digest import render_markdown, render_terminal
from .extract import dedupe, filter_rounds
from .fetcher import dump_capture, fetch_explorer
from .linkedin import build_posts
from .models import Round
from .rss import enrich, fetch_feed
from .store import Store

logger = logging.getLogger("fundingagent")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def gather(use_browser: bool = True, verbose: bool = False) -> tuple[list[Round], str, list]:
    """Collects rounds from the Explorer, falling back to the tech.eu feed.

    Returns (rounds, source_label, captures).
    """
    rounds, captures = fetch_explorer(use_browser=use_browser)
    source = "explorer"

    feed_rounds = fetch_feed(settings.rss_url)
    if rounds:
        # The feed carries the prose the Explorer's table doesn't.
        rounds = enrich(rounds, feed_rounds)
    elif feed_rounds:
        logger.warning("Explorer returned nothing parseable; using the tech.eu RSS feed")
        rounds, source = feed_rounds, "rss"

    return dedupe(rounds), source, captures


def cmd_run(args: argparse.Namespace) -> int:
    store = Store(settings.resolved_db_path)
    rounds, source, captures = gather(use_browser=not args.no_browser, verbose=args.verbose)

    if not rounds:
        print(
            "Could not read any funding rounds.\n\n"
            "Run `python -m app.cli discover` — it saves the pages and JSON the site\n"
            "actually served so the field mapping can be adjusted.",
            file=sys.stderr,
        )
        store.log_run(0, 0, 0, source, "no rounds parsed")
        return 1

    found = len(rounds)
    rounds = filter_rounds(
        rounds,
        lookback_days=args.lookback if args.lookback is not None else settings.lookback_days,
        min_amount_eur=args.min_amount if args.min_amount is not None else settings.min_amount_eur,
    )

    only_new = settings.only_new and not args.all
    fresh = store.new_rounds(rounds) if only_new else rounds

    limit = (args.per_post or settings.companies_per_post) * (args.max_posts or settings.max_posts)
    selected = fresh[:limit]

    posts = build_posts(
        selected,
        per_post=args.per_post or settings.companies_per_post,
        max_posts=args.max_posts or settings.max_posts,
        include_partial=settings.include_partial_post,
        max_chars=settings.max_post_chars,
    )

    print(render_terminal(selected))
    for i, post in enumerate(posts, start=1):
        print("─" * 72)
        print(f"LinkedIn post {i}/{len(posts)}  ({len(post)} chars — paste as-is)\n")
        print(post)
        print()

    out_dir = _write_outputs(selected, posts)
    if out_dir:
        print("─" * 72)
        print(f"Saved to {out_dir}")

    store.record(rounds)
    if selected and not args.dry_run:
        store.mark_posted(selected)
    store.log_run(found, len(selected), len(posts), source)
    return 0


def _write_outputs(rounds: list[Round], posts: list[str]) -> Path | None:
    if not rounds:
        return None
    out_dir = settings.resolved_output_dir / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "digest.md").write_text(render_markdown(rounds, posts), encoding="utf-8")
    for i, post in enumerate(posts, start=1):
        (out_dir / f"linkedin-{i}.txt").write_text(post, encoding="utf-8")
    latest = settings.resolved_output_dir / "latest"
    latest.write_text(str(out_dir), encoding="utf-8")
    return out_dir


def cmd_discover(args: argparse.Namespace) -> int:
    """Saves the raw pages/JSON so an unrecognised payload can be mapped by hand."""
    rounds, captures = fetch_explorer(use_browser=not args.no_browser)
    out_dir = settings.resolved_output_dir / "discover"

    print(f"Parsed {len(rounds)} rounds from the Explorer.\n")
    for capture in captures:
        print("\n".join(capture.summary()))
        written = dump_capture(capture, out_dir)
        for path in written:
            print(f"  saved {path}")
        print()

    if rounds:
        print("Sample of what was parsed:\n")
        for r in rounds[:3]:
            print(f"  {r.company} | {r.amount_display} | lead={r.lead_investor} | {r.description[:70]}")
    else:
        print(
            "Nothing matched the round heuristics. Inspect the saved JSON above and\n"
            "add its field names to the *_KEYS tuples in app/extract.py."
        )
    return 0


def cmd_latest(args: argparse.Namespace) -> int:
    pointer = settings.resolved_output_dir / "latest"
    if not pointer.exists():
        print("No previous run found. Run: python -m app.cli run", file=sys.stderr)
        return 1
    out_dir = Path(pointer.read_text(encoding="utf-8").strip())
    digest = out_dir / "digest.md"
    if not digest.exists():
        print(f"Missing {digest}", file=sys.stderr)
        return 1
    print(digest.read_text(encoding="utf-8"))
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    if args.action == "install":
        print(scheduler.install(args.at))
    elif args.action == "uninstall":
        print(scheduler.uninstall())
    else:
        print(scheduler.status())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="funding-agent",
        description="Daily Tech.eu funding brief + ready-to-publish LinkedIn posts.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log what the scraper is doing")

    # Repeating the flag on each subcommand lets `run -v` work as well as
    # `-v run`; SUPPRESS stops the subparser default from clearing the
    # top-level value when the flag was given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
        help="log what the scraper is doing",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", parents=[common], help="fetch, brief, and write LinkedIn posts")
    run.add_argument("--per-post", type=int, help=f"companies per post (default {settings.companies_per_post})")
    run.add_argument("--max-posts", type=int, help=f"maximum posts (default {settings.max_posts})")
    run.add_argument("--lookback", type=int, help=f"only rounds from the last N days (default {settings.lookback_days})")
    run.add_argument("--min-amount", type=float, help="skip rounds below this EUR amount")
    run.add_argument("--all", action="store_true", help="include rounds already covered on earlier runs")
    run.add_argument("--dry-run", action="store_true", help="don't mark rounds as posted")
    run.add_argument("--no-browser", action="store_true", help="skip Playwright, use plain HTTP only")
    run.set_defaults(func=cmd_run)

    discover = sub.add_parser("discover", parents=[common], help="dump the endpoints/JSON the Explorer serves")
    discover.add_argument("--no-browser", action="store_true", help="skip Playwright, use plain HTTP only")
    discover.set_defaults(func=cmd_discover)

    latest = sub.add_parser("latest", parents=[common], help="reprint the most recent brief")
    latest.set_defaults(func=cmd_latest)

    sched = sub.add_parser("schedule", parents=[common], help="install/remove the daily local job")
    sched.add_argument("action", choices=["install", "uninstall", "status"])
    sched.add_argument("--at", default="08:00", help="local time of day, HH:MM (default 08:00)")
    sched.set_defaults(func=cmd_schedule)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
