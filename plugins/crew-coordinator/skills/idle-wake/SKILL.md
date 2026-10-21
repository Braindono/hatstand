---
name: idle-wake
description: "Use for /idle-wake on|off|status: opt-in 55-minute idle handoff for this project. Never lists triggers."
---

# /idle-wake on|off|status

Opt-in per project. When on, the hook arms a 55-minute send_later after an operator prompt; if no operator prompt follows, the wake runs /handoff. A handoff disarms the wake.

- on: `harness_admin op=idle_wake args={project, on:true}`.
- off: `update_trigger(trigger_id=<armed id>, enabled=false)` if armed, then `harness_admin op=idle_wake args={project, on:false}`.
- status: read `$TMP/harness-idle-<session>.json` and config `idle_wake_projects`; report on/off and next fire time.

The armed id is in the state file. Never call list_triggers.
