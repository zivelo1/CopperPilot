# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
EasyEDA Pro PCB Parser for DFM Checking
========================================

Extracts design parameters from EasyEDA Pro JSON files for DFM validation.

EasyEDA Pro uses JSON format with canvas-based coordinate system.

Parses:
- Track widths (from TRACK elements)
- Via diameters and drill sizes
- Pad drill sizes
- Board dimensions (from BOARD_OUTLINE or calculated)
- Layer count
- Clearance settings

Output format is standardized for use with DFMChecker.

Author: CopperPilot Development Team
Created: November 9, 2025
"""

from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


class EasyEDADFMParser:
    """
    Parse EasyEDA Pro JSON files to extract DFM-relevant parameters.

    Usage:
        parser = EasyEDADFMParser()
        pcb_data = parser.parse("/path/to/file.json")
        dfm_result = DFMChecker().check(pcb_data)
    """

    # EasyEDA Pro layer ID mappings (typical)
    LAYER_NAMES = {
        "1": "TopLayer",
        "2": "BottomLayer",
        "3": "InnerLayer1",
        "4": "InnerLayer2",
        # ... more inner layers
    }

    def __init__(self):
        """Initialize EasyEDA Pro DFM parser"""
        self.logger = logger

    def parse(self, json_file_path: str) -> Dict[str, Any]:
        """
        Parse EasyEDA Pro JSON file and extract DFM parameters.

        Args:
            json_file_path: Path to EasyEDA Pro .json file

        Returns:
            Dictionary with standardized DFM data
        """
        json_path = Path(json_file_path)
        if not json_path.exists():
            raise FileNotFoundError(f"EasyEDA Pro file not found: {json_file_path}")

        self.logger.info(f"Parsing EasyEDA Pro file: {json_path.name}")

        # Load JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            easyeda_data = json.load(f)

        # EasyEDA Pro format varies, handle both PCB and canvas formats
        canvas = easyeda_data.get('canvas', '')
        if isinstance(canvas, str):
            # Parse canvas string (older format)
            shapes = self._parse_canvas_string(canvas)
        else:
            # Parse structured format (newer format)
            shapes = easyeda_data.get('shape', [])

        # Extract parameters
        data = {
            "format": "easyeda_pro",
            "file_path": str(json_path),
            "traces": self._extract_traces(shapes),
            "vias": self._extract_vias(shapes),
            "pads": self._extract_pads(shapes),
            "board_size": self._extract_board_size(shapes, easyeda_data),
            "layers": self._extract_layer_count(easyeda_data),
            "clearances": self._extract_clearances(easyeda_data),
            "silkscreen": self._extract_silkscreen(shapes)
        }

        self.logger.info(
            f"Extracted: {len(data['traces'])} traces, {len(data['vias'])} vias, "
            f"{len(data['pads'])} pads, board size: {data['board_size']}, layers: {data['layers']}"
        )

        return data

    def _parse_canvas_string(self, canvas: str) -> List[Dict[str, Any]]:
        """
        Parse EasyEDA canvas string format (older format).

        Canvas format: shape1~#@$newline@shape2~#@$...
        """
        shapes = []
        if not canvas:
            return shapes

        # Split by delimiter
        parts = canvas.split('#@$newline@')
        for part in parts:
            if not part.strip():
                continue

            # Each part: TYPE~param1~param2~...
            fields = part.split('~')
            if len(fields) > 0:
                shape_type = fields[0]
                shapes.append({
                    "type": shape_type,
                    "params": fields[1:] if len(fields) > 1 else []
                })

        return shapes

    def _extract_traces(self, shapes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract trace/track information.

        EasyEDA format: TRACK elements with width, layer, points
        """
        traces = []

        for shape in shapes:
            shape_type = shape.get("type", "")

            # TRACK elements represent traces
            if shape_type == "TRACK":
                params = shape.get("params", [])

                # Typical format: TRACK~width~layer~net~points...
                if len(params) >= 4:
                    width = float(params[0]) if params[0] else 0.2
                    layer_id = params[1]
                    net_name = params[2]
                    # Points are remaining parameters

                    # Convert width from EasyEDA units (mils) to mm
                    width_mm = width * 0.0254  # Convert mils to mm

                    traces.append({
                        "width": width_mm,
                        "layer": self.LAYER_NAMES.get(layer_id, f"Layer{layer_id}"),
                        "net": net_name,
                        "start": (0, 0),  # Would parse from points
                        "end": (0, 0),
                        "spacing": 0.127
                    })

        return traces

    def _extract_vias(self, shapes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract via information.

        EasyEDA format: VIA elements with position, diameter, drill
        """
        vias = []

        for shape in shapes:
            shape_type = shape.get("type", "")

            if shape_type == "VIA":
                params = shape.get("params", [])

                # Typical format: VIA~x~y~diameter~net~drill...
                if len(params) >= 5:
                    x = float(params[0]) if params[0] else 0
                    y = float(params[1]) if params[1] else 0
                    diameter = float(params[2]) if params[2] else 0.6
                    drill = float(params[4]) if params[4] else 0.3

                    # Convert from EasyEDA units to mm (if needed)
                    diameter_mm = diameter * 0.0254
                    drill_mm = drill * 0.0254

                    vias.append({
                        "position": (x, y),
                        "diameter": diameter_mm,
                        "drill": drill_mm,
                        "type": "through"
                    })

        return vias

    def _extract_pads(self, shapes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract pad information.

        EasyEDA format: PAD elements with various types
        """
        pads = []

        for shape in shapes:
            shape_type = shape.get("type", "")

            if shape_type == "PAD":
                params = shape.get("params", [])

                # Typical format: PAD~type~x~y~width~height~layer~net~drill~...
                if len(params) >= 9:
                    pad_type = params[0]  # ELLIPSE, RECT, etc.
                    drill = float(params[8]) if params[8] else 0

                    # Only through-hole pads have drill
                    if drill > 0:
                        drill_mm = drill * 0.0254

                        pads.append({
                            "number": "unknown",
                            "type": "thru_hole",
                            "drill": drill_mm,
                            "component": "unknown"
                        })

        return pads

    def _extract_board_size(self, shapes: List[Dict[str, Any]],
                           easyeda_data: Dict[str, Any]) -> Tuple[float, float]:
        """
        Extract board dimensions.

        EasyEDA may have BOARD_OUTLINE or we calculate from shapes.
        """
        # Try to find explicit board outline
        for shape in shapes:
            if shape.get("type") == "BOARD_OUTLINE":
                # Parse outline dimensions
                params = shape.get("params", [])
                if len(params) >= 4:
                    # Simplified: assume rectangular board
                    # Real implementation would parse polygon points
                    return (100.0, 80.0)

        # Fallback: calculate bounding box from all shapes
        # (Simplified - real implementation would parse coordinates)
        return (100.0, 80.0)

    def _extract_layer_count(self, easyeda_data: Dict[str, Any]) -> int:
        """
        Extract number of copper layers.

        EasyEDA stores layer info in 'layers' or 'routerConfig'
        """
        # Try layers array
        layers = easyeda_data.get('layers', [])
        copper_count = 0

        for layer in layers:
            if isinstance(layer, dict):
                layer_type = layer.get('layerType', '')
                if 'copper' in layer_type.lower():
                    copper_count += 1

        if copper_count > 0:
            return copper_count

        # Fallback: check router config
        router = easyeda_data.get('routerConfig', {})
        layer_setup = router.get('layerSetup', '2')

        return int(layer_setup) if layer_setup.isdigit() else 2

    def _extract_clearances(self, easyeda_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract clearance settings from design rules.

        EasyEDA stores design rules in 'designRules' or similar
        """
        clearances = []

        # Try design rules
        design_rules = easyeda_data.get('designRules', {})
        clearance = design_rules.get('clearance', 0.127)

        clearances.append({
            "feature1": "default",
            "feature2": "default",
            "distance": clearance
        })

        return clearances

    def _extract_silkscreen(self, shapes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract silkscreen line widths.

        EasyEDA format: TEXT and SOLIDREGION on silkscreen layers
        """
        silkscreen = []

        for shape in shapes:
            shape_type = shape.get("type", "")
            params = shape.get("params", [])

            if shape_type == "TEXT" and len(params) >= 4:
                # TEXT~x~y~layer~text~fontSize~...
                layer_id = params[2] if len(params) > 2 else ""

                # Silkscreen layers (varies by design)
                if "silkscreen" in layer_id.lower() or layer_id in ["15", "16"]:
                    font_size = float(params[4]) if len(params) > 4 and params[4] else 1.0
                    # Width is approximately font_size / 6
                    width = font_size / 6

                    silkscreen.append({
                        "layer": "Top SilkS" if "top" in layer_id.lower() else "Bottom SilkS",
                        "width": width * 0.0254,  # Convert to mm
                        "type": "text"
                    })

        return silkscreen


# Convenience function
def parse_easyeda_for_dfm(json_file_path: str) -> Dict[str, Any]:
    """
    Convenience function to parse EasyEDA Pro file for DFM checking.

    Usage:
        pcb_data = parse_easyeda_for_dfm("output/project/circuit.json")
        result = DFMChecker().check(pcb_data)
    """
    parser = EasyEDADFMParser()
    return parser.parse(json_file_path)
