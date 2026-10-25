-- 0052_add_id_columns_to_project_child_tables.sql
-- Give project_folders, project_meta, and discovered_repos an int serial id
-- column so the sqlite3-compat shim's auto-append RETURNING id works on them.
-- Without an id column, the shim's fallback path issues a ROLLBACK that kills
-- the enclosing write_txn (undoing the projects insert in create_project).
-- Existing natural-key PKs are preserved.

ALTER TABLE project_folders ADD COLUMN id serial;
ALTER TABLE project_meta ADD COLUMN id serial;
ALTER TABLE discovered_repos ADD COLUMN id serial;
