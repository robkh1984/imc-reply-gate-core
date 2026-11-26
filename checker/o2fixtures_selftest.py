"""core serial 23 (O2, Rob 2026-11-26): the 20 held-out fixtures for the 6-column table, run through precheck.py.
10 valid and 10 invalid replies, 2 of them scheduled-task reports on each side; I01 and I02 are cells that say TESTED
with no supporting evidence.log line, V04 is a supported cell with no such word. Each review record in reviews/ is the
real output of checker/ledgerreview.py (sonnet, rubric 0.4.21) on Rob's Mac, 2026-11-26; the classification below is
deterministic given those records. Exit 0 = 20 of 20 classified as KEY.json says."""
import json, os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); FX = os.path.join(HERE, "fixtures_o2")
K = json.load(open(os.path.join(FX, "KEY.json"))); ok = 0
for name, k in sorted(K.items()):
    d = tempfile.mkdtemp(prefix="o2fx-"); home = tempfile.mkdtemp(prefix="o2home-")
    shutil.copy(os.path.join(FX, "cases", name + ".md"), d)
    rv = os.path.join(FX, "reviews", name + ".md.review")
    if os.path.isfile(rv):
        shutil.copy(rv, d)
    env = dict(os.environ, HOME=home, IMC_PRECHECK_PANEL="0", REPLY_GATE_REPLAY="0",
               IMC_EVIDENCE_LOG=os.path.join(FX, "ledgerroot", k["ledger"], "evidence.log"))
    for v in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "IMC_PRESEND", "IMC_REPLYGATE"):
        env.pop(v, None)
    p = subprocess.run([sys.executable, os.path.join(HERE, "precheck.py"), os.path.join(d, name + ".md")],
                       capture_output=True, text=True, env=env)
    codes = sorted(set(re.findall(r"^FAIL  \[([^\]]+)\]", p.stdout, re.M)))
    good = (p.returncode == 0) == k["valid"]; ok += good
    print("%s %s valid=%s rc=%d %s" % ("ok  " if good else "MISS", name, k["valid"], p.returncode, ",".join(codes)))
print("O2 FIXTURES: %d of %d correct" % (ok, len(K)))
sys.exit(0 if ok == len(K) else 1)
