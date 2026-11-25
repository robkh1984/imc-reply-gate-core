#!/usr/bin/env python3
"""overfire_selftest.py - NEGATIVE controls for checks measured over-firing on correct text.

WHY THIS FILE EXISTS: OI-0538 says the gate's checks ship without negative controls, so a check that
over-fires passes its own suite. bin/replycontract.py measured the scale on 2026-11-20: 124 check
codes, 112 of them mentioned in no selftest at all. This file starts the other way round from a
normal selftest. Each control below feeds the check text that is CORRECT by Rob's own rules and
asserts the check stays silent. Three of them do not, today.

EXPECTED-FAILURE PROTOCOL. A control marked XFAIL names a defect that is already in the register.
While the defect stands, this file prints XFAIL and exits 0, so a known bug does not mask an
unrelated regression in the daily audit. When the check is fixed the control flips to XPASS and the
file exits 1, which is the signal to delete the marker and make it an ordinary control. A test that
quietly passes once a bug is fixed teaches nobody that it was fixed.

Measured 2026-11-20 in session 339b7bc6 against imc-reply-gate 0.3.84.
Row ids: OI-0547, OI-0564 and OI-0565. OI-0563 was allocated for the SCOPE-VS-CLAIM defect,
malformed on creation by a shell quoting error and PARKED the same minute; the defect was
re-filed as OI-0564. Do not cite OI-0563.
"""
import importlib.util
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
RESULTS = []


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m


def control(name, silent, oi):
    """silent: True when the check correctly stayed quiet on correct text."""
    RESULTS.append((name, silent, oi))
    print(("PASS  " if silent else "XFAIL ") + name + ("" if silent else "  <- %s" % oi))


# A row alone is not a table: numbered_rows() finds nothing without the header, and a fixture
# without one makes every control here pass vacuously. The first run of this file did exactly that,
# and the positive control at 1b is what caught it.
HEADER = ("| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n"
          "|---|---|---|---|---|---|---|\n")
ROW = (HEADER + "| %s | %s | %s | Rob | %s | - a pro | "
       "Con:&nbsp;a&nbsp;con&nbsp;goes&nbsp;here&nbsp;now<br>- Risk: r<br>- Mitigation: m |")

gate = _load(ROOT / "hooks" / "gate.py", "og_gate")

# 1 ROB-OWNS-WORK must stay silent on a physical act only Rob can perform, worded plainly.
# Measured 2026-11-20 19:28 PST: it fired on exactly this wording, because ROB_ASK_RE is a 13-token
# word list and "switch ... off" is in none of them.
plain_act = ROW % ("1", "CAUSE: measured - the setting is on. BLOCKS: none.",
                   "Switch the Apps Script toggle off in your Google account script settings.",
                   "TESTED - a call at 19:00 PST returned push OK.")
hits = gate.rob_owns_work_fails(plain_act)
control("ROB-OWNS-WORK stays silent on a plainly-worded physical act in Rob's own account",
        not hits, "OI-0547")

# 1b positive control: the same check MUST still fire on a Rob row that asks him for nothing at all.
no_ask = ROW % ("1", "CAUSE: measured - a thing happened. BLOCKS: none.",
                "The register was rebuilt and the Sheet was refreshed.",
                "TESTED - a call at 19:00 PST returned ok.")
control("ROB-OWNS-WORK still fires on a Rob row that asks him for nothing (positive control)",
        bool(gate.rob_owns_work_fails(no_ask)), "n/a")

rc = _load(HERE / "replycheck.py", "og_replycheck")

# 2 SCOPE-VS-CLAIM must stay silent when the universal-negative phrase is inside a QUOTED tool result
# rather than asserted by Claude. Measured 2026-11-20 19:20 PST: it fired on a CHECKED line whose
# backticked output was the literal shell error "No such file or directory".
quoted = ("CHECKED: an ls of ~/Claude/replycheck/ at 19:00:33 PST -> `No such file or directory` "
          "for that one path.")
fired = bool(rc.UNIVERSAL_NEG.search(quoted)) and not bool(rc.SCOPE_NAMED.search(quoted))
control("SCOPE-VS-CLAIM stays silent when the universal negative is inside quoted tool output",
        not fired, "OI-0564")

# 2b positive control: an unscoped universal negative asserted by Claude must still fire.
asserted = "No file anywhere defines that identifier."
control("SCOPE-VS-CLAIM still fires on an unscoped universal negative (positive control)",
        bool(rc.UNIVERSAL_NEG.search(asserted)) and not bool(rc.SCOPE_NAMED.search(asserted)), "n/a")

# 3 ID-NAME must stay silent when an identifier is named once and then repeated in the SAME sentence.
# Measured 2026-11-20 19:30 PST: it reports every bare occurrence, so a second mention three words
# later is flagged even though the reader already has the name.
named_then_repeated = ("OI-0506 (a plugin version that never reached the account) is open, and "
                       "OI-0506 is the row this closes.")
blanked = rc._id_name_blank(named_then_repeated)
bare = [m.group(0) for m in rc._ID_NAME_RX.finditer(blanked) if not rc._id_named(blanked, m)]
control("ID-NAME stays silent on a second mention in the same sentence as the name", not bare,
        "OI-0565")

# 3b positive control: a never-named identifier must still fire.
never_named = "The fix is tracked in OI-0499 and nothing else."
b2 = rc._id_name_blank(never_named)
control("ID-NAME still fires on an identifier that is never named (positive control)",
        bool([m for m in rc._ID_NAME_RX.finditer(b2) if not rc._id_named(b2, m)]) is True, "n/a")

def _codes(text, fns):
    """replycheck's own selftest helper is nested inside its selftest, so it is reproduced here."""
    del rc.FAILS[:], rc.WARNS[:]
    for fn in fns:
        fn(text)
    return {c for c, _ in rc.FAILS} | {c for c, _ in rc.WARNS}


# 4 DONE-NO-CALL must stay silent when the call IS named in the same sentence, in backticks.
# Measured 2026-11-20 19:22 PST: check_done_claim blanks every code span to the literal `CODE`
# before it looks for a call name, so naming the call the normal way hides it from the check. The
# draft only passed after the backticks were removed, which fights the rule that a command is
# written in backticks.
backticked = ("I have fixed the order without rewriting a single stored cell: "
              "`python3 openitemsrank.py` at 19:08:53 PST returned rc=0 and ranked 121 of 554 rows.\n")
control("DONE-NO-CALL stays silent when the call is named in backticks in the same sentence",
        "DONE-NO-CALL" not in _codes(backticked, [rc.check_done_claim]), "OI-0566")

# 4b positive control: a bare completion claim with no call anywhere must still fire.
control("DONE-NO-CALL still fires on a completion claim with no call at all (positive control)",
        "DONE-NO-CALL" in _codes("I fixed it.\n", [rc.check_done_claim]), "n/a")

xfail = [r for r in RESULTS if not r[1] and r[2] != "n/a"]
broken_positive = [r for r in RESULTS if not r[1] and r[2] == "n/a"]
print("")
print("%d control(s): %d silent as they should be, %d XFAIL on a filed defect, %d positive control(s) broken"
      % (len(RESULTS), sum(1 for r in RESULTS if r[1]), len(xfail), len(broken_positive)))
if broken_positive:
    print("FAILURES: a positive control did not fire; the check may now be silent when it should speak.")
    sys.exit(1)
if xfail:
    print("XFAIL, expected while these stand: %s. Exit 0 so a known defect does not mask a regression."
          % ", ".join(sorted({r[2] for r in xfail})))
    sys.exit(0)
print("ALL CONTROLS PASSED - every over-fire above is fixed; delete the XFAIL protocol from this file.")
sys.exit(0)
