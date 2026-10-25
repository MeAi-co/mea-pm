-- Skill section index — topic-level retrieval for the skill catalog.
--
-- The skills table stores one row per skill with the whole body in `content`,
-- so retrieval is whole-skill: to use one paragraph the agent loads the entire
-- body. This table gives the catalog a section-level unit — each `##` topic in
-- a SKILL.md becomes a row with its own embedding, so skill_choose(sections=True)
-- can return the matching *sections* across multiple skills (cherry-pick)
-- instead of whole bodies.
--
-- Rows are re-derived on every skill write (DELETE + INSERT per skill_id), so
-- the UNIQUE (skill_id, ordinal) constraint keeps the set exact. ON DELETE
-- CASCADE means archiving/deleting a skill drops its sections with it.
--
-- Embedding surface mirrors the live worker's `skill_sections` builder
-- (heading + body) — see jpm/core/_sections.section_text.

CREATE TABLE IF NOT EXISTS skill_sections (
    id bigserial PRIMARY KEY,
    skill_id bigint NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    heading text NOT NULL DEFAULT '',
    body text NOT NULL,
    embedding vector(768),
    embedding_model text,
    embedding_updated_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (skill_id, ordinal)
);

-- HNSW cosine index — same shape as idx_skills_embedding_hnsw.
CREATE INDEX IF NOT EXISTS idx_skill_sections_hnsw
    ON skill_sections USING hnsw (embedding vector_cosine_ops)
    WITH (m='16', ef_construction='64');

-- Lookup by parent skill (write path replaces a skill's sections wholesale).
CREATE INDEX IF NOT EXISTS idx_skill_sections_skill
    ON skill_sections (skill_id);
