#!/usr/bin/env python3
"""Test the MCP server."""

import json
import subprocess
import sys
import threading
import time


def main():
    proc = subprocess.Popen(
        [sys.executable, "-m", "scripts.mcp.nomarr_dev_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    # Read stderr in background
    def read_stderr():
        for line in proc.stderr:
            print(f"[stderr] {line.rstrip()}", file=sys.stderr)

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

    def send(req):
        line = json.dumps(req)
        print(f">>> {line[:100]}...")
        proc.stdin.write(line + "\n")
        proc.stdin.flush()

        response = proc.stdout.readline()
        if not response:
            print("<<< (no response)")
            return {}

        resp = json.loads(response)
        print(f"<<< id={resp.get('id')} keys={list(resp.keys())}")
        return resp

    # Initialize
    send(
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
            "id": 1,
        }
    )

    # Initialized notification (no response)
    print(">>> notifications/initialized")
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()
    time.sleep(0.1)

    # List tools
    resp = send({"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2})
    if "result" in resp:
        tools = [t["name"] for t in resp["result"].get("tools", [])]
        print(f"    Tools: {tools}")

    # Call discover_api
    print("\n=== Calling discover_api ===")
    start = time.time()
    resp = send(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "discover_api",
                "arguments": {
                    "params": {
                        "module_name": "nomarr.helpers.time_helper",
                        "format": "text",
                    },
                },
            },
            "id": 3,
        }
    )
    elapsed = time.time() - start
    print(f"    Elapsed: {elapsed:.1f}s")

    if "result" in resp:
        content = resp["result"].get("content", [])
        if content:
            text = content[0].get("text", "")
            print(f"    Output: {len(text)} chars")
            print(f"    Preview: {text[:150]}...")
    elif "error" in resp:
        print(f"    Error: {resp['error']}")

    proc.terminate()
    print("\nDone!")


if __name__ == "__main__":
    main()
