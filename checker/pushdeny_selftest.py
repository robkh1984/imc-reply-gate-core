"""core serial 4 control for OI-0783: a PushNotification refused by the PreToolUse gate must say that nothing was sent
and ask for one corrected resend, never that it reached Rob's phone. Exit 0 = holds."""
import json, os, subprocess, sys, tempfile, uuid
HOMEDIR = tempfile.mkdtemp(); os.makedirs(os.path.join(HOMEDIR, ".claude"))
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "hooks", "gate.py")
def run(msg):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"type": "user", "message": {"content": "IMC_GATE_ALL start"}}) + "\n"); tp = f.name
    env = dict(os.environ, IMC_GATE_ALL="1", HOME=HOMEDIR)
    p = subprocess.run([sys.executable, GATE, "pretool"], input=json.dumps({"session_id": "pd-selftest-" + uuid.uuid4().hex, "transcript_path": tp, "hook_event_name": "PreToolUse", "tool_name": "PushNotification", "tool_input": {"message": msg}}), capture_output=True, text=True, env=env)
    os.unlink(tp); return p.returncode, p.stderr + p.stdout
bad = 0
def chk(n, ok, detail=""):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + n + (("  -- " + detail[:200]) if not ok else ""))
# the exact message that was blocked in the 2026-11-24 diagnostic run (ID-NAME: a bare register id)
rc, out = run("<routine_summary>OI-0783 test: if you see this, scheduled-task notifications work.</routine_summary>")
chk("POSITIVE blocked notification -> refused", rc == 2 and "blocked this PushNotification" in out, out)
chk("POSITIVE says nothing was sent", "NOTHING WAS SENT" in out, out)
chk("POSITIVE never claims it reached the phone", "REACHED ROB'S PHONE" not in out, out)
rc2, out2 = run("<routine_summary>Test notification from a scheduled task.</routine_summary>")
chk("CONTROL clean short notification -> allowed", rc2 == 0 and "blocked" not in out2, out2)
print("PUSHDENY SELFTEST OK" if not bad else "PUSHDENY SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
