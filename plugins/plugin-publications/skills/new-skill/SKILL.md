---
name: new-skill
description: "Use when: creating, rewriting or packaging any skill or plugin, /new-skill, new skill, new plugin."
---
# /new-skill

Start here when any agent in Skill Curation begins creating or substantially changing a skill or plugin.

## 1. Claude-provided builders first
- Invoke the Skill tool `anthropic-skills:skill-creator` (the built-in /skill-creator).
- For a whole plugin also invoke `cowork-plugin-management:create-cowork-plugin` or `cowork-plugin`, if listed.
- Discover newer Anthropic-provided skills or plugins with ListSkills / SearchSkills (load via ToolSearch) and use any that fit.
- Invoke them live. Never vendor or copy their text, so they stay current.
- If one is unavailable, say so in one line and continue.

## 2. Then the custom layers
- Exchange `claude/skill-best-practices.md` (project doc) and the excellent-etiquette rules.
- Token economy: SKILL.md <=60 lines, description <=100 chars starting "Use when:".
- A cheaper worker builds from a written spec; the lead verifies.
- `python3 plugin-publications/scripts/lint.py <dir>` must show 0 fail; package with `ship.sh --package <dir>`.
- Envoy ACCEPT naming the package sha before publish.
- Publish from an EXTRACTED package dir, never the working tree.

## 3. Where they disagree
- Custom plugin rules win on format and limits.
- Claude-provided guidance wins on eval and trigger-testing method.
