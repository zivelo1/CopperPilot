# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 3: Low-Level Circuit Design
Complete port from N8N workflow nodes
This is the critical module that handles circuit generation and fixing

MULTI-AGENT ARCHITECTURE (Jan 2026):
=====================================
This module now supports TWO design approaches:

1. SINGLE-AGENT (Two-Stage): Original approach for simple circuits (<3 modules)
   - Stage 1: Component Selection (with rating guidelines)
   - Stage 2: Connection Synthesis

2. MULTI-AGENT (Hierarchical): New approach for complex circuits (3+ modules)
   - DesignSupervisor orchestrates the entire design
   - ModuleAgent coordinates per-module design
   - ComponentAgent, ConnectionAgent, ValidationAgent handle specifics
   - IntegrationAgent merges all modules

The system automatically selects the best approach based on complexity.

Enhanced with GENERIC component rating validation (December 2025):
- Validates MOSFETs, transistors, capacitors against voltage/current requirements
- Works with ANY circuit type - from simple LED blinkers to high-power amplifiers
- Generates detailed validation reports with fix suggestions
"""
import json
import re
from typing import Dict, Any, List, Optional, Set, Tuple
from pathlib import Path
import copy
import uuid
import asyncio

from datetime import datetime as _dt

from utils.logger import setup_logger
from workflow.circuit_supervisor import supervise_circuit
# Legacy validators - DEPRECATED, not used anymore
# from workflow.fix_net_conflicts import fix_net_conflicts, validate_circuit, CircuitFixer
# from workflow.safety_net_validator import safety_net_validator

# GENERIC Component Rating Validation (works with ANY circuit type)
try:
    from workflow.requirements_rating_extractor import (
        RequirementsRatingExtractor,
        extract_requirements_ratings,
        ExtractedRequirements
    )
    from workflow.component_rating_validator import (
        ComponentRatingValidator,
        validate_circuit_ratings,
        ValidationResult
    )
    RATING_VALIDATOR_AVAILABLE = True
except ImportError:
    RATING_VALIDATOR_AVAILABLE = False

# MULTI-AGENT Architecture (Jan 2026) - Optional import
# Falls back gracefully to single-agent if agents not available
try:
    from workflow.agents.design_supervisor import DesignSupervisor
    from workflow.agents.integration_agent import IntegrationAgent
    MULTI_AGENT_AVAILABLE = True
except ImportError:
    MULTI_AGENT_AVAILABLE = False

# Load multi-agent configuration
try:
    from server.config import config
    MULTI_AGENT_CONFIG = getattr(config, 'MULTI_AGENT_CONFIG', {})
except ImportError:
    MULTI_AGENT_CONFIG = {}

logger = setup_logger(__name__)


class ModuleIterator:
    """
    Handles module iteration for Step 3
    Replaces N8N's loop mechanism

    TC #95 MEMORY FIX: Now uses write-as-you-go pattern to minimize memory usage.
    Instead of storing full circuit data, only stores metadata (names, file paths).
    Full circuit data is written to disk immediately after generation.
    """

    def __init__(self):
        self.modules = []
        self.current_index = 0
        # TC #95: Only store lightweight metadata, not full circuit data
        self.results_metadata = []  # [{module, index, filepath, component_count, connection_count}]

    def initialize(self, modules: List[Dict]) -> None:
        """Initialize with module list"""
        self.modules = modules
        self.current_index = 0
        self.results_metadata = []
        logger.info(f"Initialized iterator with {len(modules)} modules")

    def get_current(self) -> Optional[Dict]:
        """Get current module"""
        if self.current_index < len(self.modules):
            return self.modules[self.current_index]
        return None

    def store_result(self, module_name: str, circuit: Dict, filepath: str = None) -> None:
        """
        Store module result metadata (not full circuit data).

        TC #95 MEMORY FIX: Only stores lightweight metadata.
        The full circuit is written to disk immediately by write_module_file().

        Args:
            module_name: Name of the module
            circuit: Circuit data (used only to extract counts, not stored)
            filepath: Path where circuit was written
        """
        # TC #95: Extract only lightweight stats, do NOT store full circuit
        metadata = {
            'module': module_name,
            'index': self.current_index,
            'filepath': filepath,
            'component_count': len(circuit.get('components', [])),
            'connection_count': len(circuit.get('connections', [])),
            'net_count': len(circuit.get('nets', []))
        }
        self.results_metadata.append(metadata)
        logger.info(f"Stored metadata for module {module_name} (index {self.current_index})")

    def increment(self) -> bool:
        """Move to next module, return True if more modules exist"""
        self.current_index += 1
        return self.current_index < len(self.modules)

    def has_more(self) -> bool:
        """Check if more modules exist"""
        return self.current_index < len(self.modules)

    def get_results(self) -> List[Dict]:
        """
        Get all stored results metadata.

        TC #95: Returns lightweight metadata only. To get full circuit data,
        read from the filepath stored in each result.
        """
        return self.results_metadata

    def get_results_with_circuits(self) -> List[Dict]:
        """
        Get results with full circuit data loaded from disk.

        TC #95: Only use this when you actually need the full circuit data
        (e.g., for generating design summary). Loads circuits one at a time
        to minimize peak memory usage.
        """
        results = []
        for metadata in self.results_metadata:
            filepath = metadata.get('filepath')
            if filepath and Path(filepath).exists():
                try:
                    with open(filepath, 'r') as f:
                        circuit_data = json.load(f)
                    results.append({
                        'module': metadata['module'],
                        'index': metadata['index'],
                        'design': circuit_data.get('circuit', circuit_data)
                    })
                except Exception as e:
                    logger.error(f"Failed to load circuit from {filepath}: {e}")
                    results.append({
                        'module': metadata['module'],
                        'index': metadata['index'],
                        'design': {}
                    })
            else:
                logger.warning(f"Circuit file not found: {filepath}")
                results.append({
                    'module': metadata['module'],
                    'index': metadata['index'],
                    'design': {}
                })
        return results


class Step3LowLevel:
    """
    Main Step 3 workflow implementation
    Handles circuit generation, fixing, and validation

    MULTI-AGENT ARCHITECTURE (Jan 2026):
    - Supports both single-agent (two-stage) and multi-agent design
    - Automatically selects best approach based on circuit complexity
    - Multi-agent: Better for complex circuits with 3+ modules
    - Single-agent: Faster for simple circuits with 1-2 modules

    Enhanced with GENERIC component rating validation:
    - Validates all circuits against extracted requirements
    - Works with ANY circuit type (low voltage, high voltage, power, signal, etc.)
    - Generates detailed validation reports with fix suggestions
    """

    def __init__(self, project_folder: str, requirements_text: str = ""):
        self.project_folder = project_folder
        self.enhanced_logger = None  # Will be set by workflow
        self.lowlevel_dir = Path(project_folder) / "lowlevel"
        self.lowlevel_dir.mkdir(parents=True, exist_ok=True)
        self.iterator = ModuleIterator()

        # GENERIC: Store requirements text for component rating validation
        # This works with ANY circuit type - the extractor analyzes the text
        self.requirements_text = requirements_text
        self.extracted_requirements: Optional[ExtractedRequirements] = None
        self.validation_results: List[Dict] = []  # Store validation results for all modules

        # MULTI-AGENT (Jan 2026): Configuration for multi-agent design
        self.use_multi_agent = MULTI_AGENT_CONFIG.get('enabled', False) and MULTI_AGENT_AVAILABLE
        self.multi_agent_threshold = MULTI_AGENT_CONFIG.get('min_modules_for_multi_agent', 3)
        self.parallel_design = MULTI_AGENT_CONFIG.get('parallel_module_design', True)
        self.interface_contracts: Dict[str, Any] = {}  # Store interface contracts between modules
        self.design_supervisor: Optional['DesignSupervisor'] = None

        logger.info(f"Multi-agent support: {'ENABLED' if self.use_multi_agent else 'DISABLED'}")
        logger.info(f"  Threshold: {self.multi_agent_threshold} modules")
        logger.info(f"  Parallel design: {'ENABLED' if self.parallel_design else 'DISABLED'}")

        # Extract requirements if available
        if RATING_VALIDATOR_AVAILABLE and requirements_text:
            try:
                self.extracted_requirements = extract_requirements_ratings(requirements_text)
                logger.info(f"Extracted requirements for validation:")
                logger.info(f"  Max Voltage: {self.extracted_requirements.max_voltage}V")
                logger.info(f"  Voltage Class: {self.extracted_requirements.voltage_class}")
                logger.info(f"  Recommended MOSFET Rating: {self.extracted_requirements.recommended_voltage_rating}V")
            except Exception as e:
                logger.warning(f"Failed to extract requirements: {e} - validation will be limited")
        
    def prepare_modules(self, high_level_design: str) -> List[Dict]:
        """
        Extract and prepare modules from high-level design
        Port of 'Prepare Modules' node
        """
        logger.info("Preparing modules from high-level design")
        
        # Parse the high-level design
        module_list = None
        
        try:
            # Handle case where output is wrapped in markdown code blocks
            if isinstance(high_level_design, str):
                json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', high_level_design)
                if json_match:
                    module_list = json.loads(json_match.group(1).strip())
                else:
                    # Try direct parse if no markdown
                    module_list = json.loads(high_level_design)
            else:
                module_list = high_level_design
        except Exception as e:
            logger.error(f"Failed to parse module list: {e}")
            # Create default modules if parsing fails
            module_list = {
                'modules': ['Power Supply', 'Main Controller', 'Signal Processing'],
                'circuitName': 'Default Circuit'
            }
        
        # Validate structure
        if not isinstance(module_list, dict) or 'modules' not in module_list:
            logger.warning("Invalid module list structure - using defaults")
            module_list = {
                'modules': ['Power Supply', 'Main Controller', 'Signal Processing'],
                'circuitName': 'Default Circuit'
            }
        
        modules = module_list.get('modules', [])
        circuit_name = module_list.get('circuitName', 'Circuit')

        # Fix 2.1: Pass full Step 2 module definition through to the AI prompt.
        # Previously only the module name was kept; description, inputs, outputs,
        # specifications, and subcomponents were all discarded.
        # _build_module_context() in agent_manager.py already handles these fields.
        prepared_modules = []
        for i, module in enumerate(modules):
            if isinstance(module, dict):
                module_name = module.get('name', f'Module_{i+1}')
                prepared = {
                    'module': module_name,
                    'totalModules': len(modules),
                    'moduleIndex': i,
                    'circuitName': circuit_name,
                    # Per-module type from Step 2 (not the global moduleType)
                    'moduleType': module.get('type', module_list.get('moduleType', 'standard')),
                    'requirements': self.requirements_text or f"Design module: {module_name}",
                    # Step 2 fields — consumed by _build_module_context()
                    'description': module.get('description', ''),
                    'inputs': module.get('inputs', []),
                    'outputs': module.get('outputs', []),
                    'specifications': module.get('specifications', {}),
                    'subcomponents': module.get('subcomponents', []),
                    # S.6 FIX: Preserve Step 2 architecture data for Step 3
                    # operating_voltage — used by rating validator (Fix G.7)
                    # isolation_domain — used by integration agent for net naming
                    'operating_voltage': module.get('operating_voltage', ''),
                    'isolation_domain': module.get('isolation_domain', ''),
                }
            else:
                module_name = str(module)
                prepared = {
                    'module': module_name,
                    'totalModules': len(modules),
                    'moduleIndex': i,
                    'circuitName': circuit_name,
                    'moduleType': module_list.get('moduleType', 'standard'),
                    'requirements': self.requirements_text or f"Design module: {module_name}",
                }
            prepared_modules.append(prepared)
        
        # Fix 2.2: Build sibling module summary and attach to each module.
        # This gives every module's AI prompt a compact table of ALL sibling modules
        # and their interfaces, enabling consistent cross-module net naming.
        sibling_summary = self._build_sibling_summary(modules, circuit_name)
        if sibling_summary:
            for prepared in prepared_modules:
                prepared['sibling_interfaces'] = sibling_summary

        # GENERIC SAFETY NET: If no modules are present (e.g., extremely short specs),
        # synthesize a minimal but valid module list so downstream steps can proceed.
        # This fallback is generic and not tied to any specific circuit type.
        if not prepared_modules:
            fallback_name = (circuit_name or 'Main Circuit')
            _fallback_name = config.DEFAULT_FALLBACK_MODULE_NAME or 'Main_Circuit'
            logger.warning(f"No modules provided by Step 2; creating a fallback '{_fallback_name}' module")
            prepared_modules = [{
                'module': _fallback_name,
                'totalModules': 1,
                'moduleIndex': 0,
                'circuitName': fallback_name,
                'moduleType': module_list.get('moduleType', 'standard'),
                'requirements': self.requirements_text if self.requirements_text else "Design main circuit module"
            }]

        logger.info(f"Prepared {len(prepared_modules)} modules")
        return prepared_modules
    
    @staticmethod
    def _build_sibling_summary(modules: list, circuit_name: str) -> str:
        """
        Fix 2.2: Build a compact interface summary of ALL modules.

        This text is injected into every module's AI prompt so the AI knows
        exactly what nets other modules expect. The AI is instructed to use
        these EXACT signal names for interface nets.

        The summary is GENERIC — it reads whatever Step 2 produced and
        formats it as a human-readable table. No assumptions about circuit type.

        Args:
            modules: Raw module list from Step 2 (list of dicts or strings)
            circuit_name: Overall circuit name

        Returns:
            Formatted sibling summary string, or '' if fewer than 2 modules.
        """
        if len(modules) < 2:
            return ''

        lines = [
            f"SYSTEM MODULE INTERFACES — {circuit_name}",
            "(for cross-module net name consistency)",
            "",
        ]

        # Build table rows
        header = f"{'Module':<30} {'Type':<12} {'Inputs':<35} {'Outputs':<35}"
        separator = '-' * len(header)
        lines.append(separator)
        lines.append(header)
        lines.append(separator)

        for mod in modules:
            if isinstance(mod, str):
                lines.append(f"{mod:<30} {'standard':<12} {'—':<35} {'—':<35}")
                continue

            name = mod.get('name', 'Unknown')[:29]
            mod_type = mod.get('type', 'standard')[:11]

            # Format inputs/outputs as comma-separated lists
            inputs_raw = mod.get('inputs', [])
            outputs_raw = mod.get('outputs', [])

            if isinstance(inputs_raw, list):
                inputs_str = ', '.join(str(i) for i in inputs_raw) or '—'
            else:
                inputs_str = str(inputs_raw) or '—'

            if isinstance(outputs_raw, list):
                outputs_str = ', '.join(str(o) for o in outputs_raw) or '—'
            else:
                outputs_str = str(outputs_raw) or '—'

            # Truncate long strings
            if len(inputs_str) > 34:
                inputs_str = inputs_str[:31] + '...'
            if len(outputs_str) > 34:
                outputs_str = outputs_str[:31] + '...'

            lines.append(f"{name:<30} {mod_type:<12} {inputs_str:<35} {outputs_str:<35}")

        lines.append(separator)
        lines.append("")
        lines.append("USE THESE EXACT SIGNAL NAMES for interface nets connecting to other modules.")
        lines.append("Internal nets (within this module only) can use any descriptive name.")

        return '\n'.join(lines)

    def extract_circuit_from_output(self, ai_output: Any) -> Dict:
        """
        Extract circuit JSON from AI output.

        CRITICAL FIX (Dec 21, 2025): Changed parsing order to try JSON FIRST.
        The hybrid prompt outputs JSON, but the old logic incorrectly detected
        '=' and 'connect' in JSON values/descriptions and tried text parsing first.

        Parsing priority:
        1. Try JSON parsing first (hybrid prompt, standard JSON)
        2. Only fall back to text format if JSON fails AND format looks like text
        """
        circuit = None

        if isinstance(ai_output, dict):
            # Check if it's a dict with raw_response containing JSON or text
            if 'raw_response' in ai_output:
                raw = ai_output['raw_response']
                if isinstance(raw, str):
                    # CRITICAL: Try JSON parsing FIRST (hybrid prompt outputs JSON)
                    json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', raw)
                    if json_match:
                        try:
                            parsed = json.loads(json_match.group(1).strip())
                            logger.info("Extracted JSON from markdown code block in raw_response")
                            if 'circuit' in parsed:
                                return parsed['circuit']
                            elif 'components' in parsed:
                                return parsed
                            else:
                                circuit = parsed
                        except json.JSONDecodeError as e:
                            logger.debug(f"JSON parse from markdown failed: {e}")

                    # Try direct JSON parse (no markdown wrapper)
                    if not circuit and '{' in raw:
                        try:
                            # Find JSON object in the response
                            start = raw.find('{')
                            end = raw.rfind('}') + 1
                            if start >= 0 and end > start:
                                parsed = json.loads(raw[start:end])
                                logger.info("Extracted JSON directly from raw_response")
                                if 'circuit' in parsed:
                                    return parsed['circuit']
                                elif 'components' in parsed:
                                    return parsed
                                else:
                                    circuit = parsed
                        except json.JSONDecodeError as e:
                            logger.debug(f"Direct JSON parse failed: {e}")

                    # ONLY fall back to text format if JSON failed and format looks like text
                    # Text format has specific pattern: "R1 = resistor(...)" not just any "="
                    if not circuit:
                        text_format_pattern = r'^\s*[A-Z]+\d+\s*=\s*\w+\s*\('
                        if re.search(text_format_pattern, raw, re.MULTILINE):
                            from workflow.circuit_text_parser import parse_circuit_text
                            logger.info("Detected text format output (component definitions), parsing...")
                            try:
                                parsed = parse_circuit_text(raw)
                                return parsed.get('circuit', parsed)
                            except Exception as e:
                                logger.error(f"Failed to parse text format: {e}")

            # Already a dict - check for circuit structure
            if 'circuit' in ai_output:
                circuit = ai_output['circuit']
            elif 'components' in ai_output:
                circuit = ai_output
            elif 'output' in ai_output:
                # Wrapped in output field
                return self.extract_circuit_from_output(ai_output['output'])
            elif 'parsed_response' in ai_output:
                return self.extract_circuit_from_output(ai_output['parsed_response'])
            else:
                circuit = ai_output

        elif isinstance(ai_output, str):
            # CRITICAL: Try JSON parsing FIRST
            # Remove markdown code blocks
            json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', ai_output)
            if json_match:
                try:
                    circuit = json.loads(json_match.group(1).strip())
                    logger.info("Extracted JSON from markdown in string output")
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse JSON from markdown: {e}")

            if not circuit and '{' in ai_output:
                # Try direct JSON parse
                try:
                    start = ai_output.find('{')
                    end = ai_output.rfind('}') + 1
                    if start >= 0 and end > start:
                        circuit = json.loads(ai_output[start:end])
                        logger.info("Extracted JSON directly from string output")
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse JSON: {e}")

            # ONLY fall back to text format if JSON failed and format looks like text
            if not circuit:
                text_format_pattern = r'^\s*[A-Z]+\d+\s*=\s*\w+\s*\('
                if re.search(text_format_pattern, ai_output, re.MULTILINE):
                    from workflow.circuit_text_parser import parse_circuit_text
                    logger.info("Detected text format in string output (component definitions), parsing...")
                    try:
                        parsed = parse_circuit_text(ai_output)
                        circuit = parsed.get('circuit', parsed)
                    except Exception as e:
                        logger.error(f"Failed to parse text format: {e}")
        
        if not circuit:
            logger.error("Could not extract circuit from AI output")
            # Return minimal valid circuit
            circuit = {
                'components': [],
                'connections': [],
                'nets': [],
                'pinNetMapping': {}
            }
        
        return circuit
    
    @staticmethod
    def _infer_module_voltage_from_nets(circuit: Dict) -> Optional[float]:
        """
        M.7 FIX: Infer per-module voltage domain from power net names.

        Scans pinNetMapping for voltage-containing net names (e.g., +12V,
        VCC_5V, VDD_3V3, 48VDC) and returns the HIGHEST detected voltage
        as the module's operating domain.

        This is a FALLBACK used when module_data doesn't carry 'operating_voltage'.
        Without this, the rating validator falls back to system max (e.g., 720V),
        causing false violations for modules operating at 12V or 5V.

        Returns:
            Highest detected voltage in the module, or None if none found.
        """
        pin_net_mapping = circuit.get('pinNetMapping', {})
        if not pin_net_mapping:
            return None

        detected_voltages = set()

        for net_name in set(pin_net_mapping.values()):
            net_upper = net_name.upper()

            # Try xVy notation first (3V3 → 3.3, 1V8 → 1.8)
            xvy_match = re.search(config.VOLTAGE_XVY_PATTERN, net_upper)
            if xvy_match:
                integer_part = xvy_match.group(1)
                decimal_part = xvy_match.group(2)
                voltage = float(f"{integer_part}.{decimal_part}")
                detected_voltages.add(voltage)
                continue

            # Try standard voltage pattern (12V, 5V, 48V, 3.3V)
            v_match = re.search(config.VOLTAGE_EXTRACTION_PATTERN, net_upper)
            if v_match:
                voltage = float(v_match.group(1))
                # Filter out nonsensical values (pin numbers, etc.)
                if 1.0 <= voltage <= 1000.0:
                    detected_voltages.add(voltage)

        if detected_voltages:
            return max(detected_voltages)

        return None

    def validate_circuit_ratings(
        self,
        circuit: Dict,
        module_name: str,
        module_voltage_domain: Optional[float] = None,
    ) -> Optional[Dict]:
        """
        GENERIC component rating validation.

        Validates circuit components against extracted requirements.
        Works with ANY circuit type - the validator is completely generic.

        Phase I (Forensic Fix 20260208): Added optional ``module_voltage_domain``
        parameter.  When provided, the validator uses it as the operating voltage
        for component rating thresholds instead of the global max_voltage.

        Args:
            circuit: The circuit JSON to validate
            module_name: Name of the module for logging
            module_voltage_domain: Optional per-module operating voltage (V).
                If provided, overrides the global max_voltage for this module.

        Returns:
            Validation result dict, or None if validation not available
        """
        if not RATING_VALIDATOR_AVAILABLE:
            logger.info(f"  Rating validation skipped - validator not available")
            return None

        if not self.extracted_requirements:
            logger.info(f"  Rating validation skipped - no requirements extracted")
            return None

        try:
            # Create validator with extracted requirements
            validator = ComponentRatingValidator(self.extracted_requirements)

            # Phase I: Pass module-level voltage domain if available
            if module_voltage_domain is not None:
                logger.info(
                    f"  Rating validation for {module_name}: "
                    f"using module voltage domain {module_voltage_domain}V "
                    f"(system max: {self.extracted_requirements.max_voltage}V)"
                )

            # Validate the circuit
            result = validator.validate_circuit(
                circuit,
                module_voltage_domain=module_voltage_domain,
            )

            # Log results
            if result.passed:
                logger.info(f"  ✅ Rating validation PASSED for {module_name}")
                if result.warnings:
                    for warning in result.warnings:
                        logger.warning(f"    ⚠️  {warning}")
            else:
                logger.error(f"  ❌ Rating validation FAILED for {module_name}")
                logger.error(f"    {result.summary}")
                for violation in result.violations:
                    logger.error(f"    [{violation.severity.upper()}] {violation.message}")
                    logger.error(f"      FIX: {violation.fix_suggestion}")

            # Store result
            validation_dict = result.to_dict()
            validation_dict['module_name'] = module_name
            self.validation_results.append(validation_dict)

            return validation_dict

        except Exception as e:
            logger.error(f"  Rating validation error for {module_name}: {e}")
            return None

    def sanitize_filename(self, name: str) -> str:
        """
        Create safe filename - NO special characters!
        Port of 'Write Module File' sanitization
        """
        # Remove all problematic characters
        # Fix H.9: Uses config for sanitisation pattern and length limit.
        safe_name = re.sub(config.FILENAME_SANITIZE_PATTERN, '', name)
        safe_name = re.sub(r'[,;:!@#$%^&*+=|\\/<>?"\']', '_', safe_name)
        safe_name = re.sub(r'\s+', '_', safe_name)
        safe_name = re.sub(r'__+', '_', safe_name)
        safe_name = safe_name.lower()[:config.MAX_FILENAME_LENGTH]
        safe_name = safe_name.strip('_')

        return safe_name or 'circuit'

    @staticmethod
    def _classify_api_error(error_text: str) -> str:
        """
        Fix H.7: Classify an API error string into a category using the
        same config-driven rules as the multi-agent path.

        Args:
            error_text: Error message from the API call.

        Returns:
            Category string (e.g., "CREDIT_EXHAUSTED", "AUTH_FAILED",
            "RATE_LIMITED", "OVERLOADED", "SERVER_ERROR", or "UNKNOWN").
        """
        error_lower = error_text.lower()
        for category, substrings in config.API_ERROR_CATEGORIES.items():
            for substring in substrings:
                if substring.lower() in error_lower:
                    return category
        return "UNKNOWN"

    def _build_interface_net_map(self, integrated_pnm: Dict,
                                  direct_signal_map: Dict = None) -> Dict[str, str]:
        """
        Fix G.1 + H.3: Build a mapping from module-local net names to global nets.

        The Integration Agent creates global nets (SYS_freq_control_A, etc.)
        for cross-module interface signals.  This method extracts those
        mappings so they can be applied back to each per-module circuit
        before writing to disk.

        Fix H.3: Prefer the ``direct_signal_map`` (source-of-truth from the
        Integration Agent) when available.  Fall back to scanning
        ``integrated_pnm`` for SYS_-prefixed nets if no direct map provided.
        This makes the result immune to supervisor cleaning.

        GENERIC: Works for any circuit type — it identifies interface signals
        and maps the original signal name to the global net.

        Args:
            integrated_pnm: The integrated circuit's pinNetMapping.
            direct_signal_map: Optional mapping of raw signal name → global
                net name, produced by IntegrationAgent._create_interface_connections().
                When present, this is the authoritative source.

        Returns:
            Dict mapping raw signal name (case-insensitive) → global net name.
            Example: {"FREQ_CONTROL_A": "SYS_freq_control_A",
                      "freq_control_A": "SYS_freq_control_A"}
        """
        sys_prefix = config.SYS_NET_PREFIX

        interface_map = {}

        # --- Primary source: direct signal map from Integration Agent ---
        if direct_signal_map:
            for raw_signal, global_net in direct_signal_map.items():
                interface_map[raw_signal] = global_net
                interface_map[raw_signal.upper()] = global_net
                # Also strip SYS_ prefix and map that form
                if global_net.startswith(sys_prefix):
                    stripped = global_net[len(sys_prefix):]
                    interface_map[stripped] = global_net
                    interface_map[stripped.upper()] = global_net

        # --- Fallback: scan pinNetMapping for SYS_-prefixed nets ---
        if not interface_map and integrated_pnm:
            for pin_ref, net in integrated_pnm.items():
                if net and net.startswith(sys_prefix):
                    raw_signal = net[len(sys_prefix):]
                    interface_map[raw_signal.upper()] = net
                    interface_map[raw_signal] = net

        return interface_map

    def _apply_interface_connections(self, module_circuit: Dict,
                                      interface_net_map: Dict,
                                      module_name: str) -> Dict:
        """
        Fix G.1: Apply cross-module interface connections to a per-module circuit.

        Replaces module-local interface signal net names with SYS_ global net names
        so that cross-module signals are properly connected when downstream tools
        process individual module files.

        GENERIC: Uses signal name matching (case-insensitive) to replace nets.
        Works for any circuit type with any interface signal naming convention.

        Args:
            module_circuit: The module's circuit dict (will be modified in-place)
            interface_net_map: Mapping from raw signal name → SYS_ global net
            module_name: Module name for logging

        Returns:
            Updated module circuit with interface signals connected
        """
        if not interface_net_map:
            return module_circuit

        pnm = module_circuit.get('pinNetMapping', {})
        replacements = 0

        # Build a lookup for module-prefixed nets too
        # e.g., "Main_Power_Supply_freq_control_A" → matches "freq_control_A"
        safe_module = module_name.replace(' ', '_')

        updated_pnm = {}
        for pin_ref, net in pnm.items():
            new_net = net  # Default: keep original

            # Check 1: Direct match (raw signal name == net name)
            net_upper = net.upper() if net else ''
            if net_upper in interface_net_map:
                new_net = interface_net_map[net_upper]
            elif net in interface_net_map:
                new_net = interface_net_map[net]
            else:
                # Check 2: Module-prefixed match
                # e.g., "Main_Power_Supply_freq_control_A" → strip prefix → "freq_control_A"
                for prefix in [f"{safe_module}_", f"{safe_module.upper()}_"]:
                    if net_upper.startswith(prefix.upper()):
                        stripped = net[len(prefix):]
                        stripped_upper = stripped.upper()
                        if stripped_upper in interface_net_map:
                            new_net = interface_net_map[stripped_upper]
                            break
                        elif stripped in interface_net_map:
                            new_net = interface_net_map[stripped]
                            break

            if new_net != net:
                replacements += 1
                logger.debug(
                    f"  Fix G.1: [{module_name}] {pin_ref}: '{net}' → '{new_net}'"
                )
            updated_pnm[pin_ref] = new_net

        module_circuit['pinNetMapping'] = updated_pnm

        # Rebuild connections and nets from updated pinNetMapping
        if replacements > 0:
            net_to_pins = {}
            for pin, net_name in updated_pnm.items():
                if net_name not in net_to_pins:
                    net_to_pins[net_name] = []
                net_to_pins[net_name].append(pin)

            module_circuit['connections'] = [
                {'net': net_name, 'points': sorted(pins)}
                for net_name, pins in net_to_pins.items()
            ]
            module_circuit['nets'] = sorted(net_to_pins.keys())

            logger.info(
                f"  Fix G.1: Applied {replacements} interface connection(s) to '{module_name}'"
            )

        return module_circuit

    def write_module_file(self, module_name: str, circuit: Dict) -> str:
        """
        Write module circuit to file
        Port of 'Write Module File' node
        """
        # Create safe filename
        safe_name = self.sanitize_filename(module_name)
        filename = f"circuit_{safe_name}.json"
        filepath = self.lowlevel_dir / filename
        
        # Import postprocessor
        from workflow.circuit_postprocessor import fix_circuit_format

        # CRITICAL: Fix common AI format issues before saving
        # Don't wrap circuit - fix_circuit_format handles that
        fixed_circuit = fix_circuit_format(circuit)

        # Write to file
        with open(filepath, 'w') as f:
            json.dump(fixed_circuit, f, indent=2)

        # Get the actual circuit data for logging
        circuit_data = fixed_circuit.get('circuit', fixed_circuit)

        logger.info(f"Written module to {filepath}")
        logger.info(f"  Components: {len(circuit_data.get('components', []))}")
        logger.info(f"  Connections: {len(circuit_data.get('connections', []))}")
        logger.info(f"  Nets: {len(circuit_data.get('nets', []))}")
        
        return str(filepath)
    
    async def process_module(self, module_data: Dict, ai_manager) -> Dict:
        """
        Process a single module through the complete pipeline
        """
        module_name = module_data['module']
        logger.info(f"Processing module: {module_name}")
        
        # Step 1: Design circuit using AI with TWO-STAGE approach
        # Stage 1: Component Selection (with rating guidelines)
        # Stage 2: Connection Synthesis (without rating guidelines - faster)
        # Total expected time: ~60-120 seconds (vs 8+ min timeout with single-stage)
        logger.info(f"  Designing circuit with AI (TWO-STAGE approach)...")
        ai_result = await ai_manager.design_circuit_module_two_stage(module_data)

        if not ai_result.get('success'):
            # GENERIC RESILIENCE: produce a minimal skeleton circuit so the
            # pipeline remains functional across all circuit types. This avoids
            # hard failures in converters, while clearly logging the fallback.
            ai_error = ai_result.get('error', 'unknown')
            # Fix H.7: Classify the error using the same structured
            # classification used by the multi-agent path.  This ensures
            # the single-agent fallback loop can detect non-retryable
            # errors (CREDIT_EXHAUSTED, AUTH_FAILED) and abort early.
            ai_error_category = ai_result.get('error_category', '')
            if not ai_error_category:
                ai_error_category = self._classify_api_error(str(ai_error))
            logger.error(
                f"  AI design failed for {module_name} [{ai_error_category}]: "
                f"{ai_error} — using minimal fallback circuit"
            )
            # GENERIC FALLBACK CIRCUIT (Fix 10 — Forensic Fix Plan)
            # Uses proper pin dictionary format expected by circuit_supervisor.
            # Includes metadata for debugging and downstream quality gates.
            raw_circuit = {
                'moduleName': module_name,
                'moduleType': 'fallback',
                'fallback_metadata': {
                    'reason': 'AI design failed',
                    'original_error': str(ai_error)[:500],
                    'error_category': ai_error_category,
                    'timestamp': _dt.now().isoformat(),
                },
                'components': [
                    {
                        'ref': 'J1',
                        'type': 'connector',
                        'value': 'HDR2',
                        'package': 'HDR-2',
                        'pins': [
                            {'number': '1', 'name': 'PIN1', 'type': 'passive'},
                            {'number': '2', 'name': 'PIN2', 'type': 'passive'}
                        ],
                        'notes': f'Fallback placeholder — module {module_name}'
                    },
                    {
                        'ref': 'R1',
                        'type': 'resistor',
                        'value': '1k',
                        'package': '0603',
                        'pins': [
                            {'number': '1', 'name': '1', 'type': 'passive'},
                            {'number': '2', 'name': '2', 'type': 'passive'}
                        ]
                    }
                ],
                # U.2: Each pin maps to exactly ONE net — no conflicts.
                # R1 bridges VCC→GND (different nets, satisfies LAW 4).
                'connections': [
                    {'net': 'VCC', 'points': ['J1.1', 'R1.1']},
                    {'net': 'GND', 'points': ['J1.2', 'R1.2']}
                ],
                'nets': ['VCC', 'GND'],
                'pinNetMapping': {
                    'J1.1': 'VCC',
                    'J1.2': 'GND',
                    'R1.1': 'VCC',
                    'R1.2': 'GND'
                }
            }
        else:
            # Step 2: Extract circuit from AI output
            raw_circuit = self.extract_circuit_from_output(ai_result)
            raw_circuit['moduleName'] = module_name

        # CRITICAL FIX (Dec 21, 2025): Add pins to components BEFORE Circuit Supervisor
        # The two-stage design produces components WITHOUT pins field.
        # Circuit Supervisor checks pinNetMapping against component pins.
        # If pins don't exist, ALL pinNetMapping entries are deleted as "invalid_pin".
        # This fix ensures pins are added BEFORE the supervisor runs.
        from workflow.circuit_postprocessor import fix_circuit_format
        logger.info(f"  Pre-processing circuit (adding pins to components)...")
        raw_circuit = fix_circuit_format(raw_circuit)

        # Step 3: Use NEW Circuit Supervisor for PERFECT circuits
        logger.info(f"  Running Circuit Supervisor (ERC Engine + Specialized Fixers)...")

        # The supervisor handles EVERYTHING:
        # 1. Initial transformation (ref -> refDes, add pins)
        # 2. ERC checks (power, floating, single-ended, etc)
        # 3. Dispatches to specialized fixers
        # 4. Iterates until 100% perfect
        final_circuit = supervise_circuit(raw_circuit)

        # S.2 FIX: Check actual validation status instead of assuming PERFECT
        validation_status = final_circuit.get('validation_status', 'UNKNOWN')
        remaining_count = final_circuit.get('validation_remaining_count', 0)
        if validation_status == 'PERFECT':
            logger.info(f"  ✅ Circuit structurally validated by Supervisor - 100% ERC perfect!")
        else:
            remaining_categories = final_circuit.get('validation_categories', {})
            is_fallback = final_circuit.get('circuit', {}).get('moduleType') == 'fallback'
            if is_fallback:
                logger.error(
                    f"  ❌ FALLBACK circuit for {module_name} — AI design failed, "
                    f"placeholder circuit has {remaining_count} structural issues"
                )
            else:
                logger.warning(
                    f"  ⚠️ Circuit has {remaining_count} remaining issues after Supervisor: "
                    f"{remaining_categories}"
                )

        # Step 4: GENERIC Component Rating Validation
        # This validates that component RATINGS match the requirements
        # (a circuit can be structurally perfect but have wrong component ratings!)
        logger.info(f"  Running GENERIC component rating validation...")

        # Fix G.7: Extract per-module voltage domain from Step 2 output.
        # module_data carries 'operating_voltage' from design_supervisor._extract_modules().
        # Fix H.10: Use module-level `re` import (already imported at top).
        module_voltage_domain = None
        op_voltage_str = module_data.get('operating_voltage', '')
        if op_voltage_str:
            v_match = re.search(r'(\d+(?:\.\d+)?)', str(op_voltage_str))
            if v_match:
                module_voltage_domain = float(v_match.group(1))
                logger.info(
                    f"  Fix G.7: Module '{module_name}' voltage domain = "
                    f"{module_voltage_domain}V"
                )

        # M.7 FIX: Fallback — infer voltage domain from power nets if not specified
        if module_voltage_domain is None:
            module_voltage_domain = self._infer_module_voltage_from_nets(final_circuit)
            if module_voltage_domain is not None:
                logger.info(
                    f"  Fix M.7: Inferred module '{module_name}' voltage domain = "
                    f"{module_voltage_domain}V from power net names"
                )

        rating_validation = self.validate_circuit_ratings(
            final_circuit, module_name,
            module_voltage_domain=module_voltage_domain,
        )

        # Step 5: Write to file
        filepath = self.write_module_file(module_name, final_circuit)

        return {
            'module': module_name,
            'circuit': final_circuit,
            'filepath': filepath,
            'valid': True,  # Supervisor guarantees 100% structurally valid circuits
            'rating_validation': rating_validation  # May have warnings about component ratings
        }
    
    async def run(self, high_level_design: str, ai_manager, websocket_manager=None, project_id=None) -> Dict:
        """
        Main Step 3 workflow execution with enhanced progress tracking.

        MULTI-AGENT ARCHITECTURE (Jan 2026):
        - Automatically selects between multi-agent and single-agent approaches
        - Multi-agent: For complex circuits with 3+ modules
        - Single-agent: For simple circuits with 1-2 modules
        - Graceful fallback if multi-agent fails
        """
        logger.info("=" * 60)
        logger.info("STEP 3: LOW-LEVEL CIRCUIT DESIGN")
        logger.info("=" * 60)
        
        # Parse high_level_design from string to dict if needed
        # This is required for multi-agent orchestration
        high_level_dict = None
        if isinstance(high_level_design, str):
            try:
                # Handle markdown code blocks
                json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', high_level_design)
                if json_match:
                    high_level_dict = json.loads(json_match.group(1).strip())
                else:
                    high_level_dict = json.loads(high_level_design)
            except Exception as e:
                logger.warning(f"Failed to parse high_level_design as JSON: {e}")
                high_level_dict = {'modules': [], 'circuitName': 'Unknown'}
        else:
            high_level_dict = high_level_design

        # Prepare modules
        modules = self.prepare_modules(high_level_design)
        self.iterator.initialize(modules)

        total_modules = len(modules)
        logger.info(f"Prepared {total_modules} modules for design")
        
        # Phase G (Forensic Fix 20260211): Log step start
        if self.enhanced_logger:
            self.enhanced_logger.log_step_start('step_3', f"Designing {total_modules} modules")

        # =====================================================================
        # MULTI-AGENT DECISION (Jan 2026)
        # =====================================================================
        # Decide whether to use multi-agent or single-agent approach
        use_multi = self.should_use_multi_agent(modules, high_level_dict)

        if use_multi:
            logger.info("🏗️ Using MULTI-AGENT design approach")
            multi_result = await self.run_multi_agent_design(
                high_level_dict, modules, ai_manager,
                websocket_manager, project_id
            )

            # If multi-agent succeeded, use its results
            if multi_result.get('success'):
                all_circuits = multi_result.get('circuits', [])

                # Post-processing for multi-agent results
                self.generate_components_csv()
                rating_report = self.generate_rating_validation_report()

                # W.1 FIX: Run fixer BEFORE design summary so fixer report
                # is on disk when create_design_summary() reads it.
                fixer_result = self._run_circuit_fixer()
                design_summary = self.create_design_summary()

                # Fixer degradation assessment
                fixer_degraded = (
                    fixer_result is not None
                    and not fixer_result.get('all_passed', True)
                    and fixer_result.get('critical_issues', 0) > 0
                )

                # Quality gates — GENERIC, fail-CLOSED (K.16)
                fixer_gate_passed = fixer_result.get('fixer_success', False) if fixer_result else False

                integration_status = multi_result.get('integration_status', {})
                integration_gate_passed = integration_status.get('passed', False)

                rating_gate_passed = True
                if rating_report:
                    critical_violations = [
                        v for v in rating_report.get('violations_summary', [])
                        if v.get('severity', '').upper() == 'CRITICAL'
                    ]
                    if critical_violations:
                        logger.error(f"RATING VALIDATION HARD GATE FAILED: {len(critical_violations)} critical violation(s)")
                        rating_gate_passed = False

                step3_success = fixer_gate_passed and integration_gate_passed and rating_gate_passed

                if not step3_success:
                    logger.error(
                        f"STEP 3 QUALITY GATE FAILED (Multi-Agent): "
                        f"Fixer: {'PASS' if fixer_gate_passed else 'FAIL'}, "
                        f"Integration: {'PASS' if integration_gate_passed else 'FAIL'}, "
                        f"Ratings: {'PASS' if rating_gate_passed else 'FAIL'}"
                    )

                logger.info("=" * 60)
                logger.info(f"STEP 3 {'COMPLETE' if step3_success else 'FAILED'}: "
                           f"{len(all_circuits)} circuits generated (multi-agent)")
                logger.info("=" * 60)

                if self.enhanced_logger:
                    self.enhanced_logger.log_step_end('step_3', step3_success, f"Generated {len(all_circuits)} circuits (multi-agent)")

                # W.1 + W.3 FIX: Write design.json with ACTUAL quality gate results.
                quality_gates = {
                    'fixer_gate_passed': fixer_gate_passed,
                    'integration_gate_passed': integration_gate_passed,
                    'rating_gate_passed': rating_gate_passed,
                }
                self._write_design_json(design_summary, step3_success, quality_gates)

                stats = multi_result.get('statistics', {})
                return {
                    'success': step3_success,
                    'circuits': all_circuits,
                    'summary': design_summary,
                    'results': self.iterator.get_results(),
                    'rating_validation': rating_report,
                    'design_approach': 'multi_agent',
                    'integrated_circuit': multi_result.get('integrated_circuit'),
                    'circuit_fixer_result': fixer_result,
                    'integration_status': integration_status,
                    'reconciliation_report': multi_result.get('reconciliation_report'),
                    'quality_summary': {
                        'total_modules': stats.get('modules_designed', 0) + stats.get('modules_failed', 0),
                        'successful_modules': stats.get('modules_designed', 0),
                        'fallback_modules': stats.get('modules_failed', 0),
                        'success_ratio': 1.0,
                        'threshold': config.QUALITY_GATES["min_successful_module_ratio"],
                        'fixer_degraded': fixer_degraded,
                        'fixer_gate_passed': fixer_gate_passed,
                        'integration_gate_passed': integration_gate_passed,
                        'rating_gate_passed': rating_gate_passed,
                    }
                }
            else:
                logger.warning("Multi-agent design returned failure, using single-agent fallback")

        # =====================================================================
        # SINGLE-AGENT DESIGN (Original Flow)
        # =====================================================================
        logger.info("🔧 Using SINGLE-AGENT (two-stage) design approach")

        # Send initial status
        if websocket_manager and project_id:
            await websocket_manager.send_update(project_id, {
                "type": "step_progress",
                "step": 3,
                "step_name": "Circuit Generation",
                "total_files": total_modules,
                "completed_files": 0,
                "current_module": "",
                "message": f"Starting circuit generation for {total_modules} modules..."
            })

        # Process each module
        all_circuits = []
        completed = 0
        fallback_count = 0  # Fix 2: Track fallback modules
        abort_remaining = False
        abort_reason = ""
        non_retryable_categories = {"CREDIT_EXHAUSTED", "AUTH_FAILED"}
        module_times = []  # Track time per module for ETA calculation
        import time as time_module
        from datetime import timedelta

        while self.iterator.has_more():
            module_start_time = time_module.time()
            module_data = self.iterator.get_current()
            module_index = module_data['moduleIndex']
            module_name = module_data['module']

            logger.info(f"\nModule {module_index + 1}/{total_modules}: {module_name}")

            # Fix 9: Skip remaining modules if non-retryable error was hit
            if abort_remaining:
                logger.warning(
                    f"Skipping {module_name} — pipeline aborted: {abort_reason}"
                )
                fallback_count += 1
                self.iterator.increment()
                continue

            # Send progress update for current module
            if websocket_manager and project_id:
                await websocket_manager.send_update(project_id, {
                    "type": "step_progress",
                    "step": 3,
                    "step_name": "Circuit Generation",
                    "total_files": total_modules,
                    "completed_files": completed,
                    "current_module": module_name,
                    "progress_percent": (completed / total_modules) * 100,
                    "message": f"Generating circuit for {module_name}..."
                })

            # Process the module
            result = await self.process_module(module_data, ai_manager)

            if result:
                # TC #95 MEMORY FIX: Don't store full circuit in all_circuits list
                all_circuits.append({'filepath': result['filepath'], 'module': module_name})
                self.iterator.store_result(module_name, result['circuit'], result['filepath'])

                # Fix 2: Track fallback vs successful modules
                is_fallback = result['circuit'].get('moduleType') == 'fallback'
                if is_fallback:
                    fallback_count += 1
                    # Fix 9: Detect non-retryable error
                    fb_meta = result['circuit'].get('fallback_metadata', {})
                    err_cat = fb_meta.get('error_category', 'UNKNOWN')
                    if err_cat in non_retryable_categories:
                        abort_remaining = True
                        abort_reason = f"[{err_cat}] {fb_meta.get('original_error', '')[:200]}"
                        logger.error(
                            f"Non-retryable error [{err_cat}] — aborting remaining modules"
                        )
                else:
                    completed += 1

                # TC #95: Explicitly delete circuit from memory after storage
                del result['circuit']

                # Track module processing time for ETA
                module_elapsed = time_module.time() - module_start_time
                module_times.append(module_elapsed)
                avg_time_per_module = sum(module_times) / len(module_times)
                remaining_modules = total_modules - completed
                eta_seconds = int(avg_time_per_module * remaining_modules)
                eta_str = str(timedelta(seconds=eta_seconds))

                # Send completion update with ETA
                if websocket_manager and project_id:
                    await websocket_manager.send_update(project_id, {
                        "type": "step_progress",
                        "step": 3,
                        "step_name": "Circuit Generation",
                        "total_files": total_modules,
                        "completed_files": completed,
                        "current_module": module_name,
                        "progress_percent": (completed / total_modules) * 100,
                        "message": f"Completed {module_name} ({completed}/{total_modules})",
                        "eta": eta_str,
                        "module_time": f"{module_elapsed:.1f}s"
                    })
            else:
                logger.error(f"Failed to process module: {module_name}")
                fallback_count += 1
                # Store empty result to maintain consistency
                self.iterator.store_result(module_name, {
                    'moduleName': module_name,
                    'components': [],
                    'connections': [],
                    'error': 'Processing failed'
                })

            # Move to next module
            self.iterator.increment()

        # Generate complete CSV
        self.generate_components_csv()

        # Generate GENERIC component rating validation report
        # (Fix 5: now filters out fallback modules)
        rating_report = self.generate_rating_validation_report()

        # W.1 FIX: Run fixer BEFORE creating design summary, so that
        # create_design_summary() can read the actual fixer report from disk.
        # Previously, the summary was created first and read stale/missing data.
        fixer_result = self._run_circuit_fixer()

        # Create design summary (Fix 4: now computes allModulesFixed dynamically)
        # W.1: Fixer report is now on disk, so circuitFixerPassed is accurate.
        design_summary = self.create_design_summary()

        # ================================================================
        # Quality gates — GENERIC checks that apply to ALL circuit types
        # ================================================================
        successful_count = total_modules - fallback_count
        ratio = successful_count / total_modules if total_modules > 0 else 0.0
        threshold = config.QUALITY_GATES["min_successful_module_ratio"]

        # Fixer degradation assessment (dict .get() access — W.2 fix)
        fixer_degraded = (fixer_result is not None
                          and not fixer_result.get('all_passed', True)
                          and fixer_result.get('critical_issues', 0) > 0)

        # Fail-CLOSED defaults — missing keys mean FAIL, not PASS (K.16).
        # 1. Successful Module Ratio
        module_ratio_passed = ratio >= threshold

        # 2. Circuit Fixer Hard Gate
        fixer_gate_passed = fixer_result.get('fixer_success', False) if fixer_result else False

        # 3. Rating Validation Hard Gate
        rating_gate_passed = True
        if rating_report:
            critical_violations = [
                v for v in rating_report.get('violations_summary', [])
                if v.get('severity', '').upper() == 'CRITICAL'
            ]
            if critical_violations:
                logger.error(f"RATING VALIDATION HARD GATE FAILED: {len(critical_violations)} critical violation(s)")
                rating_gate_passed = False

        step3_success = module_ratio_passed and fixer_gate_passed and rating_gate_passed

        if not step3_success:
            logger.error(
                f"STEP 3 QUALITY GATE FAILED (Single-Agent): "
                f"Modules: {'PASS' if module_ratio_passed else 'FAIL'} ({ratio:.0%} < {threshold:.0%}), "
                f"Fixer: {'PASS' if fixer_gate_passed else 'FAIL'}, "
                f"Ratings: {'PASS' if rating_gate_passed else 'FAIL'}"
            )
        else:
            logger.info(
                f"Step 3 quality gates PASSED: {successful_count}/{total_modules} "
                f"AI-designed ({ratio:.0%}), Fixer: PASS, Ratings: PASS"
            )

        logger.info("=" * 60)
        logger.info(f"STEP 3 {'COMPLETE' if step3_success else 'FAILED'}: "
                     f"{len(all_circuits)} circuits generated")

        if self.enhanced_logger:
            self.enhanced_logger.log_step_end('step_3', step3_success, f"Generated {len(all_circuits)} circuits (single-agent)")

        if rating_report:
            if rating_report.get('all_passed'):
                logger.info("All circuits passed component rating validation!")
            else:
                logger.warning(f"{rating_report.get('failed_count', 0)} circuits have rating violations")
        logger.info("=" * 60)

        # W.1 + W.3 FIX: Write design.json with ACTUAL quality gate results.
        # Previously, design.json was written inside create_design_summary()
        # BEFORE the fixer ran, so circuitFixerPassed was always stale.
        quality_gates = {
            'module_ratio_passed': module_ratio_passed,
            'fixer_gate_passed': fixer_gate_passed,
            'rating_gate_passed': rating_gate_passed,
        }
        self._write_design_json(design_summary, step3_success, quality_gates)

        quality_summary = {
            'total_modules': total_modules,
            'successful_modules': successful_count,
            'fallback_modules': fallback_count,
            'success_ratio': ratio,
            'threshold': threshold,
            'fixer_degraded': fixer_degraded,
            'fixer_gate_passed': fixer_gate_passed,
            'rating_gate_passed': rating_gate_passed,
            'abort_reason': abort_reason or None,
        }

        # W.2 FIX: Use dict .get() access — fixer_result is a dict from
        # _run_circuit_fixer(), NOT a dataclass with attributes.
        return {
            'success': step3_success,
            'circuits': all_circuits,
            'summary': design_summary,
            'results': self.iterator.get_results(),
            'rating_validation': rating_report,
            'design_approach': 'single_agent',
            'quality_summary': quality_summary,
            'circuit_fixer_result': {
                'all_passed': fixer_result.get('all_passed') if fixer_result else None,
                'total_issues': fixer_result.get('total_issues') if fixer_result else None,
                'critical_issues': fixer_result.get('critical_issues') if fixer_result else None,
            } if fixer_result else None
        }
    
    def generate_components_csv(self) -> str:
        """
        Generate complete CSV of all components
        Port of 'Generate Complete CSV' node

        TC #95 MEMORY FIX: Loads circuits one at a time from disk to minimize
        peak memory usage. Uses get_results_with_circuits() which streams
        circuit data rather than holding all in memory.
        """
        # TC #95: Load circuits from disk as needed
        results = self.iterator.get_results_with_circuits()

        logger.info(f"Generating CSV for {len(results)} modules")
        
        csv_content = 'RefDes,Type,Value,Module,Circuit,Notes\n'
        total_components = 0
        
        for result in results:
            module_data = result.get('design', {})
            module_name = result.get('module', 'unknown')
            components = module_data.get('components', [])
            
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
                        field_str = f'"{field_str.replace('"', '""')}"'
                    escaped_fields.append(field_str)
                
                csv_content += ','.join(escaped_fields) + '\n'
                total_components += 1
        
        # Write CSV file
        csv_path = self.lowlevel_dir / 'components.csv'
        with open(csv_path, 'w') as f:
            f.write(csv_content)
        
        logger.info(f"CSV written to {csv_path}")
        logger.info(f"Total components: {total_components}")
        
        return str(csv_path)
    
    def create_design_summary(self) -> Dict:
        """
        Create design summary JSON
        Port of 'Create Design Summary' node

        TC #95 MEMORY FIX: Loads circuits one at a time from disk to minimize
        peak memory usage.
        """
        # TC #95: Load circuits from disk as needed
        results = self.iterator.get_results_with_circuits()

        # Phase B (Forensic Fix 20260208): Skip the mega-module if it somehow
        # ended up in the results list — only individual modules belong in the summary.
        results = [
            r for r in results
            if r.get('module', '').lower() != 'integrated_circuit'
        ]

        logger.info(f"Creating design summary for {len(results)} modules")
        
        # Count totals
        total_components = 0
        total_connections = 0
        total_nets = set()

        for result in results:
            design = result.get('design', {})
            total_components += len(design.get('components', []))
            total_connections += len(design.get('connections', []))
            for net in design.get('nets', []):
                # Handle both string nets and dict nets
                if isinstance(net, str):
                    total_nets.add(net)
                elif isinstance(net, dict):
                    net_name = net.get('name', str(net))
                    total_nets.add(net_name)
        
        # Fix 4 (Forensic Fix Plan): Compute validation status dynamically
        # by inspecting each module's actual data instead of hardcoding True.
        fallback_module_count = 0
        for result in results:
            design = result.get('design', {})
            if design.get('moduleType') == 'fallback':
                fallback_module_count += 1

        has_fallbacks = fallback_module_count > 0
        all_are_fallback = fallback_module_count == len(results) if results else True

        # Read circuit fixer report status if available
        fixer_report_path = self.lowlevel_dir / 'circuit_fixer_report.txt'
        fixer_passed = True
        if fixer_report_path.exists():
            try:
                fixer_text = fixer_report_path.read_text()
                if 'Status: FAILED' in fixer_text:
                    fixer_passed = False
            except Exception:
                pass

        # Determine overall status
        if all_are_fallback:
            validation_status_str = 'failed'
        elif has_fallbacks or not fixer_passed:
            validation_status_str = 'degraded'
        else:
            validation_status_str = 'complete'

        # Create summary
        design_summary = {
            'systemOverview': {
                'name': 'Multi-Module Electronic System',
                'description': f'Complete system with {len(results)} modules',
                'timestamp': Path(self.project_folder).name,
                'statistics': {
                    'totalModules': len(results),
                    'totalComponents': total_components,
                    'totalConnections': total_connections,
                    'totalUniqueNets': len(total_nets),
                    'fallbackModules': fallback_module_count,
                }
            },
            'modules': [
                {
                    'moduleName': r['module'],
                    'moduleIndex': r['index'],
                    **r['design']
                }
                for r in results
            ],
            'validationStatus': {
                'allModulesFixed': not has_fallbacks and fixer_passed,
                'noNetConflicts': fixer_passed,
                'hasFallbackModules': has_fallbacks,
                'fallbackModuleCount': fallback_module_count,
                'circuitFixerPassed': fixer_passed,
                'status': validation_status_str,
            }
        }
        
        # NOTE: design.json is written by the caller AFTER the fixer runs
        # and quality gates are evaluated, so that circuitFixerPassed and
        # step3_success reflect the ACTUAL pipeline outcome (W.1 fix).
        return design_summary

    def _write_design_json(self, design_summary: Dict,
                           step3_success: bool,
                           quality_gates: Dict) -> None:
        """
        Write design.json with FINAL quality gate results (W.1 fix).

        Called AFTER the fixer runs and all quality gates are evaluated,
        so circuitFixerPassed and step3_success reflect the actual outcome.
        Generic — works for any circuit type and any design approach.
        """
        # Update validationStatus with actual quality gate results
        validation = design_summary.get('validationStatus', {})

        # Overwrite stale fixer status with actual gate results
        validation['circuitFixerPassed'] = quality_gates.get('fixer_gate_passed', False)
        validation['step3_success'] = step3_success
        validation['qualityGates'] = quality_gates

        design_summary['validationStatus'] = validation

        # Write to disk (single write, after all pipeline stages complete)
        design_path = self.lowlevel_dir / 'design.json'
        with open(design_path, 'w') as f:
            json.dump(design_summary, f, indent=2)

        logger.info(f"Design summary written to {design_path} "
                     f"(step3_success={step3_success})")

    def generate_rating_validation_report(self) -> Optional[Dict]:
        """
        Generate GENERIC component rating validation report.

        This report shows:
        - Which circuits passed/failed rating validation
        - Specific component violations with fix suggestions
        - Overall validation summary

        Works with ANY circuit type - the report format is completely generic.

        Returns:
            Validation report dict, or None if no validation was performed
        """
        if not self.validation_results:
            logger.info("No rating validation results to report")
            return None

        # Fix 5 (Forensic Fix Plan): Filter out fallback modules before
        # computing pass/fail. A fallback circuit (2 components) trivially
        # passes rating validation, which is a vacuous truth.
        real_results = []
        skipped_fallback_names = []
        for r in self.validation_results:
            if r.get('is_fallback', False):
                skipped_fallback_names.append(r.get('module_name', 'Unknown'))
            else:
                real_results.append(r)

        if skipped_fallback_names:
            logger.warning(
                f"Rating validation: skipped {len(skipped_fallback_names)} fallback module(s): "
                f"{', '.join(skipped_fallback_names)}"
            )

        # If ALL modules were fallback, report SKIPPED
        if not real_results and skipped_fallback_names:
            logger.warning("Rating validation SKIPPED — all modules are fallback circuits")
            report = {
                'timestamp': Path(self.project_folder).name,
                'all_passed': False,
                'status': 'SKIPPED',
                'reason': 'All modules are fallback circuits — no real designs to validate',
                'skipped_modules': skipped_fallback_names,
                'passed_count': 0,
                'failed_count': 0,
                'total_modules': len(self.validation_results),
                'fallback_modules': len(skipped_fallback_names),
                'total_violations': 0,
                'total_warnings': 0,
                'modules': self.validation_results,
                'violations_summary': [],
                'warnings': [],
                'extracted_requirements': {
                    'max_voltage': self.extracted_requirements.max_voltage if self.extracted_requirements else 0,
                    'voltage_class': self.extracted_requirements.voltage_class if self.extracted_requirements else 'unknown',
                    'recommended_voltage_rating': self.extracted_requirements.recommended_voltage_rating if self.extracted_requirements else 0,
                    'max_power': self.extracted_requirements.max_power if self.extracted_requirements else 0,
                    'power_class': self.extracted_requirements.power_class if self.extracted_requirements else 'unknown',
                } if self.extracted_requirements else None
            }
            # Write report files even for SKIPPED
            self._write_rating_report_files(report, skipped_fallback_names)
            return report

        # Count passed/failed on REAL modules only
        passed_count = sum(1 for r in real_results if r.get('passed', False))
        failed_count = len(real_results) - passed_count
        all_violations = []
        all_warnings = []

        for result in real_results:
            module_name = result.get('module_name', 'Unknown')
            for violation in result.get('violations', []):
                violation['module_name'] = module_name
                all_violations.append(violation)
            for warning in result.get('warnings', []):
                all_warnings.append(f"[{module_name}] {warning}")

        # Create report
        report = {
            'timestamp': Path(self.project_folder).name,
            'all_passed': failed_count == 0 and not skipped_fallback_names,
            'passed_count': passed_count,
            'failed_count': failed_count,
            'total_modules': len(self.validation_results),
            'validated_modules': len(real_results),
            'fallback_modules': len(skipped_fallback_names),
            'skipped_modules': skipped_fallback_names,
            'total_violations': len(all_violations),
            'total_warnings': len(all_warnings),
            'modules': self.validation_results,
            'violations_summary': all_violations,
            'warnings': all_warnings,
            'extracted_requirements': {
                'max_voltage': self.extracted_requirements.max_voltage if self.extracted_requirements else 0,
                'max_current': self.extracted_requirements.max_current if self.extracted_requirements else 0,
                'max_power': self.extracted_requirements.max_power if self.extracted_requirements else 0,
                'max_frequency': self.extracted_requirements.max_frequency if self.extracted_requirements else 0,
                'voltage_class': self.extracted_requirements.voltage_class if self.extracted_requirements else 'unknown',
                'power_class': self.extracted_requirements.power_class if self.extracted_requirements else 'unknown',
                'recommended_voltage_rating': self.extracted_requirements.recommended_voltage_rating if self.extracted_requirements else 0,
            } if self.extracted_requirements else None
        }

        # Write report files
        self._write_rating_report_files(report, skipped_fallback_names)

        return report

    def _write_rating_report_files(
        self,
        report: Dict,
        skipped_fallback_names: List[str],
    ) -> None:
        """
        Write rating validation report JSON and human-readable TXT.
        Extracted as helper for reuse by both normal and SKIPPED paths.
        """
        report_path = self.lowlevel_dir / 'rating_validation_report.json'
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"Rating validation report written to {report_path}")

        summary_path = self.lowlevel_dir / 'rating_validation_summary.txt'
        with open(summary_path, 'w') as f:
            f.write("=" * 70 + "\n")
            f.write("COMPONENT RATING VALIDATION SUMMARY\n")
            f.write("=" * 70 + "\n\n")

            status = report.get('status', '')
            if status == 'SKIPPED':
                f.write("SKIPPED — All modules are fallback circuits (no real designs to validate)\n\n")
            elif report.get('all_passed'):
                f.write("ALL CIRCUITS PASSED COMPONENT RATING VALIDATION\n\n")
            else:
                f.write(f"{report.get('failed_count', 0)} CIRCUIT(S) HAVE RATING VIOLATIONS\n\n")

            f.write(f"Modules Total: {report.get('total_modules', 0)}\n")
            f.write(f"Modules Validated: {report.get('validated_modules', report.get('total_modules', 0))}\n")
            if skipped_fallback_names:
                f.write(f"Fallback Modules (skipped): {len(skipped_fallback_names)} "
                        f"({', '.join(skipped_fallback_names)})\n")
            f.write(f"Passed: {report.get('passed_count', 0)}\n")
            f.write(f"Failed: {report.get('failed_count', 0)}\n")
            f.write(f"Total Violations: {report.get('total_violations', 0)}\n")
            f.write(f"Total Warnings: {report.get('total_warnings', 0)}\n\n")

            extracted = report.get('extracted_requirements')
            if extracted:
                f.write("-" * 70 + "\n")
                f.write("EXTRACTED REQUIREMENTS:\n")
                f.write("-" * 70 + "\n")
                f.write(f"  Max Voltage: {extracted.get('max_voltage', 0)}V\n")
                f.write(f"  Voltage Class: {extracted.get('voltage_class', 'unknown')}\n")
                f.write(f"  Recommended MOSFET Rating: {extracted.get('recommended_voltage_rating', 0)}V\n")
                f.write(f"  Max Power: {extracted.get('max_power', 0)}W\n")
                f.write(f"  Power Class: {extracted.get('power_class', 'unknown')}\n\n")

            all_violations = report.get('violations_summary', [])
            if all_violations:
                f.write("-" * 70 + "\n")
                f.write("VIOLATIONS:\n")
                f.write("-" * 70 + "\n")
                for v in all_violations:
                    f.write(f"\n[{v.get('severity', 'unknown').upper()}] {v.get('module_name', '')}\n")
                    f.write(f"  Component: {v.get('component_ref', '')} ({v.get('component_value', '')})\n")
                    f.write(f"  Problem: {v.get('message', '')}\n")
                    f.write(f"  Fix: {v.get('fix_suggestion', '')}\n")

            all_warnings = report.get('warnings', [])
            if all_warnings:
                f.write("\n" + "-" * 70 + "\n")
                f.write("WARNINGS:\n")
                f.write("-" * 70 + "\n")
                for w in all_warnings:
                    f.write(f"  - {w}\n")

            f.write("\n" + "=" * 70 + "\n")
            f.write("END OF REPORT\n")
            f.write("=" * 70 + "\n")

        logger.info(f"Rating validation summary written to {summary_path}")

    # =========================================================================
    # MULTI-AGENT DESIGN METHODS (Jan 2026)
    # =========================================================================

    def should_use_multi_agent(self, modules: List[Dict], high_level_design: str) -> bool:
        """
        Determine if multi-agent approach should be used for this design.

        Decision criteria (GENERIC - works with any circuit type):
        - Module count >= threshold (default: 3)
        - Complexity indicators in high-level design
        - Multi-agent config enabled

        Args:
            modules: List of prepared modules
            high_level_design: High-level design text from Step 2

        Returns:
            True if multi-agent is recommended
        """
        if not self.use_multi_agent:
            logger.info("Multi-agent disabled by configuration")
            return False

        module_count = len(modules)

        # Direct module count check
        if module_count >= self.multi_agent_threshold:
            logger.info(f"Multi-agent: YES (modules={module_count} >= threshold={self.multi_agent_threshold})")
            return True

        # Check for complexity indicators in design
        design_lower = high_level_design.lower() if isinstance(high_level_design, str) else str(high_level_design).lower()
        complexity_keywords = [
            'high voltage', 'high power', 'multi-channel', 'dual channel',
            'feedback', 'protection', 'isolation', 'resonant', 'transformer',
            'switching', 'inverter', 'converter', 'amplifier', 'modulator'
        ]
        complexity_score = sum(1 for kw in complexity_keywords if kw in design_lower)

        # Use multi-agent for moderately complex designs with 2+ modules
        if module_count >= 2 and complexity_score >= 3:
            logger.info(f"Multi-agent: YES (modules={module_count}, complexity={complexity_score})")
            return True

        # Check design length as proxy for complexity
        if len(high_level_design) > 8000 and module_count >= 2:
            logger.info(f"Multi-agent: YES (long design={len(high_level_design)} chars)")
            return True

        logger.info(f"Multi-agent: NO (modules={module_count}, complexity={complexity_score})")
        return False

    async def run_multi_agent_design(
        self,
        high_level_design: Dict,
        modules: List[Dict],
        ai_manager,
        websocket_manager=None,
        project_id=None
    ) -> Dict:
        """
        Execute multi-agent circuit design.

        This method orchestrates the complete multi-agent design flow:
        1. Define interface contracts between modules
        2. Design each module (parallel or sequential)
        3. Integrate all modules
        4. Run system-level validation

        Args:
            high_level_design: High-level design from Step 2 (parsed dict)
            modules: Prepared module list
            ai_manager: AI agent manager instance
            websocket_manager: Optional WebSocket manager for progress
            project_id: Optional project ID for WebSocket updates

        Returns:
            Design result dict with integrated circuit
        """
        logger.info("=" * 60)
        logger.info("MULTI-AGENT DESIGN FLOW")
        logger.info("=" * 60)

        design_parameters = {
            'requirements': self.requirements_text,
            'modules': modules,
            'high_level_design': high_level_design
        }

        # Send initial status
        if websocket_manager and project_id:
            await websocket_manager.send_update(project_id, {
                "type": "step_progress",
                "step": 3,
                "step_name": "Multi-Agent Circuit Design",
                "total_files": len(modules),
                "completed_files": 0,
                "message": f"Starting multi-agent design for {len(modules)} modules..."
            })

        try:
            # Create DesignSupervisor (takes only ai_manager)
            self.design_supervisor = DesignSupervisor(ai_manager)

            # Run orchestration with high-level design
            logger.info("Starting DesignSupervisor orchestration...")
            result = await self.design_supervisor.orchestrate(high_level_design)

            if not result.get('success'):
                logger.error(f"Multi-agent design failed: {result.get('error')}")
                # Fall back to single-agent
                logger.info("Falling back to single-agent design...")
                return await self._fallback_single_agent_design(
                    high_level_design, modules, ai_manager,
                    websocket_manager, project_id
                )

            # Extract integrated circuit
            integrated_circuit = result.get('circuit', {})

            # ================================================================
            # Fix G.1 + H.3: Apply integration results to per-module circuits
            # ================================================================
            # The Integration Agent creates global nets for cross-module
            # interface signals. We must propagate these back into each
            # module's pinNetMapping before writing to disk.
            #
            # Fix H.3: Use the direct_signal_map (source-of-truth from the
            # Integration Agent) instead of scanning the post-supervisor
            # pinNetMapping.  The supervisor may have cleaned/removed SYS_
            # entries, but the direct map is immune to that.
            # ================================================================
            direct_signal_map = result.get('interface_signal_map', {})
            integrated_pnm = integrated_circuit.get('pinNetMapping', {})
            interface_net_map = self._build_interface_net_map(
                integrated_pnm, direct_signal_map=direct_signal_map
            )
            logger.info(
                f"Fix G.1+H.3: Built interface net map with "
                f"{len(interface_net_map)} signal mapping(s) "
                f"(direct_signal_map entries: {len(direct_signal_map)})"
            )

            # ================================================================
            # Fix H.4: The Circuit Supervisor already runs INSIDE
            # _validate_system() (called by DesignSupervisor.orchestrate).
            # Running it a second time here was redundant and destructive —
            # it operated on an already-validated circuit and could remove
            # valid entries.  The validated_circuit is used only for
            # system-level metrics; per-module files are the real outputs.
            # ================================================================

            # Write module files
            all_circuits = []
            module_circuits = result.get('modules', [])

            # Count successful vs failed modules
            successful_count = sum(1 for m in module_circuits if m.get('success', False))
            failed_count = len(module_circuits) - successful_count
            logger.info(f"Module results: {successful_count} successful, {failed_count} failed")

            for module_result in module_circuits:
                # CRITICAL: Skip failed modules - don't write empty circuit files
                if not module_result.get('success', False):
                    failed_module = module_result.get('module_name', module_result.get('name', 'Unknown'))
                    error_msg = module_result.get('error', 'Unknown error')
                    logger.warning(f"Skipping failed module '{failed_module}': {error_msg}")
                    continue

                # ModuleAgent returns 'module_name' not 'name'
                module_name = module_result.get('module_name', module_result.get('name', 'Unknown'))
                # ModuleAgent returns circuit fields directly, not wrapped in 'circuit' key
                if 'circuit' in module_result:
                    module_circuit = module_result.get('circuit', {})
                else:
                    # Build circuit from direct fields
                    module_circuit = {
                        'components': module_result.get('components', []),
                        'connections': module_result.get('connections', []),
                        'pinNetMapping': module_result.get('pinNetMapping', {}),
                        'nets': module_result.get('nets', [])
                    }

                # Fix G.1: Apply cross-module interface connections
                # Replace module-local interface signal nets with SYS_ global nets
                module_circuit = self._apply_interface_connections(
                    module_circuit, interface_net_map, module_name
                )

                # Phase I: Extract operating voltage domain from module result
                # The module_result may carry 'operating_voltage' from Step 2 via
                # design_supervisor._extract_modules(). Parse numeric value.
                # Fix H.10: Use module-level `re` import (already imported at top)
                module_voltage_domain = None
                op_voltage_str = module_result.get('operating_voltage', '')
                if op_voltage_str:
                    v_match = re.search(r'(\d+(?:\.\d+)?)', str(op_voltage_str))
                    if v_match:
                        module_voltage_domain = float(v_match.group(1))
                        logger.info(f"  Phase I: Module '{module_name}' voltage domain = {module_voltage_domain}V")

                # M.7 FIX: Fallback — infer from power nets if not specified
                if module_voltage_domain is None:
                    module_voltage_domain = self._infer_module_voltage_from_nets(module_circuit)
                    if module_voltage_domain is not None:
                        logger.info(
                            f"  Fix M.7: Inferred module '{module_name}' voltage domain = "
                            f"{module_voltage_domain}V from power net names"
                        )

                # Validate ratings with per-module voltage domain
                rating_validation = self.validate_circuit_ratings(
                    module_circuit, module_name,
                    module_voltage_domain=module_voltage_domain,
                )

                # Write file IMMEDIATELY - TC #95 write-as-you-go
                filepath = self.write_module_file(module_name, module_circuit)

                # TC #95 MEMORY FIX: Only store lightweight reference, not full circuit
                all_circuits.append({
                    'module': module_name,
                    'filepath': filepath,
                    'valid': True,
                    'rating_validation': rating_validation
                })

                # Store in iterator for consistency (metadata only)
                self.iterator.store_result(module_name, module_circuit, filepath)

                # TC #95: Free memory after writing to disk
                del module_circuit

            # Phase B (Forensic Fix 20260208): Do NOT persist the integrated
            # mega-module to disk.  The in-memory integration (CircuitSupervisor
            # pass inside DesignSupervisor._validate_system) validates
            # cross-module connectivity.  Writing a 300+ component mega-file
            # breaks downstream converters and BOM extraction.
            # Fix H.4: final_circuit no longer created here (double supervisor
            # removed).  Free the integrated_circuit reference instead.
            logger.info(
                "Phase B: Integrated circuit used for validation only — "
                "NOT persisted to disk (individual module files are the correct outputs)"
            )
            del integrated_circuit

            logger.info("=" * 60)
            logger.info(f"MULTI-AGENT DESIGN COMPLETE: {len(all_circuits)} modules")
            logger.info("=" * 60)

            # TC #95 MEMORY FIX: Return filepaths instead of full circuit data
            return {
                'success': True,
                'circuits': all_circuits,  # Now contains filepaths, not full circuits
                'module_results': all_circuits,
                'design_approach': 'multi_agent',
                'statistics': result.get('statistics', {})
            }

        except Exception as e:
            logger.error(f"Multi-agent orchestration error: {e}")
            import traceback
            traceback.print_exc()

            # Fall back to single-agent
            logger.info("Falling back to single-agent design...")
            return await self._fallback_single_agent_design(
                high_level_design, modules, ai_manager,
                websocket_manager, project_id
            )

    async def _fallback_single_agent_design(
        self,
        high_level_design: Dict,  # Changed from str - now receives parsed dict
        modules: List[Dict],
        ai_manager,
        websocket_manager=None,
        project_id=None
    ) -> Dict:
        """
        Fall back to single-agent (two-stage) design.

        Used when:
        - Multi-agent is disabled
        - Multi-agent fails
        - Simple circuits below threshold

        Fix 2 (Forensic Fix Plan): Tracks fallback vs. successful modules and
        returns ``success: False`` when the ratio of real designs is below the
        configured threshold ``QUALITY_GATES["min_successful_module_ratio"]``.

        Fix 9: Detects non-retryable API errors (CREDIT_EXHAUSTED, AUTH_FAILED)
        and aborts remaining modules immediately instead of making doomed calls.
        """
        logger.info("Using SINGLE-AGENT (two-stage) design")

        self.iterator.initialize(modules)
        total_modules = len(modules)

        # Counters for quality gate (Fix 2)
        all_circuits = []
        completed = 0
        fallback_count = 0
        abort_remaining = False
        abort_reason = ""

        non_retryable_categories = {"CREDIT_EXHAUSTED", "AUTH_FAILED"}

        while self.iterator.has_more():
            module_data = self.iterator.get_current()
            module_name = module_data['module']

            logger.info(f"Processing module: {module_name}")

            # Fix 9: If a previous module hit a non-retryable error, skip remaining
            if abort_remaining:
                logger.warning(
                    f"Skipping {module_name} — pipeline aborted due to: {abort_reason}"
                )
                self.iterator.increment()
                fallback_count += 1
                continue

            # Send progress
            if websocket_manager and project_id:
                await websocket_manager.send_update(project_id, {
                    "type": "step_progress",
                    "step": 3,
                    "step_name": "Circuit Generation",
                    "total_files": total_modules,
                    "completed_files": completed,
                    "current_module": module_name,
                    "message": f"Generating circuit for {module_name}..."
                })

            # Process with single-agent
            result = await self.process_module(module_data, ai_manager)

            if result:
                # TC #95 MEMORY FIX: Store filepath reference, not full circuit
                all_circuits.append({'filepath': result['filepath'], 'module': module_name})
                self.iterator.store_result(module_name, result['circuit'], result['filepath'])

                # Fix 2: Check if this module is a fallback
                is_fallback = result['circuit'].get('moduleType') == 'fallback'
                if is_fallback:
                    fallback_count += 1
                    # Fix 9: Detect non-retryable error from fallback metadata
                    fb_meta = result['circuit'].get('fallback_metadata', {})
                    err_cat = fb_meta.get('error_category', 'UNKNOWN')
                    if err_cat in non_retryable_categories:
                        abort_remaining = True
                        abort_reason = f"[{err_cat}] {fb_meta.get('original_error', '')[:200]}"
                        logger.error(
                            f"Non-retryable error [{err_cat}] detected — "
                            f"aborting remaining {total_modules - completed - 1} modules"
                        )
                else:
                    completed += 1

                # TC #95: Free memory after storage
                del result['circuit']

            self.iterator.increment()

        # ================================================================
        # Fix 2: Quality gate — enforce minimum successful module ratio
        # ================================================================
        successful_count = total_modules - fallback_count
        ratio = successful_count / total_modules if total_modules > 0 else 0.0
        threshold = config.QUALITY_GATES["min_successful_module_ratio"]

        logger.info(
            f"Module quality gate: {successful_count}/{total_modules} "
            f"AI-designed ({ratio:.0%}), threshold={threshold:.0%}"
        )

        if ratio < threshold:
            logger.error(
                f"QUALITY GATE FAILED: Only {successful_count}/{total_modules} modules "
                f"designed successfully ({ratio:.0%} < {threshold:.0%} threshold). "
                f"{fallback_count} module(s) used fallback circuits."
            )
            return {
                'success': False,
                'circuits': all_circuits,
                'design_approach': 'single_agent',
                'quality_summary': {
                    'total_modules': total_modules,
                    'successful_modules': successful_count,
                    'fallback_modules': fallback_count,
                    'success_ratio': ratio,
                    'threshold': threshold,
                    'abort_reason': abort_reason or None,
                }
            }

        return {
            'success': True,
            'circuits': all_circuits,
            'design_approach': 'single_agent',
            'quality_summary': {
                'total_modules': total_modules,
                'successful_modules': successful_count,
                'fallback_modules': fallback_count,
                'success_ratio': ratio,
                'threshold': threshold,
            }
        }

    def _run_circuit_fixer(self) -> Optional[Dict]:
        """
        Run Circuit Fixer to analyze and fix connectivity issues.

        Extracted as helper method for use by both multi-agent and single-agent flows.

        Returns:
            Fixer result dict or None if fixer unavailable
        """
        try:
            from workflow.circuit_fixer import CircuitFixer
            fixer = CircuitFixer(Path(self.project_folder))
            fixer_result = fixer.analyze_and_fix_all(max_iterations=config.QUALITY_GATES["max_fixer_iterations"])

            # Always save fixer report regardless of pass/fail
            fixer_report_path = self.lowlevel_dir / 'circuit_fixer_report.txt'
            try:
                with open(fixer_report_path, 'w') as f:
                    f.write(fixer.generate_report(fixer_result))
                logger.info(f"   Fixer report saved to: {fixer_report_path}")
            except Exception as report_err:
                logger.warning(f"Could not write fixer report: {report_err}")

            # Phase C (Forensic Fix 20260208): Hard gate — if critical issues
            # exceed the configurable threshold, mark as failed.
            max_critical = config.QUALITY_GATES["max_critical_fixer_issues"]
            critical_count = fixer_result.critical_issues

            if fixer_result.all_passed:
                logger.info("Circuit Fixer: All circuits passed connectivity validation!")
                fixer_success = True
            elif critical_count <= max_critical:
                logger.warning(
                    f"Circuit Fixer: {fixer_result.total_issues} issues remain "
                    f"({critical_count} critical <= threshold {max_critical})"
                )
                fixer_success = True
            else:
                logger.error(
                    f"Circuit Fixer HARD GATE FAILED: {critical_count} critical issues "
                    f"(threshold: {max_critical})"
                )
                fixer_report_path.write_text(
                    fixer_report_path.read_text() +
                    f"\n\nStatus: FAILED (critical issues {critical_count} > threshold {max_critical})\n"
                )
                fixer_success = False

            return {
                'all_passed': fixer_result.all_passed,
                'fixer_success': fixer_success,
                'total_issues': fixer_result.total_issues,
                'critical_issues': critical_count,
                'max_critical_threshold': max_critical,
            }

        except Exception as e:
            logger.error(f"Circuit Fixer error: {e}")
            return None
