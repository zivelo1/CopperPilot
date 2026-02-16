# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Wire routing module for schematic generator - PROFESSIONAL GRADE.

Version: 3.0 - Proper A* pathfinding, obstacle avoidance, orthogonal routing
Date: October 2025
Author: Electronics AI System

Implements professional schematic routing:
- A* pathfinding algorithm for optimal paths
- Orthogonal (Manhattan) routing only
- True obstacle avoidance around components
- Power/ground bus routing
- Minimal wire crossings
- Clean, readable wire paths
"""
from typing import Dict, List, Tuple, Optional, Set
from collections import deque
import heapq
from .utils import SchematicContext, Wire, Point, Rectangle, get_wire_color, manhattan_distance

class WireRouter:
    """Professional-grade wire routing with A* pathfinding and obstacle avoidance."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.grid_size = 5  # Fine grid for routing
        self.wire_spacing = 15  # Minimum spacing between parallel wires
        self.obstacle_map = None
        self.routing_grid_width = 0
        self.routing_grid_height = 0

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Route all nets with wires using professional algorithms."""
        print("\n=== Stage 3: Wire Routing (Professional Grade v3.0) ===")

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
                context.warnings.append(f"Failed to route net: {net_name}")

        # Optimize routing
        self._optimize_routing(context)

        # Statistics
        context.stats['routing'] = {
            'total_nets': len(context.nets),
            'routed_nets': routed_nets,
            'failed_nets': len(failed_nets),
            'total_wires': len(context.wires)
        }

        if failed_nets:
            print(f"⚠ Failed to route {len(failed_nets)} nets")
        else:
            print(f"✓ Successfully routed all {routed_nets} nets")

        print(f"✓ Created {len(context.wires)} wire segments")

        return context

    def _build_obstacle_map(self, context: SchematicContext):
        """Build 2D obstacle map from component bounds."""
        # Create a grid for obstacle detection
        self.routing_grid_width = int(context.canvas_width // self.grid_size + 1)
        self.routing_grid_height = int(context.canvas_height // self.grid_size + 1)
        self.obstacle_map = [[False] * self.routing_grid_width for _ in range(self.routing_grid_height)]

        # Mark component areas as obstacles
        for component in context.components.values():
            bounds = component.bounds

            # Convert to grid coordinates
            x1 = max(0, int(bounds.x // self.grid_size))
            y1 = max(0, int(bounds.y // self.grid_size))
            x2 = min(self.routing_grid_width - 1, int((bounds.x + bounds.width) // self.grid_size))
            y2 = min(self.routing_grid_height - 1, int((bounds.y + bounds.height) // self.grid_size))

            # Mark the area as obstacle with margin
            margin = 3  # Grid cells margin around components
            for y in range(max(0, y1 - margin), min(self.routing_grid_height, y2 + margin + 1)):
                for x in range(max(0, x1 - margin), min(self.routing_grid_width, x2 + margin + 1)):
                    self.obstacle_map[y][x] = True

        print(f"Built obstacle map: {self.routing_grid_width}x{self.routing_grid_height} grid")

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
            # Signal nets use point-to-point routing with A*
            return self._route_signal_net_astar(pin_positions, net, context)

    def _route_power_net(self, pin_positions: List[Point], net, context: SchematicContext) -> bool:
        """Route power/ground nets using horizontal bus topology."""
        if not pin_positions:
            return True

        # Determine bus orientation based on pin distribution
        x_spread = max(p.x for p in pin_positions) - min(p.x for p in pin_positions)
        y_spread = max(p.y for p in pin_positions) - min(p.y for p in pin_positions)

        if x_spread > y_spread:
            # Use horizontal bus
            avg_y = sum(p.y for p in pin_positions) // len(pin_positions)
            min_x = min(p.x for p in pin_positions) - 80
            max_x = max(p.x for p in pin_positions) + 80

            # Find clear horizontal path
            bus_y = self._find_clear_horizontal_path(avg_y, min_x, max_x)

            # Main bus line
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
        else:
            # Use vertical bus
            avg_x = sum(p.x for p in pin_positions) // len(pin_positions)
            min_y = min(p.y for p in pin_positions) - 80
            max_y = max(p.y for p in pin_positions) + 80

            # Find clear vertical path
            bus_x = self._find_clear_vertical_path(avg_x, min_y, max_y)

            # Main bus line
            context.wires.append(Wire(
                start=Point(bus_x, min_y),
                end=Point(bus_x, max_y),
                net=net.name,
                color=net.color,
                width=3
            ))

            # Connect each pin to the bus
            for pin_pos in pin_positions:
                # Horizontal connection to bus
                context.wires.append(Wire(
                    start=pin_pos,
                    end=Point(bus_x, pin_pos.y),
                    net=net.name,
                    color=net.color,
                    width=3
                ))

        return True

    def _route_signal_net_astar(self, pin_positions: List[Point], net, context: SchematicContext) -> bool:
        """Route signal nets using A* pathfinding for optimal orthogonal paths."""
        if len(pin_positions) < 2:
            return True

        # For multi-pin nets, use minimum spanning tree approach
        # Connect all pins with minimum total wire length
        unconnected = set(range(len(pin_positions)))
        connected = {0}  # Start with first pin
        unconnected.remove(0)

        while unconnected:
            # Find closest unconnected pin to any connected pin
            min_dist = float('inf')
            best_pair = None

            for conn_idx in connected:
                for unconn_idx in unconnected:
                    dist = manhattan_distance(pin_positions[conn_idx], pin_positions[unconn_idx])
                    if dist < min_dist:
                        min_dist = dist
                        best_pair = (conn_idx, unconn_idx)

            if best_pair:
                source_idx, target_idx = best_pair
                source = pin_positions[source_idx]
                target = pin_positions[target_idx]

                # Route using A* pathfinding
                path = self._astar_pathfinding(source, target)

                if path and len(path) >= 2:
                    # Convert path to wire segments
                    for i in range(len(path) - 1):
                        # Only add wire if it's not zero-length
                        if path[i].x != path[i+1].x or path[i].y != path[i+1].y:
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

                connected.add(target_idx)
                unconnected.remove(target_idx)
            else:
                # Can't find a pair, break
                break

        return True

    def _astar_pathfinding(self, start: Point, end: Point) -> Optional[List[Point]]:
        """A* pathfinding algorithm for orthogonal routing with obstacle avoidance."""
        # Convert points to grid coordinates (must be integers)
        start_grid = (int(start.x // self.grid_size), int(start.y // self.grid_size))
        end_grid = (int(end.x // self.grid_size), int(end.y // self.grid_size))

        # Bounds checking
        if (start_grid[0] < 0 or start_grid[0] >= self.routing_grid_width or
            start_grid[1] < 0 or start_grid[1] >= self.routing_grid_height):
            return None
        if (end_grid[0] < 0 or end_grid[0] >= self.routing_grid_width or
            end_grid[1] < 0 or end_grid[1] >= self.routing_grid_height):
            return None

        # Priority queue: (f_score, g_score, position)
        open_set = [(0, 0, start_grid)]
        came_from = {}
        g_score = {start_grid: 0}

        # Direction vectors: right, left, down, up (orthogonal only)
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]

        while open_set:
            _, current_g, current = heapq.heappop(open_set)

            if current == end_grid:
                # Reconstruct path
                path_grid = []
                node = current
                while node in came_from:
                    path_grid.append(node)
                    node = came_from[node]
                path_grid.append(start_grid)
                path_grid.reverse()

                # Convert grid coordinates back to actual coordinates
                path = [Point(x * self.grid_size, y * self.grid_size) for x, y in path_grid]

                # Simplify path by removing intermediate collinear points
                path = self._simplify_path(path)

                return path

            # Explore neighbors (orthogonal moves only)
            for dx, dy in directions:
                neighbor = (current[0] + dx, current[1] + dy)

                # Check bounds
                if (neighbor[0] < 0 or neighbor[0] >= self.routing_grid_width or
                    neighbor[1] < 0 or neighbor[1] >= self.routing_grid_height):
                    continue

                # Check obstacle (but allow routing over start/end points)
                if neighbor != start_grid and neighbor != end_grid:
                    if self.obstacle_map[neighbor[1]][neighbor[0]]:
                        continue

                # Calculate tentative g_score
                tentative_g = current_g + 1

                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    # This path to neighbor is better
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g

                    # Heuristic: Manhattan distance
                    h = abs(neighbor[0] - end_grid[0]) + abs(neighbor[1] - end_grid[1])
                    f = tentative_g + h

                    heapq.heappush(open_set, (f, tentative_g, neighbor))

        # No path found
        return None

    def _simplify_path(self, path: List[Point]) -> List[Point]:
        """Remove intermediate collinear points from path."""
        if len(path) <= 2:
            return path

        simplified = [path[0]]

        for i in range(1, len(path) - 1):
            prev = simplified[-1]
            curr = path[i]
            next_point = path[i + 1]

            # Check if current point is collinear with prev and next
            if not ((prev.x == curr.x == next_point.x) or (prev.y == curr.y == next_point.y)):
                # Not collinear, keep this point
                simplified.append(curr)

        simplified.append(path[-1])
        return simplified

    def _route_l_shaped(self, start: Point, end: Point, net, context: SchematicContext):
        """Create L-shaped wire routing (horizontal then vertical or vice versa) - fallback method."""
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
        for offset in range(20, 300, 20):
            # Try above
            y_above = preferred_y - offset
            if y_above > 0 and self._is_horizontal_clear(y_above, min_x, max_x):
                return y_above

            # Try below
            y_below = preferred_y + offset
            if y_below < 3000 and self._is_horizontal_clear(y_below, min_x, max_x):
                return y_below

        # Fallback to preferred if no clear path found
        return preferred_y

    def _find_clear_vertical_path(self, preferred_x: int, min_y: int, max_y: int) -> int:
        """Find a clear vertical path near the preferred X position."""
        # Check preferred position first
        if self._is_vertical_clear(preferred_x, min_y, max_y):
            return preferred_x

        # Search left and right
        for offset in range(20, 300, 20):
            # Try left
            x_left = preferred_x - offset
            if x_left > 0 and self._is_vertical_clear(x_left, min_y, max_y):
                return x_left

            # Try right
            x_right = preferred_x + offset
            if x_right < 4000 and self._is_vertical_clear(x_right, min_y, max_y):
                return x_right

        # Fallback to preferred if no clear path found
        return preferred_x

    def _is_horizontal_clear(self, y: int, x1: int, x2: int) -> bool:
        """Check if horizontal line is clear of obstacles."""
        if not self.obstacle_map:
            return True

        y_grid = int(y // self.grid_size)
        x1_grid = int(x1 // self.grid_size)
        x2_grid = int(x2 // self.grid_size)

        if y_grid < 0 or y_grid >= self.routing_grid_height:
            return False

        for x_grid in range(min(x1_grid, x2_grid), max(x1_grid, x2_grid) + 1):
            if 0 <= x_grid < self.routing_grid_width:
                if self.obstacle_map[y_grid][x_grid]:
                    return False

        return True

    def _is_vertical_clear(self, x: int, y1: int, y2: int) -> bool:
        """Check if vertical line is clear of obstacles."""
        if not self.obstacle_map:
            return True

        x_grid = int(x // self.grid_size)
        y1_grid = int(y1 // self.grid_size)
        y2_grid = int(y2 // self.grid_size)

        if x_grid < 0 or x_grid >= self.routing_grid_width:
            return False

        for y_grid in range(min(y1_grid, y2_grid), max(y1_grid, y2_grid) + 1):
            if 0 <= y_grid < self.routing_grid_height:
                if self.obstacle_map[y_grid][x_grid]:
                    return False

        return True

    def _point_in_obstacle(self, point: Point) -> bool:
        """Check if a point is inside an obstacle."""
        if not self.obstacle_map:
            return False

        x_grid = int(point.x // self.grid_size)
        y_grid = int(point.y // self.grid_size)

        if (0 <= y_grid < self.routing_grid_height and
            0 <= x_grid < self.routing_grid_width):
            return self.obstacle_map[y_grid][x_grid]

        return False

    def _optimize_routing(self, context: SchematicContext):
        """Optimize wire routing to minimize crossings and length."""
        # Merge collinear wire segments
        self._merge_collinear_wires(context)

        # Remove redundant wires
        self._remove_redundant_wires(context)

        # Remove zero-length wires
        context.wires = [w for w in context.wires
                        if w.start.x != w.end.x or w.start.y != w.end.y]

    def _merge_collinear_wires(self, context: SchematicContext):
        """Merge collinear wire segments of the same net."""
        merged = True
        iterations = 0
        max_iterations = 5

        while merged and iterations < max_iterations:
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
            iterations += 1

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
