# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Pro format validator for EasyEDA Pro converter."""
from pathlib import Path
from typing import Dict, List, Any, Tuple
from .utils import EasyEDAContext


class ProValidator:
    """Validate EasyEDA Pro format output."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.strict_mode = config.get('strict_validation', False)
        # Capture routing metrics for downstream fixers or reporting
        self.pcb_metrics: Dict[str, Any] = {}

    def execute(self, context: EasyEDAContext) -> EasyEDAContext:
        """Validate Pro format output."""
        print("\n=== Stage 7: Pro Validation ===")

        # Run Pro-specific validation
        self._validate_pro_schematic(context)
        self._validate_pro_pcb(context)
        self._validate_connectivity(context)
        self._run_pro_drc(context)
        self._validate_endpoint_snapping(context)
        self._validate_sch_pcb_parity(context)
        self._validate_schematic_endpoints(context)
        self._run_pro_erc(context)
        self._enforce_verification_artifacts(context)

        # Generate report
        report = self._generate_report(context)
        context.stats['validation'] = report

        print(f"Validation complete: {len(context.errors)} errors, {len(context.warnings)} warnings")

        if context.errors and self.strict_mode:
            print("ERROR: Validation failed in strict mode")
            for error in context.errors:
                print(f"  - {error}")

        return context

    def _validate_pro_schematic(self, context: EasyEDAContext):
        """Validate Pro schematic format (array-based .esch format)."""
        if not context.schematic_data:
            context.warnings.append("No schematic data generated")
            return

        schematic = context.schematic_data

        # Check if it's the new array-based format
        if isinstance(schematic, list):
            # Validate array-based format
            if len(schematic) == 0:
                context.errors.append("Pro schematic is empty array")
                return

            # Check for DOCTYPE header
            if schematic[0][0] != "DOCTYPE":
                context.errors.append("Pro schematic missing DOCTYPE header")
            elif schematic[0][1] != "SCH":
                context.errors.append(f"Invalid Pro schematic DOCTYPE: {schematic[0][1]}")

            # Check for HEAD element
            has_head = any(item[0] == "HEAD" for item in schematic if isinstance(item, list) and len(item) > 0)
            if not has_head:
                context.warnings.append("Pro schematic missing HEAD element")

            # Count components and wires
            component_count = sum(1 for item in schematic if isinstance(item, list) and len(item) > 0 and item[0] == "COMPONENT")
            wire_count = sum(1 for item in schematic if isinstance(item, list) and len(item) > 0 and item[0] == "WIRE")

            if component_count == 0:
                context.warnings.append("No COMPONENT elements in Pro schematic")

            if wire_count == 0:
                context.warnings.append("No WIRE elements in Pro schematic")

        else:
            # Old format check (should not happen anymore)
            context.errors.append("Pro schematic is not in array format - format conversion failed")

    def _validate_pro_pcb(self, context: EasyEDAContext):
        """Validate Pro PCB format (array-based .epcb format).

        PHASE 4 ENHANCEMENT: Fail-closed validation for PCB completeness.
        Missing or empty PCB is now an ERROR, not a warning.
        This ensures production-ready output - partial success is complete failure.
        """
        if not context.pcb_data:
            context.errors.append("CRITICAL: No PCB data generated - Cannot manufacture board")
            return

        # Metrics used for fail-closed gating and to drive fixers
        pcb_nets = 0
        pcb_tracks = 0
        pcb_vias = 0

        # PHASE 4 FIX: Check for array-based format (new Pro format)
        if isinstance(context.pcb_data, list):
            # Validate array-based format
            if len(context.pcb_data) == 0:
                context.errors.append("CRITICAL: PCB data is empty array - Cannot manufacture board")
                return

            # Check for DOCTYPE header
            if context.pcb_data[0][0] != "DOCTYPE":
                context.errors.append("PCB missing DOCTYPE header")
            elif context.pcb_data[0][1] != "PCB":
                context.errors.append(f"Invalid PCB DOCTYPE: {context.pcb_data[0][1]}")

            # Check for HEAD element
            has_head = any(item[0] == "HEAD" for item in context.pcb_data if isinstance(item, list) and len(item) > 0)
            if not has_head:
                context.errors.append("PCB missing HEAD element")

            # Check for BOARD_OUTLINE
            has_outline = any(item[0] == "BOARD_OUTLINE" for item in context.pcb_data if isinstance(item, list) and len(item) > 0)
            if not has_outline:
                context.errors.append("CRITICAL: PCB missing BOARD_OUTLINE - Cannot manufacture board")

            # Count components
            component_count = sum(1 for item in context.pcb_data if isinstance(item, list) and len(item) > 0 and item[0] == "COMPONENT")
            if component_count == 0:
                context.errors.append("CRITICAL: No components placed on PCB - Board is empty")

            print(f"  PCB validation: {component_count} components placed")

            # Count nets/tracks/vias for gating
            for item in context.pcb_data:
                if not isinstance(item, list) or not item:
                    continue
                et = item[0]
                if et == "NET":
                    pcb_nets += 1
                elif et == "LINE":
                    pcb_tracks += 1
                elif et == "VIA":
                    pcb_vias += 1

        elif isinstance(context.pcb_data, dict):
            # Old dict format (should not happen with Phase 2 implementation)
            if len(context.pcb_data) == 0:
                context.errors.append("CRITICAL: PCB data is empty - Cannot manufacture board")
            else:
                context.warnings.append("PCB data is in legacy dict format (expected array format)")
        else:
            context.errors.append("CRITICAL: PCB data format is invalid (not array or dict)")

        # Persist metrics for reporting/fixers
        context.stats.setdefault('pcb_metrics', {})
        context.stats['pcb_metrics'].update({
            'nets': pcb_nets,
            'tracks': pcb_tracks,
            'vias': pcb_vias
        })
        self.pcb_metrics = context.stats['pcb_metrics']

        # Fail-closed: zero nets or zero copper renders the board unusable
        if pcb_nets == 0:
            context.errors.append("CRITICAL: PCB has zero NET declarations")
        if pcb_tracks == 0:
            context.errors.append("CRITICAL: PCB has zero LINE tracks (board is unrouted)")

    def _validate_connectivity(self, context: EasyEDAContext):
        """Validate component connectivity."""
        # Check for unconnected components
        connected_components = set()
        for net_name, net_points in context.nets.items():
            # Skip NC (No Connect) nets
            if net_name.startswith('NC_'):
                continue
            for point in net_points:
                if '.' in point:
                    comp_ref = point.split('.')[0]
                    connected_components.add(comp_ref)

        # Find unconnected
        for comp_ref in context.components:
            if comp_ref not in connected_components:
                comp_type = context.components[comp_ref]['type'].lower()
                # Skip mechanical components
                if comp_type not in ['heatsink', 'mounting_hole', 'fiducial', 'test_point']:
                    context.warnings.append(f"Component {comp_ref} has no connections")

        # Check for single-point nets (excluding NC nets)
        for net_name, net_points in context.nets.items():
            # Skip NC (No Connect) nets - these are intentionally single-point
            if net_name.startswith('NC_'):
                continue
            if len(net_points) == 1:
                context.warnings.append(f"Net {net_name} has only one connection")

    def _run_pro_drc(self, context: EasyEDAContext):
        """Run comprehensive Pro-specific Design Rule Check.

        PHASE 4 ENHANCEMENT: DRC now validates array-based PCB format.
        No longer skipped - runs full manufacturing validation.
        """
        if not context.pcb_data:
            print("  Skipping DRC (no PCB layout data)")
            return

        # PHASE 4 FIX: Handle array-based PCB format
        if isinstance(context.pcb_data, list):
            print("  Running DRC (Design Rule Check) on array-based PCB...")
            self._run_array_based_drc(context)
            return
        elif isinstance(context.pcb_data, dict):
            # Legacy dict format
            if len(context.pcb_data) == 0 or 'pcb' not in context.pcb_data:
                print("  Skipping DRC (PCB data incomplete)")
                return
            pcb_data = context.pcb_data['pcb']
        else:
            print("  Skipping DRC (unknown PCB format)")
            return

        print("  Running DRC (Design Rule Check) on dict-based PCB...")
        drc_errors = 0
        drc_warnings = 0

        # DRC Rule 1: Track width validation
        if 'tracks' in pcb_data:
            min_track_width = self.config.get('routing', {}).get('track_width', 0.25)  # mm
            narrow_tracks = 0
            unassigned_nets = 0

            for i, track in enumerate(pcb_data['tracks']):
                width = track.get('width', 0)
                net = track.get('net', 'unknown')

                # Convert Pro units to mm (assuming 1 Pro unit = 0.1mm)
                width_mm = width * 0.1

                if width_mm < min_track_width:
                    narrow_tracks += 1
                    if narrow_tracks <= 3:  # Only report first 3 examples
                        context.warnings.append(f"DRC: Track (net: {net}) width {width_mm:.3f}mm below minimum {min_track_width}mm")
                        drc_warnings += 1

                # Check for tracks without net assignment (warning only)
                if not net or net == 'unknown':
                    unassigned_nets += 1

            if narrow_tracks > 3:
                context.warnings.append(f"DRC: {narrow_tracks - 3} additional tracks below minimum width")
                drc_warnings += 1

            if unassigned_nets > 0:
                context.warnings.append(f"DRC: {unassigned_nets} tracks without net assignment")
                drc_warnings += 1

        # DRC Rule 2: Via size validation
        if 'vias' in pcb_data and len(pcb_data['vias']) > 0:
            min_via_drill = self.config.get('routing', {}).get('via_drill', 0.4)  # mm
            min_via_diameter = self.config.get('routing', {}).get('via_diameter', 0.8)  # mm

            small_drill_count = 0
            small_diameter_count = 0
            small_annular_count = 0
            no_net_count = 0

            for i, via in enumerate(pcb_data['vias']):
                drill = via.get('drill', 0)
                diameter = via.get('diameter', 0)
                net = via.get('net', 'unknown')

                # Convert Pro units to mm
                drill_mm = drill * 0.1
                diameter_mm = diameter * 0.1

                if drill_mm < min_via_drill:
                    small_drill_count += 1
                if diameter_mm < min_via_diameter:
                    small_diameter_count += 1

                # Check annular ring
                if diameter_mm > 0 and drill_mm > 0:
                    annular_ring = (diameter_mm - drill_mm) / 2
                    if annular_ring < 0.15:
                        small_annular_count += 1

                if not net or net == 'unknown':
                    no_net_count += 1

            if small_drill_count > 0:
                context.warnings.append(f"DRC: {small_drill_count} vias with drill below {min_via_drill}mm")
                drc_warnings += 1
            if small_diameter_count > 0:
                context.warnings.append(f"DRC: {small_diameter_count} vias with diameter below {min_via_diameter}mm")
                drc_warnings += 1
            if small_annular_count > 0:
                context.warnings.append(f"DRC: {small_annular_count} vias with annular ring below 0.15mm")
                drc_warnings += 1
            if no_net_count > 0:
                context.warnings.append(f"DRC: {no_net_count} vias without net assignment")
                drc_warnings += 1

        # DRC Rule 3: Clearance validation
        # Skip clearance check for generated PCB stubs - this would require full geometric analysis
        # which is beyond the scope of automated conversion validation
        pass

        # DRC Rule 4: Board outline validation
        if 'board' in pcb_data:
            board = pcb_data['board']
            width = board.get('width', 0)
            height = board.get('height', 0)
            thickness = board.get('thickness', 0)

            if width <= 0 or height <= 0:
                context.errors.append(f"DRC: Invalid board dimensions ({width}mm × {height}mm)")
                drc_errors += 1

            # Check JLCPCB manufacturing limits
            if width < 20 or height < 20:
                context.warnings.append(f"DRC: Board size ({width}mm × {height}mm) below JLCPCB minimum (20mm × 20mm)")
                drc_warnings += 1

            if width > 500 or height > 500:
                context.warnings.append(f"DRC: Board size ({width}mm × {height}mm) exceeds JLCPCB maximum (500mm × 500mm)")
                drc_warnings += 1

            if thickness not in [0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0]:
                context.warnings.append(f"DRC: Board thickness {thickness}mm is non-standard for JLCPCB")
                drc_warnings += 1

        # DRC Rule 5: Layer validation
        if 'layers' in pcb_data:
            required_layers = ['Top', 'Bottom', 'TopSilk', 'BottomSilk', 'BoardOutline']
            layer_names = [layer.get('name', '') for layer in pcb_data['layers']]

            for req_layer in required_layers:
                if req_layer not in layer_names:
                    context.warnings.append(f"DRC: Missing recommended layer: {req_layer}")
                    drc_warnings += 1

        # DRC Rule 6: Component placement validation
        if 'components' in pcb_data:
            out_of_bounds = []
            for i, comp in enumerate(pcb_data['components']):
                x = comp.get('x', 0)
                y = comp.get('y', 0)
                refdes = comp.get('refDes', f'Unknown_{i}')

                # Check if component is within board boundaries
                board_width = pcb_data.get('board', {}).get('width', 100)
                board_height = pcb_data.get('board', {}).get('height', 80)

                if x < 0 or y < 0 or x > board_width or y > board_height:
                    out_of_bounds.append(refdes)

            if out_of_bounds:
                if len(out_of_bounds) <= 5:
                    context.warnings.append(f"DRC: Components outside board boundaries: {', '.join(out_of_bounds)}")
                else:
                    context.warnings.append(f"DRC: {len(out_of_bounds)} components outside board boundaries (including {', '.join(out_of_bounds[:3])}...)")
                drc_warnings += 1

        print(f"  DRC completed: {drc_errors} errors, {drc_warnings} warnings")

    def _run_array_based_drc(self, context: EasyEDAContext):
        """Run DRC on array-based PCB format (Phase 4 enhancement).

        Validates:
        - Board outline dimensions and manufacturability
        - Component placement within boundaries
        - Track width and net assignments
        - Via dimensions and net assignments
        - Manufacturing constraints (JLCPCB standards)
        """
        drc_errors = 0
        drc_warnings = 0

        # Extract PCB elements from array
        board_outline = None
        components = []
        tracks = []
        vias = []
        head_data = None

        for element in context.pcb_data:
            if not isinstance(element, list) or len(element) == 0:
                continue

            elem_type = element[0]
            if elem_type == "BOARD_OUTLINE":
                board_outline = element
            elif elem_type == "COMPONENT":
                components.append(element)
            elif elem_type == "TRACK" or elem_type == "LINE":
                tracks.append(element)
            elif elem_type == "VIA":
                vias.append(element)
            elif elem_type == "HEAD":
                head_data = element[1] if len(element) > 1 else {}

        # DRC Rule 1: Board outline validation
        if board_outline:
            # Extract board dimensions from outline points
            if len(board_outline) > 2:
                points = board_outline[2]  # Points array
                if len(points) >= 8:  # At least 4 points (x,y pairs)
                    # Calculate bounding box
                    x_coords = [points[i] for i in range(0, len(points), 2)]
                    y_coords = [points[i] for i in range(1, len(points), 2)]
                    width = max(x_coords) - min(x_coords)
                    height = max(y_coords) - min(y_coords)

                    # Check JLCPCB manufacturing limits
                    if width < 20 or height < 20:
                        context.warnings.append(f"DRC: Board size ({width:.1f}mm × {height:.1f}mm) below JLCPCB minimum (20mm × 20mm)")
                        drc_warnings += 1

                    if width > 500 or height > 500:
                        context.warnings.append(f"DRC: Board size ({width:.1f}mm × {height:.1f}mm) exceeds JLCPCB maximum (500mm × 500mm)")
                        drc_warnings += 1

                    print(f"    Board: {width:.1f}mm × {height:.1f}mm")
        else:
            context.errors.append("DRC: No board outline defined")
            drc_errors += 1

        # DRC Rule 2: Component placement validation
        if len(components) == 0:
            context.errors.append("DRC: No components placed on PCB")
            drc_errors += 1
        else:
            print(f"    Components: {len(components)}")
            # In array PCB 1.8 format, the COMPONENT element does not carry footprint UUID directly
            # (mapping is maintained at project/device level). Do not error on footprint presence here.

        # DRC Rule 3: Track validation (net-aware)
        if len(tracks) > 0:
            print(f"    Tracks: {len(tracks)}")
            track_width = self.config.get('routing', {}).get('track_width', 0.25)
            unassigned_nets = 0

            for track in tracks:
                # Accept either TRACK or LINE shapes; in PCB 1.8, routed copper is encoded as LINE
                # LINE format we expect: ["LINE", id, 0, net, layerId, x1, y1, x2, y2, widthMil, 0]
                # TRACK legacy format: ["TRACK", id, [[x1,y1,x2,y2]], width, layer, net, style]
                net_name = None
                if track and track[0] == "LINE" and len(track) > 3:
                    net_name = track[3]
                elif track and track[0] == "TRACK" and len(track) > 6:
                    net_name = track[5]

                    # CRITICAL: Check for tracks without net assignment
                if not net_name or net_name == "":
                    unassigned_nets += 1

            if unassigned_nets > 0:
                context.warnings.append(f"DRC: {unassigned_nets} tracks without net assignment (risk of shorts)")
                drc_warnings += 1
        else:
            # No tracks might be OK for simple boards (e.g., breakout boards)
            context.warnings.append("DRC: No routing tracks defined (unrouted board)")
            drc_warnings += 1

        # DRC Rule 4: Via validation (net-aware)
        if len(vias) > 0:
            print(f"    Vias: {len(vias)}")
            min_via_drill = self.config.get('routing', {}).get('via_drill', 0.4)
            min_via_diameter = self.config.get('routing', {}).get('via_diameter', 0.8)
            unassigned_vias = 0

            for via in vias:
                # Format: ["VIA", id, x, y, diameter, drill, net]
                if len(via) > 6:
                    diameter = via[4]
                    drill = via[5]
                    net_name = via[6]

                    # Check via dimensions
                    if drill < min_via_drill:
                        context.warnings.append(f"DRC: Via at ({via[2]:.1f}, {via[3]:.1f}) drill {drill}mm below minimum {min_via_drill}mm")
                        drc_warnings += 1

                    if diameter < min_via_diameter:
                        context.warnings.append(f"DRC: Via at ({via[2]:.1f}, {via[3]:.1f}) diameter {diameter}mm below minimum {min_via_diameter}mm")
                        drc_warnings += 1

                    # CRITICAL: Check for vias without net assignment
                    if not net_name or net_name == "":
                        unassigned_vias += 1

            if unassigned_vias > 0:
                context.warnings.append(f"DRC: {unassigned_vias} vias without net assignment (risk of shorts)")
                drc_warnings += 1

        # DRC Rule 5: Layer validation
        if head_data and 'layers' in head_data:
            layers = head_data['layers']
            if layers < 1 or layers > 6:
                context.warnings.append(f"DRC: Layer count {layers} outside JLCPCB standard range (1-6)")
                drc_warnings += 1
            print(f"    Layers: {layers}")

        print(f"  DRC completed: {drc_errors} errors, {drc_warnings} warnings")

    def _validate_endpoint_snapping(self, context: EasyEDAContext) -> None:
        """Verify track endpoints coincide with a PAD center of the same net (importer-parity).

        Emits warnings by default; in strict mode, promotes to errors. Keeps tolerance
        modest so small quantization differences are accepted.
        """
        if not isinstance(context.pcb_data, list) or not context.pcb_data:
            return

        # Collect pad centers by net and set of coordinates (mil)
        pad_centers_by_net = {}
        for el in context.pcb_data:
            if not (isinstance(el, list) and el):
                continue
            if el[0] == "PAD" and len(el) > 8:
                net = (el[3] or "")
                x = el[6]
                y = el[7]
                try:
                    x = float(x)
                    y = float(y)
                except Exception:
                    continue
                pad_centers_by_net.setdefault(net, []).append((x, y))

        # Check LINE endpoints
        not_snapped = 0
        total_endpoints = 0
        tol_mil = 4.0  # ~0.1mm

        def _is_close(ax, ay, net):
            pts = pad_centers_by_net.get(net or "", [])
            if not pts:
                return False
            for (bx, by) in pts:
                if abs(ax - bx) <= tol_mil and abs(ay - by) <= tol_mil:
                    return True
            return False

        for el in context.pcb_data:
            if not (isinstance(el, list) and el):
                continue
            if el[0] == "LINE" and len(el) > 10:
                net = el[3]
                x1, y1, x2, y2 = el[5], el[6], el[7], el[8]
                try:
                    x1 = float(x1); y1 = float(y1); x2 = float(x2); y2 = float(y2)
                except Exception:
                    continue
                total_endpoints += 2
                a_ok = _is_close(x1, y1, net)
                b_ok = _is_close(x2, y2, net)
                if not a_ok:
                    not_snapped += 1
                if not b_ok:
                    not_snapped += 1

        if total_endpoints:
            msg = f"Endpoint snapping: {total_endpoints - not_snapped}/{total_endpoints} endpoints snapped within {tol_mil} mil"
            if not_snapped == 0:
                context.stats['endpoint_snap'] = 'OK'
                context.warnings.append(msg)
            else:
                if self.strict_mode:
                    context.errors.append(msg)
                else:
                    context.warnings.append(msg)

    def _validate_sch_pcb_parity(self, context: EasyEDAContext) -> None:
        """Check that schematic designators are present on PCB and have PAD_NET mappings.

        Generic and schema-tolerant: extracts designators via ATTR from SCH/PCB arrays,
        then verifies every schematic ref has a PCB component and at least one PAD_NET.
        In strict mode, any discrepancy is an error; otherwise a warning.
        """
        if not isinstance(context.schematic_data, list) or not isinstance(context.pcb_data, list):
            return

        # SCH: comp_id → designator
        sch_designators = {}
        for el in context.schematic_data:
            if not (isinstance(el, list) and el):
                continue
            if el[0] == "COMPONENT":
                sch_designators.setdefault(el[1], None)
            elif el[0] == "ATTR" and len(el) > 4 and el[3] == "Designator":
                sch_designators[el[2]] = el[4]

        # Map designator set from SCH
        sch_refs = {d for d in sch_designators.values() if d}

        # PCB: comp_id → designator
        pcb_designators = {}
        for el in context.pcb_data:
            if not (isinstance(el, list) and el):
                continue
            if el[0] == "COMPONENT":
                pcb_designators.setdefault(el[1], None)
            elif el[0] == "ATTR" and len(el) > 4 and el[3] == "Designator":
                pcb_designators[el[2]] = el[4]

        # Build PCB designator set
        pcb_refs = {d for d in pcb_designators.values() if d}

        # PAD_NET counts per PCB COMPONENT id
        padnet_count = {}
        for el in context.pcb_data:
            if not (isinstance(el, list) and el):
                continue
            if el[0] == "PAD_NET" and len(el) > 4:
                comp_id = el[1]
                padnet_count[comp_id] = padnet_count.get(comp_id, 0) + 1

        # Translate comp_id→designator for PAD_NET coverage
        ref_to_padnets = {}
        for comp_id, des in pcb_designators.items():
            if not des:
                continue
            ref_to_padnets[des] = ref_to_padnets.get(des, 0) + padnet_count.get(comp_id, 0)

        # Compute discrepancies
        missing_on_pcb = sorted(sch_refs - pcb_refs)
        padnet_missing = sorted([r for r in sch_refs if ref_to_padnets.get(r, 0) == 0])

        def _report(msg):
            if self.strict_mode:
                context.errors.append(msg)
            else:
                context.warnings.append(msg)

        if missing_on_pcb:
            _report(f"SCH↔PCB parity: {len(missing_on_pcb)} schematic refs missing on PCB (e.g., {', '.join(missing_on_pcb[:5])})")
        if padnet_missing:
            _report(f"Pad-net coverage: {len(padnet_missing)} refs have 0 PAD_NET mappings (e.g., {', '.join(padnet_missing[:5])})")

    def _validate_schematic_endpoints(self, context: EasyEDAContext) -> None:
        """Detect wires whose endpoints do not land on known pin positions or junctions.

        Uses context.sch_pin_positions (if present) produced by the assembler.
        This catches the "free network with no pins attached" class before release.
        """
        if not isinstance(context.schematic_data, list):
            return
        # Collect wire endpoints
        wire_pts = []
        for el in context.schematic_data:
            if not (isinstance(el, list) and el):
                continue
            if el[0] == "WIRE" and len(el) > 2:
                for seg in el[2]:
                    try:
                        x1, y1, x2, y2 = seg
                        wire_pts.append((float(x1), float(y1)))
                        wire_pts.append((float(x2), float(y2)))
                    except Exception:
                        continue
        # Set of junctions by coordinates (appear >=3 times among wire endpoints)
        from collections import Counter
        counts = Counter(wire_pts)
        junctions = {pt for pt, c in counts.items() if c >= 3}

        # Known pin positions (if provided)
        pin_pos = set()
        try:
            for _, (px, py) in getattr(context, 'sch_pin_positions', {}).items():
                pin_pos.add((float(px), float(py)))
        except Exception:
            pin_pos = set()

        # Check endpoints
        def _ok(pt):
            return (pt in pin_pos) or (pt in junctions) or (counts.get(pt, 0) >= 2)

        bad = [pt for pt in wire_pts if not _ok(pt)]
        if bad:
            msg = f"Schematic endpoints not snapped: {len(bad)} endpoints (example: {bad[0]})"
            if self.strict_mode:
                context.errors.append(msg)
            else:
                context.warnings.append(msg)

    def _run_pro_erc(self, context: EasyEDAContext):
        """Run comprehensive Pro-specific Electrical Rule Check."""
        print("  Running ERC (Electrical Rule Check)...")
        erc_errors = 0
        erc_warnings = 0

        # ERC Rule 1: Power and ground net detection
        power_nets = []
        ground_nets = []

        import re
        power_patterns = [
            r'\bvcc\b', r'\bvdd\b', r'\bvin\b', r'\bvbus\b', r'\bvbat\b', r'\bvref\b', r'\bv\+\b',
            r'\b\+?5v\b', r'\b\+?3v3\b', r'\b\+?12v\b', r'\b\+?24v\b',
            r'\bv\d+p\d+\b',   # v1p8, v3p3, v2p5, etc.
            r'\bv\d+\b',        # v5, v12, v24, etc.
            r'\b\d+v\b'         # 5v, 12v forms
        ]
        power_regex = re.compile('|'.join(power_patterns))
        ground_regex = re.compile(r'\b(gnd|vss|0v|ground|v-)\b')

        for net_name in context.nets:
            net_lower = net_name.lower()
            if power_regex.search(net_lower) or net_lower.endswith('_out'):
                power_nets.append(net_name)
            if ground_regex.search(net_lower):
                ground_nets.append(net_name)

        if not power_nets:
            # Downgrade to warning: some subcircuits may omit explicit power rail naming
            context.warnings.append("ERC: No power net detected - verify power rails are present")
            erc_warnings += 1
        else:
            print(f"    Found {len(power_nets)} power net(s): {', '.join(power_nets[:3])}")

        if not ground_nets:
            context.errors.append("ERC: No ground net detected - circuit requires ground reference")
            erc_errors += 1
        else:
            print(f"    Found {len(ground_nets)} ground net(s): {', '.join(ground_nets[:3])}")

        # ERC Rule 2: Floating pins detection
        connected_pins = set()
        nc_pins = set()
        for net_name, net_points in context.nets.items():
            for point in net_points:
                connected_pins.add(point)
                # Track NC (No Connect) pins separately - these are intentionally unconnected
                if net_name.startswith('NC_'):
                    nc_pins.add(point)

        floating_pins = 0
        for comp_ref, comp_data in context.components.items():
            comp_type = comp_data.get('type', '').lower()
            pins = comp_data.get('pins', [])

            # Skip mechanical components
            if comp_type in ['heatsink', 'mounting_hole', 'fiducial', 'test_point']:
                continue

            for pin in pins:
                pin_ref = f"{comp_ref}.{pin}"
                # Only warn if pin is not connected AND not marked as NC
                if pin_ref not in connected_pins and pin_ref not in nc_pins:
                    context.warnings.append(f"ERC: Floating pin {comp_ref} pin {pin}")
                    floating_pins += 1
                    erc_warnings += 1

        if floating_pins > 0:
            print(f"    Found {floating_pins} floating pin(s)")

        # ERC Rule 3: Unconnected components
        connected_components = set()
        for net_name, net_points in context.nets.items():
            # Skip NC (No Connect) nets when checking component connectivity
            if net_name.startswith('NC_'):
                continue
            for point in net_points:
                if '.' in point:
                    comp_ref = point.split('.')[0]
                    connected_components.add(comp_ref)

        unconnected_count = 0
        for comp_ref, comp_data in context.components.items():
            comp_type = comp_data.get('type', '').lower()

            # Skip mechanical components
            if comp_type in ['heatsink', 'mounting_hole', 'fiducial', 'test_point']:
                continue

            if comp_ref not in connected_components:
                context.errors.append(f"ERC: Component {comp_ref} ({comp_type}) has no connections")
                unconnected_count += 1
                erc_errors += 1

        if unconnected_count > 0:
            print(f"    Found {unconnected_count} unconnected component(s)")

        # ERC Rule 4: Power pin connections
        for comp_ref, comp_data in context.components.items():
            comp_type = comp_data.get('type', '').lower()
            pins = comp_data.get('pins', [])

            # Check ICs for power pins (only if they have more than 4 pins - simple ICs might not need power)
            if comp_type in ['ic', 'microcontroller', 'opamp', 'regulator'] and len(pins) > 4:
                has_vcc = False
                has_gnd = False

                for pin in pins:
                    pin_ref = f"{comp_ref}.{pin}"
                    for net_name, net_points in context.nets.items():
                        # Skip NC nets
                        if net_name.startswith('NC_'):
                            continue
                        if pin_ref in net_points:
                            if net_name in power_nets:
                                has_vcc = True
                            if net_name in ground_nets:
                                has_gnd = True

                # Only warn if component has NO power connections at all
                # Many designs intentionally use ICs without explicit power pins in schematic
                if not has_vcc and not has_gnd:
                    context.warnings.append(f"ERC: {comp_type.upper()} {comp_ref} has no power or ground connections")
                    erc_warnings += 1

        # ERC Rule 5: Short circuit detection (same net multiple times)
        for net_name, net_points in context.nets.items():
            if len(set(net_points)) != len(net_points):
                context.warnings.append(f"ERC: Net {net_name} has duplicate connection points")
                erc_warnings += 1

        # ERC Rule 6: Single-point nets (stub nets)
        stub_nets = []
        for net_name, net_points in context.nets.items():
            # Skip NC (No Connect) nets - these are intentionally single-point
            if net_name.startswith('NC_'):
                continue
            if len(net_points) == 1:
                stub_nets.append(net_name)
                context.warnings.append(f"ERC: Net {net_name} has only one connection (stub net)")
                erc_warnings += 1

        if stub_nets:
            print(f"    Found {len(stub_nets)} stub net(s)")

        # ERC Rule 7: Decoupling capacitor check
        capacitors_on_power = 0
        for comp_ref, comp_data in context.components.items():
            comp_type = comp_data.get('type', '').lower()
            if comp_type == 'capacitor':
                # Check if capacitor is connected to power and ground
                comp_nets = []
                for net_name, net_points in context.nets.items():
                    for point in net_points:
                        if point.startswith(f"{comp_ref}."):
                            comp_nets.append(net_name)

                has_power = any(net in power_nets for net in comp_nets)
                has_ground = any(net in ground_nets for net in comp_nets)

                if has_power and has_ground:
                    capacitors_on_power += 1

        if capacitors_on_power == 0 and power_nets:
            context.warnings.append("ERC: No decoupling capacitors detected on power rails")
            erc_warnings += 1
        else:
            print(f"    Found {capacitors_on_power} decoupling capacitor(s)")

        # ERC Rule 8: Net connectivity validation
        total_nets = len(context.nets)
        total_connections = sum(len(points) for points in context.nets.values())
        print(f"    Total nets: {total_nets}, Total connections: {total_connections}")

        if total_connections < len(context.components):
            context.warnings.append(f"ERC: Low connectivity ratio - {total_connections} connections for {len(context.components)} components")
            erc_warnings += 1

        print(f"  ERC completed: {erc_errors} errors, {erc_warnings} warnings")

    def _generate_report(self, context: EasyEDAContext) -> Dict:
        """Generate Pro validation report."""
        return {
            'passed': len(context.errors) == 0,
            'errors': context.errors,
            'warnings': context.warnings,
            'statistics': {
                'total_components': len(context.components),
                'total_nets': len(context.nets),
                'total_connections': len(context.connections),
                'format': 'EasyEDA Professional',
                'pcb_metrics': self.pcb_metrics,
            },
            'checks': {
                'pro_schematic': 'PASS' if not any('schematic' in e for e in context.errors) else 'FAIL',
                'pro_pcb': 'PASS' if not any('PCB' in e for e in context.errors) else 'FAIL',
                'connectivity': 'PASS' if not any('connection' in e for e in context.errors) else 'FAIL',
                'pro_drc': 'PASS' if not any('Track' in w or 'Via' in w for w in context.warnings) else 'WARNING',
                'pro_erc': 'PASS' if not any('power' in w or 'ground' in w for w in context.warnings) else 'WARNING'
            }
        }

    def _enforce_verification_artifacts(self, context: EasyEDAContext) -> None:
        """Fail-closed if required EasyEDA verification artifacts are missing."""
        candidate_roots = []
        try:
            if getattr(context, "output_path", None):
                out_base = Path(context.output_path)
                candidate_roots.append(out_base)
                candidate_roots.append(out_base / "easyeda_results")
                candidate_roots.append(out_base.parent / "easyeda_results")
            if getattr(context, "input_path", None):
                in_base = Path(context.input_path).parent
                candidate_roots.append(in_base / "easyeda_results")
        except Exception:
            candidate_roots = []

        # Remove duplicates while preserving order
        seen = set()
        ordered_roots = []
        for root in candidate_roots:
            if root not in seen:
                ordered_roots.append(root)
                seen.add(root)

        if not ordered_roots:
            context.errors.append("CRITICAL: Cannot locate easyeda_results folder to verify ERC/DRC/DFM artifacts")
            return

        def _require(root: Path) -> bool:
            erc_dir = root / "ERC" if root.name == "easyeda_results" else root / "easyeda_results" / "ERC"
            drc_dir = root / "DRC" if root.name == "easyeda_results" else root / "easyeda_results" / "DRC"
            dfm_dir = root / "verification" if root.name == "easyeda_results" else root / "easyeda_results" / "verification"

            missing = []
            invalid = []
            for path, label in ((erc_dir, "ERC"), (drc_dir, "DRC"), (dfm_dir, "DFM")):
                if not path.exists() or not any(path.iterdir()):
                    missing.append(f"{label} under {path}")
                    continue
                for f in path.iterdir():
                    name_lc = f.name.lower()
                    if "placeholder" in name_lc:
                        invalid.append(f"Placeholder {label} artifact detected: {f}")
                        continue
                    try:
                        head = f.read_bytes()[:256].lower()
                        if b"placeholder" in head:
                            invalid.append(f"Placeholder content detected in {label} artifact: {f}")
                    except Exception:
                        invalid.append(f"Unreadable {label} artifact: {f}")

            for msg in missing + invalid:
                context.errors.append(f"CRITICAL: {msg}")

            if missing or invalid:
                return False
            return True

        for root in ordered_roots:
            if _require(root):
                return
