"""0.4.12 (OI-0808): a stamp is refused unless the reviewer's RECOMMENDATION-CHECK opens with SUPPORTED.
Fixture: the 4:53 PM PST 2026-11-25 draft and its real review record (verdict PARTLY SUPPORTED)."""
import os, re, sys, shutil, tempfile, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); FX = os.path.join(HERE, "fixtures_oi0808")
def run(verdict):
    d = tempfile.mkdtemp(); shutil.copy(os.path.join(FX, "help.md"), d); shutil.copy(os.path.join(FX, "help.md.reviewed"), d)
    rt = open(os.path.join(FX, "help.md.review")).read()
    if verdict is not None:
        rt = re.sub(r"^RECOMMENDATION-CHECK:.*$", "RECOMMENDATION-CHECK: " + verdict, rt, flags=re.M)
    open(os.path.join(d, "help.md.review"), "w").write(rt)
    f = os.path.join(d, "help.md")
    o = subprocess.run([sys.executable, os.path.join(HERE, "replycheck.py"), f], capture_output=True, text=True,
                       env=dict(os.environ, REPLYCHECK_DRAFT=f))
    return "REC-NOT-SUPPORTED" in o.stdout + o.stderr
cases = [("real PARTLY SUPPORTED record refused", run(None), True),
         ("NOT SUPPORTED refused", run("NOT SUPPORTED - row 1 rests on an in-sample scan"), True),
         ("free text refused", run("Row 1 follows from the evidence above in full"), True),
         ("CONTROL: SUPPORTED passes", run("SUPPORTED - row 1 cites a run of the change on a copy"), False)]
ok = sum(g == w for _, g, w in cases)
for n, g, w in cases: print(("ok  " if g == w else "FAIL"), n, g)
print("%d of %d ok" % (ok, len(cases))); sys.exit(0 if ok == len(cases) else 1)
