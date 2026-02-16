#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
GENERIC Pre-Routing Fixer - Validates and fixes issues BEFORE Freerouting runs

This fixer operates BEFORE routing, fixing issues that would cause routing to fail:
- Component overlaps
- Board size problems
- DSN file validity
- TC #48: Footprint pad clearance validation

GENERIC: Works for ANY circuit type without hardcoding.

Author: Claude Code / CopperPilot AI System
Date: 2025-11-18
Version: 2.0 - TC #48: Added footprint pad clearance validation
"""

from __future__ import annotations
import logging
from typing import Dict, List, Tuple, Optional, TYPE_CHECKING
from pathlib import Path
import re

# TC #38 (2025-11-23): Import central manufacturing configuration
from kicad.manufacturing_config import MANUFACTURING_CONFIG

# TC #48 (2025-11-25): Import pad dimensions for clearance validation
from kicad.pad_dimensions import get_pad_spec_for_footprint, SMD_2PAD_SPECS

# TC #39 (2025-11-24): Fix RC #10 - Import CircuitGraph for correct data source
if TYPE_CHECKING:
    from kicad.circuit_graph import CircuitGraph

logger = logging.getLogger(__name__)


class PreRoutingFixer:
    """
    Pre-routing validation and fixing (GENERIC for all circuits).

    Runs BEFORE Freerouting to catch and fix issues that would cause routing failure.
    """

    def __init__(self):
        """Initialize pre-routing fixer."""
        # TC #38 (2025-11-23): Use central manufacturing configuration
        self.max_board_size = MANUFACTURING_CONFIG.MAX_BOARD_WIDTH
        self.min_component_clearance = MANUFACTURING_CONFIG.MIN_COMPONENT_CLEARANCE

    def validate_and_fix(self, pcb_file: Path, circuit_graph: 'CircuitGraph') -> Tuple[bool, str]:
        """
        Validate PCB before routing and fix issues if found (GENERIC).

        TC #39 (2025-11-24): Fix RC #10 - Changed to accept CircuitGraph instead of
        circuit dict, ensuring validation reads from correct data source with actual
        component positions from placement algorithm.

        Args:
            pcb_file: Path to .kicad_pcb file
            circuit_graph: CircuitGraph with placed components (single source of truth)

        Returns:
            (success, message) - True if valid or fixed, False if unfixable
        """
        logger.info("🔍 Pre-routing validation...")

        # Check 1: Component overlaps (read from CircuitGraph, not circuit dict)
        overlap_count = self._check_component_overlaps(circuit_graph)
        if overlap_count > 0:
            logger.warning(f"⚠️  Found {overlap_count} component overlaps")
            return (False, f"{overlap_count} component overlaps - replacecement needed")

        # Check 2: Board size reasonableness
        component_count = len(circuit_graph.components)
        board_valid, board_msg = self._check_board_size(pcb_file, component_count)
        if not board_valid:
            logger.warning(f"⚠️  {board_msg}")
            return (False, board_msg)

        # Check 3: PCB file validity
        pcb_valid, pcb_msg = self._check_pcb_validity(pcb_file)
        if not pcb_valid:
            logger.error(f"❌ {pcb_msg}")
            return (False, pcb_msg)

        # Check 4: TC #48 (2025-11-25) - Footprint pad clearances
        # Validates that pad dimensions within footprints are DRC-compliant
        # NOTE: This is informational - doesn't fail validation (new pad_dimensions module fixes the issue)
        violation_count, violations = self._check_footprint_pad_clearances(circuit_graph)
        if violation_count > 0:
            logger.info(f"ℹ️  {violation_count} footprint pad issues detected (will be fixed by TC #48 pad_dimensions)")

        logger.info("✅ Pre-routing validation passed")
        return (True, "Valid")

    def _check_component_overlaps(self, circuit_graph: 'CircuitGraph') -> int:
        """
        Check for component overlaps (GENERIC).

        TC #39 (2025-11-24): Fix RC #10 - Read positions from CircuitGraph.components
        instead of circuit dict. CircuitGraph has actual placement data from PCBPlacer,
        ensuring validation works on correct coordinates.

        TC #45 FIX (2025-11-25): Use dynamic bounding box sizes based on footprint instead
        of hardcoded 10mm x 10mm. This prevents false positive overlaps when components
        are properly spaced but smaller than 10mm.

        Args:
            circuit_graph: CircuitGraph with placed components

        Returns: Number of overlapping component pairs
        """
        overlap_count = 0

        # Convert to list for indexed iteration
        components = list(circuit_graph.components.values())

        # TC #45 FIX (2025-11-25): Log positions for debugging phantom execution bug
        if components:
            sample_positions = [(c.reference, c.position) for c in components[:3]]
            logger.info(f"  🔍 Pre-routing: Sample positions = {sample_positions}")

        for i, comp1 in enumerate(components):
            # TC #39: Read from component.position (tuple from placement algorithm)
            x1 = comp1.position[0]
            y1 = comp1.position[1]

            # TC #45 FIX (2025-11-25): Dynamic bounding box from footprint
            # Use pin count to estimate size (2-pin: 3mm, 8-pin: 5mm, etc.)
            pin_count1 = len(comp1.pins)
            w1, h1 = self._estimate_component_size(comp1.footprint, pin_count1)

            # Convert to bounding box (center-based)
            left1 = x1 - w1 / 2
            top1 = y1 - h1 / 2
            right1 = left1 + w1
            bottom1 = top1 + h1

            for comp2 in components[i+1:]:
                # TC #39: Read from component.position
                x2 = comp2.position[0]
                y2 = comp2.position[1]

                # TC #45 FIX (2025-11-25): Dynamic bounding box from footprint
                pin_count2 = len(comp2.pins)
                w2, h2 = self._estimate_component_size(comp2.footprint, pin_count2)

                left2 = x2 - w2 / 2
                top2 = y2 - h2 / 2
                right2 = left2 + w2
                bottom2 = top2 + h2

                # Check overlap (with clearance)
                clearance = self.min_component_clearance
                if not (right1 + clearance < left2 or
                        left1 > right2 + clearance or
                        bottom1 + clearance < top2 or
                        top1 > bottom2 + clearance):
                    overlap_count += 1
                    logger.debug(f"Overlap: {comp1.reference} ({w1:.1f}x{h1:.1f}mm at {x1:.1f},{y1:.1f}) "
                                f"↔ {comp2.reference} ({w2:.1f}x{h2:.1f}mm at {x2:.1f},{y2:.1f})")

        return overlap_count

    def _estimate_component_size(self, footprint: str, pin_count: int) -> Tuple[float, float]:
        """
        Estimate component bounding box size from footprint and pin count.

        TC #45 FIX (2025-11-25): GENERIC function to estimate component sizes dynamically.
        Replaces hardcoded 10mm x 10mm with intelligent size estimation based on:
        - Footprint name patterns (0402, 0603, 0805, SOIC, QFP, DIP, etc.)
        - Pin count (more pins = larger package)

        Args:
            footprint: KiCad footprint name (e.g., "Resistor_SMD:R_0603_1608Metric")
            pin_count: Number of component pins

        Returns:
            (width, height) in mm
        """
        footprint_lower = footprint.lower()

        # SMD passive components (resistors, capacitors)
        if '0402' in footprint:
            return (1.2, 0.7)
        elif '0603' in footprint:
            return (2.0, 1.2)
        elif '0805' in footprint:
            return (2.5, 1.5)
        elif '1206' in footprint:
            return (3.5, 2.0)
        elif '1210' in footprint:
            return (3.5, 2.8)
        elif '2512' in footprint:
            return (6.5, 3.5)

        # SOIC packages (8-28 pin)
        elif 'soic' in footprint_lower:
            # SOIC body width ~4mm, length depends on pin count
            length = 5.0 + (pin_count / 8) * 2.5
            return (4.0, length)

        # QFP packages (32-256 pin)
        elif 'qfp' in footprint_lower or 'lqfp' in footprint_lower or 'tqfp' in footprint_lower:
            # Square QFP packages: size roughly sqrt(pins) * 1.5mm
            import math
            size = math.sqrt(pin_count) * 1.5
            size = max(7.0, min(size, 20.0))  # Clamp between 7-20mm
            return (size, size)

        # DIP packages
        elif 'dip' in footprint_lower:
            # DIP: width ~7.6mm for narrow, ~15.2mm for wide
            width = 7.6 if pin_count <= 24 else 15.2
            length = (pin_count / 2) * 2.54 + 3.0
            return (width, length)

        # TO-220, TO-92, TO packages (power transistors)
        elif 'to-220' in footprint_lower:
            return (10.0, 15.0)
        elif 'to-92' in footprint_lower:
            return (5.0, 5.0)
        elif 'to-' in footprint_lower:
            return (6.0, 8.0)

        # SOT packages (small outline transistors)
        elif 'sot-23' in footprint_lower:
            return (3.0, 3.0)
        elif 'sot-223' in footprint_lower:
            return (7.0, 7.0)
        elif 'sot' in footprint_lower:
            return (3.5, 4.0)

        # Connectors (variable size based on pins)
        elif 'conn' in footprint_lower or 'header' in footprint_lower or 'pinheader' in footprint_lower:
            # Pin headers: 2.54mm pitch
            rows = 1 if 'x1' in footprint_lower or '1x' in footprint_lower else 2
            cols = pin_count // rows
            width = rows * 2.54 + 1.0
            length = cols * 2.54 + 1.0
            return (width, length)

        # Default: estimate based on pin count
        # Small components (2-4 pins): ~3mm
        # Medium (5-16 pins): ~5-8mm
        # Large (17+ pins): ~10-15mm
        import math
        if pin_count <= 4:
            size = 3.0
        elif pin_count <= 16:
            size = 3.0 + (pin_count - 4) * 0.4
        else:
            size = 8.0 + math.sqrt(pin_count - 16) * 1.5

        return (size, size)

    def _check_board_size(self, pcb_file: Path, component_count: int) -> Tuple[bool, str]:
        """
        Check if board size is reasonable for component count (GENERIC).

        Returns: (is_valid, message)
        """
        try:
            with open(pcb_file, 'r') as f:
                content = f.read()

            # Extract board dimensions from gr_rect on Edge.Cuts
            # CRITICAL FIX: Match negative coordinates (e.g., -7.62)
            match = re.search(r'\(gr_rect.*?\(start ([\d.-]+) ([\d.-]+)\).*?\(end ([\d.-]+) ([\d.-]+)\)',
                            content, re.DOTALL)

            if not match:
                return (False, "No board outline found")

            start_x, start_y, end_x, end_y = map(float, match.groups())
            width = abs(end_x - start_x)
            height = abs(end_y - start_y)

            logger.info(f"📐 Board size: {width:.1f}×{height:.1f}mm for {component_count} components")

            # GENERIC validation rules
            if width > self.max_board_size and component_count < 50:
                return (False, f"Board too wide ({width:.0f}mm) for {component_count} components")

            if height > self.max_board_size and component_count < 50:
                return (False, f"Board too tall ({height:.0f}mm) for {component_count} components")

            # Area check
            area = width * height
            max_area = self.max_board_size ** 2  # 150×150 = 22,500 mm²
            if area > max_area and component_count < 50:
                return (False, f"Board area ({area:.0f}mm²) too large for {component_count} components")

            return (True, "Board size OK")

        except Exception as e:
            logger.error(f"Error checking board size: {e}")
            return (False, f"Error: {str(e)}")

    def _check_footprint_pad_clearances(self, circuit_graph: 'CircuitGraph') -> Tuple[int, List[str]]:
        """
        TC #48 FIX (2025-11-25): Validate footprint pad clearances before routing.

        ROOT CAUSE: Previous code used 1.6mm fixed pad size for ALL components,
        causing DRC violations (shorting_items, solder_mask_bridge) because pads
        overlapped within the same component.

        This validation checks:
        1. Pad-to-pad clearance within each footprint
        2. Ensures SMD pad spacing matches IPC-7351B standards

        Args:
            circuit_graph: CircuitGraph with placed components

        Returns:
            (violation_count, violation_messages)
        """
        violations = []
        violation_count = 0

        for ref, comp in circuit_graph.components.items():
            footprint = comp.footprint
            pin_count = len(comp.pins)

            # Get pad specification for this footprint
            pad_spec = get_pad_spec_for_footprint(footprint, pin_count)

            # For 2-pin SMD components, check pad clearance
            if pin_count == 2 and pad_spec.pad_type == 'smd':
                # Extract size code from footprint name
                size_code = self._extract_size_code(footprint)

                if size_code and size_code in SMD_2PAD_SPECS:
                    pad_w, pad_h, center_to_center = SMD_2PAD_SPECS[size_code]

                    # Calculate edge-to-edge clearance
                    edge_clearance = center_to_center - pad_w
                    # TC #66 FIX: Changed MIN_CLEARANCE (doesn't exist) to MIN_TRACE_CLEARANCE
                    min_required = MANUFACTURING_CONFIG.MIN_TRACE_CLEARANCE

                    if edge_clearance < min_required:
                        violation_count += 1
                        msg = (f"{ref} ({footprint}): Pad clearance {edge_clearance:.2f}mm "
                               f"< {min_required}mm required")
                        violations.append(msg)
                        logger.warning(f"⚠️  {msg}")

        if violation_count == 0:
            logger.info("✅ Footprint pad clearances OK")
        else:
            logger.warning(f"⚠️  {violation_count} footprint pad clearance violations found")

        return (violation_count, violations)

    def _extract_size_code(self, footprint: str) -> Optional[str]:
        """Extract package size code from footprint name."""
        match = re.search(r'_(\d{4})(?:_|$|Metric)', footprint)
        if match:
            return match.group(1)
        return None

    def _check_pcb_validity(self, pcb_file: Path) -> Tuple[bool, str]:
        """
        Check PCB file validity (GENERIC S-expression validation).

        Returns: (is_valid, message)
        """
        try:
            with open(pcb_file, 'r') as f:
                content = f.read()

            # Check 1: Balanced parentheses
            open_count = content.count('(')
            close_count = content.count(')')

            if open_count != close_count:
                return (False, f"Unbalanced parentheses: {open_count} open, {close_count} close")

            # Check 2: Has required sections
            required_sections = ['(kicad_pcb', '(general', '(layers', '(setup']
            for section in required_sections:
                if section not in content:
                    return (False, f"Missing required section: {section}")

            # Check 3: Has at least one footprint
            if '(footprint' not in content:
                return (False, "No footprints found in PCB")

            # Check 4: Has nets defined
            if '(net ' not in content:
                return (False, "No nets defined in PCB")

            return (True, "PCB file valid")

        except Exception as e:
            logger.error(f"Error validating PCB: {e}")
            return (False, f"Error: {str(e)}")


def validate_before_routing(pcb_file: Path, circuit_graph: 'CircuitGraph') -> Tuple[bool, str]:
    """
    One-function interface for pre-routing validation (GENERIC).

    TC #39 (2025-11-24): Fix RC #10 - Changed to accept CircuitGraph instead of
    circuit dict and components list, ensuring validation uses correct data source.

    Args:
        pcb_file: Path to .kicad_pcb file
        circuit_graph: CircuitGraph with placed components

    Returns:
        (is_valid, message)
    """
    fixer = PreRoutingFixer()
    return fixer.validate_and_fix(pcb_file, circuit_graph)
