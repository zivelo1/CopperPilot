# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Requirements Rating Extractor Module
=====================================
Extracts electrical specifications from user requirements text.

This module is GENERIC and works with ANY type of circuit requirements:
- Simple LED blinkers (5V, 20mA)
- Audio amplifiers (50V, 100W)
- High-voltage power supplies (400V, 1000W)
- Motor drivers (48V, 50A)
- RF circuits (MHz frequencies)
- Any other electronic system

The extracted specifications are used to:
1. Guide the AI in Step 3 component selection
2. Validate component ratings after circuit generation
3. Calculate power budgets and thermal requirements

Author: CopperPilot
Date: December 2025
"""

import re
import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path

from utils.logger import setup_logger

logger = setup_logger(__name__)


# =============================================================================
# DATA CLASSES FOR EXTRACTED SPECIFICATIONS
# =============================================================================

@dataclass
class VoltageSpec:
    """Represents a voltage specification extracted from requirements."""
    value: float  # In volts
    unit: str  # V, mV, kV
    type: str  # 'dc', 'ac', 'peak', 'rms', 'pp' (peak-to-peak)
    context: str  # Where this was found (e.g., 'output voltage', 'supply')
    raw_text: str  # Original text that was parsed

    def get_peak_voltage(self) -> float:
        """Convert to peak voltage for component rating calculations."""
        if self.type == 'pp':
            return self.value / 2  # Vpp to Vpeak
        elif self.type == 'rms':
            return self.value * 1.414  # Vrms to Vpeak
        return self.value


@dataclass
class CurrentSpec:
    """Represents a current specification extracted from requirements."""
    value: float  # In amperes
    unit: str  # A, mA, uA
    type: str  # 'dc', 'ac', 'peak', 'rms', 'average'
    context: str
    raw_text: str


@dataclass
class PowerSpec:
    """Represents a power specification extracted from requirements."""
    value: float  # In watts
    unit: str  # W, mW, kW
    type: str  # 'average', 'peak', 'continuous', 'pulsed'
    context: str
    raw_text: str


@dataclass
class FrequencySpec:
    """Represents a frequency specification extracted from requirements."""
    value: float  # In Hz
    unit: str  # Hz, kHz, MHz, GHz
    type: str  # 'operating', 'switching', 'bandwidth', 'resonant'
    context: str
    raw_text: str


@dataclass
class ExtractedRequirements:
    """
    Complete set of extracted electrical requirements.

    This is GENERIC and represents requirements for ANY circuit type.
    Not all fields will be populated for every circuit.
    """
    voltages: List[VoltageSpec] = field(default_factory=list)
    currents: List[CurrentSpec] = field(default_factory=list)
    powers: List[PowerSpec] = field(default_factory=list)
    frequencies: List[FrequencySpec] = field(default_factory=list)

    # Derived values for component selection
    max_voltage: float = 0.0  # Maximum voltage in system (V)
    max_current: float = 0.0  # Maximum current in system (A)
    max_power: float = 0.0  # Maximum power in system (W)
    max_frequency: float = 0.0  # Maximum frequency in system (Hz)

    # Recommended component ratings (with safety margins)
    recommended_voltage_rating: float = 0.0  # Minimum Vds/Vce for semiconductors
    recommended_current_rating: float = 0.0  # Minimum Id/Ic for semiconductors
    recommended_power_rating: float = 0.0  # Minimum power for resistors/transistors

    # Context
    circuit_type: str = "general"  # Inferred circuit type
    voltage_class: str = "low"  # 'low' (<50V), 'medium' (50-250V), 'high' (>250V)
    power_class: str = "low"  # 'low' (<10W), 'medium' (10-100W), 'high' (>100W)
    frequency_class: str = "low"  # 'low' (<100kHz), 'medium' (100kHz-10MHz), 'high' (>10MHz)

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'voltages': [asdict(v) for v in self.voltages],
            'currents': [asdict(c) for c in self.currents],
            'powers': [asdict(p) for p in self.powers],
            'frequencies': [asdict(f) for f in self.frequencies],
            'max_voltage': self.max_voltage,
            'max_current': self.max_current,
            'max_power': self.max_power,
            'max_frequency': self.max_frequency,
            'recommended_voltage_rating': self.recommended_voltage_rating,
            'recommended_current_rating': self.recommended_current_rating,
            'recommended_power_rating': self.recommended_power_rating,
            'circuit_type': self.circuit_type,
            'voltage_class': self.voltage_class,
            'power_class': self.power_class,
            'frequency_class': self.frequency_class,
        }


# =============================================================================
# GENERIC PATTERN MATCHERS
# =============================================================================

class RequirementsRatingExtractor:
    """
    Extracts electrical specifications from requirements text.

    This class uses regex patterns to find voltage, current, power, and
    frequency specifications in ANY format of requirements text.

    It is designed to be:
    - GENERIC: Works with any circuit type
    - ROBUST: Handles various text formats
    - EXTENSIBLE: Easy to add new patterns
    """

    # ==========================================================================
    # VOLTAGE PATTERNS - Match various voltage specifications
    # ==========================================================================
    VOLTAGE_PATTERNS = [
        # Peak-to-peak: "360 Vpp", "360Vpp", "360 V p-p"
        (r'(\d+(?:\.\d+)?)\s*(?:V|v)(?:pp|PP|p-p|P-P)', 'pp'),
        # Peak: "180 Vpk", "180Vpeak", "180 V peak"
        (r'(\d+(?:\.\d+)?)\s*(?:V|v)(?:pk|PK|peak|PEAK)', 'peak'),
        # RMS: "120 Vrms", "120VRMS", "120 V rms"
        (r'(\d+(?:\.\d+)?)\s*(?:V|v)(?:rms|RMS)', 'rms'),
        # AC: "120 VAC", "120Vac", "120 V AC"
        (r'(\d+(?:\.\d+)?)\s*(?:V|v)(?:ac|AC)', 'ac'),
        # DC: "12 VDC", "12Vdc", "12 V DC"
        (r'(\d+(?:\.\d+)?)\s*(?:V|v)(?:dc|DC)', 'dc'),
        # Kilovolts: "1.5 kV", "1.5kV"
        (r'(\d+(?:\.\d+)?)\s*(?:kV|KV|kv)', 'dc'),  # Assume DC for kV
        # Millivolts: "500 mV", "500mV"
        (r'(\d+(?:\.\d+)?)\s*(?:mV|mv)', 'dc'),
        # Generic volts: "12V", "12 V", "12 volts"
        (r'(\d+(?:\.\d+)?)\s*(?:V|v|volts?|VOLTS?)\b', 'dc'),
    ]

    # ==========================================================================
    # CURRENT PATTERNS - Match various current specifications
    # ==========================================================================
    CURRENT_PATTERNS = [
        # Milliamps: "200 mA", "200mA"
        (r'(\d+(?:\.\d+)?)\s*(?:mA|ma)', 'mA'),
        # Microamps: "100 uA", "100µA"
        (r'(\d+(?:\.\d+)?)\s*(?:uA|µA|ua)', 'uA'),
        # Amps: "5 A", "5A", "5 amps"
        (r'(\d+(?:\.\d+)?)\s*(?:A|amps?|AMPS?)\b', 'A'),
    ]

    # ==========================================================================
    # POWER PATTERNS - Match various power specifications
    # ==========================================================================
    POWER_PATTERNS = [
        # Kilowatts: "1.5 kW", "1.5kW"
        (r'(\d+(?:\.\d+)?)\s*(?:kW|KW|kw)', 'kW'),
        # Milliwatts: "500 mW", "500mW"
        (r'(\d+(?:\.\d+)?)\s*(?:mW|mw)', 'mW'),
        # Watts: "200 W", "200W", "200 watts"
        (r'(\d+(?:\.\d+)?)\s*(?:W|w|watts?|WATTS?)\b', 'W'),
    ]

    # ==========================================================================
    # FREQUENCY PATTERNS - Match various frequency specifications
    # ==========================================================================
    FREQUENCY_PATTERNS = [
        # Gigahertz: "2.4 GHz", "2.4GHz"
        (r'(\d+(?:\.\d+)?)\s*(?:GHz|Ghz|ghz|GHZ)', 'GHz'),
        # Megahertz: "1.5 MHz", "1.5MHz"
        (r'(\d+(?:\.\d+)?)\s*(?:MHz|Mhz|mhz|MHZ)', 'MHz'),
        # Kilohertz: "50 kHz", "50KHz", "50 KHz"
        (r'(\d+(?:\.\d+)?)\s*(?:kHz|KHz|khz|KHZ)', 'kHz'),
        # Hertz: "60 Hz", "60Hz"
        (r'(\d+(?:\.\d+)?)\s*(?:Hz|hz|HZ)', 'Hz'),
    ]

    # ==========================================================================
    # CONTEXT PATTERNS - Identify what a specification relates to
    # ==========================================================================
    CONTEXT_PATTERNS = {
        'output': r'output|out|drive|deliver|produce|generate',
        'input': r'input|in|supply|source|receive',
        'power_supply': r'power\s*supply|psu|mains|ac\s*input',
        'operating': r'operat|work|run|function',
        'maximum': r'max|maximum|peak|up\s*to',
        'minimum': r'min|minimum|at\s*least',
    }

    def __init__(self):
        """Initialize the extractor."""
        self.extracted = ExtractedRequirements()

    def extract(self, requirements_text: str) -> ExtractedRequirements:
        """
        Extract all electrical specifications from requirements text.

        This is the main entry point. It:
        1. Extracts voltages, currents, powers, frequencies
        2. Calculates maximum values
        3. Applies derating rules for recommended component ratings
        4. Classifies the circuit type

        Args:
            requirements_text: Raw requirements text (can be from PDF, user input, etc.)

        Returns:
            ExtractedRequirements with all specifications and recommendations
        """
        logger.info("Extracting electrical specifications from requirements")

        self.extracted = ExtractedRequirements()

        # Normalize text for parsing
        text = self._normalize_text(requirements_text)

        # Extract each type of specification
        self._extract_voltages(text)
        self._extract_currents(text)
        self._extract_powers(text)
        self._extract_frequencies(text)

        # Calculate maximums and recommendations
        self._calculate_maximums()
        self._apply_derating_rules()
        self._classify_circuit()

        logger.info(f"Extracted: {len(self.extracted.voltages)} voltages, "
                   f"{len(self.extracted.currents)} currents, "
                   f"{len(self.extracted.powers)} powers, "
                   f"{len(self.extracted.frequencies)} frequencies")
        logger.info(f"Max voltage: {self.extracted.max_voltage}V, "
                   f"Recommended rating: {self.extracted.recommended_voltage_rating}V")

        return self.extracted

    def _normalize_text(self, text: str) -> str:
        """Normalize text for parsing."""
        # Replace various dash types with standard hyphen
        text = text.replace('–', '-').replace('—', '-')
        # Normalize whitespace
        text = ' '.join(text.split())
        return text

    def _extract_voltages(self, text: str) -> None:
        """Extract voltage specifications from text."""
        for pattern, v_type in self.VOLTAGE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = float(match.group(1))

                # Convert to volts
                if 'kV' in match.group(0) or 'KV' in match.group(0):
                    value *= 1000
                elif 'mV' in match.group(0) or 'mv' in match.group(0):
                    value /= 1000

                # Get context (surrounding text)
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context_text = text[start:end]
                context = self._determine_context(context_text)

                spec = VoltageSpec(
                    value=value,
                    unit='V',
                    type=v_type,
                    context=context,
                    raw_text=match.group(0)
                )
                self.extracted.voltages.append(spec)

    def _extract_currents(self, text: str) -> None:
        """Extract current specifications from text."""
        for pattern, unit in self.CURRENT_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = float(match.group(1))

                # Convert to amps
                if unit == 'mA':
                    value_amps = value / 1000
                elif unit == 'uA':
                    value_amps = value / 1000000
                else:
                    value_amps = value

                # Get context
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context_text = text[start:end]
                context = self._determine_context(context_text)

                spec = CurrentSpec(
                    value=value_amps,
                    unit='A',
                    type='dc',
                    context=context,
                    raw_text=match.group(0)
                )
                self.extracted.currents.append(spec)

    def _extract_powers(self, text: str) -> None:
        """Extract power specifications from text."""
        for pattern, unit in self.POWER_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = float(match.group(1))

                # Convert to watts
                if unit == 'kW':
                    value_watts = value * 1000
                elif unit == 'mW':
                    value_watts = value / 1000
                else:
                    value_watts = value

                # Get context
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context_text = text[start:end]
                context = self._determine_context(context_text)

                spec = PowerSpec(
                    value=value_watts,
                    unit='W',
                    type='average',
                    context=context,
                    raw_text=match.group(0)
                )
                self.extracted.powers.append(spec)

    def _extract_frequencies(self, text: str) -> None:
        """Extract frequency specifications from text."""
        for pattern, unit in self.FREQUENCY_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = float(match.group(1))

                # Convert to Hz
                if unit == 'GHz':
                    value_hz = value * 1e9
                elif unit == 'MHz':
                    value_hz = value * 1e6
                elif unit == 'kHz':
                    value_hz = value * 1e3
                else:
                    value_hz = value

                # Get context
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context_text = text[start:end]
                context = self._determine_context(context_text)

                spec = FrequencySpec(
                    value=value_hz,
                    unit='Hz',
                    type='operating',
                    context=context,
                    raw_text=match.group(0)
                )
                self.extracted.frequencies.append(spec)

    def _determine_context(self, surrounding_text: str) -> str:
        """Determine the context of a specification from surrounding text."""
        surrounding_lower = surrounding_text.lower()

        for context_name, pattern in self.CONTEXT_PATTERNS.items():
            if re.search(pattern, surrounding_lower):
                return context_name

        return 'general'

    def _calculate_maximums(self) -> None:
        """Calculate maximum values from all extracted specifications."""
        # Maximum voltage for component selection
        # For power stage design, we need to consider what components actually see:
        # - Vpp (peak-to-peak): Full-bridge MOSFETs see ~Vpp, half-bridge see Vpp/2
        #   Use Vpp directly for conservative rating (full-bridge assumption)
        # - Vrms: Convert to peak for rating
        # - DC: Use as-is
        if self.extracted.voltages:
            peak_voltages = []
            for v in self.extracted.voltages:
                if v.type == 'pp':
                    # For full-bridge/H-bridge designs, MOSFETs see full rail-to-rail
                    # Use full Vpp for conservative component selection
                    peak_voltages.append(v.value)
                elif v.type == 'rms':
                    peak_voltages.append(v.value * 1.414)  # Vrms to Vpeak
                else:
                    peak_voltages.append(v.value)
            self.extracted.max_voltage = max(peak_voltages)

        # Maximum current
        if self.extracted.currents:
            self.extracted.max_current = max(c.value for c in self.extracted.currents)

        # Maximum power
        if self.extracted.powers:
            self.extracted.max_power = max(p.value for p in self.extracted.powers)

        # If power not specified but V and I are, calculate it
        if self.extracted.max_power == 0 and self.extracted.max_voltage > 0 and self.extracted.max_current > 0:
            self.extracted.max_power = self.extracted.max_voltage * self.extracted.max_current

        # Maximum frequency
        if self.extracted.frequencies:
            self.extracted.max_frequency = max(f.value for f in self.extracted.frequencies)

    def _apply_derating_rules(self) -> None:
        """
        Apply standard derating rules for component selection.

        These rules are GENERIC and apply to ANY circuit:
        - Voltage: Components should be rated 1.5-2x the working voltage
        - Current: Components should be rated 1.5-2x the working current
        - Power: Components should be rated 2x the dissipated power

        These are industry-standard derating guidelines.
        """
        # Voltage derating: 1.5x for low voltage, 2x for high voltage
        if self.extracted.max_voltage > 0:
            if self.extracted.max_voltage > 100:
                # High voltage - use 2x derating
                self.extracted.recommended_voltage_rating = self.extracted.max_voltage * 2.0
            else:
                # Low voltage - use 1.5x derating
                self.extracted.recommended_voltage_rating = self.extracted.max_voltage * 1.5

        # Current derating: 1.5x for continuous operation
        if self.extracted.max_current > 0:
            self.extracted.recommended_current_rating = self.extracted.max_current * 1.5

        # Power derating: 2x for thermal margin
        if self.extracted.max_power > 0:
            self.extracted.recommended_power_rating = self.extracted.max_power * 2.0

    def _classify_circuit(self) -> None:
        """
        Classify the circuit type based on extracted specifications.

        This helps the AI select appropriate component types and topologies.
        """
        # Voltage classification
        if self.extracted.max_voltage > 250:
            self.extracted.voltage_class = 'high'
        elif self.extracted.max_voltage > 50:
            self.extracted.voltage_class = 'medium'
        else:
            self.extracted.voltage_class = 'low'

        # Power classification
        if self.extracted.max_power > 100:
            self.extracted.power_class = 'high'
        elif self.extracted.max_power > 10:
            self.extracted.power_class = 'medium'
        else:
            self.extracted.power_class = 'low'

        # Frequency classification
        if self.extracted.max_frequency > 10e6:  # > 10 MHz
            self.extracted.frequency_class = 'high'
        elif self.extracted.max_frequency > 100e3:  # > 100 kHz
            self.extracted.frequency_class = 'medium'
        else:
            self.extracted.frequency_class = 'low'

        # Infer circuit type (generic categories)
        if self.extracted.voltage_class == 'high' or self.extracted.power_class == 'high':
            self.extracted.circuit_type = 'power_electronics'
        elif self.extracted.frequency_class == 'high':
            self.extracted.circuit_type = 'rf_high_frequency'
        elif self.extracted.max_power > 0:
            self.extracted.circuit_type = 'amplifier_driver'
        else:
            self.extracted.circuit_type = 'general_purpose'

    def get_component_guidance(self) -> str:
        """
        Generate component selection guidance text for the AI.

        This is injected into the Step 3 prompt to guide component selection.

        Returns:
            Formatted guidance text based on extracted requirements.
        """
        guidance = []

        guidance.append("## COMPONENT RATING REQUIREMENTS (AUTO-EXTRACTED)")
        guidance.append("")

        if self.extracted.max_voltage > 0:
            guidance.append(f"### Voltage Requirements")
            guidance.append(f"- Maximum system voltage: {self.extracted.max_voltage:.1f}V")
            guidance.append(f"- **REQUIRED minimum voltage rating for MOSFETs/transistors: {self.extracted.recommended_voltage_rating:.0f}V**")
            guidance.append(f"- **REQUIRED minimum voltage rating for capacitors: {self.extracted.recommended_voltage_rating:.0f}V**")
            guidance.append("")

        if self.extracted.max_current > 0:
            guidance.append(f"### Current Requirements")
            guidance.append(f"- Maximum system current: {self.extracted.max_current:.2f}A")
            guidance.append(f"- **REQUIRED minimum current rating for MOSFETs/transistors: {self.extracted.recommended_current_rating:.2f}A**")
            guidance.append("")

        if self.extracted.max_power > 0:
            guidance.append(f"### Power Requirements")
            guidance.append(f"- Maximum system power: {self.extracted.max_power:.1f}W")
            guidance.append(f"- **REQUIRED minimum power handling: {self.extracted.recommended_power_rating:.1f}W**")
            guidance.append("")

        if self.extracted.max_frequency > 0:
            freq_str = self._format_frequency(self.extracted.max_frequency)
            guidance.append(f"### Frequency Requirements")
            guidance.append(f"- Maximum operating frequency: {freq_str}")
            if self.extracted.frequency_class == 'high':
                guidance.append(f"- **Use RF-rated components with fast switching times**")
            guidance.append("")

        # Add voltage class specific guidance
        if self.extracted.voltage_class == 'high':
            guidance.append("### ⚠️ HIGH VOLTAGE DESIGN - CRITICAL COMPONENT SELECTION")
            guidance.append("- Use MOSFETs rated for 500V+ (e.g., IRFP450, STW34NM60, IPP60R099C6)")
            guidance.append("- Use capacitors rated for 400V+ for high voltage rails")
            guidance.append("- Include proper isolation and safety features")
            guidance.append("- Consider half-bridge or full-bridge topologies for high power")
            guidance.append("")
        elif self.extracted.voltage_class == 'medium':
            guidance.append("### MEDIUM VOLTAGE DESIGN")
            guidance.append("- Use MOSFETs rated for 100V+ (e.g., IRFZ44N, IRF540)")
            guidance.append("- Use capacitors rated for 100V+ for power rails")
            guidance.append("")

        # Add power class specific guidance
        if self.extracted.power_class == 'high':
            guidance.append("### ⚠️ HIGH POWER DESIGN - THERMAL CONSIDERATIONS")
            guidance.append("- Include heatsinks for power semiconductors")
            guidance.append("- Use low Rds(on) MOSFETs to minimize losses")
            guidance.append("- Consider thermal shutdown protection")
            guidance.append("- Size power supply for total system load + margin")
            guidance.append("")

        return '\n'.join(guidance)

    def _format_frequency(self, freq_hz: float) -> str:
        """Format frequency for display."""
        if freq_hz >= 1e9:
            return f"{freq_hz/1e9:.2f} GHz"
        elif freq_hz >= 1e6:
            return f"{freq_hz/1e6:.2f} MHz"
        elif freq_hz >= 1e3:
            return f"{freq_hz/1e3:.2f} kHz"
        else:
            return f"{freq_hz:.2f} Hz"


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def extract_requirements_ratings(requirements_text: str) -> ExtractedRequirements:
    """
    Convenience function to extract ratings from requirements text.

    Args:
        requirements_text: Raw requirements text

    Returns:
        ExtractedRequirements object
    """
    extractor = RequirementsRatingExtractor()
    return extractor.extract(requirements_text)


def get_component_guidance_for_requirements(requirements_text: str) -> str:
    """
    Convenience function to get component guidance for a requirements text.

    Args:
        requirements_text: Raw requirements text

    Returns:
        Formatted guidance string for AI prompt injection
    """
    extractor = RequirementsRatingExtractor()
    extractor.extract(requirements_text)
    return extractor.get_component_guidance()


# =============================================================================
# CLI FOR TESTING
# =============================================================================

if __name__ == "__main__":
    # Test with sample requirements
    test_requirements = """
    Build a device with 2 ultrasonic transducers:
    - Channel 1: 50kHz, 360 Vpp, 200W output
    - Channel 2: 1.5MHz, 280 Vpp, 158W output
    Power input: 220V 60Hz
    """

    print("=" * 60)
    print("REQUIREMENTS RATING EXTRACTOR TEST")
    print("=" * 60)
    print(f"\nInput text:\n{test_requirements}")
    print("\n" + "=" * 60)

    extractor = RequirementsRatingExtractor()
    result = extractor.extract(test_requirements)

    print("\nExtracted Specifications:")
    print(f"  Voltages: {[(v.value, v.type) for v in result.voltages]}")
    print(f"  Powers: {[p.value for p in result.powers]}")
    print(f"  Frequencies: {[f.value for f in result.frequencies]}")

    print(f"\nCalculated Maximums:")
    print(f"  Max Voltage: {result.max_voltage}V")
    print(f"  Max Power: {result.max_power}W")
    print(f"  Max Frequency: {result.max_frequency}Hz")

    print(f"\nRecommended Ratings:")
    print(f"  Voltage Rating: {result.recommended_voltage_rating}V")
    print(f"  Power Rating: {result.recommended_power_rating}W")

    print(f"\nClassifications:")
    print(f"  Voltage Class: {result.voltage_class}")
    print(f"  Power Class: {result.power_class}")
    print(f"  Circuit Type: {result.circuit_type}")

    print("\n" + "=" * 60)
    print("GENERATED COMPONENT GUIDANCE:")
    print("=" * 60)
    print(extractor.get_component_guidance())
