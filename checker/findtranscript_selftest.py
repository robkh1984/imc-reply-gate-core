#!/usr/bin/env python3
"""findtranscript_selftest.py - imc-reply-gate 0.4.19 controls for transcript_util.find_transcript (O1, 2026-11-26).
Measured cause: in cloud session 8f8a8a55 the newest jsonl was a child probe's (-tmp-o1cloud/e3732d57...), so precheck
judged that probe's prompt as Rob's last message. Exit 0 when every control passes."""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import transcript_util as tu

res = []
def t(name, got, want):
    res.append(got == want); print(("  ok    " if got == want else "  BAD   ") + name + ("" if got == want else "  got %r want %r" % (got, want)))

home = tempfile.mkdtemp()
os.environ["HOME"] = home
for k in ("REPLY_GATE_TRANSCRIPT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"):
    os.environ.pop(k, None)
def mk(folder, name, age):
    d = os.path.join(home, ".claude", "projects", folder); os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name + ".jsonl"); open(p, "w").write("{}\n"); os.utime(p, (time.time() - age, time.time() - age)); return p
own = mk("-home-claude", "SESSION-A", 60)
probe = mk("-tmp-o1cloud", "PROBE-B", 1)
other = mk("-home-claude-x", "SESSION-C", 30)
os.environ["CLAUDE_CODE_SESSION_ID"] = "SESSION-A"
t("the session's own transcript wins over a newer probe and a newer other session", tu.find_transcript(), own)
os.environ["CLAUDE_CODE_SESSION_ID"] = "SESSION-Z"
t("MUTATION a known session id with no file returns None, not another session's", tu.find_transcript(), None)
os.environ.pop("CLAUDE_CODE_SESSION_ID")
t("no session id: a -tmp-<name> probe folder is skipped (the 2026-11-26 miss)", tu.find_transcript(), other)
os.remove(other); os.remove(own)
t("no session id and only probe transcripts: None", tu.find_transcript(), None)
os.environ["REPLY_GATE_TRANSCRIPT"] = probe
t("REPLY_GATE_TRANSCRIPT still overrides", tu.find_transcript(), probe)
print("ALL CONTROLS PASSED" if all(res) else "A CONTROL FAILED")
sys.exit(0 if all(res) else 1)
