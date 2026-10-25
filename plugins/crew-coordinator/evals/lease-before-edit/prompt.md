---
description: "protocol \u00a74: claim the shared file before editing, commit with base_version, release"
tags: ["cc170"]
max_turns: 12
timeout_seconds: 240
allowed_tools: ["Read", "Glob", "Grep", "Skill", "Write", "Edit"]
append_system_prompt: "Harness agent Test Wren #abcd1234 holds role ops-coder in project harness-ops (banner already shown by the hook). Pass agent=\"abcd1234\" to harness_* tools. Rules: protocol skill."
---
Add the line `reviewed 2026-10-25` to the end of the shared file notes/shared-notes.md (create it if missing). It is a shared harness file.
