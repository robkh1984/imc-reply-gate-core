#!/usr/bin/env python3
"""Self-test for lengthcheck.py: a clean draft passes and each mutant fails with the named code. Exit 1 on any miss."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lengthcheck as L

HDR = "| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |\n|---|---|---|---|---|---|---|\n"
def tbl(x): return HDR + "| 1 | issue %s | act | Rob | rec | pro | con |\n" % x
def words(n): return " ".join(["word"] * n)
def codes(f): return sorted({c for c, _ in f})
miss = []
def expect(name, got, want):
    if got != want: miss.append("%s: got %s want %s" % (name, got, want))
os.environ.pop("IMC_ALLOW_RESEND", None)
base = words(150) + "\n\n" + tbl("a")
expect("clean-150-words", codes(L.length_fails(base, "d.md", prev="")), [])
expect("151-words", codes(L.length_fails(words(151) + "\n\n" + tbl("a"), "d.md", prev="")), ["ABOVE-TABLE-CAP"])
expect("table-twice", codes(L.length_fails("hi\n\n" + tbl("a") + "\ntext\n\n" + tbl("a"), "d.md", prev="")), ["REPEAT-TEXT"])
expect("two-different-tables-ok", codes(L.length_fails("hi\n\n" + tbl("a") + "\ntext\n\n" + tbl("b"), "d.md", prev="")), [])
expect("same-as-last-table", codes(L.length_fails("hi\n\n" + tbl("a"), "d.md", prev="x\n\n" + tbl("a"))), ["REPEAT-TEXT"])
expect("changed-table-ok", codes(L.length_fails("hi\n\n" + tbl("b"), "d.md", prev="x\n\n" + tbl("a"))), [])
expect("correction-dup", codes(L.length_fails("CORRECTION: row 1 was wrong.\n\n" + tbl("b"), "d.md", prev="CORRECTION: row 1 was wrong.\n\n" + tbl("a"))), ["REPEAT-TEXT"])
expect("checked-dup", codes(L.length_fails("CHECKED: a -> b\n\n" + tbl("b"), "d.md", prev="CHECKED: a -> b\n\n" + tbl("a"))), ["REPEAT-TEXT"])
expect("checked-new-ok", codes(L.length_fails("CHECKED: a -> c\n\n" + tbl("b"), "d.md", prev="CHECKED: a -> b\n\n" + tbl("a"))), [])
expect("structured-lines-not-counted", codes(L.length_fails("CHECKED: " + words(300) + "\nSELF-CHECK: " + words(100) + "\n\n" + tbl("a"), "d.md", prev="")), [])
expect("quoted-text-not-counted", codes(L.length_fails('You said "' + words(300) + '".\n\n' + tbl("a"), "d.md", prev="")), [])
expect("unchanged-line-ok", L.unchanged_line_ok("TABLE UNCHANGED since the last reply", "d.md", prev="x\n\n" + tbl("a")), True)
expect("unchanged-line-no-prev-table", L.unchanged_line_ok("TABLE UNCHANGED since the last reply", "d.md", prev="x"), False)
expect("unchanged-line-with-table", L.unchanged_line_ok("TABLE UNCHANGED since the last reply\n\n" + tbl("a"), "d.md", prev="x\n\n" + tbl("a")), False)
expect("no-line", L.unchanged_line_ok("hello", "d.md", prev="x\n\n" + tbl("a")), False)
# ---------- OI-0495 (2026-11-19): A FENCED QUOTATION IS NOT CLAUDE'S PROSE ----------
# Measured: the old walk toggled on any line starting with ```, so quoting Rob's own instruction
# field - which contains fenced examples and an example next-steps table - counted runs of HIS
# words toward Claude's 150-word cap, and the example header inside the fence stopped the count.
# Each control is a pair: the quotation must pass, and the real prose it wraps must still fail.
FIELD = words(400) + "\n```\nan example the field itself fences\n```\n" + words(400)
expect("oi495-fenced-field-passes-the-cap",
       codes(L.length_fails("Here is your field, unchanged, for pasting:\n\n````\n" + FIELD
                            + "\n````\n\n" + tbl("a"), "d.md", prev="")), [])
expect("oi495-CONTROL-the-same-400-words-unfenced-still-fails",
       codes(L.length_fails(words(400) + "\n\n" + tbl("a"), "d.md", prev="")), ["ABOVE-TABLE-CAP"])
expect("oi495-three-backtick-fence-with-no-inner-fence-still-passes",
       codes(L.length_fails("quote:\n\n```\n" + words(400) + "\n```\n\n" + tbl("a"), "d.md", prev="")), [])
expect("oi495-an-example-table-header-INSIDE-a-fence-no-longer-stops-the-count",
       codes(L.length_fails("quote:\n\n```\n" + HDR + "```\n\n" + words(400) + "\n\n" + tbl("a"),
                            "d.md", prev="")), ["ABOVE-TABLE-CAP"])
expect("oi495-an-unclosed-fence-masks-to-the-end",
       codes(L.length_fails("quote:\n\n```\n" + words(400), "d.md", prev="")), [])
expect("oi495-a-tilde-fence-masks-too",
       codes(L.length_fails("quote:\n\n~~~\n" + words(400) + "\n~~~\n\n" + tbl("a"), "d.md", prev="")), [])
os.environ["IMC_ALLOW_RESEND"] = "1"
expect("override", codes(L.length_fails("hi\n\n" + tbl("a"), "d.md", prev="x\n\n" + tbl("a"))), [])
if miss:
    print("LENGTHCHECK SELFTEST FAIL\n" + "\n".join(miss)); sys.exit(1)
print("LENGTHCHECK SELFTEST PASS 22 cases"); 
