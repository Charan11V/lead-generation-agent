"""Centralised shared queue repository — spreadsheet view across all users."""

from __future__ import annotations

import html
import re
from typing import Any

import streamlit as st

from .memory import Memory, resolve_search_name
from .outreach_queue import bundle_from_any, enrich_queue_bundle, format_contacts_line
from .pipeline_ui import (
    pipeline_detail_html,
    render_status_stepper,
)
from .similarity import (
    PIPELINE_STATUS_LABELS,
    clean_domain,
    find_similar,
    identity_from_pipeline,
    normalize_pipeline_status,
    status_label,
)
from .ui import detail_html, empty_state_html
from .util import normalize_name

# Stable, distinct chips for owners (not purple-glow AI defaults).
_OWNER_PALETTE = (
    ("#1f6f5b", "#e7f5f0"),
    ("#8a4b1f", "#f8eee4"),
    ("#1d4f7c", "#e7f0f8"),
    ("#6b3d6e", "#f4eaf5"),
    ("#5c6b1d", "#f2f5e6"),
    ("#7a2f3a", "#f8e9ec"),
    ("#2f5f6b", "#e6f3f5"),
    ("#6b531d", "#f6f0e4"),
    ("#3d5a80", "#e9eef5"),
    ("#4a6741", "#eaf2e8"),
)

_PAGE_SIZE = 50


def _esc(text: str) -> str:
    return html.escape(text or "")


def _clip(text: str, n: int = 80) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if len(raw) <= n:
        return raw
    return raw[:n].rstrip() + "…"


def open_central_repo(*, focus_pipeline_id: int | None = None, open_id: int | None = None) -> None:
    """Navigate to the shared queue spreadsheet, optionally focused on a similar cluster."""
    st.session_state.page_view = "central"
    if focus_pipeline_id:
        st.session_state.central_focus_id = int(focus_pipeline_id)
        st.session_state.central_open_id = int(open_id or focus_pipeline_id)
    else:
        st.session_state.central_focus_id = int(st.session_state.get("central_focus_id") or 0)
    st.session_state.central_page = 0


def owner_style(email: str) -> tuple[str, str]:
    email = (email or "").strip().lower() or "unknown"
    idx = sum(ord(c) for c in email) % len(_OWNER_PALETTE)
    return _OWNER_PALETTE[idx]


def owner_chip_html(email: str, display_name: str = "") -> str:
    fg, bg = owner_style(email)
    label = (display_name or "").strip()
    text = f"{label} · {email}" if label and label.lower() != email else email
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'background:{bg};color:{fg};font-size:12px;font-weight:600;'
        f'border:1px solid {fg}33;">{_esc(text)}</span>'
    )


def _profiles_map(accounts) -> dict[str, dict]:
    if accounts is None:
        return {}
    try:
        return {
            (p.get("email") or "").strip().lower(): p
            for p in accounts.list_profiles()
        }
    except Exception:
        return {}


def _display_name(email: str, profiles: dict[str, dict]) -> str:
    p = profiles.get((email or "").strip().lower()) or {}
    return (p.get("display_name") or "").strip()


def _enrich_light(item: dict, *, profiles: dict[str, dict], similar_n: int = 0) -> dict[str, Any]:
    email = (item.get("owner_email") or "").strip().lower()
    name = _display_name(email, profiles)
    status = normalize_pipeline_status(item.get("pipeline_status") or "queued")
    search = (item.get("search_name") or "").strip() or resolve_search_name(
        {"label": "", "icp_text": item.get("icp_text") or ""}
    )
    return {
        **item,
        "owner_email": email,
        "owner_name": name,
        "owner_label": f"{name} · {email}" if name else email,
        "status_code": status,
        "status_label": status_label(status),
        "search_label": search or _clip(item.get("icp_text") or "", 60),
        "similar_n": similar_n,
        "people_line": item.get("person_name") or item.get("person_role") or "—",
        "queued_at": (item.get("created_at") or item.get("updated_at") or "")[:19].replace("T", " "),
        "updated_short": (item.get("updated_at") or "")[:19].replace("T", " "),
    }


def _dup_keys(team_light: list[dict]) -> set[int]:
    """Pipeline ids that share company identity with at least one other row (fast prefilter)."""
    buckets: dict[str, list[int]] = {}
    for r in team_light:
        rid = int(r.get("id") or 0)
        eid = (r.get("company_entity_id") or "").strip()
        dom = clean_domain(r.get("domain"))
        name = normalize_name(r.get("company") or "")
        key = eid or (f"d:{dom}" if dom else "") or (f"n:{name}" if name else f"id:{rid}")
        buckets.setdefault(key, []).append(rid)
    out: set[int] = set()
    for ids in buckets.values():
        if len(ids) > 1:
            out.update(ids)
    return out


def _cluster_ids(focus_id: int, team: list[dict]) -> set[int]:
    if not focus_id:
        return set()
    anchor = next((i for i in team if int(i.get("id") or 0) == focus_id), None)
    if not anchor:
        return {focus_id}
    hits = find_similar(
        identity_from_pipeline(anchor),
        team,
        exclude_pipeline_id=None,
    )
    ids = {int(anchor["id"])}
    for h in hits:
        try:
            ids.add(int(h["id"]))
        except (TypeError, ValueError):
            pass
    return ids


def _apply_filters(
    rows: list[dict],
    *,
    q: str,
    owners: list[str],
    statuses: list[str],
    search_names: list[str],
    similar_only: bool,
    open_only: bool,
    date_from: str,
    date_to: str,
    focus_ids: set[int],
    focus_only: bool,
) -> list[dict]:
    q = (q or "").strip().lower()
    out = []
    for r in rows:
        rid = int(r.get("id") or 0)
        if focus_only and focus_ids and rid not in focus_ids:
            continue
        if owners and (r.get("owner_email") or "") not in owners:
            continue
        if statuses and (r.get("status_code") or "") not in statuses:
            continue
        if search_names:
            sl = (r.get("search_label") or "").strip()
            if sl not in search_names:
                continue
        if similar_only and int(r.get("similar_n") or 0) <= 0 and rid not in focus_ids:
            # Will recompute similar_n after; skip soft filter here if unknown
            pass
        if open_only and (r.get("status_code") or "") in {"success", "failure"}:
            continue
        when = (r.get("queued_at") or r.get("updated_short") or "")[:10]
        if date_from and when and when < date_from:
            continue
        if date_to and when and when > date_to:
            continue
        if q:
            blob = " ".join(
                [
                    r.get("company") or "",
                    r.get("domain") or "",
                    r.get("people_line") or "",
                    r.get("owner_email") or "",
                    r.get("owner_name") or "",
                    r.get("search_label") or "",
                    r.get("icp_text") or "",
                    r.get("status_label") or "",
                    r.get("comment") or "",
                ]
            ).lower()
            if q not in blob:
                continue
        out.append(r)
    return out


def _attach_similar_counts(rows: list[dict], team: list[dict]) -> list[dict]:
    """Compute similar counts only for the visible page (keeps large repos usable)."""
    out = []
    for r in rows:
        try:
            hits = find_similar(
                identity_from_pipeline(r),
                team,
                exclude_pipeline_id=int(r["id"]),
            )
            n = len(hits)
        except Exception:
            n = 0
        out.append({**r, "similar_n": n})
    return out


def _load_detail_bundle(memory: Memory, item: dict) -> tuple[dict, dict | None]:
    bundle: dict = {}
    lead = None
    qid = item.get("send_queue_id")
    row = None
    if qid:
        try:
            # Admin-scoped: send queue is owner-scoped; try via admin helper or direct.
            row = memory.get_send_queue_item(int(qid))
        except Exception:
            row = None
        if row is None:
            try:
                owner = (item.get("owner_email") or "").strip().lower()
                if owner:
                    rows = memory.admin_send_queue(owner)
                    row = next((x for x in rows if int(x.get("id") or 0) == int(qid)), None)
            except Exception:
                row = None
        if row:
            bundle = bundle_from_any(row) or {}
    lead_id = (item.get("lead_id") or (row or {}).get("lead_id") or "").strip()
    if lead_id:
        try:
            owner = (item.get("owner_email") or "").strip().lower()
            if owner:
                # Cross-owner lead load via unscoped / admin path
                scoped = memory._admin_scoped(owner)
                lead = scoped.get_lead(lead_id)
            else:
                lead = memory.get_lead(lead_id)
        except Exception:
            lead = None
    bundle = enrich_queue_bundle(bundle, lead=lead, pipeline_item=item)
    return bundle, lead


def render_central_repo_page(
    *,
    memory: Memory,
    accounts=None,
    viewer_email: str = "",
    is_admin: bool = False,
) -> None:
    profiles = _profiles_map(accounts)
    team = memory.list_team_pipeline()
    focus_id = int(st.session_state.get("central_focus_id") or 0)
    focus_ids = _cluster_ids(focus_id, team)

    st.markdown(
        """
<div class="fx-panel-hero">
  <p class="fx-kicker">Shared queue</p>
  <h2>Central repository</h2>
  <p>Every queued company across the team — filter, search, and open full detail with shortlisted messages.</p>
</div>
""",
        unsafe_allow_html=True,
    )

    if not team:
        st.markdown(
            empty_state_html(
                "No shared queue items yet",
                "When anyone queues a company from Results, it appears here for the whole team.",
            ),
            unsafe_allow_html=True,
        )
        return

    light = [_enrich_light(i, profiles=profiles) for i in team]
    dup_ids = _dup_keys(light)

    # Legend
    owners_sorted = sorted({r["owner_email"] for r in light if r.get("owner_email")})
    legend_bits = []
    for email in owners_sorted[:12]:
        legend_bits.append(owner_chip_html(email, _display_name(email, profiles)))
    if legend_bits:
        st.markdown(
            '<p class="fx-muted" style="margin:0 0 8px">Owners</p>'
            + " ".join(legend_bits)
            + (f' <span class="fx-muted">+{len(owners_sorted) - 12} more</span>' if len(owners_sorted) > 12 else ""),
            unsafe_allow_html=True,
        )

    if focus_id and focus_ids:
        anchor = next((r for r in light if int(r.get("id") or 0) == focus_id), None)
        co = (anchor or {}).get("company") or "this company"
        c1, c2 = st.columns([0.78, 0.22])
        with c1:
            st.warning(
                f"Focused on {len(focus_ids)} similar record(s) for **{co}** — "
                "other users’ work and your own matches are highlighted below."
            )
        with c2:
            if st.button("Clear focus", use_container_width=True, key="central-clear-focus"):
                st.session_state.central_focus_id = 0
                st.rerun()

    # Filters
    st.markdown("##### Filters")
    f1, f2, f3, f4 = st.columns([0.34, 0.22, 0.22, 0.22])
    with f1:
        q = st.text_input(
            "Search",
            placeholder="Company, person, domain, owner, search…",
            key="central-q",
        )
    with f2:
        owner_opts = owners_sorted
        owners = st.multiselect(
            "Owner",
            owner_opts,
            format_func=lambda e: _display_name(e, profiles) or e,
            key="central-owners",
        )
    with f3:
        status_opts = list(PIPELINE_STATUS_LABELS.keys())
        statuses = st.multiselect(
            "Status",
            status_opts,
            format_func=lambda s: PIPELINE_STATUS_LABELS.get(s, s),
            key="central-statuses",
        )
    with f4:
        search_opts = sorted(
            {r.get("search_label") or "" for r in light if (r.get("search_label") or "").strip()}
        )
        search_names = st.multiselect("Search / ICP", search_opts, key="central-searches")

    f5, f6, f7, f8 = st.columns(4)
    with f5:
        open_only = st.checkbox("Open only (hide closed)", value=True, key="central-open-only")
    with f6:
        similar_only = st.checkbox("Has similar only", value=False, key="central-sim-only")
    with f7:
        focus_only = st.checkbox(
            "Focus cluster only",
            value=bool(focus_ids),
            key="central-focus-only",
            disabled=not bool(focus_ids),
        )
    with f8:
        date_from = st.text_input("Queued from (YYYY-MM-DD)", key="central-from", placeholder="optional")
    date_to = st.text_input("Queued to (YYYY-MM-DD)", key="central-to", placeholder="optional")

    filtered = _apply_filters(
        light,
        q=q,
        owners=owners,
        statuses=statuses,
        search_names=search_names,
        similar_only=False,
        open_only=open_only,
        date_from=(date_from or "").strip(),
        date_to=(date_to or "").strip(),
        focus_ids=focus_ids,
        focus_only=bool(focus_only and focus_ids),
    )
    if similar_only:
        filtered = [
            r
            for r in filtered
            if int(r.get("id") or 0) in dup_ids or int(r.get("id") or 0) in focus_ids
        ]

    # Sort: focus cluster first, then updated desc
    def _sort_key(r: dict):
        rid = int(r.get("id") or 0)
        in_focus = 0 if (focus_ids and rid in focus_ids) else 1
        return (in_focus, r.get("updated_at") or r.get("created_at") or "", -(rid))

    filtered.sort(key=_sort_key)

    total = len(filtered)
    page = int(st.session_state.get("central_page") or 0)
    max_page = max(0, (total - 1) // _PAGE_SIZE)
    page = min(page, max_page)
    st.session_state.central_page = page
    start = page * _PAGE_SIZE
    page_rows = filtered[start : start + _PAGE_SIZE]
    page_rows = _attach_similar_counts(page_rows, team)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Showing", len(page_rows))
    m2.metric("Matched filters", total)
    m3.metric("Team total", len(team))
    m4.metric("Focus cluster", len(focus_ids) if focus_ids else 0)

    nav_l, nav_m, nav_r = st.columns([0.2, 0.6, 0.2])
    with nav_l:
        if st.button("← Prev", disabled=page <= 0, use_container_width=True, key="central-prev"):
            st.session_state.central_page = max(0, page - 1)
            st.rerun()
    with nav_m:
        st.caption(f"Page {page + 1} of {max_page + 1} · {_PAGE_SIZE} rows per page")
    with nav_r:
        if st.button("Next →", disabled=page >= max_page, use_container_width=True, key="central-next"):
            st.session_state.central_page = min(max_page, page + 1)
            st.rerun()

    # Spreadsheet
    table_rows = []
    for r in page_rows:
        rid = int(r.get("id") or 0)
        star = "★ " if focus_ids and rid in focus_ids else ""
        table_rows.append(
            {
                " ": star.strip() or ("·" if (r.get("owner_email") or "") == (viewer_email or "").lower() else ""),
                "Owner": r.get("owner_label") or r.get("owner_email") or "",
                "Company": r.get("company") or "",
                "Domain": r.get("domain") or "",
                "People": _clip(r.get("people_line") or "", 40),
                "Search": _clip(r.get("search_label") or "", 36),
                "Status": r.get("status_label") or "",
                "Similar": int(r.get("similar_n") or 0),
                "Updated": r.get("updated_short") or r.get("queued_at") or "",
                "ID": rid,
            }
        )

    st.dataframe(table_rows, use_container_width=True, hide_index=True, height=min(520, 48 + 36 * max(len(table_rows), 1)))

    # Row picker + cluster actions
    if not page_rows:
        st.info("No rows match these filters.")
        return

    labels = {
        int(r["id"]): (
            f"{'★ ' if focus_ids and int(r['id']) in focus_ids else ''}"
            f"{r.get('company') or '—'} · {r.get('owner_label') or r.get('owner_email')} · "
            f"{r.get('status_label')} · #{r.get('id')}"
        )
        for r in page_rows
    }
    default_open = int(st.session_state.get("central_open_id") or 0)
    id_list = list(labels.keys())
    if default_open not in id_list:
        # Prefer a focus id on this page
        pick_default = next((i for i in id_list if i in focus_ids), id_list[0])
    else:
        pick_default = default_open
    pick = st.selectbox(
        "Open record",
        id_list,
        index=id_list.index(pick_default),
        format_func=lambda i: labels.get(i, str(i)),
        key="central-pick",
    )
    st.session_state.central_open_id = int(pick)
    chosen = next(r for r in page_rows if int(r["id"]) == int(pick))

    a1, a2, a3 = st.columns(3)
    with a1:
        if st.button("Focus similar cluster", use_container_width=True, key="central-focus-btn"):
            st.session_state.central_focus_id = int(chosen["id"])
            st.session_state.central_page = 0
            st.rerun()
    with a2:
        sim_n = int(chosen.get("similar_n") or 0)
        st.caption(f"{sim_n} similar elsewhere" if sim_n else "No similar matches on this page scan")
    with a3:
        st.markdown(
            owner_chip_html(chosen.get("owner_email") or "", chosen.get("owner_name") or ""),
            unsafe_allow_html=True,
        )

    _render_central_detail(
        memory,
        chosen,
        team=team,
        profiles=profiles,
        viewer_email=viewer_email,
        is_admin=is_admin,
        focus_ids=focus_ids,
    )


def _render_central_detail(
    memory: Memory,
    item: dict,
    *,
    team: list[dict],
    profiles: dict[str, dict],
    viewer_email: str,
    is_admin: bool,
    focus_ids: set[int],
) -> None:
    email = (item.get("owner_email") or "").strip().lower()
    st.markdown("##### Record detail")
    st.markdown(
        f"""
<div class="fx-card-block" style="border-left:4px solid {owner_style(email)[0]};">
  <p><strong>{_esc(item.get('company') or '—')}</strong>
     {" · ★ in focus cluster" if int(item.get('id') or 0) in focus_ids else ""}</p>
  <p>{owner_chip_html(email, item.get('owner_name') or "")}</p>
  <p class="fx-muted">{_esc(item.get('domain') or '')} · {_esc(item.get('status_label') or '')} ·
     search: {_esc(item.get('search_label') or '—')}</p>
  <p class="fx-muted">People · {_esc(item.get('people_line') or '—')}</p>
</div>
""",
        unsafe_allow_html=True,
    )

    hits = find_similar(
        identity_from_pipeline(item),
        team,
        exclude_pipeline_id=int(item["id"]),
    )
    if hits:
        st.markdown("**Similar across the team**")
        for h in hits[:12]:
            he = (h.get("owner_email") or "").strip().lower()
            st.markdown(
                f"- {owner_chip_html(he, _display_name(he, profiles))} "
                f"**{_esc(h.get('company') or '—')}** · {_esc(status_label(h.get('pipeline_status') or ''))} · "
                f"{_esc(_clip(h.get('search_name') or h.get('icp_text') or '', 50))}",
                unsafe_allow_html=True,
            )

    bundle, lead = _load_detail_bundle(memory, item)
    contacts_line = format_contacts_line(bundle.get("contacts") or [])
    if contacts_line:
        st.caption(f"Contacts · {contacts_line}")
    signal_text = (bundle.get("signal_text") or "").strip()
    if signal_text:
        st.markdown(f"**Signal** · {_esc(signal_text)}", unsafe_allow_html=True)

    msgs = bundle.get("selected_messages") or []
    if msgs:
        st.markdown("##### Shortlisted messages")
        for msg in msgs:
            st.markdown(
                f"**{(msg.get('person_name') or 'Contact')}** · {(msg.get('kind') or '').title()}"
            )
            st.text(msg.get("body") or "")
    else:
        st.caption("No shortlisted messages stored on this queue item.")

    snap = bundle.get("lead_snapshot")
    with st.expander("Full company dossier", expanded=False):
        if snap:
            st.markdown(detail_html(snap, selected_only=True), unsafe_allow_html=True)
        elif lead:
            st.markdown(detail_html(lead, omit_drafts=False), unsafe_allow_html=True)
        else:
            st.markdown(pipeline_detail_html(item, show_owner=True), unsafe_allow_html=True)

    mine = email == (viewer_email or "").strip().lower()
    st.markdown("##### Progress")
    render_status_stepper(
        memory,
        item,
        key_prefix="central",
        can_edit=mine,
        is_admin=is_admin,
    )
