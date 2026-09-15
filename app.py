"""Frequency Lead Intelligence Agent — Streamlit review queue."""

from __future__ import annotations

import importlib
import html
import io
import os
import zipfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from frequency_agent import memory as memory_mod
from frequency_agent import send_queue as send_queue_mod
from frequency_agent import contacts as contacts_mod
from frequency_agent import extract as extract_mod
from frequency_agent import channels as channels_mod
from frequency_agent import schemas as schemas_mod
from frequency_agent import icp as icp_mod
from frequency_agent import ui as ui_mod
from frequency_agent import search as search_mod
from frequency_agent import graph as graph_mod
from frequency_agent import outreach as outreach_mod
from frequency_agent import contact_cards as contact_cards_mod
from frequency_agent import auth_ui as auth_ui_mod
from frequency_agent import auth_service as auth_service_mod
from frequency_agent import mailer as mailer_mod
from frequency_agent import clerk_client as clerk_client_mod
from frequency_agent import auth as auth_mod
from frequency_agent import accounts as accounts_mod
from frequency_agent import admin_ui as admin_ui_mod
from frequency_agent import settings_ui as settings_ui_mod
from frequency_agent import jobs as jobs_mod
from frequency_agent import search_export as search_export_mod
from frequency_agent import folder_browse as folder_browse_mod
from frequency_agent import pipeline_ui as pipeline_ui_mod
from frequency_agent import similarity as similarity_mod
from frequency_agent import outreach_queue as outreach_queue_mod
from frequency_agent import repo_ui as repo_ui_mod

importlib.reload(schemas_mod)
importlib.reload(channels_mod)
importlib.reload(icp_mod)
importlib.reload(similarity_mod)
importlib.reload(memory_mod)
importlib.reload(send_queue_mod)
importlib.reload(outreach_queue_mod)
importlib.reload(extract_mod)
importlib.reload(contacts_mod)
importlib.reload(outreach_mod)
importlib.reload(contact_cards_mod)
importlib.reload(ui_mod)
importlib.reload(search_mod)
importlib.reload(search_export_mod)
importlib.reload(folder_browse_mod)
importlib.reload(pipeline_ui_mod)
importlib.reload(repo_ui_mod)
importlib.reload(graph_mod)
importlib.reload(mailer_mod)
importlib.reload(clerk_client_mod)
importlib.reload(auth_mod)
importlib.reload(auth_service_mod)
importlib.reload(accounts_mod)
importlib.reload(settings_ui_mod)
importlib.reload(admin_ui_mod)
# Do not reload jobs_mod — worker threads + reclaim state must stay process-stable.
importlib.reload(auth_ui_mod)

from frequency_agent.llm import load_json
from frequency_agent.icp import service_line_label
from frequency_agent.memory import Memory, format_fetch_label, resolve_search_name
from frequency_agent.auth_ui import current_user, render_account_chip, require_login
from frequency_agent.accounts import get_account_store
from frequency_agent.admin_ui import render_admin_page
from frequency_agent.settings_ui import render_settings_page
from frequency_agent.branding import brand_name
from frequency_agent.jobs import JobStore, job_thread_alive, start_agent_job
from frequency_agent.contact_cards import (
    direct_person_card_html,
    indirect_company_card_html,
    iter_direct_people,
    iter_indirect_leads,
    section_banner_html,
)
full_results_json_text = search_export_mod.full_results_json_text
search_contact_rows = search_export_mod.search_contact_rows
search_csv_text = search_export_mod.search_csv_text
browse_roots = folder_browse_mod.browse_roots
default_save_folder = folder_browse_mod.default_save_folder
list_subfolders = folder_browse_mod.list_subfolders
parent_within_roots = folder_browse_mod.parent_within_roots
tk_pick_folder = folder_browse_mod.tk_pick_folder
render_browser_directory_save = folder_browse_mod.render_browser_directory_save
from frequency_agent.send_queue import can_enqueue
from frequency_agent.outreach_queue import (
    apply_target_edits,
    company_queue_payload,
    list_message_targets,
    selected_messages,
)
from frequency_agent.pipeline_ui import (
    render_my_pipeline,
    render_results_similarity,
    render_team_board,
    render_working_queue,
)
from frequency_agent.repo_ui import render_central_repo
from frequency_agent.ui import (
    agent_stages_html,
    composer_header_html,
    detail_html,
    empty_state_html,
    fetch_bar,
    funnel_html,
    hero,
    inject,
    job_dock_header_html,
    normalize_theme,
    queue_label,
    results_summary_html,
    splash_html,
    theme_from_query_value,
    topbar_html,
)

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)

st.set_page_config(
    page_title=f"{brand_name()} · Lead Intelligence",
    page_icon="·",
    layout="wide",
    initial_sidebar_state="collapsed",
)

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
if "icp_text_saved" not in st.session_state:
    st.session_state.icp_text_saved = ""
if "inferred_service_line" not in st.session_state:
    st.session_state.inferred_service_line = ""
if "hydrated" not in st.session_state:
    st.session_state.hydrated = False
if "view_mode" not in st.session_state:
    st.session_state.view_mode = "query"
if "view_label" not in st.session_state:
    st.session_state.view_label = ""

if "last_search_mode" not in st.session_state:
    st.session_state.last_search_mode = ""
if "pending_icp_text" not in st.session_state:
    st.session_state.pending_icp_text = None
if "pending_search_name" not in st.session_state:
    st.session_state.pending_search_name = None
if "composer_open" not in st.session_state:
    st.session_state.composer_open = False
if "rename_search_id" not in st.session_state:
    st.session_state.rename_search_id = ""
if "page_view" not in st.session_state:
    st.session_state.page_view = "main"
# Theme: query param survives refresh; session_state survives logout within the run.
_qp_theme = theme_from_query_value(st.query_params.get("theme"))
if _qp_theme:
    st.session_state.ui_theme = _qp_theme
elif "ui_theme" not in st.session_state:
    st.session_state.ui_theme = "dark"
st.session_state.ui_theme = normalize_theme(st.session_state.ui_theme)
if theme_from_query_value(st.query_params.get("theme")) != st.session_state.ui_theme:
    st.query_params["theme"] = st.session_state.ui_theme
if "ws_sel_queries" not in st.session_state:
    st.session_state.ws_sel_queries = set()
if "ws_sel_runs" not in st.session_state:
    st.session_state.ws_sel_runs = set()
if "ws_sel_nonce" not in st.session_state:
    st.session_state.ws_sel_nonce = 0
if "splash_seen" not in st.session_state:
    st.session_state.splash_seen = False
if "active_job_id" not in st.session_state:
    st.session_state.active_job_id = ""
if "applied_job_id" not in st.session_state:
    st.session_state.applied_job_id = ""
if "job_notice" not in st.session_state:
    st.session_state.job_notice = ""
if "job_panel_expanded" not in st.session_state:
    st.session_state.job_panel_expanded = False
if "ws_section" not in st.session_state:
    st.session_state.ws_section = "searches"
if "similar_focus_id" not in st.session_state:
    st.session_state.similar_focus_id = 0
if "team_open_id" not in st.session_state:
    st.session_state.team_open_id = 0
if "repo_open_id" not in st.session_state:
    st.session_state.repo_open_id = 0
if "repo_page" not in st.session_state:
    st.session_state.repo_page = 1

st.markdown(inject(st.session_state.ui_theme), unsafe_allow_html=True)

# Fast Frequency intro once per browser session
if not st.session_state.splash_seen:
    st.markdown(splash_html(), unsafe_allow_html=True)
    st.session_state.splash_seen = True

# Auth gate — register (email OTP) → login (email + password, no login 2FA)
if not require_login():
    st.stop()

_auth = current_user() or {}
_owner_email = (_auth.get("email") or "").strip().lower()
if not _owner_email:
    st.error("Signed-in email is missing. Log out and sign in again.")
    st.stop()

# Switch workspace when a different account signs in
if st.session_state.get("auth_owner_email") != _owner_email:
    st.session_state.auth_owner_email = _owner_email
    st.session_state.hydrated = False
    st.session_state.leads = []
    st.session_state.funnel = {}
    st.session_state.logs = []
    st.session_state.queries = []
    st.session_state.selected = 0
    st.session_state.active_run_id = ""
    st.session_state.active_query_id = ""
    st.session_state.active_icp_hash = ""
    st.session_state.csv_path = ""
    st.session_state.icp_text_saved = ""
    st.session_state.view_label = ""
    st.session_state.composer_open = False

presets = load_json("icp_presets.json")
memory = Memory(owner_email=_owner_email)
accounts = get_account_store(path=memory.path)
accounts.ensure_profile(_owner_email, setup_complete=True)
_resolved_keys = accounts.resolve_api_keys(_owner_email)
openai_key = (_resolved_keys.get("openai_key") or "").strip()
tavily_key = (_resolved_keys.get("tavily_key") or "").strip()
_is_admin = accounts.is_admin(_owner_email)


def _toggle_theme() -> None:
    next_theme = "dark" if st.session_state.ui_theme == "light" else "light"
    st.session_state.ui_theme = next_theme
    st.query_params["theme"] = next_theme


def _theme_button_label() -> str:
    return "Dark" if st.session_state.ui_theme == "light" else "Light"


def apply_run(run: dict) -> None:
    st.session_state.composer_open = False
    st.session_state.leads = run.get("leads") or []
    st.session_state.funnel = run.get("funnel") or {}
    st.session_state.logs = run.get("logs") or []
    st.session_state.queries = run.get("queries") or []
    st.session_state.active_run_id = run.get("run_id") or ""
    st.session_state.active_query_id = run.get("query_id") or st.session_state.active_query_id
    st.session_state.active_icp_hash = run.get("icp_hash") or ""
    st.session_state.csv_path = run.get("csv_path") or ""
    st.session_state.inferred_service_line = run.get("service_line") or ""
    icp_text = run.get("icp") or ""
    st.session_state.icp_text_saved = icp_text
    st.session_state.pending_icp_text = icp_text
    st.session_state.selected = 0
    st.session_state.view_mode = "run"
    st.session_state.view_label = run.get("label") or format_fetch_label(
        "", run.get("run_id") or "", run.get("finished") or run.get("started") or ""
    )
    st.session_state.last_search_mode = "Loaded fetch"
    qid = run.get("query_id") or ""
    if qid:
        sess = memory.get_query_session(qid)
        if sess and (sess.get("label") or "").strip():
            st.session_state.pending_search_name = sess["label"]


def apply_query(query_id: str) -> None:
    """Load the most recent fetch for a query (fetch-more context)."""
    st.session_state.composer_open = False
    session = memory.get_query_session(query_id)
    if not session:
        return
    st.session_state.active_query_id = query_id
    st.session_state.inferred_service_line = session.get("service_line") or ""
    st.session_state.icp_text_saved = session.get("icp_text") or ""
    st.session_state.pending_icp_text = st.session_state.icp_text_saved
    if (session.get("label") or "").strip():
        st.session_state.pending_search_name = session["label"]
    runs = memory.list_runs_for_query(query_id)
    if runs:
        loaded = memory.load_run(runs[0]["run_id"])
        if loaded:
            apply_run(loaded)
            return
    st.session_state.leads = []
    st.session_state.selected = 0
    st.session_state.view_mode = "query"
    st.session_state.view_label = session.get("label") or query_id


# Restore latest fetch on first load (each fetch is its own result set)
if not st.session_state.hydrated:
    latest = memory.latest_run()
    if latest:
        apply_run(latest)
    st.session_state.hydrated = True


def _leads_for_export() -> list[dict]:
    """Leads currently on screen — this fetch only."""
    if st.session_state.leads:
        return list(st.session_state.leads)
    if st.session_state.active_run_id:
        return memory.leads_for_run(st.session_state.active_run_id)
    return []


def _export_file_stem() -> str:
    rid = st.session_state.active_run_id or "session"
    return f"frequency_fetch_{rid}"


def _render_full_export_buttons(*, prefix: str = "", use_container_width: bool = True) -> None:
    export_leads = _leads_for_export()
    if not export_leads:
        return
    rid = st.session_state.active_run_id or ""
    n_people = len(search_contact_rows(export_leads, run_id=rid))
    stem = _export_file_stem()
    csv_bytes = search_csv_text(export_leads, run_id=rid).encode("utf-8")
    json_bytes = full_results_json_text(export_leads, run_id=rid).encode("utf-8")
    c1, c2 = st.columns(2)
    c1.download_button(
        "Download CSV",
        csv_bytes,
        file_name=f"{stem}_full_results.csv",
        mime="text/csv",
        use_container_width=use_container_width,
        key=f"{prefix}dl-csv",
        help="Every company + every contact (verified + all) with channels and company/person outreach drafts.",
    )
    c2.download_button(
        "Download JSON",
        json_bytes,
        file_name=f"{stem}_full_results.json",
        mime="application/json",
        use_container_width=use_container_width,
        key=f"{prefix}dl-json",
        help="Complete lead payloads including contacts, verified contacts, channels, and outreach drafts.",
    )
    st.caption(
        f"{len(export_leads)} companies · {n_people} contact rows · "
        f"this fetch only (`{rid or '—'}`)."
    )
    if st.session_state.csv_path:
        st.caption(f"Auto-saved file: `{Path(st.session_state.csv_path).name}`")


def _run_label(r: dict) -> str:
    stored = (r.get("label") or "").strip()
    if stored:
        return stored
    return format_fetch_label(
        (r.get("icp") or r.get("icp_text") or "")[:40],
        r.get("run_id") or "",
        r.get("finished") or r.get("started") or "",
    )


def _search_display_name(session: dict) -> str:
    return resolve_search_name(session)


def _fmt_when(iso: str) -> str:
    s = (iso or "").replace("T", " ").strip()
    return s[:16] if s else "—"


def _clear_workspace() -> None:
    memory.clear_all_data()
    for key in (
        "leads", "funnel", "logs", "queries", "active_run_id", "active_query_id",
        "csv_path", "icp_text_saved", "inferred_service_line", "selected", "view_label",
        "last_search_mode", "pending_icp_text", "pending_search_name", "rename_search_id",
    ):
        if key in st.session_state:
            st.session_state[key] = [] if key in {"leads", "logs", "queries"} else ""
    st.session_state.composer_open = False
    st.session_state.hydrated = True


def _clear_ws_selection() -> None:
    """Reset workspace checkboxes (nonce remounts widgets so they uncheck)."""
    st.session_state.ws_sel_queries = set()
    st.session_state.ws_sel_runs = set()
    st.session_state.ws_sel_nonce = int(st.session_state.get("ws_sel_nonce") or 0) + 1
    # Drop stale checkbox widget state so Streamlit does not restore ticks
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and (
            key.startswith("ws-sel-q-") or key.startswith("ws-sel-r-")
        ):
            del st.session_state[key]


def _enter_workspace() -> None:
    _clear_ws_selection()
    st.session_state.page_view = "workspace"
    st.session_state.composer_open = False
    st.session_state.rename_search_id = ""


def _leave_workspace() -> None:
    _clear_ws_selection()
    st.session_state.page_view = "main"
    st.session_state.rename_search_id = ""
    st.session_state.similar_focus_id = 0
    st.session_state.team_open_id = 0


def _browse_local_folder(initial: str = "") -> str | None:
    """Prefer native OS dialog; otherwise None (UI falls back to in-app browser)."""
    return tk_pick_folder(initial)


def _render_folder_browser() -> None:
    """In-app navigator over host Documents/Downloads/Desktop + project exports."""
    roots = browse_roots(ROOT)
    if not roots:
        st.caption("No browsable folders mounted. Use Download, or paste a writable path.")
        return

    root_options = [str(r) for r in roots]
    root_labels = {str(r): r.name or str(r) for r in roots}

    if "ws_browse_path" not in st.session_state or not str(st.session_state.ws_browse_path).strip():
        st.session_state.ws_browse_path = root_options[0]

    st.markdown("**Browse folders on this PC**")
    pick_root = st.selectbox(
        "Start from",
        root_options,
        format_func=lambda p: root_labels.get(p, p),
        key="ws_browse_root",
    )
    prev_root = st.session_state.get("_ws_prev_root_sel")
    if prev_root is not None and pick_root != prev_root:
        st.session_state.ws_browse_path = pick_root
    st.session_state._ws_prev_root_sel = pick_root

    try:
        current = Path(str(st.session_state.ws_browse_path)).expanduser().resolve()
    except OSError:
        current = Path(pick_root)
        st.session_state.ws_browse_path = str(current)

    # Keep navigation inside allowed roots
    in_root = False
    for root in roots:
        try:
            current.relative_to(root)
            in_root = True
            break
        except ValueError:
            if current == root:
                in_root = True
                break
    if not in_root or not current.is_dir():
        current = Path(pick_root)
        st.session_state.ws_browse_path = str(current)

    st.code(str(current), language=None)
    nav1, nav2, nav3 = st.columns([1, 1, 2])
    with nav1:
        parent = parent_within_roots(current, roots)
        if st.button("↑ Up", use_container_width=True, key="ws-browse-up", disabled=parent is None):
            if parent is not None:
                st.session_state.ws_browse_path = str(parent)
                st.rerun()
    with nav2:
        if st.button("Use this folder", type="primary", use_container_width=True, key="ws-browse-use"):
            st.session_state.ws_save_folder = str(current)
            st.session_state.ws_browse_open = False
            st.toast(f"Save folder set to {current}")
            st.rerun()
    with nav3:
        if st.button("Close browser", use_container_width=True, key="ws-browse-close"):
            st.session_state.ws_browse_open = False
            st.rerun()

    children = list_subfolders(current)
    if not children:
        st.caption("No subfolders here — click Use this folder, or go Up.")
        return
    st.caption("Open a subfolder:")
    for i, child in enumerate(children[:80]):
        if st.button(f"📁 {child.name}", key=f"ws-browse-child-{i}", use_container_width=True):
            st.session_state.ws_browse_path = str(child)
            st.rerun()
    if len(children) > 80:
        st.caption(f"Showing 80 of {len(children)} folders.")


def _build_fetches_zip(run_ids: list[str]) -> bytes:
    """Collect full CSV + JSON (contacts + outreach) for each fetch into one zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rid in run_ids:
            loaded = memory.load_run(rid) or {}
            leads = loaded.get("leads") or memory.leads_for_run(rid)
            stem = f"frequency_fetch_{rid}"
            meta = {
                "icp": loaded.get("icp") or loaded.get("icp_text") or "",
                "service_line": loaded.get("service_line") or "",
                "query_id": loaded.get("query_id") or "",
                "label": loaded.get("label") or "",
            }
            zf.writestr(
                f"{stem}_full_results.csv",
                search_csv_text(leads, run_id=rid),
            )
            zf.writestr(
                f"{stem}_full_results.json",
                full_results_json_text(leads, run_id=rid, meta=meta),
            )
    return buf.getvalue()


def _save_fetches_zip_to_folder(run_ids: list[str], folder: str) -> Path:
    """Write one ZIP (full CSV+JSON per fetch) into the folder the user chose."""
    dest = Path(folder).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "frequency_selected_fetches.zip"
    zip_path.write_bytes(_build_fetches_zip(run_ids))
    return zip_path


def _selected_run_ids_from_workspace() -> list[str]:
    """Union of checked fetches and all fetches under checked searches."""
    run_ids: list[str] = []
    seen: set[str] = set()
    for qid in list(st.session_state.get("ws_sel_queries") or []):
        for run in memory.list_runs_for_query(qid):
            rid = run["run_id"]
            if rid not in seen:
                seen.add(rid)
                run_ids.append(rid)
    for rid in list(st.session_state.get("ws_sel_runs") or []):
        if rid not in seen:
            seen.add(rid)
            run_ids.append(rid)
    return run_ids


def _soft_delete_workspace_selection() -> None:
    covered: set[str] = set()
    for qid in list(st.session_state.ws_sel_queries):
        for r in memory.list_runs_for_query(qid):
            covered.add(r["run_id"])
    if st.session_state.ws_sel_queries:
        memory.soft_delete_query_sessions(list(st.session_state.ws_sel_queries))
    lone = [rid for rid in st.session_state.ws_sel_runs if rid not in covered]
    if lone:
        memory.soft_delete_runs(lone)
    if st.session_state.active_query_id in st.session_state.ws_sel_queries:
        st.session_state.active_query_id = ""
        st.session_state.active_run_id = ""
        st.session_state.leads = []
    elif st.session_state.active_run_id in st.session_state.ws_sel_runs:
        st.session_state.active_run_id = ""
        st.session_state.leads = []


def _render_workspace_page() -> None:
    """Full-page workspace: searches, pipeline, team board, recycle bin."""
    stats = memory.memory_stats()
    pipe_stats = memory.pipeline_stats(team=True)
    st.markdown(
        f"""
<div class="fx-panel-hero">
  <p class="fx-kicker">Workspace</p>
  <h2>{_owner_email}</h2>
  <p>Your searches stay private. Pipeline status and the team board are shared so everyone can see who is handling which company.</p>
</div>
""",
        unsafe_allow_html=True,
    )
    st.caption(
        f"{stats['seen']} leads · {stats.get('queries', 0)} searches · "
        f"{stats.get('runs', 0)} fetches · {pipe_stats.get('total') or 0} in team pipeline"
    )
    if st.session_state.pop("ws_jump_team", False):
        st.session_state.ws_section = "team"
    section = st.radio(
        "Workspace section",
        ["searches", "pipeline", "team"],
        format_func=lambda s: {
            "searches": "Searches",
            "pipeline": "My pipeline",
            "team": "Team board",
        }[s],
        horizontal=True,
        key="ws_section",
        label_visibility="collapsed",
    )
    if section == "pipeline":
        render_my_pipeline(memory=memory, owner_email=_owner_email, is_admin=_is_admin)
        return
    if section == "team":
        profiles = {
            (p.get("email") or "").strip().lower(): p for p in accounts.list_profiles()
        }
        render_team_board(
            memory=memory,
            owner_email=_owner_email,
            is_admin=_is_admin,
            profiles=profiles,
        )
        return
    _render_workspace_searches()


def _render_workspace_searches() -> None:
    """Searches, fetches, save-to-folder, recycle bin."""
    nonce = int(st.session_state.get("ws_sel_nonce") or 0)
    sessions = memory.list_query_sessions(limit=60)
    st.markdown("##### Searches")
    if not sessions:
        st.caption("No searches yet.")
    else:
        for session in sessions:
            qid = session["query_id"]
            name = _search_display_name(session)
            when = _fmt_when(session.get("last_run_at") or session.get("created_at") or "")
            runs = memory.list_runs_for_query(qid)
            with st.expander(f"{name}  ·  {when}  ·  {len(runs)} fetches", expanded=False):
                sel_q = st.checkbox(
                    "Select entire search",
                    value=qid in st.session_state.ws_sel_queries,
                    key=f"ws-sel-q-{nonce}-{qid}",
                )
                if sel_q:
                    st.session_state.ws_sel_queries.add(qid)
                else:
                    st.session_state.ws_sel_queries.discard(qid)

                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("Open", key=f"ws-open-{qid}", use_container_width=True):
                        apply_query(qid)
                        _leave_workspace()
                        st.rerun()
                with b2:
                    if st.session_state.rename_search_id == qid:
                        if st.button("Cancel", key=f"ws-ren-c-{qid}", use_container_width=True):
                            st.session_state.rename_search_id = ""
                            st.rerun()
                    else:
                        if st.button("Rename", key=f"ws-ren-{qid}", use_container_width=True):
                            st.session_state.rename_search_id = qid
                            st.rerun()
                with b3:
                    if st.button("Recycle", key=f"ws-del-{qid}", use_container_width=True):
                        memory.soft_delete_query_sessions([qid])
                        st.session_state.ws_sel_queries.discard(qid)
                        if st.session_state.active_query_id == qid:
                            st.session_state.active_query_id = ""
                            st.session_state.active_run_id = ""
                            st.session_state.leads = []
                        _clear_ws_selection()
                        st.toast("Moved to recycle bin")
                        st.rerun()

                if st.session_state.rename_search_id == qid:
                    new_name = st.text_input("New name", value=name, key=f"ws-ren-in-{qid}")
                    if st.button("Save name", key=f"ws-ren-save-{qid}", type="primary"):
                        memory.rename_query_session(qid, new_name)
                        st.session_state.rename_search_id = ""
                        st.toast("Renamed")
                        st.rerun()

                brief = (session.get("icp_text") or "").strip()
                if brief:
                    st.caption(brief if len(brief) <= 160 else brief[:160] + "…")

                for run in runs:
                    rid = run["run_id"]
                    label = _run_label(run)
                    c1, c2, c3 = st.columns([0.12, 0.58, 0.30])
                    with c1:
                        sel_r = st.checkbox(
                            "sel",
                            value=rid in st.session_state.ws_sel_runs,
                            key=f"ws-sel-r-{nonce}-{rid}",
                            label_visibility="collapsed",
                        )
                        if sel_r:
                            st.session_state.ws_sel_runs.add(rid)
                        else:
                            st.session_state.ws_sel_runs.discard(rid)
                    with c2:
                        st.caption(f"{label} · {run.get('lead_count', 0)} cos")
                    with c3:
                        if st.button("Open fetch", key=f"ws-of-{rid}", use_container_width=True):
                            loaded = memory.load_run(rid)
                            if loaded:
                                apply_run(loaded)
                                _leave_workspace()
                                st.rerun()

    sel_runs = _selected_run_ids_from_workspace()
    st.markdown("##### Selection")
    st.caption(f"{len(st.session_state.ws_sel_queries)} searches · {len(sel_runs)} fetches selected")
    s1, s2 = st.columns(2)
    with s1:
        if st.button("Select all searches", use_container_width=True, key="ws-sel-all"):
            st.session_state.ws_sel_queries = {s["query_id"] for s in sessions}
            st.rerun()
    with s2:
        if st.button("Clear selection", use_container_width=True, key="ws-sel-clear"):
            _clear_ws_selection()
            st.rerun()

    has_sel = bool(st.session_state.ws_sel_queries or st.session_state.ws_sel_runs)
    if has_sel and sel_runs:
        st.markdown("##### Save / download selected")
        st.caption(
            "ZIP includes full CSV + JSON per fetch: every contact, channels, "
            "and company + person outreach drafts."
        )
        if "ws_save_folder" not in st.session_state or not str(st.session_state.ws_save_folder).strip():
            st.session_state.ws_save_folder = default_save_folder(ROOT)
        if "ws_browse_open" not in st.session_state:
            st.session_state.ws_browse_open = False

        zip_bytes = _build_fetches_zip(sel_runs)

        # 1) Browser-native: pick any folder on this PC and write the ZIP there (Chrome/Edge)
        render_browser_directory_save(
            zip_bytes,
            file_name="frequency_selected_fetches.zip",
        )

        # 2) In-app folder browser (works in Docker via /host mounts)
        b1, b2 = st.columns([1, 1])
        with b1:
            if st.button(
                "Browse folders…",
                use_container_width=True,
                key="ws-browse-folder",
            ):
                picked = _browse_local_folder(st.session_state.ws_save_folder)
                if picked:
                    st.session_state.ws_save_folder = picked
                    st.session_state.ws_browse_open = False
                    st.toast(f"Save folder set to {picked}")
                    st.rerun()
                st.session_state.ws_browse_open = True
                st.rerun()
        with b2:
            if st.button(
                f"Save ZIP here ({len(sel_runs)} fetches)",
                type="primary",
                use_container_width=True,
                key="ws-save-folder",
            ):
                try:
                    zip_path = _save_fetches_zip_to_folder(
                        sel_runs, st.session_state.ws_save_folder
                    )
                    _clear_ws_selection()
                    st.toast(f"Saved {zip_path.name} → {zip_path.parent}")
                    st.rerun()
                except OSError as exc:
                    st.error(f"Could not save: {exc}")

        if st.session_state.ws_browse_open:
            _render_folder_browser()

        folder = st.text_input(
            "Save ZIP to this folder",
            key="ws_save_folder",
            help="Set via Browse folders, or paste a path. Docker: use Documents / Downloads / Desktop.",
        )
        st.caption(f"Current save folder: `{folder}`")

        # 3) Simple browser download (Downloads folder / save-as)
        st.download_button(
            f"Download ({len(sel_runs)} fetches)",
            zip_bytes,
            file_name="frequency_selected_fetches.zip",
            mime="application/zip",
            use_container_width=True,
            key="ws-zip",
            help="Simple browser download of the same full ZIP.",
        )

        if st.button(
            "Move selected to recycle bin",
            use_container_width=True,
            key="ws-del-sel",
            type="secondary",
        ):
            _soft_delete_workspace_selection()
            _clear_ws_selection()
            st.toast("Moved to recycle bin")
            st.rerun()
    elif has_sel:
        st.caption("Selected searches have no fetches to export yet.")
        if st.button(
            "Move selected to recycle bin",
            use_container_width=True,
            key="ws-del-sel-empty",
            type="secondary",
        ):
            _soft_delete_workspace_selection()
            _clear_ws_selection()
            st.toast("Moved to recycle bin")
            st.rerun()

    st.markdown("##### Recycle bin")
    deleted_qs = memory.list_deleted_query_sessions(limit=40)
    deleted_runs = memory.list_deleted_runs(limit=60)
    orphan_runs = [
        r for r in deleted_runs
        if not any(s["query_id"] == r.get("query_id") for s in deleted_qs)
    ]
    if not deleted_qs and not orphan_runs:
        st.caption("Recycle bin is empty.")
    else:
        for session in deleted_qs:
            qid = session["query_id"]
            name = _search_display_name(session)
            when = _fmt_when(session.get("deleted_at") or "")
            c1, c2, c3 = st.columns([0.5, 0.25, 0.25])
            with c1:
                st.caption(f"🗑 {name} · deleted {when}")
            with c2:
                if st.button("Restore", key=f"ws-res-q-{qid}", use_container_width=True):
                    memory.restore_query_sessions([qid])
                    st.toast("Restored")
                    st.rerun()
            with c3:
                if st.button("Delete forever", key=f"ws-perm-q-{qid}", use_container_width=True):
                    memory.permanently_delete_query_sessions([qid])
                    st.toast("Permanently deleted")
                    st.rerun()
        for run in orphan_runs:
            rid = run["run_id"]
            label = _run_label(run)
            c1, c2, c3 = st.columns([0.5, 0.25, 0.25])
            with c1:
                st.caption(f"🗑 Fetch {label}")
            with c2:
                if st.button("Restore", key=f"ws-res-r-{rid}", use_container_width=True):
                    memory.restore_runs([rid])
                    st.toast("Restored")
                    st.rerun()
            with c3:
                if st.button("Delete forever", key=f"ws-perm-r-{rid}", use_container_width=True):
                    memory.permanently_delete_runs([rid])
                    st.toast("Permanently deleted")
                    st.rerun()

    st.divider()
    if st.button("Clear all results forever", type="secondary", use_container_width=True, key="ws-clear-all"):
        _clear_workspace()
        _clear_ws_selection()
        st.toast("Everything cleared.")
        st.rerun()


_AGENT_STAGES = [
    "Understanding ICP",
    "Expanding queries",
    "Searching the web",
    "Extracting companies",
    "Clustering & deduping",
    "Verifying · scoring · drafting",
]
_AGENT_STAGE_MAP = {
    "queued": _AGENT_STAGES[0],
    "parse_icp": _AGENT_STAGES[0],
    "expand_queries": _AGENT_STAGES[1],
    "search_web": _AGENT_STAGES[2],
    "extract_companies": _AGENT_STAGES[3],
    "cluster": _AGENT_STAGES[4],
    "enrich": _AGENT_STAGES[5],
    "done": _AGENT_STAGES[5],
    "failed": _AGENT_STAGES[5],
}


def _jobs() -> JobStore:
    return JobStore(path=memory.path)


def _apply_finished_job(job: dict) -> None:
    """Load completed job results into the UI session."""
    jid = job.get("job_id") or ""
    if jid and st.session_state.get("applied_job_id") == jid:
        return
    if (job.get("status") or "") == "failed" or (job.get("status") or "") == "interrupted":
        st.session_state.job_notice = (job.get("error") or "Fetch failed.").strip()
        st.session_state.logs = list(job.get("logs") or [])
        if jid:
            st.session_state.applied_job_id = jid
        st.session_state.active_job_id = ""
        return

    rid = (job.get("run_id") or (job.get("result") or {}).get("run_id") or "").strip()
    qid = (job.get("query_id") or "").strip()
    if rid:
        loaded = memory.load_run(rid)
        if loaded:
            apply_run(loaded)
            st.session_state.last_search_mode = job.get("search_mode") or "Background fetch"
            st.session_state.composer_open = False
            n = len(loaded.get("leads") or [])
            st.session_state.job_notice = (
                f"Fetch finished — {n} companies saved to Workspace for {_owner_email}."
            )
            st.toast(st.session_state.job_notice)
        else:
            st.session_state.job_notice = (
                f"Fetch finished but run `{rid}` is not visible for {_owner_email}."
            )
    elif qid:
        apply_query(qid)
        st.session_state.job_notice = "Fetch finished (no new run id) — opened the search."
    st.session_state.logs = list(job.get("logs") or [])
    st.session_state.funnel = dict(job.get("funnel") or {})
    if jid:
        st.session_state.applied_job_id = jid
    st.session_state.active_job_id = ""


def _execute_agent(*, icp_text: str, query_id: str, is_fetch_more: bool, search_mode: str) -> None:
    """Enqueue a background fetch that survives navigation / refresh / other UI work."""
    if not openai_key:
        st.error("Cannot run without OPENAI_API_KEY on the server (`.env`).")
        return
    if not (icp_text or "").strip():
        st.error("Add an ICP brief before starting.")
        return
    if not (query_id or "").strip():
        st.error("Missing search id — create or open a search first.")
        return

    existing = _jobs().active_for_owner(_owner_email)
    if existing and job_thread_alive(existing["job_id"]):
        st.session_state.active_job_id = existing["job_id"]
        st.warning("A fetch is already running for your account. Progress continues in the background.")
        st.rerun()
        return

    job_id = start_agent_job(
        owner_email=_owner_email,
        query_id=query_id,
        icp_text=icp_text.strip(),
        openai_key=openai_key,
        tavily_key=tavily_key,
        search_mode=search_mode,
        is_fetch_more=is_fetch_more,
        db_path=memory.path,
    )
    st.session_state.active_job_id = job_id
    st.session_state.active_query_id = query_id
    st.session_state.composer_open = False
    st.session_state.job_notice = (
        "Fetch started in the background — progress panel above. "
        "You can minimize it and keep working while it runs."
    )
    st.session_state.job_panel_expanded = True
    st.toast("Fetch running in background")
    st.rerun()


@st.fragment(run_every=2)
def _render_background_job_panel() -> None:
    """Minimizable dock: shown while a fetch is queued/running."""
    store = _jobs()
    jid = (st.session_state.get("active_job_id") or "").strip()
    job = store.get(jid) if jid else None
    if not job or job.get("status") not in {"queued", "running"}:
        active = store.active_for_owner(_owner_email)
        if active:
            job = active
            st.session_state.active_job_id = active["job_id"]
        elif job and job.get("status") in {"done", "failed", "interrupted"}:
            _apply_finished_job(job)
            st.session_state.job_panel_expanded = False
            st.rerun()
            return
        else:
            notice = (st.session_state.get("job_notice") or "").strip()
            if notice:
                if "failed" in notice.lower() or "not visible" in notice.lower():
                    st.error(notice)
                else:
                    st.success(notice)
                st.session_state.job_notice = ""
            return

    status = (job.get("status") or "").strip()
    if status in {"done", "failed", "interrupted"}:
        _apply_finished_job(job)
        st.session_state.job_panel_expanded = False
        st.rerun()
        return

    stage_key = (job.get("stage") or "queued").strip()
    active_label = _AGENT_STAGE_MAP.get(stage_key, _AGENT_STAGES[0])
    q_hint = (job.get("query_id") or "")[:12]
    if "job_panel_expanded" not in st.session_state:
        st.session_state.job_panel_expanded = True
    expanded = bool(st.session_state.get("job_panel_expanded"))

    with st.container(border=True):
        st.markdown(
            job_dock_header_html(
                stage_label=active_label,
                query_hint=q_hint,
                expanded=expanded,
            ),
            unsafe_allow_html=True,
        )
        b1, b2, b3 = st.columns([0.34, 0.33, 0.33], gap="small")
        with b1:
            toggle_label = "Minimize" if expanded else "Show progress"
            if st.button(toggle_label, use_container_width=True, key="job-dock-toggle"):
                st.session_state.job_panel_expanded = not expanded
                st.rerun()
        with b2:
            st.caption("Safe to leave · keeps running")
        with b3:
            if not job_thread_alive(job["job_id"]):
                st.caption("Reconnecting…")
            else:
                st.caption(active_label)

        if expanded:
            st.markdown(agent_stages_html(active_label, _AGENT_STAGES), unsafe_allow_html=True)
            logs = list(job.get("logs") or [])
            if logs:
                with st.expander("Live log", expanded=True):
                    for line in logs[-14:]:
                        st.caption(line)
            else:
                st.caption("Waiting for the first pipeline update…")


# ── Top chrome / page router ──
render_account_chip()
_render_background_job_panel()

if st.session_state.page_view == "admin":
    if not _is_admin:
        st.session_state.page_view = "main"
        st.rerun()
    top_l, top_mid, top_r = st.columns([0.55, 0.22, 0.23], gap="small")
    with top_l:
        st.markdown(topbar_html(), unsafe_allow_html=True)
        st.markdown('<p class="fx-page-kicker">Admin</p>', unsafe_allow_html=True)
    with top_mid:
        if st.button(_theme_button_label(), use_container_width=True, key="btn-theme-admin"):
            _toggle_theme()
            st.rerun()
    with top_r:
        if st.button("← Back", use_container_width=True, key="btn-leave-admin"):
            st.session_state.page_view = "main"
            st.rerun()
    render_admin_page(memory=memory, accounts=accounts, viewer_email=_owner_email)
    st.stop()

if st.session_state.page_view == "settings":
    top_l, top_mid, top_r = st.columns([0.55, 0.22, 0.23], gap="small")
    with top_l:
        st.markdown(topbar_html(), unsafe_allow_html=True)
        st.markdown('<p class="fx-page-kicker">Profile</p>', unsafe_allow_html=True)
    with top_mid:
        if st.button(_theme_button_label(), use_container_width=True, key="btn-theme-settings"):
            _toggle_theme()
            st.rerun()
    with top_r:
        if st.button("← Back", use_container_width=True, key="btn-leave-settings"):
            st.session_state.page_view = "main"
            st.rerun()
    render_settings_page(_owner_email, accounts=accounts)
    st.stop()

if st.session_state.page_view == "repo":
    top_l, top_mid, top_r = st.columns([0.55, 0.22, 0.23], gap="small")
    with top_l:
        st.markdown(topbar_html(), unsafe_allow_html=True)
        st.markdown('<p class="fx-page-kicker">Team repo</p>', unsafe_allow_html=True)
    with top_mid:
        if st.button(_theme_button_label(), use_container_width=True, key="btn-theme-repo"):
            _toggle_theme()
            st.rerun()
    with top_r:
        if st.button("← Back to search", use_container_width=True, key="btn-leave-repo"):
            st.session_state.page_view = "main"
            st.rerun()
    _profiles = {
        (p.get("email") or "").strip().lower(): p for p in accounts.list_profiles()
    }
    render_central_repo(memory=memory, owner_email=_owner_email, profiles=_profiles)
    st.stop()

if st.session_state.page_view == "workspace":
    top_l, top_mid, top_r = st.columns([0.55, 0.22, 0.23], gap="small")
    with top_l:
        st.markdown(topbar_html(), unsafe_allow_html=True)
        st.markdown('<p class="fx-page-kicker">Workspace</p>', unsafe_allow_html=True)
    with top_mid:
        if st.button(_theme_button_label(), use_container_width=True, key="btn-theme-ws"):
            _toggle_theme()
            st.rerun()
    with top_r:
        if st.button("← Back to search", use_container_width=True, key="btn-leave-workspace"):
            _leave_workspace()
            st.rerun()
    _render_workspace_page()
    st.stop()

nav_cols = st.columns(
    [0.28, 0.12, 0.10, 0.12, 0.12, 0.12, 0.14] if _is_admin else [0.34, 0.14, 0.12, 0.14, 0.13, 0.13],
    gap="small",
)
with nav_cols[0]:
    st.markdown(topbar_html(), unsafe_allow_html=True)
with nav_cols[1]:
    if st.button("Create search", type="primary", use_container_width=True, key="btn-create-search"):
        st.session_state.composer_open = True
        st.session_state.rename_search_id = ""
        st.rerun()
with nav_cols[2]:
    if st.button(_theme_button_label(), use_container_width=True, key="btn-theme-main"):
        _toggle_theme()
        st.rerun()
with nav_cols[3]:
    if st.button("Workspace", use_container_width=True, key="btn-open-workspace"):
        _enter_workspace()
        st.rerun()
with nav_cols[4]:
    if st.button("Repo", use_container_width=True, key="btn-open-repo"):
        st.session_state.page_view = "repo"
        st.rerun()
with nav_cols[5]:
    if st.button("Profile", use_container_width=True, key="btn-open-settings"):
        st.session_state.page_view = "settings"
        st.rerun()
if _is_admin:
    with nav_cols[6]:
        if st.button("Admin", use_container_width=True, key="btn-open-admin"):
            st.session_state.page_view = "admin"
            st.rerun()

if not openai_key:
    st.error("Server OPENAI_API_KEY is missing — ask an admin to set it in `.env`.")

if not tavily_key:
    st.warning(
        "No Tavily API key on your account — add yours in **Profile → Tavily API key**. "
        "Without it, search falls back to DuckDuckGo (no shared server Tavily key)."
    )
active_qs = (
    memory.get_query_session(st.session_state.active_query_id)
    if st.session_state.active_query_id
    else None
)
# Skip deleted active search
if active_qs and (active_qs.get("deleted_at") or "").strip():
    active_qs = None
    st.session_state.active_query_id = ""
    st.session_state.active_run_id = ""
    st.session_state.leads = []

locked_brief = ((active_qs or {}).get("icp_text") or st.session_state.icp_text_saved or "").strip()
active_search_name = _search_display_name(active_qs) if active_qs else ""

# ── Create new search composer ──
if st.session_state.composer_open:
    st.markdown(composer_header_html(), unsafe_allow_html=True)

    compose_name = st.text_input(
        "Name this search",
        placeholder="Optional — leave empty to use the ICP as the name",
        key="compose_search_name",
    )
    preset_key = st.selectbox(
        "Example brief (optional)",
        ["(blank)"] + list(presets.keys()),
        format_func=lambda k: "Start from scratch" if k == "(blank)" else presets[k]["label"],
        key="compose_preset",
    )
    compose_default = "" if preset_key == "(blank)" else presets[preset_key]["text"]
    if f"icp-compose-{preset_key}" not in st.session_state:
        st.session_state[f"icp-compose-{preset_key}"] = compose_default
    compose_icp = st.text_area(
        "Who should we find? (ICP)",
        height=140,
        key=f"icp-compose-{preset_key}",
        help="Describe sectors, stage, geo, and buying signals.",
    )
    c1, c2 = st.columns([0.28, 0.72])
    with c1:
        if st.button("Cancel", use_container_width=True, type="secondary", key="compose-cancel"):
            st.session_state.composer_open = False
            st.rerun()
    with c2:
        go = st.button("Run intelligence →", use_container_width=True, type="primary", key="compose-go")

    if go:
        if not openai_key:
            st.error("Cannot run without OPENAI_API_KEY on the server (`.env`).")
        elif not (compose_icp or "").strip():
            st.error("Add an ICP brief before starting.")
        else:
            qid = memory.create_query_session(
                compose_icp.strip(),
                label=(compose_name or "").strip(),
            )
            st.session_state.active_query_id = qid
            st.session_state.pending_search_name = resolve_search_name(
                memory.get_query_session(qid) or {}
            )
            _execute_agent(
                icp_text=compose_icp.strip(),
                query_id=qid,
                is_fetch_more=False,
                search_mode="New search",
            )

# ── Current search workspace ──
elif active_qs or st.session_state.leads:
    st.markdown(
        f'<div class="fx-bar"><span><strong>{html.escape(active_search_name or "Current search")}</strong>'
        f'{" · " + html.escape(service_line_label(st.session_state.inferred_service_line)) if st.session_state.inferred_service_line else ""}'
        f' · {len(st.session_state.leads)} companies'
        f'{" · <code>" + html.escape(st.session_state.active_run_id) + "</code>" if st.session_state.active_run_id else ""}'
        f"</span></div>",
        unsafe_allow_html=True,
    )
    with st.expander("ICP for this search", expanded=False):
        st.write(locked_brief or "—")

    can_fetch = bool(st.session_state.active_query_id and locked_brief)
    fetch_more = st.button(
        "Fetch more →",
        type="primary",
        use_container_width=True,
        disabled=not can_fetch,
        help="Find more companies for this same search (skips ones already found).",
        key="btn-fetch-more",
    )
    if fetch_more:
        if not openai_key:
            st.error("Cannot run without OPENAI_API_KEY on the server (`.env`).")
        elif not can_fetch:
            st.error("Open or create a search first.")
        else:
            _execute_agent(
                icp_text=locked_brief,
                query_id=st.session_state.active_query_id,
                is_fetch_more=True,
                search_mode="Fetch more",
            )
else:
    st.markdown(hero(), unsafe_allow_html=True)
    st.markdown(
        empty_state_html(
            "Start with an ICP",
            "Create a new search to name it, describe who you want, and run intelligence.",
        ),
        unsafe_allow_html=True,
    )

_owner_slug = "".join(ch if ch.isalnum() else "_" for ch in _owner_email).strip("_") or "anon"
DRY_RUN_LOG = ROOT / "output" / f"dry_run_send_log_{_owner_slug}.jsonl"


def enqueue_lead(lead: dict, include_linkedin: bool = True) -> tuple[bool, str]:
    ok, reason = can_enqueue(lead)
    if not ok:
        return False, reason
    search_name = ""
    icp_text = st.session_state.get("icp_text_saved") or ""
    query_id = (lead.get("query_id") or st.session_state.get("active_query_id") or "").strip()
    if query_id:
        sess = memory.get_query_session(query_id)
        if sess:
            search_name = resolve_search_name(sess)
            icp_text = icp_text or (sess.get("icp_text") or "")
    if not search_name:
        search_name = st.session_state.get("view_label") or st.session_state.get("pending_search_name") or ""
    payload = company_queue_payload(lead, search_name=search_name, icp_text=icp_text)
    qid = memory.enqueue_send(payload)
    lead["outreach_status"] = "queued"
    pipe = memory.upsert_pipeline_from_lead(
        lead,
        send_queue_id=qid,
        query_id=query_id,
        icp_text=icp_text,
        search_name=search_name,
        channel="company",
    )
    similar = []
    if pipe.get("id"):
        similar = memory.find_similar_pipeline(pipeline_id=int(pipe["id"]))
    n_msg = len(payload.get("bundle", {}).get("selected_messages") or selected_messages(lead))
    note = f"Queued {lead.get('name') or 'company'} · {n_msg} selected message(s) · dry run only"
    if similar:
        note += f" · {len(similar)} similar already in team pipeline"
    return True, note


def _sync_lead_message_widgets(lead: dict) -> dict:
    """Pull current widget values for every message target into the lead payload."""
    for target in list_message_targets(lead):
        key = target["target_key"]
        lid = lead.get("lead_id") or ""
        email_key = f"edit-mail-{lid}-{key}"
        li_key = f"edit-li-{lid}-{key}"
        sel_mail_key = f"sel-mail-{lid}-{key}"
        sel_li_key = f"sel-li-{lid}-{key}"
        apply_target_edits(
            lead,
            target_key=key,
            email_draft=st.session_state.get(email_key, target.get("email_draft") or ""),
            linkedin_note=st.session_state.get(li_key, target.get("linkedin_note") or ""),
            select_email=st.session_state.get(sel_mail_key, target.get("select_email")),
            select_linkedin=st.session_state.get(sel_li_key, target.get("select_linkedin")),
        )
    return lead


def _render_message_editors(lead: dict) -> None:
    st.markdown("##### Generated messages")
    st.caption(
        "All generated mail and LinkedIn notes for this company. "
        "Edit in place, then tick Select under a message to include it in the company queue."
    )
    targets = list_message_targets(lead)
    if not targets:
        st.caption("No outreach drafts on this result yet.")
        return
    lid = lead.get("lead_id") or ""
    for target in targets:
        key = target["target_key"]
        title = target["label"]
        role = target.get("role") or ""
        st.markdown(f"**{title}**{f' · {role}' if role else ''}")
        email_key = f"edit-mail-{lid}-{key}"
        li_key = f"edit-li-{lid}-{key}"
        sel_mail_key = f"sel-mail-{lid}-{key}"
        sel_li_key = f"sel-li-{lid}-{key}"
        if email_key not in st.session_state:
            st.session_state[email_key] = target.get("email_draft") or ""
        if li_key not in st.session_state:
            st.session_state[li_key] = target.get("linkedin_note") or ""
        if sel_mail_key not in st.session_state:
            st.session_state[sel_mail_key] = bool(target.get("select_email"))
        if sel_li_key not in st.session_state:
            st.session_state[sel_li_key] = bool(target.get("select_linkedin"))

        st.markdown("Sample mail")
        st.text_area(
            "Sample mail",
            height=140,
            key=email_key,
            label_visibility="collapsed",
            placeholder="Sample mail",
        )
        st.checkbox(
            "Select — add this mail to the queue",
            key=sel_mail_key,
            disabled=not (st.session_state.get(email_key) or "").strip(),
        )

        st.markdown("LinkedIn note")
        st.text_area(
            "LinkedIn note",
            height=110,
            key=li_key,
            label_visibility="collapsed",
            placeholder="LinkedIn note",
        )
        st.checkbox(
            "Select — add this LinkedIn note to the queue",
            key=sel_li_key,
            disabled=not (st.session_state.get(li_key) or "").strip(),
        )

        if st.button("Save edits for this contact", key=f"save-msg-{lid}-{key}", use_container_width=True):
            apply_target_edits(
                lead,
                target_key=key,
                email_draft=st.session_state.get(email_key, ""),
                linkedin_note=st.session_state.get(li_key, ""),
                select_email=bool(st.session_state.get(sel_mail_key)),
                select_linkedin=bool(st.session_state.get(sel_li_key)),
            )
            lead["review_status"] = "edited"
            memory.update_review(lid, "edited", lead)
            st.toast(f"Saved messages for {title}")
            st.rerun()
        st.divider()


leads = st.session_state.leads
review_tab, direct_tab, indirect_tab, send_tab = st.tabs(
    ["Results", "Direct contacts", "Indirect contacts", "Queue"]
)

with review_tab:
    if st.session_state.composer_open:
        st.caption("Finish creating the search above — results will appear here.")
    elif not leads:
        st.markdown(
            empty_state_html(
                "No companies in this fetch yet",
                "Use Fetch more on the current search, or Create new search to start fresh.",
            ),
            unsafe_allow_html=True,
        )
        if st.session_state.logs:
            with st.expander("Last search log", expanded=True):
                for line in st.session_state.logs:
                    st.write("· " + line)
    else:
        st.markdown(
            results_summary_html(st.session_state.funnel or {}, len(leads)),
            unsafe_allow_html=True,
        )
        if st.session_state.funnel:
            st.markdown(funnel_html(st.session_state.funnel), unsafe_allow_html=True)
        _render_full_export_buttons(prefix="results-", use_container_width=True)

        # Results = every matched company (full dossier). Direct/Indirect tabs are contact-focused.
        sorted_idxs = sorted(
            range(len(leads)),
            key=lambda i: ((leads[i].get("score") or {}).get("total") or 0),
            reverse=True,
        )
        n_direct = sum(1 for l in leads if (l.get("result_section") or "") == "verified_people")
        n_indirect = sum(1 for l in leads if (l.get("result_section") or "") == "approach_channels")

        left, right = st.columns([0.32, 0.68], gap="medium")
        with left:
            st.caption(
                f"{len(leads)} companies · {n_direct} direct · {n_indirect} indirect"
            )
            sel = min(st.session_state.selected, len(sorted_idxs) - 1)
            idx_pick = st.radio(
                " ",
                list(range(len(sorted_idxs))),
                format_func=lambda pi: queue_label(leads[sorted_idxs[pi]]),
                index=sel,
                label_visibility="collapsed",
            )
            st.session_state.selected = idx_pick
            idx = sorted_idxs[idx_pick]
            with st.expander("Search queries & log"):
                for q in st.session_state.queries or []:
                    st.code(q)
                for line in st.session_state.logs or []:
                    st.write("· " + line)
        with right:
            lead = leads[idx]
            render_results_similarity(memory, lead, owner_email=_owner_email)

            a, b, c, d = st.columns(4)
            if a.button("Approve", use_container_width=True, type="primary"):
                lead = _sync_lead_message_widgets(lead)
                lead["review_status"] = "approved"
                leads[idx] = lead
                memory.update_review(lead["lead_id"], "approved", lead)
                ok, msg = enqueue_lead(lead)
                st.toast(msg if ok else f"Approved, not queued: {msg}")
                st.rerun()
            if b.button("Save all edits", use_container_width=True, type="secondary"):
                lead = _sync_lead_message_widgets(lead)
                lead["review_status"] = "edited"
                leads[idx] = lead
                memory.update_review(lead["lead_id"], "edited", lead)
                st.toast("All message edits saved")
                st.rerun()
            if c.button("Reject", use_container_width=True, type="secondary"):
                lead["review_status"] = "rejected"
                lead["outreach_status"] = "not_sent"
                leads[idx] = lead
                memory.update_review(lead["lead_id"], "rejected", lead, note="do_not_contact")
                st.toast(f"Rejected {lead['name']}")
                st.rerun()
            if d.button("Queue selected", use_container_width=True, type="secondary"):
                lead = _sync_lead_message_widgets(lead)
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
            st.markdown(detail_html(lead, omit_drafts=True), unsafe_allow_html=True)
            _render_message_editors(lead)
            lid = lead.get("lead_id") or ""
            n_sel = 0
            for target in list_message_targets(lead):
                key = target["target_key"]
                if st.session_state.get(f"sel-mail-{lid}-{key}") and (
                    st.session_state.get(f"edit-mail-{lid}-{key}") or ""
                ).strip():
                    n_sel += 1
                if st.session_state.get(f"sel-li-{lid}-{key}") and (
                    st.session_state.get(f"edit-li-{lid}-{key}") or ""
                ).strip():
                    n_sel += 1
            st.caption(
                f"{n_sel} message(s) selected · Queue selected adds one company item with only those messages. "
                "Unverified signals, blocked drafts, and QA flags do not stop you if you still want it in the queue."
            )

with direct_tab:
    if st.session_state.composer_open:
        st.caption("Finish creating the search above first.")
    elif not leads:
        st.markdown(
            empty_state_html(
                "No direct contacts yet",
                "Run a search — verified decision-makers for your ICP appear here with channels and a crafted email each.",
            ),
            unsafe_allow_html=True,
        )
    else:
        pairs = iter_direct_people(leads)
        st.markdown(section_banner_html("direct", len(pairs)), unsafe_allow_html=True)
        if not pairs:
            st.markdown(
                empty_state_html(
                    "No verified decision-makers in this fetch",
                    "Check Indirect contacts for company approach channels, or Fetch more.",
                ),
                unsafe_allow_html=True,
            )
        else:
            for i, (lead, person) in enumerate(pairs):
                # st.html avoids markdown treating indented/multiline card markup as code.
                st.html(direct_person_card_html(lead, person, delay_ms=min(i * 40, 400)))

with indirect_tab:
    if st.session_state.composer_open:
        st.caption("Finish creating the search above first.")
    elif not leads:
        st.markdown(
            empty_state_html(
                "No indirect contacts yet",
                "When the exact person isn’t found, best company channels for the ICP show up here with a first-touch email.",
            ),
            unsafe_allow_html=True,
        )
    else:
        rows = iter_indirect_leads(leads)
        st.markdown(section_banner_html("indirect", len(rows)), unsafe_allow_html=True)
        if not rows:
            st.markdown(
                empty_state_html(
                    "No company-channel leads",
                    "Every matched company either has a direct contact or still needs enrichment.",
                ),
                unsafe_allow_html=True,
            )
        else:
            for i, lead in enumerate(rows):
                st.html(indirect_company_card_html(lead, delay_ms=min(i * 40, 400)))

with send_tab:
    st.caption(
        "One queue per company — summary, status updates, and detailed view in the same place. "
        "Nothing is delivered externally; marking Outreach sent logs a local dry-run."
    )
    pipe_stats = memory.pipeline_stats(team=False)
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Queued", pipe_stats.get("queued") or 0)
    p2.metric("Outreach sent", pipe_stats.get("outreach_sent") or 0)
    p3.metric("Ongoing", pipe_stats.get("ongoing") or 0)
    p4.metric("Closed", (pipe_stats.get("success") or 0) + (pipe_stats.get("failure") or 0))
    render_working_queue(memory=memory, owner_email=_owner_email, is_admin=_is_admin)
    if not memory.list_pipeline():
        st.markdown(
            empty_state_html(
                "Nothing in your queue yet",
                "Select messages on a result and Queue selected — similar matches do not block you.",
            ),
            unsafe_allow_html=True,
        )
    history = [r for r in memory.list_send_queue() if r["status"] != "queued"]
    if history or DRY_RUN_LOG.exists():
        with st.expander("Activity log", expanded=False):
            if history:
                st.dataframe(
                    [
                        {
                            "When": r.get("dispatched_at") or r.get("queued_at"),
                            "Company": r.get("company"),
                            "Status": r.get("status"),
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

