# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Component Agent - Component selection for circuit modules.

The Component Agent is responsible for selecting appropriate components
for a circuit module. It ONLY handles component selection - it does NOT
create connections (that's the Connection Agent's job).

This separation allows:
1. Focused prompts with less context
2. Faster API responses
3. Better component selection without wiring concerns
4. Easier debugging of selection vs. connection issues

Author: CopperPilot Team
Date: January 2026
Version: 1.0

Key Design Principles:
- FOCUSED: Only selects components, no connections
- RATING-AWARE: Ensures proper voltage/current derating
- PIN-COMPLETE: Always includes pin definitions
- GENERIC: Works for ANY component type
"""

import json
import re
from typing import Dict, List, Any, Optional
from pathlib import Path

from utils.logger import setup_logger
from server.config import config

logger = setup_logger(__name__)


class ComponentAgent:
    """
    Component selection agent for circuit modules.

    The Component Agent analyzes module requirements and selects
    appropriate components with correct values, ratings, and packages.

    This agent is FOCUSED on component selection only. It:
    - Analyzes module function and requirements
    - Selects components with appropriate values
    - Ensures voltage/current derating
    - Provides complete pin definitions for each component

    It does NOT:
    - Create connections between components
    - Assign nets to pins
    - Handle circuit topology

    Attributes:
        ai_manager: Reference to the AI Agent Manager
    """

    def __init__(self, ai_manager):
        """
        Initialize the Component Agent.

        Args:
            ai_manager: The AI Agent Manager instance
        """
        self.ai_manager = ai_manager

    async def select_components(self, module_spec: Dict,
                                 interface: Dict) -> Dict:
        """
        Select components for a circuit module.

        This method calls the AI to select appropriate components
        based on the module requirements and interface contract.

        Args:
            module_spec: Module specification containing:
                - name: Module name
                - function: Module function/purpose
                - requirements: Electrical requirements
                - specifications: Detailed specifications

            interface: Interface contract containing:
                - power_in: Power rails consumed
                - power_out: Power rails provided
                - signals_in: Input signals
                - signals_out: Output signals

        Returns:
            Dict containing:
                - success: Whether selection succeeded
                - components: List of component dicts with pins
                - designNotes: Design rationale
        """
        module_name = module_spec.get('name', 'Unknown')
        logger.info(f"         ComponentAgent: Selecting components for {module_name}")

        # DEBUG: Log input details
        logger.debug(f"[COMPONENT_AGENT] {module_name} - Function: {module_spec.get('function', 'N/A')}")
        logger.debug(f"[COMPONENT_AGENT] {module_name} - Specifications: {module_spec.get('specifications', {})}")
        logger.debug(f"[COMPONENT_AGENT] {module_name} - Power requirements: power_in={interface.get('power_in', [])}, power_out={interface.get('power_out', [])}")

        try:
            # Build the prompt
            prompt = self._build_component_prompt(module_spec, interface)

            # Get rating guidelines
            rating_guidelines = self._get_rating_guidelines(module_spec)

            # Make AI call
            result = await self.ai_manager.call_ai(
                "component_agent",
                prompt,
                context={
                    "module": module_spec,
                    "interface": interface,
                    "rating_guidelines": rating_guidelines
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

            if not parsed or 'components' not in parsed:
                logger.error(f"         Failed to parse component response for {module_name}")
                return {
                    'success': False,
                    'error': 'Failed to parse AI response'
                }

            components = parsed['components']

            # CRITICAL: Ensure all components have pins
            components = self._ensure_pins(components)

            logger.info(f"         Selected {len(components)} components for {module_name}")

            return {
                'success': True,
                'components': components,
                'designNotes': parsed.get('designNotes', [])
            }

        except Exception as e:
            logger.error(f"Component selection failed for {module_name}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def _build_component_prompt(self, module_spec: Dict, interface: Dict) -> str:
        """
        Build the component selection prompt.

        Args:
            module_spec: Module specification
            interface: Interface contract

        Returns:
            Formatted prompt string
        """
        # Load prompt template
        prompt_file = Path("ai_agents/prompts/multi_agent/component_selection_prompt.txt")

        if prompt_file.exists():
            prompt = prompt_file.read_text()
        else:
            # Use inline prompt if file doesn't exist
            prompt = self._get_default_prompt()

        # Replace template variables
        prompt = prompt.replace('{{ module_name }}', module_spec.get('name', 'Unknown'))
        # Fix 1.3: Use `or` to treat '' as falsy so description cascades through.
        # .get('function', fallback) returns '' when key exists as empty string.
        prompt = prompt.replace(
            '{{ module_function }}',
            module_spec.get('function') or module_spec.get('description', '')
        )
        prompt = prompt.replace(
            '{{ module_requirements }}',
            json.dumps(module_spec.get('requirements') or module_spec.get('specifications', {}), indent=2)
        )
        prompt = prompt.replace('{{ module_specifications }}', json.dumps(module_spec.get('specifications', {}), indent=2))
        prompt = prompt.replace('{{ interface_inputs }}', json.dumps(interface.get('inputs', {}), indent=2))
        prompt = prompt.replace('{{ interface_outputs }}', json.dumps(interface.get('outputs', {}), indent=2))
        prompt = prompt.replace('{{ power_in }}', json.dumps(interface.get('power_in', []), indent=2))
        prompt = prompt.replace('{{ power_out }}', json.dumps(interface.get('power_out', []), indent=2))

        # Add rating guidelines
        rating_guidelines = self._get_rating_guidelines(module_spec)
        prompt = prompt.replace('{{ rating_guidelines }}', rating_guidelines)

        return prompt

    def _get_default_prompt(self) -> str:
        """
        Get default component selection prompt.

        Returns:
            Default prompt string
        """
        return """You are a Component Selection Agent.

## Your Task
Select all necessary components for the following circuit module.

## Module Information
**Name**: {{ module_name }}
**Function**: {{ module_function }}

**Requirements**:
{{ module_requirements }}

**Specifications**:
{{ module_specifications }}

## Interface Contract
This module must provide/consume these interfaces:

**Power Inputs**: {{ power_in }}
**Power Outputs**: {{ power_out }}
**Signal Inputs**: {{ interface_inputs }}
**Signal Outputs**: {{ interface_outputs }}

## Component Rating Guidelines
{{ rating_guidelines }}

## Output Format
Return a JSON object with this EXACT structure:

```json
{
  "components": [
    {
      "ref": "U1",
      "type": "ic",
      "value": "LM7805",
      "package": "TO-220",
      "description": "5V voltage regulator",
      "pins": [
        {"number": "1", "name": "VIN", "type": "power_in"},
        {"number": "2", "name": "GND", "type": "ground"},
        {"number": "3", "name": "VOUT", "type": "power_out"}
      ]
    },
    {
      "ref": "C1",
      "type": "capacitor",
      "value": "100nF",
      "package": "0603",
      "description": "Input bypass capacitor",
      "pins": [
        {"number": "1", "name": "1", "type": "passive"},
        {"number": "2", "name": "2", "type": "passive"}
      ]
    }
  ],
  "designNotes": [
    "Selected LM7805 for 5V regulation",
    "Added bypass capacitors for stability"
  ]
}
```

## CRITICAL RULES
1. EVERY component MUST have a complete `pins` array
2. Pin numbers must be strings ("1", not 1)
3. Use standard reference designators (R1, C1, U1, etc.)
4. Include appropriate bypass/decoupling capacitors
5. Use proper voltage/current derating (see guidelines)
6. Include ALL components needed for the module to function

## Do NOT include:
- Connections or wiring (handled by Connection Agent)
- Net assignments
- pinNetMapping

Return ONLY the JSON object, no additional text."""

    def _get_rating_guidelines(self, module_spec: Dict) -> str:
        """
        Generate component rating guidelines based on module requirements.

        This is CRITICAL for proper voltage/current derating.

        Args:
            module_spec: Module specification

        Returns:
            Rating guidelines string
        """
        guidelines = []

        # Extract voltage/current requirements
        requirements = module_spec.get('requirements', {})
        specs = module_spec.get('specifications', {})

        # Combine all spec text for analysis
        spec_text = json.dumps({**requirements, **specs}).upper()

        # Voltage derating
        guidelines.append("### Voltage Derating Rules")
        guidelines.append("- MOSFET Vds: Select for ≥2x operating voltage")
        guidelines.append("- Capacitor voltage: Select for ≥1.5x operating voltage")
        guidelines.append("- Diode reverse voltage: Select for ≥2x peak reverse voltage")

        # Current derating
        guidelines.append("\n### Current Derating Rules")
        guidelines.append("- Resistor power: Select for ≥2x expected power dissipation")
        guidelines.append("- Capacitor ripple current: Select for ≥1.5x expected ripple")
        guidelines.append("- Inductor saturation: Select for ≥1.5x peak current")

        # Extract specific values if present
        voltage_match = re.search(r'(\d+)\s*V', spec_text)
        if voltage_match:
            voltage = int(voltage_match.group(1))
            guidelines.append(f"\n### Module-Specific (detected {voltage}V)")
            guidelines.append(f"- Select MOSFETs with Vds ≥ {voltage * 2}V")
            guidelines.append(f"- Select capacitors rated ≥ {int(voltage * 1.5)}V")

        power_match = re.search(r'(\d+)\s*W', spec_text)
        if power_match:
            power = int(power_match.group(1))
            guidelines.append(f"- Design for {power}W power handling")

        return '\n'.join(guidelines)

    def _parse_response(self, response: str) -> Optional[Dict]:
        """
        Parse AI response to extract components.

        Args:
            response: Raw AI response text

        Returns:
            Parsed dict with components, or None if parsing failed
        """
        # TC #94: Detect truncation - if response doesn't end with proper JSON
        # closure, it's likely truncated due to max_tokens
        if response and not response.rstrip().endswith(('}', '```')):
            logger.warning("Response appears TRUNCATED (doesn't end with } or ```)")
            logger.warning(f"Last 50 chars: ...{response[-50:]}")

        # Try to extract JSON from markdown code block
        json_match = re.search(r'```json\s*\n?([\s\S]*?)\n?```', response)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error in code block: {e}")
                # TC #94: Try to repair truncated JSON
                repaired = self._repair_truncated_json(json_match.group(1).strip())
                if repaired:
                    return repaired

        # Try direct JSON parse
        if '{' in response:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(response[start:end])
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parse error in direct parse: {e}")
                    # TC #94: Try to repair truncated JSON
                    repaired = self._repair_truncated_json(response[start:end])
                    if repaired:
                        return repaired

        logger.error("Failed to parse component selection response - likely TRUNCATED")
        logger.error("Consider increasing max_tokens in config.py")
        return None

    def _repair_truncated_json(self, json_str: str) -> Optional[Dict]:
        """
        Attempt to repair truncated JSON by closing open brackets/braces.

        TC #94: When AI response is truncated due to max_tokens, the JSON
        may be incomplete. This attempts basic repair by closing structures.

        Args:
            json_str: Potentially truncated JSON string

        Returns:
            Parsed dict if repair successful, None otherwise
        """
        # Count open brackets and braces
        open_braces = json_str.count('{') - json_str.count('}')
        open_brackets = json_str.count('[') - json_str.count(']')

        if open_braces > 0 or open_brackets > 0:
            logger.warning(f"Attempting JSON repair: {open_braces} unclosed braces, {open_brackets} unclosed brackets")

            # Find last complete component by looking for last complete object
            # Look for pattern: }, { or }, ] which indicates end of a component
            last_complete = -1
            for match in re.finditer(r'\},?\s*(?=[\]\{]|$)', json_str):
                last_complete = match.end()

            if last_complete > 0:
                # Truncate to last complete component and close the structure
                repaired = json_str[:last_complete]
                repaired += ']' * open_brackets + '}' * open_braces

                try:
                    result = json.loads(repaired)
                    components_count = len(result.get('components', []))
                    logger.warning(f"JSON repair successful! Recovered {components_count} components")
                    return result
                except json.JSONDecodeError:
                    logger.warning("JSON repair failed")

        return None

    def _ensure_pins(self, components: List[Dict]) -> List[Dict]:
        """
        Ensure all components have pins defined.

        This is CRITICAL - components without pins cause downstream failures.

        Args:
            components: List of component dicts

        Returns:
            Components with pins guaranteed
        """
        for comp in components:
            if 'pins' not in comp or not comp['pins']:
                comp['pins'] = self._generate_default_pins(comp)
                logger.info(f"         Generated pins for {comp.get('ref', 'unknown')}")

        return components

    def _generate_default_pins(self, component: Dict) -> List[Dict]:
        """
        Generate default pins for a component based on its type.

        This is a GENERIC method that works for any component type.

        Args:
            component: Component dict

        Returns:
            List of pin dicts
        """
        comp_type = component.get('type', '').lower()
        package = component.get('package', '').upper()
        value = component.get('value', '').upper()

        # 2-pin passives
        if comp_type in ['resistor', 'capacitor', 'inductor', 'diode', 'led', 'fuse']:
            return [
                {'number': '1', 'name': '1', 'type': 'passive'},
                {'number': '2', 'name': '2', 'type': 'passive'}
            ]

        # 3-pin semiconductors
        if comp_type in ['transistor', 'mosfet', 'regulator', 'ldo']:
            if comp_type == 'mosfet':
                return [
                    {'number': '1', 'name': 'G', 'type': 'input'},
                    {'number': '2', 'name': 'D', 'type': 'passive'},
                    {'number': '3', 'name': 'S', 'type': 'passive'}
                ]
            elif comp_type in ['regulator', 'ldo']:
                return [
                    {'number': '1', 'name': 'VIN', 'type': 'power_in'},
                    {'number': '2', 'name': 'GND', 'type': 'ground'},
                    {'number': '3', 'name': 'VOUT', 'type': 'power_out'}
                ]
            else:
                return [
                    {'number': '1', 'name': 'B', 'type': 'input'},
                    {'number': '2', 'name': 'C', 'type': 'passive'},
                    {'number': '3', 'name': 'E', 'type': 'passive'}
                ]

        # 4-pin components
        if comp_type in ['bridge_rectifier', 'optocoupler']:
            return [
                {'number': '1', 'name': '1', 'type': 'passive'},
                {'number': '2', 'name': '2', 'type': 'passive'},
                {'number': '3', 'name': '3', 'type': 'passive'},
                {'number': '4', 'name': '4', 'type': 'passive'}
            ]

        # ICs - determine from package
        if comp_type == 'ic' or 'SOT' in package or 'SOIC' in package or 'DIP' in package:
            if 'SOT-23' in package:
                pin_count = 3
            elif 'SOIC-8' in package or 'DIP-8' in package:
                pin_count = 8
            elif 'SOIC-14' in package or 'DIP-14' in package:
                pin_count = 14
            elif 'SOIC-16' in package or 'DIP-16' in package:
                pin_count = 16
            else:
                pin_count = 8  # Default

            return [
                {'number': str(i), 'name': str(i), 'type': 'passive'}
                for i in range(1, pin_count + 1)
            ]

        # Connectors
        if comp_type == 'connector':
            # Try to extract pin count from value
            num_match = re.search(r'(\d+)', value)
            pin_count = int(num_match.group(1)) if num_match else 2
            return [
                {'number': str(i), 'name': str(i), 'type': 'passive'}
                for i in range(1, pin_count + 1)
            ]

        # Default: 2 pins
        return [
            {'number': '1', 'name': '1', 'type': 'passive'},
            {'number': '2', 'name': '2', 'type': 'passive'}
        ]
