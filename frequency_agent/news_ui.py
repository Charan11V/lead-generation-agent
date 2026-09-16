"""Premium Signal desk UI — Frequency-relevant news, independent of ICP search."""

from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta, timezone

import streamlit as st

from .accounts import AccountStore
from .icp import service_line_label as icp_service_label
from .memory import Memory
from .news_desk import run_signal_scan
from .news_eval import inflight_ids, is_running, reclaim_stale, start_eval
from .news_relevance import (
    SERVICE_CAP,
    SERVICE_EXEC,
    SERVICE_FRAC,
    rank_band,
    service_line_label,
)
from .news_store import NewsStore


def _esc(value: str | None) -> str:
    return html.escape((value or "").strip())


def _parse_dt(raw: str | None) -> datetime | None:
    text = (raw or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ago(raw: str | None) -> str:
    dt = _parse_dt(raw)
    if not dt:
        return ""
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


def _pretty_when(raw: str | None) -> str:
    dt = _parse_dt(raw)
    if not dt:
        return ""
    return dt.strftime("%d %b %Y · %H:%M UTC")


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _day_end(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=timezone.utc)


def _rail_class(service: str) -> str:
    return {
        SERVICE_EXEC: "exec",
        SERVICE_FRAC: "frac",
        SERVICE_CAP: "cap",
    }.get(service or "", "other")


def desk_hero_html() -> str:
    return """
<div class="fx-desk-hero">
  <p class="fx-kicker">Signal desk</p>
  <h2>What Frequency should see <em>today</em></h2>
  <p>A wide 24-hour sweep of public news, ranked by Frequency’s mandate — funding, CXO moves, hiring, expansion, capital. Nothing is sent to OpenAI until you press <em>Check relevance</em> on a story.</p>
</div>
"""


def desk_metrics_html(
    *,
    visible: int,
    added: int,
    exec_n: int,
    frac_n: int,
    cap_n: int,
    last_scan: str = "",
) -> str:
    last = _ago(last_scan) or "never"
    cells = [
        ("On the desk", str(visible)),
        ("New this scan", str(added)),
        ("Exec search", str(exec_n)),
        ("Fractional", str(frac_n)),
        ("Capital", str(cap_n)),
        ("Last sweep", last),
    ]
    inner = "".join(
        f'<div class="fx-metric"><div class="n">{_esc(n)}</div>'
        f'<div class="l">{_esc(label)}</div></div>'
        for label, n in cells
    )
    return f'<div class="fx-metric-row fx-desk-metrics">{inner}</div>'


def news_card_html(item: dict, *, rank: int = 0) -> str:
    service = item.get("service_line") or SERVICE_EXEC
    title = _esc(item.get("title") or "Untitled")
    url = _esc(item.get("url") or "#")
    source = _esc(item.get("source") or "Source")
    snippet = _esc(item.get("snippet") or "")
    when = _ago(item.get("published_at") or item.get("fetched_at"))
    provider = _esc(item.get("provider") or "")
    score = int(item.get("score") or 0)
    band = rank_band(score)
    reasons = item.get("reasons") or []
    if isinstance(reasons, str):
        reason_txt = reasons
    else:
        reason_txt = " · ".join(str(r) for r in reasons[:3])
    meta_bits = [source]
    if when:
        meta_bits.append(when)
    if provider:
        meta_bits.append(provider.replace("_", " "))
    meta = " · ".join(meta_bits)
    rank_bit = f'<span class="fx-news-rank">#{rank}</span>' if rank else ""
    return f"""
<div class="fx-news-card band-{_esc(band)}">
  <div class="fx-news-rail {_rail_class(service)}" aria-hidden="true"></div>
  <div class="fx-news-body">
    <div class="fx-news-top">
      <span class="fx-pill">{_esc(service_line_label(service))}</span>
      <span class="fx-news-scorewrap">{rank_bit}<span class="fx-news-score">{score}</span></span>
    </div>
    <p class="fx-news-meta">{_esc(meta)}</p>
    <h3 class="fx-news-title"><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></h3>
    {f'<p class="fx-news-why">{snippet}</p>' if snippet else ''}
    {f'<p class="fx-news-hooks">{_esc(reason_txt)}</p>' if reason_txt else ''}
  </div>
</div>
"""


def empty_desk_html() -> str:
    return """
<div class="fx-desk-empty">
  <p class="fx-kicker">Quiet so far</p>
  <h3>Nothing on the desk yet</h3>
  <p>Press <strong>Scan last 24 hours</strong>. Stories arrive ranked best to worst. Check relevance on a story only when you want a verdict.</p>
</div>
"""


def _ensure_news_state() -> None:
    if "news_sel" not in st.session_state:
        st.session_state.news_sel = set()
    if "news_sel_nonce" not in st.session_state:
        st.session_state.news_sel_nonce = 0
    if "news_view_mode" not in st.session_state:
        st.session_state.news_view_mode = "window"
    if "news_line_filter" not in st.session_state:
        st.session_state.news_line_filter = "all"
    if "news_notice" not in st.session_state:
        st.session_state.news_notice = ""
    if "news_last_added" not in st.session_state:
        st.session_state.news_last_added = 0
    if "_news_eval_watch" not in st.session_state:
        st.session_state._news_eval_watch = []


def _clear_news_selection() -> None:
    st.session_state.news_sel = set()
    st.session_state.news_sel_nonce = int(st.session_state.get("news_sel_nonce") or 0) + 1
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith("news-sel-"):
            del st.session_state[key]


def _counts(items: list[dict]) -> tuple[int, int, int]:
    exec_n = sum(1 for i in items if (i.get("service_line") or "") == SERVICE_EXEC)
    frac_n = sum(1 for i in items if (i.get("service_line") or "") == SERVICE_FRAC)
    cap_n = sum(1 for i in items if (i.get("service_line") or "") == SERVICE_CAP)
    return exec_n, frac_n, cap_n


def render_signal_desk_page(
    *,
    owner_email: str,
    memory: Memory,
    accounts: AccountStore,
    is_admin: bool,
    openai_key: str,
) -> None:
    _ensure_news_state()
    store = NewsStore(memory.path, owner_email=owner_email)
    reclaim_stale(store)
    st.session_state._news_eval_path = str(memory.path)
    st.session_state._news_eval_owner = owner_email
    st.markdown(desk_hero_html(), unsafe_allow_html=True)
    if st.session_state.get("_news_eval_watch") or inflight_ids():
        _news_eval_poller()

    scan_col, range_col = st.columns([0.46, 0.54], gap="large")
    with scan_col:
        st.markdown(
            '<div class="fx-desk-panel"><p class="fx-desk-panel-kicker">Live sweep</p>'
            "<h3>Scan the last 24 hours</h3>"
            "<p>Pulls free news APIs and publisher feeds, then ranks every usable story "
            "best to worst. A second press today adds new items beside the ones already saved. "
            "OpenAI is not used until you check a story.</p></div>",
            unsafe_allow_html=True,
        )
        if st.button("Scan last 24 hours", type="primary", use_container_width=True, key="news-scan"):
            with st.spinner("Sweeping public news — Google, GDELT, RSS, DuckDuckGo…"):
                result = run_signal_scan(
                    owner_email=owner_email,
                    db_path=memory.path,
                )
            st.session_state.news_view_mode = "window"
            st.session_state.news_last_added = int(result.get("added") or 0)
            added = int(result.get("added") or 0)
            visible = int(result.get("visible") or 0)
            if result.get("incremental"):
                st.session_state.news_notice = (
                    f"Updated the desk — {added} new stor{'y' if added == 1 else 'ies'} "
                    f"alongside {visible} from the last 24 hours."
                )
            else:
                st.session_state.news_notice = (
                    f"First sweep in this window — {added} stor{'y' if added == 1 else 'ies'} "
                    f"ranked from {result.get('considered') or 0} headlines."
                )
            _clear_news_selection()
            st.rerun()

    today = date.today()
    with range_col:
        st.markdown(
            '<div class="fx-desk-panel"><p class="fx-desk-panel-kicker">Archive</p>'
            "<h3>Browse saved dates</h3>"
            "<p>Does not call APIs. Shows stories already on your account between the dates you pick.</p></div>",
            unsafe_allow_html=True,
        )
        d1, d2 = st.columns(2)
        with d1:
            start_d = st.date_input("From", value=today - timedelta(days=7), key="news-from")
        with d2:
            end_d = st.date_input("To", value=today, key="news-to")
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Show saved", use_container_width=True, key="news-show-range"):
                st.session_state.news_view_mode = "range"
                st.session_state.news_notice = (
                    f"Showing saved stories {_esc(start_d.isoformat())} → {_esc(end_d.isoformat())}."
                )
                _clear_news_selection()
                st.rerun()
        with b2:
            if st.button("Back to 24 hours", use_container_width=True, key="news-back-window"):
                st.session_state.news_view_mode = "window"
                st.session_state.news_notice = ""
                _clear_news_selection()
                st.rerun()

    notice = (st.session_state.get("news_notice") or "").strip()
    if notice:
        st.markdown(f'<div class="fx-desk-banner">{html.escape(notice)}</div>', unsafe_allow_html=True)

    line = st.radio(
        "Practice line",
        ["all", SERVICE_EXEC, SERVICE_FRAC, SERVICE_CAP],
        format_func=lambda v: {
            "all": "All lines",
            SERVICE_EXEC: "Exec search",
            SERVICE_FRAC: "Fractional CXO",
            SERVICE_CAP: "Capital advisory",
        }[v],
        horizontal=True,
        key="news_line_filter",
        label_visibility="collapsed",
    )
    line_arg = "" if line == "all" else line

    if st.session_state.news_view_mode == "range":
        if start_d > end_d:
            st.warning("From date must be on or before To date.")
            items = []
        else:
            items = store.list_items(
                start=_day_start(start_d),
                end=_day_end(end_d),
                service_line=line_arg,
            )
        view_label = f"Saved · ranked · {start_d.isoformat()} → {end_d.isoformat()}"
    else:
        items = store.list_window(hours=24, service_line=line_arg)
        view_label = "Last 24 hours · ranked best to worst"

    latest = store.latest_scan()
    exec_n, frac_n, cap_n = _counts(items)
    st.markdown(
        desk_metrics_html(
            visible=len(items),
            added=int(st.session_state.get("news_last_added") or 0),
            exec_n=exec_n,
            frac_n=frac_n,
            cap_n=cap_n,
            last_scan=(latest or {}).get("finished_at") or "",
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="fx-desk-viewlabel">{_esc(view_label)} · {len(items)} '
        f"stor{'y' if len(items) == 1 else 'ies'}</p>",
        unsafe_allow_html=True,
    )

    _render_delete_bar(
        store,
        items,
        is_admin=is_admin,
        start_d=start_d,
        end_d=end_d,
        view_mode=st.session_state.news_view_mode,
    )

    if not items:
        st.markdown(empty_desk_html(), unsafe_allow_html=True)
    else:
        nonce = int(st.session_state.get("news_sel_nonce") or 0)
        for idx, item in enumerate(items, start=1):
            nid = item.get("news_id") or ""
            c_sel, c_card = st.columns([0.06, 0.94], gap="small")
            with c_sel:
                checked = st.checkbox(
                    "Select",
                    value=nid in st.session_state.news_sel,
                    key=f"news-sel-{nonce}-{nid}",
                    label_visibility="collapsed",
                )
                if checked:
                    st.session_state.news_sel.add(nid)
                else:
                    st.session_state.news_sel.discard(nid)
            with c_card:
                st.markdown(news_card_html(item, rank=idx), unsafe_allow_html=True)
                _render_eval_controls(
                    store,
                    item,
                    openai_key=openai_key,
                    owner_email=owner_email,
                )

    _render_recycle(store)
    if is_admin:
        st.caption("Admin: Delete forever removes stories from this account permanently.")


def _eval_label(item: dict) -> str:
    if item.get("eval_relevant") is True:
        return "Relevant"
    if item.get("eval_relevant") is False:
        return "Not relevant"
    status = (item.get("eval_status") or "").strip()
    if status == "relevant":
        return "Relevant"
    if status == "not_relevant":
        return "Not relevant"
    return ""


def _is_eval_running(item: dict) -> bool:
    nid = (item.get("news_id") or "").strip()
    if nid and is_running(nid):
        return True
    return (item.get("eval_status") or "").strip() == "running"


def _is_evaluated(item: dict) -> bool:
    if _is_eval_running(item):
        return False
    status = (item.get("eval_status") or "").strip()
    return status in {"relevant", "not_relevant"}


def _watch_eval(news_id: str) -> None:
    nid = (news_id or "").strip()
    watched = [i for i in (st.session_state.get("_news_eval_watch") or []) if i]
    if nid and nid not in watched:
        watched.append(nid)
    for live in inflight_ids():
        if live not in watched:
            watched.append(live)
    st.session_state._news_eval_watch = watched


def _render_eval_spinner() -> None:
    st.markdown(
        '<div class="fx-eval-row"><span class="fx-eval-spin" aria-hidden="true"></span>'
        '<span class="fx-eval-busy">Evaluating relevance…</span></div>',
        unsafe_allow_html=True,
    )


def _render_eval_controls(
    store: NewsStore,
    item: dict,
    *,
    openai_key: str,
    owner_email: str,
) -> None:
    nid = (item.get("news_id") or "").strip()
    if not nid:
        return
    running = _is_eval_running(item)
    evaluated = _is_evaluated(item)
    label = _eval_label(item)

    if running:
        _render_eval_spinner()
        st.caption("Running in the background — you can check other stories now.")
        return

    left, mid, right = st.columns([0.28, 0.28, 0.44], gap="small")
    with left:
        if not evaluated:
            if st.button("Check relevance", use_container_width=True, key=f"news-eval-{nid}"):
                start_eval(
                    news_id=nid,
                    owner_email=owner_email,
                    db_path=store.path,
                    openai_key=openai_key,
                    item=item,
                )
                _watch_eval(nid)
                st.rerun()
        else:
            tone = "ok" if "Not" not in label else "no"
            st.markdown(
                f'<p class="fx-eval-verdict {tone}">{_esc(label)}</p>',
                unsafe_allow_html=True,
            )
    with mid:
        if evaluated:
            with st.popover("ⓘ", key=f"news-why-{nid}"):
                st.markdown("**Why this verdict**")
                st.write(item.get("eval_why") or "No explanation stored.")
    with right:
        if not evaluated:
            st.caption("Optional — uses OpenAI only for this story.")


@st.fragment(run_every=1)
def _news_eval_poller() -> None:
    """Refresh the desk when background relevance checks finish."""
    watched = [i for i in (st.session_state.get("_news_eval_watch") or []) if i]
    live = inflight_ids()
    combined = list(dict.fromkeys([*watched, *live]))
    if not combined:
        return
    path = (st.session_state.get("_news_eval_path") or "").strip()
    owner = (st.session_state.get("_news_eval_owner") or "").strip()
    if not path or not owner:
        return
    store = NewsStore(path, owner_email=owner)
    reclaim_stale(store)
    still: list[str] = []
    for nid in combined:
        if is_running(nid):
            still.append(nid)
            continue
        row = store.get_item(nid)
        if row and (row.get("eval_status") or "").strip() == "running":
            still.append(nid)
    prev = list(st.session_state.get("_news_eval_watch") or [])
    st.session_state._news_eval_watch = still
    if still != prev:
        st.rerun()


def _render_delete_bar(
    store: NewsStore,
    items: list[dict],
    *,
    is_admin: bool,
    start_d: date,
    end_d: date,
    view_mode: str,
) -> None:
    selected = [nid for nid in (st.session_state.get("news_sel") or set()) if nid]
    st.markdown('<div class="fx-desk-actions">', unsafe_allow_html=True)
    a1, a2, a3, a4 = st.columns([0.24, 0.24, 0.28, 0.24])
    with a1:
        if st.button("Select all shown", use_container_width=True, key="news-sel-all"):
            st.session_state.news_sel = {i.get("news_id") for i in items if i.get("news_id")}
            st.session_state.news_sel_nonce = int(st.session_state.news_sel_nonce or 0) + 1
            st.rerun()
    with a2:
        if st.button(
            f"Delete selected ({len(selected)})",
            use_container_width=True,
            key="news-del-sel",
            disabled=not selected,
        ):
            n = store.soft_delete(selected)
            st.session_state.news_notice = f"Removed {n} stor{'y' if n == 1 else 'ies'} from your desk."
            _clear_news_selection()
            st.rerun()
    with a3:
        range_label = (
            "Delete saved in dates"
            if view_mode == "range"
            else "Delete in selected dates"
        )
        if st.button(range_label, use_container_width=True, key="news-del-range"):
            if start_d > end_d:
                st.session_state.news_notice = "Fix the date range before deleting."
            else:
                ids = store.ids_in_range(_day_start(start_d), _day_end(end_d))
                n = store.soft_delete(ids)
                st.session_state.news_notice = (
                    f"Removed {n} saved stor{'y' if n == 1 else 'ies'} "
                    f"from {start_d.isoformat()} to {end_d.isoformat()}."
                )
                _clear_news_selection()
            st.rerun()
    with a4:
        if is_admin:
            if st.button(
                "Delete forever",
                use_container_width=True,
                key="news-del-perm",
                disabled=not selected,
            ):
                n = store.permanently_delete(selected)
                st.session_state.news_notice = f"Permanently deleted {n} stor{'y' if n == 1 else 'ies'}."
                _clear_news_selection()
                st.rerun()
        else:
            if st.button("Clear ticks", use_container_width=True, key="news-clear-ticks"):
                _clear_news_selection()
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption(
        "Delete selected removes ticked stories from your account. "
        "Delete in dates removes every saved story in the From–To range — still only yours. "
        + ("Admins can also delete forever." if is_admin else "")
    )


def _render_recycle(store: NewsStore) -> None:
    deleted = store.list_deleted(limit=40)
    if not deleted:
        return
    with st.expander(f"Removed from your desk · {len(deleted)}", expanded=False):
        st.caption("Hidden on your account only. Restore brings them back. Admins can still wipe them forever.")
        for item in deleted:
            nid = item.get("news_id") or ""
            c1, c2 = st.columns([0.78, 0.22])
            with c1:
                st.markdown(
                    f"**{_esc(item.get('title') or 'Untitled')}**  \n"
                    f"{_esc(item.get('source') or '')} · removed {_esc(_ago(item.get('deleted_at')))}"
                )
            with c2:
                if st.button("Restore", key=f"news-restore-{nid}", use_container_width=True):
                    store.restore([nid])
                    st.session_state.news_notice = "Restored to your desk."
                    st.rerun()


def render_admin_signal_panel(*, memory: Memory, viewer_email: str = "") -> None:
    """Admin console: all-account news, date-range wipe, permanent delete."""
    store = NewsStore(memory.path)  # unscoped
    st.markdown("##### Signal desk — all accounts")
    st.caption(
        "Permanent delete cannot be undone. Users can only hide stories on their own desk."
    )
    counts = store.admin_count_by_owner()
    st.caption(
        f"{sum(counts.values())} live stories across {len(counts)} account"
        f"{'s' if len(counts) != 1 else ''}."
    )
    today = date.today()
    owners = ["(all accounts)"] + sorted(e for e in counts if e)
    pick = st.selectbox("Account", owners, key="admin-news-owner")
    owner_arg = "" if pick == "(all accounts)" else pick
    d1, d2 = st.columns(2)
    with d1:
        start_d = st.date_input("From", value=today - timedelta(days=7), key="admin-news-from")
    with d2:
        end_d = st.date_input("To", value=today, key="admin-news-to")
    scoped = NewsStore(memory.path, owner_email=owner_arg or None)
    if owner_arg:
        items = scoped.list_items(start=_day_start(start_d), end=_day_end(end_d), limit=300)
    else:
        items = store.list_items(start=_day_start(start_d), end=_day_end(end_d), limit=300)

    if items:
        st.dataframe(
            [
                {
                    "owner": i.get("owner_email") or "",
                    "when": _pretty_when(i.get("published_at") or i.get("fetched_at")),
                    "line": icp_service_label(i.get("service_line") or "")
                    or service_line_label(i.get("service_line") or ""),
                    "source": i.get("source") or "",
                    "title": i.get("title") or "",
                    "score": i.get("score") or 0,
                    "id": i.get("news_id") or "",
                }
                for i in items
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No saved stories in that range.")

    ids = [i.get("news_id") for i in items if i.get("news_id")]
    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "Permanently delete all shown",
            type="secondary",
            use_container_width=True,
            key="admin-news-wipe-shown",
            disabled=not ids,
        ):
            n = store.permanently_delete(ids)
            st.success(f"Permanently deleted {n} stories.")
            st.rerun()
    with c2:
        st.caption(f"Acting as {viewer_email or 'admin'} · {len(ids)} rows in view")
