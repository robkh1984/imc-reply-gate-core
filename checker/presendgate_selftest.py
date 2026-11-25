"""presendgate_selftest.py (imc-reply-gate 0.3.68, 2026-11-19 07:20 PST)

Controls for precheck.presend_fails, the check that refuses a stamp unless Rob's bin/presend.py has been run on the
draft being gated. Why it exists: on 2026-11-19 presend.py found 13 defects in a draft - among them a recommendation
labelled TESTED that Claude was barred from testing - that precheck.py had not raised, and Claude had skipped the
stricter checker on three consecutive replies. The project's own measurement (2026-08-15) puts a remembered rule at
3 to 6 percent against a check that fails on its own, so the rule became this check and this file keeps it honest
across versions: a positive control (fresh run passes), two negative controls (missing, stale), and one for the
instrument itself (stricter checker absent -> the check says so rather than passing silently).

Run: python3 presendgate_selftest.py     exits 0 when every control passes, 1 otherwise.
"""
import os
import sys
import time
import tempfile
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("precheck_mod", os.path.join(HERE, "precheck.py"))
precheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(precheck)

PASS, FAIL = [], []


def check(name, got_codes, want):
    (PASS if got_codes == want else FAIL).append("%s: want %s, got %s" % (name, want or "no code", got_codes or "no code"))


def codes(draft, stricter):
    return [c for c, _m in precheck.presend_fails(draft, stricter=stricter)]


def run():
    d = tempfile.mkdtemp(prefix="presendgate-")
    draft = os.path.join(d, "reply.md")
    ps = draft + ".presend"
    stricter = os.path.join(d, "presend.py")
    open(draft, "w").write("a draft\n")
    open(stricter, "w").write("# stand-in for Rob's presend.py\n")

    # 1 NEGATIVE: no .presend beside the draft - the skip this check exists to catch.
    check("missing", codes(draft, stricter), ["PRESEND-MISSING"])

    # 2 POSITIVE: a .presend newer than the draft - the only state that may be stamped.
    open(ps, "w").write("  FAIL  [X] a rule fired\n\n  13 disk FAIL, replycheck exit 1\n")  # 0.3.70: a real closing line, not a bare count
    os.utime(ps, (time.time() + 5, time.time() + 5))
    check("fresh", codes(draft, stricter), [])

    # 3 NEGATIVE: the draft edited after the run, so the record describes text that has changed.
    os.utime(draft, (time.time() + 60, time.time() + 60))
    check("stale", codes(draft, stricter), ["PRESEND-STALE"])

    # 4 INSTRUMENT: the stricter checker itself missing - a check that cannot run must not pass.
    check("stricter absent", codes(draft, os.path.join(d, "nope.py")), ["PRESEND-ABSENT"])

    # 5 NEGATIVE, 0.3.70: a hang leaves the shell's 0-byte redirect file. Existence is not the run.
    os.utime(draft, (time.time() - 60, time.time() - 60))
    open(ps, "w").write("")
    os.utime(ps, (time.time() + 5, time.time() + 5))
    check("empty .presend", codes(draft, stricter), ["PRESEND-INCOMPLETE"])

    # 6 NEGATIVE: a partial run, cut off before its closing summary, is also not a run.
    open(ps, "w").write("  FAIL  [SOMETHING] a rule fired but the run never finished\n")
    os.utime(ps, (time.time() + 5, time.time() + 5))
    check("truncated .presend", codes(draft, stricter), ["PRESEND-INCOMPLETE"])

    # 7 POSITIVE: presend's own closing line is what proves the run reached the end.
    open(ps, "w").write("  FAIL  [SOMETHING] x\n\n  3 disk FAIL, replycheck exit 1\n")
    os.utime(ps, (time.time() + 5, time.time() + 5))
    check("complete .presend", codes(draft, stricter), [])

    for ln in PASS:
        print("PASS  " + ln)
    for ln in FAIL:
        print("FAIL  " + ln)
    print("%d PASS, %d FAIL" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(run())
