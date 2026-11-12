#!/bin/sh
# Sync the published harness build to the public mirror github.com/Braindono/hatstand (hatstand-private is the private repo).
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
# every push: hatstand_check.py (0.24.0 item 17) checks the staged blobs with hatstand_guard.py's rules (path denylist,
# ledger-shape lines, live corpus titles, private terms, identity, email, credentials, workspace paths). Any hit stops the
# sync and nothing is pushed. Do not weaken or bypass these checks; the one exemption (the synthetic steward-r045 fixture,
# manifest-hashed) is listed in the CHANGELOG.
# 0.24.0 item 17 (guard spec v3): the installed pre-commit and pre-push hooks run on the commit and on every push, and this
# script refuses to push unless they will run (self-check of the clone's core.hooksPath). It never passes --no-verify.
set -eu
# a failing command inside a pipe must stop the sync (envoy m-5af8e7c4a480); pipefail where the shell has it, and the
# two git calls that feed the checks below are captured to files and checked on their own, which works in any sh
(set -o pipefail) 2>/dev/null && set -o pipefail
PUSH=0; [ "${1:-}" = "--push" ] && PUSH=1
# 0.24.0 item 17: the harness home comes from HARNESS_HOME only (harness_admin op=hatstand_sync sets it); no built-in path
[ -n "${HARNESS_HOME:-}" ] || { echo "hatstand: STOP, HARNESS_HOME is not set; nothing pushed" >&2; exit 1; }
XH="$HARNESS_HOME"
M="$XH/_harness"
REPO_URL="${HATSTAND_REPO:-https://github.com/Braindono/hatstand.git}"
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECK="$HERE/hatstand_check.py"
for f in hatstand_check.py hatstand_guard.py; do
  [ -f "$HERE/$f" ] || { echo "hatstand: STOP, $f missing next to this script; nothing pushed" >&2; exit 1; }
done
PY="${PYTHON:-python3}"
T="$(mktemp -d "${TMPDIR:-/tmp}/hatstand.XXXXXX")"   # 0.24.0 (D-2ca6d): macOS mktemp -d ignores TMPDIR without a template
trap 'rm -rf "$T"' EXIT
W="$T/hatstand"
GH='!gh auth git-credential'

# 0.19.0 (R-116): after a push, an annotated tag <plugin>-v<version> for every plugin version in the repo that has none yet
# (the clone fetched the existing tags). No branches; only the new tag refs are pushed, never --tags. Names are validated.
tag_new() {
  for d in plugins/*/; do
    pl="$(basename "$d")"
    # M6 (critic N-9d725): the version is the top-level "version" key of plugin.json, read as JSON (a greedy grep could pick a nested one)
    v="$(python3 -c 'import json,sys; v=json.load(open(sys.argv[1])).get("version",""); print(v if isinstance(v,str) else "")' "plugins/$pl/.claude-plugin/plugin.json" 2>/dev/null)" || v=""
    case "$pl" in ""|*[!a-z0-9-]*) continue ;; esac
    case "$v" in ""|*[!0-9A-Za-z._-]*) continue ;; esac
    tag="$pl-v$v"
    git rev-parse -q --verify "refs/tags/$tag" >/dev/null 2>&1 && continue
    if git -c user.name=Braindono -c user.email=Braindono@users.noreply.github.com tag -a "$tag" -m "$pl $v" \
       && git -c credential.helper= -c credential.helper="$GH" push -q origin "refs/tags/$tag:refs/tags/$tag"; then
      echo "hatstand: tagged $tag"
      echo "hatstand: pushed_ref refs/tags/$tag $(git rev-parse "refs/tags/$tag")"
    else
      echo "hatstand: tag $tag failed (the files are already pushed)" >&2
    fi
  done
}

# 0.24.0 (A-b2950 item 14): after a push, fetch origin main and compare trees; any difference, or a failed fetch, is a STOP and
# no tag is pushed. FETCH_HEAD is removed first, so an old one can never pass for a fresh fetch.
verify_remote() {
  rm -f .git/FETCH_HEAD
  if ! git -c credential.helper= -c credential.helper="$GH" fetch -q origin main; then
    echo "hatstand: STOP, remote main differs from the pushed tree ($(git rev-parse --short HEAD) vs fetch failed)" >&2; exit 1
  fi
  lt="$(git rev-parse "HEAD^{tree}")"
  rt="$(git rev-parse -q --verify "FETCH_HEAD^{tree}" 2>/dev/null || echo none)"
  if [ "$lt" != "$rt" ]; then
    echo "hatstand: STOP, remote main differs from the pushed tree ($(git rev-parse --short HEAD) vs $(git rev-parse -q --short --verify FETCH_HEAD 2>/dev/null || echo none))" >&2
    exit 1
  fi
  echo "hatstand: verified $(git rev-parse --short HEAD) = release tree$1"
}

git -c credential.helper= -c credential.helper="$GH" clone -q "$REPO_URL" "$W"
cd "$W"
# 0.24.0 item 17 (spec section 7, G12): the hooks must run for this clone, or nothing is committed or pushed
if ! "$PY" -I -B "$CHECK" self-check "$W" --home "$XH"; then
  echo "hatstand: STOP, the Hatstand hooks are not on for this clone (install them and the global includeIf); nothing pushed" >&2
  exit 1
fi
rsync -rc --delete --exclude .DS_Store --exclude __pycache__ "$M/marketplace/plugins/" plugins/
cp "$M/wake.py" bin/wake.py && chmod +x bin/wake.py
cp "$M/marketplace/.claude-plugin/marketplace.json" .claude-plugin/marketplace.json
git add -A
if git diff --cached --quiet; then
  echo "hatstand: no changes, nothing to push"
  if [ "$PUSH" = 1 ]; then
    verify_remote " (no changes)"
    tag_new
  fi
  exit 0
fi

# fail closed (R-097, D-c92cb; 0.24.0 item 17): every staged blob, as staged, through all of the guard's rules. The secret
# patterns now live in hatstand_guard.py (rule 5d); detector fixtures are exempt by path AND sha256 (CRED_PINNED).
if ! "$PY" -I -B "$CHECK" staged "$W" --home "$XH"; then
  echo "hatstand: STOP, guard hit (standing rule D-c92cb); nothing pushed" >&2; exit 1
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
  echo "hatstand: pushed_ref refs/heads/main $(git rev-parse HEAD)"
  verify_remote ""
  tag_new
else
  echo "hatstand: dry run, nothing pushed (use --push)"
fi
