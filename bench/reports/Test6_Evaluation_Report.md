# Bench A (A_MEA_JPM) vs Bench C (C_Mnemo)  
## Test 6 Evaluation Report (Revised)  
**Date of Test:** 20–21 October 2026  
**Model:** deepseek-v4.1-flash:cloud (identical for both)  
**Test Focus:** Vague multi-source, multi-hop, temporal, aggregation, and session-state recall questions

---

## 1. Executive Summary

Under production-oriented evaluation criteria, **Bench A (JPM) is the clear winner** for any serious agentic use.

Bench C can produce polished, structured narrative answers and shows better early hedging on incomplete information. However, its core retrieval strategy — stop once it has “enough” fragments to frame a story — leads to shallow grounding, unwanted hedging (including mid-answer retreats), lower factual accuracy, and dangerous loss of continuity after compression. These traits make it unsuitable for data-based work or any task where incorrect action has cost.

Bench A retrieves more thoroughly, maintains higher accuracy against the actual store, preserves usable session continuity after compression, and fails in more recoverable ways (over-eager inference rather than “data not found” or post-compression amnesia).

**The difference:** Bench A trusts its tools and does not fail at the point of use. Bench C treats retrieval as an opening bid and works around it when the answer comes back thin.

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

### Bench A (JPM) – “Keep retrieving until verified”
- Routinely issues multiple targeted retrieval calls and continues until the specific question is grounded.
- Treats the store as the source of truth rather than a source of story material.
- Higher baseline accuracy and better resistance to narrative drift.
- Post-compression, still able to answer precise session-state questions correctly.
- Failure mode tends to be over-eager inference (e.g., treating chair research as a completed purchase), which is more recoverable than claiming data does not exist or losing the referent after compression.

---

## 4. Detailed Comparison

| Criterion                              | Bench A (JPM)                                      | Bench C (Mnemo)                                          | Winner |
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

**Bench A (JPM)**
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

- **For data-based reports, specific factual questions, and real-world agentic workflows → Agent A wins.**
- Continuity after compression is a hard requirement. Bench C’s blankness on current-session referents makes it unsafe for follow-up actions.
- Unwanted hedging that arises from inadequate retrieval is not a feature; it is a symptom of insufficient grounding and produces bad UX.
- Noise can be filtered. Inaccuracy + broken continuity cannot.

**Bottom line:**  
Bench A is the production-viable agent.  
Bench C remains a capable conversationalist for low-stakes, non-actionable chat, but it does not currently meet the reliability bar for agentic use.

---

## 8. The Difference

**Bench A (JPM): trusts the tools.** Every call goes to a memory tool or an arithmetic step over values a memory tool returned. When retrieval is thin it retrieves again; when the record does not hold the answer it says so and names what it searched. In this run none of A's failures came from stepping outside the tool surface, and each of them is recoverable by asking again.

**Bench C (Mnemosyne): works around the tools.** When recall comes back thin it constructs an answer, and when the answer is challenged it reaches for another channel: the filesystem, its own database file, or an account of what it believes happened to the data. The answer arrives before the search does, which is why the workaround is needed at all.

C's workaround was an explanation: that compaction had deleted the answers, and that messages sitting in its own transcript were "not in today's log". The agent's own line records what that is worth: "it happened to be right, but that was luck, not method." A lost conclusions to vagueness and rebuilt them by retrieving again.

Evidence: `evidence/chatlogs/test6/benchA_test6.txt`, `benchC_test6.txt`, `evidence/agentlogs/`.
