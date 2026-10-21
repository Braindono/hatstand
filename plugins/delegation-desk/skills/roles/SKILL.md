---
name: roles
description: Harness role work. Use when messaging role:x, on a ◇n footer, or before editing another role's file.
---

# Roles

A role (for example `cv-management/letters-manager`) outlives the agents that hold it. Succession passes it on. One role per agent. The operator defines and assigns roles. Agents never assign themselves.

## Address
- Send to `role:<name>`, not to a sobriquet: `harness_send to=role:letters-manager`. It reaches whoever holds the role when the mail is read, and waits if the role is vacant.
- Tickets are `kind=task` messages to a role. Move them with `harness_admin op=task_update args={task_id, state, stage, to, note}`:
  - `stage` = workflow step (for example `fit-check`)
  - `to` = next role (sends a one-line notice in the ticket thread)
  - `state=completed` sends a one-line digest to the operator. Don't send a separate summary.
- Bodies: ids, paths, a short delta. Never paste file contents.

## Roster
- `◇n` in a tool footer means the roster changed. Your next `/update` lists it. Only when you need it now: `harness_admin op=roster args={since:<your last seq>}` (changes only) or `{project:"<name>"}`.

## Ownership
- Each role `owns` path globs. Leasing an owned file notifies the owner (you are not blocked). Before editing another role's file, send `kind=review` to that role. Edit only minor, reversible fixes without waiting.
- An owner receiving a "governed file leased" notice checks the diff and reverts or accepts in its thread.

## Project cards
Each project's paths and standing rules live in `Exchange/projects/<project>/PROJECT.md`. Read the card for any project you work with. Propose changes with `kind=review` to its maintainer.

## Pass the ball
Waiting costs 0 tokens: never poll or schedule check-ins. `W` = `device_bash python3 -B $HOME/mnt/Exchange/_harness/wake.py`. Load the scheduled-task tools with ToolSearch.
- Waiter: check `harness_inbox`. If the ball isn't there: `send_later delay_minutes=10080` "Ball wake for role:<you>. Run /update; stop if nothing is pending.", then `W set <your role> <trig_id>` and end your turn.
- Finisher: send the result `to=role:<r>`, then `W get <r>`. If it returns an id, `fire_trigger` it (no `text`, which fails) and `W clear <r>`.
- Woken: `/update`, work the thread, then `delete_trigger` your wake (if denied, leave it; the fallback does nothing).

## No-carry roles
If your role card says `no-carry`, start clean: no predecessor capsules, no recall of old threads. Work only from files and your inbox.
