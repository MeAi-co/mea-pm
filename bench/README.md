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

Two runs add a hint: Test 3 opens with an instruction to use the memory tools, and Test 4 carries one mid-run after the control arm had already declared its store empty. Both are disclosed in the reports that use them, because an instruction to retrieve cannot be evidence about whether an arm retrieves on its own. Tests 1 and 2 have no such line, and both arms searched on their first question regardless.

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

- **Bench A** — stock Hermes + MEA plugins + PostgreSQL + embeddings.
- **Bench C** — stock Hermes + Mnemosyne + embeddings. The control.

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

Hard errors are tallied per run, never across the block. Tests 1 to 3: **A 0, C 6**,
where C's six are two wrong purchase items, two omissions of a finished game's hours,
one fabricated premise used as the basis for arithmetic, and one item asserted as
bought when the thread only says it is being considered. Test 6 records **A 1, C 3**:
A abandoned a correct answer under pressure, C produced two false counts and one
false causal explanation. Tests 4 and 5 are graded on the criteria above and are not
tallied here.

## Reports

`reports/Test6_Evaluation_Report.md` is the criteria and the current result.
`reports/Test6_Run_Notes_20261020.md` holds the raw run notes behind it.

`reports/BenchA_vs_BenchC_Test4_Evaluation_Report.md` and
`reports/BenchA_vs_BenchC_Test5_Evaluation_Report.md` are retained in full, as
recorded on 19 October 2026, each with both of its chatlogs beside it.

`reports/BenchA_vs_BenchC_Test1_Evaluation_Report.md`,
`reports/BenchA_vs_BenchC_Test2_Evaluation_Report.md` and
`reports/BenchA_vs_BenchC_Test3_Evaluation_Report.md` follow the same form and each
has both chatlogs beside it.

Test 5 applies the same criteria ordering as Test 6 and reaches the same conclusion.
Test 4 prints an earlier ordering, with retrieval thoroughness ahead of continuity, so
its findings stand alone. Nothing is averaged, summed or compared across tests: each
report carries its own numbers and its own conclusion, and no figure migrates from one
to another.

Tests 1, 2 and 3 were originally judged on matrices of their own and left no
`*_TestX_Evaluation_Report.md` behind, so their reports here are reassessments
written from the retained chatlogs under the criteria Test 6 states. Each one says
so at the top and carries no number from its original scoring.

All three sit in the pre-compaction window: no compaction fires inside those
conversations, apart from one recompact launched mid-run by arm A in Test 3.
Continuity is therefore scored there on referent drift across turns, and they cannot
speak to behaviour after a context rebuild. That evidence starts at Test 4.

The chatlogs for Test 3 were shipped with the arms swapped in the original export.
They are relabelled here by reply identity, so the A file holds A's transcript and
A's gateway log. Any earlier reading of that test has the arms inverted.

A wins all six runs, and the reports keep each one apart rather than averaging them
into a total. Test 3 is the closest: C's provenance work there is the best in the
block, and it still loses the run by writing an intention into the record as a
completed purchase.

`reports/Cross_Test_Consistency_Report.md` is the one document that reads across all
six. It does not average them: it states what stayed constant in arm A's operating
mode across every run, and attributes the answer deviations to the deliberately
vague question set rather than to instability in the arm.

`reports/BenchC_UX_Dossier.md` audits the control arm as a user-facing tool rather
than as a score: denials of existence issued before any lookup, the same denial
extended to its own transcript after compression, tone on repeat questions, and the
context weight its approach carries. It is built from the six Bench C chatlogs with
line-numbered quotes, and it states where its case does not hold, including one test
where the defects are absent.

Every report ends the same way: a section stating which combination is best for
agentic use in that run and why, followed by an evidence index linking the chat
logs, agent logs, gateway traces and dossiers behind it. Across the six, the answer
is Bench A — stock Hermes + MEA plugins + PostgreSQL + embeddings, stated in `reports/Cross_Test_Consistency_Report.md`
along with the one run where the plugin arm did better.

## Evidence

```
bench/
├── README.md
├── questions/questions.txt
├── reports/
│   ├── BenchA_vs_BenchC_Test4_Evaluation_Report.md
│   ├── BenchA_vs_BenchC_Test5_Evaluation_Report.md
│   ├── Test6_Evaluation_Report.md
│   ├── Test6_Run_Notes_20261020.md
│   ├── Cross_Test_Consistency_Report.md
│   └── BenchC_UX_Dossier.md
└── evidence/
    ├── chatlogs/
    │   ├── test1/  benchA_test1.txt  benchC_test1.txt
    │   ├── test2/  benchA_test2.txt  benchC_test2.txt
    │   ├── test3/  benchA_test3.txt  benchC_test3.txt
    │   ├── test4/  benchA_test4.txt  benchC_test4.txt
    │   ├── test5/  benchA_test5.txt  benchC_test5.txt
    │   └── test6/  benchA_test6.txt  benchC_test6.txt
    ├── dossiers/   benchC_test1..test6_ux_dossier.md
    ├── agentlogs/  benchA_test6_agentlog.txt  benchC_test6_agentlog.txt
    ├── gateway/    bench_a_gateway_oct18-21.log  bench_c_gateway_oct18-21.log
    └── smoke/      smoke_a.log  smoke_c.log
```

Chatlogs are the primary evidence; the agent and gateway logs carry turn boundaries,
tool-call counts and compression events that a transcript cannot show. The gateway
files are the 2026-10-18 → 2026-10-21 window covering the runs, not the whole log.

**Only Test 6 has agent logs.** None were kept for Tests 4 and 5, so those directories
hold a report and two chatlogs each. The Test 4 chatlogs cover one 09:06–09:26 window
with unequal turn counts per arm, so per-turn comparisons there are not paired; Test 5
runs 15 turns per arm.

The harness that drove the gateways is not shipped: it needs live arm homes, a model
endpoint and a scratch PostgreSQL, so a bundled runner could not work elsewhere. The
method is reproducible, not the command.

## Known limits

- **n is small.** A handful of questions. Report error counts, not score deltas.
- **Not every cited file ships.** `agent.log`, `gateway.log` and the seeded personal
  markdown files live in the arm homes; the excerpts here are windows cut from them.
- **Tool surfaces were not policed.** One control-arm run read its own store file
  directly with SQLite instead of using its memory tools; the report for that run
  discloses it. Arithmetic in code happened on both arms and is not a defect.
- **Compression differs architecturally,** so latency comparisons are partly
  compression strategy, not recall quality.
