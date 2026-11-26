#!/usr/bin/env python3
"""releaselock.py - imc-reply-gate 0.4.16 RELEASE FREEZE (Rob 2026-11-26, O1 step 1).

Rob's ruling (O1 "Evidence ledger and reviewer", 2026-11-26): while O1 runs, no session but the one that holds the
lock may release the gate core. A release is any push of a commit to github.com/robkh1984/imc-reply-gate-core
(README: "commit to main"), so the lock must be checked in every session, before the push runs.

THE LOCK is the file RELEASE-LOCK at the root of the core repository. Its first line is "holder=<session id>".
It lives in the repository, not on one machine, because a cloud session and the Mac share nothing else. The lock is
lifted by deleting the file in a commit. check() has no exception for that commit: a push from any session other than
the holder is refused, a delete-only push included, so the deletion is pushed by the holder session or by Rob directly
on GitHub, outside any gated session. (Corrected 2026-11-26 on Rob's step 4; the earlier text said any session could.)

THE CHECK runs from preaction.py's every-tool PreToolUse hook. A call is a RELEASE when its input names a push to
the core repository: "git push" run in, or with -C pointing at, a clone whose origin is imc-reply-gate-core; or any
call whose input text names imc-reply-gate-core together with a push verb (git push, gh api PUT/POST/PATCH/DELETE on
contents or git refs, push_files, create_or_update_file). A release from a session that is not the holder is refused
with exit 2. If the lock cannot be read, a release is refused (fail closed); every other call passes untouched.

    python3 releaselock.py --selftest    controls; exit 0 all pass
    python3 releaselock.py status        prints the live lock as read now
Overrides: IMC_RELEASE_LOCK_FILE (read the lock from this file, for tests), IMC_RELEASE_LOCK_URL.
"""
import json, os, re, subprocess, sys, time, urllib.request

REPO = "imc-reply-gate-core"
URL = os.environ.get("IMC_RELEASE_LOCK_URL", "https://raw.githubusercontent.com/robkh1984/imc-reply-gate-core/main/RELEASE-LOCK")
API = "https://api.github.com/repos/robkh1984/imc-reply-gate-core/contents/RELEASE-LOCK?ref=main"
PUSH_VERB = re.compile(r"(\bgit\b[^|;&\n]*\bpush\b|\bgh\s+api\b[^|;&\n]*(-X\s*|--method\s+)(PUT|POST|PATCH|DELETE)|"
                       r"push_files|create_or_update_file|GITHUB_(?!GET|LIST|SEARCH)[A-Z_]*(COMMIT|PUSH|REFERENCE|REF\b|TREE|BLOB|FILE|CONTENT)[A-Z_]*|"
                       r"(git/(refs|commits|trees|blobs)|/contents/)[^\n]{0,400}?\"(method)\"\s*:\s*\"(PUT|POST|PATCH|DELETE)\"|"
                       r"\"(method)\"\s*:\s*\"(PUT|POST|PATCH|DELETE)\"[^\n]{0,400}?(git/(refs|commits|trees|blobs)|/contents/))")
GIT_PUSH = re.compile(r"\bgit\b(?P<pre>[^|;&\n]*?)\bpush\b")


def _text(tinput):
    try:
        return json.dumps(tinput, sort_keys=True)
    except Exception:
        return str(tinput)


def _origin(path):
    try:
        r = subprocess.run(["git", "-C", path, "config", "--get", "remote.origin.url"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""


def is_release(tool, tinput, cwd=None):
    """True when this call would push to the core repository."""
    t = tinput if isinstance(tinput, dict) else {}
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Read", "Grep", "Glob") or str(tool).endswith(("write_file", "edit_block", "read_file")):
        return False  # writing or reading a file that mentions a push is not a push
    text = (tool or "") + " " + _text(t)
    if REPO in text and PUSH_VERB.search(text):
        return True
    cmd = t.get("command") or ""
    if not isinstance(cmd, str) or not GIT_PUSH.search(cmd):
        return False
    dirs = [cwd or os.getcwd()]
    dirs += re.findall(r"\bgit\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+)", cmd)
    dirs += re.findall(r"(?:^|[;&|]\s*)cd\s+(\"[^\"]+\"|'[^']+'|\S+)", cmd)
    for d in dirs:
        d = os.path.expanduser(d.strip("\"'"))
        if not os.path.isabs(d) and cwd:
            d = os.path.join(cwd, d)
        if REPO in _origin(d):
            return True
    return False


def read_lock():
    """Return (holder or None for no lock, error or None)."""
    f = os.environ.get("IMC_RELEASE_LOCK_FILE")
    if f:
        if not os.path.exists(f):
            return None, None
        body = open(f).read()
    else:
        body = None
        for url, hdr in ((API, {"Accept": "application/vnd.github.raw"}), (URL + "?t=%d" % time.time(), {"Cache-Control": "no-cache"})):
            try:
                req = urllib.request.Request(url, headers=dict(hdr, **{"User-Agent": "imc-reply-gate-releaselock"}))
                with urllib.request.urlopen(req, timeout=5) as r:
                    body = r.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None, None
                err = "HTTP %d from %s" % (e.code, url.split("?")[0])
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, str(e)[:120])
        if body is None:
            return None, err
    m = re.search(r"^holder=(\S+)", body, re.M)
    if not m:
        return None, "RELEASE-LOCK has no holder= line"
    return m.group(1), None


def check(tool, tinput, session, cwd=None):
    """(0, reason) to allow, (2, message) to refuse."""
    try:
        if not is_release(tool, tinput, cwd):
            return 0, "not a release"
    except Exception as e:
        return 0, "release detection error (allowed): %s" % e
    holder, err = read_lock()
    if err:
        return 2, ("imc-reply-gate RELEASE FREEZE: this call pushes to %s, and the release lock could not be read (%s), "
                   "so the push is refused (fail closed). Retry when the network answers." % (REPO, err))
    if holder is None:
        return 0, "release allowed: no RELEASE-LOCK in the repository"
    if session and session == holder:
        return 0, "release allowed: this session holds RELEASE-LOCK"
    return 2, ("imc-reply-gate RELEASE FREEZE (Rob 2026-11-26, O1 Evidence ledger and reviewer): gate-core releases are "
               "frozen. RELEASE-LOCK in %s names session %s as the only session allowed to push; this is session %s. "
               "Do not push. Note the change for that session's hand-off instead; Rob lifts the lock by deleting RELEASE-LOCK."
               % (REPO, holder, session or "UNKNOWN"))


def selftest():
    import tempfile
    res = []
    def t(name, got, want):
        res.append(got == want); print(("  ok    " if got == want else "  BAD   ") + name + ("" if got == want else "  got %r want %r" % (got, want)))
    d = tempfile.mkdtemp()
    clone = os.path.join(d, "core"); other = os.path.join(d, "other")
    for p, url in ((clone, "https://github.com/robkh1984/imc-reply-gate-core"), (other, "https://github.com/robkh1984/something-else")):
        os.makedirs(p); subprocess.run(["git", "init", "-q", p]); subprocess.run(["git", "-C", p, "remote", "add", "origin", url])
    lock = os.path.join(d, "RELEASE-LOCK")
    open(lock, "w").write("holder=HOLDER-SESSION\nset=2026-11-26 by Rob O1\n")
    os.environ["IMC_RELEASE_LOCK_FILE"] = lock
    push = {"command": "git push origin HEAD:main"}
    t("REFUSED: another session's git push in a core clone", check("Bash", push, "OTHER", cwd=clone)[0], 2)
    t("ALLOWED: the holder's git push in a core clone", check("Bash", push, "HOLDER-SESSION", cwd=clone)[0], 0)
    t("REFUSED: git -C <core clone> push from elsewhere", check("Bash", {"command": "git -C %s push" % clone}, "OTHER", cwd=d)[0], 2)
    t("REFUSED: cd <core clone> && git push", check("Bash", {"command": "cd %s && git push -u origin main" % clone}, "OTHER", cwd=d)[0], 2)
    t("REFUSED: gh api PUT on the core repo contents", check("Bash", {"command": "gh api -X PUT repos/robkh1984/imc-reply-gate-core/contents/MANIFEST.json -f message=x"}, "OTHER")[0], 2)
    t("REFUSED: Desktop Commander push on the Mac", check("mcp__remote-devices__Desktop_Commander__start_process", {"command": "cd ~/x/imc-reply-gate-core && git push", "timeout_ms": 1}, "OTHER", cwd=d)[0], 2)
    t("REFUSED: a GitHub MCP push_files to the core repo", check("mcp__github__push_files", {"repo": "imc-reply-gate-core", "owner": "robkh1984"}, "OTHER")[0], 2)
    t("REFUSED: Composio proxy PATCH of git/refs on the core repo (the serial 17 route)", check("mcp__Composio_for_u__COMPOSIO_PROXY_EXECUTE", {"endpoint": "/repos/robkh1984/imc-reply-gate-core/git/refs/heads/main", "method": "PATCH", "body": {"sha": "abc"}}, "OTHER")[0], 2)
    t("REFUSED: Composio GITHUB_UPDATE_A_REFERENCE on the core repo", check("mcp__Composio_for_u__COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GITHUB_UPDATE_A_REFERENCE", "arguments": {"repo": "imc-reply-gate-core", "ref": "heads/main"}}]}, "OTHER")[0], 2)
    t("REFUSED: Composio GITHUB_CREATE_A_COMMIT on the core repo", check("mcp__Composio_for_u__COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GITHUB_CREATE_A_COMMIT", "arguments": {"repo": "imc-reply-gate-core"}}]}, "OTHER")[0], 2)
    t("ALLOWED: Composio GITHUB_GET_A_REFERENCE read of the core repo", check("mcp__Composio_for_u__COMPOSIO_MULTI_EXECUTE_TOOL", {"tools": [{"tool_slug": "GITHUB_GET_A_REFERENCE", "arguments": {"repo": "imc-reply-gate-core", "ref": "heads/main"}}]}, "OTHER")[0], 0)
    t("ALLOWED: Composio proxy GET of the core repo contents", check("mcp__Composio_for_u__COMPOSIO_PROXY_EXECUTE", {"endpoint": "/repos/robkh1984/imc-reply-gate-core/contents/MANIFEST.json", "method": "GET"}, "OTHER")[0], 0)
    t("REFUSED: Composio proxy PUT of core repo contents", check("mcp__Composio_for_u__COMPOSIO_PROXY_EXECUTE", {"endpoint": "/repos/robkh1984/imc-reply-gate-core/contents/MANIFEST.json", "method": "PUT", "body": {"content": "x"}}, "OTHER")[0], 2)
    t("ALLOWED: a Write of notes naming GITHUB_UPDATE_A_REFERENCE and the core repo", check("Write", {"file_path": "/tmp/n.md", "content": "imc-reply-gate-core was released by GITHUB_UPDATE_A_REFERENCE and git push"}, "OTHER")[0], 0)
    t("REFUSED: another session's delete-only push of RELEASE-LOCK (no exception, as the docstring says)", check("Bash", {"command": "git rm RELEASE-LOCK && git commit -m 'lift lock' && git push origin HEAD:main"}, "OTHER", cwd=clone)[0], 2)
    t("ALLOWED: the holder's delete-only push of RELEASE-LOCK", check("Bash", {"command": "git rm RELEASE-LOCK && git commit -m 'lift lock' && git push origin HEAD:main"}, "HOLDER-SESSION", cwd=clone)[0], 0)
    t("ALLOWED: git push in an unrelated repo", check("Bash", push, "OTHER", cwd=other)[0], 0)
    t("ALLOWED: reading the core repo (git log)", check("Bash", {"command": "git log --oneline | head"}, "OTHER", cwd=clone)[0], 0)
    t("ALLOWED: git clone of the core repo", check("Bash", {"command": "git clone https://github.com/robkh1984/imc-reply-gate-core x"}, "OTHER")[0], 0)
    t("ALLOWED: a Write that only mentions the repo name", check("Write", {"file_path": "/tmp/n.md", "content": "imc-reply-gate-core notes"}, "OTHER")[0], 0)
    os.remove(lock)
    t("ALLOWED: another session's push once Rob deletes RELEASE-LOCK", check("Bash", push, "OTHER", cwd=clone)[0], 0)
    open(lock, "w").write("garbage\n")
    t("REFUSED (fail closed): a lock with no holder line", check("Bash", push, "OTHER", cwd=clone)[0], 2)
    open(lock, "w").write("holder=HOLDER-SESSION\n")
    t("the refusal names the holder session", "HOLDER-SESSION" in check("Bash", push, "OTHER", cwd=clone)[1], True)
    del os.environ["IMC_RELEASE_LOCK_FILE"]
    print("ALL CONTROLS PASSED" if all(res) else "A CONTROL FAILED")
    return all(res)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--selftest"]:
        sys.exit(0 if selftest() else 1)
    if a[:1] == ["status"]:
        print(read_lock()); sys.exit(0)
    print(__doc__); sys.exit(1)
