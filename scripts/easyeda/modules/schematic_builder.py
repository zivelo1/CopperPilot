# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Schematic builder module for EasyEDA converter."""
from typing import Dict, List, Any, Tuple
from .utils import EasyEDAContext, Point, generate_id, mm_to_easyeda

class SchematicBuilder:
    """Build EasyEDA schematic from components and connections."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.grid_size = 10  # EasyEDA grid units
        self.component_spacing = 100  # Units between components
        self.row_height = 150  # Units between rows

    def execute(self, context: EasyEDAContext) -> EasyEDAContext:
        """Build schematic data."""
        print("\n=== Stage 3: Schematic Builder ===")

        # Initialize schematic
        schematic = self._initialize_schematic()

        # Place components
        component_positions = self._place_components(context)

        # Route wires
        wires = self._route_wires(context, component_positions)

        # Add labels
        labels = self._add_labels(context, component_positions)

        # Build schematic shapes
        shapes = []

        # Add components
        for comp_ref, position in component_positions.items():
            symbol = context.symbols[comp_ref]
            comp_shape = self._create_component_shape(symbol, position, context.components[comp_ref])
            shapes.append(comp_shape)

        # Add wires
        shapes.extend(wires)

        # Add labels
        shapes.extend(labels)

        # Add junction dots
        junctions = self._find_junctions(wires)
        for junction in junctions:
            shapes.append(self._create_junction(junction))

        # Store schematic data
        schematic['shape'] = shapes
        context.schematic_data = schematic

        print(f"Placed {len(component_positions)} components")
        print(f"Routed {len(wires)} wires")
        print(f"Added {len(junctions)} junctions")

        return context

    def _initialize_schematic(self) -> Dict:
        """Initialize EasyEDA schematic structure."""
        return {
            "head": {
                "docType": "5",
                "editorVersion": "6.5.22",
                "newgId": True,
                "c_para": {},
                "hasIdFlag": True,
                "importFlag": 0,
                "transformList": ""
            },
            "canvas": "CA~1000~1000~#000000~yes~#FFFFFF~10~1000~1000~line~10~pixel~5~0~0",
            "shape": [],
            "BBox": {
                "x": 0,
                "y": 0,
                "width": 1000,
                "height": 1000
            },
            "colors": {}
        }

    def _place_components(self, context: EasyEDAContext) -> Dict[str, Point]:
        """Place components on schematic using hierarchical layout."""
        positions = {}

        # Group components by type
        groups = self._group_components(context.components)

        # Calculate grid dimensions
        total_components = len(context.components)
        cols = min(6, max(3, int((total_components ** 0.5) + 1)))

        current_x = 100
        current_y = 100
        col_count = 0

        # Place each group
        for group_name, component_refs in groups.items():
            for comp_ref in component_refs:
                positions[comp_ref] = Point(current_x, current_y)

                # Move to next position
                col_count += 1
                if col_count >= cols:
                    col_count = 0
                    current_x = 100
                    current_y += self.row_height
                else:
                    current_x += self.component_spacing

        return positions

    def _group_components(self, components: Dict) -> Dict[str, List[str]]:
        """Group components by functional type."""
        groups = {
            'power': [],
            'input': [],
            'processing': [],
            'output': [],
            'passive': [],
            'other': []
        }

        for comp_ref, comp_data in components.items():
            comp_type = comp_data['type'].lower()

            # Categorize component
            if 'power' in comp_type or 'regulator' in comp_type or 'dc-dc' in comp_type:
                groups['power'].append(comp_ref)
            elif 'connector' in comp_type or 'input' in comp_type:
                groups['input'].append(comp_ref)
            elif 'ic' in comp_type or 'mcu' in comp_type or 'processor' in comp_type:
                groups['processing'].append(comp_ref)
            elif 'output' in comp_type or 'driver' in comp_type:
                groups['output'].append(comp_ref)
            elif comp_type in ['resistor', 'capacitor', 'inductor']:
                groups['passive'].append(comp_ref)
            else:
                groups['other'].append(comp_ref)

        # Remove empty groups
        return {k: v for k, v in groups.items() if v}

    def _route_wires(self, context: EasyEDAContext, positions: Dict[str, Point]) -> List[Dict]:
        """Route wires between components."""
        wires = []

        # Process each net
        for net_name, net_points in context.nets.items():
            # Skip single-point nets
            if len(net_points) < 2:
                continue

            # Find component pins in this net
            pin_positions = []
            for point in net_points:
                if '.' in point:
                    comp_ref, pin = point.split('.', 1)
                    if comp_ref in positions:
                        comp_pos = positions[comp_ref]
                        pin_pos = self._get_pin_position(comp_ref, pin, comp_pos, context.symbols[comp_ref])
                        if pin_pos:
                            pin_positions.append(pin_pos)

            # Route net using star topology for multi-point nets
            if len(pin_positions) > 2:
                wires.extend(self._route_star_net(pin_positions, net_name))
            elif len(pin_positions) == 2:
                wires.extend(self._route_point_to_point(pin_positions[0], pin_positions[1], net_name))

        return wires

    def _get_pin_position(self, comp_ref: str, pin: str, comp_pos: Point, symbol: Dict) -> Point:
        """Get absolute position of component pin."""
        # Find pin in symbol
        for pin_def in symbol.get('pins', []):
            if str(pin_def['id']) == str(pin):
                # Calculate absolute position
                pin_x = comp_pos.x + pin_def['x']
                pin_y = comp_pos.y + pin_def['y']
                return Point(pin_x, pin_y)
        return None

    def _route_point_to_point(self, start: Point, end: Point, net_name: str) -> List[Dict]:
        """Route wire between two points using Manhattan routing."""
        wires = []

        # Create horizontal then vertical path
        mid_x = (start.x + end.x) / 2

        # Horizontal segment from start
        if abs(start.x - mid_x) > 1:
            wires.append(self._create_wire(start, Point(mid_x, start.y), net_name))

        # Vertical segment
        if abs(start.y - end.y) > 1:
            wires.append(self._create_wire(Point(mid_x, start.y), Point(mid_x, end.y), net_name))

        # Horizontal segment to end
        if abs(mid_x - end.x) > 1:
            wires.append(self._create_wire(Point(mid_x, end.y), end, net_name))

        return wires

    def _route_star_net(self, points: List[Point], net_name: str) -> List[Dict]:
        """Route multi-point net using star topology."""
        wires = []

        # Calculate center point
        center_x = sum(p.x for p in points) / len(points)
        center_y = sum(p.y for p in points) / len(points)
        center = Point(center_x, center_y)

        # Snap center to grid
        center.x = round(center.x / self.grid_size) * self.grid_size
        center.y = round(center.y / self.grid_size) * self.grid_size

        # Route from each point to center
        for point in points:
            wires.extend(self._route_point_to_point(point, center, net_name))

        return wires

    def _create_wire(self, start: Point, end: Point, net_name: str) -> Dict:
        """Create EasyEDA wire object."""
        return {
            "type": "W",
            "id": generate_id("w"),
            "x1": start.x,
            "y1": start.y,
            "x2": end.x,
            "y2": end.y,
            "strokeWidth": 1,
            "strokeColor": "#008800",
            "net": net_name
        }

    def _create_component_shape(self, symbol: Dict, position: Point, comp_data: Dict) -> Dict:
        """Create component shape for schematic."""
        return {
            "type": "LIB",
            "id": symbol['id'],
            "x": position.x,
            "y": position.y,
            "refDes": comp_data['refDes'],
            "value": comp_data['value'],
            "symbolId": symbol['id'],
            "shapes": symbol['template'].get('shapes', []),
            "pins": symbol['template'].get('pins', [])
        }

    def _add_labels(self, context: EasyEDAContext, positions: Dict[str, Point]) -> List[Dict]:
        """Add text labels for components."""
        labels = []

        for comp_ref, position in positions.items():
            comp_data = context.components[comp_ref]

            # Add reference designator
            labels.append({
                "type": "T",
                "id": generate_id("t"),
                "x": position.x + 10,
                "y": position.y - 15,
                "text": comp_ref,
                "fontSize": 7,
                "fontFamily": "Arial",
                "fillColor": "#000000"
            })

            # Add value
            if comp_data.get('value'):
                labels.append({
                    "type": "T",
                    "id": generate_id("t"),
                    "x": position.x + 10,
                    "y": position.y + 35,
                    "text": comp_data['value'],
                    "fontSize": 7,
                    "fontFamily": "Arial",
                    "fillColor": "#000000"
                })

        return labels

    def _find_junctions(self, wires: List[Dict]) -> List[Point]:
        """Find wire junction points."""
        junctions = []
        wire_endpoints = []

        # Collect all wire endpoints
        for wire in wires:
            wire_endpoints.append(Point(wire['x1'], wire['y1']))
            wire_endpoints.append(Point(wire['x2'], wire['y2']))

        # Find points that appear more than twice (junctions)
        point_counts = {}
        for point in wire_endpoints:
            key = f"{point.x},{point.y}"
            point_counts[key] = point_counts.get(key, 0) + 1

        # Create junctions for points with 3+ connections
        for point_str, count in point_counts.items():
            if count >= 3:
                x, y = map(float, point_str.split(','))
                junctions.append(Point(x, y))

        return junctions

    def _create_junction(self, position: Point) -> Dict:
        """Create junction dot at position."""
        return {
            "type": "J",
            "id": generate_id("j"),
            "x": position.x,
            "y": position.y,
            "radius": 2,
            "fillColor": "#000000"
        }