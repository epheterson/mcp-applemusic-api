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
