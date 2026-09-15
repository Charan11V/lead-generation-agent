from frequency_agent.memory import (
    Memory,
    default_search_name,
    format_fetch_label,
)
from pathlib import Path
import tempfile


def test_format_fetch_label():
    assert "Fintech" in format_fetch_label("Fintech Series B", "abcdef123456", "2026-09-03T12:00:00+00:00")
    assert "abcdef123456"[:12] in format_fetch_label("Fintech", "abcdef123456789", "2026-09-03T12:00:00")
    assert "Untitled search" in format_fetch_label("", "abc", "")


def test_rename_search_updates_fetch_labels():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        qid = mem.create_query_session("fintech India Series B", "exec_search", label="Old name")
        mem.save_run(
            "runabc123456",
            "fintech India Series B",
            "exec_search",
            {"queued": 0},
            query_id=qid,
            lead_ids=[],
            new_lead_ids=[],
        )
        before = mem.list_runs_for_query(qid)[0]["label"]
        assert "Old name" in before
        mem.rename_query_session(qid, "Fintech B India")
        after = mem.list_runs_for_query(qid)[0]["label"]
        assert after.startswith("Fintech B India")
        assert "runabc123456"[:12] in after
        assert mem.get_query_session(qid)["label"] == "Fintech B India"


def test_default_search_name():
    assert "Untitled" in default_search_name("")
    assert "fintech" in default_search_name("fintech India").lower()
