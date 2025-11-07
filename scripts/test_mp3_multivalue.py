"""Quick test to check MP3 multi-value tag behavior."""

import tempfile
from pathlib import Path

from mutagen.id3 import ID3, TXXX

# Create a test MP3 file
test_file = Path(tempfile.gettempdir()) / "test_multivalue.mp3"

# Create minimal MP3 with ID3 tag
id3 = ID3()

# Add multi-value tag
moods = ["aggressive", "bass-forward", "electronic production"]
id3.add(TXXX(encoding=3, desc="nom:mood-loose", text=moods))

# Save to file (need minimal MP3 data)
test_file.write_bytes(
    b"ID3"
    + b"\x04\x00"  # Version 2.4
    + b"\x00"  # Flags
    + b"\x00\x00\x00\x00"  # Size placeholder
    + b"\xff\xfb\x90\x00"  # Minimal MP3 frame header
)

id3.save(test_file, v2_version=3)

print("=== ID3v2.3 ===")
# Read it back
id3_read = ID3(test_file)
frames = list(id3_read.getall("TXXX"))

print(f"Frames found: {len(frames)}")
for frame in frames:
    print(f"  desc: {frame.desc}")
    print(f"  text type: {type(frame.text)}")
    print(f"  text value: {frame.text}")
    print(f"  text length: {len(frame.text)}")
    if frame.text:
        print(f"  text[0]: {frame.text[0]!r}")

# Now try v2.4
print("\n=== ID3v2.4 ===")
id3_v4 = ID3()
id3_v4.add(TXXX(encoding=3, desc="nom:mood-loose", text=moods))
id3_v4.save(test_file, v2_version=4)

id3_read_v4 = ID3(test_file)
frames_v4 = list(id3_read_v4.getall("TXXX"))

print(f"Frames found: {len(frames_v4)}")
for frame in frames_v4:
    print(f"  desc: {frame.desc}")
    print(f"  text type: {type(frame.text)}")
    print(f"  text value: {frame.text}")
    print(f"  text length: {len(frame.text)}")

# Cleanup
test_file.unlink()
