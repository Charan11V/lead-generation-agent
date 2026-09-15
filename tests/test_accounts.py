"""Profiles, per-user API keys, admin helpers."""

from __future__ import annotations

import os
from pathlib import Path

from frequency_agent import accounts as accounts_mod
from frequency_agent.accounts import AccountStore, is_admin_email
from frequency_agent.memory import Memory


def test_admin_email_default(monkeypatch):
    monkeypatch.delenv("FREQUENCY_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("FREQUENCY_LOCAL_ADMINS", raising=False)
    monkeypatch.delenv("FREQUENCY_LOCAL_ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "")
    assert is_admin_email("charan.s@frequency.cx")
    assert is_admin_email("Charan.S@Frequency.cx")
    assert not is_admin_email("saarthak@frequency.cx")
    assert not is_admin_email("other@example.com")
    # Gmail is a normal user login — not an admin identity.
    assert not is_admin_email("charanvenkatareddy678@gmail.com")
    assert accounts_mod.can_manage_admins("charan.s@frequency.cx")
    assert not accounts_mod.can_manage_admins("saarthak@frequency.cx")
    assert not accounts_mod.can_manage_admins("other@example.com")


def test_localhost_grants_saarthak_admin(monkeypatch):
    monkeypatch.delenv("FREQUENCY_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("FREQUENCY_LOCAL_ADMINS", raising=False)
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "localhost")
    assert is_admin_email("saarthak@frequency.cx")
    assert is_admin_email("charan.s@frequency.cx")
    assert not accounts_mod.can_manage_admins("saarthak@frequency.cx")
    assert accounts_mod.can_manage_admins("charan.s@frequency.cx")
    monkeypatch.delenv("FREQUENCY_ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("FREQUENCY_LOCAL_ADMINS", "true")
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "")
    assert is_admin_email("saarthak@frequency.cx")
    assert is_admin_email("charan.s@frequency.cx")


def test_prod_host_never_grants_local_admin(monkeypatch):
    monkeypatch.delenv("FREQUENCY_ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("FREQUENCY_LOCAL_ADMINS", "true")
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "agent-internal.frequency.cx")
    assert not is_admin_email("saarthak@frequency.cx")
    assert is_admin_email("charan.s@frequency.cx")


def test_profile_and_api_keys(tmp_path: Path, monkeypatch):
    db = tmp_path / "a.db"
    store = AccountStore(path=db)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    p = store.ensure_profile("new@example.com", setup_complete=False)
    assert p["email"] == "new@example.com"
    assert int(p["setup_complete"]) == 0

    store.upsert_profile(
        "new@example.com",
        display_name="Ada",
        designation="Principal",
        company="Frequency",
        setup_complete=True,
    )
    p2 = store.get_profile("new@example.com")
    assert p2["display_name"] == "Ada"
    assert int(p2["setup_complete"]) == 1

    store.save_api_keys("new@example.com", tavily_key="tvly-test")
    keys = store.get_api_keys("new@example.com")
    assert keys["tavily_key"] == "tvly-test"
    assert "openai_key" not in keys

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-private")
    resolved = store.resolve_api_keys("new@example.com")
    assert resolved["openai_key"] == "sk-env-private"
    assert resolved["openai_source"] == "env"
    assert resolved["tavily_source"] == "user"
    assert resolved["tavily_key"] == "tvly-test"

    store.save_api_keys("new@example.com", clear_tavily=True)
    # Server env Tavily must never leak into another user's session.
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-env-shared")
    resolved2 = store.resolve_api_keys("new@example.com")
    assert resolved2["tavily_key"] == ""
    assert resolved2["tavily_source"] == "missing"
    assert resolved2["has_user_tavily"] is False
    assert resolved2["openai_key"] == "sk-env-private"

    store.save_api_keys("other@example.com", tavily_key="tvly-other")
    mine = store.resolve_api_keys("new@example.com")
    theirs = store.resolve_api_keys("other@example.com")
    assert mine["tavily_key"] == ""
    assert theirs["tavily_key"] == "tvly-other"
    assert theirs["tavily_source"] == "user"

def test_existing_profile_skips_forced_empty_complete(tmp_path: Path):
    db = tmp_path / "b.db"
    store = AccountStore(path=db)
    store.ensure_profile("old@example.com", setup_complete=True)
    p = store.get_profile("old@example.com")
    assert int(p["setup_complete"]) == 1
    assert (p.get("display_name") or "") == ""


def test_legacy_owner_is_frequency_admin(tmp_path: Path):
    db = tmp_path / "c.db"
    bare = Memory(path=db)
    q = bare.create_query_session("legacy", label="L")
    assert Memory.LEGACY_OWNER_EMAIL == "charan.s@frequency.cx"
    mem = Memory(path=db, owner_email="charan.s@frequency.cx")
    assert len(mem.list_query_sessions()) == 1
    assert mem.list_query_sessions()[0]["query_id"] == q


def test_active_gmail_owner_not_remapped(tmp_path: Path):
    """Gmail (and any real user email) must keep their rows across Memory re-init."""
    db = tmp_path / "d.db"
    gmail = "charanvenkatareddy678@gmail.com"
    user = Memory(path=db, owner_email=gmail)
    user.create_query_session("gmail inbox", label="Mine")
    # Re-open as admin / re-migrate must NOT steal gmail-owned rows.
    admin = Memory(path=db, owner_email="charan.s@frequency.cx")
    assert admin.list_query_sessions() == []
    again = Memory(path=db, owner_email=gmail)
    sessions = again.list_query_sessions()
    assert len(sessions) == 1
    assert sessions[0]["label"] == "Mine"
    assert sessions[0]["owner_email"] == gmail


def test_blank_owner_still_maps_to_admin(tmp_path: Path):
    """NULL/empty owner_email rows remain attributed to the admin account."""
    db = tmp_path / "d_blank.db"
    bare = Memory(path=db)
    qid = bare.create_query_session("unscoped", label="Legacy")
    with bare._connect() as conn:
        conn.execute(
            "UPDATE query_sessions SET owner_email = NULL WHERE query_id = ?",
            (qid,),
        )
    # Next init remaps blank → admin only
    admin = Memory(path=db, owner_email="charan.s@frequency.cx")
    sessions = admin.list_query_sessions()
    assert len(sessions) == 1
    assert sessions[0]["label"] == "Legacy"
    assert sessions[0]["owner_email"] == Memory.LEGACY_OWNER_EMAIL
    assert Memory(path=db, owner_email="charanvenkatareddy678@gmail.com").list_query_sessions() == []


def test_admin_purge(tmp_path: Path):
    db = tmp_path / "e.db"
    mem = Memory(path=db, owner_email="victim@example.com")
    mem.create_query_session("x", label="X")
    admin_view = Memory(path=db)  # unscoped
    admin_view.admin_purge_owner("victim@example.com")
    assert Memory(path=db, owner_email="victim@example.com").list_query_sessions() == []


def test_grant_and_revoke_admin(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FREQUENCY_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("FREQUENCY_LOCAL_ADMINS", raising=False)
    monkeypatch.delenv("FREQUENCY_LOCAL_ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "agent-internal.frequency.cx")
    db = tmp_path / "grants.db"
    store = AccountStore(path=db)
    actor = "charan.s@frequency.cx"
    target = "teammate@frequency.cx"

    assert store.is_admin(actor)
    assert not store.is_admin(target)
    assert accounts_mod.can_manage_admins(actor)
    assert not accounts_mod.can_manage_admins(target)

    ok, msg = store.grant_admin(target, actor_email=actor)
    assert ok, msg
    assert store.is_admin(target)
    assert store.has_admin_grant(target)
    assert accounts_mod.is_admin_email(target, path=db)
    assert not accounts_mod.can_manage_admins(target)

    denied, denied_msg = store.grant_admin("someone@frequency.cx", actor_email=target)
    assert not denied
    assert "cannot change admin access" in denied_msg.lower()
    assert not store.is_admin("someone@frequency.cx")

    locked, locked_msg = store.revoke_admin(actor, actor_email=actor)
    assert not locked
    assert store.is_admin(actor)

    ok, msg = store.revoke_admin(target, actor_email=actor)
    assert ok, msg
    assert not store.is_admin(target)
    assert not store.has_admin_grant(target)


def test_granted_admin_cannot_remove_other_admins(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FREQUENCY_ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "agent-internal.frequency.cx")
    db = tmp_path / "grants2.db"
    store = AccountStore(path=db)
    actor = "charan.s@frequency.cx"
    granted = "ops@frequency.cx"
    store.grant_admin(granted, actor_email=actor)
    ok, msg = store.revoke_admin(actor, actor_email=granted)
    assert not ok
    assert store.is_admin(actor)


def test_admin_can_remove_non_admin_not_self_or_admins(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FREQUENCY_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("FREQUENCY_LOCAL_ADMINS", raising=False)
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "agent-internal.frequency.cx")
    db = tmp_path / "remove-user.db"
    store = AccountStore(path=db)
    actor = "charan.s@frequency.cx"
    granted = "ops@frequency.cx"
    victim = "user@frequency.cx"
    store.ensure_profile(victim, setup_complete=True)
    store.save_api_keys(victim, tavily_key="tvly-victim")
    store.grant_admin(granted, actor_email=actor)

    ok, msg = store.can_remove_user(actor, actor_email=actor)
    assert not ok
    assert "own account" in msg.lower()

    ok, msg = store.can_remove_user(granted, actor_email=actor)
    assert not ok
    assert "admin" in msg.lower()

    ok, msg = store.remove_user(victim, actor_email=granted)
    assert ok, msg
    assert store.get_profile(victim) is None
    assert store.get_api_keys(victim)["tavily_key"] == ""

    denied, denied_msg = store.remove_user(victim, actor_email="nobody@frequency.cx")
    assert not denied
    assert "only admins" in denied_msg.lower()


def test_delete_profile_drops_admin_grant(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FREQUENCY_ADMIN_EMAILS", raising=False)
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "agent-internal.frequency.cx")
    db = tmp_path / "grants3.db"
    store = AccountStore(path=db)
    actor = "charan.s@frequency.cx"
    target = "gone@frequency.cx"
    store.grant_admin(target, actor_email=actor)
    store.delete_profile(target)
    assert not store.has_admin_grant(target)
    assert not store.is_admin(target)


def test_env_listed_admin_cannot_grant(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FREQUENCY_ADMIN_EMAILS", "ops@frequency.cx")
    monkeypatch.delenv("FREQUENCY_LOCAL_ADMINS", raising=False)
    monkeypatch.setattr(accounts_mod, "_request_host", lambda: "agent-internal.frequency.cx")
    db = tmp_path / "env-admin.db"
    store = AccountStore(path=db)
    assert store.is_admin("ops@frequency.cx")
    assert store.is_admin("charan.s@frequency.cx")
    assert not accounts_mod.can_manage_admins("ops@frequency.cx")
    ok, msg = store.grant_admin("new@frequency.cx", actor_email="ops@frequency.cx")
    assert not ok
    assert "cannot change admin access" in msg.lower()
    assert not store.is_admin("new@frequency.cx")
