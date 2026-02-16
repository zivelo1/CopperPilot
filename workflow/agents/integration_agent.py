# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Integration Agent - Cross-module integration and backplane creation.

The Integration Agent is responsible for connecting all designed modules
into a single unified circuit. It:
1. Merges all module circuits
2. Creates backplane connections between modules
3. Ensures interface signals are properly routed
4. Validates system-level connectivity

Author: CopperPilot Team
Date: January 2026
Version: 1.0

Key Design Principles:
- SYSTEM-LEVEL: Sees all modules (unlike Module Agent)
- INTERFACE-DRIVEN: Connects via defined interfaces
- NON-INVASIVE: Doesn't modify internal module wiring
- BACKPLANE-FOCUSED: Creates interconnect layer
"""

import json
import re
from typing import Dict, List, Any, Optional, Set
from pathlib import Path

from utils.logger import setup_logger
from server.config import config

logger = setup_logger(__name__)


class IntegrationAgent:
    """
    Cross-module integration agent.

    The Integration Agent merges individually designed modules into
    a single circuit and creates the interconnections between them.

    It operates at the SYSTEM level, seeing all modules but NOT
    modifying their internal structure.

    Attributes:
        ai_manager: Reference to the AI Agent Manager
    """

    def __init__(self, ai_manager):
        """
        Initialize the Integration Agent.

        Args:
            ai_manager: The AI Agent Manager instance
        """
        self.ai_manager = ai_manager

    async def integrate_modules(self, modules: List[Dict],
                                 interfaces: Dict) -> Dict:
        """
        Integrate all modules into a single circuit.

        This method:
        1. Merges all module components
        2. Merges all module connections
        3. Creates inter-module connections via interfaces
        4. Creates backplane circuit if needed
        5. Returns unified circuit

        Args:
            modules: List of module design results, each containing:
                - module_name: Name of the module
                - components: List of components
                - connections: List of connections
                - pinNetMapping: Pin to net mapping

            interfaces: Interface contracts for all modules

        Returns:
            Integrated circuit dict
        """
        logger.info("         IntegrationAgent: Integrating modules...")

        # DEBUG: Log integration inputs
        logger.debug(f"[INTEGRATION_AGENT] Modules to integrate: {len(modules)}")
        for mod in modules:
            mod_name = mod.get('module_name', 'Unknown')
            comp_count = len(mod.get('components', []))
            conn_count = len(mod.get('connections', []))
            logger.debug(f"[INTEGRATION_AGENT]   - {mod_name}: {comp_count} components, {conn_count} connections")
        logger.debug(f"[INTEGRATION_AGENT] Interface contracts defined for: {list(interfaces.keys())}")

        # TC #95: PRE-INTEGRATION VALIDATION
        # Check for potential issues before integration
        for mod in modules:
            mod_name = mod.get('module_name', 'Unknown')
            issues = self._validate_module_for_integration(mod)
            if issues:
                for issue in issues:
                    logger.warning(f"[INTEGRATION_AGENT] Pre-integration issue in {mod_name}: {issue}")

        # Start with empty integrated circuit
        integrated = {
            'circuitName': 'Integrated_Circuit',
            'components': [],
            'connections': [],
            'pinNetMapping': {},
            'nets': []
        }

        # Track module prefixes to avoid ref conflicts
        used_refs = set()
        module_prefix_map = {}

        # =========================================================================
        # STEP 1: Merge module components (with prefix if needed)
        # =========================================================================
        logger.info("         Step 1: Merging module components...")

        for module in modules:
            module_name = module.get('module_name', 'Unknown')
            components = module.get('components', [])

            # Determine if we need prefixes (if refs conflict)
            needs_prefix = False
            for comp in components:
                ref = comp.get('ref', '')
                if ref in used_refs:
                    needs_prefix = True
                    break

            # Create prefix if needed
            prefix = ''
            if needs_prefix:
                # Create prefix from module name
                prefix = self._create_module_prefix(module_name)
                module_prefix_map[module_name] = prefix

            # Add components with optional prefix
            for comp in components:
                new_comp = comp.copy()
                old_ref = comp.get('ref', '')

                if prefix:
                    new_comp['ref'] = f"{prefix}_{old_ref}"
                    new_comp['original_ref'] = old_ref
                    new_comp['source_module'] = module_name

                # Ensure we're not creating conflicts
                while new_comp['ref'] in used_refs:
                    new_comp['ref'] = f"{new_comp['ref']}_"

                used_refs.add(new_comp['ref'])
                integrated['components'].append(new_comp)

            logger.info(f"            Added {len(components)} components from {module_name}")

        # =========================================================================
        # Y.2 FIX: SAME-NAME NET AUTO-MERGE DETECTION
        # =========================================================================
        # Before prefixing, detect nets that appear in ≥2 modules with the
        # same name (case-insensitive). These are cross-module shared nets
        # by naming convention and must NOT be prefixed.
        # GENERIC: Works for ANY circuit topology — no hardcoded net names.
        # =========================================================================
        net_module_count: Dict[str, set] = {}  # net_upper -> set of module names
        for module in modules:
            mod_name = module.get('module_name') or ''
            if not mod_name:
                continue
            pnm = module.get('pinNetMapping', {})
            for net in set(pnm.values()):
                net_upper = net.upper()
                if net_upper not in net_module_count:
                    net_module_count[net_upper] = set()
                net_module_count[net_upper].add(mod_name)

        cross_module_nets = frozenset(
            net_upper for net_upper, mod_set in net_module_count.items()
            if len(mod_set) >= 2
        )
        if cross_module_nets:
            logger.info(
                f"         Y.2: Detected {len(cross_module_nets)} same-name net(s) "
                f"across modules: {sorted(cross_module_nets)[:10]}"
                f"{'...' if len(cross_module_nets) > 10 else ''}"
            )

        # =========================================================================
        # STEP 2: Merge module connections (update refs if prefixed)
        # =========================================================================
        logger.info("         Step 2: Merging module connections...")

        for module in modules:
            module_name = module.get('module_name', 'Unknown')
            pin_net_mapping = module.get('pinNetMapping', {})
            prefix = module_prefix_map.get(module_name, '')

            for pin_ref, net in pin_net_mapping.items():
                # Update pin ref if prefixed
                if prefix:
                    # Split pin ref: "R1.1" -> "PWR_R1.1"
                    parts = pin_ref.split('.')
                    if len(parts) == 2:
                        new_pin_ref = f"{prefix}_{parts[0]}.{parts[1]}"
                    else:
                        new_pin_ref = f"{prefix}_{pin_ref}"
                else:
                    new_pin_ref = pin_ref

                # Update net name if it's a module-local net
                # Keep power/ground nets global
                # Y.2 FIX: Also keep nets shared across ≥2 modules (same-name auto-merge)
                if not self._is_global_net(net) and net.upper() not in cross_module_nets:
                    if prefix:
                        new_net = f"{prefix}_{net}"
                    else:
                        new_net = f"{module_name}_{net}"
                else:
                    new_net = net

                integrated['pinNetMapping'][new_pin_ref] = new_net

        # =========================================================================
        # STEP 3: Create inter-module connections via interfaces
        # =========================================================================
        # Fix H.1: Pass module_prefix_map so interface connections use PREFIXED
        # pin refs matching the integrated component names.  Without this the
        # supervisor sees unprefixed refs as phantom and removes them.
        # Fix H.2: Pass _is_global_net so already-global nets (power/ground)
        # are NOT wrapped in SYS_ — they are already shared by name.
        # =========================================================================
        logger.info("         Step 3: Creating inter-module connections...")

        interface_connections = self._create_interface_connections(
            modules, interfaces, module_prefix_map
        )

        # Phase A (Forensic Fix 20260208): Validate integration results
        integration_status = self._validate_interface_connections(interface_connections, interfaces)

        # Merge interface connections
        for pin_ref, net in interface_connections.items():
            integrated['pinNetMapping'][pin_ref] = net

        # =========================================================================
        # STEP 4: Create backplane if needed
        # =========================================================================
        logger.info("         Step 4: Creating backplane...")

        backplane = self._create_backplane(modules, interfaces)
        if backplane:
            integrated['components'].extend(backplane.get('components', []))
            for pin_ref, net in backplane.get('pinNetMapping', {}).items():
                integrated['pinNetMapping'][pin_ref] = net

        # =========================================================================
        # STEP 5: Rebuild connections from pinNetMapping
        # =========================================================================
        logger.info("         Step 5: Rebuilding connections...")

        net_to_pins = {}
        for pin, net in integrated['pinNetMapping'].items():
            if net not in net_to_pins:
                net_to_pins[net] = []
            net_to_pins[net].append(pin)

        integrated['connections'] = [
            {'net': net, 'points': sorted(pins)}
            for net, pins in net_to_pins.items()
        ]
        integrated['nets'] = sorted(net_to_pins.keys())

        # =========================================================================
        # Final stats
        # =========================================================================
        total_comps = len(integrated['components'])
        total_conns = len(integrated['connections'])
        total_nets = len(integrated['nets'])

        logger.info(f"         Integration complete: {total_comps} components, "
                   f"{total_conns} connections, {total_nets} nets")

        # Fix H.3: Attach the raw interface signal map so downstream code
        # (DesignSupervisor → step_3_low_level) can build the SYS_ net map
        # from the source-of-truth definitions instead of parsing the
        # post-supervisor pinNetMapping (which may have been cleaned).
        integrated['_interface_signal_map'] = getattr(
            self, '_raw_interface_signal_map', {}
        )
        
        # Phase A (Forensic Fix 20260211): Store integration quality metrics
        integrated['_integration_status'] = integration_status

        # =========================================================================
        # W FIX: Physical port audit for global nets
        # =========================================================================
        port_audit = self._audit_global_net_ports(integrated)
        integrated['_port_audit'] = port_audit

        return integrated

    # Characters that conflict with pin reference syntax (component.pin)
    # These MUST be removed from prefixes to prevent parsing failures
    PREFIX_INVALID_CHARS = r'[.\-/\\:;,\s\(\)\[\]\{\}]'

    def _create_module_prefix(self, module_name: str) -> str:
        """
        Create a short prefix from module name.

        TC #95 FIX: Sanitizes special characters that would break pin reference
        parsing. The period '.' is especially critical as it's the delimiter
        in pin refs (e.g., "R1.1" = component R1 pin 1).

        Args:
            module_name: Full module name (e.g., "Channel_2_Module_1.5MHz")

        Returns:
            Short prefix (e.g., "CHA_2_15MHZ") - guaranteed to contain no
            characters that conflict with pin reference syntax
        """
        # Remove common words
        name = module_name.replace('_Module', '').replace('_module', '')
        name = name.replace('Module', '').replace('module', '')

        # TC #95 CRITICAL FIX: Sanitize special characters BEFORE splitting
        # This prevents periods from module names like "1.5MHz" from corrupting prefixes
        name = re.sub(self.PREFIX_INVALID_CHARS, '', name)

        # Take first 3-4 chars of each word
        words = re.split(r'[_]+', name)
        prefix_parts = []

        for word in words:
            if word:
                # Additional per-word sanitization - keep only alphanumeric
                clean_word = re.sub(r'[^a-zA-Z0-9]', '', word)
                if clean_word:
                    prefix_parts.append(clean_word[:3].upper())

        prefix = '_'.join(prefix_parts) if prefix_parts else 'MOD'

        # Validate the prefix doesn't contain problematic characters
        if not self._validate_prefix(prefix):
            logger.warning(f"[INTEGRATION_AGENT] Prefix '{prefix}' contains invalid chars, sanitizing...")
            prefix = re.sub(r'[^A-Za-z0-9_]', '', prefix)

        return prefix

    def _validate_prefix(self, prefix: str) -> bool:
        """
        Validate that a prefix doesn't contain characters that break pin parsing.

        Args:
            prefix: The prefix to validate

        Returns:
            True if prefix is safe, False if it contains problematic characters
        """
        # Characters used in pin references that must not appear in prefixes
        invalid_chars = '.:'
        return not any(c in prefix for c in invalid_chars)

    def _is_global_net(self, net: str) -> bool:
        """
        Check if a net is global (shared across modules).

        Phase A (Forensic Fix 20260208): Overhauled to prevent false globalization.
        - Power rails and ground: still use substring matching (safe — these are
          distinctive enough to not false-positive).
        - System bus signals (SPI, I2C, UART, etc.): still use substring matching.
        - Interface keywords (SENSE, CONTROL, etc.): now use PREFIX/SUFFIX matching
          instead of substring, preventing "ADC_CH0" from matching "ADC".
        - Negative patterns: nets matching NC_* or *_LOCAL are never global.
        - Pin-reference net names (e.g., "U2.6") are never global.
        - Keywords loaded from config.INTEGRATION_GLOBAL_NET_KEYWORDS.

        Args:
            net: Net name

        Returns:
            True if global net
        """
        if not net:
            return False

        net_upper = net.upper()

        # Negative patterns: never globalise these
        for local_pat in config.INTEGRATION_LOCAL_NET_PATTERNS:
            local_upper = local_pat.upper()
            if net_upper.startswith(local_upper) or net_upper.endswith(local_upper):
                return False

        # Pin-reference net names are never global
        if self._PIN_REF_RE.match(net):
            return False

        # Power rails — substring matching is safe here (distinctive keywords)
        if any(x in net_upper for x in config.INTEGRATION_POWER_NET_KEYWORDS):
            return True

        # Ground — substring matching is safe
        if any(x in net_upper for x in config.INTEGRATION_GROUND_NET_KEYWORDS):
            return True

        # System bus signals — substring matching is safe (distinctive bus names)
        if any(x in net_upper for x in config.INTEGRATION_SYSTEM_NET_KEYWORDS):
            return True

        # SYS_ prefix always indicates global net
        if net_upper.startswith('SYS_'):
            return True

        # Interface keywords — PREFIX/SUFFIX matching only (not substring).
        # This prevents "ADC_CH0" from matching keyword "ADC" via substring,
        # while still matching "ADC_OUTPUT" (starts with "ADC_") or
        # "TEMP_SENSE" (ends with "_SENSE").
        for keyword in config.INTEGRATION_GLOBAL_NET_KEYWORDS:
            kw_upper = keyword.upper()
            # Exact match
            if net_upper == kw_upper:
                return True
            # Prefix match: net starts with "KEYWORD_"
            if net_upper.startswith(kw_upper + '_'):
                return True
            # Suffix match: net ends with "_KEYWORD"
            if net_upper.endswith('_' + kw_upper):
                return True

        # M.4 FIX: Signal suffixes indicate global cross-module signals.
        # E.g., PGOOD_CONDITIONED, FAULT_FILTERED, ENABLE_DEBOUNCED
        for suffix in config.INTEGRATION_SIGNAL_SUFFIXES:
            if net_upper.endswith(suffix.upper()):
                return True

        return False

    def _create_interface_connections(self, modules: List[Dict],
                                       interfaces: Dict,
                                       module_prefix_map: Dict[str, str] = None) -> Dict:
        """
        Create connections between modules via their interfaces.

        TC #94/95 FIX: This method creates connections using flexible signal matching:
        1. Building a map of all interface output signals and their source pins
        2. Building a map of all interface input signals and their sink pins
        3. Creating global nets that connect outputs to inputs

        Fix H.1: Uses module_prefix_map to output PREFIXED pin refs that match
        the integrated circuit's component names.  Without prefixing, the
        Circuit Supervisor identifies unprefixed refs as phantom and removes
        every SYS_ net entry — the root cause of zero SYS_ nets in output.

        Fix H.2: Nets that are already globally shared (power rails, ground)
        are NOT wrapped in SYS_ — adding the prefix to nets like "+12V_digital"
        is counterproductive because per-module files already use that name.

        Args:
            modules: List of module circuits
            interfaces: Interface contracts
            module_prefix_map: Mapping of module_name → prefix string
                (from Step 1 of integrate_modules).  If None, pin refs are
                returned unprefixed (backward-compatible fallback).

        Returns:
            Dict of pin_ref -> net for interface connections.
            Also stores self._raw_interface_signal_map for downstream use
            (mapping raw signal name → global SYS_ net name).
        """
        if module_prefix_map is None:
            module_prefix_map = {}

        sys_prefix = config.SYS_NET_PREFIX  # Default "SYS_"

        interface_connections = {}

        # ------------------------------------------------------------------
        # Helper: apply module prefix to a pin ref so it matches the
        # integrated component list built in Step 1.
        # "R1.1" + prefix "PWR" → "PWR_R1.1"
        # ------------------------------------------------------------------
        def _prefix_pin_ref(pin_ref: str, prefix: str) -> str:
            if not prefix:
                return pin_ref
            parts = pin_ref.split('.')
            if len(parts) == 2:
                return f"{prefix}_{parts[0]}.{parts[1]}"
            return f"{prefix}_{pin_ref}"

        # Build map of interface output signals -> source module and pins
        output_signals = {}  # signal_name -> {'module': str, 'pins': [str]}

        for module in modules:
            module_name = module.get('module_name') or ''
            if not module_name:
                logger.warning("Module missing 'module_name' — skipping output signal mapping")
                continue
            interface = interfaces.get(module_name, {})
            pin_net_mapping = module.get('pinNetMapping', {})
            components = module.get('components', [])
            prefix = module_prefix_map.get(module_name, '')

            # Get output signals from this module
            for signal_name in interface.get('outputs', {}).keys():
                if signal_name not in output_signals:
                    output_signals[signal_name] = {'module': module_name, 'pins': []}

                matched_pins = self._find_matching_pins(pin_net_mapping, signal_name, components)
                # Fix H.1: prefix every matched pin ref
                output_signals[signal_name]['pins'].extend(
                    _prefix_pin_ref(p, prefix) for p in matched_pins
                )

            # Also check power_out
            for rail in interface.get('power_out', []):
                if rail not in output_signals:
                    output_signals[rail] = {'module': module_name, 'pins': []}
                    matched_pins = self._find_matching_pins(pin_net_mapping, rail, components)
                    output_signals[rail]['pins'].extend(
                        _prefix_pin_ref(p, prefix) for p in matched_pins
                    )

        # Build map of interface input signals -> sink module and pins
        input_signals = {}  # signal_name -> {'module': str, 'pins': [str]}

        for module in modules:
            module_name = module.get('module_name') or ''
            if not module_name:
                logger.warning("Module missing 'module_name' — skipping input signal mapping")
                continue
            interface = interfaces.get(module_name, {})
            pin_net_mapping = module.get('pinNetMapping', {})
            components = module.get('components', [])
            prefix = module_prefix_map.get(module_name, '')

            # Get input signals for this module
            for signal_name in interface.get('inputs', {}).keys():
                if signal_name not in input_signals:
                    input_signals[signal_name] = {'module': module_name, 'pins': []}

                matched_pins = self._find_matching_pins(pin_net_mapping, signal_name, components)
                # Fix H.1: prefix every matched pin ref
                input_signals[signal_name]['pins'].extend(
                    _prefix_pin_ref(p, prefix) for p in matched_pins
                )

            # Also check power_in
            for rail in interface.get('power_in', []):
                if rail not in input_signals:
                    input_signals[rail] = {'module': module_name, 'pins': []}
                    matched_pins = self._find_matching_pins(pin_net_mapping, rail, components)
                    input_signals[rail]['pins'].extend(
                        _prefix_pin_ref(p, prefix) for p in matched_pins
                    )

        # ------------------------------------------------------------------
        # Create connections: connect outputs to inputs via global net names.
        # Fix H.2: If the signal is already a global net (power/ground),
        # keep its original name — do NOT add SYS_ prefix.
        # ------------------------------------------------------------------
        connected_count = 0
        unmatched_outputs = []
        unmatched_inputs = []

        # Build the raw signal → global net mapping for downstream use
        raw_interface_signal_map = {}

        for signal_name, output_info in output_signals.items():
            if signal_name in input_signals:
                input_info = input_signals[signal_name]

                # Fix H.2: Power/ground rails are already globally shared.
                # Adding SYS_ to "+12V_digital" would force per-module files
                # to rename a net that already matches across modules.
                if self._is_global_net(signal_name):
                    global_net = signal_name  # Keep original name
                else:
                    global_net = f"{sys_prefix}{signal_name}"

                # Connect all output pins to global net
                for pin_ref in output_info['pins']:
                    interface_connections[pin_ref] = global_net

                # Connect all input pins to global net
                for pin_ref in input_info['pins']:
                    interface_connections[pin_ref] = global_net

                # Store in raw map (for step_3 to propagate to modules)
                raw_interface_signal_map[signal_name] = global_net
                raw_interface_signal_map[signal_name.upper()] = global_net

                connected_count += 1
                out_count = len(output_info['pins'])
                in_count = len(input_info['pins'])
                logger.info(f"            Interface: {signal_name} - connected {out_count} outputs to {in_count} inputs via {global_net}")
            else:
                # Log unmatched output signals for debugging
                if output_info['pins']:
                    unmatched_outputs.append(signal_name)

        # Log unmatched input signals
        for signal_name, input_info in input_signals.items():
            if signal_name not in output_signals and input_info['pins']:
                unmatched_inputs.append(signal_name)

        # Fix K.2: Fuzzy fallback matching for unmatched signals.
        # Try normalized name matching (strip underscores, case-insensitive)
        # before giving up. This catches "POWER_GOOD" vs "POWERGOOD", etc.
        still_unmatched_out = []
        self_contained_out = []
        for signal_name in unmatched_outputs:
            sig_norm = signal_name.upper().replace('_', '')
            matched = False
            for in_name, in_info in input_signals.items():
                if in_name in output_signals:
                    continue  # Already matched
                in_norm = in_name.upper().replace('_', '')
                if sig_norm == in_norm or sig_norm in in_norm or in_norm in sig_norm:
                    # Fuzzy match found — create the connection
                    out_info = output_signals[signal_name]
                    if self._is_global_net(signal_name):
                        global_net = signal_name
                    else:
                        global_net = f"{sys_prefix}{signal_name}"
                    for pin_ref in out_info['pins']:
                        interface_connections[pin_ref] = global_net
                    for pin_ref in in_info['pins']:
                        interface_connections[pin_ref] = global_net
                    raw_interface_signal_map[signal_name] = global_net
                    connected_count += 1
                    matched = True
                    logger.info(
                        f"            Interface (fuzzy): {signal_name} ~ {in_name} via {global_net}"
                    )
                    break
            if not matched:
                # Y.2 FIX: Check if signal is self-contained within source module
                # (connected to ≥2 pins internally — not an integration failure)
                out_info = output_signals[signal_name]
                source_module = next(
                    (m for m in modules if m.get('module_name') == out_info['module']),
                    None
                )
                is_self_contained = False
                if source_module:
                    pnm = source_module.get('pinNetMapping', {})
                    internal_pin_count = sum(
                        1 for net in pnm.values()
                        if net.upper() == signal_name.upper()
                    )
                    if internal_pin_count >= 2:
                        is_self_contained = True

                if is_self_contained:
                    self_contained_out.append(signal_name)
                    logger.debug(
                        f"[INTEGRATION_AGENT] Self-contained output: '{signal_name}' "
                        f"(>=2 internal connections in {out_info['module']})"
                    )
                else:
                    still_unmatched_out.append(signal_name)

        still_unmatched_in = []
        external_inputs = []
        for signal_name in unmatched_inputs:
            sig_norm = signal_name.upper().replace('_', '')
            # Check if already resolved by fuzzy pass above
            already_connected = any(
                sig_norm == raw_interface_signal_map.get(k, '').upper().replace('_', '')
                for k in raw_interface_signal_map
            )
            if already_connected:
                continue

            # Y.2 FIX: Check if this is an external system-boundary input
            # (e.g., VIN_RAW, MAINS, AC_IN — no producer module expected)
            is_external = any(
                re.search(pattern, signal_name)
                for pattern in config.EXTERNAL_INPUT_NET_PATTERNS
            )
            if is_external:
                external_inputs.append(signal_name)
                logger.debug(
                    f"[INTEGRATION_AGENT] External system-boundary input: '{signal_name}'"
                )
            else:
                still_unmatched_in.append(signal_name)

        # Fix K.2: Escalate truly unmatched signals to ERROR.
        # Y.2 FIX: External inputs and self-contained signals are expected — not errors.
        if still_unmatched_out:
            logger.error(
                f"[INTEGRATION_AGENT] UNMATCHED output signals (no consumer module): "
                f"{still_unmatched_out}"
            )
        if still_unmatched_in:
            logger.error(
                f"[INTEGRATION_AGENT] UNMATCHED input signals (no producer module): "
                f"{still_unmatched_in}"
            )
        if self_contained_out:
            logger.info(
                f"            Self-contained outputs (valid, not integration failures): "
                f"{self_contained_out}"
            )
        if external_inputs:
            logger.info(
                f"            External system-boundary inputs (no producer expected): "
                f"{external_inputs}"
            )

        logger.info(f"            Created {connected_count} inter-module signal connections")

        # Store the raw signal map on the instance for downstream retrieval
        # (DesignSupervisor passes this through to step_3_low_level.py)
        self._raw_interface_signal_map = raw_interface_signal_map

        # Y.2 FIX: Store classification counts for validation ratio adjustment
        self._external_input_count = len(external_inputs)
        self._self_contained_output_count = len(self_contained_out)

        return interface_connections

    # Compiled pin-reference pattern (e.g., "U2.6", "R10.2") — reused across calls
    _PIN_REF_RE = re.compile(config.PIN_REFERENCE_PATTERN)

    @staticmethod
    def _strip_hardware_prefixes(name: str) -> str:
        """
        V.3 FIX: Strip MCU-specific hardware prefixes from signal names.

        Bridges the gap between hardware-specific names generated by AI
        (e.g., ADC1_AIN0, TIM1_CH1, PA0) and functional interface names
        (e.g., I_SENSE_A, PWM_A).

        Uses config.INTEGRATION_HARDWARE_PREFIXES_TO_STRIP as single source
        of truth for prefix patterns.

        Args:
            name: Signal or net name (e.g., "ADC1_AIN0")

        Returns:
            Name with hardware prefix stripped (e.g., "AIN0"), or original
            if no prefix matched or result would be empty
        """
        upper = name.upper()
        for pattern in config.INTEGRATION_HARDWARE_PREFIXES_TO_STRIP:
            stripped = re.sub(pattern, '', upper, count=1, flags=re.IGNORECASE)
            if stripped and stripped != upper:
                return stripped
        return upper

    @staticmethod
    def _extract_functional_keywords(name: str) -> Set[str]:
        """
        V.3 FIX: Extract functional keywords from a signal name.

        Splits on underscores and common delimiters, returning a set of
        meaningful tokens for semantic comparison.

        Args:
            name: Signal name (e.g., "I_SENSE_A", "CHANNEL_B_TEMP")

        Returns:
            Set of uppercase keyword tokens (e.g., {"I", "SENSE", "A"})
        """
        # Split on underscores, digits-to-letters boundaries
        tokens = re.split(r'[_\-]+', name.upper())
        # Filter out single-char tokens and pure numbers (not meaningful)
        return {t for t in tokens if len(t) >= 2 and not t.isdigit()}

    def _find_matching_pins(self, pin_net_mapping: Dict[str, str], signal_name: str,
                             components: List[Dict] = None) -> List[str]:
        """
        Find pins connected to a signal with controlled matching strategies.

        Phase A (Forensic Fix 20260208): Overhauled to prevent false wiring.
        V.3 FIX: Added Strategy 2.5 (hardware-prefix-stripped matching) and
        Strategy 4.5 (functional keyword matching) to bridge the semantic gap
        between MCU-specific pin names and functional interface names.

        Strategies (in order):
        1. Exact match (case-insensitive)
        2. Normalized match (ignoring underscores)
        2.5. Hardware-prefix-stripped match (V.3 FIX)
        3. Suffix match (last segment, min length threshold)
        4. Contains match (signal in net name, min length threshold)
        4.5. Functional keyword match (V.3 FIX)

        Args:
            pin_net_mapping: Dict of pin_ref -> net_name
            signal_name: The signal name to match
            components: Optional list of components to search pin names

        Returns:
            List of matching pin references (pin-reference nets filtered out)
        """
        matches = []
        signal_upper = signal_name.upper()
        signal_normalized = signal_upper.replace('_', '')

        min_suffix_len = config.QUALITY_GATES["integration_min_suffix_len"]
        min_contains_len = config.QUALITY_GATES["integration_min_contains_len"]

        # V.3 FIX: Pre-compute stripped signal name and functional keywords
        signal_stripped = self._strip_hardware_prefixes(signal_name)
        signal_keywords = self._extract_functional_keywords(signal_name)

        for pin_ref, net in pin_net_mapping.items():
            net_upper = net.upper()
            net_normalized = net_upper.replace('_', '')

            # Strategy 1: Exact match (case-insensitive)
            if net_upper == signal_upper:
                matches.append(pin_ref)
                logger.debug(f"[INTEGRATION_AGENT] Strategy 1 (exact): '{signal_name}' == net '{net}' -> {pin_ref}")
                continue

            # Strategy 2: Normalized match (ignoring underscores)
            if net_normalized == signal_normalized:
                matches.append(pin_ref)
                logger.debug(f"[INTEGRATION_AGENT] Strategy 2 (normalized): '{signal_name}' ~= net '{net}' -> {pin_ref}")
                continue

            # Strategy 2.5 (V.3 FIX): Hardware-prefix-stripped match
            # Strip MCU-specific prefixes from both sides and compare
            net_stripped = self._strip_hardware_prefixes(net)
            if (net_stripped and signal_stripped
                    and len(net_stripped) >= 3 and len(signal_stripped) >= 3):
                net_stripped_norm = net_stripped.replace('_', '')
                signal_stripped_norm = signal_stripped.replace('_', '')
                if net_stripped_norm == signal_stripped_norm:
                    matches.append(pin_ref)
                    logger.debug(
                        f"[INTEGRATION_AGENT] Strategy 2.5 (hw-stripped): "
                        f"'{signal_name}'->'{signal_stripped}' == '{net}'->'{net_stripped}' -> {pin_ref}"
                    )
                    continue

            # Strategy 3: Suffix match — only if suffix is long enough to be meaningful
            if '_' in net:
                net_suffix = net.split('_')[-1].upper()
                if len(net_suffix) >= min_suffix_len and (net_suffix == signal_upper or net_suffix == signal_normalized):
                    matches.append(pin_ref)
                    logger.debug(f"[INTEGRATION_AGENT] Strategy 3 (suffix): '{signal_name}' matches suffix '{net_suffix}' of '{net}' -> {pin_ref}")
                    continue

            # Strategy 4: Contains match — only for long, distinctive signal names
            if len(signal_upper) >= min_contains_len and signal_upper in net_upper:
                matches.append(pin_ref)
                logger.debug(f"[INTEGRATION_AGENT] Strategy 4 (contains): '{signal_name}' in net '{net}' -> {pin_ref}")
                continue

            # Strategy 4.5 (V.3 FIX): Functional keyword matching
            # Compare functional keywords extracted from both names.
            # Requires at least 2 keyword overlap to prevent false positives.
            if signal_keywords:
                net_keywords = self._extract_functional_keywords(net)
                # Also check against functional keyword synonyms from config
                expanded_signal_kw = set(signal_keywords)
                for kw in signal_keywords:
                    synonyms = config.INTEGRATION_FUNCTIONAL_KEYWORDS.get(kw, [])
                    expanded_signal_kw.update(s.upper() for s in synonyms)
                overlap = net_keywords & expanded_signal_kw
                if len(overlap) >= 2:
                    matches.append(pin_ref)
                    logger.debug(
                        f"[INTEGRATION_AGENT] Strategy 4.5 (keywords): "
                        f"'{signal_name}' keywords {signal_keywords} overlap "
                        f"net '{net}' keywords {net_keywords} by {overlap} -> {pin_ref}"
                    )
                    continue

        # Fallback: search component pin names (exact match ONLY)
        if not matches and components:
            for comp in components:
                comp_ref = comp.get('ref', '')
                pins = comp.get('pins', [])
                for pin in pins:
                    if isinstance(pin, dict):
                        pin_name = pin.get('name', '').upper()
                        pin_num = pin.get('number', '')
                    else:
                        pin_name = str(pin).upper()
                        pin_num = str(pin)

                    pin_ref_candidate = f"{comp_ref}.{pin_num}"

                    # Exact pin name match only — no partial matching
                    if pin_name == signal_upper or pin_name == signal_normalized:
                        if pin_ref_candidate not in matches:
                            matches.append(pin_ref_candidate)
                            logger.debug(f"[INTEGRATION_AGENT] Pin-name match: '{signal_name}' == pin '{pin_name}' -> {pin_ref_candidate}")

        # Post-filter: reject any match where the NET NAME is a pin reference
        # (e.g., "U2.6", "R10.2") — these are wiring errors, not signal names.
        filtered = []
        for pin_ref in matches:
            net = pin_net_mapping.get(pin_ref, '')
            if net and self._PIN_REF_RE.match(net):
                logger.warning(f"[INTEGRATION_AGENT] REJECTED pin-reference net name '{net}' for signal '{signal_name}' at {pin_ref}")
            else:
                filtered.append(pin_ref)

        if len(filtered) < len(matches):
            logger.warning(
                f"[INTEGRATION_AGENT] Filtered {len(matches) - len(filtered)} pin-reference net(s) "
                f"for signal '{signal_name}'"
            )

        return filtered

    def _validate_interface_connections(
        self,
        interface_connections: Dict[str, str],
        interfaces: Dict,
    ) -> Dict[str, Any]:
        """
        Phase A (Forensic Fix 20260208): Validate integration quality.

        Checks:
        - Connection ratio vs interface signal count
        - Pin-reference net names in connections (ERROR — rejected)
        - Logs WARNING if below min_interface_connection_ratio threshold

        Y.2 FIX: Excludes external inputs and self-contained outputs from the
        ratio denominator (they legitimately have no cross-module connections).

        Does NOT modify interface_connections (caller decides what to do).
        """
        # Count total interface signals defined across all modules
        total_interface_signals = 0
        for module_name, iface in interfaces.items():
            total_interface_signals += len(iface.get('outputs', {}))
            total_interface_signals += len(iface.get('inputs', {}))
            total_interface_signals += len(iface.get('power_out', []))
            total_interface_signals += len(iface.get('power_in', []))

        if total_interface_signals == 0:
            logger.warning("[INTEGRATION_AGENT] No interface signals defined — nothing to validate")
            return {'passed': True, 'ratio': 1.0, 'total': 0, 'connected': 0}

        # Y.2 FIX: Exclude external inputs and self-contained outputs from ratio.
        # These are valid signals that DON'T need cross-module connections.
        external_count = getattr(self, '_external_input_count', 0)
        self_contained_count = getattr(self, '_self_contained_output_count', 0)
        adjusted_total = max(
            total_interface_signals - external_count - self_contained_count, 1
        )

        # Count unique signals that got at least one connection
        connected_nets = set(interface_connections.values())
        connection_ratio = len(connected_nets) / adjusted_total

        min_ratio = config.QUALITY_GATES["min_interface_connection_ratio"]
        passed_ratio = connection_ratio >= min_ratio

        if not passed_ratio:
            logger.warning(
                f"[INTEGRATION_AGENT] Low interface connection ratio: "
                f"{len(connected_nets)}/{adjusted_total} signals connected "
                f"({connection_ratio:.1%} < {min_ratio:.0%} threshold)"
                f"{f' [excluded {external_count} external + {self_contained_count} self-contained]' if external_count or self_contained_count else ''}"
            )
        else:
            logger.info(
                f"[INTEGRATION_AGENT] Interface connection ratio: "
                f"{len(connected_nets)}/{adjusted_total} ({connection_ratio:.1%})"
                f"{f' [excluded {external_count} external + {self_contained_count} self-contained]' if external_count or self_contained_count else ''}"
            )

        # Check for pin-reference net names in the connections
        pin_ref_count = 0
        for pin_ref, net in interface_connections.items():
            if self._PIN_REF_RE.match(net):
                logger.error(
                    f"[INTEGRATION_AGENT] Pin-reference net name detected: "
                    f"{pin_ref} -> '{net}' — this is a wiring error"
                )
                pin_ref_count += 1

        if pin_ref_count > 0:
            logger.error(
                f"[INTEGRATION_AGENT] {pin_ref_count} interface connection(s) "
                f"use pin-reference net names — these indicate broken wiring"
            )

        return {
            'passed': passed_ratio and pin_ref_count == 0,
            'ratio': connection_ratio,
            'threshold': min_ratio,
            'total_signals': total_interface_signals,
            'connected_signals': len(connected_nets),
            'pin_ref_errors': pin_ref_count
        }

    def _audit_global_net_ports(self, integrated: Dict) -> Dict[str, Any]:
        """
        W FIX: Audit global nets for physical port connections.

        Every cross-module net (SYS_* or shared global) should ideally
        connect to at least one physical port (connector, header, or test
        point) to be wireable on a real PCB.

        GENERIC: Works for any circuit topology. Uses config-driven
        component types and ref prefixes (CONNECTOR_TYPES,
        CONNECTOR_REF_PREFIXES, TESTPOINT_REF_PREFIXES).

        Does NOT auto-inject components — only flags as warnings.
        Auto-injection is fragile and masks design issues.

        Args:
            integrated: The integrated circuit dict

        Returns:
            Audit results dict with warnings
        """
        pin_net_mapping = integrated.get('pinNetMapping', {})
        components = integrated.get('components', [])

        # Build ref → component type map
        ref_type_map = {}
        for comp in components:
            ref = comp.get('ref', '')
            comp_type = (comp.get('type', '') or '').lower()
            ref_type_map[ref] = comp_type

        # Build net → pin refs map
        net_to_pins: Dict[str, List[str]] = {}
        for pin_ref, net in pin_net_mapping.items():
            if net not in net_to_pins:
                net_to_pins[net] = []
            net_to_pins[net].append(pin_ref)

        # Check global/interface nets for physical ports
        sys_prefix_upper = config.SYS_NET_PREFIX.upper()
        warnings = []

        for net, pins in net_to_pins.items():
            net_upper = net.upper()

            # Only audit cross-module/interface nets (SYS_* or global)
            is_sys_net = net_upper.startswith(sys_prefix_upper)
            is_global = self._is_global_net(net)
            if not is_sys_net and not is_global:
                continue

            # Skip power/ground nets (they don't need dedicated connectors)
            if any(x in net_upper for x in config.INTEGRATION_POWER_NET_KEYWORDS):
                continue
            if any(x in net_upper for x in config.INTEGRATION_GROUND_NET_KEYWORDS):
                continue

            # Check if any pin belongs to a physical port component
            has_physical_port = False
            for pin_ref in pins:
                comp_ref = pin_ref.split('.')[0]
                comp_type = ref_type_map.get(comp_ref, '')

                # Check by component type
                if comp_type in config.CONNECTOR_TYPES:
                    has_physical_port = True
                    break

                # Check by ref prefix (strip module prefix if present)
                comp_ref_upper = comp_ref.upper()
                base_ref = (
                    comp_ref_upper.rsplit('_', 1)[-1]
                    if '_' in comp_ref_upper
                    else comp_ref_upper
                )
                if any(base_ref.startswith(p) for p in config.CONNECTOR_REF_PREFIXES):
                    has_physical_port = True
                    break
                if any(base_ref.startswith(p) for p in config.TESTPOINT_REF_PREFIXES):
                    has_physical_port = True
                    break

            if not has_physical_port:
                warnings.append(net)
                logger.warning(
                    f"[INTEGRATION_AGENT] W audit: Global net '{net}' has no physical "
                    f"port (connector/header/test_point). Pins: {pins[:5]}"
                    f"{'...' if len(pins) > 5 else ''}"
                )

        audit_result = {
            'nets_without_ports': warnings,
            'count': len(warnings),
        }

        if warnings:
            logger.warning(
                f"[INTEGRATION_AGENT] W audit: {len(warnings)} global net(s) "
                f"without physical ports"
            )
        else:
            logger.info(
                "[INTEGRATION_AGENT] W audit: All global nets have physical ports"
            )

        return audit_result

    def _create_backplane(self, modules: List[Dict], interfaces: Dict) -> Optional[Dict]:
        """
        Create backplane circuit for inter-module connections.

        The backplane provides:
        - Power distribution (if multiple modules need power)
        - Common ground connections
        - Optional: connectors for module interfaces

        Args:
            modules: List of module circuits
            interfaces: Interface contracts

        Returns:
            Backplane circuit dict or None if not needed
        """
        # Check if backplane is needed
        if len(modules) <= 1:
            return None

        backplane = {
            'components': [],
            'pinNetMapping': {}
        }

        # Add bulk capacitors for power distribution
        bulk_caps = [
            {
                'ref': 'C_BULK1',
                'type': 'capacitor',
                'value': '100uF',
                'package': '1206',
                'description': 'Bulk power capacitor',
                'pins': [
                    {'number': '1', 'name': '1', 'type': 'passive'},
                    {'number': '2', 'name': '2', 'type': 'passive'}
                ]
            },
            {
                'ref': 'C_BULK2',
                'type': 'capacitor',
                'value': '10uF',
                'package': '0805',
                'description': 'Secondary bulk capacitor',
                'pins': [
                    {'number': '1', 'name': '1', 'type': 'passive'},
                    {'number': '2', 'name': '2', 'type': 'passive'}
                ]
            }
        ]

        backplane['components'].extend(bulk_caps)
        backplane['pinNetMapping']['C_BULK1.1'] = 'VCC'
        backplane['pinNetMapping']['C_BULK1.2'] = 'GND'
        backplane['pinNetMapping']['C_BULK2.1'] = 'VCC'
        backplane['pinNetMapping']['C_BULK2.2'] = 'GND'

        # Add test points for debugging
        test_points = [
            {
                'ref': 'TP_VCC',
                'type': 'testpoint',
                'value': 'TP',
                'package': 'TP-1MM',
                'description': 'VCC test point',
                'pins': [{'number': '1', 'name': '1', 'type': 'passive'}]
            },
            {
                'ref': 'TP_GND',
                'type': 'testpoint',
                'value': 'TP',
                'package': 'TP-1MM',
                'description': 'GND test point',
                'pins': [{'number': '1', 'name': '1', 'type': 'passive'}]
            }
        ]

        backplane['components'].extend(test_points)
        backplane['pinNetMapping']['TP_VCC.1'] = 'VCC'
        backplane['pinNetMapping']['TP_GND.1'] = 'GND'

        logger.info(f"            Created backplane with {len(backplane['components'])} components")

        return backplane

    def _validate_module_for_integration(self, module: Dict) -> List[str]:
        """
        Validate a module before integration to catch potential issues early.

        TC #95 FIX: Pre-integration validation to catch problems before they
        corrupt the integrated circuit.

        Args:
            module: Module dict to validate

        Returns:
            List of issue descriptions (empty if module is valid)
        """
        issues = []
        module_name = module.get('module_name', 'Unknown')

        # Check 1: Module name contains characters that will corrupt prefix
        if any(c in module_name for c in '.:/\\'):
            # This is now a warning, not an error, since we sanitize
            logger.debug(f"[INTEGRATION_AGENT] Module '{module_name}' contains special chars - will be sanitized")

        # Check 2: Verify components have valid references
        components = module.get('components', [])
        for comp in components:
            ref = comp.get('ref', comp.get('reference', ''))
            if '.' in ref:
                issues.append(f"Component ref '{ref}' contains period - may conflict with pin syntax")

        # Check 3: Verify pinNetMapping format
        pin_net_mapping = module.get('pinNetMapping', {})
        for pin_ref, net in pin_net_mapping.items():
            # Pin refs should have exactly one period (component.pin)
            if pin_ref.count('.') != 1:
                issues.append(f"Invalid pin ref format '{pin_ref}' - expected 'component.pin'")

        # Check 4: Check for shorted passives (LAW 4)
        shorted = self._check_module_shorted_passives(module)
        if shorted:
            issues.append(f"Found {len(shorted)} shorted passive(s) - LAW 4 violation")

        return issues

    def _check_module_shorted_passives(self, module: Dict) -> List[str]:
        """
        Check a module for shorted passive components (LAW 4 violations).

        Uses config.TWO_PIN_PASSIVE_TYPES and config.TWO_PIN_PASSIVE_PREFIXES
        as single source of truth (V.2 alignment).

        Args:
            module: Module dict to check

        Returns:
            List of shorted component references
        """
        shorted = []
        components = module.get('components', [])
        pin_net_mapping = module.get('pinNetMapping', {})

        for comp in components:
            ref = comp.get('ref', comp.get('reference', ''))
            comp_type = (comp.get('type', '') or '').lower()

            # Check if this is a two-pin passive via type or ref prefix
            is_two_pin_passive = (
                comp_type in config.TWO_PIN_PASSIVE_TYPES
                or any(ref.upper().startswith(p) for p in config.TWO_PIN_PASSIVE_PREFIXES)
            )
            if not is_two_pin_passive:
                continue

            pin1 = f"{ref}.1"
            pin2 = f"{ref}.2"
            net1 = pin_net_mapping.get(pin1)
            net2 = pin_net_mapping.get(pin2)

            if net1 and net2 and net1 == net2:
                shorted.append(ref)

        return shorted
