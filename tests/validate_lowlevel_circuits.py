#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Comprehensive validation script for lowlevel circuit JSON files.
Checks for:
1. Floating components (components with unconnected pins)
2. Single-sided connections (nets with only one pin)
3. Net conflicts (pins connected to multiple different nets)
4. General circuit completeness
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict

class CircuitValidator:
    def __init__(self):
        self.results = []
        self.total_issues = 0

    def validate_circuit_file(self, filepath: str) -> Dict:
        """Validate a single circuit JSON file."""
        circuit_name = os.path.basename(filepath)
        print(f"\n{'='*80}")
        print(f"Validating: {circuit_name}")
        print('='*80)

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
        except Exception as e:
            return {
                'file': circuit_name,
                'error': f'Failed to load JSON: {str(e)}',
                'status': 'FAILED'
            }

        # Extract circuit data
        circuit = data if 'circuit' not in data else data['circuit']

        if not circuit:
            return {
                'file': circuit_name,
                'error': 'No circuit data found',
                'status': 'FAILED'
            }

        components = circuit.get('components', [])
        connections = circuit.get('connections', [])
        nets = circuit.get('nets', [])
        pinNetMapping = circuit.get('pinNetMapping', {})

        print(f"  Components: {len(components)}")
        print(f"  Connections: {len(connections)}")
        print(f"  Nets: {len(nets)}")
        print(f"  PinNetMapping entries: {len(pinNetMapping)}")

        # Run validation checks
        issues = {
            'floating_components': [],
            'floating_pins': [],
            'single_sided_nets': [],
            'net_conflicts': [],
            'empty_connections': [],
            'missing_pinNetMapping': []
        }

        # 1. Check for floating components and pins
        connected_pins = set()

        # Build connected pins from pinNetMapping
        for pin_id in pinNetMapping:
            connected_pins.add(pin_id)

        # Also check connections array
        for conn in connections:
            if 'points' in conn and conn['points']:
                for point in conn['points']:
                    if 'ref' in point and 'pin' in point:
                        pin_id = f"{point['ref']}.{point['pin']}"
                        connected_pins.add(pin_id)
            elif 'from' in conn and 'to' in conn:
                if 'ref' in conn['from'] and 'pin' in conn['from']:
                    pin_id = f"{conn['from']['ref']}.{conn['from']['pin']}"
                    connected_pins.add(pin_id)
                if 'ref' in conn['to'] and 'pin' in conn['to']:
                    pin_id = f"{conn['to']['ref']}.{conn['to']['pin']}"
                    connected_pins.add(pin_id)

        # Check each component for floating pins
        for comp in components:
            ref = comp.get('ref', '')
            pins = comp.get('pins', [])
            comp_type = comp.get('type', '')
            value = comp.get('value', '')

            # Skip non-electrical components
            if comp_type in ['heatsink', 'mounting_hole', 'fiducial', 'mechanical']:
                continue
            if ref.startswith('HS') or ref.startswith('MH') or ref.startswith('FID'):
                continue

            floating_pins = []
            for pin in pins:
                pin_num = pin.get('number', '')
                pin_id = f"{ref}.{pin_num}"
                if pin_id not in connected_pins:
                    # Check if it's a legitimate unconnected pin
                    pin_type = pin.get('type', '').lower()
                    if pin_type not in ['nc', 'not_connected', 'n/c']:
                        floating_pins.append(pin_num)

            if floating_pins:
                if len(floating_pins) == len(pins):
                    issues['floating_components'].append(f"{ref} ({value}) - ALL {len(pins)} pins unconnected")
                else:
                    issues['floating_pins'].append(f"{ref} ({value}) - pins {', '.join(floating_pins)} unconnected")

        # 2. Check for single-sided nets
        net_connections = defaultdict(set)

        for pin_id, net_name in pinNetMapping.items():
            net_connections[net_name].add(pin_id)

        for net_name, pins in net_connections.items():
            # Skip external interface nets
            if any(ext in net_name.lower() for ext in ['external', 'output', 'input', 'connector', 'enable', 'uart', 'spi', 'i2c']):
                continue
            if len(pins) == 1:
                issues['single_sided_nets'].append(f"{net_name} - only connected to {list(pins)[0]}")

        # 3. Check for net conflicts
        pin_to_nets = defaultdict(set)

        for pin_id, net_name in pinNetMapping.items():
            pin_to_nets[pin_id].add(net_name)

        for pin_id, nets in pin_to_nets.items():
            if len(nets) > 1:
                issues['net_conflicts'].append(f"{pin_id} connected to multiple nets: {', '.join(sorted(nets))}")

        # 4. Check for empty connections
        for i, conn in enumerate(connections):
            if 'points' in conn and not conn['points']:
                issues['empty_connections'].append(f"Connection {i+1} has empty points array")
            elif 'from' in conn and 'to' in conn:
                if not conn.get('from') or not conn.get('to'):
                    issues['empty_connections'].append(f"Connection {i+1} has empty from/to")

        # 5. Check for missing pinNetMapping entries
        for comp in components:
            ref = comp.get('ref', '')
            pins = comp.get('pins', [])
            comp_type = comp.get('type', '')

            # Skip non-electrical components
            if comp_type in ['heatsink', 'mounting_hole', 'fiducial', 'mechanical']:
                continue
            if ref.startswith('HS') or ref.startswith('MH') or ref.startswith('FID'):
                continue

            for pin in pins:
                pin_num = pin.get('number', '')
                pin_type = pin.get('type', '').lower()
                if pin_type not in ['nc', 'not_connected', 'n/c']:
                    pin_id = f"{ref}.{pin_num}"
                    if pin_id not in pinNetMapping:
                        issues['missing_pinNetMapping'].append(pin_id)

        # Calculate totals
        total_issues = sum(len(v) for v in issues.values())

        # Determine status
        if total_issues == 0:
            status = 'PERFECT'
            status_symbol = '✅'
        elif issues['floating_components'] or issues['net_conflicts']:
            status = 'CRITICAL'
            status_symbol = '❌'
        elif issues['floating_pins'] or issues['single_sided_nets']:
            status = 'WARNING'
            status_symbol = '⚠️'
        else:
            status = 'MINOR'
            status_symbol = '⚡'

        # Print issues
        print(f"\n  Status: {status_symbol} {status}")

        if total_issues > 0:
            print(f"  Total Issues Found: {total_issues}")

            if issues['floating_components']:
                print(f"\n  ❌ Floating Components ({len(issues['floating_components'])}):")
                for issue in issues['floating_components'][:5]:
                    print(f"    - {issue}")
                if len(issues['floating_components']) > 5:
                    print(f"    ... and {len(issues['floating_components'])-5} more")

            if issues['floating_pins']:
                print(f"\n  ⚠️  Floating Pins ({len(issues['floating_pins'])}):")
                for issue in issues['floating_pins'][:5]:
                    print(f"    - {issue}")
                if len(issues['floating_pins']) > 5:
                    print(f"    ... and {len(issues['floating_pins'])-5} more")

            if issues['net_conflicts']:
                print(f"\n  ❌ Net Conflicts ({len(issues['net_conflicts'])}):")
                for issue in issues['net_conflicts'][:5]:
                    print(f"    - {issue}")
                if len(issues['net_conflicts']) > 5:
                    print(f"    ... and {len(issues['net_conflicts'])-5} more")

            if issues['single_sided_nets']:
                print(f"\n  ⚠️  Single-Sided Nets ({len(issues['single_sided_nets'])}):")
                for issue in issues['single_sided_nets'][:5]:
                    print(f"    - {issue}")
                if len(issues['single_sided_nets']) > 5:
                    print(f"    ... and {len(issues['single_sided_nets'])-5} more")

            if issues['empty_connections']:
                print(f"\n  ⚡ Empty Connections ({len(issues['empty_connections'])}):")
                for issue in issues['empty_connections'][:5]:
                    print(f"    - {issue}")
                if len(issues['empty_connections']) > 5:
                    print(f"    ... and {len(issues['empty_connections'])-5} more")

            if issues['missing_pinNetMapping']:
                print(f"\n  ⚡ Missing PinNetMapping ({len(issues['missing_pinNetMapping'])}):")
                for issue in issues['missing_pinNetMapping'][:5]:
                    print(f"    - {issue}")
                if len(issues['missing_pinNetMapping']) > 5:
                    print(f"    ... and {len(issues['missing_pinNetMapping'])-5} more")
        else:
            print("  ✅ No issues found - circuit is complete and valid!")

        self.total_issues += total_issues

        return {
            'file': circuit_name,
            'status': status,
            'components': len(components),
            'connections': len(connections),
            'nets': len(nets),
            'issues': issues,
            'total_issues': total_issues
        }

    def validate_directory(self, directory: str):
        """Validate all JSON files in a lowlevel directory."""
        json_files = list(Path(directory).glob('*.json'))

        if not json_files:
            print(f"No JSON files found in {directory}")
            return

        print(f"\nFound {len(json_files)} circuit files to validate")

        for filepath in sorted(json_files):
            result = self.validate_circuit_file(str(filepath))
            self.results.append(result)

        self.print_summary()

    def print_summary(self):
        """Print validation summary."""
        print("\n" + "="*80)
        print("VALIDATION SUMMARY")
        print("="*80)

        perfect_circuits = [r for r in self.results if r.get('status') == 'PERFECT']
        warning_circuits = [r for r in self.results if r.get('status') == 'WARNING']
        critical_circuits = [r for r in self.results if r.get('status') == 'CRITICAL']
        failed_circuits = [r for r in self.results if r.get('status') == 'FAILED']

        print(f"\nTotal Circuits: {len(self.results)}")
        print(f"  ✅ Perfect: {len(perfect_circuits)}")
        print(f"  ⚠️  Warning: {len(warning_circuits)}")
        print(f"  ❌ Critical: {len(critical_circuits)}")
        print(f"  💀 Failed: {len(failed_circuits)}")

        total_components = sum(r.get('components', 0) for r in self.results)
        total_connections = sum(r.get('connections', 0) for r in self.results)
        total_nets = sum(r.get('nets', 0) for r in self.results)

        print(f"\nTotal Statistics:")
        print(f"  Components: {total_components}")
        print(f"  Connections: {total_connections}")
        print(f"  Nets: {total_nets}")
        print(f"  Issues Found: {self.total_issues}")

        if critical_circuits:
            print(f"\n⚠️  CRITICAL ISSUES IN:")
            for r in critical_circuits:
                print(f"  - {r['file']}")
                issues = r.get('issues', {})
                if issues.get('floating_components'):
                    print(f"    • {len(issues['floating_components'])} floating components")
                if issues.get('net_conflicts'):
                    print(f"    • {len(issues['net_conflicts'])} net conflicts")

        if self.total_issues == 0:
            print("\n🎉 ALL CIRCUITS ARE PERFECT! Ready for manufacturing!")
        elif len(critical_circuits) == 0:
            print("\n✅ No critical issues. Circuits are manufacturable with minor warnings.")
        else:
            print(f"\n❌ {len(critical_circuits)} circuits have critical issues that must be fixed!")

        print("\n" + "="*80)

def main():
    """Main function."""
    # Find the most recent output directory
    output_dir = Path('./output')

    if not output_dir.exists():
        print("No output directory found!")
        sys.exit(1)

    # Get the most recent project
    project_dirs = sorted([d for d in output_dir.iterdir() if d.is_dir()],
                         key=lambda x: x.stat().st_mtime,
                         reverse=True)

    if not project_dirs:
        print("No project directories found!")
        sys.exit(1)

    latest_project = project_dirs[0]
    lowlevel_dir = latest_project / 'lowlevel'

    if not lowlevel_dir.exists():
        print(f"No lowlevel directory found in {latest_project}")
        sys.exit(1)

    print(f"Validating circuits in: {lowlevel_dir}")

    validator = CircuitValidator()
    validator.validate_directory(str(lowlevel_dir))

if __name__ == "__main__":
    main()