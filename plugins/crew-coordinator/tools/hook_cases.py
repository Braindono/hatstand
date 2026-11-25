"""hook_cases (0.27.2 I6): the synthetic ledger and the per-hook cases for tools/hook_latency.py. Depends on: scripts/harness.py (the real Harness API), stdlib.
build_ledger(dest, root, n_messages) makes a pristine temporary home: 5 agents (two with roles), n_messages messages, one lease, config, a transcript, a retired
chat marker and a gates.json; it never touches the live ledger. CASES maps (event, command tail) to the fixed stdin of the event and the PROOF that the intended
path ran: ("out", text in stdout), ("event", ledger event type written by the run) or ("file", path under the home or state dir that the run changed).
A hook with no proof (None) is reported as an early exit, never as measured."""
import datetime
import json
import os
import sys
import time

SID, SID_RETIRED, SID_NEW = "sess-0", "sess-retired", "sess-new"
LEASED = "notes/leased.txt"          # held by agent 1; agent 0 editing it is a lease conflict
EDITED = "notes/edited.txt"
TRANSCRIPT = "_t/transcript.jsonl"
TRANSCRIPT_Q = "_t/transcript_question.jsonl"
GATES = "_gates/gates.json"


def future(days=30):
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build_ledger(dest, root, n_messages=3000, n_agents=5):
    """-> {"home", "state", "banner"}; the home is a complete, private ledger built through the real Harness API."""
    home, state = os.path.join(dest, "home"), os.path.join(dest, "state")
    os.makedirs(home)
    os.makedirs(state)
    old = {k: os.environ.get(k) for k in ("HARNESS_HOME", "HARNESS_STATE_DIR", "HOME", "HARNESS_CACHE")}
    os.environ.update(HARNESS_HOME=home, HARNESS_STATE_DIR=state, HOME=dest, HARNESS_CACHE=os.path.join(dest, "cache"))
    sys.path.insert(0, os.path.join(root, "scripts"))
    try:
        import harness as H
        h = H.Harness(home)
        h.role_define("operator", "envoy", "orchestration")
        h.role_define("operator", "curator", "orchestration")
        h.role_define("operator", "secretary", "orchestration")
        ids = []
        for i in range(n_agents):
            kw = {"role": ["envoy", "curator", "secretary"][i]} if i < 3 else {}
            ids.append(h.register(project="orchestration", model="claude-sonnet-5-5", **kw)["id"])
        for i in range(n_agents - 1):                                            # the last agent stays unbound (the post-bind case binds it)
            h.store.append("session.bound", ids[i], {"session_id": SID if i == 0 else f"sess-{i}", "agent": ids[i]})
        for n in range(n_messages):
            h.send(ids[n % n_agents], [ids[(n + 1) % n_agents]], f"synthetic message {n} about the release gate", subject="s", kind="notice")
        h.claim(ids[1], [LEASED])
        _write(os.path.join(home, EDITED), "a\n")
        h.record(ids[0], "note", "Release gate decision: an ACCEPT line is required", "The release gate needs an ACCEPT line.", ["release", "gate"])
        _write(os.path.join(home, "_harness", "release_prehash.json"), json.dumps({"t": time.time() - 1, "hashes": {}, "carried": [], "code": "x"}))   # valid for 2 hours
        h.store.append("release.published", "system", {"name": "x", "version": "1.0.0"})
        _seed_lessons(h, home)
        h.corpus.refresh()                                                      # last, so the index is newer than the corpus stamp (auto_lookup skips an older one)
        banner = h.card(h.state(), ids[-1])["banner"]
        _write(os.path.join(home, "_harness", "config.json"), json.dumps({"idcheck_observe_until": future(), "auto_lookup": "on", "lesson_cue": "on"}))
        _write(os.path.join(home, "_harness", "retired_sessions.json"), json.dumps({"sessions": {SID_RETIRED: {"successor_name": "X", "at": "2026-01-01"}}}))
        _write(os.path.join(home, TRANSCRIPT), "\n".join(json.dumps(x) for x in (
            {"type": "user", "message": {"role": "user", "content": "please finish the release"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done: the release is built."}]}})) + "\n")
        _write(os.path.join(home, TRANSCRIPT_Q), "\n".join(json.dumps(x) for x in (
            {"type": "user", "message": {"role": "user", "content": "go on"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Should the release gate need an ACCEPT line?"}]}})) + "\n")
        _write(os.path.join(home, GATES), json.dumps({"harness": {"mode": "observe", "observe_until": future(), "sources": [{"label": "rules", "path": "RULES.md"}]},
                                                        "ask_gate": {"mode": "observe", "observe_until": future(), "sources": [{"label": "rules", "path": "RULES.md"}]}}))
        _write(os.path.join(home, "_gates", "root", "RULES.md"), "The release gate needs an ACCEPT line.\n")
        return {"built": time.time(), "home": home, "state": state, "banner": banner, "agent0": ids[0][:8], "agent2_sid": "sess-2"}
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _raw(h, etype, data):
    """Append an operator-signed event type the way the ledger holds it; a synthetic ledger has no signing seat, so the store's lock and writer are used directly."""
    with h.store._lock():
        h.store._append_locked(etype, "system", data)


def _seed_lessons(h, home):
    """Two operator-approved lessons (one on a Bash input, one on a prompt) with the approval and curation events the lesson cue hook verifies in the ledger."""
    import ontology
    lessons = {"N-aaaaa": {"rule": "Check before a force push."}, "N-ddddd": {"rule": "Publishing needs his OK in chat."}}
    for i, (lid, v) in enumerate(lessons.items()):
        ap = "A-t%04d" % i
        _raw(h, "approval.requested", {"id": ap, "action": "lesson_curate", "args": {"lessons": [{"id": lid, "when": None, "rule": v["rule"], "keys": None}]}})
        _raw(h, "approval.granted", {"id": ap, "state": "granted"})
        _raw(h, "lesson.curated", {"id": lid, "hash": "x", "by": "operator", "cue_hash": ontology.cue_hash(lid, None, v["rule"], None), "approval": ap})
    _write(os.path.join(home, "_harness", "data", "lesson_cues.json"), json.dumps({"v": 1, "lessons": {k: {"when": None, "rule": v["rule"]} for k, v in lessons.items()}}))
    _write(os.path.join(home, "_harness", "data", "lesson_triggers.json"), json.dumps({"v": 1, "max_per_session": 3, "entries": [
        {"id": "N-aaaaa", "tool": "^Bash$", "input": "(?i)force", "cue": "x"}, {"id": "N-ddddd", "on": "prompt", "input": "(?i)push", "cue": "x"}]}))


def env_for(run_dir, root):
    """The environment every hook runs in: everything under run_dir, nothing of the live machine."""
    home = os.path.join(run_dir, "home")
    return {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": run_dir, "HARNESS_HOME": home, "HARNESS_STATE_DIR": os.path.join(run_dir, "state"),
            "HARNESS_CACHE": os.path.join(run_dir, "cache"), "CLAUDE_PLUGIN_ROOT": root, "GATES_CONFIG": os.path.join(home, GATES), "ASK_GATE_ROOTS": os.path.join(home, "_gates", "root"), "LANG": "en_US.UTF-8"}


def _edit(home, rel):
    return {"tool_name": "Edit", "tool_input": {"file_path": os.path.join(home, rel), "old_string": "a", "new_string": "b"}}


def cases(home, info):
    """-> {(event, tail): (stdin extras, proof)}; paths inside `home`; info = what build_ledger returned."""
    banner = info["banner"]
    bash = {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}}
    return {
        ("SessionStart", "harness.py hook session-start"): ({"source": "startup", "session_id": SID_NEW}, ("out", "CREW COORDINATOR")),
        ("SessionStart", "ask_gate.py session"): ({"source": "startup", "session_id": "sess-2"}, ("out", "additionalContext")),
        ("PreCompact", "harness.py hook pre-compact"): ({"trigger": "auto"}, ("event", "agent.compacting")),
        ("PreToolUse", "retire_guard.py"): (dict(bash, session_id=SID_RETIRED), ("out", "RETIRED")),
        ("PreToolUse", "dreams_guard.py"): ({"tool_name": "Write", "cwd": os.path.join(home, "elsewhere"),
                                              "tool_input": {"file_path": os.path.join(os.path.dirname(home), "Claude", "99_dreams", "x.md")}}, ("event", "dreams.write_refused")),
        ("PreToolUse", "lesson_cue.py"): (bash, ("out", "Lesson N-aaaaa")),
        ("PreToolUse", "harness.py hook pre-tool-use"): (_edit(home, LEASED), ("out", "lease conflict")),
        ("PreToolUse", "mistake_pointer_hook.py"): ({"tool_name": "mcp__x__harness_record", "tool_input": {"kind": "note", "agent": info["agent0"], "title": "t"},
                                                      "transcript_path": os.path.join(home, TRANSCRIPT)}, ("file", "_harness/mistake-pointers")),
        ("PreToolUse", "ask_gate.py pre"): ({"tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Should the release gate need an ACCEPT line?"}]}},
                                            ("event", "hook.askgate")),
        ("PostToolUse", "propose_hook.py"): ({"tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "Which draft?", "options": [{"label": "A"}, {"label": "B"}]}]},
                                              "tool_response": {"answers": {"Which draft?": "A"}}}, ("event", "proposal.saved")),
        ("PostToolUse", "release_guard.py post"): ({"tool_name": "Bash", "tool_input": {"command": "python3 harness.py publish /x"}}, ("event", "release.postcheck")),
        ("PostToolUse", "harness.py hook post-tool-use"): (dict(_edit(home, EDITED), tool_response={}), ("event", "artifact.versioned")),
        ("PostToolUse", "harness.py hook post-bind"): ({"tool_name": "mcp__x__harness_register", "tool_input": {}, "tool_response": {"banner": banner}}, ("event", "session.bound")),
        ("PostToolUse", "ctx_hook.py"): ({"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {}}, ("file", "state/hook-activity")),
        ("PostToolUse", "harness.py hook idcheck"): ({"tool_name": "mcp__x__harness_send", "tool_input": {"subject": "s", "body": "per D-abcde we ship"}, "tool_response": {}},
                                                     ("event", "hook.idcheck")),
        ("PostToolUse", "attach_hook.py"): ({"tool_name": "Artifact", "tool_input": {"files": {"attach-noop.txt": "x"}},
                                             "tool_response": "Published artifact/Bh95vCZDid4tqAZog6EYP8 (Version 1, version id 1-a)"}, ("file", "_harness/attach_shapes.jsonl")),
        ("SessionEnd", "harness.py hook session-end"): ({"reason": "other"}, ("event", "agent.idle")),
        ("UserPromptSubmit", "ctx_hook.py"): ({"prompt": "hello"}, ("file", "state/harness-idle-" + SID + ".json")),
        ("UserPromptSubmit", "auto_lookup.py"): ({"prompt": "what did we decide about the release gate"}, ("file", "_harness/lookup_spool.jsonl")),
        ("UserPromptSubmit", "correction_hook.py"): ({"prompt": "No, that is wrong, I told you not to do that", "transcript_path": os.path.join(home, TRANSCRIPT)},
                                                     ("file", "_harness/mistake_spool.jsonl")),
        ("UserPromptSubmit", "harness.py hook prompt"): ({"prompt": "remember this: always cite the id", "session_id": SID_RETIRED}, ("out", "RETIRED")),
        ("UserPromptSubmit", "ctx_hook.py virtue"): ({"prompt": "he named a virtue: poetic brevity"}, ("event", "hook.virtue")),
        ("UserPromptSubmit", "lesson_cue.py"): ({"prompt": "push it to main"}, ("out", "Lesson N-ddddd")),
        ("Stop", "harness.py hook stop"): ({"transcript_path": os.path.join(home, TRANSCRIPT)}, ("event", "restore.slot")),
        ("Stop", "ask_gate.py stop"): ({"transcript_path": os.path.join(home, TRANSCRIPT_Q)}, ("event", "hook.askgate")),
    }
