from frequency_agent.icp import (
    brief_changed_from_session,
    normalize_service_line,
    same_icp_brief,
    service_line_label,
)


def test_normalize_service_line_from_llm_value():
    assert normalize_service_line("fractional_cxo", "") == "fractional_cxo"
    assert normalize_service_line("Executive Search", "") == "exec_search"


def test_normalize_service_line_from_icp_text():
    assert normalize_service_line(None, "Need a fractional CFO for a Series B fintech") == "fractional_cxo"
    assert (
        normalize_service_line(None, "Founder-led companies with working capital and M&A signals")
        == "capital_advisory"
    )
    assert normalize_service_line("", "Series B fintech hiring VP Engineering") == "exec_search"


def test_service_line_label():
    assert service_line_label("exec_search") == "Executive search"
    assert service_line_label("unknown_key") == "Unknown Key"


def test_same_icp_brief_ignores_case_and_space():
    assert same_icp_brief("Series B fintech India", "  series b   fintech india ")
    assert not same_icp_brief("Series B fintech India", "Series B SaaS India")


def test_brief_changed_from_session():
    locked = "Series B fintech startups in India"
    assert not brief_changed_from_session(locked, locked)
    assert not brief_changed_from_session("  series b fintech startups in india ", locked)
    assert brief_changed_from_session(locked + " last 60 days", locked)
    assert not brief_changed_from_session("anything", "")
