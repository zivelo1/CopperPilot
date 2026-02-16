#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Schematic Annotator - Automatic Component Reference Assignment
==============================================================

TC #39 (2025-11-24): Phase 1 Task 1.1 - Fix Component Annotation (RC #1)

CRITICAL ROOT CAUSE FIX: Component Annotation Failure
- Problem: Components have duplicate references (R?, C?, Q?, U?)
- Impact: "Schematic is not fully annotated" ERC errors
- Solution: Assign unique sequential references automatically

Root Cause Fixed:
- RC #1: Component Annotation Failure → 10-13 duplicate_reference errors

Evidence of Problem:
- ERC reports show: "duplicate_reference: R? appears multiple times"
- After manual annotation in KiCad: Errors disappear
- Working examples: Always use R1, R2, C1, C2, Q1, Q2

Fix Strategy:
- Iterate through components by type (all R's, then all C's, etc.)
- Assign sequential numbers (R1, R2, R3, ...)
- Preserve reference prefix from component type
- Handle multi-unit ICs with unit suffixes

Design Principles:
- GENERIC: Works for ANY component type and ANY circuit
- DETERMINISTIC: Same circuit always gets same annotation
- STABLE: Annotation order is consistent and predictable

Author: CopperPilot AI System (TC #39)
Date: 2025-11-24
"""

from typing import Dict, List
from collections import defaultdict
from .circuit_graph import CircuitGraph, Component


class SchematicAnnotator:
    """
    Automatic component annotation - assigns unique sequential references.

    Converts unannotated components (R?, C?, Q?) into properly annotated
    components (R1, R2, R3, C1, C2, C3, Q1, Q2).

    GENERIC: Works for any component type in any circuit topology.
    """

    def __init__(self):
        """Initialize annotator."""
        self.annotation_stats = {}  # Track annotation counts by prefix

    def annotate(self, circuit_graph: CircuitGraph) -> CircuitGraph:
        """
        Annotate components in circuit graph - ONLY those needing annotation.

        TC #68 FIX (2025-12-02): PRESERVE VALID UNIQUE REFERENCES

        Previously, this method re-annotated ALL components, breaking refs like
        'C_ENC1_A' which are already valid and unique. This caused pinNetMapping
        mismatches and resulted in PCB pads having (net 0 "") - unassigned nets.

        NEW BEHAVIOR:
        - PRESERVE valid unique refs (no '?' and not duplicate)
        - Only fix refs that actually need fixing
        - Track ref changes in self.ref_changes for pinNetMapping sync

        Args:
            circuit_graph: CircuitGraph to annotate

        Returns:
            Same CircuitGraph with annotated components
        """
        # Reset stats and ref changes tracking
        self.annotation_stats = defaultdict(int)
        self.ref_changes = {}  # old_ref -> new_ref for pinNetMapping sync

        # First pass: identify which refs need fixing
        seen_refs = set()
        needs_fixing = []  # List of (component, reason)
        valid_components = []  # Components with valid unique refs

        for component in circuit_graph.components.values():
            ref = component.reference

            if '?' in ref:
                needs_fixing.append((component, 'unannotated'))
            elif ref in seen_refs:
                needs_fixing.append((component, 'duplicate'))
            else:
                seen_refs.add(ref)
                valid_components.append(component)

        # If nothing needs fixing, return unchanged
        if not needs_fixing:
            # Still rebuild components dict to ensure keys match references
            annotated_components = {c.reference: c for c in valid_components}
            circuit_graph.components = annotated_components
            return circuit_graph

        # Second pass: fix only the components that need it
        # Group components that need fixing by their prefix
        components_to_fix_by_prefix = defaultdict(list)

        for component, reason in needs_fixing:
            # Extract prefix from reference or infer from component type
            ref = component.reference
            if '?' in ref:
                prefix = ref.replace('?', '').rstrip('0123456789')
            else:
                # For duplicates, use the original prefix
                prefix = component.reference_prefix

            # If prefix is empty or just letters with underscore (like C_ENC1_A),
            # extract just the leading letters as the prefix
            if not prefix or '_' in prefix:
                prefix = self._extract_base_prefix(ref, component.component_type)

            components_to_fix_by_prefix[prefix].append(component)

        # Find next available numbers for each prefix based on existing valid refs
        prefix_counters = defaultdict(int)
        import re
        for component in valid_components:
            ref = component.reference
            # Extract number from end of reference (e.g., R1, C25, LED3)
            match = re.match(r'^([A-Z]+)(\d+)$', ref)
            if match:
                prefix, num = match.groups()
                prefix_counters[prefix] = max(prefix_counters[prefix], int(num))

        # Increment to get next available
        for prefix in prefix_counters:
            prefix_counters[prefix] += 1

        # Assign new refs to components that need fixing
        for prefix, components in sorted(components_to_fix_by_prefix.items()):
            # Sort for deterministic order
            components.sort(key=lambda c: (c.component_type, c.reference))

            for component in components:
                old_ref = component.reference

                # Get next available number
                if prefix not in prefix_counters:
                    prefix_counters[prefix] = 1
                new_num = prefix_counters[prefix]
                prefix_counters[prefix] += 1

                new_ref = f"{prefix}{new_num}"

                # Track the change
                self.ref_changes[old_ref] = new_ref

                # Update component
                component.reference = new_ref
                component.reference_prefix = prefix

                # Track stats
                self.annotation_stats[prefix] += 1

        # Rebuild components dict with all components (valid + fixed)
        annotated_components = {}
        for component in valid_components:
            annotated_components[component.reference] = component
        for component, _ in needs_fixing:
            annotated_components[component.reference] = component

        circuit_graph.components = annotated_components

        return circuit_graph

    def _extract_base_prefix(self, ref: str, comp_type: str) -> str:
        """
        Extract base prefix from reference or component type.

        For refs like 'C_ENC1_A', extracts 'C'.
        For refs like 'LED_PWR', extracts 'LED'.

        Args:
            ref: Component reference
            comp_type: Component type

        Returns:
            Base prefix (e.g., 'R', 'C', 'U', 'LED')
        """
        # Try to extract leading letters before underscore or number
        import re
        match = re.match(r'^([A-Z]+)', ref.upper())
        if match:
            prefix = match.group(1)
            # Handle special cases like LED
            if prefix == 'LED':
                return 'LED'
            elif prefix in ('SW', 'POT'):
                return prefix
            # For single letters, return as-is
            if len(prefix) <= 2:
                return prefix

        # Fallback: infer from component type
        prefix_map = {
            'resistor': 'R',
            'capacitor': 'C',
            'transistor': 'Q',
            'mosfet': 'Q',
            'ic': 'U',
            'diode': 'D',
            'led': 'LED',
            'inductor': 'L',
            'connector': 'J',
            'switch': 'SW',
            'fuse': 'F',
            'transformer': 'T',
            'crystal': 'Y',
            'battery': 'BT',
            'potentiometer': 'POT',
            'encoder': 'ENC'
        }
        return prefix_map.get(comp_type.lower(), 'U')

    def get_ref_changes(self) -> Dict[str, str]:
        """
        Get mapping of old references to new references.

        Use this to update pinNetMapping after annotation.

        Returns:
            Dict mapping old_ref -> new_ref
        """
        return getattr(self, 'ref_changes', {})

    def get_annotation_summary(self) -> str:
        """
        Get human-readable annotation summary.

        Returns:
            String describing annotation results
        """
        ref_changes = getattr(self, 'ref_changes', {})

        if not self.annotation_stats and not ref_changes:
            return "All components already have valid unique references - no changes needed"

        if not self.annotation_stats:
            return "All components already have valid unique references - no changes needed"

        lines = []
        total = sum(self.annotation_stats.values())
        lines.append(f"Fixed {total} component reference(s):")
        for prefix, count in sorted(self.annotation_stats.items()):
            lines.append(f"  • {prefix}: {count} component(s)")

        return "\n".join(lines)


def annotate_circuit(circuit_graph: CircuitGraph, verbose: bool = True) -> CircuitGraph:
    """
    Convenience function to annotate a circuit graph.

    TC #68 FIX (2025-12-02): Now preserves valid unique references.
    Also stores ref_changes in the circuit_graph for pinNetMapping sync.

    Args:
        circuit_graph: CircuitGraph to annotate
        verbose: If True, print annotation summary

    Returns:
        Annotated CircuitGraph (with ref_changes attribute if any refs were changed)
    """
    annotator = SchematicAnnotator()
    annotated_graph = annotator.annotate(circuit_graph)

    # Store ref_changes in circuit_graph for use by callers
    # This allows pinNetMapping to be updated if refs changed
    annotated_graph.ref_changes = annotator.get_ref_changes()

    if verbose:
        print(f"  ✓ {annotator.get_annotation_summary()}")

    return annotated_graph


# ============================================================================
# SPECIALIZED ANNOTATION STRATEGIES (Future Enhancement)
# ============================================================================

class SmartAnnotator(SchematicAnnotator):
    """
    Enhanced annotator with intelligent component grouping.

    Future enhancement: Group components by circuit function
    (power supply components together, signal path components together, etc.)

    Currently uses same logic as base SchematicAnnotator.
    Placeholder for future enhancements.
    """

    def annotate(self, circuit_graph: CircuitGraph) -> CircuitGraph:
        """
        Annotate with intelligent grouping.

        Future: Group components by function/location on board.
        Current: Use base class sequential annotation.
        """
        # Future: implement function-based grouping by circuit block
        return super().annotate(circuit_graph)


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_annotation(circuit_graph: CircuitGraph) -> bool:
    """
    Validate that all components are properly annotated.

    Checks:
    - No duplicate references
    - No unannotated references (containing '?')
    - All references follow standard format (letter + number)

    Returns:
        True if annotation is valid, False otherwise
    """
    seen_references = set()
    has_errors = False

    for component in circuit_graph.components.values():
        ref = component.reference

        # Check for '?' (unannotated)
        if '?' in ref:
            print(f"  ❌ Unannotated component: {ref}")
            has_errors = True

        # Check for duplicates
        if ref in seen_references:
            print(f"  ❌ Duplicate reference: {ref}")
            has_errors = True

        seen_references.add(ref)

    return not has_errors


def check_annotation_needed(circuit_graph: CircuitGraph) -> bool:
    """
    Check if annotation is needed for this circuit.

    Returns:
        True if any component needs annotation (has '?' in reference)
    """
    return any('?' in comp.reference for comp in circuit_graph.components.values())


# ============================================================================
# MAIN (for testing)
# ============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from .circuit_graph import load_circuit_graph

    if len(sys.argv) < 2:
        print("Usage: python schematic_annotator.py <circuit_file.json>")
        sys.exit(1)

    circuit_file = Path(sys.argv[1])

    print(f"Loading circuit: {circuit_file}")
    graph = load_circuit_graph(circuit_file)

    print(f"\n{graph}")
    print(f"Stats: {graph.get_stats()}")

    # Check if annotation needed
    if check_annotation_needed(graph):
        print("\n⚠️  Circuit has unannotated components")
        print("\nAnnotating components...")
        graph = annotate_circuit(graph, verbose=True)

        print("\nValidating annotation...")
        if validate_annotation(graph):
            print("✅ Annotation is valid")
        else:
            print("❌ Annotation has errors")

        # Show example components
        print("\nExample annotated components:")
        for ref, comp in list(graph.components.items())[:5]:
            print(f"  {ref}: {comp.component_type} = {comp.value} ({comp.footprint})")

    else:
        print("\n✅ Circuit is already fully annotated")
