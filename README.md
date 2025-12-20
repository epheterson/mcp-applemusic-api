# mcp-applemusic-api

An MCP server for managing Apple Music playlists and library via the official REST API.

**Cross-platform** · **Claude Code integration** · **Actually works for playlist editing**

---

## Quick Reference

| Task | Command |
|------|---------|
| Check setup status | `applemusic-mcp status` |
| Regenerate dev token | `applemusic-mcp generate-token` |
| Re-authorize user | `applemusic-mcp authorize` |
| Config directory | `~/.config/applemusic-mcp/` |

---

## Table of Contents

- [Setup (~10 minutes)](#setup)
- [Usage Examples](#usage)
- [Available Tools](#tools-available)
- [Limitations](#important-limitations)
- [Troubleshooting](#troubleshooting)
- [CLI Reference](#cli-reference)
- [Setting Up Another Machine](#setting-up-on-another-machine)

---

## Setup

**Prerequisites:**
- Apple Developer Account (free tier works - no $99/year required)
- Python 3.10+
- Apple Music subscription

### 1. Get MusicKit Credentials (~5 min)

1. Go to [Apple Developer Portal → Keys](https://developer.apple.com/account/resources/authkeys/list)
2. Click **+** to create a new key
3. Name it anything (e.g., "MCP Server")
4. Check **MusicKit** and click Continue → Register
5. **Download the .p8 file immediately**

> **⚠️ You can only download this file ONCE.** Back it up now (iCloud, password manager, etc.)

6. Note your **Key ID** (10-character string shown on the key page)
7. Go to [Membership](https://developer.apple.com/account/#!/membership) and note your **Team ID**

### 2. Install

```bash
git clone https://github.com/epheterson/mcp-applemusic-api.git
cd mcp-applemusic-api
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .
```

### 3. Configure

```bash
# Create config directory
mkdir -p ~/.config/applemusic-mcp   # Windows: mkdir %USERPROFILE%\.config\applemusic-mcp

# Copy your .p8 key
cp ~/Downloads/AuthKey_XXXXXXXXXX.p8 ~/.config/applemusic-mcp/
```

Create `~/.config/applemusic-mcp/config.json`:

```json
{
  "team_id": "YOUR_TEAM_ID",
  "key_id": "YOUR_KEY_ID",
  "private_key_path": "~/.config/applemusic-mcp/AuthKey_XXXXXXXXXX.p8"
}
```

### 4. Generate Tokens

```bash
# Generate developer token (valid 180 days)
applemusic-mcp generate-token

# Authorize with Apple Music (opens browser)
applemusic-mcp authorize
```

### 5. Add to Claude Code

Add to `~/.claude.json` (or project `.claude/settings.json`):

```json
{
  "mcpServers": {
    "applemusic": {
      "command": "/full/path/to/mcp-applemusic-api/venv/bin/python",
      "args": ["-m", "applemusic_mcp"]
    }
  }
}
```

### 6. Verify

```bash
applemusic-mcp status
```

Should show all OK:
```
Developer Token: OK (178 days remaining)
Music User Token: OK
API Connection: OK
```

---

## Usage

Ask Claude things like:

```
"List my Apple Music playlists"
"Create a playlist called 'Road Trip 2024'"
"Search my library for Beatles songs"
"Add 'Here Comes the Sun' to my Road Trip playlist"
"What have I been listening to recently?"
```

### Common Workflow: Add a Song to a Playlist

1. **Search catalog**: `search_catalog("Wonderwall Oasis")`
2. **Add to library**: `add_to_library("catalog_id_here")`
3. **Find library ID**: `search_library("Wonderwall")`
4. **Add to playlist**: `add_to_playlist("playlist_id", "library_song_id")`

> **Why so many steps?** Apple's API requires songs to be in your library before adding to playlists, and uses different IDs for catalog vs library.

---

## Tools Available (31 total)

### Playlists

| Tool | Description |
|------|-------------|
| `get_library_playlists` | List all playlists with IDs and edit status |
| `get_playlist_tracks` | Get all tracks in a playlist |
| `create_playlist` | Create a new (editable) playlist |
| `copy_playlist` | Copy to a new editable playlist |
| `add_to_playlist` | Add tracks to a playlist |

### Library Browsing

| Tool | Description |
|------|-------------|
| `get_library_albums` | List all albums in your library |
| `get_library_artists` | List all artists in your library |
| `get_library_songs` | List songs in your library (with limit) |
| `get_library_music_videos` | List music videos in your library |
| `search_library` | Search your library → library IDs |
| `add_to_library` | Add catalog songs to your library |
| `get_album_tracks` | Get all tracks from an album (library or catalog) |
| `get_recently_added` | Content recently added to your library |
| `get_recently_played` | Recent listening history (albums/playlists) |
| `get_recently_played_tracks` | Recent listening history (individual songs) |

### Catalog Search

| Tool | Description |
|------|-------------|
| `search_catalog` | Search Apple Music → catalog IDs |
| `get_search_suggestions` | Get autocomplete suggestions for search terms |
| `get_song_details` | Get full details for a song by ID |
| `get_artist_details` | Search for artist and get albums |
| `get_artist_top_songs` | Get artist's most popular songs |
| `get_similar_artists` | Find artists similar to a given artist |
| `get_song_station` | Get radio station based on a song |
| `get_charts` | Get Apple Music charts (songs, albums, playlists) |
| `get_music_videos` | Search or browse music videos |
| `get_genres` | List all available genres |
| `get_storefronts` | List all Apple Music regions/countries |

### Discovery & Personalization

| Tool | Description |
|------|-------------|
| `get_recommendations` | Get personalized recommendations |
| `get_heavy_rotation` | Albums/playlists you play frequently |
| `get_personal_station` | Get your personal radio station |
| `rate_song` | Love or dislike a song |

### Utilities

| Tool | Description |
|------|-------------|
| `check_auth_status` | Verify tokens and API connection |

---

## Accessing Favorite Songs

Your loved songs are available as a read-only "Favorite Songs" playlist:
```
get_library_playlists()  → Find "Favorite Songs (ID: p.XXX, read-only)"
get_playlist_tracks("p.XXX")  → Get all your loved songs
```

To love a song, use `rate_song(catalog_id, "love")`.

---

## Important Limitations

### Only API-Created Playlists Are Editable

Playlists created in iTunes/Music app are **read-only** via API.

**Workaround:** `copy_playlist` creates an editable copy.

### No Playlist Deletion or Track Removal

Apple's API doesn't support:
- Deleting playlists
- Removing individual tracks from playlists
- Updating playlist names/descriptions

**Workaround:** Create a new playlist with the content you want.

### Two Types of Song IDs

| ID Type | Source | Use For |
|---------|--------|---------|
| Catalog ID | `search_catalog` | Adding to library |
| Library ID | `search_library` | Adding to playlists |

### Token Expiration

| Token | Lifetime | Renewal |
|-------|----------|---------|
| Developer | 180 days | `applemusic-mcp generate-token` |
| User | ~months | `applemusic-mcp authorize` |

You'll see warnings 30 days before developer token expires.

---

## Troubleshooting

### "Unauthorized" or 401 error
```bash
applemusic-mcp authorize
```

### "Cannot edit this playlist"
The playlist was created in iTunes/Music, not via API. Use `copy_playlist` to make an editable copy.

### Token expiring warning
```bash
applemusic-mcp generate-token
```

### Lost your .p8 key?
Create a new key in Apple Developer Portal. Update `config.json` with the new `key_id` and file path.

### Check everything
```bash
applemusic-mcp status
```

---

## CLI Reference

```bash
applemusic-mcp status          # Check tokens and API connection
applemusic-mcp generate-token  # Create new developer token (180 days)
applemusic-mcp authorize       # Browser auth for user token
applemusic-mcp init            # Create sample config file
applemusic-mcp serve           # Run MCP server (usually auto-launched)
```

**Config location:** `~/.config/applemusic-mcp/`

**Files:**
- `config.json` - Your credentials
- `AuthKey_*.p8` - Private key
- `developer_token.json` - Generated JWT
- `music_user_token.json` - User authorization

---

## Setting Up on Another Machine

1. Clone and install (step 2 above)
2. Copy your `.p8` key to `~/.config/applemusic-mcp/`
3. Create `config.json` with same `team_id` and `key_id`
4. Run `applemusic-mcp generate-token`
5. Run `applemusic-mcp authorize` (requires browser sign-in)

> **Note:** The `.p8` key and `team_id`/`key_id` are reusable. User tokens must be created per-machine.

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Validate all endpoints against your live library
python scripts/validate_endpoints.py

# Format code
black src/ tests/
ruff check src/ tests/
```

---

## License

MIT

## Credits

- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
- [Apple MusicKit](https://developer.apple.com/documentation/applemusicapi) - API documentation
- [Model Context Protocol](https://modelcontextprotocol.io/) - Protocol spec by Anthropic
