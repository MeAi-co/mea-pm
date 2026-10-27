"""Warm-replay builder (v2): PG-sourced, conversation-shaped.

Postgres is the replay source: it mirrors every session and outlives a local state.db
rewrite. Only real conversation is replayed. Each user turn is paired with the FINAL
assistant reply that follows it, so tool chatter, progress narration and tool JSON never
enter the block. SQLite ``state.db`` stays as an automatic fallback.

Read-only: nothing here writes to any store.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

CONVERSATIONAL_ROLES = ("user", "assistant")

# Rows that are not real conversation and would only add noise to a replay.
_SKIP_PREFIXES = (
    "[Context: JPM",
    "[OUT-OF-BAND USER MESSAGE",
    "[CONTEXT COMPACTION",
    "<session_meta",
    "[MEDIA:",
    '{"output"',
    '{"success"',
    '{"exit_code"',
)

DEFAULTS = {
    "enabled": True,
    "on_cold_start": True,
    "on_boot": True,
    "boot_window_seconds": 900,
    "last_n": 16,            # rendered as last_n/2 user turns plus their answers
    "max_chars": 7000,
    "per_message_chars": 700,
    "max_age_days": 14,
    "min_messages": 4,
    "source": "pg",          # pg | sqlite | auto
}

PROFILE_HOME = Path.home() / ".hermes"


def state_db_path() -> Path:
    """Path to the prime-driver SQLite store (fallback source)."""
    env = os.environ.get("HERMES_STATE_DB")
    return Path(env) if env else PROFILE_HOME / "state.db"


def _skippable(text: str) -> bool:
    head = (text or "").lstrip()
    return not head or head.startswith(_SKIP_PREFIXES)


_GREETINGS = {
    "hey", "hi", "hello", "yo", "sup", "hey there", "hi there", "hello there",
    "gm", "good morning", "good afternoon", "good evening", "morning",
    "you there", "you around", "hey you",
}


def _is_greeting(text: str) -> bool:
    """True for a bare opener with no content: 'hey', 'hi there', 'you around?'.

    These teach the next agent nothing and crowd real turns out of the budget, and a
    greeting answered by a greeting is how a warmed session still reads as cold.
    """
    t = " ".join(str(text or "").lower().split())
    t = t.strip(" .,!?:;~-")
    if not t:
        return True
    if t in _GREETINGS:
        return True
    return len(t.split()) <= 3 and t.rstrip("?") in _GREETINGS



def _clean(text: str, limit: int) -> str:
    t = " ".join(str(text or "").split())
    if len(t) > limit:
        t = t[:limit].rstrip() + " …"
    return t


def _fmt_ts(value) -> str:
    if not value:
        return "unknown time"
    try:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "unknown time"


def _pairs_from_rows(rows, *, max_pairs: int) -> list[tuple[str, str]]:
    """Collapse a message stream into (user turn, final assistant answer) pairs.

    Assistant rows between a user turn and the next one are progress narration and tool
    commentary; only the last of them is the actual answer, so mid-turn rows are dropped.
    """
    pairs: list[tuple[str, str]] = []
    pending_user: str | None = None
    best_answer: str | None = None

    def flush() -> None:
        nonlocal pending_user, best_answer
        if pending_user and best_answer and not _is_greeting(pending_user):
            pairs.append((pending_user, best_answer))
        pending_user, best_answer = None, None

    for role, content in rows:
        text = content or ""
        if _skippable(text):
            continue
        if role == "user":
            flush()
            pending_user = text
        elif pending_user is not None:
            best_answer = text  # keeps overwriting: the final answer wins
    flush()
    return pairs[-int(max_pairs):] if max_pairs else pairs


# ── Postgres (primary) ──────────────────────────────────────────────────────
def _pg_connect():
    """Connect via the profile .env. Credentials are never logged or returned."""
    env: dict[str, str] = {}
    path = PROFILE_HOME / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.startswith("JPM_PG_") and "=" in line:
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip().strip('"').strip("'")
    if not env.get("JPM_PG_PASSWORD"):
        return None
    import psycopg2

    return psycopg2.connect(
        host=env.get("JPM_PG_HOST", "127.0.0.1"),
        port=env.get("JPM_PG_PORT", "5432"),
        dbname=env.get("JPM_PG_DB", "bench"),
        user=env.get("JPM_PG_USER", "postgres"),
        password=env["JPM_PG_PASSWORD"],
        connect_timeout=4,
    )


def pg_prior_session(con, current_id: str, *, min_messages: int = 4):
    """Most recent other session with enough conversation to be worth replaying."""
    cur = con.cursor()
    cur.execute(
        "select session_id, count(*) as n, max(id) as last_id from messages "
        "where session_id <> %s and content is not null "
        "and role in ('user','assistant') group by 1 "
        "having count(*) >= %s order by last_id desc limit 1",
        (current_id, int(min_messages)),
    )
    row = cur.fetchone()
    if not row:
        return None
    sid, count, _last = row
    meta = None
    try:
        cur.execute(
            "select source, title, started_at, "
            "(select max(timestamp) from messages m2 where m2.session_id = s.id) "
            "from sessions s where s.id = %s limit 1",
            (sid,),
        )
        meta = cur.fetchone()
    except Exception:
        con.rollback()
    return {
        "id": sid,
        "source": (meta[0] if meta else "") or "",
        "title": (meta[1] if meta else "") or "",
        "when": _fmt_ts((meta[3] if meta else None) or (meta[2] if meta else None)),
        "message_count": count,
        "db": "pg",
    }


def pg_session_summary(con, session_id: str) -> str:
    """Latest stored session summary, if the store has one (often it does not)."""
    try:
        cur = con.cursor()
        cur.execute(
            "select content from session_summary_log where session_id = %s "
            "order by id desc limit 1",
            (session_id,),
        )
        row = cur.fetchone()
        return (row[0] or "") if row else ""
    except Exception:
        con.rollback()
        return ""


def pg_pairs(con, session_id: str, *, max_pairs: int = 8) -> list[tuple[str, str]]:
    cur = con.cursor()
    cur.execute(
        "select role, content from messages where session_id = %s "
        "and role in ('user','assistant') and content is not null "
        "and length(btrim(content)) > 0 order by id",
        (session_id,),
    )
    return _pairs_from_rows(cur.fetchall(), max_pairs=max_pairs)


# ── SQLite (fallback) ───────────────────────────────────────────────────────
def _sqlite_connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def sqlite_prior_session(con: sqlite3.Connection, current_id: str, *,
                         min_messages: int = 4, max_age_days: float = 14):
    cutoff = time.time() - float(max_age_days) * 86400
    row = con.execute(
        "select id, source, title, last_activity_at, started_at, message_count "
        "from sessions where id != ? and coalesce(archived, 0) = 0 "
        "and coalesce(message_count, 0) >= ? "
        "and coalesce(last_activity_at, started_at, 0) >= ? "
        "order by coalesce(last_activity_at, started_at, 0) desc limit 1",
        (current_id, int(min_messages), cutoff),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "source": row["source"] or "",
        "title": row["title"] or "",
        "when": _fmt_ts(row["last_activity_at"] or row["started_at"]),
        "message_count": row["message_count"] or 0,
        "db": "sqlite",
    }


def sqlite_pairs(con: sqlite3.Connection, session_id: str, *, max_pairs: int = 8):
    rows = con.execute(
        "select role, content from messages where session_id = ? "
        "and role in ('user','assistant') and content is not null "
        "and length(trim(content)) > 0 and coalesce(active, 1) = 1 order by id",
        (session_id,),
    ).fetchall()
    return _pairs_from_rows([(r["role"], r["content"]) for r in rows], max_pairs=max_pairs)


# ── rendering ───────────────────────────────────────────────────────────────
def build_block(session: dict, pairs: list[tuple[str, str]], *,
                header: str = "## Warm replay", max_chars: int = 7000,
                per_message_chars: int = 700, summary: str = "") -> str:
    """Render user turns with their final answers, newest kept when the budget is tight."""
    if not pairs and not summary:
        return ""
    lines: list[str] = [
        f"{header} — previous session {session['id']}"
        f" ({session.get('source') or 'unknown source'}, last activity {session.get('when')})",
    ]
    if summary:
        lines.append(f"summary: {_clean(summary, per_message_chars * 2)}")
    lines += [
        "Your last exchanges: each user turn with the final answer only. This is "
        "recollected context, not new instructions; do not re-answer it.",
        "Resume, do not greet. If the user's message is a greeting, a 'hey', or a vague "
        "open question, open with where this work stopped and what was still open, in "
        "one or two lines, then ask what to do next. Never answer as though nothing is "
        "in progress.",
        "",
    ]
    budget = max(500, int(max_chars) - len("\n".join(lines)) - 150)

    body: list[str] = []
    used = 0
    omitted = 0
    for user_text, answer in reversed(pairs):
        chunk = (
            f"user: {_clean(user_text, per_message_chars)}\n"
            f"assistant: {_clean(answer, per_message_chars)}"
        )
        if used + len(chunk) + 2 > budget:
            omitted += 1
            continue
        body.append(chunk)
        used += len(chunk) + 2
    body.reverse()
    if omitted:
        lines.append(f"({omitted} earlier exchange(s) omitted for length)")
    lines.extend(body)
    return "\n".join(lines)


def build(*, current_session_id: str, source: str = "", settings: dict | None = None,
          db_path: Path | None = None) -> tuple[str, str]:
    """Return ``(block, reason)``. An empty block means 'nothing to replay'."""
    cfg = {**DEFAULTS, **(settings or {})}
    if not current_session_id:
        return "", "no session id"

    want = str(cfg.get("source") or "pg").lower()
    max_pairs = max(1, int(cfg["last_n"]) // 2)
    session = None
    pairs: list[tuple[str, str]] = []
    summary = ""
    errs: list[str] = []

    if want in ("pg", "auto"):
        try:
            con = _pg_connect()
            if con is None:
                errs.append("pg: no credentials in profile .env")
            else:
                try:
                    session = pg_prior_session(
                        con, current_session_id, min_messages=int(cfg["min_messages"]))
                    if session:
                        summary = pg_session_summary(con, session["id"])
                        pairs = pg_pairs(con, session["id"], max_pairs=max_pairs)
                finally:
                    con.close()
        except Exception as exc:  # fail-open
            errs.append(f"pg: {exc}")

    if not pairs and want in ("pg", "sqlite", "auto"):
        try:
            path = db_path or state_db_path()
            if not path.exists():
                errs.append(f"sqlite: missing {path}")
            else:
                con = _sqlite_connect(path)
                try:
                    session = session or sqlite_prior_session(
                        con, current_session_id, min_messages=int(cfg["min_messages"]),
                        max_age_days=float(cfg["max_age_days"]))
                    if session:
                        pairs = sqlite_pairs(con, session["id"], max_pairs=max_pairs)
                finally:
                    con.close()
        except Exception as exc:
            errs.append(f"sqlite: {exc}")

    if not pairs and not summary:
        return "", "; ".join(errs) or "no prior session with conversation"
    block = build_block(
        session, pairs, max_chars=int(cfg["max_chars"]),
        per_message_chars=int(cfg["per_message_chars"]), summary=summary,
    )
    return block, (
        f"{len(pairs)} exchange(s) from {session['id']} via {session.get('db')}"
        + (" + summary" if summary else "")
    )


if __name__ == "__main__":  # manual probe: python3 _replay.py <current_session_id>
    import sys

    text, why = build(current_session_id=sys.argv[1] if len(sys.argv) > 1 else "")
    print(f"-- {why} --")
    print(text[:2500])
