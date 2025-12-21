"""MCP server for Apple Music - Cross-platform playlist and library management.

On macOS, additional AppleScript-powered tools are available for playback control,
deleting tracks from playlists, and other operations not supported by the REST API.
"""

import csv
import io
import json
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

from .auth import get_developer_token, get_user_token, get_config_dir
from . import applescript as asc

# Check if AppleScript is available (macOS only)
APPLESCRIPT_AVAILABLE = asc.is_available()

# Max characters for track listing output
MAX_OUTPUT_CHARS = 50000


def truncate(s: str, max_len: int) -> str:
    """Truncate string with ellipsis if longer than max_len."""
    return s[:max_len] + "..." if len(s) > max_len else s


def get_cache_dir() -> Path:
    """Get cache directory for CSV exports."""
    cache_dir = Path.home() / ".cache" / "applemusic-mcp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_timestamp() -> str:
    """Get timestamp for unique filenames (YYYYMMDD_HHMMSS)."""
    return time.strftime("%Y%m%d_%H%M%S")


def format_duration(ms: int | None) -> str:
    """Format milliseconds as m:ss (e.g., 3:45).

    Args:
        ms: Duration in milliseconds. Returns empty string for None, 0, or negative values.

    Returns:
        Formatted duration string like "3:45" or empty string for invalid input.
    """
    if not ms or ms <= 0:
        return ""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def extract_track_data(track: dict, include_extras: bool = False) -> dict:
    """Extract track data from API response into standardized dict.

    Args:
        track: Raw track dict from Apple Music API response.
        include_extras: If True, include additional metadata (track_number, artwork, etc.)

    Returns:
        Dict with standardized keys: name, duration, artist, album, year, genre, id.
        If include_extras=True, also includes: track_number, disc_number, has_lyrics,
        catalog_id, composer, isrc, is_explicit, preview_url, artwork_url.
    """
    attrs = track.get("attributes", {})
    play_params = attrs.get("playParams", {})
    genres = attrs.get("genreNames", [])
    release_date = attrs.get("releaseDate", "") or ""

    data = {
        "name": attrs.get("name", ""),
        "duration": format_duration(attrs.get("durationInMillis", 0)),
        "artist": attrs.get("artistName", ""),
        "album": attrs.get("albumName", ""),
        "year": release_date[:4] if release_date else "",
        "genre": genres[0] if genres else "",
        "id": track.get("id", ""),
    }

    if include_extras:
        previews = attrs.get("previews", [])
        data.update({
            "track_number": attrs.get("trackNumber", ""),
            "disc_number": attrs.get("discNumber", ""),
            "has_lyrics": attrs.get("hasLyrics", False),
            "catalog_id": play_params.get("catalogId", ""),
            "composer": attrs.get("composerName", ""),
            "isrc": attrs.get("isrc", ""),
            "is_explicit": attrs.get("contentRating") == "explicit",
            "preview_url": previews[0].get("url", "") if previews else "",
            "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
        })

    return data


def write_tracks_csv(track_data: list[dict], csv_path: Path, include_extras: bool = False) -> None:
    """Write track data to CSV file.

    Args:
        track_data: List of track dicts from extract_track_data().
        csv_path: Path to write CSV file.
        include_extras: If True, include additional metadata columns.
    """
    csv_fields = ["name", "duration", "artist", "album", "year", "genre", "id"]
    if include_extras:
        csv_fields += ["track_number", "disc_number", "has_lyrics", "catalog_id",
                       "composer", "isrc", "is_explicit", "preview_url", "artwork_url"]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(track_data)


def _format_full(t: dict) -> str:
    """Full format: Name - Artist (duration) Album [Year] Genre id"""
    year_str = f" [{t['year']}]" if t["year"] else ""
    genre_str = f" {t['genre']}" if t["genre"] else ""
    return f"{t['name']} - {t['artist']} ({t['duration']}) {t['album']}{year_str}{genre_str} {t['id']}"


def _format_clipped(t: dict) -> str:
    """Clipped format: Truncated Name - Artist (duration) Album [Year] Genre id"""
    year_str = f" [{t['year']}]" if t["year"] else ""
    genre_str = f" {t['genre']}" if t["genre"] else ""
    return f"{truncate(t['name'], 35)} - {truncate(t['artist'], 22)} ({t['duration']}) {truncate(t['album'], 30)}{year_str}{genre_str} {t['id']}"


def _format_compact(t: dict) -> str:
    """Compact format: Name - Artist (duration) id"""
    return f"{truncate(t['name'], 40)} - {truncate(t['artist'], 25)} ({t['duration']}) {t['id']}"


def _format_minimal(t: dict) -> str:
    """Minimal format: Name - Artist id"""
    return f"{truncate(t['name'], 30)} - {truncate(t['artist'], 20)} {t['id']}"


def format_track_list(track_data: list[dict]) -> tuple[list[str], str]:
    """Format track list with tiered display based on output size.

    Automatically selects the most detailed format that fits within MAX_OUTPUT_CHARS:
    - Full: Name - Artist (duration) Album [Year] Genre id
    - Clipped: Same as Full but with truncated Name/Artist/Album
    - Compact: Truncated Name - Artist (duration) id
    - Minimal: Truncated Name - Artist id

    Args:
        track_data: List of track dicts from extract_track_data().

    Returns:
        Tuple of (list of formatted strings, tier_name) where tier_name is
        "Full", "Clipped", "Compact", or "Minimal".
    """
    if not track_data:
        return [], "Full"

    def char_count(lines: list[str]) -> int:
        return sum(len(line) for line in lines) + max(0, len(lines) - 1)

    # Try full format first
    full_output = [_format_full(t) for t in track_data]
    if char_count(full_output) <= MAX_OUTPUT_CHARS:
        return full_output, "Full"

    # Try clipped (truncated but keeps all fields)
    clipped_output = [_format_clipped(t) for t in track_data]
    if char_count(clipped_output) <= MAX_OUTPUT_CHARS:
        return clipped_output, "Clipped"

    # Fall back to compact (drops album/year/genre)
    compact_output = [_format_compact(t) for t in track_data]
    if char_count(compact_output) <= MAX_OUTPUT_CHARS:
        return compact_output, "Compact"

    # Fall back to minimal
    return [_format_minimal(t) for t in track_data], "Minimal"


def format_output(
    items: list[dict],
    format: str = "text",
    export: str = "none",
    full: bool = False,
    file_prefix: str = "export",
) -> str:
    """Format output with optional file export.

    Args:
        items: List of item dicts (tracks, albums, etc.)
        format: "text" for human-readable, "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports (extras like artwork, track numbers)
        file_prefix: Prefix for export filename

    Returns:
        Formatted string (text or JSON) with optional file path info
    """
    if not items:
        return "No results" if format != "json" else "[]"

    result_parts = []

    # Build response content (skip if format="none")
    if format == "json":
        # JSON response - include standard fields, optionally extras
        if full:
            result_parts.append(json.dumps(items, indent=2))
        else:
            # Filter to standard fields only
            standard_keys = {"name", "duration", "artist", "album", "year", "genre", "id",
                           "track_count", "release_date"}
            filtered = [{k: v for k, v in item.items() if k in standard_keys} for item in items]
            result_parts.append(json.dumps(filtered, indent=2))
    elif format == "csv":
        # CSV response inline
        output = io.StringIO()
        if items and "duration" in items[0]:
            csv_fields = ["name", "duration", "artist", "album", "year", "genre", "id"]
            if full:
                csv_fields += ["track_number", "disc_number", "has_lyrics", "catalog_id",
                               "composer", "isrc", "is_explicit", "preview_url", "artwork_url"]
        else:
            csv_fields = list(items[0].keys()) if items else []
        writer = csv.DictWriter(output, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(items)
        result_parts.append(output.getvalue())
    elif format == "text":
        # Text response - use tiered formatting for tracks
        if items and "duration" in items[0]:
            # Track data - use tiered format
            formatted_lines, tier = format_track_list(items)
            result_parts.append(f"=== {len(items)} items ({tier} format) ===\n")
            result_parts.append("\n".join(formatted_lines))
        else:
            # Non-track data (albums, artists) - simple format
            result_parts.append(f"=== {len(items)} items ===\n")
            for item in items[:200]:
                if "artist" in item and "name" in item:
                    result_parts.append(f"{item['name']} - {item.get('artist', '')} {item.get('id', '')}")
                elif "name" in item:
                    result_parts.append(f"{item['name']} {item.get('id', '')}")
    # format="none" - skip response body, only show export info

    # Handle file export
    if export in ("csv", "json"):
        cache_dir = get_cache_dir()
        timestamp = get_timestamp()

        if export == "csv":
            file_path = cache_dir / f"{file_prefix}_{timestamp}.csv"
            # Determine fields based on full flag
            if items and "duration" in items[0]:
                csv_fields = ["name", "duration", "artist", "album", "year", "genre", "id"]
                if full:
                    csv_fields += ["track_number", "disc_number", "has_lyrics", "catalog_id",
                                   "composer", "isrc", "is_explicit", "preview_url", "artwork_url"]
            else:
                csv_fields = list(items[0].keys()) if items else []

            with open(file_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(items)
        else:  # json
            file_path = cache_dir / f"{file_prefix}_{timestamp}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(items if full else [{k: v for k, v in item.items()
                         if k in {"name", "duration", "artist", "album", "year", "genre", "id",
                                  "track_count", "release_date"}} for item in items], f, indent=2)

        result_parts.append(f"Exported {len(items)} items: {file_path}")
        result_parts.append(f"Resource: exports://{file_path.name}")

    if not result_parts:
        return f"{len(items)} items (use export='csv' or 'json' to save)"

    return "\n".join(result_parts)


BASE_URL = "https://api.music.apple.com/v1"
STOREFRONT = "us"

mcp = FastMCP("AppleMusicAPI")


# ============ MCP RESOURCES ============


@mcp.resource("exports://list")
def list_exports() -> str:
    """List all exported files in the cache directory."""
    cache_dir = get_cache_dir()
    files = sorted(cache_dir.glob("*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return "No exports found"
    return "\n".join(f"{f.name} ({f.stat().st_size} bytes)" for f in files[:50])


@mcp.resource("exports://{filename}")
def read_export(filename: str) -> str:
    """Read an exported file from the cache directory."""
    cache_dir = get_cache_dir()
    file_path = cache_dir / filename
    if not file_path.exists():
        return f"File not found: {filename}"
    if not file_path.is_relative_to(cache_dir):
        return "Invalid path"
    return file_path.read_text(encoding="utf-8")


def get_token_expiration_warning() -> str | None:
    """Check if developer token expires within 30 days. Returns warning message or None."""
    config_dir = get_config_dir()
    token_file = config_dir / "developer_token.json"

    if not token_file.exists():
        return None

    try:
        with open(token_file) as f:
            data = json.load(f)

        expires = data.get("expires", 0)
        days_left = (expires - time.time()) / 86400

        if days_left < 30:
            return f"⚠️ Developer token expires in {int(days_left)} days. Run: applemusic-mcp generate-token"
    except Exception:
        pass

    return None


def get_headers() -> dict:
    """Get headers for API requests."""
    return {
        "Authorization": f"Bearer {get_developer_token()}",
        "Music-User-Token": get_user_token(),
        "Content-Type": "application/json",
    }


# ============ INTERNAL HELPERS ============


def _search_catalog_songs(query: str, limit: int = 5) -> list[dict]:
    """Search catalog for songs and return raw song data.

    Args:
        query: Search term
        limit: Max results (default 5)

    Returns:
        List of song dicts with 'id', 'attributes' (name, artistName, etc.)
        Empty list on error.
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/search",
            headers=headers,
            params={"term": query, "types": "songs", "limit": min(limit, 25)},
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("results", {}).get("songs", {}).get("data", [])
    except Exception:
        pass
    return []


def _add_songs_to_library(catalog_ids: list[str]) -> tuple[bool, str]:
    """Add songs to library by catalog ID.

    Args:
        catalog_ids: List of catalog song IDs

    Returns:
        Tuple of (success, message)
    """
    if not catalog_ids:
        return False, "No catalog IDs provided"

    try:
        headers = get_headers()
        response = requests.post(
            f"{BASE_URL}/me/library",
            headers=headers,
            params={"ids[songs]": ",".join(catalog_ids)},
        )
        if response.status_code in (200, 201, 202, 204):
            return True, f"Added {len(catalog_ids)} song(s) to library"
        return False, f"API returned status {response.status_code}"
    except Exception as e:
        return False, str(e)


def _rate_song_api(song_id: str, rating: str) -> tuple[bool, str]:
    """Rate a song via API.

    Args:
        song_id: Catalog song ID
        rating: 'love' or 'dislike'

    Returns:
        Tuple of (success, message)
    """
    rating_value = {"love": 1, "dislike": -1}.get(rating.lower())
    if rating_value is None:
        return False, "rating must be 'love' or 'dislike'"

    try:
        headers = get_headers()
        body = {"type": "rating", "attributes": {"value": rating_value}}
        response = requests.put(
            f"{BASE_URL}/me/ratings/songs/{song_id}",
            headers=headers,
            json=body,
        )
        if response.status_code in (200, 201, 204):
            return True, f"Marked as {rating}"
        return False, f"API returned status {response.status_code}"
    except Exception as e:
        return False, str(e)


# ============ PLAYLIST MANAGEMENT ============


@mcp.tool()
def get_library_playlists(
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Get all playlists from your Apple Music library.

    Args:
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports

    Returns: Playlist listing in requested format
    """
    try:
        headers = get_headers()
        all_playlists = []
        offset = 0

        # Paginate to get all playlists
        while True:
            response = requests.get(
                f"{BASE_URL}/me/library/playlists",
                headers=headers,
                params={"limit": 100, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            playlists = response.json().get("data", [])
            if not playlists:
                break
            all_playlists.extend(playlists)
            if len(playlists) < 100:
                break
            offset += 100

        # Extract playlist data
        playlist_data = []
        for playlist in all_playlists:
            attrs = playlist.get("attributes", {})
            desc = attrs.get("description", {})

            playlist_data.append({
                "id": playlist.get("id", ""),
                "name": attrs.get("name", "Unknown"),
                "can_edit": attrs.get("canEdit", False),
                "is_public": attrs.get("isPublic", False),
                "date_added": attrs.get("dateAdded", ""),
                "last_modified": attrs.get("lastModifiedDate", ""),
                "description": desc.get("standard", "") if isinstance(desc, dict) else str(desc),
                "has_catalog": attrs.get("hasCatalog", False),
            })

        # Add token warning if text format
        warning = get_token_expiration_warning()
        prefix = f"{warning}\n\n" if warning and format == "text" else ""

        return prefix + format_output(playlist_data, format, export, full, "playlists")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_playlist_tracks(
    playlist_id: str = "",
    playlist_name: str = "",
    filter: str = "",
    limit: int = 0,
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Get tracks in a playlist.

    Provide EITHER playlist_id (API) OR playlist_name (AppleScript, macOS only).

    Args:
        playlist_id: Playlist ID (from get_library_playlists)
        playlist_name: Playlist name (macOS only, uses AppleScript)
        filter: Filter tracks by name/artist (case-insensitive substring match)
        limit: Max tracks to return (0 = all). Use with large playlists.
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports

    Returns: Track listing in requested format
    """
    use_api = bool(playlist_id)
    use_applescript = bool(playlist_name)

    if use_api and use_applescript:
        return "Error: Provide either playlist_id or playlist_name, not both"

    if not use_api and not use_applescript:
        return "Error: Provide playlist_id or playlist_name"

    # Use AppleScript with name
    if use_applescript:
        if not APPLESCRIPT_AVAILABLE:
            return "Error: AppleScript (playlist_name) requires macOS"
        success, result = asc.get_playlist_tracks(playlist_name)
        if not success:
            return f"Error: {result}"
        if not result:
            return "Playlist is empty"

        # Format AppleScript results
        track_data = []
        for t in result:
            track_data.append({
                "name": t.get("name", "Unknown"),
                "artist": t.get("artist", "Unknown"),
                "album": t.get("album", ""),
                "duration": t.get("duration", "0:00"),
                "genre": t.get("genre", ""),
                "year": t.get("year", ""),
                "id": t.get("id", ""),
            })

        # Apply filter
        if filter:
            filter_lower = filter.lower()
            track_data = [
                t for t in track_data
                if filter_lower in t["name"].lower() or filter_lower in t["artist"].lower()
            ]

        # Apply limit
        if limit > 0:
            track_data = track_data[:limit]

        safe_name = "".join(c if c.isalnum() else "_" for c in playlist_name)
        return format_output(track_data, format, export, full, f"playlist_{safe_name}")

    # Use API with ID
    try:
        headers = get_headers()
        all_tracks = []
        offset = 0

        while True:
            response = requests.get(
                f"{BASE_URL}/me/library/playlists/{playlist_id}/tracks",
                headers=headers,
                params={"limit": 100, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)
            if len(tracks) < 100:
                break
            offset += 100

        if not all_tracks:
            return "Playlist is empty"

        track_data = [extract_track_data(t, full) for t in all_tracks]

        # Apply filter
        if filter:
            filter_lower = filter.lower()
            track_data = [
                t for t in track_data
                if filter_lower in t["name"].lower() or filter_lower in t["artist"].lower()
            ]

        # Apply limit
        if limit > 0:
            track_data = track_data[:limit]

        safe_id = playlist_id.replace('.', '_')
        return format_output(track_data, format, export, full, f"playlist_{safe_id}")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def check_playlist(
    search: str,
    playlist_id: str = "",
    playlist_name: str = "",
) -> str:
    """
    Quick check if a song or artist is in a playlist.

    Provide EITHER playlist_id (API) OR playlist_name (AppleScript, macOS only).

    Args:
        search: Song name or artist to search for
        playlist_id: Playlist ID (from get_library_playlists)
        playlist_name: Playlist name (macOS only, uses AppleScript)

    Returns: Summary of matches or "No matches"
    """
    use_api = bool(playlist_id)
    use_applescript = bool(playlist_name)

    if use_api and use_applescript:
        return "Error: Provide either playlist_id or playlist_name, not both"
    if not use_api and not use_applescript:
        return "Error: Provide playlist_id or playlist_name"

    search_lower = search.lower()
    matches = []

    if use_applescript:
        if not APPLESCRIPT_AVAILABLE:
            return "Error: playlist_name requires macOS"
        success, tracks = asc.get_playlist_tracks(playlist_name)
        if not success:
            return f"Error: {tracks}"
        for t in tracks:
            name = t.get("name", "")
            artist = t.get("artist", "")
            if search_lower in name.lower() or search_lower in artist.lower():
                matches.append(f"{name} by {artist}")
    else:
        success, tracks = _get_playlist_track_names(playlist_id)
        if not success:
            return f"Error: {tracks}"
        for t in tracks:
            name = t.get("name", "")
            artist = t.get("artist", "")
            if search_lower in name.lower() or search_lower in artist.lower():
                matches.append(f"{name} by {artist}")

    if not matches:
        return f"No matches for '{search}'"

    if len(matches) == 1:
        return f"Found: {matches[0]}"

    result = f"Found {len(matches)} matches:\n"
    result += "\n".join(f"  - {m}" for m in matches[:10])
    if len(matches) > 10:
        result += f"\n  ...and {len(matches) - 10} more"
    return result


def _is_catalog_id(track_id: str) -> bool:
    """Check if an ID is a catalog ID (numeric) vs library ID (hex/prefixed)."""
    return track_id.isdigit()


def _get_playlist_track_names(playlist_id: str) -> tuple[bool, list[dict] | str]:
    """Get track names from a playlist for duplicate checking."""
    try:
        headers = get_headers()
        all_tracks = []
        offset = 0

        while True:
            response = requests.get(
                f"{BASE_URL}/me/library/playlists/{playlist_id}/tracks",
                headers=headers,
                params={"limit": 100, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)
            if len(tracks) < 100:
                break
            offset += 100

        return True, [
            {
                "name": t.get("attributes", {}).get("name", ""),
                "artist": t.get("attributes", {}).get("artistName", ""),
            }
            for t in all_tracks
        ]
    except Exception as e:
        return False, str(e)


def _find_track_in_list(
    tracks: list[dict], track_name: str, artist: str = ""
) -> list[str]:
    """Find matching tracks in a list by name/artist."""
    track_lower = track_name.lower()
    artist_lower = artist.lower() if artist else ""
    matches = []

    for t in tracks:
        if track_lower in t["name"].lower():
            if artist_lower:
                if artist_lower in t["artist"].lower():
                    matches.append(f"{t['name']} - {t['artist']}")
            else:
                matches.append(f"{t['name']} - {t['artist']}")

    return matches


@mcp.tool()
def create_playlist(name: str, description: str = "") -> str:
    """
    Create a new playlist in your Apple Music library.
    Playlists created via API are editable via API.

    Args:
        name: Name for the new playlist
        description: Optional description

    Returns: The new playlist ID
    """
    try:
        headers = get_headers()

        body = {"attributes": {"name": name, "description": description}}

        response = requests.post(
            f"{BASE_URL}/me/library/playlists", headers=headers, json=body
        )
        response.raise_for_status()
        data = response.json()

        playlist_id = data.get("data", [{}])[0].get("id")
        return f"Created playlist '{name}' (ID: {playlist_id})"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def add_to_playlist(
    playlist_id: str = "",
    track_ids: str = "",
    playlist_name: str = "",
    track_name: str = "",
    artist: str = "",
    allow_duplicates: bool = False,
    verify: bool = True,
) -> str:
    """
    Add songs to a playlist with smart handling.

    Automatically:
    - Adds catalog songs to library first if needed
    - Checks for duplicates (skips by default)
    - Optionally verifies the add succeeded
    - Works with ANY playlist on macOS via AppleScript

    MODE 1 - By playlist ID (cross-platform, API-editable playlists only):
        add_to_playlist(playlist_id="p.ABC123", track_ids="1440783617")  # catalog ID
        add_to_playlist(playlist_id="p.ABC123", track_ids="i.XYZ789")    # library ID

    MODE 2 - By playlist name (macOS only, works on ANY playlist):
        add_to_playlist(playlist_name="Road Trip", track_name="Hey Jude", artist="The Beatles")
        add_to_playlist(playlist_name="Road Trip", track_ids="1440783617")  # also works!

    Args:
        playlist_id: Playlist ID (from get_library_playlists) - API mode
        track_ids: Track IDs - catalog (numeric) or library IDs
        playlist_name: Playlist name (macOS only, uses AppleScript)
        track_name: Track name (macOS only, for name-based matching)
        artist: Artist name (optional, helps with matching)
        allow_duplicates: If False (default), skip tracks already in playlist
        verify: If True, verify track was added (slower but confirms success)

    Returns: Detailed result of what happened
    """
    steps = []  # Track what we did for verbose output

    # Determine which mode - more flexible now
    has_playlist_id = bool(playlist_id)
    has_playlist_name = bool(playlist_name)
    has_track_ids = bool(track_ids)
    has_track_name = bool(track_name)

    # Validate combinations
    if has_playlist_id and has_playlist_name:
        return "Error: Provide either playlist_id or playlist_name, not both"

    if not has_playlist_id and not has_playlist_name:
        return "Error: Provide playlist_id or playlist_name"

    if not has_track_ids and not has_track_name:
        return "Error: Provide track_ids or track_name"

    # === AppleScript mode (playlist by name) ===
    if has_playlist_name:
        if not APPLESCRIPT_AVAILABLE:
            return "Error: playlist_name requires macOS (use playlist_id for cross-platform)"

        # If we have track_ids but not track_name, look up track info first
        if has_track_ids and not has_track_name:
            headers = get_headers()
            ids = [s.strip() for s in track_ids.split(",") if s.strip()]
            results = []

            for track_id in ids:
                # Get track info from catalog or library
                if _is_catalog_id(track_id):
                    # Add to library first
                    steps.append(f"Adding catalog ID {track_id} to library...")
                    params = {"ids[songs]": track_id}
                    requests.post(f"{BASE_URL}/me/library", headers=headers, params=params)

                    # Get catalog info
                    response = requests.get(
                        f"{BASE_URL}/catalog/us/songs/{track_id}", headers=headers
                    )
                    if response.status_code != 200:
                        steps.append(f"  Error: Could not get info for {track_id}")
                        continue
                    data = response.json().get("data", [])
                    if not data:
                        continue
                    attrs = data[0].get("attributes", {})
                    name = attrs.get("name", "")
                    artist_name = attrs.get("artistName", "")
                else:
                    # Library ID - look up info
                    response = requests.get(
                        f"{BASE_URL}/me/library/songs/{track_id}", headers=headers
                    )
                    if response.status_code != 200:
                        steps.append(f"Error: Could not get info for {track_id}")
                        continue
                    data = response.json().get("data", [])
                    if not data:
                        continue
                    attrs = data[0].get("attributes", {})
                    name = attrs.get("name", "")
                    artist_name = attrs.get("artistName", "")

                if not name:
                    steps.append(f"  Error: No name found for {track_id}")
                    continue

                # Wait a moment for library sync if it was a catalog ID
                if _is_catalog_id(track_id):
                    time.sleep(0.5)

                # Add via AppleScript
                success, result = asc.add_track_to_playlist(
                    playlist_name, name, artist_name if artist_name else None
                )
                if success:
                    steps.append(f"Added: {name} - {artist_name}")
                    results.append(True)
                else:
                    steps.append(f"Failed to add {name}: {result}")
                    results.append(False)

            if not results:
                return "Error: No tracks could be added\n" + "\n".join(steps)
            return "\n".join(steps)

        # track_name mode (original AppleScript behavior)
        # Quick duplicate check
        if not allow_duplicates:
            success, exists = asc.track_exists_in_playlist(
                playlist_name, track_name, artist if artist else None
            )
            if success and exists:
                return f"Skipped: '{track_name}' already in playlist\n  Found: {exists}"

        # Add the track
        success, result = asc.add_track_to_playlist(
            playlist_name, track_name, artist if artist else None
        )
        if not success:
            return f"Error: {result}"
        steps.append(result)

        # Quick verify with polling
        if verify:
            for _ in range(5):  # Try up to 5 times (0.5s total)
                success, exists = asc.track_exists_in_playlist(
                    playlist_name, track_name, artist if artist else None
                )
                if success and exists:
                    steps.append(f"Verified: {exists}")
                    break
                time.sleep(0.1)
            else:
                steps.append("Warning: could not verify add")

        return "\n".join(steps)

    # === API mode (playlist by ID) ===
    try:
        headers = get_headers()
        ids = [s.strip() for s in track_ids.split(",") if s.strip()]
        if not ids:
            return "Error: No track IDs provided"

        library_ids = []
        track_info = {}  # For verbose output

        # Process each ID - add to library if catalog ID
        for track_id in ids:
            if _is_catalog_id(track_id):
                # It's a catalog ID - need to add to library first
                steps.append(f"Adding catalog ID {track_id} to library...")

                # Add to library
                params = {"ids[songs]": track_id}
                response = requests.post(
                    f"{BASE_URL}/me/library", headers=headers, params=params
                )
                if response.status_code not in (200, 202):
                    steps.append(f"  Warning: library add returned {response.status_code}")

                # Get catalog info for the track name
                cat_response = requests.get(
                    f"{BASE_URL}/catalog/us/songs/{track_id}",
                    headers=headers,
                )
                if cat_response.status_code == 200:
                    cat_data = cat_response.json().get("data", [])
                    if cat_data:
                        attrs = cat_data[0].get("attributes", {})
                        name = attrs.get("name", "")
                        artist_name = attrs.get("artistName", "")
                        track_info[track_id] = f"{name} - {artist_name}"

                        # Poll library until track appears (up to 1s)
                        found_id = None
                        for attempt in range(10):
                            if attempt > 0:
                                time.sleep(0.1)
                            lib_response = requests.get(
                                f"{BASE_URL}/me/library/search",
                                headers=headers,
                                params={"term": name, "types": "library-songs", "limit": 25},
                            )
                            if lib_response.status_code == 200:
                                lib_data = lib_response.json()
                                songs = lib_data.get("results", {}).get("library-songs", {}).get("data", [])
                                for song in songs:
                                    song_attrs = song.get("attributes", {})
                                    if (song_attrs.get("name", "").lower() == name.lower() and
                                        artist_name.lower() in song_attrs.get("artistName", "").lower()):
                                        found_id = song["id"]
                                        break
                                if found_id:
                                    break
                        if found_id:
                            library_ids.append(found_id)
                            steps.append(f"  Found in library: {name} (ID: {found_id})")
                        else:
                            steps.append(f"  Warning: could not find '{name}' in library after adding")
                else:
                    steps.append(f"  Warning: could not get catalog info for {track_id}")
            else:
                # Already a library ID
                library_ids.append(track_id)

        if not library_ids:
            return "Error: No valid library IDs to add\n" + "\n".join(steps)

        # Check for duplicates
        if not allow_duplicates:
            success, existing = _get_playlist_track_names(playlist_id)
            if success and existing:
                filtered_ids = []
                for lib_id in library_ids:
                    # Get track name for this library ID
                    response = requests.get(
                        f"{BASE_URL}/me/library/songs/{lib_id}",
                        headers=headers,
                    )
                    if response.status_code == 200:
                        data = response.json().get("data", [])
                        if data:
                            attrs = data[0].get("attributes", {})
                            name = attrs.get("name", "")
                            artist_name = attrs.get("artistName", "")
                            matches = _find_track_in_list(existing, name, artist_name)
                            if matches:
                                steps.append(f"Skipped duplicate: {name} - {artist_name}")
                                continue
                    filtered_ids.append(lib_id)
                library_ids = filtered_ids

        if not library_ids:
            steps.append("All tracks already in playlist")
            return "\n".join(steps)

        # Add to playlist
        track_data = [{"id": lid, "type": "library-songs"} for lid in library_ids]
        body = {"data": track_data}

        response = requests.post(
            f"{BASE_URL}/me/library/playlists/{playlist_id}/tracks",
            headers=headers,
            json=body,
        )

        if response.status_code == 204:
            steps.append(f"Added {len(library_ids)} track(s) to playlist")
        elif response.status_code == 403:
            return "Error: Cannot edit this playlist (not API-created). Use playlist_name on macOS.\n" + "\n".join(steps)
        elif response.status_code == 500:
            return "Error: Cannot edit this playlist (not API-created). Use playlist_name on macOS.\n" + "\n".join(steps)
        else:
            response.raise_for_status()

        # Verify
        success, updated = _get_playlist_track_names(playlist_id)
        if success:
            steps.append(f"Verified: playlist now has {len(updated)} tracks")

        return "\n".join(steps)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}\n" + "\n".join(steps)
    except (FileNotFoundError, ValueError) as e:
        return f"Error: {str(e)}\n" + "\n".join(steps)


@mcp.tool()
def copy_playlist(source_playlist_id: str, new_name: str) -> str:
    """
    Copy a playlist to a new API-editable playlist.
    Use this to make an editable copy of a read-only playlist.

    Args:
        source_playlist_id: ID of the playlist to copy
        new_name: Name for the new playlist

    Returns: New playlist ID or error
    """
    try:
        headers = get_headers()

        # Get source playlist tracks
        all_tracks = []
        offset = 0
        while True:
            response = requests.get(
                f"{BASE_URL}/me/library/playlists/{source_playlist_id}/tracks",
                headers=headers,
                params={"limit": 100, "offset": offset},
            )
            if response.status_code == 404:
                break  # End of pagination or empty
            response.raise_for_status()
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)
            if len(tracks) < 100:
                break  # Last page
            offset += 100

        # Create new playlist
        body = {"attributes": {"name": new_name}}
        response = requests.post(
            f"{BASE_URL}/me/library/playlists", headers=headers, json=body
        )
        response.raise_for_status()
        new_id = response.json()["data"][0]["id"]

        # Add tracks in batches
        batch_size = 25
        for i in range(0, len(all_tracks), batch_size):
            batch = all_tracks[i : i + batch_size]
            track_data = [{"id": t["id"], "type": "library-songs"} for t in batch]
            requests.post(
                f"{BASE_URL}/me/library/playlists/{new_id}/tracks",
                headers=headers,
                json={"data": track_data},
            )

        return f"Created '{new_name}' (ID: {new_id}) with {len(all_tracks)} tracks"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ LIBRARY MANAGEMENT ============


@mcp.tool()
def search_library(
    query: str,
    search_type: str = "songs",
    limit: int = 25,
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Search your personal Apple Music library.

    On macOS, uses AppleScript for fast local search. Falls back to API elsewhere.

    Args:
        query: Search term
        search_type: Type of search - songs, artists, albums, or all (macOS only)
        limit: Max results (default 25, up to 100 on macOS)
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports (artwork, track numbers, etc.)

    Returns: Library items with IDs (library IDs can be added to playlists)
    """
    # Try AppleScript on macOS (faster for local searches)
    if APPLESCRIPT_AVAILABLE:
        success, results = asc.search_library(query, search_type)
        if success and results:
            return format_output(results, format, export, full, f"search_{query[:20]}")
        # AppleScript found nothing or failed - fall through to API

    # API fallback (or primary on non-macOS)
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/library/search",
            headers=headers,
            params={"term": query, "types": "library-songs", "limit": min(limit, 25)},
        )
        response.raise_for_status()
        data = response.json()

        songs = data.get("results", {}).get("library-songs", {}).get("data", [])
        if not songs:
            return "No songs found"

        song_data = [extract_track_data(s, full) for s in songs]
        return format_output(song_data, format, export, full, f"search_{query[:20]}")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def add_to_library(catalog_ids: str) -> str:
    """
    Add songs from the Apple Music catalog to your personal library.
    After adding, use search_library to find the library IDs for playlist operations.

    Args:
        catalog_ids: Comma-separated catalog song IDs (from search_catalog)

    Returns: Confirmation or error message
    """
    ids = [s.strip() for s in catalog_ids.split(",") if s.strip()]
    if not ids:
        return "No catalog IDs provided"

    success, msg = _add_songs_to_library(ids)
    if success:
        return f"Successfully added {len(ids)} song(s) to your library. Use search_library to find their library IDs."
    return f"API Error: {msg}"


@mcp.tool()
def get_recently_played(
    limit: int = 30,
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Get recently played tracks from your Apple Music history.

    Args:
        limit: Number of tracks to return (default 30, max 50)
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports

    Returns: Recently played tracks in requested format
    """
    try:
        headers = get_headers()
        all_tracks = []
        max_limit = min(limit, 50)

        # API limits to 10 per request, paginate up to max
        for offset in range(0, max_limit, 10):
            batch_limit = min(10, max_limit - offset)
            response = requests.get(
                f"{BASE_URL}/me/recent/played/tracks",
                headers=headers,
                params={"limit": batch_limit, "offset": offset},
            )
            if response.status_code != 200:
                break
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)

        if not all_tracks:
            return "No recently played tracks"

        track_data = [extract_track_data(t, full) for t in all_tracks]
        return format_output(track_data, format, export, full, "recently_played")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ CATALOG SEARCH ============


@mcp.tool()
def search_catalog(
    query: str,
    types: str = "songs",
    limit: int = 15,
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Search the Apple Music catalog.

    Args:
        query: Search term
        types: Comma-separated types (songs, albums, artists, playlists)
        limit: Max results per type (default 15)
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file (songs only)
        full: Include all metadata in exports

    Returns: Search results with catalog IDs (use add_to_library to add songs)
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/search",
            headers=headers,
            params={"term": query, "types": types, "limit": min(limit, 25)},
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", {})

        # Collect all data for JSON format
        all_data = {"songs": [], "albums": [], "artists": [], "playlists": []}

        if "songs" in results:
            all_data["songs"] = [extract_track_data(s, full) for s in results["songs"].get("data", [])]

        if "albums" in results:
            for album in results["albums"].get("data", []):
                attrs = album.get("attributes", {})
                all_data["albums"].append({
                    "id": album.get("id"), "name": attrs.get("name"),
                    "artist": attrs.get("artistName"), "track_count": attrs.get("trackCount", 0),
                    "year": attrs.get("releaseDate", "")[:4],
                })

        if "artists" in results:
            for artist in results["artists"].get("data", []):
                attrs = artist.get("attributes", {})
                all_data["artists"].append({
                    "id": artist.get("id"), "name": attrs.get("name"),
                    "genres": attrs.get("genreNames", []),
                })

        if "playlists" in results:
            for pl in results["playlists"].get("data", []):
                attrs = pl.get("attributes", {})
                all_data["playlists"].append({
                    "id": pl.get("id"), "name": attrs.get("name"),
                    "curator": attrs.get("curatorName", ""),
                })

        # Handle export (songs only)
        export_msg = ""
        if export and all_data["songs"]:
            export_msg = "\n" + format_output(all_data["songs"], "text", export, full, f"catalog_{query[:20]}").split("\n")[-1]

        # JSON format - return all data
        if format == "json":
            return json.dumps(all_data, indent=2) + export_msg

        # Text format
        output = []
        if all_data["songs"]:
            output.append(f"=== {len(all_data['songs'])} Songs ===")
            for s in all_data["songs"]:
                output.append(f"{s['name']} - {s['artist']} ({s['duration']}) {s['album']} [{s['year']}] {s['id']}")

        if all_data["albums"]:
            output.append(f"\n=== {len(all_data['albums'])} Albums ===")
            for a in all_data["albums"]:
                output.append(f"  {a['name']} - {a['artist']} ({a['track_count']} tracks) [{a['year']}] {a['id']}")

        if all_data["artists"]:
            output.append(f"\n=== {len(all_data['artists'])} Artists ===")
            for a in all_data["artists"]:
                output.append(f"  {a['name']} {a['id']}")

        if all_data["playlists"]:
            output.append(f"\n=== {len(all_data['playlists'])} Playlists ===")
            for p in all_data["playlists"]:
                output.append(f"  {p['name']} {p['id']}")

        return ("\n".join(output) + export_msg) if output else "No results found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_album_tracks(
    album_id: str,
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Get all tracks from an album.
    Works with both library album IDs (l.xxx) and catalog album IDs (numeric).

    Args:
        album_id: Library album ID (l.xxx) or catalog album ID (numeric)
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports (composer, artwork, etc.)

    Returns: Track listing in requested format
    """
    try:
        headers = get_headers()

        # Detect if it's a library or catalog ID
        if album_id.startswith("l."):
            base_url = f"{BASE_URL}/me/library/albums/{album_id}/tracks"
        else:
            base_url = f"{BASE_URL}/catalog/{STOREFRONT}/albums/{album_id}/tracks"

        # Paginate to handle box sets / compilations with 100+ tracks
        all_tracks = []
        offset = 0

        while True:
            response = requests.get(
                base_url,
                headers=headers,
                params={"limit": 100, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)
            if len(tracks) < 100:
                break
            offset += 100

        if not all_tracks:
            return "No tracks found"

        # Extract track data with extras for numbered display
        track_data = [extract_track_data(t, include_extras=True) for t in all_tracks]

        return format_output(track_data, format, export, full, f"album_{album_id.replace('.', '_')}")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ LIBRARY BROWSING ============


@mcp.tool()
def browse_library(
    item_type: str = "songs",
    limit: int = 100,
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Browse your Apple Music library by type.

    Args:
        item_type: What to browse - songs, albums, artists, or videos
        limit: Max items (default 100, use 0 for all). Only applies to songs.
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports

    Returns: Item listing in requested format
    """
    try:
        headers = get_headers()
        item_type = item_type.lower().strip()

        # Map type to API endpoint
        type_map = {
            "songs": "library-songs",
            "albums": "library/albums",
            "artists": "library/artists",
            "videos": "library/music-videos",
        }
        if item_type not in type_map:
            return f"Invalid type: {item_type}. Use: songs, albums, artists, or videos"

        endpoint = type_map[item_type]
        all_items = []
        offset = 0
        fetch_all = limit == 0 or item_type != "songs"
        max_to_fetch = limit if not fetch_all else float('inf')

        # Paginate
        while len(all_items) < max_to_fetch:
            batch_limit = 100 if fetch_all else min(100, int(max_to_fetch - len(all_items)))
            url = f"{BASE_URL}/me/{endpoint}" if "/" in endpoint else f"{BASE_URL}/me/library/songs"
            response = requests.get(
                url,
                headers=headers,
                params={"limit": batch_limit, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            items = response.json().get("data", [])
            if not items:
                break
            all_items.extend(items)
            if len(items) < 100:
                break
            offset += 100

        if not all_items:
            return f"No {item_type} in library"

        # Extract data based on type
        if item_type == "songs":
            data = [extract_track_data(s, full) for s in all_items]
        elif item_type == "albums":
            data = []
            for album in all_items:
                attrs = album.get("attributes", {})
                genres = attrs.get("genreNames", [])
                data.append({
                    "id": album.get("id", ""),
                    "name": attrs.get("name", ""),
                    "artist": attrs.get("artistName", ""),
                    "track_count": attrs.get("trackCount", 0),
                    "genre": genres[0] if genres else "",
                    "release_date": attrs.get("releaseDate", ""),
                })
        elif item_type == "artists":
            data = [{"id": a.get("id", ""), "name": a.get("attributes", {}).get("name", "")} for a in all_items]
        else:  # videos
            data = [{"id": v.get("id", ""), "name": v.get("attributes", {}).get("name", ""),
                     "artist": v.get("attributes", {}).get("artistName", "")} for v in all_items]

        return format_output(data, format, export, full, f"library_{item_type}")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ DISCOVERY & PERSONALIZATION ============


@mcp.tool()
def get_recommendations(
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Get personalized music recommendations based on your listening history.

    Args:
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports

    Returns: Recommendations in requested format
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/recommendations",
            headers=headers,
            params={"limit": 10},
        )
        response.raise_for_status()
        data = response.json()

        all_items = []
        for rec in data.get("data", []):
            attrs = rec.get("attributes", {})
            title = attrs.get("title", {}).get("stringForDisplay", "Recommendation")
            relationships = rec.get("relationships", {})
            contents = relationships.get("contents", {}).get("data", [])

            for item in contents[:8]:
                item_attrs = item.get("attributes", {})
                all_items.append({
                    "category": title,
                    "name": item_attrs.get("name", "Unknown"),
                    "artist": item_attrs.get("artistName", ""),
                    "type": item.get("type", "").replace("library-", ""),
                    "id": item.get("id"),
                    "year": item_attrs.get("releaseDate", "")[:4],
                })

        return format_output(all_items, format, export, full, "recommendations")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_heavy_rotation(
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Get your heavy rotation - content you've been playing frequently.

    Args:
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports

    Returns: Heavy rotation items in requested format
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/history/heavy-rotation",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("data", [])
        if not items:
            return "No heavy rotation data"

        # Extract item data
        item_data = []
        for item in items:
            attrs = item.get("attributes", {})
            genres = attrs.get("genreNames", [])

            item_data.append({
                "id": item.get("id", ""),
                "name": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "type": item.get("type", "").replace("library-", "").replace("-", " "),
                "track_count": attrs.get("trackCount", ""),
                "genre": genres[0] if genres else "",
                "release_date": attrs.get("releaseDate", ""),
                "date_added": attrs.get("dateAdded", ""),
                "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
            })

        return format_output(item_data, format, export, full, "heavy_rotation")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_recently_added(
    limit: int = 50,
    format: str = "text",
    export: str = "none",
    full: bool = False,
) -> str:
    """
    Get content recently added to your library.

    Args:
        limit: Number of items to return (default 50)
        format: "text" (default), "json", "csv", or "none" (export only)
        export: "none" (default), "csv", or "json" to write file
        full: Include all metadata in exports

    Returns: Recently added items in requested format
    """
    try:
        headers = get_headers()
        all_items = []
        offset = 0
        max_to_fetch = min(limit, 100)

        # Paginate
        while len(all_items) < max_to_fetch:
            batch_limit = min(25, max_to_fetch - len(all_items))
            response = requests.get(
                f"{BASE_URL}/me/library/recently-added",
                headers=headers,
                params={"limit": batch_limit, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            items = response.json().get("data", [])
            if not items:
                break
            all_items.extend(items)
            if len(items) < batch_limit:
                break
            offset += 25  # Recently-added uses fixed 25-item pages

        if not all_items:
            return "No recently added content"

        # Extract item data
        item_data = []
        for item in all_items:
            attrs = item.get("attributes", {})
            genres = attrs.get("genreNames", [])

            item_data.append({
                "id": item.get("id", ""),
                "name": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "type": item.get("type", "").replace("library-", ""),
                "track_count": attrs.get("trackCount", ""),
                "genre": genres[0] if genres else "",
                "release_date": attrs.get("releaseDate", ""),
                "date_added": attrs.get("dateAdded", ""),
                "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
            })

        return format_output(item_data, format, export, full, "recently_added")

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_artist_top_songs(artist_name: str) -> str:
    """
    Get an artist's top/most popular songs.

    Args:
        artist_name: Artist name to search for

    Returns: Artist's top songs with catalog IDs
    """
    try:
        headers = get_headers()

        # Search for artist first
        search_response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/search",
            headers=headers,
            params={"term": artist_name, "types": "artists", "limit": 1},
        )
        search_response.raise_for_status()
        artists = search_response.json().get("results", {}).get("artists", {}).get("data", [])

        if not artists:
            return f"No artist found matching '{artist_name}'"

        artist = artists[0]
        artist_id = artist.get("id")
        artist_actual_name = artist.get("attributes", {}).get("name", artist_name)

        # Get top songs
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/artists/{artist_id}/view/top-songs",
            headers=headers,
        )
        response.raise_for_status()
        songs = response.json().get("data", [])

        output = [f"=== Top Songs by {artist_actual_name} ==="]
        for i, song in enumerate(songs, 1):
            attrs = song.get("attributes", {})
            name = attrs.get("name", "Unknown")
            album = attrs.get("albumName", "")
            song_id = song.get("id")
            output.append(f"{i}. {name}" + (f" ({album})" if album else "") + f" [catalog ID: {song_id}]")

        return "\n".join(output) if len(output) > 1 else "No top songs found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_similar_artists(artist_name: str) -> str:
    """
    Get artists similar to a given artist.

    Args:
        artist_name: Artist name to search for

    Returns: List of similar artists
    """
    try:
        headers = get_headers()

        # Search for artist first
        search_response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/search",
            headers=headers,
            params={"term": artist_name, "types": "artists", "limit": 1},
        )
        search_response.raise_for_status()
        artists = search_response.json().get("results", {}).get("artists", {}).get("data", [])

        if not artists:
            return f"No artist found matching '{artist_name}'"

        artist = artists[0]
        artist_id = artist.get("id")
        artist_actual_name = artist.get("attributes", {}).get("name", artist_name)

        # Get similar artists
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/artists/{artist_id}/view/similar-artists",
            headers=headers,
        )
        response.raise_for_status()
        similar = response.json().get("data", [])

        output = [f"=== Artists Similar to {artist_actual_name} ==="]
        for artist in similar:
            attrs = artist.get("attributes", {})
            name = attrs.get("name", "Unknown")
            genres = ", ".join(attrs.get("genreNames", [])[:2])
            artist_id = artist.get("id")
            output.append(f"{name} ({genres}) [artist ID: {artist_id}]")

        return "\n".join(output) if len(output) > 1 else "No similar artists found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_song_station(song_id: str) -> str:
    """
    Get the radio station based on a song. Great for discovering similar music.

    Args:
        song_id: Catalog song ID (from search_catalog)

    Returns: Station info that you can reference when asking for similar music
    """
    try:
        headers = get_headers()

        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/songs/{song_id}/station",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        stations = data.get("data", [])
        if not stations:
            return "No station found for this song"

        station = stations[0]
        attrs = station.get("attributes", {})
        name = attrs.get("name", "Unknown Station")
        station_id = station.get("id")

        return f"Station: {name}\nStation ID: {station_id}\n\nUse this station to discover music similar to this song."

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ RATINGS ============


@mcp.tool()
def rating(
    action: str,
    track_name: str = "",
    artist: str = "",
    stars: int = 0,
    song_id: str = "",
) -> str:
    """
    Rate tracks: love, dislike, get stars, or set stars.

    Args:
        action: "love", "dislike", "get", or "set"
        track_name: Track name for name-based lookup
        artist: Optional artist to disambiguate
        stars: 0-5 stars (for "set" action only)
        song_id: Catalog ID for direct rating (alternative to track_name)

    Returns: Rating info or confirmation

    Note: get/set actions require macOS (AppleScript).
    """
    action = action.lower().strip()

    # Direct ID-based rating
    if song_id and action in ("love", "dislike"):
        success, msg = _rate_song_api(song_id, action)
        if success:
            return f"Set '{action}' for song {song_id}"
        return f"Error: {msg}"

    if not track_name:
        return "Error: track_name required (or song_id for love/dislike)"

    # Star ratings (macOS only)
    if action == "get":
        if not APPLESCRIPT_AVAILABLE:
            return "Error: Star ratings require macOS"
        success, r = asc.get_rating(track_name, artist if artist else None)
        if success:
            s = r // 20
            return f"{track_name}: {'★' * s}{'☆' * (5 - s)} ({r}/100)"
        return f"Error: {r}"

    if action == "set":
        if not APPLESCRIPT_AVAILABLE:
            return "Error: Star ratings require macOS"
        r = max(0, min(5, stars)) * 20
        success, result = asc.set_rating(track_name, r, artist if artist else None)
        if success:
            return f"Set {track_name} to {'★' * stars}{'☆' * (5 - stars)}"
        return f"Error: {result}"

    # Love/dislike by name
    if action not in ("love", "dislike"):
        return f"Invalid action: {action}. Use: love, dislike, get, set"

    # Try AppleScript first on macOS
    if APPLESCRIPT_AVAILABLE:
        func = asc.love_track if action == "love" else asc.dislike_track
        success, result = func(track_name, artist if artist else None)
        if success:
            return result

    # API fallback
    search_term = f"{track_name} {artist}".strip() if artist else track_name
    songs = _search_catalog_songs(search_term, limit=5)

    for song in songs:
        attrs = song.get("attributes", {})
        song_name = attrs.get("name", "")
        song_artist = attrs.get("artistName", "")
        if track_name.lower() in song_name.lower():
            if not artist or artist.lower() in song_artist.lower():
                success, msg = _rate_song_api(song.get("id"), action)
                if success:
                    return f"{action.capitalize()}d: {song_name} by {song_artist}"
                return f"Error: {msg}"

    return f"Track not found: {track_name}"


# ============ CATALOG DETAILS ============


@mcp.tool()
def get_song_details(song_id: str) -> str:
    """
    Get detailed information about a song from the catalog.

    Args:
        song_id: Catalog song ID

    Returns: Song details including album, duration, genre, etc.
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/songs/{song_id}",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        songs = data.get("data", [])
        if not songs:
            return "Song not found"

        attrs = songs[0].get("attributes", {})
        duration = format_duration(attrs.get("durationInMillis", 0)) or "Unknown"
        output = [
            f"Title: {attrs.get('name', 'Unknown')}",
            f"Artist: {attrs.get('artistName', 'Unknown')}",
            f"Album: {attrs.get('albumName', 'Unknown')}",
            f"Genre: {', '.join(attrs.get('genreNames', ['Unknown']))}",
            f"Duration: {duration}",
            f"Release Date: {attrs.get('releaseDate', 'Unknown')}",
            f"Explicit: {'Yes' if attrs.get('contentRating') == 'explicit' else 'No'}",
            f"ISRC: {attrs.get('isrc', 'N/A')}",
        ]

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_artist_details(artist_name: str) -> str:
    """
    Get detailed information about an artist by searching for them.

    Args:
        artist_name: Artist name to search for (e.g., "Oasis", "Taylor Swift")

    Returns: Artist details including genres and albums
    """
    try:
        headers = get_headers()

        # First search for the artist
        search_response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/search",
            headers=headers,
            params={"term": artist_name, "types": "artists", "limit": 1},
        )
        search_response.raise_for_status()
        search_data = search_response.json()

        artists = search_data.get("results", {}).get("artists", {}).get("data", [])
        if not artists:
            return f"No artist found matching '{artist_name}'"

        artist = artists[0]
        artist_id = artist.get("id")
        attrs = artist.get("attributes", {})

        output = [
            f"Artist: {attrs.get('name', 'Unknown')}",
            f"Artist ID: {artist_id}",
            f"Genres: {', '.join(attrs.get('genreNames', ['Unknown']))}",
        ]

        # Get artist's albums
        albums_response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/artists/{artist_id}/albums",
            headers=headers,
            params={"limit": 10},
        )
        if albums_response.status_code == 200:
            albums_data = albums_response.json()
            albums = albums_data.get("data", [])
            if albums:
                output.append("\nRecent Albums:")
                for album in albums[:10]:
                    album_attrs = album.get("attributes", {})
                    name = album_attrs.get("name", "Unknown")
                    year = album_attrs.get("releaseDate", "")[:4]
                    album_id = album.get("id")
                    output.append(f"  - {name} ({year}) [catalog ID: {album_id}]")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_charts(chart_type: str = "songs") -> str:
    """
    Get Apple Music charts (top songs, albums, etc.).

    Args:
        chart_type: Type of chart - 'songs', 'albums', 'music-videos', or 'playlists'

    Returns: Current chart listings
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/charts",
            headers=headers,
            params={"types": chart_type, "limit": 20},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        results = data.get("results", {})

        for chart_name, chart_data in results.items():
            for chart in chart_data:
                chart_title = chart.get("name", chart_name)
                output.append(f"=== {chart_title} ===")

                for i, item in enumerate(chart.get("data", [])[:20], 1):
                    attrs = item.get("attributes", {})
                    name = attrs.get("name", "Unknown")
                    artist = attrs.get("artistName", "")
                    if artist:
                        output.append(f"  {i}. {name} - {artist}")
                    else:
                        output.append(f"  {i}. {name}")

        return "\n".join(output) if output else "No chart data available"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_music_videos(query: str = "") -> str:
    """
    Search for music videos in the Apple Music catalog.

    Args:
        query: Search term (leave empty to get featured music videos)

    Returns: Music videos with their IDs
    """
    try:
        headers = get_headers()

        if query:
            response = requests.get(
                f"{BASE_URL}/catalog/{STOREFRONT}/search",
                headers=headers,
                params={"term": query, "types": "music-videos", "limit": 15},
            )
        else:
            response = requests.get(
                f"{BASE_URL}/catalog/{STOREFRONT}/charts",
                headers=headers,
                params={"types": "music-videos", "limit": 15},
            )

        response.raise_for_status()
        data = response.json()

        output = []

        if query:
            videos = data.get("results", {}).get("music-videos", {}).get("data", [])
        else:
            # Get from charts
            charts = data.get("results", {}).get("music-videos", [])
            videos = charts[0].get("data", []) if charts else []

        for video in videos:
            attrs = video.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "Unknown")
            duration = format_duration(attrs.get("durationInMillis", 0)) or "0:00"
            video_id = video.get("id")
            output.append(f"{name} - {artist} [{duration}] (ID: {video_id})")

        return "\n".join(output) if output else "No music videos found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_genres() -> str:
    """
    Get all available music genres in the Apple Music catalog.

    Returns: List of genres with their IDs
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/genres",
            headers=headers,
            params={"limit": 50},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        for genre in data.get("data", []):
            attrs = genre.get("attributes", {})
            name = attrs.get("name", "Unknown")
            genre_id = genre.get("id")
            output.append(f"{name} (ID: {genre_id})")

        return "\n".join(output) if output else "No genres found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_search_suggestions(term: str) -> str:
    """
    Get autocomplete/typeahead suggestions for a search term.
    Useful for building search interfaces or getting quick results.

    Args:
        term: Partial search term (e.g., "tay" for Taylor Swift)

    Returns: List of suggested search terms
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/search/suggestions",
            headers=headers,
            params={"term": term, "kinds": "terms", "limit": 10},
        )
        response.raise_for_status()
        data = response.json()

        suggestions = data.get("results", {}).get("suggestions", [])
        output = ["=== Search Suggestions ==="]
        for suggestion in suggestions:
            if suggestion.get("kind") == "terms":
                search_term = suggestion.get("searchTerm", "")
                display = suggestion.get("displayTerm", search_term)
                output.append(f"  {display}")

        return "\n".join(output) if len(output) > 1 else "No suggestions found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_storefronts() -> str:
    """
    Get all available Apple Music storefronts (regions/countries).
    Useful for understanding which markets are available.

    Returns: List of storefronts with their codes and names
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/storefronts",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        output = ["=== Apple Music Storefronts ==="]
        for storefront in data.get("data", []):
            sf_id = storefront.get("id", "")
            attrs = storefront.get("attributes", {})
            name = attrs.get("name", "Unknown")
            language = attrs.get("defaultLanguageTag", "")
            output.append(f"  {sf_id.upper()}: {name} ({language})")

        return "\n".join(output) if len(output) > 1 else "No storefronts found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_personal_station() -> str:
    """
    Get your personal Apple Music radio station.
    This is a station curated based on your listening history.

    Returns: Personal station info
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/stations",
            headers=headers,
            params={"filter[identity]": "personal"},
        )
        response.raise_for_status()
        data = response.json()

        stations = data.get("data", [])
        if not stations:
            return "No personal station found (may require more listening history)"

        station = stations[0]
        attrs = station.get("attributes", {})
        name = attrs.get("name", "Your Personal Station")
        station_id = station.get("id")
        is_live = attrs.get("isLive", False)

        output = [
            f"=== {name} ===",
            f"Station ID: {station_id}",
            f"Type: {'Live' if is_live else 'On-demand'}",
            "",
            "This station plays music based on your listening history and preferences.",
        ]
        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ CACHE MANAGEMENT ============


@mcp.tool()
def cache(action: str = "info", days_old: int = 0) -> str:
    """
    View or clear cached CSV files.

    Args:
        action: "info" (default) to list files, "clear" to delete files
        days_old: When clearing, only delete files older than this (0 = all)

    Returns: Cache info or deletion summary
    """
    try:
        cache_dir = get_cache_dir()
        if not cache_dir.exists():
            return "Cache directory doesn't exist"

        csv_files = list(cache_dir.glob("*.csv"))
        if not csv_files:
            return "No CSV files in cache"

        now = time.time()

        if action.lower() == "clear":
            cutoff = now - (days_old * 86400) if days_old > 0 else now + 1
            deleted = []
            kept = []
            total_size = 0

            for f in csv_files:
                file_size = f.stat().st_size
                if days_old == 0 or f.stat().st_mtime < cutoff:
                    deleted.append(f.name)
                    total_size += file_size
                    f.unlink()
                else:
                    kept.append(f.name)

            if total_size < 1024:
                size_str = f"{total_size} bytes"
            elif total_size < 1024 * 1024:
                size_str = f"{total_size / 1024:.1f} KB"
            else:
                size_str = f"{total_size / (1024 * 1024):.1f} MB"

            output = [f"Deleted: {len(deleted)} files ({size_str})"]
            if kept:
                output.append(f"Kept: {len(kept)} files (newer than {days_old} days)")
            return "\n".join(output)

        else:  # info
            csv_files = sorted(csv_files, key=lambda f: f.stat().st_mtime, reverse=True)
            total_size = 0
            output = [f"=== Cache: {cache_dir} ===", ""]

            for f in csv_files:
                file_size = f.stat().st_size
                total_size += file_size
                age_days = (now - f.stat().st_mtime) / 86400

                if file_size < 1024:
                    size_str = f"{file_size}B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.0f}KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f}MB"

                age_str = f"{age_days * 24:.0f}h ago" if age_days < 1 else f"{age_days:.0f}d ago"
                output.append(f"{f.name} ({size_str}, {age_str})")

            total_str = f"{total_size / 1024:.1f} KB" if total_size < 1024 * 1024 else f"{total_size / (1024 * 1024):.1f} MB"
            output.insert(1, f"Total: {len(csv_files)} files, {total_str}")
            return "\n".join(output)

    except Exception as e:
        return f"Error reading cache: {str(e)}"


@mcp.tool()
def test_output_size(target_chars: int = 50000) -> str:
    """
    Diagnostic tool to test MCP response size limits using real library data.

    Fetches tracks from multiple playlists to build unique (non-repeating) content
    until hitting the target character count. Use this to find where output gets
    truncated by checking if the END marker is visible.

    Args:
        target_chars: Target character count to test (default 50000)

    Returns: Real track data from your library, with markers to detect truncation
    """
    try:
        headers = get_headers()

        # Fetch all playlists
        response = requests.get(
            f"{BASE_URL}/me/library/playlists",
            headers=headers,
            params={"limit": 100},
        )
        response.raise_for_status()
        playlists = response.json().get("data", [])

        if not playlists:
            return "No playlists found in library"

        # Build output by fetching tracks from different playlists
        header = f"=== SIZE TEST: {target_chars:,} chars target ===\n"
        header += f"=== Found {len(playlists)} playlists to draw from ===\n\n"

        content = header
        playlists_used = 0
        total_tracks = 0

        for playlist in playlists:
            if len(content) >= target_chars:
                break

            playlist_id = playlist.get("id", "")
            playlist_name = playlist.get("attributes", {}).get("name", "Unknown")

            # Fetch this playlist's tracks
            try:
                track_response = requests.get(
                    f"{BASE_URL}/me/library/playlists/{playlist_id}/tracks",
                    headers=headers,
                    params={"limit": 100},
                )
                track_response.raise_for_status()
                tracks = track_response.json().get("data", [])
            except requests.exceptions.RequestException:
                continue  # Skip playlists that fail

            if not tracks:
                continue

            # Format and add this playlist's tracks
            playlist_header = f"--- {playlist_name} ({len(tracks)} tracks, char {len(content):,}) ---\n"
            content += playlist_header

            for t in tracks:
                if len(content) >= target_chars:
                    break
                data = extract_track_data(t, include_extras=False)
                line = _format_full(data)
                content += line + "\n"
                total_tracks += 1

            content += "\n"
            playlists_used += 1

        # If we still haven't hit target, note it
        if len(content) < target_chars:
            content += f"\n(Exhausted all {len(playlists)} playlists at {len(content):,} chars)\n"

        footer = f"\n\n=== END: {len(content):,} chars, {playlists_used} playlists, {total_tracks} tracks ==="

        return content + footer

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ STATUS ============


@mcp.tool()
def check_auth_status() -> str:
    """Check if authentication tokens are valid and API is accessible."""
    config_dir = get_config_dir()
    dev_token_file = config_dir / "developer_token.json"
    user_token_file = config_dir / "music_user_token.json"

    status = []

    # Check developer token
    if dev_token_file.exists():
        try:
            with open(dev_token_file) as f:
                data = json.load(f)
            expires = data.get("expires", 0)
            days_left = (expires - time.time()) / 86400

            if days_left < 0:
                status.append("Developer Token: EXPIRED - Run: applemusic-mcp generate-token")
            elif days_left < 30:
                status.append(f"Developer Token: ⚠️ EXPIRES IN {int(days_left)} DAYS - Run: applemusic-mcp generate-token")
            else:
                status.append(f"Developer Token: OK ({int(days_left)} days remaining)")
        except Exception:
            status.append("Developer Token: ERROR reading file")
    else:
        status.append("Developer Token: MISSING - Run: applemusic-mcp generate-token")

    # Check user token
    if user_token_file.exists():
        status.append("Music User Token: OK")
    else:
        status.append("Music User Token: MISSING - Run: applemusic-mcp authorize")

    # Test API connection
    if dev_token_file.exists() and user_token_file.exists():
        try:
            headers = get_headers()
            response = requests.get(
                f"{BASE_URL}/me/library/playlists", headers=headers, params={"limit": 1}
            )
            if response.status_code == 200:
                status.append("API Connection: OK")
            elif response.status_code == 401:
                status.append("API Connection: UNAUTHORIZED - Token may be expired. Run: applemusic-mcp authorize")
            else:
                status.append(f"API Connection: FAILED ({response.status_code})")
        except Exception as e:
            status.append(f"API Connection: ERROR - {str(e)}")

    return "\n".join(status)


# =============================================================================
# AppleScript-powered tools (macOS only)
# =============================================================================
# These tools provide capabilities not available through the REST API:
# - Playback control (play, pause, skip)
# - Delete tracks from playlists
# - Delete playlists
# - Volume and shuffle control
# - Get currently playing track

if APPLESCRIPT_AVAILABLE:

    @mcp.tool()
    def play_track(
        track_name: str,
        artist: str = "",
        reveal: bool = False,
        add_to_library: bool = False,
    ) -> str:
        """Play a track from your library (macOS only).

        Plays tracks from your library. For songs not in your library, use
        reveal=True to open in Music app, or add_to_library=True to add first.

        Note: AppleScript cannot directly play catalog songs not in your library.
        This is a macOS limitation, not a bug.

        Args:
            track_name: Name of the track to play (can be partial match)
            artist: Optional artist name to disambiguate
            reveal: If track not in library, open it in Music app
            add_to_library: If track not in library, add it first then play

        Returns: Confirmation message or error
        """
        # Try library first
        success, result = asc.play_track(track_name, artist if artist else None)
        if success:
            if reveal:
                asc.reveal_track(track_name, artist if artist else None)
            return result

        # Track not in library - search catalog using helper
        search_term = f"{track_name} {artist}".strip() if artist else track_name
        songs = _search_catalog_songs(search_term, limit=5)

        # Find best match
        for song in songs:
            attrs = song.get("attributes", {})
            song_name = attrs.get("name", "")
            song_artist = attrs.get("artistName", "")

            # Check if it's a reasonable match
            if track_name.lower() not in song_name.lower():
                continue
            if artist and artist.lower() not in song_artist.lower():
                continue

            catalog_id = song.get("id")

            # Option 1: Add to library first, then play
            if add_to_library:
                add_ok, add_msg = _add_songs_to_library([catalog_id])
                if add_ok:
                    # Wait for iCloud sync, then play (up to ~10 seconds)
                    time.sleep(1)  # Initial delay for sync to start
                    for attempt in range(45):
                        if attempt > 0:
                            time.sleep(0.2)
                        success, result = asc.play_track(song_name, song_artist)
                        if success:
                            if reveal:
                                asc.reveal_track(song_name, song_artist)
                            return f"Added to library and playing: {song_name} by {song_artist}"
                    return f"Added to library but couldn't play yet: {song_name} by {song_artist}. Try again in a moment."
                return f"Failed to add to library: {add_msg}"

            # Option 2: Just reveal in Music app
            if reveal:
                asc.open_catalog_song(catalog_id)
                return (
                    f"Opened in Music: {song_name} by {song_artist}. "
                    f"Click play to start (AppleScript can't auto-play catalog songs not in library)."
                )

            # Neither flag set - explain limitation
            return (
                f"Found in catalog: {song_name} by {song_artist}. "
                f"Use add_to_library=True to add and play, or reveal=True to open in Music app. "
                f"(AppleScript cannot auto-play catalog songs not in your library)"
            )

        return f"Track not found in library or catalog: {track_name}"

    @mcp.tool()
    def play_playlist(playlist_name: str, shuffle: bool = False) -> str:
        """Start playing a playlist (macOS only).

        Args:
            playlist_name: Name of the playlist to play
            shuffle: Whether to shuffle the playlist

        Returns: Confirmation message or error
        """
        success, result = asc.play_playlist(playlist_name, shuffle)
        if success:
            return result
        return f"Error: {result}"

    @mcp.tool()
    def playback_control(action: str) -> str:
        """Control playback: play, pause, stop, next, previous (macOS only).

        Args:
            action: One of: play, pause, playpause, stop, next, previous

        Returns: Confirmation message or error
        """
        action = action.lower().strip()
        action_map = {
            "play": asc.play,
            "pause": asc.pause,
            "playpause": asc.playpause,
            "stop": asc.stop,
            "next": asc.next_track,
            "previous": asc.previous_track,
        }
        if action not in action_map:
            return f"Invalid action: {action}. Use: play, pause, playpause, stop, next, previous"

        success, result = action_map[action]()
        if success:
            return f"Playback: {action}"
        return f"Error: {result}"

    @mcp.tool()
    def get_now_playing() -> str:
        """Get info about the currently playing track (macOS only).

        Returns: Track info (name, artist, album, position) or stopped message
        """
        success, info = asc.get_current_track()
        if not success:
            return f"Error: {info}"

        if info.get("state") == "stopped":
            return "Not currently playing"

        parts = []
        if "name" in info:
            parts.append(f"Track: {info['name']}")
        if "artist" in info:
            parts.append(f"Artist: {info['artist']}")
        if "album" in info:
            parts.append(f"Album: {info['album']}")
        if "position" in info and "duration" in info:
            try:
                pos = float(info["position"])
                dur = float(info["duration"])
                pos_min, pos_sec = int(pos) // 60, int(pos) % 60
                dur_min, dur_sec = int(dur) // 60, int(dur) % 60
                parts.append(f"Position: {pos_min}:{pos_sec:02d} / {dur_min}:{dur_sec:02d}")
            except (ValueError, TypeError):
                pass

        return "\n".join(parts) if parts else "Playing (no track info available)"

    @mcp.tool()
    def playback_settings(
        volume: int = -1,
        shuffle: str = "",
        repeat: str = "",
    ) -> str:
        """Get or set playback settings (macOS only).

        With no args, returns current settings. Provide any arg to change it.

        Args:
            volume: 0-100 (-1 to leave unchanged)
            shuffle: "on" or "off" (empty to leave unchanged)
            repeat: "off", "one", or "all" (empty to leave unchanged)

        Returns: Current/updated settings or confirmation
        """
        changes = []

        # Apply any changes
        if volume >= 0:
            v = max(0, min(100, volume))
            success, result = asc.set_volume(v)
            if not success:
                return f"Error setting volume: {result}"
            changes.append(f"Volume: {v}")

        if shuffle:
            enabled = shuffle.lower() in ("on", "true", "1", "yes")
            success, result = asc.set_shuffle(enabled)
            if not success:
                return f"Error setting shuffle: {result}"
            changes.append(f"Shuffle: {'on' if enabled else 'off'}")

        if repeat:
            success, result = asc.set_repeat(repeat.lower())
            if not success:
                return f"Error setting repeat: {result}"
            changes.append(f"Repeat: {repeat}")

        # If changes were made, return confirmation
        if changes:
            return "Updated: " + ", ".join(changes)

        # Otherwise return current settings
        success, stats = asc.get_library_stats()
        if not success:
            return f"Error: {stats}"

        return (
            f"Player: {stats['player_state']}\n"
            f"Volume: {stats['volume']}\n"
            f"Shuffle: {'on' if stats['shuffle'] else 'off'}\n"
            f"Repeat: {stats['repeat']}"
        )

    @mcp.tool()
    def seek_to_position(seconds: float) -> str:
        """Seek to a specific position in the current track (macOS only).

        Args:
            seconds: Position in seconds from the start of the track

        Returns: Confirmation message
        """
        success, result = asc.seek(seconds)
        if success:
            return f"Seeked to {int(seconds // 60)}:{int(seconds % 60):02d}"
        return f"Error: {result}"

    @mcp.tool()
    def remove_from_playlist(playlist_name: str, track_name: str, artist: str = "") -> str:
        """Remove a track from a playlist (macOS only).

        This only removes the track from the playlist, not from your library.

        Args:
            playlist_name: Name of the playlist
            track_name: Name of the track to remove
            artist: Optional artist name to disambiguate

        Returns: Confirmation message or error
        """
        success, result = asc.remove_track_from_playlist(
            playlist_name, track_name, artist if artist else None
        )
        if success:
            return result
        return f"Error: {result}"

    @mcp.tool()
    def remove_from_library(track_name: str, artist: str = "") -> str:
        """Remove a track from your library entirely (macOS only).

        This deletes the track from your library. Use with caution.

        Args:
            track_name: Name of the track to remove (partial match)
            artist: Optional artist name to disambiguate

        Returns: Confirmation message or error
        """
        success, result = asc.remove_from_library(track_name, artist if artist else None)
        if success:
            return result
        return f"Error: {result}"

    @mcp.tool()
    def get_player_state() -> str:
        """Get current player state (macOS only).

        Returns: 'playing', 'paused', or 'stopped'
        """
        success, state = asc.get_player_state()
        if success:
            return f"Player state: {state}"
        return f"Error: {state}"

    @mcp.tool()
    def delete_playlist(playlist_name: str) -> str:
        """Delete a playlist entirely (macOS only).

        Warning: This permanently deletes the playlist. It cannot be undone.

        Args:
            playlist_name: Name of the playlist to delete

        Returns: Confirmation message or error
        """
        success, result = asc.delete_playlist(playlist_name)
        if success:
            return result
        return f"Error: {result}"

    @mcp.tool()
    def reveal_in_music(track_name: str, artist: str = "") -> str:
        """Reveal a track in the Music app window (macOS only).

        Opens Music app and navigates to show the track.

        Args:
            track_name: Name of the track (can be partial match)
            artist: Optional artist name to disambiguate

        Returns: Confirmation message or error
        """
        success, result = asc.reveal_track(track_name, artist if artist else None)
        if success:
            return result
        return f"Error: {result}"

    @mcp.tool()
    def airplay(device_name: str = "") -> str:
        """List or switch AirPlay devices (macOS only).

        Args:
            device_name: Device to switch to (partial match OK). Omit to list devices.

        Returns: Device list or switch confirmation
        """
        if device_name:
            success, result = asc.set_airplay_device(device_name)
            if success:
                return result
            return f"Error: {result}"
        else:
            success, devices = asc.get_airplay_devices()
            if not success:
                return f"Error: {devices}"
            if not devices:
                return "No AirPlay devices found"
            return f"AirPlay devices ({len(devices)}):\n" + "\n".join(f"  - {d}" for d in devices)



def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
