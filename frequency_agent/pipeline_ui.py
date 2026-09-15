"""Workspace pipeline + team board + queue similarity flags."""

from __future__ import annotations

import html
import re

import streamlit as st

from .similarity import (
    PIPELINE_STATUSES,
    PIPELINE_STATUS_LABELS,
    find_similar,
    identity_from_pipeline,
    is_closed_status,
    next_pipeline_actions,
    normalize_pipeline_status,
    require_comment,
    status_label,
)
from .ui import empty_state_html
from .repo_ui import open_repo_cluster, render_similar_highlight


def _esc(text: str) -> str:
    return html.escape(text or "")


def _clip(text: str, n: int = 120) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if len(raw) <= n:
        return raw
    return raw[: n].rstrip() + "…"


def _owner_label(email: str, profiles: dict[str, dict] | None = None) -> str:
    email = (email or "").strip().lower()
    profile = (profiles or {}).get(email) or {}
    name = (profile.get("display_name") or "").strip()
    if name:
        return f"{name} · {email}"
    return email or "unknown"


def open_similar_cluster(pipeline_id: int) -> None:
    """Jump to the central repo focused on this item and its matches."""
    open_repo_cluster(pipeline_id)


def stepper_html(status: str) -> str:
    current = normalize_pipeline_status(status)
    closed = is_closed_status(current)
    steps = [
        ("queued", "Queued"),
        ("outreach_sent", "Outreach sent"),
        ("ongoing", "Ongoing"),
        ("closed", "Closed"),
    ]
    order = ["queued", "outreach_sent", "ongoing"]
    idx = order.index(current) if current in order else (3 if closed else 0)
    parts = []
    for i, (code, label) in enumerate(steps):
        cls = "fx-st"
        if code == "closed" and closed:
            cls += " lost" if current == "failure" else " done"
            label = status_label(current)
        elif not closed and code == current:
            cls += " on"
        elif (code in order and order.index(code) < idx) or (closed and code != "closed"):
            cls += " done"
        parts.append(f'<span class="{cls}">{_esc(label)}</span>')
        if i < len(steps) - 1:
            parts.append('<span class="fx-st-gap"></span>')
    return f'<div class="fx-stepper">{"".join(parts)}</div>'


def pipeline_card_html(
    item: dict,
    *,
    show_owner: bool = False,
    similar_n: int = 0,
    signal_text: str = "",
    contacts_line: str = "",
) -> str:
    status = normalize_pipeline_status(item.get("pipeline_status") or "queued")
    company = item.get("company") or "—"
    person = item.get("person_name") or item.get("person_role") or "No named contact"
    domain = item.get("domain") or ""
    eid = item.get("company_entity_id") or ""
    icp = _clip(item.get("search_name") or item.get("icp_text") or "", 90)
    comment = _clip(item.get("comment") or "", 140)
    owner = item.get("owner_email") or ""
    owner_line = f'<p class="fx-pipe-meta">Owner · {_esc(owner)}</p>' if show_owner else ""
    sim = f'<span class="badge warn">Similar · {similar_n}</span>' if similar_n else ""
    signal_line = (
        f'<p class="fx-pipe-meta">Signal · {_esc(_clip(signal_text, 140))}</p>'
        if (signal_text or "").strip()
        else ""
    )
    contacts_block = (
        f'<p class="fx-pipe-meta">Contacts · {_esc(_clip(contacts_line, 160))}</p>'
        if (contacts_line or "").strip()
        else f'<p class="fx-pipe-person">{_esc(person)}{" · " + _esc(domain) if domain else ""}</p>'
    )
    return f"""
<div class="fx-pipe-card">
  <div class="fx-pipe-top">
    <p class="fx-kicker">{_esc(status_label(status))}</p>
    {sim}
  </div>
  <h3>{_esc(company)}</h3>
  {contacts_block}
  {owner_line}
  <p class="fx-pipe-meta">Search · {_esc(icp or "—")}</p>
  {signal_line}
  <p class="fx-pipe-meta">ID · <code>{_esc(eid[:18] or "—")}</code></p>
  {stepper_html(status)}
  {f'<p class="fx-pipe-comment">{_esc(comment)}</p>' if comment else ""}
</div>
"""


def pipeline_detail_html(item: dict, *, show_owner: bool = True) -> str:
    status = normalize_pipeline_status(item.get("pipeline_status") or "queued")
    person = item.get("person_name") or "No named contact"
    role = item.get("person_role") or ""
    person_line = person if not role else f"{person} · {role}"
    icp = item.get("icp_text") or item.get("search_name") or "—"
    comment = item.get("comment") or ""
    owner_block = (
        f'<p class="fx-pipe-meta">Owner · {_esc(item.get("owner_email") or "")}</p>'
        if show_owner
        else ""
    )
    return f"""
<div class="fx-pipe-detail">
  <p class="fx-kicker">{_esc(status_label(status))}</p>
  <h3>{_esc(item.get("company") or "—")}</h3>
  <p class="fx-pipe-person">{_esc(person_line)}</p>
  {owner_block}
  <p class="fx-pipe-meta">Domain · {_esc(item.get("domain") or "—")}</p>
  <p class="fx-pipe-meta">Email · {_esc(item.get("person_email") or "—")}</p>
  <p class="fx-pipe-meta">Search · {_esc(item.get("search_name") or "—")}</p>
  <p class="fx-pipe-meta">ICP · {_esc(_clip(icp, 220))}</p>
  <p class="fx-pipe-meta">Entity · <code>{_esc(item.get("company_entity_id") or "—")}</code></p>
  <p class="fx-pipe-meta">Updated · {_esc((item.get("updated_at") or "")[:19].replace("T", " "))}</p>
  {stepper_html(status)}
  {f'<p class="fx-pipe-comment">{_esc(comment)}</p>' if comment else '<p class="fx-pipe-meta">No comment yet.</p>'}
</div>
"""


def _similar_hits(item: dict, team: list[dict]) -> list[dict]:
    return find_similar(
        identity_from_pipeline(item),
        team,
        exclude_pipeline_id=int(item["id"]),
    )


def _cluster_for(item: dict, team: list[dict]) -> list[dict]:
    hits = _similar_hits(item, team)
    return [item] + hits


def render_similar_block(
    item: dict,
    hits: list[dict],
    *,
    key_prefix: str,
    allow_queue_note: bool = False,
) -> None:
    """Highlight + jump into the central repo cluster."""
    render_similar_highlight(
        item,
        hits,
        key=f"{key_prefix}-sim-go-{item.get('id')}",
        allow_queue=allow_queue_note,
    )


def _advance(memory, item: dict, to_status: str, comment: str, *, is_admin: bool) -> None:
    try:
        memory.update_pipeline_status(
            int(item["id"]),
            to_status,
            comment,
            as_admin=bool(is_admin),
        )
        # Marking outreach sent also closes the linked dry-run mail row (never delivered).
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
    except Exception as exc:
        st.error(str(exc))
        return
    label = "Response received → Ongoing" if to_status == "ongoing" else status_label(to_status)
    st.toast(f"{item.get('company') or 'Item'} → {label}")
    st.rerun()


def render_status_stepper(
    memory,
    item: dict,
    *,
    key_prefix: str,
    can_edit: bool,
    is_admin: bool,
) -> None:
    current = normalize_pipeline_status(item.get("pipeline_status") or "queued")
    if not can_edit:
        st.caption("View only — the owner advances this item.")
        return
    actions = next_pipeline_actions(current)
    if not actions:
        st.caption(f"Closed as {status_label(current)}.")
        return

    needs_comment = any(require_comment(code) for code, _label in actions)
    comment = ""
    if needs_comment:
        comment = st.text_area(
            "Comment (required to close)",
            value=item.get("comment") or "",
            height=80,
            key=f"{key_prefix}-note-{item['id']}",
        )
        st.caption("Mark success or failure after the conversation is ongoing.")

    cols = st.columns(len(actions))
    for col, (code, label) in zip(cols, actions):
        with col:
            if st.button(label, key=f"{key_prefix}-go-{code}-{item['id']}", use_container_width=True, type="primary"):
                _advance(memory, item, code, comment, is_admin=is_admin)


def render_pipeline_detail(
    memory,
    item: dict,
    *,
    owner_email: str,
    is_admin: bool,
    key_prefix: str,
    show_owner: bool = True,
) -> None:
    st.markdown(pipeline_detail_html(item, show_owner=show_owner), unsafe_allow_html=True)
    mine = (item.get("owner_email") or "").lower() == (owner_email or "").lower()
    render_status_stepper(
        memory,
        item,
        key_prefix=key_prefix,
        can_edit=mine,
        is_admin=is_admin,
    )
    events = memory.list_pipeline_events(int(item["id"]), limit=12)
    if events:
        st.markdown("**Activity**")
        for ev in events:
            from_s = status_label(ev.get("from_status") or "") if ev.get("from_status") else "—"
            to_s = status_label(ev.get("to_status") or "") if ev.get("to_status") else "—"
            when = (ev.get("at") or "")[:19].replace("T", " ")
            note = ev.get("comment") or ""
            st.caption(f"{when} · {from_s} → {to_s}" + (f" · {note}" if note else ""))


def _status_options() -> list[str]:
    return list(PIPELINE_STATUSES)


def render_my_pipeline(*, memory, owner_email: str, is_admin: bool = False) -> None:
    items = memory.list_pipeline()
    team = memory.list_team_pipeline()
    stats = memory.pipeline_stats(team=False)
    st.markdown("##### My pipeline")
    st.caption("Advance each item in order: outreach sent → response received (becomes ongoing) → success or failure.")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Queued", stats.get("queued") or 0)
    c2.metric("Outreach sent", stats.get("outreach_sent") or 0)
    c3.metric("Ongoing", stats.get("ongoing") or 0)
    c4.metric("Success", stats.get("success") or 0)
    c5.metric("Failure", stats.get("failure") or 0)

    if not items:
        st.markdown(
            empty_state_html(
                "Nothing in your pipeline yet",
                "Queue a result from Results — it lands here even if similar items already exist.",
            ),
            unsafe_allow_html=True,
        )
        return

    filter_status = st.selectbox(
        "Filter",
        ["all"] + _status_options(),
        format_func=lambda s: "All statuses" if s == "all" else PIPELINE_STATUS_LABELS.get(s, s),
        key="pipe-mine-filter",
    )
    shown = [i for i in items if filter_status == "all" or i.get("pipeline_status") == filter_status]
    for item in shown:
        hits = _similar_hits(item, team)
        st.markdown(pipeline_card_html(item, similar_n=len(hits)), unsafe_allow_html=True)
        render_similar_block(item, hits, key_prefix="mine")
        render_status_stepper(
            memory,
            item,
            key_prefix="mine",
            can_edit=(item.get("owner_email") or "").lower() == (owner_email or "").lower(),
            is_admin=is_admin,
        )
        events = memory.list_pipeline_events(int(item["id"]), limit=8)
        if events:
            with st.expander("Activity", expanded=False, key=f"mine-ev-{item['id']}"):
                for ev in events:
                    st.caption(
                        f"{ev.get('at') or ''} · {ev.get('from_status') or '—'} → "
                        f"{ev.get('to_status') or '—'} · {ev.get('comment') or ''}"
                    )
        st.divider()


def render_team_board(*, memory, owner_email: str, is_admin: bool = False, profiles: dict | None = None) -> None:
    items = memory.list_team_pipeline()
    stats = memory.pipeline_stats(team=True)
    focus_id = int(st.session_state.get("similar_focus_id") or 0)
    open_id = int(st.session_state.get("team_open_id") or 0)

    st.markdown("##### Team board")
    st.caption("Shared list of everyone who queued a company or person. Click an item to see full status.")

    if focus_id:
        focus = next((i for i in items if int(i["id"]) == focus_id), None)
        if focus:
            cluster = _cluster_for(focus, items)
            st.info(
                f"Similar cluster for {focus.get('company') or 'this company'} · "
                f"{len(cluster)} item(s) including yours."
            )
            if st.button("Show full team board", key="pipe-clear-focus"):
                st.session_state.similar_focus_id = 0
                st.rerun()
            st.markdown("##### Similar items")
            for row in cluster:
                pid = int(row["id"])
                mine = (row.get("owner_email") or "").lower() == (owner_email or "").lower()
                you = " · you" if mine else ""
                label = (
                    f"{row.get('company') or '—'} · {row.get('person_name') or 'no person'} · "
                    f"{row.get('owner_email') or ''} · {status_label(row.get('pipeline_status') or '')}{you}"
                )
                if st.button(label, key=f"cluster-open-{pid}", use_container_width=True):
                    st.session_state.team_open_id = pid
                    st.rerun()
            chosen = next((r for r in cluster if int(r["id"]) == open_id), cluster[0])
            st.markdown("##### Full status")
            render_pipeline_detail(
                memory,
                chosen,
                owner_email=owner_email,
                is_admin=is_admin,
                key_prefix=f"cluster-{chosen['id']}",
                show_owner=True,
            )
            return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Team items", stats.get("total") or 0)
    c2.metric("Outreach sent", stats.get("outreach_sent") or 0)
    c3.metric("Ongoing", stats.get("ongoing") or 0)
    c4.metric("Closed", (stats.get("success") or 0) + (stats.get("failure") or 0))

    if not items:
        st.markdown(
            empty_state_html(
                "Team board is empty",
                "When anyone queues a result, it appears here for coordination.",
            ),
            unsafe_allow_html=True,
        )
        return

    owners = sorted({(i.get("owner_email") or "").strip().lower() for i in items if i.get("owner_email")})
    f1, f2, f3 = st.columns(3)
    with f1:
        owner_pick = st.selectbox(
            "Owner",
            ["all"] + owners,
            format_func=lambda e: "Everyone" if e == "all" else _owner_label(e, profiles),
            key="pipe-team-owner",
        )
    with f2:
        status_pick = st.selectbox(
            "Status",
            ["all"] + _status_options(),
            format_func=lambda s: "All statuses" if s == "all" else PIPELINE_STATUS_LABELS.get(s, s),
            key="pipe-team-status",
        )
    with f3:
        q = st.text_input("Search company or person", key="pipe-team-q")

    needle = (q or "").strip().lower()
    shown = []
    for item in items:
        if owner_pick != "all" and (item.get("owner_email") or "").lower() != owner_pick:
            continue
        if status_pick != "all" and (item.get("pipeline_status") or "") != status_pick:
            continue
        if needle:
            blob = " ".join(
                [
                    item.get("company") or "",
                    item.get("person_name") or "",
                    item.get("domain") or "",
                    item.get("owner_email") or "",
                    item.get("icp_text") or "",
                ]
            ).lower()
            if needle not in blob:
                continue
        shown.append(item)

    st.caption(f"{len(shown)} of {len(items)} items — click a row to open full status")
    for item in shown:
        hits = _similar_hits(item, items)
        mine = (item.get("owner_email") or "").lower() == (owner_email or "").lower()
        you = " · you" if mine else ""
        sim = f" · similar {len(hits)}" if hits else ""
        label = (
            f"{item.get('company') or '—'} · {item.get('person_name') or 'no person'} · "
            f"{item.get('owner_email') or ''} · {status_label(item.get('pipeline_status') or '')}{you}{sim}"
        )
        if st.button(label, key=f"team-open-{item['id']}", use_container_width=True):
            st.session_state.team_open_id = int(item["id"])
            st.session_state.similar_focus_id = int(item["id"]) if hits else 0
            st.rerun()

    chosen = next((i for i in shown if int(i["id"]) == open_id), None)
    if chosen:
        hits = _similar_hits(chosen, items)
        st.markdown("##### Full status")
        render_pipeline_detail(
            memory,
            chosen,
            owner_email=owner_email,
            is_admin=is_admin,
            key_prefix=f"team-d-{chosen['id']}",
            show_owner=True,
        )
        if hits:
            render_similar_block(chosen, hits, key_prefix=f"team-d-{chosen['id']}")


def render_working_queue(*, memory, owner_email: str, is_admin: bool = False) -> None:
    """Single company queue: summary, status advances, and detailed view — no separate dry-run list."""
    from .outreach_queue import bundle_from_any, enrich_queue_bundle, format_contacts_line
    from .ui import detail_html

    items = memory.list_pipeline()
    if not items:
        return
    team = memory.list_team_pipeline()
    st.markdown("#### Queue")
    st.caption(
        "One card per company. Update status here (outreach sent, response received, closed), "
        "or remove an item from the queue. Detailed view shows only the messages you selected."
    )
    for item in items:
        hits = _similar_hits(item, team)
        bundle = {}
        qid = item.get("send_queue_id")
        row = None
        if qid:
            try:
                row = memory.get_send_queue_item(int(qid))
                bundle = bundle_from_any(row) if row else {}
            except Exception:
                bundle = {}
        lead = None
        lead_id = (item.get("lead_id") or (row or {}).get("lead_id") or "").strip()
        if lead_id:
            try:
                lead = memory.get_lead(lead_id)
            except Exception:
                lead = None
        bundle = enrich_queue_bundle(bundle, lead=lead, pipeline_item=item)
        if not (bundle.get("search_name") or "").strip():
            from .memory import resolve_search_name

            bundle["search_name"] = resolve_search_name(
                {
                    "label": item.get("search_name") or "",
                    "icp_text": item.get("icp_text") or "",
                }
            )
        signal_text = (bundle.get("signal_text") or "").strip()
        contacts_line = format_contacts_line(bundle.get("contacts") or [])
        n_msg = len(bundle.get("selected_messages") or [])
        st.markdown(
            pipeline_card_html(
                item,
                similar_n=len(hits),
                signal_text=signal_text,
                contacts_line=contacts_line,
            ),
            unsafe_allow_html=True,
        )
        if n_msg:
            st.caption(f"{n_msg} selected message(s) queued for this company.")
        render_similar_highlight(
            item,
            hits,
            key=f"q-sim-go-{item.get('id')}",
            allow_queue=True,
        )

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
                height=80,
                key=f"q-note-{item['id']}",
            )
            st.caption("Mark success or failure after the conversation is ongoing.")

        left, right = st.columns(2)
        with left:
            if not can_edit:
                st.caption("View only — the owner advances this item.")
            elif not actions:
                st.caption(f"Closed as {status_label(current)}.")
            elif len(actions) == 1:
                code, label = actions[0]
                if st.button(
                    label,
                    key=f"q-go-{code}-{item['id']}",
                    use_container_width=True,
                    type="primary",
                ):
                    _advance(memory, item, code, comment, is_admin=is_admin)
            else:
                sub = st.columns(len(actions))
                for col, (code, label) in zip(sub, actions):
                    with col:
                        if st.button(
                            label,
                            key=f"q-go-{code}-{item['id']}",
                            use_container_width=True,
                            type="primary",
                        ):
                            _advance(memory, item, code, comment, is_admin=is_admin)
        with right:
            if can_remove:
                if st.button(
                    "Remove from queue",
                    key=f"q-remove-{item.get('id')}",
                    use_container_width=True,
                ):
                    try:
                        memory.remove_pipeline_item(int(item["id"]), as_admin=is_admin)
                        st.toast(f"Removed {item.get('company') or 'item'} from queue")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            else:
                st.caption("")

        detail_key = f"q-detail-open-{item.get('id')}"
        if detail_key not in st.session_state:
            st.session_state[detail_key] = False
        if st.button(
            "Hide detailed view" if st.session_state[detail_key] else "Detailed view",
            key=f"q-detail-btn-{item.get('id')}",
            use_container_width=True,
        ):
            st.session_state[detail_key] = not st.session_state[detail_key]
            st.rerun()

        if st.session_state.get(detail_key):
            snap = bundle.get("lead_snapshot")
            msgs = bundle.get("selected_messages") or []
            if snap:
                st.markdown(detail_html(snap, selected_only=True), unsafe_allow_html=True)
            elif lead:
                st.markdown(detail_html(lead, omit_drafts=False), unsafe_allow_html=True)
                if msgs:
                    st.markdown("##### Selected messages")
                    for msg in msgs:
                        st.markdown(
                            f"**{(msg.get('person_name') or 'Contact')}** · "
                            f"{(msg.get('kind') or '').title()}"
                        )
                        st.text(msg.get("body") or "")
            elif msgs:
                for msg in msgs:
                    st.markdown(
                        f"**{(msg.get('person_name') or 'Contact')}** · "
                        f"{(msg.get('kind') or '').title()}"
                    )
                    st.text(msg.get("body") or "")
            else:
                st.markdown(pipeline_detail_html(item, show_owner=False), unsafe_allow_html=True)
                st.caption("No selected-message bundle stored for this older queue item.")
        st.divider()


def render_results_similarity(memory, lead: dict, *, owner_email: str) -> None:
    hits = memory.find_similar_pipeline(
        lead=lead,
        exclude_owner_lead=(owner_email, lead.get("lead_id") or ""),
    )
    if not hits:
        return
    render_similar_highlight(
        None,
        hits,
        key=f"res-sim-go-{lead.get('lead_id')}",
        allow_queue=True,
    )


def render_admin_pipeline(memory) -> None:
    items = memory.list_team_pipeline()
    stats = memory.pipeline_stats(team=True)
    events = memory.admin_list_pipeline_events(limit=250)
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Pipeline", stats.get("total") or 0)
    m2.metric("Queued", stats.get("queued") or 0)
    m3.metric("Outreach sent", stats.get("outreach_sent") or 0)
    m4.metric("Ongoing", stats.get("ongoing") or 0)
    m5.metric("Success", stats.get("success") or 0)
    m6.metric("Failure", stats.get("failure") or 0)

    st.markdown("##### All pipeline items")
    if items:
        st.dataframe(
            [
                {
                    "owner": i.get("owner_email") or "",
                    "company": i.get("company") or "",
                    "person": i.get("person_name") or "",
                    "status": i.get("pipeline_status") or "",
                    "comment": _clip(i.get("comment") or "", 80),
                    "icp": _clip(i.get("search_name") or i.get("icp_text") or "", 50),
                    "entity": i.get("company_entity_id") or "",
                    "updated": i.get("updated_at") or "",
                }
                for i in items
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No pipeline items yet.")

    st.markdown("##### Activity log")
    if events:
        st.dataframe(
            [
                {
                    "when": e.get("at") or "",
                    "actor": e.get("owner_email") or "",
                    "item owner": e.get("item_owner") or "",
                    "company": e.get("company") or "",
                    "action": e.get("action") or "",
                    "from": e.get("from_status") or "",
                    "to": e.get("to_status") or "",
                    "comment": e.get("comment") or "",
                }
                for e in events
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No pipeline events yet.")
