"""User profiles, per-user API keys, and admin directory."""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .auth_crypto import normalize_email
from .util import default_db_path

ADMIN_EMAILS_DEFAULT = ("charan.s@frequency.cx",)
# Extra admins on localhost only — never on agent-internal.frequency.cx.
LOCAL_ONLY_ADMIN_EMAILS = ("saarthak@frequency.cx",)
PRODUCTION_HOSTS = ("agent-internal.frequency.cx",)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _csv_emails(raw: str) -> set[str]:
    return {normalize_email(x) for x in raw.split(",") if x.strip()}


def _request_host() -> str:
    """Browser Host header when running under Streamlit; empty in tests/CLI."""
    try:
        import streamlit as st

        headers = getattr(getattr(st, "context", None), "headers", None) or {}
        raw = headers.get("Host") or headers.get("host") or ""
        host = str(raw).strip().lower()
        return host.split("/")[0].split(":")[0]
    except Exception:
        return ""


def _include_local_only_admins() -> bool:
    host = _request_host()
    if host in PRODUCTION_HOSTS:
        return False
    flag = (os.getenv("FREQUENCY_LOCAL_ADMINS") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    return host in LOCAL_HOSTS


def admin_emails() -> set[str]:
    raw = (os.getenv("FREQUENCY_ADMIN_EMAILS") or "").strip()
    emails = _csv_emails(raw) if raw else set()
    emails.update(normalize_email(x) for x in ADMIN_EMAILS_DEFAULT)
    extra_raw = (os.getenv("FREQUENCY_LOCAL_ADMIN_EMAILS") or "").strip()
    local_extra = (
        _csv_emails(extra_raw)
        if extra_raw
        else {normalize_email(x) for x in LOCAL_ONLY_ADMIN_EMAILS}
    )
    if _include_local_only_admins():
        emails.update(local_extra)
    return emails


def can_manage_admins(email: str) -> bool:
    return normalize_email(email) in {normalize_email(x) for x in ADMIN_EMAILS_DEFAULT}


def _granted_admin_emails(path: str | Path | None = None) -> set[str]:
    db = Path(path) if path else default_db_path()
    if not db.exists():
        return set()
    try:
        conn = sqlite3.connect(str(db), timeout=5)
        try:
            rows = conn.execute("SELECT email FROM account_admin_grants").fetchall()
        except sqlite3.OperationalError:
            return set()
        finally:
            conn.close()
    except Exception:
        return set()
    return {normalize_email(r[0]) for r in rows if r and r[0]}


def is_admin_email(email: str, *, path: str | Path | None = None) -> bool:
    email = normalize_email(email)
    if not email:
        return False
    if email in admin_emails():
        return True
    return email in _granted_admin_emails(path)


def _fernet() -> Fernet:
    secret = (
        (os.getenv("FREQUENCY_SECRETS_KEY") or "").strip()
        or (os.getenv("CLERK_SECRET_KEY") or "").strip()
        or "frequency-dev-secrets-change-me"
    )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""


def mask_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}…{value[-4:]}"


class AccountStore:
    """Local profiles + encrypted API keys (shared DB with auth/memory)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    email TEXT PRIMARY KEY,
                    display_name TEXT DEFAULT '',
                    designation TEXT DEFAULT '',
                    company TEXT DEFAULT '',
                    phone TEXT DEFAULT '',
                    linkedin_url TEXT DEFAULT '',
                    work_notes TEXT DEFAULT '',
                    setup_complete INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS user_api_keys (
                    email TEXT PRIMARY KEY,
                    openai_key_enc TEXT DEFAULT '',
                    tavily_key_enc TEXT DEFAULT '',
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS account_admin_grants (
                    email TEXT PRIMARY KEY,
                    granted_by TEXT DEFAULT '',
                    granted_at TEXT
                );
                """
            )
            self._seed_admins(conn)

    def _seed_admins(self, conn: sqlite3.Connection) -> None:
        now = _now()
        for email in admin_emails():
            row = conn.execute(
                "SELECT email FROM user_profiles WHERE email = ?", (email,)
            ).fetchone()
            if row:
                continue
            conn.execute(
                """
                INSERT INTO user_profiles (
                    email, display_name, designation, company, phone, linkedin_url,
                    work_notes, setup_complete, created_at, updated_at
                ) VALUES (?, '', '', '', '', '', '', 1, ?, ?)
                """,
                (email, now, now),
            )

    def ensure_profile(
        self,
        email: str,
        *,
        setup_complete: bool | None = None,
    ) -> dict:
        email = normalize_email(email)
        if not email:
            return {}
        existing = self.get_profile(email)
        if existing:
            return existing
        complete = 1 if (setup_complete if setup_complete is not None else True) else 0
        # New post-verify registrations pass setup_complete=False.
        # Existing accounts (first touch after deploy) get complete=True so they skip forced onboarding.
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO user_profiles (
                    email, display_name, designation, company, phone, linkedin_url,
                    work_notes, setup_complete, created_at, updated_at
                ) VALUES (?, '', '', '', '', '', '', ?, ?, ?)
                """,
                (email, complete, now, now),
            )
        return self.get_profile(email) or {}

    def get_profile(self, email: str) -> dict | None:
        email = normalize_email(email)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE email = ?", (email,)
            ).fetchone()
        return dict(row) if row else None

    def profile_complete(self, email: str) -> bool:
        profile = self.get_profile(email)
        if not profile:
            return False
        return bool(int(profile.get("setup_complete") or 0))

    def upsert_profile(
        self,
        email: str,
        *,
        display_name: str = "",
        designation: str = "",
        company: str = "",
        phone: str = "",
        linkedin_url: str = "",
        work_notes: str = "",
        setup_complete: bool | None = None,
    ) -> dict:
        email = normalize_email(email)
        now = _now()
        current = self.ensure_profile(email, setup_complete=False)
        complete = (
            int(bool(setup_complete))
            if setup_complete is not None
            else int(current.get("setup_complete") or 0)
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles (
                    email, display_name, designation, company, phone, linkedin_url,
                    work_notes, setup_complete, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    display_name = excluded.display_name,
                    designation = excluded.designation,
                    company = excluded.company,
                    phone = excluded.phone,
                    linkedin_url = excluded.linkedin_url,
                    work_notes = excluded.work_notes,
                    setup_complete = excluded.setup_complete,
                    updated_at = excluded.updated_at
                """,
                (
                    email,
                    (display_name or "").strip(),
                    (designation or "").strip(),
                    (company or "").strip(),
                    (phone or "").strip(),
                    (linkedin_url or "").strip(),
                    (work_notes or "").strip(),
                    complete,
                    current.get("created_at") or now,
                    now,
                ),
            )
        return self.get_profile(email) or {}

    def mark_setup_complete(self, email: str) -> dict:
        profile = self.get_profile(email) or self.ensure_profile(email, setup_complete=False)
        return self.upsert_profile(
            email,
            display_name=profile.get("display_name") or "",
            designation=profile.get("designation") or "",
            company=profile.get("company") or "",
            phone=profile.get("phone") or "",
            linkedin_url=profile.get("linkedin_url") or "",
            work_notes=profile.get("work_notes") or "",
            setup_complete=True,
        )

    def list_profiles(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM user_profiles ORDER BY updated_at DESC, email ASC"
            ).fetchall()
        out = [dict(r) for r in rows]
        builtin = admin_emails()
        granted = _granted_admin_emails(self.path)
        for row in out:
            email = normalize_email(row.get("email") or "")
            row["is_admin"] = email in builtin or email in granted
        return out

    def is_admin(self, email: str) -> bool:
        return is_admin_email(email, path=self.path)

    def has_admin_grant(self, email: str) -> bool:
        email = normalize_email(email)
        if not email:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT email FROM account_admin_grants WHERE email = ?",
                (email,),
            ).fetchone()
        return bool(row)

    def grant_admin(self, email: str, *, actor_email: str) -> tuple[bool, str]:
        email = normalize_email(email)
        actor = normalize_email(actor_email)
        if not can_manage_admins(actor):
            return False, "You cannot change admin access."
        if not email:
            return False, "Pick an account first."
        if email == actor:
            return False, "You already have admin access."
        if email in admin_emails():
            return False, "This account is already an admin."
        if self.has_admin_grant(email):
            return False, "This account is already an admin."
        now = _now()
        self.ensure_profile(email, setup_complete=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO account_admin_grants (email, granted_by, granted_at)
                VALUES (?, ?, ?)
                """,
                (email, actor, now),
            )
        return True, "Admin access granted."

    def revoke_admin(self, email: str, *, actor_email: str) -> tuple[bool, str]:
        email = normalize_email(email)
        actor = normalize_email(actor_email)
        if not can_manage_admins(actor):
            return False, "You cannot change admin access."
        if not email:
            return False, "Pick an account first."
        if email == actor or email in admin_emails():
            return False, "Admin access for this account cannot be removed."
        if not self.has_admin_grant(email):
            return False, "This account is not an admin."
        with self._connect() as conn:
            conn.execute("DELETE FROM account_admin_grants WHERE email = ?", (email,))
        return True, "Admin access removed."

    def can_remove_user(self, email: str, *, actor_email: str) -> tuple[bool, str]:
        """Admins may remove non-admin accounts — never themselves or other admins."""
        email = normalize_email(email)
        actor = normalize_email(actor_email)
        if not actor or not self.is_admin(actor):
            return False, "Only admins can remove users."
        if not email:
            return False, "Pick an account first."
        if email == actor:
            return False, "You cannot remove your own account."
        if self.is_admin(email):
            return False, "Admin accounts cannot be removed."
        return True, ""

    def remove_user(self, email: str, *, actor_email: str) -> tuple[bool, str]:
        ok, msg = self.can_remove_user(email, actor_email=actor_email)
        if not ok:
            return False, msg
        self.delete_profile(email)
        return True, "Account removed."

    def delete_profile(self, email: str) -> None:
        email = normalize_email(email)
        with self._connect() as conn:
            conn.execute("DELETE FROM user_profiles WHERE email = ?", (email,))
            conn.execute("DELETE FROM user_api_keys WHERE email = ?", (email,))
            conn.execute("DELETE FROM account_admin_grants WHERE email = ?", (email,))

    def get_api_keys(self, email: str) -> dict:
        email = normalize_email(email)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_api_keys WHERE email = ?", (email,)
            ).fetchone()
        if not row:
            return {"tavily_key": "", "updated_at": ""}
        return {
            "tavily_key": decrypt_secret(row["tavily_key_enc"] or ""),
            "updated_at": row["updated_at"] or "",
        }

    def save_api_keys(
        self,
        email: str,
        *,
        tavily_key: str | None = None,
        clear_tavily: bool = False,
    ) -> dict:
        """
        Save the user's Tavily key only. OpenAI stays server-side (.env).
        Pass None to leave unchanged; clear_tavily wipes the stored key.
        """
        email = normalize_email(email)
        current = self.get_api_keys(email)
        next_tavily = current["tavily_key"]
        if clear_tavily:
            next_tavily = ""
        elif tavily_key is not None and tavily_key.strip():
            next_tavily = tavily_key.strip()
        now = _now()
        with self._connect() as conn:
            # Keep openai_key_enc column empty — never store user OpenAI keys.
            conn.execute(
                """
                INSERT INTO user_api_keys (email, openai_key_enc, tavily_key_enc, updated_at)
                VALUES (?, '', ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    openai_key_enc = '',
                    tavily_key_enc = excluded.tavily_key_enc,
                    updated_at = excluded.updated_at
                """,
                (
                    email,
                    encrypt_secret(next_tavily),
                    now,
                ),
            )
        return self.get_api_keys(email)

    def resolve_api_keys(self, email: str) -> dict:
        """OpenAI from server env; Tavily only from this user's stored key (never shared)."""
        stored = self.get_api_keys(email)
        env_openai = (os.getenv("OPENAI_API_KEY") or "").strip()
        tavily = (stored.get("tavily_key") or "").strip()
        return {
            "openai_key": env_openai,
            "tavily_key": tavily,
            "openai_source": "env" if env_openai else "missing",
            "tavily_source": "user" if tavily else "missing",
            "tavily_masked": mask_secret(tavily),
            "has_user_tavily": bool(tavily),
        }


def get_account_store(path: str | Path | None = None) -> AccountStore:
    return AccountStore(path=path)
