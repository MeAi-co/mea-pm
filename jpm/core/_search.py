import logging

from ._pg import sync_conn

LOG = logging.getLogger("jpm.search")


# Map of table -> (text_columns, has_fts, id_column, title_column, ts_column,
# weight_column, time_column, desc_column, embedding_col, embed_text_cols)
# embedding_col: the pgvector column (None = not embedded / not vector-searchable)
# embed_text_cols: which columns feed the embedding text (for _text_for / sweepers)
# filter_col: column used to exclude archived rows.
#   knowledge/patterns/projects/sessions -> archived=0
#   messages/agents/user_profiles       -> active=1
#   skills/reflections/imgen_library/tasks -> None (no soft-delete column; include all)
TABLE_CONFIG = {
    "knowledge": (["name", "description", "fingerprint"], True, "id", "name", "search_vector", "weightage", "last_referenced", "description", "embedding", ["name", "description", "fingerprint"], "archived"),
    "sessions": (["title", "system_prompt"], False, "id", "title", None, None, "started_at", None, "embedding", ["title", "system_prompt"], "archived"),
    "messages": (["content", "tool_name"], True, "id", "content", "search_vector", None, "timestamp", None, "embedding", ["content", "tool_name"], "active"),
    "skills": (["name", "description", "content", "tags"], False, "id", "name", None, None, "updated_at", "description", "embedding", ["name", "description", "content", "tags"], None),
    "projects": (["name", "description"], False, "id", "name", None, None, "created_at", "description", None, None, "archived"),
    "reflections": (["insight", "trigger"], False, "id", "insight", None, None, "created_at", None, "embedding", ["insight", "trigger"], None),
    "patterns": (["name", "description"], False, "id", "name", None, None, "last_fired", "description", "embedding", ["name", "description"], "archived"),
    "imgen_library": (["name", "data"], False, "id", "name", None, None, "created_at", "data", "embedding", ["name", "data"], None),
    "tasks": (["title", "body"], False, "id", "title", None, None, "created_at", None, None, None, None),
}


def _search_knowledge(query: str, limit: int = 10, offset: int = 0, table: str = "knowledge") -> tuple[list[dict], bool]:
    """Search any table — splits multi-word queries into OR terms so any match surfaces.
    Returns (results, has_more) — has_more is True if there are more results beyond this page."""
    cfg = TABLE_CONFIG.get(table)
    if not cfg:
        return [], False

    text_cols, has_fts, id_col, title_col, ts_col, weight_col, time_col, desc_col, _emb_col, _emb_text, filter_col = cfg

    try:
        with sync_conn() as conn:
            words = [w.strip() for w in query.split() if w.strip()]
            if not words:
                return [], False

            # Build soft-delete filter: NULL filter_col = no filter
            if filter_col:
                op = "= 0" if filter_col == "archived" else "= 1"
                filter_sql = filter_col + op
            else:
                filter_sql = "1 = 1"

            # Knowledge is per profile: another profile's facts must not surface
            # here. Every other table is shared by design.
            if table == "knowledge":
                from ._profile import knowledge_scope

                scope_sql, scope_params = knowledge_scope()
            else:
                scope_sql, scope_params = "1 = 1", []

            # Fetch limit+1 to detect if there's a next page
            fetch_limit = limit + 1

            # Build ORDER BY: weightage DESC (if exists), then timestamp DESC
            order_parts = []
            if weight_col:
                order_parts.append(f"{weight_col} DESC NULLS LAST")
            if time_col:
                order_parts.append(f"{time_col} DESC NULLS LAST")
            order_clause = ", ".join(order_parts) if order_parts else f"{title_col} ASC"

            if has_fts and ts_col:
                # FTS path: OR-based tsquery on search_vector
                # Sanitize each word: tsquery only accepts alphanumeric, hyphens, apostrophes
                import re
                sanitized = []
                for w in words:
                    clean = re.sub(r'[^\w\'-]', '', w)
                    if clean and len(clean) >= 2:
                        sanitized.append(clean)
                if not sanitized:
                    return [], False
                or_query = " OR ".join(sanitized)
                # Build SELECT with optional weightage/time columns
                _select_cols = [f"{id_col} as id", f"{title_col} as title"]
                if desc_col:
                    _select_cols.append(desc_col)
                if weight_col:
                    _select_cols.append(weight_col)
                if time_col:
                    _select_cols.append(time_col)
                # entity_type is only on the knowledge table — needed by callers for type display
                if table == "knowledge":
                    _select_cols.append("entity_type")
                _select_sql = ", ".join(_select_cols)
                # websearch_to_tsquery handles stop words gracefully (ignores them)
                # and supports | for OR, "quoted phrases" for exact match, - for NOT
                tsq = f"websearch_to_tsquery('english', ?)"
                _rank_col = f"ts_rank({ts_col}, {tsq})"
                rows = conn.fetchall(
                    f"""SELECT {_select_sql}, {_rank_col} as tsrank
                      FROM {table}
                      WHERE {ts_col} @@ {tsq}
                        AND {filter_sql}
                        AND {scope_sql}
                      ORDER BY {_rank_col} DESC, {order_clause}
                      LIMIT ? OFFSET ?""",
                    (or_query, or_query, *scope_params, or_query, fetch_limit, offset)
                )
            else:
                # ILIKE path: OR across all text columns
                like_conditions = " OR ".join(
                    [f"COALESCE({col}, '') ILIKE '%' || ? || '%'" for col in text_cols for _ in words]
                )
                params = [w for col in text_cols for w in words]
                # Build SELECT with optional weightage/time columns
                _select_cols = [f"{id_col} as id", f"{title_col} as title"]
                if desc_col:
                    _select_cols.append(desc_col)
                if weight_col:
                    _select_cols.append(weight_col)
                if time_col:
                    _select_cols.append(time_col)
                # entity_type is only on the knowledge table — needed by callers for type display
                if table == "knowledge":
                    _select_cols.append("entity_type")
                _select_sql = ", ".join(_select_cols)
                rows = conn.fetchall(
                    f"""SELECT {_select_sql}
                       FROM {table}
                       WHERE ({like_conditions})
                         AND {scope_sql}
                       ORDER BY {order_clause}
                       LIMIT ? OFFSET ?""",
                    params + scope_params + [fetch_limit, offset]
                )

            has_more = len(rows) > limit
            results = [dict(r) for r in rows[:limit]]
            return results, has_more
    except Exception as e:
        LOG.error("_search_knowledge failed: %s", e, exc_info=True)
        return [], False
