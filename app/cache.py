"""Cache em memória com TTL — pronto para substituição por Redis."""
import time
from typing import Any, Optional

_store: dict[str, tuple[Any, float]] = {}


def cache_get(key: str, ttl: int = 300) -> Optional[Any]:
    entry = _store.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.time() > expires_at:
        del _store[key]
        return None
    return value


def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    _store[key] = (value, time.time() + ttl)


def cache_delete(key: str) -> None:
    _store.pop(key, None)
