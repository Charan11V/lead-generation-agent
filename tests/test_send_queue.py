from frequency_agent.send_queue import can_enqueue, queue_payload


def _approved() -> dict:
    return {
        "lead_id": "abc",
        "name": "ExamplePay",
        "review_status": "approved",
        "email_draft": "ExamplePay closed a Series B. Savart and Oro are relevant. 15 minutes?",
        "linkedin_note": "Saw the Series B. Happy to compare notes.",
        "signal": {"usable_in_outreach": True, "confidence": "HIGH", "type": "funding"},
        "contact": {"name": "Jane Founder", "role": "CEO"},
        "qa_flags": [],
    }


def test_rejected_cannot_enqueue():
    lead = _approved()
    lead["review_status"] = "rejected"
    ok, reason = can_enqueue(lead)
    assert ok is False
    assert "Rejected" in reason


def test_blocked_draft_cannot_enqueue():
    lead = _approved()
    lead["email_draft"] = "[BLOCKED — DO NOT SEND] unverified"
    ok, reason = can_enqueue(lead)
    assert ok is False


def test_approved_usable_can_enqueue():
    ok, reason = can_enqueue(_approved())
    assert ok is True
    assert reason == ""
    item = queue_payload(_approved(), "email")
    assert item["mode"] == "dry_run"
    assert item["would_send"] is False
    assert "ExamplePay" in item["recipient"]
