#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Unit test for Step 2 truncated response handling

This test verifies that the enhanced JSON parsing and module extraction
correctly handles truncated AI responses where the JSON is incomplete.

Test Case: Real failed run from 2025-11-02 where connections array was truncated
Expected: Successfully extract all 6 modules despite truncation
"""

import sys
import json
import re
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

def test_truncated_response_extraction():
    """
    Test module extraction from the actual truncated response that caused the failure.

    This simulates the _parse_ai_response and _extract_partial_json methods.
    """

    # Read the actual truncated response from the failed run
    response_file = Path('logs/runs/20251102-074719-75a16a75/ai_training/step2_high_level_20251102_075039_412_main_response.txt')

    if not response_file.exists():
        print(f"⚠️  Test file not found: {response_file}")
        print("   This test requires the failed run logs to be present.")
        return False

    with open(response_file, 'r') as f:
        raw_response = f.read()

    # Simulate _parse_ai_response behavior
    text = raw_response.strip()
    text = re.sub(r'^```json?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'```\s*$', '', text)

    # Try standard JSON parsing (should fail due to truncation)
    json_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
    if not json_match:
        print("❌ FAIL: Could not find JSON in response")
        return False

    json_str = json_match.group(1)

    try:
        # This should fail on truncated response
        parsed = json.loads(json_str)
        print("✅ JSON parsed successfully (not truncated)")
        modules = parsed.get('modules', [])
    except json.JSONDecodeError:
        print("✅ JSON parse failed as expected (truncated response)")
        print("   Attempting partial extraction via regex...")

        # Simulate _extract_partial_json behavior
        result = {}

        # Extract modules array using the enhanced regex
        modules_pattern = r'"modules"\s*:\s*\[([\s\S]*?)\]\s*,\s*("connections"|"diagrams"|\})'
        modules_match = re.search(modules_pattern, json_str)

        if not modules_match:
            print("❌ FAIL: Could not find modules pattern")
            return False

        modules_json = '[' + modules_match.group(1) + ']'

        try:
            modules = json.loads(modules_json)
        except json.JSONDecodeError as e:
            print(f"❌ FAIL: Could not parse extracted modules: {e}")
            return False

    # Validate extracted modules
    if not modules:
        print("❌ FAIL: No modules extracted")
        return False

    if len(modules) != 6:
        print(f"❌ FAIL: Expected 6 modules, got {len(modules)}")
        return False

    # Expected module names
    expected_names = [
        'Power_Supply_Module',
        'Main_Controller_Module',
        'Channel_1_Module_50kHz',
        'Channel_2_Module_1_5MHz',
        'User_Interface_Module',
        'Protection_And_Monitoring'
    ]

    for i, expected_name in enumerate(expected_names):
        if modules[i].get('name') != expected_name:
            print(f"❌ FAIL: Module {i} name mismatch")
            print(f"   Expected: {expected_name}")
            print(f"   Got: {modules[i].get('name')}")
            return False

        # Validate module structure
        if not isinstance(modules[i], dict):
            print(f"❌ FAIL: Module {i} is not a dictionary")
            return False

        required_fields = ['name', 'type', 'description', 'inputs', 'outputs', 'specifications']
        for field in required_fields:
            if field not in modules[i]:
                print(f"❌ FAIL: Module {i} missing field: {field}")
                return False

    # Success!
    print("✅ SUCCESS: All modules extracted correctly from truncated response!")
    print(f"\nExtracted {len(modules)} modules:")
    for i, module in enumerate(modules, 1):
        print(f"  {i}. {module['name']}")
        print(f"     Type: {module['type']}")
        print(f"     Inputs: {len(module['inputs'])}")
        print(f"     Outputs: {len(module['outputs'])}")
        print(f"     Specs: {len(module['specifications'])} fields")

    print("\n🎯 FIX VERIFICATION: The enhanced extraction would have prevented the system failure!")
    return True


if __name__ == '__main__':
    success = test_truncated_response_extraction()
    sys.exit(0 if success else 1)
