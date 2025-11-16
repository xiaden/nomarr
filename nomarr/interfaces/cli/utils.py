"""
Shared utility functions for CLI commands.
Helper functions used across multiple command modules.
"""

from __future__ import annotations

import json
from urllib import error as urlerror
from urllib import request

from nomarr.app import application

__all__ = [
    "api_call",
    "format_duration",
    "format_tag_summary",
]


def format_duration(seconds: float) -> str:
    """Format seconds into human readable: 2d 5h 30m"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m = int(seconds / 60)
        s = int(seconds % 60)
        return f"{m}m {s}s" if s > 0 else f"{m}m"
    elif seconds < 86400:
        h = int(seconds / 3600)
        m = int((seconds % 3600) / 60)
        return f"{h}h {m}m"
    else:
        d = int(seconds / 86400)
        h = int((seconds % 86400) / 3600)
        return f"{d}d {h}h"


def format_tag_summary(tags: dict) -> str:
    """Format a brief summary of notable tags (mood tags) for display."""
    if not tags:
        return ""

    # Priority: show mood-strict, then mood-regular, then mood-loose
    for mood_key in ["mood-strict", "mood-regular", "mood-loose"]:
        if mood_key in tags:
            values = tags[mood_key]
            if isinstance(values, list) and values:
                moods = ", ".join(sorted(values)[:5])  # Show up to 5 moods
                if len(values) > 5:
                    moods += f" +{len(values) - 5} more"
                return f"[dim]{mood_key}:[/dim] {moods}"

    return ""


def api_call(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Minimal HTTP helper to call the API using config + DB-stored API key."""
    if not application.is_running():
        raise RuntimeError("Application is not running. Start the server first.")

    host = application.api_host
    port = application.api_port
    url = f"http://{host}:{port}{path}"

    api_key = application.db.meta.get("api_key") or ""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urlerror.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": raw or str(e)}
        raise RuntimeError(f"HTTP {e.code}: {payload.get('error', str(e))}") from e
    except urlerror.URLError as e:
        raise RuntimeError(f"API not reachable at {url}: {e}") from e
