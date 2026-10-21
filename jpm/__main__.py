"""JPM CLI — single entry point for all PG operations.

Usage:
    jpm signal list                          List all signals
    jpm signal disable <id>                  Disable a signal
    jpm signal enable <id>                   Enable a signal

    jpm knowledge list [--type TYPE]         List knowledge entries
    jpm knowledge add <type> <name> <desc>   Add knowledge entry
    jpm knowledge update <id> <weightage>    Update knowledge weightage
    jpm knowledge delete <id>                Delete knowledge entry

    jpm patterns list                        List patterns
    jpm patterns archive <id>                Archive a pattern

    jpm pulse                                Show latest pulse
    jpm active                               Show current focus
    jpm loops                                Show open loops
    jpm reflections                          Show recent reflections
"""

import argparse
import sys
import logging
from typing import Any

from .core._pg import sync_conn
from .core._write import _add_knowledge, _add_reflection, _write_pulse, _set_active, _add_loop, _resolve_loop, _upsert_skill
from .core._read import _get_latest_pulse, _get_active, _get_open_loops, _get_knowledge
from .core._search import _search_knowledge

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
LOG = logging.getLogger("jpm.cli")


def _cmd_signal(args: argparse.Namespace) -> None:
    if args.action == "list":
        with sync_conn() as db:
            rows = db.execute(
                "SELECT id, trigger, action, enabled, created_at FROM signals ORDER BY id"
            ).fetchall()
        if not rows:
            print("No signals found.")
            return
        print(f"{'ID':>4}  {'Enabled':>7}  {'Trigger':<60}  {'Action'}")
        print(f"{'─'*4}  {'─'*7}  {'─'*60}  {'─'*40}")
        for r in rows:
            enabled = "✅" if r["enabled"] else "❌"
            trigger = (r["trigger"] or "")[:58]
            action = (r["action"] or "")[:38]
            print(f"{r['id']:>4}  {enabled:>7}  {trigger:<60}  {action}")

    elif args.action == "disable":
        with sync_conn() as db:
            db.execute("UPDATE signals SET enabled = 0 WHERE id = ?", (args.id,))
        print(f"Signal {args.id} disabled.")

    elif args.action == "enable":
        with sync_conn() as db:
            db.execute("UPDATE signals SET enabled = 1 WHERE id = ?", (args.id,))
        print(f"Signal {args.id} enabled.")


def _cmd_knowledge(args: argparse.Namespace) -> None:
    if args.action == "list":
        with sync_conn() as db:
            if args.type:
                rows = db.execute(
                    "SELECT id, entity_type, name, weightage, description FROM knowledge WHERE entity_type = ? AND archived = 0 ORDER BY weightage DESC, id DESC LIMIT 50",
                    (args.type,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, entity_type, name, weightage, description FROM knowledge WHERE archived = 0 ORDER BY weightage DESC, id DESC LIMIT 50"
                ).fetchall()
        if not rows:
            print("No knowledge entries found.")
            return
        print(f"{'ID':>4}  {'Type':<12}  {'Weight':>6}  {'Name'}")
        print(f"{'─'*4}  {'─'*12}  {'─'*6}  {'─'*60}")
        for r in rows:
            name = (r["name"] or "")[:58]
            print(f"{r['id']:>4}  {r['entity_type']:<12}  {r['weightage']:>6.2f}  {name}")

    elif args.action == "add":
        ok = _add_knowledge(args.type, args.name, args.desc, weightage=0.5)
        print("OK" if ok else "ERROR")

    elif args.action == "update":
        with sync_conn() as db:
            db.execute("UPDATE knowledge SET weightage = ? WHERE id = ?", (args.weightage, args.id))
        print(f"Knowledge {args.id} weightage set to {args.weightage}.")

    elif args.action == "delete":
        with sync_conn() as db:
            db.execute("UPDATE knowledge SET archived = 1 WHERE id = ?", (args.id,))
        print(f"Knowledge {args.id} archived.")


def _cmd_patterns(args: argparse.Namespace) -> None:
    if args.action == "list":
        with sync_conn() as db:
            rows = db.execute(
                "SELECT id, name, description, confidence, times_fired, archived FROM patterns ORDER BY confidence DESC"
            ).fetchall()
        if not rows:
            print("No patterns found.")
            return
        print(f"{'ID':>4}  {'Arch':>4}  {'Conf':>5}  {'Fired':>5}  {'Name'}")
        print(f"{'─'*4}  {'─'*4}  {'─'*5}  {'─'*5}  {'─'*60}")
        for r in rows:
            arch = "📦" if r["archived"] else "  "
            conf = f"{r['confidence']:.2f}"
            name = (r["name"] or "")[:58]
            print(f"{r['id']:>4}  {arch:>4}  {conf:>5}  {r['times_fired']:>5}  {name}")

    elif args.action == "archive":
        with sync_conn() as db:
            db.execute("UPDATE patterns SET archived = 1 WHERE id = ?", (args.id,))
        print(f"Pattern {args.id} archived.")


def _cmd_status(args: argparse.Namespace) -> None:
    pulse = _get_latest_pulse()
    active = _get_active()
    loops = _get_open_loops(limit=5)
    knowledge = _get_knowledge(limit=5)

    print("=== PULSE ===")
    if pulse:
        print(f"  Status: {pulse.get('status', '?')}")
        print(f"  Summary: {pulse.get('summary', '')[:200]}")
    else:
        print("  (none)")

    print("\n=== ACTIVE ===")
    if active:
        print(f"  Focus: {active.get('focus', '?')}")
        print(f"  Project: {active.get('project', '')}")
        print(f"  Status: {active.get('status', '')}")
    else:
        print("  (none)")

    print(f"\n=== LOOPS ({len(loops)} open) ===")
    for l in loops:
        print(f"  [{l.get('priority', '?')}] {l.get('content', '')[:120]}")

    print(f"\n=== KNOWLEDGE ({len(knowledge)} recent) ===")
    for k in knowledge:
        print(f"  [{k.get('entity_type', '?')}] {k.get('name', '')[:80]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="JPM — PG operations CLI")
    sub = parser.add_subparsers(dest="command")

    # signal
    sig = sub.add_parser("signal")
    sig_sub = sig.add_subparsers(dest="action")
    sig_list = sig_sub.add_parser("list")
    sig_disable = sig_sub.add_parser("disable")
    sig_disable.add_argument("id", type=int)
    sig_enable = sig_sub.add_parser("enable")
    sig_enable.add_argument("id", type=int)

    # knowledge
    kn = sub.add_parser("knowledge")
    kn_sub = kn.add_subparsers(dest="action")
    kn_list = kn_sub.add_parser("list")
    kn_list.add_argument("--type", help="Filter by entity_type")
    kn_add = kn_sub.add_parser("add")
    kn_add.add_argument("type")
    kn_add.add_argument("name")
    kn_add.add_argument("desc")
    kn_upd = kn_sub.add_parser("update")
    kn_upd.add_argument("id", type=int)
    kn_upd.add_argument("weightage", type=float)
    kn_del = kn_sub.add_parser("delete")
    kn_del.add_argument("id", type=int)

    # patterns
    pat = sub.add_parser("patterns")
    pat_sub = pat.add_subparsers(dest="action")
    pat_sub.add_parser("list")
    pat_arch = pat_sub.add_parser("archive")
    pat_arch.add_argument("id", type=int)

    # status
    sub.add_parser("pulse")
    sub.add_parser("active")
    sub.add_parser("loops")
    sub.add_parser("reflections")

    args = parser.parse_args()

    if args.command == "signal":
        _cmd_signal(args)
    elif args.command == "knowledge":
        _cmd_knowledge(args)
    elif args.command == "patterns":
        _cmd_patterns(args)
    elif args.command in ("pulse", "active", "loops", "reflections"):
        _cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
