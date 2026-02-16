# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Circuit Post-Processor
Fixes common issues in AI-generated circuits before validation
"""

import json
from typing import Dict, List, Any
from pathlib import Path
import logging

from server.config import config

logger = logging.getLogger(__name__)

def get_pins_for_component(component: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generate appropriate pins array based on component type and package
    """
    comp_type = component.get('type', '').upper()
    package = component.get('package', '').upper()
    value = component.get('value', '')

    # Resistors and Capacitors (2-pin passives)
    if comp_type in ['RESISTOR', 'CAPACITOR', 'INDUCTOR']:
        return [
            {"number": "1", "name": "1", "type": "passive"},
            {"number": "2", "name": "2", "type": "passive"}
        ]

    # Diodes
    elif comp_type == 'DIODE':
        return [
            {"number": "1", "name": "A", "type": "passive"},  # Anode
            {"number": "2", "name": "K", "type": "passive"}   # Kathode
        ]

    # MOSFETs
    elif comp_type in ['MOSFET', 'NMOS', 'PMOS', 'MOSFET_N', 'MOSFET_P']:
        if 'TO-220' in package or 'TO-247' in package:
            return [
                {"number": "1", "name": "G", "type": "input"},    # Gate
                {"number": "2", "name": "D", "type": "passive"},  # Drain
                {"number": "3", "name": "S", "type": "passive"}   # Source
            ]
        elif 'SOT-23' in package:
            return [
                {"number": "1", "name": "G", "type": "input"},
                {"number": "2", "name": "S", "type": "passive"},
                {"number": "3", "name": "D", "type": "passive"}
            ]
        else:
            # Generic 3-pin MOSFET
            return [
                {"number": "1", "name": "G", "type": "input"},
                {"number": "2", "name": "D", "type": "passive"},
                {"number": "3", "name": "S", "type": "passive"}
            ]

    # BJT Transistors
    elif comp_type in ['TRANSISTOR', 'NPN', 'PNP', 'BJT']:
        if 'TO-220' in package:
            return [
                {"number": "1", "name": "B", "type": "input"},    # Base
                {"number": "2", "name": "C", "type": "passive"},  # Collector
                {"number": "3", "name": "E", "type": "passive"}   # Emitter
            ]
        else:
            return [
                {"number": "1", "name": "B", "type": "input"},
                {"number": "2", "name": "C", "type": "passive"},
                {"number": "3", "name": "E", "type": "passive"}
            ]

    # ICs - determine by package
    elif comp_type == 'IC' or 'U' in component.get('ref', component.get('refDes', '')):
        if 'DIP-8' in package or 'SOIC-8' in package or 'SO-8' in package:
            return [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(8)
            ]
        elif 'DIP-14' in package or 'SOIC-14' in package:
            return [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(14)
            ]
        elif 'DIP-16' in package or 'SOIC-16' in package:
            return [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(16)
            ]
        elif 'LQFP-48' in package or 'QFP-48' in package:
            return [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(48)
            ]
        elif 'LQFP-64' in package:
            return [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(64)
            ]
        elif 'LQFP-100' in package:
            return [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(100)
            ]
        else:
            # Default to 8-pin IC if package not recognized
            return [
                {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
                for i in range(8)
            ]

    # Connectors
    elif comp_type == 'CONNECTOR' or 'J' in component.get('ref', component.get('refDes', '')):
        # Try to extract pin count from package or value
        pin_count = 2  # Default
        if 'PIN' in package:
            try:
                pin_count = int(package.split('PIN')[0].split('-')[-1])
            except:
                pass

        return [
            {"number": str(i+1), "name": f"PIN{i+1}", "type": "passive"}
            for i in range(pin_count)
        ]

    # Test points
    elif comp_type == 'TEST_POINT' or 'TP' in component.get('ref', component.get('refDes', '')):
        return [
            {"number": "1", "name": "TP", "type": "passive"}
        ]

    # Fuses
    elif comp_type == 'FUSE' or 'F' in component.get('ref', component.get('refDes', '')):
        return [
            {"number": "1", "name": "1", "type": "passive"},
            {"number": "2", "name": "2", "type": "passive"}
        ]

    # Transformers
    elif comp_type == 'TRANSFORMER':
        return [
            {"number": "1", "name": "PRI+", "type": "passive"},
            {"number": "2", "name": "PRI-", "type": "passive"},
            {"number": "3", "name": "SEC+", "type": "passive"},
            {"number": "4", "name": "SEC-", "type": "passive"}
        ]

    # Crystal/Oscillator
    elif comp_type in ['CRYSTAL', 'OSCILLATOR']:
        return [
            {"number": "1", "name": "1", "type": "passive"},
            {"number": "2", "name": "2", "type": "passive"}
        ]

    # LEDs
    elif comp_type == 'LED':
        return [
            {"number": "1", "name": "A", "type": "passive"},  # Anode
            {"number": "2", "name": "K", "type": "passive"}   # Kathode
        ]

    # Potentiometers
    elif comp_type == 'POTENTIOMETER':
        return [
            {"number": "1", "name": "1", "type": "passive"},  # End 1
            {"number": "2", "name": "W", "type": "passive"},  # Wiper
            {"number": "3", "name": "2", "type": "passive"}   # End 2
        ]

    # Switches
    elif comp_type == 'SWITCH':
        if 'DPDT' in package:
            # Double Pole Double Throw
            return [
                {"number": "1", "name": "1A", "type": "passive"},
                {"number": "2", "name": "1B", "type": "passive"},
                {"number": "3", "name": "1COM", "type": "passive"},
                {"number": "4", "name": "2A", "type": "passive"},
                {"number": "5", "name": "2B", "type": "passive"},
                {"number": "6", "name": "2COM", "type": "passive"}
            ]
        else:
            # Simple SPST
            return [
                {"number": "1", "name": "1", "type": "passive"},
                {"number": "2", "name": "2", "type": "passive"}
            ]

    # Default: 2-pin passive
    else:
        logger.warning(f"Unknown component type: {comp_type}, package: {package}. Using default 2-pin.")
        return [
            {"number": "1", "name": "1", "type": "passive"},
            {"number": "2", "name": "2", "type": "passive"}
        ]


def _enforce_law4_different_nets(circuit_data: Dict[str, Any]) -> int:
    """
    V.2 FIX: Deterministic enforcement of LAW 4 — two-terminal passives must
    bridge different nets. If both pins of a 2-pin passive are on the same net,
    move pin 2 to a new net named '{original_net}_B'.

    Uses config.TWO_PIN_PASSIVE_TYPES and config.TWO_PIN_PASSIVE_PREFIXES as
    single source of truth for which component types are two-pin passives.

    This is a STRUCTURAL safety net — it catches LAW 4 violations that the AI
    generated, regardless of component type. The AI may still produce better
    wiring, but this ensures no shorted passive ever reaches the supervisor.

    Args:
        circuit_data: The circuit dict (components, connections, pinNetMapping, nets)

    Returns:
        Number of LAW 4 violations auto-fixed
    """
    pin_net_mapping = circuit_data.get('pinNetMapping', {})
    connections = circuit_data.get('connections', [])
    nets = circuit_data.get('nets', [])
    components = circuit_data.get('components', [])

    if not pin_net_mapping or not components:
        return 0

    fix_count = 0

    for comp in components:
        ref = comp.get('ref', '')
        comp_type = (comp.get('type', '') or '').lower()
        pins = comp.get('pins', [])

        # Only check 2-pin components
        if len(pins) != 2:
            continue

        # Check if this component is a two-pin passive via type or ref prefix
        is_two_pin_passive = (
            comp_type in config.TWO_PIN_PASSIVE_TYPES
            or any(ref.upper().startswith(p) for p in config.TWO_PIN_PASSIVE_PREFIXES)
        )

        if not is_two_pin_passive:
            continue

        # Get pin references — use pin number from pins array
        pin1_num = pins[0].get('number', '1') if isinstance(pins[0], dict) else str(pins[0])
        pin2_num = pins[1].get('number', '2') if isinstance(pins[1], dict) else str(pins[1])
        pin1_ref = f"{ref}.{pin1_num}"
        pin2_ref = f"{ref}.{pin2_num}"

        net1 = pin_net_mapping.get(pin1_ref)
        net2 = pin_net_mapping.get(pin2_ref)

        if not net1 or not net2:
            continue

        # LAW 4 CHECK: both pins on same net = shorted passive
        if net1 == net2:
            # Create a new net for pin 2
            new_net = f"{net1}_B"

            # Ensure the new net name is unique (avoid collisions)
            existing_nets = set(pin_net_mapping.values())
            suffix_idx = 2
            while new_net in existing_nets:
                new_net = f"{net1}_B{suffix_idx}"
                suffix_idx += 1

            # Update pinNetMapping
            pin_net_mapping[pin2_ref] = new_net

            # Update connections: remove pin2 from old net, add to new net
            for conn in connections:
                if conn.get('net') == net1 and pin2_ref in conn.get('points', []):
                    conn['points'].remove(pin2_ref)

            # Add new connection entry for the new net
            connections.append({
                'net': new_net,
                'points': [pin2_ref]
            })

            # Add new net to nets list
            if new_net not in nets:
                nets.append(new_net)

            fix_count += 1
            logger.warning(
                f"LAW 4 auto-fix: {ref} ({comp_type}) had both pins on "
                f"'{net1}', moved {pin2_ref} to '{new_net}'"
            )

    return fix_count


def _remove_design_artifacts(circuit_data: Dict[str, Any]) -> int:
    """
    X.2 FIX: Remove AI design iteration artifacts from circuit data.

    AI models sometimes leave thinking artifacts as real components during
    iterative design (e.g., Q1_REPLACED, R3_OLD, U2_BACKUP). These are NOT
    real components and must be removed before validation.

    Detection is config-driven via:
    - config.DESIGN_ARTIFACT_REF_SUFFIXES: ref suffixes like _REPLACED, _OLD
    - config.DESIGN_ARTIFACT_VALUE_KEYWORDS: value keywords like 'removed', 'dnp'

    GENERIC: Works for ANY component type and ANY circuit topology.

    Args:
        circuit_data: The circuit dict (components, connections, pinNetMapping, nets)

    Returns:
        Number of artifact components removed
    """
    components = circuit_data.get('components', [])
    pin_net_mapping = circuit_data.get('pinNetMapping', {})
    connections = circuit_data.get('connections', [])

    if not components:
        return 0

    artifact_refs = set()

    for comp in components:
        ref = comp.get('ref', '')
        if not ref:
            continue

        is_artifact = False

        # Check 1: Ref suffix detection (Q1_REPLACED → suffix "REPLACED")
        if '_' in ref:
            _, suffix = ref.rsplit('_', 1)
            if suffix.upper() in config.DESIGN_ARTIFACT_REF_SUFFIXES:
                is_artifact = True

        # Check 2: Value/name keyword detection (value = "removed", "DNP")
        if not is_artifact:
            value = (comp.get('value', '') or '').lower()
            name = (comp.get('name', '') or '').lower()
            combined = f"{value} {name}"
            for keyword in config.DESIGN_ARTIFACT_VALUE_KEYWORDS:
                if keyword in combined:
                    is_artifact = True
                    break

        if is_artifact:
            artifact_refs.add(ref)

    if not artifact_refs:
        return 0

    # Remove artifact components from the components list
    circuit_data['components'] = [
        c for c in components if c.get('ref', '') not in artifact_refs
    ]

    # Remove artifact pin mappings
    pins_to_remove = [
        pin for pin in pin_net_mapping
        if any(pin.startswith(f"{ref}.") for ref in artifact_refs)
    ]
    for pin in pins_to_remove:
        del pin_net_mapping[pin]

    # Remove artifact pins from connections
    for conn in connections:
        points = conn.get('points', [])
        conn['points'] = [
            p for p in points
            if not any(p.startswith(f"{ref}.") for ref in artifact_refs)
        ]

    # Remove empty connections (all points were artifacts)
    circuit_data['connections'] = [
        c for c in connections if c.get('points', [])
    ]

    for ref in sorted(artifact_refs):
        logger.warning(f"X.2: Removed design artifact component: {ref}")

    return len(artifact_refs)


def fix_circuit_format(circuit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fix common format issues in AI-generated circuits

    Fixes:
    1. refDes -> ref conversion
    2. Add missing pins arrays
    3. Ensure proper structure
    4. LAW 4 enforcement (V.2): two-terminal passives must bridge different nets
    """

    if 'circuit' in circuit:
        circuit_data = circuit['circuit']
    else:
        circuit_data = circuit

    fixed_count = 0

    # Fix components
    if 'components' in circuit_data:
        for component in circuit_data['components']:
            # Fix refDes -> ref
            if 'refDes' in component and 'ref' not in component:
                component['ref'] = component['refDes']
                del component['refDes']
                fixed_count += 1
                logger.debug(f"Fixed refDes->ref for {component['ref']}")

            # Add missing pins array
            if 'pins' not in component or not component.get('pins'):
                component['pins'] = get_pins_for_component(component)
                fixed_count += 1
                logger.debug(f"Added pins array for {component.get('ref', 'unknown')}")

            # Ensure required fields
            if 'type' not in component:
                # Try to infer type from ref
                ref = component.get('ref', '')
                if ref.startswith('R'):
                    component['type'] = 'resistor'
                elif ref.startswith('C'):
                    component['type'] = 'capacitor'
                elif ref.startswith('L'):
                    component['type'] = 'inductor'
                elif ref.startswith('D'):
                    component['type'] = 'diode'
                elif ref.startswith('Q'):
                    component['type'] = 'transistor'
                elif ref.startswith('U'):
                    component['type'] = 'ic'
                elif ref.startswith('J'):
                    component['type'] = 'connector'
                elif ref.startswith('F'):
                    component['type'] = 'fuse'
                elif ref.startswith('TP'):
                    component['type'] = 'test_point'
                else:
                    component['type'] = 'unknown'
                fixed_count += 1

    # X.2 FIX: Remove design iteration artifacts BEFORE validation.
    # Must run BEFORE LAW 4 enforcement (artifacts may have shorted pins).
    artifact_count = _remove_design_artifacts(circuit_data)
    if artifact_count > 0:
        logger.warning(f"Artifact cleanup: removed {artifact_count} design iteration artifact(s)")
        fixed_count += artifact_count

    # V.2 FIX: Enforce LAW 4 — two-terminal passives must bridge different nets.
    # This MUST run AFTER pin arrays are added (so we know pin count) but
    # BEFORE validation. Acts as a deterministic safety net.
    law4_fixes = _enforce_law4_different_nets(circuit_data)
    if law4_fixes > 0:
        logger.warning(f"LAW 4 enforcement: auto-fixed {law4_fixes} shorted passive(s)")
        fixed_count += law4_fixes

    logger.info(f"Fixed {fixed_count} issues in circuit")

    # Ensure circuit is wrapped in 'circuit' key
    if 'circuit' not in circuit:
        circuit = {'circuit': circuit_data}

    return circuit


def process_lowlevel_circuits(output_dir: Path) -> int:
    """
    Process all circuits in lowlevel folder and fix issues

    Returns:
        Number of circuits fixed
    """
    lowlevel_dir = output_dir / 'lowlevel'

    if not lowlevel_dir.exists():
        logger.error(f"Lowlevel directory not found: {lowlevel_dir}")
        return 0

    circuits_fixed = 0

    for circuit_file in lowlevel_dir.glob('circuit_*.json'):
        logger.info(f"Processing {circuit_file.name}")

        try:
            # Load circuit
            with open(circuit_file, 'r') as f:
                circuit = json.load(f)

            # Fix format issues
            fixed_circuit = fix_circuit_format(circuit)

            # Save back
            with open(circuit_file, 'w') as f:
                json.dump(fixed_circuit, f, indent=2)

            circuits_fixed += 1
            logger.info(f"Fixed and saved {circuit_file.name}")

        except Exception as e:
            logger.error(f"Error processing {circuit_file.name}: {e}")

    return circuits_fixed


if __name__ == "__main__":
    # Test with latest output
    import sys

    if len(sys.argv) > 1:
        output_dir = Path(sys.argv[1])
    else:
        # Find latest output
        output_base = Path(__file__).parent.parent / 'output'
        latest = sorted(output_base.glob('*'))[-1] if output_base.exists() else None
        if not latest:
            print("No output directory found")
            sys.exit(1)
        output_dir = latest

    print(f"Processing circuits in: {output_dir}")

    # Set up logging
    logging.basicConfig(level=logging.INFO)

    # Process circuits
    fixed = process_lowlevel_circuits(output_dir)
    print(f"Fixed {fixed} circuits")