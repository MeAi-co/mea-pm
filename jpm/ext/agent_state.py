"""jpm ext: state — agent state table CRUD.
Imports from core, adds agent state tables and queries.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..core._pg import sync_conn

LOG = logging.getLogger(__name__)

_STATE_ID = 1


def ensure_state_tables() -> None:
    """Ensure agent state tables exist. PG handles DDL via schema apply."""
    pass


def _get_state() -> dict[str, Any] | None:
    try:
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT mood, energy, headspace, skill_override, updated_at "
                "FROM state ORDER BY updated_at DESC LIMIT 1"
            )
            if not row:
                return None
            out = dict(row)
            try:
                out["energy"] = float(out["energy"])
            except (TypeError, ValueError):
                out["energy"] = 0.5
            return out
    except Exception as e:
        LOG.debug("_get_state failed: %s", e)
        return None


def _set_state(
    mood: str = "neutral",
    energy: float = 0.5,
    headspace: str = "",
    valence: float = 0.0,
    arousal: float = 0.3,
    skill_override: str = "",
) -> bool:
    """Set current agent state. Also logs to moods table for history.

    Upserts a fixed row (id=1) to avoid DELETE races. Energy is stored as
    text (canonical schema) — asyncpg rejects floats into text columns,
    so pass energy as a string here.
    """
    mood = (mood or "neutral").strip() or "neutral"
    try:
        energy = float(energy)
    except (TypeError, ValueError):
        energy = 0.5
    energy = max(0.0, min(1.0, energy))
    valence = max(-1.0, min(1.0, float(valence)))
    arousal = max(0.0, min(1.0, float(arousal)))
    headspace = (headspace or "")[:500]
    skill_override = skill_override or ""
    now = time.time()

    try:
        with sync_conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO state (id, mood, energy, headspace, skill_override, valence, arousal, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET
                        mood = EXCLUDED.mood,
                        energy = EXCLUDED.energy,
                        headspace = EXCLUDED.headspace,
                        skill_override = EXCLUDED.skill_override,
                        valence = EXCLUDED.valence,
                        arousal = EXCLUDED.arousal,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (_STATE_ID, mood, str(energy), headspace, skill_override, float(valence), float(arousal), now),
                )
            except Exception as e:
                # Fallback for pre-0027 nodes without a PK on state.id:
                # delete + single insert (non-atomic but self-healing).
                LOG.debug("state upsert failed (%s), falling back to delete+insert", e)
                conn.execute("DELETE FROM state")
                conn.execute(
                    "INSERT INTO state (id, mood, energy, headspace, skill_override, valence, arousal, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (_STATE_ID, mood, str(energy), headspace, skill_override, float(valence), float(arousal), now),
                )
            # Also log to moods table for historical tracking
            conn.execute(
                "INSERT INTO moods (user_id, mood, context, created_at) VALUES (?, ?, ?, ?)",
                ("user", mood, headspace[:200], now),
            )
        return True
    except Exception as e:
        LOG.error("_set_state failed: %s", e)
        return False


def _nearest_tone(valence: float, arousal: float) -> str:
    """Nearest emotional tone by Euclidean distance.

    Uses DB catalog when available; otherwise a built-in set aligned with
    agent_tone.MOODS so continuous → discrete mapping stays consistent.
    """
    try:
        valence = float(valence)
        arousal = float(arousal)
    except (TypeError, ValueError):
        return "neutral"

    fallback = [
        # negative / high arousal
        ("frustrated", -0.70, 0.75),
        ("irritable",  -0.45, 0.55),
        ("overwhelmed", -0.60, 0.70),
        ("anxious",    -0.50, 0.70),
        ("stressed",   -0.40, 0.65),
        ("impatient",  -0.15, 0.60),
        # negative / low arousal
        ("sad",        -0.55, 0.25),
        ("numb",       -0.40, 0.15),
        ("tired",      -0.25, 0.20),
        ("concerned",  -0.30, 0.45),
        # neutral band
        ("neutral",     0.00, 0.35),
        ("calm",        0.15, 0.25),
        ("focused",     0.20, 0.55),
        ("surprised",   0.25, 0.70),
        # positive
        ("caring",      0.25, 0.40),
        ("hopeful",     0.40, 0.45),
        ("engaged",     0.45, 0.60),
        ("warm",        0.55, 0.45),
        ("grateful",    0.60, 0.40),
        ("playful",     0.65, 0.75),
        ("excited",     0.75, 0.85),
    ]

    rows = None
    try:
        with sync_conn() as conn:
            rows = conn.fetchall("SELECT name, valence, arousal FROM emotional_tones")
    except Exception as e:
        LOG.debug("_nearest_tone DB read failed: %s", e)

    catalog: list[tuple[str, float, float]] = []
    if rows:
        for r in rows:
            try:
                catalog.append((r["name"], float(r["valence"]), float(r["arousal"])))
            except (KeyError, TypeError, ValueError):
                continue
    if not catalog:
        catalog = fallback

    best = "neutral"
    best_dist = float("inf")
    for name, v, a in catalog:
        d = (v - valence) ** 2 + (a - arousal) ** 2
        if d < best_dist:
            best_dist = d
            best = name
    return best
