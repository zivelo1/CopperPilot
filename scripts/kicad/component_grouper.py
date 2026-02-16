#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
GENERIC Component Grouper - Groups components by function for professional PCB layout

This module analyzes circuit components and groups them by function:
- Power supply components (voltage regulators, capacitors, inductors)
- Signal processing (op-amps, filters, ADCs, DACs)
- Digital logic (microcontrollers, logic gates, memory)
- I/O and connectivity (connectors, headers, terminals)
- Passive support (decoupling caps, pull-ups/downs, termination)

GENERIC: Works for ANY circuit type by analyzing component types, values, and connectivity.

Author: Claude Code / CopperPilot AI System
Date: 2025-11-18
Version: 1.0 - Phase 3 implementation
"""

from __future__ import annotations
import logging
from typing import Dict, List, Set, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class ComponentGrouper:
    """
    GENERIC component grouping for professional PCB layout.

    Analyzes circuit topology and component types to create functional groups
    that should be placed together for optimal routing and signal integrity.
    """

    def __init__(self):
        """Initialize component grouper."""
        # Component type keywords for classification
        self.power_keywords = [
            'regulator', 'ldo', 'vreg', 'power', 'supply', 'inductor', 'l_',
            'converter', 'buck', 'boost', 'charge', 'battery'
        ]

        self.digital_keywords = [
            'mcu', 'micro', 'cpu', 'fpga', 'logic', 'gate', 'flip',
            'counter', 'shift', 'buffer', 'driver', 'memory', 'flash',
            'eeprom', 'sram', 'crystal', 'oscillator', 'clock'
        ]

        self.analog_keywords = [
            'opamp', 'op-amp', 'amplifier', 'amp', 'comparator', 'adc',
            'dac', 'filter', 'analog', 'sensor', 'transducer', 'dds',
            'pga', 'vga', 'mixer', 'detector'
        ]

        self.io_keywords = [
            'connector', 'header', 'terminal', 'jack', 'socket', 'port',
            'usb', 'uart', 'spi', 'i2c', 'interface', 'button', 'switch',
            'led', 'display', 'relay'
        ]

    def group_components(self, components: List[Dict], circuit: Dict) -> Dict[str, List[Dict]]:
        """
        Group components by function (GENERIC for all circuits).

        Args:
            components: List of component dictionaries
            circuit: Circuit data (for net analysis)

        Returns:
            Dictionary mapping group names to component lists:
            {
                'power': [...],
                'digital_core': [...],
                'analog_signal': [...],
                'io_interface': [...],
                'passive_support': [...]
            }
        """
        groups = {
            'power': [],
            'digital_core': [],
            'analog_signal': [],
            'io_interface': [],
            'passive_support': []
        }

        # STEP 1: Classify each component by type
        for comp in components:
            group = self._classify_component(comp)
            groups[group].append(comp)

        # STEP 2: Refine passive classification based on connectivity
        # Move passives close to the ICs they support
        groups = self._refine_passive_placement(groups, circuit)

        logger.info(f"📦 Component grouping:")
        for group_name, group_comps in groups.items():
            if group_comps:
                logger.info(f"   ├─ {group_name}: {len(group_comps)} components")

        return groups

    def _classify_component(self, comp: Dict) -> str:
        """
        Classify single component into functional group (GENERIC).

        Args:
            comp: Component dictionary with 'ref', 'type', 'value', 'footprint'

        Returns:
            Group name string
        """
        ref = comp.get('ref', '').lower()
        comp_type = comp.get('type', '').lower()
        value = comp.get('value', '').lower()
        footprint = comp.get('footprint', '').lower()

        # Combine all text for keyword matching
        search_text = f"{ref} {comp_type} {value} {footprint}"

        # Priority order: Power > Digital > Analog > I/O > Passive

        # Check for power components
        if any(kw in search_text for kw in self.power_keywords):
            return 'power'

        # Check for digital components
        if any(kw in search_text for kw in self.digital_keywords):
            return 'digital_core'

        # Check for analog components
        if any(kw in search_text for kw in self.analog_keywords):
            return 'analog_signal'

        # Check for I/O components
        if any(kw in search_text for kw in self.io_keywords):
            return 'io_interface'

        # Default: passive support (resistors, capacitors not classified above)
        return 'passive_support'

    def _refine_passive_placement(self, groups: Dict[str, List[Dict]],
                                   circuit: Dict) -> Dict[str, List[Dict]]:
        """
        Refine passive component grouping based on connectivity (GENERIC).

        Moves passives from 'passive_support' to the group of the IC they primarily support.

        Args:
            groups: Initial component groups
            circuit: Circuit data with net information

        Returns:
            Refined component groups
        """
        # Get passive components
        passives = groups['passive_support']
        if not passives:
            return groups

        # Build connectivity map: component ref -> set of connected component refs
        connectivity = self._build_connectivity_map(circuit)

        # For each passive, find which IC it's most connected to
        refined_passives = []
        for passive in passives:
            passive_ref = passive.get('ref', '')
            connected_refs = connectivity.get(passive_ref, set())

            # Find which group the passive is most connected to
            group_scores = defaultdict(int)
            for other_ref in connected_refs:
                # Find which group this connected component belongs to
                for group_name, group_comps in groups.items():
                    if group_name == 'passive_support':
                        continue
                    if any(c.get('ref') == other_ref for c in group_comps):
                        group_scores[group_name] += 1
                        break

            # Assign to group with highest score
            if group_scores:
                best_group = max(group_scores.items(), key=lambda x: x[1])[0]
                groups[best_group].append(passive)
            else:
                # No strong connection, keep in passive_support
                refined_passives.append(passive)

        # Update passive_support with only unassigned passives
        groups['passive_support'] = refined_passives

        return groups

    def _build_connectivity_map(self, circuit: Dict) -> Dict[str, Set[str]]:
        """
        Build connectivity map from circuit netlist (GENERIC).

        Args:
            circuit: Circuit data with connections

        Returns:
            Dictionary mapping component ref -> set of connected component refs
        """
        connectivity = defaultdict(set)

        # Lowlevel format has 'connections' list with {net, points} structure
        connections = circuit.get('connections', [])
        for conn_data in connections:
            # Each connection has 'points' which are "COMP.PIN" strings
            points = conn_data.get('points', []) if isinstance(conn_data, dict) else []

            # Extract component refs from connection points
            comp_refs = set()
            for point in points:
                # Connection format: "COMP.PIN"
                comp_ref = point.split('.')[0] if '.' in point else point
                comp_refs.add(comp_ref)

            # Each component is connected to all others on this net
            for comp_ref in comp_refs:
                connectivity[comp_ref].update(comp_refs - {comp_ref})

        return dict(connectivity)


# GENERIC helper function
def group_components_by_function(components: List[Dict], circuit: Dict) -> Dict[str, List[Dict]]:
    """
    One-function interface for component grouping (GENERIC).

    Args:
        components: List of component dictionaries
        circuit: Circuit data

    Returns:
        Dictionary mapping group names to component lists
    """
    grouper = ComponentGrouper()
    return grouper.group_components(components, circuit)
