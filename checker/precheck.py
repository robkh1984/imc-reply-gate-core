#!/usr/bin/env python3
"""precheck.py (imc-reply-gate 0.2.17 adds closing, replay and scope checks; 0.2.5, Rob 2026-10-14 13:36 PDT): check a reply draft BEFORE sending it, so the
first reply passes the Stop gate and no second next-steps table ever reaches Rob's screen.

    python3 precheck.py <draft.md>

Runs replycheck.py (beside this file) on the draft with REPLYCHECK_DRAFT set to the draft's absolute path, so
REVIEW-FIX-APPLIED and the review-record checks run against <draft>.reviewed, and judges the result exactly as
hooks/gate.py judges a reply in a project-scoped session (the strictest scope): a FAIL whose code is listed in
checker/waivers.txt does not count (that file holds the four R138 format waivers bin/replygate.py skips, plus
Rob's 2026-10-02 approvals), and gate.py's own INCOMPLETE and HOLLOW-BLOCKED checks are added. With no
unwaived FAIL it appends one line

    sha256-of-normalized-text<TAB>timestamp<TAB>draft path

to ~/.claude/imc-reply-gate-prechecked.tsv. Normalized = trailing whitespace stripped from every line and
surrounding blank lines dropped (the same normalize() as hooks/gate.py). The gate looks the sent reply up in
that file: a match skips the table-scoped codes it already ran here. A draft with any unwaived FAIL writes no
stamp and exits 1; a checker crash or empty draft exits 2.
"""
import datetime
import hashlib
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKER = os.path.join(HERE, "replycheck.py")
STAMPS = os.path.expanduser("~/.claude/imc-reply-gate-prechecked.tsv")


def _gate():
    """hooks/gate.py, loaded as a module so its waivers, gap checks and normalize() are the ones used here."""
    path = os.path.join(os.path.dirname(HERE), "hooks", "gate.py")
    spec = importlib.util.spec_from_file_location("imc_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize(text):
    return "\n".join(ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")).strip("\n")


def norm_sha(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


UNTYPABLE = set("\u00a0\u1680\u180e\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b\u202f\u205f\u3000\ufeff")


def presend_fails(draft, stricter=None):
    """0.3.68: refuse a stamp unless bin/presend.py has been run on THIS text. Kept a module-level function, not
    inline in main(), so presendgate_selftest.py can drive all four branches with temp files. `stricter` is the
    path to Rob's presend.py; the default is read from the environment or his usual location."""
    out = []
    ps = draft + ".presend"
    st = stricter or os.environ.get("IMC_PRESEND") or os.path.expanduser("~/Claude/Improving-my-Claude/bin/presend.py")
    if not os.path.isfile(st):
        out.append(("PRESEND-ABSENT", "the stricter checker %s is not on this machine, so PRESEND-MISSING could not "
                    "run; install it or say in the reply that it could not be run" % st))
    elif not os.path.isfile(ps):
        out.append(("PRESEND-MISSING", "no %s beside the draft: run `python3 %s %s > %s` and fix what it finds - the "
                    "two checkers do not overlap: on 2026-11-19 presend.py found 13 defects, among them a TESTED "
                    "label Claude was barred from earning, that precheck had not raised"
                    % (os.path.basename(ps), st, draft, ps)))
    elif os.path.getmtime(ps) < os.path.getmtime(draft):
        out.append(("PRESEND-STALE", "%s is older than the draft, so it describes text that has since changed: "
                    "re-run presend.py on the current draft" % os.path.basename(ps)))
    else:
        # 0.3.70 (2026-11-19 12:40 PST): the file's EXISTENCE is not the run. Measured today: presend.py hangs when a
        # falsifier clause names a script, because it runs that script (`drops to 6 if the gates.py suite run
        # contradicts it` -> rc=124 at 70s; the same sentence naming a time returns in a second). A shell redirect
        # creates the .presend file before presend writes a byte, so a hang leaves a 0-byte file that the existence
        # test above accepts - the check would have passed exactly the case it exists to catch. Require presend's own
        # closing line, which it writes only after every rule has run.
        body = ""
        try:
            with open(ps, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError as e:
            out.append(("PRESEND-UNREADABLE", "%s cannot be read (%s), so the run it should record cannot be "
                        "confirmed" % (os.path.basename(ps), e)))
            return out
        if not re.search(r"\d+\s+disk\s+FAIL|replycheck exit \d|PRESEND (?:CLEAN|OK)", body):
            out.append(("PRESEND-INCOMPLETE", "%s holds %d byte(s) and no closing summary line, so presend.py did not "
                        "finish on this draft - it hangs when a falsifier clause names a script. Re-run it and quote "
                        "its result, or reword the clause so it names a time rather than a script"
                        % (os.path.basename(ps), len(body))))
    return out


def main(argv):
    argv = [a for a in argv if a != "--no-project"]  # 0.2.11: the flag is read from sys.argv below
    if len(argv) != 2:
        sys.stderr.write("usage: python3 precheck.py <draft.md>\n")
        return 2
    draft = os.path.abspath(argv[1])
    if not os.path.isfile(draft):
        sys.stderr.write("NOT CHECKED  no such draft: %s\n" % draft)
        return 2
    env = dict(os.environ, REPLYCHECK_DRAFT=draft)
    env.pop("REPLYCHECK_KAP_PROJECT", None)
    gate = _gate()  # 0.3.17: loaded first so the project test below is the gate's own
    sys.path.insert(0, HERE)
    import transcript_util as _tu0
    _tr0 = _tu0.find_transcript()
    if _tr0 and gate.in_kap_project(_tr0):  # STANDING-ROWS is owed only in the Kaprelian doctors project
        env["REPLYCHECK_KAP_PROJECT"] = "1"
    # 0.2.11: judged as a project-bound session (the strictest) unless --no-project is passed.
    if "--no-project" in sys.argv:
        env.pop("REPLYCHECK_PROJECT", None)
    else:
        env["REPLYCHECK_PROJECT"] = "1"
    # 0.4.8 (Rob 2026-11-25 2:17 PM PST, session 05185df0): precheck stamped a reply that the Stop hook then blocked on
    # EVERY-REPLY-TABLE, because the gate sets REPLYCHECK_EVERY_TABLE=1 for chat replies and precheck never did, so the
    # blocked text reached Rob's screen. Precheck now runs the same check, with the gate's own task REPLY FORM waiver.
    if os.environ.get("IMC_EVERY_REPLY_TABLE") != "0":
        try:
            _tf = bool(_tr0) and gate.task_form_no_table(gate.read_entries(_tr0))
        except Exception:
            _tf = False
        if not _tf:
            env["REPLYCHECK_EVERY_TABLE"] = "1"
    p = subprocess.run([sys.executable, CHECKER, draft], capture_output=True, text=True, env=env, cwd=HERE)
    sys.stderr.write(p.stderr)
    if p.returncode not in (0, 1) or "Traceback" in p.stderr:
        sys.stdout.write(p.stdout)
        print("PRECHECK NOT CHECKED  replycheck.py rc=%d - no stamp written" % p.returncode)
        return 2
    with open(draft, encoding="utf-8", errors="replace") as f:
        text = f.read()
    fails = re.findall(r"^FAIL  \[([^\]]+)\] (.*)$", p.stdout, re.M) + gate._gap_fails(text)
    fails += gate.table_start_fails(text) + gate.rob_owns_work_fails(text)  # 0.2.13
    fails += gate.claude_row_runnable_fails(text)  # 0.3.51
    _pf = presend_fails(draft)
    # 0.3.78 (Rob approved 2026-11-19 5:46 PM PST): replygate.py was skipped in total silence, because
    # presend_fails only ever looked for presend.py. Tested on a copy at /tmp/pctest2 first: unpatched,
    # precheck never mentions replygate; patched, REPLYGATE-MISSING fires when the checker exists unrun
    # and REPLYGATE-ABSENT when it is not on the machine.
    _rg = os.environ.get("IMC_REPLYGATE") or os.path.expanduser("~/Claude/Improving-my-Claude/bin/replygate.py")
    _rgout = draft + ".replygate"
    if not os.path.isfile(_rg):
        _pf = _pf + [("REPLYGATE-ABSENT", "the second Mac checker %s is not on this machine; run it on the Mac draft "
                      "through the device bridge, or say in the reply that it could not run" % _rg)]
    elif not os.path.isfile(_rgout):
        _pf = _pf + [("REPLYGATE-MISSING", "no %s beside the draft: run `python3 %s %s > %s` and judge it by its FAIL "
                      "lines, not its exit code" % (os.path.basename(_rgout), _rg, draft, _rgout))]
    # 0.3.71 (Rob 2026-11-19 12:34 PM PST, "Agree with your recommendations on items 1-3"; first built as 0.3.69): a cloud
    # session has no ~/Claude/Improving-my-Claude, so presend.py can never run there and PRESEND-ABSENT would refuse every
    # cloud stamp. There the missing checker is printed as a WARN line, so it still does not pass silently; on the Mac it
    # stays a FAIL. Merged onto 0.3.70 (another session's PRESEND-INCOMPLETE check, built 12:23 PM PST).
    # 0.3.78: the carve-out used to match the single code ["PRESEND-ABSENT"] exactly. Adding REPLYGATE-ABSENT
    # beside it broke that equality, which would have turned both into hard FAILs and left no cloud session able
    # to stamp at all. Measured here before shipping. Any subset of the two absence codes now warns in the cloud;
    # a MISSING code (the checker exists and was not run) still fails, there as on the Mac.
    _absent = {"PRESEND-ABSENT", "REPLYGATE-ABSENT"}
    _codes = {c for c, _m in _pf}
    if _codes and _codes <= _absent and not os.path.isdir(os.path.expanduser("~/Claude/Improving-my-Claude")):
        for _c, _m in _pf:
            print("WARN  [%s] %s (cloud session: that checker lives only on Rob's Mac; run it there on the Mac draft "
                  "through the device bridge, or say in the reply that it could not run)" % (_c, _m))
    else:
        fails += _pf
    if gate.REC_RELEVANCE_ENFORCE:  # 0.3.56: same warn-only setting as hooks/gate.py
        fails += gate.rec_relevance_fails(text)  # 0.3.54
    for _n, _m in gate.ruling_covers_row_fails(text):  # 0.3.48, warn mode
        if gate.RULING_COVERS_ENFORCE:
            fails.append((_n, _m))
        else:
            print("WARN  [%s] %s" % (_n, _m))
    # 0.2.17 (Rob-agreed Oct 17 2026, rows 27 and 28 and the closing-claim fix): closing line versus the reply's own table,
    # the replay of the independent review, and the scope check. Replay and scope read the harness-written transcript
    # (REPLY_GATE_TRANSCRIPT, else the newest ~/.claude/projects/*/*.jsonl); with none found they print NOT RUN and do not pass silently.
    sys.path.insert(0, HERE)
    import closingcheck, replaycheck, scopecheck, livereadcheck, transcript_util, lengthcheck
    import fieldclaimcheck  # 0.3.83
    fails += closingcheck.closing_fails(text)
    fails += fieldclaimcheck.field_claim_fails(text)  # 0.3.83: no 'the field edit is done' without a read-back
    try:                                                   # 0.3.61: SEND-UNOWNED
        import importlib.util as _ilu
        _so = os.path.join(HERE, "sendowned.py")
        _sp = _ilu.spec_from_file_location("sendowned", _so)
        _sm = _ilu.module_from_spec(_sp); _sp.loader.exec_module(_sm)
        fails += _sm.owned_fails(text)
    except Exception as _e:
        # an erroring check must not pass silently: it becomes a FAIL, not a note.
        fails.append(("SEND-UNOWNED-ERRORED", "the SEND-UNOWNED check could not run (%s); a check that cannot run does not pass" % str(_e)[:160]))
    fails += lengthcheck.length_fails(text, draft)  # 0.3.5: REPEAT-TEXT and ABOVE-TABLE-CAP, Rob approved 2026-10-23
    _tr = transcript_util.find_transcript()
    if _tr is None:
        print("WARN  [REPLAY-NOT-RUN] no session transcript found, so the replay and scope checks did not run")
    elif os.environ.get("REPLY_GATE_REPLAY", "1") != "0":
        fails += replaycheck.replay_fails(draft, _tr) + scopecheck.scope_fails(text, _tr) + scopecheck.blocked_fails(text, _tr) + livereadcheck.live_read_fails(text, _tr)  # 0.2.23
    # 0.2.8 UNTYPABLE (F-573, Rob 2026-10-15 10:39 PDT "Why is your reply repeating itself again????"):
    # a draft carrying a character that looks like a space but is not one (U+00A0 and kin) cannot be
    # retyped into SendUserMessage exactly - measured: a typed U+00A0 arrives as U+0020 - so the stamp never
    # matches, the gate blocks, and the blocked text is still shown. Refuse it here, before the first send.
    _bad = sorted({"U+%04X" % ord(ch) for ch in text if ch in UNTYPABLE})
    if _bad:
        fails.append(("UNTYPABLE", "the draft carries %s, which looks like a space but cannot be retyped "
                      "exactly into SendUserMessage, so the sent text would never match this stamp. Use "
                      "'&nbsp;' for a non-breaking space." % ", ".join(_bad)))
    # 0.3.29 (Rob 2026-10-29 22:26 PDT, "why are the corrections after the next steps table"): the Stop-hook panel only
    # runs after text is on screen, so its findings could only follow the table. Run the same panel on the draft here, before
    # the stamp, so findings are fixed above the table. IMC_PRECHECK_PANEL=0 skips it; a failed panel warns and does not block.
    _panel_ran = False
    if os.environ.get("IMC_PRECHECK_PANEL", "1") != "0":
        _rp = os.path.join(os.path.dirname(HERE), "hooks", "reviewpanel.py")
        try:
            _pp = subprocess.run([sys.executable, _rp, "review", draft], capture_output=True, text=True, timeout=170)
            if _pp.returncode in (0, 1):
                _panel_ran = True
            if _pp.returncode == 1:
                # 0.3.30: findings print for the author to fix or dispute above the table; they no longer block the stamp,
                # because a hostile panel returns findings on every draft (measured, ctl-good.out).
                print("WARN  [PANEL-FINDINGS] the reviewer panel found defects in the draft; fix each real one, dispute the rest on the PRE-SEND REVIEW line:\n" + _pp.stdout.strip()[:3000])
            elif _pp.returncode != 0:
                print("WARN  [PANEL-NOT-RUN] reviewpanel.py review returned rc=%d: %s" % (_pp.returncode, (_pp.stdout + _pp.stderr).strip()[:200]))
        except Exception as _e:
            print("WARN  [PANEL-NOT-RUN] reviewpanel.py review did not finish: %s" % str(_e)[:200])
    w = gate.waived() if os.path.isfile(gate.WAIVERS) else set()
    # 0.2.16 (Rob 2026-10-17, row 15; RC5): a waived code does not block, so it must not read as a FAIL. Print each
    # such line as WAIVED and correct the checker's own totals line. Unwaived FAIL lines are untouched.
    _out, _k = [], 0
    for ln in p.stdout.splitlines():
        m = re.match(r"^FAIL  \[([^\]]+)\] (.*)$", ln)
        if m and m.group(1) in w:
            ln, _k = "WAIVED [%s] %s" % (m.group(1), m.group(2)), _k + 1
        _out.append(ln)
    for i, ln in enumerate(_out):
        m = re.match(r"^(\d+) FAIL, (\d+) WARN$", ln)
        if m and _k:
            _out[i] = "%d FAIL, %d WARN, %d WAIVED (shown above as WAIVED; they do not block)" % (int(m.group(1)) - _k, int(m.group(2)), _k)
    sys.stdout.write("\n".join(_out) + ("\n" if _out else ""))
    waived_codes = sorted({c for c, _ in fails if c in w})
    live = [(c, m) for c, m in fails if c not in w]
    if waived_codes:
        print("PRECHECK WAIVED (checker/waivers.txt, as the gate): %s" % ", ".join(waived_codes))
    if live:
        for c, m in live:
            if (c, m) not in re.findall(r"^FAIL  \[([^\]]+)\] (.*)$", p.stdout, re.M):
                print("FAIL  [%s] %s" % (c, m))
        codes = sorted({c for c, _ in live})
        print("PRECHECK FAIL  %d unwaived FAIL(s): %s - no stamp written; fix the draft and run precheck.py again"
              % (len(live), ", ".join(codes)))
        # *** ROUNDS, 2026-11-22. THE GATE RECORDED ONLY ITS OWN SUCCESSES. ***
        # Measured that morning: the stamp file held 18 PASS rows and not one failed run, so the
        # rework this gate causes - the rounds a reply spends being refused - had never been a
        # number anyone could read, while 70 FAIL codes accumulated on the strength of the defects
        # they catch. A ledger that records only wins cannot price its own cost. Failures now land
        # in the same file, marked FAIL, so rounds-per-reply is readable with wc and sort.
        try:
            os.makedirs(os.path.dirname(STAMPS), exist_ok=True)
            ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
            with open(STAMPS, "a", encoding="utf-8") as fh:
                fh.write("FAIL\t%s\t%s\t%s\n" % (ts, draft, ",".join(codes)))
        except OSError:
            pass
        return 1
    sha = gate.norm_sha(text)
    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    row = "%s\t%s\t%s%s\n" % (sha, ts, draft, "\tpanel=ran" if _panel_ran else "")
    # 0.4.7: a sandboxed Bash cannot write under ~/.claude; fall back to a per-user temp path the gate hooks also read.
    _errs = []
    for _dst in [STAMPS] + (gate.sandbox_fallbacks("imc-reply-gate-prechecked.tsv") if hasattr(gate, "sandbox_fallbacks") else []):
        try:
            os.makedirs(os.path.dirname(_dst), exist_ok=True)
            with open(_dst, "a", encoding="utf-8") as f:
                f.write(row)
            print("PRECHECK PASS  stamp %s written to %s" % (sha[:16], _dst))
            return 0
        except OSError as _e:
            _errs.append("%s: %s" % (_dst, type(_e).__name__))
    print("PRECHECK FAILED  the stamp could not be written anywhere: " + "; ".join(_errs))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
