"""Shared outreach pipeline: per-user queue, team board, status history."""

from __future__ import annotations

import pytest
from pathlib import Path

from frequency_agent.memory import Memory
from frequency_agent.similarity import company_entity_id


def _lead(lead_id: str, name: str, domain: str, person: str, email: str = "") -> dict:
    return {
        "lead_id": lead_id,
        "name": name,
        "domain": domain,
        "query_id": "",
        "contact": {"name": person, "role": "CEO", "email": email},
        "contacts": [],
        "score": {"total": 10},
        "signal": {"summary": "s", "usable_in_outreach": True},
    }


def test_pipeline_is_owner_scoped_but_team_board_is_shared(tmp_path: Path):
    db = tmp_path / "pipe.db"
    alice = Memory(path=db, owner_email="alice@example.com")
    bob = Memory(path=db, owner_email="bob@example.com")

    alice.upsert_pipeline_from_lead(
        _lead("lead_a", "Acme Pay", "acmepay.com", "Jane Founder", "jane@acmepay.com"),
        query_id="q_a",
        icp_text="fintech founders in India",
        search_name="Fintech India",
    )
    bob.upsert_pipeline_from_lead(
        _lead("lead_b", "Acme Payments", "acmepay.com", "Priya Sharma", "priya@acmepay.com"),
        query_id="q_b",
        icp_text="Series B CXOs",
        search_name="CXO search",
    )

    assert len(alice.list_pipeline()) == 1
    assert alice.list_pipeline()[0]["owner_email"] == "alice@example.com"
    assert len(bob.list_pipeline()) == 1
    team = alice.list_team_pipeline()
    assert len(team) == 2
    owners = {r["owner_email"] for r in team}
    assert owners == {"alice@example.com", "bob@example.com"}
    assert team[0]["company_entity_id"] == company_entity_id("acmepay.com", "Acme Pay")


def test_status_flow_is_sequential_and_response_becomes_ongoing(tmp_path: Path):
    db = tmp_path / "status.db"
    alice = Memory(path=db, owner_email="alice@example.com")
    bob = Memory(path=db, owner_email="bob@example.com")
    item = alice.upsert_pipeline_from_lead(
        _lead("lead_a", "Acme Pay", "acmepay.com", "Jane Founder"),
    )
    pid = int(item["id"])
    with pytest.raises(ValueError, match="in order"):
        alice.update_pipeline_status(pid, "success", "too soon")
    alice.update_pipeline_status(pid, "outreach_sent", "Email logged")
    # "Response received" lands on ongoing automatically.
    updated = alice.update_pipeline_status(pid, "ongoing", "Replied on LinkedIn")
    assert updated["pipeline_status"] == "ongoing"
    with pytest.raises(ValueError, match="comment"):
        alice.update_pipeline_status(pid, "success", "")
    closed = alice.update_pipeline_status(pid, "success", "Signed intro call")
    assert closed["pipeline_status"] == "success"
    assert closed["comment"] == "Signed intro call"

    with pytest.raises(PermissionError):
        bob.update_pipeline_status(pid, "failure", "not mine")

    events = alice.list_pipeline_events(pid)
    actions = [e["action"] for e in events]
    assert "created" in actions
    assert "status" in actions
    team_events = bob.list_pipeline_events(team=True)
    assert any(e.get("pipeline_id") == pid for e in team_events)


def test_requeue_does_not_reset_progressed_status(tmp_path: Path):
    db = tmp_path / "requeue.db"
    mem = Memory(path=db, owner_email="alex@example.com")
    lead = _lead("lead_a", "Acme Pay", "acmepay.com", "Jane Founder")
    item = mem.upsert_pipeline_from_lead(lead, send_queue_id=1)
    mem.update_pipeline_status(int(item["id"]), "outreach_sent", "sent")
    again = mem.upsert_pipeline_from_lead(lead, send_queue_id=2)
    assert again["id"] == item["id"]
    assert again["pipeline_status"] == "outreach_sent"
    assert again["send_queue_id"] == 2


def test_remove_pipeline_item_drops_queue_and_send_row(tmp_path: Path):
    db = tmp_path / "rm-pipe.db"
    alice = Memory(path=db, owner_email="alice@example.com")
    bob = Memory(path=db, owner_email="bob@example.com")
    lead = _lead("lead_a", "Acme Pay", "acmepay.com", "Jane Founder")
    qid = alice.enqueue_send(
        {
            "lead_id": "lead_a",
            "company": "Acme Pay",
            "channel": "company",
            "recipient": "Jane",
            "subject": "s",
            "body": "{}",
        }
    )
    item = alice.upsert_pipeline_from_lead(lead, send_queue_id=qid)
    pid = int(item["id"])
    bob.upsert_pipeline_from_lead(_lead("lead_b", "Beta", "beta.com", "Ben"))

    with pytest.raises(PermissionError):
        bob.remove_pipeline_item(pid)

    removed = alice.remove_pipeline_item(pid)
    assert removed["company"] == "Acme Pay"
    assert alice.list_pipeline() == []
    assert alice.list_send_queue("queued") == []
    assert len(bob.list_pipeline()) == 1


def test_clear_all_data_wipes_own_pipeline_only(tmp_path: Path):
    db = tmp_path / "wipe-pipe.db"
    a = Memory(path=db, owner_email="a@example.com")
    b = Memory(path=db, owner_email="b@example.com")
    a.upsert_pipeline_from_lead(_lead("la", "Acme", "acme.com", "Ann"))
    b.upsert_pipeline_from_lead(_lead("lb", "Beta", "beta.com", "Ben"))
    a.clear_all_data()
    assert a.list_pipeline() == []
    assert len(b.list_pipeline()) == 1
    assert len(a.list_team_pipeline()) == 1
