"""Profile + per-user API key settings screens."""

from __future__ import annotations

import streamlit as st

from .accounts import AccountStore, get_account_store
from .branding import brand_name


def render_profile_setup(
    email: str,
    *,
    accounts: AccountStore | None = None,
    force: bool = True,
) -> bool:
    """
    Collect profile fields. Returns True when setup is finished for this session.
    When force=True (post-registration), skip is allowed but marks complete.
    """
    accounts = accounts or get_account_store()
    email = (email or "").strip().lower()
    profile = accounts.ensure_profile(email, setup_complete=False)

    st.markdown(
        f"""
<div class="fx-panel-hero">
  <p class="fx-kicker">Welcome</p>
  <h2>Set up your profile</h2>
  <p>Tell {brand_name()} who you are. You can refine this anytime from Profile.</p>
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption(f"Signed in as {email}")

    with st.form("profile_setup_form"):
        name = st.text_input("Full name", value=profile.get("display_name") or "")
        designation = st.text_input(
            "Designation / title",
            value=profile.get("designation") or "",
            placeholder="e.g. Principal, BD Lead",
        )
        company = st.text_input("Company / practice", value=profile.get("company") or "")
        phone = st.text_input("Work phone", value=profile.get("phone") or "")
        linkedin = st.text_input("LinkedIn URL", value=profile.get("linkedin_url") or "")
        notes = st.text_area(
            "Work notes (sectors, regions, preferences)",
            value=profile.get("work_notes") or "",
            height=100,
        )
        col_a, col_b = st.columns(2)
        with col_a:
            save = st.form_submit_button("Save & continue", type="primary", use_container_width=True)
        with col_b:
            skip = st.form_submit_button("Skip for now", use_container_width=True)

    if save or skip:
        accounts.upsert_profile(
            email,
            display_name=name if save else (profile.get("display_name") or ""),
            designation=designation if save else (profile.get("designation") or ""),
            company=company if save else (profile.get("company") or ""),
            phone=phone if save else (profile.get("phone") or ""),
            linkedin_url=linkedin if save else (profile.get("linkedin_url") or ""),
            work_notes=notes if save else (profile.get("work_notes") or ""),
            setup_complete=True,
        )
        st.session_state.auth_flash = "Profile ready." if save else "You can finish your profile later."
        return True
    return False


def render_settings_page(
    email: str,
    *,
    accounts: AccountStore | None = None,
) -> None:
    accounts = accounts or get_account_store()
    email = (email or "").strip().lower()
    profile = accounts.ensure_profile(email, setup_complete=True)

    st.markdown(
        """
<div class="fx-panel-hero">
  <p class="fx-kicker">Account</p>
  <h2>Profile &amp; search key</h2>
  <p>Add your Tavily key for web search.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    tab_profile, tab_keys = st.tabs(["Profile", "Tavily API key"])

    with tab_profile:
        with st.form("settings_profile_form"):
            name = st.text_input("Full name", value=profile.get("display_name") or "")
            designation = st.text_input("Designation / title", value=profile.get("designation") or "")
            company = st.text_input("Company / practice", value=profile.get("company") or "")
            phone = st.text_input("Work phone", value=profile.get("phone") or "")
            linkedin = st.text_input("LinkedIn URL", value=profile.get("linkedin_url") or "")
            notes = st.text_area(
                "Work notes",
                value=profile.get("work_notes") or "",
                height=110,
            )
            if st.form_submit_button("Save profile", type="primary", use_container_width=True):
                accounts.upsert_profile(
                    email,
                    display_name=name,
                    designation=designation,
                    company=company,
                    phone=phone,
                    linkedin_url=linkedin,
                    work_notes=notes,
                    setup_complete=True,
                )
                st.success("Profile updated.")
                st.rerun()

    with tab_keys:
        stored_keys = accounts.get_api_keys(email)
        current_tavily = (stored_keys.get("tavily_key") or "").strip()

        st.markdown(
            """
<div class="fx-card-block">
  <p><strong>Current Tavily key on your account</strong></p>
  <p>Always visible here so you can copy it anytime after login. Only this key is used for your searches — never another user’s, and never a shared server key.</p>
</div>
""",
            unsafe_allow_html=True,
        )

        if current_tavily:
            st.text_input(
                "Saved Tavily API key",
                value=current_tavily,
                key="settings_current_tavily_display",
                help="Fully visible — select and copy anytime.",
            )
            st.code(current_tavily, language=None)
        else:
            st.warning("No Tavily key on your account yet — add one below for better web search.")

        with st.form("settings_keys_form"):
            tavily_in = st.text_input(
                "New Tavily API key",
                type="password",
                placeholder="tvly-… (leave blank to keep the current key)",
                help="Stored encrypted for your account only. Used for web search for you alone.",
            )
            clear_tavily = st.checkbox("Clear my Tavily key")
            if st.form_submit_button("Save Tavily key", type="primary", use_container_width=True):
                accounts.save_api_keys(
                    email,
                    tavily_key=tavily_in or None,
                    clear_tavily=clear_tavily,
                )
                st.success("Tavily key saved for your account only.")
                st.rerun()
