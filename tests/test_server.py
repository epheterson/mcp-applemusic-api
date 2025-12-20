"""Tests for server module."""

import json
import time
from unittest.mock import patch, MagicMock

import pytest
import responses

from applemusic_mcp import server


class TestGetTokenExpirationWarning:
    """Tests for get_token_expiration_warning function."""

    def test_returns_none_when_no_token_file(self, mock_config_dir):
        """Should return None when token file doesn't exist."""
        result = server.get_token_expiration_warning()
        assert result is None

    def test_returns_none_when_token_valid(self, mock_config_dir):
        """Should return None when token has more than 30 days left."""
        token_file = mock_config_dir / "developer_token.json"
        token_data = {"expires": time.time() + 86400 * 60}  # 60 days
        with open(token_file, "w") as f:
            json.dump(token_data, f)

        result = server.get_token_expiration_warning()
        assert result is None

    def test_returns_warning_when_expiring_soon(self, mock_config_dir):
        """Should return warning when token expires within 30 days."""
        token_file = mock_config_dir / "developer_token.json"
        token_data = {"expires": time.time() + 86400 * 15}  # 15 days
        with open(token_file, "w") as f:
            json.dump(token_data, f)

        result = server.get_token_expiration_warning()
        assert result is not None
        assert "days" in result  # Could be 14 or 15 depending on timing
        assert "generate-token" in result


class TestGetHeaders:
    """Tests for get_headers function."""

    def test_returns_headers_with_tokens(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should return properly formatted headers."""
        # Setup token files
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 30}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        result = server.get_headers()

        assert "Authorization" in result
        assert result["Authorization"].startswith("Bearer ")
        assert "Music-User-Token" in result
        assert result["Content-Type"] == "application/json"


class TestGetLibraryPlaylists:
    """Tests for get_library_playlists function."""

    @responses.activate
    def test_returns_playlists(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should return formatted playlist list."""
        # Setup tokens
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 60}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        # Mock API response
        responses.add(
            responses.GET,
            "https://api.music.apple.com/v1/me/library/playlists",
            json={
                "data": [
                    {
                        "id": "p.abc123",
                        "attributes": {"name": "Test Playlist", "canEdit": True}
                    },
                    {
                        "id": "p.def456",
                        "attributes": {"name": "Read Only", "canEdit": False}
                    }
                ]
            },
            status=200,
        )

        result = server.get_library_playlists()

        assert "Test Playlist" in result
        assert "p.abc123" in result
        assert "editable" in result
        assert "Read Only" in result
        assert "read-only" in result

    @responses.activate
    def test_handles_api_error(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should return error message on API failure."""
        # Setup tokens
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 60}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        responses.add(
            responses.GET,
            "https://api.music.apple.com/v1/me/library/playlists",
            json={"error": "Unauthorized"},
            status=401,
        )

        result = server.get_library_playlists()

        assert "API Error" in result or "401" in result


class TestCreatePlaylist:
    """Tests for create_playlist function."""

    @responses.activate
    def test_creates_playlist_successfully(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should create playlist and return ID."""
        # Setup tokens
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 60}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        responses.add(
            responses.POST,
            "https://api.music.apple.com/v1/me/library/playlists",
            json={"data": [{"id": "p.newplaylist123"}]},
            status=201,
        )

        result = server.create_playlist("My New Playlist", "A description")

        assert "My New Playlist" in result
        assert "p.newplaylist123" in result


class TestAddToPlaylist:
    """Tests for add_to_playlist function."""

    @responses.activate
    def test_adds_tracks_successfully(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should add tracks and return confirmation."""
        # Setup tokens
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 60}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        responses.add(
            responses.POST,
            "https://api.music.apple.com/v1/me/library/playlists/p.test123/tracks",
            status=204,
        )

        result = server.add_to_playlist("p.test123", "i.song1, i.song2, i.song3")

        assert "Successfully added" in result
        assert "3 track" in result

    def test_handles_empty_song_ids(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should return error for empty song IDs."""
        # Setup tokens
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 60}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        result = server.add_to_playlist("p.test123", "")

        assert "No song IDs provided" in result


class TestSearchLibrary:
    """Tests for search_library function."""

    @responses.activate
    def test_returns_search_results(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should return formatted search results."""
        # Setup tokens
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 60}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        responses.add(
            responses.GET,
            "https://api.music.apple.com/v1/me/library/search",
            json={
                "results": {
                    "library-songs": {
                        "data": [
                            {
                                "id": "i.abc123",
                                "attributes": {
                                    "name": "Wonderwall",
                                    "artistName": "Oasis",
                                    "albumName": "(What's the Story) Morning Glory?"
                                }
                            }
                        ]
                    }
                }
            },
            status=200,
        )

        result = server.search_library("Wonderwall")

        assert "Wonderwall" in result
        assert "Oasis" in result
        assert "i.abc123" in result


class TestSearchCatalog:
    """Tests for search_catalog function."""

    @responses.activate
    def test_returns_catalog_results(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should return formatted catalog search results."""
        # Setup tokens
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 60}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        responses.add(
            responses.GET,
            "https://api.music.apple.com/v1/catalog/us/search",
            json={
                "results": {
                    "songs": {
                        "data": [
                            {
                                "id": "123456789",
                                "attributes": {
                                    "name": "Let It Be",
                                    "artistName": "The Beatles"
                                }
                            }
                        ]
                    }
                }
            },
            status=200,
        )

        result = server.search_catalog("Let It Be")

        assert "Let It Be" in result
        assert "The Beatles" in result
        assert "123456789" in result


class TestCheckAuthStatus:
    """Tests for check_auth_status function."""

    def test_reports_missing_tokens(self, mock_config_dir):
        """Should report missing tokens."""
        result = server.check_auth_status()

        assert "MISSING" in result
        assert "Developer Token" in result
        assert "Music User Token" in result

    def test_reports_valid_tokens(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should report OK for valid tokens."""
        # Setup tokens
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 60}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        # Don't actually test API connection
        with patch.object(server, "get_headers", return_value={}):
            with patch("requests.get") as mock_get:
                mock_get.return_value.status_code = 200
                result = server.check_auth_status()

        assert "OK" in result
        assert "Developer Token" in result

    def test_reports_expiring_token(self, mock_config_dir, mock_developer_token, mock_user_token):
        """Should warn about expiring token."""
        # Setup expiring token
        dev_token_file = mock_config_dir / "developer_token.json"
        with open(dev_token_file, "w") as f:
            json.dump({"token": mock_developer_token, "expires": time.time() + 86400 * 10}, f)

        user_token_file = mock_config_dir / "music_user_token.json"
        with open(user_token_file, "w") as f:
            json.dump({"music_user_token": mock_user_token}, f)

        result = server.check_auth_status()

        assert "EXPIRES IN" in result or "10" in result


class TestFormatDuration:
    """Tests for format_duration helper function."""

    def test_formats_standard_duration(self):
        """Should format milliseconds as m:ss."""
        assert server.format_duration(225000) == "3:45"
        assert server.format_duration(60000) == "1:00"
        assert server.format_duration(5000) == "0:05"

    def test_handles_zero(self):
        """Should return empty string for zero."""
        assert server.format_duration(0) == ""

    def test_handles_none(self):
        """Should return empty string for None."""
        assert server.format_duration(None) == ""

    def test_handles_negative(self):
        """Should return empty string for negative values."""
        assert server.format_duration(-1000) == ""
        assert server.format_duration(-60000) == ""

    def test_handles_large_duration(self):
        """Should handle songs longer than an hour."""
        # 1 hour, 5 minutes, 30 seconds = 3930000 ms
        assert server.format_duration(3930000) == "65:30"


class TestExtractTrackData:
    """Tests for extract_track_data helper function."""

    def test_extracts_basic_fields(self):
        """Should extract core fields from track data."""
        track = {
            "id": "i.abc123",
            "attributes": {
                "name": "Wonderwall",
                "artistName": "Oasis",
                "albumName": "(What's the Story) Morning Glory?",
                "durationInMillis": 258000,
                "releaseDate": "1995-10-02",
                "genreNames": ["Rock", "Alternative"],
            }
        }
        result = server.extract_track_data(track)

        assert result["name"] == "Wonderwall"
        assert result["artist"] == "Oasis"
        assert result["album"] == "(What's the Story) Morning Glory?"
        assert result["duration"] == "4:18"
        assert result["year"] == "1995"
        assert result["genre"] == "Rock"
        assert result["id"] == "i.abc123"

    def test_handles_empty_track(self):
        """Should handle empty track dict gracefully."""
        result = server.extract_track_data({})

        assert result["name"] == ""
        assert result["artist"] == ""
        assert result["duration"] == ""
        assert result["id"] == ""

    def test_handles_missing_attributes(self):
        """Should handle track with empty attributes."""
        track = {"id": "test123", "attributes": {}}
        result = server.extract_track_data(track)

        assert result["id"] == "test123"
        assert result["name"] == ""

    def test_includes_extras_when_requested(self):
        """Should include extra fields when include_extras=True."""
        track = {
            "id": "123",
            "attributes": {
                "name": "Test",
                "trackNumber": 5,
                "discNumber": 2,
                "hasLyrics": True,
                "composerName": "John Doe",
                "isrc": "USRC12345678",
                "contentRating": "explicit",
                "playParams": {"catalogId": "cat123"},
                "previews": [{"url": "https://example.com/preview.m4a"}],
                "artwork": {"url": "https://example.com/{w}x{h}bb.jpg"},
            }
        }
        result = server.extract_track_data(track, include_extras=True)

        assert result["track_number"] == 5
        assert result["disc_number"] == 2
        assert result["has_lyrics"] is True
        assert result["composer"] == "John Doe"
        assert result["isrc"] == "USRC12345678"
        assert result["is_explicit"] is True
        assert result["catalog_id"] == "cat123"
        assert "preview.m4a" in result["preview_url"]
        assert "500x500" in result["artwork_url"]


class TestTruncate:
    """Tests for truncate helper function."""

    def test_truncates_long_string(self):
        """Should truncate and add ellipsis for strings exceeding max length."""
        result = server.truncate("This is a very long string", 10)
        assert result == "This is a ..."
        assert len(result) == 13  # 10 chars + "..."

    def test_returns_short_string_unchanged(self):
        """Should return strings shorter than max unchanged."""
        result = server.truncate("Short", 10)
        assert result == "Short"

    def test_returns_exact_length_unchanged(self):
        """Should return strings exactly at max length unchanged."""
        result = server.truncate("TenChars!!", 10)
        assert result == "TenChars!!"

    def test_handles_empty_string(self):
        """Should handle empty string."""
        result = server.truncate("", 10)
        assert result == ""


class TestFormatTrackList:
    """Tests for format_track_list helper function."""

    def test_full_format_for_small_lists(self):
        """Should use full format for small track lists."""
        tracks = [{
            "name": "Song Name",
            "artist": "Artist Name",
            "duration": "3:45",
            "album": "Album Name",
            "year": "2024",
            "genre": "Rock",
            "id": "123"
        }]
        lines, tier = server.format_track_list(tracks)

        assert tier == "Full"
        assert len(lines) == 1
        assert "Song Name - Artist Name (3:45) Album Name [2024] Rock 123" == lines[0]

    def test_clipped_format_when_full_exceeds_limit(self):
        """Should use clipped format when full format exceeds MAX_OUTPUT_CHARS."""
        track = {
            "name": "A" * 100,
            "artist": "B" * 50,
            "duration": "3:00",
            "album": "C" * 100,
            "year": "2024",
            "genre": "Rock",
            "id": "12345678901234567890"
        }
        tracks = [track] * 200
        lines, tier = server.format_track_list(tracks)

        assert tier == "Clipped"
        assert len(lines) == 200
        assert "..." in lines[0]  # Truncated
        assert "C" * 100 not in lines[0]  # Album truncated
        assert "[2024]" in lines[0]  # Year still present
        assert "Rock" in lines[0]  # Genre still present

    def test_compact_format_when_clipped_exceeds_limit(self):
        """Should use compact format when clipped format exceeds MAX_OUTPUT_CHARS."""
        track = {
            "name": "A" * 50,
            "artist": "B" * 30,
            "duration": "3:00",
            "album": "Album",
            "year": "2024",
            "genre": "Rock",
            "id": "12345678901234567890"
        }
        tracks = [track] * 450
        lines, tier = server.format_track_list(tracks)

        assert tier == "Compact"
        assert len(lines) == 450
        assert "Album" not in lines[0]  # Album dropped
        assert "[2024]" not in lines[0]  # Year dropped
        assert "(3:00)" in lines[0]  # Duration still present

    def test_minimal_format_when_compact_exceeds_limit(self):
        """Should use minimal format when compact format also exceeds limit."""
        track = {
            "name": "A" * 50,
            "artist": "B" * 30,
            "duration": "3:00",
            "album": "Album",
            "year": "2024",
            "genre": "Rock",
            "id": "12345678901234567890"
        }
        tracks = [track] * 800
        lines, tier = server.format_track_list(tracks)

        assert tier == "Minimal"
        assert len(lines) == 800
        assert "(3:00)" not in lines[0]

    def test_handles_empty_optional_fields(self):
        """Should handle tracks with empty year/genre gracefully."""
        tracks = [{
            "name": "Song",
            "artist": "Artist",
            "duration": "3:00",
            "album": "Album",
            "year": "",
            "genre": "",
            "id": "123"
        }]
        lines, tier = server.format_track_list(tracks)

        assert tier == "Full"
        assert "[" not in lines[0]
        assert lines[0] == "Song - Artist (3:00) Album 123"

    def test_returns_empty_for_no_tracks(self):
        """Should handle empty track list."""
        lines, tier = server.format_track_list([])
        assert tier == "Full"
        assert lines == []
