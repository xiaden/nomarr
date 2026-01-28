#!/usr/bin/env python3
"""
Check API endpoint coverage - which backend routes are used by the frontend.

Generates an HTML report showing:
- All backend API endpoints (from FastAPI routes)
- Endpoint documentation (docstrings)
- Frontend usage status for each endpoint
- Source files where endpoints are called

Usage:
    python scripts/check_api_coverage.py
    python scripts/check_api_coverage.py --unused-only
    python scripts/check_api_coverage.py --used-only
"""

import argparse
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from tools.api_coverage.discovery import get_backend_routes, scan_frontend_usage
from tools.api_coverage.matcher import match_endpoint_usage
from tools.api_coverage.report import generate_html_report

project_root = Path(__file__).parent.parent


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check API endpoint coverage between backend and frontend",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--used-only",
        action="store_true",
        help="Show only endpoints that ARE used by frontend",
    )
    parser.add_argument(
        "--unused-only",
        action="store_true",
        help="Show only endpoints that are NOT used by frontend",
    )

    args = parser.parse_args()

    # Validate mutually exclusive flags
    if args.used_only and args.unused_only:
        print("Error: --used-only and --unused-only are mutually exclusive", file=sys.stderr)
        return 1

    filter_mode = None
    if args.used_only:
        filter_mode = "used"
    elif args.unused_only:
        filter_mode = "unused"

    print("Scanning backend routes...")
    backend_routes = get_backend_routes()
    print(f"Found {len(backend_routes)} backend routes")

    print("\nScanning frontend usage...")
    frontend_dir = project_root / "frontend" / "src"
    frontend_usage = scan_frontend_usage(frontend_dir)
    print(f"Found {len(frontend_usage)} unique endpoint references in frontend")

    print("\nMatching endpoints...")
    endpoint_usages = match_endpoint_usage(backend_routes, frontend_usage)

    output_file = project_root / "scripts" / "outputs" / "api_coverage.html"
    print("\nGenerating HTML report...")
    generate_html_report(endpoint_usages, output_file, filter_mode)

    return 0


if __name__ == "__main__":
    sys.exit(main())
