#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle Converter Test - Clean, Run, Validate XML format
Tests Eagle converter outputs valid XML for KiCad/EasyEDA/Fusion360 import
"""

import sys
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _run_eagle_converter(lowlevel_dir: Path, output_dir: Path) -> bool:
    """Run Eagle converter"""
    print(f"\n🔄 Running Eagle Converter...")
    script = Path("scripts/eagle_converter.py")
    cmd = [sys.executable, str(script), str(lowlevel_dir), str(output_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    for line in result.stdout.split('\n'):
        if any(x in line for x in ['Processing', 'SUCCESS', 'FAILED', 'COMPLETE']):
            print(line)

    return result.returncode == 0


def _validate_eagle_xml(filepath: Path) -> Dict:
    """Validate Eagle XML file"""
    issues = []
    warnings = []

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        if root.tag != 'eagle':
            issues.append(f"{filepath.name}: Root tag is not 'eagle'")
            return {'passed': False, 'issues': issues, 'warnings': warnings}

        version = root.get('version')
        if not version:
            warnings.append(f"{filepath.name}: Missing version attribute")

        drawing = root.find('.//drawing')
        if drawing is None:
            issues.append(f"{filepath.name}: Missing drawing element")
            return {'passed': False, 'issues': issues, 'warnings': warnings}

        if filepath.suffix == '.sch':
            sheets = drawing.findall('.//sheet')
            if not sheets:
                issues.append(f"{filepath.name}: No sheets found in schematic")

            parts = drawing.findall('.//part')
            if not parts:
                issues.append(f"{filepath.name}: No parts found - schematic is empty")
            else:
                print(f"  ✅ {len(parts)} parts found")

            nets = drawing.findall('.//net')
            if not nets:
                warnings.append(f"{filepath.name}: No nets found - components may be unconnected")
            else:
                print(f"  ✅ {len(nets)} nets found")

        elif filepath.suffix == '.brd':
            elements = drawing.findall('.//element')
            if not elements:
                issues.append(f"{filepath.name}: No elements found - board is empty")
            else:
                print(f"  ✅ {len(elements)} elements found")

            signals = drawing.findall('.//signal')
            if not signals:
                warnings.append(f"{filepath.name}: No signals found - board may be unrouted")

    except ET.ParseError as e:
        issues.append(f"{filepath.name}: XML parse error: {e}")
    except Exception as e:
        issues.append(f"{filepath.name}: Validation error: {e}")

    return {'passed': len(issues) == 0, 'issues': issues, 'warnings': warnings}


@pytest.mark.converter
def test_eagle_converter(lowlevel_dir, eagle_output_dir):
    """
    Test Eagle converter: Clean → Run → Validate XML
    
    Tests that the Eagle converter:
    1. Runs successfully on perfect lowlevel input
    2. Generates valid .sch and .brd files
    3. Outputs well-formed XML compatible with Eagle/KiCad/EasyEDA
    """
    print("\n" + "="*80)
    print("EAGLE CONVERTER TEST")
    print("="*80)

    # Run converter
    assert _run_eagle_converter(lowlevel_dir, eagle_output_dir), \
        "Eagle converter execution failed"

    # Validate outputs
    all_issues = []
    for filepath in eagle_output_dir.glob("*.sch"):
        result = _validate_eagle_xml(filepath)
        all_issues.extend(result['issues'])
    
    for filepath in eagle_output_dir.glob("*.brd"):
        result = _validate_eagle_xml(filepath)
        all_issues.extend(result['issues'])

    assert len(all_issues) == 0, f"Eagle validation failed with {len(all_issues)} issues"

    print("\n✅ EAGLE CONVERTER TEST PASSED")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
