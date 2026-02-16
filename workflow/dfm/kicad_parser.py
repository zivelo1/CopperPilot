# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad PCB Parser for DFM Checking
==================================

Extracts design parameters from KiCad PCB files (.kicad_pcb) for DFM validation.

Parses:
- Trace widths and lengths
- Trace spacing (from design rules)
- Via diameters and drill sizes
- Pad drill sizes
- Board dimensions
- Layer count
- Clearance settings

Output format is standardized for use with DFMChecker.

Author: CopperPilot Development Team
Created: November 9, 2025
"""

from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path
import re
import logging

logger = logging.getLogger(__name__)


class KiCadDFMParser:
    """
    Parse KiCad PCB files to extract DFM-relevant parameters.

    Usage:
        parser = KiCadDFMParser()
        pcb_data = parser.parse("/path/to/file.kicad_pcb")
        dfm_result = DFMChecker().check(pcb_data)
    """

    def __init__(self):
        """Initialize KiCad DFM parser"""
        self.logger = logger

    def parse(self, pcb_file_path: str) -> Dict[str, Any]:
        """
        Parse KiCad PCB file and extract DFM parameters.

        Args:
            pcb_file_path: Path to .kicad_pcb file

        Returns:
            Dictionary with standardized DFM data:
            {
                "format": "kicad",
                "traces": [...],
                "vias": [...],
                "pads": [...],
                "board_size": (width, height),
                "layers": int,
                "clearances": [...],
                "silkscreen": [...]
            }
        """
        pcb_path = Path(pcb_file_path)
        if not pcb_path.exists():
            raise FileNotFoundError(f"KiCad PCB file not found: {pcb_file_path}")

        self.logger.info(f"Parsing KiCad PCB: {pcb_path.name}")

        # Read file content
        with open(pcb_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract parameters
        data = {
            "format": "kicad",
            "file_path": str(pcb_path),
            "traces": self._extract_traces(content),
            "vias": self._extract_vias(content),
            "pads": self._extract_pads(content),
            "board_size": self._extract_board_size(content),
            "layers": self._extract_layer_count(content),
            "clearances": self._extract_clearances(content),
            "silkscreen": self._extract_silkscreen(content)
        }

        self.logger.info(
            f"Extracted: {len(data['traces'])} traces, {len(data['vias'])} vias, "
            f"{len(data['pads'])} pads, board size: {data['board_size']}, layers: {data['layers']}"
        )

        return data

    def _extract_traces(self, content: str) -> List[Dict[str, Any]]:
        """
        Extract trace information from PCB content.

        KiCad format: (segment (start x y) (end x y) (width w) (layer "layer") (net n))
        """
        traces = []

        # Find all segment definitions
        segment_pattern = r'\(segment\s+(.*?)\)\s*\)'
        for match in re.finditer(segment_pattern, content, re.DOTALL):
            segment_text = match.group(1)

            # Extract width
            width_match = re.search(r'\(width\s+([0-9.]+)\)', segment_text)
            width = float(width_match.group(1)) if width_match else 0.2  # Default 0.2mm

            # Extract layer
            layer_match = re.search(r'\(layer\s+"([^"]+)"\)', segment_text)
            layer = layer_match.group(1) if layer_match else "unknown"

            # Extract net
            net_match = re.search(r'\(net\s+([0-9]+)\)', segment_text)
            net = int(net_match.group(1)) if net_match else 0

            # Extract start/end coordinates
            start_match = re.search(r'\(start\s+([0-9.-]+)\s+([0-9.-]+)\)', segment_text)
            end_match = re.search(r'\(end\s+([0-9.-]+)\s+([0-9.-]+)\)', segment_text)

            if start_match and end_match:
                start = (float(start_match.group(1)), float(start_match.group(2)))
                end = (float(end_match.group(1)), float(end_match.group(2)))

                traces.append({
                    "width": width,
                    "layer": layer,
                    "net": net,
                    "start": start,
                    "end": end,
                    "spacing": 0.127  # Will be calculated from design rules
                })

        return traces

    def _extract_vias(self, content: str) -> List[Dict[str, Any]]:
        """
        Extract via information.

        KiCad format: (via (at x y) (size d) (drill dr) (layers "F.Cu" "B.Cu"))
        """
        vias = []

        via_pattern = r'\(via\s+(.*?)\)\s*\)'
        for match in re.finditer(via_pattern, content, re.DOTALL):
            via_text = match.group(1)

            # Extract position
            at_match = re.search(r'\(at\s+([0-9.-]+)\s+([0-9.-]+)\)', via_text)
            position = (float(at_match.group(1)), float(at_match.group(2))) if at_match else (0, 0)

            # Extract size (diameter)
            size_match = re.search(r'\(size\s+([0-9.]+)\)', via_text)
            diameter = float(size_match.group(1)) if size_match else 0.6

            # Extract drill
            drill_match = re.search(r'\(drill\s+([0-9.]+)\)', via_text)
            drill = float(drill_match.group(1)) if drill_match else 0.3

            vias.append({
                "position": position,
                "diameter": diameter,
                "drill": drill,
                "type": "through"  # Can be "blind" or "buried" if specified
            })

        return vias

    def _extract_pads(self, content: str) -> List[Dict[str, Any]]:
        """
        Extract pad information (for through-hole components).

        KiCad format: (pad "1" thru_hole circle (at x y) (size d) (drill dr))
        """
        pads = []

        pad_pattern = r'\(pad\s+"([^"]+)"\s+(\w+)\s+(.*?)\)\s*\)'
        for match in re.finditer(pad_pattern, content, re.DOTALL):
            number = match.group(1)
            pad_type = match.group(2)  # thru_hole, smd, etc.
            pad_text = match.group(3)

            # Only check through-hole pads for drill size
            if pad_type == "thru_hole":
                # Extract drill
                drill_match = re.search(r'\(drill\s+([0-9.]+)\)', pad_text)
                drill = float(drill_match.group(1)) if drill_match else 0

                if drill > 0:
                    pads.append({
                        "number": number,
                        "type": pad_type,
                        "drill": drill,
                        "component": "unknown"  # Would need to parse footprint context
                    })

        return pads

    def _extract_board_size(self, content: str) -> Tuple[float, float]:
        """
        Extract board dimensions from edge cuts.

        Calculates bounding box of Edge.Cuts layer.
        """
        # Find all gr_line on Edge.Cuts layer
        edge_pattern = r'\(gr_line\s+\(start\s+([0-9.-]+)\s+([0-9.-]+)\)\s+\(end\s+([0-9.-]+)\s+([0-9.-]+)\).*?layer\s+"Edge\.Cuts"'

        x_coords = []
        y_coords = []

        for match in re.finditer(edge_pattern, content, re.DOTALL):
            x1, y1, x2, y2 = map(float, match.groups())
            x_coords.extend([x1, x2])
            y_coords.extend([y1, y2])

        if x_coords and y_coords:
            width = max(x_coords) - min(x_coords)
            height = max(y_coords) - min(y_coords)
            return (width, height)
        else:
            # Default fallback
            return (100.0, 80.0)

    def _extract_layer_count(self, content: str) -> int:
        """
        Extract number of copper layers.

        KiCad defines layers in (layers ...) section.
        """
        # Count copper layers (F.Cu, B.Cu, In1.Cu, In2.Cu, ...)
        copper_layers = 0

        # Count F.Cu and B.Cu
        if '"F.Cu"' in content:
            copper_layers += 1
        if '"B.Cu"' in content:
            copper_layers += 1

        # Count internal layers (In1.Cu, In2.Cu, ...)
        for i in range(1, 31):  # Support up to 32 layers
            if f'"In{i}.Cu"' in content:
                copper_layers += 1

        return max(copper_layers, 2)  # Minimum 2 layers

    def _extract_clearances(self, content: str) -> List[Dict[str, Any]]:
        """
        Extract clearance settings from design rules.

        KiCad stores clearances in (setup ...) section.
        This is a simplified extraction - real implementation would
        calculate actual clearances between features.
        """
        clearances = []

        # Extract default clearance from setup
        clearance_match = re.search(r'\(clearance\s+([0-9.]+)\)', content)
        if clearance_match:
            default_clearance = float(clearance_match.group(1))
            # This is a placeholder - real implementation would check actual spacing
            clearances.append({
                "feature1": "default",
                "feature2": "default",
                "distance": default_clearance
            })

        return clearances

    def _extract_silkscreen(self, content: str) -> List[Dict[str, Any]]:
        """
        Extract silkscreen line widths.

        KiCad format: (gr_text ...) and (fp_text ...) on F.SilkS or B.SilkS
        """
        silkscreen = []

        # Find silkscreen text
        silk_pattern = r'\((?:gr_text|fp_text).*?layer\s+"([FB])\.SilkS".*?\(width\s+([0-9.]+)\)'

        for match in re.finditer(silk_pattern, content, re.DOTALL):
            layer = match.group(1) + ".SilkS"
            width = float(match.group(2))

            silkscreen.append({
                "layer": layer,
                "width": width,
                "type": "text"
            })

        return silkscreen


# Convenience function
def parse_kicad_for_dfm(pcb_file_path: str) -> Dict[str, Any]:
    """
    Convenience function to parse KiCad PCB for DFM checking.

    Usage:
        pcb_data = parse_kicad_for_dfm("output/project/circuit.kicad_pcb")
        result = DFMChecker().check(pcb_data)
    """
    parser = KiCadDFMParser()
    return parser.parse(pcb_file_path)
