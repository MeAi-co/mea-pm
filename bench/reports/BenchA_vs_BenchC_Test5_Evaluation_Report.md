# Test 5 Evaluation Report  
**Bench A:** stock Hermes + MEA plugins + PostgreSQL + embeddings  
**Bench C:** stock Hermes + Mnemosyne + embeddings  
**Date of Test:** 19 October 2026  
**Model:** deepseek-v4.1-flash:cloud (identical for both)  
**Test Focus:** Vague multi-source domain identification, trip bleeding, deliberate purchase, games hours aggregation, temporal connection, common-thread synthesis, and related multi-hop questions

---

## 1. Executive Summary

Under the production-oriented evaluation criteria established across these tests, **Bench A (MEA + PostgreSQL) is the clear winner** on Test 5.

Bench C again demonstrated its characteristic pattern of shallow retrieval followed by narrative framing. On the opening question it invented psychological insight that was not present in the data, then had to walk it back when challenged. Subsequent answers frequently required user correction before the agent performed adequate search. This produces low-trust responses and limited real-world value.

Bench A retrieved more thoroughly from the outset, correctly identified the houseplant / weeks-of-care domain after the clarifying constraint, separated lived vs planned trips with clear evidence, and maintained higher overall fidelity to the store. Its answers were longer, but the extra length was largely spent on additional retrieval and justification rather than fabrication.

**The difference:** A kept retrieving. C made no tool call at all, produced a denial, and answered fully three seconds after being challenged.

---

## 2. Evaluation Criteria (Applied)

Priorities used for scoring:

1. **Accuracy** — Claims must be grounded in data actually present in the store. Non-negotiable.
2. **Continuity after compression** — Ability to retain clear referents after context compaction.
3. **Retrieval thoroughness** — Continue searching until the claim is verified, rather than stopping once a coherent story can be told.
4. **Hedging quality** — Unwanted or mid-answer hedging that signals thin evidence is a negative, especially when paired with inaccuracy.
5. **Noise / unwanted reasoning** — Secondary. Noise can be filtered; inaccuracy and broken continuity cannot.
6. Narrative polish — Tertiary.

Unacceptable combination: unwanted hedging + inaccuracy (the pattern that produces bad UX and low real-world value).

---

## 3. Core Behavioral Contrast on Test 5

### Bench C – “Retrieve just enough to frame a story”
- Opening answer invented a full psychological framing (“ritual, ordinary mornings, nobody watching, no completion bar”) around coffee/baking that was not in the data.
- When challenged (“did you just make that up?”), admitted the invention and retreated.
- On “weeks of care” it then guessed the succulent cutting — closer, but still required the user to drive the search.
- On trip memories it initially claimed it did not know them (“I don’t know. Nothing I have names them”), then recovered only after the user said “dont know? thought you had memory?”.
- Pattern throughout: 1–2 recalls → narrative synthesis → hedging or correction when the thinness becomes visible.

### Bench A (MEA + PostgreSQL) – “Keep retrieving until verified”
- Immediately searched on the opening domain question, considered coffee/baking, then continued searching when told “weeks of care” and correctly landed on the houseplant / succulent / orchid cluster.
- On trip bleeding: multiple retrievals, clear separation of Yellowstone (lived) vs Yosemite + JMT (planned), with explicit evidence criteria (companions, past tense, specific animals).
- On the deliberate purchase: retrieved the Wishbone Chair research thread and correctly noted the absence of a confirmed purchase.
- Consistently issued multiple targeted jpm / sessions calls and continued until the specific constraint was satisfied.

---

## 4. Question-by-Question Findings

| Question Theme                        | Bench A                                      | Bench C                                              | Winner |
|---------------------------------------|----------------------------------------------|------------------------------------------------------|--------|
| Domain (time/money/care, not games/travel/wildlife) | Searched → coffee → corrected to houseplants after “weeks of care” | Invented ritual framing → admitted fabrication → later guessed succulent | **A**  |
| Trip memories bleeding (done vs planned) | Clear separation: Yellowstone done; Yosemite + JMT planned | Initially claimed ignorance; recovered only after challenge | **A**  |
| Deliberate purchase (not game/ticket/replacement) | Retrieved Wishbone Chair research; noted no confirmed buy | Retrieved blazer / chair candidates; still mixed research with purchase | **A** (narrow) |
| Games hours vs “maybe someday”        | Grounded arithmetic, clear finished vs backlog | Correctly noted TLOU2 ambiguity; more narrative framing | Tie / slight A |
| Two connected days (ending / beginning) | Retrieved Feb 14 funeral + May 27 Ava; computed interval | Same core dates; more interpretive overlay             | Tie    |
| Common thread in places / experiences | Structured threads (small party, countable target, early arrival) | Similar synthesis, slightly more polished              | Tie / slight C |
| Overall data fidelity                 | Higher                                       | Lower (more invention and recovery cycles)           | **A**  |

---

## 5. Critical Failure Modes Observed

### Bench C (Unacceptable for agentic use)
- **Invention on first pass**: Fabricated “ritual / ordinary mornings” insight that had no basis in the store.
- **Shallow retrieval → forced narrative → mid-answer hedging**: Classic pattern. Required user challenge before performing adequate search on multiple questions.
- **Initial denial of memory content**: “I don’t know. Nothing I have names them” on trip memories that were present.
- Hard compression occurred mid-session (47 → 17 messages); subsequent answers showed the same referential softening seen in Test 6.
- Resulting UX: user is forced to probe, correct, and re-ask — low trust, low efficiency, low real-world value.

### Bench A (Recoverable)
- Over-retrieval and length (noise).
- On the purchase question still elevated research (Wishbone Chair) above the confirmed $50 necklace (same gap seen in Test 6).
- Micro-level tool noise, but no invention of non-existent facts and no “data not found” when the data existed.

---

## 6. Operational Observations

**Bench A**
- Multiple sequential, low-latency jpm calls per complex turn.
- Adaptive retrieval (continued searching after the first plausible domain).
- Maintained ability to answer precisely even as context grew.

**Bench C**
- Fewer tool calls, earlier synthesis.
- Visible recovery cycles driven by user pushback rather than internal verification.
- Compression event mid-test with subsequent softening of precision.

---

## 7. Final Assessment

Test 5 reproduces the same architectural and behavioral split observed in Test 6:

- Bench C optimizes for rapid narrative closure. When the first fragments are insufficient it invents or hedges rather than continuing to retrieve. This produces answers that can sound insightful but rest on incomplete or fabricated ground — unacceptable for data-based or action-oriented work.
- Bench A optimizes for verification against the store. It is wordier and sometimes over-retrieves, but it is substantially more accurate, requires less user correction, and maintains better continuity.

**Under the agreed criteria (accuracy first, continuity after compression, retrieval thoroughness, rejection of unwanted hedging + inaccuracy):**

**The combination to run for agentic work on Test 5 is Bench A — stock Hermes + MEA plugins + PostgreSQL + embeddings.**

Bench C’s pattern of invent-then-retreat remains a disqualifying flaw for any production agent expected to deliver reliable, data-grounded answers or to support follow-up actions that depend on correct referents.

---

## 8. Which Combination Is Best for Agentic Use

### The difference in this run

C made no tool call at all at 10:22 and answered "I don't know. Nothing I have names them." After "dont know? thought you had memory?" a single recall returned 25,237 characters three seconds later. A had been retrieving since the first turn, and its longer answers are retrieval rather than padding.

**Best for agentic use in this run: Bench A (MEA + PostgreSQL).** Unattended, C's first answer is a silent empty result. The recovery arrived only after a challenge, and an orchestrator does not supply challenges.

### Consistency with earlier runs

This is the sequence Test 4 recorded, in a shorter window: denial of existence, then competence the moment a human pushes. Two consecutive runs, same order of events. Set against Tests 1 to 3, where both arms searched unprompted, what differs is the trigger for the plugin arm's search, not its ability to search once triggered.

## 9. Evidence

| Piece | File |
|---|---|
| Bench A chat log | [benchA_test5.txt](../evidence/chatlogs/test5/benchA_test5.txt) |
| Bench C chat log | [benchC_test5.txt](../evidence/chatlogs/test5/benchC_test5.txt) |
| Bench C UX dossier | [benchC_test5_ux_dossier.md](../evidence/dossiers/benchC_test5_ux_dossier.md) |
| Gateway log, both arms | [bench_a_gateway_oct18-21.log](../evidence/gateway/bench_a_gateway_oct18-21.log), [bench_c_gateway_oct18-21.log](../evidence/gateway/bench_c_gateway_oct18-21.log) |

The chat logs are the primary record: they carry every user turn, every agent reply and the gateway's tool banners. The dossiers collect the quoted exhibits by line number. Nothing in this report is asserted that is not visible in one of these files.
