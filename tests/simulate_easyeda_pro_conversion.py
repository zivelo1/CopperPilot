#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Simulate EasyEDA Pro conversion on the latest output run.
Multiprocessing enabled for speed (5+ cores).

Actions:
1) Clean ONLY output/[UNIQUE]/easyeda_pro
2) Invoke scripts/easyeda_converter_pro.py with input=lowlevel and output=easyeda_pro
"""

from __future__ import annotations

import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional
import multiprocessing

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

def convert_circuit(args):
    converter_path, input_file, output_dir = args
    # For EasyEDA, the converter takes a FOLDER, not a file.
    # So we can't parallelize easily by invoking the script multiple times on single files
    # unless the script supports single file mode.
    # The script takes (input_folder, output_folder).
    # It iterates internally.
    
    # Wait, the user asked to use 5 CPU cores. 
    # The current easyeda_converter_pro.py iterates sequentially.
    # I should probably modify easyeda_converter_pro.py to support multiprocessing internally?
    # OR, I can invoke it here on single files if I modify it to accept file path.
    
    # Looking at easyeda_converter_pro.py:
    # if self.input_path.is_dir(): ... else: circuit_files = [self.input_path]
    # So it DOES support single file input!
    
    cmd = [sys.executable, str(converter_path), str(input_file), str(output_dir)]
    # print(f"Starting: {input_file.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Failed: {input_file.name}\n{result.stderr}")
    else:
        print(f"✅ Processed: {input_file.name}")
    return result.returncode

def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    latest = find_latest_output_dir(repo_root)
    if latest is None:
        print("ERROR: No output/* folder found")
        return 1

    lowlevel_dir = latest / "lowlevel"
    out_dir = latest / "easyeda_pro"
    converter = repo_root / "scripts" / "easyeda_converter_pro.py"

    if not lowlevel_dir.exists():
        print(f"ERROR: Missing lowlevel directory: {lowlevel_dir}")
        return 1
    if not converter.exists():
        print(f"ERROR: Missing converter: {converter}")
        return 1

    print("=" * 80)
    print("EASYEDA PRO CONVERTER RUNNER (PARALLEL)")
    print("=" * 80)
    print(f"Latest run folder: {latest}")
    print(f"Cleaning folder:   {out_dir}")
    clean_folder(out_dir)

    # Gather circuit files
    circuit_files = sorted(lowlevel_dir.glob("circuit_*.json"))
    if not circuit_files:
        print("No circuit files found.")
        return 0

    print(f"Found {len(circuit_files)} circuits. Processing with 7 workers...")
    
    # Prepare args
    tasks = [(converter, f, out_dir) for f in circuit_files]
    
    with multiprocessing.Pool(processes=7) as pool:
        results = pool.map(convert_circuit, tasks)
        
    failures = sum(r for r in results if r != 0)
    print(f"\nDone. Failures: {failures}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
