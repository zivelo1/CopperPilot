# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle Wire Path Generator Module

GENERIC module to generate wire paths connecting pins within a segment.
Creates minimum spanning tree with junctions at branch points.

Architecture Principle: GENERIC - works for ANY pin layout
Strategy: Graph-based wire routing with automatic junction detection
"""

import math
from typing import List, Tuple, Set, Dict, Optional
from dataclasses import dataclass


@dataclass
class Wire:
    """Represents a wire connecting two points."""
    x1: float
    y1: float
    x2: float
    y2: float

    def length(self) -> float:
        """Calculate wire length."""
        dx = self.x2 - self.x1
        dy = self.y2 - self.y1
        return math.sqrt(dx * dx + dy * dy)

    def contains_point(self, x: float, y: float, tolerance: float = 0.01) -> bool:
        """Check if a point lies on this wire."""
        # Check if point is at either endpoint
        if (abs(x - self.x1) < tolerance and abs(y - self.y1) < tolerance):
            return True
        if (abs(x - self.x2) < tolerance and abs(y - self.y2) < tolerance):
            return True

        # Check if point lies on line segment
        wire_len = self.length()
        if wire_len < tolerance:
            return False

        # Distance from point to line segment
        t = ((x - self.x1) * (self.x2 - self.x1) + (y - self.y1) * (self.y2 - self.y1)) / (wire_len * wire_len)
        t = max(0, min(1, t))  # Clamp to segment

        closest_x = self.x1 + t * (self.x2 - self.x1)
        closest_y = self.y1 + t * (self.y2 - self.y1)

        dist = math.sqrt((x - closest_x) ** 2 + (y - closest_y) ** 2)
        return dist < tolerance

    def __repr__(self):
        return f"Wire({self.x1:.2f}, {self.y1:.2f} -> {self.x2:.2f}, {self.y2:.2f})"


@dataclass
class Junction:
    """Represents a junction point where multiple wires meet."""
    x: float
    y: float

    def __repr__(self):
        return f"Junction({self.x:.2f}, {self.y:.2f})"

    def __hash__(self):
        # Round to avoid floating point precision issues
        return hash((round(self.x, 2), round(self.y, 2)))

    def __eq__(self, other):
        if not isinstance(other, Junction):
            return False
        return abs(self.x - other.x) < 0.01 and abs(self.y - other.y) < 0.01


class SegmentWireGenerator:
    """
    GENERIC wire path generator for segment connections.

    Strategy:
    1. Build minimum spanning tree of pin positions
    2. Generate wires along tree edges
    3. Identify junctions at branch points (degree > 2)

    This creates wire patterns matching real Eagle schematics.
    """

    def __init__(self):
        self.wires: List[Wire] = []
        self.junctions: List[Junction] = []

    def generate_wire_path(
        self,
        pin_positions: List[Tuple[float, float]]
    ) -> Dict:
        """
        Generate wire path connecting all pins in a cluster.

        Args:
            pin_positions: List of (x, y) coordinates

        Returns:
            Dictionary with:
            - 'wires': List of Wire objects
            - 'junctions': List of Junction objects
        """
        self.wires = []
        self.junctions = []

        # Handle edge cases
        if not pin_positions:
            return {'wires': [], 'junctions': []}

        if len(pin_positions) == 1:
            # Single pin: no wires needed (will get stub wire + label)
            return {'wires': [], 'junctions': []}

        if len(pin_positions) == 2:
            # Two pins: single wire, no junction
            x1, y1 = pin_positions[0]
            x2, y2 = pin_positions[1]
            self.wires.append(Wire(x1, y1, x2, y2))
            return {'wires': self.wires, 'junctions': []}

        # Three or more pins: build minimum spanning tree
        self._build_minimum_spanning_tree(pin_positions)

        # Detect junctions (branch points)
        self._detect_junctions(pin_positions)

        return {'wires': self.wires, 'junctions': self.junctions}

    def _build_minimum_spanning_tree(
        self,
        pin_positions: List[Tuple[float, float]]
    ):
        """
        Build minimum spanning tree using Prim's algorithm.
        Creates wires connecting all pins with minimum total wire length.
        """
        if len(pin_positions) < 2:
            return

        # Start with first pin
        in_tree = {0}
        edges = []

        # Prim's algorithm
        while len(in_tree) < len(pin_positions):
            min_dist = float('inf')
            min_edge = None

            # Find minimum edge from tree to non-tree vertex
            for i in in_tree:
                x1, y1 = pin_positions[i]
                for j in range(len(pin_positions)):
                    if j in in_tree:
                        continue

                    x2, y2 = pin_positions[j]
                    dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

                    if dist < min_dist:
                        min_dist = dist
                        min_edge = (i, j, x1, y1, x2, y2)

            if min_edge:
                i, j, x1, y1, x2, y2 = min_edge
                in_tree.add(j)
                edges.append((x1, y1, x2, y2))

        # Convert edges to wires
        for x1, y1, x2, y2 in edges:
            self.wires.append(Wire(x1, y1, x2, y2))

    def _detect_junctions(
        self,
        pin_positions: List[Tuple[float, float]]
    ):
        """
        Detect junction points where 3 or more wires meet.

        A junction is needed when:
        - 3+ wires share a common endpoint
        - A wire branches (degree > 2 at a vertex)
        """
        if not self.wires:
            return

        # Count degree (number of wire connections) at each point
        degree: Dict[Tuple[float, float], int] = {}

        for wire in self.wires:
            # Round coordinates to avoid floating point issues
            p1 = (round(wire.x1, 2), round(wire.y1, 2))
            p2 = (round(wire.x2, 2), round(wire.y2, 2))

            degree[p1] = degree.get(p1, 0) + 1
            degree[p2] = degree.get(p2, 0) + 1

        # Junction needed where degree > 2
        junction_points = {point for point, deg in degree.items() if deg > 2}

        # Convert to Junction objects
        self.junctions = [Junction(x, y) for x, y in junction_points]

    def generate_star_topology(
        self,
        pin_positions: List[Tuple[float, float]],
        hub_position: Optional[Tuple[float, float]] = None
    ) -> Dict:
        """
        Generate star topology: all pins connect to a central hub.

        Useful for power/ground nets with many connections.

        Args:
            pin_positions: List of pin coordinates
            hub_position: Hub coordinate (if None, uses centroid)

        Returns:
            Dictionary with wires and junctions
        """
        self.wires = []
        self.junctions = []

        if len(pin_positions) < 2:
            return {'wires': [], 'junctions': []}

        # Calculate hub position (centroid if not specified)
        if hub_position is None:
            avg_x = sum(x for x, y in pin_positions) / len(pin_positions)
            avg_y = sum(y for x, y in pin_positions) / len(pin_positions)
            hub_position = (avg_x, avg_y)

        hub_x, hub_y = hub_position

        # Create wire from each pin to hub
        for pin_x, pin_y in pin_positions:
            self.wires.append(Wire(pin_x, pin_y, hub_x, hub_y))

        # Hub is a junction (all wires meet there)
        if len(pin_positions) > 2:
            self.junctions.append(Junction(hub_x, hub_y))

        return {'wires': self.wires, 'junctions': self.junctions}

    def generate_orthogonal_path(
        self,
        pin_positions: List[Tuple[float, float]]
    ) -> Dict:
        """
        Generate orthogonal (Manhattan-style) wire routing.

        Uses only horizontal and vertical segments.
        Better matches typical schematic drawing style.
        """
        self.wires = []
        self.junctions = []

        if len(pin_positions) < 2:
            return {'wires': [], 'junctions': []}

        if len(pin_positions) == 2:
            # Two pins: L-shaped or straight connection
            x1, y1 = pin_positions[0]
            x2, y2 = pin_positions[1]

            if abs(x2 - x1) < 0.01:
                # Vertical alignment: direct connection
                self.wires.append(Wire(x1, y1, x2, y2))
            elif abs(y2 - y1) < 0.01:
                # Horizontal alignment: direct connection
                self.wires.append(Wire(x1, y1, x2, y2))
            else:
                # L-shaped: horizontal then vertical
                self.wires.append(Wire(x1, y1, x2, y1))  # Horizontal
                self.wires.append(Wire(x2, y1, x2, y2))  # Vertical
                self.junctions.append(Junction(x2, y1))  # Corner junction

            return {'wires': self.wires, 'junctions': self.junctions}

        # For 3+ pins: build MST first, then orthogonalize
        self._build_minimum_spanning_tree(pin_positions)

        # Convert diagonal wires to orthogonal (simplified approach)
        orthogonal_wires = []
        for wire in self.wires:
            if abs(wire.x2 - wire.x1) < 0.01 or abs(wire.y2 - wire.y1) < 0.01:
                # Already orthogonal
                orthogonal_wires.append(wire)
            else:
                # Convert to L-shape
                orthogonal_wires.append(Wire(wire.x1, wire.y1, wire.x2, wire.y1))
                orthogonal_wires.append(Wire(wire.x2, wire.y1, wire.x2, wire.y2))
                self.junctions.append(Junction(wire.x2, wire.y1))

        self.wires = orthogonal_wires
        self._detect_junctions(pin_positions)

        return {'wires': self.wires, 'junctions': self.junctions}


class WireOptimizer:
    """
    Optimizes wire paths for better schematic appearance.
    """

    @staticmethod
    def simplify_wires(wires: List[Wire]) -> List[Wire]:
        """
        Simplify wire paths by merging collinear segments.

        Args:
            wires: List of wire segments

        Returns:
            Simplified list of wires
        """
        if len(wires) <= 1:
            return wires

        # Group wires by direction
        horizontal = [w for w in wires if abs(w.y2 - w.y1) < 0.01]
        vertical = [w for w in wires if abs(w.x2 - w.x1) < 0.01]
        diagonal = [w for w in wires if w not in horizontal and w not in vertical]

        simplified = []

        # Merge collinear horizontal wires
        simplified.extend(WireOptimizer._merge_collinear_horizontal(horizontal))

        # Merge collinear vertical wires
        simplified.extend(WireOptimizer._merge_collinear_vertical(vertical))

        # Keep diagonal wires as-is
        simplified.extend(diagonal)

        return simplified

    @staticmethod
    def _merge_collinear_horizontal(wires: List[Wire]) -> List[Wire]:
        """Merge horizontal wires that are collinear."""
        if not wires:
            return []

        # Group by y-coordinate
        groups: Dict[float, List[Wire]] = {}
        for wire in wires:
            y = round(wire.y1, 2)
            if y not in groups:
                groups[y] = []
            groups[y].append(wire)

        merged = []
        for y, group in groups.items():
            # Sort by x coordinate
            group.sort(key=lambda w: min(w.x1, w.x2))

            # Merge overlapping/adjacent segments
            current = group[0]
            for next_wire in group[1:]:
                current_max_x = max(current.x1, current.x2)
                next_min_x = min(next_wire.x1, next_wire.x2)

                if next_min_x <= current_max_x + 0.01:
                    # Merge
                    current = Wire(
                        min(current.x1, current.x2, next_wire.x1, next_wire.x2),
                        y,
                        max(current.x1, current.x2, next_wire.x1, next_wire.x2),
                        y
                    )
                else:
                    merged.append(current)
                    current = next_wire

            merged.append(current)

        return merged

    @staticmethod
    def _merge_collinear_vertical(wires: List[Wire]) -> List[Wire]:
        """Merge vertical wires that are collinear."""
        if not wires:
            return []

        # Group by x-coordinate
        groups: Dict[float, List[Wire]] = {}
        for wire in wires:
            x = round(wire.x1, 2)
            if x not in groups:
                groups[x] = []
            groups[x].append(wire)

        merged = []
        for x, group in groups.items():
            # Sort by y coordinate
            group.sort(key=lambda w: min(w.y1, w.y2))

            # Merge overlapping/adjacent segments
            current = group[0]
            for next_wire in group[1:]:
                current_max_y = max(current.y1, current.y2)
                next_min_y = min(next_wire.y1, next_wire.y2)

                if next_min_y <= current_max_y + 0.01:
                    # Merge
                    current = Wire(
                        x,
                        min(current.y1, current.y2, next_wire.y1, next_wire.y2),
                        x,
                        max(current.y1, current.y2, next_wire.y1, next_wire.y2)
                    )
                else:
                    merged.append(current)
                    current = next_wire

            merged.append(current)

        return merged


# Convenience functions
def generate_segment_wires(
    pin_positions: List[Tuple[float, float]],
    topology: str = 'mst'
) -> Dict:
    """
    Generate wires for a segment connecting multiple pins.

    Args:
        pin_positions: List of (x, y) pin coordinates
        topology: 'mst' (minimum spanning tree), 'star', or 'orthogonal'

    Returns:
        Dictionary with 'wires' and 'junctions'
    """
    generator = SegmentWireGenerator()

    if topology == 'star':
        return generator.generate_star_topology(pin_positions)
    elif topology == 'orthogonal':
        return generator.generate_orthogonal_path(pin_positions)
    else:  # 'mst' or default
        return generator.generate_wire_path(pin_positions)


def optimize_segment_wires(wires: List[Wire]) -> List[Wire]:
    """
    Optimize wire paths by merging collinear segments.

    Args:
        wires: List of wire segments

    Returns:
        Optimized list of wires
    """
    return WireOptimizer.simplify_wires(wires)
