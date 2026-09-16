"""Admin console — all-user activity, per-user drill-down, purge, full exports."""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from .accounts import (
    AccountStore,
    admin_emails,
    can_manage_admins,
    get_account_store,
    mask_secret,
)
from .auth import AuthStore
from .memory import Memory, resolve_search_name
from .pipeline_ui import render_admin_pipeline
from .news_ui import render_admin_signal_panel
from .search_export import full_results_json_text, search_csv_text


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _primary_person(lead: dict) -> dict:
    contact = lead.get("contact") if isinstance(lead.get("contact"), dict) else {}
    people = [
        p
        for p in (lead.get("contacts") or [])
        if isinstance(p, dict) and (p.get("name") or "").lower() not in {"", "unknown"}
    ]
    primary = next((p for p in people if p.get("is_primary")), None)
    return primary or (people[0] if people else contact) or {}


def _lead_inspect_row(lead: dict) -> dict:
    person = _primary_person(lead)
    other_social = " | ".join(person.get("other_social") or [])
    channels = []
    for ch in person.get("channels") or []:
        if isinstance(ch, dict) and ch.get("value"):
            channels.append(f"{ch.get('kind') or 'other'}:{ch.get('value')}")
    for ch in lead.get("approach_channels") or []:
        if isinstance(ch, dict) and ch.get("value"):
            channels.append(f"co:{ch.get('kind') or 'other'}:{ch.get('value')}")
    score = lead.get("score")
    score_val = score.get("total") if isinstance(score, dict) else score
    return {
        "owner": lead.get("owner_email") or "",
        "company": lead.get("name") or lead.get("company") or "",
        "domain": lead.get("domain") or "",
        "website": lead.get("website") or "",
        "score": score_val or "",
        "contact": person.get("name") or "",
        "title": person.get("role") or "",
        "email": person.get("email") or "",
        "phone": person.get("phone") or "",
        "linkedin": person.get("linkedin_url") or "",
        "twitter": person.get("twitter_url") or "",
        "other_social": other_social,
        "best_channel": person.get("best_channel") or lead.get("best_approach_channel") or "",
        "all_channels": " | ".join(channels),
        "review": lead.get("review_status") or "",
    }


def _render_download_block(leads: list[dict], *, prefix: str, label: str) -> None:
    if not leads:
        st.caption(f"No leads to download for {label}.")
        return
    csv_text = search_csv_text(leads)
    json_text = full_results_json_text(leads)
    stamp = _stamp()
    d1, d2, d3 = st.columns([0.4, 0.3, 0.3])
    with d1:
        st.caption(f"{len(leads)} compan(ies) · full contacts (phone, email, social, channels)")
    with d2:
        st.download_button(
            "Download CSV (all contacts)",
            data=csv_text.encode("utf-8"),
            file_name=f"{prefix}-{stamp}.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"admin-dl-csv-{prefix}",
        )
    with d3:
        st.download_button(
            "Download JSON (full payloads)",
            data=json_text.encode("utf-8"),
            file_name=f"{prefix}-{stamp}.json",
            mime="application/json",
            use_container_width=True,
            key=f"admin-dl-json-{prefix}",
        )


def render_admin_page(
    *,
    memory: Memory,
    accounts: AccountStore | None = None,
    viewer_email: str = "",
) -> None:
    accounts = accounts or get_account_store(path=memory.path)
    viewer_email = (viewer_email or "").strip().lower()
    st.markdown(
        """
<div class="fx-panel-hero">
  <p class="fx-kicker">Admin</p>
  <h2>Control room</h2>
  <p>Every user’s searches, fetches, and leads — plus account tools.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    profiles = {normalize_email_safe(p.get("email")): p for p in accounts.list_profiles()}
    stats = {normalize_email_safe(s.get("email")): s for s in memory.admin_owner_stats()}
    auth_users = _list_local_auth_emails(memory.path)
    emails = sorted(set(profiles) | set(stats) | set(auth_users))

    rows = []
    for email in emails:
        p = profiles.get(email) or {}
        s = stats.get(email) or {}
        rows.append(
            {
                "email": email,
                "name": p.get("display_name") or "—",
                "designation": p.get("designation") or "—",
                "company": p.get("company") or "—",
                "admin": "yes" if accounts.is_admin(email) else "",
                "profile": "ready" if int(p.get("setup_complete") or 0) else ("empty" if p else "—"),
                "searches": int(s.get("queries") or 0),
                "leads": int(s.get("leads") or 0),
                "fetches": int(s.get("runs") or 0),
                "send_queue": int(s.get("send_queue") or 0),
                "pipeline": int(s.get("pipeline") or 0),
            }
        )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Users", len(rows))
    c2.metric("Searches", sum(r["searches"] for r in rows))
    c3.metric("Leads", sum(r["leads"] for r in rows))
    c4.metric("Fetches", sum(r["fetches"] for r in rows))
    c5.metric("Send queue", sum(r["send_queue"] for r in rows))
    c6.metric("Pipeline", sum(r["pipeline"] for r in rows))

    tab_all, tab_users, tab_monitor, tab_pipeline, tab_news = st.tabs(
        ["All activity", "Users", "Monitor user", "Pipeline", "Signal desk"]
    )

    with tab_all:
        st.markdown("##### Download all lead + contact data")
        all_leads = memory.admin_all_leads()
        _render_download_block(all_leads, prefix="frequency-all-leads", label="all accounts")
        if all_leads:
            with st.expander("Preview contact fields (first 50 companies)", expanded=False):
                st.dataframe(
                    [_lead_inspect_row(lead) for lead in all_leads[:50]],
                    use_container_width=True,
                    hide_index=True,
                )

        st.markdown("##### Every search (all accounts)")
        all_sessions = memory.admin_list_all_sessions(limit=120)
        if all_sessions:
            st.dataframe(
                [
                    {
                        "owner": s.get("owner_email") or "—",
                        "search": resolve_search_name(s),
                        "service": s.get("service_line") or "",
                        "leads": int(s.get("lead_count") or 0),
                        "updated": s.get("last_run_at") or s.get("created_at") or "",
                        "query_id": s.get("query_id") or "",
                    }
                    for s in all_sessions
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No searches stored yet.")

        st.markdown("##### Every fetch (all accounts)")
        all_runs = memory.admin_list_all_runs(limit=120)
        if all_runs:
            st.dataframe(
                [
                    {
                        "owner": r.get("owner_email") or "—",
                        "label": r.get("label") or r.get("run_id") or "",
                        "leads": int(r.get("lead_count") or 0),
                        "finished": r.get("finished") or r.get("started") or "",
                        "query_id": r.get("query_id") or "",
                        "run_id": r.get("run_id") or "",
                    }
                    for r in all_runs
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No fetches stored yet.")

    with tab_users:
        if not rows:
            st.info("No users yet.")
        else:
            st.dataframe(rows, use_container_width=True, hide_index=True)

        removable = [
            e
            for e in emails
            if e
            and e != viewer_email
            and not accounts.is_admin(e)
        ]
        st.markdown("##### Remove user")
        st.caption(
            "Any admin can remove a non-admin account and wipe their workspace data. "
            "You cannot remove yourself or other admins."
        )
        if not removable:
            st.info("No removable users right now.")
        else:
            remove_pick = st.selectbox(
                "Account to remove",
                removable,
                key="admin_users_remove_pick",
            )
            _render_remove_user_controls(
                memory,
                accounts,
                remove_pick,
                viewer_email=viewer_email,
                key_prefix="users",
            )

        if can_manage_admins(viewer_email) and emails:
            st.markdown("##### Admin access")
            st.caption(
                "Grant or remove admin for an account. Admins can monitor users, "
                "download data, and remove non-admin accounts."
            )
            grant_pick = st.selectbox(
                "Account",
                emails,
                key="admin_grant_pick",
            )
            _render_admin_access_actions(accounts, viewer_email, grant_pick, key_prefix="users")

    with tab_pipeline:
        render_admin_pipeline(memory)

    with tab_news:
        render_admin_signal_panel(memory=memory, viewer_email=viewer_email)

    with tab_monitor:
        if not emails:
            st.caption("No accounts to monitor.")
            return
        pick = st.selectbox("Account", emails, key="admin_user_pick")
        if not pick:
            return
        _render_user_monitor(
            memory, accounts, pick, profiles, stats, viewer_email=viewer_email
        )


def _render_admin_access_actions(
    accounts: AccountStore,
    viewer_email: str,
    target_email: str,
    *,
    key_prefix: str,
) -> None:
    if not can_manage_admins(viewer_email) or not target_email:
        return
    target = (target_email or "").strip().lower()
    if target in admin_emails():
        return
    is_admin = accounts.is_admin(target)
    cols = st.columns(2)
    with cols[0]:
        if st.button(
            "Make admin",
            use_container_width=True,
            disabled=is_admin,
            key=f"{key_prefix}-make-admin",
        ):
            ok, msg = accounts.grant_admin(target, actor_email=viewer_email)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()
    with cols[1]:
        if st.button(
            "Remove admin",
            use_container_width=True,
            disabled=not accounts.has_admin_grant(target),
            key=f"{key_prefix}-remove-admin",
        ):
            ok, msg = accounts.revoke_admin(target, actor_email=viewer_email)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()


def _render_user_monitor(
    memory: Memory,
    accounts: AccountStore,
    pick: str,
    profiles: dict,
    stats: dict,
    *,
    viewer_email: str = "",
) -> None:
    p = profiles.get(pick) or accounts.ensure_profile(pick, setup_complete=True)
    s = stats.get(pick) or {"queries": 0, "leads": 0, "runs": 0, "send_queue": 0, "pipeline": 0}
    keys = accounts.get_api_keys(pick)
    st.markdown(
        f"""
<div class="fx-card-block">
  <p><strong>{pick}</strong></p>
  <p>{p.get('display_name') or 'No name'} · {p.get('designation') or 'No designation'} · {p.get('company') or 'No company'}</p>
  <p>Workspace: {s.get('queries', 0)} searches · {s.get('leads', 0)} leads · {s.get('runs', 0)} fetches · {s.get('send_queue', 0)} queue · {s.get('pipeline', 0)} pipeline</p>
  <p>Tavily key: {mask_secret(keys.get('tavily_key') or '') or 'not set'}</p>
</div>
""",
        unsafe_allow_html=True,
    )

    user_leads = memory.admin_all_leads(owner_email=pick)
    st.markdown("##### Download this user’s full contact data")
    safe_email = "".join(ch if ch.isalnum() else "-" for ch in pick)[:40]
    _render_download_block(
        user_leads,
        prefix=f"frequency-{safe_email}",
        label=pick,
    )

    sessions = memory.admin_list_sessions(pick, limit=40)
    fetches = memory.admin_list_runs(pick, limit=40)
    queue = memory.admin_send_queue(pick)

    tab_searches, tab_fetches, tab_inspect, tab_queue, tab_pipe = st.tabs(
        ["Searches", "Fetches", "Inspect results", "Send queue", "Pipeline"]
    )

    with tab_searches:
        if sessions:
            st.dataframe(
                [
                    {
                        "search": resolve_search_name(s),
                        "service": s.get("service_line") or "",
                        "leads": int(s.get("lead_count") or 0),
                        "updated": s.get("last_run_at") or s.get("created_at") or "",
                        "query_id": s.get("query_id") or "",
                    }
                    for s in sessions
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No searches for this account.")

    with tab_fetches:
        if fetches:
            st.dataframe(
                [
                    {
                        "label": f.get("label") or f.get("run_id") or "",
                        "leads": int(f.get("lead_count") or 0),
                        "finished": f.get("finished") or f.get("started") or "",
                        "query_id": f.get("query_id") or "",
                        "run_id": f.get("run_id") or "",
                    }
                    for f in fetches
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No fetches for this account.")

    with tab_inspect:
        if not sessions and not fetches:
            st.caption("Nothing to inspect yet.")
        else:
            search_options = {
                resolve_search_name(s) + f" · {s.get('query_id')}": s.get("query_id")
                for s in sessions
            }
            q_pick = st.selectbox(
                "Search",
                ["(pick a search)"] + list(search_options.keys()),
                key="admin_inspect_search",
            )
            qid = search_options.get(q_pick) if q_pick and q_pick != "(pick a search)" else ""
            if qid:
                q_runs = memory.admin_list_runs_for_query(pick, qid)
                q_leads = memory.admin_leads_for_query(pick, qid)
                for lead in q_leads:
                    lead.setdefault("owner_email", pick)
                st.caption(
                    f"{len(q_runs)} fetch(es) · {len(q_leads)} lead(s) linked to this search"
                )
                if q_runs:
                    st.markdown("**Fetches for this search**")
                    st.dataframe(
                        [
                            {
                                "label": r.get("label") or r.get("run_id"),
                                "leads": int(r.get("lead_count") or 0),
                                "finished": r.get("finished") or "",
                                "run_id": r.get("run_id") or "",
                            }
                            for r in q_runs
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                run_labels = {
                    (r.get("label") or r.get("run_id") or ""): r.get("run_id") for r in q_runs
                }
                run_pick = st.selectbox(
                    "Open a fetch",
                    ["(all linked leads)"] + list(run_labels.keys()),
                    key="admin_inspect_run",
                )
                if run_pick and run_pick != "(all linked leads)":
                    loaded = memory.admin_load_run(pick, run_labels[run_pick])
                    lead_rows = (loaded or {}).get("leads") or []
                    for lead in lead_rows:
                        lead.setdefault("owner_email", pick)
                    st.caption(
                        f"Fetch {(loaded or {}).get('run_id') or ''} · {len(lead_rows)} companies"
                    )
                else:
                    lead_rows = q_leads
                if lead_rows:
                    _render_download_block(
                        lead_rows,
                        prefix=f"frequency-inspect-{qid[:10]}",
                        label="this selection",
                    )
                    st.dataframe(
                        [_lead_inspect_row(lead) for lead in lead_rows[:200]],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("No leads for this selection.")

    with tab_queue:
        if queue:
            st.dataframe(
                [
                    {
                        "company": q.get("company") or "",
                        "channel": q.get("channel") or "",
                        "recipient": q.get("recipient") or "",
                        "status": q.get("status") or "",
                        "queued_at": q.get("queued_at") or "",
                    }
                    for q in queue
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Send queue empty for this account.")

    with tab_pipe:
        user_pipe = memory.admin_list_pipeline(pick)
        if user_pipe:
            st.dataframe(
                [
                    {
                        "company": p.get("company") or "",
                        "person": p.get("person_name") or "",
                        "status": p.get("pipeline_status") or "",
                        "comment": p.get("comment") or "",
                        "icp": (p.get("search_name") or p.get("icp_text") or "")[:80],
                        "entity": p.get("company_entity_id") or "",
                        "updated": p.get("updated_at") or "",
                    }
                    for p in user_pipe
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No pipeline items for this account.")

    if can_manage_admins(viewer_email):
        st.markdown("##### Admin access")
        _render_admin_access_actions(accounts, viewer_email, pick, key_prefix="monitor")

    st.markdown("##### Remove user")
    _render_remove_user_controls(
        memory,
        accounts,
        pick,
        viewer_email=viewer_email,
        key_prefix="monitor",
    )


def _remove_user_fully(
    memory: Memory,
    accounts: AccountStore,
    target_email: str,
    *,
    actor_email: str,
) -> tuple[bool, str]:
    ok, msg = accounts.can_remove_user(target_email, actor_email=actor_email)
    if not ok:
        return False, msg
    target = (target_email or "").strip().lower()
    memory.admin_purge_owner(target)
    ok, msg = accounts.remove_user(target, actor_email=actor_email)
    if not ok:
        return False, msg
    AuthStore(path=memory.path).delete_user(target)
    return True, f"Removed {target} and purged workspace data."


def _render_remove_user_controls(
    memory: Memory,
    accounts: AccountStore,
    target_email: str,
    *,
    viewer_email: str,
    key_prefix: str,
) -> None:
    target = (target_email or "").strip().lower()
    if not target:
        return
    ok, reason = accounts.can_remove_user(target, actor_email=viewer_email)
    if not ok:
        st.info(reason)
        return
    confirm = st.text_input(
        f"Type the email to confirm removal of {target}",
        key=f"{key_prefix}-delete-confirm",
    )
    if st.button(
        "Remove user + wipe their data",
        type="primary",
        key=f"{key_prefix}-delete-btn",
        use_container_width=True,
    ):
        if (confirm or "").strip().lower() != target:
            st.error("Confirmation email does not match.")
        else:
            done, msg = _remove_user_fully(
                memory, accounts, target, actor_email=viewer_email
            )
            (st.success if done else st.error)(msg)
            if done:
                st.rerun()


def normalize_email_safe(email: str | None) -> str:
    return (email or "").strip().lower()


def _list_local_auth_emails(db_path) -> list[str]:
    try:
        store = AuthStore(path=db_path)
        with store._connect() as conn:
            rows = conn.execute("SELECT email FROM users ORDER BY email").fetchall()
        return [(r["email"] or "").strip().lower() for r in rows if r["email"]]
    except Exception:
        return []
