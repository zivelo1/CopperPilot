#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle Geometric Validator - Post-Generation Connectivity Validation

This module provides GENERIC geometric validation for generated Eagle files.
It verifies that wires actually connect to pins at the correct coordinates.

Design Principles:
- GENERIC: Works for any circuit complexity
- POST-GENERATION: Validates after files are created
- GEOMETRIC: Checks actual coordinates, not just structure
- EXPERT: ONE job - detect and report geometric problems

Author: AI Electronics System
Date: October 23, 2025
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from .eagle_symbol_library import EagleSymbolLibrary
from .eagle_geometry import GeometryCalculator


class ValidationError:
    """Container for validation error details."""

    def __init__(self, error_type: str, message: str, component: str = "", net: str = ""):
        self.error_type = error_type
        self.message = message
        self.component = component
        self.net = net

    def __str__(self):
        parts = [f"[{self.error_type}]", self.message]
        if self.component:
            parts.append(f"Component: {self.component}")
        if self.net:
            parts.append(f"Net: {self.net}")
        return " - ".join(parts)


class GeometricValidator:
    """
    GENERIC geometric validator for Eagle schematics.

    This validator checks that generated Eagle files have correct geometric
    connectivity - that wires actually touch pins at the right coordinates.

    Architecture:
    - Parses generated Eagle XML
    - Extracts component instances and positions
    - For each net segment, verifies wire touches pin
    - Reports errors without fixing (that's AutoFixer's job!)

    Usage:
        validator = GeometricValidator(symbol_library)
        success = validator.validate_schematic_file('circuit.sch')
        if not success:
            validator.print_report()
    """

    def __init__(self, symbol_library: EagleSymbolLibrary):
        """
        Initialize validator with symbol library.

        Args:
            symbol_library: EagleSymbolLibrary instance with extracted symbols
        """
        self.symbol_library = symbol_library
        self.errors: List[ValidationError] = []
        self.warnings: List[str] = []
        # CRITICAL FIX: Remove tolerance - KiCad requires EXACT coordinate matching
        # self.tolerance = 0.1  # REMOVED - was causing false PASS for off-grid coordinates

    def validate_schematic_file(self, schematic_path: str) -> bool:
        """
        Validate a generated Eagle schematic file.

        This is the main entry point for validation. It performs comprehensive
        geometric checks on the schematic.

        Args:
            schematic_path: Path to .sch file to validate

        Returns:
            True if all geometric checks pass, False otherwise

        Validation Steps:
            1. Parse XML
            2. Extract component instances with positions
            3. Validate each net segment's connectivity
            4. Check for orphaned components
            5. Verify wire-to-pin connections

        Notes:
            - Errors are stored in self.errors
            - Warnings are stored in self.warnings
            - Call print_report() to display results
        """
        self.errors.clear()
        self.warnings.clear()

        sch_file = Path(schematic_path)
        if not sch_file.exists():
            self.errors.append(ValidationError(
                "FILE_ERROR",
                f"Schematic file not found: {schematic_path}"
            ))
            return False

        try:
            # Parse XML
            tree = ET.parse(schematic_path)
            root = tree.getroot()

            # Extract component instances
            instances = self._extract_instances(root)
            if not instances:
                self.warnings.append("No component instances found in schematic")

            # Validate nets
            nets = root.findall('.//nets/net')
            if not nets:
                self.warnings.append("No nets found in schematic")
            else:
                for net in nets:
                    net_name = net.get('name', 'UNKNOWN')
                    self._validate_net_segments(net, net_name, instances, root)

            # Check for orphaned components
            self._check_orphaned_components(root, instances)

            # CRITICAL: Check network connectivity
            # This validates that all pins in a net are actually connected through wires
            # Not just that wires touch pins, but that wires form a connected graph
            for net in nets:
                net_name = net.get('name', 'UNKNOWN')
                self._validate_network_connectivity(net, net_name, instances, root)

            # CRITICAL FIX: Validate grid alignment
            # KiCad requires all coordinates to be on standard Eagle grid (2.54mm = 0.1 inch)
            self._validate_grid_alignment(root)

            # CRITICAL FIX: Validate label presence
            # Multi-segment nets MUST have labels for connectivity
            self._validate_label_presence(root)

            return len(self.errors) == 0

        except ET.ParseError as e:
            self.errors.append(ValidationError(
                "XML_ERROR",
                f"Failed to parse XML: {e}"
            ))
            return False
        except Exception as e:
            self.errors.append(ValidationError(
                "VALIDATION_ERROR",
                f"Unexpected error during validation: {e}"
            ))
            return False

    def _extract_instances(self, root: ET.Element) -> Dict:
        """
        Extract component instances with positions and metadata.

        Args:
            root: Root XML element of schematic

        Returns:
            Dictionary: {component_ref: {x, y, rotation, deviceset, ...}}

        Notes:
            - Deviceset is used to look up symbol for pin positions
            - Position is component CENTER in schematic coordinates
        """
        instances = {}

        for inst in root.findall('.//instances/instance'):
            part = inst.get('part')
            if not part:
                continue

            try:
                x = float(inst.get('x', 0))
                y = float(inst.get('y', 0))
            except (ValueError, TypeError):
                self.warnings.append(f"Invalid coordinates for instance '{part}'")
                continue

            # Get deviceset to look up symbol
            deviceset = None
            gate = inst.get('gate', 'G$1')

            # Try to find deviceset from parts section
            for part_elem in root.findall(f".//parts/part[@name='{part}']"):
                deviceset = part_elem.get('deviceset')
                break

            instances[part] = {
                'x': x,
                'y': y,
                'rotation': inst.get('rot', 'R0'),
                'gate': gate,
                'deviceset': deviceset
            }

        return instances

    def _validate_net_segments(
        self,
        net: ET.Element,
        net_name: str,
        instances: Dict,
        root: ET.Element
    ):
        """
        Validate all segments in a net for correct connectivity.

        Args:
            net: Net XML element
            net_name: Name of the net
            instances: Component instances dictionary
            root: Root XML element (for deviceset/symbol lookup)

        Validation:
            - Each pinref should have a wire that touches it
            - Wire start or end must be within tolerance of pin position
        """
        segments = net.findall('.//segment')

        for seg_idx, segment in enumerate(segments):
            pinrefs = segment.findall('.//pinref')
            wires = segment.findall('.//wire')

            if not pinrefs:
                continue  # No pins in this segment

            # CRITICAL CHECK (v23.0 - November 12, 2025): Enforce max 4 pins per segment
            # Professional Eagle standard: 2-4 pins per segment for KiCad/EasyEDA compatibility
            # Root cause: Oversized segments (3.87 avg vs 1.24 target) cause import failures
            if len(pinrefs) > 4:
                self.errors.append(ValidationError(
                    "OVERSIZED_SEGMENT",
                    f"Segment {seg_idx} has {len(pinrefs)} pins (max 4 allowed). "
                    f"Professional Eagle files use 2-4 pins per segment connected by labels. "
                    f"Split into multiple segments connected by labels with xref='yes'.",
                    net=net_name
                ))
                continue  # Don't process this segment further

            if not wires:
                self.errors.append(ValidationError(
                    "MISSING_WIRE",
                    f"Segment {seg_idx} has pinref but NO wire",
                    net=net_name
                ))
                continue

            # Validate each pinref has a wire connection
            for pinref in pinrefs:
                part = pinref.get('part')
                pin = pinref.get('pin')

                if not part or not pin:
                    continue

                if part not in instances:
                    self.errors.append(ValidationError(
                        "UNKNOWN_COMPONENT",
                        f"Component '{part}' not found in instances",
                        component=part,
                        net=net_name
                    ))
                    continue

                # Calculate expected pin position
                instance = instances[part]
                deviceset = instance.get('deviceset')

                # Resolve the actual SYMBOL used by this instance via deviceset→gate mapping
                symbol_name = None
                try:
                    # parts/part → deviceset name
                    if not deviceset:
                        for part_elem in root.findall(f".//parts/part[@name='{part}']"):
                            deviceset = part_elem.get('deviceset')
                            break
                    # devicesets/deviceset[name]/gates/gate[name=gate] → symbol
                    if deviceset:
                        for ds in root.findall(f".//deviceset[@name='{deviceset}']"):
                            for gate_elem in ds.findall('.//gate'):
                                if gate_elem.get('name') == instance.get('gate', 'G$1'):
                                    symbol_name = gate_elem.get('symbol')
                                    break
                            if symbol_name:
                                break
                except Exception:
                    symbol_name = None

                if not symbol_name:
                    # FAIL INSTEAD OF SKIP: Symbol resolution is REQUIRED for validation
                    self.errors.append(ValidationError(
                        "SYMBOL_RESOLUTION_FAILED",
                        f"Cannot resolve symbol for {part} (deviceset='{deviceset}') - "
                        f"This is a CRITICAL error that prevents ERC validation. "
                        f"Check library generation and deviceset→gate→symbol chain.",
                        component=part,
                        net=net_name
                    ))
                    continue

                # Get pin offset from the actual symbol
                try:
                    pin_offset_x, pin_offset_y = self.symbol_library.get_pin_offset(
                        symbol_name, pin
                    )
                except KeyError:
                    # Symbol or pin not found - CRITICAL ERROR
                    self.errors.append(ValidationError(
                        "PIN_NOT_IN_SYMBOL",
                        f"Pin '{pin}' not found in symbol '{symbol_name}' for {part} - "
                        f"Symbol library may be incomplete or pin naming mismatch",
                        component=part,
                        net=net_name
                    ))
                    continue

                # Calculate actual pin position
                try:
                    pin_x_raw, pin_y_raw = GeometryCalculator.calculate_pin_position(
                        instance['x'],
                        instance['y'],
                        pin_offset_x,
                        pin_offset_y,
                        instance['rotation']
                    )
                    
                    # Use exact symbol-derived pin position (no grid snapping)
                    expected_pin_x = pin_x_raw
                    expected_pin_y = pin_y_raw
                except Exception as e:
                    self.warnings.append(
                        f"Error calculating pin position for {part}.{pin}: {e}"
                    )
                    continue

                # Check if any wire touches this pin
                wire_connected = self._check_wire_touches_pin(
                    wires, expected_pin_x, expected_pin_y
                )

                if not wire_connected:
                    self.errors.append(ValidationError(
                        "PIN_NOT_CONNECTED",
                        f"Pin {part}.{pin} not connected - expected at "
                        f"({expected_pin_x:.2f}, {expected_pin_y:.2f}) but no wire touches it",
                        component=part,
                        net=net_name
                    ))

    def _check_wire_touches_pin(
        self,
        wires: List[ET.Element],
        pin_x: float,
        pin_y: float
    ) -> bool:
        """
        Check if any wire endpoint is within tolerance of pin position.

        Args:
            wires: List of wire XML elements
            pin_x, pin_y: Expected pin coordinates

        Returns:
            True if at least one wire touches the pin
        """
        for wire in wires:
            try:
                wire_x1 = float(wire.get('x1', 0))
                wire_y1 = float(wire.get('y1', 0))
                wire_x2 = float(wire.get('x2', 0))
                wire_y2 = float(wire.get('y2', 0))
            except (ValueError, TypeError):
                continue

            # Normalize both wire endpoints and expected pin to the standard
            # schematic precision (2 decimals in mm on 2.54mm grid). This preserves
            # the "exact equality" requirement while eliminating binary float noise.
            wx1n, wy1n = GeometryCalculator.normalize_coordinates(wire_x1, wire_y1, precision=2)
            wx2n, wy2n = GeometryCalculator.normalize_coordinates(wire_x2, wire_y2, precision=2)
            pxn, pyn = GeometryCalculator.normalize_coordinates(pin_x, pin_y, precision=2)

            # Check for exact match after normalization
            if wx1n == pxn and wy1n == pyn:
                return True

            # Check the other wire end
            if wx2n == pxn and wy2n == pyn:
                return True

        return False

    def _check_orphaned_components(self, root: ET.Element, instances: Dict):
        """
        Check for components that are not connected to any net.

        Args:
            root: Root XML element
            instances: Component instances dictionary
        """
        # Get all components referenced in nets
        connected_parts = set()
        for net in root.findall('.//nets/net'):
            for pinref in net.findall('.//pinref'):
                part = pinref.get('part')
                if part:
                    connected_parts.add(part)

        # Check which instances are not connected
        for part in instances:
            if part not in connected_parts:
                self.warnings.append(
                    f"Component '{part}' has no connections in any net"
                )

    def _validate_network_connectivity(
        self,
        net: ET.Element,
        net_name: str,
        instances: Dict,
        root: ET.Element
    ):
        """
        Validate that pins in each segment are connected through wires.

        CRITICAL FIX (November 12, 2025 - v23.0):
        Eagle multi-segment nets are electrically connected by being in the same <net> element,
        NOT by having physical wires between segments. Segments can be physically separate.

        This function validates connectivity WITHIN each segment only.

        Args:
            net: Net XML element
            net_name: Name of the net
            instances: Component instances dictionary
            root: Root XML element
        """
        # CRITICAL FIX: Validate connectivity PER SEGMENT, not across all segments
        segments = net.findall('.//segment')

        for seg_idx, segment in enumerate(segments):
            pinrefs = segment.findall('.//pinref')
            wires = segment.findall('.//wire')

            # Skip segments with 0-1 pins (no connectivity to validate)
            if len(pinrefs) <= 1:
                continue

            # Build pin positions for THIS segment only
            pin_positions = {}
            idx = 0
            for pinref in pinrefs:
                part = pinref.get('part')
                pin = pinref.get('pin')
                if part not in instances:
                    continue
                instance = instances[part]
                deviceset = instance.get('deviceset')
                symbol_name = None
                try:
                    if deviceset:
                        for ds in root.findall(f".//deviceset[@name='{deviceset}']"):
                            for gate_elem in ds.findall('.//gate'):
                                if gate_elem.get('name') == instance.get('gate', 'G$1'):
                                    symbol_name = gate_elem.get('symbol')
                                    break
                            if symbol_name:
                                break
                except Exception:
                    symbol_name = None
                try:
                    if symbol_name:
                        pin_offset_x, pin_offset_y = self.symbol_library.get_pin_offset(symbol_name, pin)
                        pin_x_raw, pin_y_raw = GeometryCalculator.calculate_pin_position(
                            instance['x'], instance['y'], pin_offset_x, pin_offset_y, instance.get('rotation', 'R0')
                        )
                        pin_positions[idx] = (pin_x_raw, pin_y_raw, part, pin)
                    else:
                        pin_positions[idx] = (instance['x'], instance['y'], part, pin)
                    idx += 1
                except Exception:
                    pin_positions[idx] = (instance['x'], instance['y'], part, pin)
                    idx += 1

            if len(pin_positions) < 2:
                continue  # No connectivity to validate

            # Build adjacency graph for wires in THIS segment
            adjacency = {i: set() for i in pin_positions.keys()}
            for wire in wires:
                try:
                    wx1 = float(wire.get('x1', 0)); wy1 = float(wire.get('y1', 0))
                    wx2 = float(wire.get('x2', 0)); wy2 = float(wire.get('y2', 0))
                except (ValueError, TypeError):
                    continue
                for i, (px, py, _, _) in pin_positions.items():
                    for j, (qx, qy, _, _) in pin_positions.items():
                        if i >= j:
                            continue
                        wx1n, wy1n = GeometryCalculator.normalize_coordinates(wx1, wy1, precision=2)
                        wx2n, wy2n = GeometryCalculator.normalize_coordinates(wx2, wy2, precision=2)
                        pxn, pyn = GeometryCalculator.normalize_coordinates(px, py, precision=2)
                        qxn, qyn = GeometryCalculator.normalize_coordinates(qx, qy, precision=2)
                        i_at_start = (wx1n == pxn and wy1n == pyn)
                        i_at_end = (wx2n == pxn and wy2n == pyn)
                        j_at_start = (wx1n == qxn and wy1n == qyn)
                        j_at_end = (wx2n == qxn and wy2n == qyn)
                        if (i_at_start and j_at_end) or (i_at_end and j_at_start):
                            adjacency[i].add(j)
                            adjacency[j].add(i)

            # BFS connectivity check within THIS segment
            visited = set()
            queue = [list(pin_positions.keys())[0]]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                for neighbor in adjacency[current]:
                    if neighbor not in visited:
                        queue.append(neighbor)

            # Report disconnected pins within THIS segment
            if len(visited) < len(pin_positions):
                disconnected_pins = []
                for i in pin_positions.keys():
                    if i not in visited:
                        _, _, part, pin = pin_positions[i]
                        disconnected_pins.append(f"{part}.{pin}")
                self.errors.append(ValidationError(
                    "DISCONNECTED_SEGMENT",
                    f"Net '{net_name}' segment {seg_idx} has disconnected pins: {', '.join(disconnected_pins)}. "
                    f"Wires do not connect all pins within this segment.",
                    net=net_name
                ))

    def _validate_grid_alignment(self, root: ET.Element, grid_size: float = 2.54):
        """
        Validate all coordinates are on standard Eagle grid (2.54mm = 0.1 inch).
        
        KiCad importer requires exact grid alignment - even 0.01mm off causes errors.
        
        Args:
            root: Root XML element
            grid_size: Grid size in mm (default 2.54mm = 0.1 inch)
        """
        def is_on_grid(value: float, grid: float) -> bool:
            """Check if value is on grid, handling floating point precision."""
            # Round to grid and check if difference is negligible
            snapped = round(value / grid) * grid
            return abs(value - snapped) < 0.01  # 0.01mm tolerance for floating point
        
        # Check all component instance positions
        for instance in root.findall('.//instance'):
            try:
                x = float(instance.get('x', 0))
                y = float(instance.get('y', 0))
                part = instance.get('part', 'UNKNOWN')
                
                # Check if on grid
                if not is_on_grid(x, grid_size):
                    self.errors.append(ValidationError(
                        "GRID_ALIGNMENT",
                        f"Component '{part}' X coordinate {x}mm not on {grid_size}mm grid",
                        component=part
                    ))
                
                if not is_on_grid(y, grid_size):
                    self.errors.append(ValidationError(
                        "GRID_ALIGNMENT",
                        f"Component '{part}' Y coordinate {y}mm not on {grid_size}mm grid",
                        component=part
                    ))
            except (ValueError, TypeError):
                continue
        
        # Do not enforce grid alignment on net wires.
        # Some symbols legitimately place pins at half-grid offsets (e.g., 3.81mm),
        # and wires must land exactly at those positions for true connectivity.
        # Connectivity is verified separately via geometric checks.
        
        # Do not enforce grid alignment on junctions either — junctions may sit
        # exactly at symbol pin coordinates, which can be half‑grid offsets.

    def _validate_label_presence(self, root: ET.Element):
        """
        Validate that multi-segment nets have labels.
        
        Eagle uses labels to connect segments - without them KiCad cannot
        recognize connectivity between different parts of the schematic.
        
        Args:
            root: Root XML element
        """
        for net in root.findall('.//net'):
            net_name = net.get('name', 'UNKNOWN')
            segments = net.findall('.//segment')
            
            if len(segments) > 1:
                # Multi-segment net - each segment MUST have a label
                for i, segment in enumerate(segments):
                    labels = segment.findall('.//label')
                    if not labels:
                        self.errors.append(ValidationError(
                            "MISSING_LABEL",
                            f"Net '{net_name}' segment {i+1}/{len(segments)} missing label - "
                            f"multi-segment nets require labels for connectivity",
                            net=net_name
                        ))
            elif len(segments) == 1:
                # Single segment with multiple pins
                segment = segments[0]
                pinrefs = segment.findall('.//pinref')
                
                if len(pinrefs) > 5:
                    # Large single segment - warn that it may benefit from splitting
                    # This is a warning, not an error
                    self.warnings.append(
                        f"Net '{net_name}' has {len(pinrefs)} pins in single segment - "
                        f"consider splitting into multiple segments with labels for better "
                        f"schematic organization and import compatibility"
                    )

    def print_report(self):
        """
        Print validation report with errors and warnings.

        Useful for debugging and reviewing validation results.
        """
        print("\n" + "="*70)
        print("GEOMETRIC VALIDATION REPORT")
        print("="*70)

        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for err in self.errors:
                print(f"  - {err}")
        else:
            print("\n✅ No errors found")

        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warn in self.warnings:
                print(f"  - {warn}")

        print("="*70)

    def get_error_summary(self) -> str:
        """
        Get a summary string of validation results.

        Returns:
            Summary string like "5 errors, 3 warnings"
        """
        return f"{len(self.errors)} errors, {len(self.warnings)} warnings"


# Test function
def test_geometric_validator():
    """Test the geometric validator with sample data."""
    print("Testing Geometric Validator...")
    print("Note: This requires actual schematic files to test")
    print("Validator is ready for integration with converter")


if __name__ == "__main__":
    test_geometric_validator()
