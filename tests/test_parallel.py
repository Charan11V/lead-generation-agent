from __future__ import annotations

import time

from frequency_agent.parallel import map_parallel


def test_map_parallel_preserves_order():
    items = list(range(8))

    def slow(x: int) -> int:
        time.sleep(0.01)
        return x * 2

    out = map_parallel(items, slow, max_workers=4)
    assert out == [x * 2 for x in items]


def test_map_parallel_empty():
    assert map_parallel([], lambda x: x) == []


def test_map_parallel_return_exceptions_preserves_order():
    def flaky(x: int):
        if x == 3:
            raise RuntimeError("boom")
        return x

    out = map_parallel([1, 2, 3, 4], flaky, max_workers=2, return_exceptions=True)
    assert out[0] == 1
    assert out[1] == 2
    assert isinstance(out[2], RuntimeError)
    assert out[3] == 4
