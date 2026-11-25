#!/usr/bin/env python3
"""reviewpanel.py - isolated reviewer panel for reply review (row 3 build, 2026-10-23).
Modes:
  review FILE        run the panel on FILE, print merged findings, exit 1 if any defect found, 0 if none, 2 on panel failure
  tzcheck FILE       deterministic check: a time labelled PDT/PST must match US daylight-time dates; exit 1 on mismatch
  stop               Stop-hook mode (reads hook JSON on stdin); blocks with the findings, at most MAX_ROUNDS per message
  selftest           seeds known errors and checks the panel flags them; checks isolation, wall time and cost
Panel set (Rob 2026-10-23 4:55 PM PDT): 1 default + 2 haiku + 1 opus, run in parallel, each isolated.
"""
import datetime, glob, hashlib, json, os, re, subprocess, sys, tempfile, time, concurrent.futures as cf

PANEL = [("default", None), ("haiku-1", "haiku"), ("haiku-2", "haiku"), ("opus", "opus")]
MAX_ROUNDS = 3
HOOK_BUDGET_S = 140
CLEAN_ENV_DROP = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_AFTER_LAST_COMPACT")
STATE = os.path.expanduser("~/.claude/reviewpanel-state.json")
PRECHECK_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "checker", "precheck.py")
REVIEW_PROMPT = ("Review the reply in {f}. List every defect only: wrong or unsupported claims, contradictions, arithmetic slips, "
                 "wrong time zones or dates, wrong or missing required elements, overstatements. Numbered, one line each, quoting the faulty text.")
MERGE_PROMPT = ("Several reviewers listed defects in a reply. Merge them: remove duplicates, drop confirmations and items that only say a claim cannot be checked, "
                "keep every distinct defect with the quoted text. Output a numbered list, one line per defect, then a last line 'COUNT: n'. Reviewer outputs:\n\n{x}")


AUTH_ERR = re.compile(r"\W*(?:authentication error|not logged in|please run /login|invalid api key|api error|credit balance|oauth token)", re.I)


def isolated(prompt, model=None, tools=True, turns=8, timeout=130):
    cwd = os.path.join(tempfile.gettempdir(), "reviewpanel-iso")
    os.makedirs(cwd, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in CLEAN_ENV_DROP}
    a = ["claude", "-p", prompt, "--setting-sources", "project", "--system-prompt",
         "You are a strict reviewer. Report defects only, numbered." if tools else "You are a careful editor. Answer only in the requested format.",
         "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--output-format", "json", "--max-turns", str(turns)]
    if model:
        a += ["--model", model]
    if tools:
        a += ["--allowedTools", "Read"]
    t = time.time()
    try:
        r = subprocess.run(a, capture_output=True, text=True, cwd=cwd, env=env, stdin=subprocess.DEVNULL, timeout=timeout)
        o = json.loads(r.stdout)
    except Exception as e:
        return {"result": "", "error": str(e)[:200], "cost": 0.0, "secs": time.time() - t}
    res, cost = o.get("result") or "", o.get("total_cost_usd") or 0.0
    err = None if o.get("subtype") == "success" else str(o.get("subtype"))
    # 0.3.72 (Rob 2026-11-19 12:52 PM PST, Disability Claim chat "Plaud export and Drive reorganization"): measured there,
    # every reviewer returned subtype "success" with result "Authentication error ... please try again" and $0.00, so the
    # panel counted 4 of 4 reviewers ok, found 0 defects and exited 0: a review that never ran passed as clean. A result
    # flagged is_error, a run that cost nothing, or an auth/API error text is now a failed reviewer, never an empty review.
    # AUTH_ERR applies only to a short reply that opens with the error, so a real paid review that quotes the phrase still counts.
    if err is None and (o.get("is_error") or cost <= 0 or (len(res.strip()) < 300 and AUTH_ERR.match(res.strip()))):
        err = "reviewer did not run: " + (res.strip()[:120] or "no result, $0.00")
    return {"result": res, "error": err, "cost": cost, "secs": time.time() - t, "session": o.get("session_id")}


# ---- deterministic timezone check: replaces the judgement of a reviewer, because the default model never caught it in 10 runs
def us_dst(d):
    """US daylight time: second Sunday of March to first Sunday of November."""
    def nth_sunday(y, m, n):
        x = datetime.date(y, m, 1)
        x += datetime.timedelta(days=(6 - x.weekday()) % 7)
        return x + datetime.timedelta(weeks=n - 1)
    return nth_sunday(d.year, 3, 2) <= d < nth_sunday(d.year, 11, 1)

MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
TZ_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2})(?:,? (\d{4}))?[^.\n|]{0,40}?\b(\d{1,2}:\d{2}\s?[AP]M)\s+(P[SD]T)\b")

def tzcheck(text, default_year=None):
    default_year = default_year or datetime.date.today().year
    bad = []
    for m in TZ_RE.finditer(text):
        mon, day, yr, _t, tz = m.groups()
        try:
            d = datetime.date(int(yr or default_year), MONTHS[mon], int(day))
        except ValueError:
            continue
        want = "PDT" if us_dst(d) else "PST"
        if tz != want:
            bad.append("%s should be %s on %s (daylight time %s)" % (m.group(0).strip(), want, d.isoformat(), "applies" if want == "PDT" else "has ended"))
    return bad


def panel(path):
    t0 = time.time()
    with cf.ThreadPoolExecutor(len(PANEL)) as ex:
        outs = list(ex.map(lambda p: (p[0], isolated(REVIEW_PROMPT.format(f=path), p[1])), PANEL))
    ok = [(n, o) for n, o in outs if o["result"] and not o["error"]]
    cost = sum(o["cost"] for _, o in outs)
    if not ok:
        return {"status": "failed", "findings": "", "cost": cost, "secs": time.time() - t0, "outs": outs}
    joined = "\n\n".join("== reviewer %s ==\n%s" % (n, o["result"]) for n, o in ok)
    m = isolated(MERGE_PROMPT.format(x=joined), None, tools=False, turns=3, timeout=max(20, HOOK_BUDGET_S - (time.time() - t0) - 5))
    cost += m["cost"]
    merged = m["result"] if (m["result"] and not m["error"]) else joined  # 0.3.72: a failed merge falls back to the raw findings
    return {"status": "ok", "findings": merged, "cost": cost, "secs": time.time() - t0, "outs": outs, "reviewers_ok": len(ok)}


def count_of(findings):
    m = re.search(r"COUNT:\s*(\d+)", findings)
    return int(m.group(1)) if m else len(re.findall(r"^\s*\d+[.)]\s", findings, re.M))


def api_reachable(timeout=6):
    """0.4.6 (Rob 2026-11-25, Mac Claude Code screenshot): a sandboxed Bash on the Mac denies api.anthropic.com, so every
    reviewer `claude -p` retried until its 130 s timeout and precheck ran past the Bash tool's 120 s limit (measured in the
    Mac transcript 74086a14: "deny network-outbound api.anthropic.com:443"). Probe once, honouring the proxy settings, and
    report unreachable in seconds. Any HTTP status, or a TLS error after a tunnel opened, counts as reachable."""
    import urllib.request, urllib.error, ssl
    try:
        urllib.request.urlopen(urllib.request.Request("https://api.anthropic.com/", method="HEAD"), timeout=timeout)
        return True, ""
    except urllib.error.HTTPError:
        return True, ""
    except urllib.error.URLError as e:
        r = getattr(e, "reason", e)
        if isinstance(r, ssl.SSLError):
            return True, ""
        return False, str(r)[:160]
    except ssl.SSLError:
        return True, ""
    except Exception as e:
        return False, str(e)[:160]


def cmd_review(path):
    # 0.3.72: the reviewers run in their own folder, so a relative path is unreadable to them and they returned "COUNT: 0"
    # on a draft with three seeded errors (measured 2026-11-19 12:59 PM PST, exit 0). Always hand them the absolute path.
    path = os.path.abspath(path)
    text = open(path, encoding="utf-8").read()
    tz = tzcheck(text)
    ok, why = api_reachable()
    if not ok and os.environ.get("IMC_PANEL_SKIP_PROBE") != "1":
        print("PANEL FAILED: api.anthropic.com is unreachable from this shell (%s). A sandboxed Bash blocks it; the "
              "Stop-hook panel runs outside the sandbox. Use an Agent reviewer for the pre-send review." % why); return 2
    r = panel(path)
    if r["status"] != "ok":
        print("PANEL FAILED: no reviewer returned a result"); return 2
    n = count_of(r["findings"]) + len(tz)
    print("PANEL %d of %d reviewers ok, %.0f s, $%.2f" % (r["reviewers_ok"], len(PANEL), r["secs"], r["cost"]))
    for b in tz: print("TZCHECK: " + b)
    print(r["findings"])
    return 1 if n else 0


def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}


def last_assistant_text(tp):
    last = ""
    with open(tp, encoding="utf-8", errors="replace") as f:
        for ln in f:
            try: e = json.loads(ln)
            except ValueError: continue
            if e.get("type") != "assistant": continue
            c = (e.get("message") or {}).get("content")
            parts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"] if isinstance(c, list) else ([c] if isinstance(c, str) else [])
            t = "\n".join(p for p in parts if p).strip()
            if t: last = t
    return last


def turn_key_of(tp):
    """Fix for the resend loop (F-788): the round cap was keyed on a hash of the reply text, so every corrected
    reply opened with different text, got a new key and a fresh 'Round 1 of 1', and was reviewed again without end
    (measured 2026-10-24: 291 distinct keys in reviewpanel-state.json). Key on the turn instead: the newest real
    user prompt, skipping tool results, sidechains, meta entries and Stop-hook feedback (same rule as gate.py turn_key)."""
    key = None
    try:
        with open(tp, encoding="utf-8", errors="replace") as f:
            for ln in f:
                try: e = json.loads(ln)
                except ValueError: continue
                if e.get("type") != "user" or e.get("isSidechain") or e.get("isMeta"): continue
                if isinstance(e.get("origin"), dict) and e["origin"].get("kind") == "task-notification": continue  # 0.3.22: wake-ups are not prompts
                c = (e.get("message") or {}).get("content")
                if isinstance(c, list):
                    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c): continue
                    c = " ".join(str(b.get("text", "")) for b in c if isinstance(b, dict) and b.get("type") == "text")
                if isinstance(c, str) and c.lstrip().lower().startswith("stop hook feedback"): continue
                key = "turn:" + str(e.get("uuid") or e.get("timestamp") or "unkeyed")
    except Exception:
        return None
    return key


def wakeup_reply(tp):
    """0.3.22: True when the newest real user entry is a background-task notification (origin.kind task-notification);
    such a reply answers a wake-up, not Rob, and is not reviewed (Rob 2026-10-28 10:24 PDT, the wake-up loop)."""
    last = None
    try:
        with open(tp, encoding="utf-8", errors="replace") as f:
            for ln in f:
                try: e = json.loads(ln)
                except ValueError: continue
                if e.get("type") != "user" or e.get("isSidechain") or e.get("isMeta"): continue
                c = (e.get("message") or {}).get("content")
                if isinstance(c, list):
                    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c): continue
                    c = " ".join(str(b.get("text", "")) for b in c if isinstance(b, dict) and b.get("type") == "text")
                if isinstance(c, str) and c.lstrip().lower().startswith("stop hook feedback"): continue
                last = isinstance(e.get("origin"), dict) and e["origin"].get("kind") == "task-notification"
    except Exception:
        return False
    return bool(last)


def cmd_stop():
    try: hin = json.load(sys.stdin)
    except Exception: return 0
    tp = hin.get("transcript_path")
    if not tp or not os.path.isfile(tp): return 0
    if wakeup_reply(tp): return 0
    text = last_assistant_text(tp)
    if len(text) < 400: return 0
    # 0.3.30 (Rob 2026-10-29 23:04 PDT, "Why are there corrections after the table. Fix it"): when this exact text carries a
    # precheck stamp whose panel already ran on the draft, findings were handled before the send; skip the post-send model
    # panel so none can land after the table. The timezone check still runs.
    try:
        import importlib.util as _iu
        _sp = _iu.spec_from_file_location("imc_gate", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gate.py"))
        _g = _iu.module_from_spec(_sp); _sp.loader.exec_module(_g)
        _sha = _g.norm_sha(text)
        _lines = list(_g.prechecked_lines()) if hasattr(_g, "prechecked_lines") else open(os.path.expanduser("~/.claude/imc-reply-gate-prechecked.tsv"), encoding="utf-8", errors="replace").readlines()
        for _f in (_lines,):
            # 0.3.73: a stamp counts when the panel ran on the draft, or when the reply carries a table: a table reply cannot be
            # stamped without an Agent reviewer's record (PRE-SEND-REVIEW), so a session whose panel cannot sign in is not
            # blocked again after an Agent review. A stamped table-less reply whose panel did not run is still reviewed here.
            _ran = any(ln.split("\t")[0].strip() == _sha and ("panel=ran" in ln or "| #" in text) for ln in _f)
    except Exception:
        _ran = False
    if _ran:
        tz1 = tzcheck(text)
        if tz1:
            print(json.dumps({"decision": "block", "reason": "The timezone check found defects in your last reply. Fix each one, then resend.\n" + "\n".join("TZCHECK: " + b for b in tz1) + "\nPrecheck in THIS session: python3 \"%s\" <draft>" % PRECHECK_PATH}))
        return 0
    # 0.3.28 (Rob 2026-10-29 21:19 PDT, OI-0405 second half): no model panel on a table-less reply under 150 words;
    # the deterministic timezone check still runs on it.
    if "| #" not in text and len(text.split()) < 150:
        tz0 = tzcheck(text)
        if not tz0: return 0
        print(json.dumps({"decision": "block", "reason": "The timezone check found defects in your last reply. Fix each one, then resend.\n" + "\n".join("TZCHECK: " + b for b in tz0) + "\nPrecheck in THIS session: python3 \"%s\" <draft>" % PRECHECK_PATH}))
        return 0
    key = turn_key_of(tp) or hashlib.sha256(text[:2000].encode()).hexdigest()[:16]
    st = load_state()
    rounds = st.get(key, 0)
    if rounds >= MAX_ROUNDS: return 0
    d = tempfile.mkdtemp(prefix="reviewpanel-")
    f = os.path.join(d, "reply.md"); open(f, "w").write(text)
    tz = tzcheck(text)
    r = panel(f)
    st[key] = rounds + 1
    try: json.dump(st, open(STATE, "w"))
    except Exception: pass
    if r["status"] != "ok":
        # 0.3.72: fail loudly. A panel that could not run blocks once with the reason, so the reply is not taken as reviewed.
        errs = "; ".join("%s: %s" % (nm, (o.get("error") or "")[:100]) for nm, o in r.get("outs", []))
        print(json.dumps({"decision": "block", "reason": ("PANEL FAILED: the reviewer panel could not run in this session (%s). Your last reply "
              "was NOT independently reviewed. Do not say it was. Have an Agent reviewer read the exact draft file and write its "
              "<draft>.review record, run precheck.py, and send the stamped text; or say plainly, above any table, that no "
              "independent review ran. Round %d of %d.\nPrecheck in THIS session: python3 \"%s\" <draft>" % (errs[:400], rounds + 1, MAX_ROUNDS, PRECHECK_PATH))}))
        return 0
    else:
        findings, n = r["findings"], count_of(r["findings"])
    if tz: findings = "\n".join("TZCHECK: " + b for b in tz) + "\n" + findings
    if n + len(tz) == 0: return 0
    reason = ("The reviewer panel (1 default, 2 small, 1 large model, isolated) found defects in your last reply. Fix each one that is real, "
              "then resend; dispute with a reason any that are not. Round %d of %d.\n%s\nPrecheck in THIS session: python3 \"%s\" <draft>" % (rounds + 1, MAX_ROUNDS, findings.strip(), PRECHECK_PATH))
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def selftest():
    fails = []
    # 1 deterministic tz check: positive and negative controls
    cases = [("fires Nov 9 at 9:00 AM PDT", 1), ("fires Nov 9 at 9:00 AM PST", 0), ("fires Jul 4 at 9:00 AM PST", 1), ("fires Jul 4, 2026 at 9:00 AM PDT", 0), ("fires Oct 17 at 2:08 PM PDT", 0), ("Mar 7 at 1:00 PM PDT", 1), ("Mar 9 at 1:00 PM PDT", 0)]
    for s, want in cases:
        got = len(tzcheck(s, 2026))
        if got != want: fails.append("tzcheck %r: got %d want %d" % (s, got, want))
    # 2 panel flags seeded errors, isolation, time, cost
    d = tempfile.mkdtemp(prefix="reviewpanel-self-")
    f = os.path.join(d, "reply.md")
    open(f, "w").write("The scheduled task has 12 items: 5 done and 4 open, so 9 of 12 are handled. The report was reviewed by 3 reviewers (a, b, c) and all 4 agreed. "
                       "The caching change reduced latency from 200 ms to 150 ms, a 50 percent cut. The next run is Nov 9 at 9:00 AM PDT.\n")
    t = time.time(); r = panel(f); secs = time.time() - t
    if r["status"] != "ok": fails.append("panel failed")
    else:
        txt = r["findings"].lower()
        for label, pat in (("5+4 is not 12", r"(5.*4.*12|9 of 12|12 items)"), ("3 reviewers vs 4 agreed", r"(3 reviewers|all 4|four)"), ("200 to 150 is 25 percent", r"(25 ?(%|percent)|50 ?(%|percent))")):
            if not re.search(pat, txt): fails.append("panel missed seeded error: " + label)
        for n, o in r["outs"]:
            if "CORRECTION:" in o["result"]: fails.append("reviewer %s answered in gate format (not isolated)" % n)
    if secs > HOOK_BUDGET_S - 5: fails.append("panel took %.0f s, over the hook budget" % secs)
    if not tzcheck("Nov 9 at 9:00 AM PDT", 2026): fails.append("tz control")
    # 3 (0.3.72) fail-closed control: a reviewer that returns an auth error with subtype success and $0 must make the panel FAIL
    fd = tempfile.mkdtemp(prefix="reviewpanel-fake-")
    fk = os.path.join(fd, "claude")
    open(fk, "w").write("#!/bin/sh\necho '{\"type\":\"result\",\"subtype\":\"success\",\"is_error\":false,\"result\":\"Authentication error \\u00b7 This may be a temporary network issue, please try again\",\"total_cost_usd\":0}'\n")
    os.chmod(fk, 0o755)
    _old = os.environ.get("PATH", "")
    os.environ["PATH"] = fd + os.pathsep + _old
    try:
        rf = panel(f)
        if rf["status"] != "failed": fails.append("auth-error reviewers counted as a review (status %s)" % rf["status"])
        if cmd_review(f) != 2: fails.append("review mode did not exit 2 when no reviewer ran")
        # 4 (0.3.73) a real, billed review that quotes "Authentication error" must still count as a review
        open(fk, "w").write("#!/usr/bin/env python3\nimport json\nprint(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, "
                            "'result': '1. \"Authentication error\" is quoted without a source.\\nCOUNT: 1', 'total_cost_usd': 0.07}))\n")
        rq = panel(f)
        if rq["status"] != "ok": fails.append("a billed review quoting 'Authentication error' was counted as a failed reviewer")
    finally:
        os.environ["PATH"] = _old
    print("selftest: panel %.0f s, $%.2f, reviewers ok %s" % (secs, r.get("cost", 0), r.get("reviewers_ok")))
    for x in fails: print("FAIL " + x)
    print("SELFTEST PASS" if not fails else "SELFTEST FAIL (%d)" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["review"] and len(a) == 2: sys.exit(cmd_review(a[1]))
    if a[:1] == ["tzcheck"] and len(a) == 2:
        b = tzcheck(open(a[1]).read()); [print("TZCHECK: " + x) for x in b]; sys.exit(1 if b else 0)
    if a[:1] == ["stop"]: sys.exit(cmd_stop())
    if a[:1] == ["selftest"]: sys.exit(selftest())
    print(__doc__); sys.exit(2)
