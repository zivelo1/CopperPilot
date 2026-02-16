# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Input processor module for parsing and validating JSON circuit files."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

from ..utils.base import PipelineStage, ConversionContext, ValidationError, load_json

logger = logging.getLogger(__name__)

class InputProcessor(PipelineStage):
    """Process and validate input JSON files from lowlevel folder."""

    def process(self, context: ConversionContext) -> ConversionContext:
        """Load and validate circuit JSON file."""
        try:
            # Check if single circuit file is specified
            if hasattr(context, 'circuit_file'):
                json_files = [context.circuit_file]
            else:
                # Find all JSON files in input folder
                json_files = list(context.input_path.glob("*.json"))
                if not json_files:
                    raise ValidationError(f"No JSON files found in {context.input_path}")

            logger.info(f"Processing {len(json_files)} JSON file(s)")

            # Process circuit file(s)
            circuits = []
            all_components = {}
            all_connections = []

            # Track circuit-level pinNetMapping
            all_pin_mappings = {}

            for json_file in json_files:
                if json_file.name == "design.json":
                    # Special handling for design.json if present
                    design_data = load_json(json_file)
                    context.input_data['design'] = design_data
                    continue

                # Load circuit data
                raw_data = load_json(json_file)

                # CRITICAL: Handle wrapped circuit format {"circuit": {...}}
                if 'circuit' in raw_data and isinstance(raw_data['circuit'], dict):
                    circuit_data = raw_data['circuit']
                else:
                    circuit_data = raw_data

                self._validate_circuit_structure(circuit_data)

                # Extract components for this circuit
                circuit_components = set()
                if 'components' in circuit_data:
                    for comp in circuit_data['components']:
                        # FIXED: Use 'ref' instead of 'refDes' (lowlevel format uses 'ref')
                        ref_des = comp.get('ref', comp.get('refDes', ''))
                        if ref_des:
                            all_components[ref_des] = self._normalize_component(comp)
                            circuit_components.add(ref_des)

                # Extract connections
                if 'connections' in circuit_data:
                    for conn in circuit_data['connections']:
                        all_connections.append(self._normalize_connection(conn))

                # Extract pinNetMapping for this circuit's components
                if 'pinNetMapping' in circuit_data:
                    for pin_ref, net in circuit_data['pinNetMapping'].items():
                        if '.' in pin_ref:
                            comp_ref = pin_ref.split('.')[0]
                            # Only add if component is in this circuit
                            if comp_ref in circuit_components:
                                all_pin_mappings[pin_ref] = net

                circuits.append({
                    'name': circuit_data.get('moduleName', json_file.stem),
                    'type': circuit_data.get('moduleType', 'generic'),
                    'data': circuit_data
                })

            # Store processed data in context
            context.input_data['circuits'] = circuits
            context.input_data['components'] = all_components
            context.input_data['connections'] = all_connections
            context.input_data['pinNetMapping'] = all_pin_mappings

            # Generate statistics
            context.statistics['input'] = {
                'circuits': len(circuits),
                'components': len(all_components),
                'connections': len(all_connections),
                'files_processed': len(json_files)
            }

            logger.info(f"Successfully loaded {len(all_components)} components and {len(all_connections)} connections")
            return context

        except Exception as e:
            return self.handle_error(e, context)

    def _validate_circuit_structure(self, circuit: Dict[str, Any]) -> None:
        """Validate the structure of a circuit JSON."""
        required_fields = ['moduleName']
        for field in required_fields:
            if field not in circuit:
                logger.warning(f"Missing required field: {field}")

        # Validate components if present
        if 'components' in circuit:
            if not isinstance(circuit['components'], list):
                raise ValidationError("Components must be a list")

            for comp in circuit['components']:
                if not isinstance(comp, dict):
                    raise ValidationError("Each component must be a dictionary")
                # FIXED: Check for 'ref' (lowlevel format) or 'refDes' (legacy)
                if 'ref' not in comp and 'refDes' not in comp:
                    raise ValidationError("Component missing ref/refDes")
                if 'type' not in comp:
                    ref_value = comp.get('ref', comp.get('refDes', 'unknown'))
                    raise ValidationError(f"Component {ref_value} missing type")

        # Validate connections if present
        if 'connections' in circuit:
            if not isinstance(circuit['connections'], list):
                raise ValidationError("Connections must be a list")

    def _normalize_component(self, comp: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize component data for processing."""
        # FIXED: Use 'ref' (lowlevel format) or 'refDes' (legacy) for compatibility
        ref_value = comp.get('ref', comp.get('refDes', ''))
        normalized = {
            'refDes': ref_value,  # Keep as refDes internally for KiCad processing
            'type': self._normalize_component_type(comp.get('type', '')),
            'value': comp.get('value', ''),
            'package': comp.get('package', ''),
            'specs': comp.get('specs', {}),
            'notes': comp.get('notes', ''),
            'pinNetMapping': comp.get('pinNetMapping', {}),
            'pins': comp.get('pins', [])  # Add pins array support
        }

        # Handle special component types
        comp_type = normalized['type']
        if comp_type == 'ic' and 'specs' in comp:
            # Try to determine actual IC type from specs
            suggested_part = comp['specs'].get('suggestedPart', '')
            if 'LM358' in suggested_part or 'opamp' in comp.get('notes', '').lower():
                normalized['type'] = 'opamp'
            elif '555' in suggested_part:
                normalized['type'] = 'timer'
            elif '7805' in suggested_part or 'regulator' in comp.get('notes', '').lower():
                normalized['type'] = 'regulator'

        return normalized

    def _normalize_component_type(self, comp_type: str) -> str:
        """Normalize component type string."""
        type_map = {
            'res': 'resistor',
            'cap': 'capacitor',
            'ind': 'inductor',
            'led': 'led',
            'diode': 'diode',
            'transistor': 'transistor',
            'trans': 'transistor',
            'mosfet': 'mosfet',
            'fet': 'mosfet',
            'ic': 'ic',
            'opamp': 'opamp',
            'op-amp': 'opamp',
            'regulator': 'regulator',
            'vreg': 'regulator',
            'connector': 'connector',
            'conn': 'connector',
            'crystal': 'crystal',
            'xtal': 'crystal',
            'fuse': 'fuse',
            'varistor': 'varistor',
            'mov': 'varistor',
            'transformer': 'transformer',
            'bridge': 'bridge_rectifier',
            'thermistor': 'thermistor',
            'test': 'test_point'
        }

        comp_type_lower = comp_type.lower()
        for key, value in type_map.items():
            if key in comp_type_lower:
                return value

        return comp_type_lower

    def _normalize_connection(self, conn: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize connection data."""
        normalized = {
            'net': conn.get('net', ''),
            'points': []
        }

        # Handle different connection formats
        if 'points' in conn and conn['points']:
            # Modern format with points array
            normalized['points'] = conn['points']
        elif 'from' in conn and 'to' in conn:
            # Legacy format with from/to
            normalized['points'] = [conn['from'], conn['to']]

        # Validate points format
        validated_points = []
        for point in normalized['points']:
            if isinstance(point, str) and '.' in point:
                validated_points.append(point)
            elif isinstance(point, dict):
                # Handle dictionary format if present
                ref = point.get('ref', '')
                pin = point.get('pin', '')
                if ref and pin:
                    validated_points.append(f"{ref}.{pin}")

        normalized['points'] = validated_points
        return normalized