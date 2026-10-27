# Test 2 Evaluation Report  
**Bench A:** stock Hermes + MEA plugins + PostgreSQL + embeddings  
**Bench C:** stock Hermes + Mnemosyne + embeddings  
**Date of Test:** 18 October 2026, 18:57–19:03  
**Model:** deepseek-v4.1-flash:cloud (identical for both)  
**Test Focus:** Repeat of the Test 1 question set for stability, with closer attention to purchase attribution, dated intervals, and provenance of numbers  
**Session shape:** live user-and-assistant conversation over Telegram, one conversation per arm, 11 substantive user messages / 13 question units

**Provenance.** Written from the retained chatlogs after the run, under the criteria now used for Tests 4, 5 and 6. The run was originally scored on a four-axis matrix (accuracy, query relevance, uncertainty handling, tone) and that grade is not carried forward; where the original verdict's wording is quoted it is labelled as such. Both arms received an identical question stream.

**Compression scope.** Pre-compaction window: no compaction event fires between 18:57 and 19:03 in either gateway log. Continuity here measures referent drift across turns only.

---

## 1. Executive Summary

**Bench A — stock Hermes + MEA plugins + PostgreSQL + embeddings wins Test 2, but by about half the margin the original verdict claimed. It is the combination to run for agentic work, narrowly.**

A again produced the correct game ledger, 140 hours across four titles with The Last of Us Part 2 counted as two runs, and it carried an open repair loop across three turns using its own entry IDs. C again lost the ledger, reporting Odyssey's hours as never logged and totalling 135 after self-correcting, five hours short because it still filed Hyper Light Drifter as unplayed.

Three findings differ from the original reading of this run, and they narrow the gap:

1. **A did not identify the deliberate purchase.** The original verdict credited A with the $50 necklace. In the transcript A refuses to name the item and guesses the orchid, explicitly placing the necklace among gifts for other people. C is the arm that ties $50 to the sister's necklace, though it answers the question with a Hydro Flask.
2. **Retrieval thoroughness belongs to C.** C surfaces a fourth trip, Bhutan species, sparrow calls and Half Dome figures that A never reaches. A is more precise where it does search, catching the bulk-import timestamp, but precision is not thoroughness.
3. **A leaks harness boilerplate into its answers** and produces a mangled code-run fragment, which the original scoring did not penalise.

Net: A still wins on the two criteria that decide runs, accuracy and continuity. It wins both narrowly rather than decisively.

---

## 2. Evaluation Criteria (Applied)

1. **Accuracy** — grounded claims; a total that omits an item is wrong, not approximate.
2. **Continuity after compression** — referents and open loops survive; in this window, survive across turns.
3. **Retrieval thoroughness** — breadth of verified recall, not just the first sufficient answer.
4. **Hedging quality** — doubt that is marked and earned, versus refusal used as a substitute for retrieval.
5. **Noise and polish** — leaks, boilerplate, malformed output.
6. **Tokenomics** — input tokens per call, API round-trips per turn, and memory-payload volume. Recorded with real measurements; it explains cost, it does not decide the verdict.

---

## 3. Core Behavioral Contrast

### Bench C — broader retrieval, borrowed arithmetic

C reaches material A never finds: a four-day family road trip described as roughly 200 miles each way, named Bhutan endemics, sparrow calls, Half Dome figures. It also separates provenance better than A on some turns, distinguishing authored recommendations from user statements.

Its arithmetic is the recurring weakness. Odyssey's hours are declared never logged, the total is corrected mid-run to 135, and that correction still excludes a finished game. It also reports "nine-odd titles" after listing ten, and claims eight months of emotional blankness that its own Yellowstone entry contradicts.

### Bench A (MEA + PostgreSQL) — precise ledger, thin coverage, leaky output

A is auditable where it works: its percentages check, it tracks a stale duplicate entry (216) and an open loop (195) across turns, and it catches a bulk-import artefact, noting that legacy messages are stamped within the same minute rather than reflecting real conversation times.

It also slips, but not where an earlier scoring put it. "Strip out the replay and TLOU2 is 30 hours, putting you at 110 total" is 115 by its own subtraction, five hours low, inside a hypothetical that does not touch the 140 answer. What it does not do is invent a duplicate. At Q5 it names the two completions outright, "30h on hard plus 25h on normal = 55h, but that's two separate completions of the same game, not one long one", and later it warns that counting the 30-hour run a second time would put one playthrough at 60 hours and the total at 170, which is the opposite of double counting. The duplicate it does flag, entry 216 as a stale copy of 201 with pre-correction wording, is a database housekeeping note about a superseded row. It is not a claim about how many times the user played. It emits bot boilerplate mid-answer and a broken code fragment.

---

## 4. Question-by-Question Findings

| # | Prompt theme | Better | Observation |
|---|---|---|---|
| 1 | Holiday vs wildlife overlap | A | A separates the completed trip from the planning-only one; C also clean this run. |
| 2 | Hard things + small gestures | A | A includes both TLOU2 runs, the 5K and the memory book; C thinner on the finished side. |
| 3 | Beings wild vs window | Tie | Both separate sightings from target lists. |
| 4 | Deliberate non-digital purchase | **C, on attribution** | A refuses and guesses the orchid; C ties $50 to the sister's necklace but answers "The Hydro Flask". Neither names the necklace as the purchase. |
| 5 | Games finished vs maybe-someday | A | A: 140 hours across four titles. C: Odyssey hours never logged; corrected later to 135. |
| 6 | Lost someone + met her | A | A maps "her" and gives a usable framing; C refuses harder. |
| 7 | Winter holiday + spring meeting | A | A accepts the seasonal framing; C refuses the premise. |
| 8 | Pattern connecting places | A | Both synthesise; A tighter. |
| 9 | Time between goodbye and "my girl" | A (narrow) | A flags the referent ambiguity and offers both readings; C refuses, then gives a bounded band. |
| 10 | Animals, repeat | Tie | Both clean. |
| 11 | Numbers on unfinished things | A | A separates user-owned numbers from assistant estimates. |
| 12 | Emotional timeline | A | A's dated spine is more coherent. |
| 13 | High-value area, non-gaming/travel/nature | Tie / slight C | Both reach cooking and hosting; C's framing cleaner. |

---

## 5. Critical Failure Modes

### Bench C

- Odyssey "completed — hours never logged", against a store that holds the figure.
- Total corrected to 135, still five hours short: Hyper Light Drifter listed as "8–12h" and never played.
- "Nine-odd titles" after enumerating ten.
- "Eight months of blank… not one emotionally weighted event", contradicted by its own Yellowstone "last month" entry.
- Names entities it cannot surface in the store (Himalayan pink salt block, bedroom area rug) while leaving them unsupported.

### Bench A (recoverable, no hard errors)

- Purchase question refused, then offered as a guess (orchid). The refusal is explicit and the guess is marked as one, so it is a miss, not an asserted fabrication.
- Arithmetic slip: 110 where its own figures give 115, inside a hypothetical.
- "Bhutan — never visited, no species ever named", which contradicts C's named endemics; at most one arm is right and the transcripts cannot arbitrate.
- Boilerplate leak at 18:57 and a malformed code-run fragment.

The earlier scoring of this run counted one more item against A, that it "claims the user said the 30-hour run twice" and had therefore invented a duplicate. That reading does not survive the transcript. The two completions are stated in the record, A reports both, and the duplicate A raises is a stale row. Scored as a hard error it was wrong, and it is removed here. Hard error means a factual claim the record contradicts. A guess, a hedge, an arithmetic slip inside a hypothetical and a housekeeping note do not qualify.

---

## 6. Operational Observations

From the two gateway logs for this window:

- Per-turn latency: A median 15.8 s, mean 16.6 s, max 29.5 s. C median 15.9 s, mean 16.2 s, max 26.3 s. Effectively a tie.
- Response volume: A 25,856 characters, median 2,071 per turn. C 20,414 characters, median 1,664.
- No compaction events in either log inside the window.
- Both arms answered every turn.

The original verdict of this run also recorded API-call and tool-payload counts from a captured late window: A averaged about two API calls per question against C's 3.4, and returned roughly a quarter of C's tool-result volume. Those figures are not re-derived here and are not part of the verdict.

### Tokenomics

From arm A's per-call context dumps for this window and the tool lines in arm C's transcript:

- **A:** 25 API calls across 11 substantive turns, median 48,868 input tokens per call, peak 74,982, 1,138,999 summed. System prompt median 21,275 characters; 31 tool schemas per call.
- **C:** 23 memory-tool lines across 12 user turns, about 1.9 per turn. Token figures unavailable: its home directory is not readable from this account and it kept no dumps for this window.

The comparison is therefore asymmetric, and this report says so rather than implying equal cost. Across the two windows where both arms' call patterns are visible, C issues more memory calls per turn and each call returns materially more text (Test 6 records a median 12,557 characters per C recall against 3,496 per A call). A pays for its precision in API round-trips, C pays in context volume.

---

## 7. Final Assessment

| Criterion | Winner | Margin |
|---|---|---|
| Accuracy | A | ~0.7 (zero hard errors this run; the removed duplicate charge was the only one scored) |
| Continuity | A | ~0.4 |
| Retrieval thoroughness | **C** | ~0.3 |
| Hedging quality | A | ~0.2 |
| Noise and polish | **C** | ~0.4 |

**Verdict: A wins Test 2 by roughly half a tier.** It holds the ledger and the record-level continuity; C retrieves more widely and writes more cleanly but cannot add up what it retrieves. The correction from the original reading is that the gap is narrower than first scored, and that the purchase question is a shared miss rather than an A win.

---

## 8. Which Combination Is Best for Agentic Use

### The difference in this run

Same question set as Test 1, later the same evening. A refused the necklace question, searched, refused again, and only then guessed the orchid; its refusal names what it searched and what it could not bind. C reached material A never found, a four-day family road trip described as roughly 200 miles each way, and still bound the $50 to the sister's necklace on a reading the store does not confirm.

**Best for agentic use in this run: Bench A (MEA + PostgreSQL), narrowly.** Half a tier, not a tier. What an unattended caller needs is an arm that says it cannot bind a fact before it invents the binding, and that is the arm that did.

### Consistency with earlier runs

Test 1 concluded that A closes numeric questions off its own retrieval while C closes them off a summary. This run repeats the shape on a different axis: A's answer moves where the record moves, C's answer is equally confident in both runs and supported in one. Two runs, two methods, same asymmetry. The correction this run adds is to the original verdict, which claimed a wider gap; the gap is half a tier and the purchase question is a shared miss.

## 9. Evidence

| Piece | File |
|---|---|
| Bench A chat log | [benchA_test2.txt](../evidence/chatlogs/test2/benchA_test2.txt) |
| Bench C chat log | [benchC_test2.txt](../evidence/chatlogs/test2/benchC_test2.txt) |
| Bench C UX dossier | [benchC_test2_ux_dossier.md](../evidence/dossiers/benchC_test2_ux_dossier.md) |
| Gateway log, both arms | [bench_a_gateway_oct18-21.log](../evidence/gateway/bench_a_gateway_oct18-21.log), [bench_c_gateway_oct18-21.log](../evidence/gateway/bench_c_gateway_oct18-21.log) |

The chat logs are the primary record: they carry every user turn, every agent reply and the gateway's tool banners. The dossiers collect the quoted exhibits by line number. Nothing in this report is asserted that is not visible in one of these files.
