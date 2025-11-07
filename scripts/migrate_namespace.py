"""
Migrate tags from one namespace to another in all audio files.

This script:
1. Scans all audio files in a directory
2. Reads tags from old namespace (e.g., "essentia:")
3. Writes same tags to new namespace (e.g., "nom:")
4. Optionally deletes old namespace tags

Usage:
    python scripts/migrate_namespace.py /path/to/music --old essentia --new nom --delete-old
"""

import argparse
import logging
from pathlib import Path

from mutagen.id3 import ID3, TXXX
from mutagen.mp4 import MP4

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def migrate_mp3_tags(file_path: str, old_ns: str, new_ns: str, delete_old: bool = False) -> int:
    """Migrate MP3 TXXX tags from old namespace to new namespace."""
    try:
        id3 = ID3(file_path)
        migrated = 0

        # Collect tags to migrate
        tags_to_migrate = {}
        frames_to_delete = []

        for frame in id3.getall("TXXX"):
            if frame.desc.startswith(f"{old_ns}:"):
                # Extract tag name without namespace prefix
                tag_name = frame.desc[len(old_ns) + 1 :]
                tags_to_migrate[tag_name] = frame.text  # text is a list for multi-value
                if delete_old:
                    frames_to_delete.append(frame)

        if not tags_to_migrate:
            return 0

        # Write tags with new namespace
        for tag_name, text_values in tags_to_migrate.items():
            new_desc = f"{new_ns}:{tag_name}"
            id3.add(TXXX(encoding=3, desc=new_desc, text=text_values))
            migrated += 1

        # Delete old tags if requested
        if delete_old:
            for frame in frames_to_delete:
                id3.delall(frame.HashKey)

        id3.save(file_path, v2_version=3)
        return migrated

    except Exception as e:
        logging.error(f"Failed to migrate {file_path}: {e}")
        return 0


def migrate_m4a_tags(file_path: str, old_ns: str, new_ns: str, delete_old: bool = False) -> int:
    """Migrate M4A freeform tags from old namespace to new namespace."""
    try:
        m4a = MP4(file_path)
        migrated = 0

        # Collect tags to migrate
        tags_to_migrate = {}
        keys_to_delete = []

        for key, value in m4a.tags.items():
            if key.startswith(f"----:com.apple.iTunes:{old_ns}:"):
                # Extract tag name without namespace prefix
                tag_name = key[len(f"----:com.apple.iTunes:{old_ns}:") :]
                tags_to_migrate[tag_name] = value
                if delete_old:
                    keys_to_delete.append(key)

        if not tags_to_migrate:
            return 0

        # Write tags with new namespace
        for tag_name, value in tags_to_migrate.items():
            new_key = f"----:com.apple.iTunes:{new_ns}:{tag_name}"
            m4a.tags[new_key] = value
            migrated += 1

        # Delete old tags if requested
        if delete_old:
            for key in keys_to_delete:
                del m4a.tags[key]

        m4a.save()
        return migrated

    except Exception as e:
        logging.error(f"Failed to migrate {file_path}: {e}")
        return 0


def scan_and_migrate(music_dir: str, old_ns: str, new_ns: str, delete_old: bool = False, dry_run: bool = False) -> dict:
    """
    Scan directory and migrate all audio files.

    Returns:
        Dict with stats: files_processed, files_migrated, tags_migrated
    """
    stats = {"files_processed": 0, "files_migrated": 0, "tags_migrated": 0, "files_skipped": 0}

    audio_extensions = {".mp3", ".m4a", ".flac"}
    music_path = Path(music_dir)

    if not music_path.exists():
        logging.error(f"Directory does not exist: {music_dir}")
        return stats

    logging.info(f"Scanning {music_dir}...")
    all_files = list(music_path.rglob("*"))
    audio_files = [f for f in all_files if f.suffix.lower() in audio_extensions]

    logging.info(f"Found {len(audio_files)} audio files")

    for idx, file_path in enumerate(audio_files, 1):
        if idx % 100 == 0:
            logging.info(f"Progress: {idx}/{len(audio_files)} files processed...")

        stats["files_processed"] += 1

        if dry_run:
            logging.debug(f"[DRY RUN] Would migrate: {file_path}")
            continue

        try:
            migrated = 0
            if file_path.suffix.lower() == ".mp3":
                migrated = migrate_mp3_tags(str(file_path), old_ns, new_ns, delete_old)
            elif file_path.suffix.lower() == ".m4a":
                migrated = migrate_m4a_tags(str(file_path), old_ns, new_ns, delete_old)

            if migrated > 0:
                stats["files_migrated"] += 1
                stats["tags_migrated"] += migrated
                logging.debug(f"Migrated {migrated} tags in {file_path}")
            else:
                stats["files_skipped"] += 1

        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            stats["files_skipped"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Migrate audio tags from one namespace to another")
    parser.add_argument("music_dir", help="Path to music directory")
    parser.add_argument("--old", default="essentia", help="Old namespace prefix (default: essentia)")
    parser.add_argument("--new", default="nom", help="New namespace prefix (default: nom)")
    parser.add_argument("--delete-old", action="store_true", help="Delete old namespace tags after migration")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying files")

    args = parser.parse_args()

    if args.dry_run:
        logging.info("=== DRY RUN MODE - No files will be modified ===")

    logging.info(f"Migrating tags: {args.old}: → {args.new}:")
    if args.delete_old:
        logging.warning("Old namespace tags WILL BE DELETED after migration")
    else:
        logging.info("Old namespace tags will be preserved")

    stats = scan_and_migrate(args.music_dir, args.old, args.new, args.delete_old, args.dry_run)

    logging.info("\n=== Migration Complete ===")
    logging.info(f"Files processed: {stats['files_processed']}")
    logging.info(f"Files migrated: {stats['files_migrated']}")
    logging.info(f"Files skipped: {stats['files_skipped']}")
    logging.info(f"Tags migrated: {stats['tags_migrated']}")


if __name__ == "__main__":
    main()
