"""cc 0.21.0 M0 (A-d693a item 4, curator spec v2 section 4a gap 6): two MCP server processes on ONE home and ONE state folder (what two
chats on one machine are), driven at the same time with 1,000 mixed calls. Passes only if the hash chain verifies, no ledger line is lost or
duplicated, every message and record appears exactly once, each message reaches its addressee, leases end clean, and neither client's
replies show the other's per-session data. If this fails, nothing else in 0.21.0 is built.
Negative control (10-30, scratch copy outside this tree): with the ledger lock disabled (scripts/harness.py line 1119 `fcntl.flock(lf,
fcntl.LOCK_EX)` replaced by `pass`; patched harness.py sha256 8529d2babff0), the process test FAILS at the chain check, `Harness.verify()`:
'duplicate seq (concurrent writers forked the chain)' and 'prev hash mismatch' at seq 25, 323, 464, 471, ... (50 problems listed). The same
test passes with the lock in place, so it can catch a real race. The in-process interleaved test runs one request at a time and is not a race test.
Run: python3 -B tests/test_c210_m0_two_clients.py"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _env  # noqa: F401  isolate HOME and HARNESS_* first
import json, os, re, subprocess, sys, tempfile, threading, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(HERE, "..", "scripts", "mcp_server.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import harness as H

MODEL = "claude-sonnet-5-5"
ITER = int(os.environ.get("M0_ITER", "100"))      # 100 iterations x 7 calls x 2 clients = 1,400 calls (plus register and claim/release)


class Client:
    def __init__(self, env, name):
        self.name, self.n, self.texts, self.errors = name, 0, [], []
        self.p = subprocess.Popen([sys.executable, "-B", SRV], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=env, text=True, bufsize=1)
        self.rpc("initialize", {"protocolVersion": "2025-06-18"})
        self.calls = 0

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        return json.loads(line)

    def tool(self, name, **a):
        r = self.rpc("tools/call", {"name": name, "arguments": a})
        self.calls += 1
        if "result" not in r:
            self.errors.append((name, r))
            return ""
        txt = r["result"]["content"][0]["text"]
        if r["result"].get("isError"):
            self.errors.append((name, txt[:200]))
        self.texts.append((name, txt))
        return txt

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=20)
        except Exception:
            self.p.kill()


def run_client(c, me, other, claim_path, out):
    try:
        for i in range(ITER):
            c.tool("harness_sync", agent=me, do_only=True)
            c.tool("harness_inbox", agent=me, peek=True)                        # 0.21.0 items 2 and 3 join the mixed set (M2)
            c.tool("harness_admin", op="approvals_pending", agent=me)
            c.tool("harness_inbox", agent=me)
            c.tool("harness_send", agent=me, to=other, body="M0S-%s-%03d token" % (c.name, i), subject="m0", kind="message")
            c.tool("harness_record", agent=me, kind="note", title="M0R-%s-%03d" % (c.name, i), body="m0 record")
            c.tool("harness_admin", op="approvals", agent=me)
            if i % 20 == 0:
                c.tool("harness_claim", agent=me, path=claim_path)
                c.tool("harness_release", agent=me)
    except Exception as e:      # a dead server or a bad reply is a failure, shown by the assertions below
        out.append(repr(e))


class TwoClients(unittest.TestCase):
    def test_two_server_processes_on_one_home(self):
        tmp = tempfile.mkdtemp(prefix="m0-")
        home = os.path.join(tmp, "Exchange")
        os.makedirs(os.path.join(home, "_harness"))
        env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_")}
        env.update(HARNESS_HOME=home, HARNESS_STATE_DIR=os.path.join(tmp, "state"), HARNESS_STATE_CACHE="0", PYTHONDONTWRITEBYTECODE="1")
        A, B = Client(env, "A"), Client(env, "B")
        self.addCleanup(A.close)
        self.addCleanup(B.close)
        ids = {}
        for c in (A, B):
            t = c.tool("harness_register", project="harness-ops", model=MODEL, task="m0 client " + c.name)
            m = re.search(r"#([0-9a-f]{8})", t)
            self.assertTrue(m, t[:300])
            ids[c.name] = m.group(1)
        self.assertNotEqual(ids["A"], ids["B"])
        fails = []
        ts = [threading.Thread(target=run_client, args=(A, ids["A"], ids["B"], os.path.join(home, "m0-a.txt"), fails)),
              threading.Thread(target=run_client, args=(B, ids["B"], ids["A"], os.path.join(home, "m0-b.txt"), fails))]
        [t.start() for t in ts]
        [t.join(600) for t in ts]
        self.assertEqual(fails, [])
        self.assertEqual(A.errors + B.errors, [], "tool errors")
        self.assertGreaterEqual(A.calls + B.calls, 1000)
        A.close()
        B.close()
        h = H.Harness(home)
        v = h.verify()
        self.assertTrue(v["ok"], v["problems"])                             # chain verifies, no forked or duplicate seq
        evs = h.store.read_all()
        seqs = [e["seq"] for e in evs]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)), "a ledger line was lost or duplicated")
        lines = [json.dumps(e, sort_keys=True) for e in evs]
        for c in "AB":
            for i in range(ITER):
                for pre in ("M0S", "M0R"):
                    tok = "%s-%s-%03d" % (pre, c, i)
                    n = sum(1 for ln in lines if tok in ln)
                    self.assertEqual(n, 1, "%s appears in %d events" % (tok, n))
        # every message reached exactly its addressee
        st = h.state()
        full = {ids["A"]: None, ids["B"]: None}
        for k in list(st.agents):
            for s in full:
                if k.startswith(s):
                    full[s] = k
        for sender, addressee in (("A", "B"), ("B", "A")):
            ms = [m for m in st.messages.values() if ("M0S-%s-" % sender) in (m.get("body") or "")]
            self.assertEqual(len(ms), ITER)
            for m in ms:
                self.assertEqual(list(m.get("to_resolved") or []), [full[ids[addressee]]], m.get("to_resolved"))
        # leases ended clean
        self.assertEqual(dict(st.leases), {}, "a lease was left held")
        # neither client's replies show the other's per-session data: a sync reply names only its own agent, and an inbox lists only mail to it
        for c, other in ((A, "B"), (B, "A")):
            syncs = [t for n, t in c.texts if n == "harness_sync"]
            self.assertTrue(syncs)
            self.assertTrue(any("#" + ids[c.name] in t for t in syncs), "no sync reply named its own agent")      # the header line, when shown
            for t in syncs:
                self.assertNotIn("#" + ids[other], t)
            for n, t in c.texts:
                if n == "harness_inbox":
                    self.assertNotIn("M0S-%s-" % c.name, t)             # never its own sent mail


class TwoClientsOneServerObject(unittest.TestCase):
    """Two clients' requests INTERLEAVED on ONE in-process server object, one request at a time, as one stdio server would serve them.
    (Two threads on one server object are not a supported shape: its corpus index is a SQLite handle bound to the creating thread, so the
    server answers one request at a time. Found by the first version of this test, 10-30.)"""
    def test_interleaved_requests_on_one_harness(self):
        import mcp_server as MS
        tmp = tempfile.mkdtemp(prefix="m0b-")
        home = os.path.join(tmp, "Exchange")
        os.makedirs(os.path.join(home, "_harness"))
        e = mock.patch.dict(os.environ, {"HARNESS_STATE_CACHE": "0"})      # never leave it set for the other tests in one process
        e.start()
        self.addCleanup(e.stop)
        h = H.Harness(home)
        ids = {c: h.register(project="harness-ops", model=MODEL, task="m0b " + c)["id"] for c in "AB"}
        seen = {"A": [], "B": []}
        for i in range(ITER):
            for c, o in (("A", "B"), ("B", "A")):
                me, other = ids[c], ids[o]
                seen[c].append(MS.call(h, "harness_sync", {"agent": me, "do_only": True}))
                seen[c].append(MS.call(h, "harness_inbox", {"agent": me, "peek": True}))
                MS.call(h, "harness_admin", {"op": "approvals_pending", "agent": me})
                seen[c].append(MS.call(h, "harness_inbox", {"agent": me}))
                MS.call(h, "harness_send", {"agent": me, "to": other, "body": "M0S-%s-%03d token" % (c, i), "subject": "m0", "kind": "message"})
                MS.call(h, "harness_record", {"agent": me, "kind": "note", "title": "M0R-%s-%03d" % (c, i), "body": "m0 record"})
                MS.call(h, "harness_admin", {"op": "approvals", "agent": me})
        v = h.verify()
        self.assertTrue(v["ok"], v["problems"])
        evs = h.store.read_all()
        self.assertEqual([e["seq"] for e in evs], list(range(1, len(evs) + 1)), "a ledger line was lost or duplicated")
        lines = [json.dumps(e, sort_keys=True) for e in evs]
        for c in "AB":
            for i in range(ITER):
                for pre in ("M0S", "M0R"):
                    tok = "%s-%s-%03d" % (pre, c, i)
                    self.assertEqual(sum(1 for ln in lines if tok in ln), 1, tok)
        for c, o in (("A", "B"), ("B", "A")):               # one client never sees the other's session data
            for r in seen[c]:
                self.assertNotIn("#" + ids[o][:8], r["text"] if isinstance(r, dict) and "text" in r else str(r))


if __name__ == "__main__":
    unittest.main()
