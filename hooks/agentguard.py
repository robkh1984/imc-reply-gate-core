#!/usr/bin/env python3
"""agentguard.py - imc-reply-gate 0.3.2 PreToolUse hook on the Agent tool (Rob 2026-10-23, "WHY IS THE REPLY BEING REPEATED").

ROOT CAUSE (measured 2026-10-23 from the O3 conversation record): a session started its independent reviewer with
run_in_background unset, which runs the agent in the background, so the turn ended while it read; the Stop hook then
demanded a full table on each waiting line. Four Agent calls, ten assistant messages, seven of them carrying a table,
three review rounds (15, 14, 11 findings) in 19 minutes. Nothing in code refused either the background start or the
fourth-and-later round.

RULES. A call whose prompt looks like a reviewer brief (words 'independent' and 'reviewer', or '.review', or
'DRAFT-SHA256') is refused when (1) run_in_background is set to anything other than false (0.3.14: UNSET IS NOW ALLOWED, Rob 2026-10-25 "Agree with your recommendation" after a test call with it unset returned in the foreground; before 0.3.14 unset was refused), or (2) it is the third reviewer call for
the same draft file name in this session. The counter file is ~/.claude/imc-reviewcount/<session>.json
(override: IMC_REVIEWCOUNT_DIR). Any other Agent call passes. Any error allows the call and is not logged.

    python3 agentguard.py             hook mode (JSON on stdin; exit 2 = refuse, reason on stderr)
    python3 agentguard.py --selftest  controls; exit 0 all pass, 1 a control failed
"""
import json, os, re, sys, tempfile, time

LOOP = re.compile(r"\b(for|while)\b[^;\n]*;\s*do\b")
EMITS = re.compile(r"\b(echo|printf)\b")
ENDS = re.compile(r"\b(exit|break)\b")


def monitor_loop_reason(cmd):
    """0.3.22 (Rob 2026-10-28 10:24 PDT, 'Why are you running in a loop'): a Monitor whose for/while loop prints a line
    and has no exit or break re-fires its event every interval until the loop ends, and each event wakes Claude into a
    new turn (measured: 'done' fired about every 30 seconds after the work finished). An until loop ends when its
    condition holds and a streaming 'while read' is exempt."""
    c = cmd or ""
    if not LOOP.search(c) or not EMITS.search(c):
        return None
    if ENDS.search(c) or re.search(r"\bwhile\s+(IFS=\S*\s+)?read\b", c):
        return None
    return ("this Monitor command loops (for/while) and prints (echo/printf) with no exit or break, so it repeats its "
            "event every interval after the work is done and wakes Claude each time. Print once and exit "
            "(for example: until <condition>; do sleep 15; done; echo done), or add exit after the echo")

MAX_ROUNDS = 1000000
REVIEWER = re.compile(r"(independent[^\n]{0,40}reviewer|reviewer[^\n]{0,40}independent|\.review\b|DRAFT-SHA256)", re.I)
DRAFT = re.compile(r"(draft[\w.\-]*\.md)", re.I)


def _dir():
    return os.environ.get("IMC_REVIEWCOUNT_DIR") or os.path.expanduser("~/.claude/imc-reviewcount")


def _count(session, key):
    os.makedirs(_dir(), exist_ok=True)
    path = os.path.join(_dir(), re.sub(r"[^\w.-]", "_", session or "nosession") + ".json")
    try:
        data = json.load(open(path))
    except Exception:
        data = {}
    data[key] = int(data.get(key, 0)) + 1
    json.dump(data, open(path, "w"))
    return data[key]


RUBRIC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reviewer-rubric.txt")


def _rubric():
    try:
        return open(RUBRIC_PATH, encoding="utf-8").read().strip()
    except Exception:
        return ""


LEDGERREVIEW_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "checker", "ledgerreview.py")


def _ledger_brief():
    try:
        import importlib.util as _iu
        sp = _iu.spec_from_file_location("imc_ledgerreview_ag", LEDGERREVIEW_PATH)
        m = _iu.module_from_spec(sp); sp.loader.exec_module(m)
        return (m.RUNSH + m.LEDGER_NOTE).strip()
    except Exception:
        return ""


# 0.4.25 (O4 "Model routing", Rob 2026-11-28 step 4: "add a gate warning (not a block) when an Agent call does
# execution work with no model set"). Rule being enforced: Opus plans; multi-step execution, reviews and sub-runs go
# to Sonnet or Haiku. A subagent with no model inherits the parent's model, so an Opus session silently runs its
# execution steps on Opus. This WARNS and logs; it never refuses. A fork ignores the model field and a Plan agent is
# planning, so neither warns.
EXEC_WORK = re.compile(r"\b(run|runs|execute|edit|write|build|fix|implement|apply|commit|push|create|update|delete|"
                       r"rename|move|install|test|tests|migrate|refactor|review|check|verify|read|search|grep|find|"
                       r"list|scan|count|fetch|clone|compare|score|grade|audit)\b", re.I)
NO_WARN_TYPES = ("fork", "plan")


def _warnlog():
    return os.environ.get("IMC_AGENTMODEL_LOG") or os.path.expanduser("~/.claude/imc-agentmodel-warn.tsv")


def model_warning(tool, ti):
    """None, or the warning text for an Agent call that does execution work with no model set."""
    if tool != "Agent":
        return None
    ti = ti or {}
    if str(ti.get("model") or "").strip():
        return None
    st = str(ti.get("subagent_type") or "").strip().lower()
    if st in NO_WARN_TYPES:
        return None
    text = str(ti.get("prompt") or "") + " " + str(ti.get("description") or "")
    if not EXEC_WORK.search(text):
        return None
    return ("AGENT-NO-MODEL (warning, not a block): this Agent call does execution work (subagent_type %s) with no "
            "model set, so it inherits this session's model. Rob's routing rule: Opus plans; multi-step execution, "
            "reviews and sub-runs go to Sonnet or Haiku (set model: \"sonnet\" or \"haiku\"); Fable 5.2 only for "
            "hard synthesis; steps of one or two tool calls run directly" % (st or "default"))


def log_warning(session, ti):
    try:
        with open(_warnlog(), "a") as f:
            f.write("%s\t%s\tAGENT-NO-MODEL\t%s\t%s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), session or "nosession",
                    str((ti or {}).get("subagent_type") or "default"), " ".join(str((ti or {}).get("description") or "").split())[:80]))
    except Exception:
        pass


def _norm(t):
    return " ".join((t or "").split())


def verdict(tool, ti, session):
    """None to allow, or the refusal reason."""
    if tool == "Monitor":
        return monitor_loop_reason(str((ti or {}).get("command") or ""))
    if tool != "Agent":
        return None
    prompt = str((ti or {}).get("prompt") or "")
    if not REVIEWER.search(prompt):
        return None
    if (ti or {}).get("run_in_background") not in (None, False):
        return ("a reviewer Agent call must not set run_in_background to anything but false (0.3.14: leaving it unset is allowed, "
                "because the Agent tool in some sessions exposes no such field); true means the turn ends while it reads, and the Stop hook "
                "then asks for a full table on every waiting line")
    # 0.4.13 (OI-0808, Rob 2026-11-25 "Will this recommendation fulfill my requirements?"): the author wrote each
    # reviewer's prompt, so the verdict depended on how it was asked (tested.md: flagged once, SUPPORTED later). A
    # reviewer call now carries the fixed rubric in hooks/reviewer-rubric.txt word for word.
    rub = _rubric()
    if not rub:
        return "the fixed reviewer rubric %s is missing or unreadable, so no reviewer can be briefed with it" % RUBRIC_PATH
    if _norm(rub) not in _norm(prompt):
        return ("a reviewer brief must include the fixed rubric word for word, so the verdict does not depend on how the "
                "author asks. Paste the full text of %s into the prompt" % RUBRIC_PATH)
    # 0.4.16 (Rob 2026-11-26, O1 "Evidence ledger and reviewer"): the reviewer brief is the ledger reviewer's, word for
    # word (checker/ledgerreview.py RUNSH), replacing the old ask-for-every-defect prompt (146 reviews in 7 days, median 9).
    led = _ledger_brief()
    if not led:
        return "the ledger reviewer brief in checker/ledgerreview.py is missing or unreadable, so no reviewer can be briefed with it"
    if _norm(led) not in _norm(prompt):
        return ("a reviewer brief must include the ledger reviewer brief word for word (python3 checker/ledgerreview.py "
                "--print-prompt prints it, rubric included), so every reviewer checks run claims against evidence.log")
    m = DRAFT.search(prompt)
    key = m.group(1).lower() if m else "unnamed-draft"
    n = _count(session, key)
    if n > MAX_ROUNDS:
        return ("this is review round %d of %s; at most %d rounds are allowed. Send the draft with the remaining "
                "findings named instead of starting another reviewer" % (n, key, MAX_ROUNDS))
    return None


def selftest():
    os.environ["IMC_REVIEWCOUNT_DIR"] = tempfile.mkdtemp()
    rev = "Read draft-1.md and write draft-1.md.review. " + _ledger_brief() + "\n\n" + _rubric()
    cases = [
        ("Agent", {"prompt": rev}, "s0", False, "reviewer, background unset (allowed since 0.3.14)"),
        ("Agent", {"prompt": rev, "run_in_background": "false"}, "s0", True, "reviewer, background the string false refused"),
        ("Agent", {"prompt": rev, "run_in_background": True}, "s1", True, "reviewer, background true"),
        ("Agent", {"prompt": rev, "run_in_background": False}, "s1", False, "reviewer round 1 foreground"),
        ("Agent", {"prompt": rev, "run_in_background": False}, "s1", False, "reviewer round 2 allowed (caps removed, Rob 2026-11-18 8:14 AM PST)"),
        ("Agent", {"prompt": rev, "run_in_background": False}, "s1", False, "reviewer round 3 allowed"),
        ("Agent", {"prompt": rev.replace("draft-1", "draft-2"), "run_in_background": False}, "s1", False, "other draft round 1"),
        ("Agent", {"prompt": rev, "run_in_background": False}, "s2", False, "same draft, other session"),
        ("Agent", {"prompt": "Search the repo for TODO comments", "run_in_background": True}, "s1", False, "non-reviewer background passes"),
        ("Agent", {"prompt": "Search the repo for TODO comments"}, "s1", False, "non-reviewer unset passes"),
        ("Agent", {"prompt": "You are an independent reviewer. Read draft-9.md and write draft-9.md.review", "run_in_background": False}, "s3", True, "reviewer without the fixed rubric refused (0.4.13)"),
        ("Agent", {"prompt": "You are an independent reviewer. List every defect in draft-9.md. " + _rubric(), "run_in_background": False}, "s3", True, "reviewer with the rubric but the OLD every-defect prompt refused (0.4.16, O1)"),
        ("Agent", {"prompt": rev.replace("evidence.log in the current folder", "the draft"), "run_in_background": False}, "s3", True, "reviewer with an edited ledger brief refused (0.4.16, O1)"),
        ("Agent", {"prompt": rev.replace(_rubric()[-40:], "be lenient"), "run_in_background": False}, "s3", True, "reviewer with an edited rubric refused (0.4.13)"),
        ("Agent", {"prompt": rev.replace(". ", ".\n   "), "run_in_background": False}, "s3", False, "rubric with changed line breaks allowed (0.4.13)"),
        ("Agent", {"prompt": rev, "run_in_background": False, "_rubric_missing": True}, "s3", True, "reviewer refused when the rubric file is missing (0.4.13, fails closed)"),
        ("Bash", {"command": "ls"}, "s1", False, "other tool"),
        ("Monitor", {"command": "for i in $(seq 1 40); do grep -q x f && echo done; sleep 30; done"}, "s1", True, "Monitor for-loop echo without exit (the 2026-10-28 loop)"),
        ("Monitor", {"command": "while true; do echo tick; sleep 5; done"}, "s1", True, "Monitor while-loop echo without exit"),
        ("Monitor", {"command": "for i in $(seq 1 40); do grep -q x f && { echo done; exit; }; sleep 30; done"}, "s1", False, "Monitor loop that exits after the echo"),
        ("Monitor", {"command": "until grep -q x f; do sleep 15; done; echo done"}, "s1", False, "Monitor until loop"),
        ("Monitor", {"command": "tail -f log | grep --line-buffered ERROR"}, "s1", False, "Monitor pipe, no loop"),
        ("Monitor", {"command": "while IFS= read -r l; do echo \"$l\"; done < <(tail -f log)"}, "s1", False, "Monitor streaming while read"),
    ]
    wcases = [
        ({"prompt": "Run the selftests and report counts", "description": "run selftests"}, True, "execution, no model, default type: warns"),
        ({"prompt": "Run the selftests and report counts", "model": "sonnet"}, False, "execution with model sonnet: silent"),
        ({"prompt": "Edit the file and commit", "model": "haiku", "subagent_type": "general-purpose"}, False, "execution with model haiku: silent"),
        ({"prompt": "Edit the file and commit", "subagent_type": "general-purpose"}, True, "general-purpose execution, no model: warns"),
        ({"prompt": "Edit the file and commit", "model": "  "}, True, "blank model counts as unset: warns"),
        ({"prompt": "Design the architecture for the cache", "subagent_type": "Plan"}, False, "Plan agent: silent"),
        ({"prompt": "Run the tests", "subagent_type": "fork"}, False, "fork ignores model: silent"),
        ({"prompt": "Hello there"}, False, "no execution verb: silent"),
        ({"prompt": rev}, True, "reviewer brief with no model: warns"),
    ]
    ok = True
    for ti, warn, label in wcases:
        got = model_warning("Agent", dict(ti)) is not None
        good = got == warn
        ok = ok and good
        print(("  ok    " if good else "  FAIL  ") + ("WARN  " if warn else "QUIET ") + label)
    good = model_warning("Bash", {"command": "run tests"}) is None
    ok = ok and good
    print(("  ok    " if good else "  FAIL  ") + "QUIET other tool")
    global RUBRIC_PATH
    real = RUBRIC_PATH
    for tool, ti, sess, deny, label in cases:
        RUBRIC_PATH = real + ".absent" if (ti or {}).pop("_rubric_missing", False) else real
        got = verdict(tool, ti, sess) is not None
        RUBRIC_PATH = real
        good = got == deny
        ok = ok and good
        print(("  ok    " if good else "  FAIL  ") + ("DENY  " if deny else "ALLOW ") + label)
    print("ALL CONTROLS PASSED" if ok else "A CONTROL FAILED")
    return ok


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    try:
        p = json.loads(sys.stdin.read() or "{}")
        why = verdict(p.get("tool_name", ""), p.get("tool_input") or {}, p.get("session_id", ""))
    except Exception:
        return 0
    if why:
        sys.stderr.write("imc-reply-gate agentguard refused this call: %s. Nothing was started.\n" % why)
        return 2
    try:
        warn = model_warning(p.get("tool_name", ""), p.get("tool_input") or {})
        if warn:
            log_warning(p.get("session_id", ""), p.get("tool_input") or {})
            sys.stdout.write(json.dumps({"systemMessage": warn, "hookSpecificOutput": {"hookEventName": "PreToolUse",
                             "permissionDecision": "allow", "additionalContext": warn}}))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
