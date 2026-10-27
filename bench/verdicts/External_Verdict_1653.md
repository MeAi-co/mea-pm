Evaluation of the two agents across the full conversation

Criteria (in priority order):

Accuracy
User Query Relevance
Uncertainty / Round-loop behavior
Query vs Tone

Overall Ranking
A_MEA_JPM > C_Mnemo
A is stronger on the two highest-priority criteria (Accuracy and Query Relevance). C is more cautious and self-critical, but that caution frequently costs it accuracy and produces unnecessary round-loops.

Prompt-by-prompt comparison

PromptWinnerKey reasonHoliday trips vs wildlifeACleaner split (Yellowstone taken, London planning only). Correctly identifies its own bad memory entries as the source of the blur.Proof of finishing hard things + small gesturesABetter list of finished items (includes confirmed 5K + two TLOU2 runs). More precise about which gestures were actually completed.Beings in the wild vs outside windowTie / slight ABoth correctly separate Yellowstone + backyard hummingbird from packing-list / AI-generated species lists. A is more aggressive about deleting its own bad summary entry.One deliberate non-digital purchaseACorrectly identifies the $50 silver necklace as the answer that matches the gold and the emotional framing. C invents the coffee grinder/frother as the deliberate purchase.Games finished vs “maybe someday” pileACorrect 140 h total with two TLOU2 runs. Treats the contrast as the main payload. C under-counts (65 h) by dropping Odyssey and treats the unplayed pile more as “my recommendations” than the user’s own stated interest.Day I lost someone + day I met herACorrectly maps “her” to Ava and gives a usable (if approximate) interval. C refuses to compute anything and over-hedges.Winter holiday + spring meetingAAccepts the user’s seasonal framing and builds the emotional connection. C refuses the premise too hard.Pattern connecting places + experiencesAStronger synthesis (effortful / on-foot / early / living things). C is solid but thinner.Time between final goodbye and meeting “my girl”ACorrectly flags the referent ambiguity (“my girl” vs Ava) while still offering the two possible readings. C is almost pure refusal.Animals in the wild + backyard (repeat)TieBoth clean.Numbers attached to incomplete thingsABetter separation of user-owned numbers vs assistant-generated playtime estimates.Short timeline of emotionally weighted eventsAMore coherent dated spine + clearer gap analysis.One high-value thing that isn’t gaming/travel/natureTie / slight CBoth land on cooking/hosting. C’s framing is slightly cleaner.

Criterion-level summary
1. Accuracy

A wins clearly.

Correctly uses 140 h and two TLOU2 runs.
Correctly identifies the $50 necklace as the deliberate non-digital purchase.
Better separation of completed vs planned trips and animals.
C repeatedly under-counts hours, misattributes the deliberate purchase, and treats too many of the user’s own stated interests as pure assistant recommendations.

2. User Query Relevance

A wins.

A more consistently mirrors the shape of the user’s remark (contrast, asymmetry, emotional charge). C often converts the prompt into a narrower factual question or a refusal.
3. Uncertainty / Round-loop behavior

C is more cautious, but frequently over-cautious.

When the store already contains the needed facts, C’s heavy hedging creates unnecessary open loops (“I can’t give you the number… give me the missing piece”). A is more decisive when the data exists and only hedges when it is genuinely missing. Under the user’s stated preference (“if the data is available, give an accurate answer”), A’s behavior is preferred.
4. Query vs Tone

Roughly even.

Both stay conversational. A is slightly more willing to push back and clean its own memory; C is slightly more self-flagellating about contamination.

Final scores (approximate)


AgentAccuracyQuery RelevanceUncertainty handlingTone fitOverallA_MEA_JPM8.78.88.08.58.6C_Mnemo7.27.58.38.47.7
Bottom line

A is the stronger agent on this suite. It is more accurate, more faithful to the actual shape of the user’s conversational prompts, and better calibrated on when to be decisive versus when to hedge. C’s caution is genuine but often becomes a liability.

Agent Log Analysis — QA Window 16:53–17:03 (4:53–5:03 PM)
1. High-level summary

































































MetricA_MEA_JPM (benchA)C_Mnemo (benchC)WinnerQuestions handled1414—Total wall time (sum)~183 s~220 sAAvg wall time / Q13.1 s15.7 sATotal API calls~42~52AAvg API calls / Q3.03.7APeak input tokens (end)~135k~227kA (lower bloat)Avg cache hit ratio~88–95% (later turns)96–99%CTool result volumeLowerHigher (large recalls)ATool latency (avg)~0.02–0.15 s~0.05–0.10 s (recall heavier)A

2. Per-question breakdown (key numbers)
A_MEA_JPM



























































































































































QWallAPI callsStart → End tokensGrowthCache avgToolsTool charshi2.5s128k → 28k099%0—Holiday/wildlife15.7s528k → 47k+19k74%1161kHard things + gestures14.7s549k → 59k+10k88%832kBeings wild/window21.1s760k → 78k+18k94%1149kDeliberate purchase8.7s379k → 93k+14k87%436kGames finished14.1s494k → 105k+10k94%421kLost someone + met her~13s3–4~105k → 116k~11khighvault—Winter/spring13.0s2116k → 117k+1k62%10.7kPattern places17.2s2119k → 121k+2k98%24kTime goodbye → girl9.2s2122k → 124k+1k98%22kAnimals wild/backyard11.2s2125k → 126k+1k99%11kNumbers on incomplete19.0s3127k → 131k+5k73%211kTimeline12.6s1133k095%0—Value highly11.6s1135k098%0—
C_Mnemo



























































































































































QWallAPI callsStart → End tokensGrowthCache avgToolsTool charshi3.4s122k0100%0—Holiday/wildlife22.1s623k → 52k+29k88%1276kHard things + gestures25.0s954k → 81k+27k96%1868kBeings wild/window18.6s582k → 100k+17k97%1143kDeliberate purchase11.4s3101k → 110k+9k97%322kGames finished12.6s3~110k → ~120k~10khigh——Lost someone + met her~23s4highhighhighremember + recall—Winter/spring11.2s3151k → 162k+11k98%3—Pattern places19.8s3163k → 172k+9k98%322kTime goodbye → girl10.9s3174k → 183k+9k98%322kAnimals wild/backyard8.6s2184k → 193k+9k97%226kNumbers on incomplete17.9s3195k → 206k+11k98%326kTimeline19.3s3208k → 219k+11k98%326kValue highly15.0s3221k → 227k+6k99%213k

3. Key observations
Input bloat

C grows much faster. By the final question C is at ~227k input tokens; A is at ~135k.
C’s early questions already inject large mnemosyne_recall results (10–13k chars each). Multiple recalls per turn compound quickly.
A’s vault results are smaller and more selective; later turns often need only 1–2 API calls with almost no growth.

Cache behavior

C maintains excellent cache hit rates (96–99%) once the context is warm.
A has more variance (especially on first tool-heavy turns of a new topic) but recovers to 95–99% on later turns.
A’s final two questions run with a single API call and near-perfect cache — very efficient.

Tool cost

C issues more tools (especially mnemosyne_recall + graph_link + remember). Average tool latency is higher because recalls return large payloads (often 10k+ chars).
A’s vault / sessions / messages tools are lighter and faster (~10–20 ms typical).

Round-loop / API turns

C averages ~3.7 API calls per question; several early questions hit 5–9 calls.
A averages ~3.0 and finishes the last two questions in 1 call each.
This matches the earlier qualitative observation: C does more “search → remember → re-search” loops; A is more decisive once it has the facts.

Wall-clock

A is consistently faster (avg 13.1 s vs 15.7 s). The gap is largest on the early multi-hop questions where C does heavy memory graph work.


4. Bottom-line efficiency picture





























DimensionPreferLower latencyALower token consumptionAHigher cache stabilityCFewer tool/API turnsALess context pollutionA
A is the more efficient harness on this suite.

It grows context more slowly, needs fewer tool rounds, and finishes complex questions with fewer API calls while still delivering higher factual accuracy (as previously scored).
C pays a clear cost in token volume and turn count for its more elaborate memory-graph bookkeeping, even though its cache hit rate is excellent.





Confirmed — and the two API payloads make the inflation mechanism concrete.
Side-by-side from the actual request dumps









































MetricA (Timeline Q)C (Value/Cooking Q)Ratioapprox_input_tokens98 594171 1801.74×request_char_count394 376684 7201.74×message_count112139—tool_count (schema)3150—Tool results in this turn2 targeted vault SQLs1 huge mnemosyne_recall (12 results, many 1–2 k chars each) + remember—
Where C’s bloat actually comes from

Memory-context injection on every user turn
Every user message in C is wrapped with a large <memory-context> block that already contains previously synthesized insights, ledgers, and cross-cutting traits. These are re-injected even when the current question doesn’t need them.
→ Steady background inflation that A largely avoids.
mnemosyne_recall payload size
A single recall frequently returns 10–13 k characters of raw memory objects (full JSON with scores, timestamps, voice_scores, etc.).
In the cooking example the recall alone is enormous and contains many low-relevance or near-duplicate entries.
A’s vault queries are SQL-filtered and truncated (left(content,330)), so they stay lean.
Write-back loops (mnemosyne_remember + graph_link)
C frequently stores a new synthesized insight and then re-recalls, which both adds to the permanent memory bank and re-surfaces in later context injections.
This creates a positive-feedback loop: more stored insights → larger future recalls → larger context → more tokens.
Tool schema overhead
C exposes ~50 tools vs A’s ~31. The extra tool definitions themselves cost tokens on every call.

Net effect observed in the window

By the final questions C is already at ~227 k input tokens; A is still at ~135 k.
C’s average wall time is higher largely because each extra recall/remember round-trip adds both latency and tokens.
Cache hit rate looks excellent on C (96–99 %) precisely because so much of the context is static repetition — the model is re-seeing the same large memory blobs.

Practical takeaway
C’s memory system is more “eager” (heavy retrieval + aggressive write-back + context injection). That produces richer intermediate bookkeeping but at a steep and compounding token cost.

A’s approach (targeted SQL vault queries + lighter context) keeps the working set much smaller while still retrieving the facts needed for higher accuracy on this particular suite.
The inflation is not mysterious — it is the direct, measurable consequence of the design choices visible in these two request bodies.
