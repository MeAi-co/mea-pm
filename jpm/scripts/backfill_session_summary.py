#!/usr/bin/env python3
"""
jpm session-summary backfill — one-shot populator of `sessions.summary`.

Backfills the `sessions.summary` column (added by migration 0062) for historical
sessions so tier-3 warm-start/resume can inject an orientation brief without
re-traversing raw messages.

Strategy (hybrid, per session):
  - Gather in-order existing `is_digest` rows (the rolling compressor already
    wrote chapter-level summaries) + a bounded sample of real user/assistant
    messages (head + tail only, tools excluded) + session metadata (title,
    end_reason).
  - ONE aux LLM call (task="compression") condenses that into a 2-4 sentence
    first-person brief (same prompt/voice as tier-2 `_condense_summary`).
  - `UPDATE sessions.summary`.

Idempotent: skips any session whose summary is already non-empty. Resumable:
`--limit` and `--offset` slice the queue; re-running only hits what's left.

Scope: ANY session with its own messages and no summary — finalized or not. The
`end_reason IS NOT NULL` gate was dropped (2026-09-22): 119 historical sessions
were NULL/empty and got skipped, leaving a continuity hole for child sessions
whose entire ancestor chain was unfinalized. The `EXISTS(...messages...)` clause
is now the only scope limiter (no content → nothing to summarise, still skipped).

Usage:
  python3 -m jpm.scripts.backfill_session_summary --dry-run
  python3 -m jpm.scripts.backfill_session_summary --limit 5
  python3 -m jpm.scripts.backfill_session_summary            # full run

Flags:
  --limit N      process at most N sessions (test slice)
  --offset N     skip the first N sessions (resume)
  --dry-run      print what would be done, run no LLM calls and no writes
  --force        ignore non-empty summary (re-summarize everything) — DANGEROUS
"""
import os
import sys
import time
from pathlib import Path

# Make `agent.auxiliary_client` importable (it lives under core/). Mirror how the
# gateway resolves it at runtime.
_JOSHAICO_ROOT = Path(__file__).resolve().parents[2]  # /opt/joshaico
for _p in (str(_JOSHAICO_ROOT), str(_JOSHAICO_ROOT / "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
JOSHAICO_HOME = os.environ.get("JOSHAICO_HOME") or str(Path.home() / ".joshaico")

# Self-bootstrap: load JOSHAICO_HOME/.env so JPM_PG_* (and any other config the
# imports read from the environment) are present even when the script is invoked
# without a pre-exported environment. This is what makes the backfill drop-in
# portable across fleet agents — no manual `export` and NO third-party dotenv
# dependency (python-dotenv isn't reliably installed on every agent's python).
# A minimal stdlib parser handles it; existing env vars always win (override=False).
def _load_env_file(path):
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = val

_load_env_file(Path(JOSHAICO_HOME) / ".env")

from jpm.core._pg import sync_conn  # noqa: E402
from agent.auxiliary_client import call_llm  # noqa: E402

# Bytes of full message content to feed the LLM per session (sample cap). The
# biggest session is ~2.3k messages; we never send the raw transcript.
MSG_SAMPLE_CAP = 16000
# How many head + tail real messages to include.
HEAD_N = 5
TAIL_N = 5
# Cap the final brief (matches tier-2 session_anchor cap behaviour).
SUMMARY_CAP_CHARS = 1200


def _brief_prompt(title, end_reason, digests, sampled):
    head = "\n".join(f"[{r}] {c.strip()[:900]}" for r, c in sampled[:HEAD_N] if (c or "").strip())
    tail = "\n".join(f"[{r}] {c.strip()[:900]}" for r, c in sampled[-TAIL_N:] if (c or "").strip())
    digest_text = "\n\n".join(d.strip() for d in digests if (d or "").strip())

    parts = []
    if title:
        parts.append(f"SESSION TITLE: {title}")
    if end_reason:
        parts.append(f"END REASON: {end_reason}")
    if digest_text:
        parts.append(f"EXISTING CHAPTER DIGESTS (in order):\n{digest_text}")
    parts.append(f"MESSAGE SAMPLE (head={HEAD_N} / tail={TAIL_N}):\n{head}\n\n--- tail ---\n{tail}")
    source = "\n\n".join(parts)

    return (
        "You produce a ONE-paragraph session summary (a continuity brief) for a "
        "historical Joshaico session. Write it STRICTLY FIRST-PERSON from the "
        "assistant's own view (\"We worked on X. Decided Y. Established Z. Open: W\" ) "
        "in the assistant's own warm, natural voice. Cover: what the session was "
        "about, key artifacts built or decisions made, established facts/context, and "
        "any open loops or unfinished threads. Keep it to 2-4 sentences — an "
        "orientation pointer for a future warm-start, not a replay. Do NOT add "
        "anything not implied by the source. Do NOT use a user's voice. Do NOT "
        "third-person.\\n\\nSOURCE:\\n"
        f"{source}"
    )


def _run_one(session):
    sid = session["id"]
    title = session.get("title")
    end_reason = session.get("end_reason")

    # 1) Existing digest rows (already-summarised chapters) — free signal.
    with sync_conn() as conn:
        digests = [
            r["content"] for r in conn.fetchall(
                "SELECT content FROM messages WHERE session_id = ? AND is_digest = true "
                "AND content IS NOT NULL AND content != '' ORDER BY id ASC",
                (sid,),
            )
        ]
        # 2) Real user/assistant messages, evenly sampled toward head/mid/tail.
        msgs = conn.fetchall(
            "SELECT id, role, content FROM messages "
            "WHERE session_id = ? AND role IN ('user','assistant') "
            "AND content IS NOT NULL AND content != '' "
            "AND is_digest = false ORDER BY id ASC",
            (sid,),
        )
        meta = conn.fetchone(
            "SELECT title, end_reason, started_at, ended_at FROM sessions WHERE id = ?",
            (sid,),
        )
    msg_rows = [(r["role"], r["content"]) for r in msgs]
    total = len(msg_rows)

    # No source material at all — nothing to summarise.
    if not digests and not msg_rows:
        print(f"  [{sid}] SKIP no digest rows and no real messages")
        return "skip_no_source"

    # Sample head + tail only (never the raw transcript). Keep the byte cap.
    sampled = msg_rows[:HEAD_N] + msg_rows[-TAIL_N:]
    budget = MSG_SAMPLE_CAP - sum(len(c) for _, c in sampled)
    if budget < 0:
        # Trim head toward tail first (tail carries the freshest state).
        keep_head = max(1, HEAD_N)
        while budget < 0 and keep_head > 1:
            keep_head -= 1
            sampled = msg_rows[:keep_head] + msg_rows[-TAIL_N:]
            budget = MSG_SAMPLE_CAP - sum(len(c) for _, c in sampled)
        if budget < 0:
            sampled = sampled[-TAIL_N:]

    title2 = (meta["title"] if meta else None) or title
    prompt = _brief_prompt(title2, (meta["end_reason"] if meta else None) or end_reason,
                           digests, sampled)
    try:
        resp = call_llm(
            task="compression",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        brief = resp.choices[0].message.content or ""
        if isinstance(resp, dict):
            brief = resp.get("content") or resp.get("text") or ""
    except Exception as e:
        print(f"  [{sid}] LLM FAIL {type(e).__name__}: {e}")
        return "skip_llm_fail"

    brief = (brief or "").strip()
    if not brief:
        print(f"  [{sid}] SKIP empty LLM response (digests={len(digests)}, msgs={total})")
        return "skip_empty"

    if len(brief) > SUMMARY_CAP_CHARS:
        brief = brief[:SUMMARY_CAP_CHARS].rstrip() + "…"

    with sync_conn() as conn:
        conn.execute(
            "UPDATE sessions SET summary = ? WHERE id = ? AND (summary IS NULL OR summary = '')",
            (brief, sid),
        )
    print(f"  [{sid}] ✓ {len(brief)} chars (digests={len(digests)}, msgs={total})"
          f"{(', title='+title2) if title2 else ''}")
    return "done"


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    force = "--force" in args
    limit = None
    offset = 0

    # If the first arg is a JSON object (the workflow `run` contract — params
    # arrive as JSON on sys.argv[1]), parse those too so the script works both
    # as a bare CLI (`--limit 5 --dry-run`) and when triggered by the skill-bound
    # `backfill-summaries` workflow.
    j = None
    if args and str(args[0]).lstrip().startswith("{"):
        try:
            import json as _json
            j = _json.loads(args[0])
        except ValueError:
            j = None
    if j:
        dry_run = dry_run or bool(j.get("dry_run"))
        force = force or bool(j.get("force"))
        limit = j.get("limit", limit)
        offset = j.get("offset", offset)
        for key in ("limit", "offset"):
            if j.get(key) is not None:
                try:
                    if key == "limit":
                        limit = int(j[key])
                    else:
                        offset = int(j[key])
                except (TypeError, ValueError):
                    pass
    else:
        for i, a in enumerate(args):
            if a in ("--limit", "--offset") and i + 1 < len(args):
                try:
                    val = int(args[i + 1])
                except ValueError:
                    continue
                if a == "--limit":
                    limit = val
                elif a == "--offset":
                    offset = val

    if dry_run:
        print("DRY RUN — no LLM calls, no writes.\n")

    cond = "summary IS NULL OR summary = ''"
    if force:
        cond = "1=1"  # re-summarise everything

    with sync_conn() as conn:
        rows = conn.fetchall(
            f"SELECT id, title, end_reason, model FROM sessions "
            f"WHERE ({cond}) "
            f"AND EXISTS (SELECT 1 FROM messages m WHERE m.session_id = sessions.id) "
            f"ORDER BY started_at ASC "
            f"LIMIT ? OFFSET ?",
            (limit or 10000, offset),
        )
    total = len(rows)
    print(f"Queued {total} sessions to backfill", "(force)" if force else
          f"{'(already-summarised skipped)' if not force else ''}")
    print()

    counts = {"done": 0, "skip_no_source": 0, "skip_empty": 0, "skip_llm_fail": 0}
    t0 = time.time()
    for i, s in enumerate(rows, 1):
        if dry_run:
            print(f"  [{s['id']}] WOULD summarise (title={s.get('title')!r},"
                  f" end={s.get('end_reason')})")
            counts["done"] += 1
            continue
        # Honor --limit regardless of how many were queued (resume by offset then stop).
        if limit is not None and (i - 1) >= limit:
            # Only stop after offset+limit total processed.
            break
        k = _run_one(s)
        counts[k] = counts.get(k, 0) + 1
        if counts["done"] and counts["done"] % 10 == 0 and not dry_run:
            el = time.time() - t0
            print(f"  ... {counts['done']}/{total} done, {el:.0f}s elapsed,"
                  f" ~{el/max(counts['done'],1):.1f}s/session")

    print()
    print("=== Backfill summary ===")
    print(f"  Sourced:      {total}")
    print(f"  Summarised:   {counts['done']}")
    for k, v in counts.items():
        if k != "done" and v:
            print(f"  {k.replace('_', ' ').title():13} {v}")
    if dry_run:
        print("  (dry run — nothing was written)")
    else:
        print(f"  Took {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
