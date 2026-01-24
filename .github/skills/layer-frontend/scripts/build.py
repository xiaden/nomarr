#!/usr/bin/env python3
"""Run TypeScript build on frontend (includes type-check)."""

import subprocess

subprocess.run(["npm", "run", "build"], cwd="frontend", shell=True)
