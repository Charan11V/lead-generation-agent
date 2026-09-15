"""Background agent jobs survive Streamlit reruns."""

from __future__ import annotations

import importlib
import os
import time
from pathlib import Path

import frequency_agent.jobs as jobs_mod
from frequency_agent.jobs import JobStore, job_thread_alive, start_agent_job
from frequency_agent.memory import Memory


def test_job_store_progress_and_complete(tmp_path: Path):
    db = tmp_path / "jobs.db"
    store = JobStore(path=db)
    jid = store.create(
        owner_email="a@example.com",
        query_id="q1",
        icp_text="fintech India",
        search_mode="New query",
    )
    store.mark_running(jid)
    store.patch_progress(jid, stage="search_web", logs=["hit"], funnel={"urls": 3}, run_id="r1")
    job = store.get(jid)
    assert job["status"] == "running"
    assert job["stage"] == "search_web"
    assert job["logs"] == ["hit"]
    assert job["funnel"]["urls"] == 3
    assert job["run_id"] == "r1"

    store.complete(
        jid,
        {
            "run_id": "r1",
            "query_id": "q1",
            "leads": [{"lead_id": "x"}],
            "logs": ["done"],
            "funnel": {"queued": 1},
        },
    )
    done = store.get(jid)
    assert done["status"] == "done"
    assert done["result"]["lead_count"] == 1
    assert store.active_for_owner("a@example.com") is None


def test_reclaim_survives_module_reload(tmp_path: Path):
    """Streamlit reloads jobs.py every run — must not interrupt live workers."""
    db = tmp_path / "reload.db"
    rt = jobs_mod._runtime()
    rt.reclaimed_for_pid = os.getpid()
    store = JobStore(path=db)
    jid = store.create(
        owner_email="a@example.com",
        query_id="q-reload",
        icp_text="saas",
    )
    store.mark_running(jid)

    importlib.reload(jobs_mod)
    again = jobs_mod.JobStore(path=db)
    job = again.get(jid)
    assert job["status"] == "running"


def test_start_agent_job_runs_in_background(tmp_path: Path, monkeypatch):
    db = tmp_path / "bg.db"
    Memory(path=db, owner_email="a@example.com")  # ensure schema
    # Mark reclaim already done for this PID so JobStore won't interrupt the new job.
    rt = jobs_mod._runtime()
    rt.reclaimed_for_pid = os.getpid()

    def fake_run_agent(**kwargs):
        on_update = kwargs.get("on_update")
        if on_update:
            on_update("enrich", {"logs": ["working"], "run_id": "run_bg", "funnel": {}})
        time.sleep(0.15)
        return {
            "run_id": "run_bg",
            "query_id": kwargs.get("query_id") or "",
            "leads": [],
            "logs": ["working", "done"],
            "funnel": {"queued": 0},
            "owner_email": kwargs.get("owner_email") or "",
        }

    monkeypatch.setattr("frequency_agent.graph.run_agent", fake_run_agent)

    jid = start_agent_job(
        owner_email="a@example.com",
        query_id="qbg",
        icp_text="saas india",
        openai_key="sk-test",
        db_path=db,
    )
    assert jid
    assert job_thread_alive(jid) or JobStore(path=db).get(jid)["status"] in {
        "queued",
        "running",
        "done",
    }

    store = JobStore(path=db)
    for _ in range(50):
        job = store.get(jid)
        if job and job["status"] in {"done", "failed"}:
            break
        time.sleep(0.05)
    job = store.get(jid)
    assert job["status"] == "done"
    assert job["run_id"] == "run_bg"
    assert not job_thread_alive(jid)
