#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Simulate Integration Fix - TC #95

This script tests the integration agent fix by:
1. Loading the original module circuit files (from backup)
2. Running the fixed integration agent
3. Validating the results

Purpose: Verify that the prefix sanitization fix resolves the shorted passives issue.
"""

import sys
import json
import asyncio
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from workflow.agents.integration_agent import IntegrationAgent
from workflow.circuit_supervisor import supervise_circuit


def load_module_circuits(backup_dir: Path) -> list:
    """Load module circuits from backup directory."""
    modules = []

    # Map backup files to module names
    file_mapping = {
        'circuit_main_power_supply.json': 'Main_Power_Supply',
        'circuit_main_controller_and_interface.json': 'Main_Controller_and_Interface',
        'circuit_channel_1_module_50khz.json': 'Channel_1_Module_50kHz',
        'circuit_channel_2_module_1.5mhz.json': 'Channel_2_Module_1.5MHz',
        'circuit_protection_and_monitoring.json': 'Protection_and_Monitoring',
        'circuit_front_panel_interface.json': 'Front_Panel_Interface',
        'circuit_backplane_and_interconnect.json': 'Backplane_and_Interconnect',
    }

    for filename, module_name in file_mapping.items():
        filepath = backup_dir / filename
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)

            # Extract circuit from wrapper if present
            circuit = data.get('circuit', data)

            modules.append({
                'module_name': module_name,
                'components': circuit.get('components', []),
                'connections': circuit.get('connections', []),
                'pinNetMapping': circuit.get('pinNetMapping', {}),
                'nets': circuit.get('nets', [])
            })
            print(f"  Loaded: {module_name} ({len(circuit.get('components', []))} components)")
        else:
            print(f"  Warning: {filename} not found")

    return modules


def build_interfaces(modules: list) -> dict:
    """Build interface contracts for modules."""
    interfaces = {}

    for mod in modules:
        module_name = mod['module_name']
        interfaces[module_name] = {
            'power_in': ['VCC', 'GND'] if module_name != 'Main_Power_Supply' else [],
            'power_out': ['VCC', 'GND'] if module_name == 'Main_Power_Supply' else [],
            'inputs': {},
            'outputs': {}
        }

    return interfaces


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


async def run_integration_test(run_id: str):
    """Run the integration test."""

    print("=" * 80)
    print("TC #95 INTEGRATION FIX SIMULATION")
    print("=" * 80)

    # Paths
    backup_dir = project_root / "output" / run_id / "lowlevel" / "backup"
    output_dir = project_root / "output" / run_id / "lowlevel"

    if not backup_dir.exists():
        print(f"\n❌ Backup directory not found: {backup_dir}")
        return False

    # Step 1: Load module circuits
    print("\n1. Loading module circuits from backup...")
    modules = load_module_circuits(backup_dir)
    print(f"   Loaded {len(modules)} modules")

    # Step 2: Build interfaces
    print("\n2. Building interface contracts...")
    interfaces = build_interfaces(modules)
    print(f"   Built {len(interfaces)} interface contracts")

    # Step 3: Run integration with fixed code
    print("\n3. Running integration agent (with TC #95 fix)...")
    agent = IntegrationAgent(None)

    # Test prefix generation first
    print("\n   Prefix generation test:")
    for mod in modules:
        name = mod['module_name']
        prefix = agent._create_module_prefix(name)
        has_period = '.' in prefix
        status = '❌ FAIL' if has_period else '✅ PASS'
        print(f"     {status}: {name:40} -> {prefix}")

    # Run integration
    print("\n   Running integration...")
    integrated = await agent.integrate_modules(modules, interfaces)

    print(f"\n   Integration complete:")
    print(f"     - Components: {len(integrated.get('components', []))}")
    print(f"     - Connections: {len(integrated.get('connections', []))}")
    print(f"     - Nets: {len(integrated.get('nets', []))}")

    # Step 4: Validate results
    print("\n4. Validating integrated circuit...")

    # Check shorted passives
    shorted = check_shorted_passives(integrated)
    if shorted:
        print(f"\n   ❌ Found {len(shorted)} shorted passive(s):")
        for s in shorted[:10]:
            print(f"      - {s['ref']} ({s['type']}): both pins on {s['net']}")
        if len(shorted) > 10:
            print(f"      ... and {len(shorted) - 10} more")
    else:
        print(f"\n   ✅ No shorted passives (LAW 4 validated)")

    # Check phantom components
    phantoms = check_phantom_components(integrated)
    if phantoms:
        # Group by component
        phantom_comps = set(p['expected_component'] for p in phantoms)
        print(f"\n   ❌ Found {len(phantom_comps)} phantom component(s):")
        for comp in list(phantom_comps)[:10]:
            refs = [p['pin_ref'] for p in phantoms if p['expected_component'] == comp]
            print(f"      - {comp}: {len(refs)} references")
    else:
        print(f"\n   ✅ No phantom components")

    # Check single-ended nets
    net_counts = {}
    for conn in integrated.get('connections', []):
        net = conn.get('net')
        points = conn.get('points', [])
        net_counts[net] = len(points)

    single_ended = [n for n, c in net_counts.items() if c == 1 and not n.startswith('NC_')]
    if single_ended:
        print(f"\n   ⚠️  Found {len(single_ended)} single-ended nets")
    else:
        print(f"\n   ✅ No single-ended nets")

    # Step 5: Run circuit supervisor ERC
    print("\n5. Running ERC validation...")
    try:
        validated = supervise_circuit(integrated)
        print("   ✅ Circuit passed ERC validation")
    except Exception as e:
        print(f"   ⚠️  ERC validation: {e}")
        validated = integrated

    # Step 6: Save results
    print("\n6. Saving results...")

    # Save integrated circuit
    output_file = output_dir / "circuit_integrated_circuit.json"
    with open(output_file, 'w') as f:
        json.dump({'circuit': validated}, f, indent=2)
    print(f"   Saved: {output_file}")

    # Copy individual module files from backup
    for filename in backup_dir.glob("circuit_*.json"):
        if 'integrated' not in filename.name:
            dest = output_dir / filename.name
            with open(filename) as f:
                data = json.load(f)
            with open(dest, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"   Copied: {filename.name}")

    # Summary
    print("\n" + "=" * 80)
    print("SIMULATION SUMMARY")
    print("=" * 80)

    success = len(shorted) == 0 and len(phantoms) == 0

    if success:
        print("\n✅ INTEGRATION FIX SUCCESSFUL!")
        print("   - No shorted passives")
        print("   - No phantom components")
    else:
        print("\n❌ INTEGRATION ISSUES REMAIN")
        if shorted:
            print(f"   - {len(shorted)} shorted passives")
        if phantoms:
            print(f"   - {len(set(p['expected_component'] for p in phantoms))} phantom components")

    print("\n" + "=" * 80)

    return success


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Test TC #95 Integration Fix")
    parser.add_argument("--run-id", default="20260205-143152-4109c520",
                        help="Run ID to test")
    args = parser.parse_args()

    success = asyncio.run(run_integration_test(args.run_id))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
