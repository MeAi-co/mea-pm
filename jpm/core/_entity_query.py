import logging
import time

from ._entities import _extract_entities
from ._pg import sync_conn

LOG = logging.getLogger("jpm.entity_query")


def _like_pattern(entity: str) -> str:
    """Build a substring-match ILIKE pattern, escaping user-supplied wildcards.

    Wraps in %...% so probing "Sher" matches a stored entity "Sher Fenn",
    and escapes any literal %/_ the caller passed so they can't act as
    wildcards (no injection of the pattern).
    """
    escaped = entity.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _resolve_entity(conn, name: str) -> int:
    # Atomic upsert: INSERT ... ON CONFLICT DO NOTHING RETURNING is race-safe.
    # Two concurrent writers both attempt the insert; exactly one wins and
    # returns the row, the other gets NULL and falls back to a SELECT.
    # The old SELECT-then-INSERT pattern was a TOCTOU race that threw
    # UniqueViolation on entities_name_key under concurrent writes.
    row = conn.fetchone(
        "INSERT INTO entities (name) VALUES (?) "
        "ON CONFLICT (name) DO NOTHING RETURNING entity_id",
        (name,),
    )
    if row:
        return int(row["entity_id"])
    # Race-safe fallback: the INSERT's DO NOTHING guarantees the row exists,
    # but under a shared DB with autocommit the fallback SELECT can run against
    # a snapshot that hasn't yet seen a *concurrent* writer's commit. Retry the
    # SELECT so a fresh snapshot observes the committed row; the row is
    # guaranteed present so a short bounded retry never needs to throw.
    for _ in range(3):
        row = conn.fetchone(
            "SELECT entity_id FROM entities WHERE name = ?", (name,))
        if row:
            return int(row["entity_id"])
        time.sleep(0.05)
    raise RuntimeError(f"entity '{name}' could not be resolved after upsert")


def _link_fact_entities(conn, fact_id: int, text: str) -> None:
    for name in _extract_entities(text):
        eid = _resolve_entity(conn, name)
        conn.execute(
            "INSERT INTO fact_entities (fact_id, entity_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (fact_id, eid),
        )


def _probe_entity(entity: str, limit: int = 10) -> list[dict]:
    try:
        with sync_conn() as conn:
            # Use FTS on the simple dictionary for exact-match entity names
            # (no English stemming — entity names are proper nouns)
            rows = conn.fetchall(
                """SELECT k.id, k.entity_type, k.name, k.description, k.last_referenced,
                          k.weightage
                   FROM knowledge k
                   JOIN fact_entities fe ON fe.fact_id = k.id
                   JOIN entities e ON e.entity_id = fe.entity_id
                   WHERE e.name ILIKE ?
                     AND k.archived = 0
                   ORDER BY k.weightage DESC, k.id DESC
                   LIMIT ?""",
                   (_like_pattern(entity), limit)
                   )
            return rows
    except Exception as e:
        LOG.error("_probe_entity(%s) failed: %s", entity, e, exc_info=True)
        return []


def _related_entities(entity: str, limit: int = 10) -> list[dict]:
    try:
        with sync_conn() as conn:
            rows = conn.fetchall(
                """SELECT DISTINCT k.id, k.entity_type, k.name, k.description,
                          k.weightage, k.last_referenced
                   FROM knowledge k
                   JOIN fact_entities fe ON fe.fact_id = k.id
                   WHERE fe.entity_id IN (
                       SELECT fe2.entity_id
                       FROM fact_entities fe2
                       JOIN entities e ON e.entity_id = fe2.entity_id
                       WHERE e.name ILIKE ?
                   )
                   AND k.archived = 0
                   ORDER BY k.weightage DESC, k.id DESC
                   LIMIT ?""",
                (_like_pattern(entity), limit)
            )
            return rows
    except Exception as e:
        LOG.error("_related_entities(%s) failed: %s", entity, e, exc_info=True)
        return []


def _reason_entities(entities: list[str], limit: int = 10) -> list[dict]:
    if not entities:
        return []
    try:
        with sync_conn() as conn:
            queries = []
            params = []
            for ent in entities:
                queries.append(
                    f"SELECT fact_id FROM fact_entities fe "
                    f"JOIN entities e ON e.entity_id = fe.entity_id "
                    f"WHERE e.name ILIKE ?"
                )
                params.append(_like_pattern(ent))
            if not queries:
                return []
            sql = " INTERSECT ".join(queries)
            rows = conn.fetchall(
                f"""SELECT k.id, k.entity_type, k.name, k.description,
                          k.weightage, k.last_referenced
                   FROM knowledge k
                   WHERE k.id IN ({sql})
                     AND k.archived = 0
                   ORDER BY k.weightage DESC, k.id DESC
                   LIMIT ?""",
                params + [limit]
            )
            return rows
    except Exception as e:
        LOG.error("_reason_entities(%s) failed: %s", entities, e, exc_info=True)
        return []