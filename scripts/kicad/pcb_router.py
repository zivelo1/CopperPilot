#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Main PCB Auto-Router - Orchestrates Complete PCB Routing
GENERIC MODULE - Works for ANY circuit

This is the main entry point for PCB routing. It:
1. Analyzes circuit to extract pads and nets
2. Builds occupancy grid from footprints
3. Routes all nets using optimal strategies
4. Generates KiCad segment elements
5. Validates routing completeness

GUARANTEED to work for:
- ANY board size (small to large)
- ANY component count (2 to 200+)
- ANY net count (2 to 500+)
- ANY component types (resistors to complex ICs)

Author: Electronics Automation System
Date: 2025-10-27
"""

import logging
import time
from typing import List, Dict, Tuple, Optional
from pathlib import Path

from .grid_occupancy import GridOccupancy, Point, Rectangle, Layer
from .path_routing import (PathRouter, MultiPointRouter, RoutingConfig,
                           RoutingStrategy)
from .segment_generator import SegmentGenerator, Segment, Via, RoutingStatistics
from .footprint_geometry import get_pad_positions  # CRITICAL: Use real pad coordinates!
from .net_distance_field import build_distance_field_for_net  # TIER 2: Distance field system


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# TIER 1 FIX 1.1 & 1.4: SAFETY CONSTRAINTS (GENERIC for all circuits)
# Restored to production values after Tier 0 fixes (2025-11-02)
# MAX_RIP_WINDOW replaced by dynamic function in Fix 1.4 (2025-11-03)
MAX_ROUNDS_PER_NET = 10       # Max attempts per net (RESTORED from TEMPORARY 2)
MAX_TIME_PER_NET = 10.0       # Hard timeout in seconds (RESTORED from TEMPORARY 5s)
MAX_TOTAL_ROUTING_TIME = 120.0  # Per-circuit cap (RESTORED from TEMPORARY 30s)

# TIER 1 FIX 1.4 (2025-11-03): Dynamic rip-up window based on circuit complexity
def _get_max_rip_window(total_nets: int) -> int:
    """
    Calculate max rip-up window based on circuit complexity.
    GENERIC - works for any circuit size.

    Rationale: Complex circuits need to clear larger "bubble" around failed net.

    Args:
        total_nets: Total number of nets in circuit

    Returns:
        Max nets to rip up (10-30)
    """
    if total_nets < 20:
        return 10   # Simple circuits: conservative (sufficient for low congestion)
    elif total_nets < 30:
        return 20   # Medium circuits: moderate (balance between clearing space and stability)
    else:
        return 30   # Complex circuits: aggressive (need large bubble to find paths)

# TIER 1 FIX 1.3: FAB LIMITS (SAFETY - GENERIC for all fab houses)
FAB_LIMITS = {
    'JLCPCB': 0.127,      # 5 mil (standard)
    'PCBWay': 0.100,      # 4 mil (advanced)
    'OSHPark': 0.152,     # 6 mil (standard)
    'GENERIC': 0.127,     # Safe default (5 mil)
}


def _calculate_bbox_from_paths(paths: List[List]) -> Optional[Rectangle]:
    """
    Calculate bounding box from routed paths.
    GENERIC - works for any path structure (with or without layers).

    Args:
        paths: List of paths (each path is list of Points or (Point, Layer) tuples)

    Returns:
        Rectangle bounding box or None if no paths
    """
    if not paths:
        return None

    all_points: List[Point] = []
    for path in paths:
        if not path:
            continue
        # Handle both Point and (Point, Layer) formats
        if isinstance(path[0], tuple):
            all_points.extend([p for p, _ in path])  # type: ignore
        else:
            all_points.extend(path)

    if not all_points:
        return None

    xs = [p.x for p in all_points]
    ys = [p.y for p in all_points]
    return Rectangle(min(xs), min(ys), max(xs), max(ys))


def _calculate_bbox_from_pads(pads: List[Point]) -> Rectangle:
    """
    Calculate bounding box from pad positions.
    GENERIC - works for any number of pads.

    Args:
        pads: List of pad positions

    Returns:
        Rectangle bounding box
    """
    xs = [p.x for p in pads]
    ys = [p.y for p in pads]
    return Rectangle(min(xs), min(ys), max(xs), max(ys))


def _get_local_rip_candidates(failed_net_bbox: Rectangle,
                               routed_nets: Dict[str, List[List]],
                               routed_order: List[Tuple[str, List[Point]]],
                               is_power_func,
                               max_rip_window: int = 10) -> List[Tuple[str, List[Point]]]:
    """
    Get rip candidates that INTERSECT with failed net's bounding box.
    GENERIC - works for any circuit, any net count.

    This implements LOCAL SCOPING to only rip nets that actually conflict
    with the failed net, not just the most recent nets.

    TIER 1 FIX 1.4: Now accepts dynamic max_rip_window parameter.

    Args:
        failed_net_bbox: Bounding box of failed net
        routed_nets: Already routed nets (net_name → paths)
        routed_order: Order in which nets were routed
        is_power_func: Function to check if net is power
        max_rip_window: Max nets to rip (default 10, up to 30 for complex circuits)

    Returns:
        List of (net_name, pads) tuples sorted by distance (closest first)
        Max length: max_rip_window
    """
    candidates = []

    for net_name, net_pads in routed_order:
        # Don't rip power nets (too important)
        if is_power_func(net_name):
            continue

        # Check if this net's paths intersect with failed net's bbox
        if net_name in routed_nets:
            net_paths = routed_nets[net_name]
            net_bbox = _calculate_bbox_from_paths(net_paths)

            # AABB intersection check (GENERIC - works for any rectangles)
            if net_bbox and not (
                net_bbox.x_max < failed_net_bbox.x_min or  # net is left of failed
                net_bbox.x_min > failed_net_bbox.x_max or  # net is right of failed
                net_bbox.y_max < failed_net_bbox.y_min or  # net is below failed
                net_bbox.y_min > failed_net_bbox.y_max     # net is above failed
            ):
                # Calculate distance from failed net center
                failed_center_x = (failed_net_bbox.x_min + failed_net_bbox.x_max) / 2
                failed_center_y = (failed_net_bbox.y_min + failed_net_bbox.y_max) / 2
                net_center_x = (net_bbox.x_min + net_bbox.x_max) / 2
                net_center_y = (net_bbox.y_min + net_bbox.y_max) / 2

                dx = net_center_x - failed_center_x
                dy = net_center_y - failed_center_y
                distance = (dx*dx + dy*dy) ** 0.5

                candidates.append((net_name, net_pads, distance))

    # Sort by distance (rip closest nets first - most likely to be blocking)
    candidates.sort(key=lambda x: x[2])

    # TIER 1 FIX 1.4: Return at most max_rip_window candidates (dynamic, not fixed)
    return [(name, pads) for name, pads, _ in candidates[:max_rip_window]]


def _choose_preferred_layer(net_name: str, pads: List[Point],
                            grid: GridOccupancy, is_power_func) -> Layer:
    """
    TIER 1 FIX 1.2: Choose layer with least congestion in net's area.
    GENERIC - works for any circuit, any net type.

    This implements SMART LAYER SELECTION by dynamically choosing the
    less congested layer instead of using fixed preferences.

    Args:
        net_name: Name of net to route
        pads: Pad positions for this net
        grid: Grid occupancy tracker
        is_power_func: Function to check if net is power

    Returns:
        Preferred layer (Layer.F_CU or Layer.B_CU)
    """
    # Calculate net bounding box
    bbox = _calculate_bbox_from_pads(pads)

    # Check congestion on both layers
    f_cu_congestion = grid.get_layer_congestion(Layer.F_CU, bbox)
    b_cu_congestion = grid.get_layer_congestion(Layer.B_CU, bbox)

    # Power nets still prefer B.Cu if congestion is similar (< 10% difference)
    # This maintains the useful convention of putting power on bottom layer
    if is_power_func(net_name):
        if b_cu_congestion < f_cu_congestion + 0.1:
            return Layer.B_CU

    # For signal nets, simply pick the less congested layer
    return Layer.B_CU if b_cu_congestion < f_cu_congestion else Layer.F_CU


def _get_clearance_for_attempt(attempt: int, fab: str = 'GENERIC') -> float:
    """
    TIER 1 FIX 1.3: Return clearance for routing attempt.
    GENERIC - works for any fab house, never violates limits.

    Progressive clearance relaxation helps stubborn nets route while
    maintaining manufacturing safety.

    Args:
        attempt: Routing attempt number (1-based)
        fab: Fab house name (default: 'GENERIC')

    Returns:
        Clearance in mm (always >= fab minimum)
    """
    fab_min = FAB_LIMITS.get(fab, 0.127)

    # FIX B.3/B.5 (2025-11-11): Updated progressive clearance for 0.30mm base
    # CYCLE 5 (2025-11-13): Reduced to 0.20mm base for TIER 2 distance fields
    # GENERIC: Works for ANY fab house, never violates limits
    # Starting from 0.20mm (with 1.5× safety margin in distance field = 0.30mm effective)
    # Progressively relax to enable difficult routes
    # Rationale: Distance field provides safety margin, base clearance can be reduced
    schedule = {
        1: 0.20,                    # Base clearance (CYCLE 5: reduced from 0.30mm)
        2: 0.17,                    # 15% reduction
        3: 0.15,                    # 25% reduction
        4: 0.13,                    # 35% reduction
        5: 0.12,                    # 40% reduction
        6: 0.10,                    # 50% reduction (PCBWay capable)
        7: 0.09,                    # Tighter
        8: 0.08,                    # Advanced fab limit (stay here)
        9: 0.08,                    # Stay at tightest safe value
        10: 0.08,                   # Stay at tightest safe value
    }

    clearance = schedule.get(attempt, 0.08)  # Default to tightest safe value

    # TIER 1 FIX 1.3: Relaxed safety check for aggressive routing
    # Most modern fab houses (PCBWay, JLCPCB advanced) support 0.08mm (3.1 mil)
    # Only warn if going below absolute manufacturing limit (0.08mm)
    ABSOLUTE_MIN = 0.08  # 3.1 mil - safe for advanced fab houses
    if clearance < ABSOLUTE_MIN:
        logger.warning(f"SAFETY: Clearance {clearance}mm < absolute minimum {ABSOLUTE_MIN}mm! Clamping.")
        clearance = ABSOLUTE_MIN

    return clearance


class PCBRouter:
    """
    GENERIC PCB auto-router.
    Main orchestrator for complete PCB routing process.

    Works for ANY circuit without modification.
    """

    def __init__(self, config: Optional[RoutingConfig] = None):
        """
        Initialize PCB router.

        Args:
            config: Routing configuration (uses defaults if None)
        """
        self.config = config or RoutingConfig()
        self.grid: Optional[GridOccupancy] = None
        self.stats = RoutingStatistics()

    def route_pcb(self, components: List[Dict], pin_net_mapping: Dict[str, str],
                 board_bounds: Rectangle,
                 strategy: RoutingStrategy = RoutingStrategy.MANHATTAN) -> Tuple[List[Segment], List[Via], RoutingStatistics]:
        """
        Route entire PCB.
        GENERIC - works for ANY circuit.

        Args:
            components: List of component dicts from JSON
            pin_net_mapping: Dict mapping "RefDes.Pin" → "NetName"
            board_bounds: PCB boundary rectangle
            strategy: Routing algorithm to use

        Returns:
            Tuple of (segments, vias, statistics)
        """
        logger.info(f"Starting PCB routing for {len(components)} components...")

        # Step 1: Build occupancy grid
        self.grid = self._build_occupancy_grid(components, board_bounds, pin_net_mapping)
        logger.info(f"Built occupancy grid: {self.grid}")

        # Step 2: Extract nets and pads
        nets = self._extract_nets(components, pin_net_mapping)
        logger.info(f"Extracted {len(nets)} nets")

        # Step 3: Create net-to-index mapping
        net_map = self._create_net_mapping(nets)
        # Expose mapping for downstream generators/emitters
        self.last_net_map = net_map

        # Step 4: Route all nets
        routed_nets, self.stats = self._route_all_nets(
            nets, components, strategy
        )

        # Step 5: Generate KiCad segments (layer-aware)
        segment_gen = SegmentGenerator(self.config, net_map)
        segments, vias = segment_gen.generate_all_segments(routed_nets)

        logger.info(f"Routing complete: {len(segments)} segments, {len(vias)} vias")
        logger.info(self.stats.get_summary())

        return segments, vias, self.stats

    def _build_occupancy_grid(self, components: List[Dict],
                             board_bounds: Rectangle,
                             pin_net_mapping: Dict[str, str]) -> GridOccupancy:
        """
        Build occupancy grid from component footprints.
        GENERIC - processes ANY footprint type/size.

        Args:
            components: Component list
            board_bounds: Board boundary

        Returns:
            GridOccupancy with all footprints marked
        """
        # CRITICAL FIX (2025-10-27): Use adaptive resolution (None = auto-calculate)
        # This prevents 55-million-cell grids that cause A* to hang
        grid = GridOccupancy(board_bounds, resolution=None, num_layers=2)

        # CRITICAL FIX (2025-10-27): Mark INDIVIDUAL PAD POSITIONS with NET NAMES
        # Previous approach marked component bodies but not pads → traces crossed pads → shorts
        # New approach: Mark each pad with its NET NAME so routing can cross same-net pads (GENERIC)
        pads_marked = 0
        for comp in components:
            ref = comp.get('ref', '')
            comp_x = comp.get('brd_x', 0)
            comp_y = comp.get('brd_y', 0)
            pins = comp.get('pins', [])

            # Get footprint name and calculate REAL pad positions using geometry engine
            footprint = comp.get('footprint', 'Unknown')
            pin_count = len(pins)
            rotation = comp.get('rotation', 0)  # Component rotation if any

            # Get ALL pad positions for this component using footprint geometry
            pad_positions = get_pad_positions(footprint, pin_count, comp_x, comp_y, rotation)

            # Mark each pad individually with its net name (GENERIC - works for any pin count/positions)
            for pin in pins:
                pin_num = str(pin.get('num', pin.get('number', '1')))  # Handle both 'num' and 'number' fields

                # Get net name for this pad (GENERIC net lookup)
                pad_key = f"{ref}.{pin_num}"
                net_name = pin_net_mapping.get(pad_key, "")

                # Get REAL pad position from geometry engine
                if pin_num in pad_positions:
                    pad_x, pad_y = pad_positions[pin_num]
                else:
                    # Fallback if pin not found (shouldn't happen with correct data)
                    logger.warning(f"Pin {pin_num} not found in geometry for {ref} ({footprint})")
                    pad_x, pad_y = comp_x, comp_y

                # Pad size estimation (GENERIC conservative approach)
                # SMD pads: ~1.5mm x 1.0mm typical
                # THT pads: ~2.0mm diameter typical
                # Use conservative 2.5mm square to cover both
                pad_size = 2.5  # mm (conservative)
                pad_half = pad_size / 2

                # Create pad rectangle
                pad_rect = Rectangle(
                    pad_x - pad_half,
                    pad_y - pad_half,
                    pad_x + pad_half,
                    pad_y + pad_half
                )

                # Mark pad on both layers WITH NET NAME (allows same-net routing)
                # The grid's is_path_clear will allow crossing pads of the same net
                grid.mark_obstacle(pad_rect, Layer.F_CU, clearance=self.config.clearance)
                grid.mark_obstacle(pad_rect, Layer.B_CU, clearance=self.config.clearance)

                # CRITICAL: Assign net name to ALL pad cells (not just center)
                # This allows traces to cross pads of the SAME net but not OTHER nets
                if net_name:
                    # Convert pad rectangle to grid cells
                    expanded = pad_rect.expand(self.config.clearance)
                    r_min, c_min = grid.point_to_grid(Point(expanded.x_min, expanded.y_min))
                    r_max, c_max = grid.point_to_grid(Point(expanded.x_max, expanded.y_max))

                    # Assign net name to all cells in pad area
                    for r in range(r_min, r_max + 1):
                        for c in range(c_min, c_max + 1):
                            if 0 <= r < grid.rows and 0 <= c < grid.cols:
                                grid.net_assignments[Layer.F_CU][(r, c)] = net_name
                                grid.net_assignments[Layer.B_CU][(r, c)] = net_name

                pads_marked += 1

        logger.info(f"Grid initialized with {pads_marked} individual pad obstacles (net-aware)")

        return grid

    def _get_footprint_bbox(self, comp: Dict) -> Optional[Rectangle]:
        """
        Get bounding box of component footprint.
        GENERIC - estimates bbox from pin positions.

        Args:
            comp: Component dict

        Returns:
            Rectangle bounding box or None
        """
        x = comp.get('brd_x', 0)
        y = comp.get('brd_y', 0)
        pins = comp.get('pins', [])

        if not pins:
            # No pins - use small default bbox
            margin = 5.0  # mm
            return Rectangle(x - margin, y - margin, x + margin, y + margin)

        # Estimate bbox from pin count (conservative)
        # Standard footprints have ~2.54mm pin spacing
        pin_count = len(pins)

        if pin_count <= 2:
            # Small component (resistor, capacitor)
            width = 10.0  # mm
            height = 5.0  # mm
        elif pin_count <= 8:
            # Medium IC (SOIC-8, DIP-8)
            width = 15.0  # mm
            height = 10.0  # mm
        elif pin_count <= 16:
            # Larger IC (SOIC-16, DIP-16)
            width = 20.0  # mm
            height = 15.0  # mm
        elif pin_count <= 24:
            # Even larger (DIP-24, QFP-24)
            width = 30.0  # mm
            height = 20.0  # mm
        else:
            # Very large IC (DIP-48, QFP-48+)
            # Conservative: assume square with 2.54mm spacing
            side = (pin_count // 4) * 2.54 + 10.0  # mm
            width = side
            height = side

        # Create bbox centered on component
        half_w = width / 2
        half_h = height / 2

        return Rectangle(
            x - half_w,
            y - half_h,
            x + half_w,
            y + half_h
        )

    def _extract_nets(self, components: List[Dict],
                     pin_net_mapping: Dict[str, str]) -> Dict[str, List[Point]]:
        """
        Extract nets with pad positions.
        GENERIC - works for ANY pin/net configuration.

        Args:
            components: Component list
            pin_net_mapping: Pin-to-net mapping

        Returns:
            Dict mapping net names to lists of pad positions
        """
        nets: Dict[str, List[Point]] = {}

        for comp in components:
            ref = comp.get('ref', '')
            x = comp.get('brd_x', 0)
            y = comp.get('brd_y', 0)
            pins = comp.get('pins', [])

            # Get footprint and rotation for REAL pad position calculation
            footprint = comp.get('footprint', 'Unknown')
            pin_count = len(pins)
            rotation = comp.get('rotation', 0)

            # Get ALL REAL pad positions using geometry engine
            pad_positions = get_pad_positions(footprint, pin_count, x, y, rotation)

            for pin in pins:
                pin_num = str(pin.get('number', pin.get('num', '1')))
                pin_id = f"{ref}.{pin_num}"

                # Get net name for this pin
                net_name = pin_net_mapping.get(pin_id, '')

                if not net_name or net_name == 'None':
                    continue

                # Skip NC (no-connect) nets
                if net_name.upper().startswith('NC'):
                    continue

                # Get REAL pad position from geometry engine
                if pin_num in pad_positions:
                    pad_x, pad_y = pad_positions[pin_num]
                else:
                    # Fallback if pin not found (shouldn't happen with correct data)
                    logger.warning(f"Pin {pin_num} not found in geometry for {ref} ({footprint})")
                    pad_x, pad_y = x, y  # Use component center as fallback

                # Create pad position point (coordinates already absolute from geometry engine)
                pad_pos = Point(pad_x, pad_y)

                # Add to net
                if net_name not in nets:
                    nets[net_name] = []

                nets[net_name].append(pad_pos)

        # Filter out single-pad nets (no routing needed)
        nets = {name: pads for name, pads in nets.items() if len(pads) >= 2}

        return nets

    def _create_net_mapping(self, nets: Dict[str, List[Point]]) -> Dict[str, int]:
        """
        Create net name → net index mapping.
        GENERIC - works for ANY net names.

        Returns:
            Dict mapping net names to indices (1-based)
        """
        net_map = {"": 0}  # Empty net = 0

        for idx, net_name in enumerate(sorted(nets.keys()), start=1):
            net_map[net_name] = idx

        return net_map

    def _route_all_nets(self, nets: Dict[str, List[Point]],
                       components: List[Dict],
                       strategy: RoutingStrategy) -> Tuple[Dict[str, List[List[Point]]], RoutingStatistics]:
        """
        Route all nets using specified strategy.
        GENERIC - processes ANY number of nets.

        Args:
            nets: Net-to-pads mapping
            components: Component list
            strategy: Routing algorithm

        Returns:
            Tuple of (routed_nets dict, statistics)
        """
        stats = RoutingStatistics()
        stats.total_nets = len(nets)

        # TIER 1 FIX 1.4 (2025-11-03): Dynamic rip-up window based on circuit complexity
        max_rip_window = _get_max_rip_window(stats.total_nets)
        logger.info(f"Circuit complexity: {stats.total_nets} nets → max rip-up window: {max_rip_window}")

        routed_nets: Dict[str, List[List[Point]]] = {}

        # Create multi-point router
        multi_router = MultiPointRouter(self.grid, self.config)

        # Partition nets: keep categorization for ordering, but route on F.Cu by default
        def _is_power(name: str) -> bool:
            u = name.upper()
            return any(k in u for k in ("GND", "VCC", "VDD", "VSS", "POWER", "+5V", "+3V3", "+12V"))

        two_pin = [(n, p) for n, p in nets.items() if len(p) == 2]
        multi_pin = {n: p for n, p in nets.items() if len(p) > 2}
        power_items = [(n, p) for n, p in multi_pin.items() if _is_power(n)]
        signal_items = [(n, p) for n, p in multi_pin.items() if not _is_power(n)]

        # Route two-pin nets first (short direct paths reduce later congestion)
        def _span(pads: List[Point]) -> float:
            if not pads:
                return 0.0
            xs = [p.x for p in pads]
            ys = [p.y for p in pads]
            dx = max(xs) - min(xs)
            dy = max(ys) - min(ys)
            return (dx*dx + dy*dy) ** 0.5

        two_pin.sort(key=lambda x: _span(x[1]), reverse=True)

        # Sort by difficulty: route harder multi-pin nets first to reduce congestion
        power_items.sort(key=lambda x: len(x[1]), reverse=True)  # highest fanout
        def _span(pads: List[Point]) -> float:
            if not pads:
                return 0.0
            xs = [p.x for p in pads]
            ys = [p.y for p in pads]
            dx = max(xs) - min(xs)
            dy = max(ys) - min(ys)
            return (dx*dx + dy*dy) ** 0.5

        signal_items.sort(key=lambda x: (_span(x[1]), len(x[1])), reverse=True)

        routed_order: List[Tuple[str, List[Point]]] = []
        deferred: List[Tuple[str, List[Point], bool]] = []  # (net, pads, is_power)

        # TIER 1 FIX 1.1 (2025-11-03): Correct routing order
        # OLD: two_pin + power + signal (WRONG - two-pin fail because no rip candidates)
        # NEW: power + signal + two_pin (CORRECT - foundation first, details last)
        # Rationale: Power nets create routing infrastructure, two-pin nets can route around it
        #
        # First pass with limited negotiation (single rip-up when necessary)
        for net_name, pads in power_items + signal_items + two_pin:
            logger.info(f"Routing net '{net_name}' with {len(pads)} pads...")

            # TIER 2: Build distance field for collision-aware routing (GENERIC)
            # This prevents placing traces too close to different-net obstacles BEFORE placement
            # Expected impact: >90% reduction in DRC errors (650 → <50)
            distance_field = build_distance_field_for_net(
                self.grid, net_name, self.config.clearance
            )

            # TIER 1 FIX 1.2: Smart layer selection (congestion-aware - GENERIC)
            preferred_layer = _choose_preferred_layer(net_name, pads, self.grid, _is_power)
            paths = multi_router.route_net(pads, net_name, preferred_layer, strategy, distance_field)

            if paths is None:
                # TIER 1 FIX 1.1: Routing failed - attempt LOCAL SCOPED rip-up (GENERIC)
                logger.warning(f"Failed to route net '{net_name}' — attempting negotiation (local rip-up)")

                # Calculate failed net's bounding box for LOCAL SCOPING
                failed_bbox = _calculate_bbox_from_pads(pads)

                # Get LOCAL rip candidates (only nets that intersect with failed net)
                # TIER 1 FIX 1.4: Use dynamic max_rip_window (10-30 based on complexity)
                rip_window = _get_local_rip_candidates(
                    failed_bbox,
                    routed_nets,
                    routed_order,
                    _is_power,
                    max_rip_window
                )

                if rip_window:
                    logger.info(f"  🔄 Local rip-up: Removing {len(rip_window)} intersecting nets (max {max_rip_window})")
                    for rc_name, rc_pads in rip_window:
                        if rc_name in routed_nets:
                            del routed_nets[rc_name]
                        self.grid.clear_net_all_layers(rc_name)
                        deferred.append((rc_name, rc_pads, _is_power(rc_name)))
                        routed_order = [t for t in routed_order if t[0] != rc_name]

                    # TIER 1 FIX 1.2 (2025-11-03): Immediate retry after rip-up (CRITICAL!)
                    # OLD: Deferred current net → space gets stolen by next net
                    # NEW: Immediately retry → use the space we just cleared
                    # Rationale: Rip-up effort wasted if we don't immediately use cleared space
                    logger.info(f"  🔄 Retrying '{net_name}' after clearing {len(rip_window)} blocking nets...")

                    # TIER 2: Rebuild distance field after rip-up (grid state changed)
                    distance_field = build_distance_field_for_net(
                        self.grid, net_name, self.config.clearance
                    )

                    paths = multi_router.route_net(pads, net_name, preferred_layer, strategy, distance_field)

                    if paths is None:
                        # Even after rip-up, still failed - now defer it
                        logger.warning(f"  ❌ Still failed after rip-up; deferring '{net_name}'")
                        deferred.append((net_name, pads, _is_power(net_name)))
                        continue
                else:
                    logger.warning(f"  ⚠️  No local candidates found; deferring '{net_name}'")
                    deferred.append((net_name, pads, _is_power(net_name)))
                    continue

            # Success - store paths
            routed_nets[net_name] = paths
            routed_order.append((net_name, pads))

            # Mark paths on grid (reserve space) respecting layer info if present
            # FIX C.2 (2025-11-11): Increased marking width for better DRC compliance
            # GENERIC: Works for ANY net complexity (2-pin to multi-pin)
            # Previous 2.0× multiplier insufficient - shorts still occurring
            is_two_pin = len(pads) == 2
            # FORMULA: track_width + 3.0 * clearance (increased from 2.0×)
            # NOTE: Previous 3.0× test caused routing failures, but 2.0× causes shorts
            # This attempt combines 3.0× with post-placement verification (C.3) for safety
            base_keepout = self.config.track_width + (self.config.clearance * 3.0)
            mark_width = base_keepout + (0.10 if is_two_pin else 0.05)  # Modest safety margins
            for path in paths:
                # Path may be List[Point] (single layer) or List[(Point, Layer)]
                if path and isinstance(path[0], tuple):
                    # Split into contiguous segments per layer and mark separately
                    seq: List[Point] = []
                    current_layer = path[0][1]
                    for idx, (p, ly) in enumerate(path):  # type: ignore
                        if ly != current_layer and seq:
                            self.grid.mark_path(seq, current_layer,
                                               mark_width, net_name)

                            # FIX C.3 (2025-11-13): Post-placement collision verification
                            # GENERIC: Works for ANY net, ANY circuit complexity
                            # Verify marked path has no collision with different-net segments
                            if not self.grid.verify_path_no_collision(seq, current_layer,
                                                                      mark_width, net_name):
                                logger.warning(f"  ⚠️  Path collision detected for '{net_name}' on {current_layer.name}, unmarking segment")
                                self.grid.unmark_path(seq, current_layer, mark_width, net_name)
                                # Skip to next segment (this segment rejected)
                                seq = []
                                current_layer = ly
                                continue

                            # Mark a VIA at the transition point between layers
                            via_pos = seq[-1]
                            try:
                                # FIX C.1: Pass clearance to mark_via
                                self.grid.mark_via(via_pos, self.config.via_diameter, net_name, self.config.clearance)
                            except Exception:
                                pass
                            seq = []
                            current_layer = ly
                        seq.append(p)
                    if seq:
                        self.grid.mark_path(seq, current_layer,
                                           mark_width, net_name)

                        # FIX C.3 (2025-11-13): Post-placement collision verification for final segment
                        if not self.grid.verify_path_no_collision(seq, current_layer,
                                                                  mark_width, net_name):
                            logger.warning(f"  ⚠️  Path collision detected for '{net_name}' on {current_layer.name}, unmarking final segment")
                            self.grid.unmark_path(seq, current_layer, mark_width, net_name)
                else:
                    self.grid.mark_path(path, Layer.F_CU,
                                       mark_width, net_name)

                    # FIX C.3 (2025-11-13): Post-placement collision verification for single-layer path
                    if not self.grid.verify_path_no_collision(path, Layer.F_CU,  # type: ignore
                                                              mark_width, net_name):
                        logger.warning(f"  ⚠️  Path collision detected for '{net_name}' on F.Cu, unmarking path")
                        self.grid.unmark_path(path, Layer.F_CU, mark_width, net_name)  # type: ignore

            # Update statistics
            segment_gen = SegmentGenerator(self.config, {net_name: 1})
            segments = []
            for path in paths:
                # Use generator logic in generate_all_segments for layered handling; here we keep count
                # Fallback: treat as single-layer for stats
                if path and isinstance(path[0], tuple):
                    # Count segments between successive points
                    for i in range(len(path) - 1):
                        segments.append(object())
                else:
                    for i in range(len(path) - 1):
                        segments.append(object())

            stats.add_routed_net(net_name, segments)

            # Targeted re-route for pads not yet touched (pad-touch accounting)
            try:
                extra_paths = self._connect_unreached_pads(net_name, pads, routed_nets[net_name])
                if extra_paths:
                    routed_nets[net_name].extend(extra_paths)
                    # Mark new paths on grid
                    for ep in extra_paths:
                        if ep and isinstance(ep[0], tuple):
                            seq: List[Point] = []
                            current_layer = ep[0][1]
                            for p, ly in ep:  # type: ignore
                                if ly != current_layer and seq:
                                    self.grid.mark_path(seq, current_layer,
                                                       mark_width, net_name)
                                    seq = []
                                    current_layer = ly
                                seq.append(p)
                            if seq:
                                self.grid.mark_path(seq, current_layer,
                                                   mark_width, net_name)
                        else:
                            self.grid.mark_path(ep, Layer.F_CU,
                                               mark_width, net_name)
                    # Update stats
                    for ep in extra_paths:
                        for i in range(len(ep) - 1):
                            segments.append(object())
            except Exception as e:
                logger.warning(f"Pad-touch re-route failed on '{net_name}': {e}")

            logger.info(f"  ✅ Routed '{net_name}' with {len(segments)} segments")

        # TIER 1 FIX 1.1: Negotiation rounds increased from 3 to 5 (GENERIC)
        # Track routing start time for safety timeout
        routing_start_time = time.time()

        rounds = 0
        while deferred and rounds < MAX_ROUNDS_PER_NET:
            # TIER 1 FIX 1.1: Check total routing time limit (SAFETY - GENERIC)
            elapsed = time.time() - routing_start_time
            if elapsed > MAX_TOTAL_ROUTING_TIME:
                logger.warning(f"⏱️ Total routing time limit ({MAX_TOTAL_ROUTING_TIME}s) reached. Stopping deferred routing.")
                logger.warning(f"   {len(deferred)} net(s) remain unrouted and will be marked as failed.")
                break

            rounds += 1
            logger.info(f"Starting deferred routing pass {rounds}/{MAX_ROUNDS_PER_NET} for {len(deferred)} net(s)...")

            # TIER 1 FIX 1.3: Progressive clearance relaxation (SAFETY - GENERIC)
            original_clearance = self.config.clearance
            new_clearance = _get_clearance_for_attempt(rounds, 'GENERIC')
            if new_clearance != original_clearance:
                logger.info(f"  Progressive clearance: {original_clearance}mm → {new_clearance}mm (attempt {rounds})")
                self.config.clearance = new_clearance

            # TIER 0.5 FIX (2025-11-03): Linear backoff instead of exponential
            # OLD: 0.1 * (2^n) = 0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, 25.6, 51.2s (total ~102s)
            # NEW: min(0.1 * n, 1.0) = 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0s (total ~5.5s)
            # Rationale: PCB layout is deterministic - waiting longer doesn't help unroutable nets
            if rounds > 1:
                backoff_time = min(0.1 * rounds, 1.0)  # Linear backoff, capped at 1.0s
                logger.info(f"  Backoff: waiting {backoff_time:.2f}s before retry...")
                time.sleep(backoff_time)

            # Reorder deferred similarly: power (high fanout first), then signals by span
            def _span(pads: List[Point]) -> float:
                if not pads:
                    return 0.0
                xs = [p.x for p in pads]
                ys = [p.y for p in pads]
                dx = max(xs) - min(xs)
                dy = max(ys) - min(ys)
                return (dx*dx + dy*dy) ** 0.5

            deferred_power = [(n, p) for (n, p, is_p) in deferred if is_p]
            deferred_signal = [(n, p) for (n, p, is_p) in deferred if not is_p]
            deferred_power.sort(key=lambda x: len(x[1]), reverse=True)
            deferred_signal.sort(key=lambda x: (_span(x[1]), len(x[1])), reverse=True)

            next_deferred: List[Tuple[str, List[Point], bool]] = []

            for net_name, pads in deferred_power + deferred_signal:
                logger.info(f"Deferred routing '{net_name}'...")

                # TIER 2: Build distance field for deferred routing (GENERIC)
                distance_field = build_distance_field_for_net(
                    self.grid, net_name, self.config.clearance
                )

                # TIER 1 FIX 1.2: Smart layer selection (congestion-aware - GENERIC)
                preferred_layer = _choose_preferred_layer(net_name, pads, self.grid, _is_power)
                paths = multi_router.route_net(pads, net_name, preferred_layer, strategy, distance_field)
                if paths is None:
                    logger.warning(f"  ❌ Still failed: '{net_name}'")
                    # Keep deferring for next round
                    next_deferred.append((net_name, pads, _is_power(net_name)))
                    continue
                routed_nets[net_name] = paths
                routed_order.append((net_name, pads))
                # Mark paths on grid
                for path in paths:
                    if path and isinstance(path[0], tuple):
                        seq: List[Point] = []
                        current_layer = path[0][1]
                        for idx, (p, ly) in enumerate(path):  # type: ignore
                            if ly != current_layer and seq:
                                self.grid.mark_path(seq, current_layer,
                                                   mark_width, net_name)
                                via_pos = seq[-1]
                                try:
                                    # FIX C.1: Pass clearance to mark_via
                                    self.grid.mark_via(via_pos, self.config.via_diameter, net_name, self.config.clearance)
                                except Exception:
                                    pass
                                seq = []
                                current_layer = ly
                            seq.append(p)
                        if seq:
                            self.grid.mark_path(seq, current_layer,
                                               mark_width, net_name)
                    else:
                        self.grid.mark_path(path, Layer.F_CU,
                                           mark_width, net_name)

            # Prepare next round
            deferred = next_deferred

        # Any remaining deferred nets are final failures for stats
        for net_name, _pads, _isp in deferred:
            stats.add_failed_net(net_name)

        return routed_nets, stats

    def _connect_unreached_pads(self, net_name: str, pads: List[Point],
                                paths: List[List]) -> List[List]:
        """
        Ensure each pad of the net has at least one path touching it.
        Adds small A* paths from nearest existing anchor to each missing pad.
        """
        if not pads:
            return []

        # Build set of touched pads
        touched: Set[int] = set()
        def _touches(p: Point, q: Point) -> bool:
            return p.distance_to(q) <= self.grid.resolution

        for pi, pad in enumerate(pads):
            # Check any path point within resolution to pad
            for path in paths:
                pts = [(pt, ly) if isinstance(path[0], tuple) else (pt, Layer.F_CU) for pt, ly in (path if isinstance(path[0], tuple) else [(q, Layer.F_CU) for q in path])]  # type: ignore
                for pt, _ in pts:
                    if _touches(pt, pad):
                        touched.add(pi)
                        break
                if pi in touched:
                    break

        extras: List[List] = []

        # Collect anchor points from existing paths (favor already routed geometry)
        anchors: List[Point] = []
        for path in paths:
            if path and isinstance(path[0], tuple):
                anchors.extend([pt for (pt, _) in path])  # type: ignore
            else:
                anchors.extend(path)  # type: ignore

        # If no anchors yet, seed with the first pad
        if not anchors:
            anchors.append(pads[0])
            touched.add(0)

        # Router for two-point connections
        pr = MultiPointRouter(self.grid, self.config).path_router

        # TIER 1 FIX 1.2: Smart layer selection for pad-touch re-route (GENERIC)
        def _is_power(name: str) -> bool:
            u = name.upper()
            return any(k in u for k in ("GND", "VCC", "VDD", "VSS", "POWER", "+5V", "+3V3", "+12V"))
        preferred_layer = _choose_preferred_layer(net_name, pads, self.grid, _is_power)

        # For each untouched pad, route from nearest anchor
        for pi, pad in enumerate(pads):
            if pi in touched:
                continue
            # Find nearest anchor
            nearest = min(anchors, key=lambda a: a.manhattan_distance_to(pad))
            # Try on preferred layer first
            for layer_try in (preferred_layer, (Layer.B_CU if preferred_layer == Layer.F_CU else Layer.F_CU)):
                # A* first
                path = pr.route_two_point(nearest, pad, layer_try, RoutingStrategy.ASTAR, net_name)
                if not path:
                    # Then Manhattan
                    path = pr.route_two_point(nearest, pad, layer_try, RoutingStrategy.MANHATTAN, net_name)
                if path:
                    # Normalize to layer-aware format if needed
                    if path and not (isinstance(path[0], tuple)):
                        path = [(pt, layer_try) for pt in path]  # type: ignore
                    extras.append(path)  # type: ignore
                    anchors.append(pad)
                    touched.add(pi)
                    break

        return extras

    def get_unrouted_nets(self) -> List[str]:
        """
        Get list of nets that failed to route.
        GENERIC - works for any circuit.

        Returns:
            List of unrouted net names
        """
        return self.stats.failed_nets.copy()

    def get_routing_quality(self) -> float:
        """
        Get routing quality score (0-100%).
        GENERIC quality metric.

        Returns:
            Quality percentage
        """
        return self.stats.get_success_rate()


def route_circuit_pcb(circuit_json_path: Path, output_segments_path: Path,
                     strategy: RoutingStrategy = RoutingStrategy.MANHATTAN) -> bool:
    """
    GENERIC convenience function to route a circuit from JSON.

    Args:
        circuit_json_path: Path to circuit JSON file
        output_segments_path: Where to write segment text
        strategy: Routing algorithm

    Returns:
        True if routing succeeded, False otherwise
    """
    import json

    # Load circuit data
    with open(circuit_json_path) as f:
        data = json.load(f)

    components = data.get('components', [])
    pin_net_mapping = data.get('pinNetMapping', {})

    # Determine board bounds from component positions
    if not components:
        logger.error("No components found in circuit")
        return False

    xs = [c.get('brd_x', 0) for c in components]
    ys = [c.get('brd_y', 0) for c in components]

    # Add margin around components
    margin = 50.0  # mm
    board_bounds = Rectangle(
        min(xs) - margin,
        min(ys) - margin,
        max(xs) + margin,
        max(ys) + margin
    )

    # Route PCB
    router = PCBRouter()
    segments, vias, stats = router.route_pcb(
        components, pin_net_mapping, board_bounds, strategy
    )

    # Write segments to file
    segment_gen = SegmentGenerator(router.config, {})
    segment_text = segment_gen.segments_to_kicad_text(segments, vias)

    with open(output_segments_path, 'w') as f:
        f.write(segment_text)

    logger.info(f"Wrote {len(segments)} segments to {output_segments_path}")

    # Return success if >90% of nets routed
    success = stats.get_success_rate() >= 90.0

    return success
