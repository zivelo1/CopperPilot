#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Footprint Mapper - GENERIC Component to Footprint Mapping
================================================================

This module provides GENERIC, DYNAMIC footprint inference for ANY component type.
Works with simple lowlevel format (type + pin count) and assigns appropriate
KiCad footprint library references.

DESIGN PRINCIPLES:
- GENERIC: Works for ANY circuit, not specific to any example
- MODULAR: Easy to extend with new component types
- DYNAMIC: Automatically handles varying pin counts
- FALLBACK: Provides reasonable defaults for unknown components

Author: Electronics Automation System
Date: 2025-11-16
Version: 1.1.0 + TC #76 Potentiometer Support (2025-12-09)

TC #76 FIX (2025-12-09): Potentiometer Footprint Support
========================================================
- Added explicit mappings for potentiometer, pot, trimmer, variable_resistor
- Added potentiometer detection in _infer_by_category()
- Prevents DRC clearance violations from using wrong footprints
"""

import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)


class KiCadFootprintMapper:
    """
    GENERIC mapper from component type + pin count to KiCad footprint.

    Handles all common component types with intelligent fallbacks.
    Designed to work with ANY circuit, from 2 to 200+ components.
    """

    def __init__(self):
        """Initialize the footprint mapper with GENERIC mappings."""
        # GENERIC footprint mapping: (component_type, pin_count) -> KiCad footprint
        self.footprint_map: Dict[Tuple[str, int], str] = {
            # ===== RESISTORS (2-pin passive) =====
            ('resistor', 2): 'Resistor_SMD:R_0805_2012Metric',
            ('res', 2): 'Resistor_SMD:R_0805_2012Metric',
            ('r', 2): 'Resistor_SMD:R_0805_2012Metric',

            # ===== CAPACITORS (2-pin passive) =====
            ('capacitor', 2): 'Capacitor_SMD:C_0805_2012Metric',
            ('cap', 2): 'Capacitor_SMD:C_0805_2012Metric',
            ('c', 2): 'Capacitor_SMD:C_0805_2012Metric',

            # ===== INDUCTORS (2-pin passive) =====
            ('inductor', 2): 'Inductor_SMD:L_0805_2012Metric',
            ('ind', 2): 'Inductor_SMD:L_0805_2012Metric',
            ('l', 2): 'Inductor_SMD:L_0805_2012Metric',

            # ===== DIODES (2-pin) =====
            ('diode', 2): 'Diode_SMD:D_SOD-323',
            ('d', 2): 'Diode_SMD:D_SOD-323',

            # ===== LEDS (2-pin) =====
            ('led', 2): 'LED_SMD:LED_0805_2012Metric',

            # ===== TRANSISTORS =====
            ('transistor', 3): 'Package_TO_SOT_SMD:SOT-23',
            ('bjt', 3): 'Package_TO_SOT_SMD:SOT-23',
            ('mosfet', 3): 'Package_TO_SOT_SMD:SOT-23',
            ('fet', 3): 'Package_TO_SOT_SMD:SOT-23',

            # ===== SMALL ICs (4-8 pins) =====
            ('ic', 4): 'Package_SO:SOIC-4_4.4x2.6mm_P1.27mm',
            ('ic', 5): 'Package_TO_SOT_SMD:SOT-23-5',
            ('ic', 6): 'Package_TO_SOT_SMD:SOT-23-6',
            ('ic', 8): 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',

            # ===== MEDIUM ICs (10-20 pins) =====
            ('ic', 10): 'Package_SO:MSOP-10_3x3mm_P0.5mm',
            ('ic', 14): 'Package_SO:SOIC-14_3.9x8.7mm_P1.27mm',
            ('ic', 16): 'Package_SO:SOIC-16_3.9x9.9mm_P1.27mm',
            ('ic', 20): 'Package_SO:SOIC-20_7.5x12.8mm_P1.27mm',

            # ===== LARGER ICs (24-48 pins) =====
            ('ic', 24): 'Package_SO:SOIC-24_7.5x15.4mm_P1.27mm',
            ('ic', 28): 'Package_SO:SOIC-28_7.5x17.9mm_P1.27mm',
            ('ic', 32): 'Package_QFP:LQFP-32_7x7mm_P0.8mm',
            ('ic', 44): 'Package_QFP:LQFP-44_10x10mm_P0.8mm',
            ('ic', 48): 'Package_QFP:LQFP-48_7x7mm_P0.5mm',

            # ===== LARGE ICs (50-100 pins) =====
            ('ic', 64): 'Package_QFP:LQFP-64_10x10mm_P0.5mm',
            ('ic', 80): 'Package_QFP:LQFP-80_12x12mm_P0.5mm',
            ('ic', 100): 'Package_QFP:LQFP-100_14x14mm_P0.5mm',

            # ===== VERY LARGE ICs (100+ pins) =====
            ('ic', 144): 'Package_QFP:LQFP-144_20x20mm_P0.5mm',
            ('ic', 176): 'Package_BGA:BGA-176_15x15mm_12x12_Layout_1.0mm_Ball0.5mm_Pad0.4mm',
            ('ic', 256): 'Package_BGA:BGA-256_17x17mm_Layout16x16_P1.0mm',

            # ===== CONNECTORS (variable pins) =====
            ('connector', 2): 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical',
            ('connector', 3): 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
            ('connector', 4): 'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical',
            ('connector', 5): 'Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical',
            ('connector', 6): 'Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical',
            ('connector', 8): 'Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical',
            ('connector', 10): 'Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical',

            # ===== CRYSTAL/OSCILLATORS =====
            ('crystal', 2): 'Crystal:Crystal_SMD_HC49-SD',
            ('xtal', 2): 'Crystal:Crystal_SMD_HC49-SD',
            ('oscillator', 4): 'Oscillator:Oscillator_SMD_TCXO_G158',

            # ===== SWITCHES =====
            ('switch', 2): 'Button_Switch_SMD:SW_SPST_TL3342',
            ('button', 2): 'Button_Switch_SMD:SW_Push_SPST_NO_Alps_SKRK',

            # ===== POTENTIOMETERS (TC #76 - 2025-12-09) =====
            # CRITICAL: Potentiometers need proper 3-pin footprints with adequate pad spacing.
            # Trimmer pots typically have 3 pins in a row or triangular arrangement.
            # Standard SMD resistor footprints are INVALID for pots (only 2 pads).
            ('potentiometer', 3): 'Potentiometer_SMD:Potentiometer_Bourns_3314J_Vertical',
            ('pot', 3): 'Potentiometer_SMD:Potentiometer_Bourns_3314J_Vertical',
            ('trimmer', 3): 'Potentiometer_SMD:Potentiometer_Bourns_3314J_Vertical',
            ('variable_resistor', 3): 'Potentiometer_SMD:Potentiometer_Bourns_3314J_Vertical',

            # ===== FUSES (TC #37 - 2025-11-23) =====
            # CRITICAL: Fuses are 2-pin passive components, NOT ICs!
            ('fuse', 2): 'Fuse:Fuse_1206_3216Metric',
            ('f', 2): 'Fuse:Fuse_1206_3216Metric',

            # ===== TRANSFORMERS (TC #37 - 2025-11-23) =====
            ('transformer', 4): 'Transformer_THT:Transformer_37x44',
            ('trans', 4): 'Transformer_THT:Transformer_37x44',  # Avoid conflict with transistor

            # ===== RELAYS (TC #37 - 2025-11-23) =====
            ('relay', 5): 'Relay_THT:Relay_SPDT_HJR-3FF',
            ('relay', 8): 'Relay_SMD:Relay_DPDT_Omron_G6K-2F',

            # ===== VOLTAGE REGULATORS (TC #37 - 2025-11-23) =====
            # Linear regulators: typically 3-pin (IN, GND, OUT)
            ('vreg', 3): 'Package_TO_SOT_SMD:SOT-223-3_TabPin2',
            ('ldo', 3): 'Package_TO_SOT_SMD:SOT-223-3_TabPin2',
            ('reg', 3): 'Package_TO_SOT_SMD:SOT-223-3_TabPin2',
        }

        # Component type aliases for flexibility
        self.type_aliases = {
            'resistance': 'resistor',
            'capacitance': 'capacitor',
            'inductance': 'inductor',
            'integrated_circuit': 'ic',
            'microcontroller': 'ic',
            'mcu': 'ic',
            'processor': 'ic',
            'cpu': 'ic',
            'opamp': 'ic',
            'amplifier': 'ic',
            'regulator': 'ic',
            'driver': 'ic',
            'buffer': 'ic',
            'logic': 'ic',
            'memory': 'ic',
            'transceiver': 'ic',
        }

    def validate_component(self, component_type: str, pin_count: int) -> Tuple[bool, str]:
        """
        Validate component type vs pin count for impossible combinations.

        TC #37 (2025-11-23): Added to prevent errors like "fuse with 8 pins".

        Args:
            component_type: Component type
            pin_count: Number of pins

        Returns:
            Tuple of (is_valid, warning_message)
        """
        comp_type_lower = component_type.lower().strip()

        # CRITICAL: 2-pin components that should NEVER have other pin counts
        two_pin_only = ['fuse', 'resistor', 'capacitor', 'inductor', 'led', 'diode']
        for keyword in two_pin_only:
            if keyword in comp_type_lower:
                if pin_count != 2:
                    msg = f"INVALID: {component_type} should have 2 pins, but has {pin_count}. Data corruption?"
                    logger.error(msg)
                    return (False, msg)

        # 3-pin components (transistors, regulators)
        three_pin_only = ['bjt', 'mosfet', 'fet', 'transistor', 'vreg', 'ldo']
        for keyword in three_pin_only:
            if comp_type_lower == keyword:  # Exact match to avoid false positives
                if pin_count not in [3, 4]:  # 4 pins ok for some packages (with tab/gnd)
                    msg = f"UNUSUAL: {component_type} typically has 3-4 pins, but has {pin_count}"
                    logger.warning(msg)
                    return (True, msg)  # Warning, not error

        return (True, "")  # Valid

    def get_footprint_smart(self, component_type: str, pin_count: int,
                           value: str = "", power_rating: str = "") -> str:
        """
        Get KiCad footprint with SMART selection based on component VALUE.

        TC #37 (2025-11-23): Enhanced to consider voltage, capacitance, power ratings.

        Args:
            component_type: Component type (e.g., "resistor", "capacitor")
            pin_count: Number of pins
            value: Component value (e.g., "10k", "100nF", "50V")
            power_rating: Power rating (e.g., "0.5W", "1W")

        Returns:
            KiCad footprint library reference optimized for component specs
        """
        comp_type_lower = component_type.lower().strip()

        # SMART RESISTOR FOOTPRINT SELECTION (based on power rating)
        if 'resist' in comp_type_lower or comp_type_lower in ['r', 'res']:
            power_w = self._parse_power_rating(power_rating, value)
            if power_w >= 1.0:
                return 'Resistor_SMD:R_2512_6332Metric'  # 1W+ : 2512 package
            elif power_w >= 0.5:
                return 'Resistor_SMD:R_1206_3216Metric'  # 0.5-1W : 1206 package
            elif power_w >= 0.25:
                return 'Resistor_SMD:R_0805_2012Metric'  # 0.25-0.5W : 0805 package
            else:
                return 'Resistor_SMD:R_0603_1608Metric'  # <0.25W : 0603 package (default)

        # SMART CAPACITOR FOOTPRINT SELECTION (based on voltage and capacitance)
        elif 'capac' in comp_type_lower or comp_type_lower in ['c', 'cap']:
            voltage_v = self._parse_voltage(value)
            capacitance_uf = self._parse_capacitance(value)

            # High voltage or high capacitance: use larger footprint
            if voltage_v >= 100 or capacitance_uf >= 100:
                return 'Capacitor_SMD:C_1210_3225Metric'  # High V/C: 1210 package
            elif voltage_v >= 50 or capacitance_uf >= 10:
                return 'Capacitor_SMD:C_0805_2012Metric'  # Medium V/C: 0805 package
            else:
                return 'Capacitor_SMD:C_0603_1608Metric'  # Low V/C: 0603 package (default)

        # For other components, use standard selection
        return self.get_footprint(component_type, pin_count)

    def _parse_power_rating(self, power_rating: str, value: str) -> float:
        """
        Parse power rating from string.

        TC #37 (2025-11-23): Extract power in watts.

        Args:
            power_rating: Power rating string (e.g., "0.5W", "1W")
            value: Component value (may contain power info)

        Returns:
            Power in watts (default 0.125 for standard SMD resistors)
        """
        import re
        text = (power_rating + " " + value).upper()
        match = re.search(r'(\d+\.?\d*)\s*W', text)
        if match:
            return float(match.group(1))
        return 0.125  # Default: 1/8 W (standard SMD resistor)

    def _parse_voltage(self, value: str) -> float:
        """
        Parse voltage rating from value string.

        TC #37 (2025-11-23): Extract voltage in volts.

        Args:
            value: Component value (e.g., "100nF 50V", "10uF/25V")

        Returns:
            Voltage in volts (default 16V for standard capacitors)
        """
        import re
        text = value.upper()
        match = re.search(r'(\d+\.?\d*)\s*V', text)
        if match:
            return float(match.group(1))
        return 16.0  # Default: 16V (standard SMD capacitor)

    def _parse_capacitance(self, value: str) -> float:
        """
        Parse capacitance from value string.

        TC #37 (2025-11-23): Extract capacitance in microfarads.

        Args:
            value: Component value (e.g., "100nF", "10uF", "1000pF")

        Returns:
            Capacitance in microfarads
        """
        import re
        text = value.upper()

        # Try uF/µF
        match = re.search(r'(\d+\.?\d*)\s*[UµMμ]F', text)
        if match:
            return float(match.group(1))

        # Try nF (nanofarads)
        match = re.search(r'(\d+\.?\d*)\s*NF', text)
        if match:
            return float(match.group(1)) / 1000.0  # Convert nF to uF

        # Try pF (picofarads)
        match = re.search(r'(\d+\.?\d*)\s*PF', text)
        if match:
            return float(match.group(1)) / 1000000.0  # Convert pF to uF

        return 0.1  # Default: 100nF (0.1uF)

    def get_footprint(self, component_type: str, pin_count: int) -> str:
        """
        Get KiCad footprint for a component type and pin count.

        GENERIC algorithm with intelligent fallbacks:
        1. Validate component type vs pin count
        2. Try exact match (type, pin_count)
        3. Try type alias + pin count
        4. Try category-based inference
        5. Use intelligent fallback based on pin count

        Args:
            component_type: Component type (e.g., "resistor", "ic", "capacitor")
            pin_count: Number of pins

        Returns:
            KiCad footprint library reference
        """
        # TC #37: Validate component first
        is_valid, warning = self.validate_component(component_type, pin_count)
        if not is_valid:
            logger.error(f"Invalid component detected, using emergency fallback: {warning}")

        # Normalize component type
        comp_type_lower = component_type.lower().strip()

        # Try exact match
        key = (comp_type_lower, pin_count)
        if key in self.footprint_map:
            logger.debug(f"Exact match: {component_type}({pin_count}) -> {self.footprint_map[key]}")
            return self.footprint_map[key]

        # Try alias
        if comp_type_lower in self.type_aliases:
            canonical_type = self.type_aliases[comp_type_lower]
            key = (canonical_type, pin_count)
            if key in self.footprint_map:
                logger.debug(f"Alias match: {component_type}({pin_count}) -> {canonical_type}({pin_count}) -> {self.footprint_map[key]}")
                return self.footprint_map[key]

        # Category-based fallback
        footprint = self._infer_by_category(comp_type_lower, pin_count)
        if footprint:
            logger.info(f"Category inference: {component_type}({pin_count}) -> {footprint}")
            return footprint

        # Ultimate fallback based on pin count
        footprint = self._fallback_by_pin_count(pin_count)
        logger.warning(f"Using fallback for unknown type: {component_type}({pin_count}) -> {footprint}")
        return footprint

    def _infer_by_category(self, comp_type: str, pin_count: int) -> Optional[str]:
        """
        Infer footprint by component category.

        GENERIC logic for common component patterns.
        TC #37 (2025-11-23): Enhanced with fuse, transformer, relay detection.
        """
        # TC #37: CRITICAL - Check for fuses FIRST (before generic 2-pin logic)
        # Prevents fuses from being assigned IC footprints
        if any(keyword in comp_type for keyword in ['fuse', 'protection']):
            if pin_count == 2:
                return 'Fuse:Fuse_1206_3216Metric'
            else:
                logger.warning(f"Unusual fuse with {pin_count} pins, using 2-pin fuse footprint")
                return 'Fuse:Fuse_1206_3216Metric'

        # 2-pin passive components
        if pin_count == 2:
            if any(keyword in comp_type for keyword in ['resist', 'ohm']):
                return 'Resistor_SMD:R_0805_2012Metric'
            elif any(keyword in comp_type for keyword in ['capac', 'farad']):
                return 'Capacitor_SMD:C_0805_2012Metric'
            elif any(keyword in comp_type for keyword in ['induc', 'coil', 'henry']):
                return 'Inductor_SMD:L_0805_2012Metric'
            elif any(keyword in comp_type for keyword in ['diode']):
                return 'Diode_SMD:D_SOD-323'
            elif any(keyword in comp_type for keyword in ['led', 'light']):
                return 'LED_SMD:LED_0805_2012Metric'

        # 3-pin active components
        elif pin_count == 3:
            # TC #76: Check for potentiometers FIRST (they're common 3-pin devices)
            if any(keyword in comp_type for keyword in ['pot', 'trim', 'variable_resist']):
                return 'Potentiometer_SMD:Potentiometer_Bourns_3314J_Vertical'
            # TC #37: Check for voltage regulators
            if any(keyword in comp_type for keyword in ['regul', 'vreg', 'ldo']):
                return 'Package_TO_SOT_SMD:SOT-223-3_TabPin2'
            if any(keyword in comp_type for keyword in ['trans', 'bjt', 'fet', 'mos']):
                return 'Package_TO_SOT_SMD:SOT-23'

        # TC #37: 4-pin components - check for transformers
        elif pin_count == 4:
            if any(keyword in comp_type for keyword in ['xformer', 'xfmr']) or comp_type == 'transformer':
                return 'Transformer_THT:Transformer_37x44'

        # TC #37: Relays (5-8 pins typically)
        elif any(keyword in comp_type for keyword in ['relay']):
            if pin_count <= 5:
                return 'Relay_THT:Relay_SPDT_HJR-3FF'
            else:
                return 'Relay_SMD:Relay_DPDT_Omron_G6K-2F'

        # ICs and complex components
        elif any(keyword in comp_type for keyword in ['ic', 'chip', 'controller', 'processor',
                                                       'driver', 'buffer', 'logic', 'memory',
                                                       'amp', 'regulator', 'converter']):
            return self._infer_ic_footprint(pin_count)

        # Connectors
        elif any(keyword in comp_type for keyword in ['conn', 'header', 'plug', 'jack']):
            return self._infer_connector_footprint(pin_count)

        return None

    def _infer_ic_footprint(self, pin_count: int) -> str:
        """
        GENERIC IC footprint inference based on pin count.

        TC #39 (2025-11-24): Fix RC #12 - Enhanced surface-mount package selection.
        Ensures modern ICs (especially microcontrollers) use appropriate SMD packages:
        - 48-pin ICs: LQFP-48 (7x7mm, 0.5mm pitch) - NOT DIP-48
        - 64-pin ICs: LQFP-64 (10x10mm, 0.5mm pitch)
        - 100+ pins: LQFP or QFN for high-density boards

        Uses industry-standard package progressions optimized for manufacturability.
        """
        if pin_count <= 8:
            # Small ICs: SOIC (surface-mount, standard for op-amps, logic gates)
            return f'Package_SO:SOIC-{pin_count}_3.9x4.9mm_P1.27mm'
        elif pin_count <= 28:
            # Medium ICs: SOIC (surface-mount, standard for medium complexity ICs)
            return f'Package_SO:SOIC-{pin_count}_7.5x12.8mm_P1.27mm'
        elif pin_count <= 64:
            # Larger ICs: LQFP (surface-mount, standard for microcontrollers, FPGAs)
            # TC #39: Critical fix for STM32 and similar MCUs - use LQFP, NOT DIP
            size = 7 if pin_count <= 48 else 10
            pitch = 0.5 if pin_count >= 48 else 0.8
            return f'Package_QFP:LQFP-{pin_count}_{size}x{size}mm_P{pitch}mm'
        elif pin_count <= 144:
            # Very large ICs: LQFP (surface-mount, for complex MCUs and processors)
            return f'Package_QFP:LQFP-{pin_count}_20x20mm_P0.5mm'
        else:
            # Ultra large ICs: BGA
            size = 17 + (pin_count - 256) // 64
            return f'Package_BGA:BGA-{pin_count}_{size}x{size}mm_P1.0mm'

    def _infer_connector_footprint(self, pin_count: int) -> str:
        """
        GENERIC connector footprint inference.

        Uses standard pin header format.
        """
        return f'Connector_PinHeader_2.54mm:PinHeader_1x{pin_count:02d}_P2.54mm_Vertical'

    def _fallback_by_pin_count(self, pin_count: int) -> str:
        """
        Ultimate fallback based purely on pin count.

        TC #45 FIX (2025-11-24): Aligned with _infer_ic_footprint() sizing logic.
        CRITICAL: Must match IC inference for consistency (7x7mm for 48-pin, 10x10mm for 64-pin).

        Provides reasonable generic footprint for unknown component types.
        """
        if pin_count == 1:
            # Single pin: test point
            return 'TestPoint:TestPoint_Pad_D1.5mm'
        elif pin_count == 2:
            # 2 pins: assume passive resistor (most common)
            return 'Resistor_SMD:R_0805_2012Metric'
        elif pin_count == 3:
            # 3 pins: assume transistor
            return 'Package_TO_SOT_SMD:SOT-23'
        elif pin_count <= 8:
            # 4-8 pins: small IC
            return f'Package_SO:SOIC-{pin_count}_3.9x4.9mm_P1.27mm'
        elif pin_count <= 28:
            # 10-28 pins: medium IC
            return f'Package_SO:SOIC-{pin_count}_7.5x12.8mm_P1.27mm'
        elif pin_count <= 64:
            # 32-64 pins: LQFP
            # TC #45: Match _infer_ic_footprint() sizing (7x7mm for <=48, 10x10mm for >48)
            size = 7 if pin_count <= 48 else 10
            pitch = 0.5 if pin_count >= 48 else 0.8
            return f'Package_QFP:LQFP-{pin_count}_{size}x{size}mm_P{pitch}mm'
        elif pin_count <= 144:
            # 80-144 pins: large LQFP
            return f'Package_QFP:LQFP-{pin_count}_20x20mm_P0.5mm'
        else:
            # 150+ pins: BGA
            return f'Package_BGA:BGA-{pin_count}_17x17mm_P1.0mm'


# GLOBAL INSTANCE for easy access
_footprint_mapper = None


def get_footprint_mapper() -> KiCadFootprintMapper:
    """Get global footprint mapper instance (singleton pattern)."""
    global _footprint_mapper
    if _footprint_mapper is None:
        _footprint_mapper = KiCadFootprintMapper()
    return _footprint_mapper


def infer_kicad_footprint(component_type: str, pin_count: int) -> str:
    """
    Convenience function to infer KiCad footprint.

    GENERIC function that works for ANY component type and pin count.

    Args:
        component_type: Component type from lowlevel format
        pin_count: Number of pins on component

    Returns:
        KiCad footprint library reference

    Examples:
        >>> infer_kicad_footprint('resistor', 2)
        'Resistor_SMD:R_0805_2012Metric'

        >>> infer_kicad_footprint('ic', 48)
        'Package_QFP:LQFP-48_7x7mm_P0.5mm'

        >>> infer_kicad_footprint('unknown_component', 16)
        'Package_SO:SOIC-16_7.5x12.8mm_P1.27mm'
    """
    mapper = get_footprint_mapper()
    return mapper.get_footprint(component_type, pin_count)


def infer_kicad_footprint_smart(component_type: str, pin_count: int,
                                value: str = "", power_rating: str = "") -> str:
    """
    SMART convenience function with value-based footprint selection.

    TC #37 (2025-11-23): Enhanced to consider component specifications.

    Args:
        component_type: Component type from lowlevel format
        pin_count: Number of pins on component
        value: Component value (e.g., "10k", "100nF 50V")
        power_rating: Power rating (e.g., "0.5W", "1W")

    Returns:
        KiCad footprint library reference optimized for component specs

    Examples:
        >>> infer_kicad_footprint_smart('resistor', 2, value='10k 0.5W')
        'Resistor_SMD:R_1206_3216Metric'  # 0.5W requires 1206

        >>> infer_kicad_footprint_smart('capacitor', 2, value='100uF 100V')
        'Capacitor_SMD:C_1210_3225Metric'  # High V/C requires 1210

        >>> infer_kicad_footprint_smart('resistor', 2, value='10k')
        'Resistor_SMD:R_0603_1608Metric'  # Low power defaults to 0603
    """
    mapper = get_footprint_mapper()
    return mapper.get_footprint_smart(component_type, pin_count, value, power_rating)


if __name__ == '__main__':
    # Test the mapper with various component types
    logging.basicConfig(level=logging.DEBUG)

    test_cases = [
        ('resistor', 2),
        ('capacitor', 2),
        ('ic', 8),
        ('ic', 48),
        ('ic', 100),
        ('microcontroller', 64),
        ('connector', 10),
        ('unknown_component', 16),
        ('transistor', 3),
        ('led', 2),
    ]

    print("KiCad Footprint Mapper - Test Cases")
    print("=" * 60)
    for comp_type, pins in test_cases:
        footprint = infer_kicad_footprint(comp_type, pins)
        print(f"{comp_type:20s} ({pins:3d} pins) -> {footprint}")
