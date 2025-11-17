import datetime
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

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
                    last_saved TEXT NOT NULL DEFAULT 'N/A',
                    added_at TEXT NOT NULL DEFAULT 'N/A',
                    last_attempt TEXT,
                    last_error TEXT
                )
                """
            )
            self._ensure_links_columns(conn)
            self._ensure_scraped_entries_table(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_links_category ON links(category)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scraped_entries_link ON scraped_entries(link_id)"
            )

    def _ensure_scraped_entries_table(self, conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scraped_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link_id INTEGER,
                last_found TEXT,
                timestamp TEXT,
                retrieved_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(link_id) REFERENCES links(id) ON DELETE CASCADE
            )
            """
        )
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(scraped_entries)").fetchall()]
        if "id" not in columns:
            conn.execute("ALTER TABLE scraped_entries RENAME TO scraped_entries_old")
            conn.execute(
                """
                CREATE TABLE scraped_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    link_id INTEGER,
                    last_found TEXT,
                    timestamp TEXT,
                    retrieved_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(link_id) REFERENCES links(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                INSERT INTO scraped_entries (link_id, last_found, timestamp, retrieved_at)
                SELECT link_id, last_found, timestamp, COALESCE(retrieved_at, datetime('now'))
                FROM scraped_entries_old
                """
            )
            conn.execute("DROP TABLE scraped_entries_old")

    def _ensure_links_columns(self, conn):
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(links)").fetchall()]
        needed = {"added_at", "last_attempt", "last_error"}
        missing = needed - set(columns)
        if not missing:
            return
        for col in missing:
            if col == "last_attempt":
                conn.execute("ALTER TABLE links ADD COLUMN last_attempt TEXT")
            elif col == "last_error":
                conn.execute("ALTER TABLE links ADD COLUMN last_error TEXT")
            elif col == "added_at":
                conn.execute("ALTER TABLE links ADD COLUMN added_at TEXT NOT NULL DEFAULT 'N/A'")

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
        added_at = datetime.datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO links (url, name, category, update_frequency, free_only, added_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    update_frequency=excluded.update_frequency,
                    free_only=excluded.free_only
                """,
                (url, name, category, freq, flag, added_at),
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
                SELECT
                    l.url,
                    l.name,
                    l.update_frequency,
                    l.free_only,
                    l.last_saved,
                    l.last_attempt,
                    l.last_error,
                    l.added_at,
                    (
                        SELECT last_found
                        FROM scraped_entries se2
                        WHERE se2.link_id = l.id
                        ORDER BY se2.id DESC
                        LIMIT 1
                    ) AS last_found,
                    (
                        SELECT timestamp
                        FROM scraped_entries se2
                        WHERE se2.link_id = l.id
                        ORDER BY se2.id DESC
                        LIMIT 1
                    ) AS timestamp
                FROM links l
                WHERE l.category = ?
                """,
                (category,),
            ).fetchall()
        result = {}
        for row in rows:
            result[row["url"]] = {
                "name": row["name"],
                "update_frequency": row["update_frequency"],
                "free_only": bool(row["free_only"]),
                "last_saved": row["last_saved"],
                "last_attempt": row["last_attempt"],
                "last_error": row["last_error"],
                "added_at": row["added_at"],
                "last_found": row["last_found"] or "No data",
                "timestamp": row["timestamp"] or datetime.datetime.now().strftime("%Y/%m/%d"),
            }
        return result

    def update_scraped_entry(
        self,
        url: str,
        last_found: str,
        timestamp: str,
        retrieved_at: Optional[str] = None,
    ):
        link_id = self._get_link_id(url)
        if not link_id:
            return
        retrieved_at = retrieved_at or datetime.datetime.now().isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT last_found, timestamp FROM scraped_entries WHERE link_id = ? ORDER BY id DESC LIMIT 1",
                (link_id,),
            ).fetchone()
            if existing and existing["last_found"] == last_found and existing[
                "timestamp"
            ] == timestamp:
                return
            conn.execute(
                """
                INSERT INTO scraped_entries (link_id, last_found, timestamp, retrieved_at)
                VALUES (?, ?, ?, ?)
                """,
                (link_id, last_found, timestamp, retrieved_at),
            )

    def record_failures(self, failures: Dict[str, Dict]):
        if not failures:
            return
        with self._connect() as conn:
            for url, info in failures.items():
                now = datetime.datetime.now().isoformat()
                conn.execute(
                    """
                    UPDATE links
                    SET last_attempt = ?, last_error = ?
                    WHERE url = ?
                    """,
                    (now, info.get("error"), url),
                )

    def record_success(self, url: str, when: Optional[str] = None):
        when = when or datetime.datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE links
                SET last_attempt = ?, last_error = NULL
                WHERE url = ?
                """,
                (when, url),
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
                    ORDER BY id DESC
                    LIMIT 1
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
            self.record_success(url, entry.get("retrieved_at"))
