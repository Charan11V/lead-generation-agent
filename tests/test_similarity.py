"""Canonical entity IDs and pipeline status helpers."""

from frequency_agent.similarity import (
    company_entity_id,
    identity_from_lead,
    person_entity_id,
)


def _lead(**kwargs) -> dict:
    base = {
        "lead_id": "lead_1",
        "name": "Acme Pay",
        "domain": "acmepay.com",
        "contact": {
            "name": "Jane Founder",
            "role": "CEO",
            "email": "jane@acmepay.com",
            "linkedin_url": "https://www.linkedin.com/in/jane-founder",
        },
        "contacts": [],
    }
    base.update(kwargs)
    return base


def test_company_entity_id_prefers_domain():
    a = company_entity_id("www.acmepay.com", "Acme Pay Pvt Ltd")
    b = company_entity_id("acmepay.com", "Totally Different Label")
    assert a == b
    assert a.startswith("c_")


def test_company_entity_id_falls_back_to_normalized_name():
    a = company_entity_id("unknown", "Acme Pay Pvt Ltd")
    b = company_entity_id("", "Acme Pay Limited")
    assert a == b


def test_person_entity_id_prefers_email():
    cid = company_entity_id("acmepay.com", "Acme Pay")
    a = person_entity_id(email="Jane@AcmePay.com", name="Other", company_id=cid)
    b = person_entity_id(email="jane@acmepay.com", linkedin="https://linkedin.com/in/x", name="Jane")
    assert a == b
    assert a.startswith("p_")


def test_identity_from_lead_extracts_entity_ids():
    ident = identity_from_lead(_lead())
    assert ident["company_entity_id"] == company_entity_id("acmepay.com", "Acme Pay")
    assert ident["person_entity_id"] == person_entity_id(email="jane@acmepay.com")
    assert ident["domain"] == "acmepay.com"
    assert ident["person_email"] == "jane@acmepay.com"


def test_same_domain_yields_same_company_entity_id():
    left = identity_from_lead(_lead())
    right = identity_from_lead(
        _lead(
            lead_id="lead_other",
            name="Acme Payments",
            contact={"name": "Priya Sharma", "role": "CHRO", "email": "priya@acmepay.com"},
        )
    )
    assert left["company_entity_id"] == right["company_entity_id"]


def test_status_sequence_is_linear_then_close():
    from frequency_agent.similarity import can_transition, next_pipeline_actions, normalize_pipeline_status

    assert next_pipeline_actions("queued") == [("outreach_sent", "Outreach sent")]
    assert next_pipeline_actions("outreach_sent") == [("ongoing", "Response received")]
    assert {code for code, _ in next_pipeline_actions("ongoing")} == {"success", "failure"}
    assert next_pipeline_actions("success") == []
    assert normalize_pipeline_status("response_received") == "ongoing"
    assert can_transition("queued", "outreach_sent")
    assert not can_transition("queued", "success")
    assert can_transition("outreach_sent", "ongoing")
    assert not can_transition("outreach_sent", "success")
