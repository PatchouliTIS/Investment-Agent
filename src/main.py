"""Investment Agent CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Investment Agent - Personal investment decision support"
    )
    parser.add_argument(
        "command",
        choices=["init-db", "sync", "report", "test-email", "run"],
        help="Command to execute",
    )
    parser.add_argument("--config", default="config/config.yaml", help="Config file path")
    parser.add_argument("--type", choices=["daily", "weekly"], default="daily", help="Report type")
    args = parser.parse_args()

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
    elif args.command == "test-email":
        _cmd_test_email(config)
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
    from src.analysis.llm_client import LLMClient
    from src.analysis.report_generator import ReportGenerator
    from src.notify.email_sender import EmailSender
    from src.storage.database import Database

    db = Database(config.database)
    llm_config = config.llm_deep if report_type == "weekly" and config.llm_deep else config.llm
    llm = LLMClient(llm_config)
    generator = ReportGenerator(llm, db, config)

    if report_type == "daily":
        report = generator.generate_daily_brief()
    else:
        report = generator.generate_weekly_deep()

    # Send via email if configured
    if config.email.sender and config.email.recipients:
        sender = EmailSender(config.email)
        template = "daily_brief.html" if report_type == "daily" else "weekly_deep.html"
        sender.send_report(report, template)
        print(f"Report sent to: {', '.join(config.email.recipients)}")
    else:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def _cmd_test_email(config):
    from src.notify.email_sender import EmailSender

    sender = EmailSender(config.email)
    sender.send_test()
    print(f"Test email sent to: {', '.join(config.email.recipients)}")


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
