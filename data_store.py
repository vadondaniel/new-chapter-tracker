import json
from pathlib import Path
from typing import Callable, Generic, TypeVar

DEFAULT_UPDATE_FREQUENCY = 1  # days
DEFAULT_FREE_ONLY = True

T = TypeVar("T")


class JSONFileStore(Generic[T]):
    """Lightweight wrapper that caches one JSON file per instance."""

    def __init__(self, path: Path, default_factory: Callable[[], T]):
        self.path = path
        self.default_factory = default_factory
        self._cache = None

    def _ensure_file(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(
                json.dumps(self.default_factory(), indent=4), encoding="utf-8"
            )

    def load(self) -> T:
        if self._cache is None:
            self._ensure_file()
            text = self.path.read_text(encoding="utf-8").strip()
            self._cache = (
                json.loads(text) if text else self.default_factory()
            )
        return self._cache

    def save(self):
        self._ensure_file()
        if self._cache is None:
            self._cache = self.default_factory()
        self.path.write_text(json.dumps(self._cache, indent=4), encoding="utf-8")

    def reset(self):
        self._cache = None


class CategoryStorage:
    """Manages link and scraped-data files for one category."""

    def __init__(self, links_path: str, data_path: str):
        self.links_store = JSONFileStore(Path(links_path), list)
        self.data_store = JSONFileStore(Path(data_path), dict)

    # Links helpers
    def read_links(self):
        links = self.links_store.load()
        self._ensure_link_defaults(links)
        return links

    def save_links(self):
        self.links_store.save()

    # Scraped data helpers
    def read_data(self):
        return self.data_store.load()

    def save_data(self):
        self.data_store.save()

    def _ensure_link_defaults(self, links):
        for link in links:
            freq = link.get("update_frequency", DEFAULT_UPDATE_FREQUENCY)
            link["update_frequency"] = self._normalize_frequency(freq)
            link.setdefault("free_only", DEFAULT_FREE_ONLY)

    @staticmethod
    def _normalize_frequency(value):
        try:
            freq = float(value)
            return max(1, int(freq) if freq.is_integer() else int(freq) + 1)
        except (TypeError, ValueError):
            return DEFAULT_UPDATE_FREQUENCY

    def upsert_entry(self, url: str, name: str, last_found: str, timestamp: str, last_saved=None):
        data = self.read_data()
        entry = data.get(url, {})
        data[url] = {
            "name": name or entry.get("name", "Unknown"),
            "last_found": last_found,
            "timestamp": timestamp,
            "last_saved": last_saved or entry.get("last_saved", "N/A"),
        }
        self.save_data()

    def mark_as_saved(self, url: str):
        data = self.read_data()
        entry = data.get(url)
        if entry:
            entry["last_saved"] = entry["last_found"]
            self.save_data()

    def remove_entry(self, url: str):
        data = self.read_data()
        if url in data:
            del data[url]
            self.save_data()

    def merge_scraped(self, new_data):
        data = self.read_data()
        for url, entry in new_data.items():
            existing = data.get(url, {})
            data[url] = {
                "name": entry.get("name", existing.get("name", "Unknown")),
                "last_found": entry["last_found"],
                "timestamp": entry["timestamp"],
                "last_saved": existing.get("last_saved", "N/A"),
                "free_only": entry.get("free_only", existing.get("free_only", True)),
            }
        self.save_data()
