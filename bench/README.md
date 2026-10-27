# bench/

A/B evaluation of **mea_pm** against a third-party memory plugin on an otherwise
identical stock Hermes harness. Every claim traces to a transcript or a log line.

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

## One scored run

`reports/Test6_Evaluation_Report.md` is the criteria and the result. Tests 1–5 were
calibration on an earlier criteria ordering; their scores are stale and are not
shipped.

`reports/Test6_Run_Notes_20261020.md` holds the raw run notes behind that report.

## Evidence

```
bench/
├── README.md
├── questions/questions.txt
├── reports/
│   ├── Test6_Evaluation_Report.md
│   └── Test6_Run_Notes_20261020.md
└── evidence/
    ├── chatlogs/test6/   benchA_test6.txt  benchC_test6.txt
    ├── agentlogs/        benchA_test6_agentlog.txt  benchC_test6_agentlog.txt
    ├── gateway/          bench_a_gateway_oct18-21.log  bench_c_gateway_oct18-21.log
    └── smoke/            smoke_a.log  smoke_c.log
```

Chatlogs are the primary evidence; the agent and gateway logs carry turn boundaries,
tool-call counts and compression events that a transcript cannot show. The gateway
files are the 2026-10-18 → 2026-10-21 window covering the run, not the whole log.

The harness that drove the gateways is not shipped: it needs live arm homes, a model
endpoint and a scratch PostgreSQL, so a bundled runner could not work elsewhere. The
method is reproducible, not the command.

## Known limits

- **n is small.** A handful of questions. Report error counts, not score deltas.
- **Not every cited file ships.** `agent.log`, `gateway.log` and the seeded personal
  markdown files live in the arm homes; the excerpts here are windows cut from them.
- **Compression differs architecturally,** so latency comparisons are partly
  compression strategy, not recall quality.
