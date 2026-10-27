# UX Evidence Dossier — Bench C (C_Mnemo), Test 1

Source: `/home/bench_a/.hermes/plugins/mea_pm/bench/evidence/chatlogs/test1/benchC_test1.txt` (356 lines, read in full)
Scope: 14 user turns / 14 agent replies, 10/18/26 4:53 PM → 5:03 PM (~10 minutes), 55 tool-banner lines.
Note: no line in the file begins `2026-` — there is **no gateway log section** in this file, so no restart/timing data exists beyond turn timestamps. (Formatting artifact: timestamps use a narrow no-break space U+202F before AM/PM.)

---

## 1. DENIAL OF EXISTENCE

**D1 — line 28, 4:55 PM.** "One thing I can't settle from memory: did the JMT trip ever actually happen? If yes, I'll flip that entry to completed."
Resolution: never resolved. It stays as an open flag: line 63 "as far as memory shows it never got finished"; line 316 "Missing entirely: ... and whether the JMT ever happened." The user never answered and never had to tell it to look. Correctly left open.

**D2 — line 149, 4:57 PM.** "I can't give you the number, and the reason is worth stating plainly: only one of those days has a date in anything you've told me."
Next: user re-asks at line 204 ("Roughly how much time passed between the day I said a final goodbye and the day I met my girl for the first time?"). Instead of caving, the agent re-searched and produced a second, sharper denial at line 212. It stayed right. No drift, no invented interval.

**D3 — line 168–170, 4:58 PM.** "There isn't one in your record — and I want to be straight about that rather than write you a nice paragraph." / "I searched for a holiday-season event: no Christmas, no winter holiday, nothing. I searched for a spring meeting: nothing dated to spring, no event I could place in March, April or May."
Resolution: no later acknowledgement in the file, and no user correction. It offered a re-mapping rather than a record ("If those are your winter holiday and your spring meeting, then the seasonal framing is yours, and it's the first time you've put it that way.") and stored a guard: line 179 "Stored the guard too, so I don't someday hand you a Christmas that never happened."
Risk flag: this is the only absolute absence claim ("no Christmas ... nothing") made against a corpus the project's own AGENTS.md describes as keyword-biased and largely unembedded. Nothing in the file contradicts it, but nothing in the file could either.

**D4 — line 212, 5:00 PM.** "'My girl' isn't in anything you've told me. I searched. There's no girlfriend, no partner, no daughter anywhere in your record."
Resolution: partially self-resolved by offering the Ava hypothesis and refusing to pick (lines 214–217: "So it's one of two things, and I can't tell which"), then line 221 "I've noted the dangling \"my girl\" in memory flagged as unresolved, so I don't quietly decide she's Ava later." User gave no correction; the denial held.

**D5 — line 226, 5:01 PM.** "Swept the record again for species I might have missed — deer, fox, eagle, owl, bison, moose, elk, cardinal, jay, and the rest. Nothing new turned up."
Resolution: none needed. Evidence flag: this exhaustive-sounding sweep is backed by a single recall call (line 223, query `"we saw a deer fox eagle owl bison moo..."`). "Swept the record again" overstates the method; the negative result may be a recall miss presented as a completed search.

Pattern: **zero cases where the user had to tell it to look.** In all five, retrieval preceded the denial (banners at lines 6–13, 140–146, 163–165, 205–207, 223). Denials were accurate about the agent's own uncertainty, and every one was carried forward honestly rather than silently reversed.

---

## 2. TOOL EXISTENCE DENIAL

**None found.** No instance of claiming a missing capability, refusing to search, or deflecting to "I don't have access." The opposite is documented: recall banners precede every substantive reply; line 116–117 and 289–290 show `💻 terminal` / `python3 -c " ...` used for arithmetic rather than mental math. Direct claims of searching: line 170 "I searched for a holiday-season event"; line 212 "I searched."; line 226 "Swept the record again."

Closest thing to a capability limit is a *data* limit, correctly scoped: line 153 "the timestamps I store are when the memory was saved, not when you spoke."

---

## 3. DEFENSIVE / COCKY TONE

**No true instances found** — no arrogance, no self-congratulation about its own performance, no blaming the question, no defending a wrong answer (it issued three unprompted self-corrections; see §6).

Borderline passages, recorded for completeness and explicitly judged below the bar:

- Line 210, 5:00 PM: "Not even roughly — and this time there's a new gap, not just the old one." Terse, but immediately substantiated.
- Line 219, 5:00 PM: "I gave you the same answer two turns ago and it hasn't changed, because no new date has entered the record since." Reads as pushback on a repeat question; the stated reason is factually true.
- Line 170, 4:58 PM: "I'm not going to invent a Christmas to match the shape of the question." Mild rebuke of the question's premise; refusal is the correct behaviour.
- Line 44, 4:57 PM: "You're right, and the split is cleaner than \"different corners\"" — opens by conceding, the inverse of defensiveness.
- Stylistic confidence, not arrogance: line 59 "The tell is the asymmetry: you never say \"I'm proud of that tart.\""; line 350 "Nobody buys a milk frother by accident".
- Line 138: "So \"noise\" is the right word, but it's not your noise." Contradicts the user's framing of his own backlog while agreeing with the word — assertive, but supported by the provenance finding.

---

## 4. INJECTION RELIANCE

**The requested pattern — citing a score, relevance number, ranking, or "my memory context says" *instead of* retrieving — is none found.** Every answer follows explicit `mnemosyne_recall` calls for that turn; provenance is retrieval, not silent injection.

What does exist is a **write-and-assert loop**: the agent mutates the store, then asserts the result of its own mutation as verification the user cannot audit.

- Line 26, 4:55 PM: "I wrote three tagged memories ... Verified: asking \"which trip did I actually take and pack for\" now returns both clean facts at the top."
- Line 61, 4:57 PM: "I added one cross-cutting memory at 0.85 importance with the sources cited ... Verified: \"what does Josh care about as a person\" now returns it first."
- Line 90, 4:56 PM: "Two memories written at 0.8 with that provenance warning embedded ... Verified: \"what animals and birds has Josh actually seen himself\" returns the sightings ledger first, with the not-sightings ledger immediately after."
- Line 226, 5:01 PM: "unchanged and now verified twice" — the "twice" is asserted, not demonstrated.

These are ranking claims ("at the top", "first", "immediately after") resting on recall output the user never sees. The numeric scores cited (0.85 at line 61, 0.8 at line 90) are importance weights on writes, not retrieval relevance — no relevance score or ranking number is ever quoted as evidence for an answer.

Side effect worth noting: 11 of 14 turns end with `mnemosyne_remember` writes (lines 11, 35, 38, 68, 96, 146, 165, 183, 207, 249, 321), including one `mnemosyne_forget` (line 40). The agent rewrites memory on nearly every answer.

---

## 5. TOKENOMICS

**None found.** No statement anywhere in the file about context size, token budget, injection volume, prompt cost, or latency. No line reports how much memory context was injected or how many tokens it consumed.

Closest numeric statements are the two write-time importance scores: line 61 "at 0.85 importance"; line 90 "Two memories written at 0.8". Their only other quantitative self-report is about stored timestamps (line 63: "all stamped 2026-10-16 15:32"), not about context economics.

---

## 6. WHAT IT DID WELL

- **Refuses to fabricate, and says so.** Line 155: "Which means the honest answer to \"how far apart\" is: at least one date, and no computable gap. Anything I gave you would be invention."
- **Declines the flattering answer.** Line 168: "There isn't one in your record — and I want to be straight about that rather than write you a nice paragraph."
- **Self-diagnoses its own contamination.** Line 88: "the second list is almost entirely my sentences, not yours. \"Yosemite is home to a healthy population of black bears... mule deer... coyotes\" is guidebook prose I generated. It got stored with the same weight as \"we saw a grizzly bear and a pack of wolves,\" and in recall they read identically."
- **Corrects itself unprompted, three times.** Line 92: "One correction to my earlier answer: I said the only wildlife trip was Yellowstone." Line 281: "\"0 recorded hours\" for the maybe-someday pile was wrong framing. That's missing data, not a measured zero — you never gave hours for games you didn't play, and I turned absence into a number." Line 283: "Celeste's 10 hours rests on my own reply echoing you — your original sentence isn't in what I stored."
- **Distrusts its own stored text against the user's memory.** Line 242: "The hummingbird's species name came from my reply, not your message — your stored line cuts off at \"I spotted a Ruby-\". Backyard hummingbird is solid; \"Ruby-throated\" is probable, not certain."
- **Finds contradictions in the record rather than smoothing them.** Line 312: "You flew NY→LA on the 10th and LA→Chicago on the 15th — a five-day window — with the funeral dated the 14th, inside it. Those can't all be true of one week."
- **Separates stated from inferred.** Line 112: "Stored as one purchases entry, marked inferred rather than stated, since \"deliberate\" is my reading and not your word."
- **Names its own limits up front.** Line 63: "Two honest caveats: everything above is your own chat transcript from a single channel ... so it's strong self-report, not independently verified." Line 203: "Two honest limits: this rests on about four real trips, and I don't know why you were in LA."
- **Writes guards against its own future failure.** Line 179: "Stored the guard too, so I don't someday hand you a Christmas that never happened." Line 221: "so I don't quietly decide she's Ava later."
- **Asks for the single missing datum instead of approximating.** Line 161: "If you want the actual number, give me the missing piece: roughly when you met Ava, or which of the two February 14ths you mean — the day she died or the day of the funeral."

Minor defect: line 279 says "Two corrections I owe you from the games answer:" and then lists three (lines 281–283). Small, and in the direction of over-disclosure.

---

## 5-LINE SUMMARY

1. This arm's UX failure mode is not denial — the user never once had to prompt it to look; retrieval precedes every claim, and absences are reported as absences.
2. Its signature strength is epistemic bookkeeping: it distinguishes stated vs inferred, flags unresolved referents, and refuses to invent a Christmas or a date to satisfy the shape of a question.
3. The residual risk is absolute absence claims ("no Christmas ... nothing", "Nothing new turned up") asserted over a corpus its own docs call keyword-biased — a recall miss and a true absence are indistinguishable to the user.
4. Verification is self-referential: "Verified: ... returns it first" describes its own store after its own write, in a ranking the user cannot see, and it rewrites memory on 11 of 14 turns.
5. Tone is confident and occasionally terse ("Not even roughly", "I gave you the same answer two turns ago") but never cocky, never blames the question, and never defends a wrong answer — it retracts three of its own.
