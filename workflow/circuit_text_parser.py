# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Circuit Text Parser
Converts simple text instructions from AI into proper circuit JSON format

Example Input:
    R1 = resistor(10k, 0603)
    C1 = capacitor(100nF, 0603)
    U1 = ic(STM32F103, LQFP48)

    connect R1.1 to VCC
    connect R1.2 to U1.23
    connect C1.1 to U1.23
    connect C1.2 to GND

Example Output:
    {
        "circuit": {
            "components": [...],
            "connections": [...],
            "nets": [...]
        }
    }
"""

import re
import logging
from typing import Dict, List, Any, Tuple, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class CircuitTextParser:
    """Parse simple text circuit descriptions into JSON format"""

    def __init__(self):
        self.components = {}
        self.connections = []
        self.nets = defaultdict(list)
        self.pin_net_mapping = {}
        self.component_connections = defaultdict(set)  # Track which pins are referenced per component

    def parse(self, text: str) -> Dict[str, Any]:
        """
        Parse text circuit description into JSON format

        Args:
            text: Simple text circuit description

        Returns:
            Circuit in JSON format ready for converters
        """
        # Reset state
        self.components = {}
        self.connections = []
        self.nets = defaultdict(list)
        self.pin_net_mapping = {}
        self.component_connections = defaultdict(set)

        # FIRST PASS: Collect component definitions and track pin references
        lines = text.strip().split('\n')
        component_definitions = []  # Store component definition lines

        for line_num, line in enumerate(lines, 1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#') or line.startswith('//'):
                continue

            try:
                if '=' in line and '(' in line and ')' in line:
                    # Store component declaration for later processing
                    component_definitions.append(line)
                elif line.lower().startswith('connect'):
                    # Track which pins are referenced
                    self._track_pin_references(line)
                elif line.lower().startswith('net'):
                    # Track pins in net definitions
                    self._track_net_pin_references(line)
                else:
                    logger.debug(f"Line {line_num}: Skipping unrecognized format: {line}")

            except Exception as e:
                logger.warning(f"Line {line_num}: Error in first pass '{line}': {e}")

        # SECOND PASS: Create components with correct pin counts based on actual usage
        for line in component_definitions:
            try:
                self._parse_component(line)
            except Exception as e:
                logger.warning(f"Error parsing component '{line}': {e}")

        # THIRD PASS: Process connections now that components are properly defined
        for line_num, line in enumerate(lines, 1):
            line = line.strip()

            if line and not line.startswith('#') and not line.startswith('//'):
                try:
                    if line.lower().startswith('connect'):
                        self._parse_connection(line)
                    elif line.lower().startswith('net'):
                        self._parse_net(line)
                except Exception as e:
                    logger.warning(f"Line {line_num}: Error in third pass '{line}': {e}")

        # Build final circuit structure
        return self._build_circuit()

    def _track_pin_references(self, line: str) -> None:
        """Track which pins are referenced in connections (FIRST PASS)"""
        # Strip inline comments first
        line = re.sub(r'#.*$', '', line).strip()
        # Extract all component.pin references
        pins = re.findall(r'(\w+)\.(\d+)', line)
        for comp_ref, pin_num in pins:
            self.component_connections[comp_ref].add(pin_num)

    def _track_net_pin_references(self, line: str) -> None:
        """Track which pins are referenced in net definitions (FIRST PASS)"""
        # Strip inline comments first
        line = re.sub(r'#.*$', '', line).strip()
        # Extract all component.pin references
        pins = re.findall(r'(\w+)\.(\d+)', line)
        for comp_ref, pin_num in pins:
            self.component_connections[comp_ref].add(pin_num)

    def _get_actual_pin_count(self, comp_ref: str, default_count: int) -> int:
        """
        Determine actual pin count based on connections made.
        UNIVERSAL - works for any component type.
        """
        if comp_ref in self.component_connections:
            pins_used = self.component_connections[comp_ref]
            if pins_used:
                # Return highest pin number referenced
                return max(int(pin) for pin in pins_used)
        return default_count

    def _is_potentiometer(self, comp_type: str, package: str, comp_ref: str) -> bool:
        """
        UNIVERSAL potentiometer detection.
        Detects from package name, value format, OR connection count.
        Works for ANY potentiometer without hardcoding.
        """
        # Check 1: Package name contains POT, TRIM, RV, BOURNS, etc.
        pot_indicators = ['POT', 'TRIM', 'RV-', 'BOURNS', 'VARIABLE']
        if any(indicator in package.upper() for indicator in pot_indicators):
            return True

        # Check 2: Resistor with 3 pins connected = potentiometer
        if comp_type in ['resistor', 'r']:
            actual_pins = self._get_actual_pin_count(comp_ref, 2)
            if actual_pins == 3:
                return True

        return False

    def _is_relay(self, value: str, comp_ref: str) -> bool:
        """
        GENERIC relay detection from component value/part number.
        Relays are often declared as ic(...) but have different validation rules.

        This function is intentionally GENERIC and pattern-based so it works across
        all circuit types without being tied to specific examples.

        Detection patterns:
        - Common relay series: G5V, G6K, HF, HFD, JQ, AQH, TQ, DIP reed relays
        - Manufacturer patterns: OMRON-G, HF-relay, G5V-1, etc.
        - Generic keywords: RELAY (though less common in part numbers)

        Args:
            value: Component value/part number (e.g., "G5V-1", "HFD3/12", "RELAY-SPDT")
            comp_ref: Component reference (e.g., "U5", "K1", "RLY1")

        Returns:
            True if component is detected as a relay, False otherwise
        """
        if not value:
            return False

        value_upper = value.upper()

        # Check 1: Common relay series patterns (GENERIC, manufacturer-agnostic)
        relay_series_patterns = [
            'G5V', 'G6K', 'G2R', 'G3MB',  # Omron relay series
            'HF', 'HFD', 'HFA',  # Hongfa/HF relays
            'JQ', 'JQC', 'JQX',  # Songle/JQ series
            'AQH', 'AQV', 'AQZ',  # Panasonic PhotoMOS relays
            'TQ', 'TQ2',  # Fujitsu relays
            'RELAY',  # Generic keyword
            'S1A05', 'S1D',  # Sharp/Cosmo relays
            'DIP-REED',  # DIP reed relays
        ]

        for pattern in relay_series_patterns:
            if pattern in value_upper:
                return True

        # Check 2: Reference designator patterns (K or RLY prefix common for relays)
        # Note: This is a secondary check, not primary (some designs use U for relays)
        if comp_ref and (comp_ref.startswith('K') or comp_ref.startswith('RLY')):
            return True

        return False

    def _parse_component(self, line: str) -> None:
        """
        Parse component declaration with DYNAMIC pin count detection.
        UNIVERSAL - works for any component type, any pin count.

        Examples:
            R1 = resistor(10k, 0603) -> 2 pins (normal resistor)
            RV1 = resistor(10k, POT-9MM) -> 3 pins (potentiometer auto-detected)
            U1 = ic(STM32F103, LQFP48) -> 48 pins (from package)
        """
        # Extract component ID and definition
        match = re.match(r'(\w+)\s*=\s*(\w+)\((.*?)\)', line)
        if not match:
            raise ValueError(f"Invalid component format: {line}")

        comp_id = match.group(1)
        comp_type = match.group(2).lower()
        params = match.group(3)

        # Parse parameters
        params_list = [p.strip() for p in params.split(',')]

        # Create component structure
        component = {
            'ref': comp_id,
            'type': self._normalize_type(comp_type),
            'pins': []  # Will be populated based on type
        }

        # UNIVERSAL COMPONENT HANDLING
        # Handle different component types with DYNAMIC pin count
        if comp_type in ['resistor', 'r']:
            component['value'] = params_list[0] if params_list else '1k'
            component['package'] = params_list[1] if len(params_list) > 1 else '0603'

            # UNIVERSAL POTENTIOMETER DETECTION
            if self._is_potentiometer(comp_type, component['package'], comp_id):
                # It's a potentiometer - needs 3 pins
                logger.info(f"Detected {comp_id} as potentiometer (package: {component['package']})")
                component['pins'] = [
                    {"number": "1", "name": "1", "type": "passive"},  # End 1
                    {"number": "2", "name": "2", "type": "passive"},  # Wiper
                    {"number": "3", "name": "3", "type": "passive"}   # End 2
                ]
            else:
                # Regular 2-pin resistor
                component['pins'] = [
                    {"number": "1", "name": "1", "type": "passive"},
                    {"number": "2", "name": "2", "type": "passive"}
                ]

        elif comp_type in ['capacitor', 'c']:
            component['value'] = params_list[0] if params_list else '100nF'
            component['package'] = params_list[1] if len(params_list) > 1 else '0603'
            component['pins'] = [
                {"number": "1", "name": "1", "type": "passive"},
                {"number": "2", "name": "2", "type": "passive"}
            ]

        elif comp_type in ['inductor', 'l']:
            component['value'] = params_list[0] if params_list else '10uH'
            component['package'] = params_list[1] if len(params_list) > 1 else '0603'
            component['pins'] = [
                {"number": "1", "name": "1", "type": "passive"},
                {"number": "2", "name": "2", "type": "passive"}
            ]

        elif comp_type in ['diode', 'd']:
            component['value'] = params_list[0] if params_list else '1N4148'
            component['package'] = params_list[1] if len(params_list) > 1 else 'SOD-123'
            component['pins'] = [
                {"number": "1", "name": "A", "type": "passive"},
                {"number": "2", "name": "K", "type": "passive"}
            ]

        elif comp_type in ['transistor', 'bjt', 'q']:
            component['value'] = params_list[0] if params_list else '2N2222'
            component['package'] = params_list[1] if len(params_list) > 1 else 'SOT-23'
            component['pins'] = [
                {"number": "1", "name": "B", "type": "input"},
                {"number": "2", "name": "C", "type": "passive"},
                {"number": "3", "name": "E", "type": "passive"}
            ]

        elif comp_type in ['mosfet', 'fet', 'm']:
            component['value'] = params_list[0] if params_list else 'BSS138'
            component['package'] = params_list[1] if len(params_list) > 1 else 'SOT-23'
            component['pins'] = [
                {"number": "1", "name": "G", "type": "input"},
                {"number": "2", "name": "D", "type": "passive"},
                {"number": "3", "name": "S", "type": "passive"}
            ]

        elif comp_type in ['ic', 'chip', 'u']:
            component['value'] = params_list[0] if params_list else 'UNKNOWN'
            component['package'] = params_list[1] if len(params_list) > 1 else 'DIP-8'

            # GENERIC RELAY DETECTION: Check if this IC is actually a relay
            # Relays are often declared as ic(...) but have different validation rules
            if self._is_relay(component['value'], comp_id):
                component['type'] = 'relay'
                logger.info(f"Detected {comp_id} as relay (value: {component['value']})")

            # Determine pin count from package
            pin_count = self._get_pin_count_from_package(component['package'])
            component['pins'] = [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(pin_count)
            ]

        elif comp_type in ['connector', 'conn', 'j']:
            pin_count = int(params_list[0]) if params_list and params_list[0].isdigit() else 2
            component['value'] = f'{pin_count}-pin'
            component['package'] = params_list[1] if len(params_list) > 1 else f'HDR-{pin_count}'
            component['pins'] = [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(pin_count)
            ]

        else:
            # Unknown type - DYNAMICALLY determine pin count from connections
            component['value'] = params_list[0] if params_list else 'UNKNOWN'
            component['package'] = params_list[1] if len(params_list) > 1 else 'UNKNOWN'

            # UNIVERSAL: Infer pin count from actual connections made
            actual_pin_count = self._get_actual_pin_count(comp_id, 2)
            component['pins'] = [
                {"number": str(i+1), "name": str(i+1), "type": "passive"}
                for i in range(actual_pin_count)
            ]

            if actual_pin_count > 2:
                logger.info(f"Unknown component type '{comp_type}' for {comp_id}, inferred {actual_pin_count} pins from connections")
            else:
                logger.warning(f"Unknown component type '{comp_type}' for {comp_id}, defaulting to 2 pins")

        self.components[comp_id] = component

    def _parse_connection(self, line: str) -> None:
        """
        Parse connection statement
        Examples:
            connect R1.1 to VCC
            connect R1.2 to U1.23
            connect R1.2, C1.1, U1.23  (multiple points)
            connect F1.1 to J1.1  # Comments are stripped
        """
        # CRITICAL: Strip inline comments first (before processing)
        line = re.sub(r'#.*$', '', line).strip()

        # Remove 'connect' prefix
        conn_text = re.sub(r'^connect\s+', '', line, flags=re.IGNORECASE).strip()

        # Check for different formats
        if ' to ' in conn_text.lower():
            # Format: connect A to B
            parts = re.split(r'\s+to\s+', conn_text, flags=re.IGNORECASE)
            if len(parts) == 2:
                points = [parts[0].strip(), parts[1].strip()]
            else:
                raise ValueError(f"Invalid connection format: {line}")
        elif ',' in conn_text:
            # Format: connect A, B, C
            points = [p.strip() for p in conn_text.split(',')]
        else:
            # Format: connect A B
            points = conn_text.split()

        if len(points) < 2:
            raise ValueError(f"Connection needs at least 2 points: {line}")

        # Process connection points
        processed_points = []
        net_name = None

        for point in points:
            # Check if it's a component pin (e.g., R1.1) or net name (e.g., VCC)
            if '.' in point:
                # Component pin
                processed_points.append(point)
            else:
                # Net name
                if net_name and net_name != point:
                    logger.warning(f"Multiple net names in connection: {net_name} and {point}")
                net_name = point.upper()

        # Create appropriate connection with NET MERGING
        if net_name:
            # Named net connection
            # Ensure the net exists in self.nets even if empty
            if net_name not in self.nets:
                self.nets[net_name] = []

            for point in processed_points:
                # Check if pin already assigned to a different net
                if point in self.pin_net_mapping:
                    existing_net = self.pin_net_mapping[point]
                    if existing_net != net_name:
                        # CRITICAL FIX: Determine merge direction based on net priority
                        # Power/Ground nets should NEVER be merged into signal nets
                        # Priority: GND > VCC/VDD/VSS > Signal nets
                        power_nets = ['GND', 'VCC', 'VDD', 'VSS', 'GROUND', 'V+', 'V-']

                        existing_is_power = any(x in existing_net.upper() for x in power_nets)
                        new_is_power = any(x in net_name.upper() for x in power_nets)

                        if existing_is_power and not new_is_power:
                            # Existing net is power, new is signal - Don't merge power into signal
                            # Strategy: Keep the pin on the power net, don't reassign it
                            # The signal net will still exist (created above) for future connections
                            logger.warning(f"⚠️  Pin {point} already on power net {existing_net}, NOT changing to signal net {net_name}")
                            logger.warning(f"    Keeping {point} on {existing_net} (power nets take priority)")
                            # Pin stays on existing power net - don't add to new net
                        elif new_is_power and not existing_is_power:
                            # New net is power, existing is signal - merge signal into power
                            logger.info(f"Merging signal net {existing_net} into power net {net_name} via {point}")
                            # Move all pins from existing_net to new power net
                            for old_point in list(self.nets[existing_net]):
                                if old_point not in self.nets[net_name]:
                                    self.nets[net_name].append(old_point)
                                self.pin_net_mapping[old_point] = net_name
                            # Remove old signal net
                            del self.nets[existing_net]
                        else:
                            # Both are signals or both are power - merge as before
                            logger.info(f"Merging net {existing_net} into {net_name} via {point}")
                            for old_point in list(self.nets[existing_net]):
                                if old_point not in self.nets[net_name]:
                                    self.nets[net_name].append(old_point)
                                self.pin_net_mapping[old_point] = net_name
                            # Remove old net
                            del self.nets[existing_net]
                else:
                    # New pin assignment
                    if point not in self.nets[net_name]:
                        self.nets[net_name].append(point)
                    self.pin_net_mapping[point] = net_name
        else:
            # Direct connection between components - check if any point already has a net
            existing_net = None
            for point in processed_points:
                if point in self.pin_net_mapping:
                    existing_net = self.pin_net_mapping[point]
                    break

            if existing_net:
                # Use existing net and merge all points into it
                net_name = existing_net
                for point in processed_points:
                    if point not in self.nets[net_name]:
                        self.nets[net_name].append(point)
                    self.pin_net_mapping[point] = net_name
            else:
                # Create new anonymous net
                net_name = f"NET_{len(self.nets) + 1}"
                for point in processed_points:
                    self.nets[net_name].append(point)
                    self.pin_net_mapping[point] = net_name

    def _parse_net(self, line: str) -> None:
        """
        Parse net definition
        Examples:
            net VCC includes U1.8, U2.4, R1.1
            net GND: U1.4, U2.2, C1.2
        """
        # Extract net name and points
        match = re.match(r'net\s+(\w+)[\s:]+(?:includes\s+)?(.*)', line, re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid net format: {line}")

        net_name = match.group(1).upper()
        points_text = match.group(2)

        # Parse points
        points = [p.strip() for p in re.split(r'[,\s]+', points_text) if p.strip()]

        for point in points:
            if '.' in point:  # Valid component pin
                self.nets[net_name].append(point)
                self.pin_net_mapping[point] = net_name
            else:
                logger.warning(f"Invalid pin format in net definition: {point}")

    def _normalize_type(self, comp_type: str) -> str:
        """Normalize component type names"""
        type_map = {
            'r': 'resistor',
            'c': 'capacitor',
            'l': 'inductor',
            'd': 'diode',
            'q': 'transistor',
            'bjt': 'transistor',
            'm': 'mosfet',
            'fet': 'mosfet',
            'u': 'ic',
            'chip': 'ic',
            'j': 'connector',
            'conn': 'connector'
        }
        return type_map.get(comp_type.lower(), comp_type.lower())

    def _get_pin_count_from_package(self, package: str) -> int:
        """Extract pin count from package name"""
        # Look for common patterns
        patterns = [
            r'DIP-(\d+)',
            r'SOIC-(\d+)',
            r'LQFP-(\d+)',
            r'QFP-(\d+)',
            r'TQFP-(\d+)',
            r'SSOP-(\d+)',
            r'(\d+)-pin',
            r'(\d+)PIN'
        ]

        for pattern in patterns:
            match = re.search(pattern, package, re.IGNORECASE)
            if match:
                return int(match.group(1))

        # Common packages
        common_packages = {
            'SOT-23': 3,
            'SOT-23-5': 5,
            'SOT-223': 3,
            'TO-220': 3,
            'TO-92': 3,
            'SO-8': 8,
            'DFN-8': 8
        }

        return common_packages.get(package.upper(), 8)  # Default to 8 pins

    def _build_circuit(self) -> Dict[str, Any]:
        """Build final circuit structure from parsed data"""

        # Convert components dict to list
        components_list = list(self.components.values())

        # Build connections from nets
        connections_list = []
        for net_name, points in self.nets.items():
            if len(points) > 1:
                connections_list.append({
                    "net": net_name,
                    "points": points
                })

        # Build nets list
        nets_list = [
            {"name": net_name, "pins": points}
            for net_name, points in self.nets.items()
        ]

        # Build circuit structure
        circuit = {
            "circuit": {
                "moduleName": "Circuit",
                "components": components_list,
                "connections": connections_list,
                "pinNetMapping": self.pin_net_mapping,
                "nets": nets_list
            }
        }

        # Log summary
        logger.info(f"Parsed circuit: {len(components_list)} components, {len(connections_list)} connections")

        return circuit


def parse_circuit_text(text: str, module_name: str = "Circuit") -> Dict[str, Any]:
    """
    Convenience function to parse circuit text

    Args:
        text: Circuit description in simple text format
        module_name: Name for the module

    Returns:
        Circuit in JSON format
    """
    parser = CircuitTextParser()
    circuit = parser.parse(text)
    circuit['circuit']['moduleName'] = module_name
    return circuit


# Example usage and testing
if __name__ == "__main__":
    # Test with sample circuit
    sample_text = """
    # Simple LED circuit
    R1 = resistor(330, 0603)
    D1 = diode(LED, 0805)
    C1 = capacitor(100nF, 0603)
    U1 = ic(555, DIP-8)

    # Connections
    connect R1.1 to VCC
    connect R1.2 to D1.1
    connect D1.2 to GND
    connect C1.1 to VCC
    connect C1.2 to GND
    connect U1.8 to VCC
    connect U1.1 to GND
    """

    import json

    logging.basicConfig(level=logging.INFO)
    result = parse_circuit_text(sample_text, "LED_Blinker")
    print(json.dumps(result, indent=2))