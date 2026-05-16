"""
CLI entrypoint for the embedding research pipeline.

Phases:
  install   -- pip install the requirements.txt for this package
  embed     -- Phase 1: backbone inference -> patches sidecars + DuckDB pooled vectors
  classify  -- Phase 2: head inference (PTC + CTP) -> DuckDB head_results
  analyze   -- Phase 3: retrieval metrics, ANN sweep -> DuckDB results tables
  report    -- Phase 4: generate markdown + CSV reports from DuckDB
  all       -- run phases 1-4 in sequence

Usage (from inside the devcontainer):
  # Install dependencies first
  python /workspace/scripts/embedding_research/run.py install

  # Run full pipeline (takes a while for 2386 songs)
  python /workspace/scripts/embedding_research/run.py all

  # Quick smoke-test on 20 songs
  python /workspace/scripts/embedding_research/run.py all --limit 20 --verbose

  # Re-run just the analysis + report after tweaking similarity.py
  python /workspace/scripts/embedding_research/run.py analyze report

  # Only effnet, only cosine+mean
  python /workspace/scripts/embedding_research/run.py embed analyze report \\
      --backbone effnet --strategy mean median
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Ensure the workspace root is on sys.path so the package resolves correctly
# when run as `python run.py` inside the container.
_pkg_root = Path(__file__).resolve().parent.parent.parent  # /workspace
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from scripts.embedding_research.config import BACKBONES, DB_PATH, OUTPUT_ROOT
from scripts.embedding_research.pooling import STRATEGIES

_REQ = Path(__file__).parent / "requirements.txt"


def _install() -> None:
    print(f"Installing dependencies from {_REQ} ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(_REQ)])
    print("Done.")


def _embed(args: argparse.Namespace) -> None:
    from scripts.embedding_research.embed import run

    run(limit=args.limit, force=args.force, backbones=args.backbone, verbose=args.verbose)


def _classify(args: argparse.Namespace) -> None:
    from scripts.embedding_research.classify import run

    run(
        limit=args.limit,
        force=args.force,
        backbones=args.backbone,
        heads=args.head,
        verbose=args.verbose,
    )


def _analyze(args: argparse.Namespace) -> None:
    from scripts.embedding_research.analyze import run

    run(
        limit=args.limit,
        k=args.k,
        ann_n_queries=args.ann_queries,
        backbones=args.backbone,
        strategies=args.strategy,
        verbose=args.verbose,
    )


def _report(_args: argparse.Namespace) -> None:
    from scripts.embedding_research.report import run

    run()


_PHASES = {
    "install": _install,
    "embed": _embed,
    "classify": _classify,
    "analyze": _analyze,
    "report": _report,
}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Embedding research pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "phases",
        nargs="+",
        choices=[*_PHASES, "all"],
        metavar="PHASE",
        help="One or more phases to run: install embed classify analyze report all",
    )
    ap.add_argument("--limit", type=int, default=None, help="Process only N songs (debug)")
    ap.add_argument("--backbone", nargs="+", choices=list(BACKBONES), default=None)
    ap.add_argument("--head", nargs="+", default=None)
    ap.add_argument("--strategy", nargs="+", choices=list(STRATEGIES), default=None)
    ap.add_argument("--k", type=int, default=10, help="Retrieval cutoff k")
    ap.add_argument("--ann-queries", type=int, default=200, dest="ann_queries")
    ap.add_argument("--force", action="store_true", help="Re-compute even if already done")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    phases = args.phases
    if "all" in phases:
        phases = ["install", "embed", "classify", "analyze", "report"]

    print(f"Output root : {OUTPUT_ROOT}")
    print(f"Database    : {DB_PATH}")
    print(f"Phases      : {' -> '.join(phases)}\n")

    for phase in phases:
        print(f"\n{'=' * 60}")
        print(f"  Phase: {phase.upper()}")
        print(f"{'=' * 60}")
        fn = _PHASES[phase]
        if phase == "install":
            fn()
        else:
            fn(args)

    print("\nPipeline complete.")


if __name__ == "__main__":
    main()
