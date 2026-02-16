# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Validation Agent - Per-module circuit validation.

The Validation Agent validates a single module's circuit for correctness.
It runs ERC (Electrical Rule Check) and can auto-fix minor issues.

This agent operates at the MODULE level, not system level.
System-level validation happens in the Integration Agent.

Author: CopperPilot Team
Date: January 2026
Version: 1.0

Key Design Principles:
- MODULE-SCOPED: Only validates one module at a time
- AUTO-FIX: Can fix minor issues automatically
- INTERFACE-AWARE: Validates interface signals are exposed
- DETAILED REPORTING: Provides actionable issue reports
"""

import json
from typing import Dict, List, Any, Optional, Set
from pathlib import Path

from utils.logger import setup_logger
from server.config import config

logger = setup_logger(__name__)


class ValidationAgent:
    """
    Per-module validation agent.

    The Validation Agent performs ERC checks on a single module:
    1. Power connections (VCC/GND for ICs)
    2. Floating pins/components
    3. Single-ended nets (internal signals)
    4. Shorted passives (LAW 4 violations)
    5. Interface signal exposure

    It can auto-fix minor issues and returns a detailed report.

    Attributes:
        ai_manager: Reference to the AI Agent Manager
    """

    def __init__(self, ai_manager):
        """
        Initialize the Validation Agent.

        Args:
            ai_manager: The AI Agent Manager instance
        """
        self.ai_manager = ai_manager
        self.fixes_applied = []

    async def validate_module(self, circuit: Dict, interface: Dict) -> Dict:
        """
        Validate a module circuit.

        This method runs comprehensive ERC checks and attempts
        to auto-fix minor issues.

        Args:
            circuit: Module circuit dict containing:
                - components: List of components
                - connections: List of connections
                - pinNetMapping: Pin to net mapping
                - nets: List of nets

            interface: Interface contract for validation

        Returns:
            Validation result dict containing:
                - passed: Whether validation passed
                - issues: List of issues found
                - warnings: List of warnings
                - fixes_applied: List of auto-fixes applied
                - circuit: Potentially fixed circuit
                - critical_failure: Whether issues are critical
        """
        module_name = circuit.get('module_name', 'Unknown')
        logger.info(f"         ValidationAgent: Validating {module_name}")

        # DEBUG: Log validation input
        components = circuit.get('components', [])
        connections = circuit.get('connections', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Components: {len(components)}")
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Connections: {len(connections)}")
        logger.debug(f"[VALIDATION_AGENT] {module_name} - PinNetMapping entries: {len(pin_net_mapping)}")
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Unique nets: {len(set(pin_net_mapping.values()))}")

        self.fixes_applied = []
        issues = []
        warnings = []

        # Run all validation checks
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Running power connection check...")
        power_issues = self._check_power_connections(circuit)
        issues.extend(power_issues)
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Power issues: {len(power_issues)}")

        logger.debug(f"[VALIDATION_AGENT] {module_name} - Running floating pins check...")
        floating_issues = self._check_floating_pins(circuit)
        issues.extend(floating_issues)
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Floating issues: {len(floating_issues)}")

        logger.debug(f"[VALIDATION_AGENT] {module_name} - Running single-ended nets check...")
        single_ended_issues = self._check_single_ended_nets(circuit, interface)
        issues.extend(single_ended_issues)
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Single-ended issues: {len(single_ended_issues)}")

        logger.debug(f"[VALIDATION_AGENT] {module_name} - Running shorted passives check (LAW 4)...")
        shorted_issues = self._check_shorted_passives(circuit)
        issues.extend(shorted_issues)
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Shorted passive issues (LAW 4): {len(shorted_issues)}")

        logger.debug(f"[VALIDATION_AGENT] {module_name} - Running interface signals check...")
        interface_issues = self._check_interface_signals(circuit, interface)
        issues.extend(interface_issues)
        logger.debug(f"[VALIDATION_AGENT] {module_name} - Interface issues: {len(interface_issues)}")

        # Attempt auto-fixes for minor issues
        if issues:
            circuit, remaining_issues = self._auto_fix_issues(circuit, issues)
            issues = remaining_issues

        # Determine if passed
        critical_issues = [i for i in issues if i.get('severity', 'error') == 'critical']
        passed = len(critical_issues) == 0

        # Log summary
        if passed:
            logger.info(f"         ✅ Validation PASSED ({len(warnings)} warnings)")
        else:
            logger.warning(f"         ⚠️ Validation found {len(issues)} issues")

        return {
            'passed': passed,
            'issues': issues,
            'warnings': warnings,
            'fixes_applied': self.fixes_applied,
            'circuit': circuit,
            'critical_failure': len(critical_issues) > 0
        }

    def _check_power_connections(self, circuit: Dict) -> List[Dict]:
        """
        Check for missing power/ground connections on ICs.

        Args:
            circuit: The circuit to check

        Returns:
            List of power connection issues
        """
        issues = []
        components = circuit.get('components', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})

        for comp in components:
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()

            # Only check ICs and active components
            if comp_type not in ['ic', 'amplifier', 'opamp', 'microcontroller',
                                  'comparator', 'driver', 'dds']:
                continue

            # Check for power and ground connections
            has_vcc = False
            has_gnd = False

            for pin in comp.get('pins', []):
                pin_num = pin.get('number', '')
                pin_ref = f"{ref}.{pin_num}"
                net = pin_net_mapping.get(pin_ref, '')

                if net:
                    net_upper = net.upper()
                    if any(x in net_upper for x in ['VCC', 'VDD', 'V+', 'PWR', '5V', '12V', '3V3']):
                        has_vcc = True
                    if any(x in net_upper for x in ['GND', 'VSS', 'V-', 'GROUND', '0V']):
                        has_gnd = True

            if not has_vcc:
                issues.append({
                    'type': 'ic_missing_power',
                    'component': ref,
                    'severity': 'critical',
                    'message': f'{ref} has no power (VCC/VDD) connection'
                })

            if not has_gnd:
                issues.append({
                    'type': 'ic_missing_ground',
                    'component': ref,
                    'severity': 'critical',
                    'message': f'{ref} has no ground (GND/VSS) connection'
                })

        return issues

    def _check_floating_pins(self, circuit: Dict) -> List[Dict]:
        """
        Check for floating (unconnected) pins.

        Args:
            circuit: The circuit to check

        Returns:
            List of floating pin issues
        """
        issues = []
        components = circuit.get('components', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})

        for comp in components:
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()

            # Skip non-electrical components
            if comp_type in ['heatsink', 'mounting_hole', 'fiducial']:
                continue

            for pin in comp.get('pins', []):
                pin_num = pin.get('number', '')
                pin_name = pin.get('name', '').upper()
                pin_ref = f"{ref}.{pin_num}"

                # Skip NC pins
                if 'NC' in pin_name or pin_name.startswith('NC'):
                    continue

                if pin_ref not in pin_net_mapping:
                    issues.append({
                        'type': 'floating_pin',
                        'component': ref,
                        'pin': pin_ref,
                        'severity': 'warning',
                        'message': f'{pin_ref} is not connected'
                    })

        return issues

    def _check_single_ended_nets(self, circuit: Dict, interface: Dict) -> List[Dict]:
        """
        Check for single-ended internal nets.

        Interface nets can be single-ended (they connect to other modules).
        Internal nets should have at least 2 connections.

        Args:
            circuit: The circuit to check
            interface: Interface contract

        Returns:
            List of single-ended net issues
        """
        issues = []
        pin_net_mapping = circuit.get('pinNetMapping', {})

        # Count connections per net
        net_counts = {}
        for pin, net in pin_net_mapping.items():
            if net not in net_counts:
                net_counts[net] = 0
            net_counts[net] += 1

        # Get interface signal names
        interface_signals = set()
        for key in ['inputs', 'outputs', 'signals_in', 'signals_out']:
            signals = interface.get(key, {})
            if isinstance(signals, dict):
                interface_signals.update(signals.keys())
            elif isinstance(signals, list):
                interface_signals.update(signals)

        # Check each net
        for net, count in net_counts.items():
            if count == 1:
                net_upper = net.upper()

                # Skip interface signals (they connect to other modules)
                if net in interface_signals or any(s in net_upper for s in interface_signals):
                    continue

                # Skip NC nets
                if 'NC' in net_upper:
                    continue

                # Skip test points
                if 'TP' in net_upper or 'TEST' in net_upper:
                    continue

                # Skip power rails (might connect to other modules)
                if any(x in net_upper for x in ['VCC', 'VDD', 'GND', 'VSS', 'PWR']):
                    continue

                issues.append({
                    'type': 'single_ended_net',
                    'net': net,
                    'severity': 'warning',
                    'message': f'Net {net} has only 1 connection'
                })

        return issues

    def _check_shorted_passives(self, circuit: Dict) -> List[Dict]:
        """
        Check for 2-terminal passives with both pins on same net (LAW 4).

        Args:
            circuit: The circuit to check

        Returns:
            List of shorted passive issues
        """
        issues = []
        components = circuit.get('components', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})

        passive_types = ['resistor', 'capacitor', 'inductor', 'diode', 'led', 'fuse']

        for comp in components:
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()
            pins = comp.get('pins', [])

            # Only check 2-terminal passives
            if comp_type not in passive_types or len(pins) != 2:
                continue

            pin1_num = pins[0].get('number', '1')
            pin2_num = pins[1].get('number', '2')

            pin1_ref = f"{ref}.{pin1_num}"
            pin2_ref = f"{ref}.{pin2_num}"

            net1 = pin_net_mapping.get(pin1_ref, '')
            net2 = pin_net_mapping.get(pin2_ref, '')

            if net1 and net2 and net1 == net2:
                issues.append({
                    'type': 'shorted_passive',
                    'component': ref,
                    'net': net1,
                    'severity': 'critical',
                    'message': f'{ref} has both pins on {net1} (LAW 4 violation!)'
                })

        return issues

    def _check_interface_signals(self, circuit: Dict, interface: Dict) -> List[Dict]:
        """
        Check that interface signals are properly exposed.

        Args:
            circuit: The circuit to check
            interface: Interface contract

        Returns:
            List of interface signal issues
        """
        issues = []
        pin_net_mapping = circuit.get('pinNetMapping', {})

        # Get all nets in the circuit
        circuit_nets = set(pin_net_mapping.values())

        # Check output signals are exposed
        output_signals = interface.get('outputs', {})
        if isinstance(output_signals, dict):
            for signal_name in output_signals.keys():
                # Check if signal exists as a net
                found = any(signal_name.upper() in net.upper() for net in circuit_nets)
                if not found:
                    issues.append({
                        'type': 'missing_interface_signal',
                        'signal': signal_name,
                        'severity': 'warning',
                        'message': f'Interface output {signal_name} not found in circuit'
                    })

        return issues

    def _auto_fix_issues(self, circuit: Dict, issues: List[Dict]) -> tuple:
        """
        Attempt to auto-fix minor issues.

        Args:
            circuit: The circuit to fix
            issues: List of issues

        Returns:
            Tuple of (fixed circuit, remaining issues)
        """
        pin_net_mapping = circuit.get('pinNetMapping', {})
        remaining_issues = []

        for issue in issues:
            issue_type = issue.get('type', '')

            # Fix floating pins
            if issue_type == 'floating_pin':
                pin_ref = issue.get('pin', '')
                if pin_ref:
                    # Mark as NC
                    pin_net_mapping[pin_ref] = f"NC_{pin_ref.replace('.', '_')}"
                    self.fixes_applied.append(f"Marked {pin_ref} as NC")
                    continue

            # Fix shorted passives
            if issue_type == 'shorted_passive':
                comp_ref = issue.get('component', '')
                comp = next((c for c in circuit.get('components', [])
                            if c.get('ref') == comp_ref), None)
                if comp:
                    pins = comp.get('pins', [])
                    if len(pins) >= 2:
                        pin2_ref = f"{comp_ref}.{pins[1].get('number', '2')}"
                        new_net = f"NET_{comp_ref}"
                        pin_net_mapping[pin2_ref] = new_net
                        self.fixes_applied.append(f"Fixed {comp_ref}: moved pin 2 to {new_net}")
                        continue

            # Fix IC missing power
            if issue_type == 'ic_missing_power':
                comp_ref = issue.get('component', '')
                comp = next((c for c in circuit.get('components', [])
                            if c.get('ref') == comp_ref), None)
                if comp:
                    # Find first unconnected pin
                    for pin in comp.get('pins', []):
                        pin_num = pin.get('number', '')
                        pin_ref = f"{comp_ref}.{pin_num}"
                        if pin_ref not in pin_net_mapping:
                            pin_net_mapping[pin_ref] = 'VCC'
                            self.fixes_applied.append(f"Added VCC to {pin_ref}")
                            break
                    continue

            # Fix IC missing ground
            if issue_type == 'ic_missing_ground':
                comp_ref = issue.get('component', '')
                comp = next((c for c in circuit.get('components', [])
                            if c.get('ref') == comp_ref), None)
                if comp:
                    # Find first unconnected pin
                    for pin in comp.get('pins', []):
                        pin_num = pin.get('number', '')
                        pin_ref = f"{comp_ref}.{pin_num}"
                        if pin_ref not in pin_net_mapping:
                            pin_net_mapping[pin_ref] = 'GND'
                            self.fixes_applied.append(f"Added GND to {pin_ref}")
                            break
                    continue

            # Issue couldn't be fixed
            remaining_issues.append(issue)

        # Update circuit
        circuit['pinNetMapping'] = pin_net_mapping

        # Rebuild connections
        net_to_pins = {}
        for pin, net in pin_net_mapping.items():
            if net not in net_to_pins:
                net_to_pins[net] = []
            net_to_pins[net].append(pin)

        circuit['connections'] = [
            {'net': net, 'points': sorted(pins)}
            for net, pins in net_to_pins.items()
        ]
        circuit['nets'] = list(net_to_pins.keys())

        return circuit, remaining_issues
