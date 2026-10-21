---
name: list
description: /list - custom plugins A-Z from the release registry - status, version, /commands. Use for "list", "list plugins", "plugin status", "loaded".
argument-hint: "[all]"
---
# /list

Token budget: about 1k. Output only the table and at most one line after it. Don't use widgets, artifacts or `read_me`. Source of truth is the registry (D-b9225 C2); no hand-kept list files.

1. Call `harness_admin op=registry`. Harness not loaded: `device_bash` `cat $HOME/mnt/Exchange/_harness/registry.json`. Neither: say so in one line and stop.
2. One row per registry entry, sorted A-Z: `| light | plugin | version | /commands |`.
   - /commands: every `<plugin>:<skill>` in this session's skill list, as `/plugin:skill`, comma-separated. None loaded: `–`.
   - Light 🟢 = at least one `<plugin>:<skill>` is loaded (for `harness-router`, its `harness_*` tools are present and the last /update didn't show `run ✕`).
   - Only if a row isn't 🟢, call `ListPlugins` once: `enabled: true` → 🔴 (enabled, not loaded); absent or `enabled: false` → 🟡 (not enabled).
3. Loaded plugin version differs from the registry (/update health `≠`): add `→ <registry version>` after the version.
4. `/list all`: call `ListPlugins` (no keywords) first and add rows for plugins not in the registry with light and `(unregistered)`.

After the table, one line only if needed: name any 🟡 row (enable it in the app's plugin settings) or 🔴 row (`/reload`, or reinstall).
