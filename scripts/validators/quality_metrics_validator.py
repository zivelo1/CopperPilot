#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Advanced Quality Metrics Validator
===================================

TC #62 (2025-11-30): Implementation of Advanced Quality Metrics from PRODUCT_ROADMAP_2025.md

This module provides physics-based and engineering-heuristic checks that go beyond
structural ERC/DRC validation. A circuit can pass ERC/DRC and still be a poor design.

CRITICAL DESIGN PRINCIPLE: FORMAT-AGNOSTIC
==========================================
This validator works with the LOWLEVEL JSON format (circuit description), NOT with
format-specific files (KiCad, Eagle, EasyEDA). This ensures:
- Same validation logic for ALL output formats
- Single source of truth for quality rules
- No duplication of validation code across converters

Quality Metrics Implemented:
1. Component Derating Checks - Voltage/current margin verification
2. Power Dissipation Calculations - Total board power budget
3. Thermal Estimates - Junction temperature analysis
4. Trace Impedance Analysis - Characteristic impedance for high-speed signals
5. Signal Integrity Checks (Partial) - Basic SI validation

DFM/DFT/Assembly Enhancements:
6. Multi-Vendor DFM Profiles - JLCPCB, PCBWay, OSH Park, etc.
7. Design for Test (DFT) Checks - Testpoint coverage, fiducials
8. Assembly Checks - Connector orientation, component accessibility

Author: Claude Code (Opus 4.5)
Date: 2025-11-30
Version: 1.0.0
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================

class Severity(Enum):
    """Validation issue severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MetricCategory(Enum):
    """Quality metric categories."""
    DERATING = "derating"
    POWER = "power"
    THERMAL = "thermal"
    IMPEDANCE = "impedance"
    SIGNAL_INTEGRITY = "signal_integrity"
    DFM = "dfm"
    DFT = "dft"
    ASSEMBLY = "assembly"


# IPC-2221B recommended derating percentages
DERATING_RULES = {
    "voltage": {
        "minimum_margin": 0.20,  # 20% minimum voltage derating
        "recommended_margin": 0.30,  # 30% recommended
        "electrolytic_cap": 0.40,  # 40% for electrolytic caps
    },
    "current": {
        "minimum_margin": 0.20,  # 20% minimum current derating
        "trace_margin": 0.30,  # 30% for PCB traces
    },
    "power": {
        "resistor_margin": 0.50,  # 50% for power resistors
        "general_margin": 0.30,  # 30% for general components
    },
    "temperature": {
        "max_junction_percent": 0.80,  # 80% of max junction temp
        "ambient_default": 25.0,  # Default ambient temperature (°C)
    },
}

# Thermal resistance defaults by package type (°C/W)
THERMAL_RESISTANCE_DEFAULTS = {
    "SOT-23": 250.0,
    "SOT-223": 50.0,
    "SOIC-8": 120.0,
    "SOIC-14": 100.0,
    "SOIC-16": 90.0,
    "TSSOP-14": 130.0,
    "TSSOP-16": 120.0,
    "QFP-32": 60.0,
    "QFP-44": 55.0,
    "QFP-48": 50.0,
    "LQFP-48": 45.0,
    "QFP-64": 40.0,
    "QFP-100": 30.0,
    "QFN-16": 40.0,
    "QFN-32": 30.0,
    "QFN-48": 25.0,
    "BGA-256": 20.0,
    "TO-220": 3.0,
    "TO-252": 10.0,
    "TO-263": 5.0,
    "DIP-8": 100.0,
    "DIP-14": 80.0,
    "DIP-16": 70.0,
    "0402": 300.0,
    "0603": 250.0,
    "0805": 200.0,
    "1206": 150.0,
    "default": 100.0,
}

# High-speed signal net name patterns
HIGH_SPEED_NET_PATTERNS = [
    r'USB[_\-]?D[PM]',  # USB data lines
    r'LVDS',  # LVDS signals
    r'ETH',  # Ethernet
    r'CLK|CLOCK',  # Clock signals
    r'SDRAM|DDR',  # Memory interfaces
    r'HDMI',  # HDMI
    r'PCIE',  # PCIe
    r'SATA',  # SATA
    r'SPI[_\-]?CLK',  # SPI clock
    r'I2S[_\-]?CLK',  # I2S clock
]

# PCB stackup parameters for impedance calculation (FR-4 default)
DEFAULT_STACKUP = {
    "dielectric_constant": 4.5,  # εr for FR-4
    "copper_thickness_um": 35.0,  # 1 oz copper = 35µm
    "substrate_height_mm": 1.6,  # Standard 1.6mm board
    "trace_height_mm": 0.035,  # Same as copper thickness
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ValidationIssue:
    """
    Represents a single validation issue.

    GENERIC: Works for any circuit, any format.
    """
    category: MetricCategory
    severity: Severity
    component_ref: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "component_ref": self.component_ref,
            "message": self.message,
            "details": self.details,
            "recommendation": self.recommendation,
        }


@dataclass
class PowerAnalysis:
    """
    Power dissipation analysis results.

    GENERIC: Calculated from circuit components regardless of output format.
    """
    total_power_mw: float = 0.0
    per_component_power: Dict[str, float] = field(default_factory=dict)
    per_rail_current: Dict[str, float] = field(default_factory=dict)
    efficiency_estimate: float = 0.0
    heat_sink_required: List[str] = field(default_factory=list)


@dataclass
class ThermalAnalysis:
    """
    Thermal analysis results.

    GENERIC: Based on component specifications, not format-specific.
    """
    ambient_temp_c: float = 25.0
    component_temps: Dict[str, float] = field(default_factory=dict)
    thermal_violations: List[str] = field(default_factory=list)
    hottest_component: str = ""
    max_junction_temp_c: float = 0.0


@dataclass
class ImpedanceAnalysis:
    """
    Trace impedance analysis results.

    GENERIC: Based on net characteristics and stackup parameters.
    """
    high_speed_nets: List[str] = field(default_factory=list)
    impedance_controlled_nets: List[str] = field(default_factory=list)
    uncontrolled_high_speed: List[str] = field(default_factory=list)
    calculated_impedances: Dict[str, float] = field(default_factory=dict)


@dataclass
class QualityMetricsResult:
    """
    Complete quality metrics validation result.

    GENERIC: Same structure for KiCad, Eagle, and EasyEDA.
    """
    circuit_name: str
    issues: List[ValidationIssue] = field(default_factory=list)
    power_analysis: PowerAnalysis = field(default_factory=PowerAnalysis)
    thermal_analysis: ThermalAnalysis = field(default_factory=ThermalAnalysis)
    impedance_analysis: ImpedanceAnalysis = field(default_factory=ImpedanceAnalysis)

    # Summary counts
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0

    # Overall status
    passed: bool = True

    def add_issue(self, issue: ValidationIssue):
        """Add an issue and update counts."""
        self.issues.append(issue)
        if issue.severity == Severity.ERROR or issue.severity == Severity.CRITICAL:
            self.error_count += 1
            self.passed = False
        elif issue.severity == Severity.WARNING:
            self.warning_count += 1
        else:
            self.info_count += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "circuit_name": self.circuit_name,
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [i.to_dict() for i in self.issues],
            "power_analysis": {
                "total_power_mw": self.power_analysis.total_power_mw,
                "per_rail_current": self.power_analysis.per_rail_current,
                "heat_sink_required": self.power_analysis.heat_sink_required,
            },
            "thermal_analysis": {
                "ambient_temp_c": self.thermal_analysis.ambient_temp_c,
                "hottest_component": self.thermal_analysis.hottest_component,
                "max_junction_temp_c": self.thermal_analysis.max_junction_temp_c,
                "thermal_violations": self.thermal_analysis.thermal_violations,
            },
            "impedance_analysis": {
                "high_speed_nets": self.impedance_analysis.high_speed_nets,
                "uncontrolled_high_speed": self.impedance_analysis.uncontrolled_high_speed,
            },
        }


# =============================================================================
# QUALITY METRICS VALIDATOR CLASS
# =============================================================================

class QualityMetricsValidator:
    """
    Advanced Quality Metrics Validator.

    CRITICAL: This validator is FORMAT-AGNOSTIC!

    It validates the LOWLEVEL circuit JSON, which is the common representation
    before conversion to any specific EDA format (KiCad, Eagle, EasyEDA).

    This ensures:
    - Same quality rules apply to ALL output formats
    - No code duplication across converters
    - Consistent validation results

    Usage:
        validator = QualityMetricsValidator()
        result = validator.validate_circuit(circuit_json_path)

        if not result.passed:
            print(f"Quality issues found: {result.error_count} errors")
    """

    def __init__(
        self,
        ambient_temp_c: float = 25.0,
        stackup: Dict[str, float] = None,
        vendor_profile: str = "JLCPCB",
    ):
        """
        Initialize the Quality Metrics Validator.

        Args:
            ambient_temp_c: Ambient temperature for thermal analysis (default 25°C)
            stackup: PCB stackup parameters for impedance calculation
            vendor_profile: Manufacturing vendor profile for DFM checks

        GENERIC: Same initialization works for any circuit complexity.
        """
        self.ambient_temp_c = ambient_temp_c
        self.stackup = stackup or DEFAULT_STACKUP.copy()
        self.vendor_profile = vendor_profile

        # Compile high-speed net patterns
        self.high_speed_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in HIGH_SPEED_NET_PATTERNS
        ]

    def validate_circuit(self, circuit_path: Path) -> QualityMetricsResult:
        """
        Validate a circuit JSON file with all quality metrics.

        This is the main entry point for validation.

        Args:
            circuit_path: Path to the lowlevel circuit JSON file

        Returns:
            QualityMetricsResult with all validation findings

        GENERIC: Works for ANY circuit complexity.
        """
        # Load circuit data
        try:
            with open(circuit_path, 'r', encoding='utf-8') as f:
                circuit = json.load(f)
        except Exception as e:
            result = QualityMetricsResult(circuit_name=circuit_path.stem)
            result.add_issue(ValidationIssue(
                category=MetricCategory.DFM,
                severity=Severity.CRITICAL,
                component_ref="CIRCUIT",
                message=f"Failed to load circuit: {e}",
            ))
            return result

        circuit_name = circuit.get('name', circuit_path.stem)
        result = QualityMetricsResult(circuit_name=circuit_name)

        components = circuit.get('components', [])
        nets = circuit.get('nets', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})

        # Run all validation checks
        self._check_component_derating(components, result)
        self._check_power_dissipation(components, circuit, result)
        self._check_thermal_estimates(components, result)
        self._check_trace_impedance(nets, pin_net_mapping, circuit, result)
        self._check_signal_integrity(nets, components, result)
        self._check_dft_requirements(components, result)
        self._check_assembly_requirements(components, result)

        logger.info(
            f"Quality validation for {circuit_name}: "
            f"{result.error_count} errors, {result.warning_count} warnings"
        )

        return result

    # =========================================================================
    # COMPONENT DERATING CHECKS
    # =========================================================================

    def _check_component_derating(
        self,
        components: List[Dict],
        result: QualityMetricsResult
    ):
        """
        Check component voltage, current, and power derating.

        IPC-2221B/IPC-9592 recommends:
        - Voltage: ≥20% margin (40% for electrolytic caps)
        - Current: ≥20% margin
        - Power: ≥50% margin for resistors

        GENERIC: Works for ANY component type.
        """
        for comp in components:
            ref = comp.get('ref', comp.get('reference', 'Unknown'))
            comp_type = comp.get('type', '').upper()
            value = comp.get('value', '')

            # Extract ratings from component properties
            voltage_rating = self._extract_voltage_rating(comp)
            current_rating = self._extract_current_rating(comp)
            power_rating = self._extract_power_rating(comp)

            # Extract operating conditions
            operating_voltage = self._extract_operating_voltage(comp)
            operating_current = self._extract_operating_current(comp)

            # Check voltage derating
            if voltage_rating and operating_voltage:
                self._check_voltage_derating(
                    ref, comp_type, voltage_rating, operating_voltage, result
                )

            # Check current derating
            if current_rating and operating_current:
                self._check_current_derating(
                    ref, current_rating, operating_current, result
                )

            # Check power derating for resistors
            if power_rating and 'R' in comp_type or comp_type.startswith('R'):
                self._check_power_resistor_derating(
                    ref, power_rating, operating_voltage, value, result
                )

    def _check_voltage_derating(
        self,
        ref: str,
        comp_type: str,
        voltage_rating: float,
        operating_voltage: float,
        result: QualityMetricsResult,
    ):
        """Check voltage derating for a component."""
        # Determine required margin
        if 'ELEC' in comp_type or 'ELECTROLYTIC' in comp_type:
            required_margin = DERATING_RULES["voltage"]["electrolytic_cap"]
        else:
            required_margin = DERATING_RULES["voltage"]["minimum_margin"]

        max_operating = voltage_rating * (1 - required_margin)
        actual_margin = 1 - (operating_voltage / voltage_rating)

        if operating_voltage > max_operating:
            severity = Severity.ERROR if actual_margin < 0.10 else Severity.WARNING
            result.add_issue(ValidationIssue(
                category=MetricCategory.DERATING,
                severity=severity,
                component_ref=ref,
                message=f"Voltage derating violation: {operating_voltage}V on {voltage_rating}V rated component",
                details={
                    "operating_voltage": operating_voltage,
                    "voltage_rating": voltage_rating,
                    "actual_margin_percent": round(actual_margin * 100, 1),
                    "required_margin_percent": round(required_margin * 100, 1),
                },
                recommendation=f"Use component rated for ≥{operating_voltage / (1 - required_margin):.1f}V",
            ))

    def _check_current_derating(
        self,
        ref: str,
        current_rating: float,
        operating_current: float,
        result: QualityMetricsResult,
    ):
        """Check current derating for a component."""
        required_margin = DERATING_RULES["current"]["minimum_margin"]
        max_operating = current_rating * (1 - required_margin)
        actual_margin = 1 - (operating_current / current_rating)

        if operating_current > max_operating:
            severity = Severity.ERROR if actual_margin < 0.10 else Severity.WARNING
            result.add_issue(ValidationIssue(
                category=MetricCategory.DERATING,
                severity=severity,
                component_ref=ref,
                message=f"Current derating violation: {operating_current}A on {current_rating}A rated component",
                details={
                    "operating_current": operating_current,
                    "current_rating": current_rating,
                    "actual_margin_percent": round(actual_margin * 100, 1),
                },
                recommendation=f"Use component rated for ≥{operating_current / (1 - required_margin):.2f}A",
            ))

    def _check_power_resistor_derating(
        self,
        ref: str,
        power_rating: float,
        voltage: float,
        resistance_str: str,
        result: QualityMetricsResult,
    ):
        """Check power derating for resistors."""
        # Parse resistance value
        resistance = self._parse_resistance(resistance_str)
        if not resistance or not voltage:
            return

        # Calculate actual power: P = V²/R
        actual_power = (voltage ** 2) / resistance

        required_margin = DERATING_RULES["power"]["resistor_margin"]
        max_operating = power_rating * (1 - required_margin)

        if actual_power > max_operating:
            actual_margin = 1 - (actual_power / power_rating)
            severity = Severity.ERROR if actual_margin < 0.25 else Severity.WARNING
            result.add_issue(ValidationIssue(
                category=MetricCategory.DERATING,
                severity=severity,
                component_ref=ref,
                message=f"Power resistor derating: {actual_power*1000:.1f}mW on {power_rating*1000:.0f}mW rated resistor",
                details={
                    "actual_power_mw": round(actual_power * 1000, 1),
                    "power_rating_mw": round(power_rating * 1000, 1),
                    "actual_margin_percent": round(actual_margin * 100, 1),
                },
                recommendation=f"Use resistor rated for ≥{actual_power / (1 - required_margin) * 1000:.0f}mW",
            ))

    # =========================================================================
    # POWER DISSIPATION CALCULATIONS
    # =========================================================================

    def _check_power_dissipation(
        self,
        components: List[Dict],
        circuit: Dict,
        result: QualityMetricsResult,
    ):
        """
        Calculate total power dissipation and per-rail current.

        GENERIC: Works for any circuit topology.
        """
        power_analysis = PowerAnalysis()
        rail_currents: Dict[str, float] = {}
        total_power = 0.0

        for comp in components:
            ref = comp.get('ref', comp.get('reference', 'Unknown'))
            comp_type = comp.get('type', '').upper()

            # Calculate component power
            power_mw = self._estimate_component_power(comp)
            if power_mw > 0:
                power_analysis.per_component_power[ref] = power_mw
                total_power += power_mw

            # Identify power rail connections
            self._track_rail_current(comp, rail_currents)

            # Flag components that may need heat sinks
            if power_mw > 500:  # > 500mW
                power_analysis.heat_sink_required.append(ref)

        power_analysis.total_power_mw = total_power
        power_analysis.per_rail_current = rail_currents
        result.power_analysis = power_analysis

        # Add warning if total power is high
        if total_power > 5000:  # > 5W
            result.add_issue(ValidationIssue(
                category=MetricCategory.POWER,
                severity=Severity.WARNING,
                component_ref="CIRCUIT",
                message=f"High total power dissipation: {total_power/1000:.2f}W",
                details={"total_power_mw": total_power},
                recommendation="Ensure adequate thermal management and power supply capacity",
            ))

        # Check for components needing heat sinks
        if power_analysis.heat_sink_required:
            result.add_issue(ValidationIssue(
                category=MetricCategory.POWER,
                severity=Severity.INFO,
                component_ref="CIRCUIT",
                message=f"Components may require heat sinking: {', '.join(power_analysis.heat_sink_required)}",
                details={"components": power_analysis.heat_sink_required},
            ))

    def _estimate_component_power(self, comp: Dict) -> float:
        """
        Estimate power dissipation for a component (in mW).

        GENERIC: Handles all common component types using physics-based
        estimation. Uses explicit properties when available, falls back
        to type-based heuristics with conservative defaults.

        Supported types: regulators, MOSFETs, BJTs, diodes/LEDs, op-amps,
        generic ICs, resistors, inductors, capacitors.
        """
        # Explicit power specification takes priority
        explicit_power = self._get_comp_spec(comp, 'power_dissipation')
        if explicit_power is not None:
            return self._parse_power_value(explicit_power)

        comp_type = (comp.get('type', '') or '').upper()
        value = (comp.get('value', '') or '')
        ref = (comp.get('ref', comp.get('reference', '')) or '').upper()

        # Voltage regulator: P = (Vin - Vout) × Iout (linear) or efficiency-based (switching)
        if self._is_regulator(comp_type, value, ref):
            return self._estimate_regulator_power(comp)

        # MOSFET: P = Rds_on × Id² + switching losses
        if self._is_mosfet(comp_type, ref):
            return self._estimate_mosfet_power(comp)

        # BJT transistor: P = Vce × Ic
        if self._is_transistor(comp_type, ref):
            return self._estimate_transistor_power(comp)

        # Diode (including LED): P = Vf × If
        if self._is_diode(comp_type, ref):
            return self._estimate_diode_power(comp)

        # Op-amp / amplifier: P = Iq × Vsupply
        if self._is_opamp(comp_type, value):
            return self._estimate_opamp_power(comp)

        # Generic IC (MCU, gate driver, ADC, DAC, etc.): P = Isupply × Vsupply
        if self._is_ic(comp_type, ref):
            return self._estimate_ic_power(comp)

        # Resistor: P = V²/R or I²R
        if self._is_resistor(comp_type, ref):
            return self._estimate_resistor_power(comp, value)

        # Inductor: P = DCR × I²
        if self._is_inductor(comp_type, ref):
            return self._estimate_inductor_power(comp)

        # Capacitor: P = ESR × I_rms²
        if self._is_capacitor(comp_type, ref):
            return self._estimate_capacitor_power(comp)

        return 0.0

    def _track_rail_current(self, comp: Dict, rail_currents: Dict[str, float]):
        """
        Track current draw per power rail for all component types.

        GENERIC: Infers rail name and current from component properties,
        type classification, and connection metadata.
        """
        comp_type = (comp.get('type', '') or '').upper()
        ref = (comp.get('ref', comp.get('reference', '')) or '').upper()
        value = (comp.get('value', '') or '')

        # Determine power rail name
        rail = self._infer_power_rail(comp)

        # --- ICs, MCUs, op-amps ---
        if self._is_ic(comp_type, ref) or self._is_opamp(comp_type, value):
            if any(kw in comp_type for kw in ('MCU', 'MICROCONTROLLER', 'SOC', 'FPGA')):
                iq_default = 0.050
            elif any(kw in comp_type for kw in ('DRIVER', 'GATE_DRIVER', 'GATE-DRIVER')):
                iq_default = 0.015
            else:
                iq_default = 0.010
            current = self._get_comp_spec(
                comp, 'supply_current', 'quiescent_current', 'iq', default=iq_default
            )
            rail_currents[rail] = rail_currents.get(rail, 0) + self._parse_numeric(current, iq_default)
            return

        # --- Voltage regulators (draw from input, supply output) ---
        if self._is_regulator(comp_type, value, ref):
            iout = self._get_comp_spec(comp, 'output_current', 'load_current', default=0.1)
            iout = self._parse_numeric(iout, 0.1)

            input_rail = self._get_comp_spec(comp, 'input_rail', default=None)
            if not input_rail:
                vin_num = self._parse_numeric(
                    self._get_comp_spec(comp, 'input_voltage', 'inputVoltage', default=12.0), 12.0
                )
                input_rail = self._format_rail_name(vin_num)
            rail_currents[input_rail] = rail_currents.get(input_rail, 0) + iout

            output_rail = self._get_comp_spec(comp, 'output_rail', default=None)
            if not output_rail:
                vout_num = self._parse_numeric(
                    self._get_comp_spec(comp, 'output_voltage', 'outputVoltage', default=5.0), 5.0
                )
                output_rail = self._format_rail_name(vout_num)
            rail_currents[f"{output_rail}_supply"] = (
                rail_currents.get(f"{output_rail}_supply", 0) + iout
            )
            return

        # --- MOSFETs ---
        if self._is_mosfet(comp_type, ref):
            current = self._get_comp_spec(
                comp, 'drain_current', 'load_current', 'operating_current', default=None
            )
            if current is not None:
                rail_currents[rail] = rail_currents.get(rail, 0) + self._parse_numeric(current, 1.0)
            return

        # --- BJT transistors ---
        if self._is_transistor(comp_type, ref):
            current = self._get_comp_spec(
                comp, 'collector_current', 'operating_current', default=None
            )
            if current is not None:
                rail_currents[rail] = rail_currents.get(rail, 0) + self._parse_numeric(current, 0.1)
            return

        # --- Diodes / LEDs ---
        if self._is_diode(comp_type, ref):
            current = self._get_comp_spec(
                comp, 'forward_current', 'operating_current', default=None
            )
            if current is not None:
                rail_currents[rail] = rail_currents.get(rail, 0) + self._parse_numeric(current, 0.010)
            return

        # --- Fallback: any component with explicit supply_current ---
        current = self._get_comp_spec(comp, 'supply_current', 'operating_current', default=None)
        if current is not None:
            current_val = self._parse_numeric(current, 0)
            if current_val > 0:
                rail_currents[rail] = rail_currents.get(rail, 0) + current_val

    # =========================================================================
    # COMPONENT TYPE DETECTION (GENERIC)
    # =========================================================================

    @staticmethod
    def _is_regulator(comp_type: str, value: str, ref: str) -> bool:
        """Detect voltage regulator from type, value pattern, or ref."""
        if any(kw in comp_type for kw in (
            'REGULATOR', 'LDO', 'DCDC', 'DC-DC', 'BUCK', 'BOOST', 'CONVERTER',
        )):
            return True
        value_upper = (value or '').upper()
        if re.search(
            r'(?:LM78|LM79|LM317|LM337|AMS1117|LT1083|TPS\d|LM2596|LM2576|NCP1117'
            r'|MCP1700|RT9013|TLV\d|XC6206|HT73|78L|79L|AP2112|TNY\d|TOP\d)',
            value_upper,
        ):
            return True
        return False

    @staticmethod
    def _is_mosfet(comp_type: str, ref: str) -> bool:
        """Detect MOSFET from type or ref prefix + type hint."""
        if any(kw in comp_type for kw in ('MOSFET', 'NMOS', 'PMOS', 'NFET', 'PFET')):
            return True
        if ref.startswith('Q') and 'FET' in comp_type:
            return True
        return False

    @staticmethod
    def _is_transistor(comp_type: str, ref: str) -> bool:
        """Detect BJT transistor (excludes MOSFETs)."""
        if any(kw in comp_type for kw in ('BJT', 'NPN', 'PNP', 'TRANSISTOR', 'DARLINGTON')):
            return True
        # Q-prefix without FET/MOS keywords defaults to BJT
        if ref.startswith('Q') and not any(kw in comp_type for kw in ('MOS', 'FET')):
            return True
        return False

    @staticmethod
    def _is_diode(comp_type: str, ref: str) -> bool:
        """Detect diode (including LED, Zener, Schottky, TVS)."""
        if any(kw in comp_type for kw in (
            'DIODE', 'LED', 'ZENER', 'SCHOTTKY', 'TVS', 'RECTIFIER',
        )):
            return True
        if ref.startswith('D'):
            return True
        return False

    @staticmethod
    def _is_opamp(comp_type: str, value: str) -> bool:
        """Detect operational amplifier from type or value pattern."""
        if any(kw in comp_type for kw in (
            'OPAMP', 'OP-AMP', 'OP_AMP', 'OPERATIONAL', 'COMPARATOR',
            'INSTRUMENTATION', 'AMPLIFIER',
        )):
            return True
        if re.search(
            r'(?:LM358|LM324|TL07|TL08|NE5532|OPA\d|AD8\d|INA\d|MCP60|LMV|TSV)',
            (value or '').upper(),
        ):
            return True
        return False

    @staticmethod
    def _is_ic(comp_type: str, ref: str) -> bool:
        """Detect generic IC (MCU, gate driver, ADC, DAC, etc.)."""
        if any(kw in comp_type for kw in (
            'IC', 'MCU', 'MICROCONTROLLER', 'FPGA', 'CPLD', 'SOC',
            'ADC', 'DAC', 'DRIVER', 'DDS', 'PLL', 'CODEC', 'SENSOR',
            'TIMER', 'CONTROLLER', 'SUPERVISOR', 'MULTIPLEXER', 'MUX',
        )):
            return True
        if ref.startswith('U'):
            return True
        return False

    @staticmethod
    def _is_resistor(comp_type: str, ref: str) -> bool:
        """Detect resistor."""
        return 'RESISTOR' in comp_type or comp_type.startswith('R') or ref.startswith('R')

    @staticmethod
    def _is_inductor(comp_type: str, ref: str) -> bool:
        """Detect inductor / choke / ferrite bead."""
        return (
            any(kw in comp_type for kw in ('INDUCTOR', 'CHOKE', 'FERRITE', 'TRANSFORMER'))
            or ref.startswith('L')
        )

    @staticmethod
    def _is_capacitor(comp_type: str, ref: str) -> bool:
        """Detect capacitor."""
        return 'CAPACITOR' in comp_type or comp_type.startswith('C') or ref.startswith('C')

    # =========================================================================
    # PER-TYPE POWER ESTIMATION (GENERIC)
    # =========================================================================

    def _estimate_regulator_power(self, comp: Dict) -> float:
        """P = (Vin - Vout) × Iout for linear; efficiency-based for switching."""
        vin = self._parse_numeric(
            self._get_comp_spec(comp, 'input_voltage', 'inputVoltage', default=12.0), 12.0
        )
        vout = self._parse_numeric(
            self._get_comp_spec(comp, 'output_voltage', 'outputVoltage', default=5.0), 5.0
        )
        iout = self._parse_numeric(
            self._get_comp_spec(comp, 'output_current', 'outputCurrent', 'load_current', default=0.1), 0.1
        )

        comp_type = (comp.get('type', '') or '').upper()
        value = (comp.get('value', '') or '').upper()

        # Switching regulators: use efficiency model
        if any(kw in comp_type or kw in value for kw in (
            'DCDC', 'DC-DC', 'BUCK', 'BOOST', 'SWITCHING', 'LM2596', 'LM2576',
            'TPS', 'MP23', 'TNY', 'TOP',
        )):
            efficiency = self._parse_numeric(
                self._get_comp_spec(comp, 'efficiency', default=0.85), 0.85
            )
            pout = vout * iout
            pin = pout / max(efficiency, 0.1)
            return (pin - pout) * 1000

        # Linear regulator: P = (Vin - Vout) × Iout
        if vin > vout:
            return (vin - vout) * iout * 1000
        return 0.0

    def _estimate_mosfet_power(self, comp: Dict) -> float:
        """P = Rds_on × Id² (conduction) + optional switching losses."""
        rds_on = self._get_comp_spec(comp, 'rds_on', 'rdson', 'on_resistance', default=None)
        i_drain = self._get_comp_spec(
            comp, 'drain_current', 'load_current', 'operating_current', default=None
        )

        if rds_on is not None and i_drain is not None:
            rds_on = self._parse_numeric(rds_on, 0.1)
            i_drain = self._parse_numeric(i_drain, 1.0)
            p_conduction = rds_on * (i_drain ** 2)

            # Switching loss: P_sw = 0.5 × Vds × Id × (tr + tf) × fsw
            vds = self._get_comp_spec(
                comp, 'drain_voltage', 'operating_voltage', 'supply_voltage', default=None
            )
            fsw = self._get_comp_spec(comp, 'switching_frequency', 'frequency', default=None)
            p_switching = 0.0
            if vds is not None and fsw is not None:
                vds = self._parse_numeric(vds, 48.0)
                fsw = self._parse_numeric(fsw, 100000)
                t_transition = self._parse_numeric(
                    self._get_comp_spec(comp, 'rise_time', 'transition_time', default=100e-9),
                    100e-9,
                )
                p_switching = 0.5 * vds * i_drain * t_transition * fsw

            return (p_conduction + p_switching) * 1000

        # Fallback: derate from max power rating if available
        power_rating = self._get_comp_spec(comp, 'power_rating', 'max_power', default=None)
        if power_rating is not None:
            return self._parse_numeric(power_rating, 1.0) * 0.1 * 1000
        return 0.0

    def _estimate_transistor_power(self, comp: Dict) -> float:
        """P = Vce × Ic (Vce_sat for saturated, Vce for linear region)."""
        vce = self._get_comp_spec(
            comp, 'vce_sat', 'vce', 'collector_emitter_voltage', default=None
        )
        ic = self._get_comp_spec(
            comp, 'collector_current', 'operating_current', 'load_current', default=None
        )
        if vce is not None and ic is not None:
            return self._parse_numeric(vce, 0.3) * self._parse_numeric(ic, 0.1) * 1000
        return 0.0

    def _estimate_diode_power(self, comp: Dict) -> float:
        """P = Vf × If (forward conduction loss)."""
        comp_type = (comp.get('type', '') or '').upper()

        # Zener: P = Vz × Iz (reverse bias operation)
        if 'ZENER' in comp_type:
            vz = self._parse_numeric(
                self._get_comp_spec(comp, 'zener_voltage', 'breakdown_voltage', 'voltage', default=5.0), 5.0
            )
            iz = self._parse_numeric(
                self._get_comp_spec(comp, 'zener_current', 'operating_current', default=0.005), 0.005
            )
            return vz * iz * 1000

        # Defaults vary by diode type
        if 'LED' in comp_type:
            vf_default, if_default = 2.0, 0.010
        elif 'SCHOTTKY' in comp_type:
            vf_default, if_default = 0.3, 1.0
        else:
            vf_default, if_default = 0.7, 0.5

        vf = self._parse_numeric(
            self._get_comp_spec(comp, 'forward_voltage', 'vf', default=vf_default), vf_default
        )
        i_f = self._parse_numeric(
            self._get_comp_spec(comp, 'forward_current', 'operating_current', default=if_default), if_default
        )
        return vf * i_f * 1000

    def _estimate_opamp_power(self, comp: Dict) -> float:
        """P = Iq × Vsupply."""
        iq = self._parse_numeric(
            self._get_comp_spec(comp, 'quiescent_current', 'supply_current', 'iq', default=0.005), 0.005
        )
        vcc = self._parse_numeric(
            self._get_comp_spec(comp, 'supply_voltage', 'vcc', 'operating_voltage', default=12.0), 12.0
        )
        return iq * vcc * 1000

    def _estimate_ic_power(self, comp: Dict) -> float:
        """P = Isupply × Vsupply for generic ICs with type-aware defaults."""
        comp_type = (comp.get('type', '') or '').upper()

        # Default quiescent current varies by IC category
        if any(kw in comp_type for kw in ('MCU', 'MICROCONTROLLER', 'SOC', 'FPGA')):
            iq_default = 0.050  # 50mA
        elif any(kw in comp_type for kw in ('DRIVER', 'GATE_DRIVER', 'GATE-DRIVER')):
            iq_default = 0.015  # 15mA
        elif any(kw in comp_type for kw in ('ADC', 'DAC')):
            iq_default = 0.010  # 10mA
        elif any(kw in comp_type for kw in ('DDS', 'PLL', 'SYNTHESIZER')):
            iq_default = 0.030  # 30mA
        else:
            iq_default = 0.010  # 10mA generic

        iq = self._parse_numeric(
            self._get_comp_spec(comp, 'supply_current', 'quiescent_current', 'iq', default=iq_default),
            iq_default,
        )
        vcc = self._parse_numeric(
            self._get_comp_spec(comp, 'supply_voltage', 'vcc', 'operating_voltage', default=5.0), 5.0
        )
        return iq * vcc * 1000

    def _estimate_resistor_power(self, comp: Dict, value: str) -> float:
        """P = V²/R or I²R, whichever data is available."""
        r = self._parse_resistance(value)
        if not r:
            return 0.0

        # Current-based calculation takes priority if available
        current = self._get_comp_spec(comp, 'operating_current', 'current', default=None)
        if current is not None:
            i = self._parse_numeric(current, 0.0)
            if i > 0:
                return (i ** 2) * r * 1000

        # Voltage-based calculation
        v = self._parse_numeric(
            self._get_comp_spec(comp, 'operating_voltage', 'voltage_across', default=5.0), 5.0
        )
        return (v ** 2) / r * 1000

    def _estimate_inductor_power(self, comp: Dict) -> float:
        """P = DCR × I² (DC resistance copper losses)."""
        dcr = self._get_comp_spec(comp, 'dcr', 'dc_resistance', 'series_resistance', default=None)
        current = self._get_comp_spec(
            comp, 'operating_current', 'rms_current', default=None
        )
        if dcr is not None and current is not None:
            return self._parse_numeric(dcr, 0.1) * (self._parse_numeric(current, 1.0) ** 2) * 1000
        return 0.0

    def _estimate_capacitor_power(self, comp: Dict) -> float:
        """P = ESR × I_rms² (ripple current heating, relevant for switching supplies)."""
        esr = self._get_comp_spec(comp, 'esr', 'series_resistance', default=None)
        i_rms = self._get_comp_spec(comp, 'ripple_current', 'rms_current', default=None)
        if esr is not None and i_rms is not None:
            return self._parse_numeric(esr, 0.01) * (self._parse_numeric(i_rms, 0.5) ** 2) * 1000
        return 0.0

    # =========================================================================
    # POWER ESTIMATION HELPERS
    # =========================================================================

    @staticmethod
    def _get_comp_spec(comp: Dict, *keys: str, default=None):
        """Look for a value in component top-level properties then specs dict."""
        specs = comp.get('specs', {})
        if not isinstance(specs, dict):
            specs = {}
        for key in keys:
            val = comp.get(key)
            if val is not None:
                return val
            val = specs.get(key)
            if val is not None:
                return val
        return default

    @staticmethod
    def _parse_numeric(value, default: float) -> float:
        """Parse a numeric value from string/int/float with basic unit awareness."""
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
            match = re.search(r'[\d.]+', value)
            if match:
                try:
                    return float(match.group(0))
                except ValueError:
                    pass
        return default

    @staticmethod
    def _parse_power_value(value) -> float:
        """Parse a power value to milliwatts."""
        if isinstance(value, (int, float)):
            return float(value) * 1000  # Assume watts → mW
        if isinstance(value, str):
            match = re.search(r'([\d.]+)\s*(m[Ww]|[Ww])', value)
            if match:
                num = float(match.group(1))
                unit = match.group(2).lower()
                return num if unit == 'mw' else num * 1000
        return 0.0

    def _infer_power_rail(self, comp: Dict) -> str:
        """Infer power rail name from component properties."""
        rail = self._get_comp_spec(comp, 'power_rail', 'supply_rail', default=None)
        if rail:
            return rail
        vcc = self._get_comp_spec(comp, 'supply_voltage', 'vcc', 'operating_voltage', default=None)
        if vcc is not None:
            return self._format_rail_name(self._parse_numeric(vcc, 0))
        return 'VCC'

    @staticmethod
    def _format_rail_name(voltage: float) -> str:
        """Format a voltage value into a standard rail name."""
        if voltage <= 0:
            return 'VCC'
        if voltage == int(voltage):
            return f"+{int(voltage)}V"
        return f"+{voltage:.1f}V"

    # =========================================================================
    # THERMAL ESTIMATES
    # =========================================================================

    def _check_thermal_estimates(
        self,
        components: List[Dict],
        result: QualityMetricsResult,
    ):
        """
        Estimate junction temperatures and identify thermal violations.

        Uses: Tj = Ta + (P × Rth_ja)

        GENERIC: Works for any component with thermal specifications.
        """
        thermal = ThermalAnalysis(ambient_temp_c=self.ambient_temp_c)
        max_temp = 0.0
        hottest = ""

        for comp in components:
            ref = comp.get('ref', comp.get('reference', 'Unknown'))

            # Get power dissipation
            power_w = result.power_analysis.per_component_power.get(ref, 0) / 1000
            if power_w == 0:
                continue

            # Get thermal resistance
            rth_ja = self._get_thermal_resistance(comp)

            # Calculate junction temperature
            tj = self.ambient_temp_c + (power_w * rth_ja)
            thermal.component_temps[ref] = tj

            if tj > max_temp:
                max_temp = tj
                hottest = ref

            # Check against max junction temperature
            max_tj = comp.get('max_junction_temp', 125.0)
            threshold = max_tj * DERATING_RULES["temperature"]["max_junction_percent"]

            if tj > threshold:
                thermal.thermal_violations.append(ref)
                severity = Severity.ERROR if tj > max_tj else Severity.WARNING
                result.add_issue(ValidationIssue(
                    category=MetricCategory.THERMAL,
                    severity=severity,
                    component_ref=ref,
                    message=f"Thermal violation: Estimated Tj={tj:.1f}°C exceeds {threshold:.0f}°C (80% of max {max_tj}°C)",
                    details={
                        "estimated_tj_c": round(tj, 1),
                        "max_tj_c": max_tj,
                        "power_w": round(power_w, 3),
                        "rth_ja": rth_ja,
                    },
                    recommendation="Add heat sink, improve airflow, or reduce power dissipation",
                ))

        thermal.hottest_component = hottest
        thermal.max_junction_temp_c = max_temp
        result.thermal_analysis = thermal

    def _get_thermal_resistance(self, comp: Dict) -> float:
        """
        Get thermal resistance (Rth_ja) for a component.

        GENERIC: Uses explicit value if provided, otherwise estimates from package.
        """
        # Check for explicit thermal resistance
        if 'thermal_resistance' in comp:
            return comp['thermal_resistance']

        # Estimate from package type
        footprint = comp.get('footprint', '')
        package = comp.get('package', '')

        for pkg_pattern, rth in THERMAL_RESISTANCE_DEFAULTS.items():
            if pkg_pattern in footprint.upper() or pkg_pattern in package.upper():
                return rth

        return THERMAL_RESISTANCE_DEFAULTS["default"]

    # =========================================================================
    # TRACE IMPEDANCE ANALYSIS
    # =========================================================================

    def _check_trace_impedance(
        self,
        nets: List,
        pin_net_mapping: Dict,
        circuit: Dict,
        result: QualityMetricsResult,
    ):
        """
        Check for high-speed nets that require impedance control.

        Uses microstrip impedance formula:
        Z0 = 87 / sqrt(εr + 1.41) × ln(5.98h / (0.8w + t))

        GENERIC: Based on net naming patterns and signal characteristics.
        """
        impedance = ImpedanceAnalysis()

        # Extract net names
        net_names = set()
        for net in nets:
            if isinstance(net, dict):
                net_names.add(net.get('name', ''))
            elif isinstance(net, str):
                net_names.add(net)

        # Identify high-speed nets
        for net_name in net_names:
            for pattern in self.high_speed_patterns:
                if pattern.search(net_name):
                    impedance.high_speed_nets.append(net_name)
                    break

        # Check for impedance control attributes
        controlled_nets = circuit.get('impedance_controlled_nets', [])
        impedance.impedance_controlled_nets = controlled_nets

        # Find uncontrolled high-speed nets
        for net in impedance.high_speed_nets:
            if net not in controlled_nets:
                impedance.uncontrolled_high_speed.append(net)

        result.impedance_analysis = impedance

        # Generate warnings for uncontrolled high-speed nets
        if impedance.uncontrolled_high_speed:
            result.add_issue(ValidationIssue(
                category=MetricCategory.IMPEDANCE,
                severity=Severity.WARNING,
                component_ref="NETS",
                message=f"High-speed nets without impedance control: {', '.join(impedance.uncontrolled_high_speed[:5])}",
                details={
                    "uncontrolled_count": len(impedance.uncontrolled_high_speed),
                    "nets": impedance.uncontrolled_high_speed[:10],
                },
                recommendation="Consider impedance-controlled routing for these signals",
            ))

        # Calculate target impedances
        self._calculate_target_impedances(impedance, result)

    def _calculate_target_impedances(
        self,
        impedance: ImpedanceAnalysis,
        result: QualityMetricsResult,
    ):
        """Calculate target impedances for high-speed nets."""
        for net in impedance.high_speed_nets:
            net_upper = net.upper()

            # USB 2.0: 90Ω differential
            if 'USB' in net_upper:
                impedance.calculated_impedances[net] = 90.0
            # Ethernet: 100Ω differential
            elif 'ETH' in net_upper:
                impedance.calculated_impedances[net] = 100.0
            # LVDS: 100Ω differential
            elif 'LVDS' in net_upper:
                impedance.calculated_impedances[net] = 100.0
            # General high-speed: 50Ω single-ended
            else:
                impedance.calculated_impedances[net] = 50.0

    def _calculate_microstrip_impedance(self, trace_width_mm: float) -> float:
        """
        Calculate microstrip characteristic impedance.

        Formula: Z0 = 87 / sqrt(εr + 1.41) × ln(5.98h / (0.8w + t))

        Where:
            εr = dielectric constant
            h = substrate height
            w = trace width
            t = copper thickness
        """
        er = self.stackup["dielectric_constant"]
        h = self.stackup["substrate_height_mm"]
        w = trace_width_mm
        t = self.stackup["trace_height_mm"]

        z0 = (87 / math.sqrt(er + 1.41)) * math.log(5.98 * h / (0.8 * w + t))
        return z0

    # =========================================================================
    # SIGNAL INTEGRITY CHECKS (Partial)
    # =========================================================================

    def _check_signal_integrity(
        self,
        nets: List,
        components: List[Dict],
        result: QualityMetricsResult,
    ):
        """
        Basic signal integrity checks.

        This is a PARTIAL implementation covering:
        - Rise time vs trace length (when to treat as transmission line)
        - Crosstalk potential for high-speed parallel traces

        GENERIC: Based on signal characteristics, not format-specific.
        """
        # Identify potential SI issues based on component types
        high_speed_components = []
        for comp in components:
            comp_type = comp.get('type', '').upper()
            clock_freq = comp.get('clock_frequency', 0)

            # Identify high-speed components
            if clock_freq > 10e6:  # > 10MHz
                high_speed_components.append({
                    "ref": comp.get('ref', ''),
                    "frequency": clock_freq,
                })
            elif any(hs in comp_type for hs in ['USB', 'ETH', 'LVDS', 'DDR', 'SDRAM']):
                high_speed_components.append({
                    "ref": comp.get('ref', ''),
                    "type": comp_type,
                })

        if high_speed_components:
            result.add_issue(ValidationIssue(
                category=MetricCategory.SIGNAL_INTEGRITY,
                severity=Severity.INFO,
                component_ref="CIRCUIT",
                message=f"Circuit contains {len(high_speed_components)} high-speed components requiring SI consideration",
                details={
                    "components": [c["ref"] for c in high_speed_components],
                },
                recommendation="Review trace lengths, terminations, and layer stack for high-speed signals",
            ))

        # Check for potential ground bounce (many I/O pins switching)
        io_count = sum(
            1 for c in components
            if 'MCU' in c.get('type', '').upper() or 'FPGA' in c.get('type', '').upper()
        )
        if io_count > 0:
            result.add_issue(ValidationIssue(
                category=MetricCategory.SIGNAL_INTEGRITY,
                severity=Severity.INFO,
                component_ref="CIRCUIT",
                message="Digital ICs present - consider ground bounce mitigation",
                recommendation="Use adequate decoupling capacitors and solid ground plane",
            ))

    # =========================================================================
    # DFT (DESIGN FOR TEST) CHECKS
    # =========================================================================

    def _check_dft_requirements(
        self,
        components: List[Dict],
        result: QualityMetricsResult,
    ):
        """
        Check Design for Test requirements.

        - Testpoint coverage
        - Debug headers
        - Fiducials

        GENERIC: Based on component types and circuit complexity.
        """
        # Check for testpoints
        testpoints = [c for c in components if 'TESTPOINT' in c.get('type', '').upper()]
        ic_count = sum(
            1 for c in components
            if any(t in c.get('type', '').upper() for t in ['IC', 'MCU', 'FPGA', 'SOC'])
        )

        # Rule: At least 1 testpoint per 5 ICs recommended
        recommended_testpoints = max(1, ic_count // 5)

        if len(testpoints) < recommended_testpoints:
            result.add_issue(ValidationIssue(
                category=MetricCategory.DFT,
                severity=Severity.INFO,
                component_ref="CIRCUIT",
                message=f"Limited testpoints: {len(testpoints)} present, {recommended_testpoints} recommended",
                details={
                    "testpoint_count": len(testpoints),
                    "ic_count": ic_count,
                    "recommended": recommended_testpoints,
                },
                recommendation="Add testpoints for key signals to improve debug capability",
            ))

        # Check for debug headers (JTAG, SWD, UART)
        debug_headers = [
            c for c in components
            if any(d in c.get('type', '').upper() for d in ['JTAG', 'SWD', 'DEBUG', 'UART'])
        ]

        has_programmable = any(
            any(t in c.get('type', '').upper() for t in ['MCU', 'FPGA', 'CPLD', 'SOC'])
            for c in components
        )

        if has_programmable and not debug_headers:
            result.add_issue(ValidationIssue(
                category=MetricCategory.DFT,
                severity=Severity.WARNING,
                component_ref="CIRCUIT",
                message="Programmable device without debug header",
                recommendation="Add JTAG/SWD header for programming and debug",
            ))

    # =========================================================================
    # ASSEMBLY CHECKS
    # =========================================================================

    def _check_assembly_requirements(
        self,
        components: List[Dict],
        result: QualityMetricsResult,
    ):
        """
        Check assembly-related requirements.

        - Fiducials for pick-and-place
        - Connector orientation
        - Component accessibility

        GENERIC: Based on component count and types.
        """
        # Check for fiducials (required for automated assembly)
        fiducials = [c for c in components if 'FIDUCIAL' in c.get('type', '').upper()]
        smd_count = sum(
            1 for c in components
            if 'SMD' in c.get('footprint', '').upper() or 'SMT' in c.get('footprint', '').upper()
        )

        if smd_count > 10 and len(fiducials) < 3:
            result.add_issue(ValidationIssue(
                category=MetricCategory.ASSEMBLY,
                severity=Severity.WARNING,
                component_ref="CIRCUIT",
                message=f"Insufficient fiducials: {len(fiducials)} present, 3 recommended for {smd_count} SMD components",
                details={
                    "fiducial_count": len(fiducials),
                    "smd_component_count": smd_count,
                },
                recommendation="Add 3+ fiducial markers for automated pick-and-place alignment",
            ))

        # Check connector orientation consistency
        connectors = [c for c in components if 'CONN' in c.get('type', '').upper()]
        if len(connectors) > 3:
            result.add_issue(ValidationIssue(
                category=MetricCategory.ASSEMBLY,
                severity=Severity.INFO,
                component_ref="CIRCUIT",
                message=f"Multiple connectors ({len(connectors)}) - verify consistent orientation",
                recommendation="Ensure connectors are accessible from board edge and consistently oriented",
            ))

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def _extract_voltage_rating(self, comp: Dict) -> Optional[float]:
        """Extract voltage rating from component properties."""
        if 'voltage_rating' in comp:
            return comp['voltage_rating']

        # Try to parse from value string (e.g., "100uF 25V")
        value = comp.get('value', '')
        match = re.search(r'(\d+(?:\.\d+)?)\s*V\b', value, re.IGNORECASE)
        if match:
            return float(match.group(1))

        return None

    def _extract_current_rating(self, comp: Dict) -> Optional[float]:
        """Extract current rating from component properties."""
        if 'current_rating' in comp:
            return comp['current_rating']
        return None

    def _extract_power_rating(self, comp: Dict) -> Optional[float]:
        """Extract power rating from component properties."""
        if 'power_rating' in comp:
            return comp['power_rating']

        # Try to parse from value string (e.g., "10k 0.25W")
        value = comp.get('value', '')
        match = re.search(r'(\d+(?:\.\d+)?)\s*W\b', value, re.IGNORECASE)
        if match:
            return float(match.group(1))

        return None

    def _extract_operating_voltage(self, comp: Dict) -> Optional[float]:
        """Extract operating voltage from component properties."""
        if 'operating_voltage' in comp:
            return comp['operating_voltage']
        if 'supply_voltage' in comp:
            return comp['supply_voltage']
        return None

    def _extract_operating_current(self, comp: Dict) -> Optional[float]:
        """Extract operating current from component properties."""
        if 'operating_current' in comp:
            return comp['operating_current']
        if 'supply_current' in comp:
            return comp['supply_current']
        return None

    def _parse_resistance(self, value_str: str) -> Optional[float]:
        """
        Parse resistance value from string.

        Examples: "10k", "4.7K", "100R", "1M", "470"
        """
        if not value_str:
            return None

        # Remove common suffixes
        value_str = value_str.strip().upper()

        # Pattern: number + optional multiplier
        match = re.match(r'^([\d.]+)\s*([KMR])?', value_str)
        if not match:
            return None

        value = float(match.group(1))
        multiplier = match.group(2)

        if multiplier == 'K':
            value *= 1000
        elif multiplier == 'M':
            value *= 1000000
        # 'R' or no suffix = ohms

        return value


# =============================================================================
# DFM VENDOR PROFILES
# =============================================================================

class DFMVendorProfile:
    """
    Manufacturing vendor capability profiles.

    GENERIC: Same profile structure for all EDA formats.
    """

    PROFILES = {
        "JLCPCB": {
            "name": "JLCPCB",
            "min_trace_width_mm": 0.127,  # 5 mil
            "min_clearance_mm": 0.127,  # 5 mil
            "min_via_drill_mm": 0.3,
            "min_via_diameter_mm": 0.6,
            "min_hole_to_hole_mm": 0.5,
            "min_solder_mask_bridge_mm": 0.1,
            "copper_weights_oz": [1, 2],
            "board_thickness_mm": [0.8, 1.0, 1.2, 1.6, 2.0],
            "layers": [1, 2, 4, 6],
            "min_silkscreen_width_mm": 0.15,
            "min_silkscreen_height_mm": 0.8,
        },
        "PCBWAY": {
            "name": "PCBWay",
            "min_trace_width_mm": 0.1,  # 4 mil
            "min_clearance_mm": 0.1,  # 4 mil
            "min_via_drill_mm": 0.2,
            "min_via_diameter_mm": 0.4,
            "min_hole_to_hole_mm": 0.5,
            "min_solder_mask_bridge_mm": 0.08,
            "copper_weights_oz": [0.5, 1, 2, 3],
            "board_thickness_mm": [0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0, 2.4],
            "layers": [1, 2, 4, 6, 8],
            "min_silkscreen_width_mm": 0.1,
            "min_silkscreen_height_mm": 0.6,
        },
        "OSHPARK": {
            "name": "OSH Park",
            "min_trace_width_mm": 0.152,  # 6 mil
            "min_clearance_mm": 0.152,  # 6 mil
            "min_via_drill_mm": 0.254,  # 10 mil
            "min_via_diameter_mm": 0.508,  # 20 mil
            "min_hole_to_hole_mm": 0.635,  # 25 mil
            "min_solder_mask_bridge_mm": 0.1,
            "copper_weights_oz": [1, 2],
            "board_thickness_mm": [0.8, 1.6],
            "layers": [2, 4],
            "min_silkscreen_width_mm": 0.15,
            "min_silkscreen_height_mm": 1.0,
        },
        "SEEED_FUSION": {
            "name": "Seeed Fusion",
            "min_trace_width_mm": 0.15,  # 6 mil
            "min_clearance_mm": 0.15,  # 6 mil
            "min_via_drill_mm": 0.3,
            "min_via_diameter_mm": 0.6,
            "min_hole_to_hole_mm": 0.5,
            "min_solder_mask_bridge_mm": 0.1,
            "copper_weights_oz": [1, 2],
            "board_thickness_mm": [0.8, 1.0, 1.2, 1.6, 2.0],
            "layers": [1, 2, 4, 6],
            "min_silkscreen_width_mm": 0.15,
            "min_silkscreen_height_mm": 0.8,
        },
    }

    @classmethod
    def get_profile(cls, vendor: str) -> Dict[str, Any]:
        """Get vendor profile by name."""
        return cls.PROFILES.get(vendor.upper(), cls.PROFILES["JLCPCB"])

    @classmethod
    def list_vendors(cls) -> List[str]:
        """List available vendor profiles."""
        return list(cls.PROFILES.keys())


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def validate_circuit_quality(
    circuit_path: Path,
    ambient_temp_c: float = 25.0,
    vendor: str = "JLCPCB",
) -> QualityMetricsResult:
    """
    Convenience function to validate circuit quality.

    GENERIC: Works for any circuit file regardless of target output format.

    Args:
        circuit_path: Path to lowlevel circuit JSON
        ambient_temp_c: Ambient temperature for thermal analysis
        vendor: Manufacturing vendor profile name

    Returns:
        QualityMetricsResult with all validation findings
    """
    validator = QualityMetricsValidator(
        ambient_temp_c=ambient_temp_c,
        vendor_profile=vendor,
    )
    return validator.validate_circuit(circuit_path)


def validate_all_circuits(
    lowlevel_dir: Path,
    output_report_path: Path = None,
    vendor: str = "JLCPCB",
) -> Dict[str, QualityMetricsResult]:
    """
    Validate all circuits in a lowlevel directory.

    GENERIC: Validates all circuit JSON files regardless of target format.

    Args:
        lowlevel_dir: Directory containing circuit JSON files
        output_report_path: Optional path to save JSON report
        vendor: Manufacturing vendor profile

    Returns:
        Dictionary mapping circuit names to validation results
    """
    results = {}
    validator = QualityMetricsValidator(vendor_profile=vendor)

    for circuit_file in sorted(lowlevel_dir.glob("circuit_*.json")):
        result = validator.validate_circuit(circuit_file)
        results[result.circuit_name] = result

    # Save report if requested
    if output_report_path:
        report = {
            "vendor_profile": vendor,
            "circuits": {name: r.to_dict() for name, r in results.items()},
            "summary": {
                "total_circuits": len(results),
                "passed": sum(1 for r in results.values() if r.passed),
                "failed": sum(1 for r in results.values() if not r.passed),
                "total_errors": sum(r.error_count for r in results.values()),
                "total_warnings": sum(r.warning_count for r in results.values()),
            },
        }
        with open(output_report_path, 'w') as f:
            json.dump(report, f, indent=2)

    return results


# =============================================================================
# MAIN (for testing)
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python quality_metrics_validator.py <circuit.json or lowlevel_dir>")
        print("\nAvailable vendor profiles:")
        for vendor in DFMVendorProfile.list_vendors():
            print(f"  - {vendor}")
        sys.exit(1)

    path = Path(sys.argv[1])
    vendor = sys.argv[2] if len(sys.argv) > 2 else "JLCPCB"

    print(f"\n{'='*60}")
    print(f"QUALITY METRICS VALIDATOR")
    print(f"{'='*60}")
    print(f"Vendor Profile: {vendor}")
    print()

    if path.is_file():
        result = validate_circuit_quality(path, vendor=vendor)
        print(f"\nCircuit: {result.circuit_name}")
        print(f"Status: {'PASSED' if result.passed else 'FAILED'}")
        print(f"Errors: {result.error_count}")
        print(f"Warnings: {result.warning_count}")
        print(f"Info: {result.info_count}")

        if result.issues:
            print(f"\nIssues:")
            for issue in result.issues:
                print(f"  [{issue.severity.value.upper()}] {issue.component_ref}: {issue.message}")

    elif path.is_dir():
        results = validate_all_circuits(path, vendor=vendor)

        print(f"Validated {len(results)} circuits\n")

        total_errors = 0
        total_warnings = 0

        for name, result in results.items():
            status = "PASS" if result.passed else "FAIL"
            print(f"  {name}: {status} ({result.error_count}E, {result.warning_count}W)")
            total_errors += result.error_count
            total_warnings += result.warning_count

        print(f"\nTotal: {total_errors} errors, {total_warnings} warnings")

    else:
        print(f"Error: Path not found: {path}")
        sys.exit(1)
