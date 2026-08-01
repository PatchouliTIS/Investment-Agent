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
| Storage | SQLite + SQLAlchemy | 8 tables, upsert dedup |
| AI | litellm (OpenAI / Claude / Ollama) | 3 analyst agents + portfolio advisor |
| Notify | SMTP + Jinja2 HTML | Daily brief, weekly deep, alerts |
| Schedule | APScheduler 3.x | In-process cron jobs |

## Project Structure

```
src/
├── config.py                 # Pydantic config with ${ENV_VAR} support
├── main.py                   # CLI: init-db / sync / report / set-holding / delete-holding / portfolio / test-email / run
├── data/                     # Data fetchers (a_share, fund, hk_us, news, sync)
├── storage/                  # ORM models, DB management, query service
├── analysis/                 # LLM client, stock/fund analysts, portfolio advisor, report generator
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

# Record or update an actual holding, then inspect its local valuation
python -m src.main set-holding --market a_share --symbol 600519 --name 贵州茅台 --shares 100 --cost-price 1450
python -m src.main set-holding --market fund --symbol 510300 --name 沪深300ETF --shares 1000 --cost-price 3.85
# Permanently remove a holding by its market and symbol
python -m src.main delete-holding --market fund --symbol 510300
python -m src.main portfolio

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
- **investor_profile** — optional income, available cash, fund assets, and risk preference for portfolio advice

Sensitive values use `${ENV_VAR}` interpolation from `.env`.

## Analyst Agents

| Agent | What it does |
|-------|-------------|
| **Fundamental** | Analyzes financial indicators (ROE, margins, growth, debt) via LLM |
| **Technical** | Computes MA/RSI/MACD with pandas, then LLM interprets the signals |
| **Sentiment** | Feeds recent news into LLM for sentiment scoring |
| **Fund** | Calculates NAV returns, drawdown, and annualized volatility before LLM interpretation |
| **Portfolio Advisor** | Synthesizes all individual analyses into allocation advice |

## Holdings and Valuation

Use `set-holding` to maintain actual positions for `a_share`, `fund`, `hk`, or `us`. The command upserts each `market + symbol` position, so a later entry replaces its quantity and average cost. Use `delete-holding --market MARKET --symbol SYMBOL` to permanently remove one position; a missing position is reported without changing any other holdings. `portfolio` values A/HK/US stocks with the most recent locally synchronized close and funds with the most recent NAV.

Valuation is grouped by CNY, HKD, and USD. It intentionally does not aggregate across currencies because the application does not yet sync a foreign-exchange conversion source. Daily and weekly email reports include per-holding cost, latest price, market value, and unrealized P&L when local pricing is available.

## Report Windows

Daily and weekly reports are generated through independent analysis windows. The daily brief uses 20 recent trading days, 7 days of news, and 180 days of fund NAV data. The weekly report uses a separate 60-trading-day fundamental summary, 365-day technical and fund history, 30 days of news, and up to two years of fundamental market context; it does not reuse the daily-report generation path.

## Schedule (default)

| Job | Cron | Description |
|-----|------|-------------|
| Data Sync | `0 18 * * 1-5` | Weekdays 18:00 after market close |
| Daily Brief | `30 19 * * 1-5` | Weekdays 19:30 |
| Weekly Deep | `0 10 * * 6` | Saturday 10:00 |
| Alert Check | `30 18 * * 1-5` | End-of-day price/volume anomalies, deduplicated by symbol/rule/date |

## Data Synchronization

`sync` retrieves incremental data from AKShare and stores it locally. It covers:

- A-share, Hong Kong, and U.S. daily quotes
- Open-fund and ETF NAV history
- A-share financial indicators, individual-stock fund flow, and company news

Each symbol and enrichment task is isolated: a provider failure is logged without aborting the rest of the watchlist. The report and end-of-day alert commands use the persisted data, so run `sync` successfully before generating the first report.

## Development

```bash
# Run tests
python -m pytest tests/ -v  # Python 3.10+ with the dev dependencies installed

# Lint
ruff check src/ tests/
```

### Remote LLM Probe

The regular test suite does not contact an LLM provider. To send one short, billable
`PING_OK` request using the active `config/config.yaml` and `.env` credentials, run:

```bash
RUN_LLM_INTEGRATION=1 python -m pytest -q -m integration tests/test_analysis/test_llm_integration.py
```

This test uses 32 maximum output tokens, a 20-second timeout, and no automatic retry.
It verifies only that the configured endpoint responds through the application's LLM client.

## Disclaimer

This tool is for **personal decision support only**. It does not execute trades automatically. All investment decisions should be made by the user. AI-generated analysis is for reference only and does not constitute investment advice.
