"""Email notification sender with HTML templates."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from loguru import logger

from src.config import EmailConfig
from src.utils.chinese_calendar import shanghai_today

TEMPLATES_DIR = Path(__file__).parent / "templates"


class EmailSender:
    """Sends formatted HTML email reports via SMTP."""

    def __init__(self, config: EmailConfig):
        self.config = config
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=True,
        )

    def send_report(self, report: dict, template_name: str):
        """Render a report with a template and send it via email."""
        template = self.jinja_env.get_template(template_name)
        html_content = template.render(report=report)

        report_type = report.get("type", "report")
        type_labels = {
            "daily_brief": "投资日报",
            "weekly_deep": "投资周报",
            "alert": "投资告警",
        }
        subject = f"{type_labels.get(report_type, '投资报告')} - {report.get('date', shanghai_today())}"

        self._send_html(subject, html_content)

    def send_alert(self, alert_data: dict):
        """Send an alert notification."""
        self.send_report(alert_data, "alert.html")

    def send_test(self):
        """Send a test email to verify SMTP configuration."""
        html = f"""
        <html><body>
        <h2>Investment Agent - 邮件测试</h2>
        <p>如果你收到这封邮件，说明邮件配置正确。</p>
        <p>发送时间: {shanghai_today()}</p>
        </body></html>
        """
        self._send_html("Investment Agent 邮件测试", html)

    def _send_html(self, subject: str, html_content: str):
        """Send an HTML email."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.config.sender
        msg["To"] = ", ".join(self.config.recipients)
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            if self.config.use_ssl:
                with smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port) as server:
                    server.login(self.config.sender, self.config.password)
                    server.sendmail(
                        self.config.sender, self.config.recipients, msg.as_string()
                    )
            else:
                with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port) as server:
                    server.starttls()
                    server.login(self.config.sender, self.config.password)
                    server.sendmail(
                        self.config.sender, self.config.recipients, msg.as_string()
                    )
            logger.info(f"Email sent: {subject} -> {self.config.recipients}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            raise
