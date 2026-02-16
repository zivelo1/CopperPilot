#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Schematics Text Converter Test
Tests human-readable text description generation
"""

import sys
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _run_schematics_text_converter(lowlevel_dir: Path, output_dir: Path) -> bool:
    """Run Schematics Text converter"""
    print(f"\n🔄 Running Schematics Text Converter...")
    script = Path("scripts/schematics_text_converter.py")
    cmd = [sys.executable, str(script), str(lowlevel_dir), str(output_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    for line in result.stdout.split('\n'):
        if any(x in line for x in ['Processing', 'SUCCESS', 'FAILED', 'COMPLETE', 'Generated']):
            print(line)

    return result.returncode == 0


@pytest.mark.converter
def test_schematics_text_converter(lowlevel_dir, schematics_desc_output_dir):
    """
    Test Schematics Text converter: Clean → Run → Validate TXT
    
    Tests that the Schematics Text converter:
    1. Runs successfully on perfect lowlevel input
    2. Generates text description files
    3. Content is human-readable with component/connection info
    """
    print("\n" + "="*80)
    print("SCHEMATICS TEXT CONVERTER TEST")
    print("="*80)

    # Run converter
    assert _run_schematics_text_converter(lowlevel_dir, schematics_desc_output_dir), \
        "Schematics Text converter execution failed"

    # Validate outputs exist
    txt_files = list(schematics_desc_output_dir.glob("*.txt"))
    assert len(txt_files) > 0, "No text files generated"

    # Validate text files
    for txt_file in txt_files:
        with open(txt_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # Check file is not empty
            assert len(content) > 100, f"{txt_file.name}: Content too short"
            
            # Check for key circuit description keywords
            keywords = ['component', 'connection', 'pin', 'net', 'wire']
            found_keywords = sum(1 for kw in keywords if kw.lower() in content.lower())
            assert found_keywords >= 2, f"{txt_file.name}: Missing circuit description keywords"
            
            print(f"  ✅ {txt_file.name}: Valid ({len(content)} chars, {found_keywords}/5 keywords)")

    print("\n✅ SCHEMATICS TEXT CONVERTER TEST PASSED")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
