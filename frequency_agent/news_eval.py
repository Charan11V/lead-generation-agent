"""Background Check-relevance workers — many stories at once, UI stays clickable.

Threads live in a process-global runtime so Streamlit reruns / module reloads
do not cancel in-flight evaluations.
"""

from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

from .news_desk import evaluate_article
from .news_store import NewsStore

_RUNTIME_NAME = "_frequency_news_eval_runtime"
_MAX_PARALLEL = 4


def _runtime() -> types.SimpleNamespace:
    ns = sys.modules.get(_RUNTIME_NAME)
    if ns is None:
        ns = types.SimpleNamespace(
            lock=threading.Lock(),
            threads={},
            gate=threading.Semaphore(_MAX_PARALLEL),
        )
        sys.modules[_RUNTIME_NAME] = ns  # type: ignore[assignment]
    return ns  # type: ignore[return-value]


def inflight_ids() -> set[str]:
    rt = _runtime()
    with rt.lock:
        out: set[str] = set()
        for nid, thread in rt.threads.items():
            if thread is None or thread.is_alive() or thread.ident is None:
                out.add(nid)
        return out


def is_running(news_id: str) -> bool:
    nid = (news_id or "").strip()
    if not nid:
        return False
    return nid in inflight_ids()


def start_eval(
    *,
    news_id: str,
    owner_email: str,
    db_path: str | Path,
    openai_key: str = "",
    item: dict | None = None,
) -> bool:
    """Mark the story as evaluating and return immediately. Work continues in a thread."""
    nid = (news_id or "").strip()
    owner = (owner_email or "").strip().lower()
    if not nid or not owner:
        return False
    store = NewsStore(db_path, owner_email=owner)
    row = item or store.get_item(nid)
    if not row:
        return False
    status = (row.get("eval_status") or "").strip()
    if status in {"relevant", "not_relevant"} and (row.get("eval_why") or ""):
        return False

    rt = _runtime()
    thread: threading.Thread | None = None
    with rt.lock:
        existing = rt.threads.get(nid)
        if existing is not None and existing.is_alive():
            return False
        store.mark_eval_running(nid)
        snapshot = dict(row)
        thread = threading.Thread(
            target=_worker,
            kwargs={
                "news_id": nid,
                "owner_email": owner,
                "db_path": str(Path(db_path)),
                "openai_key": openai_key or "",
                "item": snapshot,
            },
            name=f"news-eval-{nid[:10]}",
            daemon=True,
        )
        rt.threads[nid] = thread
    thread.start()
    return True


def _worker(
    *,
    news_id: str,
    owner_email: str,
    db_path: str,
    openai_key: str,
    item: dict,
) -> None:
    rt = _runtime()
    store = NewsStore(db_path, owner_email=owner_email)
    try:
        with rt.gate:
            result = evaluate_article(item, openai_key)
        store.save_evaluation(
            news_id,
            relevant=bool(result.get("relevant")),
            why=result.get("why") or "",
            service_line=result.get("service_line") or "",
        )
    except Exception:
        store.save_evaluation(
            news_id,
            relevant=False,
            why="Evaluation could not finish. Try Check relevance again.",
        )
    finally:
        with rt.lock:
            rt.threads.pop(news_id, None)


def reclaim_stale(store: NewsStore) -> int:
    """Clear running flags that have no live thread in this process (server restart)."""
    live = inflight_ids()
    return store.clear_stale_eval_running(except_ids=live)
