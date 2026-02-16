# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Complete Circuit Workflow Manager - Production Ready
Works with mock data for testing, real AI for production
"""
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
import uuid
import os

# Import workflow steps
from workflow.step_1_gather_info import Step1InfoGathering
from workflow.step_2_high_level import Step2HighLevelDesign
from workflow.step_3_low_level import Step3LowLevel
from workflow.step_4_bom_complete import Step4BOMGeneration
from workflow.step_6_packaging import Step6FinalPackaging
from workflow.converter_runner import ConverterRunner
from utils.logger import setup_logger

logger = setup_logger(__name__)

class CircuitWorkflowComplete:
    """
    Complete workflow orchestrator - production ready
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.status = "initialized"
        self.current_step = 0
        self.total_steps = 6
        self.eta = None
        self.start_time = datetime.now()
        self.logger = logger

        # Create project output folder
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.project_folder = f"{timestamp}-project-{project_id[:8]}"

        # Use environment variable or default
        output_root = os.environ.get('OUTPUT_ROOT_DIR', 'output')
        self.output_dir = Path(output_root) / self.project_folder

        # Create folder structure
        self.lowlevel_dir = self.output_dir / "lowlevel"
        self.kicad_dir = self.output_dir / "kicad"
        self.eagle_dir = self.output_dir / "eagle"
        self.easyeda_pro_dir = self.output_dir / "easyeda_pro"
        self.schematics_dir = self.output_dir / "schematics"
        self.schematics_desc_dir = self.output_dir / "schematics_desc"
        self.bom_dir = self.output_dir / "bom"
        self.highlevel_dir = self.output_dir / "highlevel"

        # Create all directories
        for dir_path in [self.lowlevel_dir, self.kicad_dir, self.eagle_dir,
                          self.easyeda_pro_dir, self.schematics_dir,
                          self.schematics_desc_dir, self.bom_dir, self.highlevel_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # Store workflow data
        self.workflow_data = {
            "modules": [],
            "circuits": [],
            "bom": {},
            "conversions": {}
        }

        logger.info(f"Workflow initialized for project {project_id}")
        logger.info(f"Output directory: {self.output_dir}")

    def update_status(self, status: str, step: int):
        """Update workflow status"""
        self.status = status
        self.current_step = step

        # Calculate ETA
        elapsed = (datetime.now() - self.start_time).seconds
        if step > 0:
            avg_time_per_step = elapsed / step
            remaining_steps = self.total_steps - step
            eta_seconds = avg_time_per_step * remaining_steps
            self.eta = (datetime.now() + timedelta(seconds=eta_seconds)).strftime("%H:%M:%S")

    def get_progress(self) -> float:
        """Get progress percentage"""
        return (self.current_step / self.total_steps) * 100

    async def run(self, requirements: Dict[str, Any], use_mock_ai: bool = True) -> Dict[str, Any]:
        """
        Main workflow execution
        use_mock_ai: If True, uses mock data instead of real AI (for testing)
        """
        try:
            logger.info(f"Starting workflow with mock_ai={use_mock_ai}")

            # Step 1: Information Gathering
            self.update_status("Gathering Information", 1)
            gathered_info = await self.step_1_gather_info(requirements, use_mock_ai)

            # Step 2: High-Level Design
            self.update_status("Creating High-Level Design", 2)
            high_level_design = await self.step_2_high_level(gathered_info, use_mock_ai)

            # Step 3: Low-Level Circuit Design
            self.update_status("Generating Circuits", 3)
            circuits = await self.step_3_low_level(high_level_design, use_mock_ai)

            # Save circuits to lowlevel folder
            for circuit in circuits:
                self.save_circuit_to_lowlevel(circuit)

            # Step 3.5: Run Converters (MUST happen after lowlevel, before Step 4)
            logger.info("Running converters after Step 3 lowlevel generation...")
            conversion_results = await self.run_converters_after_step3()

            # Step 4: BOM Generation
            self.update_status("Generating BOM", 4)
            bom = await self.step_4_bom(circuits)

            # Step 5: Format Conversion (already done in Step 3.5)
            self.update_status("Formats Already Converted", 5)
            # conversion_results already populated from Step 3.5

            # Step 6: Final Packaging
            self.update_status("Creating Package", 6)
            package = await self.step_6_package(circuits, bom, conversion_results)

            # Complete
            self.update_status("Complete", 6)

            return {
                "success": True,
                "project_id": self.project_id,
                "output_dir": str(self.output_dir),
                "circuits": circuits,
                "bom": bom,
                "conversions": conversion_results,
                "package": package,
                "files": self.list_output_files()
            }

        except Exception as e:
            logger.error(f"Workflow error: {e}")
            self.update_status(f"Error: {str(e)}", self.current_step)
            return {
                "success": False,
                "error": str(e),
                "project_id": self.project_id
            }

    async def step_1_gather_info(self, requirements: Dict, use_mock: bool = True) -> Dict:
        """Step 1: Information Gathering"""
        if use_mock:
            # Return mock data for testing
            return {
                "requirements": requirements.get("requirements", "Test circuit"),
                "specifications": {
                    "voltage": "5V",
                    "current": "1A",
                    "components": ["resistors", "capacitors", "LEDs"]
                },
                "needs_clarification": False,
                "reply": "Requirements processed successfully"
            }

        step1 = Step1InfoGathering(self.project_id)
        return await step1.process(requirements)

    async def step_2_high_level(self, gathered_info: Dict, use_mock: bool = True) -> Dict:
        """Step 2: High-Level Design"""
        if use_mock:
            # Return mock high-level design
            return {
                "modules": [
                    {"name": "PowerSupply", "description": "5V power regulation"},
                    {"name": "LEDDriver", "description": "LED control circuit"}
                ],
                "diagrams": ["block_diagram.dot"],
                "design": "Power supply -> LED Driver -> Output"
            }

        step2 = Step2HighLevelDesign(self.project_id)
        step2.output_paths = {
            'root': str(self.output_dir),
            'highlevel': str(self.highlevel_dir),
            'lowlevel': str(self.lowlevel_dir)
        }
        return await step2.process(gathered_info)

    async def step_3_low_level(self, high_level_design: Dict, use_mock: bool = True) -> List[Dict]:
        """Step 3: Low-Level Circuit Design"""
        if use_mock:
            # Return mock circuits for testing
            return [
                {
                    "name": "PowerSupply",
                    "components": [
                        {"id": "C1", "type": "CAPACITOR", "value": "10uF", "package": "0805"},
                        {"id": "C2", "type": "CAPACITOR", "value": "100nF", "package": "0603"},
                        {"id": "U1", "type": "REGULATOR", "value": "LM7805", "package": "TO220"},
                        {"id": "R1", "type": "RESISTOR", "value": "1K", "package": "0603"}
                    ],
                    "nets": [
                        {"name": "VIN", "connections": ["U1.1", "C1.1"]},
                        {"name": "GND", "connections": ["U1.2", "C1.2", "C2.2"]},
                        {"name": "VOUT", "connections": ["U1.3", "C2.1", "R1.1"]}
                    ]
                },
                {
                    "name": "LEDDriver",
                    "components": [
                        {"id": "R2", "type": "RESISTOR", "value": "330", "package": "0603"},
                        {"id": "R3", "type": "RESISTOR", "value": "330", "package": "0603"},
                        {"id": "LED1", "type": "LED", "value": "RED", "package": "0805"},
                        {"id": "LED2", "type": "LED", "value": "GREEN", "package": "0805"},
                        {"id": "Q1", "type": "TRANSISTOR", "value": "2N2222", "package": "SOT23"}
                    ],
                    "nets": [
                        {"name": "VCC", "connections": ["R2.1", "R3.1"]},
                        {"name": "LED1_NET", "connections": ["R2.2", "LED1.1"]},
                        {"name": "LED2_NET", "connections": ["R3.2", "LED2.1"]},
                        {"name": "GND", "connections": ["LED1.2", "LED2.2", "Q1.2"]}
                    ]
                }
            ]

        step3 = Step3LowLevel(str(self.output_dir))
        result = await step3.run(json.dumps(high_level_design))
        return result.get('circuits', [])

    def save_circuit_to_lowlevel(self, circuit: Dict):
        """Save circuit to lowlevel folder"""
        circuit_name = circuit.get("name", f"circuit_{uuid.uuid4().hex[:8]}")
        filename = f"CIRCUIT_{circuit_name}.json"
        filepath = self.lowlevel_dir / filename

        with open(filepath, 'w') as f:
            json.dump(circuit, f, indent=2)

        logger.info(f"Saved circuit to {filepath}")

    async def step_4_bom(self, circuits: List[Dict]) -> Dict:
        """Step 4: BOM Generation - Using new complete implementation"""
        step4 = Step4BOMGeneration(self.project_id)
        result = await step4.process(circuits, str(self.output_dir))
        self.workflow_data['bom'] = result
        return result

    async def run_converters_after_step3(self) -> Dict:
        """Run converters immediately after Step 3 lowlevel files are created"""
        try:
            logger.info("="*60)
            logger.info("STEP 3.5: RUNNING CONVERTERS")
            logger.info("="*60)

            converter = ConverterRunner(str(self.output_dir))

            # Run all converters using the actual converter scripts
            results = await converter.run_all_converters_async()

            logger.info(f"Converters complete. Results: {list(results.keys())}")
            self.workflow_data['conversions'] = results
            return results

        except Exception as e:
            logger.error(f"Converter execution error: {e}")
            # Return empty dict but don't fail the workflow
            return {}

    async def step_5_convert(self, circuits: List[Dict]) -> Dict:
        """Step 5: Format Conversion (deprecated - converters run in Step 3.5)"""
        # This is kept for compatibility but converters now run after Step 3
        logger.info("Step 5 skipped - converters already ran after Step 3")
        return self.workflow_data.get('conversions', {})

    def _get_extension(self, format: str) -> str:
        """Get file extension for format"""
        extensions = {
            'kicad': 'kicad_sch',
            'eagle': 'sch',
            'easyeda_pro': 'epro',
            'schematics': 'txt',
            'schematics_desc': 'md'
        }
        return extensions.get(format, 'txt')

    async def step_6_package(self, circuits: List[Dict], bom: Dict, conversions: Dict) -> Dict:
        """Step 6: Final Packaging - Using new implementation"""
        step6 = Step6FinalPackaging(self.project_id)
        result = await step6.process(
            str(self.output_dir),
            circuits,
            bom,
            conversions
        )
        return result

    def list_output_files(self) -> Dict[str, List[str]]:
        """List all output files organized by category"""
        files = {}

        for subdir in self.output_dir.iterdir():
            if subdir.is_dir():
                category_files = []
                for file_path in subdir.glob('*'):
                    if file_path.is_file():
                        category_files.append(file_path.name)
                if category_files:
                    files[subdir.name] = sorted(category_files)

        return files