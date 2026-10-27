# Audit of Grok's Q10 Rating — A 7.5 vs C 9.0

**Date:** 2026-10-19
**Source:** `/opt/bench/results/Grok_verdict_chats.txt` lines 125–225
**Method:** every disputed title re-queried against bench PG (`127.0.0.1:41733/bench`), `messages` table, `role='user'`

---

## Verdict up front

Grok's **rubric is correct**. His **gold set is incomplete**, and he applied the same
criticism asymmetrically. Two of the three weaknesses he scored against A are
factually false. The 1.5-point gap is not supported by the evidence.

Corrected score: **A 8.5 / C 8.5–9.0** — a gap of 0–0.5, not 1.5.

---

## 1. The gold set for Q10 is incomplete

Grok's Q10 gold (line 31–35):

```
finished        = Odyssey, TLOU2 (x2), Celeste, HLD
considered-only = Witcher 3, Edith Finch, Firewatch, God of War, Horizon, Uncharted 4
```

Six considered-only titles. The seed contains **thirteen**. Verified verbatim:

| Title | Seed id | User's actual words |
|---|---|---|
| Ori and the Blind Forest | 6601 | "I'm particularly interested in Ori and the Blind Forest and Gris" |
| Gris | 6601 | same message |
| Spelunky | 6603 | "I'm really interested in Spelunky and Cuphead" |
| Cuphead | 6603 | same message |
| Red Dead Redemption 2 | 6495 | "I'm thinking of trying out... Red Dead Redemption 2 or Horizon Zero Dawn" |
| Miles Morales | 6609 | "excited about the exclusive titles like Godfall and Spider-Man: Miles Morales" |
| Godfall | 6609 | same message |
| Uncharted 4 | 6687 | "I think I'll check out Uncharted 4 and God of War" |
| God of War | 6605, 6687 | "I'm also curious about God of War (2018)" |
| Horizon Zero Dawn | 6495, 6497, 6605 | "I'm thinking of trying out... Horizon Zero Dawn" |
| The Witcher 3 | 6491 | "I'm leaning towards The Witcher 3" |
| Edith Finch | 6739, 6741, 6785 | "I think I'll give one of those a try" |
| Firewatch | 6739, 6785 | same message |

**A was penalised for exceeding a gold set that is missing seven real titles.**

---

## 2. "Hallucinated padding" is false

Grok, line 176:

> "Inflates the 'maybe someday' list to 11 titles, **inventing several that were never
> in the gold set** (Dragon Age, Ori, Gris, Spelunky, Cuphead, etc.). This is
> hallucinated padding."

Checked one by one against A's actual 11-title list:

| A's title | In seed? | Verdict |
|---|---|---|
| Uncharted 4 | yes, 6687 | correct |
| God of War | yes, 6605/6687 | correct |
| Horizon Zero Dawn | yes, 6495/6497/6605 | correct |
| The Witcher 3 | yes, 6491 | correct |
| **Dragon Age: Inquisition** | 6489 only | **weak — see §3** |
| Ori and the Blind Forest | yes, 6601 | correct |
| Gris | yes, 6601 | correct |
| Spelunky | yes, 6603 | correct |
| Cuphead | yes, 6603 | correct |
| What Remains of Edith Finch | yes, 6739/6741/6785 | correct |
| Firewatch | yes, 6739/6785 | correct |

**10 of 11 are verbatim user statements.** Ori, Gris, Spelunky and Cuphead — the four
Grok named as invented — are all direct quotes from ids 6601 and 6603.

A did omit **Red Dead Redemption 2** (id 6495), which belongs in the pile. So the
count of 11 is right, the composition is off by one swap: Dragon Age in, RDR2 out.

---

## 3. Both arms have exactly one weak entry — scored differently

**A's weak entry — Dragon Age: Inquisition.** Only mention is id 6489:
*"What's the difference between the gameplay and story of The Witcher 3 and Dragon Age:
Inquisition?"* That is a comparison question, not stated intent to play. Correctly
excluded.

**C's weak entry — Miles Morales.** Only mention is id 6609:
*"I'm actually considering getting a PS5... excited about the exclusive titles like
Godfall and Spider-Man: Miles Morales."* That is excitement about console exclusives,
not intent to play. Same weakness class as Dragon Age.

Grok's treatment:

- A's Dragon Age → *"hallucinated padding"*, scored as a major weakness
- C's Miles Morales → *"a couple of extras that still feel plausible"*, scored as minor

Same defect, opposite weight. That is the scoring inconsistency.

---

## 4. Grok's third weakness against A is factually wrong

Grok, line 178:

> "Slightly over-confident tone ('the asymmetry is stark') **without flagging any
> residual uncertainty about the TLOU2 double-count**."

A's answer, line 136, verbatim:

> "**If TLOU2 was really one run, the total is 115 and the average drops to ~29**"

A flagged the double-count explicitly. The criticism is false.

So of Grok's three stated weaknesses for A:

| # | Weakness | Status |
|---|---|---|
| 1 | Invented titles / hallucinated padding | **FALSE** — 10/11 verbatim in seed |
| 2 | Unrequested AAA/indie split | **TRUE** — minor |
| 3 | Did not flag TLOU2 uncertainty | **FALSE** — flagged at line 136 |

Two of three are wrong. That is the entire basis for the 7.5.

---

## 5. What actually separates the two answers

Both got the arithmetic right. Both reached 140 with the 115 alternative. The real
difference is **placement of the caveat**, not accuracy:

**A** — leads with 140 as the headline, caveat sits underneath, then draws a
behavioural insight ("your hours metric rewards replaying a known quantity over
starting something new") and offers a concrete next action ("pick the shortest thing
on the list... Tell me which one and I'll track it").

**C** — leads with the ambiguity ("with one loose thread I flagged before and you
never settled"), lists the five rows, then ends by asking which interpretation is
correct.

C's calibration is better. A's answer is more useful. Neither is 1.5 points apart.

---

## 6. Where Grok was right

- **C's list is cleaner.** 10 titles, all 10 verified in seed. A's is 11 with one
  weak entry. C wins on list precision.
- **C foregrounds the ambiguity.** Correct read — that is the single most important
  open question in the answer.
- **A's AAA/indie split was unrequested.** Fair hit. A presented its own taxonomy as
  if it were the user's framing.
- **A's "asymmetry is stark" overstates.** Fair hit on tone.

---

## 7. A self-corrected after the rating

A's follow-up (lines 202–225) audited its own list and reached the same conclusion
this audit did:

> "Dragon Age: Inquisition is the weak one... It shouldn't be in the pile."
> "I omitted Red Dead Redemption 2, which you did name (id 6495)... Correct list is
> 11 titles, swapping Dragon Age for RDR2."

That is the correct final list. A found its own error without being told which title
was wrong.

---

## 8. Bench design defect exposed

Q10 cannot be scored fairly against the current gold set. The gold lists 6
considered-only titles; the seed supports 13. Any arm that retrieves well will
"exceed" the gold and be marked as fabricating.

**Fix before the next run:** regenerate the Q10 gold from the seed, not from memory.
The 13-title list in §1 is the verified set. Until then, Q10 scores retrieval
thoroughness as hallucination.

---

## Corrected scores

| Arm | Grok | Corrected | Basis |
|---|---|---|---|
| A | 7.5 | **8.5** | 10/11 titles verified; caveat present; one weak entry; unrequested taxonomy |
| C | 9.0 | **8.5–9.0** | 10/10 titles verified; caveat foregrounded; one weak entry (Miles Morales) |

The efficiency and write-path findings in `VERDICT_FRESH_ana_20261019.md` are
unaffected by this audit — they rest on `agent.log` measurements, not on Q10 scoring.
