#!/usr/bin/env python3
"""
Post-processor: Fixes KiCad schematic connectivity by placing global labels at TRUE pin positions.

Uses sexpdata to parse the .kicad_sch, extracts actual symbol pin geometry from lib_symbols,
calculates true pin positions from instance placements, then rebuilds all wires and labels.

Usage: python3 fix_schematic_labels.py <kicad_dir> <lowlevel_dir>
"""

import json
import math
import sys
import uuid
from pathlib import Path

import sexpdata


def extract_symbol_pin_defs(data):
    """Extract pin definitions from lib_symbols, organized by lib_id and unit."""
    pins = {}  # lib_id -> {unit -> [(pin_num, pin_name, x, y, angle)]}

    lib_symbols = None
    for item in data:
        if isinstance(item, list) and len(item) > 0:
            if isinstance(item[0], sexpdata.Symbol) and str(item[0]) == 'lib_symbols':
                lib_symbols = item
                break
    if not lib_symbols:
        return pins

    current_lib_id = None
    for item in lib_symbols[1:]:
        if isinstance(item, list) and len(item) > 1:
            if isinstance(item[0], sexpdata.Symbol) and str(item[0]) == 'symbol':
                sym_name = str(item[1])
                if ':' in sym_name:
                    current_lib_id = sym_name
                    if current_lib_id not in pins:
                        pins[current_lib_id] = {}
                    # Process sub-symbols
                    for sub in item[2:]:
                        if isinstance(sub, list) and len(sub) > 1:
                            if isinstance(sub[0], sexpdata.Symbol) and str(sub[0]) == 'symbol':
                                sub_name = str(sub[1])
                                parts = sub_name.rsplit('_', 2)
                                unit_num = 0
                                if len(parts) >= 3:
                                    try:
                                        unit_num = int(parts[-2])
                                    except ValueError:
                                        unit_num = 0
                                store_unit = unit_num if unit_num > 0 else 1
                                sub_pins = _find_pins(sub)
                                if sub_pins:
                                    if store_unit not in pins[current_lib_id]:
                                        pins[current_lib_id][store_unit] = []
                                    pins[current_lib_id][store_unit].extend(sub_pins)
    return pins


def _find_pins(sexp):
    """Recursively find pin definitions in an S-expression."""
    pins = []
    if not isinstance(sexp, list):
        return pins
    if len(sexp) > 0 and isinstance(sexp[0], sexpdata.Symbol) and str(sexp[0]) == 'pin':
        px, py, pangle = 0, 0, 0
        pin_num, pin_name = None, None
        for sub in sexp:
            if isinstance(sub, list) and len(sub) > 0:
                tag = str(sub[0]) if isinstance(sub[0], sexpdata.Symbol) else ''
                if tag == 'at' and len(sub) >= 4:
                    px, py, pangle = float(sub[1]), float(sub[2]), float(sub[3])
                elif tag == 'number' and len(sub) >= 2:
                    pin_num = str(sub[1])
                elif tag == 'name' and len(sub) >= 2:
                    pin_name = str(sub[1])
        if pin_num:
            pins.append((pin_num, pin_name or pin_num, px, py, pangle))
    else:
        for sub in sexp:
            if isinstance(sub, list):
                pins.extend(_find_pins(sub))
    return pins


def extract_instances(data):
    """Extract symbol instances (not in lib_symbols)."""
    instances = []
    for item in data:
        if isinstance(item, list) and len(item) > 1:
            if isinstance(item[0], sexpdata.Symbol) and str(item[0]) == 'symbol':
                lib_id = None
                ix, iy, iangle = 0, 0, 0
                unit = 1
                ref = '?'
                for sub in item[1:]:
                    if isinstance(sub, list) and len(sub) > 0:
                        tag = str(sub[0]) if isinstance(sub[0], sexpdata.Symbol) else ''
                        if tag == 'lib_id' and len(sub) >= 2:
                            lib_id = str(sub[1])
                        elif tag == 'at' and len(sub) >= 4:
                            ix, iy, iangle = float(sub[1]), float(sub[2]), float(sub[3])
                        elif tag == 'unit' and len(sub) >= 2:
                            unit = int(sub[1])
                        elif tag == 'property' and len(sub) >= 3:
                            if str(sub[1]) == 'Reference':
                                ref = str(sub[2])
                if lib_id:
                    instances.append({'ref': ref, 'lib_id': lib_id, 'x': ix, 'y': iy, 'angle': iangle, 'unit': unit})
    return instances


def calculate_true_pin_positions(pin_defs, instances):
    """Calculate actual schematic pin positions for all instances."""
    positions = {}  # "REF.PIN_NUM" -> (x, y, wire_angle)
    for inst in instances:
        lib_id = inst['lib_id']
        unit = inst['unit']
        ref = inst['ref']
        if lib_id not in pin_defs:
            continue
        unit_pins = pin_defs[lib_id].get(unit, pin_defs[lib_id].get(1, []))
        for pin_num, _, px, py, pangle in unit_pins:
            angle_rad = math.radians(inst['angle'])
            rx = px * math.cos(angle_rad) - py * math.sin(angle_rad)
            ry = px * math.sin(angle_rad) + py * math.cos(angle_rad)
            ax = round(inst['x'] + rx, 4)
            ay = round(inst['y'] + ry, 4)
            wire_angle = (pangle + inst['angle']) % 360
            positions[f"{ref}.{pin_num}"] = (ax, ay, wire_angle)
    return positions


def fix_schematic(sch_path, pin_net_map):
    """Fix a single .kicad_sch file by rebuilding all connectivity."""
    with open(sch_path) as f:
        content = f.read()

    # KiCad converter may produce labels outside the main (kicad_sch ...) block,
    # resulting in multiple top-level expressions. Wrap to parse as a list.
    try:
        data = sexpdata.loads(content)
    except (AssertionError, Exception):
        wrapped = sexpdata.loads('(' + content.strip() + ')')
        # First element should be the (kicad_sch ...) block
        data = wrapped[0] if wrapped else []
    pin_defs = extract_symbol_pin_defs(data)
    instances = extract_instances(data)
    true_positions = calculate_true_pin_positions(pin_defs, instances)

    print(f"  Parsed {len(pin_defs)} symbol defs, {len(instances)} instances, {len(true_positions)} pin positions")

    # Remove all existing wires, global_labels, and no_connect from the raw text
    lines = content.split('\n')
    new_lines = []
    skip_depth = 0
    in_skip = False

    for line in lines:
        stripped = line.strip()
        if not in_skip:
            if stripped.startswith('(wire') or stripped.startswith('(global_label') or stripped.startswith('(no_connect'):
                in_skip = True
                skip_depth = sum(1 for c in line if c == '(') - sum(1 for c in line if c == ')')
                if skip_depth <= 0:
                    in_skip = False
                continue
            new_lines.append(line)
        else:
            skip_depth += sum(1 for c in line if c == '(') - sum(1 for c in line if c == ')')
            if skip_depth <= 0:
                in_skip = False

    # Generate new connectivity
    stub_length = 2.54
    connectivity_lines = []
    label_count = 0
    wire_count = 0
    unmatched = []

    # Group pins by net
    net_to_pins = {}
    for pin_key, net_name in pin_net_map.items():
        if not net_name or net_name == 'None':
            continue
        if net_name not in net_to_pins:
            net_to_pins[net_name] = []
        net_to_pins[net_name].append(pin_key)

    for net_name, pin_keys in net_to_pins.items():
        net_upper = net_name.upper()
        if net_upper == 'NC' or net_upper.startswith('NC_'):
            continue

        for pin_key in pin_keys:
            if pin_key not in true_positions:
                unmatched.append(pin_key)
                continue

            px, py, pangle = true_positions[pin_key]

            # Calculate stub endpoint — OUTWARD from symbol body
            # Pin angle points INTO the symbol; add 180° to point AWAY
            outward_angle = (pangle + 180) % 360
            angle_rad = math.radians(outward_angle)
            sx = round(px + stub_length * math.cos(angle_rad), 2)
            sy = round(py - stub_length * math.sin(angle_rad), 2)

            # Stub wire
            w_uuid = str(uuid.uuid4())
            connectivity_lines.append(f'  (wire')
            connectivity_lines.append(f'    (pts')
            connectivity_lines.append(f'      (xy {px} {py})')
            connectivity_lines.append(f'      (xy {sx} {sy})')
            connectivity_lines.append(f'    )')
            connectivity_lines.append(f'    (stroke (width 0) (type default))')
            connectivity_lines.append(f'    (uuid "{w_uuid}")')
            connectivity_lines.append(f'  )')
            wire_count += 1

            # Global label at stub endpoint
            l_uuid = str(uuid.uuid4())
            label_angle = int(outward_angle) % 360
            connectivity_lines.append(f'  (global_label "{net_name}"')
            connectivity_lines.append(f'    (shape input)')
            connectivity_lines.append(f'    (at {sx} {sy} {label_angle})')
            connectivity_lines.append(f'    (fields_autoplaced yes)')
            connectivity_lines.append(f'    (effects (font (size 1.27 1.27)) (justify left))')
            connectivity_lines.append(f'    (uuid "{l_uuid}")')
            connectivity_lines.append(f'    (property "Intersheetrefs" "${{INTERSHEET_REFS}}"')
            connectivity_lines.append(f'      (at 0 0 0)')
            connectivity_lines.append(f'      (effects (font (size 1.27 1.27)) (hide yes))')
            connectivity_lines.append(f'    )')
            connectivity_lines.append(f'  )')
            label_count += 1

    # Insert before the final closing paren
    result = '\n'.join(new_lines)
    last_paren = result.rfind(')')
    result = result[:last_paren] + '\n' + '\n'.join(connectivity_lines) + '\n)'

    with open(sch_path, 'w') as f:
        f.write(result)

    print(f"  Generated {label_count} labels, {wire_count} wires")
    if unmatched:
        print(f"  Unmatched pins (no position found): {len(unmatched)}")
        for p in unmatched[:5]:
            print(f"    - {p}")
    return label_count > 0


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 fix_schematic_labels.py <kicad_dir> <lowlevel_dir>")
        sys.exit(1)

    kicad_dir = Path(sys.argv[1])
    lowlevel_dir = Path(sys.argv[2])

    for sch_file in sorted(kicad_dir.glob('*.kicad_sch')):
        base = sch_file.stem
        # Find matching JSON
        json_file = None
        for jf in lowlevel_dir.glob('circuit_*.json'):
            jf_norm = jf.stem.lower().replace('circuit_', '').replace('_', '')
            sch_norm = base.lower().replace('_driver', '').replace('_', '')
            if jf_norm == sch_norm or sch_norm in jf_norm or jf_norm in sch_norm:
                json_file = jf
                break

        if not json_file:
            print(f"WARNING: No matching JSON for {sch_file.name}")
            continue

        print(f"\n{'='*60}")
        print(f"Fixing: {sch_file.name} <- {json_file.name}")

        with open(json_file) as f:
            circuit = json.load(f).get('circuit', {})
        pin_net_map = circuit.get('pinNetMapping', {})

        fix_schematic(sch_file, pin_net_map)

    # Verify with kicad-cli if available
    kicad_cli = Path('/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli')
    if kicad_cli.exists():
        print(f"\n{'='*60}")
        print("VERIFYING WITH KICAD-CLI ERC...")
        import subprocess
        for sch_file in sorted(kicad_dir.glob('*.kicad_sch')):
            result = subprocess.run(
                [str(kicad_cli), 'sch', 'erc', '--exit-code-violations', '--format', 'json',
                 '-o', f'/tmp/{sch_file.stem}_erc.json', str(sch_file)],
                capture_output=True, text=True, timeout=60
            )
            with open(f'/tmp/{sch_file.stem}_erc.json') as f:
                erc = json.load(f)
            violations = erc.get('sheets', [{}])[0].get('violations', [])
            errors = [v for v in violations if v['severity'] == 'error']
            warnings = [v for v in violations if v['severity'] == 'warning']
            status = "PASS" if len(errors) == 0 else "FAIL"
            print(f"  {sch_file.stem}: {len(errors)} errors, {len(warnings)} warnings [{status}]")
            for e in errors[:3]:
                items = ', '.join(i.get('description', '')[:60] for i in e.get('items', []))
                print(f"    [{e['type']}] {items}")


if __name__ == '__main__':
    main()
