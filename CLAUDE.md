# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable with dev deps)
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_storage/test_queries.py -v

# Skip integration tests (external API calls)
python -m pytest tests/ -m "not integration"

# Lint
ruff check src/ tests/

# Lint with auto-fix
ruff check --fix src/ tests/

# CLI commands
python -m src.main init-db          # Create SQLite tables
python -m src.main sync             # Fetch market data from AKShare
python -m src.main sync --backfill-days 730   # Deepen local history (weekly window needs it)
python -m src.main report --type daily   # Generate and email daily report
python -m src.main report --type weekly  # Generate and email weekly report
python -m src.main test-email       # Send test email
python -m src.main run              # Start APScheduler daemon
```

## Architecture

Pipeline flow: `Scheduler → Data Collection (AKShare) → SQLite → AI Analysis (Messages API) → Report Generation (Jinja2) → Email`

Key design decisions:
- **LLM via litellm**: `src/analysis/llm_client.py` calls the configured provider through litellm. With `provider: anthropic`, litellm posts to `{base_url}/v1/messages`, so `base_url` is the bare host (e.g. `https://wawapii.com`). `chat_json()` parses structured JSON responses with markdown-fence handling. Two LLM configs exist: `llm` for daily and optional `llm_deep` for weekly. Responses are content-address cached in the `llm_cache` table so re-runs over unchanged data cost no tokens.
- **Parallel analyst calls**: `src/analysis/report_generator.py` runs per-symbol analyst tasks concurrently (ThreadPoolExecutor, 5 workers); the portfolio advisor still runs last, sequentially.
- **SQLite WAL**: `src/storage/database.py` enables `journal_mode=WAL` and a 30s busy timeout so overlapping scheduled jobs don't hit "database is locked".
- **Alert dedup**: `src/scheduler/jobs.py` persists each alert via `save_alert_if_new` (unique on symbol/type/date) before emailing, covering price moves, volume spikes, and holding stop-loss breaches (`alerts.stop_loss_threshold`).
- **Config uses `${ENV_VAR}` interpolation**: `src/config.py` resolves env vars from `.env` into the YAML config at load time via regex substitution. All config is validated with Pydantic.
- **Upsert dedup in storage**: All data tables have unique constraints; fetchers use SQLAlchemy upsert patterns to avoid duplicates on re-sync.
- **3 analyst agents + 1 portfolio advisor**: Each analyst (`fundamental`, `technical`, `sentiment`) produces independent JSON analysis. The `portfolio` advisor synthesizes them. All use structured JSON output from LLM via `chat_json()`.
- **Trading day awareness**: `src/utils/chinese_calendar.py` uses the `chinese-calendar` library to skip non-trading days for A-share scheduling.
- **Quote data sources**: A-share quotes try EastMoney, Sina, Tencent, then Tonghuashun (public JSONP, last resort). ETF history tries EastMoney, then Tencent forward-adjusted, with Sina unadjusted only as last resort; spot snapshots use Sina. Tencent may omit volume, which remains null rather than being fabricated. Do not assume adjustment or volume units are comparable across providers.

## Testing

- Tests use in-memory SQLite (`:memory:`) via the `test_db` fixture in `conftest.py`
- LLM calls are mocked via the `mock_llm` fixture which patches `src.analysis.llm_client.completion`
- Mark tests hitting real APIs with `@pytest.mark.integration`

## Style

- Python 3.10+, ruff with 100-char line length
- All LLM prompts are in Chinese (target audience is Chinese investors)
- Module imports use `from src.xxx import ...` (package installed in editable mode)
