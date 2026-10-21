#!/usr/bin/env python3
"""
Confidentiality gate: scan a plugin dir for denylist terms.
Usage: python3 confcheck.py <plugin-dir>
Exit: 0 (ok), 1 (hits found), 2 (denylist missing)
"""

import sys
import os
import re
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: confcheck.py <plugin-dir>", file=sys.stderr)
        sys.exit(1)
    
    plugin_dir = Path(sys.argv[1])
    if not plugin_dir.is_dir():
        print(f"Error: {plugin_dir} is not a directory", file=sys.stderr)
        sys.exit(1)
    
    # Load denylist
    exchange = Path(os.environ.get("HARNESS_HOME") or Path.home() / "mnt" / "Exchange")
    denylist_path = exchange / "resources" / "private" / "confidential.denylist"
    if not denylist_path.exists():
        print("confcheck: no denylist")
        sys.exit(2)
    
    terms = []
    with open(denylist_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                terms.append(re.compile(line, re.IGNORECASE))
    
    if not terms:
        print("confcheck ok")
        sys.exit(0)
    
    # Scan plugin files
    hits = []
    for file_path in plugin_dir.rglob('*'):
        if not file_path.is_file():
            continue
        
        # Skip binary files, assets and ignore-list paths (D-42db5)
        if file_path.suffix in ['.png', '.jpg', '.gif', '.zip', '.pyc']:
            continue
        rel_parts = file_path.relative_to(plugin_dir).parts
        if any(p == '.DS_Store' or p.startswith('._') or p in ('__pycache__', '.git') for p in rel_parts):
            continue
        is_manifest = rel_parts[-2:] == ('.claude-plugin', 'plugin.json')
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for lineno, line in enumerate(f, 1):
                    # Check for allowlist override
                    if '<!-- confcheck:allow' in line:
                        continue
                    # plugin.json "author" is exempt by rule (metadata, not content)
                    if is_manifest and re.match(r'\s*"author"\s*:', line):
                        continue
                    
                    for term in terms:
                        if term.search(line):
                            rel_path = file_path.relative_to(plugin_dir)
                            hits.append(f"{rel_path}:{lineno} {term.pattern}")
        except Exception as e:
            pass
    
    if hits:
        for hit in hits:
            print(hit)
        sys.exit(1)
    else:
        print("confcheck ok")
        sys.exit(0)

if __name__ == '__main__':
    main()
