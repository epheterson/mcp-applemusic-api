#!/usr/bin/env python3
"""
Integration test script for Apple Music MCP server.
Hits all endpoints sequentially, reusing resources, and validates output.
"""

import sys
import re
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from applemusic_mcp import server

# Track resources created for cleanup
CLEANUP_ITEMS = []
OUTPUT_LOG = []


def log(msg: str, indent: int = 0):
    """Log message to console and output log."""
    prefix = "  " * indent
    print(f"{prefix}{msg}")
    OUTPUT_LOG.append(f"{prefix}{msg}")


def check(name: str, result: str, expectations: list[str], anti_expectations: list[str] = None):
    """Check result against expectations and log."""
    log(f"\n{'='*60}")
    log(f"TEST: {name}")
    log(f"{'='*60}")

    # Show first 500 chars of result
    preview = result[:500] + "..." if len(result) > 500 else result
    log(f"Result preview:\n{preview}\n")

    passed = True

    # Check expected patterns
    for exp in expectations:
        if exp in result:
            log(f"  [PASS] Contains: {exp[:50]}{'...' if len(exp) > 50 else ''}")
        else:
            log(f"  [FAIL] Missing: {exp[:50]}{'...' if len(exp) > 50 else ''}")
            passed = False

    # Check anti-patterns (things that should NOT be present)
    for anti in (anti_expectations or []):
        if anti in result:
            log(f"  [FAIL] Should NOT contain: {anti[:50]}")
            passed = False
        else:
            log(f"  [PASS] Correctly missing: {anti[:50]}")

    return passed


def run_tests():
    """Run all integration tests."""
    log(f"Apple Music MCP Integration Test")
    log(f"Started: {datetime.now().isoformat()}")
    log(f"")

    results = {"passed": 0, "failed": 0}

    # ============ AUTH STATUS ============
    try:
        result = server.check_auth_status()
        if check("check_auth_status", result,
                 ["Developer Token:", "Music User Token:", "API Connection:"],
                 ["Error", "MISSING"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ PLAYLISTS ============
    try:
        result = server.get_library_playlists()
        if check("get_library_playlists", result,
                 ["playlists", "Full data:", ".csv", "ID:"]):
            results["passed"] += 1
            # Extract a playlist ID for later tests
            match = re.search(r'ID: (p\.[^,\)]+)', result)
            playlist_id = match.group(1) if match else None
        else:
            results["failed"] += 1
            playlist_id = None
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1
        playlist_id = None

    # ============ PLAYLIST TRACKS ============
    if playlist_id:
        try:
            result = server.get_playlist_tracks(playlist_id)
            # Check for new format: Name - Artist (duration) Album [Year] Genre id
            if check("get_playlist_tracks", result,
                     ["tracks", "Full data:", ".csv"],
                     ["(ID:"]):  # Old format had (ID: xxx)
                results["passed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            log(f"  [ERROR] {e}")
            results["failed"] += 1

    # ============ LIBRARY SONGS ============
    try:
        result = server.get_library_songs(limit=10)
        if check("get_library_songs (limit=10)", result,
                 ["songs", "Full data:", ".csv"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ LIBRARY ALBUMS ============
    try:
        result = server.get_library_albums()
        if check("get_library_albums", result,
                 ["albums", "Full data:", ".csv"]):
            results["passed"] += 1
            # Extract an album ID for later tests
            match = re.search(r'(l\.[A-Za-z0-9]+)', result)
            library_album_id = match.group(1) if match else None
        else:
            results["failed"] += 1
            library_album_id = None
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1
        library_album_id = None

    # ============ ALBUM TRACKS ============
    if library_album_id:
        try:
            result = server.get_album_tracks(library_album_id)
            # Should have numbered format: 1. Name - Artist (duration)
            if check("get_album_tracks (library)", result,
                     ["tracks", "Full data:", ".csv", ". "]):  # "1. " format
                results["passed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            log(f"  [ERROR] {e}")
            results["failed"] += 1

    # ============ LIBRARY ARTISTS ============
    try:
        result = server.get_library_artists()
        if check("get_library_artists", result,
                 ["artists", "Full data:", ".csv"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ SEARCH LIBRARY ============
    try:
        result = server.search_library("love", limit=5)
        if check("search_library ('love')", result,
                 ["results", "Full data:", ".csv"]):
            results["passed"] += 1
            # Extract a song ID for later
            match = re.search(r'(i\.[A-Za-z0-9]+)', result)
            library_song_id = match.group(1) if match else None
        else:
            results["failed"] += 1
            library_song_id = None
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1
        library_song_id = None

    # ============ SEARCH CATALOG ============
    try:
        result = server.search_catalog("Beatles", types="songs", limit=5)
        # Should have explicit markers and new format
        if check("search_catalog ('Beatles')", result,
                 ["Songs", "Full data:", ".csv"]):
            results["passed"] += 1
            # Extract a catalog song ID
            match = re.search(r'\s(\d{5,})\s*$', result, re.MULTILINE)
            catalog_song_id = match.group(1) if match else None
        else:
            results["failed"] += 1
            catalog_song_id = None
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1
        catalog_song_id = None

    # ============ RECENTLY PLAYED ============
    try:
        result = server.get_recently_played(limit=5)
        if check("get_recently_played", result,
                 ["recently played", "Full data:", ".csv"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ RECENTLY ADDED ============
    try:
        result = server.get_recently_added(limit=10)
        if check("get_recently_added", result,
                 ["recently added", "Full data:", ".csv"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ HEAVY ROTATION ============
    try:
        result = server.get_heavy_rotation()
        if check("get_heavy_rotation", result,
                 ["heavy rotation", "Full data:", ".csv"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ RECOMMENDATIONS ============
    try:
        result = server.get_recommendations()
        if check("get_recommendations", result,
                 ["recommendation", "Full data:"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ SONG DETAILS ============
    if catalog_song_id:
        try:
            result = server.get_song_details(catalog_song_id)
            # Should use format_duration helper (m:ss format)
            if check("get_song_details", result,
                     ["Title:", "Artist:", "Album:", "Duration:", "Genre:"]):
                results["passed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            log(f"  [ERROR] {e}")
            results["failed"] += 1

    # ============ ARTIST DETAILS ============
    try:
        result = server.get_artist_details("The Beatles")
        if check("get_artist_details", result,
                 ["Artist:", "Genres:"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ ARTIST TOP SONGS ============
    try:
        result = server.get_artist_top_songs("Oasis")
        if check("get_artist_top_songs", result,
                 ["Top Songs", "catalog ID:"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ SIMILAR ARTISTS ============
    try:
        result = server.get_similar_artists("Oasis")
        if check("get_similar_artists", result,
                 ["Similar"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ CHARTS ============
    try:
        result = server.get_charts("songs")
        if check("get_charts", result,
                 ["==="]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ GENRES ============
    try:
        result = server.get_genres()
        if check("get_genres", result,
                 ["ID:"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ SEARCH SUGGESTIONS ============
    try:
        result = server.get_search_suggestions("tay")
        if check("get_search_suggestions", result,
                 ["Suggestions"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ CACHE INFO ============
    try:
        result = server.get_cache_info()
        if check("get_cache_info", result,
                 ["Cache:", ".csv"]):
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ CREATE PLAYLIST (for testing, will cleanup) ============
    test_playlist_id = None
    try:
        result = server.create_playlist("__TEST_PLAYLIST__", "Integration test - delete me")
        if check("create_playlist", result,
                 ["Created", "__TEST_PLAYLIST__", "ID:"]):
            results["passed"] += 1
            match = re.search(r'ID: (p\.[A-Za-z0-9]+)', result)
            if match:
                test_playlist_id = match.group(1)
                CLEANUP_ITEMS.append(f"Delete playlist: {test_playlist_id}")
        else:
            results["failed"] += 1
    except Exception as e:
        log(f"  [ERROR] {e}")
        results["failed"] += 1

    # ============ ADD TO PLAYLIST ============
    if test_playlist_id and library_song_id:
        try:
            result = server.add_to_playlist(
                playlist_id=test_playlist_id, track_ids=library_song_id
            )
            if check("add_to_playlist", result,
                     ["Added", "track"]):
                results["passed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            log(f"  [ERROR] {e}")
            results["failed"] += 1

    # ============ SUMMARY ============
    log(f"\n{'='*60}")
    log(f"SUMMARY")
    log(f"{'='*60}")
    log(f"Passed: {results['passed']}")
    log(f"Failed: {results['failed']}")
    log(f"Total:  {results['passed'] + results['failed']}")
    log(f"")

    if CLEANUP_ITEMS:
        log("CLEANUP NEEDED:")
        for item in CLEANUP_ITEMS:
            log(f"  - {item}")
    else:
        log("No cleanup needed.")

    log(f"\nCompleted: {datetime.now().isoformat()}")

    # Write full log to file
    log_file = Path(__file__).parent / "integration_test_results.txt"
    with open(log_file, "w") as f:
        f.write("\n".join(OUTPUT_LOG))
    print(f"\nFull log written to: {log_file}")

    return results["failed"] == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
