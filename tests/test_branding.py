from frequency_agent.branding import brand_domain, brand_name, brand_url, brand_wordmark
from frequency_agent.mailer import send_otp_email
from frequency_agent.ui import splash_html, topbar_html


def test_default_brand_is_frequency(monkeypatch):
    monkeypatch.delenv("APP_BRAND", raising=False)
    monkeypatch.delenv("APP_BRAND_DOMAIN", raising=False)
    monkeypatch.delenv("APP_BRAND_URL", raising=False)
    assert brand_name() == "Frequency"
    assert brand_wordmark() == "FREQUENCY"
    assert brand_domain() == "frequency.cx"
    assert brand_url() == "https://frequency.cx"
    assert "FREQUENCY" in splash_html()
    assert "FREQUENCY" in topbar_html()


def test_tovyq_brand(monkeypatch):
    monkeypatch.setenv("APP_BRAND", "Tovyq")
    monkeypatch.setenv("APP_BRAND_DOMAIN", "tovyq.swameda.com")
    monkeypatch.setenv("APP_BRAND_URL", "https://tovyq.swameda.com")
    assert brand_name() == "Tovyq"
    assert brand_wordmark() == "TOVYQ"
    assert brand_url() == "https://tovyq.swameda.com"
    from frequency_agent.branding import rewrite_frequency

    assert "Tovyq" in rewrite_frequency("Frequency has placed leaders")
    assert "FREQUENCY" not in rewrite_frequency("FREQUENCY")
    assert "TOVYQ" in splash_html()
    assert "FREQUENCY" not in splash_html()
    assert "TOVYQ" in topbar_html()


def test_tovyq_otp_subject(monkeypatch):
    monkeypatch.setenv("APP_BRAND", "Tovyq")
    monkeypatch.setenv("AUTH_DEV_MODE", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESET_EMAIL_FROM", "Tovyq <otp@auth.frequency.cx>")
    captured: dict = {}

    class FakeEmails:
        @staticmethod
        def send(params):
            captured["params"] = params
            return {"id": "email_test"}

    import types
    import sys

    monkeypatch.setitem(sys.modules, "resend", types.SimpleNamespace(api_key=None, Emails=FakeEmails))
    ok, _msg = send_otp_email(to_email="user@example.com", otp="123456", purpose="register")
    assert ok
    assert captured["params"]["subject"] == "Verify your Tovyq email"
    assert "Welcome to Tovyq" in captured["params"]["text"]
