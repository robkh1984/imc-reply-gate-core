"""core serial 3 control for OI-0786: a table-less closing text over PROGRESS_MAX characters, unstamped, must be
blocked with a message that names the closing text, not a table. A table-carrying unstamped final text keeps the old
table message. Exit 0 = all four checks hold."""
import json, os, subprocess, sys, tempfile, uuid
HOMEDIR = tempfile.mkdtemp(); os.makedirs(os.path.join(HOMEDIR, ".claude"))
T = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | x | y | Claude | z | p | c |"
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "hooks", "gate.py")
def run(text):
    entries = [{"type": "user", "origin": {"kind": "human"}, "message": {"content": "IMC_GATE_ALL start"}},
               {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tu1", "name": "SendUserMessage", "input": {"message": "Reply.\n\n" + T}}]}},
               {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "Message delivered to user."}]}}]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(json.dumps(e) for e in entries) + "\n"); tp = f.name
    env = dict(os.environ, IMC_GATE_ALL="1", HOME=HOMEDIR)
    p = subprocess.run([sys.executable, GATE, "stop"], input=json.dumps({"session_id": "cu-selftest-" + uuid.uuid4().hex, "transcript_path": tp, "last_assistant_message": text}), capture_output=True, text=True, env=env)
    os.unlink(tp); return p.returncode, p.stderr + p.stdout
bad = 0
def chk(n, ok, detail=""):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + n + (("  -- " + detail[:160]) if not ok else ""))
LONG = 'I built the loader and it passed every test I ran, including a scheduled run and a live update that reached a session 4 minutes after its commit. Your sessions still run 0.3.92, though, so it isn\'t live yet.\n\nBLOCKED: a new plug-in version only reaches your sessions through the Check for updates button, and Chrome refuses me that page. Please press Check for updates on imc-claude-plugins and reply "done". After that, I release gate code changes myself with no click from you.'  # the 479-character closing line blocked at 6:01 PM PST 2026-11-24 in session 05185df0
rc, out = run(LONG)
chk("POSITIVE long table-less closing text -> blocked, message names the closing text", "This closing text has no table" in out and '"decision": "block"' in out, out)
chk("POSITIVE that message does not claim a table was unstamped", "Its next-steps table was sent" not in out, out)
rc2, out2 = run(LONG + "\n\n" + T)
chk("CONTROL unstamped text with a table -> not the closing-text message", "This closing text has no table" not in out2, out2)
rc3, out3 = run("Sent.")
chk("CONTROL short closing line -> not blocked", "PRECHECK-MISSING" not in out3 and "block" not in out3, out3)
print("CLOSINGUNSTAMPED SELFTEST OK" if not bad else "CLOSINGUNSTAMPED SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
