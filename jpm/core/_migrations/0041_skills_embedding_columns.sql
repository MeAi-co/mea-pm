-- Migration 0041: Add pgvector embedding columns to public.skills
--
-- Schema: public
--
-- Context:
--   Migration 0030 creates trg_skills_embed_notify on public.skills, firing
--   notify_embed_queue() which references NEW.embedding. But migration 0029
--   only adds embedding columns to the 5 retrieval tables (knowledge,
--   messages, sessions, reflections, patterns) — NOT skills. And the base
--   schema's CREATE TABLE public.skills (line ~998 of _schema_pg.sql) has no
--   embedding columns either.
--
--   Result: on a fresh node, the first INSERT/UPDATE into public.skills
--   (e.g. the skill-prefill backfill) crashes with:
--       record "new" has no field "embedding"
--   because the trigger fires and the function reads NEW.embedding, which
--   doesn't exist. Summer's node only worked because the column was added
--   ad-hoc via psql; Maria's node hit the crash during skill prefill.
--
--   This migration closes the gap so fresh fleet nodes get the column
--   automatically. It mirrors 0029's pattern exactly (vector(768) + model +
--   updated_at + HNSW index) so the embed_listener / _embed_worker can
--   populate skill embeddings the same way as the other retrieval tables.
--
-- Why this is safe:
--   - ADD COLUMN IF NOT EXISTS is idempotent — re-runs are no-ops.
--   - CREATE INDEX IF NOT EXISTS is idempotent.
--   - The trigger already exists (from 0030); this just makes its target
--     column real. No trigger changes needed.
--
-- Changes:
--   1. embedding columns on public.skills
--   2. HNSW cosine index on skills.embedding
--   3. GRANT UPDATE on the embedding columns to the embedder role
--      (mirrors 0029's grants; 0030 already grants SELECT + UPDATE on skills
--      to embedder, but only when the column exists — this makes the UPDATE
--      grant unconditional and correct).

-- 1. embedding columns on public.skills
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS embedding            vector(768);
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS embedding_model      text;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS embedding_updated_at timestamptz;

-- 2. HNSW cosine index (matches idx_<table>_embedding_hnsw convention)
CREATE INDEX IF NOT EXISTS idx_skills_embedding_hnsw
    ON public.skills USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- 3. Grant write on the embedding columns to the embedder role (idempotent)
DO $$
BEGIN
    IF to_regclass('public.skills') IS NOT NULL THEN
        EXECUTE 'GRANT UPDATE (embedding, embedding_model, embedding_updated_at)
                 ON TABLE public.skills TO embedder';
    END IF;
END $$;
