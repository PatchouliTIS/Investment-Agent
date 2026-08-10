"""Content-addressed local cache for LLM responses.

Analysis runs are expensive and frequently repeated: a report that fails while
sending email, or a second run on the same trading day, would otherwise re-issue
every prompt. Keying on a hash of the full request means unchanged prompts replay
for free while any data change still triggers a real call.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import delete, select

from src.config import LLMCacheConfig
from src.storage.database import Database
from src.storage.models import LLMCacheEntry
from src.utils.chinese_calendar import shanghai_now


def _now() -> datetime:
    """Shanghai wall-clock time as a naive value.

    ``LLMCacheEntry.created_at`` is a plain ``DateTime``, so SQLite drops any
    tzinfo on write. Storing and comparing naive Shanghai time keeps reads and
    writes on the same footing instead of mixing aware and naive datetimes.
    """
    return shanghai_now().replace(tzinfo=None)


class LLMCache:
    """Stores and replays LLM responses keyed by request content."""

    def __init__(self, db: Database, config: LLMCacheConfig | None = None):
        self.db = db
        self.config = config or LLMCacheConfig()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @staticmethod
    def build_key(model: str, payload: dict) -> str:
        """Hash the model and every request field that can change the response."""
        canonical = json.dumps(
            {"model": model, **payload}, ensure_ascii=False, sort_keys=True, default=str
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, cache_key: str, request_context: str = "unspecified") -> str | None:
        """Return a live cached response, or ``None`` on miss or expiry."""
        if not self.enabled:
            return None

        cutoff = _now() - timedelta(hours=self.config.ttl_hours)
        with self.db.get_session() as session:
            entry = session.scalar(
                select(LLMCacheEntry).where(LLMCacheEntry.cache_key == cache_key)
            )
            if entry is None:
                return None
            if entry.created_at is not None and entry.created_at < cutoff:
                logger.debug(
                    f"LLM cache expired context={request_context} "
                    f"cache_key={cache_key[:12]} age_hours>{self.config.ttl_hours:g}"
                )
                session.delete(entry)
                session.commit()
                return None

            response = entry.response_text
            age_minutes = (_now() - entry.created_at).total_seconds() / 60
            entry.hit_count = (entry.hit_count or 0) + 1
            entry.last_used_at = _now()
            session.commit()

        logger.info(
            f"LLM cache hit context={request_context} cache_key={cache_key[:12]} "
            f"age_minutes={age_minutes:.1f} response_chars={len(response)}"
        )
        return response

    def put(
        self,
        cache_key: str,
        response_text: str,
        request_context: str = "unspecified",
        llm_model: str = "",
        prompt_chars: int = 0,
    ) -> None:
        """Persist a fresh response, replacing any stale row for the same key."""
        if not self.enabled:
            return

        now = _now()
        with self.db.get_session() as session:
            existing = session.scalar(
                select(LLMCacheEntry).where(LLMCacheEntry.cache_key == cache_key)
            )
            if existing is not None:
                existing.response_text = response_text
                existing.request_context = request_context
                existing.llm_model = llm_model
                existing.prompt_chars = prompt_chars
                existing.created_at = now
                existing.last_used_at = now
            else:
                session.add(
                    LLMCacheEntry(
                        cache_key=cache_key,
                        request_context=request_context,
                        llm_model=llm_model,
                        response_text=response_text,
                        prompt_chars=prompt_chars,
                        hit_count=0,
                        created_at=now,
                        last_used_at=now,
                    )
                )
            session.commit()

        logger.debug(
            f"LLM cache stored context={request_context} cache_key={cache_key[:12]} "
            f"response_chars={len(response_text)}"
        )

    def purge_expired(self) -> int:
        """Drop rows past the TTL. Returns how many were removed."""
        cutoff = _now() - timedelta(hours=self.config.ttl_hours)
        with self.db.get_session() as session:
            removed = session.execute(
                delete(LLMCacheEntry).where(LLMCacheEntry.created_at < cutoff)
            ).rowcount
            session.commit()
        if removed:
            logger.info(f"LLM cache purged expired entries count={removed}")
        return removed or 0

    def clear(self) -> int:
        """Drop every cached response. Returns how many were removed."""
        with self.db.get_session() as session:
            removed = session.execute(delete(LLMCacheEntry)).rowcount
            session.commit()
        logger.info(f"LLM cache cleared count={removed}")
        return removed or 0

    def stats(self) -> dict:
        """Summarize cache contents for the CLI."""
        cutoff = _now() - timedelta(hours=self.config.ttl_hours)
        with self.db.get_session() as session:
            entries = list(session.scalars(select(LLMCacheEntry)))
            live = [e for e in entries if e.created_at is None or e.created_at >= cutoff]
            return {
                "enabled": self.enabled,
                "ttl_hours": self.config.ttl_hours,
                "total_entries": len(entries),
                "live_entries": len(live),
                "expired_entries": len(entries) - len(live),
                "total_hits": sum(e.hit_count or 0 for e in entries),
                "oldest_entry_at": min((e.created_at for e in entries if e.created_at), default=None),
            }
