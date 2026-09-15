from __future__ import annotations

from frequency_agent.channels import (
    apply_channels_to_candidate,
    best_channel,
    channel_search_queries,
    classify_social,
    extract_channels_from_text,
    is_linkedin_profile,
    linkedin_matches_person,
    merge_channels,
)
from frequency_agent.plugin_export import apollo_csv_text, linkedin_url_list, plugin_rows
from frequency_agent.schemas import ContactCandidate, ContactChannel


def test_strict_linkedin_person_match():
    ctx = "Jane Founder CEO at AcmePay — Jane Founder profile"
    assert linkedin_matches_person(
        "https://www.linkedin.com/in/jane-founder",
        "Jane Founder",
        company="AcmePay",
        role="CEO",
        context=ctx,
        company_domain="acmepay.com",
    )
    assert not linkedin_matches_person(
        "https://www.linkedin.com/in/random-person",
        "Jane Founder",
        company="AcmePay",
        role="CEO",
        context=ctx,
        company_domain="acmepay.com",
    )
    assert not linkedin_matches_person(
        "https://www.linkedin.com/in/jane-founder",
        "Jane Founder",
        company="OtherCo",
        role="CEO",
        context=ctx,
        company_domain="otherco.com",
    )
    assert not is_linkedin_profile("https://www.linkedin.com/company/acmepay")
    text = """
    Jane Founder CEO AcmePay
    Wrong profile: https://www.linkedin.com/in/john-smith
    Right profile: https://www.linkedin.com/in/jane-founder
    """
    chans = extract_channels_from_text(text, company_domain="acmepay.com", person_hint="Jane Founder")
    li = [c.value for c in chans if c.kind == "linkedin"]
    assert any("jane-founder" in u for u in li)
    assert not any("john-smith" in u for u in li)


def test_malformed_urls_do_not_crash_classify():
    # Scraped markdown / IPv6-looking junk previously raised ValueError: Invalid IPv6 URL
    assert classify_social("https://example.com/path[0]") is None
    assert classify_social("http://[::1]/linkedin.com/in/jane") is None
    assert classify_social("https://www.linkedin.com/in/jane-founder") == "linkedin"
    assert classify_social("") is None
    text = 'Ok Person CEO at OkCo — see https://www.linkedin.com/in/ok-person for more'
    chans = extract_channels_from_text(text, company_domain="okco.com", person_hint="Ok Person")
    kinds = {c.kind for c in chans}
    assert "linkedin" in kinds
    # Must not raise
    extract_channels_from_text("Visit http://[bad]/ or https://x.com/user_name")


def test_priority_email_over_linkedin_over_twitter():
    text = """
    Contact Jane Founder at jane@acmepay.com or +91 98765 43210.
    LinkedIn: https://www.linkedin.com/in/jane-founder
    Twitter: https://x.com/janefounder
    """
    chans = extract_channels_from_text(text, company_domain="acmepay.com", person_hint="Jane Founder")
    kinds = [c.kind for c in merge_channels(chans)]
    assert kinds[0] == "email"
    assert "phone" in kinds
    assert "linkedin" in kinds
    assert "twitter" in kinds
    top = best_channel(chans)
    assert top is not None
    assert top.kind == "email"


def test_linkedin_profile_detection():
    assert is_linkedin_profile("https://www.linkedin.com/in/jane-founder")
    assert not is_linkedin_profile("https://www.linkedin.com/login")
    assert not is_linkedin_profile("https://www.linkedin.com/posts/someone_activity-123")
    assert classify_social("https://x.com/janefounder") == "twitter"
    assert classify_social("https://twitter.com/janefounder/status/1") is None


def test_apply_channels_boosts_relevance():
    cand = ContactCandidate(
        name="Jane Founder",
        role="CEO",
        why="founder",
        usable_in_outreach=True,
        confidence="HIGH",
        relevance_score=40,
    )
    chans = [
        ContactChannel(kind="email", value="jane@acmepay.com", priority=100, confidence="HIGH"),
        ContactChannel(kind="linkedin", value="https://linkedin.com/in/jane-founder", priority=80, confidence="HIGH"),
    ]
    out = apply_channels_to_candidate(cand, chans)
    assert out.email == "jane@acmepay.com"
    assert "linkedin.com/in/jane-founder" in out.linkedin_url
    assert out.relevance_score > 40
    assert out.best_channel.startswith("email:")


def test_channel_search_queries_include_linkedin():
    qs = channel_search_queries("Jane Founder", "AcmePay", "acmepay.com")
    blob = " ".join(qs).lower()
    assert "linkedin.com/in" in blob
    assert "jane founder" in blob


def test_channels_do_not_mix_people_on_same_page():
    text = """
    Jane Founder, CEO of AcmePay, jane@acmepay.com https://www.linkedin.com/in/jane-founder https://x.com/janefounder
    Priya Sharma, CHRO, priya.sharma@acmepay.com https://www.linkedin.com/in/priya-sharma https://x.com/priyasharma
    """
    jane = extract_channels_from_text(text, company_domain="acmepay.com", person_hint="Jane Founder")
    priya = extract_channels_from_text(text, company_domain="acmepay.com", person_hint="Priya Sharma")
    jane_vals = {c.value.lower() for c in jane}
    priya_vals = {c.value.lower() for c in priya}
    assert "jane@acmepay.com" in jane_vals
    assert "priya.sharma@acmepay.com" not in jane_vals
    assert not any("priya-sharma" in v for v in jane_vals)
    assert "priya.sharma@acmepay.com" in priya_vals
    assert "jane@acmepay.com" not in priya_vals
    assert not any("jane-founder" in v for v in priya_vals)
    assert not any("janefounder" in v for v in priya_vals)


def test_generic_inbox_not_attached_to_person():
    text = "Jane Founder CEO AcmePay — write to info@acmepay.com or careers@acmepay.com"
    chans = extract_channels_from_text(text, company_domain="acmepay.com", person_hint="Jane Founder")
    emails = [c.value for c in chans if c.kind == "email"]
    assert emails == []


def test_exclusive_channels_one_owner():
    jane = ContactCandidate(name="Jane Founder", role="CEO", relevance_score=40, usable_in_outreach=True)
    priya = ContactCandidate(name="Priya Sharma", role="CHRO", relevance_score=30, usable_in_outreach=True)
    shared = ContactChannel(kind="linkedin", value="https://linkedin.com/in/jane-founder", confidence="HIGH", priority=80)
    jane = apply_channels_to_candidate(jane, [shared, ContactChannel(kind="email", value="jane@acmepay.com", confidence="HIGH", priority=100)])
    priya = apply_channels_to_candidate(priya, [shared, ContactChannel(kind="email", value="priya.sharma@acmepay.com", confidence="HIGH", priority=100)])
    from frequency_agent.channels import assign_exclusive_channels

    out = assign_exclusive_channels([jane, priya])
    assert "jane-founder" in (out[0].linkedin_url or "")
    assert "jane-founder" not in (out[1].linkedin_url or "")
    assert out[0].email == "jane@acmepay.com"
    assert out[1].email == "priya.sharma@acmepay.com"


def test_llm_confirm_drops_mismatched_social():
    from frequency_agent.channels import confirm_channels_with_llm
    from frequency_agent.schemas import ChannelClaim, ChannelConfirmBatch

    cand = ContactCandidate(
        name="Jane Founder",
        role="CEO",
        usable_in_outreach=True,
        channels=[
            ContactChannel(kind="linkedin", value="https://linkedin.com/in/john-smith", confidence="MEDIUM", priority=80),
            ContactChannel(kind="email", value="jane@acmepay.com", confidence="HIGH", priority=100),
        ],
        email="jane@acmepay.com",
        linkedin_url="https://linkedin.com/in/john-smith",
    )

    class _Fake:
        def parse(self, messages, schema, **kwargs):
            return ChannelConfirmBatch(
                claims=[
                    ChannelClaim(person="Jane Founder", kind="linkedin", value="https://linkedin.com/in/john-smith", belongs=False),
                    ChannelClaim(person="Jane Founder", kind="email", value="jane@acmepay.com", belongs=True),
                ]
            )

    out = confirm_channels_with_llm(_Fake(), company="AcmePay", candidates=[cand], corpus="Jane Founder CEO AcmePay")
    assert out[0].email == "jane@acmepay.com"
    assert not out[0].linkedin_url

    leads = [
        {
            "lead_id": "abc",
            "name": "AcmePay",
            "domain": "acmepay.com",
            "website": "https://acmepay.com",
            "contacts": [
                {
                    "name": "Jane Founder",
                    "role": "CEO",
                    "email": "jane@acmepay.com",
                    "linkedin_url": "https://linkedin.com/in/jane-founder",
                    "is_primary": True,
                    "relevance_score": 90,
                    "apollo_hint": "Open LinkedIn",
                }
            ],
        }
    ]
    rows = plugin_rows(leads)
    assert len(rows) == 1
    assert rows[0]["Email"] == "jane@acmepay.com"
    assert "linkedin.com/in/jane-founder" in rows[0]["LinkedIn URL"]
    csv_text = apollo_csv_text(leads)
    assert "First Name" in csv_text and "Jane" in csv_text
    assert "linkedin.com/in/jane-founder" in linkedin_url_list(leads)
