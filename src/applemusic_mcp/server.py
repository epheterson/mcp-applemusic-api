"""MCP server for Apple Music API - Cross-platform playlist and library management."""

import csv
import json
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

from .auth import get_developer_token, get_user_token, get_config_dir

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
def get_playlist_tracks(playlist_id: str, include_extras: bool = False) -> str:
    """
    Get all tracks in a playlist.

    Args:
        playlist_id: The playlist ID (get from get_library_playlists)
        include_extras: Include extra metadata in CSV (track/disc numbers, artwork, etc.)

    Returns: Track count, CSV file path, and track listing (tiered based on size)
    """
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

        # Write CSV using helper
        csv_path = get_cache_dir() / f"playlist_{playlist_id.replace('.', '_')}.csv"
        write_tracks_csv(track_data, csv_path, include_extras)

        # Build output
        count = len(track_data)
        formatted_lines, tier = format_track_list(track_data)
        output = [f"=== {count} tracks ({tier} format) ===", f"Full data: {csv_path}", ""]
        output.extend(formatted_lines)

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


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
def add_to_playlist(playlist_id: str, song_ids: str) -> str:
    """
    Add songs to a library playlist.
    Only works for playlists created via API (editable=true).

    Args:
        playlist_id: The playlist ID (get from get_library_playlists)
        song_ids: Comma-separated LIBRARY song IDs (get from search_library, NOT catalog IDs)

    Returns: Confirmation or error message
    """
    try:
        headers = get_headers()

        ids = [s.strip() for s in song_ids.split(",") if s.strip()]
        if not ids:
            return "No song IDs provided"

        tracks = [{"id": sid, "type": "library-songs"} for sid in ids]
        body = {"data": tracks}

        response = requests.post(
            f"{BASE_URL}/me/library/playlists/{playlist_id}/tracks",
            headers=headers,
            json=body,
        )

        if response.status_code == 204:
            return f"Successfully added {len(ids)} track(s) to playlist"
        elif response.status_code == 403:
            return "Error: Cannot edit this playlist (not API-created or permission denied)"
        elif response.status_code == 500:
            return "Error: Cannot edit this playlist (likely not API-created)"
        else:
            response.raise_for_status()
            return f"Added tracks (status: {response.status_code})"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


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
    try:
        headers = get_headers()

        ids = [s.strip() for s in catalog_ids.split(",") if s.strip()]
        if not ids:
            return "No catalog IDs provided"

        params = {"ids[songs]": ",".join(ids)}

        response = requests.post(
            f"{BASE_URL}/me/library",
            headers=headers,
            params=params,
        )

        if response.status_code == 202:
            return f"Successfully added {len(ids)} song(s) to your library. Use search_library to find their library IDs."
        else:
            response.raise_for_status()
            return f"Added to library (status: {response.status_code})"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


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
    Rate a song (love/dislike). Use catalog song IDs (from search_catalog).

    Args:
        song_id: The catalog song ID (numeric, from search_catalog)
        rating: 'love' or 'dislike'

    Returns: Confirmation or error

    Note: Removing ratings (DELETE) is not supported by Apple's API.
    """
    try:
        headers = get_headers()

        rating_value = {"love": 1, "dislike": -1}.get(rating.lower())
        if rating_value is None:
            return "Error: rating must be 'love' or 'dislike'"

        body = {
            "type": "rating",
            "attributes": {"value": rating_value}
        }
        response = requests.put(
            f"{BASE_URL}/me/ratings/songs/{song_id}",
            headers=headers,
            json=body,
        )

        if response.status_code in [200, 201]:
            return f"Successfully set rating to '{rating}' for song {song_id}"
        elif response.status_code == 204:
            return f"Rating already set to '{rating}'"
        else:
            response.raise_for_status()
            return f"Rating set (status: {response.status_code})"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


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


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
