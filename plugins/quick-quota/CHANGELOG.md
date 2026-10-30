# quick-quota changelog

## 0.1.0 (2026-10-29): first release, adopted by the curator (operator D-74753)
Scope items (verbatim, release_scope):
- quick-quota 0.1.0 as built by the secretary and tested by the operator: an AbovePrompt band with the 5-hour and weekly quota, meter, reset time and Hide
- Toasts at session start and when a window passes 90%; reads only the session usage the engine measures, no network or files
- Package leaves out the engine-generated .claude-plugin/types editor files; source of record is harness-hub/quick-quota

Details: hooks/register.tsx registers session.start (reads $.session.usage, stores the five_hour and seven_day windows), session.measure (updates on change, toast at 90% or more) and ui.render on AbovePrompt (meter, percent, "resets in", amber at 70%, red at 90%, Hide for the session). State contract in types/index.d.ts. Test: tests/quota.test.tsx (the band shows both windows on every surface). Built in the secretary's chat; the operator confirmed it in Claude Code (terminal); it does not draw in the claude.ai cloud chat view.
