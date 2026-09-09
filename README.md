# Agent Long-Term Memory

A file-based long-term memory template for AI agents, following Andrej Karpathy's method.
Works with **Claude Code**, **Gemini CLI** and **AMP Code** on macOS, Linux and Windows.

Memory is a directory of markdown files that the agent reads at the start of a session
and writes back to when the work is done. Not a database, not a plugin: plain files
a human can read too.

## Why

An agent without memory starts from zero every time. You explain the same thing again,
and it proposes the approach you rejected a month ago.

Memory fixes that: decisions, root causes and working approaches live in linked files.
The next session starts by reading them.

## Quick start

```bash
git clone https://github.com/<user>/<repo>.git
cd <repo>
./install.sh
```

Windows, PowerShell:

```powershell
git clone https://github.com/<user>/<repo>.git
cd <repo>
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer detects which agents you have. Then restart your agent and say:

> set up long-term memory

The agent reads the skill and walks you through detection, install and wiring.

## What is inside

```
skill/
├── SKILL.md              instructions for the agent
└── scripts/
    ├── ltm_detect.py     scans the machine before installing
    ├── ltm_init.py       install, adopt existing memory, wire to agents
    └── ltm_doctor.py     health check for the vault
install.sh                install: macOS, Ubuntu, Debian, Fedora, Arch
install.ps1               install: Windows
```

No dependencies. **Python 3.8 or newer** is all you need.

## Three layers

| Layer | Where | Who writes |
|-------|-------|-----------|
| **Raw** | `<project>/Raw/` | humans only. The agent reads and never edits |
| **Wiki** | `knowledge/`, `atlas/`, `00-home/` | the agent |
| **Schema** | rule files and `operations.md` | humans |

The split matters. If the agent writes into Raw, primary sources stop being sources.
If humans hand-edit the Wiki, the agent loses the link graph.

## Three operations

- **Ingest**: raw material becomes a linked knowledge page
- **Query**: an answer that cites the exact files it came from
- **Lint**: a structural integrity check

## Manual usage

The scripts work without an agent.

```bash
# what already exists on this machine
python3 skill/scripts/ltm_detect.py

# compare an existing structure against the canon
python3 skill/scripts/ltm_detect.py --compare ~/memory

# new memory
python3 skill/scripts/ltm_init.py

# adopt an existing structure without breaking it
python3 skill/scripts/ltm_init.py --adopt --path ~/memory

# wire memory into a working project
python3 skill/scripts/ltm_init.py --link ~/projects/my-app --providers claude,gemini

# health check
python3 skill/scripts/ltm_doctor.py --vault ~/memory
```

## Health check

`ltm_doctor.py` runs nine checks in about a second over 500 files:

- missing or incomplete YAML frontmatter
- malformed dates
- broken wiki-links, including ones that **look** valid
- wrong case in a project name: `[[my-proj/log]]` when the directory is `My_Proj`
- relative `../` paths, which Obsidian does not resolve
- duplicate page names
- orphan pages with no inbound link
- stubs with no content
- sessions whose knowledge has not been compiled yet

Schedule it:

```
0 20 * * * python3 "<vault>/scripts/ltm_doctor.py" --all --quiet
```

## Where the skill installs

| Agent | Directory |
|-------|-----------|
| Claude Code | `~/.claude/skills/ltm-vault/` |
| AMP Code | `~/.config/amp/skills/ltm-vault/` (Windows: `%APPDATA%\amp\skills\`) |
| Gemini CLI | `~/.gemini/skills/ltm-vault/` |

Installer options: `--claude`, `--amp`, `--gemini`, `--all`, `--help`.

## Know this up front

- **Memory is local.** No sync, one copy. Backups are the owner's responsibility
- **Do not put memory inside a working repository**: it will end up in a commit
- **Do not run two memories at once**: the agent will read the wrong one
- **No video or audio in memory.** Under git a binary stays in history forever.
  Store the transcript instead
- **WSL**: memory on a Windows drive (`/mnt/c`) is several times slower

## Multi-project

The canon says "one vault, one project". Several projects in one vault are possible,
but that is a deliberate deviation with a cost: the index is read on every query,
so each new project makes every other project more expensive.

If you go multi-project, keep the top-level index clean: navigation only, no rulebooks
and no "important stuff" lists.

## License

MIT. Use it, change it, make it yours.
