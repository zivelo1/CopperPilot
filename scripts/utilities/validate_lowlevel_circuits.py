#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Comprehensive Circuit Validation Tool
Analyzes lowlevel JSON files to ensure complete, working circuits
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict

class CircuitValidator:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []
        self.stats = {}

    def validate_circuit_file(self, file_path: Path) -> Dict:
        """Validate a single circuit file."""
        print(f"\n{'='*80}")
        print(f"ANALYZING: {file_path.name}")
        print(f"{'='*80}")

        # Reset for each file
        self.errors = []
        self.warnings = []
        self.info = []
        self.stats = {}

        try:
            with open(file_path, 'r') as f:
                circuit_data = json.load(f)

            # Extract circuit info
            circuit_name = circuit_data.get('moduleName', 'Unknown')
            print(f"Circuit Name: {circuit_name}")

            # 1. Validate components
            components = self._validate_components(circuit_data)

            # 2. Validate connections
            connections = self._validate_connections(circuit_data)

            # 3. Validate pinNetMapping
            pin_mapping = self._validate_pin_mapping(circuit_data)

            # 4. Cross-validate connectivity
            self._cross_validate_connectivity(components, connections, pin_mapping)

            # 5. Check for floating components
            self._check_floating_components(components, connections, pin_mapping)

            # 6. Check for single-ended connections
            self._check_single_ended_connections(connections, pin_mapping)

            # 7. Validate net consistency
            self._validate_net_consistency(circuit_data, connections, pin_mapping)

            # 8. Check critical nets
            self._check_critical_nets(connections, pin_mapping)

            # Print results
            self._print_results()

            return {
                'file': file_path.name,
                'circuit_name': circuit_name,
                'errors': len(self.errors),
                'warnings': len(self.warnings),
                'stats': self.stats,
                'valid': len(self.errors) == 0
            }

        except Exception as e:
            print(f"❌ ERROR: Failed to analyze file: {e}")
            return {
                'file': file_path.name,
                'circuit_name': circuit_name if 'circuit_name' in locals() else 'Unknown',
                'errors': 999,
                'warnings': 0,
                'stats': {},
                'valid': False
            }

    def _validate_components(self, circuit_data: Dict) -> Dict:
        """Validate components structure and content."""
        components = {}

        if 'components' not in circuit_data:
            self.errors.append("No 'components' field found")
            return components

        comp_list = circuit_data['components']

        # Handle both list and dict formats
        if isinstance(comp_list, list):
            for comp in comp_list:
                if 'refDes' not in comp:
                    self.errors.append(f"Component missing 'refDes': {comp}")
                    continue

                ref = comp['refDes']
                components[ref] = comp

                # Validate component fields
                if 'type' not in comp:
                    self.warnings.append(f"{ref}: Missing 'type' field")
                if 'value' not in comp:
                    self.warnings.append(f"{ref}: Missing 'value' field")

        elif isinstance(comp_list, dict):
            components = comp_list
            for ref, comp in components.items():
                if 'type' not in comp:
                    self.warnings.append(f"{ref}: Missing 'type' field")
                if 'value' not in comp:
                    self.warnings.append(f"{ref}: Missing 'value' field")

        self.stats['total_components'] = len(components)
        print(f"  Components: {len(components)}")

        # Count component types
        type_counts = defaultdict(int)
        for comp in components.values():
            comp_type = comp.get('type', 'unknown')
            type_counts[comp_type] += 1

        print(f"  Component Types:")
        for comp_type, count in sorted(type_counts.items()):
            print(f"    - {comp_type}: {count}")

        return components

    def _validate_connections(self, circuit_data: Dict) -> List:
        """Validate connections structure."""
        connections = []

        if 'connections' not in circuit_data:
            self.warnings.append("No 'connections' field found")
            return connections

        connections = circuit_data['connections']

        if not isinstance(connections, list):
            self.errors.append("'connections' must be a list")
            return []

        self.stats['total_connections'] = len(connections)
        print(f"  Connections: {len(connections)}")

        # Validate each connection
        net_points = defaultdict(set)
        for idx, conn in enumerate(connections):
            if 'net' not in conn:
                self.errors.append(f"Connection {idx}: Missing 'net' field")
                continue

            net = conn['net']

            if 'points' not in conn:
                self.errors.append(f"Connection {idx} (net {net}): Missing 'points' field")
                continue

            points = conn['points']
            if not isinstance(points, list):
                self.errors.append(f"Connection {idx} (net {net}): 'points' must be a list")
                continue

            if len(points) < 2:
                self.warnings.append(f"Net '{net}': Only {len(points)} connection point(s)")

            for point in points:
                net_points[net].add(point)

        self.stats['total_nets'] = len(net_points)
        print(f"  Unique Nets: {len(net_points)}")

        return connections

    def _validate_pin_mapping(self, circuit_data: Dict) -> Dict:
        """Validate pinNetMapping structure."""
        pin_mapping = {}

        if 'pinNetMapping' not in circuit_data:
            self.warnings.append("No 'pinNetMapping' field found")
            return pin_mapping

        raw_pin_mapping = circuit_data['pinNetMapping']

        if not isinstance(raw_pin_mapping, dict):
            self.errors.append("'pinNetMapping' must be a dictionary")
            return {}

        # Check if it's flat format (component.pin: net) or nested format
        if raw_pin_mapping:
            first_value = next(iter(raw_pin_mapping.values()))
            if isinstance(first_value, str):
                # Flat format - convert to nested for consistency
                for comp_pin, net in raw_pin_mapping.items():
                    if '.' in comp_pin:
                        comp_ref, pin_num = comp_pin.split('.', 1)
                        if comp_ref not in pin_mapping:
                            pin_mapping[comp_ref] = {}
                        pin_mapping[comp_ref][pin_num] = net
                    else:
                        self.errors.append(f"Invalid pin mapping key: {comp_pin}")
            else:
                # Already nested format
                pin_mapping = raw_pin_mapping

        # Count total pins mapped
        total_pins = sum(len(pins) if isinstance(pins, dict) else 1 for pins in pin_mapping.values())

        self.stats['total_pins_mapped'] = total_pins
        print(f"  Pin Mappings: {total_pins} pins across {len(pin_mapping)} components")

        return pin_mapping

    def _cross_validate_connectivity(self, components: Dict, connections: List, pin_mapping: Dict):
        """Cross-validate connectivity between different data structures."""
        # Build net-to-pins mapping from connections
        conn_nets = defaultdict(set)
        for conn in connections:
            if 'net' in conn and 'points' in conn:
                net = conn['net']
                for point in conn['points']:
                    conn_nets[net].add(point)

        # Build net-to-pins mapping from pinNetMapping
        pin_nets = defaultdict(set)
        for comp_ref, pins in pin_mapping.items():
            for pin_num, net in pins.items():
                if net and net != 'NC':
                    pin_nets[net].add(f"{comp_ref}.{pin_num}")

        # Compare the two
        all_nets = set(conn_nets.keys()) | set(pin_nets.keys())

        for net in all_nets:
            conn_points = conn_nets.get(net, set())
            pin_points = pin_nets.get(net, set())

            if conn_points and not pin_points:
                self.warnings.append(f"Net '{net}': In connections but not in pinNetMapping")
            elif pin_points and not conn_points:
                self.warnings.append(f"Net '{net}': In pinNetMapping but not in connections")
            elif conn_points != pin_points:
                # Check if it's just a formatting difference
                conn_normalized = {p.replace('.', '_') for p in conn_points}
                pin_normalized = {p.replace('.', '_') for p in pin_points}
                if conn_normalized != pin_normalized:
                    self.info.append(f"Net '{net}': Point mismatch between connections and pinNetMapping")

    def _check_floating_components(self, components: Dict, connections: List, pin_mapping: Dict):
        """Check for components with no connections."""
        # Get all connected components
        connected_comps = set()

        # From connections
        for conn in connections:
            if 'points' in conn:
                for point in conn['points']:
                    if '.' in point:
                        comp_ref = point.split('.')[0]
                        connected_comps.add(comp_ref)

        # From pinNetMapping
        for comp_ref in pin_mapping.keys():
            if any(net and net != 'NC' for net in pin_mapping[comp_ref].values()):
                connected_comps.add(comp_ref)

        # Find floating components
        floating = []
        for comp_ref in components.keys():
            if comp_ref not in connected_comps:
                comp_type = components[comp_ref].get('type', 'unknown')
                # Some component types are allowed to float
                if comp_type not in ['mounting_hole', 'fiducial', 'test_point', 'heatsink']:
                    floating.append(f"{comp_ref} ({comp_type})")

        if floating:
            self.errors.append(f"FLOATING COMPONENTS ({len(floating)}): {', '.join(floating)}")

        self.stats['floating_components'] = len(floating)
        print(f"  Floating Components: {len(floating)}")

    def _check_single_ended_connections(self, connections: List, pin_mapping: Dict):
        """Check for nets with only one connection point."""
        net_connection_counts = defaultdict(set)

        # Count from connections
        for conn in connections:
            if 'net' in conn and 'points' in conn:
                net = conn['net']
                for point in conn['points']:
                    net_connection_counts[net].add(point)

        # Count from pinNetMapping
        for comp_ref, pins in pin_mapping.items():
            for pin_num, net in pins.items():
                if net and net != 'NC':
                    net_connection_counts[net].add(f"{comp_ref}.{pin_num}")

        # Find single-ended nets
        single_ended = []
        for net, points in net_connection_counts.items():
            if len(points) == 1:
                single_ended.append(f"{net} (only {list(points)[0]})")

        if single_ended:
            self.errors.append(f"SINGLE-ENDED NETS ({len(single_ended)}): {', '.join(single_ended[:10])}")
            if len(single_ended) > 10:
                self.errors.append(f"  ... and {len(single_ended) - 10} more")

        self.stats['single_ended_nets'] = len(single_ended)
        print(f"  Single-Ended Nets: {len(single_ended)}")

    def _validate_net_consistency(self, circuit_data: Dict, connections: List, pin_mapping: Dict):
        """Validate that nets are consistent across all data structures."""
        # Check if 'nets' field exists
        if 'nets' in circuit_data:
            defined_nets = set(circuit_data['nets'])

            # Get all nets from connections
            conn_nets = set()
            for conn in connections:
                if 'net' in conn:
                    conn_nets.add(conn['net'])

            # Get all nets from pinNetMapping
            pin_nets = set()
            for pins in pin_mapping.values():
                for net in pins.values():
                    if net and net != 'NC':
                        pin_nets.add(net)

            # Check consistency
            all_used_nets = conn_nets | pin_nets

            undefined_nets = all_used_nets - defined_nets
            if undefined_nets:
                self.warnings.append(f"Nets used but not defined: {', '.join(sorted(undefined_nets)[:5])}")

            unused_nets = defined_nets - all_used_nets
            if unused_nets:
                self.info.append(f"Nets defined but not used: {', '.join(sorted(unused_nets)[:5])}")

    def _check_critical_nets(self, connections: List, pin_mapping: Dict):
        """Check for critical nets like power and ground."""
        # Get all nets
        all_nets = set()

        for conn in connections:
            if 'net' in conn:
                all_nets.add(conn['net'])

        for pins in pin_mapping.values():
            for net in pins.values():
                if net and net != 'NC':
                    all_nets.add(net)

        # Check for power nets
        power_nets = [net for net in all_nets if any(pwr in net.upper() for pwr in ['VCC', 'VDD', '+5V', '+3.3V', '+12V', '+24V', 'PWR'])]
        ground_nets = [net for net in all_nets if any(gnd in net.upper() for gnd in ['GND', 'VSS', 'GROUND', '0V'])]

        if not power_nets:
            self.warnings.append("No power nets found (VCC, VDD, etc.)")
        else:
            self.info.append(f"Power nets found: {', '.join(power_nets)}")

        if not ground_nets:
            self.warnings.append("No ground nets found (GND, VSS, etc.)")
        else:
            self.info.append(f"Ground nets found: {', '.join(ground_nets)}")

        print(f"  Power Nets: {len(power_nets)}")
        print(f"  Ground Nets: {len(ground_nets)}")

    def _print_results(self):
        """Print validation results."""
        print(f"\n  VALIDATION RESULTS:")
        print(f"  {'─'*40}")

        if self.errors:
            print(f"\n  ❌ ERRORS ({len(self.errors)}):")
            for error in self.errors[:10]:
                print(f"     • {error}")
            if len(self.errors) > 10:
                print(f"     ... and {len(self.errors) - 10} more errors")

        if self.warnings:
            print(f"\n  ⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings[:10]:
                print(f"     • {warning}")
            if len(self.warnings) > 10:
                print(f"     ... and {len(self.warnings) - 10} more warnings")

        if self.info:
            print(f"\n  ℹ️  INFO ({len(self.info)}):")
            for info in self.info[:5]:
                print(f"     • {info}")

        if not self.errors:
            print(f"\n  ✅ CIRCUIT IS VALID - No errors found!")
        else:
            print(f"\n  ❌ CIRCUIT HAS ISSUES - {len(self.errors)} error(s) found")

        print(f"  {'─'*40}")


def main():
    """Main validation function."""
    if len(sys.argv) < 2:
        print("Usage: python validate_lowlevel_circuits.py <lowlevel_folder>")
        sys.exit(1)

    lowlevel_path = Path(sys.argv[1])

    if not lowlevel_path.exists():
        print(f"Error: Path {lowlevel_path} does not exist")
        sys.exit(1)

    # Find all circuit JSON files
    circuit_files = sorted(lowlevel_path.glob("CIRCUIT_*.json"))

    if not circuit_files:
        print(f"No CIRCUIT_*.json files found in {lowlevel_path}")
        sys.exit(1)

    print(f"\n{'='*80}")
    print(f"CIRCUIT VALIDATION REPORT")
    print(f"{'='*80}")
    print(f"Analyzing {len(circuit_files)} circuit file(s) in: {lowlevel_path}")

    validator = CircuitValidator()
    results = []

    for circuit_file in circuit_files:
        result = validator.validate_circuit_file(circuit_file)
        results.append(result)

    # Print summary
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")

    total_errors = sum(r['errors'] for r in results)
    total_warnings = sum(r['warnings'] for r in results)
    valid_circuits = sum(1 for r in results if r['valid'])

    print(f"\nTotal Circuits: {len(results)}")
    print(f"Valid Circuits: {valid_circuits}/{len(results)}")
    print(f"Total Errors: {total_errors}")
    print(f"Total Warnings: {total_warnings}")

    print(f"\nCircuit Status:")
    for result in results:
        status = "✅ VALID" if result['valid'] else f"❌ INVALID ({result['errors']} errors)"
        print(f"  • {result['circuit_name']}: {status}")

    if valid_circuits == len(results):
        print(f"\n✅ ALL CIRCUITS ARE VALID!")
    else:
        print(f"\n❌ {len(results) - valid_circuits} CIRCUIT(S) HAVE ISSUES")

    sys.exit(0 if valid_circuits == len(results) else 1)


if __name__ == "__main__":
    main()