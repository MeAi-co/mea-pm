"""Tone detection for auto-updating agent state based on user mood.

Multi-signal heuristic engine (no LLM):
  - Structural features: length, caps, punctuation density, emoji density
  - Weighted phrase/emoji categories (not flat match counts)
  - Dimension scores → discrete mood + energy + observational headspace

Curated from production traffic patterns + feelings taxonomies.
Designed to be cheap, deterministic, and low false-positive on normal traffic.
"""

from __future__ import annotations

import re
from typing import Optional


def _compile(patterns: list[tuple[str, float]]) -> list[tuple[re.Pattern, float]]:
    return [(re.compile(p, re.IGNORECASE), w) for p, w in patterns]


# ── Weighted signal groups ───────────────────────────────────────────────────
# Narrow patterns. Polite filler ("please", bare "can you") is intentionally
# excluded to keep false positives low.

CORRECTION = _compile([
    (r"\b(that'?s not (what|right|correct)|you misunderstood|I (didn'?t|never) say)\b", 1.4),
    (r"\b(actually[,:]|correction[,:]|wait[,:]|hold on[,:])\b", 1.1),
    (r"\b(wrong|fix it|try again|do it (again|properly))\b", 1.0),
    (r"\b(already (said|told you)|I told you|repeat that)\b", 1.2),
    (r"\b(no[,:]|stop[,:]|don'?t)\b(?=.{0,40}\b(that|doing|saying|writing|using)\b)", 1.0),
])

FRUSTRATION = _compile([
    (r"\b(ugh|ffs|wtf|goddammit|seriously\?)\b", 1.3),
    (r"\b(fuck|shit|damn)(ing|ed)?\b", 1.1),
    (r"[😡🤬👿💢]", 1.4),
    (r"!{3,}|\?{3,}", 0.9),
    (r"\b(this is (ridiculous|insane|stupid)|what the hell)\b", 1.2),
    (r"\b(pissed|furious|outraged|fed up)\b", 1.3),
])

STRESS = _compile([
    (r"\b(overwhelm(ed|ing)?|swamped|buried|drowning in)\b", 1.3),
    (r"\b(stressed|stressful|too much (right now|on my plate))\b", 1.2),
    (r"\b(I can'?t (deal|handle|do this)|at capacity)\b", 1.3),
    (r"\b(burned? out|running on empty|frazzled|rattled)\b", 1.1),
    (r"\b(deadline|due (today|tomorrow)|urgent|asap)\b", 0.7),
])

ANXIETY = _compile([
    (r"\b(anxious|anxiety|nervous|worried|worrying)\b", 1.2),
    (r"\b(scared|afraid|frightened|terrified|panick?ing)\b", 1.3),
    (r"\b(uneasy|on edge|apprehensive|dreading)\b", 1.0),
    (r"[😰😨😱😟]", 1.2),
])

HEALTH = _compile([
    (r"\b(headache|migraine|dizzy|nausea|nauseous|sick|in pain)\b", 1.2),
    (r"\b(can'?t sleep|insomnia|exhausted|wiped out)\b", 1.0),
    (r"\b(doctor|hospital|appointment|meds?|pills?|prescription)\b", 0.9),
    (r"\b(stent|histamine|prediabetic|blood sugar|bp|blood pressure)\b", 1.1),
    (r"\b(flare|flare-?up|symptoms?)\b", 0.8),
])

SADNESS = _compile([
    (r"\b(sad|unhappy|down|blue|low)\b", 1.0),
    (r"\b(depressed|depressing|hopeless|heartbroken|grief)\b", 1.4),
    (r"\b(lonely|alone|empty|hollow|numb)\b", 1.1),
    (r"\b(miss(ing)? you|wish you were|longing)\b", 0.9),
    (r"[😢😭😔💔]", 1.3),
    (r"\b(disappointed|let down|discouraged)\b", 1.0),
])

PLAYFUL = _compile([
    (r"\b(lol|lmao|lmfao|haha+|hehe|rofl)\b", 0.8),
    (r"[😏😈🔥💯👀💋😘😜🤭]", 1.0),
    (r"\b(tease|banter|roast|sass(y)?|flirt)\b", 1.1),
    (r"\b(baby|my love|habibi|babe)\b", 1.2),
    (r"\b(you'?re (impossible|the worst|trouble))\b", 0.9),
    (r"\b(mischievous|silly|goofy)\b", 0.8),
])

WARM = _compile([
    (r"\b(thank you|thanks|appreciate (it|you)|grateful|thankful)\b", 0.9),
    (r"\b(love (that|this|you)|miss you|proud of you)\b", 1.1),
    (r"[❤️💕🥰😊🙏🤗]", 0.9),
    (r"\b(sweet|kind|helpful|perfect|blessed)\b", 0.5),
    (r"\b(means a lot|touched|moved)\b", 0.8),
])

ENGAGED = _compile([
    (r"\b(interesting|curious|how (does|do|would)|what if|walk me through)\b", 0.8),
    (r"\b(let'?s (go|do it|dig in|ship it)|fire away)\b", 0.9),
    (r"\b(nice|solid|clean|elegant|smart)\b", 0.5),
    (r"\b(fascinated|intrigued|tell me more)\b", 1.0),
    (r"\?{1,2}$", 0.3),
])

EXCITED = _compile([
    (r"\b(excited|pumped|stoked|thrilled|hyped)\b", 1.2),
    (r"\b(can'?t wait|so ready|let'?s goooo+)\b", 1.1),
    (r"\b(amazing|awesome|incredible|yes{2,}|yess+)\b", 0.8),
    (r"[🎉🚀✨🤩😆]", 1.0),
    (r"!{2,}", 0.5),
])

IMPATIENCE = _compile([
    (r"^(yes|no|ok|okay|sure|fine|whatever|k)\.?$", 0.9),
    (r"\b(just (do|fix|make|run) it|get on with it|hurry)\b", 1.1),
    (r"\b(short version|tldr|bottom line|skip (the )?(preamble|intro))\b", 1.0),
    (r"\b(I (already|just) (said|asked))\b", 1.0),
])

LOW_ENERGY = _compile([
    (r"\b(tired|sleepy|drained|meh|blah|whatever)\b", 0.9),
    (r"\b(not (today|now|feeling it)|maybe later)\b", 0.8),
    (r"\b(quiet (night|evening)|low key|chill|mellow)\b", 0.6),
    (r"\b(exhausted|wiped|depleted|weary)\b", 1.0),
])

NUMB = _compile([
    (r"\b(numb|empty|nothing|don'?t care|whatever+)\b", 1.1),
    (r"\b(disconnected|checked out|shut down|blank)\b", 1.2),
    (r"\b(indifferent|apathetic|meh)\b", 0.9),
])

HOPEFUL = _compile([
    (r"\b(hope(ful)?|hoping|fingers crossed)\b", 0.9),
    (r"\b(optimistic|looking up|things (will|are going to) get better)\b", 1.1),
    (r"\b(encouraged|promising|bright side)\b", 0.8),
])

SURPRISED = _compile([
    (r"\b(wow|whoa|whoah|no way|seriously\?|wait what)\b", 1.0),
    (r"\b(surprised|shocked|didn'?t expect|blown away)\b", 1.1),
    (r"[😲😮🤯]", 1.2),
])


# ── Feature extraction ───────────────────────────────────────────────────────

def _features(text: str) -> dict:
    if not text:
        return {
            "len": 0, "caps_ratio": 0.0, "excl": 0, "ques": 0,
            "emoji": 0, "short": True, "very_short": True,
        }
    letters = [c for c in text if c.isalpha()]
    caps = sum(1 for c in letters if c.isupper())
    return {
        "len": len(text),
        "caps_ratio": (caps / len(letters)) if letters else 0.0,
        "excl": text.count("!"),
        "ques": text.count("?"),
        "emoji": len(re.findall(
            r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FAFF]",
            text,
        )),
        "short": len(text) < 60,
        "very_short": len(text) < 20,
    }


def _score_category(text: str, compiled: list[tuple[re.Pattern, float]]) -> float:
    total = 0.0
    for pat, weight in compiled:
        if pat.search(text):
            total += weight
    return total


# ── Mood catalog ─────────────────────────────────────────────────────────────
# name → (base_energy, observational headspace)
# Headspace describes user state — not an agent instruction.

MOODS: dict[str, tuple[float, str]] = {
    "neutral":     (0.50, ""),
    "playful":     (0.85, "User is playful / bantering"),
    "warm":        (0.70, "User is warm and appreciative"),
    "grateful":    (0.65, "User is grateful / thankful"),
    "engaged":     (0.75, "User is engaged and leaning in"),
    "excited":     (0.90, "User is excited / energized"),
    "hopeful":     (0.60, "User is hopeful"),
    "focused":     (0.65, "User is task-focused and direct"),
    "surprised":   (0.70, "User is surprised"),
    "impatient":   (0.55, "User is clipped / wants speed"),
    "irritable":   (0.40, "User is correcting or short"),
    "frustrated":  (0.30, "User is frustrated"),
    "stressed":    (0.45, "User is under pressure"),
    "anxious":     (0.40, "User is anxious / worried"),
    "overwhelmed": (0.30, "User is overloaded"),
    "sad":         (0.25, "User is sad or down"),
    "tired":       (0.25, "User has low energy"),
    "numb":        (0.20, "User seems flat / disconnected"),
    "concerned":   (0.35, "User is dealing with health / body stuff"),
    "caring":      (0.50, "User mentioned health — supportive context"),
    "calm":        (0.45, "User is settled / low-key"),
}


def _pick_mood(scores: dict[str, float], feat: dict) -> str:
    """Priority-ordered mapping. Strong specific signals beat diffuse ones."""
    c = scores
    # Corrections
    if c["correction"] >= 1.0 and feat["short"]:
        return "irritable"
    if c["correction"] >= 1.5:
        return "irritable"

    # Frustration / anger
    if c["frustration"] >= 2.0 or (c["frustration"] >= 1.2 and feat["excl"] >= 2):
        return "frustrated"
    if c["frustration"] >= 1.0 and c["correction"] >= 0.8:
        return "frustrated"

    # Health
    if c["health"] >= 1.0 and c["stress"] >= 1.5:
        return "concerned"
    if c["health"] >= 1.0:
        return "caring"

    # Anxiety vs stress vs overwhelm
    if c["anxiety"] >= 1.5:
        return "anxious"
    if c["stress"] >= 2.2:
        return "overwhelmed"
    if c["stress"] >= 1.3:
        return "stressed"

    # Sadness / numbness
    if c["sadness"] >= 1.8:
        return "sad"
    if c["numb"] >= 1.5:
        return "numb"
    if c["sadness"] >= 1.0 and c["low_energy"] >= 0.8:
        return "sad"

    # Impatience
    if c["impatience"] >= 1.2 or (c["impatience"] >= 0.9 and feat["very_short"]):
        return "impatient"

    if c["frustration"] >= 1.0:
        return "irritable"

    # Positive cluster (order matters — more specific first)
    if c["excited"] >= 1.5:
        return "excited"
    if c["playful"] >= 1.8:
        return "playful"
    if c["playful"] >= 1.0 and c["warm"] >= 0.7:
        return "playful"
    # grateful is a warmer subtype — thanks-language boost already applied
    # in detect_tone before this point, so the threshold alone is enough.
    if c["grateful"] >= 1.2:
        return "grateful"
    if c["warm"] >= 1.5:
        return "warm"
    if c["hopeful"] >= 1.2:
        return "hopeful"
    if c["surprised"] >= 1.3:
        return "surprised"
    if c["engaged"] >= 1.4:
        return "engaged"

    # Low energy / calm
    if c["low_energy"] >= 1.3:
        return "tired"
    if c["low_energy"] >= 0.8 and feat["len"] < 80:
        return "calm"

    # Structural
    if feat["caps_ratio"] > 0.65 and feat["short"] and feat["len"] > 3:
        return "frustrated"
    if feat["very_short"] and max(c["playful"], c["warm"], c["engaged"], c["excited"]) < 0.5 and c["impatience"] >= 0.5:
        return "impatient"

    return "neutral"


def detect_tone(user_message: str, last_assistant: Optional[str] = None) -> dict:
    """Analyze user message and return agent state update.

    Returns mood, energy, headspace, plus valence/arousal for continuous callers.
    """
    if not user_message or not user_message.strip():
        energy, headspace = MOODS["neutral"]
        return {
            "mood": "neutral",
            "energy": energy,
            "headspace": headspace,
            "valence": 0.0,
            "arousal": 0.3,
        }

    text = user_message.strip()
    feat = _features(text)

    scores = {
        "correction":  _score_category(text, CORRECTION),
        "frustration": _score_category(text, FRUSTRATION),
        "stress":      _score_category(text, STRESS),
        "anxiety":     _score_category(text, ANXIETY),
        "health":      _score_category(text, HEALTH),
        "sadness":     _score_category(text, SADNESS),
        "playful":     _score_category(text, PLAYFUL),
        "warm":        _score_category(text, WARM),
        "grateful":    _score_category(text, WARM),  # warm patterns cover thanks/grateful
        "engaged":     _score_category(text, ENGAGED),
        "excited":     _score_category(text, EXCITED),
        "impatience":  _score_category(text, IMPATIENCE),
        "low_energy":  _score_category(text, LOW_ENERGY),
        "numb":        _score_category(text, NUMB),
        "hopeful":     _score_category(text, HOPEFUL),
        "surprised":   _score_category(text, SURPRISED),
    }

    # Structural boosts
    arousal_boost = 0.0
    if feat["caps_ratio"] > 0.55 and feat["len"] > 8:
        scores["frustration"] += 0.6
    if feat["excl"] >= 3:
        scores["frustration"] += 0.3
        scores["excited"] += 0.3
        arousal_boost = 0.15
    if feat["emoji"] >= 3 and scores["playful"] >= 0.5:
        scores["playful"] += 0.5
    if feat["ques"] >= 3:
        scores["stress"] += 0.3
        scores["engaged"] += 0.2
        scores["anxiety"] += 0.2

    # Repeat after assistant → mild impatience
    if last_assistant and feat["short"] and scores["correction"] < 1.0:
        prev = last_assistant.lower()[:120]
        words = [w for w in text.lower().split() if len(w) > 4]
        if text.lower() in prev or (len(text) < 40 and words and any(w in prev for w in words)):
            scores["impatience"] += 0.6

    # Boost grateful when thanks-language is strong
    if re.search(r"\b(thank|grateful|thankful|appreciate)\b", text, re.I):
        scores["grateful"] = max(scores["grateful"], scores["warm"] + 0.4)

    mood = _pick_mood(scores, feat)
    base_energy, headspace = MOODS[mood]

    energy = base_energy
    if feat["emoji"] >= 2 and mood in ("playful", "warm", "engaged", "excited", "grateful"):
        energy = min(1.0, energy + 0.1)
    if feat["very_short"] and mood in ("impatient", "irritable", "frustrated"):
        energy = max(0.15, energy - 0.05)
    if scores["low_energy"] >= 1.0:
        energy = min(energy, 0.35)

    # Continuous dimensions
    valence = (
        0.50 * scores["playful"] + 0.45 * scores["warm"] + 0.40 * scores["excited"]
        + 0.35 * scores["engaged"] + 0.30 * scores["hopeful"] + 0.25 * scores["grateful"]
        - 0.60 * scores["frustration"] - 0.50 * scores["correction"]
        - 0.45 * scores["stress"] - 0.45 * scores["anxiety"]
        - 0.50 * scores["sadness"] - 0.35 * scores["health"]
        - 0.30 * scores["low_energy"] - 0.35 * scores["numb"]
        - 0.25 * scores["impatience"]
    )
    valence = max(-1.0, min(1.0, valence / 2.8))

    arousal = (
        0.40 * scores["frustration"] + 0.35 * scores["stress"] + 0.40 * scores["anxiety"]
        + 0.30 * scores["impatience"] + 0.45 * scores["excited"]
        + 0.30 * scores["playful"] + 0.25 * scores["engaged"]
        + 0.35 * scores["surprised"] + 0.20 * scores["correction"]
        - 0.40 * scores["low_energy"] - 0.35 * scores["numb"] - 0.25 * scores["sadness"]
        + arousal_boost
    )
    arousal = max(0.05, min(1.0, 0.35 + arousal / 3.2))

    return {
        "mood": mood,
        "energy": round(energy, 2),
        "headspace": headspace,
        "valence": round(valence, 2),
        "arousal": round(arousal, 2),
    }
