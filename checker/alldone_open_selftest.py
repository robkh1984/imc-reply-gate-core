"""0.4.8 selftest: ALL OBJECTIVES DONE is cancelled by the status word OPEN, not by the plain word "open"; and precheck
runs EVERY-REPLY-TABLE as the Stop hook does."""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import replycheck as rc
ok = tot = 0
def t(name, got, want):
    global ok, tot
    tot += 1; r = got == want; ok += r; print(("ok  " if r else "FAIL"), name, "got", repr(got))
D = 'ALL OBJECTIVES DONE: `openitems.py close` returned "CLOSED OI-0783 as DONE" at 2:15 PM PST.'
t("lowercase open keeps the exemption", rc._all_done_exempt("That was the last open row.\n" + D + "\n"), True)
t("CONTROL: status word OPEN cancels it", rc._all_done_exempt("OI-0790 stays OPEN.\n" + D + "\n"), False)
t("CONTROL: BLOCKED: cancels it", rc._all_done_exempt("BLOCKED: x\n" + D + "\n"), False)
t("CONTROL: no done line, no exemption", rc._all_done_exempt("All good.\n"), False)
t("0.4.10: a reply naming unresolved points loses the exemption", rc._all_done_exempt("Two panel points stay unresolved.\n" + D + "\n"), False)
t("0.4.10 CONTROL: a resolved reply keeps it", rc._all_done_exempt("Both checks ran and passed.\n" + D + "\n"), True)
d = tempfile.mkdtemp(); f = os.path.join(d, "r.md"); open(f, "w").write("The fix is in.\n")
env = dict(os.environ, IMC_PRECHECK_PANEL="0")
p = subprocess.run([sys.executable, os.path.join(HERE, "precheck.py"), f], capture_output=True, text=True, env=env)
t("precheck runs EVERY-REPLY-TABLE on a table-less draft", "EVERY-REPLY-TABLE" in p.stdout, True)
env["IMC_EVERY_REPLY_TABLE"] = "0"
p = subprocess.run([sys.executable, os.path.join(HERE, "precheck.py"), f], capture_output=True, text=True, env=env)
t("CONTROL: IMC_EVERY_REPLY_TABLE=0 turns it off in precheck", "EVERY-REPLY-TABLE" in p.stdout, False)
print("%d of %d ok" % (ok, tot)); sys.exit(0 if ok == tot else 1)
