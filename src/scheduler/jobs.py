"""Scheduled job definitions."""

from __future__ import annotations

from datetime import timedelta

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
    """Send fresh price/volume/stop-loss alerts, each once per symbol per day."""
    if not is_trading_day():
        return

    queries = QueryService(db)
    alerts = _market_alerts(config, queries) + _stop_loss_alerts(config, queries)

    today = shanghai_today()
    fresh_alerts = [
        alert
        for alert in alerts
        if queries.save_alert_if_new(
            alert["symbol"], alert["alert_type"], today, alert["message"]
        )
    ]
    if not fresh_alerts:
        logger.info("No alerts triggered." if not alerts else "All triggered alerts already sent today.")
        return

    logger.warning(f"Found {len(fresh_alerts)} new alerts!")
    problem = config.email.credential_problem()
    if problem:
        logger.warning(f"Email delivery unavailable ({problem}); alerts not sent.")
        return
    alert_data = {
        "date": today.isoformat(),
        "type": "alert",
        "alerts": fresh_alerts,
    }
    EmailSender(config.email).send_alert(alert_data)


def _market_alerts(config: AppConfig, queries: QueryService) -> list[dict]:
    """Intraday price-change and volume-spike alerts for watched A-shares."""
    symbols = config.watchlist.a_shares
    if not symbols:
        return []

    logger.info("Checking alerts...")
    client = AkshareDataClient(
        use_env_proxy=config.akshare.use_env_proxy,
        max_retries=config.akshare.max_retries,
        retry_delay_seconds=config.akshare.retry_delay_seconds,
    )
    try:
        spot = client.fetch_latest(symbols)
    except Exception as e:
        logger.error(f"Failed to fetch real-time quotes: {e}")
        return []
    if spot.empty:
        logger.warning("No real-time quotes available, skipping alert check.")
        return []

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
        end = shanghai_today()
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
    return alerts


def _stop_loss_alerts(config: AppConfig, queries: QueryService) -> list[dict]:
    """Flag holdings whose unrealized loss breaches the configured stop-loss line."""
    threshold = config.alerts.stop_loss_threshold
    alerts = []
    for holding in queries.get_portfolio_valuation()["holdings"]:
        pnl_pct = holding.get("unrealized_pnl_pct")
        if pnl_pct is None or pnl_pct > threshold:
            continue
        alerts.append({
            "symbol": holding["symbol"],
            "alert_type": "止损警告",
            "message": (
                f"{holding['name']} 浮动盈亏 {pnl_pct:.2f}%，"
                f"已跌破止损线 {threshold}%"
            ),
            "current_value": f"{holding['latest_price']:.4f} {holding['currency']}",
        })
    return alerts
