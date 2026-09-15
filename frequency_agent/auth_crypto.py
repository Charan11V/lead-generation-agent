"""Password hashing and OTP helpers (stdlib only — no bcrypt dependency)."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Final

_PBKDF2_ROUNDS: Final[int] = 200_000
_OTP_LENGTH: Final[int] = 6
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(normalize_email(email)))


def hash_password(password: str, *, salt: str | None = None) -> tuple[str, str]:
    """Return (password_hash_hex, salt_hex)."""
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        _PBKDF2_ROUNDS,
    )
    return digest.hex(), salt_bytes.hex()


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, password_hash)


def generate_otp(length: int = _OTP_LENGTH) -> str:
    upper = 10**length
    return f"{secrets.randbelow(upper):0{length}d}"


def hash_otp(code: str, *, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()


def verify_otp(code: str, code_hash: str, *, salt: str) -> bool:
    return hmac.compare_digest(hash_otp(code.strip(), salt=salt), code_hash)


def password_ok(password: str, *, min_length: int = 8) -> tuple[bool, str]:
    if len(password or "") < min_length:
        return False, f"Password must be at least {min_length} characters."
    if password.isspace() or not password.strip():
        return False, "Password cannot be blank."
    return True, ""
