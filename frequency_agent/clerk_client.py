"""Clerk Backend API client for email/password + email OTP verification."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


def clerk_configured() -> bool:
    return bool((os.getenv("CLERK_SECRET_KEY") or "").strip())


def clerk_publishable_key() -> str:
    return (os.getenv("CLERK_PUBLISHABLE_KEY") or "").strip()


@dataclass
class ClerkUser:
    user_id: str
    email: str
    email_verified: bool
    email_address_id: str = ""
    raw: Any = None


class ClerkClient:
    """Thin wrapper around clerk-backend-api."""

    def __init__(self, secret_key: str | None = None) -> None:
        key = (secret_key or os.getenv("CLERK_SECRET_KEY") or "").strip()
        if not key:
            raise RuntimeError("CLERK_SECRET_KEY is not set.")
        from clerk_backend_api import Clerk

        self._sdk = Clerk(bearer_auth=key)

    def find_by_email(self, email: str) -> ClerkUser | None:
        email = (email or "").strip().lower()
        users = self._sdk.users.list(request={"email_address": [email], "limit": 5})
        if not users:
            return None
        return self._to_user(users[0], preferred_email=email)

    def create_user(self, email: str, password: str) -> ClerkUser:
        """
        Create user with email reserved (unverified) so registration OTP is required.
        Without reserved status, Clerk marks backend-created emails as verified.
        """
        from clerk_backend_api.models.createuserop import EmailAddressIdentificationStatus

        email = (email or "").strip().lower()
        user = self._sdk.users.create(
            email_address=[email],
            email_address_identification_status=[EmailAddressIdentificationStatus.RESERVED],
            password=password,
            skip_password_checks=False,
        )
        parsed = self._to_user(user, preferred_email=email)
        if not parsed.email_address_id:
            refreshed = self.find_by_email(email)
            if refreshed:
                return refreshed
        return parsed

    def verify_password(self, user_id: str, password: str) -> bool:
        try:
            resp = self._sdk.users.verify_password(user_id=user_id, password=password)
            return bool(getattr(resp, "verified", False))
        except Exception:
            return False

    def prepare_email_otp(self, email_address_id: str) -> str:
        """Send Clerk email OTP; returns verification_id needed for attempt."""
        resp = self._sdk.email_addresses.prepare_verification(email_address_id=email_address_id)
        vid = getattr(resp, "id", None) or ""
        if not vid:
            raise RuntimeError("Clerk did not return a verification id.")
        return str(vid)

    def attempt_email_otp(self, email_address_id: str, verification_id: str, code: str) -> bool:
        resp = self._sdk.email_addresses.attempt_verification(
            email_address_id=email_address_id,
            verification_id=verification_id,
            code=(code or "").strip(),
        )
        status = (getattr(resp, "status", None) or "").lower()
        if status in {"verified", "complete", "completed"}:
            return True
        # Some SDK payloads nest status under verification
        ver = getattr(resp, "verification", None)
        nested = (getattr(ver, "status", None) or "").lower() if ver is not None else ""
        return nested in {"verified", "complete", "completed"}

    def set_password(self, user_id: str, password: str) -> None:
        self._sdk.users.update(user_id=user_id, password=password, skip_password_checks=False)

    def mark_email_verified(self, email_address_id: str) -> None:
        self._sdk.email_addresses.update(email_address_id=email_address_id, verified=True)

    def _to_user(self, user: Any, *, preferred_email: str = "") -> ClerkUser:
        emails = list(getattr(user, "email_addresses", None) or [])
        chosen = None
        for ea in emails:
            addr = (getattr(ea, "email_address", None) or "").lower()
            if preferred_email and addr == preferred_email:
                chosen = ea
                break
        if chosen is None and emails:
            primary_id = getattr(user, "primary_email_address_id", None)
            for ea in emails:
                if getattr(ea, "id", None) == primary_id:
                    chosen = ea
                    break
            chosen = chosen or emails[0]

        email = ""
        email_id = ""
        verified = False
        if chosen is not None:
            email = (getattr(chosen, "email_address", None) or "").lower()
            email_id = str(getattr(chosen, "id", "") or "")
            if getattr(chosen, "reserved", False):
                verified = False
            else:
                ver = getattr(chosen, "verification", None)
                status = (getattr(ver, "status", None) or "").lower() if ver is not None else ""
                verified = status == "verified"
                if not verified:
                    ident = (getattr(chosen, "identification_status", None) or "").lower()
                    # "reserved" / "unverified" are not verified
                    verified = ident in {"verified", "confirmed"}

        return ClerkUser(
            user_id=str(getattr(user, "id", "") or ""),
            email=email or preferred_email,
            email_verified=verified,
            email_address_id=email_id,
            raw=user,
        )
