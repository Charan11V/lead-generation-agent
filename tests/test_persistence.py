from __future__ import annotations

import tempfile
from pathlib import Path

from frequency_agent.memory import Memory, icp_fingerprint, normalize_icp_text
from frequency_agent.search_export import search_contact_rows, search_csv_text, write_search_csv


def test_icp_fingerprint_stable_and_case_insensitive():
    a = icp_fingerprint("exec_search", "Series B fintech in India")
    b = icp_fingerprint("exec_search", "  series b   fintech in india ")
    c = icp_fingerprint("capital_advisory", "Series B fintech in India")
    assert a == b
    assert a != c
    assert normalize_icp_text("  Foo   Bar ") == "foo bar"


def test_per_query_dedup_not_global():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        q1 = mem.create_query_session("fintech India", "exec_search")
        q2 = mem.create_query_session("saas India", "exec_search")
        lead = {
            "lead_id": "lead1",
            "name": "AcmePay",
            "domain": "acmepay.com",
            "contact": {"name": "Jane"},
            "score": {"total": 80},
            "signal": {"summary": "raised"},
            "signal_hash": "abc",
            "review_status": "pending",
            "outreach_status": "not_sent",
        }
        mem.upsert_lead(lead)
        mem.link_lead_to_query(q1, "lead1", "run1", "query A")
        seen_q1 = mem.seen_for_query(q1)
        seen_q2 = mem.seen_for_query(q2)
        assert "acmepay.com" in seen_q1["domains"]
        assert "acmepay.com" not in seen_q2["domains"]
        mem.link_lead_to_query(q2, "lead1", "run2", "query B")
        assert len(mem.leads_for_query(q1)) == 1
        assert len(mem.leads_for_query(q2)) == 1
        unified = mem.unified_results()
        assert len(unified) == 2


def test_clear_all_data():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        qid = mem.create_query_session("test", "exec_search")
        mem.upsert_lead({"lead_id": "x", "name": "Co", "domain": "co.com", "contact": {}, "score": {}, "signal": {}})
        mem.link_lead_to_query(qid, "x", "r1")
        mem.clear_all_data()
        assert mem.list_query_sessions() == []
        assert mem.load_all_payloads() == []


def test_same_icp_seen_excludes_prior_companies():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        fp = icp_fingerprint("exec_search", "fintech India Series B")
        lead = {
            "lead_id": "lead1",
            "name": "AcmePay",
            "domain": "acmepay.com",
            "contact": {"name": "Jane"},
            "score": {"total": 80},
            "signal": {"summary": "raised"},
            "signal_hash": "abc",
            "review_status": "pending",
            "outreach_status": "not_sent",
        }
        mem.upsert_lead(lead, icp_hash=fp)
        mem.save_run(
            "run1",
            "fintech India Series B",
            "exec_search",
            {"queued": 1},
            lead_ids=["lead1"],
            new_lead_ids=["lead1"],
        )
        seen = mem.seen_for_icp(fp)
        assert "acmepay.com" in seen["domains"]
        assert mem.is_seen_for_icp(fp, "acmepay.com", "AcmePay")
        assert not mem.is_seen_for_icp(fp, "other.com", "OtherCo")


def test_load_run_restores_leads():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mem = Memory(Path(tmp) / "t.db")
        fp = icp_fingerprint("exec_search", "gcc hiring")
        lead = {
            "lead_id": "lead2",
            "name": "Workday",
            "domain": "workday.com",
            "contact": {"name": "not_found", "email": "", "linkedin_url": ""},
            "contacts": [
                {
                    "name": "Alex CEO",
                    "role": "CEO",
                    "email": "alex@workday.com",
                    "linkedin_url": "https://linkedin.com/in/alex",
                    "is_primary": True,
                    "rank": 1,
                }
            ],
            "score": {"total": 70, "why": "ok"},
            "signal": {"summary": "GCC", "type": "expansion", "confidence": "HIGH", "sources": []},
            "signal_hash": "xyz",
            "review_status": "pending",
            "outreach_status": "not_sent",
        }
        mem.upsert_lead(lead, icp_hash=fp)
        mem.save_run(
            "run2",
            "gcc hiring",
            "exec_search",
            {"queued": 1},
            queries=["q1"],
            logs=["did stuff"],
            lead_ids=["lead2"],
            new_lead_ids=["lead2"],
            csv_path="output/searches/run2.csv",
        )
        loaded = mem.load_run("run2")
        assert loaded is not None
        assert len(loaded["leads"]) == 1
        assert loaded["leads"][0]["name"] == "Workday"
        assert loaded["queries"] == ["q1"]
        latest = mem.latest_run()
        assert latest and latest["run_id"] == "run2"
        assert len(mem.leads_for_run("run2")) == 1
        assert mem.leads_for_run("run2")[0]["name"] == "Workday"


def test_search_csv_includes_channels():
    leads = [
        {
            "lead_id": "L1",
            "name": "AcmePay",
            "owner_email": "ops@example.com",
            "website": "https://acmepay.com",
            "domain": "acmepay.com",
            "industry": "fintech",
            "city": "Bengaluru",
            "country": "India",
            "funding_stage": "series_b",
            "funding_amount": "$20M",
            "funding_date": "2026-01-01",
            "query_id": "q1",
            "service_line_fit": "exec_search",
            "discovery_web_query": '"AcmePay" funding India',
            "why_interested": "Recent raise implies leadership build",
            "signal": {
                "type": "funding",
                "summary": "Raised Series B",
                "date": "2026-01-01",
                "confidence": "HIGH",
                "evidence_quote": "AcmePay raised $20M",
                "sources": [{"url": "https://news.example/a"}],
            },
            "score": {
                "total": 88,
                "why": "strong",
                "icp_fit": 22,
                "signal_strength": 24,
                "recency": 18,
                "contact_relevance": 24,
            },
            "email_draft": "Hi Jane — company draft",
            "linkedin_note": "Hi Jane on LI",
            "qa_flags": [],
            "field_uncertainty": [],
            "verified_contacts": [
                {
                    "name": "Jane Founder",
                    "role": "CEO",
                    "email": "jane@acmepay.com",
                    "phone": "+91 98765 43210",
                    "linkedin_url": "https://linkedin.com/in/jane",
                    "twitter_url": "https://x.com/jane",
                    "other_social": [],
                    "best_channel": "email:jane@acmepay.com",
                    "source_url": "https://acmepay.com/about",
                    "is_primary": True,
                    "rank": 1,
                    "person_verified": True,
                    "email_draft": "Hi Jane — person draft with proofs",
                    "linkedin_note": "Jane LI note",
                    "apollo_hint": "Open LinkedIn",
                    "usable_in_outreach": True,
                    "confidence": "HIGH",
                    "why": "Named CEO in press",
                    "relevance_score": 40,
                    "likelihood_reason": "Role fits",
                    "channels": [
                        {
                            "kind": "email",
                            "value": "jane@acmepay.com",
                            "confidence": "HIGH",
                            "source_url": "https://acmepay.com/about",
                            "priority": 100,
                        }
                    ],
                }
            ],
            "contacts": [
                {
                    "name": "Jane Founder",
                    "role": "CEO",
                    "email": "jane@acmepay.com",
                    "phone": "+91 98765 43210",
                    "linkedin_url": "https://linkedin.com/in/jane",
                    "is_primary": True,
                    "rank": 1,
                },
                {
                    "name": "Raj COO",
                    "role": "COO",
                    "email": "raj@acmepay.com",
                    "rank": 2,
                    "email_draft": "Hi Raj",
                    "linkedin_note": "Raj note",
                },
            ],
            "proofs": [{"company": "Savart", "outcome": "scaled"}],
            "review_status": "pending",
            "outreach_status": "not_sent",
        }
    ]
    rows = search_contact_rows(leads, run_id="abc", new_lead_ids={"L1"})
    assert len(rows) == 2
    jane = next(r for r in rows if r["Full Name"] == "Jane Founder")
    raj = next(r for r in rows if r["Full Name"] == "Raj COO")
    assert jane["Owner Email"] == "ops@example.com"
    assert jane["Email"] == "jane@acmepay.com"
    assert jane["Phone"] == "+91 98765 43210"
    assert "linkedin.com/in/jane" in jane["LinkedIn URL"]
    assert jane["Is New This Run"] == "yes"
    assert jane["All Channels"] == "email:jane@acmepay.com (HIGH) [https://acmepay.com/about]"
    assert jane["Why Interested"] == "Recent raise implies leadership build"
    assert jane["Discovery Web Query"] == '"AcmePay" funding India'
    assert jane["Person Email Draft"] == "Hi Jane — person draft with proofs"
    assert jane["Company Email Draft"] == "Hi Jane — company draft"
    assert jane["Person LinkedIn Note"] == "Jane LI note"
    assert raj["Person Email Draft"] == "Hi Raj"
    assert raj["Draft Email"] == "Hi Jane — company draft"
    text = search_csv_text(leads, run_id="abc", new_lead_ids={"L1"})
    assert "Owner Email" in text
    assert "Person Email Draft" in text
    assert "jane@acmepay.com" in text
    assert "Hi Jane — person draft with proofs" in text
    assert "Hi Raj" in text
    assert "LinkedIn URL" in text

    from frequency_agent.search_export import full_results_json_text
    import json

    payload = json.loads(full_results_json_text(leads, run_id="abc"))
    assert payload["company_count"] == 1
    assert payload["contact_row_count"] == 2
    assert payload["leads"][0]["email_draft"].startswith("Hi Jane")
    assert len(payload["leads"][0]["verified_contacts"]) == 1

    with tempfile.TemporaryDirectory() as tmp:
        path = write_search_csv(
            leads,
            tmp,
            run_id="abc",
            service_line="exec_search",
            icp_text="fintech",
            new_lead_ids={"L1"},
        )
        assert path.exists()
        assert "jane@acmepay.com" in path.read_text(encoding="utf-8")
