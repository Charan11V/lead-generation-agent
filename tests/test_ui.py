from frequency_agent.ui import (
    agent_stages_html,
    composer_header_html,
    detail_html,
    empty_state_html,
    hero,
    inject,
    queue_label,
    results_summary_html,
    splash_html,
    topbar_html,
)


def test_queue_label_is_scannable():
    lead = {
        "name": "AcmePay",
        "score": {"total": 88},
        "contact": {"name": "Jane Founder", "role": "CEO"},
        "signal": {"confidence": "HIGH"},
        "review_status": "pending",
    }
    label = queue_label(lead)
    assert "AcmePay" in label
    assert "Jane Founder" in label
    assert "88" in label


def test_chrome_has_frequency_text_not_fin_logo():
    assert "FREQUENCY" in splash_html()
    assert "fx-fin" not in splash_html()
    assert "FREQUENCY" in topbar_html()
    assert "Lead intelligence" in topbar_html()
    assert "fx-wordmark" in topbar_html()
    assert "fx-fin" not in hero()
    assert "Lead Intelligence" in hero()


def test_theme_helpers():
    from frequency_agent.ui import normalize_theme, theme_from_query_value

    assert normalize_theme(None) == "dark"
    assert normalize_theme("LIGHT") == "light"
    assert normalize_theme("nope") == "dark"
    assert theme_from_query_value("dark") == "dark"
    assert theme_from_query_value(["light"]) == "light"
    assert theme_from_query_value("purple") is None
    assert theme_from_query_value(None) is None


def test_light_and_dark_theme_css():
    light = inject("light")
    dark = inject("dark")
    assert "#EEF1F4" in light
    assert "#0F6E8C" in light
    assert "#05070A" in dark
    assert "#3DB8D4" in dark
    assert "--text-primary" in light and "--text-primary" in dark
    assert "baseButton-primary" in light
    # Primary must win after default button rules
    assert light.index(".stButton > button") < light.index('button[kind="primary"]') or \
           "Re-assert primary" in light or 'button[data-testid="baseButton-primary"]' in light
    # High-contrast button tokens + form-submit / download coverage
    for css in (light, dark):
        assert "--btn-primary-bg:" in css
        assert "--btn-primary-fg: #FFFFFF" in css
        assert "--btn-secondary-fg:" in css
        assert "primaryFormSubmit" in css
        assert "secondaryFormSubmit" in css
        assert ".stFormSubmitButton" in css
        assert ".stDownloadButton" in css
        assert "-webkit-text-fill-color: #FFFFFF !important" in css
        assert "-webkit-text-fill-color: var(--btn-secondary-fg) !important" in css
        # Must not paint bright sky accent as primary button fill
        assert "--btn-primary-bg: #3DB8D4" not in css
    assert "--btn-primary-bg: #0F6E8C" in light
    assert "--btn-primary-bg: #0E7A96" in dark
    assert "--btn-secondary-fg: #0E141B" in light
    assert "--btn-secondary-fg: #F3F7FB" in dark
    assert ".fx-desk-hero" in light
    assert ".fx-news-card" in dark

def test_new_shell_helpers():
    assert "Launch a brief" in composer_header_html()
    assert "Start" in empty_state_html("Start", "Body text")
    assert "Matched" in results_summary_html({"matched": 3, "with_people": 2, "channel_only": 1}, 5)
    assert "Direct" in results_summary_html({"with_people": 2}, 5)
    assert "Indirect" in results_summary_html({"channel_only": 1}, 5)
    labels = ["Understanding ICP", "Searching the web", "Scoring"]
    stages = agent_stages_html("Searching the web", labels)
    assert "fx-stage" in stages
    assert "fx-stage-track" in stages
    assert "fx-stage-sep" in stages
    assert stages.count("fx-stage-item") == 3
    assert stages.count("fx-stage-item active") == 1
    assert "fx-stage-item done" in stages
    assert "fx-stage-item upcoming" in stages
    assert stages.index("done") < stages.index("active")
    assert stages.index("active") < stages.index("upcoming")
    for lab in labels:
        assert lab in stages
    # CSS must keep the rail on one horizontal line
    css = inject("dark")
    assert "flex-wrap: nowrap" in css
    assert ".fx-stage-track" in css


def test_detail_html_sections():
    lead = {
        "name": "AcmePay",
        "website": "https://acmepay.com",
        "industry": "fintech",
        "city": "Bengaluru",
        "country": "India",
        "result_section": "verified_people",
        "score": {
            "total": 88,
            "why": "strong fit",
            "icp_fit": 20,
            "signal_strength": 22,
            "recency": 12,
            "approach_quality": 18,
            "evidence_depth": 8,
            "contact_relevance": 18,
        },
        "signal": {
            "type": "funding",
            "summary": "Raised Series B",
            "confidence": "HIGH",
            "evidence_quote": "raised $20M",
            "sources": [{"url": "https://news.example/a", "title": "News", "date": "2026-01-01"}],
        },
        "contact": {
            "name": "Jane Founder",
            "role": "CEO",
            "email": "jane@acmepay.com",
            "linkedin_url": "https://linkedin.com/in/jane",
            "is_primary": True,
            "usable_in_outreach": True,
            "confidence": "HIGH",
            "person_verified": True,
        },
        "verified_contacts": [
            {
                "name": "Jane Founder",
                "role": "CEO",
                "email": "jane@acmepay.com",
                "is_primary": True,
                "rank": 1,
                "usable_in_outreach": True,
                "confidence": "HIGH",
                "person_verified": True,
                "why": "Named CEO",
                "email_draft": "Hi Jane — tailored draft.",
                "linkedin_note": "Jane — LinkedIn tailored note.",
            }
        ],
        "contacts": [
            {
                "name": "Jane Founder",
                "role": "CEO",
                "email": "jane@acmepay.com",
                "is_primary": True,
                "rank": 1,
                "usable_in_outreach": True,
                "confidence": "HIGH",
                "person_verified": True,
                "why": "Named CEO",
                "email_draft": "Hi Jane — tailored draft.",
                "linkedin_note": "Jane — LinkedIn tailored note.",
            }
        ],
        "why_interested": "Funding implies team build.",
        "email_draft": "Hi Jane",
        "linkedin_note": "Congrats",
        "qa_flags": [],
        "field_uncertainty": [],
        "review_status": "pending",
    }
    html = detail_html(lead)
    assert "AcmePay" in html
    assert "Jane Founder" in html
    assert "Verified" in html or "verified" in html or "Direct" in html or "People" in html
    assert "Approach" in html
    assert "88" in html
    assert "Crafted email" in html or "Outreach message" in html or "jane@acmepay.com" in html
    assert "LinkedIn note" in html
    assert "LinkedIn tailored note" in html


def test_detail_html_approach_channel_section():
    lead = {
        "name": "ShopCo",
        "result_section": "approach_channels",
        "best_approach_channel": "email:contact@shopco.com",
        "approach_channels": [
            {
                "kind": "email",
                "value": "contact@shopco.com",
                "label": "Contact inbox",
                "source_url": "https://shopco.com/contact",
                "confidence": "HIGH",
            }
        ],
        "score": {
            "total": 55,
            "icp_fit": 18,
            "signal_strength": 10,
            "recency": 8,
            "approach_quality": 8,
            "evidence_depth": 4,
        },
        "signal": {"type": "expansion", "summary": "Opened stores", "confidence": "MEDIUM"},
        "contact": {"name": "not_found", "role": "Founder / CEO"},
        "contacts": [],
        "verified_contacts": [],
        "email_draft": "[BLOCKED]",
        "qa_flags": [],
        "field_uncertainty": [],
    }
    html = detail_html(lead)
    assert "ShopCo" in html
    assert "contact@shopco.com" in html
    assert "Approach channel" in html or "approaching channel" in html.lower() or "Indirect" in html


def test_pipeline_detail_html_shows_status_and_owner():
    from frequency_agent.pipeline_ui import pipeline_detail_html

    html = pipeline_detail_html(
        {
            "owner_email": "alice@example.com",
            "company": "Acme Pay",
            "person_name": "Jane Founder",
            "pipeline_status": "outreach_sent",
            "icp_text": "fintech CHRO",
            "comment": "Pinged on Monday",
        }
    )
    assert "Acme Pay" in html
    assert "alice@example.com" in html
    assert "Outreach sent" in html
    assert "Pinged on Monday" in html
