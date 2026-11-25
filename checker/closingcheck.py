#!/usr/bin/env python3
"""closingcheck.py (imc-reply-gate 0.2.17): a closing line may not say nothing remains / all done while the reply's own
next-steps table holds an open Claude row (Owner Claude, Action not 'NO-ARTIFACT: DONE' or 'no action').
    python3 closingcheck.py <reply.md>   exit 0 clean, 1 fail"""
import re, sys
CLAIM = re.compile(r"nothing (remains|is left|left)|all (the )?(work )?(is )?(done|finished)|work is finished|nothing else (remains|to do)", re.I)


def closing_fails(text):
    prose = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("|")]
    tail = " ".join(prose[-3:])
    m = CLAIM.search(tail)
    rows = []
    for l in text.splitlines():
        p = [x.strip() for x in l.strip().strip("|").split("|")]
        if len(p) >= 7 and p[0].isdigit() and p[3] == "Claude" and not re.search(r"NO-ARTIFACT:\s*(DONE|no action)", p[2], re.I):
            rows.append(p[0])
    if m and rows:
        return [("CLOSING-CLAIM", "the closing says '%s' while open Claude rows remain in the table: %s" % (m.group(0), ", ".join(rows)))]
    return []


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        bad = 0
        t = "| # | a | b | Owner | c | d | e |\n|---|---|---|---|---|---|---|\n| 1 | x | build it | Claude | r | p | c |\n\nThe work is finished and nothing remains on my side.\n"
        for name, txt, want in (("claim with open Claude row fails", t, True),
                                ("no claim passes", t.replace("The work is finished and nothing remains on my side.", "Row 1 is open."), False),
                                ("claim with only DONE rows passes", t.replace("build it", "NO-ARTIFACT: DONE"), False)):
            ok = bool(closing_fails(txt)) == want; bad += (not ok); print("%s %s" % ("OK " if ok else "BAD", name))
        print("SELFTEST %s" % ("CONTROLS OK" if not bad else "BAD")); sys.exit(1 if bad else 0)
    f = closing_fails(open(sys.argv[1], encoding="utf-8").read())
    for c, m in f: print("FAIL  [%s] %s" % (c, m))
    print("CLOSINGCHECK %s" % ("FAIL" if f else "CLEAN")); sys.exit(1 if f else 0)
