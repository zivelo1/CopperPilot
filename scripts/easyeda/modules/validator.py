# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Validator module for EasyEDA converter."""
from typing import Dict, List, Any, Tuple
from .utils import EasyEDAContext, validate_json_structure

class Validator:
    """Validate EasyEDA output for correctness."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.strict_mode = config.get('strict_validation', False)

    def execute(self, context: EasyEDAContext) -> EasyEDAContext:
        """Validate all aspects of the conversion."""
        print("\n=== Stage 7: Validation ===")

        # Run validation checks
        self._validate_components(context)
        self._validate_connectivity(context)
        self._validate_schematic(context)
        self._validate_pcb(context)
        self._validate_json_format(context)
        self._run_drc(context)
        self._run_erc(context)

        # Generate validation report
        report = self._generate_report(context)
        context.stats['validation'] = report

        # Print summary
        print(f"Validation complete: {len(context.errors)} errors, {len(context.warnings)} warnings")

        if context.errors and self.strict_mode:
            print("ERROR: Validation failed in strict mode")
            for error in context.errors:
                print(f"  - {error}")

        return context

    def _validate_components(self, context: EasyEDAContext):
        """Validate all components have required data."""
        for comp_ref, comp_data in context.components.items():
            # Check required fields
            if not comp_data.get('type'):
                context.errors.append(f"Component {comp_ref} missing type")

            if not comp_data.get('refDes'):
                context.errors.append(f"Component {comp_ref} missing reference designator")

            # Check symbol exists
            if comp_ref not in context.symbols:
                context.errors.append(f"Component {comp_ref} missing symbol")

            # Check footprint exists
            if comp_ref not in context.footprints:
                context.warnings.append(f"Component {comp_ref} missing footprint")

            # Validate pins
            if not comp_data.get('pins'):
                context.warnings.append(f"Component {comp_ref} has no pins defined")

    def _validate_connectivity(self, context: EasyEDAContext):
        """Validate all connections are valid."""
        # Check for unconnected components
        connected_components = set()
        for net_name, net_points in context.nets.items():
            for point in net_points:
                if '.' in point:
                    comp_ref = point.split('.')[0]
                    connected_components.add(comp_ref)

        # Find unconnected components
        for comp_ref in context.components:
            if comp_ref not in connected_components:
                # Check if it's a mechanical component
                comp_type = context.components[comp_ref]['type'].lower()
                if comp_type not in ['heatsink', 'mounting_hole', 'fiducial', 'test_point']:
                    context.warnings.append(f"Component {comp_ref} has no connections")

        # Check for duplicate connections
        seen_connections = set()
        for conn in context.connections:
            conn_key = f"{conn['from']}-{conn['to']}"
            if conn_key in seen_connections:
                context.warnings.append(f"Duplicate connection: {conn_key}")
            seen_connections.add(conn_key)

        # Check for nets with only one connection
        for net_name, net_points in context.nets.items():
            if len(net_points) == 1:
                context.warnings.append(f"Net {net_name} has only one connection")

    def _validate_schematic(self, context: EasyEDAContext):
        """Validate schematic data."""
        if not context.schematic_data:
            context.errors.append("No schematic data generated")
            return

        schematic = context.schematic_data

        # Check required fields
        if 'head' not in schematic:
            context.errors.append("Schematic missing head section")

        if 'canvas' not in schematic:
            context.errors.append("Schematic missing canvas definition")

        if 'shape' not in schematic:
            context.errors.append("Schematic missing shapes")
        elif not schematic['shape']:
            context.warnings.append("Schematic has no shapes")

        # Validate shapes
        if 'shape' in schematic:
            for shape in schematic['shape']:
                if 'type' not in shape:
                    context.errors.append("Shape missing type field")

                # Check coordinates
                if shape.get('type') == 'W':  # Wire
                    if not all(k in shape for k in ['x1', 'y1', 'x2', 'y2']):
                        context.errors.append("Wire missing coordinates")

    def _validate_pcb(self, context: EasyEDAContext):
        """Validate PCB data."""
        if not context.pcb_data:
            context.warnings.append("No PCB data generated")
            return

        pcb = context.pcb_data

        # Check required fields
        if 'head' not in pcb:
            context.errors.append("PCB missing head section")

        if 'layers' not in pcb:
            context.warnings.append("PCB missing layer definitions")

        if 'shape' not in pcb:
            context.errors.append("PCB missing shapes")

        # Check for board outline
        has_outline = False
        if 'shape' in pcb:
            for shape in pcb['shape']:
                if shape.get('layerid') == '10':  # BoardOutLine
                    has_outline = True
                    break

        if not has_outline:
            context.warnings.append("PCB missing board outline")

        # Check footprint placement
        footprint_positions = set()
        if 'shape' in pcb:
            for shape in pcb['shape']:
                if shape.get('type') == 'FOOTPRINT':
                    pos_key = f"{shape.get('x', 0)},{shape.get('y', 0)}"
                    if pos_key in footprint_positions:
                        context.warnings.append(f"Overlapping footprints at {pos_key}")
                    footprint_positions.add(pos_key)

    def _validate_json_format(self, context: EasyEDAContext):
        """Validate JSON structure compliance."""
        # Validate schematic JSON
        if context.schematic_data:
            valid, errors = validate_json_structure(context.schematic_data)
            if not valid:
                for error in errors:
                    context.errors.append(f"Schematic JSON: {error}")

        # Validate PCB JSON
        if context.pcb_data:
            # PCB has different required fields
            pcb = context.pcb_data
            if 'head' not in pcb:
                context.errors.append("PCB JSON: Missing head field")
            if 'shape' not in pcb:
                context.errors.append("PCB JSON: Missing shape field")

    def _run_drc(self, context: EasyEDAContext):
        """Run Design Rule Check on PCB."""
        if not context.pcb_data:
            return

        # Check minimum track width
        min_track_width = 2.5  # 0.25mm in EasyEDA units
        if 'shape' in context.pcb_data:
            for shape in context.pcb_data['shape']:
                if shape.get('type') == 'TRACK':
                    width = shape.get('strokeWidth', 0)
                    if width < min_track_width:
                        context.warnings.append(f"Track width {width} below minimum {min_track_width}")

        # Check minimum via size
        min_via_drill = 3  # 0.3mm
        min_via_diameter = 6  # 0.6mm
        if 'shape' in context.pcb_data:
            for shape in context.pcb_data['shape']:
                if shape.get('type') == 'VIA':
                    drill = shape.get('drill', 0)
                    diameter = shape.get('diameter', 0)
                    if drill < min_via_drill:
                        context.warnings.append(f"Via drill {drill} below minimum {min_via_drill}")
                    if diameter < min_via_diameter:
                        context.warnings.append(f"Via diameter {diameter} below minimum {min_via_diameter}")

    def _run_erc(self, context: EasyEDAContext):
        """Run Electrical Rule Check on schematic."""
        # Check for power connections
        has_power = False
        has_ground = False

        for net_name in context.nets:
            net_lower = net_name.lower()
            if 'vcc' in net_lower or 'vdd' in net_lower or '+5v' in net_lower or '+3v3' in net_lower:
                has_power = True
            if 'gnd' in net_lower or 'vss' in net_lower or '0v' in net_lower:
                has_ground = True

        if not has_power:
            context.warnings.append("No power net detected")
        if not has_ground:
            context.warnings.append("No ground net detected")

        # Check for floating inputs on ICs
        for comp_ref, comp_data in context.components.items():
            if 'ic' in comp_data['type'].lower():
                # Check if all pins are connected
                pins = comp_data.get('pins', [])
                connected_pins = set()

                for net_points in context.nets.values():
                    for point in net_points:
                        if point.startswith(f"{comp_ref}."):
                            pin = point.split('.')[1]
                            connected_pins.add(pin)

                for pin in pins:
                    if str(pin) not in connected_pins:
                        context.warnings.append(f"IC {comp_ref} pin {pin} is floating")

    def _generate_report(self, context: EasyEDAContext) -> Dict:
        """Generate validation report."""
        report = {
            'passed': len(context.errors) == 0,
            'errors': context.errors,
            'warnings': context.warnings,
            'statistics': {
                'total_components': len(context.components),
                'total_nets': len(context.nets),
                'total_connections': len(context.connections),
                'components_with_symbols': sum(1 for c in context.symbols if c),
                'components_with_footprints': sum(1 for c in context.footprints if c),
                'components_with_lcsc': sum(1 for c in context.components.values()
                                           if c.get('lcsc'))
            },
            'checks': {
                'component_validation': 'PASS' if not any('Component' in e for e in context.errors) else 'FAIL',
                'connectivity_check': 'PASS' if not any('connection' in e for e in context.errors) else 'FAIL',
                'schematic_validation': 'PASS' if not any('Schematic' in e for e in context.errors) else 'FAIL',
                'pcb_validation': 'PASS' if not any('PCB' in e for e in context.errors) else 'FAIL',
                'json_format': 'PASS' if not any('JSON' in e for e in context.errors) else 'FAIL',
                'drc': 'PASS' if not any('Track' in w or 'Via' in w for w in context.warnings) else 'WARNING',
                'erc': 'PASS' if not any('power' in w or 'ground' in w or 'floating' in w
                                        for w in context.warnings) else 'WARNING'
            }
        }

        return report