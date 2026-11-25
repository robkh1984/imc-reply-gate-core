#!/usr/bin/env python3
"""preaction.py - imc-reply-gate 0.3.0 PRE-ACTION gate (Rob 2026-10-23 09:40 PDT).

Rob's ruling: the gate applies across ALL Claude projects, sessions and tasks, BEFORE the action or request,
not only to the reply that reports it. This hook runs as PreToolUse on write-class tools. It refuses the call
unless a fresh stamp names three things: the ACTION, the OBJECTIVE it serves, and the ROOT CAUSE it addresses
(or the words "no defect: <why>" when nothing is being fixed).

  Stamp:   python3 preaction.py stamp --action "..." --objective "..." --cause "..." [--minutes 30]
  Hook:    python3 preaction.py hook          (reads the PreToolUse JSON on stdin; exit 2 = refuse)
  Selftest: python3 preaction.py --selftest

READ-ONLY CALLS PASS WITHOUT A STAMP (an allowlist, not a guess): Bash commands whose every segment starts with a
read-only program and carries no redirection, no in-place flag and no write verb. Anything the allowlist does not
recognise is treated as a write. A stamp is per session id (CLAUDE_SESSION_ID or the hook's session_id) and expires.
The stamp store is ~/.claude/imc-preaction/ (override with IMC_PREACTION_DIR). IMC_PREACTION=off disables the
hook and the hook logs that it was off, so a disabled gate is visible rather than silent.
"""
import json, os, re, sys, time, hashlib

DIR = os.environ.get("IMC_PREACTION_DIR") or os.path.expanduser("~/.claude/imc-preaction")
READ_PROGS = {"ls", "cat", "head", "tail", "grep", "rg", "wc", "stat", "file", "pwd", "echo", "date", "diff", "cmp",
              "sort", "uniq", "cut", "tr", "basename", "dirname", "realpath", "which", "type", "env", "printenv",
              "md5sum", "sha256sum", "shasum", "find", "awk", "sed", "jq", "tree", "du", "df", "id", "whoami",
              "python3", "python"}
WRITE_FLAGS = re.compile(r"(^|\s)(-i\b|--in-place|-delete\b|-exec\b|-execdir\b|-fprint)", re.I)
WRITE_VERBS = re.compile(r"\b(rm|mv|cp|chmod|chown|mkdir|touch|tee|dd|kill|curl\s+[^|;]*-X\s*(POST|PUT|DELETE|PATCH)|"
                         r"git\s+(commit|push|reset|checkout|rebase|merge|add|rm)|pip\s+install|npm\s+(install|publish)|"
                         r"clasp\s+push|launchctl|osascript)\b")
REDIRECT = re.compile(r"(?<![&<])>{1,2}(?!&)(?!\s*/dev/null)|\|\s*tee\b")  # 0.3.60: a digit before > (1>file) is a write
PY_WRITE = re.compile(r"(open\([^)]*['\"][wa+x]|write_text|write_bytes|\.write\(|os\.(remove|rename|unlink|system)|"
                      r"shutil\.|subprocess|requests\.(post|put|delete)|urlopen)")
# tools that only read
READ_TOOLS = re.compile(r"^(Read|Glob|Grep|ToolSearch|WebFetch|WebSearch|TaskList|TaskGet|ListAgents|"
                        r"mcp__[A-Za-z0-9_\-]+__(get|list|read|search|find|fetch|query|lookup|check|describe|whoami)[A-Za-z0-9_\-]*)$")
# tools whose job is to write
WRITE_TOOLS = re.compile(r"^(Write|Edit|NotebookEdit|Bash|Agent|"
                         r"mcp__remote-devices__(device_bash|device_commit_files|Control_your_Mac__osascript|"
                         r"Desktop_Commander__(write_file|edit_block|start_process|move_file|create_directory|interact_with_process|kill_process)|"
                         r"plugin_desktop-commander_desktop-commander__(write_file|edit_block|start_process|move_file|create_directory)|"
                         r"computer_(left_click|type|key|batch).*|Control_Chrome__(execute_javascript|open_url))|"
                         r"mcp__claude-code-remote__(create_trigger|update_trigger|delete_trigger|fire_trigger|send_later)|"
                         r"mcp__memory__memory_(write|append|str_replace|delete)|"
                         r"mcp__Google_(Drive__(update_file|create_file|copy_file|trash_file|share_file)|Docs__update_doc|Sheets__(update|append|batch|insert).*)|"
                         r"mcp__Gmail__(send_message|reply|forward|trash.*|create_draft)|"
                         r"mcp__claude-in-chrome__(computer|form_input|javascript_tool|navigate|file_upload)|"
                         r"mcp__Notion__notion-(create|update|delete|move).*|Artifact|Skill|SendMessage)$")


def _segments(cmd):
    return [s.strip() for s in re.split(r"&&|\|\||;|\n|\|", cmd) if s.strip()]


STAMP_CMD = re.compile(r"^\s*python3?\s+\"?[^\s\"]*preaction\.py\"?\s+stamp\s+((--multi\s*)|(--(action|objective|cause|minutes|session)\s+(\"[^\"]*\"|'[^']*'|\S+)\s*))+\.?\s*$")  # 0.3.61: --multi is valueless


def bash_is_readonly(cmd):
    if STAMP_CMD.match(cmd):   # the stamp command must not need a stamp, or the gate deadlocks itself
        return True
    if REDIRECT.search(cmd) or WRITE_FLAGS.search(cmd) or WRITE_VERBS.search(cmd):
        return False
    for seg in _segments(cmd):
        toks = seg.split()
        while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
            toks = toks[1:]
        if not toks:
            continue
        prog = os.path.basename(toks[0])
        if prog not in READ_PROGS:
            return False
        if prog in ("python3", "python") and (PY_WRITE.search(cmd) or not re.search(r"\s-(c|I\s+-c|m\s+json\.tool)\b|--selftest|\.py\b.*--(selftest|check|verify)", seg)):
            # python is read-only only for -c snippets with no write call and for selftest/check flags
            return False
        if prog == "sed" and WRITE_FLAGS.search(seg):
            return False
        if prog in ("sort", "uniq", "tree") and re.search(r"(^|\s)(-o\b|--output)", seg):  # 0.3.60: sort -o FILE writes
            return False
    return True


def is_write(tool, tinput):
    if READ_TOOLS.match(tool):
        return False
    if tool == "Bash" or tool.endswith("device_bash") or tool.endswith("start_process"):
        cmd = (tinput or {}).get("command", "")
        return not bash_is_readonly(cmd)
    if tool == "Projects":  # 0.3.58: project_write and project_delete change Rob's project docs; measured 2026-11-17 that they passed unstamped
        return (tinput or {}).get("method") not in ("project_info", "project_read", "project_search", "project_memory_list", "project_memory_read")  # 0.3.60: allowlist, unknown methods are writes
    if WRITE_TOOLS.match(tool):
        return True
    if not tool.startswith("mcp__"):  # 0.3.60: default-deny for every other built-in tool (Monitor, ScheduleWakeup, TaskCreate, ...)
        return not READ_TOOLS.match(tool)
    return not READ_TOOLS.match(tool) and tool.startswith("mcp__") and not re.search(r"__(get|list|read|search|find|fetch|query|lookup)", tool)


def _path(session):
    return os.path.join(DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", session or "nosession") + ".json")


def write_stamp(session, action, objective, cause, minutes=30, now=None, multi=False):
    now = now or time.time()
    if not session or session in ("UNKNOWN", "nosession"):
        return "refused: no session id; pass --session <id> exactly as the refusal message printed it (0.3.1: a stamp with no session id never satisfied the hook)"
    for k, v in (("action", action), ("objective", objective), ("cause", cause)):
        if not v or len(v.strip()) < 12:
            return "refused: %s is empty or under 12 characters" % k
    os.makedirs(DIR, exist_ok=True)
    rec = {"action": action.strip(), "objective": objective.strip(), "cause": cause.strip(),
           "stamped": now, "expires": now + 60 * minutes}
    if multi:
        rec["multi"] = True                      # 0.3.61: a declared batch
    rec["sha"] = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()[:16]
    with open(_path(session), "w") as f:
        json.dump(rec, f)
    return "ok"


def check_stamp(session, now=None):
    now = now or time.time()
    try:
        rec = json.load(open(_path(session)))
    except Exception as e:
        return False, "no stamp for this session (%s)" % type(e).__name__
    if rec.get("expires", 0) < now:
        return False, "the stamp expired %d minutes ago" % ((now - rec["expires"]) // 60)
    for k in ("action", "objective", "cause"):
        if len((rec.get(k) or "").strip()) < 12:
            return False, "the stamp's %s is empty" % k
    # 0.3.61: one stamp authorises one write. Measured 2026-11-17 on session 1056270b:
    # a stamp reading "Read the sheet tab ids and measure the exact write payload"
    # authorised three live worksheet writes at 12:27:08, 12:28:08 and 12:28:53, and a
    # stale stamp reading "verify the reviewer's headline finding" authorised two reverts
    # at 14:22:06 and 14:37:35. Five of ten writes were gated by a description of
    # something else, because check_stamp never marked the record used.
    if rec.get("used") and not rec.get("multi"):
        return False, ("this stamp was already used by a write at %s, for the action %r. One stamp "
                       "authorises one write: re-stamp with the action you are about to take, or pass "
                       "--multi when one stamp genuinely covers a batch"
                       % (time.strftime("%H:%M:%S", time.localtime(rec["used"])), (rec.get("action") or "")[:70]))
    return True, rec


DEF_MUTATE = re.compile(r"(^|[;&|]\s*)(cp|mv|rm|rmdir|install|dd|tee|chmod|chown|mkdir|touch|ln|truncate|patch|unzip|tar)\b"
                        r"|>{1,2}\s*[^\s&]|sed\s+(-\S*\s+)*-i|open\([^)]*[\"']w|writeFileSync|\.write\(", re.I)


def definitely_mutates(tool, tinput):
    """0.3.61: gating is deliberately broad; BINDING must be precise, or a read that the
    gate conservatively called a write spends the stamp the following write needs."""
    if tool in ("Write", "Edit", "NotebookEdit"):
        return True
    if tool == "Bash":
        return bool(DEF_MUTATE.search((tinput or {}).get("command") or ""))
    return is_write(tool, tinput)


def consume_stamp(session, now=None):
    """0.3.61: mark the stamp used so the next write needs its own."""
    try:
        pth = _path(session)
        rec = json.load(open(pth))
    except Exception:
        return False
    if rec.get("used"):
        return False
    rec["used"] = now or time.time()
    try:
        json.dump(rec, open(pth, "w"))
    except Exception:
        return False
    return True


# 0.3.75 (Rob 2026-11-19 7:11 AM PST, "ignored the requirements to test ... precheck, reply gate, and an independent reviewer"):
# measured in the Delete sweep run's session cse_014Hc2SadpAwF7YPy5xxR5WH and two test runs, the auto-mode permission check
# refused this gate's own stamp command as "[Undermining Oversight]", including the stamp before "write the final message draft
# ... and run checker/precheck.py" and the reviewer's hand-back. A self-written stamp reads as self-approval, so the gate blocked
# the very checks it exists to force. The reply-gate pipeline steps therefore pass without a stamp: running the plug-in's own
# checkers on a draft, writing a draft or review record in a temp or scratchpad folder, and launching or returning from a reviewer.
GATE_SCRIPT = re.compile(r"""^\s*(?:timeout\s+\d+\s+)?python3?\s+(?:-I\s+)?["']?(?:/root|/Users/[^/\s"']+|/home/[^/\s"']+)/\.claude/(?:plugins/synced/[^/\s"'.][^/\s"']*/imc-reply-gate[^/\s"']*|imc-reply-gate-core/v[0-9]+-[0-9a-f]{12})/(?:checker/(?:precheck|replycheck)\.py|hooks/reviewpanel\.py)["']?(?:\s+(?:review|tzcheck))?(?:\s+["']?[^\s"';&|<>]+["']?)?\s*$""")
DRAFT_PATH = re.compile(r"^(?:/tmp/|.*/scratchpad/)[^\0]*\.md(?:\.review|\.reviewed)?$")


def is_gate_pipeline(tool, tinput):
    t = tinput or {}
    if tool == "Bash":
        cmd = t.get("command") or ""
        segs = _segments(cmd)
        return bool(segs) and not REDIRECT.search(cmd) and all(GATE_SCRIPT.match(x) for x in segs)
    if tool in ("Write", "Edit"):
        fp = t.get("file_path") or ""
        return bool(DRAFT_PATH.match(fp)) and ".." not in fp
    # 0.3.76: SendUserMessage too. gate.py already refuses an unstamped table or long message there, and measured
    # 2026-11-19 2:07 PM PST in session c68f1f48: gate.py's PreToolUse hook recorded a stamped reply as sent, then this
    # hook denied the same call for want of a stamp, so the retry was refused as DUPLICATE-SEND and nothing reached Rob.
    return tool in ("Agent", "SubagentHandback", "SendUserMessage")


def decide(tool, tinput, session, now=None, off=False):
    if off:
        return 0, "PREACTION OFF (IMC_PREACTION=off): not enforced"
    if not is_write(tool, tinput):
        return 0, "read-only"
    if is_gate_pipeline(tool, tinput):
        return 0, "reply-gate pipeline step (0.3.75): no stamp needed"
    ok, rec = check_stamp(session, now)
    if ok:
        if not rec.get("multi") and definitely_mutates(tool, tinput):
            consume_stamp(session, now)          # 0.3.61
        return 0, "stamped: %s" % rec["action"][:80]
    return 2, ("imc-reply-gate PRE-ACTION: %s on %s needs a stamp BEFORE it runs. Rob 2026-10-23: the gate applies before the action, "
               "not after. Run this ONE command, alone, exactly as printed on the next line (no cd, no redirect, no text after it):\npython3 \"%s\" stamp --action \"what this call does\" --objective \"the objective it serves\" "
               "--cause \"the root cause it fixes, or 'no defect: why this is not a fix'\" --session %s\nReason: %s." %
               (tool, "this session", os.path.abspath(__file__), session or "UNKNOWN", rec))


def hook():
    try:
        d = json.load(sys.stdin)
    except Exception:
        print("PREACTION: unreadable hook input; refusing", file=sys.stderr)
        return 2
    session = d.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    code, msg = decide(d.get("tool_name", ""), d.get("tool_input") or {}, session, off=os.environ.get("IMC_PREACTION") == "off")
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(os.path.join(DIR, "preaction.log"), "a") as f:
            f.write("%s\t%s\t%s\t%d\t%s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), session[:12], d.get("tool_name", ""), code, msg[:120]))
    except Exception:
        pass
    if code:
        print(msg, file=sys.stderr)
    return code


def selftest():
    global DIR
    import tempfile
    DIR = tempfile.mkdtemp()
    res = []
    def t(name, got, want):
        res.append(got == want); print(("  ok    " if got == want else "  BAD   ") + name + ("" if got == want else "  got %r want %r" % (got, want)))
    S = "sess-1"
    t("Read passes with no stamp", decide("Read", {"file_path": "/x"}, S)[0], 0)
    t("Bash ls passes with no stamp", decide("Bash", {"command": "ls -la /tmp | head"}, S)[0], 0)
    t("Bash grep+wc passes", decide("Bash", {"command": "grep -n foo a.txt | wc -l"}, S)[0], 0)
    t("MUTATION Bash redirect is a write", decide("Bash", {"command": "echo hi > /tmp/x"}, S)[0], 2)
    t("MUTATION Bash rm is a write", decide("Bash", {"command": "rm -rf /tmp/x"}, S)[0], 2)
    t("MUTATION sed -i is a write", decide("Bash", {"command": "sed -i s/a/b/ f"}, S)[0], 2)
    t("MUTATION python writing a file is a write", decide("Bash", {"command": "python3 -c \"open('f','w').write('x')\""}, S)[0], 2)
    t("python3 -c read snippet passes", decide("Bash", {"command": "python3 -c \"print(1+1)\""}, S)[0], 0)
    t("the stamp command itself passes with no stamp", decide("Bash", {"command": 'python3 "/x/preaction.py" stamp --action "edit the file now" --objective "gate for all" --cause "rule not enforced"'}, "fresh")[0], 0)
    _pm = decide("Skill", {}, "sess-pm")[1]
    _pc = _pm.split("\n")[1]
    t("0.3.11 the command printed in the refusal matches the stamp pattern as printed", bool(STAMP_CMD.match(_pc)), True)
    t("0.3.11 the old copy with a trailing ' .' still passes the hook", decide("Bash", {"command": _pc + " ."}, "fresh")[0], 0)
    t("MUTATION a stamp command with a cd prefix is still refused", decide("Bash", {"command": "cd /tmp && " + _pc}, "fresh")[0], 2)
    t("MUTATION a stamp command with a redirect is still refused", decide("Bash", {"command": _pc + " 2>&1"}, "fresh")[0], 2)
    t("MUTATION a stamp command chained with rm is refused", decide("Bash", {"command": 'python3 /x/preaction.py stamp --action "aaaaaaaaaaaa" --objective "bbbbbbbbbbbb" --cause "cccccccccccc"; rm -rf /tmp/x'}, "fresh")[0], 2)
    t("MUTATION unknown program is a write", decide("Bash", {"command": "frobnicate --now"}, S)[0], 2)
    t("MUTATION Write with no stamp is refused", decide("Write", {"file_path": "/x", "content": "y"}, S)[0], 2)
    t("MUTATION create_trigger with no stamp is refused", decide("mcp__claude-code-remote__create_trigger", {}, S)[0], 2)
    t("MUTATION memory_write with no stamp is refused", decide("mcp__memory__memory_write", {}, S)[0], 2)
    t("MUTATION an unknown MCP write tool is refused", decide("mcp__Foo__do_the_thing", {}, S)[0], 2)
    t("an MCP list_ tool passes", decide("mcp__claude-code-remote__list_triggers", {}, S)[0], 0)
    t("MUTATION a stamp with no session id is refused", write_stamp("", "edit the checker file", "gate for all projects", "ordering rule was not enforced in code").startswith("refused"), True)
    _m = decide("Write", {"file_path": "/x"}, "sess-msg")[1]
    t("the refusal message carries the session id", "--session sess-msg" in _m, True)
    t("the printed session id stamps and then passes", (write_stamp(_m.split("--session ")[1].split()[0], "edit the checker file", "gate for all projects", "ordering rule was not enforced in code"), decide("Write", {"file_path": "/x"}, "sess-msg")[0]), ("ok", 0))
    t("stamp with a short cause is refused", write_stamp(S, "edit the checker file", "gate for all projects", "x").startswith("refused"), True)
    t("stamp written", write_stamp(S, "edit the checker file", "gate for all projects", "ordering rule was not enforced in code"), "ok")
    t("Write passes with a fresh stamp", decide("Write", {"file_path": "/x"}, S)[0], 0)
    t("MUTATION another session's call is refused", decide("Write", {"file_path": "/x"}, "sess-2")[0], 2)
    t("MUTATION an expired stamp is refused", decide("Write", {"file_path": "/x"}, S, now=time.time() + 31 * 60)[0], 2)
    t("off switch is reported, not silent", "OFF" in decide("Write", {}, "sess-3", off=True)[1], True)
    t("0.3.58 Projects project_write is a write", is_write("Projects", {"method": "project_write"}), True)
    t("0.3.58 Projects project_delete is a write", is_write("Projects", {"method": "project_delete"}), True)
    t("0.3.58 Projects project_read stays read-only", is_write("Projects", {"method": "project_read"}), False)
    t("0.3.58 Projects project_search stays read-only", is_write("Projects", {"method": "project_search"}), False)
    t("0.3.58 an unstamped project_write is refused", decide("Projects", {"method": "project_write"}, "sess-pw")[0], 2)
    t("0.3.58 an unstamped project_read is allowed", decide("Projects", {"method": "project_read"}, "sess-pw")[0], 0)
    # --- 0.3.61 controls: one stamp authorises one write -------------------------
    SU = "selftest-used"
    write_stamp(SU, "revert four rows of the live prompt library", "Objective 2 undo a bad conversion", "the test that certified it could not fail")
    t("0.3.61 a fresh stamp authorises a write", decide("Write", {"file_path": "/x", "content": "y"}, SU)[0], 0)
    t("0.3.61 MUTATION the same stamp cannot authorise a second write", decide("Write", {"file_path": "/x", "content": "y"}, SU)[0], 2)
    t("0.3.61 the refusal names the first write's action", "revert four rows" in decide("Write", {"file_path": "/x", "content": "y"}, SU)[1], True)
    t("0.3.61 a read still passes after the stamp is spent", decide("Read", {"file_path": "/x"}, SU)[0], 0)
    write_stamp(SU, "apply twenty-four conversion operations as one batch", "Objective 2 the approved batch", "no defect: a genuine batch")
    _r = json.load(open(_path(SU))); _r["multi"] = True; json.dump(_r, open(_path(SU), "w"))
    t("0.3.61 CONTROL an explicit --multi stamp still covers several writes",
      [decide("Write", {"file_path": "/x", "content": "y"}, SU)[0] for _ in range(3)], [0, 0, 0])
    write_stamp(SU, "a stamp that will be expired by hand", "Objective 2 expiry control", "no defect: expiry control")
    _r = json.load(open(_path(SU))); _r["expires"] = time.time() - 10; _r.pop("used", None); json.dump(_r, open(_path(SU), "w"))
    t("0.3.61 CONTROL an expired stamp is still refused", decide("Write", {"file_path": "/x", "content": "y"}, SU)[0], 2)
    t("0.3.61 consume_stamp is idempotent", (consume_stamp(SU), consume_stamp(SU))[1], False)
    _mc = _pc + " --multi"
    t("0.3.61 a stamp command carrying --multi still matches STAMP_CMD", bool(STAMP_CMD.match(_mc)), True)
    t("0.3.61 a stamp command carrying --multi passes the hook", decide("Bash", {"command": _mc}, "fresh")[0], 0)
    SP = "selftest-precise"
    write_stamp(SP, "write one file after a few reads", "Objective 2 binding precision", "a piped read spent the stamp")
    t("0.3.61 MUTATION a piped read does NOT spend the stamp", [decide("Bash", {"command": "grep -n x f | head -3"}, SP)[0] for _ in range(3)], [0, 0, 0])
    t("0.3.61 a cp DOES spend it", decide("Bash", {"command": "cp a b"}, SP)[0], 0)
    t("0.3.61 MUTATION and the next write is then refused", decide("Bash", {"command": "cp c d"}, SP)[0], 2)
    t("0.3.61 definitely_mutates: redirect", definitely_mutates("Bash", {"command": "echo hi > f"}), True)
    t("0.3.61 definitely_mutates: python open for write", definitely_mutates("Bash", {"command": "python3 -c \"open('f','w').write('x')\""}), True)
    t("0.3.61 definitely_mutates: plain read is not a mutation", definitely_mutates("Bash", {"command": "cat f | wc -l"}), False)
    SM = "selftest-multi-stored"
    write_stamp(SM, "a declared batch of several writes", "Objective 2 the stored multi flag", "the flag was accepted but never written to the record", multi=True)
    t("0.3.61 --multi is STORED in the stamp record", json.load(open(_path(SM))).get("multi"), True)
    t("0.3.61 a stored multi stamp survives three writes",
      [decide("Write", {"file_path": "/x", "content": "y"}, SM)[0] for _ in range(3)], [0, 0, 0])
    write_stamp(SM, "a single-write stamp with no multi flag", "Objective 2 the default", "no defect: default control")
    t("0.3.61 CONTROL without --multi the record has no multi key", json.load(open(_path(SM))).get("multi"), None)
    print("ALL CONTROLS PASSED" if all(res) else "A CONTROL FAILED")
    return all(res)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--selftest"]:
        sys.exit(0 if selftest() else 1)
    if a[:1] == ["hook"]:
        sys.exit(hook())
    if a[:1] == ["stamp"]:
        import argparse
        p = argparse.ArgumentParser(); p.add_argument("stamp")
        for k in ("action", "objective", "cause"): p.add_argument("--" + k, required=True)
        p.add_argument("--minutes", type=int, default=30); p.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", ""))
        p.add_argument("--multi", action="store_true")  # 0.3.61
        n, _extra = p.parse_known_args(a)   # 0.3.11: a stray trailing '.' copied from the old message must not break the stamp
        r = write_stamp(n.session, n.action, n.objective, n.cause, n.minutes, multi=getattr(n, "multi", False)); print(r); sys.exit(0 if r == "ok" else 1)
    print(__doc__); sys.exit(1)
