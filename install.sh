#!/usr/bin/env bash
# Installs the agent long-term memory skill.
# Works on macOS, Ubuntu, Debian, Fedora, Arch and other Unix systems.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/skill"
NAME="ltm-vault"

say()  { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- Python -----------------------------------------------------------------
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  fi
done
[ -n "$PY" ] || fail "Python 3.8 or newer is required.
  Ubuntu/Debian: sudo apt install python3
  Fedora:        sudo dnf install python3
  Arch:          sudo pacman -S python
  macOS:         brew install python3"

say "Python: $("$PY" --version 2>&1)"
[ -d "$SRC" ] || fail "skill/ directory not found next to this script"

# --- install targets ---------------------------------------------------------
# Each agent looks for skills in its own directory.
declare -a TARGETS=()
add_target() { TARGETS+=("$1|$2"); }

detect() {
  # Each line ends with `|| true`: without it a failing final `[ -d ]` returns 1
  # and `set -e` exits the script silently, telling the user nothing.
  [ -d "$HOME/.claude" ]      && add_target "Claude Code" "$HOME/.claude/skills"      || true
  [ -d "$HOME/.config/amp" ]  && add_target "AMP Code"    "$HOME/.config/amp/skills"  || true
  [ -d "$HOME/.gemini" ]      && add_target "Gemini CLI"  "$HOME/.gemini/skills"      || true
}

case "${1:-}" in
  --claude) add_target "Claude Code" "$HOME/.claude/skills" ;;
  --amp)    add_target "AMP Code"    "$HOME/.config/amp/skills" ;;
  --gemini) add_target "Gemini CLI"  "$HOME/.gemini/skills" ;;
  --all)
    add_target "Claude Code" "$HOME/.claude/skills"
    add_target "AMP Code"    "$HOME/.config/amp/skills"
    add_target "Gemini CLI"  "$HOME/.gemini/skills" ;;
  --help|-h)
    cat <<'EOF'
Usage: ./install.sh [option]

  (no option)  detect installed agents and install the skill for each
  --claude     Claude Code only
  --amp        AMP Code only
  --gemini     Gemini CLI only
  --all        all three, even if the agent is not installed yet
  --help       this help
EOF
    exit 0 ;;
  "") detect ;;
  *)  fail "unknown option: $1 (try --help)" ;;
esac

if [ ${#TARGETS[@]} -eq 0 ]; then
  say "No installed agent found."
  say "Force install with: ./install.sh --all"
  exit 1
fi

# --- install -----------------------------------------------------------------
for t in "${TARGETS[@]}"; do
  label="${t%%|*}"
  dir="${t##*|}/$NAME"
  mkdir -p "$dir"
  cp -R "$SRC/." "$dir/"
  # __pycache__ is left behind by runs inside the repo and would ship to the user.
  find "$dir" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  chmod +x "$dir"/scripts/*.py 2>/dev/null || true
  say "installed: $label -> $dir"
done

# --- verify ------------------------------------------------------------------
first="${TARGETS[0]##*|}/$NAME"
"$PY" - "$first" <<'PY'
import sys, pathlib
d = pathlib.Path(sys.argv[1])
need = ["SKILL.md", "scripts/ltm_detect.py", "scripts/ltm_init.py",
        "scripts/ltm_doctor.py", "scripts/ltm_schedule.py", "scripts/ltm_seed.py",
        "scripts/ltm_uninstall.py", "scripts/ltm_version.py", "scripts/ltm_blocks.py",
        "scripts/ltm_paths.py", "scripts/ltm_hooks.py", "scripts/ltm_session_start.py",
        "scripts/ltm_precompact.py"]
missing = [n for n in need if not (d / n).is_file()]
if missing:
    print("ERROR: missing files: " + ", ".join(missing)); sys.exit(1)
print("verify: all files present")
PY

say ""
say "Done. Next:"
say "  1. Restart your agent so it picks up the new skill."
say "  2. Ask it: \"set up long-term memory\"."
say "  3. Or run detection manually:"
say "     $PY \"$first/scripts/ltm_detect.py\""
