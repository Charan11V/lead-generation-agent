from __future__ import annotations

from frequency_agent.schemas import CompanyLead, Contact, Signal, Source
from frequency_agent.scoring import score_lead
from frequency_agent.util import domain_of, normalize_name, slug_id


def _lead(**kwargs) -> CompanyLead:
    defaults = dict(
        lead_id="abc",
        name="Razorpay",
        website="https://razorpay.com",
        domain="razorpay.com",
        industry="fintech",
        country="India",
        city="Bengaluru",
        funding_stage="series_f",
        signal=Signal(
            type="funding",
            summary="Raised a Series something in India",
            date="2026-08-01",
            recency_days=21,
            confidence="HIGH",
            usable_in_outreach=True,
            evidence_quote="The company announced a funding round",
            sources=[Source(url="https://economictimes.indiatimes.com/x", title="ET")],
        ),
        contact=Contact(
            name="Harshil Mathur",
            role="CEO",
            why="Founder/CEO for a funding signal",
            source_url="https://razorpay.com/about",
            confidence="HIGH",
            usable_in_outreach=True,
        ),
    )
    defaults.update(kwargs)
    return CompanyLead(**defaults)


def test_high_quality_lead_scores_in_the_nineties():
    icp = {
        "sectors": ["fintech"],
        "geo": "India",
        "cities": ["Bengaluru"],
        "stages": ["series_b"],
        "recency_days": 90,
        "raw_text": "Series B+ fintech India",
        "service_line": "exec_search",
    }
    scored = score_lead(_lead(), icp)
    assert scored.total >= 85
    assert scored.icp_fit <= 40
    assert "why" in scored.model_dump()
    assert scored.reasons


def test_unverified_signal_cannot_max_signal_points():
    icp = {"sectors": ["fintech"], "geo": "India", "recency_days": 90, "stages": ["series_b"]}
    lead = _lead(
        signal=Signal(type="other", summary="", confidence="UNVERIFIED", usable_in_outreach=False)
    )
    scored = score_lead(lead, icp)
    assert scored.signal_strength < 20
    assert scored.total < 85


def test_domain_and_name_normalization():
    assert domain_of("https://www.Razorpay.com/about") == "razorpay.com"
    assert normalize_name("Acme Technologies Pvt Ltd") == "acme"
    assert slug_id("razorpay.com", "Razorpay") == slug_id("razorpay.com", "razorpay")
