#!/usr/bin/env python3
"""Run ESLint and TypeScript type checking on frontend."""

import subprocess
import sys

# Run ESLint
result = subprocess.run(["npm", "run", "lint"], cwd="frontend", shell=True)
if result.returncode != 0:
    sys.exit(result.returncode)

# Run TypeScript type checking
result = subprocess.run(["npx", "tsc", "-b", "--noEmit"], cwd="frontend", shell=True)
sys.exit(result.returncode)
