#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Deep Schematics Description (Text) Validation

Ensures each lowlevel circuit has a corresponding wiring text file in
schematics_desc and that files are non-empty and contain plausible wiring
content. Exits non-zero on any failure.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _find_latest_output_dir(root: Path) -> Path | None:
    out = root / "output"
    if not out.exists():
        return None
    dirs = [p for p in out.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    latest = _find_latest_output_dir(repo)
    if not latest:
        print("ERROR: No output/* directory found")
        return 1

    low = latest / "lowlevel"
    desc = latest / "schematics_desc"
    if not low.exists() or not desc.exists():
        print(f"ERROR: Missing required folders (lowlevel={low.exists()} schematics_desc={desc.exists()})")
        return 1

    circuits = [p for p in low.glob("circuit_*.json")]
    missing = []
    weak = []
    for c in circuits:
        name = c.stem.replace("circuit_", "")
        txt = desc / f"circuit_{name}_wiring.txt"
        if not txt.exists():
            missing.append(txt.name)
            continue
        text = txt.read_text(errors='ignore')
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 5:
            weak.append(f"{txt.name}: too few lines")
        # Heuristic content checks
        if not any(k in text for k in ("NET", "->", ":", "PIN", "GND", "VCC")):
            weak.append(f"{txt.name}: lacks wiring keywords")

    if missing or weak:
        if missing:
            print("Missing schematics_desc files:")
            for f in missing:
                print(f"  - {f}")
        if weak:
            print("Weak content:")
            for w in weak:
                print(f"  - {w}")
        return 1

    print("Schematics description (text) validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

