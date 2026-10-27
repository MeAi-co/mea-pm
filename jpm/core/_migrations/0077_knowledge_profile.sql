-- 0077: knowledge is scoped per profile.
--
-- One PG store can serve several Hermes profiles. Facts and rules must not cross
-- that boundary, so each knowledge row records the profile that wrote it and the
-- uniqueness key includes it: two profiles can hold a fact with the same name
-- without one silently overwriting the other.
--
-- Entities stay shared on purpose (a person is the same person in every profile).
-- Reads that walk the entity graph still filter the facts they return through
-- this same scope. Reflections inherit scope from their session, which already
-- records its own profile.

ALTER TABLE public.knowledge ADD COLUMN IF NOT EXISTS profile text;

-- Rows predating the column come from a single-profile install, so they belong to
-- the default profile. Backfilling is mandatory before the column joins the
-- uniqueness key: a NULL there would permit duplicate inserts instead of upserts.
UPDATE public.knowledge SET profile = 'default' WHERE profile IS NULL;

-- Default rather than NULL so a writer that forgets the column lands in one known
-- profile instead of in every profile's recall.
ALTER TABLE public.knowledge ALTER COLUMN profile SET DEFAULT 'default';
ALTER TABLE public.knowledge ALTER COLUMN profile SET NOT NULL;

DROP INDEX IF EXISTS public.idx_knowledge_unique;

CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_unique
    ON public.knowledge (profile, entity_type, name);

CREATE INDEX IF NOT EXISTS idx_knowledge_profile
    ON public.knowledge (profile);
