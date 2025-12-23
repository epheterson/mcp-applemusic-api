# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.7] - 2025-12-22

### Changed

- **`check_playlist` → `search_playlist`** - Renamed for clarity and enhanced:
  - Uses native AppleScript search on macOS (fast, same as Music app search field)
  - API path manually filters tracks (cross-platform support maintained)
  - Now searches album field in addition to name/artist
  - Better name reflects actual functionality

### Fixed

- **Album search** - API path now searches album field (was missing)

## [0.2.6] - 2025-12-22

### Added

- **Auto-search feature** - Automatically find and add tracks from catalog when not in library (opt-in):
  - New `auto_search` parameter for `add_to_playlist` (uses preference if not specified, default: false)
  - When track not in library: searches catalog → adds to library → adds to playlist (one operation!)
  - Uses optimized API flow: `/catalog/{catalog_id}/library` to get library ID instantly (no retry loop)
  - Includes API verification to confirm track added to playlist
  - Reduces 7-step manual process to 1 call
  - Set via `system(action="set-pref", preference="auto_search", value=True)` to enable by default
- **New `auto_search` preference** - Control automatic catalog search behavior (default: false, respects user choice)

### Changed

- **Partial matching everywhere** - ALL track operations now support partial name matching:
  - `add_track_to_playlist` - Changed from `is` to `contains` (CRITICAL FIX)
  - `love_track` - Now supports partial matching
  - `dislike_track` - Now supports partial matching
  - `get_rating` - Now supports partial matching
  - `set_rating` - Now supports partial matching
  - No more frustration with exact titles like "Song (Live at Venue, Date)"
- **Optimized auto_search flow** - Minimal API calls:
  1. Search catalog → get catalog_id
  2. Add to library via API
  3. Get library ID from `/catalog/{catalog_id}/library` (instant!)
  4. Get playlist ID from name (AppleScript, local)
  5. Add to playlist via API
  6. Verify via API

### Fixed

- **Critical:** `add_to_playlist` with track names required EXACT match (now uses `contains`)
  - Example: "Give Up the Funk" now finds "Give up the Funk (Tear the Roof Off the Sucker)"
  - Fixes the user's exact scenario where 7 attempts were needed to add one song

## [0.2.5] - 2025-12-22

### Added

- **Track metadata caching system** - Intelligent caching for stable track metadata:
  - Dedicated `track_cache.py` module with clean interface
  - Multi-ID indexing: caches by persistent IDs (AppleScript), library IDs (API), and catalog IDs (universal)
  - Stores stable fields only: explicit status and ISRC
  - Eliminates redundant API calls (90% reduction for repeated checks)
  - Extensible design for adding more stable fields
  - 10-20x speedup for subsequent playlist explicit status checks
  - Cache persisted to `~/.cache/applemusic-mcp/track_cache.json`
- **Explicit content tracking** - Comprehensive explicit status throughout:
  - `[Explicit]` marker in all track output formats (text, JSON, CSV)
  - `fetch_explicit=True` parameter for `get_playlist_tracks()` to fetch explicit status via API
  - `clean_only=True` parameter for `search_catalog()` to filter explicit content
  - AppleScript mode shows "Unknown" by default (contentRating not exposed)
  - API mode shows accurate "Yes"/"No" explicit status
- **User preferences system** - Set defaults for common parameters:
  - `fetch_explicit` - always fetch explicit status (default: false)
  - `reveal_on_library_miss` - auto-reveal catalog tracks in Music app (default: false)
  - `clean_only` - filter explicit content in catalog searches (default: false)
  - Set via `system(action="set-pref", preference="...", value=True/False)`
  - View current preferences via `system()` info display
  - Stored in `~/.config/applemusic-mcp/config.json`
  - See `config.example.json` for format
- **New `system` tool** - Comprehensive system configuration and cache management:
  - `system()` - show preferences, track cache stats, and export files
  - `system(action="set-pref", ...)` - update preferences
  - `system(action="clear-tracks")` - clear track metadata cache separately
  - `system(action="clear-exports")` - clear CSV/JSON export files separately
  - Shows cache sizes, entry counts, file ages
  - Replaces old `cache` tool with more intuitive naming
- **Partial playlist matching** - Smart playlist name matching with exact-match priority:
  - "Jack & Norah" now finds "🤟👶🎸 Jack & Norah"
  - Exact matches always prioritized over partial matches
  - Applied to all playlist operations via `_find_playlist_applescript()` helper
- **Comprehensive documentation**:
  - `CACHING.md` - Multi-ID caching architecture, E2E flow, performance analysis
  - `COMPOSITE_KEYS.md` - Why we use composite keys for AppleScript ↔ API bridging
  - `config.example.json` - Example configuration with preferences
- **Test suite expansion** - 30 new tests (120 total: 26 track cache, 4 preferences)

### Changed

- **Error messages cleaned up** - Removed redundant playlist names from error responses
- **Helpful guidance** - Error messages suggest `search_catalog` + `add_to_library` workflow when tracks not found
- **Tool parameters** - `fetch_explicit`, `clean_only`, `reveal` now use `Optional[bool]` to support user preferences
- **Asymmetry fixes** - Systematic review and fixes for add/remove inconsistencies:
  - **`remove_from_playlist` enhanced**:
    - **Partial matching fixed** - Now uses `contains` instead of `is` (no more exact match requirement!)
    - **Array support** - Remove multiple tracks at once (comma-separated names, IDs, or JSON array)
    - **ID-based removal** - Remove by persistent IDs via `track_ids` parameter
    - **Better output** - Shows removed count, lists successes and failures separately
  - **`remove_from_library` enhanced** - Now matches `add_to_library` capabilities:
    - **Array support** - Remove multiple tracks: `track_name="Song1,Song2"` or `track_ids="ID1,ID2"`
    - **ID-based removal** - Remove by persistent IDs via `track_ids` parameter
    - **JSON array support** - Different artists: `tracks='[{"name":"Hey Jude","artist":"Beatles"}]'`
    - **Flexible formats** - Same 5 modes as `remove_from_playlist`
  - **`search_library` parameter standardized** - Renamed `search_type` → `types` to match `search_catalog`
  - **`copy_playlist` name support** - Added `source_playlist_name` parameter for macOS users (matches other playlist operations)

## [0.2.4] - 2025-12-21

### Added

- **No-credentials mode on macOS** - Many features now work without API setup:
  - `get_library_playlists` - Lists playlists via AppleScript first
  - `create_playlist` - Creates playlists via AppleScript first
  - `browse_library(songs)` - Lists library songs via AppleScript first
  - New `get_library_songs()` AppleScript helper function
- **Test cleanup** - Automatically removes test playlists after test runs

### Changed

- **AppleScript-first approach** - macOS tools try AppleScript before falling back to API
- **README** - Documents no-credentials mode, simplified requirements

## [0.2.3] - 2025-12-21

### Changed

- **format=csv** - Inline CSV output in response (in addition to text/json/none)
- **export=none** - Consistent "none" default instead of empty string
- **play_track response prefixes** - Shows `[Library]`, `[Catalog]`, or `[Catalog→Library]` to indicate source
- **Featured artist matching** - `play_track` matches "Bruno Mars" in "Uptown Funk (feat. Bruno Mars)"
- **Catalog song reveal** - `reveal=True` opens song in Music app via `music://` URL (user clicks play)
- **Add-to-library retry** - Retries add at 5s mark in case first attempt silently failed
- **URL validation** - `open_catalog_song` validates Apple Music URLs before opening

## [0.2.2] - 2025-12-20

### Added

- **MCP Resources for exports** - Claude Desktop can now read exported files:
  - `exports://list` - List all exported files
  - `exports://{filename}` - Read a specific export file

### Changed

- **Tool consolidation (55 → 42 tools)** - The answer to life, the universe, and everything:
  - `browse_library(type=songs|albums|artists|videos)` - merged 4 library listing tools
  - `rating(action=love|dislike|get|set)` - merged 5 rating tools into one
  - `playback_settings(volume, shuffle, repeat)` - merged 4 settings tools
  - `search_library` - now uses AppleScript on macOS (faster), API fallback elsewhere
  - `airplay` - list or switch devices (merged 2 tools)
  - `cache` - view or clear cache (merged 2 tools)
- **Unified output format** - List tools now support:
  - `format="text"` (default), `"json"`, `"csv"`, or `"none"` (export only)
  - `export="none"` (default), `"csv"`, or `"json"` to write files
  - `full=True` to include all metadata
- **Extended iCloud sync wait** - `play_track` now waits ~10s for add-to-library sync (was ~7s)

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
