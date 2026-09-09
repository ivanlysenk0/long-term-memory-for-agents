---
name: ltm-vault
description: Deploys, adopts and verifies a file-based long-term memory vault for agents (Karpathy method). Use when setting up memory on a new machine, wiring it into Claude Code, Gemini CLI or AMP Code, adopting an existing structure, or checking vault health.
---

# Agent long-term memory

Memory is a directory of markdown files the agent reads at session start and writes
back to afterwards. Not a database, not a plugin: plain files a human can read.

## Three layers

| Layer | Where | Who writes |
|-------|-------|-----------|
| Raw | `<project>/Raw/` | humans only, the agent reads and never edits |
| Wiki | `knowledge/`, `atlas/`, `00-home/` | the agent |
| Schema | rule files in the vault root and `operations.md` | humans |

Three operations: **Ingest** (raw material into a knowledge page), **Query** (an answer
citing its files), **Lint** (integrity check).

## Tools

All in `scripts/`, Python 3.8+ only, no dependencies.

| Script | Purpose |
|--------|---------|
| `ltm_detect.py` | scan the machine: OS, editor, existing memory, conflicts |
| `ltm_init.py` | install, adopt existing memory, wire into agents |
| `ltm_doctor.py` | health check: 9 checks, ~1 second per 500 files |

## Workflow

### 1. Detect first, always

```bash
python3 scripts/ltm_detect.py
```

Show the user the summary and **wait for their decision**. Install nothing until you
understand what is already on the machine.

The detector scores what it finds. **Score 9 or higher means memory already exists.**
Do not create a second one: the agent will read the wrong vault and answer wrong.

### 2. Read the findings

- **OS and dependencies**: Python 3.8+ required, git optional
- **Existing memory**: if found, offer `--adopt` instead of a fresh install
- **Conflicts**: memory inside a working repository will end up in a commit

Compare what you found **against the canon, not against someone's implementation**:

```bash
python3 scripts/ltm_detect.py --compare /path/to/memory
```

The canon allows different directory names. `sources/`, `Clippings/`, `inbox/` are
the same role as `Raw/`. Differences from a reference layout are **not violations**.

### 3. Install

```bash
# new memory
python3 scripts/ltm_init.py

# adopt an existing structure without breaking it
python3 scripts/ltm_init.py --adopt --path /path/to/memory

# diagnose only, change nothing
python3 scripts/ltm_init.py --check --path /path
```

### 4. Wire into agents

**Ask which provider, do not guess.** Each has its own rule file:

| Agent | Project file | Global |
|-------|--------------|--------|
| Claude Code | `CLAUDE.md` | `~/.claude/CLAUDE.md` |
| AMP Code | `AGENTS.md` | `~/.config/amp/AGENTS.md` |
| Gemini CLI | `GEMINI.md` | `~/.gemini/GEMINI.md` |

```bash
python3 scripts/ltm_init.py --link /path/to/project --providers claude,gemini
```

The block goes between `<!-- ltm:start -->` and `<!-- ltm:end -->` markers, existing
file content is preserved.

**The entry point into memory is `00-global-home/master-index.md`**, not the rule file.
The rule file answers "how to work", master-index answers "what exists".

### 5. Self-check

The installer runs 7 checks at the end. Read its output: exit code 1 means the install
is incomplete, do not tell the user it is done.

### 6. Vault health

```bash
python3 scripts/ltm_doctor.py            # check
python3 scripts/ltm_doctor.py --scout    # flag sessions ready to compile
python3 scripts/ltm_doctor.py --all      # both steps
```

ERROR gets fixed immediately. WARNING gets handled as the work goes.

Schedule it:
```
0 20 * * * python3 "<vault>/scripts/ltm_doctor.py" --all --quiet
```

## Multi-project

The canon requires "one vault, one project". Several projects in one vault is a
**deliberate deviation** and it has a cost: the index is read on every query, so each
new project makes every other project more expensive.

If the user chooses multi-project, record the cost in `operations.md` and keep the
top-level index clean: navigation only, no rulebooks.

## Pitfalls

- **Memory inside a working repository** ends up in a commit. Install into the home
  directory, outside repositories and outside cloud sync folders
- **Two vaults at once**: the agent reads the wrong one. Either adopt, or get an
  explicit decision from the owner
- **WSL and `/mnt/c`**: memory on a Windows drive is several times slower
- **Windows and non-ASCII**: run `chcp 65001` first
- **Do not port these scripts to bash.** The original called `find` inside a loop:
  3.5 minutes over 500 files versus 0.9 seconds in Python
- **Escaping `\|` in wiki-links** is required inside Obsidian tables
- **Rule files are not knowledge pages**, the doctor excludes them
- **Backups**: memory is local, one copy. Tell the owner

## Failures found in production

All of this surfaced on a vault with 500 files and 15 projects.

- **A link with a path, checked by short name, lied.** The doctor searched for `log`
  across the whole vault, found some other `log.md` and considered `[[my-proj/log]]`
  valid. The directory was `My_Proj`, the link went nowhere. 24 links in one project
  broke silently. Links containing `/` are now checked literally
- **Relative `../` paths are not resolved by Obsidian.** They look reasonable, they
  do not work
- **Rules outside the vault do not travel with it.** If shared rules live in a machine
  config file, whoever copies the vault gets structure without the rulebook. That is
  why `operations.md` is created inside the vault
- **The top-level index bloats** when the global project has no index of its own.
  General knowledge starts getting listed directly in master-index
- **A task tracker rulebook is not navigation.** Tracker rules belong in `operations.md`,
  the index keeps one line with a link
- **Blocks outlive their reason.** A list of direct links to each project's service
  files makes sense with one project and becomes duplication with ten
- **Before deleting any block of links, verify every link with a script**, not by eye

## In short

1. `ltm_detect.py`, show the summary, wait for a decision
2. resolve conflicts and dependencies
3. `ltm_init.py` in the right mode
4. `--link` into working projects
5. read the self-check block
6. verify live: ask the agent how it reads memory
7. offer a schedule for the doctor and mention backups
