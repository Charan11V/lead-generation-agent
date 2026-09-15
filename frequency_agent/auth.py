"""User accounts + email OTP verification (register, login, password reset)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .auth_crypto import (
    generate_otp,
    hash_otp,
    hash_password,
    is_valid_email,
    normalize_email,
    password_ok,
    verify_otp,
    verify_password,
)
from .mailer import send_otp_email
from .util import default_db_path

OTP_TTL_MINUTES = 10
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class AuthStore:
    """SQLite-backed auth. Uses the same DB file as Memory by default."""

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
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    email_verified INTEGER DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS otp_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed INTEGER DEFAULT 0,
                    attempts INTEGER DEFAULT 0,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_otp_email_purpose
                    ON otp_codes (email, purpose, created_at);
                """
            )

    # ── users ──────────────────────────────────────────────

    def get_user_by_email(self, email: str) -> dict | None:
        email = normalize_email(email)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def create_user(self, email: str, password: str) -> tuple[bool, str, dict | None]:
        email = normalize_email(email)
        if not is_valid_email(email):
            return False, "Enter a valid email address.", None
        ok, reason = password_ok(password)
        if not ok:
            return False, reason, None
        if self.get_user_by_email(email):
            return False, "An account with this email already exists. Log in or reset your password.", None

        pw_hash, salt = hash_password(password)
        user_id = uuid.uuid4().hex
        now = _iso(_now())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, email, password_hash, salt, email_verified, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (user_id, email, pw_hash, salt, now, now),
            )
        return True, "Account created. Check your email for a verification code.", self.get_user(user_id)

    def mark_email_verified(self, email: str) -> None:
        email = normalize_email(email)
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET email_verified = 1, updated_at = ? WHERE email = ?",
                (_iso(_now()), email),
            )

    def delete_user(self, email: str) -> None:
        """Remove login credentials and OTP rows for this email."""
        email = normalize_email(email)
        if not email:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM users WHERE email = ?", (email,))
            conn.execute("DELETE FROM otp_codes WHERE email = ?", (email,))

    def set_password(self, email: str, password: str) -> tuple[bool, str]:
        email = normalize_email(email)
        ok, reason = password_ok(password)
        if not ok:
            return False, reason
        user = self.get_user_by_email(email)
        if not user:
            return False, "No account found for that email."
        pw_hash, salt = hash_password(password)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users SET password_hash = ?, salt = ?, updated_at = ?, email_verified = 1
                WHERE email = ?
                """,
                (pw_hash, salt, _iso(_now()), email),
            )
        return True, "Password updated. You can log in now."

    def authenticate(self, email: str, password: str) -> tuple[bool, str, dict | None]:
        email = normalize_email(email)
        user = self.get_user_by_email(email)
        if not user:
            return False, "Invalid email or password.", None
        if not verify_password(password, user["password_hash"], user["salt"]):
            return False, "Invalid email or password.", None
        if not int(user.get("email_verified") or 0):
            return False, "Email not verified yet. Enter the OTP we sent, or request a new one.", user
        return True, "Logged in.", user

    # ── OTP ────────────────────────────────────────────────

    def _latest_otp(self, email: str, purpose: str) -> dict | None:
        email = normalize_email(email)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM otp_codes
                WHERE email = ? AND purpose = ? AND consumed = 0
                ORDER BY id DESC LIMIT 1
                """,
                (email, purpose),
            ).fetchone()
        return dict(row) if row else None

    def issue_otp(
        self,
        email: str,
        purpose: str,
        *,
        known_account: bool | None = None,
    ) -> tuple[bool, str]:
        """
        Issue an OTP for register/reset.
        known_account: when True, skip local-user lookup (Clerk accounts live elsewhere).
        when False/None for reset without a local user, return a generic success (no send).
        """
        email = normalize_email(email)
        if not is_valid_email(email):
            return False, "Enter a valid email address."
        if purpose not in {"register", "reset"}:
            return False, "Invalid OTP purpose."

        user = self.get_user_by_email(email)
        if purpose == "register":
            if known_account is True:
                pass  # Clerk account — no local users row
            else:
                if not user:
                    return False, "Create an account first."
                if int(user.get("email_verified") or 0):
                    return False, "This email is already verified. You can log in."
        if purpose == "reset":
            if known_account is True:
                pass  # Clerk (or other) already confirmed the account exists
            elif not user:
                # Don't reveal whether the email exists.
                return True, "If that email is registered, a reset code is on its way."

        existing = self._latest_otp(email, purpose)
        if existing:
            try:
                created = datetime.fromisoformat(existing["created_at"])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age = (_now() - created).total_seconds()
                if age < OTP_RESEND_SECONDS:
                    wait = int(OTP_RESEND_SECONDS - age)
                    return False, f"Wait {wait}s before requesting another code."
            except ValueError:
                pass

        code = generate_otp()
        salt = uuid.uuid4().hex
        code_hash = hash_otp(code, salt=salt)
        expires = _now() + timedelta(minutes=OTP_TTL_MINUTES)
        with self._connect() as conn:
            # Invalidate prior unused codes for this purpose.
            conn.execute(
                "UPDATE otp_codes SET consumed = 1 WHERE email = ? AND purpose = ? AND consumed = 0",
                (email, purpose),
            )
            conn.execute(
                """
                INSERT INTO otp_codes (email, purpose, code_hash, salt, expires_at, consumed, attempts, created_at)
                VALUES (?, ?, ?, ?, ?, 0, 0, ?)
                """,
                (email, purpose, code_hash, salt, _iso(expires), _iso(_now())),
            )

        ok, msg = send_otp_email(to_email=email, otp=code, purpose=purpose)
        if purpose == "reset" and not user and known_account is not True:
            return True, "If that email is registered, a reset code is on its way."
        # Propagate mailer success/failure (do not pretend send succeeded).
        return bool(ok), msg

    def consume_otp(self, email: str, purpose: str, code: str) -> tuple[bool, str]:
        email = normalize_email(email)
        code = (code or "").strip()
        if not code.isdigit() or len(code) != 6:
            return False, "Enter the 6-digit code from your email."

        row = self._latest_otp(email, purpose)
        if not row:
            return False, "No active code. Request a new OTP."

        try:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
        except ValueError:
            return False, "Code expired. Request a new one."

        if _now() > expires:
            with self._connect() as conn:
                conn.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (row["id"],))
            return False, "Code expired. Request a new one."

        attempts = int(row.get("attempts") or 0)
        if attempts >= OTP_MAX_ATTEMPTS:
            with self._connect() as conn:
                conn.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (row["id"],))
            return False, "Too many attempts. Request a new code."

        if not verify_otp(code, row["code_hash"], salt=row["salt"]):
            with self._connect() as conn:
                conn.execute(
                    "UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?",
                    (row["id"],),
                )
            left = OTP_MAX_ATTEMPTS - attempts - 1
            return False, f"Incorrect code. {left} attempt(s) left."

        with self._connect() as conn:
            conn.execute("UPDATE otp_codes SET consumed = 1 WHERE id = ?", (row["id"],))
        return True, "Code verified."


class AuthService:
    """High-level auth flows used by the Streamlit gate."""

    provider = "local"

    def __init__(self, store: AuthStore | None = None) -> None:
        self.store = store or AuthStore()

    def register(self, email: str, password: str, password_confirm: str) -> tuple[bool, str, dict | None]:
        if password != password_confirm:
            return False, "Passwords do not match.", None
        ok, msg, user = self.store.create_user(email, password)
        if not ok or not user:
            return ok, msg, user
        sent_ok, sent_msg = self.store.issue_otp(user["email"], "register")
        return True, f"{msg} {sent_msg}", user

    def resend_register_otp(self, email: str) -> tuple[bool, str]:
        return self.store.issue_otp(email, "register")

    def verify_registration(self, email: str, code: str) -> tuple[bool, str, dict | None]:
        ok, msg = self.store.consume_otp(email, "register", code)
        if not ok:
            return False, msg, None
        self.store.mark_email_verified(email)
        user = self.store.get_user_by_email(email)
        return True, "Email verified. You are signed in.", user

    def login(self, email: str, password: str) -> tuple[bool, str, dict | None]:
        return self.store.authenticate(email, password)

    def request_password_reset(self, email: str) -> tuple[bool, str]:
        user = self.store.get_user_by_email(email)
        if not user:
            # Always look successful to avoid account enumeration.
            return True, "If that email is registered, a reset code is on its way."
        return self.store.issue_otp(email, "reset")

    def reset_password(
        self, email: str, code: str, password: str, password_confirm: str
    ) -> tuple[bool, str]:
        if password != password_confirm:
            return False, "Passwords do not match."
        ok, msg = self.store.consume_otp(email, "reset", code)
        if not ok:
            return False, msg
        return self.store.set_password(email, password)

    def public_user(self, user: dict) -> dict:
        return {
            "user_id": user["user_id"],
            "email": user["email"],
            "email_verified": bool(int(user.get("email_verified") or 0)),
            "provider": "local",
        }
