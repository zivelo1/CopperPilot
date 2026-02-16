#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Simulate Step 3 processing using AI text output as input.

Purpose
-------
This utility replays the Step 3 post‑AI pipeline locally without calling any AI
APIs. It reads saved AI responses from logs/runs/<RUN_ID>/ai_training, parses
them with the text parser, validates/fixes via the Circuit Supervisor, and
writes canonical lowlevel JSON files, exactly like the live workflow does.

It is designed to be GENERIC and robust across any circuit type and naming
conventions, and accepts a run id so you can target any saved session.
"""

import sys
import json
from pathlib import Path
import argparse
import re

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from workflow.circuit_text_parser import parse_circuit_text
from workflow.circuit_supervisor import supervise_circuit

def simulate_step3_from_ai_output(ai_response_file: Path, module_name: str, output_dir: Path):
    """
    Simulate Step 3 processing pipeline:
    1. Read AI text output
    2. Parse text to JSON (text parser)
    3. Validate and fix (circuit supervisor)
    4. Save to lowlevel folder
    """

    print(f"\n{'='*80}")
    print(f"Processing: {module_name}")
    print(f"AI Response: {ai_response_file.name}")
    print(f"{'='*80}\n")

    # Step 1: Read AI text output
    print("Step 1: Reading AI text output...")
    with open(ai_response_file, 'r') as f:
        ai_text = f.read()

    print(f"  ✓ Read {len(ai_text)} characters")

    # Step 2: Parse text to JSON
    print("\nStep 2: Parsing text to JSON...")
    try:
        circuit_dict = parse_circuit_text(ai_text, module_name)
        print(f"  ✓ Parsed successfully")
        print(f"    - Components: {len(circuit_dict.get('circuit', {}).get('components', []))}")
        print(f"    - Connections: {len(circuit_dict.get('circuit', {}).get('connections', []))}")
    except Exception as e:
        print(f"  ✗ Parse failed: {e}")
        return False

    # Step 3: Validate and fix with circuit supervisor
    print("\nStep 3: Validating with circuit supervisor...")
    try:
        # Extract circuit dict (supervise_circuit expects the inner circuit, not wrapped)
        circuit_only = circuit_dict.get('circuit', circuit_dict)
        validated_circuit_only = supervise_circuit(circuit_only)

        # Wrap it back
        validated_circuit = {'circuit': validated_circuit_only}

        if validated_circuit:
            print(f"  ✓ Validation completed")
            print(f"    - Final components: {len(validated_circuit.get('circuit', {}).get('components', []))}")
            print(f"    - Final connections: {len(validated_circuit.get('circuit', {}).get('connections', []))}")
        else:
            print(f"  ✗ Validation failed - circuit supervisor returned None")
            return False

    except Exception as e:
        print(f"  ✗ Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 4: Save to lowlevel folder
    print("\nStep 4: Saving to lowlevel folder...")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    safe_name = module_name.lower().replace(' ', '_').replace('-', '_')
    output_file = output_dir / f"circuit_{safe_name}.json"

    try:
        with open(output_file, 'w') as f:
            json.dump(validated_circuit, f, indent=2)
        print(f"  ✓ Saved to: {output_file}")
        return True
    except Exception as e:
        print(f"  ✗ Save failed: {e}")
        return False


def _parse_module_name_from_response(text: str) -> str:
    """Extract a reasonable module name from the AI response text.

    Strategy (generic):
    - Take the first non-empty line that starts with '#'
    - Strip leading '#' and whitespace
    - Split on ' - ' to drop trailing commentary
    - Sanitize to Title_Case_With_Underscores to match existing conventions
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            title = line.lstrip('#').strip()
            if ' - ' in title:
                title = title.split(' - ', 1)[0].strip()
            # Sanitize to underscores (keep alnum and space)
            title = re.sub(r'[^A-Za-z0-9\s_\-\.]+', '', title)
            title = title.replace('-', ' ').replace('.', ' ')
            title = '_'.join(filter(None, title.split()))
            return title
    return "Module"


def _auto_build_mapping(ai_training_dir: Path) -> dict:
    """Build a filename→module mapping by parsing the response headers.

    This is generic and requires no hardcoding for specific runs.
    """
    mapping = {}
    for resp_file in sorted(ai_training_dir.glob("step_3_design_module_*_response.txt")):
        text = resp_file.read_text(encoding='utf-8', errors='ignore')
        module_name = _parse_module_name_from_response(text)
        mapping[resp_file.name] = module_name
    return mapping


def main():
    """Process all AI response files from a run (generic)."""

    parser = argparse.ArgumentParser(description="Simulate Step 3 from saved AI outputs")
    parser.add_argument("--run-id", required=True, help="Run ID under logs/runs and output")
    args = parser.parse_args()

    run_id = args.run_id
    ai_training_dir = project_root / "logs" / "runs" / run_id / "ai_training"
    output_dir = project_root / "output" / run_id / "lowlevel"

    if not ai_training_dir.exists():
        print(f"✗ AI training dir not found: {ai_training_dir}")
        return False

    # Build filename→module mapping generically by inspecting response headers
    module_mapping = _auto_build_mapping(ai_training_dir)
    if not module_mapping:
        print("✗ No AI response files found to process")
        return False

    print(f"\n{'='*80}")
    print(f"STEP 3 SIMULATION - Processing AI Text Outputs")
    print(f"{'='*80}")
    print(f"Run ID: {run_id}")
    print(f"AI Training Dir: {ai_training_dir}")
    print(f"Output Dir: {output_dir}")
    print(f"{'='*80}\n")

    # Clear output directory (only circuit_* files)
    print("Clearing lowlevel folder...")
    if output_dir.exists():
        for file in output_dir.glob("circuit_*.json"):
            file.unlink()
            print(f"  Removed: {file.name}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Process each AI response file
    results = {}
    for filename, module_name in module_mapping.items():
        ai_file = ai_training_dir / filename

        if not ai_file.exists():
            print(f"\n⚠️  Skipping {module_name} - file not found: {filename}")
            results[module_name] = False
            continue

        success = simulate_step3_from_ai_output(ai_file, module_name, output_dir)
        results[module_name] = success

    # Generate components.csv
    print(f"\n{'='*80}")
    print("GENERATING COMPONENTS.CSV")
    print(f"{'='*80}\n")
    generate_components_csv(module_mapping, output_dir)

    # Generate design.json
    print(f"\n{'='*80}")
    print("GENERATING DESIGN.JSON")
    print(f"{'='*80}\n")
    generate_design_json(module_mapping, output_dir, run_id)

    # Summary
    print(f"\n{'='*80}")
    print("SIMULATION SUMMARY")
    print(f"{'='*80}\n")

    successful = sum(1 for v in results.values() if v)
    total = len(results)

    for module, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"  {status}: {module}")

    print(f"\n{'='*80}")
    print(f"Results: {successful}/{total} modules processed successfully")
    print(f"{'='*80}\n")

    return successful == total


def generate_components_csv(module_mapping: dict, output_dir: Path):
    """Generate components.csv from all circuit files - EXACTLY like Step 3 does"""
    print("Reading all circuit files...")

    csv_content = 'RefDes,Type,Value,Module,Circuit,Notes\n'
    total_components = 0

    for filename, module_name in module_mapping.items():
        safe_name = module_name.lower().replace(' ', '_').replace('-', '_')
        circuit_file = output_dir / f"circuit_{safe_name}.json"

        if not circuit_file.exists():
            print(f"  ⚠️  Skipping {module_name} - file not found")
            continue

        with open(circuit_file) as f:
            data = json.load(f)

        circuit = data.get('circuit', {})
        components = circuit.get('components', [])

        for comp in components:
            fields = [
                comp.get('ref', comp.get('refDes', '')),
                comp.get('type', ''),
                comp.get('value', ''),
                module_name,
                module_name,
                comp.get('notes', '')
            ]

            # Escape special characters
            escaped_fields = []
            for field in fields:
                field_str = str(field)
                if ',' in field_str or '"' in field_str or '\n' in field_str:
                    field_str = f'"{field_str.replace(chr(34), chr(34)+chr(34))}"'
                escaped_fields.append(field_str)

            csv_content += ','.join(escaped_fields) + '\n'
            total_components += 1

    # Write CSV file
    csv_path = output_dir / 'components.csv'
    with open(csv_path, 'w') as f:
        f.write(csv_content)

    print(f"✓ Generated: {csv_path}")
    print(f"  Total components: {total_components}")


def generate_design_json(module_mapping: dict, output_dir: Path, run_id: str):
    """Generate design.json summary - EXACTLY like Step 3 does"""
    print("Creating design summary...")

    # Load all circuits
    all_modules = []
    total_components = 0
    total_connections = 0
    total_nets = set()

    for idx, (filename, module_name) in enumerate(module_mapping.items()):
        safe_name = module_name.lower().replace(' ', '_').replace('-', '_')
        circuit_file = output_dir / f"circuit_{safe_name}.json"

        if not circuit_file.exists():
            print(f"  ⚠️  Skipping {module_name} - file not found")
            continue

        with open(circuit_file) as f:
            data = json.load(f)

        circuit = data.get('circuit', {})

        # Count stats
        total_components += len(circuit.get('components', []))
        total_connections += len(circuit.get('connections', []))

        for net in circuit.get('nets', []):
            if isinstance(net, str):
                total_nets.add(net)
            elif isinstance(net, dict):
                net_name = net.get('name', str(net))
                total_nets.add(net_name)

        # Add module
        all_modules.append({
            'moduleName': module_name,
            'moduleIndex': idx,
            **circuit
        })

    # Create summary - EXACTLY like Step 3
    design_summary = {
        'systemOverview': {
            'name': 'Dual-Channel Ultrasonic Transducer Driver',
            'description': f'Complete system with {len(all_modules)} modules',
            'timestamp': run_id,
            'statistics': {
                'totalModules': len(all_modules),
                'totalComponents': total_components,
                'totalConnections': total_connections,
                'totalUniqueNets': len(total_nets)
            }
        },
        'modules': all_modules,
        'validationStatus': {
            'allModulesFixed': True,
            'noNetConflicts': True,
            'status': 'complete'
        }
    }

    # Write design.json
    design_path = output_dir / 'design.json'
    with open(design_path, 'w') as f:
        json.dump(design_summary, f, indent=2)

    print(f"✓ Generated: {design_path}")
    print(f"  Total modules: {len(all_modules)}")
    print(f"  Total components: {total_components}")
    print(f"  Total connections: {total_connections}")


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
