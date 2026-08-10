"""Tests for the local LLM response cache."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from src.analysis import llm_client
from src.analysis.llm_cache import LLMCache, _now
from src.analysis.llm_client import LLMClient
from src.config import LLMCacheConfig, LLMConfig
from src.storage.models import LLMCacheEntry


@pytest.fixture
def cache(test_db):
    return LLMCache(test_db, LLMCacheConfig(enabled=True, ttl_hours=24.0))


def test_key_is_stable_for_identical_requests():
    """The same request must hash identically across calls."""
    payload = {"system_prompt": "sys", "user_message": "msg", "temperature": 1.0}
    assert LLMCache.build_key("m", payload) == LLMCache.build_key("m", dict(payload))


def test_key_ignores_dict_ordering():
    """Key ordering must not create spurious misses."""
    a = LLMCache.build_key("m", {"system_prompt": "s", "user_message": "u"})
    b = LLMCache.build_key("m", {"user_message": "u", "system_prompt": "s"})
    assert a == b


@pytest.mark.parametrize(
    "model,payload",
    [
        ("other-model", {"system_prompt": "s", "user_message": "u"}),
        ("m", {"system_prompt": "s", "user_message": "different"}),
        ("m", {"system_prompt": "different", "user_message": "u"}),
    ],
)
def test_key_changes_when_request_changes(model, payload):
    """Any response-affecting change must produce a new key."""
    baseline = LLMCache.build_key("m", {"system_prompt": "s", "user_message": "u"})
    assert LLMCache.build_key(model, payload) != baseline


def test_miss_then_hit_roundtrip(cache):
    """A stored response is returned on the next lookup."""
    assert cache.get("k1") is None
    cache.put("k1", "cached text", request_context="ctx", llm_model="m")
    assert cache.get("k1") == "cached text"


def test_hit_count_increments(cache, test_db):
    """Replays are counted so reuse is observable."""
    cache.put("k1", "text")
    cache.get("k1")
    cache.get("k1")
    with test_db.get_session() as session:
        entry = session.query(LLMCacheEntry).filter_by(cache_key="k1").one()
        assert entry.hit_count == 2


def test_expired_entry_is_a_miss_and_is_dropped(test_db):
    """A response past its TTL must not be served."""
    cache = LLMCache(test_db, LLMCacheConfig(enabled=True, ttl_hours=1.0))
    cache.put("k1", "stale")
    with test_db.get_session() as session:
        entry = session.query(LLMCacheEntry).filter_by(cache_key="k1").one()
        entry.created_at = _now() - timedelta(hours=2)
        session.commit()

    assert cache.get("k1") is None
    with test_db.get_session() as session:
        assert session.query(LLMCacheEntry).filter_by(cache_key="k1").count() == 0


def test_put_replaces_existing_entry(cache):
    """Re-storing a key refreshes the response instead of duplicating it."""
    cache.put("k1", "first")
    cache.put("k1", "second")
    assert cache.get("k1") == "second"


def test_disabled_cache_never_stores_or_serves(test_db):
    """Disabling the cache must fully bypass it."""
    cache = LLMCache(test_db, LLMCacheConfig(enabled=False))
    cache.put("k1", "text")
    assert cache.get("k1") is None
    with test_db.get_session() as session:
        assert session.query(LLMCacheEntry).count() == 0


def test_clear_removes_all_entries(cache):
    """clear() drops everything and reports the count."""
    cache.put("k1", "a")
    cache.put("k2", "b")
    assert cache.clear() == 2
    assert cache.get("k1") is None


def test_purge_expired_only_removes_stale_rows(test_db):
    """Live entries survive a purge; stale ones do not."""
    cache = LLMCache(test_db, LLMCacheConfig(enabled=True, ttl_hours=1.0))
    cache.put("fresh", "a")
    cache.put("stale", "b")
    with test_db.get_session() as session:
        entry = session.query(LLMCacheEntry).filter_by(cache_key="stale").one()
        entry.created_at = _now() - timedelta(hours=5)
        session.commit()

    assert cache.purge_expired() == 1
    assert cache.get("fresh") == "a"


def test_stats_separates_live_and_expired(test_db):
    """Stats let the CLI show what a re-run would replay."""
    cache = LLMCache(test_db, LLMCacheConfig(enabled=True, ttl_hours=1.0))
    cache.put("fresh", "a")
    cache.put("stale", "b")
    with test_db.get_session() as session:
        entry = session.query(LLMCacheEntry).filter_by(cache_key="stale").one()
        entry.created_at = _now() - timedelta(hours=5)
        session.commit()

    stats = cache.stats()
    assert stats["total_entries"] == 2
    assert stats["live_entries"] == 1
    assert stats["expired_entries"] == 1


def _stub_completion(monkeypatch, calls: list):
    """Count provider calls the way the other llm_client tests do."""

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="模型回复"))]
        )

    monkeypatch.setattr(llm_client, "completion", fake_completion)


def test_client_second_call_spends_no_tokens(test_db, monkeypatch):
    """The point of the cache: an identical request must not reach the provider."""
    calls = []
    _stub_completion(monkeypatch, calls)
    client = LLMClient(
        LLMConfig(provider="openai", model="gpt-4o-mini", api_key="k"),
        cache=LLMCache(test_db, LLMCacheConfig(enabled=True)),
    )

    first = client.chat("sys", "user", request_context="fundamental:a_share/600519")
    second = client.chat("sys", "user", request_context="fundamental:a_share/600519")

    assert first == second == "模型回复"
    assert len(calls) == 1


def test_client_calls_provider_again_when_prompt_changes(test_db, monkeypatch):
    """Changed market data must still trigger a real analysis."""
    calls = []
    _stub_completion(monkeypatch, calls)
    client = LLMClient(
        LLMConfig(provider="openai", model="gpt-4o-mini", api_key="k"),
        cache=LLMCache(test_db, LLMCacheConfig(enabled=True)),
    )

    client.chat("sys", "user one")
    client.chat("sys", "user two")

    assert len(calls) == 2


def test_client_without_cache_always_calls_provider(monkeypatch):
    """Omitting the cache preserves the previous behavior."""
    calls = []
    _stub_completion(monkeypatch, calls)
    client = LLMClient(LLMConfig(provider="openai", model="gpt-4o-mini", api_key="k"))

    client.chat("sys", "user")
    client.chat("sys", "user")

    assert len(calls) == 2
