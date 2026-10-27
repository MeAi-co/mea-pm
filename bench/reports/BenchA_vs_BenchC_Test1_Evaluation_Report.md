# Test 1 Evaluation Report  
**Bench A:** stock Hermes + MEA plugins + PostgreSQL + embeddings  
**Bench C:** stock Hermes + Mnemosyne + embeddings  
**Date of Test:** 18 October 2026, 16:53–17:03  
**Model:** deepseek-v4.1-flash:cloud (identical for both)  
**Test Focus:** Vague multi-source recall under time pressure — trips vs wildlife, finished vs unfinished work, deliberate purchase, game hours, linked days, and a synthesised timeline  
**Session shape:** live user-and-assistant conversation over Telegram, one conversation per arm, 14 user turns each

**Provenance.** Written from the retained chatlogs after the run, under the criteria now used for Tests 4, 5 and 6. The run was originally scored on a different four-axis matrix (accuracy, query relevance, uncertainty handling, tone); that grade is not carried forward and no number from it appears in this report. Both arms received an identical question stream, the same model, and the same seeded memory store.

**Compression scope.** This run sits in the pre-compaction window: no compaction event fires between 16:53 and 17:03 in either gateway log. The continuity axis here therefore measures referent drift across turns, not recovery from a context rebuild. Test 1 cannot speak to post-compaction continuity.

---

## 1. Executive Summary

Under the current criteria, **Bench A — stock Hermes + MEA plugins + PostgreSQL + embeddings wins Test 1 by a clear margin, roughly one tier, and it is the combination to run for agentic work.**

The decisive question was arithmetic over a retrieved ledger: how many hours of finished games, counting each playthrough. A answered 140 hours across four titles, decomposing it as 70 + 55 + 10 + 5 with The Last of Us Part 2 counted as two distinct runs. C answered 65 hours across "three playthroughs, two distinct titles", stated that Assassin's Creed Odyssey carried no hours figure, filed Hyper Light Drifter as never played, and listed Mass Effect and Dragon Age, neither of which the user ever mentioned.

That is not a difference of phrasing. One arm retrieved the numbers and added them; the other retrieved a subset, declared the largest item unquantified, and produced a total that omitted it. Everything else in the run follows from that: A's answers are longer and messier but anchored to entry IDs, while C's are cleaner and better written and rest on a ledger that does not add up.

---

## 2. Evaluation Criteria (Applied)

1. **Accuracy** — claims grounded in the store. Non-negotiable.
2. **Continuity after compression** — referents survive a rebuild. In this run, referents survive across turns.
3. **Retrieval thoroughness** — keep searching until the claim is verified, not until a story can be told.
4. **Hedging quality** — hedging that marks real doubt is good; hedging that disguises thin evidence or a bad total is not.
5. **Noise and polish** — secondary. Noise can be filtered; a wrong total cannot.
6. **Tokenomics** — input tokens per call, API round-trips per turn, and memory-payload volume. Recorded here with real measurements; it explains cost, it does not decide the verdict.

Token, cache and latency figures are operational observation in §6, never the verdict.

Note on continuity: this axis is only partially exercised here. Compaction is the harder case and it is absent from this window, so continuity scores in Tests 1–3 rest on turn-to-turn referent drift. A run with no rebuild cannot show that an arm survives one.

---

## 3. Core Behavioral Contrast

### Bench C — confident summary, thin ledger

C answers in tidy structures with explicit caveats, and the caveats are real: it does surface that a February sequence could be read as contradictory, and it marks its own uncertainty. The problem is what the tidiness sits on. It reports 65 hours, denies that Odyssey has an hours figure, and places a game the user described as finished into the unplayed pile. It also adds two titles that appear nowhere in the user's own messages.

Its hedges often behave as surplus rather than caution: it refuses a winter-holiday mapping at 16:58 and then makes the correct mapping five lines later.

### Bench A (MEA + PostgreSQL) — message-level retrieval, verbose audit trail

A works at the level of individual messages and entry IDs, and says so: it cites the two messages in one session that disagree, notes that "two $50s in my notes and only one of them is real", and runs one repair thread across six turns, closing a promise it made earlier in the session.

The cost is visible. A spams identifiers, offers repeated repair passes, and its formatting is worse than C's.

It over-infers in one place: it reasons about the hummingbird as a bird in a "Southern California yard", a location the record does not establish, and the species argument hangs off that premise. That is a recoverable over-inference, not a fabricated fact, and A marks its own uncertainty in the same breath ("either you got extremely lucky, or the ID drifted"). Two charges an earlier reading made against this run do not survive the transcript. Gris is not pulled into the backlog: it appears once, in the "maybe someday" pile, named as a three-hour game to contrast with the sixty-to-hundred-hour commitments beside it. And the interval figures are not drift: "5 to 18 weeks" is keyed to a spring meeting, "2 to 4 months" to a weekend meeting, "1 to 4 months" to the Ava reading, and A states that the readings cannot both be right.

The asymmetry that decides the run: A's over-inferences are local, disclosed and correctable inside the conversation; C's error is the headline number.

---

## 4. Question-by-Question Findings

| # | Prompt theme | Better | Observation |
|---|---|---|---|
| 1 | Opening turn | — | Greeting only. |
| 2 | Holiday trips vs wildlife | A | A separates the completed trip from the planning-only one; both arms are clean here, A tighter. |
| 3 | Finishing hard things vs small gestures | A | A uses the two TLOU2 runs, the 5K and the memory book; C is thinner on the finished side. |
| 4 | Beings in the wild vs outside the window | A (narrow) | A keeps sightings separate from target lists; C also clean. |
| 5 | The deliberate non-digital purchase | A | A lands on the necklace and keeps the two $50 entries apart; C leans to the orchid and a Hydro Flask. |
| 6 | Finished game hours | **A, decisively** | A: "Finished — 4 titles, 140 hours" (70 + 55 + 10 + 5). C: "65 hours across three playthroughs, two distinct titles", plus "you never gave an hours figure, so it doesn't enter the sum". |
| 7 | Two connected days | A | A reads the sequence and leaves the relationship open; C asserts "those can't all be true of one week" against a sequence that is coherent. |
| 8 | Winter holiday and spring meeting | A | C refuses the mapping, then makes it. |
| 9 | Pattern across places | A | A's synthesis is tighter. |
| 10 | Interval between goodbye and meeting | A | A gives a dated answer with a named assumption; C refuses. |
| 11 | Animals, repeat of 4 | A | Both clean; neither notes the repeat. |
| 12 | Numbers on unfinished things | A | A separates user-owned numbers from assistant-generated estimates. |
| 13 | Emotional timeline | A | A's dated spine is more coherent. |
| 14 | High-value area that is not games/travel/nature | A / tie | Both reach cooking and hosting. |

Q11 is a near-verbatim repeat of Q4. Neither arm noticed, which is a harness observation rather than an arm failure.

---

## 5. Critical Failure Modes

### Bench C

- **Wrong headline total.** 65 hours against 140, with the omitted item declared unquantified.
- **Invented entities.** Mass Effect and Dragon Age appear once each in C's transcript and zero times in the user's messages.
- **Misfiled completion.** Hyper Light Drifter placed among recommendations rather than finished titles.
- **Over-absolute denial.** "There's no girlfriend, no partner, no daughter anywhere in your record", against an arm that retrieved diapers evidence from the same store. Either C missed the recall or A fabricated it; the transcripts cannot settle which, and this report does not.
- **False contradiction.** Reading a four-day and a one-day gap as mutually impossible.
- **Self-retracted metric.** It reports recorded hours in the maybe pile as zero, then withdraws the zero as missing data.

### Bench A (recoverable, no hard errors)

- "Southern California yard" is an unstated regional premise carrying a species argument, disclosed as uncertain in the same turn.

Two further items an earlier reading listed here, Gris pulled into the backlog and a three-phrasing interval drift, do not survive the transcript and are removed. "Six of those are 60-to-100-hour commitments" is a band applied to a pile the report cannot count from the transcript, so it is neither confirmed nor charged.

### Unconfirmed

A prior verdict of this run attributed C's 65-hour answer to two corrupted store rows (100 hours and 40 hours wrongly keyed to Odyssey). That mechanism is plausible and C does later store a "50–100 hours" range from recommendation prose, but the duplicate rows themselves are not visible in the transcript. Recorded here as unconfirmed, not as fact.

One disagreement the chatlogs cannot resolve: A dates the archive as stamped in the same 13 seconds on 18 October; C dates it 2026-10-16 15:32.

---

## 6. Operational Observations

Measured from the two gateway logs for this window (observation, not scoring):

- Per-turn latency: A median 13.6 s, mean 13.3 s, max 21.1 s. C median 16.4 s, mean 15.7 s, max 25.0 s.
- Response volume: A 28,625 characters across the window, median 1,986 per turn. C 25,966 characters, median 1,936.
- No compaction or summarisation events fire in either log inside the window.
- Both arms answered all 14 turns; no turn was dropped or retried.

A was slightly faster and slightly longer per answer, but the margin is small and inside run-to-run variance. It is not the reason A won.

### Tokenomics

Measured from arm A's per-call context dumps for this window, and from the tool lines in arm C's transcript:

- **A:** 43 API calls across 14 turns, median 63,942 input tokens per call, peak 100,911, 2,516,533 tokens summed over the window. System prompt holding the memory injection and instructions: 21,408 characters median. 31 tool schemas offered on every call.
- **C:** 42 memory-tool lines across 14 turns, about 3.0 per turn, several turns issuing six or seven recalls before answering.

C's context dumps and agent log sit under a home directory this account cannot read, so its token figures are not measured here; only its call counts are. What is measurable in this window already points the way: C reaches the same store with roughly three recall calls per user turn, and in Test 6, where payload sizes are recorded for both arms, each of those calls returns a median 12,557 characters against A's 3,496.

Test 1 therefore cannot separate "C retrieves more" from "C is fed more". Both arms saw the same seeded corpus, but not the same context budget.

---

## 7. Final Assessment

| Criterion | Winner | Margin |
|---|---|---|
| Accuracy | A | Decisive |
| Continuity | A | Narrow (referent drift only) |
| Retrieval thoroughness | A | Narrow |
| Hedging quality | A | Narrow |
| Noise and polish | C | Narrow |

**Verdict: A wins Test 1, clear margin.** A holds the only quantitative answer that mattered and invents no entities; C is the better writer with the wrong ledger.

Two limits on that verdict. First, continuity is only partly tested, since nothing was compacted in this window. Second, this is a single scored pass; the accuracy failures are hard facts, the axis margins are judgment.

---

## 8. Which Combination Is Best for Agentic Use

### The difference in this run

A closed the numeric question with an open ledger: 70 + 55 + 10 + 5, The Last of Us Part 2 counted as two playthroughs, 140 hours across four titles. C closed it with three playthroughs and two distinct titles at 65 hours, declared the largest item unquantified, and listed Mass Effect and Dragon Age, which appear nowhere in the store. A's extra retrieval is visible in its own output. C's shortfall is not visible in its.

**Best for agentic use in this run: Bench A (MEA + PostgreSQL).** An orchestrator acts on the number it is handed, and a 54% shortfall that nothing flags is the one failure class it cannot catch from outside.

### Consistency with earlier runs

This is the baseline of the series. There is no earlier run to compare against, and nothing here is averaged into a later total. The four reports after this one carry it forward as the first entry of the series: when a numeric question is answered from a ledger versus a summary, the ledger wins, and the later runs either repeat that shape or name the axis where it does not apply.

## 9. Evidence

| Piece | File |
|---|---|
| Bench A chat log | [benchA_test1.txt](../evidence/chatlogs/test1/benchA_test1.txt) |
| Bench C chat log | [benchC_test1.txt](../evidence/chatlogs/test1/benchC_test1.txt) |
| Bench C UX dossier | [benchC_test1_ux_dossier.md](../evidence/dossiers/benchC_test1_ux_dossier.md) |
| Gateway log, both arms | [bench_a_gateway_oct18-21.log](../evidence/gateway/bench_a_gateway_oct18-21.log), [bench_c_gateway_oct18-21.log](../evidence/gateway/bench_c_gateway_oct18-21.log) |

The chat logs are the primary record: they carry every user turn, every agent reply and the gateway's tool banners. The dossiers collect the quoted exhibits by line number. Nothing in this report is asserted that is not visible in one of these files.
