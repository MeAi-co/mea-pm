# Changelog

## 0.1.2

### Added

- **Sessions record the profile that produced them.** The mirror now writes
  `sessions.profile`, resolved from the source row's `profile_name`, falling
  back to the profile that owns the store: a launcher-pinned
  `HERMES_PROFILE_NAME`/`HERMES_PROFILE` first, then the name derived from the
  home directory (`<home>/profiles/<name>`, or `default` for the root home).
  Previously the column was left unwritten, so a store shared by several
  profiles could not attribute a session to one. Rows written before the
  column existed keep their value on re-mirror rather than being overwritten
  with a NULL.

### Notes

- One shared store is the intended topology for multiple profiles: separate
  databases cannot be joined for cross-profile recall, and the plugin targets
  the `public` schema. Attribution is per session; knowledge and entities
  remain shared by design.

## 0.1.1

### Fixed

- **Real messages were being deleted.** The pre-migration dedupe in
  `jpm/core/_pg.py` grouped by `(session_id, role, timestamp)`. Core persists
  platform messages with whole-second timestamps, so distinct messages from
  the same role in the same second collided and every row but `MIN(id)` was
  deleted. Impact: messages were silently dropped from recall for affected
  sessions. The key is now `message_id` (the source row id), falling back to a
  content hash when it is null. A true duplicate cannot exist anyway:
  `messages_session_message_id_idx` is unique, so the old key could only ever
  delete distinct messages.
- **The mirror over-reported inserts.** `inserted` was incremented per loop
  iteration while the INSERT used `ON CONFLICT DO NOTHING`, so swallowed rows
  were logged as written. It now reports the driver's `rowcount`.
- **Gaps were permanent.** The mirror only read rows above
  `MAX(message_id)`, so anything missing below that floor was never retried.
  Each turn now compares against `state.db` and backfills the missing id set;
  re-insertion is idempotent through `msg_key`.
- **`sessions.message_count` copied a stale source value.** It is now
  recalculated from the rows PG actually holds, so recall reports the true
  count instead of core's drift.
- **`chat_name` and `user_name` were never mirrored** even though both columns
  exist and both are present in `state.db`'s `origin_json`. They are now
  parsed and written.
- **False `SCHEMA DRIFT` warnings.** A table missing from PG was reported as
  having every column missing, because an empty `information_schema.columns`
  result was treated as drift. Tables absent from the live schema are now
  skipped; genuine column drift is still detected.

### Notes

- Timestamps are **local wall time by design**, written with
  `datetime.fromtimestamp` into `timestamp without time zone`, matching the
  source store. Mirrored values match the source store exactly. Consumers must
  not reinterpret these values as UTC. Rows written before a host timezone
  change remain on the earlier clock.

### Known

- `chat_topic` is mirrored but never populated on current core: it is read
  from `origin_json.chat_topic`, which is written as `null` on every row, so
  `session_topics` stays empty.
