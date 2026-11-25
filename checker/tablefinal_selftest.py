"""0.3.90 end-to-end control for TABLE-VIA-FINAL-TEXT (OI-0778): pipes a transcript into `gate.py stop` and reads the
block text. Exit 0 = fires on a final-text table in a turn Rob typed, silent in a scheduled-trigger turn, silent when the
turn has no origin, and silent on a table-less final text in a human turn."""
import json, os, subprocess, sys, tempfile, uuid
HOMEDIR = tempfile.mkdtemp(); os.makedirs(os.path.join(HOMEDIR, ".claude"))
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "hooks", "gate.py")
T = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | x | y | Claude | z | p | c |"
def run(entries, text=T):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(json.dumps(e) for e in entries) + "\n"); tp = f.name
    env = dict(os.environ, IMC_GATE_ALL="1", HOME=HOMEDIR)  # a throwaway HOME, so no real gate log or state is touched
    p = subprocess.run([sys.executable, GATE, "stop"], input=json.dumps({"session_id": "tf-selftest-" + uuid.uuid4().hex, "transcript_path": tp, "last_assistant_message": text}), capture_output=True, text=True, env=env)
    os.unlink(tp); return p.stderr + p.stdout
def user(origin=None):
    e = {"type": "user", "message": {"content": "IMC_GATE_ALL start"}}
    if origin is not None: e["origin"] = origin
    return e
bad = 0
def chk(n, ok):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + n)
chk("POSITIVE final-text table in a turn Rob typed -> TABLE-VIA-FINAL-TEXT named", "TABLE-VIA-FINAL-TEXT" in run([user({"kind": "human"})]))
chk("CONTROL final-text table in a scheduled-trigger turn -> TABLE-VIA-FINAL-TEXT absent", "TABLE-VIA-FINAL-TEXT" not in run([user({"kind": "task-notification", "subkind": "scheduled-trigger"})]))
A = {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}
chk("CONTROL Rob typed earlier, then a scheduled trigger fired into the session -> TABLE-VIA-FINAL-TEXT absent", "TABLE-VIA-FINAL-TEXT" not in run([user({"kind": "human"}), A, user({"kind": "task-notification", "subkind": "scheduled-trigger"})]))
chk("POSITIVE Rob typed, then Stop-hook feedback (isMeta) -> TABLE-VIA-FINAL-TEXT named", "TABLE-VIA-FINAL-TEXT" in run([user({"kind": "human"}), A, {"type": "user", "isMeta": True, "message": {"content": "Stop hook feedback: x"}}]))
chk("CONTROL final-text table in a turn with no origin -> TABLE-VIA-FINAL-TEXT absent", "TABLE-VIA-FINAL-TEXT" not in run([user()]))
chk("CONTROL table-less final text in a turn Rob typed -> TABLE-VIA-FINAL-TEXT absent", "TABLE-VIA-FINAL-TEXT" not in run([user({"kind": "human"})], "Sent."))
print("TABLEFINAL SELFTEST OK" if not bad else "TABLEFINAL SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
