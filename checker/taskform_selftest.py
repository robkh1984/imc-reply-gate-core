"""End-to-end control for the 0.3.65 task-form waiver: pipes a transcript into `gate.py stop`.
Exit 0 = EVERY-REPLY-TABLE is absent when the first user message fixes a "REPLY FORM" with "no table", and present
when it does not (the control)."""
import json, os, subprocess, sys, tempfile, uuid
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "hooks", "gate.py")
REPLY = ("CHECKED: python3 ~/Claude/Improving-my-Claude/bin/artifactcount.py, 07:34 PST. All three counts are ok. Exit code 0.\n"
         "Action: none; every count is below its ceiling.")
def run(first):
    entries = [{"type": "user", "message": {"content": first}},
               {"type": "assistant", "message": {"content": [{"type": "text", "text": REPLY}]}}]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(json.dumps(e) for e in entries) + "\n"); tp = f.name
    env = dict(os.environ, IMC_GATE_ALL="1")
    p = subprocess.run([sys.executable, GATE, "stop"], input=json.dumps({"session_id": "tf-selftest-" + uuid.uuid4().hex,
                       "transcript_path": tp, "last_assistant_message": REPLY}), capture_output=True, text=True, env=env, timeout=80)
    os.unlink(tp); return p.stderr + p.stdout
bad = 0
def chk(n, ok):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + n)
waived = run("IMC_GATE_ALL Read-only check. REPLY FORM: no table, no question mark.")
plain = run("IMC_GATE_ALL Read-only check. Report the counts.")
chk("WAIVER task prompt with REPLY FORM and no table -> EVERY-REPLY-TABLE absent", "EVERY-REPLY-TABLE" not in waived)
chk("CONTROL prompt without the form -> EVERY-REPLY-TABLE present", "EVERY-REPLY-TABLE" in plain)
chk("MEASURED-LABEL absent for an unquoted python3 command with a path", "MEASURED-LABEL" not in waived)
print("TASKFORM SELFTEST OK" if not bad else "TASKFORM SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
