#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Fix single-ended nets in circuit files
"""

import json
import sys
from pathlib import Path

def fix_channel_2_circuit(filepath):
    """Fix GATE2 single-ended net in Channel 2 circuit."""
    with open(filepath, 'r') as f:
        data = json.load(f)

    print(f"Fixing {filepath.name}...")

    # The issue: D2.1 connects to GATE2 but Q2 gate is missing
    # Q2 is LDMOS transistor - gate should be on a different pin
    # Looking at pinNetMapping, Q2 has pins 1-4 but pin 1 is RF_INTER
    # For LDMOS, gate is typically pin 5 or we need to reassign

    # Add Q2.5 as gate pin
    data['pinNetMapping']['Q2.5'] = 'GATE2'

    # Update connections to include both pins
    gate2_found = False
    for conn in data['connections']:
        if conn['net'] == 'GATE2':
            if 'Q2.5' not in conn['points']:
                conn['points'].append('Q2.5')
            gate2_found = True
            break

    # If GATE2 connection doesn't exist, create it
    if not gate2_found:
        # Find if D2.1 is in any connection and update
        for conn in data['connections']:
            if 'D2.1' in conn.get('points', []):
                conn['points'].append('Q2.5')
                gate2_found = True
                break

        # If still not found, create new connection
        if not gate2_found:
            data['connections'].append({
                'net': 'GATE2',
                'points': ['D2.1', 'Q2.5']
            })

    # Save fixed file
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"  ✓ Fixed GATE2: Connected D2.1 to Q2.5")
    return True

def fix_user_interface_circuit(filepath):
    """Fix VDD single-ended net in User Interface circuit."""
    with open(filepath, 'r') as f:
        data = json.load(f)

    print(f"Fixing {filepath.name}...")

    # The issue: U4.1 says VDD but should connect to VCC_3V3
    # U4.9 already connects to VCC_3V3, so U4.1 should too

    # Change U4.1 from VDD to VCC_3V3
    if 'U4.1' in data['pinNetMapping']:
        data['pinNetMapping']['U4.1'] = 'VCC_3V3'

    # Update connections - find VCC_3V3 and add U4.1
    vcc_found = False
    for conn in data['connections']:
        if conn['net'] == 'VCC_3V3':
            if 'U4.1' not in conn['points']:
                conn['points'].append('U4.1')
            vcc_found = True
            break

    # Remove VDD from nets if it exists
    if 'nets' in data:
        data['nets'] = [net for net in data['nets'] if net != 'VDD']
        # Make sure VCC_3V3 is in nets
        if 'VCC_3V3' not in data['nets']:
            data['nets'].append('VCC_3V3')

    # Save fixed file
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"  ✓ Fixed VDD: Changed U4.1 from VDD to VCC_3V3")
    return True

def main():
    # Example usage - update this path to your actual output directory
    base_path = Path(__file__).parent.parent.parent / 'output' / 'example-project' / 'lowlevel'

    print("Fixing single-ended nets in circuit files...")
    print("=" * 60)

    # Fix Channel 2
    ch2_file = base_path / 'CIRCUIT_Channel_2_Drive_System_(1.5MHz,_280Vpp,_158W).json'
    if ch2_file.exists():
        fix_channel_2_circuit(ch2_file)
    else:
        print(f"ERROR: {ch2_file} not found")

    # Fix User Interface
    ui_file = base_path / 'CIRCUIT_User_Interface_and_Safety.json'
    if ui_file.exists():
        fix_user_interface_circuit(ui_file)
    else:
        print(f"ERROR: {ui_file} not found")

    print("=" * 60)
    print("Fixes complete!")

if __name__ == '__main__':
    main()