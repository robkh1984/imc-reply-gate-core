#!/usr/bin/env python3
"""scopecheck.py (imc-reply-gate 0.2.26, Rob ruled design E on 2026-10-19 13:24 PDT, register OI-0275): every file, link or
title-shaped quoted phrase named in Rob's LAST message must have a read or a lookup attempt in the transcript (a tool_use input
naming it) or a BLOCKED line in the draft whose quoted error matches a tool result in the transcript; a waiver counts only if a
user message contains 'waive' and the source's name.
  FAIL CLOSED: a title-shaped quoted phrase is required whether or not titles.tsv knows it. The registry only adds aliases
  (old title -> new title, the [DELETE] rename) and a DELETED status; it never lowers the bar.
  QUOTES: a straight pair or a curly pair; a straight and a curly mark never pair. Only title-shaped phrases count (two or more
  words, first character a capital, digit or '['); a leading '[DELETE] ' is stripped; a bare '[DELETE]' is the rename marker, not a title;
  phrases listed in non-titles.tsv are exempt.
  LAST MESSAGE: an image-only message is Rob's last message and names nothing (the gate cannot read an image), so it does not
  fall back to an older text message.
    python3 scopecheck.py <draft> [transcript]   exit 0 clean, 1 fail"""
import os, re, sys, json, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import transcript_util as tu

REGISTRY = os.path.join(HERE, "titles.tsv")       # title <TAB> status (LIVE|DELETED) <TAB> alias_of (optional) <TAB> seen_at
NONTITLES = os.path.join(HERE, "non-titles.tsv")  # one exempt phrase per line, '#' comments

URLFILE = re.compile(r"https?://[^\s)\]>\"']+|[\w./~-]+\.(?:md|py|tsv|json|txt|csv|sh|pdf|docx|xlsx|html)\b")
QUOTED = (re.compile(r'"([^"\n]{4,80})"'), re.compile(r"“([^”\n]{4,80})”"))
MARK = re.compile(r"^\[delete\]\s*", re.I)


def norm(s):
    s = s.strip().replace("’", "'").replace("‘", "'").lower()
    return re.sub(r"\s+", " ", MARK.sub("", s)).strip()


def title_shaped(p):
    p = p.strip()
    if not p or MARK.sub("", p).strip() == "":
        return False
    p = MARK.sub("", p).strip()
    if p == p.upper():          # an all-caps banner (AUDIT CLEAN, ALL CONTROLS PASSED) is a status line, not a title
        return False
    return len(p.split()) >= 2 and (p[0].isupper() or p[0].isdigit() or p[0] == "[") and p[-1] not in ".?!,;:"


def _lines(path):
    try:
        return [l.rstrip("\n") for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def registry():
    """norm(title) -> (status, norm(alias_of) or '')"""
    out = {}
    for l in _lines(REGISTRY):
        c = l.split("\t")
        if c[0].strip().lower() in ("title", ""):
            continue
        out[norm(c[0])] = ((c[1].strip().upper() if len(c) > 1 else "LIVE"), norm(c[2]) if len(c) > 2 and c[2].strip() else "")
    return out


def named(msg):
    """[(display, kind)] kind is 'src' for files and links, 'title' for quoted phrases."""
    out, seen = [], set()
    for m in URLFILE.finditer(msg):
        n = m.group(0).strip(".,;:)")
        if n and n not in seen:
            seen.add(n); out.append((n, "src"))
    skip = {norm(x) for x in _lines(NONTITLES)}
    for rx in QUOTED:
        for m in rx.finditer(msg):
            n = m.group(1).strip()
            if title_shaped(n) and norm(n) not in skip and n not in seen:
                seen.add(n); out.append((n, "title"))
    return out


def last_user_message(transcript):
    """Text of Rob's last genuine message; '' when that message is image-only."""
    last = None
    for e in tu.entries(transcript):
        if e.get("type") != "user":
            continue
        bl = tu._blocks(e)
        txt = [b.get("text", "").strip() for b in bl if isinstance(b, dict) and b.get("type") == "text"]
        txt = [t for t in txt if t and not t.startswith(tu.SYSTEM_PREFIXES)]
        if txt:
            last = "\n".join(txt)
        elif any(isinstance(b, dict) and b.get("type") == "image" for b in bl) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in bl):
            last = ""
    return last



def _last_user_is_scheduled(transcript):
    """True when the newest user entry carrying text was written by the scheduler (origin.subkind
    'scheduled-trigger'), not typed by Rob (origin.kind 'human'). 0.3.87, OI-0680 and OI-0687."""
    kind = None
    for e in tu.entries(transcript):
        if e.get("type") != "user":
            continue
        bl = tu._blocks(e)
        if any(isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()
               and not b.get("text", "").strip().startswith(tu.SYSTEM_PREFIXES) for b in bl):
            kind = (e.get("origin") or {}).get("subkind")
    return kind == "scheduled-trigger"

def scope_fails(draft_text, transcript):
    users = tu.user_texts(transcript)
    if not users: return []
    last = last_user_message(transcript)
    if last is None: last = users[-1]
    if _last_user_is_scheduled(transcript):  # 0.3.87: a scheduled task's stored prompt is not a live request to read what it quotes
        return []
    uses, results = tu.tool_inputs_and_results(transcript)
    blob = "\n".join(uses)
    nblob = norm(blob)
    res = "\n".join(results)
    reg = registry()
    dl = draft_text.lower()
    fails = []
    for n, kind in named(last):
        key = n.lower()
        if kind == "src":
            if key in blob.lower():
                continue
        else:
            k = norm(n)
            cands = {k}
            st, alias = reg.get(k, ("", ""))
            if alias: cands.add(alias)
            for t, (s2, a2) in reg.items():          # a quoted OLD title whose registry row points at the title searched
                if a2 == k: cands.add(t)
            if any(c in nblob for c in cands):
                continue
            if st == "DELETED" and any(k in l.lower().replace("’", "'") and "deleted" in l.lower() for l in draft_text.splitlines()):
                continue
        waived = any(("waive" in u.lower() and key in u.lower()) for u in users[:-1] + [last])
        if waived:
            continue
        blocked = False
        for ln in draft_text.splitlines():
            if "BLOCKED:" in ln and key in ln.lower():
                q = re.findall(r"[\"“]([^\"”]{12,200})[\"”]", ln)
                if any(x in res for x in q):
                    blocked = True
        if not blocked:
            fails.append(("SCOPE-UNREAD", "Rob's last message names %r (%s); the transcript shows no %s, no waiver, and no BLOCKED line quoting an error that a tool result contains" % (n, "file or link" if kind == "src" else "title", "read of it" if kind == "src" else "lookup attempt for it")))
    return fails


DECISION_VERBS = re.compile(r"^(approve|decide|rule|choose|grant|enable|click|sign|accept|answer|pick)\b", re.I)


def blocked_fails(draft_text, transcript):
    """0.3.18 CHANGE 3: BLOCKED-UNPROVEN. Every BLOCKED line (at a line start or after a sentence end) must quote an error
    (12-200 characters) that a tool result in the transcript contains, or name a table row owned by Rob whose Action starts
    with a decision verb."""
    uses, results = tu.tool_inputs_and_results(transcript)
    res = "\n".join(results)
    lines = draft_text.splitlines()
    rob_rows = {}
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if ln.lstrip().startswith("|") and len(cells) >= 7 and cells[0].isdigit() and cells[3].lower() == "rob":
            rob_rows[cells[0]] = cells[2]
    fails = []
    for ln in lines:
        mb = re.search(r"(?:^|[.;]\s+)BLOCKED:", ln.strip())
        if not mb:
            continue
        body = ln.strip()[mb.end():]
        quoted = re.findall(r"[\"\u201c]([^\"\u201d]{12,200})[\"\u201d]", body)
        if any(q in res for q in quoted):
            continue
        m = re.search(r"row\s+(\d+)", body, re.I)
        if m and m.group(1) in rob_rows and DECISION_VERBS.match(rob_rows[m.group(1)]):
            continue
        fails.append(("BLOCKED-UNPROVEN", "this BLOCKED line quotes no error that a tool result contains and names no Rob-owned row whose Action is a decision: %r" % body.strip()[:100]))
    return fails


def main(a):
    if "--selftest" in a: return selftest()
    if len(a) < 2: print("usage: scopecheck.py <draft> [transcript]"); return 2
    t = a[2] if len(a) > 2 else tu.find_transcript()
    if not t: print("SCOPE NOT RUN  no transcript found"); return 2
    f = scope_fails(open(a[1], encoding="utf-8").read(), t)
    for c, m in f: print("FAIL  [%s] %s" % (c, m))
    print("SCOPECHECK %s" % ("FAIL %d" % len(f) if f else "CLEAN")); return 1 if f else 0


def selftest():
    global REGISTRY, NONTITLES
    bad = 0
    real_reg, real_non = REGISTRY, NONTITLES
    def tr(d, msg, extra=(), origin=None):
        first = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": msg}]}}
        if origin is not None: first["origin"] = origin
        ev = [first] + list(extra)
        p = os.path.join(d, "t.jsonl"); open(p, "w").write("\n".join(json.dumps(e) for e in ev)); return p
    def use(s): return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": s}}]}}
    def search(q): return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "ListAgents", "input": {"q": q}}]}}
    def res(s): return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": s}]}}
    def user(s): return {"type": "user", "message": {"role": "user", "content": s}}
    img = {"type": "user", "message": {"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}]}}
    def case(name, want, msg, extra, draft="x", reg=None, origin=None):
        nonlocal bad
        global REGISTRY
        with tempfile.TemporaryDirectory() as d:
            if reg is not None:
                REGISTRY = os.path.join(d, "titles.tsv"); open(REGISTRY, "w").write("title\tstatus\talias_of\tseen_at\n" + reg)
            else:
                REGISTRY = os.path.join(d, "none.tsv")
            f = scope_fails(draft, tr(d, msg, extra, origin))
            ok = bool(f) == want; bad += (not ok)
            print("%s %s%s" % ("OK " if ok else "BAD", name, "  -> " + f[0][0] if f else ""))
        REGISTRY = real_reg
    NONTITLES = os.path.join(tempfile.gettempdir(), "scopecheck-selftest-no-non-titles.tsv")
    case("compaction-summary text naming a never-read file is not Rob's message", False, "real question", [user("<artifact-content-authored-by-others/>\nThe summarized conversation: see never-read-summary.md and plan-z.md")])
    case("stop-hook feedback text naming a never-read file is not Rob's message", False, "real question", [user("Stop hook feedback:\n[gate.py]: see never-read-hook.md")])
    case("planted request naming a never-read file fails", True, "please check never-read-plan.md now", [])
    case("file that was read passes", False, "please check plan-a.md now", [use("/x/plan-a.md")])
    case("BLOCKED line quoting a real tool error passes", False, "please check gone.md now", [res("Error: file not found: gone.md here")],
         draft='BLOCKED: gone.md "Error: file not found: gone.md here"')
    case("BLOCKED line quoting an invented error fails", True, "please check gone.md now", [res("fine")], draft='BLOCKED: gone.md "Error: invented message text"')
    case("waiver by a user message passes", False, "please check later.md now", [{"type": "user", "message": {"role": "user", "content": "waive later.md"}}])
    case("quoted emphasis is not a source", False, 'this is not a "thorough analysis" at all', [])
    case("all-caps status banner is not a title", False, 'it printed "ALL CONTROLS PASSED" again', [])
    case("quoted single word is not a source", False, 'I typed "Continue" twice', [])
    case("bare [DELETE] marker is not a title", False, 'rename it with "[DELETE]" in front', [])
    case("title-shaped quoted phrase never looked up fails (fail closed, registry empty)", True, 'read the session "Kaprelian doctors" please', [])
    case("title-shaped phrase passes when a tool call searched it", False, 'read the session "Kaprelian doctors" please', [search("Kaprelian doctors")])
    case("renamed title: Rob quotes [DELETE] form, I searched the plain title", False, 'read "[DELETE] Kaprelian doctors" please', [search("Kaprelian doctors")])
    case("renamed title: Rob quotes the old title, registry alias points at the new one I searched", False, 'read "Old Plan Session" please', [search("[DELETE] Old Plan Session")],
         reg="Old Plan Session\tLIVE\tNew Plan Session\t2026-10-19\n")
    case("alias in the other direction: Rob quotes the new title, I searched the old", False, 'read "New Plan Session" please', [search("Old Plan Session")],
         reg="Old Plan Session\tLIVE\tNew Plan Session\t2026-10-19\n")
    case("deleted session passes when the draft says deleted", False, 'read "Gone Session Title" please', [], draft="The session Gone Session Title is deleted.",
         reg="Gone Session Title\tDELETED\t\t2026-10-19\n")
    case("deleted session with no statement in the draft still fails", True, 'read "Gone Session Title" please', [], draft="ok",
         reg="Gone Session Title\tDELETED\t\t2026-10-19\n")
    case("mixed straight and curly marks make no phrase", False, 'vs "yes, but also keep the quoted phrases on the required list” and more', [])
    case("curly pair around a title-shaped phrase is checked", True, "read “Another Session Title” please", [])
    case("image-only last message does not fall back to an older unread file", False, "please check older-unread.md now", [img])
    case("text after an image is checked again", True, "ignore that", [img, user("now read newer-unread.md")])
    case("0.3.87 scheduled-trigger turn with the header names a never-read file: not Rob's request", False, "[SCHEDULED TASK - AUTOMATED FIRING OF A CONFIGURED PROMPT]\nread never-read-task.md", [], origin={"kind": "task-notification", "subkind": "scheduled-trigger"})
    case("0.3.87 scheduled-trigger turn without the header names a never-read file: not Rob's request", False, "STANDING RULES. Read never-read-task.md", [], origin={"kind": "task-notification", "subkind": "scheduled-trigger"})
    case("0.3.87 human turn naming a never-read file still fails", True, "please read never-read-human.md", [], origin={"kind": "human"})
    case("0.3.87 human turn after a scheduled turn is still checked", True, "ok", [{"type": "user", "origin": {"kind": "human"}, "message": {"role": "user", "content": [{"type": "text", "text": "now read never-read-after.md"}]}}], origin={"kind": "task-notification", "subkind": "scheduled-trigger"})
    NONTITLES = os.path.join(tempfile.mkdtemp(), "non-titles.tsv"); open(NONTITLES, "w").write("# x\nSECOND RUN\n")
    case("phrase on the non-titles list is exempt", False, 'the "SECOND RUN" label', [])
    NONTITLES = real_non
    print("SELFTEST %s" % ("CONTROLS OK" if not bad else "BAD %d" % bad)); return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
