"""Test ruff only to isolate hanging issue."""
import json
import subprocess
from pathlib import Path

project_root = Path(__file__).parent
venv_ruff = project_root / ".venv" / "Scripts" / "ruff.exe"
target_file = "scripts/mcp/tools/lint_backend.py"

print(f"Running ruff on {target_file}...")
print(f"Command: {venv_ruff} check {target_file}")

try:
    result = subprocess.run(
        [str(venv_ruff), "check", target_file],
        capture_output=True,
        cwd=project_root,
    )
    stdout = result.stdout.decode()
    stderr = result.stderr.decode()
    print(f"Return code: {result.returncode}")
except subprocess.CalledProcessError as e:
    stdout = e.stdout.decode()
    stderr = e.stderr.decode()
    print(f"CalledProcessError: {e.returncode}")

print(f"Stdout length: {len(stdout)}")
print(f"Stderr length: {len(stderr)}")

if stdout:
    try:
        errors = json.loads(stdout)
        print(f"Parsed {len(errors)} errors from JSON")
        print(json.dumps(errors[:2], indent=2))  # Show first 2
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        print(f"First 500 chars of stdout: {stdout[:500]}")

print("Done!")
