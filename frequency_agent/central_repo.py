"""Central multi-user queue repository — searchable, filterable, full-fidelity dossiers."""

from __future__ import annotations

import hashlib
import html
import re

import streamlit as st

from .memory import resolve_search_name
from .outreach_queue import bundle_from_any, enrich_queue_bundle, format_contacts_line
from .similarity import (
    PIPELINE_STATUS_LABELS,
    PIPELINE_STATUSES,
    find_similar,
    identity_from_pipeline,
    next_pipeline_actions,
    normalize_pipeline_status,
    require_comment,
    status_label,
)
from .ui import detail_html, empty_state_html

# Distinct, non-purple owner accents (stable per email).
_OWNER_PALETTE = (
    "#1f6f5a",
    "#b85c38",
    "#2c5f8a",
    "#8a4b6e",
    "#6b7c3a",
    "#a67c2a",
    "#4a6fa5",
    "#7a4e3a",
    "#3d7a6a",
    "#9a4a5c",
    "#5c6b8a",
    "#6a5a3a",
    "#2e6b4f",
    "#c07840",
    "#3f5d7a",
)

PAGE_SIZE = 40


def _esc(text: str) -> str:
    return html.escape(text or "")


def _clip(text: str, n: int = 120) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if len(raw) <= n:
        return raw
    return raw[:n].rstrip() + "…"


def owner_color(email: str) -> str:
    email = (email or "").strip().lower() or "unknown"
    digest = hashlib.md5(email.encode("utf-8")).hexdigest()
    return _OWNER_PALETTE[int(digest[:8], 16) % len(_OWNER_PALETTE)]


def owner_display(email: str, profiles: dict | None = None) -> str:
    email = (email or "").strip().lower()
    profile = (profiles or {}).get(email) or {}
    name = (profile.get("display_name") or "").strip()
    if name:
        return f"{name}"
    return email or "unknown"


def owner_label(email: str, profiles: dict | None = None) -> str:
    email = (email or "").strip().lower()
    name = owner_display(email, profiles)
    if name != email and email:
        return f"{name} · {email}"
    return email or "unknown"


def open_queue_cluster(pipeline_id: int) -> None:
    """Jump to the shared Queue repo focused on this item and its similar matches."""
    st.session_state.page_view = "main"
    st.session_state.ws_jump_queue = True
    st.session_state.main_section = "queue"
    st.session_state.similar_focus_id = int(pipeline_id)
    st.session_state.queue_open_id = int(pipeline_id)


def _similar_hits(item: dict, team: list[dict]) -> list[dict]:
    return find_similar(
        identity_from_pipeline(item),
        team,
        exclude_pipeline_id=int(item["id"]),
    )


def _cluster_for(focus: dict, team: list[dict]) -> list[dict]:
    hits = _similar_hits(focus, team)
    by_id = {int(focus["id"]): focus}
    for h in hits:
        by_id[int(h["id"])] = h
    return sorted(by_id.values(), key=lambda r: (r.get("owner_email") or "", r.get("updated_at") or ""), reverse=True)


def _load_bundle(memory, item: dict) -> tuple[dict, dict | None]:
    bundle: dict = {}
    lead = None
    qid = item.get("send_queue_id")
    row = None
    if qid:
        try:
            row = memory.get_send_queue_item(int(qid))
            bundle = bundle_from_any(row) if row else {}
        except Exception:
            bundle = {}
    lead_id = (item.get("lead_id") or (row or {}).get("lead_id") or "").strip()
    if lead_id:
        try:
            # Prefer owner-scoped lead when possible
            owner = (item.get("owner_email") or "").strip().lower()
            if owner and hasattr(memory, "_admin_scoped"):
                lead = memory._admin_scoped(owner).get_lead(lead_id)
            else:
                lead = memory.get_lead(lead_id)
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
    return bundle, lead


def _advance(memory, item: dict, to_status: str, comment: str, *, is_admin: bool) -> None:
    try:
        memory.update_pipeline_status(
            int(item["id"]),
            to_status,
            comment,
            as_admin=bool(is_admin),
        )
        if to_status == "outreach_sent":
            qid = item.get("send_queue_id")
            if qid:
                try:
                    result = memory.dry_run_dispatch(int(qid))
                    if result:
                        from pathlib import Path

                        from .send_queue import append_jsonl

                        owner = (item.get("owner_email") or "anon").strip().lower()
                        slug = "".join(ch if ch.isalnum() else "_" for ch in owner).strip("_") or "anon"
                        root = Path(__file__).resolve().parent.parent
                        log_path = root / "output" / f"dry_run_send_log_{slug}.jsonl"
                        append_jsonl(
                            log_path,
                            {
                                "mode": "dry_run",
                                "actually_sent": False,
                                "dispatched_at": result.get("dispatched_at"),
                                "queue_id": result.get("id"),
                                "lead_id": result.get("lead_id"),
                                "company": result.get("company"),
                                "channel": result.get("channel"),
                                "recipient": result.get("recipient"),
                                "subject": result.get("subject"),
                                "note": "logged via Queue status → Outreach sent",
                            },
                        )
                except Exception:
                    pass
        st.toast(f"Updated → {status_label(to_status)}")
        st.rerun()
    except Exception as exc:
        st.error(str(exc))


def repo_row_html(
    item: dict,
    *,
    profiles: dict | None,
    similar_n: int = 0,
    highlighted: bool = False,
    mine: bool = False,
) -> str:
    email = (item.get("owner_email") or "").strip().lower()
    color = owner_color(email)
    status = normalize_pipeline_status(item.get("pipeline_status") or "queued")
    company = item.get("company") or "—"
    person = item.get("person_name") or item.get("person_role") or ""
    search = _clip(item.get("search_name") or item.get("icp_text") or "", 70)
    owner = owner_label(email, profiles)
    you = ' <span class="fx-repo-you">you</span>' if mine else ""
    sim = f'<span class="badge warn">Similar · {similar_n}</span>' if similar_n else ""
    hl = " highlighted" if highlighted else ""
    return f"""
<div class="fx-repo-row{hl}" style="border-left-color:{_esc(color)};">
  <div class="fx-repo-row-top">
    <span class="fx-repo-owner" style="background:{_esc(color)};">{_esc(owner_display(email, profiles) or email)}</span>
    <span class="fx-repo-status">{_esc(status_label(status))}</span>
    {sim}
  </div>
  <p class="fx-repo-company">{_esc(company)}{you}</p>
  <p class="fx-repo-meta">{_esc(person) if person else "No named contact"} · {_esc(owner)}</p>
  <p class="fx-repo-meta">Search · {_esc(search or "—")}</p>
</div>
"""


def legend_html(emails: list[str], profiles: dict | None) -> str:
    chips = []
    for email in emails[:16]:
        color = owner_color(email)
        label = owner_display(email, profiles) or email
        chips.append(
            f'<span class="fx-repo-legend-chip" style="border-color:{_esc(color)};">'
            f'<i style="background:{_esc(color)};"></i>{_esc(label)}</span>'
        )
    if not chips:
        return ""
    return f'<div class="fx-repo-legend">{"".join(chips)}</div>'


def _render_item_actions(
    memory,
    item: dict,
    *,
    owner_email: str,
    is_admin: bool,
    key_prefix: str,
) -> None:
    can_edit = (item.get("owner_email") or "").lower() == (owner_email or "").lower()
    can_remove = can_edit or is_admin
    current = normalize_pipeline_status(item.get("pipeline_status") or "queued")
    actions = next_pipeline_actions(current) if can_edit else []

    needs_comment = any(require_comment(code) for code, _label in actions)
    comment = ""
    if can_edit and needs_comment:
        comment = st.text_area(
            "Comment (required to close)",
            value=item.get("comment") or "",
            height=70,
            key=f"{key_prefix}-note-{item['id']}",
        )

    left, right = st.columns(2)
    with left:
        if not can_edit:
            st.caption("View only — the owner advances this item.")
        elif not actions:
            st.caption(f"Closed as {status_label(current)}.")
        elif len(actions) == 1:
            code, label = actions[0]
            if st.button(label, key=f"{key_prefix}-go-{code}-{item['id']}", use_container_width=True, type="primary"):
                _advance(memory, item, code, comment, is_admin=is_admin)
        else:
            sub = st.columns(len(actions))
            for col, (code, label) in zip(sub, actions):
                with col:
                    if st.button(label, key=f"{key_prefix}-go-{code}-{item['id']}", use_container_width=True, type="primary"):
                        _advance(memory, item, code, comment, is_admin=is_admin)
    with right:
        if can_remove and st.button(
            "Remove from queue",
            key=f"{key_prefix}-rm-{item['id']}",
            use_container_width=True,
        ):
            try:
                memory.remove_pipeline_item(int(item["id"]), as_admin=is_admin)
                st.toast(f"Removed {item.get('company') or 'item'} from queue")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_full_dossier(memory, item: dict, *, key_prefix: str, profiles: dict | None) -> None:
    from .pipeline_ui import stepper_html

    bundle, lead = _load_bundle(memory, item)
    email = (item.get("owner_email") or "").strip().lower()
    color = owner_color(email)
    signal_text = (bundle.get("signal_text") or "").strip()
    contacts_line = format_contacts_line(bundle.get("contacts") or [])
    msgs = bundle.get("selected_messages") or []

    st.markdown(
        f"""
<div class="fx-repo-detail" style="border-left-color:{_esc(color)};">
  <div class="fx-repo-row-top">
    <span class="fx-repo-owner" style="background:{_esc(color)};">{_esc(owner_display(email, profiles) or email)}</span>
    <span class="fx-repo-status">{_esc(status_label(item.get("pipeline_status") or ""))}</span>
  </div>
  <h3>{_esc(item.get("company") or "—")}</h3>
  <p class="fx-repo-meta">Owner · {_esc(owner_label(email, profiles))}</p>
  <p class="fx-repo-meta">Search · {_esc(_clip(item.get("search_name") or item.get("icp_text") or "", 120) or "—")}</p>
  <p class="fx-repo-meta">Contacts · {_esc(_clip(contacts_line, 180) or (item.get("person_name") or "—"))}</p>
  {"<p class='fx-repo-meta'>Signal · " + _esc(_clip(signal_text, 160)) + "</p>" if signal_text else ""}
  {stepper_html(item.get("pipeline_status") or "queued")}
</div>
""",
        unsafe_allow_html=True,
    )

    if msgs:
        st.markdown("##### Shortlisted messages")
        for msg in msgs:
            st.markdown(
                f"**{(msg.get('person_name') or 'Contact')}** · {(msg.get('kind') or '').title()}"
            )
            st.text(msg.get("body") or "")

    snap = bundle.get("lead_snapshot")
    detail_key = f"{key_prefix}-full-{item.get('id')}"
    if detail_key not in st.session_state:
        st.session_state[detail_key] = bool(snap or lead)
    if st.button(
        "Hide full result" if st.session_state[detail_key] else "Show full result dossier",
        key=f"{key_prefix}-full-btn-{item.get('id')}",
        use_container_width=True,
    ):
        st.session_state[detail_key] = not st.session_state[detail_key]
        st.rerun()
    if st.session_state.get(detail_key):
        if snap:
            st.markdown(detail_html(snap, selected_only=True), unsafe_allow_html=True)
        elif lead:
            st.markdown(detail_html(lead, omit_drafts=False), unsafe_allow_html=True)
        else:
            st.caption("No full lead snapshot stored for this older queue item.")


def render_central_repository(
    *,
    memory,
    owner_email: str,
    is_admin: bool = False,
    profiles: dict | None = None,
) -> None:
    """Shared queue of every user's items — search, filter, owner colors, full dossiers."""
    profiles = profiles or {}
    owner_email = (owner_email or "").strip().lower()
    items = memory.list_team_pipeline()
    stats = memory.pipeline_stats(team=True)
    focus_id = int(st.session_state.get("similar_focus_id") or 0)
    open_id = int(st.session_state.get("queue_open_id") or 0)

    st.markdown("#### Shared queue repository")
    st.caption(
        "Every queued company across the team — full result, shortlisted messages, and progress. "
        "Each owner is colour-coded. You can still queue similar items; use the highlight to compare."
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("All items", stats.get("total") or 0)
    mine_n = sum(1 for i in items if (i.get("owner_email") or "").lower() == owner_email)
    m2.metric("Yours", mine_n)
    m3.metric("Outreach sent", stats.get("outreach_sent") or 0)
    m4.metric("Ongoing", stats.get("ongoing") or 0)
    m5.metric("Closed", (stats.get("success") or 0) + (stats.get("failure") or 0))

    if not items:
        st.markdown(
            empty_state_html(
                "Shared queue is empty",
                "When anyone queues a result, it appears here for the whole team.",
            ),
            unsafe_allow_html=True,
        )
        return

    owners = sorted({(i.get("owner_email") or "").strip().lower() for i in items if i.get("owner_email")})
    st.markdown(legend_html(owners, profiles), unsafe_allow_html=True)

    # ── Similar cluster focus ──
    if focus_id:
        focus = next((i for i in items if int(i["id"]) == focus_id), None)
        if focus:
            cluster = _cluster_for(focus, items)
            st.markdown(
                f"""
<div class="fx-sim-flag">
  <span class="fx-sim-dot"></span>
  <span><strong>Similar cluster</strong> for {_esc(focus.get("company") or "this company")} —
  {len(cluster)} record(s) from the team (including yours). Compare before progressing.</span>
</div>
""",
                unsafe_allow_html=True,
            )
            if st.button("Clear cluster · show full repository", key="repo-clear-focus", use_container_width=True):
                st.session_state.similar_focus_id = 0
                st.rerun()

            for row in cluster:
                pid = int(row["id"])
                mine = (row.get("owner_email") or "").lower() == owner_email
                hits = _similar_hits(row, items)
                st.markdown(
                    repo_row_html(
                        row,
                        profiles=profiles,
                        similar_n=len(hits),
                        highlighted=(pid == open_id or pid == focus_id),
                        mine=mine,
                    ),
                    unsafe_allow_html=True,
                )
                b1, b2 = st.columns([0.7, 0.3])
                with b1:
                    if st.button(
                        "Open this record" if pid != open_id else "Selected below ↓",
                        key=f"repo-cluster-open-{pid}",
                        use_container_width=True,
                        type="primary" if pid == open_id else "secondary",
                        disabled=pid == open_id,
                    ):
                        st.session_state.queue_open_id = pid
                        st.rerun()
                with b2:
                    st.caption(status_label(row.get("pipeline_status") or ""))

            chosen = next((r for r in cluster if int(r["id"]) == open_id), cluster[0])
            st.session_state.queue_open_id = int(chosen["id"])
            st.divider()
            st.markdown("##### Full record")
            _render_full_dossier(memory, chosen, key_prefix=f"repo-c-{chosen['id']}", profiles=profiles)
            _render_item_actions(
                memory,
                chosen,
                owner_email=owner_email,
                is_admin=is_admin,
                key_prefix=f"repo-c-{chosen['id']}",
            )
            return

    # ── Filters ──
    f1, f2, f3, f4 = st.columns([0.34, 0.22, 0.22, 0.22])
    with f1:
        q = st.text_input(
            "Search",
            placeholder="Company, person, owner, search, domain…",
            key="repo-q",
        )
    with f2:
        owner_pick = st.selectbox(
            "Owner",
            ["all", "mine"] + owners,
            format_func=lambda e: (
                "Everyone"
                if e == "all"
                else ("Only mine" if e == "mine" else owner_label(e, profiles))
            ),
            key="repo-owner",
        )
    with f3:
        status_pick = st.selectbox(
            "Status",
            ["all"] + list(PIPELINE_STATUSES),
            format_func=lambda s: "All statuses" if s == "all" else PIPELINE_STATUS_LABELS.get(s, s),
            key="repo-status",
        )
    with f4:
        similar_only = st.checkbox("Has similar match", value=False, key="repo-sim-only")

    needle = (q or "").strip().lower()
    # Precompute similar counts once for filtered set efficiency
    shown: list[dict] = []
    similar_counts: dict[int, int] = {}
    for item in items:
        email = (item.get("owner_email") or "").lower()
        if owner_pick == "mine" and email != owner_email:
            continue
        if owner_pick not in {"all", "mine"} and email != owner_pick:
            continue
        if status_pick != "all" and (item.get("pipeline_status") or "") != status_pick:
            continue
        if needle:
            blob = " ".join(
                [
                    item.get("company") or "",
                    item.get("person_name") or "",
                    item.get("person_role") or "",
                    item.get("domain") or "",
                    item.get("owner_email") or "",
                    item.get("search_name") or "",
                    item.get("icp_text") or "",
                    item.get("company_entity_id") or "",
                ]
            ).lower()
            if needle not in blob:
                continue
        hits = _similar_hits(item, items)
        similar_counts[int(item["id"])] = len(hits)
        if similar_only and not hits:
            continue
        shown.append(item)

    st.caption(f"{len(shown)} record(s) match filters")

    if not shown:
        st.info("No records match these filters.")
        return

    # Pagination
    total_pages = max(1, (len(shown) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = int(st.session_state.get("repo-page") or 1)
    page = max(1, min(page, total_pages))
    st.session_state["repo-page"] = page
    if total_pages > 1:
        p_prev, p_mid, p_next = st.columns([0.2, 0.6, 0.2])
        with p_prev:
            if st.button("← Prev", disabled=page <= 1, key="repo-prev", use_container_width=True):
                st.session_state["repo-page"] = page - 1
                st.rerun()
        with p_mid:
            st.caption(f"Page {page} of {total_pages}")
        with p_next:
            if st.button("Next →", disabled=page >= total_pages, key="repo-next", use_container_width=True):
                st.session_state["repo-page"] = page + 1
                st.rerun()

    page_items = shown[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    # Keep open_id valid
    if open_id and not any(int(i["id"]) == open_id for i in shown):
        open_id = int(page_items[0]["id"]) if page_items else 0
        st.session_state.queue_open_id = open_id
    if not open_id and page_items:
        open_id = int(page_items[0]["id"])
        st.session_state.queue_open_id = open_id

    list_col, detail_col = st.columns([0.38, 0.62], gap="medium")
    with list_col:
        st.markdown("##### Records")
        for item in page_items:
            pid = int(item["id"])
            mine = (item.get("owner_email") or "").lower() == owner_email
            st.markdown(
                repo_row_html(
                    item,
                    profiles=profiles,
                    similar_n=similar_counts.get(pid, 0),
                    highlighted=pid == open_id,
                    mine=mine,
                ),
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button(
                    "View" if pid != open_id else "Viewing",
                    key=f"repo-open-{pid}",
                    use_container_width=True,
                    type="primary" if pid == open_id else "secondary",
                    disabled=pid == open_id,
                ):
                    st.session_state.queue_open_id = pid
                    st.rerun()
            with c2:
                n_sim = similar_counts.get(pid, 0)
                if n_sim and st.button(
                    f"Similar ({n_sim})",
                    key=f"repo-sim-{pid}",
                    use_container_width=True,
                ):
                    open_queue_cluster(pid)
                    st.rerun()

    with detail_col:
        chosen = next((i for i in shown if int(i["id"]) == open_id), page_items[0] if page_items else None)
        if not chosen:
            st.caption("Select a record.")
            return
        st.markdown("##### Full record")
        n_sim = similar_counts.get(int(chosen["id"]), 0)
        if n_sim:
            st.markdown(
                f"""
<div class="fx-sim-flag compact">
  <span class="fx-sim-dot"></span>
  <span>{n_sim} similar record(s) already in the shared queue.</span>
</div>
""",
                unsafe_allow_html=True,
            )
            if st.button("Open similar cluster", key=f"repo-detail-sim-{chosen['id']}", use_container_width=True):
                open_queue_cluster(int(chosen["id"]))
                st.rerun()
        _render_full_dossier(memory, chosen, key_prefix=f"repo-d-{chosen['id']}", profiles=profiles)
        _render_item_actions(
            memory,
            chosen,
            owner_email=owner_email,
            is_admin=is_admin,
            key_prefix=f"repo-d-{chosen['id']}",
        )


def results_similarity_banner_html(hits: list[dict], profiles: dict | None = None) -> str:
    if not hits:
        return ""
    lines = []
    for hit in hits[:6]:
        email = (hit.get("owner_email") or "").strip().lower()
        color = owner_color(email)
        lines.append(
            f'<div class="fx-sim-hit-row" style="border-left-color:{_esc(color)};">'
            f'<strong>{_esc(hit.get("company") or "—")}</strong> · '
            f'{_esc(owner_label(email, profiles))} · '
            f'{_esc(status_label(hit.get("pipeline_status") or ""))} · '
            f'{_esc(_clip(hit.get("search_name") or hit.get("icp_text") or "", 48) or "—")}'
            f"</div>"
        )
    more = f'<p class="fx-muted">{len(hits) - 6} more…</p>' if len(hits) > 6 else ""
    return f"""
<div class="fx-sim-flag">
  <span class="fx-sim-dot"></span>
  <div>
    <strong>Similar already in the shared queue</strong>
    <p style="margin:4px 0 8px;font-size:13px;color:var(--text-secondary);">
      You can still approve or queue. Open the cluster to compare every matching record.
    </p>
    {"".join(lines)}
    {more}
  </div>
</div>
"""
