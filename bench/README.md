# bench/

A/B evaluation of **mea_pm** against a third-party memory plugin on an otherwise
identical stock Hermes harness. Every claim traces to a transcript or a log line.

## Seeded memory, live sessions

The memory is seeded, not accumulated. Both arms ingested the same LongMemEval
sessions before the run, so what each arm knows is identical at the start; the only
variable is how that memory is stored, indexed and retrieved.

Everything after the seed is live. A real user talks to both agents over Telegram in
real time, one conversation per arm, with compression firing under load and tools
called for real. That is the combination the published benches lack: LongMemEval as
shipped is headless, a fixed haystack queried in one shot, with no human, no
turn-to-turn drift and no compaction step.

## Questions rewritten to require tools

Stock LongMemEval items are simple lookups: one fact, one X-Y relation, one field.
Answering them rewards a lucky keyword hit. The items used here were rewritten to be
vaguer and multi-hop, so no single retrieval returns the answer: the arm has to decide
what to fetch next, cross-check it and reconcile dates that disagree. The bench is
therefore measuring tool use, that is, which arm reconstructs the answer from what it
can retrieve and how many steps that takes, not which arm guesses best.

That is also why the failure Test 6 caught is visible here at all: an arm whose
compaction dropped the very messages holding the answers, then reported the resulting
zeros as fact, cannot appear in a headless bench that never compresses anything.

The sample is small and part of the scoring is judgment, which is why criteria are
graded axis by axis and failure classes are named instead of collapsed into one number.

## Conclusive before the end

Test 4, the fourth scored run, settled the direction: the plugin arm was ahead on
accuracy, continuity and retrieval, and the control arm's edge was token cost. Test 5
and Test 6 confirmed that reading rather than deciding it.

## Arms

- **A** — `mea_pm`: stock harness plus this plugin.
- **C** — `mnemosyne`: stock harness plus a third-party memory plugin. The control.
- **B** — `hindsight`, retired 2026-10-18.

The memory provider is the only intended variable. Model, provider, base URL,
sampling, toolset and turn budget are held identical; a divergence there is a defect.

## Method

Both arms answer the same question set in the same window under the same load.
Questions in `questions/questions.txt` are vague, multi-source, multi-hop and
temporal, because those require retrieval rather than a lookup.

Scoring criteria, in priority order: accuracy, continuity after compression,
retrieval thoroughness, hedging quality, then noise and polish. The order is the
weighting. Token, cache and latency numbers are supporting observation, never the
verdict; an arm that is cheaper and wrong has not won.

Error classes are graded, not lumped. A recoverable over-inference and a confident
fabricated count are different defects.

## Reports

`reports/Test6_Evaluation_Report.md` is the criteria and the current result.
`reports/Test6_Run_Notes_20261020.md` holds the raw run notes behind it.

`reports/BenchA_vs_BenchC_Test4_Evaluation_Report.md` is retained in full, as
recorded on 19 October 2026, with both Test 4 chatlogs beside it. It prints its own
criteria ordering, which differs from Test 6's, so its findings stand alone: nothing
from Test 4 is carried into a Test 6 number, and no number from either is averaged,
summed or compared across the two.

Tests 1, 2, 3 and 5 were scored against earlier orderings and are not shipped.

## Evidence

```
bench/
├── README.md
├── questions/questions.txt
├── reports/
│   ├── BenchA_vs_BenchC_Test4_Evaluation_Report.md
│   ├── Test6_Evaluation_Report.md
│   └── Test6_Run_Notes_20261020.md
└── evidence/
    ├── chatlogs/
    │   ├── test4/  benchA_test4.txt  benchC_test4.txt
    │   └── test6/  benchA_test6.txt  benchC_test6.txt
    ├── agentlogs/  benchA_test6_agentlog.txt  benchC_test6_agentlog.txt
    ├── gateway/    bench_a_gateway_oct18-21.log  bench_c_gateway_oct18-21.log
    └── smoke/      smoke_a.log  smoke_c.log
```

Chatlogs are the primary evidence; the agent and gateway logs carry turn boundaries,
tool-call counts and compression events that a transcript cannot show. The gateway
files are the 2026-10-18 → 2026-10-21 window covering the runs, not the whole log.

**Test 4 has no agent logs.** None were kept for that run, so the directory holds the
report and the two chatlogs only. The chatlogs cover one 09:06–09:26 window with
unequal turn counts per arm, so per-turn comparisons there are not paired.

The harness that drove the gateways is not shipped: it needs live arm homes, a model
endpoint and a scratch PostgreSQL, so a bundled runner could not work elsewhere. The
method is reproducible, not the command.

## Known limits

- **n is small.** A handful of questions. Report error counts, not score deltas.
- **Not every cited file ships.** `agent.log`, `gateway.log` and the seeded personal
  markdown files live in the arm homes; the excerpts here are windows cut from them.
- **Compression differs architecturally,** so latency comparisons are partly
  compression strategy, not recall quality.
