"""Track metadata cache for Apple Music MCP.

Caches stable track metadata (explicit status, ISRC) keyed by track IDs.
Supports three ID types:
- Persistent IDs (from AppleScript)
- Library IDs (from Apple Music API)
- Catalog IDs (universal, from Apple Music Catalog)

All three IDs may point to the same track. The cache stores metadata once
and indexes it by all known IDs for maximum hit rate.
"""

import json
from pathlib import Path
from typing import Optional


def get_cache_dir() -> Path:
    """Get cache directory."""
    cache_dir = Path.home() / ".cache" / "applemusic-mcp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


class TrackCache:
    """Cache for stable track metadata.

    Stores:
    - explicit: "Yes" | "No" (content rating)
    - isrc: International Standard Recording Code (stable track fingerprint)

    Designed to be easily extensible for additional stable fields.
    """

    def __init__(self):
        self.cache_file = get_cache_dir() / "track_cache.json"
        self._cache = self._load()

    def _load(self) -> dict:
        """Load cache from disk."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        """Save cache to disk."""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception:
            pass

    def get_explicit(self, track_id: str) -> Optional[str]:
        """Get cached explicit status by any ID type.

        Args:
            track_id: Persistent ID, Library ID, or Catalog ID

        Returns:
            "Yes", "No", or None if not cached
        """
        if track_id in self._cache:
            return self._cache[track_id].get("explicit")
        return None

    def set_track_metadata(
        self,
        explicit: str,
        persistent_id: Optional[str] = None,
        library_id: Optional[str] = None,
        catalog_id: Optional[str] = None,
        isrc: Optional[str] = None,
    ) -> None:
        """Cache track metadata by all known IDs.

        Stores metadata once and indexes by all provided IDs for maximum hit rate.

        Args:
            explicit: "Yes" or "No" (content rating)
            persistent_id: AppleScript persistent ID (optional)
            library_id: API library ID (optional)
            catalog_id: Universal catalog ID (optional)
            isrc: International Standard Recording Code (optional)
        """
        # Build metadata dict
        metadata = {"explicit": explicit}
        if isrc:
            metadata["isrc"] = isrc

        # Cache by all provided IDs
        ids_to_cache = [
            id for id in [persistent_id, library_id, catalog_id]
            if id
        ]

        for track_id in ids_to_cache:
            if track_id not in self._cache:
                self._cache[track_id] = metadata

        # Save to disk
        self._save()

    def clear(self) -> None:
        """Clear entire cache (for testing/maintenance)."""
        self._cache = {}
        self._save()


# Global cache instance
_track_cache = None


def get_track_cache() -> TrackCache:
    """Get the global track cache instance."""
    global _track_cache
    if _track_cache is None:
        _track_cache = TrackCache()
    return _track_cache
