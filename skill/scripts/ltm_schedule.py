#!/usr/bin/env python3
"""Put the memory doctor on a schedule.

Three systems, three different mechanisms. The script detects the system itself:
  - Linux  -> cron via crontab
  - macOS  -> launchd, because cron formally exists there, but Apple does not
             recommend it and it silently fails under privacy protection
             (Full Disk Access)
  - Windows -> Schtasks

Default: weekdays, 12:00, no weekends.
Nothing is installed without explicit consent from the user.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

MARKER = "ltm-vault-doctor"
DEFAULT_HOUR = 12
DEFAULT_MINUTE = 0


def system() -> str:
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s == "windows":
        return "windows"
    return "linux"


def python_exe() -> str:
    return sys.executable or "python3"


# --- Linux: cron -------------------------------------------------------------

def cron_line(doctor: Path, hour: int, minute: int, weekdays: bool) -> str:
    log = doctor.parent / "doctor.log"
    days = "1-5" if weekdays else "*"
    return (f'{minute} {hour} * * {days} "{python_exe()}" "{doctor}" --all --quiet '
            f'>> "{log}" 2>&1  # {MARKER}')


def cron_current() -> str:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    # Порожній crontab повертає код 1: це не помилка, просто нічого немає.
    return r.stdout if r.returncode == 0 else ""


def cron_install(doctor: Path, hour: int, minute: int, weekdays: bool) -> tuple[bool, str]:
    if not shutil_which("crontab"):
        return False, ("crontab not found. Install cron:\n"
                       "  Ubuntu/Debian: sudo apt install cron\n"
                       "  Fedora:        sudo dnf install cronie\n"
                       "  Arch:          sudo pacman -S cronie")
    existing = cron_current()
    kept = [l for l in existing.splitlines() if MARKER not in l]
    kept.append(cron_line(doctor, hour, minute, weekdays))
    body = "\n".join(kept).strip() + "\n"
    r = subprocess.run(["crontab", "-"], input=body, capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"crontab returned an error: {r.stderr.strip()}"
    return True, "schedule written to crontab"


def cron_remove() -> tuple[bool, str]:
    existing = cron_current()
    if MARKER not in existing:
        return True, "there was no entry in crontab"
    kept = [l for l in existing.splitlines() if MARKER not in l]
    body = ("\n".join(kept).strip() + "\n") if kept else ""
    r = subprocess.run(["crontab", "-"], input=body, capture_output=True, text=True)
    return (r.returncode == 0), ("entry removed" if r.returncode == 0 else r.stderr.strip())


# --- macOS: launchd ----------------------------------------------------------

LABEL = "md.ltm.vault.doctor"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_body(doctor: Path, hour: int, minute: int, weekdays: bool) -> str:
    log = doctor.parent / "doctor.log"
    if weekdays:
        # Weekday 1..5 це понеділок..п'ятниця. Кожен день окремим словником.
        cal = "\n".join(
            f"""        <dict>
            <key>Weekday</key><integer>{d}</integer>
            <key>Hour</key><integer>{hour}</integer>
            <key>Minute</key><integer>{minute}</integer>
        </dict>""" for d in range(1, 6))
        cal_block = f"    <key>StartCalendarInterval</key>\n    <array>\n{cal}\n    </array>"
    else:
        cal_block = (f"    <key>StartCalendarInterval</key>\n    <dict>\n"
                     f"        <key>Hour</key><integer>{hour}</integer>\n"
                     f"        <key>Minute</key><integer>{minute}</integer>\n    </dict>")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe()}</string>
        <string>{doctor}</string>
        <string>--all</string>
        <string>--quiet</string>
    </array>
{cal_block}
    <key>StandardOutPath</key><string>{log}</string>
    <key>StandardErrorPath</key><string>{log}</string>
    <key>RunAtLoad</key><false/>
</dict>
</plist>
"""


def launchd_install(doctor: Path, hour: int, minute: int, weekdays: bool) -> tuple[bool, str]:
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(plist_body(doctor, hour, minute, weekdays), encoding="utf-8")
    uid = os.getuid()
    # bootout може впасти, якщо агент ще не завантажений: це нормально.
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
                   capture_output=True, text=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(p)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # Старіші macOS не знають bootstrap, там працює load.
        r2 = subprocess.run(["launchctl", "load", "-w", str(p)],
                            capture_output=True, text=True)
        if r2.returncode != 0:
            return False, f"launchctl rejected the job: {r.stderr.strip() or r2.stderr.strip()}"
    return True, f"launchd job written: {p}"


def launchd_remove() -> tuple[bool, str]:
    p = plist_path()
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True, text=True)
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True, text=True)
    if p.is_file():
        p.unlink()
        return True, "launchd job removed"
    return True, "there was no launchd job"


# --- Windows: schtasks -------------------------------------------------------

TASK_NAME = "LTM Vault Doctor"


def schtasks_install(doctor: Path, hour: int, minute: int, weekdays: bool) -> tuple[bool, str]:
    when = f"{hour:02d}:{minute:02d}"
    if weekdays:
        args = ["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI"]
    else:
        args = ["/SC", "DAILY"]
    cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/TR",
           f'"{python_exe()}" "{doctor}" --all --quiet',
           *args, "/ST", when, "/F"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"schtasks returned an error: {(r.stderr or r.stdout).strip()}"
    return True, f"Windows task created: {TASK_NAME}"


def schtasks_remove() -> tuple[bool, str]:
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                       capture_output=True, text=True)
    return True, ("task removed" if r.returncode == 0 else "there was no task")


# --- допоміжне ---------------------------------------------------------------

def shutil_which(name: str) -> str | None:
    from shutil import which
    return which(name)


def find_doctor(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            return p
        if (p / "scripts" / "ltm_doctor.py").is_file():
            return p / "scripts" / "ltm_doctor.py"
        return None
    # Маркер .ltm-vault лишає установник, тому пам'ять знаходиться однозначно.
    for base in [Path.home(), Path.home() / "Documents"]:
        try:
            for marker in base.glob("*/.ltm-vault"):
                d = marker.parent / "scripts" / "ltm_doctor.py"
                if d.is_file():
                    return d
        except OSError:
            continue
    return None


def ask_yes(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        a = input(f"{prompt} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not a:
        return default
    return a in ("y", "yes")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Put the memory doctor on a schedule")
    ap.add_argument("--path", help="path to the memory or to ltm_doctor.py")
    ap.add_argument("--hour", type=int, default=DEFAULT_HOUR, help="hour, 0-23")
    ap.add_argument("--minute", type=int, default=DEFAULT_MINUTE, help="minute, 0-59")
    ap.add_argument("--everyday", action="store_true", help="every day, not only on weekdays")
    ap.add_argument("--remove", action="store_true", help="remove the schedule")
    ap.add_argument("--status", action="store_true", help="show the current state")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = ap.parse_args()

    sysname = system()

    if a.remove:
        ok, msg = ({"linux": cron_remove, "macos": launchd_remove,
                    "windows": schtasks_remove}[sysname])()
        print(msg)
        return 0 if ok else 1

    if a.status:
        if sysname == "linux":
            print("crontab:", "entry present" if MARKER in cron_current() else "no entry")
        elif sysname == "macos":
            print("launchd:", "job present" if plist_path().is_file() else "no job")
        else:
            r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME],
                               capture_output=True, text=True)
            print("schtasks:", "task present" if r.returncode == 0 else "no task")
        return 0

    doctor = find_doctor(a.path)
    if not doctor:
        print("ltm_doctor.py not found. Give the path: --path /path/to/memory")
        return 1

    if not (0 <= a.hour <= 23 and 0 <= a.minute <= 59):
        print("Invalid time.")
        return 1

    weekdays = not a.everyday
    days_label = "Monday to Friday" if weekdays else "every day"
    mech = {"linux": "cron", "macos": "launchd", "windows": "Windows Task Scheduler"}[sysname]

    print("\nScheduled memory health check")
    print(f"  system:   {sysname} ({mech})")
    print(f"  doctor:   {doctor}")
    print(f"  when:     {a.hour:02d}:{a.minute:02d}, {days_label}")
    print(f"  log:      {doctor.parent / 'doctor.log'}")
    print("\nWhat it does: once a day it checks the integrity of the memory and appends")
    print("the result to the log. It changes nothing and sends nothing outside.")

    if not a.yes and not ask_yes("\nInstall the schedule?", True):
        print("Cancelled. Nothing changed.")
        return 0

    installer = {"linux": cron_install, "macos": launchd_install, "windows": schtasks_install}[sysname]
    ok, msg = installer(doctor, a.hour, a.minute, weekdays)
    print(("\nOK: " if ok else "\nERROR: ") + msg)
    if ok:
        print(f"Remove it later: python3 {Path(__file__).name} --remove")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
