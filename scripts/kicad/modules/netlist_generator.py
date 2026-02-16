# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Netlist generator module for building circuit connectivity."""

from typing import Dict, Any, List, Set, Tuple, Optional
from collections import defaultdict
import logging

from ..utils.base import PipelineStage, ConversionContext, ValidationError

logger = logging.getLogger(__name__)

class NetlistGenerator(PipelineStage):
    """Generate netlist from connections and pinNetMapping."""

    def process(self, context: ConversionContext) -> ConversionContext:
        """Generate complete netlist from connections."""
        try:
            components = context.components
            connections = context.input_data.get('connections', [])
            pin_net_mapping = context.input_data.get('pinNetMapping', {})

            if not components:
                raise ValidationError("No components found for netlist generation")

            # Build netlist from connections and circuit-level pinNetMapping
            nets = self._build_nets_from_connections(connections, components)

            # Enhance with circuit-level pinNetMapping
            nets = self._enhance_from_circuit_mappings(nets, pin_net_mapping, components)

            # Add power and ground nets
            nets = self._add_power_nets(nets, components)

            # Validate and clean nets
            nets = self._validate_and_clean_nets(nets, components)

            # Generate net classes
            net_classes = self._generate_net_classes(nets)

            # Store in context
            context.netlist = {
                'nets': nets,
                'net_classes': net_classes,
                'statistics': self._generate_statistics(nets)
            }

            logger.info(f"Generated {len(nets)} nets connecting {len(components)} components")
            return context

        except Exception as e:
            return self.handle_error(e, context)

    def _build_nets_from_connections(self, connections: List[Dict[str, Any]],
                                    components: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Build nets from connection data."""
        nets = {}
        net_counter = 1

        for conn in connections:
            net_name = conn.get('net', '')
            points = conn.get('points', [])

            if not points:
                continue

            # Use provided net name or generate one
            if not net_name:
                net_name = f"Net_{net_counter}"
                net_counter += 1

            # Ensure net exists
            if net_name not in nets:
                nets[net_name] = {
                    'name': net_name,
                    'nodes': [],
                    'class': self._determine_net_class(net_name)
                }

            # Add connection points to net
            for point in points:
                if '.' in point:
                    ref_des, pin = point.split('.', 1)
                    if ref_des in components:
                        node = {'ref': ref_des, 'pin': pin}
                        if node not in nets[net_name]['nodes']:
                            nets[net_name]['nodes'].append(node)

        return nets

    def _enhance_from_circuit_mappings(self, nets: Dict[str, Dict[str, Any]],
                                      pin_net_mapping: Dict[str, str],
                                      components: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Enhance nets using circuit-level pinNetMapping."""
        # Process circuit-level pinNetMapping
        for pin_ref, net_name in pin_net_mapping.items():
            if '.' in pin_ref and net_name:
                ref_des, pin = pin_ref.split('.', 1)
                if ref_des in components:
                    # Ensure net exists
                    if net_name not in nets:
                        nets[net_name] = {
                            'name': net_name,
                            'nodes': [],
                            'class': self._determine_net_class(net_name)
                        }

                    # Add node to net
                    node = {'ref': ref_des, 'pin': str(pin)}
                    if node not in nets[net_name]['nodes']:
                        nets[net_name]['nodes'].append(node)

        return nets

    def _add_power_nets(self, nets: Dict[str, Dict[str, Any]],
                        components: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Add standard power nets if not present."""
        # Check for common power net names in existing nets
        power_patterns = ['VCC', 'GND', 'VDD', 'VSS', '+5V', '+3V3', '+12V', '-12V']

        for net_name in list(nets.keys()):
            for pattern in power_patterns:
                if pattern in net_name.upper():
                    nets[net_name]['class'] = 'power'
                    break

        # Ensure GND exists
        if 'GND' not in nets:
            nets['GND'] = {
                'name': 'GND',
                'nodes': [],
                'class': 'power'
            }

        return nets

    def _validate_and_clean_nets(self, nets: Dict[str, Dict[str, Any]],
                                 components: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Validate and clean nets."""
        cleaned_nets = {}

        for net_name, net_data in nets.items():
            nodes = net_data.get('nodes', [])

            # Remove invalid nodes
            valid_nodes = []
            for node in nodes:
                ref = node.get('ref', '')
                pin = node.get('pin', '')

                if ref in components and pin:
                    # Check if pin exists for component
                    comp = components[ref]
                    comp_pins = comp.get('pins', [])

                    # Convert pin to string for comparison
                    pin_str = str(pin)

                    # Accept pin if it's in the component's pin list or pinNetMapping
                    pin_net_mapping = comp.get('pinNetMapping', {})
                    if pin_str in comp_pins or pin_str in pin_net_mapping:
                        valid_nodes.append({'ref': ref, 'pin': pin_str})
                    else:
                        logger.warning(f"Invalid pin {pin_str} for component {ref}")

            # Only keep nets with at least 2 nodes
            if len(valid_nodes) >= 2:
                cleaned_nets[net_name] = {
                    'name': net_name,
                    'nodes': valid_nodes,
                    'class': net_data.get('class', 'signal')
                }
            elif len(valid_nodes) == 1:
                logger.warning(f"Net {net_name} has only one node - may be incomplete")
                # Keep single-node nets but mark them
                cleaned_nets[net_name] = {
                    'name': net_name,
                    'nodes': valid_nodes,
                    'class': net_data.get('class', 'signal'),
                    'incomplete': True
                }

        # Check for duplicate nets (same nodes)
        merged_nets = self._merge_duplicate_nets(cleaned_nets)

        return merged_nets

    def _merge_duplicate_nets(self, nets: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Merge nets that connect the same nodes."""
        node_sets = {}
        merged = {}

        for net_name, net_data in nets.items():
            # Create a frozenset of nodes for comparison
            node_set = frozenset(
                (node['ref'], node['pin'])
                for node in net_data['nodes']
            )

            if node_set in node_sets:
                # Merge with existing net
                existing_net = node_sets[node_set]
                logger.info(f"Merging net {net_name} with {existing_net}")
            else:
                # New unique net
                node_sets[node_set] = net_name
                merged[net_name] = net_data

        return merged

    def _determine_net_class(self, net_name: str) -> str:
        """Determine net class from name."""
        net_name_upper = net_name.upper()

        # Power nets
        power_keywords = ['VCC', 'VDD', 'VSS', 'GND', 'VBAT', '+', '-', 'PWR', 'POWER']
        for keyword in power_keywords:
            if keyword in net_name_upper:
                return 'power'

        # Clock nets
        clock_keywords = ['CLK', 'CLOCK', 'OSC', 'XTAL']
        for keyword in clock_keywords:
            if keyword in net_name_upper:
                return 'clock'

        # Differential pairs
        if net_name_upper.endswith('_P') or net_name_upper.endswith('_N'):
            return 'differential'

        # High-speed signals
        high_speed_keywords = ['USB', 'HDMI', 'PCIE', 'SATA', 'DDR']
        for keyword in high_speed_keywords:
            if keyword in net_name_upper:
                return 'high_speed'

        return 'signal'

    def _generate_net_classes(self, nets: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Generate net class definitions."""
        net_classes = {
            'Default': {
                'name': 'Default',
                'trace_width': 0.25,
                'via_dia': 0.8,
                'via_drill': 0.4,
                'clearance': 0.2,
                'nets': []
            },
            'Power': {
                'name': 'Power',
                'trace_width': 0.4,
                'via_dia': 1.0,
                'via_drill': 0.5,
                'clearance': 0.3,
                'nets': []
            },
            'Clock': {
                'name': 'Clock',
                'trace_width': 0.2,
                'via_dia': 0.6,
                'via_drill': 0.3,
                'clearance': 0.2,
                'nets': []
            }
        }

        # Assign nets to classes
        for net_name, net_data in nets.items():
            net_class = net_data.get('class', 'signal')

            if net_class == 'power':
                net_classes['Power']['nets'].append(net_name)
            elif net_class == 'clock':
                net_classes['Clock']['nets'].append(net_name)
            else:
                net_classes['Default']['nets'].append(net_name)

        return net_classes

    def _generate_statistics(self, nets: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Generate netlist statistics."""
        total_nodes = sum(len(net['nodes']) for net in nets.values())
        incomplete_nets = sum(1 for net in nets.values() if net.get('incomplete', False))

        net_classes = defaultdict(int)
        for net in nets.values():
            net_classes[net.get('class', 'signal')] += 1

        return {
            'total_nets': len(nets),
            'total_nodes': total_nodes,
            'average_nodes_per_net': total_nodes / len(nets) if nets else 0,
            'incomplete_nets': incomplete_nets,
            'net_classes': dict(net_classes)
        }