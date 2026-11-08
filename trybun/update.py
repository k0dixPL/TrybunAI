"""Checks GitHub Releases for a newer TrybunAI.exe and swaps the running exe for it."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

REPO = "k0dixPL/TrybunAI"
PAGE = "https://k0dixpl.github.io/TrybunAI/"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_ASSET = "TrybunAI.exe"
_HEADERS = {"User-Agent": "TrybunAI-updater", "Accept": "application/vnd.github+json"}


def parse_version(text):
    """'v1.0.12' -> (1, 0, 12); anything unparsable sorts lowest."""
    parts = re.findall(r"\d+", str(text or ""))
    return tuple(int(p) for p in parts[:3]) if parts else (0,)


def latest(timeout=10, opener=urllib.request.urlopen):
    with opener(urllib.request.Request(_API, headers=_HEADERS), timeout=timeout) as response:
        release = json.loads(response.read().decode("utf-8"))
    asset = next((a for a in release.get("assets") or [] if a.get("name") == _ASSET), None)
    digest = (asset or {}).get("digest") or ""
    notes = (release.get("body") or "").split("**Pobierz:**")[0].strip()
    return {"version": release.get("tag_name", "").lstrip("v"), "notes": notes,
            "published": release.get("published_at"), "page": release.get("html_url"),
            "url": (asset or {}).get("browser_download_url"), "size": (asset or {}).get("size"),
            "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None}


def check(current, **kwargs):
    try:
        info = latest(**kwargs)
    except Exception as exc:  # offline, GitHub down, rate limit: the app keeps working
        code = getattr(exc, "code", None)
        if code == 403:
            return {"ok": False, "error": "GitHub chwilowo ogranicza liczbę sprawdzeń. Spróbuj za godzinę."}
        detail = f"HTTP {code}" if code else type(exc).__name__
        return {"ok": False, "error": f"Nie udało się połączyć z GitHubem ({detail})."}
    info.update(ok=True, current=current, newer=parse_version(info["version"]) > parse_version(current))
    return info


def install(info, exe, opener=urllib.request.urlopen, progress=None):
    """Download the release exe next to the running one, verify it, then swap the files.

    Windows lets a running exe be renamed but not overwritten, so the old one becomes
    TrybunAI.old.exe and is removed by cleanup() on the next start.
    """
    exe = Path(exe)
    if not info.get("url") or not info.get("sha256"):
        return {"ok": False, "error": "Wydanie nie ma pliku exe z sumą kontrolną; pobierz je ze strony."}
    fresh, old = exe.with_name(exe.stem + ".new.exe"), exe.with_name(exe.stem + ".old.exe")
    digest, done = hashlib.sha256(), 0
    try:
        with opener(urllib.request.Request(info["url"], headers={"User-Agent": _HEADERS["User-Agent"]}),
                    timeout=30) as response, open(fresh, "wb") as out:
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and info.get("size"):
                    progress(done / info["size"])
    except Exception as exc:
        fresh.unlink(missing_ok=True)
        return {"ok": False, "error": f"Pobieranie nie powiodło się ({type(exc).__name__})."}
    with open(fresh, "rb") as f:
        header = f.read(2)
    if digest.hexdigest() != info["sha256"] or header != b"MZ":
        fresh.unlink(missing_ok=True)
        return {"ok": False, "error": "Pobrany plik nie zgadza się z sumą kontrolną z GitHuba. Nic nie zmieniono."}
    try:
        old.unlink(missing_ok=True)
        os.replace(exe, old)
        os.replace(fresh, exe)
    except OSError as exc:
        if not exe.exists() and old.exists():
            os.replace(old, exe)  # put the working exe back
        fresh.unlink(missing_ok=True)
        return {"ok": False, "error": f"Nie udało się podmienić pliku: {exc}"}
    return {"ok": True}


def cleanup(exe):
    """Remove the previous exe left by an update; it may still be locked for a moment."""
    try:
        Path(exe).with_name(Path(exe).stem + ".old.exe").unlink(missing_ok=True)
    except OSError:
        pass
