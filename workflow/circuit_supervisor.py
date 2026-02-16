# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Circuit Supervisor - Intelligent ERC Engine with Specialized Fixers
Guarantees 100% perfect circuits through iterative validation and targeted fixes
"""

import json
import copy
import re
from typing import Dict, List, Set, Tuple, Any, Optional
from pathlib import Path
from utils.logger import setup_logger
from server.config import config

logger = setup_logger(__name__)


def _is_power_rail(net_name: str) -> bool:
    """
    GENERIC power rail detection — handles ANY naming convention.
    Returns True if net_name matches common power rail patterns.

    All pattern data lives in config (single source of truth):
      config.POWER_RAIL_PREFIXES  — prefix strings (VCC, VDD, …)
      config.POWER_RAIL_EXACT     — exact-match set (V+, V-)
      config.POWER_RAIL_PATTERNS  — regex patterns (^V\\d+, ^[+-]\\d+, …)
    """
    if not net_name:
        return False

    net = net_name.upper().strip()

    for prefix in config.POWER_RAIL_PREFIXES:
        if net.startswith(prefix):
            return True

    if net in config.POWER_RAIL_EXACT:
        return True

    for pattern in config.POWER_RAIL_PATTERNS:
        if re.search(pattern, net):
            return True

    return False


def _is_ground_rail(net_name: str) -> bool:
    """
    GENERIC ground rail detection - handles ANY naming convention.
    Returns True if net_name matches common ground patterns.

    TC #93 FIX: Enhanced to detect ALL common ground naming conventions
    used across different circuit types:

    - Standard grounds: GND, AGND, DGND, PGND, SGND, CGND
    - Power grounds: HV_GND, LV_GND, PWR_GND
    - Reference grounds: VSS, VEE, GROUND, EARTH, CHASSIS
    - Isolated grounds: GND_ISO, ISO_GND
    - Return paths: GND_RTN, RTN
    - Zero reference: 0V, COM, COMMON
    - Negative rail references: NEG (when used as ground reference)

    This is GENERIC - works for:
    - Low voltage digital circuits (GND, DGND)
    - Analog circuits (AGND, SGND)
    - High voltage power supplies (HV_GND)
    - Motor drives (PGND, PWR_GND)
    - Mixed signal (AGND + DGND)
    - Isolated designs (GND_ISO)
    """
    if not net_name:
        return False

    net = net_name.upper().strip()

    # Use config.SUPERVISOR_GROUND_NETS as single source of truth
    for pattern in config.SUPERVISOR_GROUND_NETS:
        if pattern in net:
            return True

    # Also match patterns like GND1, GND2, GND_A, GND_B (multi-ground systems)
    if re.match(r'^GND[_\d]', net) or re.match(r'.*_GND$', net):
        return True

    return False


def _is_reference_or_shunt_device(comp_type: str, comp_value: str, comp_name: str) -> bool:
    """
    Detect reference/shunt/regulator devices that do not require a classical VCC pin.

    This function is intentionally GENERIC and pattern-based so it works across
    all circuit families and naming conventions without being tied to examples.

    Examples matched:
    - TL431/TLV431 families (programmable shunt references)
    - LM4040/LM4041 and similar fixed references
    - Generic names containing REF, VREF, SHUNT, REFERENCE
    """
    text = f"{comp_type} {comp_value} {comp_name}".upper()
    return any(k in text for k in config.REFERENCE_SHUNT_DEVICE_KEYWORDS)


def _is_power_supply_ic(comp_type: str, comp_value: str, comp_name: str) -> bool:
    """
    GENERIC detection of power supply ICs that ARE the power source (not consumers).
    These components should be SKIPPED during power/ground validation because they
    don't follow standard IC power requirements - they CREATE power rails.

    All pattern data lives in config.POWER_SUPPLY_IC_PATTERNS (single source of truth).

    Returns True if the component is a power supply IC that should skip validation.
    """
    text = f"{comp_type} {comp_value} {comp_name}".upper()
    patterns = config.POWER_SUPPLY_IC_PATTERNS

    # Generic power supply keywords
    if any(kw in text for kw in patterns['generic_keywords']):
        return True

    # Regex-based part number patterns (linear, LDO, switching, charge pump)
    for category in ('linear_reg_patterns', 'ldo_patterns',
                     'switching_patterns', 'charge_pump_patterns'):
        for pattern in patterns[category]:
            if re.search(pattern, text):
                return True

    # Generic manufacturer prefixes with power-related suffixes
    if comp_type.lower() in ['ic', 'regulator', 'power']:
        for prefix in patterns['power_prefixes']:
            if text.startswith(prefix) and re.search(r'\d{2,}', text):
                return True

    return False


def _is_negative_rail_ic(comp_type: str, comp_value: str, comp_name: str,
                         circuit: dict, comp_ref: str) -> bool:
    """
    GENERIC detection of ICs that operate on NEGATIVE voltage rails.
    These ICs do NOT connect to classical GND - instead they connect to
    negative voltage rails (V_NEG, -15V, etc.) as their "ground" reference.

    This is a FUNDAMENTAL electronics principle:
    - Positive regulators: VIN(+) → regulator → VOUT(+), with GND as reference
    - Negative regulators: GND → regulator → VOUT(-), with negative rail as "ground"

    Categories detected:
    1. Negative voltage regulators (LM79xx, LM337, etc.)
    2. Negative LDOs
    3. Components connected to negative voltage rails
    4. Inverting charge pumps (output side)

    Returns True if the component operates on negative rails and doesn't need GND.
    """
    text = f"{comp_type} {comp_value} {comp_name}".upper()

    # PATTERN 1: Negative voltage regulator part numbers (from config)
    for pattern in config.NEGATIVE_RAIL_IC_PATTERNS:
        if re.search(pattern, text):
            return True

    # PATTERN 2: Keywords indicating negative operation (from config)
    if any(kw in text for kw in config.NEGATIVE_RAIL_IC_KEYWORDS):
        return True

    # PATTERN 3: Context-based detection - check connected nets
    # If IC has no GND but IS connected to negative voltage rails, it's valid
    # ==========================================================================
    if circuit and comp_ref:
        pin_net_map = circuit.get('pinNetMapping', {})
        connected_to_negative_rail = False
        has_any_gnd = False

        for pin_ref, net in pin_net_map.items():
            if pin_ref.startswith(f"{comp_ref}."):
                net_upper = net.upper() if net else ''
                # Check for negative rail connections
                if any(neg in net_upper for neg in ['_NEG', 'NEG_', 'VNEG', 'V-',
                                                     'NEGATIVE', 'MINUS', 'V_NEG']):
                    connected_to_negative_rail = True
                # Also check for pattern like V15_NEG, V12_NEG, etc.
                if re.search(r'V\d+_?NEG|V_?NEG_?\d+|-\d+V', net_upper):
                    connected_to_negative_rail = True
                # Check if has any ground connection
                if _is_ground_rail(net):
                    has_any_gnd = True

        # If connected to negative rail but no GND, it's a negative-rail IC
        if connected_to_negative_rail and not has_any_gnd:
            return True

    return False


def _normalize_pin(pin: Any) -> Dict:
    """
    DEFENSIVE HELPER: Normalize a pin to the standard dictionary format.

    This function handles multiple pin formats that may appear in circuit data:
    1. Already a dictionary with 'number', 'name', 'type' keys -> return as-is
    2. A string (e.g., '1', '2') -> convert to standard dict format
    3. An integer -> convert to string then to dict
    4. A dictionary with only partial fields -> fill in defaults

    This makes the circuit supervisor robust to different input formats,
    preventing AttributeError crashes when processing circuits from various sources
    (AI-generated, fallback, legacy formats, etc.).

    Args:
        pin: A pin in any format (string, int, or dict)

    Returns:
        A normalized pin dictionary with 'number', 'name', 'type' keys
    """
    if isinstance(pin, dict):
        # Already a dictionary, ensure all required fields exist
        return {
            'number': str(pin.get('number', pin.get('name', '1'))),
            'name': str(pin.get('name', pin.get('number', '1'))),
            'type': pin.get('type', 'passive')
        }
    elif isinstance(pin, (str, int)):
        # String or integer pin number - convert to standard format
        pin_str = str(pin)
        return {
            'number': pin_str,
            'name': pin_str,
            'type': 'passive'
        }
    else:
        # Unknown format - return a safe default
        logger.warning(f"Unknown pin format: {type(pin).__name__} - {pin}")
        return {
            'number': '1',
            'name': '1',
            'type': 'passive'
        }


def _normalize_pins(pins: Any) -> List[Dict]:
    """
    DEFENSIVE HELPER: Normalize a list of pins to standard dictionary format.

    This is a wrapper around _normalize_pin that handles entire pin lists,
    ensuring all pins in a component are in the correct format before processing.

    Args:
        pins: A list of pins in any format, or None/empty

    Returns:
        A list of normalized pin dictionaries
    """
    if not pins:
        return []

    if not isinstance(pins, (list, tuple)):
        # Single pin passed instead of list - wrap it
        return [_normalize_pin(pins)]

    return [_normalize_pin(p) for p in pins]


class CircuitSupervisor:
    """
    Master controller that coordinates validation and fixing
    Uses ERC (Electrical Rule Check) to detect issues
    Dispatches to specialized fixers for each issue type
    """

    # Maximum stall iterations before early exit (no improvement detected)
    MAX_STALL_ITERATIONS = config.QUALITY_GATES["max_stall_iterations"]

    def __init__(self):
        self.issues_found = []
        self.fixes_applied = []
        self.iteration_count = 0
        self.max_iterations = config.QUALITY_GATES["max_supervisor_iterations"]

        # Initialize specialized fixers
        self.fixers = {
            'power_connections': PowerConnectionFixer(),
            'floating_components': FloatingComponentFixer(),
            'single_ended_nets': SingleEndedNetFixer(),
            'net_conflicts': NetConflictFixer(),
            'pin_mismatches': PinMismatchFixer(),
            'structure_issues': StructureIssueFixer(),
            'shorted_passives': ShortedPassiveFixer(),
            'rating_violations': RatingFixer(),
        }

    def supervise_and_fix(self, circuit: Dict) -> Dict:
        """
        Main supervision loop - iterate until perfect
        """
        logger.info("=" * 80)
        logger.info("CIRCUIT SUPERVISOR - STARTING VALIDATION AND REPAIR")
        logger.info("=" * 80)

        circuit = copy.deepcopy(circuit)

        # =====================================================================
        # TC #93 CRITICAL FIX: Ensure ALL components have pins BEFORE validation
        # This is the ROOT CAUSE of the 3-month bug:
        # - If components don't have pins, ALL pinNetMapping entries get deleted
        # - Result: circuits with 0 connections
        #
        # This fix is GENERIC - works for ANY circuit type by inferring pins
        # from the pinNetMapping data structure.
        # =====================================================================
        circuit = self._ensure_components_have_pins(circuit)

        # Phase J (Forensic Fix 20260208): Deterministic IC power connection
        # post-processor. Runs BEFORE the fix loop to catch the most common AI
        # failure: omitting VCC/GND connections on ICs.
        circuit = self._ensure_ic_power_connections(circuit)

        # Convergence tracking: detect when fixes stop making progress
        prev_issue_count = None
        stall_counter = 0

        while self.iteration_count < self.max_iterations:
            self.iteration_count += 1
            logger.info(f"\n--- Iteration {self.iteration_count} ---")

            # Run comprehensive ERC check
            erc_report = self.run_erc_check(circuit)

            if erc_report['passed']:
                logger.info("CIRCUIT IS 100% PERFECT!")
                break

            current_issue_count = erc_report['total_issues']
            logger.info(f"Issues remaining: {current_issue_count}")

            # Convergence detection: if issue count isn't decreasing, stop early
            if prev_issue_count is not None:
                if current_issue_count >= prev_issue_count:
                    stall_counter += 1
                    logger.warning(
                        f"No improvement: {current_issue_count} issues "
                        f"(stall {stall_counter}/{self.MAX_STALL_ITERATIONS})"
                    )
                    if stall_counter >= self.MAX_STALL_ITERATIONS:
                        # Log which categories are non-convergent
                        stalled_categories = [
                            f"{cat}({len(items)})"
                            for cat, items in erc_report['issues'].items()
                            if items
                        ]
                        logger.warning(
                            f"Fixer loop stalled after {self.iteration_count} iterations. "
                            f"Non-convergent categories: {', '.join(stalled_categories)}"
                        )
                        break
                else:
                    stall_counter = 0  # Reset on improvement

            prev_issue_count = current_issue_count

            # Fix issues by priority
            circuit = self.dispatch_fixes(circuit, erc_report)

            # Rebuild connections after fixes
            circuit = self.rebuild_circuit_structure(circuit)

        # Final validation
        final_report = self.run_erc_check(circuit)

        if not final_report['passed']:
            remaining_count = final_report['total_issues']
            remaining_categories = {
                cat: len(items) for cat, items in final_report['issues'].items() if items
            }

            # Phase C (Forensic Fix 20260208): Classify remaining issues as
            # solvable vs unsolvable. Unsolvable issues (pin-reference net names,
            # malformed connections) can't be fixed by the circuit fixer and
            # require upstream integration agent fixes.
            solvable_count, unsolvable_count, unsolvable_issues = self._classify_remaining_issues(final_report)

            logger.error(
                f"Circuit has {remaining_count} issues after "
                f"{self.iteration_count} iterations: {remaining_categories}"
            )
            if unsolvable_count > 0:
                logger.error(
                    f"  {unsolvable_count} UNSOLVABLE issues "
                    f"(require integration agent fix, not solvable by circuit fixer)"
                )

            circuit['validation_status'] = 'IMPERFECT'
            circuit['validation_issues'] = final_report['issues']
            circuit['validation_remaining_count'] = remaining_count
            circuit['validation_categories'] = remaining_categories
            circuit['validation_solvable_count'] = solvable_count
            circuit['validation_unsolvable_count'] = unsolvable_count
            circuit['validation_unsolvable_issues'] = unsolvable_issues
        else:
            circuit['validation_status'] = 'PERFECT'
            circuit['validation_remaining_count'] = 0
            circuit['validation_categories'] = {}
            circuit['validation_solvable_count'] = 0
            circuit['validation_unsolvable_count'] = 0
            circuit['validation_unsolvable_issues'] = []

        return circuit

    # Pre-compiled pin-reference regex — use config's pre-compiled version
    _PIN_REF_RE = config.PIN_REFERENCE_PATTERN_RE

    def _classify_remaining_issues(self, erc_report: Dict) -> Tuple[int, int, List[Dict]]:
        """
        Phase C (Forensic Fix 20260208): Classify remaining ERC issues as
        solvable or unsolvable.

        Solvable: Missing power pin, shorted passive, floating pin with
                  identifiable target — the circuit fixer CAN fix these.

        Unsolvable: Pin-reference net names (e.g., "U2.6"), malformed
                    connections — these require upstream integration agent
                    fixes, NOT circuit fixer.

        Returns:
            (solvable_count, unsolvable_count, unsolvable_issues_list)
        """
        solvable_count = 0
        unsolvable_count = 0
        unsolvable_issues = []

        for category, issues in erc_report.get('issues', {}).items():
            for issue in issues:
                issue_str = str(issue)
                # Check if issue involves a pin-reference net name
                if self._PIN_REF_RE.search(issue_str):
                    unsolvable_count += 1
                    unsolvable_issues.append({
                        'category': category,
                        'issue': issue,
                        'reason': 'Pin-reference net name — requires integration agent fix',
                    })
                elif 'malformed' in issue_str.lower() or 'invalid' in issue_str.lower():
                    unsolvable_count += 1
                    unsolvable_issues.append({
                        'category': category,
                        'issue': issue,
                        'reason': 'Malformed connection — requires upstream fix',
                    })
                else:
                    solvable_count += 1

        return solvable_count, unsolvable_count, unsolvable_issues

    # Y.1 FIX: Power pin names migrated to config.SUPERVISOR_POWER_PIN_NAMES
    # (single source of truth — covers VPOS, VNEG, VS+, VS-, domain-specific, etc.)
    _POWER_PIN_NAMES = config.SUPERVISOR_POWER_PIN_NAMES
    # Fix G.4: Use expanded ground pin names from config
    _GROUND_PIN_NAMES = config.SUPERVISOR_GROUND_PIN_NAMES

    def _is_active_device(self, comp_type: str, ref: str, pins: List[Dict]) -> bool:
        """
        Fix K.1 (Forensic Fix 20260211): Robust semantic classification.

        Determines if a component is an active device requiring power/ground
        by analyzing multiple signals with proper exclusion of ALL non-active
        taxonomy categories (PASSIVE, INTERCONNECT, SEMICONDUCTOR,
        ELECTROMECHANICAL, MECHANICAL).

        Signals (evaluated in order — first match wins):
        1. Explicit ACTIVE_IC taxonomy match → True
        2. Explicit NON_ACTIVE taxonomy match → False (early exit)
        3. Pin role analysis (power_in/ground pins on non-excluded types)
        4. Reference designator 'U' prefix (fallback, uses original_ref)
        5. Complexity heuristic (5+ pins, excludes non-active types)
        """
        comp_type_lower = comp_type.lower()

        # Fix K.17: For prefixed refs from integration (e.g. "PWR_U1"),
        # extract the original reference designator for classification.
        bare_ref = ref
        if '_' in ref and not ref[0].isdigit():
            # Attempt to extract original ref: "PWR_U1" → "U1", "CHA_R5" → "R5"
            parts = ref.rsplit('_', 1)
            candidate = parts[-1]
            if candidate and candidate[0].isalpha():
                bare_ref = candidate

        # Signal 1: Explicit ACTIVE_IC taxonomy (highest confidence)
        if comp_type_lower in config.ACTIVE_COMPONENT_TYPES:
            return True

        # Signal 2: Explicit NON-ACTIVE taxonomy (early exit)
        # Fix K.1: This now covers PASSIVE, INTERCONNECT, SEMICONDUCTOR,
        # ELECTROMECHANICAL, and MECHANICAL — not just passives.
        if comp_type_lower in config.NON_ACTIVE_COMPONENT_TYPES:
            return False

        # Signal 3: Pin role analysis
        # If any pin is explicitly marked as power_in or ground, AND the
        # component type is not in any non-active category, classify as active.
        # Since Signal 2 already returned False for non-active types,
        # reaching here means the type is unclassified — proceed cautiously.
        has_power_roles = False
        for pin in pins:
            pin_type = pin.get('type', '').lower()
            if pin_type in ('power_in', 'power_out', 'ground'):
                has_power_roles = True
                break
        if has_power_roles:
            return True

        # Signal 4: Reference designator 'U' prefix (ICs)
        if bare_ref.startswith('U'):
            return True

        # Signal 5: Complexity heuristic (5+ pins on unclassified type)
        # Connectors and other multi-pin non-active types already exited
        # at Signal 2. Anything remaining with 5+ pins is likely an IC.
        if len(pins) >= 5:
            return True

        return False

    def _ensure_ic_power_connections(self, circuit: Dict) -> Dict:
        """
        Phase J (Forensic Fix 20260208): Deterministic IC power connection fixer.

        For every component with type in config.ACTIVE_COMPONENT_TYPES:
        - Check if VCC/VDD/V+ pin is connected to a power rail
        - Check if GND/VSS/V- pin is connected to a ground rail
        - If NOT connected: find the nearest power/ground rail in the circuit
          and add the connection
        - Log every auto-added connection as WARNING

        This is a SAFETY NET for the most common AI failure (omitting IC power pins).
        Runs BEFORE the fix loop to reduce initial issue count.

        Generic: Works with ANY circuit — uses pin name patterns, not part numbers.
        """
        components = circuit.get('components', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})

        if not components or not pin_net_mapping:
            return circuit

        # Find existing power and ground rails in the circuit
        power_rails = set()
        ground_rails = set()
        for net_name in set(pin_net_mapping.values()):
            if _is_power_rail(net_name):
                power_rails.add(net_name)
            elif _is_ground_rail(net_name):
                ground_rails.add(net_name)

        # Default rails if we can identify them
        default_power = 'VCC' if 'VCC' in power_rails else (next(iter(power_rails), None) if power_rails else None)
        default_ground = 'GND' if 'GND' in ground_rails else (next(iter(ground_rails), None) if ground_rails else None)

        if not default_power and not default_ground:
            logger.debug("Phase J: No power/ground rails found in circuit — skipping post-processor")
            return circuit

        auto_connections = 0

        for comp in components:
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()

            # Only process active components (ICs that need power)
            if comp_type not in config.ACTIVE_COMPONENT_TYPES and not ref.startswith('U'):
                continue

            pins = comp.get('pins', [])
            if not pins:
                continue

            has_power = False
            has_ground = False
            power_pin_ref = None
            ground_pin_ref = None

            for pin in pins:
                if isinstance(pin, dict):
                    pin_name = pin.get('name', '').upper()
                    pin_num = pin.get('number', '')
                else:
                    pin_name = str(pin).upper()
                    pin_num = str(pin)

                pin_ref = f"{ref}.{pin_num}"

                # Check if this is a power pin
                if pin_name in self._POWER_PIN_NAMES:
                    existing_net = pin_net_mapping.get(pin_ref, '')
                    if existing_net and _is_power_rail(existing_net):
                        has_power = True
                    elif not power_pin_ref:
                        power_pin_ref = pin_ref

                # Check if this is a ground pin
                if pin_name in self._GROUND_PIN_NAMES:
                    existing_net = pin_net_mapping.get(pin_ref, '')
                    if existing_net and _is_ground_rail(existing_net):
                        has_ground = True
                    elif not ground_pin_ref:
                        ground_pin_ref = pin_ref

            # Auto-connect missing power
            if not has_power and power_pin_ref and default_power:
                pin_net_mapping[power_pin_ref] = default_power
                auto_connections += 1
                logger.warning(
                    f"Phase J: Auto-connected {power_pin_ref} to {default_power} "
                    f"— AI omitted power connection for {ref}"
                )

            # Auto-connect missing ground
            if not has_ground and ground_pin_ref and default_ground:
                pin_net_mapping[ground_pin_ref] = default_ground
                auto_connections += 1
                logger.warning(
                    f"Phase J: Auto-connected {ground_pin_ref} to {default_ground} "
                    f"— AI omitted ground connection for {ref}"
                )

        if auto_connections > 0:
            logger.info(f"Phase J: Auto-added {auto_connections} IC power/ground connections")
            circuit['pinNetMapping'] = pin_net_mapping

        return circuit

    def _ensure_components_have_pins(self, circuit: Dict) -> Dict:
        """
        TC #93 CRITICAL FIX: Ensure ALL components have pins defined.

        This is a DEFENSE-IN-DEPTH fix that reconstructs pins from pinNetMapping
        when components are missing their pins field. Without this fix:
        - Components without pins cause pinNetMapping validation to delete entries
        - Result: circuits with 0 connections, 2-component fallback

        This method is GENERIC - works for ANY circuit type by:
        1. Finding all pins referenced in pinNetMapping for each component
        2. Creating pin definitions from those references
        3. Using component type to infer additional pin metadata

        Args:
            circuit: The circuit dict to validate

        Returns:
            Circuit dict with all components having pins defined
        """
        components = circuit.get('components', [])
        pinNetMapping = circuit.get('pinNetMapping', {})

        if not components or not pinNetMapping:
            return circuit

        # Build map of component ref -> pins from pinNetMapping
        comp_pins_from_mapping = {}
        for pin_ref in pinNetMapping.keys():
            if '.' in pin_ref:
                comp_ref, pin_num = pin_ref.rsplit('.', 1)
                if comp_ref not in comp_pins_from_mapping:
                    comp_pins_from_mapping[comp_ref] = set()
                comp_pins_from_mapping[comp_ref].add(pin_num)

        # Check each component and add pins if missing
        fixed_count = 0
        for comp in components:
            ref = comp.get('ref', '')
            existing_pins = comp.get('pins', [])

            # If component already has pins, skip
            if existing_pins:
                continue

            # Get pins from pinNetMapping
            pins_from_mapping = comp_pins_from_mapping.get(ref, set())

            if not pins_from_mapping:
                # No pins in mapping either - this component is truly orphaned
                # Generate default pins based on component type
                comp_type = comp.get('type', '').lower()
                pins_from_mapping = self._get_default_pin_numbers(comp_type)

            # Create pin definitions
            new_pins = []
            for pin_num in sorted(pins_from_mapping, key=lambda x: (len(x), x)):
                new_pins.append({
                    'number': str(pin_num),
                    'name': str(pin_num),
                    'type': 'passive'  # Default type, can be refined later
                })

            comp['pins'] = new_pins
            fixed_count += 1
            logger.info(f"TC #93 FIX: Generated {len(new_pins)} pins for {ref} from pinNetMapping")

        if fixed_count > 0:
            logger.info(f"TC #93 FIX: Fixed {fixed_count} components with missing pins")

        return circuit

    def _get_default_pin_numbers(self, comp_type: str) -> Set[str]:
        """
        Get default pin numbers for a component type.

        This is GENERIC - provides reasonable defaults for ANY component type.
        Used when a component has no pins defined AND no pinNetMapping entries.

        Args:
            comp_type: The component type (e.g., 'resistor', 'ic', 'mosfet')

        Returns:
            Set of pin number strings
        """
        # 2-pin passives
        if comp_type in ['resistor', 'capacitor', 'inductor', 'diode', 'led',
                         'fuse', 'ferrite', 'varistor', 'thermistor']:
            return {'1', '2'}

        # 3-pin components
        if comp_type in ['transistor', 'bjt', 'mosfet', 'igbt', 'regulator',
                         'voltage_regulator', 'ldo', 'triac']:
            return {'1', '2', '3'}

        # 4-pin components
        if comp_type in ['bridge', 'bridge_rectifier', 'optocoupler', 'relay']:
            return {'1', '2', '3', '4'}

        # 8-pin ICs (default for unknown ICs)
        if comp_type in ['ic', 'opamp', 'amplifier', 'comparator', 'timer']:
            return {'1', '2', '3', '4', '5', '6', '7', '8'}

        # Default: 2 pins (most conservative default for passives)
        return {'1', '2'}

    def run_erc_check(self, circuit: Dict) -> Dict:
        """
        Comprehensive Electrical Rule Check
        Returns detailed report of ALL issues
        """
        issues = {
            'power_connections': [],
            'floating_components': [],
            'single_ended_nets': [],
            'net_conflicts': [],
            'pin_mismatches': [],
            'structure_issues': [],
            'shorted_passives': [],  # TC #91: 2-terminal passives with both pins on same net
            'rating_violations': [],
            'feedback_divider': [],  # Fix K.10: Feedback divider accuracy
            'pin_function_mismatch': [],  # Fix K.14: Pin-function wiring errors
        }

        # Check 1: Power connections
        issues['power_connections'] = self._check_power_connections(circuit)

        # Check 2: Floating components
        issues['floating_components'] = self._check_floating_components(circuit)

        # Check 3: Single-ended nets
        issues['single_ended_nets'] = self._check_single_ended_nets(circuit)

        # Q.6 FIX: Collect nets already flagged as single-ended so the structure
        # check can skip them for insufficient_connection_points (dedup).
        _single_ended_net_names = frozenset(
            issue['net'] for issue in issues['single_ended_nets']
            if isinstance(issue, dict) and 'net' in issue
        )

        # Check 4: Net conflicts
        issues['net_conflicts'] = self._check_net_conflicts(circuit)

        # Check 5: Pin mismatches
        issues['pin_mismatches'] = self._check_pin_mismatches(circuit)

        # Check 6: Structure issues (receives single-ended set for dedup)
        issues['structure_issues'] = self._check_structure_issues(
            circuit, skip_nets=_single_ended_net_names
        )

        # Check 7: Shorted passives (TC #91 - critical for SPICE simulation)
        issues['shorted_passives'] = self._check_shorted_passives(circuit)

        # Check 8: Component rating violations
        issues['rating_violations'] = self._check_rating_violations(circuit)

        # Check 9: Feedback divider accuracy (Fix K.10)
        issues['feedback_divider'] = self._check_feedback_dividers(circuit)

        # Check 10: Pin-function mismatch (Fix K.14)
        issues['pin_function_mismatch'] = self._check_pin_function_mismatch(circuit)

        # Count total issues
        total_issues = sum(len(v) for v in issues.values())

        # Fix H.8: Compute severity breakdown across all issue categories.
        # Each individual issue may carry its own 'severity' key (from
        # _check_structure_issues).  For categories that don't tag per-issue
        # severity, fall back to the category-level default in config.
        _sev_cfg = config.ISSUE_SEVERITY
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for category, items in issues.items():
            cat_default = _sev_cfg.get(category, "MEDIUM")
            for item in items:
                sev = item.get('severity', cat_default) if isinstance(item, dict) else cat_default
                severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # Log summary
        if total_issues > 0:
            logger.info(f"ERC Check found {total_issues} issues:")
            for category, items in issues.items():
                if items:
                    logger.info(f"  - {category}: {len(items)}")
            if severity_counts["CRITICAL"] > 0:
                logger.warning(
                    f"  Severity breakdown: CRITICAL={severity_counts['CRITICAL']}, "
                    f"HIGH={severity_counts['HIGH']}, MEDIUM={severity_counts['MEDIUM']}, "
                    f"LOW={severity_counts['LOW']}"
                )

        return {
            'passed': total_issues == 0,
            'total_issues': total_issues,
            'issues': issues,
            'severity_counts': severity_counts,
        }

    def _check_power_connections(self, circuit: Dict) -> List[Dict]:
        """Check for missing or incorrect power connections - ENFORCES 100% COMPLETION"""
        issues = []

        for comp in circuit.get('components', []):
            ref = comp.get('ref', '')
            # DEFENSIVE: Normalize pins to standard dict format
            # This handles string pins ['1','2'] and dict pins [{'number':'1',...}]
            pins = _normalize_pins(comp.get('pins', []))
            comp_type = comp.get('type', '').lower()
            comp_value = comp.get('value', '').upper()
            comp_name = comp.get('name', '').upper()

            # =================================================================
            # SKIP POWER SUPPLY ICs - GENERIC PATTERN-BASED DETECTION
            # Power supply ICs ARE the power source, not consumers.
            # They don't follow standard IC power requirements.
            # Uses _is_power_supply_ic() for comprehensive pattern matching.
            # =================================================================
            if _is_power_supply_ic(comp_type, comp_value, comp_name):
                logger.debug(f"Skipping power supply IC: {ref} ({comp_value})")
                continue  # Skip power supply components

            # =================================================================
            # SKIP RELAYS - they can have switched ground connections
            # This is a GENERIC exception applicable to all relay types
            # =================================================================
            if comp_type == 'relay':
                continue  # Relays don't require direct ground (can be switched)

            # =================================================================
            # SKIP OPTOCOUPLERS — Fix III.2
            # Optocouplers have LED anode/cathode + transistor emitter/collector.
            # They do NOT have VCC/GND pins. Exempt from power checks.
            # =================================================================
            if any(pat in comp_value for pat in config.OPTOCOUPLER_PART_PATTERNS):
                logger.debug(f"Skipping optocoupler: {ref} ({comp_value})")
                continue
            if comp_type in ('optocoupler', 'opto_isolator', 'photocoupler'):
                logger.debug(f"Skipping optocoupler by type: {ref} ({comp_type})")
                continue

            # =================================================================
            # CRITICAL: For ICs and active components, ENFORCE power connections
            # Phase B (Forensic Fix 20260211): Use robust semantic classification
            # instead of simple reference prefix heuristics.
            # =================================================================
            requires_power = self._is_active_device(comp_type, ref, pins)

            # Type-aware exception for references/shunt regulators
            is_ref_shunt = _is_reference_or_shunt_device(comp_type, comp_value, comp_name)

            # =================================================================
            # NEGATIVE RAIL IC DETECTION - GENERIC
            # Negative voltage regulators and ICs on negative rails don't need
            # classical GND - they use negative voltage rails as reference.
            # =================================================================
            is_negative_rail = _is_negative_rail_ic(comp_type, comp_value, comp_name,
                                                    circuit, ref)

            if requires_power:
                # MANDATE: Every IC MUST have power and ground
                has_vcc = False
                has_gnd = False
                has_negative_supply = False  # Fix G.4: dual-supply detection

                for pin in pins:
                    pin_num = pin.get('number', '')
                    pin_name = pin.get('name', '').upper()
                    pin_ref = f"{ref}.{pin_num}"
                    actual_net = circuit.get('pinNetMapping', {}).get(pin_ref, '')

                    if actual_net:
                        # GENERIC power rail detection - handles ALL naming conventions
                        if _is_power_rail(actual_net):
                            has_vcc = True
                        # Q.2 FIX: Also check pin name for power (symmetric with
                        # ground pin-name check below). Handles cases where the net
                        # name is unconventional but the pin is clearly a power pin.
                        elif pin_name in self._POWER_PIN_NAMES:
                            has_vcc = True
                        # Fix G.4: Expanded ground detection — check both net name
                        # and pin name against comprehensive ground lists.
                        if _is_ground_rail(actual_net):
                            has_gnd = True
                        elif actual_net.upper() in config.SUPERVISOR_GROUND_NETS:
                            has_gnd = True
                        elif pin_name in config.SUPERVISOR_GROUND_PIN_NAMES:
                            has_gnd = True
                        # Fix G.4: Dual-supply ICs with V-/VEE connected to a
                        # negative rail don't need a separate GND pin.
                        if pin_name in config.SUPERVISOR_NEGATIVE_SUPPLY_PIN_NAMES:
                            if actual_net and (
                                _is_power_rail(actual_net) or
                                any(neg in actual_net.upper() for neg in
                                    ['NEG', '-15V', '-12V', '-5V', 'V-', 'VEE'])
                            ):
                                has_negative_supply = True

                # CRITICAL FAILURE if IC has no power
                # Reference/shunt devices are valid with GND + reference/sense nets;
                # they do not require a literal VCC/VDD pin. In that case, skip
                # the ic_missing_power error and only enforce ground presence.
                if not has_vcc and not is_ref_shunt:
                    issues.append({
                        'type': 'ic_missing_power',
                        'component': ref,
                        'component_type': comp_type,
                        'message': f'IC {ref} has NO POWER CONNECTION - circuit will not work!'
                    })

                # =============================================================
                # GROUND CHECK - with NEGATIVE RAIL EXCEPTION
                # Negative-rail ICs (like LM337, LM7905) don't connect to GND.
                # They use negative voltage rails as their reference.
                # Fix G.4: Dual-supply ICs with V-/VEE on negative rail also OK.
                # Q.5 FIX: Reference/shunt devices (TL431, LM431, etc.) may
                # use cathode/anode as ground reference — exempt from check
                # (symmetric with VCC exemption at line 920).
                # =============================================================
                if not has_gnd and not is_negative_rail and not has_negative_supply and not is_ref_shunt:
                    issues.append({
                        'type': 'ic_missing_ground',
                        'component': ref,
                        'component_type': comp_type,
                        'message': f'IC {ref} has NO GROUND CONNECTION - circuit will not work!'
                    })
                elif not has_gnd and is_negative_rail:
                    logger.debug(f"IC {ref} ({comp_value}) operates on negative rail - no GND required")

            # Also check pin-type based detection for additional safety
            for pin in pins:
                pin_num = pin.get('number', '')
                pin_name = pin.get('name', '').upper()
                pin_type = pin.get('type', '').lower()
                pin_ref = f"{ref}.{pin_num}"

                actual_net = circuit.get('pinNetMapping', {}).get(pin_ref, None)

                # Skip signal pins
                if actual_net:
                    actual_upper = actual_net.upper()
                    if any(x in actual_upper for x in ['GATE', 'SIGNAL', 'OUTPUT', 'INPUT', 'PWM', 'ENABLE']):
                        continue

                # Check if this is a power pin by type OR name
                is_power_pin = False
                expected_net = None

                if pin_type == 'power' or pin_name in ['VCC', 'VDD', 'V+', 'GND', 'VSS', 'V-', 'GROUND']:
                    is_power_pin = True
                    if pin_name in ['VCC', 'VDD', 'V+']:
                        expected_net = 'VCC'
                    elif pin_name in ['GND', 'VSS', 'V-', 'GROUND']:
                        expected_net = 'GND'
                    elif 'VIN' in pin_name:
                        expected_net = 'VCC_INPUT'

                if is_power_pin and actual_net is None:
                    issues.append({
                        'type': 'unconnected_power_pin',
                        'component': ref,
                        'pin': pin_ref,
                        'pin_name': pin_name,
                        'expected_net': expected_net
                    })

        return issues

    def _check_floating_components(self, circuit: Dict) -> List[Dict]:
        """
        Check for components with no or partial connections.

        TC #95 Enhancement: Now also specifically detects floating IC input pins,
        which is a CRITICAL issue that can cause undefined behavior in digital
        circuits or oscillation in analog circuits.
        """
        issues = []

        # Get all connected pins
        connected_pins = set(circuit.get('pinNetMapping', {}).keys())
        pin_net_mapping = circuit.get('pinNetMapping', {})

        for comp in circuit.get('components', []):
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()
            # DEFENSIVE: Normalize pins to standard dict format
            pins = _normalize_pins(comp.get('pins', []))

            # Skip non-electrical components
            if any(x in comp_type for x in ['heatsink', 'mounting', 'fiducial', 'mechanical']):
                continue

            if not pins:
                continue

            # Check how many pins are connected
            total_pins = len(pins)
            connected_count = 0
            unconnected_pins = []
            floating_input_pins = []  # TC #95: Track floating inputs specifically

            for pin in pins:
                # Pins are now guaranteed to be dicts after normalization
                pin_num = pin.get('number') or pin.get('name') or ''
                pin_name = pin.get('name', '').upper()
                pin_type = pin.get('type', '').lower()
                pin_ref = f"{ref}.{pin_num}"

                if pin_ref in connected_pins:
                    connected_count += 1
                else:
                    # Store the full pin data for the fixer
                    unconnected_pins.append(pin)

                    # TC #95: Specifically flag floating INPUT pins on ICs
                    # These are CRITICAL issues that can cause circuit malfunction
                    is_ic = comp_type in config.ACTIVE_COMPONENT_TYPES or ref.startswith('U')
                    is_input = (pin_type == 'input' or
                               any(x in pin_name for x in ['IN', 'INPUT', 'GATE', 'ENABLE',
                                                           'CLK', 'DATA', 'ADDR', 'RESET']))
                    # Exclude NC pins and test pins
                    is_nc = 'NC' in pin_name or 'TEST' in pin_name or 'RESERVED' in pin_name

                    if is_ic and is_input and not is_nc:
                        floating_input_pins.append(pin)

            # If component has unconnected pins, it's floating (partially or fully)
            if connected_count < total_pins:
                issues.append({
                    'type': 'floating_component',
                    'component': ref,
                    'component_type': comp_type,
                    'connected_pins': connected_count,
                    'total_pins': total_pins,
                    'unconnected_pins': unconnected_pins
                })

            # TC #95: Add specific warning for floating IC inputs
            if floating_input_pins:
                for pin in floating_input_pins:
                    pin_num = pin.get('number') or pin.get('name') or ''
                    pin_name = pin.get('name', pin_num)
                    issues.append({
                        'type': 'floating_ic_input',
                        'component': ref,
                        'component_type': comp_type,
                        'pin': f"{ref}.{pin_num}",
                        'pin_name': pin_name,
                        'severity': 'critical',
                        'message': f'IC {ref} has floating input pin {pin_name} - may cause undefined behavior!'
                    })
                    logger.warning(f"TC #95: Floating IC input detected: {ref}.{pin_num} ({pin_name})")

        return issues

    def _check_single_ended_nets(self, circuit: Dict) -> List[Dict]:
        """
        Check for nets connected to only one pin.

        IMPORTANT: This check is SMARTER about interface signals.
        Not all single-ended nets are problems:

        1. NC pins - intentionally unconnected
        2. Interface signals - connect to other modules (SPI, I2C, UART, etc.)
        3. External connections - connector pins to outside world
        4. Power inputs - come from other modules
        5. MCU port pins - exposed for external connection

        Only flag INTERNAL signals that should connect 2+ components but don't.

        V-SERIES FIX: Uses STRUCTURAL rules (component type, ref prefix from
        config) instead of hardcoded ref checks. Works for any connector naming
        convention (J1, X1, P1, CN1, CONN1).
        """
        issues = []

        # STRUCTURAL: Build component type lookup from circuit data.
        # This allows detection by COMPONENT TYPE (structural) in addition to
        # ref prefix (pattern) — works even if naming convention is non-standard.
        comp_type_map = {}
        for comp in circuit.get('components', []):
            comp_ref = comp.get('ref', '')
            comp_type_map[comp_ref] = (comp.get('type', '') or '').lower()

        # Count connections per net
        net_connections = {}
        for pin, net in circuit.get('pinNetMapping', {}).items():
            if net not in net_connections:
                net_connections[net] = []
            net_connections[net].append(pin)

        for net, pins in net_connections.items():
            if len(pins) == 1:
                pin = pins[0]
                ref = pin.split('.')[0]
                net_upper = net.upper()

                # =================================================================
                # CATEGORY 1: Always OK to be single-ended
                # =================================================================

                # STRUCTURAL: Test points — check type OR ref prefix (config-driven)
                comp_type = comp_type_map.get(ref, '')
                if (comp_type in ('testpoint', 'test_point')
                        or any(ref.startswith(p) for p in config.TESTPOINT_REF_PREFIXES)):
                    continue

                # NC (No Connect) pins — any net containing NC
                if 'NC' in net_upper or net_upper.startswith('NC_'):
                    continue

                # Debug/Test nets
                if any(x in net_upper for x in ['TEST', 'DEBUG', 'SPARE', 'RESERVED']):
                    continue

                # Fix G.4: MCU GPIO/ADC/DAC pin nets — expected single-ended
                # These are I/O pins exposed for external connection.
                if any(re.match(pat, net_upper) for pat in config.SUPERVISOR_GPIO_PATTERNS):
                    continue

                # =================================================================
                # CATEGORY 2: Interface signals (OK to be single-ended)
                # These connect to other modules or external world.
                # =================================================================

                # STRUCTURAL: Connector pins — check component TYPE or ref prefix.
                # Connectors are inherently external-facing; single-ended is expected.
                # Uses config.CONNECTOR_TYPES + config.CONNECTOR_REF_PREFIXES
                # (NOT hardcoded to 'J' prefix — handles X1, P1, CN1, CONN1, etc.)
                if (comp_type in config.CONNECTOR_TYPES
                        or any(ref.upper().startswith(p) for p in config.CONNECTOR_REF_PREFIXES)):
                    continue

                # Check against the centralized interface pattern list
                if any(p in net_upper for p in config.INTERFACE_NET_PATTERNS):
                    continue

                # External signal suffixes (exact suffix match to avoid false positives)
                if net_upper.endswith(config.SINGLE_ENDED_OK_SUFFIXES):
                    continue

                # Module-prefixed interface nets (config-driven patterns)
                # V-SERIES FIX: Replaced hardcoded r'^(MOD|CH|MODULE|CHANNEL)\d+_'
                # with config.GENERIC_MODULE_PREFIX_PATTERNS for extensibility.
                if any(re.match(pat, net_upper) for pat in config.GENERIC_MODULE_PREFIX_PATTERNS):
                    continue

                # Fix G.4: SYS_ prefixed nets are global system signals from the
                # Integration Agent — expected to be single-ended within a module.
                if net_upper.startswith(config.SYS_NET_PREFIX):
                    continue

                # Power input/output to other modules
                if any(p in net_upper for p in config.SINGLE_ENDED_POWER_PREFIXES):
                    continue

                # =================================================================
                # CATEGORY 2b: External connection exempt patterns (M.5 FIX)
                # Nets matching these represent external inputs that are
                # inherently single-ended within a module.
                # =================================================================
                exempt = False
                for pattern in config.SINGLE_ENDED_EXEMPT_PATTERNS:
                    if re.search(pattern, net_upper):
                        exempt = True
                        break
                if exempt:
                    continue

                # Integration agent module name prefixes (config-driven)
                if any(net_upper.startswith(p) for p in config.INTERFACE_MODULE_PREFIXES):
                    continue

                # =================================================================
                # CATEGORY 3: Internal signals that SHOULD have 2+ connections
                # These are PROBLEMS - flag them
                # =================================================================

                # If we get here, it's an internal signal that should connect to something
                # Y.3 FIX: Add auxiliary pin hint for IC-prefixed nets
                # Nets like U1_OFSA, U3_COMP suggest missing auxiliary passives
                issue = {
                    'type': 'single_ended_net',
                    'net': net,
                    'pin': pins[0],
                }
                if re.match(r'^U\d+_', net_upper):
                    issue['hint'] = (
                        'potential missing auxiliary passive '
                        '(filter/bias/offset component per IC datasheet)'
                    )
                issues.append(issue)

        return issues

    def _check_net_conflicts(self, circuit: Dict) -> List[Dict]:
        """Check for pins connected to multiple nets"""
        issues = []

        # Build pin-to-nets mapping from connections array
        pin_to_nets = {}
        for conn in circuit.get('connections', []):
            net = conn.get('net', 'UNKNOWN')
            points = conn.get('points', [])

            for point in points:
                if '.' in str(point):
                    if point not in pin_to_nets:
                        pin_to_nets[point] = set()
                    pin_to_nets[point].add(net)

        # Find pins in multiple nets
        for pin, nets in pin_to_nets.items():
            if len(nets) > 1:
                issues.append({
                    'type': 'net_conflict',
                    'pin': pin,
                    'nets': sorted(list(nets)),
                    'count': len(nets)
                })

        return issues

    def _check_pin_mismatches(self, circuit: Dict) -> List[Dict]:
        """Check if pin connections match pin definitions"""
        issues = []

        for comp in circuit.get('components', []):
            ref = comp.get('ref', '')
            # DEFENSIVE: Normalize pins to standard dict format
            pins = _normalize_pins(comp.get('pins', []))

            for pin in pins:
                pin_num = pin.get('number', '')
                pin_name = pin.get('name', '').upper()
                pin_type = pin.get('type', '').lower()
                pin_ref = f"{ref}.{pin_num}"

                actual_net = circuit.get('pinNetMapping', {}).get(pin_ref, None)
                if not actual_net:
                    continue

                # =============================================================
                # Y.6 FIX: Configuration pin tie-to-rail exemption.
                # Pins whose names contain config keywords (ADDR, MODE, SEL,
                # CFG, etc.) are legitimately hard-tied to VCC or GND for
                # address/mode selection. Suppress mismatch errors for these.
                # GENERIC: works for all I2C-addressable ICs, mode-selectable
                # devices, boot-pin strapping on MCUs, etc.
                # =============================================================
                is_config_pin = any(
                    kw in pin_name for kw in config.CONFIG_PIN_KEYWORDS
                )
                if is_config_pin:
                    net_upper = actual_net.upper()
                    if _is_power_rail(actual_net) or _is_ground_rail(actual_net):
                        continue  # Valid config tie — skip all mismatch checks

                # CRITICAL: Only check ACTUAL power pins (by type, not just name)
                # Many pins are named GND/VCC but are actually signal pins

                # Only flag mismatches for pins explicitly typed as power/ground
                # Use GENERIC power/ground rail detection
                if pin_type == 'power':
                    if pin_name == 'VCC' and not _is_power_rail(actual_net):
                        # STRUCTURAL: Check component isolation_domain metadata
                        # BEFORE pattern matching. Components in isolated domains
                        # (e.g., high-side drivers, isolated converters) may
                        # intentionally connect power pins to domain-specific rails.
                        comp_isolation = (comp.get('specs') or {}).get('isolation_domain', '')
                        if comp_isolation:
                            continue
                        issues.append({
                            'type': 'pin_net_mismatch',
                            'pin': pin_ref,
                            'pin_name': pin_name,
                            'actual_net': actual_net,
                            'expected_pattern': 'VCC'
                        })
                elif pin_type == 'ground':
                    if not _is_ground_rail(actual_net):
                        # STRUCTURAL: Check component isolation_domain metadata
                        # BEFORE net name pattern matching. Components in isolated
                        # domains intentionally use local ground references.
                        comp_isolation = (comp.get('specs') or {}).get('isolation_domain', '')
                        if comp_isolation:
                            continue

                        # V.6 FALLBACK: Check if the net name matches an isolated
                        # ground pattern (e.g., BRIDGE_MID, ISO_GND, HS_SOURCE).
                        # Catches cases where component metadata is absent but the
                        # net name itself indicates an isolated ground domain.
                        is_isolation_ground = any(
                            re.search(pattern, actual_net)
                            for pattern in config.ISOLATION_GROUND_PATTERNS
                        )
                        if not is_isolation_ground:
                            issues.append({
                                'type': 'pin_net_mismatch',
                                'pin': pin_ref,
                                'pin_name': pin_name,
                                'actual_net': actual_net,
                                'expected_pattern': 'GND'
                            })

        return issues

    def _check_structure_issues(self, circuit: Dict,
                                skip_nets: frozenset = frozenset()) -> List[Dict]:
        """
        Check for structural issues in the circuit.

        Fix H.5: SYS_ net awareness — pin refs on SYS_ / global power nets
        may reference components from OTHER modules via their unprefixed name.
        When a circuit is an integrated (multi-module) mega-circuit, we also
        build a set of known "original_ref" values so that cross-module refs
        created by the Integration Agent are not flagged as phantom.

        Fix H.8: Every issue dict now carries a 'severity' key sourced from
        ``config.ISSUE_SEVERITY``.  The supervisor loop can use this to
        early-exit on unrecoverable CRITICAL issues.
        """
        issues = []

        # Severity lookup helper
        _severity = config.ISSUE_SEVERITY

        # Check for required fields
        if not circuit.get('components'):
            issues.append({
                'type': 'missing_components',
                'severity': _severity.get('missing_components', 'CRITICAL'),
            })

        if not circuit.get('pinNetMapping'):
            issues.append({
                'type': 'missing_pinNetMapping',
                'severity': _severity.get('missing_pinNetMapping', 'CRITICAL'),
            })

        if not circuit.get('connections'):
            issues.append({
                'type': 'missing_connections',
                'severity': _severity.get('missing_connections', 'LOW'),
            })

        # CRITICAL: Build set of valid component references and their pins
        valid_components = set()
        valid_pins = {}
        # Fix H.5: Also collect original_ref values from prefixed components.
        # When the Integration Agent prefixes "R1" → "PWR_R1", both the
        # prefixed and original forms should be considered valid in the
        # context of the integrated circuit.
        original_refs = set()
        for comp in circuit.get('components', []):
            ref = comp.get('ref', '')
            if ref:
                valid_components.add(ref)
                pins = comp.get('pins', [])
                valid_pin_nums = set()
                for pin in pins:
                    if isinstance(pin, dict):
                        valid_pin_nums.add(str(pin.get('number', '')))
                    else:
                        valid_pin_nums.add(str(pin))
                valid_pins[ref] = valid_pin_nums
                # Collect original (unprefixed) refs if present
                orig = comp.get('original_ref', '')
                if orig:
                    original_refs.add(orig)

        # Merge original refs into the valid set for phantom detection
        # so cross-module SYS_ net entries are not falsely flagged.
        all_known_refs = valid_components | original_refs

        # CRITICAL: Check for phantom/invalid component references in connections
        for conn in circuit.get('connections', []):
            if 'points' not in conn:
                issues.append({
                    'type': 'wrong_connection_format',
                    'severity': _severity.get('wrong_connection_format', 'HIGH'),
                    'net': conn.get('net', 'unknown'),
                })
            elif len(conn.get('points', [])) < 2:
                # TC #94: Skip interface signals — they SHOULD have only 1
                # connection within this module because they connect to
                # OTHER modules.
                net_name = conn.get('net', '')
                # Q.6 FIX: Skip nets already flagged as single-ended to
                # avoid double-jeopardy (same net in two issue categories).
                if net_name in skip_nets:
                    continue
                if not self._is_interface_signal(net_name):
                    issues.append({
                        'type': 'insufficient_connection_points',
                        'severity': _severity.get('insufficient_connection_points', 'MEDIUM'),
                        'net': net_name,
                        'points': len(conn.get('points', [])),
                    })
            else:
                # Check each point references a valid component and pin
                for point in conn.get('points', []):
                    if '.' in str(point):
                        parts = point.split('.', 1)
                        comp_ref = parts[0]
                        pin_num = parts[1] if len(parts) > 1 else ''
                        if comp_ref not in valid_components:
                            # Fix H.5: Before flagging as phantom, check if
                            # the ref is a known original (unprefixed) ref
                            # from a prefixed module — this means the
                            # Integration Agent created a legitimate
                            # cross-module connection.
                            if comp_ref in original_refs:
                                logger.debug(
                                    f"[SUPERVISOR] Skipping phantom flag for "
                                    f"cross-module ref {comp_ref} on net "
                                    f"{conn.get('net', '?')}"
                                )
                                continue
                            issues.append({
                                'type': 'phantom_component',
                                'severity': _severity.get('phantom_component', 'CRITICAL'),
                                'component': comp_ref,
                                'net': conn.get('net', 'unknown'),
                                'point': point,
                                'message': f'Connection references non-existent component: {comp_ref}',
                            })
                        elif comp_ref in valid_pins and pin_num not in valid_pins[comp_ref]:
                            issues.append({
                                'type': 'invalid_pin',
                                'severity': _severity.get('invalid_pin', 'HIGH'),
                                'component': comp_ref,
                                'pin': pin_num,
                                'net': conn.get('net', 'unknown'),
                                'point': point,
                                'message': f'Invalid pin {pin_num} for component {comp_ref}',
                            })

        # CRITICAL: Check pinNetMapping for phantom components and invalid pins
        for pin_ref in circuit.get('pinNetMapping', {}).keys():
            if '.' in pin_ref:
                parts = pin_ref.split('.', 1)
                comp_ref = parts[0]
                pin_num = parts[1] if len(parts) > 1 else ''
                if comp_ref not in valid_components:
                    # Fix H.5: Same cross-module original_ref check
                    if comp_ref in original_refs:
                        continue
                    issues.append({
                        'type': 'phantom_component',
                        'severity': _severity.get('phantom_component', 'CRITICAL'),
                        'component': comp_ref,
                        'pin': pin_ref,
                        'message': f'pinNetMapping references non-existent component: {comp_ref}',
                    })
                elif comp_ref in valid_pins and pin_num not in valid_pins[comp_ref]:
                    issues.append({
                        'type': 'invalid_pin',
                        'severity': _severity.get('invalid_pin', 'HIGH'),
                        'component': comp_ref,
                        'pin': pin_num,
                        'pin_ref': pin_ref,
                        'message': f'pinNetMapping has invalid pin {pin_num} for {comp_ref}',
                    })

        return issues

    def _is_interface_signal(self, net_name: str) -> bool:
        """
        TC #94: Determine if a net name is an interface signal.

        Interface signals are expected to have only 1 connection within a module
        because they connect to OTHER modules. This is NOT an error.

        N.1 FIX: Uses config.INTERFACE_NET_PATTERNS as single source of truth,
        aligned with _check_single_ended_nets(). Eliminates the "Two Brains"
        problem where hardcoded patterns diverged from config.

        V-SERIES FIX: Replaced hardcoded module prefix regex with
        config.GENERIC_MODULE_PREFIX_PATTERNS for full extensibility.

        Args:
            net_name: The net name to check

        Returns:
            True if this is an interface signal
        """
        if not net_name:
            return False

        net_upper = net_name.upper()

        # NC (no connect) pins
        if 'NC' in net_upper or net_upper.startswith('NC_'):
            return True

        # MCU GPIO/ADC/DAC pins — expected single-ended within a module
        if any(re.match(pat, net_upper) for pat in config.SUPERVISOR_GPIO_PATTERNS):
            return True

        # Test points
        if net_upper.startswith('TP'):
            return True

        # Input/Output suffixes (config-driven)
        if net_upper.endswith(config.SINGLE_ENDED_OK_SUFFIXES):
            return True

        # Centralized interface patterns (single source of truth)
        if any(p in net_upper for p in config.INTERFACE_NET_PATTERNS):
            return True

        # Power input/output prefixes
        if any(p in net_upper for p in config.SINGLE_ENDED_POWER_PREFIXES):
            return True

        # SYS_ prefixed nets are global system signals from integration agent
        if net_upper.startswith(config.SYS_NET_PREFIX):
            return True

        # V-SERIES FIX: Module-prefixed interface nets (config-driven patterns)
        # Replaced hardcoded r'^(MOD|CH|MODULE|CHANNEL)\d+_' with extensible
        # config patterns that cover all module naming conventions.
        if any(re.match(pat, net_upper) for pat in config.GENERIC_MODULE_PREFIX_PATTERNS):
            return True

        # Integration agent module name prefixes (config-driven)
        for prefix in config.INTERFACE_MODULE_PREFIXES:
            if net_upper.startswith(prefix):
                return True

        # External connection exempt patterns (regex-based)
        for pattern in config.SINGLE_ENDED_EXEMPT_PATTERNS:
            if re.search(pattern, net_upper):
                return True

        return False

    def _check_shorted_passives(self, circuit: Dict) -> List[Dict]:
        """
        TC #91: Check for 2-terminal passive components with both pins on the same net.

        This is a CRITICAL issue for SPICE simulation:
        - A resistor with both pins on GND has zero voltage across it = zero current
        - A capacitor with both pins on the same net cannot charge/discharge
        - Such components are electrically useless

        This check is GENERIC and works for ANY circuit type.
        """
        issues = []

        # Get pinNetMapping
        pin_net_mapping = circuit.get('pinNetMapping', {})
        if not pin_net_mapping:
            return issues

        # 2-terminal passive component types (config-driven single source of truth)
        passive_types = config.TWO_PIN_PASSIVE_TYPES

        # Also match by reference prefix (config-driven)
        passive_prefixes = config.TWO_PIN_PASSIVE_PREFIXES

        for comp in circuit.get('components', []):
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()

            # Check if this is a 2-terminal passive component
            is_passive = False

            # Check by type
            if comp_type in passive_types:
                is_passive = True
            # Check by reference prefix (generic fallback)
            elif ref and ref[0].upper() in passive_prefixes:
                is_passive = True

            if not is_passive:
                continue

            # Get pins for this component
            pins = comp.get('pins', [])

            # Only check 2-terminal components
            if len(pins) != 2:
                continue

            # Get pin numbers
            pin_nums = []
            for pin in pins:
                if isinstance(pin, dict):
                    pin_nums.append(str(pin.get('number', '')))
                else:
                    pin_nums.append(str(pin))

            if len(pin_nums) != 2:
                continue

            # Get nets for each pin
            pin1_key = f"{ref}.{pin_nums[0]}"
            pin2_key = f"{ref}.{pin_nums[1]}"

            net1 = pin_net_mapping.get(pin1_key, '')
            net2 = pin_net_mapping.get(pin2_key, '')

            # Check if both pins are on the same net
            if net1 and net2 and net1 == net2:
                issues.append({
                    'type': 'shorted_passive',
                    'component': ref,
                    'component_type': comp_type,
                    'pin1': pin1_key,
                    'pin2': pin2_key,
                    'net': net1,
                    'message': f'{ref} ({comp_type}) has both pins on same net "{net1}" - no current can flow!'
                })

        if issues:
            logger.warning(f"TC #91: Found {len(issues)} shorted passive component(s)")

        return issues

    def _check_rating_violations(self, circuit: Dict) -> List[Dict]:
        """
        Check for components whose voltage/current ratings are below design requirements.

        Fix 1.4 (Forensic Fix Plan): Per-rail voltage domain awareness.
        Instead of applying blanket system voltage to all components, this now
        determines each component's local voltage domain from its connected nets
        and applies derating relative to that domain.

        A bypass cap on a 3.3V rail needs ~10V, not 720V.
        """
        issues = []

        # Extract design voltage requirement from circuit metadata
        design_spec = circuit.get('design_spec', circuit.get('designSpec', {}))
        if isinstance(design_spec, str):
            design_spec = {}

        system_voltage = (
            design_spec.get('system_voltage')
            or design_spec.get('max_voltage')
            or design_spec.get('input_voltage')
            or design_spec.get('voltage')
        )

        if not system_voltage:
            return issues

        try:
            system_voltage_num = float(re.sub(r'[^\d.]', '', str(system_voltage)))
        except (ValueError, TypeError):
            return issues

        if system_voltage_num <= 0:
            return issues

        # Build net → voltage map for per-rail domain detection
        pin_net_mapping = circuit.get('pinNetMapping', {})
        net_voltage_map = self._build_net_voltage_map(circuit, system_voltage_num)

        voltage_rated_types = {
            'mosfet', 'nmos', 'pmos', 'fet', 'transistor', 'bjt', 'npn', 'pnp',
            'diode', 'zener', 'led', 'schottky', 'tvs',
            'capacitor', 'electrolytic',
            'ic', 'driver', 'gate_driver',
        }

        for comp in circuit.get('components', []):
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()
            value = comp.get('value', '')

            if comp_type not in voltage_rated_types and not ref.startswith(('Q', 'D', 'C')):
                continue

            voltage_match = re.search(r'(\d+(?:\.\d+)?)\s*V\b', str(value), re.IGNORECASE)
            if not voltage_match:
                continue

            component_voltage = float(voltage_match.group(1))

            # Per-rail: determine local voltage domain from connected nets
            local_voltage = self._get_component_local_voltage(
                ref, pin_net_mapping, net_voltage_map
            )
            # Use local voltage if found, otherwise fall back to system voltage
            domain_voltage = local_voltage if local_voltage is not None else system_voltage_num
            derated_voltage = domain_voltage * config.QUALITY_GATES["voltage_derating_factor"]

            if component_voltage < derated_voltage:
                domain_label = (
                    f"{domain_voltage}V rail"
                    if local_voltage is not None
                    else f"{system_voltage_num}V system"
                )
                issues.append({
                    'type': 'rating_violation',
                    'component': ref,
                    'component_type': comp_type,
                    'rated_voltage': component_voltage,
                    'required_voltage': derated_voltage,
                    'system_voltage': system_voltage_num,
                    'domain_voltage': domain_voltage,
                    'message': (
                        f'{ref} ({comp_type}) rated {component_voltage}V but '
                        f'{domain_label} requires {derated_voltage}V '
                        f'(={domain_voltage}V x 1.2 derating)'
                    ),
                })

        if issues:
            logger.warning(f"Found {len(issues)} rating violation(s)")

        return issues

    @staticmethod
    def _build_net_voltage_map(circuit: Dict, system_voltage: float) -> Dict[str, float]:
        """
        Build mapping from net names to approximate voltage levels.

        Uses pattern matching on net names (e.g., '+5V', 'HV_RAIL_400V').
        Falls back to system_voltage for generic HV nets.
        """
        net_voltages: Dict[str, float] = {}
        all_nets: set = set()
        for net in circuit.get('nets', []):
            if isinstance(net, str):
                all_nets.add(net)
            elif isinstance(net, dict):
                all_nets.add(net.get('name', ''))
        for net in circuit.get('pinNetMapping', {}).values():
            if isinstance(net, str):
                all_nets.add(net)

        for net in all_nets:
            if not net:
                continue
            upper = net.upper().replace(' ', '_')

            # Ground nets
            if any(g in upper for g in ('GND', 'GROUND', 'VSS', 'PGND', 'AGND', 'DGND')):
                net_voltages[net] = 0.0
                continue

            # Try explicit voltage in net name
            # Handle P instead of dot (e.g., V3P3)
            v_match_p = re.search(r'V(\d+)P(\d+)', upper)
            if v_match_p:
                net_voltages[net] = float(f"{v_match_p.group(1)}.{v_match_p.group(2)}")
                continue

            v_match = re.search(r'(\d+(?:\.\d+)?)\s*V', upper)
            if v_match:
                net_voltages[net] = float(v_match.group(1))
                continue

            # Handle +12V style
            v_match_plus = re.search(r'\+(\d+(?:\.\d+)?)\s*V?', upper)
            if v_match_plus:
                net_voltages[net] = float(v_match_plus.group(1))
                continue

            # HV indicators → system voltage
            if any(hv in upper for hv in ('HV_RAIL', 'HV_BUS', 'DC_BUS', 'DC_LINK', 'MAINS')):
                net_voltages[net] = system_voltage
                continue

            # Generic low-voltage rails
            if 'VCC' in upper or 'AVCC' in upper:
                net_voltages[net] = 5.0
                continue
            if 'VDD' in upper or 'DVCC' in upper:
                net_voltages[net] = 3.3
                continue

        return net_voltages

    @staticmethod
    def _get_component_local_voltage(
        ref: str,
        pin_net_mapping: Dict[str, str],
        net_voltage_map: Dict[str, float],
    ) -> Optional[float]:
        """
        Determine the maximum voltage domain a component operates in.

        Returns the highest voltage found on any of the component's connected
        nets, or None if no voltage domain can be determined.
        """
        max_v = 0.0
        found = False
        for pin_key, net_name in pin_net_mapping.items():
            if not pin_key.startswith(f"{ref}."):
                continue
            v = net_voltage_map.get(net_name)
            if v is not None and v > 0:
                max_v = max(max_v, v)
                found = True
        return max_v if found else None

    # =====================================================================
    # Fix K.10: Feedback Divider Accuracy Check
    # =====================================================================
    def _check_feedback_dividers(self, circuit: Dict) -> List[Dict]:
        """
        Validate feedback divider accuracy for voltage regulators.

        For any regulator IC with a feedback/sense pin (FB, VSENSE, ADJ, etc.),
        identify the resistive voltage divider and calculate the resulting
        output voltage. Flag if it deviates from the module's voltage spec
        by more than config.FEEDBACK_DIVIDER_TOLERANCE.

        Generic: Works with any regulator topology using resistive feedback.
        """
        issues = []
        pin_net_mapping = circuit.get('pinNetMapping', {})
        components = circuit.get('components', [])
        if not pin_net_mapping or not components:
            return issues

        fb_pin_names = config.FEEDBACK_PIN_NAMES

        # Build lookup: ref → component, net → list of pin_refs
        comp_map = {c.get('ref', ''): c for c in components}
        net_to_pins = {}
        for pin_ref, net in pin_net_mapping.items():
            net_to_pins.setdefault(net, []).append(pin_ref)

        for comp in components:
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()
            comp_value = comp.get('value', '').upper()
            pins = comp.get('pins', [])

            # Only check ICs that are likely regulators
            if not _is_power_supply_ic(comp_type, comp_value, comp.get('name', '').upper()):
                continue

            # Find the feedback pin
            fb_pin_ref = None
            fb_net = None
            for pin in pins:
                pin_name = pin.get('name', '').upper()
                if pin_name in fb_pin_names:
                    pin_num = pin.get('number', '')
                    fb_pin_ref = f"{ref}.{pin_num}"
                    fb_net = pin_net_mapping.get(fb_pin_ref, '')
                    break

            if not fb_net:
                continue

            # Find the output voltage pin/net for this regulator
            output_net = None
            for pin in pins:
                pin_name = pin.get('name', '').upper()
                if pin_name in ('VOUT', 'OUT', 'OUTPUT', 'SW'):
                    pin_num = pin.get('number', '')
                    output_net = pin_net_mapping.get(f"{ref}.{pin_num}", '')
                    break

            if not output_net:
                continue

            # Find resistors connected to the feedback net
            # A typical feedback divider: VOUT — R_top — FB — R_bottom — GND
            fb_net_pins = net_to_pins.get(fb_net, [])
            r_top = None
            r_bottom = None

            for pref in fb_net_pins:
                if pref == fb_pin_ref:
                    continue
                # pref = "Rxx.y" — find the component
                parts = pref.split('.')
                if len(parts) != 2:
                    continue
                r_ref = parts[0]
                r_comp = comp_map.get(r_ref)
                if not r_comp:
                    continue
                r_type = r_comp.get('type', '').lower()
                if r_type != 'resistor':
                    continue

                # Determine which pin is on the FB net and which is on the other net
                other_pin = '1' if parts[1] == '2' else '2'
                other_net = pin_net_mapping.get(f"{r_ref}.{other_pin}", '')

                if _is_power_rail(other_net) or other_net == output_net:
                    r_top = r_comp
                elif _is_ground_rail(other_net) or other_net.upper() in config.SUPERVISOR_GROUND_NETS:
                    r_bottom = r_comp

            if not r_top or not r_bottom:
                continue

            # Parse resistance values
            r_top_val = self._parse_resistance(r_top.get('value', '0'))
            r_bottom_val = self._parse_resistance(r_bottom.get('value', '0'))

            if r_top_val <= 0 or r_bottom_val <= 0:
                continue

            # Determine reference voltage (Vref) from IC datasheet norms
            # Most modern regulators: 0.8V; LM317 family: 1.25V; LM431: 2.5V
            vref = 0.8  # Default for modern buck/boost
            if any(kw in comp_value for kw in ('LM317', 'LM337', 'LM350')):
                vref = 1.25
            elif any(kw in comp_value for kw in ('TL431', 'TLV431', 'LM4040')):
                vref = 2.5
            elif any(kw in comp_value for kw in ('LM78', 'LM79', 'AMS1117')):
                continue  # Fixed-output regulators — no divider to check

            # Calculate output voltage: Vout = Vref * (1 + R_top / R_bottom)
            calculated_vout = vref * (1.0 + r_top_val / r_bottom_val)

            # Extract target voltage from module spec or output net name
            target_vout = self._extract_voltage_from_net(output_net)
            if target_vout is None or target_vout <= 0:
                continue

            # Check tolerance
            deviation = abs(calculated_vout - target_vout) / target_vout
            tolerance = config.FEEDBACK_DIVIDER_TOLERANCE

            if deviation > tolerance:
                issues.append({
                    'type': 'feedback_divider_error',
                    'component': ref,
                    'severity': 'HIGH',
                    'message': (
                        f'{ref} feedback divider gives {calculated_vout:.2f}V '
                        f'(target {target_vout:.1f}V, error {deviation:.1%}). '
                        f'R_top={r_top.get("ref")}={r_top.get("value")}, '
                        f'R_bottom={r_bottom.get("ref")}={r_bottom.get("value")}. '
                        f'Correct R_bottom to ~{vref * r_top_val / (target_vout - vref):.0f} ohms.'
                    ),
                })

        return issues

    @staticmethod
    def _parse_resistance(value_str: str) -> float:
        """Parse resistance string to ohms. Handles k, M, R notation."""
        if not value_str:
            return 0.0
        s = value_str.strip().upper().replace(',', '')
        # Remove Ohm symbol variants
        s = s.replace('OHM', '').replace('Ω', '').strip()
        try:
            # Handle R notation: 4R7 = 4.7, 0R1 = 0.1
            if 'R' in s and not s.startswith('R'):
                s = s.replace('R', '.')
                return float(s)
            # Handle k/M suffix
            multiplier = 1.0
            if s.endswith('K'):
                multiplier = 1e3
                s = s[:-1]
            elif s.endswith('M'):
                multiplier = 1e6
                s = s[:-1]
            return float(s) * multiplier
        except ValueError:
            return 0.0

    def _extract_voltage_from_net(self, net_name: str) -> float:
        """Extract voltage from a net name like '+5V', 'VOUT_5V', '3V3'."""
        if not net_name:
            return None
        upper = net_name.upper().replace('+', '').replace('-', '')
        # Try xVy format: 3V3 → 3.3, 1V8 → 1.8
        m = re.search(r'(\d+)V(\d+)', upper)
        if m:
            return float(f"{m.group(1)}.{m.group(2)}")
        # Try plain: 5V → 5.0, 12V → 12.0
        m = re.search(r'(\d+(?:\.\d+)?)\s*V', upper)
        if m:
            return float(m.group(1))
        # Try bare number after common prefixes
        m = re.search(r'(?:VOUT|OUT)_?(\d+(?:\.\d+)?)', upper)
        if m:
            return float(m.group(1))
        return None

    # =====================================================================
    # Fix K.14: Pin-Function Mismatch Check
    # =====================================================================
    def _check_pin_function_mismatch(self, circuit: Dict) -> List[Dict]:
        """
        Validate that MOSFET/transistor pins are wired to electrically correct nets.

        Checks:
        - GATE pins should NOT be on power rails (unless intentionally tied)
        - DRAIN pins should not be on ground (for N-channel) unless it's a
          low-side switch with source on ground (which is correct)
        - SOURCE pins of N-channel MOSFETs should typically be on ground or
          sense resistor

        Generic: Uses pin names from component JSON, not hardcoded pin numbers.
        """
        issues = []
        pin_net_mapping = circuit.get('pinNetMapping', {})
        components = circuit.get('components', [])

        for comp in components:
            ref = comp.get('ref', '')
            comp_type = comp.get('type', '').lower()
            pins = comp.get('pins', [])

            if comp_type not in ('mosfet', 'bjt', 'igbt', 'jfet'):
                continue

            gate_net = None
            drain_net = None
            source_net = None

            for pin in pins:
                pin_name = pin.get('name', '').upper()
                pin_num = pin.get('number', '')
                pin_ref = f"{ref}.{pin_num}"
                net = pin_net_mapping.get(pin_ref, '')

                if pin_name in ('GATE', 'G', 'BASE', 'B'):
                    gate_net = net
                elif pin_name in ('DRAIN', 'D', 'COLLECTOR', 'C'):
                    drain_net = net
                elif pin_name in ('SOURCE', 'S', 'EMITTER', 'E'):
                    source_net = net

            # Check: GATE/BASE connected to a power rail is almost always wrong
            # (except for intentional pull-up/pull-down)
            if gate_net and (_is_power_rail(gate_net) or _is_ground_rail(gate_net)):
                # Only flag if gate is directly on a POWER rail (not ground)
                # Gate tied to ground is a valid "always off" configuration
                if _is_power_rail(gate_net):
                    issues.append({
                        'type': 'pin_function_mismatch',
                        'component': ref,
                        'severity': 'HIGH',
                        'message': (
                            f'{ref} GATE/BASE pin is directly on power rail '
                            f'"{gate_net}" — this permanently turns ON the device. '
                            f'Check for drain/gate pin swap.'
                        ),
                    })

            # Check: DRAIN and SOURCE on the same net = shorted device
            if drain_net and source_net and drain_net == source_net:
                issues.append({
                    'type': 'pin_function_mismatch',
                    'component': ref,
                    'severity': 'CRITICAL',
                    'message': (
                        f'{ref} DRAIN/COLLECTOR and SOURCE/EMITTER are on the '
                        f'same net "{drain_net}" — device is short-circuited.'
                    ),
                })

        return issues

    def dispatch_fixes(self, circuit: Dict, erc_report: Dict) -> Dict:
        """
        Dispatch issues to specialized fixers in priority order
        """
        issues = erc_report['issues']

        # Fix in priority order
        # TC #95: Added 'shorted_passives' - CRITICAL for LAW 4 compliance
        fix_order = [
            'structure_issues',      # Fix structure first
            'shorted_passives',      # TC #95: LAW 4 - Fix shorted passives early (CRITICAL)
            'power_connections',      # Then power
            'pin_mismatches',        # Then pin mismatches
            'floating_components',    # Then floating
            'net_conflicts',         # Then conflicts
            'single_ended_nets',     # Then single-ended
            'rating_violations',     # Finally rating issues
        ]

        for issue_type in fix_order:
            if issues.get(issue_type):
                logger.info(f"Fixing {issue_type}: {len(issues[issue_type])} issues")
                circuit = self.fixers[issue_type].fix(circuit, issues[issue_type])
                self.fixes_applied.extend(self.fixers[issue_type].get_fixes_applied())

        return circuit

    def rebuild_circuit_structure(self, circuit: Dict) -> Dict:
        """
        Rebuild connections and nets from pinNetMapping

        TC #90: Enhanced to handle None and empty values in pinNetMapping
        """
        # Rebuild connections with points array format
        net_to_points = {}
        for pin, net in circuit.get('pinNetMapping', {}).items():
            # TC #90: Skip None and empty net values
            if not net:
                continue
            if net not in net_to_points:
                net_to_points[net] = []
            net_to_points[net].append(pin)

        connections = []
        for net, points in net_to_points.items():
            if len(points) >= 2:
                connections.append({
                    'net': net,
                    'points': sorted(points)
                })

        circuit['connections'] = connections
        # TC #90: Filter out None/empty values before sorting
        valid_nets = [n for n in net_to_points.keys() if n]
        circuit['nets'] = sorted(valid_nets)

        return circuit


class PowerConnectionFixer:
    """Specialized fixer for power connection issues"""

    def __init__(self):
        self.fixes_applied = []

    def fix(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """Fix power connection issues - ENFORCES 100% COMPLETION"""

        for issue in issues:
            # NEW: Handle IC missing power/ground issues
            if issue['type'] == 'ic_missing_power':
                comp_ref = issue['component']
                logger.info(f"CRITICAL FIX: IC {comp_ref} has NO POWER - adding VCC connection")

                # Find component
                comp = next((c for c in circuit['components'] if c.get('ref') == comp_ref), None)
                if comp:
                    # Find first unconnected pin and connect to VCC
                    for pin in comp.get('pins', []):
                        pin_num = pin.get('number', '')
                        pin_ref = f"{comp_ref}.{pin_num}"
                        if pin_ref not in circuit['pinNetMapping'] or not circuit['pinNetMapping'][pin_ref]:
                            circuit['pinNetMapping'][pin_ref] = 'VCC'
                            self.fixes_applied.append(f"CRITICAL: Added VCC to {pin_ref} for IC {comp_ref}")
                            logger.info(f"  Connected {pin_ref} to VCC")
                            break

            elif issue['type'] == 'ic_missing_ground':
                comp_ref = issue['component']
                logger.info(f"CRITICAL FIX: IC {comp_ref} has NO GROUND - adding GND connection")

                # Find component
                comp = next((c for c in circuit['components'] if c.get('ref') == comp_ref), None)
                if comp:
                    # Find first unconnected pin and connect to GND
                    for pin in comp.get('pins', []):
                        pin_num = pin.get('number', '')
                        pin_ref = f"{comp_ref}.{pin_num}"
                        if pin_ref not in circuit['pinNetMapping'] or not circuit['pinNetMapping'][pin_ref]:
                            circuit['pinNetMapping'][pin_ref] = 'GND'
                            self.fixes_applied.append(f"CRITICAL: Added GND to {pin_ref} for IC {comp_ref}")
                            logger.info(f"  Connected {pin_ref} to GND")
                            break

            elif issue['type'] == 'unconnected_power_pin':
                # Connect the power pin to the expected net
                pin_ref = issue['pin']
                expected_net = issue['expected_net']

                # CRITICAL: Check if this pin is already connected to a signal
                # If it is, the pin definition is probably WRONG
                current_net = circuit['pinNetMapping'].get(pin_ref, None)
                if current_net and any(x in current_net.upper() for x in ['GATE', 'SIGNAL', 'OUTPUT', 'PWM']):
                    # This pin is connected to a signal - it's NOT really a power pin
                    # Fix the pin definition instead
                    comp_ref = pin_ref.split('.')[0]
                    pin_num = pin_ref.split('.')[1]
                    for comp in circuit['components']:
                        if comp.get('ref') == comp_ref:
                            for pin in comp.get('pins', []):
                                if str(pin.get('number')) == pin_num:
                                    pin['type'] = 'output'  # Fix the type
                                    pin['name'] = current_net.split('_')[-1]  # Fix the name
                                    self.fixes_applied.append(
                                        f"Fixed pin definition {pin_ref}: type=power->output (connected to {current_net})"
                                    )
                                    break
                else:
                    # Normal case - connect to power
                    circuit['pinNetMapping'][pin_ref] = expected_net
                    self.fixes_applied.append(
                        f"Connected {pin_ref} ({issue['pin_name']}) to {expected_net}"
                    )

                    # CRITICAL: Ensure power nets have multiple connections
                    # If this is the only connection to VCC/GND, add bypass capacitors
                    comp_ref = pin_ref.split('.')[0]
                    net_connections = [p for p, n in circuit['pinNetMapping'].items() if n == expected_net]
                    if len(net_connections) == 1:  # Only this pin connected
                        # Add a bypass capacitor to ensure net is not single-ended
                        if expected_net == 'VCC':
                            bypass_ref = f"C_BYPASS_{comp_ref}"

                            # Check if component already exists
                            existing_refs = {c.get('ref') for c in circuit['components']}
                            if bypass_ref not in existing_refs:
                                # First, create the component definition
                                bypass_component = {
                                    'ref': bypass_ref,
                                    'type': 'capacitor',
                                    'value': '100nF',
                                    'package': '0603',
                                    'pins': [
                                        {'number': '1', 'name': '1', 'type': 'passive'},
                                        {'number': '2', 'name': '2', 'type': 'passive'}
                                    ],
                                    'notes': 'Auto-added bypass capacitor'
                                }
                                circuit['components'].append(bypass_component)
                                logger.info(f"Added bypass capacitor component: {bypass_ref}")

                            # Then add pin net mappings
                            circuit['pinNetMapping'][f"{bypass_ref}.1"] = 'VCC'
                            circuit['pinNetMapping'][f"{bypass_ref}.2"] = 'GND'
                            self.fixes_applied.append(f"Added bypass cap {bypass_ref} for VCC net")
                        elif expected_net == 'GND':
                            # Ensure GND has multiple connections
                            # Find a component that should connect to GND
                            for comp in circuit['components']:
                                if comp['ref'].startswith('C'):
                                    # Connect capacitor to ground if not already
                                    cap_ref = comp['ref']
                                    if f"{cap_ref}.2" not in circuit['pinNetMapping']:
                                        circuit['pinNetMapping'][f"{cap_ref}.2"] = 'GND'
                                        self.fixes_applied.append(f"Connected {cap_ref}.2 to GND")
                                        break

            elif issue['type'] == 'wrong_power_connection':
                # Fix the wrong connection
                pin_ref = issue['pin']
                expected_net = issue['expected_net']
                actual_net = issue['actual_net']

                # CRITICAL: If connected to a signal-like net, fix the pin definition
                if any(x in actual_net.upper() for x in ['GATE', 'SIGNAL', 'OUTPUT', 'PWM', 'ENABLE']):
                    # This is actually a signal pin, not power - fix the definition
                    comp_ref = pin_ref.split('.')[0]
                    pin_num = pin_ref.split('.')[1]
                    for comp in circuit['components']:
                        if comp.get('ref') == comp_ref:
                            for pin in comp.get('pins', []):
                                if str(pin.get('number')) == pin_num:
                                    pin['type'] = 'passive'  # Fix the type
                                    self.fixes_applied.append(
                                        f"Fixed pin definition {pin_ref}: type=power->passive (signal net {actual_net})"
                                    )
                                    break
                else:
                    # Normal power net issue - fix the connection
                    circuit['pinNetMapping'][pin_ref] = expected_net
                    self.fixes_applied.append(
                        f"Fixed {pin_ref}: {actual_net} -> {expected_net}"
                    )

        # AGGRESSIVE: Check ALL ICs and ensure they have power connections
        for comp in circuit['components']:
            if comp['ref'].startswith('U'):
                # DEFENSIVE: Normalize pins to standard dict format
                pins = _normalize_pins(comp.get('pins', []))
                has_vcc = False
                has_gnd = False

                for pin in pins:
                    pin_num = pin.get('number', '')
                    pin_ref = f"{comp['ref']}.{pin_num}"
                    net = circuit['pinNetMapping'].get(pin_ref, '') or ''  # TC #90: Handle None values
                    if 'VCC' in net or 'VDD' in net:
                        has_vcc = True
                    if 'GND' in net or 'VSS' in net:
                        has_gnd = True

                # If missing power, add it aggressively
                if not has_vcc and pins:
                    # Find first available pin and connect to VCC
                    for pin in pins:
                        pin_num = pin.get('number', '')
                        pin_ref = f"{comp['ref']}.{pin_num}"
                        if pin_ref not in circuit['pinNetMapping']:
                            circuit['pinNetMapping'][pin_ref] = 'VCC'
                            self.fixes_applied.append(f"AGGRESSIVE: Added VCC to {pin_ref}")
                            break

                if not has_gnd and pins:
                    # Find first available pin and connect to GND
                    for pin in pins:
                        pin_num = pin.get('number', '')
                        pin_ref = f"{comp['ref']}.{pin_num}"
                        if pin_ref not in circuit['pinNetMapping'] or circuit['pinNetMapping'][pin_ref] == '':
                            circuit['pinNetMapping'][pin_ref] = 'GND'
                            self.fixes_applied.append(f"AGGRESSIVE: Added GND to {pin_ref}")
                            break

        return circuit

    def get_fixes_applied(self) -> List[str]:
        return self.fixes_applied


class FloatingComponentFixer:
    """Specialized fixer for floating components"""

    def __init__(self):
        self.fixes_applied = []

    def fix(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """Fix floating components by adding appropriate connections"""

        for issue in issues:
            ref = issue['component']
            comp_type = issue['component_type']
            unconnected_pins = issue.get('unconnected_pins', [])

            # Find the component
            comp = next((c for c in circuit['components']
                        if c.get('ref') == ref), None)

            if not comp:
                continue

            # For partially connected components, only connect unconnected pins
            if unconnected_pins:
                # Handle specific unconnected pins
                for pin_data in unconnected_pins:
                    # Extract pin number from pin data (could be dict or string)
                    if isinstance(pin_data, dict):
                        pin_num = pin_data.get('number', pin_data.get('name', ''))
                    else:
                        pin_num = str(pin_data)

                    pin_ref = f"{ref}.{pin_num}"
                    # Skip if already connected
                    if pin_ref in circuit.get('pinNetMapping', {}):
                        continue

                    # For ICs, check if it's a NC pin or needs connection
                    if comp_type == 'ic':
                        # Common NC pins or pins that can be left floating
                        if pin_num in ['NC', 'DNC', 'RESERVED']:
                            continue
                        # Check if it's likely a power or ground pin
                        if any(x in str(pin_num).upper() for x in ['VCC', 'VDD', 'VSS', 'GND', 'AGND', 'DGND']):
                            # Connect to appropriate power net
                            if 'GND' in str(pin_num).upper() or 'VSS' in str(pin_num).upper():
                                circuit['pinNetMapping'][pin_ref] = "GND"
                                self.fixes_applied.append(f"Connected {ref}.{pin_num} to GND")
                            else:
                                circuit['pinNetMapping'][pin_ref] = "VCC"
                                self.fixes_applied.append(f"Connected {ref}.{pin_num} to VCC")
                        else:
                            # For other IC pins, mark as NC (no connection)
                            # Don't create single-ended nets
                            circuit['pinNetMapping'][pin_ref] = f"NC_{ref}_{pin_num}"
                            self.fixes_applied.append(f"Marked {ref}.{pin_num} as NC")
                    else:
                        # For passive components, connect to other pin or ground
                        other_pins = [p for p in comp.get('pins', []) if p != pin_data]
                        if other_pins:
                            # Connect to the same net as another pin or to ground
                            other_pin = other_pins[0]
                            if isinstance(other_pin, dict):
                                other_pin_num = other_pin.get('number', other_pin.get('name', ''))
                            else:
                                other_pin_num = str(other_pin)
                            other_pin_ref = f"{ref}.{other_pin_num}"
                            other_net = circuit.get('pinNetMapping', {}).get(other_pin_ref)
                            if other_net:
                                circuit['pinNetMapping'][pin_ref] = other_net
                                self.fixes_applied.append(f"Connected {ref}.{pin_num} to {other_net}")
                            else:
                                circuit['pinNetMapping'][pin_ref] = "GND"
                                self.fixes_applied.append(f"Connected {ref}.{pin_num} to GND")
                        else:
                            circuit['pinNetMapping'][pin_ref] = "GND"
                            self.fixes_applied.append(f"Connected {ref}.{pin_num} to GND")
                continue

            # Add connections based on component type for fully floating components
            if ref.startswith('R'):
                # Resistor
                value = comp.get('value', '').lower()
                if 'pull' in comp_type or 'pull' in value:
                    if 'down' in comp_type or 'down' in value:
                        circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_SIGNAL"
                        circuit['pinNetMapping'][f"{ref}.2"] = "GND"
                        self.fixes_applied.append(f"Connected pull-down {ref}")
                    else:
                        circuit['pinNetMapping'][f"{ref}.1"] = "VCC"
                        circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_SIGNAL"
                        self.fixes_applied.append(f"Connected pull-up {ref}")
                else:
                    circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_1"
                    circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_2"
                    self.fixes_applied.append(f"Added nets for {ref}")

            elif ref.startswith('C'):
                # Capacitor
                value = comp.get('value', '').lower()
                if any(x in value for x in ['100n', '0.1u', '1u', 'bypass', 'decoupling']):
                    circuit['pinNetMapping'][f"{ref}.1"] = "VCC"
                    circuit['pinNetMapping'][f"{ref}.2"] = "GND"
                    self.fixes_applied.append(f"Connected bypass cap {ref}")
                else:
                    circuit['pinNetMapping'][f"{ref}.1"] = f"NET_{ref}_P"
                    circuit['pinNetMapping'][f"{ref}.2"] = f"NET_{ref}_N"
                    self.fixes_applied.append(f"Added nets for cap {ref}")

            elif ref.startswith('Y'):
                # CRYSTAL - AI should have already provided load capacitors
                # CRITICAL: Do NOT create phantom components!
                # If crystal is truly floating, just connect to XTAL nets
                # The AI is responsible for creating proper load capacitors
                xtal_net1 = f"XTAL1"
                xtal_net2 = f"XTAL2"

                # Only connect crystal itself if it's floating
                if f"{ref}.1" not in circuit.get('pinNetMapping', {}):
                    circuit['pinNetMapping'][f"{ref}.1"] = xtal_net1
                if f"{ref}.2" not in circuit.get('pinNetMapping', {}):
                    circuit['pinNetMapping'][f"{ref}.2"] = xtal_net2

                self.fixes_applied.append(f"Connected crystal {ref} (AI should provide load caps)")

            elif ref.startswith('U'):
                # IC - connect power pins
                # DEFENSIVE: Normalize pins to standard dict format
                pins = _normalize_pins(comp.get('pins', []))
                if pins:
                    # Look for actual power pins
                    for pin in pins:
                        pin_num = pin.get('number', '')
                        pin_name = pin.get('name', '').upper()
                        pin_type = pin.get('type', '').lower()
                        pin_ref = f"{ref}.{pin_num}"

                        if pin_type == 'power' or pin_name in ['VCC', 'VDD', 'V+']:
                            circuit['pinNetMapping'][pin_ref] = "VCC"
                            self.fixes_applied.append(f"Connected {ref} power pin {pin_num}")
                        elif pin_type == 'ground' or pin_name in ['GND', 'VSS', 'V-']:
                            circuit['pinNetMapping'][pin_ref] = "GND"
                            self.fixes_applied.append(f"Connected {ref} ground pin {pin_num}")

        return circuit

    def get_fixes_applied(self) -> List[str]:
        return self.fixes_applied


class SingleEndedNetFixer:
    """Specialized fixer for single-ended nets"""

    def __init__(self):
        self.fixes_applied = []

    def fix(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """Fix single-ended nets"""

        for issue in issues:
            net = issue['net']
            pin = issue['pin']
            ref = pin.split('.')[0]

            # CRITICAL: Never remove power nets!
            # TC #79: Create sanitized net suffix for unique component references
            safe_net_suffix = ''.join(c if c.isalnum() else '_' for c in net)[:12]

            if net in ['VCC', 'GND', 'VSS', 'VDD'] or 'VCC' in net or 'GND' in net:
                # Power net is single-ended - add bypass capacitor
                if net == 'VCC' or 'VCC' in net:
                    # Add bypass cap (TC #79: unique ref per net)
                    bypass_ref = f"C_BYPASS_{ref}_{safe_net_suffix}"

                    # Check if component already exists
                    existing_refs = {c.get('ref') for c in circuit['components']}
                    if bypass_ref not in existing_refs:
                        # First, create the component definition
                        bypass_component = {
                            'ref': bypass_ref,
                            'type': 'capacitor',
                            'value': '100nF',
                            'package': '0603',
                            'pins': [
                                {'number': '1', 'name': '1', 'type': 'passive'},
                                {'number': '2', 'name': '2', 'type': 'passive'}
                            ],
                            'notes': 'Auto-added bypass capacitor'
                        }
                        circuit['components'].append(bypass_component)
                        logger.info(f"Added bypass capacitor component: {bypass_ref}")

                    # Then add pin net mappings
                    circuit['pinNetMapping'][f"{bypass_ref}.1"] = net
                    circuit['pinNetMapping'][f"{bypass_ref}.2"] = "GND"
                    self.fixes_applied.append(f"Added bypass cap for single-ended {net}")
                elif net == 'GND' or 'GND' in net:
                    # Connect to chassis or add ground plane connection
                    tp_ref = "TP_GND"

                    # Check if component already exists
                    existing_refs = {c.get('ref') for c in circuit['components']}
                    if tp_ref not in existing_refs:
                        # First, create the component definition
                        tp_component = {
                            'ref': tp_ref,
                            'type': 'testpoint',
                            'value': 'TP',
                            'package': 'KEYSTONE-5000',
                            'pins': [
                                {'number': '1', 'name': '1', 'type': 'passive'}
                            ],
                            'notes': 'Auto-added ground test point'
                        }
                        circuit['components'].append(tp_component)
                        logger.info(f"Added test point component: {tp_ref}")

                    # Then add pin net mapping
                    circuit['pinNetMapping'][f"{tp_ref}.1"] = net
                    self.fixes_applied.append(f"Added test point for single-ended {net}")
                continue

            # Find the component
            comp = next((c for c in circuit['components']
                        if c.get('ref') == ref), None)

            if not comp:
                # Just remove the orphan net (TC #78: check if pin exists before deleting)
                if pin in circuit.get('pinNetMapping', {}):
                    del circuit['pinNetMapping'][pin]
                    self.fixes_applied.append(f"Removed orphan net {net}")
                else:
                    self.fixes_applied.append(f"Skipped already-removed orphan pin {pin}")
                continue

            # SPECIAL HANDLING FOR CONNECTORS
            if ref.startswith('J'):
                # Connectors - all single-ended connector pins go to GND
                # This is safe for most connector pins (shield, unused pins, etc.)
                circuit['pinNetMapping'][pin] = "GND"
                self.fixes_applied.append(f"Connected connector pin {pin} to GND")
                continue

            # SPECIAL HANDLING FOR RESISTORS with single-ended nets
            if ref.startswith('R'):
                # Resistor with single-ended pin - connect it to the other pin's net or GND
                pin_num = pin.split('.')[-1]
                other_pin = f"{ref}.{'2' if pin_num == '1' else '1'}"
                other_net = circuit['pinNetMapping'].get(other_pin)

                if other_net and other_net != net:
                    # Other pin has a net - connect this pin to it
                    circuit['pinNetMapping'][pin] = other_net
                    # Remove old single-ended net
                    # Will be cleaned up in rebuild
                    self.fixes_applied.append(f"Connected {pin} to {other_net} (joining resistor)")
                elif not other_net:
                    # Other pin not connected - connect both to GND
                    circuit['pinNetMapping'][pin] = "GND"
                    circuit['pinNetMapping'][other_pin] = "GND"
                    self.fixes_applied.append(f"Connected {ref} both pins to GND")
                else:
                    # Both pins on same single-ended net - connect to GND
                    circuit['pinNetMapping'][pin] = "GND"
                    circuit['pinNetMapping'][other_pin] = "GND"
                    self.fixes_applied.append(f"Connected {ref} to GND")
                continue

            # Handle based on net type
            net_upper = net.upper()

            if 'SENSE' in net_upper and 'CURRENT' in net_upper:
                # Current sense - add sense resistor (TC #79: unique ref per net)
                sense_ref = f"R_{ref}_{safe_net_suffix}_SENSE"

                # Check if component already exists
                existing_refs = {c.get('ref') for c in circuit['components']}
                if sense_ref not in existing_refs:
                    # First, create the component definition
                    sense_component = {
                        'ref': sense_ref,
                        'type': 'resistor',
                        'value': '0.1',  # 100mOhm
                        'package': '2512',
                        'pins': [
                            {'number': '1', 'name': '1', 'type': 'passive'},
                            {'number': '2', 'name': '2', 'type': 'passive'}
                        ],
                        'notes': 'Auto-added current sense resistor'
                    }
                    circuit['components'].append(sense_component)
                    logger.info(f"Added current sense resistor component: {sense_ref}")

                # Then add pin net mappings
                circuit['pinNetMapping'][f"{sense_ref}.1"] = net
                circuit['pinNetMapping'][f"{sense_ref}.2"] = "GND"
                self.fixes_applied.append(f"Added sense resistor for {net}")

            elif 'OUTPUT' in net_upper or 'VOUT' in net_upper or 'OUT' in net_upper:
                # Output - add load/termination (TC #79: unique ref per net)
                term_ref = f"R_{ref}_{safe_net_suffix}_TERM"

                # Check if component already exists
                existing_refs = {c.get('ref') for c in circuit['components']}
                if term_ref not in existing_refs:
                    # First, create the component definition
                    term_component = {
                        'ref': term_ref,
                        'type': 'resistor',
                        'value': '50',  # 50 ohm termination
                        'package': '0603',
                        'pins': [
                            {'number': '1', 'name': '1', 'type': 'passive'},
                            {'number': '2', 'name': '2', 'type': 'passive'}
                        ],
                        'notes': 'Auto-added termination resistor'
                    }
                    circuit['components'].append(term_component)
                    logger.info(f"Added termination resistor component: {term_ref}")

                # Then add pin net mappings
                circuit['pinNetMapping'][f"{term_ref}.1"] = net
                circuit['pinNetMapping'][f"{term_ref}.2"] = "GND"

                # TC #79: Also update connections array to ensure net has 2+ points
                if 'connections' in circuit:
                    # Find existing connection for this net and add the new pin
                    net_conn = next((c for c in circuit['connections'] if c.get('net') == net), None)
                    if net_conn:
                        if f"{term_ref}.1" not in net_conn.get('points', []):
                            net_conn['points'].append(f"{term_ref}.1")
                    else:
                        # Create new connection
                        circuit['connections'].append({
                            'net': net,
                            'points': [pin, f"{term_ref}.1"]
                        })
                    # Add GND connection for pin 2
                    gnd_conn = next((c for c in circuit['connections'] if c.get('net') == 'GND'), None)
                    if gnd_conn:
                        if f"{term_ref}.2" not in gnd_conn.get('points', []):
                            gnd_conn['points'].append(f"{term_ref}.2")
                    else:
                        circuit['connections'].append({
                            'net': 'GND',
                            'points': [f"{term_ref}.2"]
                        })

                self.fixes_applied.append(f"Added termination for {net}")

            else:
                # Remove unused net (TC #78 fix: check if pin exists before deleting)
                if pin in circuit.get('pinNetMapping', {}):
                    del circuit['pinNetMapping'][pin]
                    self.fixes_applied.append(f"Removed unused net {net}")
                else:
                    # Pin was already removed by another fixer (e.g., StructureIssueFixer)
                    self.fixes_applied.append(f"Skipped already-removed pin {pin} for net {net}")

        return circuit

    def get_fixes_applied(self) -> List[str]:
        return self.fixes_applied


class NetConflictFixer:
    """Specialized fixer for net conflicts"""

    def __init__(self):
        self.fixes_applied = []

    def fix(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """Fix net conflicts by removing duplicate pin entries from connections"""

        for issue in issues:
            pin = issue['pin']
            nets = issue['nets']

            # Keep the net from pinNetMapping as the correct one
            correct_net = circuit.get('pinNetMapping', {}).get(pin)

            if not correct_net:
                # If pin not in mapping, use the first net
                correct_net = nets[0]
                circuit['pinNetMapping'][pin] = correct_net

            # Remove pin from all connections except the correct net
            for conn in circuit.get('connections', []):
                net_name = conn.get('net', '')
                points = conn.get('points', [])

                if net_name != correct_net and pin in points:
                    points.remove(pin)
                    conn['points'] = points
                    self.fixes_applied.append(
                        f"Removed {pin} from net '{net_name}' (keeping in '{correct_net}')"
                    )

        # Clean up empty connections
        circuit['connections'] = [
            conn for conn in circuit.get('connections', [])
            if len(conn.get('points', [])) >= 2
        ]

        return circuit

    def get_fixes_applied(self) -> List[str]:
        return self.fixes_applied


class PinMismatchFixer:
    """Specialized fixer for pin-net mismatches"""

    def __init__(self):
        self.fixes_applied = []

    def fix(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """Fix pin-net mismatches"""

        for issue in issues:
            pin_ref = issue['pin']
            pin_name = issue['pin_name']
            actual_net = issue['actual_net']

            # Determine correct net
            correct_net = None
            if pin_name == 'GND':
                correct_net = 'GND'
            elif pin_name == 'VCC':
                correct_net = 'VCC'
            elif pin_name == 'VDD':
                correct_net = 'VCC'
            elif pin_name == 'VSS':
                correct_net = 'GND'

            if correct_net:
                circuit['pinNetMapping'][pin_ref] = correct_net
                self.fixes_applied.append(
                    f"Fixed {pin_ref} ({pin_name}): {actual_net} -> {correct_net}"
                )

        return circuit

    def get_fixes_applied(self) -> List[str]:
        return self.fixes_applied


class StructureIssueFixer:
    """Specialized fixer for structural issues"""

    def __init__(self):
        self.fixes_applied = []

    def fix(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """Fix structural issues"""

        for issue in issues:
            if issue['type'] == 'missing_components':
                circuit['components'] = []
                self.fixes_applied.append("Added empty components array")

            elif issue['type'] == 'missing_pinNetMapping':
                circuit['pinNetMapping'] = {}
                self.fixes_applied.append("Added empty pinNetMapping")

            elif issue['type'] == 'missing_connections':
                circuit['connections'] = []
                self.fixes_applied.append("Added empty connections array")

            elif issue['type'] == 'wrong_connection_format':
                # This will be fixed in rebuild_circuit_structure
                pass

            elif issue['type'] == 'phantom_component':
                # CRITICAL: Remove phantom component references
                phantom_comp = issue.get('component')

                # Remove from connections
                if 'point' in issue:
                    for conn in circuit.get('connections', []):
                        points = conn.get('points', [])
                        if issue['point'] in points:
                            points.remove(issue['point'])
                            logger.warning(f"Removed phantom component {phantom_comp} from net {conn.get('net')}")
                            self.fixes_applied.append(f"Removed phantom {phantom_comp} from net {conn.get('net')}")

                # Remove from pinNetMapping
                if 'pin' in issue:
                    pin_ref = issue['pin']
                    if pin_ref in circuit.get('pinNetMapping', {}):
                        del circuit['pinNetMapping'][pin_ref]
                        logger.warning(f"Removed phantom pin reference: {pin_ref}")
                        self.fixes_applied.append(f"Removed phantom pin reference: {pin_ref}")

            elif issue['type'] == 'invalid_pin':
                # Remove invalid pin references
                comp = issue.get('component')
                pin = issue.get('pin')

                # Remove from connections
                if 'point' in issue:
                    for conn in circuit.get('connections', []):
                        points = conn.get('points', [])
                        if issue['point'] in points:
                            points.remove(issue['point'])
                            logger.warning(f"Removed invalid pin {comp}.{pin} from net {conn.get('net')}")
                            self.fixes_applied.append(f"Removed invalid pin {comp}.{pin} from connections")

                # Remove from pinNetMapping
                if 'pin_ref' in issue:
                    pin_ref = issue['pin_ref']
                    if pin_ref in circuit.get('pinNetMapping', {}):
                        del circuit['pinNetMapping'][pin_ref]
                        logger.warning(f"Removed invalid pin from pinNetMapping: {pin_ref}")
                        self.fixes_applied.append(f"Removed invalid pin from pinNetMapping: {pin_ref}")

        return circuit

    def get_fixes_applied(self) -> List[str]:
        return self.fixes_applied


class ShortedPassiveFixer:
    """
    TC #91: Specialized fixer for shorted passive components.

    When a 2-terminal passive (R, C, L, D) has both pins on the same net,
    no current can flow through it. This fixer attempts to create a proper
    connection by assigning one pin to a nearby/related net.

    This is a CRITICAL fix for SPICE simulation - without it, netlists
    will have zero-current components that make no sense electrically.
    """

    def __init__(self):
        self.fixes_applied = []

    def fix(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """
        Fix shorted passive components by reassigning one pin to a different net.

        Strategy:
        1. For bypass caps (C near IC): Keep one pin on GND, move other to VCC/power
        2. For resistors: Try to find a nearby signal net that makes sense
        3. For other passives: Create a unique net if no better option exists

        This is GENERIC and works for ANY circuit type.
        """
        pin_net_mapping = circuit.get('pinNetMapping', {})
        components_by_ref = {c.get('ref', ''): c for c in circuit.get('components', [])}

        for issue in issues:
            if issue['type'] != 'shorted_passive':
                continue

            comp_ref = issue['component']
            comp_type = issue['component_type']
            pin1 = issue['pin1']
            pin2 = issue['pin2']
            shorted_net = issue['net']

            # Find a suitable alternative net
            new_net = self._find_alternative_net(
                circuit, comp_ref, comp_type, shorted_net, pin_net_mapping
            )

            if new_net and new_net != shorted_net:
                # Reassign pin2 to the new net
                pin_net_mapping[pin2] = new_net
                logger.info(f"TC #91 FIX: Moved {pin2} from '{shorted_net}' to '{new_net}'")
                self.fixes_applied.append(f"Moved {pin2} from '{shorted_net}' to '{new_net}'")

                # Update connections too
                self._update_connections(circuit, pin2, shorted_net, new_net)
            else:
                # Create a unique net as last resort
                unique_net = f"NET_{comp_ref}"
                pin_net_mapping[pin2] = unique_net
                logger.warning(f"TC #91 FIX: Created unique net '{unique_net}' for {pin2}")
                self.fixes_applied.append(f"Created unique net '{unique_net}' for {pin2}")

                # Add to connections
                self._add_to_connections(circuit, pin2, unique_net)

        return circuit

    def _find_alternative_net(
        self, circuit: Dict, comp_ref: str, comp_type: str,
        current_net: str, pin_net_mapping: Dict
    ) -> Optional[str]:
        """
        Find a suitable alternative net for the component.

        Strategy varies by component type and current net:
        - Capacitors on GND: Look for VCC/power nets (likely bypass caps)
        - Capacitors on VCC: Look for GND (likely bypass caps)
        - Resistors: Look for nearby signal nets
        """
        all_nets = set(pin_net_mapping.values())

        # Common power/ground nets
        power_nets = {n for n in all_nets if _is_power_rail(n)}
        ground_nets = {n for n in all_nets if _is_ground_rail(n)}

        # If capacitor on ground, likely bypass cap - connect to power
        if comp_type == 'capacitor' and _is_ground_rail(current_net):
            for pnet in power_nets:
                return pnet

        # If capacitor on power, likely bypass cap - connect to ground
        if comp_type == 'capacitor' and _is_power_rail(current_net):
            for gnet in ground_nets:
                return gnet

        # For resistors on GND, look for VCC first (pull-down/pull-up)
        if comp_type == 'resistor' and _is_ground_rail(current_net):
            for pnet in power_nets:
                return pnet

        # For resistors on VCC, look for GND
        if comp_type == 'resistor' and _is_power_rail(current_net):
            for gnet in ground_nets:
                return gnet

        # Look for any signal net that's not the current one
        signal_nets = all_nets - power_nets - ground_nets - {current_net}
        for snet in signal_nets:
            return snet

        # If nothing else, try to find VCC or GND
        if power_nets:
            return next(iter(power_nets))
        if ground_nets:
            return next(iter(ground_nets))

        return None

    def _update_connections(
        self, circuit: Dict, pin: str, old_net: str, new_net: str
    ) -> None:
        """Update connections to reflect the pin reassignment."""
        connections = circuit.get('connections', [])

        # Remove pin from old net connection
        for conn in connections:
            if conn.get('net') == old_net:
                points = conn.get('points', [])
                if pin in points:
                    points.remove(pin)

        # Add pin to new net connection (create if doesn't exist)
        new_net_exists = False
        for conn in connections:
            if conn.get('net') == new_net:
                if pin not in conn.get('points', []):
                    conn.get('points', []).append(pin)
                new_net_exists = True
                break

        if not new_net_exists:
            connections.append({
                'net': new_net,
                'points': [pin]
            })

    def _add_to_connections(self, circuit: Dict, pin: str, net: str) -> None:
        """Add a pin to connections under the specified net."""
        connections = circuit.get('connections', [])

        # Check if net already exists
        for conn in connections:
            if conn.get('net') == net:
                if pin not in conn.get('points', []):
                    conn.get('points', []).append(pin)
                return

        # Create new connection entry
        connections.append({
            'net': net,
            'points': [pin]
        })

    def get_fixes_applied(self) -> List[str]:
        return self.fixes_applied


class RatingFixer:
    """
    Fixer for component rating violations (voltage/current derating).

    When components are rated below the design requirement (with standard 1.2x
    derating), this fixer logs actionable messages for the AI regeneration loop
    and annotates the circuit data so downstream stages can flag the issue.

    This fixer cannot change component part numbers — that requires AI
    re-selection. Instead, it marks violating components with a
    'rating_violation' flag so the next AI iteration can correct the selection.
    """

    def __init__(self):
        self.fixes_applied = []

    def fix(self, circuit: Dict, issues: List[Dict]) -> Dict:
        """
        Annotate components with rating violations.

        For each violating component, adds a 'rating_violation' key to the
        component dict with the required rating. This information is consumed
        by the AI prompt builder to request properly rated replacements.
        """
        components_by_ref = {c.get('ref', ''): c for c in circuit.get('components', [])}

        for issue in issues:
            if issue['type'] != 'rating_violation':
                continue

            comp_ref = issue['component']
            comp = components_by_ref.get(comp_ref)
            if not comp:
                continue

            # Annotate the component for the AI re-selection loop
            comp['rating_violation'] = {
                'rated_voltage': issue['rated_voltage'],
                'required_voltage': issue['required_voltage'],
                'system_voltage': issue['system_voltage'],
            }
            comp['notes'] = (
                comp.get('notes', '') +
                f' RATING VIOLATION: needs >={issue["required_voltage"]}V '
                f'(currently {issue["rated_voltage"]}V)'
            ).strip()

            logger.warning(
                f"Rating violation: {comp_ref} rated {issue['rated_voltage']}V, "
                f"needs {issue['required_voltage']}V"
            )
            self.fixes_applied.append(
                f"Flagged {comp_ref}: {issue['rated_voltage']}V < "
                f"{issue['required_voltage']}V required"
            )

        return circuit

    def get_fixes_applied(self) -> List[str]:
        return self.fixes_applied


def supervise_circuit(circuit: Dict) -> Dict:
    """
    Main entry point for circuit supervision
    """
    supervisor = CircuitSupervisor()
    return supervisor.supervise_and_fix(circuit)


# =============================================================================
# MULTI-AGENT VALIDATION API (Jan 2026)
# =============================================================================
# These functions provide a structured interface for the multi-agent system.
# They return validation results in a format suitable for agent processing.
# =============================================================================

def validate_module_circuit(
    circuit: Dict,
    module_name: str,
    interface_contract: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Validate a single module circuit and return structured results.

    This function is designed for use by the ValidationAgent in the
    multi-agent architecture. It performs ERC checks and returns a
    detailed report that can be processed by the agent.

    Args:
        circuit: The module circuit to validate
        module_name: Name of the module (for logging/reporting)
        interface_contract: Optional interface contract defining
                           expected inputs/outputs for this module

    Returns:
        Validation result dict with:
        - passed: bool - True if circuit passes all checks
        - issues: List of issue dicts with type, component, severity, message
        - warnings: List of warning strings
        - statistics: Component/connection counts
        - interface_check: Results of interface contract validation (if provided)
    """
    logger.info(f"Validating module circuit: {module_name}")

    supervisor = CircuitSupervisor()

    # Run ERC check without fixing
    erc_report = supervisor.run_erc_check(circuit)

    # Collect all issues with severity
    issues = []
    for category, category_issues in erc_report.get('issues', {}).items():
        for issue in category_issues:
            severity = 'critical' if category in ['power_connections', 'shorted_passives'] else 'warning'
            issues.append({
                'type': issue.get('type', category),
                'component': issue.get('component', ''),
                'severity': severity,
                'message': issue.get('message', str(issue)),
                'suggested_fix': _get_fix_suggestion(issue)
            })

    # Collect warnings (non-critical issues)
    warnings = []
    for category, category_issues in erc_report.get('issues', {}).items():
        if category in ['single_ended_nets', 'floating_components']:
            for issue in category_issues:
                warnings.append(f"[{category}] {issue.get('message', str(issue))}")

    # Calculate statistics
    components = circuit.get('components', [])
    connections = circuit.get('connections', [])
    nets = circuit.get('nets', [])
    pin_net_mapping = circuit.get('pinNetMapping', {})

    statistics = {
        'total_components': len(components),
        'total_connections': len(connections),
        'total_nets': len(nets) if isinstance(nets, list) else len(set(pin_net_mapping.values())),
        'ics_count': sum(1 for c in components if c.get('type', '').lower() in ['ic', 'opamp', 'amplifier']),
        'passives_count': sum(1 for c in components if c.get('type', '').lower() in ['resistor', 'capacitor', 'inductor'])
    }

    # Check interface contract if provided
    interface_check = None
    if interface_contract:
        interface_check = _validate_interface_contract(circuit, interface_contract)

    # Determine pass/fail
    critical_issues = [i for i in issues if i.get('severity') == 'critical']
    passed = len(critical_issues) == 0

    if interface_check and not interface_check.get('passed', True):
        passed = False

    result = {
        'passed': passed,
        'module_name': module_name,
        'issues': issues,
        'warnings': warnings,
        'statistics': statistics,
        'erc_report': erc_report
    }

    if interface_check:
        result['interface_check'] = interface_check

    # Log summary
    if passed:
        logger.info(f"  ✅ Module {module_name} passed validation")
    else:
        logger.warning(f"  ❌ Module {module_name} failed validation ({len(critical_issues)} critical issues)")

    return result


def validate_integrated_circuit(
    circuit: Dict,
    modules: List[Dict],
    interface_contracts: Dict[str, Dict]
) -> Dict[str, Any]:
    """
    Validate an integrated circuit (multiple modules combined).

    This function performs system-level validation after module integration.
    It checks for proper inter-module connections and system-wide issues.

    Args:
        circuit: The integrated circuit containing all modules
        modules: List of module metadata dicts
        interface_contracts: Dict mapping module names to their interface contracts

    Returns:
        Validation result dict with system-level checks
    """
    logger.info("Validating integrated circuit")

    supervisor = CircuitSupervisor()

    # Run ERC check
    erc_report = supervisor.run_erc_check(circuit)

    # System-level checks
    system_checks = {
        'power_integrity': _check_power_integrity(circuit),
        'ground_integrity': _check_ground_integrity(circuit),
        'interface_completion': _check_interface_completion(circuit, interface_contracts),
        'module_connectivity': _check_module_connectivity(circuit, modules)
    }

    # Collect all issues
    issues = []
    for check_name, check_result in system_checks.items():
        if not check_result.get('passed', True):
            issues.append({
                'type': check_name,
                'severity': 'critical' if 'power' in check_name or 'ground' in check_name else 'error',
                'message': check_result.get('details', f'{check_name} failed')
            })

    # Add ERC issues
    for category, category_issues in erc_report.get('issues', {}).items():
        for issue in category_issues:
            issues.append({
                'type': issue.get('type', category),
                'component': issue.get('component', ''),
                'severity': 'warning',
                'message': issue.get('message', str(issue))
            })

    # Calculate statistics
    components = circuit.get('components', [])
    statistics = {
        'total_components': len(components),
        'total_nets': len(set(circuit.get('pinNetMapping', {}).values())),
        'power_connections': sum(1 for n in circuit.get('pinNetMapping', {}).values() if _is_power_rail(n)),
        'ground_connections': sum(1 for n in circuit.get('pinNetMapping', {}).values() if _is_ground_rail(n)),
        'modules_integrated': len(modules)
    }

    # Determine overall pass
    critical_issues = [i for i in issues if i.get('severity') == 'critical']
    passed = len(critical_issues) == 0

    return {
        'passed': passed,
        'system_checks': system_checks,
        'issues': issues,
        'statistics': statistics,
        'erc_report': erc_report
    }


def _get_fix_suggestion(issue: Dict) -> str:
    """Get a suggested fix for an issue."""
    issue_type = issue.get('type', '')

    suggestions = {
        'ic_missing_power': 'Connect IC VCC/VDD pin to appropriate power rail',
        'ic_missing_ground': 'Connect IC GND/VSS pin to ground',
        'unconnected_power_pin': f"Connect {issue.get('pin', 'pin')} to {issue.get('expected_net', 'power rail')}",
        'floating_component': 'Connect all component pins to appropriate nets',
        'single_ended_net': 'Connect net to at least one more component',
        'shorted_passive': 'Move one pin to a different net - both pins on same net means no current flow',
        'net_conflict': 'Resolve conflicting net assignments',
        'phantom_component': 'Remove reference to non-existent component',
        'invalid_pin': 'Fix pin reference to match component definition'
    }

    return suggestions.get(issue_type, 'Review and fix the issue manually')


def _validate_interface_contract(circuit: Dict, contract: Dict) -> Dict[str, Any]:
    """
    Validate circuit against interface contract.

    Checks that:
    - All required output signals are present
    - Power requirements are met
    - Input signals have appropriate connections
    """
    issues = []
    nets = set(circuit.get('pinNetMapping', {}).values())

    # Check output signals
    for signal_name, signal_spec in contract.get('outputs', {}).items():
        if signal_name not in nets:
            # Check if signal exists with module prefix
            found = any(signal_name in n for n in nets)
            if not found:
                issues.append({
                    'type': 'missing_output_signal',
                    'signal': signal_name,
                    'message': f"Required output signal '{signal_name}' not found"
                })

    # Check input requirements
    for input_name, input_spec in contract.get('inputs', {}).items():
        if input_spec.get('type') == 'power':
            # Check power rail exists
            if input_name not in nets:
                issues.append({
                    'type': 'missing_power_input',
                    'signal': input_name,
                    'message': f"Required power input '{input_name}' not found"
                })

    passed = len(issues) == 0
    return {
        'passed': passed,
        'issues': issues,
        'details': f"Checked {len(contract.get('outputs', {}))} outputs, {len(contract.get('inputs', {}))} inputs"
    }


def _check_power_integrity(circuit: Dict) -> Dict[str, Any]:
    """Check that power distribution is complete."""
    pin_net_mapping = circuit.get('pinNetMapping', {})
    components = circuit.get('components', [])

    # Find all power rails
    power_rails = set(n for n in pin_net_mapping.values() if _is_power_rail(n))

    # Count connections per power rail
    rail_connections = {}
    for pin, net in pin_net_mapping.items():
        if _is_power_rail(net):
            if net not in rail_connections:
                rail_connections[net] = 0
            rail_connections[net] += 1

    # Check that ICs have power
    ics_without_power = []
    for comp in components:
        if comp.get('type', '').lower() in ['ic', 'opamp', 'amplifier', 'microcontroller']:
            ref = comp.get('ref', '')
            has_power = any(
                _is_power_rail(pin_net_mapping.get(f"{ref}.{p.get('number', '')}", ''))
                for p in comp.get('pins', [])
            )
            if not has_power:
                ics_without_power.append(ref)

    passed = len(ics_without_power) == 0
    details = f"Power rails: {list(power_rails)}, ICs without power: {ics_without_power}"

    return {
        'passed': passed,
        'details': details,
        'power_rails': list(power_rails),
        'ics_without_power': ics_without_power
    }


def _check_ground_integrity(circuit: Dict) -> Dict[str, Any]:
    """Check that ground connections are complete."""
    pin_net_mapping = circuit.get('pinNetMapping', {})

    # Count ground connections
    ground_connections = sum(1 for n in pin_net_mapping.values() if _is_ground_rail(n))

    # Ground should be the most connected net (or close to it)
    net_counts = {}
    for net in pin_net_mapping.values():
        if net not in net_counts:
            net_counts[net] = 0
        net_counts[net] += 1

    ground_nets = {n: c for n, c in net_counts.items() if _is_ground_rail(n)}
    total_ground = sum(ground_nets.values())

    # Ground should have a minimum fraction of total connections
    passed = total_ground >= len(pin_net_mapping) * config.QUALITY_GATES["min_ground_connection_ratio"]

    return {
        'passed': passed,
        'details': f"Ground connections: {total_ground}/{len(pin_net_mapping)} ({total_ground*100//max(1,len(pin_net_mapping))}%)",
        'ground_nets': ground_nets
    }


def _check_interface_completion(circuit: Dict, interface_contracts: Dict) -> Dict[str, Any]:
    """Check that all interface signals are routed."""
    nets = set(circuit.get('pinNetMapping', {}).values())
    missing_signals = []

    for module_name, contract in interface_contracts.items():
        # Check outputs are present
        for signal in contract.get('signals_out', []):
            if signal not in nets and not any(signal in n for n in nets):
                missing_signals.append(f"{module_name}.{signal}")

    passed = len(missing_signals) == 0

    return {
        'passed': passed,
        'details': f"Interface signals: {len(missing_signals)} missing",
        'missing_signals': missing_signals
    }


def _check_module_connectivity(circuit: Dict, modules: List[Dict]) -> Dict[str, Any]:
    """Check that all modules are connected to each other."""
    # This is a simplified check - in practice would need more sophisticated analysis
    components = circuit.get('components', [])
    module_names = [m.get('name', m.get('module', '')) for m in modules]

    # Count components per "module" (by prefix)
    module_components = {name: 0 for name in module_names}
    for comp in components:
        ref = comp.get('ref', '')
        for name in module_names:
            if name.upper() in ref.upper() or ref.startswith(name.replace('_', '')):
                module_components[name] += 1
                break

    # Check that all modules have components
    orphan_modules = [m for m, count in module_components.items() if count == 0]

    passed = len(orphan_modules) == 0

    return {
        'passed': passed,
        'details': f"Module connectivity: {len(orphan_modules)} orphan modules",
        'orphan_modules': orphan_modules,
        'module_components': module_components
    }
