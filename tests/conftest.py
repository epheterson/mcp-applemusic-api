"""Shared test fixtures."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary config directory."""
    config_dir = tmp_path / ".config" / "applemusic-mcp"
    config_dir.mkdir(parents=True)
    return config_dir


@pytest.fixture
def mock_config_dir(temp_config_dir, monkeypatch):
    """Patch get_config_dir to use temp directory."""
    from applemusic_mcp import auth
    monkeypatch.setattr(auth, "DEFAULT_CONFIG_DIR", temp_config_dir)
    return temp_config_dir


@pytest.fixture
def sample_config():
    """Sample configuration data."""
    return {
        "team_id": "TEST_TEAM_ID",
        "key_id": "TEST_KEY_ID",
        "private_key_path": "~/.config/applemusic-mcp/AuthKey_TEST.p8"
    }


@pytest.fixture
def sample_private_key():
    """Sample EC private key for testing (not a real key)."""
    # This is a test-only key, generated for testing purposes
    return """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgtest1234567890
abcdefghijklmnopqrstuvwxyzABCDEFGHhRANCAARtest1234567890abcdefgh
ijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghi
-----END PRIVATE KEY-----"""


@pytest.fixture
def configured_config_dir(mock_config_dir, sample_config, sample_private_key):
    """Config directory with config.json and private key."""
    # Write config
    config_file = mock_config_dir / "config.json"
    with open(config_file, "w") as f:
        json.dump(sample_config, f)

    # Write fake private key
    key_file = mock_config_dir / "AuthKey_TEST.p8"
    with open(key_file, "w") as f:
        f.write(sample_private_key)

    # Update config to use actual path
    sample_config["private_key_path"] = str(key_file)
    with open(config_file, "w") as f:
        json.dump(sample_config, f)

    return mock_config_dir


@pytest.fixture
def mock_developer_token():
    """A mock developer token."""
    return "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IlRFU1RfS0VZX0lEIn0.eyJpc3MiOiJURVNUX1RFQU1fSUQiLCJpYXQiOjE3MDAwMDAwMDAsImV4cCI6MTcxNTAwMDAwMH0.test_signature"


@pytest.fixture
def mock_user_token():
    """A mock music user token."""
    return "Atest1234567890abcdefghijklmnopqrstuvwxyz"


@pytest.fixture
def mock_api_headers(mock_developer_token, mock_user_token):
    """Mock API headers."""
    return {
        "Authorization": f"Bearer {mock_developer_token}",
        "Music-User-Token": mock_user_token,
        "Content-Type": "application/json",
    }
