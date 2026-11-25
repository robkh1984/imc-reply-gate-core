#!/usr/bin/env python3
"""0.3.68 STOP JSON CHANNEL selftest. In Stop mode gate.py must send a block as {"decision": "block", "reason": ...} on
stdout with exit 0 (measured 2026-11-19: exit code 2 never reached scheduled-task sessions), send nothing on an allow,
and keep exit code 2 when IMC_STOP_EXIT2=1. Exit 0 all good, 1 any control failed."""
import json, os, subprocess, sys, tempfile
GATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "gate.py")
TABLE = ("Text.\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
         "| 1 | x | y | Claude | z | - | Con: none |\n")
def run(text, extra=None):
    home = tempfile.mkdtemp(); os.makedirs(os.path.join(home, ".claude"))
    t = os.path.join(home, "t.jsonl")
    with open(t, "w") as f:
        f.write(json.dumps({"type": "user", "uuid": "u1", "message": {"role": "user", "content": "go"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n")
    env = dict(os.environ, HOME=home); env.pop("IMC_STOP_EXIT2", None); env.update(extra or {})
    p = subprocess.run([sys.executable, GATE, "stop"], input=json.dumps({"session_id": "sj", "transcript_path": t, "last_assistant_message": text}),
                       capture_output=True, text=True, env=env, timeout=120)
    return p
bad = 0
p = run(TABLE)
try:
    d = json.loads(p.stdout); ok = p.returncode == 0 and d.get("decision") == "block" and "imc-reply-gate blocked" in d.get("reason", "")
except ValueError:
    ok = False
bad += not ok; print(("OK " if ok else "BAD") + " unstamped table: JSON block on stdout, exit 0 (rc=%s)" % p.returncode)
p = run(TABLE, {"IMC_STOP_EXIT2": "1"})
ok = p.returncode == 2 and "imc-reply-gate blocked" in p.stderr
bad += not ok; print(("OK " if ok else "BAD") + " IMC_STOP_EXIT2=1 keeps exit 2 (rc=%s)" % p.returncode)
p = run("")
ok = p.returncode == 0 and not p.stdout.strip()
bad += not ok; print(("OK " if ok else "BAD") + " empty reply (allowed): nothing on stdout, exit 0 (rc=%s, out=%r)" % (p.returncode, p.stdout[:60]))
print("STOPJSON SELFTEST " + ("OK" if not bad else "BAD %d" % bad)); sys.exit(1 if bad else 0)
