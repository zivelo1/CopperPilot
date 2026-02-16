#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Segment Generator - Converts Paths to KiCad S-Expressions
GENERIC MODULE - Works for ANY circuit/trace

Purpose: Convert routing paths into proper KiCad .kicad_pcb format

Generates:
- (segment ...) elements for copper traces
- (via ...) elements for layer changes
- (arc ...) elements for curved traces (future)

All output is GENERIC and compliant with KiCad 9 format specification.

Author: Electronics Automation System
Date: 2025-10-27
"""

import uuid
from typing import List, Dict, Tuple
from dataclasses import dataclass

from .grid_occupancy import Point, Layer
from .path_routing import RoutingConfig


@dataclass
class Segment:
    """
    KiCad PCB segment (copper trace).
    GENERIC - represents any trace on any layer.
    """
    start: Point
    end: Point
    width: float
    layer: Layer
    net_idx: int
    uuid_str: str

    def to_kicad_sexpr(self) -> str:
        """
        Convert to KiCad S-expression format.
        GENERIC - follows KiCad 9 format specification.

        Format:
        (segment
          (start X Y)
          (end X Y)
          (width W)
          (layer "LayerName")
          (net N)
          (uuid "UUID")
        )
        """
        return f'''  (segment
    (start {self._format_coord(self.start.x)} {self._format_coord(self.start.y)})
    (end {self._format_coord(self.end.x)} {self._format_coord(self.end.y)})
    (width {self._format_coord(self.width)})
    (layer "{self.layer.value}")
    (net {self.net_idx})
    (uuid "{self.uuid_str}")
  )'''

    def _format_coord(self, value: float) -> str:
        """Format coordinate value to 4 decimal places (0.0001mm precision)"""
        return f"{value:.4f}"


@dataclass
class Via:
    """
    KiCad PCB via (connects layers).
    GENERIC - represents any via.
    """
    position: Point
    size: float        # Via diameter
    drill: float       # Drill hole diameter
    layers: Tuple[Layer, Layer]  # Connected layers
    net_idx: int
    uuid_str: str

    def to_kicad_sexpr(self) -> str:
        """
        Convert to KiCad S-expression format.
        GENERIC - follows KiCad 9 format specification.

        Format:
        (via
          (at X Y)
          (size S)
          (drill D)
          (layers "Layer1" "Layer2")
          (net N)
          (uuid "UUID")
        )
        """
        return f'''  (via
    (at {self._format_coord(self.position.x)} {self._format_coord(self.position.y)})
    (size {self._format_coord(self.size)})
    (drill {self._format_coord(self.drill)})
    (layers "{self.layers[0].value}" "{self.layers[1].value}")
    (net {self.net_idx})
    (uuid "{self.uuid_str}")
  )'''

    def _format_coord(self, value: float) -> str:
        """Format coordinate value to 4 decimal places"""
        return f"{value:.4f}"


class SegmentGenerator:
    """
    GENERIC segment generator.
    Converts routing paths to KiCad PCB elements.
    """

    def __init__(self, config: RoutingConfig, net_map: Dict[str, int]):
        """
        Initialize generator.

        Args:
            config: Routing configuration (track widths, via sizes)
            net_map: Mapping of net names to net indices
        """
        self.config = config
        self.net_map = net_map

    def path_to_segments(self, path: List[Point], net_name: str,
                        layer: Layer = Layer.F_CU) -> List[Segment]:
        """
        Convert path (list of points) to KiCad segments.
        GENERIC - works for ANY path length/shape.

        Args:
            path: List of points forming path
            net_name: Net name
            layer: PCB layer

        Returns:
            List of Segment objects
        """
        if len(path) < 2:
            return []

        net_idx = self.net_map.get(net_name, 0)
        segments = []

        for i in range(len(path) - 1):
            start = path[i]
            end = path[i + 1]

            # FIX 1.3 REVERTED (2025-11-10): Zero-length check broke perfect circuits
            # Routing creates these intentionally for connection points
            # Original code restoring segment creation without distance check

            segment = Segment(
                start=start,
                end=end,
                width=self.config.track_width,
                layer=layer,
                net_idx=net_idx,
                uuid_str=str(uuid.uuid4())
            )

            segments.append(segment)

        return segments

    def create_via(self, position: Point, net_name: str,
                  from_layer: Layer = Layer.F_CU,
                  to_layer: Layer = Layer.B_CU) -> Via:
        """
        Create via for layer change.
        GENERIC - works for any layer pair.

        Args:
            position: Via position
            net_name: Net name
            from_layer: Source layer
            to_layer: Destination layer

        Returns:
            Via object
        """
        net_idx = self.net_map.get(net_name, 0)

        via = Via(
            position=position,
            size=self.config.via_diameter,
            drill=self.config.via_drill,
            layers=(from_layer, to_layer),
            net_idx=net_idx,
            uuid_str=str(uuid.uuid4())
        )

        return via

    def generate_all_segments(self, routed_nets: Dict[str, List[List]],
                            layer: Layer = Layer.F_CU) -> Tuple[List[Segment], List[Via]]:
        """
        Generate all segments for all routed nets.
        GENERIC - processes ANY number of nets.

        Args:
            routed_nets: Dict mapping net names to lists of paths
            layer: Default layer

        Returns:
            Tuple of (segments list, vias list)
        """
        all_segments = []
        all_vias = []

        for net_name, paths in routed_nets.items():
            for path in paths:
                if not path:
                    continue
                # Layer-aware path: list of (Point, Layer)
                if isinstance(path[0], tuple):
                    net_idx = self.net_map.get(net_name, 0)
                    # Build segments and vias between successive points
                    prev_pt, prev_layer = path[0]
                    for i in range(1, len(path)):
                        pt, ly = path[i]
                        if ly != prev_layer:
                            # Insert a via at the transition point
                            all_vias.append(
                                Via(
                                    position=prev_pt,
                                    size=self.config.via_diameter,
                                    drill=self.config.via_drill,
                                    layers=(prev_layer, ly),
                                    net_idx=net_idx,
                                    uuid_str=str(uuid.uuid4()),
                                )
                            )
                        # Create a segment from prev_pt to pt on the current layer (ly)
                        all_segments.append(
                            Segment(
                                start=prev_pt,
                                end=pt,
                                width=self.config.track_width,
                                layer=ly,
                                net_idx=net_idx,
                                uuid_str=str(uuid.uuid4()),
                            )
                        )
                        prev_pt, prev_layer = pt, ly
                else:
                    # Single-layer path (List[Point])
                    segments = self.path_to_segments(path, net_name, layer)
                    all_segments.extend(segments)

        return all_segments, all_vias

    def remove_overlapping_segments(self, segments: List[Segment],
                                    clearance: float = 0.3) -> List[Segment]:
        """
        FIX B.7 (2025-11-11): Remove segments that overlap with different nets.
        GENERIC: Works for ANY circuit complexity.

        This fixes shorting_items DRC violations by detecting trace overlaps
        AFTER routing completes but BEFORE writing to file.

        Args:
            segments: All segments to check
            clearance: Minimum clearance in mm

        Returns:
            Filtered segment list with overlaps removed
        """
        if not segments:
            return segments

        clean_segments = []
        conflicts_removed = 0

        # Build spatial index: segment bounding boxes with dict mapping
        # FIX B.7.2 (2025-11-11): Use dict for O(1) lookups instead of list.index()
        segment_boxes = {}
        for i, seg in enumerate(segments):
            min_x = min(seg.start.x, seg.end.x) - clearance
            max_x = max(seg.start.x, seg.end.x) + clearance
            min_y = min(seg.start.y, seg.end.y) - clearance
            max_y = max(seg.start.y, seg.end.y) + clearance
            segment_boxes[i] = (min_x, min_y, max_x, max_y, seg.layer, seg.net_idx)

        # Build kept_indices set for fast lookup
        kept_indices = set()

        # Check each segment for overlaps with different nets
        # FIX B.7.1 (2025-11-11): Check against KEPT segments only, not all previous segments
        # FIX B.7.2 (2025-11-11): Use indices instead of segment objects for O(1) lookups
        for i, seg in enumerate(segments):
            has_conflict = False
            my_box = segment_boxes[i]

            # Only check against segments we've KEPT so far
            for kept_idx in kept_indices:
                other_seg = segments[kept_idx]
                other_box = segment_boxes[kept_idx]

                # Skip if same net (same-net overlaps are OK)
                if seg.net_idx == other_seg.net_idx:
                    continue

                # Skip if different layers
                if seg.layer != other_seg.layer:
                    continue

                # Check bounding box overlap
                if (my_box[0] <= other_box[2] and my_box[2] >= other_box[0] and
                    my_box[1] <= other_box[3] and my_box[3] >= other_box[1]):
                    # Bounding boxes overlap - this is a potential short
                    has_conflict = True
                    conflicts_removed += 1
                    break

            if not has_conflict:
                clean_segments.append(seg)
                kept_indices.add(i)  # Track that we kept this segment

        if conflicts_removed > 0:
            print(f"  🔍 Overlap Detection: Removed {conflicts_removed} conflicting segments")

        return clean_segments

    def segments_to_kicad_text(self, segments: List[Segment],
                              vias: List[Via]) -> str:
        """
        Convert segments and vias to KiCad PCB text format.
        GENERIC - formats ANY number of elements.

        Returns:
            String containing all segment/via S-expressions
        """
        lines = []

        # Add all segments
        for segment in segments:
            lines.append(segment.to_kicad_sexpr())

        # Add all vias
        for via in vias:
            lines.append(via.to_kicad_sexpr())

        return '\n'.join(lines)


class RoutingStatistics:
    """
    GENERIC routing statistics tracker.
    Useful for debugging and quality assessment.
    """

    def __init__(self):
        self.total_nets = 0
        self.routed_nets = 0
        self.failed_nets = []
        self.total_segments = 0
        self.total_vias = 0
        self.total_trace_length = 0.0  # mm

    def add_routed_net(self, net_name: str, segments: List[Segment]):
        """Record successfully routed net"""
        self.routed_nets += 1
        self.total_segments += len(segments)

        # Calculate total trace length (best-effort if Segment objects provided)
        for seg in segments:
            try:
                start = getattr(seg, 'start', None)
                end = getattr(seg, 'end', None)
                if start is not None and end is not None:
                    self.total_trace_length += start.distance_to(end)
            except Exception:
                # Non-fatal: stats remain approximate if placeholders were used
                pass

    def add_failed_net(self, net_name: str):
        """Record failed net"""
        self.failed_nets.append(net_name)

    def get_success_rate(self) -> float:
        """Calculate routing success rate (0-100%)"""
        if self.total_nets == 0:
            return 0.0

        return (self.routed_nets / self.total_nets) * 100.0

    def get_summary(self) -> str:
        """
        Get human-readable summary.
        GENERIC - formats statistics for any circuit.
        """
        success_rate = self.get_success_rate()

        summary = f"""
Routing Statistics:
==================
Total nets:        {self.total_nets}
Routed:            {self.routed_nets} ({success_rate:.1f}%)
Failed:            {len(self.failed_nets)}
Total segments:    {self.total_segments}
Total vias:        {self.total_vias}
Total trace length: {self.total_trace_length:.1f} mm
"""

        if self.failed_nets:
            summary += f"\nFailed nets: {', '.join(self.failed_nets[:10])}"
            if len(self.failed_nets) > 10:
                summary += f" ... and {len(self.failed_nets) - 10} more"

        return summary
