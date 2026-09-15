from __future__ import annotations

from pathlib import Path

import pytest

from frequency_agent.auth import AuthService, AuthStore
from frequency_agent.auth_crypto import (
    generate_otp,
    hash_otp,
    hash_password,
    is_valid_email,
    verify_otp,
    verify_password,
)


@pytest.fixture()
def auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AuthService:
    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr("frequency_agent.auth.OTP_RESEND_SECONDS", 0)
    store = AuthStore(tmp_path / "auth.db")
    return AuthService(store)


def test_password_roundtrip():
    digest, salt = hash_password("correct horse")
    assert verify_password("correct horse", digest, salt)
    assert not verify_password("wrong", digest, salt)


def test_otp_roundtrip():
    code = generate_otp()
    assert len(code) == 6 and code.isdigit()
    salt = "abc"
    h = hash_otp(code, salt=salt)
    assert verify_otp(code, h, salt=salt)
    assert not verify_otp("000000", h, salt=salt)


def test_email_validation():
    assert is_valid_email("a@b.co")
    assert not is_valid_email("not-an-email")


def test_register_verify_login(auth: AuthService, monkeypatch: pytest.MonkeyPatch):
    from frequency_agent import auth as auth_mod

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "424242")
    ok, msg, user = auth.register("Person@Frequency.cx", "password123", "password123")
    assert ok and user
    assert user["email"] == "person@frequency.cx"
    assert int(user["email_verified"]) == 0

    ok, msg, verified = auth.verify_registration("person@frequency.cx", "424242")
    assert ok and verified
    assert int(verified["email_verified"]) == 1

    ok, msg, logged = auth.login("person@frequency.cx", "password123")
    assert ok and logged["user_id"] == verified["user_id"]

    bad_ok, _, _ = auth.login("person@frequency.cx", "nope")
    assert not bad_ok


def test_unverified_login_blocked(auth: AuthService, monkeypatch: pytest.MonkeyPatch):
    from frequency_agent import auth as auth_mod

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "111111")
    auth.register("u@example.com", "password123", "password123")
    ok, msg, user = auth.login("u@example.com", "password123")
    assert not ok
    assert user is not None
    assert "not verified" in msg.lower()


def test_password_reset(auth: AuthService, monkeypatch: pytest.MonkeyPatch):
    from frequency_agent import auth as auth_mod

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "555555")
    auth.register("reset@example.com", "password123", "password123")
    auth.verify_registration("reset@example.com", "555555")

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "666666")
    ok, msg = auth.request_password_reset("reset@example.com")
    assert ok

    ok, msg = auth.reset_password("reset@example.com", "666666", "newpass999", "newpass999")
    assert ok

    ok, _, user = auth.login("reset@example.com", "newpass999")
    assert ok and user


def test_reset_unknown_email_does_not_leak(auth: AuthService):
    ok, msg = auth.request_password_reset("nobody@example.com")
    assert ok
    assert "if that email" in msg.lower()


def test_wrong_otp_attempts(auth: AuthService, monkeypatch: pytest.MonkeyPatch):
    from frequency_agent import auth as auth_mod

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "777777")
    auth.register("try@example.com", "password123", "password123")
    for _ in range(3):
        ok, _, _ = auth.verify_registration("try@example.com", "000000")
        assert not ok
    ok, msg, _ = auth.verify_registration("try@example.com", "777777")
    assert ok  # still within max attempts
def test_issue_otp_known_account_without_local_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Clerk reset path: account exists remotely, not in local users table."""
    from frequency_agent import auth as auth_mod

    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr(auth_mod, "OTP_RESEND_SECONDS", 0)
    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "888888")
    store = AuthStore(tmp_path / "clerk_reset.db")
    ok, msg = store.issue_otp("clerk-user@example.com", "reset", known_account=True)
    assert ok
    ok, msg = store.consume_otp("clerk-user@example.com", "reset", "888888")
    assert ok
