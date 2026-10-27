# Test 3 Evaluation Report  
**Bench A:** stock Hermes + MEA plugins + PostgreSQL + embeddings  
**Bench C:** stock Hermes + Mnemosyne + embeddings  
**Date of Test:** 18 October 2026, 21:48 to 21:56  
**Model:** deepseek-v4.1-flash:cloud (identical for both)  
**Test Focus:** Provenance under pressure: which arm can tell the user's own history from ingested third-party corpora, hold a number it derived, and audit itself when it is wrong  
**Session shape:** live user-and-assistant conversation over Telegram, one conversation per arm, 17 user turns each

**Provenance.** Written from the retained chatlogs after the run, under the criteria now used for Tests 4, 5 and 6. No verdict text survives from the original scoring of this run, so nothing is carried forward and nothing is quoted.

**Scoring basis, stated plainly.** [`questions.txt`](../questions/questions.txt) holds the prompts put to both arms. Its `IDEAL:` lines are one agent's suggested answers, written after the runs and not audited against the corpus. They are a checklist, not ground truth, and this report does not treat them as authority. Eight rows are decided from the two transcripts alone: which arm cited a source, which arm wrote the split, which arm produced the number and how, which arm named the object it had not bought. Six rows rest on a marked answer that the transcripts cannot confirm on their own: Q3, Q8, Q9, Q11, Q14 and Q15. Where a marking and a transcript disagree, the transcript wins. Every row that decides this run is a transcript row, and all of them are A's. The Q7 marking itself was corrected to 140 after review, because the question asks for hours put in and both runs of The Last of Us Part II were played.

**Label defect, corrected.** In the original export the two chatlogs were swapped: the file named for arm A contained C_Mnemo's replies and the JPM gateway log, and the file named for arm C contained A_MEA_JPM's replies and the mnemosyne log. The copies shipped here are relabelled by reply identity, so `benchA_test3.txt` now holds arm A's transcript and its own log, and `benchC_test3.txt` the same for arm C. Any reading of this test based on the original filenames has the arms inverted, including the continuity finding: the arm that launched a recompact mid-run is **A**, not C. The relabelling is checkable inside the files rather than asserted: `benchA_test3.txt` carries 75 messages under the A_MEA_JPM name against none under C_Mnemo, 23 `vault` calls against zero `mnemosyne_recall` calls, and an appended 354-line gateway log containing `_mea_loops_core` and `jpm` entries; `benchC_test3.txt` carries 31 C_Mnemo messages, 62 `mnemosyne_recall` calls, no `vault` call, and a 212-line log with 45 mnemosyne entries and no MEA entry. The two session identifiers inside the logs, 20261018_214808_bd4015e2 and 20261018_214804_43b7c197, do not overlap.

**Compression scope.** This run sits in the pre-compaction window, with one qualification: arm A's log shows `launched loop recompact pid=516647` at 21:53:28, between turns 11 and 12. That is a partial exposure, and A's answers after it are the only post-rebuild evidence in Tests 1 to 3. C never compacted in this window, so its continuity is untested by that standard.

**Corrections to the previous version of this report.** The earlier text awarded this run to C at roughly 55/45. That reading was assembled from each arm's own closing summary rather than from the questions and the two transcripts, and re-scoring it against [`questions.txt`](../questions/questions.txt) moves four rows and voids one standard the report had invented for itself:

- **Q6** credited C with tying the spend to the sister's necklace. C never mentions the necklace in that answer. It names the Wishbone Chair, an item the key records as never bought, treating the user's "exciting news about the new reading chair" as a purchase and offering to write it into the store as one. C's own Test 6 log says that line "precedes your shopping question and reads like me echoing your intention, not recording a purchase" (`benchC_test6.txt:38`). A answers with the plush rug, bought "last month", and excludes the chair with the user's own wording: "I'm thinking of getting" and "still thinking about the fabric options". Both arms miss the necklace; only C invents a purchase.
- **Q3** credited C with naming the intended trip. C named the family road trip against an Aspen plan. The key's pair is the Yellowstone backpacking trip, taken last month, against the John Muir Trail, researched and never walked. A named that pair and explained why the two blur.
- **Q5** was scored to C. It is A's. A answered in the user's own frame and wrote the split into the store; C attached record ids and then deferred the write with "Want me to write that?" Record ids on a split you never wrote are not the answer to the question asked.
- **Q7** was scored twice wrongly. The first version called both arms wrong against 140. The second version called both arms right against 115. The key is 140: the question asks for hours put in, and The Last of Us Part II was played twice, 25 hours on normal and 30 on hard, so both runs count. A led with 140 and showed its work. C refused it outright, writing "Not 140", and offered 110 or 115 instead.

Two further rows moved to unresolved for the same reason. On Q9 and Q11 A asserted that no spring anchor exists and C declined to adjudicate, but the record does hold 14 February and 27 May, which neither arm produced. That is a miss for both, not a win for either.

---

## 1. Executive Summary

**Bench A wins Test 3, six rows to three, and four of the thirteen questions are unresolved by both arms.**

A wins this run on the two things the test was built to isolate. Asked which of two blurring trip sets was actually walked, it named the pair the record supports and said why they blur. Asked for the deliberate purchase, it produced a real one and quoted the user's own words to rule out the object that was never bought. It also produced the only post-rebuild evidence in the block: after its recompact at 21:53:28 it answered "what was my first query" and "my 5th query" verbatim from the message table.

C still does the best provenance work in the block and it earns three rows on it. It attaches a record id to every claim, it marks an entire thread as foreign, and it applies the same test to numbers. But it also writes a confident purchase that never happened and offers to commit it to memory, which is the failure this test exists to catch.

Neither arm answered four of the thirteen questions. That is a fact about the corpus as much as about the arms, and it is recorded rather than hidden.

---

## 2. Evaluation Criteria (Applied)

1. **Accuracy** - grounded claims, scored against the transcripts and the marked answers in [`questions.txt`](../questions/questions.txt). A claim the record contradicts is a hard error; a disclosed miss is not.
2. **Continuity after compression** - referents and self-reference survive a rebuild. Only A faced a rebuild here.
3. **Retrieval thoroughness** - breadth plus provenance: knowing whose sentence a fact came from.
4. **Hedging quality** - marking a real limit, versus refusing to work, versus inventing an answer.
5. **Noise and polish** - structure, length discipline, malformed output.
6. **Tokenomics** - input tokens per call, API round-trips per turn, and memory-payload volume. Recorded with real measurements; it explains cost, it does not decide the verdict.

---

## 3. Core Behavioral Contrast

### Bench A (MEA + PostgreSQL) - the right pair, stated plainly, one honest miss

A's retrieval reaches the right rows, and it names the defect in the timestamps: "every message in the archive is stamped with the same ingestion time", with the timestamp reading "October 18, 10:41 AM", which is the correct explanation for the fake simultaneity in the store. That is an observation about the store's metadata, not a provenance call about a memory. Across seventeen replies A cites one internal row number (memory id 201) and no source at all, and never marks a thread as foreign; its closest move is the plain-language admission that the Yosemite list is "a list I handed you".

What it gets right is the discrimination itself. On the two blurring trip sets it names the Yellowstone backpacking trip against the John Muir Trail, which is the key's pair, rather than guessing at the nearest two threads. On the purchase it produces the plush rug and rules out the chair by quoting the user back to himself. It holds conversation-level memory across the rebuild and answers the two query-order questions verbatim from the message table.

What it does not hold is its own conclusion. It opens with 140 hours and decomposes the number: ACO 50 per cent, TLOU2 39 per cent, and the observation that counting one run rather than both would give 110 to 115. Its later audit then re-scores the same four games at 110 to 115 and calls that the verified total, leaving 140 as the conditional. Both figures stay on the record, so nothing is concealed, but the audit ends on the number the key rejects. It also overclaims uniqueness ("that's the only real seasonal anchor in the record") against its own February, September and October timeline, misfiles a never-booked April wedding into a summer blank stretch, and reduces a theme park to "another" while leaving Disneyland out of its confirmed list.

### Bench C - provenance separation, an unstable record, one invented purchase

C's provenance work is the strongest single skill either arm showed in this block, and it wins C three rows. It does not win the run. It attributes the memory source for the trip it identifies, and it goes further, marking an entire thread as foreign: "The Bhutan thread isn't even yours. It comes from ultrachat_319214". It applies the same test to numbers, separating figures that appear in the user's own turns from advice figures that appear in assistant prose, and it names the test as an instrument: "whose sentence is it in?" Its self-audit is genuine rather than performative: it wrote a heading announcing four species over a list of three, then said so itself: it "headed that section" as seen-with-own-eyes and "then listed three"

Its errors are of a different and more expensive kind. On the purchase it answers with the Wishbone Chair, an object the user was still deciding about, and offers to "write a single entry recording it as a real purchase". That is a fabrication in the exact place the test isolates, and it is the item C itself ruled unmade in Test 6. Its arithmetic carries a 260-day interval where the dates give 236, and an invented "~Feb 21" second funeral extrapolated from "next week", flagged approximate. It also puts the year of the record six months out when laying out the timeline, which is what the twelve-day cluster in Q14 rests on.

---

## 4. Question-by-Question Findings

| # | Prompt theme | Better | Observation |
|---|---|---|---|
| 1-2 | Greeting, then "strictly use your memory tools" | - | Framing turns; both complied. |
| 3 | Two sets of trip memories bleeding together | A | Marked: Yellowstone (walked last month) against the John Muir Trail (researched, never walked). A names that pair and explains the blur. C names the family road trip against an Aspen plan and asks the user to confirm a different pair. |
| 4 | Finishing hard things vs small kindnesses | A | Both reach disjoint sets and both say so; A's evidence set is tighter, C lists the JMT under things finished when it was only researched. |
| 5 | Animals seen vs animals listed | A | Marked: hummingbird, Yellowstone grizzly, wolves seen; the Yosemite list and the Bhutan itinerary only named. Both arms split the same three from the same two lists. A states it in the user's own terms ("names that arrived in conversation, no scene"), traces the Yosemite list to its own earlier message, and writes the split. C attaches a record id to every entry but reframes the question as a mechanism, announces four species over a list of three before correcting, and ends by offering the write rather than making it. |
| 6 | The deliberate purchase | A | Marked: the $50 silver necklace for the sister. Both miss it. A answers with the plush rug, bought "last month", and excludes the chair with "I'm thinking of getting" and "still thinking about the fabric options". C answers with the Wishbone Chair, an unmade decision, and offers to record it as a real purchase. A's is a real purchase; C's is a fabricated one. |
| 7 | Game hours added up | A | Marked: 140, counting both runs of The Last of Us Part II as hours lived. A leads with 140 and decomposes it (ACO half the total, TLOU2 39 per cent), and states the 110 to 115 alternative as a conditional. C refuses it: "Not 140", because it treats the second run as the same content rather than more time. A's later audit re-scores to 110 to 115, which is a flaw in the arm, not in the answer it first gave. |
| 8 | Two connected days, one an ending | **Draw, both wrong** | Marked: 102 days, 14 February to 27 May. Neither arm produces 27 May. C's 10/14/15 February braid is real evidence, unused. |
| 9 | Winter date and spring meeting | **Draw, both wrong** | Marked: 14 February and 27 May, a loss and an adoption three months apart. C refuses the charge and frames it; A claims no spring anchor exists while the record holds one. |
| 10 | Places gone vs places sought | C | C's provenance split is the strongest single answer in the run, and it carries Disneyland, which A drops. |
| 11 | Goodbye, then Ava | **Draw, both wrong** | Marked: 102 days. C doubts the grandmother attribution, A closes the interval with a named assumption; neither finds 27 May, so neither answers the question. |
| 12 | Animals in front of me vs planned | C | C separates corpora and carries ids; A separates tenses. |
| 13 | Numbers on unfinished things | C | C names the "whose sentence is it in?" test as the instrument; A reaches the same four-way split under "real numbers, but not yours" without naming it. C's ids make the difference. Both arms carry the 110 to 115 total into this answer, which the key rejects on Q7; the row is decided on the classification, not on that figure. |
| 14 | Heaviest beats and blank stretches | **Draw, both wrong** | A fills a summer gap with a planned trip; C marks blanks honestly but rests its "three major events inside about twelve days" on an invented "~Feb 21" and a year set six months out. |
| 15 | Non-games, non-travel, non-nature area | A | Marked: mixology. A puts cocktails first and names the bar and the kitchen; C says "the domain is the kitchen" and buries cocktails inside it. |
| 16-17 | "What was my first query", "my 5th query" | A | A answers both verbatim from the message table, after its recompact. C also answers, with a hedge about how to count the framing turns. |

Row count: A six, C three, four unresolved.

---

## 5. Critical Failure Modes

### Bench A

- **Late standard flip.** 140 hours is decomposed correctly, then re-scored to 110 to 115 in the later audit, with both figures stated. Nothing is hidden, but the audit lands on the number the key rejects.
- **Uniqueness overclaim.** "That's the only real seasonal anchor in the record", contradicted by the same arm's own February, September and October timeline.
- **Category misfiling.** "Miami in April, wedding, credit card points, never booked" placed inside a summer blank stretch, which is then explained as planning.
- **Entity vagueness.** A theme park reduced to "another" one, with Disneyland missing from its own confirmed list.
- **Sequencing error.** Funeral planning described as following the burial.
- **Uncited retrieval.** One row number in seventeen replies, no source, ever.

### Bench C

- **Purchase fabrication.** The Wishbone Chair presented as the deliberate purchase and offered for the record as "a real purchase", when the user was still choosing fabric and had not bought it. C had already ruled that line unmade in Test 6.
- **Fabricated projection.** It prices every unplayed title in the backlog to an hour range the record does not carry, then sums them into a projected total of 181 to 321 hours of "intent", which it calls 1.6 to 2.8 times what the user has actually played. The four finished games each carry a record id; none of the eleven backlog ranges does, and one of the eleven titles, Gris, is not on the record's list at all. Two paragraphs later the same answer says those hours weigh nothing because none of it happened, which is the right reading and contradicts the comparison it just drew.
- **Interval error.** "The two peaks sit 260 days apart" where 14 February to 8 October is 236 days.
- **Invented date.** a "~Feb 21" second funeral, extrapolated from "next week"; flagged approximate, still not in the record.
- **Year drift.** The record's timeline laid out six months out, which the Q14 cluster then depends on.
- **Self-corrected miscount.** A heading announcing four species over a list of three; caught one turn later.

---

## 6. Operational Observations

From the two gateway logs for this window:

- Per-turn latency: A median 14.2 s, mean 14.1 s, max 27.6 s. C median 10.6 s, mean 10.6 s, max 19.8 s.
- Response volume: A 29,430 characters, median 2,012 per turn. C 35,444 characters, median 2,401. C wrote more here, the reverse of Tests 1 and 2, and A was still the tighter of the two per answer.
- One recompact launched at 21:53:28 in arm A's log; none in C's.
- Both arms answered all 17 turns.

A's recompact is the only mid-conversation rebuild observed in Tests 1 to 3, and it did not visibly cost A its thread. That is one observation, not a measurement of compression safety.

### Tokenomics

From arm A's per-call context dumps for this window and the tool lines in arm C's transcript:

- **A:** 49 API calls across 17 turns, median 55,830 input tokens per call, peak 100,313, 2,769,444 summed. System prompt median 20,872 characters; 31 tool schemas per call.
- **C:** 20 memory-tool lines across 17 turns, about 1.2 per turn. Token figures unavailable; no readable dumps exist for its home.

C wrote more than A here (35,444 characters against 29,430) while making fewer memory calls, which is the inverse of Tests 1 and 2 and is consistent with this being the run where C leaned on reasoning over retrieval. A's cost sits in API round-trips: roughly three calls per turn, each carrying a median 55k-token prompt.

---

## 7. Final Assessment

| Criterion | Winner | Margin |
|---|---|---|
| Accuracy | A | Clear - C asserts an unbought object as a purchase and offers to store it, invents a date, and prices a backlog the record never priced; A's defects are misfilings and a late standard flip it states openly |
| Continuity after compression | A | Narrow - the only arm that faced a rebuild, and it held |
| Retrieval thoroughness | C | Clear on provenance, wrong on the pairing - ids and corpus attribution versus none |
| Hedging quality | A | Narrow - A marks its limits and admits the store's limits; C hedges well and then fabricates |
| Noise and polish | A | Narrow |

**Verdict: A wins Test 3, six rows to three, four questions unanswered by both.** The run isolates provenance, and C is still the better provenance instrument: it names sources, attaches ids and marks foreign corpora where A cites nothing. It does not follow that C is the more accurate arm here. The question that matters most in this test, what did I actually do, is answered with a real purchase by A and an unmade decision by C, and C offers to write that decision into memory as fact.

The four unresolved rows are not a tie and not an absence. On Q8, Q9 and Q11 both arms did the same thing: each asserted that the spring date is not in the record at all. A put it as "there is no date for the Ava meeting anywhere in the record, and I can now say that with certainty", and added that every stored message carries the same ingestion timestamp. C searched for spring, March, April and May, reported nothing, and cited the session id that carries the Ava line without reading a date off it. Both therefore returned an answer to the question asked, and both answered it the same way. If the marked 27 May is right, that answer is a hard error for both arms rather than an absence of evidence, and the failure has a specific shape: neither arm checked the date on the session that holds the fact, where the id they both quoted is the only pointer needed. The marking cannot be checked against this store, so the row records both readings rather than choosing one.

One confound is disclosed with this result: the run's first message instructs both arms to use the memory tools ("gonna ask you a few questions. Strictly use your memory tools, sessions etc to arrive at an answer."). That is a hint, it applies equally to both arms, and it means this test measures how each arm uses retrieval once told to retrieve, not whether it retrieves unprompted. The unprompted evidence is Test 1, where no such instruction was given and both arms searched anyway.

---

## 8. Which Combination Is Best for Agentic Use

### The difference in this run

This run isolates provenance, and C separates sources while A separates claims, but only one of them keeps a claim inside what the record supports. A's answer to the purchase question is a thing the user did. C's is a thing the user was considering, written up as done on offer, in a run where C had already said in another conversation that the same sentence was an echo of intent and not a purchase.

**Best for agentic use in this run: Bench A (MEA + PostgreSQL).** An agent that can name where a fact came from but will commit an intention to memory as a completed act hands its user a record that contradicts reality, and every later turn inherits the error.

### Consistency with earlier runs

Tests 1 and 2 also went to A, on numbers and attribution. This run adds the axis those two did not isolate, provenance, and A still takes it because it kept its claims inside the record and C did not. Four rows the previous version of this report awarded to C were re-scored here on the questions and the logs; the remaining C wins are real and are recorded as such. Test 4, 5 and 6 are scored on their own criteria in their own reports, and `Cross_Test_Consistency_Report.md` reads all six together: the pattern is A, A, A, A, A, A.

## 9. Evidence

| Piece | File |
|---|---|
| Bench A chat log | [benchA_test3.txt](../evidence/chatlogs/test3/benchA_test3.txt) |
| Bench C chat log | [benchC_test3.txt](../evidence/chatlogs/test3/benchC_test3.txt) |
| Bench C Test 6 log, for the chair admission | [benchC_test6.txt](../evidence/chatlogs/test6/benchC_test6.txt) |
| Question key | [questions.txt](../questions/questions.txt) |
| Bench C UX dossier | [benchC_test3_ux_dossier.md](../evidence/dossiers/benchC_test3_ux_dossier.md) |
| Gateway log, both arms | [bench_a_gateway_oct18-21.log](../evidence/gateway/bench_a_gateway_oct18-21.log), [bench_c_gateway_oct18-21.log](../evidence/gateway/bench_c_gateway_oct18-21.log) |

The chat logs are the primary record: they carry every user turn, every agent reply and the gateway's tool banners. The dossiers collect the quoted exhibits by line number. Nothing in this report is asserted that is not visible in one of these files.
