# Scoring Rubric — derived from the owner's evaluation directions
**Source:** `Grok_verdict_chats.txt` lines 67–125 (the owner's own words)
**Written:** 2026-10-19
**Status:** This is the scoring standard. Grok's 7.5/9.0 verdict is NOT the standard.

---

## 1. Why the existing question set is insufficient

the owner, verbatim (line 67):

> "trying to bench agent harness.. but these questions are direct factual based retrievals. I need some thing more harder and vague that requires them to connect dots from multiple sources and reason."

The Tier 1–5 set (Q1–Q17) is **lookup**. Each question names its key entity or date, and the answer lives in one or two rows. An arm that can grep scores well. That measures retrieval plumbing, not memory quality.

The replacement set must force:

- joining facts that never co-occur in one session
- date math / relative ordering **without explicit dates**
- filtering `played / finished / only recommended / only planned`
- resisting the urge to glue nearby mentions together
- producing a synthesized answer rather than a retrieved string

---

## 2. The four scoring axes (the owner's, verbatim line 114)

> "You can score them on whether the agent (a) retrieves the right atomic facts, (b) joins them correctly, (c) avoids the traps, and (d) states uncertainty when the memory is genuinely ambiguous"

| Axis | What it measures | Failure looks like |
|---|---|---|
| **(a) Atomic retrieval** | Did it pull the correct underlying facts? | Misses a row that exists; pulls a stale duplicate |
| **(b) Correct join** | Did it connect them the right way? | Right facts, wrong relationship; conflates two events |
| **(c) Trap avoidance** | Did it resist the planted distractor? | Assigns hours to an unplayed title; merges two Disneyland contexts |
| **(d) Uncertainty** | Did it flag genuine ambiguity? | Confident answer where the record is two-valued |

**Scoring is per-axis, not a single number.** An arm can be 4/4 on (a) and 0/4 on (d) — that is the profile that matters, not the average.

---

## 3. Question design constraints (the owner, line 114)

> "but make it more conversational that addresses 2-3 weighted points and doesnt land like a question"

Every prompt must satisfy all five:

1. **Conversational register** — reads as an offhand reflection, not a quiz item
2. **2–3 weighted points** — multiple facts must be pulled, not one
3. **Does not land like a question** — no interrogative frame
4. **No named entities or dates** — "that little girl", not "Ava"; "the day I lost someone", not "Feb 14"
5. **Forces synthesis** — the answer cannot be a retrieved string

the owner's six required categories (lines 68–104):

- **Inference & synthesis** — connect dots the user never stated
- **Temporal & relative reasoning** — no dates given
- **Aggregation + filtering + exclusion** — completed vs considered
- **Multi-session joins requiring disambiguation**
- **Adversarial / distractor-heavy**
- **Open-ended synthesis** — propose a coherent picture

---

## 4. Where Grok's rubric diverges from the owner's

Grok scored on **faithfulness to a gold list**. That is not one of the owner's four axes.

| Grok's criterion | the owner's axis | Conflict |
|---|---|---|
| "inventing several that were never in the gold set" | (a) atomic retrieval | **Direct conflict.** If the title IS in the seed, retrieving it is axis-(a) success. Grok scored it as fabrication because his gold list was short. |
| "unnecessary AAA/indie split" | none | Not a scored axis. Style, not memory quality. |
| "over-confident tone" | (d) uncertainty | Valid — but Grok applied it to A only, while C led with 140 as its headline too. |
| "tighter and closer to the actual mentioned titles" | (a) | Valid only if the gold is complete. It is not (6 of 13). |

**Consequence:** under the owner's rubric, A's 11-title list is axis-(a) **correct** for 10 of 11 entries. The single real defect is Dragon Age (comparison question, id 6489) in place of RDR2 (stated intent, id 6495). That is one wrong slot, not "hallucinated padding."

---

## 5. The scoring procedure

For each prompt:

1. **Build the gold from the seed, not from a prior verdict.** Query the message store for every row that bears on the prompt. Record ids.
2. **Score (a)** — count correct atomic facts retrieved / total in gold.
3. **Score (b)** — is the relationship between them right? Binary per join.
4. **Score (c)** — did it take any planted trap? Binary per trap.
5. **Score (d)** — where the record is genuinely two-valued, did it say so? Binary per ambiguity.
6. **Report the four axes separately.** No single composite score.

**Hard rule:** never score an answer wrong until the seed has been queried for the underlying fact. An answer that looks like a double-count or a contradiction is frequently the agent correctly reporting a genuinely two-valued fact. (This exact error was made twice in this bench — the TLOU2 hours and the "London" entity.)

---

## 6. What "accuracy" means here

the owner, line 6 of the standing criteria:

> "Accuracy - At the end of the day, accuracy is all that matters to the USER. The retrieval stats is efficiency, but accuracy is Money! Financial apps cannot afford fabrication. Car diagnosis cannot afford fabrication... so Data is king"

So the ranking order is:

1. **Does not fabricate** — highest weight. A wrong confident answer is the only disqualifying failure.
2. **Answers the question asked** — relevance to the user's actual query.
3. **Confident, not hedging** — a correct answer buried in caveats is a partial failure.
4. **Efficiency** — tokens, payload, context. Real, but secondary. Never trades against 1–3.

---

## 7. Applied to the two answers in the thread

Prompt: *"I've sunk a lot of hours into games I actually finished, but there are a few titles that only ever stayed in the 'maybe someday' pile..."*

| Axis | A (MEA_JPM) | C (Mnemo) |
|---|---|---|
| (a) Atomic retrieval | 10/11 titles verified in seed; 1 wrong slot (Dragon Age for RDR2) | 10/10 verified; 1 weak entry (Miles Morales — console excitement, not intent) |
| (b) Correct join | Correct — finished vs unplayed, hours attached only to finished | Correct — same split |
| (c) Trap avoidance | Clean — no hours on unplayed titles | Clean — same |
| (d) Uncertainty | Flagged: "If TLOU2 was really one run, the total is 115" — but as a subordinate clause | Flagged and foregrounded: "the number is either 115 or 140... Which was it?" |

**Result: A wins (a) marginally on volume, C wins (d) on placement. Both clean on (b) and (c).**

Grok's 7.5 vs 9.0 is not supported by these axes. The 1.5-point gap came from a gold-set error and a style penalty, neither of which is a scored axis.

---

## 8. Open items

- The 17-question Tier 1–5 set should be retained as a **retrieval baseline**, not the main bench. It is a plumbing check.
- The conversational set (lines 116–125, ten prompts) is the correct main bench. It needs a verified gold built from the seed before any arm is scored against it.
- No prompt in either set tests **abstention** — a question whose correct answer is "not in memory." That gap remains open.
