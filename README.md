# mcp-applemusic

MCP server for Apple Music - manage playlists, control playback, browse your library.

## Features

| Feature | macOS | Windows/Linux |
|---------|:-----:|:-------------:|
| Search catalog & library | ✅ | ✅ |
| Add songs to library | ✅ | ✅ |
| Create playlists, add tracks | ✅ | ✅ |
| Recommendations, charts, radio | ✅ | ✅ |
| Browse albums, artists, songs | ✅ | ✅ |
| **Play/pause/skip/seek** | ✅ | ❌ |
| **Volume/shuffle/repeat** | ✅ | ❌ |
| **Remove tracks from playlists** | ✅ | ❌ |
| **Delete playlists** | ✅ | ❌ |
| **Edit ANY playlist** | ✅ | ❌ |

On macOS, AppleScript removes most API limitations - edit or delete *any* playlist, not just API-created ones.

---

## Setup

**You'll need:** Apple Developer Account (free), Python 3.10+, Apple Music subscription

### 1. Get MusicKit Key

1. [Apple Developer Portal → Keys](https://developer.apple.com/account/resources/authkeys/list) → Click **+**
2. Name it anything, check **MusicKit**, click Continue → Register
3. **Download the .p8 file** (you can only download once!)
4. Note your **Key ID** (10 chars) and **Team ID** (from [Membership](https://developer.apple.com/account/#!/membership))

### 2. Install & Configure

```bash
git clone https://github.com/epheterson/mcp-applemusic.git
cd mcp-applemusic
python3 -m venv venv && source venv/bin/activate
pip install -e .

# Setup config
mkdir -p ~/.config/applemusic-mcp
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

### 3. Generate Tokens

```bash
applemusic-mcp generate-token   # Creates developer token (180 days)
applemusic-mcp authorize        # Opens browser for Apple Music auth
applemusic-mcp status           # Verify everything works
```

### 4. Add to Claude

Add to your Claude config file:
- **Claude Code:** `~/.claude.json`
- **Claude Desktop (Mac):** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Claude Desktop (Windows):** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "Apple Music": {
      "command": "/full/path/to/mcp-applemusic/venv/bin/python",
      "args": ["-m", "applemusic_mcp"]
    }
  }
}
```

---

## Usage

Ask Claude things like:
- "List my Apple Music playlists"
- "Create a playlist called 'Road Trip'"
- "Search for Beatles songs and add Hey Jude to Road Trip"
- "What have I been listening to recently?"
- "Play my workout playlist" (macOS)

---

## Tools (33 cross-platform + 18 macOS-only)

### Playlists
| Tool | Description |
|------|-------------|
| `get_library_playlists` | List all playlists with IDs and edit status |
| `get_playlist_tracks` | Get all tracks in a playlist |
| `create_playlist` | Create new playlist |
| `add_to_playlist` | Add tracks to playlist |
| `copy_playlist` | Copy to editable playlist |

### Library
| Tool | Description |
|------|-------------|
| `search_library` | Search your library → library IDs |
| `get_library_songs` | List songs in library |
| `get_library_albums` | List albums in library |
| `get_library_artists` | List artists in library |
| `get_album_tracks` | Get tracks from an album |
| `get_recently_played` | Recent listening history |
| `get_recently_added` | Recently added content |
| `add_to_library` | Add catalog song to library |
| `rate_song` | Love or dislike a song |

### Catalog & Discovery
| Tool | Description |
|------|-------------|
| `search_catalog` | Search Apple Music → catalog IDs |
| `get_song_details` | Full details for a song |
| `get_artist_details` | Artist info and discography |
| `get_artist_top_songs` | Artist's popular songs |
| `get_similar_artists` | Find similar artists |
| `get_recommendations` | Personalized recommendations |
| `get_heavy_rotation` | Your frequently played |
| `get_charts` | Top songs, albums, playlists |
| `get_genres` | List all genres |

### macOS Only (AppleScript)
| Tool | Description |
|------|-------------|
| `play_track` | Play specific track by name |
| `play_playlist` | Start playing a playlist |
| `playback_control` | Play, pause, stop, next, previous |
| `get_now_playing` | Current track info |
| `set_volume` | Set volume (0-100) |
| `set_shuffle` / `set_repeat` | Playback settings |
| `seek_to_position` | Seek within current track |
| `remove_from_playlist` | Remove track from playlist |
| `delete_playlist` | Delete a playlist |
| `get_track_rating` | Get star rating (0-5) |
| `set_track_rating` | Set star rating (0-5) |
| `get_airplay_devices` | List AirPlay devices |

### Output Format

Track listings auto-select the best format that fits:
- **Full**: Name - Artist (duration) Album [Year] Genre id
- **Clipped**: Same but with truncated names
- **Compact**: Name - Artist (duration) id
- **Minimal**: Name - Artist id

CSV exports include complete data regardless of display format.

---

## Limitations

### Windows/Linux
| Limitation | Workaround |
|------------|------------|
| Only API-created playlists editable | `copy_playlist` makes editable copy |
| Can't delete playlists or remove tracks | Create new playlist instead |
| No playback control | Use Music app directly |

### Both Platforms
- **Two ID types:** Catalog IDs (from `search_catalog`) for adding to library, Library IDs (from `search_library`) for adding to playlists
- **Tokens expire:** Developer token lasts 180 days, run `applemusic-mcp generate-token` to renew

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| 401 Unauthorized | `applemusic-mcp authorize` |
| "Cannot edit playlist" | Use `copy_playlist` for editable copy |
| Token expiring | `applemusic-mcp generate-token` |
| Check everything | `applemusic-mcp status` |

---

## CLI Reference

```bash
applemusic-mcp status          # Check tokens and connection
applemusic-mcp generate-token  # New developer token (180 days)
applemusic-mcp authorize       # Browser auth for user token
applemusic-mcp serve           # Run MCP server (auto-launched by Claude)
```

**Config:** `~/.config/applemusic-mcp/` (config.json, .p8 key, tokens)

---

## License

MIT

## Credits

[FastMCP](https://github.com/jlowin/fastmcp) · [Apple MusicKit](https://developer.apple.com/documentation/applemusicapi) · [Model Context Protocol](https://modelcontextprotocol.io/)
