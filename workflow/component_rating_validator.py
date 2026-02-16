# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Component Rating Validator Module
==================================
Validates that component ratings match application requirements.

This module is GENERIC and works with ANY circuit type:
- Validates MOSFETs, transistors, diodes against voltage/current requirements
- Validates capacitors against voltage requirements
- Validates resistors against power requirements
- Flags mismatches and provides specific fix recommendations

This catches the critical error where structurally-valid circuits
have components that cannot handle the required voltage/current/power.

Author: CopperPilot
Date: December 2025
"""

import json
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from utils.logger import setup_logger
from server.config import config
from workflow.requirements_rating_extractor import ExtractedRequirements, extract_requirements_ratings

logger = setup_logger(__name__)



# =============================================================================
# COMPONENT RATINGS — SINGLE SOURCE OF TRUTH
# =============================================================================
# All component ratings live in the external JSON database at
# data/component_ratings.json (path configured via config.COMPONENT_RATINGS_DB_PATH).
# The _load_external_ratings() classmethod loads them once at startup.
# NO hardcoded rating dicts in Python code — avoids dual-source maintenance.
# =============================================================================


@dataclass
class RatingViolation:
    """Represents a component rating violation."""
    component_ref: str
    component_type: str
    component_value: str
    violation_type: str  # 'voltage', 'current', 'power', 'frequency'
    required_rating: float
    actual_rating: float
    severity: str  # 'critical', 'warning', 'info'
    message: str
    fix_suggestion: str


@dataclass
class ValidationResult:
    """Result of component rating validation."""
    passed: bool
    violations: List[RatingViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'passed': self.passed,
            'violations': [
                {
                    'component_ref': v.component_ref,
                    'component_type': v.component_type,
                    'component_value': v.component_value,
                    'violation_type': v.violation_type,
                    'required_rating': v.required_rating,
                    'actual_rating': v.actual_rating,
                    'severity': v.severity,
                    'message': v.message,
                    'fix_suggestion': v.fix_suggestion,
                }
                for v in self.violations
            ],
            'warnings': self.warnings,
            'summary': self.summary,
        }


class ComponentRatingValidator:
    """
    Validates component ratings against application requirements.

    This class is GENERIC and works with ANY circuit type.
    It checks:
    - MOSFETs/transistors against voltage requirements
    - Capacitors against voltage requirements
    - Power components against power requirements
    - Frequency-sensitive components against frequency requirements

    Fix 1.4 (Forensic Fix Plan): Per-rail voltage domain awareness.
    Components are validated against their LOCAL voltage domain, not the
    blanket system maximum. A 5V logic MOSFET needs 20V rating, not 800V.
    """

    # Net name patterns mapped to approximate voltage levels.
    # Used for per-rail voltage domain detection.
    # Ordered from most specific to least specific.
    _NET_VOLTAGE_PATTERNS: List[Tuple[str, float]] = [
        # Exact low-voltage rails
        ('1V8', 1.8), ('1.8V', 1.8),
        ('2V5', 2.5), ('2.5V', 2.5),
        ('3V3', 3.3), ('3.3V', 3.3),
        ('5V', 5.0), ('+5V', 5.0), ('VCC_5V', 5.0), ('5V_', 5.0),
        ('12V', 12.0), ('+12V', 12.0), ('VCC_12', 12.0),
        ('15V', 15.0), ('+15V', 15.0), ('-15V', 15.0), ('VCC_POS15V', 15.0),
        ('24V', 24.0), ('+24V', 24.0),
        ('48V', 48.0), ('+48V', 48.0),
        # High-voltage patterns
        ('100V', 100.0), ('200V', 200.0), ('400V', 400.0),
        ('HV_RAIL', None),  # None = use system max
        ('HV_BUS', None), ('DC_BUS', None), ('DC_LINK', None),
        # Generic power rails (low voltage assumed)
        ('VCC', 5.0), ('VDD', 3.3), ('AVCC', 5.0), ('DVCC', 3.3),
    ]

    # Phase I: External component ratings loaded once at class level
    _external_ratings_cache: Optional[Dict] = None

    @classmethod
    def _load_external_ratings(cls) -> Dict:
        """
        Load component ratings from the external JSON database.
        This is the SINGLE source of truth for all component ratings.
        Returns cached result on subsequent calls.
        """
        if cls._external_ratings_cache is not None:
            return cls._external_ratings_cache

        cls._external_ratings_cache = {}
        db_path = Path(config.COMPONENT_RATINGS_DB_PATH)
        if db_path.exists():
            try:
                import json as _json
                raw = _json.loads(db_path.read_text())
                # Filter out comment keys
                cls._external_ratings_cache = {
                    k: v for k, v in raw.items()
                    if not k.startswith('_') and isinstance(v, dict)
                }
                logger.info(f"Phase I: Loaded {len(cls._external_ratings_cache)} entries from external ratings DB")
            except Exception as e:
                logger.warning(f"Phase I: Could not load external ratings DB: {e}")

        return cls._external_ratings_cache

    def _lookup_voltage_rating(self, comp_value: str, comp_type_hint: str = '') -> Optional[float]:
        """
        Unified voltage rating lookup — queries ONLY the external JSON DB.

        Tries exact match first, then partial match (handles variations
        like IRFZ44N vs IRFZ44). Returns the voltage rating or None.
        """
        db = self._load_external_ratings()
        value_upper = comp_value.upper()

        # Exact match
        if value_upper in db:
            entry = db[value_upper]
            return entry.get('voltage')

        # Partial match (handle variations)
        for part, entry in db.items():
            if part in value_upper or value_upper in part:
                return entry.get('voltage')

        return None

    def __init__(self, requirements: Optional[ExtractedRequirements] = None):
        """
        Initialize validator with extracted requirements.

        Args:
            requirements: Extracted electrical requirements, or None to skip requirement-based checks
        """
        self.requirements = requirements
        self.violations: List[RatingViolation] = []
        self.warnings: List[str] = []
        self._net_voltage_map: Dict[str, float] = {}  # populated per circuit
        self._pin_net_mapping: Dict[str, str] = {}      # populated per circuit
        self._module_voltage_domain: Optional[float] = None  # Phase I

        # Load external ratings database
        self._external_ratings = self._load_external_ratings()

    def validate_circuit(
        self,
        circuit: Dict,
        module_voltage_domain: Optional[float] = None,
    ) -> 'ValidationResult':
        """
        Validate all components in a circuit against requirements.

        Phase I (Forensic Fix 20260208): Added ``module_voltage_domain`` parameter.
        When provided, this voltage is used as the primary operating voltage for
        component rating thresholds, overriding the global max_voltage.  This
        prevents, e.g., a 12V fan module from being validated against 360V.

        Args:
            circuit: Circuit JSON with 'components' list
            module_voltage_domain: Optional per-module operating voltage (V).

        Returns:
            ValidationResult with any violations found
        """
        self.violations = []
        self.warnings = []

        # Phase I: Store module-level voltage domain for use in validation
        self._module_voltage_domain = module_voltage_domain

        # Extract circuit data
        if 'circuit' in circuit:
            circuit_data = circuit['circuit']
        else:
            circuit_data = circuit

        components = circuit_data.get('components', [])

        if not components:
            self.warnings.append("No components found in circuit")
            return self._create_result()

        # Fix 1.4: Build per-rail voltage domain map from pinNetMapping
        self._pin_net_mapping = circuit_data.get('pinNetMapping', {})
        self._net_voltage_map = self._build_net_voltage_map(circuit_data)

        logger.info(f"Validating {len(components)} components against requirements")

        # Validate each component
        for component in components:
            self._validate_component(component)

        return self._create_result()

    def _build_net_voltage_map(self, circuit_data: Dict) -> Dict[str, float]:
        """
        Fix 1.4 + Y.5 FIX: Build a mapping from net names to approximate voltage levels.

        Uses net name pattern matching to determine voltage domains.
        Y.5: Enhanced with xVy notation (3V3 → 3.3V, 1V8 → 1.8V) and
        RAIL_ prefix matching. Falls back to system max ONLY for
        explicitly HV-tagged nets — NOT for unrecognised nets.

        GENERIC: Works for any circuit topology and naming convention.

        Returns:
            Dict mapping net name to approximate voltage (V).
        """
        net_voltages: Dict[str, float] = {}
        all_nets = set(circuit_data.get('nets', []))
        # Also collect nets from pinNetMapping values
        for net in self._pin_net_mapping.values():
            if isinstance(net, str):
                all_nets.add(net)

        system_max = (
            self.requirements.max_voltage
            if self.requirements and self.requirements.max_voltage > 0
            else 0.0
        )

        for net in all_nets:
            if not isinstance(net, str):
                continue
            net_upper = net.upper().replace(' ', '_')

            # Y.5 FIX: Try xVy notation FIRST (3V3 → 3.3, 1V8 → 1.8)
            # This must come before the simple \d+V regex to avoid
            # extracting just "3" from "3V3" instead of "3.3"
            xvy_match = re.search(config.VOLTAGE_XVY_PATTERN, net_upper)
            if xvy_match:
                whole = xvy_match.group(1)
                frac = xvy_match.group(2)
                net_voltages[net] = float(f"{whole}.{frac}")
                continue

            # Try explicit numeric voltage extraction from net name
            v_match = re.search(r'(\d+(?:\.\d+)?)\s*V', net_upper)
            if v_match:
                net_voltages[net] = float(v_match.group(1))
                continue

            # Try pattern matching
            matched = False
            for pattern, voltage in self._NET_VOLTAGE_PATTERNS:
                if pattern.upper() in net_upper:
                    net_voltages[net] = voltage if voltage is not None else system_max
                    matched = True
                    break

            if not matched:
                # Ground nets
                if any(g in net_upper for g in ('GND', 'GROUND', 'VSS', 'PGND', 'AGND', 'DGND')):
                    net_voltages[net] = 0.0

        return net_voltages

    def _get_component_rail_voltage(self, component: Dict) -> Optional[float]:
        """
        Fix 1.4: Determine the maximum voltage rail a component operates on.

        Looks up the component's connected nets via pinNetMapping and returns
        the highest voltage domain found. Returns None if no voltage domain
        can be determined (caller should fall back to system max).
        """
        comp_ref = component.get('ref', '')
        if not comp_ref or not self._pin_net_mapping:
            return None

        max_rail_voltage = 0.0
        found_any = False

        # Check all pins of this component
        for pin_key, net_name in self._pin_net_mapping.items():
            if not pin_key.startswith(f"{comp_ref}."):
                continue
            voltage = self._net_voltage_map.get(net_name)
            if voltage is not None and voltage > 0:
                max_rail_voltage = max(max_rail_voltage, voltage)
                found_any = True

        return max_rail_voltage if found_any else None

    def _get_required_voltage_for_component(self, component: Dict, derating_factor: float = 2.0) -> float:
        """
        Fix 1.4 + Phase I: Get the required voltage rating for a component,
        using per-rail voltage domain awareness with module-level override.

        Priority:
        1. Per-rail voltage from pinNetMapping (most precise — local net analysis)
        2. Module-level voltage domain from Step 2 (Phase I addition)
        3. System-level recommended_voltage_rating (fallback)

        Args:
            component: Component dict
            derating_factor: Derating multiplier (2.0 for MOSFETs, 1.5 for caps)

        Returns:
            Required voltage rating in V, or 0.0 if unknown.
        """
        # 1. Per-rail voltage from pinNetMapping
        rail_voltage = self._get_component_rail_voltage(component)
        if rail_voltage is not None and rail_voltage > 0:
            return rail_voltage * derating_factor

        # 2. Phase I: Module-level voltage domain from Step 2
        if self._module_voltage_domain is not None and self._module_voltage_domain > 0:
            return self._module_voltage_domain * derating_factor

        # 3. Fallback to system-level recommended rating
        if self.requirements and self.requirements.recommended_voltage_rating > 0:
            return self.requirements.recommended_voltage_rating

        return 0.0

    def _validate_component(self, component: Dict) -> None:
        """Validate a single component against requirements."""
        comp_type = component.get('type', '').lower()
        comp_ref = component.get('ref', 'UNKNOWN')
        comp_value = component.get('value', '')

        # Dispatch to type-specific validators
        if comp_type in ('mosfet', 'fet', 'nmos', 'pmos'):
            self._validate_mosfet(component)
        elif comp_type in ('transistor', 'bjt', 'npn', 'pnp'):
            self._validate_transistor(component)
        elif comp_type == 'diode':
            self._validate_diode(component)
        elif comp_type == 'capacitor':
            self._validate_capacitor(component)
        elif comp_type == 'resistor':
            self._validate_resistor(component)

    def _validate_mosfet(self, component: Dict) -> None:
        """Validate MOSFET against voltage requirements."""
        comp_ref = component.get('ref', 'UNKNOWN')
        comp_value = component.get('value', '').upper()

        actual_rating = self._lookup_voltage_rating(comp_value, 'MOSFET')

        if actual_rating is None:
            self.warnings.append(
                f"Unknown MOSFET {comp_ref}: {comp_value} - cannot verify voltage rating"
            )
            return

        required_rating = self._get_required_voltage_for_component(component, derating_factor=2.0)

        if required_rating > 0 and actual_rating < required_rating:
            self.violations.append(RatingViolation(
                component_ref=comp_ref,
                component_type='MOSFET',
                component_value=comp_value,
                violation_type='voltage',
                required_rating=required_rating,
                actual_rating=actual_rating,
                severity='critical',
                message=f"MOSFET {comp_ref} ({comp_value}) rated {actual_rating}V "
                       f"cannot handle required {required_rating:.0f}V",
                fix_suggestion=self._suggest_mosfet(required_rating)
            ))

    def _validate_transistor(self, component: Dict) -> None:
        """Validate BJT against voltage requirements."""
        comp_ref = component.get('ref', 'UNKNOWN')
        comp_value = component.get('value', '').upper()

        actual_rating = self._lookup_voltage_rating(comp_value, 'transistor')

        if actual_rating is None:
            self.warnings.append(
                f"Unknown transistor {comp_ref}: {comp_value} - cannot verify voltage rating"
            )
            return

        required_rating = self._get_required_voltage_for_component(component, derating_factor=2.0)

        if required_rating > 0 and actual_rating < required_rating:
            self.violations.append(RatingViolation(
                component_ref=comp_ref,
                component_type='transistor',
                component_value=comp_value,
                violation_type='voltage',
                required_rating=required_rating,
                actual_rating=actual_rating,
                severity='critical',
                message=f"Transistor {comp_ref} ({comp_value}) rated {actual_rating}V "
                       f"cannot handle required {required_rating:.0f}V",
                fix_suggestion=self._suggest_transistor(required_rating)
            ))

    def _validate_diode(self, component: Dict) -> None:
        """Validate diode against voltage requirements."""
        comp_ref = component.get('ref', 'UNKNOWN')
        comp_value = component.get('value', '').upper()

        actual_rating = self._lookup_voltage_rating(comp_value, 'diode')

        if actual_rating is None:
            return

        # Fix 1.4: Per-rail voltage domain awareness for diodes.
        required_rating = self._get_required_voltage_for_component(component, derating_factor=2.0)

        if required_rating > 0:
            # Diodes need special consideration - bootstrap diodes etc.
            # Only flag if significantly under-rated
            if actual_rating < required_rating * 0.5:
                self.violations.append(RatingViolation(
                    component_ref=comp_ref,
                    component_type='diode',
                    component_value=comp_value,
                    violation_type='voltage',
                    required_rating=required_rating,
                    actual_rating=actual_rating,
                    severity='warning',
                    message=f"Diode {comp_ref} ({comp_value}) rated {actual_rating}V "
                           f"may be under-rated for {required_rating:.0f}V system",
                    fix_suggestion=f"Consider using a higher voltage diode like 1N4007 (1000V) or UF4007 (1000V)"
                ))

    def _validate_capacitor(self, component: Dict) -> None:
        """
        Validate capacitor against voltage requirements.

        IMPORTANT: This method is now VOLTAGE-DOMAIN AWARE.
        Capacitors are validated against their LOCAL voltage domain, not the global system max.

        A bypass cap on a 3.3V rail only needs ~10V rating, not 720V!
        Only capacitors in high-voltage domains need high-voltage ratings.
        """
        comp_ref = component.get('ref', 'UNKNOWN')
        comp_value = component.get('value', '')

        # Try to extract voltage rating from value (e.g., "100uF/100V", "470uF 50V")
        voltage_match = re.search(r'(\d+)\s*V', comp_value, re.IGNORECASE)

        if voltage_match:
            actual_rating = int(voltage_match.group(1))

            # Determine the appropriate required rating based on component's voltage domain
            required_rating = self._get_capacitor_voltage_domain(component, actual_rating)

            if required_rating > 0 and actual_rating < required_rating:
                # Determine severity based on the margin
                margin = actual_rating / required_rating if required_rating > 0 else 1.0

                if margin < 0.5:
                    # Less than 50% of required - critical
                    severity = 'critical'
                elif margin < 0.8:
                    # 50-80% of required - warning
                    severity = 'warning'
                else:
                    # Close to required - just info, might be acceptable
                    return  # Skip minor discrepancies

                self.violations.append(RatingViolation(
                    component_ref=comp_ref,
                    component_type='capacitor',
                    component_value=comp_value,
                    violation_type='voltage',
                    required_rating=required_rating,
                    actual_rating=actual_rating,
                    severity=severity,
                    message=f"Capacitor {comp_ref} ({comp_value}) rated {actual_rating}V "
                           f"in {self._get_voltage_domain_name(component)} domain (requires {required_rating:.0f}V)",
                    fix_suggestion=f"Use capacitor rated for {int(required_rating)}V or higher"
                ))
        else:
            # No voltage rating specified - only warn for high voltage components
            if self._is_high_voltage_component(component):
                if self.requirements and self.requirements.voltage_class in ('high', 'medium'):
                    self.warnings.append(
                        f"Capacitor {comp_ref} ({comp_value}) in HV domain has no voltage rating - "
                        f"verify it can handle the high voltage"
                    )

    def _get_capacitor_voltage_domain(self, component: Dict, actual_rating: int) -> float:
        """
        Determine the required voltage rating based on the capacitor's voltage domain.

        This is GENERIC and works for ANY circuit type by analyzing:
        1. Component purpose (from purpose field)
        2. Connected net names (from component context)
        3. General capacitor application rules

        Returns the required voltage rating, or 0 if validation should be skipped.
        """
        comp_ref = component.get('ref', 'UNKNOWN')
        purpose = component.get('purpose', '').lower()
        specs = component.get('specs', {})

        # Check if purpose indicates voltage domain
        purpose_lower = purpose.lower() if purpose else ''

        # LOW VOLTAGE exclusion patterns - check these FIRST
        # These patterns indicate definitely low-voltage applications
        lv_exclusions = [
            'decoupling', 'bypass', 'filter capacitor', 'crystal',
            'oscillator', 'adc', 'dac', 'op-amp', 'opamp', 'comparator',
            'reference', 'vref', 'power supply decoupling', 'supply decoupling'
        ]
        if any(ex in purpose_lower for ex in lv_exclusions):
            # This is a low-voltage application, skip HV check
            pass
        else:
            # HIGH VOLTAGE indicators (use system max voltage)
            # Note: "bulk" alone removed - too ambiguous. Use specific patterns.
            hv_indicators = [
                'high voltage', 'hv ', 'hv_', 'main power', 'dc link', 'dc bus',
                'output stage', 'power stage', 'bridge', 'inverter', 'half-bridge',
                'full-bridge', 'h-bridge', 'transformer primary', 'rectifier output',
                'mains', 'ac line', 'dc rail', 'bus capacitor', 'snubber'
            ]
            if any(ind in purpose_lower for ind in hv_indicators):
                return self.requirements.recommended_voltage_rating if self.requirements else 0

        # LOW VOLTAGE rail indicators
        lv_patterns = {
            '3.3v': 10,    # 3.3V rail -> 10V cap minimum
            '3v3': 10,
            '5v': 16,      # 5V rail -> 16V cap minimum
            '12v': 25,     # 12V rail -> 25V cap minimum
            '15v': 35,     # ±15V rail -> 35V cap minimum
            '24v': 50,     # 24V rail -> 50V cap minimum
            'logic': 16,   # Logic supply -> 16V typical
            'digital': 16,
            'analog': 35,  # Analog could be ±15V
            'bypass': 16,  # Bypass caps usually low voltage
            'decoupling': 16,
            'regulator input': 50,  # Regulator input could be higher
            'regulator output': 16,
            'microcontroller': 10,
            'mcu': 10,
            'processor': 10,
            'fpga': 10,
            'oscillator': 16,
            'crystal': 16,
        }

        for pattern, min_rating in lv_patterns.items():
            if pattern in purpose_lower:
                # Add 50% margin (standard practice)
                return min_rating * 1.5

        # Check component value for clues
        comp_value = component.get('value', '').upper()

        # Very small capacitance values are typically low voltage (oscillator, filter)
        if 'PF' in comp_value or 'NF' in comp_value:
            # picofarads and nanofarads are usually low voltage
            # Unless already rated high, assume low voltage domain
            if actual_rating <= 100:
                return actual_rating * 1.5  # Just need reasonable margin

        # Large electrolytic/bulk caps might be power supply
        if 'UF' in comp_value:
            try:
                # Extract capacitance value
                cap_match = re.search(r'(\d+(?:\.\d+)?)\s*[uU]', comp_value)
                if cap_match:
                    cap_value = float(cap_match.group(1))
                    if cap_value >= 100:  # 100uF+ could be bulk/power supply
                        # Check if it's in HV section or LV section
                        if actual_rating >= 200:
                            # Already rated for high voltage - validate against system max
                            return self.requirements.recommended_voltage_rating if self.requirements else 0
                        else:
                            # Low voltage rated - probably in LV section
                            return actual_rating * 1.5
            except (ValueError, AttributeError):
                pass

        # DEFAULT: For unidentified capacitors, apply conservative rule
        # If capacitor is already rated reasonably (>= 50% of actual use case), accept it
        # This prevents false positives for bypass caps on low-voltage rails
        if actual_rating >= 25:
            # Capacitor rated 25V+ is likely adequate for most low-voltage applications
            return 0  # Skip validation - probably fine

        return 0  # Skip validation for unidentified low-voltage caps

    def _get_voltage_domain_name(self, component: Dict) -> str:
        """Get a human-readable name for the component's voltage domain."""
        purpose = component.get('purpose', '').lower()

        # Check low-voltage patterns FIRST (more specific)
        if any(x in purpose for x in ['bypass', 'decoupling', 'filter capacitor']):
            return 'bypass/decoupling'
        elif any(x in purpose for x in ['3.3v', '3v3']):
            return '3.3V'
        elif any(x in purpose for x in ['5v']):
            return '5V'
        elif any(x in purpose for x in ['12v']):
            return '12V'
        elif any(x in purpose for x in ['15v']):
            return '±15V'
        # Only THEN check high-voltage patterns
        elif any(x in purpose for x in ['high voltage', 'hv ', 'hv_', 'power stage',
                                         'dc link', 'bridge', 'inverter', 'mains']):
            return 'HIGH VOLTAGE'
        else:
            return 'unknown'

    def _is_high_voltage_component(self, component: Dict) -> bool:
        """Check if this component is in a high-voltage section of the circuit."""
        purpose = component.get('purpose', '').lower()

        # Low-voltage exclusions - definitely NOT high voltage
        lv_exclusions = [
            'decoupling', 'bypass', 'filter capacitor', 'crystal',
            'oscillator', 'adc', 'dac', 'op-amp', 'opamp', 'comparator'
        ]
        if any(ex in purpose for ex in lv_exclusions):
            return False

        # High-voltage indicators
        hv_indicators = [
            'high voltage', 'hv ', 'hv_', 'main power', 'dc link', 'dc bus',
            'output stage', 'power stage', 'bridge', 'inverter', 'half-bridge',
            'full-bridge', 'h-bridge', 'transformer primary', 'rectifier output',
            'mains', 'ac line', 'dc rail', 'bus capacitor', 'snubber'
        ]
        return any(ind in purpose for ind in hv_indicators)

    def _validate_resistor(self, component: Dict) -> None:
        """Validate resistor against power requirements."""
        # For now, just flag if it's a power application without power resistors
        comp_ref = component.get('ref', 'UNKNOWN')
        comp_value = component.get('value', '')
        package = component.get('package', '')

        # Check if high power application
        if self.requirements and self.requirements.power_class == 'high':
            # Small packages can't handle high power
            small_packages = ['0402', '0603', '0805']
            if package in small_packages:
                # Only flag current sense or power resistors
                if any(x in comp_value.lower() for x in ['0.1', '0.01', '0.05', '0.001']):
                    self.warnings.append(
                        f"Current sense resistor {comp_ref} ({comp_value}) in {package} package - "
                        f"verify power rating for high-power application"
                    )

    def _suggest_mosfet(self, required_voltage: float) -> str:
        """Suggest appropriate MOSFETs by querying the external DB."""
        db = self._load_external_ratings()
        candidates = []
        for part, entry in db.items():
            if entry.get('type', '').upper() != 'MOSFET':
                continue
            v = entry.get('voltage', 0)
            if v >= required_voltage:
                candidates.append((part, v, entry.get('current', 0)))

        if not candidates:
            return "Use specialized high-voltage MOSFETs or IGBT modules"

        # Sort by closest voltage match, then highest current
        candidates.sort(key=lambda x: (x[1], -x[2]))
        top = candidates[:3]
        suggestions = [f"{p} ({v}V, {c}A)" for p, v, c in top]
        return f"Use MOSFET such as: {', '.join(suggestions)}"

    def _suggest_transistor(self, required_voltage: float) -> str:
        """Suggest appropriate transistors by querying the external DB."""
        db = self._load_external_ratings()
        candidates = []
        for part, entry in db.items():
            if entry.get('type', '').lower() != 'transistor':
                continue
            v = entry.get('voltage', 0)
            if v >= required_voltage:
                candidates.append((part, v, entry.get('current', 0)))

        if not candidates:
            return "Use high-voltage transistors or consider IGBTs for very high voltage"

        candidates.sort(key=lambda x: (x[1], -x[2]))
        top = candidates[:3]
        suggestions = [f"{p} ({v}V)" for p, v, _ in top]
        return f"Use transistor such as: {', '.join(suggestions)}"

    def _create_result(self) -> ValidationResult:
        """Create the final validation result."""
        # Determine if validation passed
        critical_violations = [v for v in self.violations if v.severity == 'critical']
        passed = len(critical_violations) == 0

        # Create summary
        if passed and not self.violations:
            summary = "All component ratings are appropriate for the application requirements."
        elif passed:
            summary = f"Validation passed with {len(self.violations)} warnings to review."
        else:
            summary = (f"VALIDATION FAILED: {len(critical_violations)} critical violations found. "
                      f"Components would be damaged or destroyed.")

        return ValidationResult(
            passed=passed,
            violations=self.violations,
            warnings=self.warnings,
            summary=summary
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def validate_circuit_ratings(circuit: Dict, requirements_text: str) -> ValidationResult:
    """
    Convenience function to validate circuit against requirements text.

    Args:
        circuit: Circuit JSON
        requirements_text: Raw requirements text

    Returns:
        ValidationResult
    """
    # Extract requirements
    requirements = extract_requirements_ratings(requirements_text)

    # Validate
    validator = ComponentRatingValidator(requirements)
    return validator.validate_circuit(circuit)


def validate_circuit_with_extracted_requirements(
    circuit: Dict,
    requirements: ExtractedRequirements
) -> ValidationResult:
    """
    Validate circuit against already-extracted requirements.

    Args:
        circuit: Circuit JSON
        requirements: Pre-extracted requirements

    Returns:
        ValidationResult
    """
    validator = ComponentRatingValidator(requirements)
    return validator.validate_circuit(circuit)


# =============================================================================
# CLI FOR TESTING
# =============================================================================

if __name__ == "__main__":
    import sys

    # Test with a sample circuit
    test_circuit = {
        "circuit": {
            "components": [
                {"ref": "Q1", "type": "mosfet", "value": "IRFZ44N", "package": "TO-220"},
                {"ref": "Q2", "type": "mosfet", "value": "BSS138", "package": "SOT-23"},
                {"ref": "C1", "type": "capacitor", "value": "100uF/100V", "package": "RADIAL"},
                {"ref": "R1", "type": "resistor", "value": "10k", "package": "0603"},
            ]
        }
    }

    test_requirements = """
    High voltage ultrasonic driver:
    - Output: 360 Vpp, 200W
    - Frequency: 50kHz
    """

    print("=" * 60)
    print("COMPONENT RATING VALIDATOR TEST")
    print("=" * 60)

    # Extract requirements
    requirements = extract_requirements_ratings(test_requirements)
    print(f"\nExtracted Requirements:")
    print(f"  Max Voltage: {requirements.max_voltage}V")
    print(f"  Recommended Rating: {requirements.recommended_voltage_rating}V")

    # Validate
    validator = ComponentRatingValidator(requirements)
    result = validator.validate_circuit(test_circuit)

    print(f"\nValidation Result: {'PASSED' if result.passed else 'FAILED'}")
    print(f"Summary: {result.summary}")

    if result.violations:
        print(f"\nViolations ({len(result.violations)}):")
        for v in result.violations:
            print(f"  [{v.severity.upper()}] {v.message}")
            print(f"    Fix: {v.fix_suggestion}")

    if result.warnings:
        print(f"\nWarnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  - {w}")
