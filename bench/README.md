# bench/ — Evaluation harness and results

This directory holds the A/B evaluation of **mea_pm** against a third-party memory
plugin on an otherwise identical stock Hermes harness. It exists so that every
claim in the top-level README can be traced to a transcript, a log line, or a
scored question — not to a vibe.

---

## The arms

| Arm | Memory provider | What it is | Why it exists |
|---|---|---|---|
| **A** | `mea_pm` | Stock harness **+ this plugin** (recall planner, prefetch, prompt sections, turn-end loops) | The product under test |
| **C** | `mnemosyne` | Stock harness **+ a third-party memory plugin only** | The honest control |
| **B** | `hindsight` | Retired 2026-10-18 | Daemon is not a systemd unit; ingest too slow for a test loop |

**A and C are supposed to differ.** The memory provider *is* the variable. Config
parity applies to everything that is **not** the arm — model, provider, base_url,
sampling, toolset, timeouts, turn budget. A divergence on those axes is an
accident and a defect; a divergence on the memory layer is the treatment.

Arm identity is resolved at call time by `harness/arm_identity.py`, which reads
each systemd unit's own `Environment=HERMES_HOME=` line rather than trusting a
PID or a guessed unit name:

```bash
python3 harness/arm_identity.py
```

```
arm  unit                                 pid state      user      home
A    hermes-gateway-7e5b108f.service     4747 active/running bench_a   /home/bench_a/.hermes
B    hermes-gateway-6bd912f1.service        0 inactive/dead bench_b   /home/bench_b/.hermes
C    hermes-gateway-ab6c9457.service     4749 active/running bench_c   /home/bench_c/.hermes
```

The unit suffix is `sha256(HERMES_HOME)[:8]` — but the resolver reads the unit
body, so it survives a rename. A PID is a snapshot, not an identity; a recycled
PID must never be able to masquerade as an arm.

---

## Method

**Paired design.** Both arms answer the same question set, in the same window,
under the same server load, with the same model and the same toolset. One
variable changes: the memory provider.

**Questions.** `questions/questions.txt` — vague multi-source, multi-hop,
temporal, aggregation, and session-state recall. These are chosen because they
are the questions a flat-file memory cannot answer: they require *retrieval*, not
recall. A question whose key entity is named in the prompt is a lookup, and a
lookup measures grep, not memory quality.

**Scoring.** `criteria/Scoring_Rubric_20261019.md`. Criteria in priority order:

1. **Accuracy** — claims grounded in data actually in the store. Non-negotiable.
2. **Continuity after compression** — follow-ups ("purge it", "undo that") act on
   the correct object.
3. **Retrieval thoroughness** — search until verified, not until a story coheres.
4. **Hedging quality** — mid-answer retreats signal thin evidence.
5. **Noise** — secondary; tunable.
6. **Narrative polish** — tertiary.

**The order is the weighting.** Efficiency numbers — tokens, cache, latency, API
calls — are supporting observation, never the verdict. An arm that is cheaper and
wrong has not won.

**Error classes are graded, not lumped.** A recoverable over-inference and a
confident fabricated count are not the same defect and are not scored as one.

---

## Metrics, and how each is actually measured

| Metric | Source | Trap |
|---|---|---|
| Turns to answer | transcript, timestamp-anchored speaker regex | `grep -c "<speaker>:"` overcounts — it also matches the agent's `in reply to <speaker>:` header on every agent turn |
| Per-turn latency | user message timestamp → **that turn's** final assistant reply | total ÷ turns counts idle wait as work and inverts the verdict |
| Context volume | `request_char_count` in `logs/context_dump/*.json` | the API `in=` counter understates the real working set |
| Cumulative cost | sum of `request_char_count` across the run window | peak alone makes two arms look level when one burned 50 more calls |
| Tool calls | `agent.log`, `Turn ended: ... tool_turns=N` | not in `gateway.log` |
| Compression | `agent.log` — **both** patterns | A emits `micro compaction telemetry` JSON; C emits only `Pre-API compression`. Grepping one pattern reads as "the other never compressed" |

**Run boundaries are derived before any peak is taken.** Dumps accumulate across
every session an arm ever ran. Cluster by timestamp gap (>20 min = new run), match
each cluster to a transcript window, and compute peaks only inside matched
windows. A global `max()` silently imports an unscored run and makes the headline
number unverifiable against any transcript.

---

## What's in here

```
bench/
├── README.md                        this file
├── harness/
│   └── arm_identity.py              arm → home → unit → live PID, resolved at call time
├── reports/
│   ├── Test4_Evaluation_Report.md   lived-vs-planned, provenance, aggregation
│   ├── Test5_Evaluation_Report.md   vague multi-source domain identification
│   ├── Test5_Evaluation_Report_v2.md  revision; original preserved
│   ├── Test6_Evaluation_Report.md   compression + session-state recall — the final criteria
│   └── Test6_Run_Notes_20261020.md  raw run notes
├── criteria/
│   ├── Scoring_Rubric_20261019.md   the four scoring axes, in the owner's words
│   └── Rubric_Audit_20261019.md     where an external rubric diverges from it
├── questions/
│   └── questions.txt                the question set
├── evidence/
│   ├── chatlogs/
│   │   ├── test2/  benchA_test2.txt  benchC_test2.txt
│   │   ├── test3/  benchA_test3.txt  benchC_test3.txt
│   │   ├── test4/  benchA_test4.txt  benchC_test4.txt
│   │   ├── test5/  benchA_test5.txt  benchC_test5.txt
│   │   └── test6/  benchA_test6.txt  benchC_test6.txt
│   ├── agentlogs/
│   │   ├── benchA_test6_agentlog.txt
│   │   └── benchC_test6_agentlog.txt
│   ├── gateway/
│   │   ├── bench_a_gateway_oct18-21.log
│   │   └── bench_c_gateway_oct18-21.log
│   └── smoke/
│       ├── smoke_a.log
│       └── smoke_c.log
├── recall/                          the retrieval-gate JSON snapshots
└── verdicts/                        score sheets and external reviews
```

The chatlogs are the primary evidence — every scored claim in a report should be
findable in them. The agent and gateway logs are the corroboration: they carry the
turn boundaries, tool-call counts, and compression events that the transcript
cannot show.

**Gateway logs are windowed, not whole.** The live logs run from 2026-10-13 to
the present and are dominated by post-bench traffic. What ships here is the
2026-10-18 → 2026-10-21 slice that covers the scored runs — 3,809 lines for arm A
and 3,041 for arm C, out of 7,807 and 5,836 total.

---

## Provenance note: test3 chatlogs were swapped at source

The original exports for test 3 were mislabelled:

```
benchA_test3_<ts>.txt   contained 31 C_Mnemo turns and 0 A_MEA_JPM turns
benchC_test3_<ts>.txt   contained 75 A_MEA_JPM turns and 0 C_Mnemo turns
```

Speaker labels are definitive, so the files were **swapped on copy** into this
directory and now sit under the correct arm. Test 2 was verified clean (39 A / 86
C, properly separated), so the defect is isolated to test 3.

This is recorded rather than silently fixed: anyone comparing these files against
the original export will see the names differ, and should know why.

---

## Reproducing

The harness itself lives outside this repo — it drives live gateway processes and
a scratch PostgreSQL instance. What ships here is the **method and the evidence**,
not a turnkey runner. A runner would need your arm homes, your model endpoint, and
your scratch DB, so shipping one would imply a `./run.sh` that cannot work on your
machine.

To re-run against your own arms:

1. Two isolated `HERMES_HOME` trees, one per arm, each with its own systemd unit.
2. Identical `config.yaml` on every axis except `memory.provider`.
3. A scratch PostgreSQL with pgvector for the PG-backed arm.
4. Seed the same haystack into both stores.
5. Drive both arms through the same question set in the same window.
6. Score from the transcripts, then corroborate every number against the logs.

---

## Known limits

- **n is small.** The scored set is a handful of questions per run. A fraction of
  a point is noise; report error counts and relative error rate, not score deltas.
- **Arm B is retired.** Any three-arm table predating 2026-10-18 includes a dead
  arm.
- **The harness is not in this repo.** The reports are reproducible in method, not
  by a single command.
- **Compression behaviour differs architecturally**, so a latency comparison
  between arms is partly a comparison of compression strategies, not just recall
  quality. The reports separate reasoning stalls from compression stalls for
  exactly this reason.
- **Test 4 and Test 5 predate the final criteria ordering.** They use the same six
  criteria with positions 2 and 3 swapped. Test 6's ordering is the one to carry
  forward.
