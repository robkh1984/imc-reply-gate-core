#!/usr/bin/env python3
"""replycheck - mechanical pre-send linter for Claude replies.

Reads a reply (file arg or stdin), prints findings, exits 1 on any FAIL.
Every check is countable. No check requires judgment.

Usage:  python3 replycheck.py reply.md
        pbpaste | python3 replycheck.py
"""
import os, datetime
from urllib.parse import unquote
import re
import pathlib
import sys

# Accepted ways of ESTABLISHING a title, all of which mean it was read from the target.
# Adding a method here is legitimate; typing a method you did not use is the thing the
# check exists to catch, and no list can stop that - only the habit can.
TITLE_FETCH_METHODS = ("drive-api", "artifact-read", "browser-title", "http-title")


FAILS = []
WARNS = []
INFO = []


def fail(code, msg):
    FAILS.append((code, msg))


def warn(code, msg):
    WARNS.append((code, msg))


def info(msg):
    INFO.append(msg)


# ---------- 0. CLAUDE-OWNED TEXT (OI-0495, measured 2026-11-19, session 1056270b) ----------
# 65 functions in this file raise a fail code and 5 of them blanked a fence before reading the
# draft. The other 60 read a fenced QUOTATION as if Claude had written it, so draft17 of
# 2026-11-19 - which carried Rob's own 17,087-byte global instructions field inside a fence -
# was refused for AGREEMENT, DEFERRED-WORK, ABSENCE-CLAIM and 24 RATING-CLOSABLE matches, every
# one of them Rob's own wording. A fenced block is not Claude's voice, claim or promise.
# MASKING IS THE DEFAULT, applied by the wrapper installed just above main(), so a check added
# later is masked without anyone remembering to do it. Only the names in RAW_CHECKS read the
# literal draft, and every one of those REQUIRES something to be PRESENT (a link, a quote, a
# sha, a CHECKED line, a table cell) or judges the fences themselves: masking a requirement
# check could INVENT a failure, while masking a prohibition check can only drop a finding on
# quoted text. That asymmetry, not a hand-kept list of content checks, is why the default is safe.
FENCE_LINE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"(?<!`)(`{1,3})(?!`)((?:(?!\1)[^\n])+)\1(?!`)")


def _blank_run(s):
    """s with every character replaced by a space and every newline kept, so a position or line
    number a check reports still points at the same place in the draft Rob will read."""
    return "".join("\n" if ch == "\n" else " " for ch in s)


def fenced_blanked(text):
    """Every fenced block blanked. CommonMark fence rules, because what gets quoted is usually a
    document that itself contains fences: a block opened with N backticks closes only on a line
    of N or more of the same character with nothing else on it, so a ````-wrapped quotation
    safely carries ``` examples inside it. An unclosed fence runs to the end of the text."""
    out, marker = [], None
    for ln in text.split("\n"):
        m = FENCE_LINE_RE.match(ln)
        if marker is None:
            if m:
                marker = m.group(1)
                out.append(_blank_run(ln))
            else:
                out.append(ln)
            continue
        out.append(_blank_run(ln))
        if (m and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker)
                and not ln.strip()[len(m.group(1)):].strip()):
            marker = None
    return "\n".join(out)


def inline_blanked(text):
    """Inline `code` spans blanked. Applied only to PROSE_CHECKS, which read prose for banned
    wording. An evidence check must NOT get this: Rob's own form writes the command it asks for
    inside backticks, so blanking them would delete the evidence the check exists to require."""
    return INLINE_CODE_RE.sub(lambda m: _blank_run(m.group(0)), text)


def owned_text(text):
    """The draft as CLAUDE's own words: fenced quotations blanked."""
    return fenced_blanked(text)


def owned_prose(text):
    """The draft as Claude's own PROSE: fenced quotations and inline code spans blanked."""
    return inline_blanked(fenced_blanked(text))


_RAW_DRAFT = {"text": None}


def raw_text(masked):
    """The literal draft, for the half of a check that EXCUSES a finding. R161 already held this
    rule for RATING-CLOSABLE: blanking the text a check reads to excuse itself turns a quotation
    into a NEW failure, so evidence - a CHECKED line, a quoted blocker, inline evidence - is
    read unmasked while the CLAIM is read masked. The wrapper sets this for the call it makes."""
    return _RAW_DRAFT["text"] if _RAW_DRAFT["text"] is not None else masked


def sentences(text):
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    parts = re.split(r"(?<=[.!?])\s+|\n", body)
    return [p.strip() for p in parts if p.strip()]


# ---------- 1. CLAIM LEDGER (the denominator) ----------
SYSTEM_NOUN = (
    r"(?:file|files|field|fields|tool|tools|connector|connectors|API|api|sheet|sheets|row|rows|"
    r"tab|tabs|script|scripts|task|tasks|project|projects|instruction|instructions|skill|skills|"
    r"folder|doc|docs|endpoint|token|column|columns|session|sessions|backup|trigger|prompt|"
    r"memory|repo|branch|log|logs|record|records|artifact|artifacts|page|browser|drive|index)"
)
# *** WIDENED 2026-08-27 ON ROB'S RULING. THE FLOOR MOVED BECAUSE HE MOVED IT. ***
# The 21 original verbs are copulas and possession. They cannot see a system DOING
# something - firing, refusing, reporting, blocking - which is most of what this project
# asserts. MEASURED against fixtures/CLAIM-FIXTURE.tsv, 443 hand-labelled sentences:
#   before  precision 86.6%  recall 22.6%   (58 tp, 9 fp, 199 fn)
#   after   precision 85.6%  recall 30.0%   (77 tp, 13 fp, 180 fn)
# 19 real claims gained, 4 false alarms added, all four sentences about my own process.
# I SET THE 86.6% FLOOR BEFORE SCORING AND THIS BREACHES IT. Rob took the trade; moving
# my own floor after seeing the result is the defect this project is named for.
# THE NEW FLOOR IS 85.6% AND THE SAME RULE APPLIES TO IT.
CLAIM_VERB = r"(?:is|are|was|were|has|have|had|can|cannot|can't|does|do|doesn't|don't|will|won't|returns?|contains?|supports?|lacks?|reaches?|receives?|fires?|fired|ran|runs?|report(?:s|ed)?|refus(?:e|es|ed)|den(?:y|ies|ied)|block(?:s|ed)?|match(?:es|ed)?|score[ds]?|wrote|writes?|found|finds?|produced?|exists?|carr(?:y|ies|ied)|name[ds]?|stays?|stayed|moved?|shows?)"
CLAIM_RE = re.compile(SYSTEM_NOUN + r"\b[^.]{0,60}?\b" + CLAIM_VERB + r"\b")
# *** THE SEPARATOR WAS A COLON ONLY, AND THAT MADE THE GATE PARTLY BLIND ALL SESSION. ***
# Found 2026-08-27 by the terminal session, not by this gate and not by me: a reply whose
# evidence lines read "CHECKED - ..." or "CHECKED --- ..." scored ZERO CHECKED lines, so
# LEDGER-0 and UNCITED-CLAIM judged a fully-cited reply as uncited. The failure is silent
# in the dangerous direction - it cannot produce a false PASS, but it produces false
# alarms that train the reader to discount the channel, which is how a real one gets waved
# through. An em dash, an en dash and a hyphen are all accepted now.
CHECKED_RE = re.compile(r"^\s*(?:[-*>]\s*)?(?:\*\*)?CHECKED\s*(?::|\u2014|\u2013|-)", re.I | re.M)


# *** INLINE EVIDENCE COUNTS AS A CITATION. ROB APPROVED 2026-09-30 19:10 PDT. ***
# The global field changed on 2026-09-30 to "When you say something is done, fixed, saved or
# verified, name in the same sentence the call you ran and what it returned", and told Claude
# to show results, not scaffolding. A CHECKED block is no longer the only legitimate form, so
# a sentence that names a real call AND what came back now cites itself and the reply.
# GUARDS, so prose cannot pass by sounding like evidence: the sentence needs a past-tense
# call verb, a past-tense result verb, and something concrete (a `code span`, a path, a file
# name ); and any sentence about a call not yet made ("would run", "expect it to
# return", "will check") is excluded. A false inline claim is exactly as dangerous as a false
# CHECKED line - this does not make the gate weaker than the form it already accepted.
INLINE_EVIDENCE_RE = re.compile(
    r"\b(?:ran|read|re-read|called|fetched|queried|grepped|searched|hashed|diffed|listed|loaded|executed|opened|measured)\b"
    r"[^.]{0,200}?\b(?:returned|printed|showed|came back|reported|matched|exited|read back|gave|output|listed|found|confirmed)\b", re.I)
_INLINE_HYPOTHETICAL = re.compile(r"\b(?:would|will|expect|expected|plan to|going to|should|could|if i|once i|after i)\b", re.I)
# THE CALL MUST BE NAMED. A bare number was accepted at first and the corpus run on 2026-09-30
# showed the cost: "one independent reviewer read this draft and returned 14 findings" cleared
# LEDGER-0 for a reply whose system claims cited nothing. A `code span`, a path or a file name.
_INLINE_CONCRETE = re.compile(r"(`[^`]+`|/[\w.-]+/|\b\w+\.(?:py|sh|md|tsv|json|jsonl|txt)\b)")

# TWO MECHANICAL GAPS, MEASURED 2026-09-30 ON REAL TOOL-USING REPLIES UNDER THE NEW FIELD.
# (1) "I ran `ls -1 *.txt | wc -l`, which returned 10" failed because the period inside the code
#     span stopped the [^.] window. Code spans are now masked before matching.
# (2) "`find . -maxdepth 1 -type f | wc -l` returned 12" names the call as the SUBJECT, with no
#     call verb. A code span followed closely by a result verb is now accepted as the same form.
_CODE_SPAN = re.compile(r"`[^`]+`")
INLINE_SUBJECT_RE = re.compile(
    r"`CODE`[^.]{0,40}?\b(?:returned|printed|showed|reported|gave|exited|listed|found|matched|identical|equal)\b", re.I)

def inline_evidence(sents):
    out = []
    for s in sents:
        if CHECKED_RE.match(s) or not _INLINE_CONCRETE.search(s) or _INLINE_HYPOTHETICAL.search(s):
            continue
        masked = re.sub(r"`CODE\d*`", "`CODE`", _CODE_SPAN.sub("`CODE`", s))
        if INLINE_EVIDENCE_RE.search(masked) or INLINE_SUBJECT_RE.search(masked):
            out.append(s)
    return out

def inline_evidence_text(text):
    """Split AFTER masking code spans, so 'find . -type f' does not end a sentence mid-call,
    then restore each span so callers see the original words (ABSENCE-CLAIM needs them)."""
    spans = _CODE_SPAN.findall(text)
    it = iter(range(len(spans)))
    masked = _CODE_SPAN.sub(lambda m: "`CODE%d`" % next(it), text)
    out = []
    for sent in inline_evidence(sentences(masked)):
        out.append(re.sub(r"`CODE(\d+)`", lambda m: spans[int(m.group(1))], sent))
    return out


def check_claim_ledger(text):
    sents = sentences(text)
    inline = inline_evidence_text(text)
    claims = [s for s in sents if CLAIM_RE.search(s) and not CHECKED_RE.match(s) and s not in inline]
    checked = CHECKED_RE.findall(text) + inline
    if inline:
        info("inline evidence: %d sentence(s) cite a call and its result" % len(inline))
    info("claim ledger: %d system claims, %d CHECKED lines" % (len(claims), len(checked)))
    if claims and not checked:
        fail("LEDGER-0", "%d system claims, zero CHECKED lines. Every claim is uncited." % len(claims))
    elif claims and len(checked) * 3 < len(claims):
        warn("LEDGER-THIN", "%d system claims vs %d CHECKED lines. Ratio suggests uncited claims."
             % (len(claims), len(checked)))
    return claims, checked


# ---------- 1b. UNCITED-CLAIM, added 2026-08-26 ----------
# *** THE RULE IS PER-CLAIM AND THE GATE MEASURED A RATIO. *** Rob's field says: "List every
# declarative claim the reply will make about a system, each with the tool result in THIS reply
# that supports it. A claim with nothing to cite either gets a tool call or gets cut."
# check_claim_ledger above FAILS only at ZERO CHECKED lines and otherwise compares COUNTS.
# MEASURED 2026-08-26 against the real reply: "5 system claims, 6 CHECKED lines" -> INFO, no
# finding - while the claim "local Claude Code has no Drive connector and no Chrome" was a GUESS
# with no check anywhere in the reply. THE RATIO WAS FAVOURABLE WHILE A SPECIFIC CLAIM WAS
# UNCITED, so a count could never have caught it. Rob's response: "'Asserted'...'guess'. This
# should not be happening anymore!!!"
# THIS IS GATE-CHECKS-A-WEAKER-PROPERTY-THAN-ITS-PURPOSE, already a named CAUSE in the failure
# ledger. An aggregate cannot enforce a per-item rule; it can only enforce an average.
#
# DELIBERATELY CONSERVATIVE. It matches a claim to a CHECKED line by shared distinctive words,
# needing TWO. One word matches by accident; requiring three would miss a terse CHECKED line.
# A false alarm here trains the reader to skip the gate, which is how countcheck nearly died.
_STOP = set("""the a an and or but if then than that this these those is are was were be been being
have has had do does did can cannot could will would should may might must not no nor of in on at to
for from with without by as it its into over under about only just also more most much many few
which who whom whose what when where why how all any both each other some such same so very
claim claims reply line lines run runs ran read reads i you he she they we them our your""".split())

def _words(t):
    return {w for w in re.findall(r"[a-z][a-z0-9_.\-/]{3,}", t.lower()) if w not in _STOP}

def _table_claim_cells(text):
    """Cells from next-steps rows that ASSERT something, verb or not.

    *** THE CLAIM DETECTOR COULD NOT SEE THE TABLE, AND THE TABLE IS WHERE ROB ACTS. ***
    Measured 2026-08-26: the reply that asserted "Cowork: the bridge, Chrome, Drive - everything
    tonight depended on" parsed as ONE system claim in 4,313 characters, and that was not it.
    CLAIM_RE needs a noun and a VERB; a table cell is written terse and verbless - "Local: gates
    actually block. Cowork: the bridge, Chrome, Drive" asserts a capability comparison with no
    copula anywhere in it. So the single most consequential sentence in the reply, the one Rob
    was being asked to DECIDE on, was invisible to the gate that exists to cite claims.
    Status, Recommendation and Pros/Cons cells are taken verbatim as claim candidates.
    """
    out = []
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        # 6-col: Item | Status | Owner | Recommendation | Pros/Cons -> indices 1,3,4
        # 3-col: Item | Owner -> nothing assertive to take
        if len(cells) >= 5:
            out += [cells[1], cells[3], cells[4]]
        if len(cells) >= 6:                  # seven-column shape since 2026-10-04: Cons is its own cell
            out += [cells[5]]
    return [c for c in out if c]


def check_uncited_claims(text, claims, checked_lines):
    if not checked_lines:
        return                       # LEDGER-0 already owns the zero case
    claims = list(claims) + _table_claim_cells(text)
    if not claims:
        return
    pools = [_words(c) for c in checked_lines]
    bad = []
    # *** ONLY CHECKABLE CLAIMS. TUNED 2026-08-26 AFTER MEASURING PRECISION AT ~50%. ***
    # The first version flagged 4 of 5 sentences, and two were general statements of principle
    # ("a hook that breaks a session is worse than the gap it closed") which no tool call can
    # settle. P2-33 already records that a gate whose alarm channel is mostly noise is WORSE
    # than no gate, because it trains the reader to skip it. A claim is only checkable when it
    # names something concrete - a path, a `code span`, or a number. Statements of principle,
    # and the falsifier clause beside a confidence rating, are excluded BY SHAPE rather than by
    # a keyword list, so the exclusion cannot be tuned to one sentence that got through.
    CONCRETE = re.compile(r"(`[^`]+`|/[\w.-]+/|\b\w+\.(?:py|sh|md|tsv|json|jsonl)\b|\d)")
    RATING_LINE = re.compile(r"confidence\s+\d|\d\s*/\s*10", re.I)
    for cl in claims:
        if not CONCRETE.search(cl):
            continue                     # a principle, not a measurable claim
        if RATING_LINE.search(cl):
            continue                     # the rating's own falsifier is covered by RATING-*
        cw = _words(cl)
        if not cw:
            continue
        if not any(len(cw & pool) >= 2 for pool in pools):
            bad.append(cl)
    if bad:
        # *** SHIPPED AS A WARNING, NOT A FAILURE, AND THE REASON IS A MEASUREMENT. ***
        # Precision measured 2026-08-26 against the real reply that prompted this check: 7
        # flagged, roughly 2-3 true - about 35%. A digit alone satisfies the concreteness test,
        # so judgement sentences carrying "#1" are swept in. P2-33 records that a gate whose
        # alarm channel is mostly noise is WORSE than no gate: it trains the reader to skip it,
        # which is how countcheck nearly died. FAILING a reply on a 35%-precision signal would
        # be shipping the defect this check exists to catch, so it warns until precision is
        # measured above ~80%. THE THRESHOLD IS THE PROMOTION CRITERION, not a vague intention.
        warn("UNCITED-CLAIM",
             "%d system claim(s) share no CHECKED line: %s. The rule is per-claim, not a ratio - "
             "a claim with nothing to cite gets a tool call or gets cut."
             % (len(bad), "; ".join("'" + b[:74] + "'" for b in bad[:3])))


# ---------- 2. OFFLOAD / HEDGE ----------
# *** THE CONTRACTION GAP, FOUND 2026-08-16 BY TESTING AGAINST A REAL MISS. ***
# This list had `i haven.t verified`, which matches "haven't" and "havent" but NOT the
# UNCONTRACTED "I have not verified". On 2026-08-16 the sentence "I have not verified the
# editor against it" shipped, Rob caught it by hand, and the check that exists to catch it
# scored the reply 0 FAIL. A LINTER THAT MISSES THE UNCONTRACTED FORM OF ITS OWN TARGET
# PHRASE IS THE GATE-THAT-CANNOT-FAIL SHAPE. Fixed by making the contraction OPTIONAL
# everywhere rather than by adding the one sentence that got through, which would be
# tuning to a single failure.
NEG = r"(?:haven.t|have not|hadn.t|had not|did not|didn.t|do not|don.t|cannot|can.t|could not|couldn.t)"
OFFLOAD = [
    r"worth checking on your end", r"on your end", r"you.d need to", r"you would need to",
    r"i have no way to", rf"i {NEG} verified", rf"i {NEG} check", rf"i {NEG} confirm",
    r"flagging rather than assuming",
    rf"i.ll note i {NEG}", r"next time you have it open", r"you may want to (?:check|confirm|verify)",
    r"can you (?:check|confirm|verify) whether", r"i.m unable to see", r"not visible to me",
    rf"i {NEG} (?:see|access|open|reach)", r"outside what i can",
]
OFFLOAD_RE = [(p, re.compile(p, re.I)) for p in OFFLOAD]


QUOTED = re.compile(r"\u201c[^\u201d]{0,120}\u201d|\"[^\"\n]{0,120}\"|`[^`\n]{0,120}`")


# *** THE FALSE-POSITIVE RATE WAS 42% AND IT WAS MEASURED, NOT ESTIMATED. ***
# On 2026-08-16 all 12 OFFLOAD hits in one project's history were read and classified:
# 6 were real skipped checks, 1 was a genuine trigger-blocker, and 5 WERE FALSE. The five
# fall into three shapes, and none of them is a claim about reach:
#   CONDITIONAL  "if the purpose is written somewhere I could not open" - hypothetical
#   RULE-STATING "a claim I haven't checked doesn't enter the report"   - stating the rule
#   PERCEPTUAL   "the one I can't see while writing"                    - about composing
# A DETECTOR WITH A 42% FALSE-POSITIVE RATE PRODUCES A NUMBER NOBODY CAN ACT ON, which is
# how a real finding gets discounted. Excluded structurally rather than by adding the five
# sentences that failed.
CONDITIONAL = re.compile(r"\b(?:if|unless|whether|were)\b[^.]{0,80}$", re.I)
RULE_STATING = re.compile(r"\b(?:a claim|any claim|rule|never|must not|does not enter|doesn.t enter)\b", re.I)
PERCEPTUAL = re.compile(r"(?:see|notice|spot|catch)\s+(?:it|that|them)?\s*while\s+(?:writing|composing|drafting)", re.I)


def check_offload(text):
    # a phrase named as an example is not the phrase being used
    scrub = QUOTED.sub(lambda m: " " * len(m.group(0)), text)
    for p, rx in OFFLOAD_RE:
        m = rx.search(scrub)
        if not m:
            continue
        lead = scrub[max(0, m.start() - 90):m.start()]
        tail = scrub[m.start():m.start() + 90]
        # *** THE FIRST VERSION OF THIS EXCLUSION TRADED A FALSE POSITIVE FOR A FALSE
        # NEGATIVE, WHICH IS THE WORSE DIRECTION, AND ITS OWN CONTROL CAUGHT IT. ***
        # "Drops to 6 if the Skills page is an independent editor, WHICH I have not opened"
        # was suppressed because an "if" appeared earlier in the sentence. But the
        # conditional there belongs to the CONFIDENCE FALSIFIER, not to the reach claim:
        # the phrase sits in a RELATIVE CLAUSE asserting a fact about me, not inside the
        # hypothetical. A phrase introduced by "which" or "that" is an assertion whatever
        # precedes it, so the conditional exclusion does not apply to it.
        relative = re.search(r"\b(?:which|that)\s*$", lead, re.I)
        if not relative and CONDITIONAL.search(lead):
            continue
        if RULE_STATING.search(lead) or PERCEPTUAL.search(tail):
            continue
        fail("OFFLOAD", "phrase %r at char %d - this is an unmeasured constraint or a check handed back."
             % (m.group(0), m.start()))


# ---------- 2b. TOOL DEAD-END ----------
# *** OFFLOAD MISSES THE CORRECTLY-PHRASED VERSION, AND THAT IS NOT A BUG IN OFFLOAD. ***
# Every OFFLOAD pattern keys on "I" as the subject. Rob's rule is the opposite: "Name the
# tool, never the outcome. 'The Drive connector cannot rename a Doc' is a true statement
# about one tool. 'Nobody can rename a Doc' is false." So a TOOL-subject claim is the
# (CORRECTED, made 2026-08-16, fixed 2026-10-07: the example itself proved false - the native
# Drive connector's update_file renames, measured 2026-09-08 and 2026-10-07. The phrasing
# point stands: name the tool.)
# CORRECT form and must not be flagged for its phrasing.
# THE DEFECT IS STOPPING THERE. Measured 2026-08-16 across one project's history: five
# tool-subject reach claims, of which two named an alternative route or a real credential
# blocker and were fine, two were DEAD ENDS that Rob had to catch by hand, and one was the
# retrospective describing the defect. "present_files can't reach the Drive folder" was
# true and complete-sounding; the Drive connector, Chrome and the desktop app all reached
# it, and the reply handed over a filesystem path instead.
# SO THE CHECK IS NOT "did you name a tool" BUT "did you name what DOES reach it".
# *** THE FIRST PATTERN UNDER-MATCHED AND ITS OWN CONTROL CAUGHT IT. *** It listed bare
# nouns like `the page`, so "the SETTINGS page has no read affordance" slipped through, and
# the corpus reported 1 dead-end where a hand count found 2. A MODIFIER BETWEEN THE ARTICLE
# AND THE NOUN IS THE NORMAL WAY THESE ARE WRITTEN - the settings page, the Drive connector,
# the plugin cache. Allowing one optional modifier is the fix; adding "the settings page" as
# a literal would have been tuning to the one sentence that failed.
TOOL_REACH = re.compile(
    r"\b(present_files|[a-z_]+_files|clasp|this session|the workspace|"
    r"(?:the|a)\s+(?:\w+\s+){0,2}(?:connector|sandbox|tool|editor|API|page|hook|probe|cache|"
    r"grid|endpoint|script|panel|field))\b"
    r"[^.]{0,45}?\b(?:can.?t|cannot|could not|couldn.t|does not|doesn.t|is unable|"
    r"has no|had no|returns? no|refuses?)\b", re.I)

# *** THE PATTERN ABOVE ONLY MATCHES NOUN-THEN-NEGATION: "the page cannot be read". ***
# The global field's trigger list explicitly names the REVERSE order -- "I have no way to
# observe X from here", "I can't see that from where I am" -- and this checker could not
# see any of them. Found 2026-08-16 when a control written for that exact phrasing failed
# TWICE and I assumed both times that the control was wrong. THE THIRD LOOK WAS AT THE
# PATTERN. A rule naming a phrasing the detector cannot match is the coverage gap that
# makes a linter feel safer than it is.
TOOL_REACH_REV = re.compile(
    r"\b(?:I\s+have\s+no\s+way|there.s\s+no\s+way|no\s+way\s+to|"
    r"I\s+can.?t\s+see|I\s+cannot\s+see|not\s+visible\s+to\s+me)\b"
    r"[^.]{0,60}?\b(?:connector|sandbox|tool|editor|API|page|hook|probe|cache|"
    r"grid|endpoint|script|panel|field|file|settings)\b", re.I)

# An alternative route, or a blocker that is genuinely physical. Either discharges it.
ALTERNATIVE = re.compile(
    r"\b(instead|via|use[sd]? the|another|other tool|reaches it|through the|fall ?back|"
    r"chrome|computer.use|desktop app|connector can|browser|credential|token|password|"
    r"approval|physically|only i can|forbidden)\b", re.I)


# *** BACKTICKS ARE CODE FORMATTING, NOT QUOTATION, AND SCRUBBING THEM BLINDED THIS CHECK.
# The shared QUOTED filter exists so a phrase NAMED AS AN EXAMPLE does not fire the checks
# that hunt that phrase. It strips "..." and `...` alike. But a TOOL NAME is written in
# backticks as a matter of house style, so `present_files` can't reach ... was scrubbed to
# spaces and the check saw nothing. Control caught it; the corpus had reported 1 where a
# hand count found 2. TOOL-DEADEND therefore strips only real quotation marks. ***
DQUOTE_ONLY = re.compile(r"“[^”]{0,120}”|\"[^\"\n]{0,120}\"")


def check_tool_deadend(text):
    scrub = DQUOTE_ONLY.sub(lambda m: " " * len(m.group(0)), text)
    for m in list(TOOL_REACH.finditer(scrub)) + list(TOOL_REACH_REV.finditer(scrub)):
        window = scrub[m.end():m.end() + 260]
        if ALTERNATIVE.search(window):
            continue
        warn("TOOL-DEADEND",
             "%r names a tool that cannot, and nothing within 260 chars names what does. "
             "Naming the tool is correct; stopping there is the defect."
             % re.sub(r"\s+", " ", m.group(0))[:70])


# ---------- 2a. APPROVAL-UNTESTED ----------
# *** BUILT 2026-10-02 AFTER A REPLY SAID "Creating a task in your account needs your approval"
# WITHOUT EVER CALLING create_trigger. When it was called it returned CREATED, permission_mode
# auto, and no approval card. The claim was false, and this linter scored it 0 for it: OFFLOAD
# has no approval pattern, and the rating-falsifier logic treats "an approval only Rob can give"
# as a LEGITIMATE blocker - so an approval claim was the one hand-off the gate endorsed.
# The rule: a sentence asserting that Rob's approval, permission or sign-off is required must
# sit in a paragraph that cites a tool result - a refusal, an error, an approval card, NOT RUN,
# or a named call followed by "returned". Double-quoted text is scrubbed first, so quoting the
# bad sentence (as this comment does) never fires. Scope is deliberately capability-shaped
# phrasing; "approve rows by number" is a decision request and does not match. "An approval only
# Rob can give" was in the first draft and was REMOVED after a run over 252 stored replies: its two
# hits were both Rob-row labels on real decisions, which is the legitimate use of the phrase.
APPROVAL_CLAIM = re.compile(
    r"\b(?:needs?|requires?|need)\s+(?:your|rob.?s)\s+(?:approval|sign-?off|permission|"
    r"authori[sz]ation|go-?ahead)\b"
    r"|\b(?:can.?t|cannot|could not|couldn.?t)\b[^.\n]{0,60}\bwithout\s+(?:your|rob.?s)\s+"
    r"(?:approval|sign-?off|permission|authori[sz]ation)\b"
    r"|\bawaiting\s+(?:your|rob.?s)\s+(?:approval|sign-?off|permission)\b"
    # RECALL PASS 2026-10-02: four paraphrases missed by the first version, measured.
    r"|\byou(?:.ll|\s+will)?\s+need\s+to\s+(?:approve|authori[sz]e|sign\s+off|grant)\b"
    # "yours to approve" was tried and REMOVED: a sweep of 252 stored replies gave 6 hits, all of
    # them legitimate decision-rights statements (loosening a gate, a publish setting), not
    # capability claims. Decision phrasing is not separable from capability phrasing by regex.
    r"|\bonly\s+(?:you|rob)\s+can\s+(?:approve|authori[sz]e|grant|sign\s+off)\b"
    r"|\bonce\s+you(?:.re|\s+are)\s+happy\b", re.I)
APPROVAL_EVIDENCE = re.compile(
    r"\breturned\b|\brefused\b|\bNOT RUN\b|\bapproval card\b|\bpermission prompt\b|\berror\b|"
    r"\bHTTP\s*\d{3}\b|\b(?:40[13]|405|409|429|5\d\d)\b|\bdenied\b|\brejected\b", re.I)


def check_approval_untested(text):
    body = re.sub(r"```.*?```", lambda m: " " * len(m.group(0)), text, flags=re.S)
    body = DQUOTE_ONLY.sub(lambda m: " " * len(m.group(0)), body)
    body = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), body)
    for para in re.split(r"\n\s*\n", body):
        m = APPROVAL_CLAIM.search(para)
        if not m or APPROVAL_EVIDENCE.search(para):
            continue
        fail("APPROVAL-UNTESTED",
             "%r says Rob's approval is required, and nothing in the same paragraph cites the "
             "tool result that proves it - a refusal, an error, an approval card. Make the call "
             "first; if it needs his sign-off, its own card will say so. On 2026-10-02 this "
             "exact claim was false." % re.sub(r"\s+", " ", m.group(0))[:70])


# ---------- 2a1. HANDOFF-UNTESTED ----------
# *** BUILT 2026-10-28 (Rob 08:33 and 08:37 PDT; INTAKE F-935). A reply said "BLOCKED: that needs a new Mac Claude
# Code session, which only you can start" and Rob had to ask five times for a check that a shell on his Mac ran in
# under a minute (claude plugin list printed imc-reply-gate@synced Version 0.3.20, Status loaded). His global rules
# already said it: "Never hand me a check you could run", "Do not assign Rob a task before checking whether a tool
# can do it". The rules were in context; nothing refused the sentence. HOLLOW-BLOCKED only caught vague reasons, and
# APPROVAL-UNTESTED covers approvals only, so a capability claim about Rob's own machine went straight through. The
# rule: a sentence saying only Rob can do an act, or that an act needs him to do it, must sit in a paragraph that
# cites a failed or refused call - returned, refused, error, denied, did not respond, timed out, not found, NOT RUN.
# Double-quoted text, code spans and fences are scrubbed first, so quoting the bad sentence never fires. ***
HANDOFF_CLAIM = re.compile(
    r"\bonly\s+(?:you|rob)\s+can\s+(?:start|open|run|launch|restart|quit|click|install|enable|check|read|reach|"
    r"see|do|flip|press|type|log\s*in)\b"
    r"|\b(?:needs?|requires?)\s+(?:you|rob)\s+to\s+(?:start|open|run|launch|restart|quit|click|install|enable|"
    r"check|read|reach|press|type|log\s*in)\b"
    r"|\b(?:needs?|requires?)\s+a\s+(?:new|fresh)\s+(?:mac\s+)?(?:claude(?:\s+code)?\s+)?(?:session|chat|window)\b"
    r"[^.\n]{0,80}\b(?:you|rob)\b"
    r"|\bI\s+(?:can.?t|cannot|am\s+unable\s+to)\s+(?:start|open|launch|restart|run|reach)\b[^.\n]{0,60}"
    r"\b(?:your|the)\s+(?:mac|desktop|computer|app)\b", re.I)
HANDOFF_EVIDENCE = re.compile(
    r"\breturned\b|\brefused\b|\bNOT RUN\b|\bdenied\b|\brejected\b|\berror\b|\bdid\s+not\s+respond\b|"
    r"\btimed\s+out\b|\bnot\s+found\b|\bno\s+such\b|\bunavailable\b|\bpermission\s+prompt\b|"
    r"\bHTTP\s*\d{3}\b|\bexit\s+code\b|\brc=\d", re.I)


def check_handoff_untested(text):
    body = re.sub(r"```.*?```", lambda m: " " * len(m.group(0)), text, flags=re.S)
    body = DQUOTE_ONLY.sub(lambda m: " " * len(m.group(0)), body)
    body = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), body)
    for para in re.split(r"\n\s*\n", body):
        m = HANDOFF_CLAIM.search(para)
        if not m or HANDOFF_EVIDENCE.search(para):
            continue
        fail("HANDOFF-UNTESTED",
             "%r hands Rob an act, and nothing in the same paragraph cites the failed or refused call that "
             "proves Claude cannot do it. Read the tool list, make the call (a shell on his Mac, a browser, a "
             "file tool), then say what it returned. On 2026-10-28 this exact sentence was false: a shell on "
             "his Mac ran the check in under a minute." % re.sub(r"\s+", " ", m.group(0))[:70])


# ---------- 2a2. DECLINE-UNQUOTED ----------
# *** BUILT 2026-10-23 (Rob 2:49 PM PDT, "I agree with your recommendations for items 1-5", item 3; INTAKE F-769,
# interrupted tool call read as a user refusal). A reply said "You declined the independent reviewer call"; the only
# evidence was the harness text "The user doesn't want to proceed with this tool use" that arrived beside Rob's next
# message. Rob had declined nothing ("When did i decline this?"). The rule: a sentence saying Rob declined, refused,
# rejected, denied or turned something down must sit in a reply that has a CHECKED line quoting his own message
# in double quotes with its Pacific time (for example 'CHECKED: your 2:24 PM PDT message "..."'). Double-quoted text is
# scrubbed before the claim search, so quoting the bad sentence never fires. ***
DECLINE_CLAIM = re.compile(
    r"\byou\s+(?:had\s+|have\s+)?(?:declined|refused|rejected|denied|turned\s+down|cancel+ed|"
    r"said\s+no\s+to|did\s+not\s+approve|didn.?t\s+approve)\b", re.I)
DECLINE_EVIDENCE = re.compile(
    r"^\s*CHECKED:[^\n]*\b\d{1,2}:\d{2}\s*(?:AM|PM)?[^\n]*[\"\u201c][^\"\u201d\n]{12,}[\"\u201d]", re.I | re.M)


def check_decline_unquoted(text):
    body = re.sub(r"```.*?```", lambda m: " " * len(m.group(0)), text, flags=re.S)
    claim_body = DQUOTE_ONLY.sub(lambda m: " " * len(m.group(0)), body)
    claim_body = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), claim_body)
    m = DECLINE_CLAIM.search(claim_body)
    if not m or DECLINE_EVIDENCE.search(body):
        return
    fail("DECLINE-UNQUOTED",
         "%r says you declined or refused something, and no CHECKED line quotes your own message with its "
         "Pacific time. A harness line such as 'The user doesn't want to proceed with this tool use' is an "
         "interrupted call, not your refusal (F-769, 2026-10-23). Quote your message or drop the claim."
         % re.sub(r"\s+", " ", m.group(0))[:70])


# ---------- 2b. REACH-UNSOURCED ----------
# *** ADDED 2026-09-26 TO CLOSE A MEASURED GAP, NOT TO RESTATE A RULE THAT ALREADY EXISTS. ***
# Two checks already stand near this one and NEITHER asks the question this one asks:
#   TOOL-DEADEND asks "what reaches it instead" - a route, not a source. It passes
#     "the connector cannot edit, so use the local mirror", which cites nothing.
#   ABSENCE-CLAIM asks for a search plus a positive control, but its verb list is
#     can(not) reach|see|find|list|access and does not exist. MEASURED BEFORE WRITING THIS:
#     ABSENCE_CLAIM.search("the Drive connector cannot edit content") -> None;
#     .search("the endpoint does not support tables") -> None;
#     .search("the connector has no update action") -> None.
# So a CAPABILITY claim about a named tool - the class the project instructions record as
# having been asserted untested five times - passes both. This check demands the one thing
# neither does: that the claim cite the tool's own account of itself, a quoted error, or a
# dated measurement. The scope is deliberately the verbs ABSENCE_CLAIM misses, so the two
# do not overlap and neither is weakened.
REACH_CAP = re.compile(
    r"\b((?:the|a)\s+(?:\w+\s+){0,2}(?:connector|sandbox|tool|editor|API|endpoint|script|"
    r"panel|hook|probe|cache|field|bridge|shell|mirror)|[a-z_]{3,}_[a-z_]{3,}|clasp(?:\s+\w+)?)\b"
    r"[^.]{0,60}?\b(?:can(?:not|.t)|could\s+not|couldn.t|does\s+not|doesn.t|has\s+no|have\s+no|"
    r"is\s+unable\s+to|refuses?\s+to|never)\s+"
    r"(?:\w+\s+){0,2}?(?:edit|write|update|append|modify|rename|delete|move|support|accept|"
    r"project|read|create|copy|trash|untrash|resolve|run|post|push|pull|apply|deploy|"
    r"publish|sync|save)\b", re.I)
# *** TWO CORRECTIONS FROM THE CONTROL RUN, BOTH BEFORE THIS CHECK WAS TRUSTED ONCE. ***
# (1) "deploy" was missing and the control "clasp push cannot deploy the web app" returned
#     ZERO hits - the single most consequential claim in this pipeline, since a push is not a
#     deploy, and the first draft of the detector could not see it. Added deploy, publish,
#     sync, save.
# (2) "reach" was in the verb list, which is ABSENCE_CLAIM's own territory
#     (can(?:not|.t) reach) and would have fired two codes on one sentence, weakening both.
#     Removed, so the scope now matches what the comment above claims it is.

# What discharges it. Any ONE of: the tool's own self-description (its schema, its docs, its
# tool list, its own header), a quoted error or return value, or a dated measurement. A bare
# "I tested this" does not qualify - the point is that the EVIDENCE is nameable by the reader.
REACH_SOURCE = re.compile(
    r"\b(?:its\s+own\s+(?:docs|documentation|description|schema|header|tool\s+list)|"
    r"tool\s+(?:list|schema|description)s?\b|documented\b|per\s+the\s+docs|the\s+docs\s+say|"
    r"tool\s+set\s+is|entire\s+tool\s+set|schema\s+(?:has|shows|names|omits)|"
    r"returned\b|returns\s+[{\"\u201c]|error\b|exit\s+\d|"
    r"measured\s+(?:on\s+)?20\d\d-\d\d-\d\d|tested\s+20\d\d-\d\d-\d\d|"
    r"CHECKED:|re-?measured|read\s+back)\b", re.I)


def check_reach_unsourced(text):
    """REACH-UNSOURCED: a capability claim about a named tool must cite how it is known.

    Window is 300 chars after the claim and 160 before, because the citation is written
    either way round ("measured 2026-08-14: update_file moved ..." precedes the verdict as
    often as it follows it).
    """
    scrub = DQUOTE_ONLY.sub(lambda m: " " * len(m.group(0)), text)
    for m in REACH_CAP.finditer(scrub):
        window = scrub[max(0, m.start() - 160):m.end() + 300]
        if REACH_SOURCE.search(window):
            continue
        warn("REACH-UNSOURCED",
             "%r asserts what a named tool cannot do, and nothing within the surrounding "
             "460 chars cites the tool's own docs or schema, a quoted error, or a dated "
             "measurement. An untested reach claim reads exactly like a tested one."
             % re.sub(r"\s+", " ", m.group(0))[:80])


# ---------- 3. AGREEMENT OPENER ----------
AGREE_RE = re.compile(
    r"^\W*(?:you.re right|you are right|good catch|exactly|fair point|good question|"
    r"great question|that.s a great|correct[,.]|absolutely|totally agree|agreed[,.]|"
    # 0.3.7 (Rob approved row 2, 2026-10-23 19:13 PDT): acknowledgment openers a sample of five replies showed.
    r"understood\b|noted[,.!]|got it\b|thanks?\b|thank you\b|sure[,.!]|of course\b|i understand\b|"
    r"both of your answers\b|okay[,.!]|ok[,.!])", re.I)


# *** THE BAN IS ON THE PHRASE, NOT ON THE OPENING SENTENCE. MEASURED 2026-08-19. ***
# check_opener below inspects the FIRST SENTENCE ONLY. bin/failuretable.py scanned 48 sessions of
# raw logs and found 72 uses of a banned agreement phrase across 8 sessions between 2026-08-07 and
# 2026-08-18 - nearly all of them mid-reply, in paragraph three, where check_opener cannot see.
# The global field says "if you catch yourself typing one, delete it and rewrite", with no
# position qualifier. So the detector needed to match the rule's scope, and it did not.
# PAST TENSE ADDED 2026-09-06. The regex matched "you're right" and "you are right" and returned
# False for "you were right" - the form a concession takes AFTER Rob has already corrected
# something, which is exactly the case the rule exists for. Measured on this session's own output:
# AGREE_ANYWHERE.search("You were right to pull that item") returned None.
AGREE_ANYWHERE = re.compile(r"\byou(?:(?:'|\u2019)?re| are| were| was) (?:right|correct)\b|"
                            r"\byou(?:(?:'|\u2019)?ve| have| had) a point\b|"
                            r"\bgood catch\b|\bgreat question\b|"
                            r"\bfair point\b|\bthat.s a great (?:observation|point)\b|"
                            r"(?:^|\n)\s*Exactly\b(?=[\s,.!])", re.I)


def check_agreement(text):
    """Every banned agreement phrase, wherever it appears. IN CORPUS_CHECKS, so the rate moves."""
    for m in AGREE_ANYWHERE.finditer(text):
        i = max(0, m.start() - 60)
        fail("AGREEMENT", "banned agreement phrase %r - the ban has no position qualifier, and "
                          "conceding mid-reply spends the sentence on Rob's correctness rather "
                          "than on the fact: %r" % (m.group(0), " ".join(text[i:m.end() + 80].split())))
        return


def check_opener(text):
    first = next((s for s in sentences(text) if len(s) > 2), "")
    if AGREE_RE.match(first):
        fail("OPENER", "reply opens with agreement: %r" % first[:70])
    # the mechanical test: does the first sentence survive deleting the user?
    if re.match(r"^\W*(?:you|your)\b", first, re.I):
        warn("OPENER-YOU", "first sentence is about the reader, not the fact: %r" % first[:70])


_EVERY_TABLE_HDR = re.compile(r"^\s*\|\s*#\s*\|\s*Issue\s*/\s*Risk\s*\|", re.M)


_ALL_DONE_RE = re.compile(r"^\s*ALL OBJECTIVES DONE:\s*(\S.{39,})$", re.M)
_ALL_DONE_BAD = re.compile(r"BLOCKED:|UNTESTED|drops to|NOT READ|thorough:\s*no\b|WAITING-ON-ROB|\bunresolved\b", re.I)
# 0.4.10 (Rob 2026-11-25 2:56 PM PST, "WHY DID YOU STOP???", session 05185df0): a reply that said "Two panel points stay
# unresolved" about checks Claude could still run closed on ALL OBJECTIVES DONE and the Stop hook allowed it (log
# 2026-11-25T14:34:27, "fails": []). A reply that names anything unresolved is not all done.
# 0.4.8: OPEN is the register's status word, so it is matched in capitals only. With re.I the plain words "still open
# then" and "the last open row" in a reply that closed its last row cancelled ALL OBJECTIVES DONE (measured 2026-11-25
# 2:17 PM PST, session 05185df0).
_ALL_DONE_OPEN = re.compile(r"\bOPEN\b")


def _all_done_exempt(text):
    """0.3.36 (Rob 2026-11-04 7:40 AM PST): the only reply that owes no next-steps table is one where every action and
    decision of the session is measured, tested and verified and every objective is DONE. Mechanical form: a line
    'ALL OBJECTIVES DONE: <at least 40 characters naming the call and result>' and no BLOCKED:, UNTESTED, drops to,
    NOT READ, thorough: no, OPEN or WAITING-ON-ROB anywhere in the reply. The gate cannot prove the claim true."""
    return bool(_ALL_DONE_RE.search(text)) and not _ALL_DONE_BAD.search(text) and not _ALL_DONE_OPEN.search(text)


def check_every_reply_table(text):
    """0.2.31 (Rob 2026-10-16 'a Next Steps table must ALWAYS be used in EVERY reply'; F-684 family, next-steps row 46).
    OPT-IN: runs only when REPLYCHECK_EVERY_TABLE=1, which hooks/gate.py sets for chat replies, so deliverables, drafts
    and task reports (OI-0256) are not asked for a table they cannot carry. gate.py lists the code in STATUS_WATCH, so
    until WATCH_UNTIL it only logs a STATUS-WATCH line."""
    if os.environ.get("REPLYCHECK_EVERY_TABLE") != "1":
        return
    if not _EVERY_TABLE_HDR.search(text):
        if _all_done_exempt(text):  # 0.3.36 (Rob 2026-11-04 7:40 AM PST)
            return
        try:  # 0.3.6: the one-line form for a reply whose rows did not change (lengthcheck.unchanged_line_ok)
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import lengthcheck
            if lengthcheck.unchanged_line_ok(text, os.environ.get("REPLYCHECK_DRAFT")):
                return
        except Exception:
            pass
        fail("EVERY-REPLY-TABLE", "this reply carries no next-steps table; Rob's rule (2026-11-04 7:40 AM PST) is a table in every reply "
                                  "unless the reply has a line 'ALL OBJECTIVES DONE: <40+ characters naming the call and result>' and no open item "
                                  "(header '| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |').")


# ---------- DONE-NO-CALL, 0.3.37 (Rob 2026-11-03 10:18 PM PST and 2026-11-04 7:41 PM PST pins R2: before saying DONE, fixed or
# verified, name the call that measured it and what it returned) ----------
# MEASURED CAUSE of the gap: a grep of 0.3.36 found no check on a completion claim by itself; check_claim_ledger only reads
# sentences about a system noun, so "I fixed it." passed with no call anywhere in the reply.
# NARROW BY DESIGN: only a first-person completion verb or "is/are (now) done|fixed|saved|verified|closed". Quoted text, code
# spans, table rows, CHECKED lines, negations, hypotheticals and objective status lines are not read. A sentence passes when it is
# itself inline evidence (a call verb, a result verb and a concrete name) or when a CHECKED line shares two distinctive words.
_DONE_FIRST = re.compile(r"\b(?:i(?:'ve| have)?|we(?:'ve| have)?)\s+(?:now\s+|just\s+|also\s+)?(?:saved|fixed|verified|edited|added|updated|applied|closed|confirmed|completed|finished|installed|deployed|uploaded|logged|removed|renamed|backed up)\b", re.I)
_DONE_STATE = re.compile(r"\b(?:is|are|was|were)\s+(?:now\s+)?(?:done|fixed|saved|verified|closed|complete|completed|applied)\b", re.I)
_DONE_SKIP = re.compile(r"\b(?:not|never|no|none|nothing|no longer|n't|cannot|unless|if|would|will|should|could|once|until|before|after i|to be)\b|^(?:PROJECT OBJECTIVE|OBJECTIVE|ALL OBJECTIVES DONE|PRE-SEND REVIEW|HANDOFFS|BLOCKED|SELF-CHECK|CORRECTION)\b|^\|", re.I)


def check_done_claim(text):
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    body = re.sub(r"\"[^\"\n]{0,400}\"", " ", body)
    body = re.sub(r"`[^`\n]+`", "`CODE`", body)
    inline = set(inline_evidence_text(text))
    pools = [_words(ln) for ln in text.splitlines() if CHECKED_RE.match(ln)]
    bad = []
    for sent in sentences(body):
        if CHECKED_RE.match(sent) or _DONE_SKIP.search(sent):
            continue
        if not (_DONE_FIRST.search(sent) or _DONE_STATE.search(sent)):
            continue
        if any(sent in i or i in sent for i in inline):
            continue
        if re.search(r"`CODE`", sent) and (INLINE_EVIDENCE_RE.search(sent.replace("`CODE`", "`x`")) or INLINE_SUBJECT_RE.search(sent)):
            continue
        sw = _words(sent)
        if any(len(sw & pool) >= 2 for pool in pools):
            continue
        bad.append(sent)
    if bad:
        # WATCH: until 2026-11-07 8:00 PM Pacific the check only warns, because it flagged 25 percent of 9,854 corpus replies of
        # 300+ characters (7 of a 10-reply sample were real unsupported claims, 3 false hits); REPLYCHECK_DONE_ENFORCE=1 forces fail.
        _enf = os.environ.get("REPLYCHECK_DONE_ENFORCE") == "1" or datetime.datetime.now() >= datetime.datetime(2026, 11, 5, 10, 0)
        (fail if _enf else warn)("DONE-NO-CALL", "%d completion claim(s) name no call and no result: %s. Rob's rule (R2): before saying DONE, fixed or verified, "
             "name in the same sentence the call you ran and what it returned, or cite a CHECKED line that shares two words with it."
             % (len(bad), " | ".join(b[:120] for b in bad[:3])))



# ---------- CLOSED-ON-INFERRED-CAUSE, core serial 6 (OI-0789, measured 2026-11-25 session 05185df0) ----------
# MEASURED CAUSE: the reply that closed OI-0733 carried "ROOT CAUSE: inferred, not proven - ..." beside "OI-0733 (...) is now
# closed" and a CHECKED line "CLOSED OI-0733 as DONE", and precheck stamped it (stamp a7b37d9554adf57f). Rob's EVIDENCE paragraph
# requires the root cause found and fixed first, so a close beside an inferred cause is a premature close. NARROW: fires only
# when a ROOT CAUSE line opens with "inferred" and the reply claims a register row closed or DONE. Not caught: a line that is
# measured for one row and inferred for another; quoted text is not read.
_RC_INFERRED = re.compile(r"^\s*ROOT CAUSE:\s*inferred\b", re.I | re.M)
_ROW_CLOSED = re.compile(r"\bCLOSED\s+OI-\d{3,5}\s+as\s+DONE\b|\bOI-\d{3,5}\b[^.\n|]{0,160}?\b(?:is\s+(?:now\s+)?closed|was\s+closed|closed\s+as\s+DONE)\b", re.I)


def check_closed_inferred(text):
    if not _RC_INFERRED.search(text):
        return
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    body = re.sub(r"\"[^\"\n]{0,400}\"", lambda m: m.group(0) if "CLOSED OI-" in m.group(0) else " ", body)
    m = _ROW_CLOSED.search(body)
    if m:
        fail("CLOSED-ON-INFERRED-CAUSE", "the ROOT CAUSE line says inferred, yet the reply closes a register row ('%s'). "
             "Rob's EVIDENCE rule: find the root cause and fix it before closing. Measure the cause first, or keep the row open "
             "and say what measuring it needs (OI-0789)." % m.group(0)[:120])


# ---------- ENDS-ON-INTENT, 0.3.39 (Rob 2026-11-05 12:15 AM PST "WHY DID YOU STOP???") ----------
# MEASURED CAUSE: in the 48-hour trace of 30 complaint messages, 5 replies before them ended on a wait or a promise ("I'm waiting
# for C", "I'll run the large job next", "next I rerun gatescan") with no tool call after it, and at 12:15 AM PST this session ended
# on "I'm moving on to the trace". A Stop hook runs only when the turn is ending, so a final sentence that states future work or a
# wait is a stop with work left. NARROW: the last 2 prose sentences only; quotes, code, table rows and negations are not read; a
# BLOCKED: or CANCELLED: line names the real stop and passes.
_INTENT_END = re.compile(r"\b(?:i(?:'m| am)\s+(?:now\s+)?(?:moving on|starting|waiting|going to|about to|running|rerunning|re-running|checking|building|tracing)|i(?:'ll| will)\s+(?:now\s+)?\w+|next,?\s+i(?:'ll| will)?\s+\w+|then i(?:'ll| will)\s+\w+)", re.I)
_INTENT_SKIP = re.compile(r"\b(?:not|never|no|n't|cannot|if|unless|would|once rob|once you|waiting (?:on|for) (?:you|your|rob)|reply)\b", re.I)


def check_ends_on_intent(text):
    if re.search(r"^\s*(?:BLOCKED|CANCELLED|ALL OBJECTIVES DONE)\s*:", text, re.M):
        return
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    body = re.sub(r"\"[^\"\n]{0,400}\"", " ", body)
    body = re.sub(r"`[^`\n]+`", "`CODE`", body)
    prose = [ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("|")]
    tail = sentences(" ".join(prose[-3:]))[-2:]
    for sent in tail:
        if _INTENT_END.search(sent) and not _INTENT_SKIP.search(sent):
            _enf = os.environ.get("REPLYCHECK_INTENT_ENFORCE") == "1" or datetime.datetime.now() >= datetime.datetime(2026, 11, 5, 10, 0)
            (fail if _enf else warn)("ENDS-ON-INTENT", "the reply ends on future work or a wait with no tool call after it: %s. Rob (2026-11-05 12:15 AM PST, "
                 "'WHY DID YOU STOP???'): do the work now, or end on 'BLOCKED: <the call that failed or the decision that is Rob's>'." % sent[:140])
            return


# ---------- NOTHING-LEFT-CLAIM, 0.3.47 (Rob 2026-11-11 4:32 PM PST "WHY DID YOU STOP??? ... Pin this", rule R26) ----------
# MEASURED CAUSE: the 4:20 PM PST reply closed "Nothing is left that needs a decision from you. The 05:50 PST scan ... is the only open
# item, and it runs on its own." The scan could run at once (R17) and 23 reviewer findings were deferred to "the next reply". A closing
# sentence that says nothing remains is a claim that no runnable work is left; it passes only with an ALL OBJECTIVES DONE: line or a
# stated reason that the check needs time to pass. NARROW: the last 3 prose sentences; quotes, code and table rows are not read.
_NOTHING_LEFT = re.compile(r"\b(?:nothing (?:is )?(?:left|remains)|nothing else (?:is )?(?:left|remains)|the only open item|only open item|runs on its own|needs nothing from you|no (?:decision|action) (?:is )?(?:left|remains|needed from you))\b", re.I)


def check_nothing_left(text):
    if re.search(r"^\s*ALL OBJECTIVES DONE\s*:", text, re.M):
        return
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    body = re.sub(r"\"[^\"\n]{0,600}\"", " ", body)
    body = re.sub(r"`[^`\n]+`", "`CODE`", body)
    prose = [ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("|")]
    for sent in sentences(" ".join(prose[-4:]))[-3:]:
        if _NOTHING_LEFT.search(sent) and not re.search(r"needs? time to pass|\bnot\b|\bnever\b", sent, re.I):
            fail("NOTHING-LEFT-CLAIM", "the reply closes on a claim that nothing is left or that the only open item runs on its own: %s. Rob (2026-11-11 4:32 PM PST, "
                 "'WHY DID YOU STOP???', rule R26): run every check, scan and finding you can run now; keep a scheduled check only if it needs time to pass and say why; "
                 "otherwise cite an ALL OBJECTIVES DONE: line with the call and result." % sent[:140])
            return


_REC_ROW = re.compile(r"^\s*\|\s*\d+\s*\|(.+)\|\s*$", re.M)


def check_untested_rec(text):
    """REC-NOT-TESTED, Rob 2026-11-05 9:15 AM PST ('recommendations without testing them'). The 7-column table's
    Recommendation cell (5th) must carry TESTED as its first label; a cell whose first label is UNTESTED, or with no label, is a recommendation
    Rob said he does not want to see (10:03 PM PST 2026-11-04). Measured 2026-11-05: 15 UNTESTED and 5 unlabelled of
    91 cells; 8 UNTESTED cells were sent after his ruling."""
    for m in _REC_ROW.finditer(text):
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != 6:                      # 7-column table: the number cell is outside the match
            continue
        rec = cells[3]
        _lab = re.search(r"\b(UNTESTED|TESTED)\b", rec)
        if _lab and _lab.group(1) == "TESTED":
            continue
        _enf = os.environ.get("REPLYCHECK_UNTESTED_ENFORCE") == "1" or datetime.datetime.now() >= datetime.datetime(2026, 11, 5, 10, 0)
        (fail if _enf else warn)("REC-NOT-TESTED", "Recommendation cell is UNTESTED or unlabelled: %r. Run the test now (a dry run, a copy, a replay) and "
             "begin the cell 'RECOMMEND: <what to do> TESTED (<call and result>)' - the advice first, then the run behind it (RECO-STATED, Rob 2026-11-22); if only Rob's approval or credential blocks the test, put the row under BLOCKED: and "
             "recommend only after the test." % rec[:90])
        return



# ---------- REC-TESTED-HEDGE (Rob 2026-11-09, Quorra table: 'TESTED: ... that is my general knowledge, not checked here') ----------
_TESTED_HEDGE = re.compile(r"general knowledge|from memory|\bnot\s+(?:checked|tested|verified|measured)\s+here\b|"
                           r"\bmy (?:own )?(?:judge?ment|inference|guess)\b|\bI (?:did not|have not|haven't) (?:test|check|verify|measure)\b", re.I)


def check_tested_hedge(text):
    """REC-TESTED-HEDGE. check_untested_rec only looks for the word TESTED anywhere in the Recommendation cell, so a cell that
    begins TESTED and then says the recommendation itself was not checked passes. Fail it: the recommendation must rest on the
    measured result, or the cell must be labelled UNTESTED and the row moved under BLOCKED:."""
    for m in _REC_ROW.finditer(text):
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) != 6:
            continue
        rec = cells[3]
        if re.search(r"\bTESTED\b", rec) and not re.search(r"\bUNTESTED\b", rec):
            h = _TESTED_HEDGE.search(rec)
            if h:
                fail("REC-TESTED-HEDGE", "Recommendation cell says TESTED and also %r: %r. A cell cannot be both. Test the claim the "
                     "recommendation rests on, or drop that claim from the recommendation." % (h.group(0), rec[:120]))
                return

# ---------- 4. FILLER ----------
FILLER = [r"hope this helps", r"i.d be happy to", r"let me know if", r"feel free to",
          r"^let me\b", r"^now i.ll\b", r"^i.ll now\b", r"great question", r"in summary,",
          r"to summarize", r"as (?:we|you) (?:discussed|mentioned) (?:above|earlier)"]
FILLER_RE = [(p, re.compile(p, re.I | re.M)) for p in FILLER]


def check_filler(text):
    for p, rx in FILLER_RE:
        m = rx.search(text)
        if m:
            warn("FILLER", "phrase %r - survives a topic swap, cut it." % m.group(0))


# ---------- 5. LABEL RESOLUTION ----------
LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*|])\s+(.*)$", re.M)
LABEL = re.compile(r"\*\*([^*]{3,60})\*\*|\b([A-Z][A-Z0-9 \-]{5,50}[A-Z0-9])\b")


def next_steps_block(text):
    """*** THIS RETURNED EMPTY ON ALMOST EVERY REPLY, SO LINK-REGISTRY NEVER RAN. ***

    MEASURED 2026-08-27 after Rob asked whether the links in a table were accurate. The
    block was found by looking for a PROSE PHRASE - "next steps", "blocked on me", "you can
    do now", "stack rank". SUMMARY-SPEC does not require any of those words; the table is
    identified by its HEADER ROW. So the gate fired only when a reply happened to contain a
    trigger phrase somewhere, and returned early otherwise - silently, with no url examined.
    LINK-REGISTRY is explicitly FAIL-CLOSED, and this made it fail OPEN by never reaching
    its own logic. A gate that cannot find its input is indistinguishable from a clean pass.

    The table header is the reliable anchor and it is what the spec actually mandates."""
    m = re.search(r"(?is)\n[^\n]*(next steps?|blocked on me|you can do now|stack.rank)[^\n]*\n(.*)$", text)
    if m:
        return m.group(2)
    t = re.search(r"(?im)^\|\s*#\s*\|\s*Item\s*\|.*$", text)
    return text[t.start():] if t else ""


LINK_REGISTRY = pathlib.Path.home() / "Claude/Improving-my-Claude/LINK-REGISTRY.tsv"
# *** computer:// ADDED 2026-08-26, CAUGHT BY ROB: "Where is the link?" ***
# REVIEW-LINK demands a URL on any next-steps row naming something Rob must open, and this
# pattern accepted ONLY http(s). Files that exist only on the laptop - EDIT-LOG.tsv,
# log-edit.sh, everything under bin/ - have no Drive copy and therefore no http URL, so such
# a row COULD NOT BE MADE TO PASS. Measured before fixing: adding the correct
# computer:///Users/robk/... citation left REVIEW-LINK failing and merely changed the name it
# printed. A gate that cannot be satisfied by the correct answer pressures the writer toward
# the wrong one - omitting the link - which is exactly what happened, and Rob caught it rather
# than the gate. computer:// is the citation form the Cowork interface renders for local files.
URL_RX = re.compile(r"(?:https?|computer)://[^\s)\]|]+")



BLOCK_HEAD = re.compile(r"^\*\*\d+\.\s.+\*\*\s*[-\u2014]\s*\S", re.M)


def check_block_render(text):
    """*** THE NEXT-STEPS BLOCKS RENDERED AS A WALL. ADDED 2026-09-01. ***

    Rob: "Why is the formatting for the next steps messed up again???" - and the source was
    exactly what SUMMARY-SPEC specified, which is why no gate caught it. The spec's block was
    four consecutive lines with no blank line and a last line starting with '+'. In CommonMark
    a single newline is a SOFT break, so the labelled lines collapse into one paragraph, and a
    '+' at line start opens a LIST with no blank line before it, which is malformed.

    EVERY EXISTING GATE CHECKED THAT THE FIELDS WERE PRESENT. None could see that they were
    present and unreadable. A gate that reads source and never renders it is blind to exactly
    this class, so this one encodes the two rendering rules directly.
    """
    tail = next_steps_block(text)
    if not tail:
        return
    lines = tail.split("\n")
    for i, ln in enumerate(lines):
        if re.match(r"^\s*\+\s", ln) and i and lines[i - 1].strip():
            fail("BLOCK-RENDER", "a '+' line follows a non-blank line at %r. A '+' at line start "
                 "is a list marker and needs a blank line before it, or it renders malformed. "
                 "Write the field as '- Pros / Cons: ... / ...' inside the block's bullet list."
                 % ln.strip()[:52])
        if BLOCK_HEAD.match(ln) and i + 1 < len(lines) and lines[i + 1].strip():
            fail("BLOCK-RENDER", "the block header %r is followed immediately by text with no "
                 "blank line, so its fields collapse into one paragraph. Put a blank line after "
                 "the header and one bullet per field." % ln.strip()[:52])

# *** PORTABLE MODE, 2026-10-14, ROB: "The checker can't verify links in the watchdog's report,
# because its list of known links only works on your Mac." *** LINK-REGISTRY.tsv proves a link
# against /Users/robk paths, so off the Mac every link failed. LINK-MANIFEST.tsv is written ON THE
# MAC by build_manifest.py: the same anchor / one-title / fetch-method verdicts, per (url, label),
# plus every Drive item under the two project folders keyed by its Drive ID. Portable mode looks
# links up there. ON THE MAC, WITH REPLYCHECK_PORTABLE UNSET AND THE REGISTRY PRESENT, NOTHING
# BELOW RUNS. A link absent from the manifest FAILS; a missing or stale manifest FAILS.
LINK_MANIFEST = pathlib.Path(os.environ.get("REPLYCHECK_MANIFEST")
                             or pathlib.Path(__file__).resolve().with_name("LINK-MANIFEST.tsv"))
MANIFEST_MAX_AGE_H = 8 * 24
_MDRIVE_ID = re.compile(r"/(?:file/d|document/d|spreadsheets/d|presentation/d|folders)/"
                        r"([A-Za-z0-9_-]{10,})|[?&]id=([A-Za-z0-9_-]{10,})")


def _link_portable():
    return (os.environ.get("REPLYCHECK_PORTABLE") == "1"
            or (not LINK_REGISTRY.exists() and LINK_MANIFEST.exists()))


def _mkey(u):
    m = _MDRIVE_ID.search(u)
    return (m.group(1) or m.group(2)) if m else u.rstrip("/")


# NOT NAMED check_*: the selftest derives ALL from single-argument check_ functions and would
# call this on every fixture, failing 4 Mac-path controls wherever no manifest sits beside the
# checker (measured 2026-10-14 on the 0.2.5 build). It runs only through check_link_registry.
def _link_manifest_check(text):
    """LINK-REGISTRY, portable: the Mac's verdicts read from LINK-MANIFEST.tsv by Drive ID."""
    import datetime as _dt
    tail = next_steps_block(text)
    if not tail:
        return
    urls = set(URL_RX.findall(tail))
    rows, reg_labels, gen = {}, {}, None
    if LINK_MANIFEST.exists():
        for ln in LINK_MANIFEST.read_text(encoding="utf-8").splitlines():
            g = re.match(r"# LINK-MANIFEST\.tsv - generated (\S+)", ln)
            if g:
                gen = g.group(1)
            if ln.startswith("#") or ln.startswith("key\t"):
                continue
            c = ln.split("\t")
            if len(c) < 11:
                continue
            rows.setdefault(c[0], {})[c[1]] = (c[7], c[8], c[2])
            if c[6] == "registry":
                reg_labels.setdefault(c[1], c[0])
    # Same LABEL-NAMED-UNLINKED and FILENAME-UNLINKED rules as the Mac path, labels from the manifest.
    linked = {m.group(1).strip() for m in
              re.finditer(r"\[([^\]]{3,80})\]\((?:https?://|computer://)[^)]+\)", tail)}
    _prose = re.sub(r"\]\((?:https?://|computer://)[^)]+\)", "]", tail)
    for lab in reg_labels:
        if lab not in linked and re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(lab), _prose):
            fail("LINK-REGISTRY", "LABEL-NAMED-UNLINKED: %r is named in this reply and has a "
                 "registered url, but nothing links it. (portable)" % lab[:44])
    for fm in re.finditer(r"[\w][\w ().,+-]{2,70}\.(?:pdf|csv|tsv|xlsx|docx)\b", tail):
        seg = tail[max(0, fm.start() - 220): fm.end() + 220]
        if not re.search(r"\[[^\]]*\]\((?:https?://|computer://)[^)]+\)", seg):
            fail("LINK-REGISTRY", "FILENAME-UNLINKED: %r is named with no link anywhere near it. "
                 "(portable)" % fm.group(0).strip()[:52])
    if not urls:
        return
    if not rows:
        fail("LINK-REGISTRY", "PORTABLE: %d url(s) used and LINK-MANIFEST.tsv is missing or empty "
             "at %s. No url can be verified off the Mac without it." % (len(urls), LINK_MANIFEST))
        return
    try:
        age_h = (_dt.datetime.now(_dt.timezone.utc) - _dt.datetime.strptime(
            gen, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)).total_seconds() / 3600
    except Exception:
        age_h = None
    if age_h is None or age_h > MANIFEST_MAX_AGE_H:
        fail("LINK-REGISTRY", "PORTABLE MANIFEST-STALE: LINK-MANIFEST.tsv generated %s, older than "
             "%d h or undated. Regenerate it on the Mac." % (gen, MANIFEST_MAX_AGE_H))
    for m in re.finditer(r"\[([^\]]{3,80})\]\((https?://[^)]+)\)", tail):
        lab, u = m.group(1).strip(), m.group(2).strip().rstrip("/")
        k = _mkey(u)
        if k not in rows:
            fail("LINK-REGISTRY", "PORTABLE url not in manifest: %s - not registered and not a "
                 "Drive item under the walked folders." % u[:88])
        elif lab not in rows[k]:
            fail("LINK-REGISTRY", "PORTABLE label/target mismatch: %r is linked to %s, approved "
                 "only for %s." % (lab[:44], k[:40], sorted(rows[k])[:2]))
        elif rows[k][lab][0] != "OK":
            fail("LINK-REGISTRY", "PORTABLE %s: %r (verdict recorded on the Mac)"
                 % (rows[k][lab][0], lab[:44]))
        elif rows[k][lab][1] != "Y":
            fail("LINK-REGISTRY", "TITLE-UNFETCHED: %r uses a url whose verified_title was not "
                 "read from the target. (portable)" % lab[:44])
    bare = urls - {m.group(1).strip() for m in re.finditer(r"\[[^\]]+\]\((https?://[^)]+)\)", tail)}
    for u in sorted(bare):
        if _mkey(u) not in rows:
            fail("LINK-REGISTRY", "PORTABLE unverified bare url: %s" % u[:88])


def check_link_registry(text):
    """*** THREE LINK DEFECTS IN THREE TURNS, EVERY ONE FOUND BY ROB AND NONE BY A GATE. ***
    REVIEW-LINK asks whether a URL is present. LINK-REUSE asks whether one URL serves several
    rows. NEITHER RESOLVES THE TARGET, so a row labelled "P2-22 BUNDLED-SKILL RULING" pointing
    at AUDIT-PROTOCOL.md passed clean three replies running, and a link that REDIRECTS to a
    different page passed too.

    Resolving at reply time would need the network, which this checker does not have and should
    not want. So the verification moves EARLIER: a URL may appear in a next-steps table only if
    it is already in LINK-REGISTRY.tsv, where it was recorded after being loaded and its title
    read. The gate then needs no network - it only asks whether the homework was done.

    FAIL-CLOSED: a missing registry means NO url may be used, never all of them."""
    if _link_portable():
        return _link_manifest_check(text)
    tail = next_steps_block(text)
    if not tail:
        return
    urls = set(URL_RX.findall(tail))

    # *** A REGISTERED LABEL NAMED WITHOUT ITS LINK. ADDED 2026-09-01, AFTER ROB ASKED
    # "Where is the link to the fucking sheet???" *** Three substantive replies that day named
    # SPOT-CHECK SHEET; the first two carried its url and the third did not - and the third was
    # the one he was reading when he went looking. Every other registry check guards a link that
    # IS present. None of them fires when the link is simply absent.
    # *** THIS RUNS BEFORE THE no-urls RETURN, AND THAT PLACEMENT IS THE WHOLE CHECK. ***
    # Written below it first, where it passed its own selftest by never executing: the function
    # returns early exactly when a reply contains no url, which is the defect. A check placed
    # after the return that the defect triggers cannot ever see the defect.
    if LINK_REGISTRY.exists():
        known = {}
        for ln in LINK_REGISTRY.read_text(encoding="utf-8").splitlines():
            if ln.startswith(("http", "computer://")):
                c = [x.strip() for x in ln.split("\t")]
                if len(c) >= 3 and c[2]:
                    known.setdefault(c[2], c[0])
        linked = {m.group(1).strip() for m in
                  re.finditer(r"\[([^\]]{3,80})\]\((?:https?://|computer://)[^)]+\)", tail)}
        # *** A LINK TO THE FILE MADE THIS CHECK FAIL, MEASURED 2026-09-20 ON A LIVE REPLY. ***
        # The search below ran over the RAW tail, urls included, so a row linked to
        # computer://.../instructions-backup/verify.sh contained the literal string verify.sh
        # inside its own href and was reported as naming the file with nothing linking it. The
        # only way to satisfy it was to delete the link, which inverts the check. Link TARGETS
        # are addresses, not prose, so they are stripped before the prose is searched; link TEXT
        # is kept, because a label named in link text still has to be the linked one.
        _prose = re.sub(r"\]\((?:https?://|computer://)[^)]+\)", "]", tail)
        for lab in known:
            if lab in linked:
                continue
            if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(lab), _prose):
                fail("LINK-REGISTRY", "LABEL-NAMED-UNLINKED: %r is named in this reply and has a "
                     "registered url, but nothing links it. If you are asking Rob to go and read "
                     "it, give him the link in the same breath." % lab[:44])

    # *** A FILENAME NAMED WITH NO LINK. ADDED 2026-09-01 AFTER "WHERE ARE THE LINKS????" ***
    # LABEL-NAMED-UNLINKED only fires for a label ALREADY in the registry, so a reply naming a
    # file that was never registered passed clean - which is exactly what happened: two statement
    # PDFs were named as the thing to go and check, with nothing to click. The registry cannot be
    # the trigger, because the failure is that the file is NOT in it. THE FILENAME ITSELF IS.
    for fm in re.finditer(r"[\w][\w ().,+-]{2,70}\.(?:pdf|csv|tsv|xlsx|docx)\b", tail):
        fn = fm.group(0).strip()
        seg = tail[max(0, fm.start() - 220): fm.end() + 220]
        if re.search(r"\[[^\]]*\]\((?:https?://|computer://)[^)]+\)", seg):
            continue
        fail("LINK-REGISTRY", "FILENAME-UNLINKED: %r is named with no link anywhere near it. "
             "If Rob has to open it, give him the link in the same breath - and if it is not in "
             "LINK-REGISTRY.tsv yet, look it up and record it rather than naming it bare." % fn[:52])

    if not urls:
        return
    if not LINK_REGISTRY.exists():
        fail("LINK-REGISTRY", "%d url(s) used and LINK-REGISTRY.tsv does not exist. A url is a "
             "claim about where it points; record it there after loading it." % len(urls))
        return
    # *** COLUMN 3 IS THE POINT. The first version of this check read column 1 only, so it
    # asked "is this URL known" while claiming to ask "does this URL match the row". It then
    # passed a row labelled DELETE THE TEN PHASE COWORKS pointing at the captures folder, one
    # reply after I told Rob it would stop exactly that. A URL is approved FOR A LABEL. ***
    # *** FOURTH LINK FAILURE, 2026-08-26, AND IT WAS THIS REGISTRY'S OWN. ***
    # Rob asked where [THE FOUR GENERATED GIANTS](.../1bEdDmlE...) pointed. That id is
    # AUDIT-SCRATCHPAD.md. SIX labels were bound to it and TWO recorded the verified_title as
    # "HANDREAD-WORKLIST.tsv" - A TITLE NEVER FETCHED, TYPED FROM MEMORY BY THE AUTHOR.
    # The label->url binding passed because the author writes the binding. A GATE CANNOT CATCH A
    # WRONG BELIEF WHEN THE AUTHOR SUPPLIES THE GROUND TRUTH; it could only ever catch a typo.
    # Root cause: HANDREAD-WORKLIST.tsv was not in Drive at all, so no correct url existed and
    # every "HAND-READ THE..." link borrowed the nearest plausible id.
    # TWO NEW INVARIANTS, both about the REGISTRY rather than the reply:
    #   TITLE-CONTRADICTION - one url may serve many labels but must carry ONE verified_title.
    #   TITLE-UNFETCHED     - column 5 must begin with a NAMED FETCH METHOD, so the title was
    #                         READ FROM THE TARGET rather than typed. "drive-api" was the only
    #                         accepted method until 2026-09-10, which made the check unusable
    #                         for every target that is not a Drive file: a claude.ai artifact, a
    #                         Google Maps route and a retailer order page each hit it in one
    #                         session, and the only ways past were to type "drive-api" (a lie)
    #                         or to drop the link Rob had asked for. THE INVARIANT IS PROVENANCE,
    #                         NOT DRIVE. Widening the method list keeps the invariant and stops
    #                         the gate forcing a false entry, which is the failure mode it was
    #                         built to prevent in the first place.
    allowed, titles, fetched, anchors = {}, {}, {}, {}
    for ln in LINK_REGISTRY.read_text(encoding="utf-8").splitlines():
        # *** computer:// ROWS WERE NEVER LOADED. FOUND 2026-08-26 BY THE GATE FAILING ON MY
        # OWN REGISTRATION. *** HAS_LINK was taught to accept computer:// so a local-only file
        # could be cited at all; THIS reader was left on http, so every computer:// row written
        # into the registry sat there unread and its url still reported as an unverified bare
        # url. A HALF-APPLIED CHANGE IS WORSE THAN NEITHER HALF: it looks registered and is not.
        if ln.startswith(("http", "computer://")):
            c = [x.strip() for x in ln.split("\t")]
            if len(c) >= 3 and c[2]:
                u = c[0].rstrip("/")
                allowed.setdefault(u, set()).add(c[2])
                if len(c) >= 2 and c[1]:
                    titles.setdefault(u, set()).add(c[1])
                fetched[u] = fetched.get(u, True) and (len(c) >= 5 and c[4].startswith(TITLE_FETCH_METHODS))
                if len(c) >= 7 and c[5] and c[6]:
                    anchors.setdefault(u, []).append((c[2], c[5], c[6]))
    # *** CONTENT ANCHOR, ADDED 2026-08-26 AFTER THE FIFTH LINK QUESTION FROM ROB. ***
    # The registry already checked: is this url known, does this LABEL own it, was the title
    # FETCHED, does one url carry two titles. IT NEVER CHECKED WHETHER THE LABEL DESCRIBES THE
    # FILE. Twenty minutes after building those checks I registered "THE FORMAT RULING" against
    # AUDIT-PROTOCOL.md - a file containing ZERO occurrences of that ruling - because its id was
    # already API-verified and convenient. Every existing check passed it: one url, one title,
    # fetched, label bound. THE AUTHOR WRITES THE BINDING, SO THE ONLY THING THAT CAN FALSIFY IT
    # IS THE TARGET'S OWN CONTENT.
    # COLUMN 6 is a LOCAL path, COLUMN 7 a literal string that must appear in it. No network:
    # the local file and the Drive file are the same object wherever the project symlinks them,
    # and where they are not, the anchor still proves the label matches the text it names.
    for u, rows_ in anchors.items():
        for lab, relpath, anchor in rows_:
            # NO-LOCAL-ANCHOR is a DECLARED exemption for a target with no local text: a Google
            # Doc or Sheet (the mirror holds a 177-byte pointer), a claude.ai page, a Drive
            # FOLDER, or a file deliberately deleted. Column 7 must then carry the REASON, so
            # the exemption is a recorded decision rather than a silent gap. A row with neither
            # an anchor nor a reason is refused below by the same code that refuses a bad anchor.
            if relpath == "NO-LOCAL-ANCHOR":
                if not anchor.strip():
                    fail("LINK-REGISTRY", "ANCHOR-EXEMPT-NO-REASON: %r claims no local anchor and "
                         "gives no reason. An exemption without a reason is a gap." % lab[:40])
                continue
            if relpath.startswith("DRIVE:"):
                f = pathlib.Path.home() / "Google Drive" / relpath[len("DRIVE:"):]
            elif relpath.startswith("/"):
                # An ABSOLUTE column-6 path is taken as given. The relative form assumes a
                # ~/Claude root, which is wrong for anything outside it and silently resolves
                # to a path that does not exist - an anchor that cannot be read fails the row.
                f = pathlib.Path(relpath)
            else:
                f = pathlib.Path.home() / "Claude" / relpath
            f = pathlib.Path(_drive_resolve(str(f)) or f)
            if not f.exists():
                fail("LINK-REGISTRY", "ANCHOR-UNRESOLVABLE: %r names %s and that file is not on "
                     "disk, so the label cannot be checked against its target." % (lab[:40], relpath))
                continue
            try:
                body = f.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                fail("LINK-REGISTRY", "ANCHOR-UNREADABLE: %s (%s)" % (relpath, e)); continue
            if anchor not in body:
                fail("LINK-REGISTRY", "ANCHOR-ABSENT: %r is registered against %s, but that file "
                     "does NOT contain %r. The label does not describe the target."
                     % (lab[:40], relpath, anchor[:48]))
    for u, ts in titles.items():
        if len(ts) > 1:
            fail("LINK-REGISTRY", "TITLE-CONTRADICTION: %s is recorded under %d different "
                 "titles %s. One of them was typed rather than fetched."
                 % (u[:70], len(ts), sorted(ts)))
    for m in re.finditer(r"\[([^\]]{3,80})\]\((https?://[^)]+)\)", tail):
        lab, u = m.group(1).strip(), m.group(2).strip().rstrip("/")
        if u not in allowed:
            fail("LINK-REGISTRY", "url not verified: %s - load it, read the target title, and "
                 "record it in LINK-REGISTRY.tsv before using it." % u[:88])
        elif lab not in allowed[u]:
            fail("LINK-REGISTRY", "label/target mismatch: %r is linked to a url approved only "
                 "for %s. A url is approved FOR A LABEL, not in general."
                 % (lab[:44], sorted(allowed[u])[:2]))
        elif not fetched.get(u, False):
            fail("LINK-REGISTRY", "TITLE-UNFETCHED: %r uses a url whose verified_title was not "
                 "read from the target. Fetch the target's title, write it into column 2 and "
                 "record how it was read in column 5, starting with one of %s, "
                 "before using this link." % (lab[:44], ", ".join(TITLE_FETCH_METHODS)))
    bare = urls - {m.group(1).strip() for m in re.finditer(r"\[[^\]]+\]\((https?://[^)]+)\)", tail)}
    for u in sorted(bare):
        if u.rstrip("/") not in allowed:
            fail("LINK-REGISTRY", "unverified bare url: %s" % u[:88])


# *** TABLE-SHAPE. ADDED 2026-09-01 AFTER THE FORMAT WAS BROKEN A FOURTH TIME. ***
#
# WHAT HAPPENED, AND THE MECHANISM IS THE FINDING, NOT THE FORMAT. Rob asked "Why do we have
# this format again??????" over a table headed # / Decision / What it unblocks / My
# recommendation. SUMMARY-SPEC has said since 2026-08-25, ruled by Rob with a screenshot of
# the rendering in front of him, that the live shape is:
#     | # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |
#
# THE DRAFT THAT WAS GATED HAD THE RIGHT HEADER AND PASSED. The reply Rob actually received
# did not, because it was written under the ZERO TOOL CALLS rule - his instruction that a
# reply to "can you increase the confidence level?" contains no tool calls at all. replycheck
# IS a tool call. So the one reply shape guaranteed to carry a hand-built summary table is the
# one shape that is structurally ungated, and no amount of care inside it changes that.
#
# WHY A HEADER CHECK RATHER THAN ANOTHER RULE. Four format failures now, each corrected in
# prose, each recurring. SUMMARY-SPEC's own history records Claude overriding the column list
# twice in one day, dropping Recommendation a third time by reading a budget list that was
# missing it, and this is the fourth. Prose has had four attempts. The header row is one
# string and comparing it is one line.
#
# THE ONLY LEGAL SHAPE IS THE SIX. The three-column layout further down SUMMARY-SPEC is kept
# as the record of the ruling it REPLACES, under a banner saying that implementing it is the
# mistake the banner exists to stop - so it is not accepted here.
SPEC_COLS = ["#", "issue / risk", "action", "owner", "recommendation", "pros", "cons"]
# 0.2.9, R291 (Rob 2026-10-15 11:12 PDT): "Recommendation (renamed from Claude's Recommendation)". The old
# name is still accepted here so stored replies are not re-failed; OBJECTIVE-SECTIONS fails it in new replies.
SPEC_COLS_OLD = ["#", "issue / risk", "action", "owner", "claude's recommendation", "pros", "cons"]
# CHANGED 2026-10-04 22:15 PDT on Rob's "Go": SUMMARY-SPEC's live header, ruled by Rob 2026-10-04 in Cowork,
# replaced the 2026-08-25 six-column one. The old header is no longer accepted.
TABLE_HDR = re.compile(r"(?m)^\|\s*#\s*\|.*\|\s*$")



# *** PROBE-MISSING. F-076, BUILT 2026-09-02 AFTER DAMAGING A LIVE GOOGLE DOC. ***
#
# WHAT HAPPENED. Typing into a Google Doc, cmd+Up silently did not move the caret, so 1,807
# characters went into the MIDDLE OF THE WORD "WHO". Then a screenshot showing no banner was
# explained away as stale. Then forty undo presses were assumed to have gone to a dialog that
# did not have focus. Then a scroll returned "the pane may be stuck" and I kept going. Rob had
# to restore the document from version history.
#
# WHY THE EXISTING STOP RULE DID NOT FIRE, AND THIS IS THE WHOLE DESIGN PROBLEM. It carries a
# SYNTACTIC form - no computer click may follow a javascript read inside the same batch - and
# every one of those calls was a SEPARATE round trip, so the form was satisfied throughout while
# the behaviour it exists to produce was violated four times running. A PER-BATCH RULE CANNOT
# SEE A STREAK, which is why this one keys on the CLAIM rather than on call shape.
#
# THE CHEAP MECHANISM THAT WORKS, PROVEN THE SAME DAY. In a canvas editor there is no field to
# read back BEFORE writing, so the pre-write check is a HARMLESS SELECTION: shift+Right a few
# times and confirm the highlight renders. That settled focus, keystroke delivery AND caret
# position together, before a single character was typed. NOT cmd+A - the auto-mode classifier
# blocked it, correctly, since in a document editor that is one keystroke from replacing all.
CANVAS_EDIT = re.compile(
    r"(?:typed|typing|wrote|inserted|pasted|prepended|appended)[^.\n]{0,80}"
    r"(?:google doc|the doc\b|document|canvas|textarea|editor)",
    re.I)
# BROADENED 2026-09-02 BY THE SAME CORPUS RUN. It flagged a reply saying "verified after a
# full page reload rather than by the absence of an error" as having no verification. A page
# reload IS the server-side re-read this check is asking for; my vocabulary just did not know
# the words. A false positive on a reply that did the right thing is the worst kind.
PROBE_EVIDENCE = re.compile(
    r"shift\+right|selection probe|focus probe|highlighted"
    r"|read back|read it back|download_file_content|drive connector|server-side|re-read"
    r"|page reload|reloaded|verified after|hash", re.I)



# *** PREDICTION-MISSING. Enforces the rule Rob adopted 2026-09-02, scoped to UI actions. ***
#
# THE RULE: "BEFORE ANY UI OR BROWSER ACTION, WRITE WHAT YOU EXPECT IT TO PRODUCE, THEN COMPARE
# THE RESULT AGAINST IT." It exists because the STOP rule it sits beside is per-batch, and on
# 2026-09-02 four separate round trips each satisfied that form while the behaviour it protects
# was violated four times running, ending in a damaged Google Doc Rob had to restore.
#
# WHY A PREDICTION AND NOT MORE CARE. A per-batch rule cannot see a STREAK. A written prediction
# can, because the second mismatch is visible against the first instead of being explained away
# one at a time. Measured on the day it was adopted: ten predictions written, five missed, and
# every miss found something no other check was going to find - a 1,995-byte stale backup on the
# most important field in the system, Chrome's real download directory, an audit input with no
# existence guard, a download that silently never completed, and a gate of mine that was nearly
# blind because it could not match across differently-wrapped files.
#
# WHAT THIS FAILS: a reply that claims a UI or browser action and contains no stated prediction.
# It cannot check whether the prediction was HONEST or whether the comparison was actually made -
# that stays judgement. It removes the cheapest way to skip the rule, which is silence.
# *** NARROWED 2026-09-02 AFTER A CORPUS RUN, AND THE FIRST VERSION WAS UNSHIPPABLE. ***
# Measured against 2,398 real assistant messages on disk: the first pattern fired on 707 of
# them, 29.5%. It matched a MENTION of Chrome or a tab, not an action performed. A check that
# fires on a third of replies is the permanently-red auditor this project already documents as
# training its reader to ignore it. It now requires a FIRST-PERSON PERFORMED action.
UI_ACTION = re.compile(
    r"\bI (?:clicked|navigated|typed|pressed|scrolled|dragged)\b"
    r"|\b(?:clicked|pressed|typed) (?:at|into|on) \b"
    r"|\btook a screenshot\b|\bshift\+right\b", re.I)
# \bprediction\b MISSED THE PLURAL. Found 2026-09-02 by running this check against REAL
# replies rather than fixtures alone: a reply saying "Three predictions today, two missed"
# was flagged as stating none, because the word boundary after "prediction" excludes the
# "s". FOURTH TIME IN ONE DAY A CHECK OF MINE PASSED ITS CONTROLS AND FAILED ON REAL TEXT,
# and every one was a SHAPE assumption - wrapping, casing, now inflection - never content.
PREDICTION = re.compile(r"\bpredict\w*|\bI expect\b", re.I)


def check_prediction(text):
    """A claimed UI or browser action with no stated prediction anywhere in the reply."""
    if not UI_ACTION.search(text):
        return
    if PREDICTION.search(text):
        return
    m = UI_ACTION.search(text)
    fail("PREDICTION-MISSING",
         "this reply claims a UI or browser action (%r) and states no prediction. Rob adopted the "
         "rule on 2026-09-02, scoped to UI actions: write what you expect the action to produce "
         "BEFORE it runs, then compare. The STOP rule beside it is per-batch and cannot see a "
         "streak; a written expectation can, because the second mismatch is visible against the "
         "first." % text[m.start():m.start() + 40])



# *** OPEN-ROW-LINK. F-078, 2026-09-02. THE GATE I DEFEATED BY REWORDING. ***
#
# WHAT HAPPENED, FROM MY OWN DRAFTS. REVIEW-LINK failed with "3 table row(s) name something Rob
# has to open and carry NO url: row 3 (ledger), row 4 (CLAUDE.md), row 6 (SKILL.md)". I then
# edited those three Item cells to read "the order they were recorded", "the global file" and
# "Scheduled-task instruction files". The trigger words were gone, the gate reported 0 FAIL, AND
# THE LINKS WERE STILL MISSING. Rob caught it: "WHY ARE THE LINKS TO THE THINGS I NEED TO REVIEW
# NOT INCLUDED IN THE 2ND COLUMN??? PLEASE CAPTURE THIS ONGOING MISTAKE".
#
# *** REVIEW-LINK KEYS ON VOCABULARY, AND VOCABULARY IS THE ONE THING THE AUTHOR CONTROLS FOR
# FREE. *** That is the hole, and it is not specific to links - every gate here that matches on
# WORDS rather than STRUCTURE can be silenced the same way, by the person it is meant to catch.
#
# THIS ONE KEYS ON STRUCTURE. Any row whose Status says Open must carry a URL, whatever words the
# row uses. There is nothing to reword: deleting "ledger" does not make the row un-open.
#
# THE ESCAPE HATCH IS DELIBERATE, EXPLICIT AND COUNTABLE. Some open rows genuinely have no
# artifact - a decision, a phone call. Those carry the literal token NO-ARTIFACT, which is
# greppable, so an escape is visible in the reply and can be counted later. An invisible
# exemption is what this whole failure was.
# OPEN_STATUS was removed 2026-09-02 with the widening to every row. It is recorded here
# rather than deleted silently: keying on the word "open" was the narrower rule that would
# have let the measured P8-18 case pass, because that row was not open.


OWNER_PRONOUN = re.compile(r"^\s*(me|you|mine|yours|myself|yourself|i)\s*$", re.I)


# *** TEST-FIELD. R065, ROB 2026-09-20. *** The 2026-09-20 audit graded 571 next-steps rows:
# of 280 real recommendations, 164 named no way to tell whether they worked, and 57 were later
# found wrong. A recommendation with no falsifier is an opinion with a table row around it.
# TWO CLAUSES ARE REQUIRED AND EACH FAILS SEPARATELY: "Test:" must name something RUNNABLE - a
# script, a gate, a count with a number, or a date - and "Fails if:" must name the result that
# would show the recommendation was wrong. "Test: verify it worked" is refused; so is a Fails-if
# that only restates the Test, measured by token overlap rather than by reading it.
# A NOOP ROW IS EXEMPT AND MUST SAY SO IN ITS OWN CELL ("None", "Nothing", "No change"), which
# converts a silent omission into a written claim - the OPEN-ROW-LINK lesson.
_NOOP_REC = re.compile(r"^\s*\**\s*(none|nothing\b|no change|not until|n/?a|-|\u2014)", re.I)
_TEST_CLAUSE = re.compile(r"\btest\s*:\s*(.+?)(?=\bfails? if\s*:|$)", re.I | re.S)
_FAILS_CLAUSE = re.compile(r"\bfails? if\s*:\s*(.+?)(?=\btest\s*:|$)", re.I | re.S)
# RUNNABLE means a reader could go and run it: a file, a named gate, a number, or a date.
_RUNNABLE = re.compile(r"(\b[\w./-]+\.(?:py|sh|tsv|md)\b|\bbin/|\bgate\b|\bselftest\b|"
                       r"\breport\b|\bprints?\b|\d)", re.I)


_NEGATORS = {"or", "more", "less", "under", "over", "not", "no", "fewer", "above", "below",
             "at", "least", "most", "than", "still", "does", "do", "n", "t", "fails", "fail",
             "instead", "same", "any", "it", "the", "a", "is", "are", "was", "were", "be"}


def _restates(test, fails):
    """True when Fails-if adds no NEW content word to the Test - the same sentence negated.

    *** THE FIRST VERSION USED A JACCARD THRESHOLD AND ITS OWN CONTROL FAILED, 2026-09-20. ***
    "under 6 per 10" against "6 or more per 10" scores 0.7, below any threshold loose enough to
    be safe, and a threshold high enough to catch it also catches honest pairs. WORD OVERLAP IS
    THE WRONG INSTRUMENT: what makes a Fails-if real is that it names something the Test does
    not. So the test is set difference, with comparison words excluded."""
    wt = set(re.findall(r"[a-z]+", test.lower()))
    wf = set(re.findall(r"[a-z]+", fails.lower()))
    return not (wf - wt - _NEGATORS)


def check_test_field(text):
    """Every recommendation carries a runnable Test and a Fails-if, or says it is a no-op."""
    hdr = _header_map(text)
    ri = None
    if hdr:
        m = re.search(r"^\|\s*#\s*\|(.+)\|\s*$", text, re.M)
        names = [c.strip().lower() for c in m.group(1).split("|")] if m else []
        for i, n in enumerate(names):
            if "recommend" in n:
                ri = i
                break
    missing_test, hollow, missing_fails, restated = [], [], [], []
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if len(cells) < 4:
            continue
        rec = cells[ri] if ri is not None and ri < len(cells) else cells[-2]
        if _NOOP_REC.match(rec):
            continue
        t = _TEST_CLAUSE.search(rec)
        f = _FAILS_CLAUSE.search(rec)
        rank = m.group(1)
        if not t:
            missing_test.append(rank)
            continue
        if not _RUNNABLE.search(t.group(1)):
            hollow.append((rank, t.group(1).strip()[:40]))
        if not f or len(f.group(1).strip()) < 15:
            missing_fails.append(rank)
        elif _restates(t.group(1), f.group(1)):
            restated.append(rank)
    if missing_test:
        fail("TEST-FIELD", "%d recommendation(s) name no Test: rows %s. A recommendation with no "
             "way to tell whether it worked is what the 2026-09-20 audit found in 164 of 280 rows."
             % (len(missing_test), ", ".join(missing_test)))
    if hollow:
        fail("TEST-FIELD", "%d Test clause(s) name nothing runnable - no script, gate, number or "
             "date: %s. 'Verify it worked' is not a test."
             % (len(hollow), "; ".join("row %s (%s)" % x for x in hollow)))
    if missing_fails:
        fail("TEST-FIELD", "%d recommendation(s) name no 'Fails if:' clause: rows %s. A test that "
             "cannot fail measures nothing." % (len(missing_fails), ", ".join(missing_fails)))
    if restated:
        fail("TEST-FIELD", "%d 'Fails if:' clause(s) only restate the Test: rows %s. The failure "
             "condition must name a different result, not the same one negated by tone."
             % (len(restated), ", ".join(restated)))


# *** GATE-RATIO. 2026-09-20, and it is the conversion that converts the rest. ***
# bin/enforcecheck.py scored 73 recorded recommendations against this project's operating
# principle - replace rules enforced by Claude's judgement with checks that run in code:
# 15 named a gate that exists (20.5%), 6 asserted a file's contents, and 52 were promises
# about future behaviour with nothing that fails on its own. A rule saying "write more gates"
# would have been the 53rd promise. This is the check instead.
# THE THRESHOLD IS ARGUED, NOT PICKED: the measured baseline is 20.5% and the best single
# reply managed 3 of 8 (37.5%), so 40% sits above everything achieved so far and is reachable
# by converting one or two rows. It is deliberately not 100% - some rows are a decision or a
# one-off, and forcing those into fake gates produces noise that trains its reader to ignore
# the gate. IT MAY ONLY EVER MOVE UPWARD: lowering it to pass a reply is the silencing this
# project forbids.
# *** ROB-ROW. 2026-09-20, built after two Rob-owned rows in consecutive replies turned out not
# to be his. *** The first was invented outright to satisfy STOP-WHILE-UNBLOCKED. The second was
# real work with a real dead end, but the option offered was one this project's operating
# principle already rules out, which makes it a conclusion rather than a decision.
# THE EXISTING CHECK ASKS WHETHER A TOOL COULD DO IT. This asks a different question: does the
# recommendation actually ask Rob to DECIDE, APPROVE, or SUPPLY something only he has. A row
# telling him to read, check, look at or confirm something Claude could read is the shape his
# field calls "an incapability claim with the words removed".
# IT IS DELIBERATELY A WARNING AND NOT A FAILURE. The wording test is weak - a manufactured row
# written carefully passes it - so failing on it would teach rewording rather than honesty. It
# is here to make the shape visible at the moment it is written.
_ROB_ASK = re.compile(r"\b(approve|approval|rule on|ruling|decide|decision|your call|choose|"
                      r"pick one|say yes|sign|credential|password|permission|authorise|authorize|"
                      r"produce|supply|grant|turn on|add the line|tell me which)\b", re.I)
_ROB_READ_ONLY = re.compile(r"^\W*(read|check|look at|review|verify|confirm|see|open|run)\b", re.I)
# *** THE VOCABULARY TEST WAS DEFEATED BY ONE WORD, MEASURED 2026-09-20 THE DAY IT SHIPPED. ***
# Run against the three rows it was built for, stripped to their asks, it flagged 3 of 3. Run
# against the live reply it shipped in, it flagged 0 - because that row happened to contain the
# word "ruling" while asking for nothing Claude could not settle. A wording test cannot tell
# "asks for a ruling" from "says the word ruling".
# THE SECOND SIGNAL IS NOT VOCABULARY. If Claude states its own preferred answer inside a row it
# assigned to Rob, Claude had an answer - and a question you can answer is not a decision you
# route. This catches the live case the first signal missed.
_ROB_SELF_ANSWER = re.compile(r"\bI would\b|\bI'd\b|\bmy recommendation is\b|"
                              r"\bthe answer is\b|\bI think the right\b", re.I)


# *** THE OWNER TEST READ THE WHOLE ROW, MEASURED 2026-09-20 ON THE FIRST REPLY AFTER SHIPPING. ***
# _rec_rows returns (rank, item, rec, RAW ROW TEXT), and this filter handed that raw text to
# _is_rob, which is a substring test for "rob". So a CLAUDE-owned row warned because its
# recommendation contained the words "Rob row". The control "stays silent when the same wording
# is owned by Claude" passed only because its text never said Rob anywhere.
# THIS IS THE THIRD WRONG-CELL BUG IN ONE DAY - STANDING-QUOTE and GATE-RATIO both shipped
# reading an index that was not the cell they described. The cells know which one is the owner,
# so _owner_of reads them rather than the row.
def _rec_row_owner(raw):
    cells = [c.strip() for c in raw.split("|")]
    while cells and cells[-1] == "":
        cells.pop()
    return _owner_of(cells)[0]


def check_rob_row(text):
    rows = [r for r in _rec_rows(text) if _is_rob(_rec_row_owner(r[3]))]
    for r in rows:
        rec = r[2]
        if _ROB_SELF_ANSWER.search(rec):
            warn("ROB-ROW", "row %s is owned by Rob and the recommendation states Claude's own "
                 "preferred answer inside it: %r. If Claude has an answer, the row is usually "
                 "Claude's. This is the signal the vocabulary test missed on 2026-09-20."
                 % (r[0], _ROB_SELF_ANSWER.search(rec).group(0)))
            continue
        if _ROB_ASK.search(rec):
            continue
        warn("ROB-ROW", "row %s is owned by Rob but its recommendation asks for no decision, "
             "approval, credential or physical act: %r. Two rows in consecutive replies on "
             "2026-09-20 had this shape and neither was his. If the blocker is a rule rather "
             "than a missing capability, the answer is usually a conclusion Claude should state."
             % (r[0], rec[:70]))


def check_gate_ratio(text):
    rows = _rec_rows(text)
    if len(rows) < 4:
        return
    names = _known_gate_names()
    if len(names) < 20:
        warn("GATE-RATIO", "only %d gate names derived, which cannot be right - not scored "
             "rather than scored wrongly." % len(names))
        return
    # CELL INDEX 2 IS THE RECOMMENDATION. The first version read r[1], the Item label,
    # and its own control caught it - the same wrong-cell mistake STANDING-QUOTE made on
    # 2026-09-20. _rec_rows returns (row_no, item, rec, raw).
    gated = [r for r in rows if _names_a_gate(r[2], names)]
    ratio = len(gated) / len(rows)
    if ratio < _GATE_MIN:
        fail("GATE-RATIO", "%d of %d recommendation(s) name a gate that exists (%.0f%%, floor "
             "%.0f%%). The rest are promises about future behaviour, which this project measured "
             "at 3-6%% compliance. Convert one into a check, or say in the row why it cannot be."
             % (len(gated), len(rows), 100 * ratio, 100 * _GATE_MIN))


# *** RULINGS-CITED and STANDING-QUOTE. R066, ROB 2026-09-20 "Approve #1 and #2". ***
# RULINGS-CITED: the 2026-09-20 audit found ~8 of 51 misses were methods Rob had already ruled
# out - a retrieval failure, not a judgement one. bin/rulingmatch.py shortlists the 20 rulings
# nearest each recommendation and a reader names the ones that already decided it; this check
# only enforces that the reply SAYS what came back. "RULINGS CHECKED: R017, R057 - neither
# applies because ..." or "RULINGS CHECKED: none apply". A reply with no recommendation row is
# exempt, because there is nothing to check against.
# STANDING-QUOTE: 105 of 571 audited rows were standing-row boilerplate. A standing row may now
# say it has nothing to report, but only while quoting the output of its own command - a count,
# an id or a stamp - so an empty row costs a real run instead of a phrase.
_RULINGS_LINE = re.compile(r"^RULINGS CHECKED\s*:\s*(.+)$", re.M | re.I)
# R128, Rob 2026-09-30 07:10 PDT: three digits, not R0dd. Rulings passed R099 on 2026-09-2x and
# a line citing only R126 and R127 failed as "names no ruling id" (F-328).
_RULING_ID = re.compile(r"\bR\d{3}\b")
_STANDING = re.compile(r"PROCESS AUDIT|INSTRUCTION REVIEW|BLIND SPOTS|VOICE COMPLIANCE", re.I)
_NOTHING = re.compile(r"\bnothing this reply\b", re.I)
# R128: widened with the others for consistency. It has no control of its own and cannot have one:
# the \d alternative already matches any ruling id, so this alternative never decides a match.
_QUOTED_OUTPUT = re.compile(r"\d|\bR\d{3}\b|REPLYGATE|PASSED|CLEAN|NON-EXEMPT")


_GATE_MIN = 0.40  # see the GATE-RATIO docstring in the checker below


def _known_gate_names():
    """Gate names derived from bin/ and from this file's own fail() calls. NEVER a typed
    list: a typed list would go stale and score real gates as habits, which is the exact
    defect enforcecheck's own first control caught."""
    import os
    import re as _re
    names = set()
    b = os.path.expanduser("~/Claude/Improving-my-Claude/bin")
    if os.path.isdir(b):
        names |= {f[:-3] for f in os.listdir(b) if f.endswith(".py")}
    try:
        me = open(__file__, encoding="utf-8", errors="replace").read()
        names |= set(_re.findall(r'fail\(\s*"([A-Z][A-Z0-9-]{3,})"', me))
    except Exception:
        pass
    return {n for n in names if len(n) > 3}


def _names_a_gate(text, names):
    import re as _re
    return any(_re.search(r"\b%s\b" % _re.escape(g), text or "", _re.I) for g in names)


def _rec_rows(text):
    hdr = _header_map(text)
    ri = None
    if hdr:
        m = re.search(r"^\|\s*#\s*\|(.+)\|\s*$", text, re.M)
        names = [c.strip().lower() for c in m.group(1).split("|")] if m else []
        for i, n in enumerate(names):
            if "recommend" in n:
                ri = i
                break
    out = []
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if len(cells) < 4:
            continue
        rec = cells[ri] if ri is not None and ri < len(cells) else cells[-2]
        out.append((m.group(1), cells[0], rec, m.group(0)))
    return out


def check_rulings_cited(text):
    rows = [r for r in _rec_rows(text) if not _NOOP_REC.match(r[2])]
    if not rows:
        return
    m = _RULINGS_LINE.search(text)
    if not m:
        fail("RULINGS-CITED",
             "%d recommendation row(s) and no 'RULINGS CHECKED:' line. R066: the shortlist of "
             "rulings nearest each recommendation must be named and either cited or dismissed, "
             "or the line must say none apply." % len(rows))
        return
    body = m.group(1).strip()
    if not _RULING_ID.search(body) and "none apply" not in body.lower():
        fail("RULINGS-CITED",
             "the 'RULINGS CHECKED:' line names no ruling id and does not say 'none apply': %r"
             % body[:70])
    elif _RULING_ID.search(body) and len(body) < 40:
        fail("RULINGS-CITED",
             "the 'RULINGS CHECKED:' line names rulings but says nothing about them: %r. Each "
             "named ruling is cited as governing or dismissed in a clause." % body[:70])


def check_standing_quote(text):
    bad = []
    for rank, item, rec, row in _rec_rows(text):
        if not _STANDING.search(item):
            continue
        # THE FIRST VERSION READ row.split("|")[3], WHICH IS NOT THE RECOMMENDATION CELL, and
        # its own control caught it: a row quoting a count still failed. Read the cell the
        # header named, which _rec_rows already resolved.
        if _NOTHING.search(rec) and not _QUOTED_OUTPUT.search(rec):
            bad.append(rank)
    if bad:
        fail("STANDING-QUOTE",
             "%d standing row(s) claim 'nothing this reply' and quote no output: rows %s. R066: "
             "the row names its command and carries what that command printed - a count, an id "
             "or a stamp." % (len(bad), ", ".join(bad)))


# *** CLOSE-GATES. R067, ROB 2026-09-20, the second half of R064(b). *** A reply that asks Rob to
# close a plan item must carry a CLOSECHECK line: bin/closecheck.py runs every gate that item's
# own wording names. PASS is enough on its own. BLOCK is allowed through ONLY with a ruling id in
# the same line, because that is exactly the declared-gap case Rob ruled twice today - and it
# makes the exception a written citation instead of a silent close.
_CLOSE_ASK = re.compile(r"\bclose\s+(P\d+-\d+)\b", re.I)
_CLOSECHECK = re.compile(r"^CLOSECHECK\s+(P\d+-\d+)\s*:\s*(PASS|BLOCK|NO-GATE-NAMED)\b(.*)$",
                         re.M | re.I)


def check_close_gates(text):
    asked = {m.group(1).upper() for m in _CLOSE_ASK.finditer(text)}
    if not asked:
        return
    seen = {m.group(1).upper(): (m.group(2).upper(), m.group(3)) for m in _CLOSECHECK.finditer(text)}
    missing = sorted(asked - set(seen))
    if missing:
        fail("CLOSE-GATES",
             "%d plan item(s) are put up for closing with no CLOSECHECK line: %s. R067: run "
             "bin/closecheck.py on the item and quote its verdict, because on 2026-09-20 a close "
             "was approved on one gate while the gate the item's own wording names was failing."
             % (len(missing), ", ".join(missing)))
    for item in sorted(asked & set(seen)):
        verdict, rest = seen[item]
        if verdict != "PASS" and not re.search(r"\bR\d{3}\b", rest):  # R128: three digits
            fail("CLOSE-GATES",
                 "%s is put up for closing with CLOSECHECK %s and no ruling id on that line. A "
                 "blocked close needs the ruling that declares the gap, cited where the verdict is."
                 % (item, verdict))


# *** SENT-CHECKED. F171, ROB 2026-09-21 ('Approve #1'). *** The stamp certifies the draft; it
# never saw what was sent, and one reply went out reworded after stamping with every gate
# green. bin/sentcheck.py reads the session transcript and compares each sent reply with its
# stamp. A full reply (one with a THOROUGH line) must quote that run on a SENTCHECK line:
#   SENTCHECK: <n> stamped, <n> match, 0 MISMATCH
# A MISMATCH, or match below stamped, FAILS. Zero stamped is allowed only with the words
# "container reset", because the transcript starts when the container does.
# LIMIT, STATED: replycheck cannot open the transcript, so the numbers are Claude's quotation
# of sentcheck output. What this rule enforces is that the check was RUN and its verdict
# written where Rob reads it - the gap F171 exposed was that no check existed at all.
_SENTCHECK = re.compile(r"^SENTCHECK:\s*(\d+)\s+stamped,\s*(\d+)\s+match,\s*(\d+)\s+MISMATCH\b(.*)$",
                        re.M | re.I)


_SENT_ACK = pathlib.Path(__file__).resolve().with_name(".sent-mismatch-ack.tsv")
_INTAKE_MD = pathlib.Path.home() / "Claude" / "Improving-my-Claude" / "INTAKE.md"


def _sent_acks(path=None):
    """-> [(stamp_sha16, F-number)]. Rows: sha16 TAB F-### TAB ruling TAB reason. A row missing
    any of the four is IGNORED, never honoured - an acknowledgement with no reason is not one."""
    p = pathlib.Path(path) if path else _SENT_ACK
    out = []
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        c = ln.split("\t")
        if len(c) >= 4 and re.fullmatch(r"[0-9a-f]{16}", c[0].strip()) and re.fullmatch(r"F-\d{3}", c[1].strip()) \
                and c[2].strip() and c[3].strip():
            out.append((c[0].strip(), c[1].strip()))
    return out


def _intake_text():
    try:
        return _INTAKE_MD.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# *** DEFERRED-WORK, F-291, ROB 2026-09-29 13:55 PDT: "I want you to notice that you DID THIS AGAIN,
# after I've asked you to solve for this situation a few times today." ***
# MEASURED BEFORE BUILDING: in this chat Rob asked "thorough / how confident / why is this still
# happening" 12 times, and 9 of the 12 replies just before it ADMITTED undone work in their own
# prose - "I run it after sending", "those two edits were not reviewed again", "I have not run that
# comparison". The gate stamped such replies with 0 FAIL, because every stop check looked only at
# table rows and closing lines. The admission was honest and the reply still shipped, which is the
# exact trade Rob's rule forbids: a check in my own column is a check I skipped. This FAILS a
# sentence that defers runnable work past sending or admits a check was not run, unless the same
# sentence names a real blocker - Rob's ruling or word, or a stated reason the check cannot run.
# CORPUS, 194 stamped replies: 12 hit, 11 of them genuine skipped checks, 1 blocked on Rob with the
# blocker in the NEXT sentence. Quoted text, CHECKED/SENTCHECK/RULINGS lines and table rows are
# skipped, so quoting a past failure does not trip it.
_DEFER = [
    re.compile(r"\b(?:can only|will|I'll|I|to)\s+(?:\w+\s+){0,3}?(?:run|sweep|check|measure|review|do)\w*\b"
               r"[^.\n]{0,60}\bafter sending\b", re.I),
    re.compile(r"\b(?:I|I'll|I will)\b[^.\n]{0,60}\b(?:once (?:this|the reply) is sent|in the next (?:turn|reply)|"
               r"next turn|later today|later)\b", re.I),
    re.compile(r"\b(?:was|were|is|are|has|have)\s+not\s+(?:yet\s+)?(?:been\s+)?(?:reviewed|re-reviewed|re-run|rerun|"
               r"run|checked|measured|verified|tested)(?:\s+again)?\b", re.I),
    re.compile(r"\bnot reviewed again\b", re.I),
]
_DEFER_ALLOW = re.compile(
    r"\byour (?:ruling|yes|approval|decision|go-ahead|answer)\b|\bwaits? on (?:you|your|Rob)\b|"
    r"\bblocked on (?:you|Rob)\b|\bcannot be (?:run|closed|settled)\b|\bnot runnable\b|\bon your word\b|"
    r"\bbecause (?:no|nothing)\b[^.]{0,60}\bchanged\b", re.I)
_DEFER_SKIP = re.compile(r"^\s*(?:[-*>]\s*)?(?:\*\*)?(?:CHECKED|SENTCHECK|RULINGS CHECKED|REPLYGATE)\b|^\s*\|", re.I)


def deferred_sentences(text):
    out = []
    for ln in text.splitlines():
        if _DEFER_SKIP.search(ln):
            continue
        prose = re.sub(r"\"[^\"\n]{0,300}\"|“[^”\n]{0,300}”|`[^`\n]{0,200}`", " ", ln)
        for sent in re.split(r"(?<=[.!?;])\s+", prose):
            if any(p.search(sent) for p in _DEFER) and not _DEFER_ALLOW.search(sent):
                out.append(sent.strip())
    return out


def check_deferred_work(text):
    for s in deferred_sentences(text)[:3]:
        fail("DEFERRED-WORK",
             "this sentence defers or admits skipping work that is in my own column: %r. Run it before "
             "sending, or delete the claim it supports, or name the blocker (your ruling, a reason it "
             "cannot run) in the same sentence. F-291." % s[:110])


def check_sent_checked(text):
    if not THOROUGH_LINE.search(text):
        return
    m = _SENTCHECK.search(text)
    if not m:
        fail("SENT-CHECKED",
             "a full reply carries no SENTCHECK line. F171: run bin/sentcheck.py over the session "
             "transcript and quote it as 'SENTCHECK: <n> stamped, <n> match, 0 MISMATCH', because "
             "the stamp certifies the draft and only the transcript shows what was sent.")
        return
    stamped, match, bad = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # *** R114, ROB 2026-09-29 09:40 PDT: "4. Approved". *** A mismatch already in the transcript
    # cannot be un-sent, so without this every later full reply in that session FAILS forever -
    # the permanent red this function's own UNVERIFIABLE note warns trains everyone to ignore it.
    # A mismatch is ACKNOWLEDGED only when ALL hold: its stamp sha is a row in
    # .sent-mismatch-ack.tsv beside this file, that row names an F-number, the F-number exists in
    # INTAKE.md, and the reply cites BOTH the sha and the F-number. Every acknowledged mismatch is
    # still printed as a WARN on every run, and an unacknowledged one still FAILS.
    if bad and match + bad == stamped:
        _acks = _sent_acks()
        _intake = _intake_text()
        _cited = [a for a in _acks if a[0] in text and a[1] in text and (a[1] + ".") in _intake]
        if len(_cited) >= bad:
            warn("SENT-MISMATCH-ACKNOWLEDGED",
                 "SENTCHECK reports %d MISMATCH, each acknowledged under R114 and cited here: %s. "
                 "Not a pass for those replies - they went out different from what was gated."
                 % (bad, ", ".join("%s (%s)" % (a[0], a[1]) for a in _cited)))
            return
    if bad or match != stamped:
        fail("SENT-CHECKED",
             "SENTCHECK reports %d stamped, %d match, %d MISMATCH. A sent reply differs from the "
             "bytes its stamp certified; record it as a failure before anything else." % (stamped, match, bad))
    # *** THE THIRD STATE, ADDED 2026-09-27. *** A zero had exactly two readings: a container
    # reset, or a skipped check. A THIRD is real and was met on every Cowork reply for weeks -
    # sentcheck reads ~/.claude/projects, a Cowork reply leaves no transcript there, so the run
    # CANNOT SEE the reply either way. The old rule forced a choice between typing "container
    # reset" about a container that was not reset, and carrying a permanent FAIL that trains
    # everyone to ignore a red gate. BOTH ARE WORSE THAN SAYING WHAT IS TRUE.
    # THIS IS NOT A PASS AND MUST NEVER READ AS ONE. It is a WARN, it requires a stated reason
    # after the word, and replygate prints "sent UNVERIFIED" on the stamp so the cost is visible
    # on every reply that uses it rather than hidden in a warning count.
    # WHAT IT DELIBERATELY DOES NOT TOUCH: a real mismatch, or match < stamped, still FAILS above.
    # UNVERIFIABLE only ever applies when the instrument saw NOTHING to compare.
    if stamped == 0:
        _tail = m.group(4)
        _unver = re.search(r"\bUNVERIFIABLE\b[^A-Za-z0-9]{0,4}(.{12,})", _tail, re.I | re.S)
        if re.search(r"container reset", _tail, re.I):
            pass
        elif _unver:
            warn("SENT-UNVERIFIABLE",
                 "SENTCHECK reports 0 stamped and the line declares UNVERIFIABLE with a reason: %r. "
                 "Not a pass - the reply is unverified after send, and the stamp says so."
                 % _unver.group(1).strip()[:70])
        else:
            fail("SENT-CHECKED",
                 "SENTCHECK reports 0 stamped replies with no reason. Zero is legitimate only after a "
                 "container reset, or as UNVERIFIABLE with a stated reason, and the line must say which.")



# *** ABSENCE-CLAIM, ADDED 2026-09-21 ON ROB'S "Approve 1-3". *** Two of that afternoon's four
# corrections were claims of ABSENCE built on a gap: "the ledger's own edit history is out of
# reach" (one connector searched, the transcripts dated it) and "another session" edited a file
# (the author's own memory was the only instrument; it was this session). Rob's global field
# already says VALIDATE THE INSTRUMENT BEFORE TRUSTING A NULL RESULT; TOOL-DEADEND only WARNS, and
# only when a tool noun is named. This rule FAILS a reply that makes such a claim unless a
# CHECKED line in the same reply names the search AND a positive control. The phrase list is
# deliberately narrow (a sibling rule measured 12% recall), so it is a floor, not a net.
ABSENCE_CLAIM = re.compile(
    r"\b(?:out of reach|another session|no other session|"
    r"nothing (?:covers|reads|lists|checks)|"
    r"no (?:gate|rule|tool|call|script|check) (?:covers|lists|reads|exists|checks)|"
    r"has no call that|does not exist|"
    # W38 and W45, the ledger rows this rule was approved to close, in their own words:
    r"nothing recorded|the only record|was unrecorded|and nothing else|"
    r"cannot be (?:dated|found|read|reached|listed)|"
    r"can(?:not|.t) (?:reach(?! (?:its|zero|the floor|a floor))|see|find|list|access))\b", re.I)
ABSENCE_SKIP = re.compile(r"\b(?:was|were) wrong\b|\bFails if\s*:|\bplanted\b", re.I)
ABSENCE_SEARCH = re.compile(r"\b(?:search\w*|grep\w*|list(?:ed|ing)|quer\w+|fetch\w*|scann\w+)\b", re.I)
ABSENCE_CONTROL = re.compile(r"\b(?:control|known[- ]present)\b", re.I)


def check_absence_claim(text):
    checked = [ln for ln in raw_text(text).splitlines() if CHECKED_RE.match(ln)]
    # INLINE EVIDENCE, 2026-09-30, Rob's "Fix all the gaps": the global field now asks for the
    # call and its result in the same sentence instead of a CHECKED block, so an inline sentence
    # that names the search AND a positive control satisfies this rule exactly as a CHECKED line
    # does. Same two requirements, same narrow vocabulary - only the form is widened.
    checked += inline_evidence_text(raw_text(text))
    if any(ABSENCE_SEARCH.search(c) and ABSENCE_CONTROL.search(c) for c in checked):
        return
    # The THOROUGH line lists RIVAL hypotheses ("another session, a scheduled run, or ...");
    # naming a hypothesis to test it is the opposite of asserting it, so that line is skipped.
    body = "\n".join(ln for ln in text.splitlines()
                     if not CHECKED_RE.match(ln) and not ln.lstrip().startswith("THOROUGH:"))
    scrub = DQUOTE_ONLY.sub(lambda m: " " * len(m.group(0)), body)
    m = None
    for sent in re.split(r"(?<=[.!?])\s+|\n", scrub):
        # A sentence that RETRACTS a claim ("..., was wrong"), states a falsifier ("Fails if:"),
        # or describes a planted fixture is not asserting the absence. Tuned 2026-09-21 on Rob's
        # "Approve #1" after a corpus replay labelled 9 of 23 hits false alarms of these kinds.
        if ABSENCE_SKIP.search(sent):
            continue
        m = ABSENCE_CLAIM.search(sent)
        if m:
            scrub = sent
            break
    if m:
        fail("ABSENCE-CLAIM",
             "%r claims something is absent or unreachable, and no CHECKED line names the search "
             "that was run together with a positive control. A null from an instrument never "
             "shown to find a known-present case is not evidence of absence."
             % re.sub(r"\s+", " ", scrub[max(0, m.start() - 30):m.end() + 20]).strip())

# *** NOT-RUN-CLAIM, ADDED 2026-10-14 ON ROB'S "2. Approve" (08:28 PDT). *** At 07:2x PDT a reply said
# "You stopped the live drain before it started, so nothing moved on Instagram". Its only evidence was
# a tool call returning "The user doesn't want to proceed with this tool use"; the drain was in fact
# running and moved 76 posts. ABSENCE-CLAIM did not fire: its phrases are about reach, not about work
# that did not happen. A refused or interrupted call says nothing about a process already running.
# This rule FAILS a sentence saying work did not happen unless a CHECKED line names what was read: a
# token with "/", ".log", ".md", ".tsv", ".json", "cse_", "session_", "trig_", or a Drive-style
# 25+ character ID. Quoted text, ">" quote lines and CHECKED lines themselves are not read for claims.
# gate.py keeps this code in EVERY session, beside RATING-CLOSABLE (imc-reply-gate 0.2.3).
NOT_RUN_CLAIM = re.compile(
    r"\b(?:nothing (?:moved|ran|changed)|no moves|never (?:ran|started|fired)|was not run|"
    r"(?:didn.t|did not) (?:run|start|fire))\b", re.I)
NOT_RUN_EVIDENCE = re.compile(
    r"/|\.(?:log|md|tsv|json)\b|cse_|session_|trig_|"
    r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{25,}\b", re.I)


def check_not_run_claim(text):
    checked = [ln for ln in raw_text(text).splitlines() if CHECKED_RE.match(ln)]
    if any(NOT_RUN_EVIDENCE.search(CHECKED_RE.sub("", ln, count=1)) for ln in checked):
        return
    body = "\n".join(ln for ln in text.splitlines()
                     if not CHECKED_RE.match(ln) and not ln.lstrip().startswith(">"))
    scrub = _unquoted(body)
    for sent in re.split(r"(?<=[.!?])\s+|\n", scrub):
        if NOT_RUN_CLAIM.search(sent):
            fail("NOT-RUN-CLAIM",
                 "%r says work did not happen, and no CHECKED line names the log, file path, doc ID or "
                 "session ID that was read. A refused or interrupted tool call is not evidence that a "
                 "run did not happen: read the run's own log and cite it on a CHECKED line."
                 % re.sub(r"\s+", " ", sent).strip()[:160])
            return

# *** SITE-FAULT, ADDED 2026-10-16 (imc-reply-gate 0.2.14). *** In "Kaprelian - Objective 1: Nat's Back
# and Nat's PT" a reply called Anthem's site degraded after five hand-built searches timed out; the app's own
# screens worked minutes later and the control doctor had run last, so the failure was the instrument's
# (INTAKE F-594). ABSENCE-CLAIM did not cover it (its verbs are about reach) and does not run outside this
# project anyway. This rule FAILS a sentence that blames an outside site or service - timed out, down,
# degraded, not responding, an outage - unless a CHECKED line (or inline evidence) names a control that
# passed. A sentence that blames Claude's own request, script or instrument is not a site claim.
# gate.py keeps it in EVERY session and on ungated status replies (ALWAYS_ON and STATUS_KEEP).
SITE_FAULT = re.compile(
    r"\b(?:site|website|server|service|portal|endpoint|api|anthem|provider|vendor)(?:['\u2019]s)?\b"
    r"[^.!?\n]{0,80}?\b(?:timed? out|timing out|is down|was down|went down|is degraded|was degraded|"
    r"looks degraded|seems degraded|degraded|not responding|unresponsive|outage|having (?:an )?(?:issue|problem)s?)\b"
    r"|\b(?:timed? out|outage|degraded|not responding)\b[^.!?\n]{0,40}?\b(?:on|at|from) (?:the )?(?:site|website|server|portal|anthem)\b",
    re.I)
SITE_FAULT_OWN = re.compile(
    r"\b(?:my|I|our|we)\b[^.!?\n]{0,40}\b(?:request|search|script|call|query|instrument|route|code)|"
    r"\bhand-built\b|\binstrument\b|\bsession\b|\btab\b|\bbecause\b|\bwas wrong\b|\bnot the site\b|\bnot (?:the )?(?:site|Anthem)['\u2019]s\b", re.I)
SITE_FAULT_CONTROL = re.compile(r"\bcontrol\b", re.I)
SITE_FAULT_PASS = re.compile(r"\b(?:pass(?:ed|es)?|succeeded|loaded|returned|read|worked|ok)\b", re.I)


def check_site_fault(text):
    checked = [CHECKED_RE.sub("", ln, count=1) for ln in raw_text(text).splitlines() if CHECKED_RE.match(ln)]
    checked += inline_evidence_text(raw_text(text))
    if any(SITE_FAULT_CONTROL.search(c) and SITE_FAULT_PASS.search(c) for c in checked):
        return
    body = "\n".join(ln for ln in text.splitlines()
                     if not CHECKED_RE.match(ln) and not ln.lstrip().startswith(">"))
    scrub = _unquoted(body)
    for sent in re.split(r"(?<=[.!?])\s+|\n", scrub):
        if SITE_FAULT.search(sent) and not SITE_FAULT_OWN.search(sent):
            fail("SITE-FAULT",
                 "%r blames an outside site or service, and no CHECKED line names a control that passed on the "
                 "same instrument in this pass. Until a known-good case passes, a timeout is the instrument's, "
                 "not the site's: run the control first and cite it on a CHECKED line."
                 % re.sub(r"\s+", " ", sent).strip()[:160])
            return

# *** SKILL-CLAIM-UNSAVED, ADDED 2026-09-28. *** The worst error of that session was a table row
# reading "THE SKILL IS SAVED AND LIVE - instrument-before-number now appears in the skill list".
# The skill had never been proposed: propose_skills carried no tool_use entry at all, and
# ~/.claude/skills held 150 entries with no such name. ACCEPTED IS NOT APPLIED already covered it
# and did not fire, because nothing mechanical reads a claim about an action Claude says it took.
#
# THIS CONTROL IS NARROW ON PURPOSE AND THAT IS ITS STRENGTH. It does not ask the reply to NAME a
# path, which would be satisfiable by typing one. It stats the directory. A skill asserted as live
# either has a directory or does not, and no wording changes that.
#
# INSTRUMENT VALIDATION IS BUILT IN: if the skills root is absent - a cloud container, another
# machine - the check returns silently rather than failing everything. A null from an instrument
# that cannot see the target is not evidence, including when the instrument is this one.
SKILLS_ROOT = os.path.expanduser("~/.claude/skills")
SKILL_LIVE = re.compile(
    r"(?:saved and live|is now live|is live|now appears in the skill|appears in the skill list"
    r"|in the skill listing|is installed|now carries the skill|skill is saved)", re.I)
SKILL_NOT = re.compile(
    r"(?:never|not saved|not live|no such|does not exist|was wrong|wrongly|Fails if|proposed this turn"
    r"|nothing lands|until you save|returns nothing|NOT PROPOSED)", re.I)
SKILL_NAME = re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+){1,5})\b")

# *** SCOPE-VS-CLAIM, ADDED 2026-09-28 AFTER A FALSE SENTENCE PASSED 226 CONTROLS. ***
# The sentence was "no file defines any identifier above R099". Three such identifiers existed,
# in RULINGS-LEDGER.tsv in Google Drive. ABSENCE-CLAIM did not fire BECAUSE I SATISFIED IT: it
# demands a named search plus a positive control and I supplied both - scoped to the local
# project tree, for a claim quantified over every file. ABSENCE-CLAIM verifies that a search was
# NAMED. It does not verify that the search COVERS the claim.
#
# THIS CHECK COMPARES TWO STRINGS THE REPLY ALREADY CONTAINS: the quantifier and the root. An
# unscoped universal negative fails; naming the root it was actually searched over passes. That
# is not a loophole - narrowing the claim to what was searched IS the fix, and it is the one
# outcome a reply cannot fake, because the narrowed sentence is a weaker claim.
UNIVERSAL_NEG = re.compile(
    r"\b(no file|not in any file|nothing anywhere|no such (?:file|id|ruling|identifier)"
    r"|does not (?:exist|appear) anywhere|no other file|exists? nowhere)\b", re.I)
SCOPE_NAMED = re.compile(
    # A ROOT IN BACKTICKS COUNTS, 2026-09-30: "in `~/Claude/x/r4`" named its root and failed,
    # because the backtick sat between the preposition and the path. Optional backtick only.
    r"(?:under|within|inside|in|across)\s+(?:the\s+|its\s+)?`?"
    r"(?:[~./][\w./*-]*|\w+/[\w./*-]*|local project(?:\s+tree)?|laptop|this (?:project|repo|tree)"
    r"|Drive|Google Drive|[A-Za-z0-9_.-]+\.(?:py|tsv|md|sh|json|js))", re.I)
SCOPE_SKIP = re.compile(
    r"\b(was false|was wrong|I wrote|mislabelled|corrected|Fails if|retract|turned out"
    r"|which is false|control)\b", re.I)

def check_scope_vs_claim(text):
    """SCOPE-VS-CLAIM: a universal negative must name the root it was searched over."""
    for sent in re.split(r"(?<=[.!?])\s+|\n", text):
        m = UNIVERSAL_NEG.search(sent)
        if not m or SCOPE_SKIP.search(sent):
            continue
        if SCOPE_NAMED.search(sent):
            continue
        # QUOTATION BLINDNESS, FIXED BEFORE THIS CHECK SHIPPED. Run against the three drafts
        # already written, it fired 4 times: once on the real defect and three times on a reply
        # QUOTING that defect in order to correct it. A record of a corrected claim has to
        # contain the claim, the same lesson datecheck's header records for filenames. So a
        # match sitting inside quotes, or a sentence naming this rule, is not an assertion.
        if "universal negative" in sent.lower():
            continue
        before = sent[:m.start()]
        if (before.count('"') % 2) or (before.count("'") % 2) or ("\u201c" in before and "\u201d" not in before):
            continue
        fail("SCOPE-VS-CLAIM",
             "%r is a universal negative and names no root it was searched over. A search of one "
             "tree cannot support a claim about every file - that is how 'no file defines any "
             "identifier above R099' passed while three did, in Drive. Name the root the search "
             "actually covered, which narrows the claim to what was measured."
             % re.sub(r"\s+", " ", sent).strip()[:150])

def check_count_then_universe(text):
    """COUNT-THEN-UNIVERSE: a measured file count, then a claim about a wider noun in the same breath.

    *** ADDED 2026-09-30 AFTER THE THIRD INSTANCE IN TWO DAYS, THE SECOND IN ONE EVENING. ***
    SCOPE-VS-CLAIM already catches a universal negative with no root. This catches the harder shape,
    where a root IS named, correctly, and then quietly swapped for a bigger one:
      2026-09-25  a directory listed, a subset read, a conclusion drawn about the directory.
      2026-09-30 21:55  three .cowork-* files searched, conclusion drawn about "no cloud export".
      2026-09-30 22:08  96 files searched, conclusion drawn about the disk - IN THE REPLY THAT SAID
                        the method was now "enumerate, then search all of it".
    The bounded set grew each time and the substitution did not change, which is why phrasing checks
    missed it: every sentence was individually defensible. THE SIGNATURE IS THE PAIR - a digit-bearing
    count of files or rows, and within the same paragraph a claim scoped to a noun no count can cover.
    WARN, NOT FAIL, DELIBERATELY: a reply may legitimately quote a count and then discuss the wider
    system, and a FAIL here would refuse true statements. The WARN names both halves so the author
    sees the swap rather than being told a sentence is wrong.
    """
    universe = re.compile(r"\b(?:anywhere|nowhere|the disk|every export|all exports|any export|"
                          r"every file|any file on disk|every session|the whole (?:disk|tree|system))\b",
                          re.I)
    counted = re.compile(r"\b(\d{2,6})\s+(?:files?|rows?|entries|documents?)\b", re.I)
    # *** THE WINDOW IS CHARACTERS, NOT PARAGRAPHS, AND THE FIRST VERSION GOT THAT WRONG. ***
    # Built 2026-09-30 splitting on blank lines, with a control whose two halves sat on CONSECUTIVE
    # lines. It passed. The real 22:08 reply had the count and the claim in SEPARATE paragraphs, so
    # the check could not have caught the one thing it was built for, and the control hid that by
    # being unrepresentative of the text it modelled. A CONTROL THAT DIFFERS FROM THE REAL CASE IN
    # THE DIMENSION THE CHECK KEYS ON IS NOT A CONTROL. Proximity in characters is what "in the same
    # breath" actually means; 900 is about a screen of prose.
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("|"))
    hits = []
    for c in counted.finditer(body):
        window = body[c.end():c.end() + 900]
        u = universe.search(window)
        if not u:
            continue
        # *** THE EXEMPTION WINDOW MUST STRADDLE THE UNIVERSE WORD, NOT STOP AT IT. *** The first
        # version ended the span at u.end(), so "nowhere, of the 96 I searched" - the corrected shape
        # this check exists to permit - was judged on text that stopped before "of the 96" and was
        # flagged anyway. Caught by its own negative control, which is what negative controls are for.
        span = window[max(0, u.start() - 200):u.end() + 200]
        # A claim that NAMES the set it covered beside the wider noun is the corrected shape.
        if re.search(r"\b(?:of the|within the|among the|out of|inside the)\s+(?:\d{2,6}|set|sweep)\b",
                     span, re.I):
            continue
        hits.append((c.group(1), u.group(0)))
    seen = set()
    for n, word in hits:
        if word.lower() in seen:
            continue
        seen.add(word.lower())
        warn("COUNT-THEN-UNIVERSE",
             "a count of %s is quoted and a claim scoped to %r follows within 900 characters. "
             "A sweep is evidence about the set it covered. Either say 'of the %s' beside the claim, "
             "or widen the sweep - this is the shape that shipped three times in two days, each time "
             "with a bigger bounded set and the same substitution." % (n, word, n))
        if len(seen) >= 3:
            break


def check_skill_claim(text):
    """SKILL-CLAIM-UNSAVED: a skill asserted live must have a directory under the skills root."""
    # *** CORRECTED 2026-09-28, TWO HOURS AFTER THIS CHECK SHIPPED, BY RUNNING IT ON A TRUE
    # SENTENCE. *** The first version looked only in ~/.claude/skills and FAILED a reply saying
    # instrument-before-number was live. It WAS live - it appeared in that session's skill
    # listing - and it had no directory anywhere on the laptop. Two things were wrong. ACCOUNT
    # SKILLS LIVE IN skills/synced/<uuid>/<name>, not skills/<name>, so the search root was
    # incomplete; and skills/synced is a CACHE, so a skill saved server-side is invisible here
    # until it syncs. THE SECOND ONE CANNOT BE FIXED FROM DISK. A laptop check cannot tell
    # "never proposed" from "saved and not yet cached", so asserting FAIL on that difference is
    # a check that refuses true statements. It is a WARN now, and it says which of the two it
    # cannot distinguish. The narrower executable claim survives: the search covers both roots.
    if not os.path.isdir(SKILLS_ROOT):
        return
    present = set()
    try:
        present |= set(os.listdir(SKILLS_ROOT))
    except OSError:
        return
    syncroot = os.path.join(SKILLS_ROOT, "synced")
    if os.path.isdir(syncroot):
        for sub_ in os.listdir(syncroot):
            d = os.path.join(syncroot, sub_)
            if os.path.isdir(d):
                try:
                    present |= set(os.listdir(d))
                except OSError:
                    pass
    for sent in re.split(r"(?<=[.!?])\s+|\n", text):
        if not SKILL_LIVE.search(sent):
            continue
        if SKILL_NOT.search(sent):
            continue
        for nm in SKILL_NAME.findall(sent):
            if "." in nm or "/" in nm or nm in present:
                continue
            if not os.path.isdir(os.path.join(SKILLS_ROOT, nm)):
                warn("SKILL-CLAIM-UNSAVED",
                     "this reply states a skill is live and %r has no directory under %s or its "
                     "synced subfolders. TWO EXPLANATIONS AND THIS CHECK CANNOT SEPARATE THEM: "
                     "propose_skills only renders a card and nothing was ever saved, OR it was "
                     "saved and the local cache has not pulled it. Confirm against the session's "
                     "skill listing before writing that it is live." % (nm, SKILLS_ROOT))
            break

def check_owner_pronoun(text):
    """OWNER-PRONOUN: the Owner cell takes a NAME, never a pronoun.

    *** D-030, RECOVERED 2026-08-16 AND STILL OPEN UNTIL 2026-09-02. *** SUMMARY-SPEC
    line 35 has carried the rule the whole time and nothing enforced it. TABLE-SHAPE
    checks that an Owner COLUMN exists; OWN-COLUMN checks that a Rob-owned row names a
    real blocker; neither looks at what the cell SAYS.

    THIS IS NOT A STYLE RULE, IT IS AN INVERSION. Everywhere in Rob's instruction field
    "me" and "I" are ROB and "you" is CLAUDE - measured at 20 of 20 standalone uses. So
    a row whose Owner reads "Me" reads to him as HIS row while meaning the opposite, and
    the failure is silent: the table looks complete and the work is assigned backwards.

    Only a whole-cell pronoun fires. "Rob" and "Claude" pass; so does any cell that
    merely contains the word, because the defect is the pronoun STANDING AS the name."""
    bad = []
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(0).strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if OWNER_PRONOUN.match(cells[3]):
            bad.append((cells[0], cells[3]))
    if bad:
        fail("OWNER-PRONOUN",
             "%d row(s) name the owner with a pronoun instead of a name: %s. "
             "In Rob's field 'me' is ROB and 'you' is CLAUDE, so an Owner cell reading "
             "'Me' assigns the row to him and means the opposite of what was intended. "
             "Write Rob or Claude."
             % (len(bad), ", ".join("row %s (%r)" % (i, w) for i, w in bad[:4])))


def check_open_row_link(text):
    """EVERY row in a next-steps table carries a url, or says NO-ARTIFACT out loud.

    *** WIDENED FROM OPEN-ONLY TO EVERY ROW 2026-09-02, CLOSING P8-18. *** P8-18 recorded
    the defect as "REVIEW-LINK only inspects the Item column". THAT DIAGNOSIS WAS WRONG and
    reproducing the case is what showed it: REVIEW-LINK reads m.group(0), the whole row, and
    always has. The real defect is VOCABULARY - REVIEWABLE matches file extensions and a
    handful of nouns, so the two skills Rob had to open, named as bare words in the
    Recommendation cell, matched nothing and the row passed with no link.

    A VOCABULARY LIST CANNOT BE COMPLETED, so this check does not try. It keys on the row
    EXISTING in the next-steps table, not on any word in it. Rob has to act on every row
    there; a row with genuinely nothing to open says NO-ARTIFACT and says it out loud.
    That escape hatch is the point: it converts a silent omission into a written claim."""
    bad = []
    for m in TABLE_ROW.finditer(text):
        row = m.group(0)
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if HAS_LINK.search(row) or "NO-ARTIFACT" in row:
            continue
        bad.append((cells[0], cells[1][:34]))
    if bad:
        fail("OPEN-ROW-LINK",
             "%d next-steps row(s) carry no url and no NO-ARTIFACT token: %s. Rob asked for the links "
             "to the things he has to review IN THE ITEM COLUMN. This check keys on the row "
             "EXISTING, not on the words in it, because on 2026-09-02 I silenced REVIEW-LINK by "
             "rewording three cells instead of adding three links - and a vocabulary list can "
             "always be stepped around by choosing different words."
             % (len(bad), ", ".join("row %s (%s)" % (i, w) for i, w in bad[:4])))


def check_probe(text):
    """A claimed canvas/document edit with no probe and no read-back beside it."""
    if not CANVAS_EDIT.search(text):
        return
    checked = "\n".join(l for l in text.splitlines() if l.strip().startswith("CHECKED:"))
    if PROBE_EVIDENCE.search(checked):
        return
    m = CANVAS_EDIT.search(text)
    fail("PROBE-MISSING",
         "this reply claims a document or canvas edit (%r) but no CHECKED line shows a focus "
         "probe or a server-side read-back. In a canvas editor there is no field to read before "
         "writing, so the pre-write check is a harmless selection - shift+Right a few times and "
         "confirm the highlight renders. Skipping it on 2026-09-02 put 1,807 characters into the "
         "middle of a word and cost Rob a restore." % text[m.start():m.start() + 60])


def check_table_shape(text):
    for m in TABLE_HDR.finditer(text):
        cells = [c.strip().lower() for c in m.group(0).strip().strip("|").split("|")]
        if cells == SPEC_COLS or [c.replace("\u2019", "'") for c in cells] == SPEC_COLS_OLD:
            continue
        # SCOPED TO ACTION LISTS, Rob 2026-10-02 13:02 PDT ("Approve all 3"; he asked for a more
        # flexible table). The 2026-08-25 ruling governs next-steps and decision tables. A findings,
        # comparison or option table is not one, and failing it trained the reader to ignore this
        # check. Measured before applying: --selftest 276/0 including the screenshotted Decision
        # table; 252 stored replies 15 catches -> 14, the one dropped being an audit table.
        _first = cells[1] if len(cells) > 1 else ""
        _action = re.match(r"(item|issue|decision|action|task|next|step|to-?do|ask|blocker|row)s?\b", _first)
        _owned = any(c.startswith(("owner", "status")) for c in cells)
        if not (_action or _owned):
            continue
        got = " | ".join(cells)
        fail("TABLE-SHAPE",
             "a ranked table is headed '%s'. SUMMARY-SPEC's live shape, ruled by Rob on "
             "2026-10-04 and renamed 2026-10-15, is '# | Issue / Risk | Action | Owner | Recommendation | "
             "Pros | Cons'. Width is solved by shortening cells, never by dropping one of his "
             "fields." % got[:110])


def check_labels(text):
    tail = next_steps_block(text)
    if not tail:
        return
    body = text[: text.rfind(tail)] if tail in text else text
    orphans = []
    for item in LIST_ITEM.findall(tail):
        for a, b in LABEL.findall(item):
            lab = (a or b).strip()
            if len(lab) < 6 or lab.lower() in ("owner", "status", "item", "open", "blocked"):
                continue
            if lab.lower() not in body.lower():
                orphans.append(lab)
    for lab in sorted(set(orphans)):
        warn("ORPHAN-LABEL", "%r appears in the next-steps list but never in the body above it." % lab)
    _label_defined(text, tail, body)


# *** LABEL-UNDEFINED. ADDED 2026-09-02 AFTER ROB ASKED WHAT A LABEL MEANT THREE TIMES. ***
#
# WHAT HAPPENED. One clinical point - check whether the leg pain is a circulation problem
# rather than a nerve problem - was carried through three replies under three coined names:
# "THE VASCULAR SCREEN", then "ASK ABOUT CIRCULATION AS WELL AS NERVE", then finally the
# sentence itself. Rob asked what each one meant. The third reply, which just wrote the
# sentence, was the one that worked.
#
# WHY THE EXISTING CHECK DID NOT CATCH IT, AND WHY THIS IS AN EXTENSION RATHER THAN A NEW
# RULE. ORPHAN-LABEL fires when a next-steps label appears NOWHERE in the body. All three of
# these DID appear in the body - as their own bold heading, with the label restated and
# nothing next to it saying what it is. Restating a coined phrase over itself satisfies the
# letter of "the label appears verbatim in the body" while delivering none of its purpose.
# Rob's own wording of that rule is the mechanical test - "could I search this message for
# that exact string and land on the EXPLANATION?" - and a heading is not an explanation.
#
# WHAT THIS CATCHES AND WHAT IT DOES NOT, STATED SO THE GATE IS NOT OVER-TRUSTED. It catches
# a label whose every body occurrence is a bare heading or a line consisting of the label
# alone. It CANNOT tell whether the prose beside a label is plain English or more jargon -
# "THE VASCULAR SCREEN: run the vascular screen" passes. That residue is judgement, and this
# gate reduces the surface rather than closing it.
BARE_STRIP = re.compile(r"^[\s#>*_\-—:.\d)]+|[\s#*_\-—:]+$")


def _is_bare_label_line(line, lab):
    core = BARE_STRIP.sub("", line)
    return core.strip().lower() == lab.strip().lower()


def _label_defined(text, tail, body):
    labs = []
    for item in LIST_ITEM.findall(tail):
        for a, b in LABEL.findall(item):
            lab = (a or b).strip()
            if len(lab) < 6 or lab.lower() in ("owner", "status", "item", "open", "blocked"):
                continue
            labs.append(lab)
    for lab in sorted(set(labs)):
        hits = [ln for ln in body.split("\n") if lab.lower() in ln.lower()]
        if not hits:
            continue  # ORPHAN-LABEL already owns this case
        if all(_is_bare_label_line(ln, lab) for ln in hits):
            fail("LABEL-UNDEFINED",
                 "%r appears in the body only as its own heading, never in a sentence that "
                 "says what it is. Rob asked what a label meant three times on 2026-09-01 "
                 "for exactly this shape. Write the thing itself instead of naming it." % lab[:44])


# ---------- 6. COUNT DRIFT ----------
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10}
COUNT_CLAIM = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\s+"
    r"(items?|things?|steps?|changes?|edits?|fixes?|rules?|reasons?|checks?|gaps?|problems?|failures?|rows?|options?)\b",
    re.I)


def check_counts(text):
    tail = next_steps_block(text)
    n_items = len(LIST_ITEM.findall(tail)) if tail else 0
    for m in COUNT_CLAIM.finditer(text):
        raw = m.group(1).lower()
        n = WORDNUM.get(raw, None)
        if n is None:
            try:
                n = int(raw)
            except ValueError:
                continue
        if n_items and abs(n - n_items) == 0:
            continue
        if n_items and n <= 10 and n != n_items and m.group(2).lower().startswith(("item", "step")):
            warn("COUNT-DRIFT", "text says %r but the list has %d items." % (m.group(0), n_items))


# *** COUNT-DRIFT ONLY EVER LOOKED INSIDE THE NEXT-STEPS BLOCK, AND THE DEFECT KEEPS HAPPENING
# IN PROSE. MEASURED 2026-09-07, TWICE IN ONE REPLY AND ONCE IN A PROJECT DOC. *** The sentence
# was "THREE ADDRESS COUNTS WERE WRONG." followed by FIVE named subjects - Desai, Gazmarian,
# Vartanian, Bajaj, Agrawal - and it shipped twice. check_counts could not see it: its noun list
# has no "counts", it compares only against a next-steps list, and it WARNS where this is a
# false statement of fact.
# THE COUNT WAS ALSO THE SMALLEST OF THREE ERRORS IN THAT SENTENCE. It merged two different
# claims - one address count that Anthem's own card got wrong, and four rows where the SHEET
# was short an address - under one label, so no single number could have been right.
# THE FIX IS TO MAKE THE COUNT SELF-VERIFYING RATHER THAN TO COUNT PROSE, which cannot be done
# mechanically. An emphatic paragraph that opens by claiming N of something must number its
# items inline as (1), (2) ... (N). Then the check is exact and the writer cannot drift: the
# marker count either equals the stated count or the reply does not ship.
PROSE_COUNT_NOUNS = (r"counts?|errors?|defects?|mistakes?|corrections?|conflicts?|disputes?|"
                     r"rows?|cells?|sources?|findings?|changes?|addresses|providers?|reasons?|"
                     r"gaps?|failures?|problems?|things?|items?|columns?|claims?")
PROSE_COUNT = re.compile(
    r"^\s*(?:\*\*)?\s*((?:TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|[2-9]|10))\s+"
    r"(?:[A-Za-z][A-Za-z-]*\s+){0,3}(" + PROSE_COUNT_NOUNS + r")\b",
    re.M | re.I)
ENUM_MARK = re.compile(r"\((\d{1,2})\)")


def check_prose_count(text):
    """An emphatic paragraph claiming N of something must number its items (1)..(N)."""
    bad = []
    for para in re.split(r"\n\s*\n", text):
        head = para.strip()
        if not head:
            continue
        first = head.split(".")[0]
        # Only emphatic openers: bold or SHOUTED. Ordinary prose counts are left alone.
        if not (head.startswith("**") or first.upper() == first):
            continue
        m = PROSE_COUNT.match(head.replace("**", ""))
        if not m:
            continue
        raw = m.group(1).lower()
        n = WORDNUM.get(raw)
        if n is None:
            try:
                n = int(raw)
            except ValueError:
                continue
        if n < 2:
            continue
        # A one-sentence claim enumerates nothing and is left alone.
        if len(re.findall(r"[.!?]\s", head)) < 2:
            continue
        marks = sorted({int(x) for x in ENUM_MARK.findall(head) if x.isdigit()})
        if marks == list(range(1, n + 1)):
            continue
        bad.append("%r -> %s" % (m.group(0)[:48],
                                "no (1)..(%d) markers" % n if not marks
                                else "markers %s" % marks))
    if bad:
        fail("COUNT-DRIFT-PROSE",
             "%d emphatic paragraph(s) state a count and do not number the items inline: %s. "
             "Rob's rule is that a count never drifts from its list. Counting prose cannot be "
             "checked mechanically, so the count must be made self-verifying: write (1), (2) "
             "... (N) on the items themselves, or drop the number." % (len(bad), "; ".join(bad[:3])))


# ---------- 7. RATING WITHOUT A CHECK ----------
# *** FALSE POSITIVE FOUND 2026-08-27 AND FIXED IN THE GATE, NOT IN THE SENTENCE. ***
# "10/10 controls pass" is a SELFTEST RESULT, not a confidence rating, and the old pattern
# read it as one. That single misread cascaded into three FAILs on a clean reply: it demanded
# a THOROUGH line, called the rating bare, and flagged a nearby phrase as a closable check.
# A gate that fires on every selftest report trains its reader to ignore it. The trailing
# noun is the discriminator and it is mechanical.
# SECOND FALSE-POSITIVE SHAPE, 2026-08-27: A RATIO COMPARISON.
# "a first-person hypothesis measured 2/9 against 5/10" is a MEASUREMENT, not a rating,
# and the trailing-noun exemption above cannot see it - the noun comes before, not after.
# The discriminator is another fraction immediately preceding it, which no confidence
# rating has. Same lesson as the 10/10 case: fix the pattern, not the sentence.
RATING_RAW = re.compile(r"\b(10|[0-9])\s*/\s*10\b(?!\s*(?:controls?|tests?|checks?|rows?|items?|passe?[ds]?|selftests?|fixtures?))", re.I)
PRIOR_FRACTION = re.compile(r"\d+\s*/\s*\d+\D{0,14}$")


# *** A RATING WITHOUT "/10" WAS INVISIBLE TO EVERY RATING CHECK. MEASURED 2026-09-29. ***
# RATING_RAW knew only "8/10". Replies drifted to "Confidence 8 that ...", and every check keyed
# on RATING - RATING-UNBACKED, RATING-BARE, RATING-INFLATED, RATING-CLOSABLE and THOROUGH-SIX -
# went silent on them. The .reply-corpus held 104 replies with a bare "Confidence N", no N/10 and
# no THOROUGH line, all 18 rated replies on 2026-09-29 among them. Rob then had to ask "have you
# been thorough" - the exact question THOROUGH-SIX was built on 2026-08-25 to make unnecessary.
# The digit must be a single 0-10 token so "confidence 95%" and "confidence 2026-09" do not match.
RATING_BARE = re.compile(
    r"\bconfidence(?:\s+(?:is|of|at|now|rating|level))*\s*[:=—–]?\s*(10|[0-9])\b"
    r"(?!\s*/)(?![.,]\d)(?!\s*(?:%|percent|-\d))", re.I)
# *** WIDENED THE SAME DAY, 2026-09-29, BY AN ADVERSARIAL BATTERY OF 25 FORMS. *** 12 evaded, and
# one of them was live: 12 archived replies wrote "Confidence that X: 9 out of 10", which neither
# pattern above saw. Also caught here: a table cell "| Confidence | 8 |".
_COUNT_NOUNS = r"(?:controls?|tests?|checks?|rows?|items?|files?|replies|runs?|cases?|passe?[ds]?|selftests?|fixtures?)"
RATING_OUT_OF = re.compile(r"\b(10|[0-9])\s+out\s+of\s+10\b(?!\s*" + _COUNT_NOUNS + r")", re.I)
RATING_COLON = re.compile(
    r"\bconfidence\b[^.\n|]{0,140}?[:—]\s*(10|[0-9])\b(?!\s*/)(?![.,]\d)(?!\s*(?:%|percent|-\d))", re.I)
RATING_CELL = re.compile(r"\|\s*confidence\s*\|\s*(10|[0-9])\s*\|", re.I)
# THIRD WIDENING, SAME DAY, after the pre-send reviewer named the 9 forms still evading as a gap
# Claude could close. Each is anchored on a rating verb or noun so a bare number never matches.
# ONE CAPTURE GROUP PER PATTERN: _RatingRe reads m.group(1) and m.start(1), so an alternation
# with a group per branch would hand it None for every branch but the first.
RATING_VERBS = [re.compile(p, re.I) for p in (
    r"\b(?:i|i'd|i would|i'll)\s+(?:rate|put)\s+(?:it|this|that)\s+(?:at\s+)?(10|[0-9])\b(?!\s*/)(?!\s*out)",
    r"\bconfident\s+at\s+(10|[0-9])\b(?!\s*/)",
    r"\bcertainty\s*[:=—]?\s*(10|[0-9])\b(?!\s*/)(?![.,]\d)(?!\s*(?:%|percent))",
    r"\bsure\s+at\s+(10|[0-9])\b(?!\s*/)",
    # HELD-OUT TEST, 382 refused drafts never used in tuning: 2 misses of 318, both this form.
    r"\bconfidence\s+(?:is\s+|was\s+|stays\s+)?capped\s+at\s+(10|[0-9])\b(?!\s*/)")]
# A RATING IN WORDS CARRIES NO NUMBER, so it cannot feed findall's int(). It still makes a reply a
# rated reply, so THOROUGH-SIX triggers on it. 3 archived replies were rated only this way.
WORD_RATING = re.compile(
    r"\b(?:fairly|highly|very|quite|moderately|reasonably|extremely|somewhat)\s+confident\b|"
    r"\b(?:high|medium|low|moderate)\s+confidence\b|\b\d{1,3}\s*%\s*(?:confident|sure|certain)\b|"
    r"\bconfidence\s*(?:is\s+|of\s+|at\s+|:\s*)?(?:one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I)


class _RatingRe:
    """Every numeric rating pattern, minus matches that sit just after another fraction.
    Deduplicated on the digit's position, so one rating seen by two patterns counts once."""
    def _keep(self, text, m):
        return not PRIOR_FRACTION.search(text[max(0, m.start() - 26):m.start()])
    def _all(self, text):
        ms = []
        for rx in (RATING_RAW, RATING_BARE, RATING_OUT_OF, RATING_COLON, RATING_CELL, *RATING_VERBS):
            ms += list(rx.finditer(text))
        seen, out = set(), []
        for m in sorted((m for m in ms if self._keep(text, m)), key=lambda m: m.start()):
            if m.start(1) in seen:
                continue
            seen.add(m.start(1)); out.append(m)
        return out
    def search(self, text):
        a = self._all(text)
        return a[0] if a else None
    def finditer(self, text):
        return self._all(text)
    def findall(self, text):
        # MUST return the CAPTURE GROUP, not the whole match. The original pattern has one
        # group, so callers do int(x) on the result; returning "8/10" crashed replycheck the
        # moment this class shipped, and the selftest caught it in the same minute.
        return [m.group(1) for m in self.finditer(text)]


RATING = _RatingRe()


# *** R115, ROB 2026-09-29: ONE SHARED DEFINITION OF A RATED, STAMPED, GATE-NAMING REPLY. ***
# F-283 found 11 rated replies that reached Rob with no gate run at all, and nothing read the
# sent chat for them. bin/chatstampcheck.py now does, from a browser capture that keeps no chat
# text. The browser cannot import this file, so --export-patterns hands it these exact pattern
# sources plus FIXTURES carrying THIS file's verdicts. The capture runs the fixtures too, and
# chatstampcheck refuses a capture whose browser verdicts differ, so a regex that means one thing
# in Python and another in JavaScript fails loudly instead of counting wrong.
# TIGHTENED 2026-09-29 13:40 PDT. The first form, r"^REPLYGATE ", counted a reply opening
# "REPLYGATE NOT RUN: ..." as stamped - Claude's own unstamped 13:25 reply - so any reply could pass
# chatstampcheck by starting with the word. A stamp is only a first line ending in its sha256
# fingerprint, the same shape sentcheck.py requires.
# No \A or \Z: JavaScript reads \A as a literal "A". ^ and $ without the multiline flag mean the
# same thing in both engines, and the exported fixtures prove it on every capture.
STAMP_OPEN = re.compile(r"^REPLYGATE [^\n]*\bsha256 [0-9a-f]{16}[ \t]*(?:\n|$)")
GATE_MENTION = re.compile(r"replygate|replycheck", re.I)


def is_rated(text):
    """Any kept numeric rating, or a rating in words. The single meaning of RATED for R115."""
    return bool(RATING.search(text) or WORD_RATING.search(text))


EXPORT_FIXTURES = (
    "Confidence 8/10 that it holds.", "Confidence 8 that it holds.", "Confidence: 7.",
    "confidence is 6 on this", "Confidence that X holds: 9 out of 10.", "I'd rate it 7 overall.",
    "| Confidence | 8 |", "confident at 8", "certainty: 6", "sure at 7",
    "confidence is capped at 5", "I am fairly confident this holds.", "high confidence in the fix",
    "90% sure of it", "confidence: seven",
    "10/10 controls passed.", "measured 2/9 against 5/10", "confidence 95%", "confidence 2026-09",
    "8 out of 10 tests passed", "Ran 12 checks and 3 failed.", "The confidence interval is wide.",
    "REPLYGATE PASS sha256 0123456789abcdef\n\nConfidence 8/10.",
    "The gate refused: replycheck printed 2 FAIL. Confidence 6.",
    "Plain reply with no rating and no gate.",
    "REPLYGATE NOT RUN: no stamp exists for this reply.\n\nConfidence 7.")


ZERO_CALL_TRIGGER = "can you increase the confidence level?"
# Rob's field: "IF THE GATE CANNOT RUN, SAY SO IN THAT LINE'S PLACE AND NAME THE ERROR." The one
# sanctioned unstamped first line. "REPLYGATE NOT RUN" - Claude's 13:25 wording - is not this.
CANNOT_RUN = re.compile(r"^REPLYGATE CANNOT RUN: \S")
TRIGGER_FIXTURES = ("Can you increase the confidence level?", "  can you increase  the confidence level?  ",
                    "Have you been thorough in your analysis? How confident are you?",
                    "Can you increase the confidence level? If not, then continue.")


def trigger_match(s):
    return int(" ".join(s.strip().lower().split()) == ZERO_CALL_TRIGGER)


def export_patterns():
    import hashlib, json
    d = {"numeric": [p.pattern for p in (RATING_RAW, RATING_BARE, RATING_OUT_OF, RATING_COLON,
                                         RATING_CELL, *RATING_VERBS)],
         "prior_fraction": PRIOR_FRACTION.pattern, "prior_window": 26,
         "word": WORD_RATING.pattern, "flags": "i",
         "stamp": STAMP_OPEN.pattern, "gate_mention": GATE_MENTION.pattern,
         # F-293. Rob's field scopes its zero-tool-call rule to this exact question arriving
         # alone, and says "THE DISCRIMINATOR IS MY WORDS, NOT CLAUDE'S JUDGEMENT". chatstampcheck
         # excuses an unstamped reply only when the human message before it is this string, after
         # trimming, lower-casing and collapsing spaces - so the rule is read by code, not by me.
         "zero_call_trigger": ZERO_CALL_TRIGGER,
         "cannot_run": CANNOT_RUN.pattern,
         "trigger_fixtures": [[s, int(trigger_match(s))] for s in TRIGGER_FIXTURES],
         "fixtures": [[s, int(is_rated(s)), int(bool(STAMP_OPEN.search(s))),
                       int(bool(GATE_MENTION.search(s)))] for s in EXPORT_FIXTURES]}
    body = json.dumps(d, sort_keys=True, ensure_ascii=True)
    d["export_sha"] = hashlib.sha256(body.encode()).hexdigest()[:16]
    return d


# OI-0735 (Rob 2026-11-24, "Agree with your recommendation"): Rob's field writes the falsifier as
# "lower if <the named thing> <fails>", with "the" inside the placeholder, so "lower if X fails" must count.
CHANGER = re.compile(r"(drops? to|rises? to|falls? to|would (?:raise|change|move) it|changes if|if the|\b(?:lower|higher) if\b)", re.I)



# An action Claude can perform itself. Deliberately verb-led and narrow: the point is to catch
# a falsifier that DESCRIBES WORK, not one that describes a wall.
CLOSABLE = re.compile(
    r"\b(i (can|could|have not|haven'?t|did not|didn'?t) (check|run|read|open|verify|measure|test|look)"
    r"|takes? (one|a single|under a) (pass|call|minute|command)"
    r"|one (pass|call|command|query|grep|read)"
    r"|in one (pass|call)"
    r"|(?<!\d )(?<!\bhas )(not|never) (yet )?(read|opened|run|checked|verified|measured|counted|queried)"
    r"|would (settle|close|resolve) (it|this)"
    # *** R161, ROB 2026-10-02 06:39 PDT, "Approve #3". *** "count" is split out so its NOUN use
    # is skipped: "the count that made them look like one was" (F-426) names no work. Measured
    # 2026-10-02 over 3,443 corpus replies: guarding "check" the same way dropped real hits ("the
    # check that would settle the biggest gap: take the reply..."), so only "count" is guarded.
    # *** R272 ROW 2, ROB 2026-10-11 19:04 PDT. *** "I read the watchdog SKILL.md" reports a FINISHED
    # read (F-527 item 4) and fired this pattern. A first-person past report - "I read the", "I've read
    # the", "I opened the", "I ran the", "I checked the" - is excluded; a pending or skipped read still
    # fires through "(not|never) read", "haven't read" and the bare imperative forms.
    r"|(?<!\bi )(?<!\bi've )(?<!\bwe )(?<!\bi had )(?<!\bi have )(?<!re-)(?<!\bre)(re-?)?(read|open|run|grep|query|check|verify|measure) (it|the|that|those|each|every)"
    r"|(?<!\bthe )(?<!\ba )(?<!\bthis )(?<!\beach )(re-?)?count (it|the|that|those|each|every)"
    r"|is the check|the check (is|would be)|checkable"
    # ---- ADDED 2026-08-26. THE EXISTING PATTERNS ARE VERB-LED AND CAUGHT "I have not tested
    # a link chain three deep" correctly. THEY MISSED THIS, MEASURED ON THE ACTUAL REPLY:
    # "I mapped it to P2-15/P2-06 by assumption, and that is the one element where I matched
    # on wording instead of measuring." That names an unrun MEASUREMENT with no verb the old
    # regex knew, so RATING-CLOSABLE stayed silent while RATING-INFLATED fired for a
    # different reason. The falsifier was true, the work was Claude's, and it shipped.
    # A confession of method is the same defect as a confession of omission.
    r"|by assumption|assumed rather than|matched on wording|instead of measuring"
    r"|without measuring|did not measure|rather than measur"
    r"|(?<!\byou )(?<!\bthey )(have|having) not (separated|settled|distinguished|confirmed)"
    r"|not (yet )?(separated|settled|distinguished)"
    r"|i mapped it|mapped .{0,20}by|on wording)", re.I)

# A blocker Claude genuinely cannot pass. Presence of one of these EXEMPTS the falsifier.
PHYSICAL_BLOCKER = re.compile(
    r"\b(only (rob|you) (can|know)|credential|password|2fa|physically|on your (end|machine|phone)"
    # *** R154 C, ROB 2026-10-01 19:15 PDT, "Fix the rest". *** The bare word "approval" exempted
    # any window that mentioned one, so "one extra ruling.py call before any approval entry" and
    # "Reply with approvals per row" excused a 7/10 rating whose falsifier named a check Claude
    # could run (F-406). An approval is a blocker only when it is Rob's to give and is what the
    # check waits on.
    r"|(?:your|rob's|rob) approval|approval (?:from|by|only) (?:you|rob)"
    r"|(?:needs?|requires?|awaiting|waiting (?:on|for)|blocked on|pending) (?:your |rob's )?approval"
    r"|authoris|authoriz|you would have to|no browser control|not reachable|no connector"
    r"|returned (an )?error|permission denied|unauthori[sz]ed|rate.?limit"
    r"|external drive|another machine|off ?line|requires you to"
    # *** R272 ROW 2, ROB 2026-10-11 19:04 PDT. *** An APPROVE-N line asks Rob for a numbered approval,
    # and "needs a click from you" names a step only he can take (F-527 item 6, a 6/10 whose test waited
    # on his install approval and an app restart). Both are blockers the old list did not recognise.
    r"|approve-\d|a click from you)", re.I)

NO_RESIDUAL = re.compile(
    r"\b(?:there\s+is\s+)?no\s+residual\s+uncertainty\b|\bnothing\s+(?:here\s+)?is\s+unsettled\b", re.I)


def check_rating(text, claims, checked):
    r = RATING.findall(text)
    if not r:
        return
    info("rating: %d confidence number(s) emitted" % len(r))
    if not checked:
        fail("RATING-UNBACKED",
             "a confidence number is present with zero CHECKED lines. The rating is a release valve.")
    # *** ADDED 2026-08-26. THE TWO GATES HAD DIVERGED ON THE SAME RULE, WHICH IS THE EXACT
    # CONDITION crossgate.py EXISTS TO CATCH. *** presend was taught the same hour that an
    # explicit "no residual uncertainty" claim satisfies the falsifier requirement at 9 or 10,
    # because REQUIRING a falsifier on a fully-measured rating is what manufactured the hollow
    # "drops to N if <file> is absent, which it is not" that Rob caught. replycheck was not
    # taught it, so a reply could pass one gate and fail the other on one sentence. Fixed here,
    # with the SAME threshold: 9+, and it must be CLAIMED, never merely omitted - below 9 an
    # unstated gap exists by definition and that is precisely when a falsifier is owed.
    _no_resid = NO_RESIDUAL.search(text) and any(int(x) >= 9 for x in r)
    if not CHANGER.search(text) and not _no_resid:
        fail("RATING-BARE",
             "confidence number with no named condition that would change it. A bare number is not evidence. A form that passes: 'lower if the <named thing> <fails>'.")
    if any(int(x) >= 8 for x in r) and claims and len(checked) * 3 < len(claims):
        fail("RATING-INFLATED",
             "rating >=8 while %d claims carry only %d CHECKED lines." % (len(claims), len(checked)))

    # ---- RATING-CLOSABLE, added 2026-08-19 after Rob had to ask, twice in one session,
    # whether the analysis had been thorough. ----
    #
    # *** THIS FILE USED TO SCORE THE FAILING SHAPE AS CORRECT. *** Its own control read
    # ("a correct rating with a falsifier is not BARE", "Confidence 8/10. Drops to 4 if the
    # header list is stale.", "RATING-BARE", False). So RATING-BARE tested for the PRESENCE of
    # a falsifier and nothing else, and a rating whose falsifier named a one-minute check
    # sailed through as compliant.
    #
    # THE FALSIFIER IS NOT EVIDENCE OF COMPLIANCE. IT IS EVIDENCE THE GAP WAS IDENTIFIED AND
    # THEN SKIPPED. The more precisely it names the check, the more certainly the check was
    # known and not run. Measured 2026-08-19: three consecutive ratings each named its own
    # check - "I can check that in one pass and haven't", "it takes one pass, and I have the
    # media keys" - all three were later run, all three took under a minute, and TWO OF THREE
    # CHANGED THE ANSWER.
    #
    # A LEGITIMATE FALSIFIER NAMES A PHYSICAL BLOCKER: a credential Rob holds, a device only
    # he can touch, an approval only he can give, or a tool error that can be quoted. Effort,
    # token budget and number of tool calls are NOT blockers - that is the global rule this
    # detector enforces mechanically instead of by judgement.
    # WINDOWS: around each falsifier AND around each rating. The first version scanned only
    # CHANGER windows and missed a real example from the session that prompted this - "Item 2
    # is the check, it takes one pass, and I have the media keys" carries no "drops to", so it
    # had no falsifier to hang a window on. A detector that only sees the well-formed shape
    # misses the lazier one, which is the wrong way round.
    check_rating_closable(text)


# *** R161, ROB 2026-10-02 06:39 PDT, "Approve #3". *** QUOTED TEXT IS REPORTED, NOT SAID (F-428).
# A reply explaining an earlier flag quotes the flagged phrase and the flagged rating, and before
# this it tripped the same check, so every report about RATING-CLOSABLE minted a new FAIL. Quoted
# spans are blanked to spaces (offsets kept) before matching. A single quote counts as a quote
# mark only with no letter on its outer side, so contractions ("haven't", "it's") are never
# read as quotes and a real "I haven't read" still fires.
# A span counts as a quotation only if it OPENS like one (start, space or opening bracket before
# the mark, a non-space non-punctuation character after it) and CLOSES like one (a non-space
# character before the mark, space, punctuation or end after it). Measured 2026-10-02: plain
# pairing of marks went out of phase on lines with an odd number of quotes and blanked the prose
# BETWEEN two quotations, which dropped 36 real hits across 3,443 replies.
_R161_QO = r"(?<![^\s(\[{:\u2014-])"
_R161_QC = r"(?=[\s.,;:!?)\]}\u2014-]|$)"
_R161_QUOTE = re.compile(
    _R161_QO + r'"(?=[^\s".,;:!?)])[^"\n]{0,200}?(?<=\S)"' + _R161_QC
    + r"|" + _R161_QO + r"\u201c(?=\S)[^\u201d\n]{0,200}?(?<=\S)\u201d" + _R161_QC
    + r"|`[^`\n]{1,200}`"
    + r"|" + _R161_QO + r"'(?=[^\s'.,;:!?)])[^'\n]{0,200}?(?<=[^\s\\])'" + _R161_QC)


def _unquoted(text):
    return _R161_QUOTE.sub(lambda m: " " * len(m.group(0)), text)


def check_rating_closable(text):
    """RATING-CLOSABLE, SPLIT OUT OF check_rating 2026-08-19 SO IT CAN BE MEASURED.

    *** IT LIVED INSIDE check_rating, WHICH TAKES THREE ARGUMENTS, WHICH IS WHY IT COULD NOT
    JOIN CORPUS_CHECKS. *** Every corpus check takes text alone. So the detector written to
    stop Claude publishing a rating instead of running the check was structurally excluded
    from the only number that can regress, and nothing said so: ratefloor reported HELD at 83%
    on 2026-08-19 while the identical failure was committed twice more the same day.
    A one-argument signature is the whole reason this function exists separately."""
    # R161: the rating and the falsifier are read with quotations blanked, so quoted text can no
    # longer CAUSE a FAIL. The blocker is still read on the original text, so quoted text can still
    # EXCUSE one, exactly as before: measured 2026-10-02, blanking it too turned a reply that quoted
    # "Permission denied" into a new FAIL. The change can only remove flags, never add one.
    raw = raw_text(text)
    text = _unquoted(text)
    if not RATING.search(text):
        return
    spans = [m.start() for m in CHANGER.finditer(text)] + [m.start() for m in RATING.finditer(text)]
    for s in spans:
        lo, hi = max(0, s - 120), s + 340
        cm = CLOSABLE.search(text, lo, hi)  # pos/endpos keep the lookbehinds' view of the text before lo
        if cm and not PHYSICAL_BLOCKER.search(raw[lo:hi]):
            fail("RATING-CLOSABLE",
                 "a check Claude could run is named beside the rating: %r. Run it and re-rate; "
                 "a falsifier is not a substitute for the measurement it describes."
                 % cm.group(0)[:80])
            break


# ---------- 8. RANK vs CAVEAT INVERSION ----------
UNCERTAIN = re.compile(
    r"(unverified|unconfirmed|not re-?measured|COULD NOT OPEN|ABSENT|assumed|untested|"
    r"stale|may be wrong|not checked|no evidence|drops to [0-5]\b|\b[0-5]\s*/\s*10\b)", re.I)


SECTION = re.compile(r"^[^\n]*(blocked on|you can do now|claude can do now|mine|yours|owner)[^\n]*$", re.I | re.M)


def _sections(tail):
    marks = [m.start() for m in SECTION.finditer(tail)]
    if not marks:
        return [tail]
    marks = [0] + marks + [len(tail)]
    return [tail[marks[i]:marks[i + 1]] for i in range(len(marks) - 1)]


def check_rank_inversion(text):
    tail = next_steps_block(text)
    for sec in _sections(tail):
        _rank_one(sec, text)


def _rank_one(tail, text):
    items = LIST_ITEM.findall(tail)
    if len(items) < 2:
        return
    flags = []
    for idx, item in enumerate(items, 1):
        labs = [(a or b).strip() for a, b in LABEL.findall(item)]
        lab = labs[0] if labs else item[:40]
        shaky = bool(UNCERTAIN.search(item))
        if not shaky and lab:
            for s in sentences(text):
                if lab.lower() in s.lower() and UNCERTAIN.search(s):
                    shaky = True
                    break
        flags.append((idx, lab[:48], shaky))
    for i, lab, shaky in flags:
        if not shaky:
            continue
        below = [(j, l) for j, l, sh in flags if j > i and not sh]
        for j, l in below:
            warn("RANK-INVERSION",
                 "#%d %r is flagged uncertain but ranks above #%d %r which is not." % (i, lab, j, l))
            break


# ---------- 8b. RANK CONTRADICTION (P6-05) ----------
# *** RANK-INVERSION ABOVE IS A WARN AND IT ONLY SEES UNCERTAINTY. *** Rob's issue #3 is
# "Prioritized stack-ranked list of items is not prioritized", and the shape that actually
# ships is not a hedge word - it is a list whose OWN NOTES say the order is wrong. Two
# forms, both objective, both FAIL:
#
#   DEPENDENCY   item #2's note says it depends on / is blocked by / requires item #7.
#                A dependency ranked BELOW its dependent cannot be executed in list order,
#                so the list is not a plan. Direction matters and both are parsed: an
#                explicit subject ("P9 cannot close until this does") names the DEPENDENT,
#                and a bare clause ("blocked by the ledger fix") makes the current item it.
#   PRIORITY     an item whose note says "can wait" / "lowest priority" ranks ABOVE one
#                whose note says "most urgent" / "blocks everything". The notes and the
#                ranking assert opposite things in the same message.
#
# THE VERB LIST DELIBERATELY EXCLUDES "after" AND "once". Both are ordinary narrative words
# ("after the audit closed", "once the field committed") and including them turns a check
# with a defensible false-positive rate into one nobody reads. Every verb kept below is
# unambiguously a dependency assertion.
DEP_VERB = (r"(?:blocked by|blocked on(?! rob)|depends? on|dependent on|requires?|"
            r"needs?|cannot [a-z]{1,12} until|can.t [a-z]{1,12} until|waits? on|"
            r"waiting on|gated by|prerequisite(?: is|:)?|contingent on)")
DEP_RE = re.compile(r"(?P<subj>[^.;|]{0,60}?)\b" + DEP_VERB + r"\b(?P<obj>[^.;|]{0,90})", re.I)
IDTOK = re.compile(r"\b([A-Z]{1,3}\d{1,2}-\d{1,3})\b")

LOWPRI = re.compile(r"(lowest priority|least urgent|can wait|nice to have|not urgent|"
                    r"lowest value|do (?:this )?last|deprioriti|optional)", re.I)
HIGHPRI = re.compile(r"(highest priority|most urgent|do (?:this )?first|top priority|"
                     r"blocks everything|single most important|must go first)", re.I)


# *** INDEXING THE WHOLE ITEM MADE THE CHECK UNABLE TO FIRE, AND ITS OWN POSITIVE CONTROL
# CAUGHT IT ON THE FIRST RUN. *** An item reads "**P6-09 PRE-SEND** - blocked by P6-01".
# Scanning the whole line registered P6-01 as living at position 1, so the dependency
# resolved to the row that names it and `obj == dep_pos` discarded every real inversion.
# THE ID THAT IDENTIFIES A ROW IS IN ITS HEAD; THE IDs IN ITS NOTE ARE REFERENCES. Splitting
# on the first em dash, colon, pipe or spaced hyphen separates the two, and the pipe case is
# what makes markdown table rows work, since LIST_ITEM captures a table row after its first
# cell delimiter.
def _head(item):
    return re.split(r"[—–|:]|\s-\s", item)[0]


def _rank_index(items):
    """label/ID -> 1-based position, taken from each row's HEAD only. Both IDs and bold
    labels, so a list that uses either is covered; a list that uses neither cannot be
    checked and correctly reports nothing."""
    idx = {}
    for i, item in enumerate(items, 1):
        head = _head(item)
        for tok in IDTOK.findall(head):
            idx.setdefault(tok.upper(), i)
        for a, b in LABEL.findall(head):
            lab = (a or b).strip().lower()
            if len(lab) >= 6:
                idx.setdefault(lab, i)
    return idx


# *** ROB'S ITEMS CARRY HUMAN LATENCY AND MUST NOT BE AT THE BOTTOM. ADDED 2026-08-19. ***
# Rob asked whether the next-steps list is ordered by what comes first or by impact. Reading the
# gate answered it: the only encoded rule is RANK-DEPENDENCY - the list must be runnable top to
# bottom - and nothing ranked by impact or by owner at all. The practical effect was that the one
# item he could act on sat at position 7 of 7, under a heading he had to scroll past, while six
# items that needed nothing from him sat above it. A Claude item costs seconds to start; a Rob
# item costs however long it takes him to see it. ORDER BY WHO IS WAITING, THEN BY IMPACT.
# *** RULED BY ROB 2026-08-25: "Keep the Owner column. I want one stack-ranked list, not two
# broken by owner." *** These two regexes matched the HEADINGS of a role-split block that
# SUMMARY-SPEC.md forbids and that the global field mandated - the same shape live in three
# layers at once. They are kept, unused by RANK-OWNER, ONLY so a reply that still emits the
# old headings can be recognised and failed by SPLIT-BY-OWNER below.
SECTION_ROB = re.compile(r"^\s*\*?\*?blocked on rob", re.I | re.M)
SECTION_ME = re.compile(r"^\s*\*?\*?claude can do now", re.I | re.M)

# A next-steps TABLE row: | 3 | ITEM | Status | Owner | Pros/Cons |
# Owner is the 4th cell. Deliberately tolerant of the Item cell carrying a markdown link,
# which contains pipes in neither form - [LABEL](url) has none - so a naive split is safe.
TABLE_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.+)$", re.M)


# *** REWRITTEN 2026-08-26. THE PARSER ONLY UNDERSTOOD THE RETIRED SIX-COLUMN TABLE. ***
# SUMMARY-SPEC.md, ruled by Rob 2026-08-25, retires that header and specifies a THREE-column
# table - `| # | Item | Owner |` - with one labelled block per OPEN row carrying Status,
# Task, Recommendation and Pros/Cons. Rob's global field says the same thing from the other
# direction: "if a comparison needs more than three columns, use a list."
#
# THE TRAP THIS FIXES, MEASURED BEFORE FIXING IT: a three-column row splits to 3 cells, the
# old parser skipped anything under 4, so a spec-compliant table produced ZERO parsed rows and
# STOP-WHILE-UNBLOCKED returned silently. COMPLYING WITH ROB'S FORMAT RULING WOULD HAVE
# SWITCHED OFF THE GATE HE HAS ASKED ABOUT SIX TIMES. The choice was violate the format or
# disable the check, and nothing said so.
#
# NOW BOTH SHAPES PARSE. Owner is the LAST non-empty cell in a 3-column row and the 3rd cell
# in the 6-column one. Status in spec format lives in the row's block below the table, found
# by the Item label; when no block exists the status is empty, which _is_open treats as OPEN -
# the fail-loud direction.
def _header_map(text):
    """Column name -> index, taken from the table's own header row.

    *** ADDED 2026-09-01. THE CELL-COUNT GUESSING BELOW IT WAS WRONG THE MOMENT ROB CHANGED
    THE COLUMN COUNT. *** He ruled five columns; a five-column row leaves FOUR cells after the
    rank, which fell into the `>= 3` branch and took the owner from cells[-1] - the Pros / Cons
    cell. So STOP-WHILE-UNBLOCKED reported that NOT ONE row was owned by Rob while row 1 said
    Rob in plain sight. A gate that infers a column's meaning from how many columns there are
    breaks silently on every format change, and this file has now seen five of them.
    THE HEADER IS THE ONLY THING THAT KNOWS WHAT THE COLUMNS MEAN, so read it.
    """
    m = re.search(r"^\|\s*#\s*\|(.+)\|\s*$", text, re.M)
    if not m:
        return None
    names = [c.strip().lower() for c in m.group(1).split("|")]
    while names and names[-1] == "":
        names.pop()
    idx = {}
    for i, n in enumerate(names):
        if not n:
            continue
        if ("item" in n or n.startswith("issue")) and "item" not in idx:
            idx["item"] = i
        elif "owner" in n and "owner" not in idx:
            idx["owner"] = i
        elif n.startswith("action") and "action" not in idx:
            idx["action"] = i
        elif "status" in n and "status" not in idx:
            idx["status"] = i
    return idx if "owner" in idx else None


def _table_rows(text):
    """Return [(rank, item, status, owner)] for every next-steps table row.

    Column meaning comes from the header where there is one; the cell-count heuristics remain
    only as a fallback for a reply that carries a table with no header line."""
    out = []
    hdr = _header_map(text)
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if hdr and len(cells) > max(hdr.values()):
            item = cells[hdr.get("item", 0)]
            owner = cells[hdr["owner"]]
            status = cells[hdr["status"]] if "status" in hdr and hdr["status"] < len(cells) else ""
            if not status:
                label = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", item).strip()
                b = re.search(r"^\s*\*{0,2}\d+\.\s*" + re.escape(label) + r"\b[\s\S]{0,600}?"
                              r"^\s*Status\s*:\s*(.+)$", text, re.M | re.I)
                if b:
                    status = b.group(1).strip()
            out.append((int(m.group(1)), item, status, owner))
            continue
        if len(cells) >= 5:                      # retired: Item | Status | Owner | Rec | Pros
            out.append((int(m.group(1)), cells[0], cells[1], cells[2]))
        elif len(cells) == 2:                    # retired: Item | Owner
            item, owner = cells[0], cells[1]
            label = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", item).strip()
            status = ""
            b = re.search(r"^\s*\*{0,2}\d+\.\s*" + re.escape(label) + r"\b[\s\S]{0,600}?"
                          r"^\s*Status\s*:\s*(.+)$", text, re.M | re.I)
            if b:
                status = b.group(1).strip()
            out.append((int(m.group(1)), item, status, owner))
        elif len(cells) >= 3:
            out.append((int(m.group(1)), cells[0], cells[1], cells[-1]))
    return out


# *** REWRITTEN 2026-08-26 AFTER THE SIXTH "why did you stop again???". ***
# THE OLD VERSION REQUIRED THE STATUS CELL TO BEGIN WITH THE WORD "open". Every next-steps row
# Claude actually writes carries descriptive status prose - "755 remaining, 670 dispositioned;
# 82 .md next" - so NO row counted as open, open_rows came back empty, and check_stop_unblocked
# RETURNED BEFORE IT EVER LOOKED AT THE OWNER COLUMN. The gate built to stop the stop passed
# five consecutive stops, including one reply that named the failure and committed it in the
# same breath. A CHECK WHOSE TRIGGER MATCHES ONLY A FORMAT NOBODY WRITES IS A CHECK THAT IS OFF.
#
# NOW: a row is OPEN unless its status SAYS it is finished. Closed states must be declared, which
# is the direction that fails loudly - an unlabelled row counts as open and the reply has to
# justify ending, rather than an unlabelled row silently exempting the whole table.
# TERMINAL WORDS ONLY. Each of these means the row is finished; none of them can be true of
# a row still needing work. Widening this list is how the gate gets switched off again, so a
# word goes in only if a row carrying it could never require further action.
_DONE = re.compile(r"^\s*\**\s*(done|closed|complete[d]?|resolved|shipped|landed|n/?a|"
                   r"withdrawn|superseded|cancelled|canceled|obsolete|retired|dropped|"
                   r"dead|abandoned|archived|moot)\b", re.I)


# *** THE GATE HAD NO WORD FOR "BLOCKED BY SOMETHING THAT IS NOT ROB", AND THAT IS WHAT KEPT
# MANUFACTURING THE BANNED ROW. MEASURED 2026-09-07. *** STOP-WHILE-UNBLOCKED offered two exits:
# claim the work is finished, or put a row in Rob's column. When the real state was neither -
# the Anthem host was throttled and the call returned a quotable timeout - the only satisfiable
# exit was a Rob row, and in the Doctors project the nearest Rob-shaped row is always a phone
# call, the exact thing CALL-ON-ROB and his field both ban. A gate whose only compliant answer
# is a false one teaches a workaround; that comment was already written above and the third
# state was still missing from the code.
# THE THIRD STATE IS NARROW ON PURPOSE AND MATCHES HIS OWN DEFINITION OF A BLOCKER - "a tool
# that returned an error you can quote". The status must OPEN with the word blocked AND the row
# must carry a quoted fragment. "Blocked" on its own is not a magic word: with nothing quoted
# the row stays open and the gate still fires.
_BLOCKED_EXTERNAL = re.compile(r"^\s*\**\s*blocked\b", re.I)
_QUOTED = re.compile(r"[\"\u201c][^\"\u201d]{8,}[\"\u201d]")


def _is_open(status):
    s = (status or "").strip()
    if not s:
        return True
    if _BLOCKED_EXTERNAL.search(s) and _QUOTED.search(s):
        return False
    return not _DONE.search(s)


def _is_rob(owner):
    return "rob" in owner.lower()


# *** ROB'S RULE, STATED VERBATIM 2026-08-19: "When Blocked on Rob = Nothing, I expect you to
# keep going until you're blocked on me again." *** Four times tonight he asked "why did you stop
# again???" and each time my own list said, one line above the stop, that nothing was blocking me.
# A promise to continue is judgement and judgement is what this project replaces, so the rule is
# encoded as the shape of the reply itself: A REPLY THAT DECLARES AN EMPTY ROB SECTION IS A REPLY
# THAT SHOULD NOT HAVE BEEN SENT YET. The exception is narrow and mechanical - a reply with no
# NEXT STEPS block at all is a conversational answer and is not covered.
# \W failed here: the gap between the heading and the word is "**\n\n1. **", and the list number
# is a DIGIT, which \W does not match. Widened to any characters, bounded, DOTALL. Caught by the
# control rather than by review - which is the point of writing the control first.
# *** THE THIRD EXIT IS REMOVED. IT LASTED ONE REPLY. ***
# Added 2026-09-02 so a reply answering Rob's question could end without a Rob-owned row. I used it
# in the very next reply to stop with three of my own items open and nothing blocking - the exact
# abuse my own falsifier had named one paragraph earlier. Rob's response was "Why'd you stop???"
# THE GATE WAS NEVER WRONG. It was telling me not to stop, and I built a way around it instead of
# obeying it. The correct behaviour when Rob asks a question mid-work is to ANSWER IT AND KEEP
# WORKING IN THE SAME TURN, which is what he has said four separate times.
# WHAT WAS ACTUALLY WRONG was the earlier misassignment, and that has its own fix: OWN-COLUMN fails
# a Rob-owned row naming no real blocker. Two gates, one honest path between them - do the work.
EMPTY_ROB = re.compile(r"blocked on rob.{0,60}?\b(nothing|none|no items?)\b", re.I | re.S)



def _no_table_stop(text):
    """*** THE NO-TABLE STOP. ROB, 2026-08-31: "why are you stopping???????" - seven marks. ***

    Every other stop check fires only on a NEXT-STEPS TABLE. Four consecutive replies carried
    NO table, ended on a progress line - "86 remain", "Continuing." - and handed the turn back
    with nothing blocked. All four PASSED, because there was no table to inspect. The gate was
    measuring the wrong artifact: the defect is STOPPING, and a table is one shape it takes.

    THE TELL IS A CLOSING LINE THAT CLAIMS WORK REMAINS. If the tail says work is outstanding
    and nothing anywhere in the reply is owned by Rob, that is a stop with unfinished work and
    no blocker.
    """
    tail = "\n".join(text.strip().splitlines()[-6:]).lower()
    remains = re.search(r"\b\d+\s+(?:remain|left|to go)\b|\bremaining\b|"
                        r"\bcontinuing\b|\bnext (?:are|up|is)\b|\bstill to (?:read|do)\b", tail)
    rob = re.search(r"blocked on rob|owner.{0,20}rob|\|\s*rob\s*\|", text, re.I)
    if remains and not rob:
        fail("STOP-WHILE-UNBLOCKED",
             "the closing lines say work remains (%r) and nothing in this reply is owned by "
             "Rob. A stop with unfinished work and no blocker. It carries no next-steps table, "
             "which is exactly why the table checks missed it - the defect is stopping, not "
             "formatting. Keep going, or say the work is finished in those words."
             % remains.group(0))


# *** R075'S REPAIR TEST DOES NOT LIVE HERE, AND IT DID FOR ABOUT AN HOUR ON 2026-09-20. ***
# It consulted bin/gatestate.py from inside this check, so a reply's verdict depended on the
# laptop's current gate state. THAT BROKE replygate: its control "a clean reply exits 0" runs a
# three-line fixture through this file and started failing, because a gate elsewhere was red.
# A control whose answer changes with the machine's state is not a control - the same defect
# this project recorded when a bucketderive control was pinned to a live row.
# THE SPLIT IS THE FIX, AND IT IS THE ONE ALREADY IN USE HERE: this file lints TEXT, stopcheck
# and replygate decide whether a TURN MAY END. The repair test is a fact about the session, so
# it sits in replygate's --stamp path, which is the thing that authorises a reply to ship.
# What R075 changed HERE is the deletion below: an all-Claude table no longer fails.
def check_unblocked_stop(text):
    """Rob's rule: keep going until blocked on him again.

    RE-KEYED 2026-08-25 FROM SECTION HEADINGS TO THE OWNER COLUMN. The old version matched
    the literal string "blocked on Rob ... nothing", which only exists in the two-section
    block Rob retired in the same breath. Left alone it would have gone SILENTLY DARK the
    moment the format changed - a gate that stops firing without failing is the exact defect
    this whole project is about, and it would have taken the one check that enforces his
    most-repeated complaint with it.

    The table equivalent: a next-steps table carrying OPEN work owned by Claude and NOT ONE
    open row owned by Rob means nothing is blocking, and the turn should have continued.
    """
    rows = _table_rows(text)
    if not rows:
        # Fall back to the retired shape so an old-format reply is still covered.
        if re.search(r"^\s*NEXT STEPS\s*$", text, re.M) and EMPTY_ROB.search(text):
            fail("STOP-WHILE-UNBLOCKED",
                 "this reply declares 'Blocked on Rob: nothing' and then ends. Rob's rule is to "
                 "keep going until blocked again.")
        _no_table_stop(text)
        return
    _no_table_stop(text)

    open_rows = [r for r in rows if _is_open(r[2])]
    if not open_rows:
        return
    # *** THIS GATE MANUFACTURED THE BEHAVIOUR ROB'S RULES FORBID. MEASURED 2026-09-02 WHEN HE
    # ASKED "Why is #1 on me?" AND THE HONEST ANSWER WAS: TO GET PAST THIS CHECK. ***
    # As written it had exactly two exits - claim the work is finished, which is false while 26
    # plan items remain, or put a row in Rob's column. So the only satisfiable exit was to
    # misassign an item to him, which is the precise thing OWN-COLUMN exists to catch and which
    # his field calls "an incapability claim with the words removed". A gate whose only
    # compliant answer is a false one does not enforce a rule, it teaches a workaround.
    # THE THIRD EXIT IS TRUE AND CHECKABLE BY ROB: a reply that exists to ANSWER A DIRECT
    # QUESTION he asked is a legitimate end to a turn, and saying so names something he can
    # verify against his own message rather than against my judgement. It must also name the
    # item being picked up next, so the answer cannot become a resting place.
    # *** THE THIRD EXIT LIVED FOR ABOUT NINETY MINUTES AND R075 DELETED IT THE SAME DAY. ***
    # It was built this morning as an honest way out of the fail below - answer Rob's question,
    # name the next item, end the turn. R075 removed the fail it was an escape from, so an exit
    # from nothing is all that was left. Kept code that gates nothing is the worst kind: it
    # reads as protection, it collects controls that pass without discriminating, and the next
    # reader reasons from its presence. Rob's field says bias toward deleting. The two markers
    # _ANSWERS_Q and _NEXT_ITEM went with it, as did their three controls.
    # *** R075, ROB 2026-09-20, OPTION C. THIS CHECK USED TO ENFORCE THE OPPOSITE. ***
    # It failed a reply whose open rows were all Claude's own, which is how F165 happened:
    # "Ran an unrequested multi-hour refactor of the audit infrastructure off a work queue I
    # wrote myself... Each step was defensible against the previous one." Rob chose the boundary:
    # work Claude added to its own list is NOT authorisation to continue, and the ONE exception
    # is repairing something Claude's own change broke. So a self-authored list no longer forces
    # the reply onward - an OUTSTANDING REPAIR does, and that is measured, not judged.
    # THE MEASUREMENT IS bin/gatestate.py: a gate passing at this session's baseline and failing
    # now went red because of something done since, which is Rob's own wording for a repair.
    # NO STATE MEANS NO CLAIM EITHER WAY. If the baseline was never recorded the check says so
    # and does not invent a verdict; it never turns "I could not tell" into "you may stop".
    # NOTHING FOLLOWS. Under R075 a table whose open rows are all Claude's own is a legitimate
    # end to a turn, so this function's remaining job is the two fallbacks above: the retired
    # "Blocked on Rob: nothing" shape and the no-table tail. Whether an outstanding repair
    # forbids the stop is asked by replygate --stamp, which can see the session; this file
    # cannot, and pretending otherwise is what made a text linter state-dependent for an hour.


# *** R078, ROB 2026-09-20 "Approved": THE PRE-SEND REVIEWER ON DECISION REPLIES. ***
# Measured the same day: of 28 distinct defects found in six replies, about 12 - and all three
# that Rob's own follow-ups caught - were part-for-whole conclusions. No text rule here saw them:
# the three caught replies drew ZERO warnings pointing at the caught sentence, and a quantifier
# pattern flagged 110 sentences to find about 6 of the 12. An independent reviewer agent, given
# only the draft, found them. So the review is required, and this check makes skipping it loud.
# WHAT THIS CAN AND CANNOT PROVE, stated so the check is not mistaken for more than it is: it
# proves a review line is present, names a finding count, and is not a placeholder. It cannot
# prove the reviewer ran. That is judgement-enforced, and the R078 test - Rob's follow-ups on
# the next six decision replies - is what measures whether it is actually happening.
# A DECISION REPLY is one with an OPEN next-steps row owned by Rob; nothing else pays the cost.
_PSR_LINE = re.compile(r"^\s*\*{0,2}PRE-SEND REVIEW\*{0,2}\s*:(.*)$", re.M | re.I)
_PSR_COUNT = re.compile(r"\b(\d+|no|zero|one|two|three|four|five)\s+findings?\b", re.I)
_PSR_PLACEHOLDER = re.compile(r"filled in after|to be filled|\bTBD\b|\bpending\b|not yet run", re.I)
# *** R120, ROB 2026-09-29 17:53 PDT: "THIS HAPPENED AGAIN! WHY DO YOU KEEP GIVING ME REPLIES WITHOUT
# DOING A THOROUGH ANALYSIS??? FIX THIS!!!" *** MEASURED THE SAME MINUTE over .reply-corpus: of 135
# gated 0-FAIL replies carrying a PRE-SEND REVIEW line, 47 said in some wording that no review ran -
# "none run on this reply", "not re-run", "0 findings, because no independent reviewer read this
# draft", "PENDING", "no fresh reviewer read this text" - and every one passed, because _PSR_SELF was
# a BLACKLIST of two phrasings and a skip can be worded a hundred ways. The rule was never missing;
# the check matched wording, not meaning. SO THE REQUIREMENT IS NOW POSITIVE: the line must name an
# independent reviewer, must not say one did not run, and - when replycheck is given the draft file -
# a review record <draft>.review must sit beside it holding the reviewer's own output with a
# FINDINGS: line. Declaring the skip no longer passes; only doing the review does. NO EXEMPTION,
# per the F-310 lesson: every exemption this gate has had became the path of least resistance.
_PSR_SKIP = re.compile(r"none run|not run|not re-?run|\bno\s+(independent|fresh|separate|second)\b|"
                       r"unreviewed|not reviewed|did not run|didn't run|no reviewer|\bskipp?ed\b|"
                       r"self-review|reviewed (it )?myself|by the author", re.I)
_PSR_NAMES = re.compile(r"independent reviewer|reviewer agent|independent review", re.I)
# R120b: A WHITELIST, NOT A BLACKLIST. The independent reviewer beat the blacklist with four
# rewordings ("deferred", "waived", "not performed", "n/a") in one pass. The line must now carry
# this exact shape, and its N must equal the FINDINGS: line in the review record.
# R120c: the rewordings both reviewers used, rejected whether or not the template is present.
_PSR_EVADE = re.compile(r"deferr|waiv|not performed|not attempted|not launched|n/a|hypothetical|"
                        r"postpon|outstanding|\bTODO\b|would be expected|not yet", re.I)
_PSR_TEMPLATE = re.compile(r"independent reviewer(?: agent)? returned (\d+) findings?\b", re.I)
DRAFT_PATH = None


# R239 (N-013): the sha256 a review record must name. The draft's text with every PRE-SEND REVIEW line and
# every REPLYGATE stamp line removed, because both are written after the review; nothing else is removed.
_RG_LINE = re.compile(r"^REPLYGATE\b")


def review_draft_sha(path):
    import hashlib as _hl
    try:
        t = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    keep = [l for l in t.split("\n") if not _PSR_LINE.match(l) and not _RG_LINE.match(l)]
    return _hl.sha256("\n".join(keep).encode("utf-8")).hexdigest()


def review_draft_sha_text(t):
    import hashlib as _hl
    keep = [l for l in t.split("\n") if not _PSR_LINE.match(l) and not _RG_LINE.match(l)]
    return _hl.sha256("\n".join(keep).encode("utf-8")).hexdigest()


def _file_sha(path):
    import hashlib as _hl
    try:
        return _hl.sha256(open(path, "rb").read()).hexdigest()
    except OSError:
        return None


# *** P6-14, 2026-09-21: EVERY FULL REPLY, NOT ONLY DECISION REPLIES. *** R078 required the
# independent reviewer only when a reply asked Rob to decide. The reply that told Rob a baseline
# raise would turn failurecheck green carried "self-review, no independent reviewer. This reply
# asks nothing new." - and Rob's next question found the claim false. P6-14's criterion is that
# Rob's follow-up finds nothing left to find; a self-review is the author checking the author.
_PSR_SELF = re.compile(r"self-review|no independent reviewer", re.I)


def check_presend_review(text):
    rows = _table_rows(text)
    decision = any(_is_open(r[2]) and _is_rob(r[3]) for r in rows)
    full = bool(THOROUGH_LINE.search(text))
    # R120c: the stamp path (REPLYCHECK_DRAFT set by replygate) also treats any reply with a
    # next-steps table, or over 2,000 characters, as full. The second reviewer showed a reply with
    # no rating and no THOROUGH line skipped every R120 check - the easiest path left.
    import os as _os0
    if _os0.environ.get("REPLYCHECK_DRAFT") and (rows or len(text) > 2000):
        full = True
    if not (decision or full):
        return
    m = _PSR_LINE.search(text)
    if not m:
        fail("PRE-SEND-REVIEW",
             "this reply %s and carries no PRE-SEND REVIEW line. R078 and P6-14: an "
             "independent reviewer agent reads the draft first, and the reply states how many "
             "findings it returned and what was done with each."
             % ("asks Rob to decide something" if decision else "is a full reply"))
        return
    body = m.group(1)
    if full and _PSR_SELF.search(body):
        fail("PRE-SEND-REVIEW",
             "the PRE-SEND REVIEW line is a self-review (%r). P6-14: a full reply is read by an "
             "independent reviewer agent before sending, because the author re-reading the author "
             "is how an overstated claim reached Rob on 2026-09-21." % body.strip()[:60])
        return
    if _PSR_PLACEHOLDER.search(body):
        fail("PRE-SEND-REVIEW",
             "the PRE-SEND REVIEW line is a placeholder (%r). A review that has not run is the "
             "exact skip R078 exists to make visible." % body.strip()[:60])
        return
    if not _PSR_COUNT.search(body):
        fail("PRE-SEND-REVIEW",
             "the PRE-SEND REVIEW line names no finding count. Say how many findings came back "
             "and what was done with each - fixed, cut, or disputed with a reason.")
        return
    # R120: meaning, not wording. See the note beside _PSR_SKIP.
    _tm = _PSR_TEMPLATE.search(body)
    if _PSR_SKIP.search(body) or _PSR_EVADE.search(body):
        fail("PRE-SEND-REVIEW",
             "the PRE-SEND REVIEW line says the review did not run (%r). R120: saying so is not a "
             "substitute for running it - 43 to 48 of 135 gated replies passed that way. Run the "
             "independent reviewer on this draft, save its output beside the draft as <draft>.review "
             "with a 'DRAFT: <draft file name>' line (R120e), and report its findings." % (_PSR_SKIP.search(body) or _PSR_EVADE.search(body)).group(0))
        return
    if not _tm:
        fail("PRE-SEND-REVIEW",
             "the PRE-SEND REVIEW line does not say 'independent reviewer returned N findings'. "
             "R120b: that exact shape is required, because every looser shape was reworded around.")
        return
    import os as _os
    _dp = _os.environ.get("REPLYCHECK_DRAFT")
    if _dp:
        if _dp == "-":
            fail("PRE-SEND-REVIEW",
                 "the draft came in on stdin, so there is no path beside which a review record can "
                 "sit. R120b: stamp a draft FILE; a review that cannot be located is not a review.")
            return
        rp = _dp + ".review"
        rt = open(rp, errors="ignore").read() if _os.path.isfile(rp) else ""
        fm = re.search(r"^\s*FINDINGS:\s*(\d+)", rt, re.M)
        if not fm:
            fail("PRE-SEND-REVIEW",
                 "no review record at %s with a 'FINDINGS: <n>' line (and, R120e, a 'DRAFT: <draft "
                 "file name>' line). R120: the reviewer's own "
                 "output is saved beside the draft, so a review line with nothing behind it fails "
                 "on the file system rather than on Claude's word." % rp)
            return
        # R120e, Rob approved 2026-10-06 (audit N-013): the record was never tied to its own draft,
        # and 10 of 39 records in ~/Claude/replycheck fell in 3 byte-identical groups across
        # different drafts (measured 2026-10-06) - copying one sidecar passed every later draft. Two bindings, not a hash of the
        # draft, because the draft is legitimately edited after review (the PRE-SEND REVIEW line
        # itself is added afterwards), so a hash would fail every normal reply.
        _dn = _os.path.basename(_dp)
        _dl = re.search(r"^\s*DRAFT:\s*(\S.*?)\s*$", rt, re.M)
        if not _dl or _dl.group(1) != _dn:
            fail("PRE-SEND-REVIEW",
                 "the review record at %s %s. R120e, Rob approved 2026-10-06: the record carries a "
                 "line 'DRAFT: %s' naming the draft it reviewed, so a record copied from another "
                 "draft does not pass this one."
                 % (rp, "names draft %r" % _dl.group(1) if _dl else "has no 'DRAFT: <draft file name>' line", _dn))
            return
        # R239, ROB 2026-10-07 23:02 PDT (audit N-013; made 2026-10-08, approved 2026-10-07): the record
        # must ALSO name the sha256 of the draft it reviewed, and this gate checks it. The R120e note above
        # explains why a plain hash of the final draft fails normal replies (the PRE-SEND REVIEW line is
        # added afterwards, and fixes are made after the review), so the hash is checked two ways and
        # either passes: (1) the current draft with its PRE-SEND REVIEW and REPLYGATE stamp lines removed,
        # (2) a kept copy <draft>.reviewed - the bytes the reviewer read - whose own sha256 equals it.
        _sl = re.search(r"^\s*DRAFT-SHA256:\s*([0-9a-f]{64})\s*$", rt, re.M)
        if not _sl:
            fail("PRE-SEND-REVIEW",
                 "the review record at %s has no 'DRAFT-SHA256: <64 hex>' line. R239 (Rob 2026-10-07): the "
                 "record names the sha256 of the draft it reviewed - the draft without its PRE-SEND REVIEW and "
                 "REPLYGATE lines, or a copy kept as %s.reviewed - and this gate recomputes it." % (rp, _dn))
            return
        if _sl.group(1) not in (review_draft_sha(_dp), _file_sha(_dp + ".reviewed")):
            fail("PRE-SEND-REVIEW",
                 "the review record at %s names DRAFT-SHA256 %s..., which is neither this draft (without its "
                 "PRE-SEND REVIEW and REPLYGATE lines) nor a kept %s.reviewed copy. R239: a record copied "
                 "from another draft, or a review of text that is not this draft, does not pass."
                 % (rp, _sl.group(1)[:16], _dn))
            return
        try:
            _rb = open(rp, "rb").read()
            _rd = _os.path.dirname(_os.path.abspath(rp))
            for _o in sorted(_os.listdir(_rd)):
                _op = _os.path.join(_rd, _o)
                if (_o.endswith(".review") and _os.path.abspath(_op) != _os.path.abspath(rp)
                        and _os.path.isfile(_op) and _os.path.getsize(_op) == len(_rb)
                        and open(_op, "rb").read() == _rb):
                    fail("PRE-SEND-REVIEW",
                         "the review record at %s is byte-identical to %s. R120e, Rob approved "
                         "2026-10-06: a review is written for its own draft; a copied record is "
                         "not a review of this one." % (rp, _o))
                    return
        except OSError:
            pass
        if fm.group(1) != _tm.group(1):
            fail("PRE-SEND-REVIEW",
                 "the reply says the reviewer returned %s findings and the review record says %s."
                 % (_tm.group(1), fm.group(1)))
            return
        if len(rt) < 400 or not re.search(r"^\s*VERIFIED:", rt, re.M):
            fail("PRE-SEND-REVIEW",
                 "the review record at %s is %d bytes with%s a VERIFIED: section. R120c: a one-line "
                 "'FINDINGS: 0' passed the previous version; a real review reports what it checked."
                 % (rp, len(rt), "" if re.search(r"^\s*VERIFIED:", rt, re.M) else "out"))
            return
        # R120d: count numbered lines only BEFORE the VERIFIED: section - numbered lines inside it
        # padded the count (third reviewer, finding 8).
        _vm = re.search(r"^\s*VERIFIED:", rt, re.M)
        if len(re.findall(r"^\s*\d+\.\s", rt[:_vm.start()] if _vm else rt, re.M)) < int(fm.group(1)):
            fail("PRE-SEND-REVIEW",
                 "the review record claims %s findings but lists fewer numbered findings. A bare "
                 "'FINDINGS: 0' line was enough to pass the first version of this check."
                 % fm.group(1))
            return
        # *** RECO-SUBSTANCE, 2026-11-22. THE HALF NO REGEX CAN DECIDE. ***
        # RECO-STATED (runbehind.py) can see that a Recommendation cell has an advice clause, that
        # the clause is not a CHECKED line and that it names an action. It cannot see whether the
        # advice is worth anything: two independent reviewers defeated two successive versions of
        # it, the second with "RECOMMEND: proceed with the upload above." - every syntactic leg
        # satisfied, no advice given. A third syntactic leg would be defeated the same way, so the
        # substance verdict moves to the one reader who can make it, and the gate enforces only
        # that the verdict was made and written down. Shape at the gate, substance at the reviewer,
        # neither pretending to do the other's job.
        if NEXT_STEPS_HEADER.search(text) and not re.search(
                r"^\s*RECOMMENDATION-CHECK:\s*(\S.{19,})", rt, re.M):
            fail("PRE-SEND-REVIEW",
                 "the review record at %s carries no 'RECOMMENDATION-CHECK: <verdict>' line. A table "
                 "went to the reviewer, so the reviewer says, in its own words, whether each "
                 "Recommendation cell actually recommends something or only reports a run. No regex "
                 "can decide that, which is why it is asked of the reviewer and recorded here." % rp)


# *** TABLE-LAST, ROB APPROVED 2026-10-14 09:41 PDT, "must apply on every surface" (imc-reply-gate 0.2.4). ***
# Two checks, both kept in EVERY session by gate.py's ALWAYS_ON, beside RATING-CLOSABLE and NOT-RUN-CLAIM.
# TABLE-AFTER-REVIEW: when a reply carries both a PRE-SEND REVIEW line and a next-steps table, the review
#   line comes BEFORE the table, so the table is the last thing Rob reads and the thing he acts on.
# REVIEW-FIX-APPLIED: on the stamp path (REPLYCHECK_DRAFT set) with a kept <draft>.reviewed copy, a
#   finding counted as fixed must be traceable. The PRE-SEND REVIEW line says "fixed rows N, M" (or
#   "fixed: none"), each named row must differ between the .reviewed copy's table and this draft's table,
#   and fixed + disputed + partly disputed + cut must equal the finding count. A count of fixes with no
#   changed row behind it is the claim this check exists to refuse.
NEXT_STEPS_HEADER = re.compile(
    r"^\|\s*#\s*\|\s*Issue\s*/\s*Risk\s*\|\s*Action\s*\|\s*Owner\s*\|\s*(?:Claude[’']s\s+)?Recommendation\s*\|"
    r"\s*Pros\s*\|\s*Cons\s*\|\s*$", re.M | re.I)
_RFA_NUMW = {"no": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_RFA_PART = re.compile(r"\b(\d+|no|zero|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
                       r"(partly\s+disputed|disputed|fixed|cut)\b", re.I)
_RFA_ROWS = re.compile(r"\bfixed\s+rows?\s+(\d+(?!\d)(?:\s*(?:,|and|&)\s*\d+(?!\d)"
                       r"(?!\s*(?:partly|disputed|fixed|cut|findings?)\b))*)", re.I)
# OI-0256 (2026-10-20): the task prompts say "fixed rows <row numbers, or none>", so "fixed rows none" is the form a task
# writes for no fixes; it now counts the same as "fixed: none". "N fixed in text" is the form for a report with no table.
_RFA_NONE = re.compile(r"\bfixed\s*(?::|\s+rows?)\s*none\b", re.I)
_RFA_TEXT = re.compile(r"\bfixed\s+in\s+(?:the\s+)?text\b", re.I)


def _outside_fences(text):
    """The text with fenced code blocks blanked line for line, so offsets and line numbers still
    hold. OI-0495: this was a BOOLEAN TOGGLE on any line starting with ```, which breaks on the
    thing it is most often asked to skip - a quotation of a document that itself contains fences.
    Measured 2026-11-19: a ````-wrapped copy of Rob's instruction field has an example next-steps
    table inside it, the inner ``` flipped the toggle, and OBJECTIVE-SECTIONS then failed the
    draft for a table that was his example. It now uses the same CommonMark walk as
    fenced_blanked(), which is the one definition of a fence in this file."""
    keep = fenced_blanked(text).split("\n")
    out = []
    for i, ln in enumerate(text.split("\n")):
        out.append(ln if keep[i] == ln else "")
    return "\n".join(out)


def _next_steps_rows(text):
    """{rank: row text, whitespace-normalised} for the rows under the first next-steps header; None if none."""
    t = _outside_fences(text)
    hs = list(NEXT_STEPS_HEADER.finditer(t))
    if not hs:
        return None
    rows = {}
    for h in hs:  # 0.2.9: every table, since replies now carry one table per objective (R291)
        for ln in t[h.end():].lstrip("\n").split("\n"):
            s = ln.strip()
            if not s.startswith("|"):
                break
            m = re.match(r"^\|\s*(\d+)\s*\|(.*)$", s)
            if m:
                rows[int(m.group(1))] = re.sub(r"\s+", " ", m.group(2)).strip()
    return rows


# *** CON-FORMAT, R287 (Rob 2026-10-15 10:04 PDT): "the Risk and Mitigation in the Con column are each
# bulleted and on their own lines under the Con. Adjust the column spacing so the Con column isn't as
# narrow." Built on R286 (09:29 PDT): "The Con column ... should include the Con itself following by the
# Risk(s) and Plans to mitigate/fix them." ***
# Shape required in the Cons cell of every next-steps row:
#     Con:<NBSP>first<NBSP>words ... <br>• Risk: ... <br>• Mitigation: ...
# WHY THE NON-BREAKING SPACES, MEASURED 2026-10-15 ON THE RENDERED 09:30 PDT TABLE IN THIS CHAT:
# claude.ai lays tables out automatically inside a 736 px column; a 7-column table overflows it, so every
# column shrinks to its longest unbreakable run. Cons sat at 122 px because its longest word was
# "JUDGEMENT-ONLY:". Joining the Con line's first words with U+00A0 makes that run the column's minimum:
# 6 joined words measured 258 px and 8 measured 327 px in a DOM clone of the same table. <br> renders as a
# real line break in claude.ai table cells (measured on a rendered message in the same chat).
_CON_NBSP_WORDS = 6
_BR = re.compile(r"<br\s*/?>", re.I)


def _ns_table_cells(text):
    """[(rank, [cells])] for the rows under the first next-steps header; [] if none."""
    t = _outside_fences(text)
    out = []
    for h in NEXT_STEPS_HEADER.finditer(t):  # 0.2.9: every table (R291)
        for ln in t[h.end():].lstrip("\n").split("\n"):
            s_ = ln.strip()
            if not s_.startswith("|"):
                break
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", s_.strip().strip("|"))]
            if len(cells) >= 7 and re.match(r"^\d+$", cells[0]):
                out.append((int(cells[0]), cells))
    return out


def check_con_format(text):
    bad = []
    for rank, cells in _ns_table_cells(text):
        # "&nbsp;" counts as U+00A0: Claude cannot emit a raw U+00A0 in a tool call (measured 2026-10-15:
        # a typed one arrived as U+0020), and the markdown renderer decodes the entity to the same character.
        con = cells[6].replace("&nbsp;", "\u00a0")
        parts = [x.strip() for x in _BR.split(con)]
        probs = []
        if not re.match(r"^Con:[\s ]*\S", parts[0]):
            probs.append("does not open with 'Con:'")
        rest = parts[1:]
        ri = [i for i, x in enumerate(rest) if re.match(r"^[•*-]\s*Risks?:\s*\S", x)]
        mi = [i for i, x in enumerate(rest) if re.match(r"^[•*-]\s*Mitigations?:\s*\S", x)]
        if not ri:
            probs.append("no '<br>• Risk:' line")
        if not mi:
            probs.append("no '<br>• Mitigation:' line")
        if ri and mi and min(mi) < min(ri):
            probs.append("Mitigation comes before Risk")
        words = re.sub(r"^Con:[\s ]*", "", parts[0]).split(" ")
        need = min(_CON_NBSP_WORDS, len(re.split(r"[\s ]+", re.sub(r"^Con:[\s ]*", "", parts[0]).strip())))
        joined = len(words[0].split(" ")) if words and words[0] else 0
        if parts[0].startswith("Con:") and need > 1 and joined < need:
            probs.append("its Con line does not open with %d words joined by non-breaking spaces "
                         "(U+00A0), which is what widens the column" % need)
        # NBSP-CAP, Rob 2026-10-22 19:05 PDT ("THE WIDTH OF THE NEXT STEPS COLUMNS SQUEEZES THE TEXT. FIX IT FOR
        # GOOD"): the rule above asks for the FIRST 6 words joined. A draft joined the WHOLE Con sentence, one
        # unbreakable run of ~10 words (about 450 px), and claude.ai's automatic table layout gave the other six
        # columns what was left of its 736 px column. No unbreakable run may exceed 8 words in any cell.
        for ci, cell in enumerate(cells[:7]):
            runs = [len(r.split("\u00a0")) for r in re.split(r"[ \t]+", cell.replace("&nbsp;", "\u00a0")) if "\u00a0" in r]
            if runs and max(runs) > 8:
                probs.append("column %d has an unbreakable run of %d words joined by non-breaking spaces; "
                             "more than 8 squeezes every other column" % (ci + 1, max(runs)))
        if probs:
            bad.append("row %d: %s" % (rank, "; ".join(probs)))
    if bad:
        fail("CON-FORMAT",
             "R287 (Rob 2026-10-15 10:04 PDT): each Cons cell is 'Con: ...' then '<br>• Risk: ...' then "
             "'<br>• Mitigation: ...', its first %d words joined by non-breaking spaces so the column is "
             "not squeezed. Failing: %s" % (_CON_NBSP_WORDS, " | ".join(bad)))


def check_cell_width(text):
    """CELL-WIDTH, Rob 2026-10-22 18:38 PDT ("FIX THE COLUMN WIDTHS IN THE NEXT STEPS TABLE. IT KEEPS ON MESSING UP"):
    claude.ai lays tables out automatically, so a column shrinks to its longest unbreakable run. A raw URL or a
    long ID in Issue / Risk or Action held that column wide and squeezed the rest (SUMMARY-SPEC.md line 26).
    Link targets are exempt; link labels count. Fails a raw URL or any unbroken run over 24 characters."""
    bad = []
    for rank, cells in _ns_table_cells(text):
        for ci, name in ((1, "Issue / Risk"), (2, "Action"), (4, "Recommendation"), (5, "Pros"), (6, "Cons")):
            c = re.sub(r"\]\([^)\s]*\)", "]", cells[ci])
            c = c.replace("&nbsp;", " ")
            probs = []
            if re.search(r"(?:https?|computer)://", c):
                probs.append("a raw URL")
            long_ = [w for w in re.split(r"\s+", c) if len(w) > 24] if ci in (1, 2) else []
            if long_:
                probs.append("an unbroken run of %d characters (%s...)" % (len(long_[0]), long_[0][:12]))
            if probs:
                bad.append("row %d %s: %s" % (rank, name, " and ".join(probs)))
    if bad:
        fail("CELL-WIDTH",
             "R287 / SUMMARY-SPEC.md line 26: no raw URL in any cell and no unbroken run over 24 characters in Issue / Risk or "
             "Action; write [label](url) and shorten IDs. Failing: " + " | ".join(bad))


# *** ID-NAME, R287 (Rob 2026-10-15 10:04 PDT): "Replies with a Claude identifier always need to have the
# user-facing name/title next to it in parenthesis." He had written at the same time: "Stop referring to
# things in your replies by ID!!!" The rule already existed in /preferences.md ("use its full title exactly
# as shown in the app, every time") and was not followed - a RETRIEVAL failure, so it is converted here
# into a check that refuses. ***
# Accepted: ID (name) - parentheses straight after the ID holding at least one word of 3+ letters;
#           "Full title" (ID) - the ID inside parentheses straight after a closing quote;
#           a range "OI-0054 to OI-0058 (name)".
# Exempt, because a literal is never rewritten: text inside double quotes or backticks, link targets,
# bare URLs, fenced code.
_ID_NAME_RX = re.compile(
    r"(?<![\w/\-.])(?:session_[A-Za-z0-9]{12,}|cse_[A-Za-z0-9]{12,}|trig_[A-Za-z0-9]{12,}|"
    r"chat_[0-9a-f-]{8,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|"
    r"OI-\d{4}|F-\d{3,4}|R\d{3})(?![\w\-])")
_ID_NAME_PAREN = re.compile(r"^\s*\(([^()]*)\)")
_ID_NAME_RANGE = re.compile(r"^\s+(?:to|through|and|or|-|–)\s+(OI-\d{4}|F-\d{3,4}|R\d{3})")


def _id_name_blank(text):
    t = _outside_fences(text).replace("&nbsp;", "      ")  # same length, so offsets hold
    t = re.sub(r"\]\([^)\s]*\)", lambda m: "](" + " " * (len(m.group(0)) - 3) + ")", t)
    t = re.sub(r"(?:https?|computer)://\S+", lambda m: " " * len(m.group(0)), t)
    t = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), t)
    t = re.sub(r"\"[^\"\n]*\"|“[^”\n]*”", lambda m: m.group(0)[0] + " " * (len(m.group(0)) - 2) + m.group(0)[-1], t)
    return t


def _id_named(t, m):
    after = t[m.end():]
    r = _ID_NAME_RANGE.match(after)
    if r:
        after = after[r.end():]
    pm = _ID_NAME_PAREN.match(after)
    if pm and re.search(r"[A-Za-z]{3,}", _ID_NAME_RX.sub("", pm.group(1))):
        return True
    before = t[:m.start()].rstrip()
    if before.endswith("("):
        b2 = before[:-1].rstrip()
        if b2.endswith(("\"", "”")):
            return True
    return False


def check_id_name(text):
    t = _id_name_blank(text)
    bad = []
    for m in _ID_NAME_RX.finditer(t):
        if not _id_named(t, m):
            bad.append(m.group(0))
    if bad:
        seen = []
        for b in bad:
            if b not in seen:
                seen.append(b)
        fail("ID-NAME",
             "R287 (Rob 2026-10-15 10:04 PDT): every Claude identifier carries its user-facing name or title "
             "next to it in parentheses - 'OI-0059 (wrong times in five register rows)' or '\"Full chat "
             "title\" (session_...)'. Bare: %s" % ", ".join(seen[:12]) + (" and %d more" % (len(seen) - 12) if len(seen) > 12 else ""))


# *** OBJECTIVE-SECTIONS, R291 (Rob 2026-10-15 11:12 PDT): "update the table format so that it has each of the
# objectives/goals restated from the session, and has all the open actions (Claude/Rob) need to take and open
# decisions for Rob group by the objective/goal that it supports ... separate tables for each objective/goal with
# every reply ... Recommendation (renamed from Claude's Recommendation) ... If everything related to an
# objective/goal is done, then state the status of that objective with each reply." ***
# A reply with a next-steps table must: head every table with an objective line
#   OBJECTIVE <n> - <name> [IN PROGRESS] / [NOT STARTED] / [DONE <YYYY-MM-DD> <time>]
# (a DONE objective carries no table); use the renamed "Recommendation" header; and number rows once across
# all tables, so "row 3" names one row.
_OBJ_LINE = re.compile(r"^\W*OBJECTIVE\s+(\d+)\s+[-–—]\s+(.+?)\s+\[(DONE\s+\d{4}-\d{2}-\d{2}[^\]]*|IN PROGRESS|NOT STARTED)\]\W*$")
# 0.2.11, SUMMARY-SPEC.md PROJECT OBJECTIVES AND HANDOFFS (Rob 2026-10-15 12:21 PDT): "They should not only include
# the objectives for that particular session, but also the project-level objectives/goals. If a session is not going
# to be supporting all of the project-level objectives/goals, then the Next Steps table should list the handoffs that
# need to happen from that session to other sessions." A project-bound reply (REPLYCHECK_PROJECT=1) with a table
# carries PROJECT OBJECTIVE lines before its first OBJECTIVE line; a table under a HANDOFFS line is a handoff table.
_PROJ_LINE = re.compile(r"^\W*PROJECT\s+OBJECTIVE\s+(\d+)\s+[-–—]\s+(.+?)\s+\[(DONE\s+\d{4}-\d{2}-\d{2}[^\]]*|IN PROGRESS|NOT STARTED)\]\W*$")
_HANDOFF_LINE = re.compile(r"^\W*HANDOFFS\b")


import os as _os_obj


def check_objective_sections(text):
    t = _outside_fences(text)
    hs = list(NEXT_STEPS_HEADER.finditer(t))
    if not hs:
        return
    lines = t.split("\n")
    probs, seen_rank = [], {}
    for h in hs:
        hl = t.count("\n", 0, h.start())
        if re.search(r"Claude[’']s\s+Recommendation", h.group(0), re.I):
            probs.append("the table on line %d still says \"Claude's Recommendation\"; the column is now \"Recommendation\"" % (hl + 1))
        obj = None
        for k in range(hl - 1, -1, -1):
            ln = lines[k].strip()
            if NEXT_STEPS_HEADER.match(ln) or (ln.startswith("|") and k < hl - 1 and not ln.startswith("|---")):
                break
            if _HANDOFF_LINE.match(ln):
                obj = "HANDOFFS"
                break
            m = _OBJ_LINE.match(ln)
            if m:
                obj = m
                break
        if not obj:
            probs.append("the table on line %d has no 'OBJECTIVE <n> - <name> [STATUS]' or 'HANDOFFS' line above it" % (hl + 1))
        elif obj != "HANDOFFS" and obj.group(3).startswith("DONE"):
            probs.append("OBJECTIVE %s is marked DONE but carries a table of open items" % obj.group(1))
    if _os_obj.environ.get("REPLYCHECK_PROJECT") == "1":
        first_obj = next((i for i, ln in enumerate(lines) if _OBJ_LINE.match(ln.strip())), None)
        proj = [i for i, ln in enumerate(lines) if _PROJ_LINE.match(ln.strip())]
        bad = [i for i, ln in enumerate(lines) if re.match(r"^\W*PROJECT\s+OBJECTIVE\b", ln.strip()) and i not in proj]
        if not proj:
            probs.append("this session belongs to a project, so the tables need 'PROJECT OBJECTIVE <n> - <name> [STATUS]' "
                         "lines before the first OBJECTIVE line (SUMMARY-SPEC.md PROJECT OBJECTIVES AND HANDOFFS)")
        elif first_obj is not None and min(proj) > first_obj:
            probs.append("the PROJECT OBJECTIVE lines come after the first OBJECTIVE line; put them first")
        for i in bad:
            probs.append("line %d starts 'PROJECT OBJECTIVE' but is not '<n> - <name> [DONE <date> <time> / IN PROGRESS / NOT STARTED]'" % (i + 1))
    for rank, cells in _ns_table_cells(text):
        if rank in seen_rank:
            probs.append("row %d is numbered twice; number rows once across all tables" % rank)
        seen_rank[rank] = 1
    if probs:
        fail("OBJECTIVE-SECTIONS", "R291 (Rob 2026-10-15 11:12 PDT): group the next-steps rows under objective "
             "headings. " + " | ".join(probs))


def check_table_after_review(text):
    t = _outside_fences(text)
    h = NEXT_STEPS_HEADER.search(t)
    if not h:
        return
    late = [m for m in _PSR_LINE.finditer(t) if m.start() > h.start()]
    if late:
        fail("TABLE-AFTER-REVIEW",
             "the PRE-SEND REVIEW line sits on line %d, after the next-steps table that starts on line %d. "
             "TABLE-LAST (Rob, 2026-10-14 09:41 PDT): the review line goes above the table, so the table is "
             "the last thing in the reply." % (t.count("\n", 0, late[0].start()) + 1, t.count("\n", 0, h.start()) + 1))


def check_review_fix_applied(text):
    import os as _os
    dp = _os.environ.get("REPLYCHECK_DRAFT")
    if not dp or dp == "-":
        return
    m = _PSR_LINE.search(text)
    if not m:
        return  # PRE-SEND-REVIEW owns a missing line
    body = m.group(1)
    tm = _PSR_TEMPLATE.search(body)
    if not tm:
        return  # PRE-SEND-REVIEW owns the shape of the line
    n = int(tm.group(1))
    parts = {"fixed": 0, "disputed": 0, "partly disputed": 0, "cut": 0}
    # EACH CATEGORY IS COUNTED ONCE (coordinator, 2026-10-14). A triage line naming "partly disputed" and
    # "cut" summed 14 findings to 16: the reasons repeat the labels ("row 4 cut to one line", "the part
    # disputed ..."), and every repeat was added. Now the FIRST "N <label>" per label is the count, a number
    # that is a row reference ("row 4 cut", "rows 2, 3 fixed") is never a count, and "partly disputed" is
    # matched before "disputed" so its number is never also read as plain disputed.
    _rest, _seen = body[tm.end():], set()
    for pm in _RFA_PART.finditer(_rest):
        num, kind = pm.group(1), re.sub(r"\s+", " ", pm.group(2).lower())
        if kind in _seen:
            continue
        if re.search(r"\brows?\s*(?:\d+\s*(?:,|and|&)\s*)*$", _rest[:pm.start()], re.I):
            continue
        if kind == "disputed" and re.search(r"partly\s+$", _rest[:pm.start(2)], re.I):
            continue
        _seen.add(kind)
        parts[kind] = int(num) if num.isdigit() else _RFA_NUMW[num.lower()]
    # Coordinator follow-up 2026-10-14: no skip by omission. Fixes claimed with no kept .reviewed copy FAIL;
    # with no fixes claimed ("fixed: none"), there is nothing to trace and a missing copy passes.
    if not _os.path.isfile(dp + ".reviewed"):
        if parts["fixed"] > 0 or _RFA_ROWS.search(body):
            fail("REVIEW-FIX-APPLIED",
                 "the PRE-SEND REVIEW line counts %d finding(s) as fixed and there is no %s. Keep the draft the "
                 "reviewer read as <draft>.reviewed so the fixes can be checked."
                 % (parts["fixed"], _os.path.basename(dp + ".reviewed")))
        return
    if sum(parts.values()) != n:
        fail("REVIEW-FIX-APPLIED",
             "the PRE-SEND REVIEW line counts %d findings but %d fixed + %d disputed + %d partly disputed + %d cut "
             "= %d. TABLE-LAST (Rob, 2026-10-14): every finding is accounted for, as 'N fixed', 'N disputed', "
             "'N partly disputed' or 'N cut'." % (n, parts["fixed"], parts["disputed"], parts["partly disputed"],
                                                 parts["cut"], sum(parts.values())))
        return
    rows_m, none_m, text_m = _RFA_ROWS.search(body), _RFA_NONE.search(body), _RFA_TEXT.search(body)
    if not (rows_m or none_m or text_m):
        fail("REVIEW-FIX-APPLIED",
             "the PRE-SEND REVIEW line does not say 'fixed rows N, M', 'N fixed in text' or 'fixed: none'. TABLE-LAST: a fix the "
             "reviewer found is traced to the table row it changed, and this gate compares that row against %s. Examples: "
             "'PRE-SEND REVIEW: independent reviewer returned 3 findings; 2 fixed; 1 disputed because <reason>; fixed rows 2, 4' "
             "(report with a table); 'PRE-SEND REVIEW: independent reviewer returned 3 findings; 2 fixed in text; 1 disputed "
             "because <reason>' (report with no table); '...; 3 disputed because <reason>; fixed: none' (no fixes)."
             % _os.path.basename(dp + ".reviewed"))
        return
    if none_m and (rows_m or parts["fixed"]):
        fail("REVIEW-FIX-APPLIED",
             "the PRE-SEND REVIEW line says 'fixed: none' and also counts %d fixed%s."
             % (parts["fixed"], " and names fixed rows" if rows_m else ""))
        return
    if rows_m and not parts["fixed"]:
        fail("REVIEW-FIX-APPLIED", "the PRE-SEND REVIEW line names fixed rows but counts 0 findings fixed.")
        return
    if text_m:
        # OI-0256: a report with no next-steps table has no row to trace a fix to, so the traceable change is the
        # text itself: the draft, minus its PRE-SEND REVIEW line, must differ from the kept .reviewed copy.
        if rows_m or none_m:
            fail("REVIEW-FIX-APPLIED", "the PRE-SEND REVIEW line says 'fixed in text' and also names fixed rows or 'fixed: none'.")
            return
        if not parts["fixed"]:
            fail("REVIEW-FIX-APPLIED", "the PRE-SEND REVIEW line says 'fixed in text' but counts 0 findings fixed.")
            return
        if _next_steps_rows(text) is not None:
            fail("REVIEW-FIX-APPLIED", "the PRE-SEND REVIEW line says 'fixed in text' but this draft carries a next-steps "
                 "table. Name the changed rows ('fixed rows N, M').")
            return
        try:
            _rev = open(dp + ".reviewed", encoding="utf-8", errors="replace").read()
        except OSError:
            _rev = ""
        _norm = lambda s: re.sub(r"\n{3,}", "\n\n", s).strip()
        if _norm(text.replace(m.group(0), "", 1)) == _norm(_rev):
            fail("REVIEW-FIX-APPLIED", "the PRE-SEND REVIEW line says 'fixed in text' but this draft, without that line, is "
                 "identical to %s." % _os.path.basename(dp + ".reviewed"))
        return
    if rows_m:
        named = sorted({int(x) for x in re.findall(r"\d+", rows_m.group(1))})
        try:
            before = _next_steps_rows(open(dp + ".reviewed", encoding="utf-8", errors="replace").read()) or {}
        except OSError:
            before = {}
        after = _next_steps_rows(text)
        if after is None:
            fail("REVIEW-FIX-APPLIED",
                 "the PRE-SEND REVIEW line names fixed rows %s but this draft carries no next-steps table. %s"
                 % (", ".join(map(str, named)), "A report with no table has no row to trace, so write 'N fixed in text', for example: 'PRE-SEND REVIEW: independent reviewer returned 12 findings; 5 fixed in text; 7 disputed because <reason>'. The draft must then differ from the .reviewed copy."))
            return
        missing = [r for r in named if r not in after]
        same = [r for r in named if r in after and before.get(r) == after[r]]
        if missing or same:
            fail("REVIEW-FIX-APPLIED",
                 "the PRE-SEND REVIEW line says rows %s were fixed, but %s. TABLE-LAST: a counted fix must show as "
                 "a changed row between %s and this draft." % (
                     ", ".join(map(str, named)),
                     "; ".join(x for x in (
                         ("row %s is not in this draft's table" % ", ".join(map(str, missing))) if missing else "",
                         ("row %s is identical to the reviewed copy" % ", ".join(map(str, same))) if same else "")
                         if x),
                     _os.path.basename(dp + ".reviewed")))


THOROUGH_LINE = re.compile(r"^\s*\*{0,2}THOROUGH\*{0,2}\s*:", re.I | re.M)
# The five conditions, each recognised by a distinctive word so the line cannot be faked
# with five commas. Rob's definition, in his own field: criterion validated against the
# actual activity; every load-bearing number double-sourced or flagged single-source; at
# least one deliberate disconfirming pass; nothing in Claude's own column that could change
# what is written above it; rivals listed with the call that would kill each.
# *** ENUMERATION ADDED 2026-09-17 ON ROB'S APPROVAL - THE SIXTH CRITERION, AND THE GATE HAD
# NEVER TESTED IT. *** The live global field has said SIX since 2026-09-11 (CORRECTED 2026-09-17 FROM
# "since 2026-09-13", PER F-163-DATE-CORRECTION) - "criterion, sourcing,
# disconfirming pass, own column, rivals, enumeration" - while this list held five, so the sixth
# was unchecked on every reply for five days. It was found by reading the field's own dated
# backups as audit work, not by any check. THE VARIABLE IS NO LONGER CALLED FIVE: a name that
# states a count it does not hold is the stale-label defect this file exists to catch.
CRITERIA = [("criterion", re.compile(r"criterion", re.I)),
        ("sourcing",  re.compile(r"single.source|two source|second source|double.source", re.I)),
        ("disconfirm", re.compile(r"disconfirm|refut", re.I)),
        ("own-column", re.compile(r"own column|claude.column|downstream", re.I)),
        ("rivals",    re.compile(r"rival|killer", re.I)),
        ("enumeration", re.compile(r"enumerat|every place it could|searched and not searched|not searched", re.I))]
UNMET = re.compile(r"\bunmet\b|\bnot met\b|\bNO\b|\bmissing\b|\bnone run\b", re.I)
# *** R120, ROB 2026-09-29 17:53 PDT. *** 37 of 135 gated THOROUGH lines declared a criterion unmet
# and passed, because this check only asked that the admission sit in the first line. The 17:51 PDT
# reply shipped "THOROUGH: NOT MET on three criteria" when all three were closable in the same turn -
# a second source, rivals for the remedy, an independent reviewer. Rob's field: "YOU DO NOT DECIDE A
# CHECK IS IMPRACTICAL: where one cannot settle something, SAY SO PLAINLY, name the specific blocker
# and what would settle it". So an unmet criterion now needs BLOCKER: naming one of the classes the
# field itself allows - a credential, an approval or decision of Rob's, a physical act, an event
# that has not happened yet, or a quoted tool error. No blocker, no stamp: close the gap instead.
# "single-source, unverified" is NOT an unmet declaration and stays allowed - the ONE LAB rule
# permits it with the rating capped at 5.
STRICT_UNMET = re.compile(r"\bunmet\b|\bnot met\b|\bnone run\b|\bnot run\b|\bnot done\b|"
                          r"\bnot checked\b|\bskipped\b|\bincomplete\b|\bpartial(ly)?\b|"
                          r"\bmissing\b|\bnot fully\b|\bnot closed\b|deferr|\bnot attempted\b|"
                          r"\boutstanding\b|\bTODO\b|\bleft open\b|postpon|\bnot yet\b|waiv|"
                          r"\bnot performed\b|\bun-met\b|\bunverified\b", re.I)
# "single-source, unverified" is the ONE LAB rule's permitted wording and is removed before scanning.
_ONE_LAB = re.compile(r"single.source,?\s*(and\s*)?unverified", re.I)
# R120b: the blocker must point at a ROW of this reply's own table that is either open and owned
# by Rob, or Downstream / Waiting - a fact the table states, not a keyword. The keyword version
# passed "BLOCKER: I would approve it myself" and "BLOCKER: physical laziness".
ROW_BLOCKER = re.compile(r"BLOCKER:\s*(?:see\s+)?row\s+(\d+)", re.I)
THOROUGH_BLOCKER = re.compile(r"BLOCKER:\s*.{0,120}\b(credential|password|approval|approve|Rob's (decision|ruling|call)|"
                     r"physical|not (yet )?happened|has not happened|relaunch|tool error|error:)", re.I)

# *** THE FIVE CONDITIONS WERE CHECKED FOR THEIR WORDS AND NOT FOR THEIR TRUTH, AND THAT IS
# WHAT LET THREE ROUNDS THROUGH ON 2026-09-10. *** FIVE above is five keyword patterns. The
# sourcing one matches "single.source|two source|second source|double.source", so the line
# "numbers single-source nowhere" PASSED while the classification underneath had exactly one
# reader - the opposite of what the clause asserted. A gate that checks for the presence of a
# sentence teaches the writer to write the sentence, and the ritual then survives the substance.
# Rob asked "have you been thorough" three times that day and the answer was no three times,
# with the compliant line published in every round.
# SO THE SOURCING CLAUSE MUST NOW CITE. A line that CLAIMS more than one source, or that denies
# being single-sourced, needs a CHECKED line naming the second reader or the second instrument.
# Saying "single-source, unverified" is always allowed and always passes: the honest admission
# is the cheap path, which is the point.
SOURCING_CLAIM = re.compile(
    r"\b(two|second|double|multiple)[\s-]+(sources?|readers?|instruments?)\b|"
    r"single.source\s+(nowhere|on nothing|free)|\bnot\s+single.source\b|"
    r"\btwo\s+independent\b|\bindependently\s+(measured|derived|classified)\b", re.I)
SOURCING_EVIDENCE = re.compile(
    r"second reader|independent reader|two independent|second independent|"
    r"two instruments|independent instruments|two distinct instruments|"
    r"instruments agreeing|both instruments|recomputed .{0,40}independent|"
    r"blind (second|classifier|reader)", re.I)

# *** A RATING IS NOT THE ONLY SHAPE OF A RECOMMENDATION. *** check_thorough_five returned
# immediately unless RATING matched, so a reply that recommends switching something on without
# attaching a number skipped all five conditions. Widened 2026-09-10.
SHIPPING = re.compile(
    r"\b(recommend|recommendation)\b[^.]{0,80}\b(enabl\w+|ship\w*|turn\w* on|join\w*|"
    r"restor\w+|roll\w* out|switch\w* on|make it a fail|promote\w*)\b|"
    r"\b(enable it|turn it on|ship it|switch it on|restore fail|join CORPUS_CHECKS)\b", re.I)

# *** NOTHING ANYWHERE COMPARED THE POPULATION A FIGURE WAS MEASURED ON WITH THE POPULATION THE
# CHANGE WOULD RUN ON, AND THAT IS THE ONE GAP OF THE THREE THAT IS GENUINE COVERAGE. *** The
# live profile field was grepped on 2026-09-10 for six phrasings - deployed, population it will,
# where it will run, distribution, tuned on, measured on one - and all six returned ZERO.
# THE FAILURE IT EXISTS FOR: the acronym gate was tuned to zero false positives on 821 replies
# in ONE project and enabled across ELEVEN, and a four-population re-measure returned 34 percent.
# Every other rule in that field asks whether a number is RIGHT. None asks what it is a number
# ABOUT. Scoped to replies that BOTH recommend switching something on AND carry a rate, because
# that is the shape of the failure and a wider scope would fire on ordinary prose.
DEPLOY_POP = re.compile(
    r"will run (on|against)|runs on every|runs against|deployed (on|across|to)|"
    r"population it will|every reply in|across all \w+ project|"
    r"measured on .{0,40}\b(and|but)\b .{0,40}(runs|will run|applies)", re.I)
RATE_FIGURE = re.compile(r"\bfalse[- ]positives?\b|\d+(\.\d+)?\s*(percent|%)", re.I)


ASK_IN_PROSE = re.compile(
    r"(say the word|let me know|tell me whether|tell me which|if you(?:'| ha)ve already|"
    r"just say|your call|do you want me to|shall I|want me to)", re.I)


def check_prose_decision(text):
    """*** A DECISION ASKED IN PROSE IS A DECISION THAT IS NOT IN THE TABLE. ***

    ROB, 2026-08-25, quoting Claude's own closing line back at it: "Say the word and I
    re-export; say 'already commented' and I harvest first." -- "This should have been
    captured in the table of decisions."

    He is describing a rule this system already has twice over: THE TABLE IS THE NEXT-STEPS
    LIST, and an item he must decide carries Owner=Rob. A decision parked in the last
    sentence of a reply is invisible to the ranking, invisible to STOP-WHILE-UNBLOCKED, and
    invisible to him tomorrow.

    AND THE INSTANCE THAT TRIGGERED THIS WAS WORSE THAN MISPLACED - IT WAS UNNECESSARY.
    Whether he had already commented on the Doc was answerable by one tool call,
    read_file_content with includeComments=true, which returned zero comment threads. So the
    reply spent his attention on a question it could have answered itself. That is the
    offload defect wearing a politeness.

    THE CHECK: if the reply contains a next-steps table AND an asking phrase, at least one
    OPEN row must be owned by Rob. If none is, the reply is asking in prose for something the
    table does not carry.
    """
    if not ASK_IN_PROSE.search(text):
        return
    rows = _table_rows(text)
    if not rows:
        return
    open_rob = [r for r in rows if _is_open(r[2]) and _is_rob(r[3])]
    if not open_rob:
        m = ASK_IN_PROSE.search(text)
        fail("PROSE-DECISION",
             "this reply asks Rob for something in prose (%r) but no OPEN row in the table is "
             "owned by Rob. Either it is a decision, in which case it is a row, or it is a "
             "question Claude could have settled with a tool call, in which case make the call."
             % text[m.start():m.start() + 40].strip())


def retired_r155_thorough_five(text):
    # R155: renamed from check_thorough_five so neither the send path nor the selftest's derived
    # ALL list (every check_ function) can run it. Kept as the record of what was enforced.
    """*** THE FIX FOR THE COMPLAINT ROB HAS RAISED MOST OFTEN. ***

    Measured 2026-08-25 across 962 turns of this project: ROB asked "increase the confidence
    level" in 40 separate turns, 29 of them on 2026-08-15 between 21:30 and 23:58 - one ask
    roughly every five minutes for an evening. His field already says "I SHOULD NEVER HAVE TO
    ASK" and already defines a five-condition test for THOROUGH. NOTHING WAS MISSING. The
    rule simply fires on ROB'S WORDS, so the list only ran after he spent a turn asking.

    THIS CHECK MOVES THE TRIGGER FROM HIS WORDS TO CLAUDE'S DRAFT. A reply that carries a
    confidence rating is a reply making a recommendation, and it must show the five states
    first. One line satisfies it, so the cost is a line and the benefit is that "have you
    been thorough" stops being a question Rob has to ask.

    Cheapest compliant form:
        THOROUGH: criterion validated vs the activity - numbers single-source on X -
        disconfirming pass run - nothing in my own column that changes the above -
        rivals listed with their killers
    """
    _shipping = SHIPPING.search(text)
    # A WORD RATING INSIDE QUOTATION MARKS IS A QUOTATION, NOT A RATING. Measured 2026-09-29: all
    # 5 archived WORD_RATING hits were quotes - Rob's "are you extremely confident?" four times and
    # one of Claude's own examples. An odd count of double quotes on the line before the match
    # means the match sits inside a quotation.
    def _word_rated(t):
        for wm in WORD_RATING.finditer(t):
            ls = t.rfind("\n", 0, wm.start()) + 1
            if (t.count('"', ls, wm.start()) + t.count("“", ls, wm.start())) % 2 == 0:
                return True
        return False
    if not RATING.search(text) and not _shipping and not _word_rated(text):
        return
    m = THOROUGH_LINE.search(text)
    if not m:
        fail("THOROUGH-SIX",
             "this reply carries a confidence rating but no THOROUGH: line. Rob's five "
             "conditions have to be stated BEFORE the rating, not recalled after he asks. "
             "One line: criterion, sourcing, disconfirming pass, own-column, rivals, enumeration.")
        return
    line = text[m.start():m.start() + 600]
    missing = [name for name, rx in CRITERIA if not rx.search(line)]
    if missing:
        fail("THOROUGH-SIX",
             "the THOROUGH: line does not address %s. All six conditions must appear, and "
             "an unmet one is stated as unmet rather than omitted - omitting it is how the "
             "list stops being a test." % ", ".join(missing))
        return
    # ---- SOURCING MUST CITE, ADDED 2026-09-10. See the note beside SOURCING_CLAIM. ----
    if SOURCING_CLAIM.search(line):
        _checked = "\n".join(ln for ln in text.splitlines() if CHECKED_RE.match(ln))
        if not SOURCING_EVIDENCE.search(_checked):
            fail("THOROUGH-SIX",
                 "the THOROUGH line claims more than one source and no CHECKED line names a "
                 "second reader or a second instrument. On 2026-09-10 'numbers single-source "
                 "nowhere' passed this check over a classification with exactly ONE reader. "
                 "Either cite the second one above, or write 'single-source, unverified' and "
                 "cap the rating at 5 - which is the ONE LAB rule already in the field.")
            return
    # ---- DEPLOYED POPULATION, ADDED 2026-09-10. See the note beside DEPLOY_POP. ----
    if _shipping and RATE_FIGURE.search(text) and not DEPLOY_POP.search(text):
        fail("THOROUGH-SIX",
             "this reply recommends switching something on and carries a rate, but no line says "
             "what population it will RUN on. A rate measured on one population is not a rate "
             "for the population it will run against: on 2026-09-10 a gate tuned to zero on 821 "
             "replies in one project was enabled across eleven and re-measured at 34 percent.")
        return
    # R120: an unmet criterion with no blocker is a closable gap shipped as a disclosure.
    # R120b: THOROUGH_LINE's leading \s* can swallow the newline before the line, which made
    # this slice EMPTY on 179 of 317 archived THOROUGH lines. Start at the word itself.
    _ts = text.upper().find("THOROUGH", m.start())
    # R120c: the whole THOROUGH paragraph, up to the first blank line - an admission on line 2
    # passed the one-line version.
    _te = text.find("\n\n", _ts)
    _tl = _ONE_LAB.sub("", text[_ts:_te if _te > 0 else len(text)])
    _ok = False
    for _bm in ROW_BLOCKER.finditer(_tl):
        for _r in _table_rows(text):
            if str(_r[0]).strip() == _bm.group(1) and (
                    (_is_open(_r[2]) and _is_rob(_r[3])) or
                    re.search(r"downstream|waiting", _r[2], re.I)):
                _ok = True
    if STRICT_UNMET.search(_tl) and not _ok:
        fail("THOROUGH-SIX",
             "the THOROUGH: line declares a criterion unmet (%r) and cites no 'BLOCKER: row N' "
             "whose row is open and owned by Rob, or Downstream / Waiting. R120: announcing the gap "
             "is not closing it. Close it this turn, or put what blocks it in the table and cite "
             "the row." % STRICT_UNMET.search(_tl).group(0))
        return
    # Rob's rule: if any of the five is unmet, say which IN THE FIRST LINE, unasked.
    if UNMET.search(line) and m.start() > 400:
        fail("THOROUGH-SIX",
             "the THOROUGH: line reports an unmet condition but sits %d characters in. Rob's "
             "rule is that an unmet condition is named in the FIRST LINE, without being "
             "asked - buried, it reads as disclosure instead of the skip it is." % m.start())



# *** ROB'S RULE: PUTTING AN ITEM IN HIS COLUMN IS AN INCAPABILITY CLAIM WITH THE WORDS REMOVED. ***
# It fires the same rule as saying "I can't", and it needs the same evidence: a credential Rob
# holds and Claude does not, a device only he can touch, an approval or decision only he can give,
# a physical act, or a tool error Claude can quote.
#
# MEASURED 2026-08-28, WHICH IS WHY THIS EXISTS. A row was assigned to Rob reading "Open that
# project in a session and it re-reads itself; from here I can only reach this one." Rob's reply
# was "This doesn't make sense" - and it did not, because it was covering a misassignment. Every
# project was one authenticated API call away in a browser tab Claude already had working, and
# both projects were read from that session about a minute later. THE SENTENCE WAS NONSENSE
# BECAUSE THE BLOCKER WAS INVENTED; there was no real one to describe.
#
# THE TEST IS DELIBERATELY NARROW so it does not become a noisy channel. A Rob-owned row must
# contain one of a small vocabulary of REAL blockers. Effort, token budget, context window, number
# of tool calls and "it lives behind a UI" are NOT blockers and are not in the list.
BLOCKER = re.compile(
    r"\bpassword\b|\bcredential\b|\bapi key\b|\btoken\b|\bsign in\b|\blog in\b|"
    r"\bapprove\b|\bapproval\b|\bpermission\b|\bgrant\b|"
    r"\bdecide\b|\bdecision\b|\brule\b|\bruling\b|\bconfirm\b|\bchoose\b|\bpick\b|"
    r"\bpaste\b|\btype\b|\bclick\b|\bopen the\b|\bscreenshot\b|\bphysical\b|"
    r"\byour call\b|\byours\b|\bonly you\b|\bcannot be automated\b|"
    r"\breturned\b|\berror\b|\brefused\b|\b404\b|\bdenied\b", re.I)



JARGON = pathlib.Path(__file__).with_name(".jargon-terms.tsv")


def _load_jargon():
    """term -> list of plain words, ONE of which must appear in the same paragraph.

    *** WHY A REGISTRY AND NOT A CLEVERNESS TEST. *** "Is this jargon" is a judgement, and
    judgement rules measure 3-6% in this system. A registry is a list Rob can read, argue
    with and extend, and the check over it is mechanical: if a registered term appears in a
    paragraph, that paragraph must also contain one of its plain words. The gloss is
    therefore not merely encouraged, it is CHECKABLE - the same shape as REVIEW-LINK, where
    something named must carry a URL.

    SEEDED FROM THE THREE COMPLAINTS ROB ACTUALLY MADE ON 2026-08-31, not from a guess at
    what might confuse someone: "rule the key form for scripts", "rule them exempt / a
    permanently red suite", and "its cost profile rather than its verdict carries the proof".
    Every future entry should be added the same way - after he says he cannot follow it.
    """
    out = {}
    if not JARGON.exists():
        return out
    for raw in JARGON.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        c = raw.split("\t")
        if len(c) < 2 or not c[1].strip():
            continue
        out[c[0].strip().lower()] = [w.strip().lower() for w in c[1].split("|") if w.strip()]
    return out


def check_gloss(text):
    """A registered term must be glossed in the paragraph that uses it.

    Rob, three times in one session: "What does this mean?", "I have no idea what this
    means." The rule against jargon already exists in his field - "Blunt, directive phrasing
    aimed at the reasoning" - and it is enforced by nothing. This is the enforcement.
    """
    terms = _load_jargon()
    if not terms:
        return
    # *** SCOPED TO THE SENTENCE, NOT THE PARAGRAPH, AND THE LOOSER VERSION WAS MEASURED FIRST.
    # Run against the exact paragraph Rob said he could not follow, paragraph scope caught ONE
    # of the three phrases: "cost profile" was excused by the word "seconds" in a DIFFERENT
    # sentence, and "carries the proof" by a "because" that explained something else. A gloss
    # that happens to sit nearby is not a gloss - the reader has to do the joining. Sentence
    # scope catches two of the three; the third is genuinely glossed by its own "because".
    for para in re.split(r"\n\s*\n", text):
        if para.lower().lstrip().startswith("checked:"):
            continue                      # CHECKED lines are evidence, not prose
        for sent in re.split(r"(?<=[.!?])\s+", para):
            low = sent.lower()
            for term, plain in terms.items():
                if term not in low:
                    continue
                if any(w in low for w in plain):
                    continue
                fail("GLOSS",
                     "the phrase %r is used with no plain-language gloss in the SAME "
                     "SENTENCE. Rob has said three times he cannot follow this kind of "
                     "shorthand. Say it in ordinary words beside it, or cut it. Registered "
                     "plain words: %s" % (term, ", ".join(plain)))

def check_own_column(text):
    """Fail a Rob-owned next-steps row that names no real blocker."""
    bad = []
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if len(cells) < 4:
            continue
        row = " ".join(cells)
        # *** DO NOT INDEX THE OWNER COLUMN BY POSITION. *** TABLE_ROW's group(2) excludes the
        # leading rank cell, so the owner sits at index 2 in the six-column shape and elsewhere in
        # the three-column one. The first version of this check read cells[3] - the Recommendation -
        # and reported zero Rob-owned rows while looking straight at one. That is
        # selection-by-wrong-key, committed inside the check written to catch a different instance
        # of the same class, which is why the owner is now found by CONTENT.
        owner = next((c for c in cells if c.strip().lower() in ("rob", "claude", "rob, terminal",
                                                                "claude, terminal")), "")
        if owner.strip().lower() != "rob":
            continue
        if not BLOCKER.search(row):
            bad.append(cells[1][:60] if len(cells) > 1 else row[:60])
    if bad:
        fail("OWN-COLUMN",
             "%d row(s) assigned to Rob name no real blocker: %s. Putting an item in his column is "
             "an incapability claim with the words removed - it needs a credential he holds, a "
             "device only he can touch, an approval or decision only he can give, a physical act, "
             "or a tool error you can quote. Effort and 'it lives behind a UI' are not blockers."
             % (len(bad), "; ".join(bad[:4])))



# *** A CALL, A BOOKING OR A SCHEDULING ERRAND MAY NEVER BE ASSIGNED TO ROB. ADDED 2026-09-06
# AFTER THE THIRD OCCURRENCE. *** He ruled it twice on 2026-09-02 - "Remove all tasks on me to
# call/schedule something", then "Didn't I tell you to remove all the actions on me to call
# them?" - and it happened again on 2026-09-05, when BOOK THE FIRST APPOINTMENT was put in his
# column and he replied "Take the action on me off this list".
# The Doctors for Back Pain project field already forbids it in words: "DO NOT PUT PHONE CALLS ON
# ROB'S LIST... put it in the ASK ON THE CALL column of the relevant tab so it is asked at the
# moment of booking, rather than assigning it as a separate errand."
# A rule stated three times and broken three times is not an attention problem, it is a missing
# check. OWN-COLUMN does not catch it because a phone call HAS a real blocker - only Rob can
# speak to a receptionist - so the row passes every existing gate while being exactly the thing
# he has banned.
CALL_ERRAND = re.compile(r"\b(call|calling|phone|ring|book|booking|schedule|scheduling|"
                         r"make an appointment|confirm with the (?:practice|office|clinic))\b", re.I)
CALL_EXEMPT = re.compile(r"\bask on the call\b|\bcall list\b|\bcall questions?\b|"
                         r"\bwhen (?:he|she|they) calls?\b|\bat the moment of booking\b", re.I)


# *** THE CONTROL ABOVE WENT DARK ON A QUALIFIED OWNER CELL, MEASURED 2026-09-07. ***
# The owner was found with `c.strip().lower() in ("rob", "claude")`, which demands the cell be
# EXACTLY that word. On 2026-09-07 two replies shipped rows whose Owner cells read "Rob, at the
# call" and "Claude, until the call". Neither matches, so owner came back "" and CALL-ON-ROB
# skipped both rows - the fixture ran clean while carrying the exact thing the check exists to
# stop, and Rob's answer was "I've asked you this a ton of times."
# TWO FIXES, BOTH KEYED ON WHAT WAS ACTUALLY MEASURED:
#   1. Normalise the owner to the token before the first comma, dash, paren or slash, so a
#      qualifier cannot hide the name.
#   2. AN OWNER CELL QUALIFIED BY A CALL IS A CALL ERRAND WHATEVER NAME IT CARRIES. "Claude,
#      until the call" hands the work to the call, which is Rob's mouth; labelling it Claude
#      only moves the label. Fail on the qualifier itself, either owner.
# The qualifier is the tell, so it is what the check reads - not the wording of the Item cell,
# which can always be reworded (the lesson OPEN-ROW-LINK already records).
OWNER_QUALIFIED_BY_CALL = re.compile(
    r"^(rob|claude)\b\s*[,(\-/].*\b(call|calls|calling|phone|booking|book|"
    r"appointment|schedule|scheduling)\b", re.I)


def _owner_of(cells):
    """Owner cell, normalised to the bare name. Returns (name, raw_cell)."""
    for c in cells:
        head = re.split(r"[,(\-/\u2014\u2013]", c.strip(), maxsplit=1)[0].strip().lower()
        if head in ("rob", "claude"):
            return head, c.strip()
    return "", ""


def check_call_on_rob(text):
    """Fail any Rob-owned row that assigns a call, a booking or a scheduling errand,
    and any row of either owner whose owner cell is qualified by a call."""
    bad = []
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if len(cells) < 4:
            continue
        owner, owner_raw = _owner_of(cells)
        label = cells[0][:60] if cells else " ".join(cells)[:60]
        if OWNER_QUALIFIED_BY_CALL.search(owner_raw):
            bad.append("%s [owner cell: %s]" % (label, owner_raw[:40]))
            continue
        if owner != "rob":
            continue
        row = " ".join(cells)
        if CALL_ERRAND.search(row) and not CALL_EXEMPT.search(row):
            bad.append(label)
    if bad:
        fail("CALL-ON-ROB",
             "%d row(s) assign Rob a call, a booking or a scheduling errand: %s. He has ruled "
             "this out three times - 2026-09-02 twice and 2026-09-05 - and the project field "
             "says so in words: do not put phone calls on his list; put the question in the ASK "
             "ON THE CALL column so it is asked at the moment of booking. This passes OWN-COLUMN "
             "because a call DOES have a real blocker, which is exactly why it needs its own "
             "check." % (len(bad), "; ".join(bad[:4])))


# *** ROB RULED EXERCISE ITEMS OFF THE NEXT-STEPS TABLE ON 2026-09-09, AND THE RULING WAS NEVER
# WRITTEN INTO ANY LAYER, SO THE COMPACTION THAT ENDED THAT SESSION ERASED THE ONLY PLACE IT
# LIVED. On 2026-09-10 the full-project audit put the loaded stair session and the downhill
# preconditioning session back on his list, and he answered "WHY AM I SEEING IT AGAIN???".
# A RULING HELD ONLY IN A TRANSCRIPT IS A RULING WITH A DELETION DATE. This control is the
# copy that cannot be compacted away.
EXERCISE_ERRAND = re.compile(
    r"\b(stair session|loaded stair|downhill|precondition\w*|conditioning|workout|"
    r"training session|exercise|walk down|eccentric)\b", re.I)
EXERCISE_EXEMPT = re.compile(r"\b(air.?condition\w*|conditional|conditioned on)\b", re.I)


def check_exercise_on_rob(text):
    """Fail any Rob-owned row that assigns an exercise, training or conditioning session."""
    bad = []
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if len(cells) < 4:
            continue
        owner, _raw = _owner_of(cells)
        if owner != "rob":
            continue
        row = " ".join(cells)
        if EXERCISE_ERRAND.search(row) and not EXERCISE_EXEMPT.search(row):
            bad.append(cells[0][:60])
    if bad:
        fail("EXERCISE-ON-ROB",
             "%d row(s) put an exercise, conditioning or training session in Rob's column: %s. "
             "He ruled these off the next-steps table on 2026-09-09 and had to say it again on "
             "2026-09-10. The sessions live on his CALENDAR, which already carries them with "
             "dates, reasons and both names; repeating one here is a second copy of a list he "
             "already has. It passes OWN-COLUMN because a physical act IS a real blocker, which "
             "is exactly why it needs its own check." % (len(bad), "; ".join(bad[:4])))


# *** THE SAME SHAPE, ONE LAYER OVER: GEAR AND ORDERS BELONG ON THE PACKING ARTIFACT, NOT HERE.
# The Yosemite project field already states this in words and even prescribes the test - "before
# putting a row in Rob's column, search the artifact for it" - and on 2026-09-10 I published a
# row about a shoe that has its own artifact row. A TEST WRITTEN IN PROSE IS A TEST NOBODY RUNS.
ARTIFACT_ITEM = re.compile(
    r"\b(shoe|shoes|boot|boots|sock|socks|pack|backpack|cooler|lighter|coffee|filter|"
    r"tablet|tablets|pole|poles|glove|gloves|headlamp|bladder|insole|permethrin|"
    r"leukotape|benzoin|order [A-Z0-9]{6,}|arrives|delivery|deliver\w*|ships?|shipping)\b", re.I)


def check_artifact_item_on_rob(text):
    """Fail any Rob-owned row naming gear or a delivery that belongs on the packing artifact."""
    bad = []
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        while cells and cells[-1] == "":
            cells.pop()
        if len(cells) < 4:
            continue
        owner, _raw = _owner_of(cells)
        if owner != "rob":
            continue
        row = " ".join(cells)
        if ARTIFACT_ITEM.search(row):
            bad.append(cells[0][:60])
    if bad:
        fail("ARTIFACT-ITEM-ON-ROB",
             "%d Rob-owned row(s) name gear, an order or a delivery: %s. Those live on the "
             "published packing artifact, which carries its own dated jobs and owners. The "
             "project field already ordered the test - search the artifact for the row before "
             "writing it - and prose did not make anyone run it. DUPLICATION IS THIS PROJECT'S "
             "RECORDED FAILURE MODE; four retired pack lists are the evidence."
             % (len(bad), "; ".join(bad[:4])))


# *** WRONG-DENOMINATOR IS THE LARGEST MECHANICAL FAILURE CLASS IN THIS PROJECT: 10 OCCURRENCES,
# FIVE OF THEM ON 2026-08-28. *** Every one is a count or a percentage published without naming
# the SET it was measured over, and in each case the set turned out to be the wrong one:
#
#   F135  333 rows "misjudged by READ_PAT" - measured across the whole row when the gate reads
#         only the [evidence:] tag. The fix moved EIGHT.
#   F136  five OUT OF SCOPE rows offered as proof a widening was needed - sampled from all 998
#         instead of the 553 FAILING ones. Those five already passed.
#   F137  27 rows reported as double-wrapped - measured my own output format as if it were data.
#         Zero exist.
#   F143  "list_triggers returned FOUR" - it returned three.
#   F151  14 ledger rows given a prose CAUSE - failurecheck groups on the full string, so they
#         became 14 singletons in a file whose rule is "a cause seen twice is a class".
#
# THE CHECK: a bare count or percentage in a CHECKED line must name what it was measured over.
# "6,103 of 6,154" passes. "51 failing" passes - the noun names the set. "98.2%" alone does not.
# DELIBERATELY SCOPED TO CHECKED LINES, because that is where Rob acts on a number, and because
# prose carries figures that are quotations rather than measurements.
DENOM_OK = re.compile(
    # "of" FOLLOWED BY ANYTHING NAMES A POPULATION, not just by a number. The first version
    # required \bof\s+[\d,]+ and failed "6% of section-9 markers" - a line that names its set
    # perfectly well. A false positive here is worse than a miss: it trains the reader to ignore
    # the channel, which is the noisy-alarm failure P2-33 already measured.
    r"\bof\s+\w|\bacross\s+\w|\bout of\b|\bfrom\s+[\d,]+|/\s*[\d,]{2,}|"
    r"\brows?\b|\bfiles?\b|\bitems?\b|\bentr(?:y|ies)\b|\bsites?\b|\btasks?\b|"
    r"\bskills?\b|\bsessions?\b|\bcontrols?\b|\bgates?\b|\bcolumns?\b|\bmembers?\b|"
    r"\bchars?\b|\bcharacters\b|\blines?\b|\bbytes?\b|\bB\b|\bpages?\b", re.I)
BARE_PCT = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d+)?\s*%")


def check_denominator(text):
    """A percentage on a CHECKED line must name the set it was measured over."""
    bad = []
    for ln in text.splitlines():
        t = ln.strip()
        if not t.startswith("CHECKED:"):
            continue
        if not BARE_PCT.search(t):
            continue
        if DENOM_OK.search(t):
            continue
        bad.append(t[:78])
    if bad:
        fail("DENOMINATOR",
             "%d CHECKED line(s) carry a percentage that names no population: %s. WRONG-DENOMINATOR "
             "is this project's largest failure class at 10 occurrences - every one was a number "
             "measured over a set that turned out to be the wrong one. Say what it is a percentage "
             "OF." % (len(bad), " | ".join(bad[:3])))

def check_split_by_owner(text):
    """RULED BY ROB 2026-08-25: one stack-ranked list, never two broken by owner.

    This REPLACES check_rank_sections / RANK-OWNER, which enforced the opposite - that the
    'Blocked on Rob' section sit above 'Claude can do now'. That rule presumed the split.
    With one ranked list the owner is a COLUMN and never a sort key, so a check that ranks
    by owner would now fight the ranking rules it is supposed to protect.
    """
    if SECTION_ROB.search(text) and SECTION_ME.search(text):
        fail("SPLIT-BY-OWNER",
             "this reply splits next steps into 'Blocked on Rob' and 'Claude can do now'. "
             "Rob ruled 2026-08-25: one stack-ranked list, owner is a column. Rank by "
             "dependency and impact, and put the owner in the Owner cell.")


def check_rank_contradiction(text):
    tail = next_steps_block(text)
    items = LIST_ITEM.findall(tail)
    if len(items) < 2:
        return
    idx = _rank_index(items)

    def resolve(chunk, default):
        for tok in IDTOK.findall(chunk):
            if tok.upper() in idx:
                return tok.upper(), idx[tok.upper()]
        for a, b in LABEL.findall(chunk):
            lab = (a or b).strip().lower()
            if lab in idx:
                return lab, idx[lab]
        return default

    for i, item in enumerate(items, 1):
        for m in DEP_RE.finditer(item):
            obj = resolve(m.group("obj"), None)
            if not obj:
                continue
            # the subject clause may name a DIFFERENT item as the dependent one
            dep_name, dep_pos = resolve(m.group("subj"), (None, i))
            if obj[1] == dep_pos:
                continue
            if obj[1] > dep_pos:
                fail("RANK-DEPENDENCY",
                     "#%d %r is ranked below #%d %r which depends on it. "
                     "A dependency below its dependent means the list cannot be run in order."
                     % (obj[1], obj[0], dep_pos, dep_name or "the item itself"))

    low = [i for i, it in enumerate(items, 1) if LOWPRI.search(it)]
    high = [i for i, it in enumerate(items, 1) if HIGHPRI.search(it)]
    for l in low:
        for h in high:
            if l < h:
                fail("RANK-PRIORITY",
                     "#%d says it can wait and ranks above #%d which says it is urgent. "
                     "The notes and the ranking assert opposite things." % (l, h))
                return


# ---------- 9. UNOWNED WORK ----------
MINE = re.compile(r"(?:^|\||owner\s*[:=]|assigned to)\s*(?:\*\*)?\s*(?:you|rob)\b", re.I | re.M)
READ_VERB = re.compile(r"\b(check|open|read|look at|confirm|verify|count|review|list)\b", re.I)
PHYSICAL = re.compile(r"(approv|decid|credential|password|token you|physically|trigger|sign in|log in|permission)", re.I)


def check_ownership(text):
    tail = next_steps_block(text)
    for item in LIST_ITEM.findall(tail):
        if not MINE.search(item):
            continue
        if READ_VERB.search(item) and not PHYSICAL.search(item):
            warn("UNOWNED",
                 "item assigned to you is a read/verify action with no physical blocker named: %r" % item[:80])


# *** ADDED 2026-09-11. A CONSTRAINT ATTRIBUTED TO ROB'S OWN INSTRUCTIONS IS THE ONE CLAIM
# HE HAS NO REASON TO DOUBT, WHICH IS EXACTLY WHY IT NEEDS A GATE. ***
# THE FAILURE: Claude wrote "Parked by your instruction to park operational work" in two
# consecutive replies, an hour AFTER overwriting the field that carried that sentence. The
# replacement does not contain it. The rule was cited from memory of a file Claude had itself
# edited - which the profile field forbids in those words: "Your memory of a file you edited
# an hour ago is not the file."
# WHY NOTHING CAUGHT IT: TOOL-DEADEND and OFFLOAD key on phrasing that SOUNDS like an
# incapability - "I can't", "no access", "worth checking on your end". "Parked by your
# instruction" sounds like obedience. Its EFFECT is "I did not check this"; its TONE is
# deference, so every phrase-shaped gate read it as compliance and passed it.
# THE CHECK: attributing a live constraint to Rob's instructions requires a CHECKED line that
# shows the field was actually read this reply. Quoting the rule back at him is an assertion
# about the current state of a file, not transcription.
INSTRUCTION_CLAIM = re.compile(
    r"\b(parked|blocked|barred|forbidden|prohibited|not allowed|instructed|told)\b[^.\n]{0,60}"
    r"\b(by|per|under)\s+(your|the project|Rob's)\s+(project\s+)?instruction", re.I)
INSTRUCTION_CLAIM2 = re.compile(
    r"\b(your|the project)\s+(project\s+)?instructions?\s+"
    r"(say|says|state|states|tell|told|require|requires|forbid|forbids|ban|bans|rule|ruled)", re.I)
INSTRUCTION_CHECKED = re.compile(
    r"^\s*(?:[-*>]\s*)?(?:\*\*)?CHECKED[^\n]*\b"
    r"(instructions?|prompt_template|project field|the live field|conversation_preferences)\b",
    re.I | re.M)


_INSTR_STOP = {"the", "and", "for", "with", "that", "this", "your", "work", "them", "they",
               "from", "into", "about", "rather", "than", "doing", "does", "when", "what",
               "instruction", "instructions", "project", "rather"}


def check_cited_instruction(text):
    """INSTRUCTION-UNREAD: a rule of Rob's is cited as binding with no read to back it.

    *** THE FIRST VERSION OF THIS CHECK PASSED THE TWO REPLIES IT WAS WRITTEN FOR. ***
    Its guard accepted ANY CHECKED line containing the word "instructions", and both offending
    replies happened to carry one about a DIFFERENT field - the profile warning, the project
    write. So the gate built to stop a pass-it-did-not-earn earned a pass it did not deserve,
    and only running it against the real shipped text exposed that; the synthetic control I
    wrote from memory of the phrasing had passed cleanly.
    THE GUARD IS NOW TIED TO THE CITED RULE'S OWN WORDS: a CHECKED line has to mention what the
    rule was ABOUT, not merely that instructions exist.
    """
    m = INSTRUCTION_CLAIM.search(text) or INSTRUCTION_CLAIM2.search(text)
    if not m:
        return
    checked_blob = "\n".join(ln for ln in text.splitlines() if CHECKED_RE.match(ln)).lower()
    # What was the rule about? Only the clause that follows the citation, cut at the first
    # punctuation - a wider window pulls in filler like "does" that any CHECKED line contains.
    tail = re.split(r"[.,|—–\-\n]", text[m.end():m.end() + 90].lower())[0]
    topic = [w for w in re.findall(r"[a-z]{4,}", tail) if w not in _INSTR_STOP][:4]
    if topic and any(w in checked_blob for w in topic):
        return
    if not topic and INSTRUCTION_CHECKED.search(text):
        return
    frag = text[m.start():m.start() + 70].replace("\n", " ").strip()
    fail("INSTRUCTION-UNREAD",
         "a constraint is attributed to Rob's own instructions (%r) with no CHECKED line showing "
         "the field was read in this reply. On 2026-09-11 that exact shape cited a rule Claude had "
         "deleted an hour earlier. Citing his rule back at him is the claim he is least likely to "
         "challenge, so it carries the same burden as any other claim about a system: read the "
         "field, quote it, then cite it." % frag)


# ---------- 10. CHECKS-AT-TOP ----------
def check_position(text):
    if not CHECKED_RE.search(text):
        return
    first = CHECKED_RE.search(text).start()
    prose_before = len(re.sub(r"\s+", " ", text[:first]).strip())
    if prose_before > 400:
        fail("CHECKS-LATE",
             "%d chars of prose precede the first CHECKED line. Written last, checks only record; "
             "written first, they gate." % prose_before)


# ---------- 11. VOICE MECHANICS ----------
# PORTED FROM voicelint.py 2026-08-16 AND THAT FILE IS NOW DELETED. Rob ruled: one tool for
# one job. voicelint was built on 2026-08-16 in the belief that no pre-send linter existed —
# it did, and it was this file, one day older and covering far more. THE DUPLICATE WAS THE
# DEFECT; these four checks were the only thing it had that this file did not.
# Every rule below is quoted from the live global field, not invented.

HYPE = ("amazing", "powerful", "seamless", "game-changing")   # "named so the ban is checkable"


def check_voice(text):
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    scrub = QUOTED.sub(lambda m: " " * len(m.group(0)), body)

    for w in HYPE:
        m = re.search(rf"\b{re.escape(w)}\b", scrub, re.I)
        if m:
            fail("HYPE", "hype word %r - the ban is checkable and this is on the list." % w)

    # "Plain punctuation." Three or more em dashes in one paragraph is a pile-up.
    for para in re.split(r"\n\s*\n", scrub):
        n = para.count("—")
        if n >= 3:
            warn("EMDASH", "%d em dashes in one paragraph. Plain punctuation." % n)

    # "Short declarative sentences, 12-20 words, varied." Reported as a RATE: the rule says
    # VARIED, so one long sentence is not a defect and a high share of them is.
    sents = [s for s in sentences(scrub)
             if not s.lstrip().startswith(("|", "-", "*", ">", "#"))]
    if sents:
        long_ = [s for s in sents if len(s.split()) > 30]
        if len(long_) / len(sents) > 0.25:
            warn("SENTENCE-LEN", "%d of %d sentences over 30 words (%.0f%%). Rule is 12-20, varied."
                 % (len(long_), len(sents), 100 * len(long_) / len(sents)))


# ---------- CORPUS RATE MODE ----------
# The one thing voicelint had that a per-reply linter cannot do: score a whole session
# history and emit a COMPLIANCE RATE. A rate moves and can be argued with; a per-reply
# verdict cannot show a trend.
# *** ALWAYS PASS --max-chars. *** session_scan.py defaults to 1500 and TRUNCATES each turn.
# The first rate ever published from this code was 89%, measured on 162 KB of a 366 KB
# corpus, and the rule RANKING was wrong as a result: em-dash read 2 and was actually 88.
# ---------- REVIEW-LINK, added 2026-08-26 after P8-14 was reopened ----------
# THE RULE ALREADY EXISTED IN THREE PLACES AND STILL RAN AT ZERO. P8-14 was marked DONE,
# SUMMARY-SPEC.md carries it, and Rob specified it twice in one Cowork - once as a Links
# column and again as "add the URL to the Item column". The reply he APPROVED THE PLAN IN
# carried eleven rows and no links at all, and he answered "Where are the links to what I'm
# supposed to be review???". A rule in a spec is not a check.
#
# NARROW ON PURPOSE. It fires only on a row naming something OPENABLE - a file with a known
# extension, or a named artifact noun like Plan/ledger/Doc/log - and only when that row has
# no markdown link and no bare URL. Rows about physical acts ("open a terminal") have nothing
# to link and must not trip it.
REVIEWABLE = re.compile(
    r"(\b[\w./-]+\.(md|tsv|json|py|sh|txt|csv|html)\b"
    r"|\bthe plan\b|\bledger\b|\bscratchpad\b|\bprotocol\b|\bintake\b"
    r"|\bgoogle doc\b|\bthe doc\b|\bspreadsheet\b|\bthe sheet\b|\binventory\b)", re.I)
# *** computer:// ADDED 2026-08-26, CAUGHT BY ROB: "Where is the link?" ***
# This accepted ONLY http(s). Files that exist only on the laptop - EDIT-LOG.tsv, log-edit.sh,
# everything under bin/ - have no Drive copy and therefore no http URL, so a row naming one
# COULD NOT BE MADE TO PASS BY ANY MEANS. Measured before fixing: adding the correct
# computer:///Users/robk/... citation left REVIEW-LINK failing and merely changed the filename
# it printed in the error. A GATE THAT THE CORRECT ANSWER CANNOT SATISFY PRESSURES THE WRITER
# TOWARD THE WRONG ONE - dropping the link - which is exactly what I did, and Rob caught it
# rather than the gate. computer:// is the form the Cowork interface renders for local files.
HAS_LINK = re.compile(r"\]\((?:https?|computer)://|(?:https?|computer)://\S+")
# Anything that is an ACT rather than an ARTIFACT - nothing to open, so no URL is owed.
PHYSICAL_ROW = re.compile(
    r"\b(terminal|run a .{0,20}session|approve|ratify|decide|decision|delete|"
    r"physical|your machine|log ?in|credential)\b", re.I)


def check_review_link(text):
    """REVIEW-LINK: a table row naming an openable artifact must carry its URL."""
    bad = []
    for m in TABLE_ROW.finditer(text):
        row = m.group(0)
        if HAS_LINK.search(row) or PHYSICAL_ROW.search(row):
            continue
        hit = REVIEWABLE.search(row)
        if hit:
            bad.append((m.group(1), hit.group(0)[:40]))
    if bad:
        fail("REVIEW-LINK",
             "%d table row(s) name something Rob has to open and carry NO url: %s. "
             "P8-14 and SUMMARY-SPEC both require the URL on the Item label."
             % (len(bad), ", ".join(f"row {i} ({w})" for i, w in bad[:4])))


# ---------- COMMIT-THEN-STOP, added 2026-08-26 ----------
# A DISTINCT DEFECT FROM RATING-CLOSABLE, AND WORSE. RATING-CLOSABLE catches a falsifier that
# NAMES unrun work. This catches a reply that CLAIMS THE WORK IS UNDERWAY and then ends:
#
#   "That last sentence is itself a check I can run, so I'm running it rather than leaving it
#    as a caveat."   <- final sentence of the reply. Nothing followed it.
#
# Rob: "Why did you stop?" RATING-CLOSABLE cannot fire here, because the sentence does not
# confess an omission - it asserts the opposite. A present-tense commitment in the LAST
# paragraph is self-refuting: the turn ends there, so whatever is claimed to be in progress
# demonstrably is not. The tense is the tell, and it is mechanical.
#
# SCOPED TO THE TAIL ON PURPOSE. Mid-reply narration ("I'm running the selftest now") is
# followed by the actual run and is fine. Only the closing region is checked.
COMMIT = re.compile(
    r"\b(i'?m (running|building|doing|starting|checking|testing|fixing) it"
    r"|so i'?m (running|building|doing|starting|checking)"
    r"|i am (running|building|starting) (it|that|this)"
    r"|running it (now|rather than)"
    r"|starting (it |that )?now"
    r"|i'?ll (run|build|do) (it|that) (now|next)"
    r"|taking it next|doing that now)", re.I)


def check_commit_then_stop(text):
    """COMMIT-THEN-STOP: a present-tense commitment in the closing region of a reply."""
    tail = text[-700:]
    m = COMMIT.search(tail)
    if m:
        fail("COMMIT-THEN-STOP",
             "the reply CLOSES by claiming work is underway: %r. The turn ends here, so it "
             "is not. Either do it in this turn or write what is not yet done."
             % m.group(0)[:70])


# ---------- LINK-RESOLVES, added 2026-08-27 after the THIRD link failure ----------
# THE GATE HISTORY, BECAUSE THE FIRST TWO GATES BOTH PASSED THE ROW THAT WAS WRONG:
#   REVIEW-LINK asks "is a URL present?"          -> passed
#   LINK-REUSE  asks "does one URL serve many?"   -> passed
#   NOTHING asked "does the URL go where its label says?"
# The P2-22 row carried a URL for THREE consecutive replies; it resolved to
# AUDIT-PROTOCOL.md while its label named P2-22-REVIEW.md. Rob found it by asking
# where Option C was. Two green gates and a wrong link is worse than no gate, because
# green is read as checked.
#
# WHAT THIS CHECKS, AND ONLY THIS: for a computer:// link - a LOCAL path, resolvable
# offline with no network and no credentials - the target must EXIST, and its basename
# must appear in the row's visible text. A row whose label says one file and whose href
# names another is the exact failure above.
#
# WHY IT IS SCOPED TO computer:// AND NOT http(s). Fetching a Drive URL to compare its
# title needs the network and Rob's session, so it cannot run inside a pre-send gate and
# would fail open every time it could not fetch - a check that silently passes when it
# cannot run is decoration. The local half is fully checkable, so the local half ships.
# THE http(s) HALF IS UNCOVERED AND SAYS SO RATHER THAN PRETENDING.
FILE_TOKEN = re.compile(r"\b[\w.-]+\.(?:md|tsv|csv|py|sh|json|txt|html|jsonl|yaml|yml|log)\b")
def _project_script_stems():
    """Script stems under the project's bin/, read from disk each run."""
    try:
        d = pathlib.Path.home() / "Claude/Improving-my-Claude/bin"
        return {p.stem.lower().replace("-", "").replace("_", "") for p in d.glob("*.py")}
    except Exception:
        return set()


COMPUTER_LINK = re.compile(r"\[([^\]]+)\]\(computer://([^)]+)\)")


def _visible_row_text(row):
    """The row with markdown link TARGETS stripped but LABELS kept."""
    return re.sub(r"\]\((?:https?|computer)://[^)]+\)", "]", row)


def check_link_resolves(text):
    """LINK-RESOLVES: a computer:// target must exist and match the label naming it."""
    missing, mismatched = [], []
    for m in TABLE_ROW.finditer(text):
        row = m.group(0)
        vis = _visible_row_text(row)
        for lm in COMPUTER_LINK.finditer(row):
            label, path = lm.group(1), lm.group(2)
            # *** PERCENT-DECODE FIRST. FOUND 2026-09-26 BY AN INDEPENDENT REVIEWER. ***
            # A path with a space MUST be written %20 inside a markdown link target, or the
            # link breaks. This check tested the encoded string against the filesystem and
            # reported DO NOT EXIST for two paths that both resolve. A gate emitting false
            # failures on correct input is worse than no gate: it trains its reader to
            # discount it, which is the same defect CHECK 8 of the watchdog warns about.
            path = unquote(path)
            if not os.path.exists(path):
                missing.append((m.group(1), os.path.basename(path)))
                continue
            base = os.path.basename(path.rstrip("/"))
            # *** THE CRITERION WAS WRONG ON ITS FIRST RUN AND IS NARROWED HERE. ***
            # First draft required the target's basename to appear in the row's visible
            # text. Measured against a real published table: 7 of 7 rows flagged, precision
            # ZERO. SUMMARY-SPEC requires the Item cell to be a CAPS CONCEPT LABEL, not a
            # filename, so the first draft forbade the very convention the spec mandates.
            # A gate that fires on correct output is worse than no gate.
            #
            # THE ACTUAL P2-22 DEFECT was narrower: the row's own text NAMED A FILE
            # (P2-22-REVIEW.md) and the href went to a DIFFERENT file. So this only fires
            # when the visible text contains a file-like token AND none of those tokens is
            # the href's basename - a row that contradicts itself. A conceptual label with
            # no filename in it cannot contradict anything and is left alone.
            named = set(FILE_TOKEN.findall(vis))
            if named and base not in named:
                mismatched.append((m.group(1), sorted(named)[0][:24], base))
                continue
            # *** SECOND SHAPE, MEASURED BEFORE SHIPPING, 2026-08-27. ***
            # Rob asked whether the links in a table were accurate. Hand-labelling all 60
            # distinct (label, target) pairs from the session found SEVENTEEN mismatches -
            # 28% - where the label names one artifact and the href points at another. The
            # branch above catches none of them, because those rows name no file TOKEN.
            #
            # THIS RULE WAS SCORED BEFORE BEING WIRED IN, on those same 60 pairs: it fires
            # on 2, both real, with ZERO false positives. Precision 100%, recall 12%. That
            # is deliberately narrow. The other 15 mismatches - REPLY AUDITOR pointing at
            # gates.py, SILENT EXPIRY at gates.py, THE 43% FLOOR at PLAN-ITEMS - need to
            # know which artifact a concept label refers to, which no regex can do. Shipping
            # the narrow half beats guessing at the rest; the earlier version of this check
            # fired on 7 of 7 CORRECT rows and had to be withdrawn.
            #
            # THE KNOWN SET IS DERIVED FROM DISK, NOT TYPED. An include list of script names
            # would stop covering a script the moment one is added - the defect skillcheck
            # already recorded as "an include list fails quiet".
            lab_words = {w.lower().replace("-", "")
                         for w in re.findall(r"[A-Za-z][A-Za-z-]+", label)}
            stem = os.path.splitext(base)[0].lower().replace("-", "").replace("_", "")
            hit = sorted(lab_words & _project_script_stems())
            if hit and stem not in lab_words:
                mismatched.append((m.group(1), hit[0][:24] + ".py", base))
    if missing:
        fail("LINK-RESOLVES",
             "%d computer:// target(s) DO NOT EXIST: %s. A link that 404s is worse than "
             "no link - REVIEW-LINK passes it because a URL is present."
             % (len(missing), ", ".join("row %s -> %s" % t for t in missing[:4])))
    if mismatched:
        warn("LINK-RESOLVES",
             "%d row(s) link to a file the row never names: %s. This is the P2-22 shape - "
             "the label said one file, the href went to another, and two gates passed it "
             "three times."
             % (len(mismatched),
                ", ".join("row %s ('%s' -> %s)" % t for t in mismatched[:4])))



# ---------- LINK-ESCAPES, added 2026-09-17 for F-174 ----------
# LINK-RESOLVES asks whether a computer:// target EXISTS, and it answers from this laptop, where a
# symlink into Google Drive resolves perfectly. Rob's link is resolved against the folders
# connected to his session, and a symlink whose target lies outside them does not open. On
# 2026-09-17 two paste links into ~/Claude/instructions-backup - both symlinks into Drive, because
# backupsweep moves every backup there - passed LINK-RESOLVES, REVIEW-LINK and the registry anchor
# check, and both were dead for Rob. That was F-166 recurring one level deeper, an hour after it
# was fixed. THE TEST: resolve the target and fail when it leaves the top-level tree the link
# names (/Users/<name>/<top>). It scans the WHOLE reply, not only table rows, because both dead
# links sat in prose as well as in the table.
def check_link_escapes(text):
    """LINK-ESCAPES: a computer:// link whose real target leaves the tree the link names."""
    bad = []
    for lm in COMPUTER_LINK.finditer(text):
        path = lm.group(2)
        parts = path.split("/")
        if len(parts) < 4 or not os.path.exists(path):
            continue
        root = "/".join(parts[:4])
        real = os.path.realpath(path)
        if not (real == root or real.startswith(root + "/")):
            bad.append((os.path.basename(path), real[:60]))
    if bad:
        fail("LINK-ESCAPES",
             "%d computer:// link(s) point at a symlink whose target leaves the linked tree: %s. "
             "It resolves on this laptop and is dead in Rob's session, which can only open files "
             "inside its connected folders - F-166 and F-174. Link the real file, or send it as an "
             "attachment." % (len(bad), "; ".join("%s -> %s" % t for t in bad[:3])))

# ---------- LINK-REUSE, added 2026-08-26 ----------
# REVIEW-LINK CHECKS THAT A URL IS PRESENT. IT DOES NOT CHECK THAT IT GOES ANYWHERE USEFUL,
# and Claude satisfied it four times with the SAME link to AUDIT-PROTOCOL.md while labelling
# it P2-21, P2-27, P2-28 and P9-03. Rob: "Is the link on #1 accurate?" It was not - P2-28
# lives in the plan Doc, and the protocol file was last modified 2026-08-18 and carries none
# of the figures the row cited. A REQUIRED FIELD WITH NO CORRECTNESS TEST BECOMES A
# PLACEHOLDER, which is how "every row carries a URL" passed while the URLs were wrong.
#
# THIS CANNOT VALIDATE A DESTINATION - nothing here can fetch it. What it CAN catch is the
# mechanical signature of copy-paste: one URL serving several distinct rows. WARN, not FAIL,
# because a table whose rows genuinely all live in one document is legitimate.
def check_link_reuse(text):
    """LINK-REUSE: one URL doing duty for three or more different rows."""
    seen = {}
    for m in TABLE_ROW.finditer(text):
        row = m.group(0)
        for u in re.findall(r"https?://[^\s)\]]+", row):
            seen.setdefault(u, []).append(m.group(1))
    for u, rows in seen.items():
        if len(set(rows)) >= 3:
            warn("LINK-REUSE",
                 "one url serves %d different rows (%s): %s. REVIEW-LINK only checks a url is "
                 "PRESENT, so a placeholder passes it. Confirm each row points where its own "
                 "label says." % (len(set(rows)), ", ".join(sorted(set(rows))[:5]), u[:60]))


_ACR_DIR = os.path.dirname(os.path.abspath(__file__))
_ACR_MAP = None


def check_acronyms(text):
    """ACRONYM-FIRST-USE: a mapped acronym used before its expansion in this surface.

    *** IT JOINED CORPUS_CHECKS ON THE MEASUREMENT, NOT ON THE ARGUMENT. *** The zero
    false positives that justified this gate were measured on INSTRUCTION PROSE and memory
    files, and that number did not predict replies - a different distribution, which quote
    rules back verbatim, paste tool output and name files. Run over 821 assistant turns of
    this project's history on 2026-09-10 it produced 78 flags, 27 of them not violations:
    quoted strings, code spans, fenced pastes and hyphenated identifiers. Adding the
    literal-span rule to acronym_check.py and the project-name family to the AI skip_regex
    took the reply corpus to 49 flags with ZERO false positives, and 45 of 821 replies
    flagging. THE KNOWN COST IS TWO MISSED TRUE POSITIVES: turn0084 and turn0091 wrote a
    bare API inside a fenced CHECKED block, and the fence rule silences them. A coverage
    threshold was tested at 90, 70 and 50 percent and cannot separate those two from the
    pasted specs in turn0745/0746, so the miss is accepted and recorded rather than tuned
    away with a number that does not work.

    FAIL RATHER THAN WARN, because a warning nobody clears is a rule enforced by judgement,
    which is the thing this project exists to replace. THE FALSIFIER: if a future map row
    starts hard-blocking replies on a name collision, this belongs back at warn() - and
    the map, not this call site, is where the fix goes.
    """
    global _ACR_MAP
    if _ACR_DIR not in sys.path:
        sys.path.insert(0, _ACR_DIR)
    import acronym_check as _ac
    if _ACR_MAP is None:
        _ACR_MAP = _ac.load_map(_ac.DEFAULT_MAP, "*")
    # *** DEMOTED FROM fail() TO warn() 2026-09-10, BECAUSE THE CONDITION THAT AUTHORISED THE
    # HARD FAIL STOPPED HOLDING AND NOBODY ACTED ON IT FOR THREE ROUNDS. *** Rob's condition for
    # joining CORPUS_CHECKS was "at or near zero false positives on replies". That was measured at
    # 0 over 821 replies in ONE project. Re-measured over 3,610 turns across five populations it is
    # 0.8 to 4.9 percent - a RANGE, because two independent readers of the same 266 surviving rows
    # returned 5 and 11 not-a-violation and agreed on only 2. A range that does not include zero is
    # not "at or near zero", so the authorisation lapsed at the moment of that measurement.
    # *** THE SENTENCE THIS REPLACES WAS FALSE WITHIN A DAY, AND IT IS QUOTED SO layerdiff.py CAN
    # LIFT IT: "THE RESTORATION IS ONE WORD: change warn back to fail once the TITLE-NAMING
    # BOUNDARY is ruled and the three unmeasured populations are read." BOTH OF ITS CONDITIONS
    # WERE THEN MET AND fail() IS STILL NOT AUTHORISED. *** Rob ruled the boundary on 2026-09-10
    # and the claude.ai chat surface was measured the same day: 691 assistant turns, 30
    # conversations, 177 of them holding a mapped token, 188 flags over 144 turns. Two readers of
    # those 188 rows returned 45 and 28 not-a-violation and agreed on 16, so the false-positive
    # rate is 8.5 to 23.9 percent - two to five times the Cowork range, on the surface Rob
    # actually reads. THE MAP SKIP SET he approved takes 188 to 154 with zero wrong removals, and
    # the residual is STILL 5 to 17 over 154, which is 3.2 to 11.0 percent.
    # SO THE RESTORATION IS NOT ONE WORD AND WAS NEVER GATED ON THE RULING. The condition is
    # ARITHMETIC: a measured false-positive range whose UPPER bound is at or near zero, on the
    # population the gate will run against. Four residual classes stand in the way and none is
    # expressible as a skip literal - coined item labels, an all-caps document section heading, a
    # credential abbreviation colliding with a mapped token, and an on-screen control label.
    # DO NOT RESTORE fail() ON THE STRENGTH OF A RULING. Re-measure first, and quote the number.
    # WHY WARN AND NOT REMOVAL: the detector still runs, still counts in the rate, and still shows
    # up in a pre-send read. What it stops doing is BLOCKING a reply on a boundary that has not been
    # ruled. A gate that blocks wrongly gets switched off, and then the rule is enforced by nothing.
    for token, _pos, line in _ac.check_text(text, _ACR_MAP):
        warn("ACRONYM-FIRST-USE",
             "line %d: %r used before %r. Rob's rule spells out every acronym at first use "
             "IN EACH SURFACE, and a reply is its own surface." % (line, token,
                                                                  _ACR_MAP[token]["expansion"]))


# ---------- STANDING ROWS ----------
# *** SUMMARY-SPEC.md HAS NAMED FOUR STANDING ROWS SINCE 2026-08-25 AND NOT ONE OF THEM
# APPEARED IN ANY TABLE ON 2026-09-12. *** Found by reading Rob's verbatim requirements
# rather than the spec written from them - his Block 2 lists them as rows the table always
# carries, ranked against everything else. The spec says the same, under "Standing rows -
# always present, always ranked against everything else", and it says they are "not an
# appendix".
# CLAUDE'S FIRST STATEMENT OF THIS WAS ALSO WRONG AND THE CORRECTION IS THE REASON THE GATE
# USES THE SPEC'S OWN LABELS: the reply that reported the gap said THREE rows and paraphrased
# them from Rob's prose. There are FOUR, and the spec's definitions are sharper than the
# paraphrase - VOICE COMPLIANCE, which asks for a count and a quoted instance, was missed
# entirely. A rule restated from memory drifts; a rule matched against its own file does not.
# 0.2.16 (Rob 2026-10-17 12:18 PM, row 7 "adopt"): the four rows above are replaced by the objective-process rows
# (INTAKE F-644; root causes RC1 and RC4). A row that is DONE leaves the table and is named on one line
# "STANDING ROWS DONE: <labels>"; the check is keyed on the next-steps header, so a small table elsewhere owes nothing.
STANDING_ROWS = ("INSTRUCTION FIELD FIRST", "CONFORMANCE CHECK", "HOSTILE REVIEW", "SAMPLE GATE", "APPROVAL")
_NS_HEAD = re.compile(r"^\|\s*#\s*\|\s*Issue\s*/\s*Risk\s*\|", re.I | re.M)


def check_standing_rows(text):
    """A ranked table that omits a standing row fails.

    Keyed on the TABLE EXISTING rather than on any wording, for the same reason REVIEW-LINK
    is: a check that keys on phrasing can be stepped around by rephrasing, and this project
    has watched that happen. No table, no obligation - a single-fact answer owes nothing.
    """
    if not _NS_HEAD.search(text):
        return
    # 0.3.17 (Rob 2026-10-26 "When will you fix this?"; root cause: this check ran in EVERY project-bound session, so a
    # table in any other project could never be stamped). The five rows are the objective-process rows of the Kaprelian
    # doctors project (INTAKE F-644, root causes RC1 and RC4), so the obligation exists only when gate.py / precheck.py
    # report that project via REPLYCHECK_KAP_PROJECT=1. Unset or anything else: no obligation. The table-shape checks
    # (CON-FORMAT, OBJECTIVE-SECTIONS, SELFCHECK ...) still run everywhere.
    import os as _os_kap
    if _os_kap.environ.get("REPLYCHECK_KAP_PROJECT") != "1":
        return
    rows_up = "\n".join(l for l in text.splitlines() if l.lstrip().startswith("|")).upper()
    done_up = "\n".join(l for l in text.splitlines() if l.lstrip().upper().startswith("STANDING ROWS DONE")).upper()
    missing = [r for r in STANDING_ROWS if r not in rows_up and r not in done_up]
    if missing:
        fail("STANDING-ROWS",
             "%d standing row(s) missing from the next-steps table: %s. Rob's 2026-10-17 12:18 PM ruling "
             "(row 7, adopt): every next-steps table carries the five objective-process rows until each is "
             "DONE, and a row that is DONE is named on one line 'STANDING ROWS DONE: <label>' instead."
             % (len(missing), ", ".join(missing)))


CORPUS_CHECKS = [check_standing_rows, check_offload, check_tool_deadend, check_reach_unsourced,
                 check_opener, check_filler,
                 check_voice, check_rank_contradiction, check_rating_closable,
                 check_agreement, check_review_link, check_commit_then_stop, check_link_reuse, check_link_resolves, check_link_escapes, check_own_column, check_call_on_rob, check_exercise_on_rob, check_artifact_item_on_rob, check_denominator, check_acronyms]
# *** check_rating JOINED THIS SET 2026-08-19 AND THAT IS THE WHOLE POINT OF THE EDIT. ***
# RATING-CLOSABLE was written on 2026-08-19 as the fix for "Rob had to ask whether I was
# thorough", it shipped with 26 passing controls, and it was NOT IN THIS LIST - so the only
# number that can regress could not see it. The rate HELD at 83% while the identical failure
# was committed twice more the same day. A detector outside CORPUS_CHECKS is a detector
# enforced by Claude remembering to care, which is the exact thing this project exists to
# replace. ratefloor.py fingerprints this list, so the next reading is a NEW SERIES, not a
# regression, and the 83% baseline stays comparable only to its own metric.


def _logic_fingerprint(checks=None):
    """C-032, ROB APPROVED 2026-10-06 21:33 PDT (batch). A hash of what the corpus checks DO, not
    only of their names. metric_id() was the sorted check names alone, so a detector whose logic
    changed (INLINE_EVIDENCE_RE, 2026-09-30) kept the same id and its rate drop read as a
    regression; three drops in .rate-history.tsv coincide with such changes. Hashed: each check's
    source; every same-module function it calls, transitively; every module-level regex (pattern
    and flags) and plain constant it names; and, for check_acronyms, acronym_check.py and the
    acronyms.tsv map it loads. 12 hex characters."""
    import hashlib, inspect, types
    g = globals()
    seen, parts = set(), []

    def names_of(code):
        out = set(code.co_names)
        for c in code.co_consts:
            if isinstance(c, types.CodeType):
                out |= names_of(c)
        return out

    def visit(fn):
        if fn.__name__ in seen:
            return
        seen.add(fn.__name__)
        try:
            parts.append("F:%s:%s" % (fn.__name__, inspect.getsource(fn)))
        except (OSError, TypeError):
            parts.append("F:%s:<nosource>" % fn.__name__)
        for n in sorted(names_of(fn.__code__)):
            # Runtime state, not logic: FAILS/WARNS/INFO fill as checks run and _ACR_MAP loads
            # lazily (its source file is hashed below instead). Measured: including them made two
            # fingerprints taken either side of one check call differ.
            if n in seen or n not in g or n in ("FAILS", "WARNS", "INFO", "_ACR_MAP"):
                continue
            v = g[n]
            if isinstance(v, types.FunctionType) and v.__module__ == __name__:
                visit(v)
            elif isinstance(v, re.Pattern):
                seen.add(n)
                parts.append("R:%s:%r:%d" % (n, v.pattern, v.flags))
            elif isinstance(v, (str, int, float, bool, tuple, frozenset, list, dict, set)):
                seen.add(n)
                try:
                    parts.append("C:%s:%s" % (n, repr(sorted(v)) if isinstance(v, (set, frozenset)) else repr(v)))
                except TypeError:
                    parts.append("C:%s:%r" % (n, v))

    checks = CORPUS_CHECKS if checks is None else checks
    for fn in sorted(checks, key=lambda f: f.__name__):
        visit(fn)
        if fn.__name__ == "check_acronyms":
            here = os.path.dirname(os.path.abspath(__file__))
            for extra in ("acronym_check.py", "acronyms.tsv"):
                try:
                    with open(os.path.join(here, extra), "rb") as fh:
                        parts.append("X:%s:%s" % (extra, hashlib.sha256(fh.read()).hexdigest()))
                except OSError:
                    parts.append("X:%s:<missing>" % extra)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def metric_id():
    """The identity of the RATE, not of this file. Two runs are comparable only if this
    string matches; ratefloor.py refuses to call a move a regression across a change.
    C-032: the check names plus '#' and _logic_fingerprint(), so a logic change starts a NEW
    SERIES instead of reading as a regression."""
    return "+".join(sorted(f.__name__.replace("check_", "") for f in CORPUS_CHECKS)) + "#" + _logic_fingerprint()


def corpus_rate(project, maxchars=500000):
    import subprocess
    scan = "/Users/robk/Claude/Session-Summaries/bin/session_scan.py"
    # R220, Rob 2026-10-07 07:27 PDT: --with-historical adds session_scan's fixed, named snapshot
    # (HISTORICAL_ROOTS: the 25 Improving my Claude (Overall) local sessions removed from the app
    # on 2026-10-06 ~20:30 PDT) to the live folder. A missing snapshot makes session_scan exit 4
    # with no turns, so the rate below reads "no turns" and ratefloor reports NOT MEASURED.
    # R221, Rob 2026-10-07 08:04 PDT: --with-cloud adds this project's cloud sessions from the
    # cloud corpus (session_scan.cloud_sessions). Missing, empty or stale exits 4 with no turns, so
    # the rate reads "no turns" and ratefloor reports NOT MEASURED - never a smaller corpus.
    out = subprocess.run(["python3", scan, "turns", "--project", project, "--all", "--with-historical",
                          "--with-cloud", "--max-chars", str(maxchars)], capture_output=True, text=True).stdout
    turns, cur, in_a = [], [], False
    for line in out.splitlines():
        m = re.match(r"^--- \S+ (ASSISTANT|USER)", line)
        if m:
            if in_a and cur:
                turns.append("\n".join(cur))
            in_a = (m.group(1) == "ASSISTANT")
            cur = []
            continue
        if in_a:
            cur.append(line)
    if in_a and cur:
        turns.append("\n".join(cur))

    # MATCH THE MARKER, NOT THE TOPIC WORD. Counting the bare substring "...[truncated"
    # matched THIS PROJECT'S OWN PROSE about truncation and reported 1 where the real count
    # was 0. That is the fourth time on 2026-08-16 a detector matched its own subject:
    # quoted history, a "truncated" grep, an OR clause hitting conversation content, and
    # this. The emitted marker always carries a digit and the word chars; the prose does not.
    trunc = len(re.findall(r"\.\.\.\[truncated \d+ chars\]", out))
    tally, clean = {}, 0
    for t in turns:
        del FAILS[:], WARNS[:], INFO[:]
        # *** ADDING A CHECK HERE CHANGES THE METRIC, NOT JUST THE OUTPUT. *** RANK
        # CONTRADICTION joined this set on 2026-08-18 and the rate moved for that reason
        # alone. A rate whose definition changes silently is the denominator failure this
        # project has on record three times, so ratefloor.py fingerprints THIS LIST and
        # starts a new baseline series when it changes rather than reporting a regression
        # that never happened. If you add a check here, that is the mechanism that covers it.
        for fn in CORPUS_CHECKS:
            fn(t)
        hits = FAILS + WARNS
        if not hits:
            clean += 1
        for c, _ in hits:
            tally[c] = tally.get(c, 0) + 1
    del FAILS[:], WARNS[:], INFO[:]

    print("CORPUS RATE - %s" % project)
    print("  metric          : %s" % metric_id())
    print("  assistant turns : %d" % len(turns))
    print("  clean           : %d" % clean)
    print("  COMPLIANCE      : %.0f%%" % (100 * clean / len(turns)) if turns else "  no turns")
    print("  truncated turns : %d%s" % (trunc, "  <-- RAISE --max-chars, the rate is fiction" if trunc else ""))
    for k, v in sorted(tally.items(), key=lambda x: -x[1]):
        print("    %-16s %d" % (k, v))
    return 0


def _rc_text(rows, sc="thorough: yes - read all; confidence: 10/10 in the recommendations and next steps, no residual uncertainty."):
    """Selftest helper (0.2.25): a reply with a SELF-CHECK line and a next-steps table of (issue, owner) rows."""
    h = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
    body = "".join("| %d | %s | B | %s | C. | D. | Con:&nbsp;x<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n" % (i + 1, a, o)
                   for i, (a, o) in enumerate(rows))
    return "SELF-CHECK: " + sc + "\n\n" + h + body


def _pv_text(rows):
    """Selftest helper (0.2.28): (issue, action, owner) rows under the seven-column header."""
    h = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
    body = "".join("| %d | %s | %s | %s | C. | D. | Con:&nbsp;x<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n" % (i + 1, a, b, o)
                   for i, (a, b, o) in enumerate(rows))
    return "SELF-CHECK: thorough: yes - read all; confidence: 10/10 in the recommendations and next steps, no residual uncertainty.\n\n" + h + body


def _selftest():
    """
    *** THIS DID NOT EXIST, AND `--selftest` CRASHED FOR 24 HOURS BECAUSE OF IT. ***
    main() treated any first argument that was not `--rate` as a FILENAME, so `--selftest`
    became open('--selftest') and raised FileNotFoundError. Every "controls pass" claim
    about this linter was therefore never made by this linter. THE GATE BUILT TO CATCH
    UNVERIFIED CLAIMS HAD NO WAY TO VERIFY ITSELF.
    """
    # *** 13 CHECKS, 4 CONTROLS. NINE COULD NOT FIRE AND NOBODY WOULD KNOW. ***
    # Every code below now has a POSITIVE control that must fire and, where the check can
    # produce a false positive, a NEGATIVE control that must stay silent. An unproven check
    # in the tool that grades my own replies is the worst possible place for a silent pass:
    # it reports 0 FAIL, which reads exactly like a clean reply.
    # R120e: replygate exports REPLYCHECK_DRAFT, and the self-test inherited it - 4 PRE-SEND
    # fixtures then ran on the stamp path and the stamp read 281/285. Fixtures describe the text
    # alone, so the variable is cleared for the whole self-test.
    import os as _os_st
    _os_st.environ.pop("REPLYCHECK_DRAFT", None)
    def run(text, fns):
        del FAILS[:], WARNS[:], INFO[:]
        for fn in fns:
            if fn is check_rating:
                fn(text, 0, 0)
            else:
                fn(text)
        return {c for c, _ in FAILS} | {c for c, _ in WARNS}

    # *** ALL WAS A HAND-TYPED LIST AND check_gloss WAS DISPATCHED WITHOUT BEING IN IT. ***
    # Measured 2026-08-31: the new check ran in production and its four controls all reported
    # PASS-by-absence, because the selftest never called it. A hand-maintained list of the
    # things to test is the same defect as a hand-maintained list of the things to audit -
    # it drifts, and nothing notices. ALL is now DERIVED from the module's own single-argument
    # check_ functions, so a check cannot be added without being tested.
    #
    # The multi-argument checks are named explicitly because they cannot be called generically;
    # naming them here is a decision, and the control below asserts the two sets partition the
    # module rather than letting one quietly swallow the other.
    _MULTI = {"check_uncited_claims", "check_rating"}
    _g = globals()
    _derived = [v for k, v in sorted(_g.items())
                if k.startswith("check_") and callable(v) and k not in _MULTI]
    ALL = _derived + [check_rating]

    # *** THE INVERSE DEFECT, MEASURED 2026-09-01: TESTED BUT NEVER DISPATCHED. ***
    # The note above made the TEST list derive itself. main()'s dispatch list stayed
    # HAND-TYPED, so check_table_shape passed all three of its controls while never running on
    # a real reply - 0 FAIL on the exact table Rob screenshotted. That is worse than an
    # untested check: the selftest reports green AND the live run reports clean, and the two
    # numbers are about different populations. This compares the two lists directly.
    # A CHECK MAY BE DISPATCHED INDIRECTLY AND THAT IS LEGITIMATE. check_rating_closable is
    # called from inside check_rating, not from main, and the first version of this control
    # scanned main() alone and reported it undispatched - a false positive on its first run.
    # Scan the whole module MINUS the selftest, so a call site that only exists in a fixture
    # does not count as dispatch.
    #
    # EXEMPTIONS CARRY THEIR REASON, path<TAB>reason style, and an entry with no reason is a
    # bug rather than a pass.
    # EMPTY ON PURPOSE, AND THE ONE ENTRY IT HELD IS THE REASON THIS DICT EXISTS.
    # check_rank_sections / RANK-OWNER was tested and never dispatched. Rob approved deleting
    # it on 2026-09-01 and it is gone, so an exemption is no longer the right tool - the right
    # tool was deletion. THE REASON I GAVE HIM FOR IT WAS BACKWARDS and is corrected here:
    # check_rank_sections WAS RANK-OWNER. It was superseded on 2026-08-25 by check_split_by_owner
    # / SPLIT-BY-OWNER, when Rob ruled ONE stack-ranked list with owner as a COLUMN. RANK-OWNER
    # sorted by owner, which now fights the ranking rules it was meant to protect. My exemption
    # text said it was superseded BY RANK-OWNER, naming the retired check as its own replacement.
    # The deletion was right and the sentence justifying it was not.
    _WIRING_EXEMPT = {}
    import inspect as _inspect
    _src = _inspect.getsource(_inspect.getmodule(main))
    _self_src = _inspect.getsource(_selftest)
    _live_src = _src.replace(_self_src, "")
    _undispatched = sorted(fn.__name__ for fn in _derived
                           if (fn.__name__ + "(") not in _live_src.replace(
                               "def " + fn.__name__ + "(", "")
                           and fn.__name__ not in _WIRING_EXEMPT)
    # *** THIS BRANCH PRINTED A FAIL AND COUNTED NOTHING, MEASURED 2026-09-10. ***
    # check_acronyms was added to CORPUS_CHECKS and never to main()'s dispatch. THIS CONTROL
    # CAUGHT IT ON THE FIRST RUN and printed 'FAIL WIRING: ... check_acronyms' - while the
    # summary line below said PASSED 135 FAILED 0, because the branch never touched the
    # counter. Three separate readings of that summary reported a clean selftest over a
    # printed FAIL. A control whose verdict does not reach the number the reader looks at is
    # not a control; it is a comment. The counter is now wired to it.
    _wiring_failed = 1 if _undispatched else 0
    if _undispatched:
        print("  FAIL  WIRING: tested but never dispatched by main(): %s"
              % ", ".join(_undispatched))
    else:
        print("  ok    every tested check is dispatched by main()")

    _missing = [k for k, v in sorted(_g.items())
                if k.startswith("check_") and callable(v) and v not in ALL and k not in _MULTI]
    assert not _missing, "checks defined but not tested: %s" % _missing

    OK5 = ("THOROUGH: criterion validated vs the activity - single-source, unverified - "
           "disconfirming pass run - nothing in my own column changes the above - "
           "rivals listed with killers - enumeration published, every place searched or not searched")
    BAD5 = ("THOROUGH: criterion validated vs the activity - numbers single-source nowhere - "
            "disconfirming pass run - nothing in my own column changes the above - "
            "rivals listed with killers - enumeration published and each entry marked searched or not searched")
    cases = [
        ("ROB-ROW SELF-ANSWER: a Rob row stating Claude's own preferred answer is flagged even "
         "though it uses decision vocabulary",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Rule which one governs. I would keep tracking the hash. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "ROB-ROW", True),
        ("ROB-ROW SELF-ANSWER: a genuine approval row with no self-answer stays silent",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Approve the line, since it changes what the audit covers. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "ROB-ROW", False),
        # ROB-ROW, 2026-09-20, both directions. A warning rather than a failure on purpose:
        # failing on a wording test teaches rewording.
        ("ROB-ROW warns on a Rob row that asks for no decision",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Read the file and tell me what it says. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "ROB-ROW", True),
        ("ROB-ROW stays silent on a genuine approval row",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Approve the line, since it changes what the audit covers. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "ROB-ROW", False),
        ("ROB-ROW stays silent when the same wording is owned by Claude",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Claude | Read the file and tell me what it says. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "ROB-ROW", False),
        ("ROB-ROW stays silent on a reply with no table",
         "Just prose here.\n", "ROB-ROW", False),
        # THE CONTROL THE 2026-09-20 BUG NEEDED. The one above it says "the same wording owned by
        # Claude" and proves nothing, because its text never contains the word Rob - which is the
        # only thing the broken filter looked for. This one puts Rob INSIDE a Claude-owned row.
        ("ROB-ROW stays silent on a Claude row whose recommendation says the word Rob",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Claude | Before any Rob row ships, run the file read that would settle it. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "ROB-ROW", False),
        # THE THIRD EXIT'S THREE CONTROLS WERE DELETED WITH IT ON 2026-09-20 UNDER R075. They
        # tested that answering a question plus naming the next item escaped the all-Claude
        # fail, and R075 removed that fail. Left in place they would have kept passing - an
        # exit from nothing is trivially satisfied - which is how a suite grows controls that
        # cannot discriminate. The R075 block near the bottom of this self-test replaces them.
        # GATE-RATIO, 2026-09-20, both directions plus the size floor.
        ("GATE-RATIO fires when every recommendation is a promise",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | THING 1 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 2 | THING 2 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 3 | THING 3 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 4 | THING 4 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 5 | THING 5 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n", "GATE-RATIO", True),
        ("GATE-RATIO stays silent when every recommendation names a real gate",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | THING 1 - NO-ARTIFACT | Open | Claude | Do it. Test: plancheck exits 0 and prints 143 items. Fails if: it exits 1. | Pro: a. Con: b. |\n| 2 | THING 2 - NO-ARTIFACT | Open | Claude | Do it. Test: plancheck exits 0 and prints 143 items. Fails if: it exits 1. | Pro: a. Con: b. |\n| 3 | THING 3 - NO-ARTIFACT | Open | Claude | Do it. Test: plancheck exits 0 and prints 143 items. Fails if: it exits 1. | Pro: a. Con: b. |\n| 4 | THING 4 - NO-ARTIFACT | Open | Claude | Do it. Test: plancheck exits 0 and prints 143 items. Fails if: it exits 1. | Pro: a. Con: b. |\n| 5 | THING 5 - NO-ARTIFACT | Open | Claude | Do it. Test: plancheck exits 0 and prints 143 items. Fails if: it exits 1. | Pro: a. Con: b. |\n", "GATE-RATIO", False),
        ("GATE-RATIO fires at 1 of 5, which is below the 40 percent floor",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | THING 1 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 2 | THING 2 - NO-ARTIFACT | Open | Claude | Do it. Test: plancheck exits 0 and prints 143 items. Fails if: it exits 1. | Pro: a. Con: b. |\n| 3 | THING 3 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 4 | THING 4 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 5 | THING 5 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n", "GATE-RATIO", True),
        ("GATE-RATIO does not score a table too small to have a ratio",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | THING 1 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 2 | THING 2 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n| 3 | THING 3 - NO-ARTIFACT | Open | Claude | Do it. Test: over the next 5 replies the log gains 0 rows. Fails if: it gains 1. | Pro: a. Con: b. |\n", "GATE-RATIO", False),
        ("GATE-RATIO stays silent on a reply with no recommendation table",
         "Just prose, no table at all.\n", "GATE-RATIO", False),
        # CLOSE-GATES, R067 2026-09-20, both directions.
        ("CLOSE-GATES fires on a close-ask with no CLOSECHECK line",
         "I recommend we close P2-14 now.\n", "CLOSE-GATES", True),
        ("CLOSE-GATES fires on a BLOCK verdict with no ruling id",
         "close P2-14\nCLOSECHECK P2-14: BLOCK scopecheck exit 1\n", "CLOSE-GATES", True),
        ("CLOSE-GATES stays silent on a PASS verdict",
         "close P2-14\nCLOSECHECK P2-14: PASS every named gate exit 0\n", "CLOSE-GATES", False),
        ("CLOSE-GATES stays silent on a BLOCK verdict citing the ruling that declares the gap",
         "close P2-14\nCLOSECHECK P2-14: BLOCK scopecheck exit 1, the declared c11 gap under R060\n",
         "CLOSE-GATES", False),
        # R128: the CLOSE-GATES ruling-id test reads three digits too.
        ("CLOSE-GATES stays silent on a BLOCK verdict citing a ruling past R099 (R128)",
         "close P2-14\nCLOSECHECK P2-14: BLOCK scopecheck exit 1, the declared gap under R127\n",
         "CLOSE-GATES", False),
        ("CLOSE-GATES stays silent on a reply that asks to close nothing",
         "Nothing is being closed here.\n", "CLOSE-GATES", False),
        # SENT-CHECKED, F171 2026-09-21, both directions.
        ("SENT-CHECKED fires on a full reply with no SENTCHECK line",
         "THOROUGH: sourcing - x.\n\nBody.\n", "SENT-CHECKED", True),
        ("SENT-CHECKED fires on a MISMATCH",
         "THOROUGH: sourcing - x.\nSENTCHECK: 3 stamped, 2 match, 1 MISMATCH\n", "SENT-CHECKED", True),
        ("SENT-CHECKED fires on zero stamped with no reason",
         "THOROUGH: sourcing - x.\nSENTCHECK: 0 stamped, 0 match, 0 MISMATCH\n", "SENT-CHECKED", True),
        ("SENT-CHECKED stays silent on a clean run",
         "THOROUGH: sourcing - x.\nSENTCHECK: 3 stamped, 3 match, 0 MISMATCH\n", "SENT-CHECKED", False),
        # CONTROLS FOR THE THIRD STATE, ADDED 2026-09-27. The load-bearing one is the LAST:
        # UNVERIFIABLE must never swallow a real mismatch, or it is just a way to pass.
        ("SENT-CHECKED stays silent when the line declares UNVERIFIABLE with a reason",
         "THOROUGH: sourcing - x.\nSENTCHECK: 0 stamped, 0 match, 0 MISMATCH - UNVERIFIABLE: Cowork writes no transcript under ~/.claude/projects\n",
         "SENT-CHECKED", False),
        ("SENT-UNVERIFIABLE FIRES as a warning on that same line, so it is never silent",
         "THOROUGH: sourcing - x.\nSENTCHECK: 0 stamped, 0 match, 0 MISMATCH - UNVERIFIABLE: Cowork writes no transcript under ~/.claude/projects\n",
         "SENT-UNVERIFIABLE", True),
        ("SENT-CHECKED still FIRES when UNVERIFIABLE is claimed with no reason after it",
         "THOROUGH: sourcing - x.\nSENTCHECK: 0 stamped, 0 match, 0 MISMATCH - UNVERIFIABLE\n",
         "SENT-CHECKED", True),
        ("*** UNVERIFIABLE CANNOT SWALLOW A REAL MISMATCH *** - stamped 3, 2 match, 1 MISMATCH still FAILS",
         "THOROUGH: sourcing - x.\nSENTCHECK: 3 stamped, 2 match, 1 MISMATCH - UNVERIFIABLE: whatever reason is given here\n",
         "SENT-CHECKED", True),
        ("SENT-CHECKED stays silent on zero stamped after a container reset",
         "THOROUGH: sourcing - x.\nSENTCHECK: 0 stamped, 0 match, 0 MISMATCH - container reset\n",
         "SENT-CHECKED", False),
        ("CONTROL the false sentence QUOTED for correction does NOT fire",
         'I published "no file defines any identifier above R099" and three did.\n',
         "SCOPE-VS-CLAIM", False),
        # SCOPE-VS-CLAIM, 2026-09-28: the exact false sentence that passed 226 controls.
        ("SCOPE-VS-CLAIM fires on the real false sentence",
         "no file defines any identifier above R099.\n", "SCOPE-VS-CLAIM", True),
        ("CONTROL the same claim narrowed to the root actually searched does NOT fire",
         "no file under bin/ defines any identifier above R099.\n", "SCOPE-VS-CLAIM", False),
        # COUNT-THEN-UNIVERSE, 2026-09-30: the real 22:08 shape, and the corrected shape beside it.
        ("COUNT-THEN-UNIVERSE fires on the real 22:08 pair",
         "I searched 96 files under the home folder.\n\nClaude's replies are captured nowhere.\n",
         "COUNT-THEN-UNIVERSE", True),
        ("CONTROL the same pair with the set named beside the claim does NOT fire",
         "I searched 96 files.\n\nClaude's replies appear nowhere, of the 96 I searched.\n",
         "COUNT-THEN-UNIVERSE", False),
        ("CONTROL a count with no universe word does NOT fire",
         "I searched 96 files and four of them hold the turn.\n",
         "COUNT-THEN-UNIVERSE", False),
        ("CONTROL a universe word with no count does NOT fire",
         "The replies are nowhere in the export pipeline.\n",
         "COUNT-THEN-UNIVERSE", False),
        ("CONTROL an ordinary sentence does NOT fire",
         "The ledger holds 104 rows and its ids run to R103.\n", "SCOPE-VS-CLAIM", False),
        # SKILL-CLAIM-UNSAVED, 2026-09-28: the fabricated-action row of that session.
        # R151 (Rob 2026-10-01 17:58 PDT): the fixture named instrument-before-number, which then synced to
        # this machine and made the control fail for a reason that had nothing to do with the check. A
        # positive control for "no directory" must name a skill that cannot exist.
        ("SKILL-CLAIM fires on a skill asserted live that has no directory",
         "The skill is saved and live - zz-no-such-skill-r151 now appears in the skill list.\n",
         "SKILL-CLAIM-UNSAVED", True),
        ("CONTROL a skill that DOES exist on disk does not fire",
         "The skill is saved and live - agent-platform-deploy appears in the skill list.\n",
         "SKILL-CLAIM-UNSAVED", False),
        ("CONTROL a sentence saying it was never saved does not fire",
         "instrument-before-number was never proposed, so it does not appear in the skill list.\n",
         "SKILL-CLAIM-UNSAVED", False),
        # ABSENCE-CLAIM, 2026-09-21 (Rob, "Approve 1-3"): the two false sentences of that day.
        ("ABSENCE-CLAIM fires on 'out of reach' with no searched control",
         "So the ledger's own edit history is out of reach through it.\n", "ABSENCE-CLAIM", True),
        ("ABSENCE-CLAIM fires on 'another session' with no searched control",
         "Another session applied your approval at 11:23.\n", "ABSENCE-CLAIM", True),
        ("ABSENCE-CLAIM stays silent when a CHECKED line names the search and a control",
         "Another session applied it.\nCHECKED: sessions -> searched the session list; control: this session is listed.\n",
         "ABSENCE-CLAIM", False),
        ("ABSENCE-CLAIM stays silent on the corrected sentence",
         "The transcripts dated 116 of 174 rows, so the history was reachable.\n", "ABSENCE-CLAIM", False),
        ("ABSENCE-CLAIM stays silent when the phrase is only quoted",
         'I wrote "another session" earlier and it was wrong.\n', "ABSENCE-CLAIM", False),
        ("ABSENCE-CLAIM fires on W38's own wording (a negative from a partial read)",
         "The scope delta was unrecorded and the proposal was the only record.\n", "ABSENCE-CLAIM", True),
        ("ABSENCE-CLAIM fires on W45's own wording (generalised from one task)",
         "A cloud task can read Drive and write project docs, and nothing else.\n", "ABSENCE-CLAIM", True),
        ("ABSENCE-CLAIM stays silent on a sentence that retracts the claim",
         "The conclusion it implied, that the ledger cannot be dated, was wrong.\n", "ABSENCE-CLAIM", False),
        ("ABSENCE-CLAIM stays silent on a Fails-if falsifier",
         "Fails if: any row is marked fixed by a gate that does not exist.\n", "ABSENCE-CLAIM", False),
        ("MUTATION: the same absence stated as fact still fires",
         "The row was marked fixed by a gate that does not exist.\n", "ABSENCE-CLAIM", True),
        ("ABSENCE-CLAIM stays silent on a rival listed in the THOROUGH line",
         "THOROUGH: rivals - another session, or this one.\n", "ABSENCE-CLAIM", False),
        ("ABSENCE-CLAIM stays silent on a metric that cannot reach its floor",
         "The gate cannot reach its floor until then.\n", "ABSENCE-CLAIM", False),
        ("MUTATION: a CHECKED line with a search but NO control does not satisfy ABSENCE-CLAIM",
         "It is out of reach.\nCHECKED: drive -> searched the connector's calls.\n", "ABSENCE-CLAIM", True),
        # NOT-RUN-CLAIM, 2026-10-14 (Rob, "2. Approve" 08:28 PDT): the 07:2x sentence, both directions.
        ("NOT-RUN-CLAIM fires on the 2026-10-14 07:2x sentence with no CHECKED line",
         "You stopped the live drain before it started, so nothing moved on Instagram.\n", "NOT-RUN-CLAIM", True),
        ("NOT-RUN-CLAIM stays silent when a CHECKED line names the log that was read",
         "You stopped the live drain before it started, so nothing moved on Instagram.\n"
         "CHECKED: movelog3.md read end to end - 0 move rows after 07:00 PDT.\n", "NOT-RUN-CLAIM", False),
        ("NOT-RUN-CLAIM ignores a quoted 'nothing moved'",
         'You wrote "nothing moved" at 07:25 and I am checking the drain now.\n', "NOT-RUN-CLAIM", False),
        ("NOT-RUN-CLAIM stays silent on an unrelated reply",
         "The selftest passed and the zip is ready for upload.\n", "NOT-RUN-CLAIM", False),
        # SITE-FAULT, 2026-10-16 (0.2.14, F-594): both directions plus controls.
        ("SITE-FAULT fires on the F-594 shape with no control",
         "Anthem's site looks degraded right now, so I will retry later.\n", "SITE-FAULT", True),
        ("SITE-FAULT fires on a server that timed out",
         "The provider portal timed out four times between 12:30 and 12:47.\n", "SITE-FAULT", True),
        ("SITE-FAULT stays silent when a CHECKED line names a control that passed",
         "Anthem's site looks degraded right now.\nCHECKED: control doctor Yuhuan Frank Lan read 4.91 miles on the same tab; control passed, then the search timed out.\n",
         "SITE-FAULT", False),
        ("SITE-FAULT stays silent when the sentence blames Claude's own request",
         "My hand-built search request timed out against Anthem's server.\n", "SITE-FAULT", False),
        ("SITE-FAULT ignores a quoted claim",
         'You asked why I wrote "the site looks degraded" at 12:48.\n', "SITE-FAULT", False),
        ("SITE-FAULT stays silent on an unrelated reply",
         "The selftest passed and the zip is ready for upload.\n", "SITE-FAULT", False),
        ("SITE-FAULT stays silent when the timeout is explained by Claude's own session or tab",
         "Rebuilding the Anthem session, which has been idle long enough to have timed out.\n", "SITE-FAULT", False),
        ("MUTATION: a CHECKED line with no control does not satisfy SITE-FAULT",
         "The site is down.\nCHECKED: I tried twice and it hung.\n", "SITE-FAULT", True),
        ("NOT-RUN-CLAIM fires on a curly-apostrophe didn't run",
         "The triage task didn\u2019t run last night.\n", "NOT-RUN-CLAIM", True),
        ("NOT-RUN-CLAIM accepts a CHECKED line naming a session ID",
         "The watchdog never fired.\nCHECKED: cse_011DHGRVmzKwDfLmnEc7seZ1 transcript read, no tool calls after 06:00.\n",
         "NOT-RUN-CLAIM", False),
        ("MUTATION: a CHECKED line that names nothing read does not satisfy NOT-RUN-CLAIM",
         "Nothing ran overnight.\nCHECKED: I looked and it was fine.\n", "NOT-RUN-CLAIM", True),
        # TABLE-LAST, 2026-10-14 (Rob, approved 09:41 PDT): TABLE-AFTER-REVIEW, both directions.
        ("TABLE-AFTER-REVIEW fires when the PRE-SEND REVIEW line sits below the next-steps table",
         "Summary.\n\n| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n"
         "|---|---|---|---|---|---|---|\n| 1 | Zip built | Upload it | Rob | Upload 0.2.4. | Gate live. | One step. |\n\n"
         "PRE-SEND REVIEW: independent reviewer returned 1 findings - 1 fixed; fixed rows 1.\n",
         "TABLE-AFTER-REVIEW", True),
        ("TABLE-AFTER-REVIEW stays silent when the PRE-SEND REVIEW line sits above the table",
         "Summary.\nPRE-SEND REVIEW: independent reviewer returned 1 findings - 1 fixed; fixed rows 1.\n\n"
         "| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n"
         "|---|---|---|---|---|---|---|\n| 1 | Zip built | Upload it | Rob | Upload 0.2.4. | Gate live. | One step. |\n",
         "TABLE-AFTER-REVIEW", False),
        ("TABLE-AFTER-REVIEW fires on a curly-apostrophe header too",
         "| # | Issue / Risk | Action | Owner | Claude’s Recommendation | Pros | Cons |\n"
         "|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | E. |\n"
         "**PRE-SEND REVIEW:** independent reviewer returned 0 findings.\n", "TABLE-AFTER-REVIEW", True),
        ("TABLE-AFTER-REVIEW ignores a review line and table inside a code fence",
         "Example:\n```\n| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n"
         "| 1 | A | B | Rob | C. | D. | E. |\nPRE-SEND REVIEW: independent reviewer returned 0 findings.\n```\n",
         "TABLE-AFTER-REVIEW", False),
        # R287 (Rob 2026-10-15 10:04 PDT): CON-FORMAT and ID-NAME, both directions, with mutants.
        ("CON-FORMAT stays silent on Con, then bulleted Risk and Mitigation lines, NBSP-joined opening",
         "| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:\u00a0the\u00a0account\u00a0setting\u00a0stays\u00a0on\u00a0all day<br>\u2022 Risk: an app could use it.<br>\u2022 Mitigation: only granted apps can. |\n", "CON-FORMAT", False),
        ("CON-FORMAT fires when Risk and Mitigation run inline with no line breaks",
         "| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con: x y. Risk: z. Mitigation: w. |\n", "CON-FORMAT", True),
        ("MUTATION: CON-FORMAT fires when the Mitigation bullet is missing",
         "| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:\u00a0the\u00a0account\u00a0setting\u00a0stays\u00a0on\u00a0all day<br>\u2022 Risk: an app could use it. |\n", "CON-FORMAT", True),
        ("MUTATION: CON-FORMAT fires when the opening words use ordinary spaces",
         "| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con: the account setting stays on all day<br>\u2022 Risk: an app could use it.<br>\u2022 Mitigation: only granted apps can. |\n", "CON-FORMAT", True),
        ("CON-FORMAT accepts a two-word Con joined by one NBSP",
         "| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:\u00a0none\u00a0measured<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "CON-FORMAT", False),
        ("CON-FORMAT stays silent with no next-steps table", "Prose only.\n", "CON-FORMAT", False),
        ("SELFCHECK fires on a next-steps table with no SELF-CHECK line",
         "Text.\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:&nbsp;x<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "SELFCHECK", True),
        ("SELFCHECK fires when the line has no confidence rating",
         "SELF-CHECK: thorough: yes - read all.\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:&nbsp;x<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "SELFCHECK", True),
        ("SELFCHECK fires when the rating names nothing that lowers it",
         "SELF-CHECK: thorough: yes - read all; confidence: 8/10 in the recommendations and next steps.\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:&nbsp;x<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "SELFCHECK", True),
        ("SELFCHECK fires when the thorough answer is missing",
         "SELF-CHECK: confidence: 8/10, drops to 4 if X.\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:&nbsp;x<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "SELFCHECK", True),
        ("SELFCHECK stays silent on a complete line",
         "SELF-CHECK: thorough: yes - read the full log; confidence: 10/10 in the recommendations and next steps, no residual uncertainty.\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:&nbsp;x<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "SELFCHECK", False),
        ("SELFCHECK stays silent with no next-steps table", "Prose only.\n", "SELFCHECK", False),
        ("CON-FORMAT accepts &nbsp; entities as the joining spaces",
         "| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:&nbsp;the&nbsp;account&nbsp;setting&nbsp;stays&nbsp;on&nbsp;all day<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "CON-FORMAT", False),
        ("ROOTCAUSE fires on a Claude row with no CAUSE statement", _rc_text([("A broke", "Claude")]), "ROOTCAUSE", True),
        ("ROOTCAUSE fires when the CAUSE says nothing about how well it is known", _rc_text([("A broke. CAUSE: the gate is wrong.", "Claude")]), "ROOTCAUSE", True),
        ("ROOTCAUSE fires when two rows carry the same CAUSE text", _rc_text([("A broke. CAUSE: never entered in the register (inferred).", "Claude"), ("B broke. CAUSE: never entered in the register (inferred).", "Claude")]), "ROOTCAUSE", True),
        ("ROOTCAUSE stays silent on a Rob row with no cause", _rc_text([("A decision", "Rob")]), "ROOTCAUSE", False),
        ("ROOTCAUSE stays silent on two rows with distinct marked causes", _rc_text([("A broke. CAUSE: the date is wrong (measured).", "Claude"), ("B broke. CAUSE: inferred; the Action reads it.", "Claude")]), "ROOTCAUSE", False),
        ("ROOTCAUSE fires on a Claude row whose CAUSE is not yet investigated", _rc_text([("A broke. CAUSE: not yet investigated; the Action reads it.", "Claude")]), "ROOTCAUSE", True),
        ("ROOTCAUSE stays silent on a standing process row", _rc_text([("APPROVAL: row 7 is the only decision", "Claude")]), "ROOTCAUSE", False),
        ("PREVENTS fires on a Claude row with no Prevents recurrence clause", _pv_text([("A. CAUSE: x (measured).", "B", "Claude")]), "PREVENTS", True),
        ("PREVENTS fires on a boilerplate clause that names no check", _pv_text([("A. CAUSE: x (measured).", "B. Prevents recurrence: the reply gate's refusal", "Claude")]), "PREVENTS", True),
        ("PREVENTS fires on an invented check name", _pv_text([("A. CAUSE: x (measured).", "B. Prevents recurrence: zzfakecheck.py refuses it", "Claude")]), "PREVENTS", True),
        ("PREVENTS fires when two rows carry the same clause", _pv_text([("A. CAUSE: x (measured).", "B. Prevents recurrence: ROOTCAUSE", "Claude"), ("C. CAUSE: y (measured).", "D. Prevents recurrence: ROOTCAUSE", "Claude")]), "PREVENTS", True),
        ("PREVENTS stays silent on a clause naming a registered check", _pv_text([("A. CAUSE: x (measured).", "B. Prevents recurrence: ROOTCAUSE refuses it", "Claude")]), "PREVENTS", False),
        ("PREVENTS stays silent on JUDGEMENT-ONLY", _pv_text([("A. CAUSE: x (measured).", "B. Prevents recurrence: JUDGEMENT-ONLY, no check can see it", "Claude")]), "PREVENTS", False),
        ("PREVENTS stays silent on a Rob row and a standing row", _pv_text([("A decision", "B", "Rob"), ("APPROVAL: row 7", "B", "Claude")]), "PREVENTS", False),
        ("PREVENTS-COUNT reports JUDGEMENT-ONLY rows", _pv_text([("A. CAUSE: x (measured).", "B. Prevents recurrence: JUDGEMENT-ONLY, no check", "Claude")]), "PREVENTS-COUNT", True),
        ("SELFCHECK fires on thorough: partly with no BLOCKED reason", _rc_text([("A. CAUSE: x (measured).", "Claude")], sc="thorough: partly - the other 249 rows are not covered; confidence: 6/10 in the recommendations and next steps, drops to 4 if X."), "SELFCHECK", True),
        ("SELFCHECK fires on thorough: partly even with a BLOCKED reason (R428)", _rc_text([("A. CAUSE: x (measured).", "Claude")], sc="thorough: partly - BLOCKED: read_file on the export returned permission denied; confidence: 6/10 in the recommendations and next steps, drops to 4 if X."), "SELFCHECK", True),
        ("SELFCHECK fires on thorough: no that blames open rows and names nothing NOT READ (F-1047)", _rc_text([("A. CAUSE: x (measured).", "Claude")], sc="thorough: no, because these register rows are open; BLOCKED: Rob row 1; confidence: 5/10 in the recommendations and next steps, drops to 3 if X."), "SELFCHECK", True),
        ("SELFCHECK fires on thorough: no in a reply with no table (Rob 12:10 PDT)", "Done.\n\nSELF-CHECK: thorough: no - NOT READ: session X; BLOCKED: read returned permission denied; confidence: 5/10 in the recommendations and next steps, drops to 3 if X.\n", "SELFCHECK", True),
        ("SELFCHECK stays silent on thorough: yes in a reply with no table (Rob 12:10 PDT)", "Done.\n\nSELF-CHECK: thorough: yes - read all; confidence: 10/10 in the recommendations and next steps, no residual uncertainty.\n", "SELFCHECK", False),
        ("SELFCHECK fires on a drops to in a reply with no table (Rob 2026-11-03 10:18 PM PST)", "Done.\n\nSELF-CHECK: thorough: yes - read all; confidence: 8/10 in the recommendations and next steps, drops to 4 if X.\n", "SELFCHECK", True),
        ("SELFCHECK fires on thorough: no even when it names the unread source and the failed call (Rob 12:10 PDT)", _rc_text([("A. CAUSE: x (measured).", "Claude")], sc="thorough: no - NOT READ: the export of session X; BLOCKED: read_file returned permission denied; confidence: 5/10 in the recommendations and next steps, drops to 3 if X."), "SELFCHECK", True),
        ("ID-NAME fires on a bare register id", "OI-0059 is open.\n", "ID-NAME", True),
        ("ID-NAME fires on a bare session id", "Session session_018nNiPnBytaJtATmK3QyqXE wrote it.\n", "ID-NAME", True),
        ("ID-NAME accepts an id followed by its name in parentheses",
         "OI-0059 (wrong times in five register rows) is open.\n", "ID-NAME", False),
        ("ID-NAME accepts a quoted title followed by the id in parentheses",
         "The chat \"Claude audit text fixes\" (session_01JtSX8hxt2aVrM4AgXZtMLN) ran it.\n", "ID-NAME", False),
        ("ID-NAME accepts a range with one name", "OI-0054 to OI-0058 (five closed rows) stay.\n", "ID-NAME", False),
        ("ID-NAME accepts a range joined by &nbsp; entities", "OI-0054&nbsp;to&nbsp;OI-0058&nbsp;(five closed rows) stay.\n", "ID-NAME", False),
        ("MUTATION: ID-NAME fires when the parentheses hold only another id", "OI-0059 (OI-0235) stays.\n", "ID-NAME", True),
        ("MUTATION: ID-NAME fires on a bare id inside parentheses after ordinary prose",
         "A cell cannot be edited (OI-0017).\n", "ID-NAME", True),
        ("ID-NAME ignores ids inside double quotes, backticks and link targets",
         "It printed \"CLOSED OI-0234 as DONE\" and `trig_01Mk4HHSFUp5T9WR8AC5pEhK`; [run](https://claude.ai/code/session_01R9FTLwymjoQfqPt9GNgMfG).\n",
         "ID-NAME", False),
        # R291 (Rob 2026-10-15 11:12 PDT): OBJECTIVE-SECTIONS, both directions, with mutants.
        ("OBJECTIVE-SECTIONS stays silent on two objectives, a DONE one with no table, continuous numbering",
         "OBJECTIVE 1 - Fix text [DONE 2026-10-08 9:00 AM]\n\nOBJECTIVE 2 - Gate [IN PROGRESS]\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n\nOBJECTIVE 3 - Loop [IN PROGRESS]\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 2 | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "OBJECTIVE-SECTIONS", False),
        ("OBJECTIVE-SECTIONS fires on a table with no objective line above it", "Intro.\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "OBJECTIVE-SECTIONS", True),
        ("MUTATION: OBJECTIVE-SECTIONS fires on the old 'Claude's Recommendation' header", "OBJECTIVE 1 - Gate [IN PROGRESS]\n\n| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "OBJECTIVE-SECTIONS", True),
        ("MUTATION: OBJECTIVE-SECTIONS fires when a DONE objective carries a table", "OBJECTIVE 1 - Gate [DONE 2026-10-15 9:00 AM]\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "OBJECTIVE-SECTIONS", True),
        ("MUTATION: OBJECTIVE-SECTIONS fires when two tables reuse row 1", "OBJECTIVE 1 - A [IN PROGRESS]\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n\nOBJECTIVE 2 - B [NOT STARTED]\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "OBJECTIVE-SECTIONS", True),
        ("CELL-WIDTH fires on a raw URL in Action",
         "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | Open https://claude.ai/chat/ac2b6ddc | Rob | C. | D. | Con:\u00a0one\u00a0extra\u00a0step\u00a0before\u00a0it\u00a0works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "CELL-WIDTH", True),
        ("CELL-WIDTH fires on a 32-character unbroken ID in Issue / Risk",
         "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | hash 0123456789abcdef0123456789abcdef bad | B | Rob | C. | D. | Con:\u00a0one\u00a0extra\u00a0step\u00a0before\u00a0it\u00a0works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "CELL-WIDTH", True),
        ("CELL-WIDTH fires on a raw URL in Cons (0.2.38, O3 screenshot 2026-10-22 22:26 PDT)",
         "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:\u00a0one\u00a0extra\u00a0step\u00a0before\u00a0it\u00a0works<br>\u2022 Risk: r.<br>\u2022 Mitigation: copy it (https://docs.google.com/spreadsheets/d/169brVy2OmDdl6xeQEWfSK9o9MfrvMntLSSPOSPCnY2c) first. |\n", "CELL-WIDTH", True),
        ("CELL-WIDTH stays silent on a link label with a long target",
         "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | Open [the O3 session](https://claude.ai/chat/ac2b6ddc-b5ec-4ead-b0e8-17b2b378b59f) now | Rob | C. | D. | Con:\u00a0one\u00a0extra\u00a0step\u00a0before\u00a0it\u00a0works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "CELL-WIDTH", False),
        ("CELL-WIDTH stays silent on ordinary short cells",
         "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A short issue here | B short action here | Rob | C. | D. | Con:\u00a0one\u00a0extra\u00a0step\u00a0before\u00a0it\u00a0works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n", "CELL-WIDTH", False),
        ("CON-FORMAT now reads the second table too", "OBJECTIVE 1 - A [IN PROGRESS]\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n\nOBJECTIVE 2 - B [IN PROGRESS]\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 2 | A | B | Rob | C. | D. | Con: x. Risk: y. |\n", "CON-FORMAT", True),
        ("REVIEW-FIX-APPLIED is silent with no REPLYCHECK_DRAFT (text-only path)",
         "PRE-SEND REVIEW: independent reviewer returned 2 findings - 2 fixed.\n", "REVIEW-FIX-APPLIED", False),
        ("SENT-CHECKED stays silent on a short reply with no THOROUGH line",
         "Just a short answer.\n", "SENT-CHECKED", False),
        # RULINGS-CITED and STANDING-QUOTE, R066 2026-09-20, both directions.
        ("RULINGS-CITED fires on a recommendation with no RULINGS CHECKED line",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do it. Test: bin/x.py prints 0. Fails if: it prints 1. | Pro: x. Con: y. |\n", "RULINGS-CITED", True),
        ("RULINGS-CITED fires when the line names no ruling and does not say none apply",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do it. Test: bin/x.py prints 0. Fails if: it prints 1. | Pro: x. Con: y. |\nRULINGS CHECKED: looked at some of them.\\n", "RULINGS-CITED", True),
        ("RULINGS-CITED fires when rulings are named with nothing said about them",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do it. Test: bin/x.py prints 0. Fails if: it prints 1. | Pro: x. Con: y. |\nRULINGS CHECKED: R017, R057\\n", "RULINGS-CITED", True),
        ("RULINGS-CITED stays silent on a named-and-dismissed line",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do it. Test: bin/x.py prints 0. Fails if: it prints 1. | Pro: x. Con: y. |\nRULINGS CHECKED: R017 and R057, neither applies because both are about reading files, not about this gate.\\n", "RULINGS-CITED", False),
        # R128: a ruling id past R099 is a ruling id.
        ("RULINGS-CITED stays silent on a line citing only a three-digit ruling past R099 (R128)",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do it. Test: bin/x.py prints 0. Fails if: it prints 1. | Pro: x. Con: y. |\nRULINGS CHECKED: R127 governs this because it approved the change.\\n", "RULINGS-CITED", False),
        ("RULINGS-CITED stays silent on 'none apply'",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do it. Test: bin/x.py prints 0. Fails if: it prints 1. | Pro: x. Con: y. |\nRULINGS CHECKED: none apply.\\n", "RULINGS-CITED", False),
        ("RULINGS-CITED stays silent on a reply whose only row is a no-op",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | None. | Pro: x. Con: y. |\n", "RULINGS-CITED", False),
        ("STANDING-QUOTE fires on a standing row claiming nothing with no output quoted",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | PROCESS AUDIT - NO-ARTIFACT | Open | Rob | Nothing this reply. | Pro: x. Con: y. |\nRULINGS CHECKED: none apply.\\n", "STANDING-QUOTE", True),
        ("STANDING-QUOTE stays silent when the row quotes a count",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | PROCESS AUDIT - NO-ARTIFACT | Open | Rob | Nothing this reply: the miss logger reports 64 rows, unchanged. | Pro: x. Con: y. |\nRULINGS CHECKED: none apply.\\n", "STANDING-QUOTE", False),
        ("STANDING-QUOTE stays silent on a standing row that reports a real finding",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | PROCESS AUDIT - NO-ARTIFACT | Open | Rob | I stopped early once. Test: stopcheck quoted in 10 replies. Fails if: one is missing. | Pro: x. Con: y. |\nRULINGS CHECKED: none apply.\\n", "STANDING-QUOTE", False),
        # TEST-FIELD, R065 2026-09-20, both directions on every branch.
        ("TEST-FIELD fires on a recommendation with no Test clause",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do the thing because it is better. | Pro: x. Con: y. |\n", "TEST-FIELD", True),
        ("TEST-FIELD fires on a Test naming nothing runnable",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do the thing. Test: verify it worked. Fails if: it did not work out in practice. | Pro: x. Con: y. |\n", "TEST-FIELD", True),
        ("TEST-FIELD fires on a Test with no Fails-if",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do the thing. Test: bin/misslog.py report shows under 6 per 10 replies. | Pro: x. Con: y. |\n", "TEST-FIELD", True),
        ("TEST-FIELD fires when Fails-if only restates the Test",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do the thing. Test: bin/misslog.py report shows under 6 per 10 replies. Fails if: bin/misslog.py report shows 6 or more per 10 replies. | Pro: x. Con: y. |\n", "TEST-FIELD", True),
        ("TEST-FIELD stays silent on a runnable Test plus a distinct Fails-if",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | Do the thing. Test: bin/misslog.py report shows under 6 per 10 over the next 30 replies. Fails if: Rob overrules another row for the same reason. | Pro: x. Con: y. |\n", "TEST-FIELD", False),
        ("TEST-FIELD stays silent on a declared no-op row",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Rob | None. | Pro: x. Con: y. |\n", "TEST-FIELD", False),
        # STANDING-ROWS (0.2.16: five objective-process rows, keyed on the next-steps header), both directions.
        ("STANDING-ROWS fires when a next-steps table carries none of them",
         "| # | Issue / Risk | Action | Owner |\n| 1 | DO Y | Open | Claude |\n", "STANDING-ROWS", True),
        ("STANDING-ROWS fires when only some are present",
         "| # | Issue / Risk | Action | Owner |\n| 1 | INSTRUCTION FIELD FIRST | Open | Claude |\n| 2 | HOSTILE REVIEW | Open | Claude |\n",
         "STANDING-ROWS", True),
        ("STANDING-ROWS stays silent when all five are present",
         "| # | Issue / Risk | Action | Owner |\n| 1 | INSTRUCTION FIELD FIRST | Open | Claude |\n| 2 | CONFORMANCE CHECK | Open | Claude |\n| 3 | HOSTILE REVIEW | Open | Claude |\n| 4 | SAMPLE GATE | Open | Claude |\n| 5 | APPROVAL | Open | Rob |\n",
         "STANDING-ROWS", False),
        ("STANDING-ROWS stays silent when two are present and three are named DONE",
         "STANDING ROWS DONE: INSTRUCTION FIELD FIRST, CONFORMANCE CHECK, SAMPLE GATE\n| # | Issue / Risk | Action | Owner |\n| 1 | HOSTILE REVIEW | Open | Claude |\n| 2 | APPROVAL | Open | Rob |\n",
         "STANDING-ROWS", False),
        ("STANDING-ROWS stays silent on a table that is not a next-steps table",
         "| # | Item | Status | Owner |\n| 1 | DO Y | Open | Claude |\n", "STANDING-ROWS", False),
        ("STANDING-ROWS stays silent when there is no table at all",
         "A single-fact answer owes no table.\n", "STANDING-ROWS", False),
        # POSITIVE: the code must appear.
        ("PROSE-DECISION fires when the reply asks in prose and no row is Rob's",
         "Say the word and I will re-export.\n\n| # | Item | Status | Owner |\n| 1 | DO Y | Open | Claude |\n", "PROSE-DECISION", True),
        ("PROSE-DECISION stays silent when the ask is also a Rob-owned row",
         "Say the word and I will re-export.\n\n| # | Item | Status | Owner |\n| 1 | DO Y | Open | Claude |\n| 2 | APPROVE X | Open | Rob - approval |\n", "PROSE-DECISION", False),
        ("PROSE-DECISION stays silent with no asking phrase at all",
         "Here is the result.\n\n| # | Item | Status | Owner |\n| 1 | DO Y | Open | Claude |\n", "PROSE-DECISION", False),

        ("THOROUGH-SIX fires on a rating with no THOROUGH line",
         "Some prose.\n\n8/10, drops to 3 if the header list is stale.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires when the line omits one of the six",
         "THOROUGH: criterion validated - single-source on X - disconfirming pass run - rivals listed\n\n8/10 drops to 3.\n",
         "THOROUGH-SIX", True),
        ("THOROUGH-SIX stays silent on a complete line",
         "THOROUGH: criterion validated vs the activity - numbers single-source on the 1.9s read - disconfirming pass run - nothing in my own column changes the above - rivals listed with killers - enumeration published, each entry marked searched or not searched\n\nText. 8/10 drops to 3 if X.\n", "THOROUGH-SIX", False),
        ("THOROUGH-SIX stays silent when there is no rating at all",
         "Just prose with no rating anywhere.\n", "THOROUGH-SIX", False),
        # ---- BARE RATING, added 2026-09-29. The exact sentence that shipped unchecked. ----
        ("THOROUGH-SIX fires on a bare 'Confidence 8 that' rating with no /10",
         "Some prose.\n\nConfidence 8 that items 1 and 2 are the right fixes. What would change it: a moved file.\n",
         "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on 'Confidence: 7'",
         "Some prose.\n\nConfidence: 7, drops to 4 if the header is stale.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX stays silent on 'confidence 95%', a percentage and not a rating",
         "The classifier reports confidence 95% on the sample.\n", "THOROUGH-SIX", False),
        ("THOROUGH-SIX stays silent on 'confidence 2026-09-29', a date",
         "Logged under confidence 2026-09-29 in the sheet.\n", "THOROUGH-SIX", False),
        # ---- WIDENED 2026-09-29 by the 25-form battery. The first is the live archived shape. ----
        ("THOROUGH-SIX fires on 'Confidence that X: 9 out of 10'",
         "Confidence that archiving now loses nothing you will want: 9 out of 10. What would change it: X.\n",
         "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on 'I'd put this at 8 out of 10'",
         "I'd put this at 8 out of 10, drops to 5 if X.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX stays silent on '8 out of 10 rows', a count",
         "The check passed on 8 out of 10 rows.\n", "THOROUGH-SIX", False),
        ("THOROUGH-SIX fires on an em-dash rating 'Confidence — 8'",
         "Confidence — 8, drops to 5 if X.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on a table cell '| Confidence | 8 |'",
         "| Item | x |\n| Confidence | 8 |\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on a rating in words, 'fairly confident'",
         "I am fairly confident this is the cause.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on 'I'd rate this 8'", "I'd rate this 8, drops to 5 if X.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on 'confident at 7'", "I'm confident at 7 that this holds.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on 'Certainty: 8'", "Certainty: 8. Drops to 5 if X.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on 'Confidence eight'", "Confidence eight that this holds.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX fires on '80% confident'", "I am 80% confident this holds.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX stays silent on 'rated 3 replies', a count", "The gate rated 3 replies today.\n", "THOROUGH-SIX", False),
        ("THOROUGH-SIX fires on 'confidence is capped at 5' (held-out miss)",
         "No dataset publishes it, so confidence is capped at 5 on anything resting on it.\n", "THOROUGH-SIX", True),
        ("THOROUGH-SIX stays silent on a quoted word rating, Rob's own question",
         "Rob asked \"ARE YOU EXTREMELY CONFIDENT?\" and the answer is in the table.\n", "THOROUGH-SIX", False),
        ("THOROUGH-SIX stays silent on 'confidence' as a plain noun",
         "The classifier's confidence field is empty on these rows.\n", "THOROUGH-SIX", False),
        # ---- SOURCING MUST CITE. Added 2026-09-10 after the words passed and the claim was false. ----
        ("SOURCING claimed but never cited FAILS",
         "%s\n\n8/10 drops to 3 if X.\n" % BAD5, "THOROUGH-SIX", True),
        ("CONTROL: the same claim WITH a second reader cited passes",
         "CHECKED: classification -> given a second reader blind to my verdicts.\n\n%s\n\n8/10 drops to 3 if X.\n" % BAD5,
         "THOROUGH-SIX", False),
        ("CONTROL: the honest admission passes with nothing cited",
         "%s\n\n5/10 drops to 2 if X.\n" % OK5, "THOROUGH-SIX", False),
        # ---- THE TRIGGER IS NO LONGER ONLY A RATING. ----
        ("a shipping recommendation with NO rating and no THOROUGH line FAILS",
         "The measurement is done and I recommend enabling it for every surface.\n",
         "THOROUGH-SIX", True),
        ("CONTROL: ordinary prose with neither a rating nor a recommendation stays silent",
         "Here is what the file says and what it does.\n", "THOROUGH-SIX", False),
        # ---- DEPLOYED POPULATION. ----
        ("a rate plus a shipping recommendation with no deployed population FAILS",
         "CHECKED: corpus -> 3 percent false positives over 821 replies.\n\n%s\n\nI recommend enabling it.\n" % OK5,
         "THOROUGH-SIX", True),
        ("CONTROL: naming the population it will run on passes",
         "CHECKED: corpus -> 3 percent false positives over 821 replies; it will run against every reply in all eleven projects.\n\n%s\n\nI recommend enabling it.\n" % OK5,
         "THOROUGH-SIX", False),

        ("OPENER fires on agreement", "You are right, good catch.\nSomething else.\n", "OPENER", True),
        ("OPENER fires on 'Understood.' (0.3.7)", "Understood. I changed nothing.\nThe finding is below.\n", "OPENER", True),
        ("OPENER fires on 'Both of your answers are recorded' (0.3.7)", "Both of your answers are recorded; line 100 needs a paste.\n", "OPENER", True),
        ("OPENER fires on 'Got it' (0.3.7)", "Got it, the count moved.\n", "OPENER", True),
        ("OPENER stays silent on a finding-first reply (0.3.7 control)", "The count moved from 12 to 14 and the file is 42 bytes larger.\n", "OPENER", False),
        ("OPENER stays silent on 'Notes' as a noun (0.3.7 control)", "Notes from the run are in the file.\n", "OPENER", False),
        ("AGREEMENT fires on a MID-REPLY you're right, which check_opener cannot see",
         "The manifest was regenerated.\nYou're right that the count moved.\n", "AGREEMENT", True),
        ("AGREEMENT fires on the curly apostrophe form",
         "A note.\nYou\u2019re right about the drift.\n", "AGREEMENT", True),
        ("AGREEMENT fires on the UNCONTRACTED you are right",
         "A note.\nYou are right that the count moved.\n", "AGREEMENT", True),
        ("AGREEMENT does NOT fire on the adverb exactly",
         "All 40 derived keys match exactly, zero missing.\n", "AGREEMENT", False),
        ("AGREEMENT does NOT fire on a plain factual reply",
         "The count was wrong and the file is now 42,647 bytes.\n", "AGREEMENT", False),
        # ---- R078 PRE-SEND REVIEW (Rob, 2026-09-20 "Approved"). Written BEFORE the check existed and
        # run against it to watch the two must-fire cases fail. A reply that asks Rob to decide
        # something must carry the independent reviewer's findings and what was done with each.
        ("PRE-SEND-REVIEW fires on a decision reply with no review line",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A DECISION - NO-ARTIFACT | Open | Rob | Approve it. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "PRE-SEND-REVIEW", True),
        ("PRE-SEND-REVIEW stays silent when the review line names its findings",
         "PRE-SEND REVIEW: independent reviewer returned 3 findings - 2 fixed, 1 disputed because the count was measured.\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A DECISION - NO-ARTIFACT | Open | Rob | Approve it. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "PRE-SEND-REVIEW", False),
        ("PRE-SEND-REVIEW fires on a PLACEHOLDER line, which is the shape an unrun review takes",
         "PRE-SEND REVIEW: filled in after the reviewer runs on this draft.\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A DECISION - NO-ARTIFACT | Open | Rob | Approve it. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "PRE-SEND-REVIEW", True),
        # P6-14, 2026-09-21: every full reply needs the independent reviewer.
        ("PRE-SEND-REVIEW fires on a full reply with no review line",
         "THOROUGH: sourcing - x.\n\nBody.\n", "PRE-SEND-REVIEW", True),
        ("PRE-SEND-REVIEW fires on a full reply whose review is a self-review",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: 1 finding, self-review, no independent reviewer.\n",
         "PRE-SEND-REVIEW", True),
        ("R120 PRE-SEND-REVIEW fires on 'none run on this reply, 0 findings' - 16 archived replies",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: none run on this reply, 0 findings.\n",
         "PRE-SEND-REVIEW", True),
        ("R120 PRE-SEND-REVIEW fires on the 17:48 and 17:51 PDT wording 'no fresh reviewer read this text'",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: 0 findings; no fresh reviewer read this text.\n",
         "PRE-SEND-REVIEW", True),
        ("R120 PRE-SEND-REVIEW fires on 'not re-run, so 0 findings'",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: not re-run, so 0 findings.\n",
         "PRE-SEND-REVIEW", True),
        ("R120 PRE-SEND-REVIEW fires on a count with no reviewer named",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: 4 findings, all fixed.\n",
         "PRE-SEND-REVIEW", True),
        ("R120 THOROUGH-SIX fires on 'NOT MET' with no BLOCKER - the 17:51 PDT line (CORRECTED from 17:48, F-314)",
         "THOROUGH: NOT MET on sourcing, rivals and disconfirming pass. Criterion, own column and enumeration met.\n\nConfidence 4; changes if X.\n",
         "THOROUGH-SIX", True),
        ("R120 THOROUGH-SIX stays silent on an unmet criterion citing a Downstream row",
         "Opening line.\n\nTHOROUGH: criterion met - sourcing single-source - disconfirming pass run - own column clean - rivals listed - enumeration unmet, BLOCKER: row 1.\n\nConfidence 4; changes if X.\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | RELAUNCH CHECK - NO-ARTIFACT | Downstream: waits on a relaunch | Claude | Do it then. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n",
         "THOROUGH-SIX", False),
        ("R120b THOROUGH-SIX fires when the line is NOT first - the empty-slice bug",
         "Opening line.\n\nTHOROUGH: NOT MET on sourcing. Criterion, disconfirming pass, own column, rivals and enumeration met.\n\nConfidence 4; changes if X.\n",
         "THOROUGH-SIX", True),
        ("R120b THOROUGH-SIX fires on a keyword blocker with no row",
         "THOROUGH: NOT MET on sourcing, BLOCKER: I would approve it myself. Criterion, disconfirming pass, own column, rivals, enumeration met.\n\nConfidence 4; changes if X.\n",
         "THOROUGH-SIX", True),
        ("R120b THOROUGH-SIX fires on 'missing' - a synonym the first version let through",
         "THOROUGH: criterion met - sourcing single-source - disconfirming pass missing - own column clean - rivals listed - enumeration published.\n\nConfidence 4; changes if X.\n",
         "THOROUGH-SIX", True),
        ("R120c PRE-SEND-REVIEW fires on the template plus 'skipped this turn'",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: independent reviewer returned 0 findings; it was skipped this turn.\n",
         "PRE-SEND-REVIEW", True),
        ("R120c PRE-SEND-REVIEW fires on the template plus 'hypothetical; reviewer not launched'",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: independent reviewer returned 2 findings (hypothetical; reviewer not launched).\n",
         "PRE-SEND-REVIEW", True),
        ("R120c THOROUGH-SIX fires on an admission on the line below the THOROUGH line",
         "THOROUGH: criterion met - sourcing single-source, unverified - own column clean - enumeration published.\nDisconfirming pass: not done. Rivals: not done.\n\nConfidence 4; changes if X.\n",
         "THOROUGH-SIX", True),
        ("R120c THOROUGH-SIX fires on 'deferred'",
         "THOROUGH: criterion met. Sourcing single-source, unverified. Disconfirming pass - deferred. Own column clean. Rivals listed. Enumeration done.\n\nConfidence 5; changes if X.\n",
         "THOROUGH-SIX", True),
        ("R120c THOROUGH-SIX stays silent on the permitted 'single-source, unverified'",
         "THOROUGH: criterion met. Sourcing single-source, unverified. Disconfirming pass run. Own column clean. Rivals listed. Enumeration done.\n\nConfidence 5; changes if X.\n",
         "THOROUGH-SIX", False),
        ("R120b PRE-SEND-REVIEW fires on 'independent review waived' - a reviewer-found evasion",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: 0 findings; independent review waived for this reply.\n",
         "PRE-SEND-REVIEW", True),
        ("R120b PRE-SEND-REVIEW fires on 'independent reviewer read nothing; none run' - the guard bypass",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: independent reviewer read nothing; none run, 0 findings.\n",
         "PRE-SEND-REVIEW", True),
        ("PRE-SEND-REVIEW stays silent on a full reply reviewed independently",
         "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: independent reviewer returned 2 findings, both fixed.\n",
         "PRE-SEND-REVIEW", False),
        ("CONTROL a reply whose open rows are all Claude's is not a decision reply",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Claude | Do it. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "PRE-SEND-REVIEW", False),
        ("CONTROL a Rob row already Done asks for no decision",
         "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | A DECISION - NO-ARTIFACT | Done | Rob | Approved. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n", "PRE-SEND-REVIEW", False),
        ("STOP-WHILE-UNBLOCKED fires on an empty Rob block",
         "NEXT STEPS\n\n**Blocked on Rob**\n\n1. **NOTHING.**\n\n**Claude can do now**\n\n2. **X** - y\n",
         "STOP-WHILE-UNBLOCKED", True),
        ("STOP-WHILE-UNBLOCKED stays silent when a real Rob item exists",
         "NEXT STEPS\n\n**Blocked on Rob**\n\n1. **APPROVE THE WRITE** - y\n\n**Claude can do now**\n\n2. **X** - y\n",
         "STOP-WHILE-UNBLOCKED", False),
        ("STOP-WHILE-UNBLOCKED stays silent on a reply with no next-steps block",
         "CHECKED: x -> y\n\nThe answer is 42.\n", "STOP-WHILE-UNBLOCKED", False),

        # --- THE NO-TABLE STOP, added 2026-08-31 after four replies passed while stopping.
        ("STOP-WHILE-UNBLOCKED fires on a no-table reply whose tail says work remains",
         "CHECKED: x -> y\n\nNine more read.\n\n86 remain: 62 in finance, 21 in job search.\n",
         "STOP-WHILE-UNBLOCKED", True),
        ("STOP-WHILE-UNBLOCKED fires on a bare 'Continuing.' close with nothing blocked",
         "CHECKED: x -> y\n\nDid the thing.\n\nContinuing.\n", "STOP-WHILE-UNBLOCKED", True),
        ("MUTATION: the same tail WITH a Rob-owned item does not fire",
         "CHECKED: x -> y\n\n| # | Item | Status | Owner |\n| 1 | RULE ON X | Open | Rob |\n\n86 remaining.\n",
         "STOP-WHILE-UNBLOCKED", False),
        ("a finished reply saying so in those words does not fire",
         "CHECKED: x -> y\n\nAll 137 are read. The work is finished.\n",
         "STOP-WHILE-UNBLOCKED", False),
        # THE FIXTURE HERE IS DELIBERATELY LONG. The first version was four lines, so the
        # six-line tail window swallowed the whole reply and the control failed. The check was
        # right and the control was wrong - a real reply has a body. Lengthened rather than
        # widening the check, because narrowing the tail to pass a short fixture would have
        # let the actual defect back through.
        ("CONTROL: 'remaining' earlier in the body, not in the tail, does not fire",
         "CHECKED: x -> y\n\n86 remaining at the start of today.\n\nOne.\nTwo.\nThree.\n"
         "Four.\nFive.\nSix.\nSeven.\n\nAll of them are now read and the work is finished.\n",
         "STOP-WHILE-UNBLOCKED", False),

        # --- GLOSS, added 2026-08-31 after Rob said three times he could not follow a phrase.
        ("GLOSS fires on an unglossed registered phrase",
         "The wrong-token test is decisive because its cost profile carries the proof.\n",
         "GLOSS", True),
        ("GLOSS stays silent when the same phrase is glossed in its own paragraph",
         "The wrong-token test is decisive because of its cost profile - it took fifteen "
         "seconds on a request that should have returned instantly.\n", "GLOSS", False),
        ("GLOSS does not fire on a CHECKED evidence line",
         "CHECKED: cost profile -> 15.7s\n", "GLOSS", False),
        ("GLOSS is paragraph-scoped, so a gloss in a DIFFERENT paragraph does not excuse it",
         "It took fifteen seconds.\n\nThe cost profile settles it.\n", "GLOSS", True),
        # RANK-OWNER RETIRED 2026-08-25 - Rob ruled one stack-ranked list, owner as a column,
        # so a check that ranks by owner would fight the ranking rules. Replaced by these.
        ("SPLIT-BY-OWNER fires when the reply still splits into two owner sections",
         "NEXT STEPS\n\n**Blocked on Rob**\n\n1. **APPROVE X** - y\n\n**Claude can do now**\n\n2. **DO Y** - z\n",
         "SPLIT-BY-OWNER", True),
        ("SPLIT-BY-OWNER stays silent on a single table with an Owner column",
         "| # | Item | Status | Owner |\n| 1 | DO Y | Open | Claude |\n| 2 | APPROVE X | Open | Rob - approval |\n",
         "SPLIT-BY-OWNER", False),
        ("STOP-WHILE-UNBLOCKED stays silent when an OPEN row is Rob's",
         "| # | Item | Status | Owner |\n| 1 | DO Y | Open | Claude |\n| 2 | APPROVE X | Open | Rob - approval |\n",
         "STOP-WHILE-UNBLOCKED", False),
        ("STOP-WHILE-UNBLOCKED stays silent when nothing is open at all",
         "| # | Item | Status | Owner |\n| 1 | DONE A | Completed | Claude |\n| 2 | DEAD B | Obsolete | Claude |\n",
         "STOP-WHILE-UNBLOCKED", False),
        ("STOP-WHILE-UNBLOCKED still covers the RETIRED two-section shape",
         "NEXT STEPS\n\n**Blocked on Rob**\n\n1. **NOTHING.**\n\n**Claude can do now**\n\n2. **X** - y\n",
         "STOP-WHILE-UNBLOCKED", True),
        ("OPENER-YOU fires on a reader-first opener", "You might want to look at this.\nThe value moved.\n", "OPENER-YOU", True),
        ("OFFLOAD fires on a handed-back check", "The value moved.\nWorth checking on your end.\n", "OFFLOAD", True),
        # THIS CONTROL FAILED ON ITS FIRST WRITING AND THE CHECK WAS RIGHT. I put the noun
        # in DOUBLE QUOTES, which check_tool_deadend deliberately scrubs so that quoted rule
        # text is not mistaken for a live claim. The control tested the scrub, not the check.
        ("TOOL-DEADEND fires on an untested incapability", "I have no way to observe the settings page from here.\n", "TOOL-DEADEND", True),
        # *** REACH-UNSOURCED HAD 14 AD-HOC CONTROLS AND ZERO REGISTERED ONES, FOUND 2026-09-26
        # BY AN INDEPENDENT REVIEWER, WHICH IS EXACTLY THE check_acronyms DEFECT RECORDED ABOVE:
        # controls that live in a scratch script pass once and then guard nothing. The four
        # below are the load-bearing cases, including the one the ad-hoc run caught (deploy).
        ("REACH-UNSOURCED fires on a capability claim with no source",
         "The Drive connector cannot edit content, so I stopped there.\n", "REACH-UNSOURCED", True),
        ("REACH-UNSOURCED fires on clasp cannot deploy - the verb the first draft missed",
         "clasp push cannot deploy the web app.\n", "REACH-UNSOURCED", True),
        ("REACH-UNSOURCED stays silent when a dated measurement is cited",
         "The connector cannot edit content, measured 2026-08-14 via update_file.\n", "REACH-UNSOURCED", False),
        ("REACH-UNSOURCED stays silent when the tool's own tool set is cited",
         "The connector cannot edit content: its entire tool set is search, read, download.\n", "REACH-UNSOURCED", False),
        # DECLINE-UNQUOTED, 2026-10-23 (F-769).
        ("DECLINE-UNQUOTED fires on the sentence that shipped",
         "You declined the independent reviewer call, and that review is a step in your gate.\n", "DECLINE-UNQUOTED", True),
        ("DECLINE-UNQUOTED fires on a refused claim with no CHECKED quote",
         "You refused the upload, so I stopped.\n", "DECLINE-UNQUOTED", True),
        ("DECLINE-UNQUOTED stays silent when a CHECKED line quotes his message with its time",
         "You declined the upload.\nCHECKED: your 2:24 PM PDT message \"I am not going to upload that file today\" -> declines it.\n", "DECLINE-UNQUOTED", False),
        ("DECLINE-UNQUOTED stays silent when the claim is quoted",
         "The reply said \"You declined the independent reviewer call\" and that was false.\n", "DECLINE-UNQUOTED", False),
        ("DECLINE-UNQUOTED fires on a quote that carries no time",
         "You declined the upload.\nCHECKED: your message \"I am not going to upload that file\" -> declines it.\n", "DECLINE-UNQUOTED", True),
        # HANDOFF-UNTESTED, 2026-10-28. The first control is the sentence that shipped.
        ("HANDOFF-UNTESTED fires on the 2026-10-28 sentence",
         "BLOCKED: that needs a new Mac Claude Code session, which only you can start.\n", "HANDOFF-UNTESTED", True),
        ("HANDOFF-UNTESTED fires on a needs-you-to claim",
         "Verifying this needs you to restart the app.\n", "HANDOFF-UNTESTED", True),
        ("HANDOFF-UNTESTED fires on an I-cannot-reach claim",
         "I cannot reach your Mac from here.\n", "HANDOFF-UNTESTED", True),
        ("HANDOFF-UNTESTED stays silent when the failed call is cited",
         "start_process returned an error: the device did not respond, so only you can start the session.\n", "HANDOFF-UNTESTED", False),
        ("HANDOFF-UNTESTED stays silent when the claim is quoted",
         "The reply said \"which only you can start\" and that was false.\n", "HANDOFF-UNTESTED", False),
        ("HANDOFF-UNTESTED stays silent on a plain result",
         "claude plugin list on the Mac printed Version 0.3.20, Status loaded.\n", "HANDOFF-UNTESTED", False),
        # APPROVAL-UNTESTED, 2026-10-02. The first control is the sentence that shipped.
        ("APPROVAL-UNTESTED fires on the 2026-10-02 sentence",
         "Creating a task in your account needs your approval. If you approve, I create it.\n", "APPROVAL-UNTESTED", True),
        ("APPROVAL-UNTESTED fires on a permission claim with no cited call",
         "Deleting those files requires your permission.\n", "APPROVAL-UNTESTED", True),
        ("APPROVAL-UNTESTED stays silent when the refusal is cited",
         "Creating the task needs your approval: create_trigger returned an approval card and is waiting.\n", "APPROVAL-UNTESTED", False),
        ("APPROVAL-UNTESTED stays silent when the claim is quoted",
         "The reply said \"Creating a task in your account needs your approval\" and that was false.\n", "APPROVAL-UNTESTED", False),
        ("APPROVAL-UNTESTED fires on the you-will-need-to-approve paraphrase",
         "You'll need to approve this before I can create it.\n", "APPROVAL-UNTESTED", True),
        ("APPROVAL-UNTESTED fires on the only-you-can paraphrase",
         "Only you can approve creating a scheduled task.\n", "APPROVAL-UNTESTED", True),
        ("APPROVAL-UNTESTED stays silent on a decision request",
         "Approve, reject or modify rows by number.\n", "APPROVAL-UNTESTED", False),
        # THE 2026-09-11 CASE, BOTH DIRECTIONS. The failing control is the sentence as it actually
        # shipped, twice, an hour after the field carrying that rule had been overwritten.
        ("INSTRUCTION-UNREAD fires on a rule cited with no read",
         "| 4 | AUDIT GATE | Parked by your instruction to park operational work | Claude | later | + a. - b |\n",
         "INSTRUCTION-UNREAD", True),
        ("INSTRUCTION-UNREAD is silent when the field was actually read",
         "CHECKED: the project instructions -> searched the live 25,662-byte field; the park sentence is absent.\n"
         "| 4 | AUDIT GATE | Parked by your instruction to park operational work | Claude | later | + a. - b |\n",
         "INSTRUCTION-UNREAD", False),
        ("FILLER fires on a topic-free sentence", "I'd be happy to help with this.\nThe hash matches.\n", "FILLER", True),
        # COUNT-DRIFT ONLY LOOKS INSIDE A NEXT-STEPS BLOCK, by design -- a count in ordinary
        # prose is not a list claim. My first control had no such block, so the check had
        # nothing to compare against and correctly stayed silent.
        ("COUNT-DRIFT fires when a stated count contradicts the list",
         "Three items follow.\n\n**Next steps**\n\n1. a\n2. b\n3. c\n4. d\n", "COUNT-DRIFT", True),
        ("RATING-BARE fires on a rating with no falsifier", "Confidence 8/10.\n", "RATING-BARE", True),
        ("OI-0735: the field template 'lower if <thing> fails' is not BARE", "Confidence 9/10; lower if ERR-FINDING-2026-11-04.tsv fails to hold the cut line.\n", "RATING-BARE", False),
        ("OI-0735: 'lower' with no 'if' is still BARE", "Confidence 9/10; lower in general.\n", "RATING-BARE", True),
        ("HYPE fires on a banned word", "This is a seamless and powerful result.\n", "HYPE", True),
        # THE CHECK BANS A PILE-UP, NOT A SINGLE DASH -- three or more in one paragraph.
        # My first control used ONE and called the check broken when it stayed silent.
        ("EMDASH fires on a pile-up", "A — B — C — D in one paragraph.\n", "EMDASH", True),
        ("EMDASH does NOT fire on a single dash", "The field moved — and the hash changed.\n", "EMDASH", False),
        ("SENTENCE-LEN fires on a runaway sentence", ("word " * 60).strip() + ".\n", "SENTENCE-LEN", True),
        # RANK CONTRADICTION (P6-05). Four controls, because the check has two independent
        # halves and each can fail silently in the direction that produces no output.
        ("RANK-DEPENDENCY fires when a dependency ranks below its dependent",
         "Body: **P6-01 GATE SUITE** and **P6-09 PRE-SEND**.\n\n**Next steps**\n\n"
         "1. **P6-09 PRE-SEND** — blocked by P6-01\n2. **P6-01 GATE SUITE** — the suite\n",
         "RANK-DEPENDENCY", True),
        # NEGATIVE, AND IT IS THE ONE THAT MATTERS: the CORRECT order must stay silent. A
        # dependency check that fires on a well-ordered list is worse than none, because the
        # list it rejects is the list Rob wants.
        ("RANK-DEPENDENCY stays silent when the dependency ranks above",
         "Body: **P6-01 GATE SUITE** and **P6-09 PRE-SEND**.\n\n**Next steps**\n\n"
         "1. **P6-01 GATE SUITE** — the suite\n2. **P6-09 PRE-SEND** — blocked by P6-01\n",
         "RANK-DEPENDENCY", False),
        # THE REVERSE-SUBJECT FORM. "P9-01 cannot close until this does" names P9-01 as the
        # DEPENDENT, not the dependency. Read the other way round it would fire on every
        # correctly-ordered list that explains why an item is high, which is the commonest
        # note in this project's own plans.
        ("RANK-DEPENDENCY reads an explicit subject as the dependent",
         "Body: **P6-01 GATE SUITE** and **P9-01 FINAL RUN**.\n\n**Next steps**\n\n"
         "1. **P6-01 GATE SUITE** — P9-01 cannot close until this does\n"
         "2. **P9-01 FINAL RUN** — closes it\n", "RANK-DEPENDENCY", False),
        ("RANK-PRIORITY fires when 'can wait' ranks above 'most urgent'",
         "Body text.\n\n**Next steps**\n\n1. **ALPHA ITEM** — can wait\n"
         "2. **BETA ITEM** — most urgent\n", "RANK-PRIORITY", True),
        # NEGATIVE: the code must NOT appear.
        ("clean reply trips nothing", "The field committed at 32,742 bytes.\nThe hash matches.\n", None, False),
        ("a quoted offload phrase is not a hit", 'The rule bans "worth checking on your end" as a phrase.\n', "OFFLOAD", False),
        ("a correct rating with a falsifier is not BARE", "Confidence 8/10. Drops to 4 if the header list is stale.\n", "RATING-BARE", False),
        # *** THE STOP GATE, REWRITTEN 2026-08-26 AFTER THE SIXTH "why did you stop again???". ***
        # _is_open used to require the status cell to START with "open". Real rows carry prose
        # status, so no row counted as open and the check returned before reading the Owner
        # column at all. These four controls pin the new behaviour in both directions.
        ("a prose-status table with no Rob row FAILS (the five-stop shape)",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | READ THE ROWS | 755 remaining, 82 .md next | Claude | Continue | Pro: a. Con: b |\n",
         "STOP-WHILE-UNBLOCKED", True),
        ("a prose-status table WITH a Rob row passes",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | RULE ON SCOPE | Needs Rob to decide and approve | Rob | Option C | Pro: a. Con: b |\n",
         "STOP-WHILE-UNBLOCKED", False),
        ("every row explicitly DONE does not fire",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | READ THE ROWS | DONE - all 755 dispositioned | Claude | none | Pro: a. Con: b |\n",
         "STOP-WHILE-UNBLOCKED", False),
        # *** THE SUMMARY-SPEC THREE-COLUMN SHAPE, added 2026-08-26. ***
        # Before this, a spec-compliant table parsed to ZERO rows and the stop gate returned
        # silently - so obeying Rob's own format ruling would have switched off the check he
        # has asked about six times. Both shapes must work or the format becomes a trap.
        # *** THE ANCHOR CHECK MUST BE EXERCISED HERE OR IT CAN CRASH LIVE WHILE THE
        # SELFTEST REPORTS GREEN - which is exactly what happened on 2026-08-26: the first
        # version referenced an undefined HOME, passed 68 of 68, and raised NameError on the
        # first real draft. A control that never enters a code path cannot see it break. ***
        # CONTROLS FOR FILENAME-UNLINKED, BOTH DIRECTIONS. The failing fixture is the reply
        # that produced "WHERE ARE THE LINKS????" - a statement PDF named as the thing to check.
        ("a bare filename in the next steps FIRES",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n| 1 | THE RULING | Rob |\n\n"
         "**1. THE RULING** - Rob\n\n- Task: check it against 2019 - MN327073884214.1B.pdf and report.\n",
         "LINK-REGISTRY", True),
        ("the same filename WITH a link beside it stays silent",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n| 1 | THE RULING | Rob |\n\n"
         "**1. THE RULING** - Rob\n\n- Task: check it against "
         "[THE 2019 STATEMENT](https://drive.google.com/file/d/1QbN_HbvAD4EhKGkPK0SLYydtmoJuAwja/view) and report.\n",
         "LINK-REGISTRY", False),
        ("a claimed doc edit with NO probe and NO read-back FIRES",
         "CHECKED: the plan -> ok.\n\nI typed the banner into the Google Doc and it landed.\n",
         "PROBE-MISSING", True),
        ("the same claim WITH a selection probe stays silent",
         "CHECKED: the focus probe, eight shift+Right presses -> WHO I AM highlighted.\n\nI typed the banner into the Google Doc.\n",
         "PROBE-MISSING", False),
        ("the same claim WITH a server-side read-back stays silent",
         "CHECKED: the doc, read back through the Drive connector -> all four blocks present.\n\nI typed the banner into the document.\n",
         "PROBE-MISSING", False),
        ("a reply claiming no canvas edit at all is silent",
         "CHECKED: gates -> ALL GREEN.\n\nI edited a TSV on disk with a python script.\n",
         "PROBE-MISSING", False),
        ("a claimed browser action with NO prediction FIRES",
         "CHECKED: a -> b.\n\nI clicked the Save button and it worked.\n",
         "PREDICTION-MISSING", True),
        ("the same claim WITH a stated prediction stays silent",
         "CHECKED: a -> b.\n\nPrediction: the click lands on Save.\n\nI clicked the Save button.\n",
         "PREDICTION-MISSING", False),
        ("'predicted' in past tense also satisfies it, since a miss is still a stated prediction",
         "CHECKED: a -> b.\n\nI predicted it would pass. I clicked the button and it did not.\n",
         "PREDICTION-MISSING", False),
        ("a reply with no UI action at all is silent",
         "CHECKED: gates -> ALL GREEN.\n\nI edited a TSV with a python script.\n",
         "PREDICTION-MISSING", False),
        ("REGRESSION: the PLURAL 'predictions' also satisfies it - a word boundary bug found on real replies, not fixtures",
         "CHECKED: a -> b.\n\nThree predictions today, two missed. I clicked the Save button.\n",
         "PREDICTION-MISSING", False),
        # *** P8-18 CONTROLS, 2026-09-02. THE MEASURED CASE, REPRODUCED. *** The row that
        # passed on 2026-08-26 was NOT open - the artifacts Rob had to open were named in the
        # Recommendation cell of a row whose status said nothing was pending. Keying on OPEN
        # would have left that exact reply passing, so these two controls carry a non-open
        # status deliberately.
        ("P8-18: a NON-OPEN row naming files in another cell still needs a link",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | P2-22 disposition | Completed | Rob | Option C, plus read morning and setup-writing-style | + settles it. - a read |\n",
         "OPEN-ROW-LINK", True),
        ("P8-18: the same non-open row saying NO-ARTIFACT out loud is silent",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | P2-22 disposition | Completed - NO-ARTIFACT, a ruling only Rob can give | Rob | Option C | + settles it. - a read |\n",
         "OPEN-ROW-LINK", False),
        # D-030 CONTROLS, BOTH DIRECTIONS. The failing fixture uses "Me", which in Rob's
        # field means ROB - so the row reads as his while being intended as Claude's.
        ("OWNER-PRONOUN fires on an Owner cell reading Me",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | [THE THING](https://x.test/a) | Open - NO-ARTIFACT | Me | do it | + a. - b |\n",
         "OWNER-PRONOUN", True),
        ("OWNER-PRONOUN is silent when the Owner is a name",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | [THE THING](https://x.test/a) | Open - NO-ARTIFACT | Claude | do it | + a. - b |\n",
         "OWNER-PRONOUN", False),
        ("OPEN-ROW-LINK fires on an open row with no url",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | THE LEDGER PASS | Open | Claude | do it | + a. - b |\n",
         "OPEN-ROW-LINK", True),
        ("REGRESSION: rewording the cell does NOT silence it - the exact move Rob caught",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | THE THING RECORDED EARLIER | Open | Claude | do it | + a. - b |\n",
         "OPEN-ROW-LINK", True),
        ("an open row WITH a url is silent",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | [THE LEDGER PASS](https://x.test/a) | Open | Claude | do it | + a. - b |\n",
         "OPEN-ROW-LINK", False),
        ("an open row declaring NO-ARTIFACT out loud is silent",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | THE PHONE CALL | Open - NO-ARTIFACT | Rob | call them | + a. - b |\n",
         "OPEN-ROW-LINK", False),
        # *** REVERSED 2026-09-02 WHEN P8-18 WIDENED THIS CHECK, AND NOT DELETED. *** This
        # case asserted that a Completed row needs no url. It now fires, and that is the
        # intended consequence: a completed item either produced something Rob can open, in
        # which case the link belongs on the row, or it produced nothing, in which case the
        # row says NO-ARTIFACT. The old assertion is preserved as its inverse rather than
        # removed, because deleting a control to make a change pass is the same move as
        # rewording a cell to silence a gate.
        ("REVERSED: a Completed row with neither a url nor NO-ARTIFACT now fires",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | THE DONE THING | Completed | Claude | none | + a. - b |\n",
         "OPEN-ROW-LINK", True),
        # CONTROLS FOR TABLE-SHAPE, BOTH DIRECTIONS. The FAILING fixture is the exact header
        # Rob screenshotted with "Why do we have this format again??????".
        ("the four-column decision table FIRES",
         "CHECKED: x -> y.\n\n| # | Decision | What it unblocks | My recommendation |\n|---|---|---|---|\n"
         "| 1 | THE RULING | a thing | do it |\n",
         "TABLE-SHAPE", True),
        ("TABLE-SHAPE stays silent on an audit findings table",
         "| # | Finding | Class | Evidence | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | x | false | y | z | a | b |\n",
         "TABLE-SHAPE", False),
        ("TABLE-SHAPE stays silent on an option comparison table",
         "| # | Option | Pros | Cons |\n|---|---|---|---|\n| 1 | A | x | y |\n", "TABLE-SHAPE", False),
        ("TABLE-SHAPE fires on a next-step table in the wrong shape",
         "| # | Next step | Why |\n|---|---|---|\n| 1 | A | x |\n", "TABLE-SHAPE", True),
        ("the seven-column spec header (ruled 2026-10-04) stays silent",
         "CHECKED: x -> y.\n\n| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n"
         "|---|---|---|---|---|---|---|\n| 1 | THE RULING blocks nothing | [Do it](https://example.com) | Rob | do it | a | b |\n",
         "TABLE-SHAPE", False),
        # THE RETIRED SIX-COLUMN HEADER MUST NOW FIRE, as the three-column one below does: Rob ruled
        # the seven-column shape on 2026-10-04, and a gate that still accepted the old one would
        # let a table drift back to it without a word.
        ("the retired six-column header (2026-08-25) now FIRES",
         "CHECKED: x -> y.\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n"
         "|---|---|---|---|---|---|\n| 1 | THE RULING | Open | Rob | do it | Pro: a. Con: b |\n",
         "TABLE-SHAPE", True),
        # THE SUPERSEDED THREE-COLUMN SHAPE MUST ALSO FIRE. It is kept in SUMMARY-SPEC only as
        # the record of the ruling it replaces, under a banner saying implementing it is the
        # mistake. A gate that accepted it would legalise the degraded table.
        ("the superseded three-column shape FIRES",
         "CHECKED: x -> y.\n\n| # | Item | Owner |\n|---|---|---|\n| 1 | THE RULING | Rob |\n",
         "TABLE-SHAPE", True),
        # CONTROLS FOR LABEL-UNDEFINED, BOTH DIRECTIONS. The FAILING fixture is the reply
        # Rob answered with "What is THE VASCULAR SCREEN???" - the label present in the body
        # as its own bold heading and nowhere else. The PASSING fixture is the reply that
        # ended the exchange: the same item, with the question written out in plain words.
        ("a label present in the body only as its own heading FIRES",
         "CHECKED: x -> y.\n\n**THE VASCULAR SCREEN**\n\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n"
         "| 1 | THE VASCULAR SCREEN | Rob |\n",
         "LABEL-UNDEFINED", True),
        ("the same label explained in a sentence stays silent",
         "CHECKED: x -> y.\n\nTHE VASCULAR SCREEN is one question to ask at the appointment: could this "
         "be a circulation problem in her legs rather than a nerve problem in her back, and have her foot "
         "pulses been checked?\n\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n"
         "| 1 | THE VASCULAR SCREEN | Rob |\n",
         "LABEL-UNDEFINED", False),
        # CONTROLS FOR BLOCK-RENDER, BOTH DIRECTIONS. The malformed shape is the one
        # SUMMARY-SPEC specified until 2026-09-01, so the control quotes it verbatim.
        ("the old four-line block with a bare + FIRES",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n| 1 | THE RULING | Rob |\n\n"
         "**1. THE RULING** - Rob\nTask: decide.\nRecommendation: decide now.\n+ fast / - risky\n",
         "BLOCK-RENDER", True),
        ("the corrected bullet block stays silent",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n| 1 | THE RULING | Rob |\n\n"
         "**1. THE RULING** - Rob\n\n- Task: decide.\n- Recommendation: decide now.\n- Pros / Cons: fast / risky\n",
         "BLOCK-RENDER", False),
        # CONTROLS FOR LABEL-NAMED-UNLINKED, BOTH DIRECTIONS. The check is worthless unless it
        # fires on the exact reply that caused it: a next-steps row naming SPOT-CHECK SHEET with
        # no url anywhere, which is what Rob was reading when he asked where the link was.
        ("a registered label named with no link anywhere FIRES",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n"
         "| 1 | SPOT-CHECK SHEET | Rob |\n\n**1. SPOT-CHECK SHEET** - Rob\nTask: go and read it.\n",
         "LINK-REGISTRY", True),
        ("the same label WITH its link stays silent",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n"
         "| 1 | [SPOT-CHECK SHEET](https://drive.google.com/file/d/1RYBZTg7YWumo-C--TCg7lK7xdMils08j/view?usp=drivesdk) | Rob |\n",
         "LINK-REGISTRY", False),
        # THE LIVE CASE, 2026-09-20: a row LINKED to the file was reported as naming it unlinked,
        # because the filename sits inside its own href. Under the old code this control fails.
        ("a label whose filename appears only inside its own link target stays silent",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n"
         "| 1 | [THE 22 BACKUP-LESS SURFACES](computer:///Users/robk/Claude/instructions-backup/verify.sh) | Rob |\n",
         "LINK-REGISTRY", False),
        ("naming that same file in the prose of a row still FIRES",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n"
         "| 1 | THE 22 BACKUP-LESS SURFACES | Rob | Go and read verify.sh yourself. |\n",
         "LINK-REGISTRY", True),
        ("the link-registry anchor path runs without raising",
         "CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n"
         "| 1 | [THE FORMAT RULING](https://drive.google.com/file/d/1N48mzBhbwAlLbiVSBV6lRMG3gzJ5lF50/view) | Rob |\n",
         "LINK-REGISTRY", False),
        # THE TWO GATES HAD DIVERGED ON THIS RULE, 2026-08-26. presend was taught that an
        # explicit no-residual-uncertainty claim satisfies the falsifier requirement at 9+,
        # because REQUIRING one on a fully-measured rating is what manufactured the hollow
        # clause Rob caught. replycheck was not taught it, so one sentence could pass one gate
        # and fail the other - the exact condition crossgate.py exists to detect.
        ("a 10/10 declaring no residual uncertainty is not BARE",
         "CHECKED: a thing -> a result.\nConfidence 10/10. Every claim was measured; there is no residual uncertainty to report.\n",
         "RATING-BARE", False),
        ("the same declaration at 6/10 IS still BARE",
         "CHECKED: a thing -> a result.\nConfidence 6/10. Every claim was measured; there is no residual uncertainty to report.\n",
         "RATING-BARE", True),
        # ---- RATING-CLOSABLE controls, BOTH DIRECTIONS. Added 2026-08-19. ----
        # R154 C: the F-406 reply. "approval" in the window named an entry and a reply format,
        # not a blocker, and it used to switch the check off.
        ("R154: RATING-CLOSABLE fires when 'approval' in the window is not Rob's blocker",
         "CHECKED: x -> y\nOne extra ruling.py call before any approval entry. Confidence 7/10. "
         "What would lower it: same-line citation failing, which I can measure against the 11 cited "
         "entries before building.\nReply with approvals per row.\n", "RATING-CLOSABLE", True),
        ("R154 CONTROL: a check that waits on Rob's approval is still exempt",
         "CHECKED: x -> y\nConfidence 7/10. Drops to 4 if the field edit lands differently; I can "
         "check that in one pass, but it is blocked on your approval of the write.\n",
         "RATING-CLOSABLE", False),
        # THE THREE REAL EXAMPLES THAT PROMPTED THIS, quoted from the session that failed:
        ("RATING-CLOSABLE fires on 'I can check that in one pass and haven't'",
         "CHECKED: x -> y\nConfidence 8/10. Drops to 3 if any of the 25 crcs belongs to a "
         "non-edited file - I can check that in one pass and haven't.\n", "RATING-CLOSABLE", True),
        ("RATING-CLOSABLE fires on 'it takes one pass, and I have the media keys'",
         "CHECKED: x -> y\nConfidence 6/10. Item 2 is the check, it takes one pass, and I "
         "have the media keys.\n", "RATING-CLOSABLE", True),
        ("RATING-CLOSABLE fires on a falsifier naming an unread file",
         "CHECKED: x -> y\nConfidence 7/10. Drops to 4 if FIELD_GUIDE.md says otherwise; I "
         "have not read it in full.\n", "RATING-CLOSABLE", True),
        # NEGATIVE CONTROLS - a falsifier naming a PHYSICAL blocker must NOT fire, or the
        # detector punishes the honest case and trains its reader to ignore it.
        # R272 row 2 controls, both directions, modelled on the F-527 replies.
        ("R272: a finished first-person read beside a rating does NOT fire",
         "CHECKED: x -> y\nI read the watchdog SKILL.md in full. Confidence 6/10, because the task had "
         "to retype the preferences field to hash it, which only Rob can paste exactly.\n", "RATING-CLOSABLE", False),
        ("R272: an APPROVE-N step beside a rating does NOT fire",
         "CHECKED: x -> y\nI have not confirmed the bridge passes it. Confidence 6 of 10.\n"
         "APPROVE-1: install Bun. You then restart the app, which needs a click from you.\n",
         "RATING-CLOSABLE", False),
        ("R272 CONTROL: a pending read beside a rating still fires",
         "CHECKED: x -> y\nConfidence 7/10. I am starting to read the three chats now; reading them "
         "would settle it.\n", "RATING-CLOSABLE", True),
        ("R272 CONTROL: a skipped check named as the raiser still fires",
         "CHECKED: x -> y\nConfidence 7/10 because I have not matched each outcome. Doing that would "
         "raise it; I can check that in one pass.\n", "RATING-CLOSABLE", True),
        ("R272 CONTROL: a spot-check of 4 of 430 still fires",
         "CHECKED: x -> y\nI spot-checked 4 images. Confidence 8/10. A wrong photo on a slide I "
         "did not check would lower it; I have not checked the other 426.\n", "RATING-CLOSABLE", True),
        ("a falsifier naming a credential Rob holds does NOT fire",
         "CHECKED: x -> y\nConfidence 9/10. Drops to 4 if the export lives on an external "
         "drive only Rob can touch.\n", "RATING-CLOSABLE", False),
        ("a falsifier naming a quoted tool error does NOT fire",
         "CHECKED: x -> y\nConfidence 9/10. Drops to 5 if the endpoint stops returning "
         "unauthorized; it returned an error I quoted above.\n", "RATING-CLOSABLE", False),
        ("a falsifier naming an approval only Rob can give does NOT fire",
         "CHECKED: x -> y\nConfidence 8/10. Drops to 3 if Rob's approval changes the scope.\n",
         "RATING-CLOSABLE", False),
        ("RATING-CLOSABLE fires on a falsifier confessing an ASSUMPTION, not an omission",
         "CHECKED: x -> y\nConfidence 8/10. Drops to 4 if Layer B's Tasks means the Tasks "
         "feature - I mapped it by assumption, and that is the one element where I matched "
         "on wording instead of measuring.\n", "RATING-CLOSABLE", True),
        ("RATING-CLOSABLE fires on 'not yet separated'",
         "CHECKED: x -> y\nConfidence 7/10. One thing I have not separated: whether the 403 "
         "is consent or access.\n", "RATING-CLOSABLE", True),
        # ---- R161, ROB 2026-10-02 06:39 PDT, "Approve #3". Both directions for each fix. ----
        ("R161: the NOUN 'the count that' beside a rating does NOT fire (F-426)",
         "CHECKED: x -> y\nThe files were never the problem; the count that made them look like "
         "one was.\nConfidence 8 of 10 that the gates go green.\n", "RATING-CLOSABLE", False),
        ("R161 CONTROL: the VERB 'count the' beside a rating still fires",
         "CHECKED: x -> y\nConfidence 7/10. Drops to 4 if a row is missing - count the rows to "
         "settle that.\n", "RATING-CLOSABLE", True),
        ("R161: a reply QUOTING an earlier flag and its rating does NOT fire (F-428)",
         "CHECKED: x -> y\nThe gate matched the words \"count that\" in an ordinary sentence, "
         "beside the earlier \"Confidence 8\".\n", "RATING-CLOSABLE", False),
        ("R161 CONTROL: contractions are not quotes - 'haven't read' still fires",
         "CHECKED: x -> y\nConfidence 7/10. Drops to 4 if the rule lives elsewhere; I haven't "
         "read the skill files, and it's one grep.\n", "RATING-CLOSABLE", True),
        ("R161 CONTROL: a quotation elsewhere does not hide an unquoted falsifier",
         "CHECKED: x -> y\nThe rule says \"verify before rating\". Confidence 7/10. Drops to 4 if "
         "the log disagrees; I have not read the log.\n", "RATING-CLOSABLE", True),
        ("R161 CONTROL: a quoted blocker still excuses, as before - quoting never ADDS a FAIL",
         "CHECKED: x -> y\nConfidence 9/10 - I read the mode bits directly, and the "
         "\"Permission denied\" text in the output is consistent with it.\n",
         "RATING-CLOSABLE", False),
        ("CONTROL an assumption phrase beside a PHYSICAL blocker still does NOT fire",
         "CHECKED: x -> y\nConfidence 8/10. Drops to 4 if the mapping is wrong, but only Rob "
         "can approve the change and the tool returned an error I quoted.\n",
         "RATING-CLOSABLE", False),
        # *** MEASURED 2026-09-07: CALL-ON-ROB WENT DARK ON A QUALIFIED OWNER CELL. ***
        # The owner matcher demanded the cell be exactly "Rob" or "Claude", so "Rob, at the
        # call" read as unowned and the row sailed through. The second case is the disguise
        # that followed: the same errand relabelled "Claude, until the call", which hands the
        # work to a call while carrying Claude's name.
        ("CALL-ON-ROB fires when the owner cell is Rob QUALIFIED by a call",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | ASK WHETHER HE PRACTISES THERE | Not open as work - NO-ARTIFACT | Rob, at the call | ask it first | + a. - b |\n",
         "CALL-ON-ROB", True),
        ("CALL-ON-ROB fires when a call errand is relabelled Claude, until the call",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | ARCADIA QUESTION | Not open as work - NO-ARTIFACT | Claude, until the call | leave it in the sheet | + a. - b |\n",
         "CALL-ON-ROB", True),
        ("CONTROL a plain Claude row mentioning a booking PAGE is not a call errand",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | CORROBORATE EDUCATION | Open - NO-ARTIFACT | Claude | read the Zocdoc booking profiles | + a. - b |\n",
         "CALL-ON-ROB", False),
        # *** ADDED 2026-09-10 AFTER "WHY AM I SEEING IT AGAIN???" AND "WHY IS #5 ON HERE???" ***
        ("EXERCISE-ON-ROB fires on a stair session in Rob's column",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | LOADED STAIR SESSION - did it happen | Open - NO-ARTIFACT | Rob | say yes or no | + a. - b |\n",
         "EXERCISE-ON-ROB", True),
        ("EXERCISE-ON-ROB fires on downhill preconditioning in Rob's column",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | DOWNHILL PRECONDITIONING #2 | Open - NO-ARTIFACT | Rob | do it tomorrow | + a. - b |\n",
         "EXERCISE-ON-ROB", True),
        ("CONTROL a Claude row that merely mentions the calendar's conditioning events does not fire",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | RE-READ THE CALENDAR | Open - NO-ARTIFACT | Claude | confirm the preconditioning events still exist | + a. - b |\n",
         "EXERCISE-ON-ROB", False),
        ("ARTIFACT-ITEM-ON-ROB fires on a shoe delivery in Rob's column",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | ALTRA LONE PEAK 9+ ARRIVES 15 SEPT | Open - NO-ARTIFACT | Rob | leave it | + a. - b |\n",
         "ARTIFACT-ITEM-ON-ROB", True),
        ("CONTROL a Claude row about the artifact itself does not fire",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | FOLD THE STATE DOC FACTS IN | Open - NO-ARTIFACT | Claude | edit the export row | + a. - b |\n",
         "ARTIFACT-ITEM-ON-ROB", False),
        ("STOP-WHILE-UNBLOCKED stays silent when the only open row is blocked with a quoted error",
         "NEXT STEPS\n\n| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n|---|---|---|---|---|---|\n| 1 | ANTHEM SWEEP | Blocked - the host returned \"timed out after 45000ms\" - NO-ARTIFACT | Claude | retry next session | + a. - b |\n",
         "STOP-WHILE-UNBLOCKED", False),
        # *** THE MEASURED CASE, 2026-09-07: "THREE ADDRESS COUNTS WERE WRONG" followed by FIVE
        # named subjects, shipped twice and once into a project doc. ***
        ("COUNT-DRIFT-PROSE fires on an emphatic count with no inline numbering",
         "CHECKED: a -> b\n\n**THREE ADDRESS COUNTS WERE WRONG.** Desai has three, not two. Gazmarian's four are one building. And Vartanian, Bajaj and Agrawal were second addresses nobody had found.\n",
         "COUNT-DRIFT-PROSE", True),
        ("COUNT-DRIFT-PROSE stays silent when the items are numbered and the count matches",
         "CHECKED: a -> b\n\n**THREE ADDRESS COUNTS WERE WRONG.** (1) Desai has three, not two. (2) Gazmarian's four are one building. (3) Solberg's four are genuinely four.\n",
         "COUNT-DRIFT-PROSE", False),
        ("COUNT-DRIFT-PROSE fires when the numbering stops short of the stated count",
         "CHECKED: a -> b\n\n**FOUR ROWS MOVED.** (1) Desai. (2) Gazmarian. (3) Solberg. And one more nobody numbered.\n",
         "COUNT-DRIFT-PROSE", True),
        ("CONTROL an ordinary prose sentence carrying a number does not fire",
         "CHECKED: a -> b\n\nFour rebuilds today, 33 address records read. Everything else is open.\n",
         "COUNT-DRIFT-PROSE", False),
        ("CONTROL a one-sentence emphatic count enumerates nothing and does not fire",
         "CHECKED: a -> b\n\n**TWENTY-ONE CALLS, NOT FIVE.**\n",
         "COUNT-DRIFT-PROSE", False),
        ("CONTROL a selftest result is not a confidence rating",
         "CHECKED: selftest -> 10/10 controls pass\n",
         "THOROUGH-SIX", False),
        ("CONTROL 7/10 tests passing is not a confidence rating",
         "CHECKED: suite -> 7/10 tests pass\n",
         "RATING-BARE", False),
        ("a real confidence rating is still caught",
         "Some prose about the system.\n\nConfidence 8/10 on the finding.\n",
         "THOROUGH-SIX", True),
        ("CHECKED with an EM DASH counts as a cited line",
         "CHECKED \u2014 the ledger -> 89 rows\n\nThe ledger holds 89 rows.\n",
         "LEDGER-0", False),
        ("CHECKED with a HYPHEN counts as a cited line",
         "CHECKED - the ledger -> 89 rows\n\nThe ledger holds 89 rows.\n",
         "LEDGER-0", False),
        # INLINE EVIDENCE, 2026-09-30. Both directions, plus the hypothetical that must not pass.
        ("inline evidence naming a call and its result counts as a citation",
         "The Drive connector has an update_file tool.\n\nI ran `list_tools` on the connector and it returned update_file.\n",
         "LEDGER-0", False),
        ("a hypothetical call ('would run ... expect') is NOT evidence",
         "The Drive connector has an update_file tool.\n\nI would run `list_tools` on the connector and expect it to return 1 match.\n",
         "LEDGER-0", True),
        ("inline evidence must NAME the call: a bare count does not clear (corpus false-clear 2026-09-30)",
         "The Drive connector has an update_file tool.\n\nOne independent reviewer read this draft and returned 14 findings.\n",
         "LEDGER-0", True),
        ("ABSENCE-CLAIM accepts an inline sentence naming the search and a positive control",
         "The Drive connector cannot reach that folder.\n\nI ran `search_files` on My Drive/AI and it returned 12 folders, including the known-present Yosemite folder as a control, and none named Reunion.\n",
         "ABSENCE-CLAIM", False),
        ("ABSENCE-CLAIM still fires when the inline search names no control",
         "The Drive connector cannot reach that folder.\n\nI ran `search_files` on My Drive/AI and it returned 12 folders, none named Reunion.\n",
         "ABSENCE-CLAIM", True),
        ("inline evidence survives a period inside the code span",
         "The Drive connector has an update_file tool.\n\nI ran `ls -1 *.txt | wc -l` and it returned 10.\n",
         "LEDGER-0", False),
        ("a code span as the subject followed by its result counts as inline evidence",
         "The Drive connector has an update_file tool.\n\n`find . -maxdepth 1 -type f | wc -l` returned 12.\n",
         "LEDGER-0", False),
        ("SCOPE-VS-CLAIM accepts a root named in backticks",
         "There are 12 replies saved in `~/Claude/x/r4`, and there is no file named `p7.txt`.\n",
         "SCOPE-VS-CLAIM", False),
        ("SCOPE-VS-CLAIM still fires when no root is named at all",
         "There is no file named `p7.txt`.\n",
         "SCOPE-VS-CLAIM", True),
        ("a claim with no CHECKED line and no inline evidence still fails",
         "The Drive connector has an update_file tool.\n",
         "LEDGER-0", True),
        # THE NEGATIVE CONTROL FOR THIS IS NOT EXPRESSIBLE HERE, AND SAYING SO BEATS A
        # CONTROL THAT PASSES FOR THE WRONG REASON. A fixture reading "CHECKED the ledger"
        # with a claim under it produced ZERO system claims, so LEDGER-0 had nothing to fire
        # on and the control was measuring CLAIM_RE rather than the separator. The separator
        # itself is verified directly: CHECKED_RE matches colon, em dash, en dash and hyphen,
        # and does NOT match a bare "CHECKED the ledger 89 rows".
        ("next_steps_block finds a table with NO trigger phrase anywhere",
         "Some prose.\n\n| # | Item | Status | Owner | Rec | Pros |\n|---|---|---|---|---|---|\n"
         "| 1 | [X](computer:///nope/NO-SUCH.tsv) | Open | Claude | do | + a - b |\n",
         "LINK-REGISTRY", True),
        ("CONTROL: a reply with no table and no trigger phrase raises no registry failure",
         "Just prose about the weather, with no table and no urls at all.\n",
         "LINK-REGISTRY", False),
        ("LINK-RESOLVES warns when the LABEL names a project script and the href is another",
         "| 1 | [SCOPECHECK](computer:///Users/robk/Claude/Improving-my-Claude/bin/gates.py) | Open | Claude | do it | + x - y |\n",
         "LINK-RESOLVES", True),
        ("CONTROL: label naming the SAME script as the href does not fire",
         "| 1 | [SCOPECHECK](computer:///Users/robk/Claude/Improving-my-Claude/bin/scopecheck.py) | Open | Claude | do it | + x - y |\n",
         "LINK-RESOLVES", False),
        ("CONTROL: a concept label naming no script does not fire - 7 of 7 correct rows once did",
         "| 1 | [PROCESS AUDIT](computer:///Users/robk/Claude/Improving-my-Claude/bin/gates.py) | Open | Claude | do it | + x - y |\n",
         "LINK-RESOLVES", False),
        ("CONTROL: a ratio comparison is not a confidence rating",
         "CHECKED: hypothesis -> 2/9 against 5/10\n\nThe first hypothesis measured 2/9 against 5/10.\n",
         "THOROUGH-SIX", False),
        ("a real rating after a fraction elsewhere is still caught",
         "We read 2/9 rows.\n\nSome prose about the gates and the ledger.\n\nConfidence 8/10 on the finding.\n",
         "THOROUGH-SIX", True),
        # LINK-ESCAPES, both directions, on real paths of this machine. AUDIT-REVIEWS.tsv is a
        # symlink into Drive; bin/gates.py is a real local file.
        ("LINK-ESCAPES fires on a link into a symlink whose target is in Drive",
         "See [THE REVIEWS](computer:///Users/robk/Claude/Improving-my-Claude/AUDIT-REVIEWS.tsv).\n",
         "LINK-ESCAPES", True),
        ("LINK-ESCAPES is silent on a link to a real local file",
         "See [GATES](computer:///Users/robk/Claude/Improving-my-Claude/bin/gates.py).\n",
         "LINK-ESCAPES", False),
        ("LINK-RESOLVES fires when a computer:// target does not exist",
         "| 1 | [THE LEDGER](computer:///Users/robk/Claude/Improving-my-Claude/NO-SUCH-FILE.tsv) | Open | Claude | do it | + x - y |\n",
         "LINK-RESOLVES", True),
        ("LINK-RESOLVES is silent when the target exists and the row names it",
         "| 1 | [SESSION-FAILURES-2026-08-26.tsv](computer:///Users/robk/Claude/Improving-my-Claude/SESSION-FAILURES-2026-08-26.tsv) | Open | Claude | do it | + x - y |\n",
         "LINK-RESOLVES", False),
        ("LINK-RESOLVES warns when the row names one file and links another",
         "| 1 | [P2-22-REVIEW.md](computer:///Users/robk/Claude/Improving-my-Claude/AUDIT-PROTOCOL.md) | Open | Claude | do it | + x - y |\n",
         "LINK-RESOLVES", True),
        ("CONTROL a CAPS concept label with no filename never fires - the spec requires it",
         "| 1 | [PROCESS AUDIT](computer:///Users/robk/Claude/Improving-my-Claude/AUDIT-PROTOCOL.md) | Open | Claude | do it | + x - y |\n",
         "LINK-RESOLVES", False),
        ("LINK-RESOLVES ignores http urls rather than failing open on them",
         "| 1 | [Something](https://drive.google.com/file/d/abc/view) | Open | Claude | do it | + x - y |\n",
         "LINK-RESOLVES", False),
        ("REVIEW-LINK fires on a row naming a file with no url",
         "| 1 | Read SESSION-FAILURES.tsv | Open | Rob | do it | + x - y |\n",
         "REVIEW-LINK", True),
        ("REVIEW-LINK stays silent when the row carries a markdown link",
         "| 1 | [Read the ledger](https://drive.google.com/file/d/abc/view) | Open | Rob | do it | + x - y |\n",
         "REVIEW-LINK", False),
        # ADDED 2026-08-26 AFTER ROB ASKED "Where is the link?" ON A ROW NAMING log-edit.sh.
        # A local-only file has no Drive copy and therefore no http URL, so before this the
        # row could not be made to pass BY ANY MEANS - the correct computer:// citation left
        # REVIEW-LINK failing and only changed the filename in the error. A gate the right
        # answer cannot satisfy pushes the writer toward the wrong one.
        ("REVIEW-LINK accepts a computer:// link for a local-only file",
         "| 1 | [EDIT-LOG timezone](computer:///Users/robk/Claude/instructions-backup/"
         "log-edit.sh) | Open | Rob | name one zone | + x - y |\n",
         "REVIEW-LINK", False),
        ("REVIEW-LINK still fires when the SAME row drops the computer:// link",
         "| 1 | EDIT-LOG timezone in log-edit.sh | Open | Rob | name one zone | + x - y |\n",
         "REVIEW-LINK", True),
        ("CONTROL a physical-act row owes no url",
         "| 1 | Run a Claude Code session in your terminal | Open | Rob | do it | + x - y |\n",
         "REVIEW-LINK", False),
        ("CONTROL a ratify/approve row owes no url",
         "| 1 | Ratify the three complaint classes | Open | Rob | approve | + x - y |\n",
         "REVIEW-LINK", False),
        ("COMMIT-THEN-STOP fires on a closing present-tense commitment",
         "The hash matched.\n\nThat last sentence is itself a check I can run, so I'm running "
         "it rather than leaving it as a caveat.\n", "COMMIT-THEN-STOP", True),
        ("COMMIT-THEN-STOP stays silent when the commitment is MID-reply",
         "So I'm running it now.\n" + ("Then the result came back clean and the hash matched "
         "and the control passed. " * 20) + "\nDone.\n", "COMMIT-THEN-STOP", False),
        ("CONTROL a plain past-tense report does not fire",
         "I ran it and the hash was unchanged.\n", "COMMIT-THEN-STOP", False),
        ("LINK-REUSE warns when one url serves 3 rows",
         "| 1 | [A](https://x.com/d) | Open | Rob |\n| 2 | [B](https://x.com/d) | Open | Rob |\n"
         "| 3 | [C](https://x.com/d) | Open | Rob |\n", "LINK-REUSE", True),
        ("CONTROL two rows sharing a url is not enough to warn",
         "| 1 | [A](https://x.com/d) | Open | Rob |\n| 2 | [B](https://x.com/d) | Open | Rob |\n",
         "LINK-REUSE", False),
        ("a rating with NO falsifier at all is BARE, not CLOSABLE",
         "CHECKED: x -> y\nConfidence 8/10.\n", "RATING-CLOSABLE", False),
    ]
    p = f = 0
    # R155: THOROUGH-SIX is retired, so its 42 tuple cases would assert a fail that can no
    # longer fire. They are dropped here and replaced by the two controls below, the R075 pattern.
    _t6 = [c for c in cases if c[2] == "THOROUGH-SIX"]
    cases = [c for c in cases if c[2] != "THOROUGH-SIX"]
    _pos = [c for c in _t6 if c[3]]
    _ok = bool(_pos) and all("THOROUGH-SIX" not in run(c[1], ALL) for c in _pos)
    print(("  ok    " if _ok else "  BAD   ") + "R155: THOROUGH-SIX is retired - none of its %d former positive fixtures fires" % len(_pos))
    p, f = (p + 1, f) if _ok else (p, f + 1)
    _rc = run("Some prose.\n\nConfidence 8/10. Drops to 3 if any of the 25 crcs belongs to a "
              "non-edited file - I can check that in one pass and haven't.\n", ALL)
    _ok = "RATING-CLOSABLE" in _rc and "THOROUGH-SIX" not in _rc
    print(("  ok    " if _ok else "  BAD   ") + "R155 CONTROL: RATING-CLOSABLE still fires on a closable rating with no THOROUGH line")
    p, f = (p + 1, f) if _ok else (p, f + 1)
    import os as _os_kc
    # 0.4.9 (OI-0798, 2026-11-25 2:44 PM PST): these cases read files that exist only in Rob's home folder on his Mac
    # (~/Claude/Improving-my-Claude, its link registry, ~/.claude/skills). In a cloud container 13 of them failed on
    # serial 9 and 10 alike, so the selftest could not tell a regression from a missing folder. Without that folder they
    # print SKIP and count as neither pass nor fail; on the Mac they run as before.
    _MACHINE_CASES = set(['CONTROL a CAPS concept label with no filename never fires - the spec requires it', 'CONTROL a skill that DOES exist on disk does not fire', 'CONTROL: a concept label naming no script does not fire - 7 of 7 correct rows once did', 'CONTROL: label naming the SAME script as the href does not fire', 'GATE-RATIO stays silent when every recommendation names a real gate', 'LINK-ESCAPES fires on a link into a symlink whose target is in Drive', 'LINK-RESOLVES is silent when the target exists and the row names it', 'LINK-RESOLVES warns when the LABEL names a project script and the href is another', 'SKILL-CLAIM fires on a skill asserted live that has no directory', 'a label whose filename appears only inside its own link target stays silent', 'a registered label named with no link anywhere FIRES', 'naming that same file in the prose of a row still FIRES', 'the link-registry anchor path runs without raising', 'the same filename WITH a link beside it stays silent', 'the same label WITH its link stays silent'])
    _have_home = _os_kc.path.isdir(_os_kc.path.expanduser("~/Claude/Improving-my-Claude"))
    _skipped = 0
    for name, text, code, want in cases:
        if name in _MACHINE_CASES and not _have_home:
            print("  SKIP  " + name + " (needs ~/Claude/Improving-my-Claude)")
            _skipped += 1
            continue
        if code == "STANDING-ROWS":
            _os_kc.environ["REPLYCHECK_KAP_PROJECT"] = "1"  # 0.3.17: the check only runs in the Kaprelian doctors project
        codes = run(text, ALL)
        _os_kc.environ.pop("REPLYCHECK_KAP_PROJECT", None)
        ok = (code in codes) if want else ((code not in codes) if code else (not codes))
        print(("  ok    " if ok else "  BAD   ") + name)
        p, f = (p + 1, f) if ok else (p, f + 1)
    # 0.3.17 REGRESSION (Rob 2026-10-26): STANDING-ROWS is scoped to the Kaprelian doctors project.
    _ns_ok = ("| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
              "| 1 | Rob must pick one thing, and this row gives at least sixty characters of context. | Decide | Rob | Approve | Fast | "
              "Con:&nbsp;a&nbsp;small&nbsp;cost<br>\u2022 Risk: x.<br>\u2022 Mitigation: y. |\n")
    _ns_bad = "| # | Issue / Risk | Action | Owner |\n| 1 | DO Y | Open | Claude |\n"
    _os_kc.environ.pop("REPLYCHECK_KAP_PROJECT", None)
    for _n, _t, _kap, _want in (
            ("0.3.17 CONTROL a non-Kaprelian 7-column table owes no standing rows", _ns_ok, None, False),
            ("0.3.17 CONTROL a non-Kaprelian table with REPLYCHECK_KAP_PROJECT=0 owes no standing rows", _ns_ok, "0", False),
            ("0.3.17 MUTATION the same table FAILS STANDING-ROWS in the Kaprelian project", _ns_ok, "1", True),
            ("0.3.17 MUTATION a malformed table outside Kaprelian still FAILS CON-FORMAT", _ns_ok.replace("Con:&nbsp;a&nbsp;small&nbsp;cost<br>\u2022 Risk: x.<br>\u2022 Mitigation: y.", "slow"), None, "CON-FORMAT")):
        if _kap is not None:
            _os_kc.environ["REPLYCHECK_KAP_PROJECT"] = _kap
        _codes = run(_t, ALL)
        _os_kc.environ.pop("REPLYCHECK_KAP_PROJECT", None)
        if _want == "CON-FORMAT":
            ok = "CON-FORMAT" in _codes and "STANDING-ROWS" not in _codes
        else:
            ok = ("STANDING-ROWS" in _codes) == _want
        print(("  ok    " if ok else "  BAD   ") + _n)
        p, f = (p + 1, f) if ok else (p, f + 1)
    # *** THE EMPTY-INPUT CONTROL WAS WRITTEN AS `if True` AND `p + 1`. ***
    # A hardcoded pass, added HOURS AFTER documenting that exact defect elsewhere in this
    # project. It printed ok without executing anything. Replaced with a real subprocess
    # run of this file, which is the only way to exercise the exit path it claims to test.
    # ---------- R075 (ROB 2026-09-20, OPTION C): WHAT THIS FILE STILL OWNS ----------
    # The repair test moved to replygate --stamp; its controls went with it. What stays here is
    # the deletion: an all-Claude open table is no longer a failure. THE FOUR CONTROLS BELOW
    # WERE TUPLE CASES UNTIL TODAY and each tested a PARSING property - an empty status cell
    # counts as open, the 3-column summary shape parses, a "Blocked" cell quoting nothing is
    # not a real blocker - by asserting that the retired fail fired. With the fail gone they
    # would have stayed green while testing nothing, which is how a suite fills with controls
    # that cannot discriminate. They now assert the property DIRECTLY, on the functions that
    # hold it, which is a better anchor than the text check ever was.
    def _prop(name, cond):
        nonlocal p, f
        print(("  ok    " if cond else "  BAD   ") + name)
        p, f = (p + 1, f) if cond else (p, f + 1)

    _prop("RE-POINTED an EMPTY status cell counts as OPEN", _is_open("") is True)
    _prop("CONTROL a Completed cell does not", _is_open("Completed") is False)
    _prop("RE-POINTED a Blocked cell QUOTING NOTHING still counts as open - a bare 'Blocked' "
          "is not a blocker", _is_open("Blocked - NO-ARTIFACT") is True)
    _prop("CONTROL a Blocked cell that QUOTES the blocker does not",
          _is_open('Blocked - waiting on Rob: "approve the ruling"') is False)
    _spec3 = _table_rows("CHECKED: x -> y.\nNEXT STEPS\n\n| # | Item | Owner |\n|---|---|---|\n"
                         "| 1 | THE READ | Claude |\n\n**1. THE READ** - Claude\n"
                         "Status: Open - blocks P9-03.\n")
    _prop("RE-POINTED the SPEC 3-column summary shape parses as one row", len(_spec3) == 1)
    _prop("CONTROL and that row is read as OPEN and owned by Claude",
          bool(_spec3) and _is_open(_spec3[0][2]) and not _is_rob(_spec3[0][3]))
    _prop("CONTROL an all-Claude open table no longer fails STOP-WHILE-UNBLOCKED",
          "STOP-WHILE-UNBLOCKED" not in run(
              "| # | Item | Status | Owner | Claude's Recommendation | Pros / Cons |\n"
              "|---|---|---|---|---|---|\n| 1 | A THING - NO-ARTIFACT | Open | Claude | "
              "Do it. Test: plancheck exits 0. Fails if: it exits 1. | Pro: a. Con: b. |\n",
              ALL))

    # ---------- R114 (ROB 2026-09-29): AN ACKNOWLEDGED MISMATCH, BOTH DIRECTIONS ----------
    # Synthetic ack file and INTAKE, swapped in for the run and restored after, so the controls
    # do not rot when the live files change.
    global _SENT_ACK, _INTAKE_MD
    import tempfile
    _saved = (_SENT_ACK, _INTAKE_MD)
    _td = pathlib.Path(tempfile.mkdtemp())
    (_td / "ack.tsv").write_text("aaaaaaaaaaaaaaaa\tF-901\tR114\ttest reason\n"
                                 "bbbbbbbbbbbbbbbb\tF-902\tR114\t\n", encoding="utf-8")
    (_td / "intake.md").write_text("F-901. a recorded mismatch.\nF-902. another.\n", encoding="utf-8")
    _SENT_ACK, _INTAKE_MD = _td / "ack.tsv", _td / "intake.md"
    _th = "THOROUGH: criterion - x.\n\n"
    try:
        _prop("R114 an acknowledged mismatch cited by sha AND F-number does not FAIL SENT-CHECKED",
              "SENT-CHECKED" not in run(_th + "SENTCHECK: 1 stamped, 0 match, 1 MISMATCH - aaaaaaaaaaaaaaaa, F-901.\n", ALL))
        _prop("R114 CONTROL citing the sha without the F-number still FAILS",
              "SENT-CHECKED" in run(_th + "SENTCHECK: 1 stamped, 0 match, 1 MISMATCH - aaaaaaaaaaaaaaaa.\n", ALL))
        _prop("R114 CONTROL an ack row with no reason is ignored, so citing it still FAILS",
              "SENT-CHECKED" in run(_th + "SENTCHECK: 1 stamped, 0 match, 1 MISMATCH - bbbbbbbbbbbbbbbb, F-902.\n", ALL))
        _prop("R114 CONTROL two mismatches with one acknowledged still FAIL",
              "SENT-CHECKED" in run(_th + "SENTCHECK: 2 stamped, 0 match, 2 MISMATCH - aaaaaaaaaaaaaaaa, F-901.\n", ALL))
        _prop("R114 CONTROL a stamp that is not in the ack file still FAILS",
              "SENT-CHECKED" in run(_th + "SENTCHECK: 1 stamped, 0 match, 1 MISMATCH - cccccccccccccccc, F-901.\n", ALL))
    finally:
        _SENT_ACK, _INTAKE_MD = _saved

    # ---------- R120e (ROB 2026-10-06, N-013): THE REVIEW RECORD IS BOUND TO ITS OWN DRAFT ----------
    # Real draft files in a temp dir, REPLYCHECK_DRAFT set for these calls only and cleared after,
    # so the text-only fixtures above keep running off the stamp path.
    _rd = pathlib.Path(tempfile.mkdtemp())
    _rtxt = "THOROUGH: sourcing - x.\nPRE-SEND REVIEW: independent reviewer returned 1 findings, fixed.\n"
    def _rec(name, extra="", sha=None):
        return ("DRAFT: %s\nDRAFT-SHA256: %s\n%sFINDINGS: 1\n1. HIGH - the draft overstates a count; measured value "
                "differs from the stated one and the sentence was corrected before sending.\n"
                "VERIFIED:\n- every number in the draft was re-derived from its source file\n"
                "- every link was opened and resolves to the page its label names\n"
                "- every owner cell names a person and every row has a test and a failure "
                "condition, checked row by row against the table in the draft text\n"
                % (name, sha or _rsha, extra))
    for _n in ("a.md", "b.md", "c.md", "d.md", "e.md", "f.md", "g.md", "h.md"):
        (_rd / _n).write_text(_rtxt, encoding="utf-8")
    _rsha = review_draft_sha(str(_rd / "a.md"))
    # R239 fixtures: f has no DRAFT-SHA256 line, g names a wrong sha, h was edited after review and keeps
    # the reviewed bytes as h.md.reviewed.
    (_rd / "f.md.review").write_text(_rec("f.md").replace("DRAFT-SHA256: %s\n" % _rsha, ""), encoding="utf-8")
    (_rd / "g.md.review").write_text(_rec("g.md", sha="0" * 64), encoding="utf-8")
    (_rd / "h.md.reviewed").write_text("THOROUGH: sourcing - the reviewed version.\n", encoding="utf-8")
    (_rd / "h.md.review").write_text(_rec("h.md", sha=_file_sha(str(_rd / "h.md.reviewed"))), encoding="utf-8")
    (_rd / "a.md.review").write_text(_rec("a.md"), encoding="utf-8")
    (_rd / "b.md.review").write_text(_rec("b.md").split("\n", 1)[1], encoding="utf-8")
    (_rd / "c.md.review").write_text(_rec("a.md", "note: c\n"), encoding="utf-8")
    (_rd / "d.md.review").write_text(_rec("d.md"), encoding="utf-8")
    (_rd / "spare.review").write_text(_rec("d.md"), encoding="utf-8")
    (_rd / "e.md.review").write_text(_rec("e.md"), encoding="utf-8")
    def _psr(n):
        _os_st.environ["REPLYCHECK_DRAFT"] = str(_rd / n)
        try:
            return "PRE-SEND-REVIEW" in run(_rtxt, [check_presend_review])
        finally:
            _os_st.environ.pop("REPLYCHECK_DRAFT", None)
    _prop("R120e CONTROL a record whose DRAFT line names its own draft passes", not _psr("a.md"))
    _prop("R120e a record with no DRAFT line FAILS", _psr("b.md"))
    _prop("R120e a record whose DRAFT line names another draft FAILS", _psr("c.md"))
    _prop("R120e a record byte-identical to another *.review in the directory FAILS", _psr("d.md"))
    _prop("R120e CONTROL a correct record beside differing records passes", not _psr("e.md"))
    _prop("R239 NEGATIVE a record with no DRAFT-SHA256 line FAILS", _psr("f.md"))
    _prop("R239 NEGATIVE a record naming a sha256 that is not this draft's FAILS", _psr("g.md"))
    _prop("R239 CONTROL a record naming the sha256 of the kept <draft>.reviewed copy passes", not _psr("h.md"))
    _prop("R239 CONTROL the PRE-SEND REVIEW and REPLYGATE lines do not change the draft sha",
          review_draft_sha(str(_rd / "a.md")) == review_draft_sha_text("THOROUGH: sourcing - x.\n"))
    _prop("R120e CONTROL REPLYCHECK_DRAFT is cleared after the controls",
          "REPLYCHECK_DRAFT" not in _os_st.environ)

    # ---------- 0.2.11 PROJECT OBJECTIVES AND HANDOFFS (Rob 2026-10-15 12:21 PDT), BOTH DIRECTIONS ----------
    _pt = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
    _pr = lambda n: "| %d | A | B | Rob | C. | D. | Con:one&nbsp;extra&nbsp;step&nbsp;before&nbsp;it&nbsp;works<br>\u2022 Risk: r.<br>\u2022 Mitigation: m. |\n" % n
    _pgood = ("PROJECT OBJECTIVE 1 - Loop [IN PROGRESS]\nPROJECT OBJECTIVE 2 - Audit [DONE 2026-08-16 9:00 AM]\n\n"
              "OBJECTIVE 1 - Fix text [DONE 2026-10-08 9:00 AM]\n\nOBJECTIVE 2 - Gate [IN PROGRESS]\n\n" + _pt + _pr(1) +
              "\nHANDOFFS - project objective 3 goes to another session\n\n" + _pt + _pr(2))
    _pnoproj = "OBJECTIVE 1 - Gate [IN PROGRESS]\n\n" + _pt + _pr(1)
    _plate = "OBJECTIVE 1 - Gate [IN PROGRESS]\n\nPROJECT OBJECTIVE 1 - Loop [IN PROGRESS]\n\n" + _pt + _pr(1)
    _pbadfmt = "PROJECT OBJECTIVE 1 - Loop [ongoing]\nPROJECT OBJECTIVE 2 - Audit [IN PROGRESS]\n\nOBJECTIVE 1 - Gate [IN PROGRESS]\n\n" + _pt + _pr(1)
    _pdup = ("PROJECT OBJECTIVE 1 - Loop [IN PROGRESS]\n\nOBJECTIVE 1 - Gate [IN PROGRESS]\n\n" + _pt + _pr(1) +
             "\nHANDOFFS\n\n" + _pt + _pr(1))
    _pdone = ("PROJECT OBJECTIVE 1 - Loop [IN PROGRESS]\n\nOBJECTIVE 1 - Gate [DONE 2026-10-15 9:00 AM]\n\n"
              "HANDOFFS - one item leaves this session\n\n" + _pt + _pr(1))
    _os_st.environ["REPLYCHECK_PROJECT"] = "1"
    try:
        _prop("0.2.11 CONTROL a project reply with PROJECT OBJECTIVE lines and a HANDOFFS table passes OBJECTIVE-SECTIONS",
              "OBJECTIVE-SECTIONS" not in run(_pgood, ALL))
        _prop("0.2.11 CONTROL a HANDOFFS table after a DONE objective is not open work under that objective",
              "OBJECTIVE-SECTIONS" not in run(_pdone, ALL))
        _prop("0.2.11 MUTATION a project reply with no PROJECT OBJECTIVE line FAILS", "OBJECTIVE-SECTIONS" in run(_pnoproj, ALL))
        _prop("0.2.11 MUTATION PROJECT OBJECTIVE lines after the first OBJECTIVE line FAIL", "OBJECTIVE-SECTIONS" in run(_plate, ALL))
        _prop("0.2.11 MUTATION a PROJECT OBJECTIVE line with a made-up status FAILS", "OBJECTIVE-SECTIONS" in run(_pbadfmt, ALL))
        _prop("0.2.11 MUTATION a HANDOFFS table that reuses row 1 FAILS", "OBJECTIVE-SECTIONS" in run(_pdup, ALL))
    finally:
        _os_st.environ.pop("REPLYCHECK_PROJECT", None)
    _prop("0.2.11 CONTROL outside a project no PROJECT OBJECTIVE line is required", "OBJECTIVE-SECTIONS" not in run(_pnoproj, ALL))
    _prop("0.2.11 CONTROL REPLYCHECK_PROJECT is cleared after the controls", "REPLYCHECK_PROJECT" not in _os_st.environ)

    # ---------- EVERY-REPLY-TABLE (0.2.31, next-steps row 46): opt-in by REPLYCHECK_EVERY_TABLE=1 ----------
    _et_with = "Done.\n\n| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
    _et_without = "Done. The check printed CLEAN."
    _prop("0.2.31 CONTROL EVERY-REPLY-TABLE is off unless REPLYCHECK_EVERY_TABLE=1", "EVERY-REPLY-TABLE" not in run(_et_without, [check_every_reply_table]))
    _os_st.environ["REPLYCHECK_EVERY_TABLE"] = "1"
    try:
        _prop("0.2.31 MUTATION a reply with no table FAILS EVERY-REPLY-TABLE when opted in", "EVERY-REPLY-TABLE" in run(_et_without, [check_every_reply_table]))
        _prop("0.2.31 CONTROL a reply with the table header passes EVERY-REPLY-TABLE", "EVERY-REPLY-TABLE" not in run(_et_with, [check_every_reply_table]))
    finally:
        _os_st.environ.pop("REPLYCHECK_EVERY_TABLE", None)
    _prop("0.2.31 CONTROL REPLYCHECK_EVERY_TABLE is cleared after the controls", "REPLYCHECK_EVERY_TABLE" not in _os_st.environ)
    _done_ok = "Done.\n\nALL OBJECTIVES DONE: pluginparity.py exit 0 at 8:10 AM PST, 12 of 12 rows TESTED, register rows all closed.\n"
    _done_open = _done_ok + "BLOCKED: row 3 waits on Rob.\n"
    _done_short = "Done.\n\nALL OBJECTIVES DONE: yes.\n"
    _os_st.environ["REPLYCHECK_EVERY_TABLE"] = "1"
    try:
        _prop("0.3.36 CONTROL ALL OBJECTIVES DONE line with evidence and no open item passes EVERY-REPLY-TABLE", "EVERY-REPLY-TABLE" not in run(_done_ok, [check_every_reply_table]))
        _prop("0.3.36 MUTATION the DONE line plus a BLOCKED: line FAILS EVERY-REPLY-TABLE", "EVERY-REPLY-TABLE" in run(_done_open, [check_every_reply_table]))
        _prop("0.3.36 MUTATION a DONE line under 40 characters of evidence FAILS EVERY-REPLY-TABLE", "EVERY-REPLY-TABLE" in run(_done_short, [check_every_reply_table]))
        _prop("0.3.36 MUTATION a DONE line with UNTESTED in the reply FAILS EVERY-REPLY-TABLE", "EVERY-REPLY-TABLE" in run(_done_ok + "Row 2 is UNTESTED.\n", [check_every_reply_table]))
        _hdr38 = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
        _ok38 = _hdr38 + "| 1 | A. BLOCKS: row 2. | B | Rob | C | D | E |\n| 2 | F. BLOCKS: none. | G | Claude | H | I | J |\n"
        _no38 = _hdr38 + "| 1 | A. | B | Rob | C | D | E |\n| 2 | F. | G | Claude | H | I | J |\n"
        _inv38 = _hdr38 + "| 1 | A. BLOCKS: none. | B | Rob | C | D | E |\n| 2 | F. BLOCKS: row 1. | G | Claude | H | I | J |\n"
        _prop("0.3.38 CONTROL rows that state BLOCKS in blocker-first order pass RANK-STRUCT", not _rs_check(_ok38))
        _prop("0.3.38 MUTATION rows with no BLOCKS statement FAIL RANK-STRUCT", bool(_rs_check(_no38)))
        _prop("0.3.38 MUTATION a blocker ranked below the row it blocks FAILS RANK-STRUCT", bool(_rs_check(_inv38)))
        os.environ["REPLYCHECK_DONE_ENFORCE"] = "1"
        _prop("0.3.37 MUTATION 'I fixed it.' with no call FAILS DONE-NO-CALL", "DONE-NO-CALL" in run("I fixed it.\n", [check_done_claim]))
        _prop("0.3.37 MUTATION 'The row is saved.' with no call FAILS DONE-NO-CALL", "DONE-NO-CALL" in run("The reading is done.\n", [check_done_claim]))
        _prop("0.3.37 CONTROL a call and its result in the sentence passes DONE-NO-CALL", "DONE-NO-CALL" not in run("I ran `grep -c x f.md`, which returned 3, and fixed the line.\n", [check_done_claim]))
        _prop("0.3.37 CONTROL a negation passes DONE-NO-CALL", "DONE-NO-CALL" not in run("I did not fix it and I fixed no root cause.\n", [check_done_claim]))
        _prop("0.3.37 CONTROL an objective status line passes DONE-NO-CALL", "DONE-NO-CALL" not in run("PROJECT OBJECTIVE 2 - Workstream 1 [DONE 2026-10-01]\n", [check_done_claim]))
        _prop("0.3.37 CONTROL a CHECKED line sharing two words clears the claim", "DONE-NO-CALL" not in run("The backup file is saved.\nCHECKED: re-read backup file at 8:00 PM PST -> saved text present.\n", [check_done_claim]))
        os.environ.pop("REPLYCHECK_DONE_ENFORCE", None)
        run("I fixed it.\n", [check_done_claim])
        _prop("0.3.42 CONTROL from 2026-11-05 10:00 AM PST DONE-NO-CALL refuses (FAIL, no WARN)", datetime.datetime.now() < datetime.datetime(2026, 11, 5, 10, 0) or (("DONE-NO-CALL" in {c for c, _ in FAILS}) and ("DONE-NO-CALL" not in {c for c, _ in WARNS})))
    finally:
        _os_st.environ.pop("REPLYCHECK_EVERY_TABLE", None)

    # ---------- RANK-STRUCT (0.3.0): ordering by blocking relationships, read from the table itself ----------
    _rsH = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
    def _rsT(*rs): return _rsH + "".join("| %d | %s | a | Claude | r | p | c |\n" % (n, i) for n, i in rs)
    _prop("0.3.0 CONTROL RANK-STRUCT passes when A (row 1) blocks C (row 3)", "RANK-STRUCT" not in run(_rsT((1,"A. BLOCKS: row 3."),(2,"B. BLOCKS: none."),(3,"C. Waits on row 1.")), [check_rank_struct]))
    _prop("0.3.0 MUTATION RANK-STRUCT fires when the blocker ranks below what it blocks", "RANK-STRUCT" in run(_rsT((1,"C. Waits on row 3."),(2,"B. BLOCKS: none."),(3,"A. BLOCKS: row 1.")), [check_rank_struct]))
    _prop("0.3.0 MUTATION RANK-STRUCT fires on 'blocked by' with no row number", "RANK-STRUCT" in run(_rsT((1,"A. Blocked by the upload."),(2,"B. BLOCKS: none.")), [check_rank_struct]))
    _prop("0.3.0 MUTATION RANK-STRUCT fires on a blocking cycle", "RANK-STRUCT" in run(_rsT((1,"A. BLOCKS: row 2."),(2,"B. BLOCKS: row 1.")), [check_rank_struct]))
    _prop("0.3.0 MUTATION RANK-STRUCT fires on an edge to a missing row", "RANK-STRUCT" in run(_rsT((1,"A. BLOCKS: row 9.")), [check_rank_struct]))
    _prop("0.3.0 MUTATION RANK-STRUCT fires when every row says BLOCKS: none but the text names a dependency", "RANK-STRUCT" in run(_rsT((1,"A. BLOCKS: none. Waits on the upload."),(2,"B. BLOCKS: none.")), [check_rank_struct]))
    _prop("0.3.0 CONTROL RANK-STRUCT is silent on a reply with no table", "RANK-STRUCT" not in run("Prose only.", [check_rank_struct]))

    # ---------- TABLE-LAST (ROB APPROVED 2026-10-14 09:41 PDT): REVIEW-FIX-APPLIED, BOTH DIRECTIONS ----------
    # Real draft files with a kept <draft>.reviewed copy, REPLYCHECK_DRAFT set per call and cleared after.
    _fd = pathlib.Path(tempfile.mkdtemp())
    _fh = "| # | Issue / Risk | Action | Owner | Claude's Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
    _frow1 = "| 1 | Zip built | Upload it | Rob | Upload 0.2.4. | Gate live. | One step. |\n"
    _frow2_old = "| 2 | Pin stale | Re-pin | Claude | Re-pin after upload. | Preflight green. | Waits on row 1. |\n"
    _frow2_new = "| 2 | Pin stale, blocks preflight | Re-pin | Claude | Re-pin after upload. | Preflight green. | Waits on row 1. |\n"
    def _fix(psr, rows, reviewed=True, name=None):
        name = name or ("d%d.md" % len(list(_fd.iterdir())))
        (_fd / name).write_text("Summary.\n" + psr + "\n\n" + _fh + rows, encoding="utf-8")
        if reviewed:
            (_fd / (name + ".reviewed")).write_text("Summary.\n\n" + _fh + _frow1 + _frow2_old, encoding="utf-8")
        _os_st.environ["REPLYCHECK_DRAFT"] = str(_fd / name)
        try:
            return "REVIEW-FIX-APPLIED" in run((_fd / name).read_text(encoding="utf-8"), [check_review_fix_applied])
        finally:
            _os_st.environ.pop("REPLYCHECK_DRAFT", None)
    _P2 = "PRE-SEND REVIEW: independent reviewer returned 2 findings - 1 fixed, 1 disputed because it was measured; "
    _prop("TABLE-LAST REVIEW-FIX-APPLIED CONTROL a named fixed row that changed passes",
          not _fix(_P2 + "fixed rows 2.", _frow1 + _frow2_new))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED a named fixed row identical to the .reviewed copy FAILS",
          _fix(_P2 + "fixed rows 2.", _frow1 + _frow2_old))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED a named fixed row missing from the draft's table FAILS",
          _fix(_P2 + "fixed rows 3.", _frow1 + _frow2_new))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED a line with no 'fixed rows' and no 'fixed: none' FAILS",
          _fix(_P2.rstrip("; ") + ".", _frow1 + _frow2_new))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED counts that do not sum to the finding count FAIL",
          _fix("PRE-SEND REVIEW: independent reviewer returned 3 findings - 1 fixed, 1 disputed; fixed rows 2.",
               _frow1 + _frow2_new))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED CONTROL 'partly disputed' and 'cut' count toward the sum",
          not _fix("PRE-SEND REVIEW: independent reviewer returned 4 findings - 1 fixed, 1 disputed, "
                   "1 partly disputed, 1 cut; fixed rows 2.", _frow1 + _frow2_new))
    # DOUBLE-COUNT, coordinator 2026-10-14: a triage line with "partly disputed" and "cut" summed 14 to 16.
    _prop("TABLE-LAST REVIEW-FIX-APPLIED CONTROL 'N fixed, N disputed, N partly disputed, N cut' sums each once",
          not _fix("PRE-SEND REVIEW: independent reviewer returned 14 findings - 9 fixed, 2 disputed, "
                   "2 partly disputed, 1 cut; fixed rows 2; the 2 partly disputed were half right; "
                   "row 2 cut to one line; 1 cut because it repeated row 1.", _frow1 + _frow2_new))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED CONTROL a row number before a label ('row 4 cut') is not a count",
          not _fix("PRE-SEND REVIEW: independent reviewer returned 2 findings - 1 fixed, 1 cut; fixed rows 2; "
                   "row 4 cut to one line.", _frow1 + _frow2_new))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED NEGATIVE once-per-label counts that still do not sum FAIL",
          _fix("PRE-SEND REVIEW: independent reviewer returned 15 findings - 9 fixed, 2 disputed, "
               "2 partly disputed, 1 cut; fixed rows 2.", _frow1 + _frow2_new))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED CONTROL 'fixed: none' with every finding disputed passes on an unchanged table",
          not _fix("PRE-SEND REVIEW: independent reviewer returned 1 findings - 1 disputed because the count was "
                   "re-measured; fixed: none.", _frow1 + _frow2_old))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED 'fixed: none' beside a fixed count FAILS",
          _fix("PRE-SEND REVIEW: independent reviewer returned 1 findings - 1 fixed; fixed: none.", _frow1 + _frow2_old))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED fixes claimed with no <draft>.reviewed copy FAIL",
          _fix(_P2 + "fixed rows 2.", _frow1 + _frow2_new, reviewed=False))
    _prop("TABLE-LAST REVIEW-FIX-APPLIED CONTROL 'fixed: none' with no <draft>.reviewed copy passes",
          not _fix("PRE-SEND REVIEW: independent reviewer returned 1 findings - 1 disputed because the count was "
                   "re-measured; fixed: none.", _frow1 + _frow2_old, reviewed=False))
    # OI-0256 (2026-10-20): tableless task reports. Real draft files, no next-steps table anywhere.
    def _fixt(psr, reviewed=True, same=False, table=False):
        name = "t%d.md" % len(list(_fd.iterdir()))
        _body = "Report text.\n" + psr + "\n\nMore text.\n" + ((_fh + _frow1) if table else "")
        (_fd / name).write_text(_body, encoding="utf-8")
        if reviewed:
            (_fd / (name + ".reviewed")).write_text(("Report text.\n\nMore text.\n" if same else "Report text, before.\n\nMore text.\n")
                                                    + ((_fh + _frow1) if table else ""), encoding="utf-8")
        _os_st.environ["REPLYCHECK_DRAFT"] = str(_fd / name)
        try:
            return "REVIEW-FIX-APPLIED" in run(_body, [check_review_fix_applied])
        finally:
            _os_st.environ.pop("REPLYCHECK_DRAFT", None)
    _prop("OI-0256 CONTROL a tableless report saying 'fixed rows none' with every finding disputed passes",
          not _fixt("PRE-SEND REVIEW: independent reviewer returned 2 findings; fixed rows none; 2 disputed because measured"))
    _prop("OI-0256 'fixed rows none' beside a fixed count still FAILS",
          _fixt("PRE-SEND REVIEW: independent reviewer returned 1 findings - 1 fixed; fixed rows none."))
    _prop("OI-0256 CONTROL a tableless report saying 'N fixed in text' with a changed draft passes",
          not _fixt("PRE-SEND REVIEW: independent reviewer returned 2 findings; 2 fixed in text"))
    _prop("OI-0256 'fixed in text' with a draft identical to the .reviewed copy FAILS",
          _fixt("PRE-SEND REVIEW: independent reviewer returned 2 findings; 2 fixed in text", same=True))
    _prop("OI-0256 'fixed in text' on a draft that carries a next-steps table FAILS",
          _fixt("PRE-SEND REVIEW: independent reviewer returned 2 findings; 2 fixed in text", table=True))
    _prop("OI-0256 'fixed in text' counting 0 fixed FAILS",
          _fixt("PRE-SEND REVIEW: independent reviewer returned 2 findings; 2 disputed because measured; fixed in text"))
    _prop("OI-0256 'fixed in text' with no <draft>.reviewed copy FAILS",
          _fixt("PRE-SEND REVIEW: independent reviewer returned 2 findings; 2 fixed in text", reviewed=False))
    # F-747 (2026-10-21): the tableless 'fixed rows N' failure must show the accepted form, since three capture runs and
    # nine sweep runs hit it with no example to copy (retrieval failure, not coverage).
    _fixt_name = "f747.md"
    _fixt_body = "Report text.\nPRE-SEND REVIEW: independent reviewer returned 3 findings; 2 fixed rows 1, 2; 1 disputed because measured\n\nMore text.\n"
    (_fd / _fixt_name).write_text(_fixt_body, encoding="utf-8")
    (_fd / (_fixt_name + ".reviewed")).write_text("Report text, before.\n\nMore text.\n", encoding="utf-8")
    _os_st.environ["REPLYCHECK_DRAFT"] = str(_fd / _fixt_name)
    try:
        _f747_codes = run(_fixt_body, [check_review_fix_applied])
        _f747_out = " ".join(m for c, m in FAILS if c == "REVIEW-FIX-APPLIED")
    finally:
        _os_st.environ.pop("REPLYCHECK_DRAFT", None)
    _prop("F-747 a tableless report naming fixed rows FAILS and the message shows the 'N fixed in text' form",
          "REVIEW-FIX-APPLIED" in _f747_codes and "5 fixed in text" in _f747_out)
    _prop("TABLE-LAST REVIEW-FIX-APPLIED CONTROL REPLYCHECK_DRAFT is cleared after the controls",
          "REPLYCHECK_DRAFT" not in _os_st.environ)
    # TABLE-AFTER-REVIEW MUTANT: with the header pattern disabled the positive fixture must stop firing.
    _tar_txt = _fh + _frow1 + "PRE-SEND REVIEW: independent reviewer returned 0 findings.\n"
    _tar_saved = _g["NEXT_STEPS_HEADER"]
    _g["NEXT_STEPS_HEADER"] = re.compile(r"(?!x)x")
    try:
        _tar_mut = "TABLE-AFTER-REVIEW" in run(_tar_txt, [check_table_after_review])
    finally:
        _g["NEXT_STEPS_HEADER"] = _tar_saved
    _prop("TABLE-AFTER-REVIEW MUTANT: with the header pattern disabled the positive control no longer fires", not _tar_mut)
    _prop("TABLE-AFTER-REVIEW MUTANT CONTROL: restoring the pattern restores the fire",
          "TABLE-AFTER-REVIEW" in run(_tar_txt, [check_table_after_review]))
    del FAILS[:], WARNS[:], INFO[:]

    # ---------- R115 (ROB 2026-09-29): THE EXPORT CARRIES BOTH VERDICTS AND IS STABLE ----------
    _ex = export_patterns()
    _fx = [r[1] for r in _ex["fixtures"]]
    _prop("R115 export fixtures carry at least one RATED and one UNRATED verdict", 1 in _fx and 0 in _fx)
    _prop("R115 export sha is stable across two calls", _ex["export_sha"] == export_patterns()["export_sha"])
    # ---------- F-291: DEFERRED-WORK, BOTH DIRECTIONS, ON TODAY'S OWN SENTENCES ----------
    _prop("F-291 'I sweep it after sending.' FAILS", len(deferred_sentences("I sweep it after sending.")) == 1)
    _prop("F-291 'Those last two fixes were not reviewed again.' FAILS",
          len(deferred_sentences("Those last two fixes were not reviewed again.")) == 1)
    _prop("F-291 'I have not run that comparison.' FAILS", len(deferred_sentences("I have not run that comparison.")) == 1)
    _prop("F-291 CONTROL past tense 'I kept working after sending' passes",
          not deferred_sentences("I kept working after sending, and the names are now worked up."))
    _prop("F-291 CONTROL a blocker in the same sentence passes",
          not deferred_sentences("The drift check was not run: a new gate waits on your yes in row 2."))
    _prop("F-291 CONTROL a stated reason passes",
          not deferred_sentences("plancheck was not re-run this turn because no plan artifact changed."))
    _prop("F-291 CONTROL a quoted admission passes",
          not deferred_sentences('My 12:44 reply said "I run it after sending" and shipped.'))
    _prop("F-291 CONTROL a CHECKED line is not scanned",
          not deferred_sentences("CHECKED: old reply -> \"not reviewed again\", which was not run."))
    _prop("R115 CONTROL a reply opening 'REPLYGATE NOT RUN' is NOT stamped",
          not STAMP_OPEN.search("REPLYGATE NOT RUN: no stamp exists for this reply.\n\nConfidence 7."))
    _prop("R115 the stamped fixture reads stamped and the plain one does not",
          [r[2] for r in _ex["fixtures"]].count(1) == 1)

    # ---------- C-032 (ROB APPROVED 2026-10-06 21:33 PDT): THE METRIC ID MOVES WITH THE LOGIC ----------
    global FILLER_RE
    _m0 = metric_id()
    _saved_filler = FILLER_RE
    try:
        FILLER_RE = list(FILLER_RE) + [re.compile(r"\bc032-probe-phrase\b", re.I)]
        _m1 = metric_id()
    finally:
        FILLER_RE = _saved_filler
    _prop("C-032 a change to a corpus check's regex changes metric_id (names alone stayed equal)",
          _m1 != _m0 and _m1.split("#")[0] == _m0.split("#")[0])
    _prop("C-032 CONTROL restoring the regex restores metric_id", metric_id() == _m0)
    check_filler("Great question! Happy to help.")
    _prop("C-032 CONTROL running a check does not move metric_id (runtime state is not logic)",
          metric_id() == _m0)
    del FAILS[:], WARNS[:], INFO[:]
    # NOT-RUN-CLAIM MUTANT (2026-10-14): disable the pattern and the 07:2x positive control must stop
    # firing; restore it and the control must fire again. A control that survives its own check being
    # switched off is not testing that check.
    _nr_sent = "You stopped the live drain before it started, so nothing moved on Instagram.\n"
    _nr_saved = _g["NOT_RUN_CLAIM"]
    _g["NOT_RUN_CLAIM"] = re.compile(r"(?!x)x")
    try:
        _nr_mut = "NOT-RUN-CLAIM" in run(_nr_sent, [check_not_run_claim])
    finally:
        _g["NOT_RUN_CLAIM"] = _nr_saved
    _prop("NOT-RUN-CLAIM MUTANT: with the pattern disabled the 07:2x control no longer fires", not _nr_mut)
    _prop("NOT-RUN-CLAIM MUTANT CONTROL: restoring the pattern restores the fire",
          "NOT-RUN-CLAIM" in run(_nr_sent, [check_not_run_claim]))
    del FAILS[:], WARNS[:], INFO[:]

    # ---------- OI-0495 (2026-11-19): A FENCED QUOTATION IS NOT CLAUDE'S OWN WORDS ----------
    # Measured on draft17 of session 1056270b: Rob's own global instructions field, quoted inside
    # a fence so he could paste it back, was refused for AGREEMENT, DEFERRED-WORK, ABSENCE-CLAIM
    # and 24 RATING-CLOSABLE matches. The fixture below carries one trigger for each of the four
    # codes the register row names, so every control is a PAIR: unfenced it must still fire (the
    # check is alive, not deleted), fenced it must stay silent (the quotation is not judged).
    del FAILS[:], WARNS[:], INFO[:]
    _q495 = ("Great question - here is your field as it stands.\n"
             "I will run the sweep after sending this reply.\n"
             "No other session covers the gate, and nothing recorded the run.\n"
             "Confidence: 9/10. I have not read the log that would settle it.\n")
    _c495 = {"AGREEMENT", "DEFERRED-WORK", "ABSENCE-CLAIM", "RATING-CLOSABLE"}
    _live495 = run(_q495, ALL)
    _prop("OI-0495 CONTROL the four trigger sentences, UNFENCED, still fire all four codes "
          "(missing: %s)" % (", ".join(sorted(_c495 - _live495)) or "none"), _c495 <= _live495)
    _fenced495 = run("Here is your field, unchanged, for pasting:\n\n```\n" + _q495 + "```\n", ALL)
    _prop("OI-0495 the same four sentences INSIDE A FENCE fire none of them (fired: %s)"
          % (", ".join(sorted(_c495 & _fenced495)) or "none"), not (_c495 & _fenced495))
    # The field itself contains fenced examples, so the quotation has to be wrapped in a LONGER
    # fence. A three-backtick walk would close on the inner example and judge the rest.
    _nest495 = run("Your field, which itself contains a fence:\n\n````\n" + _q495
                   + "```\n| # | Issue / Risk |\n```\n" + _q495 + "````\n", ALL)
    _prop("OI-0495 a ````-wrapped quotation carrying its own ``` example is masked whole "
          "(fired: %s)" % (", ".join(sorted(_c495 & _nest495)) or "none"), not (_c495 & _nest495))
    _unclosed495 = run("Pasting your field now:\n\n```\n" + _q495, ALL)
    _prop("OI-0495 an UNCLOSED fence masks to the end of the draft rather than nothing "
          "(fired: %s)" % (", ".join(sorted(_c495 & _unclosed495)) or "none"),
          not (_c495 & _unclosed495))
    _prop("OI-0495 masking keeps the line count and the offsets of the text outside the fence",
          len(fenced_blanked(_q495 + "```\nx\n```\ntail\n").split("\n"))
          == len((_q495 + "```\nx\n```\ntail\n").split("\n"))
          and fenced_blanked("a\n```\nx\n```\nb\n").splitlines()[0] == "a")
    _prop("OI-0495 an inline `code` span is blanked for a prose check and KEPT for an evidence "
          "check, because Rob's own form writes the command inside backticks",
          "selftest" not in owned_prose("CHECKED: `python3 x.py --selftest` -> 0 FAIL")
          and "selftest" in owned_text("CHECKED: `python3 x.py --selftest` -> 0 FAIL"))
    # WIRING: the two sets must name real functions, must not overlap, and the four checks the
    # register row names must actually be wrapped. A set naming a check that no longer exists is
    # how a mask silently stops covering the thing it was built for.
    _ghosts495 = sorted(n for n in (RAW_CHECKS | PROSE_CHECKS) if not callable(_g.get(n)))
    _prop("OI-0495 WIRING every name in RAW_CHECKS and PROSE_CHECKS is a function in this "
          "module (ghosts: %s)" % (", ".join(_ghosts495) or "none"), not _ghosts495)
    _prop("OI-0495 WIRING RAW_CHECKS and PROSE_CHECKS do not overlap (both: %s)"
          % (", ".join(sorted(RAW_CHECKS & PROSE_CHECKS)) or "none"),
          not (RAW_CHECKS & PROSE_CHECKS))
    _unmasked495 = sorted(n for n in ("check_agreement", "check_deferred_work",
                                      "check_absence_claim", "check_rating_closable")
                          if not getattr(_g.get(n), "imc_masked", None))
    _prop("OI-0495 WIRING the four checks the register row names are wrapped (unmasked: %s)"
          % (", ".join(_unmasked495) or "none"), not _unmasked495)
    _prop("OI-0495 WIRING every check_ function is either masked or named in RAW_CHECKS",
          not sorted(n for n, v in _g.items() if n.startswith("check_") and callable(v)
                     and n not in RAW_CHECKS and not getattr(v, "imc_masked", None)))
    # LINK-REGISTRY fired three times on that same fenced copy of Rob's field (measured on the
    # Mac 2026-11-19 21:05 PST), because the field names verify.sh and other registered files and
    # the check demanded a link for each. Naming a file inside a QUOTATION is not Claude naming
    # it. The registry is swapped for a temp file here, so the pair does not depend on which
    # machine runs it - the seven older link-registry controls need Rob's own registry and fail
    # in a container, and this one must not join them.
    global LINK_REGISTRY
    _lr_saved = LINK_REGISTRY
    _lr_td = pathlib.Path(tempfile.mkdtemp())
    (_lr_td / "link.tsv").write_text("https://example.invalid/v\tverify.sh on the Mac\tverify.sh\n",
                                     encoding="utf-8")
    LINK_REGISTRY = _lr_td / "link.tsv"
    _lr_tbl = ("A first line, because the anchor regex wants a newline before it.\n\n"
               "NEXT STEPS\n\n"   # next_steps_block() anchors on this line or a '| # | Item |' header
               "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n"
               "|---|---|---|---|---|---|---|\n| 1 | a | b | Rob | c. | Pro: a. | Con: b. |\n\n")
    _lr_say = "Run verify.sh before changing any instruction field.\n"
    try:
        _prop("OI-0495 CONTROL a registered label named in Claude's own prose still demands its "
              "link", "LINK-REGISTRY" in run(_lr_tbl + _lr_say, [check_link_registry]))
        _prop("OI-0495 the same label named INSIDE a fence demands no link",
              "LINK-REGISTRY" not in run(_lr_tbl + "````\n" + _lr_say + "````\n",
                                         [check_link_registry]))
    finally:
        LINK_REGISTRY = _lr_saved
    # The excusing half still reads the literal draft: a CHECKED line inside a fence must still
    # excuse an absence claim made outside it, or masking would have invented a failure.
    _prop("OI-0495 evidence inside a fence still EXCUSES an absence claim outside it",
          "ABSENCE-CLAIM" not in run("```\nCHECKED: grep -rn x . -> 3 hits, control row found\n```\n"
                                     "Nothing covers the gate.\n", [check_absence_claim]))
    del FAILS[:], WARNS[:], INFO[:]

    import subprocess
    r = subprocess.run([sys.executable, __file__], input="", capture_output=True, text=True)
    ok = r.returncode == 2 and "NOT CHECKED" in r.stdout
    print(("  ok    " if ok else "  BAD   ") + "empty input exits 2 and says NOT CHECKED")
    p, f = (p + 1, f) if ok else (p, f + 1)
    f += _wiring_failed
    print("\n  PASSED %d   FAILED %d" % (p, f) + ("   SKIPPED %d (machine-only cases)" % _skipped if _skipped else ""))
    return 1 if f else 0



def _drive_resolve(path):
    """F-215. OFF THE LAPTOP AN ANCHOR IS NOT MISSING, IT IS MOUNTED SOMEWHERE ELSE.
    Column 6 holds absolute /Users/robk/... paths. In a Cowork sandbox that root does not exist
    and cannot be created, so every anchor failed as UNRESOLVABLE and this check was unusable
    there. bin/driveresolve.py maps the path onto the mounted copy and returns None rather than
    guessing, so a genuinely missing anchor still fails exactly as it did before.
    IT IS IMPORTED LAZILY AND FAILS OPEN TO THE ORIGINAL PATH: replycheck must keep running on a
    machine where the resolver is absent, and a gate that dies because its helper moved is worse
    than the blindness it was written to cure."""
    try:
        import importlib.util
        import os
        for root in (os.path.expanduser("~/Claude/Improving-my-Claude/bin"),
                     os.path.expanduser("~/mnt/Improving-my-Claude/bin")):
            mod = os.path.join(root, "driveresolve.py")
            if os.path.isfile(mod):
                spec = importlib.util.spec_from_file_location("driveresolve", mod)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                return m.resolve(path)
    except Exception:
        pass
    return None


# *** SELFCHECK, ROB 2026-10-17 07:50 PDT (0.2.15): "apply that rule in precheck.py. I want that to be used in all
# current and future sessions, chats, and tasks across all of my Claude." *** Rob's 07:43 PDT ask: every
# next-steps table carries a self-check that answers "Have you been thorough in your analysis? How confident are
# you in your recommendations and next steps?" BEFORE the reply reaches him. THIS PARTLY REVERSES R155 (2026-10-01),
# which retired THOROUGH-SIX because six visible criteria failed 96 percent of rated replies. SELFCHECK is the
# smaller form: ONE line, two answers, no six-criteria machinery. It proves the line is present and well-formed;
# it cannot prove the analysis was thorough - the independent reviewer and the CHECKED line carry that.
_SC_LINE = re.compile(r"^\s*\*{0,2}SELF-CHECK\*{0,2}\s*:(.*)$", re.M | re.I)
_SC_THOROUGH = re.compile(r"\bthorough(?:ly)?\s*:\s*(yes|no|partly)\b", re.I)
_SC_CONF = re.compile(r"\bconfidence\s*:\s*(\d{1,2})\s*/\s*10\b", re.I)
_SC_FALSIFIER = re.compile(r"\b(drops?|falls?|would drop|lower(?:ed)?|down)\b[^.;\n]{0,40}\b(to|if|by|when)\b", re.I)


def check_selfcheck_never_no(text):
    """Rob 2026-10-30 10:19 and 12:10 PDT (INTAKE F-1055): ANY SELF-CHECK line, with or without a table, answers
    thorough: yes. 'no' and 'partly' are never sent. check_table_selfcheck only ran on table replies."""
    for m in _SC_LINE.finditer(text):
        if re.search(r"\bdrops?\s+to\b", m.group(1), re.I):
            fail("SELFCHECK", "a SELF-CHECK line carries 'drops to': Rob 2026-11-03 10:18 PM PST, that means the analysis was NOT "
                 "finished. Keep working until it reads 'thorough: yes' with confidence 9/10 or 10/10 and 'no residual uncertainty'.")
            return
        t = _SC_THOROUGH.search(m.group(1))
        if t and t.group(1).lower() in ("no", "partly"):
            fail("SELFCHECK", "a SELF-CHECK line says thorough: %s. Rob 2026-10-30 10:19 and 12:10 PDT: it always says yes, "
                 "with nothing relevant unread. Read the source by code, or name the failed call after BLOCKED: and say the "
                 "work is unfinished; do not rate it." % t.group(1).lower())
            return


def check_table_selfcheck(text):
    if not _table_rows(text):
        return
    m = _SC_LINE.search(text)
    if not m:
        fail("SELFCHECK",
             "this reply carries a next-steps table and no SELF-CHECK line. Rob 2026-10-17 07:50 PDT: before "
             "any table reaches him, one line answers 'Have you been thorough in your analysis? How confident "
             "are you in your recommendations and next steps?'. Form: 'SELF-CHECK: thorough: yes - <what was "
             "read and what was not>; confidence: 10/10 in the recommendations and next steps, no residual uncertainty.' A line that carries 'drops to' is refused (Rob 2026-11-03 10:18 PM PST).")
        return
    body = m.group(1)
    if not _SC_THOROUGH.search(body):
        fail("SELFCHECK", "the SELF-CHECK line has no 'thorough: yes|no' answer to 'Have you been thorough "
             "in your analysis?'.")
        return
    if re.search(r"\bthorough(?:ly)?\s*:\s*partly\b", body, re.I):
        fail("SELFCHECK", "the SELF-CHECK says thorough: partly. Rob 2026-10-29 15:10 PDT (R428): never send "
             "'thorough: partly'. Answer yes or no, and close the gap with a tool call or a BLOCKED line.")
        return
    c = _SC_CONF.search(body)
    if not c:
        fail("SELFCHECK", "the SELF-CHECK line has no 'confidence: N/10' answer to 'How confident are you in your "
             "recommendations and next steps?'.")
        return
    if not (1 <= int(c.group(1)) <= 10):
        fail("SELFCHECK", "the SELF-CHECK confidence is %s/10, outside 1 to 10." % c.group(1))
        return
    t = _SC_THOROUGH.search(body)
    if t and t.group(1).lower() in ("no", "partly") and not re.search(r"\bBLOCKED\s*:", body, re.I):
        fail("SELFCHECK", "the SELF-CHECK says thorough: %s with no 'BLOCKED: <the call that failed and its error, or the "
             "decision that is Rob's>'. Rob 2026-10-19: an unfinished analysis is closed with a tool call, not rated; a gap "
             "that a call could close is not a reason to send." % t.group(1).lower())
        return
    if t and t.group(1).lower() == "no":
        fail("SELFCHECK", "the SELF-CHECK says thorough: no. Rob 2026-10-30 10:19 PDT and 12:10 PDT (INTAKE F-1047): the SELF-CHECK "
             "always says yes, with nothing relevant unread; 'no' is never sent. Read the source by code, or if a call fails, put "
             "'BLOCKED: <the call that failed and its error>' and say the work is not finished; do not rate it. "
             "An open register row or a pending decision is not a reading gap.")
        return
    # DROPS-TO-OPEN (Rob 2026-11-03 10:18 PM PST): 'drops to' in the SELF-CHECK means the analysis is not finished.
    # At 9/10 or 10/10 the line declares 'no residual uncertainty' instead of naming a falsifier.
    if re.search(r"\bdrops?\s+to\b", body, re.I):
        fail("SELFCHECK", "the SELF-CHECK line carries 'drops to': Rob 2026-11-03 10:18 PM PST, that means the analysis was NOT "
             "finished. Keep working until the line reads 'thorough: yes' with confidence 9/10 or 10/10 and 'no residual uncertainty'.")
        return
    if int(c.group(1)) >= 9 and NO_RESIDUAL.search(body):
        return
    if not _SC_FALSIFIER.search(body):
        fail("SELFCHECK", "the SELF-CHECK confidence names nothing that would lower it. Say what would drop it, "
             "e.g. 'lower if <X>' ('drops to' is refused here); a rating with no falsifier is the RATING-BARE defect.")


# *** ROOTCAUSE (0.2.25, Rob 2026-10-18 and 2026-10-19 12:06 PM PDT; register row OI-0271) ***
# Rob's rule: the root cause is investigated BEFORE any recommendation. It ran on judgement and was missed, so it
# is now a refusal. Every Claude-owned work row must carry a 'CAUSE:' statement in its Issue / Risk cell, the
# statement must say how well the cause is known (measured, inferred, or not yet investigated), and two rows may
# not carry the same CAUSE text, because one sentence pasted down a column explains no row in particular.
# Rob-owned rows (a pure decision) and the standing process rows are exempt. This proves the cause is STATED and
# DISTINCT; it cannot prove it is right - the reviewer and the CHECKED lines carry that.
_RC_STANDING = re.compile(r"^\s*\**(APPROVAL|CONFORMANCE CHECK|HOSTILE REVIEW|SAMPLE GATE|INSTRUCTION FIELD FIRST)\b", re.I)
_RC_CAUSE = re.compile(r"\bCAUSE\s*:\s*(.+?)(?:\s*$)", re.I | re.S)
_RC_MARK = re.compile(r"\b(measured|inferred|not yet investigated|stated in the row)\b", re.I)


def check_table_rootcause(text):
    rows = _table_rows(text)
    if not rows:
        return
    seen = {}
    for rank, item, _status, owner in rows:
        if re.match(r"\s*rob\b", owner, re.I) or _RC_STANDING.match(item):
            continue
        m = _RC_CAUSE.search(item)
        if not m:
            fail("ROOTCAUSE", "row %d has no 'CAUSE:' statement in its Issue / Risk cell. Rob 2026-10-18: the root cause "
                 "is investigated before any recommendation. State it, or write 'CAUSE: not yet investigated' and make "
                 "the row's Action the investigation." % rank)
            continue
        body = m.group(1).strip()
        if re.search(r"not yet investigated", body, re.I):  # 0.3.18 CHANGE 4
            fail("ROOTCAUSE", "row %d CAUSE is 'not yet investigated' on a Claude-owned row. The investigation is in your own "
                 "column: run it now, then write 'measured' or 'inferred' with the output that shows it." % rank)
        if not _RC_MARK.search(body):
            fail("ROOTCAUSE", "row %d CAUSE does not say how well the cause is known: add 'measured', 'inferred' or 'not "
                 "yet investigated'." % rank)
        key = re.sub(r"\W+", " ", body.lower()).strip()
        if key in seen:
            fail("ROOTCAUSE", "row %d carries the same CAUSE text as row %d. One sentence pasted down a column explains no "
                 "row in particular; give each row its own cause." % (rank, seen[key]))
        else:
            seen[key] = rank


# *** PREVENTS (0.2.28, Rob rows 13 and 66 of the 2026-10-20 12:12 PM table) ***
# ROOTCAUSE proves a cause is STATED and DISTINCT. It cannot prove the Action removes it, so a restated symptom
# passed as a cause. PREVENTS closes that gap in the one way a script can: every Claude-owned work row's Action
# must carry 'Prevents recurrence: <clause>', and the clause must either name a check that exists in
# checks-registry.txt (this plugin's own check codes are added at run time) or say JUDGEMENT-ONLY. A clause that
# names neither is refused, so boilerplate and an invented check name both fail. Two rows may not carry the same
# clause. Each reply prints how many of its rows are JUDGEMENT-ONLY, so a column of JUDGEMENT-ONLY is visible.
# LIMIT, STATED: the registry is a snapshot of check names on Rob's Mac and in this plugin; a plugin running in
# the cloud cannot open the Mac to confirm a script still exists. checks-registry.txt is regenerated by
# build-registry (README 0.2.28). The check proves the name is KNOWN, not that the check still passes.
_PV_CLAUSE = re.compile(r"\bPrevents\s+recurrence\s*:\s*(.+)$", re.I | re.S)
_PV_JUDGE = re.compile(r"\bJUDGEMENT[- ]ONLY\b", re.I)


def _pv_registry():
    names = set()
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        for ln in open(os.path.join(here, "checks-registry.txt"), errors="ignore"):
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                names.add(ln)
    except OSError:
        pass
    try:
        src = open(os.path.abspath(__file__), errors="ignore").read()
        names.update(re.findall(r'\bfail\(\s*"([A-Z][A-Z0-9-]{2,})"', src))
    except OSError:
        pass
    return names


def _pv_actions(text):
    hdr = _header_map(text)
    out = {}
    if not hdr or "action" not in hdr:
        return out
    for m in TABLE_ROW.finditer(text):
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) > hdr["action"]:
            out[int(m.group(1))] = cells[hdr["action"]]
    return out


def check_table_prevents(text):
    rows = _table_rows(text)
    if not rows:
        return
    acts = _pv_actions(text)
    if not acts:
        fail("PREVENTS", "the next-steps table has no Action column, so no row can carry a 'Prevents recurrence:' clause.")
        return
    reg = _pv_registry()
    seen, judge, total = {}, 0, 0
    for rank, item, _status, owner in rows:
        if re.match(r"\s*rob\b", owner, re.I) or _RC_STANDING.match(item):
            continue
        total += 1
        act = acts.get(rank, "")
        m = _PV_CLAUSE.search(act)
        if not m:
            fail("PREVENTS", "row %d Action has no 'Prevents recurrence:' clause. Rob rows 13 and 66, 2026-10-20: the "
                 "gate, not my drafting, decides whether a fix removes the cause. Name a check that exists in "
                 "checks-registry.txt, or write 'Prevents recurrence: JUDGEMENT-ONLY' and say why no check can run." % rank)
            continue
        body = m.group(1).strip()
        is_judge = bool(_PV_JUDGE.search(body))
        named = [n for n in reg if re.search(r"(?<![A-Za-z0-9_.-])" + re.escape(n) + r"(?![A-Za-z0-9_-])", body, re.I)]
        if not is_judge and not named:
            fail("PREVENTS", "row %d 'Prevents recurrence:' names no check in checks-registry.txt and does not say "
                 "JUDGEMENT-ONLY. A check name that is not in the registry is treated as invented; name a real one or "
                 "mark the row JUDGEMENT-ONLY." % rank)
            continue
        if is_judge:
            judge += 1
        key = re.sub(r"\W+", " ", body.lower()).strip()
        if key in seen:
            fail("PREVENTS", "row %d carries the same 'Prevents recurrence:' clause as row %d. One clause pasted down a "
                 "column prevents nothing in particular." % (rank, seen[key]))
        else:
            seen[key] = rank
    if total:
        warn("PREVENTS-COUNT", "%d of %d Claude-owned rows are JUDGEMENT-ONLY (no check enforces the fix)." % (judge, total))


# ---------- RANK-STRUCT (0.3.0, Rob 2026-10-23 09:40 PDT; INTAKE F-761) ----------
# RANK-DEPENDENCY fired 0 times in 3,754 gate-log lines: its table finder anchored on a retired header and its
# parser split on the first pipe, so Rob's ordering rule (a blocker ranks above what it blocks, transitively) was
# not enforced on the seven-column table at all. This check reads the table structurally. Each row states
# "BLOCKS: row N" or "BLOCKS: none" and may state "Waits on rows N" in Issue / Risk; rank is the # column.
import re as _rs_re
_RS_HDR = _rs_re.compile(r'^\|\s*#\s*\|\s*Issue\s*/\s*Risk\s*\|\s*Action\s*\|\s*Owner\s*\|', _rs_re.I)
_RS_NUMS = r'((?:rows?\s+)?\d+(?:\s*(?:,|and|to|&)\s*(?:rows?\s+)?\d+)*)'
_RS_BLOCKS = _rs_re.compile(r'BLOCKS:\s*(none\b|rows?\s+\d+(?:\s*(?:,|and|&)\s*\d+)*)', _rs_re.I)
_RS_WAITS = _rs_re.compile(r'Waits\s+on\s+rows?\s+(\d+(?:\s*(?:,|and|&|to)\s*\d+)*)', _rs_re.I)
_RS_BLOCKEDBY = _rs_re.compile(r'blocked\s+by\b(?!\s+rows?\s+\d)', _rs_re.I)
_RS_DEP = _rs_re.compile(r'\b(blocked by|waits on|depends on|needs row|after row)\b', _rs_re.I)

def _rs_nums(txt):
    txt = txt.lower()
    out = []
    parts = _rs_re.split(r'\s*(?:,|and|&)\s*', _rs_re.sub(r'rows?\s+', '', txt))
    for p in parts:
        m = _rs_re.fullmatch(r'(\d+)\s*to\s*(\d+)', p.strip())
        if m: out += list(range(int(m.group(1)), int(m.group(2)) + 1))
        elif p.strip().isdigit(): out.append(int(p))
    return out

def _rs_rows(text):
    res, on = {}, False
    for line in text.split('\n'):
        if _RS_HDR.match(line): on = True; continue
        if on and _rs_re.match(r'^\|\s*-+', line): continue
        if on and line.startswith('|'):
            cells = [c.strip() for c in line.strip().strip('|').split(' | ')]
            if cells and cells[0].isdigit(): res[int(cells[0])] = cells
        elif on and not line.strip(): continue
        elif on: on = False
    return res

def _rs_check(text):
    R = _rs_rows(text); fails = []
    if not R: return fails
    edges, nonecount, missing = [], 0, []
    for n, c in R.items():
        issue = c[1] if len(c) > 1 else ''
        m = _RS_BLOCKS.search(issue)
        if m:
            if m.group(1).lower() == 'none': nonecount += 1
            else: edges += [(n, t) for t in _rs_nums(m.group(1))]
        w = _RS_WAITS.search(issue)
        if w: edges += [(b, n) for b in _rs_nums(w.group(1))]
        if _RS_BLOCKEDBY.search(issue): fails.append("row %d says 'blocked by' with no row number" % n)
        if not m and not w and len(R) >= 2: missing.append(n)  # 0.3.38 (Rob 2026-11-04 8:38 PM PST: tables in stack-ranked priority order)
    if missing:
        fails.append("rows %s state neither 'BLOCKS: row N' nor 'BLOCKS: none', so the rank order cannot be checked" % ", ".join(str(x) for x in missing))
    for b, t in edges:
        if b not in R or t not in R: fails.append("edge %d blocks %d names a row that does not exist" % (b, t))
        elif b >= t: fails.append("row %d blocks row %d but ranks at or below it" % (b, t))
    g = {}
    for b, t in edges: g.setdefault(b, set()).add(t)
    def cyc(n, seen):
        if n in seen: return True
        return any(cyc(t, seen | {n}) for t in g.get(n, ()))
    if any(cyc(n, frozenset()) for n in g): fails.append("a blocking cycle exists")
    if nonecount == len(R) and any(_RS_DEP.search(' '.join(c[1:3])) for c in R.values()):
        fails.append("every row says BLOCKS: none while the text names a dependency")
    return fails



def check_rank_struct(text):
    for f in _rs_check(text):
        fail("RANK-STRUCT", f + ". Rob 2026-10-23: a row that blocks another ranks above it. State BLOCKS: row N or BLOCKS: none in Issue / Risk, and order the rows so every blocker has the lower number.")


# ---------- OI-0495: WIRING THE CLAUDE-OWNED MASK ----------
# RAW_CHECKS read the literal draft. Each one REQUIRES something to be present, or judges the
# fences and the table structure themselves, so masking could only invent a failure.
RAW_CHECKS = frozenset("""
check_claim_ledger check_uncited_claims check_reach_unsourced check_every_reply_table
check_open_row_link check_test_field check_gate_ratio check_rob_row check_rulings_cited
check_standing_quote check_close_gates check_sent_checked check_site_fault
check_approval_untested check_handoff_untested check_decline_unquoted check_scope_vs_claim
check_count_then_universe check_probe check_table_shape check_labels
check_block_render check_counts check_rank_inversion check_rank_contradiction
check_rank_struct check_split_by_owner check_unblocked_stop check_presend_review
check_table_after_review check_review_fix_applied check_con_format check_cell_width
check_id_name check_objective_sections check_table_selfcheck check_table_rootcause
check_table_prevents check_denominator check_cited_instruction check_acronyms check_gloss
check_own_column check_standing_rows check_call_on_rob check_exercise_on_rob
check_artifact_item_on_rob check_ownership check_position check_review_link
check_commit_then_stop check_link_reuse check_link_resolves check_link_escapes
""".split())

# PROSE_CHECKS read prose for banned or deferring WORDING, so inline `code` spans are blanked
# for them too. Every other masked check sees fences blanked only.
PROSE_CHECKS = frozenset("""
check_agreement check_deferred_work check_absence_claim check_not_run_claim
check_rating_closable check_filler check_tool_deadend check_ends_on_intent check_done_claim
check_untested_rec check_tested_hedge check_selfcheck_never_no check_voice check_opener
check_nothing_left check_prose_decision check_prose_count check_owner_pronoun
check_skill_claim check_offload check_prediction
""".split())


def _owned_arg(name, fn):
    """fn with its first argument replaced by the Claude-owned view of the draft. The literal
    draft stays reachable through raw_text() for the excusing half of a mixed check."""
    import functools
    view = owned_prose if name in PROSE_CHECKS else owned_text

    @functools.wraps(fn)
    def inner(text, *a, **kw):
        prev = _RAW_DRAFT["text"]
        _RAW_DRAFT["text"] = text
        try:
            return fn(view(text), *a, **kw)
        finally:
            _RAW_DRAFT["text"] = prev
    inner.imc_masked = view.__name__
    return inner


def _install_owned_mask(g=None):
    """Wrap every check_ function in this module except RAW_CHECKS, and return the names wrapped.
    CORPUS_CHECKS was built further up from the unwrapped functions and stays unwrapped on
    purpose: it scores the session history for a rate, it gates nothing, and _logic_fingerprint
    reads each of those functions' own bytecode."""
    g = globals() if g is None else g
    done = []
    for name in sorted(n for n in list(g) if n.startswith("check_")):
        fn = g[name]
        if not callable(fn) or getattr(fn, "imc_masked", None) or name in RAW_CHECKS:
            continue
        g[name] = _owned_arg(name, fn)
        done.append(name)
    return done


MASKED_CHECKS = tuple(_install_owned_mask())


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        print("REPLYCHECK SELF-TEST\n")
        sys.exit(_selftest())
    if len(sys.argv) > 2 and sys.argv[1] == "--rate":
        sys.exit(corpus_rate(sys.argv[2]))
    if len(sys.argv) > 1 and sys.argv[1] == "--export-patterns":
        import json
        print(json.dumps(export_patterns(), sort_keys=True, ensure_ascii=True))
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        text = open(sys.argv[1], errors="ignore").read()
    else:
        text = sys.stdin.read()
    # *** EMPTY INPUT USED TO PRINT "0 FAIL, 0 WARN" AND EXIT 0. ***
    # A linter that passes nothing is the zero-without-a-control defect, in the one tool
    # whose job is to catch exactly that. It made every accidental empty pipe look clean.
    if not text.strip():
        print("NOT CHECKED  empty input - nothing was linted, and this is NOT a pass")
        sys.exit(2)
    claims, checked = check_claim_ledger(text)
    # CHECKED_RE matches the line START, so re-extract the full lines to compare against.
    _checked_lines = [ln for ln in text.splitlines() if CHECKED_RE.match(ln)]
    check_uncited_claims(text, claims, _checked_lines)
    check_offload(text)
    check_tool_deadend(text)
    check_reach_unsourced(text)
    check_opener(text)
    check_every_reply_table(text)
    check_done_claim(text)            # DONE-NO-CALL, Rob 2026-11-04 (0.3.37)
    check_closed_inferred(text)       # CLOSED-ON-INFERRED-CAUSE, core serial 6 (OI-0789)
    check_ends_on_intent(text)        # ENDS-ON-INTENT, Rob 2026-11-05 (0.3.39)
    check_nothing_left(text)          # NOTHING-LEFT-CLAIM, Rob 2026-11-11 (0.3.47, R26)
    check_untested_rec(text)          # REC-NOT-TESTED, Rob 2026-11-05 (0.3.41)
    check_tested_hedge(text)          # REC-TESTED-HEDGE, Rob 2026-11-09
    check_filler(text)
    check_prediction(text)
    check_open_row_link(text)
    check_test_field(text)
    check_gate_ratio(text)
    check_rob_row(text)
    check_rulings_cited(text)
    check_standing_quote(text)
    check_close_gates(text)
    check_sent_checked(text)
    check_deferred_work(text)
    check_absence_claim(text)
    check_not_run_claim(text)
    check_site_fault(text)
    check_approval_untested(text)
    check_handoff_untested(text)
    check_decline_unquoted(text)
    check_scope_vs_claim(text)
    check_skill_claim(text)
    check_count_then_universe(text)
    check_owner_pronoun(text)
    check_probe(text)
    check_table_shape(text)
    check_labels(text)
    check_link_registry(text)
    check_block_render(text)
    check_counts(text)
    check_prose_count(text)
    check_rating(text, claims, checked)
    check_rank_inversion(text)
    check_rank_contradiction(text)
    check_rank_struct(text)           # RANK-STRUCT, Rob 2026-10-23 (0.3.0)
    check_split_by_owner(text)
    check_unblocked_stop(text)
    check_presend_review(text)
    check_table_after_review(text)    # TABLE-LAST, Rob 2026-10-14 09:41 PDT (0.2.4)
    check_review_fix_applied(text)    # TABLE-LAST, Rob 2026-10-14 09:41 PDT (0.2.4)
    check_con_format(text)            # R287, Rob 2026-10-15 10:04 PDT (0.2.7)
    check_cell_width(text)            # Rob 2026-10-22 18:38 PDT: raw URL / long run in a cell
    check_id_name(text)               # R287, Rob 2026-10-15 10:04 PDT (0.2.7)
    check_objective_sections(text)    # R291, Rob 2026-10-15 11:12 PDT (0.2.9)
    check_table_selfcheck(text)       # SELFCHECK, Rob 2026-10-17 07:50 PDT (0.2.15)
    check_selfcheck_never_no(text)    # SELFCHECK, Rob 2026-10-30 12:10 PDT (0.3.32)
    try:                              # RECO-RUN, MEASURED-LABEL, CONF-TESTED, Rob 2026-10-29 14:09 PDT (0.3.26)
        import runbehind as _runbehind
        _runbehind.check(text, fail, warn)
    except ImportError:
        warn("RUNBEHIND-MISSING", "checker/runbehind.py is not installed beside replycheck.py")
    check_table_rootcause(text)       # ROOTCAUSE, Rob 2026-10-18, OI-0271 (0.2.25)
    check_table_prevents(text)        # PREVENTS, Rob rows 13 and 66, 2026-10-20 (0.2.28)
    # *** RETIRED R155, ROB 2026-10-01 19:29 PDT, "Agree with your recommendations." ***
    # THOROUGH-SIX required a visible THOROUGH: section on every rated reply. Rob's global field
    # says to show the result, not the scaffolding, and wins on conflict. Measured over 3,126
    # cloud replies it failed 96% of the rated ones (F-406), so it separated nothing.
    # RATING-CLOSABLE carries the substance - a rating offered where a check could be run - and
    # now reads every exported reply (R150, F-414). This reverses R120's strengthening on Rob's
    # per-item ruling. The function is kept, uncalled, as the record of what was enforced.
    # (was: check_thorough_five(text); renamed retired_r155_thorough_five)
    check_prose_decision(text)
    check_denominator(text)
    check_cited_instruction(text)
    # WIRED INTO THE PRE-SEND PATH 2026-09-10. It was in CORPUS_CHECKS - which only scores the
    # session history - and in nothing else, so the acronym rule had never once been applied to
    # a reply about to be sent. It reports at warn severity until the TITLE-NAMING BOUNDARY is
    # ruled - THAT WORDING IS SUPERSEDED, the ruling landed 2026-09-10 and did not restore fail().
    # It stays at warn on a MEASURED residual of 3.2 to 11.0 percent on the chat surface; see the
    # note at check_acronyms for the arithmetic condition that would restore fail().
    check_acronyms(text)
    check_gloss(text)
    check_own_column(text)
    # STANDING-ROWS, wired here as well as into CORPUS_CHECKS. The list alone is not
    # dispatch, and this file's own WIRING control said so on the first run.
    check_standing_rows(text)
    check_call_on_rob(text)
    check_exercise_on_rob(text)
    check_artifact_item_on_rob(text)
    check_ownership(text)
    check_position(text)
    check_voice(text)
    check_agreement(text)
    check_review_link(text)
    check_commit_then_stop(text)
    check_link_reuse(text)
    check_link_resolves(text)
    check_link_escapes(text)

    # *** RULES RETIRED 2026-09-18 BY ROB, R026, ON THE R025 MEASUREMENT. ***
    # R025 set the criterion: retire any rule that misfires more often than it catches. Over the
    # 1,007 failure episodes in the 73 transcripts (REPLYCHECK-FP-2026-09-18.md), these seven met
    # it, and Rob approved each one individually: "Approve #1-7 and 9". THE CHECK FUNCTIONS STILL
    # RUN, AND THE SELF-TEST STILL EXERCISES THEM, so un-retiring is deleting a name from this set.
    # A retired rule's hits are dropped from FAIL and WARN and counted on one INFO line, so they
    # can be measured without gating anything. Row 9 (THOROUGH-SIX) was KEPT, per Rob's approval of
    # that row's recommendation.
    # REVIEW-LINK UN-RETIRED 2026-09-18, R028 ("Approve #1 and 2."). Its retirement had rested
    # partly on Claude's false claim that OPEN-ROW-LINK already covered it. OPEN-ROW-LINK skips
    # rows marked NO-ARTIFACT and REVIEW-LINK does not; its catches after OPEN-ROW-LINK existed,
    # with no OPEN-ROW-LINK fire on the same rows, are counted in REPLYCHECK-FP-2026-09-18.md.
    RETIRED = {"CHECKS-LATE", "CALL-ON-ROB", "ARTIFACT-ITEM-ON-ROB", "OWN-COLUMN",
               "OFFLOAD", "PREDICTION-MISSING"}
    _ret = [c for c, m in FAILS + WARNS if c in RETIRED]
    FAILS[:] = [(c, m) for c, m in FAILS if c not in RETIRED]
    WARNS[:] = [(c, m) for c, m in WARNS if c not in RETIRED]
    if _ret:
        INFO.append("RETIRED (R026, not gating): %s" % ", ".join(sorted(set(_ret))))
    for m in INFO:
        print("INFO  " + m)
    for c, m in WARNS:
        print("WARN  [%s] %s" % (c, m))
    for c, m in FAILS:
        print("FAIL  [%s] %s" % (c, m))
    print("---")
    print("%d FAIL, %d WARN" % (len(FAILS), len(WARNS)))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
