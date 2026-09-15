"""Regression: hot-reload / nested-model coercion and resilient enrich."""

from __future__ import annotations

from frequency_agent.schemas import (
    CompanyLead,
    Contact,
    ContactCandidate,
    Signal,
    Source,
    fresh_signal,
    to_dict,
)


def test_to_dict_and_fresh_signal_roundtrip():
    signal = Signal(
        type="funding",
        summary="Raised Series B",
        date="2024-01-15",
        sources=[Source(url="https://example.com/news", title="News")],
        confidence="HIGH",
        usable_in_outreach=True,
        evidence_quote="raised $20M",
    )
    dumped = to_dict(signal)
    assert isinstance(dumped, dict)
    assert dumped["type"] == "funding"
    refreshed = fresh_signal(signal)
    assert refreshed.type == "funding"
    assert refreshed.sources[0].url == "https://example.com/news"


def test_company_lead_accepts_signal_instance_via_model_dump():
    """Same construction path as _enrich_cluster — Signal instance must not ValidationError."""
    signal = Signal(
        type="funding",
        summary="Series B fintech raise in India",
        date="2024-06-01",
        sources=[Source(url="https://techcrunch.com/x", title="TC")],
        confidence="MEDIUM",
        evidence_quote="closed a Series B",
    )
    contact = Contact(name="Ada Lovelace", role="CEO", confidence="HIGH")
    candidates = [
        ContactCandidate(
            name="Ada Lovelace",
            role="CEO",
            rank=1,
            is_primary=True,
            relevance_score=40,
        )
    ]
    lead = CompanyLead(
        lead_id="acme-ada",
        name="AcmePay",
        website="https://acmepay.com",
        domain="acmepay.com",
        signal=to_dict(signal) or {},
        contact=to_dict(contact) or {},
        contacts=[to_dict(c) or {} for c in candidates],
        verified_contacts=[to_dict(c) or {} for c in candidates],
    )
    assert lead.signal.type == "funding"
    assert lead.signal.summary.startswith("Series B")
    assert lead.contact.name == "Ada Lovelace"
    assert lead.contacts[0].rank == 1


def test_company_lead_still_accepts_plain_signal_same_module():
    """Same-module Signal instances remain valid without dumping."""
    lead = CompanyLead(
        lead_id="x",
        name="Co",
        signal=Signal(type="expansion", summary="New city"),
    )
    assert lead.signal.type == "expansion"
