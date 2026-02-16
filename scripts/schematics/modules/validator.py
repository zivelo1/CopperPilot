# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Validator module for schematic generator."""
from typing import Dict, List, Set, Tuple
from .utils import SchematicContext, Component, Wire, Point, Rectangle, line_segment_intersects_rectangle, line_segment_crosses_rectangle_body

class Validator:
    """Validate schematic for ERC/DRC compliance."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.errors = []
        self.warnings = []

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Perform comprehensive validation."""
        print("\n=== Stage 5: Validation ===")

        # Clear previous validation
        self.errors = []
        self.warnings = []

        # Run validation checks
        self._check_connectivity(context)
        # _check_component_placement(context) # Removed - redundant with layout engine errors and _validate_layout_quality
        self._check_wire_routing(context)
        self._check_pin_connections(context)
        self._check_power_nets(context)
        self._perform_erc(context)
        self._perform_drc(context)

        # Add results to context
        context.errors.extend(self.errors)
        context.warnings.extend(self.warnings)

        # Statistics
        context.stats['validation'] = {
            'errors': len(self.errors),
            'warnings': len(self.warnings),
            'connectivity_score': self._calculate_connectivity_score(context),
            'placement_score': self._calculate_placement_score(context)
        }

        # Print results
        if self.errors:
            print(f"❌ Found {len(self.errors)} errors:")
            for error in self.errors[:5]:
                print(f"  - {error}")
        else:
            print("✅ No errors found")

        if self.warnings:
            print(f"⚠️  Found {len(self.warnings)} warnings:")
            for warning in self.warnings[:5]:
                print(f"  - {warning}")

        return context

    def _check_connectivity(self, context: SchematicContext):
        """Check that all nets are properly connected."""
        # Check for unconnected pins
        # Refined: Only warn for unconnected pins if they are inputs or outputs
        connected_pins_in_nets = set()

        for net in context.nets.values():
            if len(net.pins) > 1: # Only consider nets with multiple connections for 'connected' status
                for comp_ref, pin_num in net.pins:
                    connected_pins_in_nets.add((comp_ref, pin_num))

        for comp_ref, component in context.components.items():
            for pin_num, pin_obj in component.pins.items(): # Iterate over Pin objects
                if (comp_ref, pin_num) not in connected_pins_in_nets:
                    # Suppress warning if pin is explicitly marked as 'unconnected'
                    if pin_obj.type == 'unconnected':
                        continue
                    
                    # Only warn if the pin is explicitly an input or output type
                    # We also need to check if this pin's net is a single-point net.
                    # This is to avoid double-warning: once for the pin, once for the net.
                    # If it's a single-point net that's not 'unconnected', the net check will catch it.
                    
                    
                    pin_is_input_output = pin_obj.type in ['input', 'output', 'power_input', 'power_output', 'bidirectional'] # Define here
                    is_part_of_single_point_net = False
                    for net in context.nets.values():
                        # Find the net associated with this pin
                        if (comp_ref, pin_num) in net.pins:
                            if len(net.pins) == 1: # This pin belongs to a single-point net
                                is_part_of_single_point_net = True
                            break

                    if pin_is_input_output and not is_part_of_single_point_net: # Only warn if it's I/O and not part of single-point net
                        self.warnings.append(f"Unconnected {pin_obj.type} pin: {comp_ref}.{pin_num}")
                    # else: Internal, passive, or unknown pins can be unconnected without warning

        # Check for single-point nets
        for net_name, net in context.nets.items():
            if len(net.pins) == 1:
                # Add a warning for single-point nets that are not specifically NC
                if not net_name.upper().endswith('_NC') and not net_name.upper().startswith('NC_'):
                    # If the single pin is of type 'unconnected', suppress this warning
                    comp_ref, pin_num = net.pins[0]
                    component = context.components.get(comp_ref)
                    if component and component.get_pin(pin_num) and component.get_pin(pin_num).type == 'unconnected':
                        continue
                    self.warnings.append(f"Net '{net_name}' has only one connection")
            elif len(net.pins) == 0:
                self.errors.append(f"Net '{net_name}' has no connections")

    def _check_wire_routing(self, context: SchematicContext):
        """Check wire routing for issues."""
        # Check for wires crossing THROUGH component bodies
        for wire in context.wires:
            for component in context.components.values():
                # For more precise check, create a slightly smaller 'body' rectangle for the component
                # to ignore overlaps with pins or very edges.
                body_margin = 10 # Pixels to shrink component bounds for crossing check
                component_body_rect = Rectangle(
                    component.bounds.x + body_margin,
                    component.bounds.y + body_margin,
                    component.bounds.width - 2 * body_margin,
                    component.bounds.height - 2 * body_margin
                )
                
                # Ensure the body rectangle is valid (positive width/height)
                if component_body_rect.width <= 0 or component_body_rect.height <= 0:
                    continue # Component too small or margin too large, skip precise check

                # Use the precise line segment to rectangle intersection check
                if line_segment_intersects_rectangle(wire.start, wire.end, component_body_rect):
                    self.warnings.append(f"Wire from net '{wire.net}' crosses through component {component.ref_des}")
        
        
        # Check for excessive wire crossings
        crossing_count = self._count_wire_crossings(context.wires)
        if crossing_count > 50:
            self.warnings.append(f"Excessive wire crossings detected: {crossing_count}")

    def _check_pin_connections(self, context: SchematicContext):
        """Check that all pins are properly defined and connected."""
        # Check for components without pins
        for comp_ref, component in context.components.items():
            if not component.pins:
                self.errors.append(f"Component {comp_ref} has no pins defined")

        # Check for mismatched pin references
        for net_name, net in context.nets.items():
            for comp_ref, pin_num in net.pins:
                if comp_ref in context.components:
                    component = context.components[comp_ref]
                    if pin_num not in component.pins:
                        self.errors.append(f"Net '{net_name}' references non-existent pin {comp_ref}.{pin_num}")
                else:
                    self.errors.append(f"Net '{net_name}' references non-existent component {comp_ref}")

    def _check_power_nets(self, context: SchematicContext):
        """Check power and ground net connectivity."""
        power_nets = []
        ground_nets = []

        for net_name, net in context.nets.items():
            if net.is_power:
                power_nets.append(net_name)
            if net.is_ground:
                ground_nets.append(net_name)

        if not power_nets:
            self.warnings.append("No power nets detected in circuit")
        if not ground_nets:
            self.warnings.append("No ground nets detected in circuit")

        # Check for ICs without power connections
        for comp_ref, component in context.components.items():
            if 'ic' in component.type.lower() or component.symbol == 'ic':
                has_power = False
                has_ground = False

                for net in context.nets.values():
                    for conn_ref, pin_num in net.pins:
                        if conn_ref == comp_ref:
                            if net.is_power:
                                has_power = True
                            if net.is_ground:
                                has_ground = True

                if not has_power:
                    self.warnings.append(f"IC {comp_ref} has no power connection")
                if not has_ground:
                    self.warnings.append(f"IC {comp_ref} has no ground connection")

    def _perform_erc(self, context: SchematicContext):
        """Perform Electrical Rules Check."""
        # Check for shorted outputs
        output_nets = {}  # net_name -> list of output pins

        for net_name, net in context.nets.items():
            outputs = []
            for comp_ref, pin_num in net.pins:
                component = context.components.get(comp_ref)
                if component:
                    pin = component.pins.get(pin_num)
                    if pin and pin.type == 'output':
                        outputs.append(f"{comp_ref}.{pin_num}")

            if len(outputs) > 1:
                self.errors.append(f"Net '{net_name}' has multiple outputs: {', '.join(outputs)}")

        # Check for floating inputs
        for comp_ref, component in context.components.items():
            for pin_num, pin in component.pins.items():
                if pin.type == 'input':
                    # Check if this input is connected
                    connected = False
                    for net in context.nets.values():
                        if (comp_ref, pin_num) in net.pins:
                            connected = True
                            break

                    if not connected:
                        self.warnings.append(f"Input pin {comp_ref}.{pin_num} is floating")

    def _perform_drc(self, context: SchematicContext):
        """Perform Design Rules Check."""
        # Check minimum spacing
        min_spacing = 20  # pixels

        components = list(context.components.values())
        for i, comp1 in enumerate(components):
            for comp2 in components[i+1:]:
                distance = comp1.position.distance_to(comp2.position)
                if distance < min_spacing:
                    self.warnings.append(f"Components {comp1.ref_des} and {comp2.ref_des} "
                                       f"are too close ({distance:.1f} < {min_spacing})")

        # Check wire angles (should be orthogonal)
        for wire in context.wires:
            if wire.start.x != wire.end.x and wire.start.y != wire.end.y:
                # Wire is diagonal
                angle = abs((wire.end.y - wire.start.y) / (wire.end.x - wire.start.x))
                if angle not in [0, float('inf')]:  # Not horizontal or vertical
                    self.warnings.append(f"Non-orthogonal wire in net '{wire.net}'")

    def _wire_crosses_component(self, wire: Wire, component: Component) -> bool:
        """Check if a wire crosses through a component's actual body."""
        # For more precise check, create a slightly smaller 'body' rectangle for the component
        # to ignore overlaps with pins or very edges.
        body_margin = 10 # Pixels to shrink component bounds for crossing check
        component_body_rect = Rectangle(
            component.bounds.x + body_margin,
            component.bounds.y + body_margin,
            component.bounds.width - 2 * body_margin,
            component.bounds.height - 2 * body_margin
        )
        
        # Ensure the body rectangle is valid (positive width/height)
        if component_body_rect.width <= 0 or component_body_rect.height <= 0:
            return False # Component too small or margin too large, skip precise check

        # Use the precise line segment to rectangle body intersection check
        return line_segment_crosses_rectangle_body(wire.start, wire.end, component_body_rect)

    def _count_wire_crossings(self, wires: List[Wire]) -> int:
        """Count the number of wire crossings."""
        crossings = 0

        for i, wire1 in enumerate(wires):
            for wire2 in wires[i+1:]:
                if self._wires_cross(wire1, wire2):
                    crossings += 1

        return crossings

    def _wires_cross(self, wire1: Wire, wire2: Wire) -> bool:
        """Check if two wires cross each other."""
        # Check if line segments intersect
        def ccw(A, B, C):
            return (C.y - A.y) * (B.x - A.x) > (B.y - A.y) * (C.x - A.x)

        A, B = wire1.start, wire1.end
        C, D = wire2.start, wire2.end

        return (ccw(A, C, D) != ccw(B, C, D) and
                ccw(A, B, C) != ccw(A, B, D))

    def _calculate_connectivity_score(self, context: SchematicContext) -> float:
        """Calculate a connectivity score (0-100)."""
        if not context.nets:
            return 0.0

        # Count connected vs unconnected pins
        total_pins = sum(len(c.pins) for c in context.components.values())
        connected_pins = sum(len(net.pins) for net in context.nets.values())

        if total_pins == 0:
            return 0.0

        return min(100.0, (connected_pins / total_pins) * 100)

    def _calculate_placement_score(self, context: SchematicContext) -> float:
        """Calculate a placement quality score (0-100)."""
        if not context.components:
            return 0.0

        score = 100.0

        # Penalize overlapping components
        components = list(context.components.values())
        for i, comp1 in enumerate(components):
            for comp2 in components[i+1:]:
                if comp1.bounds.intersects(comp2.bounds):
                    score -= 5.0

        # Penalize components outside canvas
        for component in context.components.values():
            if (component.position.x < 0 or component.position.y < 0 or
                component.position.x > context.canvas_width or
                component.position.y > context.canvas_height):
                score -= 10.0

        return max(0.0, score)

    def generate_report(self, context: SchematicContext) -> str:
        """Generate validation report."""
        report = []
        report.append("=" * 60)
        report.append("SCHEMATIC VALIDATION REPORT")
        report.append("=" * 60)
        report.append("")

        # Summary
        report.append("SUMMARY:")
        report.append(f"  Components: {len(context.components)}")
        report.append(f"  Nets: {len(context.nets)}")
        report.append(f"  Wires: {len(context.wires)}")
        report.append(f"  Errors: {len(self.errors)}")
        report.append(f"  Warnings: {len(self.warnings)}")
        report.append("")

        # Scores
        report.append("QUALITY SCORES:")
        report.append(f"  Connectivity: {context.stats.get('validation', {}).get('connectivity_score', 0):.1f}%")
        report.append(f"  Placement: {context.stats.get('validation', {}).get('placement_score', 0):.1f}%")
        report.append("")

        # Errors
        if self.errors:
            report.append("ERRORS:")
            for i, error in enumerate(self.errors, 1):
                report.append(f"  {i}. {error}")
            report.append("")

        # Warnings
        if self.warnings:
            report.append("WARNINGS:")
            for i, warning in enumerate(self.warnings[:10], 1):  # Show first 10
                report.append(f"  {i}. {warning}")
            if len(self.warnings) > 10:
                report.append(f"  ... and {len(self.warnings) - 10} more warnings")
            report.append("")

        # Result
        if not self.errors:
            report.append("✅ VALIDATION PASSED - Schematic is ready for production")
        else:
            report.append("❌ VALIDATION FAILED - Please fix errors before using schematic")

        report.append("=" * 60)

        return "\n".join(report)