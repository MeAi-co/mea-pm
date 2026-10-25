#!/usr/bin/env python3
"""One-shot hygiene sweep for persisted replay-chrome and volatile-context junk
in the ``messages`` table.

DRY RUN BY DEFAULT. Pass ``--apply`` to mutate.

Background: gateway chrome ("[Warm start: ...]" banner, "[SUPPLEMENTARY SKILL
LOAD]" note) and volatile-context breadcrumbs ("[Context: ...]") rode in on
``role='user'`` and were persisted. The 2026-09-30 build-time fix
(``agent/replay_cleanup.py`` + the gateway build sweep) stops NEW pollution and
peels chrome on READ, so the model no longer sees it. This script cleans the
HISTORICAL residue so the stored transcript is honest and the replay loop loses
its fuel.

Two families, both applied only to ACTIVE ``role='user'`` rows:

  * chrome    -> ``is_replay_artifact`` true        => deactivate
                 banner folded onto a real body      => peel body (UPDATE content)
  * context   -> head breadcrumb run with no body    => deactivate
                 head breadcrumb run + a real body   => peel body (UPDATE content)
  * whitespace-only user row                         => deactivate

The chrome decision delegates to the tested library predicates; only the
``[Context: ...]`` head-peel is local (the library predicates are chrome-only by
design -- breadcrumbs are a different family).

Reversibility: with ``--apply`` every affected row is copied to
``messages_sweep_backup_<UTCstamp>`` BEFORE mutation. Nothing is hard-deleted --
deactivation flips ``active=0`` (same soft-archive the compaction path uses).

Idempotent for the deactivate classes (they stop matching once inactive). Peel is
point-in-time: a later warm start can re-fold a banner onto the row in STORAGE,
which the build sweep peels on read -- re-run for hygiene as needed.

Usage::

    python3 -m jpm.scripts.sweep_replay_chrome            # dry run
    python3 -m jpm.scripts.sweep_replay_chrome --apply    # mutate
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_CTX_HEAD_RE = re.compile(r"^(?:\[Context:[^\]\n]*\]\s*\n?)+")


def _load_core():
    home = os.path.expanduser(os.environ.get("JOSHAICO_HOME", "~/.joshaico"))
    envp = os.path.join(home, ".env")
    if os.path.exists(envp) and not os.environ.get("JPM_PG_HOST"):
        for line in open(envp):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.startswith("JPM_PG_"):
                    os.environ.setdefault(k, v.strip().strip('"').strip("'"))
    core = os.environ.get("JOSHAICO_CORE", "")
    if core not in sys.path:
        sys.path.insert(0, core)
    return core


def peel_context_head(content: str) -> tuple[str, str]:
    """Peel a leading ``[Context: ...]`` run. -> (kind, body).

    ``[Context: JPM found ...]`` breadcrumbs must sit at the HEAD of the row to
    count -- a genuine message that merely mentions ``[Context:`` mid-body is
    left alone. kind in {'pure','mixed','none'}.
    """
    if not isinstance(content, str) or not content:
        return "none", content
    m = _CTX_HEAD_RE.match(content)
    if not m:
        return "none", content
    body = content[m.end():].strip()
    return ("pure" if not body else "mixed"), body


def classify(content, artifact, strip) -> tuple[str, str, str]:
    """-> (class, action, new_content).

    class:  'chrome' | 'context' | 'empty' | 'none'
    action: 'deactivate' | 'peel' | 'skip'

    ``artifact`` / ``strip`` are the library predicates (passed in so this module
    has no import-time dependency on ``core``).
    """
    if not isinstance(content, str) or not content.strip():
        return "empty", "deactivate", ""
    # 1. chrome (library predicate: pure chrome => drop)
    if artifact(content):
        return "chrome", "deactivate", ""
    cur = strip(content)
    if not isinstance(cur, str):
        cur = content
    # 2. context breadcrumb head (library leaves these alone by design)
    ck, cbody = peel_context_head(cur)
    if ck == "pure":
        return "context", "deactivate", ""
    if ck == "mixed":
        return "context", "peel", cbody
    # 3. banner folded onto a real body (strip changed the row)
    if cur != content:
        return "chrome", "peel", cur.strip()
    return "none", "skip", content


def _load_predicates():
    """Return ``(is_replay_artifact, strip_replay_chrome)``.

    Prefers the canonical module ``core/agent/replay_cleanup.py``. Falls back to a
    minimal embedded mirror so the sweep can still run on fleet nodes that have
    NOT yet deployed the replay-chrome fix (they lack that module). The mirror is
    deliberately tiny -- banner + skill-note only -- and is used automatically
    only until the node is upgraded, at which point the canonical module wins.
    """
    try:
        from agent.replay_cleanup import is_replay_artifact, strip_replay_chrome

        return is_replay_artifact, strip_replay_chrome
    except Exception:
        pass

    _ts = re.compile(
        r"^\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        r"(?: [A-Za-z0-9_+\-/:]+)?\]"
        r"|^\[\d{4}-\d{2}-\d{2}T[^\]]+\]"
    )
    _ws = re.compile(r"\[Warm start: showing the last ")
    _note = "[SUPPLEMENTARY SKILL LOAD]"

    def _strip(content):
        if not isinstance(content, str) or not content:
            return content
        s = content.lstrip()
        m = _ts.match(s)
        after = s[m.end():].lstrip() if m else s
        if not _ws.match(after):
            return content
        s = after
        while True:
            if _ws.match(s):
                close = s.find("]")
                if close == -1:
                    return ""
                s = s[close + 1:].lstrip()
                continue
            m = _ts.match(s)
            if m:
                a = s[m.end():].lstrip()
                if _ws.match(a):
                    s = a
                    continue
            return s

    def _effective(content):
        if not isinstance(content, str) or not content:
            return ""
        s = _strip(content)
        if not isinstance(s, str):
            return ""
        m = _ts.match(s.lstrip())
        return s.lstrip()[m.end():].lstrip() if m else s

    def _artifact(content):
        if not isinstance(content, str) or not content:
            return False
        t = _effective(content)
        return (not t) or t.startswith(_note)

    return _artifact, _strip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="mutate (default: dry run)")
    ap.add_argument("--limit", type=int, default=0, help="cap rows mutated (0 = all)")
    args = ap.parse_args()

    _load_core()
    from joshaico_state import sync_conn  # noqa: E402

    is_replay_artifact, strip_replay_chrome = _load_predicates()

    kw = {"artifact": is_replay_artifact, "strip": strip_replay_chrome}

    with sync_conn() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT id, content FROM messages "
            "WHERE active=1 AND role='user' "
            "AND (content LIKE '%[Warm start:%' "
            "  OR content LIKE '%SUPPLEMENTARY SKILL LOAD%' "
            "  OR content LIKE '[Context:%' "
            "  OR content LIKE '%ASYNC DELEGATION BATCH COMPLETE%' "
            "  OR COALESCE(TRIM(content),'') = '')"
        )
        rows = cur.fetchall()
        counts: dict[str, int] = {}
        to_deactivate: list[int] = []
        to_peel: list[tuple[int, str]] = []
        for r in rows:
            cls, action, newc = classify(r["content"], **kw)
            if action == "skip":
                continue
            counts[f"{cls}:{action}"] = counts.get(f"{cls}:{action}", 0) + 1
            if action == "deactivate":
                to_deactivate.append(r["id"])
            else:
                to_peel.append((r["id"], newc))

        if args.limit:
            budget = args.limit
            to_peel = to_peel[:budget]
            to_deactivate = to_deactivate[: max(0, budget - len(to_peel))]

        print(f"[sweep] node={os.uname().nodename} scanned={len(rows)}")
        for k in sorted(counts):
            print(f"[sweep]   {k} = {counts[k]}")
        print(f"[sweep] planned: deactivate={len(to_deactivate)} peel={len(to_peel)}")

        if not args.apply:
            print("[sweep] DRY RUN - no changes written. Re-run with --apply.")
            return 0
        if not to_deactivate and not to_peel:
            print("[sweep] nothing to do.")
            return 0

        cur.execute("SELECT to_char(now() AT TIME ZONE 'UTC','YYYYMMDD_HH24MISS') s")
        bk = f"messages_sweep_backup_{cur.fetchone()['s']}"
        # NOTE: messages.active is INTEGER (not boolean) in this schema -- mirror it
        # exactly, or the INSERT ... SELECT raises DatatypeMismatchError.
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {bk} "
            f"(id bigint PRIMARY KEY, content text, active integer, backed_up_at timestamptz DEFAULT now())"
        )
        n_bk = 0
        for mid, _ in to_peel + [(i, None) for i in to_deactivate]:
            cur.execute(
                f"INSERT INTO {bk} (id, content, active) "
                f"SELECT id, content, active FROM messages WHERE id=? ON CONFLICT (id) DO NOTHING",
                (mid,),
            )
            n_bk += cur.rowcount
        for mid, newc in to_peel:
            cur.execute("UPDATE messages SET content=? WHERE id=?", (newc, mid))
        for mid in to_deactivate:
            cur.execute("UPDATE messages SET active=0 WHERE id=?", (mid,))
        c.commit()
        print(
            f"[sweep] APPLIED: backup={bk} backed_up={n_bk} "
            f"peeled={len(to_peel)} deactivated={len(to_deactivate)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
