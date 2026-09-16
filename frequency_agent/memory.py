"""SQLite memory: leads, runs, page cache, review history, search persistence."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .similarity import (
    PIPELINE_STATUSES,
    can_transition,
    identity_from_lead,
    normalize_pipeline_status,
    require_comment,
)
from .util import default_db_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_icp_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def icp_fingerprint(service_line: str, icp_text: str) -> str:
    raw = f"{(service_line or '').strip().lower()}|{normalize_icp_text(icp_text)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def default_search_name(icp_text: str, service_line: str = "") -> str:
    """Human title when the user leaves the search name empty — prefer ICP text."""
    brief = re.sub(r"\s+", " ", (icp_text or "").strip())
    if not brief:
        return "Untitled search"
    if len(brief) > 72:
        brief = brief[:72].rstrip() + "…"
    return brief


def _is_placeholder_or_legacy_label(label: str, service_line: str = "") -> bool:
    """True when label should be ignored in favor of ICP text."""
    low = (label or "").strip().lower()
    if not low or low in {"untitled search", "untitled", "auto"}:
        return True
    # Pre-naming-option auto labels looked like "exec_search · <brief>"
    sl = (service_line or "").strip().lower()
    if sl and low.startswith(f"{sl} ·"):
        return True
    if " · " in low and low.split(" · ", 1)[0] in {
        "exec_search",
        "capital_advisory",
        "talent",
        "gtm",
        "other",
    }:
        return True
    return False


def resolve_search_name(session: dict | None) -> str:
    """Display name for a search: custom label, else ICP text (empty name → ICP)."""
    if not session:
        return "Untitled search"
    label = (session.get("label") or "").strip()
    if not _is_placeholder_or_legacy_label(label, session.get("service_line") or ""):
        return label
    return default_search_name(session.get("icp_text") or "", session.get("service_line") or "")


# Back-compat alias used by older tests / callers
display_search_name = resolve_search_name


def format_fetch_label(search_name: str, run_id: str, when: str = "") -> str:
    """Auto fetch title: search name · fetch_id · timestamp (latest→oldest in lists)."""
    name = (search_name or "").strip() or "Untitled search"
    rid = (run_id or "").strip()
    ts = (when or "").strip().replace("T", " ")
    if len(ts) > 19:
        ts = ts[:19]
    parts = [name]
    if rid:
        parts.append(rid[:12])
    if ts:
        parts.append(ts)
    return " · ".join(parts)


class Memory:
    """SQLite workspace memory. When owner_email is set, all reads/writes are scoped to that account."""

    # Pre-auth rows with NULL/empty owner_email are attributed to the primary operator.
    # Do NOT list active login emails here — continuous alias remapping used to steal
    # every new write from charanvenkatareddy678@gmail.com onto the admin account on
    # each Memory init. Historical admin data stays under LEGACY_OWNER_EMAIL; Gmail
    # (and any other real user) keeps their own owner_email forever.
    LEGACY_OWNER_EMAIL = "charan.s@frequency.cx"
    LEGACY_OWNER_ALIASES: tuple[str, ...] = ()

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        owner_email: str | None = None,
    ) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.owner_email = (owner_email or "").strip().lower() or None
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _owner_params(self) -> list[str]:
        return [self.owner_email] if self.owner_email else []

    def _owner_filter(self, alias: str = "") -> str:
        """SQL AND-clause for owner scoping (empty when unscoped / tests)."""
        if not self.owner_email:
            return ""
        col = f"{alias}.owner_email" if alias else "owner_email"
        return f" AND {col} = ?"

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
        qs_cols = {r[1] for r in conn.execute("PRAGMA table_info(query_sessions)").fetchall()}
        if "deleted_at" not in qs_cols:
            conn.execute("ALTER TABLE query_sessions ADD COLUMN deleted_at TEXT")
        run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "deleted_at" not in run_cols:
            conn.execute("ALTER TABLE runs ADD COLUMN deleted_at TEXT")

        # Per-account ownership: only unscoped (NULL/blank) rows → admin.
        # Active accounts must never be remapped on every migrate (that caused
        # Gmail user's new searches to vanish after refresh).
        legacy = self.LEGACY_OWNER_EMAIL
        for table in ("query_sessions", "runs", "leads", "send_queue", "review_events"):
            tcols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "owner_email" not in tcols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN owner_email TEXT")
            conn.execute(
                f"""
                UPDATE {table}
                SET owner_email = ?
                WHERE owner_email IS NULL OR trim(owner_email) = ''
                """,
                (legacy,),
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_owner_email ON {table} (owner_email)"
            )

        # Shared outreach pipeline — global entity IDs, per-user rows, team-visible list.
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pipeline_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_entity_id TEXT NOT NULL,
                person_entity_id TEXT DEFAULT '',
                lead_id TEXT,
                send_queue_id INTEGER,
                owner_email TEXT NOT NULL,
                company TEXT,
                domain TEXT,
                person_name TEXT DEFAULT '',
                person_role TEXT DEFAULT '',
                person_email TEXT DEFAULT '',
                person_linkedin TEXT DEFAULT '',
                channel TEXT DEFAULT '',
                query_id TEXT DEFAULT '',
                icp_text TEXT DEFAULT '',
                search_name TEXT DEFAULT '',
                pipeline_status TEXT DEFAULT 'queued',
                comment TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pipeline_owner ON pipeline_items (owner_email);
            CREATE INDEX IF NOT EXISTS idx_pipeline_company ON pipeline_items (company_entity_id);
            CREATE INDEX IF NOT EXISTS idx_pipeline_person ON pipeline_items (person_entity_id);
            CREATE INDEX IF NOT EXISTS idx_pipeline_lead ON pipeline_items (owner_email, lead_id);
            CREATE TABLE IF NOT EXISTS pipeline_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id INTEGER NOT NULL,
                owner_email TEXT,
                action TEXT,
                from_status TEXT DEFAULT '',
                to_status TEXT DEFAULT '',
                comment TEXT DEFAULT '',
                at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pipeline_events_item ON pipeline_events (pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_pipeline_events_owner ON pipeline_events (owner_email);
            """
        )
        conn.execute(
            """
            UPDATE pipeline_items
            SET pipeline_status = 'ongoing'
            WHERE pipeline_status = 'response_received'
            """
        )

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
        owner_sql = self._owner_filter()
        params_extra = self._owner_params()
        with self._connect() as conn:
            if domain and domain not in {"unknown", "not_found"}:
                row = conn.execute(
                    f"SELECT * FROM leads WHERE domain = ?{owner_sql}",
                    (domain, *params_extra),
                ).fetchone()
                if row:
                    return dict(row)
            row = conn.execute(
                f"SELECT * FROM leads WHERE lower(company) = lower(?){owner_sql}",
                (company, *params_extra),
            ).fetchone()
        return dict(row) if row else None

    def _require_write_owner(self) -> str:
        """Owner stamped on every write. Scoped Memory must have an email."""
        if self.owner_email:
            return self.owner_email
        # Unscoped CLI/tests only — never used by the signed-in Streamlit app.
        return self.LEGACY_OWNER_EMAIL

    def upsert_lead(self, lead: dict, icp_hash: str = "") -> None:
        now = _now()
        existing = self.existing_lead(lead.get("domain"), lead["name"])
        first_seen = existing["first_seen"] if existing else now
        hash_val = icp_hash or lead.get("icp_hash") or (existing or {}).get("icp_hash") or ""
        owner = self._require_write_owner()
        # Never adopt another account's owner from an existing row when scoped.
        if self.owner_email:
            owner = self.owner_email
        elif existing and (existing.get("owner_email") or "").strip():
            owner = (existing.get("owner_email") or "").strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO leads (
                    lead_id, domain, company, contact, first_seen, last_seen,
                    score, signal_hash, signal_summary, outreach_status,
                    review_status, last_contacted, do_not_contact, payload_json, icp_hash,
                    owner_email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    owner,
                ),
            )

    def update_review(self, lead_id: str, status: str, payload: dict | None = None, note: str = "") -> None:
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            if payload is not None:
                conn.execute(
                    f"""
                    UPDATE leads SET review_status = ?, payload_json = ?
                    WHERE lead_id = ?{owner_sql}
                    """,
                    (status, json.dumps(payload, ensure_ascii=False), lead_id, *owner_params),
                )
            else:
                conn.execute(
                    f"UPDATE leads SET review_status = ? WHERE lead_id = ?{owner_sql}",
                    (status, lead_id, *owner_params),
                )
            if status == "rejected":
                conn.execute(
                    f"UPDATE leads SET do_not_contact = 1 WHERE lead_id = ?{owner_sql}",
                    (lead_id, *owner_params),
                )
                conn.execute(
                    f"""
                    UPDATE send_queue SET status = 'held', note = 'removed — lead rejected'
                    WHERE lead_id = ? AND status = 'queued'{owner_sql}
                    """,
                    (lead_id, *owner_params),
                )
            conn.execute(
                """
                INSERT INTO review_events (lead_id, action, at, note, owner_email)
                VALUES (?, ?, ?, ?, ?)
                """,
                (lead_id, status, _now(), note, self.owner_email or self.LEGACY_OWNER_EMAIL),
            )

    def enqueue_send(self, item: dict) -> int:
        owner = self.owner_email or self.LEGACY_OWNER_EMAIL
        channel = (item.get("channel") or "email").strip() or "email"
        # One company-bundle row per lead; legacy email/linkedin keep channel uniqueness.
        with self._connect() as conn:
            if channel == "company":
                existing = conn.execute(
                    f"""
                    SELECT id FROM send_queue
                    WHERE lead_id = ? AND channel = 'company' AND status = 'queued'
                    {self._owner_filter()}
                    """,
                    (item["lead_id"], *self._owner_params()),
                ).fetchone()
                # Drop older per-channel queued rows for this lead when bundling.
                conn.execute(
                    f"""
                    DELETE FROM send_queue
                    WHERE lead_id = ? AND status = 'queued' AND channel IN ('email', 'linkedin')
                    {self._owner_filter()}
                    """,
                    (item["lead_id"], *self._owner_params()),
                )
            else:
                existing = conn.execute(
                    f"""
                    SELECT id FROM send_queue
                    WHERE lead_id = ? AND channel = ? AND status = 'queued'
                    {self._owner_filter()}
                    """,
                    (item["lead_id"], channel, *self._owner_params()),
                ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE send_queue
                    SET company=?, channel=?, recipient=?, subject=?, body=?, queued_at=?, note=?
                    WHERE id=?
                    """,
                    (
                        item["company"],
                        channel,
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
                    status, queued_at, dispatched_at, mode, note, owner_email
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, NULL, 'dry_run', ?, ?)
                """,
                (
                    item["lead_id"],
                    item["company"],
                    channel,
                    item["recipient"],
                    item.get("subject") or "",
                    item["body"],
                    _now(),
                    item.get("note") or "",
                    owner,
                ),
            )
            conn.execute(
                f"UPDATE leads SET outreach_status = ? WHERE lead_id = ?{self._owner_filter()}",
                ("queued", item["lead_id"], *self._owner_params()),
            )
            return int(cur.lastrowid)

    def get_send_queue_item(self, queue_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM send_queue WHERE id = ?{self._owner_filter()}",
                (queue_id, *self._owner_params()),
            ).fetchone()
        return dict(row) if row else None

    def get_send_queue_item_any(self, queue_id: int) -> dict | None:
        """Load a send-queue row regardless of owner (central repo)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM send_queue WHERE id = ?",
                (int(queue_id),),
            ).fetchone()
        return dict(row) if row else None

    def get_lead_any(self, lead_id: str, *, owner_email: str | None = None) -> dict | None:
        """Load a lead payload without requiring the current owner match."""
        lead_id = (lead_id or "").strip()
        if not lead_id:
            return None
        owner = (owner_email or "").strip().lower()
        with self._connect() as conn:
            if owner:
                row = conn.execute(
                    """
                    SELECT payload_json, review_status, do_not_contact, score
                    FROM leads
                    WHERE lead_id = ? AND lower(COALESCE(owner_email, '')) = ?
                    """,
                    (lead_id, owner),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT payload_json, review_status, do_not_contact, score
                    FROM leads
                    WHERE lead_id = ?
                    ORDER BY rowid DESC
                    LIMIT 1
                    """,
                    (lead_id,),
                ).fetchone()
        if not row or not row["payload_json"]:
            return None
        try:
            data = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        data["review_status"] = row["review_status"]
        data["do_not_contact"] = bool(row["do_not_contact"])
        if row["score"] is not None and isinstance(data.get("score"), dict):
            data["score"]["total"] = row["score"]
        return data

    def hold_send(self, queue_id: int, note: str = "held by human") -> None:
        with self._connect() as conn:
            conn.execute(
                f"UPDATE send_queue SET status = 'held', note = ? WHERE id = ?{self._owner_filter()}",
                (note, queue_id, *self._owner_params()),
            )

    def dry_run_dispatch(self, queue_id: int) -> dict | None:
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM send_queue WHERE id = ?{owner_sql}",
                (queue_id, *owner_params),
            ).fetchone()
            if not row:
                return None
            if row["status"] != "queued":
                return dict(row)
            now = _now()
            conn.execute(
                f"""
                UPDATE send_queue
                SET status = 'dry_run_sent', dispatched_at = ?, mode = 'dry_run',
                    note = 'DRY RUN — no SMTP, LinkedIn, or WhatsApp call was made'
                WHERE id = ?{owner_sql}
                """,
                (now, queue_id, *owner_params),
            )
            conn.execute(
                f"""
                UPDATE leads SET outreach_status = ?, last_contacted = ?
                WHERE lead_id = ?{owner_sql}
                """,
                ("dry_run_sent", now, row["lead_id"], *owner_params),
            )
            conn.execute(
                """
                INSERT INTO review_events (lead_id, action, at, note, owner_email)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["lead_id"],
                    "dry_run_sent",
                    now,
                    f"queue_id={queue_id}",
                    self.owner_email or self.LEGACY_OWNER_EMAIL,
                ),
            )
            return dict(
                conn.execute(
                    f"SELECT * FROM send_queue WHERE id = ?{owner_sql}",
                    (queue_id, *owner_params),
                ).fetchone()
            )

    def list_send_queue(self, status: str | None = None) -> list[dict]:
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    f"SELECT * FROM send_queue WHERE status = ?{owner_sql} ORDER BY queued_at DESC",
                    (status, *owner_params),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM send_queue WHERE 1=1{owner_sql} ORDER BY queued_at DESC",
                    (*owner_params,),
                ).fetchall()
        return [dict(r) for r in rows]

    def send_queue_stats(self) -> dict:
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            queued = conn.execute(
                f"SELECT COUNT(*) n FROM send_queue WHERE status = 'queued'{owner_sql}",
                (*owner_params,),
            ).fetchone()["n"]
            sent = conn.execute(
                f"SELECT COUNT(*) n FROM send_queue WHERE status = 'dry_run_sent'{owner_sql}",
                (*owner_params,),
            ).fetchone()["n"]
            held = conn.execute(
                f"SELECT COUNT(*) n FROM send_queue WHERE status = 'held'{owner_sql}",
                (*owner_params,),
            ).fetchone()["n"]
        return {"queued": queued, "dry_run_sent": sent, "held": held}

    def _pipeline_row(self, conn: sqlite3.Connection, pipeline_id: int) -> dict | None:
        row = conn.execute(
            "SELECT * FROM pipeline_items WHERE id = ?",
            (pipeline_id,),
        ).fetchone()
        return self._normalize_pipeline_row(row)

    def _normalize_pipeline_row(self, row) -> dict | None:
        if row is None:
            return None
        data = dict(row)
        data["pipeline_status"] = normalize_pipeline_status(data.get("pipeline_status") or "")
        return data

    def get_pipeline_item(self, pipeline_id: int) -> dict | None:
        with self._connect() as conn:
            return self._pipeline_row(conn, pipeline_id)

    def get_pipeline_for_lead(self, lead_id: str) -> dict | None:
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM pipeline_items
                WHERE lead_id = ?{owner_sql}
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (lead_id, *self._owner_params()),
            ).fetchone()
        return self._normalize_pipeline_row(row)

    def list_pipeline(self, status: str | None = None) -> list[dict]:
        """This account's pipeline rows only."""
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    f"""
                    SELECT * FROM pipeline_items
                    WHERE pipeline_status = ?{owner_sql}
                    ORDER BY updated_at DESC
                    """,
                    (status, *owner_params),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT * FROM pipeline_items
                    WHERE 1=1{owner_sql}
                    ORDER BY updated_at DESC
                    """,
                    (*owner_params,),
                ).fetchall()
        return [self._normalize_pipeline_row(r) for r in rows if r]

    def list_team_pipeline(self, status: str | None = None) -> list[dict]:
        """Centralised list — every account's pipeline, for coordination."""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM pipeline_items
                    WHERE pipeline_status = ?
                    ORDER BY updated_at DESC
                    """,
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM pipeline_items
                    ORDER BY updated_at DESC
                    """
                ).fetchall()
        return [self._normalize_pipeline_row(r) for r in rows if r]

    def pipeline_stats(self, *, team: bool = False) -> dict:
        owner_sql = "" if team else self._owner_filter()
        params = [] if team else self._owner_params()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT pipeline_status AS status, COUNT(*) AS n
                FROM pipeline_items
                WHERE 1=1{owner_sql}
                GROUP BY pipeline_status
                """,
                (*params,),
            ).fetchall()
        counts = {s: 0 for s in PIPELINE_STATUSES}
        total = 0
        for row in rows:
            key = (row["status"] or "queued").strip().lower()
            n = int(row["n"] or 0)
            counts[key] = counts.get(key, 0) + n
            total += n
        counts["total"] = total
        return counts

    def upsert_pipeline_from_lead(
        self,
        lead: dict,
        *,
        send_queue_id: int | None = None,
        query_id: str = "",
        icp_text: str = "",
        search_name: str = "",
        channel: str = "email",
    ) -> dict:
        """Create or refresh a pipeline row when a lead enters the send queue.

        Does not reset status if the same owner already progressed this lead.
        """
        ident = identity_from_lead(lead)
        owner = self.owner_email or self.LEGACY_OWNER_EMAIL
        lead_id = (lead.get("lead_id") or "").strip()
        qid = (query_id or lead.get("query_id") or "").strip()
        brief = (icp_text or "").strip()
        label = (search_name or "").strip()
        if qid and (not brief or not label):
            session = self.get_query_session(qid)
            if session:
                brief = brief or (session.get("icp_text") or "")
                label = label or (session.get("label") or "")
        now = _now()
        with self._connect() as conn:
            existing = None
            if lead_id:
                existing = conn.execute(
                    """
                    SELECT * FROM pipeline_items
                    WHERE owner_email = ? AND lead_id = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (owner, lead_id),
                ).fetchone()
            if existing:
                keep_status = existing["pipeline_status"] or "queued"
                conn.execute(
                    """
                    UPDATE pipeline_items SET
                        company_entity_id=?, person_entity_id=?,
                        send_queue_id=COALESCE(?, send_queue_id),
                        company=?, domain=?, person_name=?, person_role=?,
                        person_email=?, person_linkedin=?,
                        channel=?, query_id=?, icp_text=?, search_name=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        ident["company_entity_id"],
                        ident["person_entity_id"],
                        send_queue_id,
                        ident["company"],
                        ident["domain"],
                        ident["person_name"],
                        ident["person_role"],
                        ident["person_email"],
                        ident["person_linkedin"],
                        channel or existing["channel"] or "",
                        qid or existing["query_id"] or "",
                        brief or existing["icp_text"] or "",
                        label or existing["search_name"] or "",
                        now,
                        existing["id"],
                    ),
                )
                row = self._pipeline_row(conn, int(existing["id"]))
                return row or dict(existing) | {"pipeline_status": keep_status}
            cur = conn.execute(
                """
                INSERT INTO pipeline_items (
                    company_entity_id, person_entity_id, lead_id, send_queue_id,
                    owner_email, company, domain, person_name, person_role,
                    person_email, person_linkedin, channel, query_id, icp_text,
                    search_name, pipeline_status, comment, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', '', ?, ?)
                """,
                (
                    ident["company_entity_id"],
                    ident["person_entity_id"],
                    lead_id,
                    send_queue_id,
                    owner,
                    ident["company"],
                    ident["domain"],
                    ident["person_name"],
                    ident["person_role"],
                    ident["person_email"],
                    ident["person_linkedin"],
                    channel,
                    qid,
                    brief,
                    label,
                    now,
                    now,
                ),
            )
            pid = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO pipeline_events (
                    pipeline_id, owner_email, action, from_status, to_status, comment, at
                ) VALUES (?, ?, 'created', '', 'queued', '', ?)
                """,
                (pid, owner, now),
            )
            return self._pipeline_row(conn, pid) or {}

    def update_pipeline_status(
        self,
        pipeline_id: int,
        status: str,
        comment: str = "",
        *,
        as_admin: bool = False,
    ) -> dict:
        status = normalize_pipeline_status(status)
        if status not in PIPELINE_STATUSES:
            raise ValueError(f"Unknown pipeline status: {status}")
        note = (comment or "").strip()
        if require_comment(status) and not note:
            raise ValueError("A comment is required for success or failure.")
        owner = self.owner_email or self.LEGACY_OWNER_EMAIL
        now = _now()
        with self._connect() as conn:
            row = self._pipeline_row(conn, pipeline_id)
            if not row:
                raise ValueError("Pipeline item not found.")
            row_owner = (row.get("owner_email") or "").strip().lower()
            if not as_admin and self.owner_email and row_owner != self.owner_email:
                raise PermissionError("You can only update your own pipeline items.")
            prev = normalize_pipeline_status(row.get("pipeline_status") or "queued")
            if not as_admin and not can_transition(prev, status):
                raise ValueError(
                    f"Status must move in order. From {prev.replace('_', ' ')} the next step is not {status.replace('_', ' ')}."
                )
            conn.execute(
                """
                UPDATE pipeline_items
                SET pipeline_status = ?, comment = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, note if note else (row.get("comment") or ""), now, pipeline_id),
            )
            conn.execute(
                """
                INSERT INTO pipeline_events (
                    pipeline_id, owner_email, action, from_status, to_status, comment, at
                ) VALUES (?, ?, 'status', ?, ?, ?, ?)
                """,
                (pipeline_id, owner, prev, status, note, now),
            )
            updated = self._pipeline_row(conn, pipeline_id)
        return updated or row

    def remove_pipeline_item(
        self,
        pipeline_id: int,
        *,
        as_admin: bool = False,
    ) -> dict:
        """Remove a queue item (pipeline row + linked send_queue + events)."""
        owner = self.owner_email or self.LEGACY_OWNER_EMAIL
        with self._connect() as conn:
            row = self._pipeline_row(conn, pipeline_id)
            if not row:
                raise ValueError("Queue item not found.")
            row_owner = (row.get("owner_email") or "").strip().lower()
            if not as_admin and self.owner_email and row_owner != self.owner_email:
                raise PermissionError("You can only remove your own queue items.")
            qid = row.get("send_queue_id")
            lead_id = (row.get("lead_id") or "").strip()
            conn.execute("DELETE FROM pipeline_events WHERE pipeline_id = ?", (pipeline_id,))
            conn.execute("DELETE FROM pipeline_items WHERE id = ?", (pipeline_id,))
            if qid:
                conn.execute(
                    f"DELETE FROM send_queue WHERE id = ?{self._owner_filter()}",
                    (int(qid), *self._owner_params()),
                )
            elif lead_id:
                # Legacy / bundle rows tied to this lead still sitting in the mail queue
                conn.execute(
                    f"""
                    DELETE FROM send_queue
                    WHERE lead_id = ? AND status = 'queued'{self._owner_filter()}
                    """,
                    (lead_id, *self._owner_params()),
                )
            if lead_id:
                conn.execute(
                    f"""
                    UPDATE leads SET outreach_status = ?
                    WHERE lead_id = ?{self._owner_filter()}
                      AND outreach_status IN ('queued', 'dry_run_sent')
                    """,
                    ("not_sent", lead_id, *self._owner_params()),
                )
            conn.execute(
                """
                INSERT INTO review_events (lead_id, action, at, note, owner_email)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    lead_id or f"pipeline:{pipeline_id}",
                    "queue_removed",
                    _now(),
                    f"pipeline_id={pipeline_id}",
                    owner,
                ),
            )
        return dict(row)

    def list_pipeline_events(
        self,
        pipeline_id: int | None = None,
        *,
        team: bool = False,
        limit: int = 200,
    ) -> list[dict]:
        with self._connect() as conn:
            if pipeline_id is not None:
                rows = conn.execute(
                    """
                    SELECT e.*, p.company, p.person_name, p.owner_email AS item_owner
                    FROM pipeline_events e
                    LEFT JOIN pipeline_items p ON p.id = e.pipeline_id
                    WHERE e.pipeline_id = ?
                    ORDER BY e.at DESC, e.id DESC
                    LIMIT ?
                    """,
                    (pipeline_id, limit),
                ).fetchall()
            elif team:
                rows = conn.execute(
                    """
                    SELECT e.*, p.company, p.person_name, p.owner_email AS item_owner
                    FROM pipeline_events e
                    LEFT JOIN pipeline_items p ON p.id = e.pipeline_id
                    ORDER BY e.at DESC, e.id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT e.*, p.company, p.person_name, p.owner_email AS item_owner
                    FROM pipeline_events e
                    LEFT JOIN pipeline_items p ON p.id = e.pipeline_id
                    WHERE e.owner_email = ?
                    ORDER BY e.at DESC, e.id DESC
                    LIMIT ?
                    """,
                    (self.owner_email or self.LEGACY_OWNER_EMAIL, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def load_all_payloads(self) -> list[dict]:
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT payload_json, review_status, do_not_contact FROM leads WHERE 1=1{owner_sql} ORDER BY score DESC",
                (*self._owner_params(),),
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
        owner_sql = self._owner_filter()
        params = self._owner_params()
        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) n FROM leads WHERE 1=1{owner_sql}", (*params,)
            ).fetchone()["n"]
            rejected = conn.execute(
                f"SELECT COUNT(*) n FROM leads WHERE do_not_contact = 1{owner_sql}",
                (*params,),
            ).fetchone()["n"]
            runs = conn.execute(
                f"SELECT COUNT(*) n FROM runs WHERE 1=1{owner_sql}", (*params,)
            ).fetchone()["n"]
            queries = conn.execute(
                f"SELECT COUNT(*) n FROM query_sessions WHERE 1=1{owner_sql}",
                (*params,),
            ).fetchone()["n"]
        return {"seen": total, "do_not_contact": rejected, "runs": runs, "queries": queries}

    def seen_for_icp(self, fingerprint: str) -> dict:
        """Companies already found for this ICP+service_line fingerprint."""
        from .util import normalize_name

        domains: set[str] = set()
        names: set[str] = set()
        lead_ids: set[str] = set()
        with self._connect() as conn:
            # Leads tagged with this icp_hash (this account only)
            rows = conn.execute(
                f"SELECT lead_id, domain, company, payload_json FROM leads WHERE icp_hash = ?{self._owner_filter()}",
                (fingerprint, *self._owner_params()),
            ).fetchall()
            # Also any lead linked to a prior run with this hash
            run_rows = conn.execute(
                f"SELECT lead_ids_json FROM runs WHERE icp_hash = ?{self._owner_filter()}",
                (fingerprint, *self._owner_params()),
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
                    f"""
                    SELECT lead_id, domain, company, payload_json FROM leads
                    WHERE lead_id IN ({placeholders}){self._owner_filter()}
                    """,
                    (*extra_ids, *self._owner_params()),
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
        finished = _now()
        search_name = ""
        if query_id:
            session = self.get_query_session(query_id)
            search_name = ((session or {}).get("label") or "").strip()
        if not search_name:
            search_name = default_search_name(icp, service_line)
        label = format_fetch_label(search_name, run_id, finished)
        owner = self._require_write_owner()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, started, finished, icp, service_line, funnel_json,
                    icp_hash, queries_json, logs_json, lead_ids_json, new_lead_ids_json,
                    csv_path, label, skipped_seen, query_id, owner_email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    started or finished,
                    finished,
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
                    owner,
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

    def list_runs(self, limit: int = 40, *, include_deleted: bool = False) -> list[dict]:
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            if include_deleted:
                rows = conn.execute(
                    f"""
                    SELECT run_id, started, finished, icp, service_line, funnel_json,
                           icp_hash, label, csv_path, skipped_seen, lead_ids_json, new_lead_ids_json,
                           query_id, deleted_at, owner_email
                    FROM runs
                    WHERE 1=1{owner_sql}
                    ORDER BY finished DESC
                    LIMIT ?
                    """,
                    (*owner_params, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT run_id, started, finished, icp, service_line, funnel_json,
                           icp_hash, label, csv_path, skipped_seen, lead_ids_json, new_lead_ids_json,
                           query_id, deleted_at, owner_email
                    FROM runs
                    WHERE (deleted_at IS NULL OR deleted_at = ''){owner_sql}
                    ORDER BY finished DESC
                    LIMIT ?
                    """,
                    (*owner_params, limit),
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
            row = conn.execute(
                f"SELECT * FROM runs WHERE run_id = ?{self._owner_filter()}",
                (run_id, *self._owner_params()),
            ).fetchone()
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
                    f"""
                    SELECT payload_json, review_status, do_not_contact FROM leads
                    WHERE lead_id IN ({placeholders}){self._owner_filter()}
                    """,
                    (*d["lead_ids"], *self._owner_params()),
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
            d["query_id"] = d.get("query_id") or ""
        return d

    def leads_for_run(self, run_id: str) -> list[dict]:
        """Leads produced in a single fetch only (not cumulative across fetches)."""
        loaded = self.load_run(run_id)
        return (loaded or {}).get("leads") or []

    def list_fetch_history(self, limit: int = 50) -> list[dict]:
        """Saved fetches with metadata for the history UI."""
        out: list[dict] = []
        for meta in self.list_runs(limit=limit):
            rid = meta["run_id"]
            out.append(
                {
                    **meta,
                    "query_id": meta.get("query_id") or "",
                    "icp_text": meta.get("icp") or "",
                }
            )
        return out

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
                FROM leads WHERE lead_id IN ({placeholders}){self._owner_filter()}
                ORDER BY score DESC
                """,
                (*ids, *self._owner_params()),
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

    def get_lead(self, lead_id: str) -> dict | None:
        """Load one lead payload by id (owner-scoped)."""
        lead_id = (lead_id or "").strip()
        if not lead_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT payload_json, review_status, do_not_contact, score, signal_summary
                FROM leads WHERE lead_id = ?{self._owner_filter()}
                """,
                (lead_id, *self._owner_params()),
            ).fetchone()
        if not row or not row["payload_json"]:
            return None
        data = json.loads(row["payload_json"])
        data["review_status"] = row["review_status"]
        data["do_not_contact"] = bool(row["do_not_contact"])
        if row["score"] is not None and isinstance(data.get("score"), dict):
            data["score"]["total"] = row["score"]
        return data

    # ── Query-centric sessions (dedup only within a query) ──

    def create_query_session(self, icp_text: str, service_line: str = "", label: str = "") -> str:
        import uuid

        qid = uuid.uuid4().hex[:12]
        now = _now()
        sl = (service_line or "").strip()
        name = (label or "").strip() or default_search_name(icp_text, sl)
        owner = self._require_write_owner()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO query_sessions (
                    query_id, icp_text, service_line, created_at, last_run_at, label, owner_email
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (qid, icp_text, sl, now, now, name, owner),
            )
        return qid

    def rename_query_session(self, query_id: str, label: str) -> None:
        """Rename a search; empty name falls back to ICP text. Fetch labels inherit it."""
        session = self.get_query_session(query_id)
        if not session:
            return
        name = (label or "").strip() or default_search_name(
            session.get("icp_text") or "", session.get("service_line") or ""
        )
        with self._connect() as conn:
            conn.execute(
                f"UPDATE query_sessions SET label = ? WHERE query_id = ?{self._owner_filter()}",
                (name, query_id, *self._owner_params()),
            )
        self.sync_run_labels_for_query(query_id)

    def sync_run_labels_for_query(self, query_id: str) -> None:
        session = self.get_query_session(query_id)
        if not session:
            return
        search_name = resolve_search_name(session)
        runs = self.list_runs_for_query(query_id, include_deleted=True)
        with self._connect() as conn:
            for r in runs:
                if r.get("deleted_at"):
                    continue
                lbl = format_fetch_label(
                    search_name,
                    r["run_id"],
                    r.get("finished") or r.get("started") or "",
                )
                conn.execute(
                    f"UPDATE runs SET label = ? WHERE run_id = ?{self._owner_filter()}",
                    (lbl, r["run_id"], *self._owner_params()),
                )

    def update_query_session(
        self,
        query_id: str,
        *,
        service_line: str | None = None,
        icp_text: str | None = None,
    ) -> None:
        session = self.get_query_session(query_id)
        if not session:
            return
        sl = (service_line if service_line is not None else session.get("service_line") or "").strip()
        text = icp_text if icp_text is not None else session.get("icp_text") or ""
        # Preserve user-facing search name; do not overwrite on ICP/service updates.
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE query_sessions
                SET service_line = ?, icp_text = ?
                WHERE query_id = ?{self._owner_filter()}
                """,
                (sl, text, query_id, *self._owner_params()),
            )

    def touch_query_session(self, query_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                f"UPDATE query_sessions SET last_run_at = ? WHERE query_id = ?{self._owner_filter()}",
                (_now(), query_id, *self._owner_params()),
            )

    def get_query_session(self, query_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM query_sessions WHERE query_id = ?{self._owner_filter()}",
                (query_id, *self._owner_params()),
            ).fetchone()
        return dict(row) if row else None

    def list_query_sessions(self, limit: int = 50, *, include_deleted: bool = False) -> list[dict]:
        owner_sql = self._owner_filter("qs")
        owner_params = self._owner_params()
        with self._connect() as conn:
            if include_deleted:
                rows = conn.execute(
                    f"""
                    SELECT qs.*, COUNT(ql.lead_id) AS lead_count
                    FROM query_sessions qs
                    LEFT JOIN query_leads ql ON ql.query_id = qs.query_id
                    WHERE 1=1{owner_sql}
                    GROUP BY qs.query_id
                    ORDER BY qs.last_run_at DESC
                    LIMIT ?
                    """,
                    (*owner_params, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT qs.*, COUNT(ql.lead_id) AS lead_count
                    FROM query_sessions qs
                    LEFT JOIN query_leads ql ON ql.query_id = qs.query_id
                    WHERE (qs.deleted_at IS NULL OR qs.deleted_at = ''){owner_sql}
                    GROUP BY qs.query_id
                    ORDER BY qs.last_run_at DESC
                    LIMIT ?
                    """,
                    (*owner_params, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def list_deleted_query_sessions(self, limit: int = 50) -> list[dict]:
        owner_sql = self._owner_filter("qs")
        owner_params = self._owner_params()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT qs.*, COUNT(ql.lead_id) AS lead_count
                FROM query_sessions qs
                LEFT JOIN query_leads ql ON ql.query_id = qs.query_id
                WHERE qs.deleted_at IS NOT NULL AND qs.deleted_at != ''{owner_sql}
                GROUP BY qs.query_id
                ORDER BY qs.deleted_at DESC
                LIMIT ?
                """,
                (*owner_params, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def soft_delete_query_sessions(self, query_ids: list[str]) -> int:
        """Move searches (and their fetches) to the recycle bin."""
        ids = [q for q in query_ids if q]
        if not ids:
            return 0
        now = _now()
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            for qid in ids:
                conn.execute(
                    f"UPDATE query_sessions SET deleted_at = ? WHERE query_id = ?{owner_sql}",
                    (now, qid, *owner_params),
                )
                conn.execute(
                    f"UPDATE runs SET deleted_at = ? WHERE query_id = ?{owner_sql}",
                    (now, qid, *owner_params),
                )
        return len(ids)

    def soft_delete_runs(self, run_ids: list[str]) -> int:
        ids = [r for r in run_ids if r]
        if not ids:
            return 0
        now = _now()
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE runs SET deleted_at = ? WHERE run_id IN ({placeholders}){owner_sql}",
                [now, *ids, *owner_params],
            )
        return len(ids)

    def restore_query_sessions(self, query_ids: list[str]) -> int:
        ids = [q for q in query_ids if q]
        if not ids:
            return 0
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            for qid in ids:
                conn.execute(
                    f"UPDATE query_sessions SET deleted_at = NULL WHERE query_id = ?{owner_sql}",
                    (qid, *owner_params),
                )
                conn.execute(
                    f"UPDATE runs SET deleted_at = NULL WHERE query_id = ?{owner_sql}",
                    (qid, *owner_params),
                )
        return len(ids)

    def restore_runs(self, run_ids: list[str]) -> int:
        ids = [r for r in run_ids if r]
        if not ids:
            return 0
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE runs SET deleted_at = NULL WHERE run_id IN ({placeholders}){owner_sql}",
                [*ids, *owner_params],
            )
            # Ensure parent searches are restored if a fetch is brought back
            rows = conn.execute(
                f"SELECT DISTINCT query_id FROM runs WHERE run_id IN ({placeholders}){owner_sql}",
                [*ids, *owner_params],
            ).fetchall()
            for row in rows:
                qid = row["query_id"]
                if qid:
                    conn.execute(
                        f"UPDATE query_sessions SET deleted_at = NULL WHERE query_id = ?{owner_sql}",
                        (qid, *owner_params),
                    )
        return len(ids)

    def permanently_delete_query_sessions(self, query_ids: list[str]) -> int:
        ids = [q for q in query_ids if q]
        if not ids:
            return 0
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        deleted = 0
        with self._connect() as conn:
            for qid in ids:
                owned = conn.execute(
                    f"SELECT 1 FROM query_sessions WHERE query_id = ?{owner_sql}",
                    (qid, *owner_params),
                ).fetchone()
                if not owned and self.owner_email:
                    continue
                run_rows = conn.execute(
                    f"SELECT run_id FROM runs WHERE query_id = ?{owner_sql}",
                    (qid, *owner_params),
                ).fetchall()
                for rr in run_rows:
                    rid = rr["run_id"]
                    conn.execute("DELETE FROM run_leads WHERE run_id = ?", (rid,))
                    conn.execute(f"DELETE FROM runs WHERE run_id = ?{owner_sql}", (rid, *owner_params))
                conn.execute("DELETE FROM query_leads WHERE query_id = ?", (qid,))
                conn.execute(
                    f"DELETE FROM query_sessions WHERE query_id = ?{owner_sql}",
                    (qid, *owner_params),
                )
                deleted += 1
        return deleted

    def permanently_delete_runs(self, run_ids: list[str]) -> int:
        ids = [r for r in run_ids if r]
        if not ids:
            return 0
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        deleted = 0
        with self._connect() as conn:
            for rid in ids:
                owned = conn.execute(
                    f"SELECT 1 FROM runs WHERE run_id = ?{owner_sql}",
                    (rid, *owner_params),
                ).fetchone()
                if not owned and self.owner_email:
                    continue
                conn.execute("DELETE FROM run_leads WHERE run_id = ?", (rid,))
                conn.execute(f"DELETE FROM runs WHERE run_id = ?{owner_sql}", (rid, *owner_params))
                deleted += 1
        return deleted

    def list_deleted_runs(self, limit: int = 80) -> list[dict]:
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT run_id, started, finished, label, query_id, lead_ids_json, deleted_at, icp, service_line
                FROM runs
                WHERE deleted_at IS NOT NULL AND deleted_at != ''{owner_sql}
                ORDER BY deleted_at DESC
                LIMIT ?
                """,
                (*owner_params, limit),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["lead_ids"] = json.loads(d.get("lead_ids_json") or "[]")
            except json.JSONDecodeError:
                d["lead_ids"] = []
            d["lead_count"] = len(d["lead_ids"])
            out.append(d)
        return out

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
        # Refuse cross-account query ids when scoped
        if self.owner_email and not self.get_query_session(query_id):
            return {"domains": domains, "names": names, "lead_ids": lead_ids}
        owner_sql = self._owner_filter("l")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT l.lead_id, l.domain, l.company
                FROM query_leads ql
                JOIN leads l ON l.lead_id = ql.lead_id
                WHERE ql.query_id = ?{owner_sql}
                """,
                (query_id, *self._owner_params()),
            ).fetchall()
        for row in rows:
            lead_ids.add(row["lead_id"])
            if row["domain"] and row["domain"] not in {"unknown", "not_found"}:
                domains.add(row["domain"].lower())
            if row["company"]:
                names.add(normalize_name(row["company"]))
        return {"domains": domains, "names": names, "lead_ids": lead_ids}

    def leads_for_query(self, query_id: str) -> list[dict]:
        if self.owner_email and not self.get_query_session(query_id):
            return []
        owner_sql = self._owner_filter("l")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT l.payload_json, l.review_status, l.do_not_contact, l.score,
                       ql.discovery_web_query, ql.run_id, ql.linked_at
                FROM query_leads ql
                JOIN leads l ON l.lead_id = ql.lead_id
                WHERE ql.query_id = ?{owner_sql}
                ORDER BY l.score DESC
                """,
                (query_id, *self._owner_params()),
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

    def list_runs_for_query(self, query_id: str, *, include_deleted: bool = False) -> list[dict]:
        owner_sql = self._owner_filter()
        owner_params = self._owner_params()
        with self._connect() as conn:
            if include_deleted:
                rows = conn.execute(
                    f"""
                    SELECT run_id, started, finished, funnel_json, lead_ids_json, new_lead_ids_json,
                           skipped_seen, label, csv_path, icp, service_line, query_id, deleted_at
                    FROM runs WHERE query_id = ?{owner_sql}
                    ORDER BY finished DESC
                    """,
                    (query_id, *owner_params),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT run_id, started, finished, funnel_json, lead_ids_json, new_lead_ids_json,
                           skipped_seen, label, csv_path, icp, service_line, query_id, deleted_at
                    FROM runs
                    WHERE query_id = ? AND (deleted_at IS NULL OR deleted_at = ''){owner_sql}
                    ORDER BY finished DESC
                    """,
                    (query_id, *owner_params),
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
        """Wipe workspace data for this account only (or entire DB if unscoped)."""
        with self._connect() as conn:
            if self.owner_email:
                owner = self.owner_email
                # Join tables first via owned parents
                conn.execute(
                    """
                    DELETE FROM query_leads WHERE query_id IN (
                        SELECT query_id FROM query_sessions WHERE owner_email = ?
                    )
                    """,
                    (owner,),
                )
                conn.execute(
                    """
                    DELETE FROM run_leads WHERE run_id IN (
                        SELECT run_id FROM runs WHERE owner_email = ?
                    )
                    """,
                    (owner,),
                )
                conn.execute(
                    """
                    DELETE FROM pipeline_events WHERE pipeline_id IN (
                        SELECT id FROM pipeline_items WHERE owner_email = ?
                    )
                    """,
                    (owner,),
                )
                for table in (
                    "pipeline_items",
                    "review_events",
                    "send_queue",
                    "runs",
                    "query_sessions",
                    "leads",
                ):
                    conn.execute(f"DELETE FROM {table} WHERE owner_email = ?", (owner,))
                news_tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "news_items" in news_tables:
                    conn.execute("DELETE FROM news_items WHERE owner_email = ?", (owner,))
                if "news_scans" in news_tables:
                    conn.execute("DELETE FROM news_scans WHERE owner_email = ?", (owner,))
            else:
                for table in (
                    "pipeline_events",
                    "pipeline_items",
                    "query_leads",
                    "run_leads",
                    "review_events",
                    "send_queue",
                    "runs",
                    "query_sessions",
                    "leads",
                ):
                    conn.execute(f"DELETE FROM {table}")
                news_tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "news_items" in news_tables:
                    conn.execute("DELETE FROM news_items")
                if "news_scans" in news_tables:
                    conn.execute("DELETE FROM news_scans")
            if not keep_page_cache:
                conn.execute("DELETE FROM page_cache")

    def admin_owner_stats(self) -> list[dict]:
        """Unscoped rollup of workspace activity by owner_email (admin only)."""
        with self._connect() as conn:
            query_rows = {
                (r["email"] or "").strip().lower(): int(r["n"] or 0)
                for r in conn.execute(
                    """
                    SELECT owner_email AS email, COUNT(*) AS n
                    FROM query_sessions
                    WHERE owner_email IS NOT NULL AND trim(owner_email) != ''
                    GROUP BY owner_email
                    """
                ).fetchall()
            }
            lead_rows = {
                (r["email"] or "").strip().lower(): int(r["n"] or 0)
                for r in conn.execute(
                    """
                    SELECT owner_email AS email, COUNT(*) AS n
                    FROM leads
                    WHERE owner_email IS NOT NULL AND trim(owner_email) != ''
                    GROUP BY owner_email
                    """
                ).fetchall()
            }
            run_rows = {
                (r["email"] or "").strip().lower(): int(r["n"] or 0)
                for r in conn.execute(
                    """
                    SELECT owner_email AS email, COUNT(*) AS n
                    FROM runs
                    WHERE owner_email IS NOT NULL AND trim(owner_email) != ''
                    GROUP BY owner_email
                    """
                ).fetchall()
            }
            queue_rows = {
                (r["email"] or "").strip().lower(): int(r["n"] or 0)
                for r in conn.execute(
                    """
                    SELECT owner_email AS email, COUNT(*) AS n
                    FROM send_queue
                    WHERE owner_email IS NOT NULL AND trim(owner_email) != ''
                    GROUP BY owner_email
                    """
                ).fetchall()
            }
            pipe_rows = {
                (r["email"] or "").strip().lower(): int(r["n"] or 0)
                for r in conn.execute(
                    """
                    SELECT owner_email AS email, COUNT(*) AS n
                    FROM pipeline_items
                    WHERE owner_email IS NOT NULL AND trim(owner_email) != ''
                    GROUP BY owner_email
                    """
                ).fetchall()
            }
        emails = sorted(set(query_rows) | set(lead_rows) | set(run_rows) | set(queue_rows) | set(pipe_rows))
        out = []
        for email in emails:
            out.append(
                {
                    "email": email,
                    "queries": query_rows.get(email, 0),
                    "leads": lead_rows.get(email, 0),
                    "runs": run_rows.get(email, 0),
                    "send_queue": queue_rows.get(email, 0),
                    "pipeline": pipe_rows.get(email, 0),
                }
            )
        return sorted(out, key=lambda r: (-r["leads"], -r["queries"], -r["runs"], r["email"]))

    def _admin_scoped(self, email: str) -> "Memory":
        email = (email or "").strip().lower()
        return Memory(path=self.path, owner_email=email)

    def admin_list_all_sessions(self, limit: int = 100) -> list[dict]:
        """Admin: every search across all owners (newest first)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT qs.*, COUNT(ql.lead_id) AS lead_count
                FROM query_sessions qs
                LEFT JOIN query_leads ql ON ql.query_id = qs.query_id
                WHERE (qs.deleted_at IS NULL OR qs.deleted_at = '')
                GROUP BY qs.query_id
                ORDER BY qs.last_run_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def admin_list_all_runs(self, limit: int = 100) -> list[dict]:
        """Admin: every fetch across all owners (newest first)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, started, finished, icp, service_line, funnel_json,
                       icp_hash, label, csv_path, skipped_seen, lead_ids_json,
                       new_lead_ids_json, query_id, deleted_at, owner_email
                FROM runs
                WHERE (deleted_at IS NULL OR deleted_at = '')
                ORDER BY finished DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            try:
                d["lead_ids"] = json.loads(d.get("lead_ids_json") or "[]")
            except json.JSONDecodeError:
                d["lead_ids"] = []
            d["lead_count"] = len(d["lead_ids"])
            out.append(d)
        return out

    def admin_list_sessions(self, email: str, limit: int = 50) -> list[dict]:
        """Admin: list searches for any owner (explicit cross-user API)."""
        return self._admin_scoped(email).list_query_sessions(limit=limit)

    def admin_list_runs(self, email: str, limit: int = 40) -> list[dict]:
        """Admin: list fetches/runs for any owner."""
        return self._admin_scoped(email).list_runs(limit=limit)

    def admin_list_runs_for_query(self, email: str, query_id: str) -> list[dict]:
        return self._admin_scoped(email).list_runs_for_query(query_id)

    def admin_load_run(self, email: str, run_id: str) -> dict | None:
        """Admin: load a fetch + leads for any owner."""
        return self._admin_scoped(email).load_run(run_id)

    def admin_leads_for_query(self, email: str, query_id: str) -> list[dict]:
        return self._admin_scoped(email).leads_for_query(query_id)

    def admin_send_queue(self, email: str, status: str | None = None) -> list[dict]:
        return self._admin_scoped(email).list_send_queue(status=status)

    def admin_list_pipeline(self, email: str | None = None) -> list[dict]:
        if email:
            return self._admin_scoped(email).list_pipeline()
        return self.list_team_pipeline()

    def admin_list_pipeline_events(self, limit: int = 250) -> list[dict]:
        return self.list_pipeline_events(team=True, limit=limit)

    def admin_purge_owner(self, email: str) -> None:
        """Delete all workspace rows for an owner (admin)."""
        email = (email or "").strip().lower()
        if not email:
            return
        self._admin_scoped(email).clear_all_data(keep_page_cache=True)

    def admin_all_leads(self, *, owner_email: str | None = None) -> list[dict]:
        """Admin: full lead payloads (contacts, phones, social, channels) across users."""
        owner = (owner_email or "").strip().lower()
        with self._connect() as conn:
            if owner:
                rows = conn.execute(
                    """
                    SELECT owner_email, payload_json, review_status, do_not_contact, score
                    FROM leads
                    WHERE owner_email = ?
                    ORDER BY score DESC
                    """,
                    (owner,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT owner_email, payload_json, review_status, do_not_contact, score
                    FROM leads
                    WHERE owner_email IS NOT NULL AND trim(owner_email) != ''
                    ORDER BY owner_email ASC, score DESC
                    """
                ).fetchall()
        out: list[dict] = []
        for row in rows:
            if not row["payload_json"]:
                continue
            try:
                data = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            data["owner_email"] = (row["owner_email"] or data.get("owner_email") or "").strip().lower()
            data["review_status"] = row["review_status"] or data.get("review_status") or ""
            data["do_not_contact"] = bool(row["do_not_contact"])
            out.append(data)
        return out
