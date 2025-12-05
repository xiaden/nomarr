"""
Fix imports after services/ reorganization.

Changes:
- .services.analytics_svc -> .services.domain.analytics_svc
- .services.calibration_svc -> .services.domain.calibration_svc
- .services.library_svc -> .services.domain.library_svc
- .services.recalibration_svc -> .services.domain.recalibration_svc
- .services.navidrome_svc -> .services.domain.navidrome_svc
- .services.config_svc -> .services.infrastructure.config_svc
- .services.keys_svc -> .services.infrastructure.keys_svc
- .services.health_monitor_svc -> .services.infrastructure.health_monitor_svc
- .services.info_svc -> .services.infrastructure.info_svc
- .services.queue_svc -> .services.infrastructure.queue_svc
- .services.ml_svc -> .services.infrastructure.ml_svc
- .services.workers_coordinator_svc -> .services.infrastructure.worker_system_svc
- .services.coordinator_svc -> DELETE (removed file)
- .services.worker_pool_svc -> DELETE (removed file)
"""

import re
from pathlib import Path

# Domain services
DOMAIN_SERVICES = [
    "analytics_svc",
    "calibration_svc",
    "library_svc",
    "recalibration_svc",
    "navidrome_svc",
]

# Infrastructure services
INFRA_SERVICES = [
    "config_svc",
    "keys_svc",
    "health_monitor_svc",
    "info_svc",
    "queue_svc",
    "ml_svc",
    "cli_bootstrap_svc",
    "calibration_download_svc",
]

# Deleted services (remove imports)
DELETED_SERVICES = ["coordinator_svc", "worker_pool_svc"]

# Special case: rename
RENAMED_SERVICES = {"workers_coordinator_svc": "worker_system_svc"}


def fix_import_line(line: str) -> str:
    """Fix a single import line."""
    # Check for domain services
    for svc in DOMAIN_SERVICES:
        pattern = rf"from nomarr\.services\.{svc} import"
        if re.search(pattern, line):
            return line.replace(f"nomarr.services.{svc}", f"nomarr.services.domain.{svc}")

    # Check for infrastructure services
    for svc in INFRA_SERVICES:
        pattern = rf"from nomarr\.services\.{svc} import"
        if re.search(pattern, line):
            return line.replace(f"nomarr.services.{svc}", f"nomarr.services.infrastructure.{svc}")

    # Check for renamed services
    for old_name, new_name in RENAMED_SERVICES.items():
        pattern = rf"from nomarr\.services\.{old_name} import"
        if re.search(pattern, line):
            return line.replace(f"nomarr.services.{old_name}", f"nomarr.services.infrastructure.{new_name}")

    # Check for deleted services - comment out the line
    for svc in DELETED_SERVICES:
        pattern = rf"from nomarr\.services\.{svc} import"
        if re.search(pattern, line):
            return f"# DELETED: {line}"

    return line


def fix_file(filepath: Path) -> bool:
    """Fix imports in a single file. Returns True if changes were made."""
    try:
        content = filepath.read_text(encoding="utf-8")
        original = content

        lines = content.splitlines(keepends=True)
        fixed_lines = [fix_import_line(line) for line in lines]
        fixed_content = "".join(fixed_lines)

        if fixed_content != original:
            filepath.write_text(fixed_content, encoding="utf-8")
            return True
        return False
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False


def main():
    """Fix all Python files in the project."""
    root = Path(__file__).parent.parent

    # Find all Python files (exclude .venv, __pycache__, etc.)
    python_files = []
    for pattern in ["nomarr/**/*.py", "tests/**/*.py"]:
        python_files.extend(root.glob(pattern))

    # Filter out excluded paths
    python_files = [f for f in python_files if ".venv" not in f.parts and "__pycache__" not in f.parts]

    changed_count = 0
    for filepath in python_files:
        if fix_file(filepath):
            print(f"✓ Fixed: {filepath.relative_to(root)}")
            changed_count += 1

    print(f"\n✅ Fixed {changed_count} files")


if __name__ == "__main__":
    main()
