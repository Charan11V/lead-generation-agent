from frequency_agent.plugin_export import contact_rows, enrich_rows


def _lead(*, email="", phone="", linkedin="", twitter="", name="Ada"):
    return {
        "lead_id": "L1",
        "name": "Acme",
        "domain": "acme.com",
        "website": "https://acme.com",
        "contact": {
            "name": name,
            "role": "CEO",
            "email": email,
            "phone": phone,
            "linkedin_url": linkedin,
            "twitter_url": twitter,
        },
        "contacts": [],
        "score": {"total": 70},
        "signal": {"summary": "x"},
    }


def test_enrich_rows_needs_social_without_email_or_phone():
    leads = [
        _lead(linkedin="https://linkedin.com/in/ada"),
        _lead(email="ada@acme.com", linkedin="https://linkedin.com/in/ada"),
        _lead(phone="+1 555", twitter="https://x.com/ada"),
        _lead(),  # no social
    ]
    rows = enrich_rows(leads)
    assert len(rows) == 1
    assert rows[0]["Full Name"] == "Ada"
    assert "linkedin.com" in (rows[0].get("LinkedIn URL") or "")


def test_contact_rows_email_or_phone():
    leads = [
        _lead(email="a@acme.com"),
        _lead(phone="+1 555"),
        _lead(linkedin="https://linkedin.com/in/x"),
    ]
    rows = contact_rows(leads)
    assert len(rows) == 2
