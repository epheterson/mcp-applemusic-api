# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2025-12-20

### Added

- **`remove_from_library`** - Remove tracks from library via AppleScript (macOS only)
- **`check_playlist`** - Quick check if song/artist is in a playlist (cross-platform)
- **`set_airplay_device`** - Switch audio output to AirPlay device (macOS)
- **`_rate_song_api`** - Internal helper for rating songs via API

### Changed

- **`love_track` / `dislike_track` now cross-platform** - Uses AppleScript on macOS, falls back to API elsewhere

- **play_track enhanced** - Now properly handles catalog tracks not in library:
  - `add_to_library=True`: Adds song to library first, then plays
  - `reveal=True`: Opens song in Music app for manual play
  - Clear messaging about AppleScript's inability to auto-play non-library catalog tracks
- **Code refactoring** - Extracted `_search_catalog_songs()` and `_add_songs_to_library()` internal helpers to reduce duplication

### Fixed

- Fixed `play_track` calling non-existent `reveal_in_music` (now correctly calls `reveal_track`)
- Replaced misleading `play_catalog_track` AppleScript function with honest `open_catalog_song`

## [0.2.0] - 2024-12-20

### Added

- **AppleScript integration for macOS** - 16 new tools providing capabilities not available via REST API:
  - Playback control: `play_track`, `play_playlist`, `playback_control`, `get_now_playing`, `seek_to_position`
  - Volume/settings: `set_volume`, `get_volume_and_playback`, `set_shuffle`, `set_repeat`
  - Playlist management: `remove_from_playlist`, `delete_playlist`
  - Track ratings: `love_track`, `dislike_track`
  - Other: `reveal_in_music`, `get_airplay_devices`, `local_search_library`
- **Clipped output tier** - New tier between Full and Compact that truncates long names while preserving all metadata fields (album, year, genre)
- **Platform Capabilities table** in README showing feature availability across macOS and Windows/Linux
- **Cross-platform OS classifiers** in pyproject.toml (Windows, Linux in addition to macOS)
- **Security documentation** for AppleScript input escaping

### Changed

- Renamed package from `mcp-applemusic-api` to `mcp-applemusic` (repo rename pending)
- Updated README with comprehensive macOS-only tools documentation
- Improved input sanitization: backslash escaping added to prevent edge cases in AppleScript strings
- Test count increased from 48 to 71 tests

### Fixed

- Exception handling in AppleScript module: replaced bare `except:` with specific exception types

## [0.1.0] - 2024-12-15

### Added

- Initial release with REST API integration
- 33 cross-platform MCP tools for Apple Music
- Playlist management (create, add tracks, copy)
- Library browsing and search
- Catalog search and recommendations
- Tiered output formatting (Full, Compact, Minimal)
- CSV export for large track listings
- Developer token generation and user authorization
- Comprehensive test suite (48 tests)
