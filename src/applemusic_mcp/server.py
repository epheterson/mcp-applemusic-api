"""MCP server for Apple Music API - Cross-platform playlist and library management."""

import json
import time

import requests
from mcp.server.fastmcp import FastMCP

from .auth import get_developer_token, get_user_token, get_config_dir

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
    Returns playlist names, IDs, and whether they're editable.
    Only API-created playlists can be edited.
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/library/playlists", headers=headers, params={"limit": 100}
        )
        response.raise_for_status()
        data = response.json()

        output = []

        # Check for token expiration warning
        warning = get_token_expiration_warning()
        if warning:
            output.append(warning)
            output.append("")

        for playlist in data.get("data", []):
            attrs = playlist.get("attributes", {})
            name = attrs.get("name", "Unknown")
            can_edit = attrs.get("canEdit", False)
            playlist_id = playlist.get("id")
            edit_status = "editable" if can_edit else "read-only"
            output.append(f"{name} (ID: {playlist_id}, {edit_status})")

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

    Returns: List of tracks with their library IDs
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
            response.raise_for_status()
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)
            offset += 100

        output = []
        for track in all_tracks:
            attrs = track.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "Unknown")
            track_id = track.get("id")
            output.append(f"{name} - {artist} (library ID: {track_id})")

        return "\n".join(output) if output else "Playlist is empty"

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
def update_playlist(playlist_id: str, name: str = "", description: str = "") -> str:
    """
    Update a playlist's name and/or description.
    Only works for playlists created via API (editable=true).

    Args:
        playlist_id: The playlist ID
        name: New name (optional)
        description: New description (optional)

    Returns: Confirmation or error message
    """
    try:
        headers = get_headers()

        attrs = {}
        if name:
            attrs["name"] = name
        if description:
            attrs["description"] = description

        if not attrs:
            return "Error: Provide at least a name or description to update"

        body = {"attributes": attrs}

        response = requests.patch(
            f"{BASE_URL}/me/library/playlists/{playlist_id}",
            headers=headers,
            json=body,
        )

        if response.status_code == 204:
            return "Successfully updated playlist"
        elif response.status_code == 403:
            return "Error: Cannot edit this playlist (not API-created or permission denied)"
        else:
            response.raise_for_status()
            return f"Updated playlist (status: {response.status_code})"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def delete_playlist(playlist_id: str) -> str:
    """
    Delete a playlist from your library.
    Only works for playlists created via API (editable=true).

    Args:
        playlist_id: The playlist ID to delete

    Returns: Confirmation or error message
    """
    try:
        headers = get_headers()

        response = requests.delete(
            f"{BASE_URL}/me/library/playlists/{playlist_id}",
            headers=headers,
        )

        if response.status_code == 204:
            return f"Successfully deleted playlist {playlist_id}"
        elif response.status_code == 403:
            return "Error: Cannot delete this playlist (not API-created or permission denied)"
        elif response.status_code == 404:
            return "Error: Playlist not found"
        else:
            response.raise_for_status()
            return f"Deleted playlist (status: {response.status_code})"

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
            response.raise_for_status()
            tracks = response.json().get("data", [])
            if not tracks:
                break
            all_tracks.extend(tracks)
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
def search_library(query: str) -> str:
    """
    Search your personal Apple Music library for songs.

    Args:
        query: Search term

    Returns: Songs from your library with library IDs (these can be added to playlists)
    """
    try:
        headers = get_headers()

        response = requests.get(
            f"{BASE_URL}/me/library/search",
            headers=headers,
            params={"term": query, "types": "library-songs", "limit": 25},
        )
        response.raise_for_status()
        data = response.json()

        songs = data.get("results", {}).get("library-songs", {}).get("data", [])

        output = []
        for song in songs:
            attrs = song.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "Unknown")
            album = attrs.get("albumName", "")
            song_id = song.get("id")
            if album:
                output.append(f"{name} - {artist} ({album}) [library ID: {song_id}]")
            else:
                output.append(f"{name} - {artist} [library ID: {song_id}]")

        return "\n".join(output) if output else "No songs found"

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
def get_recently_played() -> str:
    """
    Get recently played tracks from your Apple Music history.

    Returns: List of recently played tracks
    """
    try:
        headers = get_headers()

        response = requests.get(
            f"{BASE_URL}/me/recent/played/tracks",
            headers=headers,
            params={"limit": 20},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        for track in data.get("data", []):
            attrs = track.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "Unknown")
            album = attrs.get("albumName", "Unknown")
            output.append(f"{name} - {artist} ({album})")

        return "\n".join(output) if output else "No recently played tracks"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ CATALOG SEARCH ============


@mcp.tool()
def search_catalog(query: str, types: str = "songs") -> str:
    """
    Search the Apple Music catalog.

    Args:
        query: Search term
        types: Comma-separated types (songs, albums, artists, playlists)

    Returns: Search results with catalog IDs (use add_to_library to add these to your library first)
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/search",
            headers=headers,
            params={"term": query, "types": types, "limit": 10},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        results = data.get("results", {})

        if "songs" in results:
            output.append("=== Songs (use add_to_library with these IDs) ===")
            for song in results["songs"].get("data", []):
                attrs = song.get("attributes", {})
                name = attrs.get("name", "Unknown")
                artist = attrs.get("artistName", "Unknown")
                song_id = song.get("id")
                output.append(f"  {name} - {artist} [catalog ID: {song_id}]")

        if "albums" in results:
            output.append("=== Albums ===")
            for album in results["albums"].get("data", []):
                attrs = album.get("attributes", {})
                name = attrs.get("name", "Unknown")
                artist = attrs.get("artistName", "Unknown")
                album_id = album.get("id")
                output.append(f"  {name} - {artist} [catalog ID: {album_id}]")

        if "artists" in results:
            output.append("=== Artists ===")
            for artist in results["artists"].get("data", []):
                attrs = artist.get("attributes", {})
                name = attrs.get("name", "Unknown")
                output.append(f"  {name}")

        return "\n".join(output) if output else "No results found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def get_album_tracks(album_id: str) -> str:
    """
    Get all tracks from an album.
    Use search_catalog with types='albums' to find album IDs.

    Args:
        album_id: Catalog album ID

    Returns: List of tracks with their catalog IDs
    """
    try:
        headers = get_headers()

        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/albums/{album_id}/tracks",
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

        output = ["=== Album Tracks (use add_to_library with these IDs) ==="]
        for track in data.get("data", []):
            attrs = track.get("attributes", {})
            name = attrs.get("name", "Unknown")
            track_num = attrs.get("trackNumber", "?")
            duration_ms = attrs.get("durationInMillis", 0)
            duration = f"{duration_ms // 60000}:{(duration_ms // 1000) % 60:02d}"
            track_id = track.get("id")
            output.append(f"  {track_num}. {name} [{duration}] (catalog ID: {track_id})")

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

    Returns: List of albums with artist names
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/library/albums",
            headers=headers,
            params={"limit": 100},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        for album in data.get("data", []):
            attrs = album.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "Unknown")
            track_count = attrs.get("trackCount", 0)
            album_id = album.get("id")
            output.append(f"{name} - {artist} ({track_count} tracks) [library ID: {album_id}]")

        return "\n".join(output) if output else "No albums in library"

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
def get_library_songs(limit: int = 50) -> str:
    """
    Get songs from your Apple Music library (not a search, just browse).

    Args:
        limit: Number of songs to return (default 50, max 100)

    Returns: List of songs with library IDs
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/library/songs",
            headers=headers,
            params={"limit": min(limit, 100)},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        for song in data.get("data", []):
            attrs = song.get("attributes", {})
            name = attrs.get("name", "Unknown")
            artist = attrs.get("artistName", "Unknown")
            album = attrs.get("albumName", "")
            song_id = song.get("id")
            if album:
                output.append(f"{name} - {artist} ({album}) [library ID: {song_id}]")
            else:
                output.append(f"{name} - {artist} [library ID: {song_id}]")

        return "\n".join(output) if output else "No songs in library"

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
            params={"limit": 20},
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
def get_stations() -> str:
    """
    Get your Apple Music radio stations.

    Returns: List of your stations
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/library/stations",
            headers=headers,
            params={"limit": 50},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        for station in data.get("data", []):
            attrs = station.get("attributes", {})
            name = attrs.get("name", "Unknown")
            station_id = station.get("id")
            output.append(f"{name} [ID: {station_id}]")

        return "\n".join(output) if output else "No stations found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


# ============ RATINGS ============


@mcp.tool()
def get_favorite_songs() -> str:
    """
    Get songs you've marked as favorites (loved).

    Returns: List of your favorite/loved songs
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/me/ratings/songs",
            headers=headers,
            params={"limit": 50},
        )
        response.raise_for_status()
        data = response.json()

        output = ["=== Your Favorite Songs ==="]
        for rating in data.get("data", []):
            attrs = rating.get("attributes", {})
            value = attrs.get("value", 0)
            if value > 0:  # Loved
                # Get the song details from relationships
                song_id = rating.get("id", "")
                output.append(f"Loved song ID: {song_id}")

        return "\n".join(output) if len(output) > 1 else "No favorite songs found"

    except requests.exceptions.RequestException as e:
        return f"API Error: {str(e)}"
    except (FileNotFoundError, ValueError) as e:
        return str(e)


@mcp.tool()
def rate_song(song_id: str, rating: str) -> str:
    """
    Rate a song in your library (love/dislike).

    Args:
        song_id: The library song ID
        rating: 'love', 'dislike', or 'none' to remove rating

    Returns: Confirmation or error
    """
    try:
        headers = get_headers()

        rating_value = {"love": 1, "dislike": -1, "none": 0}.get(rating.lower())
        if rating_value is None:
            return "Error: rating must be 'love', 'dislike', or 'none'"

        if rating_value == 0:
            # Remove rating
            response = requests.delete(
                f"{BASE_URL}/me/ratings/library-songs/{song_id}",
                headers=headers,
            )
        else:
            # Set rating
            body = {
                "type": "ratings",
                "attributes": {"value": rating_value}
            }
            response = requests.put(
                f"{BASE_URL}/me/ratings/library-songs/{song_id}",
                headers=headers,
                json={"data": [body]},
            )

        if response.status_code in [200, 201, 204]:
            return f"Successfully set rating to '{rating}' for song {song_id}"
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
def get_artist_details(artist_id: str) -> str:
    """
    Get detailed information about an artist from the catalog.

    Args:
        artist_id: Catalog artist ID

    Returns: Artist details and top songs
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/artists/{artist_id}",
            headers=headers,
            params={"include": "top-songs"},
        )
        response.raise_for_status()
        data = response.json()

        artists = data.get("data", [])
        if not artists:
            return "Artist not found"

        artist = artists[0]
        attrs = artist.get("attributes", {})

        output = [
            f"Artist: {attrs.get('name', 'Unknown')}",
            f"Genres: {', '.join(attrs.get('genreNames', ['Unknown']))}",
        ]

        # Add top songs if available
        relationships = artist.get("relationships", {})
        top_songs = relationships.get("top-songs", {}).get("data", [])

        if top_songs:
            output.append("\nTop Songs:")
            for song in top_songs[:10]:
                song_attrs = song.get("attributes", {})
                name = song_attrs.get("name", "Unknown")
                album = song_attrs.get("albumName", "")
                output.append(f"  - {name}" + (f" ({album})" if album else ""))

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
def get_curator_playlists(curator_id: str = "apple-music-1") -> str:
    """
    Get playlists from an Apple Music curator.

    Args:
        curator_id: Curator ID (default is Apple Music's main curator)

    Returns: Curated playlists
    """
    try:
        headers = get_headers()
        response = requests.get(
            f"{BASE_URL}/catalog/{STOREFRONT}/apple-curators/{curator_id}/playlists",
            headers=headers,
            params={"limit": 20},
        )
        response.raise_for_status()
        data = response.json()

        output = []
        for playlist in data.get("data", []):
            attrs = playlist.get("attributes", {})
            name = attrs.get("name", "Unknown")
            desc = attrs.get("description", {}).get("short", "")
            playlist_id = playlist.get("id")
            output.append(f"{name} (ID: {playlist_id})")
            if desc:
                output.append(f"  {desc[:100]}...")

        return "\n".join(output) if output else "No playlists found"

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
