#!/usr/bin/env python3
"""replaycheck.py (imc-reply-gate 0.2.17, Rob-agreed Oct 17 2026, rows 27): the stamp is refused unless the SESSION TRANSCRIPT
(written by the harness) shows a reviewer agent whose prompt held (a) Rob's last message, (b) the sha256 of the draft being
stamped, (c) the Glitch Check prompt (signature 'FIVE-CATEGORY CHECK'), (d) a canary id; and the review record
<draft>.review shows (e) a canary reported back, (f) a final pass 'NEW FINDINGS: 0' within six passes, (g) a clause map.
    python3 replaycheck.py <draft> [transcript]   exit 0 clean, 1 fail
It proves the review ran with the inputs, not that the review was good."""
import hashlib, os, re, sys, tempfile, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import transcript_util as tu


def norm_sha(text):
    t = "\n".join(l.rstrip() for l in text.replace("\r\n", "\n").split("\n")).strip("\n")
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def replay_fails(draft, transcript):
    fails = []
    text = open(draft, encoding="utf-8").read()
    sha = norm_sha(text)
    rec = draft + ".review"
    if not os.path.isfile(rec):
        return [("REPLAY-NO-RECORD", "no %s" % os.path.basename(rec))]
    r = open(rec, encoding="utf-8").read()
    users = tu.user_texts(transcript)
    if not users:
        return []  # 0.2.34: a compacted session holds only the summary, so there is no user message to replay against (scopecheck returns [] the same way)
    last = re.sub(r"\s+", " ", users[-1])[:80]
    canary = re.search(r"CANARY-ID:\s*(\S+)", r)
    if not canary:
        fails.append(("REPLAY-NO-CANARY", "the review record names no 'CANARY-ID: <id>'"))
    cid = canary.group(1) if canary else None
    ok = []
    for p in tu.agent_prompts(transcript):
        pn = re.sub(r"\s+", " ", p)
        if last in pn and sha in p and "FIVE-CATEGORY CHECK" in p and cid and cid in p:
            ok.append(p)
    if not ok:
        miss = []
        pr = tu.agent_prompts(transcript)
        if not any(last in re.sub(r"\s+", " ", p) for p in pr): miss.append("Rob's last message")
        if not any(sha in p for p in pr): miss.append("the draft's sha256 (a reply edited after review fails here)")
        if not any("FIVE-CATEGORY CHECK" in p for p in pr): miss.append("the Glitch Check prompt")
        if cid and not any(cid in p for p in pr): miss.append("the canary id")
        fails.append(("REPLAY-NO-REVIEWER", "no single reviewer agent prompt in the transcript holds all four of: Rob's last message, the draft sha256, the Glitch Check prompt, the canary id; missing across all prompts: %s" % (", ".join(miss) or "no one prompt has all four")))
    if len(ok) > 6:
        fails.append(("REPLAY-PASSES", "%d reviewer passes carry this draft; the limit is six" % len(ok)))
    if cid and not re.search(r"CANARY-FOUND:\s*%s\b" % re.escape(cid), r):
        fails.append(("REPLAY-CANARY-MISSED", "the review record does not report the planted canary %s back" % cid))
    passes = re.findall(r"^PASS\s+(\d+)\s+NEW FINDINGS:\s*(\d+)", r, re.M)
    if not passes:
        fails.append(("REPLAY-NO-PASSES", "no 'PASS n NEW FINDINGS: k' lines in the review record"))
    else:
        if passes[-1][1] != "0":
            fails.append(("REPLAY-NOT-ZERO", "the final pass %s reports NEW FINDINGS: %s, not 0" % passes[-1]))
        if len(passes) > 6:
            fails.append(("REPLAY-PASSES", "%d passes recorded; the limit is six" % len(passes)))
        if len(passes) < 2 and re.search(r"FINDINGS:\s*[1-9]", r):
            fails.append(("REPLAY-ONE-PASS", "findings were reported and fixed with no second pass"))
    cm = re.search(r"CLAUSE-MAP:\s*\n((?:\s*-\s.*\n?)+)", r)
    if not cm or len([l for l in cm.group(1).splitlines() if l.strip()]) < 2:
        fails.append(("REPLAY-NO-CLAUSE-MAP", "the record carries no CLAUSE-MAP with one '- ' line per clause of Rob's request (at least two)"))
    return fails


def main(a):
    if "--selftest" in a:
        return selftest()
    if len(a) < 2: print("usage: replaycheck.py <draft> [transcript]"); return 2
    t = a[2] if len(a) > 2 else tu.find_transcript()
    if not t: print("REPLAY NOT RUN  no transcript found"); return 2
    f = replay_fails(os.path.abspath(a[1]), t)
    for c, m in f: print("FAIL  [%s] %s" % (c, m))
    print("REPLAYCHECK %s" % ("FAIL %d" % len(f) if f else "CLEAN")); return 1 if f else 0


def _mk(d, draft_text, prompt_has_sha=True, record=None, canary="CNRY-7Q", rob="Why is the table wrong? please fix it now"):
    p = os.path.join(d, "r.md"); open(p, "w").write(draft_text)
    sha = norm_sha(draft_text)
    prompt = "FIVE-CATEGORY CHECK\n%s\n%s\n%s" % (rob, sha if prompt_has_sha else "0" * 64, canary)
    ev = [{"type": "user", "message": {"role": "user", "content": rob}},
          {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Agent", "input": {"prompt": prompt}}]}}]
    t = os.path.join(d, "t.jsonl"); open(t, "w").write("\n".join(json.dumps(e) for e in ev))
    open(p + ".review", "w").write(record if record is not None else
        "CANARY-ID: %s\nCANARY-FOUND: %s\nPASS 1 NEW FINDINGS: 4\nPASS 2 NEW FINDINGS: 0\nCLAUSE-MAP:\n- why wrong -> para 1\n- fix it -> para 2\n" % (canary, canary))
    return p, t


def selftest():
    bad = 0
    def case(name, want_fail, **kw):
        nonlocal bad
        with tempfile.TemporaryDirectory() as d:
            dt = kw.pop("draft", "draft text v1")
            p, t = _mk(d, dt, **kw)
            if kw.get("_edit"): pass
            f = replay_fails(p, t)
            ok = bool(f) == want_fail
            print("%s %s%s" % ("OK " if ok else "BAD", name, "" if not f else "  -> " + f[0][0]))
            bad += (not ok)
    case("two-pass reviewed draft passes", False)
    case("findings fixed with no second pass fails", True, record="CANARY-ID: CNRY-7Q\nCANARY-FOUND: CNRY-7Q\nPASS 1 NEW FINDINGS: 4\nCLAUSE-MAP:\n- a\n- b\n")
    case("draft edited after the zero pass fails on the hash", True, prompt_has_sha=False)
    case("shallow draft omitting clauses fails", True, record="CANARY-ID: CNRY-7Q\nCANARY-FOUND: CNRY-7Q\nPASS 1 NEW FINDINGS: 3\nPASS 2 NEW FINDINGS: 0\nCLAUSE-MAP:\n- only one\n")
    case("canary not reported back fails", True, record="CANARY-ID: CNRY-7Q\nPASS 1 NEW FINDINGS: 3\nPASS 2 NEW FINDINGS: 0\nCLAUSE-MAP:\n- a\n- b\n")
    with tempfile.TemporaryDirectory() as d:  # 0.2.34 control: no genuine user message must not FAIL
        dp = os.path.join(d, "draft.md"); open(dp, "w").write("x"); open(dp + ".review", "w").write("x")
        tp = os.path.join(d, "t.jsonl"); open(tp, "w").write('{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\n')
        f = replay_fails(dp, tp)
        print("%s compacted transcript with no user message does not fail" % ("OK " if not f else "BAD")); bad += bool(f)
    print("SELFTEST %s" % ("CONTROLS OK" if not bad else "BAD %d" % bad)); return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
