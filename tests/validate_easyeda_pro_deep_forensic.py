#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Deep EasyEDA Pro Validation (Forensic Level)

Runs light preflight checks plus the EasyEDA Pro forensic validator to ensure
files are import-ready and structurally sound. Exits non-zero on any failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
import subprocess


def _find_latest_output_dir(root: Path) -> Path | None:
    out = root / "output"
    if not out.exists():
        return None
    dirs = [p for p in out.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _preflight_easyeda(easy_dir: Path) -> list[str]:
    errors: list[str] = []
    epro = list(easy_dir.glob("*.epro"))
    if not epro:
        errors.append("No .epro files found")
        return errors
    # Basic size sanity (avoid empty artifacts)
    for f in epro:
        if f.stat().st_size < 1024:
            errors.append(f"{f.name}: file too small (<1KB)")
    # Require EasyEDA verification artifacts to exist before running full validator
    # Prefer collocated easyeda_results under easyeda_pro; fall back to sibling for legacy runs.
    results_root = easy_dir / "easyeda_results"
    if not results_root.exists():
        results_root = easy_dir.parent / "easyeda_results"
    for name in ("ERC", "DRC", "verification"):
        path = results_root / name
        if not path.exists() or not any(path.iterdir()):
            errors.append(f"Missing EasyEDA {name} artifacts under {path}")
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
        
    easy_dir = latest / "easyeda_pro"
    if not easy_dir.exists():
        print(f"ERROR: EasyEDA Pro folder not found: {easy_dir}")
        return 1

    print("=" * 80)
    print("EASYEDA PRO DEEP FORENSIC VALIDATION")
    print("=" * 80)
    print(f"Run folder: {latest}")
    print(f"Target dir: {easy_dir}\n")

    pre = _preflight_easyeda(easy_dir)
    if pre:
        print("Preflight checks failed:")
        for i, err in enumerate(pre, 1):
            print(f"  {i}. {err}")
        return 1
    else:
        print("Preflight: PASS")

    validator = repo / "tests" / "validate_easyeda_pro_forensic.py"
    cmd = [sys.executable, str(validator), str(easy_dir)]
    print(f"\nExecuting: {' '.join(cmd)}\n")
    res = subprocess.run(cmd)
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
