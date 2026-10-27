#!/bin/sh
# Sync the published harness build to the private repo github.com/Braindono/hatstand.
# 0.17.0 (R-048): shipped in crew-coordinator and run by `harness_admin op=hatstand_sync` (dry run; push after a clean
# dry run of the same marketplace). HATSTAND_REPO overrides the remote (tests use a local bare repo). The temp clone is
# removed on exit (our own temp folder).
# Standing rule (operator 2026-10-23): every new build is also pushed to hatstand.
#   hatstand-sync.sh           dry run: show what would change, push nothing
#   hatstand-sync.sh --push    commit and push (only if something changed and the secret scan is clean)
# Source of truth: the published marketplace under Exchange/_harness. Never copies the ledger, corpus,
# registry or config. Needs the gh login (gh auth status). Safe to re-run; no changes means no commit.
# STANDING RULE (operator 2026-10-26, D-c92cb): the corpus and the ledger are NEVER published to Hatstand. No corpus
# entry, ledger event, vault file, handoff, digest or archive may reach this repo. 0.18.0 (R-097) enforces it before
# every push: the secret scan below, then hatstand_guard.py (path denylist, ledger-shape lines, live corpus titles).
# Any hit stops the sync and nothing is pushed. Do not weaken or bypass these checks; the one exemption (the synthetic
# steward-r045 fixture, manifest-hashed) is listed in the CHANGELOG.
set -eu
# a failing command inside a pipe must stop the sync (envoy m-5af8e7c4a480); pipefail where the shell has it, and the
# two git calls that feed the checks below are captured to files and checked on their own, which works in any sh
(set -o pipefail) 2>/dev/null && set -o pipefail
PUSH=0; [ "${1:-}" = "--push" ] && PUSH=1
# 0.18.0 (R-082): without HARNESS_HOME, the new home ~/Claude/Exchange first, then the old path (one release)
if [ -n "${HARNESS_HOME:-}" ]; then XH="$HARNESS_HOME"
elif [ -d "$HOME/Claude/Exchange" ]; then XH="$HOME/Claude/Exchange"
else XH="$HOME/Claude/Projects/Exchange"; fi
M="$XH/_harness"
REPO_URL="${HATSTAND_REPO:-https://github.com/Braindono/hatstand.git}"
GUARD="$(cd "$(dirname "$0")" && pwd)/hatstand_guard.py"
[ -f "$GUARD" ] || { echo "hatstand: STOP, hatstand_guard.py missing next to this script; nothing pushed" >&2; exit 1; }
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
W="$T/hatstand"
GH='!gh auth git-credential'

git -c credential.helper= -c credential.helper="$GH" clone -q "$REPO_URL" "$W"
cd "$W"
rsync -rc --delete --exclude .DS_Store --exclude __pycache__ "$M/marketplace/plugins/" plugins/
cp "$M/wake.py" bin/wake.py && chmod +x bin/wake.py
cp "$M/marketplace/.claude-plugin/marketplace.json" .claude-plugin/marketplace.json
git add -A
if git diff --cached --quiet; then echo "hatstand: no changes, nothing to push"; exit 0; fi

# fail closed: refuse to push anything that looks like a secret or personal address.
# Known detector code and synthetic test fixtures are exempt BY FILE (they define the secret patterns and use fake
# values such as AKIAIOSFODNN7EXAMPLE); a match anywhere else, including any other test file, stops the push.
EXEMPT='plugins/crew-coordinator/scripts/(transcript_indexer|insight_share)\.py|plugins/crew-coordinator/scripts/hatstand-sync\.sh|plugins/crew-coordinator/tests/(test_cc162_indexer|test_e4_c3)\.py'
git diff --cached -U0 > "$T/staged.diff" || { echo "hatstand: STOP, git diff failed; nothing pushed" >&2; exit 1; }
HITS="$(awk '/^\+\+\+ /{f=substr($2,3)} /^\+[^+]/{print f"\t"$0}' "$T/staged.diff" | grep -E "gh[pousr]_[A-Za-z0-9]{16,}|github_pat_|(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{20,}|BEGIN [A-Z ]*PRIVATE KEY|(AKIA|ASIA)[0-9A-Z]{12,}|AIza[0-9A-Za-z_-]{20,}|privaterelay" | grep -vE "^($EXEMPT)	" || true)"
if [ -n "$HITS" ]; then
  echo "hatstand: STOP, the staged diff matches a secret pattern outside the exempt files; nothing pushed:" >&2
  echo "$HITS" | cut -c1-160 >&2; exit 1
fi
# corpus/ledger guard (R-097, D-c92cb): path denylist, ledger-shape lines and live corpus titles. The R-045 steward
# fixture is a synthetic, frozen corpus; only its files whose sha matches its manifest are exempt, and the secret scan
# above still reads them.
# Names are NUL-separated and unquoted (core.quotepath=false, -z): a quoted non-ASCII name would not open and must
# never be skipped (critic B1). HARNESS_HOME goes to the guard so the live-title check also runs when this script is
# run directly (critic N2).
git -c core.quotepath=false diff --cached --name-only -z --diff-filter=ACMR > "$T/staged.names" \
  || { echo "hatstand: STOP, git could not list the staged files; nothing pushed" >&2; exit 1; }
if ! HARNESS_HOME="${M%/_harness}" "${PYTHON:-python3}" -B "$GUARD" "$W" < "$T/staged.names"; then
  echo "hatstand: STOP, corpus/ledger guard hit (standing rule D-c92cb); nothing pushed" >&2; exit 1
fi

CHANGED="$(git diff --cached --name-only | sed -n 's#^plugins/\([^/]*\)/.*#\1#p' | sort -u)"
LABEL=""
for pl in $CHANGED; do
  v="$(grep -m1 '"version"' plugins/$pl/.claude-plugin/plugin.json 2>/dev/null | sed 's/.*: *"\(.*\)".*/\1/')" || v="?"   # label only
  LABEL="${LABEL:+$LABEL, }$pl $v"
done
[ -n "$LABEL" ] || LABEL="repo files"
echo "hatstand: changes found ($LABEL):"; git diff --cached --stat | tail -8
if [ "$PUSH" = 1 ]; then
  # 0.18.0 (R-115, D-b7b3c): the commit carries no Co-Authored-By line; author and committer are the Braindono identity.
  git -c user.name=Braindono -c user.email=Braindono@users.noreply.github.com commit -q -m "Sync to $LABEL

Published build(s) mirrored from the harness marketplace."
  git -c credential.helper= -c credential.helper="$GH" push -q origin main
  echo "hatstand: pushed $(git rev-parse --short HEAD)"
else
  echo "hatstand: dry run, nothing pushed (use --push)"
fi
