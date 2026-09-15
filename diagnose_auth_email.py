"""Diagnose registration email delivery (Clerk vs local)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)


def mask(v: str | None) -> str:
    v = (v or "").strip()
    if not v:
        return "(empty)"
    if len(v) <= 10:
        return v[:2] + "…"
    return f"{v[:8]}…{v[-4:]} (len={len(v)})"


def main() -> int:
    print("=== env (masked) ===")
    for k in [
        "AUTH_PROVIDER",
        "AUTH_DEV_MODE",
        "CLERK_SECRET_KEY",
        "CLERK_PUBLISHABLE_KEY",
        "RESEND_API_KEY",
        "RESET_EMAIL_FROM",
        "SMTP_HOST",
    ]:
        raw = os.getenv(k)
        if k.endswith("KEY") or k == "RESET_EMAIL_FROM":
            print(f"{k}={mask(raw)}")
        else:
            print(f"{k}={(raw or '').strip() or '(empty)'}")

    from frequency_agent.auth_service import auth_provider_label, get_auth_service
    from frequency_agent.clerk_client import clerk_configured

    svc = get_auth_service()
    print("\n=== active auth ===")
    print("label=", auth_provider_label())
    print("class=", type(svc).__name__)
    print("clerk_configured=", clerk_configured())

    log = ROOT / "output" / "otp_dev.log"
    print("\n=== otp_dev.log ===")
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="replace")
        lines = text.strip().splitlines()
        print(f"exists, lines={len(lines)}")
        # Show last few lines but redact otp= values
        for line in lines[-12:]:
            if "otp=" in line.lower():
                import re

                line = re.sub(r"(otp=)\d+", r"\1******", line, flags=re.I)
            print(line[:200])
    else:
        print("missing")

    if not clerk_configured():
        print("\nDIAGNOSIS: CLERK_SECRET_KEY is empty → app uses LOCAL auth.")
        print("Local registration OTP goes to smtp or otp_dev.log — NOT your inbox via Clerk/Resend.")
        print("Resend is only used for password-reset when AUTH_DEV_MODE=0.")
        return 1

    print("\n=== Clerk API probe ===")
    try:
        from frequency_agent.clerk_client import ClerkClient

        client = ClerkClient()
        # Light call: list users limit 1
        users = client._sdk.users.list(request={"limit": 1})
        print("users.list ok, count=", len(users or []))
    except Exception as exc:
        print("Clerk API error:", type(exc).__name__, str(exc)[:300])
        return 2

    # Inspect prepare_verification signature / whether strategy is required
    try:
        import inspect
        from clerk_backend_api.emailaddresses import EmailAddresses

        print("prepare_verification sig=", inspect.signature(EmailAddresses.prepare_verification))
    except Exception as exc:
        print("sig inspect failed:", exc)

    email = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if email:
        print(f"\n=== lookup {email} ===")
        user = client.find_by_email(email)
        if not user:
            print("No Clerk user for that email.")
        else:
            print(
                "user_id=",
                user.user_id[:8] + "…",
                "verified=",
                user.email_verified,
                "email_address_id=",
                (user.email_address_id[:8] + "…") if user.email_address_id else "(empty)",
            )
            if user.email_address_id and not user.email_verified:
                print("Attempting prepare_email_otp (sends Clerk verification email)...")
                try:
                    vid = client.prepare_email_otp(user.email_address_id)
                    print("prepare_email_otp OK, verification_id len=", len(vid))
                    print("Check inbox (and spam) for Clerk verification email.")
                except Exception as exc:
                    print("prepare_email_otp FAILED:", type(exc).__name__)
                    detail = str(exc)
                    # redact
                    detail = detail.replace(os.getenv("CLERK_SECRET_KEY") or "", "***")
                    print(detail[:500])
            elif user.email_verified:
                print("Email already verified in Clerk — registration OTP would not be resent as verify-email.")
    else:
        print("\nTip: re-run with email arg to probe that Clerk user:")
        print("  python diagnose_auth_email.py you@example.com")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
