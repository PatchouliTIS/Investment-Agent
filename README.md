# Investment Agent

AI-powered personal investment decision support agent that periodically scrapes financial data across A-shares, funds, and HK/US stocks, then generates analytical reports via multi-model LLM and delivers them by email.

## Architecture

```
[Scheduler/APScheduler] → [Data Collection/AKShare] → [SQLite Storage]
                                                            ↓
[Email Notification] ← [Report Generation] ← [AI Analysis/litellm]
```

| Layer | Tech | Purpose |
|-------|------|---------|
| Data | AKShare | A-shares, funds/ETFs, HK/US stocks, news |
| Storage | SQLite + SQLAlchemy | 7 tables, upsert dedup |
| AI | litellm (OpenAI / Claude / Ollama) | 4 analyst agents + portfolio advisor |
| Notify | SMTP + Jinja2 HTML | Daily brief, weekly deep, alerts |
| Schedule | APScheduler 3.x | In-process cron jobs |

## Project Structure

```
src/
├── config.py                 # Pydantic config with ${ENV_VAR} support
├── main.py                   # CLI: init-db / sync / report / test-email / run
├── data/                     # Data fetchers (a_share, fund, hk_us, news, sync)
├── storage/                  # ORM models, DB management, query service
├── analysis/                 # LLM client, 4 analyst agents, report generator
├── notify/                   # Email sender + 3 HTML templates
├── scheduler/                # Job definitions + APScheduler runner
└── utils/                    # Logging, rate limiter, trading day calendar
```

## Quick Start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure
cp config/config.example.yaml config/config.yaml
cp .env.example .env
# Edit both files — fill in LLM API keys and email SMTP credentials

# 3. Initialize database
python -m src.main init-db

# 4. Sync market data
python -m src.main sync

# 5. Generate a report (requires valid LLM API key)
python -m src.main report --type daily

# 6. Test email delivery
python -m src.main test-email

# 7. Start the scheduled daemon
python -m src.main run
```

## Configuration

Edit `config/config.yaml` (copied from `config.example.yaml`):

- **watchlist** — stock/fund codes to track
- **llm** — primary LLM provider for daily analysis (e.g. `gpt-4o-mini`)
- **llm_deep** — optional stronger model for weekly deep reports (e.g. `claude-sonnet-4-20250514`)
- **email** — SMTP settings (QQ Mail, Gmail, etc.)
- **schedule** — cron expressions for data sync, daily/weekly reports
- **alerts** — price change % and volume spike thresholds

Sensitive values use `${ENV_VAR}` interpolation from `.env`.

## Analyst Agents

| Agent | What it does |
|-------|-------------|
| **Fundamental** | Analyzes financial indicators (ROE, margins, growth, debt) via LLM |
| **Technical** | Computes MA/RSI/MACD with pandas, then LLM interprets the signals |
| **Sentiment** | Feeds recent news into LLM for sentiment scoring |
| **Portfolio Advisor** | Synthesizes all individual analyses into allocation advice |

## Schedule (default)

| Job | Cron | Description |
|-----|------|-------------|
| Data Sync | `0 18 * * 1-5` | Weekdays 18:00 after market close |
| Daily Brief | `30 19 * * 1-5` | Weekdays 19:30 |
| Weekly Deep | `0 10 * * 6` | Saturday 10:00 |
| Alert Check | Every 30 min, 9:00–15:00 weekdays | Price/volume anomaly detection |

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Lint
ruff check src/ tests/
```

## Disclaimer

This tool is for **personal decision support only**. It does not execute trades automatically. All investment decisions should be made by the user. AI-generated analysis is for reference only and does not constitute investment advice.
