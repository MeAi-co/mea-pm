#!/usr/bin/env python3
"""
jpm session mining — Extract findings from state.db session messages.
Searches for trading pipeline discussions, bug discoveries, decisions, and patterns.
"""
import time
import os
import re
from pathlib import Path

from jpm.core._pg import sync_conn

# Prefer JOSHAICO_HOME (runtime data dir), fall back to standalone fallback
_JPM_HOME = os.environ.get("JOSHAICO_HOME") or str(Path.home() / ".joshaico")
JOSHAICO_HOME = _JPM_HOME

# Keywords that indicate a finding worth saving
FINDING_PATTERNS = [
    r"(?:root cause|the problem|the issue|the bug|the flaw)",
    r"(?:fixed|resolved|solved|patched)",
    r"(?:the fix|solution|approach|pattern)",
    r"(?:discovered|found|realized|noticed|identified)",
    r"(?:lesson|takeaway|key insight|key learning)",
    r"(?:conflict|overwrite|fighting|contradict)",
    r"(?:trail.clip|orphan|naked|stale|watchdog)",
    r"(?:config|DEFAULT_CONFIG|BASE_CONFIG|LEVEL_SLIDERS)",
    r"(?:SWING|SCALP|CAUTION|trade.profile)",
    r"(?:Neo|mid.eval|entry.engine|exit.monitor|morpheus)",
    r"(?:range.analyzer|range.profile|retracement|volatility.regime)",
    r"(?:DOW|session|Wednesday|bear.*Wed)",
    r"(?:macro|BTC cycle|regime)",
    r"(?:post.trade|feedback|thesis)",
]

def mine_sessions():
    # Get all non-cron sessions with substantial content via PG
    with sync_conn() as conn:
        sessions = conn.fetchall(
            "SELECT id, title, source, started_at, message_count "
            "FROM sessions "
            "WHERE source != 'cron' "
            "AND message_count >= 50 "
            "ORDER BY started_at DESC "
            "LIMIT 30"
        )

    print(f"Found {len(sessions)} trading-related sessions to mine")

    # Get messages from these sessions
    findings = []
    for s in sessions:
        sid = s['id']
        with sync_conn() as conn:
            msgs = conn.fetchall(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? AND role = 'assistant' "
                "ORDER BY id",
                (sid,)
            )

        for m in msgs:
            content = m['content'] or ''
            # Skip short messages
            if len(content) < 100:
                continue
            # Check for finding patterns
            for pattern in FINDING_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    # Extract the relevant paragraph
                    paragraphs = content.split('\n\n')
                    for p in paragraphs:
                        if re.search(pattern, p, re.IGNORECASE) and len(p) > 60:
                            # Clean up
                            p = p.strip()[:300]
                            findings.append({
                                'session': s['title'] or sid[:20],
                                'content': p,
                            })
                            break
                    break

    print(f"Extracted {len(findings)} potential findings")

    # Deduplicate by content similarity
    unique = []
    seen = set()
    for f in findings:
        key = f['content'][:80]
        if key not in seen:
            seen.add(key)
            unique.append(f)

    print(f"After dedup: {len(unique)} unique findings")

    # Add as reflections via PG
    now = time.time()
    count = 0
    for f in unique:
        with sync_conn() as conn:
            conn.execute(
                "INSERT INTO reflections (session_id, trigger, insight, impact) VALUES (?, ?, ?, ?)",
                (f['session'][:20], "session_mining", f['content'], 5)
            )
        count += 1

    print(f"Added {count} reflections to JPM")
    print("\n✅ Mining complete!")


if __name__ == "__main__":
    mine_sessions()