"""Per-account workspace isolation."""

from __future__ import annotations

from pathlib import Path

from frequency_agent.memory import Memory


def _seed_user(mem: Memory, *, label: str, run_id: str, lead_id: str) -> tuple[str, str]:
    qid = mem.create_query_session(f"ICP for {label}", service_line="exec_search", label=label)
    mem.upsert_lead(
        {
            "lead_id": lead_id,
            "name": f"{label} Co",
            "domain": f"{label.lower()}.example",
            "contact": {"name": "A"},
            "score": {"total": 10},
            "signal": {"summary": "s"},
        }
    )
    mem.link_lead_to_query(qid, lead_id, run_id, "q")
    mem.save_run(
        run_id,
        icp=f"ICP for {label}",
        service_line="exec_search",
        funnel={"queued": 1},
        lead_ids=[lead_id],
        new_lead_ids=[lead_id],
        query_id=qid,
    )
    mem.enqueue_send(
        {
            "lead_id": lead_id,
            "company": f"{label} Co",
            "channel": "email",
            "recipient": f"{label.lower()}@example.com",
            "subject": "hi",
            "body": "body",
        }
    )
    return qid, run_id


def test_legacy_data_attributed_and_new_accounts_start_fresh(tmp_path: Path):
    db = tmp_path / "iso.db"

    # Simulate pre-auth data written without an owner (migration backfills LEGACY owner).
    bare = Memory(path=db)  # unscoped
    q_legacy = bare.create_query_session("legacy ICP for Charan", service_line="exec_search", label="Charan search")
    bare.save_run(
        "run_legacy",
        icp="legacy ICP for Charan",
        service_line="exec_search",
        funnel={"queued": 1},
        lead_ids=[],
        query_id=q_legacy,
    )
    bare.upsert_lead(
        {
            "lead_id": "lead_legacy",
            "name": "Legacy Co",
            "domain": "legacy.example",
            "contact": {"name": "A"},
            "score": {"total": 10},
            "signal": {"summary": "s"},
        }
    )

    charan = Memory.LEGACY_OWNER_EMAIL
    mem_charan = Memory(path=db, owner_email=charan)
    mem_other = Memory(path=db, owner_email="newuser@example.com")

    assert len(mem_charan.list_query_sessions()) == 1
    assert mem_charan.list_query_sessions()[0]["query_id"] == q_legacy
    assert mem_charan.latest_run() is not None
    assert mem_charan.memory_stats()["queries"] == 1
    assert mem_charan.memory_stats()["seen"] == 1

    # New account sees nothing
    assert mem_other.list_query_sessions() == []
    assert mem_other.latest_run() is None
    assert mem_other.memory_stats()["queries"] == 0
    assert mem_other.memory_stats()["seen"] == 0
    assert mem_other.get_query_session(q_legacy) is None

    # New account can create its own search without touching Charan's
    q_new = mem_other.create_query_session("fresh ICP", label="New search")
    mem_other.save_run(
        "run_new",
        icp="fresh ICP",
        service_line="exec_search",
        funnel={},
        query_id=q_new,
    )
    assert len(mem_other.list_query_sessions()) == 1
    assert len(mem_charan.list_query_sessions()) == 1
    assert mem_charan.list_query_sessions()[0]["query_id"] == q_legacy
    assert mem_other.list_query_sessions()[0]["query_id"] == q_new


def test_clear_all_data_only_wipes_current_owner(tmp_path: Path):
    db = tmp_path / "wipe.db"
    a = Memory(path=db, owner_email="a@example.com")
    b = Memory(path=db, owner_email="b@example.com")
    a.create_query_session("A ICP", label="A")
    b.create_query_session("B ICP", label="B")
    a.clear_all_data()
    assert a.list_query_sessions() == []
    assert len(b.list_query_sessions()) == 1


def test_create_revisit_and_isolation(tmp_path: Path):
    """Writes are owner-tagged; reopen with same owner restores workspace."""
    db = tmp_path / "revisit.db"
    alice = Memory(path=db, owner_email="alice@example.com")
    bob = Memory(path=db, owner_email="bob@example.com")

    q_a, run_a = _seed_user(alice, label="Alice", run_id="run_alice_1", lead_id="lead_alice_1")
    q_b, run_b = _seed_user(bob, label="Bob", run_id="run_bob_1", lead_id="lead_bob_1")

    # Fresh connections simulate login revisit
    alice2 = Memory(path=db, owner_email="alice@example.com")
    bob2 = Memory(path=db, owner_email="bob@example.com")

    assert [s["query_id"] for s in alice2.list_query_sessions()] == [q_a]
    assert [s["query_id"] for s in bob2.list_query_sessions()] == [q_b]
    assert alice2.latest_run()["run_id"] == run_a
    assert bob2.latest_run()["run_id"] == run_b
    assert alice2.load_run(run_a) is not None
    assert alice2.load_run(run_b) is None
    assert bob2.get_query_session(q_a) is None
    assert alice2.leads_for_query(q_a)
    assert alice2.leads_for_query(q_b) == []
    assert len(alice2.list_send_queue()) == 1
    assert alice2.list_send_queue()[0]["lead_id"] == "lead_alice_1"
    assert bob2.list_send_queue()[0]["lead_id"] == "lead_bob_1"


def test_deleted_runs_and_permanent_delete_are_owner_scoped(tmp_path: Path):
    db = tmp_path / "del.db"
    a = Memory(path=db, owner_email="a@example.com")
    b = Memory(path=db, owner_email="b@example.com")
    qa, ra = _seed_user(a, label="A", run_id="run_a_del", lead_id="lead_a_del")
    qb, rb = _seed_user(b, label="B", run_id="run_b_del", lead_id="lead_b_del")

    a.soft_delete_runs([ra])
    deleted_a = a.list_deleted_runs()
    assert any(r["run_id"] == ra for r in deleted_a)
    assert not any(r["run_id"] == rb for r in deleted_a)
    assert b.list_deleted_runs() == []

    # Cannot permanently delete another owner's search/run
    assert a.permanently_delete_query_sessions([qb]) == 0
    assert b.get_query_session(qb) is not None
    assert a.permanently_delete_runs([rb]) == 0
    assert b.load_run(rb) is not None

    a.soft_delete_query_sessions([qa])
    assert a.permanently_delete_query_sessions([qa]) == 1
    assert a.get_query_session(qa) is None
    assert b.get_query_session(qb) is not None


def test_admin_cross_user_visibility_not_leaked_to_normal_scope(tmp_path: Path):
    db = tmp_path / "admin.db"
    a = Memory(path=db, owner_email="user.a@example.com")
    b = Memory(path=db, owner_email="user.b@example.com")
    qa, ra = _seed_user(a, label="A", run_id="run_admin_a", lead_id="lead_admin_a")
    qb, rb = _seed_user(b, label="B", run_id="run_admin_b", lead_id="lead_admin_b")

    admin = Memory(path=db, owner_email="charan.s@frequency.cx")
    # Admin's own scoped Memory still only sees their data
    assert admin.list_query_sessions() == []

    # Explicit admin APIs see everyone
    stats = {s["email"]: s for s in admin.admin_owner_stats()}
    assert stats["user.a@example.com"]["queries"] == 1
    assert stats["user.a@example.com"]["leads"] == 1
    assert stats["user.a@example.com"]["runs"] == 1
    assert stats["user.a@example.com"]["send_queue"] == 1
    assert stats["user.b@example.com"]["queries"] == 1

    sessions_a = admin.admin_list_sessions("user.a@example.com")
    assert [s["query_id"] for s in sessions_a] == [qa]
    runs_b = admin.admin_list_runs("user.b@example.com")
    assert [r["run_id"] for r in runs_b] == [rb]
    loaded = admin.admin_load_run("user.a@example.com", ra)
    assert loaded and loaded["run_id"] == ra
    assert len(loaded.get("leads") or []) == 1
    leads = admin.admin_leads_for_query("user.b@example.com", qb)
    assert len(leads) == 1

    all_s = admin.admin_list_all_sessions()
    all_ids = {s["query_id"] for s in all_s}
    assert qa in all_ids and qb in all_ids
    owners = {s["owner_email"] for s in all_s}
    assert "user.a@example.com" in owners and "user.b@example.com" in owners
    all_r = admin.admin_list_all_runs()
    assert {r["run_id"] for r in all_r} >= {ra, rb}

    all_leads = admin.admin_all_leads()
    assert len(all_leads) >= 2
    owners_leads = {lead.get("owner_email") for lead in all_leads}
    assert "user.a@example.com" in owners_leads and "user.b@example.com" in owners_leads
    only_a = admin.admin_all_leads(owner_email="user.a@example.com")
    assert only_a and all(lead.get("owner_email") == "user.a@example.com" for lead in only_a)
    # Full payloads are returned (contacts nested inside), not just indexed columns.
    assert all("name" in lead or "company" in lead for lead in only_a)

    # Normal user Memory must not use unscoped reads for others
    assert a.admin_list_sessions  # method exists on class
    # But regular list_* stays isolated
    assert a.list_query_sessions()[0]["query_id"] == qa
    assert a.load_run(rb) is None
    assert a.leads_for_query(qb) == []
