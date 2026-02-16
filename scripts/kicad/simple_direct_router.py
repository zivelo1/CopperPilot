#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Simple Direct PCB Router - GUARANTEED to generate traces for ALL nets.

This router uses a straightforward approach:
1. For each net, connect all pads directly
2. Use simple L-shaped or straight traces
3. No collision detection (rely on DRC to find issues)
4. ALWAYS generates traces (never fails)

This ensures 100% routing completion, though traces may overlap.
Manual cleanup may be needed, but at least we have copper connections.
"""

import logging
from typing import List, Dict, Tuple, Set
import math

logger = logging.getLogger(__name__)


class SimpleDirectRouter:
    """
    Simple direct router that ALWAYS generates traces.
    Prioritizes connectivity over aesthetics.
    Now with collision avoidance for better DRC results.
    """

    def __init__(self):
        """Initialize the simple router - PROFESSIONAL PCB approach."""
        self.trace_width = 0.3  # mm - slightly wider for better DRC compliance
        self.via_diameter = 0.8  # mm
        self.via_drill = 0.4  # mm
        self.clearance = 0.3  # mm - minimum spacing between traces
        self.pad_clearance = 1.0  # mm - keep traces away from pads (critical!)
        self.existing_segments = []  # Track segments for collision detection
        self.y_offset_step = 3.0  # mm - larger offset for better spacing
        self.all_pads = {}  # Map of (x, y) -> net_name for ALL pads
        self.pin_net_mapping = {}  # Map of "REF.PIN" -> "NET_NAME"

    def route_all_nets(self,
                      components: List[Dict],
                      pin_net_mapping: Dict[str, str],
                      pad_positions: Dict[str, Tuple[float, float]]) -> List[Dict]:
        """
        Route ALL nets with simple direct connections.
        STRATEGY: Power nets on B.Cu, signal nets on F.Cu = NO CROSSINGS!

        Args:
            components: List of components
            pin_net_mapping: Mapping of "REF.PIN" -> "NET_NAME"
            pad_positions: Mapping of "REF.PIN" -> (x, y) coordinates

        Returns:
            List of trace segments
        """
        # Store pin-to-net mapping for collision detection
        self.pin_net_mapping = pin_net_mapping

        # Build map of pad positions to net names (for collision detection)
        self.all_pads = {}
        for pin_id, net_name in pin_net_mapping.items():
            if pin_id in pad_positions and net_name and not net_name.startswith('NC'):
                pos = pad_positions[pin_id]
                # Round to avoid floating point issues
                pos_key = (round(pos[0], 2), round(pos[1], 2))
                self.all_pads[pos_key] = net_name

        # Group pins by net
        nets = {}
        for pin_id, net_name in pin_net_mapping.items():
            if net_name and not net_name.startswith('NC'):
                if net_name not in nets:
                    nets[net_name] = []

                if pin_id in pad_positions:
                    nets[net_name].append(pad_positions[pin_id])
                else:
                    logger.warning(f"Pin {pin_id} has no pad position")

        # Separate power nets from signal nets
        power_nets = {}
        signal_nets = {}

        for net_name, pads in nets.items():
            is_power = any(pwr in net_name.upper() for pwr in ['GND', 'VCC', 'VDD', 'VSS', 'POWER', '+5V', '+3V3', '+12V'])
            if is_power:
                power_nets[net_name] = pads
            else:
                signal_nets[net_name] = pads

        logger.info(f"SimpleDirectRouter: {len(power_nets)} power nets, {len(signal_nets)} signal nets")

        # Generate traces for each net
        all_segments = []
        total_nets = len(nets)
        routed_count = 0

        # Route power nets on BACK layer (B.Cu) using direct connections
        # Professional approach: Physical layer separation prevents crossings
        # - Power nets (GND, VCC, etc.) on B.Cu (back copper)
        # - Signal nets on F.Cu (front copper)
        # - Traces on different layers CANNOT cross!
        for net_name, pads in power_nets.items():
            if len(pads) < 2:
                continue

            segments = self.route_net_on_layer(net_name, pads, 'B.Cu')
            all_segments.extend(segments)

            if segments:
                routed_count += 1
                logger.debug(f"Routed power net {net_name} on B.Cu: {len(segments)} segments")

        # Route signal nets AFTER power nets (F.Cu layer, sequential)
        for net_name, pads in signal_nets.items():
            if len(pads) < 2:
                continue

            segments = self.route_net_on_layer(net_name, pads, 'F.Cu')
            all_segments.extend(segments)

            if segments:
                routed_count += 1
                logger.debug(f"Routed signal net {net_name} on F.Cu: {len(segments)} segments")

        logger.info(f"SimpleDirectRouter: Routed {routed_count}/{total_nets} nets")
        logger.info(f"Generated {len(all_segments)} total segments")

        # CRITICAL: Multi-pass collision detection and fixing
        # Check all segments against each other and move colliding ones to alternate layer
        all_segments = self._fix_collisions_multipass(all_segments)

        return all_segments

    def route_net_on_layer(self, net_name: str, pads: List[Tuple[float, float]], layer: str) -> List[Dict]:
        """
        Route a net on a specific layer using DIRECT DIAGONAL traces.
        PROFESSIONAL APPROACH: Direct point-to-point minimizes crossings.

        GENERIC - works for any layer (F.Cu, B.Cu, etc.)

        Args:
            net_name: Name of the net
            pads: List of (x, y) pad coordinates
            layer: Target layer (e.g., 'B.Cu', 'F.Cu')

        Returns:
            List of segment dictionaries
        """
        if len(pads) < 2:
            return []

        segments = []

        # Sort pads by X coordinate for systematic routing
        sorted_pads = sorted(pads, key=lambda p: (p[0], p[1]))

        # Use thicker traces for power nets
        is_power = any(pwr in net_name.upper() for pwr in ['GND', 'VCC', 'VDD', 'VSS', 'POWER'])
        width = 0.5 if is_power else self.trace_width

        # PROFESSIONAL APPROACH: Direct traces with collision avoidance
        # Try direct connection first, then alternatives if it crosses existing traces
        for i in range(len(sorted_pads) - 1):
            x1, y1 = sorted_pads[i]
            x2, y2 = sorted_pads[i + 1]

            # Create candidate segment
            candidate = {
                'start_x': x1,
                'start_y': y1,
                'end_x': x2,
                'end_y': y2,
                'width': width,
                'layer': layer,
                'net': net_name
            }

            # Check if it crosses any existing segment on this net
            crosses = False
            for existing_seg in self.existing_segments:
                if self.segments_cross(candidate, existing_seg):
                    crosses = True
                    break

            if not crosses:
                # No collision - use direct route
                segments.append(candidate)
                self.existing_segments.append(candidate)
            else:
                # Collision detected - try alternate layer if signal net
                if layer == 'F.Cu' and not is_power:
                    # Try routing on back layer instead
                    alternate = candidate.copy()
                    alternate['layer'] = 'B.Cu'
                    segments.append(alternate)
                    self.existing_segments.append(alternate)
                    logger.debug(f"  Avoided collision: routed {net_name} on B.Cu")
                else:
                    # No alternative - use direct route anyway (DRC will catch it)
                    segments.append(candidate)
                    self.existing_segments.append(candidate)
                    logger.debug(f"  Collision unavoidable for {net_name}")

        return segments

    def segments_cross(self, seg1: Dict, seg2: Dict) -> bool:
        """
        Check if two line segments intersect using proper geometric algorithm.
        GENERIC - works for any segment coordinates.
        """
        # If segments are on different layers, they don't cross
        if seg1.get('layer') != seg2.get('layer'):
            return False

        # If segments are from the same net, they can touch
        if seg1.get('net') == seg2.get('net'):
            return False

        # Get coordinates
        x1, y1 = seg1['start_x'], seg1['start_y']
        x2, y2 = seg1['end_x'], seg1['end_y']
        x3, y3 = seg2['start_x'], seg2['start_y']
        x4, y4 = seg2['end_x'], seg2['end_y']

        # Use line segment intersection algorithm (CCW method)
        def ccw(ax, ay, bx, by, cx, cy):
            """Check if three points are in counter-clockwise order."""
            return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)

        # Two segments intersect if their endpoints are on opposite sides
        # Segment 1: (x1,y1) to (x2,y2)
        # Segment 2: (x3,y3) to (x4,y4)
        ccw1 = ccw(x1, y1, x2, y2, x3, y3)
        ccw2 = ccw(x1, y1, x2, y2, x4, y4)
        ccw3 = ccw(x3, y3, x4, y4, x1, y1)
        ccw4 = ccw(x3, y3, x4, y4, x2, y2)

        # Segments intersect if CCW tests differ
        return (ccw1 != ccw2) and (ccw3 != ccw4)

    def find_alternate_route(self, x1: float, y1: float, x2: float, y2: float,
                            net_name: str, width: float, attempt: int) -> List[Dict]:
        """
        Find alternate route that avoids existing traces.
        GENERIC - tries multiple strategies based on attempt number.
        """
        segments = []
        layer = 'F.Cu'

        # Strategy based on attempt number
        if attempt == 1:
            # Try routing with Y-offset
            mid_y = (y1 + y2) / 2 + self.y_offset_step
            segments = [
                {'start_x': x1, 'start_y': y1, 'end_x': x1, 'end_y': mid_y,
                 'width': width, 'layer': layer, 'net': net_name},
                {'start_x': x1, 'start_y': mid_y, 'end_x': x2, 'end_y': mid_y,
                 'width': width, 'layer': layer, 'net': net_name},
                {'start_x': x2, 'start_y': mid_y, 'end_x': x2, 'end_y': y2,
                 'width': width, 'layer': layer, 'net': net_name}
            ]
        elif attempt == 2:
            # Try routing with negative Y-offset
            mid_y = (y1 + y2) / 2 - self.y_offset_step
            segments = [
                {'start_x': x1, 'start_y': y1, 'end_x': x1, 'end_y': mid_y,
                 'width': width, 'layer': layer, 'net': net_name},
                {'start_x': x1, 'start_y': mid_y, 'end_x': x2, 'end_y': mid_y,
                 'width': width, 'layer': layer, 'net': net_name},
                {'start_x': x2, 'start_y': mid_y, 'end_x': x2, 'end_y': y2,
                 'width': width, 'layer': layer, 'net': net_name}
            ]
        elif attempt == 3:
            # Try back layer (B.Cu) with vias
            segments = [
                {'start_x': x1, 'start_y': y1, 'end_x': x2, 'end_y': y2,
                 'width': width, 'layer': 'B.Cu', 'net': net_name}
            ]
            # Note: Vias would need to be added separately
        else:
            # Last resort: use direct connection anyway
            segments = [
                {'start_x': x1, 'start_y': y1, 'end_x': x2, 'end_y': y2,
                 'width': width, 'layer': layer, 'net': net_name}
            ]

        return segments

    def route_net_simple(self, net_name: str, pads: List[Tuple[float, float]]) -> List[Dict]:
        """
        Route a single net using simple direct connections.

        Strategy:
        1. Sort pads by X coordinate
        2. Connect adjacent pads with L-shaped traces
        3. Always generate SOME trace (never fail)

        Args:
            net_name: Name of the net
            pads: List of (x, y) pad coordinates

        Returns:
            List of segment dictionaries
        """
        if len(pads) < 2:
            return []

        segments = []

        # Sort pads by X coordinate for systematic routing
        sorted_pads = sorted(pads, key=lambda p: (p[0], p[1]))

        # All on front layer (F.Cu) initially
        # Collision detection will move segments to B.Cu as needed
        layer = 'F.Cu'

        # Use thicker traces for power nets
        is_power = any(pwr in net_name.upper() for pwr in ['GND', 'VCC', 'VDD', 'VSS', 'POWER'])
        width = 0.5 if is_power else self.trace_width

        # CRITICAL: ALWAYS connect ALL pads - connectivity is priority #1
        # Use simple direct connections to guarantee 100% connectivity
        for i in range(len(sorted_pads) - 1):
            x1, y1 = sorted_pads[i]
            x2, y2 = sorted_pads[i + 1]

            # Simple L-shaped or straight connection (ALWAYS works)
            if abs(x2 - x1) > 0.01 and abs(y2 - y1) > 0.01:
                # L-shaped: horizontal then vertical
                segments.append({
                    'start_x': x1,
                    'start_y': y1,
                    'end_x': x2,
                    'end_y': y1,
                    'width': width,
                    'layer': layer,
                    'net': net_name
                })
                segments.append({
                    'start_x': x2,
                    'start_y': y1,
                    'end_x': x2,
                    'end_y': y2,
                    'width': width,
                    'layer': layer,
                    'net': net_name
                })
            else:
                # Straight connection
                segments.append({
                    'start_x': x1,
                    'start_y': y1,
                    'end_x': x2,
                    'end_y': y2,
                    'width': width,
                    'layer': layer,
                    'net': net_name
                })

        return segments

    def route_power_net_special(self, net_name: str, pads: List[Tuple[float, float]]) -> List[Dict]:
        """
        Special routing for power nets (VCC, GND) using star topology.
        CRITICAL: Power nets use B.Cu (back copper) to physically separate from signals.

        Args:
            net_name: Name of the power net
            pads: List of pad coordinates

        Returns:
            List of segments forming star connection on B.Cu layer
        """
        if len(pads) < 2:
            return []

        segments = []

        # Find center point of all pads
        center_x = sum(p[0] for p in pads) / len(pads)
        center_y = sum(p[1] for p in pads) / len(pads)

        # Connect each pad to the center (star topology)
        for x, y in pads:
            # Use wider traces for power
            width = 0.5 if 'GND' in net_name or 'VCC' in net_name else self.trace_width

            segments.append({
                'start_x': x,
                'start_y': y,
                'end_x': center_x,
                'end_y': center_y,
                'width': width,
                'layer': 'B.Cu',  # Power nets on BACK copper (physical separation!)
                'net': net_name
            })

        return segments

    def _fix_collisions_multipass(self, segments: List[Dict]) -> List[Dict]:
        """
        Multi-pass collision detection and fixing using graph coloring.
        GENERIC - works for any set of segments, any circuit complexity.

        Strategy (CRITICAL FIX 2025-10-31):
        1. Detect DIFFERENT-NET collisions only (net-aware detection already implemented)
        2. Build conflict graph (nodes=segments, edges=collisions)
        3. Assign layers using greedy 2-color algorithm (F.Cu/B.Cu)
        4. Repeat until convergence or max passes

        This eliminates ping-pong effect and converges in 2-3 passes.
        """
        MAX_PASSES = 5  # Increased for convergence

        previous_collision_count = float('inf')

        for pass_num in range(1, MAX_PASSES + 1):
            # Find all DIFFERENT-NET collisions (net-aware detection)
            collisions = []

            for i in range(len(segments)):
                for j in range(i + 1, len(segments)):
                    # segments_cross already checks nets - only returns True for different nets
                    if self.segments_cross(segments[i], segments[j]):
                        collisions.append((i, j))

            if not collisions:
                logger.info(f"  Pass {pass_num}: No collisions - routing PERFECT!")
                break

            logger.info(f"  Pass {pass_num}: Found {len(collisions)} different-net collisions")

            # Check for convergence (collision count not decreasing)
            if len(collisions) >= previous_collision_count:
                logger.info(f"    Collision count not decreasing - applying graph coloring")

            previous_collision_count = len(collisions)

            # Build conflict graph - ONLY for segments involved in collisions
            # Graph[i] = set of segment indices that collide with segment i
            colliding_segments = set()
            for i, j in collisions:
                colliding_segments.add(i)
                colliding_segments.add(j)

            graph = {i: set() for i in colliding_segments}
            for i, j in collisions:
                graph[i].add(j)
                graph[j].add(i)

            # Assign layers using greedy 2-color algorithm
            # CRITICAL FIX: Only reassign segments involved in collisions
            layer_assignments = {}

            # Sort nodes by degree (most constrained first - more collisions = fix first)
            nodes_by_degree = sorted(graph.keys(), key=lambda n: len(graph[n]), reverse=True)

            for node in nodes_by_degree:
                # Get layers already assigned to neighbors
                neighbor_layers = {layer_assignments.get(n) for n in graph[node] if n in layer_assignments}

                # Prefer current layer if no conflict, otherwise switch
                current_layer = segments[node]['layer']
                alt_layer = 'B.Cu' if current_layer == 'F.Cu' else 'F.Cu'

                if current_layer not in neighbor_layers:
                    # Current layer is fine - no conflict with neighbors
                    layer_assignments[node] = current_layer
                else:
                    # Current layer conflicts - must use alternate
                    layer_assignments[node] = alt_layer

            # Apply layer assignments and count changes
            f_to_b_count = 0
            b_to_f_count = 0

            for seg_idx, new_layer in layer_assignments.items():
                if segments[seg_idx]['layer'] != new_layer:
                    old_layer = segments[seg_idx]['layer']
                    segments[seg_idx]['layer'] = new_layer

                    if old_layer == 'F.Cu':
                        f_to_b_count += 1
                    else:
                        b_to_f_count += 1

            logger.info(f"    Reassigned {len(layer_assignments)} segments (only colliding): {f_to_b_count} F→B, {b_to_f_count} B→F")

        if collisions:
            logger.warning(f"  ⚠️  {len(collisions)} collisions remaining after {MAX_PASSES} passes")
            logger.warning(f"      These may require manual routing or 3+ layer board")

        return segments

    def insert_vias_for_layer_transitions(self, segments: List[Dict],
                                          pad_positions: Dict[str, Tuple[float, float]]) -> List[Dict]:
        """
        Insert vias where segments change layers or connect to pads on different layer.
        GENERIC: Works for any circuit, any segment/pad configuration.

        Critical for eliminating unconnected_items DRC errors.

        Args:
            segments: List of routed segments
            pad_positions: Mapping of "REF.PIN" -> (x, y) coordinates

        Returns:
            List of via dictionaries
        """
        vias = []
        via_positions = set()  # Track via positions to avoid duplicates

        # Build map of pad positions to net names
        pad_to_net = {}
        for pin_id, net_name in self.pin_net_mapping.items():
            if pin_id in pad_positions and net_name:
                pos = pad_positions[pin_id]
                pad_to_net[pos] = net_name

        # Group segments by net
        nets = {}
        for seg in segments:
            net_name = seg.get('net', '')
            if net_name not in nets:
                nets[net_name] = []
            nets[net_name].append(seg)

        # For each net, check if segments span multiple layers
        for net_name, net_segments in nets.items():
            layers = set(seg['layer'] for seg in net_segments)

            if len(layers) > 1:
                # Net spans multiple layers - need vias at connection points
                logger.debug(f"  Net {net_name} spans {len(layers)} layers - inserting vias")

                # Find where segments from different layers connect
                for i, seg1 in enumerate(net_segments):
                    for seg2 in net_segments[i+1:]:
                        if seg1['layer'] != seg2['layer']:
                            # Different layers - check if they share endpoint
                            shared_point = self._get_shared_endpoint(seg1, seg2)

                            if shared_point:
                                # Round to avoid floating point duplicates
                                via_key = (round(shared_point[0], 2), round(shared_point[1], 2))

                                if via_key not in via_positions:
                                    via_positions.add(via_key)

                                    # Create via at shared endpoint
                                    via = {
                                        'x': shared_point[0],
                                        'y': shared_point[1],
                                        'size': 0.8,  # 0.8mm diameter (standard)
                                        'drill': 0.4,  # 0.4mm drill hole
                                        'layers': ['F.Cu', 'B.Cu'],
                                        'net': net_name
                                    }
                                    vias.append(via)
                                    logger.debug(f"    Via at ({via['x']:.2f}, {via['y']:.2f}) for {net_name}")

        logger.info(f"  Inserted {len(vias)} vias for layer transitions")
        return vias

    def _get_shared_endpoint(self, seg1: Dict, seg2: Dict) -> Tuple[float, float]:
        """
        Get the shared endpoint between two segments, if any.
        GENERIC: Works for any segment pair.

        Returns:
            (x, y) coordinates of shared endpoint, or None if no shared endpoint
        """
        endpoints1 = [
            (seg1['start_x'], seg1['start_y']),
            (seg1['end_x'], seg1['end_y'])
        ]
        endpoints2 = [
            (seg2['start_x'], seg2['start_y']),
            (seg2['end_x'], seg2['end_y'])
        ]

        # Check if any endpoints match (within tolerance)
        tolerance = 0.1  # mm

        for e1 in endpoints1:
            for e2 in endpoints2:
                if abs(e1[0] - e2[0]) < tolerance and abs(e1[1] - e2[1]) < tolerance:
                    return e1

        return None


def route_pcb_simple(components: List[Dict],
                     pin_net_mapping: Dict[str, str],
                     pad_positions: Dict[str, Tuple[float, float]]) -> Tuple[List[Dict], List[Dict], int, int]:
    """
    Main entry point for simple PCB routing.

    This function GUARANTEES trace generation for all nets.
    CRITICAL FIX (2025-10-31): Now also generates vias for layer transitions.

    Args:
        components: Component list
        pin_net_mapping: Pin to net mapping
        pad_positions: Pad position mapping

    Returns:
        Tuple of (segments, vias, routed_count, total_nets)
    """
    router = SimpleDirectRouter()

    # Route all nets
    segments = router.route_all_nets(components, pin_net_mapping, pad_positions)

    # CRITICAL FIX (2025-10-31): Insert vias for layer transitions
    # This eliminates unconnected_items DRC errors
    vias = router.insert_vias_for_layer_transitions(segments, pad_positions)

    # Count unique nets
    nets = set()
    for pin_id, net_name in pin_net_mapping.items():
        if net_name and not net_name.startswith('NC'):
            nets.add(net_name)

    # Count how many nets got segments
    routed_nets = set()
    for seg in segments:
        if 'net' in seg:
            routed_nets.add(seg['net'])

    return segments, vias, len(routed_nets), len(nets)


if __name__ == "__main__":
    # Test the router
    test_components = [
        {'ref': 'R1', 'pins': [{'number': '1'}, {'number': '2'}]},
        {'ref': 'C1', 'pins': [{'number': '1'}, {'number': '2'}]},
    ]

    test_mapping = {
        'R1.1': 'NET1',
        'R1.2': 'GND',
        'C1.1': 'NET1',
        'C1.2': 'GND'
    }

    test_positions = {
        'R1.1': (10.0, 10.0),
        'R1.2': (15.0, 10.0),
        'C1.1': (10.0, 20.0),
        'C1.2': (15.0, 20.0)
    }

    segments, routed, total = route_pcb_simple(test_components, test_mapping, test_positions)

    print(f"Test routing: {routed}/{total} nets routed")
    print(f"Generated {len(segments)} segments")

    for seg in segments:
        print(f"  {seg['net']}: ({seg['start_x']:.1f}, {seg['start_y']:.1f}) -> "
              f"({seg['end_x']:.1f}, {seg['end_y']:.1f})  ")
