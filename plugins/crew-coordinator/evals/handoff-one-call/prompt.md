---
description: "handoff skill \u00a71: one harness_handoff call, then reply with only the bootstrap line in a fenced block"
tags: ["cc170"]
max_turns: 12
timeout_seconds: 240
allowed_tools: ["Read", "Glob", "Grep", "Skill"]
append_system_prompt: "Harness agent Test Wren #abcd1234 holds role ops-coder in project harness-ops (banner already shown by the hook). Pass agent=\"abcd1234\" to harness_* tools. Rules: protocol skill."
---
Wrap up and hand off ops-coder. Today: weekly report built (done); Outputs spec not started (open); dashboard idea dropped by me. Next action: run eval phase 1.
