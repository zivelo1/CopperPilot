# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
EasyEDA Pro → BoardData Adapter
===============================

TC #81 (2025-12-14): Updated for Manhattan Router (Pure Python Routing)

Converts EasyEDA Professional PCB JSON (.epcb) into the generic BoardData
representation used by the Manhattan routing engine.

DESIGN GOALS
------------
✅ GENERIC: Works for ANY EasyEDA Pro board, regardless of circuit type.
✅ MODULAR: Isolated adapter layer – no dependence on specific converters.
✅ DYNAMIC: Handles simple 2‑component boards up to large, dense designs.
✅ NON‑DESTRUCTIVE: Does not modify input data; purely reads and maps.

This module intentionally focuses on the subset of EasyEDA structures that
are required to drive the Manhattan router:
    - Board outline geometry
    - Copper layer stack
    - Components and placements
    - Pads (positions, sizes, drills)
    - Nets and pad membership (via PAD_NET data)

It does NOT attempt to be a full EasyEDA schema parser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Tuple

from .board_data import (
    BoardData,
    BoardOutline,
    Component,
    DesignRules,
    Layer,
    Net,
    Pad,
    PadShape,
    Side,
)
from .ses_parser import RoutingData


@dataclass
class EasyEDABoardAdapter:
    """
    Adapter for converting EasyEDA Pro PCB data into BoardData.

    TC #81 (2025-12-14): Updated for Manhattan Router (Pure Python Routing)

    Usage pattern (GENERIC, format‑agnostic for EasyEDA):
        adapter = EasyEDABoardAdapter()
        board = adapter.from_epcb_file(epcb_path)

    The resulting BoardData instance can then be routed by the Manhattan
    router (pure Python, no external dependencies).
    """

    def from_epcb_file(self, epcb_path: Path) -> BoardData:
        """
        Load a .epcb file and convert it into BoardData.

        The .epcb file uses a line‑delimited JSON array format, where each
        line is a standalone JSON array like:
            ["DOCTYPE","PCB","1.8"]
            ["HEAD",{...}]
            ["LAYER",1,"TOP",...]
            ...

        Args:
            epcb_path: Path to the EasyEDA Pro .epcb file.

        Returns:
            BoardData instance populated from the file.
        """
        content = epcb_path.read_text(encoding="utf-8", errors="ignore")
        lines = [ln for ln in content.splitlines() if ln.strip()]
        records: List[List[Any]] = []
        for ln in lines:
            try:
                records.append(json.loads(ln))
            except Exception:
                # Keep adapter robust – skip malformed lines rather than failing hard.
                continue

        return self.from_epcb_records(records, board_name=epcb_path.stem)

    def from_epcb_records(self, records: List[List[Any]], board_name: str = "easyeda_board") -> BoardData:
        """
        Convert parsed EasyEDA Pro PCB records into BoardData.

        Args:
            records: List of EasyEDA array records (per‑line JSON arrays).
            board_name: Optional board name used for BoardData metadata.

        Returns:
            BoardData instance.
        """
        layers = self._extract_layers(records)
        outline = self._extract_outline(records)
        components, pads_by_ref = self._extract_components_and_pads(records)
        nets = self._extract_nets(records, pads_by_ref)
        rules = self._default_design_rules()

        board = BoardData(
            components=components,
            nets=nets,
            outline=outline,
            design_rules=rules,
            layers=layers or ["F.Cu", "B.Cu"],
            board_name=board_name,
        )
        return board

    # INTERNAL HELPERS
    # ------------------------------------------------------------------
    def _extract_layers(self, records: List[List[Any]]) -> List[str]:
        """
        Extract the active copper layers from LAYER records.

        EasyEDA uses numeric layer ids and names such as TOP/BOTTOM/InnerX.
        We map to a simple front/back model for the shared router.
        """
        layers: List[str] = []
        for rec in records:
            if not rec or rec[0] != "LAYER":
                continue
            if len(rec) < 3:
                continue
            name = str(rec[2]).upper()
            if name == "TOP" and Layer.F_CU.value not in layers:
                layers.append(Layer.F_CU.value)
            elif name == "BOTTOM" and Layer.B_CU.value not in layers:
                layers.append(Layer.B_CU.value)
        # Guarantee at least front/back
        if not layers:
            layers = [Layer.F_CU.value, Layer.B_CU.value]
        elif len(layers) == 1:
            # mirror to have two layers for routing if only one present
            layers.append(Layer.B_CU.value if layers[0] == Layer.F_CU.value else Layer.F_CU.value)
        return layers

    def _extract_outline(self, records: List[List[Any]]) -> BoardOutline:
        """
        Build a crude board outline from EasyEDA outline primitives.

        For now we approximate the outline as the bounding box of all
        OUTLINE primitives. This is sufficient for router extents and
        remains GENERIC across projects.
        """
        min_x = min_y = float("inf")
        max_x = max_y = float("-inf")

        for rec in records:
            if not rec:
                continue
            kind = rec[0]
            if kind == "BOARD_OUTLINE" and len(rec) > 2 and isinstance(rec[2], list):
                coords = rec[2]
            elif kind in {"TRACK", "ARC", "CIRCLE"} and len(rec) > 2:
                coords = rec[2]
            else:
                continue
            try:
                if isinstance(coords, list) and len(coords) >= 4:
                    xs = coords[0::2]
                    ys = coords[1::2]
                    for x, y in zip(xs, ys):
                        min_x = min(min_x, float(x))
                        max_x = max(max_x, float(x))
                        min_y = min(min_y, float(y))
                        max_y = max(max_y, float(y))
            except Exception:
                continue

        if min_x == float("inf") or min_y == float("inf"):
            # Fallback: generic 100×80mm board if no outline found.
            outline_points = [(0.0, 0.0), (100.0, 0.0), (100.0, 80.0), (0.0, 80.0)]
        else:
            outline_points = [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
            ]
        return BoardOutline(points_mm=outline_points)

    def _extract_components_and_pads(
        self,
        records: List[List[Any]],
    ) -> Tuple[List[Component], Dict[str, List[Pad]]]:
        """
        Extract components and pads from PCB primitives.

        This adapter uses a conservative mapping based on common EasyEDA
        patterns. It intentionally avoids over‑fitting to a specific board.
        """
        components: Dict[str, Component] = {}
        pads_by_ref: Dict[str, List[Pad]] = {}

        # Pass 1: collect designators from ATTR entries so component references are stable.
        designator_by_comp: Dict[str, str] = {}
        footprint_by_comp: Dict[str, str] = {}
        for rec in records:
            if not rec or rec[0] != "ATTR":
                continue
            if len(rec) > 4 and str(rec[3]) == "Designator":
                try:
                    designator_by_comp[str(rec[2])] = str(rec[4])
                except Exception:
                    continue
            if len(rec) > 4 and str(rec[3]) == "Footprint":
                try:
                    # Preserve explicit footprint UUIDs/ids when present to keep DSN image mapping stable.
                    footprint_by_comp[str(rec[2])] = str(rec[4])
                except Exception:
                    continue

        for rec in records:
            if not rec:
                continue
            kind = rec[0]

            # COMPONENT (Pro 1.8): ["COMPONENT", id, flags, layerId, xMil, yMil, rotation, attrs, mirror]
            if kind == "COMPONENT" and len(rec) >= 7:
                comp_id = str(rec[1])
                ref = designator_by_comp.get(comp_id, comp_id)
                try:
                    x_mil = float(rec[4])
                    y_mil = float(rec[5])
                    rotation = float(rec[6] or 0.0)
                except Exception:
                    x_mil = y_mil = 0.0
                    rotation = 0.0
                x_mm = x_mil / 39.3700787402
                y_mm = y_mil / 39.3700787402
                side = Side.TOP
                footprint_id = footprint_by_comp.get(comp_id) or ref or comp_id or "default"
                components[ref] = Component(
                    reference=ref,
                    value="",
                    # Keep footprint non-empty so DSN images are generated for every component.
                    footprint=footprint_id,
                    x_mm=x_mm,
                    y_mm=y_mm,
                    rotation_deg=rotation,
                    side=side,
                    pads=[],
                )
                pads_by_ref.setdefault(ref, [])

            # PAD primitives carry pad geometry; we map them to Pad objects.
            if kind == "PAD" and len(rec) >= 7:
                try:
                    pad_num = str(rec[1])
                    ref = str(rec[2])
                    x_mm = float(rec[3])
                    y_mm = float(rec[4])
                    width_mm = float(rec[5])
                    height_mm = float(rec[6])
                    pad = Pad(
                        number=pad_num,
                        x_mm=x_mm,
                        y_mm=y_mm,
                        width_mm=width_mm,
                        height_mm=height_mm,
                        shape=PadShape.RECT,
                        drill_mm=0.0,
                        layer=Layer.F_CU,
                        net_name="",  # Filled from PAD_NET records
                    )
                    pads_by_ref.setdefault(ref, []).append(pad)
                except Exception:
                    continue

        # Attach pads to components
        for ref, pads in pads_by_ref.items():
            comp = components.get(ref)
            if not comp:
                continue
            comp.pads.extend(pads)

        return list(components.values()), pads_by_ref

    def _extract_nets(
        self,
        records: List[List[Any]],
        pads_by_ref: Dict[str, List[Pad]],
    ) -> List[Net]:
        """
        Build Net objects using PAD_NET assignments where available.

        This keeps the mapping GENERIC and aligned with existing exporter
        behaviour (which already emits PAD_NET).
        """
        nets_by_name: Dict[str, Net] = {}

        for rec in records:
            if not rec or rec[0] != "PAD_NET":
                continue
            # Example (conceptual):
            # ["PAD_NET", pad_ref, pad_num, net_name]
            if len(rec) < 4:
                continue
            pad_ref = str(rec[1])
            pad_num = str(rec[2])
            net_name = str(rec[3])

            net = nets_by_name.setdefault(net_name, Net(name=net_name, pads=[]))
            net.pads.append((pad_ref, pad_num))

            # Update Pad.net_name field if we have a matching pad instance.
            for pad in pads_by_ref.get(pad_ref, []):
                if pad.number == pad_num:
                    pad.net_name = net_name

        return list(nets_by_name.values())

    def _default_design_rules(self) -> DesignRules:
        """
        Return conservative, EasyEDA‑compatible default design rules.

        These values are deliberately generic and should match the existing
        EasyEDA converter’s internal assumptions (e.g., 0.25mm tracks).
        """
        return DesignRules(
            trace_width_mm=0.25,
            clearance_mm=0.25,
            via_drill_mm=0.4,
            via_diameter_mm=0.8,
        )


@dataclass
class EasyEDARouteApplicator:
    """
    Apply routing results back into EasyEDA Pro PCB records.

    TC #81 (2025-12-14): Updated for Manhattan Router (Pure Python Routing)

    This class is the EasyEDA counterpart to the KiCad RouteApplicator:
    it takes format‑agnostic RoutingData and translates it into EasyEDA
    PCB `LINE` primitives that represent routed tracks.

    The applicator is intentionally conservative:
    - It does NOT remove existing tracks today; it only appends new ones.
    - It uses mil coordinates and the same `LINE` shape format as the
      existing Pro emitter in easyeda_converter_pro.py.
    - It is GENERIC and works for any routed board.
    """

    def apply_to_epcb_records(
        self,
        records: List[List[Any]],
        routing_data: RoutingData,
        default_track_width_mm: float = 0.25,
    ) -> List[List[Any]]:
        """
        Append routed tracks from RoutingData as EasyEDA `LINE` primitives.

        Args:
            records: Existing .epcb record list (array‑per‑line format).
            routing_data: Parsed routing output from SES.
            default_track_width_mm: Fallback width when SES width is zero.

        Returns:
            New record list including additional `LINE` entries.
        """
        if not routing_data.wires:
            # Nothing to apply; return records as‑is.
            return records

        new_records: List[List[Any]] = list(records)

        # Collect existing ids to avoid collisions.
        existing_ids = {
            str(rec[1])
            for rec in records
            if len(rec) > 1 and isinstance(rec[1], str)
        }

        def _next_id(counter: int) -> Tuple[str, int]:
            """Generate a new, unique element id."""
            while True:
                eid = f"fr{counter}"
                counter += 1
                if eid not in existing_ids:
                    existing_ids.add(eid)
                    return eid, counter

        id_counter = 1

        # Utility: convert millimetres to mils (1 mm ≈ 39.37 mils).
        def _mm_to_mil(value_mm: float) -> float:
            return round(value_mm * 39.37007874, 4)

        # Generate LINE primitives for each routed wire segment.
        for wire in routing_data.wires:
            net_name = wire.net_name or ""
            # Map SES layer name to EasyEDA numeric layer id (1=TOP, 2=BOTTOM).
            layer_name = (wire.layer or "").upper()
            if layer_name in ("F.CU", "TOP"):
                layer_id = 1
            elif layer_name in ("B.CU", "BOTTOM"):
                layer_id = 2
            else:
                layer_id = 1

            width_mm = wire.width_mm or default_track_width_mm
            width_mil = _mm_to_mil(width_mm)

            if len(wire.path_points) < 2:
                continue

            points = wire.path_points
            for i in range(len(points) - 1):
                x1_mm, y1_mm = points[i]
                x2_mm, y2_mm = points[i + 1]

                x1_mil = _mm_to_mil(x1_mm)
                y1_mil = _mm_to_mil(y1_mm)
                x2_mil = _mm_to_mil(x2_mm)
                y2_mil = _mm_to_mil(y2_mm)

                line_id, id_counter = _next_id(id_counter)

                # Format (aligned with existing emitter):
                # ["LINE", id, 0, net_name, layerId, x1, y1, x2, y2, widthMil, 0]
                new_records.append(
                    [
                        "LINE",
                        line_id,
                        0,
                        net_name,
                        layer_id,
                        x1_mil,
                        y1_mil,
                        x2_mil,
                        y2_mil,
                        width_mil,
                        0,
                    ]
                )

        return new_records
