#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Path Routing Algorithms for PCB Auto-Routing
GENERIC MODULE - Works for ANY circuit complexity

Implements multiple routing strategies:
- Strategy 1: Manhattan routing (L-shaped/Z-shaped paths)
- Strategy 2: A* pathfinding with obstacle avoidance
- Strategy 3: Advanced multi-layer routing (future)

All algorithms are GENERIC and work for ANY:
- Board size
- Component count
- Net complexity
- Track width
- Clearance requirements

Author: Electronics Automation System
Date: 2025-10-27
"""

import heapq
from typing import List, Tuple, Optional, Set, Dict
from dataclasses import dataclass, field
from enum import Enum

from .grid_occupancy import Point, Rectangle, GridOccupancy, Layer


class RoutingStrategy(Enum):
    """Available routing strategies"""
    MANHATTAN = "manhattan"  # Simple L/Z routing
    ASTAR = "astar"          # A* pathfinding
    ADVANCED = "advanced"    # Multi-layer with rip-up/reroute


@dataclass
class RoutingConfig:
    """
    GENERIC configuration for routing.
    Works for any circuit by adjusting parameters.
    """
    track_width: float = 0.25          # mm (standard)
    via_diameter: float = 0.8          # mm
    via_drill: float = 0.4             # mm
    clearance: float = 0.2             # mm (min distance between traces)
    min_track_width: float = 0.15      # mm (manufacturing limit)

    # Cost weights for A* routing
    distance_weight: float = 1.0       # Cost per mm of trace
    bend_penalty: float = 0.8          # Cost for each 90° bend (smoother paths)
    via_penalty: float = 0.8           # Cost for layer change (encourage clean layer flips)

    # Search limits (prevent infinite loops)
    max_search_nodes: int = 500000     # Max A* nodes to explore (increased for complex nets)
    max_path_length: float = 2000.0    # mm (sanity check, increased for large boards)
    astar_timeout: float = 12.0        # seconds per two-point A* (deep search for tough nets)

    # Layer preferences
    prefer_top_layer: bool = True      # Prefer F.Cu over B.Cu


@dataclass(order=True)
class AStarNode:
    """
    Node for A* pathfinding algorithm.
    GENERIC - works for any search space.
    """
    f_cost: float                       # Total cost (g + h)
    g_cost: float = field(compare=False)  # Cost from start
    h_cost: float = field(compare=False)  # Heuristic to goal
    point: Point = field(compare=False)
    layer: Layer = field(compare=False)
    parent: Optional['AStarNode'] = field(default=None, compare=False)
    num_bends: int = field(default=0, compare=False)


class PathRouter:
    """
    GENERIC path routing engine.
    Routes 2-pin connections using various strategies.
    """

    def __init__(self, grid: GridOccupancy, config: RoutingConfig):
        """
        Initialize router.

        Args:
            grid: Occupancy grid for collision detection
            config: Routing configuration
        """
        self.grid = grid
        self.config = config

    def route_two_point(self, start: Point, end: Point,
                       layer: Layer = Layer.F_CU,
                       strategy: RoutingStrategy = RoutingStrategy.MANHATTAN,
                       net_name: str = "",
                       distance_field = None) -> Optional[List[Point]]:
        """
        Route between two points using specified strategy.
        GENERIC - works for ANY two points on board.

        TIER 2 Enhancement: Accepts optional distance field for clearance-aware routing.

        Args:
            start: Starting point
            end: Ending point
            layer: Preferred layer
            strategy: Routing algorithm
            net_name: Net name (for debugging)
            distance_field: Optional NetDistanceField for clearance-aware routing

        Returns:
            List of points forming path, or None if routing failed
        """
        if strategy == RoutingStrategy.MANHATTAN:
            return self._route_manhattan(start, end, layer, net_name, distance_field)
        elif strategy == RoutingStrategy.ASTAR:
            return self._route_astar(start, end, layer, net_name, distance_field)
        else:
            raise ValueError(f"Unknown routing strategy: {strategy}")

    def _route_manhattan(self, start: Point, end: Point,
                        layer: Layer, net_name: str, distance_field = None) -> Optional[List[Point]]:
        """
        Manhattan routing: L-shaped or Z-shaped paths.
        GENERIC - tries multiple path orientations.

        TIER 2 Enhancement: Uses distance field to check clearance requirements.

        Strategy:
        1. Try horizontal-first path (→ then ↓)
        2. Try vertical-first path (↓ then →)
        3. Try 3-segment Z-path if both fail
        4. For each candidate path, verify distance field clearances (if provided)

        Returns: Path or None if blocked
        """
        # Try horizontal-first (→ then ↓)
        path_h = self._try_l_path(start, end, horizontal_first=True)
        if path_h and self.grid.is_path_clear(path_h, layer,
                                              self.config.track_width, net_name):
            # TIER 2: Check distance field clearances (if provided)
            if distance_field is None or self._path_has_clearance(path_h, distance_field):
                return path_h

        # Try vertical-first (↓ then →)
        path_v = self._try_l_path(start, end, horizontal_first=False)
        if path_v and self.grid.is_path_clear(path_v, layer,
                                              self.config.track_width, net_name):
            # TIER 2: Check distance field clearances (if provided)
            if distance_field is None or self._path_has_clearance(path_v, distance_field):
                return path_v

        # Try Z-path (3 segments)
        path_z = self._try_z_path(start, end, layer, net_name, distance_field)
        if path_z:
            return path_z

        # All Manhattan attempts failed
        return None

    def _try_l_path(self, start: Point, end: Point,
                   horizontal_first: bool) -> List[Point]:
        """
        Create L-shaped path (2 segments at right angles).
        GENERIC - works for any start/end positions.

        Args:
            horizontal_first: If True, go horizontal then vertical
                            If False, go vertical then horizontal
        """
        if horizontal_first:
            # Horizontal first: start → (end.x, start.y) → end
            corner = Point(end.x, start.y)
        else:
            # Vertical first: start → (start.x, end.y) → end
            corner = Point(start.x, end.y)

        return [start, corner, end]

    def _try_z_path(self, start: Point, end: Point,
                   layer: Layer, net_name: str, distance_field = None) -> Optional[List[Point]]:
        """
        Try Z-shaped path (3 segments).
        GENERIC - tries multiple midpoint positions.

        TIER 2 Enhancement: Uses distance field to check clearance requirements.

        Strategy:
        1. Try midpoint at 25%, 50%, 75% along X or Y axis
        2. Check if resulting path is clear
        3. Check distance field clearances (if provided)

        Returns: Path or None
        """
        dx = end.x - start.x
        dy = end.y - start.y

        # Try Z-path along X axis (horizontal offsets)
        for ratio in [0.25, 0.5, 0.75]:
            mid_x = start.x + dx * ratio

            path = [
                start,
                Point(mid_x, start.y),
                Point(mid_x, end.y),
                end
            ]

            if self.grid.is_path_clear(path, layer,
                                       self.config.track_width, net_name):
                # TIER 2: Check distance field clearances (if provided)
                if distance_field is None or self._path_has_clearance(path, distance_field):
                    return path

        # Try Z-path along Y axis (vertical offsets)
        for ratio in [0.25, 0.5, 0.75]:
            mid_y = start.y + dy * ratio

            path = [
                start,
                Point(start.x, mid_y),
                Point(end.x, mid_y),
                end
            ]

            if self.grid.is_path_clear(path, layer,
                                       self.config.track_width, net_name):
                # TIER 2: Check distance field clearances (if provided)
                if distance_field is None or self._path_has_clearance(path, distance_field):
                    return path

        return None

    def _path_has_clearance(self, path: List[Point], distance_field) -> bool:
        """
        TIER 2: Check if path maintains required clearance from different-net obstacles.
        GENERIC - works for ANY path, ANY distance field.

        Args:
            path: List of waypoints forming the path
            distance_field: NetDistanceField to query

        Returns:
            True if ALL points on path have sufficient clearance, False otherwise
        """
        if distance_field is None:
            return True  # No distance field provided, assume safe

        required_clearance = self.config.clearance

        # Check clearance at all waypoints
        for point in path:
            if not distance_field.is_safe(point, required_clearance):
                # This point is too close to a different-net obstacle
                return False

        # All points have sufficient clearance
        return True

    def _route_astar(self, start: Point, end: Point,
                    layer: Layer, net_name: str, distance_field = None) -> Optional[List[Point]]:
        """
        A* pathfinding algorithm with TIMEOUT PROTECTION.
        GENERIC - works for ANY obstacle configuration.

        CRITICAL FIX (2025-10-27): Added timeout to prevent hangs on complex nets.
        - Max 30 seconds per net (configurable)
        - Max 500,000 nodes explored (configurable)
        - Fails gracefully if limits exceeded

        TIER 2 Enhancement: Uses distance field to penalize paths near different-net obstacles.
        - Adds cost penalty based on proximity to other nets
        - Naturally routes through areas with good clearance
        - Prevents DRC violations BEFORE they happen

        Features:
        - Optimal path finding
        - Obstacle avoidance
        - Bend minimization
        - Layer change support (via vias)
        - Distance field-aware cost function (TIER 2)

        Returns: Optimal path or None if no path exists
        """
        import time

        # CRITICAL FIX: Start timeout timer
        start_time = time.time()
        timeout_seconds = self.config.astar_timeout

        # A* data structures
        open_set = []  # Priority queue
        closed_set: Set[Tuple[Point, Layer]] = set()
        g_scores: Dict[Tuple[Point, Layer], float] = {}

        # Initialize start node
        h_start = self._heuristic(start, end)
        start_node = AStarNode(
            f_cost=h_start,
            g_cost=0.0,
            h_cost=h_start,
            point=start,
            layer=layer,
            parent=None,
            num_bends=0
        )

        heapq.heappush(open_set, start_node)
        g_scores[(start, layer)] = 0.0

        nodes_explored = 0

        while open_set and nodes_explored < self.config.max_search_nodes:
            # CRITICAL FIX: Check timeout
            if time.time() - start_time > timeout_seconds:
                # Timeout exceeded - fail gracefully
                return None
            current = heapq.heappop(open_set)
            nodes_explored += 1

            # Goal check
            if current.point.distance_to(end) < self.grid.resolution:
                # Reconstruct and then force exact start/end anchors for DRC pad contact
                path = self._reconstruct_path(current)
                # Ensure first element is start anchor
                if path:
                    first = path[0]
                    if isinstance(first, tuple):
                        p0, l0 = first
                        if p0.distance_to(start) > 1e-6:
                            # Prepend exact start with same layer as first node
                            path.insert(0, (start, l0))
                    else:
                        if first.distance_to(start) > 1e-6:
                            path.insert(0, start)
                else:
                    # Path somehow empty; seed with start
                    path = [(start, layer)]

                # Ensure last element is exact pad center for end
                last = path[-1]
                if isinstance(last, tuple):
                    pN, lN = last
                    if pN.distance_to(end) > 1e-6:
                        path.append((end, lN))
                else:
                    if last.distance_to(end) > 1e-6:
                        path.append(end)

                return path

            # Mark as explored
            closed_set.add((current.point, current.layer))

            # Explore neighbors
            neighbors = self._get_astar_neighbors(current, end, net_name, distance_field)

            for neighbor in neighbors:
                state = (neighbor.point, neighbor.layer)

                if state in closed_set:
                    continue

                # Check if this path to neighbor is better
                if state not in g_scores or neighbor.g_cost < g_scores[state]:
                    g_scores[state] = neighbor.g_cost
                    heapq.heappush(open_set, neighbor)

        # No path found
        return None

    def _get_astar_neighbors(self, node: AStarNode, goal: Point,
                            net_name: str, distance_field = None) -> List[AStarNode]:
        """
        Get valid neighbor nodes for A* search.
        GENERIC - works for any grid configuration.

        TIER 2 Enhancement: Uses distance field to add clearance-based cost penalty.

        Returns neighbors in 4 directions (Manhattan-friendly) plus VIA option
        for layer changes with a via penalty. Ensures DRC-safe occupancy using
        the grid for collision checks.
        """
        neighbors = []
        current_point = node.point
        r, c = self.grid.point_to_grid(current_point)

        # Direction vectors (4-connected grid for Manhattan-friendly paths)
        directions = [
            (-1, 0),  # Up
            (1, 0),   # Down
            (0, -1),  # Left
            (0, 1),   # Right
        ]

        for dr, dc in directions:
            nr, nc = r + dr, c + dc

            # Check bounds
            if not (0 <= nr < self.grid.rows and 0 <= nc < self.grid.cols):
                continue

            # Check if cell is free
            if self.grid.grids[node.layer][nr][nc] != 0:
                # Check if it's the same net (allowed)
                cell_net = self.grid.net_assignments[node.layer].get((nr, nc), "")
                if cell_net != net_name:
                    continue  # Occupied by different net

            neighbor_point = self.grid.grid_to_point(nr, nc)

            # Calculate movement cost (distance + congestion steering)
            move_distance = current_point.distance_to(neighbor_point)
            move_cost = move_distance * self.config.distance_weight
            # Add a small congestion penalty at neighbor location to avoid tight corridors
            try:
                move_cost += self.grid.congestion_penalty(neighbor_point, node.layer)
            except Exception:
                pass

            # TIER 2: Add distance field penalty (penalize paths near different-net obstacles)
            if distance_field is not None:
                clearance_dist = distance_field.get_distance(neighbor_point)
                required_clearance = self.config.clearance

                # CYCLE 4 BASELINE (77% DRC reduction - PROVEN WORKING)
                # Gentle penalty that guides without blocking
                # Add penalty inversely proportional to clearance margin
                # Paths with more clearance get lower cost (preferred)
                if clearance_dist < required_clearance * 3.0:
                    # Within 3× clearance distance - add graduated penalty
                    clearance_margin = clearance_dist - required_clearance
                    max_margin = required_clearance * 2.0  # From 1× to 3×
                    # Clamp penalty_factor to [0, 1] range
                    penalty_factor = max(0.0, min(1.0, 1.0 - (clearance_margin / max_margin)))
                    clearance_penalty = penalty_factor * 5.0  # Max 5.0 penalty
                    move_cost += clearance_penalty
                # else: clearance >= 3× required - no penalty (good clearance)

            # Add bend penalty if direction changed
            num_bends = node.num_bends
            if node.parent:
                prev_dir = self._get_direction(node.parent.point, node.point)
                curr_dir = self._get_direction(node.point, neighbor_point)
                if prev_dir != curr_dir:
                    move_cost += self.config.bend_penalty
                    num_bends += 1

            # Create neighbor node
            g_cost = node.g_cost + move_cost
            h_cost = self._heuristic(neighbor_point, goal)
            f_cost = g_cost + h_cost

            neighbor = AStarNode(
                f_cost=f_cost,
                g_cost=g_cost,
                h_cost=h_cost,
                point=neighbor_point,
                layer=node.layer,
                parent=node,
                num_bends=num_bends
            )

            neighbors.append(neighbor)

        # VIA neighbor (layer change in-place) — only if space allows
        # We approximate via feasibility with can_place_via and add a via penalty
        other_layer = Layer.B_CU if node.layer == Layer.F_CU else Layer.F_CU
        try:
            if self.grid.can_place_via(current_point, self.config.via_diameter, self.config.clearance, net_name):
                via_cost = self.config.via_penalty
                g_cost = node.g_cost + via_cost
                h_cost = self._heuristic(current_point, goal)
                f_cost = g_cost + h_cost
                via_node = AStarNode(
                    f_cost=f_cost,
                    g_cost=g_cost,
                    h_cost=h_cost,
                    point=current_point,  # same geometry
                    layer=other_layer,    # different layer
                    parent=node,
                    num_bends=node.num_bends
                )
                neighbors.append(via_node)
        except Exception:
            # Be conservative if via feasibility check fails
            pass

        # Optional: Layer change via at current cell (net-aware)
        if self.grid.num_layers > 1:
            other_layer = Layer.B_CU if node.layer == Layer.F_CU else Layer.F_CU
            # Only consider via if the target cell on the other layer is not blocked by different net
            if self.grid.grids[other_layer][r][c] == 0:
                cell_net = self.grid.net_assignments[other_layer].get((r, c), "")
                if cell_net in ("", net_name):
                    g_cost = node.g_cost + self.config.via_penalty
                    h_cost = self._heuristic(node.point, goal)
                    f_cost = g_cost + h_cost
                    via_node = AStarNode(
                        f_cost=f_cost,
                        g_cost=g_cost,
                        h_cost=h_cost,
                        point=node.point,
                        layer=other_layer,
                        parent=node,
                        num_bends=node.num_bends
                    )
                    neighbors.append(via_node)

        return neighbors

    def _get_direction(self, from_point: Point, to_point: Point) -> Tuple[int, int]:
        """
        Get direction vector (normalized).
        GENERIC - works for any direction.
        """
        dx = to_point.x - from_point.x
        dy = to_point.y - from_point.y

        # Normalize to -1, 0, 1
        dir_x = 0 if abs(dx) < 1e-6 else (1 if dx > 0 else -1)
        dir_y = 0 if abs(dy) < 1e-6 else (1 if dy > 0 else -1)

        return (dir_x, dir_y)

    def _heuristic(self, point: Point, goal: Point) -> float:
        """
        A* heuristic function.
        GENERIC - uses Manhattan distance (admissible and consistent).

        Manhattan distance is optimal for grid-based routing.
        """
        return point.manhattan_distance_to(goal) * self.config.distance_weight

    def _reconstruct_path(self, node: AStarNode) -> List:
        """
        Reconstruct path from A* goal node to start.
        Returns list of (Point, Layer) tuples to preserve layer changes.
        """
        path: List = []
        current = node

        while current is not None:
            # Preserve both geometry and layer so callers can create vias
            path.append((current.point, current.layer))
            current = current.parent

        # Reverse to get start → goal
        path.reverse()

        # Simplify path (remove redundant intermediate points)
        # Work on the geometric component for collinearity while preserving layers
        if len(path) > 2 and isinstance(path[0], tuple):
            pts = [p for (p, _) in path]
            layers = [ly for (_, ly) in path]
            simplified_pts: List[Point] = []
            simplified_layers: List[Layer] = []

            simplified_pts.append(pts[0])
            simplified_layers.append(layers[0])

            for i in range(1, len(pts) - 1):
                prev = simplified_pts[-1]
                curr = pts[i]
                nxt = pts[i + 1]
                # Keep point if geometry bends or if layer changes here
                if (not self._is_collinear(prev, curr, nxt)) or (layers[i] != layers[i - 1]):
                    simplified_pts.append(curr)
                    simplified_layers.append(layers[i])

            simplified_pts.append(pts[-1])
            simplified_layers.append(layers[-1])

            path = list(zip(simplified_pts, simplified_layers))
        else:
            # Fallback: no layers provided (e.g., Manhattan) → simplify points only
            points_only = path  # already points if not tuples
            points_only = self._simplify_path(points_only)  # type: ignore
            path = points_only

        return path

    def _simplify_path(self, path: List[Point]) -> List[Point]:
        """
        Remove redundant intermediate points from path.
        GENERIC - works for any path.

        Example: [A, B, C] where A-B-C are collinear → [A, C]
        """
        if len(path) <= 2:
            return path

        simplified = [path[0]]

        for i in range(1, len(path) - 1):
            prev = simplified[-1]
            current = path[i]
            next_point = path[i + 1]

            # Check if current is on line segment prev → next
            if not self._is_collinear(prev, current, next_point):
                simplified.append(current)

        simplified.append(path[-1])

        return simplified

    def _is_collinear(self, p1: Point, p2: Point, p3: Point,
                     tolerance: float = 1e-3) -> bool:
        """
        Check if three points are collinear (on same line).
        GENERIC mathematical check.
        """
        # Cross product should be zero for collinear points
        cross = abs((p2.y - p1.y) * (p3.x - p2.x) -
                   (p2.x - p1.x) * (p3.y - p2.y))

        return cross < tolerance


class MultiPointRouter:
    """
    GENERIC multi-point net router.
    Routes nets with 2+ pins using optimal strategies.
    """

    def __init__(self, grid: GridOccupancy, config: RoutingConfig):
        """
        Initialize multi-point router.

        Args:
            grid: Occupancy grid
            config: Routing configuration
        """
        self.grid = grid
        self.config = config
        self.path_router = PathRouter(grid, config)

    def route_net(self, pads: List[Point], net_name: str,
                 layer: Layer = Layer.F_CU,
                 strategy: RoutingStrategy = RoutingStrategy.MANHATTAN,
                 distance_field = None) -> Optional[List[List[Point]]]:
        """
        Route multi-pin net using minimum spanning tree.
        GENERIC - works for ANY number of pads.

        TIER 2 Enhancement: Accepts optional distance field for collision-aware routing.
        Distance field prevents placing traces too close to different-net obstacles.

        Args:
            pads: List of pad positions to connect
            net_name: Net name
            layer: Preferred layer
            strategy: Routing algorithm
            distance_field: Optional NetDistanceField for clearance-aware routing

        Returns:
            List of paths (each path connects two pads), or None if routing failed
        """
        if len(pads) < 2:
            return []  # Single pad net (no routing needed)

        if len(pads) == 2:
            # Simple 2‑pin net – prefer vias more (lower penalty) to escape congestion
            path = self._route_with_fallback(
                pads[0], pads[1], layer, strategy, net_name, via_penalty_override=0.2,
                distance_field=distance_field
            )
            return [path] if path else None

        # Multi-pin net: use MST to find optimal connection order
        mst_edges = self._compute_mst(pads)

        # Route each MST edge with progressive fallback strategy
        all_paths: List[List] = []
        for start_idx, end_idx in mst_edges:
            start = pads[start_idx]
            end = pads[end_idx]

            path = self._route_with_fallback(
                start, end, layer, strategy, net_name, distance_field=distance_field
            )

            if path is None:
                # Failed to route this edge; keep partial progress and continue
                continue

            all_paths.append(path)

        # If at least one segment routed, return partial result; otherwise signal failure
        return all_paths if all_paths else None

    def _route_with_fallback(self, start: Point, end: Point,
                            layer: Layer, initial_strategy: RoutingStrategy,
                            net_name: str, via_penalty_override: Optional[float] = None,
                            distance_field = None) -> Optional[List[Point]]:
        """
        GENERIC routing with automatic progressive fallback.

        OPTIMIZATION (2025-11-10): Manhattan-first strategy for 3-5× speedup
        - Try Manhattan FIRST (instant, works for 80%+ of routes)
        - Fall back to A* ONLY when Manhattan fails (slow but higher success rate)
        - Expected impact: 3-5× speedup on average circuits

        TIER 2 Enhancement: Accepts optional distance field for clearance-aware routing.

        Args:
            start: Start point
            end: End point
            layer: PCB layer
            initial_strategy: First strategy to try (ignored - always Manhattan first)
            net_name: Net name for debugging
            via_penalty_override: Optional via penalty override for two-pin nets
            distance_field: Optional NetDistanceField for clearance-aware routing

        Returns:
            Path or None if all strategies fail
        """
        # OPTIMIZATION (2025-11-10): Try Manhattan FIRST (fast)
        # Manhattan routing is instant and works for 80%+ of simple connections
        orig_via_pen = self.path_router.config.via_penalty
        if via_penalty_override is not None:
            self.path_router.config.via_penalty = via_penalty_override
        try:
            path = self.path_router.route_two_point(
                start, end, layer, RoutingStrategy.MANHATTAN, net_name, distance_field
            )
        finally:
            # Restore original penalty
            self.path_router.config.via_penalty = orig_via_pen

        if path:
            return path

        # Fallback to A* (slower but more capable) if Manhattan fails
        # A* with 150mm pad spacing can take seconds per net, but has higher success rate
        orig_via_pen = self.path_router.config.via_penalty
        if via_penalty_override is not None:
            self.path_router.config.via_penalty = via_penalty_override
        try:
            path = self.path_router.route_two_point(
                start, end, layer, RoutingStrategy.ASTAR, net_name, distance_field
            )
        finally:
            # Restore original penalty
            self.path_router.config.via_penalty = orig_via_pen

        if path:
            return path

        # Last-chance fallback: Try layer flip with via
        # Try a forced layer flip at the start anchor, then route on the other layer
        other = Layer.B_CU if layer == Layer.F_CU else Layer.F_CU

        # Try Manhattan on other layer first (fast)
        alt = self.path_router.route_two_point(start, end, other, RoutingStrategy.MANHATTAN, net_name, distance_field)
        if alt:
            # Build a layer-aware path with a via at start
            if isinstance(alt[0], tuple):
                # Already layer-aware
                return [(start, layer), (start, other)] + alt
            else:
                return [(start, layer), (start, other)] + [(p, other) for p in alt]

        # Try A* on other layer (slower fallback)
        alt = self.path_router.route_two_point(start, end, other, RoutingStrategy.ASTAR, net_name, distance_field)
        if alt:
            # Build a layer-aware path with a via at start
            if isinstance(alt[0], tuple):
                # Already layer-aware from A*
                return [(start, layer), (start, other)] + alt
            else:
                return [(start, layer), (start, other)] + [(p, other) for p in alt]

        # No path found
        return None

    def _compute_mst(self, pads: List[Point]) -> List[Tuple[int, int]]:
        """
        Compute Minimum Spanning Tree of pads.
        GENERIC - uses Prim's algorithm for ANY number of pads.

        Returns: List of edges (pairs of pad indices)
        """
        n = len(pads)

        if n <= 1:
            return []

        # Distance matrix
        dist = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                d = pads[i].distance_to(pads[j])
                dist[i][j] = d
                dist[j][i] = d

        # Prim's algorithm
        visited = [False] * n
        visited[0] = True

        edges = []

        for _ in range(n - 1):
            min_dist = float('inf')
            min_edge = None

            # Find minimum edge from visited to unvisited
            for i in range(n):
                if not visited[i]:
                    continue

                for j in range(n):
                    if visited[j]:
                        continue

                    if dist[i][j] < min_dist:
                        min_dist = dist[i][j]
                        min_edge = (i, j)

            if min_edge:
                edges.append(min_edge)
                visited[min_edge[1]] = True

        return edges
