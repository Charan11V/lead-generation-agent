"""Thread-pool helpers for I/O-bound pipeline stages (search, fetch, enrich)."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

# BaseException is used in annotations for return_exceptions mode.


def worker_count(env_name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(env_name, str(default))))
    except ValueError:
        return default


def map_parallel(
    items: list[T],
    fn: Callable[[T], R],
    *,
    max_workers: int | None = None,
    env_name: str = "PARALLEL_WORKERS",
    default_workers: int = 6,
    return_exceptions: bool = False,
) -> list[R | BaseException]:
    """Run fn over items in a thread pool; preserves input order.

    When return_exceptions=True, failures become Exception instances in the
    result list instead of aborting the whole batch.
    """
    if not items:
        return []
    workers = max_workers or worker_count(env_name, default_workers)
    workers = min(workers, len(items))

    def _call(x: T) -> R | BaseException:
        try:
            return fn(x)
        except BaseException as exc:
            if return_exceptions:
                return exc
            raise

    if workers <= 1:
        return [_call(x) for x in items]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        if not return_exceptions:
            return list(pool.map(fn, items))
        futures = {pool.submit(fn, item): idx for idx, item in enumerate(items)}
        out: list[R | BaseException] = [None] * len(items)  # type: ignore[list-item]
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                out[idx] = fut.result()
            except BaseException as exc:
                out[idx] = exc
        return out
