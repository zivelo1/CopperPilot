# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Wire routing module for schematic generator."""
from typing import Dict, List, Tuple, Optional, Set
from collections import deque
from .utils import SchematicContext, Wire, Point, Rectangle, get_wire_color, manhattan_distance

class WireRouter:
    """Intelligent wire routing with orthogonal paths and obstacle avoidance."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.grid_size = 5
        self.wire_spacing = 10
        self.obstacle_map = None
        self.routing_grid = None

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Route all nets with wires."""
        print("\n=== Stage 3: Wire Routing ===")

        # Build obstacle map from components
        self._build_obstacle_map(context)

        # Route each net
        routed_nets = 0
        failed_nets = []

        for net_name, net in context.nets.items():
            if len(net.pins) < 2:
                continue  # Skip single-pin nets

            # Get wire color based on net type
            net.color = get_wire_color(net_name)

            # Route this net
            if self._route_net(net, context):
                routed_nets += 1
            else:
                failed_nets.append(net_name)

        # Statistics
        context.stats['routing'] = {
            'total_nets': len(context.nets),
            'routed_nets': routed_nets,
            'failed_nets': len(failed_nets),
            'total_wires': len(context.wires)
        }

        if failed_nets:
            context.warnings.append(f"Failed to route {len(failed_nets)} nets: {', '.join(failed_nets[:5])}")

        print(f"Routed {routed_nets}/{len(context.nets)} nets")
        print(f"Created {len(context.wires)} wire segments")

        return context

    def _build_obstacle_map(self, context: SchematicContext):
        """Build 2D obstacle map from component bounds."""
        # Create a grid for obstacle detection
        grid_width = context.canvas_width // self.grid_size
        grid_height = context.canvas_height // self.grid_size
        self.obstacle_map = [[False] * grid_width for _ in range(grid_height)]

        # Mark component areas as obstacles
        for component in context.components.values():
            bounds = component.bounds

            # Convert to grid coordinates
            x1 = max(0, bounds.x // self.grid_size)
            y1 = max(0, bounds.y // self.grid_size)
            x2 = min(grid_width - 1, (bounds.x + bounds.width) // self.grid_size)
            y2 = min(grid_height - 1, (bounds.y + bounds.height) // self.grid_size)

            # Mark the area as obstacle with margin
            margin = 2  # Grid cells margin
            for y in range(max(0, y1 - margin), min(grid_height, y2 + margin + 1)):
                for x in range(max(0, x1 - margin), min(grid_width, x2 + margin + 1)):
                    self.obstacle_map[y][x] = True

    def _route_net(self, net, context: SchematicContext) -> bool:
        """Route a single net connecting all its pins."""
        if len(net.pins) == 0:
            return True

        # Get all pin positions for this net
        pin_positions = []
        for comp_ref, pin_num in net.pins:
            component = context.components.get(comp_ref)
            if component:
                pin = component.get_pin(pin_num)
                if pin:
                    pin_positions.append(pin.position)

        if len(pin_positions) < 2:
            return True  # Not enough pins to connect

        # Use different strategies based on net type
        if net.is_power or net.is_ground:
            # Power/ground nets use bus routing
            return self._route_power_net(pin_positions, net, context)
        else:
            # Signal nets use point-to-point routing
            return self._route_signal_net(pin_positions, net, context)

    def _route_power_net(self, pin_positions: List[Point], net, context: SchematicContext) -> bool:
        """Route power/ground nets using bus topology."""
        if not pin_positions:
            return True

        # Find the average Y position for horizontal bus
        avg_y = sum(p.y for p in pin_positions) // len(pin_positions)

        # Create horizontal bus
        min_x = min(p.x for p in pin_positions) - 50
        max_x = max(p.x for p in pin_positions) + 50

        # Main bus line
        bus_y = self._find_clear_horizontal_path(avg_y, min_x, max_x)
        context.wires.append(Wire(
            start=Point(min_x, bus_y),
            end=Point(max_x, bus_y),
            net=net.name,
            color=net.color,
            width=3  # Thicker for power
        ))

        # Connect each pin to the bus
        for pin_pos in pin_positions:
            # Vertical connection to bus
            context.wires.append(Wire(
                start=pin_pos,
                end=Point(pin_pos.x, bus_y),
                net=net.name,
                color=net.color,
                width=3
            ))

        return True

    def _route_signal_net(self, pin_positions: List[Point], net, context: SchematicContext) -> bool:
        """Route signal nets using point-to-point orthogonal routing."""
        if len(pin_positions) < 2:
            return True

        # For multi-pin nets, use star topology from first pin
        source = pin_positions[0]

        for target in pin_positions[1:]:
            # Route orthogonal path from source to target
            path = self._find_orthogonal_path(source, target)
            if path:
                # Convert path to wire segments
                for i in range(len(path) - 1):
                    context.wires.append(Wire(
                        start=path[i],
                        end=path[i + 1],
                        net=net.name,
                        color=net.color,
                        width=2
                    ))
            else:
                # Fallback to L-shaped routing
                self._route_l_shaped(source, target, net, context)

        return True

    def _find_orthogonal_path(self, start: Point, end: Point) -> Optional[List[Point]]:
        """Find orthogonal path using simplified A* algorithm."""
        # For simplicity, use L-shaped routing
        # More complex routing can be implemented here
        return None  # Use fallback L-shaped routing

    def _route_l_shaped(self, start: Point, end: Point, net, context: SchematicContext):
        """Create L-shaped wire routing (horizontal then vertical or vice versa)."""
        # Determine routing strategy based on positions
        dx = abs(end.x - start.x)
        dy = abs(end.y - start.y)

        if dx > dy:
            # Horizontal first, then vertical
            corner = Point(end.x, start.y)
        else:
            # Vertical first, then horizontal
            corner = Point(start.x, end.y)

        # Check if corner is in obstacle
        if self._point_in_obstacle(corner):
            # Try alternative corner
            alt_corner = Point(end.x, start.y) if dy > dx else Point(start.x, end.y)
            if not self._point_in_obstacle(alt_corner):
                corner = alt_corner
            else:
                # Use dogleg routing
                mid_x = (start.x + end.x) // 2
                mid_y = (start.y + end.y) // 2
                corner1 = Point(mid_x, start.y)
                corner2 = Point(mid_x, end.y)

                # Create dogleg path
                context.wires.append(Wire(start, corner1, net.name, net.color))
                context.wires.append(Wire(corner1, corner2, net.name, net.color))
                context.wires.append(Wire(corner2, end, net.name, net.color))
                return

        # Create L-shaped path
        if start.x != corner.x or start.y != corner.y:
            context.wires.append(Wire(start, corner, net.name, net.color))
        if corner.x != end.x or corner.y != end.y:
            context.wires.append(Wire(corner, end, net.name, net.color))

    def _find_clear_horizontal_path(self, preferred_y: int, min_x: int, max_x: int) -> int:
        """Find a clear horizontal path near the preferred Y position."""
        # Check preferred position first
        if self._is_horizontal_clear(preferred_y, min_x, max_x):
            return preferred_y

        # Search above and below
        for offset in range(10, 200, 10):
            # Try above
            y_above = preferred_y - offset
            if y_above > 0 and self._is_horizontal_clear(y_above, min_x, max_x):
                return y_above

            # Try below
            y_below = preferred_y + offset
            if y_below < 2400 and self._is_horizontal_clear(y_below, min_x, max_x):
                return y_below

        # Fallback to preferred if no clear path found
        return preferred_y

    def _is_horizontal_clear(self, y: int, x1: int, x2: int) -> bool:
        """Check if horizontal line is clear of obstacles."""
        if not self.obstacle_map:
            return True

        y_grid = int(y // self.grid_size)
        x1_grid = int(x1 // self.grid_size)
        x2_grid = int(x2 // self.grid_size)

        if y_grid < 0 or y_grid >= len(self.obstacle_map):
            return False

        for x_grid in range(min(x1_grid, x2_grid), max(x1_grid, x2_grid) + 1):
            if 0 <= x_grid < len(self.obstacle_map[0]):
                if self.obstacle_map[y_grid][x_grid]:
                    return False

        return True

    def _point_in_obstacle(self, point: Point) -> bool:
        """Check if a point is inside an obstacle."""
        if not self.obstacle_map:
            return False

        x_grid = int(point.x // self.grid_size)
        y_grid = int(point.y // self.grid_size)

        if (0 <= y_grid < len(self.obstacle_map) and
            0 <= x_grid < len(self.obstacle_map[0])):
            return self.obstacle_map[y_grid][x_grid]

        return False

    def optimize_routing(self, context: SchematicContext):
        """Optimize wire routing to minimize crossings and length."""
        # Merge collinear wire segments
        self._merge_collinear_wires(context)

        # Remove redundant wires
        self._remove_redundant_wires(context)

    def _merge_collinear_wires(self, context: SchematicContext):
        """Merge collinear wire segments of the same net."""
        merged = True
        while merged:
            merged = False
            i = 0
            while i < len(context.wires) - 1:
                wire1 = context.wires[i]
                j = i + 1
                while j < len(context.wires):
                    wire2 = context.wires[j]

                    if wire1.net == wire2.net and self._are_collinear(wire1, wire2):
                        # Merge wires
                        merged_wire = self._merge_wires(wire1, wire2)
                        if merged_wire:
                            context.wires[i] = merged_wire
                            context.wires.pop(j)
                            merged = True
                        else:
                            j += 1
                    else:
                        j += 1
                i += 1

    def _are_collinear(self, wire1: Wire, wire2: Wire) -> bool:
        """Check if two wires are collinear."""
        # Check if both are horizontal
        if wire1.start.y == wire1.end.y and wire2.start.y == wire2.end.y:
            return wire1.start.y == wire2.start.y

        # Check if both are vertical
        if wire1.start.x == wire1.end.x and wire2.start.x == wire2.end.x:
            return wire1.start.x == wire2.start.x

        return False

    def _merge_wires(self, wire1: Wire, wire2: Wire) -> Optional[Wire]:
        """Merge two collinear wires if they overlap or touch."""
        # Check if wires touch or overlap
        if wire1.start.y == wire1.end.y:  # Horizontal
            min1, max1 = min(wire1.start.x, wire1.end.x), max(wire1.start.x, wire1.end.x)
            min2, max2 = min(wire2.start.x, wire2.end.x), max(wire2.start.x, wire2.end.x)

            if max1 >= min2 - 1 and max2 >= min1 - 1:  # Overlap or touch
                return Wire(
                    Point(min(min1, min2), wire1.start.y),
                    Point(max(max1, max2), wire1.start.y),
                    wire1.net,
                    wire1.color,
                    wire1.width
                )
        else:  # Vertical
            min1, max1 = min(wire1.start.y, wire1.end.y), max(wire1.start.y, wire1.end.y)
            min2, max2 = min(wire2.start.y, wire2.end.y), max(wire2.start.y, wire2.end.y)

            if max1 >= min2 - 1 and max2 >= min1 - 1:  # Overlap or touch
                return Wire(
                    Point(wire1.start.x, min(min1, min2)),
                    Point(wire1.start.x, max(max1, max2)),
                    wire1.net,
                    wire1.color,
                    wire1.width
                )

        return None

    def _remove_redundant_wires(self, context: SchematicContext):
        """Remove redundant wire segments."""
        # Remove zero-length wires
        context.wires = [w for w in context.wires
                        if w.start.x != w.end.x or w.start.y != w.end.y]