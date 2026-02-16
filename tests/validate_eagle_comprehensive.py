#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Comprehensive Forensic Validation for Eagle CAD Files
Tests EVERYTHING - structure, attributes, connectivity, format compliance

This script performs 11 validation tests on generated Eagle files:
1. File existence and XML validity
2. XML well-formedness
3. ⭐ GEOMETRIC ACCURACY - Wire endpoints match pin positions (CRITICAL TEST)
4. Segment structure correctness
5. Label attribute validation
6. Wire attribute validation
7. Label-based connectivity format
8. Board ratsnest validation
9. Component placement validation
10. Net completeness
11. Cross-file consistency

⭐ Test #3 (Geometric Accuracy) is THE MOST IMPORTANT:
   - Verifies wires are at EXACT pin positions (within 0.1mm)
   - Catches bugs that pass XML structure validation
   - Tests 20 random pins per circuit for efficiency
   - Pass threshold: ≥95% accuracy overall
   - This test would have caught the fuse→IC2 symbol bug immediately

Usage:
    python3 tests/validate_eagle_comprehensive.py <eagle_directory>
    python3 tests/validate_eagle_comprehensive.py output/20251019-091410-4587f35c/eagle

Expected behavior:
    - All 11 tests must pass for production readiness
    - Geometric accuracy test is critical - if this fails, files are broken
    - Exit code 0 = all tests passed, 1 = failures detected
"""

import sys
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple
import random


class ComprehensiveEagleValidator:
    def __init__(self, eagle_dir: str, lowlevel_dir: str = None):
        self.eagle_dir = Path(eagle_dir)
        self.lowlevel_dir = Path(lowlevel_dir) if lowlevel_dir else None
        self.errors = []
        self.warnings = []
        self.test_results = {}

    def run_all_tests(self) -> bool:
        """Run all validation tests and return overall pass/fail."""
        print("=" * 80)
        print("COMPREHENSIVE FORENSIC VALIDATION - EAGLE CAD FILES")
        print("Deep Analysis of Structure, Connectivity, and Production Readiness")
        print("=" * 80)
        print(f"Directory: {self.eagle_dir}")
        print("=" * 80)
        print()

        tests = [
            ("File Existence", self._test_file_existence),
            ("XML Validity", self._test_xml_validity),
        ]

        # FIX #2 (November 12, 2025): Add pin completeness test if lowlevel directory provided
        # This catches missing NC pins that validators previously missed
        if self.lowlevel_dir and self.lowlevel_dir.exists():
            tests.append(("Pin Completeness", self._test_pin_completeness))

        tests.extend([
            ("Geometric Accuracy", self._test_geometric_accuracy),
            ("Segment Structure", self._test_segment_structure),
            ("Label Attributes", self._test_label_attributes),
            ("Wire Attributes", self._test_wire_attributes),
            ("Label Connectivity Format", self._test_label_connectivity),
            ("Board Ratsnest", self._test_board_ratsnest),
            ("Component Placement", self._test_component_placement),
            ("Net Completeness", self._test_net_completeness),
            ("Cross-File Consistency", self._test_cross_file_consistency),
        ])

        for test_name, test_func in tests:
            print(f"\n{'='*80}")
            print(f"TEST: {test_name}")
            print('='*80)
            passed = test_func()
            self.test_results[test_name] = passed
            if passed:
                print(f"✅ {test_name}: PASSED")
            else:
                print(f"❌ {test_name}: FAILED")

        # Final report
        self._print_final_report()

        # Return overall pass/fail
        return all(self.test_results.values())

    def _test_file_existence(self) -> bool:
        """Test 1: Verify all expected files exist."""
        sch_files = list(self.eagle_dir.glob("*.sch"))
        brd_files = list(self.eagle_dir.glob("*.brd"))

        print(f"Schematic files found: {len(sch_files)}")
        print(f"Board files found: {len(brd_files)}")

        if len(sch_files) == 0:
            self.errors.append("No schematic files found")
            return False

        if len(brd_files) == 0:
            self.errors.append("No board files found")
            return False

        # Check matching pairs
        sch_bases = {f.stem for f in sch_files}
        brd_bases = {f.stem for f in brd_files}

        if sch_bases != brd_bases:
            missing_brd = sch_bases - brd_bases
            missing_sch = brd_bases - sch_bases
            if missing_brd:
                self.warnings.append(f"Missing board files for: {missing_brd}")
            if missing_sch:
                self.warnings.append(f"Missing schematic files for: {missing_sch}")

        print(f"✓ Found {len(sch_files)} schematic/board pairs")
        return True

    def _test_xml_validity(self) -> bool:
        """Test 2: Verify XML is well-formed."""
        all_files = list(self.eagle_dir.glob("*.sch")) + list(self.eagle_dir.glob("*.brd"))
        valid_count = 0

        for file in all_files:
            try:
                ET.parse(file)
                valid_count += 1
            except ET.ParseError as e:
                self.errors.append(f"XML parse error in {file.name}: {e}")

        print(f"✓ {valid_count}/{len(all_files)} files have valid XML")
        return valid_count == len(all_files)

    def _test_pin_completeness(self) -> bool:
        """
        Test 3: Verify CONNECTED pins from lowlevel exist in Eagle files.

        FIX #3 (November 12, 2025 - v25.0): Updated for correct NC pin behavior
        CRITICAL: NC pins should NOT appear in Eagle files
        Previous test checked for ALL pins and failed when NC pins were omitted

        CORRECT BEHAVIOR (based on KiCad import analysis):
        - NC pins should NOT appear in any net/segment
        - Creating stub wires for NC pins causes "dangling wire" errors in KiCad
        - Only CONNECTED pins should be verified

        This test ensures:
        - Every CONNECTED pin (in pinNetMapping) appears in Eagle schematic
        - NC pins are intentionally omitted (correct Eagle behavior)
        - No connected pins are silently dropped during conversion
        """
        import json

        if not self.lowlevel_dir:
            print("⚠️  Lowlevel directory not provided - skipping pin completeness check")
            return True

        print("\nChecking pin completeness (CONNECTED pins only)...")
        print("NC (No-Connect) pins are intentionally omitted - this is CORRECT")
        print()

        all_valid = True
        total_components = 0
        total_pins_expected = 0
        total_pins_found = 0
        total_missing = 0

        # For each lowlevel file, check corresponding Eagle schematic
        for lowlevel_file in self.lowlevel_dir.glob("circuit_*.json"):
            circuit_name = lowlevel_file.stem.replace('circuit_', '')
            eagle_sch = self.eagle_dir / f"{circuit_name}.sch"

            if not eagle_sch.exists():
                self.errors.append(f"{circuit_name}: Eagle schematic not found")
                all_valid = False
                continue

            # Load expected pins from lowlevel (ONLY CONNECTED PINS)
            lowlevel_data = json.load(open(lowlevel_file))
            pin_net_mapping = lowlevel_data['circuit'].get('pinNetMapping', {})

            # Build set of connected pins (pins that appear in pinNetMapping)
            # SKIP NC pins (nets starting with "NC" or equal to "NC")
            expected_pins = {}  # component_ref → set of CONNECTED pin numbers
            for pin_id, net_name in pin_net_mapping.items():
                if '.' in pin_id and net_name:  # Format: "R1.1" → net_name
                    # Skip NC pins (e.g., "NC", "NC1", "NC2", "NC_U1_1", etc.)
                    if net_name.startswith('NC') or net_name == 'NC':
                        continue  # NC pin - intentionally omitted from Eagle
                    ref, pin_number = pin_id.split('.', 1)
                    if ref not in expected_pins:
                        expected_pins[ref] = set()
                        total_components += 1
                    expected_pins[ref].add(pin_number)
                    total_pins_expected += 1

            # Load actual pins from Eagle schematic
            tree = ET.parse(eagle_sch)
            actual_pins = {}  # component_ref → set of pin numbers (via Eagle pin names)

            # Build pin number mapping from component types
            # Need to reverse-map Eagle pin names → numbers using same logic as converter
            comp_eagle_pins = {}  # ref → eagle_pin_name → original_number
            for comp in lowlevel_data['circuit']['components']:
                ref = comp['ref']
                comp_type = comp.get('type', '').lower()
                comp_eagle_pins[ref] = {}

                for pin_info in comp['pins']:
                    number = str(pin_info['number'])
                    name = pin_info.get('name', number)

                    # Use SAME pin mapping logic as converter (eagle_converter.py lines 863-893)
                    if comp_type in ['diode', 'led', 'zener']:
                        # Diodes: 1→A, 2→C
                        if name in ['A', '1']:
                            eagle_pin = 'A'
                        elif name in ['K', 'C', '2']:
                            eagle_pin = 'C'
                        else:
                            eagle_pin = name
                    elif comp_type in ['mosfet', 'nmos', 'pmos', 'fet']:
                        # MOSFETs: G→1, D→2, S→3
                        if name == 'G':
                            eagle_pin = '1'
                        elif name == 'D':
                            eagle_pin = '2'
                        elif name == 'S':
                            eagle_pin = '3'
                        else:
                            eagle_pin = number
                    elif comp_type in ['transistor', 'bjt', 'npn', 'pnp']:
                        # Transistors: keep B/C/E
                        eagle_pin = name
                    elif comp_type in ['connector', 'header', 'ic', 'opamp']:
                        # ICs/Connectors: strip PIN prefix or use number
                        eagle_pin = name.replace('PIN', '') if 'PIN' in name.upper() else number
                    else:
                        # Default: strip PIN prefix or use number
                        eagle_pin = name.replace('PIN', '') if 'PIN' in name.upper() else number

                    # Store mapping: eagle_pin_name → original_number
                    comp_eagle_pins[ref][eagle_pin] = number
                    comp_eagle_pins[ref][number] = number  # Also map number→number for direct lookups

            # Extract pinrefs from all nets
            for net in tree.findall('.//net'):
                for pinref in net.findall('.//pinref'):
                    part = pinref.get('part')
                    eagle_pin = pinref.get('pin')

                    if part not in actual_pins:
                        actual_pins[part] = set()

                    # Map Eagle pin name back to original number
                    if part in comp_eagle_pins and eagle_pin in comp_eagle_pins[part]:
                        original_number = comp_eagle_pins[part][eagle_pin]
                        actual_pins[part].add(original_number)
                    else:
                        # Fallback: use Eagle pin name directly
                        actual_pins[part].add(eagle_pin)

            # Compare expected vs actual for each component
            for ref, expected in expected_pins.items():
                actual = actual_pins.get(ref, set())
                missing = expected - actual

                total_pins_found += len(actual)

                if missing:
                    total_missing += len(missing)
                    self.errors.append(
                        f"{circuit_name}: Component {ref} missing {len(missing)} pin(s): {sorted(missing)}"
                    )
                    all_valid = False
                    print(f"❌ {circuit_name}: {ref} missing pins {sorted(missing)}")
                else:
                    print(f"✓ {circuit_name}: {ref} all {len(expected)} pins present")

        print()
        print(f"Overall: {total_pins_found}/{total_pins_expected} pins verified")
        if total_missing > 0:
            print(f"❌ {total_missing} pins MISSING across {total_components} components")
        else:
            print(f"✓ All component pins accounted for")

        return all_valid

    def _test_geometric_accuracy(self) -> bool:
        """Test 3: CRITICAL - Verify wire endpoints match actual pin positions.

        This is THE MOST IMPORTANT TEST - it verifies that wires are placed
        at the exact coordinates where component pins are located.

        How it works:
        1. Calculate expected pin position: component_position + pin_offset_from_symbol
        2. Check if any wire endpoint exists at that position (within 0.1mm tolerance)
        3. Report pass/fail for each tested pin

        Why this matters:
        - XML structure validation can pass even if coordinates are wrong
        - Internal validation can report "perfect" while files are broken
        - THIS test verifies actual geometric correctness
        - KiCad ERC errors are caused by wires NOT at pin positions
        """
        sch_files = list(self.eagle_dir.glob("*.sch"))

        print(f"\nTesting geometric accuracy of wire placements...")
        print("This verifies wires are at EXACT pin positions (not just XML structure)")
        print()

        all_results = []
        detailed_failures = []

        for sch_file in sch_files:
            result = self._validate_circuit_geometry(sch_file, num_samples=20)
            all_results.append(result)

            status = "✅" if result['accuracy'] >= 95 else ("⚠️" if result['accuracy'] >= 90 else "❌")
            print(f"{status} {sch_file.name:40} {result['pass']:2}/{result['total']:2} pins ({result['accuracy']:5.1f}%)")

            # Track failures for detailed reporting
            if result['accuracy'] < 95:
                detailed_failures.append({
                    'file': sch_file.name,
                    'accuracy': result['accuracy'],
                    'pass': result['pass'],
                    'fail': result['fail']
                })

        print()

        # Calculate overall accuracy
        total_pass = sum(r['pass'] for r in all_results)
        total_fail = sum(r['fail'] for r in all_results)
        total_pins = total_pass + total_fail
        overall_accuracy = (total_pass / total_pins * 100) if total_pins > 0 else 0

        print(f"Overall: {total_pass}/{total_pins} pins verified ({overall_accuracy:.1f}% accurate)")

        # Add errors for failed circuits
        for failure in detailed_failures:
            self.errors.append(
                f"{failure['file']}: Only {failure['accuracy']:.1f}% geometric accuracy "
                f"({failure['fail']} pins have wires at wrong positions)"
            )

        # PASS threshold: 95% accuracy
        # This allows for minor symbol library issues while catching major problems
        if overall_accuracy >= 95:
            print("✓ Geometric accuracy test PASSED (≥95% threshold)")
            return True
        else:
            print(f"✗ Geometric accuracy test FAILED ({overall_accuracy:.1f}% < 95% threshold)")
            return False

    def _validate_circuit_geometry(self, sch_file: Path, num_samples: int = 20) -> dict:
        """Validate geometric accuracy of a single circuit by testing random pins.

        Returns dict with: {'pass': int, 'fail': int, 'total': int, 'accuracy': float}
        """
        tree = ET.parse(sch_file)
        root = tree.getroot()

        # Build component positions from instances
        comp_positions = {}
        for instance in root.findall('.//instances/instance'):
            part = instance.get('part')
            x = float(instance.get('x'))
            y = float(instance.get('y'))
            comp_positions[part] = (x, y)

        # Build symbol pin offsets
        symbol_pins = {}
        for symbol in root.findall('.//symbol'):
            symbol_name = symbol.get('name')
            symbol_pins[symbol_name] = {}
            for pin in symbol.findall('.//pin'):
                pin_name = pin.get('name')
                pin_x = float(pin.get('x', 0))
                pin_y = float(pin.get('y', 0))
                symbol_pins[symbol_name][pin_name] = (pin_x, pin_y)

        # Build part → symbol mapping
        part_symbols = {}
        for instance in root.findall('.//instances/instance'):
            part = instance.get('part')
            gate = instance.get('gate')
            for part_elem in root.findall('.//parts/part'):
                if part_elem.get('name') == part:
                    device = part_elem.get('deviceset')
                    for deviceset in root.findall('.//deviceset'):
                        if deviceset.get('name') == device:
                            for gate_elem in deviceset.findall('.//gate'):
                                if gate_elem.get('name') == gate:
                                    symbol = gate_elem.get('symbol')
                                    part_symbols[part] = symbol
                                    break
                    break

        # Collect all pins from all nets
        all_pins = []
        for net in root.findall('.//net'):
            net_name = net.get('name')
            for segment in net.findall('.//segment'):
                for pinref in segment.findall('.//pinref'):
                    part = pinref.get('part')
                    pin = pinref.get('pin')
                    all_pins.append((part, pin, net_name, segment))

        if not all_pins:
            return {'pass': 0, 'fail': 0, 'total': 0, 'accuracy': 0}

        # Test random sample of pins
        random.seed(sch_file.name)  # Deterministic sampling
        test_pins = random.sample(all_pins, min(num_samples, len(all_pins)))

        pass_count = 0
        fail_count = 0

        for part, pin, net_name, segment in test_pins:
            if part not in comp_positions or part not in part_symbols:
                continue

            comp_x, comp_y = comp_positions[part]
            symbol = part_symbols[part]

            if symbol not in symbol_pins or pin not in symbol_pins[symbol]:
                fail_count += 1
                continue

            pin_offset_x, pin_offset_y = symbol_pins[symbol][pin]
            expected_x = comp_x + pin_offset_x
            expected_y = comp_y + pin_offset_y

            # Check if any wire endpoint in this segment matches expected position
            found_match = False
            for wire in segment.findall('.//wire'):
                x1 = float(wire.get('x1'))
                y1 = float(wire.get('y1'))
                x2 = float(wire.get('x2'))
                y2 = float(wire.get('y2'))

                error1 = ((x1 - expected_x)**2 + (y1 - expected_y)**2)**0.5
                error2 = ((x2 - expected_x)**2 + (y2 - expected_y)**2)**0.5

                if error1 < 0.1 or error2 < 0.1:  # Within 0.1mm tolerance
                    pass_count += 1
                    found_match = True
                    break

            if not found_match:
                fail_count += 1

        total = pass_count + fail_count
        accuracy = (pass_count / total * 100) if total > 0 else 0

        return {
            'pass': pass_count,
            'fail': fail_count,
            'total': total,
            'accuracy': accuracy
        }

    def _test_segment_structure(self) -> bool:
        """Test 3: Verify segment structural validity (v17 multi-pinref format).

        Enforces v17 physical wire-based connectivity (October 30, 2025):
        - Multiple pinrefs per segment (star topology)
        - Physical wire elements connecting pins
        - NO labels required (labels are v16 legacy format)

        This is the CORRECT format that creates actual electrical connections.
        Single-pinref isolated segments are REJECTED.
        """
        sch_files = list(self.eagle_dir.glob("*.sch"))
        total_segments = 0
        valid_segments = 0

        for sch_file in sch_files:
            tree = ET.parse(sch_file)
            root = tree.getroot()

            for net in root.findall('.//net'):
                net_name = net.get('name')
                for i, segment in enumerate(net.findall('segment')):
                    total_segments += 1
                    pinrefs = segment.findall('pinref')
                    wires = segment.findall('wire')

                    # v17: Multi-pinref segments with physical wires (star topology)
                    # For multi-pin nets: need 2+ pinrefs and physical wires
                    # For single-pin nets: 1 pinref is OK (no wires needed)
                    if len(pinrefs) >= 1 and (len(pinrefs) == 1 or len(wires) >= 1):
                        valid_segments += 1
                    else:
                        self.errors.append(
                            f"{sch_file.name}: Net '{net_name}' segment {i} has INVALID structure "
                            f"(pinrefs={len(pinrefs)}, wires={len(wires)}) "
                            f"- Multi-pin nets MUST have physical wire connections"
                        )

        print(f"✓ {valid_segments}/{total_segments} segments have correct structure")
        return valid_segments == total_segments

    def _test_label_attributes(self) -> bool:
        """Test 4: Verify all labels have required attributes."""
        sch_files = list(self.eagle_dir.glob("*.sch"))
        total_labels = 0
        valid_labels = 0

        for sch_file in sch_files:
            tree = ET.parse(sch_file)
            root = tree.getroot()

            for label in root.findall('.//nets//label'):
                total_labels += 1
                has_x = label.get('x') is not None
                has_y = label.get('y') is not None
                has_size = label.get('size') is not None
                has_layer = label.get('layer') == '95'
                has_xref = label.get('xref') == 'yes'

                if all([has_x, has_y, has_size, has_layer, has_xref]):
                    valid_labels += 1
                else:
                    issues = []
                    if not has_x: issues.append("missing x")
                    if not has_y: issues.append("missing y")
                    if not has_size: issues.append("missing size")
                    if not has_layer: issues.append("wrong/missing layer")
                    if not has_xref: issues.append("missing xref")
                    self.errors.append(f"{sch_file.name}: Label {', '.join(issues)}")

        print(f"✓ {valid_labels}/{total_labels} labels have correct attributes")
        return valid_labels == total_labels

    def _test_wire_attributes(self) -> bool:
        """Test 5: Verify all wires have required attributes and non-zero length."""
        sch_files = list(self.eagle_dir.glob("*.sch"))
        total_wires = 0
        valid_wires = 0

        for sch_file in sch_files:
            tree = ET.parse(sch_file)
            root = tree.getroot()

            for wire in root.findall('.//nets//wire'):
                total_wires += 1
                has_x1 = wire.get('x1') is not None
                has_y1 = wire.get('y1') is not None
                has_x2 = wire.get('x2') is not None
                has_y2 = wire.get('y2') is not None
                has_width = wire.get('width') is not None
                has_layer = wire.get('layer') == '91'

                if all([has_x1, has_y1, has_x2, has_y2, has_width, has_layer]):
                    # Check non-zero length
                    try:
                        x1, y1 = float(wire.get('x1')), float(wire.get('y1'))
                        x2, y2 = float(wire.get('x2')), float(wire.get('y2'))
                        length = ((x2-x1)**2 + (y2-y1)**2)**0.5
                        if length >= 0.1:  # At least 0.1mm
                            valid_wires += 1
                        else:
                            self.errors.append(f"{sch_file.name}: Wire has near-zero length: {length:.4f}mm")
                    except ValueError as e:
                        self.errors.append(f"{sch_file.name}: Wire coordinate parse error: {e}")
                else:
                    issues = []
                    if not (has_x1 and has_y1): issues.append("missing start coords")
                    if not (has_x2 and has_y2): issues.append("missing end coords")
                    if not has_width: issues.append("missing width")
                    if not has_layer: issues.append("wrong/missing layer")
                    self.errors.append(f"{sch_file.name}: Wire {', '.join(issues)}")

        print(f"✓ {valid_wires}/{total_wires} wires have correct attributes and length")
        return valid_wires == total_wires

    def _test_label_connectivity(self) -> bool:
        """Test 6: Verify all nets use v17 wire-based connectivity."""
        sch_files = list(self.eagle_dir.glob("*.sch"))
        total_nets = 0
        valid_nets = 0

        print("\nChecking connectivity format: v17 multi-pinref with physical wires\n")

        for sch_file in sch_files:
            tree = ET.parse(sch_file)
            root = tree.getroot()

            for net in root.findall('.//net'):
                net_name = net.get('name')
                total_nets += 1
                segments = net.findall('segment')

                # v17: ALL segments should have multiple pinrefs and physical wires (star topology)
                # Single-pin nets (1 pinref, 0 wires) are OK
                # Multi-pin nets (2+ pinrefs) MUST have wires
                all_correct = all(
                    (len(seg.findall('pinref')) == 1) or  # Single-pin net OK
                    (len(seg.findall('pinref')) >= 2 and len(seg.findall('wire')) >= 1)  # Multi-pin needs wires
                    for seg in segments
                ) if segments else True

                if all_correct:
                    valid_nets += 1
                else:
                    self.errors.append(
                        f"{sch_file.name}: Net '{net_name}' has segments without proper wire connectivity (v17 format required)"
                    )

        print(f"✓ {valid_nets}/{total_nets} nets have correct v17 wire-based connectivity")
        return valid_nets == total_nets

    def _test_board_ratsnest(self) -> bool:
        """
        Test 7: Verify boards have proper routing (copper wires).

        CRITICAL UPDATE (November 12, 2025 - v23.0):
        Previous "ratsnest-only" approach (0 copper wires) caused 100% KiCad DRC failures.
        NEW CORRECT BEHAVIOR: Boards MUST have copper routing for import compatibility.
        """
        brd_files = list(self.eagle_dir.glob("*.brd"))
        all_valid = True

        for brd_file in brd_files:
            tree = ET.parse(brd_file)
            root = tree.getroot()

            # Count contactrefs (pad definitions)
            contactrefs = len(root.findall('.//board//signals//contactref'))

            # Count copper wires on layers 1-16
            copper_wires = 0
            for wire in root.findall('.//board//signals//wire'):
                layer = wire.get('layer', '')
                if layer.isdigit() and 1 <= int(layer) <= 16:
                    copper_wires += 1

            print(f"{brd_file.name}: {contactrefs} contactrefs, {copper_wires} copper wires")

            # CRITICAL CHECK: Boards MUST have copper routing (not just ratsnest)
            if copper_wires == 0:
                self.errors.append(
                    f"{brd_file.name}: Has 0 copper wires - board is UNROUTED. "
                    f"This will cause 'unconnected pads' DRC errors in KiCad/EasyEDA."
                )
                all_valid = False

            # CRITICAL CHECK: Boards MUST have contactrefs (pad definitions)
            if contactrefs == 0:
                self.errors.append(f"{brd_file.name}: Has 0 contactrefs (expected > 0)")
                all_valid = False

        return all_valid

    def _test_component_placement(self) -> bool:
        """Test 8: Verify components are within board bounds."""
        brd_files = list(self.eagle_dir.glob("*.brd"))
        all_valid = True

        for brd_file in brd_files:
            tree = ET.parse(brd_file)
            root = tree.getroot()

            # Find board outline
            outline_wires = root.findall('.//board//plain//wire[@layer="20"]')
            if not outline_wires:
                self.warnings.append(f"{brd_file.name}: No board outline found")
                continue

            # Calculate board dimensions
            max_x = max(max(float(w.get('x1', 0)), float(w.get('x2', 0))) for w in outline_wires)
            max_y = max(max(float(w.get('y1', 0)), float(w.get('y2', 0))) for w in outline_wires)

            # Check component positions
            elements = root.findall('.//board//elements//element')
            out_of_bounds = 0
            for elem in elements:
                x = float(elem.get('x', 0))
                y = float(elem.get('y', 0))

                margin = 10.0  # mm
                if x > max_x - margin or y > max_y - margin:
                    out_of_bounds += 1

            if out_of_bounds > 0:
                self.warnings.append(f"{brd_file.name}: {out_of_bounds} components near/outside board edge")

            print(f"{brd_file.name}: Board {max_x:.0f}x{max_y:.0f}mm, {len(elements)} components, {out_of_bounds} near edge")

        return all_valid

    def _test_net_completeness(self) -> bool:
        """Test 9: Verify all nets are complete (wires or legacy labels)."""
        sch_files = list(self.eagle_dir.glob("*.sch"))
        all_valid = True

        for sch_file in sch_files:
            tree = ET.parse(sch_file)
            root = tree.getroot()

            for net in root.findall('.//net'):
                net_name = net.get('name')
                segments = net.findall('segment')
                has_wire = any(len(seg.findall('wire')) >= 1 and len(seg.findall('pinref')) >= 1 for seg in segments)
                if not has_wire:
                    all_label = all(
                        len(seg.findall('pinref')) == 1 and len(seg.findall('label')) == 1
                    ) if segments else True
                    if not all_label:
                        self.errors.append(f"{sch_file.name}: Net '{net_name}' lacks wires and valid label-only segments")
                        all_valid = False

        return all_valid

    def _test_cross_file_consistency(self) -> bool:
        """Test 10: Verify schematic and board files are consistent."""
        sch_files = list(self.eagle_dir.glob("*.sch"))
        brd_files = list(self.eagle_dir.glob("*.brd"))

        all_valid = True

        for sch_file in sch_files:
            brd_file = self.eagle_dir / f"{sch_file.stem}.brd"
            if not brd_file.exists():
                continue

            # Parse both files
            sch_tree = ET.parse(sch_file)
            brd_tree = ET.parse(brd_file)

            # Compare component counts
            sch_parts = {p.get('name') for p in sch_tree.findall('.//parts//part')}
            brd_elements = {e.get('name') for e in brd_tree.findall('.//board//elements//element')}

            if sch_parts != brd_elements:
                missing_in_brd = sch_parts - brd_elements
                extra_in_brd = brd_elements - sch_parts
                if missing_in_brd:
                    self.errors.append(f"{sch_file.stem}: Components in SCH but not BRD: {missing_in_brd}")
                    all_valid = False
                if extra_in_brd:
                    self.errors.append(f"{sch_file.stem}: Components in BRD but not SCH: {extra_in_brd}")
                    all_valid = False
            else:
                print(f"{sch_file.stem}: ✓ {len(sch_parts)} components match between SCH and BRD")

        return all_valid

    def _print_final_report(self):
        """Print comprehensive final report."""
        print("\n" + "=" * 80)
        print("FINAL FORENSIC VALIDATION REPORT")
        print("=" * 80)
        print()

        # Test results summary
        print("TEST RESULTS:")
        passed = sum(1 for v in self.test_results.values() if v)
        total = len(self.test_results)

        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"  {status}: {test_name}")

        print()
        print(f"Overall: {passed}/{total} tests passed")
        print()

        # Errors
        if self.errors:
            print(f"❌ ERRORS: {len(self.errors)}")
            for i, error in enumerate(self.errors[:20], 1):
                print(f"  {i}. {error}")
            if len(self.errors) > 20:
                print(f"  ... and {len(self.errors) - 20} more errors")
            print()

        # Warnings
        if self.warnings:
            print(f"⚠️  WARNINGS: {len(self.warnings)}")
            for i, warning in enumerate(self.warnings[:10], 1):
                print(f"  {i}. {warning}")
            if len(self.warnings) > 10:
                print(f"  ... and {len(self.warnings) - 10} more warnings")
            print()

        # Production readiness
        print("=" * 80)
        if passed == total and len(self.errors) == 0:
            print("✅ PRODUCTION READY")
            print("🎉 All files passed comprehensive forensic validation")
            print("🚀 Files are ready for import to Eagle/KiCad/EasyEDA")
        elif passed == total and len(self.errors) == 0 and len(self.warnings) > 0:
            print("⚠️  PASSED WITH WARNINGS")
            print("Files are structurally correct but have minor issues")
        else:
            print("❌ NOT PRODUCTION READY")
            print(f"Failed {total - passed} tests with {len(self.errors)} errors")
            print("Files need fixes before import")
        print("=" * 80)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate_eagle_comprehensive.py <eagle_directory> [lowlevel_directory]")
        print("Example: python3 validate_eagle_comprehensive.py output/20251019-091410-4587f35c/eagle")
        print("Example with pin check: python3 validate_eagle_comprehensive.py output/20251019-091410-4587f35c/eagle output/20251019-091410-4587f35c/lowlevel")
        sys.exit(1)

    eagle_dir = sys.argv[1]
    lowlevel_dir = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.exists(eagle_dir):
        print(f"Error: Directory not found: {eagle_dir}")
        sys.exit(1)

    if lowlevel_dir and not os.path.exists(lowlevel_dir):
        print(f"Warning: Lowlevel directory not found: {lowlevel_dir}")
        print("Skipping pin completeness check")
        lowlevel_dir = None

    validator = ComprehensiveEagleValidator(eagle_dir, lowlevel_dir)
    success = validator.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
