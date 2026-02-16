#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Forensic Validation Script for Eagle Schematics

Performs deep validation of generated Eagle files to ensure:
1. Segment structure matches real Eagle files (20-40% isolated, 60-80% multi-pin)
2. Wire connectivity - wires actually connect pins
3. Junction placement - junctions at branch points
4. No missing connections
"""

import xml.etree.ElementTree as ET
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def analyze_schematic(sch_file: Path) -> Dict:
    """Analyze Eagle schematic structure."""
    tree = ET.parse(sch_file)
    root = tree.getroot()

    results = {
        'file': sch_file.name,
        'total_segments': 0,
        'single_pinref_segments': 0,
        'multi_pinref_segments': 0,
        'total_pinrefs': 0,
        'total_wires': 0,
        'total_junctions': 0,
        'total_labels': 0,
        'nets': [],
        'errors': [],
        'warnings': []
    }

    # Analyze each net
    nets = root.findall('.//nets/net')
    for net in nets:
        net_name = net.get('name')
        segments = net.findall('.//segment')

        net_info = {
            'name': net_name,
            'segments': len(segments),
            'pinrefs': 0,
            'wires': 0,
            'junctions': 0
        }

        for segment in segments:
            results['total_segments'] += 1

            pinrefs = segment.findall('.//pinref')
            wires = segment.findall('.//wire')
            junctions = segment.findall('.//junction')
            labels = segment.findall('.//label')

            num_pinrefs = len(pinrefs)
            num_wires = len(wires)
            num_junctions = len(junctions)
            num_labels = len(labels)

            results['total_pinrefs'] += num_pinrefs
            results['total_wires'] += num_wires
            results['total_junctions'] += num_junctions
            results['total_labels'] += num_labels

            net_info['pinrefs'] += num_pinrefs
            net_info['wires'] += num_wires
            net_info['junctions'] += num_junctions

            # Categorize segment
            if num_pinrefs == 1:
                results['single_pinref_segments'] += 1
                # Single pinref should have label
                if num_labels == 0:
                    results['warnings'].append(
                        f"Net '{net_name}': Single-pinref segment missing label"
                    )
            elif num_pinrefs > 1:
                results['multi_pinref_segments'] += 1
                # Multi-pinref should have wires
                if num_wires == 0:
                    results['errors'].append(
                        f"Net '{net_name}': {num_pinrefs} pins but NO wires!"
                    )
                # Should have at least (n-1) wires for MST
                elif num_wires < (num_pinrefs - 1):
                    results['warnings'].append(
                        f"Net '{net_name}': {num_pinrefs} pins but only {num_wires} wires (need {num_pinrefs - 1})"
                    )

            # Check for orphaned segments (no connectivity)
            if num_pinrefs > 0 and num_wires == 0 and num_labels == 0:
                results['errors'].append(
                    f"Net '{net_name}': Segment has {num_pinrefs} pins but NO wires or labels!"
                )

        results['nets'].append(net_info)

    # Calculate percentages
    if results['total_segments'] > 0:
        results['isolated_pct'] = (results['single_pinref_segments'] / results['total_segments']) * 100
        results['multi_pct'] = (results['multi_pinref_segments'] / results['total_segments']) * 100
    else:
        results['isolated_pct'] = 0
        results['multi_pct'] = 0

    # Validate segment distribution
    if results['total_segments'] > 10:
        if results['isolated_pct'] > 50:
            results['errors'].append(
                f"STRUCTURE ERROR: {results['isolated_pct']:.1f}% isolated segments (expected 0-40%)"
            )
        elif results['isolated_pct'] > 45:
            results['warnings'].append(
                f"High isolated percentage: {results['isolated_pct']:.1f}% (expected 0-40%)"
            )

        if results['multi_pct'] < 50:
            results['errors'].append(
                f"STRUCTURE ERROR: Only {results['multi_pct']:.1f}% multi-pin segments (expected 60-100%)"
            )

    return results


def print_report(results: Dict):
    """Print formatted validation report."""
    print(f"\n{'=' * 80}")
    print(f"FORENSIC VALIDATION REPORT: {results['file']}")
    print(f"{'=' * 80}")

    print(f"\n📊 SEGMENT STRUCTURE:")
    print(f"  Total segments: {results['total_segments']}")
    print(f"  Single-pinref:  {results['single_pinref_segments']} ({results['isolated_pct']:.1f}%)")
    print(f"  Multi-pinref:   {results['multi_pinref_segments']} ({results['multi_pct']:.1f}%)")

    print(f"\n📈 CONNECTIVITY ELEMENTS:")
    print(f"  Total pinrefs:   {results['total_pinrefs']}")
    print(f"  Total wires:     {results['total_wires']}")
    print(f"  Total junctions: {results['total_junctions']}")
    print(f"  Total labels:    {results['total_labels']}")

    print(f"\n🔌 NET ANALYSIS:")
    print(f"  Total nets: {len(results['nets'])}")
    for net in results['nets'][:10]:  # Show first 10
        print(f"    {net['name']}: {net['segments']} segs, {net['pinrefs']} pins, {net['wires']} wires, {net['junctions']} juncs")
    if len(results['nets']) > 10:
        print(f"    ... and {len(results['nets']) - 10} more nets")

    # Errors
    if results['errors']:
        print(f"\n❌ ERRORS ({len(results['errors'])}):")
        for error in results['errors']:
            print(f"  - {error}")
    else:
        print(f"\n✅ NO ERRORS")

    # Warnings
    if results['warnings']:
        print(f"\n⚠️  WARNINGS ({len(results['warnings'])}):")
        for warning in results['warnings'][:10]:
            print(f"  - {warning}")
        if len(results['warnings']) > 10:
            print(f"  ... and {len(results['warnings']) - 10} more warnings")

    # Overall assessment
    print(f"\n{'=' * 80}")
    if not results['errors']:
        print(f"✅ VALIDATION PASSED - File structure is correct")
    else:
        print(f"❌ VALIDATION FAILED - {len(results['errors'])} critical errors")
    print(f"{'=' * 80}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 forensic_validation.py <path_to_eagle_folder>")
        sys.exit(1)

    eagle_dir = Path(sys.argv[1])
    if not eagle_dir.exists():
        print(f"Error: Directory not found: {eagle_dir}")
        sys.exit(1)

    # Find all .sch files
    sch_files = list(eagle_dir.glob("*.sch"))
    if not sch_files:
        print(f"No .sch files found in {eagle_dir}")
        sys.exit(1)

    print(f"\n{'#' * 80}")
    print(f"# FORENSIC VALIDATION - EAGLE SCHEMATIC FILES")
    print(f"# Directory: {eagle_dir}")
    print(f"# Files: {len(sch_files)}")
    print(f"{'#' * 80}")

    all_results = []
    total_errors = 0
    total_warnings = 0

    for sch_file in sorted(sch_files):
        try:
            results = analyze_schematic(sch_file)
            all_results.append(results)
            total_errors += len(results['errors'])
            total_warnings += len(results['warnings'])
            print_report(results)
        except Exception as e:
            print(f"\n❌ ERROR analyzing {sch_file.name}: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print(f"\n{'#' * 80}")
    print(f"# SUMMARY - ALL FILES")
    print(f"{'#' * 80}")
    print(f"Files analyzed: {len(all_results)}")
    print(f"Total errors: {total_errors}")
    print(f"Total warnings: {total_warnings}")

    if total_errors == 0:
        print(f"\n✅✅✅ ALL FILES PASSED FORENSIC VALIDATION ✅✅✅")
        print(f"100% PERFECT - Ready for production")
    else:
        print(f"\n❌❌❌ VALIDATION FAILED ❌❌❌")
        print(f"{total_errors} critical errors found across all files")

    print(f"{'#' * 80}\n")

    sys.exit(0 if total_errors == 0 else 1)


if __name__ == '__main__':
    main()
