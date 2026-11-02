"""Plans and usage limits of each account, read without spending any quota.

- Claude/Haiku: the plan from `claude auth status`; the limits ride along every reply as a
  rate_limit_event, so the last one seen is kept in a file shared by all projects.
- Codex: plan and limits are written into its own session logs after every turn.
- Antigravity: `agy -p=/usage` prints the remaining weekly limits without calling a model.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

NO_WINDOW = subprocess.CREATE_NO_WINDOW
_STORE = Path(os.environ.get("APPDATA") or Path.home()) / "TrybunAI" / "limits.json"
_LOCK = threading.Lock()
_CLAUDE_WINDOWS = {"five_hour": "5 godzin", "seven_day": "tydzień", "seven_day_opus": "tydzień (Opus)",
                   "seven_day_sonnet": "tydzień (Sonnet)"}


def _window(label, used, resets_at):
    used = max(0.0, min(100.0, float(used)))
    return {"label": label, "used": round(used), "resets_at": resets_at}


def _span(minutes):
    if minutes and minutes % 1440 == 0:
        days = minutes // 1440
        return "tydzień" if days == 7 else f"{days} dni"
    return f"{round((minutes or 0) / 60)} godzin"


def _run(cmd, timeout=30):
    out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW,
                         stdin=subprocess.DEVNULL)
    return out.returncode, out.stdout.decode("utf-8", "replace")


# ---- Claude ---------------------------------------------------------------
def record_claude(info):
    """Called with rate_limit_info from a Claude or Haiku reply."""
    if not isinstance(info, dict):
        return
    windows = [_window(_CLAUDE_WINDOWS.get(name, name), w.get("utilization", 0) * 100, w.get("resetsAt"))
               for name, w in (info.get("unifiedWindows") or {}).items() if isinstance(w, dict)]
    if not windows:
        return
    with _LOCK:
        data = _load()
        data["claude"] = {"windows": windows, "checked_at": int(time.time())}
        try:
            _STORE.parent.mkdir(parents=True, exist_ok=True)
            _STORE.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass  # limits are a convenience; a read-only profile must not break a reply


def _load():
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def claude(exe):
    result = {"label": "Claude i Haiku", "plan": None, "windows": [], "checked_at": None,
              "note": "Limity odświeżają się przy każdej odpowiedzi Claude'a lub Haiku."}
    try:
        code, out = _run([exe, "auth", "status"])
        status = json.loads(out) if code == 0 else {}
        result["plan"] = (status.get("subscriptionType") or status.get("authMethod") or "").capitalize() or None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    with _LOCK:
        result.update(_load().get("claude") or {})
    if not result["windows"]:
        result["note"] = "Limity pojawią się po pierwszej odpowiedzi Claude'a lub Haiku."
    return result


# ---- Codex ----------------------------------------------------------------
def codex(home=None):
    result = {"label": "Codex", "plan": None, "windows": [], "checked_at": None,
              "note": "Odświeża się po każdej odpowiedzi Codexa."}
    folder = Path(home or Path.home()) / ".codex" / "sessions"
    try:
        logs = sorted(folder.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    except OSError:
        logs = []
    for log in logs:
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if '"rate_limits"' not in line:
                continue
            try:
                entry = json.loads(line)
                limits = entry["payload"]["rate_limits"]
            except (ValueError, KeyError, TypeError):
                continue
            if not isinstance(limits, dict):
                continue
            result["plan"] = (limits.get("plan_type") or "").capitalize() or None
            for key in ("primary", "secondary"):
                w = limits.get(key)
                if isinstance(w, dict) and w.get("used_percent") is not None:
                    result["windows"].append(_window(_span(w.get("window_minutes")), w["used_percent"],
                                                     w.get("resets_at")))
            try:
                result["checked_at"] = int(datetime.fromisoformat(
                    entry["timestamp"].replace("Z", "+00:00")).timestamp())
            except (KeyError, ValueError, AttributeError):
                result["checked_at"] = int(log.stat().st_mtime)
            return result
    result["note"] = "Limity pojawią się po pierwszej odpowiedzi Codexa."
    return result


# ---- Antigravity ----------------------------------------------------------
_AGY_GROUPS = {"gemini models": "Modele Gemini", "claude and gpt models": "Modele Claude i GPT"}

def parse_agy_usage(text):
    """Lines: '<models>\\tWeekly Limit Remaining\\t91%\\t2026-11-09T19:43:39Z'."""
    windows = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 4 or not parts[2].endswith("%"):
            continue
        try:
            remaining = float(parts[2].rstrip("%"))
            resets = int(datetime.fromisoformat(parts[3].replace("Z", "+00:00")).timestamp())
        except ValueError:
            continue
        span = "tydzień" if "weekly" in parts[1].lower() else parts[1]
        name = _AGY_GROUPS.get(parts[0].lower(), parts[0])
        windows.append(_window(f"{name}, {span}", 100 - remaining, resets))
    return windows


def antigravity(exe):
    result = {"label": "Antigravity", "plan": "Konto Google", "windows": [], "checked_at": None, "note": None}
    try:
        code, out = _run([exe, "-p=/usage"], timeout=60)
        result["windows"] = parse_agy_usage(out)
        result["checked_at"] = int(time.time())
        if not result["windows"]:
            result["note"] = "Antigravity nie podał limitów. Czy jest zalogowany?"
    except (OSError, subprocess.SubprocessError):
        result["note"] = "Nie udało się zapytać Antigravity o limity."
    return result


def collect(binaries):
    """All accounts at once; the slow CLI calls run side by side."""
    jobs = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        if binaries.get("claude"):
            jobs.append(pool.submit(claude, binaries["claude"]))
        if binaries.get("codex"):
            jobs.append(pool.submit(codex))
        if binaries.get("antigravity"):
            jobs.append(pool.submit(antigravity, binaries["antigravity"]))
        return [job.result() for job in jobs]
