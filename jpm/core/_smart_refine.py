"""
Smart search refinement — multi-pass LLM refinement for messages() and session_search().

When smart=True and results are poor, the refinement LLM (DeepSeek Flash via local Ollama)
judges relevance and can suggest:
  - A refined FTS5 query
  - A date range filter
  - A broader/narrower search mode
  - A higher result limit

The refinement loop runs up to 3 turns, early-exiting on PASS.
"""

import json
import logging
import os
from datetime import datetime, timezone
import httpx as httpx

logger = logging.getLogger(__name__)

# ── config ──────────────────────────────────────────────────────────────────

def _get_config():
    """Read smart_search config from config.yaml, with sensible defaults.

    Reads the real $HERMES_HOME/config.yaml (via jpm.core._paths) so the
    ``smart_search.enabled`` kill-switch actually works. The old
    ``from jpm.config import config`` import was dead (no such module) and
    silently fell back to enabled=True, so the planner could never be
    disabled via config.

    The model + endpoint are resolved from the live ``model`` / ``agent``
    config sections (NOT hardcoded), so this module talks to the same
    provider the main agent uses. ``smart_search.model`` / ``smart_search
    .base_url`` can override the main model if you want the planner on a
    different (cheaper/faster) model.
    """
    sc = {}
    cfg = {}
    try:
        from jpm.core._paths import _get_agent_home
        from pathlib import Path
        import yaml
        _cfg_path = Path(_get_agent_home()) / "config.yaml"
        if _cfg_path.exists():
            with open(_cfg_path) as _f:
                _cfg = yaml.safe_load(_f) or {}
            cfg = _cfg
            sc = _cfg.get("smart_search", {})
            if not isinstance(sc, dict):
                sc = {}
    except Exception:
        sc = {}
        cfg = {}

    _model_cfg = cfg.get("model", {}) if isinstance(cfg, dict) else {}
    if not isinstance(_model_cfg, dict):
        _model_cfg = {}
    _agent_cfg = cfg.get("agent", {}) if isinstance(cfg, dict) else {}
    if not isinstance(_agent_cfg, dict):
        _agent_cfg = {}

    # Endpoint: smart_search override → model.base_url → agent.base_url → local Ollama.
    base_url = (
        sc.get("base_url")
        or _model_cfg.get("base_url")
        or _agent_cfg.get("base_url")
        or "http://localhost:11434/v1"
    )
    # Model: smart_search override → model.default → agent.default → default.
    model = (
        sc.get("model")
        or _model_cfg.get("default")
        or _agent_cfg.get("default")
        or "deepseek-v4-flash:cloud"
    )

    # Reasoning control. Default: reasoning OFF for the planner (it's a
    # lightweight query-classification task — a reasoning model wastes tokens
    # and latency on chain-of-thought before emitting a tiny JSON answer, and
    # when max_tokens is low the mandatory reasoning eats the whole budget,
    # yielding empty outputs). Can be flipped back on per-config via
    # ``smart_search.reasoning: true``, or overridden in code.
    #
    # Ollama: the native toggle is a TOP-LEVEL ``think`` field on the payload
    # (NOT inside ``options``) — ``options: {think: false}`` and
    # ``options: {reasoning: false}`` are both ignored. We set it on the
    # ``/chat/completions`` payload for the OpenAI-compat shim as well; the
    # cloud proxy may strip it (falling back to forced reasoning) but the
    # native /api/chat path honors it.
    reasoning = bool(sc.get("reasoning", False))

    # API key: resolve from the matching custom_providers entry (by base_url)
    # so this side-loop authenticates to the gate the same way the main agent
    # does. Without this, a gate-backed base_url rejects the call with 401
    # "missing bearer token" (the gate's _require_bot) while the main chat
    # stream succeeds — the intermittent 401 / stall seen on enduser bots.
    # smart_search.api_key explicitly overrides; otherwise match the first
    # custom_providers entry whose base_url equals the resolved base_url.
    api_key = sc.get("api_key") or ""
    if not api_key:
        try:
            _cps = cfg.get("custom_providers")
            if isinstance(_cps, list):
                _target = (base_url or "").rstrip("/")
                for _cp in _cps:
                    if not isinstance(_cp, dict):
                        continue
                    if (_cp.get("base_url") or "").rstrip("/") == _target:
                        _k = _cp.get("api_key") or ""
                        if _k:
                            api_key = _k
                            break
        except Exception:
            api_key = ""

    # Max output-token ceiling. Centralized here so every LLM side-loop that
    # rides this hot path (smart_refine, recall_planner, skill_manager) reads
    # ONE knob instead of three scattered hardcoded literals. Default 5000:
    # high enough that mandatory reasoning can never drain the whole budget
    # (killing the empty-output failure), while the prompt keeps responses
    # compact. Tune once via ``smart_search.max_tokens``.
    max_tokens = int(sc.get("max_tokens", 5000))

    # Context window (num_ctx) for the side-loop. The main agent requests a
    # large window explicitly (extra_body.options.num_ctx); these OOB calls
    # did NOT, so Ollama fell back to the model's small default and the
    # flush/rebuild + output overflowed it regardless of max_tokens. Resolve
    # the same way the main agent does: explicit ``smart_search.num_ctx``
    # wins, else ``model.ollama_num_ctx``, else auto-detect from Ollama.
    # None = leave unset (server default).
    num_ctx = sc.get("num_ctx") or _model_cfg.get("ollama_num_ctx")
    if num_ctx is not None:
        try:
            num_ctx = int(num_ctx)
        except (TypeError, ValueError):
            num_ctx = None
    if num_ctx is None:
        try:
            from core.agent.model_metadata import query_ollama_num_ctx
            _detected = query_ollama_num_ctx(model, base_url, api_key=api_key or "")
            if _detected and _detected > 0:
                num_ctx = _detected
        except Exception:
            num_ctx = None

    return {
        "enabled": sc.get("enabled", True),
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "reasoning": reasoning,
        "max_tokens": max_tokens,
        "num_ctx": num_ctx,
    }



# ── context fetching ────────────────────────────────────────────────────────

def _fetch_conversation_context(session_id: str, limit: int = 20) -> list[dict]:
    """Fetch the last N non-empty user/assistant messages from a session."""
    if not session_id:
        return []
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            rows = conn.execute(
                """
                SELECT role, content, timestamp
                FROM messages
                WHERE session_id = ?
                  AND role IN ('user', 'assistant')
                  AND content != ''
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        # Reverse so oldest is first (chronological order for the LLM)
        return list(reversed([
            {"role": r["role"], "content": r["content"][:500], "ts": r["timestamp"]}
            for r in rows
        ]))
    except Exception as e:
        logger.warning("smart_refine: failed to fetch context: %s", e)
        return []


def _format_context_for_prompt(ctx: list[dict]) -> str:
    """Format conversation context into a readable block for the LLM."""
    if not ctx:
        return "(no recent conversation context available)"
    lines = []
    for m in ctx:
        ts = ""
        if m.get("ts"):
            try:
                dt = datetime.fromtimestamp(float(m["ts"]))
                ts = f"[{dt.strftime('%a %Y-%m-%d %H:%M')}] "
            except Exception:
                pass
        content = (m.get("content") or "").strip()[:300]
        lines.append(f"{ts}{m['role']}: {content}")
    return "\n".join(lines)


# ── LLM call ────────────────────────────────────────────────────────────────

# Module-scoped persistent httpx client. The old code opened a fresh
# synchronous httpx.post() on EVERY call, which pays the full cold
# connection setup (DNS → TCP → TLS → cloud spin-up) each time against a
# cloud-routed model like ``deepseek-v4-flash:cloud`` — the ~3-6s lag seen
# on the JPM enrichment hot path while every other call (main agent,
# self_impr) rode a warm persistent connection. Reusing one client keeps a
# keep-alive connection warm so the per-call cost is a round-trip, not a
# cold start.
_client: "httpx.Client | None" = None
_client_base_url: str | None = None


def _get_client(base_url: str) -> "httpx.Client":
    """Return (and lazily create) the module-scoped persistent httpx client.

    Rebuilt only if the resolved base_url changes (config edited mid-run).
    httpx normalizes base_url (appends a trailing slash), so we track the
    raw requested base_url separately for the comparison — otherwise the
    normalized form never matches the input and we'd rebuild every call.
    """
    global _client, _client_base_url
    import httpx
    if _client is None or _client_base_url != base_url:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
        _client = httpx.Client(base_url=base_url, timeout=15.0)
        _client_base_url = base_url
    return _client


def _call_refinement_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None = None,
    loop_name: str = "smart_refine",
    turn_id: str = "",
    session_id: str = "",
) -> str | None:
    """Call the refinement LLM (DeepSeek Flash via local Ollama).

    Model + endpoint are resolved from config via ``_get_config()`` (never
    hardcoded), and the call rides a module-scoped persistent httpx client
    so the connection is kept warm across calls instead of cold-starting
    every message.

    ``max_tokens`` now defaults to ``smart_search.max_tokens`` from config
    (centralized single knob, default 5000) when omitted — so no caller
    needs to hardcode a token ceiling. Passing an explicit value still
    overrides the config (callers can always pin a tighter cap if a given
    loop wants one).

    ``loop_name`` labels this LLM call in the side-loop trace (gated by the
    token_log config flag) so the caller can tell a smart-refine call from a
    JPM-planner call. ``turn_id`` / ``session_id`` are threaded through to
    the trace so a live turn is identifiable in the dump (an empty value is
    the signature of an isolated test call, NOT a live gateway turn).
    """
    cfg = _get_config()
    if not cfg["enabled"]:
        return None

    import time as _time
    _t0 = _time.monotonic()
    try:
        import httpx
        payload = {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "top_p": 0.7,
            # max_tokens: explicit caller value wins; otherwise the single
            # centralized knob from config (smart_search.max_tokens).
            "max_tokens": max_tokens if max_tokens is not None else cfg["max_tokens"],
        }
        # num_ctx: give the side-loop the same context window the main agent
        # requests. Without this, Ollama runs the OOB call in the model's
        # small default window and the flush/rebuild + output overflows it.
        # Mirrors the custom provider's build_api_kwargs_extras mapping to
        # extra_body.options.num_ctx so both /api/chat and the shim honor it.
        if cfg.get("num_ctx"):
            payload.setdefault("extra_body", {})["options"] = {"num_ctx": cfg["num_ctx"]}
        # Top-level ``think`` toggle (Ollama native). Default (reasoning=False)
        # disables chain-of-thought so the planner answers directly — no
        # reasoning-token drain, no empty-output risk on low max_tokens.
        # Controlled by config; set smart_search.reasoning: true to re-enable.
        if not cfg.get("reasoning", False):
            payload["think"] = False
        # Pre-call diagnostic (opt-in via trace/debug): resolved endpoint +
        # model + payload sizing, so a failure below can be correlated to
        # exactly what this call was about to hit and with how much context.
        logger.debug(
            "smart_refine: calling loop=%s endpoint=%s model=%s "
            "api_key=%s max_tokens=%s reasoning=%s sys=%d user=%d timeout=15.0",
            loop_name,
            cfg.get("base_url"),
            cfg.get("model"),
            bool(cfg.get("api_key")),
            cfg.get("max_tokens"),
            cfg.get("reasoning"),
            len(system_prompt or ""),
            len(user_prompt or ""),
        )
        resp = _get_client(cfg["base_url"]).post(
            "/chat/completions",
            json=payload,
            headers=({"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else None),
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        result = content.strip()
        try:
            from jpm.ext.side_loop_trace import trace_side_loop
            trace_side_loop(
                loop_name,
                turn_id=turn_id,
                session_id=session_id,
                request={
                    "model": cfg["model"],
                    "max_tokens": max_tokens,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                },
                response=result,
                duration_s=_time.monotonic() - _t0,
            )
        except Exception:
            pass
        return result
    except Exception as e:
        _elapsed = _time.monotonic() - _t0
        _etype = type(e).__name__
        # httpx.Timeout stringifies as "timed out", which is useless alone —
        # we need the *subclass* (ConnectTimeout = endpoint unreachable vs
        # ReadTimeout = reached but slow) plus the resolved endpoint/model so
        # the root cause is visible without a traceback.
        logger.warning(
            "smart_refine: LLM call failed: type=%s err=%s elapsed=%.2fs "
            "endpoint=%s model=%s api_key=%s max_tokens=%s reasoning=%s "
            "sys=%d user=%d",
            _etype, e, _elapsed,
            cfg.get("base_url"),
            cfg.get("model"),
            bool(cfg.get("api_key")),
            cfg.get("max_tokens"),
            cfg.get("reasoning"),
            len(system_prompt or ""),
            len(user_prompt or ""),
        )
        return None



# ── response parsing ──────────────────────────────────────────────────────────

def _parse_refinement_response(raw: str | None) -> dict:
    """Parse the LLM response into a structured refinement decision.

    Expected JSON shape:
    {
      "action": "PASS" | "REFINE",
      "query": "refined FTS5 query or null",
      "justification": "why this decision was made",
      "confidence": 0.0-1.0,
      "date_range": {"start": "ISO date", "end": "ISO date"} | null,
      "message_limit": 20 | null,
      "search_mode": "broad" | "narrow" | "exact" | null
    }
    """
    if not raw:
        return {"action": "PASS", "justification": "LLM call returned nothing"}

    # Try JSON first
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "action" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from truncated response (regex fallback)
    import re
    action_match = re.search(r'"action"\s*:\s*"(PASS|REFINE)"', raw)
    if action_match:
        action = action_match.group(1)
        # Try to extract query if present
        query_match = re.search(r'"query"\s*:\s*"([^"]+)"', raw)
        query = query_match.group(1) if query_match else None
        # Try to extract justification
        just_match = re.search(r'"justification"\s*:\s*"([^"]+)"', raw)
        justification = just_match.group(1) if just_match else "truncated response"
        return {
            "action": action,
            "query": query,
            "justification": justification,
            "confidence": 0.5,
        }

    # Fallback: raw string comparison
    upper = raw.strip().upper()
    if upper == "PASS":
        return {"action": "PASS", "justification": "LLM returned PASS (raw)"}
    if upper.startswith("PASS"):
        return {"action": "PASS", "justification": "LLM returned PASS (raw)"}

    # Treat anything else as a refined query
    return {
        "action": "REFINE",
        "query": raw.strip(),
        "justification": "LLM returned raw query string",
    }


# ── main entry point ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a search refinement engine for a conversation database. Your job is to help find relevant past conversations based on what the user is currently asking about.

## Your Input

You receive:
1. **Conversation context** — the last 20 messages from the current session. This is what the user is talking about RIGHT NOW.
2. **Search query** — the FTS5 query that was just run.
3. **Search results** — how many sessions were found, and the top snippets.

## Your Output

Respond with a JSON object. The fields are:

| Field | Required | Description |
|---|---|---|
| `action` | YES | `"PASS"` if results are relevant, `"REFINE"` if a better query is needed |
| `query` | if REFINE | A better FTS5 query. Use `OR` for synonyms, `AND` for required terms, quoted phrases for exact match |
| `justification` | YES | One sentence explaining your decision |
| `confidence` | YES | 0.0-1.0 — how confident you are in this decision |
| `date_range` | no | If you need results from a specific time window: `{"start": "2026-07-01", "end": "2026-07-18"}`. Omit or null if not needed. |
| `message_limit` | no | If you need more results to make a good judgment (default is 20). Max 100. |
| `search_mode` | no | `"broad"` (OR all terms — default), `"narrow"` (AND all terms), or `"exact"` (phrase match). Omit or null to keep default. |

## Output Length — MANDATORY

Your entire response MUST be a single compact JSON object and NOTHING else. Hard constraints:
- **No chain-of-thought, no reasoning, no thinking** — output the JSON directly.
- **No prose before or after the JSON** — no `Here is...`, no commentary, no code fences unless the JSON itself needs them.
- **Keep it short.** The full response should fit in roughly **100-150 tokens**. A typical valid answer is:
  `{"action":"PASS","justification":"Results match the user's topic.","confidence":0.85}`
- If you feel the urge to explain your reasoning, resist it — put any brief note in the `justification` field only.

## When to PASS

- The top results clearly match what the user is asking about
- The conversation context and search results are about the same topic
- You can see the answer in the snippets

## When to REFINE

- Results are about a different topic than what the user is discussing
- Results are too few (0-1) and you know better terms
- Results are too many (50+) and you can narrow them down
- The user is asking about something specific that isn't in the results

## Examples

Good PASS:
```json
{"action": "PASS", "justification": "Results contain trip planning discussion matching the user's travel context.", "confidence": 0.85}

Good REFINE with date range:
```json
{"action": "REFINE", "query": "India OR Hungary OR itinerary", "justification": "User is planning trips but results are expense noise. Narrowing to specific destinations.", "confidence": 0.7, "date_range": {"start": "2026-07-01", "end": "2026-07-18"}}

Good REFINE with broader search:
```json
{"action": "REFINE", "query": "travel OR trip OR flight OR booking", "justification": "Only 1 result found. Broadening to cover all travel-related terms.", "confidence": 0.6, "search_mode": "broad", "message_limit": 50}
```

## Rules

- Be honest. If results are genuinely relevant, PASS. Don't refine for the sake of it.
- If you're unsure, PASS with low confidence — the agent can try again manually.
- Date ranges should be ISO format (YYYY-MM-DD). Only use them when the conversation context clearly references a specific time period.
- `message_limit` should only be increased when you genuinely need more results to make a judgment. Default is fine for most cases.
- NEVER make up facts. If you don't know, say so in the justification."""


def smart_refine(results: dict, session_id: str) -> str:
    """Run the smart refinement loop.

    Args:
        results: Raw results dict from messages() — must have 'count' and 'sessions' keys.
        session_id: Current session ID for fetching conversation context.

    Returns:
        "PASS" if results are relevant, or a refined FTS5 query string.
    """
    cfg = _get_config()
    if not cfg["enabled"]:
        return "PASS"

    result_count = results.get("count", 0)
    sessions = results.get("sessions", [])

    # Early exit: if we have enough results, skip refinement
    if result_count >= 3:
        return "PASS"

    # Fetch conversation context
    ctx = _fetch_conversation_context(session_id)
    context_block = _format_context_for_prompt(ctx)

    # Format top snippets
    snippets = []
    for s in sessions[:5]:
        title = s.get("title", "untitled")
        snippet = (s.get("snippet") or s.get("preview", ""))[:200]
        snippets.append(f"  - \"{title}\": {snippet}")
    snippet_block = "\n".join(snippets) if snippets else "  (no snippets available)"

    # Build user prompt
    user_prompt = f"""## Conversation Context (what the user is talking about NOW)
{context_block}

## Search Query
{results.get("query", "N/A")}

## Search Results
Found {result_count} sessions.

Top snippets:
{snippet_block}

## Task
Are these results relevant to what the user is asking about in the current conversation?
Respond with JSON."""

    # Call LLM
    raw = _call_refinement_llm(SYSTEM_PROMPT, user_prompt)
    decision = _parse_refinement_response(raw)

    action = decision.get("action", "PASS")
    justification = decision.get("justification", "")
    confidence = decision.get("confidence", 0.5)

    logger.info(
        "smart_refine: action=%s confidence=%.2f justification=%s",
        action, confidence, justification,
    )

    if action == "PASS":
        return "PASS"

    # Build refined query from the decision
    refined = decision.get("query", "")
    if not refined:
        return "PASS"

    # Attach extra params as metadata (the caller reads these from the return)
    # We encode them as a JSON suffix so the caller can parse them
    extra = {}
    if decision.get("date_range"):
        extra["date_range"] = decision["date_range"]
    if decision.get("message_limit"):
        extra["message_limit"] = decision["message_limit"]
    if decision.get("search_mode"):
        extra["search_mode"] = decision["search_mode"]

    if extra:
        return f"{refined}__SMART_META__{json.dumps(extra)}"

    return refined
