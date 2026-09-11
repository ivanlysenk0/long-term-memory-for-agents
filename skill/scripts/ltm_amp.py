#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install the long-term memory plugin into Amp.

An Amp plugin is not the same thing as a Claude Code hook, hence a separate
installer. The key differences that ruled out shared code:

- a plugin is a directory, not a line in a settings file
- it needs the vault scripts next to it, in a `scripts/` subdirectory
- Amp has no context-compaction event, so `PreCompact` is not installed here

Install location (per Amp documentation):
    $XDG_CONFIG_HOME/amp/plugins/   when the variable is set
    ~/.config/amp/plugins/          macOS and Linux
    %USERPROFILE%\\.config\\amp\\plugins\\  Windows

Modes: --status, --dry-run, --install, --uninstall.
"""
import os
import shutil
import sys
from pathlib import Path

NAME = "ltm-vault"
# Scripts without which the plugin is useless. ltm_precompact.py is not
# needed: Amp has no context-compaction event.
SCRIPTS = ["ltm_paths.py", "ltm_session_start.py", "ltm_sync.py", "ltm_doctor.py"]


def plugins_dir():
    """Amp system plugins directory."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "amp" / "plugins"
    if os.name == "nt":
        return Path(os.environ.get("USERPROFILE", Path.home())) / ".config" / "amp" / "plugins"
    return Path.home() / ".config" / "amp" / "plugins"


def source_dir():
    """Skill directory: source of both the plugin and the scripts."""
    return Path(__file__).resolve().parent.parent


def status():
    target = plugins_dir() / NAME
    print("Amp plugins directory: %s" % plugins_dir())
    if not target.is_dir():
        print("Memory plugin: not installed")
        return 0
    print("Memory plugin: installed at %s" % target)
    missing = [s for s in SCRIPTS if not (target / "scripts" / s).is_file()]
    if missing:
        print("  MISSING scripts: %s" % ", ".join(missing))
    else:
        print("  scripts present: %d" % len(SCRIPTS))
    return 0


def install(dry):
    src = source_dir()
    plugin_src = src / "amp-plugin" / "index.ts"
    if not plugin_src.is_file():
        print("Plugin file not found: %s" % plugin_src)
        return 1

    missing = [s for s in SCRIPTS if not (src / "scripts" / s).is_file()]
    if missing:
        print("Scripts not found: %s" % ", ".join(missing))
        return 1

    target = plugins_dir() / NAME
    print("From: %s" % (src / "amp-plugin"))
    print("To:   %s" % target)
    print("")
    print("Planned changes:")
    print("  %s index.ts" % ("update" if (target / "index.ts").is_file() else "add"))
    for s in SCRIPTS:
        exists = (target / "scripts" / s).is_file()
        print("  %s scripts/%s" % ("update" if exists else "add", s))

    if dry:
        print("")
        print("This is a preview. Nothing was changed.")
        print("Repeat with --install to apply.")
        return 0

    (target / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(plugin_src, target / "index.ts")
    for s in SCRIPTS:
        shutil.copy2(src / "scripts" / s, target / "scripts" / s)

    print("")
    print("Done. The plugin loads when Amp starts: restart it")
    print("or run `plugins: reload` from the command palette.")
    print("Verify with: `amp plugins list`")
    return 0


def uninstall(dry):
    target = plugins_dir() / NAME
    if not target.is_dir():
        print("Plugin is not installed, nothing to remove.")
        return 0
    print("Directory to be removed: %s" % target)
    if dry:
        print("This is a preview. Nothing was changed.")
        return 0
    shutil.rmtree(target)
    print("Removed. The vault itself is untouched: it is data, not installer files.")
    return 0


def main():
    args = set(sys.argv[1:])
    if "--install" in args:
        return install(False)
    if "--uninstall" in args:
        return uninstall("--dry-run" in args)
    if "--dry-run" in args:
        return install(True)
    if "--status" in args or not args:
        return status()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
