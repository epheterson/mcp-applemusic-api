"""MCP server for Apple Music - Cross-platform playlist and library management.

On macOS, additional AppleScript-powered tools are available for playback control,
deleting tracks from playlists, and other operations not supported by the REST API.
"""

import csv
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


BASE_URL = "https://api.music.apple.com/v1"
STOREFRONT = "us"

mcp = FastMCP("AppleMusicAPI")


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
def get_library_playlists() -> str:
    """
    Get all playlists from your Apple Music library.
    Returns playlist names, IDs, edit status, and metadata.
    Only API-created playlists can be edited.
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

        output = []

        # Check for token expiration warning
        warning = get_token_expiration_warning()
        if warning:
            output.append(warning)
            output.append("")

        # Extract full playlist data
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

        # Write CSV with full data
        if playlist_data:
            csv_path = get_cache_dir() / "library_playlists.csv"
            csv_fields = ["name", "id", "can_edit", "is_public", "date_added", "last_modified", "description", "has_catalog"]

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=csv_fields)
                writer.writeheader()
                writer.writerows(playlist_data)

            output.append(f"=== {len(playlist_data)} playlists ===")
            output.append(f"Full data: {csv_path}")
            output.append("")

        for p in playlist_data:
            edit_status = "editable" if p["can_edit"] else "read-only"
            modified = p["last_modified"][:10] if p["last_modified"] else ""
            mod_str = f", modified {modified}" if modified else ""
            output.append(f"{p['name']} (ID: {p['id']}, {edit_status}{mod_str})")

        return "\n".join(output) if output else "No playlists found"

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
    include_extras: bool = False,
) -> str:
    """
    Get tracks in a playlist.

    Provide EITHER playlist_id (API) OR playlist_name (AppleScript, macOS only).

    Args:
        playlist_id: Playlist ID (from get_library_playlists)
        playlist_name: Playlist name (macOS only, uses AppleScript)
        filter: Filter tracks by name/artist (case-insensitive substring match)
        limit: Max tracks to return (0 = all). Use with large playlists.
        include_extras: Include extra metadata in CSV (track/disc numbers, artwork, etc.)

    Returns: Track count, CSV file path, and track listing (tiered based on size)
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

        # Write CSV (full data always)
        safe_name = "".join(c if c.isalnum() else "_" for c in playlist_name)
        csv_path = get_cache_dir() / f"playlist_{safe_name}.csv"
        write_tracks_csv(track_data, csv_path, include_extras)
        total_count = len(track_data)

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

        count = len(track_data)
        formatted_lines, tier = format_track_list(track_data)
        header = f"=== {count} tracks"
        if filter or limit:
            header += f" (of {total_count} total)"
        header += f" ({tier} format) ==="
        output = [header, f"Full data: {csv_path}", ""]
        output.extend(formatted_lines)
        return "\n".join(output)

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
            # 404 can mean empty playlist or end of pagination
            if response.status_code == 404:
                break
            response.raise_for_status()
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)
            if len(tracks) < 100:
                break  # Last page
            offset += 100

        if not all_tracks:
            return "Playlist is empty"

        # Extract track data using helper
        track_data = [extract_track_data(t, include_extras) for t in all_tracks]

        # Write CSV using helper (full data always)
        csv_path = get_cache_dir() / f"playlist_{playlist_id.replace('.', '_')}.csv"
        write_tracks_csv(track_data, csv_path, include_extras)
        total_count = len(track_data)

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

        # Build output
        count = len(track_data)
        formatted_lines, tier = format_track_list(track_data)
        header = f"=== {count} tracks"
        if filter or limit:
            header += f" (of {total_count} total)"
        header += f" ({tier} format) ==="
        output = [header, f"Full data: {csv_path}", ""]
        output.extend(formatted_lines)

        return "\n".join(output)

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

    MODE 1 - By IDs (cross-platform):
        add_to_playlist(playlist_id="p.ABC123", track_ids="1440783617")  # catalog ID
        add_to_playlist(playlist_id="p.ABC123", track_ids="i.XYZ789")    # library ID

    MODE 2 - By names (macOS only, works on ANY playlist):
        add_to_playlist(playlist_name="Road Trip", track_name="Hey Jude", artist="The Beatles")

    Args:
        playlist_id: Playlist ID (from get_library_playlists)
        track_ids: Track IDs - accepts catalog IDs (numeric) or library IDs
        playlist_name: Playlist name (macOS only, uses AppleScript)
        track_name: Track name (macOS only)
        artist: Artist name (optional, helps with matching)
        allow_duplicates: If False (default), skip tracks already in playlist
        verify: If True, verify track was added (slower but confirms success)

    Returns: Detailed result of what happened
    """
    steps = []  # Track what we did for verbose output

    # Determine which mode
    use_api = bool(playlist_id)
    use_applescript = bool(playlist_name and track_name)

    if use_api and use_applescript:
        return "Error: Provide either IDs or names, not both"

    if not use_api and not use_applescript:
        return "Error: Provide playlist_id + track_ids, or playlist_name + track_name"

    # === MODE 2: AppleScript with names (macOS) ===
    if use_applescript:
        if not APPLESCRIPT_AVAILABLE:
            return "Error: Name-based add requires macOS"

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

    # === MODE 1: API with IDs ===
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
def search_library(query: str, limit: int = 25, include_extras: bool = False) -> str:
    """
    Search your personal Apple Music library for songs.

    Args:
        query: Search term
        limit: Max results to return (default 25)
        include_extras: Include extra metadata in CSV (track/disc numbers, artwork, etc.)

    Returns: Songs from your library with library IDs (these can be added to playlists)
    """
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

        # Extract song data using helper
        song_data = [extract_track_data(s, include_extras) for s in songs]

        # Write CSV (timestamped to avoid overwrites)
        safe_query = "".join(c if c.isalnum() else "_" for c in query)[:30]
        csv_path = get_cache_dir() / f"search_library_{safe_query}_{get_timestamp()}.csv"
        write_tracks_csv(song_data, csv_path, include_extras)

        # Build output
        count = len(song_data)
        formatted_lines, tier = format_track_list(song_data)
        output = [f"=== {count} results for '{query}' ({tier} format) ===", f"Full data: {csv_path}", ""]
        output.extend(formatted_lines)

        return "\n".join(output)

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
def get_recently_played(limit: int = 30, include_extras: bool = False) -> str:
    """
    Get recently played tracks from your Apple Music history.

    Args:
        limit: Number of tracks to return (default 30, max 50)
        include_extras: Include extra metadata in CSV (track/disc numbers, artwork, etc.)

    Returns: Recently played tracks with CSV export
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

        # Extract track data using helper
        track_data = [extract_track_data(t, include_extras) for t in all_tracks]

        # Write CSV using helper
        csv_path = get_cache_dir() / "recently_played.csv"
        write_tracks_csv(track_data, csv_path, include_extras)

        # Build output
        count = len(track_data)
        formatted_lines, tier = format_track_list(track_data)
        output = [f"=== {count} recently played tracks ({tier} format) ===", f"Full data: {csv_path}", ""]
        output.extend(formatted_lines)

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ CATALOG SEARCH ============


@mcp.tool()
def search_catalog(query: str, types: str = "songs", limit: int = 15, include_extras: bool = False) -> str:
    """
    Search the Apple Music catalog.

    Args:
        query: Search term
        types: Comma-separated types (songs, albums, artists, playlists)
        limit: Max results per type (default 15)
        include_extras: Include extra metadata in CSV (track/disc numbers, artwork, etc.)

    Returns: Search results with catalog IDs (use add_to_library to add songs to your library first)
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

        output = []
        results = data.get("results", {})

        if "songs" in results:
            songs = results["songs"].get("data", [])

            # Always extract extras for display ([E] markers) - CSV respects include_extras param
            song_data = [extract_track_data(s, include_extras=True) for s in songs]

            if song_data:
                # Write CSV (timestamped to avoid overwrites)
                safe_query = "".join(c if c.isalnum() else "_" for c in query)[:30]
                csv_path = get_cache_dir() / f"search_catalog_{safe_query}_{get_timestamp()}.csv"
                write_tracks_csv(song_data, csv_path, include_extras)

                output.append(f"=== {len(song_data)} Songs (use add_to_library with these IDs) ===")
                output.append(f"Full data: {csv_path}")
                output.append("")

                # Display with explicit markers: Name - Artist (duration) Album [Year] Genre [E] id
                for s in song_data:
                    year_str = f" [{s['year']}]" if s["year"] else ""
                    genre_str = f" {s['genre']}" if s["genre"] else ""
                    explicit_str = " [E]" if s.get("is_explicit") else ""
                    output.append(f"{s['name']} - {s['artist']} ({s['duration']}) {s['album']}{year_str}{genre_str}{explicit_str} {s['id']}")

        if "albums" in results:
            albums = results["albums"].get("data", [])
            output.append("")
            output.append(f"=== {len(albums)} Albums ===")
            for album in albums:
                attrs = album.get("attributes", {})
                name = attrs.get("name", "Unknown")
                artist = attrs.get("artistName", "Unknown")
                year = attrs.get("releaseDate", "")[:4]
                year_str = f" [{year}]" if year else ""
                track_count = attrs.get("trackCount", 0)
                album_id = album.get("id")
                output.append(f"  {name} - {artist} ({track_count} tracks){year_str} [catalog ID: {album_id}]")

        if "artists" in results:
            artists = results["artists"].get("data", [])
            output.append("")
            output.append(f"=== {len(artists)} Artists ===")
            for artist in artists:
                attrs = artist.get("attributes", {})
                name = attrs.get("name", "Unknown")
                genres = ", ".join(attrs.get("genreNames", [])[:2])
                genre_str = f" ({genres})" if genres else ""
                artist_id = artist.get("id")
                output.append(f"  {name}{genre_str} [artist ID: {artist_id}]")

        if "playlists" in results:
            playlists = results["playlists"].get("data", [])
            output.append("")
            output.append(f"=== {len(playlists)} Playlists ===")
            for playlist in playlists:
                attrs = playlist.get("attributes", {})
                name = attrs.get("name", "Unknown")
                curator = attrs.get("curatorName", "")
                curator_str = f" by {curator}" if curator else ""
                playlist_id = playlist.get("id")
                output.append(f"  {name}{curator_str} [playlist ID: {playlist_id}]")

        return "\n".join(output) if output else "No results found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_album_tracks(album_id: str, include_extras: bool = False) -> str:
    """
    Get all tracks from an album.
    Works with both library album IDs (l.xxx from get_library_albums)
    and catalog album IDs (numeric from search_catalog).

    Args:
        album_id: Library album ID (l.xxx) or catalog album ID (numeric)
        include_extras: Include extra metadata in CSV (composer, artwork, etc.)

    Returns: Track count, CSV file path, and track listing
    """
    try:
        headers = get_headers()

        # Detect if it's a library or catalog ID
        if album_id.startswith("l."):
            base_url = f"{BASE_URL}/me/library/albums/{album_id}/tracks"
            id_type = "library"
        else:
            base_url = f"{BASE_URL}/catalog/{STOREFRONT}/albums/{album_id}/tracks"
            id_type = "catalog"

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

        # Always extract extras for display (track numbers, [E] markers) - CSV respects include_extras param
        track_data = [extract_track_data(t, include_extras=True) for t in all_tracks]

        # Write CSV
        safe_id = album_id.replace(".", "_")
        csv_path = get_cache_dir() / f"album_{safe_id}.csv"
        write_tracks_csv(track_data, csv_path, include_extras)

        # Build output - album tracks use numbered format
        count = len(track_data)
        output = [f"=== {count} tracks ({id_type} IDs) ===", f"Full data: {csv_path}", ""]

        for t in track_data:
            track_num = t.get("track_number", "")
            disc_num = t.get("disc_number")
            # Show disc prefix only for multi-disc albums (disc > 1)
            # Handle both int and empty string cases
            disc_str = f"{disc_num}-" if disc_num and isinstance(disc_num, int) and disc_num > 1 else ""
            explicit_str = " [E]" if t.get("is_explicit") else ""
            year_str = f" [{t['year']}]" if t["year"] else ""
            # Format: 1. Name - Artist (duration) [Year] Genre [E] id
            output.append(f"{disc_str}{track_num}. {t['name']} - {t['artist']} ({t['duration']}){year_str} {t['genre']}{explicit_str} {t['id']}")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ LIBRARY BROWSING ============


@mcp.tool()
def get_library_albums() -> str:
    """
    Get all albums in your Apple Music library.

    Returns: Album count, CSV file path, and album listing
    """
    try:
        headers = get_headers()
        all_albums = []
        offset = 0

        while True:
            response = requests.get(
                f"{BASE_URL}/me/library/albums",
                headers=headers,
                params={"limit": 100, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            albums = response.json().get("data", [])
            if not albums:
                break
            all_albums.extend(albums)
            if len(albums) < 100:
                break
            offset += 100

        if not all_albums:
            return "No albums in library"

        # Extract full album data
        album_data = []
        for album in all_albums:
            attrs = album.get("attributes", {})
            genres = attrs.get("genreNames", [])

            album_data.append({
                "id": album.get("id", ""),
                "name": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "track_count": attrs.get("trackCount", 0),
                "genre": genres[0] if genres else "",
                "genres": ", ".join(genres),
                "release_date": attrs.get("releaseDate", ""),
                "date_added": attrs.get("dateAdded", ""),
                "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
            })

        # Write CSV with full data
        csv_path = get_cache_dir() / "library_albums.csv"
        csv_fields = ["name", "artist", "track_count", "genre", "genres", "release_date", "date_added", "id", "artwork_url"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(album_data)

        # Build output
        count = len(album_data)
        output = [f"=== {count} albums ===", f"Full data: {csv_path}", ""]

        # Tiered display
        if count <= 150:
            for a in album_data:
                year = a["release_date"][:4] if a["release_date"] else ""
                year_str = f" [{year}]" if year else ""
                genre_str = f" {a['genre']}" if a["genre"] else ""
                output.append(f"{a['name']} - {a['artist']} ({a['track_count']} tracks) {year_str}{genre_str} {a['id']}")
        else:
            for a in album_data:
                name = a["name"][:40] + "..." if len(a["name"]) > 40 else a["name"]
                artist = a["artist"][:20] + "..." if len(a["artist"]) > 20 else a["artist"]
                output.append(f"{name} - {artist} ({a['track_count']}) {a['id']}")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_library_artists() -> str:
    """
    Get all artists in your Apple Music library.

    Returns: Artist count, CSV file path, and artist listing
    """
    try:
        headers = get_headers()
        all_artists = []
        offset = 0

        # Paginate to get all artists
        while True:
            response = requests.get(
                f"{BASE_URL}/me/library/artists",
                headers=headers,
                params={"limit": 100, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            artists = response.json().get("data", [])
            if not artists:
                break
            all_artists.extend(artists)
            if len(artists) < 100:
                break
            offset += 100

        if not all_artists:
            return "No artists in library"

        # Extract artist data (library artists have limited metadata)
        artist_data = []
        for artist in all_artists:
            attrs = artist.get("attributes", {})
            artist_data.append({
                "id": artist.get("id", ""),
                "name": attrs.get("name", ""),
            })

        # Write CSV
        csv_path = get_cache_dir() / "library_artists.csv"
        csv_fields = ["name", "id"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(artist_data)

        # Build output
        count = len(artist_data)
        output = [f"=== {count} artists ===", f"Full data: {csv_path}", ""]

        # Tiered display
        if count <= 200:
            for a in artist_data:
                output.append(f"{a['name']} [library ID: {a['id']}]")
        else:
            for a in artist_data:
                name = a["name"][:40] + "..." if len(a["name"]) > 40 else a["name"]
                output.append(f"{name} ({a['id']})")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_library_songs(limit: int = 100, include_extras: bool = False) -> str:
    """
    Get songs from your Apple Music library (not a search, just browse).

    Args:
        limit: Number of songs to return (default 100, use 0 for all songs)
        include_extras: Include extra metadata in CSV (track/disc numbers, artwork, etc.)

    Returns: Song count, CSV file path, and song listing
    """
    try:
        headers = get_headers()
        all_songs = []
        offset = 0
        fetch_all = limit == 0
        max_to_fetch = limit if not fetch_all else float('inf')

        while len(all_songs) < max_to_fetch:
            batch_limit = 100 if fetch_all else min(100, max_to_fetch - len(all_songs))
            response = requests.get(
                f"{BASE_URL}/me/library/songs",
                headers=headers,
                params={"limit": batch_limit, "offset": offset},
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            songs = response.json().get("data", [])
            if not songs:
                break
            all_songs.extend(songs)
            if len(songs) < 100:
                break
            offset += 100

        if not all_songs:
            return "No songs in library"

        # Extract song data using helper
        song_data = [extract_track_data(s, include_extras) for s in all_songs]

        # Write CSV using helper
        csv_path = get_cache_dir() / "library_songs.csv"
        write_tracks_csv(song_data, csv_path, include_extras)

        # Build output
        count = len(song_data)
        formatted_lines, tier = format_track_list(song_data)
        output = [f"=== {count} songs ({tier} format) ===", f"Full data: {csv_path}", ""]
        output.extend(formatted_lines)

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ DISCOVERY & PERSONALIZATION ============


@mcp.tool()
def get_recommendations() -> str:
    """
    Get personalized music recommendations based on your listening history.

    Returns: Grouped recommendations with IDs for adding to library/playlists
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

        output = []
        all_items = []

        for rec in data.get("data", []):
            attrs = rec.get("attributes", {})
            title = attrs.get("title", {}).get("stringForDisplay", "Recommendation")

            output.append(f"=== {title} ===")

            # Get the recommended items
            relationships = rec.get("relationships", {})
            contents = relationships.get("contents", {}).get("data", [])

            for item in contents[:8]:
                item_attrs = item.get("attributes", {})
                name = item_attrs.get("name", "Unknown")
                artist = item_attrs.get("artistName", "")
                item_type = item.get("type", "").replace("library-", "")
                item_id = item.get("id")
                year = item_attrs.get("releaseDate", "")[:4]
                year_str = f" [{year}]" if year else ""

                all_items.append({
                    "category": title,
                    "name": name,
                    "artist": artist,
                    "type": item_type,
                    "id": item_id,
                    "year": year,
                })

                if artist:
                    output.append(f"  {name} - {artist}{year_str} ({item_type}) [ID: {item_id}]")
                else:
                    output.append(f"  {name}{year_str} ({item_type}) [ID: {item_id}]")

            output.append("")

        # Write CSV with all recommendations
        if all_items:
            csv_path = get_cache_dir() / "recommendations.csv"
            csv_fields = ["category", "name", "artist", "type", "year", "id"]

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=csv_fields)
                writer.writeheader()
                writer.writerows(all_items)

            output.insert(0, f"Full data: {csv_path}")
            output.insert(0, f"=== {len(all_items)} recommendations ===")

        return "\n".join(output) if output else "No recommendations available"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_heavy_rotation() -> str:
    """
    Get your heavy rotation - content you've been playing frequently.

    Returns: Count, CSV file path, and albums/playlists you play most often
    """
    try:
        headers = get_headers()
        # Note: heavy-rotation endpoint doesn't accept limit parameter
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

        # Write CSV
        csv_path = get_cache_dir() / "heavy_rotation.csv"
        csv_fields = ["name", "artist", "type", "track_count", "genre", "release_date", "date_added", "id", "artwork_url"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(item_data)

        # Build output
        count = len(item_data)
        output = [f"=== {count} items in heavy rotation ===", f"Full data: {csv_path}", ""]

        for item in item_data:
            year = item["release_date"][:4] if item["release_date"] else ""
            year_str = f" [{year}]" if year else ""
            tracks_str = f" ({item['track_count']} tracks)" if item["track_count"] else ""
            if item["artist"]:
                output.append(f"{item['name']} - {item['artist']}{tracks_str}{year_str} ({item['type']}) [ID: {item['id']}]")
            else:
                output.append(f"{item['name']}{tracks_str}{year_str} ({item['type']}) [ID: {item['id']}]")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_recently_added(limit: int = 50) -> str:
    """
    Get content recently added to your library.

    Args:
        limit: Number of items to return (default 50)

    Returns: Count, CSV file path, and recently added albums/songs/playlists
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

        # Write CSV
        csv_path = get_cache_dir() / "recently_added.csv"
        csv_fields = ["name", "artist", "type", "track_count", "genre", "release_date", "date_added", "id", "artwork_url"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(item_data)

        # Build output
        count = len(item_data)
        output = [f"=== {count} recently added items ===", f"Full data: {csv_path}", ""]

        for item in item_data:
            date_added = item["date_added"][:10] if item["date_added"] else ""
            date_str = f" [added {date_added}]" if date_added else ""
            tracks_str = f" ({item['track_count']} tracks)" if item["track_count"] else ""
            if item["artist"]:
                output.append(f"{item['name']} - {item['artist']}{tracks_str} ({item['type']}){date_str} [ID: {item['id']}]")
            else:
                output.append(f"{item['name']}{tracks_str} ({item['type']}){date_str} [ID: {item['id']}]")

        return "\n".join(output)

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
def rate_song(song_id: str, rating: str) -> str:
    """
    Rate a song by ID (love/dislike).

    Args:
        song_id: The catalog song ID (numeric, from search_catalog)
        rating: 'love' or 'dislike'

    Returns: Confirmation or error

    Note: Removing ratings (DELETE) is not supported by Apple's API.
    """
    success, msg = _rate_song_api(song_id, rating)
    if success:
        return f"Successfully set rating to '{rating}' for song {song_id}"
    return f"Error: {msg}"


@mcp.tool()
def love_track(track_name: str, artist: str = "") -> str:
    """
    Mark a track as loved (by name).

    On macOS uses AppleScript for direct library access.
    On other platforms searches library for catalog ID and uses API.

    Args:
        track_name: Name of the track
        artist: Optional artist name to disambiguate

    Returns: Confirmation message or error
    """
    # Try AppleScript first on macOS
    if APPLESCRIPT_AVAILABLE:
        success, result = asc.love_track(track_name, artist if artist else None)
        if success:
            return result
        # Fall through to API if AppleScript fails

    # API fallback: search library for catalog ID
    search_term = f"{track_name} {artist}".strip() if artist else track_name
    songs = _search_catalog_songs(search_term, limit=5)

    for song in songs:
        attrs = song.get("attributes", {})
        song_name = attrs.get("name", "")
        song_artist = attrs.get("artistName", "")
        if track_name.lower() in song_name.lower():
            if not artist or artist.lower() in song_artist.lower():
                success, msg = _rate_song_api(song.get("id"), "love")
                if success:
                    return f"Loved: {song_name} by {song_artist}"
                return f"Error: {msg}"

    return f"Track not found: {track_name}"


@mcp.tool()
def dislike_track(track_name: str, artist: str = "") -> str:
    """
    Mark a track as disliked (by name).

    On macOS uses AppleScript for direct library access.
    On other platforms searches library for catalog ID and uses API.

    Args:
        track_name: Name of the track
        artist: Optional artist name to disambiguate

    Returns: Confirmation message or error
    """
    # Try AppleScript first on macOS
    if APPLESCRIPT_AVAILABLE:
        success, result = asc.dislike_track(track_name, artist if artist else None)
        if success:
            return result
        # Fall through to API if AppleScript fails

    # API fallback: search catalog for ID
    search_term = f"{track_name} {artist}".strip() if artist else track_name
    songs = _search_catalog_songs(search_term, limit=5)

    for song in songs:
        attrs = song.get("attributes", {})
        song_name = attrs.get("name", "")
        song_artist = attrs.get("artistName", "")
        if track_name.lower() in song_name.lower():
            if not artist or artist.lower() in song_artist.lower():
                success, msg = _rate_song_api(song.get("id"), "dislike")
                if success:
                    return f"Disliked: {song_name} by {song_artist}"
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
def get_library_music_videos() -> str:
    """
    Get music videos saved in your personal library.

    Returns: List of music videos with their IDs
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/library/music-videos",
            headers=headers,
            params={"limit": 50},
        )
        response.raise_for_status()
        data = response.json()

        output = ["=== Library Music Videos ==="]
        for video in data.get("data", []):
            attrs = video.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "Unknown")
            video_id = video.get("id")
            output.append(f"{name} - {artist} [library ID: {video_id}]")

        return "\n".join(output) if len(output) > 1 else "No music videos in library"

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
def clear_cache(days_old: int = 0) -> str:
    """
    Clear cached CSV files from the export directory.

    Args:
        days_old: Only delete files older than this many days (0 = delete all)

    Returns: Summary of deleted files and space reclaimed
    """
    try:
        cache_dir = get_cache_dir()
        if not cache_dir.exists():
            return "Cache directory doesn't exist"

        csv_files = list(cache_dir.glob("*.csv"))
        if not csv_files:
            return "No CSV files in cache"

        now = time.time()
        cutoff = now - (days_old * 86400) if days_old > 0 else now + 1  # +1 to delete all

        deleted = []
        kept = []
        total_size = 0

        for f in csv_files:
            file_age_days = (now - f.stat().st_mtime) / 86400
            file_size = f.stat().st_size

            if days_old == 0 or f.stat().st_mtime < cutoff:
                deleted.append(f.name)
                total_size += file_size
                f.unlink()
            else:
                kept.append(f.name)

        # Format size
        if total_size < 1024:
            size_str = f"{total_size} bytes"
        elif total_size < 1024 * 1024:
            size_str = f"{total_size / 1024:.1f} KB"
        else:
            size_str = f"{total_size / (1024 * 1024):.1f} MB"

        output = [f"=== Cache cleanup ==="]
        output.append(f"Deleted: {len(deleted)} files ({size_str})")

        if kept:
            output.append(f"Kept: {len(kept)} files (newer than {days_old} days)")

        if deleted:
            output.append("")
            output.append("Deleted files:")
            for f in deleted[:20]:  # Limit display
                output.append(f"  - {f}")
            if len(deleted) > 20:
                output.append(f"  ... and {len(deleted) - 20} more")

        return "\n".join(output)

    except Exception as e:
        return f"Error clearing cache: {str(e)}"


@mcp.tool()
def get_cache_info() -> str:
    """
    Get information about cached CSV files.

    Returns: List of cached files with sizes and ages
    """
    try:
        cache_dir = get_cache_dir()
        if not cache_dir.exists():
            return "Cache directory doesn't exist"

        csv_files = sorted(cache_dir.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not csv_files:
            return "No CSV files in cache"

        now = time.time()
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

            if age_days < 1:
                age_str = f"{age_days * 24:.0f}h ago"
            else:
                age_str = f"{age_days:.0f}d ago"

            output.append(f"{f.name} ({size_str}, {age_str})")

        # Total
        if total_size < 1024 * 1024:
            total_str = f"{total_size / 1024:.1f} KB"
        else:
            total_str = f"{total_size / (1024 * 1024):.1f} MB"

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
                    # Wait for iCloud sync, then play (up to ~7 seconds)
                    time.sleep(1)  # Initial delay for sync to start
                    for attempt in range(30):
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
    def set_volume(volume: int) -> str:
        """Set the Music app volume (macOS only).

        Args:
            volume: Volume level 0-100

        Returns: Confirmation message
        """
        volume = max(0, min(100, volume))
        success, result = asc.set_volume(volume)
        if success:
            return f"Volume set to {volume}"
        return f"Error: {result}"

    @mcp.tool()
    def get_volume_and_playback() -> str:
        """Get current volume and playback settings (macOS only).

        Returns: Volume, shuffle, repeat, and player state
        """
        success, stats = asc.get_library_stats()
        if not success:
            return f"Error: {stats}"

        return (
            f"Player state: {stats['player_state']}\n"
            f"Volume: {stats['volume']}\n"
            f"Shuffle: {'on' if stats['shuffle'] else 'off'}\n"
            f"Repeat: {stats['repeat']}"
        )

    @mcp.tool()
    def set_shuffle(enabled: bool) -> str:
        """Turn shuffle on or off (macOS only).

        Args:
            enabled: True to enable shuffle, False to disable

        Returns: Confirmation message
        """
        success, result = asc.set_shuffle(enabled)
        if success:
            return f"Shuffle {'enabled' if enabled else 'disabled'}"
        return f"Error: {result}"

    @mcp.tool()
    def set_repeat(mode: str) -> str:
        """Set repeat mode (macOS only).

        Args:
            mode: One of: off, one (repeat current track), all (repeat playlist)

        Returns: Confirmation message
        """
        success, result = asc.set_repeat(mode.lower())
        if success:
            return f"Repeat mode set to: {mode}"
        return f"Error: {result}"

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
    def get_track_rating(track_name: str, artist: str = "") -> str:
        """Get the star rating of a track (macOS only).

        Args:
            track_name: Name of the track
            artist: Optional artist name to disambiguate

        Returns: Rating as stars (0-5) and raw value (0-100)
        """
        success, rating = asc.get_rating(track_name, artist if artist else None)
        if success:
            stars = rating // 20
            return f"{track_name}: {'★' * stars}{'☆' * (5 - stars)} ({rating}/100)"
        return f"Error: {rating}"

    @mcp.tool()
    def set_track_rating(track_name: str, stars: int, artist: str = "") -> str:
        """Set the star rating of a track (macOS only).

        Args:
            track_name: Name of the track
            stars: Rating 0-5 stars
            artist: Optional artist name to disambiguate

        Returns: Confirmation message or error
        """
        rating = max(0, min(5, stars)) * 20  # Convert stars to 0-100
        success, result = asc.set_rating(track_name, rating, artist if artist else None)
        if success:
            return f"Set {track_name} to {'★' * stars}{'☆' * (5 - stars)}"
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
    def get_airplay_devices() -> str:
        """Get list of available AirPlay devices (macOS only).

        Returns: List of AirPlay device names
        """
        success, devices = asc.get_airplay_devices()
        if not success:
            return f"Error: {devices}"

        if not devices:
            return "No AirPlay devices found"

        return f"AirPlay devices ({len(devices)}):\n" + "\n".join(f"  - {d}" for d in devices)

    @mcp.tool()
    def set_airplay_device(device_name: str) -> str:
        """Switch audio output to an AirPlay device (macOS only).

        Args:
            device_name: Name of the AirPlay device (partial match OK)

        Returns: Confirmation or error
        """
        success, result = asc.set_airplay_device(device_name)
        if success:
            return result
        return f"Error: {result}"

    @mcp.tool()
    def local_search_library(query: str, search_type: str = "all") -> str:
        """Search your local library via AppleScript (macOS only).

        This uses AppleScript to search directly, which can be faster than the API
        for local library searches. Limited to 100 results.

        Args:
            query: Search query
            search_type: Type of search - all, artists, albums, or songs

        Returns: Search results with track details
        """
        success, results = asc.search_library(query, search_type)
        if not success:
            return f"Error: {results}"

        if not results:
            return f"No results found for '{query}'"

        # Format results
        lines = [f"=== {len(results)} results for '{query}' (via AppleScript) ===\n"]
        for t in results:
            duration = t.get("duration", "")
            genre = t.get("genre", "")
            year = t.get("year", "")

            line = f"{t['name']} - {t['artist']}"
            if duration:
                line += f" ({duration})"
            if t.get("album"):
                line += f" {t['album']}"
            if year:
                line += f" [{year}]"
            if genre:
                line += f" {genre}"
            line += f" {t['id']}"
            lines.append(line)

        return "\n".join(lines)


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
