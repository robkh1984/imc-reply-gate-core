#!/usr/bin/env python3
"""intakeguard.py - imc-reply-gate 0.2.13 PreToolUse hook (Rob 2026-10-16 12:32 PDT, next-steps row 7:
"Investigate the root cause and fix it so it doesn't happen again").

ROOT CAUSE (INTAKE F-565, 2026-10-14): nine INTAKE.md entries failed the stamp check because later lines were
appended to the end of INTAKE.md with printf or a heredoc and no '## ' heading, so the parser folded them into
the previous entry. bin/intakestamp.py append is the only writer that stamps an entry; a rule saying so did not
stop the headless appends. This hook refuses them before they run: a shell or file-write tool call that writes
to INTAKE.md without going through intakestamp.py is denied (exit 2, reason on stderr). Reads are allowed.

    python3 intakeguard.py            hook mode (JSON on stdin)
    python3 intakeguard.py --selftest controls; exit 0 all pass, 1 a control failed
"""
import json
import re
import sys

WRITE_RES = [
    re.compile(r'(?:>>?|\btee(?:\s+-a)?)\s*["\']?[^\s;|&"\']*INTAKE\.md'),          # redirect / tee into it
    re.compile(r'open\([^)]*INTAKE\.md[^)]*["\'](?:a|w|r\+|a\+|w\+)'),               # python open for write
    re.compile(r'INTAKE[^\n]{0,80}\.(?:write_text|write)\('),                        # pathlib write
    re.compile(r'\b(?:cp|mv)\s+[^\n;|&]+\s+["\']?[^\s;|&"\']*INTAKE\.md["\']?\s*(?:$|[;|&])', re.M),  # cp/mv onto it
]
FILE_TOOLS = ("write_file", "edit_block", "Write", "Edit")
SED_SEG = re.compile(r'\bsed\s+[^\n;|&]*')


def sed_writes_intake(blob):
    """core serial 5 (OI-0736): refuse an in-place sed only when the intake log is one of the FILES sed edits,
    not when its name appears in sed's script. An unparseable segment is refused, as before."""
    import shlex
    for m in SED_SEG.finditer(blob):
        seg = m.group(0)
        if "INTAKE.md" not in seg:
            continue
        try:
            toks = shlex.split(seg)
        except ValueError:
            return seg
        if not any(t.startswith("-i") or t.startswith("--in-place") for t in toks[1:]):
            continue  # not in place: sed only prints
        files, script_seen, i = [], False, 1
        while i < len(toks):
            t = toks[i]
            if t in ("-e", "-f", "--expression", "--file"):
                script_seen = True
                i += 2
                continue
            if t.startswith(("--expression=", "--file=")):
                script_seen = True
            elif t == "-i" and i + 1 < len(toks) and toks[i + 1] == "":
                i += 2  # macOS: sed -i '' (empty backup suffix)
                continue
            elif t.startswith("-") and t != "-":
                pass
            elif not script_seen:
                script_seen = True  # the first operand is the script
            else:
                files.append(t)
            i += 1
        if any(f.endswith("INTAKE.md") for f in files):
            return seg
    return None


def verdict(tool, tool_input):
    """None to allow, or the denial reason."""
    blob = json.dumps(tool_input or {}, ensure_ascii=False)
    blob = blob.encode("utf-8").decode("unicode_escape", errors="ignore") if "\\" in blob else blob
    if "INTAKE.md" not in blob:
        return None
    if "intakestamp.py" in blob:
        return None
    path = str((tool_input or {}).get("path") or (tool_input or {}).get("file_path") or "")
    if tool and any(tool.endswith(t) for t in FILE_TOOLS):
        # core serial 5 (OI-0736): a file tool writes only its path; its content may quote the name freely.
        return ("%s would write INTAKE.md directly" % tool) if path.endswith("INTAKE.md") else None
    raw = "\n".join(v for v in (tool_input or {}).values() if isinstance(v, str))  # raw text, not JSON: JSON quotes break shlex
    seg = sed_writes_intake(raw)
    if seg:
        return "the command writes INTAKE.md directly (%s)" % seg[:80]
    for rx in WRITE_RES:
        m = rx.search(blob)
        if m:
            return "the command writes INTAKE.md directly (%s)" % m.group(0)[:80]
    return None


def selftest():
    cases = [
        ("Bash", {"command": "printf 'x' >> ~/Claude/Improving-my-Claude/INTAKE.md"}, True),
        ("Bash", {"command": "cat <<'E' >> INTAKE.md\nhello\nE"}, True),
        ("mcp__remote-devices__Control_your_Mac__osascript", {"script": "do shell script \"echo x >> ~/Claude/Improving-my-Claude/INTAKE.md\""}, True),
        ("Bash", {"command": "sed -i '' 's/a/b/' INTAKE.md"}, True),
        ("mcp__remote-devices__Desktop_Commander__write_file", {"path": "/Users/robk/Claude/Improving-my-Claude/INTAKE.md", "content": "x"}, True),
        ("Bash", {"command": "python3 -c \"open('INTAKE.md','a').write('x')\""}, True),
        ("Bash", {"command": "grep -n F-565 INTAKE.md | head"}, False),
        ("Bash", {"command": "tail -c 600 INTAKE.md > /tmp/x.txt"}, False),
        ("Bash", {"command": "python3 bin/intakestamp.py append --title T --body-file /tmp/b.txt"}, False),
        ("Bash", {"command": "cp INTAKE.md /tmp/INTAKE-copy.txt"}, False),
        ("Bash", {"command": "ls -l"}, False),
        # core serial 5 (OI-0736): the name inside sed's script or a file tool's content is allowed
        ("Bash", {"command": "sed -i '' 's/old/see INTAKE.md entry/' other.md"}, False),
        ("Bash", {"command": "sed -i.bak -e 's/a/b/' ~/Claude/Improving-my-Claude/INTAKE.md"}, True),
        ("Bash", {"command": "sed -i -e s/a/b/ other.md INTAKE.md"}, True),
        ("Bash", {"command": "sed -i 's/a/b/' \"/Users/robk/Claude/Improving-my-Claude/INTAKE.md\""}, True),
        ("Bash", {"command": "sed -n '1,5p' INTAKE.md"}, False),
        ("Bash", {"command": "cd x && sed -i '' 's/a/b/' INTAKE.md && ls"}, True),
        ("Bash", {"command": "sed --in-place=.bak 's/a/b/' INTAKE.md"}, True),
        ("mcp__remote-devices__Desktop_Commander__write_file", {"path": "/tmp/rgtest/addrows.py", "content": "refused: sed -i 's/a/b/' INTAKE.md"}, False),
        ("Edit", {"file_path": "/Users/robk/Claude/Improving-my-Claude/INTAKE.md", "old_string": "a", "new_string": "b"}, True),
    ]
    ok = True
    for tool, inp, deny in cases:
        got = verdict(tool, inp) is not None
        good = got == deny
        ok = ok and good
        print(("  ok    " if good else "  FAIL  ") + ("DENY " if deny else "ALLOW ") + tool + " " + json.dumps(inp)[:70])
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
        sys.stderr.write("imc-reply-gate intakeguard refused this call: %s. Write INTAKE entries only with "
                         "python3 ~/Claude/Improving-my-Claude/bin/intakestamp.py append --title \"TITLE\" "
                         "--body-file PATH (INTAKE F-565: headless appends broke nine entries). Nothing was run.\n" % why)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
