# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 2: High-Level Design Generation
Ported from N8N workflow to Python
Creates system architecture and block diagrams
"""

"""
=============================================================================
IMPORTS - Step 2 High-Level Design Module
=============================================================================
Standard library imports for async operations, file handling, and system access.
asyncio is REQUIRED for timeout retry logic with await asyncio.sleep().
=============================================================================
"""
import asyncio  # CRITICAL: Required for timeout retry logic (TC #92 fix)
import json
import re
import os
import subprocess
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import tempfile

# Use relative imports that will work
import sys
sys.path.append(str(Path(__file__).parent.parent))

from ai_agents.agent_manager import AIAgentManager
from utils.logger import setup_logger, comprehensive_logger
from workflow.state_manager import WorkflowStateManager
from workflow.diagram_text_parser import parse_diagram_text

logger = setup_logger(__name__)


class Step2HighLevelDesign:
    """
    Step 2: High-Level Design
    - Creates system architecture from requirements
    - Generates block diagrams (DOT format)
    - Renders diagrams using Graphviz
    - Prepares module list for Step 3
    """

    def __init__(self, project_id: str, websocket_manager=None):
        self.project_id = project_id
        self.websocket_manager = websocket_manager  # TC #78: Added for progress updates
        self.ai_manager = AIAgentManager()
        self.state_manager = WorkflowStateManager()
        self.logger = logger
        self.output_paths = {}
        self.enhanced_logger = None  # Initialize as None, will be set if needed

    async def _send_progress(self, message: str, sub_step: int, total_sub_steps: int = 4):
        """TC #78: Send progress updates to websocket for real-time chat updates"""
        if self.websocket_manager and self.project_id:
            try:
                await self.websocket_manager.send_update(self.project_id, {
                    "type": "step_progress",
                    "step": 2,
                    "step_name": "High-Level Design",
                    "message": message,
                    "sub_step": sub_step,
                    "total_sub_steps": total_sub_steps,
                    "progress_percent": (sub_step / total_sub_steps) * 100
                })
            except Exception as e:
                self.logger.warning(f"Failed to send progress update: {e}")

    async def process(self, step1_output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main processing function for Step 2

        Args:
            step1_output: Dict from Step 1 containing:
                - facts: { devicePurpose, generalSpecifications }

        Returns:
            Dict containing:
                - diagrams: List of diagram objects
                - modules: Extracted module list
                - outputPaths: Where files are saved
        """

        # Log input
        if self.enhanced_logger:
            self.enhanced_logger.log_step_input('step2_high_level', step1_output, 'Step 1 output as input')
        try:
            self.logger.info("=" * 60)
            self.logger.info(f"STEP 2: HIGH-LEVEL DESIGN GENERATION")
            self.logger.info(f"Project: {self.project_id}")
            self.logger.info("=" * 60)

            # Log to comprehensive logger for Step 2 tab
            comprehensive_logger.log_step("step2_high", "=" * 60)
            comprehensive_logger.log_step("step2_high", f"STEP 2: HIGH-LEVEL DESIGN GENERATION")
            comprehensive_logger.log_step("step2_high", f"Project: {self.project_id}")
            comprehensive_logger.log_step("step2_high", f"Input: {json.dumps(step1_output, indent=2)[:1000]}..." if len(json.dumps(step1_output)) > 1000 else f"Input: {json.dumps(step1_output, indent=2)}")

            # DON'T create paths - use the ones provided by workflow!
            # The workflow already created all directories
            if not self.output_paths:
                raise ValueError("Output paths must be set by workflow before calling process()!")

            # TC #78: Send progress update - Analyzing requirements
            await self._send_progress("Analyzing requirements...", 1)

            # Prepare design parameters
            # Support both formats: with 'facts' wrapper or direct parameters
            if 'facts' in step1_output:
                design_parameters = step1_output['facts']
            else:
                # Direct parameters format
                design_parameters = step1_output

            design_params = {
                'sessionId': self.project_id,
                'designParameters': design_parameters
            }

            # Process with AI to generate high-level design
            high_level_response = await self._generate_high_level_design(design_params)

            # TC #78: Send progress update - Architecture generated
            await self._send_progress("Generating system architecture...", 2)

            # Log the high_level_response structure for debugging
            self.logger.info(f"High-level response type: {type(high_level_response)}")
            if isinstance(high_level_response, dict):
                self.logger.info(f"High-level response keys: {list(high_level_response.keys())}")
                if 'diagrams' in high_level_response:
                    self.logger.info(f"Found 'diagrams' key directly with {len(high_level_response['diagrams'])} items")

            # Extract and fix DOT diagrams
            diagrams = self._extract_diagrams(high_level_response)

            # Log diagram extraction result
            self.logger.info(f"Extracted {len(diagrams)} diagrams total")

            # Render diagrams with Graphviz
            rendered_diagrams = await self._render_diagrams(diagrams)

            # TC #78: Send progress update - Diagrams created
            await self._send_progress("Creating block diagrams...", 3)

            # Extract module list from design
            # ROBUST MODULE EXTRACTION: Handles complete, truncated, and malformed AI responses
            # This is GENERIC - works for ANY circuit type (LED blinker to spacecraft power system)
            modules = []

            # Try multiple extraction paths with detailed logging
            if 'raw_response' in high_level_response and isinstance(high_level_response['raw_response'], str):
                # Path 1: Parse the raw_response string (handles markdown, JSON fences, truncation)
                self.logger.info("Attempting module extraction from raw_response")
                try:
                    parsed_response = self._parse_ai_response(high_level_response['raw_response'])
                    self.logger.debug(f"Parsed response type: {type(parsed_response)}, keys: {list(parsed_response.keys()) if isinstance(parsed_response, dict) else 'N/A'}")
                    modules = self._extract_modules(parsed_response)
                    if modules:
                        self.logger.info(f"✅ Extracted {len(modules)} modules from raw_response")
                except Exception as e:
                    self.logger.warning(f"Could not parse/extract from raw_response: {e}")

            # Path 2: Try direct extraction from high_level_response (if Path 1 failed or no raw_response)
            if not modules:
                self.logger.info("Attempting module extraction from high_level_response directly")
                try:
                    modules = self._extract_modules(high_level_response)
                    if modules:
                        self.logger.info(f"✅ Extracted {len(modules)} modules from high_level_response")
                except Exception as e:
                    self.logger.warning(f"Could not extract from high_level_response: {e}")

            # Log extraction result
            if modules:
                self.logger.info(f"📋 Module extraction successful: {len(modules)} modules")
                for i, mod in enumerate(modules, 1):
                    mod_name = mod.get('name', 'UNNAMED') if isinstance(mod, dict) else str(mod)
                    self.logger.info(f"   {i}. {mod_name}")
            else:
                self.logger.warning("⚠️ No modules extracted from AI response - will use safety net")

            # IMPORTANT: Consolidate modules to practical buildable units (N8N Step 3)
            # This remains fully generic and applies simple consolidation only when appropriate.
            # Never leave the workflow with an empty module list: downstream steps require at
            # least one module to proceed and produce converter outputs.
            try:
                # For modular channel systems, consolidate sub-functions into channel modules
                modules = self._consolidate_for_modular_channels(modules)
            except Exception as e:
                # Consolidation itself is non-critical; log and continue safely.
                self.logger.warning(f"Module consolidation failed: {e}. Using original modules.")

            # FINAL SAFETY NET: Ensure modules are never empty
            # If extraction + consolidation produced no modules (typical for very short inputs),
            # generate a small, generic module set based on the device purpose. This keeps the
            # pipeline dynamic and applicable to ANY circuit complexity level.
            if not modules:
                self.logger.error("🔴 CRITICAL: No modules extracted from AI response!")
                self.logger.error("This should NOT happen with the new robust extraction logic.")
                self.logger.error("Generating fallback generic modules to prevent pipeline failure.")
                modules = self._create_default_modules(design_params)

            # VALIDATE: Ensure we have valid modules before proceeding
            if not modules or len(modules) == 0:
                raise ValueError("CRITICAL FAILURE: Step 2 produced zero modules. Cannot proceed with circuit generation.")

            # Validate module structure
            for i, module in enumerate(modules):
                if not isinstance(module, dict):
                    raise ValueError(f"Invalid module at index {i}: not a dictionary")
                if 'name' not in module:
                    raise ValueError(f"Invalid module at index {i}: missing 'name' field")

            self.logger.info(f"✅ Step 2 validation passed: {len(modules)} valid modules ready for Step 3")

            # TC #78: Send progress update - Modules finalized
            await self._send_progress(f"Finalizing {len(modules)} module definitions...", 4)

            # Prepare output
            output = {
                'diagrams': rendered_diagrams,
                'modules': modules,
                'outputPaths': self.output_paths,
                'highLevelDesign': high_level_response,
                'designParameters': design_params['designParameters']
            }

            # Save to state
            self.state_manager.update_state('step_2_output', output)
            self.state_manager.update_state('outputPaths', self.output_paths)

            # Handle case where no diagrams were generated
            if not rendered_diagrams:
                self.logger.warning("No diagrams extracted from AI response, creating default diagram")
                # Try to create a minimal diagram from modules
                if modules:
                    self.logger.warning("Creating emergency fallback diagram from modules")
                    # Create INTELLIGENT topology based on module types

                    # Analyze module types
                    power_modules = []
                    control_modules = []
                    channel_modules = []
                    output_modules = []
                    other_modules = []

                    for m in modules:
                        name = (m.get('name', '') if isinstance(m, dict) else str(m)).lower()
                        module = m if isinstance(m, dict) else {'name': str(m)}

                        if 'power' in name or 'supply' in name:
                            power_modules.append(module)
                        elif 'control' in name or 'main' in name or 'processor' in name:
                            control_modules.append(module)
                        elif 'channel' in name or 'driver' in name or 'amplifier' in name:
                            channel_modules.append(module)
                        elif 'output' in name or 'interface' in name:
                            output_modules.append(module)
                        else:
                            other_modules.append(module)

                    # Build correct topology (PARALLEL channels!)
                    dot_lines = ['digraph G {',
                                 '  rankdir=LR;',
                                 '  node[shape=box,style=filled,fillcolor=lightblue];']

                    # Add all nodes
                    all_modules = power_modules + control_modules + channel_modules + output_modules + other_modules
                    node_names = []
                    for module in all_modules:
                        name = module.get('name', 'Module') if isinstance(module, dict) else str(module)
                        node_names.append(self._sanitize_node_name(name))

                    # Style nodes by type
                    for module in power_modules:
                        name = self._sanitize_node_name(module.get('name', 'Power'))
                        dot_lines.append(f'  {name}[fillcolor=lightgreen];')
                    for module in control_modules:
                        name = self._sanitize_node_name(module.get('name', 'Control'))
                        dot_lines.append(f'  {name}[fillcolor=lightyellow];')
                    for module in channel_modules:
                        name = self._sanitize_node_name(module.get('name', 'Channel'))
                        dot_lines.append(f'  {name}[fillcolor=lightcoral];')
                    for module in output_modules:
                        name = self._sanitize_node_name(module.get('name', 'Output'))
                        dot_lines.append(f'  {name}[fillcolor=lightgray];')

                    # Create INTELLIGENT connections
                    edges = []

                    # Power -> Control
                    if power_modules and control_modules:
                        p_name = self._sanitize_node_name(power_modules[0].get('name'))
                        c_name = self._sanitize_node_name(control_modules[0].get('name'))
                        edges.append(f'{p_name} -> {c_name}')

                    # Control -> Channels (PARALLEL!)
                    if control_modules and channel_modules:
                        c_name = self._sanitize_node_name(control_modules[0].get('name'))
                        for channel in channel_modules:
                            ch_name = self._sanitize_node_name(channel.get('name'))
                            edges.append(f'{c_name} -> {ch_name}')

                    # Channels -> Output (PARALLEL!)
                    if channel_modules and output_modules:
                        o_name = self._sanitize_node_name(output_modules[0].get('name'))
                        for channel in channel_modules:
                            ch_name = self._sanitize_node_name(channel.get('name'))
                            edges.append(f'{ch_name} -> {o_name}')

                    # If no special topology detected, use linear as last resort
                    if not edges and len(all_modules) > 1:
                        for i in range(len(node_names) - 1):
                            edges.append(f'{node_names[i]} -> {node_names[i+1]}')

                    # Add edges as separate lines
                    if edges:
                        for edge in edges:
                            dot_lines.append(f'  {edge};')
                    else:
                        dot_lines.append('  // No connections')

                    dot_lines.append('}')

                    default_dot = '\n'.join(dot_lines)
                    rendered_diagrams = [{
                        'filename': 'system_overview',
                        'graphviz_dot': default_dot
                    }]
                else:
                    # Absolute fallback - just create an empty diagram
                    rendered_diagrams = [{
                        'filename': 'system_overview',
                        'graphviz_dot': 'digraph G { label="ERROR: No diagram generated"; }'
                    }]

            # Save diagrams to disk (PNG and DOT files)
            self._save_diagrams(rendered_diagrams, output)

            # DON'T save JSON files - only PNG and DOT!

            # Log completion to both loggers
            self.logger.info("=" * 60)
            self.logger.info(f"STEP 2 COMPLETED")
            self.logger.info(f"  Diagrams generated: {len(diagrams)}")
            self.logger.info(f"  Modules extracted: {len(modules)}")
            for i, module in enumerate(modules):
                self.logger.info(f"    Module {i+1}: {module}")
            self.logger.info(f"  High-level design created with {len(str(high_level_response))} characters")
            self.logger.info(f"  Output directory: {self.output_paths['highlevel']}")
            self.logger.info("=" * 60)

            # Log to comprehensive logger for Step 2 tab
            comprehensive_logger.log_step("step2_high", "=" * 60)
            comprehensive_logger.log_step("step2_high", f"STEP 2 COMPLETED")
            comprehensive_logger.log_step("step2_high", f"  Diagrams generated: {len(diagrams)}")
            comprehensive_logger.log_step("step2_high", f"  Modules extracted: {len(modules)}")
            for i, module in enumerate(modules):
                comprehensive_logger.log_step("step2_high", f"    Module {i+1}: {json.dumps(module, indent=2) if isinstance(module, dict) else module}")
            comprehensive_logger.log_step("step2_high", f"  High-level design: {json.dumps(high_level_response, indent=2)[:2000]}..." if len(json.dumps(high_level_response)) > 2000 else f"  High-level design: {json.dumps(high_level_response, indent=2)}")
            comprehensive_logger.log_step("step2_high", f"  Output directory: {self.output_paths['highlevel']}")
            comprehensive_logger.log_step("step2_high", "=" * 60)

            # Generate professional summary document in highlevel/ directory
            try:
                self._write_design_summary(
                    high_level_response, modules, self.output_paths['highlevel']
                )
            except Exception as exc:
                self.logger.warning(f"Design summary generation failed (non-fatal): {exc}")

            if self.enhanced_logger:
                self.enhanced_logger.log_step_output('step2_high_level', output, 'Step 2 results')
            return output

        except Exception as e:
            self.logger.error(f"Error in Step 2: {str(e)}")
            raise

    def _create_output_paths(self) -> Dict[str, str]:
        """DEPRECATED - Paths should be set by workflow, not created here"""
        # This method should not be called anymore
        # Paths are managed by the workflow using project_manager
        raise RuntimeError("Output paths must be set by workflow, not created by step")

    def _ensure_directories(self):
        """Directories already created by workflow - just log"""
        # DON'T create directories - they're already created by the workflow!
        pass

    def _slugify(self, text: str) -> str:
        """Convert text to filesystem-safe slug"""
        slug = str(text).lower().strip()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = re.sub(r'^-+|-+$', '', slug)
        return slug[:40] or 'project'

    async def _generate_high_level_design(self, design_params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate high-level design using AI with retry logic for overload errors"""

        # Load the Step 2 prompt from correct location
        prompt_path = Path(__file__).parent.parent / "ai_agents" / "prompts" / "AI Agent - Step 2 - High Level Prompt.txt"

        if prompt_path.exists():
            with open(prompt_path, 'r') as f:
                prompt_template = f.read()
        else:
            self.logger.warning(f"Prompt file not found at {prompt_path}, using fallback")
            prompt_template = self._get_fallback_prompt()

        # Replace variables in prompt - fix the template replacement
        # Check if we have the old format or new format
        if 'designParameters' in design_params:
            design_params_json = json.dumps(design_params['designParameters'], indent=2)
        else:
            # Direct format - just use the params as is
            design_params_json = json.dumps(design_params, indent=2)

        self.logger.debug(f"Design params being sent to AI (first 500 chars): {design_params_json[:500]}")

        # Use the actual N8N template variable format
        prompt = prompt_template.replace('{{ JSON.stringify($json.designParameters, null, 2) }}', design_params_json)

        # Try AI call with retry for overload AND timeout errors
        # CRITICAL FIX (Dec 21): Added timeout retry logic - API timeouts were not being retried
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Call AI with Claude 4 Sonnet
                result = await self.ai_manager.call_ai(
                    step_name="step_2_high_level",
                    prompt=prompt,
                    context={"design_params": design_params}
                )

                # CRITICAL FIX: Check if API call failed (timeout or error)
                # call_ai() returns {"success": False} on timeout, not an exception
                if not result.get('success', True):
                    error_msg = result.get('error', 'Unknown error')
                    # Check for timeout or network errors
                    if any(err in error_msg.lower() for err in ['timeout', 'timed out', 'interrupted', 'network']):
                        if attempt < max_retries - 1:
                            wait_time = 30 * (attempt + 1)  # 30, 60 seconds
                            self.logger.warning(
                                f"⚠️ AI TIMEOUT for Step 2 (attempt {attempt + 1}/{max_retries}). "
                                f"Retrying in {wait_time}s..."
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            self.logger.error(f"❌ AI timeout after {max_retries} attempts. Creating fallback design.")
                            return self._create_fallback_design(design_params)
                    elif 'overloaded' in error_msg.lower():
                        if attempt < max_retries - 1:
                            self.logger.warning(f"AI overloaded, retrying in {5 * (attempt + 1)} seconds...")
                            await asyncio.sleep(5 * (attempt + 1))
                            continue
                        else:
                            return self._create_fallback_design(design_params)
                    else:
                        # Unknown error - try to continue anyway
                        self.logger.warning(f"AI call returned error: {error_msg}")

                # Get the raw response first
                raw_response = result.get('raw_response', '')

                # Log raw response for debugging
                self.logger.debug(f"Raw AI response (first 500 chars): {raw_response[:500]}...")

                # Parse the raw response to get JSON
                if raw_response:
                    parsed = self._parse_ai_response(raw_response)
                else:
                    # Fallback to parsed_response if raw_response is empty
                    parsed = result.get('parsed_response', {})

                self.logger.info(f"Parsed response type: {type(parsed)}")
                if isinstance(parsed, dict):
                    self.logger.info(f"Parsed response keys: {list(parsed.keys())}")

                return parsed

            except Exception as e:
                error_msg = str(e)
                if 'overloaded' in error_msg.lower() and attempt < max_retries - 1:
                    self.logger.warning(f"AI overloaded, retrying in {5 * (attempt + 1)} seconds...")
                    await asyncio.sleep(5 * (attempt + 1))  # Exponential backoff
                elif attempt == max_retries - 1:
                    self.logger.error(f"AI call failed after {max_retries} attempts. Creating fallback design.")
                    # Return a fallback design structure
                    return self._create_fallback_design(design_params)
                else:
                    raise

    def _parse_ai_response(self, response: Any) -> Dict[str, Any]:
        """
        Parse AI response with robust error recovery for malformed/truncated JSON.

        PROBLEM SOLVED:
        AI responses can be truncated due to output length limits (e.g., connections array cut off).
        Standard JSON parsing fails on truncated responses, causing module extraction to fail,
        which cascades to zero circuits generated, which breaks the entire pipeline.

        SOLUTION:
        1. Try standard JSON parsing (handles complete responses)
        2. If fails, try to fix common JSON errors (handles minor issues)
        3. If still fails, extract partial JSON (handles truncation) via regex
        4. The partial extraction specifically targets the modules array, which is usually complete
           even when later sections (connections, diagrams) are truncated

        GENERIC: Works for ANY circuit type - simple LED blinker to complex multi-channel systems.
        """

        if isinstance(response, dict):
            return response

        if not isinstance(response, str):
            return {}

        # Try to extract JSON from string
        text = response.strip()

        # Remove code fences (AI often wraps JSON in ```json ... ```)
        text = re.sub(r'^```json?\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'```\s*$', '', text)

        # Find JSON object or array
        json_match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
        if json_match:
            json_str = json_match.group(1)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                self.logger.warning(f"Initial JSON parse failed (likely truncated response): {e}")
                # Try to fix common JSON errors (missing closing braces, trailing commas, etc.)
                fixed_json = self._fix_json_errors(json_str)
                try:
                    return json.loads(fixed_json)
                except json.JSONDecodeError as e2:
                    self.logger.error(f"Could not auto-fix JSON errors: {e2}")
                    # CRITICAL FALLBACK: Extract modules via regex (works with truncated responses!)
                    self.logger.info("Attempting partial JSON extraction via regex (handles truncation)")
                    return self._extract_partial_json(json_str)

        return {'raw_response': response}

    def _fix_json_errors(self, json_str: str) -> str:
        """Fix common JSON formatting issues"""
        # Remove trailing commas before closing braces/brackets
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)

        # Fix unclosed strings (common with truncation)
        # Count quotes and add closing quote if odd number
        quote_count = json_str.count('"') - json_str.count('\\"')
        if quote_count % 2 != 0:
            json_str += '"'

        # Fix truncated responses - try to close open structures
        open_braces = json_str.count('{') - json_str.count('}')
        open_brackets = json_str.count('[') - json_str.count(']')

        # Add closing structures
        if open_brackets > 0:
            json_str += ']' * open_brackets
        if open_braces > 0:
            json_str += '}' * open_braces

        # Remove incomplete trailing content after last complete structure
        # Find the last complete JSON object/array
        for i in range(len(json_str) - 1, -1, -1):
            if json_str[i] in '}]':
                test_str = json_str[:i+1]
                try:
                    json.loads(test_str)
                    return test_str
                except (json.JSONDecodeError, ValueError):
                    continue

        return json_str

    def _extract_partial_json(self, json_str: str) -> Dict[str, Any]:
        """
        Extract as much information as possible from malformed/truncated JSON.

        CRITICAL: This handles the common case where AI responses are truncated due to
        length limits but the modules section is complete. This is GENERIC - works for
        ANY circuit type (simple LED blinker to complex multi-channel systems).
        """
        result = {'raw_response': json_str}

        # Strategy 1: Try to extract complete modules array (handles truncated connections)
        # Look for: "modules": [...], "connections" or "modules": [...] }
        # This works even if the connections array is truncated/incomplete
        modules_pattern = r'"modules"\s*:\s*\[([\s\S]*?)\]\s*,\s*("connections"|"diagrams"|\})'
        modules_match = re.search(modules_pattern, json_str)

        if modules_match:
            try:
                # Extract the complete modules array as valid JSON
                modules_json = '[' + modules_match.group(1) + ']'
                modules = json.loads(modules_json)
                if modules:
                    self.logger.info(f"✅ Extracted {len(modules)} modules from truncated JSON via regex")
                    result['modules'] = modules
                    return result  # Success! Return early
            except json.JSONDecodeError as e:
                self.logger.warning(f"Could not parse extracted modules array: {e}")
                # Fall through to simpler extraction

        # Strategy 2: Fallback - extract module names only (minimal extraction)
        # This is a last resort for severely malformed responses
        if 'modules' not in result:
            try:
                # Look for module name fields
                module_names = re.findall(r'"name"\s*:\s*"([^"]+)"', json_str)
                if module_names:
                    # Create minimal module objects
                    modules = [{'name': name, 'description': '', 'inputs': [], 'outputs': [], 'specifications': {}}
                               for name in module_names if not name.startswith('Module_')]
                    if modules:
                        self.logger.warning(f"⚠️ Extracted {len(modules)} module names only (minimal info)")
                        result['modules'] = modules
            except (json.JSONDecodeError, ValueError, TypeError):
                pass  # Malformed JSON, continue with partial extraction

        # Extract description
        desc_match = re.search(r'"description"\s*:\s*"([^"]*)"', json_str)
        if desc_match:
            result['description'] = desc_match.group(1)

        # Extract connections if present
        conn_match = re.search(r'"connections"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
        if conn_match:
            try:
                connections = []
                conn_pattern = r'\{[^{}]*\}'
                for c_match in re.finditer(conn_pattern, conn_match.group(1)):
                    try:
                        conn = json.loads(c_match.group(0))
                        connections.append(conn)
                    except (json.JSONDecodeError, ValueError):
                        pass  # Skip malformed connection
                if connections:
                    result['connections'] = connections
            except (json.JSONDecodeError, ValueError, TypeError):
                pass  # Could not parse connections

        return result

    def _extract_diagrams(self, high_level_response: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extract and fix DOT diagrams from AI response

        Now supports TEXT-BASED diagram format (preferred):
        AI provides diagram_text field, we parse it to DOT
        """

        diagrams = []

        # Log the response structure for debugging
        self.logger.info(f"_extract_diagrams: Response type: {type(high_level_response)}")
        if isinstance(high_level_response, dict):
            self.logger.info(f"_extract_diagrams: Response keys: {list(high_level_response.keys())}")

        # PRIORITY 1: Check for TEXT-BASED diagram (NEW FORMAT)
        if 'diagram_text' in high_level_response:
            diagram_text = high_level_response.get('diagram_text', '')
            self.logger.info(f"Found diagram_text field - using text-based parser")

            if diagram_text and diagram_text != "REQUIRED - SEE FORMAT BELOW":
                dot_content, errors = parse_diagram_text(diagram_text)
                if errors:
                    self.logger.warning(f"Diagram text parse errors: {errors}")

                diagrams = [{
                    'filename': 'system_overview',
                    'graphviz_dot': dot_content
                }]
                self.logger.info(f"Generated diagram from text ({len(dot_content)} chars)")
                return diagrams

        # If no valid diagram_text, generate it from modules
        if 'modules' in high_level_response and high_level_response['modules']:
            self.logger.info("No diagram_text found, generating from modules list")
            diagram_text = self._generate_diagram_text_from_modules(high_level_response['modules'])
            if diagram_text:
                dot_content, errors = parse_diagram_text(diagram_text)
                if errors:
                    self.logger.warning(f"Generated diagram text parse errors: {errors}")
                else:
                    diagrams = [{
                        'filename': 'system_overview',
                        'graphviz_dot': dot_content
                    }]
                    self.logger.info(f"Generated diagram from modules ({len(dot_content)} chars)")
                    return diagrams

        # FALLBACK: Try old diagram formats
        if 'diagrams' in high_level_response:
            diagrams_value = high_level_response.get('diagrams')
            self.logger.info(f"_extract_diagrams: Found 'diagrams' key, type: {type(diagrams_value)}, len: {len(diagrams_value) if isinstance(diagrams_value, list) else 'N/A'}")

        # Try various paths where diagrams might be
        possible_paths = [
            high_level_response.get('diagrams'),
            high_level_response.get('high_level', {}).get('diagrams'),
            high_level_response.get('output', {}).get('diagrams'),
            high_level_response.get('outputs', {}).get('diagrams'),
            high_level_response.get('result', {}).get('diagrams'),
        ]

        for i, path in enumerate(possible_paths):
            if isinstance(path, list):
                self.logger.info(f"_extract_diagrams: Found diagrams at path index {i}, count: {len(path)}")
                diagrams = path
                break

        # If still no diagrams, check if response itself is a diagram
        if not diagrams and any(key in high_level_response for key in ['graphviz_dot', 'dot', 'graphviz', 'gv']):
            diagrams = [high_level_response]

        # Process and fix each diagram
        fixed_diagrams = []
        for i, diagram in enumerate(diagrams):
            if not isinstance(diagram, dict):
                self.logger.debug(f"Skipping non-dict diagram: {type(diagram)}")
                continue

            # Extract DOT content
            dot_content = (diagram.get('graphviz_dot') or
                          diagram.get('dot') or
                          diagram.get('graphviz') or
                          diagram.get('gv') or '')

            if not dot_content:
                self.logger.debug(f"No DOT content found in diagram {i}")
                continue

            # Fix DOT syntax
            fixed_dot = self._fix_dot_syntax(dot_content)

            # Get filename
            filename = (diagram.get('filename') or
                       diagram.get('fileName') or
                       diagram.get('name') or
                       diagram.get('title') or
                       f'diagram_{i + 1}')

            fixed_diagrams.append({
                'filename': self._slugify(filename),
                'graphviz_dot': fixed_dot
            })

        return fixed_diagrams

    def _consolidate_for_modular_channels(self, modules: List[Dict]) -> List[Dict]:
        """Consolidate modules into practical modular units for channel-based systems"""
        if not modules:
            return modules

        # Check if this appears to be a multi-channel system
        # Look for DDS, amplifier, matching modules (indicators of detailed channel breakdown)
        channel_subsystems = []
        core_modules = []

        for module in modules:
            name = module.get('name', '').lower()
            module_type = module.get('type', '').lower()

            # Check if this is a channel subsystem (not core infrastructure)
            is_channel_subsystem = any(keyword in name or keyword in module_type
                                      for keyword in ['dds', 'amplifier', 'matching', 'impedance',
                                                     'phase', 'detector', 'resonance', 'tracker'])

            if is_channel_subsystem:
                channel_subsystems.append(module)
            else:
                core_modules.append(module)

        # If we have many channel subsystems, this needs consolidation
        if len(channel_subsystems) >= 4 and len(modules) > 6:
            self.logger.info(f"Detected over-detailed modules ({len(modules)} total, {len(channel_subsystems)} channel subsystems)")

            # Group channel subsystems by channel number
            channel_groups = {'1': [], '2': [], 'generic': []}

            for module in channel_subsystems:
                name = module.get('name', '').lower()

                # Detect channel number
                if any(x in name for x in ['ch1', 'channel_1', '_1', '50khz']):
                    channel_groups['1'].append(module)
                elif any(x in name for x in ['ch2', 'channel_2', '_2', '1.5mhz', '1500khz']):
                    channel_groups['2'].append(module)
                else:
                    # Generic modules that might be duplicated per channel
                    channel_groups['generic'].append(module)
            self.logger.info(f"Consolidating {len(modules)} modules into practical design")

            consolidated = []

            # Keep essential core modules (power, control)
            power_modules = [m for m in core_modules if 'power' in m.get('name', '').lower() or 'supply' in m.get('name', '').lower()]
            control_modules = [m for m in core_modules if 'control' in m.get('name', '').lower() or 'interface' in m.get('name', '').lower()]
            protection_modules = [m for m in core_modules if 'protection' in m.get('name', '').lower()]

            # Add core modules (max 2 power, 2 control, 1 protection)
            for module in power_modules[:2]:
                consolidated.append(module)
            for module in control_modules[:2]:
                consolidated.append(module)
            for module in protection_modules[:1]:
                consolidated.append(module)

            # Create consolidated channel modules
            for ch_num, ch_modules in [('1', channel_groups['1']), ('2', channel_groups['2'])]:
                if ch_modules:
                    # Merge all channel subsystems into one module
                    channel_module = {
                        'name': f'Channel_{ch_num}_Module',
                        'type': 'channel',
                        'description': f'Complete Channel {ch_num} module with all subsystems integrated',
                        'inputs': [],
                        'outputs': [],
                        'specifications': {}
                    }

                    # Merge data from all subsystems
                    for module in ch_modules:
                        # Merge specifications
                        channel_module['specifications'].update(module.get('specifications', {}))
                        # Collect unique inputs/outputs
                        for inp in module.get('inputs', []):
                            if inp not in channel_module['inputs']:
                                channel_module['inputs'].append(inp)
                        for out in module.get('outputs', []):
                            if out not in channel_module['outputs']:
                                channel_module['outputs'].append(out)

                    # Limit inputs/outputs to most important
                    channel_module['inputs'] = channel_module['inputs'][:5]
                    channel_module['outputs'] = channel_module['outputs'][:3]

                    consolidated.append(channel_module)

            self.logger.info(f"Consolidated to {len(consolidated)} practical modules")
            return consolidated

        # If not too many modules or not channel-based, return as-is
        return modules

    def _generate_diagram_text_from_modules(self, modules: List[Dict]) -> str:
        """Generate diagram_text format from modules list with intelligent connections"""
        if not modules:
            return ""

        lines = []

        # Add all modules
        for module in modules:
            name = module.get('name', 'Unknown')
            module_type = module.get('type', 'module')
            lines.append(f"Module: {name} (type: {module_type})")

        lines.append("")  # Blank line between modules and connections

        # Create intelligent connections based on module types and inputs/outputs
        module_names = [m.get('name', '') for m in modules]

        # Find key modules by type AND name (comprehensive detection)
        power_modules = [m for m in modules if 'power' in m.get('type', '').lower() or 'power' in m.get('name', '').lower()]
        control_modules = [m for m in modules if 'control' in m.get('type', '').lower() or 'controller' in m.get('name', '').lower()]
        protection_modules = [m for m in modules if 'protection' in m.get('type', '').lower() or 'protection' in m.get('name', '').lower()]
        interface_modules = [m for m in modules if 'interface' in m.get('type', '').lower() or 'interface' in m.get('name', '').lower() or 'ui' in m.get('name', '').lower() or 'display' in m.get('name', '').lower()]
        cooling_modules = [m for m in modules if 'cooling' in m.get('type', '').lower() or 'cooling' in m.get('name', '').lower() or 'fan' in m.get('name', '').lower()]

        # CRITICAL FIX: Detect consolidated channel modules
        # These are complete channel modules with type='channel' or 'channel' in name or numbered
        channel_modules = [m for m in modules if
                          m.get('type', '').lower() == 'channel' or
                          'channel' in m.get('name', '').lower() or
                          any(f'_{num}_' in m.get('name', '').lower() or f'_ch{num}' in m.get('name', '').lower() or f'ch{num}' in m.get('name', '').lower() for num in ['1', '2', '3', '4'])]

        # For backward compatibility, also detect separate signal/amplifier/matching modules
        signal_modules = [m for m in modules if m not in channel_modules and ('signal' in m.get('type', '').lower() or 'dds' in m.get('name', '').lower())]
        amplifier_modules = [m for m in modules if m not in channel_modules and ('amplifier' in m.get('type', '').lower() or 'amplifier' in m.get('name', '').lower())]
        matching_modules = [m for m in modules if m not in channel_modules and ('matching' in m.get('type', '').lower() or 'impedance' in m.get('name', '').lower())]
        sensing_modules = [m for m in modules if m not in channel_modules and ('sensing' in m.get('type', '').lower() or 'sensor' in m.get('name', '').lower())]
        feedback_modules = [m for m in modules if m not in channel_modules and ('feedback' in m.get('type', '').lower() or 'phase' in m.get('name', '').lower())]

        # Generate connections based on typical signal flow
        connections = []

        # Power connections - Power to ALL modules except itself
        if power_modules:
            main_power = power_modules[0].get('name')
            for module in modules:
                if module != power_modules[0]:  # Don't connect power to itself
                    connections.append(f"Connect: {main_power} -> {module.get('name')}")

        # Control connections
        if control_modules:
            main_control = control_modules[0].get('name')

            # Control to ALL channel modules (consolidated or separate)
            for ch in channel_modules:
                connections.append(f"Connect: {main_control} -> {ch.get('name')}")

            # Control to signal generators (if separate from channels)
            for sig in signal_modules:
                connections.append(f"Connect: {main_control} -> {sig.get('name')}")

            # Control to protection
            for prot in protection_modules:
                connections.append(f"Connect: {main_control} -> {prot.get('name')}")

            # Control to interface (bidirectional - user input)
            for ui in interface_modules:
                connections.append(f"Connect: {ui.get('name')} -> {main_control}")

            # Control to cooling (fan control based on temperature)
            for cool in cooling_modules:
                connections.append(f"Connect: {main_control} -> {cool.get('name')}")

        # Channel feedback connections
        if channel_modules and protection_modules:
            # Channels provide feedback to protection module
            for ch in channel_modules:
                connections.append(f"Connect: {ch.get('name')} -> {protection_modules[0].get('name')}")

        # Signal flow for channels
        # Try to match channel-specific modules
        for ch_num in ['1', '2', 'Ch1', 'Ch2']:
            ch_signal = [m for m in signal_modules if ch_num in m.get('name', '')]
            ch_amp = [m for m in amplifier_modules if ch_num in m.get('name', '')]
            ch_match = [m for m in matching_modules if ch_num in m.get('name', '')]
            ch_sense = [m for m in sensing_modules if ch_num in m.get('name', '')]
            ch_feedback = [m for m in feedback_modules if ch_num in m.get('name', '')]

            # Signal -> Amplifier
            if ch_signal and ch_amp:
                connections.append(f"Connect: {ch_signal[0].get('name')} -> {ch_amp[0].get('name')}")
            # Amplifier -> Matching
            if ch_amp and ch_match:
                connections.append(f"Connect: {ch_amp[0].get('name')} -> {ch_match[0].get('name')}")
            # Matching -> Sensing
            if ch_match and ch_sense:
                connections.append(f"Connect: {ch_match[0].get('name')} -> {ch_sense[0].get('name')}")
            # Sensing -> Feedback
            if ch_sense and ch_feedback:
                connections.append(f"Connect: {ch_sense[0].get('name')} -> {ch_feedback[0].get('name')}")

        # Feedback to control
        if feedback_modules and control_modules:
            for fb in feedback_modules:
                connections.append(f"Connect: {fb.get('name')} -> {control_modules[0].get('name')}")

        # Add unique connections only
        seen = set()
        for conn in connections:
            if conn not in seen:
                lines.append(conn)
                seen.add(conn)

        return '\n'.join(lines)

    def _sanitize_node_name(self, name: str) -> str:
        """Universal sanitizer for Graphviz node names"""
        if not name:
            return '""'
        # Always quote names with special characters
        if any(char in name for char in ['(', ')', ',', '/', '\\', ':', ';', ' ', '-', '.', '[', ']', '{', '}', '|', '<', '>', '=', '+', '*', '&', '%', '$', '#', '@', '!', '?', '"', "'"]):
            # Escape quotes inside the name
            escaped_name = name.replace('"', '\\"')
            return f'"{escaped_name}"'
        return name

    def _fix_dot_syntax(self, dot_content: str) -> str:
        """Fix common DOT syntax issues"""

        if not dot_content or not isinstance(dot_content, str):
            return 'digraph G { label="Empty diagram"; }'

        dot = dot_content.strip()

        # Remove code fences
        dot = re.sub(r'^```\w*\n?', '', dot)
        dot = re.sub(r'```$', '', dot)
        dot = dot.strip()

        # Check if it has valid graph declaration
        if not re.match(r'^\s*(di)?graph\s+\w*\s*{', dot, re.IGNORECASE):
            # Add wrapper
            dot = f"""digraph G {{
  rankdir=LR;
  node[shape=box,style=filled,fillcolor=lightblue];
  edge[color=gray];

  {dot}
}}"""

        # Ensure closing brace
        if not dot.rstrip().endswith('}'):
            dot = dot + '\n}'

        # Fix brace matching
        open_braces = dot.count('{')
        close_braces = dot.count('}')

        if open_braces > close_braces:
            dot = dot + '\n}' * (open_braces - close_braces)
        elif close_braces > open_braces:
            # Remove extra closing braces
            for _ in range(close_braces - open_braces):
                dot = re.sub(r'}\s*$', '', dot, count=1)
            dot = dot + '\n}'

        return dot

    async def _render_diagrams(self, diagrams: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Render DOT diagrams using Graphviz"""

        rendered = []

        for diagram in diagrams:
            try:
                # Create temp file for DOT content
                with tempfile.NamedTemporaryFile(mode='w', suffix='.dot', delete=False) as f:
                    f.write(diagram['graphviz_dot'])
                    dot_file = f.name

                # Output file path
                png_file = os.path.join(self.output_paths['highlevel'], f"{diagram['filename']}.png")

                # Run Graphviz (dot command)
                result = subprocess.run(
                    ['dot', '-Tpng', dot_file, '-o', png_file],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    rendered.append({
                        **diagram,
                        'png_path': png_file,
                        'rendered': True
                    })
                    self.logger.info(f"Rendered diagram: {diagram['filename']}")
                else:
                    self.logger.error(f"Failed to render {diagram['filename']}: {result.stderr}")
                    rendered.append({
                        **diagram,
                        'error': result.stderr,
                        'rendered': False
                    })

                # Clean up temp file
                os.unlink(dot_file)

            except FileNotFoundError:
                self.logger.warning("Graphviz not installed. Saving DOT files only.")
                # Just save the DOT file if Graphviz not available
                dot_path = os.path.join(self.output_paths['highlevel'], f"{diagram['filename']}.dot")
                with open(dot_path, 'w') as f:
                    f.write(diagram['graphviz_dot'])
                rendered.append({
                    **diagram,
                    'dot_path': dot_path,
                    'rendered': False
                })
            except Exception as e:
                self.logger.error(f"Error rendering diagram {diagram['filename']}: {str(e)}")
                rendered.append({
                    **diagram,
                    'error': str(e),
                    'rendered': False
                })

        return rendered

    def _extract_modules(self, high_level_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract module list from high-level design"""

        modules = []

        # Try to find modules in response
        possible_paths = [
            high_level_response.get('modules'),
            high_level_response.get('components'),
            high_level_response.get('subsystems'),
            high_level_response.get('blocks'),
            high_level_response.get('high_level', {}).get('modules'),
        ]

        for path in possible_paths:
            if isinstance(path, list):
                modules = path
                break

        # If no modules found, try to extract from diagram labels
        if not modules:
            modules = self._extract_modules_from_diagrams(high_level_response.get('diagrams', []))

        # Ensure each module has required fields
        normalized_modules = []
        for i, module in enumerate(modules):
            if isinstance(module, str):
                module = {'name': module}

            if not isinstance(module, dict):
                continue

            normalized = {
                'name': module.get('name', f'Module_{i + 1}'),
                'description': module.get('description', ''),
                'inputs': module.get('inputs', []),
                'outputs': module.get('outputs', []),
                'specifications': module.get('specifications', {}),
                'operating_voltage': module.get('operating_voltage', ''),
                'isolation_domain': module.get('isolation_domain', 'GND_SYSTEM')
            }
            normalized_modules.append(normalized)

        return normalized_modules

    def _extract_modules_from_diagrams(self, diagrams: List[Dict]) -> List[Dict[str, Any]]:
        """Fallback: extract module names from DOT diagram content"""

        modules = []
        seen = set()

        for diagram in diagrams:
            if not isinstance(diagram, dict):
                continue

            dot_content = diagram.get('graphviz_dot', '')

            # Extract node definitions (simple pattern)
            # Looks for patterns like: ModuleName [label="..."]
            pattern = r'(\w+)\s*\[.*?label\s*=\s*"([^"]+)"'
            matches = re.findall(pattern, dot_content)

            for node_id, label in matches:
                # Skip edge definitions and special nodes
                if node_id.lower() in ['graph', 'node', 'edge', 'digraph', 'subgraph']:
                    continue

                if label not in seen:
                    seen.add(label)
                    modules.append({
                        'name': label,
                        'description': f'Module extracted from diagram',
                        'inputs': [],
                        'outputs': [],
                        'specifications': {}
                    })

        return modules

    async def _consolidate_modules_to_practical(self, high_level_design: Dict[str, Any], initial_modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Consolidate modules to practical buildable units using N8N's Extract Module List logic"""

        # Analyze system complexity to determine appropriate module count
        # This is UNIVERSAL - works for ANY circuit type

        # FIX: Parse description from nested structure
        device_desc = ''
        raw_response = high_level_design.get('raw_response', '')
        if raw_response:
            try:
                import json
                import re
                # Extract JSON from raw_response (might be wrapped in ```json blocks)
                json_match = re.search(r'\{[\s\S]*\}', raw_response)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    device_desc = str(parsed.get('description', '')).lower()
                    self.logger.debug(f"Extracted description from raw_response: {device_desc[:200]}...")
                else:
                    device_desc = raw_response.lower()
            except Exception as e:
                self.logger.warning(f"Could not parse raw_response: {e}")
                device_desc = raw_response.lower()

        # Fallback to direct description field if raw_response parsing failed
        if not device_desc:
            device_desc = str(high_level_design.get('description', '')).lower()

        module_names = [m.get('name', '').lower() for m in initial_modules]

        # Log for debugging
        self.logger.info(f"Analyzing complexity for: {device_desc[:100]}...")
        self.logger.info(f"Initial module count: {len(initial_modules)}")

        # Keep complexity detection SIMPLE - let the AI decide based on module count
        # The AI already knows the appropriate complexity from analyzing the requirements

        # Just use basic indicators to avoid extremes
        is_explicitly_simple = device_desc.startswith('simple ') or 'simple circuit' in device_desc
        has_multiple_channels = any(pattern in device_desc for pattern in ['dual-channel', 'multi-channel', '2-channel', '4-channel', '8-channel'])

        # Enhanced multi-channel detection
        channel_count = 0
        channel_patterns = [
            (r'(\d+)[-\s]?channel', 1),  # "2-channel", "2 channel"
            (r'dual[-\s]?channel', 2),     # "dual-channel", "dual channel"
            (r'stereo', 2),                # stereo implies 2 channels
            (r'quad[-\s]?channel', 4),     # "quad-channel"
            (r'multi[-\s]?channel', 4),    # "multi-channel" (assume 4 as default)
        ]

        for pattern, count in channel_patterns:
            match = re.search(pattern, device_desc, re.IGNORECASE)
            if match:
                if count == 1:  # Extract number from pattern
                    channel_count = int(match.group(1))
                else:
                    channel_count = count
                break

        # Also check module names for channel indication
        if channel_count == 0:
            for i, module in enumerate(module_names):
                if 'channel' in module:
                    # Count channel modules
                    channel_modules = sum(1 for m in module_names if 'channel' in m)
                    if channel_modules > 1:
                        channel_count = channel_modules
                        break

        self.logger.debug(f"Channel count detected: {channel_count}")

        # SIMPLE complexity determination based on module count
        # Let the AI's module count drive the complexity, not keywords
        if is_explicitly_simple:
            complexity = 'simple'
        elif len(initial_modules) >= 8:
            complexity = 'complex'
        elif len(initial_modules) >= 4:
            complexity = 'medium'
        elif len(initial_modules) >= 2:
            complexity = 'simple_to_medium'
        else:
            complexity = 'simple'

        # Set FLEXIBLE target ranges - let the AI decide within reasonable bounds
        # The AI understands the circuit better than keyword matching

        if is_explicitly_simple:
            # User explicitly said "simple" - respect that
            target_min = 1
            target_max = 3
            self.logger.info(f"User requested simple circuit - allowing {target_min}-{target_max} modules")

        elif len(initial_modules) <= 2:
            # Very few modules - probably simple
            target_min = 1
            target_max = 4  # But allow up to 4 if AI thinks it needs more
            self.logger.info(f"Small circuit - allowing {target_min}-{target_max} modules")

        elif len(initial_modules) <= 5:
            # Medium range
            target_min = 2
            target_max = 7  # Flexible upper bound
            self.logger.info(f"Medium circuit - allowing {target_min}-{target_max} modules")

        elif len(initial_modules) <= 8:
            # Larger circuit
            target_min = 3
            target_max = 10  # Allow reasonable expansion
            self.logger.info(f"Complex circuit - allowing {target_min}-{target_max} modules")

        else:
            # Very complex - but still set some reasonable bounds
            target_min = 4
            target_max = 12  # Max 12 to keep it practical
            self.logger.info(f"Very complex circuit - allowing {target_min}-{target_max} modules")

        # Special handling for multi-channel systems
        if channel_count > 1:
            # For multi-channel, ensure we have at least channels + supporting modules
            target_min = max(target_min, channel_count + 3)  # channels + power + control + signal gen minimum
            target_max = max(target_max, channel_count + 6)  # channels + power + control + signal + feedback + protection
            self.logger.info(f"Multi-channel system detected ({channel_count} channels) - adjusted to {target_min}-{target_max} modules")

        # For complex systems, prefer more modules for better separation
        if 'ultrasonic' in device_desc or 'resonance' in device_desc or 'rf' in device_desc:
            target_min = max(target_min, 6)  # Complex systems need proper separation (increased from 5 to 6)
            self.logger.info(f"Complex system detected - minimum modules set to {target_min}")

        # If module count is already good, return as-is
        if target_min <= len(initial_modules) <= target_max:
            self.logger.info(f"Module count {len(initial_modules)} is appropriate for {complexity} circuit")
            return initial_modules

        # Load the Extract Module List prompt from the project's prompt directory
        n8n_prompt_path = Path(__file__).parent.parent / "ai_agents" / "prompts" / "AI Agent - Step 3 - Extract Module List Prompt.txt"

        if n8n_prompt_path.exists():
            with open(n8n_prompt_path, 'r') as f:
                prompt_template = f.read()
        else:
            # Fallback to embedded consolidation logic
            return self._simple_module_consolidation(initial_modules)

        # Prepare the high-level design text
        high_level_text = json.dumps(high_level_design, indent=2)

        # Replace the variable in the prompt
        prompt = prompt_template.replace('{{ $json.highLevelText }}', high_level_text)

        # Add minimum module requirement to the prompt
        min_modules_instruction = f"\n\nCRITICAL REQUIREMENT: This circuit requires a MINIMUM of {target_min} modules and MAXIMUM of {target_max} modules based on its complexity. DO NOT consolidate below {target_min} modules. Multi-channel systems require: Power Supply, Control/MCU, Signal Generation, each Channel Driver, Feedback/Sensing, and Protection circuits as separate modules."
        prompt = prompt + min_modules_instruction

        # Call AI to consolidate modules
        result = await self.ai_manager.call_ai(
            step_name="module_consolidation",
            prompt=prompt,
            context={"high_level_design": high_level_design}
        )

        try:
            # Parse the response
            response = result.get('parsed_response', result.get('raw_response', {}))
            if isinstance(response, str):
                response = json.loads(response)

            # Extract consolidated module names
            consolidated_names = response.get('modules', [])

            # Map the consolidated modules back to the detailed modules
            if consolidated_names:
                consolidated_modules = self._map_consolidated_modules(initial_modules, consolidated_names)

                # CRITICAL: Validate module count meets minimum requirements
                if len(consolidated_modules) < target_min:
                    self.logger.warning(f"AI consolidated to {len(consolidated_modules)} modules, but minimum is {target_min}. Using initial modules instead.")
                    return initial_modules

                return consolidated_modules
            else:
                return initial_modules

        except Exception as e:
            self.logger.warning(f"Module consolidation failed: {e}, using original modules")
            return initial_modules

    def _simple_module_consolidation(self, modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Simple fallback consolidation logic"""
        # Group similar modules
        consolidated = []

        # Power-related modules
        power_modules = [m for m in modules if 'power' in m['name'].lower() or 'supply' in m['name'].lower()]
        if power_modules:
            consolidated.append({
                'name': 'Power_Supply',
                'description': 'Complete power management system',
                'inputs': [],
                'outputs': [],
                'specifications': {}
            })

        # Control modules
        control_modules = [m for m in modules if 'control' in m['name'].lower() or 'master' in m['name'].lower()]
        if control_modules:
            consolidated.append({
                'name': 'Control_System',
                'description': 'Central control and processing',
                'inputs': [],
                'outputs': [],
                'specifications': {}
            })

        # Channel-specific modules (keep separate for multi-channel systems)
        for i in range(1, 5):  # Support up to 4 channels
            channel_modules = [m for m in modules if f'channel_{i}' in m['name'].lower() or f'ch{i}' in m['name'].lower()]
            if channel_modules:
                consolidated.append({
                    'name': f'Channel_{i}',
                    'description': f'Channel {i} complete circuit',
                    'inputs': [],
                    'outputs': [],
                    'specifications': {}
                })

        # If we still have too many, just take the first 6
        if len(consolidated) > 6:
            consolidated = consolidated[:6]

        # If we have too few, use original
        if len(consolidated) < 2:
            return modules[:6]  # Cap at 6

        return consolidated

    def _map_consolidated_modules(self, detailed_modules: List[Dict[str, Any]], consolidated_names: List[str]) -> List[Dict[str, Any]]:
        """Map consolidated module names to detailed module info"""
        result = []

        for name in consolidated_names:
            if isinstance(name, dict):
                # Already a module dict
                result.append(name)
            else:
                # Create a consolidated module
                # Try to find matching detailed modules
                matching = []
                name_lower = name.lower()

                for module in detailed_modules:
                    module_name_lower = module['name'].lower()

                    # Check for keyword matches
                    if ('channel' in name_lower and 'channel' in module_name_lower):
                        # Match channel numbers
                        import re
                        name_num = re.search(r'\d+', name)
                        module_num = re.search(r'\d+', module['name'])
                        if name_num and module_num and name_num.group() == module_num.group():
                            matching.append(module)
                    elif any(keyword in module_name_lower for keyword in name_lower.split('_')):
                        matching.append(module)

                # Create consolidated module
                if matching:
                    # Merge specifications from matching modules
                    specs = {}
                    for m in matching:
                        specs.update(m.get('specifications', {}))

                    result.append({
                        'name': name,
                        'description': matching[0].get('description', ''),
                        'inputs': matching[0].get('inputs', []),
                        'outputs': matching[0].get('outputs', []),
                        'specifications': specs
                    })
                else:
                    # No match, create basic module
                    result.append({
                        'name': name,
                        'description': f'{name} module',
                        'inputs': [],
                        'outputs': [],
                        'specifications': {}
                    })

        return result

    def _create_default_diagram(self, modules: List[Dict[str, Any]]) -> str:
        """Create a proper block diagram from modules with clean topology"""

        # Build the diagram based on actual modules
        dot_lines = [
            'digraph G {',
            '  rankdir=LR;',
            '  node[shape=box,style=filled,fillcolor=lightblue];',
            ''
        ]

        # Process modules and categorize them
        power_mods = []
        control_mods = []
        signal_mods = []
        amplifier_mods = []
        matching_mods = []
        sensing_mods = []
        other_mods = []

        for module in modules:
            name = module.get('name', '')
            name_lower = name.lower()

            # Clean name for display
            display_name = name.replace('_', ' ')
            safe_name = name.replace(' ', '_').replace('(', '').replace(')', '').replace(',', '')

            # Categorize module (TC #78 fix: added 'channel' and 'module' keywords for colored diagrams)
            if 'power' in name_lower or 'supply' in name_lower:
                power_mods.append((safe_name, display_name))
                color = 'lightgreen'
            elif 'control' in name_lower or 'mcu' in name_lower or 'controller' in name_lower or 'master' in name_lower:
                control_mods.append((safe_name, display_name))
                color = 'lightyellow'
            elif 'signal' in name_lower or 'dds' in name_lower or 'generator' in name_lower:
                signal_mods.append((safe_name, display_name))
                color = 'lightblue'
            elif 'amplifier' in name_lower or 'driver' in name_lower or 'channel' in name_lower or 'module' in name_lower:
                # Channel/module types get coral color (same as amplifier/driver)
                amplifier_mods.append((safe_name, display_name))
                color = 'lightcoral'
            elif 'matching' in name_lower or 'impedance' in name_lower:
                matching_mods.append((safe_name, display_name))
                color = 'lightsalmon'
            elif 'sens' in name_lower or 'feedback' in name_lower or 'monitor' in name_lower or 'protection' in name_lower:
                sensing_mods.append((safe_name, display_name))
                color = 'lightcyan'
            elif 'interface' in name_lower or 'output' in name_lower or 'front' in name_lower or 'panel' in name_lower:
                # Interface/output modules get a distinct color
                other_mods.append((safe_name, display_name))
                color = 'plum'
            else:
                other_mods.append((safe_name, display_name))
                color = 'lightgray'

            # Add node
            dot_lines.append(f'  "{safe_name}"[label="{display_name}",fillcolor={color}];')

        dot_lines.append('')

        # Create logical connections
        # Power → Everything
        for power_safe, _ in power_mods:
            for ctrl_safe, _ in control_mods:
                dot_lines.append(f'  "{power_safe}" -> "{ctrl_safe}";')
            for sig_safe, _ in signal_mods:
                dot_lines.append(f'  "{power_safe}" -> "{sig_safe}";')
            for amp_safe, _ in amplifier_mods:
                dot_lines.append(f'  "{power_safe}" -> "{amp_safe}";')

        # Controller → Signal Generators
        for ctrl_safe, _ in control_mods:
            for sig_safe, _ in signal_mods:
                dot_lines.append(f'  "{ctrl_safe}" -> "{sig_safe}";')

        # Signal → Amplifiers
        for sig_safe, _ in signal_mods:
            for amp_safe, _ in amplifier_mods:
                dot_lines.append(f'  "{sig_safe}" -> "{amp_safe}";')

        # Amplifiers → Matching (if exists)
        if matching_mods:
            for amp_safe, _ in amplifier_mods:
                for match_safe, _ in matching_mods:
                    dot_lines.append(f'  "{amp_safe}" -> "{match_safe}";')

        # Sensing → Controller (feedback loop)
        for sens_safe, _ in sensing_mods:
            for ctrl_safe, _ in control_mods:
                dot_lines.append(f'  "{sens_safe}" -> "{ctrl_safe}";')

        dot_lines.append('}')
        return '\n'.join(dot_lines)

    def _determine_module_type(self, module_name: str) -> str:
        """Determine module type from its name"""
        name_lower = module_name.lower()

        if 'power' in name_lower or 'supply' in name_lower:
            return 'power'
        elif 'control' in name_lower or 'monitor' in name_lower or 'mcu' in name_lower:
            return 'control'
        elif 'signal' in name_lower or 'generator' in name_lower or 'dds' in name_lower:
            return 'signal'
        elif 'channel' in name_lower or 'driver' in name_lower or 'amplifier' in name_lower:
            return 'output'
        else:
            return 'generic'

    def _save_diagrams(self, diagrams: List[Dict[str, Any]], output_data: Dict[str, Any] = None):
        """Save ONLY DOT and PNG files - NO JSON!"""

        # If no diagrams provided, create a default one
        if not diagrams:
            self.logger.warning("No diagrams found in AI response - creating default block diagram")
            # Create a default diagram based on modules
            if output_data:
                modules = output_data.get('modules', [])
            else:
                state = self.state_manager.get_state()
                step_2_output = state.get('step_2_output', {})
                modules = step_2_output.get('modules', [])
            if modules:
                default_dot = self._create_default_diagram(modules)
                diagrams = [{
                    'filename': 'system_overview',
                    'graphviz_dot': default_dot
                }]

        # Save DOT files and render to PNG
        for diagram in diagrams:
            if 'graphviz_dot' in diagram:
                filename = diagram.get('filename', 'diagram')

                # Save DOT file
                dot_path = os.path.join(self.output_paths['highlevel'], f"{filename}.dot")
                with open(dot_path, 'w') as f:
                    f.write(diagram['graphviz_dot'])

                # Always try to render PNG
                try:
                    import subprocess
                    png_path = os.path.join(self.output_paths['highlevel'], f"{filename}.png")
                    result = subprocess.run(
                        ['dot', '-Tpng', '-o', png_path],
                        input=diagram['graphviz_dot'],
                        text=True,
                        capture_output=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        self.logger.info(f"✓ Rendered {filename}.png successfully")
                        if self.enhanced_logger:
                            self.enhanced_logger.log_subprocess('step2_high_level',
                                f'dot -Tpng -o {png_path}',
                                'PNG rendered successfully',
                                result.stderr,
                                result.returncode)
                    else:
                        self.logger.error(f"Failed to render {filename}.png: {result.stderr}")
                        if self.enhanced_logger:
                            self.enhanced_logger.log_subprocess('step2_high_level',
                                f'dot -Tpng -o {png_path}',
                                '',
                                result.stderr,
                                result.returncode)
                except Exception as e:
                    self.logger.warning(f"Could not render PNG: {e}")
                    if self.enhanced_logger:
                        self.enhanced_logger.log_warning('step2_high_level',
                            f"PNG rendering failed: {e}",
                            context="Graphviz")

        # DON'T SAVE JSON FILES - Pass data through state only!
        # The user was VERY clear - ONLY PNG and DOT files in highlevel folder!

        self.logger.info(f"Saved {len(diagrams)} diagrams (DOT and PNG) to {self.output_paths['highlevel']}")

    def _save_high_level_design(self, high_level_response: Dict[str, Any], modules: List[Dict[str, Any]]):
        """Save high-level design and modules to files"""

        # If response has raw_response with JSON string, parse it first
        parsed_response = high_level_response
        if 'raw_response' in high_level_response and isinstance(high_level_response['raw_response'], str):
            try:
                parsed = self._parse_ai_response(high_level_response['raw_response'])
                if isinstance(parsed, dict):
                    parsed_response = parsed
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                self.logger.debug(f"Could not re-parse raw response: {e}")

        # Save high-level design JSON
        design_path = os.path.join(self.output_paths['highlevel'], 'high_level_design.json')
        with open(design_path, 'w') as f:
            json.dump(parsed_response, f, indent=2)

        # Save modules list separately for Step 3
        modules_path = os.path.join(self.output_paths['highlevel'], 'modules.json')
        with open(modules_path, 'w') as f:
            json.dump(modules, f, indent=2)

        self.logger.info(f"Saved high-level design and {len(modules)} modules to {self.output_paths['highlevel']}")

    def _get_fallback_prompt(self) -> str:
        """Fallback prompt if prompt file not found"""
        return """You are an expert electronic systems architect. Create a high-level block diagram design.

DEVICE PURPOSE: {{ $json.designParameters.devicePurpose }}

SPECIFICATIONS:
{{ JSON.stringify($json.designParameters.generalSpecifications, null, 2) }}

Create a system architecture with:
1. Major functional blocks/modules
2. Interfaces between modules
3. Signal flow
4. Power distribution overview

Output JSON with:
- diagrams: Array of Graphviz DOT diagrams
- modules: List of system modules
- interfaces: Key connections

Format:
{
  "diagrams": [{
    "filename": "system_overview",
    "graphviz_dot": "digraph { ... }"
  }],
  "modules": [{
    "name": "Module Name",
    "description": "What it does",
    "inputs": [],
    "outputs": []
  }]
}"""

    def _create_fallback_design(self, design_params: Dict[str, Any]) -> Dict[str, Any]:
        """Create a fallback design when AI fails"""

        # Extract basic info from design params
        device_purpose = design_params.get('designParameters', {}).get('devicePurpose', 'Electronic System')
        specs = design_params.get('designParameters', {}).get('generalSpecifications', {})

        # Create basic modules based on device purpose
        modules = self._create_default_modules(design_params)

        # Create a basic diagram
        diagram_dot = self._create_default_diagram(modules)

        return {
            'diagrams': [{
                'filename': 'system_overview',
                'graphviz_dot': diagram_dot
            }],
            'modules': modules,
            'devicePurpose': device_purpose,
            'specifications': specs,
            'interfaces': [],
            'raw_response': 'Fallback design created due to AI unavailability'
        }

    def _create_default_modules(self, design_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create default modules based on device purpose"""

        device_purpose = design_params.get('designParameters', {}).get('devicePurpose', '').lower()

        # Detect complexity
        complexity = 'medium'

        complexity_indicators = {
            'simple': ['led', 'blink', 'button', 'switch', 'buzzer', 'single', 'basic'],
            'medium': ['sensor', 'monitor', 'control', 'charger', 'supply', 'driver', 'iot'],
            'complex': ['channel', 'multi', 'test', 'measurement', 'rf', 'radio', 'acquisition'],
        }

        for level, keywords in complexity_indicators.items():
            if any(keyword in device_purpose for keyword in keywords):
                complexity = level
                break

        # Detect number of channels if applicable
        import re
        channel_match = re.search(r'(\d+)[\s-]?channel', device_purpose)
        num_channels = int(channel_match.group(1)) if channel_match else 0

        # Create modules based on complexity
        modules = []

        # Always add power supply for non-trivial circuits
        if complexity != 'simple':
            modules.append({
                'name': 'Power_Supply',
                'description': 'Power management and distribution',
                'inputs': ['Power input'],
                'outputs': ['Regulated voltages'],
                'specifications': {}
            })

        # Add control module for medium/complex
        if complexity in ['medium', 'complex']:
            modules.append({
                'name': 'Control_System',
                'description': 'Central control and monitoring',
                'inputs': ['User interface', 'Sensors'],
                'outputs': ['Control signals'],
                'specifications': {}
            })

        # Add channel modules if detected
        if num_channels > 0:
            for i in range(1, num_channels + 1):
                modules.append({
                    'name': f'Channel_{i}',
                    'description': f'Channel {i} processing',
                    'inputs': ['Input signal', 'Control'],
                    'outputs': ['Output signal'],
                    'specifications': {}
                })

        # Add generic modules if we don't have enough
        if len(modules) < 2:
            modules.append({
                'name': 'Main_Circuit',
                'description': 'Main circuit implementation',
                'inputs': ['Input'],
                'outputs': ['Output'],
                'specifications': {}
            })

        if len(modules) < 2:
            modules.append({
                'name': 'Interface',
                'description': 'Input/Output interface',
                'inputs': ['External'],
                'outputs': ['Processed'],
                'specifications': {}
            })

        return modules

    # ------------------------------------------------------------------
    # Professional summary document
    # ------------------------------------------------------------------

    def _write_design_summary(
        self,
        high_level_response: Dict[str, Any],
        modules: List[Dict[str, Any]],
        highlevel_dir: str,
    ) -> None:
        """Generate a professional Markdown summary of the high-level design.

        Writes ``highlevel_design_summary.md`` into *highlevel_dir*.  The method
        is intentionally lenient: it never raises on missing data—it simply
        omits the corresponding section so the rest of the document still
        renders correctly.
        """

        # --- Resolve the parsed AI response (may be nested under raw_response)
        parsed = self._resolve_parsed_response(high_level_response)

        lines: List[str] = []

        self._summary_header(lines, parsed)
        self._summary_modules(lines, modules)
        self._summary_connections(lines, parsed)
        self._summary_power_budget(lines, parsed)
        self._summary_design_rationale(lines, parsed)

        # --- Footer
        lines.append("---")
        lines.append(
            f"*Generated by CopperPilot Step 2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
        )
        lines.append("")

        out_path = os.path.join(highlevel_dir, "highlevel_design_summary.md")
        Path(out_path).write_text("\n".join(lines), encoding="utf-8")
        self.logger.info(f"Design summary written to {out_path}")

    # -- helpers for _write_design_summary --------------------------------

    def _resolve_parsed_response(self, hlr: Dict[str, Any]) -> Dict[str, Any]:
        """Extract the parsed JSON dict from *high_level_response*.

        The response may already be fully parsed, or the real JSON may live
        inside ``raw_response`` as a string that needs a second parse pass.
        """
        if "modules" in hlr:
            return hlr

        raw = hlr.get("raw_response")
        if isinstance(raw, str):
            try:
                return self._parse_ai_response(raw)
            except Exception:
                pass
        return hlr

    def _summary_header(self, lines: List[str], parsed: Dict[str, Any]) -> None:
        """Title and system overview paragraph."""
        lines.append("# High-Level Design Summary")
        lines.append("")
        description = parsed.get("description", "")
        if description:
            lines.append("## System Overview")
            lines.append("")
            lines.append(description)
            lines.append("")

    def _summary_modules(self, lines: List[str], modules: List[Dict[str, Any]]) -> None:
        """Module summary table."""
        if not modules:
            return

        lines.append("## Module Architecture")
        lines.append("")
        lines.append("| # | Module | Type | Description | Key Specifications |")
        lines.append("|---|--------|------|-------------|--------------------|")

        for idx, mod in enumerate(modules, 1):
            name = str(mod.get("name", "—")).replace("|", "/")
            mtype = str(mod.get("type", mod.get("moduleType", "—"))).replace("|", "/")
            desc = str(mod.get("description", "—")).replace("|", "/")
            specs = mod.get("specifications", {})
            if isinstance(specs, dict) and specs:
                spec_str = "; ".join(f"{k}: {v}" for k, v in specs.items())
            else:
                spec_str = "—"
            spec_str = str(spec_str).replace("|", "/")
            lines.append(f"| {idx} | **{name}** | {mtype} | {desc} | {spec_str} |")

        lines.append("")

    def _summary_connections(self, lines: List[str], parsed: Dict[str, Any]) -> None:
        """Connection matrix table."""
        connections = parsed.get("connections", [])
        if not connections:
            return

        lines.append("## Inter-Module Connections")
        lines.append("")
        lines.append("| # | From | To | Type | Notes |")
        lines.append("|---|------|----|------|-------|")

        for idx, conn in enumerate(connections, 1):
            src = str(conn.get("from", "—")).replace("|", "/")
            dst = str(conn.get("to", "—")).replace("|", "/")
            ctype = str(conn.get("type", "—")).replace("|", "/")
            notes = conn.get("notes", conn.get("wire", ""))
            notes = str(notes).replace("|", "/") if notes else "—"
            lines.append(f"| {idx} | {src} | {dst} | {ctype} | {notes} |")

        lines.append("")

    def _summary_power_budget(self, lines: List[str], parsed: Dict[str, Any]) -> None:
        """Power budget section from the structured ``power_budget`` field."""
        pb = parsed.get("power_budget", {})
        if not isinstance(pb, dict) or not pb:
            return

        lines.append("## Power Budget")
        lines.append("")

        # Top-level figures
        summary_keys = [
            ("mains_input", "Mains Input"),
            ("total_power_estimate", "Total Power Estimate"),
            ("efficiency_estimate", "Efficiency Estimate"),
            ("thermal_dissipation", "Thermal Dissipation"),
        ]
        for key, label in summary_keys:
            val = pb.get(key)
            if val:
                lines.append(f"- **{label}:** {val}")
        lines.append("")

        # Rail details
        rails = pb.get("rails", [])
        if rails:
            lines.append("### Power Rails")
            lines.append("")
            lines.append("| Rail | Voltage | Max Current | Consumers |")
            lines.append("|------|---------|-------------|-----------|")
            for rail in rails:
                rname = rail.get("name", "—")
                rvolt = rail.get("voltage", "—")
                rcurr = rail.get("max_current", "—")
                consumers = rail.get("consumers", [])
                cons_str = ", ".join(consumers) if consumers else "—"
                lines.append(f"| {rname} | {rvolt} | {rcurr} | {cons_str} |")
            lines.append("")

    def _summary_design_rationale(self, lines: List[str], parsed: Dict[str, Any]) -> None:
        """Design rationale — structured format or fallback to legacy design_notes."""
        rationale = parsed.get("design_rationale", [])
        if rationale and isinstance(rationale, list):
            lines.append("## Design Rationale")
            lines.append("")
            for idx, entry in enumerate(rationale, 1):
                if isinstance(entry, dict):
                    topic = entry.get("topic", f"Decision {idx}")
                    decision = entry.get("decision", "")
                    alternatives = entry.get("alternatives_considered", "")
                    lines.append(f"### {idx}. {topic}")
                    lines.append("")
                    if decision:
                        lines.append(f"**Decision:** {decision}")
                        lines.append("")
                    if alternatives:
                        lines.append(f"*Alternatives considered:* {alternatives}")
                        lines.append("")
                elif isinstance(entry, str):
                    lines.append(f"{idx}. {entry}")
                    lines.append("")
            return

        # Fallback: legacy design_notes (array of strings)
        notes = parsed.get("design_notes", [])
        if notes and isinstance(notes, list):
            lines.append("## Design Notes")
            lines.append("")
            for idx, note in enumerate(notes, 1):
                if isinstance(note, str) and note.strip():
                    lines.append(f"{idx}. {note.strip()}")
                    lines.append("")
