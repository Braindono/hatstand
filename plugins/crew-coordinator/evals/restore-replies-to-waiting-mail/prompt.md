---
description: "restore skill \u00a73 + protocol P-89: restore with the given capsule, then answer waiting mail at once"
tags: ["cc170"]
max_turns: 12
timeout_seconds: 240
allowed_tools: ["Read", "Glob", "Grep", "Skill"]
append_system_prompt: "Harness agent Test Wren #abcd1234 holds role ops-coder in project harness-ops (banner already shown by the hook). Pass agent=\"abcd1234\" to harness_* tools. Rules: protocol skill."
---
restore as ops-coder from Exchange/projects/harness-ops/handoffs/2026-10-24-misty-rasp.md
