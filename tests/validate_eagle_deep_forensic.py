#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Deep Eagle Validation (Forensic Level)

Combines structural preflight checks with the comprehensive Eagle validator to
confirm files are importable and manufacturable (ratsnest policy, geometry,
segment structure). Exits non-zero on any failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
import xml.etree.ElementTree as ET
import subprocess


def _find_latest_output_dir(root: Path) -> Path | None:
    output_root = root / "output"
    if not output_root.exists():
        return None
    dirs = [p for p in output_root.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _preflight_eagle(eagle_dir: Path) -> list[str]:
    errors: list[str] = []
    sch_files = sorted(eagle_dir.glob("*.sch"))
    brd_files = sorted(eagle_dir.glob("*.brd"))
    if not sch_files or not brd_files:
        errors.append("Missing .sch/.brd outputs")
        return errors

    # Ensure 1:1 base names
    sch_bases = {f.stem for f in sch_files}
    brd_bases = {f.stem for f in brd_files}
    if sch_bases != brd_bases:
        errors.append(f"SCH/BRD mismatch: sch={len(sch_bases)} brd={len(brd_bases)}")

    # Basic XML well-formedness
    for f in sch_files + brd_files:
        try:
            ET.parse(f)
        except Exception as e:
            errors.append(f"XML parse error in {f.name}: {e}")

    return errors


def _forensic_check_xml(eagle_dir: Path) -> list[str]:
    """Perform deep forensic checks on Eagle XML structure."""
    errors: list[str] = []
    sch_files = sorted(eagle_dir.glob("*.sch"))

    for sch_file in sch_files:
        try:
            tree = ET.parse(sch_file)
            root = tree.getroot()

            # 1. Wire Count Check (Layer 91 - Nets)
            # Must have wires on layer 91 for schematic connectivity to be visible
            wires = root.findall(".//schematic//segment//wire[@layer='91']")
            if not wires:
                errors.append(f"{sch_file.name}: CRITICAL - No wires on layer 91 found. Schematic is visually disconnected.")

            # 2. Grid Alignment Check (Instances)
            # Components should be on 0.05" (1.27mm) or 0.1" (2.54mm) grid
            instances = root.findall(".//schematic//instance")
            misaligned = 0
            for inst in instances:
                x = float(inst.get('x', 0))
                y = float(inst.get('y', 0))
                # Check alignment to 1.27mm (0.05 inch) with small tolerance
                if (abs(x % 1.27) > 0.01 and abs(x % 1.27 - 1.27) > 0.01) or \
                   (abs(y % 1.27) > 0.01 and abs(y % 1.27 - 1.27) > 0.01):
                    misaligned += 1
            
            if misaligned > 0:
                errors.append(f"{sch_file.name}: {misaligned} components are not aligned to 0.05\" (1.27mm) grid.")

        except Exception as e:
            errors.append(f"{sch_file.name}: Forensic check failed: {e}")

    return errors


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    
    # Phase G.3 (Forensic Fix 20260211): Support explicit target path
    if len(sys.argv) > 1:
        latest = Path(sys.argv[1])
        if not latest.is_absolute():
            latest = repo / latest
    else:
        latest = _find_latest_output_dir(repo)
        
    if not latest or not latest.exists():
        print(f"ERROR: Target directory not found: {latest}")
        return 1
        
    eagle_dir = latest / "eagle"
    if not eagle_dir.exists():
        print(f"ERROR: Eagle folder not found: {eagle_dir}")
        return 1

    print("=" * 80)
    print("EAGLE DEEP FORENSIC VALIDATION")
    print("=" * 80)
    print(f"Run folder: {latest}")
    print(f"Target dir: {eagle_dir}\n")

    pre = _preflight_eagle(eagle_dir)
    if pre:
        print("Preflight checks failed:")
        for i, err in enumerate(pre, 1):
            print(f"  {i}. {err}")
        return 1
    else:
        print("Preflight: PASS")

    # Deep Forensic Checks
    forensic_errors = _forensic_check_xml(eagle_dir)
    if forensic_errors:
        print("Forensic checks failed:")
        for i, err in enumerate(forensic_errors, 1):
            print(f"  {i}. {err}")
        return 1
    print("Forensic Checks: PASS")

    validator = repo / "tests" / "validate_eagle_comprehensive.py"
    cmd = [sys.executable, str(validator), str(eagle_dir)]
    print(f"\nExecuting: {' '.join(cmd)}\n")
    res = subprocess.run(cmd)
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
