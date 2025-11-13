"""
Shared utility functions for CLI commands.
Helper functions used across multiple command modules.
"""

from __future__ import annotations

import json
from urllib import error as urlerror
from urllib import request

from nomarr.config import compose
from nomarr.data.db import Database

__all__ = [
    "api_call",
    "format_duration",
    "format_tag_summary",
    "get_avg_processing_time",
    "get_db",
    "update_avg_processing_time",
]


def get_db(cfg=None) -> Database:
    """Get Database instance from config."""
    if cfg is None:
        cfg = compose({})
    return Database(cfg["db_path"])


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


def get_avg_processing_time(db: Database) -> float:
    """Get average processing time from recent successful jobs."""
    # Check if we have stored average
    stored_avg = db.get_meta("avg_processing_time")
    if stored_avg:
        return float(stored_avg)

    # Calculate from last 5 successful jobs
    cur = db.conn.execute(
        """
        SELECT finished_at, started_at
        FROM queue
        WHERE status='done' AND finished_at IS NOT NULL AND started_at IS NOT NULL
        ORDER BY finished_at DESC
        LIMIT 5
        """
    )
    rows = cur.fetchall()

    if not rows:
        # No history yet - use default estimate
        return 100.0

    # Calculate average from recent jobs
    times = [(finished - started) / 1000.0 for finished, started in rows]
    avg = sum(times) / len(times)

    # Store for future use
    db.set_meta("avg_processing_time", str(avg))
    return avg


def update_avg_processing_time(db: Database, job_elapsed: float):
    """Update rolling average processing time after job completion."""
    current_avg = get_avg_processing_time(db)

    # Weighted average: 80% old avg, 20% new job
    new_avg = (current_avg * 0.8) + (job_elapsed * 0.2)
    db.set_meta("avg_processing_time", str(new_avg))


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
    cfg = compose({})
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 8356))
    url = f"http://{host}:{port}{path}"
    db = get_db(cfg)
    try:
        api_key = db.get_meta("api_key") or ""
    finally:
        db.close()

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
