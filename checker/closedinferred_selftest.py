#!/usr/bin/env python3
"""closedinferred_selftest.py - controls for CLOSED-ON-INFERRED-CAUSE (core serial 6, OI-0789).
Case 1 is the measured 2026-11-25 reply shape that closed OI-0733 on an inferred root cause."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replycheck as R

CASES = [
    ("measured 2026-11-25 shape: inferred cause beside a closed row", True,
     "OI-0733 (routes that drive claude.ai settings are refused) is now closed.\n\nROOT CAUSE: inferred, not proven - the texts were written from a route that worked.\n\nCHECKED: `openitems.py close OI-0733` -> \"CLOSED OI-0733 as DONE\"; 6:08 AM PST.\n"),
    ("CHECKED close line alone with an inferred cause", True,
     "ROOT CAUSE: inferred - no check found.\n\nCHECKED: `openitems.py close OI-0999` -> \"CLOSED OI-0999 as DONE\"; 6:08 AM PST.\n"),
    ("measured cause beside a closed row passes", False,
     "OI-0736 (intake guard over-blocks) is closed.\n\nROOT CAUSE: measured - the old guard matched the name inside sed's script.\n"),
    ("inferred cause with no close passes", False,
     "OI-0788 (route re-test) stays open.\n\nROOT CAUSE: inferred, not proven - no re-test found in bin/.\n"),
    ("no ROOT CAUSE line passes", False, "OI-0001 (x) is now closed.\n"),
]


def main():
    bad = 0
    for name, want, text in CASES:
        R.FAILS.clear()
        R.check_closed_inferred(text)
        got = any(c == "CLOSED-ON-INFERRED-CAUSE" for c, _ in R.FAILS)
        ok = got == want
        bad += not ok
        print("  %-4s %s (want %s, got %s)" % ("ok" if ok else "FAIL", name, want, got))
    print("CLOSEDINFERRED SELFTEST %s" % ("FAIL" if bad else "OK"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
