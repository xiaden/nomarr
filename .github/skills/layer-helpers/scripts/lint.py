#!/usr/bin/env python3
"""Run all linters on helpers layer."""

import subprocess

LAYER = "nomarr/helpers"

subprocess.run(["ruff", "check", LAYER])
subprocess.run(["mypy", LAYER])
subprocess.run(["vulture", LAYER, "--min-confidence", "60"])
subprocess.run(["bandit", "-r", LAYER, "-q"])
subprocess.run(["radon", "cc", LAYER, "-a", "-s"])
subprocess.run(["lint-imports"])
