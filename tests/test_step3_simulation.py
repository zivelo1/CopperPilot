#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 3 Simulation Test
Tests low-level circuit generation with Step 2 output
"""

import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from workflow.step_3_low_level import Step3LowLevel
from ai_agents.agent_manager import AIAgentManager

async def test_step3():
    """Test Step 3 with Step 2 output from latest run"""

    print("=" * 80)
    print("STEP 3 SIMULATION TEST")
    print("=" * 80)

    # Get Step 2 output - modules generated from successful Step 2 run
    modules = [
        {'name': 'Power_Supply_Module'},
        {'name': 'Main_Controller_Module'},
        {'name': 'Channel_1_Driver_Module'},
        {'name': 'Channel_2_Driver_Module'},
        {'name': 'User_Interface_Module'},
        {'name': 'Protection_and_Monitoring_Module'}
    ]

    # Read the full Step 2 output from the state
    step2_output_file = Path('output/20251005-114147-e5390dec/highlevel/step2_output.json')
    if step2_output_file.exists():
        with open(step2_output_file) as f:
            step2_data = json.load(f)
            high_level_design = step2_data.get('highLevelDesign', {})
    else:
        # Minimal high-level design structure
        high_level_design = {
            'description': 'Dual-channel ultrasonic transducer driver system',
            'modules': modules
        }

    # Initialize Step 3
    project_id = '20251005-114147-e5390dec'
    project_folder = f'output/{project_id}'
    step3 = Step3LowLevel(project_folder=project_folder)

    print(f"\nProject ID: {project_id}")
    print(f"Output dir: {step3.lowlevel_dir}")
    print(f"Modules to process: {len(modules)}")

    # Run Step 3
    print("\n" + "=" * 80)
    print("Running Step 3...")
    print("=" * 80)

    try:
        # Initialize AI manager
        from ai_agents.agent_manager import AIAgentManager
        ai_manager = AIAgentManager()

        result = await step3.run(
            high_level_design=json.dumps(high_level_design),
            ai_manager=ai_manager,
            websocket_manager=None,
            project_id=project_id
        )

        print("\n" + "=" * 80)
        print("STEP 3 COMPLETED SUCCESSFULLY")
        print("=" * 80)

        # Show results
        circuits = result.get('circuits', [])
        print(f"\nCircuits generated: {len(circuits)}")
        for circuit_name in circuits:
            circuit_file = step3.lowlevel_dir / f"circuit_{circuit_name.lower().replace(' ', '_')}.json"
            if circuit_file.exists():
                with open(circuit_file) as f:
                    data = json.load(f)
                    circuit_data = data.get('circuit', data)
                    components = circuit_data.get('components', [])
                    nets = circuit_data.get('nets', [])
                    print(f"  ✓ {circuit_name}: {len(components)} components, {len(nets)} nets")
            else:
                print(f"  ✗ {circuit_name}: File not found")

        print(f"\nOutput path: {step3.lowlevel_dir}")

        return True

    except Exception as e:
        print(f"\n❌ STEP 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = asyncio.run(test_step3())
    sys.exit(0 if success else 1)
