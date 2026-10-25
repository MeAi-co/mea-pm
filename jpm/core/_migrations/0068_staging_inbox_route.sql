-- 0068_staging_inbox_route.sql
-- Peer-to-peer reply loop: stamp the sender's wire route onto the message so
-- the receiver can reply without a central registry lookup, and link replies
-- to the message they answer.
--
-- WHY THIS MIGRATION EXISTS
-- The staging loop is push-based: agent A POSTs a task to agent B's
-- /staging/webhook, which writes a row into B's LOCAL staging_inbox. For B to
-- reply, it needs A's wire route (magicdns + webhook_port). Rather than query
-- a central registry (which does not exist fleet-wide — every node runs its
-- own jpm-pg), the route RIDES THE MESSAGE: A stamps from_route into the
-- payload, B stores it here, and B's staging_reply tool POSTs back to it.
--
-- Also widens the message_type CHECK to admit 'reply'. Without this the
-- staging_reply tool's INSERT fails the constraint and the reply is lost
-- silently (the webhook returns 500, the sender never hears back).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, DROP CONSTRAINT IF EXISTS.
-- Safe to re-apply on any node.

ALTER TABLE staging_inbox
    ADD COLUMN IF NOT EXISTS from_route jsonb;

ALTER TABLE staging_inbox
    ADD COLUMN IF NOT EXISTS in_reply_to bigint;

CREATE INDEX IF NOT EXISTS idx_staging_inbox_in_reply_to
    ON staging_inbox (in_reply_to)
    WHERE in_reply_to IS NOT NULL;

-- Widen the message_type CHECK to include 'reply'. Drop + re-add is the
-- only way to alter a CHECK in PG; IF EXISTS makes it idempotent.
ALTER TABLE staging_inbox
    DROP CONSTRAINT IF EXISTS staging_inbox_message_type_check;

ALTER TABLE staging_inbox
    ADD CONSTRAINT staging_inbox_message_type_check
    CHECK (message_type = ANY (ARRAY[
        'message','patch_review','notification','alert',
        'task_assignment','role_update','escalation','reply'
    ]::text[]));
