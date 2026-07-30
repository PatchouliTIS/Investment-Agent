"""APScheduler setup and lifecycle management."""

from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from src.config import AppConfig
from src.scheduler.jobs import (
    job_check_alerts,
    job_daily_data_sync,
    job_daily_report,
    job_weekly_report,
)
from src.storage.database import Database


class SchedulerRunner:
    """Manages the APScheduler lifecycle."""

    def __init__(self, config: AppConfig, db: Database):
        self.config = config
        self.db = db
        self.scheduler = BlockingScheduler()

        self._register_jobs()

    def _register_jobs(self):
        """Register all scheduled jobs."""
        # Daily data sync (e.g., "0 18 * * 1-5")
        self.scheduler.add_job(
            job_daily_data_sync,
            CronTrigger.from_crontab(self.config.schedule.data_sync_cron),
            args=[self.config, self.db],
            id="daily_data_sync",
            name="Daily Data Sync",
            misfire_grace_time=3600,
        )

        # Daily report (e.g., "30 19 * * 1-5")
        self.scheduler.add_job(
            job_daily_report,
            CronTrigger.from_crontab(self.config.schedule.daily_report_cron),
            args=[self.config, self.db],
            id="daily_report",
            name="Daily Report",
            misfire_grace_time=3600,
        )

        # Weekly deep report (e.g., "0 10 * * 6")
        self.scheduler.add_job(
            job_weekly_report,
            CronTrigger.from_crontab(self.config.schedule.weekly_report_cron),
            args=[self.config, self.db],
            id="weekly_report",
            name="Weekly Deep Report",
            misfire_grace_time=7200,
        )

        # Alert checking after the end-of-day data synchronization.
        self.scheduler.add_job(
            job_check_alerts,
            CronTrigger.from_crontab(self.config.schedule.alert_check_cron),
            args=[self.config, self.db],
            id="check_alerts",
            name="End-of-Day Alert Check",
            misfire_grace_time=1800,
        )

        logger.info("Scheduled jobs registered:")
        for job in self.scheduler.get_jobs():
            logger.info(f"  - {job.name}: {job.trigger}")

    def start(self):
        """Start the blocking scheduler."""
        logger.info("Starting scheduler...")
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")
