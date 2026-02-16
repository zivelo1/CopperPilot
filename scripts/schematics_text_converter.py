#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Schematics Text Converter - Version 2.0
Converts JSON circuit files to crystal-clear human-readable wiring instructions
Generates step-by-step connection documentation that technicians can follow to wire circuits
"""

import json
import sys
import re
from pathlib import Path
import logging
from datetime import datetime
from collections import defaultdict, OrderedDict
from typing import Dict, List, Set, Tuple, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def is_power_rail(net_name: str) -> bool:
    """
    GENERIC power rail detection - handles ANY naming convention.
    Copied from circuit_supervisor.py to ensure consistency.

    Supports patterns like:
    - Standard: VCC, VDD, VSS, VEE, VBAT, VIN, VOUT
    - Voltage: V12, 12V, V3P3, V1P8, 24VDC, 48VDC
    - Output: V12_OUT, V5_OUT, V3P3_OUT
    - Negative: V12_NEG, VNEG, VEE
    - Special: PWR, PWR_MAIN, VPOS, VBUS
    """
    if not net_name:
        return False

    net = net_name.upper().strip()

    # Standard power rail names
    standard_rail_prefixes = ['VCC', 'VDD', 'VSS', 'VEE', 'VBAT', 'VIN', 'VOUT',
                               'VBUS', 'VPOS', 'VNEG']
    for prefix in standard_rail_prefixes:
        if net.startswith(prefix):
            return True

    # Exact matches for simple patterns
    if net in ['V+', 'V-']:
        return True

    # Voltage-specific patterns
    voltage_patterns = [
        r'^V\d+$',              # V12, V5, V3
        r'^\d+V$',              # 12V, 5V, 3V
        r'^V\d+P\d+',           # V3P3, V1P8, V2P5
        r'^V\d+_',              # V12_OUT, V5_NEG, V12_RAIL
        r'^\d+VDC',             # 24VDC, 48VDC, 12VDC
        r'^PWR',                # PWR, PWR_MAIN, PWR_INPUT
        r'V(POS|NEG)',          # VPOS, VNEG
        r'PROTECTED$',          # VIN_PROTECTED
        r'FUSED$',              # VIN_FUSED
    ]

    for pattern in voltage_patterns:
        if re.search(pattern, net):
            return True

    return False


def is_ground_rail(net_name: str) -> bool:
    """
    GENERIC ground rail detection - handles ANY naming convention.
    Copied from circuit_supervisor.py to ensure consistency.

    Supports patterns like:
    - GND, AGND, DGND, PGND (analog/digital/power ground)
    - VSS, GROUND, EARTH
    - GND_ISO (isolated ground)
    """
    if not net_name:
        return False

    net = net_name.upper().strip()

    # All common ground rail names and patterns
    ground_patterns = ['GND', 'AGND', 'DGND', 'PGND', 'VSS',
                       'GROUND', 'EARTH', 'GND_ISO', 'CHASSIS']

    for pattern in ground_patterns:
        if pattern in net:
            return True

    return False


class CircuitComponent:
    """Represents a circuit component with all its properties"""
    
    def __init__(self, ref_des: str, comp_data: dict):
        self.ref_des = ref_des
        self.type = comp_data.get('type', 'unknown')
        self.value = comp_data.get('value', 'N/A')
        self.specs = comp_data.get('specs', {})
        self.package = comp_data.get('package', '')
        self.notes = comp_data.get('notes', '')
        self.power = comp_data.get('power', '')
        self.connections = {}  # pin -> list of connections
        
    def add_connection(self, pin: str, target_ref: str, target_pin: str, net: str):
        """Add a connection to this component"""
        if pin not in self.connections:
            self.connections[pin] = []
        self.connections[pin].append({
            'target_ref': target_ref,
            'target_pin': target_pin,
            'net': net
        })
    
    def get_pin_count(self) -> int:
        """Get total number of connected pins"""
        return len(self.connections)
    
    def get_type_string(self) -> str:
        """Get formatted component type"""
        type_map = {
            'resistor': 'resistor',
            'capacitor': 'capacitor',
            'inductor': 'inductor',
            'diode': 'diode',
            'led': 'LED',
            'transistor': 'transistor',
            'mosfet': 'MOSFET',
            'op_amp': 'op-amp',
            'voltage_regulator': 'regulator',
            'microcontroller': 'MCU',
            'dds_ic': 'DDS chip',
            'adc': 'ADC',
            'dac': 'DAC',
            'transformer': 'transformer',
            'crystal': 'crystal',
            'connector': 'connector',
            'test_point': 'test point',
            'usb_controller': 'USB controller',
            'gate_driver': 'gate driver',
            'vga': 'VGA',
            'switch': 'switch',
            'relay': 'relay',
            'fuse': 'fuse',
            'thermistor': 'thermistor',
            'potentiometer': 'potentiometer'
        }
        return type_map.get(self.type, self.type.replace('_', ' '))
    
    def get_suggested_part(self) -> str:
        """Get suggested part number if available"""
        return self.specs.get('suggestedPart', '')


class SchematicsTextConverter:
    """Enhanced converter for perfect human-readable wiring instructions"""
    
    def __init__(self):
        self.components = {}  # ref_des -> CircuitComponent
        self.nets = {}  # net_name -> list of connection points
        # REMOVED hardcoded power_nets and ground_nets - now using GENERIC detection functions
        self.module_name = ''
        self.module_type = ''
        self.validation_status = ''
        self.erc_errors = []
        self.drc_errors = []
        
    def load_circuit(self, json_path: Path) -> bool:
        """Load and parse circuit data from JSON file"""
        try:
            with open(json_path, 'r') as f:
                raw_data = json.load(f)

            # CRITICAL: Handle wrapped circuit format {"circuit": {...}}
            if 'circuit' in raw_data and isinstance(raw_data['circuit'], dict):
                data = raw_data['circuit']
            else:
                data = raw_data

            self.module_name = data.get('moduleName', 'Unknown Circuit')
            self.module_type = data.get('moduleType', 'circuit')
            self.validation_status = data.get('validationStatus', 'unchecked')
            
            # Load components
            # FIXED: Use 'ref' (lowlevel format) instead of 'refDes'
            for comp_data in data.get('components', []):
                ref_des = comp_data.get('ref', comp_data.get('refDes', ''))
                if ref_des:
                    self.components[ref_des] = CircuitComponent(ref_des, comp_data)
            
            # Parse connections using the points array format
            connections = data.get('connections', [])
            for conn in connections:
                net_name = conn.get('net', '')
                points = conn.get('points', [])
                
                if net_name and points:
                    # Initialize net if not exists
                    if net_name not in self.nets:
                        self.nets[net_name] = []
                    
                    # Parse all points and add to net
                    parsed_points = []
                    for point in points:
                        if '.' in point:
                            comp_ref, pin = point.split('.', 1)
                            parsed_points.append({'component': comp_ref, 'pin': pin})
                            # Add unique points to net
                            point_dict = {'component': comp_ref, 'pin': pin}
                            if point_dict not in self.nets[net_name]:
                                self.nets[net_name].append(point_dict)
                    
                    # Build component connections for all points in the net
                    for i in range(len(parsed_points)):
                        comp1_ref = parsed_points[i]['component']
                        comp1_pin = parsed_points[i]['pin']
                        
                        if comp1_ref in self.components:
                            # Connect to all other points in the same net
                            for j in range(len(parsed_points)):
                                if i != j:
                                    comp2_ref = parsed_points[j]['component']
                                    comp2_pin = parsed_points[j]['pin']
                                    self.components[comp1_ref].add_connection(
                                        comp1_pin, comp2_ref, comp2_pin, net_name
                                    )
            
            logger.info(f"Loaded {len(self.components)} components and {len(self.nets)} nets")
            return True
            
        except Exception as e:
            logger.error(f"Error loading circuit: {e}")
            return False
    
    def run_erc(self) -> Tuple[bool, List[str]]:
        """Run Electrical Rule Check"""
        errors = []
        
        # Check for unconnected components
        for ref_des, comp in self.components.items():
            if comp.get_pin_count() == 0:
                errors.append(f"Component {ref_des} has no connections")
        
        # Check for single-point nets
        for net_name, points in self.nets.items():
            if len(points) < 2:
                errors.append(f"Net '{net_name}' has only {len(points)} connection point(s)")
        
        # Check for invalid component references in nets
        for net_name, points in self.nets.items():
            for point in points:
                comp_ref = point['component']
                if comp_ref not in self.components:
                    errors.append(f"Invalid component reference '{comp_ref}' in net '{net_name}'")
        
        self.erc_errors = errors
        return len(errors) == 0, errors
    
    def run_drc(self) -> Tuple[bool, List[str]]:
        """Run Design Rule Check"""
        errors = []
        
        # Check for proper power connections using GENERIC detection
        has_power = False
        has_ground = False
        for net_name in self.nets:
            if is_power_rail(net_name) and not is_ground_rail(net_name):
                has_power = True
            if is_ground_rail(net_name):
                has_ground = True
        
        if not has_power:
            errors.append("No power supply nets found in circuit")
        if not has_ground:
            errors.append("No ground nets found in circuit")
        
        # Check for floating pins (components with very few connections)
        for ref_des, comp in self.components.items():
            expected_pins = self.get_expected_pin_count(comp.type, comp.package)
            actual_pins = comp.get_pin_count()
            if expected_pins > 0 and actual_pins < expected_pins / 2:
                errors.append(f"Component {ref_des} may have floating pins ({actual_pins}/{expected_pins} connected)")
        
        self.drc_errors = errors
        return len(errors) == 0, errors
    
    def get_expected_pin_count(self, comp_type: str, package: str) -> int:
        """Get expected pin count for component validation"""
        # Package-based pin counts
        package_pins = {
            'SOT23': 3, 'SOT223': 3, 'TO220': 3, 'TO92': 3, 'TO247': 3,
            'DIP8': 8, 'SOIC8': 8, 'TSSOP8': 8, 'MSOP8': 8,
            'MSOP-10': 10, 'DIP14': 14, 'SOIC14': 14,
            'DIP16': 16, 'SOIC16': 16, 'TSSOP16': 16,
            'TQFP32': 32, 'TQFP48': 48, 'TQFP64': 64,
            'LQFP100': 100, 'LQFP144': 144,
            '0402': 2, '0603': 2, '0805': 2, '1206': 2, '1210': 2,
            'HC49': 2,  # Crystal package
        }
        
        # Component type defaults
        type_pins = {
            'resistor': 2, 'capacitor': 2, 'inductor': 2,
            'diode': 2, 'led': 2, 'crystal': 2, 'fuse': 2,
            'transistor': 3, 'mosfet': 3, 'voltage_regulator': 3,
            'op_amp': 8, 'vga': 16, 'dds_ic': 10,
        }
        
        # Check package first
        for pkg_key in package_pins:
            if pkg_key in package.upper():
                return package_pins[pkg_key]
        
        # Then check type
        if comp_type in type_pins:
            return type_pins[comp_type]
        
        return 0  # Unknown
    
    def format_pin_name(self, comp: CircuitComponent, pin: str) -> str:
        """Format pin name based on component type"""
        comp_type = comp.type
        
        # Transistor pins
        if comp_type in ['transistor', 'mosfet']:
            pin_map = {
                '1': 'base', 'B': 'base', 'b': 'base',
                '2': 'collector', 'C': 'collector', 'c': 'collector',
                '3': 'emitter', 'E': 'emitter', 'e': 'emitter',
                'G': 'gate', 'g': 'gate',
                'D': 'drain', 'd': 'drain',
                'S': 'source', 's': 'source'
            }
            return pin_map.get(pin, f"pin {pin}")
        
        # Polarized capacitors
        elif comp_type == 'capacitor':
            if pin in ['1', '+', 'pos']:
                return 'positive'
            elif pin in ['2', '-', 'neg']:
                return 'negative'
            return f"pin {pin}"
        
        # Diodes and LEDs
        elif comp_type in ['diode', 'led']:
            if pin in ['1', 'A', 'a', '+']:
                return 'anode'
            elif pin in ['2', 'K', 'k', '-']:
                return 'cathode'
            return f"pin {pin}"
        
        # Connectors - descriptive pin names
        elif comp_type == 'connector':
            return f"pin {pin}"
        
        # ICs and other components
        else:
            return f"pin {pin}"
    
    def get_component_description(self, ref_des: str, include_pin: str = None) -> str:
        """Get formatted component description"""
        if ref_des not in self.components:
            # Check if it's a net name using GENERIC detection
            if ref_des in self.nets:
                if is_ground_rail(ref_des):
                    return f"{ref_des} (ground)"
                elif is_power_rail(ref_des):
                    return f"{ref_des} (power)"
                else:
                    return f"{ref_des} (signal)"
            return ref_des
        
        comp = self.components[ref_des]
        comp_type = comp.get_type_string()
        value = comp.value
        part = comp.get_suggested_part()
        
        # Build base description
        if part:
            desc = f"{ref_des} ({comp_type} \"{value}\" [{part}])"
        else:
            desc = f"{ref_des} ({comp_type} \"{value}\")"
        
        # Add pin if specified
        if include_pin:
            pin_name = self.format_pin_name(comp, include_pin)
            desc += f" {pin_name}"
        
        return desc
    
    def get_key_nets(self) -> List[str]:
        """
        Identify and return a prioritized list of key nets for explicit mention.
        This directly addresses the 'Structural Parity Warnings'.
        Prioritizes power/ground, then significant signal nets (input/output/sense),
        then other multi-connection signal nets.
        """
        key_nets = OrderedDict()

        # Pre-filter: Exclude nets explicitly marked as "No Connect" (e.g., ending with _NC or starting with NC_)
        all_nets = [net_name for net_name in self.nets.keys() 
                    if not net_name.upper().endswith('_NC') and not net_name.upper().startswith('NC_')]

        # 1. Power and Ground Nets (Highest Priority)
        for net_name in sorted(all_nets):
            if is_power_rail(net_name) or is_ground_rail(net_name):
                key_nets[net_name] = None

        # 2. Critical Signal Nets (Inputs, Outputs, Control, Sense)
        # These patterns are heuristic and can be expanded based on project needs
        critical_signal_patterns = [
            r'_IN$', r'_OUT$', r'_ENABLE$', r'_SELECT$', r'_CS$', r'_SENSE$',
            r'CLK$', r'DATA$', r'SYNC$', r'RESET$', r'IRQ$', r'PWM', r'ADC', r'DAC',
            r'^OSC', r'^BUFF', r'^AMP', r'^CH\d+', r'^VREF'
        ]
        for net_name in sorted(all_nets):
            if net_name not in key_nets and len(self.nets[net_name]) > 1: # Only include if it has more than one connection
                for pattern in critical_signal_patterns:
                    if re.search(pattern, net_name, re.IGNORECASE):
                        key_nets[net_name] = None
                        break
        
        # 3. All other multi-point signal nets, excluding _NC (No Connect)
        for net_name in sorted(all_nets):
            if net_name not in key_nets and len(self.nets[net_name]) > 1:
                key_nets[net_name] = None
        
        return list(key_nets.keys())

    def _append_net_instructions(self, output: List[str], net_name: str):
        """Helper to format instructions for a single net."""
        points = self.nets[net_name]
        if len(points) < 2:
            return
            
        output.append(f"\nNet: {net_name}")
        for i, point in enumerate(points):
            comp_desc = self.get_component_description(point['component'], point['pin'])
            output.append(f"  {i+1}. {comp_desc}")

    def generate_text_output(self) -> str:
        """Generate comprehensive human-readable wiring instructions"""
        output = []
        
        # Header
        output.append("=" * 80)
        output.append("CIRCUIT WIRING INSTRUCTIONS")
        output.append(f"Circuit: {self.module_name}")
        output.append(f"Type: {self.module_type}")
        output.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output.append("=" * 80)
        output.append("")
        
        # Run checks
        erc_ok, erc_errors = self.run_erc()
        drc_ok, drc_errors = self.run_drc()
        
        # Component List Section
        output.append("COMPONENT LIST")
        output.append("-" * 40)
        
        # Group components by type
        comp_by_type = defaultdict(list)
        for ref_des, comp in sorted(self.components.items()):
            comp_type = comp.get_type_string()
            comp_by_type[comp_type].append(comp)
        
        for comp_type in sorted(comp_by_type.keys()):
            output.append(f"\n{comp_type.upper()}S:")
            for comp in sorted(comp_by_type[comp_type], key=lambda x: x.ref_des):
                desc = f"  {comp.ref_des}: {comp.value}"
                if comp.get_suggested_part():
                    desc += f" (Part: {comp.get_suggested_part()})"
                if comp.power:
                    desc += f" [{comp.power}]"
                if comp.notes:
                    desc += f" - {comp.notes}"
                output.append(desc)
        
        # Validation Status
        output.append("")
        output.append("=" * 80)
        output.append("CIRCUIT VALIDATION")
        output.append("-" * 40)
        output.append(f"ERC Status: {'PASS ✓' if erc_ok else 'FAIL ✗'}")
        if not erc_ok:
            for error in erc_errors[:5]:  # Show first 5 errors
                output.append(f"  - {error}")
            if len(erc_errors) > 5:
                output.append(f"  ... and {len(erc_errors) - 5} more errors")
        
        output.append(f"DRC Status: {'PASS ✓' if drc_ok else 'FAIL ✗'}")
        if not drc_ok:
            for error in drc_errors[:5]:
                output.append(f"  - {error}")
            if len(drc_errors) > 5:
                output.append(f"  ... and {len(drc_errors) - 5} more errors")
        
        # Connection Instructions
        output.append("")
        output.append("=" * 80)
        output.append("CONNECTION INSTRUCTIONS (Tiered by Function)")
        output.append("-" * 40)
        output.append("Wire the circuit in the following priority order:")

        key_nets = self.get_key_nets()
        
        # TIER 1: POWER AND GROUND
        output.append("\nSTEP 1: POWER AND GROUND DISTRIBUTION")
        output.append("-" * 30)
        power_ground_found = False
        for net_name in key_nets:
            if is_power_rail(net_name) or is_ground_rail(net_name):
                self._append_net_instructions(output, net_name)
                power_ground_found = True
        if not power_ground_found:
            output.append("  (No dedicated power rails detected)")

        # TIER 2: PRIMARY SIGNAL PATH
        output.append("\nSTEP 2: PRIMARY SIGNAL PATH AND INTERFACES")
        output.append("-" * 30)
        # Signals identified as critical in get_key_nets
        signal_patterns = [r'_IN$', r'_OUT$', r'PWM', r'ADC', r'DAC', r'^AMP', r'^CH\d+']
        signals_found = False
        for net_name in key_nets:
            if is_power_rail(net_name) or is_ground_rail(net_name):
                continue
            if any(re.search(p, net_name, re.IGNORECASE) for p in signal_patterns):
                self._append_net_instructions(output, net_name)
                signals_found = True
        if not signals_found:
            output.append("  (No primary signal nets identified)")

        # TIER 3: AUXILIARY LOGIC AND CONTROL
        output.append("\nSTEP 3: AUXILIARY LOGIC AND CONTROL")
        output.append("-" * 30)
        aux_found = False
        for net_name in key_nets:
            if is_power_rail(net_name) or is_ground_rail(net_name):
                continue
            # Check if not already processed in T2
            if not any(re.search(p, net_name, re.IGNORECASE) for p in signal_patterns):
                self._append_net_instructions(output, net_name)
                aux_found = True
        if not aux_found:
            output.append("  (No auxiliary nets identified)")
        output.append("")
        
        # Step 1: Power Connections
        output.append("STEP 1: POWER AND GROUND CONNECTIONS")
        output.append("-" * 30)
        
        # Ground connections using GENERIC detection
        ground_connections = []
        for net_name in sorted(self.nets.keys()):
            if is_ground_rail(net_name):
                output.append(f"\n{net_name} Connections:")
                for point in self.nets[net_name]:
                    comp_ref = point['component']
                    pin = point['pin']
                    if comp_ref in self.components:
                        comp_desc = self.get_component_description(comp_ref, pin)
                        output.append(f"  {comp_desc} => {net_name} (ground)")

        # Power connections using GENERIC detection
        for net_name in sorted(self.nets.keys()):
            if is_power_rail(net_name) and not is_ground_rail(net_name):
                output.append(f"\n{net_name} Connections:")
                for point in self.nets[net_name]:
                    comp_ref = point['component']
                    pin = point['pin']
                    if comp_ref in self.components:
                        comp_desc = self.get_component_description(comp_ref, pin)
                        output.append(f"  {comp_desc} => {net_name} (power)")
        
        # Step 2: Signal Connections
        output.append("")
        output.append("STEP 2: SIGNAL CONNECTIONS")
        output.append("-" * 30)
        output.append("Connect components as follows (each line shows a direct connection):")
        output.append("")
        
        # Generate pairwise connections for all key signal nets
        seen_connections = set()
        connection_num = 1
        
        # Prioritize key nets
        key_signal_nets = [net for net in self.get_key_nets() if not is_power_rail(net) and not is_ground_rail(net)]
        other_nets = [net for net in sorted(self.nets.keys()) if net not in key_signal_nets and not is_power_rail(net) and not is_ground_rail(net)]
        
        nets_to_process = key_signal_nets + other_nets

        for net_name in nets_to_process:
            points = self.nets[net_name]
            if len(points) > 1:
                output.append(f"\nNet: {net_name}")
                for i in range(len(points)):
                    for j in range(i + 1, len(points)):
                        point1 = points[i]
                        point2 = points[j]
                        
                        comp1_ref = point1['component']
                        comp1_pin = point1['pin']
                        comp2_ref = point2['component']
                        comp2_pin = point2['pin']
                        
                        # Create connection key to avoid duplicates
                        conn_key = tuple(sorted([
                            f"{comp1_ref}:{comp1_pin}",
                            f"{comp2_ref}:{comp2_pin}"
                        ]))
                        
                        if conn_key not in seen_connections:
                            seen_connections.add(conn_key)
                            
                            if comp1_ref in self.components and comp2_ref in self.components:
                                desc1 = self.get_component_description(comp1_ref, comp1_pin)
                                desc2 = self.get_component_description(comp2_ref, comp2_pin)
                                output.append(f"  {connection_num:3d}. {desc1} => {desc2}")
                                connection_num += 1
        
        # Step 3: Verification Checklist
        output.append("")
        output.append("=" * 80)
        output.append("WIRING VERIFICATION CHECKLIST")
        output.append("-" * 40)
        output.append("Check each component has the correct number of connections:")
        output.append("")
        
        # Count actual connections per component
        for ref_des in sorted(self.components.keys()):
            comp = self.components[ref_des]
            pin_count = comp.get_pin_count()
            expected = self.get_expected_pin_count(comp.type, comp.package)
            
            if pin_count == 0:
                status = "✗ UNCONNECTED"
            elif expected > 0 and pin_count < expected:
                status = f"⚠ PARTIAL ({pin_count}/{expected})"
            else:
                status = f"✓ OK ({pin_count} pins)"
            
            comp_desc = f"{ref_des} ({comp.get_type_string()})"
            output.append(f"  [{status:^15}] {comp_desc}")
            
            # Show which pins are connected
            if pin_count > 0 and pin_count < 10:  # Don't show for large ICs
                connected_pins = sorted(comp.connections.keys())
                output.append(f"                   Connected pins: {', '.join(connected_pins)}")
        
        # Summary Section
        output.append("")
        output.append("=" * 80)
        output.append("SUMMARY")
        output.append("-" * 40)
        output.append(f"Total Components: {len(self.components)}")
        output.append(f"Total Nets: {len(self.nets)}")
        # Use GENERIC detection for power/ground counting
        output.append(f"Power/Ground Nets: {len([n for n in self.nets if is_power_rail(n) or is_ground_rail(n)])}")
        output.append(f"Signal Nets: {len([n for n in self.nets if not is_power_rail(n) and not is_ground_rail(n)])}")
        output.append(f"Total Connections: {len(seen_connections)}")
        
        # List any unconnected components
        unconnected = [ref for ref, comp in self.components.items() if comp.get_pin_count() == 0]
        if unconnected:
            output.append("")
            output.append(f"⚠ WARNING: Unconnected components: {', '.join(unconnected)}")
        
        output.append("")
        output.append("=" * 80)
        output.append("END OF WIRING INSTRUCTIONS")
        output.append("Double-check all connections before applying power!")
        output.append("=" * 80)
        
        return "\n".join(output)


def convert_circuit_to_text(json_path: Path, output_path: Path) -> bool:
    """Convert a single circuit JSON file to text documentation"""
    try:
        converter = SchematicsTextConverter()
        
        if not converter.load_circuit(json_path):
            logger.error(f"Failed to load {json_path}")
            return False
        
        # Generate text output
        text_output = converter.generate_text_output()
        
        # Write to file
        output_file = output_path / f"{json_path.stem}_wiring.txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(text_output)
        
        logger.info(f"Generated: {output_file}")
        
        # Report validation status
        erc_ok, _ = converter.run_erc()
        drc_ok, _ = converter.run_drc()
        if not erc_ok or not drc_ok:
            logger.warning(f"  Validation issues detected in {json_path.stem}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error converting {json_path}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main conversion process"""
    # Parse command line arguments
    if len(sys.argv) > 2:
        input_path = Path(sys.argv[1])
        output_path = Path(sys.argv[2])
    elif len(sys.argv) > 1:
        input_path = Path(sys.argv[1])
        output_path = input_path.parent / 'schematics_desc'
    else:
        # Find latest output folder
        output_dir = Path('output')
        if not output_dir.exists():
            logger.error("No output directory found")
            sys.exit(1)
        
        # Find latest project folder
        project_folders = [d for d in output_dir.iterdir() 
                          if d.is_dir() and d.name.startswith('202')]
        if not project_folders:
            logger.error("No project folders found")
            sys.exit(1)
        
        latest_folder = max(project_folders, key=lambda x: x.stat().st_mtime)
        input_path = latest_folder / 'lowlevel'
        output_path = latest_folder / 'schematics_desc'
    
    # Verify input path
    if not input_path.exists():
        logger.error(f"Input path does not exist: {input_path}")
        sys.exit(1)
    
    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("SCHEMATICS TEXT CONVERTER v2.0")
    logger.info("=" * 60)
    logger.info(f"Input:  {input_path}")
    logger.info(f"Output: {output_path}")
    logger.info("")
    
    # Find all circuit JSON files
    # Support both uppercase and lowercase circuit files
    circuit_files = list(input_path.glob('circuit_*.json'))
    if not circuit_files:
        circuit_files = list(input_path.glob('CIRCUIT_*.json'))

    if not circuit_files:
        logger.error("No circuit_*.json or CIRCUIT_*.json files found")
        sys.exit(1)
    
    logger.info(f"Found {len(circuit_files)} circuit files to convert")
    logger.info("-" * 60)
    
    # Process each file
    success_count = 0
    failed_files = []
    
    for circuit_file in sorted(circuit_files):
        logger.info(f"Processing: {circuit_file.name}")
        if convert_circuit_to_text(circuit_file, output_path):
            success_count += 1
        else:
            failed_files.append(circuit_file.name)
    
    # Summary
    logger.info("-" * 60)
    logger.info(f"Conversion complete: {success_count}/{len(circuit_files)} files converted")
    
    if failed_files:
        logger.error(f"Failed files: {', '.join(failed_files)}")
        sys.exit(1)
    else:
        logger.info("All files converted successfully!")
        logger.info(f"Output files are in: {output_path}")


if __name__ == "__main__":
    main()