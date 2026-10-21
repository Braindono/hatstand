#!/usr/bin/env python3
"""Per-session usage record deriver from harness events."""

import json
import sys

def load_events(path):
    """Load events from jsonl, tolerating bad lines."""
    events = []
    with open(path) as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except:
                pass
    return events

def process_events(events):
    """Build usage records from events."""
    agents = {}
    
    for evt in events:
        evt_type = evt.get('type')
        data = evt.get('data', {})
        ts = evt.get('ts')
        
        if evt_type == 'agent.registered':
            agent_id = data.get('id', '')
            if agent_id:
                agents[agent_id] = {
                    'agent': agent_id[:8],
                    'sobriquet': data.get('sobriquet'),
                    'role': None,
                    'project': data.get('project'),
                    'model': (lambda m: None if m in (None, 'unknown') else m)(data.get('model') or (data.get('config') or {}).get('model')),
                    'start': ts,
                    'end': None,
                    'active': True,
                    'ctx_peak': None,
                    'ctx_base': None,
                    'ctx_peak_pct': None,
                    'handoffs': 0,
                    'msgs_sent': 0,
                    'input_tokens': None,
                    'output_tokens': None,
                    'cache_read_tokens': None,
                    'src': 'events'
                }
        elif evt_type == 'role.assigned':
            agent_id = data.get('agent', '')
            if agent_id in agents:
                agents[agent_id]['role'] = data.get('role')
        elif evt_type == 'agent.synced':
            agent_id = data.get('id') or evt.get('actor', '')
            summary = dict(data.get('summary') or {})
            for k in ('ctx', 'ctx_base'):
                if data.get(k) is not None: summary[k] = data[k]
            if agent_id in agents and summary:
                ctx = summary.get('ctx')
                if ctx is not None:
                    p = agents[agent_id]['ctx_peak']
                    agents[agent_id]['ctx_peak'] = ctx if p is None else max(p, ctx)
                ctx_base = summary.get('ctx_base')
                if ctx_base is not None:
                    agents[agent_id]['ctx_base'] = ctx_base
                if ts and agents[agent_id]['end'] is None:
                    agents[agent_id]['end'] = ts
        elif evt_type in ('agent.superseded', 'agent.retired'):
            agent_id = data.get('id', '')
            if agent_id in agents:
                agents[agent_id]['active'] = False
                agents[agent_id]['end'] = ts
        elif evt_type == 'message.sent':
            from_id = data.get('from', '')
            if from_id in agents:
                agents[from_id]['msgs_sent'] += 1
                if data.get('kind') == 'handoff':
                    agents[from_id]['handoffs'] += 1
                if ts and agents[from_id]['end'] is None:
                    agents[from_id]['end'] = ts
    
    for agent_id, rec in agents.items():
        if rec['ctx_peak']:
            win = 1000000 if '1m' in (rec['model'] or '') else 200000
            rec['ctx_peak_pct'] = round(100 * rec['ctx_peak'] / win, 1)
    
    return agents

def run_self_test():
    """Run self-tests."""
    e1 = [
        {'type': 'agent.registered', 'actor': 'a', 'data': {'id': 'aaaa0001', 'sobriquet': 'A', 'project': 'p1'}, 'ts': 100},
        {'type': 'agent.synced', 'actor': 'a', 'data': {'id': 'aaaa0001', 'summary': {'ctx': 50000, 'ctx_base': 100000}}, 'ts': 150},
        {'type': 'agent.superseded', 'actor': 'a', 'data': {'id': 'aaaa0001', 'successor': 'b'}, 'ts': 200},
    ]
    a1 = process_events(e1)
    r1 = a1.get('aaaa0001')
    assert r1 and not r1['active'] and r1['end'] == 200, f"T1 failed"
    
    e2 = [
        {'type': 'agent.registered', 'actor': 'b', 'data': {'id': 'bbbb0002', 'sobriquet': 'B', 'project': 'p2'}, 'ts': 100},
        {'type': 'message.sent', 'actor': 'b', 'data': {'from': 'bbbb0002', 'kind': 'handoff'}, 'ts': 150},
    ]
    a2 = process_events(e2)
    r2 = a2.get('bbbb0002')
    assert r2 and r2['active'] and r2['handoffs'] == 1, f"T2 failed"
    
    e3 = [
        {'type': 'agent.registered', 'actor': 'c', 'data': {'id': 'cccc0003', 'sobriquet': 'C', 'project': 'p3'}, 'ts': 100},
        {'type': 'agent.retired', 'actor': 'c', 'data': {'id': 'cccc0003', 'reason': 'timeout'}, 'ts': 150},
    ]
    a3 = process_events(e3)
    r3 = a3.get('cccc0003')
    assert r3 and r3['ctx_peak'] is None and r3['ctx_base'] is None, f"T3 failed"
    
    return True

def run_summary(records):
    """Print summary line."""
    active_count = sum(1 for r in records if r['active'])
    ctx_peaks = [r['ctx_peak'] for r in records if r['ctx_peak'] is not None]
    median_ctx = None
    if ctx_peaks:
        ctx_peaks.sort()
        mid = len(ctx_peaks) // 2
        if len(ctx_peaks) % 2 == 0:
            median_ctx = (ctx_peaks[mid - 1] + ctx_peaks[mid]) // 2
        else:
            median_ctx = ctx_peaks[mid]
    
    total_handoffs = sum(r['handoffs'] for r in records)
    print(f"usage: n={len(records)} active={active_count} peak_ctx_med={median_ctx} handoffs={total_handoffs}")

def main():
    import os
    ex = os.path.expanduser('~/mnt/Exchange')
    events_file = os.environ.get('HARNESS_EVENTS', ex + '/_harness/events.jsonl')
    output_file = ex + '/projects/orchestration/digests/usage.jsonl'
    self_test = False
    summary = False
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--events':
            events_file = args[i + 1]
            i += 2
        elif args[i] == '--out':
            output_file = args[i + 1]
            i += 2
        elif args[i] == '--self-test':
            self_test = True
            i += 1
        elif args[i] == '--summary':
            summary = True
            i += 1
        elif args[i] == '--dry':
            output_file = None
            i += 1
        else:
            i += 1
    
    if self_test:
        try:
            if run_self_test():
                print("PASS")
                return 0
        except AssertionError as e:
            print(f"FAIL: {e}")
            return 1
    
    if events_file:
        events = load_events(events_file)
        agents = process_events(events)
        records = list(agents.values())
        records.sort(key=lambda r: (r['start'] or '', r['agent']))
        
        if output_file:
            with open(output_file, 'w') as f:
                for rec in records:
                    f.write(json.dumps(rec) + '\n')
        
        if summary:
            run_summary(records)
        
        return 0
    
    return 1

if __name__ == '__main__':
    sys.exit(main())
