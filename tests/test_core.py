"""Offline tests. Real CLIs are replaced by a small script speaking each JSONL dialect."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
from trybun import core, limits, mapa, models, setup, update  # noqa: E402
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
print(json.dumps({"type": "init", "session_id": "abc-123"}))
print(json.dumps({"type": "message", "role": "assistant", "content": reply, "delta": True}), flush=True)
print(json.dumps({"type": "result", "status": "success"}))
"""


class Pure(unittest.TestCase):
    def test_mentions_only_at_start(self):
        self.assertEqual(parse_targets("@codex @claude zrób", "gemini"), (["codex", "claude"], "zrób"))
        self.assertEqual(parse_targets("zapytaj @codex o to", "gemini"), (["gemini"], "zapytaj @codex o to"))
        self.assertEqual(parse_targets("@wszyscy hej", "claude", ["claude", "codex", "gemini"])[0],
                         ["claude", "codex", "gemini"])
        self.assertEqual(parse_targets("@nieznany hej", "claude"), (["claude"], "@nieznany hej"))

    def test_context_skips_own_and_failed_messages(self):
        msgs = [
            {"role": "user", "targets": ["claude"], "text": "pytanie"},
            {"role": "assistant", "agent": "claude", "text": "odp claude", "status": "ok"},
            {"role": "assistant", "agent": "codex", "text": "moja", "status": "ok"},
            {"role": "assistant", "agent": "gemini", "text": "zepsute", "status": "error"},
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
        self.assertIn("default", build_command("gemini", "c", "read"))
        for agent in ("claude", "codex", "gemini"):
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
                build_command("gemini", "c", model=bad)
            with self.assertRaises(ValueError):
                build_command("gemini", "c", session=bad)

    def test_parsers(self):
        self.assertEqual(parse_event("claude", {"type": "stream_event", "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}}}), [("text", "a")])
        self.assertEqual(parse_event("claude", {"type": "stream_event", "parent_tool_use_id": "t", "event": {
            "type": "content_block_delta", "delta": {"type": "text_delta", "text": "a"}}}), [])
        self.assertEqual(parse_event("claude", {"type": "result", "is_error": True, "result": "x"}), [("fatal", "x")])
        self.assertEqual(parse_event("codex", {"type": "thread.started", "thread_id": "t"}), [("session", "t")])
        self.assertEqual(parse_event("codex", {"type": "turn.failed", "error": {"message": "m"}}), [("fatal", "m")])
        self.assertEqual(parse_event("gemini", {"type": "result", "status": "error", "error": {"message": "m"}}),
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
        self.assertIn("GEMINI_API_KEY", message)

    def test_everyone_respects_exclusions(self):
        self.assertEqual(parse_targets("@wszyscy hej", "gemini", ["claude", "codex"]), (["claude", "codex"], "hej"))
        self.assertEqual(parse_targets("@gemini hej", "claude", ["claude"]), (["gemini"], "hej"), "direct mention wins")
        self.assertEqual(parse_targets("@wszyscy @gemini hej", "claude", ["codex"])[0], ["codex", "gemini"])
        self.assertEqual(parse_targets("@wszyscy hej", "claude", []), ([], "hej"), "must not fall back to default")

    def test_gemini_joins_everyone_by_default_only_with_key(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}):
            self.assertIn("gemini", core.default_everyone())
        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(core.default_everyone(), ["claude", "codex", "antigravity"])

    def test_debate_parsing(self):
        team = ["claude", "codex"]
        self.assertIsNone(parse_debate("@claude co to @debata", team))
        self.assertIsNone(parse_debate("@debatax 3 temat", team))
        self.assertEqual(parse_debate("@debata 2 @gemini @codex baza czy pliki", team),
                         {"rounds": 2, "agents": ["gemini", "codex"], "topic": "baza czy pliki"})
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

    def test_claude_reports_context_size_and_skips_skills(self):
        self.assertIn("--disable-slash-commands", build_command("claude", "c", "read"))
        event = {"type": "assistant", "message": {"id": "m1", "model": "claude-sonnet-5", "content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "a.html"}}],
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 437000}}}
        self.assertEqual(parse_event("claude", event),
                         [("activity", "Read: a.html"), ("usage", {"call": "m1", "model": "claude-sonnet-5",
                                                                   "context": 438002})])
        result = core._Result()
        session = Session.__new__(Session)
        for kind, value in parse_event("claude", event) + parse_event("claude", event):
            if kind == "usage":
                Session._apply(session, kind, value, result, "r")
        self.assertEqual(result.usage(), {"model": "claude-sonnet-5", "context": 438002, "calls": 1},
                         "one call split over two events counts once")

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
        self.session = Session(self.dir, self.events.append, binaries={"gemini": "x", "claude": "x", "codex": "x", "haiku": "x"})
        self.assertEqual(self.session.settings["prompter"], "haiku")
        patcher = mock.patch.object(core, "build_command",
                                    lambda agent, *a, **k: [sys.executable, str(script)])
        patcher.start()
        self.addCleanup(patcher.stop)
        # The fake CLI speaks Gemini's dialect whichever agent it stands in for.
        dialect = mock.patch.object(core, "parse_event", lambda agent, obj: parse_event("gemini", obj))
        dialect.start()
        self.addCleanup(dialect.stop)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.session.shutdown)  # runs first: waits for map refreshes

    def wait_idle(self):
        deadline = time.time() + 20
        while self.session._busy and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.session._busy)

    def test_turn_saves_reply_and_session(self):
        self.assertTrue(self.session.send("@gemini cześć", "claude")["ok"])
        self.wait_idle()
        self.assertEqual(self.session.messages[-1]["text"], "odp zażółć")
        self.assertEqual(self.session.sessions["gemini"], {"id": "abc-123", "seen": 1})
        saved = json.loads((self.dir / ".trybunai" / "chat.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["messages"][-1]["status"], "ok")
        self.assertTrue((self.dir / ".trybunai" / ".gitignore").exists())

    def test_second_model_receives_first_models_reply_once(self):
        self.session.send("@gemini pierwsze", "claude")
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
        self.session.send("@gemini ZLE", "claude")
        self.wait_idle()
        msg = self.session.messages[-1]
        self.assertEqual(msg["status"], "error")
        self.assertIn("zaloguj", msg["error"])

    def test_stop_kills_process(self):
        self.session.send("@gemini ZAWIS", "claude")
        deadline = time.time() + 10
        while "gemini" not in self.session._procs and time.time() < deadline:
            time.sleep(0.01)
        started = time.time()
        self.session.stop("gemini")
        self.wait_idle()
        self.assertLess(time.time() - started, 15)
        self.assertEqual(self.session.messages[-1]["status"], "stopped")

    def test_second_send_while_busy_refused(self):
        self.session.send("@gemini ZAWIS", "claude")
        self.assertFalse(self.session.send("@gemini znowu", "claude")["ok"])
        deadline = time.time() + 10
        while "gemini" not in self.session._procs and time.time() < deadline:
            time.sleep(0.01)
        self.session.stop("gemini")
        self.wait_idle()

    def test_each_agent_has_its_own_mode(self):
        seen = {}
        def fake(agent, exe, mode, *a, **k):
            seen[agent] = mode
            return [sys.executable, str(self.dir / "fake.py")]
        self.session.update_settings({"modes": {"codex": "edit"}})
        with mock.patch.object(core, "build_command", fake):
            self.session.send("@codex @gemini hej", "claude")
            self.wait_idle()
        self.assertEqual(seen, {"codex": "edit", "gemini": "read"})

    def test_excluded_model_is_skipped_and_saved(self):
        self.session.update_settings({"everyone": ["gemini"]})
        self.session.send("@wszyscy hej", "claude")
        self.wait_idle()
        self.assertEqual(self.session.messages[0]["targets"], ["gemini"])
        self.session.load()
        self.assertEqual(self.session.settings["everyone"], ["gemini"])

    def test_everyone_empty_or_not_installed_is_refused(self):
        self.session.update_settings({"everyone": []})
        self.assertFalse(self.session.send("@wszyscy hej", "claude")["ok"])
        self.assertEqual(self.session.messages, [])
        self.session.update_settings({"everyone": ["claude", "gemini"]})
        self.session._binaries["claude"] = None
        self.session.send("@wszyscy hej", "codex")
        self.wait_idle()
        self.assertEqual(self.session.messages[0]["targets"], ["gemini"])

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
        result, calls = self.menu_debate({"topic": "plan gry", "agents": ["codex", "gemini", "claude"], "rounds": 2,
                                          "implementer": "claude", "review": True, "fix_rounds": 0})
        self.assertTrue(result["ok"])
        self.assertEqual(calls, [("codex", "read"), ("gemini", "read"), ("claude", "read")] * 2 +
                         [("claude", "full"), ("codex", "read"), ("gemini", "read")],
                         "speaking order as chosen, implementer with its own rights, reviewers read-only")
        labels = [m.get("label") for m in self.session.messages if m["role"] == "assistant"]
        self.assertEqual(labels[-3:], ["wdrożenie", "sprawdzenie", "sprawdzenie"])
        self.assertEqual(self.session.messages[0]["implementer"], "claude")
        self.assertEqual([m.get("verdict") for m in self.session.messages[-2:]], ["remarks", "remarks"])
        self.assertTrue(any(e["t"] == "debate_end" and "Zostały uwagi" in e["text"] for e in self.events))

    def test_remarks_get_one_fix_round_then_a_recheck(self):
        self.session.update_settings({"modes": {"claude": "full"}})
        result, calls = self.menu_debate({"topic": "plan", "agents": ["claude", "codex"], "rounds": 1,
                                          "implementer": "claude", "review": True, "fix_rounds": 2})
        self.assertTrue(result["ok"])
        self.assertEqual(calls[2:], [("claude", "full"), ("codex", "read"), ("claude", "full"), ("codex", "read")])
        replies = [(m["agent"], m.get("label"), m.get("verdict")) for m in self.session.messages if m["role"] == "assistant"]
        self.assertEqual(replies[2:], [("claude", "wdrożenie", None), ("codex", "sprawdzenie", "remarks"),
                                       ("claude", "poprawki 1/2", None), ("codex", "sprawdzenie 2", "accept")],
                         "an acceptance ends the loop before the cap")
        self.assertTrue(any(e["t"] == "debate_end" and "Zaakceptowane" in e["text"] for e in self.events))

    def test_blocked_actions_offer_a_one_time_retry(self):
        def parse(agent, obj):
            events = parse_event("gemini", obj)
            if obj.get("type") == "result":
                events.append(("denied", {"tool": "Write", "detail": "Write: a.html", "needs": "edit"}))
            return events
        seen = []
        def fake(agent, exe, mode, *a, **k):
            seen.append(mode)
            return [sys.executable, str(self.dir / "fake.py")]
        self.session.update_settings({"roles": {"gemini": "tester gry"}})
        with mock.patch.object(core, "parse_event", parse), mock.patch.object(core, "build_command", fake):
            self.session.send("@gemini zapisz plik", "claude")
            self.wait_idle()
            self.assertIn("Twoja stała rola w tym zespole (ustawił ją użytkownik): tester gry",
                          (self.dir / "last_prompt.txt").read_text(encoding="utf-8"))
            msg = self.session.messages[-1]
            self.assertEqual((msg["needs"], msg["denied"][0]["tool"]), ("edit", "Write"))
            self.assertTrue(self.session.retry_with("gemini", "edit")["ok"])
            self.wait_idle()
        self.assertEqual(seen, ["read", "edit"], "the retry runs once with the granted mode")
        self.assertEqual(self.session.settings["modes"].get("gemini", "read"), "read", "lasting rights unchanged")
        self.assertEqual(self.session.messages[-2]["grant"], "edit")
        self.assertFalse(self.session.retry_with("gemini", "root")["ok"])
        self.assertFalse(self.session.update_settings({"roles": {"gemini": "x" * 401}})["ok"])

    def test_menu_debate_refuses_read_only_implementer_and_warns_without_one(self):
        result, calls = self.menu_debate({"topic": "x", "agents": ["claude", "codex"], "implementer": "codex"})
        self.assertFalse(result["ok"])
        self.assertIn("Tylko odczyt", result["error"])
        self.assertEqual(calls, [])
        result, _ = self.menu_debate({"topic": "wdróż poprawki", "agents": ["claude", "codex"], "rounds": 1})
        self.assertTrue(result["ok"])
        self.assertIn("tylko do odczytu", result["warn"])

    def test_fresh_session_starts_from_memory_and_last_exchange(self):
        self.session.send("@gemini pierwsze", "claude")
        self.wait_idle()
        self.assertTrue(self.session.fresh_session("gemini")["ok"])
        self.wait_idle()
        summary = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("pierwsze", summary, "the summarizer reads the chat")
        self.assertEqual(self.session.read_memory().strip(), "odp zażółć")
        self.assertEqual(self.session.sessions["gemini"], {"seen": 0})
        self.assertTrue(any(e["t"] == "fresh" and e["agents"] == ["gemini"] for e in self.events))
        self.session.send("@gemini drugie", "claude")
        self.wait_idle()
        prompt = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("<pamiec_projektu>\nodp zażółć", prompt)
        self.assertIn("pierwsze", prompt, "the last exchange is replayed, own reply included")
        self.session.new_chat()
        self.session.send("@gemini po nowej rozmowie", "claude")
        self.wait_idle()
        self.assertIn("pamiec_projektu", (self.dir / "last_prompt.txt").read_text(encoding="utf-8"),
                      "the memory outlives a new chat")

    def test_save_state_keeps_sessions_and_new_chat_saves_first(self):
        self.session.send("@gemini ustalamy coś", "claude")
        self.wait_idle()
        self.session.write_memory("## Nie ruszać\n- misje mają jedną niewiadomą")
        result = self.session.save_state()
        self.assertTrue(result["ok"])
        prompt = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("misje mają jedną niewiadomą", prompt, "the old memory, mines included, is the base")
        self.assertIn("Nie ruszać", prompt)
        self.assertEqual(result["memory"].strip(), "odp zażółć")
        self.assertEqual(self.session.sessions["gemini"]["id"], "abc-123", "saving state resets nothing")
        self.session.write_memory("")
        self.session._binaries["haiku"] = None
        result = self.session.new_chat()
        self.assertTrue(result["ok"], "a failed save never blocks a new chat")
        self.assertIn("Nie udało się", result["warn"])
        self.assertEqual(self.session.messages, [])
        self.session._binaries["haiku"] = "x"
        self.session.send("@gemini hej", "claude")
        self.wait_idle()
        self.assertTrue(self.session.new_chat()["ok"])
        self.assertEqual(self.session.read_memory().strip(), "odp zażółć", "a new chat saves the state first")

    def big_context(self):
        def parse(agent, obj):
            events = parse_event("gemini", obj)
            if obj.get("type") == "result":
                events.append(("usage", {"call": "c", "model": None, "context": core.CONTEXT_WARN + 1}))
            return events
        return mock.patch.object(core, "parse_event", parse)

    def test_oversized_session_is_replaced_automatically(self):
        with self.big_context():
            self.session.send("@gemini duża sesja", "claude")
            self.wait_idle()
        self.assertEqual(self.session.read_memory().strip(), "odp zażółć")
        self.assertNotIn("id", self.session.sessions["gemini"])
        self.assertEqual(self.session.messages[-1]["usage"]["context"], core.CONTEXT_WARN + 1)

    def test_auto_refresh_can_be_off_and_keeps_session_when_memory_fails(self):
        self.session.update_settings({"auto_fresh": False})
        with self.big_context():
            self.session.send("@gemini duża sesja", "claude")
            self.wait_idle()
        self.assertEqual(self.session.sessions["gemini"]["id"], "abc-123")
        self.session.update_settings({"auto_fresh": True})
        self.session._binaries["haiku"] = None  # the summarizer cannot run
        with self.big_context():
            self.session.send("@gemini znowu", "claude")
            self.wait_idle()
        self.assertEqual(self.session.sessions["gemini"]["id"], "abc-123", "no memory, so no automatic reset")
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
            self.assertFalse(self.session.send("@gemini hej", "claude")["ok"], "nothing interleaves")
            self.session.stop("claude")
            self.wait_idle()
        self.assertEqual(len([m for m in self.session.messages if m["role"] == "assistant"]), 1)
        self.assertFalse(self.session._stop_requested)
        self.assertTrue(self.session.send("@gemini hej", "claude")["ok"], "usable again afterwards")
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
            self.session.send("@gemini rysuj", "claude")
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
        self.assertFalse(self.session.send("@gemini hej", "claude", ["fake.py"])["ok"])
        self.session.send("@gemini hej", "claude", [attached["path"]])
        self.wait_idle()
        prompt = (self.dir / "last_prompt.txt").read_text(encoding="utf-8")
        self.assertIn(attached["path"], prompt)

    def test_new_chat_archives(self):
        self.session.send("@gemini cześć", "claude")
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
        # A console that would otherwise wait a minute, like Gemini sitting in its chat after login.
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
        self.assertIn("class Klient\n    def wyslij(self, dane)", baza)
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
