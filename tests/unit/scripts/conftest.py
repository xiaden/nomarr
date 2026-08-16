"""Narrowly-scoped sys.path bootstrap for the scripts tests.

The tests under ``tests/unit/scripts/`` exercise ``scripts/validate_commit.py``,
which lives at the repository root (``scripts/`` is a real package with
``__init__.py``). When pytest is launched through its ``pytest`` console entry
point — exactly how the backend test gate does it, see the ``test`` job in
``.github/workflows/backend-tests.yml``:

    pytest tests/ -v -m "not container_only and not requires_database and not code_smell"

— the repository root is *not* on ``sys.path``, so ``from
scripts.validate_commit import ...`` fails at collection with
``ModuleNotFoundError: No module named 'scripts'`` (running ``python -m pytest``
happens to work only because that form prepends the current directory itself).

Rather than touch shared project config (``pyproject.toml`` ``pythonpath``,
``conftest.py`` at the repo root, or global ``rootdir`` behaviour), this
conftest makes the repo root importable for just this directory. It is the
smallest change that makes the validator test module collect under the exact
backend workflow command.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # <repo>/tests/unit/scripts -> <repo>

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
