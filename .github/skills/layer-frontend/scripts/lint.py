#!/usr/bin/env python3
"""Run ESLint on frontend."""

import subprocess

subprocess.run(["npm", "run", "lint"], cwd="frontend", shell=True)
