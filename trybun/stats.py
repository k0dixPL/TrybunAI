"""Token usage over time: one JSON line per model run in .trybunai/tokeny.jsonl.

The file outlives "Nowa rozmowa" (the chat is archived, the statistics are not).
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

FILE = "tokeny.jsonl"
KEEP_LINES = 50_000  # a few years of heavy use; older lines are dropped when the file is trimmed
TRIM_BYTES = 8_000_000
FIELDS = ("input", "cached", "output")
RANGES = {  # key: (bucket count, hours per bucket)
    "24h": (24, 1),
    "7d": (7, 24),
    "30d": (30, 24),
    "90d": (90, 24),
}
_lock = threading.Lock()


def add_tokens(total, part):
    """Sum token counts field by field."""
    for key in FIELDS:
        total[key] = total.get(key, 0) + int(part.get(key) or 0)
    return total


def record(folder, agent, model, kind, tokens, calls, ts=None):
    """Append one run. `tokens` is {"input", "cached", "output"}; empty runs are not written."""
    row = {"ts": round(ts or time.time(), 1), "agent": agent, "model": model, "kind": kind, "calls": calls}
    add_tokens(row, tokens)
    if not any(row[k] for k in FIELDS):
        return False
    path = Path(folder) / FILE
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        if path.stat().st_size > TRIM_BYTES:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)[-KEEP_LINES:]
            tmp = path.with_suffix(".tmp")
            tmp.write_text("".join(lines), encoding="utf-8")
            tmp.replace(path)
    return True


def read(folder, since=0.0):
    path = Path(folder) / FILE
    rows = []
    try:
        with _lock, path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line cut short by a crash
                if isinstance(row, dict) and isinstance(row.get("ts"), (int, float)) and row["ts"] >= since:
                    rows.append(row)
    except FileNotFoundError:
        pass
    return rows


def _bucket_starts(range_key, now):
    count, hours = RANGES[range_key]
    if hours == 1:
        last = now.replace(minute=0, second=0, microsecond=0)
    else:
        last = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Days are stepped on the calendar, not by 24 h, so a DST change keeps buckets on midnight.
    starts = []
    for i in range(count - 1, -1, -1):
        if hours == 1:
            starts.append(last - timedelta(hours=i))
        else:
            day = (last - timedelta(days=i)).date()
            starts.append(datetime(day.year, day.month, day.day))
    return starts, hours


def summarize(folder, range_key="7d", now=None):
    """Buckets for the chart and per-model totals for the table, in local time."""
    if range_key not in RANGES:
        range_key = "7d"
    now = now or datetime.now()
    starts, hours = _bucket_starts(range_key, now)
    edges = [s.timestamp() for s in starts]
    end = (starts[-1] + timedelta(hours=1) if hours == 1 else starts[-1] + timedelta(days=1)).timestamp()
    buckets = [{"start": e, "label": s.strftime("%H:00" if hours == 1 else "%d.%m"), "by": {}}
               for s, e in zip(starts, edges)]
    totals, kinds = {}, {}
    for row in read(folder, edges[0]):
        ts = row["ts"]
        if ts >= end:
            continue
        idx = max(i for i, e in enumerate(edges) if e <= ts)
        agent = str(row.get("agent") or "?")
        cell = buckets[idx]["by"].setdefault(agent, {"runs": 0})
        add_tokens(cell, row)
        cell["runs"] += 1
        tot = totals.setdefault(agent, {"runs": 0, "calls": 0})
        add_tokens(tot, row)
        tot["runs"] += 1
        tot["calls"] += int(row.get("calls") or 0)
        kind = str(row.get("kind") or "czat")
        add_tokens(kinds.setdefault(kind, {}), row)
    return {"range": range_key, "hourly": hours == 1, "buckets": buckets, "totals": totals, "kinds": kinds}
