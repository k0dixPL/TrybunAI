"""Model lists for the Settings dropdowns, read from what each CLI already knows. Nothing here calls a model."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

NO_WINDOW = subprocess.CREATE_NO_WINDOW
_STORE = Path(os.environ.get("APPDATA") or Path.home()) / "TrybunAI" / "models.json"
_LOCK = threading.Lock()
# Claude Code accepts these aliases and maps them to the newest model of each family.
_CLAUDE_ALIASES = [("sonnet", "Sonnet (najnowszy)"), ("opus", "Opus (najnowszy)"), ("haiku", "Haiku (najnowszy)")]


def _option(value, label=None):
    return {"value": value, "label": label or value}


def claude(home=None):
    options = [_option(v, l) for v, l in _CLAUDE_ALIASES]
    try:
        config = json.loads((Path(home or Path.home()) / ".claude.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return options
    extra = config.get("additionalModelOptionsCache") or []
    for item in extra if isinstance(extra, list) else [extra]:
        if isinstance(item, dict) and item.get("value"):
            options.append(_option(item["value"], item.get("label") or item["value"]))
    used = config.get("lastModelUsage") or {}
    for model in used if isinstance(used, dict) else []:
        if model.startswith("claude-"):
            options.append(_option(model))
    return _unique(options)


def codex(home=None):
    try:
        cache = json.loads((Path(home or Path.home()) / ".codex" / "models_cache.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = [m for m in cache.get("models") or [] if isinstance(m, dict) and m.get("slug")]
    models = [m for m in models if m.get("visibility") != "hide"]
    models.sort(key=lambda m: m.get("priority") or 0)
    return _unique([_option(m["slug"], m.get("display_name") or m["slug"]) for m in models])


def antigravity(exe):
    """`agy models` prints '<id>\\t<name>' lines; signed out it fails and the list stays empty."""
    try:
        out = subprocess.run([exe, "models"], capture_output=True, timeout=60, creationflags=NO_WINDOW,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    options = []
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) >= 2 and parts[0] and " " not in parts[0]:
            options.append(_option(parts[0], parts[1]))
    return options


def _unique(options):
    seen, result = set(), []
    for option in options:
        if option["value"] not in seen:
            seen.add(option["value"])
            result.append(option)
    return result


def collect(binaries, refresh=False):
    """Lists per agent. Antigravity needs a CLI call, so its list is cached until a refresh."""
    with _LOCK:
        try:
            cached = json.loads(_STORE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        agy = cached.get("antigravity") or []
        if (refresh or not agy) and binaries.get("antigravity"):
            fresh = antigravity(binaries["antigravity"])
            if fresh or refresh:
                agy = fresh
                try:
                    _STORE.parent.mkdir(parents=True, exist_ok=True)
                    _STORE.write_text(json.dumps({"antigravity": agy}), encoding="utf-8")
                except OSError:
                    pass
    claude_list = claude()
    return {"claude": claude_list, "haiku": claude_list, "codex": codex(), "antigravity": agy, "gemini": []}
