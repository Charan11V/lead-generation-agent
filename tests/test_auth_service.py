from __future__ import annotations

from frequency_agent.auth_service import ClerkAuthService, get_auth_service
from frequency_agent.auth import AuthService as LocalAuthService


def test_get_auth_service_defaults_local(monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    monkeypatch.delenv("AUTH_PROVIDER", raising=False)
    svc = get_auth_service()
    assert isinstance(svc, LocalAuthService)
    assert svc.provider == "local"


def test_get_auth_service_force_local(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("AUTH_PROVIDER", "local")
    svc = get_auth_service()
    assert isinstance(svc, LocalAuthService)


def test_get_auth_service_clerk(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake")
    monkeypatch.delenv("AUTH_PROVIDER", raising=False)
    svc = get_auth_service()
    assert isinstance(svc, ClerkAuthService)
    assert svc.provider == "clerk"
