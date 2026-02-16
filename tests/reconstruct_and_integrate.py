#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Reconstruct Module Circuits and Test Integration Fix - TC #95

This script:
1. Reconstructs module circuits from component_agent + connection_agent AI outputs
2. Runs the fixed integration agent
3. Validates the results for shorted passives and phantom components

Purpose: Complete end-to-end test of TC #95 integration fix.
"""

import sys
import json
import asyncio
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from workflow.agents.integration_agent import IntegrationAgent
from workflow.circuit_supervisor import supervise_circuit


def extract_json_from_response(text: str) -> Optional[dict]:
    """Extract JSON from AI response text."""
    # Try to find JSON in code blocks
    json_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
    matches = re.findall(json_pattern, text)

    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # Try raw JSON
    try:
        # Find the first { and last }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
    except json.JSONDecodeError:
        pass

    return None


def match_agent_files(ai_training_dir: Path) -> List[Tuple[str, Path, Path]]:
    """
    Match component_agent and connection_agent files by timestamp.

    Returns list of (module_name, component_file, connection_file) tuples.
    """
    matches = []

    # Get all component agent files
    component_files = sorted(ai_training_dir.glob("component_agent_*_response.txt"))

    # Build mapping of timestamp -> files
    for comp_file in component_files:
        # Extract timestamp from filename
        # Format: component_agent_20260205_143629_449_main_response.txt
        parts = comp_file.stem.split('_')
        if len(parts) >= 5:
            timestamp = '_'.join(parts[2:5])

            # Find matching connection file
            conn_pattern = f"connection_agent_*_{timestamp}_*_response.txt"
            conn_files = list(ai_training_dir.glob(conn_pattern))

            if conn_files:
                conn_file = conn_files[0]

                # Try to extract module name from the prompt
                prompt_file = str(comp_file).replace('_response.txt', '_prompt.txt')
                module_name = extract_module_name_from_prompt(Path(prompt_file))

                if module_name:
                    matches.append((module_name, comp_file, conn_file))

    return matches


def extract_module_name_from_prompt(prompt_file: Path) -> Optional[str]:
    """Extract module name from component agent prompt."""
    if not prompt_file.exists():
        return None

    text = prompt_file.read_text(errors='ignore')

    # Look for **Module Name**: pattern
    pattern = r'\*\*Module Name\*\*:\s*(.+?)[\n\r]'
    match = re.search(pattern, text)
    if match:
        name = match.group(1).strip()
        # Clean up the name
        name = name.replace(' ', '_').replace('-', '_')
        return name

    return None


def reconstruct_module(component_file: Path, connection_file: Path, module_name: str) -> Optional[dict]:
    """Reconstruct a module circuit from component and connection agent outputs."""

    print(f"\n   Reconstructing: {module_name}")

    # Load component data
    comp_text = component_file.read_text(errors='ignore')
    comp_data = extract_json_from_response(comp_text)

    if not comp_data or 'components' not in comp_data:
        print(f"     ❌ Failed to extract components")
        return None

    components = comp_data['components']
    print(f"     Components: {len(components)}")

    # Load connection data
    conn_text = connection_file.read_text(errors='ignore')
    conn_data = extract_json_from_response(conn_text)

    if not conn_data or 'pinNetMapping' not in conn_data:
        print(f"     ❌ Failed to extract connections")
        return None

    pin_net_mapping = conn_data['pinNetMapping']
    print(f"     Pin mappings: {len(pin_net_mapping)}")

    # Build connections from pinNetMapping
    net_to_pins = {}
    for pin, net in pin_net_mapping.items():
        if net not in net_to_pins:
            net_to_pins[net] = []
        net_to_pins[net].append(pin)

    connections = [
        {'net': net, 'points': sorted(pins)}
        for net, pins in net_to_pins.items()
    ]

    nets = sorted(net_to_pins.keys())
    print(f"     Connections: {len(connections)}, Nets: {len(nets)}")

    return {
        'module_name': module_name,
        'components': components,
        'connections': connections,
        'pinNetMapping': pin_net_mapping,
        'nets': nets
    }


def check_shorted_passives(circuit: dict) -> list:
    """Check for shorted passive components (LAW 4 violations)."""
    shorted = []
    passive_types = {'resistor', 'capacitor', 'inductor'}

    components = circuit.get('components', [])

    # Build pin_to_net from connections
    pin_to_net = {}
    for conn in circuit.get('connections', []):
        net = conn.get('net')
        for point in conn.get('points', []):
            pin_to_net[point] = net

    # Check each passive
    for comp in components:
        ref = comp.get('ref', comp.get('reference', ''))
        comp_type = comp.get('type', '').lower()

        if comp_type in passive_types:
            pin1 = f"{ref}.1"
            pin2 = f"{ref}.2"
            net1 = pin_to_net.get(pin1)
            net2 = pin_to_net.get(pin2)

            if net1 and net2 and net1 == net2:
                shorted.append({
                    'ref': ref,
                    'type': comp_type,
                    'net': net1
                })

    return shorted


def check_phantom_components(circuit: dict) -> list:
    """Check for phantom component references."""
    phantoms = []

    # Get all component references
    components = circuit.get('components', [])
    comp_refs = set()
    for comp in components:
        ref = comp.get('ref', comp.get('reference', ''))
        comp_refs.add(ref)

    # Check connections for references to non-existent components
    for conn in circuit.get('connections', []):
        for point in conn.get('points', []):
            # Extract component ref from pin ref (e.g., "R1.1" -> "R1")
            if '.' in point:
                comp_ref = point.rsplit('.', 1)[0]
                if comp_ref not in comp_refs:
                    phantoms.append({
                        'pin_ref': point,
                        'expected_component': comp_ref
                    })

    return phantoms


def build_interfaces(modules: list) -> dict:
    """Build interface contracts for modules."""
    interfaces = {}

    for mod in modules:
        module_name = mod['module_name']
        is_power_supply = 'power' in module_name.lower() and 'supply' in module_name.lower()

        interfaces[module_name] = {
            'power_in': [] if is_power_supply else ['VCC', 'GND'],
            'power_out': ['VCC', 'GND'] if is_power_supply else [],
            'inputs': {},
            'outputs': {}
        }

    return interfaces


async def run_reconstruction_and_integration(run_id: str):
    """Main reconstruction and integration test."""

    print("=" * 80)
    print("TC #95 INTEGRATION FIX - FULL RECONSTRUCTION TEST")
    print("=" * 80)

    ai_training_dir = project_root / "logs" / "runs" / run_id / "ai_training"
    output_dir = project_root / "output" / run_id / "lowlevel"

    if not ai_training_dir.exists():
        print(f"\n❌ AI training directory not found: {ai_training_dir}")
        return False

    # Step 1: Match agent files
    print("\n1. Matching component and connection agent files...")
    matches = match_agent_files(ai_training_dir)
    print(f"   Found {len(matches)} module pairs")

    if not matches:
        print("\n❌ No matching agent files found")
        return False

    # Step 2: Reconstruct modules
    print("\n2. Reconstructing modules from AI outputs...")
    modules = []
    for module_name, comp_file, conn_file in matches:
        module = reconstruct_module(comp_file, conn_file, module_name)
        if module:
            modules.append(module)

    print(f"\n   Reconstructed {len(modules)} modules:")
    for mod in modules:
        print(f"     - {mod['module_name']}: {len(mod['components'])} components")

    # Step 3: Build interfaces
    print("\n3. Building interface contracts...")
    interfaces = build_interfaces(modules)

    # Step 4: Test prefix generation (verify fix works)
    print("\n4. Testing prefix generation (TC #95 fix)...")
    agent = IntegrationAgent(None)

    all_prefixes_valid = True
    for mod in modules:
        name = mod['module_name']
        prefix = agent._create_module_prefix(name)
        has_period = '.' in prefix
        status = '❌ FAIL' if has_period else '✅ PASS'
        if has_period:
            all_prefixes_valid = False
        print(f"   {status}: {name:40} -> {prefix}")

    if not all_prefixes_valid:
        print("\n   ❌ Prefix fix not working correctly!")
        return False

    print("\n   ✅ All prefixes valid (no periods)")

    # Step 5: Run integration
    print("\n5. Running integration agent...")
    integrated = await agent.integrate_modules(modules, interfaces)

    print(f"\n   Integration complete:")
    print(f"     - Components: {len(integrated.get('components', []))}")
    print(f"     - Connections: {len(integrated.get('connections', []))}")
    print(f"     - Nets: {len(integrated.get('nets', []))}")

    # Step 6: Validate results
    print("\n6. Validating integrated circuit...")

    # Check shorted passives
    shorted = check_shorted_passives(integrated)
    shorted_by_prefix = {}
    for s in shorted:
        prefix = s['ref'].split('_')[0] if '_' in s['ref'] else 'NONE'
        if prefix not in shorted_by_prefix:
            shorted_by_prefix[prefix] = []
        shorted_by_prefix[prefix].append(s)

    if shorted:
        print(f"\n   ⚠️  Found {len(shorted)} shorted passive(s):")
        for prefix, items in sorted(shorted_by_prefix.items()):
            print(f"     [{prefix}]: {len(items)} shorted")
            for s in items[:3]:
                print(f"       - {s['ref']} ({s['type']}): both pins on {s['net']}")
            if len(items) > 3:
                print(f"       ... and {len(items) - 3} more")
    else:
        print(f"\n   ✅ No shorted passives (LAW 4 validated)")

    # Check phantom components
    phantoms = check_phantom_components(integrated)
    if phantoms:
        phantom_comps = set(p['expected_component'] for p in phantoms)
        print(f"\n   ❌ Found {len(phantom_comps)} phantom component(s):")
        for comp in list(phantom_comps)[:5]:
            refs = [p['pin_ref'] for p in phantoms if p['expected_component'] == comp]
            print(f"     - {comp}: {len(refs)} references")
    else:
        print(f"\n   ✅ No phantom components")

    # Step 7: Save results
    print("\n7. Saving results...")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save individual modules
    for mod in modules:
        safe_name = mod['module_name'].lower().replace(' ', '_').replace('-', '_')
        module_file = output_dir / f"circuit_{safe_name}.json"
        circuit = {
            'circuit': {
                'components': mod['components'],
                'connections': mod['connections'],
                'pinNetMapping': mod['pinNetMapping'],
                'nets': mod['nets']
            }
        }
        with open(module_file, 'w') as f:
            json.dump(circuit, f, indent=2)
        print(f"   Saved: {module_file.name}")

    # Save integrated circuit
    integrated_file = output_dir / "circuit_integrated_circuit.json"
    with open(integrated_file, 'w') as f:
        json.dump({'circuit': integrated}, f, indent=2)
    print(f"   Saved: {integrated_file.name}")

    # Generate design.json
    design = {
        'systemOverview': {
            'name': 'Dual-Channel Ultrasonic Transducer Driver',
            'description': f'Complete system with {len(modules)} modules',
            'timestamp': run_id,
            'statistics': {
                'totalModules': len(modules),
                'totalComponents': len(integrated.get('components', [])),
                'totalConnections': len(integrated.get('connections', [])),
                'totalUniqueNets': len(integrated.get('nets', []))
            }
        },
        'modules': [m['module_name'] for m in modules],
        'validationStatus': {
            'shortedPassives': len(shorted),
            'phantomComponents': len(set(p['expected_component'] for p in phantoms)) if phantoms else 0,
            'status': 'pass' if len(shorted) == 0 and len(phantoms) == 0 else 'issues'
        }
    }
    design_file = output_dir / "design.json"
    with open(design_file, 'w') as f:
        json.dump(design, f, indent=2)
    print(f"   Saved: {design_file.name}")

    # Summary
    print("\n" + "=" * 80)
    print("FINAL SUMMARY")
    print("=" * 80)

    # Count integration-caused shorted passives (those with prefixes containing module markers)
    integration_shorted = [s for s in shorted if 'CHA_2' in s['ref'] or 'CHA_1' in s['ref']]
    ai_shorted = [s for s in shorted if s not in integration_shorted]

    print(f"\n   Total shorted passives: {len(shorted)}")
    print(f"     - From integration bug (should be 0 now): {len(integration_shorted)}")
    print(f"     - From AI generation: {len(ai_shorted)}")

    if len(integration_shorted) == 0:
        print("\n   ✅ TC #95 FIX VERIFIED - No integration-caused shorted passives!")
    else:
        print(f"\n   ❌ TC #95 FIX INCOMPLETE - {len(integration_shorted)} integration-caused shorted passives")

    print("\n" + "=" * 80)

    return len(integration_shorted) == 0 and len(phantoms) == 0


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Reconstruct and test TC #95 fix")
    parser.add_argument("--run-id", default="20260205-143152-4109c520",
                        help="Run ID to test")
    args = parser.parse_args()

    success = asyncio.run(run_reconstruction_and_integration(args.run_id))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
