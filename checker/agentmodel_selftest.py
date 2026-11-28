#!/usr/bin/env python3
"""agentmodel_selftest.py - O4 "Model routing" fixtures for hooks/agentguard.py AGENT-NO-MODEL (core serial 27).

Runs agentguard.py in hook mode, as Claude Code does (JSON on stdin), and checks the warning end to end:
an Agent call doing execution work with no model exits 0 (never refused), prints a PreToolUse JSON whose
systemMessage and additionalContext carry AGENT-NO-MODEL, and appends one line to the warning log; the same call
with model sonnet or haiku prints nothing and logs nothing; a reviewer brief without the rubric is still refused
(exit 2), so the warning did not weaken the existing block.
    python3 checker/agentmodel_selftest.py    exit 0 when every fixture passes
"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(os.path.dirname(HERE), "hooks", "agentguard.py")


def run(tool_input, log, tool="Agent"):
    env = dict(os.environ, IMC_AGENTMODEL_LOG=log, IMC_REVIEWCOUNT_DIR=tempfile.mkdtemp())
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "session_id": "fixture-o4"})
    r = subprocess.run([sys.executable, GUARD], input=payload, capture_output=True, text=True, env=env, timeout=30)
    return r.returncode, r.stdout, r.stderr


def lines(path):
    try:
        return open(path).read().splitlines()
    except FileNotFoundError:
        return []


def main():
    log = os.path.join(tempfile.mkdtemp(), "warn.tsv")
    ok = True
    cases = [
        ("F1 execution, no model: exit 0, warns, logs 1", {"prompt": "Run every selftest and report counts", "description": "run selftests"}, 0, True, 1),
        ("F2 execution, model sonnet: exit 0, silent, logs 0", {"prompt": "Run every selftest and report counts", "model": "sonnet"}, 0, False, 0),
        ("F3 execution, model haiku: exit 0, silent, logs 0", {"prompt": "Edit the file and commit", "model": "haiku"}, 0, False, 0),
        ("F4 Plan agent, no model: exit 0, silent", {"prompt": "Design the cache and write a plan", "subagent_type": "Plan"}, 0, False, 0),
        ("F5 reviewer brief without rubric, no model: still refused exit 2", {"prompt": "You are an independent reviewer. Read draft-9.md and write draft-9.md.review", "run_in_background": False}, 2, False, 0),
    ]
    for label, ti, want_rc, want_warn, want_new in cases:
        before = len(lines(log))
        rc, out, err = run(ti, log)
        warned = False
        if out.strip():
            try:
                j = json.loads(out)
                warned = ("AGENT-NO-MODEL" in j.get("systemMessage", "") and
                          "AGENT-NO-MODEL" in j["hookSpecificOutput"]["additionalContext"] and
                          j["hookSpecificOutput"]["permissionDecision"] == "allow")
            except Exception:
                warned = False
        new = len(lines(log)) - before
        good = rc == want_rc and warned == want_warn and new == want_new
        ok = ok and good
        print(("PASS " if good else "FAIL ") + label + "  (rc=%d warned=%s logged=%d)" % (rc, warned, new))
    print("AGENTMODEL FIXTURES: %s" % ("5 of 5 PASS" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
