"""End-to-end auth flow checks (Clerk service mocked — no live network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from frequency_agent.auth import AuthStore
from frequency_agent.auth_service import ClerkAuthService
from frequency_agent.clerk_client import ClerkUser


class FakeClerk:
    def __init__(self) -> None:
        self.users: dict[str, ClerkUser] = {}
        self.passwords: dict[str, str] = {}
        self.marked_verified: list[str] = []

    def find_by_email(self, email: str) -> ClerkUser | None:
        return self.users.get(email.strip().lower())

    def create_user(self, email: str, password: str) -> ClerkUser:
        email = email.strip().lower()
        user = ClerkUser(
            user_id=f"user_{email}",
            email=email,
            email_verified=False,
            email_address_id=f"idn_{email}",
        )
        self.users[email] = user
        self.passwords[user.user_id] = password
        return user

    def verify_password(self, user_id: str, password: str) -> bool:
        return self.passwords.get(user_id) == password

    def mark_email_verified(self, email_address_id: str) -> None:
        self.marked_verified.append(email_address_id)
        for user in self.users.values():
            if user.email_address_id == email_address_id:
                user.email_verified = True

    def set_password(self, user_id: str, password: str) -> None:
        self.passwords[user_id] = password


@pytest.fixture()
def clerk_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ClerkAuthService, FakeClerk]:
    from frequency_agent import auth as auth_mod

    monkeypatch.setenv("AUTH_DEV_MODE", "1")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setattr(auth_mod, "OTP_RESEND_SECONDS", 0)
    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "123456")
    client = FakeClerk()
    store = AuthStore(tmp_path / "otp.db")
    return ClerkAuthService(client=client, otp_store=store), client


def test_flow_register_verify_login(clerk_auth, monkeypatch: pytest.MonkeyPatch):
    auth, client = clerk_auth
    from frequency_agent import auth as auth_mod

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "123456")

    ok, msg, pending = auth.register("a@frequency.cx", "password1234567", "password1234567")
    assert ok and pending
    assert pending["email_verified"] is False
    assert pending["email"] == "a@frequency.cx"

    ok, msg, user = auth.verify_registration(
        "a@frequency.cx",
        "123456",
        email_address_id=pending["email_address_id"],
    )
    assert ok and user
    assert user["email_verified"] is True
    assert client.marked_verified == ["idn_a@frequency.cx"]

    ok, msg, logged = auth.login("a@frequency.cx", "password1234567")
    assert ok and logged["email"] == "a@frequency.cx"


def test_flow_unverified_login_returns_pending(clerk_auth, monkeypatch: pytest.MonkeyPatch):
    auth, _client = clerk_auth
    from frequency_agent import auth as auth_mod

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "111111")
    auth.register("b@frequency.cx", "password1234567", "password1234567")

    ok, msg, pending = auth.login("b@frequency.cx", "password1234567")
    assert not ok
    assert pending is not None
    assert pending["email_verified"] is False
    assert "not verified" in msg.lower()


def test_flow_password_reset(clerk_auth, monkeypatch: pytest.MonkeyPatch):
    auth, client = clerk_auth
    from frequency_agent import auth as auth_mod

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "222222")
    auth.register("c@frequency.cx", "password1234567", "password1234567")
    auth.verify_registration("c@frequency.cx", "222222", email_address_id="idn_c@frequency.cx")

    monkeypatch.setattr(auth_mod, "generate_otp", lambda: "333333")
    ok, msg, pending = auth.request_password_reset("c@frequency.cx")
    assert ok and pending

    ok, msg = auth.reset_password(
        "c@frequency.cx",
        "333333",
        "newpassword12345",
        "newpassword12345",
        user_id=pending["user_id"],
    )
    assert ok
    assert client.passwords["user_c@frequency.cx"] == "newpassword12345"

    ok, _, logged = auth.login("c@frequency.cx", "newpassword12345")
    assert ok and logged
