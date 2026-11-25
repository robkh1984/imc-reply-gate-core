#!/usr/bin/env python3
"""editlogguard.py - PreToolUse hook modelled on intakeguard.py (added 0.3.34, 2026-11-02, Rob R441).
ROOT CAUSE it answers: on 2026-11-02 a hand append to EDIT-LOG.tsv (local time, no log-edit.sh) was
caught only after the fact by bin/editlogshape.py. This hook refuses a shell or file-write call that writes
EDIT-LOG.tsv directly. It has no allow-list line for log-edit.sh: that script writes the log from inside itself, so a
call that merely runs it contains no direct write, and a call that mentions it AND appends by hand is still denied.
    python3 editlogguard.py            hook mode (JSON on stdin; exit 2 = deny)
    python3 editlogguard.py --selftest controls; exit 0 all pass, 1 a control failed
"""
import json, re, sys

LOGNAME = r'EDIT-LOG\.tsv'
WRITE_RES = [
    re.compile(r'(?:>>?|\btee(?:\s+-a)?)\s*["\']?[^\s;|&"\']*' + LOGNAME),
    re.compile(r'\bsed\s+-i[^\n;|&]*' + LOGNAME),
    re.compile(r'open\([^)]*' + LOGNAME + r'[^)]*["\'](?:a|w|r\+|a\+|w\+)'),
    re.compile(r'EDIT-LOG[^\n]{0,80}\.(?:write_text|write)\('),
    re.compile(r'\b(?:cp|mv)\s+[^\n;|&]+\s+["\']?[^\s;|&"\']*' + LOGNAME + r'["\'}\s]*(?:$|[;|&])', re.M),
]
FILE_TOOLS = ("write_file", "edit_block", "Write", "Edit")


def verdict(tool, tool_input):
    ti = tool_input or {}
    blob = json.dumps(ti, ensure_ascii=False)
    blob = blob.encode("utf-8").decode("unicode_escape", errors="ignore") if "\\" in blob else blob
    if "EDIT-LOG.tsv" not in blob:
        return None
    path = str(ti.get("path") or ti.get("file_path") or "")
    if tool and any(tool.endswith(t) for t in FILE_TOOLS) and path.endswith("EDIT-LOG.tsv"):
        return "%s would write EDIT-LOG.tsv directly" % tool
    for rx in WRITE_RES:
        m = rx.search(blob)
        if m:
            return "the command writes EDIT-LOG.tsv directly (%s)" % m.group(0)[:80]
    return None


def selftest():
    P = "/Users/robk/Claude/instructions-backup/"
    cases = [
        ("Bash", {"command": "printf '2026-11-02T16:50\\tretired-surfaces\\t1\\n' >> " + P + "EDIT-LOG.tsv"}, True),
        ("Bash", {"command": "cd " + P + " && echo row >> EDIT-LOG.tsv"}, True),
        ("mcp__remote-devices__Desktop_Commander__start_process", {"command": "echo x | tee -a ~/Claude/instructions-backup/EDIT-LOG.tsv", "timeout_ms": 1000}, True),
        ("Bash", {"command": "sed -i '' 's/a/b/' EDIT-LOG.tsv"}, True),
        ("mcp__remote-devices__Desktop_Commander__write_file", {"path": P + "EDIT-LOG.tsv", "content": "x"}, True),
        ("Bash", {"command": "python3 -c \"open('EDIT-LOG.tsv','a').write('x')\""}, True),
        ("Bash", {"command": "cp /tmp/x.tsv " + P + "EDIT-LOG.tsv"}, True),
        ("Bash", {"command": "zsh ./log-edit.sh retired-surfaces 1 aaaaaaaaaaaa 2 bbbbbbbbbbbb note && printf x >> EDIT-LOG.tsv"}, True),
        ("Bash", {"command": "zsh ./log-edit.sh retired-surfaces 60443 affc1ca5a8f569dd 61021 a6b6ffd5f36585d1 note"}, False),
        ("Bash", {"command": "awk -F'\\t' '$2==\"openitems.py\"' EDIT-LOG.tsv | tail -2"}, False),
        ("Bash", {"command": "grep -n 'artifactcount.py' EDIT-LOG.tsv > /tmp/hits.txt"}, False),
        ("Bash", {"command": "python3 -c \"print(open('EDIT-LOG.tsv',encoding='utf-8').read()[:10])\""}, False),
        ("Bash", {"command": "cp " + P + "EDIT-LOG.tsv /tmp/EDIT-LOG-copy.tsv"}, False),
        ("Bash", {"command": "printf x >> " + P + ".edit-log-receipt-acks.tsv"}, False),
        ("Bash", {"command": "ls -l"}, False),
    ]
    ok = True
    for tool, inp, deny in cases:
        got = verdict(tool, inp) is not None
        good = got == deny
        ok = ok and good
        print(("  ok    " if good else "  FAIL  ") + ("DENY " if deny else "ALLOW ") + tool.split("__")[-1] + " " + json.dumps(inp)[:70])
    print("ALL CONTROLS PASSED" if ok else "A CONTROL FAILED")
    return ok


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    why = verdict(payload.get("tool_name", ""), payload.get("tool_input") or {})
    if why:
        sys.stderr.write("editlogguard refused this call: %s. Append to EDIT-LOG.tsv only through "
                         "zsh ~/Claude/instructions-backup/log-edit.sh (column 1 is UTC). Nothing was run.\n" % why)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
