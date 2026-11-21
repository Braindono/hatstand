"""restore_model_warn: one banner line when a chat's model differs from its role's chosen model.

What it does: reads role_models.json and returns "Model: this chat runs X; the role's choice is Y. Switch with /model Y."
Why: a chat on the wrong model was only caught by the next morning's check. Warn only, never block.
Depends on: json, os. File: <ops root>/projects/orchestration/scripts/rules/role_models.json (HARNESS_OPS_ROOT or the default below).
Interface: model_line(role, model) -> str ('' when the role is unlisted, the model matches, or the file is missing/unreadable).
"""
import json
import os

DEFAULT_PATH = os.path.join(os.path.expanduser("~"), "Claude", "Code", "harness-ops", "projects", "orchestration", "scripts", "rules", "role_models.json")


def _path():
    root = os.environ.get("HARNESS_OPS_ROOT")
    if root:
        return os.path.join(root, "projects", "orchestration", "scripts", "rules", "role_models.json")
    return DEFAULT_PATH


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _short(m):
    return str(m or "").strip()


def model_line(role, model):
    """One line, or '' for no warning. Only roles with an explicit entry are checked."""
    d = _load()
    want = (d.get("roles") or {}).get(str(role or "").strip())
    if not want or not _short(model) or _short(model) == "unknown":
        return ""
    want = [str(w) for w in want]
    if _short(model) in want or "*" in want:
        return ""
    aliases = {v: k for k, v in (d.get("aliases") or {}).items()}
    pick = want[0]
    return (f"Model: this chat runs {_short(model)}; the role's choice is {pick}. "
            f"Switch with /model {aliases.get(pick, pick)}.")
