CORRECTION: my closing line after the last table named no blocker for the recommendations it described. BLOCKED: row 1 below, your decision.

Partly. "Refuse" makes the gate demand a real test on every row where I would change something. It cannot make your pure decisions testable: for "accept" or "press Add" there is nothing for me to run, so those rows still rest on their premise.

I ran the refined rule on the 46 premise-only rows in this session's drafts. It flagged 19, each proposing a change by me when I read them, and passed 27 decisions or acts of yours. The rule was tuned on these same rows, so this is not yet an independent test.

Your other requirement is unaffected: every conversation and both health checks ran the gate when last measured.

ROOT CAUSE: measured - the gate's check_untested_rec passes any TESTED label, premise-only included.

CHECKED: `python3` scan of 46 "TESTED (premise only)" table rows in this session's scratchpad drafts, with rows flagged when owned by Claude or when the Action says "I" followed by fix, build, change, make, add, remove, edit, create, write, ship, release, feed, call, update, patch, rename, move, delete or install -> 19 flagged, 27 passed; 2026-11-25 4:53 PM PST.
CHECKED: `python3` scan of the same 46 rows with the first prototype's word list -> 35 flagged, 29 of them owned by you, such as "Do: on the "Imc reply gate, From imc-claude-plugins" page ... press Add"; 2026-11-25 4:52 PM PST.
CHECKED: `get_values` on the health-log sheet -> both health checks "PASS" on "v12-e8ed2afec53d", read at 3:12 PM PST; Control_Chrome chat_conversations?limit=200 -> 17 of 17 conversations with a workspace session, read at 4:20 PM PST; 2026-11-25.
PRE-SEND REVIEW: independent reviewer returned 12 findings; 10 fixed; 2 disputed: decision rows have no change to run, and the scan count differs from the reviewer's because its word list differs; fixed rows 1.
SELF-CHECK: thorough: yes, confidence: 9/10 in row 1, lower if the released rule flags a pure decision row of yours.

PROJECT OBJECTIVE 4 - The AI Prompt Library pipeline [IN PROGRESS]
OBJECTIVE 1 - Rulings that wait on Rob (this session, under project objective 4) [IN PROGRESS]
| # | Issue / Risk | Action | Owner | Recommendation | Pros | Cons |
|---|---|---|---|---|---|---|
| 1 | OI-0808 (recommendations sent as premise-only): the gate passes any TESTED label. CAUSE: measured - 19 of this session's 46 premise-only rows proposed a change by me. BLOCKS: none | Decide: "refuse" - the gate refuses premise-only on a row I own, or whose Action says "I" plus one of the change verbs above, so I run the change first; or "keep" | Rob | RECOMMEND: choose "refuse", because it puts a mechanical test requirement on every change row, where your rule mattered today. TESTED: the scan above flagged 19 change rows and passed 27 of your decisions; it was tuned on these same rows | Change rows can no longer reach you on a premise alone | Con:&nbsp;each&nbsp;change&nbsp;row&nbsp;costs&nbsp;a&nbsp;test&nbsp;run<br>• Risk: a change row worded without those verbs slips past.<br>• Mitigation: the release ships with a selftest built from these 46 rows. |
