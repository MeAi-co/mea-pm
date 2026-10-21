import re

# Stopwords that are not valid entities — sentence starters, common verbs, articles
_ENTITY_STOPWORDS = {
    "the", "a", "an", "this", "that", "these", "those",
    "when", "where", "what", "which", "who", "whom", "whose",
    "how", "why", "and", "or", "but", "not", "if", "so",
    "for", "with", "without", "at", "by", "from", "into", "onto",
    "about", "after", "before", "during", "through", "until",
    "use", "using", "used", "check", "checking", "checked",
    "get", "getting", "got", "set", "setting", "run", "running",
    "make", "making", "made", "do", "does", "did", "doing",
    "have", "has", "had", "having", "is", "are", "was", "were",
    "be", "been", "being", "will", "would", "could", "should",
    "can", "may", "might", "shall", "must", "need", "needs",
    "don", "doesn", "didn", "isn", "aren", "wasn", "weren",
    "won", "wouldn", "couldn", "shouldn", "can't", "won't",
    "all", "each", "every", "both", "few", "many", "much",
    "some", "any", "no", "none", "one", "two", "three",
    "first", "last", "next", "previous", "other", "another",
    "also", "too", "very", "just", "only", "even", "still",
    "already", "always", "never", "often", "sometimes",
    "here", "there", "then", "than", "now", "ago", "later",
    "up", "down", "in", "out", "on", "off", "over", "under",
    "again", "further", "more", "most", "less", "least",
    "such", "as", "to", "into", "onto", "upon", "via",
    "let", "lets", "let's", "please", "see", "seen", "look",
    "know", "known", "think", "thought", "say", "said", "tell",
    "told", "ask", "asked", "find", "found", "show", "shown",
    "add", "added", "remove", "removed", "update", "updated",
    "create", "created", "delete", "deleted", "save", "saved",
    "load", "loaded", "start", "started", "stop", "stopped",
    "open", "opened", "close", "closed", "send", "sent",
    "try", "tried", "work", "works", "worked", "working",
}

# Entity extraction patterns
_RE_CAPITALIZED  = re.compile(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b')
_RE_DOUBLE_QUOTE = re.compile(r'"([^"]+)"')
_RE_SINGLE_QUOTE = re.compile(r"'([^']+)'")
_RE_AKA          = re.compile(
    r'(\w+(?:\s+\w+)*)\s+(?:aka|also known as)\s+(\w+(?:\s+\w+)*)',
    re.IGNORECASE,
)


def _extract_entities(text: str) -> list[str]:
    """Extract entity names from text. Returns deduplicated list.
    Filters out common stopwords that are not valid entities.
    For multi-word entities, filters if ALL words are stopwords.
    """
    entities: set[str] = set()
    for m in _RE_CAPITALIZED.finditer(text):
        candidate = m.group(1).strip()
        words = candidate.split()
        # Keep if at least one word is NOT a stopword
        if any(w.lower() not in _ENTITY_STOPWORDS for w in words):
            entities.add(candidate)
    for m in _RE_DOUBLE_QUOTE.finditer(text):
        candidate = m.group(1).strip()
        words = candidate.split()
        if any(w.lower() not in _ENTITY_STOPWORDS for w in words):
            entities.add(candidate)
    for m in _RE_SINGLE_QUOTE.finditer(text):
        candidate = m.group(1).strip()
        words = candidate.split()
        if any(w.lower() not in _ENTITY_STOPWORDS for w in words):
            entities.add(candidate)
    for m in _RE_AKA.finditer(text):
        c1 = m.group(1).strip()
        c2 = m.group(2).strip()
        words1 = c1.split()
        words2 = c2.split()
        if any(w.lower() not in _ENTITY_STOPWORDS for w in words1):
            entities.add(c1)
        if any(w.lower() not in _ENTITY_STOPWORDS for w in words2):
            entities.add(c2)
    return sorted(entities)