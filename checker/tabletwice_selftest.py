"""End-to-end control for TABLE-TWICE-IN-TURN: pipes a transcript into `gate.py stop` and reads the block text.
Exit 0 = fires with a delivered table + closing table, silent without the delivered table."""
import json, os, subprocess, sys, tempfile, uuid
HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "hooks", "gate.py")
T = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | x | y | Claude | z | p | c |"
def run(entries):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(json.dumps(e) for e in entries) + "\n"); tp = f.name
    env = dict(os.environ, IMC_GATE_ALL="1")
    p = subprocess.run([sys.executable, GATE, "stop"], input=json.dumps({"session_id": "tt-selftest-" + uuid.uuid4().hex, "transcript_path": tp, "last_assistant_message": T}), capture_output=True, text=True, env=env)
    os.unlink(tp); return p.stderr + p.stdout
U = {"type": "user", "message": {"content": "IMC_GATE_ALL start"}}
S = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__x__SendUserMessage", "input": {"message": T}}]}}
R = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "sent"}]}}
bad = 0
def chk(n, ok):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + n)
chk("MUTATION delivered SendUserMessage table + closing table -> TABLE-TWICE-IN-TURN named", "TABLE-TWICE-IN-TURN" in run([U, S, R]))
chk("CONTROL closing table with no earlier delivered table -> TABLE-TWICE-IN-TURN absent", "TABLE-TWICE-IN-TURN" not in run([U]))
print("TABLETWICE SELFTEST OK" if not bad else "TABLETWICE SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
