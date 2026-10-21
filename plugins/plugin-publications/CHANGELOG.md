# Changelog

## 0.8.3 (2026-10-14)
- /upgrade skill (drift spec J, envoy conditions e-i): wraps `harness.py upgrade-plan` (cc 0.14.7): plan, refuse unapproved, print or run, reload, verify.

## 0.8.2 (2026-10-08): publish from an extracted package dir
- README step 7 and skills/new-skill/SKILL.md: publish from an EXTRACTED package dir, never the working tree.

## 0.8.1 (2026-10-07): lint catches invalid frontmatter YAML
- lint: ERROR `frontmatter YAML invalid` when any SKILL.md frontmatter fails a real YAML parse (PyYAML if importable, else stdlib checks for unquoted ': ' and unescaped inner quotes). Root cause: excellent-etiquette 0.1.0 index description had nested double quotes and failed to load.
- lint: plugin.json parsed strictly (rejects duplicate keys and NaN/Infinity constants).
- lint: history-line exemption ("formerly", "renamed from", "hardikpandya/stop-slop") waives only the names after the phrase; old names before it are still flagged.
- `--self-test` adds cases: nested double quotes fail, single-quoted with inner double quotes pass, unquoted `Use when: x` fails, history-waiver scope.

## 0.8.0 (2026-10-07): renamed from plugin-press
- Renamed plugin-press 0.7.4 -> plugin-publications 0.8.0 (plugin.json, README, gate.py); `/list` unchanged.
- lint: `plugin-press` and `prose-polish` added to retired names (ERROR as /command prefix and as old skill name outside CHANGELOG; lines saying "formerly"/"renamed from" are allowed). `--self-test` now runs real cases for both names.
- New skill `new-skill` (`/new-skill`): invoke Claude-provided skill/plugin builders first, then apply custom layers.

## 0.7.4 (2026-10-07)
- lint: `_OLD_SKILLS` (stop-slop -> polish). ERROR `old skill name stop-slop (now polish)` for `stop-slop` or `/stop-slop` in .md/.json outside CHANGELOG.md; upstream `hardikpandya/stop-slop` attribution is allowed.

## 0.7.3 (2026-10-06)
- lint: `_capsule_open` accepts `status: "open"`, `status: 'Open'` and trailing whitespace (quotes optional, value case-insensitive); `opened` and `accepted by ...` stay closed.

## 0.7.2 (2026-10-06)
- lint: `--corpus <Exchange dir>` runs the old-name check over projects/*/{CLAUDE,PROJECT,OPERATOR-PREFERENCES,build_instructions}.md, templates/*.md and open handoff capsules (`status: open`); skips _archive, specs, review, notes; exit 1 on hits.

## 0.7.1 (2026-10-06)
- lint: old-name check names the replacement (`/harness-router:` -> crew-coordinator); harness-router added to RETIRED source dirs.
- ship.sh: zip is built in a mktemp dir and `cat`-ed into place; excludes `*.bak`, `*.old`, `zi??????` temp files, `__pycache__`; the post-build check rejects them. The marked-sync proof also runs for crew-coordinator.

## 0.7.0 (2026-10-06)
- P8 (D-f9110): scripts/usage.py derives a per-session usage record (Exchange/projects/orchestration/digests/usage.jsonl) from events.jsonl; token fields null until crew-coordinator's ctx_hook reports them.
- lint: RETIRED set skips renamed plugins' old source dirs in /command and skill-name collision checks.

Renamed from skill-foundry (D-b2c05).
- Bare command references: `/skill-foundry:list` → `/list`.
- Three new lint rules: old plugin name prefix detection, namespaced command warning, skill-name collision check.
- New release gate (gate.py) for evaluating candidate models.
- README review checklist: all proposed changes must cite an event id.


## 0.6.4

- lint: fail on an XML-like tag (`<x`) in a skill description; the Claude app rejects the install (hr 0.12.2 restore skill).

## 0.6.3

- ship.sh: the marked-sync proof removes its temp ledger on exit (trap).
- `list` description trimmed to ≤150 chars (clears the D-6d252 warn).

## 0.6.2

- lint: fail on an unquoted `: ` in a skill description (N-ee0fb); `list` description reworded.
- ship.sh: harness-router packages must pass a marked sync run twice on a throwaway ledger (0.10.3 regression).

## 0.6.1

D-6d252 (token baseline).
- lint: WARN (non-failing) when a skill description exceeds 150 chars or a plugin's descriptions total more than 1200 chars; prints the total otherwise.
- `list` description trimmed to 150 chars.

## 0.6.0

D-b9225 quick fixes + D-4ee13.
- C3: `handoff` skill moved to harness-router 0.9.0 (`/harness-router:handoff`).
- C2: `/list` builds its table from the release registry; list.md, PLUGINS.md and plugins.json are retired (archived with mv -n).
- lint `--handoff`: status may be `open` or `accepted` (S7: the ledger is the source of handoff status).

## 0.5.2
- `lint.py --handoff` (D-15566 P6): fails on `model: unknown` when the `from:` role is a judgment role (envoy, lead, steward). Other roles may still use `unknown`.

## 0.5.1
- /handoff: frontmatter gains `model:` (the outgoing agent's exact model id, from its banner); §0 tells the successor to register with `model=`. `lint.py --handoff` requires `model` (value may be `unknown`). Template: Exchange/templates/HANDOFF.template.md.

## 0.5.0
- /list renders a pre-built markdown table in chat (Exchange/projects/skill-curation/list.md, from plugins_md.py) with 🟢/🟡/🔴 lights. No widget, so no display-tool setup call (was ~9k tokens per chat). About 1k tokens per run, down from ~2.7k plus ~9k on the first run. Descriptions are cut at 60 chars with …; ask for a row to see it in full.

## 0.4.1
- /list: no longer calls ListPlugins by default (its result rendered as a second, redundant list). Status now comes from this session's skill list; ListPlugins runs only to split a non-green row into yellow or red.
- `/list all`: also shows the full account plugin list (ListPlugins), including non-custom plugins. argument-hint `[all]`.

## 0.4.0
- New `/list` skill: custom plugins A-Z in an inline widget, with a status light (green = enabled and loaded, yellow = not enabled, red = enabled but not loaded or running), operator /commands, and descriptions that are truncated with … and expand on click. Reads Exchange/projects/skill-curation/list.widget.html (generated by plugins_md.py); status comes from ListPlugins plus this session's skill list. Markdown fallback when no widget tool.
- lint.py: fails when a skill's shortened /command (e.g. `/reload`) matches one in any other custom plugin under the same source root, or repeats inside the plugin. Rename the skill to fix.
- lint.py --commands [src-root]: the same conflict check across all custom plugins; exits 1 on any collision.
- lint.py: plugin dir resolved to an absolute path, so `lint.py .` works.

## 0.3.1
- plugin.json: `author` is now an object (`{"name": "Brian"}`). The string form stopped the plugin's skills from loading, so `/skill-foundry:handoff` was missing.
- lint.py: fails when `author` is not an object with a `name`.
- README step 8 "Confirm load" (D-a54c7).

## 0.3.0
- /handoff ships only in skill-foundry as `/skill-foundry:handoff`. harness-router 0.5.0 no longer bundles a copy (D-bc60d, supersedes D-30936 Q1).
- ship.sh: removed the copy-to-harness-router and `--check` modes. `--package` is the only mode.

## 0.2.1
- ship.sh --package <dir>: fresh ZIP with the plugin dir as root, ignore list excluded, then verified (unzip -t, single root, no ignored entries). Lint runs first.
- lint.py: reads Exchange/_harness/ignore and fails on any match, including __pycache__/ (D-42db5); checks every rule instead of stopping at the first; accepts "Use for" triggers; plugin.json name must equal the dir name, with no odd keys; fails if confcheck is missing.
- lint.py --handoff <file>: requires the template skeleton, §0, `status: open`, `successor_of=`, a project and ≤1500 tokens (fixes the Swift Coyote handoff defect).
- confcheck: honors HARNESS_HOME; skips ignore-list paths; exempts the plugin.json "author" line.
- /handoff: copies the template skeleton verbatim, keeps §0 and `status: open`, requires a project, and runs lint --handoff before replying.
- Remove HTML comment key from plugin.json (invalid JSON)
- Document confcheck author exemption in README

## 0.2.0
- Add confcheck.py (scans denylist, respects allowlist comments)
- Add lint.py (validates plugin.json, SKILL.md format, token budgets, CHANGELOG, confcheck)
- Add ship.sh --check for package verification
- Add /handoff skill (shipped from skill-foundry)

## 0.1.0
- Scaffold: /handoff skill with Exchange-backed handoffs
