# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Input processing module for EasyEDA converter."""
import json
from pathlib import Path
from typing import Dict, List, Any
from .utils import EasyEDAContext

class InputProcessor:
    """Process input JSON files from lowlevel folder."""

    def __init__(self, config: Dict = None):
        self.config = config or {}

    def execute(self, context: EasyEDAContext) -> EasyEDAContext:
        """Process input files and populate context."""
        print("\n=== Stage 1: Input Processing ===")

        # Find and load JSON files
        json_files = self._find_json_files(context.input_path)
        if not json_files:
            context.errors.append("No JSON files found in input directory")
            return context

        print(f"Found {len(json_files)} circuit files")

        # Process each circuit file
        for json_file in json_files:
            circuit_data = self._load_circuit(json_file)
            if circuit_data:
                circuit_name = json_file.stem
                self._process_circuit(circuit_data, circuit_name, context)

        # Build consolidated netlist
        self._build_netlist(context)

        # Generate statistics
        context.stats['input'] = {
            'circuits': len(context.circuits),
            'components': len(context.components),
            'connections': len(context.connections),
            'nets': len(context.nets)
        }

        print(f"Processed {len(context.components)} components")
        print(f"Found {len(context.connections)} connections")
        print(f"Generated {len(context.nets)} nets")

        return context

    def _find_json_files(self, input_path: Path) -> List[Path]:
        """Find all JSON files in input directory."""
        json_files = []

        # Check if input_path is a directory
        if input_path.is_dir():
            json_files = sorted(input_path.glob("*.json"))
        else:
            # Single file mode
            if input_path.suffix == '.json':
                json_files = [input_path]

        # Filter out non-circuit files
        circuit_files = []
        for f in json_files:
            if not f.stem.startswith('.') and f.stem != 'components':
                circuit_files.append(f)

        return circuit_files

    def _load_circuit(self, filepath: Path) -> Dict:
        """Load and validate circuit JSON."""
        try:
            with open(filepath, 'r') as f:
                raw_data = json.load(f)

            # CRITICAL: Handle wrapped circuit format {"circuit": {...}}
            if 'circuit' in raw_data and isinstance(raw_data['circuit'], dict):
                data = raw_data['circuit']
            else:
                data = raw_data

            # Validate structure
            if 'moduleName' not in data:
                print(f"Warning: No moduleName in {filepath.name}")

            return data

        except Exception as e:
            print(f"Error loading {filepath}: {e}")
            return None

    def _process_circuit(self, circuit_data: Dict, circuit_name: str, context: EasyEDAContext):
        """Process a single circuit and extract components/connections."""
        # Store circuit data
        context.circuits.append(circuit_data)

        # Extract components
        if 'components' in circuit_data:
            for comp in circuit_data['components']:
                # Add circuit prefix to avoid reference conflicts
                # FIXED: Use 'ref' (lowlevel format) instead of 'refDes'
                ref_des = comp.get('ref', comp.get('refDes', ''))
                if ref_des:
                    # Store component with original refDes
                    context.components[ref_des] = {
                        'circuit': circuit_name,
                        'refDes': ref_des,
                        'type': comp.get('type', 'unknown'),
                        'value': comp.get('value', ''),
                        'specs': comp.get('specs', {}),
                        'package': comp.get('package', ''),
                        'notes': comp.get('notes', ''),
                        'pins': self._extract_pins(comp)
                    }

        # Extract connections
        if 'connections' in circuit_data:
            for conn in circuit_data['connections']:
                # Handle different connection formats
                connection = self._normalize_connection(conn, circuit_name)
                if connection:
                    context.connections.append(connection)

        # Extract pinNetMapping if available
        if 'pinNetMapping' in circuit_data:
            for pin_ref, net in circuit_data['pinNetMapping'].items():
                if '.' in pin_ref:
                    comp_ref, pin = pin_ref.split('.', 1)
                    if comp_ref in context.components:
                        # Add net mapping to component
                        if 'net_mappings' not in context.components[comp_ref]:
                            context.components[comp_ref]['net_mappings'] = {}
                        context.components[comp_ref]['net_mappings'][pin] = net

    def _extract_pins(self, component: Dict) -> List[str]:
        """Extract pin numbers from component."""
        pins = []

        # Try to get pins from specs
        if 'specs' in component:
            specs = component['specs']
            if 'pins' in specs:
                pins = specs['pins']
            elif 'pinCount' in specs:
                # Generate sequential pins
                pin_count = int(specs['pinCount'])
                pins = [str(i+1) for i in range(pin_count)]

        # Default pins for common components
        if not pins:
            comp_type = component.get('type', '').lower()
            if comp_type in ['resistor', 'capacitor', 'inductor', 'fuse', 'mov', 'varistor']:
                pins = ['1', '2']
            elif comp_type in ['led', 'diode']:
                pins = ['A', 'K']
            elif comp_type == 'transistor' or comp_type == 'bjt':
                pins = ['B', 'C', 'E']
            elif comp_type == 'mosfet':
                pins = ['G', 'D', 'S']
            elif comp_type == 'bridge_rectifier' or comp_type == 'bridge rectifier':
                pins = ['AC1', 'AC2', 'DC+', 'DC-']
            elif comp_type == 'transformer':
                pins = ['P1', 'P2', 'S1', 'S2']  # Primary and secondary
            elif comp_type == 'relay':
                pins = ['COIL1', 'COIL2', 'NO', 'COM', 'NC']
            elif comp_type == 'crystal' or comp_type == 'oscillator':
                pins = ['1', '2']
            elif comp_type == 'switch' or comp_type == 'button':
                pins = ['1', '2']
            elif comp_type == 'connector':
                # Default 2-pin connector
                pins = ['1', '2']
            elif 'ic' in comp_type or 'regulator' in comp_type:
                # Default 8-pin IC
                pins = [str(i+1) for i in range(8)]

        return pins

    def _normalize_connection(self, conn: Any, circuit_name: str) -> Dict:
        """Normalize connection format."""
        connection = {}

        # Handle dict format
        if isinstance(conn, dict):
            if 'from' in conn and 'to' in conn:
                connection = {
                    'circuit': circuit_name,
                    'from': conn['from'],
                    'to': conn['to'],
                    'net': conn.get('net', '')
                }
            elif 'points' in conn:
                # Handle points array format
                points = conn['points']
                if len(points) >= 2:
                    connection = {
                        'circuit': circuit_name,
                        'from': points[0],
                        'to': points[-1],
                        'points': points,
                        'net': conn.get('net', '')
                    }

        # Handle array format [from, to]
        elif isinstance(conn, list) and len(conn) >= 2:
            connection = {
                'circuit': circuit_name,
                'from': conn[0],
                'to': conn[1],
                'net': ''
            }

        return connection

    def _build_netlist(self, context: EasyEDAContext):
        """Build consolidated netlist from connections and pinNetMapping."""
        nets = {}
        net_counter = 1

        # Process connections
        for conn in context.connections:
            from_point = conn['from']
            to_point = conn['to']

            # Find or create net
            net_name = conn.get('net', '')
            if not net_name:
                # Check if points already belong to a net
                for existing_net, points in nets.items():
                    if from_point in points or to_point in points:
                        net_name = existing_net
                        break

                if not net_name:
                    net_name = f"NET{net_counter}"
                    net_counter += 1

            # Add points to net
            if net_name not in nets:
                nets[net_name] = set()
            nets[net_name].add(from_point)
            nets[net_name].add(to_point)

            # Add intermediate points if available
            if 'points' in conn:
                for point in conn['points']:
                    nets[net_name].add(point)

        # Process pinNetMapping
        for comp_ref, comp_data in context.components.items():
            if 'net_mappings' in comp_data:
                for pin, net_name in comp_data['net_mappings'].items():
                    pin_ref = f"{comp_ref}.{pin}"
                    if net_name not in nets:
                        nets[net_name] = set()
                    nets[net_name].add(pin_ref)

        # Convert sets to lists for JSON serialization
        context.nets = {net: list(points) for net, points in nets.items()}