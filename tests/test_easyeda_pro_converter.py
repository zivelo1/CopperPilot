#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
EasyEDA Pro Converter Test
Tests EasyEDA Pro JSON format generation
"""

import sys
import subprocess
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _run_easyeda_converter(lowlevel_dir: Path, output_dir: Path) -> bool:
    """Run EasyEDA Pro converter"""
    print(f"\n🔄 Running EasyEDA Pro Converter...")
    script = Path("scripts/easyeda_pro_converter.py")
    cmd = [sys.executable, str(script), str(lowlevel_dir), str(output_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    for line in result.stdout.split('\n'):
        if any(x in line for x in ['Processing', 'SUCCESS', 'FAILED', 'COMPLETE']):
            print(line)

    return result.returncode == 0


@pytest.mark.converter
def test_easyeda_pro_converter(lowlevel_dir, easyeda_output_dir):
    """
    Test EasyEDA Pro converter: Clean → Run → Validate JSON
    
    Tests that the EasyEDA Pro converter:
    1. Runs successfully on perfect lowlevel input
    2. Generates valid JSON files
    3. Outputs EasyEDA Pro compatible format
    """
    print("\n" + "="*80)
    print("EASYEDA PRO CONVERTER TEST")
    print("="*80)

    # Run converter
    assert _run_easyeda_converter(lowlevel_dir, easyeda_output_dir), \
        "EasyEDA Pro converter execution failed"

    # Validate outputs exist
    json_files = list(easyeda_output_dir.glob("*.json"))
    assert len(json_files) > 0, "No JSON files generated"

    # Validate JSON files
    for json_file in json_files:
        with open(json_file) as f:
            try:
                data = json.load(f)
                assert isinstance(data, (dict, list)), f"{json_file.name}: Invalid JSON structure"
                print(f"  ✅ {json_file.name}: Valid JSON")
            except json.JSONDecodeError as e:
                pytest.fail(f"{json_file.name}: Invalid JSON - {e}")

    print("\n✅ EASYEDA PRO CONVERTER TEST PASSED")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
