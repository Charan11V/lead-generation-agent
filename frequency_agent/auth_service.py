"""Auth facade: Clerk when CLERK_SECRET_KEY is set, else local SQLite + SMTP OTP."""

from __future__ import annotations

import os

from .auth import AuthService as LocalAuthService
from .auth import AuthStore
from .auth_crypto import is_valid_email, normalize_email, password_ok
from .clerk_client import ClerkClient, clerk_configured


class ClerkAuthService:
    """
    Register → Clerk creates reserved email → Resend OTP → verify → mark Clerk email verified.
    Login → email + password only (no login 2FA).
    Password reset → Resend OTP then Clerk set_password.
    """

    provider = "clerk"

    def __init__(
        self,
        client: ClerkClient | None = None,
        otp_store: AuthStore | None = None,
    ) -> None:
        self.client = client or ClerkClient()
        self.otp_store = otp_store or AuthStore()

    def register(self, email: str, password: str, password_confirm: str) -> tuple[bool, str, dict | None]:
        email = normalize_email(email)
        if password != password_confirm:
            return False, "Passwords do not match.", None
        if not is_valid_email(email):
            return False, "Enter a valid email address.", None
        # Clerk Dashboard password policy on this instance requires 15+ chars.
        ok, reason = password_ok(password, min_length=15)
        if not ok:
            return False, reason, None

        existing = self.client.find_by_email(email)
        if existing:
            if existing.email_verified:
                return False, "An account with this email already exists. Log in or reset your password.", None
            # Unverified leftover — resend OTP and continue verification UI.
            pending = {
                "user_id": existing.user_id,
                "email": existing.email or email,
                "email_verified": False,
                "email_address_id": existing.email_address_id,
                "verification_id": "",
                "provider": "clerk",
                "otp_via": "local",
            }
            sent_ok, sent_msg = self.otp_store.issue_otp(email, "register", known_account=True)
            if not sent_ok:
                return True, f"Account pending verification. {sent_msg}", pending
            return True, f"Account pending verification. {sent_msg}", pending

        try:
            user = self.client.create_user(email, password)
        except Exception as exc:
            return False, _clerk_err("Could not create account", exc), None

        pending = {
            "user_id": user.user_id,
            "email": user.email or email,
            "email_verified": False,
            "email_address_id": user.email_address_id,
            "verification_id": "",
            "provider": "clerk",
            "otp_via": "local",
        }
        sent_ok, sent_msg = self.otp_store.issue_otp(email, "register", known_account=True)
        if not sent_ok:
            return (
                True,
                f"Account created, but sending the verification email failed: {sent_msg} "
                "Use Resend code on the next screen.",
                pending,
            )
        return True, "Account created. Check your email for a verification code.", pending

    def resend_register_otp(self, email: str, *, email_address_id: str = "") -> tuple[bool, str, str]:
        """Returns (ok, message, verification_id). verification_id unused for local OTP."""
        email = normalize_email(email)
        user = self.client.find_by_email(email)
        if not user and not email_address_id:
            return False, "Create an account first.", ""
        if user and user.email_verified:
            return False, "This email is already verified. You can log in.", ""
        ok, msg = self.otp_store.issue_otp(email, "register", known_account=True)
        return ok, msg, ""

    def verify_registration(
        self,
        email: str,
        code: str,
        *,
        email_address_id: str = "",
        verification_id: str = "",
    ) -> tuple[bool, str, dict | None]:
        email = normalize_email(email)
        ok, msg = self.otp_store.consume_otp(email, "register", code)
        if not ok:
            return False, msg, None

        ea_id = email_address_id
        user = self.client.find_by_email(email)
        if not ea_id and user:
            ea_id = user.email_address_id
        if not ea_id:
            return False, "Could not find this email on the account. Contact support.", None
        try:
            self.client.mark_email_verified(ea_id)
        except Exception as exc:
            return False, _clerk_err("Code accepted, but email could not be marked verified", exc), None

        user = self.client.find_by_email(email)
        if not user:
            return False, "Account not found after verification.", None
        # Force verified in session even if Clerk list lags.
        pub = self.public_user(user.__dict__)
        pub["email_verified"] = True
        return True, "Email verified. You are signed in.", pub

    def login(self, email: str, password: str) -> tuple[bool, str, dict | None]:
        email = normalize_email(email)
        user = self.client.find_by_email(email)
        if not user:
            return False, "Invalid email or password.", None
        if not self.client.verify_password(user.user_id, password):
            return False, "Invalid email or password.", None
        if not user.email_verified:
            pending = {
                "user_id": user.user_id,
                "email": user.email or email,
                "email_verified": False,
                "email_address_id": user.email_address_id,
                "verification_id": "",
                "provider": "clerk",
                "otp_via": "local",
            }
            try:
                self.otp_store.issue_otp(email, "register", known_account=True)
            except Exception:
                pass
            return False, "Email not verified yet. Enter the OTP we sent, or request a new one.", pending
        return True, "Logged in.", self.public_user(user.__dict__)

    def request_password_reset(self, email: str) -> tuple[bool, str, dict | None]:
        """Send a local OTP (Resend / AUTH_DEV_MODE). Clerk email OTP is only for unverified addresses."""
        email = normalize_email(email)
        user = self.client.find_by_email(email)
        if not user:
            return True, "If that email is registered, a reset code is on its way.", None
        ok, msg = self.otp_store.issue_otp(email, "reset", known_account=True)
        pending = {
            "user_id": user.user_id,
            "email": user.email,
            "email_address_id": user.email_address_id,
            "verification_id": "",
            "provider": "clerk",
            "reset_via": "local_otp",
        }
        if not ok:
            return False, msg, None
        return True, "If that email is registered, a reset code is on its way.", pending

    def reset_password(
        self,
        email: str,
        code: str,
        password: str,
        password_confirm: str,
        *,
        email_address_id: str = "",
        verification_id: str = "",
        user_id: str = "",
    ) -> tuple[bool, str]:
        if password != password_confirm:
            return False, "Passwords do not match."
        ok, reason = password_ok(password, min_length=15)
        if not ok:
            return False, reason
        email = normalize_email(email)
        ok, msg = self.otp_store.consume_otp(email, "reset", code)
        if not ok:
            return False, msg
        uid = user_id
        if not uid:
            user = self.client.find_by_email(email)
            if not user:
                return False, "No account found for that email."
            uid = user.user_id
        try:
            self.client.set_password(uid, password)
        except Exception as exc:
            return False, _clerk_err("Could not update password", exc)
        return True, "Password updated. You can log in now."

    def public_user(self, user: dict) -> dict:
        return {
            "user_id": user.get("user_id") or user.get("id") or "",
            "email": user.get("email") or "",
            "email_verified": bool(user.get("email_verified")),
            "provider": "clerk",
            "email_address_id": user.get("email_address_id") or "",
        }


def _clerk_err(prefix: str, exc: Exception) -> str:
    detail = str(exc).strip() or type(exc).__name__
    # Avoid dumping huge SDK traces into the UI
    if len(detail) > 220:
        detail = detail[:220] + "…"
    if prefix:
        return f"{prefix}: {detail}"
    return detail


def get_auth_service() -> LocalAuthService | ClerkAuthService:
    """
    Prefer Clerk when CLERK_SECRET_KEY is present.
    AUTH_PROVIDER=local forces the SQLite + SMTP path (useful for tests / offline).
    """
    provider = (os.getenv("AUTH_PROVIDER") or "").strip().lower()
    if provider == "local":
        return LocalAuthService()
    if provider == "clerk" or clerk_configured():
        if not clerk_configured():
            raise RuntimeError("AUTH_PROVIDER=clerk but CLERK_SECRET_KEY is missing.")
        return ClerkAuthService()
    return LocalAuthService()


def auth_provider_label() -> str:
    svc = get_auth_service()
    if isinstance(svc, ClerkAuthService):
        return "Clerk"
    return "local"
