"""Knowledge about each CLI: how to invoke it and how to read its JSONL output."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil

AGENTS = {
    "claude": {"label": "Claude", "binary": "claude"},
    "codex": {"label": "Codex", "binary": "codex"},
    # Google's successor to Gemini CLI for personal accounts (free tier with limits).
    "antigravity": {"label": "Antigravity", "binary": "agy",
                    "fallback": os.path.join(os.environ.get("LOCALAPPDATA", ""), "agy", "bin", "agy.exe")},
    # Since June 2026 Gemini CLI only serves API keys, so it is shown only once installed.
    "gemini": {"label": "Gemini", "binary": "gemini", "optional": True},
    # Same CLI as Claude, cheaper and faster model, its own conversation.
    "haiku": {"label": "Haiku", "binary": "claude", "family": "claude", "model": "haiku"},
}
MODES = ("read", "edit", "full")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

# Gemini's npm shim is a .cmd, which goes through cmd.exe. The prompt always
# travels over stdin, and everything else placed on the command line is validated.
_SAFE_ARG = re.compile(r"^[\w.:\-\[\]]+$")


def is_safe_arg(value: str) -> bool:
    return bool(_SAFE_ARG.match(value or ""))


def find_binary(agent_id: str) -> str | None:
    name = AGENTS[agent_id]["binary"]
    for candidate in (f"{name}.exe", f"{name}.cmd", name):
        path = shutil.which(candidate)
        if path:
            return path
    # A fresh install edits PATH in the registry, which a running app does not see.
    fallback = AGENTS[agent_id].get("fallback")
    return fallback if fallback and os.path.isfile(fallback) else None


def _agy_settings(mode, prompter):
    """Antigravity's own default writes files unasked, so every mode gets explicit rules.
    Outside a trusted folder headless agy denies even reads unless they are allowed."""
    if prompter:
        rules = {"deny": ["read_file(*)", "write_file(*)", "command(*)"]}
    elif mode == "edit":
        rules = {"allow": ["read_file(*)", "write_file(*)"], "deny": ["command(*)"]}
    else:
        rules = {"allow": ["read_file(*)"], "deny": ["write_file(*)", "command(*)"]}
    return json.dumps({"permissions": rules})


def stdin_payload(agent_id, prompt):
    """Antigravity reads stdin only as stream-json; the others take plain text."""
    if _family(agent_id) == "antigravity":
        return json.dumps({"event": "user", "message": {"role": "user", "content": prompt}},
                          ensure_ascii=False) + "\n"
    return prompt


def _family(agent_id):
    return AGENTS.get(agent_id, {}).get("family", agent_id)


def build_command(agent_id, exe, mode="read", session=None, model=None, prompter=False, images=(),
                  name=None):
    """Return argv. The prompt is always written to stdin."""
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    model = model or AGENTS.get(agent_id, {}).get("model")
    family = _family(agent_id)
    for value in (session, model):
        if value and not is_safe_arg(value):
            raise ValueError(f"unsafe argument: {value!r}")

    if family == "claude":
        cmd = [exe, "-p", "--output-format", "stream-json", "--verbose",
               "--include-partial-messages"]
        if prompter:
            cmd += ["--tools", "", "--no-session-persistence"]
        elif mode == "full":
            cmd += ["--dangerously-skip-permissions"]
        else:
            # dontAsk: reads work and anything else is denied instead of hanging
            # on an approval prompt nobody can answer in headless mode.
            cmd += ["--permission-mode", "dontAsk" if mode == "read" else "acceptEdits"]
        if session:
            cmd += ["--resume", session]
        if name and not prompter:  # repeated on resume, so older chats get renamed too
            cmd += ["--name", name]
    elif family == "codex":
        cmd = [exe, "exec"]
        if session:
            cmd.append("resume")  # `resume` has no -s flag, so the sandbox goes through -c
        for image in images:
            cmd += ["-i", str(image)]  # -i is greedy: it must be followed by another flag
        cmd += ["--json", "--skip-git-repo-check"]
        if mode == "full" and not prompter:
            cmd += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            sandbox = "workspace-write" if mode == "edit" and not prompter else "read-only"
            # Without an explicit Windows sandbox, headless Codex rejects every
            # shell command with "blocked by policy", even plain reads.
            cmd += ["-c", f'sandbox_mode="{sandbox}"', "-c", 'windows.sandbox="unelevated"']
            if prompter:
                cmd.append("--ephemeral")
    elif family == "gemini":
        cmd = [exe, "-o", "stream-json", "--skip-trust", "-p", ""]
        approval = {"read": "default", "edit": "auto_edit", "full": "yolo"}[mode]
        cmd += ["--approval-mode", "default" if prompter else approval]
        if session:
            cmd += ["--resume", session]
    elif family == "antigravity":
        # agy.exe is a real exe, not a .cmd shim, so the JSON argument does not pass through cmd.exe.
        cmd = [exe, "--input-format", "stream-json", "--output-format", "stream-json"]
        if mode == "full" and not prompter:
            cmd += ["--dangerously-skip-permissions"]
        else:
            cmd += ["--settings", _agy_settings(mode, prompter)]
        if session:
            cmd += ["--conversation", session]
    else:
        raise ValueError(f"unknown agent: {agent_id}")

    if model:
        cmd += ["--model", model]
    if family == "codex":
        if session:
            cmd.append(session)
        cmd.append("-")  # read the prompt from stdin
    return cmd


def session_name(project_name, suffix=""):
    """Fixed sidebar name in the Claude app: TrAI-<pc>-<project>[-suffix]."""
    # The npm shim goes through cmd.exe, so no part may carry shell characters.
    parts = [platform.node() or "pc", project_name] + ([suffix] if suffix else [])
    return "TrAI-" + "-".join(re.sub(r"[^\w.\-]+", "-", p).strip("-") or "x" for p in parts)


def build_remote_command(exe, project_name):
    """Prompts go to the phone for approval: a remote channel never gets the chat's modes."""
    return [exe, "remote-control", "--name", session_name(project_name, "zdalnie"),
            "--permission-mode", "default"]


def _shorten(value, limit=140):
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tool_summary(name, params):
    if isinstance(params, dict):
        params = {str(k).lower(): v for k, v in params.items()}  # Antigravity uses "Path", "CommandLine"
        for key in ("command", "commandline", "file_path", "path", "absolutepath", "pattern", "query",
                    "url", "description"):
            if params.get(key):
                return f"{name}: {_shorten(params[key])}"
    return str(name)


def parse_event(agent_id, obj):
    """Translate one JSON line into (kind, value) tuples.

    Kinds: session, text, break (new assistant message), activity, warn, fatal, limits.
    """
    if not isinstance(obj, dict):
        return []
    return {"claude": _parse_claude, "codex": _parse_codex, "gemini": _parse_gemini,
            "antigravity": _parse_antigravity}[_family(agent_id)](obj)


def _parse_claude(o):
    kind = o.get("type")
    if kind == "system" and o.get("subtype") == "init":
        return [("session", o.get("session_id"))]
    if kind == "rate_limit_event":
        return [("limits", o.get("rate_limit_info"))]
    if o.get("parent_tool_use_id"):
        return []  # subagent chatter stays out of the transcript
    if kind == "stream_event":
        ev = o.get("event") or {}
        if ev.get("type") == "message_start":
            return [("break", None)]
        if ev.get("type") == "content_block_delta":
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta":
                return [("text", delta.get("text", ""))]
    elif kind == "assistant":
        blocks = (o.get("message") or {}).get("content") or []
        return [("activity", _tool_summary(b.get("name"), b.get("input")))
                for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
    elif kind == "result":
        if o.get("is_error"):
            detail = o.get("result") or "; ".join(map(str, o.get("errors") or [])) or o.get("subtype")
            return [("fatal", str(detail))]
    return []


def _parse_codex(o):
    kind = o.get("type")
    if kind == "thread.started":
        return [("session", o.get("thread_id"))]
    if kind == "turn.failed":
        return [("fatal", str((o.get("error") or {}).get("message", "Codex: tura nieudana")))]
    if kind == "error":
        return [("warn", str(o.get("message", "")))]
    item = o.get("item") or {}
    itype = item.get("type")
    if kind == "item.completed" and itype == "agent_message":
        return [("break", None), ("text", item.get("text", ""))]
    if kind == "item.started" and itype == "command_execution":
        return [("activity", f"polecenie: {_shorten(item.get('command', ''))}")]
    if kind == "item.completed" and itype == "file_change":
        paths = [c.get("path", "?") for c in item.get("changes") or [] if isinstance(c, dict)]
        return [("activity", f"pliki: {_shorten(', '.join(paths))}")]
    if kind == "item.started" and itype in ("mcp_tool_call", "web_search"):
        return [("activity", _shorten(item.get("tool") or item.get("query") or itype))]
    return []


def _parse_gemini(o):
    kind = o.get("type")
    if kind == "init":
        return [("session", o.get("session_id"))]
    if kind == "message" and o.get("role") == "assistant":
        return [("text", o.get("content") or "")]
    if kind == "tool_use":
        return [("break", None), ("activity", _tool_summary(o.get("tool_name"), o.get("parameters")))]
    if kind == "error":
        return [("warn", str(o.get("message", "")))]
    if kind == "result" and o.get("status") == "error":
        err = o.get("error") or {}
        return [("fatal", str(err.get("message") if isinstance(err, dict) else err))]
    return []


def _parse_antigravity(o):
    kind = o.get("event")
    if kind == "init":
        return [("session", o.get("conversation_id"))]
    if kind == "result":
        res = o.get("result") or {}
        if res.get("status") != "SUCCESS":
            return [("fatal", str(res.get("error") or res.get("finished_reason") or "Antigravity: tura nieudana"))]
        return []
    step = o.get("step_update") or {}
    if kind != "step_update":
        return []
    if step.get("step_type") == "agent_response" and step.get("text_delta"):
        return [("text", step["text_delta"])]
    if step.get("step_type") == "tool" and step.get("state") == "ACTIVE":
        info = step.get("tool_info") or {}
        return [("break", None), ("activity", _tool_summary(step.get("tool_name"), info.get("parameters")))]
    return []
