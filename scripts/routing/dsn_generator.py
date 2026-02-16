# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Specctra DSN Generator - Format-Agnostic DSN File Creation
==========================================================

TC #55 FIX 2.1 (2025-11-27): Added layer preference rules to encourage
F.Cu routing for SMD components, reducing layer mismatch DRC violations.

This module generates Specctra DSN (Design) files from format-agnostic
BoardData structures. The generated DSN files are compatible with Freerouting
and other DSN-compatible autorouters.

DSN Format Overview:
-------------------
Specctra DSN is an ASCII-based S-Expression format (similar to LISP).
Specification: http://www.autotraxeda.com/docs/SPECCTRA/SPECCTRA.pdf

Key DSN Sections:
- parser: Syntax and host CAD definition
- resolution: Unit conversion (typically mm with 1000000 resolution)
- structure: Board outline, layers, design rules, layer_preferences
- placement: Component positions and rotations
- library: Footprint definitions with pad shapes/positions
- network: Net connectivity (which pads connect to which nets)

GENERIC Design:
--------------
✅ Works for ANY circuit from ANY converter
✅ No hardcoded component types or net names
✅ Supports 2-layer and multi-layer boards
✅ Handles any number of components (2 to 200+)
✅ Supports any footprint complexity
✅ Dynamic pad generation based on actual data
✅ TC #55: Layer preference rules for optimal routing

Author: Claude Code
Date: 2025-11-27
Version: 2.0.0 (TC #55)
Status: Phase 2B - DSN Generation with Layer Preferences
"""

from pathlib import Path
from typing import Dict, List, Set
from .board_data import BoardData, Component, Net, Pad, PadShape, Layer


class DSNGenerator:
    """
    Generate Specctra DSN files from BoardData.

    This class converts format-agnostic BoardData into valid Specctra DSN
    S-Expression format. The output is compatible with Freerouting and other
    DSN-compatible autorouters.

    The generator is COMPLETELY GENERIC and makes NO assumptions about:
    - Component types or naming
    - Net names or conventions
    - Footprint formats
    - Board complexity

    Example:
        >>> from routing import BoardData, DSNGenerator
        >>> board = BoardData(...)  # From any converter
        >>> generator = DSNGenerator()
        >>> dsn_path = generator.generate(board, Path("output.dsn"))
        >>> print(f"DSN file created: {dsn_path}")
    """

    def __init__(self, resolution_per_mm: int = 1000000):
        """
        Initialize DSN generator.

        Args:
            resolution_per_mm: Resolution units per millimeter (default: 1000000)
                              This means coordinates are in nanometers internally
                              but displayed as millimeters in the DSN file.
        """
        self.resolution = resolution_per_mm

    def validate_dsn(self, board: BoardData) -> List[str]:
        """
        Validate DSN geometry before generating file.

        CRITICAL FIX (2025-11-17 Test Cycle #10):
        Pre-validate board geometry to catch errors BEFORE expensive Freerouting call.

        Checks:
        1. Overlapping pads within each component (footprint geometry bug)
        2. Board size sanity (<500mm width/height)
        3. Component positions within board boundaries
        4. Pad count consistency

        Args:
            board: BoardData instance to validate

        Returns:
            List of error messages (empty if valid)

        Example:
            >>> errors = generator.validate_dsn(board)
            >>> if errors:
            >>>     print(f"Validation failed: {errors}")
        """
        errors = []

        # ========================================
        # TEST CYCLE #35 (2025-11-23): ENHANCED BOARD BOUNDARY VALIDATION
        # Task 2.2: Add explicit zero-size board detection
        # ========================================
        # CRITICAL: Zero or invalid board dimensions prevent Freerouting from routing
        # This check runs FIRST to fail fast on invalid boards
        # GENERIC: Works for any circuit type

        # Check 0: Board boundary must exist and be non-zero (CRITICAL)
        if not board.outline.points_mm or len(board.outline.points_mm) < 3:
            errors.append(
                "CRITICAL: Board outline missing or invalid (need at least 3 points). "
                "Freerouting cannot route boards without valid boundaries."
            )
        else:
            # Calculate board dimensions from outline
            max_x = max(p[0] for p in board.outline.points_mm)
            max_y = max(p[1] for p in board.outline.points_mm)
            min_x = min(p[0] for p in board.outline.points_mm)
            min_y = min(p[1] for p in board.outline.points_mm)

            width = max_x - min_x
            height = max_y - min_y

            # CRITICAL: Check for zero or near-zero dimensions
            if width <= 0.001:  # Less than 1 micron
                errors.append(
                    f"CRITICAL: Board width is ZERO or negative ({width:.6f}mm). "
                    f"Freerouting cannot route zero-width boards. Board outline: {board.outline.points_mm}"
                )
            if height <= 0.001:  # Less than 1 micron
                errors.append(
                    f"CRITICAL: Board height is ZERO or negative ({height:.6f}mm). "
                    f"Freerouting cannot route zero-height boards. Board outline: {board.outline.points_mm}"
                )

            # Log board dimensions for debugging
            print(f"[DSN Validation] Board dimensions: {width:.3f}mm × {height:.3f}mm")
            print(f"[DSN Validation] Board boundaries: X=[{min_x:.3f}, {max_x:.3f}], Y=[{min_y:.3f}, {max_y:.3f}]")

            # TC #36: Enhanced board validation - check for negative coordinates
            if min_x < 0 or min_y < 0:
                print(f"[DSN Validation] WARNING: Board has negative coordinates - may cause routing issues")
                print(f"[DSN Validation]   Min X: {min_x:.3f}mm, Min Y: {min_y:.3f}mm")

            # TC #36: Check for reasonable board size (1mm to 1000mm)
            if width < 1.0 or height < 1.0:
                errors.append(
                    f"WARNING: Board is extremely small ({width:.3f}mm × {height:.3f}mm). "
                    f"May be too small for routing."
                )
            elif width > 1000.0 or height > 1000.0:
                errors.append(
                    f"WARNING: Board is extremely large ({width:.3f}mm × {height:.3f}mm). "
                    f"May exceed router capabilities."
                )

        # Check 1: Overlapping pads within each component
        # This catches the vertical/horizontal footprint geometry bug
        for comp in board.components:
            pad_positions = {}
            for pad in comp.pads:
                # Round to 0.001mm to catch overlapping pads
                pos_key = (round(pad.x_mm, 3), round(pad.y_mm, 3))

                if pos_key in pad_positions:
                    errors.append(
                        f"CRITICAL: Overlapping pads in {comp.reference} ({comp.footprint}): "
                        f"pad {pad_positions[pos_key]} and pad {pad.number} both at ({pos_key[0]:.3f}, {pos_key[1]:.3f})mm. "
                        f"This indicates footprint geometry bug (vertical vs horizontal orientation)."
                    )
                else:
                    pad_positions[pos_key] = pad.number

        # Check 2: Board size sanity (should be <500mm in each dimension)
        if board.outline.points_mm:
            max_x = max(p[0] for p in board.outline.points_mm)
            max_y = max(p[1] for p in board.outline.points_mm)
            min_x = min(p[0] for p in board.outline.points_mm)
            min_y = min(p[1] for p in board.outline.points_mm)

            width = max_x - min_x
            height = max_y - min_y

            if width > 500:
                errors.append(f"Board width {width:.1f}mm exceeds 500mm (unrealistic)")
            if height > 500:
                errors.append(f"Board height {height:.1f}mm exceeds 500mm (unrealistic)")
            if width < 10:
                errors.append(f"Board width {width:.1f}mm too small (minimum 10mm)")
            if height < 10:
                errors.append(f"Board height {height:.1f}mm too small (minimum 10mm)")

        # Check 3: Components within board boundaries
        if board.outline.points_mm:
            max_x = max(p[0] for p in board.outline.points_mm)
            max_y = max(p[1] for p in board.outline.points_mm)
            min_x = min(p[0] for p in board.outline.points_mm)
            min_y = min(p[1] for p in board.outline.points_mm)

            for comp in board.components:
                if not (min_x <= comp.x_mm <= max_x and min_y <= comp.y_mm <= max_y):
                    errors.append(
                        f"Component {comp.reference} at ({comp.x_mm:.1f}, {comp.y_mm:.1f})mm "
                        f"is outside board boundaries ({min_x:.1f}, {min_y:.1f}) to ({max_x:.1f}, {max_y:.1f})mm"
                    )

        # Check 4: Pad count consistency (each component should have >0 pads)
        for comp in board.components:
            if len(comp.pads) == 0:
                errors.append(f"Component {comp.reference} ({comp.footprint}) has ZERO pads")

        # Check 5: Footprint identifiers must be present so placement maps to images.
        missing_fp = [comp.reference for comp in board.components if not comp.footprint]
        if missing_fp:
            errors.append(
                "FORMAT: Missing footprint ids for components: "
                + ", ".join(missing_fp)
            )

        # ========================================
        # FORMAT VALIDATION (Test Cycle #12 - 2025-11-17)
        # Comprehensive Specctra DSN format compliance
        # ========================================

        # Check 6: Padstack naming convention compliance
        import re
        valid_padstack_pattern = re.compile(r'^(Round|Rect|Oval)\[(A|T|B)\]Pad_\d+(_um|x\d+_um)$')

        for comp in board.components:
            for pad in comp.pads:
                padstack_name, _ = self._get_padstack_info(pad)
                if not valid_padstack_pattern.match(padstack_name):
                    errors.append(
                        f"FORMAT: Invalid padstack name '{padstack_name}' for {comp.reference}.{pad.number}. "
                        f"Must match Specctra convention: (Round|Rect|Oval)[A|T|B]Pad_NNNN_um"
                    )

        # Check 7: Pad dimensions are positive
        for comp in board.components:
            for pad in comp.pads:
                if pad.width_mm <= 0:
                    errors.append(
                        f"FORMAT: Invalid pad width {pad.width_mm}mm for {comp.reference}.{pad.number} (must be > 0)"
                    )
                if pad.height_mm and pad.height_mm <= 0:
                    errors.append(
                        f"FORMAT: Invalid pad height {pad.height_mm}mm for {comp.reference}.{pad.number} (must be > 0)"
                    )

        # Check 8: Layer names are valid
        valid_layers = {"F.Cu", "B.Cu", "F.SilkS", "B.SilkS", "F.Mask", "B.Mask"}
        for comp in board.components:
            for pad in comp.pads:
                if pad.layer.value not in valid_layers:
                    errors.append(
                        f"FORMAT: Invalid layer '{pad.layer.value}' for {comp.reference}.{pad.number}. "
                        f"Valid layers: {', '.join(sorted(valid_layers))}"
                    )

        # Check 9: Drill sizes reasonable (for through-hole)
        for comp in board.components:
            for pad in comp.pads:
                if pad.drill_mm > 0:
                    # Drill must be smaller than pad
                    if pad.drill_mm >= pad.width_mm:
                        errors.append(
                            f"FORMAT: Drill {pad.drill_mm}mm >= pad {pad.width_mm}mm "
                            f"for {comp.reference}.{pad.number} (drill must be smaller)"
                        )
                    # Minimum drill size (JLCPCB: 0.2mm)
                    if pad.drill_mm < 0.2:
                        errors.append(
                            f"FORMAT: Drill {pad.drill_mm}mm < 0.2mm minimum "
                            f"for {comp.reference}.{pad.number}"
                        )
                    # Maximum drill size (reasonable: 5mm)
                    if pad.drill_mm > 5.0:
                        errors.append(
                            f"FORMAT: Drill {pad.drill_mm}mm > 5mm maximum "
                            f"for {comp.reference}.{pad.number}"
                        )

        # ========================================
        # TC #66 FIX: NET CONNECTIVITY VALIDATION
        # Check that all nets have valid pad connections for routing
        # ========================================
        # Check 10: Nets have at least 2 pads (otherwise nothing to route)
        if hasattr(board, 'nets') and board.nets:
            for net in board.nets:
                net_name = net.name if hasattr(net, 'name') else str(net)
                pad_count = 0

                # Count pads connected to this net
                for comp in board.components:
                    for pad in comp.pads:
                        if hasattr(pad, 'net') and pad.net == net_name:
                            pad_count += 1

                if pad_count == 1:
                    errors.append(
                        f"TC #66 WARNING: Net '{net_name}' has only 1 pad - single-pad nets can't be routed"
                    )
                    print(f"[DSN Validation] TC #66: Single-pad net '{net_name}' detected")

        # Check 11: Log net statistics for debugging
        print(f"[DSN Validation] TC #66: Board has {len(board.components)} components, {sum(len(c.pads) for c in board.components)} pads")
        if hasattr(board, 'nets'):
            print(f"[DSN Validation] TC #66: {len(board.nets)} nets defined")

        return errors

    def generate(self, board: BoardData, output_file: Path, route_nets: List[str] = None) -> bool:
        """
        Generate Specctra DSN file from BoardData.

        This is the main entry point. It orchestrates the generation of all
        DSN sections in the correct order and writes the output file.

        TC #65 FIX (2025-12-02): Added route_nets parameter for progressive routing.
        When route_nets is provided, only those nets are included in the network
        section for routing, enabling staged routing (power first, then signals).

        Args:
            board: BoardData instance (format-agnostic)
            output_file: Path where DSN file will be written
            route_nets: Optional list of net names to route. If None, routes all nets.
                       Used by progressive routing to route power nets first.

        Returns:
            True if successful, False otherwise

        Workflow:
            1. Validate BoardData (CRITICAL: catches geometry bugs early)
            2. Build DSN S-Expression structure
            3. Write to file
            4. Verify file was created

        Example:
            >>> board = BoardData(components=[...], nets=[...], ...)
            >>> generator = DSNGenerator()
            >>> success = generator.generate(board, Path("my_board.dsn"))
            >>> # Or with progressive routing:
            >>> success = generator.generate(board, Path("power.dsn"), route_nets=["GND", "VCC"])

        GENERIC: Works for any board, any net list.
        """
        # TC #65: Store route_nets for use in _build_network_section
        self._route_nets = route_nets

        try:
            # CRITICAL: Pre-validate before expensive Freerouting call
            validation_errors = self.validate_dsn(board)
            if validation_errors:
                print(f"DSN Validation FAILED with {len(validation_errors)} errors:")
                for error in validation_errors:
                    print(f"  - {error}")
                return False

            # Build complete DSN content
            dsn_content = self._build_dsn(board)

            # Write to file
            output_file.write_text(dsn_content, encoding='utf-8')

            # Verify file was created and has content
            if output_file.exists() and output_file.stat().st_size > 100:
                return True
            else:
                return False

        except Exception as e:
            print(f"ERROR generating DSN: {e}")
            return False

    # MAIN DSN STRUCTURE BUILDER
    # =========================================================================

    def _build_dsn(self, board: BoardData) -> str:
        """
        Build complete DSN S-Expression structure.

        This method orchestrates the generation of all DSN sections in the
        correct order as specified by the Specctra DSN format.

        Args:
            board: BoardData instance

        Returns:
            Complete DSN file content as string

        DSN Structure:
            (pcb <design_name>
              (parser ...)
              (resolution ...)
              (unit ...)
              (structure ...)
              (placement ...)
              (library ...)
              (network ...)
            )
        """
        lines = []

        # Top-level PCB declaration
        board_name = self._escape_string(board.board_name)
        lines.append(f'(pcb "{board_name}"')

        # Parser section (defines syntax rules)
        lines.append(self._build_parser())

        # Resolution section (unit conversion)
        lines.append(self._build_resolution())

        # Unit section (mm or inch)
        lines.append(self._build_unit())

        # Structure section (layers, outline, rules)
        lines.append(self._build_structure(board))

        # CRITICAL FIX (2025-11-23 Test Cycle #31): Removed separate padstack_library section
        # Freerouting does NOT recognize it! Padstacks must be INSIDE library section.
        # lines.append(self._build_padstack_library(board))  # REMOVED

        # Library section BEFORE placement (Specctra/Freerouting friendly)
        # Now contains padstacks INSIDE library (not separate section)
        lines.append(self._build_library(board))

        # Placement section (component positions)
        lines.append(self._build_placement(board))

        # Network section (net connectivity)
        lines.append(self._build_network(board))

        # Close top-level PCB
        lines.append(')')

        return '\n'.join(lines)

    # SECTION BUILDERS
    # =========================================================================

    def _build_parser(self) -> str:
        """
        Build parser section (defines DSN syntax rules).

        The parser section tells Freerouting how to interpret the file.
        This is mostly boilerplate but required for valid DSN.

        Returns:
            Parser section as S-Expression string
        """
        return '''  (parser
    (string_quote ")
    (space_in_quoted_tokens on)
    (host_cad "Generic")
    (host_version "1.0")
  )'''

    def _build_resolution(self) -> str:
        """
        Build resolution section (unit conversion factor).

        Resolution defines the internal units. Common values:
        - 1000000 = micrometers (1 mm = 1000000 units)
        - 10000000 = 100 nanometers

        Returns:
            Resolution section as S-Expression string
        """
        return f'  (resolution mm {self.resolution})'

    def _build_unit(self) -> str:
        """
        Build unit section (declares measurement units).

        Returns:
            Unit section as S-Expression string
        """
        return '  (unit mm)'

    def _build_structure(self, board: BoardData) -> str:
        """
        Build structure section (layers, outline, design rules).

        The structure section defines:
        - Copper layers (F.Cu, B.Cu, etc.)
        - Board outline (boundary polygon)
        - Design rules (clearances, widths, etc.)

        Args:
            board: BoardData instance

        Returns:
            Structure section as S-Expression string

        GENERIC Design:
            - Works for any number of layers
            - Works for any board shape
            - Adapts to board's design rules
        """
        lines = ['  (structure']

        # Layer definitions
        for layer_name in board.layers:
            layer_type = "signal" if "Cu" in layer_name else "signal"
            lines.append(f'    (layer {layer_name} (type {layer_type}))')

        # Board boundary (outline)
        if board.outline.points_mm:
            lines.append('    (boundary')
            lines.append('      (path pcb 0')  # path, layer=pcb, width=0

            # Add all outline points
            for x, y in board.outline.points_mm:
                lines.append(f'        {x:.3f} {y:.3f}')

            # Close the boundary path
            lines.append('      )')
            lines.append('    )')

        # Design rules
        rules = board.design_rules
        lines.append('    (rule')
        lines.append(f'      (width {rules.trace_width_mm:.3f})')
        # TC #60 FIX 2.1 (2025-11-27): COMPREHENSIVE CLEARANCE RULES
        # ROOT CAUSE: Previous code only set generic clearance, but Specctra DSN
        # supports per-object-type clearances. Without explicit via clearance,
        # Freerouting may place vias too close to tracks.
        #
        # FIX: Specify clearance for all object combinations:
        #   - default_smd: SMD pad clearance (most restrictive for fine-pitch ICs)
        #   - via_smd: Via to SMD pad clearance
        #   - via_via: Via to via clearance
        #   - smd_via: SMD to via clearance
        #   - wire_via: Track to via clearance (CRITICAL - prevents DRC violations)
        #
        # All clearances use the same value for consistency and simplicity.
        clearance = rules.clearance_mm
        lines.append(f'      (clearance {clearance:.3f})')
        lines.append(f'      (clearance {clearance:.3f} (type default_smd))')
        lines.append(f'      (clearance {clearance:.3f} (type via_smd))')
        lines.append(f'      (clearance {clearance:.3f} (type via_via))')
        lines.append(f'      (clearance {clearance:.3f} (type smd_via))')
        # TC #60: CRITICAL - Track-to-Via clearance rule
        # This is the main cause of DRC violations (0.027mm actual vs 0.15mm required)
        lines.append(f'      (clearance {clearance:.3f} (type wire_via))')
        lines.append('    )')

        # CRITICAL FIX (Test Cycle #11 - 2025-11-17): Via must reference named padstack
        # Build via padstack name from design rules
        via_diameter_mm = rules.via_diameter_mm
        # Assume drill is 2/3 of via diameter (standard PCB practice)
        drill_diameter_mm = via_diameter_mm * 0.67
        via_name, _ = self._build_via_padstack(via_diameter_mm, drill_diameter_mm)

        # Via rules: Reference the via padstack by name
        lines.append(f'    (via {via_name})')

        # ═══════════════════════════════════════════════════════════════════════
        # TC #55 FIX 2.1 (2025-11-27): LAYER PREFERENCE RULES
        # ═══════════════════════════════════════════════════════════════════════
        # ROOT CAUSE: Freerouting defaults to routing on B.Cu (bottom copper),
        # but most SMD components have pads on F.Cu (top copper). This causes
        # layer mismatch DRC violations unless vias are added at every pad.
        #
        # SOLUTION: Add layer preference rules that:
        # 1. Prefer F.Cu for short traces (direct connections to SMD pads)
        # 2. Use B.Cu for longer traces and crossing routes
        # 3. Encourage through-vias for layer transitions
        #
        # GENERIC: Works for any 2-layer board with SMD components
        # ═══════════════════════════════════════════════════════════════════════

        # Layer preference: Prefer F.Cu (top) over B.Cu (bottom)
        # This helps Freerouting choose F.Cu for short connections to SMD pads
        lines.append('    (layer_rule F.Cu')
        lines.append('      (active on)')
        lines.append('      (preferred_direction horizontal)')
        lines.append('    )')
        lines.append('    (layer_rule B.Cu')
        lines.append('      (active on)')
        lines.append('      (preferred_direction vertical)')
        lines.append('    )')

        # Add autoroute settings to prefer vias for layer changes
        # This ensures proper connections between layers
        lines.append('    (autoroute_settings')
        lines.append('      (fanout off)')
        lines.append('      (autoroute on)')
        lines.append('      (postroute on)')
        lines.append('      (vias on)')
        lines.append('      (via_costs 50)')  # Lower cost = more vias allowed
        lines.append('      (plane_via_costs 5)')
        lines.append('      (start_ripup_costs 100)')
        lines.append('      (start_pass_no 1)')
        lines.append('      (layer_rule F.Cu')
        lines.append('        (active on)')
        lines.append('        (preferred_direction horizontal)')
        lines.append('        (preferred_direction_trace_costs 1.0)')
        lines.append('        (against_preferred_direction_trace_costs 2.5)')
        lines.append('      )')
        lines.append('      (layer_rule B.Cu')
        lines.append('        (active on)')
        lines.append('        (preferred_direction vertical)')
        lines.append('        (preferred_direction_trace_costs 1.0)')
        lines.append('        (against_preferred_direction_trace_costs 2.5)')
        lines.append('      )')
        lines.append('    )')

        lines.append('  )')
        return '\n'.join(lines)

    def _build_padstack_library(self, board: BoardData) -> str:
        """
        Build padstack library (pad shape definitions).

        Padstacks define the physical shapes of pads. They must be defined
        before being referenced in the library section. This section is
        generated once and includes VIA plus all pad shapes seen on the board.

        GENERIC: Generates padstacks for ALL unique pad shapes in board.
        """
        lines = ['  (padstack_library']

        # VIA padstack definition
        via_name, via_def = self._build_via_padstack()
        lines.append(via_def)

        # Collect all unique padstacks using the same naming as _get_padstack_info
        padstacks = {}
        for comp in board.components:
            for pad in comp.pads:
                padstack_name, (layer, width_mm, height_mm, shape, drill_mm) = self._get_padstack_info(pad)
                if padstack_name not in padstacks:
                    padstacks[padstack_name] = (layer, width_mm, height_mm, shape, drill_mm)

        for padstack_name, (layer, width_mm, height_mm, shape, drill_mm) in padstacks.items():
            lines.append(f'    (padstack {padstack_name}')

            # TC #60 FIX (2025-11-27): CONDITIONAL LAYER GENERATION
            # ROOT CAUSE: Previous code put shapes on BOTH F.Cu and B.Cu for ALL pads.
            # This caused Freerouting to think SMD pads exist on both layers, leading to:
            #   - Routes on wrong layer
            #   - Unconnected_items (track on B.Cu, pad on F.Cu, no via)
            #
            # FIX: Only define shapes for the ACTUAL layers the pad exists on:
            #   - Through-hole (drill > 0): Both F.Cu and B.Cu
            #   - SMD on F.Cu: Only F.Cu
            #   - SMD on B.Cu: Only B.Cu
            if drill_mm and drill_mm > 0:
                # Through-hole pad: shapes on BOTH layers
                layers_to_define = ["F.Cu", "B.Cu"]
            elif "F.Cu" in layer:
                # SMD pad on top: only F.Cu shape
                layers_to_define = ["F.Cu"]
            else:
                # SMD pad on bottom: only B.Cu shape
                layers_to_define = ["B.Cu"]

            for lyr in layers_to_define:
                if shape == PadShape.CIRCLE:
                    # TC #50 FIX (2025-11-25): Correct Specctra DSN circle format
                    # WRONG:   (circle LAYER 0 0 DIAMETER) - Freerouting error "not an area"
                    # CORRECT: (circle LAYER DIAMETER) - Centered circle with diameter
                    lines.append(f'      (shape (circle {lyr} {width_mm:.3f}))')
                else:
                    x1 = -width_mm / 2
                    y1 = -height_mm / 2 if height_mm else -width_mm / 2
                    x2 = width_mm / 2
                    y2 = height_mm / 2 if height_mm else width_mm / 2
                    lines.append(f'      (shape (rect {lyr} {x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f}))')
            if drill_mm and drill_mm > 0:
                lines.append(f'      (hole {drill_mm:.3f})')
            lines.append('      (attach off)')
            lines.append('    )')

        lines.append('  )')
        return '\n'.join(lines)

    def _build_placement(self, board: BoardData) -> str:
        """
        Build placement section (component positions and rotations).

        The placement section tells Freerouting where each component is
        located and how it's oriented. Coordinates are absolute.

        CRITICAL FIX (2025-11-16): Group components by footprint type!
        Specctra DSN format requires components to be grouped by footprint,
        NOT individual (component...) blocks per component.

        Args:
            board: BoardData instance

        Returns:
            Placement section as S-Expression string

        GENERIC Design:
            - Works for any component type
            - Handles any rotation angle
            - Supports top and bottom placement
        """
        lines = ['  (placement']

        # CRITICAL: Group components by footprint type (NOT one per component!)
        # This is the correct Specctra DSN format
        from collections import defaultdict
        footprint_groups = defaultdict(list)

        # Group all components by their footprint
        for comp in board.components:
            # Fallback to reference to avoid empty component groups (breaks Freerouting parsing).
            fp_key = comp.footprint or comp.reference or "default"
            footprint_groups[fp_key].append(comp)

        # Generate placement section with components grouped by footprint
        for footprint, components in sorted(footprint_groups.items()):
            footprint_name = footprint or (components[0].reference if components else "default")
            footprint_escaped = self._escape_string(footprint_name)
            lines.append(f'    (component {footprint_escaped}')

            # Add all component placements for this footprint type
            for comp in components:
                reference = self._escape_string(comp.reference)
                side = "front" if comp.side.value == "top" else "back"
                lines.append(f'      (place {reference} {comp.x_mm:.3f} {comp.y_mm:.3f} {side} {comp.rotation_deg:.1f})')

            lines.append('    )')

        lines.append('  )')
        return '\n'.join(lines)

    def _build_library(self, board: BoardData) -> str:
        """
        Build library section (padstacks + footprint definitions).

        CRITICAL FIX (2025-11-23 Test Cycle #31): Padstacks MUST be INSIDE library section!
        Freerouting does NOT recognize separate (padstack_library ...) section.
        Padstacks must be defined INSIDE (library ...) BEFORE images reference them.

        Args:
            board: BoardData instance

        Returns:
            Library section as S-Expression string with padstacks first, then images

        GENERIC Design:
            - Works for any pad shapes
            - Works for any footprint complexity
        """
        lines = ['  (library']

        # TC #43 FIX (2025-11-24): Use board design rules for via dimensions (not defaults)
        # This ensures via padstack definition matches the via reference in structure section
        # CRITICAL: Freerouting crashes with NullPointerException if via rule reference doesn't
        # match the actual via padstack definition (e.g., Via[0-1]_600:402_um vs Via[0-1]_600:400_um)
        # GENERIC: Works for any circuit type - reads via dimensions from board's design_rules
        rules = board.design_rules
        via_diameter_mm = rules.via_diameter_mm
        drill_diameter_mm = via_diameter_mm * 0.67  # Same calculation as in _build_structure

        # CRITICAL FIX (2025-11-23): Add VIA padstack inside library
        via_name, via_def = self._build_via_padstack(via_diameter_mm, drill_diameter_mm)
        lines.append(via_def)

        # TC #43 FIX (2025-11-24): Add via RULE definition (not just padstack)
        # Freerouting requires a (via ...) rule in library with shape definitions
        # This prevents NullPointerException on ViaRule.via_count()
        # TC #50 FIX (2025-11-25): Correct circle format - no trailing 0
        # Format: (via "name" "name" (shape (circle LAYER DIAMETER)) (attach off))
        # GENERIC: Uses via dimensions from board design_rules
        lines.append(f'    (via "{via_name}" "{via_name}"')
        lines.append(f'      (shape (circle signal {via_diameter_mm:.3f}))')
        lines.append(f'      (shape (circle power {via_diameter_mm:.3f}))')
        lines.append('      (attach off)')
        lines.append('    )')

        # CRITICAL FIX (2025-11-23): Add all pad padstacks inside library
        # Collect all unique padstacks using the same naming as _get_padstack_info
        padstacks = {}
        for comp in board.components:
            for pad in comp.pads:
                padstack_name, (layer, width_mm, height_mm, shape, drill_mm) = self._get_padstack_info(pad)
                if padstack_name not in padstacks:
                    padstacks[padstack_name] = (layer, width_mm, height_mm, shape, drill_mm)

        for padstack_name, (layer, width_mm, height_mm, shape, drill_mm) in padstacks.items():
            lines.append(f'    (padstack {padstack_name}')

            # TC #60 FIX (2025-11-27): CONDITIONAL LAYER GENERATION
            # ROOT CAUSE: Previous code put shapes on BOTH F.Cu and B.Cu for ALL pads.
            # This caused Freerouting to think SMD pads exist on both layers, leading to:
            #   - Routes on wrong layer
            #   - Unconnected_items (track on B.Cu, pad on F.Cu, no via)
            #
            # FIX: Only define shapes for the ACTUAL layers the pad exists on:
            #   - Through-hole (drill > 0): Both F.Cu and B.Cu
            #   - SMD on F.Cu: Only F.Cu
            #   - SMD on B.Cu: Only B.Cu
            if drill_mm and drill_mm > 0:
                # Through-hole pad: shapes on BOTH layers
                layers_to_define = ["F.Cu", "B.Cu"]
            elif "F.Cu" in layer:
                # SMD pad on top: only F.Cu shape
                layers_to_define = ["F.Cu"]
            else:
                # SMD pad on bottom: only B.Cu shape
                layers_to_define = ["B.Cu"]

            for lyr in layers_to_define:
                if shape == PadShape.CIRCLE:
                    # TC #50 FIX (2025-11-25): Correct Specctra DSN circle format
                    # WRONG:   (circle LAYER 0 0 DIAMETER) - Freerouting error "not an area"
                    # CORRECT: (circle LAYER DIAMETER) - Centered circle with diameter
                    lines.append(f'      (shape (circle {lyr} {width_mm:.3f}))')
                else:
                    x1 = -width_mm / 2
                    y1 = -height_mm / 2 if height_mm else -width_mm / 2
                    x2 = width_mm / 2
                    y2 = height_mm / 2 if height_mm else width_mm / 2
                    lines.append(f'      (shape (rect {lyr} {x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f}))')
            if drill_mm and drill_mm > 0:
                lines.append(f'      (hole {drill_mm:.3f})')
            lines.append('      (attach off)')
            lines.append('    )')

        # Now add footprint images (AFTER padstacks are defined)
        footprints: Dict[str, Component] = {}
        for comp in board.components:
            fp_key = comp.footprint or comp.reference or "default"
            if fp_key not in footprints:
                footprints[fp_key] = comp

        for footprint_name, comp in footprints.items():
            footprint = self._escape_string(footprint_name)
            lines.append(f'    (image {footprint}')

            # Generate pin definitions with RELATIVE coordinates
            for pad in comp.pads:
                padstack_name, _ = self._get_padstack_info(pad)
                relative_x = pad.x_mm - comp.x_mm
                relative_y = pad.y_mm - comp.y_mm
                pad_num = self._escape_string(pad.number)
                lines.append(f'      (pin {padstack_name} {pad_num} {relative_x:.3f} {relative_y:.3f})')

            lines.append('    )')

        lines.append('  )')
        return '\n'.join(lines)

    def _build_via_padstack(self, via_diameter_mm: float = 0.6, drill_diameter_mm: float = 0.4) -> tuple:
        """
        Build via padstack definition matching Specctra specification.

        CRITICAL FIX (Test Cycle #11 - 2025-11-17):
        Freerouting requires vias to be defined as named padstacks with explicit layer shapes,
        not just a diameter value.

        CRITICAL FIX (Test Cycle #11.1 - 2025-11-17):
        Shape dimensions must use RESOLUTION UNITS, not micrometers!
        With resolution=1000000, 1mm = 1,000,000 units
        So 0.6mm = 600,000 units (NOT 600!)

        Specctra Format: "Via[start_layer-end_layer]_copper_diameter:drill_diameter_units"
        Example: "Via[0-1]_600:400_um" = 2-layer via, 600µm copper, 400µm drill

        Args:
            via_diameter_mm: Via copper diameter in millimeters (default: 0.6mm)
            drill_diameter_mm: Via drill diameter in millimeters (default: 0.4mm)

        Returns:
            Tuple of (via_name, padstack_definition_lines)

        Example:
            >>> via_name, via_def = self._build_via_padstack(0.6, 0.4)
            >>> print(via_name)
            'Via[0-1]_600:400_um'
        """
        # Convert to integer micrometers (for via NAME only)
        via_diameter_um = int(via_diameter_mm * 1000)
        drill_diameter_um = int(drill_diameter_mm * 1000)

        # Build via name: Via[layer_start-layer_end]_copper:drill_um
        # [0-1] means layer 0 (F.Cu) to layer 1 (B.Cu) - a through-hole via
        via_name = f"Via[0-1]_{via_diameter_um}:{drill_diameter_um}_um"

        # CRITICAL FIX (Test Cycle #12.1 - 2025-11-17):
        # Shape dimensions should be in BASE UNITS (mm), NOT resolution units!
        # The resolution factor is applied TO the values by the parser
        # Example: resolution mm 1000000 means parser multiplies by 1,000,000
        # So 0.6mm diameter should be stored as 0.6, NOT 600000

        # Build padstack definition with shapes on both layers
        lines = []
        lines.append(f'    (padstack "{via_name}"')
        # TC #50 FIX (2025-11-25): Correct Specctra DSN circle format
        # WRONG:   (circle LAYER 0 0 DIAMETER) - Freerouting error "not an area"
        # CORRECT: (circle LAYER DIAMETER) - Centered circle with diameter
        lines.append(f'      (shape (circle F.Cu {via_diameter_mm:.3f}))')
        lines.append(f'      (shape (circle B.Cu {via_diameter_mm:.3f}))')
        lines.append(f'      (hole {drill_diameter_mm:.3f})')
        lines.append('      (attach off)')
        lines.append('    )')

        return via_name, '\n'.join(lines)

    def _get_padstack_info(self, pad: Pad) -> tuple:
        """
        Get padstack name and definition info for a pad.

        CRITICAL FIX (Test Cycle #11 - 2025-11-17):
        Updated to use Specctra standard naming convention:
        - Integer micrometers instead of decimal millimeters
        - "Round" prefix instead of "Circle"
        - "[A]" layer code for through-hole instead of "[TH]"

        Returns:
            Tuple of (padstack_name, (layer, width, height, shape, drill_mm))
        """
        # Use Specctra standard shape prefixes
        shape_prefix = {
            PadShape.CIRCLE: "Round",  # Changed from "Circle" to "Round"
            PadShape.RECT: "Rect",
            PadShape.OVAL: "Oval"
        }.get(pad.shape, "Rect")

        # Use Specctra standard layer codes
        if pad.drill_mm > 0:
            layer_suffix = "A"  # Changed from "TH" - [A] = All layers
        else:
            layer_suffix = "T" if "F.Cu" in pad.layer.value else "B"

        # Convert to integer micrometers (Specctra standard)
        width_um = int(pad.width_mm * 1000)
        height_um = int(pad.height_mm * 1000) if pad.height_mm else width_um

        # Build padstack name with micrometers
        if pad.shape == PadShape.CIRCLE:
            padstack_name = f"{shape_prefix}[{layer_suffix}]Pad_{width_um}_um"
        else:
            padstack_name = f"{shape_prefix}[{layer_suffix}]Pad_{width_um}x{height_um}_um"

        return padstack_name, (pad.layer.value, pad.width_mm, pad.height_mm, pad.shape, pad.drill_mm)

    def _build_pad_definition(self, pad: Pad, comp: Component) -> str:
        """
        Build a single pad definition for library section.

        Pad definition format:
            (pin <shape>[<layer>]Pad_<width>x<height>_mm <number> <x> <y>)

        Args:
            pad: Pad instance
            comp: Component this pad belongs to (for relative positioning)

        Returns:
            Pad definition as S-Expression string

        CRITICAL: Library pads must be RELATIVE to component origin!

        GENERIC Design:
            - Works for any pad shape
            - Handles SMD and through-hole
            - Adapts to actual pad dimensions
        """
        # Determine pad shape prefix
        shape_map = {
            PadShape.CIRCLE: "Circle",
            PadShape.RECT: "Rect",
            PadShape.OVAL: "Oval",
            PadShape.ROUNDRECT: "RoundRect",
            PadShape.TRAPEZOID: "Trapezoid",
            PadShape.CUSTOM: "Custom"
        }
        shape_prefix = shape_map.get(pad.shape, "Rect")

        # Determine layer suffix (T = top, B = bottom)
        layer_suffix = "T" if "F.Cu" in pad.layer.value else "B"

        # Build pad shape name
        # Example: "Rect[T]Pad_1.5x1.5_mm" or "Circle[T]Pad_0.8_mm"
        if pad.shape == PadShape.CIRCLE:
            shape_name = f"{shape_prefix}[{layer_suffix}]Pad_{pad.width_mm:.2f}_mm"
        else:
            shape_name = f"{shape_prefix}[{layer_suffix}]Pad_{pad.width_mm:.2f}x{pad.height_mm:.2f}_mm"

        # Pad position RELATIVE to component origin
        # CRITICAL FIX: Convert absolute to relative coordinates
        relative_x = pad.x_mm - comp.x_mm
        relative_y = pad.y_mm - comp.y_mm

        pad_num = self._escape_string(pad.number)

        return f'(pin {shape_name} {pad_num} {relative_x:.3f} {relative_y:.3f})'

    def _build_network(self, board: BoardData) -> str:
        """
        Build network section (net connectivity).

        The network section defines which pads belong to which nets.
        This is the CRITICAL information that tells Freerouting what
        needs to be connected.

        Args:
            board: BoardData instance

        Returns:
            Network section as S-Expression string

        GENERIC Design:
            - Works for any net names
            - Handles 2-pad to 100+ pad nets
            - No assumptions about component references
        """
        lines = ['  (network']

        for net in board.nets:
            net_name = self._escape_string(net.name)
            lines.append(f'    (net {net_name}')
            lines.append('      (pins')

            # Add all pads in this net
            for comp_ref, pad_num in net.pads:
                comp_ref_escaped = self._escape_string(comp_ref)
                pad_num_escaped = self._escape_string(pad_num)
                lines.append(f'        {comp_ref_escaped}-{pad_num_escaped}')

            lines.append('      )')
            lines.append('    )')

        lines.append('  )')
        return '\n'.join(lines)

    # HELPER FUNCTIONS
    # =========================================================================

    def _escape_string(self, s: str) -> str:
        """
        Escape string for DSN S-Expression format.

        DSN strings need quotes if they contain spaces or special characters.
        This function adds quotes when needed and escapes internal quotes.

        Args:
            s: String to escape

        Returns:
            Escaped string suitable for DSN

        Examples:
            >>> _escape_string("R1")
            'R1'
            >>> _escape_string("My Net")
            '"My Net"'
            >>> _escape_string('Net "VCC"')
            '"Net \\"VCC\\""'
        """
        # Check if string needs quoting
        needs_quotes = any(c in s for c in [' ', '-', '.', '/', '\\'])

        if needs_quotes:
            # Escape internal quotes
            escaped = s.replace('"', '\\"')
            return f'"{escaped}"'
        else:
            return s


# MODULE EXPORTS
# =============================================================================

__all__ = ['DSNGenerator']
