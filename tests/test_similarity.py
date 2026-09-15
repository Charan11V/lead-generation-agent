"""Canonical entity IDs and cross-result similarity."""

from frequency_agent.similarity import (
    company_entity_id,
    company_name_score,
    find_similar,
    identity_from_lead,
    person_entity_id,
    similarity_verdict,
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


def test_same_domain_is_a_match_across_icps():
    left = identity_from_lead(_lead())
    right = identity_from_lead(
        _lead(
            lead_id="lead_other",
            name="Acme Payments",
            contact={"name": "Priya Sharma", "role": "CHRO", "email": "priya@acmepay.com"},
        )
    )
    verdict = similarity_verdict(left, right)
    assert verdict is not None
    assert verdict["kind"] in {"company", "company_and_person"}
    assert verdict["company_score"] >= 0.86


def test_fuzzy_company_name_without_domain():
    left = identity_from_lead(_lead(domain="unknown", name="Acme Pay Pvt Ltd"))
    right = identity_from_lead(
        _lead(
            lead_id="lead_b",
            domain="",
            name="Acme Pay",
            contact={"name": "Jane Founder", "email": "other@example.com"},
        )
    )
    assert company_name_score("Acme Pay Pvt Ltd", "Acme Pay") >= 0.86
    verdict = similarity_verdict(left, right)
    assert verdict is not None


def test_unrelated_companies_do_not_match():
    left = identity_from_lead(_lead())
    right = identity_from_lead(
        _lead(
            lead_id="lead_z",
            name="Zoho",
            domain="zoho.com",
            contact={"name": "Sridhar Vembu", "email": "sv@zoho.com"},
        )
    )
    assert similarity_verdict(left, right) is None


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


def test_same_person_email_flags_even_if_company_label_differs():
    left = identity_from_lead(_lead())
    right = identity_from_lead(
        _lead(
            lead_id="lead_x",
            name="AcmePay India",
            domain="unknown",
            contact={"name": "Jane F", "email": "jane@acmepay.com"},
        )
    )
    verdict = similarity_verdict(left, right)
    assert verdict is not None
    assert verdict["person_score"] >= 0.99


def test_find_similar_excludes_self_and_returns_reasons():
    alice = {
        "id": 1,
        "owner_email": "alice@example.com",
        "lead_id": "lead_a",
        "company": "Acme Pay",
        "domain": "acmepay.com",
        "person_name": "Jane Founder",
        "person_email": "jane@acmepay.com",
        "company_entity_id": company_entity_id("acmepay.com", "Acme Pay"),
        "person_entity_id": person_entity_id(email="jane@acmepay.com"),
        "pipeline_status": "outreach_sent",
        "icp_text": "fintech CHRO India",
    }
    bob = dict(alice)
    bob.update(
        {
            "id": 2,
            "owner_email": "bob@example.com",
            "lead_id": "lead_b",
            "pipeline_status": "queued",
            "icp_text": "CXOs after Series B",
        }
    )
    ident = identity_from_lead(_lead())
    hits = find_similar(ident, [alice, bob], exclude_pipeline_id=2)
    assert len(hits) == 1
    assert hits[0]["owner_email"] == "alice@example.com"
    assert hits[0]["match_reasons"]
