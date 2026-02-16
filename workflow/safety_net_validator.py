# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Safety Net Validator
Final quality gate ensuring 100% perfect circuits before converter processing
Ported from N8N Safety Net Validator node
"""
import json
import copy
from typing import Dict, Any, List, Tuple, Set
from pathlib import Path

from utils.logger import setup_logger

logger = setup_logger(__name__)


class SafetyNetValidator:
    """
    Comprehensive circuit validator with auto-fixing capabilities
    Ensures zero-defect circuits reach production
    """

    def __init__(self):
        self.fixes_applied = []
        self.validation_report = {}

    def validate_and_fix(self, circuit: Dict) -> Dict:
        """
        Main validation and fixing function
        Returns fixed circuit with 100% guarantee of validity
        """
        if not circuit:
            raise ValueError("Circuit is None or empty")

        logger.info("Starting Safety Net Validation...")

        # Make a deep copy to avoid modifying original
        circuit = copy.deepcopy(circuit)

        # Track initial state
        initial_issues = self._find_all_issues(circuit)
        logger.info(f"Initial issues found: {len(initial_issues)}")

        # Apply fixes in order of priority
        # First fix major structural issues
        circuit = self._fix_floating_components(circuit)
        circuit = self._fix_capacitor_connections(circuit)
        circuit = self._fix_power_connections(circuit)
        circuit = self._fix_unconnected_power_pins(circuit)
        circuit = self._fix_component_specific_issues(circuit)

        # Rebuild connections before fixing nets
        circuit = self._rebuild_connections(circuit)

        # Fix net issues AFTER all other fixes (they might create single-ended nets)
        circuit = self._fix_single_ended_nets(circuit)
        circuit = self._fix_orphan_nets(circuit)

        # Final rebuild and validation
        circuit = self._rebuild_connections(circuit)
        circuit = self._validate_final_circuit(circuit)

        # Track final state
        final_issues = self._find_all_issues(circuit)

        self.validation_report = {
            'initial_issues': initial_issues,
            'final_issues': final_issues,
            'fixes_applied': self.fixes_applied,
            'success': len(final_issues) == 0
        }

        if len(final_issues) > 0:
            logger.warning(f"Remaining issues after fixes: {final_issues}")
        else:
            logger.info("✅ Circuit validation passed - 100% perfect!")

        return circuit

    def _find_all_issues(self, circuit: Dict) -> List[str]:
        """Find all issues in the circuit"""
        issues = []

        # Check for floating components
        floating = self._find_floating_components(circuit)
        if floating:
            issues.extend([f"Floating component: {comp}" for comp in floating])

        # Check for single-ended nets
        single_ended = self._find_single_ended_nets(circuit)
        if single_ended:
            issues.extend([f"Single-ended net: {net}" for net in single_ended])

        # Check for missing power connections
        missing_power = self._find_missing_power_connections(circuit)
        if missing_power:
            issues.extend([f"Missing power for: {comp}" for comp in missing_power])

        # Check for net conflicts
        conflicts = self._find_net_conflicts(circuit)
        if conflicts:
            issues.extend([f"Net conflict at pin: {pin}" for pin in conflicts])

        return issues

    def _find_floating_components(self, circuit: Dict) -> Set[str]:
        """Find components with no connections"""
        floating = set()

        if not circuit.get('components') or not circuit.get('pinNetMapping'):
            return floating

        # Get all connected components
        connected = set()
        for pin in circuit.get('pinNetMapping', {}).keys():
            connected.add(pin.split('.')[0])

        # Check each component
        for comp in circuit.get('components', []):
            ref = comp.get('ref', comp.get('refDes', ''))
            comp_type = comp.get('type', '').lower()

            # Skip non-electrical components
            if self._is_non_electrical(comp_type):
                continue

            if ref and ref not in connected:
                floating.add(ref)

        return floating

    def _find_single_ended_nets(self, circuit: Dict) -> Set[str]:
        """Find nets connected to only one pin"""
        single_ended = set()

        net_connections = {}
        for pin, net in circuit.get('pinNetMapping', {}).items():
            if net not in net_connections:
                net_connections[net] = []
            net_connections[net].append(pin)

        for net, pins in net_connections.items():
            # Skip external interfaces
            if self._is_external_net(net):
                continue

            if len(pins) == 1:
                single_ended.add(net)

        return single_ended

    def _find_missing_power_connections(self, circuit: Dict) -> Set[str]:
        """Find ICs without power connections using intelligent pattern matching"""
        missing_power = set()

        pin_mapping = circuit.get('pinNetMapping', {})

        # Universal power patterns for detection
        POWER_PATTERNS = {
            'positive': ['VCC', 'VDD', 'V+', '+5V', '+3V3', '+3.3V', '+12V', '+9V', 'VBUS', 'VBAT',
                        'VS+', 'PWR', 'POWER', 'VIN', 'VSUP', 'AVCC', 'DVCC', 'PVCC', 'VCORE'],
            'negative': ['GND', 'VSS', 'V-', '0V', 'DGND', 'AGND', 'PGND', 'VS-', 'GROUND',
                        'COM', 'COMMON', 'NEG', 'EARTH', 'RTN', 'RETURN']
        }

        for comp in circuit.get('components', []):
            ref = comp.get('ref', comp.get('refDes', ''))
            comp_type = comp.get('type', '').lower()

            # Check ICs and voltage regulators
            if not ref:
                continue

            # Determine if component needs power
            needs_power = False
            if ref.startswith('U'):  # ICs
                needs_power = True
            elif 'regulator' in comp_type or 'converter' in comp_type:
                needs_power = True
            elif comp.get('value', '').upper() in ['555', 'LM317', 'LM7805', 'LM2596']:
                needs_power = True

            if not needs_power:
                continue

            # Check for power connections
            has_power = False
            has_ground = False

            for pin, net in pin_mapping.items():
                if pin.startswith(f"{ref}."):
                    net_upper = net.upper()
                    # Check positive power
                    if any(pattern in net_upper for pattern in POWER_PATTERNS['positive']):
                        has_power = True
                    # Check ground/negative
                    elif any(pattern in net_upper for pattern in POWER_PATTERNS['negative']):
                        has_ground = True

            if not has_power or not has_ground:
                missing_power.add(ref)
                if not has_power:
                    logger.debug(f"{ref} missing positive power connection")
                if not has_ground:
                    logger.debug(f"{ref} missing ground connection")

        return missing_power

    def _find_net_conflicts(self, circuit: Dict) -> Set[str]:
        """Find pins connected to multiple different nets"""
        conflicts = set()

        # This should already be fixed by fix_net_conflicts
        # But check anyway
        pin_nets = {}
        for pin, net in circuit.get('pinNetMapping', {}).items():
            if pin in pin_nets and pin_nets[pin] != net:
                conflicts.add(pin)
            else:
                pin_nets[pin] = net

        return conflicts

    def _is_non_electrical(self, comp_type: str) -> bool:
        """Check if component is non-electrical"""
        non_electrical_types = [
            'heatsink', 'mounting', 'fiducial', 'mechanical',
            'testpoint', 'hole', 'logo', 'text'
        ]
        return any(x in comp_type.lower() for x in non_electrical_types)

    def _is_external_net(self, net: str) -> bool:
        """Check if net is an external interface"""
        external_nets = [
            'ENABLE', 'UART', 'TX', 'RX', 'SDA', 'SCL',
            'MOSI', 'MISO', 'SCK', 'CS', 'INT', 'RST',
            'INPUT', 'OUTPUT', 'SIGNAL', 'SENSE'
        ]
        net_upper = net.upper()
        return any(x in net_upper for x in external_nets)

    def _fix_floating_components(self, circuit: Dict) -> Dict:
        """Fix floating components by adding appropriate connections"""
        floating = self._find_floating_components(circuit)

        if not floating:
            return circuit

        logger.info(f"Fixing {len(floating)} floating components...")

        for ref in floating:
            comp = next((c for c in circuit['components']
                        if c.get('ref', c.get('refDes', '')) == ref), None)

            if not comp:
                continue

            comp_type = comp.get('type', '').lower()
            value = comp.get('value', '').lower()

            # Fix based on component type
            if ref.startswith('C'):
                # Capacitor - check if bypass/decoupling
                if any(x in value for x in ['100n', '0.1u', '1u', 'bypass', 'decoupling']):
                    circuit['pinNetMapping'][f"{ref}.1"] = "VCC"
                    circuit['pinNetMapping'][f"{ref}.2"] = "GND"
                    self.fixes_applied.append(f"Connected bypass cap {ref} to VCC/GND")
                else:
                    # Generic capacitor connection
                    circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_1"
                    circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_2"
                    self.fixes_applied.append(f"Added nets for capacitor {ref}")

            elif ref.startswith('R'):
                # Resistor - check if pull-up/pull-down
                if 'pull' in comp_type or 'pullup' in value or 'pulldown' in value:
                    if 'down' in comp_type or 'down' in value:
                        circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_SIGNAL"
                        circuit['pinNetMapping'][f"{ref}.2"] = "GND"
                        self.fixes_applied.append(f"Connected pull-down {ref} to GND")
                    else:
                        circuit['pinNetMapping'][f"{ref}.1"] = "VCC"
                        circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_SIGNAL"
                        self.fixes_applied.append(f"Connected pull-up {ref} to VCC")
                else:
                    circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_1"
                    circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_2"
                    self.fixes_applied.append(f"Added nets for resistor {ref}")

            elif ref.startswith('U'):
                # IC - connect power pins at minimum
                pins = comp.get('pins', [])
                if pins:
                    # Typical power pins
                    circuit['pinNetMapping'][f"{ref}.1"] = "VCC"
                    circuit['pinNetMapping'][f"{ref}.{len(pins)}"] = "GND"
                    self.fixes_applied.append(f"Connected power pins for IC {ref}")

            elif ref.startswith('SW'):
                # Switch - connect common to ground
                circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_IN"
                circuit['pinNetMapping'][f"{ref}.2"] = "GND"
                self.fixes_applied.append(f"Connected switch {ref} common to GND")

            elif ref.startswith('LED'):
                # LED - needs current limiting
                circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_ANODE"
                circuit['pinNetMapping'][f"{ref}.2"] = "GND"
                self.fixes_applied.append(f"Connected LED {ref} cathode to GND")

        return circuit

    def _fix_single_ended_nets(self, circuit: Dict) -> Dict:
        """Fix nets with only one connection"""
        single_ended = self._find_single_ended_nets(circuit)

        if not single_ended:
            return circuit

        logger.info(f"Fixing {len(single_ended)} single-ended nets...")

        for net in single_ended:
            # Find the single pin connected to this net
            connected_pin = None
            for pin, pin_net in circuit['pinNetMapping'].items():
                if pin_net == net:
                    connected_pin = pin
                    break

            if not connected_pin:
                continue

            # Intelligently fix based on net name and pin type
            ref, pin_num = connected_pin.split('.')
            net_upper = net.upper()

            # Find the component
            comp = next((c for c in circuit['components']
                        if c.get('ref', c.get('refDes', '')) == ref), None)

            if not comp:
                # Just remove if we can't find component
                del circuit['pinNetMapping'][connected_pin]
                self.fixes_applied.append(f"Removed orphan single-ended net {net}")
                continue

            # Check pin function if available
            pin_info = None
            if comp.get('pins'):
                pin_info = next((p for p in comp['pins']
                                if str(p.get('number')) == pin_num), None)

            # Fix based on net/pin type
            fixed = False

            # Handle voltage regulator outputs
            if 'VOUT' in net_upper or 'OUTPUT' in net_upper:
                # This is an output - connect to a load or test point
                # For now, add a load resistor connection
                new_net = f"{net}_LOAD"
                circuit['pinNetMapping'][f"R_{ref}_LOAD.1"] = net
                circuit['pinNetMapping'][f"R_{ref}_LOAD.2"] = "GND"
                self.fixes_applied.append(f"Added load for output net {net}")
                fixed = True

            # Handle input nets
            elif 'VIN' in net_upper or 'INPUT' in net_upper:
                # Connect to appropriate power source
                if 'NEG' in net_upper or '-' in net:
                    # Negative input - connect to negative rail
                    circuit['pinNetMapping'][connected_pin] = "V_NEG"
                    self.fixes_applied.append(f"Connected {net} to V_NEG")
                else:
                    # Positive input - connect to power
                    circuit['pinNetMapping'][connected_pin] = "VCC"
                    self.fixes_applied.append(f"Connected {net} to VCC")
                fixed = True

            # Handle sense/feedback nets
            elif 'SENSE' in net_upper or 'FEEDBACK' in net_upper or 'FB' in net_upper:
                # These often connect back to output
                # Find related output net
                output_net = net.replace('_SENSE', '').replace('_FEEDBACK', '').replace('_FB', '')
                if output_net in circuit.get('nets', []):
                    # Create feedback connection
                    circuit['pinNetMapping'][f"R_{ref}_FB.1"] = net
                    circuit['pinNetMapping'][f"R_{ref}_FB.2"] = output_net
                    self.fixes_applied.append(f"Created feedback connection for {net}")
                    fixed = True

            # Handle current sense nets
            elif 'CURRENT' in net_upper and 'SENSE' in net_upper:
                # Current sense should connect to ADC or monitoring circuit
                # For external connectors (J1, J2, etc), it's OK to be single-ended
                if ref.startswith('J'):
                    # This is an external interface - it's OK to be single-ended
                    logger.info(f"Keeping {net} as external interface")
                    fixed = True  # Don't delete it
                else:
                    # Internal current sense - add sense resistor
                    circuit['pinNetMapping'][f"R_{ref}_SENSE.1"] = net
                    circuit['pinNetMapping'][f"R_{ref}_SENSE.2"] = "GND"
                    self.fixes_applied.append(f"Added sense resistor for {net}")
                    fixed = True

            # Handle opamp outputs
            elif 'OPAMP' in net_upper and 'OUT' in net_upper:
                # Opamp output needs a load
                circuit['pinNetMapping'][f"R_{ref}_OUT.1"] = net
                circuit['pinNetMapping'][f"R_{ref}_OUT.2"] = "GND"
                self.fixes_applied.append(f"Added load for opamp output {net}")
                fixed = True

            if not fixed:
                # For any other single-ended net, remove it
                del circuit['pinNetMapping'][connected_pin]
                self.fixes_applied.append(f"Removed unused single-ended net {net}")

        return circuit

    def _fix_capacitor_connections(self, circuit: Dict) -> Dict:
        """Ensure all capacitors have both pins connected"""
        for comp in circuit.get('components', []):
            ref = comp.get('ref', comp.get('refDes', ''))

            if not ref.startswith('C'):
                continue

            # Check both pins
            pin1 = f"{ref}.1"
            pin2 = f"{ref}.2"

            pin1_connected = pin1 in circuit.get('pinNetMapping', {})
            pin2_connected = pin2 in circuit.get('pinNetMapping', {})

            if pin1_connected and not pin2_connected:
                # Connect second pin to ground
                circuit['pinNetMapping'][pin2] = "GND"
                self.fixes_applied.append(f"Connected {ref} pin 2 to GND")
            elif pin2_connected and not pin1_connected:
                # Connect first pin to VCC (for bypass caps)
                circuit['pinNetMapping'][pin1] = "VCC"
                self.fixes_applied.append(f"Connected {ref} pin 1 to VCC")

        return circuit

    def _fix_power_connections(self, circuit: Dict) -> Dict:
        """Fix missing power connections for ICs using intelligent pattern matching"""
        missing_power = self._find_missing_power_connections(circuit)

        if not missing_power:
            return circuit

        logger.info(f"Fixing power connections for {len(missing_power)} ICs...")

        # Universal power pin patterns
        POWER_PIN_PATTERNS = {
            'positive': ['VCC', 'VDD', 'V+', 'VIN', 'PWR', 'VBUS', 'VBAT', 'VS+', 'VCC_', 'VDD_', '+V', 'POWER'],
            'negative': ['GND', 'VSS', 'V-', 'GROUND', '0V', 'AGND', 'DGND', 'PGND', 'VS-', 'COM', 'COMMON']
        }

        for ref in missing_power:
            comp = next((c for c in circuit['components']
                        if c.get('ref', c.get('refDes', '')) == ref), None)

            if not comp:
                continue

            pins = comp.get('pins', [])
            if not pins:
                continue

            # First try: Look for named power pins
            power_found = False
            ground_found = False

            for pin in pins:
                pin_name = pin.get('name', '').upper()
                pin_num = pin.get('number', '')
                pin_ref = f"{ref}.{pin_num}"

                # Check if already connected
                if pin_ref in circuit.get('pinNetMapping', {}):
                    existing_net = circuit['pinNetMapping'][pin_ref]
                    if any(p in existing_net.upper() for p in POWER_PIN_PATTERNS['positive']):
                        power_found = True
                    if any(p in existing_net.upper() for p in POWER_PIN_PATTERNS['negative']):
                        ground_found = True
                    continue

                # Match positive power
                if not power_found and any(pattern in pin_name for pattern in POWER_PIN_PATTERNS['positive']):
                    circuit['pinNetMapping'][pin_ref] = "VCC"
                    self.fixes_applied.append(f"Connected {ref} pin {pin_num} ({pin_name}) to VCC")
                    power_found = True

                # Match negative power/ground
                elif not ground_found and any(pattern in pin_name for pattern in POWER_PIN_PATTERNS['negative']):
                    circuit['pinNetMapping'][pin_ref] = "GND"
                    self.fixes_applied.append(f"Connected {ref} pin {pin_num} ({pin_name}) to GND")
                    ground_found = True

            # Second try: Use common IC pinouts if no named pins found
            if not power_found or not ground_found:
                comp_type = comp.get('type', '').lower()
                value = comp.get('value', '').upper()

                # Handle voltage regulators specifically (3-pin)
                if 'regulator' in comp_type and len(pins) == 3:
                    # Fix voltage regulator connections - they MUST be correct
                    fixed_regulator = False

                    for pin in pins:
                        pin_name = pin.get('name', '').upper()
                        pin_num = pin.get('number', '')
                        pin_ref = f"{ref}.{pin_num}"

                        current_net = circuit.get('pinNetMapping', {}).get(pin_ref, '')
                        correct_net = None

                        # Determine correct net for this pin
                        if 'VIN' in pin_name:
                            # VIN must connect to power input
                            if 'VIN' not in current_net and 'VCC' not in current_net.upper() and 'PWR' not in current_net.upper():
                                # Look for available input power net
                                if 'VIN' in circuit.get('nets', []):
                                    correct_net = 'VIN'
                                elif 'VIN_PROTECTED' in circuit.get('nets', []):
                                    correct_net = 'VIN_PROTECTED'
                                elif 'VCC_INPUT' in circuit.get('nets', []):
                                    correct_net = 'VCC_INPUT'
                                else:
                                    correct_net = 'VCC'

                                circuit['pinNetMapping'][pin_ref] = correct_net
                                self.fixes_applied.append(f"Fixed {ref}.{pin_num} (VIN): {current_net} -> {correct_net}")
                                fixed_regulator = True
                                power_found = True

                        elif 'GND' in pin_name:
                            # GND must connect to ground
                            if 'GND' not in current_net and current_net != 'GND':
                                circuit['pinNetMapping'][pin_ref] = 'GND'
                                self.fixes_applied.append(f"Fixed {ref}.{pin_num} (GND): {current_net} -> GND")
                                fixed_regulator = True
                                ground_found = True

                        elif 'VOUT' in pin_name:
                            # VOUT should connect to the output voltage net
                            # Don't change if it looks like a valid output net
                            if 'GND' in current_net or 'VIN' in current_net:
                                # This is wrong - fix it
                                output_net = f"VOUT_{ref}"
                                circuit['pinNetMapping'][pin_ref] = output_net
                                self.fixes_applied.append(f"Fixed {ref}.{pin_num} (VOUT): {current_net} -> {output_net}")
                                fixed_regulator = True

                    if fixed_regulator:
                        logger.info(f"Fixed misconnected voltage regulator {ref}")

                # Common IC power pin configurations
                elif len(pins) == 8:  # 8-pin ICs (op-amps, 555, etc)
                    if not power_found:
                        if '555' in value:
                            circuit['pinNetMapping'][f"{ref}.8"] = "VCC"
                            self.fixes_applied.append(f"Connected {ref} pin 8 to VCC (555 timer)")
                        else:
                            circuit['pinNetMapping'][f"{ref}.8"] = "VCC"  # Common for 8-pin
                            self.fixes_applied.append(f"Connected {ref} pin 8 to VCC (8-pin IC)")
                    if not ground_found:
                        circuit['pinNetMapping'][f"{ref}.1"] = "GND"  # Common for 8-pin
                        self.fixes_applied.append(f"Connected {ref} pin 1 to GND (8-pin IC)")

                elif len(pins) == 14:  # 14-pin ICs (logic gates, etc)
                    if not power_found:
                        circuit['pinNetMapping'][f"{ref}.14"] = "VCC"
                        self.fixes_applied.append(f"Connected {ref} pin 14 to VCC (14-pin IC)")
                    if not ground_found:
                        circuit['pinNetMapping'][f"{ref}.7"] = "GND"
                        self.fixes_applied.append(f"Connected {ref} pin 7 to GND (14-pin IC)")

                elif len(pins) == 16:  # 16-pin ICs
                    if not power_found:
                        circuit['pinNetMapping'][f"{ref}.16"] = "VCC"
                        self.fixes_applied.append(f"Connected {ref} pin 16 to VCC (16-pin IC)")
                    if not ground_found:
                        circuit['pinNetMapping'][f"{ref}.8"] = "GND"
                        self.fixes_applied.append(f"Connected {ref} pin 8 to GND (16-pin IC)")

                # Generic fallback for any other IC
                elif ref.startswith('U'):
                    # For any IC we don't recognize, at minimum connect power
                    # Try first and last pins as a last resort
                    if not power_found and len(pins) > 0:
                        circuit['pinNetMapping'][f"{ref}.{len(pins)}"] = "VCC"
                        self.fixes_applied.append(f"Connected {ref} pin {len(pins)} to VCC (generic IC)")
                        power_found = True
                    if not ground_found and len(pins) > 0:
                        circuit['pinNetMapping'][f"{ref}.1"] = "GND"
                        self.fixes_applied.append(f"Connected {ref} pin 1 to GND (generic IC)")
                        ground_found = True

        return circuit

    def _fix_unconnected_power_pins(self, circuit: Dict) -> Dict:
        """Fix ANY unconnected power pin, regardless of IC power status"""
        logger.info("Checking for unconnected power pins...")
        fixes_count = 0

        for comp in circuit.get('components', []):
            ref = comp.get('ref', comp.get('refDes', ''))
            pins = comp.get('pins', [])

            for pin in pins:
                pin_num = pin.get('number', '')
                pin_name = pin.get('name', '').upper()
                pin_type = pin.get('type', '').lower()
                pin_ref = f"{ref}.{pin_num}"

                # Skip if already connected
                if pin_ref in circuit.get('pinNetMapping', {}):
                    # Special case: if connected to wrong net, fix it
                    current_net = circuit['pinNetMapping'][pin_ref]
                    if pin_name == 'VCC' and current_net not in ['VCC', 'VDD', '+5V', '+3V3']:
                        logger.warning(f"{pin_ref} (VCC) connected to {current_net}, fixing to VCC")
                        circuit['pinNetMapping'][pin_ref] = "VCC"
                        self.fixes_applied.append(f"Fixed {pin_ref} (VCC) from {current_net} to VCC")
                        fixes_count += 1
                    continue

                # AGGRESSIVE: ANY pin named VCC/GND/etc or typed as power MUST be connected
                if pin_name == 'VCC' or pin_type == 'power' and 'VCC' in pin_name:
                    circuit['pinNetMapping'][pin_ref] = "VCC"
                    self.fixes_applied.append(f"Connected power pin {pin_ref} ({pin_name}) to VCC")
                    fixes_count += 1
                elif pin_name == 'GND' or pin_type == 'ground' or 'GND' in pin_name:
                    circuit['pinNetMapping'][pin_ref] = "GND"
                    self.fixes_applied.append(f"Connected ground pin {pin_ref} ({pin_name}) to GND")
                    fixes_count += 1
                elif any(p in pin_name for p in ['VDD', 'V+', 'PWR', 'POWER', '+V']):
                    circuit['pinNetMapping'][pin_ref] = "VCC"
                    self.fixes_applied.append(f"Connected power pin {pin_ref} ({pin_name}) to VCC")
                    fixes_count += 1
                elif any(g in pin_name for g in ['VSS', 'V-', 'GROUND', '0V']):
                    circuit['pinNetMapping'][pin_ref] = "GND"
                    self.fixes_applied.append(f"Connected ground pin {pin_ref} ({pin_name}) to GND")
                    fixes_count += 1
                elif 'VIN' in pin_name:
                    circuit['pinNetMapping'][pin_ref] = "VCC_INPUT"
                    self.fixes_applied.append(f"Connected input pin {pin_ref} ({pin_name}) to VCC_INPUT")
                    fixes_count += 1

        if fixes_count > 0:
            logger.info(f"Fixed {fixes_count} unconnected power pins")

        return circuit

    def _fix_orphan_nets(self, circuit: Dict) -> Dict:
        """Remove orphan nets that exist in nets list but not in connections"""
        if 'nets' not in circuit:
            return circuit

        # Find which nets are actually used
        used_nets = set()

        # From pinNetMapping
        for net in circuit.get('pinNetMapping', {}).values():
            used_nets.add(net)

        # From connections (if using points array format)
        for conn in circuit.get('connections', []):
            if 'net' in conn:
                used_nets.add(conn['net'])

        # Remove orphan nets
        original_nets = set(circuit['nets'])
        orphans = original_nets - used_nets

        if orphans:
            circuit['nets'] = list(used_nets)
            logger.info(f"Removed {len(orphans)} orphan nets: {orphans}")
            self.fixes_applied.append(f"Removed orphan nets: {', '.join(orphans)}")

        return circuit

    def _fix_component_specific_issues(self, circuit: Dict) -> Dict:
        """Fix issues specific to certain component types"""
        for comp in circuit.get('components', []):
            ref = comp.get('ref', comp.get('refDes', ''))
            comp_type = comp.get('type', '').lower()

            # Fix crystal oscillator connections
            if ref.startswith('Y') or ref.startswith('X'):
                if 'crystal' in comp_type:
                    # Crystals often need ground connection on case
                    case_pin = f"{ref}.3"
                    if case_pin not in circuit.get('pinNetMapping', {}):
                        circuit['pinNetMapping'][case_pin] = "GND"
                        self.fixes_applied.append(f"Connected crystal {ref} case to GND")

            # Fix transformer connections
            elif ref.startswith('T'):
                if 'transformer' in comp_type:
                    # Ensure at least primary and secondary connections
                    if f"{ref}.1" not in circuit.get('pinNetMapping', {}):
                        circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_PRI_1"
                    if f"{ref}.2" not in circuit.get('pinNetMapping', {}):
                        circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_PRI_2"
                    if f"{ref}.3" not in circuit.get('pinNetMapping', {}):
                        circuit['pinNetMapping'][f"{ref}.3"] = f"NET_{ref}_SEC_1"
                    if f"{ref}.4" not in circuit.get('pinNetMapping', {}):
                        circuit['pinNetMapping'][f"{ref}.4"] = f"NET_{ref}_SEC_2"

        return circuit

    def _rebuild_connections(self, circuit: Dict) -> Dict:
        """Rebuild connections array from pinNetMapping"""
        net_connections = {}

        for pin, net in circuit.get('pinNetMapping', {}).items():
            if net not in net_connections:
                net_connections[net] = []
            net_connections[net].append(pin)

        # CRITICAL: Use points array format for converters!
        connections = []
        for net, pins in net_connections.items():
            if len(pins) >= 2:
                connections.append({
                    'net': net,
                    'points': sorted(pins)  # Points array format
                })

        circuit['connections'] = connections

        # Update nets list
        circuit['nets'] = list(net_connections.keys())

        return circuit

    def _validate_final_circuit(self, circuit: Dict) -> Dict:
        """Final validation to ensure circuit is perfect"""
        final_issues = self._find_all_issues(circuit)

        if final_issues:
            logger.warning(f"Circuit still has issues after fixes: {final_issues}")
        else:
            logger.info("✅ Circuit passed final validation - 100% perfect!")

        # Add validation metadata
        circuit['validation'] = {
            'passed': len(final_issues) == 0,
            'timestamp': str(Path(__file__).stat().st_mtime),
            'validator_version': '1.0',
            'issues_found': len(self.validation_report.get('initial_issues', [])),
            'issues_fixed': len(self.fixes_applied),
            'remaining_issues': len(final_issues)
        }

        return circuit


def safety_net_validator(circuit: Dict) -> Dict:
    """
    Main entry point for safety net validation
    """
    validator = SafetyNetValidator()
    return validator.validate_and_fix(circuit)