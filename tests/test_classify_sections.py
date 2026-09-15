from __future__ import annotations

from frequency_agent.approach_channels import (
    best_approach_channel_str,
    discover_company_approach_channels,
)
from frequency_agent.classify import classify_result_section
from frequency_agent.contacts import is_verified_person_contact, mark_and_select_verified_people
from frequency_agent.schemas import ContactCandidate, SearchHit


def test_fresh_approach_channels_accepts_model_dump_roundtrip():
    """Hot-reload can leave duplicate ApproachChannel class identities; dump+validate fixes it."""
    from frequency_agent.schemas import ApproachChannel, CompanyLead, fresh_approach_channels

    raw = ApproachChannel(
        kind="email",
        value="contact@acmepay.com",
        label="Contact inbox",
        priority=100,
        confidence="HIGH",
    )
    fresh = fresh_approach_channels([raw, raw.model_dump()])
    assert len(fresh) == 2
    lead = CompanyLead(
        lead_id="x",
        name="AcmePay",
        approach_channels=fresh,
        best_approach_channel="email:contact@acmepay.com",
    )
    assert lead.approach_channels[0].value == "contact@acmepay.com"


def test_company_approach_channels_prefer_company_inbox():
    corpus = """
    AcmePay contact us at contact@acmepay.com or careers@acmepay.com.
    Visit https://acmepay.com/contact-us for more.
    Jane Founder personal: jane@acmepay.com
    """
    hits = [
        SearchHit(
            query="q",
            url="https://acmepay.com/careers",
            title="Careers",
            snippet="Join AcmePay",
        )
    ]
    chans = discover_company_approach_channels(
        corpus,
        company="AcmePay",
        domain="acmepay.com",
        website="https://acmepay.com",
        hits=hits,
        person_emails={"jane@acmepay.com"},
    )
    values = {c.value for c in chans}
    assert "contact@acmepay.com" in values or "careers@acmepay.com" in values
    assert "jane@acmepay.com" not in values
    assert best_approach_channel_str(chans)


def test_is_verified_person_requires_playbook_role():
    corpus = "Priya Nair is Head of Talent at Acme and leads hiring across India."
    cand = ContactCandidate(
        name="Priya Nair",
        role="Head of Talent",
        confidence="HIGH",
        usable_in_outreach=True,
        inferred=False,
        email="priya.nair@acme.com",
        source_url="https://acme.com/team",
    )
    ok, reason = is_verified_person_contact(
        cand,
        service_line="exec_search",
        signal_type="hiring_surge",
        company="Acme",
        domain="acme.com",
        corpus=corpus,
    )
    assert ok, reason

    reporter = ContactCandidate(
        name="Sam Writer",
        role="Journalist",
        confidence="HIGH",
        usable_in_outreach=True,
        inferred=False,
        email="sam@news.com",
    )
    ok2, _ = is_verified_person_contact(
        reporter,
        service_line="exec_search",
        signal_type="funding",
        company="Acme",
        domain="acme.com",
        corpus="Sam Writer journalist covered Acme funding.",
    )
    assert not ok2


def test_mark_and_select_keeps_top_verified_only():
    corpus = (
        "Priya Nair Head of Talent at Acme. "
        "Raj Shah is CEO at Acme. "
        "Bob Intern works at Acme as intern. "
        "Reach Priya Nair at priya.nair@acme.com. "
        "Reach Raj Shah at raj.shah@acme.com."
    )
    people = [
        ContactCandidate(
            name="Priya Nair",
            role="Head of Talent",
            confidence="HIGH",
            usable_in_outreach=True,
            email="priya.nair@acme.com",
            relevance_score=90,
        ),
        ContactCandidate(
            name="Raj Shah",
            role="CEO",
            confidence="HIGH",
            usable_in_outreach=True,
            email="raj.shah@acme.com",
            relevance_score=70,
        ),
        ContactCandidate(
            name="Bob Intern",
            role="Intern",
            confidence="MEDIUM",
            usable_in_outreach=True,
            relevance_score=20,
        ),
    ]
    display, marked = mark_and_select_verified_people(
        people,
        service_line="exec_search",
        signal_type="hiring_surge",
        company="Acme",
        domain="acme.com",
        corpus=corpus,
        max_people=3,
    )
    names = {c.name for c in display}
    assert "Bob Intern" not in names
    assert display
    assert display[0].is_primary
    assert any(c.person_verified for c in marked)


def test_classify_result_section():
    assert (
        classify_result_section(
            {
                "signal": {"confidence": "HIGH"},
                "verified_contacts": [{"name": "A", "person_verified": True}],
                "approach_channels": [],
            }
        )
        == "verified_people"
    )
    assert (
        classify_result_section(
            {
                "signal": {"confidence": "HIGH"},
                "verified_contacts": [],
                "contacts": [],
                "contact": {"name": "not_found"},
                "approach_channels": [{"kind": "email", "value": "contact@x.com"}],
                "best_approach_channel": "email:contact@x.com",
            }
        )
        == "approach_channels"
    )
    assert (
        classify_result_section(
            {
                "signal": {"confidence": "UNVERIFIED"},
                "verified_contacts": [{"name": "A", "person_verified": True}],
                "approach_channels": [{"kind": "email", "value": "info@x.com"}],
                "best_approach_channel": "email:info@x.com",
            }
        )
        == "approach_channels"
    )
    assert (
        classify_result_section(
            {
                "signal": {"confidence": "HIGH"},
                "verified_contacts": [],
                "contacts": [],
                "contact": {"name": "not_found"},
                "approach_channels": [],
            }
        )
        == "unresolved"
    )
