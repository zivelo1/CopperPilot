# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Format-Agnostic PCB Board Data Structures
=========================================

This module defines GENERIC, MODULAR dataclasses that represent PCB data
in a format-independent way. These structures serve as the intermediate
representation between:
- KiCad .kicad_pcb files (S-Expression)
- Eagle .brd files (XML)
- EasyEDA JSON files

The design is intentionally SIMPLE and GENERIC to support ANY circuit type,
ANY complexity, and ANY EDA tool format.

Key Principles:
--------------
✅ GENERIC: No format-specific fields or assumptions
✅ MODULAR: Each class has single responsibility
✅ DYNAMIC: Works for 2-pin resistors to 256-pin ICs
✅ EXTENSIBLE: Easy to add new properties without breaking existing code
✅ TYPE-SAFE: Uses Python dataclasses with type hints
✅ DOCUMENTED: Professional docstrings for all classes

TC #60 FIX (2025-11-27): USE KICAD PROJECT RULES
================================================
Design rules can now be loaded from KiCad project files (.kicad_pro)
using the KiCadProjectLoader. This ensures we use EXACT rules from
proven KiCad projects instead of guessing.

Author: Claude Code
Date: 2025-11-16
Version: 1.1.0 (TC #60 - KiCad Project Rules Integration)
Status: Phase 2B - Core Data Structures
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ENUMERATIONS
# =============================================================================

class Layer(Enum):
    """PCB layer enumeration (GENERIC - works for any layer count)."""
    F_CU = "F.Cu"      # Front copper
    B_CU = "B.Cu"      # Back copper
    F_SILKS = "F.SilkS"  # Front silkscreen
    B_SILKS = "B.SilkS"  # Back silkscreen
    F_MASK = "F.Mask"    # Front solder mask
    B_MASK = "B.Mask"    # Back solder mask
    EDGE_CUTS = "Edge.Cuts"  # Board outline


class PadShape(Enum):
    """Pad shape enumeration (GENERIC - supports all common shapes)."""
    CIRCLE = "circle"
    RECT = "rect"
    OVAL = "oval"
    ROUNDRECT = "roundrect"
    TRAPEZOID = "trapezoid"
    CUSTOM = "custom"


class Side(Enum):
    """Component mounting side (GENERIC)."""
    TOP = "top"
    BOTTOM = "bottom"


# BASIC DATA STRUCTURES
# =============================================================================

@dataclass
class Pad:
    """
    Format-agnostic pad representation.

    A pad is a connection point on a component footprint. This class
    represents pads in a GENERIC way that works for:
    - Through-hole pads (with drill)
    - SMD pads (no drill)
    - Any shape (circle, rect, oval, etc.)
    - Any size (from tiny 0201 resistors to large connectors)

    Coordinates are ABSOLUTE (not relative to component).

    Attributes:
        number: Pad number/name (e.g., "1", "2", "A1", "GND")
        x_mm: Absolute X position in millimeters
        y_mm: Absolute Y position in millimeters
        width_mm: Pad width in millimeters
        height_mm: Pad height in millimeters
        shape: Pad shape (circle, rect, oval, etc.)
        drill_mm: Drill diameter in mm (0.0 for SMD pads)
        layer: Pad layer (F.Cu, B.Cu, etc.)
        net_name: Net name this pad belongs to (empty for unconnected)

    Example:
        >>> pad = Pad(
        ...     number="1",
        ...     x_mm=10.0,
        ...     y_mm=20.0,
        ...     width_mm=1.5,
        ...     height_mm=1.5,
        ...     shape=PadShape.CIRCLE,
        ...     drill_mm=0.8,
        ...     layer=Layer.F_CU,
        ...     net_name="VCC"
        ... )
    """
    number: str
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    shape: PadShape
    drill_mm: float = 0.0
    layer: Layer = Layer.F_CU
    net_name: str = ""


@dataclass
class Component:
    """
    Format-agnostic component representation.

    Represents a component (resistor, IC, connector, etc.) in a GENERIC way
    that works for ANY component type from ANY EDA format.

    The coordinate system is ABSOLUTE millimeters. Rotation is in degrees
    (0-360, counterclockwise from horizontal right = 0°).

    Attributes:
        reference: Component reference designator (e.g., "R1", "U3", "C42")
        value: Component value (e.g., "10k", "ATmega328", "100nF")
        footprint: Footprint name (e.g., "R_0805", "DIP-8", "SOT-23")
        x_mm: Absolute X position in millimeters (component center)
        y_mm: Absolute Y position in millimeters (component center)
        rotation_deg: Rotation in degrees (0-360, CCW from right)
        side: Component mounting side (top or bottom)
        pads: List of pads belonging to this component

    GENERIC Design:
        - Works for 2-pin resistors to 256-pin ICs
        - No assumptions about footprint format
        - Pads can have ANY number, ANY naming convention
        - Supports through-hole and SMD

    Example:
        >>> component = Component(
        ...     reference="R1",
        ...     value="10k",
        ...     footprint="R_0805",
        ...     x_mm=50.0,
        ...     y_mm=75.0,
        ...     rotation_deg=90.0,
        ...     side=Side.TOP,
        ...     pads=[pad1, pad2]
        ... )
    """
    reference: str
    value: str
    footprint: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    side: Side
    pads: List[Pad] = field(default_factory=list)


@dataclass
class Net:
    """
    Format-agnostic net representation.

    A net is an electrical connection between multiple pads. This class
    represents nets in a GENERIC way that works for ANY circuit complexity.

    Attributes:
        name: Net name (e.g., "VCC", "GND", "NET_1", "SDA")
        pads: List of pads connected to this net as (component_ref, pad_number)

    The pads list uses tuples of (reference, pad_number) to uniquely identify
    each connection point. For example:
        ("R1", "1")  = Pad 1 of R1
        ("U3", "14") = Pad 14 of U3
        ("C5", "2")  = Pad 2 of C5

    GENERIC Design:
        - Works for 2-pad nets (simple resistor) to 100+ pad nets (power/ground)
        - No assumptions about net naming conventions
        - Supports ANY component reference format
        - Supports ANY pad numbering scheme

    Example:
        >>> net_vcc = Net(
        ...     name="VCC",
        ...     pads=[
        ...         ("R1", "1"),
        ...         ("C1", "1"),
        ...         ("U1", "8"),
        ...     ]
        ... )
        >>>
        >>> net_signal = Net(
        ...     name="SDA",
        ...     pads=[("U1", "3"), ("U2", "3")]
        ... )
    """
    name: str
    pads: List[Tuple[str, str]] = field(default_factory=list)


@dataclass
class BoardOutline:
    """
    Format-agnostic board outline representation.

    Represents the physical board edge as a closed polygon. Coordinates
    are in millimeters, forming a closed path.

    Attributes:
        points_mm: List of (x, y) coordinates in millimeters

    The points form a closed polygon. The last point automatically connects
    back to the first point (no need to duplicate first point).

    GENERIC Design:
        - Works for rectangular boards
        - Works for complex shapes (rounded corners, cutouts)
        - No assumptions about board size or shape
        - Minimum 3 points (triangle), no maximum

    Example:
        >>> # Rectangular board 100mm × 50mm
        >>> outline = BoardOutline(points_mm=[
        ...     (0.0, 0.0),
        ...     (100.0, 0.0),
        ...     (100.0, 50.0),
        ...     (0.0, 50.0)
        ... ])
        >>>
        >>> # Complex shape with 8 points
        >>> complex_outline = BoardOutline(points_mm=[
        ...     (0, 0), (50, 0), (60, 10),
        ...     (60, 40), (50, 50), (0, 50),
        ...     (0, 40), (10, 10)
        ... ])
    """
    points_mm: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class DesignRules:
    """
    Format-agnostic PCB design rules.

    Defines manufacturing constraints and design parameters that apply to
    the entire board. These are used by the autorouter to ensure
    manufacturability.

    Attributes:
        trace_width_mm: Default trace width in millimeters
        clearance_mm: Minimum clearance between copper features
        via_drill_mm: Via drill diameter in millimeters
        via_diameter_mm: Via pad diameter in millimeters
        min_hole_to_hole_mm: Minimum hole-to-hole spacing

    GENERIC Design:
        - Works for any fabricator capabilities
        - Values can be adjusted per-project
        - Supports standard and advanced manufacturing

    Typical Values:
        - Standard PCB: trace=0.25mm, clearance=0.2mm
        - Fine-pitch PCB: trace=0.15mm, clearance=0.15mm
        - Power PCB: trace=0.5mm+, clearance=0.3mm+

    Example:
        >>> # JLCPCB 2-layer standard (default - PHASE C.3)
        >>> rules = DesignRules(
        ...     trace_width_mm=0.15,
        ...     clearance_mm=0.15,
        ...     via_drill_mm=0.3,
        ...     via_diameter_mm=0.6,
        ...     min_hole_to_hole_mm=0.4
        ... )
        >>>
        >>> # Conservative PCB rules (tighter tolerances)
        >>> conservative_rules = DesignRules(
        ...     trace_width_mm=0.25,
        ...     clearance_mm=0.2,
        ...     via_drill_mm=0.4,
        ...     via_diameter_mm=0.8,
        ...     min_hole_to_hole_mm=0.5
        ... )
    """
    # GROUP C - TASK C.1 (2025-11-20): Increased trace widths for better routability
    # Professional PCB design: wider traces are easier to route without collisions
    # JLCPCB 2-layer standard profile (conservative for reliable manufacturing)
    # RESTORED (2025-11-20 22:00): Post-revert test proved these changes WORK
    # Forensic data: Removing these caused +365 violations (+12.3% regression)
    trace_width_mm: float = 0.25  # INCREASED from 0.15mm (signal traces)
    power_trace_width_mm: float = 0.4  # RESTORED: Wider traces for power rails (prevents shorts)
    # TC #59 FIX 0.1 (2025-11-27): REDUCED clearance from 0.25mm to 0.15mm
    # ROOT CAUSE: TC #57's 0.25mm clearance was IMPOSSIBLE for 0.5mm pitch ICs
    #   - IPC-7351B: 0.5mm pitch -> 0.3mm pad height -> 0.2mm actual edge-to-edge
    #   - Setting clearance to 0.25mm > 0.2mm actual = ALWAYS FAILS DRC
    # Solution: 0.15mm is compatible with fine-pitch AND above JLCPCB minimum (0.127mm)
    clearance_mm: float = 0.15    # TC #59: REDUCED from 0.25mm for IPC-7351B compatibility
    # TC #57 FIX 1.2 (2025-11-27): Increased via sizes to match working KiCad examples
    via_drill_mm: float = 0.4     # INCREASED from 0.3mm (matches working examples)
    via_diameter_mm: float = 0.8  # INCREASED from 0.6mm (matches working examples)
    min_hole_to_hole_mm: float = 0.5  # INCREASED from 0.4mm (for larger vias)

    # PHASE 12.1 (2025-11-20): RESTORED - Solder mask margin for manufacturability
    # Forensic data: 0.1mm prevented 65 clearance violations
    # PHASE 16 (2025-11-20): INCREASED to 0.2mm for better solder_mask_bridge reduction
    # Target: Reduce solder_mask_bridge from ~1,684 to <500
    solder_mask_margin_mm: float = 0.2  # DOUBLED margin for manufacturing safety

    # PHASE 15.4 (2025-11-23): Enhanced clearance for power nets
    # GENERIC: Extra safety margin for power rails (VCC, GND, etc.)
    # Prevents dangerous VCC-GND shorts
    power_clearance_mm: float = 0.5  # INCREASED clearance for power nets (2.5x signal clearance)


@dataclass
class BoardData:
    """
    Complete format-agnostic PCB board representation.

    This is the TOP-LEVEL data structure that contains all information
    needed to generate a Specctra DSN file and route a PCB.

    The design is COMPLETELY GENERIC and works for:
    - Any EDA format (KiCad, Eagle, EasyEDA, Altium, etc.)
    - Any circuit complexity (2 components to 200+ components)
    - Any layer count (2-layer to multi-layer)
    - Any board size or shape

    Attributes:
        components: List of all components on the board
        nets: List of all electrical nets
        outline: Board physical outline/edge
        design_rules: Manufacturing constraints
        layers: List of copper layers (e.g., ["F.Cu", "B.Cu"])
        board_name: Optional board name for identification

    CONVERSION WORKFLOW:
        1. Converter reads native format (.kicad_pcb, .brd, .json)
        2. Converter extracts data and creates BoardData instance
        3. DSNGenerator converts BoardData → DSN file
        4. Freerouting routes DSN → SES file
        5. SESParser extracts routing → Apply to native format

    GENERIC GUARANTEES:
        ✅ No format-specific fields
        ✅ No hardcoded component types
        ✅ No assumptions about naming conventions
        ✅ Works for ANY valid PCB design
        ✅ Extensible without breaking existing code

    Example:
        >>> board = BoardData(
        ...     components=[r1, r2, c1, u1],  # Any components
        ...     nets=[vcc, gnd, signal1, signal2],  # Any nets
        ...     outline=BoardOutline([...]),
        ...     design_rules=DesignRules(),
        ...     layers=["F.Cu", "B.Cu"],
        ...     board_name="MyCircuit"
        ... )
        >>>
        >>> # Now route it
        >>> from routing import FreeRoutingEngine
        >>> engine = FreeRoutingEngine()
        >>> result = engine.route_board(board)
    """
    components: List[Component] = field(default_factory=list)
    nets: List[Net] = field(default_factory=list)
    outline: BoardOutline = field(default_factory=BoardOutline)
    design_rules: DesignRules = field(default_factory=DesignRules)
    layers: List[str] = field(default_factory=lambda: ["F.Cu", "B.Cu"])
    board_name: str = "untitled"


# VALIDATION HELPERS
# =============================================================================

def validate_board_data(board: BoardData) -> List[str]:
    """
    Validate BoardData for common errors.

    This function performs GENERIC validation checks that apply to ANY
    circuit. It does NOT assume specific component types or net names.

    Args:
        board: BoardData instance to validate

    Returns:
        List of error messages (empty list if valid)

    Validation Checks:
        ✅ At least 2 components
        ✅ At least 1 net
        ✅ All nets have at least 2 pads
        ✅ Board outline has at least 3 points
        ✅ No duplicate component references
        ✅ All pads in nets reference valid components
        ✅ Design rules have positive values

    Example:
        >>> errors = validate_board_data(board)
        >>> if errors:
        ...     for error in errors:
        ...         print(f"ERROR: {error}")
        ... else:
        ...     print("Board data is valid!")
    """
    errors = []

    # Check component count (minimum 2 for a valid circuit)
    if len(board.components) < 2:
        errors.append(f"Too few components: {len(board.components)} (need at least 2)")

    # Check net count (minimum 1 for a valid circuit)
    if len(board.nets) < 1:
        errors.append(f"No nets defined (need at least 1)")

    # Check each net has at least 2 pads (otherwise not a connection)
    for net in board.nets:
        if len(net.pads) < 2:
            errors.append(f"Net '{net.name}' has {len(net.pads)} pads (need at least 2)")

    # Check board outline has at least 3 points (minimum polygon)
    if len(board.outline.points_mm) < 3:
        errors.append(f"Board outline has {len(board.outline.points_mm)} points (need at least 3)")

    # Check for duplicate component references
    refs = [comp.reference for comp in board.components]
    duplicates = [ref for ref in refs if refs.count(ref) > 1]
    if duplicates:
        errors.append(f"Duplicate component references: {set(duplicates)}")

    # Check all pads in nets reference valid components
    component_refs = {comp.reference for comp in board.components}
    for net in board.nets:
        for comp_ref, pad_num in net.pads:
            if comp_ref not in component_refs:
                errors.append(f"Net '{net.name}' references invalid component '{comp_ref}'")

    # Check design rules have positive values
    rules = board.design_rules
    if rules.trace_width_mm <= 0:
        errors.append(f"Invalid trace width: {rules.trace_width_mm} (must be > 0)")
    if rules.clearance_mm <= 0:
        errors.append(f"Invalid clearance: {rules.clearance_mm} (must be > 0)")
    if rules.via_drill_mm <= 0:
        errors.append(f"Invalid via drill: {rules.via_drill_mm} (must be > 0)")
    if rules.via_diameter_mm <= rules.via_drill_mm:
        errors.append(f"Via diameter ({rules.via_diameter_mm}) must be > drill ({rules.via_drill_mm})")

    return errors


# MODULE EXPORTS
# =============================================================================

__all__ = [
    # Enums
    'Layer',
    'PadShape',
    'Side',

    # Data classes
    'Pad',
    'Component',
    'Net',
    'BoardOutline',
    'DesignRules',
    'BoardData',

    # Validation
    'validate_board_data',
]
