"""Durable auth session tokens for Streamlit (survive browser refresh).

Primary store: ``?fx_session=`` query param (same pattern as ``?theme=``).
Best-effort: browser cookie ``fx_session`` via JS (readable on next load with
``st.context.cookies``).

Token is HMAC-signed (email, user_id, provider, email_verified, expiry).
No passwords are stored in the token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

SESSION_COOKIE_NAME = "fx_session"
SESSION_QUERY_PARAM = "fx_session"
DEFAULT_TTL_DAYS = 21
DEFAULT_TTL_SECONDS = DEFAULT_TTL_DAYS * 24 * 60 * 60


def _session_secret() -> bytes:
    secret = (
        (os.getenv("AUTH_SESSION_SECRET") or "").strip()
        or (os.getenv("FREQUENCY_SECRETS_KEY") or "").strip()
        or (os.getenv("CLERK_SECRET_KEY") or "").strip()
        or "frequency-dev-auth-session-change-me"
    )
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + pad).encode("ascii"))


def issue_session_token(
    user: dict[str, Any],
    *,
    ttl_seconds: int | None = None,
    now: int | None = None,
) -> str:
    """Build a signed session token for a verified auth user dict."""
    email = (user.get("email") or "").strip().lower()
    if not email:
        raise ValueError("session token requires email")
    user_id = str(user.get("user_id") or "").strip()
    provider = str(user.get("provider") or "local").strip() or "local"
    verified = bool(user.get("email_verified"))
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
    if ttl <= 0:
        raise ValueError("ttl_seconds must be positive")
    exp = int(now if now is not None else time.time()) + ttl
    payload = {
        "v": 1,
        "email": email,
        "user_id": user_id,
        "provider": provider,
        "email_verified": verified,
        "exp": exp,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _b64url_encode(hmac.new(_session_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session_token(
    token: str | None,
    *,
    now: int | None = None,
) -> dict[str, Any] | None:
    """Validate token signature + expiry. Returns user fields or None."""
    raw = (token or "").strip()
    if not raw or raw.count(".") != 1:
        return None
    body, sig = raw.split(".", 1)
    if not body or not sig:
        return None
    expected = _b64url_encode(hmac.new(_session_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or int(payload.get("v") or 0) != 1:
        return None
    try:
        exp = int(payload.get("exp"))
    except (TypeError, ValueError):
        return None
    ts = int(now if now is not None else time.time())
    if exp < ts:
        return None
    email = (payload.get("email") or "").strip().lower()
    if not email:
        return None
    if not bool(payload.get("email_verified")):
        return None
    return {
        "email": email,
        "user_id": str(payload.get("user_id") or "").strip(),
        "provider": str(payload.get("provider") or "local").strip() or "local",
        "email_verified": True,
    }


def _query_param_value(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else ""
    return str(raw or "").strip()


def read_session_token_candidates() -> list[str]:
    """Collect fx_session values from query param then cookie (deduped).

    Query param is primary (tab-local URL identity). Cookie is a browser-wide
    fallback for cold loads without ``?fx_session=``. Preferring the query
    token avoids one tab's login clobbering another tab's identity on refresh
    when both tabs still carry their own signed ``fx_session`` in the URL.
    """
    found: list[str] = []
    try:
        import streamlit as st

        qp = _query_param_value(st.query_params.get(SESSION_QUERY_PARAM))
        if qp:
            found.append(qp)
        cookies = getattr(getattr(st, "context", None), "cookies", None)
        if cookies is not None:
            cookie_val = str(cookies.get(SESSION_COOKIE_NAME) or "").strip()
            if cookie_val and cookie_val not in found:
                found.append(cookie_val)
    except Exception:
        pass
    return found


def read_session_token_from_request() -> str:
    """Return the first valid fx_session token (query preferred, then cookie)."""
    for token in read_session_token_candidates():
        if verify_session_token(token) is not None:
            return token
    return ""


def _inject_browser_cookie(token: str | None, *, max_age_seconds: int) -> None:
    """Best-effort Set-Cookie via JS on the parent document (iframe-safe)."""
    try:
        import streamlit.components.v1 as components
    except Exception:
        return
    name = SESSION_COOKIE_NAME
    if token:
        # Token is urlsafe base64 + '.'; only — still escape for JS string safety.
        safe = token.replace("\\", "\\\\").replace('"', "")
        script = f"""
<script>
(function() {{
  try {{
    var d = (window.parent && window.parent.document) ? window.parent.document : document;
    var v = encodeURIComponent("{safe}");
    d.cookie = "{name}=" + v + "; path=/; max-age={int(max_age_seconds)}; SameSite=Lax";
    if (window.location && window.location.protocol === "https:") {{
      d.cookie = "{name}=" + v + "; path=/; max-age={int(max_age_seconds)}; SameSite=Lax; Secure";
    }}
  }} catch (e) {{}}
}})();
</script>
"""
    else:
        # Expire on both HTTP and HTTPS variants — logout must not leave a readable cookie.
        script = f"""
<script>
(function() {{
  try {{
    var d = (window.parent && window.parent.document) ? window.parent.document : document;
    var expired = "{name}=; path=/; max-age=0; SameSite=Lax; expires=Thu, 01 Jan 1970 00:00:01 GMT";
    d.cookie = expired;
    d.cookie = expired + "; Secure";
  }} catch (e) {{}}
}})();
</script>
"""
    try:
        components.html(script, height=0, width=0)
    except Exception:
        pass


def persist_auth_session(user: dict[str, Any], *, ttl_seconds: int | None = None) -> str | None:
    """Write signed token to query params + browser cookie. Returns token or None."""
    if not user or not user.get("email_verified"):
        return None
    token = issue_session_token(user, ttl_seconds=ttl_seconds)
    ttl = DEFAULT_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
    try:
        import streamlit as st

        st.query_params[SESSION_QUERY_PARAM] = token
        st.session_state.pop("_auth_block_restore", None)
        st.session_state.pop("_auth_need_cookie_clear", None)
    except Exception:
        pass
    _inject_browser_cookie(token, max_age_seconds=ttl)
    try:
        import streamlit as st

        st.session_state["_fx_session_cookie_pushed"] = True
    except Exception:
        pass
    return token


def clear_auth_session(*, clear_cookie: bool = True) -> None:
    """Remove durable session from query params (+ optionally browser cookie)."""
    try:
        import streamlit as st

        if SESSION_QUERY_PARAM in st.query_params:
            del st.query_params[SESSION_QUERY_PARAM]
        st.session_state.pop("_fx_session_cookie_pushed", None)
    except Exception:
        pass
    if clear_cookie:
        _inject_browser_cookie(None, max_age_seconds=0)


def restore_auth_user(*, is_admin_email=None) -> dict[str, Any] | None:
    """
    If a valid fx_session token is present, return an auth_user dict.
    Re-syncs query param / cookie when one side is missing.
    """
    token = read_session_token_from_request()
    user = verify_session_token(token)
    if not user:
        return None
    if is_admin_email is not None:
        user["is_admin"] = bool(is_admin_email(user.get("email") or ""))
    else:
        user["is_admin"] = False
    user["email_address_id"] = ""

    # Keep query param in sync (like theme) when cookie-only restore happened.
    try:
        import streamlit as st

        qp = _query_param_value(st.query_params.get(SESSION_QUERY_PARAM))
        if qp != token:
            st.query_params[SESSION_QUERY_PARAM] = token
        if not st.session_state.get("_fx_session_cookie_pushed"):
            remaining = DEFAULT_TTL_SECONDS
            try:
                body = token.split(".", 1)[0]
                payload = json.loads(_b64url_decode(body).decode("utf-8"))
                remaining = max(60, int(payload.get("exp") or 0) - int(time.time()))
            except Exception:
                remaining = DEFAULT_TTL_SECONDS
            _inject_browser_cookie(token, max_age_seconds=remaining)
            st.session_state["_fx_session_cookie_pushed"] = True
    except Exception:
        pass
    return user
