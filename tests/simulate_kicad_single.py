#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Single-Module KiCad Conversion Simulation

Purpose
- Speed up iteration by converting and validating one circuit module at a time
- Uses the production converter; creates a temporary lowlevel folder containing just one circuit JSON + design.json

Usage
  python3 tests/simulate_kicad_single.py [module_substring]

Examples
  python3 tests/simulate_kicad_single.py power_supply
  python3 tests/simulate_kicad_single.py channel_1

This script is GENERIC and works for any project run structure.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def find_latest_output_dir(root: Path) -> Path | None:
    out = root / "output"
    if not out.exists():
        return None
    dirs = [p for p in out.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def pick_circuit(lowlevel: Path, needle: str) -> Path | None:
    needle = needle.lower()
    candidates = sorted([p for p in lowlevel.glob("circuit_*.json")])
    for p in candidates:
        if needle in p.name.lower():
            return p
    return None


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    latest = find_latest_output_dir(repo)
    if not latest:
        print("ERROR: No output/* folder found")
        return 1

    lowlevel = latest / "lowlevel"
    if not lowlevel.exists():
        print(f"ERROR: Missing lowlevel dir: {lowlevel}")
        return 1

    # Resolve target module
    target = sys.argv[1] if len(sys.argv) > 1 else "power_supply"
    circuit_file = pick_circuit(lowlevel, target)
    if not circuit_file:
        print(f"ERROR: Could not find a circuit matching '{target}' under {lowlevel}")
        return 1

    # Prepare single-run lowlevel folder
    single_lowlevel = latest / "lowlevel_single"
    if single_lowlevel.exists():
        shutil.rmtree(single_lowlevel)
    single_lowlevel.mkdir(parents=True, exist_ok=True)

    # Copy design.json if exists (context may be useful for converter)
    design = lowlevel / "design.json"
    if design.exists():
        shutil.copy2(design, single_lowlevel / "design.json")

    # Copy just the selected circuit json
    shutil.copy2(circuit_file, single_lowlevel / circuit_file.name)

    # Prepare single-run kicad output folder
    single_kicad = latest / "kicad_single"
    if single_kicad.exists():
        shutil.rmtree(single_kicad)
    single_kicad.mkdir(parents=True, exist_ok=True)

    # Run converter
    converter = repo / "scripts" / "kicad_converter.py"
    cmd = [sys.executable, str(converter), str(single_lowlevel), str(single_kicad)]
    print("Executing:", " ".join(cmd))
    res = subprocess.run(cmd)
    print("\nConverter exit code:", res.returncode)

    # Quick sanity
    sch = sorted(single_kicad.glob("*.kicad_sch"))
    pcb = sorted(single_kicad.glob("*.kicad_pcb"))
    if len(sch) != 1 or len(pcb) != 1:
        print("ERROR: Expected exactly one sch and one pcb in kicad_single/")
        return 1

    # Report traces/wires
    pcb_text = pcb[0].read_text(errors="ignore")
    segs = pcb_text.count("(segment")
    print(f"\nSegments in PCB: {segs}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

