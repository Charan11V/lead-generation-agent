from __future__ import annotations

from pathlib import Path

from frequency_agent.contact_cards import (
    direct_person_card_html,
    indirect_company_card_html,
    iter_direct_people,
    iter_indirect_leads,
    section_banner_html,
)


def test_section_banners():
    assert "Direct" in section_banner_html("direct", 3)
    assert "Indirect" in section_banner_html("indirect", 2)
    assert "Results tab" in section_banner_html("direct", 1)
    assert "Results tab" in section_banner_html("indirect", 1)


def test_direct_card_lists_channels_without_duplicate_drafts():
    lead = {
        "name": "AcmePay",
        "industry": "fintech",
        "city": "Bengaluru",
        "country": "India",
        "website": "https://acmepay.com",
        "score": {"total": 82},
        "email_draft": "Hi Jane",
        "linkedin_note": "Hi Jane on LI",
    }
    person = {
        "name": "Jane Founder",
        "role": "CEO",
        "email": "jane@acmepay.com",
        "linkedin_url": "https://linkedin.com/in/jane-founder",
        "email_draft": "Hi Jane — saw the raise.\n\nWorth a chat?",
        "linkedin_note": "Jane — congrats on the raise.",
    }
    html = direct_person_card_html(lead, person)
    assert "AcmePay" in html
    assert "Jane Founder" in html
    assert "jane@acmepay.com" in html
    assert "LinkedIn" in html
    # Drafts live on Results only — not repeated here.
    assert "saw the raise" not in html
    assert "congrats on the raise" not in html
    assert "Results tab" in html
    assert '<div class="fx-hit"' in html
    assert "&lt;div" not in html
    assert '<div class="fx-mail">' not in html
    for line in html.splitlines():
        if line.strip():
            assert not line.startswith("    "), f"indented line would break markdown: {line!r}"


def test_indirect_card_lists_channels_without_duplicate_drafts():
    lead = {
        "name": "ShopCo",
        "score": {"total": 61},
        "contact": {"role": "Founder / CEO"},
        "best_approach_channel": "email:contact@shopco.com",
        "approach_channels": [
            {"kind": "email", "value": "contact@shopco.com", "label": "Contact inbox"}
        ],
        "email_draft": "Hello ShopCo team",
        "linkedin_note": "Hello ShopCo — saw the expansion.",
    }
    html = indirect_company_card_html(lead)
    assert "ShopCo" in html
    assert "contact@shopco.com" in html
    assert "Hello ShopCo team" not in html
    assert "saw the expansion" not in html
    assert "Results tab" in html
    assert '<div class="fx-hit' in html
    assert "&lt;div" not in html
    assert '<div class="fx-mail">' not in html


def test_app_direct_indirect_use_st_html():
    """Rendering path should use st.html (not markdown) for contact cards."""
    src = Path(__file__).resolve().parents[1].joinpath("app.py").read_text(encoding="utf-8")
    assert "st.html(direct_person_card_html" in src
    assert "st.html(indirect_company_card_html" in src
    assert "unsafe_allow_html=True" in src  # other HTML surfaces still use markdown safely


def test_iter_splits_direct_indirect():
    leads = [
        {
            "result_section": "verified_people",
            "score": {"total": 90},
            "verified_contacts": [{"name": "A", "role": "CEO"}],
            "name": "ACo",
        },
        {
            "result_section": "approach_channels",
            "score": {"total": 70},
            "name": "BCo",
            "approach_channels": [{"kind": "email", "value": "x@b.co"}],
        },
    ]
    assert len(iter_direct_people(leads)) == 1
    assert len(iter_indirect_leads(leads)) == 1
