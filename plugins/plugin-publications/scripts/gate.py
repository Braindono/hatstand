#!/usr/bin/env python3
"""
Release gate for plugin-publications: evaluates candidate models against current.
Usage: gate.py <eval-input.json>     evaluate and gate
       gate.py --self-test           run inline self-test
Exit: 0 ACCEPT, 1 REJECT
"""
import json, sys, math
from pathlib import Path


def evaluate_gate(tasks):
    """
    Evaluate tasks with dev/train split.
    Rules:
    - Use dev split only; any null score → FAIL "ungraded episode"
    - d = mean(cand−cur), SE = stdev(diffs)/sqrt(n)
    - ACCEPT if d > SE, or |d| ≤ SE and mean cost_cand < mean cost_cur
    - else REJECT
    - If no dev rows: WARN "dev==train", fall back to all rows
    """
    dev_tasks = [t for t in tasks if t.get("split") == "dev"]
    use_tasks = dev_tasks
    warn = None
    
    if not dev_tasks:
        use_tasks = tasks
        warn = "dev==train"
    
    if not use_tasks:
        return "REJECT", 0, 0, 0, None, None, warn
    
    # Check for ungraded episodes
    for t in use_tasks:
        if t.get("current") is None or t.get("candidate") is None:
            return "REJECT", 0, 0, 0, None, None, "ungraded episode"
    
    # Calculate differences
    diffs = [t.get("candidate", 0) - t.get("current", 0) for t in use_tasks]
    n = len(diffs)
    d = sum(diffs) / n if n > 0 else 0
    
    # Calculate SE
    if n > 1:
        var = sum((x - d) ** 2 for x in diffs) / n
        stdev = math.sqrt(var)
        se = stdev / math.sqrt(n)
    else:
        se = 0
    
    # Get costs
    cost_cur = sum(t.get("cost_cur", 0) for t in use_tasks) / n if n > 0 else 0
    cost_cand = sum(t.get("cost_cand", 0) for t in use_tasks) / n if n > 0 else 0
    
    # Decision logic
    if d > se or (abs(d) <= se and cost_cand < cost_cur):
        decision = "ACCEPT"
    else:
        decision = "REJECT"
    
    return decision, d, se, n, cost_cur, cost_cand, warn


def format_gate_line(decision, d, se, n, cost_cur, cost_cand, warn):
    """Format the one-line gate output."""
    if n == 0:
        return f"gate: {decision}"
    
    cost_str = f"{cost_cur:.1f}→{cost_cand:.1f}" if cost_cur and cost_cand else "n/a"
    warn_str = f" {warn}" if warn else ""
    return f"gate: {decision} d={d:.3f} SE={se:.3f} n={n} cost={cost_str}{warn_str}"


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        # Self-test with 3 inline cases
        # Case 1: ACCEPT (d > SE)
        tasks1 = [
            {"id": "t1", "split": "dev", "current": 0.8, "candidate": 0.85, "cost_cur": 100, "cost_cand": 95},
            {"id": "t2", "split": "dev", "current": 0.8, "candidate": 0.86, "cost_cur": 100, "cost_cand": 95},
        ]
        decision1, d1, se1, n1, cc1, cand1, w1 = evaluate_gate(tasks1)
        print(f"Test 1 (ACCEPT): {format_gate_line(decision1, d1, se1, n1, cc1, cand1, w1)}")
        assert decision1 == "ACCEPT", f"Test 1 failed: expected ACCEPT, got {decision1}"
        
        # Case 2: REJECT
        tasks2 = [
            {"id": "t1", "split": "dev", "current": 0.9, "candidate": 0.85, "cost_cur": 100, "cost_cand": 95},
            {"id": "t2", "split": "dev", "current": 0.9, "candidate": 0.84, "cost_cur": 100, "cost_cand": 95},
        ]
        decision2, d2, se2, n2, cc2, cand2, w2 = evaluate_gate(tasks2)
        print(f"Test 2 (REJECT): {format_gate_line(decision2, d2, se2, n2, cc2, cand2, w2)}")
        assert decision2 == "REJECT", f"Test 2 failed: expected REJECT, got {decision2}"
        
        # Case 3: ungraded
        tasks3 = [
            {"id": "t1", "split": "dev", "current": 0.8, "candidate": None, "cost_cur": 100, "cost_cand": 95},
        ]
        decision3, d3, se3, n3, cc3, cand3, w3 = evaluate_gate(tasks3)
        print(f"Test 3 (ungraded): {format_gate_line(decision3, d3, se3, n3, cc3, cand3, w3)}")
        assert decision3 == "REJECT", f"Test 3 failed: expected REJECT, got {decision3}"
        
        print("\n✓ All self-tests passed")
        sys.exit(0)
    
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    
    try:
        data = json.loads(Path(sys.argv[1]).read_text())
        tasks = data.get("tasks", [])
        decision, d, se, n, cost_cur, cost_cand, warn = evaluate_gate(tasks)
        print(format_gate_line(decision, d, se, n, cost_cur, cost_cand, warn))
        sys.exit(0 if decision == "ACCEPT" else 1)
    except Exception as e:
        print(f"✕ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
