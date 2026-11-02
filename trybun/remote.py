"""Runs `claude remote-control`, which lets the Claude app drive sessions on this computer."""
from __future__ import annotations

import collections
import re
import subprocess
import threading

from . import setup

NO_WINDOW = subprocess.CREATE_NO_WINDOW
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_URL = re.compile(r"https://claude\.ai/code\S*")


class RemoteControl:
    """One server process at most. Every change of state is emitted as a "remote" event."""

    def __init__(self, emit):
        self._emit = emit
        self._lock = threading.Lock()
        self._proc = None
        self._stopping = False
        self._state = {"state": "off", "url": None, "error": None}

    @property
    def active(self):
        with self._lock:
            return self._proc is not None

    def status(self):
        with self._lock:
            return dict(self._state)

    def _publish(self, **state):
        """Call with the lock held; events are ordered the same way as the states."""
        self._state = {"state": "off", "url": None, "error": None, **state}
        self._emit({"t": "remote", **self._state})

    def start(self, cmd, cwd):
        with self._lock:
            if self._proc:
                return {"ok": True}
            try:
                # No stdin: without a terminal the server reports problems instead of asking.
                self._proc = subprocess.Popen(
                    cmd, cwd=cwd, env=setup._env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                )
            except OSError as exc:
                return {"ok": False, "error": f"Nie udało się uruchomić Claude: {exc}"}
            self._stopping = False
            self._publish(state="connecting")
            proc = self._proc
        threading.Thread(target=self._read, args=(proc,), daemon=True).start()
        return {"ok": True}

    def _read(self, proc):
        tail = collections.deque(maxlen=5)
        connected = False
        for raw in proc.stdout:
            line = _ANSI.sub("", raw.decode("utf-8", "replace")).strip()
            if line:
                tail.append(line)
            url = _URL.search(line)
            if url or "Connected" in line:
                connected = True
                with self._lock:  # the server redraws its status, so most of these change nothing
                    link = url.group() if url else self._state["url"]
                    if self._state["state"] != "connected" or self._state["url"] != link:
                        self._publish(state="connected", url=link)
        code = proc.wait()
        proc.stdout.close()
        with self._lock:
            error = None
            if not self._stopping:
                error = (f"Zdalne sterowanie przestało działać (kod {code})." if connected
                         else (tail[-1] if tail else f"Claude zakończył pracę (kod {code})."))
            self._proc = None
            self._publish(error=error)

    def stop(self):
        """Also ends the sessions the server spawned: /T takes the whole process tree."""
        with self._lock:
            proc = self._proc
            if not proc:
                return
            self._stopping = True
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, creationflags=NO_WINDOW)
