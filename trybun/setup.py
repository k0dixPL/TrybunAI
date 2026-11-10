"""Installs missing CLIs, then opens one login window at a time."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import winreg
from pathlib import Path

NO_WINDOW = subprocess.CREATE_NO_WINDOW
_WINGET = ["winget", "install", "--exact", "--silent", "--disable-interactivity",
           "--accept-package-agreements", "--accept-source-agreements", "--id"]
_STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "_MEIPASS2")


def _env():
    return {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}


def _npm(package):
    return ["npm", "install", "--global", "--no-fund", "--no-audit", package]


TOOLS = {
    # Each tool lists install commands to try in order, so a missing winget falls back to npm.
    "claude": {"label": "Claude Code", "install": [_WINGET + ["Anthropic.ClaudeCode"],
                                                   _npm("@anthropic-ai/claude-code")],
               "login": ["auth", "login"]},
    "codex": {"label": "Codex", "install": [_WINGET + ["OpenAI.Codex"], _npm("@openai/codex")],
              "login": ["login"]},
    # Google's official installer: downloads agy.exe, checks its SHA-512, adds it to the user PATH.
    "agy": {"label": "Antigravity CLI",
            "install": [["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                         "irm https://antigravity.google/cli/install.ps1 | iex"]],
            "login": [],
            "login_hint": "Antigravity: zaloguj się kontem Google w oknie. Okno zamknie się samo po zalogowaniu."},
}
_FALLBACK = {"agy": Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"}


def refresh_path():
    """Installers change PATH in the registry; a running process would not see it."""
    parts = []
    locations = ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                 (winreg.HKEY_CURRENT_USER, "Environment"))
    for root, key in locations:
        try:
            with winreg.OpenKey(root, key) as handle:
                parts.append(os.path.expandvars(winreg.QueryValueEx(handle, "Path")[0]))
        except OSError:
            pass
    parts.append(os.environ.get("PATH", ""))
    os.environ["PATH"] = ";".join(parts)


def find(name):
    for candidate in (f"{name}.exe", f"{name}.cmd", name):
        path = shutil.which(candidate)
        if path:
            return path
    fallback = _FALLBACK.get(name)
    return str(fallback) if fallback and fallback.is_file() else None


def is_logged_in(tool, exe):
    try:
        if tool == "claude":
            out = subprocess.run([exe, "auth", "status"], capture_output=True, timeout=30,
                                 creationflags=NO_WINDOW, env=_env(), stdin=subprocess.DEVNULL)
            return bool(json.loads(out.stdout.decode("utf-8", "replace")).get("loggedIn"))
        if tool == "codex":
            out = subprocess.run([exe, "login", "status"], capture_output=True, timeout=30,
                                 creationflags=NO_WINDOW, env=_env(), stdin=subprocess.DEVNULL)
            return out.returncode == 0
        if tool == "agy":  # signed out, it refuses to list models
            out = subprocess.run([exe, "models"], capture_output=True, timeout=30,
                                 creationflags=NO_WINDOW, env=_env(), stdin=subprocess.DEVNULL)
            return out.returncode == 0
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return False


def status():
    result = {}
    for tool, info in TOOLS.items():
        exe = find(tool)
        result[tool] = {"label": info["label"], "installed": bool(exe),
                        "logged_in": bool(exe) and is_logged_in(tool, exe)}
    return result


def _run_quiet(cmd):
    """Runs without a window. UAC prompts from installers still appear on their own."""
    exe = find(cmd[0])
    if not exe:
        return False, f"nie znaleziono: {cmd[0]}"
    try:
        out = subprocess.run([exe, *cmd[1:]], capture_output=True, creationflags=NO_WINDOW,
                             env=_env(), stdin=subprocess.DEVNULL, timeout=900)
    except subprocess.SubprocessError as exc:
        return False, str(exc)
    lines = out.stdout.decode("utf-8", "replace").strip().splitlines() or \
        out.stderr.decode("utf-8", "replace").strip().splitlines()
    return out.returncode == 0, lines[-1].strip() if lines else f"kod {out.returncode}"


def _open_login_window(cmd, done, poll=3.0):
    """Blocks until the user closes the window or done() says the login landed, keeping logins
    one at a time. A CLI that stays in its chat after a browser login would never exit on its own."""
    proc = subprocess.Popen(cmd, env=_env(), cwd=Path.home(), creationflags=subprocess.CREATE_NEW_CONSOLE)
    while True:
        try:
            proc.wait(timeout=poll)
            return
        except subprocess.TimeoutExpired:
            pass
        if done():
            # The .cmd shim runs under cmd.exe, so the whole tree must go.
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=NO_WINDOW)
            proc.wait()
            return


def run_setup(log, run=_run_quiet, open_window=_open_login_window):
    """Install what is missing, then log in to what is not logged in. Returns True if all is ready."""
    # 1. Everything installs first, so logins are not interleaved with long waits.
    for tool, info in TOOLS.items():
        if find(tool):
            log(f"{info['label']}: już zainstalowany.")
            continue
        log(f"{info['label']}: instaluję…")
        detail = ""
        for cmd in info["install"]:
            ok, detail = run(cmd)
            refresh_path()
            if find(tool):
                break
        log(f"{info['label']}: zainstalowany." if find(tool) else f"{info['label']}: nie udało się ({detail}).")

    # 2. One login window at a time.
    ready = True
    for tool, info in TOOLS.items():
        exe = find(tool)
        if not exe:
            ready = False
            continue
        if is_logged_in(tool, exe):
            log(f"{info['label']}: już zalogowany.")
            continue
        log(info.get("login_hint") or f"{info['label']}: zaloguj się w nowym oknie.")
        try:
            open_window([exe, *info["login"]], lambda: is_logged_in(tool, exe))
        except OSError as exc:
            log(f"{info['label']}: nie udało się otworzyć okna ({exc}).")
        if is_logged_in(tool, exe):
            log(f"{info['label']}: zalogowany.")
        else:
            ready = False
            log(f"{info['label']}: logowanie nieukończone.")
    return ready
