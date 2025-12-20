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
| Play/pause/skip/seek | ✅ | ❌ |
| Volume/shuffle/repeat | ✅ | ❌ |
| Remove tracks from playlists | ✅ | ❌ |
| Delete playlists | ✅ | ❌ |
| Edit ANY playlist | ✅ | ❌ |

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

## Tools (52 total)

*macOS = requires Mac with Music app*

### Playlists
| Tool | Description |
|------|-------------|
| `get_library_playlists` | List all playlists |
| `get_playlist_tracks` | Get tracks (by ID or name*) with filter/limit |
| `create_playlist` | Create new playlist |
| `add_to_playlist` | Smart add: auto-adds to library, skips duplicates, verifies |
| `copy_playlist` | Copy playlist to editable version |
| `remove_from_playlist` | Remove track *(macOS)* |
| `delete_playlist` | Delete playlist *(macOS)* |

*By name requires macOS. With names, can edit ANY playlist.

`add_to_playlist` accepts catalog IDs (auto-adds to library first) or library IDs. Duplicate checking is on by default.

### Library
| Tool | Description |
|------|-------------|
| `search_library` | Search your library (API) |
| `local_search_library` | Search your library *(macOS)* |
| `get_library_songs` | List songs |
| `get_library_albums` | List albums |
| `get_library_artists` | List artists |
| `get_library_music_videos` | List music videos |
| `get_album_tracks` | Get tracks from album |
| `get_recently_played` | Recent listening history |
| `get_recently_added` | Recently added content |
| `add_to_library` | Add song from catalog |
| `rate_song` | Love or dislike (API) |
| `love_track` | Mark as loved *(macOS)* |
| `dislike_track` | Mark as disliked *(macOS)* |
| `get_track_rating` | Get star rating *(macOS)* |
| `set_track_rating` | Set star rating *(macOS)* |

### Catalog & Discovery
| Tool | Description |
|------|-------------|
| `search_catalog` | Search Apple Music |
| `get_song_details` | Full song details |
| `get_artist_details` | Artist info and discography |
| `get_artist_top_songs` | Artist's popular songs |
| `get_similar_artists` | Find similar artists |
| `get_recommendations` | Personalized recommendations |
| `get_heavy_rotation` | Your frequently played |
| `get_personal_station` | Your personal radio station |
| `get_song_station` | Radio station from a song |
| `get_charts` | Top songs, albums, playlists |
| `get_genres` | List all genres |
| `get_storefronts` | List Apple Music regions |
| `get_search_suggestions` | Autocomplete suggestions |
| `get_music_videos` | Search music videos |

### Playback *(macOS)*
| Tool | Description |
|------|-------------|
| `play_track` | Play any track (library first, then catalog) |
| `play_playlist` | Start playing a playlist |
| `playback_control` | Play, pause, stop, next, previous |
| `get_now_playing` | Current track info |
| `get_player_state` | Get playing/paused/stopped state |
| `seek_to_position` | Seek within current track |
| `set_volume` | Set volume (0-100) |
| `set_shuffle` | Toggle shuffle |
| `set_repeat` | Set repeat mode (off, one, all) |
| `get_volume_and_playback` | Get current settings |

### Utilities
| Tool | Description |
|------|-------------|
| `check_auth_status` | Verify tokens and connection |
| `get_airplay_devices` | List AirPlay devices *(macOS)* |
| `reveal_in_music` | Show track in Music app *(macOS)* |
| `get_cache_info` | Show CSV cache info |
| `clear_cache` | Clear cached exports |

### Output Format

Track listings auto-select the best format that fits:
- **Full**: Name - Artist (duration) Album [Year] Genre id
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
