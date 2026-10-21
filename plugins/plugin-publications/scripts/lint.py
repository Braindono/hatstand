#!/usr/bin/env python3
"""
Review lint for Harness plugins and handoff files.
Usage: lint.py <plugin-dir>          plugin gate (ignore list, plugin.json, skills, CHANGELOG, confcheck, /command conflicts)
       lint.py --commands [src-root]  /command conflict check across all custom plugins (default: parent of this plugin)
       lint.py --handoff <file.md>   handoff gate (template skeleton, §0, status open|accepted, budget)
       lint.py --all <root>          skill-name collision check across plugin dirs
       lint.py --self-test           run inline self-test
Exit: 0 all pass, 1 any fail.
"""
import fnmatch, json, os, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IGNORE_DEFAULT = [".DS_Store", "._*", "__pycache__/", "*.pyc"]
DESC_MAX, BODY_MAX, HANDOFF_MAX = 200, 600, 1500
DESC_WARN, DESC_TOTAL_WARN = 150, 1200   # D-6d252: non-failing budget warnings


def exchange():
    return Path(os.environ.get("HARNESS_HOME") or Path.home() / "mnt" / "Exchange")


def ignore_list():
    pats = list(IGNORE_DEFAULT)
    try:
        for line in (exchange() / "_harness" / "ignore").read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line not in pats:
                pats.append(line)
    except OSError:
        pass
    return [p.rstrip("/") for p in pats]


class R:
    def __init__(self): self.ok = self.bad = 0
    def check(self, cond, good, bad):
        if cond: print("✓ " + good); self.ok += 1
        else: print("✕ " + bad); self.bad += 1
        return cond
    def done(self):
        print(f"\nResult: {self.ok} passed, {self.bad} failed"); return self.bad == 0


def short_commands(d):
    """Operator /commands a plugin exposes, prefix stripped: {'/name': 'plugin/skills/x'}; dupes inside d listed separately."""
    d, out, dup = Path(d), {}, []
    for md in sorted(d.glob("skills/*/SKILL.md")):
        fm = re.match(r"^---\n(.*?)\n---", md.read_text(), re.DOTALL)
        meta = fm.group(1) if fm else ""
        if re.search(r"(?m)^user-invocable: *false", meta): continue
        n = re.search(r"(?m)^name: *(.+)$", meta)
        key = "/" + (n.group(1).strip().strip('"') if n else md.parent.name).lower()
        src = f"{d.name}/skills/{md.parent.name}"
        if key in out: dup.append((key, out[key], src))
        out.setdefault(key, src)
    for md in sorted(d.glob("commands/*.md")):
        key, src = "/" + md.stem.lower(), f"{d.name}/commands/{md.name}"
        if key in out: dup.append((key, out[key], src))
        out.setdefault(key, src)
    return out, dup


# Plugins renamed in W1/W2 (D-b2c05; harness-router -> crew-coordinator): their source dirs are retired and skipped by conflict checks.
RETIRED = {"harness-router", "skill-foundry", "agent-delegation", "parsed-job-data", "stop-slop", "design-lite", "plugin-press", "prose-polish"}


def _live(pj):
    return pj.parent.parent.name not in RETIRED


def command_conflicts(root):
    """All /command collisions across every plugin source under root. Returns [(cmd, [sources])]."""
    seen = {}
    for pj in filter(_live, sorted(Path(root).glob("*/.claude-plugin/plugin.json"))):
        cmds, dup = short_commands(pj.parent.parent)
        for k, src in cmds.items(): seen.setdefault(k, []).append(src)
        for k, _, src in dup: seen[k].append(src)
    return sorted((k, v) for k, v in seen.items() if len(v) > 1)


def lint_commands(root):
    c = command_conflicts(root)
    for k, v in c: print(f"✕ {k} collides: {', '.join(v)}")
    if not c: print(f"✓ No /command conflicts under {root}")
    return not c


_OLD_NAMES = ["harness-router", "skill-foundry", "agent-delegation", "parsed-job-data", "stop-slop", "design-lite", "plugin-press", "prose-polish"]
# Old name -> current name, for the message. Only listed renames name a replacement.
_RENAMED_TO = {"harness-router": "crew-coordinator", "plugin-press": "plugin-publications", "prose-polish": "polished-prose"}


def _old_name_hits(text):
    """Return 'hits (hint)' for old plugin /command prefixes in text, or '' if none."""
    pattern = r"/(?:" + "|".join(re.escape(n) for n in _OLD_NAMES) + r"):"
    matches = re.findall(pattern, text)
    if not matches: return ""
    hits = sorted(set(matches))
    hint = "; ".join(f"/{n}: renamed to {_RENAMED_TO[n]}" for n in (m[1:-1] for m in hits) if n in _RENAMED_TO)
    return ", ".join(hits) + (f" ({hint})" if hint else "")


_OLD_SKILLS = {"stop-slop": "polish", "plugin-press": "plugin-publications", "prose-polish": "polished-prose"}
# Lines that state the rename history may keep the old name (e.g. "formerly plugin-press").
_HISTORY_LINE = re.compile(r"formerly|renamed from|hardikpandya/stop-slop", re.I)


def _before_history(line):
    """Envoy note: a history phrase waives only the names that follow it; names before it still count."""
    m = _HISTORY_LINE.search(line)
    return line[:m.start()] if m else line


def check_old_skill_names(d):
    """Old skill names (stop-slop -> polish) in .md/.json outside CHANGELOG (error). Upstream 'hardikpandya/stop-slop' stays."""
    d = Path(d)
    issues = []
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            if f == "CHANGELOG.md" or not f.endswith((".md", ".json")): continue
            path = os.path.join(root, f)
            try: text = open(path).read()
            except Exception: continue
            text = "\n".join(_before_history(l) for l in text.splitlines())
            for old, new in _OLD_SKILLS.items():
                if re.search(r"(?<![\w/-])/?" + re.escape(old) + r"(?![\w-])", text):
                    issues.append(f"{os.path.relpath(path, d)}: old skill name {old} (now {new})")
    return issues


def check_old_plugin_names(d):
    """Check for old plugin name command prefixes outside CHANGELOG (error)."""
    d = Path(d)
    issues = []
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            if f == "CHANGELOG.md": continue  # history lines stay as written
            if f.endswith((".md", ".py")):
                path = os.path.join(root, f)
                try:
                    h = _old_name_hits(open(path).read())
                    if h: issues.append(f"{os.path.relpath(path, d)}: {h}")
                except: pass
    return issues


def _capsule_open(text):
    """True when the frontmatter has a `status:` line whose value is `open`, optionally wrapped in one pair of
    single or double quotes, case-insensitive, trailing whitespace allowed (`open`, `"open"`, `'Open'`)."""
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    return bool(fm and re.search(r"(?mi)^status:[ \t]*(?:\"open\"|'open'|open)[ \t]*$", fm.group(1)))


def lint_corpus(ex):
    """F1: old /plugin: prefixes in live Exchange text: project docs, templates, open handoff capsules.
    Skips _archive, specs, review, notes, and closed capsules."""
    ex = Path(ex)
    files = []
    for name in ("CLAUDE", "PROJECT", "OPERATOR-PREFERENCES", "build_instructions"):
        files += sorted(ex.glob(f"projects/*/{name}.md"))
    files += sorted(ex.glob("templates/*.md"))
    files += [f for f in sorted(ex.glob("projects/*/handoffs/*.md"))
              if _capsule_open(f.read_text(errors="replace"))]
    bad = 0
    for f in files:
        h = _old_name_hits(f.read_text(errors="replace"))
        if h:
            bad += 1
            print(f"✕ {f.relative_to(ex)}: {h}")
    if not bad: print(f"✓ corpus: no old plugin names in {len(files)} live files under {ex}")
    return not bad


def check_namespaced(d):
    """WARN: /<plugin>:<skill> in operator-facing text; bare /<skill> survives renames."""
    out = []
    for path in sorted(Path(d).rglob("*.md")):
        if path.name == "CHANGELOG.md": continue
        for m in set(re.findall(r"(?<![\w:/.])/([a-z0-9][a-z0-9-]*):([a-z0-9][a-z0-9-]*)", path.read_text(errors="ignore"))):
            out.append(f"{path.relative_to(d)}: /{m[0]}:{m[1]} → /{m[1]}")
    return out


def check_skill_name_collisions(root):
    """Check for skill-name collisions across all plugin dirs (--all mode)."""
    seen = {}
    collisions = []
    for pdir in filter(_live, sorted(Path(root).glob("*/.claude-plugin/plugin.json"))):
        plugin_dir = pdir.parent.parent
        cmds, _ = short_commands(plugin_dir)
        for cmd, src in cmds.items():
            skill_name = cmd.lstrip("/")
            if skill_name in seen:
                collisions.append((skill_name, [seen[skill_name], src]))
            else:
                seen[skill_name] = src
    return collisions


def check_frontmatter_yaml(fm):
    """Return an error string if the frontmatter text is not valid YAML, else ''. PyYAML when importable, else stdlib heuristics."""
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml:
        try:
            v = yaml.safe_load(fm)
            return "" if isinstance(v, dict) else "frontmatter is not a mapping"
        except yaml.YAMLError as e:
            return str(e).splitlines()[0] if str(e) else "YAML error"
    for line in fm.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):[ \t]+(.+?)\s*$", line)
        if not m: continue
        v = m.group(2)
        if v[0] in "\"'":
            q = v[0]
            body = v[1:-1] if len(v) > 1 and v[-1] == q else v[1:]
            if len(v) < 2 or v[-1] != q: return f"{m.group(1)}: unterminated quoted scalar"
            if q == '"' and re.search(r'(?<!\\)"', body): return f"{m.group(1)}: unescaped double quote inside double-quoted scalar"
            if q == "'" and re.search(r"(?<!')'(?!')", body): return f"{m.group(1)}: unescaped single quote inside single-quoted scalar"
        elif ": " in v or v.startswith(("[", "{", "&", "*", "!", "|", ">", "%", "@", "`")) and not v.startswith(("[", "{", "|", ">")):
            return f"{m.group(1)}: unquoted ': ' or reserved indicator in plain scalar"
    return ""


def _strict_pairs(pairs):
    keys = [k for k, _ in pairs]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup: raise ValueError(f"duplicate keys {sorted(dup)}")
    return dict(pairs)


def lint_plugin(d):
    d, r = Path(d).resolve(), R()
    if not d.is_dir():
        print(f"✕ {d}: not a directory"); return False
    pats, hits = ignore_list(), []
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != ".git"]
        for n in dirs + files:
            if any(fnmatch.fnmatchcase(n, p) for p in pats):
                hits.append(os.path.relpath(os.path.join(root, n), d))
    r.check(not hits, "No ignored files (D-42db5)", f"Ignored files present (D-42db5): {', '.join(hits[:5])}")

    pj, version = d / ".claude-plugin" / "plugin.json", None
    try:
        data = json.loads(pj.read_text(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"bad constant {c}")),
                          object_pairs_hook=_strict_pairs)
        version = data.get("version", "")
        odd = [k for k in data if not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", k)]
        r.check(re.match(r"^\d+\.\d+\.\d+$", version) and data.get("name") == d.name and not odd,
                f"plugin.json valid ({data.get('name')} {version})",
                f"plugin.json: need semver, name == dir name ({d.name}), plain keys (bad: {odd})")
        a = data.get("author")
        r.check(a is None or (isinstance(a, dict) and isinstance(a.get("name"), str)),
                "plugin.json author ok",
                'plugin.json: author must be an object {"name": ...}; a string drops the plugin\'s skills')
    except Exception as e:
        r.check(False, "", f"plugin.json: missing or invalid JSON ({e})")

    desc_total = 0
    for sk in sorted((d / "skills").glob("*/")) if (d / "skills").is_dir() else []:
        md = sk / "SKILL.md"
        if not md.exists():
            r.check(False, "", f"{sk.name}: SKILL.md not found"); continue
        text = md.read_text()
        fm = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
        if not fm:
            r.check(False, "", f"{sk.name}: no frontmatter"); continue
        yerr = check_frontmatter_yaml(fm.group(1))
        r.check(not yerr, f"{sk.name}: frontmatter YAML valid", f"{sk.name}: frontmatter YAML invalid ({yerr})")
        name = re.search(r"(?m)^name: *(.+)$", fm.group(1))
        desc = re.search(r"(?m)^description: *(.+)$", fm.group(1))
        desc = desc.group(1).strip() if desc else ""
        quoted = len(desc) > 1 and desc[0] == desc[-1] and desc[0] in "\"'"
        body = len(fm.group(2).strip()) / 4
        probs = []
        if not name or not desc: probs.append("missing name/description")
        if len(desc) > DESC_MAX: probs.append(f"description {len(desc)} chars > {DESC_MAX}")
        if desc and not re.search(r"Use (when|for)|Trigger", desc, re.I): probs.append("no trigger clause")
        if desc and re.search(r"<[A-Za-z/!?]", desc): probs.append("XML-like tag in description (Claude app rejects the install)")
        if desc and not quoted and ": " in desc: probs.append("unquoted ': ' in description (breaks YAML; N-ee0fb)")
        if body > BODY_MAX: probs.append(f"body {body:.0f} tokens > {BODY_MAX}")
        desc_total += len(desc)
        if len(desc) > DESC_WARN:
            print(f"⚠ {sk.name}: description {len(desc)} chars > {DESC_WARN} (warn, D-6d252)")
        r.check(not probs, f"{sk.name}: valid (desc {len(desc)} chars, body {body:.0f} tokens)", f"{sk.name}: {'; '.join(probs)}")

    if desc_total > DESC_TOTAL_WARN:
        print(f"⚠ descriptions total {desc_total} chars > {DESC_TOTAL_WARN} (warn, D-6d252)")
    else:
        print(f"· descriptions total {desc_total} chars (≤ {DESC_TOTAL_WARN})")

    cl = d / "CHANGELOG.md"
    r.check(cl.exists() and version and f"## {version}" in cl.read_text(),
            f"CHANGELOG: entry for {version}", f"CHANGELOG: missing or no entry for {version}")

    c = [(k, v) for k, v in command_conflicts(d.resolve().parent) if any(s.startswith(d.name + "/") for s in v)]
    r.check(not c, "/commands: no conflicts with other custom plugins",
            "/command conflicts (rename the skill): " + "; ".join(f"{k} in {', '.join(v)}" for k, v in c))

    old = check_old_plugin_names(d)
    r.check(not old, "old plugin names: none used as /command prefix",
            "old plugin name as /command prefix (use the bare /command): " + "; ".join(old))
    oldsk = check_old_skill_names(d)
    r.check(not oldsk, "old skill names: none",
            "; ".join(oldsk))
    for w in check_namespaced(d): print(f"⚠ namespaced command: {w}")

    cc = HERE / "confcheck.py"
    if r.check(cc.exists(), "confcheck present", f"confcheck missing at {cc}"):
        res = subprocess.run([sys.executable, str(cc), str(d)], capture_output=True, text=True, timeout=30)
        r.check(res.returncode == 0, "confcheck: passed",
                f"confcheck: exit {res.returncode}\n  " + res.stdout.strip().replace("\n", "\n  "))
    return r.done()


def lint_handoff(f):
    f, r = Path(f), R()
    if not f.is_file():
        print(f"✕ {f}: not a file"); return False
    t = f.read_text()
    fm = re.match(r"^---\n(.*?)\n---\n", t, re.DOTALL)
    meta = dict(re.findall(r"(?m)^(\w+): *(.*?)\s*(?:#.*)?$", fm.group(1))) if fm else {}
    r.check(bool(fm), "frontmatter present", "frontmatter missing (copy the template skeleton)")
    for k in ("handoff", "from", "model", "project", "created", "status", "budget"):
        r.check(bool(meta.get(k)), f"field {k}", f"field {k} missing")
    fl = re.search(r"(?m)^from: *(.*)$", fm.group(1) if fm else "")
    role = (re.search(r"\(([^)]*)\)", fl.group(1)) or [None, ""])[1] if fl else ""
    if re.search(r"envoy|lead|steward", role or "", re.I):   # D-15566 P6: judgment roles need a known model
        r.check(meta.get("model", "unknown").lower() != "unknown", f"model known for judgment role {role}",
                f"model: unknown not allowed for judgment role '{role}' (D-15566 P6): use your exact model id")
    # S7 (D-4ee13): the ledger is the source of handoff status; frontmatter is open (new) or accepted (successor set it)
    r.check(meta.get("status") in ("open", "accepted"), f"status: {meta.get('status')}",
            f"status is '{meta.get('status')}'; must be open (new) or accepted (set by the successor)")
    r.check(meta.get("project") and "<" not in meta.get("project", ""), "project set", "project missing or placeholder")
    r.check("## 0. Bootstrap" in t, "§0 Bootstrap present", "§0 Bootstrap missing")
    frm = meta.get("from", "")
    if frm != "none":
        r.check(re.search(r"successor_of=[0-9a-f]{8}", t), "successor_of=<short-id> in §0", "§0 lacks successor_of=<8-hex short id>")
    left = sorted(set(re.findall(r"<(?:project|project-slug|short-id|role|yyyy-mm-dd|Sobriquet|outgoing-sobriquet|one-line mission|model-id)>", t)))
    r.check(not left, "no template placeholders left", f"unfilled placeholders: {left}")
    r.check("HOW TO FILL" not in t, "template comment block removed", "remove the HOW TO comment block")
    tok = len(t) / 4
    r.check(tok <= HANDOFF_MAX, f"budget {tok:.0f} ≤ {HANDOFF_MAX} tokens", f"budget {tok:.0f} > {HANDOFF_MAX} tokens")
    return r.done()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--self-test"]:
        bad = 0
        for n in ("plugin-press", "prose-polish", "harness-router"):
            if not _old_name_hits(f"run /{n}:list"): print(f"✕ self-test: /{n}: not flagged"); bad += 1
        if _old_name_hits("run /list"): print("✕ self-test: bare /list flagged"); bad += 1
        import tempfile
        for n in ("plugin-press", "prose-polish"):
            with tempfile.TemporaryDirectory() as t:
                Path(t, "a.md").write_text(f"use {n} here\n")
                Path(t, "b.md").write_text(f"formerly {n}\n")
                got = check_old_skill_names(t)
                if len(got) != 1 or not got[0].startswith("a.md"): print(f"✕ self-test: skill-name case {n}: {got}"); bad += 1
        with tempfile.TemporaryDirectory() as t:
            Path(t, "a.md").write_text("use prose-polish; formerly plugin-press\n")
            Path(t, "b.md").write_text("formerly plugin-press, prose-polish\n")
            got = check_old_skill_names(t)
            if len(got) != 1 or not got[0].startswith("a.md") or "prose-polish" not in got[0]:
                print(f"✕ self-test: history waiver scope: {got}"); bad += 1
        for label, fm, want_bad in (
            ("nested double quotes", 'name: x\ndescription: "Use when: "foo" bar"', True),
            ("single-quoted inner double", "name: x\ndescription: 'Use when: \"foo\" bar'", False),
            ("unquoted Use when: x", "name: x\ndescription: Use when: x", True),
        ):
            got = bool(check_frontmatter_yaml(fm))
            if got != want_bad: print(f"✕ self-test: yaml case {label}: invalid={got}"); bad += 1
        if bad: sys.exit(1)
        print("✓ Self-test passed")
        sys.exit(0)
    if a[:1] == ["--handoff"] and len(a) == 2: sys.exit(0 if lint_handoff(a[1]) else 1)
    if a[:1] == ["--corpus"] and len(a) == 2: sys.exit(0 if lint_corpus(a[1]) else 1)
    if a[:1] == ["--commands"] and len(a) <= 2: sys.exit(0 if lint_commands(a[1] if len(a) == 2 else HERE.parent.parent) else 1)
    if a[:1] == ["--all"] and len(a) == 2:
        root = Path(a[1])
        c = check_skill_name_collisions(root)
        for skill, sources in c:
            print(f"✕ {skill} collision: {', '.join(sources)}")
        if not c: print(f"✓ No skill-name collisions under {root}")
        sys.exit(0 if not c else 1)
    if len(a) == 1: sys.exit(0 if lint_plugin(a[0]) else 1)
    print(__doc__, file=sys.stderr); sys.exit(1)
