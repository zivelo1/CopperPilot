# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Main Circuit Workflow Manager
Coordinates the entire circuit generation process
"""
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
import uuid

from server.config import config
from utils.logger import WorkflowLogger, DebugRecorder, ComprehensiveLogger
from utils.conversation_logger import ConversationLogger
from utils.project_manager import project_manager
from utils.enhanced_logger import EnhancedLogger
from ai_agents.agent_manager import ai_manager, APIHealthCheckError
# Set enhanced logger for AI manager
ai_manager.enhanced_logger = None  # Will be set per workflow

# Import the new workflow steps
from .step_1_gather_info import Step1InfoGathering
from .step_1_1_requirements_archiver import Step11RequirementsArchiver  # NEW: Requirements archiver for LLM training
from .step_2_high_level import Step2HighLevelDesign
from .step_3_low_level import Step3LowLevel
from .step_4_bom import Step4BOMGeneration
from .converter_runner import ConverterRunner
from .step_5_quality_assurance import Step5QualityAssurance
from .step_6_packaging import Step6FinalPackaging
from .step_2_5_project_summary import Step25ProjectSummary

class CircuitWorkflow:
    """
    Main workflow orchestrator - replaces N8N workflow
    """

    def __init__(self, project_id: str, websocket_manager=None):
        self.project_id = project_id
        self.status = "initialized"
        self.current_step = 0
        self.total_steps = 7  # Updated: 1-Info, 2-HighLevel, 3-Circuits, 4-Conversion, 5-BOM, 6-QA, 7-Package
        self.eta = None
        self.start_time = datetime.now()
        self.websocket_manager = websocket_manager

        # Create project with centralized manager
        self.project_info = project_manager.create_project(project_id)
        self.project_folder = self.project_info['project_folder']

        # DON'T create directories yet - wait for Step 2
        self.output_dir = None
        self.highlevel_dir = None
        self.lowlevel_dir = None
        self.kicad_dir = None
        self.eagle_dir = None
        self.easyeda_dir = None
        self.easyeda_pro_dir = None
        self.schematics_dir = None
        self.schematics_desc_dir = None
        self.bom_dir = None
        self.project_info_dir = None

        # Initialize enhanced logger
        self.enhanced_logger = EnhancedLogger(
            self.project_folder,
            self.project_info['logs_dir']
        )
        # Set enhanced logger for AI manager
        from ai_agents.agent_manager import ai_manager as global_ai_manager
        global_ai_manager.enhanced_logger = self.enhanced_logger

        # Keep existing loggers for backward compatibility
        self.comprehensive_logger = ComprehensiveLogger(project_id)
        self.logger = WorkflowLogger(project_id)
        self.recorder = DebugRecorder(project_id)

        # Store workflow data
        self.workflow_data = {
            "modules": [],
            "circuits": [],
            "components_csv": None,
            "design_json": None
        }

        self.enhanced_logger.log(f"Workflow initialized for project {project_id} (folder: {self.project_folder})")
        self.comprehensive_logger.log_step("step1_info", "Workflow initialized, waiting for user input")

        # Initialize conversation logger
        self.conversation_logger = ConversationLogger(project_id)

        # State for clarification handling
        self.state = {
            'needs_clarification': False,
            'clarification_questions': '',
            'gathered_info': None,
            'clarification_history': []
        }

    async def update_status(self, status: str, step: int):
        """Update workflow status and send WebSocket update"""
        self.status = status
        self.current_step = step

        # Log status update
        self.comprehensive_logger.log_step("main", f"Status: {status} | Step: {step}/{self.total_steps}")

        # Calculate ETA
        elapsed = (datetime.now() - self.start_time).seconds
        if step > 0:
            avg_time_per_step = elapsed / step
            remaining_steps = self.total_steps - step
            eta_seconds = avg_time_per_step * remaining_steps
            self.eta = str(timedelta(seconds=int(eta_seconds)))

        # Send WebSocket update if manager is available
        if self.websocket_manager:
            try:
                await self.websocket_manager.send_update(self.project_id, {
                    "type": "progress",
                    "status": status,
                    "step": step,
                    "progress": self.get_progress(),
                    "eta": self.eta
                })
            except Exception as e:
                self.logger.logger.warning(f"Failed to send WebSocket update: {e}")

    def get_progress(self) -> float:
        """Get progress percentage"""
        return (self.current_step / self.total_steps) * 100

    def get_recent_logs(self, count: int = 10) -> List[Dict]:
        """Get recent log entries"""
        all_logs = self.logger.get_step_logs()
        return sorted(all_logs, key=lambda x: x.get('timestamp', ''), reverse=True)[:count]

    async def run(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main workflow execution
        """
        try:
            self.logger.log_input("workflow_start", requirements)

            # Log user input to conversation logger
            self.conversation_logger.log_user_input(
                requirements.get("requirements", ""),
                requirements.get("pdf_content"),
                bool(requirements.get("image_content"))
            )
            # Persist original requirements text for Step 2.5 summary (human-facing PDF)
            try:
                self.state['original_requirements_text'] = requirements.get('requirements', requirements.get('chatInput', ''))
            except Exception:
                self.state['original_requirements_text'] = ''

            # CRITICAL FIX: Persist PDF content for clarification loop
            # The PDF must be available if the AI needs to ask clarification questions
            # Otherwise the AI cannot reference the document when user responds
            if requirements.get('pdf_content'):
                self.state['original_pdf_content'] = requirements.get('pdf_content')
                self.logger.logger.info(f"PDF content persisted in state: {len(requirements.get('pdf_content', b''))} bytes")
            if requirements.get('files'):
                self.state['original_files'] = requirements.get('files')
                self.logger.logger.info(f"Files persisted in state: {len(requirements.get('files', []))} files")

            # ================================================================
            # PRE-FLIGHT: API health check (Fix 1 — Forensic Fix Plan)
            # ================================================================
            # Verifies API key validity and credit availability BEFORE any
            # expensive operations.  Raises APIHealthCheckError for fatal
            # errors (CREDIT_EXHAUSTED, AUTH_FAILED) which is caught by the
            # outer try/except and returned as a workflow failure.
            await self.update_status("Pre-flight checks", 0)
            try:
                await ai_manager.test_connection()
            except APIHealthCheckError as hce:
                self.logger.logger.error(f"Pre-flight API check failed: {hce}")
                self.enhanced_logger.log(
                    f"WORKFLOW ABORTED — API pre-flight failed [{hce.category}]: {hce.detail}"
                )
                duration = (datetime.now() - self.start_time).total_seconds()
                self.enhanced_logger.log_workflow_complete(False, duration, "N/A")
                return {
                    "success": False,
                    "error": (
                        f"Workflow aborted before Step 1: API pre-flight check failed "
                        f"[{hce.category}]. {hce.detail}"
                    ),
                    "project_id": self.project_id,
                }

            # Step 1: Information Gathering
            await self.update_status("Gathering Information", 1)
            gathered_info = await self.step_1_gather_info(requirements)

            # Check if clarification is needed
            if gathered_info.get('needs_clarification', False):
                # Save state for continuation
                self.state['needs_clarification'] = True
                self.state['clarification_questions'] = gathered_info.get('reply', '')
                self.state['gathered_info'] = gathered_info

                # Return clarification request to user
                await self.update_status("Needs Clarification", 1)
                self.logger.logger.info("Workflow paused - clarification needed from user")
                return {
                    "success": True,
                    "needs_clarification": True,
                    "questions": gathered_info.get('reply', ''),
                    "project_id": self.project_id,
                    "message": "Please provide additional information to continue"
                }

            # CRITICAL FIX: Save gathered_info to state so Step 3 can access it
            # This was missing - gathered_info was only saved in clarification branch!
            self.state['gathered_info'] = gathered_info

            # Step 2: High-Level Design
            await self.update_status("Creating High-Level Design", 2)
            high_level_design = await self.step_2_high_level(gathered_info)

            # Step 3: Low-Level Circuit Design (THE CRITICAL STEP)
            await self.update_status("Generating Circuits", 3)
            step3_result = await self.step_3_low_level(high_level_design)

            # Fix 3 (Forensic Fix Plan): step_3_low_level now returns the full
            # result dict which includes ``success``, ``quality_summary``, etc.
            # We need the circuits list AND the success flag.
            circuits = step3_result if isinstance(step3_result, list) else step3_result.get('circuits', step3_result) if isinstance(step3_result, dict) else step3_result

            # Determine Step 3 success from the result
            step3_success = True
            step3_quality = {}
            if isinstance(step3_result, dict):
                step3_success = step3_result.get('success', True)
                step3_quality = step3_result.get('quality_summary', {})
                # Extract circuits list for downstream steps
                if 'circuits' in step3_result:
                    circuits = step3_result['circuits']

            if not step3_success:
                self.logger.logger.error(
                    f"Step 3 quality gate FAILED: {step3_quality}"
                )

            # Note: Step 3 already saves circuits with proper names in lowlevel folder
            # No need to duplicate save here

            # Step 3.5: Run Converters (CRITICAL - Must run before BOM!)
            await self.update_status("Format Conversion", 4)
            self.logger.log_step("step_3_converters", "status", "Starting converters after Step 3 completion...")
            conversion_results = await self.run_converters_after_step3()
            self.logger.log_step("step_3_converters", "status", f"Converters completed: {len(conversion_results.get('results', {}))} formats generated")

            # Step 5: BOM Generation
            await self.update_status("BOM & Parts Selection", 5)
            circuit_list = circuits if isinstance(circuits, list) else []
            bom = await self.step_4_bom(circuit_list)

            # Step 6: Quality Assurance (forensic validators)
            await self.update_status("Quality Assurance", 6)
            qa_results = await self.step_5_qa()

            # Step 7: Packaging (ZIP + manifest)
            await self.update_status("Final Packaging", 7)
            package_results = await self.step_6_package(circuit_list, bom, conversion_results)

            # ================================================================
            # Fix 3 (Forensic Fix Plan): Honest completion reporting
            # ================================================================
            # Workflow success = Step 3 quality gate passed
            # (other steps may have their own issues but lowlevel is the foundation)
            workflow_success = step3_success
            status_label = "Complete" if workflow_success else "Completed with issues"
            await self.update_status(status_label, 7)

            self.logger.log_output("workflow_complete", {
                "project_id": self.project_id,
                "output_dir": str(self.output_dir),
                "circuits_generated": len(circuit_list),
                "formats_converted": len(conversion_results),
                "step3_success": step3_success,
                "step3_quality": step3_quality,
                "qa_success": qa_results.get("success") if isinstance(qa_results, dict) else None,
                "package": package_results if isinstance(package_results, dict) else {}
            })

            # Log workflow completion with ACTUAL success status
            duration = (datetime.now() - self.start_time).total_seconds()
            total_cost = ai_manager.get_total_cost()
            self.enhanced_logger.log_workflow_complete(workflow_success, duration, str(self.output_dir))

            # Print cost summary to terminal
            print("\n" + "=" * 60)
            if workflow_success:
                print("WORKFLOW COST SUMMARY")
            else:
                print("WORKFLOW COMPLETED WITH ISSUES")
                if step3_quality:
                    fb = step3_quality.get('fallback_modules', 0)
                    total = step3_quality.get('total_modules', 0)
                    print(f"   Low-Level Quality: {total - fb}/{total} modules AI-designed")
                    if step3_quality.get('abort_reason'):
                        print(f"   Abort Reason: {step3_quality['abort_reason']}")
            print("=" * 60)
            print(f"   Total AI API Cost: ${total_cost:.4f}")
            print(f"   Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
            print(f"   Circuits Generated: {len(circuit_list)}")
            print(f"   Output Directory: {self.output_dir}")
            print("=" * 60 + "\n")

            self.logger.logger.info(
                f"WORKFLOW {'COMPLETE' if workflow_success else 'COMPLETED WITH ISSUES'} "
                f"- Cost: ${total_cost:.4f}, Duration: {duration:.1f}s"
            )

            return {
                "success": workflow_success,
                "project_id": self.project_id,
                "output_dir": str(self.output_dir),
                "circuits": circuit_list,
                "conversions": conversion_results,
                "qa": qa_results,
                "step3_quality": step3_quality,
                "total_cost": total_cost,
                "duration_seconds": duration
            }

        except Exception as e:
            self.logger.log_error("workflow", e)
            # Log the full error internally but only send a generic message to user
            self.comprehensive_logger.error(f"Workflow error: {str(e)}", exc_info=True)
            await self.update_status("An error occurred. Please check the logs.", self.current_step)
            return {
                "success": False,
                "error": "An error occurred during circuit generation. Our team has been notified.",
                "project_id": self.project_id
            }

    async def step_1_gather_info(self, requirements: Dict) -> Dict:
        """
        Step 1: Information Gathering - Using new ported implementation

        This step processes user requirements and extracts specifications using AI.
        After Step 1 completes, Step 1.1 automatically archives the requirements
        in multiple formats for future LLM training and analysis.
        """
        self.logger.log_input("step_1_gather_info", requirements)

        # Use the new Step 1 implementation
        step1 = Step1InfoGathering(self.project_id)
        step1.enhanced_logger = self.enhanced_logger
        result = await step1.process(requirements)

        # Step 1.1: Archive requirements for LLM training (NEW)
        # This runs automatically after Step 1 to save requirements in multiple formats
        try:
            self.logger.logger.info("Starting Step 1.1: Requirements Archiver")
            archiver = Step11RequirementsArchiver(self.project_id, self.project_folder)
            archive_result = await archiver.process(result, requirements)

            if archive_result.get('success'):
                self.logger.logger.info(
                    f"Step 1.1 completed: Generated {len(archive_result.get('files_generated', {}))} format(s) "
                    f"for LLM training"
                )
                # Store archive info for potential use later
                result['archive_info'] = archive_result
            else:
                self.logger.logger.warning(
                    f"Step 1.1 failed (non-critical): {archive_result.get('error', 'Unknown error')}"
                )
        except Exception as e:
            # Step 1.1 is non-critical - log error but continue workflow
            self.logger.logger.error(f"Step 1.1 archiver error (non-critical): {str(e)}")

        # Check if clarification is needed
        if result.get('needs_clarification', False):
            # In a real implementation, this would handle the clarification loop
            # For now, we'll just return the result
            self.logger.logger.warning("Step 1 needs clarification from user")

        self.logger.log_output("step_1_gather_info", result)
        return result

    async def step_2_high_level(self, gathered_info: Dict) -> Dict:
        """Step 2: High-Level Design - Using new ported implementation"""
        self.logger.log_input("step_2_high_level", gathered_info)

        # CREATE OUTPUT FOLDER NOW - ONLY ONCE using project manager!
        if not self.output_dir:
            # Use project manager to ensure directories
            dirs = project_manager.ensure_directories(self.project_id)

            # Set all directory paths
            self.output_dir = dirs['output_root']
            self.highlevel_dir = dirs['highlevel']
            self.lowlevel_dir = dirs['lowlevel']
            self.kicad_dir = dirs['kicad']
            self.eagle_dir = dirs['eagle']
            self.easyeda_pro_dir = dirs['easyeda_pro']
            self.schematics_dir = dirs['schematics']
            self.schematics_desc_dir = dirs['schematics_desc']
            self.bom_dir = dirs['bom']
            self.project_info_dir = dirs['project_info']

            self.enhanced_logger.log(f"Created output directory: {self.output_dir}")
            self.enhanced_logger.log_step('step2_high_level', f"Output directories created at: {self.output_dir}")

        # Use the new Step 2 implementation (TC #78: pass websocket_manager for progress updates)
        step2 = Step2HighLevelDesign(self.project_id, websocket_manager=self.websocket_manager)
        step2.enhanced_logger = self.enhanced_logger

        # Update output paths to use our created directories
        step2.output_paths = {
            'root': str(self.output_dir),
            'highlevel': str(self.highlevel_dir),
            'lowlevel': str(self.lowlevel_dir),
            'kicad': str(self.kicad_dir),
            'easyeda_pro': str(self.easyeda_pro_dir),
            'eagle': str(self.eagle_dir),
            'schematics': str(self.schematics_dir),
            'schematics_desc': str(self.schematics_desc_dir),
            'bom': str(self.bom_dir)
        }

        result = await step2.process(gathered_info)

        self.logger.log_output("step_2_high_level", result)

        # Step 2.5: Generate human-friendly Project Summary PDF under project_info
        try:
            await self.update_status("Creating Project Summary", 2.5)
            summary = Step25ProjectSummary(
                project_id=self.project_id,
                project_folder=self.project_folder,
                output_root=self.output_dir,
                project_info_dir=self.project_info_dir,
                highlevel_dir=self.highlevel_dir
            )
            # Prefer raw text input; fallback to chatInput
            original_text = self.state.get('original_requirements_text', '')
            if not original_text:
                original_text = gathered_info.get('original_text', '') or ''
            summary_result = await summary.generate(
                user_requirements_text=original_text,
                step1_output=gathered_info,
                step2_output=result
            )
            self.workflow_data['project_summary'] = summary_result
        except Exception as e:
            # Non-fatal: continue even if summary generation fails
            self.logger.logger.warning(f"Step 2.5 (Project Summary) failed: {e}")

        return result

    async def step_3_low_level(self, high_level_design: Dict) -> Dict:
        """
        Step 3: Low-Level Circuit Design
        THIS IS THE CRITICAL STEP - Now using complete ported implementation

        Enhanced with GENERIC component rating validation (December 2025):
        - Passes requirements text to Step 3 for component rating extraction
        - Validates all generated circuits against extracted requirements
        - Works with ANY circuit type (low/high voltage, power, signal, etc.)

        Returns:
            Full result dict with keys: success, circuits, quality_summary, etc.
        """
        self.logger.log_input("step_3_low_level", high_level_design)

        # Import the complete Step 3 implementation
        from workflow.step_3_low_level import Step3LowLevel

        # GENERIC: Extract requirements text for component rating validation
        # This works with ANY circuit type - the extractor analyzes the text dynamically
        # CRITICAL FIX: Include PARSED specs from Step 1, not just raw user text
        requirements_text = self.state.get('original_requirements_text', '')

        # Get gathered_info which contains AI-extracted specs from Step 1
        # Use 'or {}' to handle case where key exists but value is None
        gathered_info = self.state.get('gathered_info') or {}

        # DEBUG: Log what we got from state
        self.logger.logger.info(f"[Step 3] gathered_info keys: {list(gathered_info.keys()) if gathered_info else 'EMPTY'}")

        # If we have parsed specifications, convert them to text for the extractor
        # This ensures electrical specs from PDFs are available for validation
        # Step 1 returns specs in: facts.generalSpecifications
        specs = {}

        # Primary location: facts.generalSpecifications (from Step 1)
        facts = gathered_info.get('facts') or {}
        specs = facts.get('generalSpecifications') or {}
        self.logger.logger.info(f"[Step 3] facts.generalSpecifications: {len(specs)} items")

        # Fallback: direct specifications key
        if not specs:
            specs = gathered_info.get('specifications') or {}
            if specs:
                self.logger.logger.info(f"[Step 3] Using direct 'specifications': {len(specs)} items")

        # Fallback: complete_facts.generalSpecifications
        if not specs:
            complete_facts = gathered_info.get('complete_facts') or {}
            specs = complete_facts.get('generalSpecifications') or {}
            if specs:
                self.logger.logger.info(f"[Step 3] Using complete_facts.generalSpecifications: {len(specs)} items")

        if specs:
            # Convert structured specs to searchable text
            spec_lines = []
            for key, value in specs.items():
                if value:  # Skip empty values
                    # Convert key from snake_case to readable format
                    readable_key = key.replace('_', ' ').title()
                    spec_lines.append(f"{readable_key}: {value}")

            # Append specs to requirements text for extractor to find voltage/power values
            if spec_lines:
                spec_text = "\n".join(spec_lines)
                requirements_text = f"{requirements_text}\n\n=== EXTRACTED SPECIFICATIONS ===\n{spec_text}"
                self.logger.logger.info(f"Added {len(spec_lines)} parsed specs to requirements text for rating validation")

        if not requirements_text:
            requirements_text = gathered_info.get('original_text', '') or gathered_info.get('requirements', '')

        # Create Step 3 processor with requirements for validation
        step3 = Step3LowLevel(str(self.output_dir), requirements_text=requirements_text)
        step3.enhanced_logger = self.enhanced_logger

        # Extract modules from high_level_design output
        if isinstance(high_level_design, dict):
            # Extract modules from Step 2 output
            modules = high_level_design.get('modules', [])
            circuit_name = high_level_design.get('designParameters', {}).get('devicePurpose', 'Circuit')

            # Create the module list structure that Step 3 expects
            module_list = {
                'modules': modules,
                'circuitName': circuit_name
            }
            high_level_text = json.dumps(module_list)
        else:
            high_level_text = high_level_design
        
        # Run the complete Step 3 workflow with WebSocket support
        result = await step3.run(high_level_text, ai_manager, self.websocket_manager, self.project_id)

        # Extract circuits
        circuits = result.get('circuits', [])

        # Store results in workflow data
        self.workflow_data['modules'] = result.get('results', [])
        self.workflow_data['circuits'] = circuits
        self.workflow_data['design_json'] = result.get('summary', {})

        self.logger.log_output("step_3_low_level", {
            "circuits": circuits,
            "module_count": len(circuits),
            "summary": result.get('summary', {}),
            "success": result.get('success', True),
            "quality_summary": result.get('quality_summary', {}),
        })

        # Return the FULL result dict (not just circuits) so the caller can
        # inspect success, quality_summary, etc. (Fix 3)
        return result
    
    def save_circuit_to_lowlevel(self, circuit: Dict):
        """Save circuit to lowlevel folder"""
        circuit_name = circuit.get("name", f"circuit_{uuid.uuid4().hex[:8]}")
        filename = f"CIRCUIT_{circuit_name}.json"
        filepath = self.lowlevel_dir / filename

        with open(filepath, 'w') as f:
            json.dump(circuit, f, indent=2)

        self.logger.logger.info(f"Saved circuit to {filepath}")

    async def step_4_bom(self, circuits: List[Dict]) -> Dict:
        """Step 4: BOM Generation - Using new ported implementation"""
        self.logger.log_input("step_4_bom", {"circuit_count": len(circuits)})

        # Send WebSocket notification that BOM step is starting
        if self.websocket_manager:
            try:
                await self.websocket_manager.send_update(self.project_id, {
                    "type": "step_progress",
                    "step": 4,
                    "step_name": "BOM & Parts Selection",
                    "status": "in_progress",
                    "message": f"Processing {len(circuits)} circuits for BOM generation..."
                })
            except Exception as e:
                self.logger.logger.debug(f"Failed to send BOM start notification: {e}")

        # Use the new Step 4 implementation (pass websocket manager for progress updates)
        step4 = Step4BOMGeneration(self.project_id, websocket_manager=self.websocket_manager)
        step4.enhanced_logger = self.enhanced_logger

        # Process circuits and generate BOM
        result = await step4.process(circuits, str(self.bom_dir))

        # Send WebSocket notification that BOM step is complete
        if self.websocket_manager:
            try:
                total_parts = result.get('total_components', 0) if isinstance(result, dict) else 0
                await self.websocket_manager.send_update(self.project_id, {
                    "type": "step_progress",
                    "step": 4,
                    "step_name": "BOM & Parts Selection",
                    "status": "completed",
                    "message": f"BOM generated with {total_parts} components"
                })
            except Exception as e:
                self.logger.logger.debug(f"Failed to send BOM complete notification: {e}")

        self.logger.log_output("step_4_bom", result)
        return result

    async def continue_with_clarification(self, clarification_data: Dict) -> Dict:
        """
        Continue workflow after receiving clarification from user
        """
        try:
            # Ensure clarification_history exists (defensive programming)
            # GENERIC FIX: Initialize if missing to handle any state corruption
            if 'clarification_history' not in self.state:
                self.state['clarification_history'] = []

            # Add clarification to history
            self.state['clarification_history'].append({
                'timestamp': datetime.now().isoformat(),
                'response': clarification_data.get('requirements', '')
            })

            # Combine previous info with clarification
            # CRITICAL FIX: Include original PDF content so AI can reference the document
            # when processing user's clarification responses
            combined_input = {
                'requirements': clarification_data.get('requirements', ''),
                'chatInput': clarification_data.get('requirements', ''),
                'messages': self.state.get('clarification_history', []),
                'previous_facts': self.state.get('gathered_info', {}).get('facts', {}),
                # Include PDF content from original submission
                'pdf_content': self.state.get('original_pdf_content'),
                'files': self.state.get('original_files', [])
            }

            # Log PDF inclusion for debugging
            if combined_input.get('pdf_content'):
                self.logger.logger.info(f"PDF content included in clarification: {len(combined_input['pdf_content'])} bytes")
            else:
                self.logger.logger.warning("No PDF content available for clarification - AI cannot reference original document")

            # PRE-FLIGHT: API health check (same as primary run path)
            try:
                await ai_manager.test_connection()
            except APIHealthCheckError as hce:
                self.logger.logger.error(f"Pre-flight API check failed: {hce}")
                duration = (datetime.now() - self.start_time).total_seconds()
                self.enhanced_logger.log_workflow_complete(False, duration, "N/A")
                return {
                    "success": False,
                    "error": (
                        f"Workflow aborted: API pre-flight check failed "
                        f"[{hce.category}]. {hce.detail}"
                    ),
                    "project_id": self.project_id,
                }

            # Re-run Step 1 with additional information
            await self.update_status("Processing Clarification", 1)
            gathered_info = await self.step_1_gather_info(combined_input)

            # Check if still needs more clarification
            if gathered_info.get('needs_clarification', False):
                # Update state
                self.state['needs_clarification'] = True
                self.state['clarification_questions'] = gathered_info.get('reply', '')
                self.state['gathered_info'] = gathered_info

                return {
                    "success": True,
                    "needs_clarification": True,
                    "questions": gathered_info.get('reply', ''),
                    "project_id": self.project_id,
                    "message": "Additional information still needed"
                }

            # Information complete, continue with workflow
            self.state['needs_clarification'] = False
            self.state['gathered_info'] = gathered_info

            # Continue with Step 2: High-Level Design
            await self.update_status("Creating High-Level Design", 2)
            high_level_design = await self.step_2_high_level(gathered_info)

            # Step 3: Low-Level Circuit Design
            await self.update_status("Generating Circuits", 3)
            step3_result = await self.step_3_low_level(high_level_design)

            # Fix 3: Extract success and quality info
            step3_success = True
            step3_quality = {}
            circuits = step3_result
            if isinstance(step3_result, dict):
                step3_success = step3_result.get('success', True)
                step3_quality = step3_result.get('quality_summary', {})
                circuits = step3_result.get('circuits', [])

            circuit_list = circuits if isinstance(circuits, list) else []

            # Step 4: Format Conversion
            await self.update_status("Format Conversion", 4)
            conversion_results = await self.run_converters_after_step3()

            # Step 5: BOM Generation
            await self.update_status("BOM & Parts Selection", 5)
            bom = await self.step_4_bom(circuit_list)

            # Step 6: Quality Assurance
            await self.update_status("Quality Assurance", 6)
            qa_results = await self.step_5_qa()

            # Step 7: Packaging
            await self.update_status("Final Packaging", 7)
            package_results = await self.step_6_package(circuit_list, bom, conversion_results)

            # Fix 3: Honest completion reporting
            workflow_success = step3_success
            status_label = "Complete" if workflow_success else "Completed with issues"
            await self.update_status(status_label, 7)

            self.logger.log_output("workflow_complete", {
                "project_id": self.project_id,
                "output_dir": str(self.output_dir),
                "circuits_generated": len(circuit_list),
                "formats_converted": len(conversion_results),
                "step3_success": step3_success,
            })

            duration = (datetime.now() - self.start_time).total_seconds()
            total_cost = ai_manager.get_total_cost()
            self.enhanced_logger.log_workflow_complete(workflow_success, duration, str(self.output_dir))

            # Print cost summary to terminal
            print("\n" + "=" * 60)
            if workflow_success:
                print("WORKFLOW COST SUMMARY")
            else:
                print("WORKFLOW COMPLETED WITH ISSUES")
                if step3_quality:
                    fb = step3_quality.get('fallback_modules', 0)
                    total = step3_quality.get('total_modules', 0)
                    print(f"   Low-Level Quality: {total - fb}/{total} modules AI-designed")
            print("=" * 60)
            print(f"   Total AI API Cost: ${total_cost:.4f}")
            print(f"   Duration: {duration:.1f} seconds ({duration/60:.1f} minutes)")
            print(f"   Circuits Generated: {len(circuit_list)}")
            print(f"   Output Directory: {self.output_dir}")
            print("=" * 60 + "\n")

            self.logger.logger.info(
                f"WORKFLOW {'COMPLETE' if workflow_success else 'COMPLETED WITH ISSUES'} "
                f"- Cost: ${total_cost:.4f}, Duration: {duration:.1f}s"
            )

            return {
                "success": workflow_success,
                "project_id": self.project_id,
                "output_dir": str(self.output_dir),
                "circuits": circuit_list,
                "conversions": conversion_results,
                "qa": qa_results,
                "step3_quality": step3_quality,
                "total_cost": total_cost,
                "duration_seconds": duration
            }

        except Exception as e:
            self.logger.log_error("continue_workflow", e)
            # Log the full error internally but only send a generic message to user
            self.comprehensive_logger.error(f"Continue workflow error: {str(e)}", exc_info=True)
            await self.update_status("An error occurred. Please check the logs.", self.current_step)
            return {
                "success": False,
                "error": "An error occurred during circuit generation. Our team has been notified.",
                "project_id": self.project_id
            }

    async def run_converters_after_step3(self) -> Dict:
        """
        Run converters immediately after Step 3 lowlevel files are created
        This MUST happen before Step 4 BOM generation
        """
        self.logger.log_input("run_converters_after_step3", {"project_folder": self.project_folder})

        try:
            self.logger.log_step("step_3_converters", "divider", "="*60)
            self.logger.log_step("step_3_converters", "header", "STEP 3.5: RUNNING CONVERTERS")
            self.logger.log_step("step_3_converters", "divider", "="*60)

            # Use the ConverterRunner to run all converters
            converter = ConverterRunner(self.project_folder)

            # Run all converters in parallel using the actual scripts
            results = await converter.run_all_converters_async()

            self.logger.log_step("step_3_converters", "complete", f"Converters complete. Results: {list(results.get('results', {}).keys())}")
            self.logger.log_output("run_converters_after_step3", results)

            return results

        except Exception as e:
            self.logger.log_error(f"Converter execution error: {e}")
            # Return empty dict but don't fail the workflow
            return {}

    async def step_5_qa(self) -> Dict:
        """Step 5: Quality Assurance — run forensic validations and summarize results."""
        self.logger.log_input("step_5_qa", {
            "output_dir": str(self.output_dir)
        })

        # Send WebSocket notification that QA step is starting
        if self.websocket_manager:
            try:
                await self.websocket_manager.send_update(self.project_id, {
                    "type": "step_progress",
                    "step": 5,
                    "step_name": "Quality Assurance",
                    "status": "in_progress",
                    "message": "Running quality assurance validations..."
                })
            except Exception as e:
                self.logger.logger.debug(f"Failed to send QA start notification: {e}")

        try:
            qa = Step5QualityAssurance(self.project_id, self.websocket_manager)
            result = await qa.process(str(self.output_dir))
            # Save QA summary to workflow data
            self.workflow_data['qa'] = result

            # Send WebSocket notification that QA step is complete
            if self.websocket_manager:
                try:
                    success = result.get('success', False) if isinstance(result, dict) else False
                    await self.websocket_manager.send_update(self.project_id, {
                        "type": "step_progress",
                        "step": 5,
                        "step_name": "Quality Assurance",
                        "status": "completed",
                        "message": f"QA {'passed' if success else 'completed with issues'}"
                    })
                except Exception as e:
                    self.logger.logger.debug(f"Failed to send QA complete notification: {e}")

            self.logger.log_output("step_5_qa", result)
            return result
        except Exception as e:
            self.logger.log_error("step_5_qa", e)
            return {"success": False, "error": str(e)}

    async def step_6_package(self, circuits: List[Dict], bom: Dict, conversions: Dict) -> Dict:
        """Step 6: Final Packaging — ZIP project and expose for download."""
        self.logger.log_input("step_6_package", {
            "circuit_count": len(circuits),
            "conversion_count": len(conversions)
        })

        # Send WebSocket notification that packaging step is starting
        if self.websocket_manager:
            try:
                await self.websocket_manager.send_update(self.project_id, {
                    "type": "step_progress",
                    "step": 6,
                    "step_name": "Final Packaging",
                    "status": "in_progress",
                    "message": "Creating final package..."
                })
            except Exception as e:
                self.logger.logger.debug(f"Failed to send packaging start notification: {e}")

        try:
            packer = Step6FinalPackaging(self.project_id)
            result = await packer.process(
                output_dir=str(self.output_dir),
                circuits=circuits,
                bom_data=bom or {},
                conversion_results=conversions or {}
            )

            # Send WebSocket notification that packaging step is complete
            if self.websocket_manager:
                try:
                    zip_path = result.get('zip_path', '') if isinstance(result, dict) else ''
                    await self.websocket_manager.send_update(self.project_id, {
                        "type": "step_progress",
                        "step": 6,
                        "step_name": "Final Packaging",
                        "status": "completed",
                        "message": "Package ready for download",
                        "zip_path": zip_path
                    })
                except Exception as e:
                    self.logger.logger.debug(f"Failed to send packaging complete notification: {e}")

            self.logger.log_output("step_6_package", result)
            return result
        except Exception as e:
            self.logger.log_error("step_6_package", e)
            return {"success": False, "error": str(e)}
