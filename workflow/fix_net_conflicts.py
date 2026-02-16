# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Fix Net Conflicts & Transform Module - PRODUCTION v5.0 COMPLETE
Purpose: Fix circuit issues AND transform to converter-compatible format
Ported from N8N 'Fix Net Conflicts' node

Features:
  - Converts refDes -> ref
  - Adds pins array to all components
  - Fixes net conflicts
  - Fixes floating components
  - Ensures proper data structure
  - Rebuilds connections with points arrays
  - Final validation
"""

import json
import re
from typing import Dict, List, Set, Tuple, Any, Optional
from utils.logger import setup_logger

logger = setup_logger(__name__)


class CircuitFixer:
    """
    Complete port of N8N Fix Net Conflicts v5.0 logic
    This is the critical component that makes circuits work
    """

    @staticmethod
    def estimate_pin_count(component: Dict) -> int:
        """
        Estimate pin count based on component type and package
        """
        ref_des = component.get('refDes') or component.get('ref', '')
        comp_type = (component.get('type', '')).lower()
        package = (component.get('package', '')).upper()

        # Default pin count
        pin_count = 2

        # Check package for pin count hints
        if 'DIP' in package:
            match = re.search(r'DIP[- ]?(\d+)', package)
            if match:
                pin_count = int(match.group(1))
        elif 'SOIC' in package:
            match = re.search(r'SOIC[- ]?(\d+)', package)
            if match:
                pin_count = int(match.group(1))
        elif 'TSSOP' in package:
            match = re.search(r'TSSOP[- ]?(\d+)', package)
            if match:
                pin_count = int(match.group(1))
        elif 'QFP' in package:
            match = re.search(r'QFP[- ]?(\d+)', package)
            if match:
                pin_count = int(match.group(1))
        elif 'MSOP' in package:
            match = re.search(r'MSOP[- ]?(\d+)', package)
            if match:
                pin_count = int(match.group(1))
        elif 'TO-' in package:
            match = re.search(r'TO-(\d+)', package)
            if match:
                num = int(match.group(1))
                if num in [220, 247, 263, 252]:
                    pin_count = 3  # TO packages typically 3 pins
                elif num < 10:
                    pin_count = num

        # Component-specific defaults if package didn't give us info
        if not pin_count or pin_count == 2:
            if ref_des.startswith('U'):
                # ICs
                if 'microcontroller' in comp_type:
                    if 'stm32f4' in comp_type:
                        pin_count = 100
                    else:
                        pin_count = 28
                elif 'op' in comp_type or 'amp' in comp_type:
                    pin_count = 8
                elif '555' in comp_type:
                    pin_count = 8
                elif 'regulator' in comp_type:
                    pin_count = 3
                elif 'smps' in comp_type:
                    pin_count = 24
                elif 'pfc' in comp_type:
                    pin_count = 8
                elif 'boost' in comp_type:
                    pin_count = 10
                elif 'adc' in comp_type:
                    if 'ads8688' in comp_type:
                        pin_count = 38
                    else:
                        pin_count = 8
                elif 'dds' in comp_type:
                    pin_count = 20
                elif 'lan8720' in comp_type:
                    pin_count = 24
                elif 'usb3300' in comp_type:
                    pin_count = 32
                else:
                    pin_count = 8  # Default IC
            elif ref_des.startswith('Q'):
                pin_count = 3  # Transistors
            elif ref_des.startswith('D'):
                if 'bridge' in comp_type:
                    pin_count = 4
                elif 'dual' in comp_type or 'double' in comp_type:
                    pin_count = 3
                else:
                    pin_count = 2
            elif ref_des.startswith('BR'):
                pin_count = 4  # Bridge rectifier
            elif ref_des.startswith('T'):
                if 'transformer' in comp_type:
                    # Check for winding info in specs
                    specs_str = json.dumps(component.get('specs', {}))
                    if '10:1:1:2' in specs_str or 'multiple' in specs_str:
                        pin_count = 8
                    else:
                        pin_count = 6
                else:
                    pin_count = 3
            elif ref_des.startswith('J') or ref_des.startswith('P'):
                # Connectors - check specs
                specs = component.get('specs', {})
                if specs.get('pins'):
                    pins_str = str(specs['pins'])
                    match = re.search(r'\d+', pins_str)
                    if match:
                        pin_count = int(match.group(0))
                elif '10p' in comp_type or '10P' in package:
                    pin_count = 10
                elif 'bnc' in comp_type:
                    pin_count = 3
                elif 'rj45' in comp_type:
                    pin_count = 8
                else:
                    pin_count = 3  # Default connector
            elif ref_des.startswith('SW'):
                pin_count = 2  # Switch
            elif ref_des.startswith('F'):
                pin_count = 2  # Fuse
            elif ref_des.startswith('MOV') or ref_des.startswith('TVS'):
                pin_count = 2  # Varistor/TVS
            elif ref_des.startswith('Y') or ref_des.startswith('X'):
                if 'oscillator' in comp_type:
                    pin_count = 4
                else:
                    pin_count = 2  # Crystal

        return pin_count

    @staticmethod
    def generate_pins_array(component: Dict) -> List[Dict]:
        """
        Generate pins array for a component
        """
        ref_des = component.get('refDes') or component.get('ref', '')
        comp_type = (component.get('type', '')).lower()
        
        # Get pin count
        pin_count = CircuitFixer.estimate_pin_count(component)
        
        # Generate basic pins array
        pins = []
        for i in range(1, pin_count + 1):
            pins.append({
                'number': str(i),
                'type': 'passive',  # Default, will be overridden
                'name': f'PIN{i}'
            })
        
        # Set specific pin types based on component
        if ref_des.startswith('U'):
            if len(pins) >= 8:
                pins[0]['type'] = 'power'
                pins[0]['name'] = 'VCC'
                pins[-1]['type'] = 'power'
                pins[-1]['name'] = 'GND'
            elif len(pins) == 3:
                # Voltage regulator
                pins[0] = {'number': '1', 'type': 'power', 'name': 'VIN'}
                pins[1] = {'number': '2', 'type': 'output', 'name': 'VOUT'}
                pins[2] = {'number': '3', 'type': 'power', 'name': 'GND'}
        elif ref_des.startswith('Q'):
            if len(pins) == 3:
                pins[0] = {'number': '1', 'type': 'input', 'name': 'Gate'}
                pins[1] = {'number': '2', 'type': 'passive', 'name': 'Drain'}
                pins[2] = {'number': '3', 'type': 'passive', 'name': 'Source'}
        elif ref_des.startswith('D') and 'bridge' not in comp_type:
            if len(pins) == 2:
                pins[0] = {'number': '1', 'type': 'passive', 'name': 'Anode'}
                pins[1] = {'number': '2', 'type': 'passive', 'name': 'Cathode'}
        
        return pins


def fix_net_conflicts(circuit: Dict) -> Dict:
    """
    Main function to fix circuit issues and transform to converter-compatible format
    Complete port of N8N Fix Net Conflicts v5.0
    
    Args:
        circuit: Raw circuit from AI or previous step
        
    Returns:
        Fixed and transformed circuit ready for converters
    """
    logger.info(f"Processing circuit: {circuit.get('moduleName', 'Unknown')}")
    logger.info(f"Components: {len(circuit.get('components', []))}")
    
    # ============================================================================
    # PHASE 1: TRANSFORM COMPONENT STRUCTURE
    # ============================================================================
    logger.info("Phase 1: Transforming component structure...")
    
    if not circuit.get('components'):
        raise ValueError("Invalid circuit structure - missing components")
    
    transformed_components = []
    for comp in circuit['components']:
        transformed = {
            'ref': comp.get('ref') or comp.get('refDes'),  # Convert refDes to ref
            'type': comp.get('type'),
            'value': comp.get('value'),
            'specs': comp.get('specs', {}),
            'package': comp.get('package'),
            'notes': comp.get('notes'),
            'pins': comp.get('pins') or CircuitFixer.generate_pins_array(comp)  # Add pins if missing
        }
        
        # Ensure we have a ref
        if not transformed['ref']:
            raise ValueError(f"Component missing reference designator: {json.dumps(comp)}")
        
        transformed_components.append(transformed)
    
    circuit['components'] = transformed_components
    logger.info(f"  ✓ Transformed {len(circuit['components'])} components")
    
    # ============================================================================
    # PHASE 2: FIX PINNETMAPPING REFERENCES
    # ============================================================================
    logger.info("Phase 2: Fixing pinNetMapping references...")
    
    new_pin_net_mapping = {}
    for pin, net in (circuit.get('pinNetMapping', {})).items():
        # Check if pin uses old refDes format
        parts = pin.split('.')
        if len(parts) == 2:
            ref_des = parts[0]
            pin_num = parts[1]
            
            # Find the component
            comp = next((c for c in circuit['components'] 
                        if c['ref'] == ref_des or c.get('refDes') == ref_des), None)
            
            if comp:
                new_pin_net_mapping[f"{comp['ref']}.{pin_num}"] = net
            else:
                new_pin_net_mapping[pin] = net
        else:
            new_pin_net_mapping[pin] = net
    
    circuit['pinNetMapping'] = new_pin_net_mapping
    
    # ============================================================================
    # PHASE 3: FIX NET CONFLICTS
    # ============================================================================
    logger.info("Phase 3: Checking for net conflicts...")
    
    consolidated_pin_map = {}
    conflicts = 0
    
    for pin, net in circuit['pinNetMapping'].items():
        if pin in consolidated_pin_map and consolidated_pin_map[pin] != net:
            logger.warning(f"  Conflict at {pin}: {consolidated_pin_map[pin]} vs {net} - keeping first")
            conflicts += 1
        else:
            consolidated_pin_map[pin] = net
    
    circuit['pinNetMapping'] = consolidated_pin_map
    logger.info(f"  ✓ Resolved {conflicts} conflicts")
    
    # ============================================================================
    # PHASE 4: FIX FLOATING COMPONENTS
    # ============================================================================
    logger.info("Phase 4: Checking for floating components...")
    
    connected_components = set()
    for pin in circuit['pinNetMapping'].keys():
        connected_components.add(pin.split('.')[0])
    
    floating_fixed = 0
    for comp in circuit['components']:
        ref = comp['ref']
        comp_type = (comp.get('type', '')).lower()
        
        # Skip non-electrical components
        skip_types = ['heatsink', 'mounting', 'fiducial', 'mechanical']
        if any(t in comp_type for t in skip_types):
            continue
        
        if ref not in connected_components:
            logger.info(f"  Fixing floating component: {ref}")
            
            # Add basic connections based on component type
            if ref.startswith('R'):
                circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_1"
                circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_2"
            elif ref.startswith('C'):
                # Check if bypass cap
                value = (comp.get('value', '')).lower()
                if '100n' in value or '0.1u' in value or 'bypass' in value:
                    circuit['pinNetMapping'][f"{ref}.1"] = 'VCC'
                    circuit['pinNetMapping'][f"{ref}.2"] = 'GND'
                else:
                    circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_P"
                    circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_N"
            elif ref.startswith('L'):
                circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_IN"
                circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_OUT"
            elif ref.startswith('D'):
                circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_A"
                circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_K"
            elif ref.startswith('Q'):
                circuit['pinNetMapping'][f"{ref}.1"] = f"{ref}_GATE"
                circuit['pinNetMapping'][f"{ref}.2"] = f"{ref}_DRAIN"
                circuit['pinNetMapping'][f"{ref}.3"] = f"{ref}_SOURCE"
            elif ref.startswith('U'):
                # At minimum connect power pins
                pins = comp.get('pins', [])
                if pins:
                    circuit['pinNetMapping'][f"{ref}.1"] = 'VCC'
                    circuit['pinNetMapping'][f"{ref}.{len(pins)}"] = 'GND'
            else:
                # Generic connection
                circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}"
            
            floating_fixed += 1
    
    logger.info(f"  ✓ Fixed {floating_fixed} floating components")
    
    # ============================================================================
    # PHASE 5: REBUILD CONNECTIONS WITH POINTS ARRAYS
    # ============================================================================
    logger.info("Phase 5: Rebuilding connections with proper points arrays...")
    
    net_to_points = {}
    for pin, net in circuit['pinNetMapping'].items():
        if net not in net_to_points:
            net_to_points[net] = []
        net_to_points[net].append(pin)
    
    circuit['connections'] = []
    for net, points in net_to_points.items():
        if len(points) >= 2:
            circuit['connections'].append({
                'net': net,
                'points': sorted(points)  # CRITICAL: Must have points array!
            })
    
    # Update nets list
    circuit['nets'] = sorted(net_to_points.keys())
    
    logger.info(f"  ✓ Rebuilt {len(circuit['connections'])} connections")
    logger.info(f"  ✓ Total nets: {len(circuit['nets'])}")
    
    # ============================================================================
    # PHASE 6: FINAL VALIDATION
    # ============================================================================
    logger.info("Phase 6: Final validation...")
    
    issues = 0
    
    # Check for remaining floating components
    final_connected = set()
    for pin in circuit['pinNetMapping'].keys():
        final_connected.add(pin.split('.')[0])
    
    for comp in circuit['components']:
        if comp['ref'] not in final_connected:
            comp_type = (comp.get('type', '')).lower()
            if not any(t in comp_type for t in ['heatsink', 'mounting']):
                logger.warning(f"  WARNING: {comp['ref']} still floating")
                issues += 1
    
    # Check for single-ended nets
    for net, points in net_to_points.items():
        if len(points) == 1:
            pin = points[0]
            ref = pin.split('.')[0]
            
            # Check if it's a legitimate external connection
            if (not ref.startswith(('J', 'P')) and 
                'EXTERNAL' not in net and 'ENABLE' not in net):
                logger.warning(f"  WARNING: Single-ended net {net} at {pin}")
                issues += 1
    
    logger.info(f"  Total issues remaining: {issues}")
    
    # ============================================================================
    # FINAL OUTPUT
    # ============================================================================
    logger.info("=" * 60)
    logger.info("CIRCUIT TRANSFORMATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Module: {circuit.get('moduleName', 'Unknown')}")
    logger.info(f"Components: {len(circuit['components'])} (with pins arrays)")
    logger.info(f"Connections: {len(circuit['connections'])} (with points arrays)")
    logger.info(f"Nets: {len(circuit['nets'])}")
    logger.info(f"Issues: {issues}")
    
    return circuit


def validate_circuit(circuit: Dict) -> Dict:
    """
    Validate circuit for completeness and correctness
    
    Returns:
        Dict with 'valid' boolean and 'issues' list
    """
    issues = []
    
    # Check for components
    if not circuit.get('components'):
        issues.append("No components found")
    else:
        # Check component structure
        for comp in circuit['components']:
            if not comp.get('ref'):
                issues.append(f"Component missing 'ref' field: {comp.get('type', 'unknown')}")
            if not comp.get('pins'):
                issues.append(f"Component {comp.get('ref', 'unknown')} missing pins array")
    
    # Check for connections
    if not circuit.get('connections'):
        issues.append("No connections found")
    else:
        # Check connection structure
        for conn in circuit['connections']:
            if not conn.get('points'):
                issues.append(f"Connection {conn.get('net', 'unknown')} missing points array")
            elif len(conn['points']) < 2:
                issues.append(f"Connection {conn.get('net', 'unknown')} has less than 2 points")
    
    # Check for pinNetMapping
    if not circuit.get('pinNetMapping'):
        issues.append("No pinNetMapping found")
    
    # Check for floating components
    if circuit.get('pinNetMapping'):
        connected_refs = set(pin.split('.')[0] for pin in circuit['pinNetMapping'].keys())
        
        for comp in circuit.get('components', []):
            ref = comp.get('ref')
            comp_type = (comp.get('type', '')).lower()
            
            # Skip non-electrical
            if any(t in comp_type for t in ['heatsink', 'mounting', 'fiducial', 'mechanical']):
                continue
                
            if ref and ref not in connected_refs:
                issues.append(f"Component {ref} is floating (not connected)")
    
    return {
        'valid': len(issues) == 0,
        'issues': issues
    }
