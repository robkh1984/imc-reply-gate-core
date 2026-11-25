#!/usr/bin/env python3
"""approvalledger.py - imc-reply-gate 0.3.49 PreToolUse hook (Rob 2026-11-12 1:52 PM PST, "Approve both your recommendations").

PURPOSE. Rob's standing rulings are checked at the ACTION, keyed on tool name and arguments, not on how a reply is worded.
The ledger is checker/approvals-ledger.tsv. Columns (tab separated, # lines ignored):
  tool | arg | pattern | qualifier | exceptions | mode | expires | ruling
  tool       exact tool name, e.g. mcp__claude-code-remote__delete_trigger
  arg        the tool_input key whose value is matched, e.g. trigger_id
  pattern    regex the value must fully match
  qualifier  name of a JSON file under the approvals dir that maps value -> facts, plus 'key=value' tests all of which must hold
             (e.g. qualified-triggers.json;ended_reason=run_once_fired;persist_session=true). Empty = no qualifier.
  exceptions regex; if it matches the qualifier facts text the row does not apply (never-fired, recurring, persist_session false)
  mode       warn (log the match, change nothing) or enforce (emit permissionDecision allow)
  expires    ISO date after which the row is ignored, or - for none
  ruling     Rob's words and time
Approvals dir: ~/.claude/imc-approvals (override IMC_APPROVALS_DIR). Log: log.tsv there. Any error allows nothing and logs nothing.

    python3 approvalledger.py             hook mode (JSON on stdin)
    python3 approvalledger.py --selftest  controls; exit 0 all pass
"""
import json, os, re, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(os.path.dirname(HERE), "checker", "approvals-ledger.tsv")


def adir():
    return os.environ.get("IMC_APPROVALS_DIR") or os.path.expanduser("~/.claude/imc-approvals")


def rows(path=None):
    out = []
    for ln in open(path or LEDGER, encoding="utf-8"):
        if not ln.strip() or ln.startswith("#"):
            continue
        c = ln.rstrip("\n").split("\t")
        if len(c) < 8:
            continue
        out.append(dict(zip(("tool", "arg", "pattern", "qualifier", "exceptions", "mode", "expires", "ruling"), c)))
    return out


def match(tool, ti, ledger=None, today=None):
    """Return (row, facts_text) for the first applicable ledger row, else None."""
    today = today or datetime.date.today().isoformat()
    for r in rows(ledger):
        if r["tool"] != tool:
            continue
        if r["expires"] not in ("-", "") and r["expires"] < today:
            continue
        val = str((ti or {}).get(r["arg"], ""))
        if not re.fullmatch(r["pattern"], val):
            continue
        facts = ""
        if r["qualifier"]:
            parts = r["qualifier"].split(";")
            try:
                data = json.load(open(os.path.join(adir(), parts[0])))
            except Exception:
                continue
            rec = data.get(val)
            if not isinstance(rec, dict):
                continue
            if any(str(rec.get(k.split("=", 1)[0])).lower() != k.split("=", 1)[1].lower() for k in parts[1:]):
                continue
            facts = json.dumps(rec, sort_keys=True)
        if r["exceptions"] and re.search(r["exceptions"], facts + " " + val, re.I):
            continue
        return r, facts
    return None


def log(tool, ti, r, facts, decision):
    try:
        os.makedirs(adir(), exist_ok=True)
        with open(os.path.join(adir(), "log.tsv"), "a") as f:
            f.write("\t".join([datetime.datetime.now().isoformat(timespec="seconds"), tool, json.dumps(ti, sort_keys=True), r["mode"], decision, r["ruling"][:120]]) + "\n")
    except Exception:
        pass


def decide(tool, ti, ledger=None):
    """Return the hook JSON dict to print, or None."""
    m = match(tool, ti, ledger)
    if not m:
        return None
    r, facts = m
    if r["mode"] != "enforce":
        log(tool, ti, r, facts, "warn-would-allow")
        return None
    log(tool, ti, r, facts, "allow")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": "standing ruling: " + r["ruling"]}}


def main():
    try:
        d = json.load(sys.stdin)
        out = decide(d.get("tool_name", ""), d.get("tool_input") or {})
        if out:
            print(json.dumps(out))
    except Exception:
        pass
    sys.exit(0)


def selftest():
    import tempfile
    t = tempfile.mkdtemp()
    os.environ["IMC_APPROVALS_DIR"] = t
    led = os.path.join(t, "led.tsv")
    tool = "mcp__claude-code-remote__delete_trigger"
    def write(mode):
        open(led, "w").write("\t".join([tool, "trigger_id", r"trig_[A-Za-z0-9]+", "q.json;ended_reason=run_once_fired;persist_session=true",
                                        "recurring", mode, "-", "Rob 2026-11-12 11:37 AM PST"]) + "\n")
    json.dump({"trig_ok": {"ended_reason": "run_once_fired", "persist_session": True},
               "trig_nopersist": {"ended_reason": "run_once_fired", "persist_session": False},
               "trig_never": {"ended_reason": None, "persist_session": True}}, open(os.path.join(t, "q.json"), "w"))
    bad = 0
    def chk(name, got, want):
        nonlocal bad
        if bool(got) != want:
            bad += 1
            print("FAIL", name)
    write("enforce")
    chk("enforce qualified allows", decide(tool, {"trigger_id": "trig_ok"}, led), True)
    chk("persist false refused", decide(tool, {"trigger_id": "trig_nopersist"}, led), False)
    chk("never fired refused", decide(tool, {"trigger_id": "trig_never"}, led), False)
    chk("unlisted id refused", decide(tool, {"trigger_id": "trig_zzz"}, led), False)
    chk("other tool refused", decide("Bash", {"trigger_id": "trig_ok"}, led), False)
    write("warn")
    chk("warn mode never allows", decide(tool, {"trigger_id": "trig_ok"}, led), False)
    chk("warn mode logs", os.path.exists(os.path.join(t, "log.tsv")), True)
    open(led, "w").write("\t".join([tool, "trigger_id", r"trig_.*", "", "", "enforce", "2020-01-01", "x"]) + "\n")
    chk("expired row ignored", decide(tool, {"trigger_id": "trig_ok"}, led), False)
    print("approvalledger_selftest", "FAIL" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
