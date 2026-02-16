# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle PCB Parser for DFM Checking
==================================

Extracts design parameters from Eagle board files (.brd) for DFM validation.

Eagle uses XML format, making parsing straightforward with element tree.

Parses:
- Trace widths (wire elements on copper layers)
- Via diameters and drill sizes
- Pad drill sizes
- Board dimensions (from wire elements on dimension layer)
- Layer count
- Clearance settings (from design rules)

Output format is standardized for use with DFMChecker.

Author: CopperPilot Development Team
Created: November 9, 2025
"""

from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path
import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger(__name__)


class EagleDFMParser:
    """
    Parse Eagle board files to extract DFM-relevant parameters.

    Usage:
        parser = EagleDFMParser()
        pcb_data = parser.parse("/path/to/file.brd")
        dfm_result = DFMChecker().check(pcb_data)
    """

    # Eagle layer definitions
    COPPER_LAYERS = {
        1: "Top",
        2: "Route2",
        3: "Route3",
        # ... up to 16
        16: "Bottom"
    }

    def __init__(self):
        """Initialize Eagle DFM parser"""
        self.logger = logger

    def parse(self, brd_file_path: str) -> Dict[str, Any]:
        """
        Parse Eagle board file and extract DFM parameters.

        Args:
            brd_file_path: Path to .brd file

        Returns:
            Dictionary with standardized DFM data
        """
        brd_path = Path(brd_file_path)
        if not brd_path.exists():
            raise FileNotFoundError(f"Eagle board file not found: {brd_file_path}")

        self.logger.info(f"Parsing Eagle board: {brd_path.name}")

        # Parse XML
        tree = ET.parse(brd_path)
        root = tree.getroot()

        # Eagle boards have structure: <eagle><drawing><board>
        board = root.find('.//board')
        if board is None:
            raise ValueError(f"Invalid Eagle board file: {brd_file_path}")

        # Extract parameters
        data = {
            "format": "eagle",
            "file_path": str(brd_path),
            "traces": self._extract_traces(board),
            "vias": self._extract_vias(board),
            "pads": self._extract_pads(board),
            "board_size": self._extract_board_size(board),
            "layers": self._extract_layer_count(board),
            "clearances": self._extract_clearances(board),
            "silkscreen": self._extract_silkscreen(board)
        }

        self.logger.info(
            f"Extracted: {len(data['traces'])} traces, {len(data['vias'])} vias, "
            f"{len(data['pads'])} pads, board size: {data['board_size']}, layers: {data['layers']}"
        )

        return data

    def _extract_traces(self, board: ET.Element) -> List[Dict[str, Any]]:
        """
        Extract trace information (wire elements on copper layers).

        Eagle format: <wire x1="" y1="" x2="" y2="" width="" layer=""/>
        """
        traces = []

        # Find all signals (routed nets)
        signals = board.find('signals')
        if signals is not None:
            for signal in signals.findall('signal'):
                signal_name = signal.get('name', 'unknown')

                # Find wire elements
                for wire in signal.findall('wire'):
                    layer_num = int(wire.get('layer', '0'))

                    # Check if it's a copper layer (1-16)
                    if 1 <= layer_num <= 16:
                        width = float(wire.get('width', '0.2'))
                        x1 = float(wire.get('x1', '0'))
                        y1 = float(wire.get('y1', '0'))
                        x2 = float(wire.get('x2', '0'))
                        y2 = float(wire.get('y2', '0'))

                        traces.append({
                            "width": width,
                            "layer": self.COPPER_LAYERS.get(layer_num, f"Layer{layer_num}"),
                            "net": signal_name,
                            "start": (x1, y1),
                            "end": (x2, y2),
                            "spacing": 0.127  # Will be extracted from design rules
                        })

        return traces

    def _extract_vias(self, board: ET.Element) -> List[Dict[str, Any]]:
        """
        Extract via information.

        Eagle format: <via x="" y="" extent="" drill=""/>
        """
        vias = []

        signals = board.find('signals')
        if signals is not None:
            for signal in signals.findall('signal'):
                for via in signal.findall('via'):
                    x = float(via.get('x', '0'))
                    y = float(via.get('y', '0'))
                    drill = float(via.get('drill', '0.3'))

                    # Via diameter is typically drill + 2 * annular ring
                    # Eagle uses 'extent' to define layer span, not diameter
                    # Assume standard: diameter = drill + 0.26mm (0.13mm ring on each side)
                    diameter = drill + 0.26

                    vias.append({
                        "position": (x, y),
                        "diameter": diameter,
                        "drill": drill,
                        "type": "through"
                    })

        return vias

    def _extract_pads(self, board: ET.Element) -> List[Dict[str, Any]]:
        """
        Extract pad information (through-hole pads).

        Eagle format: <element><package><pad name="" x="" y="" drill=""/>
        """
        pads = []

        elements = board.find('elements')
        if elements is not None:
            for element in elements.findall('element'):
                element_name = element.get('name', 'unknown')

                # Find pads in element
                for pad in element.findall('.//pad'):
                    pad_name = pad.get('name', 'unknown')
                    drill = float(pad.get('drill', '0'))

                    if drill > 0:
                        pads.append({
                            "number": pad_name,
                            "type": "thru_hole",
                            "drill": drill,
                            "component": element_name
                        })

        return pads

    def _extract_board_size(self, board: ET.Element) -> Tuple[float, float]:
        """
        Extract board dimensions from dimension layer (layer 20).

        Calculates bounding box of dimension wires.
        """
        x_coords = []
        y_coords = []

        # Find plain section (contains board outline)
        plain = board.find('plain')
        if plain is not None:
            for wire in plain.findall('wire'):
                layer = wire.get('layer', '')
                # Dimension layer is typically 20
                if layer == '20':
                    x1 = float(wire.get('x1', '0'))
                    y1 = float(wire.get('y1', '0'))
                    x2 = float(wire.get('x2', '0'))
                    y2 = float(wire.get('y2', '0'))

                    x_coords.extend([x1, x2])
                    y_coords.extend([y1, y2])

        if x_coords and y_coords:
            width = max(x_coords) - min(x_coords)
            height = max(y_coords) - min(y_coords)
            return (width, height)
        else:
            # Default fallback
            return (100.0, 80.0)

    def _extract_layer_count(self, board: ET.Element) -> int:
        """
        Extract number of copper layers from layer definitions.

        Eagle defines layers explicitly in <layers> section.
        """
        copper_layers = set()

        layers = board.find('.//layers')
        if layers is not None:
            for layer in layers.findall('layer'):
                number = int(layer.get('number', '0'))
                # Copper layers are 1-16
                if 1 <= number <= 16:
                    copper_layers.add(number)

        # Typical boards: 2-layer (1,16), 4-layer (1,2,15,16), etc.
        count = len(copper_layers)
        return max(count, 2)  # Minimum 2 layers

    def _extract_clearances(self, board: ET.Element) -> List[Dict[str, Any]]:
        """
        Extract clearance settings from design rules.

        Eagle design rules are in <designrules> section.
        """
        clearances = []

        # Find design rules
        designrules = board.find('.//designrules')
        if designrules is not None:
            # Find clearance parameters
            for param in designrules.findall('.//param[@name="mdCopperDimension"]'):
                # Minimum copper dimension (clearance)
                value = float(param.text or '0.127')
                clearances.append({
                    "feature1": "copper",
                    "feature2": "copper",
                    "distance": value
                })

        return clearances

    def _extract_silkscreen(self, board: ET.Element) -> List[Dict[str, Any]]:
        """
        Extract silkscreen line widths.

        Eagle silkscreen layers: 21 (tPlace - top), 22 (bPlace - bottom)
        """
        silkscreen = []

        # Check text elements on silkscreen layers
        elements = board.find('elements')
        if elements is not None:
            for element in elements.findall('element'):
                for attribute in element.findall('.//attribute'):
                    layer = attribute.get('layer', '')
                    if layer in ['21', '22']:  # Silkscreen layers
                        size = float(attribute.get('size', '1.27'))
                        # Eagle 'size' is text height; line width is typically size/6
                        width = size / 6

                        silkscreen.append({
                            "layer": "Top SilkS" if layer == '21' else "Bottom SilkS",
                            "width": width,
                            "type": "text"
                        })

        # Check wire elements on silkscreen layers
        plain = board.find('plain')
        if plain is not None:
            for wire in plain.findall('wire'):
                layer = wire.get('layer', '')
                if layer in ['21', '22']:
                    width = float(wire.get('width', '0.15'))
                    silkscreen.append({
                        "layer": "Top SilkS" if layer == '21' else "Bottom SilkS",
                        "width": width,
                        "type": "line"
                    })

        return silkscreen


# Convenience function
def parse_eagle_for_dfm(brd_file_path: str) -> Dict[str, Any]:
    """
    Convenience function to parse Eagle board for DFM checking.

    Usage:
        pcb_data = parse_eagle_for_dfm("output/project/circuit.brd")
        result = DFMChecker().check(pcb_data)
    """
    parser = EagleDFMParser()
    return parser.parse(brd_file_path)
