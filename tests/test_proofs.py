from frequency_agent.proofs import match_proofs
from frequency_agent.schemas import CompanyLead, Signal
from frequency_agent.util import domain_of


FINTECH_ICP = {
    "sectors": ["fintech", "AI"],
    "stages": ["series_a"],
    "service_line": "exec_search",
    "geo": "India",
    "raw_text": "Series A fintech AI companies in India needing leadership",
}


def test_fintech_lead_matches_fintech_proofs():
    lead = CompanyLead(
        lead_id="x",
        name="ExamplePay",
        industry="fintech",
        country="India",
        funding_stage="series_b",
        signal=Signal(type="funding", summary="Series B fintech raise in India", confidence="HIGH"),
    )
    matches = match_proofs(lead, FINTECH_ICP, k=3)
    names = {m.company.lower() for m in matches}
    assert names & {"savart", "oro", "dpdzero", "gnani.ai", "data sutram"}
    assert len(matches) <= 3
    assert any(m.match_tier == "direct" for m in matches)


def test_same_icp_does_not_clone_fintech_proofs_across_unrelated_companies():
    """Filtrous / ThoughtSpot / Unispore must not all get identical 'direct' fintech proofs."""
    filtrous = CompanyLead(
        lead_id="f",
        name="Filtrous",
        industry="biotechnology lab supplies",
        country="United States",
        city="San Diego",
        signal=Signal(
            type="expansion",
            summary="Lab consumables supplier expanding clinical diagnostics catalog",
            confidence="MEDIUM",
        ),
    )
    thoughtspot = CompanyLead(
        lead_id="t",
        name="ThoughtSpot",
        industry="AI analytics SaaS",
        country="United States",
        funding_stage="growth",
        signal=Signal(
            type="product_launch",
            summary="Enterprise AI analytics and business intelligence platform",
            confidence="HIGH",
        ),
    )
    thoughtspot.contact.role = "VP Product Marketing"

    unispore = CompanyLead(
        lead_id="u",
        name="Unispore",
        industry="mushroom spawn manufacturing",
        country="India",
        city="Hyderabad",
        company_size="sme",
        signal=Signal(
            type="other",
            summary="Organic mushroom spawn laboratory and agri biolabs in Hyderabad",
            confidence="MEDIUM",
        ),
    )

    f_m = match_proofs(filtrous, FINTECH_ICP, k=3)
    t_m = match_proofs(thoughtspot, FINTECH_ICP, k=3)
    u_m = match_proofs(unispore, FINTECH_ICP, k=3)

    f_ids = [m.id for m in f_m]
    t_ids = [m.id for m in t_m]
    u_ids = [m.id for m in u_m]

    # Not the same ordered fintech stack for every company
    assert not (f_ids == t_ids == u_ids == ["savart", "data_sutram", "dpdzero"])

    # Fintech-only proofs must not be claimed as direct for lab / agri companies
    for m in f_m:
        if m.id in {"savart", "dpdzero", "oro"}:
            assert m.match_tier == "related"
            assert m.usage_hint
            assert "not a direct match" in m.usage_hint.lower()
    for m in u_m:
        if m.id in {"savart", "dpdzero", "oro", "data_sutram"}:
            assert m.match_tier == "related"
            assert m.usage_hint

    # ThoughtSpot should prefer AI/analytics-ish proofs as direct when possible
    t_direct = {m.id for m in t_m if m.match_tier == "direct"}
    assert "savart" not in t_direct  # fintech wealth ≠ analytics SaaS
    # At least one non-fintech-or-related framing present
    assert any(m.match_tier == "direct" for m in t_m) or any(
        m.id in {"hosted_ai", "elucidata", "data_sutram", "sima_ai", "gnani_ai"} for m in t_m
    )


def test_related_proofs_carry_suggestion_copy():
    lead = CompanyLead(
        lead_id="lab",
        name="Filtrous",
        industry="laboratory consumables",
        country="United States",
        signal=Signal(type="other", summary="Clinical lab supply distributor", confidence="LOW"),
    )
    matches = match_proofs(lead, FINTECH_ICP, k=3)
    assert matches
    related = [m for m in matches if m.match_tier == "related"]
    assert related
    assert all(m.usage_hint for m in related)
    assert all(m.why_matched.lower().startswith("related suggestion") for m in related)


def test_www_and_bare_domain_dedup():
    assert domain_of("https://www.example.com/news") == domain_of("http://example.com")
