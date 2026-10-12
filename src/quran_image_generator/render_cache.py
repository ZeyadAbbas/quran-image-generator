"""Bounded, thread-safe caches for immutable measurements and preview assets."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class RenderCache(Generic[K, V]):
    def __init__(
        self,
        capacity: int,
        *,
        max_bytes: int = 64 * 1024 * 1024,
        dispose: Callable[[V], None] | None = None,
    ) -> None:
        self.capacity = capacity
        self.max_bytes = max_bytes
        self._dispose = dispose
        self._items: OrderedDict[K, tuple[V, int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    def get(self, key: K) -> V | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return item[0]

    def copy(self, key: K, clone: Callable[[V], V]) -> V | None:
        """Clone disposable values while eviction is excluded by the cache lock."""
        with self._lock:
            value = self.get(key)
            return None if value is None else clone(value)

    def put(self, key: K, value: V, *, size: int = 1) -> None:
        with self._lock:
            previous = self._items.pop(key, None)
            if previous:
                self._bytes -= previous[1]
                if self._dispose:
                    self._dispose(previous[0])
            if size > self.max_bytes:
                return
            self._items[key] = value, size
            self._bytes += size
            while len(self._items) > self.capacity or self._bytes > self.max_bytes:
                _, (old, cost) = self._items.popitem(last=False)
                self._bytes -= cost
                if self._dispose:
                    self._dispose(old)

    def clear(self) -> None:
        with self._lock:
            if self._dispose:
                for value, _ in self._items.values():
                    self._dispose(value)
            self._items.clear()
            self._bytes = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def file_identity(path: str | Path) -> tuple[str, int, int, int, int]:
    """Invalidate decoded/file-derived data after a file is replaced or edited.

    Pinned font/asset SHA-256 verification remains separate and is performed on
    every caption request. This inexpensive key never replaces that check.
    """
    selected = Path(path).resolve()
    stat = selected.stat()
    return str(selected), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


class CaptionRenderCache:
    """One editor session's fitted plans and exact PNG bytes; no stale paths."""

    def __init__(self) -> None:
        self.plans: RenderCache[str, tuple] = RenderCache(
            128, max_bytes=16 * 1024 * 1024
        )
        self.assets: RenderCache[str, tuple] = RenderCache(
            256, max_bytes=64 * 1024 * 1024
        )

    def clear(self) -> None:
        self.plans.clear()
        self.assets.clear()
