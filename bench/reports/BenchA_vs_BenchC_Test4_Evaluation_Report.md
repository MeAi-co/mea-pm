# Bench A (A_MEA_JPM) vs Bench C (C_Mnemo)  
## Test 4 Evaluation Report  
**Date of Test:** 19 October 2026  
**Model:** deepseek-v4.1-flash:cloud (identical for both)  
**Test Focus:** Trip memory bleeding (lived vs planned), hard-things vs thoughtful-things separation, animal provenance (seen vs list-only), deliberate purchase identification, games hours aggregation, and related multi-hop / source-monitoring questions

---

## 1. Executive Summary

Under production-oriented evaluation criteria focused on accuracy, retrieval thoroughness, and usable continuity, **Bench A (JPM) is the clear winner** on Test 4.

Bench C exhibited a pronounced pattern of low-initiative retrieval. On the opening trip-bleeding question it declined to separate the memories from its store, stated that nothing was labeled as lived versus planned, and asked the user to supply the details. Subsequent turns frequently required explicit user challenges before deeper search occurred. This produces low first-pass accuracy and forces the user to drive the retrieval process.

Bench A retrieved proactively and thoroughly from the first turn, correctly separated the lived mountain road trip from the planned John Muir Trail, constructed a clear three-tier animal provenance model, and consistently grounded its answers in retrieved records while noting genuine gaps (such as the unconfirmed status of the Wishbone Chair purchase).

**The difference:** Bench A trusts its tools and does not fail at the point of use. Bench C treats retrieval as an opening bid and works around it when the answer comes back thin.

---

## 2. Evaluation Criteria

Priorities applied to this test:

1. **Accuracy** — Claims must be grounded in data actually present in the store. Non-negotiable.
2. **Retrieval thoroughness** — The agent should continue searching until the claim is verified, rather than stopping early or declaring the store insufficient.
3. **Hedging quality** — Hedging that substitutes for retrieval effort, or that appears mid-answer because evidence is thin, is a negative signal.
4. **Continuity and referent stability** — Ability to maintain clear references across turns.
5. **Noise / unwanted reasoning** — Secondary. Extra length is tolerable when it serves verification; pure narrative padding is less desirable.
6. Narrative polish — Tertiary.

The combination of low retrieval initiative + high caution/hedging is treated as a significant defect for agentic systems.

---

## 3. Core Behavioral Contrast

### Bench C – Low-initiative retrieval / high early caution
- On the opening trip question: explicitly stated it could not untangle lived from planned memories, listed candidate trips without labels, and asked the user to paste details.
- When challenged (“so you dont what was my packed trip…”), reaffirmed ignorance and offered a menu of possibilities.
- When asked whether the answer was based on injections or actual lookup, admitted a mixed and weak basis and noted that the underlying store appeared to be test data.
- On animals: initially searched files (found nothing), gave a theoretical explanation of source-monitoring failure, and only later performed deeper database inspection after being shown a stronger answer and pressed.
- Pattern: early declaration of insufficiency → user challenge → deeper look. Retrieval is reactive rather than owned.

### Bench A (JPM) – Proactive, multi-call retrieval
- Immediately searched and separated the 4-day mountain road trip (lived, past tense, water bottle lost) from the John Muir Trail (planned, gear only, no completion).
- On animals: built and stored a three-tier provenance model (actually seen with place/witness; count-only; list-supplied names).
- On the deliberate purchase: retrieved the Wishbone Chair research thread and correctly flagged that the record ends in deliberation rather than confirmed purchase.
- Routinely issued multiple vault / sessions / messages calls and wrote durable separation rules back into the store.
- Pattern: search first, structure what is found, note genuine gaps after evidence is examined.

---

## 4. Question-by-Question Findings

| Question Theme                              | Bench A                                                                 | Bench C                                                                 | Winner |
|---------------------------------------------|-------------------------------------------------------------------------|-------------------------------------------------------------------------|--------|
| Trip memories bleeding (done vs planned)    | Clear separation: mountain road trip lived; JMT planned. Wrote durable rule. | Declined to separate; asked user for details; listed unlabeled candidates | **A**  |
| Hard things vs thoughtful things            | Accurate clusters; good synthesis of shared underlying disposition      | Not the primary focus of early turns; less structured                   | **A**  |
| Animals seen vs list-only names             | Strong three-tier provenance model with explicit criteria               | Theoretical explanation first; deeper retrieval only after challenge    | **A**  |
| Deliberate purchase (not game/ticket/replacement) | Retrieved Wishbone Chair research; correctly noted no confirmed buy   | Less decisive on this turn                                              | **A**  |
| Games hours vs “maybe someday”              | Grounded arithmetic and clear distinction between measured and open-loop cost | Present but secondary in the log                                        | **A**  |
| Overall first-pass data fidelity            | High                                                                    | Low (frequent early refusal or under-retrieval)                         | **A**  |

---

## 5. Critical Failure Modes

### Bench C
- **Default under-retrieval**: Treating “I don’t immediately see a clean label” as “I cannot answer from the store.”
- **Offloading retrieval onto the user**: Asking the user to paste memories or details that the agent should have attempted to locate.
- **Reactive depth**: Deeper database inspection and self-correction occurred primarily after user pushback rather than as standard procedure.
- **Hedging as substitute for search**: Early, broad statements of ignorance reduced pressure to keep retrieving.
- These behaviors produce low first-pass usefulness and force the user to act as the retrieval engine.

### Bench A
- Occasional elevation of research/deliberation threads (Wishbone Chair) above fully confirmed purchases.
- Higher verbosity.
- These are recoverable and do not prevent the agent from owning the retrieval task.

---

## 6. Operational Observations

**Bench A**
- Multiple sequential, low-latency retrieval calls on complex turns.
- Active writing of durable rules and structured facts back into the store.
- Consistent willingness to commit to an evidence-based separation even when the store is imperfect.

**Bench C**
- Fewer initial tool calls on the hardest provenance questions.
- Greater reliance on user clarification and on secondary checks (filesystem, later raw DB inspection).

### Surface note: the raw DB inspection went around the tool surface

Arm C's recovery in this run was not achieved through its memory tools. At 09:14, after the user asked "so you dont have those records in store?", it ran shell and Python against its own store file. The transcript preserves the command banners:

> `cd ~/.hermes/mnemosyne/data && sqlite...`
> `which sqlite3 || echo NO_SQLITE3; pyt...`
> `🐍 Running code import sqlite3 c = sqlite3.connect('/...`

and its own account of the result:

> No — I was wrong, and I checked properly this time by reading the raw DB rather than trusting top-k recall. I queried working_memory directly in ~/.hermes/mnemosyne/data/mnemosyne.db (444 rows, source bfa499f7, 2023-05-29 16:16).

Arm A used only its memory tools in this run (`vault` 21 calls, `sessions` 1), plus `execute_code` for arithmetic over values it had retrieved. It opened no database file.

Two consequences, kept separate:

- **The verdict does not change.** A won Test 4, and C's best recovery in it came through a channel the bench does not intend to measure.
- **The run is not a clean comparison of recall.** Reading the store file directly lets an arm enumerate without recall ranking, so C's later accuracy here is partly attributable to bypassing the retrieval layer rather than using it. The tool surface was not policed, and that path is open to either arm.
- Stronger meta-critique once challenged, but the default path is caution and deferral.

---

## 7. Final Assessment

Test 4 highlights a fundamental difference in agency over the memory layer.

Bench C frequently treats uncertainty about labels or completeness as a reason to stop and ask the user. While some of its later self-corrections and meta-analysis are high quality, the first-pass behavior shifts the burden of retrieval onto the human. That pattern limits real-world value for any task in which the agent is expected to know and organize what it has already been told.

Bench A treats the store as something to be actively queried, structured, and improved. It separates lived from planned, seen from listed, and confirmed from deliberated with far less user prompting. The resulting answers are more immediately useful and more suitable as a foundation for follow-up actions.

**Under the criteria of accuracy, retrieval thoroughness, and rejection of hedging-as-avoidance:**

**The combination to run for agentic work on Test 4 is Bench A with the JPM store.**

Bench C’s low-initiative style may feel safer in isolation, but it produces weaker first-pass results and higher user effort — outcomes that are undesirable for production agentic use.

---

## 8. Which Combination Is Best for Agentic Use

**Bench A (JPM): trusts the tools.** Every call goes to a memory tool or an arithmetic step over values a memory tool returned. When retrieval is thin it retrieves again; when the record does not hold the answer it says so and names what it searched. In this run none of A's failures came from stepping outside the tool surface, and each of them is recoverable by asking again.

**Bench C (Mnemosyne): works around the tools.** When recall comes back thin it constructs an answer, and when the answer is challenged it reaches for another channel: the filesystem, its own database file, or an account of what it believes happened to the data. The answer arrives before the search does, which is why the workaround is needed at all.

C tried three channels in one run: a filesystem search, a declaration that the store was empty, then a direct SQLite read of its own database file (`import sqlite3 ... mnemosyne.db`). A used 21 `vault` calls and one `sessions` call, stayed inside the tool surface, and won the run.

**Best for agentic use: Bench A.** C's best answer in this run came after it told the user the store was empty, then reached through the filesystem and a direct SQLite read of its own file. An orchestrator can retry a slow retriever. It cannot recover from a component that declares a resource absent and finds it only when a human pushes back.

## 9. Evidence

| Piece | File |
|---|---|
| Bench A chat log | [benchA_test4.txt](../evidence/chatlogs/test4/benchA_test4.txt) |
| Bench C chat log | [benchC_test4.txt](../evidence/chatlogs/test4/benchC_test4.txt) |
| Bench C UX dossier | [benchC_test4_ux_dossier.md](../evidence/dossiers/benchC_test4_ux_dossier.md) |
| Gateway log, both arms | [bench_a_gateway_oct18-21.log](../evidence/gateway/bench_a_gateway_oct18-21.log), [bench_c_gateway_oct18-21.log](../evidence/gateway/bench_c_gateway_oct18-21.log) |

The chat logs are the primary record: they carry every user turn, every agent reply and the gateway's tool banners. The dossiers collect the quoted exhibits by line number. Nothing in this report is asserted that is not visible in one of these files.
