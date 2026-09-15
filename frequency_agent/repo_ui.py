"""Centralised Excel-style queue repository (all users)."""

from __future__ import annotations

import hashlib
import html
import re

import streamlit as st

from .outreach_queue import bundle_from_any, enrich_queue_bundle, format_contacts_line
from .similarity import PIPELINE_STATUS_LABELS, find_similar, identity_from_pipeline, status_label
from .ui import detail_html, empty_state_html

PAGE_SIZE = 50

OWNER_PALETTE = (
    "#C6EFCE",
    "#BDD7EE",
    "#F8CBAD",
    "#E2D5F1",
    "#FFF2CC",
    "#F4B6C2",
    "#C9DAF8",
    "#D9EAD3",
    "#FCE5CD",
    "#D0E0E3",
    "#D5A6BD",
    "#A2C4C9",
)


def _esc(text: str) -> str:
    return html.escape(text or "")


def _clip(text: str, n: int = 120) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if len(raw) <= n:
        return raw
    return raw[:n].rstrip() + "…"


def owner_color(email: str) -> str:
    key = (email or "").strip().lower() or "unknown"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return OWNER_PALETTE[digest[0] % len(OWNER_PALETTE)]


def owner_display(email: str, profiles: dict[str, dict] | None = None) -> tuple[str, str]:
    email = (email or "").strip().lower()
    profile = (profiles or {}).get(email) or {}
    name = (profile.get("display_name") or "").strip() or "—"
    return name, email or "—"


def open_repo_cluster(pipeline_id: int) -> None:
    st.session_state.page_view = "repo"
    st.session_state.similar_focus_id = int(pipeline_id)
    st.session_state.repo_open_id = int(pipeline_id)
    st.session_state.repo_page = 1


def similar_highlight_html(n: int, *, allow_queue: bool = False) -> str:
    extra = " You can still queue this and keep working it." if allow_queue else ""
    return (
        f'<div class="fx-sim-jump"><b>Similar items already in the team repo · {int(n)}</b>'
        f"{_esc(extra)}</div>"
    )


def render_similar_highlight(
    item: dict | None,
    hits: list[dict],
    *,
    key: str,
    allow_queue: bool = False,
) -> None:
    if not hits:
        return
    focus_id = 0
    if item and item.get("id"):
        focus_id = int(item["id"])
    elif hits[0].get("id"):
        focus_id = int(hits[0]["id"])
    if not focus_id:
        return
    st.markdown(similar_highlight_html(len(hits), allow_queue=allow_queue), unsafe_allow_html=True)
    if st.button(
        f"Open {len(hits)} similar in repo",
        key=key,
        use_container_width=True,
    ):
        open_repo_cluster(focus_id)
        st.rerun()


def _similar_hits(item: dict, team: list[dict]) -> list[dict]:
    return find_similar(
        identity_from_pipeline(item),
        team,
        exclude_pipeline_id=int(item["id"]),
    )


def cluster_for(item: dict, team: list[dict]) -> list[dict]:
    return [item] + _similar_hits(item, team)


def filter_repo_rows(
    items: list[dict],
    *,
    needle: str = "",
    owner: str = "all",
    status: str = "all",
    similar_only: bool = False,
    similar_counts: dict[int, int] | None = None,
) -> list[dict]:
    q = (needle or "").strip().lower()
    owner = (owner or "all").strip().lower()
    status = (status or "all").strip().lower()
    counts = similar_counts or {}
    out: list[dict] = []
    for item in items:
        if owner != "all" and (item.get("owner_email") or "").strip().lower() != owner:
            continue
        if status != "all" and (item.get("pipeline_status") or "") != status:
            continue
        if similar_only and not counts.get(int(item["id"]), 0):
            continue
        if q:
            blob = " ".join(
                [
                    item.get("company") or "",
                    item.get("domain") or "",
                    item.get("person_name") or "",
                    item.get("person_email") or "",
                    item.get("owner_email") or "",
                    item.get("search_name") or "",
                    item.get("icp_text") or "",
                    item.get("pipeline_status") or "",
                ]
            ).lower()
            if q not in blob:
                continue
        out.append(item)
    return out


def _hydrate_item(memory, item: dict) -> dict:
    from .memory import resolve_search_name

    bundle: dict = {}
    qid = item.get("send_queue_id")
    row = None
    if qid:
        try:
            row = memory.get_send_queue_item_any(int(qid))
            bundle = bundle_from_any(row) if row else {}
        except Exception:
            bundle = {}
    lead = None
    lead_id = (item.get("lead_id") or (row or {}).get("lead_id") or "").strip()
    owner = (item.get("owner_email") or "").strip().lower()
    if lead_id:
        try:
            lead = memory.get_lead_any(lead_id, owner_email=owner)
        except Exception:
            lead = None
    bundle = enrich_queue_bundle(bundle, lead=lead, pipeline_item=item)
    if not (bundle.get("search_name") or "").strip():
        bundle["search_name"] = resolve_search_name(
            {
                "label": item.get("search_name") or "",
                "icp_text": item.get("icp_text") or "",
            }
        )
    return {"bundle": bundle, "lead": lead}


def _sheet_html(
    rows: list[dict],
    *,
    profiles: dict[str, dict],
    similar_counts: dict[int, int],
    highlight_ids: set[int],
) -> str:
    head = "".join(
        f"<th>{label}</th>"
        for label in (
            "Owner",
            "Email",
            "Company",
            "Domain",
            "People",
            "Search / ICP",
            "Signal",
            "Status",
            "Msgs",
            "Similar",
            "Updated",
        )
    )
    body_parts = []
    for item in rows:
        pid = int(item["id"])
        name, email = owner_display(item.get("owner_email") or "", profiles)
        color = owner_color(item.get("owner_email") or "")
        hit = pid in highlight_ids
        people = item.get("_people") or item.get("person_name") or "—"
        signal = item.get("_signal") or "—"
        search = item.get("search_name") or item.get("icp_text") or "—"
        n_msg = item.get("_n_msg")
        n_msg_s = "—" if n_msg is None else str(n_msg)
        sim_n = similar_counts.get(pid, 0)
        updated = (item.get("updated_at") or "")[:19].replace("T", " ")
        cls = ' class="fx-sheet-hit"' if hit else ""
        mark = ' <span class="fx-sheet-mark">SIMILAR</span>' if hit else ""
        body_parts.append(
            f"<tr{cls}>"
            f'<td class="fx-sheet-owner" style="background:{color}">{_esc(name)}{mark}</td>'
            f'<td style="background:{color}">{_esc(email)}</td>'
            f"<td>{_esc(item.get('company') or '—')}</td>"
            f"<td>{_esc(item.get('domain') or '—')}</td>"
            f"<td>{_esc(_clip(str(people), 80))}</td>"
            f"<td>{_esc(_clip(str(search), 90))}</td>"
            f"<td>{_esc(_clip(str(signal), 90))}</td>"
            f"<td>{_esc(status_label(item.get('pipeline_status') or ''))}</td>"
            f"<td>{_esc(n_msg_s)}</td>"
            f"<td>{sim_n or '—'}</td>"
            f"<td>{_esc(updated)}</td>"
            f"</tr>"
        )
    return (
        '<div class="fx-sheet-wrap"><table class="fx-sheet">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_parts)}</tbody>"
        "</table></div>"
    )


def _render_item_detail(memory, item: dict, *, profiles: dict, viewer_email: str) -> None:
    name, email = owner_display(item.get("owner_email") or "", profiles)
    color = owner_color(item.get("owner_email") or "")
    st.markdown(
        f'<p style="margin:0 0 8px;padding:6px 10px;border:1px solid #000;background:{color};color:#000">'
        f"<b>{_esc(name)}</b> · {_esc(email)} · {_esc(status_label(item.get('pipeline_status') or ''))}</p>",
        unsafe_allow_html=True,
    )
    packed = _hydrate_item(memory, item)
    bundle = packed["bundle"]
    lead = packed["lead"]
    snap = bundle.get("lead_snapshot")
    msgs = bundle.get("selected_messages") or []
    if snap:
        st.markdown(detail_html(snap, selected_only=True), unsafe_allow_html=True)
    elif lead:
        st.markdown(detail_html(lead, omit_drafts=False), unsafe_allow_html=True)
    else:
        st.caption("Full dossier snapshot is not stored on this older queue item.")
        st.write(
            {
                "company": item.get("company"),
                "domain": item.get("domain"),
                "person": item.get("person_name"),
                "search": item.get("search_name"),
                "icp": item.get("icp_text"),
                "status": item.get("pipeline_status"),
            }
        )
    if msgs:
        st.markdown("**Shortlisted messages**")
        for msg in msgs:
            st.markdown(
                f"**{(msg.get('person_name') or 'Contact')}** · {(msg.get('kind') or '').title()}"
            )
            st.text(msg.get("body") or "")
    events = memory.list_pipeline_events(int(item["id"]), limit=12)
    if events:
        st.markdown("**Activity**")
        for ev in events:
            when = (ev.get("at") or "")[:19].replace("T", " ")
            note = ev.get("comment") or ""
            st.caption(
                f"{when} · {ev.get('from_status') or '—'} → {ev.get('to_status') or '—'}"
                + (f" · {note}" if note else "")
            )
    mine = (item.get("owner_email") or "").lower() == (viewer_email or "").lower()
    if mine:
        st.caption("This is your record.")


def render_central_repo(
    *,
    memory,
    owner_email: str,
    profiles: dict[str, dict] | None = None,
) -> None:
    profiles = profiles or {}
    items = memory.list_team_pipeline()
    st.markdown("#### Team repo")
    st.caption(
        "Every queued company across all users. Spreadsheet view — search and filter. "
        "Owner colour is stable per email. Similar matches are highlighted in gold."
    )
    if not items:
        st.markdown(
            empty_state_html(
                "Repo is empty",
                "When anyone queues a result, it appears here for the whole team.",
            ),
            unsafe_allow_html=True,
        )
        return

    similar_counts = {int(it["id"]): len(_similar_hits(it, items)) for it in items}
    focus_id = int(st.session_state.get("similar_focus_id") or 0)
    focus = next((i for i in items if int(i["id"]) == focus_id), None) if focus_id else None
    highlight_ids: set[int] = set()
    cluster: list[dict] = []
    if focus:
        cluster = cluster_for(focus, items)
        highlight_ids = {int(r["id"]) for r in cluster}
        st.info(
            f"Similar cluster for {focus.get('company') or 'this company'} · "
            f"{len(cluster)} record(s) from all matching users."
        )
        if st.button("Show full repo", key="repo-clear-focus"):
            st.session_state.similar_focus_id = 0
            st.session_state.repo_open_id = 0
            st.rerun()

    owners = sorted(
        {(i.get("owner_email") or "").strip().lower() for i in items if i.get("owner_email")}
    )
    f1, f2, f3, f4 = st.columns([0.34, 0.22, 0.22, 0.22])
    with f1:
        needle = st.text_input("Search", placeholder="company, person, email, domain…", key="repo-q")
    with f2:
        owner_pick = st.selectbox(
            "Owner",
            ["all"] + owners,
            format_func=lambda e: "Everyone" if e == "all" else " · ".join(owner_display(e, profiles)),
            key="repo-owner",
        )
    with f3:
        status_pick = st.selectbox(
            "Status",
            ["all"] + list(PIPELINE_STATUS_LABELS.keys()),
            format_func=lambda s: "All statuses" if s == "all" else PIPELINE_STATUS_LABELS.get(s, s),
            key="repo-status",
        )
    with f4:
        similar_only = st.checkbox("Has similar", key="repo-has-sim")

    shown = filter_repo_rows(
        items,
        needle=needle,
        owner=owner_pick,
        status=status_pick,
        similar_only=similar_only,
        similar_counts=similar_counts,
    )
    if highlight_ids:
        shown = [r for r in shown if int(r["id"]) in highlight_ids] or shown
        shown.sort(key=lambda r: 0 if int(r["id"]) in highlight_ids else 1)

    total = len(shown)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if "repo_page" not in st.session_state:
        st.session_state.repo_page = 1
    page = int(st.session_state.repo_page or 1)
    if page > pages:
        page = pages
        st.session_state.repo_page = page
    start = (page - 1) * PAGE_SIZE
    page_rows = shown[start : start + PAGE_SIZE]

    for item in page_rows:
        packed = _hydrate_item(memory, item)
        bundle = packed["bundle"]
        item["_signal"] = (bundle.get("signal_text") or "").strip()
        item["_people"] = format_contacts_line(bundle.get("contacts") or []) or (
            item.get("person_name") or ""
        )
        item["_n_msg"] = len(bundle.get("selected_messages") or [])

    st.caption(f"{total} row(s) · page {page} of {pages}")
    st.markdown(
        _sheet_html(
            page_rows,
            profiles=profiles,
            similar_counts=similar_counts,
            highlight_ids=highlight_ids,
        ),
        unsafe_allow_html=True,
    )

    nav_l, nav_r = st.columns(2)
    with nav_l:
        if st.button("Previous page", disabled=page <= 1, key="repo-prev"):
            st.session_state.repo_page = page - 1
            st.rerun()
    with nav_r:
        if st.button("Next page", disabled=page >= pages, key="repo-next"):
            st.session_state.repo_page = page + 1
            st.rerun()

    legend = []
    for email in owners[:12]:
        nm, em = owner_display(email, profiles)
        color = owner_color(email)
        legend.append(
            f'<span style="display:inline-block;margin:0 10px 6px 0;padding:2px 8px;'
            f'border:1px solid #000;background:{color};color:#000">{_esc(nm)} · {_esc(em)}</span>'
        )
    if legend:
        st.markdown("<p style='margin:8px 0 4px'><b>Owner colours</b></p>" + "".join(legend), unsafe_allow_html=True)

    if cluster and highlight_ids:
        st.markdown("##### Matching records (all details)")
        st.caption("Every similar item from this cluster — yours and other users’ — with full company, people, signal, and shortlisted mail.")
        for row in cluster:
            with st.expander(
                f"{row.get('company') or '—'} · {owner_display(row.get('owner_email') or '', profiles)[0]} · "
                f"{status_label(row.get('pipeline_status') or '')}",
                expanded=True,
            ):
                _render_item_detail(memory, row, profiles=profiles, viewer_email=owner_email)
        return

    labels = {
        int(r["id"]): (
            f"{r.get('company') or '—'} · "
            f"{owner_display(r.get('owner_email') or '', profiles)[0]} · "
            f"{status_label(r.get('pipeline_status') or '')}"
        )
        for r in page_rows
    }
    if not labels:
        return
    ids = list(labels.keys())
    pick = st.selectbox(
        "Open full record",
        ids,
        format_func=lambda i: labels.get(int(i), str(i)),
        key="repo-open-pick",
    )
    chosen = next((r for r in page_rows if int(r["id"]) == int(pick)), None)
    if chosen:
        st.markdown("##### Record detail")
        _render_item_detail(memory, chosen, profiles=profiles, viewer_email=owner_email)
