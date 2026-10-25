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
set -eu
PUSH=0; [ "${1:-}" = "--push" ] && PUSH=1
M="${HARNESS_HOME:-$HOME/Claude/Projects/Exchange}/_harness"
REPO_URL="${HATSTAND_REPO:-https://github.com/Braindono/hatstand.git}"
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
HITS="$(git diff --cached -U0 | awk '/^\+\+\+ /{f=substr($2,3)} /^\+[^+]/{print f"\t"$0}' | grep -E "gho_|ghp_|github_pat_|sk-[A-Za-z0-9]{16,}|sk-ant-[A-Za-z0-9_-]{20,}|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{12,}|privaterelay" | grep -vE "^($EXEMPT)	" || true)"
if [ -n "$HITS" ]; then
  echo "hatstand: STOP, the staged diff matches a secret pattern outside the exempt files; nothing pushed:" >&2
  echo "$HITS" | cut -c1-160 >&2; exit 1
fi
# the R-045 steward fixture is a synthetic, frozen corpus (tests/fixtures/steward-r045, manifest-hashed); it is the only
# runtime-shaped data allowed, and the secret scan above still reads it.
if git diff --cached --name-only | grep -vE "^plugins/crew-coordinator/tests/fixtures/steward-r045/" | grep -E "(^|/)(events\.jsonl|registry\.json|config\.json|corpus\.db)$|\.lock$" >/dev/null; then
  echo "hatstand: STOP, runtime data staged; nothing pushed" >&2; exit 1
fi

CHANGED="$(git diff --cached --name-only | sed -n 's#^plugins/\([^/]*\)/.*#\1#p' | sort -u)"
LABEL=""
for pl in $CHANGED; do
  v="$(grep -m1 '"version"' plugins/$pl/.claude-plugin/plugin.json | sed 's/.*: *"\(.*\)".*/\1/')"
  LABEL="${LABEL:+$LABEL, }$pl $v"
done
[ -n "$LABEL" ] || LABEL="repo files"
echo "hatstand: changes found ($LABEL):"; git diff --cached --stat | tail -8
if [ "$PUSH" = 1 ]; then
  git -c user.name=Braindono -c user.email=Braindono@users.noreply.github.com commit -q -m "Sync to $LABEL

Published build(s) mirrored from the harness marketplace.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
  git -c credential.helper= -c credential.helper="$GH" push -q origin main
  echo "hatstand: pushed $(git rev-parse --short HEAD)"
else
  echo "hatstand: dry run, nothing pushed (use --push)"
fi
