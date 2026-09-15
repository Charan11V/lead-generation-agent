from frequency_agent.outreach_queue import (
    apply_target_edits,
    can_enqueue_company,
    company_queue_payload,
    parse_queue_bundle,
    selected_messages,
)
from frequency_agent.send_queue import can_enqueue, queue_payload


def _approved() -> dict:
    return {
        "lead_id": "abc",
        "name": "ExamplePay",
        "domain": "examplepay.com",
        "review_status": "approved",
        "email_draft": "ExamplePay closed a Series B. Savart and Oro are relevant. 15 minutes?",
        "linkedin_note": "Saw the Series B. Happy to compare notes.",
        "signal": {
            "usable_in_outreach": True,
            "confidence": "HIGH",
            "type": "funding",
            "summary": "Series B announced",
        },
        "contact": {"name": "Jane Founder", "role": "CEO", "is_primary": True},
        "contacts": [
            {
                "name": "Jane Founder",
                "role": "CEO",
                "is_primary": True,
                "email": "jane@examplepay.com",
                "email_draft": "ExamplePay closed a Series B. Savart and Oro are relevant. 15 minutes?",
                "linkedin_note": "Saw the Series B. Happy to compare notes.",
            }
        ],
        "verified_contacts": [
            {
                "name": "Jane Founder",
                "role": "CEO",
                "is_primary": True,
                "person_verified": True,
                "email": "jane@examplepay.com",
                "email_draft": "ExamplePay closed a Series B. Savart and Oro are relevant. 15 minutes?",
                "linkedin_note": "Saw the Series B. Happy to compare notes.",
            }
        ],
        "qa_flags": [],
        "result_section": "verified_people",
    }


def test_rejected_cannot_enqueue():
    lead = _approved()
    lead["review_status"] = "rejected"
    ok, reason = can_enqueue(lead)
    assert ok is False
    assert "Rejected" in reason


def test_blocked_or_unverified_can_enqueue_if_selected():
    lead = _approved()
    lead["review_status"] = "pending"
    lead["signal"]["usable_in_outreach"] = False
    lead["signal"]["confidence"] = "UNVERIFIED"
    lead["qa_flags"] = ["Unsourced number in email: '12'."]
    lead["email_draft"] = "[BLOCKED — DO NOT SEND] unverified"
    lead["contacts"][0]["email_draft"] = "[BLOCKED — DO NOT SEND] unverified"
    lead["verified_contacts"][0]["email_draft"] = "[BLOCKED — DO NOT SEND] unverified"
    lead["contacts"][0]["linkedin_note"] = ""
    lead["verified_contacts"][0]["linkedin_note"] = ""
    lead["linkedin_note"] = ""
    lead["contacts"][0]["queue_email"] = True
    lead["verified_contacts"][0]["queue_email"] = True
    ok, reason = can_enqueue(lead)
    assert ok is True, reason
    msgs = selected_messages(lead)
    assert len(msgs) == 1
    assert msgs[0]["body"].startswith("[BLOCKED")


def test_approved_usable_can_enqueue():
    lead = _approved()
    lead["contacts"][0]["queue_email"] = True
    lead["verified_contacts"][0]["queue_email"] = True
    ok, reason = can_enqueue(lead)
    assert ok is True
    assert reason == ""
    item = queue_payload(lead, "email")
    assert item["mode"] == "dry_run"
    assert item["would_send"] is False
    assert "ExamplePay" in item["recipient"]


def test_company_bundle_queues_selected_only():
    lead = _approved()
    lead["contacts"][0]["queue_email"] = True
    lead["contacts"][0]["queue_linkedin"] = False
    lead["verified_contacts"][0]["queue_email"] = True
    lead["verified_contacts"][0]["queue_linkedin"] = False
    msgs = selected_messages(lead)
    assert len(msgs) == 1
    assert msgs[0]["kind"] == "email"
    ok, reason = can_enqueue_company(lead)
    assert ok, reason
    payload = company_queue_payload(lead, search_name="Fintech CEOs", icp_text="Series B founders")
    assert payload["channel"] == "company"
    bundle = parse_queue_bundle(payload)
    assert bundle is not None
    assert bundle["search_name"] == "Fintech CEOs"
    assert bundle["signal_text"]
    assert bundle["contacts"]
    assert len(bundle["selected_messages"]) == 1
    assert bundle["selected_messages"][0]["kind"] == "email"
    snap = bundle["lead_snapshot"]
    assert "Series B" in (snap.get("email_draft") or snap["contacts"][0].get("email_draft") or "")
    # LinkedIn deselected — should be cleared on snapshot person
    assert not (snap["contacts"][0].get("linkedin_note") or "").strip()


def test_nothing_selected_by_default_blocks_enqueue():
    lead = _approved()
    # Fresh generated drafts — no queue_* flags yet → nothing selected
    ok, reason = can_enqueue(lead)
    assert ok is False
    assert "Select at least one" in reason


def test_enrich_fills_search_signal_contacts():
    from frequency_agent.outreach_queue import enrich_queue_bundle

    lead = _approved()
    bundle = enrich_queue_bundle(
        {"kind": "legacy", "search_name": "", "signal_text": "", "contacts": []},
        lead=lead,
        pipeline_item={"search_name": "", "icp_text": "Series B fintech founders in India"},
    )
    assert bundle["search_name"]
    assert "Series B" in bundle["signal_text"] or "funding" in bundle["signal_text"].lower()
    assert any(c.get("name") == "Jane Founder" for c in bundle["contacts"])
