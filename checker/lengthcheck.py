#!/usr/bin/env python3
"""lengthcheck.py (imc-reply-gate 0.3.5; Rob approved rows 1 and 2, 2026-10-23 18:29 PDT).

Two checks run by precheck.py on a draft, each returning (code, message) pairs like closingcheck.py:

  REPEAT-TEXT   a draft repeats text it already sent: the same next-steps table twice inside one draft, the same
                table as the last stamped draft, or a CORRECTION: or CHECKED: line identical to one in the last
                stamped draft. Override for a reply Rob asked to have resent: IMC_ALLOW_RESEND=1.
  ABOVE-TABLE-CAP   more than CAP words of prose above the table. Not counted: the gate's own structured lines
                (PROJECT OBJECTIVE, OBJECTIVE, CHECKED, SELF-CHECK, PRE-SEND REVIEW, STANDING ROWS, HANDOFFS,
                ROOT CAUSE), quote lines (">"), text inside double quotes or backticks, and code fences
                (CommonMark fences: a ````-wrapped quotation keeps its own ``` examples inside it, OI-0495).
                CAP is 150 (a proposal, not a measurement: readers' median above-table text was 250 to 300).
"""
import os
import re

CAP = 150
HEADER_RE = re.compile(r"^\|\s*#\s*\|\s*Issue\s*/\s*Risk\s*\|", re.I)
STRUCT_RE = re.compile(r"^(PROJECT OBJECTIVE|OBJECTIVE|CHECKED|SELF-CHECK|PRE-SEND REVIEW|STANDING ROWS|HANDOFFS|ROOT CAUSE)\b")
STAMPS = os.path.expanduser("~/.claude/imc-reply-gate-prechecked.tsv")


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def tables(text):
    """Every next-steps table in the text, as one normalized string per table (header row to last | row)."""
    out, cur = [], None
    for ln in text.split("\n"):
        if HEADER_RE.match(ln.strip()):
            cur = [ln]
        elif cur is not None and ln.strip().startswith("|"):
            cur.append(ln)
        elif cur is not None:
            out.append(_norm("\n".join(cur)))
            cur = None
    if cur is not None:
        out.append(_norm("\n".join(cur)))
    return out


def tagged_lines(text, tag):
    return [_norm(ln) for ln in text.split("\n") if ln.strip().startswith(tag)]


FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


def above_table_words(text):
    """Words of Claude's own prose above the table. OI-0495 (measured 2026-11-19): the fence walk
    was a BOOLEAN TOGGLE on any line starting with ```, and the HEADER_RE break was tested before
    it. What gets quoted here is Rob's own instruction field, which itself contains fenced
    examples and an example next-steps table, so quoting it broke the walk two ways: every inner
    ``` flipped the toggle, which counted whole runs of HIS words toward Claude's 150-word cap,
    and the example table header inside the fence hit the break and stopped the count dead.
    The walk now follows the CommonMark rule the quotation needs - a block opened with N
    backticks (or tildes) closes only on a line of N or more of the same character and nothing
    else - so a ````-wrapped quotation carries its own ``` examples, and the header break is
    read only outside a fence."""
    n, marker = 0, None
    for ln in text.split("\n"):
        s = ln.strip()
        m = FENCE_RE.match(s)
        if marker is not None:
            if m and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker) \
                    and not s[len(m.group(1)):].strip():
                marker = None
            continue
        if m:
            marker = m.group(1)
            continue
        if HEADER_RE.match(s):
            break
        if not s or s.startswith(">") or s.startswith("|") or STRUCT_RE.match(s) or s.startswith("CORRECTION:"):
            continue
        s = re.sub(r'"[^"]*"|`[^`]*`', " ", s)
        n += len(s.split())
    return n


def previous_draft(draft_path, stamps=STAMPS):
    """Text of the newest stamped draft that is not this draft, or None."""
    if not os.path.isfile(stamps):
        return None
    for ln in reversed(open(stamps, encoding="utf-8", errors="replace").read().splitlines()):
        parts = ln.split("\t")
        if len(parts) >= 3 and os.path.abspath(parts[2]) != os.path.abspath(draft_path) and os.path.isfile(parts[2]):
            return open(parts[2], encoding="utf-8", errors="replace").read()
    return None


UNCHANGED_RE = re.compile(r"^TABLE UNCHANGED since (?:the last reply|\S+.*)$", re.M)


def previous_table_draft(text, draft_path=None, stamps=STAMPS):
    """0.4.11 (OI-0807): the newest stamped draft that is not this reply. In the Stop hook there is
    no draft path, so previous_draft("") returned the TABLE UNCHANGED reply's own stamped draft, which has no table,
    and the Stop hook refused a line precheck had accepted (measured 2026-11-25, stamp ecf9f32c496c68b9)."""
    if not os.path.isfile(stamps):
        return None
    here = text.strip()
    for ln in reversed(open(stamps, encoding="utf-8", errors="replace").read().splitlines()):
        parts = ln.split("\t")
        if len(parts) < 3 or parts[0] == "FAIL" or not os.path.isfile(parts[2]):
            continue
        if draft_path and os.path.abspath(parts[2]) == os.path.abspath(draft_path):
            continue
        body = open(parts[2], encoding="utf-8", errors="replace").read()
        if body.strip() == here:
            continue
        return body  # the newest other stamped draft; the caller requires it to hold a table, as precheck does
    return None


def unchanged_line_ok(text, draft_path=None, prev=None):
    """0.3.6 (Rob 2026-10-23 18:36 PDT, row 1 'Agree'): a reply whose rows did not change carries the line
    'TABLE UNCHANGED since the last reply' instead of the table. Valid only when the draft holds no table and the
    last stamped draft held one. Returns True when the line is present and valid."""
    if not UNCHANGED_RE.search(text) or tables(text):
        return False
    if prev is None:
        prev = previous_table_draft(text, draft_path)
    return bool(prev and tables(prev))


def length_fails(text, draft_path, prev=None):
    fails = []
    t = tables(text)
    if len(t) > len(set(t)):
        fails.append(("REPEAT-TEXT", "the same next-steps table appears more than once in this draft. Send it once."))
    if os.environ.get("IMC_ALLOW_RESEND") != "1":
        if prev is None:
            prev = previous_draft(draft_path)
        if prev:
            pt = set(tables(prev))
            if t and any(x in pt for x in t):
                fails.append(("REPEAT-TEXT", "this draft's table is identical to the table in the last stamped draft. Change the rows that changed, or set IMC_ALLOW_RESEND=1 when Rob asked for the table again."))
            for tag in ("CORRECTION:", "CHECKED:"):
                old = set(tagged_lines(prev, tag))
                dup = [x for x in tagged_lines(text, tag) if x in old]
                if dup:
                    fails.append(("REPEAT-TEXT", "%d %s line(s) repeat the last stamped draft word for word, first: '%s'. Drop it or run the check again and report the new result." % (len(dup), tag, dup[0][:70])))
    w = above_table_words(text)
    if w > CAP:
        fails.append(("ABOVE-TABLE-CAP", "%d words of prose above the table, cap %d (structured lines, quotes and code are not counted). Cut %d." % (w, CAP, w - CAP)))
    return fails
