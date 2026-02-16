#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
SPICE Netlist Generator - Convert CopperPilot Circuits to SPICE Format
=======================================================================

This module generates standard SPICE netlist files (.cir) from CopperPilot
circuit JSON files. The output is compatible with:
- ngspice (open-source)
- LTSpice (requires minor syntax adjustments)
- HSPICE, PSpice, and other SPICE variants

Design Philosophy
-----------------
1. GENERIC: Works with ANY circuit type
2. COMPLETE: Generates self-contained netlists with all required models
3. SIMULATABLE: Includes default analysis commands for immediate simulation
4. WELL-DOCUMENTED: Output includes comments explaining the circuit

SPICE Netlist Format
--------------------
* Title line (first line)
* Comments and metadata
* Component declarations
* .model statements
* .subckt definitions
* Analysis commands (.tran, .ac, .dc)
* .end

Author: CopperPilot Team
Date: December 2025
Version: 1.0.0
"""

import json
import re
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from server.config import config

from .model_library import SpiceModelLibrary, SpiceType, ComponentModel
from .spice_utils import spice_safe_name


@dataclass
class NetlistConfig:
    """
    Configuration options for SPICE netlist generation.

    Attributes
    ----------
    include_comments : bool
        Include descriptive comments in output
    include_analysis : bool
        Include default analysis commands
    ground_net_name : str
        Name of the ground net (will be mapped to node 0)
    default_tran_stop : str
        Default transient analysis stop time
    default_tran_step : str
        Default transient analysis step time
    default_ac_points : int
        Number of points per decade for AC analysis
    default_ac_start : str
        AC analysis start frequency
    default_ac_stop : str
        AC analysis stop frequency
    """
    include_comments: bool = True
    include_analysis: bool = True
    ground_net_name: str = "GND"
    default_tran_stop: str = "10m"
    default_tran_step: str = "1u"
    default_ac_points: int = 100
    default_ac_start: str = "1"
    default_ac_stop: str = "10MEG"


class SpiceNetlistGenerator:
    """
    Generate SPICE netlist files from CopperPilot circuit JSON.

    This class provides a complete conversion pipeline:
    1. Load circuit JSON
    2. Build net-to-node mapping
    3. Generate component statements
    4. Add required model definitions
    5. Add analysis commands
    6. Write complete netlist

    The generator is GENERIC and works with any circuit complexity,
    from simple RC filters to complex multi-stage amplifiers.
    """

    def __init__(self, config: Optional[NetlistConfig] = None):
        """
        Initialize the netlist generator.

        Parameters
        ----------
        config : Optional[NetlistConfig]
            Configuration options. Uses defaults if not provided.
        """
        self.config = config or NetlistConfig()
        self.model_library = SpiceModelLibrary()
        self._net_to_node: Dict[str, str] = {}
        self._node_counter: int = 1
        self._required_models: Set[str] = set()
        # N.4 FIX: Dict keyed by subcircuit name prevents duplicate definitions
        # when the same connector type appears multiple times with different pin names.
        self._required_subcircuits: Dict[str, str] = {}

    def convert(self, input_path: str, output_path: str) -> bool:
        """
        Convert a circuit JSON file to SPICE netlist.

        Parameters
        ----------
        input_path : str
            Path to CopperPilot circuit JSON file
        output_path : str
            Path for output .cir file

        Returns
        -------
        bool
            True if conversion successful
        """
        try:
            # Load circuit data
            with open(input_path, 'r') as f:
                data = json.load(f)

            circuit = data.get('circuit', data)
            # Fix K.15: Try multiple keys for circuit name
            module_name = (
                circuit.get('moduleName')
                or circuit.get('circuitName')
                or circuit.get('module_name')
                or data.get('moduleName')
                or data.get('circuitName')
                or Path(input_path).stem
                or 'Unknown_Circuit'
            )

            # Generate netlist
            netlist = self.generate_netlist(circuit, module_name)

            # Write output
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(netlist, encoding='utf-8')

            return True

        except Exception as e:
            print(f"Error converting {input_path}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def generate_netlist(self, circuit: Dict[str, Any], title: str = "Circuit") -> str:
        """
        Generate complete SPICE netlist from circuit data.

        This is the main generation method that orchestrates all steps
        of netlist creation.

        Parameters
        ----------
        circuit : Dict[str, Any]
            Circuit data from CopperPilot JSON
        title : str
            Circuit title for netlist header

        Returns
        -------
        str
            Complete SPICE netlist
        """
        # Reset state for new circuit
        self._net_to_node = {}
        self._node_counter = 1
        self._required_models = set()
        self._required_subcircuits = {}
        # Q.8 FIX: Track nets driven by subcircuit output pins to prevent
        # auto-generating external voltage sources that would create loops.
        self._subcircuit_driven_nets = set()

        components = circuit.get('components', [])
        connections = circuit.get('connections', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})
        nets = circuit.get('nets', [])

        # Build net-to-node mapping (GND = 0, others = 1, 2, 3, ...)
        self._build_net_mapping(nets, connections)

        # Generate sections
        sections = []

        # 1. Title line (required - first line of netlist)
        clean_title = re.sub(r'[^\w\s\-_]', '', title)
        sections.append(f"* {clean_title}")
        sections.append("")

        # 2. Header comments
        if self.config.include_comments:
            sections.append(self._generate_header_comments(circuit, title))

        # 3. Component statements
        sections.append(self._generate_component_statements(components, pin_net_mapping))

        # 4. Model definitions
        models_section = self._generate_model_definitions(components)
        if models_section:
            sections.append(models_section)

        # 5. Power sources (auto-detect VCC/VDD nets and add sources)
        power_sources = self._generate_power_sources(nets)
        if power_sources:
            sections.append(power_sources)

        # 6. Analysis commands
        if self.config.include_analysis:
            sections.append(self._generate_analysis_commands())

        # 7. End statement
        sections.append("\n.end")

        netlist_text = '\n'.join(sections)

        # M.11 FIX: Pre-validate syntax before returning
        if config.SPICE_VALIDATE_SYNTAX:
            self._validate_netlist_syntax(netlist_text)

        return netlist_text

    def _build_net_mapping(self, nets: List, connections: List[Dict]) -> None:
        """
        Build mapping from net names to SPICE node numbers.

        SPICE requires numeric node names (or alphanumeric in some variants).
        Ground must be node 0.

        Fix 4.1: Ensures GND is ALWAYS node 0 and power rails are NEVER node 0.
        Previously, if GND wasn't found first, a power rail could become node 0.

        Fix 4.2: Sanitizes net names to be SPICE-compatible:
        - Removes R suffix from resistor values (620R → 620)
        - Replaces spaces with underscores
        - Ensures SPICE-valid node identifiers

        Parameters
        ----------
        nets : List
            List of net names (strings) or net dicts with 'name' key
        connections : List[Dict]
            List of connection definitions
        """
        # Collect all unique net names
        all_nets = set()
        for net in nets:
            if isinstance(net, str):
                all_nets.add(net)
            elif isinstance(net, dict) and 'name' in net:
                all_nets.add(net['name'])
        for conn in connections:
            net_name = conn.get('net', '')
            if net_name:
                all_nets.add(net_name)

        # Phase E (Forensic Fix 20260208): Ground pattern matching overhauled.
        # Uses structured exact/prefix/suffix matching from config instead of
        # substring matching.  The old '0' in net_upper bug caused any net
        # containing the digit 0 (e.g., "+180V_DC", "ADC_CH0") to be mapped
        # to GND (node 0).
        gnd_cfg = config.SPICE_GROUND_PATTERNS
        gnd_exact = {p.upper() for p in gnd_cfg["exact"]}
        gnd_prefixes = [p.upper() for p in gnd_cfg["prefixes"]]
        gnd_suffixes = [s.upper() for s in gnd_cfg["suffixes"]]
        spice_logger = logging.getLogger(__name__)

        ground_found = False
        for net in all_nets:
            net_upper = net.upper()
            is_ground = False

            # Exact match
            if net_upper in gnd_exact:
                is_ground = True
            # Prefix match
            elif any(net_upper.startswith(pfx) for pfx in gnd_prefixes):
                is_ground = True
            # Suffix match
            elif any(net_upper.endswith(sfx) for sfx in gnd_suffixes):
                is_ground = True

            if is_ground:
                self._net_to_node[net] = '0'
                ground_found = True

        # Fallback: check SPICE config ground_net_name
        if not ground_found:
            for net in all_nets:
                if net.upper() == self.config.ground_net_name.upper():
                    self._net_to_node[net] = '0'
                    ground_found = True
                    break

        # If STILL no ground, create an implicit ground
        if not ground_found:
            self._net_to_node['GND'] = '0'

        # Map remaining nets to sequential node numbers (never 0)
        for net in sorted(all_nets):
            if net and net not in self._net_to_node:
                if net.upper().startswith('NC_') or net.upper() == 'NC':
                    continue
                self._net_to_node[net] = str(self._node_counter)
                self._node_counter += 1

        # Phase E safety check: verify no power rail is mapped to node 0
        # Fix I.1: Use local power rail detection instead of importing from
        # workflow.circuit_supervisor (which triggers ModuleNotFoundError in
        # subprocess context due to utils.logger import chain).
        for net, node in list(self._net_to_node.items()):
            if node == '0' and self._is_power_rail_local(net) and net.upper() not in gnd_exact:
                new_node = str(self._node_counter)
                self._node_counter += 1
                self._net_to_node[net] = new_node
                spice_logger.error(
                    f"Phase E: Power rail '{net}' was incorrectly mapped to node 0 (GND). "
                    f"Reassigned to node {new_node}."
                )

    @staticmethod
    def _is_power_rail_local(net_name: str) -> bool:
        """
        Fix I.1: Local power rail detection using config patterns.

        Replaces the import of _is_power_rail from workflow.circuit_supervisor
        which fails in subprocess context due to utils.logger import chain.

        All pattern data comes from config (single source of truth):
          config.POWER_RAIL_PREFIXES  — prefix strings
          config.POWER_RAIL_EXACT     — exact-match set
          config.POWER_RAIL_PATTERNS  — regex patterns
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

    @staticmethod
    def _sanitize_spice_name(name: str) -> str:
        """
        Sanitize a name for SPICE compatibility.

        V.4 FIX: Delegates to the canonical spice_safe_name() in scripts.spice,
        ensuring identical output as model_library.py's subcircuit definitions.
        Previously used \\w regex (which matches Unicode in Python 3), causing
        mismatches with model_library's ASCII-only regex — e.g., 200kOhm vs 200k_.
        """
        return spice_safe_name(name)

    @staticmethod
    def _sanitize_spice_value(value: str) -> str:
        """
        Fix 4.2: Sanitize component values for SPICE.

        - 620R → 620 (SPICE doesn't understand R suffix)
        - 3.0V → 3.3V is NOT touched (this is a design issue, not conversion)
        """
        # Remove R suffix used in some resistor notations
        return re.sub(r'(\d+)[Rr](\b)', r'\1\2', value)

    def _get_node(self, net_name: str) -> str:
        """
        Get SPICE node number for a net name.

        Parameters
        ----------
        net_name : str
            Net name from circuit

        Returns
        -------
        str
            SPICE node number/name
        """
        if not net_name:
            return '0'  # Unconnected → ground (safer than floating)

        # NC pins get unique high-impedance nodes
        if net_name.upper().startswith('NC_') or net_name.upper() == 'NC':
            nc_node = f"NC_{self._node_counter}"
            self._node_counter += 1
            return nc_node

        # Phase E (Forensic Fix 20260208): Never default unmapped nets to node 0.
        # If a net was not mapped during _build_net_mapping, assign a NEW
        # sequential node instead of silently grounding it.
        node = self._net_to_node.get(net_name)
        if node is None:
            new_node = str(self._node_counter)
            self._node_counter += 1
            self._net_to_node[net_name] = new_node
            logging.getLogger(__name__).warning(
                f"Phase E: Net '{net_name}' not in net mapping — assigned new node {new_node}"
            )
            return new_node
        return node

    def _resolve_pin_to_canonical(self, pin_name: str, spice_type_key: str) -> Optional[str]:
        """
        Fix L.2: Resolve an AI-generated pin name to its canonical SPICE name.

        Uses config.SPICE_PIN_NAME_ALIASES to match common pin name variants
        (e.g., "DRAIN" → "D", "GATE" → "G", "COLLECTOR" → "C").

        Parameters
        ----------
        pin_name : str
            Pin name from the AI-generated component (e.g., "DRAIN", "G", "1")
        spice_type_key : str
            Key into config.SPICE_PIN_NAME_ALIASES (e.g., "MOSFET", "BJT", "DIODE")

        Returns
        -------
        Optional[str]
            Canonical SPICE pin name (e.g., "D", "G", "S", "B") or None if no match
        """
        aliases = config.SPICE_PIN_NAME_ALIASES.get(spice_type_key, {})
        pin_upper = pin_name.upper().strip()

        for canonical, alias_list in aliases.items():
            # Direct match to canonical name
            if pin_upper == canonical:
                return canonical
            # Match against alias list
            if pin_upper in (a.upper() for a in alias_list):
                return canonical

        return None

    def _reorder_nodes_to_spice_order(
        self,
        component: Dict,
        nodes: List[str],
        model: 'ComponentModel',
        spice_type_key: str,
    ) -> List[str]:
        """
        Fix L.2: Reorder component nodes from AI-generated pin order to
        SPICE-required pin order.

        The AI generates pins in arbitrary order (e.g., G, D, S for a MOSFET).
        SPICE requires a specific order (D, G, S, B for MOSFET; C, B, E for BJT;
        A, K for diode). This method maps each pin name to its canonical SPICE
        name using config-driven aliases, then reorders the nodes accordingly.

        Falls back to position-based ordering when pin names cannot be resolved.

        Parameters
        ----------
        component : Dict
            The component dict with 'pins' list
        nodes : List[str]
            Node numbers in the original (AI-generated) pin order
        model : ComponentModel
            The SPICE model with pin_order defining the required output order
        spice_type_key : str
            Key into config.SPICE_PIN_NAME_ALIASES (e.g., "MOSFET", "BJT")

        Returns
        -------
        List[str]
            Nodes reordered to match SPICE-required pin order
        """
        pins = component.get('pins', [])
        canonical_order = model.pin_order  # e.g., ['D', 'G', 'S', 'B']

        if not canonical_order or not pins:
            return nodes

        # Step 1: Build mapping from canonical pin name → node
        canonical_to_node: Dict[str, str] = {}
        used_indices: set = set()

        for i, pin in enumerate(pins):
            if i >= len(nodes):
                break
            pin_name = pin.get('name', pin.get('number', str(i + 1)))
            canonical = self._resolve_pin_to_canonical(pin_name, spice_type_key)
            if canonical and canonical not in canonical_to_node:
                canonical_to_node[canonical] = nodes[i]
                used_indices.add(i)

        # Step 2: Check if we resolved enough pins to reorder
        matched_count = sum(1 for c in canonical_order if c in canonical_to_node)

        if matched_count < 2:
            # Not enough pin names matched — try positional fallback.
            # If the component has exactly the right number of pins for this
            # type, assume they're in the standard datasheet order (pin 1, 2, 3).
            # This is a last-resort heuristic but better than outputting random order.
            spice_logger = logging.getLogger(__name__)
            spice_logger.warning(
                f"Fix L.2: Component '{component.get('ref', '?')}' — only "
                f"{matched_count}/{len(canonical_order)} pins resolved by name. "
                f"Using positional fallback."
            )
            return nodes

        # Step 3: Build reordered node list following canonical SPICE order
        reordered = []
        unmatched_nodes = [
            nodes[i] for i in range(len(nodes)) if i not in used_indices
        ]
        unmatched_idx = 0

        for canonical_pin in canonical_order:
            if canonical_pin in canonical_to_node:
                reordered.append(canonical_to_node[canonical_pin])
            else:
                # Pin not found in component — use next unmatched node, or
                # for Body pin on MOSFET, default to Source node
                if canonical_pin == 'B' and 'S' in canonical_to_node:
                    reordered.append(canonical_to_node['S'])
                elif unmatched_idx < len(unmatched_nodes):
                    reordered.append(unmatched_nodes[unmatched_idx])
                    unmatched_idx += 1
                else:
                    reordered.append('0')  # Ground as last resort

        return reordered

    def _generate_header_comments(self, circuit: Dict, title: str) -> str:
        """Generate descriptive header comments for the netlist."""
        lines = [
            "* " + "=" * 70,
            f"* SPICE Netlist: {title}",
            f"* Generated by CopperPilot SPICE Converter",
            f"* Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "* " + "=" * 70,
            "*",
            f"* Components: {len(circuit.get('components', []))}",
            f"* Nets: {len(circuit.get('nets', []))}",
            f"* Connections: {len(circuit.get('connections', []))}",
            "*",
            "* Net-to-Node Mapping:",
        ]

        # Add net mapping (limit to first 20 for readability)
        for i, (net, node) in enumerate(sorted(self._net_to_node.items())):
            if i >= 20:
                remaining = len(self._net_to_node) - 20
                lines.append(f"*   ... and {remaining} more nets")
                break
            lines.append(f"*   {net} = node {node}")

        lines.append("*")
        lines.append("")

        return '\n'.join(lines)

    def _generate_component_statements(
        self,
        components: List[Dict],
        pin_net_mapping: Dict[str, str]
    ) -> str:
        """
        Generate SPICE component statements.

        Each component is converted to its SPICE equivalent:
        - R<name> <n+> <n-> <value>
        - C<name> <n+> <n-> <value>
        - D<name> <n+> <n-> <model>
        - Q<name> <nc> <nb> <ne> <model>
        - X<name> <nodes...> <subckt>

        Parameters
        ----------
        components : List[Dict]
            List of component definitions
        pin_net_mapping : Dict[str, str]
            Mapping from pin (ref.pin) to net name

        Returns
        -------
        str
            SPICE component statements
        """
        lines = ["* " + "-" * 50, "* Component Statements", "* " + "-" * 50]

        # Group by type for organization
        by_type: Dict[str, List[str]] = {}

        for comp in components:
            ref = comp.get('ref', 'X')
            model = self.model_library.get_model(comp)
            spice_type = model.spice_type

            # Get node connections for this component
            pins = comp.get('pins', [])
            nodes = []

            for pin in pins:
                pin_num = pin.get('number', pin.get('name', '1'))
                pin_key = f"{ref}.{pin_num}"
                net_name = pin_net_mapping.get(pin_key, '')
                node = self._get_node(net_name)
                nodes.append(node)

                # Q.8 FIX: If this is a subcircuit output pin, record the net
                # as "driven by subcircuit" so the power source generator skips it.
                if spice_type == SpiceType.SUBCIRCUIT and net_name:
                    pin_name_upper = pin.get('name', '').upper()
                    if pin_name_upper in config.SPICE_SUBCIRCUIT_OUTPUT_PIN_NAMES:
                        self._subcircuit_driven_nets.add(net_name)

            # Generate statement based on type
            statement = self._format_component_statement(ref, model, nodes, comp)

            # Organize by type
            type_key = spice_type.value
            if type_key not in by_type:
                by_type[type_key] = []
            by_type[type_key].append(statement)

            # Track required models (N.4: dedup subcircuits by name, not content)
            if model.model_definition:
                if model.spice_type == SpiceType.SUBCIRCUIT:
                    subckt_name = model.model_name or 'UNKNOWN'
                    if subckt_name not in self._required_subcircuits:
                        self._required_subcircuits[subckt_name] = model.model_definition
                else:
                    self._required_models.add(model.model_definition)

        # Output grouped by type
        type_labels = {
            'R': 'Resistors',
            'C': 'Capacitors',
            'L': 'Inductors',
            'D': 'Diodes',
            'Q': 'Transistors (BJT)',
            'M': 'MOSFETs',
            'X': 'Subcircuits (ICs)',
            'V': 'Voltage Sources',
            'I': 'Current Sources',
        }

        for type_key in ['R', 'C', 'L', 'D', 'Q', 'M', 'X', 'V', 'I']:
            if type_key in by_type:
                label = type_labels.get(type_key, type_key)
                lines.append(f"\n* {label}")
                lines.extend(by_type[type_key])

        return '\n'.join(lines)

    def _format_component_statement(
        self,
        ref: str,
        model: ComponentModel,
        nodes: List[str],
        component: Dict
    ) -> str:
        """
        Format a single component statement.

        Parameters
        ----------
        ref : str
            Component reference designator
        model : ComponentModel
            SPICE model for the component
        nodes : List[str]
            Node numbers for each pin
        component : Dict
            Original component data

        Returns
        -------
        str
            Formatted SPICE statement
        """
        spice_prefix = model.spice_type.value
        # Fix 4.2: Sanitize value for SPICE compatibility (e.g., 620R → 620)
        value = self._sanitize_spice_value(component.get('value', ''))

        # Ensure we have at least 2 nodes for 2-terminal devices
        while len(nodes) < model.num_terminals:
            nodes.append('0')  # Default unconnected pins to ground

        if model.spice_type in (SpiceType.RESISTOR, SpiceType.CAPACITOR, SpiceType.INDUCTOR):
            # R/C/L: prefix + ref + n+ + n- + value
            # T.4 FIX: If the model has a pre-computed value (e.g., thermistor
            # modeled as resistor at nominal resistance, ferrite bead as
            # impedance), use that instead of re-parsing the raw component value.
            if model.default_params and 'value' in model.default_params:
                spice_value = str(model.default_params['value'])
            else:
                _, spice_value = self.model_library.parse_value(value, model.spice_type.name.lower())

            # Handle fuse/connector as small resistance
            comp_type = component.get('type', '').lower()
            if comp_type in ('fuse', 'connector', 'jumper', 'header', 'terminal'):
                spice_value = '0.001'  # 1mΩ

            # Ensure prefix matches ref or add it
            if ref[0].upper() != spice_prefix:
                spice_ref = f"{spice_prefix}{ref}"
            else:
                spice_ref = ref

            return f"{spice_ref} {nodes[0]} {nodes[1]} {spice_value}"

        elif model.spice_type == SpiceType.DIODE:
            # D: D + ref + n_anode + n_cathode + model
            # Fix L.2: Reorder pins from AI order to SPICE order (A, K)
            nodes = self._reorder_nodes_to_spice_order(
                component, nodes, model, 'DIODE'
            )
            if ref[0].upper() != 'D':
                spice_ref = f"D{ref}"
            else:
                spice_ref = ref
            return f"{spice_ref} {nodes[0]} {nodes[1]} {model.model_name}"

        elif model.spice_type == SpiceType.BJT:
            # Q: Q + ref + nc + nb + ne + model
            # Fix L.2: Reorder pins from AI order to SPICE order (C, B, E)
            nodes = self._reorder_nodes_to_spice_order(
                component, nodes, model, 'BJT'
            )
            if ref[0].upper() != 'Q':
                spice_ref = f"Q{ref}"
            else:
                spice_ref = ref
            # Ensure 3 nodes: C, B, E
            while len(nodes) < 3:
                nodes.append('0')
            return f"{spice_ref} {nodes[0]} {nodes[1]} {nodes[2]} {model.model_name}"

        elif model.spice_type == SpiceType.MOSFET:
            # M: M + ref + nd + ng + ns + nb + model
            # Fix L.2: Reorder pins from AI order to SPICE order (D, G, S, B)
            nodes = self._reorder_nodes_to_spice_order(
                component, nodes, model, 'MOSFET'
            )
            if ref[0].upper() != 'M':
                spice_ref = f"M{ref}"
            else:
                spice_ref = ref
            # Ensure 4 nodes: D, G, S, B (body often connected to source)
            while len(nodes) < 4:
                nodes.append(nodes[2] if len(nodes) > 2 else '0')  # Body to source
            return f"{spice_ref} {nodes[0]} {nodes[1]} {nodes[2]} {nodes[3]} {model.model_name}"

        elif model.spice_type == SpiceType.SUBCIRCUIT:
            # X: X + ref + nodes... + subckt_name
            if ref[0].upper() != 'X':
                spice_ref = f"X{ref}"
            else:
                spice_ref = ref
            nodes_str = ' '.join(nodes)
            # Fix 4.2: Sanitize subcircuit name (spaces → underscores)
            safe_model = self._sanitize_spice_name(model.model_name)
            return f"{spice_ref} {nodes_str} {safe_model}"

        else:
            # Generic fallback
            nodes_str = ' '.join(nodes[:2])
            return f"* Unknown: {ref} {nodes_str} {value}"

    def _generate_model_definitions(self, components: List[Dict]) -> str:
        """
        Generate .model and .subckt definitions for all components.

        Parameters
        ----------
        components : List[Dict]
            List of component definitions

        Returns
        -------
        str
            Model and subcircuit definitions
        """
        lines = []

        if self._required_models:
            lines.append("\n* " + "-" * 50)
            lines.append("* Device Models")
            lines.append("* " + "-" * 50)
            for model_def in sorted(self._required_models):
                lines.append(model_def)

        if self._required_subcircuits:
            lines.append("\n* " + "-" * 50)
            lines.append("* Subcircuit Definitions")
            lines.append("* " + "-" * 50)
            for name in sorted(self._required_subcircuits):
                lines.append(self._required_subcircuits[name])

        return '\n'.join(lines) if lines else ""

    def _generate_power_sources(self, nets: List) -> str:
        """
        Auto-generate power sources for detected power rails.

        This scans net names for common power rail patterns and adds
        appropriate voltage sources.

        Parameters
        ----------
        nets : List
            List of net names (strings or dicts with 'name' key)

        Returns
        -------
        str
            Voltage source definitions
        """
        lines = ["\n* " + "-" * 50, "* Power Sources (Auto-Generated)", "* " + "-" * 50]
        sources_added = 0

        # Power rail patterns from config (single source of truth)
        power_patterns = config.SPICE_POWER_SOURCE_PATTERNS

        # Fix K.8: Track already-added sources to avoid duplicates
        added_nets = set()

        for net_item in nets:
            # Handle both string and dict formats
            if isinstance(net_item, str):
                net = net_item
            elif isinstance(net_item, dict) and 'name' in net_item:
                net = net_item['name']
            else:
                continue

            # Q.8 FIX: Skip nets driven by subcircuit output pins to prevent
            # voltage source loops (two ideal sources on same node = singular matrix).
            if net in self._subcircuit_driven_nets:
                continue

            # Fix K.8: Strip leading +/- (common convention: +12V, +5V, -15V)
            # and replace dots with V for xVy notation (3.3V → 3V3V)
            net_stripped = net.upper().lstrip('+-')
            net_upper = net_stripped.replace('.', 'V')

            # Detect negative rail from original net name prefix
            is_negative = net.lstrip().startswith('-') or net.lstrip().startswith('MINUS')

            for pattern, default_voltage in power_patterns:
                match = re.match(pattern, net_upper)
                if match:
                    # Determine voltage
                    if default_voltage is not None:
                        voltage = default_voltage
                    else:
                        # Extract from pattern
                        groups = match.groups()
                        if groups:
                            try:
                                # Handle patterns like "3V3" → 3.3
                                voltage_str = groups[0]
                                if len(groups) > 1 and groups[1]:
                                    voltage_str += '.' + groups[1]
                                voltage = float(voltage_str)
                            except ValueError:
                                continue
                        else:
                            continue

                    # Check for negative rail (from name or prefix)
                    if is_negative or 'MINUS' in net_upper or 'NEG' in net_upper:
                        voltage = -abs(voltage)

                    # Get node number
                    node = self._get_node(net)

                    # Avoid duplicate sources for the same net
                    if node in added_nets:
                        break
                    added_nets.add(node)

                    # Create voltage source
                    source_name = f"V_{re.sub(r'[^A-Za-z0-9_]', '_', net)}"
                    lines.append(f"{source_name} {node} 0 DC {voltage}")
                    sources_added += 1
                    break

        # T.3 FIX: Secondary detection pass — check nets that weren't matched
        # by SPICE_POWER_SOURCE_PATTERNS against POWER_RAIL_PATTERNS.
        # If a net is recognized as a power rail, try to extract voltage
        # from its name using VOLTAGE_EXTRACTION_PATTERN.
        if sources_added == 0:
            power_rail_patterns = config.POWER_RAIL_PATTERNS
            voltage_rx = re.compile(config.VOLTAGE_EXTRACTION_PATTERN)
            # Also check for xVy notation (3V3 → 3.3)
            xvy_rx = re.compile(config.VOLTAGE_XVY_PATTERN) if hasattr(config, 'VOLTAGE_XVY_PATTERN') else None

            for net_item in nets:
                if isinstance(net_item, str):
                    net = net_item
                elif isinstance(net_item, dict) and 'name' in net_item:
                    net = net_item['name']
                else:
                    continue

                if net in self._subcircuit_driven_nets:
                    continue

                net_upper = net.upper().lstrip('+-')
                node = self._get_node(net)
                if node in added_nets or node == '0':
                    continue

                # Check against power rail classification patterns
                is_power_rail = any(
                    re.search(p, net_upper) for p in power_rail_patterns
                )
                if not is_power_rail:
                    continue

                # Try to extract voltage from net name
                voltage = None
                if xvy_rx:
                    xvy_match = xvy_rx.search(net_upper)
                    if xvy_match:
                        try:
                            voltage = float(xvy_match.group(1) + '.' + xvy_match.group(2))
                        except (ValueError, IndexError):
                            pass
                if voltage is None:
                    v_match = voltage_rx.search(net_upper)
                    if v_match:
                        try:
                            voltage = float(v_match.group(1))
                        except ValueError:
                            pass

                if voltage is None:
                    voltage = config.SPICE_DEFAULT_POWER_SOURCE_VOLTAGE

                is_negative = net.lstrip().startswith('-') or 'MINUS' in net_upper or 'NEG' in net_upper
                if is_negative:
                    voltage = -abs(voltage)

                added_nets.add(node)
                source_name = f"V_{re.sub(r'[^A-Za-z0-9_]', '_', net)}"
                lines.append(f"{source_name} {node} 0 DC {voltage}")
                sources_added += 1

        if sources_added == 0:
            lines.append("* WARNING: No power rails auto-detected")
            lines.append("* Add voltage sources manually for simulation:")
            lines.append("* Example: VCC net_vcc 0 DC 5")

        return '\n'.join(lines)

    def _generate_analysis_commands(self) -> str:
        """
        Generate default analysis commands.

        Includes:
        - .tran for time-domain simulation
        - .ac for frequency response
        - .op for DC operating point

        Returns
        -------
        str
            Analysis command section
        """
        cfg = self.config

        lines = [
            "\n* " + "-" * 50,
            "* Analysis Commands",
            "* " + "-" * 50,
            "* Uncomment the analysis type you need:",
            "",
            "* DC Operating Point",
            ".op",
            "",
            "* Transient Analysis",
            f"* .tran 0 {cfg.default_tran_stop} 0 {cfg.default_tran_step}",
            "",
            "* AC Analysis (frequency sweep)",
            f"* .ac dec {cfg.default_ac_points} {cfg.default_ac_start} {cfg.default_ac_stop}",
            "",
            "* DC Sweep (example: sweep VIN from 0 to 10V)",
            "* .dc VIN 0 10 0.1",
            "",
            "* Control commands for ngspice",
            ".control",
            "run",
            "* plot v(node1) v(node2)",
            ".endc",
        ]

        return '\n'.join(lines)

    def _validate_netlist_syntax(self, netlist_text: str) -> None:
        """
        M.11 FIX: Pre-validate generated netlist for common ngspice syntax errors.

        Checks for:
        1. '&' operator in B-source lines (invalid in ngspice; must use nested ternary)
        2. 'pulse()' inside B-source expressions (only valid in standalone V/I sources)
        3. Subcircuit instance vs definition pin count mismatches

        Logs warnings for any issues found. Does NOT modify the netlist.
        """
        spice_logger = logging.getLogger(__name__)
        lines = netlist_text.split('\n')

        # Track subcircuit definitions for pin count validation
        subckt_pin_counts = {}  # name → pin_count

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip comments and empty lines
            if not stripped or stripped.startswith('*'):
                continue

            upper = stripped.upper()

            # Check 1: B-source with '&' operator
            if upper.startswith('B') and '=' in stripped:
                # This is a B-source behavioral expression
                expr_part = stripped.split('=', 1)[1] if '=' in stripped else ''
                if '&' in expr_part:
                    spice_logger.warning(
                        f"M.11: Line {line_num}: B-source uses '&' operator "
                        f"(invalid in ngspice — use nested ternary): {stripped[:80]}"
                    )

                # Check 2: pulse() inside B-source
                if 'PULSE(' in expr_part.upper():
                    spice_logger.warning(
                        f"M.11: Line {line_num}: B-source uses pulse() "
                        f"(invalid inside B-source — only valid in standalone V/I): {stripped[:80]}"
                    )

            # Track .subckt definitions for pin count check
            if upper.startswith('.SUBCKT '):
                parts = stripped.split()
                if len(parts) >= 2:
                    subckt_name = parts[1]
                    # Pin names are everything after the name until end or a param
                    pin_names = [p for p in parts[2:] if not p.startswith('.') and '=' not in p]
                    subckt_pin_counts[subckt_name.upper()] = len(pin_names)

            # Check 3: Subcircuit instance pin count
            if upper.startswith('X'):
                parts = stripped.split()
                if len(parts) >= 2:
                    # Last token is the subcircuit name
                    subckt_ref = parts[-1].upper()
                    instance_pins = parts[1:-1]  # Everything between instance name and subckt name

                    expected = subckt_pin_counts.get(subckt_ref)
                    if expected is not None and len(instance_pins) != expected:
                        spice_logger.warning(
                            f"M.11: Line {line_num}: Subcircuit instance '{parts[0]}' "
                            f"has {len(instance_pins)} pins but '{subckt_ref}' expects "
                            f"{expected} pins: {stripped[:80]}"
                        )


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def convert_to_spice(input_path: str, output_path: str) -> bool:
    """
    Convenience function to convert circuit JSON to SPICE netlist.

    Parameters
    ----------
    input_path : str
        Path to CopperPilot circuit JSON
    output_path : str
        Path for output .cir file

    Returns
    -------
    bool
        True if conversion successful
    """
    generator = SpiceNetlistGenerator()
    return generator.convert(input_path, output_path)
