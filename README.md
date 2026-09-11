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
git clone https://github.com/ivanlysenk0/long-term-memory-for-agents.git
cd long-term-memory-for-agents
./install.sh
```

Windows, PowerShell:

```powershell
git clone https://github.com/ivanlysenk0/long-term-memory-for-agents.git
cd long-term-memory-for-agents
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
    ├── ltm_doctor.py     health check for the vault
    ├── ltm_schedule.py   runs the check on a schedule
    ├── ltm_seed.py       hand ready-made memory content to another person
    └── ltm_uninstall.py  full removal of the memory and install traces
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

# pack memory content into an encrypted file for a teammate
python3 skill/scripts/ltm_seed.py --pack team.ltmseed --projects infra,qa

# merge such a file into your own memory
python3 skill/scripts/ltm_seed.py --unpack team.ltmseed --dry-run
```

## Health check

`ltm_doctor.py` runs ten checks in about a second over 500 files:

- missing or incomplete YAML frontmatter
- malformed dates
- broken wiki-links, including ones that **look** valid
- wrong case in a project name: `[[my-proj/log]]` when the directory is `My_Proj`
- relative `../` paths, which Obsidian does not resolve
- duplicate page names
- orphan pages with no inbound link
- stubs with no content
- sessions whose knowledge has not been compiled yet
- scripts in the memory that fell behind the skill version

Schedule it with one command:

```bash
python3 skill/scripts/ltm_schedule.py
```

Default: **weekdays, 12:00**, weekends skipped. The script detects your OS and asks
for confirmation before writing anything: Linux `cron`, macOS `launchd`,
Windows `schtasks`.

```bash
python3 skill/scripts/ltm_schedule.py --hour 9      # different time
python3 skill/scripts/ltm_schedule.py --everyday    # weekends too
python3 skill/scripts/ltm_schedule.py --status      # what is scheduled now
python3 skill/scripts/ltm_schedule.py --remove      # remove it
```

## Handing memory to another person

`ltm_seed.py` packs memory content into a single encrypted file and merges it
into someone else's memory. Use it when a newcomer should start with the team's
accumulated knowledge instead of an empty structure.

```bash
# owner: pack
python3 skill/scripts/ltm_seed.py --pack team.ltmseed --projects infra,qa

# teammate: see what would happen, change nothing
python3 skill/scripts/ltm_seed.py --unpack team.ltmseed --dry-run

# teammate: merge
python3 skill/scripts/ltm_seed.py --unpack team.ltmseed
```

**What to include.** Without `--projects` the whole memory is packed, personal
content included. The rule is simple: list projects explicitly, and only
work-related ones. Health, money, family and relocation projects never go into
a seed. Review the file list printed by `--pack` before sending.

**Never archived** regardless of your choice: `.git` (it holds the full history,
including things that were deleted once), `.obsidian`, caches, logs and the
`.ltm-vault` marker.

**Nothing is overwritten.** If a file already exists on the other side and
differs, the seed version lands next to it with a `.seed.md` suffix and the
human decides. The vault doctor skips those files, so they do not break checks.

**Encryption:** the key comes from the password via scrypt, the data via
AES-256-GCM. GCM is deliberate: it detects a tampered file, not just hides the
content. Send the password over a separate channel, never with the file. Access
cannot be revoked once the file is handed over.

## Updating to a new version

The memory and the scripts are updated separately. Two different steps.

**Step 1, the skill in the agent directory.** A repeat install is the update:

```bash
cd long-term-memory-for-agents
git pull
./install.sh          # Windows: powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Restart the agent afterwards, otherwise it keeps the old `SKILL.md` in process memory.

**Step 2, the scripts inside the memory itself.** The installer deliberately
leaves them alone: it is idempotent and overwrites nothing, so `<vault>/scripts/`
stays on whatever version you started with. There is a separate mode for that:

```bash
python3 skill/scripts/ltm_init.py --update
python3 skill/scripts/ltm_init.py --update --path ~/memory/long-term-memory-vault
python3 skill/scripts/ltm_init.py --version    # which version is installed now
```

`--update` rewrites only the four executable files in `<vault>/scripts/`:
the doctor, the scheduler, seed and uninstall. The structure, `knowledge/`,
the rule files and any text of yours stay untouched. It prints the file list
and asks for confirmation before writing, then runs the doctor right after.

The same thing is in the menu without flags: option 2 when you run `ltm_init.py`.

**How you learn it is time.** The doctor compares the version in the manifest
with its own and warns when they drift apart:

```
Scripts: 1.0.0 in the memory, 1.1.0 in the skill. Update: ltm_init.py --update --path <vault>
```

The line is printed in `--quiet` too, because the scheduled run is the quiet one.
The version lives in `.ltm-install-manifest.json`, field `scripts_version`.
If the memory was installed before versions existed the field is empty: that is
expected, the first `--update` fills it in.

## Removal: put the machine back as it was

The installer asks this first: install, or remove everything it put in place.
This exists mainly for testing on different systems, because without a rollback
the skill is tested on a machine exactly once.

```bash
python3 skill/scripts/ltm_uninstall.py --survey     # show what was found
python3 skill/scripts/ltm_uninstall.py --dry-run    # what would be removed
python3 skill/scripts/ltm_uninstall.py              # remove
python3 skill/scripts/ltm_uninstall.py --keep-vault # drop integrations, keep the memory
```

Everything goes: the memory, the blocks in project rule files, the scheduler
entry, the skill in the agent directories.

**Your own files survive.** If `CLAUDE.md` existed in the project before the
install, only the memory block is cut out and your text stays. What the installer
created is recorded in a manifest inside the memory.

The action cannot be undone, so you type the word `DELETE`. There is no second
copy of the memory.

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
