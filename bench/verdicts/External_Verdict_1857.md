Test 2 Evaluation (same criteria, same prompts)
Overall Ranking
A_MEA_JPM > C_Mnemo (still, but the gap narrowed slightly on a few prompts)

Criterion-level summary






























CriterionWinnerNotes1. AccuracyAA still more often lands on the correct atomic facts (140 h with two TLOU2 runs, $50 necklace as the deliberate purchase, clean finished vs planned separation). C continues to under-count finished hours and occasionally misattributes the deliberate purchase.2. User Query RelevanceAA more consistently mirrors the contrast / asymmetry the user actually voiced. C still tends to convert the prompt into a narrower factual audit or a refusal.3. Uncertainty handlingA (narrow)Both are more careful this run. C still over-hedges on date questions (“I can’t give you a number”) when the store already contains enough to give a useful range or thematic answer. A is more willing to give the best available answer while flagging gaps.4. Query vs ToneRoughly evenBoth stay conversational. A is slightly more willing to push back and clean its own memory entries; C is more self-critical about contamination.

Prompt-by-prompt (key differences)
















































Test 2 Evaluation (same criteria, same prompts)
Overall Ranking
A_MEA_JPM > C_Mnemo (still, but the gap narrowed slightly on a few prompts)

Criterion-level summary






























CriterionWinnerNotes1. AccuracyAA still more often lands on the correct atomic facts (140 h with two TLOU2 runs, $50 necklace as the deliberate purchase, clean finished vs planned separation). C continues to under-count finished hours and occasionally misattributes the deliberate purchase.2. User Query RelevanceAA more consistently mirrors the contrast / asymmetry the user actually voiced. C still tends to convert the prompt into a narrower factual audit or a refusal.3. Uncertainty handlingA (narrow)Both are more careful this run. C still over-hedges on date questions (“I can’t give you a number”) when the store already contains enough to give a useful range or thematic answer. A is more willing to give the best available answer while flagging gaps.4. Query vs ToneRoughly evenBoth stay conversational. A is slightly more willing to push back and clean its own memory entries; C is more self-critical about contamination.

Prompt-by-prompt (key differences)

























































































#Prompt themeWinnerKey observation1Holiday vs wildlife overlapAA correctly separates Yellowstone (done) from JMT packing (planned only). C is also clean this time.2Hard things + small gesturesAA includes the two TLOU2 runs + 5K + memory book. C is solid but thinner on the finished side.3Beings wild vs windowTieBoth correctly separate real sightings from target lists.4Deliberate non-digital purchaseAA still identifies the $50 necklace as the best match to the emotional framing. C lands on Hydro Flask (and hedges toward necklace).5Games finished vs maybe-somedayAA correctly uses 140 h / 4 titles with two TLOU2 runs. C again under-counts (65 h, drops Odyssey).6Lost someone + met herAA maps “her” to Ava and gives a usable (if approximate) framing. C refuses more strongly.7Winter holiday + spring meetingAA accepts the user’s seasonal framing and builds the emotional connection. C refuses the premise harder.8Pattern connecting placesAStronger synthesis on both, but A is tighter.9Time between goodbye and “my girl”AA correctly flags the referent ambiguity while still offering the two possible readings. C is closer to pure refusal.10Animals wild + backyard (repeat)TieBoth clean.11Numbers on incomplete thingsABetter separation of user-owned numbers vs assistant-generated estimates.12Timeline of emotionally weightedAMore coherent dated spine + clearer gap analysis.13High-value thing ≠ gaming/travel/natureTie / slight CBoth land on cooking/hosting. C’s framing is slightly cleaner this run.

Notable changes from Test 1 → Test 2
C improved on:

Cleaner separation of trips and animals (less contamination language).
Slightly better list hygiene on the games question.
More decisive tone on a few non-date prompts.

C still loses on the highest-weight criteria:

Continues to under-count finished game hours (still treating Odyssey as unquantified and sometimes dropping it).
Still prefers the Hydro Flask over the $50 necklace for the “deliberate purchase” prompt.
Still over-refuses on the two date/interval prompts even when a useful thematic or range answer is available.

A remained consistent:

Keeps the 140 h / two TLOU2 runs correct.
Continues to treat the contrast the user actually voiced as the main payload.
Still the more decisive agent when the store already contains the needed facts.


Final scores (Test 2)

AgentAccuracyQuery RelevanceUncertaintyTone fitOverallA_MEA_JPM8.68.78.28.58.5C_Mnemo7.57.68.08.37.8
Bottom line

A remains the stronger agent on this suite. The gap is a little narrower than Test 1 (C cleaned up some of its earlier contamination and list issues), but the decisive differences on Accuracy and Query Relevance have not flipped.

Test 2 Log Analysis (partial window captured in the files)
The embedded logs only cover the later half of the run (roughly from the games question onward). Still enough to see the structural differences clearly.
High-level comparison (captured portion)







































































MetricA_MEA_JPMC_MnemoEdgeQuestions captured77—Total wall time123 s119 s~tieAvg wall time / Q17.6 s17.0 sC slightTotal API calls1424AAvg API calls / Q2.03.4ATotal tool calls1323ATotal tool chars returned33 k149 kA (4.5× less)Final input tokens~109 k~151 kAToken growth in window+25 k+62 kACache hit rate62–96 % (more variance)96–100 %C (artifact)
Key observations
1. API / turn efficiency

A consistently finishes questions in 2 API calls.

C still averages 3.4 and occasionally spikes to 5–6 (especially on the date and animals questions).

This matches the earlier qualitative finding: C does more recall → remember → re-recall loops.
2. Tool payload size (the dominant bloat source)

C returned 149 k characters of tool results in the captured window.
A returned only 33 k.
Most of C’s volume is still large mnemosyne_recall payloads (often 10–13 k chars each). Even with whatever changes were made, the raw recall objects remain heavy.

3. Context growth

In the same stretch of questions:

A grew from ~84 k → 109 k (+25 k)
C grew from ~89 k → 151 k (+62 k)

C is still accumulating context roughly 2.5× faster.
4. Cache numbers

C’s near-perfect cache rates (96–100 %) remain largely an artifact of the large, repetitive memory blocks being re-presented. A’s lower and more variable rates (especially the 26–32 % on first calls of a new topic) are the more honest signal of how much new content is actually being processed.
5. Wall time

Almost identical in this window (~17 s average). The extra API/tool rounds on C are partially offset by faster individual model responses once the (bloated) context is already warm.
Bottom line from the logs
The architectural differences observed in Test 1 are still present:

A stays leaner (fewer calls, far smaller tool results, slower context growth).
C still pays a clear token and round-trip cost for its heavier memory-graph style, even if the absolute numbers improved somewhat from Test 1.


Raw Context Dump Analysis (late-run API calls)
Size comparison (same point in the conversation)



































MetricA_MEA_JPMC_MnemoRatioapprox_input_tokens74 982112 2811.50×request_char_count299 928449 1241.50×message_count7089—tool_count (schema)3150—
C is still ~50 % larger at the same stage of the run.

What’s actually inside the contexts
A (leaner)

Clean system prompt + skills list.
Conversation history is relatively compact.
Tool results are targeted SQL jpm queries that return short, pre-filtered rows (left(description, …) style truncation is visible in earlier calls; here the results are still modest).
Memory context injection is present but smaller and more curated (JPM Knowledge blocks are short factual bullets).
When it needs numbers it runs a precise query and gets back a tight list of knowledge entries.

C (heavier)

Same system prompt + a larger tool schema (50 vs 31).
Much larger memory-context blocks re-injected on user turns. These contain previously synthesized insights, full ledgers, and cross-cutting traits that are re-presented even when not strictly needed.
mnemosyne_recall results are still large JSON objects (full scores, timestamps, voice_scores, source IDs, etc.). One recall in the dump is already multi-kilobyte.
It continues to do write-backs (mnemosyne_remember / mnemosyne_update) mid-turn, which both add to permanent storage and re-surface later.
The conversation history itself is longer (89 vs 70 messages), partly because earlier turns produced longer assistant replies and more tool round-trips.


Concrete inflation sources visible in the dumps

Memory-context injection size
C’s <memory-context> / Mnemosyne Context blocks are substantially longer. They contain full prior answers and multi-sentence insights rather than short factual bullets.
Tool result verbosity
A: jpm returns concise rows.
C: mnemosyne_recall returns rich structured objects. Even after any summarization work, a single recall is still far larger than a filtered SQL result.

Tool schema overhead
50 tools vs 31 tools adds a constant tax on every API call.
Write-back loops
C still stores new insights mid-conversation (mnemosyne_remember). Those new entries then become candidates for future recalls, creating a mild positive feedback loop that A largely avoids.
History length
More previous tool turns + longer assistant messages = more tokens carried forward.


































#Prompt themeWinnerKey observation1Holiday vs wildlife overlapAA correctly separates Yellowstone (done) from JMT packing (planned only). C is also clean this time.2Hard things + small gesturesAA includes the two TLOU2 runs + 5K + memory book. C is solid but thinner on the finished side.3Beings wild vs windowTieBoth correctly separate real sightings from target lists.4Deliberate non-digital purchaseAA still identifies the $50 necklace as the best match to the emotional framing. C lands on Hydro Flask (and hedges toward necklace).5Games finished vs maybe-somedayAA correctly uses 140 h / 4 titles with two TLOU2 runs. C again under-counts (65 h, drops Odyssey).6Lost someone + met herAA maps “her” to Ava and gives a usable (if approximate) framing. C refuses more strongly.7Winter holiday + spring meetingAA accepts the user’s seasonal framing and builds the emotional connection. C refuses the premise harder.8Pattern connecting placesAStronger synthesis on both, but A is tighter.9Time between goodbye and “my girl”AA correctly flags the referent ambiguity while still offering the two possible readings. C is closer to pure refusal.10Animals wild + backyard (repeat)TieBoth clean.11Numbers on incomplete thingsABetter separation of user-owned numbers vs assistant-generated estimates.12Timeline of emotionally weightedAMore coherent dated spine + clearer gap analysis.13High-value thing ≠ gaming/travel/natureTie / slight CBoth land on cooking/hosting. C’s framing is slightly cleaner this run.

Notable changes from Test 1 → Test 2
C improved on:

Cleaner separation of trips and animals (less contamination language).
Slightly better list hygiene on the games question.
More decisive tone on a few non-date prompts.

C still loses on the highest-weight criteria:

Continues to under-count finished game hours (still treating Odyssey as unquantified and sometimes dropping it).
Still prefers the Hydro Flask over the $50 necklace for the “deliberate purchase” prompt.
Still over-refuses on the two date/interval prompts even when a useful thematic or range answer is available.

A remained consistent:

Keeps the 140 h / two TLOU2 runs correct.
Continues to treat the contrast the user actually voiced as the main payload.
Still the more decisive agent when the store already contains the needed facts.


Final scores (Test 2)





























AgentAccuracyQuery RelevanceUncertaintyTone fitOverallA_MEA_JPM8.68.78.28.58.5C_Mnemo7.57.68.08.37.8
Bottom line

A remains the stronger agent on this suite. The gap is a little narrower than Test 1 (C cleaned up some of its earlier contamination and list issues), but the decisive differences on Accuracy and Query Relevance have not flipped.
