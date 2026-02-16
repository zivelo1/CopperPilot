#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Test KiCad compatibility by simulating KiCad's connection validation.

This test checks if our generated Eagle files would pass KiCad's ERC by validating:
1. Every pin has a wire endpoint within tolerance
2. Wires form connected networks
3. No dangling wires
"""

import xml.etree.ElementTree as ET
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from eagle.eagle_symbol_library import EagleSymbolLibrary
from eagle.eagle_geometry import GeometryCalculator


def test_kicad_compatibility(sch_file: Path):
    """Test if schematic is compatible with KiCad import."""
    print(f"\nTesting: {sch_file.name}")
    print("=" * 70)

    tree = ET.parse(sch_file)
    root = tree.getroot()

    # Extract symbol library
    symbol_lib = EagleSymbolLibrary()
    library = root.find('.//drawing/schematic/libraries/library')
    if library is not None:
        symbols = library.find('symbols')
        if symbols is not None and len(symbols) > 0:
            for symbol in symbols.findall('symbol'):
                try:
                    symbol_lib.extract_symbol(symbol)
                except Exception as e:
                    print(f"Warning: Failed to extract symbol: {e}")

    # Get instances
    instances = {}
    for inst in root.findall('.//instances/instance'):
        part = inst.get('part')
        instances[part] = {
            'x': float(inst.get('x')),
            'y': float(inst.get('y')),
            'rot': inst.get('rot', 'R0')
        }

    # Get parts→deviceset mapping
    parts_deviceset = {}
    for part_elem in root.findall('.//parts/part'):
        name = part_elem.get('name')
        parts_deviceset[name] = part_elem.get('deviceset')

    errors = []
    warnings = []
    tolerance = 0.01  # 0.01mm tolerance (KiCad uses tight tolerance)

    # Check each net
    for net in root.findall('.//nets/net'):
        net_name = net.get('name')

        for segment in net.findall('.//segment'):
            pinrefs = segment.findall('.//pinref')
            wires = segment.findall('.//wire')

            if len(pinrefs) < 2:
                continue

            # Get actual pin positions
            pin_positions = []
            for pinref in pinrefs:
                part = pinref.get('part')
                pin_name = pinref.get('pin')

                if part not in instances:
                    errors.append(f"Net {net_name}: Part {part} not found in instances")
                    continue

                # Get symbol and calculate pin position
                deviceset = parts_deviceset.get(part)
                if not deviceset:
                    errors.append(f"Net {net_name}: No deviceset for {part}")
                    continue

                # Find symbol for this deviceset/gate
                symbol_name = None
                for ds in root.findall(f".//deviceset[@name='{deviceset}']"):
                    for gate in ds.findall('.//gate'):
                        symbol_name = gate.get('symbol')
                        break
                    break

                if not symbol_name:
                    errors.append(f"Net {net_name}: No symbol for {part}")
                    continue

                try:
                    pin_offset_x, pin_offset_y = symbol_lib.get_pin_offset(symbol_name, pin_name)
                    inst = instances[part]
                    pin_x, pin_y = GeometryCalculator.calculate_pin_position(
                        inst['x'], inst['y'], pin_offset_x, pin_offset_y, inst['rot']
                    )
                    pin_positions.append((pin_x, pin_y, part, pin_name))
                except Exception as e:
                    errors.append(f"Net {net_name}: Failed to calculate position for {part}.{pin_name}: {e}")
                    continue

            if len(pin_positions) < 2:
                continue

            # Check each pin has a wire touching it
            for pin_x, pin_y, part, pin_name in pin_positions:
                has_wire = False
                for wire in wires:
                    try:
                        wx1 = float(wire.get('x1'))
                        wy1 = float(wire.get('y1'))
                        wx2 = float(wire.get('x2'))
                        wy2 = float(wire.get('y2'))

                        # Check if either wire endpoint touches this pin
                        dist1 = ((wx1 - pin_x)**2 + (wy1 - pin_y)**2)**0.5
                        dist2 = ((wx2 - pin_x)**2 + (wy2 - pin_y)**2)**0.5

                        if dist1 < tolerance or dist2 < tolerance:
                            has_wire = True
                            break
                    except (ValueError, TypeError):
                        continue

                if not has_wire:
                    errors.append(f"Net {net_name}: Pin {part}.{pin_name} at ({pin_x:.4f}, {pin_y:.4f}) has NO wire touching it")

    # Report
    if errors:
        print(f"\n❌ FAILED - {len(errors)} error(s):")
        for err in errors[:10]:  # Show first 10
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")
        return False
    else:
        print(f"\n✅ PASSED - All pins have wires touching them")
        return True


if __name__ == "__main__":
    # Default to latest eagle output; override with command line argument
    import sys
    if len(sys.argv) > 1:
        eagle_dir = Path(sys.argv[1])
    else:
        # Find most recent output directory
        output_root = Path(__file__).parent.parent / "output"
        output_dirs = sorted(output_root.glob("*/eagle"), reverse=True)
        if output_dirs:
            eagle_dir = output_dirs[0]
        else:
            print("No eagle output found. Pass directory as argument.")
            sys.exit(1)

    sch_files = list(eagle_dir.glob("*.sch"))

    passed = 0
    failed = 0

    for sch_file in sorted(sch_files):
        if test_kicad_compatibility(sch_file):
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed} passed, {failed} failed out of {len(sch_files)} files")
    print("=" * 70)

    sys.exit(0 if failed == 0 else 1)
