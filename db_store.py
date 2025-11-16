import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from datetime import datetime

DEFAULT_UPDATE_FREQUENCY = 1  # days
DEFAULT_FREE_ONLY = False


class ChapterDatabase:
    """SQLite-backed store for links and scraped entries."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS links (
                    id INTEGER PRIMARY KEY,
                    url TEXT UNIQUE NOT NULL,
                    name TEXT,
                    category TEXT NOT NULL,
                    update_frequency INTEGER NOT NULL DEFAULT 1,
                    free_only INTEGER NOT NULL DEFAULT 0,
                    last_saved TEXT NOT NULL DEFAULT 'N/A'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scraped_entries (
                    link_id INTEGER UNIQUE,
                    last_found TEXT,
                    timestamp TEXT,
                    retrieved_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(link_id) REFERENCES links(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_category ON links(category)")

    @staticmethod
    def _normalize_frequency(value):
        try:
            freq = float(value)
            rounded = int(freq) if freq.is_integer() else int(freq) + 1
            return max(1, rounded)
        except (TypeError, ValueError):
            return DEFAULT_UPDATE_FREQUENCY

    @staticmethod
    def _to_flag(value):
        return 1 if bool(value) else 0

    def _get_link_id(self, url: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM links WHERE url = ?", (url,)).fetchone()
            return row["id"] if row else None

    def get_links(self, category: str) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT url, name, update_frequency, free_only FROM links WHERE category = ? ORDER BY id",
                (category,),
            ).fetchall()
        return [
            {
                "url": row["url"],
                "name": row["name"],
                "update_frequency": row["update_frequency"],
                "free_only": bool(row["free_only"]),
            }
            for row in rows
        ]

    def add_link(
        self,
        name: str,
        url: str,
        category: str,
        update_frequency: int,
        free_only: bool,
    ):
        freq = self._normalize_frequency(update_frequency)
        flag = self._to_flag(free_only)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO links (url, name, category, update_frequency, free_only)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    update_frequency=excluded.update_frequency,
                    free_only=excluded.free_only
                """,
                (url, name, category, freq, flag),
            )

    def update_link(
        self,
        original_url: str,
        new_url: str,
        name: str,
        update_frequency: int,
        free_only: bool,
    ):
        freq = self._normalize_frequency(update_frequency)
        flag = self._to_flag(free_only)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE links
                SET url = ?, name = ?, update_frequency = ?, free_only = ?
                WHERE url = ?
                """,
                (new_url, name, freq, flag, original_url),
            )

    def remove_link(self, url: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM links WHERE url = ?", (url,))

    def get_scraped_data(self, category: str) -> Dict[str, Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT l.url,
                       l.name,
                       l.free_only,
                       l.last_saved,
                       se.last_found,
                       se.timestamp
                FROM links l
                LEFT JOIN scraped_entries se ON l.id = se.link_id
                WHERE l.category = ?
                """,
                (category,),
            ).fetchall()
        result = {}
        for row in rows:
            result[row["url"]] = {
                "name": row["name"],
                "free_only": bool(row["free_only"]),
                "last_saved": row["last_saved"],
                "last_found": row["last_found"] or "No data",
                "timestamp": row["timestamp"] or datetime.now().strftime("%Y/%m/%d"),
            }
        return result

    def update_scraped_entry(self, url: str, last_found: str, timestamp: str):
        link_id = self._get_link_id(url)
        if not link_id:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scraped_entries (link_id, last_found, timestamp)
                VALUES (?, ?, ?)
                ON CONFLICT(link_id) DO UPDATE SET
                    last_found = excluded.last_found,
                    timestamp = excluded.timestamp,
                    retrieved_at = excluded.retrieved_at
                """,
                (link_id, last_found, timestamp),
            )

    def mark_saved(self, url: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE links
                SET last_saved = (
                    SELECT IFNULL(last_found, 'N/A')
                    FROM scraped_entries
                    WHERE link_id = links.id
                )
                WHERE url = ?
                """,
                (url,),
            )

    def set_last_saved(self, url: str, value: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE links SET last_saved = ? WHERE url = ?",
                (value or "N/A", url),
            )

    def update_link_metadata(
        self,
        url: str,
        name: Optional[str] = None,
        free_only: Optional[bool] = None,
    ):
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if free_only is not None:
            updates.append("free_only = ?")
            params.append(self._to_flag(free_only))
        if not updates:
            return
        params.append(url)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE links SET {', '.join(updates)} WHERE url = ?", tuple(params)
            )

    def merge_scraped(self, entries: Dict[str, Dict]):
        for url, entry in entries.items():
            if not entry.get("last_found"):
                continue
            if entry.get("name"):
                self.update_link_metadata(url, name=entry["name"])
            if "free_only" in entry:
                self.update_link_metadata(url, free_only=entry["free_only"])
            self.update_scraped_entry(url, entry["last_found"], entry["timestamp"])
