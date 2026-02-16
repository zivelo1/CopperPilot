# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Footprint Library Loader
==============================

GENERIC: Load footprint definitions from KiCad's official libraries.
Uses the EXACT same footprint files that KiCad uses.
NO GUESSING - just copying what KiCad would use.

This module parses KiCad's .kicad_mod files (S-Expression format) and extracts:
- Pad definitions (positions, sizes, shapes, drill, layers)
- Silkscreen graphics (F.SilkS)
- Courtyard graphics (F.CrtYd)
- Fabrication layer graphics (F.Fab)
- 3D model references

Author: Claude Code
Date: 2025-11-27
Version: 1.0.0
Test Cycle: TC #60 - ARCHITECTURAL FIX
"""

import re
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, NamedTuple
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PadType(Enum):
    """Pad type enumeration matching KiCad."""
    SMD = "smd"
    THRU_HOLE = "thru_hole"
    CONNECT = "connect"  # Test point / mechanical
    NPTH = "np_thru_hole"  # Non-plated through hole


class PadShape(Enum):
    """Pad shape enumeration matching KiCad."""
    CIRCLE = "circle"
    RECT = "rect"
    OVAL = "oval"
    ROUNDRECT = "roundrect"
    TRAPEZOID = "trapezoid"
    CUSTOM = "custom"


@dataclass
class LibraryPad:
    """
    Complete pad definition from KiCad library.

    EXACT copy of what KiCad uses - no guessing, no calculation.
    """
    number: str
    pad_type: PadType
    shape: PadShape
    x: float  # Relative X position (mm)
    y: float  # Relative Y position (mm)
    width: float  # Size width (mm)
    height: float  # Size height (mm)
    layers: List[str] = field(default_factory=list)
    drill: float = 0.0  # Drill diameter (mm), 0 for SMD
    drill_offset_x: float = 0.0
    drill_offset_y: float = 0.0
    roundrect_rratio: float = 0.25  # For roundrect pads
    rotation: float = 0.0  # Pad rotation (degrees)

    def to_kicad_format(self, pad_x: float = None, pad_y: float = None,
                        net_index: int = 0, net_name: str = "") -> str:
        """
        Generate KiCad S-Expression for this pad.

        Args:
            pad_x: Override X position (absolute)
            pad_y: Override Y position (absolute)
            net_index: Net index for connectivity
            net_name: Net name for connectivity

        Returns:
            KiCad S-Expression string for the pad
        """
        x = pad_x if pad_x is not None else self.x
        y = pad_y if pad_y is not None else self.y

        lines = []

        # Pad header
        lines.append(f'    (pad "{self.number}" {self.pad_type.value} {self.shape.value}')

        # Position with optional rotation
        if self.rotation != 0:
            lines.append(f'      (at {x:.6g} {y:.6g} {self.rotation})')
        else:
            lines.append(f'      (at {x:.6g} {y:.6g})')

        # Size
        lines.append(f'      (size {self.width:.6g} {self.height:.6g})')

        # Drill for through-hole
        if self.drill > 0:
            if self.drill_offset_x != 0 or self.drill_offset_y != 0:
                lines.append(f'      (drill {self.drill:.6g} (offset {self.drill_offset_x:.6g} {self.drill_offset_y:.6g}))')
            else:
                lines.append(f'      (drill {self.drill:.6g})')

        # Layers
        if self.layers:
            layer_str = ' '.join(f'"{l}"' for l in self.layers)
            lines.append(f'      (layers {layer_str})')

        # Roundrect ratio for roundrect pads
        if self.shape == PadShape.ROUNDRECT:
            lines.append(f'      (roundrect_rratio {self.roundrect_rratio:.6g})')

        # Net connectivity (if provided)
        if net_index > 0 and net_name:
            lines.append(f'      (net {net_index} "{net_name}")')

        lines.append('    )')

        return '\n'.join(lines)


@dataclass
class GraphicLine:
    """Line graphic element from footprint."""
    start_x: float
    start_y: float
    end_x: float
    end_y: float
    width: float
    layer: str


@dataclass
class GraphicPoly:
    """Polygon graphic element from footprint."""
    points: List[Tuple[float, float]]
    width: float
    layer: str
    fill: bool = False


@dataclass
class FootprintData:
    """
    Complete footprint definition from KiCad library.

    Contains ALL data needed to create an exact copy of the footprint.
    """
    name: str
    description: str = ""
    tags: str = ""
    attr: str = "smd"  # smd, through_hole
    layer: str = "F.Cu"
    pads: List[LibraryPad] = field(default_factory=list)
    silkscreen_lines: List[GraphicLine] = field(default_factory=list)
    silkscreen_polys: List[GraphicPoly] = field(default_factory=list)
    courtyard_lines: List[GraphicLine] = field(default_factory=list)
    fab_lines: List[GraphicLine] = field(default_factory=list)
    model_path: str = ""

    def get_pad_by_number(self, number: str) -> Optional[LibraryPad]:
        """Get pad by its number/name."""
        for pad in self.pads:
            if pad.number == number:
                return pad
        return None

    def get_pin_count(self) -> int:
        """Get total number of pads."""
        return len(self.pads)

    def get_bounding_box(self) -> Tuple[float, float, float, float]:
        """
        Get bounding box of all pads.

        Returns:
            (min_x, min_y, max_x, max_y) in mm
        """
        if not self.pads:
            return (0, 0, 0, 0)

        min_x = min(p.x - p.width/2 for p in self.pads)
        max_x = max(p.x + p.width/2 for p in self.pads)
        min_y = min(p.y - p.height/2 for p in self.pads)
        max_y = max(p.y + p.height/2 for p in self.pads)

        return (min_x, min_y, max_x, max_y)


class KiCadFootprintLoader:
    """
    GENERIC: Load footprint definitions from KiCad's official libraries.

    Uses the EXACT same footprint files that KiCad uses.
    NO GUESSING - just copying what KiCad would use.

    Usage:
        loader = KiCadFootprintLoader()
        fp = loader.load_footprint("Package_SO:SOIC-14_3.9x8.7mm_P1.27mm")
        for pad in fp.pads:
            print(f"Pad {pad.number}: {pad.width}x{pad.height}mm at ({pad.x}, {pad.y})")
    """

    # Default KiCad footprint library paths
    DEFAULT_LIBRARY_PATHS = [
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"),  # macOS
        Path("/usr/share/kicad/footprints"),  # Linux
        Path("C:/Program Files/KiCad/share/kicad/footprints"),  # Windows
    ]

    def __init__(self, library_paths: List[Path] = None):
        """
        Initialize with paths to .pretty directories.

        Args:
            library_paths: List of paths to search for footprint libraries.
                          If None, uses default KiCad installation paths.
        """
        if library_paths is None:
            # Find first valid default path
            self.library_paths = []
            for path in self.DEFAULT_LIBRARY_PATHS:
                if path.exists():
                    self.library_paths.append(path)
                    logger.info(f"Found KiCad footprint library at: {path}")
                    break

            if not self.library_paths:
                logger.warning("No default KiCad footprint library found!")
        else:
            self.library_paths = library_paths

        # Cache for loaded footprints
        self.footprint_cache: Dict[str, FootprintData] = {}

        # Index of available footprints (lazy loaded)
        self._library_index: Dict[str, Path] = {}
        self._index_built = False

    def _build_library_index(self):
        """Build index of all available footprints."""
        if self._index_built:
            return

        for lib_path in self.library_paths:
            if not lib_path.exists():
                continue

            # Each .pretty directory is a library
            for pretty_dir in lib_path.glob("*.pretty"):
                library_name = pretty_dir.stem  # e.g., "Package_SO"

                # Index all .kicad_mod files
                for fp_file in pretty_dir.glob("*.kicad_mod"):
                    fp_name = fp_file.stem  # e.g., "SOIC-14_3.9x8.7mm_P1.27mm"
                    full_name = f"{library_name}:{fp_name}"
                    self._library_index[full_name] = fp_file

                    # Also index by short name for convenience
                    if fp_name not in self._library_index:
                        self._library_index[fp_name] = fp_file

        self._index_built = True
        logger.info(f"Indexed {len(self._library_index)} footprints")

    def load_footprint(self, footprint_name: str) -> Optional[FootprintData]:
        """
        Load complete footprint definition from library.

        Args:
            footprint_name: Either "Library:Footprint" or just "Footprint"
                           e.g., "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm"
                           or "SOIC-14_3.9x8.7mm_P1.27mm"

        Returns:
            FootprintData with EXACT pads, outlines, silkscreen, courtyard
            None if footprint not found
        """
        # Check cache first
        if footprint_name in self.footprint_cache:
            return self.footprint_cache[footprint_name]

        # Build index if needed
        self._build_library_index()

        # Find footprint file
        fp_path = self._find_footprint_file(footprint_name)
        if fp_path is None:
            logger.warning(f"Footprint not found: {footprint_name}")
            return None

        # Parse the .kicad_mod file
        fp_data = self._parse_kicad_mod(fp_path)

        # Cache it
        if fp_data:
            self.footprint_cache[footprint_name] = fp_data

        return fp_data

    def _find_footprint_file(self, footprint_name: str) -> Optional[Path]:
        """
        Find footprint file by name.

        Args:
            footprint_name: Either "Library:Footprint" or just "Footprint"

        Returns:
            Path to .kicad_mod file, or None if not found
        """
        # Try exact match first
        if footprint_name in self._library_index:
            return self._library_index[footprint_name]

        # Try with library prefix
        if ":" in footprint_name:
            library, fp_name = footprint_name.split(":", 1)

            # Look in specific library
            for lib_path in self.library_paths:
                pretty_dir = lib_path / f"{library}.pretty"
                if pretty_dir.exists():
                    fp_file = pretty_dir / f"{fp_name}.kicad_mod"
                    if fp_file.exists():
                        return fp_file

        # Try to find by partial match (for generic footprint names)
        search_name = footprint_name.split(":")[-1] if ":" in footprint_name else footprint_name

        for full_name, fp_path in self._library_index.items():
            if search_name in full_name:
                return fp_path

        return None

    def _parse_kicad_mod(self, fp_path: Path) -> Optional[FootprintData]:
        """
        Parse .kicad_mod file and extract all geometry.

        Args:
            fp_path: Path to .kicad_mod file

        Returns:
            FootprintData with complete footprint definition
        """
        try:
            content = fp_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"Failed to read {fp_path}: {e}")
            return None

        # Extract footprint name
        name_match = re.search(r'\(footprint\s+"([^"]+)"', content)
        name = name_match.group(1) if name_match else fp_path.stem

        # Extract description
        descr_match = re.search(r'\(descr\s+"([^"]+)"\)', content)
        description = descr_match.group(1) if descr_match else ""

        # Extract tags
        tags_match = re.search(r'\(tags\s+"([^"]+)"\)', content)
        tags = tags_match.group(1) if tags_match else ""

        # Extract attribute (smd, through_hole)
        attr_match = re.search(r'\(attr\s+(\w+)\)', content)
        attr = attr_match.group(1) if attr_match else "smd"

        # Extract layer
        layer_match = re.search(r'\(layer\s+"([^"]+)"\)', content)
        layer = layer_match.group(1) if layer_match else "F.Cu"

        # Parse pads
        pads = self._parse_pads(content)

        # Parse graphics (silkscreen, courtyard, fab)
        silkscreen_lines = self._parse_graphic_lines(content, "F.SilkS")
        silkscreen_polys = self._parse_graphic_polys(content, "F.SilkS")
        courtyard_lines = self._parse_graphic_lines(content, "F.CrtYd")
        fab_lines = self._parse_graphic_lines(content, "F.Fab")

        # Extract 3D model path
        model_match = re.search(r'\(model\s+"([^"]+)"', content)
        model_path = model_match.group(1) if model_match else ""

        return FootprintData(
            name=name,
            description=description,
            tags=tags,
            attr=attr,
            layer=layer,
            pads=pads,
            silkscreen_lines=silkscreen_lines,
            silkscreen_polys=silkscreen_polys,
            courtyard_lines=courtyard_lines,
            fab_lines=fab_lines,
            model_path=model_path
        )

    def _parse_pads(self, content: str) -> List[LibraryPad]:
        """
        Parse all pad definitions from footprint content.

        GENERIC: Works for ANY pad configuration.
        """
        pads = []

        # Pattern for pad blocks - captures full pad definition
        # Example: (pad "1" smd roundrect (at -2.475 -3.81) (size 1.95 0.6) (layers "F.Cu" "F.Mask" "F.Paste") (roundrect_rratio 0.25))
        pad_pattern = r'\(pad\s+"([^"]+)"\s+(\w+)\s+(\w+)\s*(.*?)\n\s*\)'

        for match in re.finditer(pad_pattern, content, re.DOTALL):
            pad_number = match.group(1)
            pad_type_str = match.group(2)
            shape_str = match.group(3)
            pad_content = match.group(4)

            # Parse pad type
            pad_type_map = {
                'smd': PadType.SMD,
                'thru_hole': PadType.THRU_HOLE,
                'connect': PadType.CONNECT,
                'np_thru_hole': PadType.NPTH,
            }
            pad_type = pad_type_map.get(pad_type_str, PadType.SMD)

            # Parse shape
            shape_map = {
                'circle': PadShape.CIRCLE,
                'rect': PadShape.RECT,
                'oval': PadShape.OVAL,
                'roundrect': PadShape.ROUNDRECT,
                'trapezoid': PadShape.TRAPEZOID,
                'custom': PadShape.CUSTOM,
            }
            shape = shape_map.get(shape_str, PadShape.ROUNDRECT)

            # Parse position
            at_match = re.search(r'\(at\s+([\d.\-]+)\s+([\d.\-]+)(?:\s+([\d.\-]+))?\)', pad_content)
            x = float(at_match.group(1)) if at_match else 0.0
            y = float(at_match.group(2)) if at_match else 0.0
            rotation = float(at_match.group(3)) if at_match and at_match.group(3) else 0.0

            # Parse size
            size_match = re.search(r'\(size\s+([\d.\-]+)\s+([\d.\-]+)\)', pad_content)
            width = float(size_match.group(1)) if size_match else 1.0
            height = float(size_match.group(2)) if size_match else 1.0

            # Parse drill (for through-hole)
            drill = 0.0
            drill_offset_x = 0.0
            drill_offset_y = 0.0
            drill_match = re.search(r'\(drill\s+([\d.\-]+)(?:\s+\(offset\s+([\d.\-]+)\s+([\d.\-]+)\))?\)', pad_content)
            if drill_match:
                drill = float(drill_match.group(1))
                if drill_match.group(2):
                    drill_offset_x = float(drill_match.group(2))
                    drill_offset_y = float(drill_match.group(3))

            # Parse layers
            layers = []
            layers_match = re.search(r'\(layers\s+(.*?)\)', pad_content)
            if layers_match:
                layer_str = layers_match.group(1)
                # Extract quoted layer names
                layers = re.findall(r'"([^"]+)"', layer_str)
                # Handle unquoted wildcards like *.Cu
                if not layers:
                    layers = layer_str.split()

            # Parse roundrect ratio
            rratio_match = re.search(r'\(roundrect_rratio\s+([\d.\-]+)\)', pad_content)
            roundrect_rratio = float(rratio_match.group(1)) if rratio_match else 0.25

            pad = LibraryPad(
                number=pad_number,
                pad_type=pad_type,
                shape=shape,
                x=x,
                y=y,
                width=width,
                height=height,
                layers=layers,
                drill=drill,
                drill_offset_x=drill_offset_x,
                drill_offset_y=drill_offset_y,
                roundrect_rratio=roundrect_rratio,
                rotation=rotation
            )

            pads.append(pad)

        return pads

    def _parse_graphic_lines(self, content: str, layer: str) -> List[GraphicLine]:
        """
        Parse graphic lines (fp_line) for a specific layer.

        GENERIC: Works for silkscreen, courtyard, fab layer.
        """
        lines = []

        # Pattern for fp_line
        line_pattern = rf'\(fp_line\s+\(start\s+([\d.\-]+)\s+([\d.\-]+)\)\s+\(end\s+([\d.\-]+)\s+([\d.\-]+)\).*?\(layer\s+"{layer}"\)'

        for match in re.finditer(line_pattern, content, re.DOTALL):
            start_x = float(match.group(1))
            start_y = float(match.group(2))
            end_x = float(match.group(3))
            end_y = float(match.group(4))

            # Extract width from stroke
            width_match = re.search(r'\(width\s+([\d.\-]+)\)', match.group(0))
            width = float(width_match.group(1)) if width_match else 0.12

            lines.append(GraphicLine(
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
                width=width,
                layer=layer
            ))

        return lines

    def _parse_graphic_polys(self, content: str, layer: str) -> List[GraphicPoly]:
        """
        Parse graphic polygons (fp_poly) for a specific layer.

        GENERIC: Works for any polygon graphics.
        """
        polys = []

        # Pattern for fp_poly
        poly_pattern = rf'\(fp_poly\s+\(pts(.*?)\).*?\(layer\s+"{layer}"\)'

        for match in re.finditer(poly_pattern, content, re.DOTALL):
            pts_content = match.group(1)

            # Extract points
            points = []
            for pt_match in re.finditer(r'\(xy\s+([\d.\-]+)\s+([\d.\-]+)\)', pts_content):
                x = float(pt_match.group(1))
                y = float(pt_match.group(2))
                points.append((x, y))

            if points:
                # Extract width
                width_match = re.search(r'\(width\s+([\d.\-]+)\)', match.group(0))
                width = float(width_match.group(1)) if width_match else 0.12

                # Check fill
                fill = 'fill yes' in match.group(0) or 'fill solid' in match.group(0)

                polys.append(GraphicPoly(
                    points=points,
                    width=width,
                    layer=layer,
                    fill=fill
                ))

        return polys

    def find_matching_footprint(self, generic_name: str, pin_count: int = None) -> Optional[FootprintData]:
        """
        Find a footprint that matches a generic name like "SOIC-14" or "R_0805".

        This is a SMART matcher that understands common footprint naming conventions.

        Args:
            generic_name: Generic footprint name (e.g., "SOIC-14", "R_0805", "QFP-44")
            pin_count: Optional pin count to help narrow search

        Returns:
            Best matching FootprintData, or None if not found
        """
        self._build_library_index()

        # Normalize name
        search = generic_name.upper()

        # Build search patterns
        patterns = [generic_name]

        # Add common variations
        if search.startswith("SOIC-") or search.startswith("SOIC_"):
            # SOIC packages
            pins = search.split("-")[-1].split("_")[0]
            patterns.extend([
                f"SOIC-{pins}_",
                f"SO-{pins}_",
            ])
        elif search.startswith("QFP") or search.startswith("TQFP") or search.startswith("LQFP"):
            # QFP packages
            pins = re.search(r'(\d+)', search)
            if pins:
                patterns.extend([
                    f"QFP-{pins.group(1)}_",
                    f"TQFP-{pins.group(1)}_",
                    f"LQFP-{pins.group(1)}_",
                ])
        elif search.startswith("R_") or search.startswith("R0"):
            # Resistors
            size = re.search(r'(\d{4})', search)
            if size:
                patterns.extend([
                    f"R_{size.group(1)}_",
                    f"R_{size.group(1)}Metric",
                ])
        elif search.startswith("C_") or search.startswith("C0"):
            # Capacitors
            size = re.search(r'(\d{4})', search)
            if size:
                patterns.extend([
                    f"C_{size.group(1)}_",
                    f"C_{size.group(1)}Metric",
                ])

        # Search for matches
        best_match = None
        best_score = 0

        for full_name, fp_path in self._library_index.items():
            for pattern in patterns:
                if pattern.lower() in full_name.lower():
                    # Score based on exact match quality
                    score = len(pattern)

                    # Bonus for pin count match
                    if pin_count is not None:
                        if f"-{pin_count}_" in full_name or f"-{pin_count}." in full_name:
                            score += 100

                    # Bonus for shorter names (prefer standard variants)
                    score -= len(full_name) / 100

                    if score > best_score:
                        best_score = score
                        best_match = full_name

        if best_match:
            return self.load_footprint(best_match)

        return None

    def get_available_libraries(self) -> List[str]:
        """Get list of all available footprint libraries."""
        self._build_library_index()

        libraries = set()
        for full_name in self._library_index.keys():
            if ":" in full_name:
                lib = full_name.split(":")[0]
                libraries.add(lib)

        return sorted(libraries)

    def get_footprints_in_library(self, library_name: str) -> List[str]:
        """Get list of all footprints in a specific library."""
        self._build_library_index()

        footprints = []
        prefix = f"{library_name}:"
        for full_name in self._library_index.keys():
            if full_name.startswith(prefix):
                footprints.append(full_name)

        return sorted(footprints)


# Convenience function for quick access
_global_loader: Optional[KiCadFootprintLoader] = None

def get_footprint_loader() -> KiCadFootprintLoader:
    """
    Get the global footprint loader instance.

    Creates a singleton loader on first call for efficiency.
    """
    global _global_loader
    if _global_loader is None:
        _global_loader = KiCadFootprintLoader()
    return _global_loader


def load_kicad_footprint(footprint_name: str) -> Optional[FootprintData]:
    """
    Convenience function to load a footprint.

    Args:
        footprint_name: Either "Library:Footprint" or just "Footprint"

    Returns:
        FootprintData or None
    """
    return get_footprint_loader().load_footprint(footprint_name)


def find_footprint(generic_name: str, pin_count: int = None) -> Optional[FootprintData]:
    """
    Convenience function to find a matching footprint.

    Args:
        generic_name: Generic name like "SOIC-14" or "R_0805"
        pin_count: Optional pin count

    Returns:
        Best matching FootprintData or None
    """
    return get_footprint_loader().find_matching_footprint(generic_name, pin_count)


__all__ = [
    'PadType',
    'PadShape',
    'LibraryPad',
    'GraphicLine',
    'GraphicPoly',
    'FootprintData',
    'KiCadFootprintLoader',
    'get_footprint_loader',
    'load_kicad_footprint',
    'find_footprint',
]
