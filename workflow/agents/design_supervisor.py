# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Design Supervisor - Master orchestrator for multi-agent circuit design.

The Design Supervisor is the top-level coordinator that:
1. Parses high-level design from Step 2
2. Defines interfaces between modules
3. Spawns and coordinates Module Agents (in parallel when possible)
4. Validates inter-module integration
5. Aggregates final circuit output

This is the ONLY agent that sees the complete system picture.
All other agents operate with limited, focused context.

Author: CopperPilot Team
Date: January 2026
Version: 1.0

Key Design Principles:
- GENERIC: Works for ANY circuit type (LED blinker to complex amplifiers)
- MODULAR: Each module is designed independently
- INTERFACE-DRIVEN: Modules communicate via defined contracts
- ERROR-RESILIENT: Isolated failures don't cascade
"""

import json
import asyncio
import copy
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime

from utils.logger import setup_logger
from server.config import config

# Import sub-agents
from .module_agent import ModuleAgent
from .integration_agent import IntegrationAgent

logger = setup_logger(__name__)


class DesignSupervisor:
    """
    Master orchestrator for multi-agent circuit design.

    The Design Supervisor coordinates the entire circuit design process:
    1. Analyzes high-level design to extract modules
    2. Defines interfaces between modules
    3. Spawns Module Agents for each module (can run in parallel)
    4. Coordinates Integration Agent for cross-module connections
    5. Validates and returns the complete circuit

    Attributes:
        ai_manager: Reference to the AI Agent Manager for API calls
        module_agent: Reusable Module Agent instance
        integration_agent: Integration Agent instance
        interfaces: Defined interfaces between modules
        module_results: Results from each Module Agent
    """

    def __init__(self, ai_manager):
        """
        Initialize the Design Supervisor.

        Args:
            ai_manager: The AI Agent Manager instance for making API calls
        """
        self.ai_manager = ai_manager
        self.module_agent = ModuleAgent(ai_manager)
        self.integration_agent = IntegrationAgent(ai_manager)
        self.interfaces = {}
        self.module_results = []
        self.design_metrics = {
            'start_time': None,
            'end_time': None,
            'modules_designed': 0,
            'modules_failed': 0,
            'total_components': 0,
            'total_connections': 0,
            'api_calls': 0,
            'total_cost': 0.0
        }

    async def orchestrate(self, high_level_design: Dict) -> Dict:
        """
        Main entry point for multi-agent circuit design.

        This method coordinates the entire design process:
        1. Extract modules from high-level design
        2. Define interfaces between modules
        3. Design each module (can be parallel)
        4. Integrate all modules
        5. Return complete circuit

        Args:
            high_level_design: The high-level design from Step 2, containing:
                - modules: List of module specifications
                - circuitName: Name of the overall circuit
                - requirements: System-level requirements

        Returns:
            Complete circuit dict with all components, connections, and metadata
        """
        self.design_metrics['start_time'] = datetime.now()
        logger.info("=" * 80)
        logger.info("DESIGN SUPERVISOR - STARTING MULTI-AGENT ORCHESTRATION")
        logger.info("=" * 80)

        # DEBUG: Log input design structure
        logger.debug(f"[SUPERVISOR] Input design keys: {list(high_level_design.keys())}")
        logger.debug(f"[SUPERVISOR] Circuit name: {high_level_design.get('circuitName', 'Unknown')}")
        if 'modules' in high_level_design:
            logger.debug(f"[SUPERVISOR] Modules in design: {len(high_level_design.get('modules', []))}")

        try:
            # =========================================================================
            # PHASE 1: Extract and validate modules
            # =========================================================================
            logger.info("\n📋 PHASE 1: Extracting modules from high-level design...")
            modules = self._extract_modules(high_level_design)

            if not modules:
                logger.error("No modules found in high-level design!")
                return self._create_fallback_circuit(high_level_design)

            logger.info(f"   Found {len(modules)} modules to design:")
            for i, module in enumerate(modules, 1):
                logger.info(f"   {i}. {module.get('name', 'Unknown')}")

            # =========================================================================
            # PHASE 2: Define interfaces between modules
            # =========================================================================
            logger.info("\n🔌 PHASE 2: Defining module interfaces...")
            self.interfaces = await self._define_interfaces(modules, high_level_design)

            logger.info(f"   Defined interfaces for {len(self.interfaces)} modules")
            for mod_name, iface in self.interfaces.items():
                logger.debug(f"[SUPERVISOR] Interface for {mod_name}:")
                logger.debug(f"   Power in: {iface.get('power_in', [])}")
                logger.debug(f"   Power out: {iface.get('power_out', [])}")
                logger.debug(f"   Signals in: {iface.get('signals_in', [])}")
                logger.debug(f"   Signals out: {iface.get('signals_out', [])}")

            # =========================================================================
            # PHASE 3: Design each module (parallel when possible)
            # =========================================================================
            logger.info("\n🔧 PHASE 3: Designing modules...")
            self.module_results = await self._design_all_modules(modules)

            # Count successful modules
            successful = sum(1 for r in self.module_results if r.get('success', False))
            total = len(modules)
            self.design_metrics['modules_designed'] = successful
            self.design_metrics['modules_failed'] = total - successful

            logger.info(f"   Designed {successful}/{total} modules successfully")

            # Fix 6 (Forensic Fix Plan): Configurable success threshold
            # instead of only checking for 0% success.
            success_ratio = successful / total if total > 0 else 0.0
            threshold = config.QUALITY_GATES["min_multi_agent_success_ratio"]

            if success_ratio < threshold:
                logger.error(
                    f"Multi-agent quality gate FAILED: {successful}/{total} "
                    f"modules succeeded ({success_ratio:.0%} < {threshold:.0%} threshold). "
                    f"Returning failure."
                )
                return self._create_fallback_circuit(high_level_design)

            # =========================================================================
            # PHASE 3.5: Interface contract reconciliation
            # =========================================================================
            logger.info("\n📊 PHASE 3.5: Reconciling interface contracts...")
            reconciliation_report = await self._reconcile_interface_contract(
                self.module_results, self.interfaces
            )
            
            # Phase C+ (Feb 2026): Auto-resolve interface gaps
            if reconciliation_report:
                logger.info("🔧 PHASE 3.6: Attempting auto-resolution of interface gaps...")
                self.module_results = self._auto_resolve_interface_gaps(
                    self.module_results, reconciliation_report
                )

            # =========================================================================
            # PHASE 4: Integrate modules
            # =========================================================================
            logger.info("\n🔗 PHASE 4: Integrating modules...")
            integrated_circuit = await self._integrate_modules()

            # =========================================================================
            # PHASE 5: Final validation
            # =========================================================================
            logger.info("\n✅ PHASE 5: Final validation...")
            validated_circuit = await self._validate_system(integrated_circuit)

            # =========================================================================
            # PHASE 6: Aggregate metrics and return
            # =========================================================================
            self.design_metrics['end_time'] = datetime.now()
            self._log_final_metrics(validated_circuit)

            # Return result with success flag and module data
            # Success is true if we have any components (even if validation is imperfect)
            has_components = len(validated_circuit.get('components', [])) > 0
            validation_status = validated_circuit.get('validation_status', 'UNKNOWN')

            # Fix H.3: Pass interface definitions and the raw interface
            # signal map through to step_3_low_level.py.  This is the
            # source-of-truth for which signals map to which SYS_ net
            # names — independent of any supervisor cleaning.
            interface_signal_map = integrated_circuit.get(
                '_interface_signal_map', {}
            )
            
            # Phase A (Forensic Fix 20260211): Extract integration status
            integration_status = integrated_circuit.get('_integration_status', {})

            return {
                'success': has_components,
                'circuit': validated_circuit,
                'modules': self.module_results,
                'validation_status': validation_status,
                'interfaces': self.interfaces,
                'interface_signal_map': interface_signal_map,
                'integration_status': integration_status,
                'reconciliation_report': reconciliation_report,
                'statistics': {
                    'modules_designed': self.design_metrics['modules_designed'],
                    'modules_failed': self.design_metrics['modules_failed'],
                    'total_components': len(validated_circuit.get('components', [])),
                    'total_connections': len(validated_circuit.get('connections', [])),
                    'duration_seconds': (self.design_metrics['end_time'] -
                                        self.design_metrics['start_time']).total_seconds()
                }
            }

        except Exception as e:
            logger.error(f"Design orchestration failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return self._create_fallback_circuit(high_level_design)

    async def _reconcile_interface_contract(
        self,
        modules: List[Dict],
        interfaces: Dict,
    ) -> Dict:
        """
        Fix K.9 + Phase C: Interface contract reconciliation with component-level validation.

        Two-layer check:
        1. PIN-LEVEL: Do the selected components have pins whose names match
           the required interface signals? If the IC simply doesn't have a
           POWER_GOOD pin, no amount of wiring can create one.
        2. NET-LEVEL: Are the required signals actually wired (present in
           pinNetMapping)? This catches cases where the pin exists but the
           connection agent forgot to wire it.

        Returns a report dict keyed by module_name with missing signals.
        """
        reconciliation_report = {}

        for module_result in modules:
            if not module_result.get('success', False):
                continue

            module_name = module_result.get('module_name', module_result.get('name', 'Unknown'))
            interface = interfaces.get(module_name, {})

            # Extract circuit data
            if 'circuit' in module_result:
                module_circuit = module_result.get('circuit', {})
            else:
                module_circuit = {
                    'components': module_result.get('components', []),
                    'connections': module_result.get('connections', []),
                    'pinNetMapping': module_result.get('pinNetMapping', {}),
                    'nets': module_result.get('nets', [])
                }

            pin_net_mapping = module_circuit.get('pinNetMapping', {})
            components = module_circuit.get('components', [])

            # Fix K.9: Build a set of ALL pin names across all components in this module.
            # This lets us detect when the selected ICs fundamentally lack a required signal.
            all_pin_names = set()
            for comp in components:
                for pin in comp.get('pins', []):
                    pname = pin.get('name', '').upper().replace('_', '')
                    if pname:
                        all_pin_names.add(pname)

            # Check all required outputs
            required_outputs = set(interface.get('outputs', {}).keys()) | set(interface.get('power_out', []))
            connected_nets = {str(n).upper() for n in pin_net_mapping.values()}

            missing_outputs = []
            for out in required_outputs:
                out_upper = str(out).upper()
                out_normalized = out_upper.replace('_', '')
                if out_upper not in connected_nets:
                    # Also check if ANY component pin name matches (fuzzy)
                    has_candidate_pin = any(
                        out_normalized in pn or pn in out_normalized
                        for pn in all_pin_names
                    ) if len(out_normalized) >= 3 else False
                    missing_outputs.append({
                        'signal': out,
                        'has_candidate_pin': has_candidate_pin,
                    })

            # Check all required inputs
            required_inputs = set(interface.get('inputs', {}).keys()) | set(interface.get('power_in', []))
            missing_inputs = []
            for inp in required_inputs:
                inp_upper = str(inp).upper()
                inp_normalized = inp_upper.replace('_', '')
                if inp_upper not in connected_nets:
                    has_candidate_pin = any(
                        inp_normalized in pn or pn in inp_normalized
                        for pn in all_pin_names
                    ) if len(inp_normalized) >= 3 else False
                    missing_inputs.append({
                        'signal': inp,
                        'has_candidate_pin': has_candidate_pin,
                    })

            if missing_outputs or missing_inputs:
                # Fix K.9: Escalate to ERROR for signals with NO candidate pin
                # (the IC physically cannot provide the signal).
                no_pin_outputs = [m['signal'] for m in missing_outputs if not m['has_candidate_pin']]
                no_pin_inputs = [m['signal'] for m in missing_inputs if not m['has_candidate_pin']]
                wiring_outputs = [m['signal'] for m in missing_outputs if m['has_candidate_pin']]
                wiring_inputs = [m['signal'] for m in missing_inputs if m['has_candidate_pin']]

                if no_pin_outputs or no_pin_inputs:
                    logger.error(
                        f"   [RECONCILE] {module_name}: IC LACKS required signals! "
                        f"No candidate pins for: outputs={no_pin_outputs}, inputs={no_pin_inputs}"
                    )
                if wiring_outputs or wiring_inputs:
                    logger.warning(
                        f"   [RECONCILE] {module_name}: Unwired signals (pins exist): "
                        f"outputs={wiring_outputs}, inputs={wiring_inputs}"
                    )

                reconciliation_report[module_name] = {
                    'missing_outputs': [m['signal'] for m in missing_outputs],
                    'missing_inputs': [m['signal'] for m in missing_inputs],
                    'no_pin_outputs': no_pin_outputs,
                    'no_pin_inputs': no_pin_inputs,
                }

        return reconciliation_report

    def _auto_resolve_interface_gaps(
        self,
        modules: List[Dict],
        report: Dict,
    ) -> List[Dict]:
        """
        Phase C+ (Feb 2026): Deterministic interface gap repair.
        
        Attempts to map missing interface signals to suitable component pins
        using fuzzy matching on pin names and types.
        """
        updated_modules = []
        
        for module_result in modules:
            module_name = module_result.get('module_name', module_result.get('name', 'Unknown'))
            gaps = report.get(module_name)
            
            if not gaps or not module_result.get('success', False):
                updated_modules.append(module_result)
                continue
                
            # Create working copy of circuit
            if 'circuit' in module_result:
                circuit = copy.deepcopy(module_result['circuit'])
            else:
                circuit = {
                    'components': copy.deepcopy(module_result.get('components', [])),
                    'connections': copy.deepcopy(module_result.get('connections', [])),
                    'pinNetMapping': copy.deepcopy(module_result.get('pinNetMapping', {})),
                    'nets': copy.deepcopy(module_result.get('nets', []))
                }
                
            pin_net_mapping = circuit['pinNetMapping']
            components = circuit['components']
            
            resolved_count = 0
            
            # Combine all missing signals to resolve
            missing = set(gaps.get('missing_outputs', [])) | set(gaps.get('missing_inputs', []))
            
            for signal in missing:
                sig_upper = signal.upper().replace('_', '')
                best_pin = None
                
                # Search components for candidate pins
                for comp in components:
                    ref = comp.get('ref', '')
                    pins = comp.get('pins', [])
                    
                    for pin in pins:
                        pin_num = pin.get('number', '')
                        pin_name = pin.get('name', '').upper().replace('_', '')
                        pin_type = pin.get('type', '').lower()
                        pin_ref = f"{ref}.{pin_num}"
                        
                        # Only consider pins that are floating or on NC_ nets
                        current_net = pin_net_mapping.get(pin_ref, '')
                        if current_net and not current_net.startswith('NC_') and not current_net.startswith('NET_'):
                            continue
                            
                        # Fuzzy match: name similarity or type match for power
                        if sig_upper in pin_name or pin_name in sig_upper:
                            best_pin = pin_ref
                            break
                            
                        # Power rail match
                        if ('VCC' in sig_upper or 'VDD' in sig_upper) and pin_type == 'power_in':
                            best_pin = pin_ref
                            break
                        if 'GND' in sig_upper and pin_type == 'ground':
                            best_pin = pin_ref
                            break
                            
                    if best_pin:
                        break
                        
                if best_pin:
                    pin_net_mapping[best_pin] = signal
                    resolved_count += 1
                    logger.info(f"   [AUTO-RESOLVE] {module_name}: Mapped '{signal}' to {best_pin}")
            
            if resolved_count > 0:
                # Update module result with repaired circuit
                if 'circuit' in module_result:
                    module_result['circuit'] = circuit
                else:
                    module_result.update(circuit)
                logger.info(f"   [AUTO-RESOLVE] {module_name}: Resolved {resolved_count} gap(s)")
                
            updated_modules.append(module_result)
            
        return updated_modules

    def _extract_modules(self, high_level_design: Dict) -> List[Dict]:
        """
        Extract module specifications from high-level design.

        This method parses the high-level design to identify individual modules
        that need to be designed. Each module becomes a separate design task.

        Args:
            high_level_design: The complete high-level design dict

        Returns:
            List of module specification dicts, each containing:
                - name: Module name
                - description: Module description
                - function: Module function
                - inputs: Expected inputs
                - outputs: Expected outputs
                - requirements: Module-specific requirements
        """
        modules = []

        # Check for 'modules' key (standard format)
        if 'modules' in high_level_design:
            raw_modules = high_level_design['modules']

            # Handle string format (sometimes AI returns string)
            if isinstance(raw_modules, str):
                try:
                    raw_modules = json.loads(raw_modules)
                except json.JSONDecodeError:
                    # Parse as list of names
                    raw_modules = [{'name': m.strip()} for m in raw_modules.split(',')]

            # Normalize each module
            for module in raw_modules:
                if isinstance(module, str):
                    modules.append({'name': module, 'description': module})
                elif isinstance(module, dict):
                    # Ensure minimum required fields
                    normalized = {
                        'name': module.get('name', module.get('module', 'Unknown')),
                        'description': module.get('description', ''),
                        # Fix 1.1: Use description as primary source for function.
                        # Step 2 provides 'description', not 'function' or 'purpose'.
                        # The `or` operator treats '' as falsy, cascading correctly.
                        'function': (
                            module.get('description')
                            or module.get('function')
                            or module.get('purpose', '')
                        ),
                        'inputs': module.get('inputs', []),
                        'outputs': module.get('outputs', []),
                        # Fix 1.2: Use specifications as primary source for requirements.
                        # Step 2 provides 'specifications', not 'requirements'.
                        'requirements': module.get('specifications') or module.get('requirements', {}),
                        'specifications': module.get('specifications', {}),
                        # Fix 2.1: Pass through Step 2 fields for sibling context
                        'subcomponents': module.get('subcomponents', []),
                        'type': module.get('type', 'standard'),
                        # Phase I (Forensic Fix 20260208): Extract operating voltage
                        # domain from Step 2 output for per-module rating validation.
                        'operating_voltage': module.get('operating_voltage', ''),
                    }
                    modules.append(normalized)

        # Check for 'circuitModules' key (alternative format)
        elif 'circuitModules' in high_level_design:
            for module in high_level_design['circuitModules']:
                modules.append({
                    'name': module.get('name', 'Unknown'),
                    'description': module.get('description', ''),
                    'function': (
                        module.get('description')
                        or module.get('function')
                        or module.get('purpose', '')
                    ),
                    'inputs': module.get('inputs', []),
                    'outputs': module.get('outputs', []),
                    'requirements': module.get('specifications') or module.get('requirements', {}),
                    'specifications': module.get('specifications', {}),
                    'subcomponents': module.get('subcomponents', []),
                    'type': module.get('type', 'standard'),
                    'operating_voltage': module.get('operating_voltage', ''),
                })

        # Add circuit-level context to each module
        circuit_name = high_level_design.get('circuitName', 'Circuit')
        circuit_requirements = high_level_design.get('requirements', {})

        for module in modules:
            module['circuitName'] = circuit_name
            module['circuitRequirements'] = circuit_requirements

        # Fix 2.2: Build sibling module summary for cross-module net naming
        if len(modules) >= 2:
            sibling_summary = self._build_sibling_summary(modules, circuit_name)
            for module in modules:
                module['sibling_interfaces'] = sibling_summary

        return modules

    @staticmethod
    def _build_sibling_summary(modules: List[Dict], circuit_name: str) -> str:
        """
        Fix 2.2: Build a compact interface summary of ALL modules.

        Injected into every module's prompt so the AI uses consistent
        interface net names across modules. Fully generic — works with
        any circuit type by reading whatever Step 2 produced.
        """
        lines = [
            f"SYSTEM MODULE INTERFACES — {circuit_name}",
            "(for cross-module net name consistency)",
            "",
        ]

        header = f"{'Module':<30} {'Type':<12} {'Inputs':<35} {'Outputs':<35}"
        separator = '-' * len(header)
        lines.append(separator)
        lines.append(header)
        lines.append(separator)

        for mod in modules:
            name = mod.get('name', 'Unknown')[:29]
            mod_type = mod.get('type', 'standard')[:11]

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

    async def _define_interfaces(self, modules: List[Dict],
                                  high_level_design: Dict) -> Dict:
        """
        Define interfaces between modules.

        Fix 2.3: Replaced keyword heuristic interface detection with actual
        Step 2 inputs/outputs data. Previously guessed from module names
        (e.g., "if 'power' in name → provides power rails"). Now reads
        the actual defined interfaces from Step 2.

        This is GENERIC — works with ANY circuit type because it uses
        the actual module definitions, not assumptions about naming.

        Args:
            modules: List of module specifications (with Step 2 fields)
            high_level_design: The complete high-level design

        Returns:
            Interface dict mapping module names to their interface contracts
        """
        interfaces = {}

        # Classify signals into power vs. signal categories.
        # Power nets are identified by common voltage patterns in their names.
        power_patterns = config.DESIGN_SUPERVISOR_POWER_SIGNAL_PATTERNS

        def _classify_signal(sig_data: Any) -> str:
            """Return 'power' or 'signal' based on signal data."""
            if isinstance(sig_data, dict):
                stype = sig_data.get('type', '').upper()
                if 'POWER' in stype:
                    return 'power'
                name = sig_data.get('name', '').upper()
            else:
                name = str(sig_data).upper()
            
            upper = name.replace(' ', '_')
            if any(p in upper for p in power_patterns):
                return 'power'
            return 'signal'

        for module in modules:
            module_name = module.get('name', 'Unknown')

            interface = {
                'inputs': {},
                'outputs': {},
                'power_in': [],
                'power_out': [],
                'signals_in': [],
                'signals_out': [],
                'isolation_domain': module.get('isolation_domain', 'GND_SYSTEM')
            }

            # Parse inputs from Step 2 data
            raw_inputs = module.get('inputs', [])
            if isinstance(raw_inputs, list):
                for inp in raw_inputs:
                    inp_name = inp.get('name', str(inp)) if isinstance(inp, dict) else str(inp)
                    interface['inputs'][inp_name] = (
                        inp if isinstance(inp, dict) else {'name': inp_name, 'type': 'signal'}
                    )
                    kind = _classify_signal(inp)
                    if kind == 'power':
                        interface['power_in'].append(inp_name)
                    else:
                        interface['signals_in'].append(inp_name)
            elif isinstance(raw_inputs, dict):
                interface['inputs'] = raw_inputs

            # Parse outputs from Step 2 data
            raw_outputs = module.get('outputs', [])
            if isinstance(raw_outputs, list):
                for out in raw_outputs:
                    out_name = out.get('name', str(out)) if isinstance(out, dict) else str(out)
                    interface['outputs'][out_name] = (
                        out if isinstance(out, dict) else {'name': out_name, 'type': 'signal'}
                    )
                    kind = _classify_signal(out)
                    if kind == 'power':
                        interface['power_out'].append(out_name)
                    else:
                        interface['signals_out'].append(out_name)
            elif isinstance(raw_outputs, dict):
                interface['outputs'] = raw_outputs

            # Fallback: if Step 2 provided no inputs/outputs, ensure at least
            # GND is listed so the module gets basic power connectivity.
            if not interface['power_in'] and not interface['power_out']:
                interface['power_in'] = ['GND']

            interfaces[module_name] = interface

        # Second pass: auto-connect power suppliers to consumers.
        # A module whose outputs include power nets is a supplier.
        power_suppliers = [
            m for m in modules if interfaces[m['name']]['power_out']
        ]
        if power_suppliers:
            # Merge all supplier rails into a shared set
            all_power_rails = []
            for supplier in power_suppliers:
                all_power_rails.extend(interfaces[supplier['name']]['power_out'])
            # Deduplicate while preserving order
            seen: set = set()
            unique_rails = []
            for rail in all_power_rails:
                if rail not in seen:
                    seen.add(rail)
                    unique_rails.append(rail)

            for module in modules:
                if module not in power_suppliers:
                    # Add supplier rails to consumer's power_in if not already present
                    existing = set(interfaces[module['name']]['power_in'])
                    for rail in unique_rails:
                        if rail not in existing:
                            interfaces[module['name']]['power_in'].append(rail)

        logger.debug(f"Defined interfaces: {json.dumps(interfaces, indent=2)}")
        return interfaces

    async def _design_all_modules(self, modules: List[Dict]) -> List[Dict]:
        """
        Design all modules, using parallelism when possible.

        This method spawns Module Agents for each module. Modules can be
        designed in parallel since they don't depend on each other's
        internal structure (only on interfaces).

        Args:
            modules: List of module specifications

        Returns:
            List of module design results
        """
        # Get parallelism config
        max_parallel = config.MULTI_AGENT_CONFIG.get('max_parallel_modules', 3)

        results = []

        # Design modules in batches for controlled parallelism
        for i in range(0, len(modules), max_parallel):
            batch = modules[i:i + max_parallel]

            logger.info(f"   Designing batch {i // max_parallel + 1}: {[m['name'] for m in batch]}")

            # Create tasks for parallel execution
            tasks = []
            for module in batch:
                module_interface = self.interfaces.get(module['name'], {})
                task = self._design_single_module(module, module_interface)
                tasks.append(task)

            # Execute batch in parallel
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for j, result in enumerate(batch_results):
                module_name = batch[j]['name']

                if isinstance(result, Exception):
                    logger.error(f"   ❌ {module_name} FAILED: {str(result)}")
                    results.append({
                        'success': False,
                        'module_name': module_name,
                        'error': str(result)
                    })
                elif result.get('success', False):
                    logger.info(f"   ✅ {module_name} completed: "
                               f"{len(result.get('components', []))} components")
                    results.append(result)
                else:
                    logger.warning(f"   ⚠️ {module_name} returned with issues")
                    results.append(result)

        return results

    async def _design_single_module(self, module: Dict, interface: Dict) -> Dict:
        """
        Design a single module using the Module Agent.

        Args:
            module: Module specification
            interface: Interface contract for this module

        Returns:
            Module design result
        """
        try:
            result = await self.module_agent.design_module(module, interface)

            # Add module name to result
            result['module_name'] = module['name']

            # Track metrics
            if result.get('success', False):
                self.design_metrics['total_components'] += len(result.get('components', []))
                self.design_metrics['total_connections'] += len(result.get('connections', []))

            return result

        except Exception as e:
            logger.error(f"Module design failed for {module['name']}: {str(e)}")
            return {
                'success': False,
                'module_name': module['name'],
                'error': str(e)
            }

    async def _integrate_modules(self) -> Dict:
        """
        Integrate all designed modules into a single circuit.

        This method:
        1. Collects all successful module designs
        2. Calls the Integration Agent to connect them
        3. Creates the unified circuit structure

        Returns:
            Integrated circuit dict
        """
        # Collect successful module circuits
        successful_modules = [r for r in self.module_results if r.get('success', False)]

        if not successful_modules:
            logger.error("No successful modules to integrate!")
            return {'success': False, 'error': 'No modules to integrate'}

        # Use Integration Agent to connect modules
        integrated = await self.integration_agent.integrate_modules(
            successful_modules,
            self.interfaces
        )

        return integrated

    async def _validate_system(self, circuit: Dict) -> Dict:
        """
        Perform final system-level validation.

        This validates the complete integrated circuit for:
        - All interface signals are properly connected
        - No orphaned modules
        - Power distribution is complete
        - No critical ERC violations

        Args:
            circuit: The integrated circuit

        Returns:
            Validated circuit with status
        """
        # Import circuit supervisor for validation
        from workflow.circuit_supervisor import CircuitSupervisor

        supervisor = CircuitSupervisor()
        validated = supervisor.supervise_and_fix(circuit)

        return validated

    def _create_fallback_circuit(self, high_level_design: Dict) -> Dict:
        """
        Create a minimal fallback circuit when design fails.

        This ensures we always return a valid circuit structure,
        even if the multi-agent design completely fails.

        Args:
            high_level_design: The original high-level design

        Returns:
            Minimal valid circuit
        """
        circuit_name = high_level_design.get('circuitName', 'Fallback_Circuit')

        logger.warning(f"Creating fallback circuit for {circuit_name}")

        fallback_circuit = {
            'circuitName': circuit_name,
            'components': [
                {
                    'ref': 'J1',
                    'type': 'connector',
                    'value': 'CONN-2',
                    'package': 'HDR-2X1',
                    'pins': [
                        {'number': '1', 'name': '1', 'type': 'passive'},
                        {'number': '2', 'name': '2', 'type': 'passive'}
                    ]
                },
                {
                    'ref': 'R1',
                    'type': 'resistor',
                    'value': '10k',
                    'package': '0603',
                    'pins': [
                        {'number': '1', 'name': '1', 'type': 'passive'},
                        {'number': '2', 'name': '2', 'type': 'passive'}
                    ]
                }
            ],
            'connections': [
                {'net': 'NET1', 'points': ['J1.1', 'R1.1']},
                {'net': 'GND', 'points': ['J1.2', 'R1.2']}
            ],
            'pinNetMapping': {
                'J1.1': 'NET1',
                'J1.2': 'GND',
                'R1.1': 'NET1',
                'R1.2': 'GND'
            },
            'nets': ['NET1', 'GND'],
            'validation_status': 'FALLBACK',
            'design_error': 'Multi-agent design failed - using fallback circuit'
        }

        # Return in same format as successful orchestration
        return {
            'success': False,
            'circuit': fallback_circuit,
            'modules': [],
            'validation_status': 'FALLBACK',
            'error': 'Design failed - using fallback circuit',
            'statistics': {
                'modules_designed': 0,
                'modules_failed': 0,
                'total_components': 2,
                'total_connections': 2,
                'duration_seconds': 0
            }
        }

    def _log_final_metrics(self, circuit: Dict) -> None:
        """
        Log final design metrics.

        Args:
            circuit: The final circuit
        """
        duration = (self.design_metrics['end_time'] -
                   self.design_metrics['start_time']).total_seconds()

        logger.info("\n" + "=" * 80)
        logger.info("DESIGN SUPERVISOR - ORCHESTRATION COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Duration: {duration:.1f} seconds")
        logger.info(f"Modules designed: {self.design_metrics['modules_designed']}")
        logger.info(f"Modules failed: {self.design_metrics['modules_failed']}")
        logger.info(f"Total components: {len(circuit.get('components', []))}")
        logger.info(f"Total connections: {len(circuit.get('connections', []))}")
        logger.info(f"Validation status: {circuit.get('validation_status', 'UNKNOWN')}")
        logger.info("=" * 80)
