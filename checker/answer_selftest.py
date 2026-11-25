#!/usr/bin/env python3
"""0.3.23 selftest: VERIFY-ANSWER (a No, or an answer with no tool call and no CHECKED line, to 'have you investigated /
measured / tested' is refused) and PROMISE-OPEN (a promised table with no table, BLOCKED: or CANCELLED: is refused).
Runs gate.py stop end to end against a fake transcript in a throwaway HOME. Usage: answer_selftest.py [path to gate.py].
Exit 0 = every control behaves. Run it against the 0.3.22 gate.py and the refusal cases must fail."""
import os as _os_0368; _os_0368.environ["IMC_STOP_EXIT2"] = "1"  # 0.3.68: these controls read exit code 2; the JSON Stop channel is tested in stopjson_selftest.py
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "hooks", "gate.py")
MARK = 'This session is attached to the Project **"Improving my Claude (Overall)"**'
Q = "Before I answer, have you investigated the root causes? Have you measured and tested your recommendations before recommending them to me."
TBL = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | x | y | Claude | z | p | c |"
def U(u, c, **k): return dict({"type": "user", "uuid": u, "message": {"role": "user", "content": c}}, **k)
def A(u, t): return {"type": "assistant", "uuid": u, "message": {"role": "assistant", "content": [{"type": "text", "text": t}]}}
def T(u): return {"type": "assistant", "uuid": u, "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t" + u, "name": "Bash", "input": {"command": "ls"}}]}}
def R(u): return {"type": "user", "uuid": u, "toolUseResult": {"stdout": "ok"}, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t" + u, "content": "ok"}]}}
def mk():
    home = tempfile.mkdtemp(prefix="ansself-"); os.makedirs(os.path.join(home, ".claude")); return home
def run(entries, text, home=None, mode="stop"):
    home = home or mk()
    tp = os.path.join(home, "t.jsonl")
    with open(tp, "w") as f:
        for e in entries: f.write(json.dumps(e) + "\n")
    env = dict(os.environ, HOME=home, IMC_GATE_ALL="1", IMC_EVERY_REPLY_TABLE="0")
    payload = json.dumps({"session_id": "selftest", "transcript_path": tp, "last_assistant_message": text})
    p = subprocess.run([sys.executable, GATE, mode], input=payload, capture_output=True, text=True, env=env, timeout=120)
    return p.returncode, p.stderr + p.stdout, home
bad = 0
def chk(name, ok, detail=""):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + name + ("" if ok else "  :: " + detail[:300]))
ask = [U("u1", MARK + "\n" + Q)]
rc, err, _ = run(ask, "No. I wrote the rows from summaries.")
chk("CONTROL a No to the verification question is refused", rc == 2 and "VERIFY-ANSWER" in err, "rc=%s %s" % (rc, err))
rc, err, _ = run(ask, "I did not investigate the root causes.")
chk("CONTROL 'I did not' is refused as a No", rc == 2 and "VERIFY-ANSWER" in err, "rc=%s %s" % (rc, err))
rc, err, _ = run(ask, "Yes. The root causes are found and the fixes are tested.")
chk("CONTROL a Yes with no tool call and no CHECKED line is refused", rc == 2 and "VERIFY-ANSWER" in err, "rc=%s %s" % (rc, err))
rc, err, _ = run(ask + [T("a1"), R("r1")], "Yes.\nCHECKED: `ls` printed one line, so the folder exists.")
chk("MUTATION a Yes with a tool call in the turn and a CHECKED line passes", "VERIFY-ANSWER" not in err, "rc=%s %s" % (rc, err))
rc, err, _ = run([U("u0", MARK + "\n" + Q), T("a0"), R("r0"), U("u1", "Thanks, now list the files.")], "Done.")
chk("CONTROL a question in an earlier turn does not apply to a later turn", "VERIFY-ANSWER" not in err, "rc=%s %s" % (rc, err))
rc, err, _ = run(ask, "BLOCKED: the grep call failed with 'permission denied'.")
chk("MUTATION a BLOCKED: line naming the failing call passes", "VERIFY-ANSWER" not in err, "rc=%s %s" % (rc, err))
rc, err, _ = run([U("u1", MARK + "\nplease list the files")], "No. There are none.")
chk("CONTROL a No to an ordinary prompt is not touched", "VERIFY-ANSWER" not in err, "rc=%s %s" % (rc, err))
base = [U("u1", MARK + "\nplease fix it")]
rc, err, _ = run(base, "I will send a corrected table only after that.")
chk("CONTROL a promised table with no table, BLOCKED: or CANCELLED: is refused", rc == 2 and "PROMISE-OPEN" in err, "rc=%s %s" % (rc, err))
rc, err, home = run(base, "I will send a corrected table only after that.\nBLOCKED: row 1 waits on a decision of Rob's.")
chk("MUTATION the same promise with a BLOCKED: line passes", "PROMISE-OPEN" not in err, "rc=%s %s" % (rc, err))
p = json.load(open(os.path.join(home, ".claude", "imc-reply-gate-promises.json"))) if os.path.isfile(os.path.join(home, ".claude", "imc-reply-gate-promises.json")) else {}
chk("MUTATION the kept-open promise is stored in the ledger", "selftest" in p, str(p))
payload = json.dumps({"session_id": "selftest"})
q = subprocess.run([sys.executable, GATE, "prompt"], input=payload, capture_output=True, text=True, env=dict(os.environ, HOME=home), timeout=60)
chk("MUTATION the next prompt prints the open promise", "OPEN PROMISE" in q.stdout, q.stdout + q.stderr)
rc, err, _ = run(base, "I will send the report now.\nCANCELLED: the report is no longer needed.")
chk("MUTATION a CANCELLED: line withdraws the promise", "PROMISE-OPEN" not in err, "rc=%s %s" % (rc, err))
rc, err, _ = run(base, 'You wrote "I will send a table" in your note.')
chk("CONTROL a quoted promise is not a promise", "PROMISE-OPEN" not in err, "rc=%s %s" % (rc, err))
rc, err, _ = run(base, "I will send the table below.\n\n" + TBL)
chk("CONTROL a promise delivered in the same reply passes this check", "PROMISE-OPEN" not in err, "rc=%s %s" % (rc, err))
print("ANSWER SELFTEST OK" if not bad else "ANSWER SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
