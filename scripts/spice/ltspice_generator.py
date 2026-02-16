#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
LTSpice Schematic Generator - Convert CopperPilot Circuits to LTSpice Format
=============================================================================

This module generates LTSpice schematic files (.asc) from CopperPilot circuit
JSON files. The output can be opened directly in LTSpice XVII/24 for visual
editing and simulation.

LTSpice .asc File Format
------------------------
The .asc format is a text-based schematic format with:
- Version header
- SHEET definition (size)
- WIRE statements (connections)
- SYMBOL statements (components with position and rotation)
- SYMATTR statements (component attributes: InstName, Value, etc.)
- FLAG statements (net labels)
- TEXT statements (comments)

Design Philosophy
-----------------
1. GENERIC: Works with ANY circuit type
2. AUTO-LAYOUT: Automatically places components in a grid
3. COMPLETE: Generates fully viewable/editable schematics
4. SIMULATION-READY: Includes default simulation commands

Author: CopperPilot Team
Date: December 2025
Version: 1.0.0
"""

import json
import math
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

from .model_library import SpiceModelLibrary, SpiceType


class Rotation(Enum):
    """LTSpice component rotation values."""
    R0 = "R0"      # 0 degrees (default)
    R90 = "R90"    # 90 degrees
    R180 = "R180"  # 180 degrees
    R270 = "R270"  # 270 degrees
    M0 = "M0"      # Mirrored
    M90 = "M90"    # Mirrored + 90
    M180 = "M180"  # Mirrored + 180
    M270 = "M270"  # Mirrored + 270


@dataclass
class LTSpiceSymbol:
    """
    Represents an LTSpice symbol placement.

    Attributes
    ----------
    symbol_name : str
        LTSpice symbol name (e.g., "res", "cap", "diode", "nmos")
    x : int
        X coordinate (LTSpice units, typically multiples of 16)
    y : int
        Y coordinate
    rotation : Rotation
        Component rotation
    inst_name : str
        Instance name (e.g., "R1", "C1")
    value : str
        Component value (e.g., "10k", "100n")
    extra_attrs : Dict[str, str]
        Additional attributes (SpiceLine, etc.)
    """
    symbol_name: str
    x: int
    y: int
    rotation: Rotation = Rotation.R0
    inst_name: str = ""
    value: str = ""
    extra_attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class LTSpiceWire:
    """
    Represents a wire segment in LTSpice.

    Attributes
    ----------
    x1, y1 : int
        Start coordinates
    x2, y2 : int
        End coordinates
    """
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass
class LTSpiceFlag:
    """
    Represents a net label (FLAG) in LTSpice.

    Attributes
    ----------
    x, y : int
        Position
    net_name : str
        Net/node name
    """
    x: int
    y: int
    net_name: str


@dataclass
class LayoutConfig:
    """
    Configuration for automatic component layout.

    Attributes
    ----------
    grid_size : int
        Base grid size (LTSpice uses 16)
    component_spacing_x : int
        Horizontal spacing between components
    component_spacing_y : int
        Vertical spacing between components
    margin_x : int
        Left margin
    margin_y : int
        Top margin
    max_columns : int
        Maximum components per row before wrapping
    """
    grid_size: int = 16
    component_spacing_x: int = 192  # 12 grid units
    component_spacing_y: int = 160  # 10 grid units
    margin_x: int = 128
    margin_y: int = 128
    max_columns: int = 8


class LTSpiceGenerator:
    """
    Generate LTSpice schematic files from CopperPilot circuit JSON.

    This class provides:
    1. Automatic component placement with grid alignment
    2. Wire routing between connected pins
    3. Net label generation
    4. Simulation command insertion
    """

    # =========================================================================
    # SYMBOL MAPPING - Maps component types to LTSpice symbols
    # =========================================================================
    SYMBOL_MAP = {
        # Passives
        'resistor': 'res',
        'capacitor': 'cap',
        'inductor': 'ind',
        'fuse': 'res',          # Fuse as resistor
        'connector': 'res',      # Connector as 0-ohm
        'jumper': 'res',

        # Diodes
        'diode': 'diode',
        'led': 'LED',
        'zener': 'zener',
        'schottky': 'schottky',
        'tvs': 'zener',

        # Transistors
        'npn': 'npn',
        'pnp': 'pnp',
        'nmos': 'nmos',
        'pmos': 'pmos',
        'jfet': 'njf',          # N-channel JFET

        # ICs - use generic symbols
        'ic': 'Opamps\\\\UniversalOpamp2',  # Generic opamp as fallback
        'opamp': 'Opamps\\\\UniversalOpamp2',
        'comparator': 'Comparators\\\\LT1011',
        'regulator': 'Misc\\\\cell',  # Generic cell as placeholder

        # Sources
        'voltage_source': 'voltage',
        'current_source': 'current',
    }

    # Pin offsets for common LTSpice symbols (relative to symbol origin)
    # Format: symbol_name -> [(pin_num, x_offset, y_offset), ...]
    PIN_OFFSETS = {
        'res': [('1', 0, -32), ('2', 0, 32)],           # Vertical resistor
        'cap': [('1', 0, -16), ('2', 0, 16)],           # Vertical capacitor
        'ind': [('1', 0, -32), ('2', 0, 32)],           # Vertical inductor
        'diode': [('A', 0, -32), ('K', 0, 32)],         # Anode top, Cathode bottom
        'LED': [('A', 0, -32), ('K', 0, 32)],
        'zener': [('A', 0, -32), ('K', 0, 32)],
        'schottky': [('A', 0, -32), ('K', 0, 32)],
        'npn': [('C', 16, -32), ('B', -32, 0), ('E', 16, 32)],
        'pnp': [('C', 16, 32), ('B', -32, 0), ('E', 16, -32)],
        'nmos': [('D', 16, -32), ('G', -48, 0), ('S', 16, 32)],
        'pmos': [('D', 16, 32), ('G', -48, 0), ('S', 16, -32)],
        'voltage': [('p', 0, -32), ('n', 0, 32)],
        'current': [('p', 0, -32), ('n', 0, 32)],
    }

    def __init__(self, layout_config: Optional[LayoutConfig] = None):
        """
        Initialize the LTSpice generator.

        Parameters
        ----------
        layout_config : Optional[LayoutConfig]
            Layout configuration. Uses defaults if not provided.
        """
        self.config = layout_config or LayoutConfig()
        self.model_library = SpiceModelLibrary()

        # State for current schematic
        self._symbols: List[LTSpiceSymbol] = []
        self._wires: List[LTSpiceWire] = []
        self._flags: List[LTSpiceFlag] = []
        self._texts: List[Tuple[int, int, str]] = []

        # Component placement tracking
        self._component_positions: Dict[str, Tuple[int, int]] = {}
        self._component_symbols: Dict[str, str] = {}
        self._pin_positions: Dict[str, Tuple[int, int]] = {}

    def convert(self, input_path: str, output_path: str) -> bool:
        """
        Convert a circuit JSON file to LTSpice schematic.

        Parameters
        ----------
        input_path : str
            Path to CopperPilot circuit JSON file
        output_path : str
            Path for output .asc file

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
            module_name = circuit.get('moduleName', 'Unknown_Circuit')

            # Generate schematic
            schematic = self.generate_schematic(circuit, module_name)

            # Write output
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(schematic, encoding='utf-8')

            return True

        except Exception as e:
            print(f"Error converting {input_path}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def generate_schematic(self, circuit: Dict[str, Any], title: str = "Circuit") -> str:
        """
        Generate complete LTSpice schematic from circuit data.

        Parameters
        ----------
        circuit : Dict[str, Any]
            Circuit data from CopperPilot JSON
        title : str
            Circuit title

        Returns
        -------
        str
            Complete LTSpice .asc file content
        """
        # Reset state
        self._symbols = []
        self._wires = []
        self._flags = []
        self._texts = []
        self._component_positions = {}
        self._component_symbols = {}
        self._pin_positions = {}

        components = circuit.get('components', [])
        connections = circuit.get('connections', [])
        pin_net_mapping = circuit.get('pinNetMapping', {})

        # 1. Place components
        self._place_components(components)

        # 2. Calculate pin positions
        self._calculate_pin_positions(components)

        # 3. Route wires for connections
        self._route_connections(connections, pin_net_mapping)

        # 4. Add net labels (flags) for important nets
        self._add_net_labels(connections)

        # 5. Add title and info text
        self._add_title_text(title, len(components), len(connections))

        # 6. Generate output
        return self._generate_asc_content(title)

    def _place_components(self, components: List[Dict]) -> None:
        """
        Automatically place components in a grid layout.

        Components are organized by type:
        - Power components (regulators, etc.) at top
        - ICs in the middle
        - Passives at bottom

        Parameters
        ----------
        components : List[Dict]
            List of component definitions
        """
        cfg = self.config

        # Group components by category
        power_comps = []
        ic_comps = []
        passive_comps = []
        other_comps = []

        for comp in components:
            comp_type = comp.get('type', '').lower()
            comp_value = comp.get('value', '').upper()

            # Categorize
            if 'regulator' in comp_type or 'LM78' in comp_value or 'LM79' in comp_value or 'AMS' in comp_value:
                power_comps.append(comp)
            elif comp_type == 'ic' or comp_type == 'opamp':
                ic_comps.append(comp)
            elif comp_type in ('resistor', 'capacitor', 'inductor', 'diode', 'led'):
                passive_comps.append(comp)
            else:
                other_comps.append(comp)

        # Place each category
        current_y = cfg.margin_y

        # Power section
        if power_comps:
            current_y = self._place_component_row(power_comps, current_y, "Power")
            current_y += cfg.component_spacing_y // 2

        # IC section
        if ic_comps:
            current_y = self._place_component_row(ic_comps, current_y, "ICs")
            current_y += cfg.component_spacing_y // 2

        # Passive section
        if passive_comps:
            current_y = self._place_component_row(passive_comps, current_y, "Passives")
            current_y += cfg.component_spacing_y // 2

        # Other components
        if other_comps:
            current_y = self._place_component_row(other_comps, current_y, "Other")

    def _place_component_row(
        self,
        components: List[Dict],
        start_y: int,
        category: str
    ) -> int:
        """
        Place a row of components.

        Parameters
        ----------
        components : List[Dict]
            Components to place
        start_y : int
            Starting Y coordinate
        category : str
            Category name for section label

        Returns
        -------
        int
            Y coordinate after placing all components
        """
        cfg = self.config
        current_x = cfg.margin_x
        current_y = start_y
        max_y = start_y
        col = 0

        for comp in components:
            ref = comp.get('ref', 'X')
            comp_type = comp.get('type', '').lower()
            value = comp.get('value', '')

            # Get symbol
            symbol_name = self._get_symbol_name(comp_type, value)

            # Check for row wrap
            if col >= cfg.max_columns:
                current_x = cfg.margin_x
                current_y += cfg.component_spacing_y
                col = 0

            # Store position
            self._component_positions[ref] = (current_x, current_y)
            self._component_symbols[ref] = symbol_name

            # Create symbol
            symbol = LTSpiceSymbol(
                symbol_name=symbol_name,
                x=current_x,
                y=current_y,
                rotation=Rotation.R0,
                inst_name=ref,
                value=value,
            )
            self._symbols.append(symbol)

            # Update position
            current_x += cfg.component_spacing_x
            max_y = max(max_y, current_y)
            col += 1

        return max_y + cfg.component_spacing_y

    def _get_symbol_name(self, comp_type: str, value: str) -> str:
        """
        Get LTSpice symbol name for a component.

        Parameters
        ----------
        comp_type : str
            Component type
        value : str
            Component value/part number

        Returns
        -------
        str
            LTSpice symbol name
        """
        comp_type_lower = comp_type.lower()
        value_upper = value.upper()

        # Check direct mapping
        if comp_type_lower in self.SYMBOL_MAP:
            return self.SYMBOL_MAP[comp_type_lower]

        # Check for specific parts
        if 'LM78' in value_upper or 'LM79' in value_upper or 'AMS' in value_upper:
            return 'Misc\\\\cell'  # Voltage regulator

        if 'TL07' in value_upper or 'LM358' in value_upper or 'NE5532' in value_upper:
            return 'Opamps\\\\opamp2'

        # Fallback
        return 'res'  # Default to resistor symbol

    def _calculate_pin_positions(self, components: List[Dict]) -> None:
        """
        Calculate absolute pin positions for all components.

        Parameters
        ----------
        components : List[Dict]
            Component definitions
        """
        for comp in components:
            ref = comp.get('ref', '')
            pins = comp.get('pins', [])
            symbol = self._component_symbols.get(ref, 'res')
            pos = self._component_positions.get(ref, (0, 0))

            # Get pin offsets for this symbol
            pin_offsets = self.PIN_OFFSETS.get(symbol, [])

            for i, pin in enumerate(pins):
                pin_num = pin.get('number', pin.get('name', str(i + 1)))
                pin_key = f"{ref}.{pin_num}"

                # Find offset for this pin
                offset_x, offset_y = 0, 0

                for offset_pin, ox, oy in pin_offsets:
                    if str(offset_pin) == str(pin_num) or offset_pin == pin.get('name', ''):
                        offset_x, offset_y = ox, oy
                        break
                else:
                    # Default: stack pins vertically
                    offset_y = -32 + i * 32

                self._pin_positions[pin_key] = (pos[0] + offset_x, pos[1] + offset_y)

    def _route_connections(
        self,
        connections: List[Dict],
        pin_net_mapping: Dict[str, str]
    ) -> None:
        """
        Route wires between connected pins.

        Uses a simple star topology: connect all pins to a central bus point.

        Parameters
        ----------
        connections : List[Dict]
            Connection definitions with net and points
        pin_net_mapping : Dict[str, str]
            Pin to net mapping
        """
        for conn in connections:
            net_name = conn.get('net', '')
            points = conn.get('points', [])

            if len(points) < 2:
                continue

            # Skip NC nets
            if net_name.upper().startswith('NC_'):
                continue

            # Get positions of all pins in this net
            pin_positions = []
            for point in points:
                if point in self._pin_positions:
                    pin_positions.append(self._pin_positions[point])

            if len(pin_positions) < 2:
                continue

            # Calculate center point for star routing
            avg_x = sum(p[0] for p in pin_positions) // len(pin_positions)
            avg_y = sum(p[1] for p in pin_positions) // len(pin_positions)

            # Snap to grid
            grid = self.config.grid_size
            avg_x = (avg_x // grid) * grid
            avg_y = (avg_y // grid) * grid

            # Route from each pin to center (Manhattan routing)
            for px, py in pin_positions:
                # Horizontal then vertical
                if px != avg_x:
                    self._wires.append(LTSpiceWire(px, py, avg_x, py))
                if py != avg_y:
                    self._wires.append(LTSpiceWire(avg_x, py, avg_x, avg_y))

    def _add_net_labels(self, connections: List[Dict]) -> None:
        """
        Add net labels (FLAGS) for important nets.

        Labels are added for:
        - Power rails (VCC, GND, etc.)
        - Named signals (not generic NET_xx)

        Parameters
        ----------
        connections : List[Dict]
            Connection definitions
        """
        important_patterns = [
            r'^V[CD][CD]',      # VCC, VDD
            r'^GND',           # Ground
            r'^V_',            # V_5V, V_3V3, etc.
            r'^IN',            # Input signals
            r'^OUT',           # Output signals
            r'^CLK',           # Clock signals
            r'^RST',           # Reset signals
        ]

        for conn in connections:
            net_name = conn.get('net', '')
            points = conn.get('points', [])

            # Check if this is an important net
            is_important = any(re.match(pat, net_name.upper()) for pat in important_patterns)

            # Skip generic NET_xx names unless they're power
            if net_name.startswith('NET_') and not is_important:
                continue

            if not points:
                continue

            # Find a pin position for the label
            for point in points:
                if point in self._pin_positions:
                    px, py = self._pin_positions[point]
                    self._flags.append(LTSpiceFlag(px, py, net_name))
                    break

    def _add_title_text(self, title: str, num_components: int, num_connections: int) -> None:
        """Add title and info text to the schematic."""
        self._texts.append((
            self.config.margin_x,
            32,
            f"{title} - Generated by CopperPilot"
        ))
        self._texts.append((
            self.config.margin_x,
            64,
            f"Components: {num_components}, Nets: {num_connections}"
        ))

    def _generate_asc_content(self, title: str) -> str:
        """
        Generate the complete .asc file content.

        Parameters
        ----------
        title : str
            Schematic title

        Returns
        -------
        str
            Complete .asc file content
        """
        lines = []

        # Header
        lines.append("Version 4")
        lines.append("SHEET 1 2000 1500")

        # Wires
        for wire in self._wires:
            lines.append(f"WIRE {wire.x1} {wire.y1} {wire.x2} {wire.y2}")

        # Flags (net labels)
        for flag in self._flags:
            lines.append(f"FLAG {flag.x} {flag.y} {flag.net_name}")

        # Symbols
        for symbol in self._symbols:
            lines.append(f"SYMBOL {symbol.symbol_name} {symbol.x} {symbol.y} {symbol.rotation.value}")
            lines.append(f"SYMATTR InstName {symbol.inst_name}")
            if symbol.value:
                lines.append(f"SYMATTR Value {symbol.value}")
            for attr_name, attr_value in symbol.extra_attrs.items():
                lines.append(f"SYMATTR {attr_name} {attr_value}")

        # Text annotations
        for x, y, text in self._texts:
            # Escape special characters
            safe_text = text.replace('\\', '\\\\').replace('\n', '\\n')
            lines.append(f"TEXT {x} {y} Left 2 !; {safe_text}")

        # Default simulation command (as comment)
        sim_x = self.config.margin_x
        sim_y = 96
        lines.append(f"TEXT {sim_x} {sim_y} Left 2 !.tran 0 10m 0 1u")

        return '\n'.join(lines)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def convert_to_ltspice(input_path: str, output_path: str) -> bool:
    """
    Convenience function to convert circuit JSON to LTSpice schematic.

    Parameters
    ----------
    input_path : str
        Path to CopperPilot circuit JSON
    output_path : str
        Path for output .asc file

    Returns
    -------
    bool
        True if conversion successful
    """
    generator = LTSpiceGenerator()
    return generator.convert(input_path, output_path)
