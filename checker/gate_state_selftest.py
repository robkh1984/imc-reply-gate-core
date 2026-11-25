#!/usr/bin/env python3
"""F-305 selftest: gate.py stop must BLOCK a gated no-table reply when ~/.claude is writable, and when the
state path cannot be written must still exit 0 but log why=ERROR-STATE and print ERROR-STATE on stderr.
Exit 0 = both controls behaved, 1 = a control failed."""
import os as _os_0368; _os_0368.environ["IMC_STOP_EXIT2"] = "1"  # 0.3.68: these controls read exit code 2; the JSON Stop channel is tested in stopjson_selftest.py
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); GATE = os.path.join(HERE, "..", "hooks", "gate.py")
def tr(d):
    p = os.path.join(d, "tr.jsonl"); ev = [
     {"type": "user", "uuid": "u3", "message": {"role": "user", "content": "This session is attached to the Project **\"Improving my Claude (Overall)\"** hello"}},
     {"type": "assistant", "uuid": "a3", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "SendUserFile", "input": {"files": ["x.md"], "status": "normal"}}]}},
     {"type": "user", "uuid": "r3", "toolUseResult": {"ok": True}, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "sent"}]}},
     {"type": "assistant", "uuid": "a4", "message": {"role": "assistant", "content": [{"type": "text", "text": "Here is a deliverable that decides something and carries no next-steps table."}]}}]
    open(p, "w").write("\n".join(json.dumps(e) for e in ev)); return p
def run(unwritable):
    with tempfile.TemporaryDirectory() as h:
        os.makedirs(os.path.join(h, ".claude"))
        if unwritable: os.makedirs(os.path.join(h, ".claude", "imc-reply-gate.state.json"))
        t = tr(h); env = dict(os.environ, HOME=h, REPLY_GATE_TRANSCRIPT=t, IMC_EVERY_REPLY_TABLE="1")
        r = subprocess.run([sys.executable, GATE, "stop"], input=json.dumps({"session_id": "s1", "transcript_path": t}), capture_output=True, text=True, env=env)
        lg = open(os.path.join(h, ".claude", "imc-reply-gate.log")).read().strip().split("\n")[-1] if os.path.exists(os.path.join(h, ".claude", "imc-reply-gate.log")) else ""
        return r.returncode, r.stderr, lg
bad = 0
rc, err, lg = run(False); ok = rc == 2; bad += not ok; print("%s writable state: gated no-table reply is blocked (exit %s)" % ("OK " if ok else "BAD", rc))
rc, err, lg = run(True); ok = rc == 0 and "ERROR-STATE" in err and '"why": "ERROR-STATE"' in lg; bad += not ok; print("%s unwritable state: exit 0, stderr and log say ERROR-STATE (exit %s)" % ("OK " if ok else "BAD", rc))
print("SELFTEST CONTROLS OK" if not bad else "SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
