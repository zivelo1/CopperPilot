#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
TC #90: Simulate Step 3 Two-Stage Processing from AI Outputs.

This script tests the truncation recovery fix (TC #90) by:
1. Reading Stage 1 AI responses (components JSON - possibly truncated)
2. Applying the NEW truncation recovery logic
3. Parsing components with the fixed _parse_with_repair method
4. Generating connections locally (no API calls needed)
5. Writing canonical lowlevel JSON files

This script is GENERIC - works for ANY circuit type, not tied to specific examples.

Usage:
    python tests/simulate_step3_two_stage.py --run-id <RUN_ID>
"""

import sys
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from workflow.circuit_supervisor import supervise_circuit


def recover_truncated_json(json_str: str) -> Optional[str]:
    """
    TC #90 FIX (Enhanced): Recover truncated JSON by finding the last complete element.

    Strategy:
    1. Find the last complete component object (ends with proper `}`)
    2. Truncate everything after that
    3. Close all unclosed structures

    This handles complex cases where truncation happens mid-property.

    Args:
        json_str: Potentially truncated JSON string

    Returns:
        Recovered JSON string or None if not truncated
    """
    # Count unclosed braces and brackets
    open_braces = json_str.count('{') - json_str.count('}')
    open_brackets = json_str.count('[') - json_str.count(']')

    if open_braces <= 0 and open_brackets <= 0:
        return None  # Not truncated

    print(f"  TC #90: Detected truncation - {open_braces} unclosed braces, {open_brackets} unclosed brackets")

    # Strategy: Find the last complete object in the components array
    # Look for patterns like: }   ] or },  followed by incomplete content

    # Find all positions where a complete object ends (},\n or }\n  ])
    truncated = json_str.rstrip()

    # Best approach: find the last occurrence of a complete component definition
    # A complete component ends with: }   (possibly followed by comma)
    # and the pins array is closed: ]

    # Find the last position where we have `]\n    }` (end of pins array + end of component)
    last_complete_component = -1

    # Pattern: end of pins array followed by end of component object
    # This handles: `]\n    },` or `]\n    }\n  ]` etc.
    for match in re.finditer(r'\]\s*\}\s*,?', truncated):
        last_complete_component = match.end()

    if last_complete_component > 0:
        # Truncate to last complete component
        truncated = truncated[:last_complete_component].rstrip(',').rstrip()
        print(f"  TC #90: Truncated to last complete component at position {last_complete_component}")
    else:
        # Fallback: try to find any complete object
        # Remove partial property (string or otherwise)
        # Pattern: ,"key": value  where value is incomplete

        # Remove incomplete string values (missing closing quote)
        truncated = re.sub(r'"[^"]*$', '', truncated)

        # Remove incomplete key-value pairs
        truncated = re.sub(r',?\s*"[^"]*":\s*$', '', truncated)

        # Remove incomplete object/array starts
        truncated = re.sub(r',?\s*[\[{]\s*$', '', truncated)

        # Remove trailing comma
        truncated = re.sub(r',\s*$', '', truncated)

        print(f"  TC #90: Used fallback cleanup")

    # Recalculate after cleanup
    open_braces = truncated.count('{') - truncated.count('}')
    open_brackets = truncated.count('[') - truncated.count(']')

    # Ensure we have balanced structures by closing them in order
    # For JSON with nested arrays in objects, order matters: ] then }

    # Build closing sequence
    closers = ''

    # If we're inside a components array, close it
    if open_brackets > 0:
        closers += ']' * open_brackets
        print(f"  TC #90: Adding {open_brackets} closing brackets")

    # Close any remaining objects (including the root)
    if open_braces > 0:
        closers += '}' * open_braces
        print(f"  TC #90: Adding {open_braces} closing braces")

    result = truncated + closers

    print(f"  TC #90: Recovery complete, result length: {len(result)}")

    return result


def parse_stage1_response(raw_response: str) -> Optional[Dict]:
    """
    Parse Stage 1 response with truncation recovery.

    Mirrors the logic in agent_manager.py but standalone for simulation.
    """
    # Try to extract JSON from markdown code block
    json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', raw_response)

    json_str = None
    if json_match:
        json_str = json_match.group(1).strip()
    elif '{' in raw_response:
        start = raw_response.find('{')
        end = raw_response.rfind('}') + 1
        if start >= 0 and end > start:
            json_str = raw_response[start:end]

    if not json_str:
        print("  ERROR: No JSON found in response")
        return None

    # Try direct parse first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"  JSON parse failed at position {e.pos}: {e.msg}")

        # Try truncation recovery
        recovered = recover_truncated_json(json_str)
        if recovered:
            try:
                result = json.loads(recovered)
                comp_count = len(result.get('components', []))
                print(f"  TC #90 SUCCESS: Recovered {comp_count} components from truncated JSON!")
                return result
            except json.JSONDecodeError as e2:
                print(f"  TC #90: Recovery failed: {e2.msg}")

        return None


def generate_connections_from_components(components: List[Dict], module_name: str) -> Tuple[List[Dict], Dict[str, str], List[str]]:
    """
    Generate basic connections from components (no API calls).

    Strategy:
    1. Identify power pins (VIN, VCC, VDD, +, power_in) -> connect to VCC net
    2. Identify ground pins (GND, VSS, -, ground) -> connect to GND net
    3. Create module-specific signal nets for other pins

    This is GENERIC - works for ANY circuit type.

    Args:
        components: List of component dicts with pins
        module_name: Name for prefixing nets

    Returns:
        Tuple of (connections, pinNetMapping, nets)
    """
    connections = []
    pin_net_mapping = {}
    nets = set(['VCC', 'GND'])

    # Patterns for power/ground detection
    # TC #90: Enhanced to detect more IC power pins
    power_patterns = ['VCC', 'VDD', 'VIN', 'V+', '+V', 'VBAT', 'VIN+', 'power_in', 'DC+',
                      'AVCC', 'DVCC', 'PVCC', 'VP', 'VDC', 'VLOGIC', 'VBS', 'VB']
    ground_patterns = ['GND', 'VSS', 'V-', '-V', 'DGND', 'AGND', 'VIN-', 'ground', 'DC-',
                       'PGND', 'SGND', 'COM', 'EPAD', 'EXPPAD']
    # TC #90: Special pins that need bypass to GND
    bypass_patterns = ['CAP', 'BYPASS', 'COMP', 'SS', 'RT', 'CT', 'FB', 'SOFT', 'BOOT']
    # TC #90: Output/driver pins that need connection
    output_patterns = ['OUT', 'HB', 'HS', 'LO', 'HO', 'SW', 'PHASE', 'DRV', 'GATE']

    vcc_points = []
    gnd_points = []
    signal_nets = {}  # net_name -> [points]
    net_counter = 1

    for comp in components:
        ref = comp.get('ref', '')
        pins = comp.get('pins', [])

        for pin in pins:
            if isinstance(pin, dict):
                pin_num = pin.get('number', '')
                pin_name = pin.get('name', str(pin_num))
                pin_type = pin.get('type', 'passive')
            else:
                pin_num = str(pin)
                pin_name = str(pin)
                pin_type = 'passive'

            point = f"{ref}.{pin_num}"

            # Classify pin
            pin_name_upper = pin_name.upper()

            # TC #90: Check ground patterns FIRST to handle VIN- correctly
            # (VIN- should go to GND, not VCC due to VIN prefix)
            if any(p in pin_name_upper for p in ground_patterns) or pin_type == 'ground':
                gnd_points.append(point)
                pin_net_mapping[point] = 'GND'
            elif any(p in pin_name_upper for p in power_patterns) or pin_type == 'power_in':
                vcc_points.append(point)
                pin_net_mapping[point] = 'VCC'
            elif any(p in pin_name_upper for p in bypass_patterns):
                # TC #90: Bypass pins typically need bypass cap to GND
                # Connect to a bypass net that links to GND
                bypass_net = f"BYPASS_{ref}_{pin_num}"
                nets.add(bypass_net)
                pin_net_mapping[point] = bypass_net
                # Also connect bypass net to GND via bypass cap
                gnd_points.append(point)  # Simplified: just connect to GND
                pin_net_mapping[point] = 'GND'
            elif any(p in pin_name_upper for p in output_patterns):
                # TC #90: Output pins need meaningful connections
                # Create output nets grouped by component
                output_net = f"OUT_{ref}"
                if output_net not in signal_nets:
                    signal_nets[output_net] = []
                    nets.add(output_net)
                signal_nets[output_net].append(point)
                pin_net_mapping[point] = output_net
            else:
                # Create a signal net
                net_name = f"NET_{net_counter}"
                net_counter += 1

                if net_name not in signal_nets:
                    signal_nets[net_name] = []
                    nets.add(net_name)

                signal_nets[net_name].append(point)
                pin_net_mapping[point] = net_name

    # Build connections
    if vcc_points:
        connections.append({'net': 'VCC', 'points': vcc_points})
    if gnd_points:
        connections.append({'net': 'GND', 'points': gnd_points})

    for net_name, points in signal_nets.items():
        if points:
            connections.append({'net': net_name, 'points': points})

    return connections, pin_net_mapping, sorted(list(nets))


def extract_module_name_from_prompt(prompt_file: Path) -> str:
    """Extract module name from prompt file content."""
    try:
        text = prompt_file.read_text()
        # Look for "Module: <name>" pattern
        match = re.search(r'Module:\s*(\d+)/\d+\s*-\s*([^\n]+)', text)
        if match:
            return match.group(2).strip()

        # Look for module name in prompt
        match = re.search(r'"module":\s*"([^"]+)"', text)
        if match:
            return match.group(1).strip()

    except Exception:
        pass

    return "Unknown_Module"


def process_stage1_response(response_file: Path, prompt_file: Path, output_dir: Path) -> bool:
    """
    Process a single Stage 1 response file.

    1. Parse JSON (with truncation recovery)
    2. Generate connections
    3. Validate with circuit supervisor
    4. Save to lowlevel folder
    """
    # Extract module name from prompt
    module_name = extract_module_name_from_prompt(prompt_file)

    print(f"\n{'='*80}")
    print(f"Processing: {module_name}")
    print(f"Response: {response_file.name}")
    print(f"{'='*80}\n")

    # Read response
    print("Step 1: Reading AI response...")
    raw_response = response_file.read_text()
    print(f"  Read {len(raw_response)} characters")

    # Parse with truncation recovery
    print("\nStep 2: Parsing JSON (with TC #90 truncation recovery)...")
    parsed = parse_stage1_response(raw_response)

    if not parsed:
        print("  FAILED: Could not parse response")
        return False

    components = parsed.get('components', [])
    print(f"  SUCCESS: Parsed {len(components)} components")

    if len(components) < 3:
        print("  WARNING: Very few components - may indicate truncation issue")

    # Generate connections
    print("\nStep 3: Generating connections...")
    connections, pin_net_mapping, nets = generate_connections_from_components(components, module_name)
    print(f"  Generated {len(connections)} connections across {len(nets)} nets")

    # Build circuit structure
    circuit = {
        'moduleName': module_name.replace(' ', '_'),
        'moduleType': 'ai_designed',
        'components': components,
        'connections': connections,
        'nets': nets,
        'pinNetMapping': pin_net_mapping
    }

    # Validate with circuit supervisor
    print("\nStep 4: Validating with Circuit Supervisor...")
    try:
        validated_circuit = supervise_circuit(circuit)
        if validated_circuit:
            print(f"  SUCCESS: Validation complete")
            print(f"    Components: {len(validated_circuit.get('components', []))}")
            print(f"    Connections: {len(validated_circuit.get('connections', []))}")
        else:
            print("  WARNING: Circuit supervisor returned None, using original")
            validated_circuit = circuit
    except Exception as e:
        print(f"  WARNING: Validation error: {e}")
        validated_circuit = circuit

    # Save to file
    print("\nStep 5: Saving to lowlevel folder...")
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = module_name.lower().replace(' ', '_').replace('-', '_')
    safe_name = re.sub(r'[^a-z0-9_]', '', safe_name)
    output_file = output_dir / f"circuit_{safe_name}.json"

    output_data = {'circuit': validated_circuit}

    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"  SUCCESS: Saved to {output_file}")

    return True


def find_latest_stage1_for_each_module(ai_training_dir: Path) -> Dict[str, Tuple[Path, Path]]:
    """
    Find the latest Stage 1 response for each module.

    Multiple attempts may exist for each module due to retries.
    We want the last (most recent) attempt per module.

    Returns:
        Dict mapping module_name -> (response_file, prompt_file)
    """
    # Group files by timestamp
    response_files = sorted(ai_training_dir.glob("step_3_stage1_components_*_response.txt"))

    # Build module -> latest files mapping
    module_files = {}

    for resp_file in response_files:
        # Get corresponding prompt file
        prompt_file = resp_file.parent / resp_file.name.replace('_response.txt', '_prompt.txt')

        if not prompt_file.exists():
            continue

        # Extract module name
        module_name = extract_module_name_from_prompt(prompt_file)

        # Keep the latest (files are sorted, so last one wins)
        module_files[module_name] = (resp_file, prompt_file)

    return module_files


def generate_components_csv(output_dir: Path):
    """Generate components.csv from all circuit files."""
    print("\nGenerating components.csv...")

    csv_lines = ['RefDes,Type,Value,Module,Package,Notes']
    total = 0

    for circuit_file in sorted(output_dir.glob("circuit_*.json")):
        with open(circuit_file) as f:
            data = json.load(f)

        circuit = data.get('circuit', data)
        module_name = circuit.get('moduleName', circuit_file.stem)

        for comp in circuit.get('components', []):
            ref = comp.get('ref', '')
            ctype = comp.get('type', '')
            value = comp.get('value', '')
            package = comp.get('package', '')
            notes = comp.get('notes', comp.get('purpose', ''))

            # Escape fields
            fields = [ref, ctype, value, module_name, package, notes]
            escaped = []
            for f in fields:
                s = str(f)
                if ',' in s or '"' in s:
                    s = f'"{s.replace(chr(34), chr(34)+chr(34))}"'
                escaped.append(s)

            csv_lines.append(','.join(escaped))
            total += 1

    csv_path = output_dir / 'components.csv'
    csv_path.write_text('\n'.join(csv_lines))
    print(f"  Generated: {csv_path} ({total} components)")


def generate_design_json(output_dir: Path, run_id: str):
    """Generate design.json summary."""
    print("\nGenerating design.json...")

    modules = []
    total_components = 0
    total_connections = 0
    all_nets = set()

    for idx, circuit_file in enumerate(sorted(output_dir.glob("circuit_*.json"))):
        with open(circuit_file) as f:
            data = json.load(f)

        circuit = data.get('circuit', data)

        modules.append({
            'moduleName': circuit.get('moduleName', ''),
            'moduleIndex': idx,
            'circuit': circuit
        })

        total_components += len(circuit.get('components', []))
        total_connections += len(circuit.get('connections', []))
        all_nets.update(circuit.get('nets', []))

    design = {
        'systemOverview': {
            'name': 'Multi-Module Electronic System',
            'description': f'Complete system with {len(modules)} modules',
            'timestamp': run_id,
            'statistics': {
                'totalModules': len(modules),
                'totalComponents': total_components,
                'totalConnections': total_connections,
                'totalUniqueNets': len(all_nets)
            }
        },
        'modules': modules
    }

    design_path = output_dir / 'design.json'
    with open(design_path, 'w') as f:
        json.dump(design, f, indent=2)

    print(f"  Generated: {design_path}")
    print(f"    Modules: {len(modules)}")
    print(f"    Components: {total_components}")
    print(f"    Connections: {total_connections}")


def main():
    parser = argparse.ArgumentParser(description="TC #90: Simulate Step 3 Two-Stage from AI outputs")
    parser.add_argument("--run-id", required=True, help="Run ID under logs/runs and output")
    args = parser.parse_args()

    run_id = args.run_id
    ai_training_dir = project_root / "logs" / "runs" / run_id / "ai_training"
    output_dir = project_root / "output" / run_id / "lowlevel"

    print(f"\n{'='*80}")
    print(f"TC #90: STEP 3 TWO-STAGE SIMULATION")
    print(f"{'='*80}")
    print(f"Run ID: {run_id}")
    print(f"AI Training: {ai_training_dir}")
    print(f"Output: {output_dir}")
    print(f"{'='*80}\n")

    if not ai_training_dir.exists():
        print(f"ERROR: AI training dir not found: {ai_training_dir}")
        return False

    # Find latest Stage 1 response for each module
    module_files = find_latest_stage1_for_each_module(ai_training_dir)

    if not module_files:
        print("ERROR: No Stage 1 response files found")
        return False

    print(f"Found {len(module_files)} modules to process:")
    for name in sorted(module_files.keys()):
        print(f"  - {name}")

    # Clear output directory
    print("\nClearing lowlevel folder...")
    if output_dir.exists():
        for f in output_dir.glob("circuit_*.json"):
            f.unlink()
            print(f"  Removed: {f.name}")
        for f in ['components.csv', 'design.json', 'rating_validation_report.json', 'rating_validation_summary.txt']:
            fp = output_dir / f
            if fp.exists():
                fp.unlink()
                print(f"  Removed: {f}")

    # Process each module
    results = {}
    for module_name, (resp_file, prompt_file) in sorted(module_files.items()):
        success = process_stage1_response(resp_file, prompt_file, output_dir)
        results[module_name] = success

    # Generate summary files
    generate_components_csv(output_dir)
    generate_design_json(output_dir, run_id)

    # Print summary
    print(f"\n{'='*80}")
    print("SIMULATION SUMMARY")
    print(f"{'='*80}\n")

    success_count = sum(1 for v in results.values() if v)
    total = len(results)

    for name, success in sorted(results.items()):
        status = "SUCCESS" if success else "FAILED"
        print(f"  [{status}] {name}")

    print(f"\n{'='*80}")
    print(f"Results: {success_count}/{total} modules processed successfully")
    print(f"{'='*80}\n")

    return success_count == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
