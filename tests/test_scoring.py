from __future__ import annotations

from frequency_agent.schemas import CompanyLead, Contact, ContactCandidate, Signal, Source
from frequency_agent.scoring import WEAK_SIGNAL_TOTAL_CAP, meets_criteria, score_lead
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
            email="harshil@razorpay.com",
        ),
        verified_contacts=[
            ContactCandidate(
                name="Harshil Mathur",
                role="CEO",
                why="Founder/CEO",
                source_url="https://razorpay.com/about",
                confidence="HIGH",
                usable_in_outreach=True,
                email="harshil@razorpay.com",
                person_verified=True,
                playbook_role_match=True,
                is_primary=True,
                rank=1,
            )
        ],
    )
    defaults.update(kwargs)
    return CompanyLead(**defaults)


def test_high_quality_lead_scores_high():
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
    assert scored.total >= 70
    assert scored.icp_fit <= 30
    assert scored.approach_quality <= 20
    assert scored.evidence_depth <= 10
    assert scored.contact_relevance == scored.approach_quality
    assert "why" in scored.model_dump()
    assert scored.reasons


def test_unverified_signal_is_capped():
    icp = {"sectors": ["fintech"], "geo": "India", "recency_days": 90, "stages": ["series_b"]}
    lead = _lead(
        signal=Signal(
            type="funding",
            summary="Raised Series B in India fintech Bengaluru",
            date="2026-08-01",
            recency_days=21,
            confidence="UNVERIFIED",
            usable_in_outreach=False,
            evidence_quote="The company announced a funding round",
            sources=[Source(url="https://economictimes.indiatimes.com/x", title="ET")],
        ),
        verified_contacts=[],
    )
    scored = score_lead(lead, icp)
    assert scored.signal_strength < 20
    assert scored.total <= WEAK_SIGNAL_TOTAL_CAP
    assert scored.capped_for_weak_signal or scored.total <= WEAK_SIGNAL_TOTAL_CAP


def test_meets_criteria_usable_or_icp_fit():
    icp = {"sectors": ["fintech"], "geo": "India", "recency_days": 90, "stages": ["series_b"]}
    good = _lead()
    good.score = score_lead(good, icp)
    assert meets_criteria(good)

    weak = _lead(
        signal=Signal(type="other", summary="", confidence="UNVERIFIED", usable_in_outreach=False),
        industry="unknown",
        country="USA",
        city="unknown",
        verified_contacts=[],
        contact=Contact(name="not_found"),
    )
    weak.score = score_lead(weak, icp)
    # Low ICP fit and unusable signal → may fail criteria
    if weak.score.icp_fit < 12 and not weak.signal.usable_in_outreach:
        assert not meets_criteria(weak)


def test_domain_and_name_normalization():
    assert domain_of("https://www.Razorpay.com/about") == "razorpay.com"
    assert normalize_name("Acme Technologies Pvt Ltd") == "acme"
    assert slug_id("razorpay.com", "Razorpay") == slug_id("razorpay.com", "razorpay")
