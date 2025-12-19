# mcp-applemusic-api

An MCP (Model Context Protocol) server for managing Apple Music playlists via the official Apple Music API.

**Unlike AppleScript-based solutions, this actually works for adding/removing tracks from playlists.**

## Features

- ✅ **List playlists** with track counts and editability status
- ✅ **Create playlists** via API (these are editable)
- ✅ **Add tracks** to API-created playlists
- ✅ **Search** your library and the Apple Music catalog
- ✅ **Playback controls** (play, pause, next, previous)
- ✅ **Get current track** info

## Why This Exists

AppleScript-based Apple Music automation is broken for playlist modification in modern macOS - commands execute but silently fail to add tracks. The Apple Music REST API actually works, but requires proper authentication.

## Prerequisites

1. **Apple Developer Account** (free or paid)
2. **macOS** with Apple Music app
3. **Python 3.10+**
4. **Active Apple Music subscription** (for user token)

## Setup

### 1. Create MusicKit Credentials

1. Go to [Apple Developer Portal](https://developer.apple.com/account/resources/authkeys/list)
2. Create a new **Key** with **MusicKit** enabled
3. Download the `.p8` private key file (you can only download once!)
4. Note your **Key ID** (shown after creation)
5. Note your **Team ID** (from Membership page)

### 2. Install the Package

```bash
# Clone the repo
git clone https://github.com/epheterson/mcp-applemusic-api.git
cd mcp-applemusic-api

# Create virtual environment and install
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

> **Note:** This is an MCP "server" in name only. You don't run it manually—Claude Code launches it automatically when needed.

### 3. Configure Credentials

```bash
# Copy your .p8 key
cp /path/to/AuthKey_XXXXXXXX.p8 ~/.config/applemusic-mcp/

# Create config file
cat > ~/.config/applemusic-mcp/config.json << EOF
{
  "team_id": "YOUR_TEAM_ID",
  "key_id": "YOUR_KEY_ID",
  "private_key_path": "~/.config/applemusic-mcp/AuthKey_XXXXXXXX.p8"
}
EOF
```

### 4. Generate Developer Token

```bash
applemusic-mcp generate-token
```

This creates a JWT valid for 180 days.

### 5. Authorize User Access

```bash
applemusic-mcp authorize
```

This opens a browser for Apple ID login. After authorizing, the Music User Token is saved.

### 6. Configure Claude Code

Add to your Claude Code MCP settings (`~/.claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "applemusic": {
      "command": "/path/to/mcp-applemusic-api/venv/bin/python",
      "args": ["-m", "applemusic_mcp"]
    }
  }
}
```

## Usage

Once configured, Claude can:

```
"List my Apple Music playlists"
"Add 'Wonderwall' by Oasis to my workout playlist"
"Create a new playlist called 'Road Trip 2024'"
"Search my library for songs by The Beatles"
"What's currently playing?"
```

## Important Limitations

### Playlist Editability

The Apple Music API can only edit playlists that were **created via the API**. Playlists created in iTunes/Music app are read-only via API.

**Workaround:** Create a new playlist via Claude, then copy tracks from the old playlist.

### Token Expiration

- **Developer Token:** Valid 180 days, regenerate with `applemusic-mcp generate-token`
- **Music User Token:** Expires periodically, re-authorize with `applemusic-mcp authorize`

## Tools Available

| Tool | Description |
|------|-------------|
| `music_play` | Start playback |
| `music_pause` | Pause playback |
| `music_next` | Next track |
| `music_previous` | Previous track |
| `music_current_track` | Get now playing info |
| `music_play_playlist` | Play a playlist by name |
| `music_list_playlists` | List all playlists (local) |
| `api_get_library_playlists` | List playlists with IDs and editability |
| `api_search_catalog` | Search Apple Music catalog |
| `api_get_library_songs` | Search your library |
| `api_create_playlist` | Create a new playlist |
| `api_add_to_playlist` | Add tracks to a playlist |
| `check_auth_status` | Verify tokens are valid |

## Troubleshooting

### "Unauthorized" during browser auth
- Make sure you're serving auth.html via HTTP, not file://
- Run `applemusic-mcp authorize` which handles this

### "Unable to update tracks" error
- The playlist wasn't created via API
- Create a new playlist with `api_create_playlist` first

### Token expired
- Developer token: `applemusic-mcp generate-token`
- User token: `applemusic-mcp authorize`

## License

MIT

## Credits

Built to solve the "AppleScript playlist editing is broken" problem. Inspired by frustration with existing solutions that don't actually work.
