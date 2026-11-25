#!/usr/bin/env python3
"""0.3.12 selftest: a CORRECTION-only reply after Stop-hook feedback in the same turn owes no table; nothing else is
waived. Runs gate.py stop end to end against a fake transcript in a throwaway HOME. Usage: corrwaiver_selftest.py
[path to gate.py]. Exit 0 = every control behaves. Run it against an older gate.py and the first case must fail."""
import os as _os_0368; _os_0368.environ["IMC_STOP_EXIT2"] = "1"  # 0.3.68: these controls read exit code 2; the JSON Stop channel is tested in stopjson_selftest.py
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "hooks", "gate.py")
MARK = 'This session is attached to the Project **"Improving my Claude (Overall)"**'
TBL = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | x | y | Claude | z | p | c |"
def U(u, c, **k): return dict({"type": "user", "uuid": u, "message": {"role": "user", "content": c}}, **k)
def A(u, t): return {"type": "assistant", "uuid": u, "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}}
FB = U("fb1", "Stop hook feedback:\nreviewer found defects", isMeta=True)
def run(entries, text):
    home = tempfile.mkdtemp(prefix="corrself-")
    os.makedirs(os.path.join(home, ".claude"))
    tp = os.path.join(home, "t.jsonl")
    with open(tp, "w") as f:
        for e in entries: f.write(json.dumps(e) + "\n")
    env = dict(os.environ, HOME=home, IMC_GATE_ALL="1", IMC_EVERY_REPLY_TABLE="1")
    payload = json.dumps({"session_id": "selftest", "transcript_path": tp, "last_assistant_message": text})
    p = subprocess.run([sys.executable, GATE, "stop"], input=payload, capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stderr
bad = 0
def chk(name, ok, detail=""):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + name + ("" if ok else "  :: " + detail[:300]))
base = [U("u1", MARK + "\nplease fix"), A("a1", "Here is the answer.\n\n" + TBL)]
rc, err = run(base + [FB], "CORRECTION: the table's row 1 owner is Claude.")
chk("MUTATION CORRECTION-only reply after hook feedback passes (exit 0)", rc == 0, "rc=%s %s" % (rc, err))
rc, err = run(base + [FB], "**CORRECTION:** bold marker still counts.\n- CORRECTION: a bullet still counts.")
chk("MUTATION emphasis and bullet before CORRECTION: still pass", rc == 0, "rc=%s %s" % (rc, err))
rc, err = run(base, "CORRECTION: no hook feedback in this turn.")
chk("CONTROL same text with no hook feedback in the turn is still refused for no table", rc == 2 and "EVERY-REPLY-TABLE" in err, "rc=%s %s" % (rc, err))
rc, err = run(base + [FB], "CORRECTION: one line.\nAnd a plain sentence that is not a correction.")
chk("CONTROL a mixed reply is still refused", rc == 2 and "EVERY-REPLY-TABLE" in err, "rc=%s %s" % (rc, err))
rc, err = run([U("u1", MARK + "\nfirst"), A("a1", "x"), FB, U("u2", "a new real prompt")], "CORRECTION: feedback belongs to an earlier turn.")
chk("CONTROL hook feedback from an earlier turn waives nothing", rc == 2 and "EVERY-REPLY-TABLE" in err, "rc=%s %s" % (rc, err))
rc, err = run(base + [FB], "Plain reply with no table and no correction prefix.")
chk("CONTROL a plain table-less reply after feedback is still refused", rc == 2 and "EVERY-REPLY-TABLE" in err, "rc=%s %s" % (rc, err))
rc, err = run(base + [FB], "CORRECTION: " + "x" * 3000)
chk("CONTROL a CORRECTION-only reply over the length cap is still refused", rc == 2 and "EVERY-REPLY-TABLE" in err, "rc=%s %s" % (rc, err))
rc, err = run(base + [FB], "CORRECTION: here is the table again.\n\n" + TBL)
chk("CONTROL a CORRECTION line that carries a table is not waived by this rule", "EVERY-REPLY-TABLE" not in err and rc in (0, 2), "rc=%s %s" % (rc, err))
print("CORRWAIVER SELFTEST OK" if not bad else "CORRWAIVER SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
