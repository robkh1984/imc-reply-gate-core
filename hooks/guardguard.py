#!/usr/bin/env python3
"""guardguard.py - imc-reply-gate 0.2.35 PreToolUse hook (Rob 2026-10-21, guard lifecycle).

ROOT CAUSE: a recurring check trigger was created on my own initiative with no condition for ending it, so it kept
firing after the thing it watched was settled (INTAKE F-719; GUARDS.tsv row trig_01WfWnKpiYy4KD1K4TqpJnSC).
bin/guardcheck.py and preflight CHECK O catch a guard that is REGISTERED without a retire condition, but nothing
forced a new guard to be registered. This hook refuses the creation before it happens.

RULE: mcp__claude-code-remote__create_trigger with a cron_expression (recurring) and initiation own_followup or
own_initiative is denied unless its prompt carries a line  GUARD-RETIRE: <condition or date, 8+ characters>.
One-shot triggers (run_once_at) and send_later are allowed: they end themselves. A person-requested trigger
(human_request / human_schedule) is allowed: Rob owns its lifetime.

WHAT THIS CANNOT DO, STATED SO IT IS NOT OVERCLAIMED: the hook runs in the cloud container and cannot read
GUARDS.tsv on the Mac, so it checks the declaration in the payload, not the registry. Registry membership is still
checked on the Mac by bin/guardcheck.py through preflight CHECK O.

    python3 guardguard.py            hook mode (JSON on stdin; exit 2 = deny, reason on stderr)
    python3 guardguard.py --selftest controls; exit 0 all pass, 1 a control failed
"""
import json
import re
import sys

RETIRE_RE = re.compile(r'^\s*GUARD-RETIRE:\s*(\S.{7,})$', re.M)
OWN = ("own_followup", "own_initiative")


def verdict(tool, tool_input):
    """None to allow, or the denial reason."""
    ti = tool_input or {}
    if not (tool or "").endswith("create_trigger"):
        return None
    if ti.get("run_once_at") or not ti.get("cron_expression"):
        return None
    if ti.get("initiation") not in OWN:
        return None
    if RETIRE_RE.search(str(ti.get("prompt") or "")):
        return None
    return ("a recurring trigger created on my own initiative has no 'GUARD-RETIRE: <condition or date>' line in its "
            "prompt (name: %s)" % str(ti.get("name") or "")[:60])


def selftest():
    good = "check X\nGUARD-RETIRE: Rob closes C-20261021-001 or 2026-10-28"
    cases = [
        ("mcp__claude-code-remote__create_trigger", {"name": "a", "cron_expression": "0 * * * *", "initiation": "own_followup", "prompt": "check X"}, True),
        ("mcp__claude-code-remote__create_trigger", {"name": "a", "cron_expression": "0 * * * *", "initiation": "own_initiative", "prompt": "GUARD-RETIRE: x"}, True),
        ("mcp__claude-code-remote__create_trigger", {"name": "a", "cron_expression": "0 * * * *", "initiation": "own_followup"}, True),
        ("mcp__claude-code-remote__create_trigger", {"name": "a", "cron_expression": "0 * * * *", "initiation": "own_followup", "prompt": good}, False),
        ("mcp__claude-code-remote__create_trigger", {"name": "a", "run_once_at": "2026-10-22T00:00:00Z", "initiation": "own_followup", "prompt": "check X"}, False),
        ("mcp__claude-code-remote__create_trigger", {"name": "a", "cron_expression": "0 * * * *", "initiation": "human_request", "prompt": "daily thing"}, False),
        ("mcp__claude-code-remote__send_later", {"message": "remind", "delay_minutes": 5, "initiation": "own_followup"}, False),
        ("mcp__claude-code-remote__list_triggers", {}, False),
        ("Bash", {"command": "ls"}, False),
    ]
    ok = True
    for tool, inp, deny in cases:
        got = verdict(tool, inp) is not None
        good_ = got == deny
        ok = ok and good_
        print(("  ok    " if good_ else "  FAIL  ") + ("DENY " if deny else "ALLOW ") + tool.split("__")[-1] + " " + json.dumps(inp)[:70])
    print("ALL CONTROLS PASSED" if ok else "A CONTROL FAILED")
    return ok


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    why = verdict(payload.get("tool_name", ""), payload.get("tool_input") or {})
    if why:
        sys.stderr.write("imc-reply-gate guardguard refused this call: %s. Add a line 'GUARD-RETIRE: <the ruling or date "
                         "that ends it>' to the prompt, and add the guard to ~/Claude/Improving-my-Claude/GUARDS.tsv "
                         "in the same turn. Nothing was created.\n" % why)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
