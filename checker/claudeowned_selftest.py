import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "hooks"))
import gate
HDR = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
def row(owner, action, issue="x"):
    return HDR + "| 1 | %s | %s | %s | TESTED: yes | p | c |\n" % (issue, action, owner)
cases = [
 (row("Claude", "Claude replays the recorded replies and reports the count"), 1),
 (row("Claude", "Claude runs the check", issue="BLOCKED: the call returned an error"), 0),
 (row("Rob", "Rob approves the upload"), 0),
]
bad = 0
for t, want in cases:
    got = len(gate.claude_row_runnable_fails(t))
    if got != want:
        bad += 1; print("FAIL want %d got %d: %s" % (want, got, t.splitlines()[-1][:90]))
print("claudeowned_selftest %s" % ("OK" if not bad else "FAILED"))
sys.exit(1 if bad else 0)
