"""Single JPM tool schema — unified jpm() replaces the old 4-tool split."""

JPM_SCHEMA = {
    "name": "jpm",
    "description": (
        "jpm is your MEMORY VAULT, your persistent brain, the context Library. Use it to fetch and store information "
        "about anything. Check your vault for stored facts and past context before re-deriving or re-asking. "
        "It is NOT a general search engine — for live/external content (web pages, links, files, system state) "
        "go to the live source first; the vault only holds what was previously stored. "
        "Users may call it Memory/VAULT. USE it for tables/schema/query to inspect and manipulate ANY table in the PG "
        "database directly: list tables, describe columns, run arbitrary SQL, create/rename "
        "tables, manage indexes. You never need PG credentials; the connection is handled "
        "internally. It is also the single entry point for ALL YOUR Memory and facts "
        "(knowledge, reflections, patterns, sessions, skills) — fetch sections, write state, "
        "search, manage facts, give feedback. Every call returns clean structured markdown "
        "— headers, bullet lists, and **jpm error:** / **jpm <action> ok** lines. "
        "USE jpm BEFORE guessing, re-deriving, or re-asking — the answer is probably already "
        "stored here.\n\n"
        "ACTIONS:\n"
        "--- Fetch ---\n"
        "• fetch — Read structured sections: pulse, active, loops, knowledge, reflections, "
        "capabilities, task_context. Pass section= + optional filter= for targeted queries. "
        "For knowledge, filter='search:keywords' runs VECTOR-FIRST semantic search "
        "(pgvector + Ollama embeddings), so paraphrased/non-exact queries work; FTS5 "
        "full-text is only a fallback when embeddings are unavailable. "
        "filter='entity:MySystem' shows all facts linked to that entity.\n"
        "--- Update ---\n"
        "• update — Write to any section: pulse, active, loops, resolve_loop, knowledge, "
        "reflection, capability, task_context. Content uses key:value format for most sections.\n"
        "--- Knowledge CRUD ---\n"
        "• add — Store a fact. Pass name= (title) and content= (body/details).\n"
        "• get — Get full entry by id. Pass fact_id= and table= (default: knowledge). Returns all columns.\n"
        "• search — Search any table (knowledge, sessions, skills, projects, tasks, etc). Pass table= to target. Default: knowledge.\n"
        "• probe — ALL facts linked to an entity.\n"
        "• related — Facts sharing entities with a given entity.\n"
        "• reason — Facts connected to MULTIPLE entities simultaneously.\n"
        "• contradict — Find potentially conflicting facts.\n"
        "• list — List recent facts.\n"
        "• update — Adjust a fact's weightage (weight_delta). Positive bumps helpful_count, negative bumps stale_count.\n"
        "• remove — Archive a fact (soft delete).\n"
        "--- Feedback ---\n"
        "• helpful — Mark a fact as useful (raises weightage, bumps helpful_count).\n"
        "• unhelpful — Mark a fact as outdated (lowers weightage, bumps stale_count).\n"
        "--- Schema / SQL (lite pgadmin) ---\n"
        "• tables — List all tables in the schema (no args).\n"
        "• schema — Describe a table's columns, types, and nullability. Pass table=.\n"
        "• create_table — Create a table. Pass name= + columns= (list of 'name type [constraints]') "
        "or raw sql= for full control.\n"
        "• rename_table — Rename a table. Pass name= (old) + new_name=.\n"
        "• index — Manage indexes. Pass op= (list/create/drop/rebuild). "
        "list needs table=; create needs name= + table= + columns=; drop/rebuild need name=.\n"
        "• query — Run ARBITRARY SQL against the PG database (read AND write). "
        "Pass sql=. SELECT/WITH return rows (up to `limit`, default 100, max 2000). "
        "Each cell value is returned in full unless it exceeds `truncate` (default 100 chars) — "
        "over-long values are cut with an explicit `…[+N chars]` marker, and the PK column "
        "(id) is ALWAYS shown in full so you can fetch the whole row with `row` "
        "table=<table> id=<pk> or `get`. Pass truncate=0 to return every value in full in one pass. "
        "INSERT/UPDATE/DELETE/DDL return affected-row count. "
        "This is the escape hatch for any table operation the structured actions don't cover — "
        "no need to hunt for PG credentials, the connection is handled internally. "
        "DESTRUCTIVE statements (DROP/TRUNCATE/DELETE/ALTER/REINDEX) on CORE tables "
        "(knowledge, messages, sessions, skills, etc.) are HARD-BLOCKED. "
        "On user-created tables they require confirm=true to proceed.\n"
        "• row — Fetch ONE full row by primary key. Pass table= + id=. Returns EVERY "
        "column with the FULL value, no truncation — the depth step of the two-pass pattern "
        "(query for fast triage, then row to pull a specific row in full).\n\n"
        "POWER: jpm reaches the SAME database the memory layer uses. Inspect anything with "
        "tables/schema/query — no credentials needed, connection handled internally. "
        "If you can't remember whether a fact is stored, or you need a table's columns, "
        "or you want to run a quick SQL check, jpm is the fastest path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "fetch", "update",
                    "add", "get", "search", "probe", "related", "reason",
                    "contradict", "list", "remove",
                    "helpful", "unhelpful",
                    "tables", "schema", "query", "row",
                    "create_table", "rename_table", "index",
                ],
                "description": (
                    "Which operation to perform. fetch/update for structured sections "
                    "(pulse, active, loops, knowledge, reflections, capabilities, task_context). "
                    "add/search/probe/related/reason/contradict/list for knowledge CRUD. "
                    "helpful/unhelpful for fact feedback. "
                    "tables/schema/query/row for schema browsing and arbitrary SQL. "
                    "create_table/rename_table/index for table and index DDL."
                ),
            },
            "section": {
                "type": "string",
                "enum": [
                    "pulse", "active", "loops", "resolve_loop",
                    "knowledge", "reflection", "reflections",
                    "capability", "capabilities", "task_context",
                ],
                "description": (
                    "REQUIRED for fetch and update. Which memory section to read/write. "
                    "fetch: pulse, active, loops, knowledge, reflections, capabilities, task_context. "
                    "update: pulse, active, loops, resolve_loop, knowledge, reflection, capability, task_context."
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "Content for add or update actions. "
                    "For add: the fact body/details. "
                    "For update: key:value format — "
                    "'status:nominal summary:brief', "
                    "'focus:what project:proj status:ready', "
                    "'content:the issue project:proj priority:high', "
                    "'type:system name:MySystem description:what it does', "
                    "'insight:the lesson trigger:why impact:8', "
                    "'tool:tool_name', "
                    "'project_name:proj milestone:step status:done'."
                ),
            },
            "query": {
                "type": "string",
                "description": (
                    "Search query string. Required for: search (semantic/vector-first), "
                    "contradict (find conflicts). "
                    "For fetch mode with knowledge section, use filter='search:term' instead."
                ),
            },
            "entity": {
                "type": "string",
                "description": "Entity name for probe or related lookups.",
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of entity names for reason (find connections between multiple entities).",
            },
            "fact_id": {
                "type": "integer",
                "description": "Fact record ID. Required for: get, helpful, unhelpful.",
            },
            "category": {
                "type": "string",
                "enum": ["user_pref", "project", "tool", "general", "identity", "soul", "dna", "rule"],
                "description": "Category for add action (default: general). Maps to entity_type in knowledge.",
            },
            "name": {
                "type": "string",
                "description": "Title/name for the fact (action='add' only). Stored as the knowledge entry name. Auto-generated from content if omitted.",
            },
            "fingerprints": {
                "type": "string",
                "description": "JSON object of search aliases for action='add'. e.g. '{\"aliases\": [\"team\", \"infra\", \"nodes\"]}' so searching 'team' finds this entry. Stored in fingerprint column and included in FTS search.",
            },
            "tags": {
                "type": "string",
                "description": "Comma-separated tags (reserved for future use).",
            },
            "weight_delta": {
                "type": "number",
                "description": "Weightage adjustment for the update action (default: 0). Applied to knowledge.weightage (clamped 0-1); positive also bumps helpful_count, negative bumps stale_count.",
            },
            "min_weightage": {
                "type": "number",
                "description": "Minimum weightage threshold for search results (default: 0.3). Results below this are filtered out.",
            },
            "weightage": {
                "type": "number",
                "description": "Priority score for add action (0.0-1.0, default 0.5). Higher = more important. Entries with weightage >= 0.70 get full injection; 0.21-0.69 get breadcrumbs; <=0.20 skipped.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return. For search/list/knowledge: default 10, max 50. For action='query': default 100, max 2000 (rows).",
            },
            "offset": {
                "type": "integer",
                "description": "Page offset for pagination (action='search' only). Default: 0. Use offset=10 for page 2, offset=20 for page 3, etc.",
            },
            "table": {
                "type": "string",
                "description": (
                    "Table name for action='search', 'schema', or 'row'. Default: knowledge. "
                    "Any table in the PG schema is valid (e.g. 'sessions', 'messages', 'skills', "
                    "'projects', 'tasks', 'reflections', 'patterns', or any user-created table). "
                    "Use action='tables' to list them all."
                ),
            },
            "sql": {
                "type": "string",
                "description": (
                    "Arbitrary SQL for action='query'. SELECT/WITH return rows — up to `limit` "
                    "(default 100, max 2000); pass limit= to raise the cap when the result set is "
                    "small, and add SQL OFFSET to the statement for paging. Long cell values are "
                    "cut to `truncate` chars (default 100) with an explicit '…[+N chars]' marker; "
                    "pass truncate=0 for full values. The id/PK column is always shown in full so "
                    "you can fetch the whole row with action='row'. INSERT/UPDATE/DELETE/DDL "
                    "return affected-row count. Use $1, $2 placeholders with params= for values. "
                    "This runs against the PG database directly — read AND write."
                ),
            },
            "id": {
                "type": "integer",
                "description": (
                    "Primary key value. Required for action='row' (with table=) to fetch a single "
                    "full row by id — the depth step after a truncated query."
                ),
            },
            "truncate": {
                "type": "integer",
                "description": (
                    "For action='query': max chars per cell value (default 100). Pass truncate=0 "
                    "to return every value in full (no truncation) in one pass; pass a number to "
                    "set a custom cutoff. The id/PK column is always shown in full regardless."
                ),
            },
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional parameter values for action='query' when using $1, $2 placeholders.",
            },
            "confirm": {
                "type": "boolean",
                "description": "Required for action='query' with a DESTRUCTIVE statement (DROP/TRUNCATE/DELETE/ALTER/REINDEX) on a NON-core (user-created) table. Set confirm=true to proceed. Core tables are hard-blocked regardless. Omit for SELECT/INSERT/UPDATE and all read-only queries.",
            },
            "new_name": {
                "type": "string",
                "description": "New name for action='rename_table'.",
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column definitions for action='create_table' (list of 'name type [constraints]') or column names for action='index' op=create.",
            },
            "op": {
                "type": "string",
                "enum": ["list", "create", "drop", "rebuild"],
                "description": "Operation for action='index': list (show indexes on a table), create, drop, or rebuild.",
            },
            "filter": {
                "type": "string",
                "description": (
                    "Optional filter string for fetch mode. Key:value format. "
                    "For knowledge: 'search:full text query' (semantic/vector-first), "
                    "or 'entity:MySystem' (entity probe). "
                    "For loops: 'priority:high' or 'project:trading_bot'. "
                    "For reflections: 'session_id:abc123' or 'impact:8'. "
                    "For capabilities: 'proficiency:high'. "
                    "For task_context: 'project_name:trading_bot' or 'status:pending'."
                ),
            },
        },
        "required": ["action"],
    },
}
