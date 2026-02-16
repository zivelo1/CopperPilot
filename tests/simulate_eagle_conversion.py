#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Simulate Eagle conversion on the latest output run.

Actions:
1) Clean ONLY output/[UNIQUE]/eagle
2) Invoke scripts/eagle_converter.py with input=lowlevel and output=eagle
3) Verify parity between input circuits and output files

LOGGING REQUIREMENT:
When running this script, ALL logs MUST be written to the logs/ folder.
Usage:
    nohup python3 tests/simulate_eagle_conversion.py > logs/eagle_simulation.log 2>&1 &
"""

from __future__ import annotations

import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def find_latest_output_dir(root: Path) -> Optional[Path]:
    output_root = root / "output"
    if not output_root.exists():
        return None
    dirs = [p for p in output_root.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


def clean_folder(folder: Path) -> None:
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        return
    for entry in folder.iterdir():
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except Exception as e:
            print(f"WARNING: Could not delete {entry}: {e}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    latest = find_latest_output_dir(repo_root)
    if latest is None:
        print("ERROR: No output/* folder found")
        return 1

    lowlevel_dir = latest / "lowlevel"
    out_dir = latest / "eagle"
    converter = repo_root / "scripts" / "eagle_converter.py"

    if not lowlevel_dir.exists():
        print(f"ERROR: Missing lowlevel directory: {lowlevel_dir}")
        return 1
    if not converter.exists():
        print(f"ERROR: Missing converter: {converter}")
        return 1

    print("=" * 80)
    print("EAGLE CONVERTER RUNNER")
    print("=" * 80)
    print(f"Latest run folder: {latest}")
    print(f"Cleaning folder:   {out_dir}")
    clean_folder(out_dir)

    cmd = [sys.executable, str(converter), str(lowlevel_dir), str(out_dir)]
    print(f"\nExecuting: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)

    # Parity check: number of circuits must match generated files
    try:
        circuit_jsons = sorted([p for p in lowlevel_dir.glob('circuit_*.json')])
        sch_files = sorted([p for p in out_dir.glob('*.sch')])
        brd_files = sorted([p for p in out_dir.glob('*.brd')])

        circuits = len(circuit_jsons)
        sch = len(sch_files)
        brd = len(brd_files)

        print("=" * 80)
        print("PARITY CHECK")
        print("=" * 80)
        print(f"Circuits (lowlevel 'circuit_*.json'): {circuits}")
        print(f"Eagle schematics (.sch):            {sch}")
        print(f"Eagle boards (.brd):                {brd}")

        if sch != circuits or brd != circuits:
            print("\n❌ PARITY VIOLATION: counts do not match")
            missing_sch = {p.stem.replace('circuit_', '') for p in circuit_jsons} - {p.stem for p in sch_files}
            missing_brd = {p.stem.replace('circuit_', '') for p in circuit_jsons} - {p.stem for p in brd_files}
            if missing_sch:
                print(f"  Missing .sch for: {sorted(missing_sch)}")
            if missing_brd:
                print(f"  Missing .brd for: {sorted(missing_brd)}")
            return 1
        else:
            print("\n✅ PARITY OK: counts match")
    except Exception as e:
        print(f"WARNING: Parity check failed to run: {e}")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
