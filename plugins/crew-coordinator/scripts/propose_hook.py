#!/usr/bin/env python3
"""propose_hook: 0.27.3 C1 piece 3. PostToolUse hook (matcher AskUserQuestion): the questions, options and his answer go to the proposal store with source=hook.
Depends on: ask_payload (the one parser), proposals; harness (lazily, for the home and ledger). Never fails the tool call: any error exits 0, silent.
Input (stdin JSON): {session_id, cwd, tool_name, tool_input, tool_response}. The project comes from the ledger record of the agent bound to session_id (cwd folder name as a hint), "harness" only if both fail. Writes one proposal per call (kind=options). The Hub Decide card line belongs to the secretary's card writer
(her module): she calls proposals.save(..., source="hub") herself.
hooks.json entry needed (cluster D registers it): {"matcher": "AskUserQuestion", "hooks": [{"type": "command", "command": "python3 \\"${CLAUDE_PLUGIN_ROOT}/scripts/propose_hook.py\\"", "timeout": 10}]} under PostToolUse."""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ask_payload, proposals


def project_for(d, h):
    """Project of the agent bound to the hook's session_id (ledger record); else the agent whose project matches the cwd folder name; else None."""
    st = h.state()
    aid = st.sessions.get((d or {}).get("session_id") or "")
    proj = ((st.agents.get(aid) or {}).get("project") or "") if aid else ""
    if not proj:
        hint = H_norm((os.path.basename((d or {}).get("cwd") or "").rstrip("/")))
        known = {H_norm(a.get("project")) for a in st.agents.values() if a.get("project")}
        proj = hint if hint in known else ""
    return proj or None


def H_norm(p):
    import re
    return re.sub(r"[\s_]+", "-", (p or "").strip().lower())


def run(d, home, store=None, actor="system", project=None):
    """-> saved dict or None (not an AskUserQuestion call, or nothing to save)."""
    name = (d.get("tool_name") or "") if isinstance(d, dict) else ""
    if not (name == "AskUserQuestion" or name.endswith("__AskUserQuestion")):
        return None
    qs = ask_payload.questions(d.get("tool_input"))
    if not qs:
        return None
    ans = ask_payload.answers(d.get("tool_response"))
    items = []
    for q in qs:
        opts = "".join(f"\n   - {o['label']}" + (f": {o['description']}" if o["description"] else "") + (f"\n     preview: {o['preview']}" if o["preview"] else "") for o in q["options"])
        items.append(f"{q['question']}{opts}")
    answer = "\n".join(f"{k}: {v}" for k, v in ans.items()) or None
    title = (qs[0]["header"] or qs[0]["question"])[:80]
    return proposals.save(home, project or os.environ.get("HARNESS_PROJECT") or "harness", "options", title, items, source="hook", store=store, actor=actor, answer=answer)


def main():
    try:
        d = json.loads(sys.stdin.read())
        import harness as H
        h = H.Harness()
        run(d, h.home, h.store, project=project_for(d, h))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
