"""Live check against the real CLIs. Spends a little quota.

Works in a normal folder next to this script: Python's tempfile creates owner-only
ACLs on Windows, which the Codex sandbox cannot read, so it would give false failures.

Run: .venv\\Scripts\\python e2e_live.py [claude codex antigravity]
"""
import shutil
import sys
import time
from pathlib import Path

from trybun.core import Session


def wait(session, timeout=240):
    end = time.time() + timeout
    while session._busy and time.time() < end:
        time.sleep(0.1)
    if session._busy:
        raise SystemExit("TIMEOUT")


def check(name, passed, session):
    print("PASS" if passed else "FAIL", name, "|", repr(session.messages[-1].get("text"))[:150],
          session.messages[-1].get("error") or "")


def main(agents):
    folder = Path(__file__).parent / "_e2e test"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    try:
        (folder / "a.txt").write_text("haslo-77", encoding="utf-8")
        session = Session(folder, lambda event: None)
        for agent in agents:
            session.update_settings({"mode": "read"})
            session.send(f"@{agent} Odczytaj plik a.txt i podaj jego treść oraz słowo: zażółć", "claude")
            wait(session)
            reply = session.messages[-1].get("text", "")
            check(f"{agent} odczyt", "haslo-77" in reply and "zażółć" in reply, session)

            session.send(f"@{agent} Utwórz plik {agent}-ro.txt z treścią hi.", "claude")
            wait(session)
            check(f"{agent} tylko odczyt blokuje zapis", not (folder / f"{agent}-ro.txt").exists(), session)

            session.update_settings({"mode": "edit"})
            session.send(f"@{agent} Utwórz plik {agent}-rw.txt z treścią hi.", "claude")
            wait(session)
            check(f"{agent} edycja zapisuje, sesja wznowiona", (folder / f"{agent}-rw.txt").exists(), session)
        if len(agents) > 1:
            code = f"ZEBRA-{int(time.time()) % 1000}"
            session.send(f"@{agents[0]} Napisz dokładnie: {code}", "claude")
            wait(session)
            session.send(f"@{agents[1]} Jakie słowo-kod napisał przed chwilą drugi model? Podaj samo słowo.", "claude")
            wait(session)
            check("wspólny kontekst", code in session.messages[-1].get("text", ""), session)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:] or ["claude", "codex"])
