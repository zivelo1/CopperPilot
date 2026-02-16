# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""JSON assembler module for EasyEDA converter."""
import json
import time
from typing import Dict, List, Any
from .utils import EasyEDAContext, generate_id

class JSONAssembler:
    """Assemble final EasyEDA JSON format."""

    def __init__(self, config: Dict = None):
        self.config = config or {}

    def execute(self, context: EasyEDAContext) -> EasyEDAContext:
        """Assemble final JSON structures."""
        print("\n=== Stage 5: JSON Assembly ===")

        # Get circuit name from the first circuit (should only be one per context now)
        circuit_name = 'circuit'
        if context.circuits:
            circuit_name = context.circuits[0].get('moduleName', 'circuit')

        # Assemble schematic if available
        if context.schematic_data:
            context.schematic_data = self._assemble_schematic(context.schematic_data, circuit_name)

        # Assemble PCB if available
        if context.pcb_data:
            context.pcb_data = self._assemble_pcb(context.pcb_data, circuit_name)

        print(f"Assembled schematic and PCB for {circuit_name}")

        return context

    def _create_project_structure(self, name: str) -> Dict:
        """Create EasyEDA project structure."""
        return {
            "docType": "project",
            "title": name,
            "description": f"Generated circuit: {name}",
            "tags": ["generated", "circuit"],
            "id": generate_id("pro"),
            "schematics": [],
            "pcbs": [],
            "components": [],
            "nets": []
        }

    def _assemble_schematic(self, schematic_data: Dict, circuit_name: str) -> Dict:
        """Assemble schematic JSON."""
        # Update schematic metadata
        schematic = schematic_data.copy()

        # Set proper document info
        if 'head' not in schematic:
            schematic['head'] = {}

        schematic['head'].update({
            "docType": "5",  # Schematic document
            "title": f"{circuit_name}_schematic",
            "uuid": generate_id("sch"),
            "newgId": True,
            "editorVersion": "6.5.22",
            "createTime": time.strftime("%Y-%m-%d %H:%M:%S")
        })

        # Ensure canvas is set
        if 'canvas' not in schematic:
            schematic['canvas'] = "CA~1000~1000~#000000~yes~#FFFFFF~10~1000~1000~line~10~pixel~5~0~0"

        # Process shapes
        if 'shape' in schematic:
            schematic['shape'] = self._process_shapes(schematic['shape'])

        # Add dataStr format (alternative representation)
        schematic['dataStr'] = self._generate_datastr(schematic)

        return schematic

    def _assemble_pcb(self, pcb_data: Dict, circuit_name: str) -> Dict:
        """Assemble PCB JSON."""
        # Update PCB metadata
        pcb = pcb_data.copy()

        # Set proper document info
        if 'head' not in pcb:
            pcb['head'] = {}

        pcb['head'].update({
            "docType": "3",  # PCB document
            "title": f"{circuit_name}_pcb",
            "uuid": generate_id("pcb"),
            "newgId": True,
            "editorVersion": "6.5.22"
        })

        # Process shapes for PCB
        if 'shape' in pcb:
            pcb['shape'] = self._process_pcb_shapes(pcb['shape'])

        # Add PCB-specific data
        pcb['DRCRULE'] = self._get_drc_rules()

        return pcb

    def _process_shapes(self, shapes: List[Dict]) -> List[Dict]:
        """Process and validate schematic shapes."""
        processed = []

        for shape in shapes:
            # Ensure all shapes have required fields
            if 'type' not in shape:
                continue

            # Process based on type
            if shape['type'] == 'LIB':
                # Component library reference
                processed_shape = self._process_component_shape(shape)
            elif shape['type'] == 'W':
                # Wire
                processed_shape = self._process_wire_shape(shape)
            elif shape['type'] == 'T':
                # Text
                processed_shape = self._process_text_shape(shape)
            elif shape['type'] == 'J':
                # Junction
                processed_shape = self._process_junction_shape(shape)
            else:
                processed_shape = shape

            if processed_shape:
                processed.append(processed_shape)

        return processed

    def _process_component_shape(self, shape: Dict) -> Dict:
        """Process component library shape."""
        # Ensure component has all required fields
        processed = shape.copy()

        # Add default values if missing
        if 'id' not in processed:
            processed['id'] = generate_id("lib")

        if 'x' not in processed:
            processed['x'] = 0

        if 'y' not in processed:
            processed['y'] = 0

        # Format for EasyEDA
        processed['shape'] = "LIB"

        return processed

    def _process_wire_shape(self, shape: Dict) -> Dict:
        """Process wire shape."""
        processed = shape.copy()

        # Ensure wire has endpoints
        if not all(k in processed for k in ['x1', 'y1', 'x2', 'y2']):
            return None

        # Format as polyline for EasyEDA
        processed['points'] = [
            [processed['x1'], processed['y1']],
            [processed['x2'], processed['y2']]
        ]

        # Set default stroke
        if 'strokeWidth' not in processed:
            processed['strokeWidth'] = 1

        if 'strokeColor' not in processed:
            processed['strokeColor'] = "#008800"

        return processed

    def _process_text_shape(self, shape: Dict) -> Dict:
        """Process text shape."""
        processed = shape.copy()

        # Set defaults
        if 'fontSize' not in processed:
            processed['fontSize'] = 7

        if 'fontFamily' not in processed:
            processed['fontFamily'] = "Arial"

        if 'fillColor' not in processed:
            processed['fillColor'] = "#000000"

        return processed

    def _process_junction_shape(self, shape: Dict) -> Dict:
        """Process junction shape."""
        processed = shape.copy()

        # Set default radius
        if 'radius' not in processed:
            processed['radius'] = 2

        if 'fillColor' not in processed:
            processed['fillColor'] = "#000000"

        return processed

    def _process_pcb_shapes(self, shapes: List[Dict]) -> List[Dict]:
        """Process PCB shapes."""
        processed = []

        for shape in shapes:
            if shape.get('type') == 'TRACK':
                processed.append(self._process_track_shape(shape))
            elif shape.get('type') == 'PAD':
                processed.append(self._process_pad_shape(shape))
            elif shape.get('type') == 'VIA':
                processed.append(self._process_via_shape(shape))
            elif shape.get('type') == 'TEXT':
                processed.append(self._process_pcb_text_shape(shape))
            elif shape.get('type') == 'FOOTPRINT':
                processed.append(self._process_footprint_shape(shape))
            else:
                processed.append(shape)

        return processed

    def _process_track_shape(self, shape: Dict) -> Dict:
        """Process PCB track."""
        processed = shape.copy()

        # Ensure track has points
        if 'pointArr' not in processed:
            processed['pointArr'] = []

        # Set default layer
        if 'layerid' not in processed:
            processed['layerid'] = "1"  # Top layer

        # Set default width
        if 'strokeWidth' not in processed:
            processed['strokeWidth'] = 2.5  # 0.25mm in EasyEDA units

        return processed

    def _process_pad_shape(self, shape: Dict) -> Dict:
        """Process PCB pad."""
        processed = shape.copy()

        # Set defaults
        if 'shape' not in processed:
            processed['shape'] = "RECT"

        if 'layerid' not in processed:
            processed['layerid'] = "1"

        return processed

    def _process_via_shape(self, shape: Dict) -> Dict:
        """Process PCB via."""
        processed = shape.copy()

        # Set default via parameters
        if 'diameter' not in processed:
            processed['diameter'] = 8  # 0.8mm

        if 'drill' not in processed:
            processed['drill'] = 4  # 0.4mm

        return processed

    def _process_pcb_text_shape(self, shape: Dict) -> Dict:
        """Process PCB text."""
        processed = shape.copy()

        # Set default layer for silkscreen
        if 'layerid' not in processed:
            processed['layerid'] = "3"  # Top silkscreen

        return processed

    def _process_footprint_shape(self, shape: Dict) -> Dict:
        """Process footprint shape."""
        processed = shape.copy()

        # Ensure footprint has pads
        if 'pads' not in processed:
            processed['pads'] = []

        return processed

    def _generate_datastr(self, schematic: Dict) -> str:
        """Generate dataStr representation for schematic."""
        # EasyEDA uses a compressed string format for some data
        # For simplicity, we'll use JSON string
        data = {
            "head": schematic.get('head', {}),
            "canvas": schematic.get('canvas', ''),
            "shape": schematic.get('shape', [])
        }
        return json.dumps(data, separators=(',', ':'))

    def _get_drc_rules(self) -> Dict:
        """Get default DRC rules for PCB."""
        return {
            "trackWidth": 0.254,  # mm
            "clearance": 0.254,   # mm
            "viaHole": 0.4,       # mm
            "viaDiameter": 0.8,   # mm
            "routingLayers": "all"
        }