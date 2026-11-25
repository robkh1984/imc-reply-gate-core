#!/usr/bin/env python3
"""Acronym first-use gate. Flags a token from the ALLOWLIST used before its expansion.

THE DESIGN DECISION, AND THE MEASUREMENT BEHIND IT. The industry rule (Microsoft Writing
Style Guide, Hyperlint, both via Vale's conditional check) flags every 3-5 letter capital
token and exempts ~50 known-safe ones. Run against Rob's live Instructions field on
2026-09-10 that produced 1,951 matches, 1,926 after its exceptions list, led by THE x268,
NOT x107, AND x103 - because his house style shouts for emphasis and English words are 3-5
letters. Filtering out tokens inside a run of 3+ consecutive all-caps words cut it to 142,
which is a 93% reduction and still not a gate anyone would leave on.

SO THIS INVERTS IT. Only tokens on the allowlist are ever considered. The checker never has
to decide whether THE is an acronym, because THE is not on the list. False positives on
emphasis are impossible by construction. The failure mode becomes a MISSED acronym - one
wrong word in one document - instead of a gate that gets switched off, which would leave the
rule enforced by nothing.

Scope beats the default: a row scoped "yosemite" wins over the same token scoped "*". That is
what resolves NPS, which is National Park Service in a trip document and Net Promoter Score
in a product one - the collision a downloaded glossary would have got wrong.

Usage:  python3 acronym_check.py [--scope NAME] [--map PATH] FILE [FILE...]
        python3 acronym_check.py --stats [--scope NAME] FILE [FILE...]
        python3 acronym_check.py --selftest
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MAP = os.path.join(HERE, "acronyms.tsv")


def load_map(path, scope="*"):
    rows = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4 or parts[0] == "token":
                continue
            token, cls, expansion, row_scope = parts[0], parts[1], parts[2], parts[3]
            skip = parts[4] if len(parts) > 4 else ""
            if row_scope not in ("*", scope):
                continue
            prev = rows.get(token)
            # a scoped row beats a "*" row; otherwise first wins
            if prev is None or (row_scope != "*" and prev["scope"] == "*"):
                rows[token] = {"class": cls, "expansion": expansion.strip(),
                               "scope": row_scope, "skip": skip.strip()}
    return rows


def _expansion_regex(expansion):
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", expansion) if p]
    return re.compile(r"[\s\-]+".join(parts), re.I)


AFTER_WINDOW = 140      # chars after a token in which an expansion still counts as first-use
ENUM_RADIUS = 90        # chars either side searched for sibling tokens
ENUM_SIBLINGS = 2       # this many other map tokens nearby makes it a list, not a use


# *** A LITERAL QUOTED STRING IS NEVER A USE, AND ROB'S RULE ALREADY SAID SO. *** The
# Instructions field states it outright: a token inside a literal quoted string is never
# expanded whatever its class, because the prompt-library memory file records a spreadsheet
# column as "Target LLM (tier routing)" and rewriting that would make a measured record wrong.
# The gate did not implement it, because instruction prose almost never quotes.
#
# MEASURED 2026-09-10 OVER 821 ASSISTANT REPLIES, WHICH IS WHY THIS EXISTS. 78 flags, 27 of
# them not real violations. The classes were quoted strings, code spans and dotted or
# hyphenated identifiers - none of which appears in a memory file, which is exactly why the
# 0-false-positive figure measured on instruction prose did not predict behaviour on replies.
# Replies quote rules back verbatim, paste tool output and name files.
FENCE_RE = re.compile(r"(?ms)^(```|~~~).*?^\1")
CODE_RE = re.compile(r"`[^`\n]+`")
DQUOTE_RE = re.compile("[\"\u201c][^\"\u201c\u201d\n]{1,300}[\"\u201d]")
SQUOTE_RE = re.compile(r"(?<![A-Za-z0-9])'[^'\n]{1,300}'(?![A-Za-z0-9])")
# AN IDENTIFIER, NOT PROSE, AND THE THRESHOLD IS TWO SEPARATORS RATHER THAN ONE. With one,
# "the API-derived tier" would be silenced - a genuine bare use, measured in turn0062 of the
# live corpus. With two, `project-AI-Prompt-Library-instructions` and
# HANDOFF-from-AI-Prompt-Library-2026-08-15.md are silenced and that use still flags.
IDENT_RE = re.compile(r"[A-Za-z0-9]+(?:[-_./][A-Za-z0-9]+){2,}")


# *** TITLE-NAMING: RULED BY ROB 2026-09-10 - NAMING AN ITEM BY ITS TITLE IS A NAME, NOT A
# USE. *** Implementing that ruling as a POSITIONAL heuristic was attempted four ways and
# three of the four were measured WORSE THAN USELESS on 3,610 assistant turns, so only the
# fourth ships. What was tried, and what each removed / how many of those removals were wrong:
#   number + phrase + token          15 removed, 11 WRONG - it eats quantities: "the 8 MCP
#                                    servers", "13 UI operations", "Orbi 10G LAN port"
#   Title Case run of 3 or more       7 removed,  6 WRONG - Rob's house style SHOUTS, so
#                                    "USE THE API" is three capitalised words, and it also
#                                    ate "the Apps Script API enabled"
#   hyphenated identifier + token     8 removed,  5 WRONG - adjective compounds look identical
#                                    to item names: "hover-dependent UI", "per-project API"
#   ordinal WORD + number             4 removed,  3 WRONG - "STEP 0 uses the API" matched
# THE ONE THAT SURVIVED IS THE NARROWEST: a ZERO-PADDED ordinal, which in this corpus only
# ever introduces a catalogue item - "dropping 01 (PRD, ...)", "prompt 07 (MCP server)",
# "07-09 TPM Onboarding". 4 removals, 4 correct, 0 wrong. The broader ruling therefore lives
# in skip_regex per named item and in the literal-span rules, NOT in a position test, and
# that limit is measured rather than assumed.
# *** THE LABEL RULING: RULED BY ROB 2026-09-10, AND IT NARROWS THE LINE ABOVE RATHER THAN
# WIDENING IT. A COINED ALL-CAPS ITEM LABEL IS NOT A TITLE. *** The title-naming ruling covers
# the title of a thing that EXISTS - a document, a product, a catalogue entry. It does NOT cover
# a label Claude invented three replies earlier and is now referring back to: SSID MISMATCH as a
# named rival hypothesis, FORGET THE IoT SSID as a named next-steps row. Those are Claude's own
# words about Claude's own list, and the acronym inside them is doing its ordinary semantic work.
# WHY THIS MATTERS MORE THAN THE SIX FLAGS IT DECIDES: if a coined label counted as a title, the
# gate would be defeated by capitalising a phrase, which is a silencer any writer can reach for
# without noticing they have. The rule has to be one the writer cannot author their way around.
# MEASURED ON 177 CHAT TURNS, 2026-09-10: exactly 6 flags turn on this question. Reader one
# cleared all six as titles; a second reader given only Rob's definitions cleared none of them.
# Applying the ruling moves reader one's residual from 11 false positives to 5, and leaves the
# second reader's 17 untouched, because that reader had already scored them as violations.
# A COUNT IN THE REPLY THAT PROPOSED THIS RULING SAID NINE AND WAS WRONG; THE SET IS SIX, and it
# is recorded here rather than corrected silently.
# NOTHING IN THE CODE CHANGES. _title_spans already matches only a zero-padded ordinal, so the
# gate ALREADY behaves this way; the ruling is written down to stop a future pass from widening
# the position test to reach these six, which is the same mistake the four ablations above
# measured and rejected.
ORDINAL_TITLE = r"\b0\d\b\s*[:.)]?\s*\(?\s*(?:[A-Z][\w&/'-]*[\s&/-]+){0,4}%s\b"


def _title_spans(text, token):
    return [m.span() for m in re.finditer(ORDINAL_TITLE % re.escape(token), text)]


def _literal_spans(text):
    """Spans in which a mapped token is being QUOTED or NAMED rather than used."""
    spans = []
    for rx in (FENCE_RE, CODE_RE, DQUOTE_RE, SQUOTE_RE, IDENT_RE):
        spans.extend(m.span() for m in rx.finditer(text))
    return spans


def _in_enumeration(text, pos, token, amap):
    """True when the occurrence sits in a comma-separated run of other mapped tokens."""
    lo = max(0, pos - ENUM_RADIUS)
    hi = min(len(text), pos + ENUM_RADIUS)
    window = text[lo:hi]
    if "," not in window:
        return False
    siblings = 0
    for other in amap:
        if other == token:
            continue
        if re.search(r"\b%s\b" % re.escape(other), window):
            siblings += 1
            if siblings >= ENUM_SIBLINGS:
                return True
    return False


def check_text(text, amap):
    """Return a list of (token, position, line_no) for tokens used before their expansion."""
    findings = []
    lit_spans = _literal_spans(text)
    for token, row in sorted(amap.items()):
        if row["class"] != "expand" or not row["expansion"]:
            continue
        # CASE-INSENSITIVE ON PURPOSE. skip_regex describes a CONTEXT - a folder path, a
        # product title - and the same context appears cased differently in the same file.
        # The one flag left after the enumeration and after-window fixes was exactly this:
        # an aliases line carrying "AI prompt library" where the pattern said "AI Prompt Library".
        skip_re = re.compile(row["skip"], re.I) if row["skip"] else None
        skip_spans = [m.span() for m in skip_re.finditer(text)] if skip_re else []
        skip_spans += _title_spans(text, token)

        occ = []
        for m in re.finditer(r"\b%s\b" % re.escape(token), text):
            if any(a <= m.start() < b for a, b in skip_spans):
                continue
            if any(a <= m.start() < b for a, b in lit_spans):
                continue
            occ.append(m.start())
        if not occ:
            continue

        exp_re = _expansion_regex(row["expansion"])
        dm = exp_re.search(text)
        def_at = dm.start() if dm else None

        first = occ[0]
        if def_at is not None and def_at <= first:
            continue
        # DEFINED IMMEDIATELY AFTER counts as defined at first use. The narrow
        # "TOKEN (Expansion)" form was not enough: real text writes 'PM means "Product
        # Manager"' and 'the 2023 US-NWL - the NASPA Word List, from the ...', both of
        # which define on the spot and both of which the parenthetical-only test flagged.
        window = text[first: first + len(token) + len(row["expansion"]) + AFTER_WINDOW]
        if exp_re.search(window):
            continue
        # A LIST OF ACRONYMS IS A MENTION, NOT A USE. A rule that enumerates its own
        # tokens - "ISP, LAN, SSID, IoT, DSLR ... EXPAND THESE" - is talking ABOUT them.
        # Eleven of the eighteen first-run flags were this one sentence.
        if _in_enumeration(text, first, token, amap):
            continue
        findings.append((token, first, text.count("\n", 0, first) + 1))
    return findings


def _selftest():
    amap = {
        "NPS": {"class": "expand", "expansion": "National Park Service", "scope": "yosemite", "skip": ""},
        "API": {"class": "expand", "expansion": "application programming interface", "scope": "*", "skip": ""},
        "LiDAR": {"class": "expand", "expansion": "light-detection-and-ranging", "scope": "*", "skip": ""},
        "PM": {"class": "expand", "expansion": "Product Manager", "scope": "*",
               "skip": r"\d{1,2}(:\d{2})?\s*PM"},
        "GM": {"class": "never", "expansion": "", "scope": "*", "skip": ""},
        "AI": {"class": "expand", "expansion": "artificial intelligence", "scope": "*",
               "skip": r"Master AI Prompt Library"},
        "NWL": {"class": "expand", "expansion": "NASPA Word List", "scope": "*", "skip": ""},
        "NASPA": {"class": "expand", "expansion": "North American Scrabble Players Association", "scope": "*", "skip": ""},
        "ISP": {"class": "expand", "expansion": "Internet Service Provider", "scope": "*", "skip": ""},
        "LAN": {"class": "expand", "expansion": "local area network", "scope": "*", "skip": ""},
        "JSM": {"class": "expand", "expansion": "Jira Service Management", "scope": "*", "skip": ""},
    }
    cases = [
        ("flags a bare first use", "The NPS page says it is open.", ["NPS"]),
        ("passes when defined first", "The National Park Service (NPS) page. NPS again.", []),
        ("passes the parenthetical order", "NPS (National Park Service) says so.", []),
        ("tolerates hyphen drift", "light detection and ranging is off; LiDAR later.", []),
        ("flags the second token only", "The application programming interface (API) and the NPS page.", ["NPS"]),
        ("never-class is never flagged", "A Sony GM lens, and another GM.", []),
        ("clock times do not flag PM", "Ready from 1 PM, and back by 8 PM.", []),
        ("a real PM does flag", "Rob is a senior PM at Ford.", ["PM"]),
        ("SHOUTED EMPHASIS IS NOT FLAGGED", "THE RULE IS THAT YOU MUST NOT DO THIS AND NEVER THAT.", []),
        ("defined immediately after, no parens",
         'PM means "Product Manager" in this file.', []),
        ("defined after with a dash",
         "set to the 2023 NWL - the NASPA Word List, from the association", ["NASPA"]),
        ("an enumeration of tokens is a mention",
         "GENUINE ACRONYMS: ISP, LAN, NPS, API, LiDAR - EXPAND THESE.", []),
        ("a comma near a lone token still flags",
         "Check the NPS page, then drive.", ["NPS"]),
        # ---- TITLE-NAMING, ruled by Rob 2026-09-10. Positive AND negative. ----
        ("a zero-padded ordinal names an item, it does not use the token",
         "The digest justified dropping 01 (PRD, overlaps existing rows).", []),
        ("a zero-padded ordinal before a titled phrase is a name",
         "Only prompt 07 (NPS Dashboard) drops, on 16 hits.", []),
        ("A QUANTITY IS NOT AN ORDINAL and must still flag",
         "Missing piece is the 8 API servers on that slide.", ["API"]),
        ("an unpadded number before the token still flags",
         "far safer than 13 API operations", ["API"]),
        ("skip_regex ignores casing",
         "aliases: [Master AI prompt library, other]", []),
        # ---- LITERAL SPANS. Added 2026-09-10 from the 821-reply corpus measurement. ----
        ("a backticked identifier is not a use",
         "Audit `project-AI-Prompt-Library-instructions` today.", []),
        ("a dotted filename is not a use",
         "See HANDOFF-from-AI-Prompt-Library-2026-08-15.md in that folder.", []),
        ("a double-quoted string is a literal",
         'The skill says "Jira, JSM, Confluence" already.', []),
        ("a single-quoted path is a literal",
         "One folder is 'AI TODOs/AI Photos to clean up' on the Desktop.", []),
        ("a fenced block is a literal",
         "before\n```\nthe API returned 404\n```\nafter", []),
        # *** THE NEGATIVE CONTROLS. A silencer with no floor silences everything. ***
        ("ONE hyphen is prose and still flags",
         "Browser control is available. Proceeding with the API-derived tier.", ["API"]),
        ("a bare use beside a quoted one still flags",
         'He said "hello there" and then read the NPS page.', ["NPS"]),
        ("a bare use after a code span still flags",
         "Ran `verify.sh` and then hit the LAN directly.", ["LAN"]),
    ]
    passed = failed = 0
    for name, text, expect in cases:
        got = sorted(t for t, _, _ in check_text(text, amap))
        if got == sorted(expect):
            passed += 1
        else:
            failed += 1
            print("  FAIL %-34s expected %r got %r" % (name, expect, got))
    print("selftest: %d passed / %d failed" % (passed, failed))
    return 0 if failed == 0 else 1


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        sys.exit(_selftest())
    scope = "*"
    mappath = DEFAULT_MAP
    stats = False
    files = []
    i = 0
    while i < len(argv):
        if argv[i] == "--scope":
            scope = argv[i + 1]; i += 2
        elif argv[i] == "--map":
            mappath = argv[i + 1]; i += 2
        elif argv[i] == "--stats":
            stats = True; i += 1
        else:
            files.append(argv[i]); i += 1
    if not files:
        print(__doc__); sys.exit(2)
    amap = load_map(mappath, scope)
    total = 0
    for path in files:
        text = open(path, encoding="utf-8", errors="ignore").read()
        f = check_text(text, amap)
        total += len(f)
        if stats:
            print("%-58s %d" % (os.path.basename(path)[:58], len(f)))
        else:
            for token, pos, line in f:
                print("%s:%d: '%s' used before its expansion" % (os.path.basename(path), line, token))
    if stats:
        print("%-58s %d" % ("TOTAL", total))
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
