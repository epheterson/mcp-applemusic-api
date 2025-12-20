#!/usr/bin/env python3
"""
AppleScript integration test for Apple Music MCP server.
Tests all AppleScript-powered tools and cleans up after itself.

Run after integration_test.py to also clean up API-created test playlists.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from applemusic_mcp import applescript as asc

OUTPUT_LOG = []
TEST_PLAYLIST_PREFIX = "__TEST_"  # Any playlist starting with this gets deleted


def log(msg: str, indent: int = 0):
    """Log message to console and output log."""
    prefix = "  " * indent
    print(f"{prefix}{msg}")
    OUTPUT_LOG.append(f"{prefix}{msg}")


def check(name: str, success: bool, result, expectations: list[str] = None):
    """Check result against expectations and log."""
    log(f"\n{'='*60}")
    log(f"TEST: {name}")
    log(f"{'='*60}")

    # Show result preview
    result_str = str(result)
    preview = result_str[:500] + "..." if len(result_str) > 500 else result_str
    log(f"Success: {success}")
    log(f"Result: {preview}\n")

    if not success:
        log(f"  [FAIL] Operation failed")
        return False

    if expectations:
        passed = True
        for exp in expectations:
            if exp in result_str:
                log(f"  [PASS] Contains: {exp[:50]}{'...' if len(exp) > 50 else ''}")
            else:
                log(f"  [FAIL] Missing: {exp[:50]}{'...' if len(exp) > 50 else ''}")
                passed = False
        return passed

    log(f"  [PASS] Operation succeeded")
    return True


def cleanup_test_playlists():
    """Delete any test playlists from both API and AppleScript tests."""
    log(f"\n{'='*60}")
    log("CLEANUP: Removing test playlists")
    log(f"{'='*60}")

    success, playlists = asc.get_playlists()
    if not success:
        log(f"  [WARN] Could not get playlists: {playlists}")
        return 0

    deleted = 0
    for p in playlists:
        name = p.get("name", "")
        if name.startswith(TEST_PLAYLIST_PREFIX):
            log(f"  Deleting: {name}")
            del_success, del_result = asc.delete_playlist(name)
            if del_success:
                log(f"    [OK] Deleted")
                deleted += 1
            else:
                log(f"    [WARN] Failed: {del_result}")

    log(f"  Cleaned up {deleted} test playlist(s)")
    return deleted


def run_tests():
    """Run all AppleScript integration tests."""
    log(f"Apple Music AppleScript Integration Test")
    log(f"Started: {datetime.now().isoformat()}")
    log(f"")

    # Check if AppleScript is available
    if not asc.is_available():
        log("[ERROR] AppleScript not available (not on macOS or osascript missing)")
        return False

    log("[OK] AppleScript is available")

    results = {"passed": 0, "failed": 0}

    # ============ PLAYBACK STATE ============
    try:
        success, state = asc.get_player_state()
        if check("get_player_state", success, state):
            results["passed"] += 1
            log(f"  Player state: {state}")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ VOLUME ============
    try:
        success, volume = asc.get_volume()
        original_volume = volume if success else 50
        if check("get_volume", success, volume):
            results["passed"] += 1
            log(f"  Current volume: {volume}")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1
        original_volume = 50

    # ============ SET VOLUME (and restore) ============
    try:
        # Set to 25, then restore
        success, result = asc.set_volume(25)
        if check("set_volume (to 25)", success, result):
            results["passed"] += 1
            # Verify it changed
            success, new_vol = asc.get_volume()
            if success and new_vol == 25:
                log(f"  [PASS] Volume confirmed at 25")
            # Restore
            asc.set_volume(original_volume)
            log(f"  Restored volume to {original_volume}")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1
        asc.set_volume(original_volume)

    # ============ SHUFFLE STATE ============
    try:
        success, shuffle = asc.get_shuffle()
        if check("get_shuffle", success, shuffle):
            results["passed"] += 1
            log(f"  Shuffle: {'on' if shuffle else 'off'}")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ REPEAT STATE ============
    try:
        success, repeat = asc.get_repeat()
        if check("get_repeat", success, repeat):
            results["passed"] += 1
            log(f"  Repeat: {repeat}")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ CURRENT TRACK ============
    try:
        success, info = asc.get_current_track()
        if check("get_current_track", success, info):
            results["passed"] += 1
            if info.get("state") == "stopped":
                log(f"  Not playing")
            else:
                log(f"  Playing: {info.get('name', 'Unknown')} - {info.get('artist', 'Unknown')}")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ GET PLAYLISTS ============
    try:
        success, playlists = asc.get_playlists()
        if check("get_playlists", success, playlists):
            results["passed"] += 1
            log(f"  Found {len(playlists)} playlists")
            # Find a playlist with tracks for later tests
            test_source_playlist = None
            test_track_name = None
            test_track_artist = None
            for p in playlists:
                if p.get("track_count", 0) > 0 and p.get("track_count", 0) < 100 and not p.get("smart"):
                    test_source_playlist = p.get("name")
                    break
        else:
            results["failed"] += 1
            test_source_playlist = None
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1
        test_source_playlist = None

    # ============ GET PLAYLIST TRACKS ============
    if test_source_playlist:
        try:
            success, tracks = asc.get_playlist_tracks(test_source_playlist, limit=10)
            if check("get_playlist_tracks", success, tracks):
                results["passed"] += 1
                log(f"  Got {len(tracks)} tracks from '{test_source_playlist}'")
                if tracks:
                    test_track_name = tracks[0].get("name")
                    test_track_artist = tracks[0].get("artist")
                    log(f"  Sample track: {test_track_name} - {test_track_artist}")
            else:
                results["failed"] += 1
        except Exception as e:
            log(f"  [ERROR] {e}")
            results["failed"] += 1
            test_track_name = None

    # ============ SEARCH LIBRARY ============
    try:
        success, results_list = asc.search_library("love", "all")
        if check("search_library ('love')", success, results_list):
            results["passed"] += 1
            log(f"  Found {len(results_list)} results")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ LIBRARY STATS ============
    try:
        success, stats = asc.get_library_stats()
        if check("get_library_stats", success, stats):
            results["passed"] += 1
            log(f"  Tracks: {stats.get('track_count', 0)}")
            log(f"  Playlists: {stats.get('playlist_count', 0)}")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ AIRPLAY DEVICES ============
    try:
        success, devices = asc.get_airplay_devices()
        if check("get_airplay_devices", success, devices):
            results["passed"] += 1
            log(f"  Found {len(devices)} AirPlay device(s)")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ CREATE TEST PLAYLIST ============
    test_playlist_name = f"{TEST_PLAYLIST_PREFIX}APPLESCRIPT_{int(time.time())}"
    try:
        success, playlist_id = asc.create_playlist(test_playlist_name, "AppleScript integration test")
        if check("create_playlist", success, playlist_id):
            results["passed"] += 1
            log(f"  Created: {test_playlist_name}")
        else:
            results["failed"] += 1
            test_playlist_name = None
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1
        test_playlist_name = None

    # ============ ADD TRACK TO PLAYLIST ============
    if test_playlist_name and test_track_name:
        try:
            success, result = asc.add_track_to_playlist(
                test_playlist_name, test_track_name, test_track_artist
            )
            if check("add_track_to_playlist", success, result):
                results["passed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            log(f"  [ERROR] {e}")
            results["failed"] += 1

        # Verify track was added
        try:
            success, tracks = asc.get_playlist_tracks(test_playlist_name)
            if success and len(tracks) > 0:
                log(f"  [PASS] Verified: playlist has {len(tracks)} track(s)")
            else:
                log(f"  [WARN] Could not verify track addition")
        except Exception:
            pass

    # ============ REMOVE TRACK FROM PLAYLIST ============
    if test_playlist_name and test_track_name:
        try:
            success, result = asc.remove_track_from_playlist(
                test_playlist_name, test_track_name, test_track_artist
            )
            if check("remove_track_from_playlist", success, result):
                results["passed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            log(f"  [ERROR] {e}")
            results["failed"] += 1

    # ============ DELETE PLAYLIST ============
    if test_playlist_name:
        try:
            success, result = asc.delete_playlist(test_playlist_name)
            if check("delete_playlist", success, result):
                results["passed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            log(f"  [ERROR] {e}")
            results["failed"] += 1

    # ============ INVALID REPEAT MODE ============
    try:
        success, result = asc.set_repeat("invalid_mode")
        if not success and "invalid" in result.lower():
            log(f"\n{'='*60}")
            log("TEST: set_repeat (invalid mode)")
            log(f"{'='*60}")
            log(f"  [PASS] Correctly rejected invalid mode")
            results["passed"] += 1
        else:
            log(f"  [FAIL] Should have rejected invalid mode")
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ NONEXISTENT PLAYLIST ============
    try:
        success, result = asc.get_playlist_tracks("__NONEXISTENT_PLAYLIST_12345__")
        if not success and "not found" in result.lower():
            log(f"\n{'='*60}")
            log("TEST: get_playlist_tracks (nonexistent)")
            log(f"{'='*60}")
            log(f"  [PASS] Correctly reported playlist not found")
            results["passed"] += 1
        else:
            log(f"  [FAIL] Should have reported not found")
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ CLEANUP ============
    cleanup_test_playlists()

    # ============ SUMMARY ============
    log(f"\n{'='*60}")
    log(f"SUMMARY")
    log(f"{'='*60}")
    log(f"Passed: {results['passed']}")
    log(f"Failed: {results['failed']}")
    log(f"Total:  {results['passed'] + results['failed']}")
    log(f"\nCompleted: {datetime.now().isoformat()}")

    # Write full log to file
    log_file = Path(__file__).parent / "integration_test_applescript_results.txt"
    with open(log_file, "w") as f:
        f.write("\n".join(OUTPUT_LOG))
    print(f"\nFull log written to: {log_file}")

    return results["failed"] == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
