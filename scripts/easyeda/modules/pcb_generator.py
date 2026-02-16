# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""PCB generator module for EasyEDA converter."""
from typing import Dict, List, Any, Tuple
from .utils import EasyEDAContext, Point, generate_id, mm_to_easyeda

class PCBGenerator:
    """Generate PCB layout for EasyEDA."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.board_width = 100  # mm
        self.board_height = 80  # mm
        self.component_spacing = 10  # mm
        self.track_width = 0.25  # mm
        self.via_diameter = 0.8  # mm
        self.via_drill = 0.4  # mm

    def execute(self, context: EasyEDAContext) -> EasyEDAContext:
        """Generate PCB layout."""
        print("\n=== Stage 4: PCB Generator ===")

        # Initialize PCB
        pcb = self._initialize_pcb()

        # Place footprints
        footprint_positions = self._place_footprints(context)

        # Route tracks
        tracks = self._route_tracks(context, footprint_positions)

        # Add vias where needed
        vias = self._add_vias(tracks)

        # Build PCB shapes
        shapes = []

        # Add board outline
        shapes.append(self._create_board_outline())

        # Add footprints
        for comp_ref, position in footprint_positions.items():
            footprint = context.footprints[comp_ref]
            fp_shape = self._create_footprint_shape(footprint, position, context.components[comp_ref])
            shapes.append(fp_shape)

        # Add tracks
        shapes.extend(tracks)

        # Add vias
        shapes.extend(vias)

        # Add silkscreen
        silkscreen = self._add_silkscreen(context, footprint_positions)
        shapes.extend(silkscreen)

        # Store PCB data
        pcb['shape'] = shapes
        context.pcb_data = pcb

        print(f"Placed {len(footprint_positions)} footprints")
        print(f"Routed {len(tracks)} tracks")
        print(f"Added {len(vias)} vias")

        return context

    def _initialize_pcb(self) -> Dict:
        """Initialize EasyEDA PCB structure."""
        return {
            "head": {
                "docType": "3",
                "editorVersion": "6.5.22",
                "newgId": True,
                "c_para": {
                    "package": "",
                    "pre": "",
                    "Contributor": "",
                    "link": "",
                    "Model_3D": ""
                },
                "hasIdFlag": True,
                "importFlag": 0
            },
            "canvas": f"CA~{mm_to_easyeda(self.board_width)}~{mm_to_easyeda(self.board_height)}~#000000~yes~#FFFFFF~10~1000~1000~line~10~pixel~5~0~0",
            "shape": [],
            "layers": [
                "1~TopLayer~#FF0000~true~true~true~",
                "2~BottomLayer~#0000FF~true~false~true~",
                "3~TopSilkLayer~#FFFF00~true~false~true~",
                "4~BottomSilkLayer~#808080~true~false~true~",
                "5~TopPasteMaskLayer~#808080~true~false~true~",
                "6~BottomPasteMaskLayer~#808080~true~false~true~",
                "7~TopSolderMaskLayer~#800080~true~false~true~0.1",
                "8~BottomSolderMaskLayer~#AA00FF~true~false~true~0.1",
                "9~Ratlines~#6464FF~false~false~true~",
                "10~BoardOutLine~#FF00FF~true~false~true~",
                "11~Multi-Layer~#C0C0C0~true~false~true~",
                "12~Document~#FFFFFF~true~false~true~",
                "13~TopAssembly~#33CC99~false~false~false~",
                "14~BottomAssembly~#5555FF~false~false~false~",
                "15~Mechanical~#F022F0~false~false~false~",
                "19~3DModel~#66CCFF~false~false~false~",
                "21~Inner1~#999966~false~false~false~~",
                "22~Inner2~#008000~false~false~false~~"
            ]
        }

    def _place_footprints(self, context: EasyEDAContext) -> Dict[str, Point]:
        """Place footprints on PCB."""
        positions = {}

        # Group components by type for better placement
        groups = self._group_components_for_pcb(context.components)

        # Calculate grid
        total_components = len(context.components)
        cols = min(8, max(4, int((total_components ** 0.5) + 1)))

        # Start position (in mm)
        current_x = 10
        current_y = 10
        max_height = 0
        col_count = 0

        # Place each group
        for group_name, component_refs in groups.items():
            for comp_ref in component_refs:
                # Convert to EasyEDA units
                positions[comp_ref] = Point(
                    mm_to_easyeda(current_x),
                    mm_to_easyeda(current_y)
                )

                # Get footprint size
                footprint = context.footprints[comp_ref]
                fp_width = self._get_footprint_width(footprint)
                fp_height = self._get_footprint_height(footprint)
                max_height = max(max_height, fp_height)

                # Move to next position
                col_count += 1
                if col_count >= cols:
                    col_count = 0
                    current_x = 10
                    current_y += max_height + self.component_spacing
                    max_height = 0
                else:
                    current_x += fp_width + self.component_spacing

        return positions

    def _group_components_for_pcb(self, components: Dict) -> Dict[str, List[str]]:
        """Group components for PCB placement."""
        groups = {
            'connectors': [],
            'power': [],
            'ics': [],
            'passives': [],
            'misc': []
        }

        for comp_ref, comp_data in components.items():
            comp_type = comp_data['type'].lower()

            if 'connector' in comp_type:
                groups['connectors'].append(comp_ref)
            elif 'power' in comp_type or 'regulator' in comp_type:
                groups['power'].append(comp_ref)
            elif 'ic' in comp_type or comp_data.get('package', '').startswith('DIP'):
                groups['ics'].append(comp_ref)
            elif comp_type in ['resistor', 'capacitor', 'inductor']:
                groups['passives'].append(comp_ref)
            else:
                groups['misc'].append(comp_ref)

        return {k: v for k, v in groups.items() if v}

    def _route_tracks(self, context: EasyEDAContext, positions: Dict[str, Point]) -> List[Dict]:
        """Route PCB tracks between components."""
        tracks = []

        # Process each net
        for net_name, net_points in context.nets.items():
            if len(net_points) < 2:
                continue

            # Find pad positions for this net
            pad_positions = []
            for point in net_points:
                if '.' in point:
                    comp_ref, pin = point.split('.', 1)
                    if comp_ref in positions:
                        pad_pos = self._get_pad_position(comp_ref, pin, positions[comp_ref], context.footprints[comp_ref])
                        if pad_pos:
                            pad_positions.append(pad_pos)

            # Route net
            if len(pad_positions) > 2:
                # Use star routing for multi-point nets
                tracks.extend(self._route_star_tracks(pad_positions, net_name))
            elif len(pad_positions) == 2:
                # Simple point-to-point routing
                tracks.extend(self._route_simple_track(pad_positions[0], pad_positions[1], net_name))

        return tracks

    def _get_pad_position(self, comp_ref: str, pin: str, comp_pos: Point, footprint: Dict) -> Point:
        """Get pad position for component pin."""
        # Simple pad position calculation
        # In real implementation, this would use actual footprint data
        template = footprint.get('template', {})

        if template.get('type') == 'smd':
            # SMD component - simple two-pad layout
            if pin == '1':
                return Point(comp_pos.x - mm_to_easyeda(1), comp_pos.y)
            elif pin == '2':
                return Point(comp_pos.x + mm_to_easyeda(1), comp_pos.y)
        elif template.get('type') == 'tht':
            # Through-hole component
            pitch = mm_to_easyeda(template.get('pitch', 2.54))
            pin_num = int(pin) - 1 if pin.isdigit() else 0
            return Point(comp_pos.x + pin_num * pitch, comp_pos.y)

        return comp_pos

    def _route_simple_track(self, start: Point, end: Point, net_name: str) -> List[Dict]:
        """Route simple track between two points."""
        tracks = []

        # Create L-shaped route
        mid_y = (start.y + end.y) / 2

        # Horizontal segment
        if abs(start.x - end.x) > 1:
            tracks.append(self._create_track(start, Point(end.x, start.y), net_name, "1"))

        # Vertical segment
        if abs(start.y - end.y) > 1:
            tracks.append(self._create_track(Point(end.x, start.y), end, net_name, "1"))

        return tracks

    def _route_star_tracks(self, points: List[Point], net_name: str) -> List[Dict]:
        """Route multi-point net using star topology."""
        tracks = []

        # Calculate center point
        center_x = sum(p.x for p in points) / len(points)
        center_y = sum(p.y for p in points) / len(points)
        center = Point(center_x, center_y)

        # Route from each point to center
        for point in points:
            tracks.extend(self._route_simple_track(point, center, net_name))

        return tracks

    def _create_track(self, start: Point, end: Point, net_name: str, layer: str) -> Dict:
        """Create PCB track."""
        return {
            "type": "TRACK",
            "id": generate_id("tr"),
            "layerid": layer,
            "net": net_name,
            "pointArr": [
                {"x": start.x, "y": start.y},
                {"x": end.x, "y": end.y}
            ],
            "strokeWidth": mm_to_easyeda(self.track_width)
        }

    def _add_vias(self, tracks: List[Dict]) -> List[Dict]:
        """Add vias for layer transitions."""
        vias = []
        # Simple implementation - add vias at track intersections if needed
        # In a real implementation, this would analyze layer transitions
        return vias

    def _create_board_outline(self) -> Dict:
        """Create board outline."""
        width = mm_to_easyeda(self.board_width)
        height = mm_to_easyeda(self.board_height)

        return {
            "type": "RECT",
            "id": generate_id("rect"),
            "layerid": "10",  # BoardOutLine layer
            "x": 0,
            "y": 0,
            "width": width,
            "height": height,
            "strokeWidth": 1,
            "fillColor": "none"
        }

    def _create_footprint_shape(self, footprint: Dict, position: Point, comp_data: Dict) -> Dict:
        """Create footprint shape for PCB."""
        template = footprint.get('template', {})

        # Simple footprint representation
        pads = []
        if template.get('type') == 'smd':
            # Create two SMD pads
            pad_width = mm_to_easyeda(0.8)
            pad_height = mm_to_easyeda(1.2)
            pad_spacing = mm_to_easyeda(2)

            pads.append({
                "type": "PAD",
                "shape": "RECT",
                "x": position.x - pad_spacing/2,
                "y": position.y,
                "width": pad_width,
                "height": pad_height,
                "layerid": "1",  # Top layer
                "net": "",
                "number": "1"
            })
            pads.append({
                "type": "PAD",
                "shape": "RECT",
                "x": position.x + pad_spacing/2,
                "y": position.y,
                "width": pad_width,
                "height": pad_height,
                "layerid": "1",  # Top layer
                "net": "",
                "number": "2"
            })

        return {
            "type": "FOOTPRINT",
            "id": footprint['id'],
            "x": position.x,
            "y": position.y,
            "refDes": comp_data['refDes'],
            "pads": pads
        }

    def _add_silkscreen(self, context: EasyEDAContext, positions: Dict[str, Point]) -> List[Dict]:
        """Add silkscreen labels."""
        silkscreen = []

        for comp_ref, position in positions.items():
            # Add reference designator
            silkscreen.append({
                "type": "TEXT",
                "id": generate_id("txt"),
                "layerid": "3",  # TopSilkLayer
                "x": position.x,
                "y": position.y - mm_to_easyeda(3),
                "text": comp_ref,
                "fontSize": mm_to_easyeda(1),
                "strokeWidth": 0.15
            })

        return silkscreen

    def _get_footprint_width(self, footprint: Dict) -> float:
        """Get footprint width in mm."""
        template = footprint.get('template', {})
        return template.get('width', 3.2)  # Default 3.2mm

    def _get_footprint_height(self, footprint: Dict) -> float:
        """Get footprint height in mm."""
        template = footprint.get('template', {})
        return template.get('height', 1.6)  # Default 1.6mm