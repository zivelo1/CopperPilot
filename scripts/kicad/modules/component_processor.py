# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Component processor module for mapping components to KiCad symbols and footprints."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import logging
import re

from ..utils.base import PipelineStage, ConversionContext, ValidationError, load_json

logger = logging.getLogger(__name__)

class ComponentProcessor(PipelineStage):
    """Map components to KiCad symbols and footprints."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        # Load component database
        db_path = Path(__file__).parent.parent / 'data' / 'component_db.json'
        self.component_db = load_json(db_path)

        # Load pin mappings
        pin_path = Path(__file__).parent.parent / 'data' / 'pin_mappings.json'
        self.pin_mappings = load_json(pin_path)

    def process(self, context: ConversionContext) -> ConversionContext:
        """Process components and map to KiCad symbols."""
        try:
            components = context.input_data.get('components', {})
            pin_net_mapping = context.input_data.get('pinNetMapping', {})
            if not components:
                raise ValidationError("No components found to process")

            processed_components = {}

            for ref_des, comp_data in components.items():
                try:
                    # Extract pins for this component from circuit-level mapping
                    comp_pins = {}
                    for pin_ref, net in pin_net_mapping.items():
                        if pin_ref.startswith(f"{ref_des}."):
                            pin_num = pin_ref.split('.', 1)[1]
                            comp_pins[pin_num] = net

                    processed = self._process_component(ref_des, comp_data, comp_pins)
                    processed_components[ref_des] = processed
                except Exception as e:
                    logger.warning(f"Error processing {ref_des}: {e}")
                    # Use fallback processing
                    processed = self._fallback_component(ref_des, comp_data)
                    processed_components[ref_des] = processed

            context.components = processed_components

            # Generate symbol library
            context.symbols = self._generate_symbol_library(processed_components)

            # Generate footprint library
            context.footprints = self._generate_footprint_library(processed_components)

            # Statistics
            context.statistics['components'] = {
                'total': len(processed_components),
                'mapped': sum(1 for c in processed_components.values() if c.get('symbol')),
                'unmapped': sum(1 for c in processed_components.values() if not c.get('symbol'))
            }

            logger.info(f"Processed {len(processed_components)} components")
            return context

        except Exception as e:
            return self.handle_error(e, context)

    def _process_component(self, ref_des: str, comp_data: Dict[str, Any], comp_pins: Dict[str, str] = None) -> Dict[str, Any]:
        """Process a single component."""
        comp_type = comp_data.get('type', 'generic')
        value = comp_data.get('value', '')
        package = comp_data.get('package', '')

        if comp_pins is None:
            comp_pins = {}

        # Get mapping from database
        if comp_type in self.component_db:
            db_entry = self.component_db[comp_type]
            symbol = db_entry['symbol']
            prefix = db_entry['prefix']
            pins = db_entry['pins']
            footprint = self._select_footprint(db_entry, package, value)
        else:
            # Try to find closest match
            symbol, prefix, pins, footprint = self._find_best_match(comp_type, package, value)

        # Build processed component
        processed = {
            'refDes': ref_des,
            'type': comp_type,
            'value': value,
            'symbol': symbol,
            'footprint': footprint,
            'prefix': prefix,
            'pins': self._get_pin_list(ref_des, comp_data, pins, comp_pins),
            'pinNetMapping': comp_pins,  # Use circuit-level pins
            'specs': comp_data.get('specs', {}),
            'package': package,
            'uuid': self._generate_component_uuid(ref_des)
        }

        # Add special handling for ICs with known pinouts
        if comp_type in ['ic', 'opamp', 'regulator']:
            processed = self._enhance_ic_data(processed, comp_data)

        return processed

    def _select_footprint(self, db_entry: Dict[str, Any], package: str, value: str) -> str:
        """Select appropriate footprint based on package or value."""
        footprints = db_entry.get('footprints', {})

        # Try exact package match
        if package:
            package_upper = package.upper()
            for key, footprint in footprints.items():
                if key.upper() in package_upper or package_upper in key.upper():
                    return footprint

        # Try to infer from value
        if value:
            # Check for SMD size hints in value
            for size in ['0402', '0603', '0805', '1206']:
                if size in value:
                    if size in footprints:
                        return footprints[size]

        # Default to THT or first available
        if 'THT' in footprints:
            return footprints['THT']
        elif footprints:
            return list(footprints.values())[0]

        return "Package_DIP:DIP-8_W7.62mm"  # Default fallback

    def _find_best_match(self, comp_type: str, package: str, value: str) -> Tuple[str, str, int, str]:
        """Find best match for unknown component type."""
        # Check if it's a variant of known type
        type_lower = comp_type.lower()

        # Check for IC types
        if 'ic' in type_lower or 'chip' in type_lower:
            pins = self._estimate_pin_count(package)
            return f"Package_DIP:DIP-{pins}_W7.62mm", 'U', pins, f"Package_DIP:DIP-{pins}_W7.62mm"

        # Check for connector types
        if 'conn' in type_lower or 'header' in type_lower or 'plug' in type_lower:
            pins = self._estimate_pin_count(package)
            return f"Connector_Generic:Conn_01x{pins:02d}", 'J', pins, f"Connector_PinHeader_2.54mm:PinHeader_1x{pins:02d}_P2.54mm_Vertical"

        # Default generic component
        return "Device:R", 'U', 2, "Package_DIP:DIP-8_W7.62mm"

    def _estimate_pin_count(self, package: str) -> int:
        """Estimate pin count from package string."""
        if not package:
            return 8  # Default

        # Look for numbers in package name
        numbers = re.findall(r'\d+', package)
        if numbers:
            # Return the largest reasonable number
            for num in sorted(map(int, numbers), reverse=True):
                if 2 <= num <= 100:  # Reasonable pin count range
                    return num

        # Check common package names
        package_upper = package.upper()
        if 'DIL' in package_upper or 'DIP' in package_upper:
            # DIL08, DIP14, etc.
            match = re.search(r'(?:DIL|DIP)(\d+)', package_upper)
            if match:
                return int(match.group(1))

        return 8  # Default

    def _get_pin_list(self, ref_des: str, comp_data: Dict[str, Any], default_pins: int, comp_pins: Dict[str, str] = None) -> List[str]:
        """Get list of pins for component."""
        # Use circuit-level pins if provided
        if comp_pins:
            return list(comp_pins.keys())

        # Check if we have known pinout
        specs = comp_data.get('specs', {})
        suggested_part = specs.get('suggestedPart', '')

        for part_name, pinout in self.pin_mappings.items():
            if part_name in suggested_part:
                return list(pinout.keys())

        # Generate default pin list
        return [str(i+1) for i in range(default_pins)]

    def _enhance_ic_data(self, processed: Dict[str, Any], comp_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance IC data with specific pin mappings."""
        specs = comp_data.get('specs', {})
        suggested_part = specs.get('suggestedPart', '')

        # Check for known IC types
        for part_name, pinout in self.pin_mappings.items():
            if part_name in suggested_part or part_name in processed['value']:
                processed['pinout'] = pinout
                processed['pins'] = list(pinout.keys())
                # Update symbol if we have a better match
                if 'LM358' in part_name or 'LM741' in part_name:
                    processed['symbol'] = 'Amplifier_Operational:' + part_name
                elif '555' in part_name:
                    processed['symbol'] = 'Timer:NE555P'
                elif '7805' in part_name:
                    processed['symbol'] = 'Regulator_Linear:LM7805_TO220'
                break

        return processed

    def _fallback_component(self, ref_des: str, comp_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback processing for components that fail normal processing."""
        logger.warning(f"Using fallback for {ref_des}")

        # Determine basic type from refDes prefix
        prefix = ''.join(filter(str.isalpha, ref_des))

        symbol_map = {
            'R': ('Device:R', 2),
            'C': ('Device:C', 2),
            'L': ('Device:L', 2),
            'D': ('Device:D', 2),
            'Q': ('Device:Q_NPN_BCE', 3),
            'U': ('Package_DIP:DIP-8_W7.62mm', 8),
            'J': ('Connector_Generic:Conn_01x04', 4),
            'F': ('Device:Fuse', 2),
            'T': ('Device:Transformer_1P_1S', 4)
        }

        symbol, pins = symbol_map.get(prefix, ('Device:R', 2))

        return {
            'refDes': ref_des,
            'type': comp_data.get('type', 'generic'),
            'value': comp_data.get('value', ''),
            'symbol': symbol,
            'footprint': 'Package_DIP:DIP-8_W7.62mm' if pins > 2 else 'Resistor_SMD:R_0805_2012Metric',
            'prefix': prefix,
            'pins': [str(i+1) for i in range(pins)],
            'pinNetMapping': comp_data.get('pinNetMapping', {}),
            'specs': comp_data.get('specs', {}),
            'package': comp_data.get('package', ''),
            'uuid': self._generate_component_uuid(ref_des)
        }

    def _generate_component_uuid(self, ref_des: str) -> str:
        """Generate unique UUID for component."""
        import uuid
        # Use deterministic UUID based on refDes for consistency
        namespace = uuid.NAMESPACE_DNS
        return str(uuid.uuid5(namespace, f"kicad.component.{ref_des}"))

    def _generate_symbol_library(self, components: Dict[str, Any]) -> Dict[str, Any]:
        """Generate symbol library data."""
        symbols = {}
        for ref_des, comp in components.items():
            symbol = comp.get('symbol', '')
            if symbol and symbol not in symbols:
                symbols[symbol] = {
                    'lib': symbol.split(':')[0] if ':' in symbol else 'Device',
                    'name': symbol.split(':')[1] if ':' in symbol else symbol,
                    'instances': []
                }
            if symbol:
                symbols[symbol]['instances'].append(ref_des)

        return symbols

    def _generate_footprint_library(self, components: Dict[str, Any]) -> Dict[str, Any]:
        """Generate footprint library data."""
        footprints = {}
        for ref_des, comp in components.items():
            footprint = comp.get('footprint', '')
            if footprint and footprint not in footprints:
                footprints[footprint] = {
                    'lib': footprint.split(':')[0] if ':' in footprint else 'Package_DIP',
                    'name': footprint.split(':')[1] if ':' in footprint else footprint,
                    'instances': []
                }
            if footprint:
                footprints[footprint]['instances'].append(ref_des)

        return footprints