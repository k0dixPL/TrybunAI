"""Project map: short notes that lead models to the code instead of making them search it.

<project>/.trybunai/mapa/ holds INDEX.md (one line per file), one note per Python module
(public signatures plus import links in both directions) and ZMIANY.md, a short log of what
the models changed. Links are [[wiki links]], so the folder opens as an Obsidian vault.
Standard library only, no GUI code.
"""
from __future__ import annotations

import ast
import json
import os
import re
import time
from pathlib import Path

MAP_DIR = "mapa"
INDEX = "INDEX.md"
LOG = "ZMIANY.md"
STATE = ".stan.json"
LOG_KEEP = 30
DEFAULT_EXCLUDE = ["obiekty"]
MAX_SIGNATURES = 40
INDEX_TARGET = 150
MAX_FILES = 50_000
MANUAL_START, MANUAL_END = "<!-- reczne -->", "<!-- /reczne -->"
_MANUAL = re.compile(re.escape(MANUAL_START) + r"\n?(.*?)" + re.escape(MANUAL_END), re.S)
# Non-Python files worth one INDEX line; data, images and docs stay out.
LISTED_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".ps1", ".psm1",
                   ".bat", ".cmd", ".sh", ".sql", ".toml", ".yml", ".yaml", ".ini", ".cfg", ".kt", ".java"}
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_SECRET = re.compile(r"(?i)\b(has[lł]o|password|passwd|pwd|token|secret|api[_-]?key)\b\s*[:=]\s*[^\s,;)]+")
FRESH_HINT = ("Mapa projektu: .trybunai/mapa/INDEX.md. Zacznij od niej i notatek modułów, "
              "kod czytaj wybiórczo.")


def scrub(text):
    """Names from the code only: no addresses, e-mails or values that look like secrets."""
    text = _SECRET.sub(lambda m: m.group(1) + "=…", text)
    return _EMAIL.sub("<email>", _IP.sub("<IP>", text))


def map_dir(project):
    return Path(project) / ".trybunai" / MAP_DIR


def is_excluded(rel, exclude):
    """rel is a posix path; an entry matches a folder name anywhere or a path prefix."""
    parts = rel.split("/")
    for entry in exclude:
        entry = entry.strip().strip("/")
        if entry and (entry in parts[:-1] or rel == entry or rel.startswith(entry + "/")):
            return True
    return False


# ---- reading the code ----------------------------------------------------

def _default(node):
    """Defaults may hold addresses or passwords, so only plain numbers and names are shown."""
    if isinstance(node, ast.Constant) and (not isinstance(node.value, (str, bytes)) or not node.value):
        return repr(node.value)
    if isinstance(node, (ast.Name, ast.Attribute)):
        return ast.unparse(node)
    return "…"


def _args(args):
    out = []
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for i, (arg, default) in enumerate(zip(positional, defaults)):
        text = arg.arg + (f": {ast.unparse(arg.annotation)}" if arg.annotation else "")
        if default is not None:
            text += f"={_default(default)}"
        out.append(text)
        if args.posonlyargs and i == len(args.posonlyargs) - 1:
            out.append("/")
    if args.vararg:
        out.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        out.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        out.append(arg.arg + (f"={_default(default)}" if default is not None else ""))
    if args.kwarg:
        out.append("**" + args.kwarg.arg)
    return ", ".join(out)


def _function(node, indent=""):
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return scrub(f"{indent}{prefix} {node.name}({_args(node.args)}){ret}")


def _first_line(node):
    doc = ast.get_docstring(node) or ""
    return scrub(doc.strip().splitlines()[0].strip()) if doc.strip() else ""


def read_module(path):
    """Docstring, public signatures and raw imports of one file; None fields when it does not parse."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    info = {"lines": text.count("\n") + 1, "doc": "", "signatures": [], "imports": [], "error": None}
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        info["error"] = f"błąd składni w linii {exc.lineno}"
        return info
    info["doc"] = _first_line(tree)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            info["signatures"].append(_function(node))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            info["signatures"].append(scrub(f"class {node.name}" + (f"({bases})" if bases else "")))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_"):
                    info["signatures"].append(_function(item, "    "))
    for node in ast.walk(tree):  # imports inside functions count too: lazy imports are common
        if isinstance(node, ast.Import):
            info["imports"].extend([0, a.name, []] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            info["imports"].append([node.level, node.module or "", [a.name for a in node.names]])
    return info


def module_name(rel):
    """'pkg/sub/mod.py' -> 'pkg.sub.mod'; a package's __init__.py is the package itself."""
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__" and len(parts) > 1:
        parts = parts[:-1]
    return ".".join(parts)


def _resolver(names):
    def find(dotted):
        if dotted in names:
            return dotted
        # Code under src/ or another root folder imports without that prefix.
        tails = [n for n in names if n.endswith("." + dotted)]
        return tails[0] if len(tails) == 1 else None
    return find


def resolve_imports(module, is_package, imports, names):
    """Project modules this module imports; standard library and packages are dropped."""
    find, found = _resolver(names), set()
    package = module if is_package else module.rpartition(".")[0]
    for level, base, items in imports:
        if level:
            parts = package.split(".") if package else []
            if level - 1 > len(parts):
                continue
            anchor = ".".join(parts[:len(parts) - (level - 1)])
            base = ".".join(p for p in (anchor, base) if p)
        if not items:  # "import a.b.c": the longest known prefix
            bits = base.split(".")
            candidates = [[".".join(bits[:i])] for i in range(len(bits), 0, -1)]
        else:  # "from a import b": submodule a.b if there is one, else names defined in a
            candidates = [[f"{base}.{item}" if base else item for item in items], [base]]
        for group in candidates:
            hits = {h for h in (c and find(c) for c in group) if h and h != module}
            if hits:
                found |= hits
                break
    return sorted(found)


# ---- writing the notes ---------------------------------------------------

def _manual(text, default=""):
    match = _MANUAL.search(text or "")
    return match.group(1) if match else default


def _manual_block(old_text):
    return f"{MANUAL_START}\n{_manual(old_text)}{MANUAL_END}"


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_if_changed(path, text):
    if _read(path) != text:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def clean_doc(rel, doc):
    """Drop a leading file name ("core/history.py - ...") that only repeats the path."""
    parts = rel.split("/")
    for i in range(len(parts)):
        tail = "/".join(parts[i:])
        if doc.lower().startswith(tail.lower()):
            return doc[len(tail):].lstrip(" -–—:").strip()
    return doc


def _links(names):
    return ", ".join(f"[[{n}]]" for n in names) if names else "—"


def module_note(name, rel, info, depends, used_by, old_text=""):
    lines = [f"# {name}", "", f"Plik: `{rel}` ({info['lines']} linii)"]
    doc = clean_doc(rel, info["doc"])
    if doc:
        lines += ["", doc]
    if info["error"]:
        lines += ["", f"Nie udało się odczytać: {info['error']}."]
    lines += ["", f"Zależy od: {_links(depends)}", f"Używany przez: {_links(used_by)}", ""]
    sigs = info["signatures"]
    if sigs:
        lines += ["## Publiczne", "", "```python", *sigs[:MAX_SIGNATURES], "```"]
        if len(sigs) > MAX_SIGNATURES:
            lines.append(f"(+{len(sigs) - MAX_SIGNATURES} więcej)")
        lines.append("")
    lines += ["## Uwagi (ręczne: przeznaczenie, pułapki; generator ich nie zmienia)", "",
              _manual_block(old_text), ""]
    return "\n".join(lines)


def _size(n):
    return f"{n / 1024:.0f} KB" if n >= 1024 else f"{n} B"


def index_note(project_name, modules, others, old_text=""):
    """modules: [(rel, name, info)], others: [(rel, size)], both sorted by path."""
    head = [f"# Mapa projektu {project_name}", "",
            "Generuje TrybunAI z kodu. Notatki modułów: publiczne sygnatury i powiązania importów. "
            "Mapa prowadzi do kodu, nie zastępuje go.", ""]
    body, folder = [], None

    def heading(rel):
        nonlocal folder
        current = rel.rpartition("/")[0] or "."
        if current != folder:
            folder = current
            body.extend(["", f"## {current}/" if current != "." else "## (główny folder)"])

    def place(entry):  # the main folder first, then folders in order
        folder_name = entry[0].rpartition("/")[0]
        return (folder_name != "", folder_name, entry[0])
    entries = sorted([(rel, "py", name, info) for rel, name, info in modules] +
                     [(rel, "file", None, size) for rel, size in others], key=place)
    short = len(entries) + 20 > INDEX_TARGET  # too long: other files collapse to one line per folder
    grouped = {}
    for rel, kind, name, data in entries:
        if kind == "file" and short:
            grouped.setdefault(rel.rpartition("/")[0] or ".", []).append((rel, data))
            continue
        heading(rel)
        if kind == "py":
            doc = clean_doc(rel, data["doc"])
            note = f" — {doc}" if doc else ""
            body.append(f"- [[{name}]]{note} ({data['lines']} l.)")
        else:
            body.append(f"- `{rel}` ({_size(data)})")
    if grouped:
        body += ["", "## Pozostałe pliki"]
        for where, items in sorted(grouped.items()):
            kinds = sorted({Path(r).suffix.lstrip(".") for r, _ in items})
            total = sum(s for _, s in items)
            body.append(f"- `{where}/` — {len(items)} plików ({', '.join(kinds)}), {_size(total)}")
    tail = ["", "## Uwagi (ręczne)", "", _manual_block(old_text), ""]
    return "\n".join(head + body[1:] + tail)


# ---- generation ------------------------------------------------------------

def _walk(project, skip_dirs, exclude):
    found, seen = {}, 0
    for folder, dirs, files in os.walk(project):
        dirs[:] = sorted(d for d in dirs if d not in skip_dirs and not d.startswith("."))
        base = Path(folder)
        for name in files:
            seen += 1
            if seen > MAX_FILES:
                return found
            path = base / name
            rel = path.relative_to(project).as_posix()
            if is_excluded(rel, exclude):
                continue
            suffix = path.suffix.lower()
            if (suffix == ".py" or suffix in LISTED_SUFFIXES) and name.lower() != "desktop.ini":
                try:
                    stat = path.stat()
                except OSError:
                    continue
                found[rel] = (stat.st_mtime_ns, stat.st_size)
    return found


def _load_state(folder):
    try:
        return json.loads((folder / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def generate(project, skip_dirs=(), exclude=DEFAULT_EXCLUDE):
    """Create or refresh the map. Only changed files are parsed again; only changed notes are written.

    Returns {"modules", "files", "parsed", "written"} counts.
    """
    project = Path(project).resolve()
    folder = map_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    state = _load_state(folder)
    cached = state.get("files", {}) if state.get("exclude") == list(exclude) else {}
    current = _walk(project, set(skip_dirs), exclude)
    files, parsed = {}, 0
    for rel, (mtime, size) in current.items():
        old = cached.get(rel)
        if old and old.get("mtime") == mtime:
            files[rel] = old
            continue
        entry = {"mtime": mtime, "size": size}
        if rel.endswith(".py"):
            try:
                entry["info"] = read_module(project / rel)
            except OSError:
                continue
            parsed += 1
        files[rel] = entry

    modules = {module_name(rel): rel for rel in files if rel.endswith(".py")}
    depends = {}
    for name, rel in modules.items():
        depends[name] = resolve_imports(name, rel.endswith("__init__.py"), files[rel]["info"]["imports"], modules)
    used_by = {name: [] for name in modules}
    for name, deps in depends.items():
        for dep in deps:
            used_by[dep].append(name)

    written = 0
    for name, rel in modules.items():
        path = folder / f"{name}.md"
        note = module_note(name, rel, files[rel]["info"], depends[name], sorted(used_by[name]), _read(path))
        written += _write_if_changed(path, note)
    # A note of a deleted module goes away, unless someone wrote something by hand in it.
    for path in folder.glob("*.md"):
        if path.name in (INDEX, LOG) or path.stem in modules:
            continue
        old = _read(path)
        if _manual(old).strip():
            if "Plik już nie istnieje" not in old:
                path.write_text(old.replace("\n", "\n\n**Plik już nie istnieje.**\n", 1), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)

    index = index_note(project.name,
                       sorted((rel, name, files[rel]["info"]) for name, rel in modules.items()),
                       sorted((rel, e["size"]) for rel, e in files.items() if not rel.endswith(".py")),
                       _read(folder / INDEX))
    written += _write_if_changed(folder / INDEX, index)
    (folder / STATE).write_text(json.dumps({"exclude": list(exclude), "files": files}, ensure_ascii=False),
                                encoding="utf-8")
    return {"modules": len(modules), "files": len(files), "parsed": parsed, "written": written}


# ---- change log ------------------------------------------------------------

def first_sentence(text, limit=120):
    text = re.sub(r"[`*_#>]+", "", text or "").strip()
    line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    sentence = re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0]
    sentence = scrub(sentence)
    return sentence if len(sentence) <= limit else sentence[:limit - 1].rstrip() + "…"


def read_log(project):
    """Entries oldest first."""
    text = _read(map_dir(project) / LOG)
    return [l for l in text.splitlines() if re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d \[", l)]


def append_log(project, label, reply, changed, when=None, keep=LOG_KEEP):
    """One line per turn that changed files; only the newest `keep` entries stay."""
    if not changed:
        return None
    names = sorted(changed)
    shown = ", ".join(names[:8]) + (f" (+{len(names) - 8})" if len(names) > 8 else "")
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(when))
    line = f"{stamp} [{label}] {first_sentence(reply) or '(bez opisu)'} | pliki: {scrub(shown)}"
    entries = (read_log(project) + [line])[-keep:]
    folder = map_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    head = ("# Ostatnie zmiany modeli\n\nProwadzi TrybunAI po każdej turze, w której model zmienił pliki. "
            f"Zostaje {keep} najnowszych wpisów.\n\n")
    (folder / LOG).write_text(head + "\n".join(entries) + "\n", encoding="utf-8")
    return line


def entries_since(entries, last_seen, skip_label=None, limit=10):
    """Entries newer than last_seen (all of them when it rotated out), minus the model's own."""
    if last_seen in entries:
        entries = entries[entries.index(last_seen) + 1:]
    if skip_label:
        entries = [e for e in entries if not e.split("] ", 1)[0].endswith(f"[{skip_label}")]
    return entries[-limit:]


def prompt_note(fresh, entries):
    """What a turn prompt gets about the map: the hint for a fresh session, new changes for both."""
    parts = [FRESH_HINT] if fresh else []
    if entries:
        intro = "Ostatnie zmiany w plikach (dziennik TrybunAI):" if fresh else \
            "Od twojej ostatniej tury inne modele zmieniły pliki (dziennik TrybunAI):"
        parts.append(intro + "\n" + "\n".join(f"- {e}" for e in entries))
    return "\n".join(parts)


# ---- shared start files ----------------------------------------------------

START_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
START_TEXT = ("# Zasady projektu\n\n"
              "- Wspólne zasady dla wszystkich modeli: `REGULY.md` (prowadzi właściciel projektu).\n"
              "- Mapa kodu: `.trybunai/mapa/INDEX.md` (generuje TrybunAI). Zacznij od niej, "
              "kod czytaj wybiórczo.\n")


def create_start_files(project):
    """Create the missing CLAUDE.md / AGENTS.md / GEMINI.md; existing ones are never touched."""
    project = Path(project)
    created, existing = [], []
    for name in START_FILES:
        path = project / name
        if path.exists():
            existing.append(str(path))
        else:
            path.write_text(START_TEXT, encoding="utf-8")
            created.append(str(path))
    return {"ok": True, "created": created, "existing": existing,
            "rules_missing": not (project / "REGULY.md").exists()}
