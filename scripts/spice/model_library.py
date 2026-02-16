#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
SPICE Model Library - Generic Component to SPICE Model Mapping
==============================================================

This module provides a GENERIC, EXTENSIBLE mapping from CopperPilot component
types to SPICE primitives and models. It handles ANY circuit type from simple
LED blinkers to complex multi-board industrial systems.

Design Philosophy
-----------------
1. GENERIC: No hardcoded assumptions about circuit types
2. EXTENSIBLE: Easy to add new component types and models
3. FALLBACK: Unknown components get reasonable default models
4. VALUE PARSING: Robust parsing of component values (10k, 100nF, 1.5MHz, etc.)

SPICE Primitive Types
---------------------
- R: Resistor (2-terminal)
- C: Capacitor (2-terminal)
- L: Inductor (2-terminal)
- D: Diode (2-terminal)
- Q: BJT Transistor (3-terminal: C, B, E)
- M: MOSFET (4-terminal: D, G, S, B)
- J: JFET (3-terminal: D, G, S)
- X: Subcircuit (N-terminal: op-amps, ICs, etc.)
- V: Voltage source
- I: Current source

Author: CopperPilot Team
Date: December 2025
Version: 1.0.0
"""

import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from pathlib import Path

# Ensure project root is on sys.path for config import
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from server.config import config
from .spice_utils import spice_safe_name


class SpiceType(Enum):
    """
    SPICE primitive element types.

    Each type corresponds to a SPICE netlist prefix letter.
    This enumeration is GENERIC and covers all standard SPICE elements.
    """
    RESISTOR = "R"           # R<name> <n+> <n-> <value>
    CAPACITOR = "C"          # C<name> <n+> <n-> <value>
    INDUCTOR = "L"           # L<name> <n+> <n-> <value>
    DIODE = "D"              # D<name> <n+> <n-> <model>
    BJT = "Q"                # Q<name> <nc> <nb> <ne> <model>
    MOSFET = "M"             # M<name> <nd> <ng> <ns> <nb> <model>
    JFET = "J"               # J<name> <nd> <ng> <ns> <model>
    SUBCIRCUIT = "X"         # X<name> <nodes...> <subckt>
    VOLTAGE_SOURCE = "V"     # V<name> <n+> <n-> <value>
    CURRENT_SOURCE = "I"     # I<name> <n+> <n-> <value>
    SWITCH = "S"             # S<name> <n+> <n-> <nc+> <nc-> <model>
    TRANSMISSION_LINE = "T"  # T<name> <nodes...> <params>
    COUPLED_INDUCTOR = "K"   # K<name> <L1> <L2> <coupling>


@dataclass
class ComponentModel:
    """
    Represents a SPICE model for a component.

    This is a GENERIC container that can represent ANY component type,
    from simple resistors to complex ICs with many pins.

    Attributes
    ----------
    spice_type : SpiceType
        The SPICE primitive type (R, C, L, D, Q, M, X, etc.)
    model_name : Optional[str]
        SPICE model name (e.g., "1N4148", "2N2222", "LM358")
    num_terminals : int
        Number of terminals (2 for passives, 3-4 for transistors, N for ICs)
    pin_order : List[str]
        Order of pins for netlist generation (e.g., ["A", "K"] for diode)
    default_params : Dict[str, str]
        Default parameters for the model
    model_definition : Optional[str]
        Full SPICE .model or .subckt definition (if needed)
    ltspice_symbol : Optional[str]
        LTSpice symbol name for .asc generation
    """
    spice_type: SpiceType
    model_name: Optional[str] = None
    num_terminals: int = 2
    pin_order: List[str] = field(default_factory=list)
    default_params: Dict[str, str] = field(default_factory=dict)
    model_definition: Optional[str] = None
    ltspice_symbol: Optional[str] = None


class SpiceModelLibrary:
    """
    GENERIC library for mapping CopperPilot components to SPICE models.

    This class provides:
    1. Component type detection (resistor, capacitor, transistor, IC, etc.)
    2. Value parsing (10k → 10000, 100nF → 100e-9, etc.)
    3. Model selection based on component value/part number
    4. Fallback models for unknown components

    The library is designed to be EXTENSIBLE - new component types and
    models can be added without modifying existing code.
    """

    # =========================================================================
    # SI PREFIX MULTIPLIERS - Used for value parsing
    # =========================================================================
    SI_PREFIXES = {
        'f': 1e-15,   # femto
        'p': 1e-12,   # pico
        'n': 1e-9,    # nano
        'u': 1e-6,    # micro (also μ)
        'μ': 1e-6,    # micro (unicode)
        'm': 1e-3,    # milli
        'k': 1e3,     # kilo
        'K': 1e3,     # kilo (alternate)
        'M': 1e6,     # mega
        'G': 1e9,     # giga
        'T': 1e12,    # tera
    }

    # SPICE-compatible suffix mapping
    SPICE_SUFFIXES = {
        1e-15: 'f',
        1e-12: 'p',
        1e-9: 'n',
        1e-6: 'u',
        1e-3: 'm',
        1e3: 'k',
        1e6: 'MEG',
        1e9: 'G',
        1e12: 'T',
    }

    # =========================================================================
    # COMPONENT TYPE MAPPING - Maps CopperPilot types to SPICE types
    # =========================================================================
    TYPE_MAPPING = {
        # Passive components (2-terminal)
        'resistor': SpiceType.RESISTOR,
        'res': SpiceType.RESISTOR,
        'r': SpiceType.RESISTOR,
        'capacitor': SpiceType.CAPACITOR,
        'cap': SpiceType.CAPACITOR,
        'c': SpiceType.CAPACITOR,
        'inductor': SpiceType.INDUCTOR,
        'ind': SpiceType.INDUCTOR,
        'l': SpiceType.INDUCTOR,
        'coil': SpiceType.INDUCTOR,

        # Diodes (2-terminal)
        'diode': SpiceType.DIODE,
        'd': SpiceType.DIODE,
        'led': SpiceType.DIODE,
        'zener': SpiceType.DIODE,
        'schottky': SpiceType.DIODE,
        'tvs': SpiceType.DIODE,

        # Transistors (3-4 terminal)
        'npn': SpiceType.BJT,
        'pnp': SpiceType.BJT,
        'bjt': SpiceType.BJT,
        'transistor': SpiceType.BJT,
        'nmos': SpiceType.MOSFET,
        'pmos': SpiceType.MOSFET,
        'mosfet': SpiceType.MOSFET,
        'fet': SpiceType.MOSFET,
        'jfet': SpiceType.JFET,
        'n-jfet': SpiceType.JFET,
        'p-jfet': SpiceType.JFET,

        # ICs and complex components (subcircuits)
        'ic': SpiceType.SUBCIRCUIT,
        'opamp': SpiceType.SUBCIRCUIT,
        'op-amp': SpiceType.SUBCIRCUIT,
        'comparator': SpiceType.SUBCIRCUIT,
        'regulator': SpiceType.SUBCIRCUIT,
        'voltage_regulator': SpiceType.SUBCIRCUIT,
        'adc': SpiceType.SUBCIRCUIT,
        'dac': SpiceType.SUBCIRCUIT,
        'microcontroller': SpiceType.SUBCIRCUIT,
        'mcu': SpiceType.SUBCIRCUIT,
        'driver': SpiceType.SUBCIRCUIT,
        'amplifier': SpiceType.SUBCIRCUIT,

        # Sources (typically for test/stimulus)
        'voltage_source': SpiceType.VOLTAGE_SOURCE,
        'vsource': SpiceType.VOLTAGE_SOURCE,
        'current_source': SpiceType.CURRENT_SOURCE,
        'isource': SpiceType.CURRENT_SOURCE,

        # Fix K.6: Connectors as SUBCIRCUIT (independent pins, no internal short).
        # Previously modeled as RESISTOR (0.001 Ohm between pin 1 and 2),
        # which shorts power rails on multi-pin connectors.
        'connector': SpiceType.SUBCIRCUIT,
        'header': SpiceType.SUBCIRCUIT,
        'terminal': SpiceType.SUBCIRCUIT,
        'jack': SpiceType.SUBCIRCUIT,
        'jumper': SpiceType.RESISTOR,     # 2-pin jumper OK as resistor
        'fuse': SpiceType.RESISTOR,       # Model as small resistance
        'switch': SpiceType.SWITCH,

        # Fix K.13: Ferrite beads as RESISTOR (impedance at 100MHz),
        # NOT inductor. A "600" ferrite bead = 600 Ohm, not 600 Henry.
        'ferrite': SpiceType.RESISTOR,
        'ferrite_bead': SpiceType.RESISTOR,
        'bead': SpiceType.RESISTOR,
        'emi_filter': SpiceType.RESISTOR,

        # M.6 FIX: NTC/PTC thermistors as resistors at nominal resistance
        'ntc': SpiceType.RESISTOR,
        'thermistor': SpiceType.RESISTOR,
        'ntc_thermistor': SpiceType.RESISTOR,
        'ptc': SpiceType.RESISTOR,
        'temperature_sensor': SpiceType.RESISTOR,
        'temp_sensor': SpiceType.RESISTOR,
        'rtd': SpiceType.RESISTOR,

        # V.7 FIX: Potentiometers as subcircuits (3-terminal voltage divider)
        'potentiometer': SpiceType.SUBCIRCUIT,
        'trimmer': SpiceType.SUBCIRCUIT,
        'trimpot': SpiceType.SUBCIRCUIT,
        'pot': SpiceType.SUBCIRCUIT,
        'variable_resistor': SpiceType.SUBCIRCUIT,
        'rheostat': SpiceType.SUBCIRCUIT,

        # Crystal/Oscillator (LC equivalent)
        'crystal': SpiceType.SUBCIRCUIT,
        'oscillator': SpiceType.SUBCIRCUIT,
        'xtal': SpiceType.SUBCIRCUIT,

        # Transformers
        'transformer': SpiceType.COUPLED_INDUCTOR,
    }

    # =========================================================================
    # KNOWN SPICE MODELS - Common diodes, transistors, and ICs
    # =========================================================================
    DIODE_MODELS = {
        # General purpose diodes
        '1N4148': '.model 1N4148 D(Is=2.52e-9 Rs=0.568 N=1.752 BV=100 IBV=100u)',
        '1N4007': '.model 1N4007 D(Is=7.02e-9 Rs=0.0341 N=1.8 BV=1000 IBV=5u)',
        '1N4001': '.model 1N4001 D(Is=2.55e-9 Rs=0.042 N=1.75 BV=50 IBV=5u)',
        '1N5819': '.model 1N5819 D(Is=1e-5 Rs=0.04 N=1.3 BV=40 IBV=1m)',  # Schottky
        '1N5822': '.model 1N5822 D(Is=1.5e-5 Rs=0.03 N=1.25 BV=40 IBV=1m)',  # Schottky
        'SS34': '.model SS34 D(Is=1e-5 Rs=0.025 N=1.2 BV=40 IBV=1m)',  # Schottky
        'SS14': '.model SS14 D(Is=5e-6 Rs=0.03 N=1.25 BV=40 IBV=1m)',  # Schottky

        # Zener diodes (example models)
        'BZX84C5V1': '.model BZX84C5V1 D(Is=1e-14 BV=5.1 IBV=5m)',
        'BZX84C3V3': '.model BZX84C3V3 D(Is=1e-14 BV=3.3 IBV=5m)',

        # TVS diodes (simplified)
        'SMBJ51A': '.model SMBJ51A D(Is=1e-14 BV=51 IBV=1)',
        'SMBJ24A': '.model SMBJ24A D(Is=1e-14 BV=24 IBV=1)',

        # LEDs (simplified forward drop)
        'LED_RED': '.model LED_RED D(Is=1e-20 N=1.5 BV=5 IBV=1u)',
        'LED_GREEN': '.model LED_GREEN D(Is=1e-21 N=1.6 BV=5 IBV=1u)',
        'LED_BLUE': '.model LED_BLUE D(Is=1e-22 N=1.8 BV=5 IBV=1u)',
        'LED_WHITE': '.model LED_WHITE D(Is=1e-22 N=1.8 BV=5 IBV=1u)',
        'LED': '.model LED D(Is=1e-21 N=1.6 BV=5 IBV=1u)',
    }

    BJT_MODELS = {
        # NPN transistors
        '2N2222': '.model 2N2222 NPN(Is=1e-14 Bf=200 Vaf=100 Ikf=0.3 Ise=1e-14 Ne=1.5 Br=3 Var=100)',
        '2N3904': '.model 2N3904 NPN(Is=1e-14 Bf=300 Vaf=100 Ikf=0.4 Ise=1e-14 Ne=1.5)',
        'BC547': '.model BC547 NPN(Is=1e-14 Bf=400 Vaf=100 Ikf=0.1)',
        'BC337': '.model BC337 NPN(Is=1e-14 Bf=200 Vaf=100 Ikf=0.8)',

        # PNP transistors
        '2N2907': '.model 2N2907 PNP(Is=1e-14 Bf=200 Vaf=100 Ikf=0.3)',
        '2N3906': '.model 2N3906 PNP(Is=1e-14 Bf=300 Vaf=100 Ikf=0.4)',
        'BC557': '.model BC557 PNP(Is=1e-14 Bf=400 Vaf=100 Ikf=0.1)',
    }

    MOSFET_MODELS = {
        # N-channel MOSFETs
        'IRF540': '.model IRF540 NMOS(Level=3 Kp=20 Vto=4 Rd=0.077)',
        'IRF530': '.model IRF530 NMOS(Level=3 Kp=15 Vto=4 Rd=0.16)',
        '2N7000': '.model 2N7000 NMOS(Level=3 Kp=0.15 Vto=2.5 Rd=5)',
        'BS170': '.model BS170 NMOS(Level=3 Kp=0.1 Vto=2 Rd=5)',
        'IRLZ44N': '.model IRLZ44N NMOS(Level=3 Kp=100 Vto=2 Rd=0.022)',

        # P-channel MOSFETs
        'IRF9540': '.model IRF9540 PMOS(Level=3 Kp=10 Vto=-4 Rd=0.2)',
        'IRF9530': '.model IRF9530 PMOS(Level=3 Kp=8 Vto=-4 Rd=0.3)',
    }

    # =========================================================================
    # OPAMP AND IC SUBCIRCUITS
    # =========================================================================
    # Phase E Upgrade (Feb 2026): Functional behavioral models instead of stubs
    OPAMP_SUBCIRCUITS = {
        # Generic opamp behavioral model
        'OPAMP_GENERIC': '''
.subckt OPAMP_GENERIC INP INN VCC VEE OUT
* Behavioral op-amp model
* High input impedance
Rin INP INN 10MEG
* Voltage-controlled voltage source for open-loop gain
E1 OUT_INT 0 INP INN 100k
* Output resistance and rail-clamping approximation
R1 OUT_INT OUT 100
Cout OUT 0 10p
.ends OPAMP_GENERIC''',

        'LM358': '''
.subckt LM358 INP INN VCC VEE OUT
* LM358 Behavioral Model
Rin INP INN 2MEG
E1 OUT_INT 0 INP INN 100k
R1 OUT_INT OUT 100
* Simple rail limiting
V_HIGH VCC OUT_INT DC 1.5
V_LOW OUT_INT VEE DC 0.1
.ends LM358''',

        'AD9833': '''
.subckt AD9833 COMP VDD CAP DGND MCLK AGND VOUT AVDD SCLK SDATA FSYNC
* AD9833 Functional Sine Source Model (Approximate)
* Generates 50kHz sine on VOUT if VDD is present
B1 VOUT AGND V=V(VDD,DGND) > 2.5 ? 0.6*sin(2*3.14159*50k*time) : 0
R1 VDD DGND 10k
R2 AVDD AGND 10k
.ends AD9833''',

        'IR2110': '''
.subckt IR2110 VCC HIN LIN COM LO VSS VB HO
* IR2110 Functional Gate Driver Model
* High side: HO tracks HIN relative to VB/VS (approximated)
B1 HO COM V=V(HIN,VSS) > 2 ? V(VB,COM) : 0
* Low side: LO tracks LIN relative to VCC/COM
B2 LO COM V=V(LIN,VSS) > 2 ? V(VCC,COM) : 0
R1 VCC COM 20k
R2 VSS COM 10
.ends IR2110''',

        # M.2 FIX: ngspice B-source rules:
        #   - NO '&' operator (use nested ternary instead)
        #   - NO pulse() inside B-source (only valid in standalone V/I sources)
        #   - Use time-based switching via sin() for duty cycle approximation
        'TPS54331': '''
.subckt TPS54331 BOOT VIN EN SS VSENSE COMP GND SW
* TPS54331 Buck Controller Behavioral Model (M.2 fixed)
* Nested ternary replaces invalid '&' operator
* Duty cycle approximation replaces invalid pulse() in B-source
B1 SW GND V=V(VIN,GND) > 3.5 ? (V(EN,GND) > 1.2 ? V(VIN,GND)*0.5 : 0) : 0
R1 VIN GND 100k
R2 VSENSE GND 1MEG
.ends TPS54331''',

        'AD9851': '''
.subckt AD9851 DGND AVDD DVDD AGND VOUT DAC_BP IOUT IOUTB VINN VINP
* AD9851 Functional 1.5MHz Source Model
B1 VOUT AGND V=V(AVDD,AGND) > 2.5 ? 0.5*sin(2*3.14159*1.5MEG*time) : 0
R1 AVDD AGND 10k
.ends AD9851''',

        'IR2113': '''
.subckt IR2113 VCC HIN LIN COM LO VSS VB HO
* IR2113 Functional Gate Driver Model (Same as IR2110)
B1 HO COM V=V(HIN,VSS) > 2 ? V(VB,COM) : 0
B2 LO COM V=V(LIN,VSS) > 2 ? V(VCC,COM) : 0
R1 VCC COM 20k
.ends IR2113''',
    }

    # Voltage regulator subcircuits (simplified)
    REGULATOR_SUBCIRCUITS = {
        'LM7805': '''
.subckt LM7805 IN GND OUT
* 5V linear regulator
V1 OUT GND DC 5
Rin IN OUT 1
.ends LM7805''',

        'LM7812': '''
.subckt LM7812 IN GND OUT
V1 OUT GND DC 12
Rin IN OUT 1
.ends LM7812''',

        'LM7815': '''
.subckt LM7815 IN GND OUT
V1 OUT GND DC 15
Rin IN OUT 1
.ends LM7815''',

        'LM7915': '''
.subckt LM7915 IN GND OUT
V1 OUT GND DC -15
Rin IN OUT 1
.ends LM7915''',

        'LM317': '''
.subckt LM317 IN ADJ OUT
* Adjustable regulator - requires external resistors
* OUT = 1.25 * (1 + R2/R1) where ADJ is connected to R1-R2 junction
V1 OUT ADJ DC 1.25
Rin IN OUT 0.5
.ends LM317''',

        'AMS1117-3.3': '''
.subckt AMS1117-3.3 GND IN OUT
V1 OUT GND DC 3.3
Rin IN OUT 0.5
.ends AMS1117-3.3''',

        'AMS1117-5.0': '''
.subckt AMS1117-5.0 GND IN OUT
V1 OUT GND DC 5
Rin IN OUT 0.5
.ends AMS1117-5.0''',
    }

    # =========================================================================
    # CLASS METHODS
    # =========================================================================

    def __init__(self):
        """
        Initialize the model library.

        Creates internal caches for model lookups and allows
        runtime extension of the library.
        """
        self._custom_models: Dict[str, str] = {}
        self._custom_subcircuits: Dict[str, str] = {}

    def get_spice_type(self, component_type: str) -> SpiceType:
        """
        Get the SPICE type for a given CopperPilot component type.

        This method is GENERIC and handles any component type by:
        1. Checking the TYPE_MAPPING dictionary
        2. Falling back to SUBCIRCUIT for unknown types

        Parameters
        ----------
        component_type : str
            CopperPilot component type (e.g., "resistor", "ic", "opamp")

        Returns
        -------
        SpiceType
            The corresponding SPICE primitive type
        """
        normalized = component_type.lower().strip()
        return self.TYPE_MAPPING.get(normalized, SpiceType.SUBCIRCUIT)

    def parse_value(self, value_str: str, component_type: str = '') -> Tuple[float, str]:
        """
        Parse a component value string into a numeric value and SPICE-compatible suffix.

        Handles various formats:
        - "10k" → (10000, "10k")
        - "100nF" → (1e-7, "100n")
        - "1.5MHz" → (1500000, "1.5MEG")
        - "470uF/63V" → (4.7e-4, "470u")  # Strips voltage rating
        - "33uH/3A" → (3.3e-5, "33u")     # Strips current rating

        Parameters
        ----------
        value_str : str
            Component value string from CopperPilot JSON
        component_type : str
            Component type (helps interpret ambiguous values)

        Returns
        -------
        Tuple[float, str]
            (numeric_value, spice_string)
        """
        if not value_str:
            return (0.0, "0")

        # Clean the string - remove voltage/current ratings
        clean = value_str.strip()
        # Remove /XXV or /XXA ratings (e.g., "470uF/63V" -> "470uF")
        clean = re.sub(r'/[\d.]+[VAva]', '', clean)
        # Remove standalone voltage/current specs
        clean = re.sub(r'\s*[\d.]+[VAva]\s*$', '', clean)

        # T.1 FIX: Strip type descriptor words from component values
        # (e.g., "10k NTC" → "10k", "100nF ceramic" → "100nF")
        # Uses config-driven list for maintainability.
        descriptors = config.SPICE_VALUE_TYPE_DESCRIPTORS
        if descriptors:
            words = clean.split()
            clean = ' '.join(
                w for w in words if w.lower() not in descriptors
            ).strip()

        # Handle special cases for part numbers (return as-is)
        if self._is_part_number(clean):
            return (0.0, clean)

        # Parse numeric value with SI prefix
        # Patterns like: "10k", "100nF", "470uF", "33uH", "4.7M"
        match = re.match(r'^([\d.]+)\s*([fpnuμmkKMGT]?)([FHΩRCLVAHz]*)$', clean, re.IGNORECASE)
        if not match:
            # Try alternate pattern: "10k", "4k7" (European notation)
            match = re.match(r'^([\d.]+)\s*([fpnuμmkKMGT])(\d*)$', clean, re.IGNORECASE)
        if match:
            number = float(match.group(1))
            prefix = match.group(2)
            unit = match.group(3)

            # Apply SI prefix multiplier
            multiplier = self.SI_PREFIXES.get(prefix, 1.0)
            numeric_value = number * multiplier

            # Build SPICE-compatible string
            spice_suffix = self._get_spice_suffix(multiplier)
            spice_str = f"{number}{spice_suffix}" if spice_suffix else str(number)

            return (numeric_value, spice_str)

        # Try to extract just the number
        num_match = re.match(r'^([\d.]+)', clean)
        if num_match:
            return (float(num_match.group(1)), num_match.group(1))

        # Return as-is for part numbers
        return (0.0, clean)

    def _is_part_number(self, value: str) -> bool:
        """
        Check if a value string is a part number (not a component value).

        Part numbers typically contain letters in the middle or start with letters.
        Examples: "LM7815", "1N4148", "2N2222", "TL074"

        Parameters
        ----------
        value : str
            Value string to check

        Returns
        -------
        bool
            True if this appears to be a part number
        """
        # Contains letters in the middle or starts with letters
        if re.match(r'^[A-Za-z]', value):
            return True
        # Digit-letter-digit pattern: "1N4148", "2N2222", "BC547"
        if re.search(r'\d[A-Za-z]+\d', value):
            return True
        # T.2 FIX: Previous regex r'^\d+[A-Za-z]+' was too broad — it matched
        # valid SI-prefixed values like "10k", "100n", "4.7u". A part number
        # requires 2+ letters after digits AND a trailing digit (e.g., "1N4148").
        # Single-letter SI prefixes (k, M, n, u, p, etc.) are NOT part numbers.
        return False

    def _get_spice_suffix(self, multiplier: float) -> str:
        """
        Get SPICE-compatible suffix for a multiplier value.

        Parameters
        ----------
        multiplier : float
            SI prefix multiplier (e.g., 1e3 for kilo)

        Returns
        -------
        str
            SPICE suffix string
        """
        # Find closest match
        for mult, suffix in self.SPICE_SUFFIXES.items():
            if abs(multiplier - mult) / mult < 0.01:
                return suffix
        return ""

    def get_model(self, component: Dict[str, Any]) -> ComponentModel:
        """
        Get a SPICE model for a component.

        This is the main method for component-to-model conversion.
        It handles:
        1. Type detection from component type or ref prefix
        2. Model selection based on value/part number
        3. Pin mapping for multi-terminal devices

        Parameters
        ----------
        component : Dict[str, Any]
            Component dict from CopperPilot JSON with keys:
            - ref: Reference designator (e.g., "R1", "U1")
            - type: Component type (e.g., "resistor", "ic")
            - value: Component value (e.g., "10k", "LM7815")
            - pins: List of pin definitions

        Returns
        -------
        ComponentModel
            SPICE model for the component
        """
        comp_type = component.get('type', '').lower()
        comp_value = component.get('value', '')
        comp_ref = component.get('ref', '')
        pins = component.get('pins', [])

        # Get SPICE type
        spice_type = self.get_spice_type(comp_type)

        # M.6 FIX: NTC/PTC thermistor detection — model as resistor at nominal
        # resistance. Must check BEFORE the type-based dispatch since some
        # thermistors may have type='sensor' which maps to SUBCIRCUIT.
        if (comp_type in config.NTC_THERMISTOR_TYPES or
                any(comp_ref.upper().startswith(p) for p in config.NTC_THERMISTOR_REF_PREFIXES)):
            return self._build_thermistor_model(component)

        # V.7 FIX: Potentiometer detection — model as voltage divider at 50%
        # wiper position. Must check BEFORE generic subcircuit fallback.
        if (comp_type in config.POTENTIOMETER_TYPES or
                any(comp_ref.upper().startswith(p) for p in config.POTENTIOMETER_REF_PREFIXES)):
            return self._build_potentiometer_model(component)

        # Build model based on type
        if spice_type == SpiceType.RESISTOR:
            return self._build_resistor_model(component)
        elif spice_type == SpiceType.CAPACITOR:
            return self._build_capacitor_model(component)
        elif spice_type == SpiceType.INDUCTOR:
            return self._build_inductor_model(component)
        elif spice_type == SpiceType.DIODE:
            return self._build_diode_model(component)
        elif spice_type == SpiceType.BJT:
            return self._build_bjt_model(component)
        elif spice_type == SpiceType.MOSFET:
            return self._build_mosfet_model(component)
        elif spice_type == SpiceType.SUBCIRCUIT:
            return self._build_subcircuit_model(component)
        else:
            # Fallback: treat as subcircuit
            return self._build_generic_model(component)

    def _build_resistor_model(self, component: Dict[str, Any]) -> ComponentModel:
        """Build model for resistor components."""
        value = component.get('value', '0')
        comp_type = component.get('type', '').lower()
        comp_ref = component.get('ref', '').upper()

        # Fix K.13: Ferrite beads — value is impedance in ohms at 100MHz,
        # NOT inductance. A "600" ferrite bead = 600 Ohm series resistance.
        if comp_type in config.FERRITE_BEAD_TYPES or any(
            comp_ref.startswith(p) for p in config.FERRITE_BEAD_REF_PREFIXES
        ):
            # Parse the bare number as ohms (no unit suffix conversion)
            try:
                impedance = float(re.sub(r'[^0-9.]', '', value) or '100')
            except ValueError:
                impedance = 100.0  # Default ferrite bead impedance
            spice_value = str(impedance)
        elif comp_type in ('fuse', 'jumper'):
            spice_value = '0.001'  # 1 milliohm for fuses/jumpers
        else:
            _, spice_value = self.parse_value(value, 'resistor')

        return ComponentModel(
            spice_type=SpiceType.RESISTOR,
            model_name=None,
            num_terminals=2,
            pin_order=['1', '2'],
            default_params={'value': spice_value},
            ltspice_symbol='res',
        )

    def _build_thermistor_model(self, component: Dict[str, Any]) -> ComponentModel:
        """
        M.6 FIX: Build model for NTC/PTC thermistor components.

        Thermistors are 2-terminal temperature-dependent resistors. In SPICE
        they are modeled as simple resistors at their nominal resistance value.
        A 10k NTC at 25°C → 10k resistor.

        Falls back to 10k (common NTC value) if the value can't be parsed.
        """
        value = component.get('value', '10k')

        # Try to parse the value as a resistance
        try:
            _, spice_value = self.parse_value(value, 'resistor')
            # If parse returned a part number (0.0), use default
            numeric, _ = self.parse_value(value, 'resistor')
            if numeric == 0.0:
                spice_value = '10k'  # Default NTC resistance at 25°C
        except Exception:
            spice_value = '10k'

        return ComponentModel(
            spice_type=SpiceType.RESISTOR,
            model_name=None,
            num_terminals=2,
            pin_order=['1', '2'],
            default_params={'value': spice_value},
            ltspice_symbol='res',
        )

    def _build_potentiometer_model(self, component: Dict[str, Any]) -> ComponentModel:
        """
        V.7 FIX: Build a voltage-divider model for potentiometers/trimmers.

        Potentiometers are 3-terminal variable resistors modeled at 50%
        wiper position (mid-range). This provides a physically meaningful
        SPICE model that allows simulation to verify voltage divider behavior,
        unlike the generic stub (10MEG resistors) used previously.

        Pin mapping: CW (pin 1) — WIPER (pin 2) — CCW (pin 3)
        At 50%: R_TOP = R_BOT = total_resistance / 2

        Falls back to 10k total resistance if the value can't be parsed.
        """
        value = component.get('value', '10k')

        # Parse total resistance
        try:
            _, spice_value = self.parse_value(value, 'resistor')
            numeric, _ = self.parse_value(value, 'resistor')
            if numeric == 0.0:
                numeric = 10000.0  # Default 10k potentiometer
        except Exception:
            numeric = 10000.0

        # Model at 50% wiper position
        r_half = numeric / 2.0
        # Format for SPICE (use engineering notation)
        if r_half >= 1e6:
            r_str = f"{r_half / 1e6:.3g}MEG"
        elif r_half >= 1e3:
            r_str = f"{r_half / 1e3:.4g}k"
        else:
            r_str = f"{r_half:.4g}"

        # Use canonical name sanitization for subcircuit name
        safe_value = spice_safe_name(value)
        subckt_name = f"POT_{safe_value}"

        subckt_def = (
            f"\n.subckt {subckt_name} CW WIPER CCW\n"
            f"* Potentiometer {value} at 50% wiper position\n"
            f"* Pin 1 = CW (clockwise end)\n"
            f"* Pin 2 = WIPER (wiper/slider)\n"
            f"* Pin 3 = CCW (counter-clockwise end)\n"
            f"R_TOP CW WIPER {r_str}\n"
            f"R_BOT WIPER CCW {r_str}\n"
            f".ends {subckt_name}"
        )

        return ComponentModel(
            spice_type=SpiceType.SUBCIRCUIT,
            model_name=subckt_name,
            num_terminals=3,
            pin_order=['1', '2', '3'],
            default_params={'value': str(numeric)},
            model_definition=subckt_def,
            ltspice_symbol=None,
        )

    def _build_capacitor_model(self, component: Dict[str, Any]) -> ComponentModel:
        """Build model for capacitor components."""
        value = component.get('value', '0')
        _, spice_value = self.parse_value(value, 'capacitor')

        return ComponentModel(
            spice_type=SpiceType.CAPACITOR,
            model_name=None,
            num_terminals=2,
            pin_order=['1', '2'],
            default_params={'value': spice_value},
            ltspice_symbol='cap',
        )

    def _build_inductor_model(self, component: Dict[str, Any]) -> ComponentModel:
        """Build model for inductor components."""
        value = component.get('value', '0')
        _, spice_value = self.parse_value(value, 'inductor')

        return ComponentModel(
            spice_type=SpiceType.INDUCTOR,
            model_name=None,
            num_terminals=2,
            pin_order=['1', '2'],
            default_params={'value': spice_value},
            ltspice_symbol='ind',
        )

    def _build_diode_model(self, component: Dict[str, Any]) -> ComponentModel:
        """Build model for diode components (including LEDs, TVS, Zeners)."""
        value = component.get('value', '')
        value_upper = value.upper()

        # Find matching model
        model_name = 'D_GENERIC'
        model_def = '.model D_GENERIC D(Is=1e-14 N=1.8 BV=100)'

        # Check for known diode models
        for name, definition in self.DIODE_MODELS.items():
            if name.upper() in value_upper or value_upper in name.upper():
                model_name = name
                model_def = definition
                break

        # LED detection
        if 'LED' in value_upper:
            # Extract color if specified
            for color in ['RED', 'GREEN', 'BLUE', 'WHITE', 'YELLOW']:
                if color in value_upper:
                    model_name = f'LED_{color}'
                    model_def = self.DIODE_MODELS.get(model_name, self.DIODE_MODELS['LED'])
                    break
            else:
                model_name = 'LED'
                model_def = self.DIODE_MODELS['LED']

        return ComponentModel(
            spice_type=SpiceType.DIODE,
            model_name=model_name,
            num_terminals=2,
            pin_order=['A', 'K'],  # Anode, Cathode
            default_params={},
            model_definition=model_def,
            ltspice_symbol='diode',
        )

    def _build_bjt_model(self, component: Dict[str, Any]) -> ComponentModel:
        """Build model for BJT transistor components."""
        value = component.get('value', '')
        comp_type = component.get('type', '').lower()
        value_upper = value.upper()

        # Determine NPN or PNP
        is_pnp = 'pnp' in comp_type or '2N2907' in value_upper or '2N3906' in value_upper

        # Find matching model
        model_name = '2N2907' if is_pnp else '2N2222'
        model_def = self.BJT_MODELS.get(model_name, '')

        for name, definition in self.BJT_MODELS.items():
            if name.upper() in value_upper:
                model_name = name
                model_def = definition
                break

        return ComponentModel(
            spice_type=SpiceType.BJT,
            model_name=model_name,
            num_terminals=3,
            pin_order=['C', 'B', 'E'],  # Collector, Base, Emitter
            default_params={},
            model_definition=model_def,
            ltspice_symbol='npn' if not is_pnp else 'pnp',
        )

    def _build_mosfet_model(self, component: Dict[str, Any]) -> ComponentModel:
        """Build model for MOSFET components."""
        value = component.get('value', '')
        comp_type = component.get('type', '').lower()
        value_upper = value.upper()

        # Determine N-ch or P-ch
        is_pmos = 'pmos' in comp_type or 'p-ch' in comp_type or 'IRF9' in value_upper

        # Find matching model
        model_name = 'IRF9540' if is_pmos else 'IRF540'
        model_def = self.MOSFET_MODELS.get(model_name, '')

        for name, definition in self.MOSFET_MODELS.items():
            if name.upper() in value_upper:
                model_name = name
                model_def = definition
                break

        return ComponentModel(
            spice_type=SpiceType.MOSFET,
            model_name=model_name,
            num_terminals=4,
            pin_order=['D', 'G', 'S', 'B'],  # Drain, Gate, Source, Body
            default_params={},
            model_definition=model_def,
            ltspice_symbol='nmos' if not is_pmos else 'pmos',
        )

    def _build_subcircuit_model(self, component: Dict[str, Any]) -> ComponentModel:
        """
        Build model for ICs and complex components using subcircuits.

        Fix K.4: Pin-count-aware behavioral model matching.
        When a known IC is matched by name, the model's pin count is compared
        with the component's actual pin count. If they differ, a pin-adapted
        wrapper subcircuit is generated that maps AI-generated pins to the
        behavioral model's canonical pins using fuzzy name matching.

        Fix K.6: Connector components get a passthrough subcircuit where
        each pin is an independent node (no internal connections).
        """
        value = component.get('value', '')
        pins = component.get('pins', [])
        comp_type = component.get('type', '').lower()
        value_upper = value.upper()

        # Fix K.6: Connector passthrough — each pin is independent
        if comp_type in config.CONNECTOR_TYPES:
            return self._build_connector_passthrough(component)

        # Determine subcircuit based on value/part number
        subckt_name = value.replace('-', '_').replace('.', '_')
        subckt_def = None
        model_pin_map = None  # Canonical pin list from config

        # Check for known op-amps / behavioral models
        for name, definition in self.OPAMP_SUBCIRCUITS.items():
            if name.upper() in value_upper:
                subckt_name = name
                subckt_def = definition
                model_pin_map = config.BEHAVIORAL_MODEL_PIN_MAP.get(name)
                # M.3 FIX: Generic fallback — strip voltage/package suffix to find base entry
                # Handles AMS1117-3.3 (voltage), LM7805CT (package), TPS54331D (package)
                if model_pin_map is None:
                    base_name = re.sub(r'[-_]\d+[.\d]*$', '', name)
                    model_pin_map = config.BEHAVIORAL_MODEL_PIN_MAP.get(base_name)
                # R-series: Also try stripping trailing letter package codes (CT, D, N, etc.)
                if model_pin_map is None:
                    base_name = re.sub(r'[A-Z]{1,3}$', '', name)
                    if base_name and base_name != name:
                        model_pin_map = config.BEHAVIORAL_MODEL_PIN_MAP.get(base_name)
                break

        # Check for known voltage regulators
        if not subckt_def:
            for name, definition in self.REGULATOR_SUBCIRCUITS.items():
                if name.upper().replace('-', '') in value_upper.replace('-', ''):
                    subckt_name = name
                    subckt_def = definition
                    model_pin_map = config.BEHAVIORAL_MODEL_PIN_MAP.get(name)
                    # M.3 FIX: Generic fallback for regulators too
                    if model_pin_map is None:
                        base_name = re.sub(r'[-_]\d+[.\d]*$', '', name)
                        model_pin_map = config.BEHAVIORAL_MODEL_PIN_MAP.get(base_name)
                    # R-series: Also try stripping trailing letter package codes
                    if model_pin_map is None:
                        base_name = re.sub(r'[A-Z]{1,3}$', '', name)
                        if base_name and base_name != name:
                            model_pin_map = config.BEHAVIORAL_MODEL_PIN_MAP.get(base_name)
                    break

        # Y.4 FIX: Apply spice_safe_name() to subckt_name ONCE, so the name
        # is consistent in BOTH the .subckt definition AND the X instance call.
        # Without this, AMS1117-3.3 becomes AMS1117_3.3 in the instance (via
        # netlist_generator's sanitize) but stays AMS1117-3.3 in the .subckt
        # definition → "unknown subckt" SPICE error.
        subckt_name = spice_safe_name(subckt_name)

        # Fix K.4: If we found a behavioral model, check pin count compatibility
        if subckt_def and model_pin_map:
            model_pin_count = len(model_pin_map)
            comp_pin_count = len(pins)

            if model_pin_count != comp_pin_count:
                # Pin count mismatch — build an adapted wrapper
                subckt_def = self._build_pin_adapted_wrapper(
                    subckt_name, subckt_def, model_pin_map, pins
                )
                # Use a wrapper name to avoid conflict with the inner model
                subckt_name = f"{subckt_name}_ADAPTED"

        # If no known subcircuit, create a generic placeholder
        if not subckt_def:
            pin_names = [(p.get('name') or p.get('number') or str(i+1)) for i, p in enumerate(pins)]
            subckt_def = self._create_generic_subcircuit(subckt_name, pin_names)

        return ComponentModel(
            spice_type=SpiceType.SUBCIRCUIT,
            model_name=subckt_name,
            num_terminals=len(pins),
            pin_order=[p.get('number', str(i+1)) for i, p in enumerate(pins)],
            default_params={},
            model_definition=subckt_def,
            ltspice_symbol=None,
        )

    def _build_connector_passthrough(self, component: Dict[str, Any]) -> ComponentModel:
        """
        Fix K.6: Build a passthrough subcircuit for connectors.

        Each pin is an independent node with no internal connections to other
        pins. This prevents the old 0.001-ohm model from shorting power rails
        on multi-pin connectors (RJ45, barrel jacks, etc.).
        """
        pins = component.get('pins', [])
        value = component.get('value', 'CONN')
        # V.4 FIX: Use canonical spice_safe_name() for consistent Unicode handling
        clean_name = spice_safe_name(value)
        subckt_name = f"CONN_{clean_name}"

        pin_names = [(p.get('name') or p.get('number') or str(i + 1)) for i, p in enumerate(pins)]
        unique_pins = self._deduplicate_pin_names(pin_names)
        pins_str = ' '.join(unique_pins)

        # Each pin gets a high-impedance pull to a common internal node
        # (prevents floating node warnings without creating shorts)
        internals = []
        for i, pname in enumerate(unique_pins):
            internals.append(f"R{i + 1} {pname} _CONN_INT 100MEG")

        internals_str = '\n'.join(internals) if internals else "* Empty connector"

        subckt_def = f'''
.subckt {subckt_name} {pins_str}
* Connector passthrough - each pin is independent
{internals_str}
.ends {subckt_name}'''

        return ComponentModel(
            spice_type=SpiceType.SUBCIRCUIT,
            model_name=subckt_name,
            num_terminals=len(pins),
            pin_order=[p.get('number', str(i + 1)) for i, p in enumerate(pins)],
            default_params={},
            model_definition=subckt_def,
            ltspice_symbol=None,
        )

    def _build_pin_adapted_wrapper(
        self,
        model_name: str,
        original_def: str,
        model_pins: List[str],
        component_pins: List[Dict],
    ) -> str:
        """
        Fix K.4: Build a wrapper subcircuit that adapts component pins to
        the behavioral model's canonical pin list.

        When the AI defines an IC with more or fewer pins than the behavioral
        model expects, this wrapper:
        1. Maps matching pin names (fuzzy) from component → model
        2. Ties unmatched model pins to internal NC nodes
        3. Ties extra component pins to high-impedance stubs

        Returns the complete SPICE definition (inner model + wrapper).
        """
        comp_pin_names = [
            (p.get('name') or p.get('number') or str(i + 1))
            for i, p in enumerate(component_pins)
        ]
        unique_comp_pins = self._deduplicate_pin_names(comp_pin_names)

        # Build fuzzy mapping: component pin → model pin
        comp_to_model = {}
        used_model_pins = set()

        # Pass 1: Exact match (case-insensitive)
        for i, cpin in enumerate(unique_comp_pins):
            cpin_upper = cpin.upper()
            for mpin in model_pins:
                if mpin.upper() == cpin_upper and mpin not in used_model_pins:
                    comp_to_model[cpin] = mpin
                    used_model_pins.add(mpin)
                    break

        # Pass 2: Substring match for unmatched pins
        for i, cpin in enumerate(unique_comp_pins):
            if cpin in comp_to_model:
                continue
            cpin_norm = cpin.upper().replace('_', '')
            for mpin in model_pins:
                if mpin in used_model_pins:
                    continue
                mpin_norm = mpin.upper().replace('_', '')
                if cpin_norm in mpin_norm or mpin_norm in cpin_norm:
                    comp_to_model[cpin] = mpin
                    used_model_pins.add(mpin)
                    break

        # Build wrapper subcircuit
        wrapper_name = f"{model_name}_ADAPTED"
        wrapper_pins_str = ' '.join(unique_comp_pins)

        # Internal nodes for model connection
        internal_lines = []
        model_connections = []
        nc_count = 0

        for mpin in model_pins:
            if mpin in used_model_pins:
                # Find which component pin maps to this
                for cpin, mapped_mpin in comp_to_model.items():
                    if mapped_mpin == mpin:
                        model_connections.append(cpin)
                        break
            else:
                # Unmatched model pin → internal NC node
                nc_count += 1
                nc_node = f"_NC_{nc_count}"
                model_connections.append(nc_node)
                internal_lines.append(f"R_NC{nc_count} {nc_node} 0 100MEG")

        # Extra component pins not in the model → stub to ground via 100MEG
        stub_count = 0
        for cpin in unique_comp_pins:
            if cpin not in comp_to_model:
                stub_count += 1
                internal_lines.append(f"R_STUB{stub_count} {cpin} 0 100MEG")

        model_conn_str = ' '.join(model_connections)
        internals = '\n'.join(internal_lines)

        return f'''{original_def}

.subckt {wrapper_name} {wrapper_pins_str}
* Pin-adapted wrapper for {model_name} (Fix K.4)
* Maps {len(unique_comp_pins)} component pins to {len(model_pins)} model pins
X_INNER {model_conn_str} {model_name}
{internals}
.ends {wrapper_name}'''

    def _build_generic_model(self, component: Dict[str, Any]) -> ComponentModel:
        """Build a generic model for unknown component types."""
        pins = component.get('pins', [])
        ref = component.get('ref', 'X')
        value = component.get('value', 'UNKNOWN')

        # V.4 FIX: Use canonical spice_safe_name() for consistent Unicode handling
        subckt_name = f"GENERIC_{spice_safe_name(value)}"
        pin_names = [(p.get('name') or str(i+1)) for i, p in enumerate(pins)]
        subckt_def = self._create_generic_subcircuit(subckt_name, pin_names)

        return ComponentModel(
            spice_type=SpiceType.SUBCIRCUIT,
            model_name=subckt_name,
            num_terminals=len(pins),
            pin_order=[str(i+1) for i in range(len(pins))],
            default_params={},
            model_definition=subckt_def,
            ltspice_symbol=None,
        )

    @staticmethod
    def _deduplicate_pin_names(pin_names: List[str]) -> List[str]:
        """
        Fix K.7: Ensure all pin names in a subcircuit are unique.

        SPICE subcircuit declarations require unique node names.
        Duplicate names (e.g., 4x SOURCE on a VIPER22A) are disambiguated
        by appending _2, _3, etc.

        Also sanitizes names to contain only SPICE-safe characters.
        """
        seen = {}
        unique = []
        for name in pin_names:
            # Sanitize: SPICE node names must be alphanumeric + underscore
            clean = re.sub(r'[^A-Za-z0-9_]', '_', name) if name else 'PIN'
            if not clean or clean[0].isdigit():
                clean = f'P{clean}'

            if clean in seen:
                seen[clean] += 1
                unique.append(f"{clean}_{seen[clean]}")
            else:
                seen[clean] = 1
                unique.append(clean)
        return unique

    def _create_generic_subcircuit(self, name: str, pin_names: List[str]) -> str:
        """
        Create a generic subcircuit definition for unknown ICs.

        This creates a behavioral model that:
        - Has high impedance between all pins
        - Doesn't affect circuit behavior significantly
        - Allows simulation to proceed

        Fix K.7: Pin names are deduplicated before use to prevent SPICE
        syntax errors from components with repeated pin function names
        (e.g., VIPER22A with 4x SOURCE, 3x DRAIN).

        Parameters
        ----------
        name : str
            Subcircuit name
        pin_names : List[str]
            List of pin names (may contain duplicates)

        Returns
        -------
        str
            SPICE subcircuit definition with unique node names
        """
        # V.4 FIX: Use canonical spice_safe_name() for consistent Unicode handling
        clean_name = spice_safe_name(name)
        unique_pins = self._deduplicate_pin_names(pin_names)
        pins_str = ' '.join(unique_pins)

        # Create high-impedance resistors between adjacent pins
        resistors = []
        for i in range(len(unique_pins) - 1):
            resistors.append(f"R{i+1} {unique_pins[i]} {unique_pins[i+1]} 10MEG")
        resistors_str = '\n'.join(resistors) if resistors else "* No internal connections"

        # Add pin name comment for traceability
        pin_comment_parts = [f"* Pin {i+1} = {pin_names[i]}" for i in range(len(pin_names))]
        pin_comments = '\n'.join(pin_comment_parts)

        return f'''
.subckt {clean_name} {pins_str}
* Generic placeholder for {name}
* WARNING: This is a stub - actual behavior not modeled
{pin_comments}
{resistors_str}
.ends {clean_name}'''

    def get_all_required_models(self, components: List[Dict[str, Any]]) -> str:
        """
        Get all SPICE model definitions required for a list of components.

        Parameters
        ----------
        components : List[Dict[str, Any]]
            List of component dicts from CopperPilot JSON

        Returns
        -------
        str
            SPICE model and subcircuit definitions
        """
        models_needed = set()
        subcircuits_needed = set()

        for comp in components:
            model = self.get_model(comp)
            if model.model_definition:
                if model.spice_type == SpiceType.SUBCIRCUIT:
                    subcircuits_needed.add(model.model_definition)
                else:
                    models_needed.add(model.model_definition)

        result = []

        if models_needed:
            result.append("* Component Models")
            result.extend(sorted(models_needed))

        if subcircuits_needed:
            result.append("\n* Subcircuit Definitions")
            result.extend(sorted(subcircuits_needed))

        return '\n'.join(result)

    def add_custom_model(self, name: str, definition: str) -> None:
        """
        Add a custom model definition to the library.

        Parameters
        ----------
        name : str
            Model name
        definition : str
            SPICE .model definition
        """
        self._custom_models[name.upper()] = definition

    def add_custom_subcircuit(self, name: str, definition: str) -> None:
        """
        Add a custom subcircuit definition to the library.

        Parameters
        ----------
        name : str
            Subcircuit name
        definition : str
            SPICE .subckt definition
        """
        self._custom_subcircuits[name.upper()] = definition


# =============================================================================
# MODULE-LEVEL CONVENIENCE FUNCTIONS
# =============================================================================

def get_spice_type(component_type: str) -> SpiceType:
    """Convenience function to get SPICE type without instantiating library."""
    return SpiceModelLibrary().get_spice_type(component_type)


def parse_value(value_str: str) -> Tuple[float, str]:
    """Convenience function to parse component value."""
    return SpiceModelLibrary().parse_value(value_str)
