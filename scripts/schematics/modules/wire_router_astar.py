# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Wire routing module with A* pathfinding to avoid component collisions."""
from typing import Dict, List, Tuple, Optional, Set
from .utils import SchematicContext, Wire, Point, Rectangle, Component, get_wire_color
import heapq

class WireRouter:
    """A* pathfinding wire router with obstacle avoidance."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.grid_size = 20  # Grid resolution for pathfinding (optimized balance)
        self.obstacles = []

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Route all nets using A* pathfinding with obstacle avoidance."""
        print("\n=== Stage 3: Wire Routing (A* Pathfinding) ===")

        routed = 0
        total_wires = 0
        skipped_nets = 0
        failed_routes = 0

        # Build obstacle map from component bounds
        self._build_obstacle_map(context)
        print(f"  Built obstacle map with {len(self.obstacles)} components")

        for net_name, net in context.nets.items():
            if len(net.pins) < 2:
                continue

            net.color = get_wire_color(net_name)
            pin_positions = self._get_pin_positions(net, context)

            if len(pin_positions) < 2:
                skipped_nets += 1
                if skipped_nets <= 3:
                    print(f"⚠️  Net '{net_name}' has {len(net.pins)} pins but only {len(pin_positions)} positions found")
                continue

            # Route using star topology with A* pathfinding
            hub = pin_positions[0]
            net_wires = 0

            for pin_pos in pin_positions[1:]:
                # Find path from pin to hub avoiding obstacles
                path = self._find_path(pin_pos, hub, context)

                if path and len(path) >= 2 and failed_routes < 5:
                    print(f"    ✓ Found path for {net_name}: {len(path)} points")

                if path and len(path) >= 2:
                    # Convert path to wire segments
                    for i in range(len(path) - 1):
                        context.wires.append(Wire(
                            start=path[i],
                            end=path[i + 1],
                            net=net.name,
                            color=net.color,
                            width=2
                        ))
                        total_wires += 1
                        net_wires += 1
                else:
                    failed_routes += 1
                    if failed_routes <= 5:
                        print(f"    ✗ Path failed for {net_name}, using fallback")
                    # Fallback: direct L-shaped connection if pathfinding fails
                    if pin_pos.x != hub.x:
                        context.wires.append(Wire(
                            start=pin_pos,
                            end=Point(hub.x, pin_pos.y),
                            net=net.name,
                            color=net.color,
                            width=2
                        ))
                        total_wires += 1
                        net_wires += 1

                    if pin_pos.y != hub.y:
                        context.wires.append(Wire(
                            start=Point(hub.x, pin_pos.y),
                            end=hub,
                            net=net.name,
                            color=net.color,
                            width=2
                        ))
                        total_wires += 1
                        net_wires += 1

            routed += 1

        context.stats['routing'] = {
            'total_nets': len(context.nets),
            'routed_nets': routed,
            'total_wires': total_wires,
            'failed_routes': failed_routes
        }

        if failed_routes > 0:
            print(f"⚠️  {failed_routes} routes used fallback (direct) paths")
        print(f"✓ Routed {routed} nets with {total_wires} wire segments")

        return context

    def _build_obstacle_map(self, context: SchematicContext):
        """Build map of obstacles (component bounds) for pathfinding."""
        self.obstacles = []

        for component in context.components.values():
            # Store component bounds as obstacle
            # Add small margin to avoid wires touching component edges
            margin = 25 # Increased margin for better clearance (to reduce wire crossing components)
            obstacle = Rectangle(
                x=component.bounds.x - margin,
                y=component.bounds.y - margin,
                width=component.bounds.width + 2 * margin,
                height=component.bounds.height + 2 * margin
            )
            self.obstacles.append((component, obstacle))

    def _find_path(self, start: Point, goal: Point, context: SchematicContext) -> Optional[List[Point]]:
        """Find path from start to goal using A* algorithm."""

        # Snap points to grid
        start_grid = self._snap_to_grid(start)
        goal_grid = self._snap_to_grid(goal)

        # A* algorithm
        open_set = []
        heapq.heappush(open_set, (0, start_grid))
        came_from = {}
        g_score = {start_grid: 0}
        f_score = {start_grid: self._heuristic(start_grid, goal_grid)}
        closed_set = set()

        max_iterations = 25000  # Prevent infinite loops (increased for complex paths)
        iterations = 0

        while open_set and iterations < max_iterations:
            iterations += 1
            current = heapq.heappop(open_set)[1]

            if self._points_equal(current, goal_grid):
                # Reconstruct path
                path = [goal]
                while current in came_from:
                    current = came_from[current]
                    if not self._points_equal(current, start_grid):
                        path.append(Point(current[0], current[1]))
                path.append(start)
                path.reverse()
                return self._simplify_path(path)

            closed_set.add(current)

            # Check neighbors (4-directional: up, down, left, right)
            for neighbor in self._get_neighbors(current, context):
                if neighbor in closed_set:
                    continue

                # Check if neighbor intersects obstacles (but allow if it's near the goal or start)
                if not self._is_near_endpoint(neighbor, start_grid, goal_grid):
                    if self._intersects_obstacle(Point(neighbor[0], neighbor[1]), context):
                        continue

                tentative_g = g_score[current] + self._distance(current, neighbor)

                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f_score[neighbor] = tentative_g + self._heuristic(neighbor, goal_grid)
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))

        # No path found
        return None

    def _snap_to_grid(self, point: Point) -> Tuple[int, int]:
        """Snap point to grid."""
        return (
            (point.x // self.grid_size) * self.grid_size,
            (point.y // self.grid_size) * self.grid_size
        )

    def _points_equal(self, p1: Tuple[int, int], p2: Tuple[int, int]) -> bool:
        """Check if two grid points are equal."""
        return abs(p1[0] - p2[0]) < self.grid_size and abs(p1[1] - p2[1]) < self.grid_size

    def _is_near_endpoint(self, point: Tuple[int, int], start: Tuple[int, int], goal: Tuple[int, int]) -> bool:
        """Check if point is near start or goal (within a dynamic pixel range based on grid_size)."""
        dynamic_distance = self.grid_size * 2 # Reverted to original distance
        dist_to_start = abs(point[0] - start[0]) + abs(point[1] - start[1])
        dist_to_goal = abs(point[0] - goal[0]) + abs(point[1] - goal[1])
        return dist_to_start < dynamic_distance or dist_to_goal < dynamic_distance

    def _heuristic(self, p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
        """Manhattan distance heuristic."""
        return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

    def _distance(self, p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
        """Distance between two grid points."""
        return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

    def _get_neighbors(self, point: Tuple[int, int], context: SchematicContext) -> List[Tuple[int, int]]:
        """Get valid neighbor grid points (4-directional)."""
        x, y = point
        neighbors = []

        for dx, dy in [(self.grid_size, 0), (-self.grid_size, 0), (0, self.grid_size), (0, -self.grid_size)]:
            nx, ny = x + dx, y + dy

            # Check bounds
            if 0 <= nx < context.canvas_width and 0 <= ny < context.canvas_height:
                neighbors.append((nx, ny))

        return neighbors

    def _intersects_obstacle(self, point: Point, context: SchematicContext) -> bool:
        """Check if point intersects any obstacle."""
        for component, obstacle in self.obstacles:
            if (obstacle.x <= point.x <= obstacle.x + obstacle.width and
                obstacle.y <= point.y <= obstacle.y + obstacle.height):
                return True
        return False

    def _simplify_path(self, path: List[Point]) -> List[Point]:
        """Simplify path by removing collinear points."""
        if len(path) <= 2:
            return path

        simplified = [path[0]]

        for i in range(1, len(path) - 1):
            prev = simplified[-1]
            curr = path[i]
            next_p = path[i + 1]

            # Check if curr is collinear with prev and next
            if not self._is_collinear(prev, curr, next_p):
                simplified.append(curr)

        simplified.append(path[-1])
        return simplified

    def _is_collinear(self, p1: Point, p2: Point, p3: Point) -> bool:
        """Check if three points are collinear (on same line)."""
        # Points are collinear if they're on the same horizontal or vertical line
        return (p1.x == p2.x == p3.x) or (p1.y == p2.y == p3.y)

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
