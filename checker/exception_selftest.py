#!/usr/bin/env python3
"""exception_selftest.py - controls for gate.py exception_fails (EXCEPTION-REJECTED, 0.3.2). Exit 0 all pass."""
import importlib.util, os, sys
here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("gate", os.path.join(here, "..", "hooks", "gate.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
H = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
CASES = [
    ("I add a waiver for this check", "I recommend an exemption for this row", True),
    ("I read the waiver reason for all 12 codes and bring them to you for approval", "one approval ask per code", False),
    ("I add a reply-gate check that fails any row whose Action or Recommendation asks for an exemption, exception or waiver",
     "I recommend building it, since it is the code form of your rule against exceptions", False),
    ("I raise the baseline from 2 to 3", "I recommend letting it pass", True),
    ("I record the failure", "I recommend we keep the waiver for now", True),
    ("No exception is requested", "I do not recommend an exemption", False),
]
ok = True
for a, r, deny in CASES:
    got = bool(m.exception_fails(H + "| 1 | x | %s | Claude | %s | p | c |" % (a, r)))
    good = got == deny
    ok = ok and good
    print(("  ok    " if good else "  FAIL  ") + ("DENY  " if deny else "ALLOW ") + a[:60])
print("ALL CONTROLS PASSED" if ok else "A CONTROL FAILED")
sys.exit(0 if ok else 1)
