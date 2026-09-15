"""Durable background agent jobs — survive Streamlit reruns, navigation, and refresh.

The Streamlit script run can be cancelled when the user clicks elsewhere or refreshes.
Jobs run in a process-local thread and persist progress + results in SQLite so the UI
can reconnect and the fetch still completes (same container process).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .util import default_db_path

# Process-global runtime — must survive importlib.reload(jobs) on every Streamlit rerun.
_RUNTIME_NAME = "_frequency_agent_job_runtime"


def _runtime() -> types.SimpleNamespace:
    ns = sys.modules.get(_RUNTIME_NAME)
    if ns is None:
        ns = types.SimpleNamespace(
            lock=threading.Lock(),
            threads={},
            reclaimed_for_pid=None,
        )
        sys.modules[_RUNTIME_NAME] = ns  # type: ignore[assignment]
    return ns  # type: ignore[return-value]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()
        self._reclaim_stale_once()

    def _connect(self):
        import sqlite3

        conn = sqlite3.connect(self.path, timeout=60)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=60000")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_jobs (
                    job_id TEXT PRIMARY KEY,
                    owner_email TEXT NOT NULL,
                    query_id TEXT,
                    icp_text TEXT,
                    status TEXT NOT NULL,
                    stage TEXT DEFAULT '',
                    run_id TEXT DEFAULT '',
                    search_mode TEXT DEFAULT '',
                    is_fetch_more INTEGER DEFAULT 0,
                    error TEXT DEFAULT '',
                    logs_json TEXT DEFAULT '[]',
                    funnel_json TEXT DEFAULT '{}',
                    result_json TEXT DEFAULT '{}',
                    created_at TEXT,
                    updated_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_agent_jobs_owner_status
                    ON agent_jobs (owner_email, status, updated_at);
                """
            )

    def _reclaim_stale_once(self) -> None:
        """On real process start only — mark leftover rows interrupted (not on Streamlit reload)."""
        rt = _runtime()
        pid = os.getpid()
        with rt.lock:
            if rt.reclaimed_for_pid == pid:
                return
            rt.reclaimed_for_pid = pid
            # Never reclaim jobs that still have a live worker thread in this process.
            live = {jid for jid, t in rt.threads.items() if t and t.is_alive()}
            now = _now()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT job_id FROM agent_jobs WHERE status IN ('queued', 'running')"
                ).fetchall()
                for row in rows:
                    jid = row["job_id"]
                    if jid in live:
                        continue
                    conn.execute(
                        """
                        UPDATE agent_jobs
                        SET status = 'interrupted',
                            error = 'Server restarted while this fetch was running. Start the search again.',
                            updated_at = ?,
                            finished_at = ?
                        WHERE job_id = ? AND status IN ('queued', 'running')
                        """,
                        (now, now, jid),
                    )

    def create(
        self,
        *,
        owner_email: str,
        query_id: str,
        icp_text: str,
        search_mode: str = "",
        is_fetch_more: bool = False,
    ) -> str:
        job_id = uuid.uuid4().hex[:16]
        now = _now()
        owner = (owner_email or "").strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_jobs (
                    job_id, owner_email, query_id, icp_text, status, stage,
                    search_mode, is_fetch_more, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', 'queued', ?, ?, ?, ?)
                """,
                (
                    job_id,
                    owner,
                    query_id or "",
                    icp_text or "",
                    search_mode or "",
                    1 if is_fetch_more else 0,
                    now,
                    now,
                ),
            )
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM agent_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row(row) if row else None

    def active_for_owner(self, owner_email: str) -> dict | None:
        owner = (owner_email or "").strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_jobs
                WHERE owner_email = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (owner,),
            ).fetchone()
        return self._row(row) if row else None

    def active_for_query(self, owner_email: str, query_id: str) -> dict | None:
        owner = (owner_email or "").strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_jobs
                WHERE owner_email = ? AND query_id = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (owner, query_id or ""),
            ).fetchone()
        return self._row(row) if row else None

    def latest_finished_for_owner(self, owner_email: str, *, after: str = "") -> dict | None:
        owner = (owner_email or "").strip().lower()
        with self._connect() as conn:
            if after:
                row = conn.execute(
                    """
                    SELECT * FROM agent_jobs
                    WHERE owner_email = ? AND status IN ('done', 'failed', 'interrupted')
                      AND finished_at > ?
                    ORDER BY finished_at DESC
                    LIMIT 1
                    """,
                    (owner, after),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM agent_jobs
                    WHERE owner_email = ? AND status IN ('done', 'failed', 'interrupted')
                    ORDER BY finished_at DESC
                    LIMIT 1
                    """,
                    (owner,),
                ).fetchone()
        return self._row(row) if row else None

    def mark_running(self, job_id: str) -> None:
        self._patch(job_id, status="running", stage="parse_icp")

    def patch_progress(
        self,
        job_id: str,
        *,
        stage: str = "",
        logs: list | None = None,
        funnel: dict | None = None,
        run_id: str = "",
    ) -> None:
        fields: dict[str, Any] = {}
        if stage:
            fields["stage"] = stage
        if logs is not None:
            fields["logs_json"] = json.dumps(logs[-80:], ensure_ascii=False)
        if funnel is not None:
            fields["funnel_json"] = json.dumps(funnel, ensure_ascii=False)
        if run_id:
            fields["run_id"] = run_id
        if fields:
            self._patch(job_id, **fields)

    def complete(self, job_id: str, result: dict) -> None:
        err = (result.get("error") or "").strip()
        status = "failed" if err else "done"
        self._patch(
            job_id,
            status=status,
            stage="failed" if err else "done",
            error=err,
            run_id=(result.get("run_id") or "").strip(),
            logs_json=json.dumps((result.get("logs") or [])[-80:], ensure_ascii=False),
            funnel_json=json.dumps(result.get("funnel") or {}, ensure_ascii=False),
            result_json=json.dumps(
                {
                    "run_id": result.get("run_id") or "",
                    "query_id": result.get("query_id") or "",
                    "icp_hash": result.get("icp_hash") or "",
                    "csv_path": result.get("csv_path") or "",
                    "service_line": (result.get("icp") or {}).get("service_line")
                    or result.get("service_line")
                    or "",
                    "lead_count": len(result.get("leads") or []),
                    "skipped_seen": result.get("skipped_seen") or 0,
                },
                ensure_ascii=False,
            ),
            finished_at=_now(),
        )

    def fail(self, job_id: str, message: str) -> None:
        self._patch(
            job_id,
            status="failed",
            stage="failed",
            error=(message or "Job failed")[:2000],
            finished_at=_now(),
        )

    def _patch(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields = dict(fields)
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [job_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE agent_jobs SET {cols} WHERE job_id = ?", vals)

    @staticmethod
    def _row(row) -> dict:
        d = dict(row)
        try:
            d["logs"] = json.loads(d.get("logs_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            d["logs"] = []
        try:
            d["funnel"] = json.loads(d.get("funnel_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            d["funnel"] = {}
        try:
            d["result"] = json.loads(d.get("result_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            d["result"] = {}
        if not isinstance(d["logs"], list):
            d["logs"] = []
        if not isinstance(d["funnel"], dict):
            d["funnel"] = {}
        if not isinstance(d["result"], dict):
            d["result"] = {}
        d["is_fetch_more"] = bool(int(d.get("is_fetch_more") or 0))
        return d


def job_thread_alive(job_id: str) -> bool:
    rt = _runtime()
    with rt.lock:
        t = rt.threads.get(job_id)
    return bool(t and t.is_alive())


def start_agent_job(
    *,
    owner_email: str,
    query_id: str,
    icp_text: str,
    openai_key: str,
    tavily_key: str = "",
    search_mode: str = "",
    is_fetch_more: bool = False,
    db_path: str | Path | None = None,
) -> str:
    """Create a DB job and start a background thread. Returns job_id."""
    store = JobStore(path=db_path)
    owner = (owner_email or "").strip().lower()
    existing = store.active_for_query(owner, query_id)
    if existing and job_thread_alive(existing["job_id"]):
        return existing["job_id"]
    if existing and not job_thread_alive(existing["job_id"]):
        store.fail(
            existing["job_id"],
            "Previous fetch worker stopped unexpectedly. Starting a new one.",
        )

    job_id = store.create(
        owner_email=owner,
        query_id=query_id,
        icp_text=icp_text,
        search_mode=search_mode,
        is_fetch_more=is_fetch_more,
    )

    def _worker() -> None:
        local = JobStore(path=db_path)
        local.mark_running(job_id)
        try:
            from .graph import run_agent

            def on_update(node: str, state: dict) -> None:
                local.patch_progress(
                    job_id,
                    stage=node or "",
                    logs=list(state.get("logs") or []),
                    funnel=dict(state.get("funnel") or {}),
                    run_id=(state.get("run_id") or ""),
                )

            result = run_agent(
                icp_text=icp_text,
                openai_key=openai_key,
                tavily_key=tavily_key or "",
                query_id=query_id,
                on_update=on_update,
                owner_email=owner,
            )
            # Ensure query_id on result for UI apply
            if isinstance(result, dict) and query_id and not result.get("query_id"):
                result["query_id"] = query_id
            local.complete(job_id, result if isinstance(result, dict) else {})
        except Exception as exc:
            local.fail(
                job_id,
                f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}",
            )
        finally:
            rt = _runtime()
            with rt.lock:
                rt.threads.pop(job_id, None)

    thread = threading.Thread(
        target=_worker,
        name=f"frequency-agent-job-{job_id}",
        daemon=False,
    )
    rt = _runtime()
    with rt.lock:
        rt.threads[job_id] = thread
    thread.start()
    return job_id
