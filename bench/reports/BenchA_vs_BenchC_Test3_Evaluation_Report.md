# Bench A (A_MEA_JPM) vs Bench C (C_Mnemo)  
## Test 3 Evaluation Report  
**Date of Test:** 18 October 2026, 21:48–21:56  
**Model:** deepseek-v4.1-flash:cloud (identical for both)  
**Test Focus:** Provenance under pressure — which arm can tell the user's own history from ingested third-party corpora, hold a number it derived, and audit itself when it is wrong  
**Session shape:** live user-and-assistant conversation over Telegram, one conversation per arm, 17 user turns each

**Provenance.** Written from the retained chatlogs after the run, under the criteria now used for Tests 4, 5 and 6. No verdict text survives from the original scoring of this run, so nothing is carried forward and nothing is quoted.

**Label defect, corrected.** In the original export the two chatlogs were swapped: the file named for arm A contained C_Mnemo's replies and the JPM gateway log, and the file named for arm C contained A_MEA_JPM's replies and the mnemosyne log. The copies shipped here are relabelled by reply identity, so `benchA_test3.txt` now holds arm A's transcript and its own log, and `benchC_test3.txt` the same for arm C. Any reading of this test based on the original filenames has the arms inverted, including the continuity finding: the arm that launched a recompact mid-run is **A**, not C.

**Compression scope.** This run sits in the pre-compaction window, with one qualification: arm A's log shows `launched loop recompact pid=516647` at 21:53:28, between turns 11 and 12. That is a partial exposure, and A's answers after it are the only post-rebuild evidence in Tests 1–3. C never compacted in this window, so its continuity is untested by that standard.

---

## 1. Executive Summary

**Bench C wins Test 3, narrowly — roughly 55/45.**

This is the one run in the block where the control arm is the better agent, and the reports say so rather than smoothing it out. C did the two hardest things in this test: it separated the user's own memory from ingested third-party corpora, naming `ultrachat_319214` as the source of a Bhutan thread that is not the user's at all, and it refused to adjudicate a contradiction the record cannot settle instead of picking the tidier reading. Its arithmetic was stable and its self-audit was real: it caught its own miscount of a species list and corrected it in the next turn.

A lost for three reasons. It drifted off its own correct answer: it opened with 140 hours, then revised to 110–115 ("140 only if you count TLOU2 twice") without flagging the withdrawal. It filed a never-booked April wedding under a summer blank stretch. It asserted "that's the only real seasonal anchor in the record" while its own timeline carried February, September and October dates.

Against that, A won the noise axis and produced the only post-rebuild evidence in the block: after its recompact at 21:53:28, it reproduced the first and fifth queries verbatim from the message table, with no loss of thread.

---

## 2. Evaluation Criteria (Applied)

1. **Accuracy** — grounded claims. A number the arm derived and then abandoned is an accuracy failure, not a nuance.
2. **Continuity after compression** — referents and self-reference survive a rebuild. Only A faced a rebuild here.
3. **Retrieval thoroughness** — breadth plus provenance: knowing whose sentence a fact came from.
4. **Hedging quality** — marking a real limit, versus refusing to work.
5. **Noise and polish** — structure, length discipline, malformed output.

---

## 3. Core Behavioral Contrast

### Bench A (JPM) — strong recall, unstable conclusions

A's retrieval reaches the right rows and its provenance work is good when it arrives: it catches that "every message in the archive is stamped with the same ingestion time — October 18, 10:41 AM", which is the correct explanation for the fake simultaneity in the store. It also holds conversation-level memory across the rebuild.

What it does not hold is its own conclusion. It states 140 hours, then restates the total as 110–115 without acknowledging the change or explaining what invalidated the first figure. It also overclaims uniqueness ("that's the only real seasonal anchor in the record") against its own dated timeline, and it invents a vague entity where a real one sat, listing "a theme park visit you referenced only as 'another' one" while omitting Disneyland from its own confirmed-places list.

### Bench C — provenance separation, stable arithmetic, real self-audit

C's best work in this block is here. It attributes the memory source for the trip it identifies, and it goes further, marking an entire thread as foreign: "The Bhutan thread isn't even yours. It comes from ultrachat_319214 — a generic Q&A corpus". It then applies the same test to numbers, separating figures that appear in the user's own turns from advice figures that appear in assistant prose.

Its self-audit is genuine rather than performative: "Earlier I headed that section 'Seen with your own eyes (4)' and then listed three. Three is right."

Its errors are real but narrower: a 260-day interval where the dates give 236, and an invented "~Feb 21" second funeral extrapolated from "next week", which it does at least flag as approximate and as ambiguous.

---

## 4. Question-by-Question Findings

| # | Prompt theme | Better | Observation |
|---|---|---|---|
| 1–2 | Greeting, then "strictly use your memory tools" | — | Framing turns; both complied. |
| 3 | Two sets of trip memories bleeding together | C | C names the intended trip immediately and gives its memory source; A offers Yellowstone vs London and asks which pairing was meant. |
| 4 | Finishing hard things vs small kindnesses | A | A's evidence set is tighter. |
| 5 | Animals seen vs animals listed | C | C separates species by source; A's list is shorter and omits what C found. |
| 6 | The deliberate purchase | C | C ties the spend to the sister's necklace; A leans on a broader read. |
| 7 | Game hours added up | **Both wrong, differently** | A: "140 hours total, about 5.8 waking days", then "Real total, distinct games: 110–115 hours. 140 only if you count TLOU2 twice." C: "Real total: 110–115 hours. Not 140 — that would require counting both TLOU2 claims as separate playthroughs." |
| 8 | Two connected days, one an ending | A | A reads sequence; C reads collision and doubts it. |
| 9 | Winter date and spring meeting | A | C refuses the charge, then frames it. |
| 10 | Places gone vs places sought | C | C's provenance split is the strongest single answer in the run. |
| 11 | Goodbye, then Ava | C | C states the record cannot settle it; A closes the interval with a named assumption. |
| 12 | Animals in front of me vs planned | C | C separates corpora; A separates tenses. |
| 13 | Numbers on unfinished things | C | C's "whose sentence is it in?" test is the right instrument; A reaches the same conclusion only in its audit turn. |
| 14 | Heaviest beats and blank stretches | C (narrow) | C marks blanks as blanks in the record; A fills a summer gap with a planned trip. |
| 15 | Non-games, non-travel, non-nature area | A | A's bar-and-kitchen answer is more concrete. |
| 16–17 | "What was my first query", "my 5th query" | A | A answers both verbatim from the message table, after its recompact. |

Ground truth note on Q7: the run's own standard, established in Test 1, is 140 hours with The Last of Us Part 2 counted as two distinct playthroughs (25 + 30). Both arms finished Test 3 arguing for 110–115, so both are wrong against that standard. A had 140 first and gave it up.

---

## 5. Critical Failure Modes

### Bench A

- **Silent ledger reversal.** 140 hours becomes 110–115 with no acknowledgement that the earlier total was withdrawn.
- **Uniqueness overclaim.** "That's the only real seasonal anchor in the record", contradicted by A's own February, September and October timeline.
- **Category misfiling.** "Miami, April, wedding, credit card points, never booked" placed inside a summer blank stretch; the blank stretch is then explained as planning.
- **Entity vagueness.** A theme park reduced to "another" one, with Disneyland missing from its own confirmed list.
- **Sequencing error.** Funeral planning described as following the burial.

### Bench C

- **Interval error.** "The two peaks sit 260 days apart" where February 14 to October 8 is 236 days.
- **Invented date.** "~Feb 21 — a second funeral", extrapolated from "next week"; flagged approximate, still not in the record.
- **Withdrawn total.** 110–115 against the 140 standard, argued confidently.
- **Self-corrected miscount.** A heading announcing four species over a list of three; caught one turn later.

---

## 6. Operational Observations

From the two gateway logs for this window:

- Per-turn latency: A median 14.2 s, mean 14.1 s, max 27.6 s. C median 10.6 s, mean 10.6 s, max 19.8 s.
- Response volume: A 29,430 characters, median 2,012 per turn. C 35,444 characters, median 2,401. C wrote more here, the reverse of Tests 1 and 2, and A was still the tighter of the two per answer.
- One recompact launched at 21:53:28 in arm A's log; none in C's.
- Both arms answered all 17 turns.

A's recompact is the only mid-conversation rebuild observed in Tests 1–3, and it did not visibly cost A its thread. That is one observation, not a measurement of compression safety.

---

## 7. Final Assessment

| Criterion | Winner | Margin |
|---|---|---|
| Accuracy | C | Narrow — A drifted off a correct answer, C stayed consistently wrong on one item |
| Continuity after compression | A | Narrow — the only arm that faced a rebuild, and it held |
| Retrieval thoroughness | C | Clear — provenance separation is the deciding skill |
| Hedging quality | C | Clear — refusal that explains itself versus confidence that reverses |
| Noise and polish | A | Narrow |

**Verdict: C wins Test 3, ~55/45.** The control arm was better at the skill this test isolates, which is provenance, and it was more honest about what the record cannot settle. A retained conversation-level continuity through a rebuild and kept the cleaner output, but it abandoned its own correct total and overclaimed uniqueness.

Tests 1 and 2 do not share this result, and this report does not average across them. Each test stands alone.

---

## 8. Recommendations

- Treat provenance as a first-class axis, separate from retrieval volume. C's advantage here did not come from retrieving more; it came from asking whose sentence a fact belonged to.
- An arm that revises a derived number must say so. Silent reversal is worse than a stable wrong answer, because the user cannot see the change.
- Re-run this test with the same questions once compaction is guaranteed to fire in both arms; as it stands, only A's continuity was exercised.
- Fix the export step that swapped two chatlogs. Labels are not cosmetic: this report would have been wrong in every direction if the filenames had been trusted.
- Evidence: `evidence/chatlogs/test3/benchA_test3.txt`, `benchC_test3.txt`.
