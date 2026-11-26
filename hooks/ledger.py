#!/usr/bin/env python3
"""ledger.py - imc-reply-gate 0.4.16 EVIDENCE LEDGER (Rob 2026-11-26, O1 "Evidence ledger and reviewer", step 2).

WHY. A reviewer that reads only the reply and the files missed both invented runs (revsem.log, 2026-11-26); one that
checked every run claim against a record of what ran caught all four (revsem4.log). This hook writes that record.

WHAT. A PostToolUse hook. For every tool call it appends ONE line to the session's evidence.log:
    seq  Pacific time  tool  id=<tool_use_id>  in=<sha256[:12] of the input>  cmd=<input excerpt>  out=<output excerpt>  mac=<16 hex>
Fields are tab-separated; tabs and newlines inside an excerpt are written as \\t and \\n. The output excerpt is the first
700 and last 300 characters of the tool's response when it is longer than 1,000.

WHO MAY WRITE IT. Only this hook. mac is an HMAC-SHA256 over the line's other fields and the previous line's mac, keyed
by a random per-session key the hook creates beside the log (.key, mode 600). A line typed by anything else (echo >>,
an editor, a script that does not hold the key) fails `ledger.py verify`, and so does an edited, deleted or reordered
line, because the chain breaks there. preaction.py also refuses any Write, Edit or shell command that names the ledger
folder, except the read-only verbs listed in READERS. LIMIT, said plainly: a process that reads .key can forge a line;
the folder guard is what stops a session from reading it, and a determined bypass of that guard is not covered.

WHERE. ~/.claude/imc-evidence/<session id>/evidence.log (override IMC_EVIDENCE_DIR), in the cloud container and on the Mac.

    python3 ledger.py hook                 PostToolUse mode (JSON on stdin); never blocks, exit 0
    python3 ledger.py path <session>       print the session's evidence.log path
    python3 ledger.py verify <evidence.log> [--key <file>]   one line per bad line, then a summary; exit 1 if any bad
    python3 ledger.py export <session> <dest dir>   copy evidence.log and its key for a reviewer; the only copy route
    python3 ledger.py --selftest
"""
import datetime, hashlib, hmac, json, os, re, secrets, shutil, sys

DIR = os.environ.get("IMC_EVIDENCE_DIR") or os.path.expanduser("~/.claude/imc-evidence")
HEAD, TAIL = 700, 300
READERS = re.compile(r"^\s*(cat|head|tail|grep|rg|wc|ls|stat|sha256sum|shasum|python3?\s+\S*ledger\.py\s+(verify|path|export)|"
                     r"python3?\s+\S*ledgerreview\.py)\b")


def _sname(session):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session or "nosession")


def path(session):
    return os.path.join(DIR, _sname(session), "evidence.log")


def pacific(ts=None):
    t = datetime.datetime.now(datetime.timezone.utc) if ts is None else ts
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        # US Pacific without tzdata: PDT from the second Sunday of March to the first Sunday of November
        def nth_sunday(y, m, n):
            x = datetime.date(y, m, 1); x += datetime.timedelta(days=(6 - x.weekday()) % 7)
            return x + datetime.timedelta(weeks=n - 1)
        d = (t - datetime.timedelta(hours=8)).date()
        dst = nth_sunday(d.year, 3, 2) <= d < nth_sunday(d.year, 11, 1)
        return (t - datetime.timedelta(hours=7 if dst else 8)).strftime("%Y-%m-%d %H:%M:%S ") + ("PDT" if dst else "PST")


def esc(s):
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "").replace("\n", "\\n")


def excerpt(s, head=HEAD, tail=TAIL):
    return s if len(s) <= head + tail else s[:head] + " [...%d chars...] " % (len(s) - head - tail) + s[-tail:]


def _flat(x):
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        out = []
        for b in x:
            if isinstance(b, dict) and "text" in b:
                out.append(str(b["text"]))
            elif isinstance(b, dict) and b.get("type") == "image":
                out.append("[image]")
            else:
                out.append(_flat(b))
        return "\n".join(out)
    if isinstance(x, dict):
        for k in ("stdout", "output", "content", "result", "text"):
            if k in x and x[k] not in (None, ""):
                rest = {kk: vv for kk, vv in x.items() if kk != k and vv not in (None, "", False, [])}
                tail = ("\n" + json.dumps(rest, sort_keys=True, default=str)[:300]) if rest else ""
                return _flat(x[k]) + tail
        return json.dumps(x, sort_keys=True, default=str)
    return "" if x is None else str(x)


def input_summary(tool, ti):
    if isinstance(ti, dict):
        for k in ("command", "file_path", "path", "pattern", "query", "url", "prompt", "message"):
            if ti.get(k):
                return "%s=%s" % (k, str(ti[k]))
    return json.dumps(ti, sort_keys=True, default=str)


def _key(folder):
    kp = os.path.join(folder, ".key")
    if not os.path.exists(kp):
        os.makedirs(folder, exist_ok=True)
        fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    return open(kp).read().strip().encode()


def _mac(key, fields, prev):
    return hmac.new(key, ("\t".join(fields) + "\t" + prev).encode("utf-8", "replace"), hashlib.sha256).hexdigest()[:16]


def _last(lp):
    try:
        with open(lp, "rb") as f:
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 8192))
            lines = [l for l in f.read().decode("utf-8", "replace").split("\n") if l.strip()]
        if lines:
            p = lines[-1].split("\t")
            return int(p[0]), p[-1][4:] if p[-1].startswith("mac=") else ""
    except (OSError, ValueError, IndexError):
        pass
    return 0, ""


def append(session, tool, tinput, tresponse, tool_use_id="", ts=None):
    import fcntl
    lp = path(session)
    folder = os.path.dirname(lp)
    os.makedirs(folder, exist_ok=True)
    key = _key(folder)
    raw_in = json.dumps(tinput, sort_keys=True, default=str)
    with open(os.path.join(folder, ".lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        seq, prev = _last(lp)
        fields = [str(seq + 1), pacific(ts), tool or "?", "id=" + (tool_use_id or "-"),
                  "in=" + hashlib.sha256(raw_in.encode()).hexdigest()[:12],
                  "cmd=" + esc(excerpt(input_summary(tool, tinput), 300, 100)),
                  "out=" + esc(excerpt(_flat(tresponse)))]
        line = "\t".join(fields) + "\tmac=" + _mac(key, fields, prev)
        with open(lp, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return line


def verify(lp, keyfile=None):
    """Return (n_lines, list of (line_no, reason))."""
    keyfile = keyfile or os.path.join(os.path.dirname(lp), ".key")
    key = open(keyfile).read().strip().encode()
    bad, prev, want_seq, n = [], "", 1, 0
    for i, line in enumerate(open(lp, encoding="utf-8", errors="replace").read().split("\n"), 1):
        if not line.strip():
            continue
        n += 1
        p = line.split("\t")
        if len(p) != 8 or not p[-1].startswith("mac="):
            bad.append((i, "FORGED: not a hook-written line (wrong shape: %d fields)" % len(p)))
            continue
        fields, mac = p[:-1], p[-1][4:]
        if _mac(key, fields, prev) != mac:
            bad.append((i, "FORGED: mac does not verify (line not written by the hook, or edited)"))
        elif fields[0] != str(want_seq):
            bad.append((i, "CHAIN BREAK: seq %s where %d was expected (a line was removed or reordered)" % (fields[0], want_seq)))
        prev = mac
        try:
            want_seq = int(fields[0]) + 1
        except ValueError:
            want_seq += 1
    return n, bad


def guard(tool, tinput):
    """(0, why) allow / (2, message) refuse: nothing but this hook writes the ledger folder. Only the ledger root
    (~/.claude/imc-evidence or IMC_EVIDENCE_DIR) is guarded; other files that happen to be called evidence.log are not."""
    FOLDER_RE = re.compile("imc-evidence|" + re.escape(DIR))
    t = tinput if isinstance(tinput, dict) else {}
    if tool in ("Write", "Edit", "NotebookEdit", "MultiEdit") or tool.endswith(("write_file", "edit_block", "move_file", "edit_file", "create_directory")):
        target = " ".join(str(t.get(k, "")) for k in ("file_path", "path", "source", "destination", "notebook_path"))
        if FOLDER_RE.search(target):
            return 2, ("imc-reply-gate EVIDENCE LEDGER: only the PostToolUse hook writes the ledger (%s). This %s call targets it "
                       "and is refused. Read it with cat/grep, or copy it with: python3 ledger.py export <session> <dest>" % (target.strip(), tool))
        return 0, "not the ledger"
    cmd = t.get("command") or t.get("script") or ""
    if isinstance(cmd, str) and FOLDER_RE.search(cmd):
        segs = [s for s in re.split(r"&&|\|\||;|\n|\|", cmd) if FOLDER_RE.search(s)]
        if re.search(r"(?<![&<])>{1,2}|\btee\b|-i\b|--in-place", cmd) and any(FOLDER_RE.search(s) for s in re.split(r">{1,2}", cmd)[1:]):
            pass  # a redirect into the ledger: refused below
        elif all(READERS.match(s) for s in segs):
            return 0, "read-only use of the ledger"
        return 2, ("imc-reply-gate EVIDENCE LEDGER: only the PostToolUse hook writes the ledger. This command names the "
                   "ledger folder with something other than a read (%s), so it is refused. Read with cat/grep/head/tail/wc, "
                   "verify with ledger.py verify, copy with ledger.py export." % cmd[:160])
    return 0, "not the ledger"


def hook():
    try:
        d = json.load(sys.stdin)
        append(d.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "", d.get("tool_name", ""),
               d.get("tool_input"), d.get("tool_response", d.get("tool_output")), d.get("tool_use_id", ""))
    except Exception as e:
        try:
            os.makedirs(DIR, exist_ok=True)
            with open(os.path.join(DIR, "ledger-errors.log"), "a") as f:
                f.write("%s %s: %s\n" % (pacific(), type(e).__name__, e))
        except Exception:
            pass
    return 0


def export(session, dest):
    src = path(session)
    os.makedirs(dest, exist_ok=True)
    shutil.copy2(src, os.path.join(dest, "evidence.log"))
    shutil.copy2(os.path.join(os.path.dirname(src), ".key"), os.path.join(dest, ".ledger-key"))
    os.chmod(os.path.join(dest, ".ledger-key"), 0o600)
    return os.path.join(dest, "evidence.log")


def selftest():
    global DIR
    import tempfile
    DIR = tempfile.mkdtemp()
    res = []
    def t(name, got, want):
        res.append(got == want); print(("  ok    " if got == want else "  BAD   ") + name + ("" if got == want else "  got %r want %r" % (got, want)))
    S = "self-1"
    append(S, "Bash", {"command": "wc -l a.txt"}, {"stdout": "42 a.txt", "stderr": ""}, "toolu_A")
    append(S, "Read", {"file_path": "/x/y.md"}, "line1\nline2\twith tab", "toolu_B")
    append(S, "Bash", {"command": "echo big"}, {"stdout": "x" * 5000}, "toolu_C")
    lp = path(S)
    lines = open(lp).read().splitlines()
    t("three hook lines written", len(lines), 3)
    t("each line has 8 tab fields", [len(l.split("\t")) for l in lines], [8, 8, 8])
    t("time is Pacific", bool(re.search(r"\tP[SD]T\t|\d P[SD]T\t", lines[0])), True)
    t("a long output is cut to head and tail", "[..." in lines[2] and len(lines[2]) < 1400, True)
    t("an untouched ledger verifies clean", verify(lp)[1], [])
    with open(lp, "a") as f:
        f.write("4\t2026-11-26 09:30:00 PST\tBash\tid=toolu_FAKE\tin=000000000000\tcmd=command=pytest\tout=12 passed\tmac=0123456789abcdef\n")
    n, bad = verify(lp)
    t("MUTATION a forged line appended with echo is caught", [b[0] for b in bad], [4])
    open(lp, "w").write("\n".join(lines[:1] + [lines[1].replace("line1", "LINE1")] + lines[2:]) + "\n")
    t("MUTATION an edited output excerpt is caught", [b[0] for b in verify(lp)[1]], [2])
    open(lp, "w").write("\n".join([lines[0], lines[2]]) + "\n")
    t("MUTATION a deleted line breaks the chain", bool(verify(lp)[1]), True)
    open(lp, "w").write("\n".join(lines) + "\n")
    t("restored ledger verifies clean again", verify(lp)[1], [])
    t("GUARD refuses Write to the ledger", guard("Write", {"file_path": lp, "content": "x"})[0], 2)
    t("GUARD refuses echo >> evidence.log", guard("Bash", {"command": "echo hi >> %s" % lp})[0], 2)
    t("GUARD refuses sed -i on the ledger", guard("Bash", {"command": "sed -i s/a/b/ %s" % lp})[0], 2)
    t("GUARD refuses cp over the ledger", guard("Bash", {"command": "cp /tmp/f %s" % lp})[0], 2)
    t("GUARD refuses python writing the ledger", guard("Bash", {"command": "python3 -c \"open('%s','a').write('x')\"" % lp})[0], 2)
    t("GUARD refuses Desktop Commander write_file to the ledger", guard("mcp__remote-devices__Desktop_Commander__write_file", {"path": lp, "content": "x"})[0], 2)
    t("GUARD allows cat and grep of the ledger", guard("Bash", {"command": "cat %s | grep wc" % lp})[0], 0)
    t("GUARD allows ledger.py verify", guard("Bash", {"command": "python3 /h/ledger.py verify %s" % lp})[0], 0)
    t("GUARD allows an unrelated Write", guard("Write", {"file_path": "/tmp/draft.md", "content": "x"})[0], 0)
    t("GUARD allows writing some other evidence.log (the 2026-11-26 prototype's ledger.sh)", guard("Bash", {"command": "echo x | tee -a ~/Claude/tmp/review-20261126/o1smoke/evidence.log"})[0], 0)
    t("GUARD refuses tee into the real ledger root", guard("Bash", {"command": "echo x | tee -a ~/.claude/imc-evidence/s/evidence.log"})[0], 2)
    out = export(S, os.path.join(DIR, "exp"))
    t("export copy verifies with the exported key", verify(out, os.path.join(DIR, "exp", ".ledger-key"))[1], [])
    print("ALL CONTROLS PASSED" if all(res) else "A CONTROL FAILED")
    return all(res)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--selftest"]:
        sys.exit(0 if selftest() else 1)
    if a[:1] == ["hook"]:
        sys.exit(hook())
    if a[:1] == ["path"] and len(a) == 2:
        print(path(a[1])); sys.exit(0)
    if a[:1] == ["export"] and len(a) == 3:
        print(export(a[1], a[2])); sys.exit(0)
    if a[:1] == ["verify"] and len(a) >= 2:
        kf = a[a.index("--key") + 1] if "--key" in a else None
        n, bad = verify(a[1], kf)
        for i, why in bad:
            print("LINE %d %s" % (i, why))
        print("LEDGER-VERIFY: %d lines, %d bad" % (n, len(bad)))
        sys.exit(1 if bad else 0)
    print(__doc__); sys.exit(1)
