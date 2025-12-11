"""
Diagnostic script to check what mood tags exist in the database.
"""

import sqlite3
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def diagnose_mood_tags(db_path: str):
    """Check what mood-related tags exist in the database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("=" * 80)
    print("MOOD TAG DIAGNOSTICS")
    print("=" * 80)
    print()

    # Check total counts
    cursor = conn.execute("SELECT COUNT(*) FROM library_files")
    print(f"Total files: {cursor.fetchone()[0]}")

    cursor = conn.execute("SELECT COUNT(*) FROM library_tags")
    print(f"Total unique tags: {cursor.fetchone()[0]}")

    cursor = conn.execute("SELECT COUNT(*) FROM library_tags WHERE is_nomarr_tag = 1")
    print(f"Nomarr tags (is_nomarr_tag=1): {cursor.fetchone()[0]}")

    cursor = conn.execute("SELECT COUNT(*) FROM file_tags")
    print(f"Total file-tag associations: {cursor.fetchone()[0]}")
    print()

    # Check for tags with 'mood' in the key
    print("-" * 80)
    print("TAGS WITH 'mood' IN KEY (first 20):")
    print("-" * 80)
    cursor = conn.execute(
        """
        SELECT key, value, type, is_nomarr_tag, COUNT(ft.file_id) as file_count
        FROM library_tags lt
        LEFT JOIN file_tags ft ON ft.tag_id = lt.id
        WHERE LOWER(lt.key) LIKE '%mood%'
        GROUP BY lt.id
        ORDER BY file_count DESC
        LIMIT 20
        """
    )
    rows = cursor.fetchall()
    if rows:
        for row in rows:
            print(
                f"  key={row['key']!r:30s} value={row['value']!r:20s} "
                f"type={row['type']:10s} is_nomarr={row['is_nomarr_tag']} files={row['file_count']}"
            )
    else:
        print("  (no tags found)")
    print()

    # Check for exact mood tag keys we're looking for
    print("-" * 80)
    print("EXACT MOOD TAG KEYS:")
    print("-" * 80)
    for mood_key in ["mood-strict", "mood-regular", "mood-loose", "nom:mood-strict", "nom:mood-regular", "nom:mood-loose"]:
        cursor = conn.execute(
            """
            SELECT COUNT(DISTINCT ft.file_id) as file_count, is_nomarr_tag
            FROM library_tags lt
            LEFT JOIN file_tags ft ON ft.tag_id = lt.id
            WHERE lt.key = ?
            GROUP BY lt.is_nomarr_tag
            """,
            (mood_key,),
        )
        rows = cursor.fetchall()
        if rows:
            for row in rows:
                print(f"  key={mood_key!r:25s} is_nomarr={row['is_nomarr_tag']} files={row['file_count']}")
        else:
            print(f"  key={mood_key!r:25s} (NOT FOUND)")
    print()

    # Sample some actual tag values
    print("-" * 80)
    print("SAMPLE NOMARR TAGS (first 20):")
    print("-" * 80)
    cursor = conn.execute(
        """
        SELECT DISTINCT lt.key
        FROM library_tags lt
        WHERE lt.is_nomarr_tag = 1
        LIMIT 20
        """
    )
    rows = cursor.fetchall()
    if rows:
        for row in rows:
            print(f"  {row['key']!r}")
    else:
        print("  (no nomarr tags found)")
    print()

    conn.close()


if __name__ == "__main__":
    # Default to development database
    db_path = project_root / "config" / "db" / "nomarr.db"

    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    diagnose_mood_tags(str(db_path))
