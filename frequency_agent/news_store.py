"""Per-account Frequency signal-desk storage (same SQLite file as Memory)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .util import default_db_path, slug_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


class NewsStore:
    """Owner-scoped news items. Unscoped instance is for admin / tests."""

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
        if not self.owner_email:
            return ""
        col = f"{alias}.owner_email" if alias else "owner_email"
        return f" AND {col} = ?"

    def _write_owner(self) -> str:
        if self.owner_email:
            return self.owner_email
        return "unscoped"

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS news_items (
                    news_id TEXT PRIMARY KEY,
                    owner_email TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    url TEXT,
                    title TEXT,
                    source TEXT,
                    provider TEXT,
                    published_at TEXT,
                    fetched_at TEXT,
                    snippet TEXT,
                    why_relevant TEXT,
                    service_line TEXT,
                    score INTEGER DEFAULT 0,
                    reasons_json TEXT DEFAULT '[]',
                    payload_json TEXT DEFAULT '{}',
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_news_owner ON news_items (owner_email);
                CREATE INDEX IF NOT EXISTS idx_news_owner_fp ON news_items (owner_email, fingerprint);
                CREATE INDEX IF NOT EXISTS idx_news_published ON news_items (published_at);
                CREATE INDEX IF NOT EXISTS idx_news_fetched ON news_items (fetched_at);
                CREATE TABLE IF NOT EXISTS news_scans (
                    scan_id TEXT PRIMARY KEY,
                    owner_email TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    window_hours INTEGER DEFAULT 24,
                    incremental INTEGER DEFAULT 0,
                    added_count INTEGER DEFAULT 0,
                    considered_count INTEGER DEFAULT 0,
                    total_visible INTEGER DEFAULT 0,
                    stats_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_news_scans_owner ON news_scans (owner_email);
                """
            )
            self._migrate_eval(conn)

    def _migrate_eval(self, conn: sqlite3.Connection) -> None:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(news_items)").fetchall()}
        alters = {
            "eval_status": "ALTER TABLE news_items ADD COLUMN eval_status TEXT DEFAULT ''",
            "eval_relevant": "ALTER TABLE news_items ADD COLUMN eval_relevant INTEGER",
            "eval_why": "ALTER TABLE news_items ADD COLUMN eval_why TEXT DEFAULT ''",
            "eval_at": "ALTER TABLE news_items ADD COLUMN eval_at TEXT",
        }
        for col, sql in alters.items():
            if col not in cols:
                conn.execute(sql)

    def existing_fingerprints(self, *, include_deleted: bool = True) -> set[str]:
        owner_sql = self._owner_filter()
        extra = "" if include_deleted else " AND (deleted_at IS NULL OR deleted_at = '')"
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT fingerprint FROM news_items WHERE 1=1{owner_sql}{extra}",
                self._owner_params(),
            ).fetchall()
        return {(r["fingerprint"] or "") for r in rows if r["fingerprint"]}

    def upsert_new(self, articles: list[dict]) -> list[dict]:
        """Insert articles that this owner has never stored. Returns newly inserted rows."""
        if not articles:
            return []
        owner = self._write_owner()
        existing = self.existing_fingerprints(include_deleted=True)
        now = _now()
        inserted: list[dict] = []
        with self._connect() as conn:
            for art in articles:
                fp = (art.get("fingerprint") or "").strip()
                if not fp or fp in existing:
                    continue
                news_id = "nws_" + slug_id(owner, fp)
                reasons = art.get("reasons") or []
                if isinstance(reasons, str):
                    reasons_json = reasons
                else:
                    reasons_json = json.dumps(list(reasons))
                row = {
                    "news_id": news_id,
                    "owner_email": owner,
                    "fingerprint": fp,
                    "url": art.get("url") or "",
                    "title": art.get("title") or "",
                    "source": art.get("source") or "",
                    "provider": art.get("provider") or "",
                    "published_at": art.get("published_at") or "",
                    "fetched_at": now,
                    "snippet": art.get("snippet") or "",
                    "why_relevant": art.get("why_relevant") or "",
                    "service_line": art.get("service_line") or "exec_search",
                    "score": int(art.get("score") or 0),
                    "reasons_json": reasons_json,
                    "payload_json": json.dumps(art.get("payload") or {}),
                    "deleted_at": None,
                    "eval_status": "",
                    "eval_relevant": None,
                    "eval_why": "",
                    "eval_at": None,
                }
                conn.execute(
                    """
                    INSERT INTO news_items (
                        news_id, owner_email, fingerprint, url, title, source, provider,
                        published_at, fetched_at, snippet, why_relevant, service_line,
                        score, reasons_json, payload_json, deleted_at
                    ) VALUES (
                        :news_id, :owner_email, :fingerprint, :url, :title, :source, :provider,
                        :published_at, :fetched_at, :snippet, :why_relevant, :service_line,
                        :score, :reasons_json, :payload_json, :deleted_at
                    )
                    """,
                    row,
                )
                existing.add(fp)
                inserted.append(self._row_out(row))
        return inserted

    def _row_out(self, row: dict | sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["reasons"] = json.loads(d.get("reasons_json") or "[]")
        except json.JSONDecodeError:
            d["reasons"] = []
        try:
            d["payload"] = json.loads(d.get("payload_json") or "{}")
        except json.JSONDecodeError:
            d["payload"] = {}
        d["eval_status"] = (d.get("eval_status") or "").strip()
        d["eval_why"] = (d.get("eval_why") or "").strip()
        rel = d.get("eval_relevant")
        if rel in (None, ""):
            d["eval_relevant"] = None
        else:
            d["eval_relevant"] = bool(int(rel))
        return d

    def _sort_key(self, row: dict) -> tuple:
        pub = _parse_dt(row.get("published_at"))
        fetched = _parse_dt(row.get("fetched_at"))
        stamp = pub or fetched or datetime.min.replace(tzinfo=timezone.utc)
        return (-(int(row.get("score") or 0)), -stamp.timestamp())

    def list_items(
        self,
        *,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        include_deleted: bool = False,
        service_line: str = "",
        limit: int = 800,
        owner_email: str | None = None,
    ) -> list[dict]:
        """List saved items. Date bounds use published_at, falling back to fetched_at."""
        owner = (owner_email or "").strip().lower() or self.owner_email
        clauses = ["1=1"]
        params: list = []
        if owner:
            clauses.append("owner_email = ?")
            params.append(owner)
        if not include_deleted:
            clauses.append("(deleted_at IS NULL OR deleted_at = '')")
        if service_line:
            clauses.append("service_line = ?")
            params.append(service_line)
        sql = f"SELECT * FROM news_items WHERE {' AND '.join(clauses)}"
        with self._connect() as conn:
            rows = [self._row_out(r) for r in conn.execute(sql, params).fetchall()]
        start_dt = start if isinstance(start, datetime) else _parse_dt(str(start) if start else "")
        end_dt = end if isinstance(end, datetime) else _parse_dt(str(end) if end else "")
        if start_dt or end_dt:
            filtered = []
            for row in rows:
                stamp = _parse_dt(row.get("published_at")) or _parse_dt(row.get("fetched_at"))
                if stamp is None:
                    if start_dt and not end_dt:
                        continue
                    filtered.append(row)
                    continue
                if start_dt and stamp < start_dt:
                    continue
                if end_dt and stamp > end_dt:
                    continue
                filtered.append(row)
            rows = filtered
        rows.sort(key=self._sort_key)
        return rows[:limit]

    def list_window(self, *, hours: int = 24, **kwargs) -> list[dict]:
        start = datetime.now(timezone.utc) - timedelta(hours=hours)
        return self.list_items(start=start, **kwargs)

    def list_deleted(self, limit: int = 80) -> list[dict]:
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM news_items
                WHERE deleted_at IS NOT NULL AND deleted_at != ''{owner_sql}
                ORDER BY deleted_at DESC
                LIMIT ?
                """,
                (*self._owner_params(), limit),
            ).fetchall()
        return [self._row_out(r) for r in rows]

    def ids_in_range(
        self,
        start: str | datetime,
        end: str | datetime,
        *,
        include_deleted: bool = False,
    ) -> list[str]:
        return [r["news_id"] for r in self.list_items(start=start, end=end, include_deleted=include_deleted)]

    def get_item(self, news_id: str) -> dict | None:
        nid = (news_id or "").strip()
        if not nid:
            return None
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT * FROM news_items WHERE news_id = ?{owner_sql}",
                (nid, *self._owner_params()),
            ).fetchone()
        return self._row_out(row) if row else None

    def mark_eval_running(self, news_id: str) -> bool:
        nid = (news_id or "").strip()
        if not nid:
            return False
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE news_items
                SET eval_status = 'running', eval_relevant = NULL, eval_why = '', eval_at = ?
                WHERE news_id = ?{owner_sql}
                """,
                (_now(), nid, *self._owner_params()),
            )
            return int(cur.rowcount or 0) == 1

    def clear_stale_eval_running(self, *, except_ids: set[str] | None = None) -> int:
        live = {i for i in (except_ids or set()) if i}
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT news_id FROM news_items
                WHERE eval_status = 'running'{owner_sql}
                """,
                self._owner_params(),
            ).fetchall()
            stale = [r["news_id"] for r in rows if r["news_id"] not in live]
            if not stale:
                return 0
            placeholders = ",".join("?" * len(stale))
            cur = conn.execute(
                f"""
                UPDATE news_items
                SET eval_status = '', eval_relevant = NULL, eval_why = ''
                WHERE news_id IN ({placeholders}){owner_sql}
                """,
                [*stale, *self._owner_params()],
            )
            return int(cur.rowcount or 0)

    def save_evaluation(
        self,
        news_id: str,
        *,
        relevant: bool,
        why: str,
        service_line: str = "",
    ) -> bool:
        nid = (news_id or "").strip()
        if not nid:
            return False
        owner_sql = self._owner_filter()
        now = _now()
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE news_items
                SET eval_status = ?, eval_relevant = ?, eval_why = ?, eval_at = ?
                    {", service_line = ?" if service_line else ""}
                WHERE news_id = ?{owner_sql}
                """,
                (
                    "relevant" if relevant else "not_relevant",
                    1 if relevant else 0,
                    (why or "").strip()[:800],
                    now,
                    *([service_line] if service_line else []),
                    nid,
                    *self._owner_params(),
                ),
            )
            return int(cur.rowcount or 0) == 1

    def soft_delete(self, news_ids: list[str]) -> int:
        ids = [i for i in news_ids if i]
        if not ids:
            return 0
        now = _now()
        owner_sql = self._owner_filter()
        placeholders = ",".join("?" * len(ids))
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE news_items SET deleted_at = ?
                WHERE news_id IN ({placeholders}){owner_sql}
                """,
                [now, *ids, *self._owner_params()],
            )
        return len(ids)

    def restore(self, news_ids: list[str]) -> int:
        ids = [i for i in news_ids if i]
        if not ids:
            return 0
        owner_sql = self._owner_filter()
        placeholders = ",".join("?" * len(ids))
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE news_items SET deleted_at = NULL
                WHERE news_id IN ({placeholders}){owner_sql}
                """,
                [*ids, *self._owner_params()],
            )
        return len(ids)

    def permanently_delete(self, news_ids: list[str]) -> int:
        """Hard-delete rows this store can see. Unscoped admin store can wipe any id."""
        ids = [i for i in news_ids if i]
        if not ids:
            return 0
        owner_sql = self._owner_filter()
        placeholders = ",".join("?" * len(ids))
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM news_items WHERE news_id IN ({placeholders}){owner_sql}",
                [*ids, *self._owner_params()],
            )
            return int(cur.rowcount or 0)

    def record_scan(
        self,
        *,
        added_count: int,
        considered_count: int,
        total_visible: int,
        incremental: bool,
        stats: dict | None = None,
        window_hours: int = 24,
    ) -> str:
        scan_id = "scn_" + slug_id(self._write_owner(), _now(), str(uuid.uuid4()))
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO news_scans (
                    scan_id, owner_email, started_at, finished_at, window_hours,
                    incremental, added_count, considered_count, total_visible, stats_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    self._write_owner(),
                    now,
                    now,
                    window_hours,
                    1 if incremental else 0,
                    int(added_count),
                    int(considered_count),
                    int(total_visible),
                    json.dumps(stats or {}),
                ),
            )
        return scan_id

    def latest_scan(self) -> dict | None:
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM news_scans
                WHERE 1=1{owner_sql}
                ORDER BY finished_at DESC
                LIMIT 1
                """,
                self._owner_params(),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["stats"] = json.loads(d.get("stats_json") or "{}")
        except json.JSONDecodeError:
            d["stats"] = {}
        return d

    def last_scan_in_window(self, *, hours: int = 24) -> dict | None:
        latest = self.latest_scan()
        if not latest:
            return None
        finished = _parse_dt(latest.get("finished_at"))
        if not finished:
            return None
        if finished >= datetime.now(timezone.utc) - timedelta(hours=hours):
            return latest
        return None

    def clear_owner(self) -> None:
        with self._connect() as conn:
            if self.owner_email:
                conn.execute("DELETE FROM news_items WHERE owner_email = ?", (self.owner_email,))
                conn.execute("DELETE FROM news_scans WHERE owner_email = ?", (self.owner_email,))
            else:
                conn.execute("DELETE FROM news_items")
                conn.execute("DELETE FROM news_scans")

    def admin_list_all(self, *, limit: int = 200, owner_email: str = "") -> list[dict]:
        clauses = ["(deleted_at IS NULL OR deleted_at = '')"]
        params: list = []
        if owner_email:
            clauses.append("owner_email = ?")
            params.append(owner_email.strip().lower())
        sql = f"""
            SELECT * FROM news_items
            WHERE {' AND '.join(clauses)}
            ORDER BY fetched_at DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
        return [self._row_out(r) for r in rows]

    def admin_count_by_owner(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT owner_email AS email, COUNT(*) AS n
                FROM news_items
                WHERE deleted_at IS NULL OR deleted_at = ''
                GROUP BY owner_email
                """
            ).fetchall()
        return {(r["email"] or "").strip().lower(): int(r["n"] or 0) for r in rows}
