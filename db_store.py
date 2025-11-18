import datetime
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_UPDATE_FREQUENCY = 1  # days
DEFAULT_FREE_ONLY = False

_DEFAULT_CATEGORIES = [
    ("main", 1),
    ("manga", 5),
    ("novel", 5),
]


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
                    favorite INTEGER NOT NULL DEFAULT 0,
                    last_attempt TEXT,
                    last_error TEXT
                )
                """
            )
            self._ensure_links_columns(conn)
            self._ensure_scraped_entries_table(conn)
            self._ensure_categories_table(conn)
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

    def _ensure_categories_table(self, conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                name TEXT PRIMARY KEY,
                update_interval_hours INTEGER NOT NULL DEFAULT 1,
                last_checked TEXT,
                display_name TEXT,
                include_in_nav INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self._ensure_category_columns(conn)
        self._seed_categories(conn)

    def _ensure_category_columns(self, conn):
        columns = {
            row["name"]: row for row in conn.execute("PRAGMA table_info(categories)").fetchall()
        }
        if "display_name" not in columns:
            conn.execute("ALTER TABLE categories ADD COLUMN display_name TEXT")
        if "include_in_nav" not in columns:
            conn.execute(
                "ALTER TABLE categories ADD COLUMN include_in_nav INTEGER NOT NULL DEFAULT 1"
            )
        rows = conn.execute("SELECT name, display_name FROM categories").fetchall()
        for row in rows:
            current = (row["display_name"] or "").strip()
            fallback = (row["name"][:1] or "M").upper()
            if current and current != fallback:
                continue
            conn.execute(
                "UPDATE categories SET display_name = ? WHERE name = ?",
                (self._default_display_name(row["name"]), row["name"]),
            )
        conn.execute(
            """
            UPDATE categories
            SET include_in_nav = 1
            WHERE include_in_nav IS NULL
            """
        )

    def _seed_categories(self, conn):
        existing = {
            row["name"] for row in conn.execute("SELECT name FROM categories").fetchall()
        }
        for name, hours in _DEFAULT_CATEGORIES:
            if name not in existing:
                conn.execute(
                    """
                    INSERT INTO categories (
                        name,
                        update_interval_hours,
                        display_name,
                        include_in_nav
                    ) VALUES (?, ?, ?, 1)
                    """,
                    (name, hours, self._default_display_name(name)),
                )

    def _ensure_links_columns(self, conn):
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(links)").fetchall()]
        needed = {"added_at", "favorite", "last_attempt", "last_error"}
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
            elif col == "favorite":
                conn.execute("ALTER TABLE links ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")

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

    def _default_display_name(self, name: str) -> str:
        if not name:
            return "Main"
        normalized = (name or "").strip()
        if not normalized:
            return "Main"
        if normalized.lower() == "main":
            return "Main"
        human = normalized.replace("_", " ").replace("-", " ").strip()
        return human.title() or "Main"

    def _normalize_category(self, value: str) -> str:
        return (value or "").strip().lower()

    def _sanitize_interval(self, value: Any) -> int:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    def _get_link_id(self, url: str) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM links WHERE url = ?", (url,)).fetchone()
        return row["id"] if row else None

    def get_links(self, category: str) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT url, name, update_frequency, free_only, favorite FROM links WHERE category = ? ORDER BY id",
                (category,),
            ).fetchall()
        return [
            {
                "url": row["url"],
                "name": row["name"],
                "update_frequency": row["update_frequency"],
                "free_only": bool(row["free_only"]),
                "favorite": bool(row["favorite"]),
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
        favorite: bool = False,
    ):
        freq = self._normalize_frequency(update_frequency)
        flag = self._to_flag(free_only)
        added_at = datetime.datetime.now().isoformat()
        favorite_flag = self._to_flag(favorite)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO links (url, name, category, update_frequency, free_only, added_at, favorite)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    update_frequency=excluded.update_frequency,
                    free_only=excluded.free_only
                """,
                (url, name, category, freq, flag, added_at, favorite_flag),
            )

    def update_link(
        self,
        original_url: str,
        new_url: str,
        name: str,
        update_frequency: int,
        free_only: bool,
        category: Optional[str] = None,
    ):
        freq = self._normalize_frequency(update_frequency)
        flag = self._to_flag(free_only)
        updates = [
            ("url = ?", new_url),
            ("name = ?", name),
            ("update_frequency = ?", freq),
            ("free_only = ?", flag),
        ]
        if category:
            updates.append(("category = ?", category))
        set_clause = ", ".join(clause for clause, _ in updates)
        params = [value for _, value in updates]
        params.append(original_url)
        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE links
                SET {set_clause}
                WHERE url = ?
                """,
                params,
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
                    l.favorite,
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
                "favorite": bool(row["favorite"]),
                "last_found": row["last_found"] or "No data",
                "timestamp": row["timestamp"] or datetime.datetime.now().strftime("%Y/%m/%d"),
            }
        return result

    def get_link_history(self, url: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            link = conn.execute(
                """
                SELECT id, url, name, last_saved, last_attempt, added_at, update_frequency, free_only
                FROM links
                WHERE url = ?
                """,
                (url,),
            ).fetchone()
            if not link:
                return None
            entries = conn.execute(
                """
                SELECT id, last_found, timestamp, retrieved_at
                FROM scraped_entries
                WHERE link_id = ?
                ORDER BY id DESC
                """,
                (link["id"],),
            ).fetchall()
        latest_id = entries[0]["id"] if entries else None
        return {
            "url": link["url"],
            "name": link["name"],
            "last_saved": link["last_saved"],
            "last_attempt": link["last_attempt"],
            "added_at": link["added_at"],
            "update_frequency": link["update_frequency"],
            "free_only": bool(link["free_only"]),
            "history": [
                {
                    "entry_id": row["id"],
                    "last_found": row["last_found"],
                    "timestamp": row["timestamp"],
                    "retrieved_at": row["retrieved_at"],
                    "is_latest": row["id"] == latest_id,
                }
                for row in entries
            ],
        }

    def get_history_entry(self, url: str, entry_id: int) -> Optional[Dict[str, Any]]:
        link_id = self._get_link_id(url)
        if not link_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, last_found
                FROM scraped_entries
                WHERE link_id = ? AND id = ?
                """,
                (link_id, entry_id),
            ).fetchone()
        return row

    def delete_history_entry(self, url: str, entry_id: int) -> bool:
        link_id = self._get_link_id(url)
        if not link_id:
            return False
        with self._connect() as conn:
            latest = conn.execute(
                """
                SELECT id
                FROM scraped_entries
                WHERE link_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (link_id,),
            ).fetchone()
            if latest and latest["id"] == entry_id:
                raise ValueError("Cannot delete the latest history entry")
            result = conn.execute(
                """
                DELETE FROM scraped_entries
                WHERE link_id = ? AND id = ?
                """,
                (link_id, entry_id),
            )
        return result.rowcount > 0

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
        favorite: Optional[bool] = None,
    ):
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if free_only is not None:
            updates.append("free_only = ?")
            params.append(self._to_flag(free_only))
        if favorite is not None:
            updates.append("favorite = ?")
            params.append(self._to_flag(favorite))
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

    def get_categories(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name,
                       update_interval_hours,
                       last_checked,
                       display_name,
                       include_in_nav
                FROM categories
                ORDER BY CASE name WHEN 'main' THEN 0 ELSE 1 END, name
                """
            ).fetchall()
        return [
            {
                "name": row["name"],
                "update_interval_hours": row["update_interval_hours"],
                "last_checked": row["last_checked"],
                "display_name": row["display_name"] or self._default_display_name(row["name"]),
                "include_in_nav": bool(row["include_in_nav"]),
            }
            for row in rows
        ]

    def get_category(self, name: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT name, update_interval_hours, last_checked, display_name, include_in_nav
                FROM categories
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
        if not row:
            return None
        return {
            "name": row["name"],
            "update_interval_hours": row["update_interval_hours"],
            "last_checked": row["last_checked"],
            "display_name": row["display_name"] or self._default_display_name(row["name"]),
            "include_in_nav": bool(row["include_in_nav"]),
        }

    def get_category_names(self) -> List[str]:
        return [cat["name"] for cat in self.get_categories()]

    def set_category_last_checked(self, name: str, timestamp: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE categories SET last_checked = ? WHERE name = ?",
                (timestamp, name),
            )

    def get_category_unsaved_counts(self) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    category,
                    SUM(
                        CASE
                            WHEN latest_last_found IS NOT NULL
                                 AND latest_last_found <> IFNULL(last_saved, '')
                            THEN 1
                            ELSE 0
                        END
                    ) AS unsaved
                FROM (
                    SELECT
                        l.category AS category,
                        l.last_saved AS last_saved,
                        (
                            SELECT last_found
                            FROM scraped_entries se
                            WHERE se.link_id = l.id
                            ORDER BY se.id DESC
                            LIMIT 1
                        ) AS latest_last_found
                    FROM links l
                ) data
                GROUP BY category
                """
            ).fetchall()
        return {row["category"]: row["unsaved"] or 0 for row in rows}

    def create_category(
        self,
        name: str,
        update_interval_hours: int = 1,
        display_name: Optional[str] = None,
        include_in_nav: bool = True,
    ) -> Dict[str, Any]:
        normalized = self._normalize_category(name)
        if not normalized:
            raise ValueError("Category name is required")
        display = (display_name or "").strip() or self._default_display_name(normalized)
        interval = self._sanitize_interval(update_interval_hours or 1)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO categories (name, update_interval_hours, display_name, include_in_nav)
                VALUES (?, ?, ?, ?)
                """,
                (normalized, interval, display, self._to_flag(include_in_nav)),
            )
        return self.get_category(normalized) or {}

    def update_category_entry(
        self,
        name: str,
        new_name: Optional[str] = None,
        update_interval_hours: Optional[int] = None,
        display_name: Optional[str] = None,
        include_in_nav: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        current = self.get_category(name)
        if not current:
            return None
        updates = []
        params: List[Any] = []
        normalized_new_name = self._normalize_category(new_name) if new_name else None
        if normalized_new_name and normalized_new_name != name:
            updates.append("name = ?")
            params.append(normalized_new_name)
        if update_interval_hours is not None:
            updates.append("update_interval_hours = ?")
            params.append(self._sanitize_interval(update_interval_hours))
        if display_name is not None:
            base_name = normalized_new_name or name
            cleaned = (display_name or "").strip() or self._default_display_name(base_name)
            updates.append("display_name = ?")
            params.append(cleaned)
        if include_in_nav is not None:
            updates.append("include_in_nav = ?")
            params.append(self._to_flag(include_in_nav))
        if not updates:
            return current

        with self._connect() as conn:
            conn.execute(
                f"UPDATE categories SET {', '.join(updates)} WHERE name = ?",
                (*params, name),
            )
            if normalized_new_name and normalized_new_name != name:
                conn.execute(
                    "UPDATE links SET category = ? WHERE category = ?",
                    (normalized_new_name, name),
                )
        target_name = normalized_new_name or name
        return self.get_category(target_name)

    def delete_category(self, name: str) -> bool:
        normalized = self._normalize_category(name)
        if normalized == "main":
            raise ValueError("Main category cannot be removed")
        with self._connect() as conn:
            conn.execute("DELETE FROM links WHERE category = ?", (normalized,))
            result = conn.execute(
                "DELETE FROM categories WHERE name = ?",
                (normalized,),
            )
        return result.rowcount > 0
