# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Layout engine module for component placement in schematic and PCB."""

import math
from typing import Dict, Any, List, Tuple, Optional
import logging

from ..utils.base import PipelineStage, ConversionContext, ValidationError

logger = logging.getLogger(__name__)

class LayoutEngine(PipelineStage):
    """Generate component layout for schematic and PCB."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.schematic_grid = 1.27  # mm (50 mils)
        self.pcb_grid = 0.1  # mm
        self.schematic_spacing_x = 12.7  # mm
        self.schematic_spacing_y = 10.16  # mm
        self.pcb_spacing_x = 10.0  # mm
        self.pcb_spacing_y = 8.0  # mm

    def process(self, context: ConversionContext) -> ConversionContext:
        """Generate layout for components."""
        try:
            components = context.components
            connections = context.input_data.get('connections', [])

            if not components:
                raise ValidationError("No components to layout")

            # Analyze connectivity for grouping
            component_groups = self._group_components(components, connections)

            # Generate schematic layout
            schematic_layout = self._generate_schematic_layout(component_groups)

            # Generate PCB layout
            pcb_layout = self._generate_pcb_layout(component_groups)

            # Store layouts in context
            context.layout = {
                'schematic': schematic_layout,
                'pcb': pcb_layout,
                'groups': component_groups
            }

            # Statistics
            context.statistics['layout'] = {
                'groups': len(component_groups),
                'schematic_bounds': self._calculate_bounds(schematic_layout),
                'pcb_bounds': self._calculate_bounds(pcb_layout)
            }

            logger.info(f"Generated layout for {len(components)} components in {len(component_groups)} groups")
            return context

        except Exception as e:
            return self.handle_error(e, context)

    def _group_components(self, components: Dict[str, Any], connections: List[Dict[str, Any]]) -> List[List[str]]:
        """Group components by connectivity and function."""
        groups = []

        # Build connectivity graph
        graph = {}
        for conn in connections:
            points = conn.get('points', [])
            for point in points:
                if '.' in point:
                    ref_des = point.split('.')[0]
                    if ref_des not in graph:
                        graph[ref_des] = set()
                    # Add all other components in this net
                    for other_point in points:
                        if '.' in other_point:
                            other_ref = other_point.split('.')[0]
                            if other_ref != ref_des:
                                graph[ref_des].add(other_ref)

        # Group by functional blocks
        grouped = set()

        # Power supply components
        power_group = []
        for ref_des, comp in components.items():
            if ref_des not in grouped:
                comp_type = comp.get('type', '')
                if comp_type in ['regulator', 'fuse', 'varistor', 'transformer', 'bridge_rectifier']:
                    power_group.append(ref_des)
                    grouped.add(ref_des)
                elif ref_des.startswith('F') or ref_des.startswith('BR'):
                    power_group.append(ref_des)
                    grouped.add(ref_des)
        if power_group:
            groups.append(power_group)

        # Input/Output connectors
        io_group = []
        for ref_des, comp in components.items():
            if ref_des not in grouped:
                if comp.get('type') == 'connector' or ref_des.startswith('J'):
                    io_group.append(ref_des)
                    grouped.add(ref_des)
        if io_group:
            groups.append(io_group)

        # Main ICs and their support components
        for ref_des, comp in components.items():
            if ref_des not in grouped and comp.get('type') in ['ic', 'opamp', 'microcontroller']:
                ic_group = [ref_des]
                grouped.add(ref_des)

                # Find connected passives
                if ref_des in graph:
                    for connected in graph[ref_des]:
                        if connected not in grouped:
                            connected_comp = components.get(connected, {})
                            if connected_comp.get('type') in ['resistor', 'capacitor', 'crystal']:
                                ic_group.append(connected)
                                grouped.add(connected)

                groups.append(ic_group)

        # Remaining components
        remaining = []
        for ref_des in components.keys():
            if ref_des not in grouped:
                remaining.append(ref_des)
                grouped.add(ref_des)

        # Split remaining into reasonable groups
        while remaining:
            group = remaining[:10]  # Max 10 components per group
            remaining = remaining[10:]
            groups.append(group)

        return groups

    def _generate_schematic_layout(self, component_groups: List[List[str]]) -> Dict[str, Tuple[float, float]]:
        """Generate schematic layout positions."""
        layout = {}

        # Use grid-based layout
        col_width = self.schematic_spacing_x * 5  # 5 grid units
        row_height = self.schematic_spacing_y * 5  # 5 grid units

        # Calculate grid dimensions
        total_components = sum(len(group) for group in component_groups)
        cols = min(5, len(component_groups))  # Max 5 columns
        rows = math.ceil(len(component_groups) / cols)

        # Place groups
        for group_idx, group in enumerate(component_groups):
            # Calculate group position
            group_col = group_idx % cols
            group_row = group_idx // cols

            group_x = 50 + group_col * col_width
            group_y = 50 + group_row * row_height

            # Place components within group
            for comp_idx, ref_des in enumerate(group):
                # Arrange in sub-grid within group
                sub_cols = min(3, len(group))
                sub_col = comp_idx % sub_cols
                sub_row = comp_idx // sub_cols

                x = group_x + sub_col * self.schematic_spacing_x * 2
                y = group_y + sub_row * self.schematic_spacing_y * 2

                # Snap to grid
                x = round(x / self.schematic_grid) * self.schematic_grid
                y = round(y / self.schematic_grid) * self.schematic_grid

                layout[ref_des] = (x, y)

        return layout

    def _generate_pcb_layout(self, component_groups: List[List[str]]) -> Dict[str, Tuple[float, float]]:
        """Generate PCB layout positions."""
        layout = {}

        # PCB layout - larger board for many components
        pcb_width = 200.0  # 200mm board width
        pcb_height = 150.0  # 150mm board height

        # Reserve space for mounting holes
        margin = 5.0  # 5mm margin

        # Calculate available area
        avail_width = pcb_width - 2 * margin
        avail_height = pcb_height - 2 * margin

        # Place power components at top
        power_y = margin
        power_x = margin

        # Place connectors on edges
        conn_left_x = margin
        conn_right_x = pcb_width - margin - 10
        conn_y = margin + 20

        # Place main components in center
        main_x_start = margin + 15
        main_y_start = margin + 10

        # Flatten all components
        all_components = []
        for group in component_groups:
            all_components.extend(group)

        # Use simple grid placement with proper spacing
        spacing_x = max(self.pcb_spacing_x * 2, 15.0)  # At least 15mm spacing
        spacing_y = max(self.pcb_spacing_y * 2, 15.0)  # At least 15mm spacing

        grid_cols = int(avail_width / spacing_x)
        if grid_cols < 1:
            grid_cols = 1

        for idx, ref_des in enumerate(all_components):
            col = idx % grid_cols
            row = idx // grid_cols

            x = margin + col * spacing_x
            y = margin + row * spacing_y

            # Ensure within bounds
            x = max(margin, min(x, pcb_width - margin - 10))
            y = max(margin, min(y, pcb_height - margin - 10))

            # Snap to PCB grid
            x = round(x / self.pcb_grid) * self.pcb_grid
            y = round(y / self.pcb_grid) * self.pcb_grid

            layout[ref_des] = (x, y)

        return layout

    def _calculate_bounds(self, layout: Dict[str, Tuple[float, float]]) -> Dict[str, float]:
        """Calculate bounding box of layout."""
        if not layout:
            return {'min_x': 0, 'min_y': 0, 'max_x': 0, 'max_y': 0}

        positions = list(layout.values())
        xs = [pos[0] for pos in positions]
        ys = [pos[1] for pos in positions]

        return {
            'min_x': min(xs),
            'min_y': min(ys),
            'max_x': max(xs),
            'max_y': max(ys),
            'width': max(xs) - min(xs),
            'height': max(ys) - min(ys)
        }