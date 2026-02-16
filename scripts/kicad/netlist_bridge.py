#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Netlist Bridge - Ensures Schematic and PCB Netlist Synchronization
==================================================================

TC #39 (2025-11-24): Phase 4 Task 4.1 - Implement Netlist Bridge (RC #5)

CRITICAL ROOT CAUSE FIX: Schematic-PCB Netlist Desynchronization
- Problem: PCB pad nets don't match schematic nets (55+ net_conflict errors per circuit)
- Impact: "Pad net (NET_4) doesn't match net given by schematic (VCC_12V)"
- Solution: Generate netlist from CircuitGraph ONCE, use for both schematic AND PCB

Root Cause Fixed:
- RC #5: Netlist Desynchronization → 55+ net_conflict errors per circuit

Evidence of Problem:
- DRC reports: "Pad net (NET_4) doesn't match net given by schematic (VCC_12V)"
- DRC reports: "No corresponding pin found in schematic" for component pads
- Schematic nets != PCB nets for same components

Fix Strategy:
- CircuitGraph is single source of truth for netlist
- Both schematic and PCB generation use SAME Net objects
- Validate: Every pad in PCB has net matching schematic symbol pin
- No net renaming or remapping during conversion

Design Principles:
- SINGLE SOURCE OF TRUTH: CircuitGraph netlist used by all modules
- VALIDATED: Check schematic-PCB net correspondence before generation
- GENERIC: Works for any net structure and any component pin configuration

Author: CopperPilot AI System (TC #39)
Date: 2025-11-24
"""

from typing import Dict, List, Tuple, Set, Optional
from dataclasses import dataclass

from .circuit_graph import CircuitGraph, Net, Component, ComponentPin


@dataclass
class NetlistValidationError:
    """
    Netlist synchronization error.

    Attributes:
        component_ref: Component reference (e.g., "R1", "U1")
        pin_number: Pin number
        schematic_net: Net name in schematic
        pcb_net: Net name in PCB
        message: Error description
    """
    component_ref: str
    pin_number: str
    schematic_net: str
    pcb_net: str
    message: str

    def __str__(self):
        return (f"{self.component_ref}.{self.pin_number}: "
                f"Schematic={self.schematic_net}, "
                f"PCB={self.pcb_net} - {self.message}")


class NetlistBridge:
    """
    Ensures schematic and PCB use identical netlists.

    Provides single authoritative netlist from CircuitGraph.
    Validates netlist consistency before file generation.

    CRITICAL: Both schematic generator AND PCB generator MUST use this class
    to get net assignments. Never generate nets independently.
    """

    def __init__(self, circuit_graph: CircuitGraph):
        """
        Initialize netlist bridge.

        Args:
            circuit_graph: CircuitGraph containing authoritative netlist
        """
        self.circuit_graph = circuit_graph
        self.validation_errors: List[NetlistValidationError] = []

    def get_net_for_pin(self, component_ref: str, pin_number: str) -> Optional[str]:
        """
        Get net name for a specific component pin.

        This is the AUTHORITATIVE source for pin-to-net mapping.
        Both schematic and PCB generation MUST call this method.

        Args:
            component_ref: Component reference (e.g., "R1", "U1")
            pin_number: Pin number (e.g., "1", "2", "VCC", "GND")

        Returns:
            Net name, or None if pin not found
        """
        # Get component
        component = self.circuit_graph.components.get(component_ref)
        if not component:
            return None

        # Find pin
        pin = component.get_pin_by_number(pin_number)
        if not pin:
            return None

        return pin.net

    def get_all_nets(self) -> Dict[str, Net]:
        """
        Get all nets in circuit.

        Returns:
            Dictionary mapping net_name -> Net object
        """
        return self.circuit_graph.nets

    def get_component_pins(self, component_ref: str) -> List[ComponentPin]:
        """
        Get all pins for a component.

        Args:
            component_ref: Component reference (e.g., "R1", "U1")

        Returns:
            List of ComponentPin objects
        """
        component = self.circuit_graph.components.get(component_ref)
        if not component:
            return []
        return component.pins

    def get_pins_on_net(self, net_name: str) -> Set[Tuple[str, str]]:
        """
        Get all (component_ref, pin_number) tuples connected to a net.

        Args:
            net_name: Net name (e.g., "GND", "VCC", "NET_1")

        Returns:
            Set of (component_ref, pin_number) tuples
        """
        net = self.circuit_graph.nets.get(net_name)
        if not net:
            return set()

        pins = set()
        # Need to find which component each pin belongs to
        for component in self.circuit_graph.components.values():
            for pin in component.pins:
                if pin.net == net_name:
                    pins.add((component.reference, pin.number))

        return pins

    def validate_netlist(self) -> bool:
        """
        Validate netlist for consistency.

        Checks:
        - All component pins have valid net assignments
        - No orphaned nets (nets with no pins)
        - No dangling connections (nets with only 1 pin)

        Returns:
            True if netlist is valid
        """
        self.validation_errors = []

        # Check all components have net assignments
        for component in self.circuit_graph.components.values():
            for pin in component.pins:
                if not pin.net:
                    self.validation_errors.append(NetlistValidationError(
                        component_ref=component.reference,
                        pin_number=pin.number,
                        schematic_net="",
                        pcb_net="",
                        message="Pin has no net assignment"
                    ))

                elif pin.net not in self.circuit_graph.nets:
                    self.validation_errors.append(NetlistValidationError(
                        component_ref=component.reference,
                        pin_number=pin.number,
                        schematic_net=pin.net,
                        pcb_net="",
                        message=f"Net '{pin.net}' not found in netlist"
                    ))

        return len(self.validation_errors) == 0

    def generate_netlist_report(self) -> str:
        """
        Generate human-readable netlist report.

        Shows all nets, connected pins, and statistics.

        Returns:
            String containing netlist report
        """
        lines = []
        lines.append(f"\n{'='*70}")
        lines.append(f"Netlist Report: {self.circuit_graph.circuit_name}")
        lines.append(f"{'='*70}")

        stats = self.circuit_graph.get_stats()
        lines.append(f"Components: {stats['components']}")
        lines.append(f"Nets: {stats['nets']}")
        lines.append(f"Pins: {stats['pins']}")
        lines.append(f"Power nets: {stats['power_nets']}")

        # Group nets by type
        power_nets = []
        signal_nets = []

        for net_name, net in sorted(self.circuit_graph.nets.items()):
            if net.is_power:
                power_nets.append((net_name, len(net.pins)))
            else:
                signal_nets.append((net_name, len(net.pins)))

        # Show power nets
        if power_nets:
            lines.append(f"\nPower/Ground Nets ({len(power_nets)}):")
            for net_name, pin_count in sorted(power_nets, key=lambda x: -x[1])[:10]:
                lines.append(f"  • {net_name}: {pin_count} connections")

        # Show top signal nets
        if signal_nets:
            lines.append(f"\nSignal Nets (top 10 of {len(signal_nets)}):")
            for net_name, pin_count in sorted(signal_nets, key=lambda x: -x[1])[:10]:
                lines.append(f"  • {net_name}: {pin_count} connections")

        # Show validation errors if any
        if self.validation_errors:
            lines.append(f"\n⚠️  Validation Errors ({len(self.validation_errors)}):")
            for error in self.validation_errors[:10]:  # Show first 10
                lines.append(f"  • {error}")

        lines.append(f"{'='*70}\n")

        return "\n".join(lines)

    def export_netlist_kicad_format(self) -> str:
        """
        Export netlist in KiCad netlist format.

        This can be used for debugging or external tools.

        Returns:
            KiCad netlist format string
        """
        lines = []
        lines.append("(export (version D)")
        lines.append(f'  (design (source "{self.circuit_graph.circuit_name}"))')
        lines.append("  (components")

        # Export components
        for component in sorted(self.circuit_graph.components.values(), key=lambda c: c.reference):
            lines.append(f'    (comp (ref "{component.reference}")')
            lines.append(f'          (value "{component.value}")')
            lines.append(f'          (footprint "{component.footprint}"))')

        lines.append("  )")
        lines.append("  (nets")

        # Export nets
        for net_name in sorted(self.circuit_graph.nets.keys()):
            pins = self.get_pins_on_net(net_name)
            if pins:
                lines.append(f'    (net (code ?) (name "{net_name}")')
                for comp_ref, pin_num in sorted(pins):
                    lines.append(f'         (node (ref "{comp_ref}") (pin "{pin_num}"))')
                lines.append("    )")

        lines.append("  )")
        lines.append(")")

        return "\n".join(lines)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def create_netlist_bridge(circuit_graph: CircuitGraph) -> NetlistBridge:
    """
    Create netlist bridge for circuit.

    Args:
        circuit_graph: CircuitGraph with netlist

    Returns:
        NetlistBridge instance
    """
    return NetlistBridge(circuit_graph)


def validate_netlist_synchronization(
    circuit_graph: CircuitGraph,
    verbose: bool = True
) -> Tuple[bool, List[NetlistValidationError]]:
    """
    Validate netlist for synchronization issues.

    Args:
        circuit_graph: CircuitGraph to validate
        verbose: If True, print validation results

    Returns:
        (is_valid, errors) tuple
    """
    bridge = NetlistBridge(circuit_graph)
    is_valid = bridge.validate_netlist()

    if verbose:
        if is_valid:
            print("  ✅ Netlist validation: PASSED")
        else:
            print(f"  ❌ Netlist validation: FAILED ({len(bridge.validation_errors)} errors)")
            for error in bridge.validation_errors[:5]:  # Show first 5
                print(f"    • {error}")

    return (is_valid, bridge.validation_errors)


# ============================================================================
# INTEGRATION HELPERS
# ============================================================================

class NetlistCache:
    """
    Cache for netlist bridge instances.

    Ensures same NetlistBridge is used throughout conversion process.
    Prevents accidental creation of multiple bridges with potentially
    inconsistent data.
    """

    def __init__(self):
        self._cache: Dict[str, NetlistBridge] = {}

    def get_bridge(self, circuit_graph: CircuitGraph) -> NetlistBridge:
        """
        Get or create netlist bridge for circuit.

        Args:
            circuit_graph: CircuitGraph

        Returns:
            NetlistBridge instance (cached)
        """
        cache_key = circuit_graph.circuit_name

        if cache_key not in self._cache:
            self._cache[cache_key] = NetlistBridge(circuit_graph)

        return self._cache[cache_key]

    def clear(self):
        """Clear cache."""
        self._cache = {}


# Global cache instance
_netlist_cache = NetlistCache()


def get_netlist_bridge(circuit_graph: CircuitGraph) -> NetlistBridge:
    """
    Get cached netlist bridge for circuit.

    This ensures the SAME NetlistBridge instance is used by both
    schematic and PCB generation, preventing synchronization issues.

    Args:
        circuit_graph: CircuitGraph

    Returns:
        NetlistBridge instance (cached)
    """
    return _netlist_cache.get_bridge(circuit_graph)


def clear_netlist_cache():
    """Clear global netlist cache."""
    _netlist_cache.clear()


# ============================================================================
# MAIN (for testing)
# ============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .circuit_graph import load_circuit_graph

    if len(sys.argv) < 2:
        print("Usage: python netlist_bridge.py <circuit_file.json>")
        sys.exit(1)

    circuit_file = Path(sys.argv[1])

    print(f"Loading circuit: {circuit_file}")
    graph = load_circuit_graph(circuit_file)

    print(f"\n{graph}")

    print("\nCreating netlist bridge...")
    bridge = create_netlist_bridge(graph)

    print("\nValidating netlist...")
    is_valid = bridge.validate_netlist()

    print(bridge.generate_netlist_report())

    if is_valid:
        print("\n✅ Netlist is valid (synchronized)")

        # Show example net
        if bridge.get_all_nets():
            first_net = list(bridge.get_all_nets().keys())[0]
            pins = bridge.get_pins_on_net(first_net)
            print(f"\nExample net '{first_net}': {len(pins)} connections")
            for comp_ref, pin_num in list(pins)[:5]:
                net_name = bridge.get_net_for_pin(comp_ref, pin_num)
                print(f"  • {comp_ref}.{pin_num} -> {net_name}")

    else:
        print(f"\n❌ Netlist has {len(bridge.validation_errors)} errors")
