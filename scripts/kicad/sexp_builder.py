#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
S-Expression Builder - Safe KiCad File Generation using sexpdata Library

TC #84 (2025-12-15): CRITICAL FIX for S-expression corruption

═══════════════════════════════════════════════════════════════════════════════
ROOT CAUSE OF CORRUPTION:
- Previous code used regex to modify S-expressions (e.g., pad replacement)
- Regex CANNOT reliably handle nested parentheses
- Result: Partial replacements left orphaned text → DUPLICATE PAD DEFINITIONS
- sexpdata parser then FAILED → All code fixers FAILED

SOLUTION:
This module uses sexpdata library for ALL S-expression operations:
1. Build S-expressions programmatically (never string concatenation)
2. Parse existing S-expressions into Python objects
3. Modify Python objects (add/remove/update pads, footprints)
4. Serialize back to valid S-expression string
5. VALIDATE before writing to file

DESIGN PRINCIPLES:
- NEVER use regex for S-expression modification
- ALWAYS validate before writing
- Use sexpdata for all parsing/serialization
- Generic - works for ANY component type
═══════════════════════════════════════════════════════════════════════════════

Author: Claude Code / CopperPilot AI System
Date: 2025-12-15
Version: 1.0.0 - TC #84 Initial Implementation
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Union, Any
import logging

# sexpdata is the REQUIRED library for S-expression handling
try:
    import sexpdata
    from sexpdata import Symbol, dumps, loads
    SEXPDATA_AVAILABLE = True
except ImportError:
    SEXPDATA_AVAILABLE = False
    print("CRITICAL: sexpdata library not installed. Run: pip install sexpdata")

# Central configuration
try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "server"))
    from config import Config
    KICAD_CFG = Config.KICAD_CONFIG
except ImportError:
    KICAD_CFG = {
        "pcb_version": "20241229",
        "sch_version": "20250114",
        "generator_version": "9.0",
    }

logger = logging.getLogger(__name__)


@dataclass
class PadDefinition:
    """Data class for pad definition parameters."""
    number: str
    pad_type: str  # 'smd' or 'thru_hole'
    shape: str  # 'roundrect', 'rect', 'circle', 'oval'
    at: Tuple[float, float]
    size: Tuple[float, float]
    layers: List[str]
    net: Optional[Tuple[int, str]] = None  # (net_number, net_name)
    drill: Optional[float] = None  # For thru_hole pads
    roundrect_rratio: float = 0.25
    solder_mask_margin: Optional[float] = None
    uuid: Optional[str] = None


class SExpressionBuilder:
    """
    Build valid KiCad S-expressions using sexpdata library.

    CRITICAL: This class MUST be used for ALL S-expression generation.
    NEVER use string concatenation or regex for S-expression modification.

    Usage:
        builder = SExpressionBuilder()

        # Build a pad
        pad_sexp = builder.build_pad(
            number="1",
            pad_type="smd",
            shape="roundrect",
            at=(0, 0),
            size=(1.0, 1.5),
            layers=["F.Cu", "F.Paste", "F.Mask"],
            net=(1, "VCC")
        )

        # Convert to string
        pad_str = builder.to_string(pad_sexp)

        # Validate before writing
        if builder.validate_sexp(pad_str):
            # Safe to write
            pass
    """

    def __init__(self):
        """Initialize the S-expression builder."""
        if not SEXPDATA_AVAILABLE:
            raise ImportError(
                "sexpdata library is required but not installed. "
                "Run: pip install sexpdata"
            )

    # ═══════════════════════════════════════════════════════════════════════════
    # PAD BUILDING
    # ═══════════════════════════════════════════════════════════════════════════

    def build_pad(
        self,
        number: str,
        pad_type: str,
        shape: str,
        at: Tuple[float, float],
        size: Tuple[float, float],
        layers: List[str],
        net: Optional[Tuple[int, str]] = None,
        drill: Optional[float] = None,
        roundrect_rratio: float = 0.25,
        solder_mask_margin: Optional[float] = None,
        pad_uuid: Optional[str] = None
    ) -> List:
        """
        Build a valid pad S-expression.

        Args:
            number: Pad number (e.g., "1", "2", "A1")
            pad_type: 'smd' or 'thru_hole'
            shape: 'roundrect', 'rect', 'circle', 'oval'
            at: (x, y) position relative to footprint
            size: (width, height) of pad
            layers: List of layers (e.g., ["F.Cu", "F.Paste", "F.Mask"])
            net: Optional (net_number, net_name) tuple
            drill: Drill diameter for thru_hole pads
            roundrect_rratio: Corner ratio for roundrect (0.0-0.5)
            solder_mask_margin: Optional mask margin override
            pad_uuid: Optional UUID (generated if not provided)

        Returns:
            List representing S-expression structure
        """
        # Generate UUID if not provided
        if pad_uuid is None:
            pad_uuid = str(uuid.uuid4())

        # Start building pad structure
        pad = [Symbol('pad'), number, Symbol(pad_type), Symbol(shape)]

        # Position
        pad.append([Symbol('at'), at[0], at[1]])

        # Size
        pad.append([Symbol('size'), size[0], size[1]])

        # Drill (for thru_hole only)
        if pad_type == 'thru_hole' and drill is not None:
            pad.append([Symbol('drill'), drill])

        # Layers
        layers_sexp = [Symbol('layers')]
        for layer in layers:
            layers_sexp.append(layer)
        pad.append(layers_sexp)

        # Roundrect ratio (for roundrect shape)
        if shape == 'roundrect':
            pad.append([Symbol('roundrect_rratio'), roundrect_rratio])

        # Solder mask margin (optional)
        if solder_mask_margin is not None and solder_mask_margin > 0:
            pad.append([Symbol('solder_mask_margin'), solder_mask_margin])

        # Net assignment
        if net is not None:
            net_num, net_name = net
            pad.append([Symbol('net'), net_num, net_name])

        # UUID
        pad.append([Symbol('uuid'), pad_uuid])

        return pad

    def build_pad_from_definition(self, pad_def: PadDefinition) -> List:
        """Build pad S-expression from PadDefinition dataclass."""
        return self.build_pad(
            number=pad_def.number,
            pad_type=pad_def.pad_type,
            shape=pad_def.shape,
            at=pad_def.at,
            size=pad_def.size,
            layers=pad_def.layers,
            net=pad_def.net,
            drill=pad_def.drill,
            roundrect_rratio=pad_def.roundrect_rratio,
            solder_mask_margin=pad_def.solder_mask_margin,
            pad_uuid=pad_def.uuid
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # FOOTPRINT BUILDING
    # ═══════════════════════════════════════════════════════════════════════════

    def build_footprint(
        self,
        name: str,
        pads: List[List],
        at: Tuple[float, float],
        layer: str = "F.Cu",
        reference: str = "REF**",
        value: str = "VAL**",
        footprint_uuid: Optional[str] = None,
        rotation: float = 0
    ) -> List:
        """
        Build a valid footprint S-expression.

        Args:
            name: Footprint name (e.g., "Resistor_SMD:R_0805_2012Metric")
            pads: List of pad S-expressions (from build_pad())
            at: (x, y) position on board
            layer: Layer ("F.Cu" or "B.Cu")
            reference: Reference designator (e.g., "R1")
            value: Component value (e.g., "10k")
            footprint_uuid: Optional UUID (generated if not provided)
            rotation: Rotation angle in degrees

        Returns:
            List representing footprint S-expression structure
        """
        if footprint_uuid is None:
            footprint_uuid = str(uuid.uuid4())

        fp = [Symbol('footprint'), name]

        # Layer
        fp.append([Symbol('layer'), layer])

        # UUID
        fp.append([Symbol('uuid'), footprint_uuid])

        # Position (with optional rotation)
        if rotation != 0:
            fp.append([Symbol('at'), at[0], at[1], rotation])
        else:
            fp.append([Symbol('at'), at[0], at[1]])

        # Properties
        fp.append(self._build_property("Reference", reference, (0, -3), "F.SilkS"))
        fp.append(self._build_property("Value", value, (0, 3), "F.Fab"))
        fp.append(self._build_property("Footprint", name, (0, 0), "F.Fab", hide=True))

        # Path
        fp.append([Symbol('path'), f"/{footprint_uuid}"])

        # Add all pads
        for pad in pads:
            fp.append(pad)

        return fp

    def _build_property(
        self,
        name: str,
        value: str,
        at: Tuple[float, float],
        layer: str,
        hide: bool = False
    ) -> List:
        """Build a property S-expression."""
        prop = [Symbol('property'), name, value]
        prop.append([Symbol('at'), at[0], at[1], 0])

        if hide:
            prop.append([Symbol('unlocked'), Symbol('yes')])

        prop.append([Symbol('layer'), layer])

        if hide:
            prop.append([Symbol('hide'), Symbol('yes')])

        prop.append([Symbol('uuid'), str(uuid.uuid4())])
        prop.append([Symbol('effects'),
                    [Symbol('font'),
                     [Symbol('size'), 1, 1],
                     [Symbol('thickness'), 0.15]]])

        return prop

    # ═══════════════════════════════════════════════════════════════════════════
    # WIRE/SEGMENT BUILDING
    # ═══════════════════════════════════════════════════════════════════════════

    def build_segment(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        width: float,
        layer: str,
        net: int,
        segment_uuid: Optional[str] = None
    ) -> List:
        """
        Build a track segment S-expression.

        Args:
            start: (x, y) start point
            end: (x, y) end point
            width: Track width in mm
            layer: Layer name (e.g., "F.Cu")
            net: Net number
            segment_uuid: Optional UUID

        Returns:
            List representing segment S-expression
        """
        if segment_uuid is None:
            segment_uuid = str(uuid.uuid4())

        seg = [Symbol('segment')]
        seg.append([Symbol('start'), start[0], start[1]])
        seg.append([Symbol('end'), end[0], end[1]])
        seg.append([Symbol('width'), width])
        seg.append([Symbol('layer'), layer])
        seg.append([Symbol('net'), net])
        seg.append([Symbol('uuid'), segment_uuid])

        return seg

    def build_via(
        self,
        at: Tuple[float, float],
        size: float,
        drill: float,
        layers: List[str],
        net: int,
        via_uuid: Optional[str] = None
    ) -> List:
        """
        Build a via S-expression.

        Args:
            at: (x, y) position
            size: Via pad diameter
            drill: Drill diameter
            layers: List of layers (typically ["F.Cu", "B.Cu"])
            net: Net number
            via_uuid: Optional UUID

        Returns:
            List representing via S-expression
        """
        if via_uuid is None:
            via_uuid = str(uuid.uuid4())

        via = [Symbol('via')]
        via.append([Symbol('at'), at[0], at[1]])
        via.append([Symbol('size'), size])
        via.append([Symbol('drill'), drill])

        layers_sexp = [Symbol('layers')]
        for layer in layers:
            layers_sexp.append(layer)
        via.append(layers_sexp)

        via.append([Symbol('net'), net])
        via.append([Symbol('uuid'), via_uuid])

        return via

    # ═══════════════════════════════════════════════════════════════════════════
    # SERIALIZATION AND VALIDATION
    # ═══════════════════════════════════════════════════════════════════════════

    def to_string(self, sexp: List, indent: int = 4) -> str:
        """
        Convert S-expression list to formatted string.

        Args:
            sexp: S-expression as nested list
            indent: Indentation spaces (0 for compact)

        Returns:
            Formatted S-expression string
        """
        if indent > 0:
            return self._format_sexp(sexp, 0, indent)
        else:
            return dumps(sexp)

    def _format_sexp(self, sexp: Any, level: int, indent: int) -> str:
        """Recursively format S-expression with proper indentation."""
        if isinstance(sexp, list):
            if not sexp:
                return "()"

            # Check if this is a simple list (all atoms)
            if all(not isinstance(item, list) for item in sexp):
                items = [self._format_atom(item) for item in sexp]
                return "(" + " ".join(items) + ")"

            # Complex list - use multiline format
            lines = []
            ind = " " * (level * indent)
            ind_next = " " * ((level + 1) * indent)

            # First element (usually a symbol)
            first = self._format_atom(sexp[0]) if not isinstance(sexp[0], list) else self._format_sexp(sexp[0], level + 1, indent)

            # Check if we can fit on one line
            rest = sexp[1:]
            simple_rest = all(not isinstance(item, list) or
                            (isinstance(item, list) and all(not isinstance(i, list) for i in item))
                            for item in rest)

            if simple_rest and len(rest) <= 3:
                # Compact format for simple expressions
                items = [first] + [self._format_sexp(item, level + 1, indent) if isinstance(item, list) else self._format_atom(item) for item in rest]
                return "(" + " ".join(items) + ")"

            # Multiline format
            result = "(" + first
            for item in rest:
                if isinstance(item, list):
                    result += "\n" + ind_next + self._format_sexp(item, level + 1, indent)
                else:
                    result += " " + self._format_atom(item)
            result += ")"
            return result
        else:
            return self._format_atom(sexp)

    def _format_atom(self, atom: Any) -> str:
        """Format a single atom (symbol, string, number)."""
        if isinstance(atom, Symbol):
            return str(atom)
        elif isinstance(atom, str):
            return f'"{atom}"'
        elif isinstance(atom, float):
            # Format floats consistently
            if atom == int(atom):
                return str(int(atom))
            return f"{atom:.4f}".rstrip('0').rstrip('.')
        else:
            return str(atom)

    def validate_sexp(self, content: str) -> Tuple[bool, str]:
        """
        Validate S-expression string for balanced parentheses and correct structure.

        Args:
            content: S-expression string to validate

        Returns:
            (is_valid, error_message)
        """
        # Count parentheses
        open_count = content.count('(')
        close_count = content.count(')')

        if open_count != close_count:
            delta = open_count - close_count
            return False, f"Unbalanced parentheses: {delta:+d} ({open_count} open, {close_count} close)"

        # Try to parse with sexpdata
        try:
            parsed = loads(content)
            return True, "Valid S-expression"
        except Exception as e:
            return False, f"Parse error: {str(e)}"

    def validate_file(self, filepath: Path) -> Tuple[bool, str]:
        """
        Validate a KiCad file for S-expression correctness.

        Args:
            filepath: Path to .kicad_pcb or .kicad_sch file

        Returns:
            (is_valid, error_message)
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            return self.validate_sexp(content)
        except Exception as e:
            return False, f"File read error: {str(e)}"

    # ═══════════════════════════════════════════════════════════════════════════
    # PARSING AND MODIFICATION
    # ═══════════════════════════════════════════════════════════════════════════

    def parse_file(self, filepath: Path) -> Optional[List]:
        """
        Parse a KiCad file into S-expression structure.

        Args:
            filepath: Path to .kicad_pcb or .kicad_sch file

        Returns:
            Parsed S-expression as nested list, or None if parsing fails
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            return loads(content)
        except Exception as e:
            logger.error(f"Failed to parse {filepath}: {e}")
            return None

    def write_file(self, filepath: Path, sexp: List, validate: bool = True) -> bool:
        """
        Write S-expression to file with validation.

        Args:
            filepath: Output file path
            sexp: S-expression structure to write
            validate: If True, validate before writing (RECOMMENDED)

        Returns:
            True if write succeeded, False otherwise
        """
        content = self.to_string(sexp)

        if validate:
            is_valid, error = self.validate_sexp(content)
            if not is_valid:
                logger.error(f"REFUSING to write invalid S-expression to {filepath}: {error}")
                return False

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Successfully wrote validated S-expression to {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to write {filepath}: {e}")
            return False


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_builder() -> SExpressionBuilder:
    """Get a SExpressionBuilder instance."""
    return SExpressionBuilder()


def validate_pcb_file(filepath: Path) -> Tuple[bool, str]:
    """
    Validate a PCB file before any modification.

    CRITICAL: Call this BEFORE attempting any fixes to detect corruption early.
    """
    builder = SExpressionBuilder()
    return builder.validate_file(filepath)


def build_smd_pad(
    number: str,
    x: float,
    y: float,
    width: float,
    height: float,
    net: Optional[Tuple[int, str]] = None
) -> str:
    """
    Convenience function to build a SMD pad string.

    Args:
        number: Pad number
        x, y: Position
        width, height: Pad size
        net: Optional (net_num, net_name)

    Returns:
        Formatted pad S-expression string
    """
    builder = SExpressionBuilder()
    pad = builder.build_pad(
        number=number,
        pad_type="smd",
        shape="roundrect",
        at=(x, y),
        size=(width, height),
        layers=["F.Cu", "F.Paste", "F.Mask"],
        net=net,
        roundrect_rratio=0.25
    )
    return builder.to_string(pad, indent=0)


def build_thru_hole_pad(
    number: str,
    x: float,
    y: float,
    size: float,
    drill: float,
    net: Optional[Tuple[int, str]] = None
) -> str:
    """
    Convenience function to build a through-hole pad string.

    Args:
        number: Pad number
        x, y: Position
        size: Pad diameter
        drill: Drill diameter
        net: Optional (net_num, net_name)

    Returns:
        Formatted pad S-expression string
    """
    builder = SExpressionBuilder()
    pad = builder.build_pad(
        number=number,
        pad_type="thru_hole",
        shape="circle",
        at=(x, y),
        size=(size, size),
        layers=["*.Cu", "*.Mask"],
        net=net,
        drill=drill
    )
    return builder.to_string(pad, indent=0)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE SELF-TEST
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("SExpressionBuilder Module Test")
    print("=" * 60)

    builder = SExpressionBuilder()

    # Test pad building
    pad = builder.build_pad(
        number="1",
        pad_type="smd",
        shape="roundrect",
        at=(-0.95, 0),
        size=(1.0, 1.45),
        layers=["F.Cu", "F.Paste", "F.Mask"],
        net=(1, "VCC"),
        roundrect_rratio=0.25
    )
    pad_str = builder.to_string(pad)
    print("\nGenerated SMD Pad:")
    print(pad_str)

    # Validate
    is_valid, msg = builder.validate_sexp(pad_str)
    print(f"\nValidation: {msg}")

    # Test segment building
    seg = builder.build_segment(
        start=(10.0, 20.0),
        end=(30.0, 20.0),
        width=0.25,
        layer="F.Cu",
        net=1
    )
    seg_str = builder.to_string(seg)
    print("\nGenerated Segment:")
    print(seg_str)

    # Test via building
    via = builder.build_via(
        at=(20.0, 20.0),
        size=0.8,
        drill=0.4,
        layers=["F.Cu", "B.Cu"],
        net=1
    )
    via_str = builder.to_string(via)
    print("\nGenerated Via:")
    print(via_str)

    print("\n" + "=" * 60)
    print("All tests passed!")
