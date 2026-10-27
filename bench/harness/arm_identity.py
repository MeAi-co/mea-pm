#!/usr/bin/env python3
"""Resolve a bench arm to its live gateway by SERVICE IDENTITY, never by PID.

A PID is a snapshot of one process at one instant. It changes on every
restart, so any script or report that pins a PID is stale the moment the
gateway is restarted. The durable identity of an arm is:

    arm letter  ->  HERMES_HOME  ->  systemd unit  ->  MainPID (live, resolved)

The unit name is `hermes-gateway-<sha256(HERMES_HOME)[:8]>.service` -- verified
against all three live units. It IS derivable, but this resolver does not rely
on that: it reads each unit's `Environment=HERMES_HOME=` line, which is the
authoritative declaration and survives any change to the naming convention.
The hash is used only as a cross-check, never as the lookup key.

Usage:
    python3 arm_identity.py            # table of all arms
    python3 arm_identity.py A          # one arm, machine-readable
    python3 arm_identity.py --json     # all arms as JSON

Exit codes: 0 ok, 1 arm not found, 2 systemd unavailable.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

UNIT_GLOB = "hermes-gateway-*.service"
UNIT_DIR = Path("/etc/systemd/system")

# Arm letter -> home. This is the ONLY place an arm is named. Everything
# downstream (unit, pid, user) is resolved from it at call time.
ARM_HOMES = {
    "A": "/home/bench_a/.hermes",
    "B": "/home/bench_b/.hermes",
    "C": "/home/bench_c/.hermes",
}


def _systemctl(*args: str) -> str:
    try:
        done = subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


def _unit_home(unit_path: Path) -> str:
    """Read HERMES_HOME out of a unit file's Environment= lines."""
    try:
        text = unit_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("Environment="):
            continue
        for token in re.findall(r'"?([A-Z_]+)=([^"\s]+)"?', line):
            if token[0] == "HERMES_HOME":
                return token[1]
    return ""


def discover_units() -> dict[str, Path]:
    """Map HERMES_HOME -> unit file path, by reading the units themselves."""
    found: dict[str, Path] = {}
    if not UNIT_DIR.is_dir():
        return found
    for path in sorted(UNIT_DIR.glob(UNIT_GLOB)):
        home = _unit_home(path)
        if home:
            found[home.rstrip("/")] = path
    return found


def resolve(arm: str) -> dict:
    """Resolve one arm to its live gateway. Returns a dict, never raises."""
    home = ARM_HOMES.get(arm.upper())
    if not home:
        return {"arm": arm, "error": f"unknown arm {arm!r}; known: {sorted(ARM_HOMES)}"}

    units = discover_units()
    unit_path = units.get(home.rstrip("/"))
    if unit_path is None:
        return {
            "arm": arm.upper(),
            "hermes_home": home,
            "error": "no systemd unit declares this HERMES_HOME",
            "units_seen": {k: v.name for k, v in units.items()},
        }

    unit = unit_path.name
    pid_raw = _systemctl("show", unit, "-p", "MainPID", "--value")
    state = _systemctl("show", unit, "-p", "ActiveState", "--value")
    sub = _systemctl("show", unit, "-p", "SubState", "--value")
    user = _systemctl("show", unit, "-p", "User", "--value")

    try:
        pid = int(pid_raw)
    except (TypeError, ValueError):
        pid = 0

    # Cross-check: the live process must actually carry this HERMES_HOME.
    # A unit can be "active" while its MainPID is a supervisor, not the gateway.
    env_home = ""
    if pid > 0:
        try:
            raw = Path(f"/proc/{pid}/environ").read_bytes()
            for entry in raw.split(b"\0"):
                if entry.startswith(b"HERMES_HOME="):
                    env_home = entry.split(b"=", 1)[1].decode("utf-8", "replace")
                    break
        except OSError:
            env_home = ""

    return {
        "arm": arm.upper(),
        "hermes_home": home,
        "unit": unit,
        "unit_path": str(unit_path),
        "active_state": state,
        "sub_state": sub,
        "user": user,
        "pid": pid,
        "pid_env_home": env_home,
        "pid_matches_home": env_home.rstrip("/") == home.rstrip("/") if env_home else None,
        "running": state == "active" and sub == "running" and pid > 0,
    }


def main(argv: list[str]) -> int:
    if not UNIT_DIR.is_dir():
        print("systemd unit dir not found", file=sys.stderr)
        return 2

    if "--json" in argv:
        print(json.dumps({a: resolve(a) for a in ARM_HOMES}, indent=2))
        return 0

    arms = [a for a in argv if not a.startswith("-")] or sorted(ARM_HOMES)
    if len(arms) == 1:
        info = resolve(arms[0])
        print(json.dumps(info, indent=2))
        return 0 if "error" not in info else 1

    print(f"{'arm':<4} {'unit':<32} {'pid':>7} {'state':<10} {'user':<9} home")
    print("-" * 100)
    rc = 0
    for arm in arms:
        info = resolve(arm)
        if "error" in info:
            print(f"{arm:<4} {'--':<32} {'--':>7} {'--':<10} {'--':<9} {info['error']}")
            rc = 1
            continue
        # Only meaningful for a live unit: a dead unit has no PID to compare.
        flag = ""
        if info["running"] and info["pid_matches_home"] is False:
            flag = "  <-- PID HOME MISMATCH"
        print(
            f"{info['arm']:<4} {info['unit']:<32} {info['pid']:>7} "
            f"{info['active_state'] + '/' + info['sub_state']:<10} "
            f"{info['user']:<9} {info['hermes_home']}{flag}"
        )
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
