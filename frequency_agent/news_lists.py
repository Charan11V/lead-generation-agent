"""Owner-scoped curated lists of Signal Desk news articles."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .util import default_db_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NewsListStore:
    """Named lists of news_ids for an account (same SQLite file as Memory / NewsStore)."""

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
                CREATE TABLE IF NOT EXISTS news_lists (
                    list_id TEXT PRIMARY KEY,
                    owner_email TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_news_lists_owner ON news_lists (owner_email);
                CREATE TABLE IF NOT EXISTS news_list_items (
                    list_id TEXT NOT NULL,
                    news_id TEXT NOT NULL,
                    owner_email TEXT NOT NULL,
                    added_at TEXT,
                    PRIMARY KEY (list_id, news_id)
                );
                CREATE INDEX IF NOT EXISTS idx_news_list_items_owner ON news_list_items (owner_email);
                CREATE INDEX IF NOT EXISTS idx_news_list_items_news ON news_list_items (news_id);
                """
            )
            self._migrate_deep(conn)

    def _migrate_deep(self, conn: sqlite3.Connection) -> None:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(news_list_items)").fetchall()}
        alters = {
            "deep_researched_at": "ALTER TABLE news_list_items ADD COLUMN deep_researched_at TEXT",
            "lead_json": "ALTER TABLE news_list_items ADD COLUMN lead_json TEXT DEFAULT ''",
            "deep_error": "ALTER TABLE news_list_items ADD COLUMN deep_error TEXT DEFAULT ''",
        }
        for col, sql in alters.items():
            if col not in cols:
                conn.execute(sql)

    def create_list(self, name: str, description: str = "") -> dict:
        label = (name or "").strip() or "Untitled list"
        desc = (description or "").strip()
        list_id = "nli_" + uuid.uuid4().hex[:16]
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO news_lists (
                    list_id, owner_email, name, description, created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (list_id, self._write_owner(), label, desc, now, now),
            )
        return self.get_list(list_id) or {
            "list_id": list_id,
            "name": label,
            "description": desc,
            "created_at": now,
            "updated_at": now,
            "item_count": 0,
        }

    def get_list(self, list_id: str, *, include_deleted: bool = False) -> dict | None:
        lid = (list_id or "").strip()
        if not lid:
            return None
        owner_sql = self._owner_filter()
        deleted_sql = "" if include_deleted else " AND (deleted_at IS NULL OR deleted_at = '')"
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT l.*,
                    (
                        SELECT COUNT(*) FROM news_list_items i
                        WHERE i.list_id = l.list_id
                    ) AS item_count
                FROM news_lists l
                WHERE l.list_id = ?{owner_sql}{deleted_sql}
                """,
                (lid, *self._owner_params()),
            ).fetchone()
        return dict(row) if row else None

    def list_lists(self, *, limit: int = 100) -> list[dict]:
        owner_sql = self._owner_filter("l")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT l.*,
                    (
                        SELECT COUNT(*) FROM news_list_items i
                        WHERE i.list_id = l.list_id
                    ) AS item_count
                FROM news_lists l
                WHERE (l.deleted_at IS NULL OR l.deleted_at = ''){owner_sql}
                ORDER BY l.updated_at DESC, l.created_at DESC
                LIMIT ?
                """,
                (*self._owner_params(), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_list(self, list_id: str, *, name: str, description: str) -> dict | None:
        lid = (list_id or "").strip()
        if not lid:
            return None
        label = (name or "").strip() or "Untitled list"
        desc = (description or "").strip()
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE news_lists
                SET name = ?, description = ?, updated_at = ?
                WHERE list_id = ? AND (deleted_at IS NULL OR deleted_at = ''){owner_sql}
                """,
                (label, desc, _now(), lid, *self._owner_params()),
            )
        return self.get_list(lid)

    def soft_delete_list(self, list_id: str) -> bool:
        lid = (list_id or "").strip()
        if not lid:
            return False
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE news_lists
                SET deleted_at = ?, updated_at = ?
                WHERE list_id = ? AND (deleted_at IS NULL OR deleted_at = ''){owner_sql}
                """,
                (_now(), _now(), lid, *self._owner_params()),
            )
            return cur.rowcount > 0

    def add_items(self, list_id: str, news_ids: list[str]) -> int:
        """Add news_ids to list. Returns count newly added (skips duplicates)."""
        lid = (list_id or "").strip()
        if not lid or not self.get_list(lid):
            return 0
        ids = [n.strip() for n in news_ids if (n or "").strip()]
        if not ids:
            return 0
        owner = self._write_owner()
        now = _now()
        added = 0
        with self._connect() as conn:
            for nid in ids:
                try:
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO news_list_items (list_id, news_id, owner_email, added_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (lid, nid, owner, now),
                    )
                    added += cur.rowcount
                except sqlite3.Error:
                    continue
            if added:
                conn.execute(
                    f"""
                    UPDATE news_lists SET updated_at = ?
                    WHERE list_id = ?{self._owner_filter()}
                    """,
                    (now, lid, *self._owner_params()),
                )
        return added

    def remove_items(self, list_id: str, news_ids: list[str]) -> int:
        lid = (list_id or "").strip()
        ids = [n.strip() for n in news_ids if (n or "").strip()]
        if not lid or not ids:
            return 0
        owner_sql = self._owner_filter()
        placeholders = ",".join("?" * len(ids))
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                DELETE FROM news_list_items
                WHERE list_id = ? AND news_id IN ({placeholders}){owner_sql}
                """,
                (lid, *ids, *self._owner_params()),
            )
            n = cur.rowcount
            if n:
                conn.execute(
                    f"""
                    UPDATE news_lists SET updated_at = ?
                    WHERE list_id = ?{owner_sql}
                    """,
                    (_now(), lid, *self._owner_params()),
                )
            return n

    def list_item_ids(self, list_id: str) -> list[str]:
        lid = (list_id or "").strip()
        if not lid:
            return []
        owner_sql = self._owner_filter()
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT news_id FROM news_list_items
                WHERE list_id = ?{owner_sql}
                ORDER BY added_at DESC
                """,
                (lid, *self._owner_params()),
            ).fetchall()
        return [(r["news_id"] or "").strip() for r in rows if (r["news_id"] or "").strip()]

    def list_items_with_news(self, list_id: str) -> list[dict]:
        """Join list membership to news_items (includes soft-deleted news so list stays readable)."""
        import json

        lid = (list_id or "").strip()
        if not lid or not self.get_list(lid):
            return []
        owner_sql = self._owner_filter("i")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    i.added_at AS list_added_at,
                    i.deep_researched_at AS deep_researched_at,
                    i.lead_json AS lead_json,
                    i.deep_error AS deep_error,
                    n.*
                FROM news_list_items i
                LEFT JOIN news_items n ON n.news_id = i.news_id
                WHERE i.list_id = ?{owner_sql}
                ORDER BY i.added_at DESC
                """,
                (lid, *self._owner_params()),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            d = dict(row)
            if not d.get("news_id"):
                d["news_id"] = ""
            if not d.get("title"):
                d["title"] = "(story removed from desk)"
            try:
                d["reasons"] = json.loads(d.get("reasons_json") or "[]")
            except json.JSONDecodeError:
                d["reasons"] = []
            raw_lead = (d.get("lead_json") or "").strip()
            lead = None
            if raw_lead:
                try:
                    lead = json.loads(raw_lead)
                except json.JSONDecodeError:
                    lead = None
            d["lead"] = lead if isinstance(lead, dict) else None
            d["is_enriched"] = bool((d.get("deep_researched_at") or "").strip() and d.get("lead"))
            d["deep_error"] = (d.get("deep_error") or "").strip()
            out.append(d)
        return out

    def pending_deep_research_ids(self, list_id: str) -> list[str]:
        """News IDs on the list that have not been successfully deep-researched yet."""
        return [
            (i.get("news_id") or "").strip()
            for i in self.list_items_with_news(list_id)
            if (i.get("news_id") or "").strip() and not i.get("is_enriched")
        ]

    def save_deep_research(
        self,
        list_id: str,
        news_id: str,
        lead: dict | None,
        *,
        error: str = "",
    ) -> bool:
        import json

        lid = (list_id or "").strip()
        nid = (news_id or "").strip()
        if not lid or not nid:
            return False
        owner_sql = self._owner_filter()
        now = _now()
        lead_json = json.dumps(lead, default=str) if lead else ""
        researched_at = now if lead else None
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE news_list_items
                SET deep_researched_at = ?, lead_json = ?, deep_error = ?
                WHERE list_id = ? AND news_id = ?{owner_sql}
                """,
                (researched_at, lead_json, (error or "").strip(), lid, nid, *self._owner_params()),
            )
            if cur.rowcount:
                conn.execute(
                    f"""
                    UPDATE news_lists SET updated_at = ?
                    WHERE list_id = ?{owner_sql}
                    """,
                    (now, lid, *self._owner_params()),
                )
            return cur.rowcount > 0

    def get_list_item(self, list_id: str, news_id: str) -> dict | None:
        for item in self.list_items_with_news(list_id):
            if (item.get("news_id") or "").strip() == (news_id or "").strip():
                return item
        return None

    def lists_containing_news(self, news_ids: list[str]) -> dict[str, list[dict]]:
        """Map each news_id → [{list_id, name}, ...] for active (non-deleted) lists."""
        ids = [n.strip() for n in news_ids if (n or "").strip()]
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        owner_sql = self._owner_filter("i")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT i.news_id AS news_id, l.list_id AS list_id, l.name AS name
                FROM news_list_items i
                INNER JOIN news_lists l ON l.list_id = i.list_id
                WHERE i.news_id IN ({placeholders})
                  AND (l.deleted_at IS NULL OR l.deleted_at = '')
                  {owner_sql}
                ORDER BY l.name COLLATE NOCASE ASC, l.created_at ASC
                """,
                (*ids, *self._owner_params()),
            ).fetchall()
        out: dict[str, list[dict]] = {nid: [] for nid in ids}
        for r in rows:
            nid = (r["news_id"] or "").strip()
            if not nid:
                continue
            out.setdefault(nid, []).append(
                {
                    "list_id": (r["list_id"] or "").strip(),
                    "name": (r["name"] or "").strip() or "Untitled",
                }
            )
        return out

    def clear_owner(self) -> None:
        with self._connect() as conn:
            if self.owner_email:
                conn.execute("DELETE FROM news_list_items WHERE owner_email = ?", (self.owner_email,))
                conn.execute("DELETE FROM news_lists WHERE owner_email = ?", (self.owner_email,))
            else:
                conn.execute("DELETE FROM news_list_items")
                conn.execute("DELETE FROM news_lists")
