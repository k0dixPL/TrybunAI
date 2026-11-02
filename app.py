"""TrybunAI: one chat window for Claude Code, Codex and Gemini CLI."""
from __future__ import annotations

import base64
import json
import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path

import webview

from trybun.core import Session


def base_dir() -> Path:
    """The folder the exe was copied to is the project the models work in."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()


def resource(name: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return root / name


class Bridge:
    """Forwards events to the page from one thread, merging text deltas."""

    def __init__(self):
        self._queue = queue.Queue()
        self.window = None
        threading.Thread(target=self._pump, daemon=True).start()

    def emit(self, event):
        self._queue.put(event)

    def _pump(self):
        while True:
            batch = [self._queue.get()]
            threading.Event().wait(0.03)
            while not self._queue.empty():
                event = self._queue.get()
                last = batch[-1]
                if event["t"] == "delta" and last["t"] == "delta" and last["id"] == event["id"]:
                    last["text"] += event["text"]
                else:
                    batch.append(event)
            if self.window:
                try:
                    self.window.evaluate_js(f"window.onEvents({json.dumps(batch)})")
                except Exception:  # window is closing
                    return


class Api:
    """Methods callable from JavaScript. Underscored attributes are not exposed."""

    def __init__(self, session: Session):
        self._session = session
        self._window = None

    def snapshot(self):
        return self._session.snapshot()

    def logo(self):
        data = resource("ui/logo.png").read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode()

    def send(self, text, target, attachments=()):
        return self._session.send(text, target, attachments)

    def setup_status(self):
        return self._session.setup_status()

    def start_setup(self):
        return self._session.start_setup()

    def pick_attachments(self):
        picked = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True)
        return [self._session.attach_file(path) for path in picked or []]

    def paste_attachment(self, name, encoded):
        return self._session.attach_bytes(name, encoded)

    def image_data(self, rel):
        return self._session.image_data(rel)

    def open_image(self, rel):
        path = self._session.image_path(rel)
        if path:
            os.startfile(path)

    def refine(self, text, target):
        return self._session.refine(text, target)

    def stop(self, key):
        self._session.stop(key)

    def update_settings(self, changes):
        return self._session.update_settings(changes)

    def new_chat(self):
        return self._session.new_chat()

    def remote_start(self):
        return self._session.remote_start()

    def remote_stop(self):
        self._session.remote_stop()

    def choose_project(self):
        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"ok": False, "cancelled": True}
        result = self._session.set_project(picked[0])
        if result["ok"]:
            self._window.set_title(f"TrybunAI · {self._session.project.name}")
        return result

    def open_link(self, url):
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            webbrowser.open(url)


def main():
    bridge = Bridge()
    session = Session(base_dir(), bridge.emit)
    api = Api(session)
    html = resource("ui/index.html").read_text(encoding="utf-8")
    window = webview.create_window(
        f"TrybunAI · {session.project.name}", html=html, js_api=api,
        width=1100, height=820, min_size=(640, 480), background_color="#14161a",
    )
    api._window = window
    bridge.window = window
    window.events.closed += session.shutdown
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
