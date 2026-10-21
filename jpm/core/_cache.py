from collections import OrderedDict
import typing
from typing import Any


class _LRUCache:
    """Simple LRU cache for frequent query results.
    Caches the last N unique queries to avoid repeated DB hits.
    """
    def __init__(self, max_size: int = 128):
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> typing.Optional[Any]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def invalidate(self, prefix: str = "") -> None:
        if not prefix:
            self._cache.clear()
        else:
            keys = [k for k in self._cache if k.startswith(prefix)]
            for k in keys:
                del self._cache[k]

    def clear(self) -> None:
        self._cache.clear()


# Global cache (lazy init)
_CACHE: _LRUCache | None = None


def _get_cache() -> _LRUCache:
    global _CACHE
    if _CACHE is None:
        _CACHE = _LRUCache()
    return _CACHE