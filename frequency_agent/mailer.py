"""Outbound email for auth OTPs.

Register + password-reset OTPs: Resend when AUTH_DEV_MODE=0, else otp_dev.log.
(Clerk stores accounts; Resend delivers verification codes for this Streamlit app.)
"""

from __future__ import annotations

import os
from pathlib import Path

from .branding import brand_name

# Matches frequency_agent.auth.OTP_TTL_MINUTES (avoid circular import).
OTP_TTL_MINUTES = 10


def smtp_configured() -> bool:
    return bool(
        (os.getenv("SMTP_HOST") or "").strip()
        and (os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "").strip()
    )


def resend_configured() -> bool:
    return bool(
        (os.getenv("RESEND_API_KEY") or "").strip()
        and (os.getenv("RESET_EMAIL_FROM") or "").strip()
    )


def _auth_dev_flag() -> str:
    return (os.getenv("AUTH_DEV_MODE") or "").strip().lower()


def auth_dev_mode() -> bool:
    flag = _auth_dev_flag()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    # Legacy: missing SMTP used to imply dev logging.
    return not resend_configured() and not smtp_configured()


def send_otp_email(*, to_email: str, otp: str, purpose: str) -> tuple[bool, str]:
    """
    Send a 6-digit OTP for register or reset.
    AUTH_DEV_MODE=0 → Resend. AUTH_DEV_MODE=1 → output/otp_dev.log (never logs OTP in prod).
    """
    brand = brand_name()
    if purpose == "reset":
        subject = f"Reset your {brand} password"
        body = (
            f"We received a request to reset your {brand} password.\n\n"
            "Your verification code is:\n\n"
            f"    {otp}\n\n"
            f"This code expires in {OTP_TTL_MINUTES} minutes.\n\n"
            "If you did not request a password reset, you can ignore this email.\n\n"
            f"— {brand}\n"
        )
        fail_msg = "Could not send password reset email. Please try again later."
        missing_msg = "Password reset email is not configured."
    else:
        # register (and any other purpose)
        subject = f"Verify your {brand} email"
        body = (
            f"Welcome to {brand}.\n\n"
            "Your verification code is:\n\n"
            f"    {otp}\n\n"
            f"This code expires in {OTP_TTL_MINUTES} minutes.\n\n"
            "If you did not create an account, you can ignore this email.\n\n"
            f"— {brand}\n"
        )
        fail_msg = "Could not send verification email. Please try again later."
        missing_msg = "Verification email is not configured."

    if _auth_dev_flag() in {"1", "true", "yes", "on"}:
        return _write_dev_otp(to_email, otp, purpose, subject, body)

    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    from_addr = (os.getenv("RESET_EMAIL_FROM") or "").strip()
    if not api_key or not from_addr:
        return False, missing_msg

    try:
        import resend

        resend.api_key = api_key
        resend.Emails.send(
            {
                "from": from_addr,
                "to": [to_email],
                "subject": subject,
                "text": body,
            }
        )
        return True, f"OTP sent to {to_email}."
    except Exception:
        # Do not include API key, OTP, or raw provider details in the returned message.
        return False, fail_msg


def _write_dev_otp(to_email: str, otp: str, purpose: str, subject: str, body: str) -> tuple[bool, str]:
    root = Path(__file__).resolve().parent.parent
    path = root / "output" / "otp_dev.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n[{stamp}] to={to_email} purpose={purpose} otp={otp}\n{subject}\n{body}\n")
    return True, (
        f"Dev mode: OTP for {to_email} written to output/otp_dev.log "
        f"(AUTH_DEV_MODE=1)."
    )
