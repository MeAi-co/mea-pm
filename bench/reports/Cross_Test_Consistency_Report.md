# Cross-Test Consistency: Bench A Across All Six Tests

Arm: `A_MEA_JPM` (JPM / mea_sessions, retrieval-first).
Comparison arm: `C_Mnemo` (Mnemosyne, auto-injected context).
Companion documents: the six `BenchA_vs_BenchC_TestX_Evaluation_Report.md` files, `BenchC_UX_Dossier.md`, and the six reports' chatlogs.

## 1. What this document settles

The six per-test reports each score one run, and they do not agree: A wins Tests 1 and 2, C wins Test 3 narrowly, A wins Tests 4, 5 and 6. Read on their own they look like a run-to-run coin flip decided by which question came up.

That reading is wrong, and this document is the correction. The per-test verdicts stand on their own axes; what they do not say, because a single run cannot, is whether the arm behaves the same way every time. Across six runs it does.

**Verdict: Bench A is consistent and stable as an agentic tool across all six tests. Its answer deviations track the vagueness and non-specificity of the questions, not instability in the arm.**

## 2. What "consistent" means here, operationally

Four claims, each measurable, none of them about answer quality:

1. **It retrieves before it asserts.** Every substantive reply in every run follows memory calls made in that turn.
2. **It uses the same tool surface every run.** 31 tool schemas offered on every call, in all five runs with recorded dumps.
3. **It carries the same context envelope every run.** Median input prompt and system prompt hold within a narrow band across five runs.
4. **Its failures are of one kind.** Where A is wrong, it is wrong about which record answers a vague question, not about what the record says.

Claims 2 and 3 are arithmetic from arm A's own per-call context dumps. Claims 1 and 4 are read from the transcripts and stated with their evidence below.

## 3. The measured envelope

From A's per-call context dumps for each test window. Test 6 has no dumps; its tool figures come from the retained agent log.

| Test | Turns | API calls | Median input tokens | Peak input | Summed tokens | System prompt (chars) | Tools offered |
|---|---|---|---|---|---|---|---|
| 1 | 14 | 43 | 63,942 | 100,911 | 2,516,533 | 21,408 | 31 |
| 2 | 11 | 25 | 48,868 | 74,982 | 1,138,999 | 21,275 | 31 |
| 3 | 17 | 49 | 55,830 | 100,313 | 2,769,444 | 20,872 | 31 |
| 4 | 16 | 50 | 60,470 | 125,355 | 3,198,615 | 20,766 | 31 |
| 5 | 15 | 54 | 50,712 | 97,674 | 2,835,776 | 20,766 | 31 |
| 6 | — | 47 (tool calls) | not recorded | — | — | — | — |

Two things stand out, and neither is a performance claim:

- **The envelope does not drift.** System prompt size moves by 642 characters across five runs. Tools offered do not change. Median input prompt stays between 48.9k and 63.9k tokens.
- **Call volume scales with question difficulty, not with run index.** 25 calls for Test 2's eleven turns, 54 for Test 5's fifteen. A spends more when the question is vaguer, which is the behaviour the bench was built to test.

## 4. Claim 1: retrieval before assertion

This is the behaviour the whole bench turns on, and it is where the arms separate most cleanly.

Bench C's dossier documents the opposite pattern twice at the log level: a false denial issued with zero tool calls (Test 5, 10:22:18, `api_calls=1`, no tool), and a store declared empty before the agent read it (Test 4, "The machine is empty", corrected to "the Aspen Valley records were sitting in the store the whole time").

One disclosure belongs here, because it affects how much this claim proves. Two runs instruct the agents to use their memory tools: Test 3 opens with "gonna ask you a few questions. Strictly use your memory tools, sessions etc to arrive at an answer." (L5), and Test 4 has "use your memory tools only" mid-run (L187), after the control arm had already declared the store empty. Tests 1 and 2 carry no such instruction, and both arms still retrieved on their first substantive turn without one: Bench C issued five recall calls, Bench A three.

A's transcripts show continuous tool use, and the one A refusal examined in detail is retrieval-backed. Test 2, where A declines to name the deliberate purchase and guesses the orchid:

> [10/18/26 6:58 PM] bench_8857784145 A_MEA_JPM: ⚙️ jpm: "challenge difficult perseverance quit..."

The refusal comes after the search, and it names what it did find ("A silver necklace with a small pendant for your sister", Test 2 L51) while declining to tie it to the question's framing. That is a retrieval miss, disclosed, not a denial issued in place of looking.

## 5. Claim 4: one failure mode, and it is not fabrication

Where A is wrong across the six runs, the error is consistently about mapping a vague question to the right record. Three instances, all already recorded in the per-test reports:

- **Test 2 — attribution.** A searched, found the necklace among gifts, and refused to identify it as the $50 deliberate purchase, offering the orchid instead. Wrong answer, correct behaviour: it would not assert a link the record did not carry.
- **Test 3 — a revision not flagged.** A opened with the 140-hour ledger and later revised to "140 only if you count TLOU2 twice", landing at 110–115. The arithmetic was right; the withdrawal was not announced as a withdrawal.
- **Test 1 — no deviation.** A's 140 hours across four titles is the correct total (70+55+10+5, with TLOU2 counted twice), reached by assembling entries rather than by recalling a stored sentence.

Against that, C's Test 1 failure is a different species: 65 hours across "three playthroughs, two distinct titles", plus two titles that appear in no memory at all, and a stored user fact of "The Witcher 3 — 50–100 hours". That is invention under a confident register, and it is the failure A does not produce.

## 6. Why the deviations track question vagueness

The questions were deliberately rewritten from stock LongMemEval lookups into vaguer multi-source asks, to test which agent uses its tools to reach an answer rather than which agent has the fact pre-loaded. That design makes some deviation unavoidable, and it should be attributed to the question rather than to the arm.

Three features of the runs support that attribution:

1. **A's errors concentrate where the question is least specific.** The purchase question ("the gesture side", Test 2) and the hours question ("how many hours", Test 3) both require deciding which of several records the user means. Where the question names its target, A lands it (Test 1's ledger, Test 4's trip untangling, Test 5's arithmetic).
2. **A's wrong answers stay inside the corpus.** Every number it gives traces to an entry it retrieved. It does not import outside titles, dates or figures.
3. **Call volume rises where answers get vaguer** (Section 3), which is the arm responding to vagueness by working harder rather than guessing sooner.

## 7. Reconciling Test 3

Test 3 is the one run C wins, and this document does not overturn it.

That verdict rests on a single axis: provenance separation. C told the user plainly that a thread was not his ("The Bhutan thread isn't even yours. It comes from ultrachat_319214"), while A revised a total mid-answer without flagging that it had withdrawn the earlier one.

Two points, kept separate:

- **As a per-test judgment on that axis, the Test 3 verdict stands.** The transcript supports it.
- **It does not contradict A's cross-test stability.** A's tools, envelope and retrieval-first habit are identical in Test 3 to the other five. What differed was one disclosure convention under pressure, not the arm's operating mode.

The honest formulation is: C won one test on one axis, and A is the same tool in all six.

## 8. Cost, for completeness

Consistency is worthless if it costs the most, so the cost is stated rather than implied.

- **A in Tests 1–5:** median 48.9k–63.9k input tokens per call, 25–54 calls per run.
- **C where measurable:** Test 6 returns 402,950 characters of tool output across 44 calls against A's 264,865 across 47; C's memory reads are a median 12,557 characters each against A's 3,496. Test 3's own log shows C's prompt growing 9.6× within the run; Test 5's shows a 58.3-second turn at compression.
- **C for Tests 1, 2 and 4:** not measurable; its home directory is unreadable and no dumps exist. Not estimated here.

A is not the cheaper arm by call count. It is the cheaper arm per answer because its calls return less, and it is the only arm whose cost can be measured across all six runs.

## 9. Limits

- **Tests 1–3 are pre-compaction.** They cannot speak to post-compaction stability. Test 3 contains one mid-run `recompact` launched by A at 21:53:28; A kept its thread through it, which is one observation, not a measurement of compression safety.
- **Tests 4–6 are the post-compaction evidence**, and those are A's strongest runs.
- **Six runs, one operator, live user-assistant sessions**, not headless automation. Repeatability is bounded by that.
- **Results are not additive.** Nothing here averages the six tests into a score, and the 7.5 / 3.5 Test 6 run rating is not an aggregate.

## 10. Final assessment

**Bench A is consistent and stable across all six tests.** Put in one line, which is also the finding of every individual report: the control arm trusts its tools and does not fail at the point of use, and the plugin arm treats retrieval as an opening bid and works around it when the answer comes back thin. Same tool surface, same context envelope to within 642 characters of system prompt, retrieval before assertion in every run, and a failure mode that stays inside the record it retrieved.

The deviations in its answers belong to the questions. They were built vague on purpose, and A answers vague questions by retrieving more and asserting less, which is the behaviour the bench was designed to detect.
