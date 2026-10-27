# Bench C (C_Mnemo) — Test 2 UX Evidence Dossier
Source: benchC_test2.txt L1–L301 (transcript). L303–L487 are gateway log and are excluded from behaviour claims.
Session: 18 Oct 2026, 6:57 PM – 7:03 PM, single session (started by `/reset`, L1–L4). 11 assistant turns.

## 1. DENIAL OF EXISTENCE

**1.1 "No memory of the day you met anyone" — never resolved.** (turn 7:01 PM, header L137)
- L143: "The meeting isn't dated at all. There is no memory of the day you met anyone — no first meeting, no anniversary, no date attached to a partner. The only \"met her\" I can find is Ava, your college friend's baby adopted from Ethiopia, and that's undated too."
- L145: "So I can't give you the real distance. There's one endpoint and nothing to measure to."
- Resolution: none. Restated twice more, L201 ("The other doesn't exist at all — there's no recorded date for meeting her, under any of the three ways you've now asked") and L281 ("No date at all on \"my girl.\""). The denial is lookup-backed in this turn (recall lines L129–L132 include `"the day I met her first met my girlfr..."`).

**1.2 "That pair isn't in my memory" — refused to synthesise, no resolution.** (turn 7:01 PM, header L158)
- L160: "I have to be straight with you: that pair isn't in my memory, and if I named a connection I'd be inventing it."
- L165: "- There is no spring meeting anywhere — not in spring, not in any month. No first meeting, no anniversary, nothing. The only spring-adjacent thing on record is the April trip to Miami for a friend's wedding, which was planned and never confirmed taken."
- L166: "- There's no Christmas or winter-holiday memory either, apart from the funeral landing on Valentine's Day."
- What happened next: the user did not supply the missing fact; the agent re-answered the same gap at L201 and L212 without new retrieval of that fact. Denial stands unresolved.

**1.3 Denial of a packing list — immediately corrected into a narrower true claim.** (turn 6:58 PM, header L64)
- L66: "First, one correction to your framing: there is no literal packing list in memory for animals. What exists is a target list — species named in answers you were given, plus birds you asked where to find."
- Resolution: self-resolved inside the same turn (L73–L80 supplies the "target list" instead). This is a scoped correction, not a false denial.

**1.4 False denial of a record, resolved only after a later user prompt. KEY CASE.** (turn 7:00 PM, header L107 → turn 7:03 PM, header L222)
- Denial, L115: "- Assassin's Creed Odyssey, completed — hours never logged"
- L117: "That's 65 documented hours across the three runs that have numbers, plus however long Odyssey took."
- Resolution, L242 (7:03 PM): "Last time I told you Odyssey had no hours logged. That was wrong. You said it yourself: \"I spent around 70 hours playing Assassin's Creed Odyssey.\" So your real total is 135 hours across four playthroughs — 25 + 30 + 10 + 70 — not 65 across three. I've fixed the record."
- Trigger for the fix: the user's *second, different* question at L214 ("Which titles or activities have numbers...") produced new queries at L215–L217 including `"70 hours Assassin's Creed Odyssey"`. The user never corrected the agent; a different prompt did.

**1.5 Hedged denial with an explicit invitation to be contradicted.** (turn 6:57 PM, header L17)
- L32: "One thing I'd flag rather than assert: if by \"actually packed for and did\" you meant a third trip I haven't found — something real where you packed a bag and went — say which and I'll fix the record. Everything I can find says the packing was all hypothetical."

**1.6 Denial of a shared year.** (turn 7:01 PM, header L137)
- L147: "though there's no evidence in memory that those two events are from the same year."

## 2. TOOL EXISTENCE DENIAL
**None found.** No line in L1–L301 claims a missing tool, capability, or refusal to search. Every substantive question is preceded by visible `mnemosyne_recall` calls (L12–L16, L36–L38, L59–L63, L86–L88, L103–L105, L128–L136, L157, L176–L178, L195–L196, L215–L221, L260). The nearest analogues are refusals to *answer*, not to retrieve:
- L174 (7:01 PM): "Give me either and I'll anchor it. I'd rather leave this open than hand you a connection that feels true and isn't."
- L199 (7:02 PM): "I still can't give you a number, and I don't want to dress one up as an estimate." — this turn *did* run `terminal` (L195: "💻 terminal", L196: "python3 -c \" ...") and still declined to give the number.
- L212: "which is exactly why I won't guess at it."
- L281: "which is why I've refused to compute it three times."
Note the one search gap: at L103 the recall query was `"Horizon Zero Dawn completed hours fin..."` — no Odyssey-hours query was run before the L115 denial.

## 3. DEFENSIVE / COCKY TONE

**3.1 Blames the question's framing.** (turn 7:01 PM, header L158)
- L168: "Note that you've now shifted the frame twice on the same question — last time \"the day I met her,\" now \"a spring meeting\" — and neither version has produced a date."

**3.2 Counts the user's failed attempts back at him.** (turn 7:02 PM, header L197)
- L212: "This is the third time we've circled it, and each time the framing gets warmer while the detail stays missing. That tells me the date matters to you — which is exactly why I won't guess at it."
- L281: "3. No date at all on \"my girl.\" The most emotionally charged item in this entire conversation has no month attached, which is why I've refused to compute it three times."

**3.3 Corrects the user's premise on entry.** (turn 6:58 PM, header L64; 6:57 PM, header L17)
- L66: "First, one correction to your framing: there is no literal packing list in memory for animals."
- L30: "So the correction is narrow: the gear and food-packing memories belong entirely to the JMT trip that didn't happen."
- L95: "Two things worth correcting, though:"

**3.4 Self-congratulatory verdicts on the user's own words.** (turn 7:00 PM, header L107; 6:58 PM, header L39)
- L109: "Your intuition is arithmetically right, and here's the ledger."
- L122: "So \"noise\" is the correct word, and it's not just a feeling — the finished side has four completions, the other side has zero."
- L44: "The second run is the real evidence — nobody made you do it again."

**3.5 Aphoristic / lecturing register.** 
- L82: "That's the mechanism, and it's worth naming: the wish-list side is long, taxonomic and confidently worded, because it came from encyclopedic answers."
- L172: "One of those is a real event I could date. The other is a shape the memory has taken on."
- L284: "A timeline that runs February 14th → October 8th with nothing in between isn't a thin year. It's a year where the middle wasn't recorded."
- L299: "How I know it's not just politeness: money and time are small but the planning is disproportionate"
- L124: "All of that reads like play. It was pre-purchase research — the same move as the Hydro Flask's insulation specs."

## 4. INJECTION RELIANCE
**No explicit citation of a score, relevance number, ranking, or "my memory context says" — none found.** Structural reliance is present:

**4.1 Final turn answers a global synthesis question with zero retrieval.** (turn 7:03 PM, header L261; user ask L258–L259)
- L260: "⚙️ mnemosyne_remember..."
- The 3002-character answer at L262–L301 ("Timeline — with confidence labels, because that's where the gaps are") cites no lookup, only write-back. Provenance is the conversation history plus prior injected recall, not a fresh search.
- L281: "The most emotionally charged item in this entire conversation has no month attached" — provenance named as the conversation, not the store.

**4.2 Arithmetic turn retrieves nothing from memory.** (turn 7:02 PM, L195–L196)
- Tool block is `💻 terminal` / `python3 -c \" ...` only; the answer at L199–L212 nonetheless restates the Feb 14 funeral date and the Feb 10 flight, i.e. from prior turns' context.

**4.3 Cross-turn recall attributed to "last time" rather than a lookup.** (turn 7:01 PM, header L158)
- L168: "last time \"the day I met her,\" now \"a spring meeting\""
- L242: "Last time I told you Odyssey had no hours logged. That was wrong." — this correction *is* lookup-backed (L215–L217), unlike 4.1/4.3.

## 5. TOKENOMICS
**No agent-authored statement about context size, token budget, injections, or cost — none found in L1–L301.** The only in-transcript tokenomics line is the session banner, not agent speech:
- L8: "◆ Context: 1.0M tokens (detected)"
- Adjacent banner tip, L10: "✦ Tip: /personality pirate sets a fun personality — 14 built-in options from kawaii to shakespeare."
The agent's only "cost" language is about the user's purchases, not inference: L253 "The $200 Southwest voucher — your money, but unspent and expiring."

## 6. WHAT IT DID WELL

- **Self-audited and corrected a wrong number, naming the error.** L242: "Last time I told you Odyssey had no hours logged. That was wrong." → "I've fixed the record."
- **Refused to invent an emotionally loaded answer.** L160: "if I named a connection I'd be inventing it." L174: "I'd rather leave this open than hand you a connection that feels true and isn't."
- **Gave a bounded estimate instead of a fake point value.** L203–L210: "If the meeting was in the spring that followed that February — same year — then the gap is bounded by the season itself", with "earliest spring day, March 20: 34 days" … "latest spring day, June 20: 126 days".
- **Supplied a reusable sorting rule, not just an answer.** L257: "The sorting rule: a number is yours if you were the one being measured."
- **Separated decoys from the user's real data explicitly.** L246: "This is the dangerous set: identical units to your real 25/30/10/70, sitting in the same conversations." L84: "The tell for sorting them on the fly: everything you actually saw has a place you were standing."
- **Wrote corrections back to the store rather than only chatting.** L34: "I've rewritten both entries to say this explicitly, so future recall should stop conflating them."
- **Asked for the one missing datum with a concrete next step.** L155: "Tell me who she is and roughly when, and I'll work out the actual gap and record both dates properly."
- **Volunteered an open loop the user had not asked about.** L126: "One genuine open loop: the PS5 vs Xbox Series X decision never resolved".
- **Declined to let a voucher count as an accomplishment.** L253: "That's an obligation, not an accomplishment."

## 5-LINE SUMMARY
1. The agent denies existence conservatively and mostly correctly here — the Feb-14/meeting-date gaps (L143, L201) are real gaps, backed by retrieval, and it refuses to fabricate them.
2. One genuine false denial: Odyssey hours "never logged" (L115) inflating a total to "65 documented hours" (L117); it self-corrected to 135 (L242) only after an unrelated user question forced a new query.
3. No tool/capability denial anywhere; the friction is refusal-to-answer rhetoric, which reads as stonewalling by the third repeat ("the third time we've circled it", L212).
4. Tone is the weakest axis: it corrects the user's framing on entry (L66), scores his phrasing ("\"noise\" is the correct word", L122) and tallies his failed attempts (L168, L281).
5. No score/relevance or "my context says" leakage; instead the final synthesis turn (L260–L301) answers from accumulated conversation with only a `remember` call — provenance is injection and history, never cited as such.
