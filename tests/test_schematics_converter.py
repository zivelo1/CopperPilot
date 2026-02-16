#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Schematics Converter Test
Tests PNG schematic diagram generation
"""

import sys
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _run_schematics_converter(lowlevel_dir: Path, output_dir: Path) -> bool:
    """Run Schematics converter"""
    print(f"\n🔄 Running Schematics Converter...")
    script = Path("scripts/schematics_converter.py")
    cmd = [sys.executable, str(script), str(lowlevel_dir), str(output_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    for line in result.stdout.split('\n'):
        if any(x in line for x in ['Processing', 'SUCCESS', 'FAILED', 'COMPLETE', 'Generated']):
            print(line)

    return result.returncode == 0


@pytest.mark.converter
def test_schematics_converter(lowlevel_dir, schematics_output_dir):
    """
    Test Schematics converter: Clean → Run → Validate PNG
    
    Tests that the Schematics converter:
    1. Runs successfully on perfect lowlevel input
    2. Generates PNG schematic diagrams
    3. Files are valid images with reasonable size
    """
    print("\n" + "="*80)
    print("SCHEMATICS CONVERTER TEST")
    print("="*80)

    # Run converter
    assert _run_schematics_converter(lowlevel_dir, schematics_output_dir), \
        "Schematics converter execution failed"

    # Validate outputs exist
    png_files = list(schematics_output_dir.glob("*.png"))
    assert len(png_files) > 0, "No PNG files generated"

    # Validate PNG files
    for png_file in png_files:
        # Check file size (should be > 1KB for valid image)
        file_size = png_file.stat().st_size
        assert file_size > 1024, f"{png_file.name}: File too small ({file_size} bytes)"
        
        # Check PNG header
        with open(png_file, 'rb') as f:
            header = f.read(8)
            assert header == b'\x89PNG\r\n\x1a\n', f"{png_file.name}: Invalid PNG header"
        
        print(f"  ✅ {png_file.name}: Valid PNG ({file_size // 1024} KB)")

    print("\n✅ SCHEMATICS CONVERTER TEST PASSED")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
