"""Password-reset OTP delivery via Resend — does not alter register/login flows."""

from __future__ import annotations

from pathlib import Path

import pytest

from frequency_agent.mailer import send_otp_email


def test_reset_otp_uses_resend_when_auth_dev_mode_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("AUTH_DEV_MODE", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESET_EMAIL_FROM", "Frequency <otp@auth.frequency.cx>")

    captured: dict = {}

    class FakeEmails:
        @staticmethod
        def send(params):
            captured["params"] = params
            return {"id": "email_test"}

    import types
    import sys

    fake_resend = types.SimpleNamespace(api_key=None, Emails=FakeEmails)
    monkeypatch.setitem(sys.modules, "resend", fake_resend)

    # Ensure production path never touches otp_dev.log
    log_path = Path(__file__).resolve().parent.parent / "output" / "otp_dev.log"
    before = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

    ok, msg = send_otp_email(to_email="user@example.com", otp="123456", purpose="reset")
    assert ok
    assert "123456" not in msg
    assert "re_test_key" not in msg
    assert captured["params"]["from"] == "Frequency <otp@auth.frequency.cx>"
    assert captured["params"]["to"] == ["user@example.com"]
    assert captured["params"]["subject"] == "Reset your Frequency password"
    assert "123456" in captured["params"]["text"]
    assert "10 minutes" in captured["params"]["text"]
    assert "ignore" in captured["params"]["text"].lower()
    assert fake_resend.api_key == "re_test_key"

    after = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert after == before


def test_reset_otp_resend_failure_hides_secrets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DEV_MODE", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_secret_should_not_leak")
    monkeypatch.setenv("RESET_EMAIL_FROM", "Frequency <otp@auth.frequency.cx>")

    class BoomEmails:
        @staticmethod
        def send(params):
            raise RuntimeError("upstream failed with re_secret_should_not_leak and otp 999999")

    import types
    import sys

    monkeypatch.setitem(
        sys.modules,
        "resend",
        types.SimpleNamespace(api_key=None, Emails=BoomEmails),
    )

    ok, msg = send_otp_email(to_email="user@example.com", otp="654321", purpose="reset")
    assert not ok
    assert "654321" not in msg
    assert "re_secret" not in msg
    assert "could not send" in msg.lower()


def test_register_otp_uses_resend_when_auth_dev_mode_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DEV_MODE", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESET_EMAIL_FROM", "Frequency <otp@auth.frequency.cx>")

    captured: dict = {}

    class FakeEmails:
        @staticmethod
        def send(params):
            captured["params"] = params
            return {"id": "email_test"}

    import types
    import sys

    fake_resend = types.SimpleNamespace(api_key=None, Emails=FakeEmails)
    monkeypatch.setitem(sys.modules, "resend", fake_resend)

    ok, msg = send_otp_email(to_email="user@example.com", otp="123456", purpose="register")
    assert ok
    assert "123456" not in msg
    assert captured["params"]["subject"] == "Verify your Frequency email"
    assert "123456" in captured["params"]["text"]


def test_reset_otp_dev_mode_still_writes_log(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    called = {"n": 0}

    class FakeEmails:
        @staticmethod
        def send(params):
            called["n"] += 1
            return {"id": "nope"}

    import types
    import sys

    monkeypatch.setitem(sys.modules, "resend", types.SimpleNamespace(api_key=None, Emails=FakeEmails))

    ok, msg = send_otp_email(to_email="dev@example.com", otp="111222", purpose="reset")
    assert ok
    assert called["n"] == 0
    assert "otp_dev.log" in msg


def test_password_reset_flow_still_verifies_otp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Existing AuthStore reset verify path unchanged; only delivery is swapped."""
    from frequency_agent import auth as auth_mod
    from frequency_agent.auth import AuthService, AuthStore

    monkeypatch.setenv("AUTH_DEV_MODE", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("RESET_EMAIL_FROM", "Frequency <otp@auth.frequency.cx>")
    monkeypatch.setattr(auth_mod, "OTP_RESEND_SECONDS", 0)
    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "424242")

    captured: dict = {}

    class FakeEmails:
        @staticmethod
        def send(params):
            captured["params"] = params
            return {"id": "email_test"}

    import types
    import sys

    monkeypatch.setitem(sys.modules, "resend", types.SimpleNamespace(api_key=None, Emails=FakeEmails))

    auth = AuthService(AuthStore(tmp_path / "auth.db"))
    # Local register still uses SMTP/dev for register purpose — force register via store + verify
    monkeypatch.setenv("AUTH_DEV_MODE", "1")  # register OTP via log
    ok, _, user = auth.register("reset-resend@example.com", "password123", "password123")
    assert ok and user
    ok, _, verified = auth.verify_registration("reset-resend@example.com", "424242")
    assert ok and verified

    monkeypatch.setenv("AUTH_DEV_MODE", "0")
    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "777888")
    ok, msg = auth.request_password_reset("reset-resend@example.com")
    assert ok
    assert captured.get("params")
    assert "777888" in captured["params"]["text"]

    ok, msg = auth.reset_password("reset-resend@example.com", "777888", "newpass999", "newpass999")
    assert ok

    ok, _, logged = auth.login("reset-resend@example.com", "newpass999")
    assert ok and logged
