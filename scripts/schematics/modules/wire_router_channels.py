# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Channel-based wire routing - MANDATORY no component crossing"""
from typing import Dict, List, Tuple, Set
from .utils import SchematicContext, Wire, Point, Rectangle, Component, get_wire_color

class WireRouter:
    """Channel-based routing with MANDATORY component avoidance."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.clearance = 20  # Minimum clearance from component bounds

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Route wires using only routing channels."""
        print("\n=== Stage 3: Channel-Based Wire Routing ===")

        routed = 0
        total_wires = 0
        failed_routes = []

        for net_name, net in context.nets.items():
            if len(net.pins) < 2:
                continue

            net.color = get_wire_color(net_name)
            pin_positions = self._get_pin_positions(net, context)

            if len(pin_positions) < 2:
                continue

            # Route with MANDATORY component avoidance
            wires = self._route_net_with_avoidance(net, pin_positions, context)

            if wires:
                context.wires.extend(wires)
                total_wires += len(wires)
                routed += 1
            else:
                failed_routes.append(net_name)

        if failed_routes:
            print(f"⚠️  Failed to route {len(failed_routes)} nets: {failed_routes[:5]}")

        context.stats['routing'] = {
            'total_nets': len(context.nets),
            'routed_nets': routed,
            'failed_nets': len(failed_routes),
            'total_wires': total_wires
        }

        print(f"✓ Routed {routed} nets with {total_wires} wires")
        print(f"✓ {len(failed_routes)} nets could not route without crossing")

        return context

    def _route_net_with_avoidance(self, net, pin_positions: List[Point], context: SchematicContext) -> List[Wire]:
        """Route net avoiding ALL components."""
        wires = []

        # Use first pin as hub (star topology)
        hub = pin_positions[0]

        for pin_pos in pin_positions[1:]:
            # Try to create route that avoids all components
            route_wires = self._route_between_points_avoiding_components(
                pin_pos, hub, net.name, net.color, context
            )

            if route_wires:
                wires.extend(route_wires)
            else:
                # Route failed - cannot avoid components
                return None

        return wires

    def _route_between_points_avoiding_components(
        self,
        start: Point,
        end: Point,
        net_name: str,
        color: str,
        context: SchematicContext
    ) -> List[Wire]:
        """Create L-shaped route that avoids ALL components."""
        wires = []

        # Try horizontal-first route
        corner = Point(end.x, start.y)

        # Check if horizontal segment crosses any component
        h_wire = Wire(start, corner, net_name, color, 2)
        if not self._wire_crosses_any_component(h_wire, context):
            # Check if vertical segment crosses any component
            v_wire = Wire(corner, end, net_name, color, 2)
            if not self._wire_crosses_any_component(v_wire, context):
                # Both segments clear - use this route
                if h_wire.start.x != h_wire.end.x:  # Non-zero horizontal
                    wires.append(h_wire)
                if v_wire.start.y != v_wire.end.y:  # Non-zero vertical
                    wires.append(v_wire)
                return wires

        # Try vertical-first route
        corner = Point(start.x, end.y)

        v_wire = Wire(start, corner, net_name, color, 2)
        if not self._wire_crosses_any_component(v_wire, context):
            h_wire = Wire(corner, end, net_name, color, 2)
            if not self._wire_crosses_any_component(h_wire, context):
                if v_wire.start.y != v_wire.end.y:
                    wires.append(v_wire)
                if h_wire.start.x != h_wire.end.x:
                    wires.append(h_wire)
                return wires

        # Both L-shaped routes fail - try direct route (last resort)
        direct_wire = Wire(start, end, net_name, color, 2)
        if not self._wire_crosses_any_component(direct_wire, context):
            wires.append(direct_wire)
            return wires

        # Cannot route without crossing
        return None

    def _wire_crosses_any_component(self, wire: Wire, context: SchematicContext) -> bool:
        """Check if wire crosses ANY component (excluding wires connected to component's own pins)."""
        for component in context.components.values():
            # Check if either endpoint is a pin of THIS component
            start_is_this_comp_pin = self._point_is_component_pin(wire.start, component)
            end_is_this_comp_pin = self._point_is_component_pin(wire.end, component)

            # If wire connects to this component's pin, skip checking against THIS component
            # (wires are allowed to touch the component they're connecting to)
            if start_is_this_comp_pin or end_is_this_comp_pin:
                continue

            # Check if wire crosses this component's bounds
            if wire.intersects_rect(component.bounds):
                return True

        return False

    def _point_is_component_pin(self, point: Point, component: Component) -> bool:
        """Check if a point is at one of the component's pins."""
        for pin in component.pins.values():
            if abs(point.x - pin.position.x) < 5 and abs(point.y - pin.position.y) < 5:
                return True
        return False

    def _get_pin_positions(self, net, context: SchematicContext) -> List[Point]:
        """Get all pin positions for a net."""
        positions = []
        for comp_ref, pin_num in net.pins:
            component = context.components.get(comp_ref)
            if component:
                pin = component.get_pin(pin_num)
                if pin:
                    positions.append(pin.position)
        return positions
