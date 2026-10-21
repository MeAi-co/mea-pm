"""Shared Ollama embedding client with primary→fallback failover.

Centralizes the Ollama embed call so every path (live embed worker,
watchdog reconciler, hybrid retrieval) uses the SAME failover logic
instead of each reading OLLAMA_URL independently.

Failover design (per Josh's requirement):
  - OLLAMA_URL            = primary GPU (default: local 5060 Ti)
  - OLLAMA_FALLBACK_URL   = secondary GPU (default: Tina's RTX 2060 over tailnet)
  - embed() tries primary first; on ANY failure (connection refused,
    timeout, bad response) it falls back to the secondary. If both fail,
    it raises so the caller can degrade loudly (never silently).

Env:
  OLLAMA_URL            http://127.0.0.1:11434   (primary)
  OLLAMA_FALLBACK_URL   http://100.123.92.106:11434  (P5000 fallback)
  EMBED_MODEL           nomic-embed-text
  EMBED_NUM_GPU         -1
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error

log = logging.getLogger("jpm.ollama")

def _env_urls() -> list[str]:
    """Read the Ollama URL chain lazily (import-time reads race load_dotenv).

    Accepts both:
      - OLLAMA_URL="http://a:11434,http://b:11434"  (comma chain, listener style)
      - OLLAMA_URL="http://a:11434" + OLLAMA_FALLBACK_URL="http://b:11434"
    The chain form wins; the fallback env var is appended when it isn't
    already present in the chain.
    """
    chain = [u.strip() for u in os.environ.get(
        "OLLAMA_URL", "http://127.0.0.1:11434"
    ).split(",") if u.strip()]
    fb = os.environ.get("OLLAMA_FALLBACK_URL")
    if fb and fb.strip() not in chain:
        chain.append(fb.strip())
    return chain

def _env_primary():
    """Primary embed endpoint = first URL in the chain."""
    return _env_urls()[0]

def _env_fallback():
    """Secondary embed endpoint = second URL in the chain (or None)."""
    urls = _env_urls()
    return urls[1] if len(urls) > 1 else urls[0]

def _env_model():
    return os.environ.get("EMBED_MODEL", "nomic-embed-text")

def _env_num_gpu():
    return int(os.environ.get("EMBED_NUM_GPU", "-1"))


def _env_provider() -> str:
    """Embed provider: 'ollama' (native /api/embed) or 'llamacpp' (OpenAI /v1/embeddings).

    Default 'ollama' keeps the existing path untouched. Set EMBED_PROVIDER=llamacpp
    to route through a llama.cpp / llama-server OpenAI-compatible endpoint.
    """
    return os.environ.get("EMBED_PROVIDER", "ollama").strip().lower()


def _env_max_chars() -> int:
    """Per-input embed clamp ceiling in chars.

    Default 5500 (~1850 tokens at local Ollama's ~2.97 chars/token ratio).
    Remote llama.cpp endpoints can tokenize tighter (e.g. 2.5 chars/token),
    so 5500 chars can still blow past a 2048-token n_ctx. Set EMBED_MAX_CHARS
    lower (e.g. 5000) on nodes routing to such endpoints.

    NOTE: llama-server's --batch-size is a PHYSICAL batch ceiling that rejects
    (HTTP 500) any single input over it, independent of n_ctx. nomic-embed-text
    tokenizes at ~2.0 chars/token, so a 2048-token batch is only ~4000 chars.
    The live node sets EMBED_MAX_CHARS=3800 (~1900 tokens) to stay under it.
    """
    try:
        return int(os.environ.get("EMBED_MAX_CHARS", "5500").strip())
    except ValueError:
        return 5500


def _call_ollama(url: str, texts: list[str], timeout: int = 120) -> list[list[float]]:
    """Embed texts against ONE Ollama URL (native /api/embed). Raises on failure.

    Attaches `Authorization: Bearer *** when OLLAMA_API_KEY is set, so
    the shared client works against gated/aggregating ollama ingress
    (e.g. the ollama-gate proxy). Unset -> no header -> plain no-auth
    upstream unchanged (backward compatible).
    """
    payload = json.dumps(
        {"model": _env_model(), "input": texts, "options": {"num_gpu": _env_num_gpu()}}
    ).encode()
    _hdrs = {
        "Content-Type": "application/json",
        # Browser User-Agent so the request survives Cloudflare bot-protection at
        # the edge when OLLAMA_URL is a public SaaS hostname (Python-urllib UA is 403'd).
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    }
    _key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if _key:
        _hdrs["Authorization"] = f"Bearer {_key}"
    req = urllib.request.Request(
        f"{url}/api/embed",
        data=payload,
        headers=_hdrs,
    )
    data = _urlopen_json(req, timeout)
    if "embeddings" not in data or not isinstance(data["embeddings"], list):
        raise RuntimeError(f"unexpected embed response from {url}: {str(data)[:200]}")
    return data["embeddings"]


def _call_llamacpp(url: str, texts: list[str], timeout: int = 120) -> list[list[float]]:
    """Embed texts against ONE llama.cpp / llama-server (OpenAI /v1/embeddings).

    llama.cpp exposes the OpenAI-compatible embeddings endpoint:
        POST {url}/v1/embeddings
        {"input": [...], "model": "..."}
        -> {"data": [{"embedding": [...], "index": 0}, ...]}

    Returns vectors in input order (sorted by index). Raises on failure.
    """
    payload = json.dumps({"input": texts, "model": _env_model()}).encode()
    _hdrs = {
        "Content-Type": "application/json",
        # Browser User-Agent so the request survives Cloudflare bot-protection at
        # the edge when OLLAMA_URL is a public SaaS hostname (Python-urllib UA is 403'd).
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    }
    _key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if _key:
        _hdrs["Authorization"] = f"Bearer {_key}"
    req = urllib.request.Request(
        f"{url}/v1/embeddings",
        data=payload,
        headers=_hdrs,
    )
    data = _urlopen_json(req, timeout)
    if "data" not in data or not isinstance(data["data"], list):
        raise RuntimeError(f"unexpected embed response from {url}: {str(data)[:200]}")
    # Sort by index to preserve input order (OpenAI may return out of order)
    ordered = sorted(data["data"], key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in ordered]


def _call(url: str, texts: list[str], timeout: int = 120) -> list[list[float]]:
    """Embed texts against ONE endpoint, dispatching on EMBED_PROVIDER."""
    if _env_provider() == "llamacpp":
        return _call_llamacpp(url, texts, timeout)
    return _call_ollama(url, texts, timeout)


def _is_context_size_error(err: Exception) -> bool:
    """True if *err* is an endpoint rejection for exceeding the context window.

    llama.cpp / llama-server returns HTTP 400 with a body containing
    ``exceed_context_size_error``; Ollama may surface a similar message.
    We match on the message text (case-insensitive) so we stay endpoint-agnostic
    and don't depend on urllib's exact exception type.
    """
    msg = str(err).lower()
    return (
        "exceed_context_size" in msg
        or "context size" in msg
        or "context_length" in msg
        or "context window" in msg
        or "too many tokens" in msg
        or "maximum context" in msg
        # llama.cpp / llama-server physical-batch rejection. It returns HTTP 500
        # (not 400) with: "input (N tokens) is too large to process. increase the
        # physical batch size (current batch size: M)". Without these two
        # substrings the error looked generic, so _split_and_retry never fired and
        # the oversized row was dropped instead of truncated to fit.
        or "too large to process" in msg
        or "physical batch size" in msg
    )


def _urlopen_json(req, timeout: int):
    """urlopen + JSON decode, surfacing the HTTP error BODY on failure.

    urllib's HTTPError.__str__() is only "HTTP Error 500: Internal Server
    Error" — the response body is discarded. llama.cpp puts the real reason
    ("input (N tokens) is too large to process...") in that body, so without
    reading it _is_context_size_error() can never match and the truncate-and-
    retry path stays dead. Re-raise with the body appended so the matcher sees it.
    """
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        body = ""
        try:
            body = err.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise RuntimeError(f"{err} body={body}") from err


def _truncate_to_fit(text: str, max_chars: int) -> str:
    """Truncate *text* to *max_chars*, keeping the head (matches ollama truncate=true)."""
    return text[:max_chars] if text and len(text) > max_chars else text


def embed(texts: list[str], timeout: int = 120) -> list[list[float]]:
    """Embed texts with primary→fallback failover. Raises if ALL fail.

    Tries each URL in the chain in order; on any exception, logs loudly
    and moves to the next endpoint. If every endpoint fails, re-raises the
    last error so callers degrade loudly (never silently).

    Clamps every input to 5500 chars (~1850 tokens). nomic-embed-text-v1.5
    refuses inputs over its 2048-token context ceiling (llama.cpp 400, ollama
    silently truncates) — guard every batch row here so no caller's payload
    can 503 the chain. Trim keeps the head (matches ollama truncate=true).
    """
    if not texts:
        return []
    # Per-input clamp (the 2048-token ceiling is per-input, not per-batch).
    max_chars = _env_max_chars()
    if any(t and len(t) > max_chars for t in texts):
        n = sum(1 for t in texts if t and len(t) > max_chars)
        log.warning(
            "embed: clamping %d oversized input(s) (first orig=%d→%d chars) to "
            "stay under the 2048-token ceiling",
            n, next(len(t) for t in texts if t and len(t) > max_chars), max_chars,
        )
        texts = [(t[:max_chars] if t and len(t) > max_chars else t) for t in texts]
    urls = _env_urls()
    last_err: Exception | None = None
    for i, url in enumerate(urls):
        try:
            return _call(url, texts, timeout)
        except Exception as err:
            last_err = err
            # Self-healing: if the endpoint rejected the batch for exceeding
            # its context window, the char-based clamp guessed wrong (remote
            # tokenizers differ). Isolate the oversized row(s) and truncate
            # them progressively until they fit, instead of re-sending the
            # same failing batch forever. This is endpoint-agnostic and
            # kills the infinite retry loop.
            #
            # NOTE: this must ALSO fire for a single-row payload. The listener
            # retries oversized rows as `embed([text])` (len == 1); gating on
            # `len(texts) > 1` sent those straight to `raise`, so a lone
            # oversized row was never embedded and the log showed the generic
            # "no more endpoints" instead of a truncate-and-fit retry.
            # `_split_and_retry` already loops per row, so it handles len == 1.
            if _is_context_size_error(err):
                log.warning(
                    "ollama %s (%s) context-size error on %d-row batch — "
                    "isolating and truncating to fit",
                    "primary" if i == 0 else f"fallback[{i}]", url, len(texts),
                )
                return _split_and_retry(url, texts, timeout)
            remaining = urls[i + 1:]
            log.warning(
                "ollama %s (%s) failed (%s) — %s",
                "primary" if i == 0 else f"fallback[{i}]",
                url, err,
                f"falling back to {remaining}" if remaining else "no more endpoints",
            )
    assert last_err is not None
    log.error("ollama ALL endpoints %s failed: %s", urls, last_err)
    raise last_err


def _split_and_retry(url: str, texts: list[str], timeout: int) -> list[list[float]]:
    """Embed *texts* against ONE endpoint, isolating rows that exceed the
    context window and truncating them progressively until they fit.

    Called when a multi-row batch was rejected for context size. Embeds each
    row individually so one oversized row can't poison the whole batch; any
    row that still exceeds the window is truncated (halving, then stepping
    down) and retried until it fits. Returns vectors in input order.
    """
    out: list[list[float] | None] = [None] * len(texts)
    for idx, text in enumerate(texts):
        if not text:
            out[idx] = []
            continue
        cur = text
        while True:
            try:
                out[idx] = _call(url, [cur], timeout)[0]
                break
            except Exception as err:
                if not _is_context_size_error(err) or len(cur) <= 256:
                    raise
                # Halve, then step down by 25% each pass until it fits.
                cur = cur[: max(256, int(len(cur) * 0.5))]
                log.warning(
                    "embed: truncating oversized row %d to %d chars after "
                    "context-size error — retrying same endpoint",
                    idx, len(cur),
                )
    return [v for v in out if v is not None]


def embed_query(query: str, timeout: int = 30) -> list[float] | None:
    """Embed a single query with failover. Returns vector or None on failure."""
    # Guard: clamp oversized queries. nomic-embed-text-v1.5 has a hard 2048-token
    # ceiling (llama.cpp refuses > n_ctx with 400; ollama silently truncates).
    # Any single query over ~5500 chars / ~1850 tokens blows past the ceiling and
    # 503s the embed chain. Trim to keep the head (matches ollama truncate=true).
    # This is the single choke point for ALL query-embed callers (intent router,
    # recall, hooks) — guard it here, not at individual call sites.
    max_chars = _env_max_chars()
    if query and len(query) > max_chars:
        log.warning(
            "embed_query: truncating %d-char query to %d (%.3f ratio) to stay "
            "under the 2048-token embed ceiling",
            len(query), max_chars, max_chars / len(query),
        )
        query = query[:max_chars]
    try:
        vecs = embed([query], timeout=timeout)
        return vecs[0] if vecs else None
    except Exception as e:
        log.warning("embed query failed (degrading): %s", e)
        return None
