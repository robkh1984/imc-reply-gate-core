#!/usr/bin/env python3
"""imc-reply-gate (renamed from prompt-library-reply-gate in 0.1.8, H6 2026-10-09; owner Improving my Claude (Overall)): run checker/replycheck.py on a reply and block it on any unwaived FAIL.

Modes (argv[1]):
  stop     Stop hook. Checks payload last_assistant_message, else the last assistant text in
           transcript_path.
  pretool  PreToolUse hook on SendUserMessage and PushNotification. Checks tool_input.message.
           A blocked PushNotification STILL REACHES ROB'S PHONE: measured 2026-10-15, a push blocked at
           ~11:31 PDT showed on his phone (Rob 11:47 PDT, OI-0201). The 2026-10-05 claim that it is not
           sent (audit item 26) was false.

Contract:
  - INCOMPLETE (0.2.0, F-523, Rob 2026-10-11 12:14 PDT): runs in EVERY session the plugin loads in,
    scoped or not. A reply line that uses incomplete-review wording ("not checked", "partly done",
    "caveat" ...) fails unless that line or the next one carries "BLOCKED:" naming the tool call that
    failed or the decision that is Rob's. Text inside double quotes, backticks, code fences and
    ">" quote lines is ignored, so quoting Rob or a file does not trip it.
  - The full replycheck.py runs only when the transcript contains the AI Prompt Library or the
    Improving my Claude (Overall) attachment marker (the second added in 0.1.9, OI-0027).
  - RATING-CLOSABLE (0.2.1, R272, Rob 2026-10-11 19:04 PDT): Rob's confidence rule is account-wide,
    so every OTHER session runs replycheck.py too and keeps only its RATING-CLOSABLE result, beside
    INCOMPLETE. A reply that rates itself while naming a check Claude could run fails anywhere.
  - NOT-RUN-CLAIM (0.2.3, Rob 2026-10-14 08:28 PDT): kept in every session too. A sentence saying
    work did not happen ("nothing moved", "didn't run" ...) fails unless a CHECKED line names the
    log, path, doc ID or session ID that was read.
  - TABLE-LAST (0.2.4, Rob 2026-10-14 09:41 PDT, "must apply on every surface"): replycheck.py's
    TABLE-AFTER-REVIEW and REVIEW-FIX-APPLIED are kept in every session too (ALWAYS_ON). And
    TABLE-RESEND, here in the gate: when the previous Stop block in this session blocked a reply that
    carried a next-steps table, the next Stop reply must carry the whole table again (same header, at
    least as many rows) and a line "TABLE REISSUED". The block message for a reply with a table says
    to resend the whole corrected table instead of CORRECTION: lines alone.
  - 0.2.5 (Rob 2026-10-14 13:36 PDT, "Having two Next Steps tables show up for each reply is confusing"):
    TABLE-RESEND applies only when the block involved the table - a TABLE_SCOPED code, a 'line N' or quoted
    evidence that sits in a table row, or a RATING-* code whose rating sits in a row. A prose-only block says
    "The table above passed; do NOT resend it." and TABLE-DUPLICATE fails a same-turn reply that repeats
    that table. PRECHECK: checker/precheck.py stamps a draft's normalized sha256 in
    ~/.claude/imc-reply-gate-prechecked.tsv when replycheck.py passes it with REPLYCHECK_DRAFT set; a reply
    with a table matching a stamp logs precheck-matched and skips its table-scoped failures; no stamp logs
    a non-blocking PRECHECK-MISSING warn.
  - 0.2.6 (Rob 2026-10-14 21:32 PDT, R285 row 2, "No, I want the pre-check"): PRECHECK-MISSING now BLOCKS in
    every session. On SendUserMessage the hook runs before the tool, so the unchecked table never reaches Rob.
    On Stop the table is already on screen, so the block asks for one CORRECTION line flagging it and forbids
    resending the table (a second table is what Rob called confusing).
  - 0.2.12 (Rob 2026-10-16 10:41 PDT, "blocks only deliverables and replies that ask me to decide"):
    GATING. A reply is checked, and can be blocked, only when it is a deliverable or asks Rob to decide.
    Every other reply is let through with a log line (why "ungated status reply") and the checker is not
    run on it. DELIVERABLE = this turn (after the newest real user prompt; Stop-hook feedback and isMeta
    entries are not prompts) called SendUserFile, Artifact with action publish (or none), a Claude Docs
    create/update/batch, Projects/project_write with present_to_user true, Gamma generate, Drive
    create_file, or Gmail create_draft/send_message. A PushNotification is gated by asks only. ASKS ROB TO
    DECIDE = a table row whose Owner cell names Rob (any table with an Owner column), a request phrase
    (ASK_RE), or a prose line ending in "?". A reply is also gated while a block armed in the last 10
    minutes is pending for its session (the resend and duplicate rules need it), and when the detector
    errors (it fails closed). STATUS_KEEP lists codes still enforced on ungated replies; it ships empty.
    IMC_GATE_ALL=1 in the hook's environment restores the 0.2.11 behaviour (every reply gated).
  - 0.2.39 (Rob 2026-10-23 07:44 PDT): turn_key ignores Stop-hook feedback, so the block cap of 2 now bites;
    a tableless closing note after a DELIVERED SendUserMessage that carried a real table (not blocked, not a quoted header) is not failed for EVERY-REPLY-TABLE.
  - Stop: checks rewrites too (0.2.2); the per-turn block cap of 2 ends any loop.
  - At most MAX_BLOCKS blocks per session-turn, counted across both modes (0.2.4: state is kept per
    session, so two sessions no longer reset each other's count). A reply let through by the cap is
    logged AND written whole to ~/.claude/imc-reply-gate-unchecked.log, so it is not waved through
    unrecorded.
  - Block = exit 2 with the unwaived FAIL lines on stderr.
  - Any error inside this hook (missing file, bad JSON, crash, checker timeout) = allow and log.
  - Every decision is logged to ~/.claude/imc-reply-gate.log.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(ROOT, "checker", "replycheck.py")
# replycheck.py codes kept in EVERY session (0.2.1 RATING-CLOSABLE, 0.2.3 NOT-RUN-CLAIM,
# 0.2.4 TABLE-AFTER-REVIEW and REVIEW-FIX-APPLIED).
ALWAYS_ON = ("RATING-CLOSABLE", "NOT-RUN-CLAIM", "TABLE-AFTER-REVIEW", "REVIEW-FIX-APPLIED",
             "CON-FORMAT", "ID-NAME", "OBJECTIVE-SECTIONS", "SITE-FAULT", "SELFCHECK", "ROOTCAUSE",
             "RANK-STRUCT", "PREVENTS", "HOLLOW-BLOCKED", "HANDOFF-UNTESTED", "INCOMPLETE", "DEFERRED-WORK", "RATING-INFLATED", "ABSENCE-CLAIM", "REVIEW-LINK", "VERIFY-ANSWER", "PROMISE-OPEN", "DONE-NO-CALL", "ENDS-ON-INTENT", "REC-NOT-TESTED", "NOTHING-LEFT-CLAIM")  # 0.3.37 adds DONE-NO-CALL  # 0.3.0 universal core, Rob 2026-10-23 09:40 PDT  # 0.2.25 ROOTCAUSE, OI-0271  # 0.2.14 SITE-FAULT, F-594  # 0.2.7: R287, Rob 2026-10-15 10:04 PDT, every session
WAIVERS = os.path.join(ROOT, "checker", "waivers.txt")
LOG = os.path.expanduser("~/.claude/imc-reply-gate.log")
STATE = os.path.expanduser("~/.claude/imc-reply-gate.state.json")
UNCHECKED_LOG = os.path.expanduser("~/.claude/imc-reply-gate-unchecked.log")
MAX_SESSIONS = 50
# 0.2.4 TABLE-LAST: the next-steps header Rob ruled 2026-10-04, matched as replycheck.py matches it.
NEXT_STEPS_HEADER = re.compile(
    r"^\|\s*#\s*\|\s*Issue\s*/\s*Risk\s*\|\s*Action\s*\|\s*Owner\s*\|\s*(?:Claude[’']s\s+)?Recommendation\s*\|"
    r"\s*Pros\s*\|\s*Cons\s*\|\s*$", re.I)
REISSUED = re.compile(r"^\s*\**\s*TABLE REISSUED\b", re.M)
# 0.2.5 (Rob 2026-10-14 13:36 PDT, "Having two Next Steps tables show up for each reply is confusing"):
# codes whose failure lives in the next-steps table. Only a block that involves the table asks for a resend.
TABLE_SCOPED = ("ONE-DECISION", "REVIEW-LINK", "OPEN-ROW-LINK", "TABLE-SHAPE", "TABLE-AFTER-REVIEW", "REVIEW-FIX-APPLIED", "CON-FORMAT", "OBJECTIVE-SECTIONS",
                "EXCEPTION-REJECTED", "RANK-DEPENDENCY", "RANK-STRUCT", "PREVENTS", "STANDING-ROWS", "TEST-FIELD", "GATE-RATIO", "TABLE-RESEND", "SELFCHECK", "ROOTCAUSE")
RATING_IN_ROW = re.compile(r"\b\d{1,2}\s*/\s*10\b|\bconfidence\b", re.I)
PRECHECKED = os.path.expanduser("~/.claude/imc-reply-gate-prechecked.tsv")


def sandbox_fallbacks(name):
    """0.4.7 (Rob 2026-11-25, Mac Claude Code): a sandboxed Bash on the Mac cannot write under ~/.claude (measured: the
    stamp command raised "PermissionError: [Errno 1] Operation not permitted: '~/.claude/imc-preaction/6068fe85-....json'"
    at 13:38:52 PST), so precheck and the pre-action stamp could not record anything and every write was refused. Writers
    that run inside the sandbox fall back to these paths; the hooks, which run outside it, read them too. Only folders
    owned by this user count, so another account cannot plant a stamp."""
    import glob as _g
    uid = os.getuid() if hasattr(os, "getuid") else -1
    roots = ["/tmp/claude-%d" % uid, "/private/tmp/claude-%d" % uid]
    if os.environ.get("TMPDIR"):
        roots.insert(0, os.environ["TMPDIR"].rstrip("/"))
    out = []
    for r in roots:
        for c in [os.path.join(r, name)] + _g.glob(os.path.join(r, "*", name)) + _g.glob(os.path.join(r, "*", "*", name)):
            try:
                if os.path.realpath(c) not in [os.path.realpath(x) for x in out] and \
                        (not os.path.exists(c) or os.stat(c).st_uid == uid):
                    out.append(c)
            except OSError:
                pass
    return out


def prechecked_files():
    return [PRECHECKED] + [c for c in sandbox_fallbacks("imc-reply-gate-prechecked.tsv") if os.path.isfile(c)]


def prechecked_lines():
    for fp in prechecked_files():
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for ln in f:
                    yield ln
        except OSError:
            continue
MAX_BLOCKS = 2
PUSH_MAX = 1000  # 0.3.67: a table-less PushNotification up to this many characters is an alert, not a reply
PROGRESS_MAX = 400  # 0.3.3: a table-less SendUserMessage up to this many characters is a progress line
PLAIN_STAMP = True  # 0.3.88 (Rob 2026-11-24, "stamp everything", OI-0727): a table-less reply or notification longer than PROGRESS_MAX needs a precheck stamp again; this undoes 0.3.28 (OI-0405 option A).
SENT_DIR = os.path.expanduser("~/.claude/imc-reply-gate-sent")
CHECK_TIMEOUT = 75
# The marker as it appears raw and as it appears JSON-escaped inside a .jsonl transcript line.
MARKERS = (
    'This session is attached to the Project **"AI Prompt Library"**',
    'This session is attached to the Project **\\"AI Prompt Library\\"**',
    'This session is attached to the Project **"Improving my Claude (Overall)"**',
    'This session is attached to the Project **\\"Improving my Claude (Overall)\\"**',
)
# PushNotification only: AI Prompt Library tasks that push but carry no project marker. Each string
# is the opening of that task's stored prompt or SKILL.md, read live 2026-10-05. Audit item 26.
PUSH_MARKERS = (
    "Read-only watchdog for Rob's AI Prompt Library",          # 3 WATCHDOG (cloud)
    "TASK: Alert Rob if this Sunday's watchdog run failed",     # Watchdog run check (cloud)
    "Run Rob's AI Prompt Library preflight on this Mac",       # preflight [local, Saturdays]
    "name: instagram-weekly-capture",                          # 1 CAPTURE (desktop)
    "name: prompt-library-triage",                             # 2 TRIAGE (desktop)
)


INCOMPLETE_TERMS = [
    r"not fully", r"not done", r"caveats?", r"partly done", r"partially (?:done|read|checked|reviewed|verified)",
    r"not checked", r"still remains?", r"nobody checked", r"not compared", r"not verified", r"unverified",
    r"(?:did not|didn't|have not|haven't|has not|hasn't) (?:yet )?(?:read|check|checked|verify|verified|compare|compared|open|opened|review|reviewed|test|tested)",
    r"not (?:yet )?(?:read|reviewed|opened|confirmed|tested)", r"untested", r"skimmed", r"spot[- ]check(?:ed)?",
    r"could not (?:verify|confirm|check|read)", r"couldn't (?:verify|confirm|check|read)", r"left unchecked",
    r"not exhaustive", r"not thorough", r"incomplete", r"not (?:yet )?(?:measured|re-?measured)",
]
INCOMPLETE_RE = re.compile(r"(?<![-\w])\b(?:" + "|".join(INCOMPLETE_TERMS) + r")\b(?!-)", re.I)  # 0.3.21: a hyphenated check name such as HANDOFF-UNTESTED is not an admission


def _strip_quoted(line):
    line = re.sub(r"`[^`]*`", " ", line)
    line = re.sub(r"\u201c[^\u201d]*\u201d", " ", line)
    line = re.sub(r'"[^"\n]*"', " ", line)
    return line


BLOCKED_TAG = re.compile(r"BLOCKED:\s*(.*)")
# A reason must name a failed call or error, or a decision that is Rob's (F-531, 2026-10-11).
REAL_REASON = re.compile(
    r"\b(?:refus\w*|error\w*|fail\w*|returned|rc\s*=?\s*\d|exit(?:ed)?\s*\d|denied|timed? ?out|unreachable|"
    r"not (?:available|reachable|connected|installed|allowed|permitted)|no (?:tool|access|route|connector)|"
    r"cannot reach|can't reach|missing|404|403|401|500|"
    r"rob|your (?:decision|call|ruling|approval|reply|yes|choice|go)|yours|approv\w*|ruling|row \d+|"
    r"credential|password|sign[- ]in|physical|upload|restart)\b", re.I)
HOLLOW = re.compile(r"^\s*(?:none|n/?a|nothing|-+|tbd|na|no blocker\w*|not applicable)?\s*[.;:]?\s*$", re.I)


# 2026-10-18 (ported onto 0.2.23 on 2026-10-19 from the gt15 build): a reason that admits the work was simply
# not done is not a blocker. On 2026-10-18 22:28 PDT a reply carried "BLOCKED: I have not opened
# .gate-failures-last.txt yet" and passed because the same sentence also named "your instruction". The file was
# one command away and held 17 defects the reply had counted as 4.
SELF_ADMITTED = re.compile(
    r"\b(?:(?:have|has|had) not|haven't|hasn't|did not|didn't|not yet|never)\s+"
    r"(?:\w+\s+){0,2}?(?:open(?:ed)?|read|run|ran|check(?:ed)?|look(?:ed)?|measure[d]?|search(?:ed)?|try|tried|tested)\b" + "|" + "|".join((
    # 0.2.37 (Rob 2026-10-22 9:26 PM): the same admission in the passive or the file-absence form. "BLOCKED: the call
    # list_triggers page 2 was not made, and the O3 session id is in no file I read" passed 0.2.36 because neither
    # phrase matched; both are a choice not to look, not a blocker.
    r"\b(?:was|were|is|are|remain(?:s)?|stay(?:s)?)\s+(?:not|never|still not|yet to be)\s+(?:\w+\s+){0,2}?(?:made|open(?:ed)?|read|run|ran|check(?:ed)?|look(?:ed)?|measure[d]?|search(?:ed)?|tested|done)\b",
    r"\bin no (?:file|doc|document|page|report)\b",
    r"\b(?:left|leaves|deferred|saved) (?:for|to) (?:the |this |that |those |these |next )?(?:\w+ ){0,3}?(?:turn|first actions?|next|later|row)\b",
)), re.I)


# A reason that NAMES a failed call or error (refused, returned, error, denied, rc=, 404 ...) stays a real blocker
# even if it also says what was not tried afterwards; found in the 2026-10-19 port test, where the gt15 form
# turned two truthful blockers ("was refused ... I did not try the other two") into failures.
FAILED_CALL = re.compile(
    r"\b(?:refus\w*|returned|rc\s*=?\s*\d|exit(?:ed)?\s*\d|denied|timed? ?out|unreachable|"
    r"cannot reach|can't reach|40[134]|500)\b", re.I)  # no bare error/fail: '.gate-failures-last.txt' is a file name


def blocked_ok(line):
    """True when the line carries BLOCKED: with a real reason."""
    m = BLOCKED_TAG.search(line)
    if not m:
        return False
    reason = m.group(1)
    if SELF_ADMITTED.search(reason) and not FAILED_CALL.search(reason):
        return False
    return not HOLLOW.match(reason) and bool(REAL_REASON.search(reason))


def hollow_fails(text):
    """F-531. One FAIL per BLOCKED: line whose reason names no failed call, error, or decision of Rob's."""
    out, fence = [], False
    for i, raw in enumerate(text.splitlines()):
        if raw.strip().startswith("```"):
            fence = not fence
            continue
        if fence or raw.lstrip().startswith(">") or "BLOCKED:" not in _strip_quoted(raw):
            continue
        if not blocked_ok(_strip_quoted(raw)):
            out.append(("HOLLOW-BLOCKED", "line %d: '%s' gives no real reason. Do the work instead, or name the call "
                        "that failed and its error, or the decision that is Rob's." % (i + 1, raw.strip()[:90])))
    return out


def incomplete_fails(text):
    """F-523. One FAIL per line that uses incomplete-review wording without a BLOCKED: reason."""
    out, fence = [], False
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        if raw.strip().startswith("```"):
            fence = not fence
            continue
        if fence or raw.lstrip().startswith(">"):
            continue
        m = INCOMPLETE_RE.search(_strip_quoted(raw))
        if not m:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if blocked_ok(raw) or (nxt.lstrip().startswith("BLOCKED:") and blocked_ok(nxt)):
            continue
        out.append(("INCOMPLETE", "line %d says '%s' with no BLOCKED: reason. Close the gap with a tool call "
                    "before replying, or add 'BLOCKED: <the call that failed and its error, or the decision that "
                    "is Rob's>' on that line or the next." % (i + 1, m.group(0))))
    return out


def log(mode, decision, **kv):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        rec = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               "mode": mode, "decision": decision}
        rec.update(kv)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _already_sent(session, sha):
    try:
        with open(os.path.join(SENT_DIR, (session or "nosession") + ".txt"), encoding="utf-8") as f:
            return any(ln.strip() == sha for ln in f)
    except FileNotFoundError:
        return False


def _mark_sent(session, sha):
    os.makedirs(SENT_DIR, exist_ok=True)
    with open(os.path.join(SENT_DIR, (session or "nosession") + ".txt"), "a", encoding="utf-8") as f:
        f.write(sha + "\n")


def allow(mode, why, **kv):
    log(mode, "allow", why=why, **kv)
    sys.exit(0)


# 0.2.11: any claude.ai Project, not only the two above. replycheck.py then requires PROJECT OBJECTIVE lines
# (SUMMARY-SPEC.md PROJECT OBJECTIVES AND HANDOFFS, Rob 2026-10-15 12:21 PDT).
PROJECT_MARKERS = ("This session is attached to the Project **", "This session is bound to a claude.ai Project")


KAP_UUID = "01a05e74-a45f-756e-8899-a35cce139ab9"  # the Kaprelian doctors claude.ai project uuid (0.3.19)
KAP_ATTACHED = re.compile(r'This session is attached to the Project \*\*\\?"?[^*"]{0,40}aprelian')
KAP_BOUND = re.compile(r'This session is bound to a claude\.ai Project')


def in_kap_project(transcript_path):
    """0.3.20: True when the session's own binding names the Kaprelian doctors project: a transcript entry that carries
    the marker naming Kaprelian (KAP_ATTACHED), or the bound marker with the project uuid (KAP_UUID), and that entry is the
    binding itself. Skipped: assistant messages, tool calls, tool results and typed prompts (a user entry that is not an
    attachment and does not begin with a system-reminder), because they only quote text; a line that is not JSON is skipped.
    0.3.17 and 0.3.18 matched any line (INTAKE F-923); 0.3.19 still counted a typed prompt that quoted the binding."""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not (KAP_ATTACHED.search(line) or (KAP_BOUND.search(line) and KAP_UUID in line)):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(o, dict) or o.get("type") == "assistant":
                    continue
                msg = o.get("message") or {}
                c = msg.get("content")
                if msg.get("role") == "assistant":
                    continue
                if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result") for b in c):
                    continue
                if o.get("toolUseResult"):
                    continue
                if o.get("type") == "user" and not o.get("attachment"):
                    txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict))
                    if not txt.lstrip().startswith("<system-reminder>"):
                        continue
                return True
    except OSError:
        pass
    return False


def in_scope(transcript_path, markers=MARKERS):
    with open(transcript_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if any(m in line for m in markers):
                return True
    return False


def read_entries(transcript_path):
    out = []
    with open(transcript_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def is_tool_result(entry):
    if entry.get("toolUseResult"):
        return True
    c = (entry.get("message") or {}).get("content")
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def turn_key(entries):
    """The newest real user prompt (not a tool result, not a sidechain, not Stop-hook feedback or an isMeta
    entry) marks the turn. 0.2.39 (Rob 2026-10-23 07:44 PDT, "Why is the next steps table being repeated 3 times"):
    this used to count the hook's own feedback as a new prompt, so every block started a new turn, the block
    counter reset to 1 every time and MAX_BLOCKS never ended a loop (measured: 490 of 499 logged blocks had
    n=1). _is_hook_feedback, written for turn_deliverable in 0.2.12, was never applied here."""
    for e in reversed(entries):
        if (e.get("type") == "user" and not e.get("isSidechain") and not is_tool_result(e)
                and not _is_hook_feedback(e)):
            return str(e.get("uuid") or e.get("timestamp") or "unkeyed")
    return "no-user-boundary"


TABLE_HEADER_RE = re.compile(r"(?m)^[ \t]*\|\s*#\s*\|\s*Issue\s*/\s*Risk\s*\|\s*Action\s*\|\s*Owner\s*\|[^\n]*\n[ \t]*\|[ \t:|-]*---")


def turn_sent_table(entries):
    """0.2.39: True when a SendUserMessage in this turn carried a real next-steps table (header line at the
    start of a line followed by the separator row, not a quoted header) AND was delivered (its tool_result is
    not an error and does not say blocked). A blocked or quoted table waives nothing."""
    start = 0
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if (e.get("type") == "user" and not e.get("isSidechain") and not is_tool_result(e)
                and not _is_hook_feedback(e)):
            start = i + 1
            break
    sent = {}
    for e in entries[start:]:
        c = (e.get("message") or {}).get("content")
        if not isinstance(c, list) or e.get("isSidechain"):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if (e.get("type") == "assistant" and b.get("type") == "tool_use"
                    and b.get("name", "").rsplit("__", 1)[-1] == "SendUserMessage"
                    and TABLE_HEADER_RE.search(str((b.get("input") or {}).get("message", "")))):
                sent[b.get("id")] = True
            elif e.get("type") == "user" and b.get("type") == "tool_result" and b.get("tool_use_id") in sent:
                body = json.dumps(b.get("content", ""))
                if b.get("is_error") or "blocked" in body.lower() or "NOTHING WAS SENT" in body:
                    sent[b.get("tool_use_id")] = False
    return any(sent.values())


def newest_prompt_is_human(entries):
    """0.3.90 (OI-0778): True when the newest real user prompt (not a tool result, sidechain, hook feedback or isMeta
    entry) carries origin.kind 'human', so Rob typed it. A scheduled-trigger turn, or an entry with no origin (older
    transcripts and the selftests' fixtures), returns False, so scheduled task replies keep their final-text tables."""
    # REVISED BEFORE UPLOAD (independent review 2026-11-24): _is_hook_feedback skips every task-notification, so a
    # scheduled-trigger prompt that fired into a session Rob had typed in was skipped and Rob's older prompt answered
    # True. A scheduled trigger now ends the walk with False. A compaction summary (isCompactSummary, no origin) is
    # skipped; when it is the oldest entry left, the walk ends False and the check stays silent (known gap).
    for e in reversed(entries):
        if e.get("type") != "user" or e.get("isSidechain") or is_tool_result(e):
            continue
        if (e.get("origin") or {}).get("subkind") == "scheduled-trigger":
            return False
        if e.get("isCompactSummary") or _is_hook_feedback(e):
            continue
        return (e.get("origin") or {}).get("kind") == "human"
    return False


# 0.3.12 (Rob 2026-10-25 06:48 PDT, "why is your reply repeating itself AGAIN"; approved upload 06:59 PDT): the block
# text tells Claude to send "only CORRECTION: lines", and EVERY-REPLY-TABLE then refused those table-less lines, so
# each correction became a second block and a longer chain of replies (measured in the session transcript: the 2 of 2
# block fired on a CORRECTION-only reply). A reply whose every line starts "CORRECTION:" and that follows Stop-hook
# feedback in the same turn is the answer the gate asked for, so it owes no table. Nothing else is waived.
CORRECTION_MAX = 2500
CORR_LINE = re.compile(r"^[\W_]*(?:CORRECTION|BLOCKED):\s*\S")  # 0.3.52: a one-line BLOCKED: after Stop-hook feedback is the reply the hook text asks for (Rob 2026-11-17 8:53 AM PST)


def correction_only(text):
    """True when every non-blank line starts with 'CORRECTION:' (markdown emphasis or a bullet may precede it),
    the text has no next-steps table and is at most CORRECTION_MAX characters."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines or len(text) > CORRECTION_MAX or TABLE_HEADER_RE.search(text):
        return False
    if all(CORR_LINE.match(ln) for ln in lines):
        return True
    # 0.3.84 (OI-0493): the gate's own block message asks for prose naming the failing rows and says
    # "Do NOT resend the table". A reply that does exactly that was then refused by EVERY-REPLY-TABLE,
    # because this test accepted only lines starting CORRECTION: or BLOCKED:. Measured 2026-11-20
    # 09:12 PST: block 1 gave SELFCHECK + INCOMPLETE + PRECHECK-MISSING with that instruction, and the
    # table-less follow-up it asked for was refused, so the turn could not end either way. Stays
    # narrow: short, no table, at most six lines, and it must name a row the way the message asks.
    return len(lines) <= 6 and bool(re.search(r"\brows?\s+\d+", text, re.I))


def turn_has_hook_feedback(entries):
    """True when Stop-hook feedback (the gate's or the reviewer panel's) sits in the current turn, that is, after
    the newest real user prompt. Only then is a correction reply a follow-up to something that was already sent."""
    start = 0
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if (e.get("type") == "user" and not e.get("isSidechain") and not is_tool_result(e)
                and not _is_hook_feedback(e)):
            start = i + 1
            break
    return any(e.get("type") == "user" and not e.get("isSidechain") and not is_tool_result(e) and _is_hook_feedback(e)
               for e in entries[start:])


def task_form_no_table(entries):
    """0.3.65 (Rob 2026-11-18 6:02 PM PST, "WHY DID YOU STOP???", OI-0474): a scheduled task whose own prompt fixes a
    table-less REPLY FORM ("no table") was blocked twice by EVERY-REPLY-TABLE on its 07:34 PST run. True when the
    session's first real user message carries both "REPLY FORM" and "no table"."""
    for e in entries:
        if e.get("type") == "user" and not e.get("isSidechain") and not is_tool_result(e):
            c = (e.get("message") or {}).get("content")
            if isinstance(c, list):
                c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
            t = c if isinstance(c, str) else ""
            return bool(re.search(r"REPLY FORM", t) and re.search(r"\bno table\b", t, re.I))
    return False


def last_assistant_text(entries):
    for e in reversed(entries):
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, str) and c.strip():
            return c
        if isinstance(c, list):
            t = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            if t.strip():
                return t
    return ""


def _load_state():
    """{"sessions": {session_id: {"turn", "blocks", "pending_table", "ts"}}}. 0.2.4: per session, so two
    sessions sharing this file no longer reset each other's block count or pending table."""
    try:
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        st = {}
    if not isinstance(st, dict) or not isinstance(st.get("sessions"), dict):
        st = {"sessions": {}}
    return st


def _save_state(st):
    ss = st["sessions"]
    if len(ss) > MAX_SESSIONS:
        for k in sorted(ss, key=lambda k: ss[k].get("ts", 0))[:len(ss) - MAX_SESSIONS]:
            del ss[k]
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f)


def _sess(st, session):
    s = st["sessions"].setdefault(session, {})
    s.setdefault("turn", None)
    s.setdefault("blocks", 0)
    s.setdefault("pending_table", None)
    s["ts"] = datetime.datetime.now().timestamp()
    return s


def bump(session, key):
    """Count a block for this session-turn; a new turn in the same session resets the count only."""
    st = _load_state()
    s = _sess(st, session)
    if s["turn"] != key:
        s["turn"], s["blocks"] = key, 0
    s["blocks"] += 1
    _save_state(st)
    return s["blocks"]


def get_pending(session):
    return (_load_state()["sessions"].get(session) or {}).get("pending_table")


def set_pending(session, value):
    st = _load_state()
    _sess(st, session)["pending_table"] = value
    _save_state(st)


def table_info(text):
    """(first header line, row count over every next-steps table) outside code fences, or None."""
    lines, fence = text.split("\n"), False
    first, n = None, 0
    for i, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            fence = not fence
            continue
        if fence or not NEXT_STEPS_HEADER.match(ln.strip()):
            continue
        first = first or ln.strip()
        for nxt in lines[i + 1:]:
            s = nxt.strip()
            if not s.startswith("|"):
                break
            if re.match(r"^\|\s*\d+\s*\|", s):
                n += 1
    return (first, n) if first else None  # 0.2.9: rows of every table (R291)


def table_rows(text):
    """Every table row line ('|' first) outside code fences, whitespace-collapsed, in order."""
    out, fence = [], False
    for ln in text.split("\n"):
        if ln.strip().startswith("```"):
            fence = not fence
            continue
        if not fence and ln.strip().startswith("|"):
            out.append(re.sub(r"\s+", " ", ln.strip()))
    return out


def numbered_rows(text):
    """The numbered data rows of every next-steps table, whitespace-collapsed."""
    lines, fence = text.split("\n"), False
    rows = []
    for i, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            fence = not fence
            continue
        if fence or not NEXT_STEPS_HEADER.match(ln.strip()):
            continue
        for nxt in lines[i + 1:]:
            s = nxt.strip()
            if not s.startswith("|"):
                break
            if re.match(r"^\|\s*\d+\s*\|", s):
                rows.append(re.sub(r"\s+", " ", s))
    return rows  # 0.2.9: rows of every table (R291)


# *** 0.2.13 (Rob 2026-10-16 12:43 PDT "WHY ARE THERE TWO NEXT STEPS TABLES????" and 13:02 PDT). ***
# TABLE-START: the next-steps rows of a reply are ONE table numbered from 1 with no gaps or repeats. A reply that
# opens at row 12 is a partial second table, which is the failure Rob raised again on 2026-10-16.
# ROB-OWNS-WORK: a row owned by Rob must ask him for something only he can give - a decision ('reply "..."'), an
# approval, an upload, a sign-in or a physical act. Any other Rob row is work Claude should have investigated to
# its root cause and fixed before showing the table ("I don't need to see something if you can fix it without a
# decision from me"). This is the mechanical half; whether the root cause was really fixed stays JUDGEMENT-ONLY.
ROB_ASK_RE = re.compile(r'reply\s*["\u201c]|\bapprov|\bupload|\bsign in\b|\bsign-in\b|\bpassword|\bcredential|'
                        r'\bpress\b|\bclick\b|\bdecide\b|\bdecision\b|\bscreenshot\b|\bphysical', re.I)


def _cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def table_start_fails(text):
    nums = []
    for r in numbered_rows(text):
        try:
            nums.append(int(_cells(r)[0]))
        except (ValueError, IndexError):
            pass
    if not nums:
        return []
    want = list(range(1, len(nums) + 1))
    if nums != want:
        return [("TABLE-START", "the next-steps rows run %s; they must be one table numbered 1 to %d with no gap or "
                 "repeat. A table that starts above row 1 is a partial second table: send the whole table once."
                 % (",".join(str(n) for n in nums), len(nums)))]
    return []


def rob_owns_work_fails(text):
    out = []
    for r in numbered_rows(text):
        c = _cells(r)
        if len(c) < 4 or c[3].strip().lower() != "rob":
            continue
        if not ROB_ASK_RE.search(c[2]):
            out.append(("ROB-OWNS-WORK", "row %s is owned by Rob but its Action asks him for no decision, approval, "
                        "upload, sign-in or physical act: '%s'. Investigate the root cause and fix it first; show Rob "
                        "only what needs him." % (c[0], c[2][:90])))
    return out


# *** 0.2.20 (Rob 2026-10-18 1:11 PM PDT, item 10 'Approve', F-657). ***
# ONE-DECISION: "each decision should be on their own line and include the context on those lines so I don't go hunting."
# A Rob-owned row may name only ONE OI- id, and its Issue / Risk cell must hold at least 60 characters, so the context
# rides on the row instead of sitting in a file Rob has to open. Judgement-only remainder: whether the context is the
# RIGHT context.
OI_ID_RE = re.compile(r"\bOI-\d{3,4}\b")


def one_decision_fails(text):
    out = []
    for r in numbered_rows(text):
        c = _cells(r)
        if len(c) < 4 or c[3].strip().lower() != "rob":
            continue
        ids = sorted(set(OI_ID_RE.findall(c[1] + " " + c[2])))
        if len(ids) > 1:
            out.append(("ONE-DECISION", "row %s is owned by Rob and names %d open items (%s). Put each decision on its "
                        "own row with its own context, so Rob does not have to sort one answer out of several."
                        % (c[0], len(ids), ", ".join(ids))))
        elif ids and len(c[1]) < 60:
            out.append(("ONE-DECISION", "row %s names %s but its Issue / Risk cell holds only %d characters. State what "
                        "the decision is and what it affects in the row, so Rob does not have to open a file."
                        % (c[0], ids[0], len(c[1]))))
    return out


EXC_RE = re.compile(
    r"\b(?:grant|granting|add|adding|keep|keeping|approve|approving|allow|allowing|apply|applying|request|requesting|"
    r"recommend|recommending|propose|proposing|raise|raising)\s+(?:an?\s+|the\s+|your\s+)?(?:new\s+|standing\s+)?"
    r"(?:exemption|exception|waiver|baseline)\b|\b(?:waive|exempt)\s+(?:this|the|it|that)\b|"
    r"\blet\s+(?:it|this|that)\s+pass\b|\bpass\s+despite\b", re.I)
EXC_NEG = re.compile(r"(?:\bno|\bnot|\bnever|\bwithout|reject\w*|refus\w*|\bcut|remov\w*|\bfail\w*)\W+(?:\w+\W+){0,3}$", re.I)


# RULING-COVERS-ROW, 0.3.48 (Rob 2026-11-12 12:59 PM PST, "Agree with your recommendation"): a row owned by Rob that asks his
# approval for an action a standing ruling of his already allows is work Claude should run, not a question. ROB-OWNS-WORK
# above tests only the wording of the Action cell. Rulings live in checker/rulings-allow.tsv (pattern, exception, ruling);
# a row is flagged when its Action matches a pattern and its Issue/Action/Recommendation match no exception. WARN MODE:
# ENFORCED from 0.3.50 (Rob 2026-11-12 4:08 PM PST "go"): replay over 20029 replies flagged 13 rows, all before the ruling existed; exceptions widened to run sessions, chats, files and desktop-app tasks.
RULING_COVERS_ENFORCE = True
RULINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "checker", "rulings-allow.tsv")


def ruling_covers_row_fails(text, rulings_file=None):
    out = []
    try:
        rules = []
        for l in open(rulings_file or RULINGS_FILE, encoding="utf-8"):
            if l.strip() and not l.startswith("#"):
                p = l.rstrip("\n").split("\t")
                if len(p) >= 3:
                    rules.append((re.compile(p[0], re.I), re.compile(p[1], re.I) if p[1] else None, p[2]))
    except OSError:
        return out
    for r in numbered_rows(text):
        c = _cells(r)
        if len(c) < 6 or c[3].strip().lower() != "rob":
            continue
        for pat, exc, ruling in rules:
            if pat.search(c[2]) and not (exc and exc.search(" ".join(c[1:3]) + " " + c[4])):
                out.append(("RULING-COVERS-ROW", "row %s asks Rob to approve '%s' but a standing ruling already allows it: %s. "
                            "Run it, or name in the row why the ruling does not cover it." % (c[0], c[2][:80], ruling)))
                break
    return out



# 0.3.54 REC-TEST-RELEVANCE (Rob 2026-11-17 9:15 AM PST: "Are you sure item 1 is required? You better me if you already said it's TESTED"):
# measured 2026-11-17 9:16 AM PST, a row whose Recommendation said "TESTED (`ls` exited 0)" for an unrelated action passed every check, because
# REC-NOT-TESTED and RECO-RUN look only for the word TESTED, a call and a result. This check requires the parenthetical to share at least one
# word stem (5+ letters) with the row's Issue or Action cell, so the named call is about the thing recommended.
_REL_STOP = set("decide whether would should could please about their there which these those after before while where being start starting yes no tested reads read exited returned result results output".split())


REC_RELEVANCE_ENFORCE = False  # 0.3.54: warn-only, 17% of replayed firings were real (Rob 2026-11-17)


def _stems(s):
    return {w[:5] for w in re.findall(r"[a-z]{5,}", s.lower()) if w not in _REL_STOP}


def rec_relevance_fails(text):
    fails = []
    for r in numbered_rows(text):
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        m = re.match(r"TESTED\s*\((.*?)\)\s*:", cells[4])
        if not m:
            continue
        issue_action = _stems(cells[1] + " " + cells[2])
        if issue_action and not (_stems(m.group(1)) & issue_action):
            fails.append(("REC-TEST-RELEVANCE", "row %s says TESTED but the named call shares no word with the issue or action it recommends, so it does not test it: '%s'. Run a test of the thing recommended, or recommend only what the named call shows." % (cells[0], m.group(1)[:90])))
    return fails


def claude_row_runnable_fails(text):
    """0.3.51 CLAUDE-ROW-RUNNABLE (Rob 2026-11-17 8:45 AM PST, 'at what point will you not be stopping'; R7, R26): a next-steps
    row owned by Claude is work Claude can run now, so ending the reply on it is a stop with runnable work. It passes only when
    the row names a BLOCKED reason (a failed call or Rob's decision). Rob-owned rows are not read."""
    out = []
    for r in numbered_rows(text):
        c = _cells(r)
        if len(c) < 6 or c[3].strip().lower() != "claude":
            continue
        if re.search(r"\bBLOCKED\b", " ".join(c[1:5])):
            continue
        out.append(("CLAUDE-ROW-RUNNABLE", "row %s is owned by Claude ('%s'), so the work is runnable now and the reply stops with it undone. "
                    "Run it and report the result, or write BLOCKED: <the failed call or Rob's decision> in the row." % (c[0], c[2][:80])))
    return out


def table_row_fails(text):
    """0.4.11 (Rob 2026-11-25 4:38 PM PST "now", OI-0805): the Stop hook and precheck each listed their own table-row
    checks, so precheck lacked one_decision_fails and exception_fails and stamped a reply the Stop hook then blocked
    on ONE-DECISION (measured 2026-11-25, stamp c4aa6eed92de76ea). Both now call this one list."""
    return (table_start_fails(text) + rob_owns_work_fails(text) + one_decision_fails(text) + exception_fails(text)
            + claude_row_runnable_fails(text))

def exception_fails(text):
    """0.3.2 EXCEPTION-REJECTED (Rob 2026-10-23, 'I don't like exceptions'): a next-steps row whose Action or
    Recommendation recommends an exemption, exception, waiver or baseline raise fails. A row that only names an
    existing waiver for review, or a check that refuses exceptions, passes. Issue / Risk is not read."""
    out = []
    for r in numbered_rows(text):
        c = _cells(r)
        if len(c) < 5:
            continue
        for label, cell in (("Action", c[2]), ("Recommendation", c[4])):
            for m in EXC_RE.finditer(cell):
                if EXC_NEG.search(cell[max(0, m.start() - 40):m.start()]):
                    continue
                out.append(("EXCEPTION-REJECTED", "row %s %s recommends an exception ('%s'). Rob 2026-10-23: no "
                            "exceptions. Fix the cause, or say in the row why it cannot be fixed and ask him to rule."
                            % (c[0], label, m.group(0))))
                break
    return out


_EVIDENCE = re.compile(r"'([^'\n]{6,})'|\"([^\"\n]{6,})\"")


def fail_in_table(code, msg, text):
    """0.2.5. True when this failure involves the next-steps table: a table-scoped code, a 'line N' that is a
    table row, quoted evidence found inside a table row line, or a RATING-* code whose rating sits in a row."""
    if code in TABLE_SCOPED:
        return True
    rows = table_rows(text)
    if not rows:
        return False
    lines = text.split("\n")
    for m in re.finditer(r"\bline (\d+)\b", msg):
        k = int(m.group(1)) - 1
        if 0 <= k < len(lines) and lines[k].strip().startswith("|"):
            return True
    ev = [a or b for a, b in _EVIDENCE.findall(msg)]
    for e in ev:
        e = re.sub(r"\s+", " ", e.strip().rstrip(".").rstrip("…"))
        if len(e) >= 6 and any(e in r for r in rows):
            return True
    if code.startswith("RATING-"):
        prose_has = any(RATING_IN_ROW.search(ln) for ln in lines if not ln.strip().startswith("|"))
        if any(RATING_IN_ROW.search(r) for r in rows) and not prose_has:
            return True
    return False


def table_involved(fails, text):
    return any(fail_in_table(c, m, text) for c, m in fails)


def normalize(text):
    """0.2.5 PRECHECK: trailing whitespace stripped per line, surrounding blank lines dropped."""
    return "\n".join(ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")).strip("\n")


def norm_sha(text):
    import hashlib
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def prechecked(sha):
    return any(ln.split("\t", 1)[0].strip() == sha for ln in prechecked_lines())


def first_diff_hint(text):
    """0.2.16 (Rob 2026-10-17, row 6): when the stamp misses, name the first differing character against the
    closest stamped draft, so nobody retypes a long reply blind. Reads the last 8 stamps' draft files; shows
    code points so a look-alike character is visible."""
    try:
        sent = normalize(text)
        rows = [ln.rstrip("\n").split("\t") for ln in prechecked_lines() if ln.strip()]
        best = None
        for row in rows[-8:]:
            if len(row) < 3 or not os.path.isfile(row[2]):
                continue
            d = normalize(open(row[2], encoding="utf-8", errors="replace").read())
            import difflib
            q = difflib.SequenceMatcher(None, d, sent, autojunk=False).quick_ratio()
            if best is None or q > best[0]:
                best = (q, row[2], d)
        if not best or best[0] < 0.8:
            return " No stamped draft is 80 percent similar to this text; it was probably never prechecked."
        _q, path, d = best
        i, m = 0, min(len(d), len(sent))
        while i < m and d[i] == sent[i]:
            i += 1
        if i == len(d) == len(sent):
            return " The text equals draft %s after normalizing; the stamp file may have changed." % path
        line = sent.count("\n", 0, i) + 1
        col = i - (sent.rfind("\n", 0, i) + 1) + 1
        def cp(s, k):
            return "U+%04X %r" % (ord(s[k]), s[k]) if k < len(s) else "end of text"
        return (" Closest stamped draft: %s. First difference at character %d (line %d, column %d): sent %s, draft %s."
                " Sent context %r; draft context %r. Fix that spot and send the stamped text unchanged."
                % (path, i, line, col, cp(sent, i), cp(d, i), sent[max(0, i - 30):i + 30], d[max(0, i - 30):i + 30]))
    except Exception as e:
        return " (first-difference lookup failed: %s)" % e


SESSION_POINTER = (
    "IMC-REPLY-GATE (SessionStart, source=%s). A pointer, not the rules: a reply that asks Rob to decide carries ONE "
    "next-steps table, sent last, under the header\n"
    "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n"
    "Before sending it: write the draft to a file, have an independent reviewer read that file, run "
    "python3 %s/checker/precheck.py <draft>, and send the stamped text unchanged. The gate refuses any difference "
    "and names the first differing character. Do not rebuild a table from a compacted summary: re-read the newest "
    "NEXT-STEPS document in the project. Stop only when a decision of Rob's is waiting. The five objectives are the "
    "\"PROJECT OBJECTIVE <n> - <name> [status]\" lines of the newest table.")


def _plugin_version():
    """Version of the installed plugin, read from .claude-plugin/plugin.json at run time so the banner cannot differ
    from it (0.3.64; Rob 2026-11-18: no hard-coded version). Falls back to 'unknown' if the file cannot be read."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "unknown")
    except Exception:
        return "unknown"


PROMPT_REMINDER = (
    "IMC-REPLY-GATE (every user turn, " + _plugin_version() + "; Rob 2026-10-24 20:25 PDT: corrections must come BEFORE the table). "
    "The gate acts after text is on Rob's screen (README, measured 2026-10-02), so only your own pre-send steps keep a "
    "correction ahead of a table. A reply that carries a next-steps table is: written to a draft file, read by one "
    "independent reviewer (run_in_background false), fixed from the findings, stamped by checker/precheck.py, then sent "
    "once as the stamped text, with every correction above the table and no second table. Never send a table first and "
    "correct it afterwards. Ask the reviewer to open its RECOMMENDATION-CHECK line with SUPPORTED or NOT SUPPORTED; "
    "precheck refuses a table whose review does not open with SUPPORTED (0.4.12, OI-0808), so fix and re-review, or "
    "withdraw the RECOMMEND. Precheck, in THIS session, is: python3 \"" + os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "checker", "precheck.py") + "\" <draft> "
    "(0.3.71: the absolute path is printed every turn because the plug-in folder can be renamed mid-session, for "
    "example to imc-reply-gate~g2 after an update, and because the SessionStart pointer is skipped at startup; "
    "measured 2026-11-19 in the Disability Claim session \"Plaud export and Drive cleanup\", which said the checker was "
    "not in its container when it was).")


def promptreminder(payload):
    """UserPromptSubmit. Prints PROMPT_REMINDER into the model's context on every user turn, in every session
    the plugin loads in (not only project sessions): the 2026-10-17 to 2026-10-24 failures were a retrieval failure, the
    rule existed in memory and was not consulted at send time."""
    log("prompt", "note", detail="reminder printed", session=str(payload.get("session_id", "")))
    print(PROMPT_REMINDER)
    try:  # 0.3.23: an open promise from an earlier reply of this session
        pr = _load_promises().get(str(payload.get("session_id", "")))
        if pr:
            print("IMC-REPLY-GATE OPEN PROMISE (kept open with a BLOCKED: line at %s): %s. Deliver it, or write CANCELLED: and the reason, in your next reply." % (pr.get("ts", "?"), pr.get("text", "")))
    except Exception:
        pass
    sys.exit(0)


def sessionstart(payload):
    """0.2.16 (Rob 2026-10-17, row 5): re-print the pointer after compaction, resume and startup in project sessions."""
    source = str(payload.get("source", ""))
    tp = payload.get("transcript_path") or ""
    try:
        scoped = bool(tp) and in_scope(tp, PROJECT_MARKERS)
    except Exception:
        scoped = False
    if not scoped:
        allow("sessionstart", "not a project session", source=source)
    root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(SESSION_POINTER % (source or "?", root))
    log("sessionstart", "note", detail="pointer printed", source=source)
    sys.exit(0)


def duplicate_fails(text, pending, key):
    """0.2.5 TABLE-DUPLICATE. The previous reply was blocked for prose only; its table passed and is already on
    Rob's screen. A reply in the same turn that repeats that table (same header, any of its rows verbatim) fails."""
    if not pending or pending.get("involved", True) or pending.get("turn") != key:
        return []
    old = set(pending.get("rows_text") or [])
    new = numbered_rows(text)
    if not table_info(text) or not old or not (old & set(new)):
        return []
    return [("TABLE-DUPLICATE", "the previous reply in this session was blocked for its prose only; its "
             "next-steps table passed and is already on Rob's screen, and this reply repeats it (%d of %d rows "
             "verbatim). Send NO further text this turn: no CORRECTION line, no second table. Put the corrected wording at the top of your next reply, above its one table. Do NOT resend the table."
             % (len(old & set(new)), len(old)))]


def resend_fails(text, pending):
    """0.2.4 TABLE-RESEND. The blocked reply carried a table; this one must carry it whole again.
    0.2.5: only when that block involved the table (state written before 0.2.5 has no flag = involved)."""
    # 0.2.19 (Rob 2026-10-17 9:57 PM PDT): "one set of tables per reply ... should not repeat themselves in the
    # same reply". A block fires after the table is already on screen, so demanding the whole table again put a
    # second copy in front of Rob. The block message now asks for CORRECTION lines; the corrected table goes
    # out once, in the next regular reply.
    return []
    if not pending or not pending.get("involved", True):
        return []
    want = int(pending.get("rows") or 0)
    ti = table_info(text)
    probs = []
    if not ti:
        probs.append("carries no next-steps table")
    elif ti[1] < want:
        probs.append("carries %d table rows against %d in the blocked reply" % (ti[1], want))
    if not REISSUED.search(text):
        probs.append("has no 'TABLE REISSUED' line")
    if not probs:
        return []
    return [("TABLE-RESEND", "the previous reply in this session was blocked while it carried a next-steps table "
             "of %d rows, and this reply %s. Resend the WHOLE corrected table (header '| # | Issue / Risk | "
             "Action | Owner | Claude's Recommendation | Pros | Cons |', at least %d rows) with a line "
             "'TABLE REISSUED'." % (want, "; ".join(probs), want))]


def write_unchecked(mode, session, key, n, src, fails, text):
    """0.2.4: a reply let through by the block cap is kept whole, so the cap does not hide it."""
    try:
        os.makedirs(os.path.dirname(UNCHECKED_LOG), exist_ok=True)
        rec = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "mode": mode,
               "session": session, "turn": key, "n": n, "source": src, "fails": fails, "text": text}
        with open(UNCHECKED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=True) + "\n")
    except Exception:
        pass


# 0.2.12 GATING (Rob 2026-10-16 10:41 PDT).
GATE_ALL = os.environ.get("IMC_GATE_ALL") != "0"  # 0.3.18 CHANGE 1: every reply gated unless IMC_GATE_ALL=0
STATUS_KEEP = ("SITE-FAULT", "SELFCHECK", "VERIFY-ANSWER", "PROMISE-OPEN")  # codes still enforced on an ungated reply (0.2.14: SITE-FAULT, F-594)
# 0.2.29 (Rob 2026-10-20 5:15 PM PDT, F-684): these four run on every reply in every session. Until WATCH_UNTIL they only
# log a STATUS-WATCH line (the refusals are counted from the log); from WATCH_UNTIL they block like any kept code.
STATUS_WATCH = ("OPENER", "AGREEMENT", "HYPE", "STOP-WHILE-UNBLOCKED", "EVERY-REPLY-TABLE")  # 0.2.31 adds EVERY-REPLY-TABLE (row 46)
WATCH_UNTIL = datetime.datetime(2026, 10, 22, 21, 30)  # Pacific; 0.2.37 ends the watch early (Rob 2026-10-22 9:21 PM, O3 replies had no table and no review)


def _now():
    v = os.environ.get("IMC_GATE_NOW")  # test hook only
    return datetime.datetime.fromisoformat(v) if v else datetime.datetime.now()


def watching():
    return _now() < WATCH_UNTIL
PENDING_FRESH_S = 600  # a block armed longer ago than this no longer gates an unrelated reply
ASK_RE = re.compile("|".join((
    r"\b(?:reply|respond|answer|tell me)\s+(?:[\"“'`]|yes\b|no\b|with\b|which\b|approve\b|agree\b)",
    r"\b(?:needs?|awaits?|requires?|waiting (?:on|for)|pending|for) (?:your|Rob['’]s) (?:decision|call|approval|ruling|go-ahead|answer|choice)\b",
    r"\b(?:your|Rob['’]s) (?:decision|call|approval|ruling|go-ahead|answer|choice) (?:is|are) (?:needed|required)\b",
    r"\bI need (?:a|your) (?:decision|approval|answer|ruling|choice)\b",
    r"\bdecision (?:that )?is (?:Rob['’]s|yours)\b",
    r"\bshould I\b", r"\bdo you want\b", r"\bwant me to\b", r"\bwould you like\b",
    r"\bplease (?:confirm|choose|pick|approve|decide|advise)\b", r"\bpick one\b",
    r"\bNO-ARTIFACT:",
)), re.I)
ROB_RE = re.compile(r"\brob\b", re.I)
DELIVERABLE_SUFFIXES = ("Google_Drive__create_file", "Gmail__create_draft", "Gmail__send_message")


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def asks_rob(text):
    """Why this reply asks Rob to decide ('' when it does not): a table row whose Owner cell names Rob (any
    table with an Owner column), a request phrase, or a prose line ending in a question mark. Code fences and
    quote lines are ignored; so are table rows for the phrase and question tests."""
    fence, owner_idx = False, None
    for ln in text.split("\n"):
        s = ln.strip()
        if s.startswith("```"):
            fence, owner_idx = not fence, None
            continue
        if fence or s.startswith(">"):
            continue
        if s.startswith("|"):
            cells = _cells(s)
            low = [re.sub(r"[*_`]", "", c).strip().lower() for c in cells]
            if owner_idx is None:
                if "owner" in low:
                    owner_idx = low.index("owner")
                continue
            if set(s) <= set("|-: "):
                continue
            if owner_idx < len(cells) and ROB_RE.search(re.sub(r"[*_`]", "", cells[owner_idx])):
                return "Rob-owned table row"
            continue
        owner_idx = None
        if ASK_RE.search(ln):
            return "ask line"
        core = _strip_quoted(ln).rstrip().rstrip("*_`)]  ")
        if core.endswith("?"):
            return "question line"
    return ""


def _is_notification(e):
    """0.3.22 (Rob 2026-10-28 10:24 and 10:26 PDT, 'Why are you running in a loop... fix it in the guard / gate'). A
    background-task event (Monitor, Agent hand-back) reaches the transcript as a user entry whose origin.kind is
    'task-notification'. turn_key and turn_key_of counted each one as a new prompt from Rob, so the per-turn block cap
    (MAX_BLOCKS) and the panel round cap (MAX_ROUNDS) reset on every wake-up and never ended the loop."""
    o = e.get("origin")
    return isinstance(o, dict) and o.get("kind") == "task-notification"


def wakeup_reply(entries):
    """0.3.22: True when the newest user entry that is not a tool result, sidechain, meta entry or Stop-hook feedback is
    a task notification, i.e. this reply answers a background wake-up and not a message from Rob."""
    for e in reversed(entries):
        if e.get("type") != "user" or e.get("isSidechain") or e.get("isMeta") or is_tool_result(e):
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, list):
            c = " ".join(str(b.get("text", "")) for b in c if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(c, str) and c.lstrip().lower().startswith("stop hook feedback"):
            continue
        return _is_notification(e)
    return False


def _is_hook_feedback(e):
    """Stop-hook feedback and meta entries sit in the transcript as user entries but are not Rob's prompts."""
    if e.get("isMeta"):
        return True
    if _is_notification(e):  # 0.3.22: a background-task wake-up is not a new prompt from Rob
        return True
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list):  # 0.2.39: list-form content carries hook feedback too
        c = " ".join(str(b.get("text", "")) for b in c if isinstance(b, dict) and b.get("type") == "text")
    return isinstance(c, str) and c.lstrip().lower().startswith("stop hook feedback")


def _deliverable_call(name, inp):
    base = name.rsplit("__", 1)[-1]
    if base == "SendUserFile":
        return True
    if base == "Artifact":
        return inp.get("action", "publish") == "publish"
    if base in ("Projects", "project_write"):
        method = inp.get("method", "project_write" if base == "project_write" else "")
        return method == "project_write" and inp.get("present_to_user") is True
    if "Claude_Docs__" in name:
        return base in ("create", "update", "batch")
    if "Gamma__generate" in name:
        return True
    return any(name.endswith(x) for x in DELIVERABLE_SUFFIXES)


def turn_deliverable(entries):
    """Name of the first deliverable tool call made after the newest real user prompt, or ''."""
    start = 0
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if (e.get("type") == "user" and not e.get("isSidechain") and not is_tool_result(e)
                and not _is_hook_feedback(e)):
            start = i + 1
            break
    for e in entries[start:]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        c = (e.get("message") or {}).get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_use" and _deliverable_call(b.get("name", ""), b.get("input") or {}):
                return b.get("name", "")
    return ""


def gating(session, tp, text, tool=None):
    """(gated, why). Fails closed: any error means gated, which is the 0.2.11 behaviour."""
    if GATE_ALL:
        return True, "IMC_GATE_ALL=1"
    try:
        why = asks_rob(text)
        if why:
            return True, "asks Rob to decide: " + why
        p = get_pending(session)
        if p:
            at = p.get("at")
            if at is None or datetime.datetime.now().timestamp() - float(at) < PENDING_FRESH_S:
                return True, "block pending for this session"
            set_pending(session, None)
        if tp and tool != "PushNotification":
            d = turn_deliverable(read_entries(tp))
            if d:
                return True, "deliverable: " + d
        return False, "ungated status reply"
    except Exception as e:
        return True, "gating error, fail closed: %s" % e


def waived():
    codes = set()
    with open(WAIVERS, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                codes.add(ln)
    return codes


FIX_WORDS = re.compile(r"\b(?:fix(?:es|ed)?|broken|fail(?:s|ed|ure)?|refus\w*|wrong|error\w*|defect\w*|drift|stalls?|regress\w*|bug)\b", re.I)
ROOT_LINE = re.compile(r"^\s*ROOT CAUSE:\s*(.*)$")


def rootcause_fails(text):
    """0.2.22 (Rob 2026-10-18 4:26 PM PDT: root causes before recommendations, ALWAYS). A reply whose next-steps
    table proposes a fix (a row whose Issue / Risk or Recommendation uses failure or fix wording) must carry one
    'ROOT CAUSE: <what caused it, and the CHECKED line that shows it>' line, or 'ROOT CAUSE: none - <why this is
    new work and not a repair>' with a reason of at least 20 characters. The check proves the line exists and is
    not hollow; whether the cause is true is the reviewer's and the CHECKED line's job."""
    fix_row, fence, roots = False, False, []
    for raw in text.splitlines():
        if raw.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = ROOT_LINE.match(raw)
        if m:
            roots.append(m.group(1).strip())
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if raw.lstrip().startswith("|") and len(cells) >= 7 and cells[0].isdigit():
            if FIX_WORDS.search(_strip_quoted(cells[1] + " " + cells[4])):
                fix_row = True
    if not fix_row:
        return []
    for r in roots:
        body = re.sub(r"^none\s*-\s*", "", r, flags=re.I) if r.lower().startswith("none") else r
        if len(body) >= 20 and not HOLLOW.match(body):
            return []
    return [("ROOT-CAUSE", "a table row proposes a fix but the reply has no 'ROOT CAUSE:' line of at least 20 "
             "characters. Name what caused the problem and where it was checked, or write 'ROOT CAUSE: none - "
             "<why this is new work, not a repair>'. Rob 2026-10-18: root causes before recommendations, always.")]


def _gap_fails(text):
    return incomplete_fails(text) + hollow_fails(text) + rootcause_fails(text)


# ---- 0.3.23 (Rob 2026-10-28 20:08 and 20:45 PDT: "have you investigated the root causes? have you measured and tested" was
# answered No, and "I will send a corrected table only after that" was never kept; OI-0416, INTAKE F-976, ruling R412).
# MEASURED CAUSE: no check read the newest user message or stored a promise, and replycheck.deferred_sentences returned []
# for both sentences. Two checks, kept in every session the plug-in loads in. They prove that tool calls and CHECKED lines
# exist, not that the claims are right.
PROMISES = os.path.expanduser("~/.claude/imc-reply-gate-promises.json")
VERIFY_Q = re.compile(r"\b(?:have|did|do|are|were|was)\s+you\b[^?\n]{0,100}?\b(?:investigat\w*|measur\w*|test\w*|verif\w*|validat\w*|root[- ]cause\w*)[^?\n]{0,100}\?", re.I)
NO_OPEN = re.compile(r"^[\s>*_`#\-]*(?:No\b(?![-\w])|I\s+(?:did\s+not|have\s+not|haven['’]t|didn['’]t)\b|Not\s+yet\b)", re.I)
PROMISE_RE = re.compile(r"\b(?:I(?:['’]ll|\s+will|\s+am\s+going\s+to))\s+(?:send|resend|post|give|provide|produce|share|write|deliver)\b[^.\n]{0,80}?\b(?:table|report|list|draft|document|summary|reply|answer|update)\b", re.I)
SYS_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S | re.I)


def _entry_text(e):
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list):
        c = " ".join(str(b.get("text", "")) for b in c if isinstance(b, dict) and b.get("type") == "text")
    return c if isinstance(c, str) else ""


def _turn_after_prompt(entries):
    """(prompt text, entries after it) for the newest real user prompt, or ("", [])."""
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if (e.get("type") == "user" and not e.get("isSidechain") and not is_tool_result(e) and not _is_hook_feedback(e)):
            return SYS_REMINDER.sub(" ", _entry_text(e)), entries[i + 1:]
    return "", []


def _tool_calls(turn):
    n = 0
    for e in turn:
        c = (e.get("message") or {}).get("content") if e.get("type") == "assistant" and not e.get("isSidechain") else None
        if isinstance(c, list):
            n += sum(1 for b in c if isinstance(b, dict) and b.get("type") == "tool_use")
    return n


TABLE_REF_RE = re.compile(r"(?i)\b(?:the table (?:above|i sent|sent)|table above|above table|sent without its pre-?check)\b")


def turn_table_state(entries):
    """0.3.25: (attempted, delivered) for next-steps tables sent by SendUserMessage after the newest real prompt.
    attempted counts every call whose message carried a table; delivered counts those whose tool_result is not an
    error and does not say blocked / NOTHING WAS SENT. A table in an assistant text block counts as delivered."""
    start = 0
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if (e.get("type") == "user" and not e.get("isSidechain") and not is_tool_result(e)
                and not _is_hook_feedback(e)):
            start = i + 1
            break
    sent, attempted, delivered = {}, 0, 0
    for e in entries[start:]:
        c = (e.get("message") or {}).get("content")
        if not isinstance(c, list) or e.get("isSidechain"):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if e.get("type") == "assistant" and b.get("type") == "text" and TABLE_HEADER_RE.search(str(b.get("text", ""))):
                delivered += 1
            elif (e.get("type") == "assistant" and b.get("type") == "tool_use"
                    and b.get("name", "").rsplit("__", 1)[-1] == "SendUserMessage"
                    and TABLE_HEADER_RE.search(str((b.get("input") or {}).get("message", "")))):
                sent[b.get("id")] = True
                attempted += 1
            elif e.get("type") == "user" and b.get("type") == "tool_result" and b.get("tool_use_id") in sent:
                body = json.dumps(b.get("content", ""))
                if b.get("is_error") or "blocked" in body.lower() or "NOTHING WAS SENT" in body:
                    sent[b.get("tool_use_id")] = False
    delivered += sum(1 for v in sent.values() if v)
    return attempted, delivered


def table_lost_fails(mode, tp, text):
    """TABLE-NOT-SENT (0.3.25): this turn a next-steps table was sent through SendUserMessage and denied, none was
    delivered, and this text is a table-less correction or points at 'the table above'. Rob has no table; correction
    lines about a table he never saw are the failure he reported on 2026-10-29."""
    if mode not in ("pretool", "stop") or not tp or table_info(text):
        return []
    if not (correction_only(text) or TABLE_REF_RE.search(text or "")):
        return []
    try:
        attempted, delivered = turn_table_state(read_entries(tp))
    except Exception:
        return []
    if attempted and not delivered:
        return [("TABLE-NOT-SENT", "a next-steps table was blocked earlier this turn and no table has reached Rob, so a "
                 "CORRECTION: reply or a reference to 'the table above' describes something he has not seen. Send the "
                 "whole corrected table now (draft file, reviewer round, checker/precheck.py, stamped text unchanged), "
                 "or open with BLOCKED: and the check that fails three times.")]
    return []


def answer_fails(mode, entries, text):
    """VERIFY-ANSWER: a newest prompt that asks whether root causes were investigated, or recommendations measured, tested
    or verified, must be answered with the work done and cited, never with a No."""
    if mode == "pretool" and len(text.strip()) <= PROGRESS_MAX:
        return []
    prompt, turn = _turn_after_prompt(entries)
    if not prompt or not VERIFY_Q.search(prompt):
        return []
    if NO_OPEN.match(text.strip()):
        return [("VERIFY-ANSWER", "the newest message from Rob asks whether root causes were investigated or recommendations "
                 "were measured and tested, and this reply opens with a No. A No is not a place to end a turn: do the "
                 "investigation and the measurement now with tool calls, then answer with the result and CHECKED lines "
                 "that name each call and what it returned. If a call is blocked, open with BLOCKED: and the failing call.")]
    has_blocked = re.search(r"(?m)^\W*BLOCKED:", text) is not None
    if not has_blocked and (_tool_calls(turn) == 0 or not re.search(r"(?m)^\W*CHECKED\b", text)):
        return [("VERIFY-ANSWER", "the newest message from Rob asks whether root causes were investigated or recommendations "
                 "were measured and tested. An answer needs tool calls made in this turn and CHECKED lines naming each call "
                 "and what it returned; this reply has %s. Run the checks, then answer." %
                 ("no tool call in this turn" if _tool_calls(turn) == 0 else "no CHECKED line"))]
    return []


def _load_promises():
    try:
        return json.load(open(PROMISES, encoding="utf-8"))
    except Exception:
        return {}


def _save_promises(d):
    try:
        os.makedirs(os.path.dirname(PROMISES), exist_ok=True)
        tmp = PROMISES + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, PROMISES)
    except Exception:
        pass


def promise_fails(mode, session, text):
    """PROMISE-OPEN: a reply that promises a table, report or answer later must deliver it in the same reply, or name the
    blocker on a BLOCKED: line, or withdraw it on a CANCELLED: line. A promise kept open is stored for the next prompt."""
    prose = []
    for ln in text.splitlines():
        if re.match(r"^\s*(?:[-*>]\s*)?(?:\*\*)?(?:CHECKED|CORRECTION)\b|^\s*\|", ln, re.I):
            continue
        prose.append(re.sub(r"\"[^\"\n]{0,300}\"|“[^”\n]{0,300}”|`[^`\n]{0,200}`", " ", ln))
    m = PROMISE_RE.search("\n".join(prose))
    delivered = bool(table_info(text))
    covered = re.search(r"(?m)^\W*(?:BLOCKED|CANCELLED):", text) is not None
    st = _load_promises()
    if mode == "stop":
        if delivered or re.search(r"(?m)^\W*CANCELLED:", text):
            if session in st:
                st.pop(session, None); _save_promises(st)
        elif m and covered:
            st[session] = {"text": m.group(0)[:120], "ts": str(_now())[:16]}; _save_promises(st)
    if m and not delivered and not covered:
        return [("PROMISE-OPEN", "this reply promises something for later (a table, report, list, draft or answer) and neither "
                 "delivers it, nor names the blocker on a BLOCKED: line, nor withdraws it on a CANCELLED: line. Do the work "
                 "now and send it, or add a BLOCKED: line that names the decision of Rob's or the failing call.")]
    return []


def answer_promise_fails(mode, tp, session, text):
    out = []
    try:
        entries = read_entries(tp) if tp else []
        out += answer_fails(mode, entries, text)
    except Exception as e:
        log(mode, "note", session=session, detail="answer check failed: %s" % e)
    try:
        out += promise_fails(mode, session, text)
    except Exception as e:
        log(mode, "note", session=session, detail="promise check failed: %s" % e)
    return out


PRECHECK_SHIM = """#!/usr/bin/env python3
# Written by imc-reply-gate core serial 7 (OI-0794, 2026-11-25) at every session start. Task prompts written before the
# loader run "$(ls -d /root/.claude/plugins/synced/*/imc-reply-gate*/checker/precheck.py | head -1)"; the loader layout
# had no such file. This runs the loader's current cached precheck, or the copy bundled under core/.
import os, pathlib, sys
plugin = pathlib.Path(__file__).resolve().parent.parent
cache = pathlib.Path.home() / ".claude" / "imc-reply-gate-core"
root = plugin / "core"
try:
    cur = (cache / "current").read_text(encoding="utf-8").strip()
    if cur and (cache / cur / "checker" / "precheck.py").is_file():
        root = cache / cur
except OSError:
    pass
os.environ["CLAUDE_PLUGIN_ROOT"] = str(root)
os.execv(sys.executable, [sys.executable, str(root / "checker" / "precheck.py")] + sys.argv[1:])
"""


def ensure_precheck_shim(plugin=None):
    """core serial 7 (OI-0794 (three task prompts call a removed precheck path)): no plug-in update needed. The loader
    passes its own folder in IMC_GATE_LOADER_PLUGIN; write <plugin>/checker/precheck.py when it is missing or differs.
    Never raises: a session start must not fail over this. Returns 'written', 'present' or the reason it did nothing."""
    try:
        plugin = plugin or os.environ.get("IMC_GATE_LOADER_PLUGIN", "")
        if not plugin or not os.path.isfile(os.path.join(plugin, "loader.py")):
            return "no loader plug-in"
        d = os.path.join(plugin, "checker")
        f = os.path.join(d, "precheck.py")
        if os.path.isfile(f) and open(f, encoding="utf-8").read() == PRECHECK_SHIM:
            return "present"
        os.makedirs(d, exist_ok=True)
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(PRECHECK_SHIM)
        os.replace(tmp, f)
        return "written"
    except Exception as e:  # noqa: BLE001
        return "error: %s" % e


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "?"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        allow(mode, "error", detail="bad JSON on stdin: %s" % e)
    if mode == "sessionstart":
        ensure_precheck_shim()
        sessionstart(payload)
    if mode == "prompt":
        promptreminder(payload)
    session = str(payload.get("session_id", ""))
    tp = payload.get("transcript_path") or ""
    tool = payload.get("tool_name")
    markers = MARKERS + PUSH_MARKERS if (mode == "pretool" and tool == "PushNotification") else MARKERS
    try:
        # 0.3.72 (Rob 2026-11-19 12:47 and 12:52 PM PST, Disability Claim chat "Plaud export and Drive cleanup"/"reorganization"):
        # Objective 8 is "every session, chat and task". Any claude.ai Project session is now scoped, not only AI Prompt
        # Library and Improving my Claude (Overall), so project-only codes (for example PRE-SEND-REVIEW) run there too.
        # Not the cause of that chat's 12:51 PM miss: a replay showed 0.3.68 already blocks it on EVERY-REPLY-TABLE.
        scoped = bool(tp) and (in_scope(tp, markers) or in_scope(tp, PROJECT_MARKERS))
    except Exception as e:
        scoped = False
        log(mode, "note", session=session, detail="transcript unreadable, INCOMPLETE only: %s" % e)

    if mode == "stop":
        # 0.2.2 (F-532): a rewrite after a block is checked too; the per-turn block cap ends any loop.
        text = payload.get("last_assistant_message") or ""
        src = "last_assistant_message"
        if not (isinstance(text, str) and text.strip()):
            text, src = last_assistant_text(read_entries(tp)), "transcript"
    elif mode == "pretool":
        if tool not in ("SendUserMessage", "PushNotification"):
            allow(mode, "not a gated tool", session=session, tool=tool)
        text = (payload.get("tool_input") or {}).get("message") or ""
        src = "PushNotification" if tool == "PushNotification" else "tool_input.message"
    else:
        allow(mode, "error", session=session, detail="unknown mode")

    if not text.strip():
        allow(mode, "empty reply", session=session, source=src)
    if mode == "stop" and not table_info(text):  # 0.3.22: a no-table reply to a background wake-up is not gated
        try:
            if tp and wakeup_reply(read_entries(tp)):
                allow(mode, "wake-up reply, no table", session=session, source=src, chars=len(text))
        except SystemExit:
            raise
        except Exception as e:
            log(mode, "note", session=session, detail="wake-up check failed: %s" % e)

    gated, gate_why = gating(session, tp, text, tool)
    if not gated and not STATUS_KEEP:
        allow(mode, "ungated status reply", session=session, source=src, chars=len(text), gate=gate_why)
    log(mode, "note", session=session, detail="gated: " + gate_why)

    fails = []
    if os.path.isfile(CHECKER):
        try:
            in_project = bool(tp) and in_scope(tp, PROJECT_MARKERS)
        except Exception:
            in_project = False
        env = dict(os.environ, REPLYCHECK_PROJECT="1") if in_project else {k: v for k, v in os.environ.items() if k != "REPLYCHECK_PROJECT"}
        env.pop("REPLYCHECK_KAP_PROJECT", None)
        if in_project and bool(tp) and in_kap_project(tp):  # 0.3.17: STANDING-ROWS is a Kaprelian-project obligation only
            env["REPLYCHECK_KAP_PROJECT"] = "1"
        # R376 (Rob 2026-10-25 19:05 PDT, edit authorised 2026-10-26 09:39 PDT): no table in every reply. The old every-reply check
        # (0.2.31) is now opt-in: it runs only when IMC_EVERY_REPLY_TABLE=1, which the plug-in's own selftests set.
        # 0.3.36 (Rob 2026-11-04 7:40 AM PST): R376 is withdrawn. A next-steps table ends every reply unless the reply
        # carries 'ALL OBJECTIVES DONE:' (checker/replycheck.py check_every_reply_table). IMC_EVERY_REPLY_TABLE=0 turns it off.
        if os.environ.get("IMC_EVERY_REPLY_TABLE") != "0":
            env["REPLYCHECK_EVERY_TABLE"] = "1"
        else:
            env.pop("REPLYCHECK_EVERY_TABLE", None)
        p = subprocess.run([sys.executable, CHECKER], input=text, capture_output=True, text=True,
                           timeout=CHECK_TIMEOUT, cwd=os.path.dirname(CHECKER), env=env)
        if p.returncode not in (0, 1) or "Traceback" in p.stderr:
            log(mode, "note", session=session, detail="checker rc=%s stderr=%s" % (p.returncode, p.stderr[-400:]))
        else:
            fails = re.findall(r"^FAIL  \[([^\]]+)\] (.*)$", p.stdout, re.M)
            watch = [(c, m) for c, m in fails if c in STATUS_WATCH]  # 0.2.29, F-684
            if not scoped:
                fails = [(c, m) for c, m in fails if c in ALWAYS_ON]
    else:
        log(mode, "note", session=session, detail="checker missing: %s" % CHECKER)
    fails += _gap_fails(text)
    # 0.3.83 FIELD-CLAIM-UNVERIFIED (the second trap of the 2026-11-19 instructions-backup brief):
    # a reply may not say an account instruction-field edit is done without quoting a read-back byte
    # count and hash. Measured 2026-11-19: Rob pasted a 16,852-byte rewrite and reported it done; the
    # live field held 455 characters of his own chat messages. Unconditional, like _gap_fails: the
    # field governs every session, so the check is not scoped to one project.
    _fcp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "checker", "fieldclaimcheck.py")
    if os.path.isfile(_fcp):
        try:
            import importlib.util as _ilu0
            _fs = _ilu0.spec_from_file_location("fieldclaimcheck", _fcp)
            _fm = _ilu0.module_from_spec(_fs); _fs.loader.exec_module(_fm)
            fails += _fm.field_claim_fails(text)
        except Exception as _e:  # an erroring check must not pass silently
            fails.append(("FIELD-CLAIM-ERRORED", "the FIELD-CLAIM-UNVERIFIED check could not run (%s); "
                          "a check that cannot run does not pass" % str(_e)[:160]))
    else:
        log(mode, "note", session=session, detail="checker/fieldclaimcheck.py absent: FIELD-CLAIM-UNVERIFIED not run")
    fails += answer_promise_fails(mode, tp, session, text)  # 0.3.23
    fails += table_lost_fails(mode, tp, text)  # 0.3.25
    # 0.2.29 STATUS-WATCH: the four voice checks on every reply, every session.
    try:
        for c, m in watch:
            if watching():
                log(mode, "warn", session=session, detail="STATUS-WATCH " + c, gated=gated)
            elif c not in {x for x, _ in fails}:
                fails.append((c, m))
    except NameError:
        pass
    # 0.2.5 PRECHECK: a reply with a next-steps table whose normalized sha256 checker/precheck.py stamped has had
    # its table-scoped codes run on the draft (with REPLYCHECK_DRAFT); skip them here, keep the prose checks.
    # 0.2.6: a missing stamp BLOCKS (R285). Stop asks for a flag line, never a resent table.
    precheck = None
    if table_info(text):
        try:
            if prechecked(norm_sha(text)):
                precheck = "matched"
                dropped = sorted({c for c, m in fails if fail_in_table(c, m, text)})
                fails = [(c, m) for c, m in fails if not fail_in_table(c, m, text)]
                log(mode, "note", session=session, detail="precheck-matched", skipped=dropped)
            else:
                precheck = "missing"
                log(mode, "warn", session=session, detail="PRECHECK-MISSING")
                if mode == "pretool" and tool == "SendUserMessage":
                    fails.append(("PRECHECK-MISSING", "this message carries a next-steps table that checker/precheck.py "
                                  "has not stamped. NOTHING WAS SENT. Save the exact text as a draft file, have the "
                                  "independent reviewer read it, run python3 \"" + os.path.join(ROOT, "checker", "precheck.py") + "\" <draft>, "
                                  "and send the stamped text unchanged." + first_diff_hint(text)))
                elif mode == "stop":
                    fails.append(("PRECHECK-MISSING", "the next-steps table in this reply was sent without a "
                                  "precheck.py stamp for its exact text." + first_diff_hint(text)))
        except Exception as e:
            log(mode, "note", session=session, detail="precheck lookup failed: %s" % e)
    # 0.3.18 CHANGE 2: Stop mode asks a stamp for a no-table reply longer than PROGRESS_MAX, as SendUserMessage does.
    if PLAIN_STAMP and mode == "stop" and not table_info(text) and len(text.strip()) > PROGRESS_MAX:
        try:
            if not prechecked(norm_sha(text)):
                fails.append(("PRECHECK-MISSING", "this reply is longer than %d characters, carries no table and has no checker/precheck.py stamp for its exact text." % PROGRESS_MAX))
        except Exception as e:
            log(mode, "note", session=session, detail="stop no-table stamp lookup failed: %s" % e)
    if table_info(text):
        fails += table_row_fails(text)  # 0.2.13, 0.2.20, 0.3.2, 0.3.51; 0.4.11 one list shared with precheck
        _rr = rec_relevance_fails(text)  # 0.3.54, warn-only until REC_RELEVANCE_ENFORCE is True
        if _rr:
            if REC_RELEVANCE_ENFORCE:
                fails += _rr
            else:
                log(mode, "note", session=session, detail="REC-TEST-RELEVANCE (warn): " + _rr[0][1][:200])
        _rc = ruling_covers_row_fails(text)  # 0.3.48
        if _rc:
            if RULING_COVERS_ENFORCE:
                fails += _rc
            else:
                log(mode, "note", session=session, detail="RULING-COVERS-ROW (warn): " + _rc[0][1][:200])
    try:
        key = turn_key(read_entries(tp))
    except Exception:
        key = "transcript-unreadable"
    # 0.2.4 TABLE-RESEND: Stop only, in every session. A pending table comes from this session's last Stop block.
    # 0.2.5 TABLE-DUPLICATE: when that block did not involve the table, repeating the table fails instead.
    pending = None
    if mode == "stop":
        try:
            pending = get_pending(session)
        except Exception as e:
            log(mode, "note", session=session, detail="state unreadable, TABLE-RESEND skipped: %s" % e)
        try:
            if not table_info(text) and turn_sent_table(read_entries(tp)):
                fails = [(c, m) for c, m in fails if c != "EVERY-REPLY-TABLE"]
                log(mode, "note", session=session, detail="EVERY-REPLY-TABLE waived: a stamped table was already sent by SendUserMessage this turn")
        except Exception as e:
            log(mode, "note", session=session, detail="turn_sent_table failed: %s" % e)
        try:
            # 0.3.53 TABLE-TWICE-IN-TURN (Rob 2026-11-17 9:01 AM PST, "Why were there repeats of your reply?"): a delivered
            # SendUserMessage table plus a table in the closing text shows Rob the table twice in one turn.
            if table_info(text) and turn_sent_table(read_entries(tp)):
                fails.append(("TABLE-TWICE-IN-TURN", "a next-steps table was already delivered by SendUserMessage this turn, so this closing text repeats it. Send the closing text without a table, or send the table only once."))
        except Exception as e:
            log(mode, "note", session=session, detail="table-twice check failed: %s" % e)
        try:
            # 0.3.90 TABLE-VIA-FINAL-TEXT (OI-0778, recurrence of OI-0651; Rob 2026-11-24 "build 0.3.90"): the final
            # assistant text is checked only here, after Rob has read it, while a SendUserMessage is checked by pretool
            # before display (measured offline in session 77397478: stamped text rc=0, first line altered rc=2 "NOTHING
            # WAS SENT"). Two reworded stamped tables reached Rob as final text on 2026-11-24. In a turn Rob typed, a
            # next-steps table must go out through SendUserMessage; scheduled-trigger turns are not affected.
            if table_info(text) and newest_prompt_is_human(read_entries(tp)):
                fails.append(("TABLE-VIA-FINAL-TEXT", "this next-steps table was sent as the final reply text, which the gate checks only after Rob has read it. From the next reply on, in a turn Rob typed, send each table through SendUserMessage, whose pretool check refuses a reworded or unstamped table before display, and end the turn with one short line."))
        except Exception as e:
            log(mode, "note", session=session, detail="table-via-final-text check failed: %s" % e)
        fails += resend_fails(text, pending)
        fails += duplicate_fails(text, pending, key)
    corr_waiver = False
    try:
        if mode in ("stop", "pretool") and tp and correction_only(text) and turn_has_hook_feedback(read_entries(tp)):
            corr_waiver = True
            fails = [(c, m) for c, m in fails if c != "EVERY-REPLY-TABLE"]
            log(mode, "note", session=session, detail="EVERY-REPLY-TABLE waived: CORRECTION-only reply after Stop-hook feedback this turn (0.3.12)")
    except Exception as e:
        log(mode, "note", session=session, detail="correction waiver failed: %s" % e)
    try:
        if mode in ("stop", "pretool") and tp and task_form_no_table(read_entries(tp)):
            fails = [(c, m) for c, m in fails if c != "EVERY-REPLY-TABLE"]
            log(mode, "note", session=session, detail="EVERY-REPLY-TABLE waived: the task prompt's REPLY FORM says no table (0.3.65)")
    except Exception as e:
        log(mode, "note", session=session, detail="task-form waiver failed: %s" % e)
    if not gated:
        _keep = STATUS_KEEP + (() if watching() else STATUS_WATCH)
        fails = [(c, m) for c, m in fails if c in _keep]
    # 0.3.3 PROGRESS LANE (White Hat 2026-10-23, reviewers 6 and 8): EVERY-REPLY-TABLE applied to a mid-work
    # progress line (measured: 8 refusals on 2026-10-23) and the refusal text said the line was on Rob's screen,
    # which is false for a pretool block. A table-less SendUserMessage of at most PROGRESS_MAX characters is a
    # progress line; every other check still runs on it.
    is_send = (mode == "pretool" and tool in ("SendUserMessage", "PushNotification"))  # 0.3.88: a notification needs a stamp too (OI-0727)
    if is_send and not table_info(text) and len(text.strip()) <= PROGRESS_MAX:
        fails = [(c, m) for c, m in fails if c != "EVERY-REPLY-TABLE"]
    # 0.3.66 (2026-11-18, memory check run 05:58 PST): a short table-less PushNotification is a phone alert, not a
    # reply; EVERY-REPLY-TABLE blocked it although the alert had already reached Rob's phone.
    # 0.3.67: the blocked 05:58 PST alert was 498 characters, over PROGRESS_MAX (400); alerts get PUSH_MAX.
    if mode == "pretool" and tool == "PushNotification" and not table_info(text) and len(text.strip()) <= PUSH_MAX:
        fails = [(c, m) for c, m in fails if c != "EVERY-REPLY-TABLE"]
    # 0.3.3 SINGLE SEND PATH: a long message must be a stamped draft, with or without the exact header, and a
    # stamped text can go out once per session (DUPLICATE-SEND), so a retype or a resend is refused before display.
    if is_send:
        try:
            sha = norm_sha(text)
            stamped = prechecked(sha)
            if PLAIN_STAMP and not table_info(text) and len(text.strip()) > PROGRESS_MAX and not stamped and not corr_waiver:
                fails.append(("PRECHECK-MISSING", "this message is longer than %d characters and carries no stamp from "
                              "checker/precheck.py for its exact text. NOTHING WAS SENT. Save it as a draft, run "
                              "precheck.py, and send the stamped text unchanged.%s" % (PROGRESS_MAX, first_diff_hint(text))))
            if stamped and _already_sent(session, sha):
                fails.append(("DUPLICATE-SEND", "this exact stamped text was already sent in this session. NOTHING WAS "
                              "SENT. Do not send it again; if it needs a change, change the draft, stamp it, send once."))
        except Exception as e:
            log(mode, "note", session=session, detail="send-path check failed: %s" % e)
    try:
        w = waived()
    except Exception:
        w = set()
    live = [(c, m) for c, m in fails if c not in w]
    codes_all = sorted({c for c, _ in fails})
    if not live and is_send and table_info(text):
        try:
            _mark_sent(session, norm_sha(text))
        except Exception:
            pass
    if not live:
        if pending:
            try:
                set_pending(session, None)
            except Exception:
                pass
        allow(mode, ("clean" if not fails else "only waived") if scoped else "out-of-scope",
              session=session, source=src, chars=len(text), fails=codes_all, scoped=scoped, precheck=precheck)

    n = bump(session, key)
    live_codes = sorted({c for c, _ in live})
    if n > MAX_BLOCKS:
        write_unchecked(mode, session, key, n, src, live_codes, text)
        if pending:
            try:
                set_pending(session, None)
            except Exception:
                pass
        allow(mode, "block cap reached", session=session, turn=key, n=n, source=src, fails=live_codes,
              unchecked_log=UNCHECKED_LOG)
    tinfo = table_info(text) if mode == "stop" else None
    involved = bool(tinfo) and table_involved(live, text)
    if tinfo:
        try:
            set_pending(session, {"header": tinfo[0], "rows": tinfo[1], "turn": key, "involved": involved,
                                  "rows_text": numbered_rows(text), "at": datetime.datetime.now().timestamp()})
        except Exception as e:
            log(mode, "note", session=session, detail="state unwritable, TABLE-RESEND not armed: %s" % e)
    pend_involved = bool(pending) and pending.get("involved", True)
    log(mode, "block", session=session, turn=key, n=n, source=src, chars=len(text), fails=live_codes,
        table_rows=(tinfo[1] if tinfo else None), table_involved=(involved if tinfo else None), precheck=precheck)
    if mode == "pretool" and src == "tool_input.message":
        # 0.3.25 (Rob 2026-10-29 09:32 PDT, "I'm not seeing the Next Steps tables"): a PreToolUse block DENIES the call, so
        # the text never reaches Rob. MEASURED in a session transcript: 2 blocked SendUserMessage calls returned a hook
        # error, 8 delivered ones returned "Message delivered to user." The old text told Claude the blocked text was
        # already on Rob's screen and to send only CORRECTION: lines, so a blocked table was replaced by corrections and
        # Rob never got it (92 CORRECTION-only replies since 21:20 PDT on 2026-10-28, 5 of 7 "the table above was sent
        # without its pre-check" lines had no table before them).
        sys.stderr.write("imc-reply-gate blocked this SendUserMessage (%d of %d this turn). "
                         "NOTHING WAS SENT: a PreToolUse block denies the call, so this text did NOT reach Rob's screen "
                         "(the tool result is an error; only a delivered call returns 'Message delivered to user.'). "
                         "Rob has no table from this call. Do NOT send CORRECTION: lines in its place and never write "
                         "'the table above'. Fix the failures below in your draft file, run checker/precheck.py on the "
                         "draft, and send the whole message once, unchanged.%s Failures:\n"
                         % (n, MAX_BLOCKS, first_diff_hint(text) if "PRECHECK-MISSING" in live_codes else ""))
        for c, m in live:
            sys.stderr.write("FAIL  [%s] %s\n" % (c, m))
        sys.exit(2)
    if src == "PushNotification":
        # core serial 4 (OI-0783, 2026-11-24): this branch runs only in PreToolUse mode, and a PreToolUse block
        # DENIES the call, exactly as 0.3.25 measured for SendUserMessage. MEASURED in a scheduled run that day
        # (Drive file "OI-0783 push notification diagnostic"): the old text said the blocked notification had
        # reached Rob's phone and must not be resent, so the run sent nothing and Rob got nothing.
        sys.stderr.write("imc-reply-gate blocked this PushNotification (%d of %d this turn). "
                         "NOTHING WAS SENT: a PreToolUse block denies the call, so this notification did NOT reach "
                         "Rob's phone. Fix the failures below and send the notification once more, corrected. "
                         "Failures:\n" % (n, MAX_BLOCKS))
        for c, m in live:
            sys.stderr.write("FAIL  [%s] %s\n" % (c, m))
        sys.exit(2)
    if mode == "stop" and live_codes == ["PRECHECK-MISSING"]:
        # 0.2.6: the table is on Rob's screen and nothing in it failed a rule; only the stamp is missing.
        try:
            set_pending(session, None)
        except Exception:
            pass
        if not tinfo:
            # core serial 3 (OI-0786, 2026-11-24): measured in session 05185df0 - three closing lines of 425, 435
            # and 479 characters, with no table, drew the message below, which said a TABLE was unstamped, so
            # Claude told Rob a stamped table had gone out unchecked. Name the real failure instead.
            sys.stderr.write("imc-reply-gate blocked this reply (%d of %d this turn). "
                             "THE BLOCKED TEXT IS ALREADY ON ROB'S SCREEN. This closing text has no table; it is %d "
                             "characters, over the %d-character limit for unstamped text (PRECHECK-MISSING). This block "
                             "is about the closing text only and says nothing about any table sent earlier this "
                             "turn. Send NO further text this turn. From the next reply on, keep the "
                             "closing line at %d characters or fewer, or precheck it.\n"
                             % (n, MAX_BLOCKS, len(text.strip()), PROGRESS_MAX, PROGRESS_MAX))
            sys.exit(2)
        sys.stderr.write("imc-reply-gate blocked this reply (%d of %d this turn). "
                         "THE BLOCKED TEXT IS ALREADY ON ROB'S SCREEN. Its next-steps table was sent without a "
                         "precheck.py stamp for the exact text (PRECHECK-MISSING). Do NOT resend the table. Send "
                         "no CORRECTION line after it; state at the top of your next reply that the table above was sent without its pre-check and was not re-verified as sent. Send every later table through SendUserMessage after "
                         "precheck.py stamps it, unchanged.%s\n" % (n, MAX_BLOCKS, first_diff_hint(text)))
        sys.exit(2)
    if (tinfo and not involved) or (not tinfo and pending and not pend_involved):
        # 0.2.5: the block is about the prose only. The table already on Rob's screen passed.
        sys.stderr.write("imc-reply-gate blocked this reply (%d of %d this turn). "
                         "THE BLOCKED TEXT IS ALREADY ON ROB'S SCREEN. The table above passed; do NOT resend it. "
                         "Send NO further text this turn: no CORRECTION line. Put the corrected prose at the top of your next reply, above its one table. A repeated table fails TABLE-DUPLICATE - two "
                         "tables per reply is what Rob called confusing (2026-10-14 13:36 PDT). To point at the failing sentence, put it in double quotes or a code block; quoted text is not checked as your own claim. Failures:\n" % (n, MAX_BLOCKS))
        for c, m in live:
            sys.stderr.write("FAIL  [%s] %s\n" % (c, m))
        sys.exit(2)
    if tinfo or pending:
        rows = max(tinfo[1] if tinfo else 0, int((pending or {}).get("rows") or 0))
        sys.stderr.write("imc-reply-gate blocked this reply (%d of %d this turn). "
                         "THE BLOCKED TEXT IS ALREADY ON ROB'S SCREEN, AND IT CARRIED A NEXT-STEPS TABLE. "
                         "Do NOT resend the table: one set of tables per reply, and no table repeated within "
                         "a reply (Rob 2026-10-17 9:57 PM PDT). Send NO CORRECTION line this turn. "
                         "In your next regular reply, above its table, name each failing row by its number and give "
                         "the corrected cell text; the corrected table goes out once, whole, there. To point at the failing sentence, put it in double quotes or a code block; quoted text is not checked as your own claim. Failures:\n" % (n, MAX_BLOCKS))
        for c, m in live:
            sys.stderr.write("FAIL  [%s] %s\n" % (c, m))
        sys.exit(2)
    sys.stderr.write("imc-reply-gate blocked this reply (%d of %d this turn). "
                     "THE BLOCKED TEXT IS ALREADY ON ROB'S SCREEN (measured 2026-10-04 for both the final "
                     "reply and SendUserMessage). DO NOT RESEND IT WHOLE - that is what makes a duplicate. "
                     "Send NO further text this turn and no CORRECTION line; put the corrected sentences at the top of your next reply, above its table. To point at the failing sentence, put it in double quotes or a code block; quoted text is not checked as your own claim. Failures:\n" % (n, MAX_BLOCKS))
    for c, m in live:
        sys.stderr.write("FAIL  [%s] %s\n" % (c, m))
    sys.exit(2)


def _stop_json_channel():
    """0.3.68 (Rob 2026-11-19 7:11 AM PST, scheduled runs sent unchecked replies). Measured 2026-11-19: in scheduled-task
    sessions a Stop block sent as exit code 2 on stderr surfaced only as a 'stop-hook-error' notification and never
    reached Claude (test run cse_014Hc2SbNTU4qbP5nPDbgYDt; Delete sweep run cse_014Hc2SadpAwF7YPy5xxR5WH, 5 times),
    while the reviewer panel's JSON {"decision": "block"} on stdout did reach it. So in Stop mode the same block text
    is sent as that JSON decision, exit 0. PreToolUse blocks keep exit code 2."""
    import io
    buf = io.StringIO()
    real = sys.stderr
    sys.stderr = buf
    code = 0
    try:
        main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    finally:
        sys.stderr = real
    text = buf.getvalue()
    if code == 2 and text.strip():
        # 0.3.72: name the absolute precheck path in every Stop block; the folder can be renamed mid-session (imc-reply-gate~g2)
        text = text.rstrip() + "\nPrecheck in THIS session: python3 \"%s\" <draft>" % os.path.join(ROOT, "checker", "precheck.py")
        sys.stdout.write(json.dumps({"decision": "block", "reason": text}))
        sys.exit(0)
    if text:
        real.write(text)
    sys.exit(code)


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "stop" and os.environ.get("IMC_STOP_EXIT2") != "1":
            _stop_json_channel()
        main()
    except SystemExit:
        raise
    except BaseException as e:
        # 0.2.33 (F-305): a state-file write error used to read as a plain allow/error row. Tag it ERROR-STATE
        # and say so on stderr, so a gate that has silently stopped limiting is visible (still fail-open).
        _mode = sys.argv[1] if len(sys.argv) > 1 else "?"
        _state_err = isinstance(e, OSError) and ("imc-reply-gate.state" in str(e) or getattr(e, "filename", None) == STATE)
        log(_mode, "allow", why=("ERROR-STATE" if _state_err else "error"),
            detail="%s: %s" % (type(e).__name__, e), tb=traceback.format_exc()[-800:])
        if _state_err:
            sys.stderr.write("imc-reply-gate ERROR-STATE: cannot write %s (%s); the per-turn block counter is not kept and this reply was allowed.\n" % (STATE, e))
        sys.exit(0)
