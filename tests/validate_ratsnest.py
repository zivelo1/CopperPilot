#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Validate Eagle files are using RATSNEST approach (no copper routing).
This should result in 0 DRC violations when imported to KiCad.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

def validate_board_file(filepath):
    """Validate a single board file for ratsnest approach."""
    print(f"\nValidating: {filepath.name}")
    print("-" * 60)

    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
    except ET.ParseError as e:
        print(f"  ❌ XML Parse Error: {e}")
        return False

    # Count different types of elements
    signals = root.findall('.//board/signals/signal')
    elements = root.findall('.//board/elements/element')

    total_contactrefs = 0
    total_copper_wires = 0
    total_other_wires = 0
    nets_with_copper = []

    for signal in signals:
        net_name = signal.get('name', 'Unknown')
        contactrefs = signal.findall('contactref')
        total_contactrefs += len(contactrefs)

        # Check for copper wires (layers 1-16 are copper layers)
        copper_layers = ['1', '2', '3', '4', '5', '6', '7', '8',
                        '9', '10', '11', '12', '13', '14', '15', '16']

        copper_wires = []
        for wire in signal.findall('wire'):
            layer = wire.get('layer', '')
            if layer in copper_layers:
                copper_wires.append(wire)
                total_copper_wires += 1

        if copper_wires:
            nets_with_copper.append(f"{net_name} (layer {copper_wires[0].get('layer')})")

    # Count non-copper wires (board outline, silkscreen, etc)
    all_wires = root.findall('.//wire')
    for wire in all_wires:
        layer = wire.get('layer', '')
        if layer not in ['1', '2', '3', '4', '5', '6', '7', '8',
                         '9', '10', '11', '12', '13', '14', '15', '16']:
            total_other_wires += 1

    # Report results
    print(f"  Components: {len(elements)}")
    print(f"  Nets: {len(signals)}")
    print(f"  Contactrefs (pad assignments): {total_contactrefs}")
    print(f"  Copper wires (layers 1-16): {total_copper_wires}")
    print(f"  Other wires (outline/silk): {total_other_wires}")

    if total_copper_wires > 0:
        print(f"\n  ⚠️  WARNING: Found {total_copper_wires} copper wire(s)!")
        print(f"  Nets with copper routing:")
        for net in nets_with_copper[:5]:
            print(f"    - {net}")
        if len(nets_with_copper) > 5:
            print(f"    ... and {len(nets_with_copper) - 5} more")
        return False
    else:
        print(f"\n  ✅ RATSNEST MODE: No copper routing found")
        print(f"  ✅ Board has {total_contactrefs} pad connections defined as airwires")
        print(f"  ✅ Ready for manual/auto routing in Eagle")
        return True

def main():
    """Main validation function."""
    if len(sys.argv) != 2:
        print("Usage: python validate_ratsnest.py <eagle_directory>")
        sys.exit(1)

    eagle_dir = Path(sys.argv[1])
    if not eagle_dir.exists():
        print(f"Error: Directory {eagle_dir} does not exist")
        sys.exit(1)

    print("=" * 70)
    print("RATSNEST VALIDATION FOR EAGLE BOARD FILES")
    print("Ensures no copper routing (prevents DRC violations)")
    print("=" * 70)

    # Find all board files
    board_files = list(eagle_dir.glob("*.brd"))
    if not board_files:
        print("No board files found!")
        sys.exit(1)

    print(f"Found {len(board_files)} board file(s)")

    all_valid = True
    total_copper = 0

    for board_file in sorted(board_files):
        valid = validate_board_file(board_file)
        if not valid:
            all_valid = False

    print("\n" + "=" * 70)
    if all_valid:
        print("✅ VALIDATION PASSED - All boards use ratsnest approach")
        print("✅ Expected: 0 DRC violations when imported to KiCad")
        print("✅ Boards are ready for routing")
    else:
        print("❌ VALIDATION FAILED - Some boards have copper routing")
        print("❌ This will cause DRC violations in KiCad")
        print("❌ Fix the routing algorithm")
        sys.exit(1)
    print("=" * 70)

if __name__ == "__main__":
    main()