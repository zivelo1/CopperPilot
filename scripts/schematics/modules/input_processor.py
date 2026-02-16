# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Input processing module for schematic generator."""
import json
from pathlib import Path
from typing import Dict, List, Any
from .utils import SchematicContext, Component, Net, Point, Rectangle, get_component_type_category

class InputProcessor:
    """Process input JSON files from lowlevel folder."""

    def __init__(self, config: Dict = None):
        self.config = config or {}

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Process input files and populate context."""
        print("\n=== Stage 1: Input Processing ===")

        # Load circuit data
        if not context.input_path or not context.input_path.exists():
            context.errors.append(f"Input file not found: {context.input_path}")
            return context

        try:
            with open(context.input_path, 'r') as f:
                raw_data = json.load(f)

            # CRITICAL: Handle wrapped circuit format {"circuit": {...}}
            if 'circuit' in raw_data and isinstance(raw_data['circuit'], dict):
                context.circuit_data = raw_data['circuit']
            else:
                context.circuit_data = raw_data
        except Exception as e:
            context.errors.append(f"Failed to load circuit data: {e}")
            return context

        # Extract components
        self._extract_components(context)

        # Extract nets
        self._extract_nets(context)

        # Statistics
        context.stats['input'] = {
            'components': len(context.components),
            'nets': len(context.nets),
            'total_pins': sum(len(c.pins) for c in context.components.values())
        }

        print(f"Loaded {len(context.components)} components")
        print(f"Found {len(context.nets)} nets")

        return context

    def _extract_components(self, context: SchematicContext):
        """Extract components from circuit data."""
        if 'components' not in context.circuit_data:
            context.warnings.append("No components found in circuit data")
            return

        # CRITICAL: Build pin number to name mapping for all components
        context.pin_number_to_name = {}

        for comp_data in context.circuit_data['components']:
            # CRITICAL FIX: Handle both 'ref' and 'refDes' fields
            ref_des = comp_data.get('ref', comp_data.get('refDes', ''))
            if not ref_des:
                continue

            comp_type = comp_data.get('type', 'unknown')
            value = comp_data.get('value', '')

            # Create component
            component = Component(
                ref_des=ref_des,
                type=comp_type,
                value=value,
                position=Point(0, 0),  # Will be set by layout engine
                bounds=Rectangle(0, 0, 0, 0),  # Will be set by layout engine
                specs=comp_data.get('specs') or {}
            )

            # Determine component category
            component.symbol = get_component_type_category(comp_type)

            # Store component
            context.components[ref_des] = component

            # UNIVERSAL FIX: Dynamically create pins from lowlevel JSON data
            # Works for ANY component type with ANY number of pins (2 to 256+)
            # Handles: resistors (2-pin), potentiometers (3-pin), ICs (8-64 pins),
            #          connectors (any pins), transformers (multi-winding), etc.
            if 'pins' in comp_data:
                for pin in comp_data['pins']:
                    pin_number = pin.get('number', '')
                    pin_name = pin.get('name', '')
                    pin_type = pin.get('type', 'passive')

                    if pin_number:
                        final_pin_type = pin_type
                        if pin_type == 'no_connect' or 'nc' in pin_name.lower() or 'no_connect' in pin_name.lower():
                            final_pin_type = 'unconnected'

                        # Create actual Pin object (position will be set by layout engine)
                        component.add_pin(
                            pin_number=pin_number,
                            name=pin_name or pin_number,  # Use number as name if no name
                            position=Point(0, 0),  # Layout engine will set actual position
                            pin_type=final_pin_type
                        )

                        # Store mapping: "Q1.1" -> "Q1.G", etc.
                        if pin_name:
                            context.pin_number_to_name[f"{ref_des}.{pin_number}"] = f"{ref_des}.{pin_name}"

    def _extract_nets(self, context: SchematicContext):
        """Extract nets from circuit data."""
        # First try connections field
        if 'connections' in context.circuit_data:
            self._process_connections(context)

        # Also check for pinNetMapping
        if 'pinNetMapping' in context.circuit_data:
            self._process_pin_net_mapping(context)

        # Deduplicate and consolidate nets
        self._consolidate_nets(context)

    def _process_connections(self, context: SchematicContext):
        """Process connections to build nets."""
        connections = context.circuit_data.get('connections', [])

        for conn in connections:
            net_name = None
            pins = []

            # Handle different connection formats
            if isinstance(conn, dict):
                if 'net' in conn:
                    net_name = conn['net']

                # Extract pins from various formats
                if 'from' in conn and 'to' in conn:
                    pins = [conn['from'], conn['to']]
                elif 'points' in conn:
                    pins = conn['points']
                elif 'pins' in conn:
                    pins = conn['pins']

            elif isinstance(conn, list):
                pins = conn

            # Create or update net
            if pins:
                if not net_name:
                    # Generate net name from first pin
                    net_name = f"NET_{len(context.nets) + 1}"

                if net_name not in context.nets:
                    context.nets[net_name] = Net(name=net_name)

                # Add all pins to net
                for pin_ref in pins:
                    if '.' in pin_ref:
                        # CRITICAL: Convert numeric pin refs to named pin refs (Q1.1 -> Q1.G)
                        if pin_ref in context.pin_number_to_name:
                            pin_ref = context.pin_number_to_name[pin_ref]

                        comp_ref, pin_num = pin_ref.split('.', 1)
                        if comp_ref in context.components:
                            context.nets[net_name].add_connection(comp_ref, pin_num)

    def _process_pin_net_mapping(self, context: SchematicContext):
        """Process pinNetMapping to build nets."""
        pin_net_mapping = context.circuit_data.get('pinNetMapping', {})

        for pin_ref, net_name in pin_net_mapping.items():
            if '.' in pin_ref:
                # CRITICAL: Convert numeric pin refs to named pin refs (Q1.1 -> Q1.G)
                if pin_ref in context.pin_number_to_name:
                    pin_ref = context.pin_number_to_name[pin_ref]

                comp_ref, pin_num = pin_ref.split('.', 1)

                if comp_ref in context.components:
                    # Create net if it doesn't exist
                    if net_name not in context.nets:
                        context.nets[net_name] = Net(name=net_name)

                    # Add connection
                    context.nets[net_name].add_connection(comp_ref, pin_num)

    def _consolidate_nets(self, context: SchematicContext):
        """Consolidate and deduplicate nets."""
        # Identify power and ground nets
        for net_name, net in context.nets.items():
            net_lower = net_name.lower()

            if any(pwr in net_lower for pwr in ['vcc', 'vdd', 'v+', '+5v', '+12v', '+3.3v']):
                net.is_power = True
                net.color = 'red'
            elif any(gnd in net_lower for gnd in ['gnd', 'ground', 'vss', 'v-', '0v']):
                net.is_ground = True
                net.color = 'black'

        # Remove duplicate connections within each net
        for net in context.nets.values():
            net.pins = list(set(net.pins))

    def validate_input(self, context: SchematicContext) -> bool:
        """Validate input data."""
        if not context.components:
            context.errors.append("No components found in input")
            return False

        if not context.nets:
            context.warnings.append("No nets found - circuit may be disconnected")

        # Check for components without connections
        connected_components = set()
        for net in context.nets.values():
            for comp_ref, _ in net.pins:
                connected_components.add(comp_ref)

        for comp_ref in context.components:
            if comp_ref not in connected_components:
                context.warnings.append(f"Component {comp_ref} has no connections")

        return len(context.errors) == 0