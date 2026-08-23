from frequency_agent.proofs import match_proofs
from frequency_agent.schemas import CompanyLead, Signal
from frequency_agent.util import domain_of


def test_fintech_lead_matches_fintech_proofs():
    lead = CompanyLead(
        lead_id="x",
        name="ExamplePay",
        industry="fintech",
        country="India",
        funding_stage="series_b",
        signal=Signal(type="funding", summary="Series B fintech raise in India", confidence="HIGH"),
    )
    matches = match_proofs(
        lead,
        {"sectors": ["fintech"], "stages": ["series_b"], "service_line": "exec_search", "geo": "India"},
        k=3,
    )
    names = {m.company.lower() for m in matches}
    assert names & {"savart", "oro", "dpdzero", "gnani.ai", "data sutram"}
    assert len(matches) <= 3


def test_www_and_bare_domain_dedup():
    assert domain_of("https://www.example.com/news") == domain_of("http://example.com")
