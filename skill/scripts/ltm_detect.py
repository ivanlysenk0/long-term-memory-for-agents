#!/usr/bin/env python3
"""
ltm_detect.py - machine recon before deploying the long-term memory.

Changes nothing. It only looks around and answers five questions:
  1. which OS, which Python, what is missing and how to install it
  2. whether Obsidian is installed and where its vaults are
  3. which projects the user has and where to wire the memory in
  4. whether a long-term memory already exists, even under a different name
  5. whether a new memory would conflict with what is already there

Usage:
    python3 ltm_detect.py            human-readable report
    python3 ltm_detect.py --json     machine-readable report for an agent
    python3 ltm_detect.py --deep     search the whole home directory for a memory

No dependencies, stdlib only.
"""

from __future__ import annotations

__version__ = "1.1.0"

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()

# Имена, под которыми у людей встречается долговременная память агентов.
# Своё имя vault тут не единственное: коллега мог назвать её как угодно.
MEMORY_NAME_HINTS = [
    "long-term-memory", "longterm-memory", "ltm", "memory-vault", "agent-memory",
    "llm-wiki", "llm_wiki", "knowledge-vault", "second-brain", "brain",
    "obsidian-vault", "notes-vault", "memory", "vault", "wiki", "zettelkasten",
]

# Файлы, по которым узнаём тип найденного каталога.
MARKER_FILES = {
    "master-index.md": "karpathy-index",
    "index.md": "index",
    "AGENTS.md": "agents-rules",
    "CLAUDE.md": "claude-rules",
    "GEMINI.md": "gemini-rules",
    "README.md": "readme",
    "log.md": "log",
    "pending-concepts.md": "karpathy-scout",
}

KARPATHY_DIRS = {"knowledge", "sessions", "00-home", "atlas", "Raw", "00-global-home"}

PROJECT_MARKERS = [
    ".git", "package.json", "pyproject.toml", "requirements.txt", "go.mod",
    "Cargo.toml", "pom.xml", "build.gradle", "composer.json", "Gemfile",
    "CMakeLists.txt", "Makefile", "docker-compose.yml", ".venv",
]

SKIP_SCAN = {
    ".cache", ".local", "Library", "AppData", "node_modules", ".npm", ".nvm",
    "snap", ".steam", ".wine", "Applications", ".Trash", "$RECYCLE.BIN",
    ".git", "venv", ".venv", "site-packages", "OrbStack", ".docker",
}


# ------------------------------------------------------------------- система

def detect_os() -> dict:
    sysname = platform.system()
    info = {
        "system": sysname,
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 8),
        "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC", ""),
        "wsl": False,
        "family": "unknown",
        "pkg_manager": None,
    }
    if sysname == "Linux":
        info["family"] = "linux"
        rel = ""
        try:
            rel = Path("/proc/version").read_text(errors="ignore").lower()
        except OSError:
            pass
        # WSL важен: там Windows-пути и Linux-пути живут вместе, и память легко
        # положить на медленный /mnt/c вместо родной ФС.
        info["wsl"] = "microsoft" in rel or "wsl" in rel
        for mgr, probe in (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman"), ("zypper", "zypper")):
            if shutil.which(probe):
                info["pkg_manager"] = mgr
                break
        osrel = Path("/etc/os-release")
        if osrel.is_file():
            m = re.search(r'^PRETTY_NAME="?([^"\n]+)', osrel.read_text(errors="ignore"), re.M)
            if m:
                info["distro"] = m.group(1)
    elif sysname == "Darwin":
        info["family"] = "macos"
        info["distro"] = f"macOS {platform.mac_ver()[0]}"
        info["pkg_manager"] = "brew" if shutil.which("brew") else None
    elif sysname == "Windows":
        info["family"] = "windows"
        info["distro"] = f"Windows {platform.release()}"
        for mgr in ("winget", "choco", "scoop"):
            if shutil.which(mgr):
                info["pkg_manager"] = mgr
                break
    return info


def detect_tools(osinfo: dict) -> dict:
    tools = {}
    for name, cmds in {
        "python3": ["python3", "python", "py"],
        "git": ["git"],
        "obsidian": ["obsidian"],
        "claude": ["claude"],
        "amp": ["amp"],
        "code": ["code"],
    }.items():
        found = next((shutil.which(c) for c in cmds if shutil.which(c)), None)
        tools[name] = found
    return tools


def obsidian_state(osinfo: dict) -> dict:
    """Find the installed Obsidian and the list of its vaults."""
    fam = osinfo["family"]
    app_paths, config = [], None

    if fam == "macos":
        app_paths = [Path("/Applications/Obsidian.app"), HOME / "Applications/Obsidian.app"]
        config = HOME / "Library/Application Support/obsidian/obsidian.json"
    elif fam == "linux":
        app_paths = [
            Path("/usr/bin/obsidian"), Path("/usr/local/bin/obsidian"),
            Path("/opt/Obsidian"), Path("/var/lib/flatpak/app/md.obsidian.Obsidian"),
            HOME / ".local/share/flatpak/app/md.obsidian.Obsidian",
        ]
        app_paths += list(HOME.glob("*.AppImage")) + list((HOME / "Applications").glob("*.AppImage")) \
            if (HOME / "Applications").is_dir() else list(HOME.glob("*.AppImage"))
        config = HOME / ".config/obsidian/obsidian.json"
        flat = HOME / ".var/app/md.obsidian.Obsidian/config/obsidian/obsidian.json"
        if flat.is_file():
            config = flat
    elif fam == "windows":
        local = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData/Local"))
        app_paths = [local / "Obsidian/Obsidian.exe", Path("C:/Program Files/Obsidian/Obsidian.exe")]
        config = Path(os.environ.get("APPDATA", HOME / "AppData/Roaming")) / "obsidian/obsidian.json"

    installed = any(p.exists() for p in app_paths)
    if not installed and shutil.which("obsidian"):
        installed = True

    vaults = []
    if config and config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8", errors="replace"))
            for vid, v in (data.get("vaults") or {}).items():
                p = v.get("path", "")
                vaults.append({"path": p, "exists": Path(p).is_dir(), "open": bool(v.get("open"))})
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "installed": installed,
        "config": str(config) if config else None,
        "config_found": bool(config and config.is_file()),
        "vaults": vaults,
        "install_hint": _obsidian_hint(osinfo),
    }


def _obsidian_hint(osinfo: dict) -> str:
    mgr, fam = osinfo.get("pkg_manager"), osinfo["family"]
    if fam == "linux":
        if mgr == "apt":
            return ("Obsidian is not in apt. Options: flatpak install flathub md.obsidian.Obsidian, "
                    "or the .AppImage from obsidian.md, or snap install obsidian --classic")
        if mgr == "pacman":
            return "sudo pacman -S obsidian"
        if mgr == "dnf":
            return "flatpak install flathub md.obsidian.Obsidian"
        return "flatpak install flathub md.obsidian.Obsidian, or the .AppImage from obsidian.md"
    if fam == "macos":
        return "brew install --cask obsidian" if mgr == "brew" else "download from obsidian.md"
    if fam == "windows":
        if mgr == "winget":
            return "winget install Obsidian.Obsidian"
        if mgr == "choco":
            return "choco install obsidian"
        return "download the installer from obsidian.md"
    return "download from obsidian.md"


# ------------------------------------------------------------------ проекты

def scan_projects(roots: list[Path], max_depth: int = 3) -> list[dict]:
    """Find the user's working projects, so there is somewhere to wire the memory in."""
    found, seen = [], set()

    def walk(d: Path, depth: int):
        if depth > max_depth or d.name in SKIP_SCAN or d.name.startswith("."):
            return
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            return
        names = {e.name for e in entries}
        hits = [m for m in PROJECT_MARKERS if m in names]
        if hits:
            key = str(d.resolve())
            if key not in seen:
                seen.add(key)
                found.append({
                    "path": str(d),
                    "name": d.name,
                    "markers": hits,
                    "has_git": ".git" in names,
                    "has_claude_md": "CLAUDE.md" in names,
                    "has_agents_md": "AGENTS.md" in names,
                })
            return  # внутрь проекта не лезем, подпроекты нас не интересуют
        for e in entries:
            if e.is_dir() and not e.is_symlink():
                walk(e, depth + 1)

    for r in roots:
        if r.is_dir():
            walk(r, 1)
    return sorted(found, key=lambda x: x["path"])


# -------------------------------------------------- существующая память

def score_memory(d: Path) -> dict | None:
    """Score how much a directory looks like an agent long-term memory.

    We count signals, not the name: a memory can be called llm-wiki or second-brain."""
    try:
        entries = list(d.iterdir())
    except (PermissionError, OSError):
        return None
    names = {e.name for e in entries}
    dirs = {e.name for e in entries if e.is_dir()}

    md_count = 0
    for p in d.rglob("*.md"):
        if ".git" in p.parts:
            continue
        md_count += 1
        if md_count > 400:
            break
    if md_count == 0:
        return None

    signals, score = [], 0
    karp = KARPATHY_DIRS & dirs
    if karp:
        score += 3 * len(karp)
        signals.append(f"Karpathy method directories: {', '.join(sorted(karp))}")
    for f, kind in MARKER_FILES.items():
        if f in names:
            score += 3 if kind.startswith("karpathy") else 1
            signals.append(f"file {f}")
    if ".obsidian" in dirs:
        score += 3
        signals.append("Obsidian vault (.obsidian)")
    if any(name_hint in d.name.lower() for name_hint in MEMORY_NAME_HINTS):
        score += 2
        signals.append(f"telling directory name: {d.name}")

    # Признак живой памяти: YAML-шапки и вики-ссылки в файлах.
    fm_hits = link_hits = checked = 0
    for p in list(d.rglob("*.md"))[:60]:
        if ".git" in p.parts:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            continue
        checked += 1
        if head.startswith("---"):
            fm_hits += 1
        if "[[" in head:
            link_hits += 1
    if checked:
        if fm_hits / checked > 0.5:
            score += 4
            signals.append(f"frontmatter in {fm_hits} of {checked} checked files")
        if link_hits / checked > 0.3:
            score += 3
            signals.append(f"wiki-links in {link_hits} of {checked} checked files")

    sessions = d / "sessions"
    has_sessions = sessions.is_dir() or any((c / "sessions").is_dir() for c in entries if c.is_dir())
    if has_sessions:
        score += 3
        signals.append("a sessions directory is present")

    if score < 5:
        return None

    if score >= 14:
        verdict = "almost certainly a long-term memory built with the Karpathy method"
    elif score >= 9:
        verdict = "looks like an agent knowledge base, needs a check by the agent"
    else:
        verdict = "possibly just notes, not an agent memory"

    return {
        "path": str(d),
        "name": d.name,
        "md_files": md_count if md_count <= 400 else "400+",
        "score": score,
        "verdict": verdict,
        "signals": signals,
        "karpathy_dirs": sorted(karp),
        "has_obsidian": ".obsidian" in dirs,
        "has_rules": bool({"AGENTS.md", "CLAUDE.md", "GEMINI.md"} & names),
    }


def find_memories(deep: bool, obsidian: dict) -> list[dict]:
    candidates: list[Path] = []

    # 1. Хранилища, о которых знает сам Obsidian: самый надёжный источник.
    for v in obsidian.get("vaults", []):
        if v.get("exists"):
            candidates.append(Path(v["path"]))

    # 2. Типичные места.
    for sub in ["", "memory", "Documents", "notes", "Notes", "vaults", "obsidian",
                "Documents/Obsidian", "Dropbox", "workspace", "projects", "dev"]:
        base = HOME / sub if sub else HOME
        if not base.is_dir():
            continue
        try:
            for e in base.iterdir():
                if e.is_dir() and not e.name.startswith("."):
                    if any(h in e.name.lower() for h in MEMORY_NAME_HINTS):
                        candidates.append(e)
                    elif (e / ".obsidian").is_dir() or (e / "00-global-home").is_dir():
                        candidates.append(e)
        except (PermissionError, OSError):
            continue

    # 3. Глубокий поиск по .obsidian, только по требованию: он медленный.
    if deep:
        for marker in HOME.rglob(".obsidian"):
            if any(s in marker.parts for s in SKIP_SCAN):
                continue
            candidates.append(marker.parent)

    results, seen = [], set()
    for c in candidates:
        try:
            key = str(c.resolve())
        except OSError:
            continue
        if key in seen or not c.is_dir():
            continue
        seen.add(key)
        r = score_memory(c)
        if r:
            results.append(r)
    return sorted(results, key=lambda x: -x["score"])


def assess_conflicts(memories: list[dict], target: Path) -> list[dict]:
    """Work out whether a new memory would get in the way of what is already installed."""
    out = []
    for m in memories:
        mp = Path(m["path"])
        rel = None
        try:
            if mp.resolve() == target.resolve():
                rel = "same"
            elif target.resolve().is_relative_to(mp.resolve()):
                rel = "target_inside"
            elif mp.resolve().is_relative_to(target.resolve()):
                rel = "existing_inside"
        except (OSError, ValueError):
            pass

        if rel == "same":
            out.append({"path": m["path"], "level": "blocker",
                        "issue": "the new memory would land exactly on top of the existing one",
                        "action": "do not install here: either adopt the existing one, or pick another path"})
        elif rel in ("target_inside", "existing_inside"):
            out.append({"path": m["path"], "level": "blocker",
                        "issue": "the directories are nested, Obsidian and the doctor would treat two graphs as one",
                        "action": "pick a path outside the existing memory"})
        elif m["score"] >= 14:
            out.append({"path": m["path"], "level": "warning",
                        "issue": "this is already a working agent memory, a second one creates two sources of truth",
                        "action": "ask the owner: adopt and extend the existing one, or run both in parallel on purpose"})
        elif m["has_rules"]:
            out.append({"path": m["path"], "level": "warning",
                        "issue": "it has its own AGENTS.md / CLAUDE.md, the agent may read foreign rules",
                        "action": "review the rule files and do not duplicate contradictory instructions"})
    return out


# Канон метода Карпати.
# "LTM Vault - QA Team Presentation (Karpathy method)", источники: разборы llm-wiki.
# Разделение на обязательное и вариативное здесь принципиально: агент не имеет права
# требовать от пользователя переделки того, что метод оставляет на усмотрение.
CANON = {
    "mandatory": {
        "raw_layer": {
            "what": "immutable source layer, the LLM only reads it",
            "detect": ["Raw", "raw", "sources", "Sources", "Clippings", "inbox", "Inbox"],
        },
        "wiki_layer": {
            "what": "knowledge layer, markdown concepts, maintained by the LLM",
            "detect": ["knowledge", "wiki", "notes", "concepts", "atlas", "pages"],
        },
        "schema_file": {
            "what": "rules file in the root: CLAUDE.md or AGENTS.md",
            "detect_files": ["CLAUDE.md", "AGENTS.md", "GEMINI.md"],
        },
        "index": {
            "what": "index.md, the wiki map, updated on every Ingest",
            "detect_files": ["index.md", "master-index.md", "README.md", "home.md", "MOC.md"],
        },
        "log": {
            "what": "log.md, the operations journal, append-only",
            "detect_files": ["log.md", "CHANGELOG.md", "journal.md"],
        },
    },
    "variable": [
        "the exact folder and file names",
        "how knowledge/ is split into subcategories",
        "whether sessions/ exists and its format",
        "whether 00-home/ exists as a separate navigation layer",
        "the set of frontmatter fields",
        "the editor of choice: Obsidian, VS Code, Antigravity",
        "the agent of choice: Claude Code, AMP, Codex, OpenCode",
        "how Ingest is automated: one source at a time or in batches",
        "search at scale: index.md, qmd, hybrid or vector",
    ],
    "forbidden": [
        "a human edits files in the wiki layer by hand",
        "the LLM writes or changes files in Raw",
        "one-off RAG without writing the result back into the wiki",
        "unrelated topics kept in one vault",
        "rewriting or deleting lines in log.md",
        "facts in the wiki with no link to a source",
    ],
}

# Референсная раскладка: одна из допустимых реализаций канона, а не сам канон.
REFERENCE_LAYOUT = {
    "root_dirs": ["00-global-home", "scripts"],
    "root_files": ["AGENTS.md", "CLAUDE.md", "README.md"],
    "project_dirs": ["00-home", "atlas", "knowledge", "sessions", "Raw", "scripts", "tasks"],
    "project_files": ["log.md"],
    "home_files": ["index.md", "current-priorities.md", "hot.md", "pending-concepts.md"],
    "knowledge_cats": ["decisions", "patterns", "debugging", "integrations", "analyses", "research"],
    "frontmatter": ["title", "date", "project", "agent", "type", "tags", "status"],
}


def canon_audit(vault: Path) -> dict:
    """Check someone else's structure against the CANON, not against one implementation."""
    try:
        top = list(vault.iterdir())
    except (PermissionError, OSError):
        return {"error": "no access to the directory"}

    all_dirs = {d.name for d in vault.rglob("*") if d.is_dir() and ".git" not in d.parts}
    all_files = {f.name for f in vault.rglob("*.md") if ".git" not in f.parts}
    root_files = {f.name for f in top if f.is_file()}

    result = {"present": [], "missing": [], "notes": []}
    for key, spec in CANON["mandatory"].items():
        found = None
        if "detect" in spec:
            hit = sorted(set(spec["detect"]) & all_dirs)
            if hit:
                found = f"directories: {', '.join(hit)}"
        if not found and "detect_files" in spec:
            pool = root_files if key == "schema_file" else all_files
            hit = sorted(set(spec["detect_files"]) & pool)
            if hit:
                found = f"files: {', '.join(hit)}"
        if found:
            result["present"].append({"element": key, "what": spec["what"], "found": found})
        else:
            result["missing"].append({"element": key, "what": spec["what"],
                                      "detect": spec.get("detect") or spec.get("detect_files")})

    # Запрещённое, что видно машинно. Остальное проверяет агент чтением правил.
    if not (set(CANON["mandatory"]["raw_layer"]["detect"]) & all_dirs):
        result["notes"].append(
            "no Raw layer found: it is unclear where the facts come from and what backs the links")

    md_total = len([f for f in vault.rglob("*.md") if ".git" not in f.parts])
    topics = sorted(d.name for d in top if d.is_dir() and not d.name.startswith(".")
                    and d.name not in ("scripts", "Clippings", "assets", "attachments"))
    if len(topics) > 12:
        result["notes"].append(
            f"{len(topics)} top-level directories: check the rule 'one vault, one topic'")
    result["md_files"] = md_total
    result["top_level"] = topics
    return result


def layout_diff(vault: Path) -> dict:
    """Compare against the reference layout. These are NOT violations, only differences."""
    try:
        top = list(vault.iterdir())
    except (PermissionError, OSError):
        return {"error": "no access"}

    root_dirs = {d.name for d in top if d.is_dir() and not d.name.startswith(".")}
    root_files = {f.name for f in top if f.is_file()}

    projects = [d for d in top if d.is_dir() and not d.name.startswith(".")
                and d.name not in ("scripts", "Clippings", "assets", "attachments")]

    diff = {
        "root_dirs_missing": sorted(set(REFERENCE_LAYOUT["root_dirs"]) - root_dirs),
        "root_dirs_extra": sorted(root_dirs - set(REFERENCE_LAYOUT["root_dirs"]) - {p.name for p in projects}),
        "root_files_missing": sorted(set(REFERENCE_LAYOUT["root_files"]) - root_files),
        "projects": [],
        "frontmatter": {},
    }

    for p in projects[:20]:
        try:
            subs = {d.name for d in p.iterdir() if d.is_dir()}
            files = {f.name for f in p.iterdir() if f.is_file()}
        except (PermissionError, OSError):
            continue
        diff["projects"].append({
            "name": p.name,
            "missing_dirs": sorted(set(REFERENCE_LAYOUT["project_dirs"]) - subs),
            "extra_dirs": sorted(subs - set(REFERENCE_LAYOUT["project_dirs"])),
            "missing_files": sorted(set(REFERENCE_LAYOUT["project_files"]) - files),
        })

    # Какие поля шапки реально используются: это подскажет, что просить у пользователя.
    seen: dict[str, int] = {}
    checked = 0
    for f in list(vault.rglob("*.md"))[:80]:
        if ".git" in f.parts:
            continue
        try:
            head = f.read_text(encoding="utf-8", errors="replace")[:1500]
        except OSError:
            continue
        if not head.startswith("---"):
            continue
        checked += 1
        for line in head.splitlines()[1:25]:
            if line.strip() == "---":
                break
            m = re.match(r"^([a-zA-Z_][\w-]*):", line)
            if m:
                seen[m.group(1)] = seen.get(m.group(1), 0) + 1
    diff["frontmatter"] = {
        "checked_files": checked,
        "fields_used": dict(sorted(seen.items(), key=lambda x: -x[1])),
        "reference_fields": REFERENCE_LAYOUT["frontmatter"],
        "missing_vs_reference": sorted(set(REFERENCE_LAYOUT["frontmatter"]) - set(seen)),
        "extra_vs_reference": sorted(set(seen) - set(REFERENCE_LAYOUT["frontmatter"])),
    }
    return diff


def suggest_target(osinfo: dict) -> dict:
    fam = osinfo["family"]
    if osinfo.get("wsl"):
        return {"path": str(HOME / "memory/long-term-memory-vault"),
                "why": "WSL: keep the memory on the native Linux filesystem, not on /mnt/c, otherwise it will be slow"}
    if fam == "windows":
        return {"path": str(HOME / "memory" / "long-term-memory-vault"),
                "why": "the user profile root, outside repositories and outside OneDrive"}
    return {"path": str(HOME / "memory/long-term-memory-vault"),
            "why": "the home directory root, outside working repositories"}


# --------------------------------------------------------------------- вывод

def build_report(deep: bool) -> dict:
    osinfo = detect_os()
    tools = detect_tools(osinfo)
    obs = obsidian_state(osinfo)
    target = suggest_target(osinfo)
    memories = find_memories(deep, obs)
    conflicts = assess_conflicts(memories, Path(target["path"]))
    projects = scan_projects([HOME, HOME / "projects", HOME / "dev", HOME / "work",
                              HOME / "src", HOME / "Documents"])

    deps = []
    if not osinfo["python_ok"]:
        cmd = {"apt": "sudo apt install python3", "dnf": "sudo dnf install python3",
               "pacman": "sudo pacman -S python", "brew": "brew install python",
               "winget": "winget install Python.Python.3.12"}.get(osinfo.get("pkg_manager"), "python.org")
        deps.append({"name": "Python 3.8+", "status": "missing", "how": cmd, "blocking": True})
    else:
        deps.append({"name": "Python 3.8+", "status": f"present, {osinfo['python']}", "how": "", "blocking": False})

    deps.append({"name": "Obsidian", "status": "present" if obs["installed"] else "missing",
                 "how": "" if obs["installed"] else obs["install_hint"],
                 "blocking": False})
    deps.append({"name": "git", "status": "present" if tools["git"] else "missing",
                 "how": "" if tools["git"] else "not required: the memory is local, with no sync",
                 "blocking": False})

    agents = []
    if tools["claude"] or (HOME / ".claude").is_dir():
        agents.append("claude-code")
    if tools["amp"]:
        agents.append("amp")

    return {
        "os": osinfo, "tools": tools, "obsidian": obs, "dependencies": deps,
        "agents_found": agents, "suggested_target": target,
        "existing_memories": memories, "conflicts": conflicts,
        "projects": projects,
    }


def print_report(r: dict) -> None:
    o = r["os"]
    print("=" * 62)
    print("RECON BEFORE INSTALLING THE LONG-TERM MEMORY")
    print("=" * 62)

    print("\n[1] System")
    print(f"  OS: {o.get('distro', o['system'])} ({o['machine']})")
    if o.get("wsl"):
        print("  WARNING: this is WSL. Put the memory on the Linux filesystem, not on /mnt/c")
    print(f"  Python: {o['python']}   package manager: {o.get('pkg_manager') or 'not found'}")

    print("\n[2] Dependencies")
    for d in r["dependencies"]:
        mark = "!" if d["blocking"] and d["status"] == "missing" else "-"
        print(f"  {mark} {d['name']}: {d['status']}")
        if d["how"]:
            print(f"      install: {d['how']}")

    print("\n[3] Obsidian")
    obs = r["obsidian"]
    print(f"  installed: {'yes' if obs['installed'] else 'no'}")
    if obs["vaults"]:
        print(f"  known vaults ({len(obs['vaults'])}):")
        for v in obs["vaults"]:
            print(f"    {'ok ' if v['exists'] else 'no '} {v['path']}")
    elif obs["installed"]:
        print("  no vaults registered, the memory will have to be opened as a vault by hand")

    print("\n[4] Agents")
    print(f"  found: {', '.join(r['agents_found']) or 'none found in PATH'}")

    print("\n[5] Existing memory")
    if not r["existing_memories"]:
        print("  not found, installing from scratch")
    for m in r["existing_memories"]:
        print(f"  * {m['path']}")
        print(f"      verdict: {m['verdict']} (score {m['score']}, .md files: {m['md_files']})")
        for s in m["signals"][:5]:
            print(f"      - {s}")

    print("\n[6] Conflicts")
    if not r["conflicts"]:
        print("  none detected")
    for c in r["conflicts"]:
        print(f"  [{c['level']}] {c['path']}")
        print(f"      {c['issue']}")
        print(f"      what to do: {c['action']}")

    print("\n[7] User projects")
    if not r["projects"]:
        print("  none found")
    for p in r["projects"][:25]:
        flags = []
        if p["has_claude_md"]:
            flags.append("has CLAUDE.md")
        if p["has_agents_md"]:
            flags.append("has AGENTS.md")
        print(f"  - {p['path']}  [{', '.join(p['markers'][:3])}]" + (f"  ({', '.join(flags)})" if flags else ""))
    if len(r["projects"]) > 25:
        print(f"  ... {len(r['projects']) - 25} more")

    print("\n[8] Suggested install path")
    t = r["suggested_target"]
    print(f"  {t['path']}")
    print(f"  why: {t['why']}")

    blockers = [c for c in r["conflicts"] if c["level"] == "blocker"]
    missing = [d for d in r["dependencies"] if d["blocking"] and d["status"] == "missing"]
    print("\n" + "=" * 62)
    if blockers:
        print("RESULT: do not install yet, resolve the conflicts above first")
    elif missing:
        print("RESULT: install the dependencies marked with ! first")
    else:
        print("RESULT: safe to install, no blockers")
    print("=" * 62)


def print_compare(out: dict) -> None:
    c, d = out["canon"], out["layout_diff"]
    print("=" * 62)
    print("REVIEW OF AN EXISTING MEMORY")
    print("=" * 62)
    print(f"\nDirectory: {out['vault']}")
    print(f".md files: {c.get('md_files', '?')}")
    print(f"Top level: {', '.join(c.get('top_level', [])[:15]) or 'empty'}")

    print("\n[A] Karpathy method canon: mandatory")
    for e in c.get("present", []):
        print(f"  yes   {e['element']}: {e['what']}")
        print(f"        {e['found']}")
    for e in c.get("missing", []):
        print(f"  NO    {e['element']}: {e['what']}")
        print(f"        looked for: {', '.join(e['detect'])}")
    for n in c.get("notes", []):
        print(f"  ! {n}")

    print("\n[B] What the canon leaves to the owner, no change required")
    for v in CANON["variable"]:
        print(f"  - {v}")

    print("\n[C] What the canon forbids, verify by reading the rules")
    for v in CANON["forbidden"]:
        print(f"  - {v}")

    print("\n[D] Differences from the reference layout (these are NOT violations)")
    if d.get("root_dirs_missing"):
        print(f"  missing in the root: {', '.join(d['root_dirs_missing'])}")
    if d.get("root_files_missing"):
        print(f"  missing files in the root: {', '.join(d['root_files_missing'])}")
    if d.get("root_dirs_extra"):
        print(f"  extra in the root: {', '.join(d['root_dirs_extra'][:10])}")
    for p in d.get("projects", [])[:10]:
        bits = []
        if p["missing_dirs"]:
            bits.append(f"missing: {', '.join(p['missing_dirs'])}")
        if p["extra_dirs"]:
            bits.append(f"own: {', '.join(p['extra_dirs'][:6])}")
        if p["missing_files"]:
            bits.append(f"missing files: {', '.join(p['missing_files'])}")
        if bits:
            print(f"  {p['name']}: " + "; ".join(bits))

    fm = d.get("frontmatter", {})
    if fm.get("checked_files"):
        print(f"\n[E] Frontmatter, files checked: {fm['checked_files']}")
        used = ", ".join(f"{k}({v})" for k, v in list(fm["fields_used"].items())[:12])
        print(f"  in use: {used or 'none'}")
        if fm.get("missing_vs_reference"):
            print(f"  missing versus the reference: {', '.join(fm['missing_vs_reference'])}")
        if fm.get("extra_vs_reference"):
            print(f"  custom fields: {', '.join(fm['extra_vs_reference'][:10])}")

    print("\n" + "=" * 62)
    print("Next: show this to the user and ask what to keep.")
    print("Take unclear points to the memory owner instead of deciding for them.")
    print("=" * 62)


def main() -> int:
    ap = argparse.ArgumentParser(description="Recon before installing the long-term memory")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--deep", action="store_true", help="search the whole home directory for a memory")
    ap.add_argument("--compare", metavar="PATH",
                    help="review a specific memory: canon plus differences from the reference")
    args = ap.parse_args()

    if args.compare:
        v = Path(args.compare).expanduser()
        if not v.is_dir():
            print(f"No such directory: {v}")
            return 2
        out = {"vault": str(v), "canon": canon_audit(v), "layout_diff": layout_diff(v),
               "canon_reference": CANON}
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print_compare(out)
        return 0

    r = build_report(args.deep)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_report(r)
    return 1 if any(c["level"] == "blocker" for c in r["conflicts"]) else 0


if __name__ == "__main__":
    sys.exit(main())
