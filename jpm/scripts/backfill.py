#!/usr/bin/env python3
"""
jpm backfill — Seed Jim's workhorse memory with historical context.
# Run this on Jim's node after deploying the jpm plugin.
"""
import time
import os
from pathlib import Path

from jpm.core._pg import sync_conn

# Prefer JOSHAICO_HOME runtime path, fall back to standalone fallback
_JPM_HOME = os.environ.get("JOSHAICO_HOME") or str(Path.home() / ".joshaico")
JOSHAICO_HOME = _JPM_HOME


def backfill():
    now = time.time()

    # ── Knowledge Graph ──
    knowledge = [
        ("system", "Oracle", "Generates direction, confidence, and regime signals. Was dead for 7 hours, now firing SHORT at 0.450 confidence."),
        ("system", "Neo", "Strategic validator. Gets full picture: profile + range + history + news + macro. Validates trade profile output, adjusts strategic params. Mid-trade: re-evaluates thesis every 300s. Can say 'close it' if thesis is dead. Currently: output is logged but never acted on."),
        ("system", "Trade Profile Classifier", "Takes range data, structure, session, DOW, news. Outputs SWING/SCALP/CAUTION. Output never reaches Neo."),
        ("system", "Entry Engine", "Gets final 31-param config, gate check, enter or skip. Never sees Neo's validated config."),
        ("system", "Mid_eval", "Runs every 60s. Gets price, momentum, structure, confluence, daily PnL. Adjusts config within profile bands. Doesn't know what profile the trade was classified as. Overwrites trail values."),
        ("system", "Freqtrade", "Used for simulations. Too fast, inaccurate results. NostalgiaForInfinityX7 is the top community strategy (3.3K stars, 73K lines). Multi-timeframe analysis, 5 entry modes, dynamic position sizing."),
        ("architecture", "Data Flow", "Pre-trade: Profile classifier -> Neo -> Entry engine. Mid-trade: Mid_eval adjusts within bands, Neo re-evaluates every 300s. Post-trade: No feedback loop. Modules don't share data properly."),
        ("architecture", "Module Problem", "Each module built to solve its own problem. They don't talk to each other. One module makes a good entry, another closes it for no reason. No shared source of truth."),
    ]
    with sync_conn() as conn:
        for etype, name, desc in knowledge:
            conn.execute(
                "INSERT INTO knowledge (entity_type, name, description, last_referenced) VALUES (?, ?, ?, ?) ON CONFLICT (entity_type, name) DO NOTHING",
                (etype, name, desc, now)
            )
    print(f"Seeded {len(knowledge)} knowledge entries")

    # ── Loops ──
    loops = [
        ("Fix module communication: Neo's output is logged but never acted on", "trading_bot", "high"),
        ("Mid_eval overwrites trail values because it doesn't know the trade profile", "trading_bot", "high"),
        ("Entry engine hardcodes COOLDOWN_LOSSES/COOLDOWN_MINUTES instead of reading from BASE_CONFIG", "trading_bot", "medium"),
        ("Exit monitor still falls back to BASE_CONFIG instead of reading complete trade config", "trading_bot", "low"),
        ("No post-trade feedback — system never checks if thesis was right after exit", "trading_bot", "high"),
        ("No macro layer — BTC cycle, session×DOW×regime patterns not fed to Neo", "trading_bot", "high"),
        ("Aggression engine stuck in SURVIVAL — lost_in_transit trades counted as losses", "trading_bot", "medium"),
        ("Dead params in Neo JSON (quick_death*, flat_kill*, reversal*) — nothing reads them", "trading_bot", "low"),
        ("DOW pattern: Bear Wednesdays 12-16 UTC = 73-86% red bars — should be a hard rule", "trading_bot", "high"),
        ("Watchdog timer resurrects broken services — needs to know when services are intentionally stopped", "trading_bot", "medium"),
        ("Pipeline: v7 speedrun engine tracing captured — no path to EntryEngine", "trading_bot", "high"),
        ("Pipeline: post-trade analysis never writes back to v7 speedrun engine", "trading_bot", "medium"),
    ]
    with sync_conn() as conn:
        for content, project, priority in loops:
            conn.execute(
                "INSERT INTO loops (content, project, priority) VALUES (?, ?, ?)",
                (content, project, priority)
            )
    print(f"Seeded {len(loops)} open loops")

    # ── Pulse ──
    with sync_conn() as conn:
        conn.execute(
            "INSERT INTO pulse (status, summary, session_id) VALUES (?, ?, ?)",
            ("idle", "Backfill complete — initial JPM memory seeded", "backfill")
        )
    print("Pulse set to idle")

    # ── Active focus ──
    with sync_conn() as conn:
        conn.execute("DELETE FROM active")
        conn.execute(
            "INSERT INTO active (focus, project, status, updated_at) VALUES (?, ?, ?, ?)",
            ("Trading pipeline: decouple Neo, consolidate config, fix data flow", "trading_bot", "analyzing", now)
        )
    print("Active focus set")

    # ── Reflections ──
    reflections = [
        ("The single-source-of-truth problem: every module has its own config. BASE_CONFIG is a chain of overrides, not a source of truth. Solution: one ConfigManager that all modules read from, with versioned overrides per profile.",
         "architecture", 9),
        ("Neo is the smartest module but completely sidelined. Its output is logged but never used. This is the single biggest waste in the pipeline.",
         "architecture", 8),
        ("Mid_eval and trail management are fighting each other. Mid_eval adjusts config within profile bands, but trail management overwrites those adjustments. They need to be a single function.",
         "architecture", 7),
        ("DOW patterns are real and measurable. Bear Wednesdays 12-16 UTC show 73-86% red bars. This should be a hard rule, not a suggestion.",
         "trading", 8),
    ]
    with sync_conn() as conn:
        for insight, trigger, impact in reflections:
            conn.execute(
                "INSERT INTO reflections (session_id, trigger, insight, impact) VALUES (?, ?, ?, ?)",
                ("backfill", trigger, insight, impact)
            )
    print(f"Seeded {len(reflections)} reflections")

    print("\n✅ Backfill complete!")


if __name__ == "__main__":
    backfill()