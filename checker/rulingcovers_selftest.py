import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "hooks"))
import gate
HDR = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
def row(action, issue="x", reco="TESTED: yes"):
    return HDR + "| 1 | %s | %s | Rob | %s | p | c |\n" % (issue, action, reco)
cases = [
 (row("Rob approves deleting 5 fired one-shot scheduled tasks of the PT session"), 1),
 (row("Rob approves deleting 4 fired one-shot tasks", issue="each has persist_session false"), 0),
 (row("Rob approves deleting 5 one-shots", issue="they never fired"), 0),
 (row("Rob approves the plug-in upload"), 0),
]
bad = 0
for t, want in cases:
    got = len(gate.ruling_covers_row_fails(t))
    if got != want:
        bad += 1; print("FAIL want %d got %d: %s" % (want, got, t.splitlines()[-1][:90]))
print("rulingcovers_selftest %s" % ("OK" if not bad else "FAILED"))
sys.exit(1 if bad else 0)
