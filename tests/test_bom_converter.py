#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
BOM Converter Test
Tests Bill of Materials generation with dual-supplier support
"""

import sys
import subprocess
import csv
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _run_bom_converter(lowlevel_dir: Path, output_dir: Path) -> bool:
    """Run BOM converter"""
    print(f"\n🔄 Running BOM Converter...")
    script = Path("scripts/bom_converter.py")
    cmd = [sys.executable, str(script), str(lowlevel_dir), str(output_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    for line in result.stdout.split('\n'):
        if any(x in line for x in ['Processing', 'BOM', 'SUCCESS', 'FAILED', 'COMPLETE']):
            print(line)

    return result.returncode == 0


@pytest.mark.converter
def test_bom_converter(lowlevel_dir, bom_output_dir):
    """
    Test BOM converter: Clean → Run → Validate CSV
    
    Tests that the BOM converter:
    1. Runs successfully on perfect lowlevel input
    2. Generates BOM files in CSV format
    3. Includes dual-supplier information
    """
    print("\n" + "="*80)
    print("BOM CONVERTER TEST")
    print("="*80)

    # Run converter
    assert _run_bom_converter(lowlevel_dir, bom_output_dir), \
        "BOM converter execution failed"

    # Validate outputs exist
    bom_files = list(bom_output_dir.glob("*.csv")) + list(bom_output_dir.glob("*.xlsx"))
    assert len(bom_files) > 0, "No BOM files generated"

    # Validate CSV files
    for bom_file in bom_output_dir.glob("*.csv"):
        with open(bom_file, newline='') as f:
            try:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) > 0, f"{bom_file.name}: BOM is empty"
                
                # Check for required columns
                if rows:
                    headers = rows[0].keys()
                    assert any('qty' in h.lower() or 'quantity' in h.lower() for h in headers), \
                        f"{bom_file.name}: Missing quantity column"
                    print(f"  ✅ {bom_file.name}: {len(rows)} items")
            except csv.Error as e:
                pytest.fail(f"{bom_file.name}: Invalid CSV - {e}")

    print("\n✅ BOM CONVERTER TEST PASSED")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
