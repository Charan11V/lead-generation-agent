from __future__ import annotations

from frequency_agent.contact_policy import (
    is_excluded_contact,
    validate_outreach_contact,
)


def test_excludes_press_and_investors():
    ok, _ = is_excluded_contact("Jane Doe", "Spokesperson", "Acme", "")
    assert ok
    ok, _ = is_excluded_contact("VC Partner", "Partner at Sequoia", "Acme", "")
    assert ok
    ok, _ = is_excluded_contact("Reporter", "Journalist", "Acme", "published by")
    assert ok


def test_accepts_decision_maker_at_company():
    corpus = "Priya Nair was appointed Head of Talent at Acme to lead hiring."
    ok, reason = validate_outreach_contact(
        "Priya Nair",
        "Head of Talent",
        "Acme",
        corpus,
        domain="acme.com",
        quote=corpus,
    )
    assert ok, reason
    ok, reason = validate_outreach_contact(
        "Random Investor",
        "Board Member at BigVC",
        "Acme",
        "Random Investor said Acme is growing",
    )
    assert not ok
