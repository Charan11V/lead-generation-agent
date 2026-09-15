"""Tests for durable auth session tokens (HMAC sign / verify)."""

from __future__ import annotations

import sys
import time
import types

import pytest

from frequency_agent.session_cookie import (
    DEFAULT_TTL_SECONDS,
    issue_session_token,
    read_session_token_candidates,
    read_session_token_from_request,
    verify_session_token,
)


@pytest.fixture()
def session_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-auth-session-secret")
    monkeypatch.delenv("FREQUENCY_SECRETS_KEY", raising=False)
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)


def _user(**overrides):
    base = {
        "email": "Person@Frequency.cx",
        "user_id": "user_abc",
        "provider": "clerk",
        "email_verified": True,
    }
    base.update(overrides)
    return base


def test_issue_and_verify_roundtrip(session_secret):
    token = issue_session_token(_user(), now=1_700_000_000)
    got = verify_session_token(token, now=1_700_000_000)
    assert got is not None
    assert got["email"] == "person@frequency.cx"
    assert got["user_id"] == "user_abc"
    assert got["provider"] == "clerk"
    assert got["email_verified"] is True


def test_local_provider_roundtrip(session_secret):
    token = issue_session_token(_user(provider="local", user_id="42"), now=100)
    got = verify_session_token(token, now=100)
    assert got is not None
    assert got["provider"] == "local"
    assert got["user_id"] == "42"


def test_rejects_tampered_payload(session_secret):
    token = issue_session_token(_user(), now=1_700_000_000)
    body, sig = token.split(".", 1)
    # Flip a character in the body segment.
    tampered_body = ("A" if body[0] != "A" else "B") + body[1:]
    assert verify_session_token(f"{tampered_body}.{sig}", now=1_700_000_000) is None


def test_rejects_tampered_signature(session_secret):
    token = issue_session_token(_user(), now=1_700_000_000)
    body, sig = token.split(".", 1)
    bad_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert verify_session_token(f"{body}.{bad_sig}", now=1_700_000_000) is None


def test_rejects_expired_token(session_secret):
    now = 1_700_000_000
    token = issue_session_token(_user(), ttl_seconds=60, now=now)
    assert verify_session_token(token, now=now + 59) is not None
    assert verify_session_token(token, now=now + 61) is None


def test_rejects_unverified_email_in_token(session_secret, monkeypatch):
    # Force-issue a token with email_verified=False by patching issue path:
    # issue_session_token copies the flag; verify must reject it.
    token = issue_session_token(_user(email_verified=False), now=100)
    assert verify_session_token(token, now=100) is None


def test_rejects_empty_and_malformed(session_secret):
    assert verify_session_token(None) is None
    assert verify_session_token("") is None
    assert verify_session_token("no-dot") is None
    assert verify_session_token("a.b.c") is None


def test_secret_rotation_invalidates(session_secret, monkeypatch):
    token = issue_session_token(_user(), now=100)
    assert verify_session_token(token, now=100) is not None
    monkeypatch.setenv("AUTH_SESSION_SECRET", "rotated-secret")
    assert verify_session_token(token, now=100) is None


def test_default_ttl_is_multi_week(session_secret):
    now = int(time.time())
    token = issue_session_token(_user(), now=now)
    # Still valid near end of default window
    assert verify_session_token(token, now=now + DEFAULT_TTL_SECONDS - 10) is not None
    assert verify_session_token(token, now=now + DEFAULT_TTL_SECONDS + 10) is None


def test_token_does_not_embed_password(session_secret):
    token = issue_session_token(_user(password="super-secret"), now=100)
    assert "super-secret" not in token
    assert "password" not in token.lower()


def _install_fake_streamlit(monkeypatch: pytest.MonkeyPatch, *, query: str = "", cookie: str = ""):
    """Minimal st.query_params / st.context.cookies for session restore tests."""
    st = types.ModuleType("streamlit")
    st.query_params = {"fx_session": query} if query else {}
    cookies = {"fx_session": cookie} if cookie else {}
    st.context = types.SimpleNamespace(cookies=cookies)
    monkeypatch.setitem(sys.modules, "streamlit", st)
    return st


def test_query_param_preferred_over_cookie(session_secret, monkeypatch):
    """Multi-tab: URL token wins over a newer cookie from another tab's login."""
    now = int(time.time())
    query_token = issue_session_token(
        _user(email="charanvenkatareddy678@gmail.com"),
        now=now,
    )
    cookie_token = issue_session_token(
        _user(email="charan.s@frequency.cx"),
        now=now,
    )
    _install_fake_streamlit(monkeypatch, query=query_token, cookie=cookie_token)
    candidates = read_session_token_candidates()
    assert candidates[0] == query_token
    assert candidates[1] == cookie_token
    chosen = read_session_token_from_request()
    assert chosen == query_token
    got = verify_session_token(chosen, now=now)
    assert got is not None
    assert got["email"] == "charanvenkatareddy678@gmail.com"


def test_cookie_used_when_query_absent(session_secret, monkeypatch):
    now = int(time.time())
    cookie_token = issue_session_token(_user(email="charan.s@frequency.cx"), now=now)
    _install_fake_streamlit(monkeypatch, query="", cookie=cookie_token)
    assert read_session_token_candidates() == [cookie_token]
    assert read_session_token_from_request() == cookie_token


def test_logout_blocks_cookie_restore(session_secret, monkeypatch):
    """After Log out, leftover cookie must not silently sign the user back in."""
    import frequency_agent.auth_ui as auth_ui

    class _SS(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

        def __setattr__(self, name, value):
            self[name] = value

    now = int(time.time())
    cookie_token = issue_session_token(_user(email="charan.s@frequency.cx"), now=now)
    st = _install_fake_streamlit(monkeypatch, query="", cookie=cookie_token)
    st.session_state = _SS(
        {
            "auth_user": {"email": "charan.s@frequency.cx", "email_verified": True},
            "auth_pending_email": "",
            "auth_pending_email_address_id": "",
            "auth_pending_user_id": "",
            "auth_flash": "",
            "auth_screen": "hub",
            "auth_needs_onboarding": False,
            "ui_theme": "dark",
        }
    )
    st.rerun = lambda: None
    monkeypatch.setattr(auth_ui, "st", st)
    monkeypatch.setattr(auth_ui, "clear_auth_session", lambda clear_cookie=True: None)

    auth_ui.logout()
    assert st.session_state.auth_user is None
    assert st.session_state.get("_auth_block_restore") is True
    assert st.session_state.get("_auth_need_cookie_clear") is True

    # Simulate the post-logout rerun: cookie still present in the request.
    st.session_state["_auth_need_cookie_clear"] = False
    auth_ui._ensure_auth_state()
    assert st.session_state.auth_user is None
