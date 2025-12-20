"""AppleScript integration for Music.app on macOS.

This module provides direct control of the Music app via AppleScript,
enabling capabilities not available through the REST API like playback
control, deleting tracks from playlists, and deleting playlists.

Only available on macOS with the Music app installed.

Security Notes:
    - All user input (track names, playlist names, etc.) is escaped via
      _escape_for_applescript() which escapes backslashes first, then quotes,
      before embedding in AppleScript strings. This prevents injection attacks.
    - Scripts are executed via subprocess.run() with capture_output=True
      and a 30-second timeout to prevent hangs.
    - The osascript binary location is verified via shutil.which() before use.
"""

import subprocess
import sys
import shutil
from typing import Optional


def is_available() -> bool:
    """Check if AppleScript is available (macOS with osascript)."""
    return sys.platform == 'darwin' and shutil.which('osascript') is not None


def _escape_for_applescript(s: str) -> str:
    """Escape a string for safe use in AppleScript.

    Backslashes must be escaped first, then quotes, to prevent
    injection attacks and handle edge cases like 'Playlist\\Test'.
    """
    return s.replace('\\', '\\\\').replace('"', '\\"')


def run_applescript(script: str) -> tuple[bool, str]:
    """Execute AppleScript and return (success, output/error).

    Args:
        script: AppleScript code to execute

    Returns:
        Tuple of (success: bool, output: str)
        On success, output is the script's return value.
        On failure, output is the error message.
    """
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "AppleScript timed out after 30 seconds"
    except Exception as e:
        return False, str(e)


# =============================================================================
# Playback Control
# =============================================================================

def play() -> tuple[bool, str]:
    """Start or resume playback."""
    return run_applescript('tell application "Music" to play')


def pause() -> tuple[bool, str]:
    """Pause playback."""
    return run_applescript('tell application "Music" to pause')


def playpause() -> tuple[bool, str]:
    """Toggle play/pause."""
    return run_applescript('tell application "Music" to playpause')


def stop() -> tuple[bool, str]:
    """Stop playback."""
    return run_applescript('tell application "Music" to stop')


def next_track() -> tuple[bool, str]:
    """Skip to next track."""
    return run_applescript('tell application "Music" to next track')


def previous_track() -> tuple[bool, str]:
    """Go to previous track."""
    return run_applescript('tell application "Music" to previous track')


def get_player_state() -> tuple[bool, str]:
    """Get current player state (playing, paused, stopped)."""
    return run_applescript('tell application "Music" to get player state as string')


def get_current_track() -> tuple[bool, dict]:
    """Get info about currently playing track.

    Returns:
        Tuple of (success, track_info_dict or error_string)
    """
    script = '''
    tell application "Music"
        if player state is stopped then
            return "STOPPED"
        end if
        set t to current track
        set output to ""
        set output to output & "name:" & (name of t) & "\\n"
        set output to output & "artist:" & (artist of t) & "\\n"
        set output to output & "album:" & (album of t) & "\\n"
        set output to output & "duration:" & (duration of t) & "\\n"
        set output to output & "position:" & (player position) & "\\n"
        try
            set output to output & "genre:" & (genre of t) & "\\n"
        end try
        try
            set output to output & "year:" & (year of t) & "\\n"
        end try
        return output
    end tell
    '''
    success, output = run_applescript(script)
    if not success:
        return False, output
    if output == "STOPPED":
        return True, {"state": "stopped"}

    # Parse key:value pairs
    track_info = {"state": "playing"}
    for line in output.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            track_info[key.strip()] = value.strip()
    return True, track_info


def get_volume() -> tuple[bool, int]:
    """Get current volume (0-100)."""
    success, output = run_applescript('tell application "Music" to get sound volume')
    if success:
        try:
            return True, int(output)
        except ValueError:
            return False, f"Invalid volume value: {output}"
    return False, output


def set_volume(volume: int) -> tuple[bool, str]:
    """Set volume (0-100)."""
    volume = max(0, min(100, volume))
    return run_applescript(f'tell application "Music" to set sound volume to {volume}')


def get_shuffle() -> tuple[bool, bool]:
    """Get shuffle state."""
    success, output = run_applescript('tell application "Music" to get shuffle enabled')
    if success:
        return True, output.lower() == 'true'
    return False, output


def set_shuffle(enabled: bool) -> tuple[bool, str]:
    """Set shuffle on/off."""
    value = 'true' if enabled else 'false'
    return run_applescript(f'tell application "Music" to set shuffle enabled to {value}')


def get_repeat() -> tuple[bool, str]:
    """Get repeat mode (off, one, all)."""
    return run_applescript('tell application "Music" to get song repeat as string')


def set_repeat(mode: str) -> tuple[bool, str]:
    """Set repeat mode (off, one, all)."""
    if mode not in ('off', 'one', 'all'):
        return False, f"Invalid repeat mode: {mode}. Use 'off', 'one', or 'all'"
    return run_applescript(f'tell application "Music" to set song repeat to {mode}')


def seek(position: float) -> tuple[bool, str]:
    """Seek to position in seconds."""
    return run_applescript(f'tell application "Music" to set player position to {position}')


# =============================================================================
# Playlist Operations
# =============================================================================

def get_playlists() -> tuple[bool, list[dict]]:
    """Get all user playlists with details.

    Returns:
        Tuple of (success, list of playlist dicts or error string)
    """
    script = '''
    tell application "Music"
        set output to ""
        repeat with p in user playlists
            set pName to name of p
            set pId to persistent ID of p
            set pSmart to smart of p
            set pCount to count of tracks of p
            try
                set pTime to time of p
            on error
                set pTime to "0:00"
            end try
            set output to output & pName & "|||" & pId & "|||" & pSmart & "|||" & pCount & "|||" & pTime & "\\n"
        end repeat
        return output
    end tell
    '''
    success, output = run_applescript(script)
    if not success:
        return False, output

    playlists = []
    for line in output.split('\n'):
        if '|||' in line:
            parts = line.split('|||')
            if len(parts) >= 5:
                playlists.append({
                    'name': parts[0],
                    'id': parts[1],
                    'smart': parts[2].lower() == 'true',
                    'track_count': int(parts[3]) if parts[3].isdigit() else 0,
                    'duration': parts[4]
                })
    return True, playlists


def get_playlist_tracks(playlist_name: str, limit: int = 500) -> tuple[bool, list[dict]]:
    """Get tracks in a playlist by name.

    Args:
        playlist_name: Name of the playlist
        limit: Maximum number of tracks to return (default 500)

    Returns:
        Tuple of (success, list of track dicts or error string)
    """
    # Escape quotes in playlist name
    safe_name = _escape_for_applescript(playlist_name)
    script = f'''
    tell application "Music"
        try
            set targetPlaylist to first user playlist whose name is "{safe_name}"
        on error
            return "ERROR:Playlist not found: {safe_name}"
        end try

        set output to ""
        set trackLimit to {limit}
        set trackCount to 0
        repeat with t in tracks of targetPlaylist
            if trackCount >= trackLimit then exit repeat
            set tName to name of t
            set tArtist to artist of t
            set tAlbum to album of t
            set tDuration to duration of t
            set tId to persistent ID of t
            try
                set tGenre to genre of t
            on error
                set tGenre to ""
            end try
            try
                set tYear to year of t as string
            on error
                set tYear to ""
            end try
            set output to output & tName & "|||" & tArtist & "|||" & tAlbum & "|||" & tDuration & "|||" & tGenre & "|||" & tYear & "|||" & tId & "\\n"
            set trackCount to trackCount + 1
        end repeat
        return output
    end tell
    '''
    success, output = run_applescript(script)
    if not success:
        return False, output
    if output.startswith("ERROR:"):
        return False, output[6:]

    tracks = []
    for line in output.split('\n'):
        if '|||' in line:
            parts = line.split('|||')
            if len(parts) >= 7:
                # Format duration
                try:
                    dur_sec = float(parts[3])
                    minutes = int(dur_sec) // 60
                    seconds = int(dur_sec) % 60
                    duration = f"{minutes}:{seconds:02d}"
                except (ValueError, TypeError):
                    duration = ""

                tracks.append({
                    'name': parts[0],
                    'artist': parts[1],
                    'album': parts[2],
                    'duration': duration,
                    'genre': parts[4],
                    'year': parts[5],
                    'id': parts[6]
                })
    return True, tracks


def create_playlist(name: str, description: str = "") -> tuple[bool, str]:
    """Create a new playlist.

    Args:
        name: Playlist name
        description: Optional description

    Returns:
        Tuple of (success, playlist_id or error)
    """
    safe_name = _escape_for_applescript(name)
    safe_desc = _escape_for_applescript(description)

    if description:
        script = f'''
        tell application "Music"
            set newPlaylist to make new user playlist with properties {{name:"{safe_name}", description:"{safe_desc}"}}
            return persistent ID of newPlaylist
        end tell
        '''
    else:
        script = f'''
        tell application "Music"
            set newPlaylist to make new user playlist with properties {{name:"{safe_name}"}}
            return persistent ID of newPlaylist
        end tell
        '''
    return run_applescript(script)


def delete_playlist(playlist_name: str) -> tuple[bool, str]:
    """Delete a playlist by name.

    Args:
        playlist_name: Name of the playlist to delete

    Returns:
        Tuple of (success, message or error)
    """
    safe_name = _escape_for_applescript(playlist_name)
    script = f'''
    tell application "Music"
        try
            set targetPlaylist to first user playlist whose name is "{safe_name}"
            delete targetPlaylist
            return "Deleted playlist: {safe_name}"
        on error errMsg
            return "ERROR:" & errMsg
        end try
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


def add_track_to_playlist(playlist_name: str, track_name: str, artist: Optional[str] = None) -> tuple[bool, str]:
    """Add a track from library to a playlist.

    Args:
        playlist_name: Target playlist name
        track_name: Name of the track to add
        artist: Optional artist name to disambiguate

    Returns:
        Tuple of (success, message or error)
    """
    safe_playlist = _escape_for_applescript(playlist_name)
    safe_track = _escape_for_applescript(track_name)

    if artist:
        safe_artist = _escape_for_applescript(artist)
        track_query = f'first track of library playlist 1 whose name is "{safe_track}" and artist contains "{safe_artist}"'
    else:
        track_query = f'first track of library playlist 1 whose name is "{safe_track}"'

    script = f'''
    tell application "Music"
        try
            set targetPlaylist to first user playlist whose name is "{safe_playlist}"
        on error
            return "ERROR:Playlist not found: {safe_playlist}"
        end try
        try
            set targetTrack to {track_query}
        on error
            return "ERROR:Track not found: {safe_track}"
        end try
        duplicate targetTrack to targetPlaylist
        return "Added " & name of targetTrack & " to " & name of targetPlaylist
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


def remove_track_from_playlist(playlist_name: str, track_name: str, artist: Optional[str] = None) -> tuple[bool, str]:
    """Remove a track from a playlist (not from library).

    Args:
        playlist_name: Playlist to remove from
        track_name: Name of the track to remove
        artist: Optional artist name to disambiguate

    Returns:
        Tuple of (success, message or error)
    """
    safe_playlist = _escape_for_applescript(playlist_name)
    safe_track = _escape_for_applescript(track_name)

    if artist:
        safe_artist = _escape_for_applescript(artist)
        track_filter = f'whose name is "{safe_track}" and artist contains "{safe_artist}"'
    else:
        track_filter = f'whose name is "{safe_track}"'

    script = f'''
    tell application "Music"
        try
            set targetPlaylist to first user playlist whose name is "{safe_playlist}"
        on error
            return "ERROR:Playlist not found: {safe_playlist}"
        end try
        try
            set targetTrack to (first track of targetPlaylist {track_filter})
        on error
            return "ERROR:Track not found in playlist: {safe_track}"
        end try
        set trackName to name of targetTrack
        delete targetTrack
        return "Removed " & trackName & " from {safe_playlist}"
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


def play_playlist(playlist_name: str, shuffle: bool = False) -> tuple[bool, str]:
    """Start playing a playlist.

    Args:
        playlist_name: Name of the playlist to play
        shuffle: Whether to shuffle the playlist

    Returns:
        Tuple of (success, message or error)
    """
    safe_name = _escape_for_applescript(playlist_name)
    shuffle_cmd = "set shuffle enabled to true" if shuffle else "set shuffle enabled to false"

    script = f'''
    tell application "Music"
        try
            set targetPlaylist to first user playlist whose name is "{safe_name}"
        on error
            return "ERROR:Playlist not found: {safe_name}"
        end try
        {shuffle_cmd}
        play targetPlaylist
        return "Now playing: {safe_name}"
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


def play_track(track_name: str, artist: Optional[str] = None) -> tuple[bool, str]:
    """Play a specific track from library.

    Args:
        track_name: Name of the track to play
        artist: Optional artist name to disambiguate

    Returns:
        Tuple of (success, message or error)
    """
    safe_track = _escape_for_applescript(track_name)

    if artist:
        safe_artist = _escape_for_applescript(artist)
        track_query = f'first track of library playlist 1 whose name contains "{safe_track}" and artist contains "{safe_artist}"'
    else:
        track_query = f'first track of library playlist 1 whose name contains "{safe_track}"'

    script = f'''
    tell application "Music"
        try
            set targetTrack to {track_query}
        on error
            return "ERROR:Track not found: {safe_track}"
        end try
        play targetTrack
        return "Now playing: " & name of targetTrack & " by " & artist of targetTrack
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


# =============================================================================
# Library Search
# =============================================================================

def search_library(query: str, search_type: str = "all") -> tuple[bool, list[dict]]:
    """Search the local library.

    Args:
        query: Search query
        search_type: Type of search - "all", "artists", "albums", "songs"

    Returns:
        Tuple of (success, list of track dicts or error)
    """
    safe_query = _escape_for_applescript(query)

    # Map search types to AppleScript search kinds
    search_map = {
        "all": "",
        "artists": "only artists",
        "albums": "only albums",
        "songs": "only songs"
    }
    search_modifier = search_map.get(search_type, "")

    script = f'''
    tell application "Music"
        set searchResults to search library playlist 1 for "{safe_query}" {search_modifier}
        set output to ""
        set maxResults to 100
        set resultCount to 0
        repeat with t in searchResults
            if resultCount >= maxResults then exit repeat
            set tName to name of t
            set tArtist to artist of t
            set tAlbum to album of t
            set tDuration to duration of t
            set tId to persistent ID of t
            try
                set tGenre to genre of t
            on error
                set tGenre to ""
            end try
            try
                set tYear to year of t as string
            on error
                set tYear to ""
            end try
            set output to output & tName & "|||" & tArtist & "|||" & tAlbum & "|||" & tDuration & "|||" & tGenre & "|||" & tYear & "|||" & tId & "\\n"
            set resultCount to resultCount + 1
        end repeat
        return output
    end tell
    '''
    success, output = run_applescript(script)
    if not success:
        return False, output

    tracks = []
    for line in output.split('\n'):
        if '|||' in line:
            parts = line.split('|||')
            if len(parts) >= 7:
                try:
                    dur_sec = float(parts[3])
                    minutes = int(dur_sec) // 60
                    seconds = int(dur_sec) % 60
                    duration = f"{minutes}:{seconds:02d}"
                except (ValueError, TypeError):
                    duration = ""

                tracks.append({
                    'name': parts[0],
                    'artist': parts[1],
                    'album': parts[2],
                    'duration': duration,
                    'genre': parts[4],
                    'year': parts[5],
                    'id': parts[6]
                })
    return True, tracks


# =============================================================================
# Track Metadata
# =============================================================================

def love_track(track_name: str, artist: Optional[str] = None) -> tuple[bool, str]:
    """Mark a track as loved.

    Args:
        track_name: Name of the track
        artist: Optional artist name to disambiguate

    Returns:
        Tuple of (success, message or error)
    """
    safe_track = _escape_for_applescript(track_name)

    if artist:
        safe_artist = _escape_for_applescript(artist)
        track_query = f'first track of library playlist 1 whose name is "{safe_track}" and artist contains "{safe_artist}"'
    else:
        track_query = f'first track of library playlist 1 whose name is "{safe_track}"'

    script = f'''
    tell application "Music"
        try
            set targetTrack to {track_query}
        on error
            return "ERROR:Track not found: {safe_track}"
        end try
        set loved of targetTrack to true
        set disliked of targetTrack to false
        return "Loved: " & name of targetTrack
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


def dislike_track(track_name: str, artist: Optional[str] = None) -> tuple[bool, str]:
    """Mark a track as disliked.

    Args:
        track_name: Name of the track
        artist: Optional artist name to disambiguate

    Returns:
        Tuple of (success, message or error)
    """
    safe_track = _escape_for_applescript(track_name)

    if artist:
        safe_artist = _escape_for_applescript(artist)
        track_query = f'first track of library playlist 1 whose name is "{safe_track}" and artist contains "{safe_artist}"'
    else:
        track_query = f'first track of library playlist 1 whose name is "{safe_track}"'

    script = f'''
    tell application "Music"
        try
            set targetTrack to {track_query}
        on error
            return "ERROR:Track not found: {safe_track}"
        end try
        set disliked of targetTrack to true
        set loved of targetTrack to false
        return "Disliked: " & name of targetTrack
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


def get_rating(track_name: str, artist: Optional[str] = None) -> tuple[bool, int]:
    """Get track rating (0-100, where 20=1 star, 40=2 stars, etc).

    Args:
        track_name: Name of the track
        artist: Optional artist name to disambiguate

    Returns:
        Tuple of (success, rating 0-100 or error message)
    """
    safe_track = _escape_for_applescript(track_name)

    if artist:
        safe_artist = _escape_for_applescript(artist)
        track_query = f'first track of library playlist 1 whose name is "{safe_track}" and artist contains "{safe_artist}"'
    else:
        track_query = f'first track of library playlist 1 whose name is "{safe_track}"'

    script = f'''
    tell application "Music"
        try
            set targetTrack to {track_query}
        on error
            return "ERROR:Track not found: {safe_track}"
        end try
        return rating of targetTrack as integer
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    try:
        return True, int(output)
    except (ValueError, TypeError):
        return False, f"Invalid rating value: {output}"


def set_rating(track_name: str, rating: int, artist: Optional[str] = None) -> tuple[bool, str]:
    """Set track rating (0-100, where 20=1 star, 40=2 stars, etc).

    Args:
        track_name: Name of the track
        rating: Rating value 0-100
        artist: Optional artist name to disambiguate

    Returns:
        Tuple of (success, message or error)
    """
    safe_track = _escape_for_applescript(track_name)
    rating = max(0, min(100, rating))

    if artist:
        safe_artist = _escape_for_applescript(artist)
        track_query = f'first track of library playlist 1 whose name is "{safe_track}" and artist contains "{safe_artist}"'
    else:
        track_query = f'first track of library playlist 1 whose name is "{safe_track}"'

    script = f'''
    tell application "Music"
        try
            set targetTrack to {track_query}
        on error
            return "ERROR:Track not found: {safe_track}"
        end try
        set rating of targetTrack to {rating}
        return "Set rating to {rating} for: " & name of targetTrack
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


# =============================================================================
# AirPlay
# =============================================================================

def get_airplay_devices() -> tuple[bool, list[str]]:
    """Get list of available AirPlay devices."""
    script = '''
    tell application "Music"
        set deviceNames to name of every AirPlay device
        set output to ""
        repeat with d in deviceNames
            set output to output & d & "\\n"
        end repeat
        return output
    end tell
    '''
    success, output = run_applescript(script)
    if not success:
        return False, output

    devices = [d.strip() for d in output.split('\n') if d.strip()]
    return True, devices


# =============================================================================
# Utilities
# =============================================================================

def reveal_track(track_name: str, artist: Optional[str] = None) -> tuple[bool, str]:
    """Reveal a track in the Music app window.

    Args:
        track_name: Name of the track
        artist: Optional artist name to disambiguate

    Returns:
        Tuple of (success, message or error)
    """
    safe_track = _escape_for_applescript(track_name)

    if artist:
        safe_artist = _escape_for_applescript(artist)
        track_query = f'first track of library playlist 1 whose name contains "{safe_track}" and artist contains "{safe_artist}"'
    else:
        track_query = f'first track of library playlist 1 whose name contains "{safe_track}"'

    script = f'''
    tell application "Music"
        try
            set targetTrack to {track_query}
        on error
            return "ERROR:Track not found: {safe_track}"
        end try
        reveal targetTrack
        activate
        return "Revealed: " & name of targetTrack
    end tell
    '''
    success, output = run_applescript(script)
    if output.startswith("ERROR:"):
        return False, output[6:]
    return success, output


def get_library_stats() -> tuple[bool, dict]:
    """Get library statistics."""
    script = '''
    tell application "Music"
        set trackCount to count of tracks of library playlist 1
        set playlistCount to count of user playlists
        set playerState to player state as string
        set shuffleState to shuffle enabled
        set repeatState to song repeat as string
        set vol to sound volume

        return trackCount & "|||" & playlistCount & "|||" & playerState & "|||" & shuffleState & "|||" & repeatState & "|||" & vol
    end tell
    '''
    success, output = run_applescript(script)
    if not success:
        return False, output

    parts = output.split('|||')
    if len(parts) >= 6:
        return True, {
            'track_count': int(parts[0]) if parts[0].isdigit() else 0,
            'playlist_count': int(parts[1]) if parts[1].isdigit() else 0,
            'player_state': parts[2],
            'shuffle': parts[3].lower() == 'true',
            'repeat': parts[4],
            'volume': int(parts[5]) if parts[5].isdigit() else 0
        }
    return False, "Failed to parse library stats"
