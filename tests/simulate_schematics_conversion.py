#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Simulate Schematics (PNG) conversion on the latest output run.

Actions:
1) Clean ONLY output/[UNIQUE]/schematics
2) Invoke scripts/schematics_converter.py with input=lowlevel and output=schematics
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
    out_dir = latest / "schematics"
    converter = repo_root / "scripts" / "schematics_converter.py"

    if not lowlevel_dir.exists():
        print(f"ERROR: Missing lowlevel directory: {lowlevel_dir}")
        return 1
    if not converter.exists():
        print(f"ERROR: Missing converter: {converter}")
        return 1

    print("=" * 80)
    print("SCHEMATICS (PNG) CONVERTER RUNNER")
    print("=" * 80)
    print(f"Latest run folder: {latest}")
    print(f"Cleaning folder:   {out_dir}")
    clean_folder(out_dir)

    # Use the exec_in_venv.sh script to ensure execution within the virtual environment
    exec_script = repo_root / "bin" / "exec_in_venv.sh"
    cmd = [str(exec_script), sys.executable, str(converter), str(lowlevel_dir), str(out_dir)]
    print(f"\nExecuting: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
