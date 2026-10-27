# Changelog

## 0.2.0

### Added

- **Profile-aware knowledge store.** `knowledge` gains a `profile` column, and
  its uniqueness key becomes `(profile, entity_type, name)`. One shared vault can
  now serve several Hermes profiles while each profile owns its own facts.
- **Profile resolution follows core.** The owning profile is resolved from the
  `hermes_home` core injects into the memory provider, falling back to an
  explicit env pin, so a multiplexed gateway attributes each routed turn to the
  profile it belongs to rather than the profile that launched the process.
- **Cross-profile opt-in.** Reads are scoped to the calling profile by default;
  `JPM_KNOWLEDGE_SCOPE=all` widens search, listings, entity probes, and prompt
  injection to every profile in the vault.
- **Migration 0077.** Adds the column, backfills existing rows, and rebuilds the
  unique index. Applied by the plugin's own schema runner on load. Fresh
  installs get the same shape from the base schema.

### Changed

- `entities` remain shared across profiles on purpose: a person or system is the
  same thing in every profile, and fact rows returned through the graph are
  still filtered by profile scope.
- `reflections` inherit their profile through `sessions.profile` rather than
  carrying a label of their own.
- Every knowledge read path is scoped: full-text search, LIKE fallback, vector
  search and fetch-by-id, knowledge listing, single-fact fetch, entity probe /
  related / reason, prompt injection, and the memory tool's own list and remove
  actions.

### Migration notes

- Existing facts are labeled with the default profile by the migration, so a
  single-profile install reads exactly what it read before.
- `ON CONFLICT` targets on `knowledge` must match the new key; writing against
  the old two-column target will fail rather than silently duplicate.

### Side loops

- `mea_sessions` 0.1.2: sessions record the profile that produced them, and a
  re-mirror preserves an existing label instead of overwriting it with NULL.

See `side_loops/mea_sessions/CHANGELOG.md` for the mirror's own history.
