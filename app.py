"""Frequency Lead Intelligence Agent — Streamlit review queue."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from frequency_agent import memory as memory_mod
from frequency_agent import send_queue as send_queue_mod
from frequency_agent import contacts as contacts_mod
from frequency_agent import extract as extract_mod
from frequency_agent import graph as graph_mod

importlib.reload(memory_mod)
importlib.reload(send_queue_mod)
importlib.reload(extract_mod)
importlib.reload(contacts_mod)
importlib.reload(graph_mod)

from frequency_agent.export import export_leads, leads_to_rows
from frequency_agent.graph import run_agent
from frequency_agent.llm import load_json
from frequency_agent.memory import Memory, icp_fingerprint
from frequency_agent.plugin_export import (
    apollo_csv_text,
    apollo_search_clipboard,
    linkedin_url_list,
    plugin_rows,
    write_plugin_exports,
)
from frequency_agent.search_export import search_csv_text
from frequency_agent.send_queue import append_jsonl, can_enqueue, queue_payload
from frequency_agent.ui import detail_html, funnel_html, hero, inject, lead_card

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)

st.set_page_config(
    page_title="Frequency · Lead Intelligence",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(inject(), unsafe_allow_html=True)

if "leads" not in st.session_state:
    st.session_state.leads = []
if "funnel" not in st.session_state:
    st.session_state.funnel = {}
if "logs" not in st.session_state:
    st.session_state.logs = []
if "selected" not in st.session_state:
    st.session_state.selected = 0
if "queries" not in st.session_state:
    st.session_state.queries = []
if "active_run_id" not in st.session_state:
    st.session_state.active_run_id = ""
if "active_query_id" not in st.session_state:
    st.session_state.active_query_id = ""
if "active_icp_hash" not in st.session_state:
    st.session_state.active_icp_hash = ""
if "csv_path" not in st.session_state:
    st.session_state.csv_path = ""
if "service_line_saved" not in st.session_state:
    st.session_state.service_line_saved = "exec_search"
if "icp_text_saved" not in st.session_state:
    st.session_state.icp_text_saved = ""
if "hydrated" not in st.session_state:
    st.session_state.hydrated = False
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "query"
if "view_label" not in st.session_state:
    st.session_state.view_label = ""

presets = load_json("icp_presets.json")
memory = Memory()
openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()

# Restore latest query session on first load
if not st.session_state.hydrated:
    sessions = memory.list_query_sessions(limit=1)
    if sessions:
        qid = sessions[0]["query_id"]
        st.session_state.active_query_id = qid
        st.session_state.leads = memory.leads_for_query(qid)
        st.session_state.service_line_saved = sessions[0].get("service_line") or "exec_search"
        st.session_state.icp_text_saved = sessions[0].get("icp_text") or ""
        runs = memory.list_runs_for_query(qid)
        if runs:
            latest = memory.load_run(runs[0]["run_id"])
            if latest:
                st.session_state.funnel = latest.get("funnel") or {}
                st.session_state.logs = latest.get("logs") or []
                st.session_state.queries = latest.get("queries") or []
                st.session_state.active_run_id = latest.get("run_id") or ""
                st.session_state.csv_path = latest.get("csv_path") or ""
        st.session_state.view_label = sessions[0].get("label") or qid
    st.session_state.hydrated = True


def apply_query(query_id: str) -> None:
    session = memory.get_query_session(query_id)
    if not session:
        return
    st.session_state.active_query_id = query_id
    st.session_state.leads = memory.leads_for_query(query_id)
    st.session_state.service_line_saved = session.get("service_line") or "exec_search"
    st.session_state.icp_text_saved = session.get("icp_text") or ""
    st.session_state.selected = 0
    st.session_state.view_mode = "query"
    st.session_state.view_label = session.get("label") or query_id
    runs = memory.list_runs_for_query(query_id)
    if runs:
        loaded = memory.load_run(runs[0]["run_id"])
        if loaded:
            st.session_state.funnel = loaded.get("funnel") or {}
            st.session_state.logs = loaded.get("logs") or []
            st.session_state.queries = loaded.get("queries") or []
            st.session_state.active_run_id = loaded.get("run_id") or ""
            st.session_state.csv_path = loaded.get("csv_path") or ""


def apply_run(run: dict) -> None:
    st.session_state.leads = run.get("leads") or []
    st.session_state.funnel = run.get("funnel") or {}
    st.session_state.logs = run.get("logs") or []
    st.session_state.queries = run.get("queries") or []
    st.session_state.active_run_id = run.get("run_id") or ""
    st.session_state.active_icp_hash = run.get("icp_hash") or ""
    st.session_state.csv_path = run.get("csv_path") or ""
    st.session_state.service_line_saved = run.get("service_line") or "exec_search"
    st.session_state.icp_text_saved = run.get("icp") or ""
    st.session_state.selected = 0
    st.session_state.view_mode = "run"
    st.session_state.view_label = f"Fetch {run.get('run_id', '')[:12]} · {len(st.session_state.leads)} leads"


def _query_label(q: dict) -> str:
    return (
        f"{(q.get('last_run_at') or q.get('created_at') or '')[:16]} · "
        f"{q.get('lead_count', 0)} leads · "
        f"{(q.get('label') or q['query_id'])[:48]}"
    )


def _run_label(r: dict) -> str:
    return (
        f"{(r.get('finished') or r.get('started') or '')[:16]} · "
        f"{r.get('new_count', r.get('lead_count', 0))} leads · "
        f"skipped {r.get('skipped_seen') or 0} · "
        f"{(r.get('label') or r['run_id'])[:40]}"
    )


with st.sidebar:
    st.markdown(
        '<div class="fx-mark"><div class="fx-fin"></div>'
        '<p class="fx-word" style="font-size:20px">FREQUENCY</p></div>'
        '<p style="color:#8a9a9e;font-size:12px;margin-top:-6px">Keys load from .env · searches persist</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="fx-badges">'
        f'<span class="badge {"high" if openai_key else "low"}">'
        f'{"OpenAI loaded" if openai_key else "OpenAI missing"}</span>'
        f'<span class="badge {"high" if tavily_key else "low"}">'
        f'{"Tavily loaded" if tavily_key else "Tavily missing"}</span></div>',
        unsafe_allow_html=True,
    )
    stats = memory.memory_stats()
    send_stats = (
        memory.send_queue_stats()
        if hasattr(memory, "send_queue_stats")
        else {"queued": 0, "dry_run_sent": 0, "held": 0}
    )
    st.markdown(
        f"**Memory** · {stats['seen']} leads · {stats.get('queries', 0)} queries · "
        f"{stats.get('runs', 0)} fetches · {stats['do_not_contact']} do-not-contact"
    )
    st.markdown(
        f"**Dry-run queue** · {send_stats['queued']} queued · "
        f"{send_stats['dry_run_sent']} logged · {send_stats['held']} held"
    )
    st.caption("DRY RUN MODE — nothing is delivered to a real inbox or LinkedIn.")

    if st.button("Clear all results", use_container_width=True, type="secondary"):
        memory.clear_all_data()
        for key in (
            "leads", "funnel", "logs", "queries", "active_run_id", "active_query_id",
            "csv_path", "icp_text_saved", "service_line_saved", "selected", "view_label",
        ):
            if key in st.session_state:
                st.session_state[key] = [] if key in {"leads", "logs", "queries"} else ""
        st.session_state.hydrated = True
        st.toast("All queries, leads, and runs cleared.")
        st.rerun()

    query_sessions = memory.list_query_sessions(limit=40)
    if query_sessions:
        st.markdown("#### Your queries")
        labels = {q["query_id"]: _query_label(q) for q in query_sessions}
        options = [q["query_id"] for q in query_sessions]
        current_q = st.session_state.active_query_id if st.session_state.active_query_id in labels else options[0]
        pick_q = st.selectbox(
            "Load a saved query",
            options,
            index=options.index(current_q) if current_q in options else 0,
            format_func=lambda qid: labels.get(qid, qid),
            help="Each ICP you enter is its own query session. Companies dedupe only within that query.",
        )
        if pick_q != st.session_state.active_query_id:
            apply_query(pick_q)
            st.rerun()

    past = memory.list_runs(limit=20)
    if past:
        st.markdown("#### Recent fetches")
        labels = {r["run_id"]: _run_label(r) for r in past}
        options = ["— current view —"] + [r["run_id"] for r in past]
        current = st.session_state.active_run_id if st.session_state.active_run_id in labels else "— current view —"
        pick = st.selectbox(
            "Load a single fetch run",
            options,
            index=options.index(current) if current in options else 0,
            format_func=lambda rid: labels.get(rid, rid),
            help="One fetch = one Run agent / Fetch more click. Use **All queries** tab for the full history.",
        )
        if pick != "— current view —" and pick != st.session_state.active_run_id:
            loaded = memory.load_run(pick)
            if loaded:
                apply_run(loaded)
                st.rerun()

    if st.session_state.leads:
        # Full contacts CSV for active search
        search_csv = search_csv_text(
            st.session_state.leads,
            run_id=st.session_state.active_run_id or "session",
        )
        st.download_button(
            "Download this search CSV",
            search_csv.encode("utf-8"),
            file_name=f"search_{st.session_state.active_run_id or 'session'}_contacts.csv",
            mime="text/csv",
            use_container_width=True,
            help="All companies + emails, phones, LinkedIn, X, and other links from this search",
        )
        csv_path, _json_path = export_leads(st.session_state.leads, ROOT / "output")
        df = pd.DataFrame(leads_to_rows(st.session_state.leads))
        st.download_button(
            "Download sample_output.csv",
            df.to_csv(index=False).encode("utf-8"),
            file_name="sample_output.csv",
            mime="text/csv",
            use_container_width=True,
        )
        if st.session_state.csv_path:
            st.caption(f"Auto-saved: {Path(st.session_state.csv_path).name}")
        else:
            st.caption(f"Also in output/{csv_path.name}")

st.markdown(hero(), unsafe_allow_html=True)

if st.session_state.active_query_id:
    qs = memory.get_query_session(st.session_state.active_query_id)
    if qs:
        n_leads = len(memory.leads_for_query(st.session_state.active_query_id))
        st.caption(
            f"**Active query** `{st.session_state.active_query_id}` · "
            f"created {qs.get('created_at', '')[:16]} · last fetch {qs.get('last_run_at', '')[:16]} · "
            f"**{n_leads} companies** total for this query (dedup within query only)."
        )
elif st.session_state.active_run_id and st.session_state.leads:
    st.caption(
        f"**Viewing fetch** `{st.session_state.active_run_id}` · {len(st.session_state.leads)} leads from that run."
    )

default_sl = st.session_state.service_line_saved if st.session_state.service_line_saved in {
    "exec_search", "fractional_cxo", "capital_advisory"
} else "exec_search"

c1, c2, c3 = st.columns([1.1, 1.6, 0.8])
with c1:
    service_line = st.selectbox(
        "Service line",
        ["exec_search", "fractional_cxo", "capital_advisory"],
        index=["exec_search", "fractional_cxo", "capital_advisory"].index(default_sl),
        format_func=lambda x: {
            "exec_search": "Executive search",
            "fractional_cxo": "Fractional CXO",
            "capital_advisory": "Capital advisory",
        }[x],
    )
with c2:
    preset_key = st.selectbox(
        "ICP preset",
        list(presets.keys()),
        format_func=lambda k: presets[k]["label"],
    )
with c3:
    st.write("")
    col_a, col_b = st.columns(2)
    with col_a:
        run_new = st.button("New query", use_container_width=True, type="primary")
    with col_b:
        fetch_more = st.button(
            "Fetch more",
            use_container_width=True,
            help="Same query — finds more companies without repeating ones already linked to this query.",
            disabled=not st.session_state.active_query_id,
        )

# Prefer restored ICP text when it matches a prior run; otherwise preset
icp_default = st.session_state.icp_text_saved or presets[preset_key]["text"]
icp_text = st.text_area(
    "Ideal customer profile",
    value=icp_default,
    height=90,
    key=f"icp-{preset_key}",
)

run = run_new or fetch_more

if not openai_key:
    st.error("OPENAI_API_KEY is empty in `.env`. Add it and refresh.")
elif not tavily_key:
    st.warning("TAVILY_API_KEY is empty — search will fall back to DuckDuckGo.")

if run:
    if not openai_key:
        st.error("Cannot run without OPENAI_API_KEY in `.env`.")
    else:
        status = st.status("Researching public sources…", expanded=True)
        labels = {
            "parse_icp": "Parsing ICP (+ loading companies already in this query)",
            "expand_queries": "Expanding search queries",
            "search_web": "Searching the public web",
            "extract_companies": "Extracting companies from sources",
            "cluster": "Deduplicating · skipping companies already in this query",
            "enrich": "Verifying signals, scoring, interest briefs, drafting",
        }

        query_id = ""
        if fetch_more and st.session_state.active_query_id:
            query_id = st.session_state.active_query_id
        elif run_new:
            query_id = memory.create_query_session(icp_text, service_line)
            st.session_state.active_query_id = query_id

        def on_update(node, state):
            status.write(labels.get(node, node))
            if state.get("queries"):
                st.session_state.queries = state["queries"]
            if state.get("funnel"):
                st.session_state.funnel = state["funnel"]
            if state.get("logs"):
                st.session_state.logs = state["logs"]

        try:
            result = run_agent(
                icp_text=icp_text,
                service_line=service_line,
                openai_key=openai_key,
                tavily_key=tavily_key,
                query_id=query_id,
                on_update=on_update,
            )
            if result.get("error"):
                status.update(label="Stopped", state="error")
                st.error(result["error"])
            else:
                st.session_state.leads = memory.leads_for_query(query_id) if query_id else (result.get("leads") or [])
                st.session_state.funnel = result.get("funnel") or {}
                st.session_state.logs = result.get("logs") or []
                st.session_state.queries = result.get("queries") or []
                st.session_state.active_run_id = result.get("run_id") or ""
                st.session_state.active_query_id = query_id
                st.session_state.active_icp_hash = result.get("icp_hash") or icp_fingerprint(
                    service_line, icp_text
                )
                st.session_state.csv_path = result.get("csv_path") or ""
                st.session_state.service_line_saved = service_line
                st.session_state.icp_text_saved = icp_text
                st.session_state.selected = 0
                st.session_state.view_mode = "query"
                skipped = result.get("skipped_seen") or 0
                n_new = len(result.get("leads") or [])
                n_total = len(st.session_state.leads)
                status.update(
                    label=f"Done — {n_new} new this fetch, {n_total} total for query, {skipped} skipped (already in query)",
                    state="complete",
                )
                if n_new == 0 and skipped:
                    st.warning(
                        "No **new** companies this fetch — everything matching this query is already linked. "
                        "Try a broader ICP or start a **New query** with different criteria."
                    )
        except Exception as exc:
            status.update(label="Failed", state="error")
            st.exception(exc)

if st.session_state.funnel:
    st.markdown(funnel_html(st.session_state.funnel), unsafe_allow_html=True)

if st.session_state.queries:
    with st.expander("Queries the agent actually ran", expanded=False):
        for q in st.session_state.queries:
            st.code(q)

if st.session_state.logs:
    with st.expander("Run log", expanded=False):
        for line in st.session_state.logs:
            st.write("· " + line)

DRY_RUN_LOG = ROOT / "output" / "dry_run_send_log.jsonl"


def enqueue_lead(lead: dict, include_linkedin: bool = True) -> tuple[bool, str]:
    ok, reason = can_enqueue(lead)
    if not ok:
        return False, reason
    qid = memory.enqueue_send(queue_payload(lead, "email"))
    extra = 0
    if include_linkedin and (lead.get("linkedin_note") or "").strip() and not (lead.get("linkedin_note") or "").startswith("[BLOCKED"):
        memory.enqueue_send(queue_payload(lead, "linkedin"))
        extra = 1
    lead["outreach_status"] = "queued"
    return True, f"Queued email #{qid}" + (" + LinkedIn note" if extra else "") + " — dry run only"


def dispatch_item(row: dict) -> None:
    result = memory.dry_run_dispatch(int(row["id"]))
    if not result:
        return
    append_jsonl(
        DRY_RUN_LOG,
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
            "body": result.get("body"),
            "note": result.get("note"),
        },
    )
    for lead in st.session_state.leads:
        if lead.get("lead_id") == result.get("lead_id"):
            lead["outreach_status"] = "dry_run_sent"


leads = st.session_state.leads
review_tab, history_tab, plugin_tab, send_tab = st.tabs(
    ["Review queue", "All queries & results", "Apollo / DAG enrich", "Dry-run send queue"]
)

with review_tab:
    if not leads:
        st.info("Enter an ICP above, then click **New query** (first search) or **Fetch more** (same query, no repeats within it).")
    else:
        left, right = st.columns([0.38, 0.62], gap="large")
        with left:
            st.subheader("Review queue")
            names = [
                f"{(l.get('score') or {}).get('total', 0):02d}  {l.get('name')}  ·  {(l.get('signal') or {}).get('confidence')}  ·  {l.get('outreach_status') or l.get('review_status')}"
                for l in leads
            ]
            idx = st.radio(
                "Leads",
                list(range(len(leads))),
                format_func=lambda i: names[i],
                index=min(st.session_state.selected, len(leads) - 1),
                label_visibility="collapsed",
            )
            st.session_state.selected = idx
            st.markdown(lead_card(leads[idx], active=True), unsafe_allow_html=True)
        with right:
            lead = leads[idx]
            st.markdown(detail_html(lead), unsafe_allow_html=True)
            st.caption("Human actions — nothing is delivered until you dry-run from the send queue, and even then it only writes a log.")
            a, b, c, d = st.columns(4)
            if a.button("Approve", use_container_width=True):
                lead["review_status"] = "approved"
                leads[idx] = lead
                memory.update_review(lead["lead_id"], "approved", lead)
                ok, msg = enqueue_lead(lead)
                st.toast(msg if ok else f"Approved, not queued: {msg}")
                st.rerun()
            if c.button("Reject", use_container_width=True):
                lead["review_status"] = "rejected"
                lead["outreach_status"] = "not_sent"
                leads[idx] = lead
                memory.update_review(lead["lead_id"], "rejected", lead, note="do_not_contact")
                st.toast(f"Rejected {lead['name']} — held in send queue if it was waiting")
                st.rerun()
            edited = st.text_area(
                "Edit email",
                value=lead.get("email_draft") or "",
                height=220,
                key=f"edit-{lead['lead_id']}",
            )
            if b.button("Save edit", use_container_width=True):
                lead["email_draft"] = edited
                lead["review_status"] = "edited"
                leads[idx] = lead
                memory.update_review(lead["lead_id"], "edited", lead)
                st.toast("Edit saved — approve or queue it next")
                st.rerun()
            if d.button("Queue dry-run", use_container_width=True):
                lead["email_draft"] = edited
                if lead.get("review_status") not in {"approved", "edited"}:
                    lead["review_status"] = "edited"
                leads[idx] = lead
                memory.update_review(lead["lead_id"], lead["review_status"], lead)
                ok, msg = enqueue_lead(lead)
                if ok:
                    st.toast(msg)
                else:
                    st.error(msg)
                st.rerun()
            st.caption("Approve auto-queues a dry-run send. Queue dry-run uses the edited text. No SMTP is configured.")

with history_tab:
    st.subheader("All queries & results")
    st.caption(
        "Every ICP you run is a separate query. The same company can appear in multiple queries. "
        "Within one query, **Fetch more** never repeats companies already linked to that query."
    )
    unified = memory.unified_results()
    if not unified:
        st.info("No saved queries yet. Run **New query** above to start.")
    else:
        for block in unified:
            with st.expander(
                f"{block.get('label', block['query_id'])} · {len(block.get('leads') or [])} companies · "
                f"{block.get('fetch_count', 0)} fetch(es) · created {str(block.get('created_at', ''))[:16]}",
                expanded=block["query_id"] == st.session_state.active_query_id,
            ):
                st.markdown(f"**Query ID:** `{block['query_id']}`")
                st.markdown(f"**ICP:** {block.get('icp_text') or '—'}")
                st.markdown(
                    f"**Service line:** {block.get('service_line')} · "
                    f"**Created:** {block.get('created_at')} · **Last fetch:** {block.get('last_run_at')}"
                )
                h1, h2 = st.columns(2)
                if h1.button("Load in review queue", key=f"load-q-{block['query_id']}", use_container_width=True):
                    apply_query(block["query_id"])
                    st.rerun()
                runs = block.get("runs") or []
                if runs:
                    st.markdown("**Fetches for this query**")
                    for r in runs:
                        st.write(
                            f"· {r.get('finished', r.get('started', ''))[:19]} — "
                            f"{r.get('lead_count', 0)} leads this fetch · skipped {r.get('skipped_seen') or 0} dupes in query"
                        )
                q_leads = block.get("leads") or []
                if q_leads:
                    st.markdown("**Companies**")
                    rows = []
                    for l in q_leads:
                        sig = l.get("signal") or {}
                        contact = l.get("contact") or {}
                        rows.append(
                            {
                                "Score": (l.get("score") or {}).get("total", 0),
                                "Company": l.get("name"),
                                "Signal": sig.get("summary", "")[:80],
                                "Contact": contact.get("name"),
                                "Web query": (l.get("discovery_web_query") or "")[:60],
                                "Linked": (l.get("linked_at") or "")[:19],
                            }
                        )
                    st.dataframe(rows, hide_index=True, use_container_width=True)

with plugin_tab:
    st.subheader("Apollo.io / DAG Leads enrichment tray")
    st.info(
        "Public email/phone/LinkedIn/X are captured when found on the open web. "
        "Where email is missing, open the LinkedIn URL with your **Apollo** or **DAG** browser extension "
        "already logged in — no re-login per lead. This app never logs into LinkedIn/Apollo/DAG."
    )
    if not leads:
        st.caption("Run the agent first — people from the review queue appear here.")
    else:
        rows = plugin_rows(leads)
        with_email = sum(1 for r in rows if r.get("Email"))
        with_li = sum(1 for r in rows if r.get("LinkedIn URL"))
        with_phone = sum(1 for r in rows if r.get("Phone"))
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("People", len(rows))
        m2.metric("Public email", with_email)
        m3.metric("LinkedIn URL", with_li)
        m4.metric("Public phone", with_phone)

        st.markdown("#### How to use your plugins")
        st.markdown(
            "1. Install & stay signed into **Apollo.io** and/or **DAG Leads** in Chrome.\n"
            "2. Prefer rows with a **LinkedIn URL** — click **Open** (or download the URL list and open them).\n"
            "3. On each LinkedIn profile, click the extension icon once — it fills email/phone without a new login.\n"
            "4. If LinkedIn is missing, copy the **Apollo search** fallback lines (Name | Company | Domain).\n"
            "5. Download **apollo_dag_enrich.csv** for bulk paste / CRM import."
        )

        if rows:
            paths = write_plugin_exports(leads, ROOT / "output")
            c1, c2, c3 = st.columns(3)
            c1.download_button(
                "Download Apollo/DAG CSV",
                apollo_csv_text(leads),
                file_name="apollo_dag_enrich.csv",
                mime="text/csv",
                use_container_width=True,
            )
            li_text = linkedin_url_list(leads)
            c2.download_button(
                "Download LinkedIn URL list",
                li_text or "# no linkedin urls yet\n",
                file_name="linkedin_profiles.txt",
                mime="text/plain",
                use_container_width=True,
                disabled=not bool(li_text),
            )
            fallback = apollo_search_clipboard(leads)
            c3.download_button(
                "Download Apollo search fallback",
                fallback or "# all people already have LinkedIn URLs\n",
                file_name="apollo_search_fallback.txt",
                mime="text/plain",
                use_container_width=True,
            )
            st.caption(f"Also saved under `output/` · {paths['csv'].name}")

            st.markdown("#### People to enrich")
            for i, row in enumerate(rows):
                with st.container():
                    left, right = st.columns([0.72, 0.28])
                    with left:
                        badges = []
                        if row.get("Email"):
                            badges.append(f"email `{row['Email']}`")
                        if row.get("Phone"):
                            badges.append(f"phone `{row['Phone']}`")
                        if row.get("LinkedIn URL"):
                            badges.append("LinkedIn")
                        if row.get("Twitter/X URL"):
                            badges.append("X")
                        badge_s = " · ".join(badges) if badges else "no public channel yet"
                        st.markdown(
                            f"**{row['Full Name']}** · {row['Title']} @ **{row['Company']}**  \n"
                            f"`{row['Domain'] or 'no domain'}` · {badge_s}  \n"
                            f"{row.get('Apollo Hint') or ''}"
                        )
                    with right:
                        if row.get("LinkedIn URL"):
                            st.link_button(
                                "Open LinkedIn → plugin",
                                row["LinkedIn URL"],
                                use_container_width=True,
                            )
                        elif row.get("Twitter/X URL"):
                            st.link_button(
                                "Open X profile",
                                row["Twitter/X URL"],
                                use_container_width=True,
                            )
                        else:
                            st.caption("No profile URL")
                    if i < len(rows) - 1:
                        st.divider()

            if li_text:
                with st.expander("Copy all LinkedIn URLs"):
                    st.code(li_text)
            if fallback:
                with st.expander("Copy Apollo search fallback (no LinkedIn)"):
                    st.code(fallback)
            with st.expander("Full enrichment table"):
                st.dataframe(rows, hide_index=True, use_container_width=True)

with send_tab:
    st.subheader("Dry-run send queue")
    st.warning("Mode is locked to **dry run**. Messages are written to `output/dry_run_send_log.jsonl` only. No inbox, no LinkedIn, no WhatsApp.")
    qstats = memory.send_queue_stats()
    m1, m2, m3 = st.columns(3)
    m1.metric("Queued", qstats["queued"])
    m2.metric("Dry-run logged", qstats["dry_run_sent"])
    m3.metric("Held", qstats["held"])

    queued = memory.list_send_queue("queued")
    if queued:
        if st.button("Dry-run send all queued", type="primary"):
            for row in queued:
                dispatch_item(row)
            st.toast(f"Logged {len(queued)} dry-run sends — nothing delivered")
            st.rerun()
        for row in queued:
            with st.container():
                st.markdown(
                    f"**{row['company']}** · {row['channel']} · `{row['status']}`  \n"
                    f"To: {row['recipient']}  \n"
                    f"Subject: {row['subject'] or '—'}  \n"
                    f"Queued {row['queued_at']}"
                )
                with st.expander("Body"):
                    st.text(row["body"] or "")
                s1, s2 = st.columns(2)
                if s1.button("Dry-run send", key=f"send-{row['id']}", use_container_width=True):
                    dispatch_item(row)
                    st.toast(f"Dry-run logged for {row['company']} — not delivered")
                    st.rerun()
                if s2.button("Hold", key=f"hold-{row['id']}", use_container_width=True):
                    memory.hold_send(int(row["id"]))
                    st.toast(f"Held {row['company']}")
                    st.rerun()
                st.divider()
    else:
        st.info("Nothing queued. Approve a lead in Review, or click **Queue dry-run**.")

    history = [r for r in memory.list_send_queue() if r["status"] != "queued"]
    if history:
        st.markdown("#### Log")
        st.dataframe(
            [
                {
                    "When": r.get("dispatched_at") or r.get("queued_at"),
                    "Company": r.get("company"),
                    "Channel": r.get("channel"),
                    "To": r.get("recipient"),
                    "Status": r.get("status"),
                    "Mode": r.get("mode"),
                    "Note": r.get("note"),
                }
                for r in history
            ],
            hide_index=True,
            use_container_width=True,
        )
        if DRY_RUN_LOG.exists():
            st.download_button(
                "Download dry-run log",
                DRY_RUN_LOG.read_text(encoding="utf-8"),
                file_name="dry_run_send_log.jsonl",
                mime="application/jsonl",
            )

