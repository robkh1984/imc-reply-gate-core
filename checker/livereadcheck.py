#!/usr/bin/env python3
"""livereadcheck.py (imc-reply-gate 0.2.23, Rob 2026-10-18 20:01 PDT "build the check", INTAKE row 2 of that reply):
a next-steps row owned by Rob that names a memory file (/topics/x.md, /areas/x.md, /people/x.md, /projects/<id>/..., /preferences.md,
/profile.md) must be backed by a live read of that same file in THIS transcript: a memory_read tool_use whose path matches, whose
result is not an error, and, when the result prints "[updated: <time>]" and the entry carries a timestamp, a read made after that time;
and the draft must carry a CHECKED line naming the same path and memory_read. Origin: on 2026-10-18 Rob was asked to decide report
rows 108 and 109 from a 5:58 AM report while the account file had been updated at 3:42 PM; the rule 'prefer a tool call for live
state' existed, so the failure was retrieval, and only code that refuses can close it.
Limit, stated: it proves a read happened and is named, not that the read was understood.
    python3 livereadcheck.py <draft> [transcript]   exit 0 clean, 1 fail      python3 livereadcheck.py --selftest"""
import os, re, sys, json, tempfile
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import transcript_util as tu

PATH = re.compile(r"(?<![\w.])(/(?:topics|areas|people)/[\w.-]+\.md|/projects/[\w.-]+/(?:[\w.-]+/)*[\w.-]+\.md|/preferences\.md|/profile\.md|/index\.md)")
ROW = re.compile(r"^\|\s*\d+\s*\|")


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _reads(transcript):
    """[(path, entry_time, result_text)] for every memory_read tool_use, results matched by tool_use_id."""
    uses, res = [], {}
    for e in tu.entries(transcript):
        for b in tu._blocks(e):
            if b.get("type") == "tool_use" and str(b.get("name", "")).endswith("memory_read"):
                p = (b.get("input") or {}).get("path")
                for q in (p if isinstance(p, list) else [p]):
                    if isinstance(q, str):
                        uses.append((q, _ts(e.get("timestamp")), b.get("id")))
            elif b.get("type") == "tool_result":
                c = b.get("content")
                res[b.get("tool_use_id")] = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
    return [(p, t, res.get(i, "")) for p, t, i in uses]


def live_read_fails(draft_text, transcript):
    fails, reads = [], None
    for ln in draft_text.splitlines():
        if not ROW.match(ln):
            continue
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < 6 or cells[4] != "Rob":
            continue
        for path in sorted(set(PATH.findall(ln))):
            if reads is None:
                reads = _reads(transcript)
            good = []
            for p, t, r in reads:
                if not (p == path or p.endswith(path)):
                    continue
                if re.search(r"out of project scope|not found|error", r[:200], re.I) and "[updated:" not in r[:300]:
                    continue
                m = re.search(r"\[updated: ([^\]]+)\]", r[:300])
                u = _ts(m.group(1)) if m else None
                if u and t and t < u:
                    continue
                good.append((p, t))
            if not good:
                fails.append(("LIVE-READ-MISSING", "row owned by Rob names %s but the transcript shows no successful memory_read of it made after its [updated:] time. Read the file now, then cite the read in a CHECKED line." % path))
                continue
            cited = any(l.lstrip().startswith("CHECKED") and path in l and "memory_read" in l for l in draft_text.splitlines())
            if not cited:
                fails.append(("LIVE-READ-UNCITED", "row owned by Rob names %s and it was read, but no CHECKED line names both %s and memory_read." % (path, path)))
    return fails


def main(a):
    if "--selftest" in a:
        return selftest()
    if len(a) < 2:
        print("usage: livereadcheck.py <draft> [transcript]"); return 2
    t = a[2] if len(a) > 2 else tu.find_transcript()
    if not t:
        print("LIVEREAD NOT RUN  no transcript found"); return 2
    f = live_read_fails(open(a[1], encoding="utf-8").read(), t)
    for c, m in f:
        print("FAIL  [%s] %s" % (c, m))
    print("LIVEREADCHECK %s" % ("FAIL %d" % len(f) if f else "CLEAN")); return 1 if f else 0


def selftest():
    bad = 0
    ROB = "| 1 | issue | act | Rob | rec | pro | con |\n"
    CL = "| 2 | issue about /topics/home-network.md | act | Claude | rec | pro | con |\n"
    P = "/topics/home-network.md"

    def use(i, path):
        return {"type": "assistant", "timestamp": "2026-10-18T20:00:00+00:00", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": i, "name": "mcp__memory__memory_read", "input": {"path": path}}]}}

    def res(i, s):
        return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": s}]}}

    def case(name, want, draft, ev):
        nonlocal bad
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.jsonl")
            open(p, "w").write("\n".join(json.dumps(e) for e in ev))
            f = live_read_fails(draft, p)
            ok = bool(f) == want
            bad += (not ok)
            print("%s %s%s" % ("OK " if ok else "BAD", name, "  -> " + f[0][0] if f else ""))
    row = ROB.replace("issue", "stale line in " + P)
    chk = "CHECKED: memory_read of %s at 8:00 PM returned version x.\n" % P
    good = [use("a", P), res("a", "[updated: 2026-10-18T19:00:00+00:00] [size: 9]\nbody")]
    case("Rob row, no read at all, fails", True, row + chk, [])
    case("Rob row, read and cited, passes", False, row + chk, good)
    case("Rob row, read but not cited, fails", True, row, good)
    case("read made before the file was updated, fails", True, row + chk, [use("a", P), res("a", "[updated: 2026-10-18T21:00:00+00:00]\nbody")])
    case("read refused as out of project scope, fails", True, row + chk, [use("a", P), res("a", "out of project scope")])
    case("Claude-owned row naming a file is not gated", False, CL, [])
    case("Rob row naming no memory file is not gated", False, ROB, [])
    case("read of a different file, fails", True, row + chk, [use("a", "/topics/other.md"), res("a", "[updated: 2026-10-18T19:00:00+00:00]\nbody")])
    print("SELFTEST %s" % ("CONTROLS OK" if not bad else "BAD %d" % bad)); return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
