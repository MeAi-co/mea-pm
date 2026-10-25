-- 0066_skills_role_tags.sql
-- Schema descriptor for skills.role_tags + idempotent seed of the builtin
-- skill<->role bindings.
--
-- Companion to 0065_skills_role_tags.sql (which created the column). This
-- migration does two idempotent, additive things:
--
--   1. Attaches a COLUMN COMMENT so the schema is self-describing — the same
--      "agent's memory vault is self-describing" pattern as 0056_table_comments.
--   2. SEEDS the builtin skills' role bindings on any node where they are
--      still untagged. Guarded by `role_tags = ''` so it NEVER clobbers a
--      curation a node has already applied (safe to re-run, safe on the fleet).
--
-- What role_tags means
-- --------------------
-- Comma-separated role slugs (matching the host agent roles/<slug>.yaml) that a
-- skill BELONGS TO. Empty string = role-agnostic / global (always allowed).
-- M:N by design — one skill may serve several roles. No join table; this is the
-- same "TAGS not tables" pattern used for knowledge/project scope binding.
--
-- Consumers: skills_tool / skill_choose_tool / project_skills_tool render a
-- `role` field from this column, hinting the agent to self-check its active
-- role (role_choose) before relying on a role-specific skill.
--
-- Idempotent: COMMENT ON COLUMN overwrites; UPDATEs are guarded — safe to re-run.

COMMENT ON COLUMN public.skills.role_tags IS
  'Comma-separated role slugs (matching the host agent roles/<slug>.yaml) this skill belongs to. Empty = role-agnostic/global. M:N, no join table. Rendered as the `role` field in skill_view/skills_list/skill_choose; hints the agent to role_choose(name=...) before using a role-specific skill.';

-- ── Seed builtin bindings (non-clobbering) ─────────────────────────────────
-- Only touches rows still at the default empty string, so a node whose
-- curator has retagged a skill is left alone.

-- programmer: engineering / rigor / code-execution skills
UPDATE public.skills SET role_tags = 'programmer'
 WHERE role_tags = '' AND name IN (
   'claude-code', 'codex', 'opencode',
   'plan', 'spike', 'simplify-code',
   'systematic-debugging', 'test-driven-development', 'requesting-code-review',
   'node-inspect-debugger', 'python-debugpy'
 );

-- assistant: generalist ops / diagnostics / daily-driver skills
UPDATE public.skills SET role_tags = 'assistant'
 WHERE role_tags = '' AND name IN (
   'ops'
 );
