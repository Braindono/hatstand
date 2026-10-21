# plugin-publications

Foundry for building and shipping Harness skills. Includes infrastructure for spec-driven builds with quality gates.

## Skills

- **new-skill** (`/new-skill`): start any skill or plugin build with Claude-provided builders first, then the custom rules.
- **list** (`/list`): plugin table built from the release registry (D-b9225 C2).
- `/handoff` moved to harness-router 0.9.0 (D-b9225 C3).

## Build process (D-a54c7)

1. **Restate**: the lead confirms the change with the operator.
2. **Build**: the lead edits the source here. Haiku workers are for bulk read/audit only.
3. **Lint**: `scripts/lint.py <plugin-dir>` (handoffs: `--handoff <file>`; Exchange text: `--corpus <Exchange dir>` flags old `/plugin:` prefixes in project docs, templates and open handoff capsules, skipping _archive, specs, review, notes and closed capsules).
4. **Package**: `scripts/ship.sh --package <plugin-dir>` makes a verified ZIP.
5. **Review**: the operator sees the diff and the package manifest.
6. **Approve**: the operator approves explicitly.
7. **Publish**: `harness.py publish <plugin-dir> --notes "…"`, then the fleet reinstalls. Publish from an EXTRACTED package dir, never the working tree.
8. **Confirm load**: don't close out until the log shows `server.started` with the new code (`/update` → `run ✓`). If not, run `/reload` (hr ≥0.5.1) or quit and reopen the app.

## Confcheck

The confcheck tool scans for confidential content using Exchange/resources/private/confidential.denylist.
The `author` field in plugin.json is exempt from confcheck by rule (it is metadata, not sensitive content).
To exempt other fields, use HTML comments: `<!-- confcheck:allow term -->` (valid for non-JSON files only).

## Package structure

- `.claude-plugin/plugin.json` — metadata (name, version, description)
- `README.md` — this file
- `CHANGELOG.md` — version history
- `skills/` — individual skill directories
- `scripts/` — build tools

See plugin-publications source at Harness_Router/plugin-publications/.

## Review checklist

Every proposed skill or rule change must cite an event id (events.jsonl #N / m-…/D-…) or trace step. Uncited rationale is rejected and not repaired.
