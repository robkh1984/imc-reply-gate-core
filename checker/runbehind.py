#!/usr/bin/env python3
"""runbehind.py - a recommendation, a "measured" label and a high confidence each need a run behind them.

Built 2026-10-29 for the three rows Rob approved at 14:09 PDT:
  RECO-RUN       every table row's Recommendation cell carries TESTED or UNTESTED. TESTED needs a CHECKED
                 line in the same reply that has a time and a result arrow or exit code. UNTESTED needs a
                 BLOCKED marker in the cell or in the reply.
  MEASURED-LABEL a ROOT CAUSE / CAUSE / SELF-CHECK line that says "measured" needs a CHECKED line in the same
                 reply that names a command, and a CHECKED line that names no command is refused.
  CONF-TESTED    a SELF-CHECK confidence above 5/10 for a row needs that row's Recommendation to say TESTED
                 (not UNTESTED).

What it does NOT prove: that the cited run happened. It proves the reply cites one, in a form a reader can
check. Entry point: check(text, fail, warn). Self-test: python3 runbehind.py --selftest.
"""
import re
import sys

_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.+)$", re.M)
_CHECKED = re.compile(r"^\s*(?:[-*>]\s*)?(?:\*\*)?CHECKED\s*(?::|—|–|-)(.*)$", re.I | re.M)
_TESTED = re.compile(r"(?<![A-Za-z])TESTED\b")
_UNTESTED = re.compile(r"\bUNTESTED\b")
_NOTRUN = re.compile(r"(?i)\b(refus\w*|denied|error\w*|failed|failure|timed out|time-?out|unavailable|not available|no such tool|no tool|credential\w*|physical|trigger|needs? (?:your |a |an )?approval|approval of)\b")
_MEASURED = re.compile(r"(?<![A-Za-z])(?<!not )(?<!not yet )measured\b", re.I)
# 0.3.65: an unquoted shell command with a path argument also counts (Daily artifact count check form, 2026-11-18)
_COMMAND = re.compile(r"`[^`]+`|\b(connector|lookup|message read|file read|read in full)\b|\b(python3|bash|zsh|grep|ls|cat|sed|find|wc)\s+[~/.][\w~/.-]+", re.I)
_TIME = re.compile(r"\b\d{1,2}:\d{2}\b")
_RESULT = re.compile(r"->|\bexit\s*\d|→")
# *** RECO-STATED. ROB 2026-11-22 08:26 AM PST, after a Recommendation cell he was sent held
# only evidence: "THIS IS NOT A RECOMMENDATION. Identify the root cause". ***
# The cause was that every check on this column enforced the WRAPPER and none enforced the
# CONTENT: RECO-RUN wants TESTED or UNTESTED plus a cited run, TEST-FIELD wants Test and Fails-if,
# CONF-TESTED wants the marker to match the confidence. A cell can satisfy all three while
# recommending nothing, and on 2026-11-22 one did. Measured that morning over the replies in
# ~/Claude/_offtree/task-replies: 1,088 of 1,126 Recommendation cells state no recommendation at
# all, so this was never a one-off - the column has carried evidence instead of advice for its
# whole life, and the gate could not see it because nothing looked.
# THE REQUIRED FORM IS A MARKER, NOT A PHRASE LIST. A list of recommending verbs is satisfiable by
# accident and misses honest wordings; "RECOMMEND:" cannot be satisfied by evidence prose, and it
# tells the writer the shape instead of leaving them to guess it, which is how TESTED already works.
# *** THE FIRST VERSION OF THIS CHECK WAS ITSELF A WRAPPER, AND A REVIEWER DEFEATED IT IN ONE
# LINE: "RECOMMEND: TESTED at 8:30 AM PST, exit 0, 12 rows" clears a marker and a 20-character
# floor on pure evidence text. A rule that only counts characters after a token enforces the
# token, which is the very defect it was written to remove. So the clause is tested three ways:
# it must exist, it must NOT read like a CHECKED line, and it must tell the reader what to do.
# EVIDENCE TOKENS ARE THE GATE'S OWN: a clock time, an exit code or arrow, or a backticked
# command are what this file already uses to recognise a cited run, so a clause containing them
# is a run, not advice. The directive list is not the only test - it sits behind the evidence
# test - which is why a verb list is safe here and was not safe alone.
# THE CLAUSE ENDS AT THE EVIDENCE, AND ITS LENGTH IS CHECKED SEPARATELY. The first boundary put
# the 20-character floor inside the lookahead, so "RECOMMEND: upload it. TESTED at 8:30" slid past
# the TESTED boundary and swallowed the evidence, failing a legitimate short recommendation for
# the wrong reason. A reviewer found that too. Length, evidence and directive are now three
# separate verdicts on one clause, each with its own message.
_RECOMMEND = re.compile(r"\bRECOMMEND(?:ATION)?\s*:\s*(.*?)(?=(?:\bTESTED\b|\bUNTESTED\b|$))", re.I | re.S)
_EVIDENCEY = re.compile(r"\b\d{1,2}:\d{2}\b|->|→|\bexit\s*\d|`[^`]+`")
_DIRECTIVE = re.compile(r"\b(install|upload|keep|retire|demote|delete|remove|add|run|wait|hold|"
                        r"choose|pick|take|switch|accept|decline|approve|reject|leave|revert|"
                        r"restore|raise|lower|stop|start|merge|split|rename|move|file|close|"
                        r"do|don'?t|should|yes|no|go with|prefer|neither|either)\b", re.I)
_NO_RECOMMEND = re.compile(r"\bNO RECOMMENDATION\s*:\s*(\S.{19,})", re.I | re.S)
_REC_NOOP = re.compile(r"^\s*\**\s*(none|nothing\b|no change|not until|n/?a|-|\u2014)\s*\**\s*$", re.I)

_CONF = re.compile(r"(\d{1,2})\s*/\s*10\s+in\s+(?:the\s+)?(rows?\s+\d+(?:\s*(?:,|and|to)\s*\d+(?!\d|\s*/))*)", re.I)
_SC_LINE = re.compile(r"^\s*\*{0,2}SELF-CHECK\*{0,2}\s*:(.*)$", re.M | re.I)


def _header(text):
    m = re.search(r"^\|\s*#\s*\|(.+)\|\s*$", text, re.M)
    if not m:
        return None
    names = [c.strip().lower() for c in m.group(1).split("|")]
    while names and names[-1] == "":
        names.pop()
    for i, n in enumerate(names):
        if n.startswith("recommendation"):
            return i
    return None


def _rec_cells(text):
    """{row number: Recommendation cell text}."""
    idx = _header(text)
    out = {}
    if idx is None:
        return out
    for m in _ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if len(cells) > idx:
            out[int(m.group(1))] = cells[idx]
    return out


def _expand(rows):
    nums = [int(n) for n in re.findall(r"\d+", rows)]
    if re.search(r"\d\s*to\s*\d", rows) and len(nums) == 2:
        return list(range(nums[0], nums[1] + 1))
    return nums


def check(text, fail, warn):
    recs = _rec_cells(text)
    checked = [m.group(1) for m in _CHECKED.finditer(text)]
    cited = [c for c in checked if _TIME.search(c) and _RESULT.search(c)]
    has_blocked = bool(re.search(r"\bBLOCKED\s*:", text))

    for n, cell in sorted(recs.items()):
        # 0.3.85: a declared no-op and an explicit NO RECOMMENDATION are not untested work, and
        # RECO-RUN used to refuse both for carrying neither marker - so the honest way out of
        # RECO-STATED was closed by a sibling check. A reviewer found that before Rob did.
        if _REC_NOOP.match(cell) or _NO_RECOMMEND.search(cell):
            continue
        if _UNTESTED.search(cell):
            if not re.search(r"\bBLOCKED\s*:", cell) and not has_blocked:
                fail("RECO-RUN", "row %d says UNTESTED but names no BLOCKED: reason in the cell or the reply. "
                     "Rob 2026-10-29 14:09 PDT: an untested recommendation names the gap it could not close." % n)
            elif not _NOTRUN.search(cell):
                # 0.3.28 RECO-UNRUN (Rob 2026-10-29 21:19 PDT, agreed row 7): "waits on Rob" explains why the
                # DECISION waits, not why the test was not run. The cell itself must name a failed call, a
                # refusal, a missing credential, trigger or approval, or an unavailable tool.
                fail("RECO-UNRUN", "row %d says UNTESTED but its cell names no failed call, refusal, credential, "
                     "approval or unavailable tool as the reason the test was not run. Run the test, then say "
                     "TESTED. Rob 2026-10-29: measure, test and validate before presenting." % n)
        elif _TESTED.search(cell):
            if not cited:
                fail("RECO-RUN", "row %d says TESTED but the reply has no CHECKED line with a time and a result "
                     "(an arrow or an exit code). Rob 2026-10-29 14:09 PDT: TESTED needs the run in the same reply." % n)
        else:
            fail("RECO-RUN", "row %d's Recommendation carries neither TESTED nor UNTESTED. Rob 2026-10-29 14:09 PDT: "
                 "every recommendation says whether a run stands behind it." % n)

    for n, cell in sorted(recs.items()):
        if _REC_NOOP.match(cell) or _NO_RECOMMEND.search(cell):
            continue
        m = _RECOMMEND.search(cell)
        if not m:
            fail("RECO-STATED", "row %d's Recommendation cell carries evidence but states no recommendation. "
                 "Rob 2026-11-22 08:26 AM PST, on a cell that held only test results: \"THIS IS NOT A "
                 "RECOMMENDATION\". Add 'RECOMMEND: <what you advise and why, 20+ characters>' to the cell, "
                 "or 'NO RECOMMENDATION: <why you are not making one>'. Cell begins: '%s'"
                 % (n, cell.strip()[:60]))
            continue
        clause = m.group(1).strip()
        if len(clause) < 20:
            fail("RECO-STATED", "row %d's RECOMMEND clause is %d characters - too thin to be advice. "
                 "Say what to do and why, in at least 20 characters. Clause: '%s'" % (n, len(clause), clause[:40]))
            continue
        if _EVIDENCEY.search(clause):
            fail("RECO-STATED", "row %d's RECOMMEND clause reads like a CHECKED line - it carries %s. "
                 "Evidence belongs in the TESTED part of the cell; the RECOMMEND part says what to do. "
                 "Clause: '%s'" % (n, "a clock time" if re.search(r"\b\d{1,2}:\d{2}\b", clause)
                                   else "an exit code or result arrow" if re.search(r"->|→|\bexit\s*\d", clause)
                                   else "a command in backticks", clause.strip()[:60]))
        elif not _DIRECTIVE.search(clause):
            fail("RECO-STATED", "row %d's RECOMMEND clause names no action to take. A recommendation says "
                 "what to do - install, keep, retire, wait, choose one over the other, or do nothing. "
                 "Clause: '%s'" % (n, clause.strip()[:60]))

    label_lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if re.match(r"(ROOT CAUSE|SELF-CHECK)\s*:", s, re.I) or (s.startswith("|") and "CAUSE:" in s):
            if _MEASURED.search(s):
                label_lines.append(s)
    if label_lines:
        named = [c for c in checked if _COMMAND.search(c)]
        if not named:
            fail("MEASURED-LABEL", "a ROOT CAUSE, CAUSE or SELF-CHECK line says \"measured\" and no CHECKED line names a "
                 "command or lookup. Rob 2026-10-29 14:09 PDT: the word measured means a run happened in this reply.")
    for c in checked:
        if not _COMMAND.search(c):
            fail("MEASURED-LABEL", "a CHECKED line names no command, lookup or read: '%s'. A CHECKED line without a "
                 "command cannot be re-run." % c.strip()[:70])

    m = _SC_LINE.search(text)
    if m and recs:
        body = m.group(1)
        pairs = [(int(a), _expand(b)) for a, b in _CONF.findall(body)]
        for conf, rows in pairs:
            if conf <= 5:
                continue
            for r in rows:
                cell = recs.get(r)
                if cell is not None and not (_TESTED.search(cell) and not _UNTESTED.search(cell)):
                    fail("CONF-TESTED", "SELF-CHECK rates row %d at %d/10 but its Recommendation is not marked TESTED. "
                         "Rob 2026-10-29 14:09 PDT: above 5/10 needs a run behind the row." % (r, conf))
        if not pairs:
            g = re.search(r"confidence\s*:\s*(\d{1,2})\s*/\s*10", body, re.I)
            if g and int(g.group(1)) > 5:
                bad = [r for r, c in recs.items() if not (_TESTED.search(c) and not _UNTESTED.search(c))]
                if bad:
                    fail("CONF-TESTED", "SELF-CHECK rates the whole table %s/10 but rows %s are not marked TESTED."
                         % (g.group(1), ", ".join(str(b) for b in bad)))


def _selftest():
    ok = [0, 0]

    def run(text):
        f, w = [], []
        check(text, lambda c, m: f.append(c), lambda c, m: w.append(c))
        return f

    def ck(name, got, want):
        ok[0 if got == want else 1] += 1
        print(("PASS  " if got == want else "FAIL  ") + name + ("" if got == want else "  got %r want %r" % (got, want)))

    hdr = "| # | Issue | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
    good_chk = "CHECKED: 2026-10-29 13:00 PDT, `ls -l a` -> exit 0.\n"
    row_bare = "| 1 | i | a | Rob | TESTED on a copy. | p | c |\n"   # no RECOMMEND clause: RECO-STATED fodder
    row_t = "| 1 | i | a | Rob | TESTED on a copy. RECOMMEND: install it, the copy behaved. | p | c |\n"
    row_u = ("| 2 | i | a | Rob | UNTESTED: the call failed with a refusal. RECOMMEND: wait for the "
             "credential before installing. BLOCKED: row 2 (Rob). | p | c |\n")
    row_n = "| 3 | i | a | Rob | Please approve. | p | c |\n"
    rec = " RECOMMEND: install the candidate, because its own run prints the degraded verdict."
    row_tr = "| 1 | i | a | Rob | TESTED on a copy." + rec + " | p | c |\n"
    ck("POSITIVE RECO-STATED: an evidence-only Recommendation cell fires",
       "RECO-STATED" in run(good_chk + hdr + row_bare), True)
    ck("NEGATIVE RECO-STATED: a cell with a RECOMMEND clause is silent",
       "RECO-STATED" in run(good_chk + hdr + row_tr), False)
    ck("NEGATIVE RECO-STATED: an explicit NO RECOMMENDATION with a reason is silent",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | TESTED on a copy. NO RECOMMENDATION: the "
                            "two options cost the same and the choice is yours. | p | c |\n"), False)
    # *** THE DEFEAT A REVIEWER FOUND, 2026-11-22, now a control in both directions. ***
    ck("NEGATIVE RECO-STATED: short advice followed by its evidence is not read as evidence",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | RECOMMEND: upload it before the next "
                            "piece of work. TESTED at 8:30 AM PST -> exit 0. | p | c |\n"), False)
    ck("POSITIVE RECO-STATED: a clause under the floor fires",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | RECOMMEND: do it. TESTED at 8:30 AM "
                            "PST -> exit 0. | p | c |\n"), True)
    ck("POSITIVE RECO-STATED: a RECOMMEND clause that is just evidence fires",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | RECOMMEND: TESTED at 8:30 AM PST, "
                            "exit 0, 12 rows | p | c |\n"), True)
    ck("POSITIVE RECO-STATED: a RECOMMEND clause with a backticked command fires",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | TESTED on a copy. RECOMMEND: run "
                            "`python3 bin/x.py` and read what it prints | p | c |\n"), True)
    ck("POSITIVE RECO-STATED: a RECOMMEND clause naming no action fires",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | TESTED on a copy. RECOMMEND: the "
                            "situation is unfortunate and the numbers are what they are | p | c |\n"), True)
    ck("NEGATIVE RECO-STATED: advice with a directive and no evidence token is silent",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | TESTED on a copy. RECOMMEND: keep the "
                            "narrow version and retire the broad one | p | c |\n"), False)
    ck("NEGATIVE RECO-RUN: a NO RECOMMENDATION cell is not treated as untested work",
       "RECO-RUN" in run(good_chk + hdr + "| 1 | i | a | Rob | NO RECOMMENDATION: the two options cost "
                         "the same and the choice is yours. | p | c |\n"), False)
    ck("NEGATIVE RECO-RUN: a declared no-op cell is exempt",
       "RECO-RUN" in run(good_chk + hdr + "| 1 | i | a | Rob | No change | p | c |\n"), False)
    ck("POSITIVE RECO-STATED: a bare RECOMMEND with nothing after it fires",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | TESTED on a copy. RECOMMEND: yes. | p | c |\n"), True)
    ck("NEGATIVE RECO-STATED: a None cell is exempt",
       "RECO-STATED" in run(good_chk + hdr + "| 1 | i | a | Rob | None | p | c |\n"), False)
    ck("POSITIVE: no marker fires RECO-RUN", "RECO-RUN" in run(good_chk + hdr + row_n), True)
    ck("NEGATIVE: TESTED with a CHECKED line is silent", run(good_chk + hdr + row_t), [])
    ck("NEGATIVE: UNTESTED with BLOCKED is silent", run(good_chk + hdr + row_u), [])
    ck("POSITIVE: TESTED with no CHECKED line fires", "RECO-RUN" in run(hdr + row_t), True)
    row_w = "| 4 | i | a | Rob | UNTESTED: I recommend A. BLOCKED: row 4 waits on Rob (see its Action). | p | c |\n"
    ck("POSITIVE 0.3.28: UNTESTED whose only BLOCKED is waits-on-Rob fires RECO-UNRUN",
       "RECO-UNRUN" in run(good_chk + hdr + row_w), True)
    ck("NEGATIVE 0.3.28: UNTESTED naming a refusal is silent", "RECO-UNRUN" in run(good_chk + hdr + row_u), False)
    ck("NEGATIVE 0.3.28: TESTED never fires RECO-UNRUN", "RECO-UNRUN" in run(good_chk + hdr + row_t), False)
    ck("POSITIVE: UNTESTED with no BLOCKED fires",
       "RECO-RUN" in run(good_chk + hdr + "| 2 | i | a | Rob | UNTESTED: gap. | p | c |\n"), True)
    ck("POSITIVE: measured with no CHECKED command fires MEASURED-LABEL",
       "MEASURED-LABEL" in run("ROOT CAUSE: measured: it broke.\n" + hdr + row_t), True)
    ck("NEGATIVE: measured with a backtick command is silent",
       "MEASURED-LABEL" in run("ROOT CAUSE: measured: it broke.\n" + good_chk + hdr + row_t), False)
    ck("NEGATIVE: loosely worded CHECKED (connector lookup) is accepted",
       "MEASURED-LABEL" in run("ROOT CAUSE: measured: x.\nCHECKED: 2026-10-29 13:05 PDT, the Drive connector's file lookup -> not found.\n" + hdr + row_t), False)
    ck("POSITIVE: CHECKED with no command fires",
       "MEASURED-LABEL" in run("CHECKED: 2026-10-29 13:00 PDT, all good -> yes.\n" + hdr + row_t), True)
    ck("NEGATIVE: unmeasured/not measured does not trigger the label rule",
       "MEASURED-LABEL" in run("ROOT CAUSE: inferred, not measured.\n" + good_chk + hdr + row_t), False)
    sc = "SELF-CHECK: thorough: no - x; confidence: 7/10 in row 2, 4/10 in row 1, drops to 3 if y. BLOCKED: row 2 (Rob).\n"
    ck("POSITIVE: 7/10 on an UNTESTED row fires CONF-TESTED", "CONF-TESTED" in run(sc + good_chk + hdr + row_t + row_u), True)
    sc2 = "SELF-CHECK: thorough: yes - x; confidence: 7/10 in row 1, 4/10 in row 2, drops to 3 if y.\n"
    ck("NEGATIVE: 7/10 on a TESTED row is silent", "CONF-TESTED" in run(sc2 + good_chk + hdr + row_t + row_u), False)
    sc3 = "SELF-CHECK: thorough: yes - x; confidence: 6/10 in rows 1 to 2, drops to 3 if y.\n"
    ck("POSITIVE: a range of rows is expanded", "CONF-TESTED" in run(sc3 + good_chk + hdr + row_t + row_u), True)
    sc4 = "SELF-CHECK: thorough: yes - x; confidence: 5/10 in rows 1 and 2, drops to 3 if y. BLOCKED: row 2 (Rob).\n"
    ck("NEGATIVE: 5/10 never fires", "CONF-TESTED" in run(sc4 + good_chk + hdr + row_t + row_u), False)
    sc5 = "SELF-CHECK: thorough: yes - x; confidence: 5/10 in rows 1 to 2, 7/10 in row 3, drops to 3 if y. BLOCKED: row 2 (Rob).\n"
    ck("POSITIVE: a later clause after a comma is still read",
       "CONF-TESTED" in run(sc5 + good_chk + hdr + row_t + row_u + row_n), True)
    print("\n%d passed, %d failed" % (ok[0], ok[1]))
    return 1 if ok[1] else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.exit(_selftest())
    print(__doc__)
