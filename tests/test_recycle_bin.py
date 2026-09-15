from pathlib import Path
import tempfile

from frequency_agent.memory import Memory


def test_soft_delete_run_alone_and_restore():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        qid = mem.create_query_session("fintech India", "exec_search", label="Fintech")
        mem.save_run(
            "runkeep000001",
            "fintech India",
            "exec_search",
            {"queued": 0},
            query_id=qid,
            lead_ids=[],
            new_lead_ids=[],
        )
        mem.save_run(
            "runtrash00002",
            "fintech India",
            "exec_search",
            {"queued": 0},
            query_id=qid,
            lead_ids=[],
            new_lead_ids=[],
        )
        assert len(mem.list_runs_for_query(qid)) == 2
        mem.soft_delete_runs(["runtrash00002"])
        active = {r["run_id"] for r in mem.list_runs_for_query(qid)}
        assert active == {"runkeep000001"}
        deleted = mem.list_deleted_runs()
        assert any(r["run_id"] == "runtrash00002" for r in deleted)
        mem.restore_runs(["runtrash00002"])
        assert {r["run_id"] for r in mem.list_runs_for_query(qid)} == {
            "runkeep000001",
            "runtrash00002",
        }


def test_permanent_delete_search():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        qid = mem.create_query_session("gone brief", label="Gone")
        mem.save_run(
            "rungone000001",
            "gone brief",
            "exec_search",
            {"queued": 0},
            query_id=qid,
            lead_ids=[],
            new_lead_ids=[],
        )
        mem.soft_delete_query_sessions([qid])
        assert mem.list_deleted_query_sessions()
        mem.permanently_delete_query_sessions([qid])
        assert mem.list_deleted_query_sessions() == []
        assert mem.get_query_session(qid) is None
