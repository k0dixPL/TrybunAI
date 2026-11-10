"""Offline tests. Real CLIs are replaced by a small script speaking each JSONL dialect."""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
from trybun import core, limits, mapa, models, setup, stats, update  # noqa: E402
from trybun.agents import (build_command, build_remote_command, parse_event, session_name,  # noqa: E402
                           stdin_payload)
from trybun.remote import RemoteControl  # noqa: E402
from trybun.core import (Session, build_turn_prompt, clean_prompter_output, parse_debate,  # noqa: E402
                         parse_targets)

FAKE = r"""
import json, sys, time
data = sys.stdin.buffer.read().decode("utf-8")
open("last_prompt.txt", "w", encoding="utf-8").write(data)
if "ZAWIS" in data:
    time.sleep(60)
if "ZLE" in data:
    print("Please set an Auth method", file=sys.stderr)
    sys.exit(41)
reply = "odp zażółć"
if "WERDYKT: AKCEPTUJĘ" in data:  # a reviewer: remarks first, acceptance on the re-check
    reply = "dobrze\nWERDYKT: AKCEPTUJĘ" if "ponowne sprawdzenie" in data else "błąd w pliku\nWERDYKT: UWAGI"
if "PROPOZYCJE" in data:  # a debate summary
    reply = "Stanęło na JSON.\n\n**PROPOZYCJE:**\n1. Zapis do settings.json\n2. **Pole schema** (sporne)\n3. Migracja"
print(json.dumps({"event": "init", "conversation_id": "abc-123"}))
print(json.dumps({"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": reply}}), flush=True)
print(json.dumps({"event": "result", "result": {"status": "SUCCESS"}}))
"""


class Pure(unittest.TestCase):
    def test_mentions_only_at_start(self):
        self.assertEqual(parse_targets("@codex @claude zrób", "antigravity"), (["codex", "claude"], "zrób"))
        self.assertEqual(parse_targets("zapytaj @codex o to", "antigravity"), (["antigravity"], "zapytaj @codex o to"))
        self.assertEqual(parse_targets("@wszyscy hej", "claude", ["claude", "codex", "antigravity"])[0],
                         ["claude", "codex", "antigravity"])
        self.assertEqual(parse_targets("@nieznany hej", "claude"), (["claude"], "@nieznany hej"))

    def test_context_skips_own_and_failed_messages(self):
        msgs = [
            {"role": "user", "targets": ["claude"], "text": "pytanie"},
            {"role": "assistant", "agent": "claude", "text": "odp claude", "status": "ok"},
            {"role": "assistant", "agent": "codex", "text": "moja", "status": "ok"},
            {"role": "assistant", "agent": "antigravity", "text": "zepsute", "status": "error"},
        ]
        prompt = build_turn_prompt(msgs, "codex", "dalej")
        self.assertIn("odp claude", prompt)
        self.assertNotIn("moja", prompt)
        self.assertNotIn("zepsute", prompt)
        self.assertEqual(build_turn_prompt([], "codex", "dalej"), "dalej")

    def test_context_is_capped_and_keeps_newest(self):
        msgs = [{"role": "assistant", "agent": "claude", "status": "ok", "text": f"{i} " + "x" * 9000}
                for i in range(6)]
        prompt = build_turn_prompt(msgs, "codex", "q")
        self.assertIn("5 xxx", prompt)
        self.assertNotIn("0 xxx", prompt)
        self.assertLess(len(prompt), core.CONTEXT_LIMIT + 1000)

    def test_read_only_never_grants_write(self):
        self.assertIn("dontAsk", build_command("claude", "c", "read"))
        self.assertIn('sandbox_mode="read-only"', build_command("codex", "c", "read"))
        for agent in ("claude", "codex", "antigravity"):
            joined = " ".join(build_command(agent, "c", "full", prompter=True))
            for flag in ("dangerously", "yolo", "workspace-write", "acceptEdits"):
                self.assertNotIn(flag, joined)

    def test_codex_resume_order(self):
        cmd = build_command("codex", "c", "edit", session="id-1")
        self.assertEqual(cmd[:3], ["c", "exec", "resume"])
        self.assertEqual(cmd[-2:], ["id-1", "-"])
        self.assertNotIn("-s", cmd)

    def test_unsafe_values_rejected(self):
        for bad in ("x & calc", 'a"b', "a|b", "a b"):
            with self.assertRaises(ValueError):
                build_command("antigravity", "c", model=bad)
            with self.assertRaises(ValueError):
                build_command("antigravity", "c", session=bad)

    def test_parsers(self):
        self.assertEqual(parse_event("claude", {"type": "stream_event", "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}}}), [("text", "a")])
        self.assertEqual(parse_event("claude", {"type": "stream_event", "parent_tool_use_id": "t", "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}}}), [])
        self.assertEqual(parse_event("claude", {"type": "result", "is_error": True, "result": "x"}), [("fatal", "x")])
        self.assertEqual(parse_event("codex", {"type": "thread.started", "thread_id": "t"}), [("session", "t")])
        self.assertEqual(parse_event("codex", {"type": "turn.failed", "error": {"message": "m"}}), [("fatal", "m")])
        self.assertEqual(parse_event("antigravity", {"event": "result", "result": {"status": "FAILED", "error": "m"}}),
                         [("fatal", "m")])

    def test_crash_dump_reduced_to_cause(self):
        result = core._Result()
        result.returncode = 1
        result.tail.extend([
            "Warning: 256-color support not detected.",
            "}",
            "An unexpected critical error occurred:IneligibleTierError: no longer supported",
            "    at foo (file:///x.js:1:1)",
        ])
        message = result.error_message()
        self.assertNotIn("file:///", message)
        self.assertNotIn("256-color", message)

    def test_everyone_respects_exclusions(self):
        self.assertEqual(parse_targets("@wszyscy hej", "antigravity", ["claude", "codex"]), (["claude", "codex"], "hej"))
        self.assertEqual(parse_targets("@agy hej", "claude", ["claude"]), (["antigravity"], "hej"), "direct mention wins")
        self.assertEqual(parse_targets("@wszyscy @agy hej", "claude", ["codex"])[0], ["codex", "antigravity"])
        self.assertEqual(parse_targets("@wszyscy hej", "claude", []), ([], "hej"), "must not fall back to default")

    def test_debate_parsing(self):
        team = ["claude", "codex"]
        self.assertIsNone(parse_debate("@claude co to @debata", team))
        self.assertIsNone(parse_debate("@debatax 3 temat", team))
        self.assertEqual(parse_debate("@debata 2 @agy @codex baza czy pliki", team),
                         {"rounds": 2, "agents": ["antigravity", "codex"], "topic": "baza czy pliki"})
        self.assertEqual(parse_debate("@debata temat", team), {"rounds": 3, "agents": team, "topic": "temat"})
        self.assertEqual(parse_debate("@debata 3 lata temu", team)["topic"], "lata temu")
        for bad in ("@debata 0 temat", "@debata 11 temat", "@debata @claude temat", "@debata 2 @claude @codex", "@debata"):
            self.assertIn("error", parse_debate(bad, team), bad)

    def test_debate_prompts_change_by_round(self):
        first = core.build_debate_turn("t", ["claude", "codex"], 1, 3)
        last = core.build_debate_turn("t", ["claude", "codex"], 3, 3)
        self.assertIn("Runda 1 z 3", first)
        self.assertIn("ostatnia runda", last)
        self.assertIn("niczego nie zmieniaj", first)

    def test_haiku_is_claude_with_cheap_model(self):
        self.assertEqual(parse_targets("@haiku hej", "claude"), (["haiku"], "hej"))
        self.assertNotIn("haiku", parse_targets("@wszyscy hej", "claude")[0])
        cmd = build_command("haiku", "c", "read")
        self.assertEqual(cmd[cmd.index("--model") + 1], "haiku")
        self.assertIn("dontAsk", cmd)
        cmd = build_command("haiku", "c", "read", model="claude-haiku-5-5")
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-haiku-5-5")
        self.assertEqual(parse_event("haiku", {"type": "result", "is_error": True, "result": "x"}), [("fatal", "x")])
        self.assertNotIn("--model", build_command("claude", "c", "read"))

    def test_prompter_uses_haiku_by_default_without_tools(self):
        cmd = build_command("haiku", "c", "read", prompter=True)
        self.assertIn("--no-session-persistence", cmd)
        self.assertIn("haiku", cmd)

    def test_antigravity_command_and_permissions(self):
        def rules(mode, **kw):
            cmd = build_command("antigravity", "agy.exe", mode, **kw)
            return json.loads(cmd[cmd.index("--settings") + 1])["permissions"]
        self.assertEqual(rules("read"), {"allow": ["read_file(*)"], "deny": ["write_file(*)", "command(*)"]})
        self.assertIn("write_file(*)", rules("edit")["allow"])
        self.assertIn("command(*)", rules("edit")["deny"])
        self.assertNotIn("allow", rules("full", prompter=True), "the prompter never gets tools")
        cmd = build_command("antigravity", "agy.exe", "full", session="c-1", model="gemini-3.8-flash-high")
        self.assertIn("--dangerously-skip-permissions", cmd)
        self.assertEqual(cmd[cmd.index("--conversation") + 1], "c-1")
        self.assertNotIn("-p", cmd, "the prompt goes through stdin as stream-json")
        line = json.loads(stdin_payload("antigravity", "zażółć"))
        self.assertEqual(line, {"event": "user", "message": {"role": "user", "content": "zażółć"}})
        self.assertEqual(stdin_payload("codex", "x"), "x")
        self.assertEqual(parse_targets("@agy hej", "claude"), (["antigravity"], "hej"))

    def test_antigravity_events(self):
        ev = lambda o: parse_event("antigravity", o)
        self.assertEqual(ev({"event": "init", "conversation_id": "c-1"}), [("session", "c-1")])
        self.assertEqual(ev({"event": "step_update", "step_update": {"step_type": "agent_response",
                                                                     "state": "ACTIVE", "text_delta": "ok"}}),
                         [("text", "ok")])
        tool = {"event": "step_update", "step_update": {"step_type": "tool", "state": "ACTIVE", "tool_name": "read_file",
                                                        "tool_info": {"parameters": {"Path": "C:\\a.txt"}}}}
        self.assertEqual(ev(tool), [("break", None), ("activity", "read_file: C:\\a.txt")])
        tool["step_update"]["state"] = "DONE"
        self.assertEqual(ev(tool), [], "a tool is announced once")
        self.assertEqual(ev({"event": "result", "result": {"status": "SUCCESS", "response": "ok"}}), [])
        self.assertEqual(ev({"event": "result", "result": {"status": "ERROR", "error": "brak limitu"}}),
                         [("fatal", "brak limitu")])

    def test_proposals_are_parsed_from_a_summary(self):
        text = "Podsumowanie.\nDruga linia.\n\nPROPOZYCJE:\n1) Pierwsza\n2. **Druga**\n- trzecia\n\nKoniec gadania."
        self.assertEqual(core.parse_proposals(text), ("Podsumowanie.\nDruga linia.", ["Pierwsza", "Druga", "trzecia"]))
        self.assertEqual(core.parse_proposals("Bez listy.\n1. coś"), ("Bez listy.\n1. coś", []))
        many = "PROPOZYCJE:\n" + "\n".join(f"{i}. p{i}" for i in range(1, 20))
        self.assertEqual(len(core.parse_proposals(many)[1]), core.MAX_PROPOSALS)

    def test_claude_reports_context_size_and_skips_skills(self):
        self.assertIn("--disable-slash-commands", build_command("claude", "c", "read"))
        event = {"type": "assistant", "message": {"id": "m1", "model": "claude-sonnet-5", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "a.html"}}],
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 437000}}}
        self.assertEqual(parse_event("claude", event),
                         [("activity", "Read: a.html"), ("usage", {"call": "m1", "model": "claude-sonnet-5",
                                                                   "context": 438002}),
                          ("tokens", {"call": "m1", "input": 1002, "cached": 437000, "output": 0})])
        result = core._Result()
        session = Session.__new__(Session)
        event["message"]["usage"]["output_tokens"] = 50  # the final event of the call has the output count
        for kind, value in parse_event("claude", event) + parse_event("claude", event):
            if kind in ("usage", "tokens"):
                Session._apply(session, kind, value, result, "r")
        self.assertEqual(result.usage(), {"model": "claude-sonnet-5", "context": 438002, "calls": 1},
                         "one call split over two events counts once")
        self.assertEqual(result.token_total(), {"input": 1002, "cached": 437000, "output": 50})

    def test_token_counts_from_codex_and_antigravity(self):
        codex = {"type": "turn.completed", "usage": {"input_tokens": 9000, "cached_input_tokens": 7000,
                                                     "output_tokens": 300}}
        self.assertEqual(parse_event("codex", codex),
                         [("tokens", {"call": "turn", "input": 2000, "cached": 7000, "output": 300})])
        agy = {"event": "step_update", "step_update": {"step_type": "agent_response", "state": "DONE",
               "conversation_id": "c", "step_index": 3, "usage": {"input_tokens": 500, "output_tokens": 40}}}
        self.assertIn(("tokens", {"call": "c:3", "input": 500, "cached": 0, "output": 40}),
                      parse_event("antigravity", agy))
        bad = {"type": "turn.completed", "usage": {"input_tokens": "x"}}
        self.assertEqual(parse_event("codex", bad)[0][1]["input"], 0, "junk never breaks a turn")

    def test_token_stats_buckets_by_local_time(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 11, 8, 15, 30)
            at = lambda *a: datetime(*a).timestamp()
            stats.record(tmp, "claude", "opus", "czat", {"input": 10, "cached": 100, "output": 5}, 2, at(2026, 11, 8, 15, 5))
            stats.record(tmp, "claude", "opus", "debata", {"input": 1, "cached": 0, "output": 1}, 1, at(2026, 11, 8, 9, 59))
            stats.record(tmp, "codex", None, "czat", {"input": 7, "cached": 0, "output": 3}, 1, at(2026, 11, 2, 0, 0))
            stats.record(tmp, "codex", None, "czat", {"input": 7, "cached": 0, "output": 3}, 1, at(2026, 11, 1, 23, 59))
            self.assertFalse(stats.record(tmp, "haiku", None, "czat", {}, 0), "an empty run is not written")
            with open(Path(tmp) / stats.FILE, "a", encoding="utf-8") as fh:
                fh.write('{"ts": 1, "agent": "x"\n')  # cut short by a crash
            week = stats.summarize(tmp, "7d", now)
            self.assertEqual([b["label"] for b in week["buckets"]][0], "02.11")
            self.assertEqual(week["buckets"][0]["by"]["codex"], {"runs": 1, "input": 7, "cached": 0, "output": 3},
                             "the day before the range is left out")
            self.assertEqual(week["buckets"][-1]["by"]["claude"]["runs"], 2)
            self.assertEqual(week["totals"]["claude"], {"runs": 2, "calls": 3, "input": 11, "cached": 100, "output": 6})
            self.assertEqual(week["kinds"]["debata"], {"input": 1, "cached": 0, "output": 1})
            day = stats.summarize(tmp, "24h", now)
            self.assertTrue(day["hourly"])
            self.assertEqual(len(day["buckets"]), 24)
            self.assertEqual(day["buckets"][-1]["label"], "15:00")
            self.assertEqual(day["buckets"][-1]["by"]["claude"]["output"], 5)
            self.assertEqual(day["buckets"][-7]["by"]["claude"]["output"], 1, "09:59 lands in the 09:00 bucket")
            self.assertNotIn("codex", day["totals"])
            self.assertEqual(stats.summarize(tmp, "zły")["range"], "7d")

    def test_history_is_imported_once_from_the_clis_own_logs(self):
        from datetime import datetime, timezone
        iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); project = tmp / "moj projekt"; data = project / ".trybunai"
            now = time.time(); t = now - 3600
            claude = tmp / "claude"; folder = claude / re.sub(r"[^A-Za-z0-9]", "-", str(project)); folder.mkdir(parents=True)
            usage = {"input_tokens": 3, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 7}
            def call(mid, ts, model="claude-opus-5-5", entry="sdk-cli", out=7):
                return {"type": "assistant", "entrypoint": entry, "isSidechain": False, "timestamp": iso(ts),
                        "message": {"id": mid, "model": model, "usage": {**usage, "output_tokens": out}}}
            user = lambda ts, entry="sdk-cli": {"type": "user", "entrypoint": entry, "timestamp": iso(ts),
                                                "message": {"content": "zrób to"}}
            tool = {"type": "user", "entrypoint": "sdk-cli", "message": {"content": [{"type": "tool_result"}]}}
            lines = [user(t), call("a", t, out=2), call("a", t, out=7), tool, call("b", t + 5),  # one run, two calls
                     user(t + 60), call("c", t + 61, model="claude-haiku-5-5"),
                     user(t + 90, "claude-desktop"), call("d", t + 91, entry="claude-desktop"),  # the user's own chat
                     {"type": "assistant", "entrypoint": "sdk-cli", "isSidechain": True, "timestamp": iso(t),
                      "message": {"id": "e", "model": "x", "usage": usage}}, "zepsuta linia"]
            (folder / "s1.jsonl").write_text("\n".join(json.dumps(l) if isinstance(l, dict) else l for l in lines),
                                             encoding="utf-8")
            codex = tmp / "codex"; day = datetime.fromtimestamp(t)
            cdir = codex / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"; cdir.mkdir(parents=True)
            count = lambda total, last: {"timestamp": iso(t), "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": total}, "last_token_usage": {"input_tokens": last,
                                                                                  "cached_input_tokens": 40, "output_tokens": 5}}}}
            meta = lambda cwd, origin="codex_exec": {"type": "session_meta", "payload": {"cwd": cwd, "originator": origin}}
            rows = [meta(str(project)), {"type": "event_msg", "payload": {"type": "task_started"}},
                    count(100, 100), count(100, 100), count(250, 150)]
            (cdir / "rollout-1.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
            (cdir / "rollout-2.jsonl").write_text("\n".join(map(json.dumps, [meta(str(tmp)), count(1, 1)])), encoding="utf-8")
            (cdir / "rollout-3.jsonl").write_text("\n".join(map(json.dumps, [meta(str(project), "codex_tui"), count(1, 1)])),
                                                  encoding="utf-8")
            stats.record(data, "claude", None, "czat", {"input": 1, "cached": 0, "output": 1}, 1, now - 60)
            self.assertEqual(stats.backfill(data, project, now, claude, codex), 3)
            rows = sorted(((r["agent"], r["calls"], r["input"], r["cached"], r["output"])
                           for r in stats.read(data) if r["kind"] == "historia"))
            self.assertEqual(rows, [("claude", 2, 206, 2000, 14), ("codex", 2, 170, 80, 10), ("haiku", 1, 103, 1000, 7)])
            self.assertIsNone(stats.backfill(data, project, now, claude, codex), "imported once")
            later = tmp / "pozniej" / ".trybunai"
            stats.record(later, "claude", None, "czat", {"input": 1, "cached": 0, "output": 1}, 1, t - 10)
            self.assertEqual(stats.backfill(later, project, now, claude, codex), 0,
                             "nothing after the first recorded run is imported again")

    def test_update_check_and_safe_swap(self):
        import hashlib, io
        new_exe = b"MZ nowy program"
        good = hashlib.sha256(new_exe).hexdigest()
        def release(sha):
            return {"tag_name": "v1.0.20", "body": "- zmiana\n\n**Pobierz:** plik", "html_url": "https://x/rel",
                    "assets": [{"name": "TrybunAI.exe", "browser_download_url": "https://x/TrybunAI.exe",
                                "size": len(new_exe), "digest": f"sha256:{sha}"}]}
        class Opener:
            def __init__(self, sha): self.sha = sha
            def __call__(self, request, timeout=None):
                body = json.dumps(release(self.sha)).encode() if "api.github" in request.full_url else new_exe
                return io.BytesIO(body)
        self.assertGreater(update.parse_version("v1.0.10"), update.parse_version("1.0.9"), "numbers, not text")
        info = update.check("1.0.11", opener=Opener(good))
        self.assertTrue(info["ok"] and info["newer"])
        self.assertEqual((info["version"], info["notes"]), ("1.0.20", "- zmiana"))
        self.assertFalse(update.check("1.0.20", opener=Opener(good))["newer"])
        def broken(request, timeout=None): raise OSError("offline")
        self.assertFalse(update.check("1.0.11", opener=broken)["ok"])
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp, "TrybunAI.exe"); exe.write_bytes(b"MZ stary")
            bad = update.install(update.check("1.0.11", opener=Opener("0" * 64)), exe, opener=Opener("0" * 64))
            self.assertFalse(bad["ok"])
            self.assertEqual(exe.read_bytes(), b"MZ stary", "a wrong checksum changes nothing")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["TrybunAI.exe"])
            self.assertTrue(update.install(update.check("1.0.11", opener=Opener(good)), exe, opener=Opener(good))["ok"])
            self.assertEqual(exe.read_bytes(), new_exe)
            self.assertEqual(Path(tmp, "TrybunAI.old.exe").read_bytes(), b"MZ stary")
            update.cleanup(exe)
            self.assertFalse(Path(tmp, "TrybunAI.old.exe").exists())

    def test_verdicts_and_denials_are_read_from_output(self):
        self.assertEqual(core.parse_verdict("ok\n**WERDYKT: AKCEPTUJĘ**"), "accept")
        self.assertEqual(core.parse_verdict("WERDYKT: AKCEPTUJĘ\npotem jednak\nWERDYKT: UWAGI"), "remarks")
        self.assertEqual(core.parse_verdict("Werdykt: nie mogę sprawdzić"), "unverified")
        self.assertEqual(core.parse_verdict("wygląda dobrze"), "unverified", "no verdict is never an acceptance")
        claude = {"type": "result", "permission_denials": [
            {"tool_name": "Write", "tool_input": {"file_path": "a.txt"}},
            {"tool_name": "Bash", "tool_input": {"command": "echo y > b.txt"}}]}
        self.assertEqual([v["needs"] for k, v in parse_event("claude", claude)], ["edit", "full"])
        agy = {"event": "step_update", "step_update": {"step_type": "tool", "state": "ERROR", "tool_name": "run_command",
               "tool_info": {"parameters": {"CommandLine": "echo y"}, "error": {"message": "Permission denied for x"}}}}
        self.assertEqual(parse_event("antigravity", agy), [("denied", {"tool": "run_command",
                                                                      "detail": "run_command: echo y", "needs": "full"})])
        agy["step_update"]["tool_info"]["error"]["message"] = "file not found"
        self.assertEqual(parse_event("antigravity", agy), [], "ordinary tool errors are not permission problems")

    def test_model_lists_from_each_cli(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, ".claude.json").write_text(json.dumps({
                "additionalModelOptionsCache": [{"value": "claude-fable-5-1[1m]", "label": "Fable"}],
                "lastModelUsage": {"claude-sonnet-5": {}, "gpt-x": {}}}), encoding="utf-8")
            Path(home, ".codex").mkdir()
            Path(home, ".codex", "models_cache.json").write_text(json.dumps({"models": [
                {"slug": "gpt-reserve", "display_name": "GPT-Reserve", "visibility": "hide", "priority": 0},
                {"slug": "gpt-5.6-terra", "display_name": "GPT-5.6-Terra", "visibility": "list", "priority": 2},
                {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna", "visibility": "list", "priority": 1}]}),
                encoding="utf-8")
            claude = [o["value"] for o in models.claude(home)]
            self.assertEqual(claude, ["sonnet", "opus", "haiku", "claude-fable-5-1[1m]", "claude-sonnet-5"])
            self.assertEqual([o["value"] for o in models.codex(home)], ["gpt-6-luna", "gpt-5.6-terra"],
                             "hidden models are left out, the order follows Codex")
        self.assertEqual(models.claude(tempfile.gettempdir() + "\\brak")[:1], [{"value": "sonnet", "label": "Sonnet (najnowszy)"}])
        out = subprocess.CompletedProcess([], 0, b"Fetching available models...\ngemini-3.8-flash-high\tGemini 3.8 Flash (High)\n", b"")
        with mock.patch.object(models.subprocess, "run", return_value=out):
            self.assertEqual(models.antigravity("agy"), [{"value": "gemini-3.8-flash-high", "label": "Gemini 3.8 Flash (High)"}])
        with mock.patch.object(models.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"", b"sign in")):
            self.assertEqual(models.antigravity("agy"), [])

    def test_limits_from_each_cli(self):
        usage = ("Gemini Models\tWeekly Limit Remaining\t91%\t2026-11-09T19:43:39Z\n"
                 "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-11-09T19:57:02Z\n")
        wins = limits.parse_agy_usage(usage)
        self.assertEqual([(w["label"], w["used"]) for w in wins],
                         [("Modele Gemini, tydzień", 9), ("Modele Claude i GPT, tydzień", 0)])
        with tempfile.TemporaryDirectory() as home:
            log = Path(home, ".codex", "sessions", "2026", "11", "02", "rollout-x.jsonl")
            log.parent.mkdir(parents=True)
            entry = {"timestamp": "2026-11-02T19:11:21.595Z", "payload": {"type": "token_count", "rate_limits": {
                "primary": {"used_percent": 9.0, "window_minutes": 43200, "resets_at": 1796151314},
                "secondary": None, "plan_type": "go"}}}
            log.write_text('{"payload":{}}\n' + json.dumps(entry) + "\n", encoding="utf-8")
            got = limits.codex(home)
        self.assertEqual(got["plan"], "Go")
        self.assertEqual(got["windows"], [{"label": "30 dni", "used": 9, "resets_at": 1796151314}])
        info = {"unifiedWindows": {"five_hour": {"utilization": 0.24, "resetsAt": 1},
                                   "seven_day": {"utilization": 0.28, "resetsAt": 2}}}
        self.assertEqual(parse_event("haiku", {"type": "rate_limit_event", "rate_limit_info": info}),
                         [("limits", info)])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(limits, "_STORE", Path(tmp, "l.json")), \
                mock.patch.object(limits, "_run", lambda cmd, timeout=30: (0, '{"subscriptionType": "pro"}')):
            limits.record_claude(info)
            got = limits.claude("claude")
        self.assertEqual(got["plan"], "Pro")
        self.assertEqual([(w["label"], w["used"]) for w in got["windows"]], [("5 godzin", 24), ("tydzień", 28)])

    def test_claude_sessions_get_fixed_name(self):
        with mock.patch("platform.node", return_value="MOJ PC"):
            self.assertEqual(session_name("Mój projekt&x"), "TrAI-MOJ-PC-Mój-projekt-x")
            self.assertEqual(session_name("app", "haiku"), "TrAI-MOJ-PC-app-haiku")
        cmd = build_command("claude", "c", "read", session="id-1", name="TrAI-a-b")
        self.assertEqual(cmd[cmd.index("--name") + 1], "TrAI-a-b")
        self.assertNotIn("--name", build_command("haiku", "c", "read", prompter=True, name="TrAI-a-b"))
        self.assertNotIn("--name", " ".join(build_command("codex", "c", "read", name="TrAI-a-b")))

    def test_codex_image_flag_cannot_swallow_prompt_marker(self):
        cmd = build_command("codex", "c", "read", images=["a b.png"])
        self.assertEqual(cmd[cmd.index("-i") + 2], "--json")
        self.assertEqual(cmd[-1], "-")

    def test_prompter_output_unfenced(self):
        self.assertEqual(clean_prompter_output("```\nabc\n```"), "abc")
        self.assertEqual(clean_prompter_output("a ```x``` b"), "a ```x``` b")


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        script = self.dir / "fake.py"
        script.write_text(FAKE, encoding="utf-8")
        self.events = []
        self.session = Session(self.dir, self.events.append, binaries={"antigravity": "x", "claude": "x", "codex": "x", "haiku": "x"})
        self.assertEqual(self.session.settings["prompter"], "haiku")
        patcher = mock.patch.object(core, "build_command",
                                    lambda agent, *a, **k: [sys.executable, str(script)])
        patcher.start()
        self.addCleanup(patcher.stop)
        # The fake CLI speaks Antigravity's dialect whichever agent it stands in for.
        dialect = mock.patch.object(core, "parse_event", lambda agent, obj: parse_event("antigravity", obj))
        dialect.start()
        self.addCleanup(dialect.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.session.shutdown)  # runs first: waits for map refreshes

    def wait_idle(self):
        deadline = time.time() + 20
        while self.session._busy and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.session._busy)

    def test_specialists_join_the_chat(self):
        seen = []
        def fake(agent, exe, mode, session=None, model=None, **k):
            seen.append((agent, core.AGENTS[agent]["family"], model))
            return [sys.executable, str(self.dir / "fake.py")]
        arch = {"id": "arch", "name": "Architekt", "family": "claude"}
        bad = [[{**arch, "id": "Arch"}], [{**arch, "id": "codex"}], [arch, arch], [{**arch, "family": "gemini"}]]
        for personas in bad:
            self.assertFalse(self.session.update_settings({"personas": personas})["ok"], personas)
        self.assertNotIn("arch", core.AGENTS, "a rejected list must not stay registered")
        self.assertTrue(self.session.update_settings({
            "personas": [arch], "models": {"arch": "haiku"}, "roles": {"arch": "oceniasz wdrożenia"},
            "colors": {"arch": "#12ab34"}, "everyone": ["claude", "arch"]})["ok"])
        self.assertFalse(self.session.update_settings({"colors": {"arch": "red"}})["ok"])
        self.assertEqual(core.parse_targets("@arch @codex hej", "claude"), (["arch", "codex"], "hej"))
        with mock.patch.object(core, "build_command", fake):
            self.assertTrue(self.session.send("@arch czy to się da wdrożyć?", "codex")["ok"])
            self.wait_idle()
        self.assertEqual(seen, [("arch", "claude", "haiku")])
        prompt = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("@arch", prompt)
        self.assertIn("oceniasz wdrożenia", prompt)
        self.assertEqual(self.session.messages[-1]["agent"], "arch")
        self.assertEqual(self.session.sessions["arch"]["id"], "abc-123", "its own conversation")
        # Reloading the project brings the specialist back; removing hides it but keeps old messages readable.
        again = Session(self.dir, lambda e: None, binaries={"claude": "x"})
        self.assertEqual(again.snapshot()["agents"]["arch"]["label"], "Architekt")
        self.assertTrue(again._binaries.get("arch"))
        self.assertTrue(again.update_settings({"personas": [{**arch, "hidden": True}], "target": "arch"})["ok"])
        self.assertEqual(again.settings["everyone"], ["claude"])
        self.assertEqual(again.settings["target"], "claude")
        self.assertEqual(core.parse_targets("@arch hej", "claude")[0], ["claude"])
        self.assertFalse(again.send("hej", "arch")["ok"])
        self.assertTrue(again.snapshot()["agents"]["arch"]["hidden"])
        again.shutdown()

    def test_turn_saves_reply_and_session(self):
        self.assertTrue(self.session.send("@agy cześć", "claude")["ok"])
        self.wait_idle()
        self.assertEqual(self.session.messages[-1]["text"], "odp zażółć")
        self.assertEqual(self.session.sessions["antigravity"], {"id": "abc-123", "seen": 1})
        saved = json.loads((self.dir / ".trybunai" / "chat.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["messages"][-1]["status"], "ok")
        self.assertTrue((self.dir / ".trybunai" / ".gitignore").exists())

    def test_second_model_receives_first_models_reply_once(self):
        self.session.send("@agy pierwsze", "claude")
        self.wait_idle()
        self.session.send("@claude drugie", "claude")
        self.wait_idle()
        first = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("odp zażółć", first)
        self.session.send("@claude trzecie", "claude")
        self.wait_idle()
        again = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertEqual(again, "trzecie")

    def test_failure_is_reported_with_login_hint(self):
        self.session.send("@agy ZLE", "claude")
        self.wait_idle()
        msg = self.session.messages[-1]
        self.assertEqual(msg["status"], "error")
        self.assertIn("zaloguj", msg["error"])

    def test_stop_kills_process(self):
        self.session.send("@agy ZAWIS", "claude")
        deadline = time.time() + 10
        while "antigravity" not in self.session._procs and time.time() < deadline:
            time.sleep(0.01)
        started = time.time()
        self.session.stop("antigravity")
        self.wait_idle()
        self.assertLess(time.time() - started, 15)
        self.assertEqual(self.session.messages[-1]["status"], "stopped")

    def test_stop_after_process_ended_does_not_kill_next_reply(self):
        def late_stop(*args, **kwargs):  # the process has ended, the agent is still busy
            self.session.stop("antigravity")
            return []

        with mock.patch.object(self.session, "_collect_images", side_effect=late_stop):
            self.session.send("@agy pierwsze", "claude")
            self.wait_idle()
        self.assertEqual(self.session.messages[-1]["status"], "ok")
        self.session.send("@agy drugie", "claude")
        self.wait_idle()
        self.assertEqual(self.session.messages[-1]["status"], "ok")
        self.assertEqual(self.session.messages[-1]["text"], "odp zażółć")

    def test_corrupt_chat_is_kept_aside_and_chat_starts_empty(self):
        folder = self.dir / ".trybunai"
        folder.mkdir(exist_ok=True)
        (folder / "chat.json").write_text("{nie json", encoding="utf-8")
        session = Session(self.dir, self.events.append, binaries={"antigravity": "x"})
        self.addCleanup(session.shutdown)
        self.assertEqual(session.messages, [])
        kept = list(folder.glob("chat-uszkodzony-*.json"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].read_text(encoding="utf-8"), "{nie json")
        self.assertFalse((folder / "chat.json").exists())

    def test_memory_update_is_announced_to_the_window(self):
        with mock.patch.object(self.session, "_update_memory_locked", return_value=None):
            self.session._update_memory()
        kinds = [e["t"] for e in self.events if e["t"].startswith("memory")]
        self.assertEqual(kinds, ["memory_start", "memory_end"])

    def test_pdf_text_is_cut_to_the_limit(self):
        folder = self.dir / ".trybunai" / "attachments"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "a.pdf").write_bytes(b"%PDF-1.4")
        rel = ".trybunai/attachments/a.pdf"
        pages = [mock.Mock(**{"extract_text.return_value": "abcdef"}),
                 mock.Mock(**{"extract_text.return_value": "ghijkl"})]
        with mock.patch.object(core, "PdfReader") as reader:
            reader.return_value.pages = pages
            text = self.session._pdf_text([rel], 8)
            self.assertEqual(self.session._pdf_text([rel], 0), "")
        self.assertEqual(text, f"Treść załącznika {rel} [tekst ucięty do limitu]:\nabcdef\ng")

    def test_second_send_while_busy_refused(self):
        self.session.send("@agy ZAWIS", "claude")
        self.assertFalse(self.session.send("@agy znowu", "claude")["ok"])
        deadline = time.time() + 10
        while "antigravity" not in self.session._procs and time.time() < deadline:
            time.sleep(0.01)
        self.session.stop("antigravity")
        self.wait_idle()

    def test_each_agent_has_its_own_mode(self):
        seen = {}
        def fake(agent, exe, mode, *a, **k):
            seen[agent] = mode
            return [sys.executable, str(self.dir / "fake.py")]
        self.session.update_settings({"modes": {"codex": "edit"}})
        with mock.patch.object(core, "build_command", fake):
            self.session.send("@codex @agy hej", "claude")
            self.wait_idle()
        self.assertEqual(seen, {"codex": "edit", "antigravity": "read"})

    def test_excluded_model_is_skipped_and_saved(self):
        self.session.update_settings({"everyone": ["antigravity"]})
        self.session.send("@wszyscy hej", "claude")
        self.wait_idle()
        self.assertEqual(self.session.messages[0]["targets"], ["antigravity"])
        self.session.load()
        self.assertEqual(self.session.settings["everyone"], ["antigravity"])

    def test_everyone_empty_or_not_installed_is_refused(self):
        self.session.update_settings({"everyone": []})
        self.assertFalse(self.session.send("@wszyscy hej", "claude")["ok"])
        self.assertEqual(self.session.messages, [])
        self.session.update_settings({"everyone": ["claude", "antigravity"]})
        self.session._binaries["claude"] = None
        self.session.send("@wszyscy hej", "codex")
        self.wait_idle()
        self.assertEqual(self.session.messages[0]["targets"], ["antigravity"])

    def debate(self, text, script=None):
        calls = []
        def fake(agent, exe, mode, *a, **k):
            calls.append((agent, mode))
            return [sys.executable, str(script or self.dir / "fake.py")]
        with mock.patch.object(core, "build_command", fake):
            self.assertTrue(self.session.send(text, "claude")["ok"])
            self.wait_idle()
        return calls

    def test_debate_takes_turns_read_only_even_with_full_access(self):
        self.session.update_settings({"modes": {"claude": "full", "codex": "edit"}})
        calls = self.debate("@debata 2 @claude @codex temat")
        self.assertEqual(calls, [("claude", "read"), ("codex", "read")] * 2)
        replies = [m for m in self.session.messages if m["role"] == "assistant"]
        self.assertEqual([m["label"] for m in replies], ["runda 1/2", "runda 1/2", "runda 2/2", "runda 2/2"])
        self.assertFalse(self.session._busy)
        self.assertTrue(any(e["t"] == "debate_end" and "zakończona" in e["text"] for e in self.events))

    def menu_debate(self, plan):
        calls = []
        def fake(agent, exe, mode, *a, **k):
            calls.append((agent, mode))
            return [sys.executable, str(self.dir / "fake.py")]
        with mock.patch.object(core, "build_command", fake):
            result = self.session.start_debate(plan)
            self.wait_idle()
        return result, calls

    def test_menu_debate_order_then_implement_then_review(self):
        self.session.update_settings({"modes": {"claude": "full"}})
        result, calls = self.menu_debate({"topic": "plan gry", "agents": ["codex", "antigravity", "claude"], "rounds": 2,
                                          "implementer": "claude", "review": True, "fix_rounds": 0, "confirm": False})
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [("codex", "read"), ("antigravity", "read"), ("claude", "read")] * 2 +
                         [("claude", "full"), ("codex", "read"), ("antigravity", "read")],
                         "speaking order as chosen, implementer with its own rights, reviewers read-only")
        labels = [m.get("label") for m in self.session.messages if m["role"] == "assistant"]
        self.assertEqual(labels[-3:], ["wdrożenie", "sprawdzenie", "sprawdzenie"])
        self.assertEqual(self.session.messages[0]["implementer"], "claude")
        self.assertEqual([m.get("verdict") for m in self.session.messages[-2:]], ["remarks", "remarks"])
        self.assertTrue(any(e["t"] == "debate_end" and "Zostały uwagi" in e["text"] for e in self.events))

    def test_remarks_get_one_fix_round_then_a_recheck(self):
        self.session.update_settings({"modes": {"claude": "full"}})
        result, calls = self.menu_debate({"topic": "plan", "agents": ["claude", "codex"], "rounds": 1,
                                          "implementer": "claude", "review": True, "fix_rounds": 2, "confirm": False})
        self.assertTrue(result["ok"])
        self.assertEqual(calls[2:], [("claude", "full"), ("codex", "read"), ("claude", "full"), ("codex", "read")])
        replies = [(m["agent"], m.get("label"), m.get("verdict")) for m in self.session.messages if m["role"] == "assistant"]
        self.assertEqual(replies[2:], [("claude", "wdrożenie", None), ("codex", "sprawdzenie", "remarks"),
                                       ("claude", "poprawki 1/2", None), ("codex", "sprawdzenie 2", "accept")],
                         "an acceptance ends the loop before the cap")
        self.assertTrue(any(e["t"] == "debate_end" and "Zaakceptowane" in e["text"] for e in self.events))

    def test_debate_waits_for_the_users_pick_before_implementing(self):
        self.session.update_settings({"modes": {"claude": "full"}})
        result, calls = self.menu_debate({"topic": "plan", "agents": ["claude", "codex"], "rounds": 1,
                                          "implementer": "claude", "review": True, "fix_rounds": 0})
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [("claude", "read"), ("codex", "read"), ("claude", "read")],
                         "the summary is written read-only and nothing is implemented yet")
        summary = self.session.messages[-1]
        self.assertEqual(summary["label"], "podsumowanie")
        self.assertEqual(summary["summary"], "Stanęło na JSON.")
        self.assertEqual(summary["proposals"], ["Zapis do settings.json", "Pole schema (sporne)", "Migracja"])
        self.assertTrue(summary["pending"])
        self.assertFalse(self.session._busy, "everybody is free while the user reads")
        self.assertTrue(any(e["t"] == "debate_end" and "wybierz" in e["text"] for e in self.events))
        self.assertFalse(self.session.choose_proposals(summary["id"], [])["ok"], "nothing picked")
        self.assertFalse(self.session.choose_proposals(summary["id"], [7])["ok"])
        self.assertFalse(self.session.choose_proposals("nie-ma", [0])["ok"])
        calls.clear()
        def fake(agent, exe, mode, *a, **k):
            calls.append((agent, mode))
            return [sys.executable, str(self.dir / "fake.py")]
        with mock.patch.object(core, "build_command", fake):
            self.assertTrue(self.session.choose_proposals(summary["id"], [2, 0], "bez zmian w UI")["ok"])
            self.wait_idle()
        self.assertEqual(calls, [("claude", "full"), ("codex", "read")])
        choice = next(m for m in self.session.messages if m.get("choice"))
        self.assertIn("- Zapis do settings.json\n- Migracja", choice["text"])
        self.assertNotIn("schema", choice["text"])
        self.assertIn("Moje uwagi: bez zmian w UI", choice["text"])
        self.assertEqual((summary["pending"], summary["chosen"]), (False, [0, 2]))
        labels = [m.get("label") for m in self.session.messages if m["role"] == "assistant"]
        self.assertEqual(labels[-2:], ["wdrożenie", "sprawdzenie"])
        self.assertIn("wybrane przez użytkownika", (self.dir / "last_prompt.txt").read_text(encoding="utf-8"))
        self.assertFalse(self.session.choose_proposals(summary["id"], [0])["ok"], "decided only once")
        self.assertTrue(any(e["t"] == "debate_end" and "wdrożył wybrane" in e["text"] for e in self.events))

    def test_debate_summary_can_be_skipped(self):
        self.session.update_settings({"modes": {"claude": "edit"}})
        self.menu_debate({"topic": "plan", "agents": ["claude", "codex"], "rounds": 1, "implementer": "claude"})
        summary = self.session.messages[-1]
        self.assertTrue(self.session.choose_proposals(summary["id"], None)["ok"])
        self.assertEqual((summary["pending"], summary["chosen"]), (False, None))
        self.assertFalse(self.session._busy)
        self.session.load()
        self.assertFalse(self.session.messages[-1]["pending"], "the decision is saved")

    def test_blocked_actions_offer_a_one_time_retry(self):
        def parse(agent, obj):
            events = parse_event("antigravity", obj)
            if obj.get("event") == "result":
                events.append(("denied", {"tool": "Write", "detail": "Write: a.html", "needs": "edit"}))
            return events
        seen = []
        def fake(agent, exe, mode, *a, **k):
            seen.append(mode)
            return [sys.executable, str(self.dir / "fake.py")]
        self.session.update_settings({"roles": {"antigravity": "tester gry"}})
        with mock.patch.object(core, "parse_event", parse), mock.patch.object(core, "build_command", fake):
            self.session.send("@agy zapisz plik", "claude")
            self.wait_idle()
            self.assertIn("Twoja stała rola w tym zespole (ustawił ją użytkownik): tester gry",
                          (self.dir / "last_prompt.txt").read_text(encoding="utf-8"))
            msg = self.session.messages[-1]
            self.assertEqual((msg["needs"], msg["denied"][0]["tool"]), ("edit", "Write"))
            self.assertTrue(self.session.retry_with("antigravity", "edit")["ok"])
            self.wait_idle()
        self.assertEqual(seen, ["read", "edit"], "the retry runs once with the granted mode")
        self.assertEqual(self.session.settings["modes"].get("antigravity", "read"), "read", "lasting rights unchanged")
        self.assertEqual(self.session.messages[-2]["grant"], "edit")
        self.assertFalse(self.session.retry_with("antigravity", "root")["ok"])
        self.assertFalse(self.session.update_settings({"roles": {"antigravity": "x" * 1001}})["ok"])

    def test_menu_debate_refuses_read_only_implementer_and_warns_without_one(self):
        result, calls = self.menu_debate({"topic": "x", "agents": ["claude", "codex"], "implementer": "codex"})
        self.assertFalse(result["ok"])
        self.assertIn("Tylko odczyt", result["error"])
        self.assertEqual(calls, [])
        result, _ = self.menu_debate({"topic": "wdróż poprawki", "agents": ["claude", "codex"], "rounds": 1})
        self.assertTrue(result["ok"])
        self.assertIn("tylko do odczytu", result["warn"])

    def test_fresh_session_starts_from_memory_and_last_exchange(self):
        self.session.send("@agy pierwsze", "claude")
        self.wait_idle()
        self.assertTrue(self.session.fresh_session("antigravity")["ok"])
        self.wait_idle()
        summary = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("pierwsze", summary, "the summarizer reads the chat")
        self.assertEqual(self.session.read_memory().strip(), "odp zażółć")
        self.assertEqual(self.session.sessions["antigravity"], {"seen": 0})
        self.assertTrue(any(e["t"] == "fresh" and e["agents"] == ["antigravity"] for e in self.events))
        self.session.send("@agy drugie", "claude")
        self.wait_idle()
        # Antigravity sends the prompt as one JSON line, so the newlines are escaped inside it.
        prompt = json.loads((self.dir / "last_prompt.txt").read_text(encoding="utf-8"))["message"]["content"]
        self.assertIn("<pamiec_projektu>\nodp zażółć", prompt)
        self.assertIn("pierwsze", prompt, "the last exchange is replayed, own reply included")
        self.session.new_chat()
        self.session.send("@agy po nowej rozmowie", "claude")
        self.wait_idle()
        self.assertIn("pamiec_projektu", (self.dir / "last_prompt.txt").read_text(encoding="utf-8"),
                      "the memory outlives a new chat")

    def test_save_state_keeps_sessions_and_new_chat_saves_first(self):
        self.session.send("@agy ustalamy coś", "claude")
        self.wait_idle()
        self.session.write_memory("## Nie ruszać\n- misje mają jedną niewiadomą")
        result = self.session.save_state()
        self.assertTrue(result["ok"])
        prompt = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("misje mają jedną niewiadomą", prompt, "the old memory, mines included, is the base")
        self.assertIn("Nie ruszać", prompt)
        self.assertEqual(result["memory"].strip(), "odp zażółć")
        self.assertEqual(self.session.sessions["antigravity"]["id"], "abc-123", "saving state resets nothing")
        self.session.write_memory("")
        self.session._binaries["haiku"] = None
        result = self.session.new_chat()
        self.assertTrue(result["ok"], "a failed save never blocks a new chat")
        self.assertIn("Nie udało się", result["warn"])
        self.assertEqual(self.session.messages, [])
        self.session._binaries["haiku"] = "x"
        self.session.send("@agy hej", "claude")
        self.wait_idle()
        self.assertTrue(self.session.new_chat()["ok"])
        self.assertEqual(self.session.read_memory().strip(), "odp zażółć", "a new chat saves the state first")

    def big_context(self):
        def parse(agent, obj):
            events = parse_event("antigravity", obj)
            if obj.get("event") == "result":
                events.append(("usage", {"call": "c", "model": None, "context": core.CONTEXT_WARN + 1}))
            return events
        return mock.patch.object(core, "parse_event", parse)

    def test_every_run_is_written_to_token_statistics(self):
        def parse(agent, obj):
            events = parse_event("antigravity", obj)
            if obj.get("event") == "result":
                events.append(("tokens", {"call": "c", "input": 120, "cached": 800, "output": 30}))
            return events
        with mock.patch.object(core, "parse_event", parse):
            self.session.send("@agy hej", "claude")
            self.wait_idle()
            rows = stats.read(self.dir / core.STATE_DIR)
            self.session.new_chat()  # the memory update is a second run
        self.assertEqual([r["kind"] for r in stats.read(self.dir / core.STATE_DIR)], ["czat", "pamięć"],
                         "statistics outlive a new chat")
        self.assertEqual([(r["agent"], r["kind"], r["input"], r["cached"], r["output"]) for r in rows],
                         [("antigravity", "czat", 120, 800, 30)])
        totals = self.session.token_stats("24h")["totals"]
        self.assertEqual((totals["antigravity"]["output"], totals["haiku"]["output"]), (30, 30),
                         "the memory run counts for its engine")

    def test_oversized_session_is_replaced_automatically(self):
        with self.big_context():
            self.session.send("@agy duża sesja", "claude")
            self.wait_idle()
        self.assertEqual(self.session.read_memory().strip(), "odp zażółć")
        self.assertNotIn("id", self.session.sessions["antigravity"])
        self.assertEqual(self.session.messages[-1]["usage"]["context"], core.CONTEXT_WARN + 1)

    def test_auto_refresh_can_be_off_and_keeps_session_when_memory_fails(self):
        self.session.update_settings({"auto_fresh": False})
        with self.big_context():
            self.session.send("@agy duża sesja", "claude")
            self.wait_idle()
        self.assertEqual(self.session.sessions["antigravity"]["id"], "abc-123")
        self.session.update_settings({"auto_fresh": True})
        self.session._binaries["haiku"] = None  # the summarizer cannot run
        with self.big_context():
            self.session.send("@agy znowu", "claude")
            self.wait_idle()
        self.assertEqual(self.session.sessions["antigravity"]["id"], "abc-123", "no memory, so no automatic reset")
        self.assertTrue(any(e["t"] == "fresh" and "Nie udało się" in e["text"] for e in self.events))
        self.assertFalse(self.session.update_settings({"auto_fresh": "tak"})["ok"])

    def test_debater_sees_previous_speaker_once(self):
        self.debate("@debata 1 @claude @codex temat-xyz")
        prompt = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertEqual(prompt.count("odp zażółć"), 1, "Codex reads Claude's reply from this round")
        self.assertIn("temat-xyz", prompt)

    def test_debate_error_stops_remaining_turns(self):
        script = self.dir / "broken.py"
        script.write_text("import sys; sys.stdin.read(); print('boom', file=sys.stderr); sys.exit(1)", encoding="utf-8")
        calls = self.debate("@debata 3 @claude @codex temat", script)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(e["t"] == "debate_end" and "błąd" in e["text"] for e in self.events))

    def test_stop_ends_whole_debate_and_clears_state(self):
        script = self.dir / "slow.py"
        script.write_text("import sys,time; sys.stdin.read(); time.sleep(60)", encoding="utf-8")
        with mock.patch.object(core, "build_command", lambda *a, **k: [sys.executable, str(script)]):
            self.session.send("@debata 3 @claude @codex temat", "claude")
            deadline = time.time() + 10
            while "claude" not in self.session._procs and time.time() < deadline:
                time.sleep(0.01)
            self.assertFalse(self.session.send("@agy hej", "claude")["ok"], "nothing interleaves")
            self.session.stop("claude")
            self.wait_idle()
        self.assertEqual(len([m for m in self.session.messages if m["role"] == "assistant"]), 1)
        self.assertFalse(self.session._stop_requested)
        self.assertTrue(self.session.send("@agy hej", "claude")["ok"], "usable again afterwards")
        self.wait_idle()

    def test_old_single_mode_file_is_migrated(self):
        (self.dir / ".trybunai").mkdir(exist_ok=True)
        (self.dir / ".trybunai" / "chat.json").write_text('{"settings": {"mode": "edit"}}', encoding="utf-8")
        self.session.load()
        self.assertEqual(self.session.settings["modes"]["claude"], "edit")

    def test_image_created_by_a_turn_is_attached_to_reply(self):
        script = self.dir / "paint.py"
        script.write_text(FAKE + "\nopen('nowy.png','wb').write(b'x')\n", encoding="utf-8")
        (self.dir / "stary.png").write_bytes(b"old")
        with mock.patch.object(core, "build_command", lambda *a, **k: [sys.executable, str(script)]):
            self.session.send("@agy rysuj", "claude")
            self.wait_idle()
        self.assertEqual(self.session.messages[-1]["images"], ["nowy.png"])

    def test_file_api_stays_inside_project(self):
        outside = Path(tempfile.gettempdir()) / "trybun-outside.png"
        outside.write_bytes(b"secret")
        self.addCleanup(outside.unlink)
        self.assertIsNone(self.session.image_data(str(outside)))
        self.assertIsNone(self.session.image_data("../trybun-outside.png"))
        (self.dir / "note.txt").write_text("x", encoding="utf-8")
        self.assertIsNone(self.session.image_data("note.txt"))

    def test_attachment_reaches_prompt_and_rejects_foreign_paths(self):
        attached = self.session.attach_bytes("zdjęcie 1.png", "eA==")
        self.assertTrue(attached["ok"])
        self.assertFalse(self.session.send("@agy hej", "claude", ["fake.py"])["ok"])
        self.session.send("@agy hej", "claude", [attached["path"]])
        self.wait_idle()
        prompt = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn(attached["path"], prompt)

    def test_new_chat_archives(self):
        self.session.send("@agy cześć", "claude")
        self.wait_idle()
        self.assertTrue(self.session.new_chat()["ok"])
        self.assertEqual(self.session.messages, [])
        self.assertTrue(list((self.dir / ".trybunai").glob("chat-*.json")))


    def test_map_hint_for_fresh_session_and_changes_for_live_one(self):
        self.session.send("@claude hej", "claude")
        self.wait_idle()
        first = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("Mapa projektu: .trybunai/mapa/INDEX.md", first)
        self.assertIn("[[fake]]", (self.dir / ".trybunai" / "mapa" / "INDEX.md").read_text(encoding="utf-8"))
        self.session.update_settings({"modes": {"codex": "edit"}})
        self.session.send("@codex popraw. Reszta opisu.", "claude")
        self.wait_idle()
        log = core.mapa.read_log(self.dir)
        self.assertEqual(len(log), 1)
        self.assertIn("[Codex] odp zażółć | pliki: last_prompt.txt", log[0])
        self.session.send("@claude dalej", "claude")
        self.wait_idle()
        live = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("Od twojej ostatniej tury inne modele zmieniły pliki", live)
        self.assertIn("[Codex] odp zażółć", live)
        self.assertNotIn("INDEX.md", live)
        self.session.send("@claude znowu", "claude")
        self.wait_idle()
        self.assertEqual((self.dir / "last_prompt.txt").read_text(encoding="utf-8"), "znowu")
        self.session.update_settings({"map": False})
        self.session.new_chat(save_state=False)
        self.session.send("@claude bez mapy", "claude")
        self.wait_idle()
        self.assertNotIn("Mapa projektu", (self.dir / "last_prompt.txt").read_text(encoding="utf-8"))
        self.assertFalse(self.session.update_settings({"map_exclude": ["../x"]})["ok"])


class Installer(unittest.TestCase):
    """The real flow with installers and windows replaced: nothing is installed here."""

    def scenario(self, present, logged_in):
        present, logged_in = set(present), set(logged_in)
        calls = []

        def run(cmd):
            calls.append(("run", cmd))
            target = {"Anthropic.ClaudeCode": "claude", "OpenAI.Codex": "codex",
                      "irm https://antigravity.google/cli/install.ps1 | iex": "agy"}.get(cmd[-1])
            if target:
                present.add(target)
            return bool(target), "ok"

        def window(cmd, done):
            calls.append(("window", cmd))
            logged_in.add(cmd[0])

        with mock.patch.object(setup, "find", lambda n: n if n in present else None), \
                mock.patch.object(setup, "is_logged_in", lambda t, e: t in logged_in), \
                mock.patch.object(setup, "refresh_path", lambda: None):
            log = []
            ready = setup.run_setup(log.append, run, window)
        return ready, calls, log

    def test_clean_laptop_installs_all_then_logs_in_one_by_one(self):
        ready, calls, _ = self.scenario([], [])
        self.assertTrue(ready)
        kinds = [c[0] for c in calls]
        self.assertEqual(kinds, ["run"] * 3 + ["window"] * 3, "all installs come before any login")
        self.assertEqual(calls[2][1][0], "powershell", "Antigravity uses Google's own installer")
        self.assertEqual([c[1] for c in calls[3:]], [["claude", "auth", "login"], ["codex", "login"], ["agy"]])

    def test_ready_machine_does_nothing(self):
        all_tools = ["claude", "codex", "agy"]
        ready, calls, _ = self.scenario(all_tools, all_tools)
        self.assertTrue(ready)
        self.assertEqual(calls, [])

    def test_only_missing_login_opens_window(self):
        ready, calls, _ = self.scenario(["claude", "codex", "agy"], ["claude", "agy"])
        self.assertTrue(ready)
        self.assertEqual(calls, [("window", ["codex", "login"])])

    def test_failed_install_is_reported_not_hidden(self):
        with mock.patch.object(setup, "find", lambda n: None), mock.patch.object(setup, "refresh_path", lambda: None):
            log = []
            ready = setup.run_setup(log.append, lambda cmd: (False, "brak sieci"), lambda cmd, done: self.fail("window"))
        self.assertFalse(ready)
        self.assertTrue(any("brak sieci" in line for line in log))

    def test_window_closed_without_login_is_not_ready(self):
        with mock.patch.object(setup, "find", lambda n: n), mock.patch.object(setup, "is_logged_in", lambda t, e: False):
            log = []
            self.assertFalse(setup.run_setup(log.append, lambda cmd: (True, ""), lambda cmd, done: None))
        self.assertTrue(any("nieukończone" in line for line in log))

    def test_login_window_closes_itself_once_logged_in(self):
        # A console that would otherwise wait a minute, like a CLI sitting in its chat after login.
        cmd = ["cmd.exe", "/c", "ping -n 60 127.0.0.1 >nul"]
        checks = []
        started = time.time()
        setup._open_login_window(cmd, lambda: checks.append(1) or len(checks) >= 2, poll=0.3)
        self.assertLess(time.time() - started, 15)
        self.assertEqual(len(checks), 2)

    def test_real_status_and_path_refresh_do_not_lose_path(self):
        before = os.environ["PATH"]
        self.addCleanup(os.environ.__setitem__, "PATH", before)
        setup.refresh_path()
        self.assertTrue(os.environ["PATH"].endswith(before))


class ProjectMap(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "pkg").mkdir()
        (self.dir / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (self.dir / "pkg" / "baza.py").write_text(
            '"""Połączenie z bazą."""\n'
            'HOST = "10.0.0.5"\n'
            'def polacz(host="192.168.1.10", port=22, haslo="tajne123", *, timeout=5):\n    return 1\n'
            'def _ukryta():\n    pass\n'
            'class Klient:\n    def wyslij(self, dane): pass\n    def _wew(self): pass\n',
            encoding="utf-8")
        (self.dir / "pkg" / "zakladka.py").write_text(
            "from . import baza\nfrom .baza import Klient\nimport json\n"
            + "".join(f"def f{i}(): pass\n" for i in range(45)), encoding="utf-8")
        (self.dir / "main.py").write_text("import pkg.zakladka\n", encoding="utf-8")
        (self.dir / "ui").mkdir()
        (self.dir / "ui" / "app.js").write_text("x", encoding="utf-8")
        (self.dir / "obiekty").mkdir()
        (self.dir / "obiekty" / "klient_kowalski.py").write_text("def x(): pass\n", encoding="utf-8")
        (self.dir / "node_modules").mkdir()
        (self.dir / "node_modules" / "lib.js").write_text("x", encoding="utf-8")
        self.folder = mapa.map_dir(self.dir)

    def generate(self, **kwargs):
        return mapa.generate(self.dir, core._SKIP_DIRS, **kwargs)

    def test_notes_links_signatures_and_secrets(self):
        stats = self.generate()
        self.assertEqual(stats["modules"], 4)
        index = (self.folder / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("[[pkg.baza]] — Połączenie z bazą.", index)
        self.assertIn("`ui/app.js`", index)
        self.assertNotIn("kowalski", index, "excluded data folder")
        self.assertNotIn("lib.js", index)
        self.assertFalse((self.folder / "obiekty.klient_kowalski.md").exists())
        baza = (self.folder / "pkg.baza.md").read_text(encoding="utf-8")
        self.assertIn("def polacz(host=…, port=22, haslo=…, *, timeout=5)", baza)
        self.assertIn("def polacz(host=…, port=22, haslo=…, *, timeout=5)  # L3", baza)
        self.assertIn("class Klient  # L7\n    def wyslij(self, dane)  # L8", baza)
        self.assertNotIn("## Mapa pliku", baza, "a small file shows only the public part")
        for leak in ("192.168", "10.0.0.5", "tajne123", "_ukryta", "_wew"):
            self.assertNotIn(leak, baza)
        self.assertIn("Używany przez: [[pkg.zakladka]]", baza)
        tab = (self.folder / "pkg.zakladka.md").read_text(encoding="utf-8")
        self.assertIn("Zależy od: [[pkg.baza]]", tab)
        self.assertIn("Używany przez: [[main]]", tab)
        self.assertIn("(+5 więcej)", tab)
        self.assertNotIn("json", tab)

    def test_manual_section_survives_and_refresh_is_incremental(self):
        self.generate()
        note = self.folder / "pkg.baza.md"
        text = note.read_text(encoding="utf-8").replace(
            "<!-- reczne -->\n", "<!-- reczne -->\nUwaga: nie zmieniać portu.\n")
        note.write_text(text, encoding="utf-8")
        self.assertEqual(self.generate()["parsed"], 0, "nothing changed, nothing parsed")
        source = self.dir / "pkg" / "baza.py"
        source.write_text(source.read_text(encoding="utf-8") + "def nowa(): pass\n", encoding="utf-8")
        os.utime(source, ns=(time.time_ns(), time.time_ns() + 10**9))
        stats = self.generate()
        self.assertEqual(stats["parsed"], 1)
        text = note.read_text(encoding="utf-8")
        self.assertIn("def nowa()", text)
        self.assertIn("Uwaga: nie zmieniać portu.", text)
        source.unlink()
        self.generate()
        self.assertIn("Plik już nie istnieje", note.read_text(encoding="utf-8"), "hand notes are kept")

    def test_excluded_folders_are_configurable(self):
        self.generate(exclude=["ui", "pkg/zakladka.py"])
        index = (self.folder / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("[[obiekty.klient_kowalski]]", index)
        self.assertNotIn("app.js", index)
        self.assertNotIn("[[pkg.zakladka]]", index)

    def test_big_file_gets_full_outline_with_private_methods(self):
        body = "".join(f"    def _m{i}(self):\n        pass\n" for i in range(200))
        (self.dir / "pkg" / "duza.py").write_text(
            '"""v2.0\n\nZakładka z tabelą obiektów."""\n'
            "def _pomocnik():\n    pass\n"
            "class Tabela:\n    def __init__(self): pass\n    def __repr__(self): pass\n"
            "    def load(self): pass\n" + body + "\n" * 400, encoding="utf-8")
        self.generate()
        note = (self.folder / "pkg.duza.md").read_text(encoding="utf-8")
        outline = note.split("## Mapa pliku", 1)[1]
        self.assertIn("L4 _pomocnik", outline)
        self.assertIn("class Tabela  # L6", outline)
        self.assertIn("    L7 __init__", outline)
        self.assertNotIn("__repr__", outline)
        self.assertIn("    L9 load", outline)
        self.assertIn("    L10 _m0", outline)
        self.assertIn("(+53 więcej)", outline, "1 function + __init__ + load + 200 methods, 150 shown")
        self.assertIn("def load(self)  # L9", note.split("## Mapa pliku")[0])
        index = (self.folder / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("[[pkg.duza]] — Zakładka z tabelą obiektów.", index)

    def test_version_only_docstrings_are_skipped(self):
        self.assertEqual(mapa.clean_doc("modules/tab_table.py", "modules/tab_table.py - v1.1"), "")
        self.assertEqual(mapa.clean_doc("m/tab_batch.py", "modules/tab_batch.py - v4.0 (przepisane od zera)\n"
                                        "Masowe operacje na kamerach."), "Masowe operacje na kamerach.")
        self.assertEqual(mapa.clean_doc("a.py", "v2.0\n====\nOpis."), "Opis.")
        self.assertEqual(mapa.clean_doc("a.py", "Wersja v2.0 dodała eksport."), "Wersja v2.0 dodała eksport.")
        self.assertEqual(mapa.clean_doc("core/history.py", "core/history.py"), "")

    def test_huge_module_without_code_is_data(self):
        (self.dir / "pkg" / "_intro.py").write_text(
            '"""Animacja zakodowana base64."""\nDANE = (\n' + '    "QUJD"\n' * 6000 + ")\n", encoding="utf-8")
        self.generate()
        index = (self.folder / "INDEX.md").read_text(encoding="utf-8")
        self.assertIn("[[pkg._intro]] — Animacja zakodowana base64. (dane, 6004 l.)", index)
        self.assertIn("Plik z danymi", (self.folder / "pkg._intro.md").read_text(encoding="utf-8"))
        self.assertNotIn("dane,", index.split("[[pkg.baza]]")[1].split("\n")[0])

    def test_log_keeps_newest_thirty(self):
        for i in range(35):
            mapa.append_log(self.dir, "Codex", f"Zmiana {i}. Dalszy opis.", [f"plik{i}.py"])
        entries = mapa.read_log(self.dir)
        self.assertEqual(len(entries), 30)
        self.assertIn("[Codex] Zmiana 34. | pliki: plik34.py", entries[-1])
        self.assertIn("Zmiana 5.", entries[0])
        self.assertIsNone(mapa.append_log(self.dir, "Codex", "nic", []))
        long = mapa.first_sentence("**Dodałem** " + "x" * 300)
        self.assertEqual(len(long), 120)

    def test_entries_since_and_prompt_note(self):
        entries = ["2026-11-08 14:00 [Codex] a | pliki: a.py", "2026-11-08 14:01 [Claude] b | pliki: b.py",
                   "2026-11-08 14:02 [Codex] c | pliki: c.py"]
        self.assertEqual(mapa.entries_since(entries, entries[0], skip_label="Claude"), [entries[2]])
        self.assertEqual(mapa.entries_since(entries, "wypadł z dziennika"), entries)
        fresh = mapa.prompt_note(True, entries[:1])
        self.assertIn(".trybunai/mapa/INDEX.md", fresh)
        self.assertIn("- 2026-11-08 14:00 [Codex] a", fresh)
        self.assertNotIn("INDEX.md", mapa.prompt_note(False, entries[:1]))
        self.assertEqual(mapa.prompt_note(False, []), "")
        self.assertTrue(build_turn_prompt([], "claude", "pytanie", project_map=fresh).endswith("pytanie"))

    def test_start_files_never_overwrite(self):
        (self.dir / "CLAUDE.md").write_text("moje", encoding="utf-8")
        result = mapa.create_start_files(self.dir)
        self.assertEqual((self.dir / "CLAUDE.md").read_text(encoding="utf-8"), "moje")
        self.assertEqual(len(result["created"]), 2)
        self.assertIn("REGULY.md", (self.dir / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertTrue(result["rules_missing"])


class Remote(unittest.TestCase):
    SERVER = ("import time\n"
              "print('\\x1b[1A\\x1b[J Connected', flush=True)\n"
              "print('Continue in https://claude.ai/code?environment=env_1', flush=True)\n"
              "time.sleep(60)\n")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.events = []
        self.remote = RemoteControl(self.events.append)
        self.addCleanup(self.remote.stop)

    def wait_for(self, state):
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.remote.status()["state"] == state:
                return self.remote.status()
            time.sleep(0.02)
        self.fail(f"never reached {state}: {self.remote.status()}")

    def start(self, script):
        return self.remote.start([sys.executable, "-c", script], self.dir)

    def test_connects_reports_link_and_stops_cleanly(self):
        self.assertTrue(self.start(self.SERVER)["ok"])
        self.assertEqual(self.wait_for("connected")["url"], "https://claude.ai/code?environment=env_1")
        self.assertTrue(self.remote.active)
        self.remote.stop()
        self.assertIsNone(self.wait_for("off")["error"])
        self.assertFalse(self.remote.active)
        self.assertEqual(self.events[0]["state"], "connecting")
        self.assertEqual(self.events[-1]["state"], "off")

    def test_failure_before_connecting_shows_why(self):
        self.start("import sys; print('You must be logged in'); sys.exit(1)")
        deadline = time.time() + 20
        while self.remote.active and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.remote.status(), {"state": "off", "url": None, "error": "You must be logged in"})

    def test_missing_binary_is_an_error_not_a_crash(self):
        result = self.remote.start([str(self.dir / "brak.exe")], self.dir)
        self.assertFalse(result["ok"])
        self.assertFalse(self.remote.active)

    def test_project_cannot_change_under_a_running_server(self):
        session = Session(self.dir, self.events.append, binaries={"claude": "x"})
        session._remote = self.remote
        self.start(self.SERVER)
        self.wait_for("connected")
        self.assertFalse(session.set_project(self.dir)["ok"])

    def test_command_never_bypasses_permissions_and_sanitizes_name(self):
        cmd = build_remote_command("c", "Mój projekt & calc")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "default")
        self.assertNotIn("&", cmd[cmd.index("--name") + 1])
        self.assertNotIn(" ", cmd[cmd.index("--name") + 1])


if __name__ == "__main__":
    unittest.main()
