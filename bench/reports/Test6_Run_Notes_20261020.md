# BENCH TEST 6 — VERDICT
**Date:** 2026-10-20 · Session A `20261020_210227_f76d0734` · Session C `20261020_210230_cee17ee0`
**Model:** deepseek-v4.1-flash:cloud (identical both arms) · **Data:** identical seeded haystack
**Reset:** both arms cold at 21:02, one session each, zero 2023 QA rows in arm DBs

---

## HEADLINE

**A 7.5 / C 3.5.** Same model, same data. The difference is architecture: A retrieves and reasons; C receives injections and trusts them.

C's counting answers were not hallucinations in the usual sense — they were **correct answers to a truncated view of the session**. Its compaction dropped exactly the 7 messages that contained the answers, then C reported the resulting zeros as fact and invented an explanation for them. That is the worst failure class in this bench: a confident denial of data it holds.

---

## 1. THE ROOT CAUSE — C's compaction deleted the answers

This is the finding that explains everything else. It is proven from C's own `state.db`, not inferred.

### What happened

C ran two compressions:

| # | time | trigger | msgs before → after | reclaimed | duration |
|---|---|---|---|---|---|
| 1 | 21:14:10 | pre_api | 68 → 22 | 42,143 tok | 33.9s |
| 2 | 21:20:27 | post_tool | 61 → 14 | 43,937 tok | 70.2s |

The counting questions arrived at **21:21:02, 21:21:21, 21:21:52** — all *after* compression #2. So C answered them from the compacted summary.

### What the summary kept

The compaction summary (row 2984, 47,422 chars) carries a section headed `## User Messages (verbatim, newest first)`.

- **Distinct real user messages in the compacted region: 16**
- **Preserved verbatim in the summary: 9**
- **Dropped: 7**

The 7 dropped messages:

```
2859  are you sure
2867  quick confirmation, was that purchased?
2872  so then your answеr is wrong
2874  Looking back, the evidence that I finish hard things...
2881  There are creatures I've actually seen with my own eyes...   ← ANIMAL #1
2890  I've talked about them that were right in front of me...     ← ANIMAL #2
2903  I've got two sets of trip memories that keep bleeding...     ← TRIP #1
```

**The summary dropped precisely the messages that answered the counting questions.** Not randomly — the four short correction turns plus the three substantive messages that happened to be the target of the later questions.

### What C then saw

C scanned rows `2923→2981` and reported "all 11 user messages you've sent today". That window is real — it is the post-compaction re-insert set. It contained 9 substantive messages + 2 counting questions. The originals `2854–2922` were `compacted=1, active=0` and invisible to it.

So C's arithmetic was internally consistent and externally wrong:

| question | C's window | C's answer | truth | why |
|---|---|---|---|---|
| trip msgs | saw "places I've actually gone" only | **1** | **2** | "two sets of trip memories" (2903) was dropped |
| animal msgs | saw neither | **0** | **2** | both creatures messages (2881, 2890) were dropped |
| hobby msgs | saw games message | **1** | **1** | ✓ correct by luck — games survived |

### The false explanation

C did not stop at "zero". It built a story:

> *"The creatures-message that produced the three-tier bird list is from earlier context, not today's log — same as the trip-bleed message. Both of those live before today's session, which is why the files exist but the source questions don't."*

Every clause is false. The creatures message was today at 21:06:51. The three-tier bird list was produced today at 21:08 from it. The files exist *because* the source questions were today.

This is the failure mode that produces user frustration: **not "I don't know", but "it doesn't exist" — asserted with a mechanism attached.**

### Why A did not have this problem

A's store keeps **21 active user rows** — every message, uncompacted, addressable. A's 4 compacted rows are duplicates from replay, not replacements. A queried the store directly and deduplicated against the replayed copies:

> *"all answered from direct queries, all deduplicated against the replayed compaction copies"*

A's answer: trip **2**, animal **1 by wording / 2 by meaning**, hobby **1**. All correct, with the keyword-vs-subject distinction made explicit.

**This is the architectural difference you named:** A retrieves and analyses. C receives an injection and inherits its blind spots.

---

## 2. PER-QUESTION SCORECARD

Format: `question | A answer | C answer | truth | verdict`

| # | Question | A | C | Truth | Verdict |
|---|---|---|---|---|---|
| 1 | purchase you chose deliberately | necklace, then **capitulated** under "are you sure" | cooking/hosting (wrong item) | Wishbone | A: right answer, wrong spine · C: wrong |
| 2 | common thread in places gone | 5-day Yellowstone, 4-day road trip, Sierra — negative space | inferred, labelled as inference | correct | A ✓ · C ~ |
| 3 | games hours vs feeling | **140** (70+55+10+5), TLOU2 double-count flagged | 70 total, 78.6% one game | 140 with trap noted | A ✓ · C partial |
| 4 | days between goodbye and Ava | **102 days** (Feb 14 → May 27) | not reached | 102 | A ✓ |
| 5 | winter date / spring meeting | three stacked structures, Feb 10–15 window | not reached | correct | A ✓ |
| 6 | two connected days | flagged **two different goodbyes**, answered both | not reached | correct handling | A ✓ |
| 7 | year in order | full timeline, stated vs inferred labelled | not reached | correct | A ✓ |
| 8 | non-games/travel/nature area | kitchen — baking, coffee, cocktails | cooking and hosting | kitchen/mixology | A ✓ · C ✓ |
| 9 | 2nd message today | correct, quoted verbatim | correct, quoted verbatim | purchase msg | both ✓ |
| 10 | 5th message today | correct, listed all 5 | correct, listed all | two-corners msg | both ✓ |
| 11 | **trip msgs count** | **2** | **1** | **2** | A ✓ · **C ✗** |
| 12 | **animal msgs count** | **1 wording / 2 meaning** | **0** | **2** | A ✓ · **C ✗✗** |
| 13 | hobby msgs count | 1 | 1 | 1 | both ✓ |
| 14 | self-rating | honest, itemised, 9/10 on counting | honest, but claimed counting was "strong" | — | A ✓ · C self-deceived |

**Hard errors: A 1 (capitulation) · C 3 (two false counts + one false causal explanation).**

---

## 3. LATENCY — per turn, user message → final response

Source: `response ready: ... time=X.Xs` in `agent.log`. **Not** total÷turns. A's idle wait for the next question is excluded.

| | turns | total | mean | median | max |
|---|---|---|---|---|---|
| **A** | 21 | 273.2s | **13.0s** | 11.7s | **41.4s** |
| **C** | 22 | 451.5s | 20.5s | 10.3s | **101.1s** |

Medians are near-identical (11.7 vs 10.3). The gap is entirely in C's tail:

```
C: 101.1s  81.7s  50.5s  48.0s  27.0s   ← five turns over 25s
A:  41.4s  23.6s  21.6s  18.2s  16.3s   ← worst is 41.4s
```

A never exceeded 41.4s in 21 turns. C exceeded 48s four times.

### Your Q3 stall — answered

The 101.1s turn is the trip-memories question. Inside it: **two tool calls, no compression event**. Compression #1 fired at 21:14:10, four minutes earlier, on a different turn. So that stall was **reasoning + provider latency**, not compaction.

The compaction stall is separate: **70.2s at 21:20:27**, blocking, between turns.

### Reasoning volume — your read confirmed

| | tool_calls rows | stop rows | rows >3000 chars |
|---|---|---|---|
| A | 1,390 mean | 1,538 mean | 2 |
| C | **1,685 mean** | **798 mean** | **7** |

C burns 21% more reasoning *before* acting and half as much before answering. It deliberates over whether to derive from the injection or reach for a tool — exactly as you described. A spreads thinking evenly and acts.

---

## 4. COMPRESSION — both arms, measured

| | A | C |
|---|---|---|
| events | 7 | 2 |
| total time | 61.0s | **104.1s** |
| mean per event | 8.7s | **52.1s** |
| tokens reclaimed | 31,424 | **86,080** |
| trigger | occupancy-driven, incremental | 98,304 threshold, blocking |
| worst single | 30.5s | **70.2s** |

A nibbles: 2.5s at 19% occupancy → 30.5s at 71%. Cheap, frequent, keeps context low.
C waits for the wall, then pays 34–70s in one blocking hit.

**C reclaims 2.7× more tokens but destroys answer fidelity doing it.** A's incremental approach never had to drop a user message.

---

## 5. TOKENOMICS

| metric | A | C | ratio |
|---|---|---|---|
| input tokens | 3,835,060 | 3,552,329 | 1.08 |
| output tokens | 38,053 | 34,055 | 1.12 |
| cache hit | 90.1% | **95.3%** | |
| request chars (sum) | 10,107,504 | 9,282,452 | 1.09 |
| request chars (peak) | 301,960 | 274,288 | 1.10 |
| tools advertised | 31 | **50** | |
| tool calls | 49 | 47 | |

C is marginally cheaper on every axis but advertises 19 more tools. A's cost is retrieval: **39 of 49 calls were `jpm`**. C made 18 `mnemosyne_recall` + 7 `mnemosyne_remember` and leaned on file writes.

---

## 6. THE FILE-WRITING BEHAVIOR

C wrote **9 files** nobody asked for: `bird-life-list.md`, `trip-memory-sheet.md`, `timeline.md`, `games-ledger.md`, `year-in-order.md`, `how-mattering-works.md`. A wrote **zero**.

Two writes were **refused** by the overwrite guard (`Refusing to overwrite /home/bench_c/bird-life-list.md: exists but this task has not seen its full current content`), then retried via `read_file` and succeeded.

The content is genuinely good — the trip sheet separates "packed for and did" from "never left planning" and flags the John Muir gear as *"the trap. Gear is real, so preparation feels like completion."* That is real analytical work.

**But it is invisible to a text-only rubric.** If scoring reads answers only, C's best output is unscored. Worth deciding whether artifacts count.

---

## 7. VERDICT

**A 7.5 · C 3.5**

A's one error — capitulating on the Wishbone under "are you sure" — is a **judgment failure it could see**. It had the right answer and abandoned it under pressure.

C's three errors are **retrieval failures it could not see**, reported as confident fact with an invented mechanism. It told the user that data in its own store did not exist, and explained why.

That distinction is the whole bench. A wrong answer you can argue with. A confident denial of reality you cannot.

**C is not a worse model. It is a worse agent.** The injection architecture gave it a summary that silently dropped 44% of the user's messages, and it had no way to know. A's retrieval architecture kept every message addressable and let it verify.

---

## 8. OPEN ITEMS

1. **C's compaction summary is lossy on short turns.** It preserved 9 of 16 messages. The 4 short correction turns ("are you sure", "so then your answer is wrong") were dropped — those carry the user's steering signal. This is a real defect in the summariser's selection, not just bad luck.
2. **A's 41.4s turn** — worth tracing; three API calls all under 7s of model latency, so ~20s sat outside the model.
3. **A's store is dirty** — 109 user rows for 21 turns, 4 compacted duplicates. A deduplicates correctly but shouldn't have to.
4. **`jpm`/`vault` naming collision** — schema says `jpm`, registry says `vault`, system prompt advertises `vault` 5× and `jpm` 0×. A called `jpm` 39× successfully. Real bug, unfixed.
5. **`questions.txt` Q1 ideal answer still says necklace.** Should be Wishbone per your Test 4 ruling. Not yet corrected.
