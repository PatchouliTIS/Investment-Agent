"""Investment Agent CLI entry point."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Investment Agent - Personal investment decision support"
    )
    parser.add_argument(
        "command",
        choices=[
            "init-db",
            "sync",
            "report",
            "set-holding",
            "delete-holding",
            "portfolio",
            "test-email",
            "cache-stats",
            "clear-cache",
            "run",
        ],
        help="Command to execute",
    )
    parser.add_argument("--config", default="config/config.yaml", help="Config file path")
    parser.add_argument("--type", choices=["daily", "weekly"], default="daily", help="Report type")
    parser.add_argument("--market", choices=["a_share", "fund", "hk", "us"], help="Holding market")
    parser.add_argument("--symbol", help="Holding symbol")
    parser.add_argument("--name", help="Holding display name")
    parser.add_argument("--shares", type=float, help="Holding quantity")
    parser.add_argument("--cost-price", type=float, help="Average cost per unit")
    args = parser.parse_args()

    if args.command == "set-holding":
        missing = [
            option
            for option, value in {
                "--market": args.market,
                "--symbol": args.symbol,
                "--shares": args.shares,
                "--cost-price": args.cost_price,
            }.items()
            if value is None
        ]
        if missing:
            parser.error(f"set-holding requires {' '.join(missing)}")
    elif args.command == "delete-holding":
        missing = [
            option
            for option, value in {"--market": args.market, "--symbol": args.symbol}.items()
            if value is None
        ]
        if missing:
            parser.error(f"delete-holding requires {' '.join(missing)}")

    from src.config import load_config

    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Setup logging
    from src.utils.logging_config import setup_logging

    setup_logging(config.log_level)

    if args.command == "init-db":
        _cmd_init_db(config)
    elif args.command == "sync":
        _cmd_sync(config)
    elif args.command == "report":
        _cmd_report(config, args.type)
    elif args.command == "set-holding":
        _cmd_set_holding(config, args)
    elif args.command == "delete-holding":
        _cmd_delete_holding(config, args)
    elif args.command == "portfolio":
        _cmd_portfolio(config)
    elif args.command == "test-email":
        _cmd_test_email(config)
    elif args.command == "cache-stats":
        _cmd_cache_stats(config)
    elif args.command == "clear-cache":
        _cmd_clear_cache(config)
    elif args.command == "run":
        _cmd_run(config)


def _cmd_init_db(config):
    from src.storage.database import Database

    db = Database(config.database)
    db.create_tables()
    print(f"Database initialized at: {config.database.path}")


def _cmd_sync(config):
    from src.data.sync import DataSyncService
    from src.storage.database import Database

    db = Database(config.database)
    db.create_tables()
    sync = DataSyncService(config, db)
    sync.sync_all()


def _cmd_report(config, report_type: str):
    from loguru import logger

    from src.analysis.llm_cache import LLMCache
    from src.analysis.llm_client import LLMClient
    from src.analysis.report_generator import ReportGenerator
    from src.notify.email_sender import EmailSender
    from src.notify.local_report import save_report
    from src.storage.database import Database

    db = Database(config.database)
    db.create_tables()
    llm_config = config.llm_deep if report_type == "weekly" and config.llm_deep else config.llm

    # Warn before spending tokens, but still generate: the cache makes a retry free.
    credential_problem = config.email.credential_problem()
    if credential_problem:
        logger.warning(
            f"Email delivery unavailable ({credential_problem}); "
            "report will be saved under data/reports/ instead"
        )

    cache = LLMCache(db, config.llm_cache)
    cache.purge_expired()
    llm = LLMClient(llm_config, cache=cache)
    generator = ReportGenerator(llm, db, config)

    if report_type == "daily":
        report = generator.generate_daily_brief()
    else:
        report = generator.generate_weekly_deep()

    template = "daily_brief.html" if report_type == "daily" else "weekly_deep.html"
    sender = EmailSender(config.email)
    subject, html = sender.render_report(report, template)

    if credential_problem:
        path = save_report(report, html)
        print(f"Email skipped ({credential_problem}). Report saved: {path}")
        print("Fix it by setting EMAIL_SMTP_PASSWORD to your QQ SMTP auth code, then re-run.")
        print("The re-run replays cached LLM responses, so it costs no tokens.")
        return

    try:
        sender.send_rendered(subject, html)
        print(f"Report sent to: {', '.join(config.email.recipients)}")
    except Exception as error:
        path = save_report(report, html)
        logger.error(f"Email delivery failed, report kept locally: {error}")
        print(f"Email failed ({error}). Report saved: {path}")
        print("Re-running replays cached LLM responses, so it costs no tokens.")
        raise SystemExit(1) from error


def _cmd_set_holding(config, args):
    """Create or update a manually entered holding."""
    from src.storage.database import Database
    from src.storage.queries import QueryService

    db = Database(config.database)
    db.create_tables()
    QueryService(db).upsert_portfolio_holding(
        args.market,
        args.symbol,
        args.name or args.symbol,
        args.shares,
        args.cost_price,
    )
    print(f"Holding saved: {args.market}/{args.symbol}")


def _cmd_delete_holding(config, args):
    """Delete one manually maintained holding."""
    from src.storage.database import Database
    from src.storage.queries import QueryService

    db = Database(config.database)
    db.create_tables()
    deleted = QueryService(db).delete_portfolio_holding(args.market, args.symbol)
    if deleted:
        print(f"Holding deleted: {args.market}/{args.symbol}")
    else:
        print(f"Holding not found: {args.market}/{args.symbol}")


def _cmd_portfolio(config):
    """Print current locally valued holdings without contacting an LLM."""
    import json

    from src.storage.database import Database
    from src.storage.queries import QueryService

    db = Database(config.database)
    db.create_tables()
    valuation = QueryService(db).get_portfolio_valuation()
    print(json.dumps(valuation, ensure_ascii=False, indent=2, default=str))


def _cmd_test_email(config):
    from src.notify.email_sender import EmailSender

    sender = EmailSender(config.email)
    sender.send_test()
    print(f"Test email sent to: {', '.join(config.email.recipients)}")


def _cmd_cache_stats(config):
    """Report how much of the LLM cache is available for reuse."""
    import json

    from src.analysis.llm_cache import LLMCache
    from src.storage.database import Database

    db = Database(config.database)
    db.create_tables()
    stats = LLMCache(db, config.llm_cache).stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))


def _cmd_clear_cache(config):
    """Drop every cached LLM response, forcing fresh calls on the next run."""
    from src.analysis.llm_cache import LLMCache
    from src.storage.database import Database

    db = Database(config.database)
    db.create_tables()
    removed = LLMCache(db, config.llm_cache).clear()
    print(f"Cleared {removed} cached LLM response(s).")


def _cmd_run(config):
    from src.scheduler.runner import SchedulerRunner
    from src.storage.database import Database

    db = Database(config.database)
    db.create_tables()
    runner = SchedulerRunner(config, db)
    print("Investment Agent scheduler started. Press Ctrl+C to stop.")
    runner.start()


if __name__ == "__main__":
    main()
