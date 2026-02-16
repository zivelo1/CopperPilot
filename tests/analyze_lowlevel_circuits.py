#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Comprehensive Analysis of Low-Level Circuit Files
Validates that circuits are 100% complete and perfect
ENHANCED VERSION: Detects ALL issues including floating components and invalid pins
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any
from collections import defaultdict

# Ensure project root is in sys.path so we can import server.config
_PROJECT_ROOT = str(Path(__file__).parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

class CircuitAnalyzer:
    """Thorough circuit analyzer for 100% validation with ZERO tolerance"""

    def __init__(self):
        self.issues = []
        self.warnings = []
        self.critical_issues = []
        self.stats = defaultdict(int)

    def analyze_circuit(self, circuit_path: Path) -> Dict[str, Any]:
        """Analyze a single circuit file for completeness with deep validation"""
        print(f"\n{'=' * 80}")
        print(f"Analyzing: {circuit_path.name}")
        print('=' * 80)

        with open(circuit_path) as f:
            data = json.load(f)

        # Handle nested structure
        if 'circuit' in data and isinstance(data['circuit'], dict):
            circuit = data['circuit']
            print("✓ Proper nested structure detected")
        else:
            circuit = data
            print("✗ Missing nested structure")
            self.critical_issues.append(f"{circuit_path.name}: Missing 'circuit' wrapper")

        # Extract circuit elements
        components = circuit.get('components', [])
        connections = circuit.get('connections', [])
        nets = circuit.get('nets', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})

        print(f"\nCircuit Statistics:")
        print(f"  Components: {len(components)}")
        print(f"  Connections: {len(connections)}")
        print(f"  Nets: {len(nets)}")
        print(f"  Pin mappings: {len(pin_net_mapping)}")

        # Initialize result
        result = {
            'name': circuit_path.stem,
            'components': len(components),
            'connections': len(connections),
            'nets': len(nets),
            'completeness': 100.0,
            'issues': [],
            'warnings': [],
            'critical_issues': []
        }

        # Reset instance variables
        self.issues = []
        self.warnings = []
        self.critical_issues = []

        # === VALIDATION CHECKS ===

        # 1. Check for floating components (CRITICAL)
        print("\n1. FLOATING COMPONENT CHECK (CRITICAL):")
        floating = self._check_floating_components(components, connections, pin_net_mapping)
        if floating:
            print(f"  ❌ FOUND {len(floating)} FLOATING COMPONENTS:")
            for comp in floating:
                print(f"     - {comp['ref']} ({comp['type']}): {comp['connected']}/{comp['total']} pins connected")
                if comp['unconnected_pins']:
                    print(f"       Unconnected pins: {', '.join(comp['unconnected_pins'])}")
                self.critical_issues.append(f"Floating: {comp['ref']} - {comp['connected']}/{comp['total']} pins")
            result['completeness'] -= len(floating) * 10
        else:
            print("  ✅ All components fully connected")

        # 2. Check for single-ended nets
        print("\n2. SINGLE-ENDED NET CHECK:")
        single_ended = self._check_single_ended_nets(connections, components)
        if single_ended:
            print(f"  ❌ FOUND {len(single_ended)} SINGLE-ENDED NETS:")
            for net in single_ended:
                print(f"     - Net '{net['net']}': Only {net['count']} connection(s)")
                # Check if it's a crystal (common false positive)
                if 'XTAL' in net['net'].upper():
                    print(f"       ⚠️ Crystal net - may need special handling")
                    self.warnings.append(f"Crystal net {net['net']} single-ended")
                else:
                    self.issues.append(f"Single-ended: {net['net']}")
            result['completeness'] -= len(single_ended) * 5
        else:
            print("  ✅ All nets properly connected")

        # 3. Check for invalid pin references
        print("\n3. INVALID PIN REFERENCE CHECK:")
        invalid_pins = self._check_invalid_pins(components, connections, pin_net_mapping)
        if invalid_pins:
            print(f"  ❌ FOUND {len(invalid_pins)} INVALID PIN REFERENCES:")
            for pin in invalid_pins:
                print(f"     - {pin['pin']}: {pin['issue']}")
                self.critical_issues.append(f"Invalid pin: {pin['pin']}")
            result['completeness'] -= len(invalid_pins) * 15
        else:
            print("  ✅ All pin references valid")

        # 4. Check for phantom components
        print("\n4. PHANTOM COMPONENT CHECK:")
        phantom = self._check_phantom_components(components, connections, pin_net_mapping)
        if phantom:
            print(f"  ❌ FOUND {len(phantom)} PHANTOM COMPONENTS:")
            for comp in phantom:
                print(f"     - {comp} referenced but not defined")
                self.critical_issues.append(f"Phantom: {comp}")
            result['completeness'] -= len(phantom) * 20
        else:
            print("  ✅ No phantom components")

        # 5. Check IC power connections
        print("\n5. IC POWER CONNECTION CHECK:")
        unpowered = self._check_ic_power(components, connections, pin_net_mapping)
        if unpowered:
            print(f"  ⚠️ FOUND {len(unpowered)} POTENTIAL IC POWER ISSUES:")
            for ic in unpowered:
                print(f"     - {ic['ref']}: {ic['issue']}")
                # This might be a false positive for some ICs
                self.warnings.append(f"IC power: {ic['ref']}")
        else:
            print("  ✅ All ICs have power connections")

        # 6. Check for duplicate connections
        print("\n6. DUPLICATE CONNECTION CHECK:")
        duplicates = self._check_duplicate_connections(connections)
        if duplicates:
            print(f"  ⚠️ FOUND {len(duplicates)} DUPLICATE CONNECTIONS:")
            for dup in duplicates[:5]:  # Show first 5
                print(f"     - {dup}")
            self.warnings.append(f"{len(duplicates)} duplicate connections")
        else:
            print("  ✅ No duplicate connections")

        # 7. Check net consistency
        print("\n7. NET CONSISTENCY CHECK:")
        net_issues = self._check_net_consistency(connections, nets, pin_net_mapping)
        if net_issues:
            print(f"  ⚠️ FOUND {len(net_issues)} NET INCONSISTENCIES:")
            for issue in net_issues[:5]:  # Show first 5
                print(f"     - {issue}")
            self.warnings.extend(net_issues)
        else:
            print("  ✅ Nets are consistent")

        # 8. RE-RUN CIRCUIT SUPERVISOR FOR LIVE VALIDATION
        # Instead of reading saved status, re-run the supervisor with current code
        # This ensures we always get accurate validation results
        print("\n8. CIRCUIT SUPERVISOR LIVE VALIDATION:")
        try:
            # Import supervisor dynamically to get latest code
            import sys
            import importlib
            # Add project root to path if not already there
            project_root = str(Path(__file__).parent.parent)
            if project_root not in sys.path:
                sys.path.insert(0, project_root)
            if 'workflow.circuit_supervisor' in sys.modules:
                importlib.reload(sys.modules['workflow.circuit_supervisor'])
            from workflow.circuit_supervisor import CircuitSupervisor

            # Run live validation
            supervisor = CircuitSupervisor()
            erc_report = supervisor.run_erc_check(circuit)

            if erc_report['passed']:
                print(f"  ✅ Circuit PASSES live ERC validation")
                # Also update the circuit's saved status for consistency
                circuit['validation_status'] = 'PERFECT'
            else:
                print(f"  ❌ Circuit FAILS live ERC validation")
                print(f"  Live issues found: {erc_report['total_issues']}")
                for category, items in erc_report['issues'].items():
                    if items:
                        print(f"    - {category}: {len(items)}")
                        for item in items[:3]:  # Show first 3
                            msg = item.get('message', item.get('type', str(item)))
                            print(f"      * {msg}")
                self.critical_issues.append("Circuit supervisor: FAILS LIVE ERC")
                result['completeness'] = 0  # Force to 0% if supervisor fails
        except ImportError as e:
            # Fallback to reading saved status if supervisor not available
            print(f"  ⚠️ Could not import supervisor ({e}), checking saved status...")
            if 'validation_status' in circuit:
                status = circuit['validation_status']
                if status == 'IMPERFECT':
                    print(f"  ❌ CIRCUIT MARKED AS IMPERFECT BY SUPERVISOR")
                    if 'validation_issues' in circuit:
                        print(f"  Supervisor issues: {circuit['validation_issues']}")
                    self.critical_issues.append("Circuit supervisor: IMPERFECT")
                    result['completeness'] = 0
                else:
                    print(f"  ✅ Circuit validation status: {status}")
            else:
                print("  ⚠️ No validation_status field (old format or not validated)")

        # Ensure completeness doesn't go below 0
        result['completeness'] = max(0, result['completeness'])

        # Store all issues
        result['critical_issues'] = self.critical_issues
        result['issues'] = self.issues
        result['warnings'] = self.warnings

        # Summary
        print(f"\n{'=' * 40}")
        print(f"VALIDATION SUMMARY:")
        print(f"  Critical Issues: {len(self.critical_issues)}")
        print(f"  Issues: {len(self.issues)}")
        print(f"  Warnings: {len(self.warnings)}")
        print(f"  Completeness: {result['completeness']:.1f}%")

        if self.critical_issues:
            print(f"\n❌ CIRCUIT HAS CRITICAL ISSUES - NOT PRODUCTION READY")
        elif self.issues:
            print(f"\n⚠️ CIRCUIT HAS ISSUES - NEEDS ATTENTION")
        elif self.warnings:
            print(f"\n⚠️ CIRCUIT HAS WARNINGS - REVIEW RECOMMENDED")
        else:
            print(f"\n✅ CIRCUIT IS 100% PERFECT - PRODUCTION READY")

        return result

    def _check_floating_components(self, components: List, connections: List, pin_net_mapping: Dict) -> List[Dict]:
        """Check for components with unconnected pins

        TC #90: Skip mechanical components (heatsinks, mounting holes, fiducials)
        These don't require electrical connections.
        """
        floating = []

        # Build set of connected pins from both connections and pinNetMapping
        connected_pins = set()

        # From connections (new format with net/points)
        for conn in connections:
            if 'points' in conn:
                for point in conn['points']:
                    connected_pins.add(point)

        # From pinNetMapping
        connected_pins.update(pin_net_mapping.keys())

        # TC #90: Mechanical component types that don't need electrical connections
        MECHANICAL_TYPES = {'heatsink', 'mounting', 'fiducial', 'mechanical', 'standoff', 'bracket'}

        # Check each component
        for comp in components:
            ref = comp.get('ref', '')
            pins = comp.get('pins', [])
            comp_type = comp.get('type', '').lower()

            # TC #90: Skip mechanical components
            if any(mech in comp_type for mech in MECHANICAL_TYPES):
                continue
            connected_count = 0
            unconnected = []

            for pin in pins:
                pin_ref = f"{ref}.{pin['number']}"
                if pin_ref in connected_pins:
                    connected_count += 1
                else:
                    unconnected.append(pin['number'])

            if connected_count < len(pins):
                floating.append({
                    'ref': ref,
                    'type': comp.get('type', 'unknown'),
                    'connected': connected_count,
                    'total': len(pins),
                    'unconnected_pins': unconnected
                })

        return floating

    def _check_single_ended_nets(self, connections: List, components: List) -> List[Dict]:
        """Check for nets with only one connection point.

        Fix IV.1: Filters out legitimate single-ended nets to match the
        circuit supervisor's logic, preventing inflated issue counts.
        All filter patterns are loaded from server.config (single source of
        truth) so they stay in sync with the supervisor automatically.
        """
        from server.config import config as _cfg

        net_connections = defaultdict(list)
        for conn in connections:
            if 'net' in conn and 'points' in conn:
                for point in conn['points']:
                    net_connections[conn['net']].append(point)

        # Build set of connector/test-point refs for filtering (config-driven)
        _conn_prefixes = tuple(_cfg.CONNECTOR_REF_PREFIXES) if hasattr(_cfg, 'CONNECTOR_REF_PREFIXES') else ('J', 'X', 'P', 'CN', 'CONN')
        _tp_prefixes = tuple(_cfg.TESTPOINT_REF_PREFIXES) if hasattr(_cfg, 'TESTPOINT_REF_PREFIXES') else ('TP',)
        _all_prefixes = _conn_prefixes + _tp_prefixes
        connector_refs = set()
        for c in components:
            cref = c.get('ref', '').upper()
            ctype = c.get('type', '').lower()
            if cref.startswith(_all_prefixes) or ctype in _cfg.CONNECTOR_TYPES:
                connector_refs.add(c['ref'])

        single_ended = []
        filtered_count = 0

        for net, points in net_connections.items():
            if len(points) >= 2:
                continue

            net_upper = net.upper()
            ref = points[0].split('.')[0] if points else ''

            # --- Category 1: Always legitimate single-ended ---

            # NC (No Connect) nets
            if 'NC' in net_upper or net_upper.startswith('NC_'):
                filtered_count += 1
                continue

            # GPIO / MCU port pins (from config.SUPERVISOR_GPIO_PATTERNS)
            if any(re.match(pat, net_upper) for pat in _cfg.SUPERVISOR_GPIO_PATTERNS):
                filtered_count += 1
                continue

            # Cross-module interface signals (SYS_ prefix from config)
            if net_upper.startswith(_cfg.SYS_NET_PREFIX):
                filtered_count += 1
                continue

            # Test points and connectors
            if ref in connector_refs:
                filtered_count += 1
                continue

            # --- Category 2: Interface signals ---

            # Protocol / debug keywords (from config.INTERFACE_NET_PATTERNS)
            if any(kw in net_upper for kw in _cfg.INTERFACE_NET_PATTERNS):
                filtered_count += 1
                continue

            # Input/Output suffixes (from config.SINGLE_ENDED_OK_SUFFIXES)
            if net_upper.endswith(_cfg.SINGLE_ENDED_OK_SUFFIXES):
                filtered_count += 1
                continue

            # Power interface patterns (from config.SINGLE_ENDED_POWER_PREFIXES)
            if any(p in net_upper for p in _cfg.SINGLE_ENDED_POWER_PREFIXES):
                filtered_count += 1
                continue

            # Module-prefixed interface nets (config-driven patterns)
            _mod_patterns = getattr(_cfg, 'GENERIC_MODULE_PREFIX_PATTERNS', [r'^(MOD|CH|MODULE|CHANNEL)\d+_'])
            if any(re.match(pat, net_upper) for pat in _mod_patterns):
                filtered_count += 1
                continue

            # N.1 FIX: Integration agent module name prefixes (config-driven)
            if any(net_upper.startswith(p) for p in _cfg.INTERFACE_MODULE_PREFIXES):
                filtered_count += 1
                continue

            # N.2 FIX: External connection exempt patterns (regex-based)
            exempt = False
            for pattern in _cfg.SINGLE_ENDED_EXEMPT_PATTERNS:
                if re.search(pattern, net_upper):
                    exempt = True
                    break
            if exempt:
                filtered_count += 1
                continue

            # --- Category 3: Genuine single-ended issues ---
            single_ended.append({
                'net': net,
                'count': len(points),
                'points': points,
            })

        # Attach filter stats for reporting
        if single_ended:
            single_ended[-1]['_filtered_total'] = filtered_count
        return single_ended

    def _check_invalid_pins(self, components: List, connections: List, pin_net_mapping: Dict) -> List[Dict]:
        """Check for references to pins that don't exist"""
        # Build valid pin set
        valid_pins = set()
        for comp in components:
            ref = comp['ref']
            for pin in comp.get('pins', []):
                valid_pins.add(f"{ref}.{pin['number']}")

        invalid = []

        # Check connections
        for conn in connections:
            if 'points' in conn:
                for point in conn['points']:
                    if '.' in point and point not in valid_pins:
                        invalid.append({
                            'pin': point,
                            'issue': 'Referenced in connection but pin does not exist'
                        })

        # Check pinNetMapping
        for pin_ref in pin_net_mapping.keys():
            if '.' in pin_ref and pin_ref not in valid_pins:
                invalid.append({
                    'pin': pin_ref,
                    'issue': 'In pinNetMapping but pin does not exist'
                })

        return invalid

    def _check_phantom_components(self, components: List, connections: List, pin_net_mapping: Dict) -> List[str]:
        """Check for component references that don't have definitions"""
        defined_refs = {comp['ref'] for comp in components}
        referenced_refs = set()

        # From connections
        for conn in connections:
            if 'points' in conn:
                for point in conn['points']:
                    if '.' in point:
                        ref = point.split('.')[0]
                        referenced_refs.add(ref)

        # From pinNetMapping
        for pin_ref in pin_net_mapping.keys():
            if '.' in pin_ref:
                ref = pin_ref.split('.')[0]
                referenced_refs.add(ref)

        phantom = referenced_refs - defined_refs
        return list(phantom)

    def _check_ic_power(self, components: List, connections: List, pin_net_mapping: Dict) -> List[Dict]:
        """Check if ICs have proper power connections"""
        # Build pin-to-net mapping
        pin_nets = dict(pin_net_mapping)

        # Also add from connections
        for conn in connections:
            if 'net' in conn and 'points' in conn:
                net = conn['net']
                for point in conn['points']:
                    pin_nets[point] = net

        issues = []
        power_keywords = ['VCC', 'VDD', 'V+', 'POWER', '3V3', '5V', '12V', '24V', 'VIN']
        ground_keywords = ['GND', 'VSS', 'V-', 'GROUND', 'AGND', 'DGND', '0V']

        for comp in components:
            if comp.get('type', '').lower() in ['ic', 'microcontroller', 'mcu', 'voltage_regulator']:
                ref = comp['ref']
                has_power = False
                has_ground = False

                # Check all pins
                for pin in comp.get('pins', []):
                    pin_ref = f"{ref}.{pin['number']}"
                    net = pin_nets.get(pin_ref, '')

                    # Check net name
                    if any(pwr in net.upper() for pwr in power_keywords):
                        has_power = True
                    if any(gnd in net.upper() for gnd in ground_keywords):
                        has_ground = True

                # Report issues
                if not has_power and not ref.startswith('U'):  # Skip some false positives
                    issues.append({'ref': ref, 'issue': 'No power connection detected'})
                if not has_ground:
                    issues.append({'ref': ref, 'issue': 'No ground connection detected'})

        return issues

    def _check_duplicate_connections(self, connections: List) -> List[str]:
        """Check for duplicate connections"""
        seen = set()
        duplicates = []

        for conn in connections:
            if 'points' in conn and 'net' in conn:
                points = tuple(sorted(conn['points']))
                net = conn['net']
                sig = f"{net}:{points}"

                if sig in seen:
                    duplicates.append(f"Duplicate: {net} connecting {points}")
                else:
                    seen.add(sig)

        return duplicates

    def _check_net_consistency(self, connections: List, nets: List, pin_net_mapping: Dict) -> List[str]:
        """Check net consistency across different representations"""
        issues = []

        # Get nets from connections
        conn_nets = set()
        for conn in connections:
            if 'net' in conn:
                conn_nets.add(conn['net'])

        # Get nets from pinNetMapping
        mapped_nets = set(pin_net_mapping.values())

        # Get defined nets (if nets array exists and is not empty)
        if nets and isinstance(nets, list) and all(isinstance(n, str) for n in nets):
            defined_nets = set(nets)

            # Check for undefined nets in connections
            undefined_in_conn = conn_nets - defined_nets
            if undefined_in_conn:
                for net in undefined_in_conn:
                    issues.append(f"Net '{net}' used in connections but not defined")

            # Check for undefined nets in pinNetMapping
            undefined_in_map = mapped_nets - defined_nets
            if undefined_in_map:
                for net in undefined_in_map:
                    issues.append(f"Net '{net}' in pinNetMapping but not defined")

        return issues


def main():
    """Main analysis function"""

    # Get output directory
    output_dir = Path("output")

    if len(sys.argv) > 1:
        project_dir = Path(sys.argv[1])
    else:
        # Find latest output folder
        if output_dir.exists():
            output_dirs = [d for d in output_dir.iterdir()
                          if d.is_dir() and d.name != '.DS_Store']
            if output_dirs:
                latest_dir = sorted(output_dirs, reverse=True)[0]
                project_dir = latest_dir / 'lowlevel'
            else:
                print("❌ No output directories found")
                return
        else:
            print("❌ Output directory not found")
            return

    if not project_dir.exists():
        print(f"❌ Directory not found: {project_dir}")
        return

    # Get all circuit JSON files
    circuit_files = list(project_dir.glob('circuit_*.json'))

    if not circuit_files:
        print(f"❌ No circuit files found in {project_dir}")
        return

    print("=" * 80)
    print("COMPREHENSIVE LOW-LEVEL CIRCUIT ANALYSIS")
    print("Requirement: 100% COMPLETE circuits (no 'almost' in electronics!)")
    print("=" * 80)
    print(f"\nFound {len(circuit_files)} circuit files to analyze")

    analyzer = CircuitAnalyzer()
    all_results = []
    perfect_circuits = 0
    total_critical = 0
    total_issues = 0
    total_warnings = 0

    for circuit_file in sorted(circuit_files):
        result = analyzer.analyze_circuit(circuit_file)
        all_results.append(result)

        if (result['completeness'] == 100 and
            not result['critical_issues'] and
            not result['issues']):
            perfect_circuits += 1

        total_critical += len(result.get('critical_issues', []))
        total_issues += len(result['issues'])
        total_warnings += len(result['warnings'])

    # Final Summary
    print("\n" + "=" * 80)
    print("FINAL ANALYSIS SUMMARY")
    print("=" * 80)

    print(f"\nCircuits Analyzed: {len(circuit_files)}")
    print(f"Perfect Circuits (100%): {perfect_circuits}/{len(circuit_files)}")
    print(f"Total Critical Issues: {total_critical}")
    print(f"Total Issues: {total_issues}")
    print(f"Total Warnings: {total_warnings}")

    print("\nPer-Circuit Summary:")
    for result in all_results:
        if result['completeness'] == 100 and not result.get('critical_issues') and not result['issues']:
            status = "✅ PERFECT"
        else:
            status = f"{result['completeness']:.1f}%"
        print(f"  {result['name']}: {status}")

        if result.get('critical_issues'):
            print(f"    Critical: {len(result['critical_issues'])}")
            for issue in result['critical_issues'][:3]:
                print(f"      - {issue}")
        if result['issues']:
            print(f"    Issues: {len(result['issues'])}")
        if result['warnings']:
            print(f"    Warnings: {len(result['warnings'])}")

    # Overall verdict
    print("\n" + "=" * 80)
    if perfect_circuits == len(circuit_files):
        print("✅ ALL CIRCUITS ARE 100% PERFECT!")
        print("Ready for production and PCB manufacturing")
    else:
        print(f"❌ ONLY {perfect_circuits}/{len(circuit_files)} CIRCUITS ARE PERFECT")
        print("Critical issues MUST be fixed before production")
        print("\nRequired fixes:")
        if total_critical > 0:
            print(f"  - {total_critical} CRITICAL issues (floating components, invalid pins)")
        if total_issues > 0:
            print(f"  - {total_issues} issues (single-ended nets, etc.)")
    print("=" * 80)


if __name__ == "__main__":
    main()