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
| `ltm_doctor.py` | health check: 10 checks, ~1 second per 500 files |
| `ltm_hooks.py` | Claude Code hooks: memory loads and saves itself |
| `ltm_schedule.py` | puts the check on a schedule: cron, launchd or Windows Scheduler |
| `ltm_seed.py` | hands ready-made memory content to another person, as an encrypted file |
| `ltm_uninstall.py` | removes the memory and every trace of the install, for repeat testing |
| `ltm_version.py` | three versions at once: skill, memory, GitHub. Step 0 before any work |


## Claude Code hooks

Without hooks the vault is just a folder: the agent starts from zero every
session and everything said is lost when the context is compacted.

```
python3 scripts/ltm_hooks.py --status     what is installed now
python3 scripts/ltm_hooks.py --dry-run    plan, no changes
python3 scripts/ltm_hooks.py --install    install
python3 scripts/ltm_hooks.py --uninstall  remove only our hooks
```

| Event | What it does |
|-------|--------------|
| `SessionStart` | loads memory into context; after compaction returns the dump |
| `PreCompact` | saves the conversation before the context is compacted |

| `Stop` | marks knowledge candidates, commits and pushes the vault |

`Stop` is installed only when the vault is under git.

What `Stop` does, in order: it scans fresh session logs for signs of analysis
(architecture, pattern, root cause, decision made, comparison) and on three
hits appends a candidate to `pending-concepts.md`, then commits and pushes.
It writes no pages: those are composed by the agent and the call is made by a
human. On a clean tree the hook exits silently without touching the network.

**Saving a session stays with the human.** Hooks load memory and keep the raw
material safe, but what deserves `knowledge/` is decided by a person asking to
save the session. `SessionEnd` is deliberately not installed: it only fires on
an explicit end, duplicates `PreCompact`, and contradicts Karpathy's method.

Other people's hooks on the same events are left alone, and `settings.json` is
backed up before any change. Hooks are read at session start: open a new session
after installing.

**Saving a session stays with the human.** `SessionEnd` only fires on an explicit
end (`/clear`, `/resume`, quitting the app). If someone simply stops typing and
leaves the window open, the event never fires. So the main path is asking
"save the session", and the hook is only a safety net.

Hooks do not decide what deserves `knowledge/` and never write pages there: a
script cannot understand a conversation. It keeps the raw material and reminds.

## Workflow

### 0. Version check, BEFORE any work with the memory

The first thing you do when this skill opens. Do not skip it: the skill lives in
three places and they drift apart unnoticed.

```bash
python3 scripts/ltm_version.py --json
```

The script finds the memory itself and returns three versions: the skill on
disk, the scripts inside the memory, and the fresh version from GitHub. The
network is optional: with no internet `remote` is `null`, and that is not a blocker.

What to do with the answer:

- `remote_drift: true`: a newer version exists in the repository. **Stop and tell
  the person**, do not start working silently. In substance: "Your memory was
  deployed by version X, the repository is already at Y. The current setup
  differs from what the new version installs. Update now?"
- `local_drift: true`: the scripts in the memory fell behind the skill. Same
  question, no network involved.
- both `false`: carry on, ask nothing.

Once the person agrees you do it yourself, in exactly this order:

```bash
cd <repo clone> && git pull && ./install.sh                     # 1. the skill
python3 scripts/ltm_init.py --update  --path <vault>            # 2. the scripts
python3 scripts/ltm_init.py --migrate --path <vault> --dry-run  # 3. show
python3 scripts/ltm_init.py --migrate --path <vault>            # 4. apply
```

Step 3 is mandatory and you show its output to the person BEFORE step 4.

**Be honest about the limit.** The skill text is already in your context, and
after `git pull` you still remember the old revision in this same session.
Re-read `SKILL.md` from disk. If the workflow itself changed, say plainly
"restart the session" instead of pretending everything was picked up.

**Declining is a valid answer.** The person may say "work as is". Then you work
with the current version and do not raise it again in this session.

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

### Scheduling

Do not leave scheduling to the user: the advice "add a line to crontab" never
gets followed. Set it up right away, but **only with explicit consent**: this
changes the system, not just the vault.

```bash
python3 scripts/ltm_schedule.py              # weekdays, 12:00, asks for confirmation
python3 scripts/ltm_schedule.py --hour 9     # different time
python3 scripts/ltm_schedule.py --everyday   # weekends too
python3 scripts/ltm_schedule.py --status     # what is scheduled now
python3 scripts/ltm_schedule.py --remove     # remove it
```

The mechanism follows the OS: Linux `cron`, macOS `launchd`, Windows `schtasks`.
macOS uses `launchd` because cron is technically present there but Apple does not
recommend it, and under privacy protection it fails silently.

The installer offers scheduling itself, after the self-check passes. The
`--schedule` and `--no-schedule` flags control it without prompting.

### 7. Filling memory with ready-made content

An empty memory is useless to a newcomer: the agent reads the structure and finds
nothing in it. `ltm_seed.py` solves that by shipping the content as one encrypted
parcel.

```bash
python3 scripts/ltm_seed.py --pack team.ltmseed --projects infra,qa   # owner side
python3 scripts/ltm_seed.py --unpack team.ltmseed --dry-run           # teammate, preview
python3 scripts/ltm_seed.py --unpack team.ltmseed                     # teammate, merge
```

**The human picks the content, not you.** Without `--projects` the whole memory
is packed, personal content included. Never build a seed without an explicit
project list and without showing that list to the owner. Health, money, family
and document projects never go into a seed.

**Always `--dry-run` first.** It prints what would be added and where a conflict
appears, and writes nothing.

**Merging never overwrites.** The existing file stays, the seed version lands
next to it with a `.seed.md` suffix. A human decides from there, not the agent.
The doctor skips those files, so the check does not break.

**Password over a separate channel.** And say it plainly: once handed over,
access cannot be revoked, the file is already in someone else's hands. That is
not an implementation limit, it is a property of handing over any file.

The installer offers a seed after a successful self-check. The `--seed` and
`--no-seed` flags control this without prompting.

### 9. Removal: put the machine back as it was

The installer asks this first, before detection:

```
What do you want to do?
  1. Install or update the memory
  2. Remove everything this skill installed
```

The second branch exists mainly to test the skill on different systems. Without
a rollback the skill is tested on a machine exactly once, and the second attempt
runs on top of the leftovers of the first, so it is unclear what you are testing.

```bash
python3 scripts/ltm_uninstall.py --survey     # show what was found, change nothing
python3 scripts/ltm_uninstall.py --dry-run    # what would be removed
python3 scripts/ltm_uninstall.py              # remove, with a confirmation word
python3 scripts/ltm_uninstall.py --deep       # if the memory sits in an unusual place
python3 scripts/ltm_uninstall.py --keep-vault # drop integrations, keep the memory
```

Five kinds of traces are removed: the memory itself, `<!-- ltm:start -->` blocks
in project rule files, rule files created by the installer, the scheduler entry,
and the skill in the agent directories.

**Other people's files are left alone.** If `CLAUDE.md` existed in the project
before the install, only our block is cut out and the file keeps its own text.
The manifest `.ltm-install-manifest.json` inside the memory tells them apart:
the installer records what it created and what it merely appended to.

If there is no manifest, the script searches by the block marker and says plainly
that it is acting on markers. It does not delete rule files in that case: without
a manifest there is no way to prove a file is ours.

**Confirmation by word, not by letter.** Deleting a memory is too expensive to
fire from a stray keypress, so the user types `DELETE`. Use `--yes` for automated
tests.

When done, the script checks itself with a second search: if anything is left,
it exits with code 1 and suggests running with `--deep`.

## Updating a user who already has the skill

Two layers, two different commands. Do not mix them up.

**Layer 1, the skill in the agent directory.** `git pull` in the repository clone,
then `./install.sh`. The installer does `cp -R`, i.e. it overwrites, so no separate
update command exists. Restart the agent afterwards.

**Layer 2, the scripts inside the memory.** The install deliberately does NOT
update them: it is idempotent, and `write_once` / `install_doctor` skip an
existing file. There is a separate mode for it:

```
python3 ltm_init.py --update                       default path
python3 ltm_init.py --update --path <vault>        explicit path
python3 ltm_init.py --update --path <vault> --yes  no confirmation
python3 ltm_init.py --version --path <vault>       compare versions
```

Exactly four files in `<vault>/scripts/` get rewritten: `ltm_doctor.py`,
`ltm_schedule.py`, `ltm_seed.py`, `ltm_uninstall.py`. Nothing else is touched:
not the structure, not `knowledge/`, not the rule files, not any text. The list
is printed and confirmed before writing, and the doctor runs right after.

**The version lives in the manifest**, field `scripts_version` in
`.ltm-install-manifest.json`. The doctor compares it with its own and warns on
a mismatch; the line shows up in `--quiet` as well. A memory installed before
versions existed has no such field: that is not an error, the first `--update`
fills it in.

**The typical case for an old install:** `ltm_uninstall.py` is missing from
`<vault>/scripts/` entirely, because it was added later, and the doctor is a
month old. One `--update` covers both.

**Layer 3, the structure and rules inside the memory.** The most important and
the least visible one. The rules file in the memory root defines HOW the agent
works with the records, and the install never updates it.

```
python3 ltm_init.py --migrate --path <vault> --dry-run   always first
python3 ltm_init.py --migrate --path <vault>             apply
```

- adds files that old installs never had
- rewrites the rules file only if the person never edited it: checked against
  the `rules_hash` fingerprint in the manifest, not guessed
- in a memory installed before fingerprints existed there is nothing to judge by.
  The script then says "rules from an older version, whether you edited them is
  unknown" and touches nothing: it drops a `.new` next to it and suggests a
  `diff`. Never tell the person "you edited this by hand" with no fingerprint:
  that would be a lie
- leaves an edited file alone, placing the new version next to it as `.new`
- never touches `knowledge/`, `sessions/`, `Raw/`

**Never suggest "wipe the memory and reinstall".** `ltm_uninstall.py` is for
testing on a clean machine, not for updating: it deletes the person's records.
Updating always happens in place.

## What the skill writes into working projects

The single most important text in the skill. The agent is opened inside a
working project, not inside the store, so it will never see a rules file sitting
in the store root. Everything needed has to be in the block that lands in the
project's own `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`.

The block follows Karpathy's canon: three layers and three operations.

| What | Why |
|------|-----|
| Raw layer | `<project>/Raw/` is written by the human only; the agent reads, never edits |
| Wiki layer | `knowledge/`, `00-home/` are maintained by the agent |
| Schema layer | the block itself and `00-home/operations.md` |
| Query operation | an answer starts at the project's `index.md`, not at a guess |
| Ingest operation | raw material -> key points -> **pause and approval** -> pages |
| Lint operation | orphans, broken links, stubs, stale claims |
| Query -> Save | exactly what must be saved and what must not |
| `index.md` | updated **the moment** a page is created, not at session end |
| wiki links | path from the store root, `../` forbidden |

**The block language is detected automatically** from the project's existing
rule file: Ukrainian, Russian or English. The person already answered that
question when they wrote their `CLAUDE.md`; asking twice is pointless.

**The store directory name is matched, not guessed.** On disk the project may be
`Sky-Kids-SMM-bot` while the store calls it `sky-kids-smm-bot`. The canon does
not require identical names, so the skill matches ignoring case and separators,
and asks the human when there is no unambiguous match.

## Entry point: one project or several

| Projects | Entry point | Why |
|----------|-------------|-----|
| one | `index.md` at the root | Karpathy's canon; no `00-global-home` is created |
| several | `00-global-home/master-index.md` | a level above per-project indexes is needed |

The master index must not also be called `index.md`: projects have their own
`index.md`, and two different files sharing a name confuse agent and human alike.

An existing entry point always wins over the calculation: renaming it would
break every link pointing at it.

## Boundaries: what the skill never does

- **`--yes` does not wire projects.** It means "do not ask me about my own
  memory", not "edit files I never named". Touching someone else's files always
  requires an explicit `--link`
- **A memory in a temporary directory is never written into real projects.**
  A `/tmp` path disappears on reboot while the instruction "the memory lives
  here" stays forever
- **After install the written paths are verified.** A block can land
  successfully yet point at nothing; the self-check then reports FAIL, not "done"

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
