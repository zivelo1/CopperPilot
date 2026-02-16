#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
CircuitGraph - Single Source of Truth for Circuit Data
======================================================

TC #39 (2025-11-24): Phase 0 - Foundation Data Model
CRITICAL: All circuit data flows through this class before generation.

Purpose:
- Parse lowlevel JSON into validated circuit graph
- Provide single authoritative representation of circuit
- Enable pre-flight validation before file generation
- Support GENERIC circuit topologies (any component, any net structure)

Design Principles:
- GENERIC: Works for any circuit type (simple LED to complex MCU systems)
- MODULAR: Independent, reusable data structure
- DYNAMIC: Adapts to circuit complexity automatically
- VALIDATED: Fail-fast on invalid input data

Root Causes Fixed:
- RC #1: Provides foundation for component annotation
- RC #5: Enables netlist synchronization between schematic and PCB
- RC #7: Pre-flight validation prevents broken output

Author: CopperPilot AI System (TC #39)
Date: 2025-11-24
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Tuple, Any
from pathlib import Path
import json
from collections import defaultdict


@dataclass
class ComponentPin:
    """
    Represents a single pin on a component.

    Attributes:
        number: Pin number/identifier (e.g., "1", "2", "A1", "VCC")
        name: Pin function name (e.g., "GND", "VCC", "OUT", "IN+")
        net: Net name this pin connects to
        position: (x, y) position relative to component origin
        pin_type: Pin electrical type (input, output, bidirectional, power, etc.)
    """
    number: str
    name: str
    net: str
    position: Tuple[float, float] = (0.0, 0.0)
    pin_type: str = "passive"

    def __hash__(self):
        """Make ComponentPin hashable for use in sets."""
        return hash((self.number, self.name, self.net))


@dataclass
class Component:
    """
    Represents a circuit component with all its properties.

    Attributes:
        reference: Unique component reference (e.g., "R1", "C1", "U1")
        reference_prefix: Reference designator prefix (e.g., "R", "C", "U")
        component_type: Component type (e.g., "resistor", "capacitor", "IC")
        value: Component value (e.g., "10k", "100nF", "LM358")
        footprint: KiCad footprint identifier
        pins: List of ComponentPin objects
        position: (x, y) position on board
        rotation: Rotation angle in degrees (0, 90, 180, 270)
        properties: Additional component properties
        original_data: Original JSON data for reference
    """
    reference: str  # e.g., "R1", "C2", "U1"
    reference_prefix: str  # e.g., "R", "C", "U"
    component_type: str  # e.g., "resistor", "capacitor"
    value: str  # e.g., "10k", "100nF"
    footprint: str  # KiCad footprint
    pins: List[ComponentPin] = field(default_factory=list)
    position: Tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    properties: Dict[str, Any] = field(default_factory=dict)
    original_data: Dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        """Make Component hashable for use in sets."""
        return hash(self.reference)

    def get_pin_by_number(self, pin_number: str) -> Optional[ComponentPin]:
        """Get pin by its number."""
        for pin in self.pins:
            if pin.number == pin_number:
                return pin
        return None

    def get_pins_on_net(self, net_name: str) -> List[ComponentPin]:
        """Get all pins connected to a specific net."""
        return [pin for pin in self.pins if pin.net == net_name]


@dataclass
class Net:
    """
    Represents an electrical net (connection) in the circuit.

    Attributes:
        name: Net name (e.g., "GND", "VCC", "NET_1")
        pins: Set of ComponentPin objects connected to this net
        net_class: Net class for DRC rules ("Default", "Power", etc.)
        is_power: True if this is a power/ground net
    """
    name: str
    pins: Set[ComponentPin] = field(default_factory=set)
    net_class: str = "Default"
    is_power: bool = False

    def add_pin(self, pin: ComponentPin):
        """Add a pin to this net."""
        self.pins.add(pin)

    def get_components(self) -> Set[str]:
        """Get unique component references connected to this net."""
        # Extract component reference from pin's parent
        # Note: We'll need to track this in CircuitGraph
        return set()  # Placeholder - will be populated by CircuitGraph

    def is_connected(self) -> bool:
        """Check if net has at least 2 connected pins (valid connection)."""
        return len(self.pins) >= 2

    def is_dangling(self) -> bool:
        """Check if net has only 1 pin (dangling connection - error)."""
        return len(self.pins) == 1

    def is_empty(self) -> bool:
        """Check if net has no pins (empty net - warning)."""
        return len(self.pins) == 0


@dataclass
class ValidationError:
    """
    Represents a validation error found in the circuit.

    Attributes:
        severity: Error severity ("CRITICAL", "ERROR", "WARNING")
        category: Error category (e.g., "ANNOTATION", "NETLIST", "COMPONENT")
        message: Human-readable error message
        location: Location in circuit (component ref, net name, etc.)
        fix_suggestion: Suggested fix for the error
    """
    severity: str  # "CRITICAL", "ERROR", "WARNING"
    category: str  # "ANNOTATION", "NETLIST", "COMPONENT", "FOOTPRINT"
    message: str
    location: str = ""
    fix_suggestion: str = ""

    def __str__(self):
        loc_str = f" [{self.location}]" if self.location else ""
        return f"{self.severity}: {self.category}{loc_str}: {self.message}"


class CircuitGraph:
    """
    Single source of truth for circuit data.

    Parses lowlevel JSON and builds validated graph representation.
    All circuit generation operations use this as authoritative data source.

    Attributes:
        circuit_name: Circuit module name
        components: Dictionary mapping reference -> Component
        nets: Dictionary mapping net_name -> Net
        validation_errors: List of ValidationError objects
        metadata: Additional circuit metadata
    """

    def __init__(self, circuit_data: Dict[str, Any], circuit_name: str = ""):
        """
        Initialize CircuitGraph from lowlevel JSON data.

        Args:
            circuit_data: Circuit dictionary from CIRCUIT_*.json
            circuit_name: Optional circuit name override
        """
        self.circuit_name = circuit_name or circuit_data.get('moduleName', 'unknown')
        self.components: Dict[str, Component] = {}
        self.nets: Dict[str, Net] = {}
        self.validation_errors: List[ValidationError] = []
        self.metadata: Dict[str, Any] = {}

        # Store original data for reference
        self.original_data = circuit_data

        # Parse circuit data
        self._parse_components(circuit_data)
        self._parse_nets(circuit_data)
        self._build_net_to_component_mapping()

    def _parse_components(self, circuit_data: Dict[str, Any]):
        """
        Parse components from circuit data.

        Extracts all components and their pins, creating Component objects.
        Handles unannotated components (R?, C?, etc.) - annotation happens later.
        """
        components_data = circuit_data.get('components', [])

        for comp_data in components_data:
            # Extract component properties
            comp_type = comp_data.get('type', 'unknown')
            comp_value = comp_data.get('value', '')
            footprint = comp_data.get('footprint', '')

            # Extract reference (may be unannotated like "R?", "C?")
            # Annotation will be fixed in Phase 1
            # Lowlevel JSON uses 'ref' not 'reference'
            reference = comp_data.get('ref', comp_data.get('reference', 'U?'))

            # Determine reference prefix (R, C, U, etc.)
            if reference and reference[0].isalpha():
                reference_prefix = reference.rstrip('0123456789?')
            else:
                # Infer from component type if reference missing
                reference_prefix = self._infer_reference_prefix(comp_type)
                reference = f"{reference_prefix}?"

            # Create Component object
            component = Component(
                reference=reference,
                reference_prefix=reference_prefix,
                component_type=comp_type,
                value=comp_value,
                footprint=footprint,
                position=(comp_data.get('x', 0), comp_data.get('y', 0)),
                rotation=comp_data.get('rotation', 0),
                properties={
                    'power_rating': comp_data.get('power_rating', ''),
                    'voltage_rating': comp_data.get('voltage_rating', ''),
                    'tolerance': comp_data.get('tolerance', ''),
                },
                original_data=comp_data
            )

            # Parse pins
            pins_data = comp_data.get('pins', [])
            for pin_data in pins_data:
                pin = ComponentPin(
                    number=str(pin_data.get('number', '')),
                    name=pin_data.get('name', ''),
                    net=pin_data.get('net', ''),
                    position=(pin_data.get('x', 0), pin_data.get('y', 0)),
                    pin_type=pin_data.get('type', 'passive')
                )
                component.pins.append(pin)

            # Store component
            self.components[reference] = component

    def _parse_nets(self, circuit_data: Dict[str, Any]):
        """
        Parse nets from circuit data.

        Builds Net objects by collecting all pins connected to each net.
        Detects power/ground nets automatically.

        Handles two formats:
        - List of strings: ["GND", "VCC", "NET_1"]
        - List of dicts: [{"name": "GND"}, {"name": "VCC"}]
        """
        nets_data = circuit_data.get('nets', [])

        # First pass: Create Net objects
        for net_data in nets_data:
            # Handle both string and dict formats
            if isinstance(net_data, str):
                net_name = net_data
            elif isinstance(net_data, dict):
                net_name = net_data.get('name', '')
            else:
                continue

            if not net_name:
                continue

            # Detect power nets
            is_power = any(keyword in net_name.upper()
                          for keyword in ['VCC', 'VDD', 'GND', 'POWER', 'SUPPLY', '5V', '3V3', '12V', '24V'])

            net = Net(
                name=net_name,
                is_power=is_power,
                net_class="Power" if is_power else "Default"
            )

            self.nets[net_name] = net

        # Second pass: Populate nets with pins from components
        for component in self.components.values():
            for pin in component.pins:
                if pin.net in self.nets:
                    self.nets[pin.net].add_pin(pin)
                else:
                    # Create net if it doesn't exist (handle orphaned pins)
                    net = Net(name=pin.net)
                    net.add_pin(pin)
                    self.nets[pin.net] = net

    def _build_net_to_component_mapping(self):
        """Build mapping of which components connect to each net."""
        # This enables Net.get_components() to work
        for component in self.components.values():
            for pin in component.pins:
                if pin.net in self.nets:
                    # Store component reference in net's metadata
                    if not hasattr(self.nets[pin.net], '_component_refs'):
                        self.nets[pin.net]._component_refs = set()
                    self.nets[pin.net]._component_refs.add(component.reference)

    def _infer_reference_prefix(self, component_type: str) -> str:
        """
        Infer reference prefix from component type.

        GENERIC: Works for any component type.
        """
        component_type_lower = component_type.lower()

        # Standard mappings
        if 'resistor' in component_type_lower:
            return 'R'
        elif 'capacitor' in component_type_lower:
            return 'C'
        elif 'inductor' in component_type_lower or 'coil' in component_type_lower:
            return 'L'
        elif 'diode' in component_type_lower:
            return 'D'
        elif 'transistor' in component_type_lower or 'mosfet' in component_type_lower or 'bjt' in component_type_lower:
            return 'Q'
        elif 'connector' in component_type_lower or 'header' in component_type_lower:
            return 'J'
        elif 'ic' in component_type_lower or 'chip' in component_type_lower or 'mcu' in component_type_lower:
            return 'U'
        elif 'led' in component_type_lower:
            return 'D'
        elif 'switch' in component_type_lower or 'button' in component_type_lower:
            return 'SW'
        elif 'crystal' in component_type_lower or 'oscillator' in component_type_lower:
            return 'Y'
        else:
            return 'U'  # Default to U for unknown types

    def validate(self) -> bool:
        """
        Validate circuit graph for common errors.

        Performs pre-flight checks before file generation.
        Returns True if valid (warnings allowed), False if critical errors found.

        Checks:
        - Duplicate component references
        - Dangling nets (only 1 pin)
        - Empty nets (no pins)
        - Components without footprints
        - Unannotated components (R?, C?, etc.)
        """
        self.validation_errors = []  # Reset errors

        # Check for duplicate component references
        seen_refs = set()
        for component in self.components.values():
            if component.reference in seen_refs:
                self.validation_errors.append(ValidationError(
                    severity="CRITICAL",
                    category="ANNOTATION",
                    message=f"Duplicate component reference: {component.reference}",
                    location=component.reference,
                    fix_suggestion="Run component annotation (Phase 1 Task 1.1)"
                ))
            seen_refs.add(component.reference)

        # Check for unannotated components (R?, C?, etc.)
        for component in self.components.values():
            if '?' in component.reference:
                self.validation_errors.append(ValidationError(
                    severity="ERROR",
                    category="ANNOTATION",
                    message=f"Unannotated component: {component.reference}",
                    location=component.reference,
                    fix_suggestion="Run component annotation (Phase 1 Task 1.1)"
                ))

        # Check for components without footprints
        for component in self.components.values():
            if not component.footprint:
                self.validation_errors.append(ValidationError(
                    severity="ERROR",
                    category="FOOTPRINT",
                    message=f"Component missing footprint: {component.reference}",
                    location=component.reference,
                    fix_suggestion="Assign footprint based on component specifications"
                ))

        # Check for dangling nets (only 1 pin - incomplete connection)
        for net in self.nets.values():
            if net.is_dangling():
                self.validation_errors.append(ValidationError(
                    severity="WARNING",
                    category="NETLIST",
                    message=f"Net has only 1 connection (dangling): {net.name}",
                    location=net.name,
                    fix_suggestion="Check if connection is intentional or missing"
                ))

        # Check for empty nets (no pins - likely data error)
        for net in self.nets.values():
            if net.is_empty():
                self.validation_errors.append(ValidationError(
                    severity="WARNING",
                    category="NETLIST",
                    message=f"Net has no connections: {net.name}",
                    location=net.name,
                    fix_suggestion="Remove unused net or add connections"
                ))

        # Check if any nets exist
        if not self.nets:
            self.validation_errors.append(ValidationError(
                severity="CRITICAL",
                category="NETLIST",
                message="Circuit has no nets (no connections)",
                location="circuit",
                fix_suggestion="Check input JSON for netlist data"
            ))

        # Check if any components exist
        if not self.components:
            self.validation_errors.append(ValidationError(
                severity="CRITICAL",
                category="COMPONENT",
                message="Circuit has no components",
                location="circuit",
                fix_suggestion="Check input JSON for component data"
            ))

        # Return False if CRITICAL errors found
        has_critical = any(err.severity == "CRITICAL" for err in self.validation_errors)
        return not has_critical

    def get_validation_report(self) -> str:
        """Generate human-readable validation report."""
        if not self.validation_errors:
            return "✅ Circuit validation: PASSED (no errors)"

        # Count by severity
        critical_count = sum(1 for e in self.validation_errors if e.severity == "CRITICAL")
        error_count = sum(1 for e in self.validation_errors if e.severity == "ERROR")
        warning_count = sum(1 for e in self.validation_errors if e.severity == "WARNING")

        report = []
        report.append(f"\n{'='*70}")
        report.append(f"Circuit Validation Report: {self.circuit_name}")
        report.append(f"{'='*70}")
        report.append(f"CRITICAL: {critical_count}  |  ERRORS: {error_count}  |  WARNINGS: {warning_count}")
        report.append(f"{'='*70}\n")

        # Group errors by severity
        for severity in ["CRITICAL", "ERROR", "WARNING"]:
            errors = [e for e in self.validation_errors if e.severity == severity]
            if errors:
                report.append(f"\n{severity} ({len(errors)}):")
                for error in errors:
                    report.append(f"  • {error}")

        report.append(f"\n{'='*70}")

        return "\n".join(report)

    def get_stats(self) -> Dict[str, int]:
        """Get circuit statistics."""
        return {
            'components': len(self.components),
            'nets': len(self.nets),
            'pins': sum(len(comp.pins) for comp in self.components.values()),
            'power_nets': sum(1 for net in self.nets.values() if net.is_power),
            'validation_errors': len(self.validation_errors),
            'critical_errors': sum(1 for e in self.validation_errors if e.severity == "CRITICAL"),
        }

    def __str__(self):
        """String representation of circuit graph."""
        stats = self.get_stats()
        return (f"CircuitGraph(name={self.circuit_name}, "
                f"components={stats['components']}, "
                f"nets={stats['nets']}, "
                f"pins={stats['pins']})")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_circuit_graph(circuit_file: Path) -> CircuitGraph:
    """
    Load CircuitGraph from CIRCUIT_*.json file.

    Args:
        circuit_file: Path to CIRCUIT_*.json file

    Returns:
        CircuitGraph object

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is not valid JSON
        ValueError: If circuit data is invalid
    """
    if not circuit_file.exists():
        raise FileNotFoundError(f"Circuit file not found: {circuit_file}")

    with open(circuit_file, 'r') as f:
        data = json.load(f)

    circuit_data = data.get('circuit', {})
    if not circuit_data:
        raise ValueError(f"No 'circuit' key found in {circuit_file}")

    circuit_name = circuit_data.get('moduleName', circuit_file.stem.replace('circuit_', ''))

    return CircuitGraph(circuit_data, circuit_name)


def validate_circuit_file(circuit_file: Path, fail_on_errors: bool = True) -> Tuple[bool, List[ValidationError]]:
    """
    Validate a circuit file and return validation results.

    Args:
        circuit_file: Path to CIRCUIT_*.json file
        fail_on_errors: If True, return False on any ERROR or CRITICAL
                       If False, return False only on CRITICAL

    Returns:
        (is_valid, errors) tuple
    """
    try:
        graph = load_circuit_graph(circuit_file)
        is_valid = graph.validate()

        if fail_on_errors:
            # Fail on ERROR or CRITICAL
            has_errors = any(err.severity in ["CRITICAL", "ERROR"]
                           for err in graph.validation_errors)
            return (not has_errors, graph.validation_errors)
        else:
            # Fail only on CRITICAL
            return (is_valid, graph.validation_errors)

    except Exception as e:
        error = ValidationError(
            severity="CRITICAL",
            category="SYSTEM",
            message=f"Failed to load circuit: {str(e)}",
            location=str(circuit_file)
        )
        return (False, [error])


# ============================================================================
# MAIN (for testing)
# ============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python circuit_graph.py <circuit_file.json>")
        sys.exit(1)

    circuit_file = Path(sys.argv[1])

    print(f"Loading circuit: {circuit_file}")
    graph = load_circuit_graph(circuit_file)

    print(f"\n{graph}")
    print(f"\nStats: {graph.get_stats()}")

    print("\nValidating circuit...")
    is_valid = graph.validate()

    print(graph.get_validation_report())

    if is_valid:
        print("\n✅ Circuit is VALID (ready for generation)")
        sys.exit(0)
    else:
        print("\n❌ Circuit is INVALID (fix errors before generation)")
        sys.exit(1)
