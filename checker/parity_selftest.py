"""0.4.11 selftest (OI-0805, OI-0807, OI-0802): precheck and the Stop hook agree on ONE-DECISION, the timezone check
and TABLE UNCHANGED; the panel allows one round per draft."""
import os, sys, tempfile, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
def load(n, p):
    sp = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
g = load("g", os.path.join(ROOT, "hooks", "gate.py"))
rp = load("rp", os.path.join(ROOT, "hooks", "reviewpanel.py"))
lc = load("lc", os.path.join(HERE, "lengthcheck.py"))
ok = tot = 0
def t(name, got, want):
    global ok, tot
    tot += 1; r = got == want; ok += r; print(("ok  " if r else "FAIL"), name, "got", repr(got)[:100])
HDR = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
two = HDR + "| 1 | OI-0800 (a) and OI-0804 (b): context long enough for the row to be read on its own here. BLOCKS: none | Decide: yes or no | Rob | RECOMMEND: choose yes, because x. | a | Con:&nbsp;a&nbsp;b&nbsp;c&nbsp;d&nbsp;e<br>• Risk: r.<br>• Mitigation: m. |\n"
t("shared list carries ONE-DECISION", any(c == "ONE-DECISION" for c, _ in g.table_row_fails(two)), True)
src = open(os.path.join(HERE, "precheck.py")).read()
t("precheck calls the shared list", "gate.table_row_fails(text)" in src, True)
t("precheck runs tzcheck as a FAIL", '("TZCHECK", _b)' in src, True)
t("TZ false positive gone", rp.tzcheck('stat -> newest "Oct 16 15:08:12 2026"; 3:01 PM PST.', 2026), [])
t("CONTROL: a real Oct PST still caught", len(rp.tzcheck("Oct 16, 2026 at 3:01 PM PST", 2026)), 1)
t("CONTROL: Nov PST is fine", rp.tzcheck("Nov 25, 2026 at 3:01 PM PST", 2026), [])
t("panel allows one round per draft", rp.MAX_ROUNDS, 1)
d = tempfile.mkdtemp(); stamps = os.path.join(d, "st.tsv")
a = os.path.join(d, "a.md"); open(a, "w").write("Reply.\n\n" + two)
b = os.path.join(d, "b.md"); un = "Short answer.\n\nTABLE UNCHANGED since the last reply.\n"; open(b, "w").write(un)
open(stamps, "w").write("x\t1\t%s\nFAIL\t2\t%s\tX\ny\t3\t%s\n" % (a, b, b))
t("Stop-side lookup skips the reply's own draft", bool(lc.tables(lc.previous_table_draft(un, None, stamps) or "")), True)
open(stamps, "w").write("y\t3\t%s\n" % b)
t("CONTROL: no earlier table, no pass", lc.previous_table_draft(un, None, stamps), None)
def _turn(msg, result="Message delivered to user."):
    return [{"type": "user", "message": {"content": "next steps?"}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "SendUserMessage", "input": {"message": msg}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": result}]}}]
t("OI-0811 delivered TABLE UNCHANGED counts as the turn's table", g.turn_sent_table(_turn("Short.\n\nTABLE UNCHANGED since the last reply.\n")), True)
t("OI-0811 CONTROL: blocked TABLE UNCHANGED does not count", g.turn_sent_table(_turn("Short.\n\nTABLE UNCHANGED since the last reply.\n", "imc-reply-gate blocked this SendUserMessage. NOTHING WAS SENT")), False)
t("OI-0811 CONTROL: a mention inside a sentence does not count", g.turn_sent_table(_turn("I wrote TABLE UNCHANGED since the last reply in prose.")), False)
print("%d of %d ok" % (ok, tot)); sys.exit(0 if ok == tot else 1)
