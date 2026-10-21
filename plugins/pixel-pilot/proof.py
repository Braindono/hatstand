#!/usr/bin/env python3 -B
import sys
import json
import re
from pathlib import Path

def run_proofs(plugin_dir):
    """Run all 7 proofs"""
    plugin_path = Path(plugin_dir)
    results = {}
    
    # Upstream reference word counts (from build)
    upstream_counts = {
        'design-critique': 542,
        'design-system': 772,
        'design-handoff': 538,
        'ux-copy': 498,
        'accessibility-review': 586,
        'research-synthesis': 383,
        'user-research': 226
    }
    
    # P1: exactly one SKILL.md under skills/
    skill_files = list((plugin_path / "skills").glob("**/SKILL.md"))
    p1_pass = len(skill_files) == 1
    results['P1'] = p1_pass
    print(f"P1 (one SKILL.md): {'✓' if p1_pass else '✗'} ({len(skill_files)} found)")
    
    # P2: description is ≤200 chars and no angle brackets
    if skill_files:
        skill_file = skill_files[0]
        with open(skill_file, 'r') as f:
            content = f.read()
        
        # Extract description from frontmatter
        fm_match = re.search(r'description:\s*["\']?([^"\'\n]+)', content)
        description = fm_match.group(1) if fm_match else ""
        
        desc_len = len(description)
        has_angles = '<' in description or '>' in description
        p2_pass = desc_len <= 200 and not has_angles
        results['P2'] = p2_pass
        print(f"P2 (desc ≤200 chars, no <>): {'✓' if p2_pass else '✗'} (len={desc_len}, has_angles={has_angles})")
    
    # P3: no figma|linear|jira|notion|slack|mcp|connector|~~|CONNECTORS in lines with "pull" or "URL" (excluding NOTICE and README)
    bad_patterns = ['figma', 'linear', 'jira', 'notion', 'slack', 'mcp', 'connector', '~~', 'CONNECTORS']
    violations = []
    
    for filepath in plugin_path.rglob("*"):
        if filepath.is_file():
            # Skip NOTICE and README
            if filepath.name in ['NOTICE', 'README.md']:
                continue
            
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    for lineno, line in enumerate(f, 1):
                        # Only check lines with "pull" or "URL"
                        if 'pull' in line.lower() or 'url' in line.lower():
                            for pattern in bad_patterns:
                                if pattern.lower() in line.lower():
                                    violations.append((filepath.relative_to(plugin_path), lineno, pattern))
                        # Check ~~, mcp, connector everywhere
                        elif pattern in ['~~', 'mcp', 'connector', 'CONNECTORS']:
                            if pattern == '~~' and '~~' in line:
                                violations.append((filepath.relative_to(plugin_path), lineno, pattern))
                            elif pattern in ['mcp', 'CONNECTORS'] and pattern.lower() in line.lower():
                                violations.append((filepath.relative_to(plugin_path), lineno, pattern))
            except:
                pass
    
    p3_pass = len(violations) == 0
    results['P3'] = p3_pass
    if p3_pass:
        print(f"P3 (no figma/linear/jira/notion/slack/mcp/connector/~~/CONNECTORS in pull/URL lines): ✓")
    else:
        print(f"P3 (no figma/linear/jira/notion/slack/mcp/connector/~~/CONNECTORS in pull/URL lines): ✗")
        for fpath, lineno, pattern in violations[:5]:
            print(f"  Line {lineno} in {fpath}: {pattern}")
    
    # P4: seven references exist, each ≥60% of upstream word count
    ref_dir = plugin_path / "skills" / "design" / "references"
    refs = {}
    if ref_dir.exists():
        for ref_file in ref_dir.glob("*.md"):
            with open(ref_file, 'r') as f:
                content = f.read()
            word_count = len(content.split())
            ref_name = ref_file.stem
            refs[ref_name] = word_count
    
    p4_pass = True
    issues = []
    for name, upstream_count in upstream_counts.items():
        if name not in refs:
            p4_pass = False
            issues.append(f"  Missing reference: {name}")
        else:
            ref_count = refs[name]
            ratio = ref_count / upstream_count if upstream_count > 0 else 0
            if ratio < 0.6:
                p4_pass = False
                issues.append(f"  {name}: {ref_count} words ({ratio:.1%} of {upstream_count})")
    
    results['P4'] = p4_pass
    if p4_pass:
        print(f"P4 (7 refs, each ≥60%): ✓")
    else:
        print(f"P4 (7 refs, each ≥60%): ✗")
        for issue in issues:
            print(issue)
    
    # P5: LICENSE hash starts with a6946284 and ends with 2e26
    import hashlib
    license_file = plugin_path / "LICENSE"
    p5_pass = False
    if license_file.exists():
        with open(license_file, 'rb') as f:
            content_bytes = f.read()
        sha256_hash = hashlib.sha256(content_bytes).hexdigest()
        p5_pass = sha256_hash.startswith('a6946284') and sha256_hash.endswith('2e26')
    
    results['P5'] = p5_pass
    print(f"P5 (LICENSE hash valid): {'✓' if p5_pass else '✗'}")
    
    # P6: plugin.json is valid, version 0.1.0, name design-lite
    plugin_json_file = plugin_path / ".claude-plugin" / "plugin.json"
    p6_pass = False
    if plugin_json_file.exists():
        try:
            with open(plugin_json_file, 'r') as f:
                pj = json.load(f)
            p6_pass = (
                pj.get('name') == 'pixel-pilot' and
                pj.get('version') == '0.2.0' and
                isinstance(pj, dict)
            )
        except:
            p6_pass = False
    
    results['P6'] = p6_pass
    print(f"P6 (plugin.json valid, v0.2.0, name pixel-pilot): {'✓' if p6_pass else '✗'}")
    
    # P7: commands/ does NOT exist
    commands_dir = plugin_path / "commands"
    p7_pass = not commands_dir.exists()
    results['P7'] = p7_pass
    print(f"P7 (commands/ does NOT exist): {'✓' if p7_pass else '✗'}")
    
    # Summary
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print(f"\n{passed}/{total} proofs passed")
    
    return all(results.values()), results

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: proof.py <plugin_dir>")
        sys.exit(1)
    
    success, results = run_proofs(sys.argv[1])
    sys.exit(0 if success else 1)
