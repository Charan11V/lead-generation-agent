"""Streamlit auth screens — login, register + OTP, profile setup, forgot password."""

from __future__ import annotations

import streamlit as st

from .accounts import get_account_store, is_admin_email
from .auth_service import auth_provider_label, get_auth_service
from .branding import brand_name, brand_wordmark
from .clerk_client import clerk_publishable_key
from .mailer import auth_dev_mode, resend_configured
from .session_cookie import clear_auth_session, persist_auth_session, restore_auth_user
from .settings_ui import render_profile_setup


def _ensure_auth_state() -> None:
    defaults = {
        "auth_user": None,
        "auth_pending_email": "",
        "auth_pending_email_address_id": "",
        "auth_pending_user_id": "",
        "auth_flash": "",
        "auth_screen": "hub",  # hub | verify | reset | profile_setup
        "auth_needs_onboarding": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Finish logout on this run: deliver cookie-clear JS (prior run's st.rerun
    # aborted before the browser could execute it).
    if st.session_state.pop("_auth_need_cookie_clear", False):
        clear_auth_session(clear_cookie=True)

    # Explicit logout: never auto-restore from leftover cookie / URL token
    # until the user signs in again (same Streamlit browser session).
    if st.session_state.get("_auth_block_restore"):
        st.session_state.auth_user = None
        return

    # Browser refresh clears session_state; restore from ?fx_session= / cookie.
    # Only when auth_user is empty — never overwrite a live tab-local login.
    if not st.session_state.auth_user:
        restored = restore_auth_user(is_admin_email=is_admin_email)
        if restored:
            st.session_state.auth_user = restored


def current_user() -> dict | None:
    _ensure_auth_state()
    return st.session_state.auth_user


def logout() -> None:
    # Preserve ui_theme across logout (also mirrored in ?theme= query param).
    theme = st.session_state.get("ui_theme")
    st.session_state.auth_user = None
    st.session_state.auth_pending_email = ""
    st.session_state.auth_pending_email_address_id = ""
    st.session_state.auth_pending_user_id = ""
    st.session_state.auth_flash = ""
    st.session_state.auth_screen = "hub"
    st.session_state.auth_needs_onboarding = False
    # Block cookie/URL restore after logout; clear URL now; clear cookie on next run
    # so components.html is actually delivered to the browser.
    st.session_state["_auth_block_restore"] = True
    st.session_state["_auth_need_cookie_clear"] = True
    clear_auth_session(clear_cookie=False)
    if theme in ("dark", "light"):
        st.session_state.ui_theme = theme


def _remember_pending(pending: dict | None, *, fallback_email: str = "") -> None:
    pending = pending or {}
    st.session_state.auth_pending_email = (
        (pending.get("email") or "").strip().lower()
        or (fallback_email or "").strip().lower()
        or (st.session_state.auth_pending_email or "")
    )
    if pending.get("email_address_id"):
        st.session_state.auth_pending_email_address_id = str(pending.get("email_address_id") or "")
    if pending.get("user_id"):
        st.session_state.auth_pending_user_id = str(pending.get("user_id") or "")


def _is_clerk(auth) -> bool:
    return getattr(auth, "provider", "") == "clerk" or auth.__class__.__name__ == "ClerkAuthService"


def _email_unverified(user: dict) -> bool:
    v = user.get("email_verified")
    if isinstance(v, bool):
        return not v
    try:
        return not bool(int(v or 0))
    except (TypeError, ValueError):
        return not bool(v)


def _session_user(auth, user: dict) -> dict:
    if user.get("provider") in {"clerk", "local"} and "email" in user:
        email = user.get("email") or ""
        return {
            "user_id": user.get("user_id") or "",
            "email": email,
            "email_verified": bool(user.get("email_verified")),
            "provider": user.get("provider") or getattr(auth, "provider", "local"),
            "email_address_id": user.get("email_address_id") or "",
            "is_admin": is_admin_email(email),
        }
    pub = auth.public_user(user)
    pub["is_admin"] = is_admin_email(pub.get("email") or "")
    return pub


def _clear_pending() -> None:
    st.session_state.auth_pending_email = ""
    st.session_state.auth_pending_email_address_id = ""
    st.session_state.auth_pending_user_id = ""


def _accounts():
    return get_account_store()


def _after_verified_login(auth, user: dict, *, onboarding: bool) -> None:
    st.session_state.pop("_auth_block_restore", None)
    st.session_state.pop("_auth_need_cookie_clear", None)
    st.session_state.auth_user = _session_user(auth, user)
    persist_auth_session(st.session_state.auth_user)
    _clear_pending()
    email = (st.session_state.auth_user.get("email") or "").strip().lower()
    store = _accounts()
    if onboarding and not is_admin_email(email):
        existing = store.get_profile(email)
        if existing:
            store.upsert_profile(
                email,
                display_name=existing.get("display_name") or "",
                designation=existing.get("designation") or "",
                company=existing.get("company") or "",
                phone=existing.get("phone") or "",
                linkedin_url=existing.get("linkedin_url") or "",
                work_notes=existing.get("work_notes") or "",
                setup_complete=False,
            )
        else:
            store.ensure_profile(email, setup_complete=False)
        st.session_state.auth_needs_onboarding = True
        st.session_state.auth_screen = "profile_setup"
        return

    if not store.get_profile(email):
        store.ensure_profile(email, setup_complete=True)
    profile = store.get_profile(email) or {}
    if not int(profile.get("setup_complete") or 0):
        st.session_state.auth_needs_onboarding = True
        st.session_state.auth_screen = "profile_setup"
    else:
        st.session_state.auth_needs_onboarding = False
        st.session_state.auth_screen = "hub"


def _do_verify(auth, email: str, code: str) -> None:
    email = (email or "").strip().lower()
    if not email:
        st.error("Enter the email you registered with.")
        return
    if _is_clerk(auth):
        ok, msg, user = auth.verify_registration(
            email,
            code,
            email_address_id=st.session_state.auth_pending_email_address_id,
        )
    else:
        ok, msg, user = auth.verify_registration(email, code)
    if ok and user:
        st.session_state.auth_flash = msg
        _after_verified_login(auth, user, onboarding=True)
        st.rerun()
    else:
        st.error(msg)


def _auth_shell(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
<div class="fx-auth-shell">
  <p class="fx-wordmark">{brand_wordmark()}</p>
  <p class="fx-kicker">{title}</p>
  <p class="fx-auth-sub">{subtitle}</p>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_verify_panel(auth, *, provider: str, title: str = "Verify your email") -> None:
    email = (st.session_state.auth_pending_email or "").strip()
    _auth_shell(title, "Enter the 6-digit code from your inbox to unlock the workspace.")
    if email:
        st.write(f"Code was sent to **{email}**.")
    st.caption(f"Auth · {provider}")

    with st.form("verify_email_form"):
        email_in = st.text_input("Email used to register", value=email)
        code = st.text_input("6-digit verification code", max_chars=8)
        col_a, col_b = st.columns(2)
        with col_a:
            verify = st.form_submit_button("Verify & continue", type="primary", use_container_width=True)
        with col_b:
            resend = st.form_submit_button("Resend code", use_container_width=True)

    if resend:
        target = (email_in or email or "").strip().lower()
        st.session_state.auth_pending_email = target
        if _is_clerk(auth):
            ok, msg, _ = auth.resend_register_otp(
                target, email_address_id=st.session_state.auth_pending_email_address_id
            )
        else:
            ok, msg = auth.resend_register_otp(target)
        (st.success if ok else st.error)(msg)

    if verify:
        _do_verify(auth, email_in or email, code)

    if st.button("Back to sign in", key="verify_back_btn"):
        st.session_state.auth_screen = "hub"
        st.rerun()


def require_login(auth=None) -> bool:
    """
    Render auth UI when not signed in. Returns True if the user may use the app.
    """
    _ensure_auth_state()
    auth = auth or get_auth_service()

    flash = (st.session_state.auth_flash or "").strip()
    if flash:
        st.success(flash)
        st.session_state.auth_flash = ""

    user = st.session_state.auth_user
    if user and user.get("email_verified"):
        email = (user.get("email") or "").strip().lower()
        store = _accounts()
        profile = store.get_profile(email)
        if not profile:
            store.ensure_profile(email, setup_complete=True)
            profile = store.get_profile(email)
        needs = st.session_state.auth_needs_onboarding or (
            profile is not None and not int(profile.get("setup_complete") or 0)
        )
        if needs or st.session_state.auth_screen == "profile_setup":
            st.session_state.auth_screen = "profile_setup"
            done = render_profile_setup(email, accounts=store, force=True)
            if done:
                st.session_state.auth_needs_onboarding = False
                st.session_state.auth_screen = "hub"
                st.rerun()
            return False
        user["is_admin"] = is_admin_email(email)
        st.session_state.auth_user = user
        return True

    provider = auth_provider_label()
    screen = (st.session_state.auth_screen or "hub").strip()

    if screen == "verify":
        _render_verify_panel(auth, provider=provider)
        return False

    if screen == "reset":
        email = (st.session_state.auth_pending_email or "").strip()
        _auth_shell("Reset password", "Enter the code, then choose a new password.")
        st.write(f"Code sent to **{email or 'your email'}**.")
        pw_hint = "New password (min 15 chars)" if _is_clerk(auth) else "New password"
        with st.form("reset_password_form"):
            code = st.text_input("6-digit code", max_chars=8)
            password = st.text_input(pw_hint, type="password")
            confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Update password", type="primary", use_container_width=True)
        if st.button("Back to sign in", key="reset_back_btn"):
            st.session_state.auth_screen = "hub"
            _clear_pending()
            st.rerun()
        if submitted:
            if _is_clerk(auth):
                ok, msg = auth.reset_password(
                    email,
                    code,
                    password,
                    confirm,
                    email_address_id=st.session_state.auth_pending_email_address_id,
                    user_id=st.session_state.auth_pending_user_id,
                )
            else:
                ok, msg = auth.reset_password(email, code, password, confirm)
            if ok:
                st.session_state.auth_screen = "hub"
                _clear_pending()
                st.session_state.auth_flash = msg
                st.rerun()
            else:
                st.error(msg)
        return False

    _auth_shell("Sign in", f"Precision research for {brand_name()} BD — register, verify, then enter the desk.")
    st.caption(f"Auth provider · **{provider}**")

    if provider == "Clerk":
        if not clerk_publishable_key():
            st.caption("Optional: set `CLERK_PUBLISHABLE_KEY` in `.env`.")
        if auth_dev_mode():
            st.info("AUTH_DEV_MODE=1 — codes are written to `output/otp_dev.log` (not emailed).")
        elif not resend_configured():
            st.warning("Set `RESEND_API_KEY` and `RESET_EMAIL_FROM` in `.env` or codes cannot be emailed.")

    with st.expander("Have a verification code?", expanded=bool(st.session_state.auth_pending_email)):
        st.caption("Use this if you already received the email OTP.")
        with st.form("hub_verify_form"):
            v_email = st.text_input(
                "Email",
                value=st.session_state.auth_pending_email or "",
                key="hub_verify_email",
            )
            v_code = st.text_input("6-digit code", max_chars=8, key="hub_verify_code")
            v_go = st.form_submit_button("Verify email", type="primary", use_container_width=True)
        if v_go:
            st.session_state.auth_pending_email = (v_email or "").strip().lower()
            _do_verify(auth, st.session_state.auth_pending_email, v_code)

    mode = st.radio(
        "Action",
        ["Log in", "Register", "Forgot password"],
        horizontal=True,
        key="auth_mode_radio",
    )

    if mode == "Log in":
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", type="primary", use_container_width=True)
        if submitted:
            ok, msg, user = auth.login(email, password)
            if ok and user:
                st.session_state.auth_flash = msg
                _after_verified_login(auth, user, onboarding=False)
                st.rerun()
            elif user and _email_unverified(user):
                _remember_pending(user, fallback_email=email)
                st.session_state.auth_screen = "verify"
                st.session_state.auth_flash = msg
                st.rerun()
            else:
                st.error(msg)

    elif mode == "Register":
        pw_hint = "Password (min 15 characters for Clerk)" if _is_clerk(auth) else "Password (min 8 characters)"
        with st.form("register_form"):
            email = st.text_input("Work email")
            password = st.text_input(pw_hint, type="password")
            confirm = st.text_input("Confirm password", type="password")
            submitted = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if submitted:
            ok, msg, user = auth.register(email, password, confirm)
            if user and _email_unverified(user):
                _remember_pending(user, fallback_email=email)
                st.session_state.auth_screen = "verify"
                st.session_state.auth_flash = msg
                st.rerun()
            elif ok and user:
                _remember_pending(user, fallback_email=email)
                st.session_state.auth_screen = "verify"
                st.session_state.auth_flash = msg
                st.rerun()
            else:
                st.error(msg or "Could not create account.")

    else:
        with st.form("forgot_form"):
            email = st.text_input("Account email")
            submitted = st.form_submit_button("Send reset code", type="primary", use_container_width=True)
        if submitted:
            if _is_clerk(auth):
                ok, msg, pending = auth.request_password_reset(email)
                if ok:
                    _remember_pending(pending, fallback_email=email)
                    st.session_state.auth_screen = "reset"
                    st.session_state.auth_flash = msg
                    st.rerun()
                else:
                    st.error(msg)
            else:
                ok, msg = auth.request_password_reset(email)
                if ok:
                    _remember_pending({"email": (email or "").strip().lower()}, fallback_email=email)
                    st.session_state.auth_screen = "reset"
                    st.session_state.auth_flash = msg
                    st.rerun()
                else:
                    st.error(msg)

    return False


def render_account_chip() -> None:
    user = current_user()
    if not user:
        return
    name_bit = ""
    try:
        profile = get_account_store().get_profile(user.get("email") or "")
        if profile and (profile.get("display_name") or "").strip():
            name_bit = f" · {profile['display_name']}"
    except Exception:
        name_bit = ""
    role = " · admin" if user.get("is_admin") or is_admin_email(user.get("email") or "") else ""
    c1, c2 = st.columns([0.78, 0.22])
    with c1:
        st.caption(f"Signed in as **{user.get('email')}**{name_bit}{role}")
    with c2:
        if st.button("Log out", use_container_width=True, key="auth_logout"):
            logout()
            st.rerun()


def render_account_sidebar(auth=None) -> None:
    render_account_chip()
