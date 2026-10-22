"""Scheduled job definitions."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from loguru import logger

from src.config import AppConfig
from src.data.akshare_client import AkshareDataClient
from src.data.sync import DataSyncService
from src.analysis.llm_cache import LLMCache
from src.analysis.llm_client import LLMClient
from src.analysis.report_generator import ReportGenerator
from src.notify.email_sender import EmailSender
from src.notify.local_report import save_report
from src.storage.database import Database
from src.storage.queries import QueryService
from src.utils.chinese_calendar import is_trading_day, shanghai_today


def job_daily_data_sync(config: AppConfig, db: Database):
    """Fetch all new data after market close."""
    if not is_trading_day():
        logger.info("Not a trading day, skipping data sync.")
        return
    logger.info("Running daily data sync job...")
    sync = DataSyncService(config, db)
    sync.sync_all()


def _build_generator(config: AppConfig, db: Database, llm_config) -> ReportGenerator:
    """Wire a cache-backed generator so retries replay instead of re-billing."""
    cache = LLMCache(db, config.llm_cache)
    cache.purge_expired()
    return ReportGenerator(LLMClient(llm_config, cache=cache), db, config)


def _deliver_report(config: AppConfig, report: dict, template: str) -> None:
    """Email a report, falling back to disk so a failed send wastes no tokens."""
    sender = EmailSender(config.email)
    subject, html = sender.render_report(report, template)

    problem = config.email.credential_problem()
    if problem:
        path = save_report(report, html)
        logger.warning(f"Email skipped ({problem}); report saved locally path={path}")
        return

    try:
        sender.send_rendered(subject, html)
    except Exception as error:  # noqa: BLE001
        path = save_report(report, html)
        logger.error(f"Email delivery failed, report kept locally path={path}: {error}")


def job_daily_report(config: AppConfig, db: Database):
    """Generate and send daily brief."""
    if not is_trading_day():
        logger.info("Not a trading day, skipping daily report.")
        return
    logger.info("Running daily report job...")
    generator = _build_generator(config, db, config.llm)
    report = generator.generate_daily_brief()
    _deliver_report(config, report, "daily_brief.html")


def job_weekly_report(config: AppConfig, db: Database):
    """Generate and send weekly deep analysis."""
    logger.info("Running weekly report job...")
    llm_config = config.llm_deep if config.llm_deep else config.llm
    generator = _build_generator(config, db, llm_config)
    report = generator.generate_weekly_deep()
    _deliver_report(config, report, "weekly_deep.html")


def job_check_alerts(config: AppConfig, db: Database):
    """Check for price/volume anomalies using real-time quotes and send alerts."""
    if not is_trading_day():
        return

    symbols = config.watchlist.a_shares
    if not symbols:
        return

    logger.info("Checking alerts...")
    try:
        spot = AkshareDataClient().fetch_latest(symbols)
    except Exception as e:
        logger.error(f"Failed to fetch real-time quotes: {e}")
        return
    if spot.empty:
        logger.warning("No real-time quotes available, skipping alert check.")
        return

    queries = QueryService(db)
    alerts = []

    for symbol in symbols:
        rows = spot[spot["symbol"] == symbol]
        if rows.empty:
            continue
        latest = rows.iloc[0]
        change_pct = latest.get("change_pct")
        price = latest.get("close")

        # Price change alert (intraday, real-time)
        if pd.notna(change_pct) and abs(change_pct) >= config.alerts.price_change_threshold:
            direction = "大涨" if change_pct > 0 else "大跌"
            alerts.append({
                "symbol": symbol,
                "alert_type": f"价格异动 - {direction}",
                "message": f"实时涨跌幅 {change_pct:.2f}%，超过阈值 {config.alerts.price_change_threshold}%",
                "current_value": f"¥{price:.2f}" if pd.notna(price) else "-",
            })

        # Volume spike alert: real-time volume vs 20-day average from daily bars
        end = date.today()
        start = end - timedelta(days=45)
        df = queries.get_quotes("a_share", symbol, start, end)
        if len(df) >= 20:
            avg_volume = df["volume"].iloc[-20:].mean()
            volume = latest.get("volume")
            if pd.notna(volume) and avg_volume > 0:
                volume_ratio = volume / avg_volume
                if volume_ratio >= config.alerts.volume_spike_threshold:
                    alerts.append({
                        "symbol": symbol,
                        "alert_type": "成交量异常放大",
                        "message": f"实时成交量为20日均量的 {volume_ratio:.1f} 倍，超过阈值 {config.alerts.volume_spike_threshold}x",
                        "current_value": f"成交量 {volume:,.0f}",
                    })

    if alerts:
        logger.warning(f"Found {len(alerts)} alerts!")
        alert_data = {
            "date": shanghai_today().isoformat(),
            "type": "alert",
            "alerts": alerts,
        }
        if config.email.sender and config.email.recipients:
            sender = EmailSender(config.email)
            sender.send_alert(alert_data)
    else:
        logger.info("No alerts triggered.")
