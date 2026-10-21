#!/bin/bash
set -e

FOUNDRY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LINT="$FOUNDRY_DIR/scripts/lint.py"

# /handoff now ships only in skill-foundry (D-bc60d): the old copy-to-harness-router
# and --check modes are gone. The only mode is --package.
if [[ "$1" == "--package" ]]; then
    # Package a plugin as ZIP archive
    if [[ -z "$2" ]]; then
        echo "Usage: ship.sh --package <plugin_dir>"
        exit 1
    fi
    
    PLUGIN_DIR="$(cd "$2" && pwd)"
    PLUGIN_NAME=$(basename "$PLUGIN_DIR")
    PLUGIN_VERSION=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$PLUGIN_DIR/.claude-plugin/plugin.json")
    PARENT="$(dirname "$PLUGIN_DIR")"
    OUTPUT="$PARENT/$PLUGIN_NAME-$PLUGIN_VERSION.plugin"

    # Release gate (if evals exist)
    GATE_INPUT="$PLUGIN_DIR/evals/gate-input.json"
    if [[ -f "$GATE_INPUT" ]]; then
        echo "=== Release gate ==="
        python3 -B "$FOUNDRY_DIR/scripts/gate.py" "$GATE_INPUT" || exit 1
    fi

    # Lint first (fails on ignore-list files, bad manifest, skills, CHANGELOG, confcheck)
    echo "=== Lint check ==="
    python3 -B "$LINT" "$PLUGIN_DIR" || exit 1

    # harness-router: marked sync must run twice on a throwaway ledger (0.10.3 regression)
    if [[ "$PLUGIN_NAME" == "harness-router" || "$PLUGIN_NAME" == "crew-coordinator" ]]; then
        echo "=== Marked-sync proof ==="
        T="$(mktemp -d)"
        trap 'rm -rf "$T" "$ZT"' EXIT
        X=(env HARNESS_HOME="$T" python3 -B "$PLUGIN_DIR/scripts/harness.py" --home "$T")
        "${X[@]}" init > /dev/null 2>&1
        AG=$("${X[@]}" register --project ship-proof --model m --task proof | python3 -c 'import json,sys;print(json.load(sys.stdin)["short"])') || { echo "✕ proof register failed"; exit 1; }
        "${X[@]}" update --agent "$AG" --ctx 1000 --base 500 > /dev/null && "${X[@]}" update --agent "$AG" --ctx 2000 --base 500 > /dev/null             || { echo "✕ marked sync twice failed"; exit 1; }
        echo "✓ marked sync ×2 on throwaway ledger"
    fi

    ZT=""; T="${T:-}"
    trap 'rm -rf "$T" "$ZT"' EXIT
    # Fresh ZIP, plugin dir as root, ignore list excluded (D-42db5).
    # rm first: zip -r would otherwise append to a stale archive.
    # Archive old file instead of deleting
    [[ -f "$OUTPUT" ]] && mv "$OUTPUT" "${OUTPUT}.bak" 2>/dev/null || true
    # Build in a temp dir, then cat into place (a failed zip never leaves a partial .plugin).
    ZT="$(mktemp -d)"
    (cd "$PARENT" && zip -rq "$ZT/out.zip" "$PLUGIN_NAME" \
        -x '*/.DS_Store' '*/._*' '*/__pycache__/*' '*.pyc' '*/.git/*' \
        '*.bak' '*.old' '*/zi??????')
    cat "$ZT/out.zip" > "$OUTPUT"

    # Verify: archive integrity, single root, no ignored entries
    unzip -tq "$OUTPUT" > /dev/null || { echo "✕ zip test failed"; exit 1; }
    if unzip -Z1 "$OUTPUT" | grep -v "^$PLUGIN_NAME/" | grep -q .; then echo "✕ entries outside $PLUGIN_NAME/"; exit 1; fi
    if unzip -Z1 "$OUTPUT" | grep -Eq '(^|/)(\.DS_Store|\._[^/]*|__pycache__/.*|[^/]*\.pyc|[^/]*\.bak|[^/]*\.old|zi[A-Za-z0-9]{6})$'; then echo "✕ ignored files in package"; exit 1; fi
    echo "✓ Packaged: $OUTPUT ($(unzip -Z1 "$OUTPUT" | grep -vc '/$') files)"
else
    echo "Usage: ship.sh --package <plugin_dir>"
    exit 1
fi
