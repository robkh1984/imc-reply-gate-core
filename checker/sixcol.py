#!/usr/bin/env python3
"""sixcol.py - imc-reply-gate core serial 23 (0.4.21), O2 "6-column table" (Rob 2026-11-26).

Rob replaced the 7-column next-steps table and the 6-part closing block with ONE table:

    | ID | Issue/Action | Owner | Recommendation | Pros | Cons with Risks and Mitigations |

WHY A SHIM. About 60 checks in replycheck.py, gate.py and runbehind.py read table cells by position in the old
7-column layout (# | Issue / Risk | Action | Owner | Recommendation | Pros | Cons). Rewriting each one is 60 chances
to shift an index wrongly. to_internal() instead rewrites a 6-column table, line for line, into the 7-column shape the
checks already read, by copying the Issue/Action cell into both the Issue / Risk and the Action positions. Line
numbers do not move, so a check that reports "line N" still points at the line Rob sees. The text that is HASHED and
STAMPED is always the original; only the text the checks read goes through to_internal().

    python3 sixcol.py --selftest
"""
import re
import sys

NEW_HEADER = re.compile(
    r"^\|\s*ID\s*\|\s*Issue\s*/\s*Action\s*\|\s*Owner\s*\|\s*Recommendation\s*\|\s*Pros\s*\|"
    r"\s*Cons\s+with\s+Risks\s+and\s+Mitigations\s*\|\s*$", re.I)
OLD_HEADER = re.compile(
    r"^\|\s*#\s*\|\s*Issue\s*/\s*Risk\s*\|\s*Action\s*\|\s*Owner\s*\|\s*(?:Claude[’']s\s+)?Recommendation\s*\|"
    r"\s*Pros\s*\|\s*Cons\s*\|\s*$", re.I)
NEW_HEADER_TEXT = "| ID | Issue/Action | Owner | Recommendation | Pros | Cons with Risks and Mitigations |"
INTERNAL_HEADER = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |"
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def _split(line):
    s = line.strip()
    body = s[1:] if s.startswith("|") else s
    if body.endswith("|"):
        body = body[:-1]
    return body.split("|")


def has_new_table(text):
    return any(NEW_HEADER.match(ln.strip()) for ln in _unfenced(text))


def has_old_table(text):
    return any(OLD_HEADER.match(ln.strip()) for ln in _unfenced(text))


def _unfenced(text):
    fence = False
    for ln in text.split("\n"):
        if FENCE.match(ln):
            fence = not fence
            continue
        if not fence:
            yield ln


def to_internal(text):
    """Return text with every 6-column next-steps table rewritten into the 7-column internal shape.
    Text outside those tables, and every fenced block, is returned unchanged. Same number of lines."""
    lines = text.split("\n")
    out, fence, in_tbl = [], False, False
    for ln in lines:
        if FENCE.match(ln):
            fence = not fence
            in_tbl = False
            out.append(ln)
            continue
        if fence:
            out.append(ln)
            continue
        s = ln.strip()
        if NEW_HEADER.match(s):
            in_tbl = True
            out.append(INTERNAL_HEADER)
            continue
        if in_tbl and s.startswith("|"):
            cells = _split(s)
            if all(re.match(r"^\s*:?-{3,}:?\s*$", c) for c in cells if c.strip() or True) and cells:
                out.append("|" + "|".join(["---"] * 7) + "|")
                continue
            if len(cells) == 6:
                cells = cells[:2] + [cells[1]] + cells[2:]
            out.append("|" + "|".join(cells) + "|")
            continue
        in_tbl = False
        out.append(ln)
    return "\n".join(out)


# ---------- DEMOTED CLOSING-BLOCK CHECKS (O2 step 5) ----------
# Rob 2026-11-26: "turn every closing-block check into a warning that logs and does not block, for 7 days".
# checker/demoted.txt lists the codes, one per line: CODE<TAB>reason. Each hit is printed as WARN [DEMOTED:CODE]
# and appended to ~/.claude/imc-reply-gate-demoted.tsv, so the 7 days measure what each check would have blocked.
# After DEMOTE_UNTIL the codes stay warnings and one WARN [DEMOTION-EXPIRED] asks for the delete-or-restore ruling:
# re-arming a closing-block check by date would refuse the very format Rob ruled in.
import datetime as _dt
import os as _os

HERE = _os.path.dirname(_os.path.abspath(__file__))
DEMOTED_FILE = _os.path.join(HERE, "demoted.txt")
DEMOTE_UNTIL = "2026-12-03"
DEMOTE_LOG = _os.path.expanduser("~/.claude/imc-reply-gate-demoted.tsv")


def demoted_codes(path=None):
    out = {}
    try:
        for ln in open(path or DEMOTED_FILE, encoding="utf-8"):
            ln = ln.rstrip("\n")
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            code, _, why = ln.partition("\t")
            out[code.strip()] = why.strip()
    except OSError:
        pass
    return out


def _log_demoted(hits):
    if not hits:
        return
    try:
        _os.makedirs(_os.path.dirname(DEMOTE_LOG), exist_ok=True)
        ts = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
        sid = _os.environ.get("CLAUDE_CODE_SESSION_ID") or _os.environ.get("CLAUDE_SESSION_ID") or "-"
        with open(DEMOTE_LOG, "a", encoding="utf-8") as fh:
            for c, m in hits:
                fh.write("%s\t%s\t%s\t%s\n" % (ts, sid, c, m.replace("\t", " ").replace("\n", " ")[:300]))
    except OSError:
        pass


# ---------- RETIRED CLOSING-BLOCK CHECKS (O5 step 7, core serial 29) ----------
# Rob 2026-11-28 (O5 brief, step 7): "retire each closing-block warning that never caught a real error; keep any that
# did". checker/retired.txt lists the retired codes, CODE<TAB>evidence. A retired code is dropped from the fails
# silently: no FAIL, no WARN, no demoted.tsv line. Rollback: delete a line from retired.txt and the code warns again.
RETIRED_FILE = _os.path.join(HERE, "retired.txt")


def retired_codes(path=None):
    return set(demoted_codes(path or RETIRED_FILE))


def drop_retired(fails, path=None):
    """fails with every retired code removed (a new list)."""
    r = retired_codes(path)
    return [(c, m) for c, m in fails if c not in r]


def demote(fails, warns, path=None):
    """Move every demoted code from fails (a list of (code, msg)) into warns, in place, and log each one."""
    fails[:] = drop_retired(fails)
    codes = demoted_codes(path)
    hits = [(c, m) for c, m in fails if c in codes]
    if not hits:
        return []
    fails[:] = [(c, m) for c, m in fails if c not in codes]
    for c, m in hits:
        warns.append(("DEMOTED:" + c, m))
    if _dt.date.today().isoformat() > DEMOTE_UNTIL:
        warns.append(("DEMOTION-EXPIRED", "the 7-day warn-only window for the closing-block checks ended %s: "
                      "read %s and ask Rob to rule delete or restore for each code" % (DEMOTE_UNTIL, DEMOTE_LOG)))
    _log_demoted(hits)
    return hits


def split_demoted(fails, path=None):
    """For callers holding a plain list: (kept, demoted)."""
    codes = demoted_codes(path)
    fails = drop_retired(fails)
    return [(c, m) for c, m in fails if c not in codes], [(c, m) for c, m in fails if c in codes]


# ---------- REC-NO-EVIDENCE (O2 step 5) ----------
# Rob 2026-11-26: "The proof is the hook-written evidence.log: the O1 reviewer checks each Recommendation cell's
# claim against the log lines it cites, and fails any cell no log line supports." This is the mechanical half:
# every Recommendation cell must CITE lines ("evidence.log L12" or "evidence.log L12, L15"), and every cited line
# must exist in this session's evidence.log and verify (hook-written, chain intact). Whether a cited line SUPPORTS
# the claim is the reviewer's half (hooks/reviewer-rubric.txt, REC-NOT-SUPPORTED). The word TESTED counts for
# nothing here. A recommendation that cannot be tested is a Rob decision row: its Recommendation cell opens
# "DECISION:" and says what is unknown and why it cannot be measured.
CITE_RE = re.compile(r"evidence\.log\s+((?:L\d+(?:\s*(?:,|and|&|-|to)\s*)?)+)", re.I)
LNUM_RE = re.compile(r"L(\d+)")
NOOP_RE = re.compile(r"^\s*\**\s*(none|nothing\b|no change|n/?a|-|—)\s*\**\s*\.?\s*$", re.I)
DECISION_RE = re.compile(r"^\s*\**\s*DECISION\s*:", re.I)


def evidence_log_path():
    p = _os.environ.get("IMC_EVIDENCE_LOG")
    if p:
        return p
    sid = _os.environ.get("CLAUDE_CODE_SESSION_ID") or _os.environ.get("CLAUDE_SESSION_ID") or ""
    if not sid:
        return None
    d = _os.environ.get("IMC_EVIDENCE_DIR") or _os.path.expanduser("~/.claude/imc-evidence")
    return _os.path.join(d, re.sub(r"[^A-Za-z0-9_.-]", "_", sid), "evidence.log")


def _ledger():
    import importlib.util
    lp = _os.path.join(_os.path.dirname(HERE), "hooks", "ledger.py")
    if not _os.path.isfile(lp):  # the portable checker folder is flat: ledger.py sits beside this file
        lp = _os.path.join(HERE, "ledger.py")
    spec = importlib.util.spec_from_file_location("imc_ledger_sixcol", lp)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def new_table_rows(text):
    """[(row_id, cells)] for every numbered row of every 6-column table outside fences."""
    out, in_tbl = [], False
    for ln in _unfenced(text):
        s = ln.strip()
        if NEW_HEADER.match(s):
            in_tbl = True
            continue
        if in_tbl and s.startswith("|"):
            cells = [c.strip() for c in _split(s)]
            if cells and re.match(r"^\d+$", cells[0]):
                out.append((cells[0], cells))
            continue
        in_tbl = False
    return out


def _expand(spec):
    nums = []
    for a, b in re.findall(r"L(\d+)(?:\s*(?:-|to)\s*L?(\d+))?", spec):
        a = int(a)
        nums.extend(range(a, int(b) + 1) if b and int(b) >= a and int(b) - a < 200 else [a])
    return nums


def evidence_fails(text, log=None):
    rows = new_table_rows(text)
    if not rows:
        return []
    out, cites = [], {}
    for rid, c in rows:
        if len(c) != 6:
            out.append(("TABLE-SHAPE", "row %s has %d cells; the table is '%s' (6 cells)" % (rid, len(c), NEW_HEADER_TEXT)))
            continue
        owner, rec = c[2], c[3]
        if NOOP_RE.match(rec):
            continue
        if DECISION_RE.match(rec):
            if owner.strip().lower() != "rob":
                out.append(("DECISION-ROW", "row %s opens DECISION: but its Owner is %r; an untestable recommendation "
                            "becomes a decision row owned by Rob" % (rid, owner)))
            if not re.search(r"\bunknown\b", rec, re.I) or not re.search(r"\b(because|since|as)\b", rec, re.I):
                out.append(("DECISION-ROW", "row %s is a decision row but does not say what is unknown and why it "
                            "cannot be measured (Rob 2026-11-26)" % rid))
            continue
        spec = " ".join(m.group(1) for m in CITE_RE.finditer(rec))
        nums = _expand(spec)
        if not nums:
            out.append(("REC-NO-EVIDENCE", "row %s's Recommendation cites no evidence.log line. Rob 2026-11-26: every "
                        "recommendation is measured and tested before he sees it, and the proof is the hook-written "
                        "evidence.log, not a label. Cite the lines ('evidence.log L12, L15'), or make it a DECISION: row "
                        "for Rob saying what is unknown and why it cannot be measured" % rid))
            continue
        cites[rid] = nums
    if not cites:
        return out
    lp = log or evidence_log_path()
    if not lp or not _os.path.isfile(lp):
        out.append(("REC-NO-EVIDENCE", "rows %s cite evidence.log lines but this session has no evidence.log (%s). The "
                    "ledger hook writes it; without it no cited line can be confirmed, so the rows do not pass"
                    % (", ".join(cites), lp or "no session id")))
        return out
    try:
        led = _ledger()
        n, bad = led.verify(lp)
        seqs = set()
        badseq = set()
        badlines = {i for i, _r in bad}
        for i, line in enumerate(open(lp, encoding="utf-8", errors="replace").read().split("\n"), 1):
            if not line.strip():
                continue
            f0 = line.split("\t", 1)[0]
            if f0.isdigit():
                (badseq if i in badlines else seqs).add(int(f0))
    except Exception as e:
        out.append(("REC-NO-EVIDENCE", "evidence.log at %s could not be verified (%s), so no cited line counts" % (lp, str(e)[:120])))
        return out
    for rid, nums in cites.items():
        missing = [x for x in nums if x not in seqs and x not in badseq]
        forged = [x for x in nums if x in badseq]
        if forged:
            out.append(("REC-NO-EVIDENCE", "row %s cites evidence.log line(s) %s that ledger.py verify marks FORGED or "
                        "CHAIN BREAK; a line the hook did not write supports nothing" % (rid, ", ".join("L%d" % x for x in forged))))
        if missing:
            out.append(("REC-NO-EVIDENCE", "row %s cites evidence.log line(s) %s that do not exist (the log holds %d lines)"
                        % (rid, ", ".join("L%d" % x for x in missing), n)))
    return out


def table_last_fails(text):
    """TABLE-NOT-LAST (O2, Rob 2026-11-26): the table is always the last thing in a reply; nothing follows it."""
    lines = text.split("\n")
    fence, last_tbl_end, seen = False, None, False
    in_tbl = False
    for i, ln in enumerate(lines):
        if FENCE.match(ln):
            fence = not fence
            in_tbl = False
            continue
        if fence:
            continue
        s = ln.strip()
        if NEW_HEADER.match(s):
            in_tbl, seen = True, True
            last_tbl_end = i
            continue
        if in_tbl and s.startswith("|"):
            last_tbl_end = i
            continue
        in_tbl = False
    if not seen:
        return []
    tail = [l for l in lines[last_tbl_end + 1:] if l.strip()]
    if tail:
        return [("TABLE-NOT-LAST", "%d line(s) follow the table, starting %r. Rob 2026-11-26: the table is the last thing in "
                 "the reply and nothing follows it; move this text above the table" % (len(tail), tail[0].strip()[:80]))]
    return []


def _selftest():
    ok = fail = 0

    def t(name, got, want):
        nonlocal ok, fail
        if got == want:
            ok += 1
            print("ok   " + name)
        else:
            fail += 1
            print("FAIL " + name + ": got %r want %r" % (got, want))

    src = ("Lead line.\n\nOBJECTIVE 1 - x [IN PROGRESS]\n\n" + NEW_HEADER_TEXT + "\n|---|---|---|---|---|---|\n"
           "| 1 | Gate refuses X. Fix the parser. | Claude | RECOMMEND: ship it; evidence.log L4 shows 31 of 31. | p | c |\n")
    got = to_internal(src)
    t("same line count", len(got.split("\n")), len(src.split("\n")))
    t("header becomes internal", INTERNAL_HEADER in got, True)
    row = [l for l in got.split("\n") if l.startswith("| 1 |") or l.startswith("| 1|") or l.startswith("|1")]
    t("row gains a 7th cell", len(_split(row[0])) if row else 0, 7)
    t("issue/action copied into action position", _split(row[0])[1] == _split(row[0])[2] if row else False, True)
    t("owner stays owner", _split(row[0])[3].strip() if row else "", "Claude")
    fenced = "```\n" + NEW_HEADER_TEXT + "\n| 1 | a | Rob | b | c | d |\n```\n"
    t("fenced table untouched", to_internal(fenced), fenced)
    t("has_new_table", has_new_table(src), True)
    t("has_new_table false in fence", has_new_table(fenced), False)
    old = INTERNAL_HEADER + "\n|---|---|---|---|---|---|---|\n| 1 | a | b | Rob | c | d | e |\n"
    t("old table untouched", to_internal(old), old)
    t("has_old_table", has_old_table(old), True)
    t("prose with pipes outside a table untouched", to_internal("a | b | c\n"), "a | b | c\n")
    print("sixcol selftest pass=%d fail=%d" % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        sys.exit(_selftest())
    sys.stdout.write(to_internal(sys.stdin.read()))
