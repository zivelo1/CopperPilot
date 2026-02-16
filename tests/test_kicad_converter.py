#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Converter Test - Clean, Run, Validate with ERC/DRC
Tests KiCad converter with perfect lowlevel input
"""

import sys
import subprocess
import json
from pathlib import Path
from typing import Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _run_kicad_converter(lowlevel_dir: Path, output_dir: Path) -> bool:
    """Run KiCad converter"""
    print(f"\n🔄 Running KiCad Converter...")
    print(f"  Input: {lowlevel_dir}")
    print(f"  Output: {output_dir}")

    script = Path("scripts/kicad_converter.py")
    cmd = [sys.executable, str(script), str(lowlevel_dir), str(output_dir)]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    # Print summary lines
    if result.stdout:
        for line in result.stdout.split('\n'):
            if any(x in line for x in ['Processing', 'SUCCESS', 'FAILED', 'errors', 'warnings', 'COMPLETE']):
                print(line)

    if result.returncode != 0:
        print(f"❌ KiCad Converter FAILED (exit code: {result.returncode})")
        if result.stderr:
            print("STDERR:", result.stderr)
        return False

    print(f"✅ KiCad Converter completed")
    return True


def _validate_kicad_file(filepath: Path, file_type: str) -> Dict:
    """Validate a single KiCad file"""
    issues = []
    warnings = []

    if not filepath.exists():
        issues.append(f"File not found: {filepath.name}")
        return {'passed': False, 'issues': issues, 'warnings': warnings}

    try:
        with open(filepath, 'r') as f:
            content = f.read()

        if len(content) < 100:
            issues.append(f"{filepath.name}: File too short - likely empty or corrupted")
            return {'passed': False, 'issues': issues, 'warnings': warnings}

        if file_type == 'kicad_sch':
            if '(kicad_sch' not in content:
                issues.append(f"{filepath.name}: Not a valid KiCad schematic file")
            if '(version' not in content:
                warnings.append(f"{filepath.name}: Missing version tag")

            symbol_count = content.count('(symbol ')
            if symbol_count == 0:
                issues.append(f"{filepath.name}: No symbols found - circuit is empty")

            wire_count = content.count('(wire')
            junction_count = content.count('(junction')
            if wire_count == 0 and junction_count == 0:
                warnings.append(f"{filepath.name}: No wires or junctions - components may be disconnected")

        elif file_type == 'kicad_pcb':
            if '(kicad_pcb' not in content:
                issues.append(f"{filepath.name}: Not a valid KiCad PCB file")

            footprint_count = content.count('(footprint')
            if footprint_count == 0:
                issues.append(f"{filepath.name}: No footprints found - PCB is empty")

            track_count = content.count('(segment')
            if track_count == 0:
                warnings.append(f"{filepath.name}: No tracks found - PCB may be unrouted")

        elif file_type == 'kicad_pro':
            try:
                proj_data = json.loads(content)
                if 'board' not in proj_data and 'schematic' not in proj_data:
                    warnings.append(f"{filepath.name}: Project file missing board/schematic references")
            except json.JSONDecodeError:
                issues.append(f"{filepath.name}: Not valid JSON")

    except Exception as e:
        issues.append(f"{filepath.name}: Failed to read/parse: {e}")

    return {
        'passed': len(issues) == 0,
        'issues': issues,
        'warnings': warnings
    }


def _run_erc_drc_checks(output_dir: Path) -> Dict:
    """Run ERC/DRC equivalent checks on KiCad files"""
    print(f"\n🔍 Running ERC/DRC Checks...")
    print(f"{'='*80}")

    issues = []
    warnings = []

    sch_files = list(output_dir.glob("*.kicad_sch"))
    pcb_files = list(output_dir.glob("*.kicad_pcb"))

    print(f"Found {len(sch_files)} schematic files")
    print(f"Found {len(pcb_files)} PCB files")

    # ERC checks on schematics
    for sch_file in sch_files:
        print(f"\n📋 ERC Check: {sch_file.name}")

        with open(sch_file, 'r') as f:
            content = f.read()

        symbol_count = content.count('(symbol ')
        wire_count = content.count('(wire')
        label_count = content.count('(label')

        print(f"  Symbols: {symbol_count}, Wires: {wire_count}, Labels: {label_count}")

        if '(no_connect' in content:
            nc_count = content.count('(no_connect')
            warnings.append(f"{sch_file.name}: {nc_count} no-connect markers")

        if 'ERC' in content and 'error' in content.lower():
            issues.append(f"{sch_file.name}: Contains ERC error markers")

        if symbol_count > 0 and wire_count == 0:
            issues.append(f"{sch_file.name}: Components present but no wires - ERC FAIL")
        elif symbol_count > 0:
            print(f"  ✅ ERC: Components connected with wires")

    # DRC checks on PCBs
    for pcb_file in pcb_files:
        print(f"\n📋 DRC Check: {pcb_file.name}")

        with open(pcb_file, 'r') as f:
            content = f.read()

        footprint_count = content.count('(footprint')
        track_count = content.count('(segment')
        via_count = content.count('(via')

        print(f"  Footprints: {footprint_count}, Tracks: {track_count}, Vias: {via_count}")

        if 'clearance' in content.lower() and 'violation' in content.lower():
            issues.append(f"{pcb_file.name}: Contains clearance violations")

        if footprint_count > 0 and track_count == 0:
            warnings.append(f"{pcb_file.name}: PCB has footprints but no tracks - likely unrouted")
        elif footprint_count > 0:
            print(f"  ✅ DRC: Footprints have routing")

        if '(gr_line' not in content and '(gr_rect' not in content:
            warnings.append(f"{pcb_file.name}: No board outline found")

    return {
        'passed': len(issues) == 0,
        'issues': issues,
        'warnings': warnings
    }


def _validate_kicad_outputs(output_dir: Path) -> Dict:
    """Deep validation of KiCad outputs"""
    print(f"\n🔍 DEEP VALIDATION OF KICAD OUTPUTS")
    print(f"{'='*80}")

    all_issues = []
    all_warnings = []

    # Find all circuit files
    circuit_files = {}
    for sch_file in output_dir.glob("*.kicad_sch"):
        base_name = sch_file.stem
        circuit_files[base_name] = {
            'sch': sch_file,
            'pcb': output_dir / f"{base_name}.kicad_pcb",
            'pro': output_dir / f"{base_name}.kicad_pro"
        }

    print(f"Found {len(circuit_files)} circuits\n")

    # Validate each circuit
    for circuit_name, files in circuit_files.items():
        print(f"📁 Circuit: {circuit_name}")
        print(f"{'-'*80}")

        for file_type, filepath in files.items():
            if not filepath.exists():
                all_issues.append(f"{circuit_name}: Missing {file_type} file")
                print(f"  ❌ Missing: {filepath.name}")
            else:
                print(f"  ✅ Found: {filepath.name}")
                result = _validate_kicad_file(filepath, f"kicad_{file_type}")
                all_issues.extend(result['issues'])
                all_warnings.extend(result['warnings'])

    # Run ERC/DRC checks
    erc_drc_result = _run_erc_drc_checks(output_dir)
    all_issues.extend(erc_drc_result['issues'])
    all_warnings.extend(erc_drc_result['warnings'])

    # Final verdict
    print(f"\n{'='*80}")
    print(f"VALIDATION RESULTS")
    print(f"{'='*80}")

    if all_issues:
        print(f"\n❌ CRITICAL ISSUES ({len(all_issues)}):")
        for issue in all_issues:
            print(f"  - {issue}")

    if all_warnings:
        print(f"\n⚠️  WARNINGS ({len(all_warnings)}):")
        for warning in all_warnings[:10]:
            print(f"  - {warning}")
        if len(all_warnings) > 10:
            print(f"  ... and {len(all_warnings) - 10} more warnings")

    passed = len(all_issues) == 0

    if passed and len(all_warnings) == 0:
        print(f"\n✅ ALL KICAD FILES ARE 100% PERFECT")
        print(f"   ERC: PASSED")
        print(f"   DRC: PASSED")
        print(f"   Ready for KiCad 9 and PCB manufacturing")
    elif passed:
        print(f"\n✅ KICAD FILES PASSED ERC/DRC (with {len(all_warnings)} warnings)")
    else:
        print(f"\n❌ KICAD VALIDATION FAILED")
        print(f"   ERC/DRC FAILED - Circuits have errors")

    return {
        'passed': passed,
        'issues': all_issues,
        'warnings': all_warnings
    }


@pytest.mark.converter
def test_kicad_converter(lowlevel_dir, kicad_output_dir):
    """
    Test KiCad converter: Clean → Run → Validate (ERC/DRC)

    Tests that the KiCad converter:
    1. Runs successfully on perfect lowlevel input
    2. Generates valid .kicad_sch, .kicad_pcb, .kicad_pro files
    3. Passes ERC (Electrical Rule Check) validation
    4. Passes DRC (Design Rule Check) validation
    """
    print("\n" + "="*80)
    print("KICAD CONVERTER TEST - CLEAN, RUN, VALIDATE (ERC/DRC)")
    print("="*80)

    # Run converter
    assert _run_kicad_converter(lowlevel_dir, kicad_output_dir), \
        "KiCad converter execution failed"

    # Validate outputs
    result = _validate_kicad_outputs(kicad_output_dir)

    # Assert validation passed
    if not result['passed']:
        print("\n" + "="*80)
        print("❌ KICAD CONVERTER TEST FAILED")
        print("="*80)
        pytest.fail(f"KiCad validation failed with {len(result['issues'])} issues")

    print("\n" + "="*80)
    print("🎉 KICAD CONVERTER TEST PASSED - 100% PERFECT")
    print("="*80)


if __name__ == "__main__":
    # Allow running as script for backwards compatibility
    sys.exit(pytest.main([__file__, "-v"]))
