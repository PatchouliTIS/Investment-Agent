"""Scheduled job definitions."""

from __future__ import annotations

from datetime import date

from loguru import logger

from src.config import AlertConfig, AppConfig
from src.data.sync import DataSyncService
from src.analysis.llm_client import LLMClient
from src.analysis.report_generator import ReportGenerator
from src.notify.email_sender import EmailSender
from src.storage.database import Database
from src.storage.queries import QueryService
from src.utils.chinese_calendar import is_trading_day


def job_daily_data_sync(config: AppConfig, db: Database):
    """Fetch all new data after market close."""
    if not is_trading_day():
        logger.info("Not a trading day, skipping data sync.")
        return
    logger.info("Running daily data sync job...")
    sync = DataSyncService(config, db)
    sync.sync_all()


def job_daily_report(config: AppConfig, db: Database):
    """Generate and send daily brief."""
    if not is_trading_day():
        logger.info("Not a trading day, skipping daily report.")
        return
    logger.info("Running daily report job...")
    llm = LLMClient(config.llm)
    generator = ReportGenerator(llm, db, config)
    report = generator.generate_daily_brief()

    if config.email.sender and config.email.recipients:
        sender = EmailSender(config.email)
        sender.send_report(report, "daily_brief.html")


def job_weekly_report(config: AppConfig, db: Database):
    """Generate and send weekly deep analysis."""
    logger.info("Running weekly report job...")
    llm_config = config.llm_deep if config.llm_deep else config.llm
    llm = LLMClient(llm_config)
    generator = ReportGenerator(llm, db, config)
    report = generator.generate_weekly_deep()

    if config.email.sender and config.email.recipients:
        sender = EmailSender(config.email)
        sender.send_report(report, "weekly_deep.html")


def job_check_alerts(config: AppConfig, db: Database):
    """Check for price/volume anomalies and send alerts."""
    if not is_trading_day():
        return

    logger.info("Checking alerts...")
    queries = QueryService(db)
    alerts = []

    for symbol in config.watchlist.a_shares:
        from datetime import timedelta

        end = date.today()
        start = end - timedelta(days=30)
        df = queries.get_quotes("a_share", symbol, start, end)
        if df.empty or len(df) < 2:
            continue

        latest = df.iloc[-1]

        # Price change alert
        if abs(latest["change_pct"] or 0) >= config.alerts.price_change_threshold:
            direction = "大涨" if latest["change_pct"] > 0 else "大跌"
            alerts.append({
                "symbol": symbol,
                "alert_type": f"价格异动 - {direction}",
                "message": f"涨跌幅 {latest['change_pct']:.2f}%，超过阈值 {config.alerts.price_change_threshold}%",
                "current_value": f"¥{latest['close']:.2f}",
            })

        # Volume spike alert
        if len(df) >= 20:
            avg_volume = df["volume"].iloc[-21:-1].mean()
            if avg_volume > 0:
                volume_ratio = latest["volume"] / avg_volume
                if volume_ratio >= config.alerts.volume_spike_threshold:
                    alerts.append({
                        "symbol": symbol,
                        "alert_type": "成交量异常放大",
                        "message": f"成交量为20日均量的 {volume_ratio:.1f} 倍，超过阈值 {config.alerts.volume_spike_threshold}x",
                        "current_value": f"成交量 {latest['volume']:,.0f}",
                    })

    if alerts:
        logger.warning(f"Found {len(alerts)} alerts!")
        alert_data = {
            "date": date.today().isoformat(),
            "type": "alert",
            "alerts": alerts,
        }
        if config.email.sender and config.email.recipients:
            sender = EmailSender(config.email)
            sender.send_alert(alert_data)
    else:
        logger.info("No alerts triggered.")
