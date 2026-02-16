# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Connection Agent - Connection synthesis for circuit modules.

The Connection Agent is responsible for creating connections between
components that were selected by the Component Agent. It receives
a list of components with their pins and creates:
1. Net assignments for each pin (pinNetMapping)
2. Connection arrays grouping pins by net
3. Interface signal routing

This separation allows:
1. Focused prompts for connection logic
2. Component selection without wiring concerns
3. Easier debugging of connection issues
4. Better handling of complex topologies

Author: CopperPilot Team
Date: January 2026
Version: 1.0

Key Design Principles:
- FOCUSED: Only creates connections, no component selection
- INTERFACE-AWARE: Routes interface signals correctly
- NO-SHORTS: Ensures no 2-terminal passive has both pins on same net
- COMPLETE: All pins must be assigned to a net
"""

import json
import re
from typing import Dict, List, Any, Optional, Set
from pathlib import Path

from utils.logger import setup_logger
from server.config import config

logger = setup_logger(__name__)

# Pre-compiled pin-reference regex — use config's pre-compiled version
_PIN_REF_RE = config.PIN_REFERENCE_PATTERN_RE


class ConnectionAgent:
    """
    Connection synthesis agent for circuit modules.

    The Connection Agent takes a list of components with pins and
    creates the wiring between them. It ensures:
    - All power pins are connected to appropriate rails
    - All ground pins are connected to ground
    - Signal flow makes sense for the module function
    - Interface signals are properly exposed
    - No passive components have both pins on the same net

    Attributes:
        ai_manager: Reference to the AI Agent Manager
    """

    def __init__(self, ai_manager):
        """
        Initialize the Connection Agent.

        Args:
            ai_manager: The AI Agent Manager instance
        """
        self.ai_manager = ai_manager

    async def synthesize_connections(self, components: List[Dict],
                                      module_spec: Dict,
                                      interface: Dict) -> Dict:
        """
        Synthesize connections between components.

        This method analyzes the components and creates appropriate
        connections based on:
        - Component types and pin functions
        - Module purpose and signal flow
        - Interface requirements

        Args:
            components: List of component dicts with pins
            module_spec: Module specification
            interface: Interface contract

        Returns:
            Dict containing:
                - success: Whether synthesis succeeded
                - connections: List of connection dicts
                - pinNetMapping: Pin to net mapping
                - nets: List of net names
        """
        module_name = module_spec.get('name', 'Unknown')
        logger.info(f"         ConnectionAgent: Synthesizing connections for {module_name}")

        # DEBUG: Log input summary
        logger.debug(f"[CONNECTION_AGENT] {module_name} - Components count: {len(components)}")
        logger.debug(f"[CONNECTION_AGENT] {module_name} - Interface signals_in: {interface.get('signals_in', [])}")
        logger.debug(f"[CONNECTION_AGENT] {module_name} - Interface signals_out: {interface.get('signals_out', [])}")
        total_pins = sum(len(c.get('pins', [])) for c in components)
        logger.debug(f"[CONNECTION_AGENT] {module_name} - Total pins to connect: {total_pins}")

        try:
            # Build the prompt
            prompt = self._build_connection_prompt(components, module_spec, interface)

            # Make AI call
            result = await self.ai_manager.call_ai(
                "connection_agent",
                prompt,
                context={
                    "components": components,
                    "module": module_spec,
                    "interface": interface
                },
                use_cache=True
            )

            if not result.get('success', False):
                logger.error(f"         AI call failed for {module_name}: {result.get('error')}")
                return {
                    'success': False,
                    'error': result.get('error', 'AI call failed')
                }

            # Parse response
            parsed = self._parse_response(result.get('raw_response', ''))

            if not parsed or 'pinNetMapping' not in parsed:
                logger.error(f"         Failed to parse connection response for {module_name}")
                # Try to create basic connections
                return self._create_basic_connections(components, interface)

            # Validate and fix connections
            pin_net_mapping = parsed.get('pinNetMapping', {})
            pin_net_mapping = self._validate_connections(pin_net_mapping, components)

            # Fix G.2: Remove phantom component references
            pin_net_mapping = self._remove_phantom_references(pin_net_mapping, components)

            # Fix G.9/G.3: Reject pin-reference net names and check dangling internals
            pin_net_mapping = self._fix_pin_reference_nets(pin_net_mapping)
            self._warn_dangling_internal_nets(pin_net_mapping, interface)

            # TC #94: Ensure interface signals exist in pinNetMapping
            pin_net_mapping = self._ensure_interface_signals(pin_net_mapping, components, interface)

            # Rebuild connections from pinNetMapping
            connections, nets = self._build_connections_from_mapping(pin_net_mapping)

            logger.info(f"         Synthesized {len(connections)} connections, {len(nets)} nets")

            return {
                'success': True,
                'connections': connections,
                'pinNetMapping': pin_net_mapping,
                'nets': nets
            }

        except Exception as e:
            logger.error(f"Connection synthesis failed for {module_name}: {str(e)}")
            return self._create_basic_connections(components, interface)

    def _build_connection_prompt(self, components: List[Dict],
                                  module_spec: Dict,
                                  interface: Dict) -> str:
        """
        Build the connection synthesis prompt.

        Args:
            components: List of components
            module_spec: Module specification
            interface: Interface contract

        Returns:
            Formatted prompt string
        """
        # Load prompt template
        prompt_file = Path("ai_agents/prompts/multi_agent/connection_synthesis_prompt.txt")

        if prompt_file.exists():
            prompt = prompt_file.read_text()
        else:
            prompt = self._get_default_prompt()

        # Replace template variables
        prompt = prompt.replace('{{ module_name }}', module_spec.get('name', 'Unknown'))
        prompt = prompt.replace('{{ module_function }}', module_spec.get('function', module_spec.get('description', '')))
        prompt = prompt.replace('{{ components }}', json.dumps(components, indent=2))
        prompt = prompt.replace('{{ interface_inputs }}', json.dumps(interface.get('inputs', {}), indent=2))
        prompt = prompt.replace('{{ interface_outputs }}', json.dumps(interface.get('outputs', {}), indent=2))
        prompt = prompt.replace('{{ power_in }}', json.dumps(interface.get('power_in', ['VCC', 'GND']), indent=2))
        prompt = prompt.replace('{{ power_out }}', json.dumps(interface.get('power_out', []), indent=2))

        return prompt

    def _get_default_prompt(self) -> str:
        """
        Get default connection synthesis prompt.

        TC #94 FIX: Improved prompt with stronger interface signal requirements.

        Returns:
            Default prompt string
        """
        return """You are a Connection Synthesis Agent.

## Your Task
Create all connections between the components for this circuit module.

## Module Information
**Name**: {{ module_name }}
**Function**: {{ module_function }}

## Components (from Component Agent)
{{ components }}

## Interface Contract
**Power Inputs**: {{ power_in }}
**Power Outputs**: {{ power_out }}
**Signal Inputs**: {{ interface_inputs }}
**Signal Outputs**: {{ interface_outputs }}

## Output Format
Return a JSON object with this EXACT structure:

```json
{
  "pinNetMapping": {
    "U1.1": "VIN",
    "U1.2": "GND",
    "U1.3": "VCC_5V",
    "C1.1": "VIN",
    "C1.2": "GND",
    "C2.1": "VCC_5V",
    "C2.2": "GND"
  },
  "connectionNotes": [
    "U1 regulates VIN to VCC_5V",
    "C1 provides input filtering",
    "C2 provides output filtering"
  ]
}
```

## CRITICAL RULES - CONNECTION LAWS

### LAW 1: Every IC Must Have Power and Ground
- Find VCC/VDD pin → connect to power rail (VCC, VCC_5V, etc.)
- Find GND/VSS pin → connect to GND

### LAW 2: Every Pin Must Be Assigned
- No pin can be left without a net assignment
- Unused pins → assign to NC_<ref>_<pin> nets (e.g., NC_U1_9)

### LAW 3: Power Rails Need Multiple Connections
- VCC must connect to ≥2 pins (power + bypass cap)
- GND must connect to ≥2 pins

### LAW 4: TWO-TERMINAL PASSIVES MUST HAVE DIFFERENT NETS
**CRITICAL**: For any component with exactly 2 pins (R, C, L, D):
- Pin 1 MUST be on a DIFFERENT net than Pin 2
- WRONG: R1.1 → GND, R1.2 → GND (both on GND = shorted!)
- CORRECT: R1.1 → VCC, R1.2 → LED_ANODE (different nets)

If you violate LAW 4, the circuit will not function!

### LAW 5: Interface Signals MUST Use EXACT Names
**CRITICAL**: Interface signals connect this module to OTHER modules.
- For EACH signal in interface_inputs, create a net with that EXACT name
- For EACH signal in interface_outputs, create a net with that EXACT name
- Connect the appropriate component pin to these nets

Example:
- If interface_outputs contains "voltage_sense", you MUST create net "voltage_sense"
- If interface_inputs contains "enable", you MUST create net "enable"

These interface nets will only have ONE connection within THIS module (because
they connect to OTHER modules in the system). This is CORRECT and expected.

### LAW 6: Internal Signal Naming
- Internal signals (not in interface) should have descriptive names
- Use pattern: PURPOSE_COMPONENT (e.g., "GATE_DRIVE_Q1", "FEEDBACK_R2")
- Avoid generic NET_1, NET_2 unless truly generic

## Do NOT include:
- Component definitions (already provided)
- Connections array (will be built from pinNetMapping)

Return ONLY the JSON object."""

    def _parse_response(self, response: str) -> Optional[Dict]:
        """
        Parse AI response to extract connections.

        Args:
            response: Raw AI response text

        Returns:
            Parsed dict with pinNetMapping, or None if parsing failed
        """
        # Try to extract JSON from markdown code block
        json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try direct JSON parse
        if '{' in response:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(response[start:end])
                except json.JSONDecodeError:
                    pass

        logger.error("Failed to parse connection synthesis response")
        return None

    def _validate_connections(self, pin_net_mapping: Dict,
                               components: List[Dict]) -> Dict:
        """
        Validate and fix connection issues.

        This method checks for:
        1. Missing pin assignments
        2. Shorted passives (LAW 4)
        3. Power/ground connections for ICs

        Args:
            pin_net_mapping: The pin to net mapping
            components: List of components

        Returns:
            Validated/fixed pin_net_mapping
        """
        # Build component lookup
        comp_by_ref = {c.get('ref', ''): c for c in components}

        # Check each component
        for comp in components:
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()
            pins = comp.get('pins', [])

            # Check all pins are assigned
            for pin in pins:
                pin_num = pin.get('number', '')
                pin_ref = f"{ref}.{pin_num}"

                if pin_ref not in pin_net_mapping:
                    # Assign based on pin type/name
                    pin_name = pin.get('name', '').upper()
                    pin_type = pin.get('type', '').lower()

                    # Fix H.6: Use config-driven keyword sets instead of
                    # hardcoded lists.  This makes power/ground detection
                    # work for any circuit type (3.3V, 48V, +/-15V, etc.).
                    if pin_name in config.POWER_PIN_KEYWORDS or pin_type == 'power_in':
                        # Auto-detect the actual power rail from existing
                        # nets rather than defaulting to "VCC".
                        power_rail = self._detect_power_rail(pin_net_mapping)
                        pin_net_mapping[pin_ref] = power_rail
                    elif pin_name in config.GROUND_PIN_KEYWORDS or pin_type == 'ground':
                        ground_rail = self._detect_ground_rail(pin_net_mapping)
                        pin_net_mapping[pin_ref] = ground_rail
                    else:
                        # Create unique net for unassigned pins
                        pin_net_mapping[pin_ref] = f"NET_{ref}_{pin_num}"

                    logger.info(f"         Auto-assigned {pin_ref} to {pin_net_mapping[pin_ref]}")

            # Check LAW 4: Two-terminal passives
            if comp_type in ['resistor', 'capacitor', 'inductor', 'diode', 'led', 'fuse']:
                if len(pins) == 2:
                    pin1_ref = f"{ref}.{pins[0].get('number', '1')}"
                    pin2_ref = f"{ref}.{pins[1].get('number', '2')}"

                    net1 = pin_net_mapping.get(pin1_ref, '')
                    net2 = pin_net_mapping.get(pin2_ref, '')

                    if net1 and net2 and net1 == net2:
                        # VIOLATION: Both pins on same net!
                        logger.warning(f"         LAW 4 VIOLATION: {ref} has both pins on {net1}")

                        # Fix: Create unique net for pin 2
                        new_net = f"NET_{ref}"
                        pin_net_mapping[pin2_ref] = new_net
                        logger.info(f"         Fixed: {pin2_ref} moved to {new_net}")

        return pin_net_mapping

    def _ensure_interface_signals(self, pin_net_mapping: Dict,
                                    components: List[Dict],
                                    interface: Dict) -> Dict:
        """
        TC #94: Ensure all interface signals exist in pinNetMapping.

        This method checks that every signal defined in the interface contract
        has at least one pin connected to it. If not, it tries to find an
        appropriate pin to connect.

        Args:
            pin_net_mapping: Current pin to net mapping
            components: List of components
            interface: Interface contract

        Returns:
            Updated pin_net_mapping with interface signals ensured
        """
        # Get all required interface signals
        required_signals = set()

        # Input signals
        for signal_name in interface.get('inputs', {}).keys():
            required_signals.add(signal_name)

        # Output signals
        for signal_name in interface.get('outputs', {}).keys():
            required_signals.add(signal_name)

        # Check which signals are already present
        existing_nets = set(pin_net_mapping.values())
        missing_signals = required_signals - existing_nets

        if missing_signals:
            logger.info(f"         TC #94: Missing interface signals: {missing_signals}")

            # Try to create connections for missing signals
            for signal_name in missing_signals:
                # Look for a component pin that might be related to this signal
                signal_upper = signal_name.upper().replace('_', '')

                # Search for pins with matching names
                for comp in components:
                    ref = comp.get('ref', '')
                    pins = comp.get('pins', [])

                    for pin_info in pins:
                        pin_num = pin_info.get('number', '')
                        pin_name = pin_info.get('name', '').upper().replace('_', '')
                        pin_type = pin_info.get('type', '')
                        pin_ref = f"{ref}.{pin_num}"

                        # Skip if already assigned to something meaningful
                        if pin_ref in pin_net_mapping:
                            current_net = pin_net_mapping[pin_ref]
                            # Only reassign if it's a generic NET_ or NC_ assignment
                            if not current_net.startswith('NET_') and not current_net.startswith('NC_'):
                                continue

                        # Check if pin name matches signal name
                        if signal_upper in pin_name or pin_name in signal_upper:
                            pin_net_mapping[pin_ref] = signal_name
                            logger.info(f"         TC #94: Connected {pin_ref} to interface signal '{signal_name}'")
                            break

                        # Check pin type for sense/control signals
                        if 'sense' in signal_name.lower() and pin_type == 'input':
                            if 'sense' in pin_name.lower() or 'adc' in pin_name.lower():
                                pin_net_mapping[pin_ref] = signal_name
                                logger.info(f"         TC #94: Connected {pin_ref} to interface signal '{signal_name}'")
                                break

                        if 'control' in signal_name.lower() and pin_type == 'output':
                            if 'dac' in pin_name.lower() or 'pwm' in pin_name.lower():
                                pin_net_mapping[pin_ref] = signal_name
                                logger.info(f"         TC #94: Connected {pin_ref} to interface signal '{signal_name}'")
                                break

        return pin_net_mapping

    def _build_connections_from_mapping(self, pin_net_mapping: Dict) -> tuple:
        """
        Build connections array from pinNetMapping.

        Args:
            pin_net_mapping: Pin to net mapping

        Returns:
            Tuple of (connections list, nets list)
        """
        # Group pins by net
        net_to_pins = {}
        for pin, net in pin_net_mapping.items():
            if net not in net_to_pins:
                net_to_pins[net] = []
            net_to_pins[net].append(pin)

        # Build connections array
        connections = []
        for net, pins in net_to_pins.items():
            connections.append({
                'net': net,
                'points': sorted(pins)
            })

        return connections, list(net_to_pins.keys())

    def _remove_phantom_references(self, pin_net_mapping: Dict,
                                    components: List[Dict]) -> Dict:
        """
        Fix G.2: Remove connections that reference non-existent (phantom) components.

        The ConnectionAgent may generate pin references like "DDS_CAP.1" or
        "BRIDGE_OUT.2" for conceptual nodes that were never instantiated as real
        components by the ComponentAgent. These phantom references cause downstream
        validation failures.

        This is GENERIC — works for any circuit type by checking every pin reference
        against the actual component list.

        Args:
            pin_net_mapping: Pin to net mapping (may contain phantom refs)
            components: List of actual components from ComponentAgent

        Returns:
            Cleaned pin_net_mapping with phantom references removed
        """
        # Build set of valid component references
        valid_refs = {c.get('ref', '') for c in components}
        valid_refs.discard('')

        cleaned = {}
        removed_count = 0

        for pin_ref, net in pin_net_mapping.items():
            # Extract component ref from pin ref (e.g., "R1.2" → "R1")
            parts = pin_ref.split('.')
            comp_ref = parts[0] if parts else pin_ref

            if comp_ref in valid_refs:
                cleaned[pin_ref] = net
            else:
                removed_count += 1
                logger.warning(
                    f"[CONNECTION_AGENT] Removed phantom reference: "
                    f"{pin_ref} -> {net} (component '{comp_ref}' does not exist)"
                )

        if removed_count > 0:
            logger.warning(
                f"[CONNECTION_AGENT] Removed {removed_count} phantom component reference(s)"
            )

        return cleaned

    def _fix_pin_reference_nets(self, pin_net_mapping: Dict) -> Dict:
        """
        Fix G.9: Reject and fix net names that are pin references (LAW 5 violation).

        Net names like "U6.2" or "Q1.3" are pin reference identifiers, not signal
        names. These confuse downstream tools and violate LAW 5.

        This method renames them to a safe pattern: "U6.2" → "NET_U6_PIN2".

        Args:
            pin_net_mapping: Pin to net mapping

        Returns:
            Fixed pin_net_mapping with pin-reference nets renamed
        """
        renamed_count = 0
        fixed = {}

        for pin_ref, net in pin_net_mapping.items():
            if net and _PIN_REF_RE.match(net):
                # Convert "U6.2" to "NET_U6_PIN2"
                parts = net.split('.')
                new_net = f"NET_{parts[0]}_PIN{parts[1]}"
                fixed[pin_ref] = new_net
                renamed_count += 1
                logger.warning(
                    f"[CONNECTION_AGENT] LAW 5: Renamed pin-reference net "
                    f"'{net}' → '{new_net}' at {pin_ref}"
                )
            else:
                fixed[pin_ref] = net

        if renamed_count > 0:
            logger.warning(
                f"[CONNECTION_AGENT] Fixed {renamed_count} pin-reference net name(s) (LAW 5)"
            )

        return fixed

    def _warn_dangling_internal_nets(self, pin_net_mapping: Dict,
                                      interface: Dict) -> None:
        """
        Fix G.3: Warn about internal nets with only one connection.

        Every net that is NOT an interface signal and NOT prefixed with NC_ should
        have at least 2 connections. Nets with only 1 connection indicate broken
        signal paths (dangling signals).

        This is a warning-only check — it logs issues for debugging but does not
        modify the mapping (the circuit supervisor handles the actual fixing).

        Args:
            pin_net_mapping: Pin to net mapping
            interface: Interface contract (to identify interface signals)
        """
        # Collect interface signal names (these are expected to be single-ended)
        interface_signals = set()
        for sig in interface.get('inputs', {}).keys():
            interface_signals.add(sig.upper())
        for sig in interface.get('outputs', {}).keys():
            interface_signals.add(sig.upper())
        for rail in interface.get('power_in', []):
            interface_signals.add(rail.upper())
        for rail in interface.get('power_out', []):
            interface_signals.add(rail.upper())

        # Count connections per net
        net_counts = {}
        for pin_ref, net in pin_net_mapping.items():
            net_counts[net] = net_counts.get(net, 0) + 1

        dangling = []
        for net, count in net_counts.items():
            if count != 1:
                continue
            net_upper = net.upper()
            # Skip NC nets
            if net_upper.startswith('NC_') or 'NC' in net_upper:
                continue
            # Skip interface signals
            if net_upper in interface_signals:
                continue
            # Skip power/ground rails (Fix H.6: use config keywords)
            if any(kw in net_upper for kw in config.INTEGRATION_POWER_NET_KEYWORDS):
                continue
            if any(kw in net_upper for kw in config.INTEGRATION_GROUND_NET_KEYWORDS):
                continue
            dangling.append(net)

        if dangling:
            logger.warning(
                f"[CONNECTION_AGENT] {len(dangling)} dangling internal net(s) detected "
                f"(single connection, not interface/NC): {dangling[:10]}"
                + (f" ... and {len(dangling) - 10} more" if len(dangling) > 10 else "")
            )

    @staticmethod
    def _detect_power_rail(pin_net_mapping: Dict) -> str:
        """
        Fix H.6: Auto-detect the primary power rail from existing nets.

        Scans the already-assigned net names for common power rail patterns
        and returns the first match.  Falls back to "VCC" only when no
        power rail is found in the current mapping.

        GENERIC: Works for any voltage level (3.3V, 5V, 12V, 48V, +/-15V, etc.)
        by checking against the config-driven keyword list.

        Args:
            pin_net_mapping: Current pin-to-net mapping.

        Returns:
            The detected power rail net name, or "VCC" as ultimate fallback.
        """
        existing_nets = set(pin_net_mapping.values())
        # Check for exact matches first (most reliable)
        for net in existing_nets:
            net_upper = net.upper()
            for kw in config.INTEGRATION_POWER_NET_KEYWORDS:
                if kw in net_upper:
                    return net
        return "VCC"

    @staticmethod
    def _detect_ground_rail(pin_net_mapping: Dict) -> str:
        """
        Fix H.6: Auto-detect the primary ground rail from existing nets.

        Scans the already-assigned net names for common ground patterns
        and returns the first match.  Falls back to "GND" only when no
        ground rail is found in the current mapping.

        GENERIC: Handles AGND, DGND, PGND, VSS, COM, etc.

        Args:
            pin_net_mapping: Current pin-to-net mapping.

        Returns:
            The detected ground rail net name, or "GND" as ultimate fallback.
        """
        existing_nets = set(pin_net_mapping.values())
        for net in existing_nets:
            net_upper = net.upper()
            for kw in config.INTEGRATION_GROUND_NET_KEYWORDS:
                if kw in net_upper:
                    return net
        return "GND"

    def _create_basic_connections(self, components: List[Dict],
                                   interface: Dict) -> Dict:
        """
        Create basic connections as fallback.

        This is used when AI fails to create connections.
        It creates minimal valid connections.

        Args:
            components: List of components
            interface: Interface contract

        Returns:
            Basic connections dict
        """
        logger.warning("         Creating basic fallback connections")

        pin_net_mapping = {}
        net_counter = 1

        for comp in components:
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()
            pins = comp.get('pins', [])

            if not pins:
                continue

            # For passives, connect pin 1 to VCC, pin 2 to GND
            if comp_type in ['resistor', 'capacitor', 'inductor']:
                if len(pins) >= 2:
                    pin_net_mapping[f"{ref}.{pins[0].get('number', '1')}"] = 'VCC'
                    pin_net_mapping[f"{ref}.{pins[1].get('number', '2')}"] = 'GND'

            # For ICs, connect power pins
            # Fix H.6: Use config-driven keyword sets.
            elif comp_type == 'ic':
                for pin in pins:
                    pin_num = pin.get('number', '')
                    pin_name = pin.get('name', '').upper()
                    pin_ref = f"{ref}.{pin_num}"

                    if pin_name in config.POWER_PIN_KEYWORDS:
                        pin_net_mapping[pin_ref] = 'VCC'
                    elif pin_name in config.GROUND_PIN_KEYWORDS:
                        pin_net_mapping[pin_ref] = 'GND'
                    else:
                        pin_net_mapping[pin_ref] = f"NET{net_counter}"
                        net_counter += 1

            # Default: assign sequential nets
            else:
                for pin in pins:
                    pin_num = pin.get('number', '')
                    pin_ref = f"{ref}.{pin_num}"
                    pin_net_mapping[pin_ref] = f"NET{net_counter}"
                    net_counter += 1

        connections, nets = self._build_connections_from_mapping(pin_net_mapping)

        return {
            'success': True,
            'connections': connections,
            'pinNetMapping': pin_net_mapping,
            'nets': nets
        }
