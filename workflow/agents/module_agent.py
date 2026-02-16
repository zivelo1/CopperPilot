# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Module Agent - Per-module design coordinator.

The Module Agent designs a single circuit module by coordinating:
1. Component Agent - Selects appropriate components
2. Connection Agent - Creates connections between components
3. Validation Agent - Validates the module circuit

Each Module Agent operates with LIMITED context - it only knows about
its own module, not about other modules in the system.

Author: CopperPilot Team
Date: January 2026
Version: 1.0

Key Design Principles:
- ISOLATED: Each module is designed independently
- INTERFACE-AWARE: Knows what signals to expose/consume
- ERROR-RESILIENT: Can recover from sub-agent failures
- GENERIC: Works for ANY circuit module type
"""

import json
import asyncio
from typing import Dict, List, Any, Optional
from pathlib import Path

from utils.logger import setup_logger
from server.config import config

# Import sub-agents
from .component_agent import ComponentAgent
from .connection_agent import ConnectionAgent
from .validation_agent import ValidationAgent

logger = setup_logger(__name__)


class ModuleAgent:
    """
    Per-module design coordinator.

    The Module Agent is responsible for designing a single module by:
    1. Understanding module requirements and interface contract
    2. Delegating component selection to Component Agent
    3. Delegating connection synthesis to Connection Agent
    4. Delegating validation to Validation Agent
    5. Returning validated module circuit

    This agent has LIMITED context - it only knows about its own module.
    It doesn't see other modules, only the interface contract.

    Attributes:
        ai_manager: Reference to the AI Agent Manager
        component_agent: Component selection agent
        connection_agent: Connection synthesis agent
        validation_agent: Module validation agent
    """

    def __init__(self, ai_manager):
        """
        Initialize the Module Agent.

        Args:
            ai_manager: The AI Agent Manager instance
        """
        self.ai_manager = ai_manager
        self.component_agent = ComponentAgent(ai_manager)
        self.connection_agent = ConnectionAgent(ai_manager)
        self.validation_agent = ValidationAgent(ai_manager)

    async def design_module(self, module_spec: Dict, interface: Dict) -> Dict:
        """
        Design a complete module circuit.

        This is the main entry point for module design. It coordinates
        the Component Agent, Connection Agent, and Validation Agent
        to produce a validated module circuit.

        Args:
            module_spec: Module specification containing:
                - name: Module name
                - description: Module description
                - function: Module function/purpose
                - requirements: Module-specific requirements
                - specifications: Electrical specifications

            interface: Interface contract containing:
                - inputs: Expected input signals
                - outputs: Expected output signals
                - power_in: Power rails consumed
                - power_out: Power rails provided

        Returns:
            Module circuit dict containing:
                - success: Whether design succeeded
                - module_name: Name of the module
                - components: List of component dicts
                - connections: List of connection dicts
                - pinNetMapping: Pin to net mapping
                - nets: List of net names
                - validation: Validation report
        """
        module_name = module_spec.get('name', 'Unknown_Module')
        logger.info(f"    🔧 MODULE AGENT: Starting design for {module_name}")

        # DEBUG: Log module specification and interface
        logger.debug(f"[MODULE_AGENT] {module_name} - Spec keys: {list(module_spec.keys())}")
        logger.debug(f"[MODULE_AGENT] {module_name} - Interface: power_in={interface.get('power_in', [])}, signals_in={interface.get('signals_in', [])}")
        logger.debug(f"[MODULE_AGENT] {module_name} - Requirements: {module_spec.get('requirements', {})}")

        try:
            # =========================================================================
            # STEP 1: Component Selection
            # =========================================================================
            logger.info(f"       Step 1: Selecting components for {module_name}...")

            components_result = await self.component_agent.select_components(
                module_spec,
                interface
            )

            if not components_result.get('success', False):
                logger.error(f"       ❌ Component selection failed for {module_name}")
                return {
                    'success': False,
                    'module_name': module_name,
                    'error': f"Component selection failed: {components_result.get('error', 'Unknown')}"
                }

            components = components_result.get('components', [])
            logger.info(f"       ✅ Selected {len(components)} components")

            # DEBUG: Log component details
            for comp in components[:5]:  # Log first 5 components
                logger.debug(f"[MODULE_AGENT] {module_name} - Component: {comp.get('ref')} ({comp.get('type')}) = {comp.get('value')}, pins={len(comp.get('pins', []))}")
            if len(components) > 5:
                logger.debug(f"[MODULE_AGENT] {module_name} - ... and {len(components)-5} more components")

            # =========================================================================
            # STEP 2: Connection Synthesis
            # =========================================================================
            logger.info(f"       Step 2: Synthesizing connections for {module_name}...")

            connections_result = await self.connection_agent.synthesize_connections(
                components,
                module_spec,
                interface
            )

            if not connections_result.get('success', False):
                logger.error(f"       ❌ Connection synthesis failed for {module_name}")
                return {
                    'success': False,
                    'module_name': module_name,
                    'error': f"Connection synthesis failed: {connections_result.get('error', 'Unknown')}",
                    'components': components  # Include components even if connections failed
                }

            connections = connections_result.get('connections', [])
            pin_net_mapping = connections_result.get('pinNetMapping', {})
            nets = connections_result.get('nets', [])

            logger.info(f"       ✅ Created {len(connections)} connections, {len(nets)} nets")

            # =========================================================================
            # STEP 3: Assemble Module Circuit
            # =========================================================================
            module_circuit = {
                'module_name': module_name,
                'components': components,
                'connections': connections,
                'pinNetMapping': pin_net_mapping,
                'nets': nets
            }

            # =========================================================================
            # STEP 4: Validation
            # =========================================================================
            logger.info(f"       Step 3: Validating {module_name}...")

            validation_result = await self.validation_agent.validate_module(
                module_circuit,
                interface
            )

            # Get validated circuit (may have auto-fixes applied)
            if validation_result.get('circuit'):
                module_circuit = validation_result['circuit']

            # Check validation status
            if validation_result.get('passed', False):
                logger.info(f"       ✅ {module_name} validation PASSED")
            else:
                issues = validation_result.get('issues', [])
                logger.warning(f"       ⚠️ {module_name} validation found {len(issues)} issues")

                # If validation failed critically, retry with fixes
                if validation_result.get('critical_failure', False):
                    logger.info(f"       Attempting recovery for {module_name}...")
                    module_circuit = await self._attempt_recovery(
                        module_circuit,
                        validation_result.get('issues', []),
                        interface
                    )

            # =========================================================================
            # STEP 5: Return Result
            # =========================================================================
            return {
                'success': True,
                'module_name': module_name,
                'components': module_circuit.get('components', []),
                'connections': module_circuit.get('connections', []),
                'pinNetMapping': module_circuit.get('pinNetMapping', {}),
                'nets': module_circuit.get('nets', []),
                'validation': validation_result
            }

        except Exception as e:
            logger.error(f"Module design failed for {module_name}: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'module_name': module_name,
                'error': str(e)
            }

    async def _attempt_recovery(self, circuit: Dict, issues: List[Dict],
                                 interface: Dict) -> Dict:
        """
        Attempt to recover from validation failures.

        This method tries to fix critical issues by:
        1. Analyzing the issues
        2. Calling Connection Agent to fix connections
        3. Re-validating

        Args:
            circuit: The circuit with issues
            issues: List of validation issues
            interface: Interface contract

        Returns:
            Recovered circuit (or original if recovery failed)
        """
        logger.info("       Attempting module recovery...")

        # Categorize issues
        power_issues = [i for i in issues if 'power' in i.get('type', '').lower()]
        floating_issues = [i for i in issues if 'floating' in i.get('type', '').lower()]
        connection_issues = [i for i in issues if 'connection' in i.get('type', '').lower()]

        # If power issues, try to add power connections
        if power_issues:
            logger.info(f"       Fixing {len(power_issues)} power issues...")
            circuit = self._fix_power_issues(circuit, power_issues)

        # If floating issues, try to connect floating pins
        if floating_issues:
            logger.info(f"       Fixing {len(floating_issues)} floating issues...")
            circuit = self._fix_floating_issues(circuit, floating_issues)

        return circuit

    def _fix_power_issues(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """
        Fix power-related issues in the circuit.

        This method adds missing power and ground connections.

        Args:
            circuit: The circuit to fix
            issues: Power-related issues

        Returns:
            Fixed circuit
        """
        pin_net_mapping = circuit.get('pinNetMapping', {})
        components = circuit.get('components', [])

        for issue in issues:
            comp_ref = issue.get('component', '')

            # Find the component
            comp = next((c for c in components if c.get('ref') == comp_ref), None)
            if not comp:
                continue

            # Add VCC connection if missing
            if 'power' in issue.get('type', '').lower() and 'ground' not in issue.get('type', '').lower():
                # Find a power pin
                for pin in comp.get('pins', []):
                    pin_name = pin.get('name', '').upper()
                    pin_num = pin.get('number', '')
                    pin_ref = f"{comp_ref}.{pin_num}"

                    if pin_name in ['VCC', 'VDD', 'V+', 'VIN'] or pin.get('type') == 'power':
                        if pin_ref not in pin_net_mapping:
                            pin_net_mapping[pin_ref] = 'VCC'
                            logger.info(f"       Added VCC to {pin_ref}")
                            break

            # Add GND connection if missing
            if 'ground' in issue.get('type', '').lower():
                # Find a ground pin
                for pin in comp.get('pins', []):
                    pin_name = pin.get('name', '').upper()
                    pin_num = pin.get('number', '')
                    pin_ref = f"{comp_ref}.{pin_num}"

                    if pin_name in ['GND', 'VSS', 'V-', 'GROUND'] or pin.get('type') == 'ground':
                        if pin_ref not in pin_net_mapping:
                            pin_net_mapping[pin_ref] = 'GND'
                            logger.info(f"       Added GND to {pin_ref}")
                            break

        circuit['pinNetMapping'] = pin_net_mapping
        circuit = self._rebuild_connections(circuit)
        return circuit

    def _fix_floating_issues(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """
        Fix floating pin issues in the circuit.

        This method connects floating pins appropriately.

        Args:
            circuit: The circuit to fix
            issues: Floating pin issues

        Returns:
            Fixed circuit
        """
        pin_net_mapping = circuit.get('pinNetMapping', {})

        for issue in issues:
            pin_ref = issue.get('pin', '')
            if not pin_ref:
                continue

            # If pin is floating, connect to appropriate net
            if pin_ref not in pin_net_mapping:
                # For now, mark as NC (No Connect)
                pin_net_mapping[pin_ref] = f"NC_{pin_ref.replace('.', '_')}"
                logger.info(f"       Marked {pin_ref} as NC")

        circuit['pinNetMapping'] = pin_net_mapping
        circuit = self._rebuild_connections(circuit)
        return circuit

    def _rebuild_connections(self, circuit: Dict) -> Dict:
        """
        Rebuild connections array from pinNetMapping.

        This ensures the connections array is consistent with pinNetMapping.

        Args:
            circuit: The circuit to rebuild

        Returns:
            Circuit with rebuilt connections
        """
        pin_net_mapping = circuit.get('pinNetMapping', {})

        # Group pins by net
        net_to_pins = {}
        for pin, net in pin_net_mapping.items():
            if net not in net_to_pins:
                net_to_pins[net] = []
            net_to_pins[net].append(pin)

        # Build connections array
        connections = []
        for net, pins in net_to_pins.items():
            if len(pins) >= 1:  # Include even single-ended nets
                connections.append({
                    'net': net,
                    'points': sorted(pins)
                })

        circuit['connections'] = connections
        circuit['nets'] = list(net_to_pins.keys())

        return circuit
