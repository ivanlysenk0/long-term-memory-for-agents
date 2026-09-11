#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vault synchronisation with the remote repository. Stop event hook.

Runs after every agent reply. Does three things in order:

1. marks fresh session logs as knowledge candidates
2. commits vault changes
3. pushes them to the remote

Why after EVERY reply rather than on a schedule: vault edits appear
unpredictably and the agent window can be closed at any moment. The hook
stands by and acts only when there is something to save: on a clean tree it
exits silently without touching the network.

Why candidates are marked BEFORE the commit: the queue entry must travel in
the same commit. Marking afterwards would delay it until the next agent reply,
and closing the window would lose it entirely.

Why Python and not shell: Windows has no bash, and every user needs this hook.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ltm_paths import find_vault, log_dir, state_dir  # noqa: E402

# How long to wait for the lock, seconds.
LOCK_WAIT = 30
# A lock older than this is stale: the process was killed with nobody to clean up.
LOCK_STALE = 120
# How many keyword hits are needed to mark a log as a candidate.
THRESHOLD = 3
# Signs that a log contains analysis rather than plain conversation.
TRIGGERS = [
    r"глибок\w+ аналіз", r"глубок\w+ анализ", r"deep dive",
    r"детальн\w+ розбір", r"детальн\w+ разбор",
    r"архітектур\w+", r"архитектур\w+", r"architecture",
    r"патерн", r"паттерн", r"pattern",
    r"root cause", r"корінь причини", r"корень причины",
    r"ухвалено рішення", r"принят\w+ решение", r"decision made",
    r"порівняння", r"сравнение", r"comparison",
]


def log(msg):
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = d / "ltm-sync.log"
        with p.open("a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def git(vault, *args, timeout=90):
    """Run git. Returns (code, output). Never raises."""
    try:
        r = subprocess.run(["git", *args], cwd=str(vault), capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def acquire_lock(vault):
    """Lock via mkdir: atomic on every filesystem.

    A check-then-create on a file has no such guarantee and contains a race
    of its own.
    """
    lock = vault / ".git" / "ltm-sync.lock"
    for _ in range(LOCK_WAIT):
        try:
            lock.mkdir(parents=True)
            return lock
        except FileExistsError:
            time.sleep(1)
        except Exception:
            return None
    try:
        if time.time() - lock.stat().st_mtime > LOCK_STALE:
            lock.rmdir()
            lock.mkdir()
            return lock
    except Exception:
        pass
    return None


def scout(vault):
    """Mark fresh session logs as knowledge candidates.

    The script only marks. Pages are written by the agent and the call is made
    by a human: automation cannot tell analysis from an incidental mention of
    a word, and a queue full of noise stops being read.
    """
    marked = 0
    cutoff = time.time() - 86400
    for proj in sorted(p for p in vault.iterdir() if p.is_dir()):
        sessions = proj / "sessions"
        home = proj / "00-home"
        if not sessions.is_dir() or not home.is_dir():
            continue
        queue = home / "pending-concepts.md"
        seen = queue.read_text(encoding="utf-8", errors="ignore") if queue.is_file() else ""
        for f in sorted(sessions.glob("*.md")):
            try:
                if f.stat().st_mtime < cutoff or f.stem in seen:
                    continue
                body = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            hits = [t for t in TRIGGERS if re.search(t, body, re.I)]
            if len(hits) < THRESHOLD:
                continue
            entry = (
                "\n### %s\n"
                "- Session: [[%s/sessions/%s|%s]]\n"
                "- Keyword hits: %d\n"
                "- Status: pending\n"
                "- Action: extract concept(s) into knowledge/<category>/, "
                "update index.md and log.md\n"
                % (datetime.now().strftime("%Y-%m-%d %H:%M"),
                   proj.name, f.name, f.stem, len(hits))
            )
            try:
                if not queue.is_file():
                    queue.write_text(
                        "---\ntitle: \"Knowledge candidates\"\n"
                        "type: pending-queue\nstatus: active\n---\n\n"
                        "# Knowledge candidates\n\n"
                        "Entries with status `pending` await compilation.\n",
                        encoding="utf-8")
                with queue.open("a", encoding="utf-8") as fh:
                    fh.write(entry)
                seen += f.stem
                marked += 1
            except Exception:
                continue
    return marked


def main():
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    vault = find_vault()
    if vault is None or not (vault / ".git").is_dir():
        return 0

    lock = acquire_lock(vault)
    if lock is None:
        log("skipped: sync already running in another process")
        return 0

    try:
        marked = scout(vault)
        if marked:
            log("concept_scout: candidates marked: %d" % marked)

        code, out = git(vault, "status", "--porcelain")
        if code != 0 or not out:
            return 0
        files = len(out.splitlines())

        git(vault, "add", "-A")
        rc, _ = git(vault, "commit", "-m", "auto vault sync")
        if rc != 0:
            return 0

        # Expanded pull: the rebase target is a branch NAME, not the
        # .git/FETCH_HEAD file. Otherwise a parallel fetch from another process
        # rewrites FETCH_HEAD with every branch and rebase fails with
        # "Cannot rebase onto multiple branches".
        branch = git(vault, "rev-parse", "--abbrev-ref", "HEAD")[1] or "main"
        fail = None
        rc, out = git(vault, "fetch", "--quiet", "origin", branch)
        if rc == 0:
            rc, out = git(vault, "rebase", "--autostash", "origin/%s" % branch)
            if rc != 0:
                fail = "rebase: %s" % out.splitlines()[0][:90] if out else "rebase"
        else:
            fail = "fetch: %s" % out.splitlines()[0][:90] if out else "fetch"

        if fail is None:
            rc, out = git(vault, "push", "origin", branch)
            if rc != 0:
                fail = "push: %s" % out.splitlines()[0][:90] if out else "push"

        alert = state_dir() / "sync-alert.txt"
        if fail:
            log("SYNC FAILED (%s), files %d" % (fail, files))
            try:
                alert.parent.mkdir(parents=True, exist_ok=True)
                with alert.open("a", encoding="utf-8") as f:
                    f.write("%s | %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M"), fail))
            except Exception:
                pass
        else:
            log("ok: committed and pushed, files %d" % files)
            try:
                alert.unlink()
            except Exception:
                pass
    finally:
        try:
            lock.rmdir()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("ERROR: %s" % e)
        sys.exit(0)
