"""Create test fixture library structure for Nomarr e2e tests

This script:
1. Creates Test-Songs directory with a curated subset
2. Copies files and manipulates tags for testing
3. Creates edge cases (missing metadata, etc.)
"""

import os
import shutil
from pathlib import Path

from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

TEST_MUSIC_ROOT = Path("E:/Test-Music")
TEST_SONGS_DIR = TEST_MUSIC_ROOT / "Test-Songs"

# Clean slate
if TEST_SONGS_DIR.exists():
    shutil.rmtree(TEST_SONGS_DIR)
TEST_SONGS_DIR.mkdir()

print(f"Created {TEST_SONGS_DIR}")

# Select some source files for testing
test_sources = [
    # Files that will have nom: tags (for validation testing)
    ("The Fratellis/Costello Music (Bonus Track Version)/01 Henrietta.m4a", "with-tags"),
    ("The Fratellis/Costello Music (Bonus Track Version)/02 Flathead.m4a", "with-tags"),
    ("OutKast/Stankonia/05 Ms. Jackson.m4a", "with-tags"),
    # Files that will NOT have nom: tags (for ML worker testing)
    ("LØLØ/Time as an Almighty River (2024)/01 - Doormat.m4a", "without-tags"),
    ("LØLØ/Time as an Almighty River (2024)/02 - Black Hole.m4a", "without-tags"),
    # Files for edge cases
    ("∗NSYNC/Celebrity/1. Pop.m4a", "edge-case"),
]

print("\nCopying and preparing test files...")

for source_rel, category in test_sources:
    source = TEST_MUSIC_ROOT / source_rel

    if not source.exists():
        print(f"⚠️ Source not found: {source}")
        continue

    # Create clean filename
    dest_name = f"{category}_{source.name}".replace(" ", "_")
    dest = TEST_SONGS_DIR / dest_name

    shutil.copy2(source, dest)
    print(f"✓ Copied: {dest.name}")

    try:
        # Open file for tag manipulation
        if dest.suffix == ".m4a":
            audio = MP4(str(dest))
        elif dest.suffix == ".mp3":
            audio = MP3(str(dest))
        else:
            continue

        # Add nom: tags to "with-tags" files
        if category == "with-tags":
            if dest.suffix == ".m4a":
                audio["\xa9cmt"] = ["nom:genre:rock nom:mood:energetic nom:theme:party"]
            elif dest.suffix == ".mp3":
                audio["COMM::XXX"] = "nom:genre:rock nom:mood:energetic nom:theme:party"
            audio.save()
            print(f"  → Added nom: tags")

        # Remove ALL tags from "without-tags" files (to trigger ML)
        elif category == "without-tags":
            audio.delete()
            # Re-add minimal metadata so it's still a valid file
            audio = MP4(str(dest)) if dest.suffix == ".m4a" else MP3(str(dest))
            if dest.suffix == ".m4a":
                audio["\xa9nam"] = [source.stem]
                audio["\xa9ART"] = ["Unknown Artist"]
            audio.save()
            print(f"  → Stripped tags (will need ML)")

        # Edge case: corrupt or minimal metadata
        elif category == "edge-case":
            if dest.suffix == ".m4a":
                audio["\xa9nam"] = [source.stem]
                # Missing artist, album, etc.
            audio.save()
            print(f"  → Created edge case (minimal metadata)")

    except Exception as e:
        print(f"  ⚠️ Tag manipulation failed: {e}")

print(f"\n✅ Test fixture created in {TEST_SONGS_DIR}")
print(f"   Files with nom: tags: {len([s for s in test_sources if s[1] == 'with-tags'])}")
print(f"   Files without nom: tags: {len([s for s in test_sources if s[1] == 'without-tags'])}")
print(f"   Edge case files: {len([s for s in test_sources if s[1] == 'edge-case'])}")
