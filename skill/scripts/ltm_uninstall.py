#!/usr/bin/env python3
"""Full removal of the long-term memory and every trace of the installation.

Needed first of all for testing: without a rollback the skill can be verified on
a machine exactly once, and the second attempt already runs on top of the leftovers
of the first one.

The script removes five kinds of traces:
  1. the memory itself (the folder with the `.ltm-vault` marker)
  2. `<!-- ltm:start -->` blocks in the rule files of working projects
  3. rule files created by the installer, not by a human
  4. the scheduler entry: cron, launchd or schtasks
  5. the skill in the agent directories (~/.claude/skills and others)

The main principle: do not touch what is not ours. If `CLAUDE.md` existed in the
project before us, only our block is cut out of it and the file stays. What exactly
the installer created is known from the `.ltm-install-manifest.json` manifest inside
the memory. If there is no manifest (an old installation), the script falls back to
searching by markers and says honestly that it is acting on a guess.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

MARKER_FILE = ".ltm-vault"
MANIFEST = ".ltm-install-manifest.json"
BLOCK_START = "<!-- ltm:start -->"
BLOCK_END = "<!-- ltm:end -->"

CRON_MARKER = "ltm-vault-doctor"
LAUNCHD_LABEL = "md.ltm.vault.doctor"
SCHTASKS_NAME = "LTM Vault Doctor"

RULE_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
SKILL_NAME = "ltm-vault"

# Directories where install.sh / install.ps1 put the skill.
def skill_dirs() -> list[Path]:
    home = Path.home()
    out = [
        home / ".claude" / "skills" / SKILL_NAME,
        home / ".gemini" / "skills" / SKILL_NAME,
        home / ".config" / "amp" / "skills" / SKILL_NAME,
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "amp" / "skills" / SKILL_NAME)
    return out


# Folders there is no point entering during a search: the memory is never there,
# and they eat more time than everything else combined.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".cache",
    "Library", "AppData", ".Trash", ".local", "site-packages", ".npm",
    "Applications", "snap", ".rustup", ".cargo", "go",
}


def system() -> str:
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    return "linux"


def ask_yes(prompt: str, default: bool = False) -> bool:
    d = "y/N" if not default else "Y/n"
    try:
        raw = input(f"{prompt} [{d}]: ").strip().lower()
    except EOFError:
        return default
    if not raw:
        return default
    return raw in ("y", "yes")


# --- finding the traces ------------------------------------------------------

def find_vaults(explicit: str | None, deep: bool = False) -> list[Path]:
    """Find the memory by the `.ltm-vault` marker."""
    if explicit:
        p = Path(explicit).expanduser()
        return [p] if p.is_dir() else []

    home = Path.home()
    found: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            found.append(p)

    # Fast path: the usual locations at depth 1-2.
    for base in (home, home / "Documents", home / "memory", home / "Documents" / "memory"):
        if not base.is_dir():
            continue
        try:
            for marker in base.glob(f"*/{MARKER_FILE}"):
                add(marker.parent)
            for marker in base.glob(f"*/*/{MARKER_FILE}"):
                add(marker.parent)
        except OSError:
            continue

    if deep:
        # A deep search is needed when the person put the memory off to the side.
        for root, dirs, files in os.walk(home):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                       or d == ".obsidian" and False]
            if MARKER_FILE in files:
                add(Path(root))
                dirs[:] = []  # there is no point descending into the memory
    return found


def read_manifest(vault: Path) -> dict | None:
    p = vault / MANIFEST
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def find_linked_projects(deep: bool = False) -> list[Path]:
    """Find the rule files that contain our block.

    We search by the block marker, not by the file name: `CLAUDE.md` exists in
    plenty of projects and none of them may be deleted.
    """
    home = Path.home()
    hits: list[Path] = []
    max_depth = 6 if deep else 3

    for root, dirs, files in os.walk(home):
        rel_depth = len(Path(root).relative_to(home).parts)
        if rel_depth >= max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name not in RULE_FILES:
                continue
            p = Path(root) / name
            try:
                if BLOCK_START in p.read_text(encoding="utf-8", errors="replace"):
                    hits.append(p)
            except OSError:
                continue
    return hits


def scheduler_state() -> tuple[bool, str]:
    """Whether an entry exists in the scheduler of this system."""
    s = system()
    if s == "linux":
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        text = r.stdout if r.returncode == 0 else ""
        return CRON_MARKER in text, "crontab"
    if s == "macos":
        p = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        return p.is_file(), "launchd"
    r = subprocess.run(["schtasks", "/Query", "/TN", SCHTASKS_NAME],
                       capture_output=True, text=True)
    return r.returncode == 0, "schtasks"


# --- removal -----------------------------------------------------------------

def remove_scheduler(dry: bool) -> list[str]:
    done: list[str] = []
    present, kind = scheduler_state()
    if not present:
        return done
    if dry:
        return [f"remove the {kind} entry"]

    s = system()
    if s == "linux":
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = r.stdout if r.returncode == 0 else ""
        kept = [l for l in existing.splitlines() if CRON_MARKER not in l]
        body = "\n".join(kept).strip()
        body = body + "\n" if body else ""
        w = subprocess.run(["crontab", "-"], input=body, capture_output=True, text=True)
        done.append("crontab: entry removed" if w.returncode == 0
                    else f"crontab: error, {w.stderr.strip()}")
    elif s == "macos":
        p = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LAUNCHD_LABEL}"],
                       capture_output=True, text=True)
        try:
            p.unlink()
            done.append("launchd: job removed")
        except OSError as e:
            done.append(f"launchd: error, {e}")
    else:
        r = subprocess.run(["schtasks", "/Delete", "/TN", SCHTASKS_NAME, "/F"],
                           capture_output=True, text=True)
        done.append("schtasks: job removed" if r.returncode == 0
                    else f"schtasks: error, {r.stderr.strip()}")
    return done


def strip_block(path: Path, dry: bool) -> str | None:
    """Cut our block out of someone else's rule file, keep the file itself."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"{path}: not read, {e}"
    if BLOCK_START not in text:
        return None
    start = text.index(BLOCK_START)
    try:
        end = text.index(BLOCK_END) + len(BLOCK_END)
    except ValueError:
        # No end marker: the file was edited by hand. We do not guess the boundary.
        return f"{path}: the block is damaged, remove it by hand"
    new = (text[:start].rstrip() + "\n" + text[end:].lstrip()).strip()
    new = new + "\n" if new else ""
    if dry:
        return f"cut out the block: {path}"
    try:
        if new.strip():
            path.write_text(new, encoding="utf-8")
            return f"block cut out: {path}"
        # Only the heading was left in the file: it was ours and is empty without the block.
        path.unlink()
        return f"file became empty and was deleted: {path}"
    except OSError as e:
        return f"{path}: not written, {e}"


def remove_path(p: Path, dry: bool) -> str:
    if dry:
        return f"delete: {p}"
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return f"deleted: {p}"
    except OSError as e:
        return f"NOT deleted {p}: {e}"


def count_files(p: Path) -> int:
    n = 0
    for _, _, files in os.walk(p):
        n += len(files)
    return n


# --- report ------------------------------------------------------------------

def survey(args) -> dict:
    vaults = find_vaults(args.path, deep=args.deep)
    manifests = {str(v): read_manifest(v) for v in vaults}

    # Projects come from the manifest when there is one: exact knowledge beats a search.
    linked: list[Path] = []
    from_manifest = False
    for v in vaults:
        m = manifests.get(str(v))
        if m and m.get("project_links"):
            from_manifest = True
            for item in m["project_links"]:
                p = Path(item["path"])
                if p.is_file():
                    linked.append(p)
    if not from_manifest:
        linked = find_linked_projects(deep=args.deep)

    skills = [d for d in skill_dirs() if d.is_dir()]
    sched, sched_kind = scheduler_state()
    return {
        "vaults": vaults,
        "manifests": manifests,
        "linked": sorted(set(linked)),
        "linked_from_manifest": from_manifest,
        "skills": skills,
        "scheduler": sched,
        "scheduler_kind": sched_kind,
    }


def print_survey(s: dict) -> bool:
    found_any = False
    print("What was found on this machine\n")

    if s["vaults"]:
        found_any = True
        print("Memory:")
        for v in s["vaults"]:
            m = s["manifests"].get(str(v))
            mark = "manifest present" if m else "no manifest, acting on markers"
            print(f"  {v}   files: {count_files(v)}   ({mark})")
    else:
        print("Memory: not found")

    if s["linked"]:
        found_any = True
        src = "from the manifest" if s["linked_from_manifest"] else "found by search"
        print(f"\nRule files with our block ({src}):")
        for p in s["linked"]:
            print(f"  {p}")
    else:
        print("\nRule files with our block: not found")

    if s["skills"]:
        found_any = True
        print("\nSkill in the agent directories:")
        for d in s["skills"]:
            print(f"  {d}")
    else:
        print("\nSkill in the agent directories: not found")

    print(f"\nScheduler ({s['scheduler_kind']}): "
          + ("entry present" if s["scheduler"] else "no entry"))
    if s["scheduler"]:
        found_any = True
    return found_any


def do_remove(s: dict, args) -> int:
    dry = args.dry_run
    actions: list[str] = []

    actions += remove_scheduler(dry)

    for p in s["linked"]:
        # A file created by the installer itself is deleted whole.
        # Someone else's file stays, only the block goes.
        ours = False
        for v in s["vaults"]:
            m = s["manifests"].get(str(v)) or {}
            for item in m.get("project_links", []):
                if Path(item["path"]) == p and item.get("action") == "created":
                    ours = True
        if ours:
            actions.append(remove_path(p, dry))
        else:
            r = strip_block(p, dry)
            if r:
                actions.append(r)

    for d in s["skills"]:
        actions.append(remove_path(d, dry))

    if not args.keep_vault:
        for v in s["vaults"]:
            actions.append(remove_path(v, dry))

    print()
    for a in actions:
        print(f"  {a}")
    if not actions:
        print("  nothing to remove")

    if dry:
        print("\nThat was --dry-run, nothing was changed.")
        return 0

    # A check after the work: a report is not the same as a fact.
    left = survey(args)
    rest = (len(left["vaults"]) if not args.keep_vault else 0) + len(left["linked"]) \
        + len(left["skills"]) + (1 if left["scheduler"] else 0)
    if rest:
        print(f"\nWARNING: traces left: {rest}. Run it again with --deep.")
        return 1
    print("\nClean: no traces of the installation are left.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Remove the long-term memory and every trace of the installation")
    ap.add_argument("--path", help="path to the memory, if the search does not see it")
    ap.add_argument("--survey", action="store_true",
                    help="only show what was found, change nothing")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be deleted, without deleting")
    ap.add_argument("--deep", action="store_true",
                    help="deep search across the whole home folder, slower")
    ap.add_argument("--keep-vault", action="store_true",
                    help="remove the integrations, but keep the memory itself")
    ap.add_argument("--yes", action="store_true",
                    help="no confirmation, for automated tests")
    args = ap.parse_args()

    print("Removing the long-term memory\n")
    s = survey(args)
    found = print_survey(s)

    if args.survey:
        return 0
    if not found:
        print("\nNothing to remove.")
        return 0
    if args.dry_run:
        return do_remove(s, args)

    total_files = sum(count_files(v) for v in s["vaults"]) if not args.keep_vault else 0
    print("\n" + "=" * 60)
    print("This cannot be undone. The memory is local, there is no copy.")
    if total_files:
        print(f"Memory files to be deleted: {total_files}")
    print("=" * 60)

    if not args.yes:
        # A deliberate word instead of 'y': deleting the memory is too expensive
        # to fire from an accidental keystroke.
        try:
            word = input("To confirm, type DELETE: ").strip()
        except EOFError:
            word = ""
        if word != "DELETE":
            print("Cancelled, nothing was changed.")
            return 0

    return do_remove(s, args)


if __name__ == "__main__":
    sys.exit(main())
