#!/usr/bin/env python3
"""
Endpoint Validation Script for Apple Music MCP Server

This script tests all 31 API endpoints against your live Apple Music library
to verify everything is working correctly. Run this after setup or when debugging.

Usage:
    python scripts/validate_endpoints.py

Requirements:
    - Valid developer token (run: applemusic-mcp generate-token)
    - Valid user token (run: applemusic-mcp authorize)
    - Active Apple Music subscription
"""

import sys
import time
from pathlib import Path

# Add the src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from applemusic_mcp import server


def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_result(name: str, result: str, success: bool):
    """Print a test result."""
    icon = "✅" if success else "❌"
    print(f"\n{icon} {name}")
    # Show first 3 lines of output for context
    lines = result.strip().split("\n")[:3]
    for line in lines:
        print(f"   {line[:80]}")
    if len(result.strip().split("\n")) > 3:
        print(f"   ... ({len(result.strip().split(chr(10)))} lines total)")


def is_success(result: str) -> bool:
    """Check if an endpoint call was successful."""
    error_indicators = [
        "API Error:",
        "Error:",
        "MISSING",
        "EXPIRED",
        "not found",
        "Failed",
    ]
    # Empty results are OK for some endpoints
    if not result or result.strip() == "":
        return False
    return not any(indicator.lower() in result.lower() for indicator in error_indicators)


def main():
    print_header("Apple Music MCP Server - Endpoint Validation")
    print("\nThis script tests all 31 endpoints against your live library.")
    print("Make sure you have valid tokens configured.\n")

    # Track results
    passed = 0
    failed = 0
    results = []

    # Store IDs for dependent tests
    test_data = {
        "playlist_id": None,
        "library_song_id": None,
        "catalog_song_id": None,
        "album_id": None,
        "artist_name": None,
    }

    # ========== STATUS CHECK ==========
    print_header("1. Authentication Status")

    result = server.check_auth_status()
    success = "OK" in result and "MISSING" not in result
    print_result("check_auth_status()", result, success)
    if success:
        passed += 1
    else:
        failed += 1
        print("\n⚠️  Authentication issues detected. Fix these before continuing.")
        print("   Run: applemusic-mcp generate-token")
        print("   Run: applemusic-mcp authorize")
        return 1

    # ========== PLAYLIST MANAGEMENT ==========
    print_header("2. Playlist Management (5 endpoints)")

    # get_library_playlists
    result = server.get_library_playlists()
    success = is_success(result) or "No playlists found" in result
    print_result("get_library_playlists()", result, success)
    results.append(("get_library_playlists", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # Extract a playlist ID for testing
    if "ID:" in result:
        for line in result.split("\n"):
            if "ID: p." in line:
                test_data["playlist_id"] = line.split("ID: ")[1].split(",")[0].strip()
                break

    # get_playlist_tracks
    if test_data["playlist_id"]:
        result = server.get_playlist_tracks(test_data["playlist_id"])
        success = is_success(result) or "empty" in result.lower()
        print_result(f"get_playlist_tracks({test_data['playlist_id'][:15]}...)", result, success)
    else:
        result = "Skipped - no playlist ID available"
        success = True
        print_result("get_playlist_tracks()", result, success)
    results.append(("get_playlist_tracks", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # create_playlist - creates a test playlist
    test_playlist_name = f"MCP Test {int(time.time())}"
    result = server.create_playlist(test_playlist_name, "Validation test")
    success = "Created" in result and "ID:" in result
    print_result(f"create_playlist('{test_playlist_name}')", result, success)
    results.append(("create_playlist", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # Extract new playlist ID
    new_playlist_id = None
    if "ID:" in result:
        new_playlist_id = result.split("ID: ")[1].split(")")[0].strip()

    # add_to_playlist - need a library song ID first
    # Get one from search_library
    search_result = server.search_library("love")
    if "library ID:" in search_result:
        for line in search_result.split("\n"):
            if "library ID:" in line:
                test_data["library_song_id"] = line.split("library ID: ")[1].split("]")[0].strip()
                break

    if new_playlist_id and test_data["library_song_id"]:
        result = server.add_to_playlist(new_playlist_id, test_data["library_song_id"])
        success = "Successfully added" in result
        print_result(f"add_to_playlist(..., {test_data['library_song_id'][:15]}...)", result, success)
    else:
        result = "Skipped - no playlist or song ID available"
        success = True
        print_result("add_to_playlist()", result, success)
    results.append(("add_to_playlist", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # copy_playlist
    if test_data["playlist_id"]:
        copy_name = f"Copy Test {int(time.time())}"
        result = server.copy_playlist(test_data["playlist_id"], copy_name)
        success = "Created" in result or "tracks" in result
        print_result(f"copy_playlist(..., '{copy_name}')", result, success)
    else:
        result = "Skipped - no source playlist available"
        success = True
        print_result("copy_playlist()", result, success)
    results.append(("copy_playlist", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # ========== LIBRARY MANAGEMENT ==========
    print_header("3. Library Management (5 endpoints)")

    # search_library
    result = server.search_library("beatles")
    success = is_success(result) or "No songs found" in result
    print_result("search_library('beatles')", result, success)
    results.append(("search_library", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_library_albums
    result = server.get_library_albums()
    success = is_success(result) or "No albums" in result
    print_result("get_library_albums()", result, success)
    results.append(("get_library_albums", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # Extract album ID
    if "library ID:" in result:
        for line in result.split("\n"):
            if "library ID:" in line:
                test_data["album_id"] = line.split("library ID: ")[1].split("]")[0].strip()
                break

    # get_library_artists
    result = server.get_library_artists()
    success = is_success(result) or "No artists" in result
    print_result("get_library_artists()", result, success)
    results.append(("get_library_artists", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # Extract artist name for later
    if "library ID:" in result:
        for line in result.split("\n"):
            if "[library ID:" in line:
                test_data["artist_name"] = line.split(" [library ID:")[0].strip()
                break

    # get_library_songs
    result = server.get_library_songs(10)
    success = is_success(result) or "No songs" in result
    print_result("get_library_songs(10)", result, success)
    results.append(("get_library_songs", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_library_music_videos
    result = server.get_library_music_videos()
    success = is_success(result) or "No music videos" in result
    print_result("get_library_music_videos()", result, success)
    results.append(("get_library_music_videos", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # ========== CATALOG SEARCH ==========
    print_header("4. Catalog Search (5 endpoints)")

    # search_catalog
    result = server.search_catalog("Wonderwall Oasis")
    success = is_success(result)
    print_result("search_catalog('Wonderwall Oasis')", result, success)
    results.append(("search_catalog", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # Extract catalog song ID
    if "catalog ID:" in result:
        for line in result.split("\n"):
            if "catalog ID:" in line:
                test_data["catalog_song_id"] = line.split("catalog ID: ")[1].split("]")[0].strip()
                break

    # get_song_details
    if test_data["catalog_song_id"]:
        result = server.get_song_details(test_data["catalog_song_id"])
        success = "Title:" in result
        print_result(f"get_song_details({test_data['catalog_song_id']})", result, success)
    else:
        result = "Skipped - no catalog song ID"
        success = True
        print_result("get_song_details()", result, success)
    results.append(("get_song_details", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_artist_details
    result = server.get_artist_details("Oasis")
    success = "Artist:" in result
    print_result("get_artist_details('Oasis')", result, success)
    results.append(("get_artist_details", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_album_tracks
    if test_data["album_id"]:
        result = server.get_album_tracks(test_data["album_id"])
        success = "Tracks" in result or "No tracks" in result
        print_result(f"get_album_tracks({test_data['album_id'][:15]}...)", result, success)
    else:
        result = "Skipped - no album ID available"
        success = True
        print_result("get_album_tracks()", result, success)
    results.append(("get_album_tracks", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_search_suggestions
    result = server.get_search_suggestions("tay")
    success = is_success(result) or "No suggestions" in result
    print_result("get_search_suggestions('tay')", result, success)
    results.append(("get_search_suggestions", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # ========== DISCOVERY & PERSONALIZATION ==========
    print_header("5. Discovery & Personalization (9 endpoints)")

    # get_recommendations
    result = server.get_recommendations()
    success = is_success(result) or "No recommendations" in result
    print_result("get_recommendations()", result, success)
    results.append(("get_recommendations", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_heavy_rotation
    result = server.get_heavy_rotation()
    success = is_success(result) or "No heavy rotation" in result
    print_result("get_heavy_rotation()", result, success)
    results.append(("get_heavy_rotation", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_recently_played
    result = server.get_recently_played()
    success = is_success(result) or "No recently played" in result
    print_result("get_recently_played()", result, success)
    results.append(("get_recently_played", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_recently_played_tracks
    result = server.get_recently_played_tracks()
    success = is_success(result) or "No recently played" in result
    print_result("get_recently_played_tracks()", result, success)
    results.append(("get_recently_played_tracks", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_recently_added
    result = server.get_recently_added()
    success = is_success(result) or "No recently added" in result
    print_result("get_recently_added()", result, success)
    results.append(("get_recently_added", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_artist_top_songs
    artist_to_search = test_data["artist_name"] or "Taylor Swift"
    result = server.get_artist_top_songs(artist_to_search)
    success = "Top Songs" in result
    print_result(f"get_artist_top_songs('{artist_to_search}')", result, success)
    results.append(("get_artist_top_songs", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_similar_artists
    result = server.get_similar_artists("Oasis")
    success = "Similar" in result or "No similar" in result
    print_result("get_similar_artists('Oasis')", result, success)
    results.append(("get_similar_artists", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_song_station
    if test_data["catalog_song_id"]:
        result = server.get_song_station(test_data["catalog_song_id"])
        success = "Station" in result
        print_result(f"get_song_station({test_data['catalog_song_id']})", result, success)
    else:
        result = "Skipped - no catalog song ID"
        success = True
        print_result("get_song_station()", result, success)
    results.append(("get_song_station", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_personal_station
    result = server.get_personal_station()
    success = "Station" in result or "personal station" in result.lower()
    print_result("get_personal_station()", result, success)
    results.append(("get_personal_station", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # ========== CATALOG BROWSING ==========
    print_header("6. Catalog Browsing (5 endpoints)")

    # get_charts
    result = server.get_charts("songs")
    success = "===" in result
    print_result("get_charts('songs')", result, success)
    results.append(("get_charts", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_music_videos
    result = server.get_music_videos("Taylor Swift")
    success = is_success(result) or "No music videos" in result
    print_result("get_music_videos('Taylor Swift')", result, success)
    results.append(("get_music_videos", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_genres
    result = server.get_genres()
    success = "ID:" in result
    print_result("get_genres()", result, success)
    results.append(("get_genres", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # get_storefronts
    result = server.get_storefronts()
    success = "Storefronts" in result
    print_result("get_storefronts()", result, success)
    results.append(("get_storefronts", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # add_to_library (test with a catalog song)
    if test_data["catalog_song_id"]:
        result = server.add_to_library(test_data["catalog_song_id"])
        # Both success and "already in library" are OK
        success = "Successfully" in result or "added" in result.lower()
        print_result(f"add_to_library({test_data['catalog_song_id']})", result, success)
    else:
        result = "Skipped - no catalog song ID"
        success = True
        print_result("add_to_library()", result, success)
    results.append(("add_to_library", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # ========== RATINGS ==========
    print_header("7. Ratings (1 endpoint)")

    # rate_song (test with love)
    if test_data["catalog_song_id"]:
        result = server.rate_song(test_data["catalog_song_id"], "love")
        success = "Successfully" in result or "Rating" in result
        print_result(f"rate_song({test_data['catalog_song_id']}, 'love')", result, success)
    else:
        result = "Skipped - no catalog song ID"
        success = True
        print_result("rate_song()", result, success)
    results.append(("rate_song", success))
    passed += 1 if success else 0
    failed += 0 if success else 1

    # ========== SUMMARY ==========
    print_header("VALIDATION SUMMARY")

    total = passed + failed
    print(f"\n  Total: {total} endpoints tested")
    print(f"  ✅ Passed: {passed}")
    print(f"  ❌ Failed: {failed}")
    print(f"  Success Rate: {passed/total*100:.1f}%")

    if failed > 0:
        print("\n  Failed endpoints:")
        for name, success in results:
            if not success:
                print(f"    - {name}")

    print(f"\n{'=' * 60}")

    # Cleanup note
    print("\n📝 Note: Test playlists were created. You may want to delete them:")
    print(f"   - '{test_playlist_name}'")
    if test_data["playlist_id"]:
        print(f"   - 'Copy Test ...'")
    print("   (Playlist deletion must be done in the Music app)")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
