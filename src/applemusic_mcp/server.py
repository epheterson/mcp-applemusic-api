"""MCP server for Apple Music API - Cross-platform playlist and library management."""

import csv
import json
import time
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

from .auth import get_developer_token, get_user_token, get_config_dir


def get_cache_dir() -> Path:
    """Get cache directory for CSV exports."""
    cache_dir = Path.home() / ".cache" / "applemusic-mcp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def format_duration(ms: int) -> str:
    """Format milliseconds as mm:ss.mmm"""
    if not ms:
        return ""
    total_seconds = ms / 1000
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:06.3f}"

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
def get_playlist_tracks(playlist_id: str) -> str:
    """
    Get all tracks in a playlist.

    Args:
        playlist_id: The playlist ID (get from get_library_playlists)

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

        # Extract full track data
        track_data = []
        for track in all_tracks:
            attrs = track.get("attributes", {})
            play_params = attrs.get("playParams", {})
            genres = attrs.get("genreNames", [])

            track_data.append({
                "id": track.get("id", ""),
                "catalog_id": play_params.get("catalogId", ""),
                "name": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "album": attrs.get("albumName", ""),
                "duration_ms": attrs.get("durationInMillis", 0),
                "duration": format_duration(attrs.get("durationInMillis", 0)),
                "track_number": attrs.get("trackNumber", ""),
                "disc_number": attrs.get("discNumber", ""),
                "genre": genres[0] if genres else "",
                "genres": ", ".join(genres),
                "release_date": attrs.get("releaseDate", ""),
                "has_lyrics": attrs.get("hasLyrics", False),
                "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
            })

        # Always write CSV with full data
        csv_path = get_cache_dir() / f"playlist_{playlist_id.replace('.', '_')}.csv"
        csv_fields = ["name", "duration", "artist", "album", "track_number", "disc_number",
                      "release_date", "genre", "genres", "has_lyrics", "id", "catalog_id", "artwork_url"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(track_data)

        # Build output with count header
        count = len(track_data)
        output = [f"=== {count} tracks ===", f"Full data: {csv_path}", ""]

        # Tiered display based on track count
        if count <= 120:
            # Full format: Name (duration) - Artist | Album [Year] Genre
            for t in track_data:
                year = t["release_date"][:4] if t["release_date"] else ""
                year_str = f" [{year}]" if year else ""
                genre_str = f" {t['genre']}" if t["genre"] else ""
                output.append(f"{t['name']} ({t['duration']}) - {t['artist']} | {t['album']}{year_str}{genre_str} (ID: {t['id']})")
        elif count <= 350:
            # Compact: Name - Artist (ID)
            for t in track_data:
                name = t["name"][:45] + "..." if len(t["name"]) > 45 else t["name"]
                artist = t["artist"][:25] + "..." if len(t["artist"]) > 25 else t["artist"]
                output.append(f"{name} - {artist} ({t['id']})")
        else:
            # Minimal: truncated name + ID only
            for t in track_data:
                name = t["name"][:30] + "..." if len(t["name"]) > 30 else t["name"]
                output.append(f"{name} {t['id']}")

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
def search_library(query: str, limit: int = 25) -> str:
    """
    Search your personal Apple Music library for songs.

    Args:
        query: Search term
        limit: Max results to return (default 25)

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

        # Extract full song data
        song_data = []
        for song in songs:
            attrs = song.get("attributes", {})
            play_params = attrs.get("playParams", {})
            genres = attrs.get("genreNames", [])

            song_data.append({
                "id": song.get("id", ""),
                "catalog_id": play_params.get("catalogId", ""),
                "name": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "album": attrs.get("albumName", ""),
                "duration_ms": attrs.get("durationInMillis", 0),
                "duration": format_duration(attrs.get("durationInMillis", 0)),
                "track_number": attrs.get("trackNumber", ""),
                "disc_number": attrs.get("discNumber", ""),
                "genre": genres[0] if genres else "",
                "genres": ", ".join(genres),
                "release_date": attrs.get("releaseDate", ""),
                "has_lyrics": attrs.get("hasLyrics", False),
                "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
            })

        # Write CSV with full data
        safe_query = "".join(c if c.isalnum() else "_" for c in query)[:30]
        csv_path = get_cache_dir() / f"search_library_{safe_query}.csv"
        csv_fields = ["name", "duration", "artist", "album", "track_number", "disc_number",
                      "release_date", "genre", "genres", "has_lyrics", "id", "catalog_id", "artwork_url"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(song_data)

        # Build output
        count = len(song_data)
        output = [f"=== {count} results for '{query}' ===", f"Full data: {csv_path}", ""]

        # Display with full metadata (search results are always small)
        for s in song_data:
            year = s["release_date"][:4] if s["release_date"] else ""
            year_str = f" [{year}]" if year else ""
            output.append(f"{s['name']} ({s['duration']}) - {s['artist']} | {s['album']}{year_str} [library ID: {s['id']}]")

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
def get_recently_played(limit: int = 30) -> str:
    """
    Get recently played tracks from your Apple Music history.

    Args:
        limit: Number of tracks to return (default 30, max 50)

    Returns: Recently played tracks with full metadata and CSV export
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

        # Extract full track data
        track_data = []
        for track in all_tracks:
            attrs = track.get("attributes", {})
            genres = attrs.get("genreNames", [])
            previews = attrs.get("previews", [])
            preview_url = previews[0].get("url", "") if previews else ""

            track_data.append({
                "id": track.get("id", ""),
                "name": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "album": attrs.get("albumName", ""),
                "composer": attrs.get("composerName", ""),
                "duration_ms": attrs.get("durationInMillis", 0),
                "duration": format_duration(attrs.get("durationInMillis", 0)),
                "track_number": attrs.get("trackNumber", ""),
                "disc_number": attrs.get("discNumber", ""),
                "genre": genres[0] if genres else "",
                "genres": ", ".join(genres),
                "release_date": attrs.get("releaseDate", ""),
                "isrc": attrs.get("isrc", ""),
                "is_apple_digital_master": attrs.get("isAppleDigitalMaster", False),
                "has_lyrics": attrs.get("hasLyrics", False),
                "content_rating": attrs.get("contentRating", ""),
                "url": attrs.get("url", ""),
                "preview_url": preview_url,
                "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
            })

        # Write CSV with full data
        csv_path = get_cache_dir() / "recently_played.csv"
        csv_fields = ["name", "duration", "artist", "album", "composer", "track_number", "disc_number",
                      "release_date", "genre", "genres", "isrc", "is_apple_digital_master", "has_lyrics",
                      "content_rating", "id", "url", "preview_url", "artwork_url"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(track_data)

        # Build output
        count = len(track_data)
        output = [f"=== {count} recently played tracks ===", f"Full data: {csv_path}", ""]

        # Display with metadata
        for t in track_data:
            year = t["release_date"][:4] if t["release_date"] else ""
            year_str = f" [{year}]" if year else ""
            composer_str = f" (by {t['composer']})" if t["composer"] else ""
            output.append(f"{t['name']} ({t['duration']}) - {t['artist']} | {t['album']}{year_str}{composer_str}")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ CATALOG SEARCH ============


@mcp.tool()
def search_catalog(query: str, types: str = "songs", limit: int = 15) -> str:
    """
    Search the Apple Music catalog.

    Args:
        query: Search term
        types: Comma-separated types (songs, albums, artists, playlists)
        limit: Max results per type (default 15)

    Returns: Search results with catalog IDs and full metadata (use add_to_library to add songs to your library first)
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

            # Extract full song data
            song_data = []
            for song in songs:
                attrs = song.get("attributes", {})
                genres = attrs.get("genreNames", [])
                previews = attrs.get("previews", [])
                preview_url = previews[0].get("url", "") if previews else ""

                song_data.append({
                    "id": song.get("id", ""),
                    "name": attrs.get("name", ""),
                    "artist": attrs.get("artistName", ""),
                    "album": attrs.get("albumName", ""),
                    "composer": attrs.get("composerName", ""),
                    "duration_ms": attrs.get("durationInMillis", 0),
                    "duration": format_duration(attrs.get("durationInMillis", 0)),
                    "track_number": attrs.get("trackNumber", ""),
                    "disc_number": attrs.get("discNumber", ""),
                    "genre": genres[0] if genres else "",
                    "genres": ", ".join(genres),
                    "release_date": attrs.get("releaseDate", ""),
                    "isrc": attrs.get("isrc", ""),
                    "is_explicit": attrs.get("contentRating") == "explicit",
                    "is_apple_digital_master": attrs.get("isAppleDigitalMaster", False),
                    "has_lyrics": attrs.get("hasLyrics", False),
                    "url": attrs.get("url", ""),
                    "preview_url": preview_url,
                    "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
                })

            # Write CSV with full data
            if song_data:
                safe_query = "".join(c if c.isalnum() else "_" for c in query)[:30]
                csv_path = get_cache_dir() / f"search_catalog_{safe_query}.csv"
                csv_fields = ["name", "duration", "artist", "album", "composer", "track_number", "disc_number",
                              "release_date", "genre", "genres", "isrc", "is_explicit", "is_apple_digital_master",
                              "has_lyrics", "id", "url", "preview_url", "artwork_url"]

                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=csv_fields)
                    writer.writeheader()
                    writer.writerows(song_data)

                output.append(f"=== {len(song_data)} Songs (use add_to_library with these IDs) ===")
                output.append(f"Full data: {csv_path}")
                output.append("")

                for s in song_data:
                    year = s["release_date"][:4] if s["release_date"] else ""
                    year_str = f" [{year}]" if year else ""
                    explicit_str = " [E]" if s["is_explicit"] else ""
                    output.append(f"  {s['name']} ({s['duration']}) - {s['artist']} | {s['album']}{year_str}{explicit_str} [catalog ID: {s['id']}]")

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
def get_album_tracks(album_id: str) -> str:
    """
    Get all tracks from an album.
    Works with both library album IDs (l.xxx from get_library_albums)
    and catalog album IDs (numeric from search_catalog).

    Args:
        album_id: Library album ID (l.xxx) or catalog album ID (numeric)

    Returns: List of tracks with their IDs
    """
    try:
        headers = get_headers()

        # Detect if it's a library or catalog ID
        if album_id.startswith("l."):
            url = f"{BASE_URL}/me/library/albums/{album_id}/tracks"
            id_type = "library"
        else:
            url = f"{BASE_URL}/catalog/{STOREFRONT}/albums/{album_id}/tracks"
            id_type = "catalog"

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

        output = [f"=== Album Tracks ({id_type} IDs) ==="]
        for track in data.get("data", []):
            attrs = track.get("attributes", {})
            name = attrs.get("name", "Unknown")
            track_num = attrs.get("trackNumber", "?")
            duration_ms = attrs.get("durationInMillis", 0)
            duration = f"{duration_ms // 60000}:{(duration_ms // 1000) % 60:02d}"
            track_id = track.get("id")
            output.append(f"  {track_num}. {name} [{duration}] ({id_type} ID: {track_id})")

        return "\n".join(output) if len(output) > 1 else "No tracks found"

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
                output.append(f"{a['name']} - {a['artist']} ({a['track_count']} tracks){year_str} [ID: {a['id']}]")
        else:
            for a in album_data:
                name = a["name"][:40] + "..." if len(a["name"]) > 40 else a["name"]
                artist = a["artist"][:20] + "..." if len(a["artist"]) > 20 else a["artist"]
                output.append(f"{name} - {artist} ({a['id']})")

        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_library_artists() -> str:
    """
    Get all artists in your Apple Music library.

    Returns: List of artists
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/library/artists",
            headers=headers,
            params={"limit": 100},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        for artist in data.get("data", []):
            attrs = artist.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist_id = artist.get("id")
            output.append(f"{name} [library ID: {artist_id}]")

        return "\n".join(output) if output else "No artists in library"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_library_songs(limit: int = 100) -> str:
    """
    Get songs from your Apple Music library (not a search, just browse).

    Args:
        limit: Number of songs to return (default 100, use 0 for all songs)

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

        # Extract full song data
        song_data = []
        for song in all_songs:
            attrs = song.get("attributes", {})
            play_params = attrs.get("playParams", {})
            genres = attrs.get("genreNames", [])

            song_data.append({
                "id": song.get("id", ""),
                "catalog_id": play_params.get("catalogId", ""),
                "name": attrs.get("name", ""),
                "artist": attrs.get("artistName", ""),
                "album": attrs.get("albumName", ""),
                "duration_ms": attrs.get("durationInMillis", 0),
                "duration": format_duration(attrs.get("durationInMillis", 0)),
                "track_number": attrs.get("trackNumber", ""),
                "disc_number": attrs.get("discNumber", ""),
                "genre": genres[0] if genres else "",
                "genres": ", ".join(genres),
                "release_date": attrs.get("releaseDate", ""),
                "has_lyrics": attrs.get("hasLyrics", False),
                "artwork_url": attrs.get("artwork", {}).get("url", "").replace("{w}x{h}", "500x500"),
            })

        # Write CSV with full data
        csv_path = get_cache_dir() / "library_songs.csv"
        csv_fields = ["name", "duration", "artist", "album", "track_number", "disc_number",
                      "release_date", "genre", "genres", "has_lyrics", "id", "catalog_id", "artwork_url"]

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            writer.writerows(song_data)

        # Build output
        count = len(song_data)
        output = [f"=== {count} songs ===", f"Full data: {csv_path}", ""]

        # Tiered display
        if count <= 120:
            for s in song_data:
                year = s["release_date"][:4] if s["release_date"] else ""
                year_str = f" [{year}]" if year else ""
                output.append(f"{s['name']} ({s['duration']}) - {s['artist']} | {s['album']}{year_str} (ID: {s['id']})")
        elif count <= 350:
            for s in song_data:
                name = s["name"][:45] + "..." if len(s["name"]) > 45 else s["name"]
                artist = s["artist"][:25] + "..." if len(s["artist"]) > 25 else s["artist"]
                output.append(f"{name} - {artist} ({s['id']})")
        else:
            for s in song_data:
                name = s["name"][:30] + "..." if len(s["name"]) > 30 else s["name"]
                output.append(f"{name} {s['id']}")

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

    Returns: Recommended albums, playlists, and stations
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
        for rec in data.get("data", []):
            rec_type = rec.get("type", "unknown")
            attrs = rec.get("attributes", {})
            title = attrs.get("title", {}).get("stringForDisplay", "Recommendation")

            output.append(f"=== {title} ===")

            # Get the recommended items
            relationships = rec.get("relationships", {})
            contents = relationships.get("contents", {}).get("data", [])

            for item in contents[:5]:  # Limit items per recommendation
                item_attrs = item.get("attributes", {})
                name = item_attrs.get("name", "Unknown")
                artist = item_attrs.get("artistName", "")
                item_type = item.get("type", "")
                if artist:
                    output.append(f"  {name} - {artist} ({item_type})")
                else:
                    output.append(f"  {name} ({item_type})")

        return "\n".join(output) if output else "No recommendations available"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_heavy_rotation() -> str:
    """
    Get your heavy rotation - content you've been playing frequently.

    Returns: Albums and playlists you play most often
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/history/heavy-rotation",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        output = ["=== Heavy Rotation (Your Most Played) ==="]
        for item in data.get("data", []):
            attrs = item.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "")
            item_type = item.get("type", "").replace("library-", "").replace("-", " ")

            if artist:
                output.append(f"{name} - {artist} ({item_type})")
            else:
                output.append(f"{name} ({item_type})")

        return "\n".join(output) if len(output) > 1 else "No heavy rotation data"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_recently_added() -> str:
    """
    Get content recently added to your library.

    Returns: Recently added albums, songs, and playlists
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/library/recently-added",
            headers=headers,
            params={"limit": 25},
        )
        response.raise_for_status()
        data = response.json()

        output = ["=== Recently Added to Library ==="]
        for item in data.get("data", []):
            attrs = item.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "")
            item_type = item.get("type", "").replace("library-", "")
            item_id = item.get("id")

            if artist:
                output.append(f"{name} - {artist} ({item_type}) [ID: {item_id}]")
            else:
                output.append(f"{name} ({item_type}) [ID: {item_id}]")

        return "\n".join(output) if len(output) > 1 else "No recently added content"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_recently_played_tracks() -> str:
    """
    Get individual tracks you've played recently (not just albums/playlists).

    Returns: Recently played songs with details
    """
    try:
        headers = get_headers()
        all_tracks = []

        # API limits to 10 per request, max 50 total
        for offset in range(0, 50, 10):
            response = requests.get(
                f"{BASE_URL}/me/recent/played/tracks",
                headers=headers,
                params={"limit": 10, "offset": offset},
            )
            if response.status_code != 200:
                break
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)

        output = ["=== Recently Played Tracks ==="]
        for track in all_tracks:
            attrs = track.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "Unknown")
            album = attrs.get("albumName", "")
            output.append(f"{name} - {artist}" + (f" ({album})" if album else ""))

        return "\n".join(output) if len(output) > 1 else "No recently played tracks"

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
        output = [
            f"Title: {attrs.get('name', 'Unknown')}",
            f"Artist: {attrs.get('artistName', 'Unknown')}",
            f"Album: {attrs.get('albumName', 'Unknown')}",
            f"Genre: {', '.join(attrs.get('genreNames', ['Unknown']))}",
            f"Duration: {attrs.get('durationInMillis', 0) // 60000}:{(attrs.get('durationInMillis', 0) // 1000) % 60:02d}",
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
            duration_ms = attrs.get("durationInMillis", 0)
            duration = f"{duration_ms // 60000}:{(duration_ms // 1000) % 60:02d}"
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
