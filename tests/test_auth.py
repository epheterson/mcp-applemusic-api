"""Tests for auth module."""

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from applemusic_mcp import auth


class TestGetConfigDir:
    """Tests for get_config_dir function."""

    def test_creates_directory_if_not_exists(self, mock_config_dir):
        """Should create config directory if it doesn't exist."""
        # Remove the directory first
        import shutil
        shutil.rmtree(mock_config_dir)
        assert not mock_config_dir.exists()

        # Call get_config_dir
        result = auth.get_config_dir()

        assert result.exists()
        assert result.is_dir()

    def test_returns_existing_directory(self, mock_config_dir):
        """Should return existing directory without error."""
        result = auth.get_config_dir()
        assert result == mock_config_dir
        assert result.exists()


class TestLoadConfig:
    """Tests for load_config function."""

    def test_loads_valid_config(self, mock_config_dir, sample_config):
        """Should load valid config file."""
        config_file = mock_config_dir / "config.json"
        with open(config_file, "w") as f:
            json.dump(sample_config, f)

        result = auth.load_config()

        assert result["team_id"] == "TEST_TEAM_ID"
        assert result["key_id"] == "TEST_KEY_ID"

    def test_raises_when_config_missing(self, mock_config_dir):
        """Should raise FileNotFoundError when config doesn't exist."""
        with pytest.raises(FileNotFoundError) as exc_info:
            auth.load_config()

        assert "Config file not found" in str(exc_info.value)

    def test_raises_on_invalid_json(self, mock_config_dir):
        """Should raise error on invalid JSON."""
        config_file = mock_config_dir / "config.json"
        with open(config_file, "w") as f:
            f.write("not valid json {{{")

        with pytest.raises(json.JSONDecodeError):
            auth.load_config()


class TestGetPrivateKeyPath:
    """Tests for get_private_key_path function."""

    def test_resolves_path_with_tilde(self, mock_config_dir):
        """Should expand ~ in path."""
        config = {"private_key_path": "~/test/key.p8"}

        with patch.object(Path, "exists", return_value=True):
            result = auth.get_private_key_path(config)

        assert "~" not in str(result)
        assert result.is_absolute()

    def test_raises_when_key_missing(self, mock_config_dir):
        """Should raise FileNotFoundError when key doesn't exist."""
        config = {"private_key_path": str(mock_config_dir / "nonexistent.p8")}

        with pytest.raises(FileNotFoundError) as exc_info:
            auth.get_private_key_path(config)

        assert "Private key not found" in str(exc_info.value)


class TestGetDeveloperToken:
    """Tests for get_developer_token function."""

    def test_returns_valid_token(self, mock_config_dir, mock_developer_token):
        """Should return token when valid and not expired."""
        token_file = mock_config_dir / "developer_token.json"
        token_data = {
            "token": mock_developer_token,
            "expires": time.time() + 86400 * 30,  # 30 days from now
        }
        with open(token_file, "w") as f:
            json.dump(token_data, f)

        result = auth.get_developer_token()

        assert result == mock_developer_token

    def test_raises_when_token_missing(self, mock_config_dir):
        """Should raise FileNotFoundError when token file doesn't exist."""
        with pytest.raises(FileNotFoundError) as exc_info:
            auth.get_developer_token()

        assert "Developer token not found" in str(exc_info.value)

    def test_raises_when_token_expired(self, mock_config_dir, mock_developer_token):
        """Should raise ValueError when token is expired."""
        token_file = mock_config_dir / "developer_token.json"
        token_data = {
            "token": mock_developer_token,
            "expires": time.time() - 86400,  # Expired yesterday
        }
        with open(token_file, "w") as f:
            json.dump(token_data, f)

        with pytest.raises(ValueError) as exc_info:
            auth.get_developer_token()

        assert "expired" in str(exc_info.value).lower()

    def test_raises_when_token_expiring_soon(self, mock_config_dir, mock_developer_token):
        """Should raise ValueError when token expires within 1 day."""
        token_file = mock_config_dir / "developer_token.json"
        token_data = {
            "token": mock_developer_token,
            "expires": time.time() + 3600,  # 1 hour from now
        }
        with open(token_file, "w") as f:
            json.dump(token_data, f)

        with pytest.raises(ValueError) as exc_info:
            auth.get_developer_token()

        assert "expired" in str(exc_info.value).lower()


class TestGetUserToken:
    """Tests for get_user_token function."""

    def test_returns_valid_token(self, mock_config_dir, mock_user_token):
        """Should return user token when present."""
        token_file = mock_config_dir / "music_user_token.json"
        token_data = {"music_user_token": mock_user_token}
        with open(token_file, "w") as f:
            json.dump(token_data, f)

        result = auth.get_user_token()

        assert result == mock_user_token

    def test_raises_when_token_missing(self, mock_config_dir):
        """Should raise FileNotFoundError when token doesn't exist."""
        with pytest.raises(FileNotFoundError) as exc_info:
            auth.get_user_token()

        assert "Music user token not found" in str(exc_info.value)


class TestSaveUserToken:
    """Tests for save_user_token function."""

    def test_saves_token_to_file(self, mock_config_dir, mock_user_token):
        """Should save token to JSON file."""
        auth.save_user_token(mock_user_token)

        token_file = mock_config_dir / "music_user_token.json"
        assert token_file.exists()

        with open(token_file) as f:
            data = json.load(f)

        assert data["music_user_token"] == mock_user_token
        assert "created" in data


class TestCreateAuthHtml:
    """Tests for create_auth_html function."""

    def test_contains_developer_token(self, mock_developer_token):
        """Should embed developer token in HTML."""
        html = auth.create_auth_html(mock_developer_token, 8765)

        assert mock_developer_token in html

    def test_contains_port(self):
        """Should embed port number in HTML."""
        html = auth.create_auth_html("test_token", 9999)

        assert "9999" in html

    def test_contains_musickit_script(self, mock_developer_token):
        """Should include MusicKit JS library."""
        html = auth.create_auth_html(mock_developer_token, 8765)

        assert "musickit" in html.lower()
        assert "js-cdn.music.apple.com" in html
