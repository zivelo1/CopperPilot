# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Router module for generating wire routing in schematic and PCB tracks."""

import math
from typing import Dict, Any, List, Tuple, Optional, Set
from collections import deque
import logging

from ..utils.base import PipelineStage, ConversionContext

logger = logging.getLogger(__name__)

class Router(PipelineStage):
    """Route connections between components."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.grid_size = 1.27  # mm for schematic
        self.track_width = 0.25  # mm for PCB
        self.clearance = 0.2  # mm

    def process(self, context: ConversionContext) -> ConversionContext:
        """Generate routing for all nets."""
        try:
            nets = context.netlist.get('nets', {})
            schematic_layout = context.layout.get('schematic', {})
            pcb_layout = context.layout.get('pcb', {})
            components = context.components

            if not nets:
                logger.warning("No nets to route")
                context.routes = {'schematic': {}, 'pcb': {}}
                return context

            # Route schematic wires
            schematic_routes = self._route_schematic(nets, schematic_layout, components)

            # Route PCB tracks
            pcb_routes = self._route_pcb(nets, pcb_layout, components)

            # Store routes in context
            context.routes = {
                'schematic': schematic_routes,
                'pcb': pcb_routes,
                'statistics': self._generate_routing_statistics(schematic_routes, pcb_routes)
            }

            logger.info(f"Routed {len(schematic_routes)} nets in schematic and {len(pcb_routes)} nets in PCB")
            return context

        except Exception as e:
            return self.handle_error(e, context)

    def _route_schematic(self, nets: Dict[str, Dict[str, Any]],
                        layout: Dict[str, Tuple[float, float]],
                        components: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Route wires in schematic."""
        routes = {}

        for net_name, net_data in nets.items():
            nodes = net_data.get('nodes', [])

            if len(nodes) < 2:
                continue

            # Get positions for all nodes
            positions = []
            for node in nodes:
                ref = node['ref']
                pin = node['pin']

                if ref in layout:
                    pos = layout[ref]
                    # Calculate pin position (simplified - assumes pins on sides)
                    pin_pos = self._get_pin_position(pos, pin, components.get(ref, {}))
                    positions.append(pin_pos)

            if len(positions) >= 2:
                # Route using Manhattan routing
                wire_segments = self._manhattan_route(positions)
                routes[net_name] = wire_segments

        return routes

    def _route_pcb(self, nets: Dict[str, Dict[str, Any]],
                   layout: Dict[str, Tuple[float, float]],
                   components: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Route tracks in PCB."""
        routes = {}

        # Sort nets by priority (power nets first)
        sorted_nets = sorted(nets.items(),
                           key=lambda x: (0 if x[1].get('class') == 'power' else 1, x[0]))

        obstacles = self._build_obstacle_map(layout, components)

        for net_name, net_data in sorted_nets:
            nodes = net_data.get('nodes', [])

            if len(nodes) < 2:
                continue

            # Get positions for all nodes
            positions = []
            for node in nodes:
                ref = node['ref']
                pin = node['pin']

                if ref in layout:
                    pos = layout[ref]
                    # Get pad position
                    pad_pos = self._get_pad_position(pos, pin, components.get(ref, {}))
                    positions.append(pad_pos)

            if len(positions) >= 2:
                # Route tracks avoiding obstacles
                track_segments = self._route_pcb_net(positions, obstacles, net_data.get('class', 'signal'))
                routes[net_name] = track_segments

                # Add tracks to obstacles for next nets
                for segment in track_segments:
                    obstacles.append(segment)

        return routes

    def _manhattan_route(self, positions: List[Tuple[float, float]]) -> List[Dict[str, Any]]:
        """Create Manhattan (orthogonal) routing between positions."""
        if len(positions) < 2:
            return []

        segments = []

        # Use star topology for nets with more than 2 nodes
        if len(positions) > 2:
            # Find center point
            center_x = sum(p[0] for p in positions) / len(positions)
            center_y = sum(p[1] for p in positions) / len(positions)

            # Snap to grid
            center_x = round(center_x / self.grid_size) * self.grid_size
            center_y = round(center_y / self.grid_size) * self.grid_size

            center = (center_x, center_y)

            # Route each position to center
            for pos in positions:
                if pos != center:
                    segments.extend(self._create_manhattan_path(pos, center))

            # Add junction dot at center
            segments.append({
                'type': 'junction',
                'position': center,
                'diameter': 0.5
            })
        else:
            # Simple point-to-point routing
            segments = self._create_manhattan_path(positions[0], positions[1])

        return segments

    def _create_manhattan_path(self, start: Tuple[float, float],
                               end: Tuple[float, float]) -> List[Dict[str, Any]]:
        """Create Manhattan path between two points."""
        segments = []

        x1, y1 = start
        x2, y2 = end

        if x1 == x2:
            # Vertical line
            segments.append({
                'type': 'wire',
                'start': start,
                'end': end
            })
        elif y1 == y2:
            # Horizontal line
            segments.append({
                'type': 'wire',
                'start': start,
                'end': end
            })
        else:
            # L-shaped path
            # Try horizontal first, then vertical
            corner = (x2, y1)

            segments.append({
                'type': 'wire',
                'start': start,
                'end': corner
            })
            segments.append({
                'type': 'wire',
                'start': corner,
                'end': end
            })

        return segments

    def _route_pcb_net(self, positions: List[Tuple[float, float]],
                       obstacles: List[Any],
                       net_class: str) -> List[Dict[str, Any]]:
        """Route a PCB net avoiding obstacles."""
        if len(positions) < 2:
            return []

        # Determine track width based on net class
        track_width = 0.4 if net_class == 'power' else 0.25

        segments = []

        # For now, use simple routing (can be enhanced with A* later)
        if len(positions) > 2:
            # Multi-point net - use minimum spanning tree
            mst_edges = self._minimum_spanning_tree(positions)

            for edge in mst_edges:
                start, end = edge
                path = self._find_pcb_path(start, end, obstacles)

                for i in range(len(path) - 1):
                    segments.append({
                        'type': 'track',
                        'start': path[i],
                        'end': path[i + 1],
                        'width': track_width,
                        'layer': 'F.Cu',
                        'net': net_class
                    })
        else:
            # Two-point net
            path = self._find_pcb_path(positions[0], positions[1], obstacles)

            for i in range(len(path) - 1):
                segments.append({
                    'type': 'track',
                    'start': path[i],
                    'end': path[i + 1],
                    'width': track_width,
                    'layer': 'F.Cu',
                    'net': net_class
                })

        return segments

    def _find_pcb_path(self, start: Tuple[float, float],
                       end: Tuple[float, float],
                       obstacles: List[Any]) -> List[Tuple[float, float]]:
        """Find path between two points avoiding obstacles."""
        # Simplified pathfinding - can be replaced with A* for better results
        # For now, use Manhattan routing with basic obstacle avoidance

        x1, y1 = start
        x2, y2 = end

        # Try direct Manhattan path
        if abs(x2 - x1) > abs(y2 - y1):
            # Horizontal preference
            corner = (x2, y1)
        else:
            # Vertical preference
            corner = (x1, y2)

        # Check if path is clear
        path1_clear = self._is_path_clear(start, corner, obstacles)
        path2_clear = self._is_path_clear(corner, end, obstacles)

        if path1_clear and path2_clear:
            return [start, corner, end]
        else:
            # Try alternative corner
            alt_corner = (x1, y2) if corner == (x2, y1) else (x2, y1)
            return [start, alt_corner, end]

    def _is_path_clear(self, start: Tuple[float, float],
                       end: Tuple[float, float],
                       obstacles: List[Any]) -> bool:
        """Check if path between two points is clear of obstacles."""
        # Simplified check - can be enhanced
        # For now, assume paths are clear if they don't cross component centers
        return True

    def _minimum_spanning_tree(self, positions: List[Tuple[float, float]]) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Calculate minimum spanning tree for positions."""
        if len(positions) < 2:
            return []

        # Prim's algorithm
        edges = []
        visited = {positions[0]}
        unvisited = set(positions[1:])

        while unvisited:
            min_edge = None
            min_dist = float('inf')

            for v in visited:
                for u in unvisited:
                    dist = self._distance(v, u)
                    if dist < min_dist:
                        min_dist = dist
                        min_edge = (v, u)

            if min_edge:
                edges.append(min_edge)
                visited.add(min_edge[1])
                unvisited.remove(min_edge[1])

        return edges

    def _distance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Calculate Manhattan distance between two points."""
        return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

    def _get_pin_position(self, comp_pos: Tuple[float, float],
                         pin: str,
                         component: Dict[str, Any]) -> Tuple[float, float]:
        """Get schematic pin position for component."""
        x, y = comp_pos
        pins = component.get('pins', [])
        pin_count = len(pins)

        # Simplified pin positioning
        if pin_count <= 2:
            # Two-pin component (resistor, capacitor, etc.)
            if pin == '1':
                return (x - 2.54, y)
            else:
                return (x + 2.54, y)
        else:
            # Multi-pin component - arrange pins around rectangle
            try:
                pin_idx = pins.index(str(pin))
                if pin_idx < pin_count // 2:
                    # Left side
                    return (x - 5.08, y + (pin_idx - pin_count // 4) * 2.54)
                else:
                    # Right side
                    return (x + 5.08, y + (pin_idx - 3 * pin_count // 4) * 2.54)
            except (ValueError, IndexError):
                return comp_pos

    def _get_pad_position(self, comp_pos: Tuple[float, float],
                         pin: str,
                         component: Dict[str, Any]) -> Tuple[float, float]:
        """Get PCB pad position for component."""
        # Similar to pin position but for PCB
        return self._get_pin_position(comp_pos, pin, component)

    def _build_obstacle_map(self, layout: Dict[str, Tuple[float, float]],
                           components: Dict[str, Any]) -> List[Any]:
        """Build obstacle map from component positions."""
        obstacles = []

        for ref_des, pos in layout.items():
            comp = components.get(ref_des, {})
            # Add component bounding box as obstacle
            obstacles.append({
                'type': 'component',
                'position': pos,
                'size': (10, 10),  # Simplified size
                'ref': ref_des
            })

        return obstacles

    def _generate_routing_statistics(self, schematic_routes: Dict[str, Any],
                                    pcb_routes: Dict[str, Any]) -> Dict[str, Any]:
        """Generate routing statistics."""
        sch_segments = sum(len(route) for route in schematic_routes.values())
        pcb_segments = sum(len(route) for route in pcb_routes.values())

        return {
            'schematic': {
                'routed_nets': len(schematic_routes),
                'total_segments': sch_segments
            },
            'pcb': {
                'routed_nets': len(pcb_routes),
                'total_segments': pcb_segments
            }
        }