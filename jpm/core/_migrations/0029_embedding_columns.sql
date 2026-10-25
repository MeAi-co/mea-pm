-- 0029_embedding_columns.sql
-- Add pgvector embedding columns + HNSW indexes to the 5 retrieval tables.
--
-- Why: the vector recall stack (hybrid_search_knowledge, recall_context,
-- prefetch, embed_watchdog, _embed_worker) auto-detects the `embedding`
-- column and silently falls back to FTS when it's absent. On this node the
-- columns were added ad-hoc via psql (never captured in a migration), so a
-- fresh fleet node pulling the code would get NO vector recall — the exact
-- silent-degradation footgun we've been eliminating. This migration makes
-- the vector schema reproducible fleet-wide: every node gets it
-- automatically on next restart, no manual tinkering, no drift.
--
-- Idempotent via IF NOT EXISTS — safe on nodes that already have the columns
-- (this node included). Matches the live column types (vector(768), text,
-- timestamptz) and the existing HNSW index params (m=16, ef_construction=64)
-- and naming convention (idx_<table>_embedding_hnsw).

-- 1. pgvector extension (idempotent)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. embedding columns on the 5 retrieval tables
ALTER TABLE public.knowledge   ADD COLUMN IF NOT EXISTS embedding            vector(768);
ALTER TABLE public.knowledge   ADD COLUMN IF NOT EXISTS embedding_model      text;
ALTER TABLE public.knowledge   ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz;

ALTER TABLE public.messages    ADD COLUMN IF NOT EXISTS embedding            vector(768);
ALTER TABLE public.messages    ADD COLUMN IF NOT EXISTS embedding_model      text;
ALTER TABLE public.messages    ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz;

ALTER TABLE public.sessions    ADD COLUMN IF NOT EXISTS embedding            vector(768);
ALTER TABLE public.sessions    ADD COLUMN IF NOT EXISTS embedding_model      text;
ALTER TABLE public.sessions    ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz;

ALTER TABLE public.reflections ADD COLUMN IF NOT EXISTS embedding            vector(768);
ALTER TABLE public.reflections ADD COLUMN IF NOT EXISTS embedding_model      text;
ALTER TABLE public.reflections ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz;

ALTER TABLE public.patterns    ADD COLUMN IF NOT EXISTS embedding            vector(768);
ALTER TABLE public.patterns    ADD COLUMN IF NOT EXISTS embedding_model      text;
ALTER TABLE public.patterns    ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz;

-- 3. HNSW cosine indexes (match live params + naming convention)
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_hnsw
    ON public.knowledge USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_messages_embedding_hnsw
    ON public.messages USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_sessions_embedding_hnsw
    ON public.sessions USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_reflections_embedding_hnsw
    ON public.reflections USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_patterns_embedding_hnsw
    ON public.patterns USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
