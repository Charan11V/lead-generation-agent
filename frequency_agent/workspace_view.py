"""Helpers for opening one or many fetches into the Results view."""

from __future__ import annotations


def merge_run_payloads(loaded_runs: list[dict]) -> dict:
    """
    Merge multiple memory.load_run() payloads into one Results session payload.

    Leads are deduped by lead_id (fallback: name|website). First occurrence wins —
    callers should pass runs newest-first so fresher drafts stay.
    """
    if not loaded_runs:
        return {
            "leads": [],
            "funnel": {},
            "logs": [],
            "queries": [],
            "run_ids": [],
            "run_id": "",
            "query_id": "",
            "query_ids": [],
            "icp_hash": "",
            "icp": "",
            "service_line": "",
            "csv_path": "",
            "label": "",
        }

    leads: list[dict] = []
    seen: set[str] = set()
    for run in loaded_runs:
        rid = (run.get("run_id") or "").strip()
        for lead in run.get("leads") or []:
            lid = (lead.get("lead_id") or "").strip()
            key = lid or f"{(lead.get('name') or '').strip().lower()}|{(lead.get('website') or '').strip().lower()}"
            if not key or key in seen:
                continue
            seen.add(key)
            row = dict(lead)
            if rid and not (row.get("fetch_run_id") or "").strip():
                row["fetch_run_id"] = rid
            leads.append(row)

    funnel: dict = {}
    for run in loaded_runs:
        for k, v in (run.get("funnel") or {}).items():
            if isinstance(v, (int, float)):
                funnel[k] = funnel.get(k, 0) + v
            elif k not in funnel:
                funnel[k] = v

    logs: list = []
    for run in loaded_runs:
        logs.extend(run.get("logs") or [])

    queries: list = []
    seen_q: set[str] = set()
    for run in loaded_runs:
        for q in run.get("queries") or []:
            s = str(q)
            if s in seen_q:
                continue
            seen_q.add(s)
            queries.append(q)

    run_ids = [(r.get("run_id") or "").strip() for r in loaded_runs if (r.get("run_id") or "").strip()]
    query_ids = sorted(
        {
            (r.get("query_id") or "").strip()
            for r in loaded_runs
            if (r.get("query_id") or "").strip()
        }
    )
    # Single shared query → usable for Fetch more; mixed → empty (blocked).
    query_id = query_ids[0] if len(query_ids) == 1 else ""

    first = loaded_runs[0]
    n = len(run_ids)
    label = (first.get("label") or "").strip()
    if n > 1:
        label = f"{n} fetches · {len(leads)} companies"

    return {
        "leads": leads,
        "funnel": funnel,
        "logs": logs,
        "queries": queries,
        "run_ids": run_ids,
        "run_id": run_ids[0] if run_ids else "",
        "query_id": query_id,
        "query_ids": query_ids,
        "icp_hash": first.get("icp_hash") or "",
        "icp": first.get("icp") or "",
        "service_line": first.get("service_line") or "",
        "csv_path": first.get("csv_path") or "",
        "label": label,
    }


def fetch_more_guard(
    *,
    active_query_id: str,
    locked_brief: str,
    query_ids_in_view: list[str] | None = None,
) -> tuple[bool, str]:
    """Whether Fetch more is allowed for the current Results view."""
    qid = (active_query_id or "").strip()
    brief = (locked_brief or "").strip()
    if not qid or not brief:
        return False, "Open or create a search first."
    ids = [x.strip() for x in (query_ids_in_view or []) if (x or "").strip()]
    uniq = sorted(set(ids))
    if len(uniq) > 1:
        return (
            False,
            "Fetch more needs one search. Open selected fetches from a single search only.",
        )
    if uniq and uniq[0] != qid:
        return (
            False,
            "Opened fetches belong to a different search. Open that search’s fetches to fetch more.",
        )
    return True, ""
