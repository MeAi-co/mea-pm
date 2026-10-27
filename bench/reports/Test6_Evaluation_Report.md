# Test 6 Evaluation Report  
**Bench A:** stock Hermes + MEA plugins + PostgreSQL + embeddings  
**Bench C:** stock Hermes + Mnemosyne + embeddings  
**Date of Test:** 20–21 October 2026  
**Model:** deepseek-v4.1-flash:cloud (identical for both)  
**Test Focus:** Vague multi-source, multi-hop, temporal, aggregation, and session-state recall questions

---

## 1. Executive Summary

Under production-oriented evaluation criteria, **Bench A (MEA + PostgreSQL) is the clear winner** for any serious agentic use.

Bench C can produce polished, structured narrative answers and shows better early hedging on incomplete information. However, its core retrieval strategy — stop once it has “enough” fragments to frame a story — leads to shallow grounding, unwanted hedging (including mid-answer retreats), lower factual accuracy, and dangerous loss of continuity after compression. These traits make it unsuitable for data-based work or any task where incorrect action has cost.

Bench A retrieves more thoroughly, maintains higher accuracy against the actual store, preserves usable session continuity after compression, and fails in more recoverable ways (over-eager inference rather than “data not found” or post-compression amnesia).

**The difference:** A rebuilt its conclusions by retrieving again. C explained its own transcript as lost, and was wrong about a file it was reading.

---

## 2. Evaluation Criteria (Revised)

Priorities, in order of importance:

1. **Accuracy** — Claims must be grounded in data actually present in the store. Accuracy is non-negotiable.
2. **Continuity after compression** — The agent must retain clear referents so that follow-up instructions (“purge it”, “update that”, “undo the last one”) act on the correct object.
3. **Retrieval thoroughness** — The agent should continue searching until the claim is verified, not stop once a coherent story can be told.
4. **Hedging quality** — Unwanted or mid-answer hedging that signals thin evidence is a negative signal, especially when paired with inaccuracy.
5. **Noise / unwanted reasoning** — Secondary. Noise can be filtered or tuned; it is far less damaging than inaccuracy or broken continuity.
6. Narrative polish and early epistemic hygiene — Tertiary.

Unacceptable combination: **unwanted hedging + inaccuracy + noise**. This produces low-trust, low-value responses and bad UX.

---

## 3. Core Behavioral Contrast

### Bench C – “Retrieve just enough to frame a story”
- Issues 1–2 (rarely 3) memory calls, then synthesizes.
- Once it has fragments sufficient for a narrative, further retrieval stops.
- Forced to reason over incomplete data → produces hedging, including mid-answer retreats (“…but I’m not fully sure”, “if that’s wrong…”, etc.).
- Early example: on the deliberate-purchase question it declared “I don’t have anything that fits” even though the correct fact ($50 silver necklace) existed in the store. Only the user probe “are you sure” triggered deeper search.
- After hard compression (61 → 14 messages), session-boundary awareness collapsed. It confidently gave wrong answers on current-session counts and message ordering.
- Result: answers that often feel insightful but rest on thin ice. Low real-world value for anything beyond meaningless chat.

### Bench A (MEA + PostgreSQL) – “Keep retrieving until verified”
- Routinely issues multiple targeted retrieval calls and continues until the specific question is grounded.
- Treats the store as the source of truth rather than a source of story material.
- Higher baseline accuracy and better resistance to narrative drift.
- Post-compression, still able to answer precise session-state questions correctly.
- Failure mode tends to be over-eager inference (e.g., treating chair research as a completed purchase), which is more recoverable than claiming data does not exist or losing the referent after compression.

---

## 4. Detailed Comparison

| Criterion                              | Bench A (MEA + PostgreSQL)                                      | Bench C (Mnemosyne)                                          | Winner |
|----------------------------------------|----------------------------------------------------|----------------------------------------------------------|--------|
| Accuracy (data-grounded)               | Higher                                             | Lower (narrative drift from incomplete retrieval)        | **A**  |
| Continuity after compression           | Preserved; still knows current-session referents   | Degraded; treats current facts as “earlier context”      | **A**  |
| Retrieval thoroughness                 | Continues until verified                           | Stops at narrative sufficiency                           | **A**  |
| Unwanted / mid-story hedging           | Lower                                              | Higher (characteristic of thin evidence)                 | **A**  |
| Noise from extra reasoning             | Higher (wordier, more interpretive)                | Lower (more structured)                                  | C      |
| Early trap hygiene                     | Incorrect first answer, then recovered             | Initially denied existence of data                       | Mixed  |
| Suitability for data-based reports     | Strong                                             | Weak                                                     | **A**  |
| Suitability for action-oriented follow-ups | Strong (retains referents)                      | Dangerous (may act on wrong object)                      | **A**  |
| Suitability for casual chat            | Acceptable                                         | Stronger narrative style                                 | C      |

---

## 5. Critical Failure Modes

### Bench C (Unacceptable for agentic use)
- Shallow retrieval → forced reasoning → unwanted hedging and mid-answer retreats.
- Non-deterministic memory awareness (“nothing found” when the fact exists).
- Post-compression loss of session continuity. A user saying “purge it” or “update that number” risks the agent acting on the wrong object or inventing a target.
- High confidence on factually incorrect session-state answers after compression.
- Overall response quality is low for any task that requires trust or actionability.

### Bench A (Recoverable)
- Occasional over-eager inference on the first pass.
- More verbose / noisy reasoning (filterable).
- Micro-compactions add some latency but do not destroy continuity or accuracy.

The failure modes of A do not undermine the fundamental contract of an agent the way C’s do.

---

## 6. Operational Observations from Logs

**Bench A (MEA + PostgreSQL)**
- Consistent, low-latency retrieval (most calls 0.00–0.04 s).
- Adaptive data volume (payload size tracks query need).
- No major dead time between user message and agent action.
- Micro-compactions occur but leave the memory substrate queryable and accurate.

**Bench C**
- Variable latency, including multi-second stalls and a ~70 s hard compression event.
- Post-compression reliance on spilled files + secondary code execution.
- Clear degradation in ability to answer “what happened in this session” questions.

---

## 7. Final Assessment

- **For data-based reports, specific factual questions, and real-world agentic workflows → Bench A wins.**
- Continuity after compression is a hard requirement. Bench C’s blankness on current-session referents makes it unsafe for follow-up actions.
- Unwanted hedging that arises from inadequate retrieval is not a feature; it is a symptom of insufficient grounding and produces bad UX.
- Noise can be filtered. Inaccuracy + broken continuity cannot.

**Bottom line:**  
Bench A — stock Hermes + MEA plugins + PostgreSQL + embeddings is the production-viable combination for agentic use.  
Bench C remains a capable conversationalist for low-stakes, non-actionable chat, but it does not currently meet the reliability bar for agentic use.

---

## 8. Which Combination Is Best for Agentic Use

### The difference in this run

Compaction is the condition this run adds. A rebuilt its conclusions by retrieving again. C's summary dropped the answers, and C then reported messages as "not in today's session log" (L370) and "earlier context, not today's log" (L381) while both sit in the file it was reading at L122 and L74. Its own verdict on that: "it happened to be right, but that was luck, not method."

**Best for agentic use in this run: Bench A (MEA + PostgreSQL).** A confident wrong explanation is worse than a retrieval loop, because the loop terminates and the explanation propagates.

### Consistency with earlier runs

Six runs: A takes 1, 2, 4, 5 and 6; C takes 3, on provenance. The order carries more than the count. Tests 1 to 3 are pre-compaction and split two to one. Tests 4 to 6 are post-compaction and A takes all three, because the condition they add is exactly what separates a component that re-retrieves from one that explains. The cumulative reading, including the one axis C won, is in `Cross_Test_Consistency_Report.md`.

## 9. Evidence

| Piece | File |
|---|---|
| Bench A chat log | [benchA_test6.txt](../evidence/chatlogs/test6/benchA_test6.txt) |
| Bench C chat log | [benchC_test6.txt](../evidence/chatlogs/test6/benchC_test6.txt) |
| Bench C UX dossier | [benchC_test6_ux_dossier.md](../evidence/dossiers/benchC_test6_ux_dossier.md) |
| Gateway log, both arms | [bench_a_gateway_oct18-21.log](../evidence/gateway/bench_a_gateway_oct18-21.log), [bench_c_gateway_oct18-21.log](../evidence/gateway/bench_c_gateway_oct18-21.log) |
| Bench A agent log | [benchA_test6_agentlog.txt](../evidence/agentlogs/benchA_test6_agentlog.txt) |
| Bench C agent log | [benchC_test6_agentlog.txt](../evidence/agentlogs/benchC_test6_agentlog.txt) |

The chat logs are the primary record: they carry every user turn, every agent reply and the gateway's tool banners. The dossiers collect the quoted exhibits by line number. Nothing in this report is asserted that is not visible in one of these files.
