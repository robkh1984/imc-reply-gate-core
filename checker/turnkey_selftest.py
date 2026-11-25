#!/usr/bin/env python3
"""0.2.39 selftest: turn_key must ignore Stop-hook feedback entries (so the block cap of 2 can fire), and
turn_sent_table must see a SendUserMessage table in the current turn only. Exit 0 = all controls behave."""
import importlib.util, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("gate", os.path.join(HERE, "..", "hooks", "gate.py"))
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
U = lambda u, c, **k: dict({"type": "user", "uuid": u, "message": {"role": "user", "content": c}}, **k)
A = lambda u, blocks: {"type": "assistant", "uuid": u, "message": {"role": "assistant", "content": blocks}}
TBL = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n| 1 | x | y | Claude | z | p | c |"
SUM = lambda m: A("a", [{"type": "tool_use", "id": "t", "name": "mcp__x__SendUserMessage", "input": {"message": m}}])
RES = lambda err, txt="sent": {"type": "user", "uuid": "r", "toolUseResult": {}, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": txt, "is_error": err}]}}
bad = 0
def chk(name, ok):
    global bad; bad += (not ok); print(("OK  " if ok else "BAD ") + name)
fb = U("fb1", "Stop hook feedback:\nEVERY-REPLY-TABLE", isMeta=True)
fb2 = U("fb2", "Stop hook feedback: again", isMeta=True)
chk("MUTATION turn_key ignores isMeta hook feedback (same key before and after two blocks)",
    g.turn_key([U("u1", "hello"), SUM(TBL), fb, fb2]) == "u1")
chk("CONTROL turn_key moves on a real new user prompt", g.turn_key([U("u1", "hello"), fb, U("u2", "next")]) == "u2")
chk("CONTROL text-only hook feedback (no isMeta) is ignored too", g.turn_key([U("u1", "hi"), U("fb3", "Stop hook feedback: x")]) == "u1")
chk("MUTATION turn_sent_table true after SendUserMessage with the table header", g.turn_sent_table([U("u1", "hi"), SUM(TBL), fb]) is True)
chk("CONTROL turn_sent_table false with no SendUserMessage table", g.turn_sent_table([U("u1", "hi"), SUM("plain note"), fb]) is False)
chk("CONTROL turn_sent_table false when the table was sent in an earlier turn", g.turn_sent_table([U("u1", "hi"), SUM(TBL), U("u2", "new ask")]) is False)
chk("MUTATION a blocked SendUserMessage table (is_error) waives nothing", g.turn_sent_table([U("u1", "hi"), SUM(TBL), RES(True, "NOTHING WAS SENT"), fb]) is False)
chk("CONTROL a delivered SendUserMessage table still counts", g.turn_sent_table([U("u1", "hi"), SUM(TBL), RES(False), fb]) is True)
chk("MUTATION a message that only quotes the header in prose waives nothing", g.turn_sent_table([U("u1", "hi"), SUM("the header `| # | Issue / Risk | Action | Owner |` is checked")]) is False)
chk("MUTATION list-form hook feedback is ignored by turn_key", g.turn_key([U("u1", "hi"), U("fb4", [{"type": "text", "text": "Stop hook feedback: x"}])]) == "u1")
print("TURNKEY SELFTEST OK" if not bad else "TURNKEY SELFTEST BAD %d" % bad); sys.exit(1 if bad else 0)
