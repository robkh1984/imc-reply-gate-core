#!/usr/bin/env python3
"""0.3.25 selftest: a refused SendUserMessage delivers nothing, so (1) the pretool block text must say NOTHING WAS SENT and
never tell Claude the text is on Rob's screen, and (2) TABLE-NOT-SENT refuses a table-less CORRECTION: reply or a 'table above'
reference when a table was denied this turn and none was delivered. Runs gate.py pretool end to end against a fake transcript in
a throwaway HOME. Usage: tablelost_selftest.py [path to gate.py]. Exit 0 = every control behaves; against the 0.3.23 gate.py the
refusal cases must fail (negative control)."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "hooks", "gate.py")
MARK = 'This session is attached to the Project **"Improving my Claude (Overall)"**'
TBL = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | x | y | Rob | z | p | c |"
def U(u, c): return {"type": "user", "uuid": u, "message": {"role": "user", "content": c}}
def S(u, msg): return {"type": "assistant", "uuid": u, "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t" + u, "name": "SendUserMessage", "input": {"message": msg}}]}}
def R(u, body, err): return {"type": "user", "uuid": u, "toolUseResult": {"x": 1}, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t" + u, "content": body, "is_error": err}]}}
def run(entries, msg):
    home = tempfile.mkdtemp(prefix="tlself-"); os.makedirs(os.path.join(home, ".claude"))
    tp = os.path.join(home, "t.jsonl")
    with open(tp, "w") as f:
        for e in entries: f.write(json.dumps(e) + "\n")
    env = dict(os.environ, HOME=home, IMC_GATE_ALL="1", IMC_EVERY_REPLY_TABLE="0")
    payload = json.dumps({"session_id": "tlself", "transcript_path": tp, "tool_name": "SendUserMessage", "tool_input": {"message": msg}})
    p = subprocess.run([sys.executable, GATE, "pretool"], input=payload, capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stderr + p.stdout
bad = 0
def chk(name, ok, detail=""):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + name + ("" if ok else "  :: " + detail[:400]))
base = [U("u1", MARK + "\nplease give me the next steps")]
corr = "CORRECTION: the table above was sent without its pre-check; it was not re-verified as sent."
denied = base + [S("a1", TBL), R("a1", "PreToolUse:SendUserMessage hook error: imc-reply-gate blocked this SendUserMessage", True)]
ok_sent = base + [S("a1", TBL), R("a1", "Message delivered to user.", False)]
rc, err = run(denied, corr)
chk("CONTROL a CORRECTION-only reply about 'the table above' after a DENIED table is refused", rc == 2 and "TABLE-NOT-SENT" in err, "rc=%s %s" % (rc, err))
rc, err = run(denied, "CORRECTION: row 1 should name Rob as owner.")
chk("CONTROL any table-less CORRECTION-only reply after a denied table is refused", rc == 2 and "TABLE-NOT-SENT" in err, "rc=%s %s" % (rc, err))
rc, err = run(ok_sent, corr)
chk("MUTATION the same correction after a DELIVERED table is not refused as TABLE-NOT-SENT", "TABLE-NOT-SENT" not in err, "rc=%s %s" % (rc, err))
rc, err = run(base, corr)
chk("MUTATION a correction when no table was attempted this turn is not refused as TABLE-NOT-SENT", "TABLE-NOT-SENT" not in err, "rc=%s %s" % (rc, err))
rc, err = run(denied, "Working on the gate fix now.")
chk("MUTATION a plain progress line after a denied table is not refused as TABLE-NOT-SENT", "TABLE-NOT-SENT" not in err, "rc=%s %s" % (rc, err))
rc, err = run(denied, TBL)
chk("MUTATION resending a table after a denied one is not refused as TABLE-NOT-SENT", "TABLE-NOT-SENT" not in err, "rc=%s %s" % (rc, err))
rc, err = run(base, TBL)
chk("CONTROL the block text for an unstamped table says NOTHING WAS SENT", rc == 2 and "NOTHING WAS SENT" in err, "rc=%s %s" % (rc, err))
chk("CONTROL the block text never says the blocked text is on Rob's screen", "ON ROB'S SCREEN" not in err and "table above was sent" not in err, err)
chk("CONTROL the block text forbids CORRECTION-only replacement", "Do NOT send CORRECTION: lines in its place" in err, err)
rc, err = run(base, "The OI-0419 row is done and verified.")
chk("CONTROL a block for a non-precheck code (bare id) also says NOTHING WAS SENT", rc == 2 and "NOTHING WAS SENT" in err and "ON ROB'S SCREEN" not in err, "rc=%s %s" % (rc, err))
print("TABLELOST SELFTEST OK" if not bad else "TABLELOST SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
