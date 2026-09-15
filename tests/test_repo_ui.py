from pathlib import Path

from frequency_agent.memory import Memory
from frequency_agent.repo_ui import cluster_for, filter_repo_rows, owner_color, owner_display
from frequency_agent.similarity import identity_from_lead


def test_owner_color_is_stable_and_differs():
    a = owner_color("ada@frequency.cx")
    b = owner_color("ben@frequency.cx")
    assert a == owner_color("ADA@frequency.cx")
    assert a.startswith("#")
    assert a != b


def test_owner_display_uses_profile_name():
    name, email = owner_display(
        "ada@frequency.cx",
        {"ada@frequency.cx": {"display_name": "Ada"}},
    )
    assert name == "Ada"
    assert email == "ada@frequency.cx"


def test_filter_repo_rows_search_owner_status_similar():
    items = [
        {
            "id": 1,
            "owner_email": "ada@frequency.cx",
            "company": "ThoughtSpot",
            "domain": "thoughtspot.com",
            "person_name": "Jane",
            "person_email": "",
            "search_name": "AI SaaS",
            "icp_text": "",
            "pipeline_status": "queued",
        },
        {
            "id": 2,
            "owner_email": "ben@frequency.cx",
            "company": "Filtrous",
            "domain": "filtrous.com",
            "person_name": "Sam",
            "person_email": "",
            "search_name": "Labs",
            "icp_text": "",
            "pipeline_status": "outreach_sent",
        },
    ]
    assert [r["id"] for r in filter_repo_rows(items, needle="thought")] == [1]
    assert [r["id"] for r in filter_repo_rows(items, owner="ben@frequency.cx")] == [2]
    assert [r["id"] for r in filter_repo_rows(items, status="queued")] == [1]
    only_sim = filter_repo_rows(items, similar_only=True, similar_counts={1: 2, 2: 0})
    assert [r["id"] for r in only_sim] == [1]


def test_cluster_and_unscoped_lead_lookup(tmp_path: Path):
    db = tmp_path / "repo.db"
    ada = Memory(path=db, owner_email="ada@frequency.cx")
    ben = Memory(path=db, owner_email="ben@frequency.cx")
    lead = {
        "lead_id": "ts-1",
        "name": "ThoughtSpot",
        "domain": "thoughtspot.com",
        "email_draft": "Hi from Ada",
        "signal": {"type": "product_launch", "summary": "AI analytics launch", "usable_in_outreach": True},
        "contact": {"name": "Jane Doe", "role": "VP", "email": "jane@thoughtspot.com"},
        "contacts": [{"name": "Jane Doe", "role": "VP", "email": "jane@thoughtspot.com", "is_primary": True}],
    }
    ident = identity_from_lead(lead)
    assert ident["domain"] == "thoughtspot.com"
    ada.upsert_lead(lead, icp_hash="x")
    qid = ada.enqueue_send(
        {
            "lead_id": "ts-1",
            "company": "ThoughtSpot",
            "channel": "company",
            "recipient": "Jane",
            "subject": "ThoughtSpot",
            "body": "Hi",
            "mode": "dry_run",
            "note": "",
        }
    )
    pipe_a = ada.upsert_pipeline_from_lead(lead, send_queue_id=qid, search_name="AI SaaS", channel="company")
    lead_b = dict(lead)
    lead_b["lead_id"] = "ts-2"
    lead_b["email_draft"] = "Hi from Ben"
    ben.upsert_lead(lead_b, icp_hash="y")
    qid_b = ben.enqueue_send(
        {
            "lead_id": "ts-2",
            "company": "ThoughtSpot",
            "channel": "company",
            "recipient": "Jane",
            "subject": "ThoughtSpot",
            "body": "Hi Ben",
            "mode": "dry_run",
            "note": "",
        }
    )
    pipe_b = ben.upsert_pipeline_from_lead(lead_b, send_queue_id=qid_b, search_name="AI SaaS", channel="company")
    team = ada.list_team_pipeline()
    assert len(team) >= 2
    cluster = cluster_for(pipe_a, team)
    ids = {int(r["id"]) for r in cluster}
    assert int(pipe_a["id"]) in ids
    assert int(pipe_b["id"]) in ids
    loaded = ada.get_lead_any("ts-2", owner_email="ben@frequency.cx")
    assert loaded is not None
    assert loaded["email_draft"] == "Hi from Ben"
    row = ada.get_send_queue_item_any(int(qid_b))
    assert row is not None
    assert row["lead_id"] == "ts-2"
