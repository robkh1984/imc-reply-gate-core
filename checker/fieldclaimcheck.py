#!/usr/bin/env python3
"""fieldclaimcheck.py (imc-reply-gate 0.3.83, built 2026-11-19/20 for the second trap in the
scheduled brief "instructions-backup tooling OI-0498 OI-0500 OI-0502"):

A REPLY MAY NOT SAY AN ACCOUNT INSTRUCTION-FIELD EDIT IS DONE UNLESS THE SAME REPLY QUOTES A
READ-BACK: a byte or character count AND a hash, beside a word naming the read.

WHY, MEASURED. On 2026-11-19 6:51 PM PST Rob pasted a 16,852-byte rewrite into the global
instructions field and said it was done. At 7:21 PM a session read the field back through
/api/account_profile: 455 characters, sha256 42d0b1377960a982, holding nothing but the text of two
of his own chat messages. Every rule in the field had been replaced, and the session that reported
the objective complete would have recorded it as done on his word (OI-0500). The field is the
surface that governs every other session, so a false "done" there is the most expensive sentence
this gate can let through, and it is also the cheapest to check: the read-back route exists
(navigate + get_page_text, no JavaScript, so auto mode does not refuse it) and prints both numbers.

WHAT COUNTS AS PROOF. One line of the reply carrying all three of:
    a size   - 16,851 B / 455 characters / 16852 bytes
    a hash   - 12 or more hex characters
    the read - "read-back", "read back", "account_profile", "get_page_text" or "fieldreadback"
The three must sit on ONE line, because a hash in one paragraph and a size in another is how a reply
assembles a proof out of parts that were never measured together.

LIMIT, STATED: this proves the reply quotes a read-back, not that the read-back was of this field at
this time. bin/fieldreadback.py is what compares the hash against the newest EDIT-LOG row, and
log-edit.sh GUARD 2b is what refuses to log the row without it. This check is the third of those
three, and the only one that binds what Rob is told.

    python3 fieldclaimcheck.py <draft>     exit 0 clean, 1 fail
    python3 fieldclaimcheck.py --selftest
"""
import re
import sys

# The ACCOUNT fields only. A local instruction file (~/.claude/CLAUDE.md, HOW-TO-RESUME.md) is
# covered by log-edit.sh's live-hash guard, which reads the file itself; these three cannot be.
FIELD = re.compile(r"global[-\s]instructions?(?:\s+field)?|instructions?\s+field|"
                   r"conversation[_-]preferences|cowork[_\s]global[_\s]instructions|profile\s+field",
                   re.I)
DONE = re.compile(r"\b(?:is|are|was|were|now)?\s*(?:done|complete|completed|landed|live|in place|"
                  r"pasted|saved|applied|updated|replaced|rewritten|written|shipped|set)\b", re.I)
# A sentence that denies, defers, conditions or questions the claim is not a claim. "before" and
# "would" catch the two commonest shapes: describing the state before an edit, and describing what a
# future edit would do.
NEG = re.compile(r"\b(?:not|no|never|none|cannot|can't|could ?n[o']t|did ?n[o']t|does ?n[o']t|"
                 r"is ?n[o']t|was ?n[o']t|without|unverified|unconfirmed|unchecked|refus\w*|"
                 r"unchanged|untouched|stale|fail\w*|pending|blocked|awaiting|before|would|should|"
                 r"must|needs?|if|unless|whether|until|rob's paste|his paste|do ?n[o']t)\b", re.I)
SIZE = re.compile(r"\b\d[\d,]*\s*(?:B\b|bytes?\b|chars?\b|characters?\b)", re.I)
HASH = re.compile(r"\b[0-9a-f]{12,64}\b", re.I)
READ = re.compile(r"read[-\s]?back|account_profile|get_page_text|fieldreadback", re.I)


def _units(text):
    """One unit per line, and per sentence inside a line: a next-steps row is one long line and a
    claim inside one cell of it must not be judged against a negation in another cell."""
    for ln in text.replace("\r\n", "\n").split("\n"):
        parts = re.split(r"(?<=[.;!?])\s+|\s*\|\s*", ln)
        for p in parts:
            if p.strip():
                yield p.strip()


def proof_lines(text):
    return [ln for ln in text.replace("\r\n", "\n").split("\n")
            if SIZE.search(ln) and HASH.search(ln) and READ.search(ln)]


def field_claim_fails(text):
    claims = [u for u in _units(text) if FIELD.search(u) and DONE.search(u) and not NEG.search(u)]
    if not claims:
        return []
    if proof_lines(text):
        return []
    return [("FIELD-CLAIM-UNVERIFIED",
             "the reply says an account instruction-field edit is done - %r - and no line of it quotes a "
             "read-back of that field: one line must carry a size, a hash of 12+ hex characters, and one of "
             "'read-back', 'account_profile', 'get_page_text' or 'fieldreadback'. On 2026-11-19 exactly this "
             "sentence was true of a field holding 455 characters of Rob's own chat messages. Read it back "
             "(navigate https://claude.ai/api/account_profile, get_page_text, then python3 "
             "bin/fieldreadback.py --body <that text>) and quote what it printed, or say instead that the "
             "edit is unverified." % claims[0][:160])]


def selftest():
    bad = 0
    PROOF = ("CHECKED: read-back of the live field through account_profile returned 16,851 B, "
             "sha256 3c1f4a06ab9f4db7.\n")

    def case(name, want_fail, text):
        nonlocal bad
        got = bool(field_claim_fails(text))
        ok = got == want_fail
        bad += (not ok)
        print("%s %s" % ("OK " if ok else "BAD", name))

    case("bare claim with no proof fails", True,
         "The global instructions field edit is done.\n")
    case("the same claim with a proof line passes", False,
         "The global instructions field edit is done.\n" + PROOF)
    case("a denial is not a claim", False,
         "I changed nothing in the global instructions field.\n")
    case("'that is Rob's paste' is not a claim", False,
         "The live instructions field is Rob's paste and was not touched by this run.\n")
    case("no field mentioned at all passes", False,
         "Closed OI-0498 and OI-0500; verify.sh now writes its verdict to a file.\n")
    case("conversation_preferences updated, no proof, fails", True,
         "conversation_preferences updated at 7:40 PM.\n")
    case("size but no hash is not proof", True,
         "The global instructions field is updated.\nThe read-back returned 16,851 B.\n")
    case("hash but no size is not proof", True,
         "The global instructions field is updated.\nThe read-back returned sha256 3c1f4a06ab9f4db7.\n")
    case("size and hash with no word naming the read is not proof", True,
         "The global instructions field is updated.\nIt holds 16,851 B, sha256 3c1f4a06ab9f4db7.\n")
    case("size and hash on DIFFERENT lines is not proof", True,
         "The global instructions field is updated.\nThe read-back returned 16,851 B.\n"
         "sha256 3c1f4a06ab9f4db7\n")
    case("a claim inside one cell of a next-steps row fails", True,
         "| 1 | field rewrite | the global instructions field is now in place | Rob | ship it | x | y |\n")
    case("a row whose other cells negate does not rescue the claiming cell", True,
         "| 1 | nothing was refused | the instructions field is now applied | Rob | x | y | z |\n")
    case("claim and proof on one line passes", False,
         "The profile field now reads 16,851 B, sha256 3c1f4a06ab9f4db7 on a read-back.\n")
    case("a future-tense plan is not a claim", False,
         "Rob should paste it, and then the global instructions field would be updated.\n")
    case("'unverified' in the same sentence is not a claim", False,
         "The global instructions field edit is done but unverified.\n")
    case("get_page_text wording counts as the read", False,
         "The global instructions field is updated.\n"
         "get_page_text returned 455 characters, sha256 42d0b1377960a982.\n")
    print("FIELDCLAIMCHECK SELFTEST %s" % ("ALL CONTROLS PASSED" if not bad else "BAD %d" % bad))
    return 1 if bad else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if len(argv) < 2:
        print("usage: fieldclaimcheck.py <draft>")
        return 2
    with open(argv[1], encoding="utf-8", errors="replace") as fh:
        f = field_claim_fails(fh.read())
    for c, m in f:
        print("FAIL  [%s] %s" % (c, m))
    print("FIELDCLAIMCHECK %s" % ("FAIL %d" % len(f) if f else "CLEAN"))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
