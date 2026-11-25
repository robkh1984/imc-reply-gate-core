#!/usr/bin/env python3
"""0.3.3 selftest for the send path in hooks/gate.py pretool: progress lane, long unstamped text, retype, duplicate.
Runs the real hook under a throwaway HOME so no real state is touched. Exit 0 only if every control passes."""
import json, os, subprocess, sys, tempfile, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "gate.py")
TSV = os.path.expanduser("~/.claude/imc-reply-gate-prechecked.tsv")
SCOPE = ("This session is bound to a claude.ai Project",)
home = tempfile.mkdtemp()
os.makedirs(home + "/.claude")
tp = home + "/t.jsonl"
open(tp, "w").write(json.dumps({"type": "user", "message": {"role": "user", "content": SCOPE[0]}}) + "\n")
sys.path.insert(0, os.path.join(ROOT, "hooks"))
def run(msg, sess, tool="SendUserMessage"):
    env = dict(os.environ, HOME=home)
    p = subprocess.run([sys.executable, HOOK, "pretool"], capture_output=True, text=True, env=env,
                       input=json.dumps({"session_id": sess, "transcript_path": tp, "tool_name": tool, "tool_input": {"message": msg}}))
    return p.returncode, p.stderr
# 0.3.90 (OI-0748): the retype and duplicate controls stamp their OWN fixture inside the throwaway HOME. Until 0.3.89
# they borrowed the newest stamped draft from the live ledger, so the result depended on what was stamped last: on
# 2026-11-24 a table-less stamped reply made two controls FAIL with EVERY-REPLY-TABLE while the same code passed when
# pinned to a draft with a table. The fixture is a complete reply with a next-steps table that the pretool checks
# accept, stamped with gate.norm_sha into a ledger that exists only in the throwaway HOME.
import gate as _gate
FIX = home + "/fixture-draft.md"
FIXTEXT = 'The fixture build is ready, and it needs your ruling before it ships.\n\nROOT CAUSE: none - this is a selftest fixture, not a repair.\n\nCHECKED: `python3 checker/sendpath_selftest.py` on the fixture build -> "ALL CONTROLS PASSED", exit 0; 9:00 AM PST.\nPRE-SEND REVIEW: independent reviewer returned 0 findings; 0 fixed; 0 disputed because none were raised; fixed rows none.\nSELF-CHECK: thorough: yes, confidence: 9/10 in row 1, lower if the fixture selftest fails on a clean machine.\n\nPROJECT OBJECTIVE 1 - Selftest fixture [IN PROGRESS]\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | The fixture build waits for a ruling. CAUSE: measured - the CHECKED line above. BLOCKS: none | Approve: reply "ship it" and the fixture build ships. Reply "hold" and nothing changes | Rob | RECOMMEND: choose "ship it" over holding, because the selftest passed. TESTED (the CHECKED line above) | One step | Con:&nbsp;one&nbsp;more&nbsp;step&nbsp;for&nbsp;you<br>• Risk: the fixture is wrong.<br>• Mitigation: the selftest re-runs on every build. |\n'
open(FIX, "w").write(FIXTEXT)
FIX_TSV = home + "/fixture-prechecked.tsv"
open(FIX_TSV, "w").write("%s\t2026-01-01T00:00:00-08:00\t%s\tpanel=fixture\n" % (_gate.norm_sha(open(FIX).read()), FIX))
stamped = (FIX, "fixture")
ok = True
def check(name, cond):
    global ok
    print(("  ok    " if cond else "  FAIL  ") + name); ok = ok and cond
rc, _ = run("Working on row 3 now.", "s1");            check("ALLOW progress line without a table", rc == 0)
rc, err = run("x " * 300 + "\n\nno table here", "s2");   check("BLOCK (0.3.88, PLAIN_STAMP on) long unstamped text without a table", rc != 0 and "PRECHECK-MISSING" in err)
rc, err = run("Sonnet run judged 0 items. " * 20, "s2p", "PushNotification");   check("BLOCK (0.3.88) long unstamped PushNotification without a table", rc != 0 and "PRECHECK-MISSING" in err)
rc, _ = run("Run passed.", "s1p", "PushNotification");   check("ALLOW (0.3.88) short PushNotification under PROGRESS_MAX", rc == 0)
tbl = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | a long enough issue text to count as context for this control row | Decide: reply yes | Rob | TESTED: x | p | c |\n"
rc, err = run("x " * 300 + "\n\n" + tbl, "s2t");   check("DENY long unstamped text WITH a table (PRECHECK-MISSING)", rc == 2 and "PRECHECK-MISSING" in err)
if stamped:
    shutil.copy(FIX_TSV, home + "/.claude/imc-reply-gate-prechecked.tsv")
    d = open(stamped[0]).read()
    rc, err = run(d + " ", "s3");  check("ALLOW same text with only trailing whitespace (normalized)", rc == 0)
    rc, err = run(d.replace("a", "b", 1), "s4"); check("0.3.88: one-character retype of a stamped draft is refused for a stamp", "PRECHECK-MISSING" in err)
    rc1, _ = run(d, "s5"); rc2, err2 = run(d, "s5"); check("DENY second send of the same stamped text", rc1 == 0 and rc2 == 2 and "DUPLICATE-SEND" in err2)
else:
    print("  skip  no stamped draft file on disk for the retype and duplicate controls")
shutil.rmtree(home, ignore_errors=True)
print("ALL CONTROLS PASSED" if ok else "FAILED"); sys.exit(0 if ok else 1)
