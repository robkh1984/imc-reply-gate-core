import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks"))
import gate
H = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
bad = H + "| 1 | 0.3.53 is unproven in a live session | Decide yes or no to starting a new Claude Code session | Rob | TESTED (`ls` exited 0): yes | p | c |"
good = H + "| 1 | The gate refused the one-line reply | Decide yes or no to uploading the zip | Rob | TESTED (`gate.correction_only` returned True on the reply line): approve | p | c |"
assert gate.rec_relevance_fails(bad), "unrelated call must fire"
assert not gate.rec_relevance_fails(good), "related call must stay silent"
print("relevance_selftest OK")
