#!/bin/sh
# One-time setup for a Mac (or Linux) checkout. Safe to re-run: it never overwrites existing config or data.
#   ./setup.sh                 create the shared folder and config, run the checks
#   ./setup.sh --home PATH     use PATH as the shared folder (default ~/Claude/Projects/Exchange)
#   ./setup.sh --link          also symlink bin/harness to ~/.local/bin/harness
#   ./setup.sh --test          also run the crew-coordinator test suite
set -eu
REPO="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="${HARNESS_HOME:-$HOME/Claude/Projects/Exchange}"
LINK=0; TEST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --home) HOME_DIR="$2"; shift 2 ;;
    --link) LINK=1; shift ;;
    --test) TEST=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

echo "== checks"
command -v python3 >/dev/null 2>&1 || { echo "python3 not found. Install Python 3.8 or newer." >&2; exit 1; }
python3 - <<'PY' || exit 1
import sqlite3, sys
if sys.version_info < (3, 8):
    sys.exit("Python 3.8 or newer is required, found %s" % sys.version.split()[0])
try:
    sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(a)")
    print("python %s, sqlite fts5: yes" % sys.version.split()[0])
except sqlite3.OperationalError:
    print("python %s, sqlite fts5: NO (corpus search falls back to a slower path)" % sys.version.split()[0])
PY

echo "== shared folder: $HOME_DIR"
mkdir -p "$HOME_DIR"
chmod +x "$REPO/bin/harness" "$REPO/bin/wake.py" 2>/dev/null || true
HARNESS_HOME="$HOME_DIR" "$REPO/bin/harness" init
echo "   config: $HOME_DIR/_harness/config.json (edit project_aliases, allowed_roots as needed)"

if [ "$LINK" = 1 ]; then
  mkdir -p "$HOME/.local/bin"
  if [ -e "$HOME/.local/bin/harness" ] && [ ! -L "$HOME/.local/bin/harness" ]; then
    echo "   not linking: ~/.local/bin/harness exists and is not a symlink" >&2
  else
    ln -sf "$REPO/bin/harness" "$HOME/.local/bin/harness"
    echo "== linked ~/.local/bin/harness (make sure ~/.local/bin is on your PATH)"
  fi
fi

if [ "$TEST" = 1 ]; then
  echo "== tests"
  (cd "$REPO/plugins/crew-coordinator" && python3 -m unittest discover -s tests -q)
fi

cat <<MSG

== next steps
1. Add this repo as a Claude Code marketplace and install the plugins (inside Claude Code):
     /plugin marketplace add $REPO
     /plugin install crew-coordinator@harness-local
     (optional) delegation-desk, excellent-etiquette, pixel-pilot, plugin-publications @harness-local
2. Point sessions at the shared folder: export HARNESS_HOME="$HOME_DIR"  (add it to your shell profile)
3. Restart Claude Code. A new chat should show a Crew Coordinator banner; then run: $REPO/bin/harness roster
4. Operator approvals (agents cannot approve their own requests):  harness pending   then   harness approve <id>
5. Dashboard (optional):  harness serve   ->  http://127.0.0.1:7717
MSG
