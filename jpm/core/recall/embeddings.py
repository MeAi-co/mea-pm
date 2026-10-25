"""Embedding service — swappable provider behind one interface.

Default: Ollama (OLLAMA_URL / EMBED_MODEL env, nomic-embed-text).
Provider registry allows a hosted API (OpenAI-compatible) to slot in without
touching any caller. Batch + cache keeps token cost near zero.

Ollama calls delegate to jpm.core._ollama.embed() so the comma-chain
OLLAMA_URL (primary → fallback GPU) and failover logic are shared with the
live embed listener and hybrid retrieval — never re-implemented here.

vLLM provider (EMBED_PROVIDER=vllm) calls an OpenAI-compatible /v1/embeddings
endpoint. Additive — the ollama default is untouched.
"""
import json
import logging
import os
import urllib.request
from functools import lru_cache

from .._ollama import embed as _ollama_embed

LOG = logging.getLogger("jpm.recall.embeddings")

EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "768"))

# vLLM endpoint (OpenAI-compatible). No default host — set VLLM_URL to enable.
VLLM_URL = os.environ.get("VLLM_URL", "")
VLLM_TIMEOUT = int(os.environ.get("VLLM_TIMEOUT", "120"))


class EmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class OllamaEmbeddingProvider(EmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Chain-aware: tries every OLLAMA_URL in order (primary → fallback),
        # logs loudly per failure, raises only when all endpoints are dead.
        return _ollama_embed(texts)


class VllmEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible /v1/embeddings against a vLLM server.

    Additive provider — only active when EMBED_PROVIDER=vllm. Uses the same
    urllib style as _ollama.py (no new deps). Raises on failure so callers
    degrade loudly, never silently.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": EMBED_MODEL, "input": texts}).encode()
        req = urllib.request.Request(
            f"{VLLM_URL}/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=VLLM_TIMEOUT) as resp:
            data = json.loads(resp.read())
        if "data" not in data or not isinstance(data["data"], list):
            raise RuntimeError(f"unexpected vLLM embed response: {str(data)[:200]}")
        # vLLM returns data as a list of {index, embedding, object}; order by index.
        ordered = sorted(data["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in ordered]


@lru_cache(maxsize=4096)
def _embed_one_cached(text: str) -> tuple[float, ...]:
    return tuple(_get_provider().embed([text])[0])


def _get_provider() -> EmbeddingProvider:
    provider_name = os.environ.get("EMBED_PROVIDER", "ollama")
    if provider_name == "ollama":
        return OllamaEmbeddingProvider()
    if provider_name == "vllm":
        return VllmEmbeddingProvider()
    if provider_name == "llamacpp":
        # llama.cpp does NOT go through VllmEmbeddingProvider: _ollama.embed()
        # already dispatches to _call_llamacpp (OpenAI /v1/embeddings) when
        # EMBED_PROVIDER=llamacpp, AND gives us the primary→fallback chain, the
        # 2048-token per-input clamp, and the shrink-and-retry self-heal.
        # Routing straight to VLLM_URL skips all three (400 on long inputs).
        # Wiring fix 2026-10-02: de097fc added the llamacpp backend to
        # _ollama.py but never registered it here, so every sweep/query under
        # EMBED_PROVIDER=llamacpp raised "unknown provider" — silent, for weeks.
        return OllamaEmbeddingProvider()
    raise ValueError(f"unknown EMBED_PROVIDER: {provider_name}")


def embed_texts(texts: list[str], cache: bool = True) -> list[list[float]]:
    if cache and len(texts) == 1:
        return [list(_embed_one_cached(texts[0]))]
    return _get_provider().embed(texts)


def embed_query(query: str) -> list[float] | None:
    try:
        return embed_texts([query])[0]
    except Exception as e:
        LOG.warning("embed failed (degrading to FTS): %s", e)
        return None
