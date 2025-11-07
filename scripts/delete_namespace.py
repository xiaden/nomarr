"""
Delete all tags from a specific namespace in audio files.

This script:
1. Scans all audio files in a directory
2. Removes all tags matching the specified namespace prefix
3. Saves the files

Usage:
    python scripts/delete_namespace.py /path/to/music --namespace essentia
    python scripts/delete_namespace.py /path/to/music --namespace essentia --dry-run
"""

import argparse
import logging
from pathlib import Path

from mutagen.id3 import ID3
from mutagen.mp4 import MP4

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def delete_mp3_namespace(file_path: str, namespace: str) -> int:
    """Delete all TXXX tags from specified namespace in MP3 file."""
    try:
        id3 = ID3(file_path)
        deleted = 0

        # Collect frames to delete
        frames_to_delete = []
        for frame in id3.getall("TXXX"):
            if frame.desc.startswith(f"{namespace}:"):
                frames_to_delete.append(frame)
                deleted += 1

        if deleted == 0:
            return 0

        # Delete collected frames
        for frame in frames_to_delete:
            id3.delall(frame.HashKey)

        id3.save(file_path, v2_version=3)
        return deleted

    except Exception as e:
        logging.error(f"Failed to process {file_path}: {e}")
        return 0


def delete_m4a_namespace(file_path: str, namespace: str) -> int:
    """Delete all freeform tags from specified namespace in M4A file."""
    try:
        m4a = MP4(file_path)
        deleted = 0

        # Collect keys to delete
        keys_to_delete = []
        for key in m4a.tags:
            if key.startswith(f"----:com.apple.iTunes:{namespace}:"):
                keys_to_delete.append(key)
                deleted += 1

        if deleted == 0:
            return 0

        # Delete collected keys
        for key in keys_to_delete:
            del m4a.tags[key]

        m4a.save()
        return deleted

    except Exception as e:
        logging.error(f"Failed to process {file_path}: {e}")
        return 0


def scan_and_delete(music_dir: str, namespace: str, dry_run: bool = False) -> dict:
    """
    Scan directory and delete namespace tags from all audio files.

    Returns:
        Dict with stats: files_processed, files_modified, tags_deleted
    """
    stats = {"files_processed": 0, "files_modified": 0, "tags_deleted": 0, "files_skipped": 0}

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
            logging.debug(f"[DRY RUN] Would delete {namespace}: tags from: {file_path}")
            continue

        try:
            deleted = 0
            if file_path.suffix.lower() == ".mp3":
                deleted = delete_mp3_namespace(str(file_path), namespace)
            elif file_path.suffix.lower() == ".m4a":
                deleted = delete_m4a_namespace(str(file_path), namespace)

            if deleted > 0:
                stats["files_modified"] += 1
                stats["tags_deleted"] += deleted
                logging.debug(f"Deleted {deleted} tags from {file_path}")
            else:
                stats["files_skipped"] += 1

        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            stats["files_skipped"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Delete all tags from a specific namespace in audio files")
    parser.add_argument("music_dir", help="Path to music directory")
    parser.add_argument("--namespace", default="essentia", help="Namespace prefix to delete (default: essentia)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying files")

    args = parser.parse_args()

    if args.dry_run:
        logging.info("=== DRY RUN MODE - No files will be modified ===")

    logging.warning(f"This will DELETE ALL '{args.namespace}:*' tags from your audio files!")
    if not args.dry_run:
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() not in ("yes", "y"):
            logging.info("Operation cancelled")
            return

    stats = scan_and_delete(args.music_dir, args.namespace, args.dry_run)

    logging.info("\n=== Deletion Complete ===")
    logging.info(f"Files processed: {stats['files_processed']}")
    logging.info(f"Files modified: {stats['files_modified']}")
    logging.info(f"Files skipped: {stats['files_skipped']}")
    logging.info(f"Tags deleted: {stats['tags_deleted']}")


if __name__ == "__main__":
    main()
