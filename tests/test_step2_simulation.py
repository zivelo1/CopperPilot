#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 2 Simulation Test
Tests high-level design generation with real Step 1 output
"""

import asyncio
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from workflow.step_2_high_level import Step2HighLevelDesign
from ai_agents.agent_manager import AIAgentManager
from workflow.state_manager import WorkflowStateManager

async def test_step2():
    """Test Step 2 with real inputs from latest run"""

    print("=" * 80)
    print("STEP 2 SIMULATION TEST")
    print("=" * 80)

    # Step 1 output from logs/runs/20251005-114147-e5390dec/steps/step1_info_gathering.log
    step1_output = {
        'devicePurpose': 'Adaptive amplifier ultrasonic transducer driver with 2 independent resonance circuits for piezoelectric ultrasonic transducers testing, capable of autonomous resonance tracking and remote control',
        'generalSpecifications': {
            'total_channels': '2',
            'channel1_nominal_frequency': '50kHz',
            'channel1_drive_power': '200W',
            'channel1_drive_voltage': '360Vpp',
            'channel1_impedance_fm': '48.23Ω to 994.86mΩ',
            'channel1_impedance_fn': '110.56Ω to 19698Ω',
            'channel1_fm_range': '39.26kHz to 47.32kHz',
            'channel1_fn_range': '39.45kHz to 48.92kHz',
            'channel1_C0': '28.80nF to 40.90nF',
            'channel1_Cp': '44.57nF',
            'channel2_nominal_frequency': '1.5MHz',
            'channel2_drive_power': '158W',
            'channel2_drive_voltage': '280Vpp',
            'channel2_impedance_fm': '1.37Ω to 598.62mΩ',
            'channel2_impedance_fn': '19.42Ω to 4146.2Ω',
            'channel2_fm_range': '0.94MHz to 1.29MHz',
            'channel2_fn_range': '1.37MHz to 1.51MHz',
            'channel2_C0': '6.34nF to 17.56nF',
            'channel2_Cp': '26.34nF to 31.97nF',
            'mains_input': '220V 60Hz with fuse and ground',
            'output_connector': 'BNC 75Ω preferred, 50Ω acceptable',
            'max_transducer_rating': '470Vpp',
            'internal_signal_generation': 'DDS, MCU, or alternative for autonomous operation',
            'frequency_control': 'real-time adaptive frequency adjustment, PLL or digital',
            'resonance_tracking': 'automatic phase-based resonance detection and tracking, target 0° phase',
            'telemetry': 'real-time frequency, phase angle, voltage, current, power readouts and logging',
            'remote_control': 'PC-based control via USB preferred, UART or Ethernet acceptable',
            'manual_override': 'disable automatic mode, manual frequency setting',
            'waveform_types': 'sine, square, triangle, sawtooth, pulse',
            'signal_quality': 'ultra-low noise, lowest possible THD and THD+N, good SNR',
            'operation_mode': 'independent or simultaneous channel operation',
            'modularity': 'modular channels connecting to main board',
            'cooling': 'heatsinks or fans as needed',
            'duty_cycle': '30-60 minutes continuous per run',
            'controls_per_channel': 'on/off switch, gain control knob, power LED',
            'shared_controls': 'main power switch with LED, optional master gain, optional voltage meter',
            'optional_external_input': 'BNC per channel for diagnostics',
            'safety': 'basic protection circuitry, no formal certifications required',
            'form_factor': 'bench-top tabletop device',
            'component_preference': 'off-the-shelf, quality-cost balance',
            'project_scope': 'MVP/POC proof of concept',
            'tolerance': '±10% per frequency, capacitance, impedance'
        }
    }

    # Initialize managers
    ai_manager = AIAgentManager()

    # Initialize Step 2
    step2 = Step2HighLevelDesign(
        project_id='20251005-114147-e5390dec'
    )

    # Set output paths (normally done by workflow)
    from pathlib import Path
    output_base = Path('output') / step2.project_id
    step2.output_paths = {
        'highlevel': output_base / 'highlevel',
        'lowlevel': output_base / 'lowlevel'
    }
    step2.output_paths['highlevel'].mkdir(parents=True, exist_ok=True)

    print(f"\nProject ID: {step2.project_id}")
    print(f"Output dir: {step2.output_paths['highlevel']}")

    # Run Step 2
    print("\n" + "=" * 80)
    print("Running Step 2...")
    print("=" * 80)

    try:
        result = await step2.process(
            step1_output=step1_output
        )

        print("\n" + "=" * 80)
        print("STEP 2 COMPLETED SUCCESSFULLY")
        print("=" * 80)

        # Show results
        print(f"\nModules generated: {len(result.get('modules', []))}")
        for i, module in enumerate(result.get('modules', []), 1):
            print(f"  {i}. {module.get('name', 'Unknown')}")

        print(f"\nDiagrams generated: {len(result.get('diagrams', []))}")
        for diagram in result.get('diagrams', []):
            print(f"  - {diagram.get('filename')}.png")

        print(f"\nOutput path: {step2.output_paths['highlevel']}")

        return True

    except Exception as e:
        print(f"\n❌ STEP 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = asyncio.run(test_step2())
    sys.exit(0 if success else 1)
