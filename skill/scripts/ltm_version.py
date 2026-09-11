#!/usr/bin/env python3
"""
ltm_version.py - show three versions at once: skill, memory, repository.

Why. The skill lives in three places and they drift apart unnoticed:
the skill files in the agent directory, the scripts inside the memory, and the
fresh code on GitHub. The agent runs this BEFORE working with the memory, so it
does not silently operate on stale rules.

Usage:
    python3 ltm_version.py                   human readable
    python3 ltm_version.py --json            machine readable, for the agent
    python3 ltm_version.py --vault PATH      explicit path to the memory
    python3 ltm_version.py --offline         do not touch the network
    python3 ltm_version.py --timeout 3       different timeout, 5s by default

Exit codes:
    0  everything matches, or only the remote version differs
    2  local versions drifted apart: time to update
    0  network unreachable. That is NOT an error: working offline is fine

The network is optional. No internet, no problem: the script quietly works off
the local versions and says so plainly.
"""

from __future__ import annotations

__version__ = "1.1.0"

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

MANIFEST = ".ltm-install-manifest.json"

# Both official repositories. We check them both: the person may have installed
# either one.
REMOTES = {
    "en": "https://raw.githubusercontent.com/ivanlysenk0/long-term-memory-for-agents/main/VERSION",
    "uk": "https://raw.githubusercontent.com/ivanlysenk0/long-term-memory-vault-kit/main/VERSION",
}


def skill_version() -> str:
    """Version of the skill currently sitting next to this script."""
    # First the VERSION file at the repository root, if run from a clone.
    here = Path(__file__).resolve().parent
    for cand in (here.parent.parent / "VERSION", here.parent / "VERSION"):
        if cand.is_file():
            try:
                v = cand.read_text(encoding="utf-8").strip()
                if v:
                    return v
            except OSError:
                pass
    # Otherwise take it from the neighbouring ltm_init.py: it is always there.
    init = here / "ltm_init.py"
    if init.is_file():
        try:
            for line in init.read_text(encoding="utf-8").splitlines()[:40]:
                if line.startswith("__version__"):
                    return line.split('"')[1]
        except (OSError, IndexError):
            pass
    return __version__


def find_vault(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_dir() else None
    env = os.environ.get("LTM_VAULT")
    if env and Path(env).expanduser().is_dir():
        return Path(env).expanduser()
    for c in (Path.home() / "long-term-memory-vault",
              Path.home() / "memory" / "long-term-memory-vault"):
        if c.is_dir():
            return c
    return None


def vault_version(vault: Path | None) -> str | None:
    if not vault:
        return None
    p = vault / MANIFEST
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    v = data.get("scripts_version") if isinstance(data, dict) else None
    return v if isinstance(v, str) else None


def remote_version(timeout: float = 5.0) -> tuple[str | None, str | None]:
    """Fresh version from GitHub. Returns (version, failure reason).

    The network is optional here, so any error is not an exception but simply
    "unknown". The agent must carry on rather than crash.
    """
    last = None
    for name, url in REMOTES.items():
        try:
            with urlopen(url, timeout=timeout) as r:
                v = r.read(64).decode("utf-8", "replace").strip()
                if v:
                    return v, None
        except (URLError, HTTPError, OSError, ValueError) as e:
            last = f"{name}: {e.__class__.__name__}"
    return None, last or "unknown reason"


def parse(v: str | None) -> tuple:
    """Version as a tuple of numbers, so 1.10.0 and 1.9.0 compare correctly."""
    if not v:
        return ()
    out = []
    for part in v.split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Versions of the skill, the memory and the repo")
    ap.add_argument("--vault", help="path to the memory")
    ap.add_argument("--json", action="store_true", help="machine readable output")
    ap.add_argument("--offline", action="store_true", help="do not touch the network")
    ap.add_argument("--timeout", type=float, default=5.0, help="network timeout, seconds")
    args = ap.parse_args()

    vault = find_vault(args.vault)
    skill = skill_version()
    inmem = vault_version(vault)
    remote, why = (None, "disabled by --offline") if args.offline \
        else remote_version(args.timeout)

    local_drift = bool(vault) and inmem != skill
    remote_drift = bool(remote) and parse(remote) > parse(skill)

    # What to do: a single action, not a list of options.
    if remote_drift:
        action = ("A newer version exists in the repository. Update the skill first: "
                  "git pull and ./install.sh, then --update and --migrate.")
    elif local_drift:
        action = (f"The scripts in the memory fell behind. Update: "
                  f"ltm_init.py --update --path {vault} , then "
                  f"ltm_init.py --migrate --path {vault} --dry-run")
    else:
        action = "Everything is current, you can start working."

    if args.json:
        print(json.dumps({
            "skill": skill,
            "vault": str(vault) if vault else None,
            "vault_version": inmem,
            "remote": remote,
            "remote_error": why,
            "local_drift": local_drift,
            "remote_drift": remote_drift,
            "action": action,
        }, ensure_ascii=False, indent=2))
        return 2 if local_drift or remote_drift else 0

    print("=== Versions ===")
    print(f"  skill on disk:      {skill}")
    print(f"  memory:             {inmem or 'no stamp'}"
          + (f"   ({vault})" if vault else "   (memory not found)"))
    if remote:
        print(f"  repository:         {remote}")
    else:
        print(f"  repository:         unknown ({why})")
        print("  the network is optional: the local check still works")
    print()
    print(action)
    return 2 if local_drift or remote_drift else 0


if __name__ == "__main__":
    sys.exit(main())
