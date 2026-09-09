#!/usr/bin/env python3
"""
ltm_init.py - interactive deployment of the agent long-term memory.

Creates a local vault following the reference structure, installs the doctor
script, and wires up Claude Code and AMP through their rule files. No git,
no cloud: the memory lives on this machine only.

Works on Ubuntu, macOS and Windows. No dependencies, stdlib only.

Usage:
    python3 ltm_init.py                    interactive, asks questions
    python3 ltm_init.py --check            diagnostics only, changes nothing
    python3 ltm_init.py --path DIR --projects a,b --yes    no questions

The script is idempotent: a repeat run does not overwrite existing files,
it only adds what is missing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Провайдер -> имя файла правил, который читает его агент.
# Спрашиваем у пользователя, не угадываем: у человека может стоять несколько сразу.
PROVIDERS = {
    "claude": {"file": "CLAUDE.md", "label": "Claude Code"},
    "amp": {"file": "AGENTS.md", "label": "AMP Code"},
    "gemini": {"file": "GEMINI.md", "label": "Gemini CLI"},
}
ALL_RULE_FILES = [v["file"] for v in PROVIDERS.values()]

SUBDIRS = ["00-home", "atlas", "knowledge", "sessions", "Raw", "scripts", "tasks"]
KNOWLEDGE_CATS = ["decisions", "patterns", "debugging", "integrations", "analyses", "research"]
TODAY = datetime.now().strftime("%Y-%m-%d")

created: list[str] = []
skipped: list[str] = []


def fm(title: str, project: str, ftype: str, tags: list[str]) -> str:
    tag_lines = "\n".join(f"  - {t}" for t in tags)
    return (
        f"---\ntitle: \"{title}\"\ndate: {TODAY}\nproject: {project}\n"
        f"agent: ltm-init\ntype: {ftype}\ntags:\n{tag_lines}\n"
        f"status: active\nsources: 0\n---\n\n"
    )


def write_once(path: Path, content: str) -> None:
    """Never overwrite an existing file: the memory matters more than the template."""
    if path.exists():
        skipped.append(str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(str(path))


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        val = ""
    return val or default


def ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    try:
        val = input(f"{prompt} ({d}): ").strip().lower()
    except EOFError:
        val = ""
    if not val:
        return default
    return val in ("y", "yes")


def default_vault_path() -> Path:
    return Path.home() / "memory" / "long-term-memory-vault"


# ------------------------------------------------------------- диагностика

def diagnose(vault: Path) -> None:
    print("=== Diagnostics ===")
    print(f"OS: {sys.platform}   Python: {sys.version.split()[0]}")
    print(f"Target vault: {vault}")
    if vault.exists():
        md = [p for p in vault.rglob("*.md") if ".git" not in p.parts]
        projects = sorted(d.name for d in vault.iterdir()
                          if d.is_dir() and not d.name.startswith(".") and (d / "00-home").is_dir())
        print(f"  vault already exists: {len(md)} .md files")
        print(f"  projects following the template: {len(projects)}")
        if projects:
            print(f"  list: {', '.join(projects)}")
        loose = [d.name for d in vault.iterdir()
                 if d.is_dir() and not d.name.startswith(".") and not (d / "00-home").is_dir()]
        if loose:
            print(f"  folders without 00-home (off template): {', '.join(loose)}")
        print(f"  master-index.md: {'present' if (vault / '00-global-home' / 'master-index.md').is_file() else 'MISSING'}")
        print(f"  doctor: {'present' if (vault / 'scripts' / 'ltm_doctor.py').is_file() else 'MISSING'}")
    else:
        print("  no vault yet, it will be created from scratch")

    claude = Path.home() / ".claude"
    print(f"Claude Code: {'found ~/.claude' if claude.is_dir() else '~/.claude folder not found'}")
    print(f"git in PATH: {'yes' if shutil.which('git') else 'no'} (not required for a local memory)")
    print()


# ------------------------------------------------------------- генерация

def make_project(vault: Path, project: str) -> None:
    pdir = vault / project
    for sub in SUBDIRS:
        (pdir / sub).mkdir(parents=True, exist_ok=True)
    for cat in KNOWLEDGE_CATS:
        (pdir / "knowledge" / cat).mkdir(parents=True, exist_ok=True)
        write_once(pdir / "knowledge" / cat / ".gitkeep", "")

    write_once(pdir / "00-home" / "index.md",
        fm(f"{project}: index", project, "index", ["navigation", "index"]) +
        f"# {project}\n\nProject entry point. The agent starts reading here.\n\n"
        "## What this project is\n\nDescribe it in one paragraph: what we build, why, and for whom.\n\n"
        "## Navigation\n\n"
        "- [[current-priorities]]: what we are doing right now\n"
        "- [[hot]]: hot facts and open questions\n"
        "- [[log]]: chronological journal\n\n"
        "## Knowledge\n\nAdd a link to every new page in knowledge/ here, with a one-line description.\n")

    write_once(pdir / "00-home" / "current-priorities.md",
        fm(f"{project}: priorities", project, "index", ["priorities"]) +
        "# Current priorities\n\n1. \n2. \n3. \n\n"
        "Back link: [[index]]\n")

    write_once(pdir / "00-home" / "hot.md",
        fm(f"{project}: hot", project, "index", ["hot"]) +
        "# Hot\n\nFacts that come up often, and open questions.\n\n"
        "Back link: [[index]]\n")

    write_once(pdir / "log.md",
        fm(f"{project}: journal", project, "index", ["log"]) +
        f"# Journal\n\n## {TODAY} init | project created in the memory\n")

    write_once(pdir / "Raw" / "README.md",
        "# Raw\n\nOnly a human puts material here. The agent reads it and never changes it.\n"
        "Text only: transcripts, excerpts, metadata. No video or audio here.\n")

    # Слой Schema проекта. Без него правила расползаются по агентским файлам
    # и через месяц расходятся между собой.
    write_once(pdir / "00-home" / "operations.md",
        fm(f"Vault Operations: {project}", project, "operations",
           ["workflow", "ingest", "query", "lint"]) +
        f"""# Vault Operations: {project}

Rules for how the agent works with this project's memory. Rules shared by all projects:
[[00-global-home/00-home/operations|global operations.md]].

## Layers

| Layer | Where | Who writes |
|-------|-------|------------|
| Raw | `Raw/` | human only, the agent reads and never changes it |
| Wiki | `knowledge/`, `atlas/`, `00-home/` | the agent |
| Schema | this file | human |

## Ingest

1. Put the source material in `Raw/` with a link to the source and a date.
2. Check the index: if a page on the topic exists, update it instead of creating a second one.
3. Before creating or substantially editing a page, show the owner the change and get approval.
4. Update `00-home/index.md` and `log.md`, then run the doctor.

## Query

1. Start from [[{project}/00-home/index|the project index]].
2. Read knowledge pages and their primary sources.
3. Name the files the facts came from in the answer.

## Project scope

Describe here what belongs to this project and what does not. An empty section means
the scope is undefined and the agent will drag unrelated material in.

## Lint

`python3 scripts/ltm_doctor.py` from the memory root. Every new knowledge page must get
an inbound link from `index.md`, otherwise it is an orphan page and the agent never reaches it.
""")

    write_once(pdir / "00-home" / "pending-concepts.md",
        fm(f"{project}: compilation queue", project, "index", ["pending"]) +
        "# Compilation queue\n\nSession logs whose concepts have not been extracted into `knowledge/` yet.\n"
        "Filled in by `ltm_doctor.py --scout`.\n")


def make_global_home(vault: Path, projects: list[str], providers: list[str] | None = None) -> None:
    providers = providers or ["claude", "amp"]
    gh = vault / "00-global-home"
    for sub in ["00-home", "knowledge", "Raw", "sessions", "tasks"]:
        (gh / sub).mkdir(parents=True, exist_ok=True)

    mi = gh / "master-index.md"
    if mi.is_file():
        # Повторный запуск: не перезаписываем индекс, а дописываем недостающие проекты.
        text = mi.read_text(encoding="utf-8")
        missing = [p for p in projects if f"[[{p}/00-home/index" not in text]
        if missing:
            add = "\n".join(f"| [[{p}/00-home/index\\|{p}]] | Active | [[{p}/00-home/index]] |" for p in missing)
            lines = text.rstrip().splitlines()
            last_row = max((i for i, l in enumerate(lines) if l.startswith("| [[")), default=len(lines) - 1)
            lines[last_row + 1:last_row + 1] = add.splitlines()
            mi.write_text("\n".join(lines) + "\n", encoding="utf-8")
            created.append(f"{mi} (+{len(missing)} projects)")
        else:
            skipped.append(str(mi))
        return

    rows = "\n".join(
        ["| [[00-global-home/00-home/index\\|Global knowledge]] | Active | [[00-global-home/00-home/index]] |"]
        + [f"| [[{p}/00-home/index\\|{p}]] | Active | [[{p}/00-home/index]] |" for p in projects])
    rule_lines = "\n".join(
        f"- `{PROVIDERS[k]['file']}`: rules for {PROVIDERS[k]['label']}" for k in providers)
    write_once(mi,
        fm("Master Index", "global", "index", ["navigation", "index"]) +
        "# Master Index\n\nEntry point into the long-term memory. Every request starts here.\n\n"
        "## Before working with the memory\n\n"
        "Read the rules first:\n\n"
        "- [[00-global-home/00-home/operations|Global rules]]: layers, Query, Query -> Save, format, wiki-links\n"
        "- `<project>/00-home/operations.md`: rules for a specific project, they differ per project\n\n"
        "Short pointers for an agent opened directly in the memory root:\n\n"
        + rule_lines + "\n\n"
        "The files have identical content, only the names differ: different agents read different names.\n\n"
        "## Projects\n\n| Project | Status | Entry point |\n|---------|--------|-------------|\n"
        + rows + "\n\n"
        "## Authorship of entries\n\n"
        "The `agent` field in the frontmatter answers 'who wrote this', the `date` field answers 'when'.\n"
        "The memory is local for now, but these fields are mandatory from day one: without them,\n"
        "moving to a memory shared by several people would require rewriting every file.\n")

    write_once(gh / "log.md",
        fm("Global journal", "global", "index", ["log"]) +
        f"# Global journal\n\n## {TODAY} init | memory deployed locally\n")

    # Глобальный operations: правила ЖИВУТ ВНУТРИ памяти, а не в файле настройки
    # машины. Иначе при копировании памяти на другую машину правила не поедут.
    write_once(gh / "00-home" / "operations.md",
        fm("Vault Operations: global rules", "global", "operations",
           ["workflow", "ingest", "query", "lint"]) +
        """# Vault Operations: global rules

Shared rules for working with the memory. Rules for a specific project live in
`<project>/00-home/operations.md` and take precedence where they add detail.

This file lives inside the memory on purpose: when the memory is copied to another
machine the rules travel with it, and the agent needs no external config file.

## Layers

| Layer | Where | Who writes |
|-------|-------|------------|
| Raw | `<project>/Raw/` | human only |
| Wiki | `knowledge/`, `atlas/`, `00-home/` | the agent |
| Schema | the rule files in the memory root and `operations.md` | human |

## Query

1. `00-global-home/master-index.md`
2. `<project>/00-home/index.md`
3. `<project>/00-home/operations.md`, project rules differ
4. `knowledge/`, then `log.md` and recent `sessions/`

Read between 10 and 50 files per request. Name the source files in the answer.

## Query -> Save

Save when the session produced: a new connection between entities, a synthesis across
sources, a comparison of approaches with reasoning, the root cause of a bug, an
architectural conclusion. Do not save a plain fact lookup or a short clarification.

Without a knowledge page the knowledge stays in the session log only, and the structural
lint does not check session logs. Session logs are cheap, knowledge pages are expensive.

## Mandatory format

Every .md starts with YAML: `title`, `date`, `project`, `agent`, `type`, `tags`, `status`.

## Wiki-links

- Every knowledge page has at least one inbound link, otherwise it is an orphan page.
- Links are two-way: if A links to B, then B links to A.
- Write the path from the memory root. Obsidian does not resolve relative `../` paths.
- The case of the project name matters: a link to `my-proj/log` when the directory is
  `My_Proj` leads nowhere, even though it looks fine.
- Session logs are not linked into the graph.

## One document per topic

There is one page per topic. An outdated one is marked `status: superseded` with a link
to its replacement, instead of being duplicated by a second file in a different state.

## Source material: text only

Do not put video or audio into the memory: if the memory is under git, the binary stays
in history forever. Transcribe in a temporary folder and store the text.

## Health check

`python3 scripts/ltm_doctor.py` from the memory root. An ERROR is fixed immediately,
a WARNING is handled as the work goes on.

## At the end of a session

Create `<project>/sessions/YYYY-MM-DD_HHMM_<agent>_<topic>.md`, update
`current-priorities.md` and `hot.md`, and append to `log.md`.
""")

    # Индекс глобального проекта. Без него знания общего уровня начинают
    # перечисляться прямо в master-index, и он раздувается.
    write_once(gh / "00-home" / "index.md",
        fm("00-global-home: index", "global", "index", ["navigation", "index"]) +
        """# 00-global-home: index

> **Rules for working with the memory: [[operations]].** Read them before writing anything.

Entry point into global knowledge: things that apply to several projects at once and
belong to none of them. Navigation between projects lives separately, in
[[00-global-home/master-index|Master Index]].

## Operational cache

- [[operations]]: shared rules for working with the memory
- [[00-global-home/log|log.md]]: chronological journal

## Knowledge

The sections mirror the subfolders of `knowledge/`. Each page is listed once, with a
one-line description. There should be no 'favourites' lists ordered by importance here:
sections are organised by the category of their content.
""")


def make_rules(vault: Path, projects: list[str]) -> str:
    plist = "\n".join(f"- `{p}/`" for p in projects)
    return f"""# Long-term memory rules

The agent reads this file at the start of every session. It describes how the memory
is built and what the agent must do with it.

## Where the memory is and where to start

Root: this directory. The memory is local, there is no sync.
The only copy lives on this machine, so backups are the owner's responsibility.

**The entry point into the memory is `00-global-home/master-index.md`, not this file.**
This file describes HOW to work with the memory. The master-index describes WHAT is in it.
The order is: read these rules, then go to the master-index and follow the links.

## Structure

```
<vault>/
├── 00-global-home/       global navigation
│   └── master-index.md   canonical entry point, reading starts here
├── <project>/
│   ├── 00-home/          index.md, current-priorities.md, hot.md, pending-concepts.md
│   ├── atlas/            architecture, stack, database, deployment
│   ├── knowledge/        decisions, patterns, debugging, integrations, analyses, research
│   ├── sessions/         session logs YYYY-MM-DD_HHMM_agent_topic.md
│   ├── Raw/              sources, written by a human only
│   ├── scripts/          local project utilities
│   └── log.md            append-only journal
└── scripts/ltm_doctor.py memory health check
```

Current projects:
{plist}

## Layers and permissions

- `Raw/` is written by a human only. The agent reads it and never changes it.
- `atlas/`, `knowledge/`, `00-home/` are maintained by the agent.
- This rules file is written by a human.
- Session logs are raw material, not canon. The canon lives in `knowledge/`.

## File format

Every .md starts with YAML frontmatter:

```yaml
---
title: "Description"
date: YYYY-MM-DD
project: <project>
agent: claude-code
type: <atlas|integration|decision|debugging|pattern|business|analysis|session>
tags: [tag1, tag2]
status: active
sources: 0
---
```

## The Query operation, answering a question

1. `00-global-home/master-index.md`
2. `<project>/00-home/index.md`
3. `<project>/knowledge/decisions/`
4. `<project>/knowledge/patterns/`
5. `<project>/00-home/current-priorities.md`
6. `<project>/00-home/hot.md`
7. `<project>/log.md`
8. recent files in `<project>/sessions/`

The 10-50 rule: read between 10 and 50 files per request, no more.
Name the files the facts came from in the answer.
Do not answer 'nothing found' before this path has been walked to the end.

## The Save operation, what must be saved

- new connections between entities
- a synthesis of ideas from different sources
- a comparison of approaches and the reasoning behind the choice
- a bug fix and its root cause
- an architectural conclusion or a new pattern
- an update to the behaviour of an already documented concept

Do not save: a plain fact lookup, a short clarification, anything already fully on a page.

## When creating a new page in knowledge/

1. add a link in `<project>/00-home/index.md` with a one-line description
2. append a line to `<project>/log.md`
3. add two-way wiki-links to the related pages
4. add a `## Sources` section at the end of the page with a link to the session file
5. increment `sources:` in the frontmatter

The wiki-link rule: every knowledge page has at least one inbound link, otherwise it is
an orphan page and the doctor flags it. Session logs are not linked.

## At the end of a session

- create `<project>/sessions/YYYY-MM-DD_HHMM_<agent>_<topic>.md`
- update `current-priorities.md` and `hot.md`
- append an entry to `log.md`
- run `python3 scripts/ltm_doctor.py` and fix everything it reports as ERROR

## Health check

```
python3 scripts/ltm_doctor.py           full check
python3 scripts/ltm_doctor.py --scout   flag sessions that are ready to be compiled
python3 scripts/ltm_doctor.py --all     scout, then the check
python3 scripts/ltm_doctor.py --json    machine-readable output for the agent
```

An ERROR is fixed immediately. A WARNING is handled as work on the project goes on.

## Shared memory: the rules apply already

The memory is local right now, one copy, on this machine. It may later be merged for
several people. The transport for that merge is not chosen yet. So that the transition
does not require rewriting every file, these rules apply from day one:

- **Authorship is mandatory.** The `agent` field in the frontmatter answers 'who wrote this',
  `date` answers 'when'. Without them, a shared memory makes it impossible to tell whose
  entry it is and whether it is still current
- **One document per topic.** If a page on the topic exists, update it. Do not create a
  second file on the same topic. In a shared memory, two files about one thing guarantee
  a wrong answer from the agent
- **Do not delete outdated pages.** Set `status: superseded` in the frontmatter and put a
  link to the replacement in the first line of the body. A deleted page looks like it never
  existed, while a colleague may still have it open
- **`log.md` is append-only.** Do not rewrite or delete lines. It is the only way to tell
  who changed what once there is more than one writer
- **Personal is separated from shared.** Anything that must not reach colleagues belongs in
  a project marked clearly in `index.md`, not mixed in with everything else
- **Edits are atomic.** One topic, one file, at a time. Large rewrites of a whole project
  turn into unresolvable conflicts in a shared memory

When a transport is chosen (shared git, a network folder or a server), these rules do not
change, only a sync procedure gets added.

## Style

Do not use em dashes anywhere: not in memory files, not in answers.
Replace them with a comma, a colon, brackets or a full stop.
"""


def install_doctor(vault: Path) -> None:
    # Планировщик кладём рядом с доктором: без него регулярная проверка
    # остаётся советом в тексте, который никто не выполнит.
    sched_src = Path(__file__).resolve().parent / "ltm_schedule.py"
    if sched_src.is_file():
        sched_dst = vault / "scripts" / "ltm_schedule.py"
        sched_dst.parent.mkdir(parents=True, exist_ok=True)
        if sched_dst.exists():
            skipped.append(str(sched_dst))
        else:
            shutil.copy2(sched_src, sched_dst)
            created.append(str(sched_dst))
            if os.name != "nt":
                try:
                    sched_dst.chmod(0o755)
                except OSError:
                    pass

    src = Path(__file__).resolve().parent / "ltm_doctor.py"
    dst = vault / "scripts" / "ltm_doctor.py"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        print(f"  WARNING: no ltm_doctor.py next to this script, copy it to {dst} by hand")
        return
    if dst.exists():
        skipped.append(str(dst))
    else:
        shutil.copy2(src, dst)
        created.append(str(dst))
    if os.name != "nt":
        dst.chmod(0o755)

    # Windows: батник, чтобы доктор запускался двойным кликом и из cmd.
    if os.name == "nt":
        bat = vault / "scripts" / "ltm_doctor.bat"
        write_once(bat, f'@echo off\r\nchcp 65001 >nul\r\npython "%~dp0ltm_doctor.py" %*\r\n')
    else:
        sh = vault / "scripts" / "ltm_doctor.sh"
        write_once(sh, '#!/usr/bin/env bash\nexec python3 "$(dirname "$0")/ltm_doctor.py" "$@"\n')
        if sh.exists():
            sh.chmod(0o755)


MEMORY_BLOCK_START = "<!-- ltm:start -->"
MEMORY_BLOCK_END = "<!-- ltm:end -->"


def memory_block(vault: Path, provider: str = "claude") -> str:
    """The block inserted into the rule files of a working project.

    Wrapped in markers so a repeat run updates it instead of adding copies."""
    rules_file = PROVIDERS.get(provider, PROVIDERS["claude"])["file"]
    return (
        f"{MEMORY_BLOCK_START}\n"
        "## Long-term memory\n\n"
        "This is NOT this project's memory and not the agent's MEMORY.md file. It is a separate\n"
        "file-based knowledge store, shared by every project on this machine.\n\n"
        f"Memory directory: `{vault}`\n\n"
        "How to approach it:\n"
        f"1. rules for working with the memory: `{vault / rules_file}`\n"
        f"2. entry point into the memory itself: `{vault / '00-global-home' / 'master-index.md'}`\n"
        "3. then follow the links from the master-index: `<project>/00-home/index.md`,\n"
        "   `knowledge/decisions/`, `knowledge/patterns/`, `current-priorities.md`, `hot.md`,\n"
        "   recent files in `<project>/sessions/`\n\n"
        "When to use it: questions about decisions made earlier, architecture, the cause of a bug,\n"
        "anything already discussed. Do not answer 'I do not know' before walking this path.\n\n"
        "What to record: new connections, a synthesis across sources, a comparison of approaches,\n"
        "the root cause of a bug, an architectural conclusion. Do not record a plain fact lookup.\n\n"
        "At the end of a session: a log in `<project>/sessions/`, update `log.md`.\n"
        "Health check: `python3 " + str(vault / "scripts" / "ltm_doctor.py") + "`\n"
        f"{MEMORY_BLOCK_END}\n"
    )


def link_project(project_dir: Path, vault: Path, providers: list[str]) -> list[str]:
    """Write a pointer to the memory into the rule files of a working project.

    A file is created only if the user picked that provider: a stray GEMINI.md in the
    project of someone who does not use Gemini is just clutter."""
    done = []
    for prov in providers:
        fname = PROVIDERS[prov]["file"]
        block = memory_block(vault, prov)
        target = project_dir / fname
        if target.is_file():
            text = target.read_text(encoding="utf-8", errors="replace")
            if MEMORY_BLOCK_START in text:
                # Блок уже есть: обновляем его содержимое, остальной файл не трогаем.
                start = text.index(MEMORY_BLOCK_START)
                end = text.index(MEMORY_BLOCK_END) + len(MEMORY_BLOCK_END) + 1
                new = text[:start] + block + text[end:]
                if new != text:
                    target.write_text(new, encoding="utf-8")
                    done.append(f"{target} (block updated)")
            else:
                with target.open("a", encoding="utf-8") as fh:
                    fh.write("\n\n" + block)
                done.append(f"{target} (block appended)")
        else:
            target.write_text(f"# {project_dir.name}\n\n" + block, encoding="utf-8")
            done.append(f"{target} (created)")
    return done


def adopt_existing(vault: Path, providers: list[str]) -> list[str]:
    """Adopt someone else's memory: do not break the structure, only add what is missing."""
    notes = []
    projects = sorted(d.name for d in vault.iterdir()
                      if d.is_dir() and not d.name.startswith(".")
                      and d.name not in ("scripts", "Clippings"))
    if not (vault / "00-global-home" / "master-index.md").is_file():
        make_global_home(vault, projects, providers)
        notes.append("created 00-global-home/master-index.md, there was no entry point")
    else:
        # Точка входа есть, но может не вести к правилам. Дописываем ссылку, текст не трогаем.
        mi = vault / "00-global-home" / "master-index.md"
        txt = mi.read_text(encoding="utf-8", errors="replace")
        missing = [PROVIDERS[p]["file"] for p in providers if PROVIDERS[p]["file"] not in txt]
        if missing:
            with mi.open("a", encoding="utf-8") as fh:
                fh.write("\n## Rules for working with the memory\n\n")
                for f in missing:
                    fh.write(f"- `{f}` in the memory root\n")
            notes.append(f"links to the rule files appended to the master-index: {', '.join(missing)}")
    for p in projects:
        pdir = vault / p
        if not (pdir / "00-home").is_dir() and (pdir / "sessions").is_dir():
            notes.append(f"project {p}: no 00-home, the structure differs from the reference, left as is")
    for prov in providers:
        f = PROVIDERS[prov]["file"]
        if not (vault / f).is_file():
            notes.append(f"added {f} with the rules")
    return notes


def discover_projects(vault: Path, max_depth: int = 3) -> list[dict]:
    """Find the user's working projects, so they can be offered as a list."""
    markers = [".git", "package.json", "pyproject.toml", "requirements.txt", "go.mod",
               "Cargo.toml", "pom.xml", "build.gradle", "composer.json", "Gemfile",
               "CMakeLists.txt", "Makefile", "docker-compose.yml"]
    skip = {".cache", ".local", "Library", "AppData", "node_modules", ".npm", ".nvm",
            "snap", "Applications", ".Trash", ".git", "venv", ".venv", "OrbStack"}
    found, seen = [], set()

    def walk(d: Path, depth: int):
        if depth > max_depth or d.name in skip or d.name.startswith("."):
            return
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            return
        names = {e.name for e in entries}
        if set(markers) & names:
            key = str(d.resolve())
            if key not in seen and key != str(vault.resolve()):
                seen.add(key)
                found.append({
                    "path": str(d),
                    "rules": sorted(set(ALL_RULE_FILES) & names),
                    "markers": sorted(set(markers) & names)[:3],
                })
            return
        for e in entries:
            if e.is_dir() and not e.is_symlink():
                walk(e, depth + 1)

    for root in [Path.home(), Path.home() / "projects", Path.home() / "dev",
                 Path.home() / "work", Path.home() / "src", Path.home() / "Documents"]:
        if root.is_dir():
            walk(root, 1)
    return sorted(found, key=lambda x: x["path"])


def choose_projects(vault: Path) -> list[str]:
    """Show the projects found and let the user choose. Without a choice nothing is touched."""
    print("\nLooking for working projects...")
    projects = discover_projects(vault)
    if not projects:
        raw = ask("No projects found. Enter paths manually, comma separated (empty = skip)", "")
        return [t.strip() for t in raw.split(",") if t.strip()]

    print(f"\nProjects found: {len(projects)}")
    for i, p in enumerate(projects, 1):
        rules = f"has {', '.join(p['rules'])}" if p["rules"] else "no rule files"
        print(f"  {i}. {p['path']}")
        print(f"     [{', '.join(p['markers'])}]  {rules}")

    print("\nWhich projects should point to the long-term memory?")
    print("  numbers separated by commas, 'all', 'rules' (only those that already have rule files),")
    print("  or empty to leave everything alone")
    raw = ask("Choice", "").strip().lower()
    if not raw:
        return []
    if raw in ("all", "*"):
        return [p["path"] for p in projects]
    if raw in ("rules", "with-rules"):
        return [p["path"] for p in projects if p["rules"]]
    out = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit() and 1 <= int(tok) <= len(projects):
            out.append(projects[int(tok) - 1]["path"])
    return out


def verify(vault: Path, linked: list[str], providers: list[str]) -> bool:
    """Self-check: the agent must confirm that the installation actually works."""
    print("\n=== Self-check ===")
    ok = True

    mi = vault / "00-global-home" / "master-index.md"
    checks = [
        ("memory directory", vault.is_dir()),
        ("entry point master-index.md", mi.is_file()),
    ]
    for prov in providers:
        f = PROVIDERS[prov]["file"]
        checks.append((f"rules {f} ({PROVIDERS[prov]['label']})", (vault / f).is_file()))
    # Точка входа обязана вести к правилам, иначе агент их не найдёт.
    if mi.is_file():
        txt = mi.read_text(encoding="utf-8", errors="replace")
        checks.append(("master-index points to the rule files",
                       all(PROVIDERS[p]["file"] in txt for p in providers)))
    checks += [
        ("doctor ltm_doctor.py", (vault / "scripts" / "ltm_doctor.py").is_file()),
        ("path marker .ltm-vault", (vault / ".ltm-vault").is_file()),
    ]
    for label, res in checks:
        print(f"  {'ok  ' if res else 'FAIL'} {label}")
        ok = ok and res

    doctor = vault / "scripts" / "ltm_doctor.py"
    if doctor.is_file():
        try:
            r = subprocess.run([sys.executable, str(doctor), "--vault", str(vault), "--quiet"],
                               capture_output=True, text=True, timeout=180)
            passed = r.returncode == 0
            print(f"  {'ok  ' if passed else 'FAIL'} doctor runs (exit code {r.returncode})")
            tail = [l for l in r.stdout.strip().splitlines() if l.strip()][-2:]
            for line in tail:
                print(f"       {line}")
            ok = ok and passed
        except (subprocess.SubprocessError, OSError) as e:
            print(f"  FAIL doctor did not run: {e}")
            ok = False

    if linked:
        print(f"  ok   rules wired into projects: {len(linked)}")
        for l in linked:
            print(f"       {l}")

    print("\n  RESULT: " + ("the installation works" if ok else "there are failures, see the FAIL lines above"))
    return ok


def print_next_steps(vault: Path, providers: list[str] | None = None) -> None:
    providers = providers or ["claude"]
    doctor = vault / "scripts" / "ltm_doctor.py"
    mi = vault / "00-global-home" / "master-index.md"
    print("\n=== What next ===")
    print("1. Check the memory right now:")
    print(f"   python3 \"{doctor}\"")
    print("2. Entry point into the memory (the agent opens it first):")
    print(f"   {mi}")
    print("3. Rule files in the memory root:")
    for prov in providers:
        print(f"   {vault / PROVIDERS[prov]['file']}  ->  {PROVIDERS[prov]['label']}")
    print("4. Global wiring, if you need it outside the selected projects:")
    for prov in providers:
        home_cfg = {"claude": "~/.claude/CLAUDE.md", "amp": "~/.config/amp/AGENTS.md",
                    "gemini": "~/.gemini/GEMINI.md"}.get(prov, "")
        if home_cfg:
            print(f"   {home_cfg}: add a pointer to {mi}")
    sched = vault / "scripts" / "ltm_schedule.py"
    print("5. Regular memory health check:")
    if sched.is_file():
        print(f"   python3 \"{sched}\"")
        print("   Puts the doctor on a schedule: weekdays, 12:00. It asks for confirmation.")
    else:
        print(f"   python3 \"{doctor}\" --all --quiet")
    print("6. Backup: the memory is local, there is one copy. Keep a copy off this machine.")


def offer_schedule(vault: Path, auto_yes: bool = False) -> None:
    """Offer the schedule right after the installation.

    A separate step and only with consent: writing to cron, launchd or the Windows
    Task Scheduler changes the user's system, not the inside of the memory.
    """
    sched = vault / "scripts" / "ltm_schedule.py"
    if not sched.is_file():
        return
    print("\n=== Regular check ===")
    print("Memory decays quietly: broken links and orphan pages are invisible")
    print("until the agent starts answering wrong. The check catches this early.")
    if not auto_yes:
        try:
            a = input("Put the check on a schedule: weekdays, 12:00? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return
        if a and a not in ("y", "yes"):
            print("Skipped. To do it later:")
            print(f"  python3 \"{sched}\"")
            return
    r = subprocess.run([sys.executable or "python3", str(sched),
                        "--path", str(vault), "--yes"],
                       capture_output=False)
    if r.returncode != 0:
        print("The schedule was not installed. Try it manually:")
        print(f"  python3 \"{sched}\"")


def main() -> int:
    ap = argparse.ArgumentParser(description="Deploy the agent long-term memory")
    ap.add_argument("--path", help="path to the vault")
    ap.add_argument("--projects", help="comma separated list of projects")
    ap.add_argument("--check", action="store_true", help="diagnostics only")
    ap.add_argument("--yes", action="store_true", help="no questions")
    ap.add_argument("--adopt", action="store_true",
                    help="adopt the existing memory at this path instead of creating a new one")
    ap.add_argument("--link", metavar="DIRS",
                    help="wire the memory into working projects: comma separated paths")
    ap.add_argument("--no-verify", action="store_true", help="skip the self-check")
    ap.add_argument("--schedule", action="store_true",
                    help="install the scheduled check right away: weekdays, 12:00")
    ap.add_argument("--no-schedule", action="store_true",
                    help="do not offer the schedule")
    ap.add_argument("--providers", metavar="LIST",
                    help="comma separated agents: claude, amp, gemini. Asks by default")
    args = ap.parse_args()

    print("Deploying the agent long-term memory\n")

    vault = Path(args.path).expanduser() if args.path else default_vault_path()
    if not args.path and not args.yes and not args.check:
        vault = Path(ask("Where to put the memory", str(default_vault_path()))).expanduser()

    diagnose(vault)
    if args.check:
        return 0

    # Провайдера НЕ угадываем: у человека может стоять несколько агентов сразу,
    # и от выбора зависит и что кладём в память, и какие файлы искать в его проектах.
    if args.providers:
        providers = [p.strip().lower() for p in args.providers.split(",")
                     if p.strip().lower() in PROVIDERS]
    elif args.yes:
        providers = ["claude", "amp"]
    else:
        print("Which agent do you use? You can pick several.")
        for i, (k, v) in enumerate(PROVIDERS.items(), 1):
            print(f"  {i}. {v['label']}  ->  {v['file']}")
        raw = ask("Numbers separated by commas, or 'all'", "1")
        if raw.strip().lower() in ("all", "*"):
            providers = list(PROVIDERS)
        else:
            keys = list(PROVIDERS)
            providers = []
            for tok in raw.split(","):
                tok = tok.strip()
                if tok.isdigit() and 1 <= int(tok) <= len(keys):
                    providers.append(keys[int(tok) - 1])
                elif tok.lower() in PROVIDERS:
                    providers.append(tok.lower())
    if not providers:
        providers = ["claude"]
    print(f"Rule files will be: {', '.join(PROVIDERS[p]['file'] for p in providers)}")

    if args.projects:
        projects = [p.strip() for p in args.projects.split(",") if p.strip()]
    elif args.yes:
        projects = ["work"]
    else:
        raw = ask("Projects, comma separated (these are just folders, you can add more later)", "work")
        projects = [p.strip() for p in raw.split(",") if p.strip()]

    if not args.yes:
        print(f"\nThe memory will be created in {vault}")
        print(f"Projects: {', '.join(projects)}")
        if not ask_yes("Continue?"):
            print("Cancelled.")
            return 0

    vault.mkdir(parents=True, exist_ok=True)
    (vault / "scripts").mkdir(exist_ok=True)

    if args.adopt:
        # Чужая память уже устроена как-то. Не переделываем её под эталон,
        # а только дописываем то, без чего агент не сможет работать.
        print("\nAdopt mode: the existing memory is taken as is.")
        for note in adopt_existing(vault, providers):
            print(f"  {note}")
    else:
        make_global_home(vault, projects, providers)
        for p in projects:
            make_project(vault, p)

    rules = make_rules(vault, projects)
    # Один текст под разными именами: каждый агент читает своё имя файла.
    for prov in providers:
        write_once(vault / PROVIDERS[prov]["file"], rules)
    write_once(vault / "README.md",
        fm("Long-term memory", "global", "meta", ["vault", "memory"]) +
        "# Agent long-term memory\n\n"
        "A local file-based memory for Claude Code and AMP. There is no sync.\n\n"
        "Start reading: [[00-global-home/master-index]]\n"
        "Rules: `AGENTS.md`\n"
        "Health check: `python3 scripts/ltm_doctor.py`\n")
    write_once(vault / ".ltm-vault", str(vault))

    install_doctor(vault)

    linked: list[str] = []
    link_targets: list[str] = []
    if args.link:
        link_targets = [t.strip() for t in args.link.split(",") if t.strip()]
    elif not args.yes:
        link_targets = choose_projects(vault)

    for t in link_targets:
        pdir = Path(t).expanduser()
        if not pdir.is_dir():
            print(f"  skipped, no such directory: {pdir}")
            continue
        linked += link_project(pdir, vault, providers)

    print(f"\nFiles and folders created: {len(created)}")
    if skipped:
        print(f"Skipped (already existed): {len(skipped)}")

    ok = True
    if not args.no_verify:
        ok = verify(vault, linked, providers)

    # Расписание предлагаем только когда установка действительно рабочая:
    # ставить проверку на сломанную память бессмысленно.
    if ok and not args.check:
        if args.schedule:
            offer_schedule(vault, auto_yes=True)
        elif not args.yes and not args.no_schedule:
            offer_schedule(vault, auto_yes=False)

    print_next_steps(vault, providers)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
