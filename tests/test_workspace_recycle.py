from pathlib import Path
import tempfile

from frequency_agent.memory import Memory, resolve_search_name


def test_soft_delete_search_and_restore():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        qid = mem.create_query_session("fintech India Series B", "exec_search", label="")
        mem.save_run(
            "runsoft123456",
            "fintech India Series B",
            "exec_search",
            {"queued": 0},
            query_id=qid,
            lead_ids=[],
            new_lead_ids=[],
        )
        assert len(mem.list_query_sessions()) == 1
        assert len(mem.list_runs_for_query(qid)) == 1
        mem.soft_delete_query_sessions([qid])
        assert mem.list_query_sessions() == []
        assert mem.list_runs_for_query(qid) == []
        deleted = mem.list_deleted_query_sessions()
        assert len(deleted) == 1
        assert deleted[0]["query_id"] == qid
        mem.restore_query_sessions([qid])
        assert len(mem.list_query_sessions()) == 1
        assert len(mem.list_runs_for_query(qid)) == 1


def test_empty_label_stores_icp_as_name():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        qid = mem.create_query_session("AI fintech Series B startups in India", label="")
        sess = mem.get_query_session(qid)
        name = resolve_search_name(sess)
        assert "AI fintech Series B" in name
