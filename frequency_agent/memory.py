"""SQLite memory: leads, runs, page cache, review history, search persistence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_icp_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def icp_fingerprint(service_line: str, icp_text: str) -> str:
    raw = f"{(service_line or '').strip().lower()}|{normalize_icp_text(icp_text)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


class Memory:
    def __init__(self, path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parent.parent
        self.path = Path(path) if path else root / "frequency_agent.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS leads (
                    lead_id TEXT PRIMARY KEY,
                    domain TEXT,
                    company TEXT,
                    contact TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    score INTEGER,
                    signal_hash TEXT,
                    signal_summary TEXT,
                    outreach_status TEXT,
                    review_status TEXT,
                    last_contacted TEXT,
                    do_not_contact INTEGER DEFAULT 0,
                    payload_json TEXT
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    started TEXT,
                    finished TEXT,
                    icp TEXT,
                    service_line TEXT,
                    funnel_json TEXT
                );
                CREATE TABLE IF NOT EXISTS page_cache (
                    url TEXT PRIMARY KEY,
                    fetched TEXT,
                    title TEXT,
                    text TEXT
                );
                CREATE TABLE IF NOT EXISTS send_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT,
                    company TEXT,
                    channel TEXT,
                    recipient TEXT,
                    subject TEXT,
                    body TEXT,
                    status TEXT,
                    queued_at TEXT,
                    dispatched_at TEXT,
                    mode TEXT DEFAULT 'dry_run',
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id TEXT,
                    action TEXT,
                    at TEXT,
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS run_leads (
                    run_id TEXT,
                    lead_id TEXT,
                    is_new INTEGER DEFAULT 1,
                    PRIMARY KEY (run_id, lead_id)
                );
                CREATE TABLE IF NOT EXISTS query_sessions (
                    query_id TEXT PRIMARY KEY,
                    icp_text TEXT,
                    service_line TEXT,
                    created_at TEXT,
                    last_run_at TEXT,
                    label TEXT
                );
                CREATE TABLE IF NOT EXISTS query_leads (
                    query_id TEXT,
                    lead_id TEXT,
                    run_id TEXT,
                    discovery_web_query TEXT,
                    linked_at TEXT,
                    PRIMARY KEY (query_id, lead_id)
                );
                """
            )
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
        alters = {
            "icp_hash": "ALTER TABLE runs ADD COLUMN icp_hash TEXT",
            "queries_json": "ALTER TABLE runs ADD COLUMN queries_json TEXT",
            "logs_json": "ALTER TABLE runs ADD COLUMN logs_json TEXT",
            "lead_ids_json": "ALTER TABLE runs ADD COLUMN lead_ids_json TEXT",
            "new_lead_ids_json": "ALTER TABLE runs ADD COLUMN new_lead_ids_json TEXT",
            "csv_path": "ALTER TABLE runs ADD COLUMN csv_path TEXT",
            "label": "ALTER TABLE runs ADD COLUMN label TEXT",
            "skipped_seen": "ALTER TABLE runs ADD COLUMN skipped_seen INTEGER DEFAULT 0",
            "query_id": "ALTER TABLE runs ADD COLUMN query_id TEXT",
        }
        for col, sql in alters.items():
            if col not in cols:
                conn.execute(sql)
        lead_cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        if "icp_hash" not in lead_cols:
            conn.execute("ALTER TABLE leads ADD COLUMN icp_hash TEXT")

    def get_cached_page(self, url: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT url, title, text, fetched FROM page_cache WHERE url = ?",
                (url,),
            ).fetchone()
        return dict(row) if row else None

    def cache_page(self, url: str, title: str, text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO page_cache (url, fetched, title, text)
                VALUES (?, ?, ?, ?)
                """,
                (url, _now(), title or "", text or ""),
            )

    def existing_lead(self, domain: str | None, company: str) -> dict | None:
        with self._connect() as conn:
            if domain and domain not in {"unknown", "not_found"}:
                row = conn.execute(
                    "SELECT * FROM leads WHERE domain = ?", (domain,)
                ).fetchone()
                if row:
                    return dict(row)
            row = conn.execute(
                "SELECT * FROM leads WHERE lower(company) = lower(?)", (company,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_lead(self, lead: dict, icp_hash: str = "") -> None:
        now = _now()
        existing = self.existing_lead(lead.get("domain"), lead["name"])
        first_seen = existing["first_seen"] if existing else now
        hash_val = icp_hash or lead.get("icp_hash") or (existing or {}).get("icp_hash") or ""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO leads (
                    lead_id, domain, company, contact, first_seen, last_seen,
                    score, signal_hash, signal_summary, outreach_status,
                    review_status, last_contacted, do_not_contact, payload_json, icp_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead["lead_id"],
                    lead.get("domain") or "unknown",
                    lead["name"],
                    (lead.get("contact") or {}).get("name", "not_found"),
                    first_seen,
                    now,
                    (lead.get("score") or {}).get("total", 0),
                    lead.get("signal_hash", ""),
                    (lead.get("signal") or {}).get("summary", ""),
                    lead.get("outreach_status", "not_sent"),
                    lead.get("review_status", "pending"),
                    (existing or {}).get("last_contacted"),
                    1 if existing and existing.get("do_not_contact") else 0,
                    json.dumps(lead, ensure_ascii=False),
                    hash_val,
                ),
            )

    def update_review(self, lead_id: str, status: str, payload: dict | None = None, note: str = "") -> None:
        with self._connect() as conn:
            if payload is not None:
                conn.execute(
                    """
                    UPDATE leads SET review_status = ?, payload_json = ?
                    WHERE lead_id = ?
                    """,
                    (status, json.dumps(payload, ensure_ascii=False), lead_id),
                )
            else:
                conn.execute(
                    "UPDATE leads SET review_status = ? WHERE lead_id = ?",
                    (status, lead_id),
                )
            if status == "rejected":
                conn.execute(
                    "UPDATE leads SET do_not_contact = 1 WHERE lead_id = ?",
                    (lead_id,),
                )
                conn.execute(
                    "UPDATE send_queue SET status = 'held', note = 'removed — lead rejected' WHERE lead_id = ? AND status = 'queued'",
                    (lead_id,),
                )
            conn.execute(
                "INSERT INTO review_events (lead_id, action, at, note) VALUES (?, ?, ?, ?)",
                (lead_id, status, _now(), note),
            )

    def enqueue_send(self, item: dict) -> int:
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM send_queue
                WHERE lead_id = ? AND channel = ? AND status = 'queued'
                """,
                (item["lead_id"], item["channel"]),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE send_queue
                    SET company=?, recipient=?, subject=?, body=?, queued_at=?, note=?
                    WHERE id=?
                    """,
                    (
                        item["company"],
                        item["recipient"],
                        item.get("subject") or "",
                        item["body"],
                        _now(),
                        item.get("note") or "updated in place",
                        existing["id"],
                    ),
                )
                return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO send_queue (
                    lead_id, company, channel, recipient, subject, body,
                    status, queued_at, dispatched_at, mode, note
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, NULL, 'dry_run', ?)
                """,
                (
                    item["lead_id"],
                    item["company"],
                    item["channel"],
                    item["recipient"],
                    item.get("subject") or "",
                    item["body"],
                    _now(),
                    item.get("note") or "",
                ),
            )
            conn.execute(
                "UPDATE leads SET outreach_status = ? WHERE lead_id = ?",
                ("queued", item["lead_id"]),
            )
            return int(cur.lastrowid)

    def hold_send(self, queue_id: int, note: str = "held by human") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE send_queue SET status = 'held', note = ? WHERE id = ?",
                (note, queue_id),
            )

    def dry_run_dispatch(self, queue_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM send_queue WHERE id = ?", (queue_id,)).fetchone()
            if not row:
                return None
            if row["status"] != "queued":
                return dict(row)
            now = _now()
            conn.execute(
                """
                UPDATE send_queue
                SET status = 'dry_run_sent', dispatched_at = ?, mode = 'dry_run',
                    note = 'DRY RUN — no SMTP, LinkedIn, or WhatsApp call was made'
                WHERE id = ?
                """,
                (now, queue_id),
            )
            conn.execute(
                """
                UPDATE leads SET outreach_status = ?, last_contacted = ?
                WHERE lead_id = ?
                """,
                ("dry_run_sent", now, row["lead_id"]),
            )
            conn.execute(
                "INSERT INTO review_events (lead_id, action, at, note) VALUES (?, ?, ?, ?)",
                (row["lead_id"], "dry_run_sent", now, f"queue_id={queue_id}"),
            )
            return dict(conn.execute("SELECT * FROM send_queue WHERE id = ?", (queue_id,)).fetchone())

    def list_send_queue(self, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM send_queue WHERE status = ? ORDER BY queued_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM send_queue ORDER BY queued_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def send_queue_stats(self) -> dict:
        with self._connect() as conn:
            queued = conn.execute(
                "SELECT COUNT(*) n FROM send_queue WHERE status = 'queued'"
            ).fetchone()["n"]
            sent = conn.execute(
                "SELECT COUNT(*) n FROM send_queue WHERE status = 'dry_run_sent'"
            ).fetchone()["n"]
            held = conn.execute(
                "SELECT COUNT(*) n FROM send_queue WHERE status = 'held'"
            ).fetchone()["n"]
        return {"queued": queued, "dry_run_sent": sent, "held": held}

    def load_all_payloads(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json, review_status, do_not_contact FROM leads ORDER BY score DESC"
            ).fetchall()
        out = []
        for row in rows:
            if not row["payload_json"]:
                continue
            data = json.loads(row["payload_json"])
            data["review_status"] = row["review_status"]
            data["do_not_contact"] = bool(row["do_not_contact"])
            out.append(data)
        return out

    def memory_stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) n FROM leads").fetchone()["n"]
            rejected = conn.execute(
                "SELECT COUNT(*) n FROM leads WHERE do_not_contact = 1"
            ).fetchone()["n"]
            runs = conn.execute("SELECT COUNT(*) n FROM runs").fetchone()["n"]
            queries = conn.execute("SELECT COUNT(*) n FROM query_sessions").fetchone()["n"]
        return {"seen": total, "do_not_contact": rejected, "runs": runs, "queries": queries}

    def seen_for_icp(self, fingerprint: str) -> dict:
        """Companies already found for this ICP+service_line fingerprint."""
        from .util import normalize_name

        domains: set[str] = set()
        names: set[str] = set()
        lead_ids: set[str] = set()
        with self._connect() as conn:
            # Leads tagged with this icp_hash
            rows = conn.execute(
                "SELECT lead_id, domain, company, payload_json FROM leads WHERE icp_hash = ?",
                (fingerprint,),
            ).fetchall()
            # Also any lead linked to a prior run with this hash
            run_rows = conn.execute(
                "SELECT lead_ids_json FROM runs WHERE icp_hash = ?",
                (fingerprint,),
            ).fetchall()
            extra_ids: list[str] = []
            for rr in run_rows:
                if rr["lead_ids_json"]:
                    try:
                        extra_ids.extend(json.loads(rr["lead_ids_json"]))
                    except json.JSONDecodeError:
                        pass
            if extra_ids:
                placeholders = ",".join("?" * len(extra_ids))
                more = conn.execute(
                    f"SELECT lead_id, domain, company, payload_json FROM leads WHERE lead_id IN ({placeholders})",
                    extra_ids,
                ).fetchall()
                rows = list(rows) + list(more)

        for row in rows:
            lead_ids.add(row["lead_id"])
            if row["domain"] and row["domain"] not in {"unknown", "not_found"}:
                domains.add(row["domain"].lower())
            if row["company"]:
                names.add(normalize_name(row["company"]))
        return {"domains": domains, "names": names, "lead_ids": lead_ids}

    def is_seen_for_icp(self, fingerprint: str, domain: str, company: str) -> bool:
        from .util import normalize_name

        seen = self.seen_for_icp(fingerprint)
        if domain and domain not in {"unknown", "not_found"} and domain.lower() in seen["domains"]:
            return True
        if normalize_name(company) in seen["names"]:
            return True
        return False

    def save_run(
        self,
        run_id: str,
        icp: str,
        service_line: str,
        funnel: dict,
        *,
        queries: list | None = None,
        logs: list | None = None,
        lead_ids: list[str] | None = None,
        new_lead_ids: list[str] | None = None,
        csv_path: str = "",
        skipped_seen: int = 0,
        started: str | None = None,
        query_id: str = "",
    ) -> None:
        fp = icp_fingerprint(service_line, icp)
        label = f"{service_line} · {(icp or '')[:60]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, started, finished, icp, service_line, funnel_json,
                    icp_hash, queries_json, logs_json, lead_ids_json, new_lead_ids_json,
                    csv_path, label, skipped_seen, query_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started or _now(),
                    _now(),
                    icp,
                    service_line,
                    json.dumps(funnel),
                    fp,
                    json.dumps(queries or []),
                    json.dumps(logs or []),
                    json.dumps(lead_ids or []),
                    json.dumps(new_lead_ids or []),
                    csv_path,
                    label,
                    skipped_seen,
                    query_id or "",
                ),
            )
            for lid in lead_ids or []:
                is_new = 1 if lid in (new_lead_ids or []) else 0
                conn.execute(
                    """
                    INSERT OR REPLACE INTO run_leads (run_id, lead_id, is_new)
                    VALUES (?, ?, ?)
                    """,
                    (run_id, lid, is_new),
                )

    def list_runs(self, limit: int = 40) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, started, finished, icp, service_line, funnel_json,
                       icp_hash, label, csv_path, skipped_seen, lead_ids_json, new_lead_ids_json
                FROM runs
                ORDER BY finished DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["funnel"] = json.loads(d.pop("funnel_json") or "{}")
            except json.JSONDecodeError:
                d["funnel"] = {}
            try:
                d["lead_ids"] = json.loads(d.get("lead_ids_json") or "[]")
            except json.JSONDecodeError:
                d["lead_ids"] = []
            try:
                d["new_lead_ids"] = json.loads(d.get("new_lead_ids_json") or "[]")
            except json.JSONDecodeError:
                d["new_lead_ids"] = []
            d["lead_count"] = len(d["lead_ids"])
            d["new_count"] = len(d["new_lead_ids"])
            out.append(d)
        return out

    def load_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["funnel"] = json.loads(d.get("funnel_json") or "{}")
            except json.JSONDecodeError:
                d["funnel"] = {}
            try:
                d["queries"] = json.loads(d.get("queries_json") or "[]")
            except json.JSONDecodeError:
                d["queries"] = []
            try:
                d["logs"] = json.loads(d.get("logs_json") or "[]")
            except json.JSONDecodeError:
                d["logs"] = []
            try:
                d["lead_ids"] = json.loads(d.get("lead_ids_json") or "[]")
            except json.JSONDecodeError:
                d["lead_ids"] = []
            try:
                d["new_lead_ids"] = json.loads(d.get("new_lead_ids_json") or "[]")
            except json.JSONDecodeError:
                d["new_lead_ids"] = []

            leads: list[dict] = []
            if d["lead_ids"]:
                placeholders = ",".join("?" * len(d["lead_ids"]))
                lrows = conn.execute(
                    f"SELECT payload_json, review_status, do_not_contact FROM leads WHERE lead_id IN ({placeholders})",
                    d["lead_ids"],
                ).fetchall()
                by_id = {}
                for lr in lrows:
                    if not lr["payload_json"]:
                        continue
                    data = json.loads(lr["payload_json"])
                    data["review_status"] = lr["review_status"]
                    data["do_not_contact"] = bool(lr["do_not_contact"])
                    by_id[data.get("lead_id")] = data
                # Preserve run order
                for lid in d["lead_ids"]:
                    if lid in by_id:
                        leads.append(by_id[lid])
            d["leads"] = leads
        return d

    def latest_run(self) -> dict | None:
        runs = self.list_runs(limit=1)
        if not runs:
            return None
        return self.load_run(runs[0]["run_id"])

    def all_leads_for_icp(self, fingerprint: str) -> list[dict]:
        """Every lead ever found for this ICP fingerprint (across runs)."""
        seen = self.seen_for_icp(fingerprint)
        if not seen["lead_ids"]:
            return []
        with self._connect() as conn:
            ids = list(seen["lead_ids"])
            placeholders = ",".join("?" * len(ids))
            rows = conn.execute(
                f"""
                SELECT payload_json, review_status, do_not_contact, score
                FROM leads WHERE lead_id IN ({placeholders})
                ORDER BY score DESC
                """,
                ids,
            ).fetchall()
        out = []
        for row in rows:
            if not row["payload_json"]:
                continue
            data = json.loads(row["payload_json"])
            data["review_status"] = row["review_status"]
            data["do_not_contact"] = bool(row["do_not_contact"])
            out.append(data)
        return out

    # ── Query-centric sessions (dedup only within a query) ──

    def create_query_session(self, icp_text: str, service_line: str) -> str:
        import uuid

        qid = uuid.uuid4().hex[:12]
        now = _now()
        label = f"{service_line} · {(icp_text or '')[:72]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO query_sessions (query_id, icp_text, service_line, created_at, last_run_at, label)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (qid, icp_text, service_line, now, now, label),
            )
        return qid

    def touch_query_session(self, query_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE query_sessions SET last_run_at = ? WHERE query_id = ?",
                (_now(), query_id),
            )

    def get_query_session(self, query_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM query_sessions WHERE query_id = ?", (query_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_query_sessions(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT qs.*, COUNT(ql.lead_id) AS lead_count
                FROM query_sessions qs
                LEFT JOIN query_leads ql ON ql.query_id = qs.query_id
                GROUP BY qs.query_id
                ORDER BY qs.last_run_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def link_lead_to_query(
        self,
        query_id: str,
        lead_id: str,
        run_id: str,
        discovery_web_query: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO query_leads (query_id, lead_id, run_id, discovery_web_query, linked_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (query_id, lead_id, run_id, discovery_web_query or "", _now()),
            )

    def seen_for_query(self, query_id: str) -> dict:
        """Companies already linked to this query session — used for per-query dedup only."""
        from .util import normalize_name

        domains: set[str] = set()
        names: set[str] = set()
        lead_ids: set[str] = set()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT l.lead_id, l.domain, l.company
                FROM query_leads ql
                JOIN leads l ON l.lead_id = ql.lead_id
                WHERE ql.query_id = ?
                """,
                (query_id,),
            ).fetchall()
        for row in rows:
            lead_ids.add(row["lead_id"])
            if row["domain"] and row["domain"] not in {"unknown", "not_found"}:
                domains.add(row["domain"].lower())
            if row["company"]:
                names.add(normalize_name(row["company"]))
        return {"domains": domains, "names": names, "lead_ids": lead_ids}

    def leads_for_query(self, query_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT l.payload_json, l.review_status, l.do_not_contact, l.score,
                       ql.discovery_web_query, ql.run_id, ql.linked_at
                FROM query_leads ql
                JOIN leads l ON l.lead_id = ql.lead_id
                WHERE ql.query_id = ?
                ORDER BY l.score DESC
                """,
                (query_id,),
            ).fetchall()
        out = []
        for row in rows:
            if not row["payload_json"]:
                continue
            data = json.loads(row["payload_json"])
            data["review_status"] = row["review_status"]
            data["do_not_contact"] = bool(row["do_not_contact"])
            data["discovery_web_query"] = row["discovery_web_query"] or data.get("discovery_web_query") or ""
            data["fetch_run_id"] = row["run_id"] or data.get("fetch_run_id") or ""
            data["linked_at"] = row["linked_at"]
            data["query_id"] = query_id
            out.append(data)
        return out

    def unified_results(self) -> list[dict]:
        """All queries with their leads — for the unified history view."""
        sessions = self.list_query_sessions(limit=100)
        out = []
        for s in sessions:
            qid = s["query_id"]
            leads = self.leads_for_query(qid)
            runs = self.list_runs_for_query(qid)
            out.append(
                {
                    **s,
                    "leads": leads,
                    "fetch_count": len(runs),
                    "runs": runs,
                }
            )
        return out

    def list_runs_for_query(self, query_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, started, finished, funnel_json, lead_ids_json, new_lead_ids_json, skipped_seen
                FROM runs WHERE query_id = ?
                ORDER BY finished DESC
                """,
                (query_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["funnel"] = json.loads(d.get("funnel_json") or "{}")
            except json.JSONDecodeError:
                d["funnel"] = {}
            try:
                d["lead_ids"] = json.loads(d.get("lead_ids_json") or "[]")
            except json.JSONDecodeError:
                d["lead_ids"] = []
            d["lead_count"] = len(d["lead_ids"])
            out.append(d)
        return out

    def clear_all_data(self, keep_page_cache: bool = True) -> None:
        with self._connect() as conn:
            for table in (
                "query_leads",
                "run_leads",
                "review_events",
                "send_queue",
                "runs",
                "query_sessions",
                "leads",
            ):
                conn.execute(f"DELETE FROM {table}")
            if not keep_page_cache:
                conn.execute("DELETE FROM page_cache")
