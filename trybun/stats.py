"""Token usage over time: one JSON line per model run in .trybunai/tokeny.jsonl.

The file outlives "Nowa rozmowa" (the chat is archived, the statistics are not).
"""
from __future__ import annotations

import json
import os
import re
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


# ---- history from before the statistics existed ------------------------------------------
# Claude Code and Codex keep their own session logs with token counts. Runs started by TrybunAI
# are told apart from the user's own work: Claude marks them "sdk-cli", Codex "codex_exec".
IMPORT_MARK = "tokeny-import.json"
IMPORT_DAYS = 90


def claude_root():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def codex_root():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"


def _stamp(text):
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def _num(v):
    return v if isinstance(v, (int, float)) else 0


def claude_history(project, since, until, root=None):
    """One row per run (a user prompt and the model calls answering it) of headless Claude/Haiku."""
    folder = (root or claude_root()) / re.sub(r"[^A-Za-z0-9]", "-", str(project))
    rows = []
    for path in sorted(folder.glob("*.jsonl")):
        runs, calls, run = {}, {}, 0
        for o in _lines(path):
            if o.get("type") == "user" and o.get("entrypoint") == "sdk-cli" and not o.get("isSidechain"):
                content = (o.get("message") or {}).get("content")
                if isinstance(content, str) or not any(isinstance(c, dict) and c.get("type") == "tool_result"
                                                       for c in content or []):
                    run += 1
            if o.get("type") != "assistant" or o.get("entrypoint") != "sdk-cli" or o.get("isSidechain"):
                continue
            msg = o.get("message") or {}
            usage, model = msg.get("usage") or {}, str(msg.get("model") or "")
            ts = _stamp(o.get("timestamp"))
            if not usage or not ts or not (since <= ts < until) or model.startswith("<"):
                continue
            tokens = {"input": _num(usage.get("input_tokens")) + _num(usage.get("cache_creation_input_tokens")),
                      "cached": _num(usage.get("cache_read_input_tokens")), "output": _num(usage.get("output_tokens"))}
            key = msg.get("id") or o.get("uuid")
            seen = calls.setdefault(key, {"run": run, "ts": ts, "model": model})  # one call is logged per block
            for k in FIELDS:
                seen[k] = max(seen.get(k, 0), tokens[k])
        for call in calls.values():
            row = runs.setdefault(call["run"], {"ts": call["ts"], "model": call["model"], "calls": 0})
            add_tokens(row, call)
            row["calls"] += 1
        for row in runs.values():
            agent = "haiku" if "haiku" in row["model"] else "claude"
            rows.append({"ts": row["ts"], "agent": agent, "model": row["model"], "kind": "historia",
                         "calls": row["calls"], **{k: row[k] for k in FIELDS}})
    return rows


def codex_history(project, since, until, root=None):
    """One row per Codex task (codex exec turn) run in the project folder."""
    root = root or codex_root()
    want = os.path.normcase(os.path.abspath(str(project)))
    rows, day = [], datetime.fromtimestamp(since).date()
    while day <= datetime.fromtimestamp(until).date():
        for path in sorted((root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}").glob("rollout-*.jsonl")):
            lines = _lines(path)
            meta = next(lines, {}).get("payload") or {}
            if meta.get("originator") != "codex_exec" or \
                    os.path.normcase(os.path.abspath(str(meta.get("cwd") or "?"))) != want:
                continue
            row, last_total = None, None
            for o in lines:
                payload = o.get("payload") or {}
                kind = payload.get("type")
                if kind == "task_started":
                    row = None
                if kind != "token_count" or not isinstance(payload.get("info"), dict):
                    continue
                info = payload["info"]
                if info.get("total_token_usage") == last_total:
                    continue  # the same count is sometimes reported twice
                last_total = info.get("total_token_usage")
                used = info.get("last_token_usage") or {}
                ts = _stamp(o.get("timestamp"))
                if not ts or not (since <= ts < until):
                    continue
                if row is None:
                    row = {"ts": ts, "agent": "codex", "model": None, "kind": "historia", "calls": 0}
                    rows.append(row)
                total, cached = _num(used.get("input_tokens")), _num(used.get("cached_input_tokens"))
                add_tokens(row, {"input": max(total - cached, 0), "cached": min(cached, total),
                                 "output": _num(used.get("output_tokens"))})
                row["calls"] += 1
        day += timedelta(days=1)
    return [r for r in rows if any(r.get(k) for k in FIELDS)]


def backfill(folder, project, now=None, claude=None, codex=None):
    """Once per project: copy the last 90 days from the CLIs' logs, up to the first recorded run,
    so nothing is counted twice. Returns the number of imported runs, or None when already done."""
    folder = Path(folder)
    mark = folder / IMPORT_MARK
    if mark.exists():
        return None
    now = now or time.time()
    first = min((r["ts"] for r in read(folder)), default=now)
    since = now - IMPORT_DAYS * 86400
    rows = claude_history(project, since, first, claude) + codex_history(project, since, first, codex)
    for row in sorted(rows, key=lambda r: r["ts"]):
        record(folder, row["agent"], row["model"], "historia", row, row["calls"], row["ts"])
    folder.mkdir(parents=True, exist_ok=True)
    mark.write_text(json.dumps({"ts": now, "runs": len(rows), "until": first}), encoding="utf-8")
    return len(rows)
