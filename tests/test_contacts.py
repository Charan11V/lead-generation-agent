from __future__ import annotations

from unittest.mock import MagicMock, patch

from frequency_agent.contacts import (
    _candidate_from_raw,
    contact_search_queries,
    discover_contacts_for_lead,
    rank_contacts,
    suggested_roles,
)
from frequency_agent.schemas import ContactCandidate, EnrichmentExtract, ICP, SearchHit, Signal


def test_hiring_signal_prefers_talent_leader_over_random_exec():
    chro = _candidate_from_raw(
        name="Priya Nair",
        role="Head of Talent",
        why="Owns hiring",
        source_url="https://example.com/a",
        quote="Priya Nair was appointed Head of Talent at Acme",
        corpus="Priya Nair was appointed Head of Talent at Acme to scale the team.",
        inferred=False,
        service_line="exec_search",
        signal_type="hiring_surge",
        signal_summary="Acme is hiring VP Engineering roles across Bengaluru",
        company="Acme",
        domain="acme.com",
    )
    ceo = _candidate_from_raw(
        name="Raj Shah",
        role="CEO",
        why="Founder",
        source_url="https://example.com/b",
        quote="Raj Shah founded Acme",
        corpus="Raj Shah founded Acme in 2019.",
        inferred=False,
        service_line="exec_search",
        signal_type="hiring_surge",
        signal_summary="Acme is hiring VP Engineering roles across Bengaluru",
        company="Acme",
        domain="acme.com",
    )
    assert chro is not None and ceo is not None
    ranked = rank_contacts([ceo, chro], service_line="exec_search", signal_type="hiring_surge")
    assert ranked[0].name == "Priya Nair"
    assert ranked[0].is_primary is True


def test_rank_contacts_marks_primary_and_orders_by_score():
    a = ContactCandidate(
        name="Alice",
        role="CEO",
        why="a",
        relevance_score=50,
        usable_in_outreach=True,
        confidence="HIGH",
    )
    b = ContactCandidate(
        name="Bob",
        role="CHRO",
        why="b",
        relevance_score=80,
        usable_in_outreach=True,
        confidence="HIGH",
    )
    ranked = rank_contacts([a, b], service_line="exec_search", signal_type="hiring_surge")
    assert ranked[0].name == "Bob"
    assert ranked[0].rank == 1
    assert ranked[1].rank == 2


def test_contact_search_queries_include_hiring_and_leadership():
    qs = contact_search_queries(
        "AcmePay",
        service_line="exec_search",
        signal_type="hiring_surge",
        domain="acmepay.com",
    )
    blob = " ".join(qs).lower()
    assert "acmepay" in blob
    assert "head of talent" in blob or "chro" in blob
    assert "site:acmepay.com" in blob


def test_suggested_roles_for_capital_advisory_funding():
    roles = suggested_roles("capital_advisory", "funding")
    assert "cfo" in roles


def test_discover_contacts_empty_extra_extract_falls_back_without_crash():
    """Retail-style ICPs often find companies but no named execs; extra search then extracts nothing."""
    search = MagicMock()
    search.search.return_value = []
    icp = ICP(
        raw_text="Retail/luxury chains across India with 50+ store locations",
        service_line="exec_search",
        geo="India",
        sectors=["retail", "luxury"],
    )
    signal = Signal(type="expansion", summary="ShopCo opened 20 new stores in India.")
    hits = [
        SearchHit(
            query="retail India expansion",
            url="https://example.com/shopco",
            title="ShopCo expands",
            snippet="ShopCo opened 20 stores.",
            raw_content="ShopCo opened 20 stores across India this year.",
        )
    ]
    with patch("frequency_agent.contacts.extract_contacts_from_corpus", return_value=[]):
        contact, ranked, _corpus, verified = discover_contacts_for_lead(
            llm=MagicMock(),
            search=search,
            memory=None,
            company="ShopCo",
            domain="shopco.com",
            icp=icp,
            signal=signal,
            enrich_data=EnrichmentExtract(),
            corpus="ShopCo opened 20 stores across India this year.",
            hits=hits,
        )
    assert contact.name == "not_found"
    assert ranked
    assert ranked[0].is_primary is True
    assert verified == []
