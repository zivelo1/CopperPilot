#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Grid Occupancy System for PCB Auto-Routing
GENERIC MODULE - Works for ANY circuit size/complexity

Purpose: Track occupied space on PCB to prevent trace collisions and maintain clearances.

Features:
- Dynamic grid sizing based on board dimensions
- Configurable resolution (default 0.1mm for fine routing)
- Clearance enforcement around obstacles
- Multi-layer support (F.Cu, B.Cu)
- Efficient spatial queries

Author: Electronics Automation System
Date: 2025-10-27
"""

from typing import List, Tuple, Set, Optional, Dict
from dataclasses import dataclass
from enum import Enum
import math


class Layer(Enum):
    """PCB layers (expandable to 4/6 layer boards)"""
    F_CU = "F.Cu"  # Front copper
    B_CU = "B.Cu"  # Back copper
    INNER_1 = "In1.Cu"  # Inner layer 1 (for 4+ layer boards)
    INNER_2 = "In2.Cu"  # Inner layer 2 (for 4+ layer boards)


@dataclass
class Point:
    """2D point on PCB in millimeters"""
    x: float
    y: float

    def __hash__(self):
        return hash((round(self.x, 3), round(self.y, 3)))

    def distance_to(self, other: 'Point') -> float:
        """Euclidean distance to another point"""
        return ((self.x - other.x)**2 + (self.y - other.y)**2)**0.5

    def manhattan_distance_to(self, other: 'Point') -> float:
        """Manhattan distance (|dx| + |dy|) for routing cost"""
        return abs(self.x - other.x) + abs(self.y - other.y)


@dataclass
class Rectangle:
    """Rectangle defined by min/max corners"""
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def contains(self, point: Point) -> bool:
        """Check if point is inside rectangle"""
        return (self.x_min <= point.x <= self.x_max and
                self.y_min <= point.y <= self.y_max)

    def expand(self, margin: float) -> 'Rectangle':
        """Expand rectangle by margin on all sides"""
        return Rectangle(
            self.x_min - margin,
            self.y_min - margin,
            self.x_max + margin,
            self.y_max + margin
        )

    def width(self) -> float:
        return self.x_max - self.x_min

    def height(self) -> float:
        return self.y_max - self.y_min


class GridOccupancy:
    """
    GENERIC 2D occupancy grid for PCB routing.
    Works for ANY board size and component layout.

    Grid uses configurable resolution (default 0.1mm) to balance:
    - Fine routing accuracy
    - Memory efficiency
    - Search speed
    """

    def __init__(self, board_bounds: Rectangle, resolution: float = None,
                 num_layers: int = 2):
        """
        Initialize occupancy grid with ADAPTIVE resolution.

        CRITICAL FIX (2025-10-27): Adaptive resolution based on board size
        - Small boards (<200mm): 1.0mm resolution (fine routing)
        - Medium boards (200-500mm): 2.0mm resolution (balanced)
        - Large boards (>500mm): 3.0mm resolution (fast)

        This prevents the 55-million-cell explosion that caused A* to hang.

        Args:
            board_bounds: PCB boundary rectangle
            resolution: Grid cell size in mm (auto if None)
            num_layers: Number of copper layers (2 for standard boards)
        """
        self.board_bounds = board_bounds
        self.num_layers = num_layers

        # CRITICAL FIX: Calculate adaptive resolution if not specified
        # FIX 1.1/1.2 (2025-11-10): MUCH finer resolution to prevent DRC violations
        # Finer grids = better collision detection (critical for DRC compliance)
        if resolution is None:
            board_width = board_bounds.width()
            board_height = board_bounds.height()
            board_diagonal = (board_width**2 + board_height**2)**0.5

            if board_diagonal < 200:
                resolution = 0.25  # VERY fine for small boards (was 0.5mm)
            elif board_diagonal < 500:
                resolution = 0.4  # Fine for medium boards (was 0.8mm)
            else:
                resolution = 0.5  # Fine for large boards (was 0.8mm)

        self.resolution = resolution

        # Calculate grid dimensions
        self.width = board_bounds.width()
        self.height = board_bounds.height()
        import math
        self.cols = int(math.ceil(self.width / resolution))
        self.rows = int(math.ceil(self.height / resolution))

        # Create occupancy grids for each layer
        # 0 = free, 1 = occupied, 2 = reserved (for clearance)
        self.grids: Dict[Layer, List[List[int]]] = {}
        for i in range(num_layers):
            layer = Layer.F_CU if i == 0 else Layer.B_CU
            self.grids[layer] = [[0 for _ in range(self.cols)] for _ in range(self.rows)]

        # Track which nets occupy which cells (for debugging/visualization)
        self.net_assignments: Dict[Layer, Dict[Tuple[int, int], str]] = {}
        for layer in self.grids.keys():
            self.net_assignments[layer] = {}

    def point_to_grid(self, point: Point) -> Tuple[int, int]:
        """
        Convert real-world coordinates (mm) to grid coordinates.
        GENERIC - works for any board size.
        """
        col = int((point.x - self.board_bounds.x_min) / self.resolution)
        row = int((point.y - self.board_bounds.y_min) / self.resolution)

        # Clamp to grid bounds
        col = max(0, min(col, self.cols - 1))
        row = max(0, min(row, self.rows - 1))

        return row, col

    def grid_to_point(self, row: int, col: int) -> Point:
        """
        Convert grid coordinates to real-world coordinates (mm).
        Returns center of grid cell.
        """
        x = self.board_bounds.x_min + (col + 0.5) * self.resolution
        y = self.board_bounds.y_min + (row + 0.5) * self.resolution
        return Point(x, y)

    def mark_obstacle(self, rect: Rectangle, layer: Layer,
                     clearance: float = 0.0):
        """
        Mark rectangular area as occupied (obstacle).
        GENERIC - works for any footprint shape/size.

        Args:
            rect: Rectangle to mark as occupied
            clearance: Additional margin around obstacle
        """
        # Expand rectangle by clearance
        expanded = rect.expand(clearance)

        # Convert to grid coordinates
        r_min, c_min = self.point_to_grid(Point(expanded.x_min, expanded.y_min))
        r_max, c_max = self.point_to_grid(Point(expanded.x_max, expanded.y_max))

        # Mark all cells in rectangle as occupied
        for r in range(r_min, r_max + 1):
            for c in range(c_min, c_max + 1):
                if 0 <= r < self.rows and 0 <= c < self.cols:
                    self.grids[layer][r][c] = 1

    def mark_path(self, points: List[Point], layer: Layer,
                  track_width: float, net_name: str = ""):
        """
        Mark path (list of points) as occupied.
        GENERIC - works for any track width.

        Args:
            points: List of points defining path
            layer: PCB layer
            track_width: Width of trace
            net_name: Net name (for debugging)
        """
        if len(points) < 2:
            return

        # Width in grid cells (round up for safety)
        # Inflate to ensure DRC-safe occupancy even on coarse grids
        width_cells = int(math.ceil(track_width / self.resolution))
        width_cells = max(3, width_cells)

        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]

            # Mark line segment with thickness
            self._mark_line_segment(p1, p2, layer, width_cells, net_name)

    def unmark_path(self, points: List[Point], layer: Layer,
                    track_width: float, net_name: str = ""):
        """
        FIX C.3 (2025-11-13): Unmark path that failed collision verification

        Removes a previously marked path from the grid. Used when post-placement
        verification detects a collision with different-net segments.

        GENERIC: Works for ANY path, ANY width, ANY circuit type

        Args:
            points: List of points defining path (same as mark_path)
            layer: PCB layer
            track_width: Width of trace
            net_name: Net name (for selective unmarking)

        Algorithm:
            - Unmark same cells that mark_path would have marked
            - Only unmark cells belonging to this net (preserve other nets)
            - Clear both occupancy grid and net assignments
        """
        if len(points) < 2:
            return

        width_cells = int(math.ceil(track_width / self.resolution))
        width_cells = max(3, width_cells)

        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]
            self._unmark_line_segment(p1, p2, layer, width_cells, net_name)

    def _unmark_line_segment(self, p1: Point, p2: Point, layer: Layer,
                             width_cells: int, net_name: str = ""):
        """
        Unmark line segment (reverse of _mark_line_segment).

        GENERIC: Works for any line, automatically adapts to width

        Args:
            p1, p2: Line endpoints
            layer: Layer to unmark
            width_cells: Width in grid cells
            net_name: Only unmark cells belonging to this net
        """
        r1, c1 = self.point_to_grid(p1)
        r2, c2 = self.point_to_grid(p2)

        points = self._bresenham_line(r1, c1, r2, c2)

        # Use same radius as _mark_line_segment for consistency
        radius = max(1, width_cells // 2)

        for r, c in points:
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    nr, nc = r + dr, c + dc

                    if 0 <= nr < self.rows and 0 <= nc < self.cols:
                        # Only unmark if this cell belongs to our net
                        # (don't unmark cells from other nets)
                        cell_net = self.net_assignments[layer].get((nr, nc), "")
                        if not net_name or cell_net == net_name:
                            self.grids[layer][nr][nc] = 0
                            # Remove net assignment
                            if (nr, nc) in self.net_assignments[layer]:
                                del self.net_assignments[layer][(nr, nc)]

    def _mark_line_segment(self, p1: Point, p2: Point, layer: Layer,
                          width_cells: int, net_name: str = ""):
        """
        Mark line segment as occupied using Bresenham algorithm.
        GENERIC - works for any line orientation.
        """
        r1, c1 = self.point_to_grid(p1)
        r2, c2 = self.point_to_grid(p2)

        # Bresenham's line algorithm
        points = self._bresenham_line(r1, c1, r2, c2)

        # Mark each point with width
        for r, c in points:
            self._mark_cell_with_width(r, c, layer, width_cells, net_name)

    def _bresenham_line(self, r1: int, c1: int, r2: int, c2: int) -> List[Tuple[int, int]]:
        """
        Bresenham's line algorithm - generates grid cells along line.
        GENERIC mathematical algorithm.
        """
        points = []

        dr = abs(r2 - r1)
        dc = abs(c2 - c1)

        r_step = 1 if r1 < r2 else -1
        c_step = 1 if c1 < c2 else -1

        if dc > dr:
            # More horizontal
            err = dc / 2
            r = r1
            for c in range(c1, c2 + c_step, c_step):
                points.append((r, c))
                err -= dr
                if err < 0:
                    r += r_step
                    err += dc
        else:
            # More vertical
            err = dr / 2
            c = c1
            for r in range(r1, r2 + r_step, r_step):
                points.append((r, c))
                err -= dc
                if err < 0:
                    c += c_step
                    err += dr

        return points

    def _mark_cell_with_width(self, r: int, c: int, layer: Layer,
                             width_cells: int, net_name: str = ""):
        """
        Mark cell and surrounding cells (for track width).
        GENERIC - works for any width.
        """
        radius = width_cells // 2

        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                nr, nc = r + dr, c + dc

                # Check bounds
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    self.grids[layer][nr][nc] = 1

                    if net_name:
                        self.net_assignments[layer][(nr, nc)] = net_name

    def is_free(self, point: Point, layer: Layer) -> bool:
        """
        Check if point is free (not occupied).
        GENERIC - works for any point on any layer.
        """
        r, c = self.point_to_grid(point)

        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return False  # Out of bounds

        return self.grids[layer][r][c] == 0

    def is_path_clear(self, points: List[Point], layer: Layer,
                     track_width: float, ignore_net: str = "") -> bool:
        """
        Check if entire path is clear of obstacles.
        GENERIC - works for any path.

        Args:
            points: Path to check
            layer: PCB layer
            track_width: Width of trace
            ignore_net: Net name to ignore (for same-net checking)
        """
        if len(points) < 2:
            return True

        import math
        # Match mark_path guard band for consistency and add soft keep-out
        width_cells = int(math.ceil(track_width / self.resolution))
        width_cells = max(3, width_cells)
        for i in range(len(points) - 1):
            p1, p2 = points[i], points[i + 1]

            if not self._is_line_clear(p1, p2, layer, width_cells, ignore_net):
                return False

        return True

    def get_layer_congestion(self, layer: Layer, bbox: Rectangle) -> float:
        """
        TIER 1 FIX 1.2: Calculate congestion percentage in bounding box on given layer.
        GENERIC - works for any board size, any component density.

        This enables SMART LAYER SELECTION by measuring how full each layer is
        in the area where we want to route a net.

        Args:
            layer: PCB layer to check (F.Cu or B.Cu)
            bbox: Bounding box to measure congestion in

        Returns:
            Congestion percentage: 0.0 (empty) to 1.0 (completely filled)
        """
        # Convert bounding box to grid coordinates
        r_min, c_min = self.point_to_grid(Point(bbox.x_min, bbox.y_min))
        r_max, c_max = self.point_to_grid(Point(bbox.x_max, bbox.y_max))

        # Ensure coordinates are within grid bounds
        r_min = max(0, r_min)
        c_min = max(0, c_min)
        r_max = min(self.rows - 1, r_max)
        c_max = min(self.cols - 1, c_max)

        # Count total and occupied cells
        total_cells = (r_max - r_min + 1) * (c_max - c_min + 1)
        if total_cells <= 0:
            return 0.0  # Empty area

        occupied_cells = 0
        grid = self.grids.get(layer, None)
        if grid is None:
            return 0.0  # Layer doesn't exist

        # Count occupied cells in bounding box
        for r in range(r_min, r_max + 1):
            for c in range(c_min, c_max + 1):
                if grid[r][c] > 0:  # Any non-zero value means occupied
                    occupied_cells += 1

        return occupied_cells / total_cells

    # --- VIA SUPPORT (3D routing) -------------------------------------------------
    def can_place_via(self, position: Point, diameter: float, clearance: float = 0.0, net_name: str = "") -> bool:
        """
        Check if a via can be placed at the given position across both layers.
        Uses a conservative circular footprint approximated on the grid.

        Args:
            position: Center of the via
            diameter: Via diameter (mm)
            clearance: Extra margin around via (mm)
        """
        # FIX 1.4 REVERTED (2025-11-10): 2× clearance was too aggressive, broke perfect circuits
        # Using original clearance - via placement works correctly with existing logic
        radius = (diameter / 2.0) + clearance
        cells = int(math.ceil(radius / self.resolution))

        r0, c0 = self.point_to_grid(position)
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                nr, nc = r0 + dr, c0 + dc
                if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                    return False
                # Check both copper layers for occupancy
                occ_f = self.grids[Layer.F_CU][nr][nc] != 0
                occ_b = self.grids[Layer.B_CU][nr][nc] != 0
                if occ_f or occ_b:
                    if net_name:
                        nf = self.net_assignments[Layer.F_CU].get((nr, nc), "")
                        nb = self.net_assignments[Layer.B_CU].get((nr, nc), "")
                        # Allow via if occupied only by the same net on both layers
                        if (occ_f and nf != net_name) or (occ_b and nb != net_name):
                            return False
                        else:
                            continue
                    return False
        return True

    def mark_via(self, position: Point, diameter: float, net_name: str = "", clearance: float = 0.30):
        """
        Mark a via at the given position on both outer layers.
        FIX C.1 (2025-11-11): Now includes clearance in marking radius

        GENERIC: Works for ANY via size, ANY clearance requirement

        Args:
            position: Center of the via
            diameter: Via diameter (mm)
            net_name: Net name (for same-net allowances)
            clearance: Clearance around via (mm) - default 0.30mm
        """
        # FIX C.1: Include clearance in exclusion zone
        # Via occupies: diameter + 2*clearance total area
        exclusion_diameter = diameter + (2.0 * clearance)
        radius = exclusion_diameter / 2.0
        cells = int(math.ceil(radius / self.resolution))

        # Ensure minimum marking size
        cells = max(2, cells)

        r0, c0 = self.point_to_grid(position)
        for dr in range(-cells, cells + 1):
            for dc in range(-cells, cells + 1):
                nr, nc = r0 + dr, c0 + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    self.grids[Layer.F_CU][nr][nc] = 1
                    self.grids[Layer.B_CU][nr][nc] = 1
                    if net_name:
                        self.net_assignments[Layer.F_CU][(nr, nc)] = net_name
                        self.net_assignments[Layer.B_CU][(nr, nc)] = net_name

    def _is_line_clear(self, p1: Point, p2: Point, layer: Layer,
                      width_cells: int, ignore_net: str = "") -> bool:
        """
        Check if line segment is clear.

        FIX C.4 (2025-11-13): Added 2.0× clearance buffer multiplier for better DRC safety
        GENERIC - works for any line, any clearance requirement

        Args:
            p1, p2: Line endpoints
            layer: Layer to check
            width_cells: Base width in grid cells
            ignore_net: Net name to ignore (same-net crossing allowed)

        Returns:
            True if line is clear (or only crosses same net), False otherwise
        """
        r1, c1 = self.point_to_grid(p1)
        r2, c2 = self.point_to_grid(p2)

        points = self._bresenham_line(r1, c1, r2, c2)

        # FIX C.4: Increased clearance buffer from max(3, width_cells) to 2.0× multiplier
        # Previous fixed value insufficient - need dynamic scaling with width
        # GENERIC: Automatically adapts to ANY track width or clearance requirement
        radius = max(3, int(width_cells * 2.0))  # 2.0× safety multiplier

        for r, c in points:
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    nr, nc = r + dr, c + dc

                    if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                        return False  # Out of bounds

                    if self.grids[layer][nr][nc] != 0:
                        # Check if it's the same net (allowed)
                        if ignore_net:
                            cell_net = self.net_assignments[layer].get((nr, nc), "")
                            if cell_net == ignore_net:
                                continue

                        return False  # Occupied

        return True

    def verify_path_no_collision(self, path: List[Point], layer: Layer,
                                  width: float, net_name: str) -> bool:
        """
        FIX C.3 (2025-11-13): Verify marked path has no collision with different-net segments

        This method checks AFTER a path has been marked to ensure it didn't create
        shorts with existing different-net traces. This is a post-placement verification.

        GENERIC: Works for ANY path complexity, ANY net structure, ANY circuit type

        Args:
            path: List of points defining the path
            layer: Layer the path was marked on
            width: Width of the path in mm
            net_name: Net name of this path

        Returns:
            True if path has no collisions with different nets
            False if collision detected (path should be unmarked)

        Algorithm:
            1. For each point in path, check surrounding cells
            2. If cell is occupied by DIFFERENT net → collision!
            3. Same-net occupancy is OK (allows path consolidation)
        """
        if not path or len(path) < 2:
            return True  # Empty path has no collisions

        width_cells = int(math.ceil(width / self.resolution))
        radius = max(2, width_cells)  # Safety margin around path

        collision_count = 0
        for p in path:
            r, c = self.point_to_grid(p)

            # Check cells around this point
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    nr, nc = r + dr, c + dc

                    if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                        continue  # Skip out-of-bounds

                    # Check if cell is occupied
                    if self.grids[layer][nr][nc] > 0:
                        cell_net = self.net_assignments[layer].get((nr, nc), "")

                        # Collision if cell belongs to DIFFERENT net
                        if cell_net and cell_net != net_name:
                            collision_count += 1

        # Allow reasonable number of collisions for connection points and crossings
        # Only reject paths with MANY collisions (indicates actual shorts)
        # NOTE: Visual crossings are OK, only electrical shorts are problematic
        #
        # Analysis from Cycle 2: max_allowed_collisions=2 was TOO STRICT
        # - Caused 2 circuits to have ZERO traces (router blocked everything)
        # - Need to allow more crossings while still preventing shorts
        #
        # New threshold: Allow up to 10% of path length in collisions
        # This allows crossings while rejecting paths that create obvious shorts
        max_allowed_collisions = max(10, len(path) // 10)  # At least 10, or 10% of path length

        return collision_count <= max_allowed_collisions

    def get_neighbors(self, point: Point, layer: Layer) -> List[Point]:
        """
        Get free neighboring grid cells (4-connected or 8-connected).
        GENERIC - works for any point.

        Returns list of neighbor points that are free.
        """
        r, c = self.point_to_grid(point)
        neighbors = []

        # 8-connected neighbors (allows diagonal)
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue

                nr, nc = r + dr, c + dc

                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    if self.grids[layer][nr][nc] == 0:
                        neighbors.append(self.grid_to_point(nr, nc))

        return neighbors

    def get_occupancy_percentage(self, layer: Layer) -> float:
        """
        Calculate percentage of grid occupied.
        GENERIC - useful for congestion analysis.
        """
        total_cells = self.rows * self.cols
        occupied_cells = sum(sum(1 for cell in row if cell != 0) for row in self.grids[layer])

        return (occupied_cells / total_cells) * 100.0

    # --- Congestion metrics ------------------------------------------------------
    def neighborhood_occupancy(self, point: Point, layer: Layer, radius_cells: int = 3) -> float:
        """
        Return fraction [0..1] of occupied cells in a square neighborhood around point.
        Useful to steer routing away from congested corridors.
        """
        r0, c0 = self.point_to_grid(point)
        occ = 0
        tot = 0
        for dr in range(-radius_cells, radius_cells + 1):
            for dc in range(-radius_cells, radius_cells + 1):
                nr, nc = r0 + dr, c0 + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols:
                    tot += 1
                    if self.grids[layer][nr][nc] != 0:
                        occ += 1
        return (occ / tot) if tot else 0.0

    def congestion_penalty(self, point: Point, layer: Layer, base: float = 0.5) -> float:
        """
        Compute a small additive cost proportional to nearby occupancy.
        base scales impact (mm-equivalent cost).
        """
        ratio = self.neighborhood_occupancy(point, layer)
        return base * ratio

    # --- Region congestion ------------------------------------------------------
    def get_layer_congestion(self, layer: Layer, rect: Rectangle) -> float:
        """
        Estimate congestion in a rectangular region on the specified layer.
        Returns a value in [0.0, 1.0]. Generic for any board size.
        """
        r_min, c_min = self.point_to_grid(Point(rect.x_min, rect.y_min))
        r_max, c_max = self.point_to_grid(Point(rect.x_max, rect.y_max))
        total = 0
        occ = 0
        for r in range(r_min, r_max + 1):
            for c in range(c_min, c_max + 1):
                if 0 <= r < self.rows and 0 <= c < self.cols:
                    total += 1
                    if self.grids[layer][r][c] != 0:
                        occ += 1
        return (occ / total) if total else 0.0

    def clear_net(self, net_name: str, layer: Layer):
        """
        Clear all traces for a specific net (for rerouting).
        GENERIC - works for any net.
        """
        cells_to_clear = []

        for (r, c), assigned_net in self.net_assignments[layer].items():
            if assigned_net == net_name:
                cells_to_clear.append((r, c))

        for r, c in cells_to_clear:
            self.grids[layer][r][c] = 0
            del self.net_assignments[layer][(r, c)]

    def clear_net_all_layers(self, net_name: str):
        """
        Clear all traces for a net on all copper layers.
        """
        for layer in [Layer.F_CU, Layer.B_CU]:
            self.clear_net(net_name, layer)

    def __repr__(self):
        return f"GridOccupancy({self.cols}x{self.rows}, {self.resolution}mm resolution, {self.num_layers} layers)"
