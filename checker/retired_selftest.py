#!/usr/bin/env python3
"""O5 serial 29 control: retired codes drop silently, demoted codes still warn, other codes still fail, and an
emptied retired list restores the warning (the rollback)."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import sixcol
ok = 0; bad = 0
def chk(name, cond):
    global ok, bad
    print(("ok   " if cond else "FAIL ") + name); ok += bool(cond); bad += (not cond)
sixcol.DEMOTE_LOG = os.path.join(tempfile.mkdtemp(), "demoted.tsv")
fails = [("SELFCHECK", "x"), ("NOT-RUN-CLAIM", "y"), ("REC-NO-EVIDENCE", "z"), ("PREVENTS", "w")]
kept, dem = sixcol.split_demoted(list(fails))
chk("retired SELFCHECK and PREVENTS are gone from both lists", not any(c in ("SELFCHECK", "PREVENTS") for c, _ in kept + dem))
chk("NOT-RUN-CLAIM still demoted to a warning", [c for c, _ in dem] == ["NOT-RUN-CLAIM"])
chk("REC-NO-EVIDENCE still fails", [c for c, _ in kept] == ["REC-NO-EVIDENCE"])
f2 = list(fails); w2 = []
sixcol.demote(f2, w2)
chk("demote(): retired codes print no WARN", [c for c, _ in w2 if c.startswith("DEMOTED:")] == ["DEMOTED:NOT-RUN-CLAIM"])
chk("demote(): only REC-NO-EVIDENCE left failing", [c for c, _ in f2] == ["REC-NO-EVIDENCE"])
log = open(sixcol.DEMOTE_LOG).read() if os.path.exists(sixcol.DEMOTE_LOG) else ""
chk("demoted.tsv logs NOT-RUN-CLAIM and no retired code", "NOT-RUN-CLAIM" in log and "SELFCHECK" not in log and "PREVENTS" not in log)
empty = os.path.join(tempfile.mkdtemp(), "retired.txt"); open(empty, "w").write("# none\n")
sixcol.RETIRED_FILE = empty
kept3, dem3 = sixcol.split_demoted(list(fails))
chk("rollback: with an empty retired.txt, SELFCHECK and PREVENTS warn again", sorted(c for c, _ in dem3) == ["NOT-RUN-CLAIM", "PREVENTS", "SELFCHECK"])
sixcol.RETIRED_FILE = os.path.join(HERE, "no-such-file.txt")
chk("missing retired.txt retires nothing", len(sixcol.split_demoted(list(fails))[1]) == 3)
print("RETIRED SELFTEST %d of %d" % (ok, ok + bad)); sys.exit(1 if bad else 0)
