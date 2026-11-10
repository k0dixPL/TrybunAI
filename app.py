"""TrybunAI: one chat window for Claude Code, Codex and Antigravity CLI."""
from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import webview

from trybun import __version__, update
from trybun.core import Session

AUTHOR = "k0dixPL"


def window_title(project_name):
    return f"TrybunAI {__version__} · {project_name}"


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
                except Exception:  # one bad event or a closing window: keep the pump alive for the rest
                    continue


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

    def limits(self):
        return self._session.limits()

    def debate(self, plan):
        return self._session.start_debate(plan if isinstance(plan, dict) else {})

    def fresh_session(self, agent):
        return self._session.fresh_session(agent)

    def get_memory(self):
        return self._session.read_memory()

    def save_state(self):
        return self._session.save_state()

    def about(self):
        return {"version": __version__, "author": AUTHOR, "repo": f"https://github.com/{update.REPO}",
                "page": update.PAGE, "frozen": bool(getattr(sys, "frozen", False))}

    def check_update(self):
        return update.check(__version__)

    def install_update(self):
        """Swap this exe for the newest release and start it; only the running copy is updated."""
        if not getattr(sys, "frozen", False):
            return {"ok": False, "error": "Aktualizacja działa tylko w pliku exe. Tu użyj git pull."}
        if self._session._busy:
            return {"ok": False, "error": "Najpierw poczekaj, aż modele skończą pracę."}
        info = update.check(__version__)
        if not info["ok"]:
            return info
        if not info["newer"]:
            return {"ok": False, "error": "Masz już najnowszą wersję."}
        result = update.install(info, sys.executable)
        if not result["ok"]:
            return result
        # A fresh PyInstaller process must not inherit this one's unpacked temp folder.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEI", "_PYI"))}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen([sys.executable], cwd=str(base_dir()), env=env,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        threading.Timer(0.5, self._window.destroy).start()
        return {"ok": True, "version": info["version"]}

    def refresh_map(self):
        return self._session.refresh_map()

    def map_info(self):
        return self._session.map_info()

    def token_stats(self, range_key="7d"):
        return self._session.token_stats(range_key)

    def open_map_folder(self):
        folder = self._session.refresh_map().get("folder")
        if folder:
            os.startfile(folder)

    def start_files(self):
        return self._session.start_files()

    def choose_proposals(self, message_id, selected=None, note=""):
        return self._session.choose_proposals(message_id, selected, note)

    def retry_with(self, agent, mode):
        return self._session.retry_with(agent, mode)

    def model_options(self, refresh=False):
        return self._session.model_options(refresh)

    def set_memory(self, text):
        return self._session.write_memory(text)

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

    def open_project_folder(self):
        os.startfile(str(self._session.project))

    def open_link(self, url):
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            webbrowser.open(url)


def main():
    if getattr(sys, "frozen", False):
        update.cleanup(sys.executable)  # the exe replaced by the last update
    bridge = Bridge()
    session = Session(base_dir(), bridge.emit)
    api = Api(session)
    html = resource("ui/index.html").read_text(encoding="utf-8")
    window = webview.create_window(
        window_title(session.project.name), html=html, js_api=api,
        width=1100, height=820, min_size=(640, 480), background_color="#14161a",
        text_select=True,  # pywebview domyślnie blokuje zaznaczanie tekstu w całym oknie
    )
    api._window = window
    bridge.window = window
    window.events.closed += session.shutdown
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
