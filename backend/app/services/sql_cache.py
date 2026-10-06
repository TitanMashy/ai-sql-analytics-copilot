"""Optional prompt-to-SQL cache (``SQL_CACHE_ENABLED``, off by default).

Caches the SQL that answered a standalone question, so a repeat skips the LLM call. It never
caches result rows: a cache hit still runs the cached SQL through the validator and the tenant-
scoped executor, so a hit returns the caller's own fresh data. Entries are keyed by the
normalized question, a fingerprint of the analytics schema (a schema change invalidates every
entry), and the tenant; only successful, fully executed answers are stored, and conversations with
prior context are never cached because their SQL depends on that context.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock

from app.core.auth import Principal
from app.core.config import get_settings


@dataclass(frozen=True)
class CachedSql:
    sql: str
    explanation: str
    tables_used: tuple[str, ...]
    confidence: float | None
    provider: str


def normalize_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.casefold()).strip(" ?!.")


def tenant_key(principal: Principal | None) -> str:
    if principal is None:
        return "none"
    if principal.is_global:
        return "global"
    return f"customer:{principal.customer_id}"


class SqlCache:
    def __init__(self, ttl_seconds: float = 300, max_entries: int = 1000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[str, str, str], tuple[float, CachedSql]] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def key(
        question: str, schema_version: str, principal: Principal | None
    ) -> tuple[str, str, str]:
        return (normalize_question(question), schema_version, tenant_key(principal))

    def get(self, key: tuple[str, str, str]) -> CachedSql | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.monotonic() - stored_at > self.ttl_seconds:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def put(self, key: tuple[str, str, str], value: CachedSql) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic(), value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def discard(self, key: tuple[str, str, str]) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


@lru_cache
def get_sql_cache() -> SqlCache | None:
    """The process cache, or ``None`` when the feature is off."""
    settings = get_settings()
    if not settings.sql_cache_enabled:
        return None
    return SqlCache(settings.sql_cache_ttl_seconds, settings.sql_cache_max_entries)
