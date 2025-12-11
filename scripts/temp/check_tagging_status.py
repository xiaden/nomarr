"""
Check how many files are marked as tagged vs untagged.
"""

import sqlite3
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def check_tagging_status(db_path: str):
    """Check tagging status of files in database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 80)
    print("TAGGING STATUS CHECK")
    print("=" * 80)
    print()

    # Total files
    cursor = conn.execute("SELECT COUNT(*) FROM library_files")
    total = cursor.fetchone()[0]
    print(f"Total files: {total}")
    print()

    # Tagged files
    cursor = conn.execute("SELECT COUNT(*) FROM library_files WHERE tagged = 1")
    tagged = cursor.fetchone()[0]
    print(f"Files marked as tagged: {tagged} ({tagged / total * 100:.1f}%)")

    # Untagged files
    cursor = conn.execute("SELECT COUNT(*) FROM library_files WHERE tagged = 0 OR tagged IS NULL")
    untagged = cursor.fetchone()[0]
    print(f"Files marked as untagged: {untagged} ({untagged / total * 100:.1f}%)")
    print()

    # Files with ANY nomarr tags
    cursor = conn.execute("""
        SELECT COUNT(DISTINCT ft.file_id)
        FROM file_tags ft
        JOIN library_tags lt ON lt.id = ft.tag_id
        WHERE lt.is_nomarr_tag = 1
    """)
    files_with_tags = cursor.fetchone()[0]
    print(f"Files with any nomarr tags in DB: {files_with_tags} ({files_with_tags / total * 100:.1f}%)")
    print()

    # Sample some untagged files
    print("-" * 80)
    print("SAMPLE UNTAGGED FILES (first 10):")
    print("-" * 80)
    cursor = conn.execute("""
        SELECT id, path, tagged, skip_auto_tag
        FROM library_files
        WHERE tagged = 0 OR tagged IS NULL
        LIMIT 10
    """)
    for row in cursor.fetchall():
        print(f"  id={row['id']:5d} tagged={row['tagged']} skip_auto_tag={row['skip_auto_tag']} path={row['path']}")
    print()

    conn.close()


if __name__ == "__main__":
    db_path = project_root / "config" / "db" / "nomarr.db"

    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    check_tagging_status(str(db_path))
