"""Workspace Lists — curated collections of Signal Desk news stories + deep research."""

from __future__ import annotations

import html
from datetime import datetime, timezone

import streamlit as st

from .memory import Memory
from .news_deep import (
    NEWS_EVENT_TAG,
    deep_research_pending_on_list,
    is_junk_news_url,
    news_event_icp_text,
    news_event_search_name,
    sanitize_news_lead,
    unwrap_article_url,
)
from .news_lists import NewsListStore
from .news_ui import news_card_html
from .outreach_queue import (
    apply_target_edits,
    can_enqueue_company,
    company_queue_payload,
    list_message_targets,
    selected_messages,
)
from .ui import detail_html


def _esc(value: str | None) -> str:
    return html.escape((value or "").strip())


def _fmt_when(iso: str) -> str:
    text = (iso or "").strip().replace("Z", "+00:00")
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text[:16].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d %b %Y · %H:%M UTC")


def _enriched_badge(item: dict) -> str:
    if item.get("is_enriched"):
        return '<span class="fx-pill fx-pill-enriched">Enriched</span>'
    if (item.get("deep_error") or "").strip():
        return '<span class="fx-pill fx-pill-warn">Research failed</span>'
    return '<span class="fx-pill fx-pill-not-enriched">Not enriched</span>'


def render_workspace_lists(
    *,
    memory: Memory,
    owner_email: str,
    openai_key: str = "",
    tavily_key: str = "",
) -> None:
    store = NewsListStore(memory.path, owner_email=owner_email)
    if "ws_list_id" not in st.session_state:
        st.session_state.ws_list_id = ""
    if "ws_list_rename_id" not in st.session_state:
        st.session_state.ws_list_rename_id = ""
    if "ws_list_open_news_id" not in st.session_state:
        st.session_state.ws_list_open_news_id = ""

    st.markdown("##### Lists")
    st.caption(
        "Curated sets of Signal Desk stories — not tied to ICP search. "
        "Create a list here, add articles from Signal Desk, then run Deep research."
    )

    with st.expander("Create a new list", expanded=False):
        new_name = st.text_input("List name", key="ws-list-new-name", placeholder="e.g. India Series B this week")
        new_desc = st.text_area(
            "Short description",
            key="ws-list-new-desc",
            height=80,
            placeholder="Optional — what this list is for",
        )
        if st.button("Create list", type="primary", use_container_width=True, key="ws-list-create"):
            if not (new_name or "").strip():
                st.error("Give the list a name.")
            else:
                created = store.create_list(new_name, new_desc)
                st.session_state.ws_list_id = created.get("list_id") or ""
                st.session_state.ws_list_rename_id = ""
                st.session_state.ws_list_open_news_id = ""
                st.toast(f"Created “{created.get('name') or 'list'}”")
                st.rerun()

    lists = store.list_lists()
    if not lists:
        st.info("No lists yet — create one above, then add stories from Signal Desk.")
        return

    options = [""] + [l["list_id"] for l in lists]
    labels = {
        "": "Select a list…",
        **{
            l["list_id"]: f"{l.get('name') or 'Untitled'} · {int(l.get('item_count') or 0)} stories"
            for l in lists
        },
    }
    current = st.session_state.ws_list_id
    if current not in options:
        current = ""
        st.session_state.ws_list_id = ""

    pick = st.selectbox(
        "Your lists",
        options,
        index=options.index(current) if current in options else 0,
        format_func=lambda lid: labels.get(lid, lid),
        key="ws-list-pick",
    )
    if pick != st.session_state.ws_list_id:
        st.session_state.ws_list_id = pick
        st.session_state.ws_list_rename_id = ""
        st.session_state.ws_list_open_news_id = ""
        st.rerun()

    lid = (st.session_state.ws_list_id or "").strip()
    if not lid:
        return

    meta = store.get_list(lid)
    if not meta:
        st.session_state.ws_list_id = ""
        st.warning("That list is no longer available.")
        return

    st.markdown(
        f"""
<div class="fx-panel-hero" style="margin-top:0.75rem;">
  <p class="fx-kicker">Selected list</p>
  <h2>{_esc(meta.get("name") or "Untitled")}</h2>
  <p>Created {_esc(_fmt_when(meta.get("created_at") or ""))}
 · {int(meta.get("item_count") or 0)} stor{"y" if int(meta.get("item_count") or 0) == 1 else "ies"}</p>
  {f"<p>{_esc(meta.get('description') or '')}</p>" if (meta.get("description") or "").strip() else ""}
</div>
""",
        unsafe_allow_html=True,
    )

    b1, b2, b3 = st.columns(3)
    with b1:
        if st.session_state.ws_list_rename_id == lid:
            if st.button("Cancel edit", use_container_width=True, key="ws-list-ren-cancel"):
                st.session_state.ws_list_rename_id = ""
                st.rerun()
        else:
            if st.button("Rename / edit description", use_container_width=True, key="ws-list-ren"):
                st.session_state.ws_list_rename_id = lid
                st.rerun()
    with b2:
        if st.button("Delete list", use_container_width=True, key="ws-list-del", type="secondary"):
            store.soft_delete_list(lid)
            st.session_state.ws_list_id = ""
            st.session_state.ws_list_rename_id = ""
            st.session_state.ws_list_open_news_id = ""
            st.toast("List deleted")
            st.rerun()
    with b3:
        pending = store.pending_deep_research_ids(lid)
        label = (
            f"Deep research ({len(pending)} new)"
            if pending
            else "Deep research (all done)"
        )
        if st.button(
            label,
            type="primary",
            use_container_width=True,
            key="ws-list-deep",
            disabled=not pending or not (openai_key or "").strip(),
        ):
            status = st.empty()
            with st.spinner(
                "Deep researching new stories in parallel — contacts, proofs, outreach…"
            ):
                def _prog(i: int, total: int, title: str) -> None:
                    status.caption(f"Researching {i}/{total}: {title[:80]}")

                result = deep_research_pending_on_list(
                    list_id=lid,
                    list_store=store,
                    memory=memory,
                    openai_key=openai_key,
                    tavily_key=tavily_key,
                    on_progress=_prog,
                )
            status.empty()
            st.toast(
                f"Deep research done — {result.get('ok') or 0} enriched"
                + (f", {result.get('failed') or 0} failed" if result.get("failed") else "")
            )
            if result.get("errors"):
                with st.expander("Research errors", expanded=False):
                    for err in result["errors"][:20]:
                        st.caption(err)
            st.rerun()
        if not (openai_key or "").strip():
            st.caption("Server OPENAI_API_KEY required for Deep research.")
        elif not pending:
            st.caption("All stories in this list are already enriched. Add new articles to research again.")

    if st.session_state.ws_list_rename_id == lid:
        ren_name = st.text_input("List name", value=meta.get("name") or "", key=f"ws-list-ren-name-{lid}")
        ren_desc = st.text_area(
            "Short description",
            value=meta.get("description") or "",
            height=80,
            key=f"ws-list-ren-desc-{lid}",
        )
        if st.button("Save changes", type="primary", use_container_width=True, key=f"ws-list-ren-save-{lid}"):
            store.update_list(lid, name=ren_name, description=ren_desc)
            st.session_state.ws_list_rename_id = ""
            st.toast("List updated")
            st.rerun()

    items = store.list_items_with_news(lid)
    if not items:
        st.caption("This list is empty. Open Signal Desk, select stories, and add them to this list.")
        return

    open_id = (st.session_state.ws_list_open_news_id or "").strip()
    if open_id:
        opened = next((i for i in items if (i.get("news_id") or "") == open_id), None)
        if opened:
            _render_article_detail(
                store,
                memory,
                meta=meta,
                item=opened,
                openai_key=openai_key,
            )
            return

    enriched_n = sum(1 for i in items if i.get("is_enriched"))
    st.markdown(f"##### Stories in this list · {len(items)} · {enriched_n} enriched")
    st.caption("Click Open on an enriched story to see full research (proofs, Why Frequency, drafts) and queue it.")

    for idx, item in enumerate(items, start=1):
        nid = (item.get("news_id") or "").strip()
        st.html(_enriched_badge(item))
        st.markdown(news_card_html(item, rank=idx), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if item.get("is_enriched"):
                if st.button("Open research", key=f"ws-list-open-{lid}-{nid}", use_container_width=True, type="primary"):
                    st.session_state.ws_list_open_news_id = nid
                    st.rerun()
            elif (item.get("deep_error") or "").strip():
                st.caption((item.get("deep_error") or "").strip())
            else:
                st.caption("Run Deep research to enrich this story.")
        with c2:
            if nid and st.button(
                "Remove from list",
                key=f"ws-list-rm-{lid}-{nid}",
                use_container_width=True,
            ):
                store.remove_items(lid, [nid])
                if st.session_state.ws_list_open_news_id == nid:
                    st.session_state.ws_list_open_news_id = ""
                st.toast("Removed from list")
                st.rerun()


def _render_article_detail(
    store: NewsListStore,
    memory: Memory,
    *,
    meta: dict,
    item: dict,
    openai_key: str = "",
) -> None:
    lead = item.get("lead") if isinstance(item.get("lead"), dict) else None
    nid = (item.get("news_id") or "").strip()
    list_name = (meta.get("name") or "").strip()
    article_url = unwrap_article_url(
        (item.get("url") or "").strip(),
        (item.get("snippet") or "").strip(),
    )

    top_l, top_r = st.columns([0.22, 0.78])
    with top_l:
        if st.button("← Back to list", key=f"ws-list-back-{nid}", use_container_width=True):
            st.session_state.ws_list_open_news_id = ""
            st.rerun()
    with top_r:
        st.caption(f"{NEWS_EVENT_TAG} · deep research dossier")

    title = _esc(item.get("title") or "Story")
    link_bit = ""
    if article_url and not is_junk_news_url(article_url):
        link_bit = (
            f'<p class="fx-dh-meta"><a href="{_esc(article_url)}" target="_blank" '
            f'rel="noopener noreferrer">Open original article ↗</a></p>'
        )
    st.html(
        f"""
<div class="fx-news-research-hero">
  <p class="fx-kicker">{_esc(NEWS_EVENT_TAG)}</p>
  <h2>{title}</h2>
  {link_bit}
</div>
"""
    )

    if not lead:
        st.warning("No deep-research payload on this story yet.")
        return

    # Strip aggregator URLs from older saves; keep company website/channel clean.
    lead = sanitize_news_lead(dict(lead))

    # st.html keeps dossier CSS/layout intact (markdown collapses structure into plain text).
    st.html(
        f'<div class="fx-news-research-shell">{detail_html(lead, omit_drafts=True)}</div>'
    )

    st.html(
        '<div class="fx-news-outreach-head">'
        "<h3>Outreach messages</h3>"
        "<p>Tick at least one message, then add to queue. Queued items are tagged "
        f"{_esc(NEWS_EVENT_TAG)}.</p></div>"
    )

    _ensure_outreach_widget_defaults(lead, nid)
    lead = _sync_list_message_widgets(lead, nid)

    for target in list_message_targets(lead):
        key = target["target_key"]
        label = _esc(target.get("label") or "Contact")
        role = _esc(target.get("role") or "")
        role_bit = f" · {role}" if role else ""
        st.html(
            f'<div class="fx-news-msg-label"><strong>{label}</strong>{role_bit}</div>'
        )
        e1, e2 = st.columns(2)
        with e1:
            st.text_area(
                "Email draft",
                key=f"list-edit-mail-{nid}-{key}",
                height=160,
            )
            st.checkbox(
                "Queue email",
                key=f"list-sel-mail-{nid}-{key}",
                disabled=not str(st.session_state.get(f"list-edit-mail-{nid}-{key}") or "").strip(),
            )
        with e2:
            st.text_area(
                "LinkedIn note",
                key=f"list-edit-li-{nid}-{key}",
                height=160,
            )
            st.checkbox(
                "Queue LinkedIn",
                key=f"list-sel-li-{nid}-{key}",
                disabled=not str(st.session_state.get(f"list-edit-li-{nid}-{key}") or "").strip(),
            )
        apply_target_edits(
            lead,
            target_key=key,
            email_draft=st.session_state.get(f"list-edit-mail-{nid}-{key}"),
            linkedin_note=st.session_state.get(f"list-edit-li-{nid}-{key}"),
            select_email=st.session_state.get(f"list-sel-mail-{nid}-{key}"),
            select_linkedin=st.session_state.get(f"list-sel-li-{nid}-{key}"),
        )

    lead = _sync_list_message_widgets(lead, nid)
    store.save_deep_research(meta.get("list_id") or "", nid, lead)

    ok, reason = can_enqueue_company(lead)
    q1, q2 = st.columns([0.7, 0.3])
    with q1:
        if st.button(
            "Add to queue",
            type="primary",
            use_container_width=True,
            key=f"list-queue-{nid}",
            disabled=not ok,
        ):
            note = _enqueue_news_lead(
                memory,
                lead,
                list_name=list_name,
                article=item,
            )
            st.toast(note)
            st.rerun()
    with q2:
        n_sel = len(selected_messages(lead))
        st.caption(f"{n_sel} message(s) selected" if n_sel else (reason or "Select a message"))


def _ensure_outreach_widget_defaults(lead: dict, nid: str) -> None:
    """Seed Streamlit widget state once so Queue email/LI start checked when drafts exist."""
    for target in list_message_targets(lead):
        key = target["target_key"]
        mail_key = f"list-edit-mail-{nid}-{key}"
        li_key = f"list-edit-li-{nid}-{key}"
        sel_mail = f"list-sel-mail-{nid}-{key}"
        sel_li = f"list-sel-li-{nid}-{key}"
        if mail_key not in st.session_state:
            st.session_state[mail_key] = target.get("email_draft") or ""
        if li_key not in st.session_state:
            st.session_state[li_key] = target.get("linkedin_note") or ""
        if sel_mail not in st.session_state:
            st.session_state[sel_mail] = bool(
                target.get("select_email")
                or (st.session_state.get(mail_key) or "").strip()
            )
        if sel_li not in st.session_state:
            st.session_state[sel_li] = bool(
                target.get("select_linkedin")
                or (st.session_state.get(li_key) or "").strip()
            )


def _sync_list_message_widgets(lead: dict, nid: str) -> dict:
    """Pull Streamlit widget values into the lead before queue / save."""
    for target in list_message_targets(lead):
        key = target["target_key"]
        apply_target_edits(
            lead,
            target_key=key,
            email_draft=st.session_state.get(
                f"list-edit-mail-{nid}-{key}", target.get("email_draft") or ""
            ),
            linkedin_note=st.session_state.get(
                f"list-edit-li-{nid}-{key}", target.get("linkedin_note") or ""
            ),
            select_email=st.session_state.get(
                f"list-sel-mail-{nid}-{key}", target.get("select_email")
            ),
            select_linkedin=st.session_state.get(
                f"list-sel-li-{nid}-{key}", target.get("select_linkedin")
            ),
        )
    return lead


def _enqueue_news_lead(
    memory: Memory,
    lead: dict,
    *,
    list_name: str,
    article: dict,
) -> str:
    ok, reason = can_enqueue_company(lead)
    if not ok:
        return reason
    search_name = news_event_search_name(list_name, article.get("title") or "")
    icp_text = news_event_icp_text(article, list_name=list_name)
    lead = dict(lead)
    lead["source_kind"] = "news_event"
    lead["search_name"] = search_name
    payload = company_queue_payload(lead, search_name=search_name, icp_text=icp_text)
    qid = memory.enqueue_send(payload)
    lead["outreach_status"] = "queued"
    memory.upsert_pipeline_from_lead(
        lead,
        send_queue_id=qid,
        query_id=(lead.get("query_id") or "").strip(),
        icp_text=icp_text,
        search_name=search_name,
        channel="company",
    )
    n_msg = len(payload.get("bundle", {}).get("selected_messages") or selected_messages(lead))
    return (
        f"Queued {lead.get('name') or 'company'} · {NEWS_EVENT_TAG} · "
        f"{n_msg} selected message(s) · dry run only"
    )
