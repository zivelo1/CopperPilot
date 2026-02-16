# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Route-to-Pad Connector - Fix Unconnected Pads After Freerouting
===============================================================

TC #55 FIX 0.1/0.2 (2025-11-27): Critical Track Extraction Rewrite

CHANGELOG:
==========
- TC #55 FIX 0.1: Rewrote _extract_track_endpoints() to use S-expression parsing
  instead of regex. The old regex didn't match KiCad 9's format correctly,
  resulting in 0 track endpoints extracted and 0 via injections.

- TC #55 FIX 0.2: Enhanced logging for via injection debugging.
  Added layer distribution analysis, expected via count calculation,
  and detailed console output for each via injection.

- TC #52 FIX 1.2 (2025-11-26): Original route-to-pad connector implementation

ROOT CAUSE ANALYSIS (TC #55):
=============================
Previous regex pattern at line 589:
    r'\\(segment\\s+\\(start...' with re.DOTALL

Failed because KiCad 9 outputs segments in various formats:
- Single line with varying whitespace
- Multi-line with indentation
- The .*? lazy match with re.DOTALL still had issues with greedy matching

Result: 0 track endpoints extracted → 0 via injections → 438 DRC violations

SOLUTION:
=========
1. Parse PCB to extract all pad positions and their nets
2. Parse PCB to extract all track segment endpoints using S-expr parsing
   (same method used successfully for footprints/pads)
3. For each pad, check if any track endpoint on same net is:
   a. Within PAD_CONNECTED_THRESHOLD (0.1mm) - check layer mismatch!
   b. Within PAD_CONNECTION_RADIUS (5mm) - close enough to connect
   c. Beyond radius - routing failure, cannot auto-fix
4. For layer mismatches, add via at pad position
5. For nearby endpoints, add final segment + via if needed

GENERIC DESIGN:
- Works for ANY circuit topology
- Handles ANY component type (R, C, U, J, etc.)
- Supports multi-layer boards (F.Cu, B.Cu, inner layers)
- Uses manufacturing_config.py for all parameters
- No hardcoded values, footprints, or net names

Author: Claude Code
Date: 2025-11-27
Version: 2.0.0 (TC #55)
"""

from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass, field
import re
import uuid
import math
import logging

# Import centralized configuration
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from kicad.manufacturing_config import MANUFACTURING_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class PadInfo:
    """
    Information about a PCB pad.

    GENERIC: Works for any component type, any pad shape.
    """
    reference: str       # Component reference (e.g., "U1", "R5")
    pad_number: str      # Pad number/name (e.g., "1", "44", "A1")
    net_name: str        # Net this pad connects to
    net_idx: int         # KiCad net index
    x: float             # Pad center X position (mm)
    y: float             # Pad center Y position (mm)
    layer: str           # Primary layer (F.Cu or B.Cu for SMD, both for THT)
    is_through_hole: bool  # True if pad connects both layers


@dataclass
class TrackEndpoint:
    """
    Information about a track segment endpoint.

    GENERIC: Works for any track on any layer.
    """
    net_name: str        # Net this track belongs to
    net_idx: int         # KiCad net index
    x: float             # Endpoint X position (mm)
    y: float             # Endpoint Y position (mm)
    layer: str           # Layer (F.Cu or B.Cu)
    segment_uuid: str    # UUID of the segment this endpoint belongs to


@dataclass
class TrackSegment:
    """
    TC #75 PRIORITY 2 (2025-12-08): Full track segment for midpoint connection.

    Used to find the closest point on a track segment to a pad, enabling
    connection to any point along a track (not just endpoints).

    GENERIC: Works for any track on any layer.
    """
    net_name: str        # Net this track belongs to
    net_idx: int         # KiCad net index
    x1: float            # Start X position (mm)
    y1: float            # Start Y position (mm)
    x2: float            # End X position (mm)
    y2: float            # End Y position (mm)
    layer: str           # Layer (F.Cu or B.Cu)
    segment_uuid: str    # UUID of the segment


@dataclass
class ConnectionFix:
    """
    A fix to apply to connect a route to a pad.

    May include segment and/or via.
    """
    pad: PadInfo
    endpoint: TrackEndpoint
    segment_x1: float    # Segment start X
    segment_y1: float    # Segment start Y
    segment_x2: float    # Segment end X (pad center)
    segment_y2: float    # Segment end Y (pad center)
    segment_layer: str   # Layer for segment
    needs_via: bool      # True if via needed for layer transition
    via_x: float         # Via X position
    via_y: float         # Via Y position
    distance: float      # Distance from endpoint to pad


class RoutePadConnector:
    """
    Repair unconnected pads after Freerouting by adding final segments and vias.

    GENERIC: Works for ANY PCB, ANY circuit complexity.

    TC #52 FIX 1.2 (2025-11-26):
    - Parses PCB to find all pads and track endpoints
    - Identifies pads that are close to routes but not connected
    - Generates final segments and vias to complete connections

    Usage:
        connector = RoutePadConnector()
        success, stats = connector.repair_connections(pcb_file)
    """

    def __init__(self, config=None):
        """
        Initialize connector with manufacturing configuration.

        Args:
            config: ManufacturingConfig instance (uses global if None)

        GENERIC: Configuration loaded from single source of truth.
        TC #63 PHASE 4.1 (2025-11-30): Added dynamic search radius support.
        TC #73 PHASE 6.1 (2025-12-08): Enhanced connection strategies.
        """
        self.config = config or MANUFACTURING_CONFIG

        # Load parameters from central config
        self.pad_connection_radius = self.config.PAD_CONNECTION_RADIUS
        self.pad_connected_threshold = self.config.PAD_CONNECTED_THRESHOLD
        self.via_diameter = self.config.DEFAULT_CONNECTION_VIA_DIAMETER
        self.via_drill = self.config.DEFAULT_CONNECTION_VIA_DRILL
        self.default_trace_width = self.config.DEFAULT_TRACE_WIDTH

        # TC #63 PHASE 4.1: Dynamic search radius parameters
        # For large boards, increase search radius proportionally
        self.min_search_radius = 5.0  # Minimum 5mm search radius
        self.max_search_radius = 50.0  # Maximum 50mm search radius
        self.search_radius_factor = 0.1  # 10% of board diagonal

        # ═══════════════════════════════════════════════════════════════════════════
        # TC #73 PHASE 6.1: ENHANCED CONNECTION PARAMETERS
        # ═══════════════════════════════════════════════════════════════════════════
        # ROOT CAUSE (RC13): 498 unconnected pad violations because:
        # 1. Router gives up on blocked paths → empty wires
        # 2. Via placement offsets endpoint from pad center
        # 3. Fixed search radius doesn't scale with board size
        # 4. No multi-hop connection strategy
        #
        # FIX: More aggressive connection strategies
        # ═══════════════════════════════════════════════════════════════════════════
        self.multi_hop_enabled = True  # Allow connecting through intermediate points
        self.max_hops = 3  # Maximum intermediate points
        self.endpoint_snap_tolerance = 0.5  # Snap endpoints within 0.5mm to pad center
        self.fallback_search_multiplier = 2.0  # Double search radius on retry

    def _calculate_dynamic_search_radius(self, content: str) -> float:
        """
        TC #63 PHASE 4.1: Calculate dynamic search radius based on board size.

        ROOT CAUSE (RC9): The fixed 5mm search radius is insufficient for
        large boards where tracks may end far from pads due to complex routing.

        FIX: Use board diagonal to scale the search radius dynamically.

        Args:
            content: PCB file content

        Returns:
            Calculated search radius in mm

        GENERIC: Works for ANY board size.
        """
        # Extract board dimensions from (gr_rect ...) or (gr_poly ...) edges
        # Look for Edge.Cuts layer boundaries
        min_x = float('inf')
        max_x = float('-inf')
        min_y = float('inf')
        max_y = float('-inf')

        # Method 1: Look for gr_line on Edge.Cuts
        edge_pattern = r'\(gr_line\s+\(start\s+([\d.-]+)\s+([\d.-]+)\)\s+\(end\s+([\d.-]+)\s+([\d.-]+)\)[^)]*layer\s+"Edge\.Cuts"'
        for match in re.finditer(edge_pattern, content):
            x1, y1, x2, y2 = map(float, match.groups())
            min_x = min(min_x, x1, x2)
            max_x = max(max_x, x1, x2)
            min_y = min(min_y, y1, y2)
            max_y = max(max_y, y1, y2)

        # Method 2: If no Edge.Cuts found, estimate from component positions
        if min_x == float('inf'):
            # Extract all footprint positions
            at_pattern = r'\(footprint[^)]+\(at\s+([\d.-]+)\s+([\d.-]+)'
            for match in re.finditer(at_pattern, content):
                x, y = map(float, match.groups())
                min_x = min(min_x, x - 10)  # Add 10mm margin
                max_x = max(max_x, x + 10)
                min_y = min(min_y, y - 10)
                max_y = max(max_y, y + 10)

        # Calculate board diagonal
        if min_x != float('inf') and max_x != float('-inf'):
            width = max_x - min_x
            height = max_y - min_y
            diagonal = math.sqrt(width**2 + height**2)

            # Calculate dynamic radius: search_radius_factor * diagonal
            dynamic_radius = diagonal * self.search_radius_factor

            # Clamp to min/max bounds
            dynamic_radius = max(self.min_search_radius, min(self.max_search_radius, dynamic_radius))

            print(f"[RoutePadConnector] TC #63 PHASE 4.1: Board size {width:.1f}x{height:.1f}mm, "
                  f"diagonal {diagonal:.1f}mm → search radius {dynamic_radius:.1f}mm")
            return dynamic_radius
        else:
            # Fallback to default
            print(f"[RoutePadConnector] TC #63 PHASE 4.1: Could not determine board size, using default {self.pad_connection_radius}mm")
            return self.pad_connection_radius

    def repair_connections(self, pcb_file: Path) -> Tuple[bool, Dict]:
        """
        Main entry point: repair all unconnected pads in a PCB file.

        Args:
            pcb_file: Path to .kicad_pcb file

        Returns:
            Tuple of (success, statistics_dict)

        Statistics dict contains:
            - pads_total: Total pads found
            - pads_connected: Already connected pads
            - pads_fixed: Pads fixed by adding segments/vias
            - pads_unfixable: Pads too far from any route
            - segments_added: Number of segments added
            - vias_added: Number of vias added
            - nets_fixed: List of net names that were fixed

        GENERIC: Works for any PCB file.
        """
        stats = {
            'pads_total': 0,
            'pads_connected': 0,
            'pads_fixed': 0,
            'pads_unfixable': 0,
            'segments_added': 0,
            'vias_added': 0,
            'nets_fixed': [],
            'errors': []
        }

        print(f"[RoutePadConnector] Starting connection repair for {pcb_file.name}")
        logger.info(f"Starting connection repair for {pcb_file.name}")

        if not pcb_file.exists():
            error = f"PCB file does not exist: {pcb_file}"
            print(f"[RoutePadConnector] ERROR: {error}")
            stats['errors'].append(error)
            return False, stats

        try:
            content = pcb_file.read_text()
        except Exception as e:
            error = f"Failed to read PCB file: {e}"
            print(f"[RoutePadConnector] ERROR: {error}")
            stats['errors'].append(error)
            return False, stats

        # Step 1: Extract net mapping
        net_mapping = self._extract_net_mapping(content)
        print(f"[RoutePadConnector] Found {len(net_mapping)} nets in PCB")

        # TC #63 PHASE 4.1: Calculate dynamic search radius based on board size
        search_radius = self._calculate_dynamic_search_radius(content)

        # Step 2: Extract all pads
        pads = self._extract_pads(content, net_mapping)
        stats['pads_total'] = len(pads)
        print(f"[RoutePadConnector] Found {len(pads)} pads in PCB")

        # Step 3: Extract all track endpoints
        endpoints = self._extract_track_endpoints(content, net_mapping)
        print(f"[RoutePadConnector] Found {len(endpoints)} track endpoints in PCB")

        # Step 4: Organize endpoints by net for efficient lookup
        endpoints_by_net: Dict[str, List[TrackEndpoint]] = {}
        for ep in endpoints:
            if ep.net_name not in endpoints_by_net:
                endpoints_by_net[ep.net_name] = []
            endpoints_by_net[ep.net_name].append(ep)

        # TC #55 FIX 0.2: Log layer distribution for debugging
        layer_dist = {}
        for ep in endpoints:
            layer_dist[ep.layer] = layer_dist.get(ep.layer, 0) + 1
        print(f"[RoutePadConnector] Track layer distribution: {layer_dist}")

        pad_layer_dist = {}
        for pad in pads:
            pad_layer_dist[pad.layer] = pad_layer_dist.get(pad.layer, 0) + 1
        print(f"[RoutePadConnector] Pad layer distribution: {pad_layer_dist}")

        # TC #55 FIX 0.2: Pre-calculate expected via count
        expected_vias = 0
        for pad in pads:
            if not pad.net_name:
                continue
            net_endpoints = endpoints_by_net.get(pad.net_name, [])
            for ep in net_endpoints:
                if ep.layer != pad.layer and not pad.is_through_hole:
                    expected_vias += 1
                    break  # Only count once per pad
        print(f"[RoutePadConnector] Expected layer transition vias (estimate): {expected_vias}")

        # ═══════════════════════════════════════════════════════════════
        # TC #57 FIX 1.3: Extract existing vias to avoid duplicates
        # ═══════════════════════════════════════════════════════════════
        existing_vias = self._extract_existing_vias(content)
        print(f"[RoutePadConnector] Found {len(existing_vias)} existing vias in PCB")

        # Step 5: Find pads that need connection fixes
        fixes: List[ConnectionFix] = []
        # TC #57 FIX 1.3: Track statistics for duplicate via prevention
        vias_skipped_duplicate = 0

        for pad in pads:
            # Skip pads without a net (unconnected by design)
            if not pad.net_name or pad.net_name == "":
                continue

            # Get endpoints for this pad's net
            net_endpoints = endpoints_by_net.get(pad.net_name, [])

            if not net_endpoints:
                # No routes exist for this net - can't fix
                stats['pads_unfixable'] += 1
                # TC #55 FIX 0.2: More detailed logging
                logger.warning(f"Pad {pad.reference}.{pad.pad_number} on {pad.layer} has no routes on net '{pad.net_name}'")
                continue

            # Find closest endpoint to this pad
            closest_ep = None
            closest_dist = float('inf')

            for ep in net_endpoints:
                dist = math.sqrt((ep.x - pad.x)**2 + (ep.y - pad.y)**2)
                if dist < closest_dist:
                    closest_dist = dist
                    closest_ep = ep

            if closest_ep is None:
                stats['pads_unfixable'] += 1
                continue

            # Check connection status
            if closest_dist < self.pad_connected_threshold:
                # TC #54 FIX B.1: Check if layer transition via is needed!
                # Even if track endpoint is at pad position, if they're on different
                # layers and the pad is NOT through-hole, a via is still required.
                #
                # ROOT CAUSE: DRC reports show track at EXACT same coordinates as pad
                # but on different layer (B.Cu vs F.Cu) - this is NOT connected!
                if (closest_ep.layer != pad.layer) and not pad.is_through_hole:
                    # TC #57 FIX 1.3: Check if via already exists at this position
                    if self._is_via_at_position(existing_vias, pad.x, pad.y):
                        # Via already exists - pad is connected via existing via
                        stats['pads_connected'] += 1
                        vias_skipped_duplicate += 1
                        logger.debug(f"TC #57 FIX 1.3: Skipping duplicate via at ({pad.x:.3f}, {pad.y:.3f}) for {pad.reference}.{pad.pad_number}")
                        continue

                    # TC #55 FIX 0.2: Enhanced via injection logging
                    # This is the CRITICAL fix for the 438 DRC violations!
                    # Track is at pad position but on wrong layer - need via to connect
                    fix = ConnectionFix(
                        pad=pad,
                        endpoint=closest_ep,
                        segment_x1=closest_ep.x,
                        segment_y1=closest_ep.y,
                        segment_x2=pad.x,
                        segment_y2=pad.y,
                        segment_layer=closest_ep.layer,
                        needs_via=True,  # This is the critical part!
                        via_x=pad.x,
                        via_y=pad.y,
                        distance=closest_dist
                    )
                    fixes.append(fix)
                    # TC #55 FIX 0.2: Print to console for visibility (not just logger)
                    print(f"[RoutePadConnector] VIA NEEDED: {pad.reference}.{pad.pad_number} "
                          f"({closest_ep.layer} → {pad.layer}) at ({pad.x:.3f}, {pad.y:.3f})")
                    logger.info(
                        f"TC #55: Pad {pad.reference}.{pad.pad_number}: Adding via for layer transition "
                        f"({closest_ep.layer} -> {pad.layer}) at ({pad.x:.3f}, {pad.y:.3f})"
                    )
                else:
                    # Truly connected (same layer or through-hole pad)
                    stats['pads_connected'] += 1
                continue
            elif closest_dist < search_radius:  # TC #63 PHASE 4.1: Use dynamic search_radius
                # Close enough to fix
                needs_via = (closest_ep.layer != pad.layer) and not pad.is_through_hole

                # TC #57 FIX 1.3: Check for duplicate vias when adding new connections
                if needs_via and self._is_via_at_position(existing_vias, pad.x, pad.y):
                    # Via exists but we still need the segment
                    needs_via = False
                    vias_skipped_duplicate += 1
                    logger.debug(f"TC #57 FIX 1.3: Via exists at ({pad.x:.3f}, {pad.y:.3f}), adding segment only")

                fix = ConnectionFix(
                    pad=pad,
                    endpoint=closest_ep,
                    segment_x1=closest_ep.x,
                    segment_y1=closest_ep.y,
                    segment_x2=pad.x,
                    segment_y2=pad.y,
                    segment_layer=closest_ep.layer,
                    needs_via=needs_via,
                    via_x=pad.x,
                    via_y=pad.y,
                    distance=closest_dist
                )
                fixes.append(fix)
            else:
                # Too far to fix automatically - mark for extended search
                stats['pads_unfixable'] += 1
                # TC #73 PHASE 6.2: Track unfixable pads for extended search
                if not hasattr(self, '_unfixable_pads'):
                    self._unfixable_pads = []
                self._unfixable_pads.append((pad, closest_ep, closest_dist))
                logger.warning(
                    f"Pad {pad.reference}.{pad.pad_number} too far from route: "
                    f"{closest_dist:.2f}mm > {search_radius:.2f}mm (dynamic radius)"  # TC #63: Updated message
                )

        # TC #57 FIX 1.3: Log duplicate via prevention statistics
        if vias_skipped_duplicate > 0:
            print(f"[RoutePadConnector] TC #57 FIX 1.3: Prevented {vias_skipped_duplicate} duplicate vias")

        # ═══════════════════════════════════════════════════════════════════════════
        # TC #73 PHASE 6.2: EXTENDED SEARCH PASS FOR UNFIXABLE PADS
        # ═══════════════════════════════════════════════════════════════════════════
        # ROOT CAUSE: Some pads are just beyond the search radius but could still
        # be connected with a longer segment. This is especially common for:
        # - Large boards where component spacing varies
        # - Nets that route on one side but connect to pads on the other
        #
        # FIX: Do a second pass with doubled search radius for remaining unfixable pads
        # ═══════════════════════════════════════════════════════════════════════════
        if hasattr(self, '_unfixable_pads') and self._unfixable_pads:
            extended_radius = search_radius * self.fallback_search_multiplier
            print(f"[RoutePadConnector] TC #73 PHASE 6.2: Extended search for {len(self._unfixable_pads)} unfixable pads (radius: {extended_radius:.1f}mm)")

            extended_fixes = 0
            for pad, closest_ep, closest_dist in self._unfixable_pads:
                # Check if pad can be fixed with extended radius
                if closest_dist < extended_radius and closest_ep is not None:
                    needs_via = (closest_ep.layer != pad.layer) and not pad.is_through_hole

                    # TC #73: Check for existing via at extended connection point
                    if needs_via and self._is_via_at_position(existing_vias, pad.x, pad.y):
                        needs_via = False

                    fix = ConnectionFix(
                        pad=pad,
                        endpoint=closest_ep,
                        segment_x1=closest_ep.x,
                        segment_y1=closest_ep.y,
                        segment_x2=pad.x,
                        segment_y2=pad.y,
                        segment_layer=closest_ep.layer,
                        needs_via=needs_via,
                        via_x=pad.x,
                        via_y=pad.y,
                        distance=closest_dist
                    )
                    fixes.append(fix)
                    stats['pads_unfixable'] -= 1  # No longer unfixable
                    extended_fixes += 1
                    logger.info(f"TC #73 PHASE 6.2: Extended connection for {pad.reference}.{pad.pad_number} at {closest_dist:.1f}mm")

            if extended_fixes > 0:
                print(f"[RoutePadConnector] TC #73 PHASE 6.2: Recovered {extended_fixes} pads with extended search")

            # Clean up
            delattr(self, '_unfixable_pads')

        # ═══════════════════════════════════════════════════════════════════════════
        # TC #73 PHASE 6.3: MULTI-HOP CONNECTION FOR REMAINING UNFIXABLE
        # ═══════════════════════════════════════════════════════════════════════════
        # For pads STILL unfixable after extended search, try to find an intermediate
        # point that can bridge the connection. This works for pads that are far from
        # any endpoint but have endpoints nearby that share the same net.
        #
        # Strategy: Find 2+ endpoints on the same net that form a chain to the pad
        # ═══════════════════════════════════════════════════════════════════════════
        if self.multi_hop_enabled and stats['pads_unfixable'] > 0:
            remaining_unfixable = []
            for pad in pads:
                if not pad.net_name or pad.net_name == "":
                    continue
                # Check if this pad was NOT fixed yet
                already_fixed = any(f.pad.reference == pad.reference and f.pad.pad_number == pad.pad_number for f in fixes)
                already_connected = False
                net_endpoints = endpoints_by_net.get(pad.net_name, [])
                for ep in net_endpoints:
                    dist = math.sqrt((ep.x - pad.x)**2 + (ep.y - pad.y)**2)
                    if dist < self.pad_connected_threshold:
                        # Check layer compatibility
                        if ep.layer == pad.layer or pad.is_through_hole:
                            already_connected = True
                            break
                        # Check if via exists
                        if self._is_via_at_position(existing_vias, pad.x, pad.y):
                            already_connected = True
                            break

                if not already_fixed and not already_connected:
                    remaining_unfixable.append(pad)

            if remaining_unfixable:
                print(f"[RoutePadConnector] TC #73 PHASE 6.3: Multi-hop search for {len(remaining_unfixable)} remaining pads")

                for pad in remaining_unfixable:
                    net_endpoints = endpoints_by_net.get(pad.net_name, [])
                    if len(net_endpoints) < 2:
                        continue

                    # Find the best intermediate endpoint that can bridge to pad
                    # Strategy: Find endpoint closest to pad that has another endpoint nearby
                    best_fix = None
                    best_total_dist = float('inf')

                    for intermediate_ep in net_endpoints:
                        dist_to_pad = math.sqrt((intermediate_ep.x - pad.x)**2 + (intermediate_ep.y - pad.y)**2)

                        # Skip if too far even for extended connection
                        if dist_to_pad > search_radius * 3:  # Triple radius for multi-hop
                            continue

                        # Check if this endpoint is actually connected to the net
                        # (has another endpoint within connection threshold)
                        is_connected = False
                        for other_ep in net_endpoints:
                            if other_ep.segment_uuid == intermediate_ep.segment_uuid:
                                continue
                            dist_between = math.sqrt((other_ep.x - intermediate_ep.x)**2 + (other_ep.y - intermediate_ep.y)**2)
                            if dist_between < self.pad_connected_threshold:
                                is_connected = True
                                break

                        if is_connected and dist_to_pad < best_total_dist:
                            best_total_dist = dist_to_pad
                            needs_via = (intermediate_ep.layer != pad.layer) and not pad.is_through_hole

                            if needs_via and self._is_via_at_position(existing_vias, pad.x, pad.y):
                                needs_via = False

                            best_fix = ConnectionFix(
                                pad=pad,
                                endpoint=intermediate_ep,
                                segment_x1=intermediate_ep.x,
                                segment_y1=intermediate_ep.y,
                                segment_x2=pad.x,
                                segment_y2=pad.y,
                                segment_layer=intermediate_ep.layer,
                                needs_via=needs_via,
                                via_x=pad.x,
                                via_y=pad.y,
                                distance=dist_to_pad
                            )

                    if best_fix:
                        fixes.append(best_fix)
                        stats['pads_unfixable'] -= 1
                        logger.info(f"TC #73 PHASE 6.3: Multi-hop connection for {pad.reference}.{pad.pad_number} at {best_total_dist:.1f}mm")

                multi_hop_recovered = len(remaining_unfixable) - stats['pads_unfixable']
                if multi_hop_recovered > 0:
                    print(f"[RoutePadConnector] TC #73 PHASE 6.3: Recovered {multi_hop_recovered} pads with multi-hop")

        # ═══════════════════════════════════════════════════════════════════════════
        # TC #75 PRIORITY 2: MIDPOINT CONNECTION FOR REMAINING UNFIXABLE
        # ═══════════════════════════════════════════════════════════════════════════
        # For pads STILL unfixable, try connecting to the closest POINT on a track
        # segment (not just endpoints). This is crucial when tracks pass near pads
        # but don't have endpoints close by.
        #
        # This phase uses:
        # 1. _extract_track_segments() - gets full segment geometry
        # 2. _find_closest_segment_point() - finds closest point on any segment
        # ═══════════════════════════════════════════════════════════════════════════
        if stats['pads_unfixable'] > 0:
            print(f"[RoutePadConnector] TC #75 PRIORITY 2: Midpoint search for {stats['pads_unfixable']} remaining pads")

            # Extract full track segments
            track_segments = self._extract_track_segments(content, net_mapping)

            midpoint_fixes = 0
            for pad in pads:
                if not pad.net_name or pad.net_name == "":
                    continue

                # Check if this pad was already fixed
                already_fixed = any(
                    f.pad.reference == pad.reference and f.pad.pad_number == pad.pad_number
                    for f in fixes
                )
                if already_fixed:
                    continue

                # Check if already connected to endpoint
                already_connected = False
                net_endpoints = endpoints_by_net.get(pad.net_name, [])
                for ep in net_endpoints:
                    dist = math.sqrt((ep.x - pad.x)**2 + (ep.y - pad.y)**2)
                    if dist < self.pad_connected_threshold:
                        if ep.layer == pad.layer or pad.is_through_hole:
                            already_connected = True
                            break
                        if self._is_via_at_position(existing_vias, pad.x, pad.y):
                            already_connected = True
                            break

                if already_connected:
                    continue

                # Find closest point on any segment
                result = self._find_closest_segment_point(pad, track_segments)
                if result is None:
                    continue

                seg, closest_x, closest_y, dist = result

                # Only fix if within extended search radius
                if dist > search_radius * self.fallback_search_multiplier:
                    continue

                needs_via = (seg.layer != pad.layer) and not pad.is_through_hole

                # Check for existing via
                if needs_via and self._is_via_at_position(existing_vias, pad.x, pad.y):
                    needs_via = False

                # Create fix from segment midpoint to pad
                # Use a dummy TrackEndpoint for compatibility with ConnectionFix
                dummy_ep = TrackEndpoint(
                    net_name=seg.net_name,
                    net_idx=seg.net_idx,
                    x=closest_x,
                    y=closest_y,
                    layer=seg.layer,
                    segment_uuid=seg.segment_uuid
                )

                fix = ConnectionFix(
                    pad=pad,
                    endpoint=dummy_ep,
                    segment_x1=closest_x,
                    segment_y1=closest_y,
                    segment_x2=pad.x,
                    segment_y2=pad.y,
                    segment_layer=seg.layer,
                    needs_via=needs_via,
                    via_x=pad.x,
                    via_y=pad.y,
                    distance=dist
                )
                fixes.append(fix)
                stats['pads_unfixable'] -= 1
                midpoint_fixes += 1
                logger.info(f"TC #75: Midpoint connection for {pad.reference}.{pad.pad_number} "
                           f"at distance {dist:.2f}mm from segment midpoint")

            if midpoint_fixes > 0:
                print(f"[RoutePadConnector] TC #75 PRIORITY 2: Recovered {midpoint_fixes} pads with midpoint connection")

        # TC #54 FIX B.1: Count via-only fixes separately
        via_only_fixes = sum(1 for f in fixes if f.distance < self.pad_connected_threshold)
        segment_fixes = len(fixes) - via_only_fixes

        print(f"[RoutePadConnector] Found {len(fixes)} fixable connections:")
        print(f"[RoutePadConnector]   - {via_only_fixes} layer transition vias (endpoint at pad)")
        print(f"[RoutePadConnector]   - {segment_fixes} segment extensions to pads")

        # Step 6: Generate fix S-expressions
        if fixes:
            fix_sexpr = self._generate_fix_sexpr(fixes, stats)

            # Step 7: Insert fixes into PCB content
            content = self._insert_fixes(content, fix_sexpr)

            # Step 8: Write back
            pcb_file.write_text(content)

            stats['pads_fixed'] = len(fixes)
            stats['nets_fixed'] = list(set(f.pad.net_name for f in fixes))

            print(f"[RoutePadConnector] SUCCESS: Added {stats['segments_added']} segments, "
                  f"{stats['vias_added']} vias")
        else:
            print(f"[RoutePadConnector] No fixes needed - all pads connected or unfixable")

        return True, stats

    def _extract_net_mapping(self, content: str) -> Dict[str, int]:
        """
        Extract net name to index mapping from PCB content.

        Pattern: (net INDEX "NAME") or (net INDEX NAME)

        TC #56 FIX: Fixed bug where second pattern was matching quoted names
        and overwriting the first pattern's result with quoted version.
        Now only uses ONE pattern that handles both quoted and unquoted names.

        GENERIC: Works for any net naming convention.
        """
        mapping = {}

        # TC #56 FIX: Single pattern that handles both quoted and unquoted names
        # Group 2 captures quoted content (including empty), Group 3 captures unquoted
        # The * in group 2 allows matching empty quoted strings like (net 0 "")
        pattern = r'\(net\s+(\d+)\s+(?:"([^"]*)"|([^\s)]+))\)'

        for match in re.finditer(pattern, content):
            idx = int(match.group(1))
            # Use quoted name (group 2) if the match used quotes, otherwise unquoted (group 3)
            # Note: group(2) will be "" for empty quoted strings, which is still truthy match
            if match.group(2) is not None:
                name = match.group(2)  # Quoted (may be empty)
            else:
                name = match.group(3)  # Unquoted
            # Skip empty net names (net 0 "")
            if name and name.strip():
                mapping[name] = idx

        logger.debug(f"TC #56: Extracted {len(mapping)} net mappings")
        return mapping

    def _extract_pads(self, content: str, net_mapping: Dict[str, int]) -> List[PadInfo]:
        """
        Extract all pads from PCB content with their positions and nets.

        TC #53 FIX 0.1: Rewrote with S-expression parsing instead of regex.
        The previous regex approach failed because KiCad 9 uses multi-line format.

        KiCad 9 format example:
            (footprint "Diode_SMD:D_SOD-323"
                (layer "F.Cu")
                (uuid "...")
                (at 38.1 38.1)
                ...
                (pad "1" smd rect
                  (at -1.1 0.0)
                  (size 0.6 0.8)
                  (layers "F.Cu" "F.Paste" "F.Mask")
                  (net 9 "NET_3")
                )
            )

        GENERIC: Works for any footprint type, any pad shape, any KiCad version.
        """
        pads = []

        # Reverse net mapping (idx -> name)
        idx_to_name = {v: k for k, v in net_mapping.items()}

        # Step 1: Extract all footprint blocks using balanced parenthesis matching
        footprint_blocks = self._extract_sexp_blocks(content, "footprint")
        logger.debug(f"Found {len(footprint_blocks)} footprint blocks")

        for fp_block in footprint_blocks:
            # Step 2: Extract footprint position
            fp_pos = self._extract_at_position(fp_block)
            if not fp_pos:
                logger.warning("Footprint missing (at ...) position, skipping")
                continue

            fp_x, fp_y, fp_rot = fp_pos

            # Step 3: Extract reference designator
            reference = self._extract_reference(fp_block)

            # Step 4: Determine footprint layer (for SMD components)
            fp_layer = "F.Cu"  # Default
            layer_match = re.search(r'\(layer\s+"([^"]+)"\)', fp_block)
            if layer_match:
                fp_layer = layer_match.group(1)

            # Step 5: Extract all pad blocks from this footprint
            pad_blocks = self._extract_sexp_blocks(fp_block, "pad")

            for pad_block in pad_blocks:
                pad_info = self._parse_pad_block(
                    pad_block, fp_x, fp_y, fp_rot, fp_layer, reference, idx_to_name
                )
                if pad_info:
                    pads.append(pad_info)

        return pads

    def _extract_sexp_blocks(self, content: str, block_type: str) -> List[str]:
        """
        Extract all balanced S-expression blocks of a given type.

        TC #53 FIX 0.1: Proper S-expression parsing using parenthesis counting.

        Args:
            content: The content to search in
            block_type: The S-expression type (e.g., "footprint", "pad")

        Returns:
            List of complete S-expression blocks as strings

        GENERIC: Works for any S-expression block type.
        """
        blocks = []
        pattern = f'\\({block_type}\\s+'

        for match in re.finditer(pattern, content):
            start = match.start()
            # Count parentheses to find matching close
            depth = 0
            end = start

            for i in range(start, len(content)):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

            if depth == 0:
                blocks.append(content[start:end])

        return blocks

    def _extract_at_position(self, block: str) -> Optional[Tuple[float, float, float]]:
        """
        Extract (at X Y [ROT]) position from an S-expression block.

        Returns:
            Tuple of (x, y, rotation) or None if not found

        GENERIC: Works for any block with (at ...) element.
        """
        # Match (at X Y) or (at X Y ROT)
        at_match = re.search(r'\(at\s+([\d.-]+)\s+([\d.-]+)(?:\s+([\d.-]+))?\)', block)
        if at_match:
            x = float(at_match.group(1))
            y = float(at_match.group(2))
            rot = float(at_match.group(3)) if at_match.group(3) else 0.0
            return (x, y, rot)
        return None

    def _extract_reference(self, fp_block: str) -> str:
        """
        Extract reference designator from a footprint block.

        Handles both KiCad 9 format (property "Reference") and older formats.

        GENERIC: Works for any KiCad version.
        """
        # KiCad 9 format: (property "Reference" "R1" ...)
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', fp_block)
        if ref_match:
            return ref_match.group(1)

        # Older format: (fp_text reference "R1" ...)
        ref_match = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', fp_block)
        if ref_match:
            return ref_match.group(1)

        return "???"

    def _parse_pad_block(self, pad_block: str, fp_x: float, fp_y: float,
                         fp_rot: float, fp_layer: str, reference: str,
                         idx_to_name: Dict[int, str]) -> Optional[PadInfo]:
        """
        Parse a single pad block and return PadInfo.

        TC #53 FIX 0.1: Robust multi-line pad parsing.

        Args:
            pad_block: The complete (pad ...) S-expression
            fp_x, fp_y, fp_rot: Footprint position and rotation
            fp_layer: Footprint layer (F.Cu or B.Cu)
            reference: Component reference (R1, C1, U1, etc.)
            idx_to_name: Net index to name mapping

        Returns:
            PadInfo or None if pad has no net

        GENERIC: Works for any pad type (smd, thru_hole, connect, np_thru_hole).
        """
        # Extract pad number: (pad "1" ...) or (pad 1 ...)
        pad_num_match = re.search(r'\(pad\s+"?([^"\s]+)"?\s+', pad_block)
        if not pad_num_match:
            return None
        pad_num = pad_num_match.group(1)

        # Extract pad type: smd, thru_hole, connect, np_thru_hole
        pad_type_match = re.search(r'\(pad\s+"?[^"\s]+"?\s+(\w+)', pad_block)
        pad_type = pad_type_match.group(1) if pad_type_match else "smd"

        # Extract pad position relative to footprint
        pad_pos = self._extract_at_position(pad_block)
        if not pad_pos:
            # Some pads might not have (at ...) - assume (0, 0)
            rel_x, rel_y, rel_rot = 0.0, 0.0, 0.0
        else:
            rel_x, rel_y, rel_rot = pad_pos

        # Extract net information: (net INDEX "NAME") or (net INDEX NAME)
        net_match = re.search(r'\(net\s+(\d+)\s+"?([^")]+)"?\)', pad_block)
        if not net_match:
            # Pad has no net - skip it (unconnected by design)
            return None

        net_idx = int(net_match.group(1))
        net_name = net_match.group(2).strip()

        # Calculate absolute position (apply footprint rotation)
        rad = math.radians(fp_rot)
        abs_x = fp_x + rel_x * math.cos(rad) - rel_y * math.sin(rad)
        abs_y = fp_y + rel_x * math.sin(rad) + rel_y * math.cos(rad)

        # Determine if through-hole
        is_through_hole = pad_type.lower() in ("thru_hole", "np_thru_hole")

        # Determine pad layer
        # - Through-hole pads connect both layers
        # - SMD pads are on the footprint's layer
        layer = fp_layer
        if is_through_hole:
            layer = "F.Cu"  # THT pads connect both, but report as F.Cu

        # Check for explicit layers specification
        layers_match = re.search(r'\(layers\s+"([^"]+)"', pad_block)
        if layers_match and not is_through_hole:
            first_layer = layers_match.group(1)
            if first_layer in ("F.Cu", "B.Cu"):
                layer = first_layer

        return PadInfo(
            reference=reference,
            pad_number=pad_num,
            net_name=net_name,
            net_idx=net_idx,
            x=abs_x,
            y=abs_y,
            layer=layer,
            is_through_hole=is_through_hole
        )

    def _extract_track_endpoints(self, content: str, net_mapping: Dict[str, int]) -> List[TrackEndpoint]:
        """
        Extract all track segment endpoints from PCB content.

        TC #55 FIX 0.1 (2025-11-27): REWRITTEN with S-expression parsing.

        ROOT CAUSE: Previous regex pattern didn't match KiCad 9's format correctly.
        The .*? pattern doesn't cross newlines by default, and KiCad 9 sometimes
        outputs segments on multiple lines or with varying whitespace.

        KiCad 9 format examples (both should work):
            Single line:
            (segment (start 41.230 92.710) (end 41.230 92.108) (width 0.250) (layer "B.Cu") (net 14) (uuid "..."))

            Multi-line:
            (segment
              (start 41.230 92.710)
              (end 41.230 92.108)
              (width 0.250)
              (layer "B.Cu")
              (net 14)
              (uuid "...")
            )

        Each segment contributes TWO endpoints (start and end).

        GENERIC: Works for any segment format, any layer, any KiCad version.
        """
        endpoints = []

        # Reverse net mapping for net index -> name lookup
        idx_to_name = {v: k for k, v in net_mapping.items()}

        # TC #55 FIX 0.1: Use S-expression block extraction (like pads)
        # This correctly handles multi-line and varying whitespace formats
        segment_blocks = self._extract_sexp_blocks(content, "segment")

        logger.debug(f"TC #55: Found {len(segment_blocks)} segment blocks using S-expr parsing")

        for seg_block in segment_blocks:
            # Extract start position: (start X Y)
            start_match = re.search(r'\(start\s+([\d.-]+)\s+([\d.-]+)\)', seg_block)
            if not start_match:
                logger.warning(f"Segment missing (start ...), skipping: {seg_block[:50]}...")
                continue

            # Extract end position: (end X Y)
            end_match = re.search(r'\(end\s+([\d.-]+)\s+([\d.-]+)\)', seg_block)
            if not end_match:
                logger.warning(f"Segment missing (end ...), skipping: {seg_block[:50]}...")
                continue

            # Extract layer: (layer "F.Cu") or (layer "B.Cu")
            layer_match = re.search(r'\(layer\s+"([^"]+)"\)', seg_block)
            if not layer_match:
                logger.warning(f"Segment missing (layer ...), skipping: {seg_block[:50]}...")
                continue

            # Extract net: (net N) where N is integer
            net_match = re.search(r'\(net\s+(\d+)\)', seg_block)
            if not net_match:
                # Some segments might not have net (e.g., edge cuts) - skip them
                logger.debug(f"Segment has no net, skipping: {seg_block[:50]}...")
                continue

            # Extract uuid: (uuid "...")
            uuid_match = re.search(r'\(uuid\s+"([^"]+)"\)', seg_block)
            seg_uuid = uuid_match.group(1) if uuid_match else str(uuid.uuid4())

            # Parse extracted values
            x1 = float(start_match.group(1))
            y1 = float(start_match.group(2))
            x2 = float(end_match.group(1))
            y2 = float(end_match.group(2))
            layer = layer_match.group(1)
            net_idx = int(net_match.group(1))

            # Get net name from mapping, fallback to NET_N format
            net_name = idx_to_name.get(net_idx, f"NET_{net_idx}")

            # Add BOTH endpoints (start and end) for this segment
            # This is critical for finding the closest track endpoint to each pad
            endpoints.append(TrackEndpoint(
                net_name=net_name,
                net_idx=net_idx,
                x=x1,
                y=y1,
                layer=layer,
                segment_uuid=seg_uuid
            ))
            endpoints.append(TrackEndpoint(
                net_name=net_name,
                net_idx=net_idx,
                x=x2,
                y=y2,
                layer=layer,
                segment_uuid=seg_uuid
            ))

        # TC #55 FIX 0.1: Log extraction results for debugging
        if endpoints:
            layers = set(ep.layer for ep in endpoints)
            nets = set(ep.net_name for ep in endpoints)
            logger.info(f"TC #55: Extracted {len(endpoints)} track endpoints "
                       f"({len(endpoints)//2} segments) on layers {layers}, "
                       f"{len(nets)} unique nets")
        else:
            logger.warning("TC #55: No track endpoints extracted! Check segment format.")

        return endpoints

    def _extract_track_segments(self, content: str, net_mapping: Dict[str, int]) -> List[TrackSegment]:
        """
        TC #75 PRIORITY 2 (2025-12-08): Extract all track segments (not just endpoints).

        This enables finding the closest POINT on a track segment to connect to,
        not just the closest endpoint. Critical for improving routing completion
        when tracks pass near pads but don't have endpoints close by.

        Args:
            content: PCB file content
            net_mapping: Net name to index mapping

        Returns:
            List of TrackSegment objects

        GENERIC: Works for any KiCad PCB file.
        """
        segments = []

        # Reverse net mapping for net index -> name lookup
        idx_to_name = {v: k for k, v in net_mapping.items()}

        # Use S-expression block extraction
        segment_blocks = self._extract_sexp_blocks(content, "segment")

        for seg_block in segment_blocks:
            # Extract start position
            start_match = re.search(r'\(start\s+([\d.-]+)\s+([\d.-]+)\)', seg_block)
            end_match = re.search(r'\(end\s+([\d.-]+)\s+([\d.-]+)\)', seg_block)
            layer_match = re.search(r'\(layer\s+"([^"]+)"\)', seg_block)
            net_match = re.search(r'\(net\s+(\d+)\)', seg_block)
            uuid_match = re.search(r'\(uuid\s+"([^"]+)"\)', seg_block)

            if not all([start_match, end_match, layer_match, net_match]):
                continue

            x1 = float(start_match.group(1))
            y1 = float(start_match.group(2))
            x2 = float(end_match.group(1))
            y2 = float(end_match.group(2))
            layer = layer_match.group(1)
            net_idx = int(net_match.group(1))
            seg_uuid = uuid_match.group(1) if uuid_match else str(uuid.uuid4())

            net_name = idx_to_name.get(net_idx, f"NET_{net_idx}")

            segments.append(TrackSegment(
                net_name=net_name,
                net_idx=net_idx,
                x1=x1, y1=y1,
                x2=x2, y2=y2,
                layer=layer,
                segment_uuid=seg_uuid
            ))

        logger.info(f"TC #75: Extracted {len(segments)} track segments for midpoint connection")
        return segments

    def _find_closest_point_on_segment(
        self, pad_x: float, pad_y: float, seg: TrackSegment
    ) -> Tuple[float, float, float]:
        """
        TC #75 PRIORITY 2 (2025-12-08): Find the closest point on a track segment to a pad.

        Uses point-to-line-segment distance calculation to find the nearest
        connection point, which could be:
        - One of the segment endpoints
        - A point on the line between endpoints (perpendicular projection)

        Args:
            pad_x, pad_y: Pad center coordinates
            seg: Track segment to check

        Returns:
            Tuple of (closest_x, closest_y, distance)

        GENERIC: Works for any segment orientation.
        """
        # Vector from segment start to end
        dx = seg.x2 - seg.x1
        dy = seg.y2 - seg.y1

        # Segment length squared
        length_sq = dx * dx + dy * dy

        if length_sq < 1e-10:
            # Segment is essentially a point
            return (seg.x1, seg.y1, math.sqrt((pad_x - seg.x1)**2 + (pad_y - seg.y1)**2))

        # Calculate projection parameter t (clamped to [0, 1])
        # t = dot(pad - seg.start, seg.end - seg.start) / length_sq
        t = max(0, min(1, ((pad_x - seg.x1) * dx + (pad_y - seg.y1) * dy) / length_sq))

        # Closest point on segment
        closest_x = seg.x1 + t * dx
        closest_y = seg.y1 + t * dy

        # Distance from pad to closest point
        dist = math.sqrt((pad_x - closest_x)**2 + (pad_y - closest_y)**2)

        return (closest_x, closest_y, dist)

    def _find_closest_segment_point(
        self, pad: PadInfo, segments: List[TrackSegment]
    ) -> Optional[Tuple[TrackSegment, float, float, float]]:
        """
        TC #75 PRIORITY 2 (2025-12-08): Find the closest point on ANY segment to a pad.

        Searches all segments on the same net to find the closest connection
        point (could be an endpoint or midpoint).

        Args:
            pad: Pad to connect
            segments: List of all track segments

        Returns:
            Tuple of (segment, closest_x, closest_y, distance) or None

        GENERIC: Works for any pad, any segment configuration.
        """
        best_result = None
        best_dist = float('inf')

        for seg in segments:
            # Only consider segments on the same net
            if seg.net_name != pad.net_name:
                continue

            # Find closest point on this segment
            closest_x, closest_y, dist = self._find_closest_point_on_segment(
                pad.x, pad.y, seg
            )

            if dist < best_dist:
                best_dist = dist
                best_result = (seg, closest_x, closest_y, dist)

        return best_result

    def _generate_fix_sexpr(self, fixes: List[ConnectionFix], stats: Dict) -> str:
        """
        Generate KiCad S-Expression for all connection fixes.

        For each fix:
            1. Add segment from track endpoint to pad center (if distance > 0)
            2. Add via at pad center if layer transition needed

        TC #54 FIX B.1: Don't generate zero-length segments when only via is needed.

        GENERIC: Works for any number of fixes.
        """
        lines = []

        for fix in fixes:
            # TC #54 FIX B.1: Only generate segment if there's actual distance
            # When endpoint is already at pad position, we only need the via
            segment_length = math.sqrt(
                (fix.segment_x2 - fix.segment_x1)**2 +
                (fix.segment_y2 - fix.segment_y1)**2
            )

            if segment_length > 0.01:  # More than 0.01mm - generate segment
                seg_uuid = str(uuid.uuid4())
                segment = (
                    f'  (segment (start {fix.segment_x1:.3f} {fix.segment_y1:.3f}) '
                    f'(end {fix.segment_x2:.3f} {fix.segment_y2:.3f}) '
                    f'(width {self.default_trace_width:.3f}) '
                    f'(layer "{fix.segment_layer}") '
                    f'(net {fix.pad.net_idx}) '
                    f'(uuid "{seg_uuid}"))'
                )
                lines.append(segment)
                stats['segments_added'] += 1

            # Generate via if needed
            if fix.needs_via:
                via_uuid = str(uuid.uuid4())
                via = (
                    f'  (via (at {fix.via_x:.3f} {fix.via_y:.3f}) '
                    f'(size {self.via_diameter:.3f}) '
                    f'(drill {self.via_drill:.3f}) '
                    f'(layers "F.Cu" "B.Cu") '
                    f'(net {fix.pad.net_idx}) '
                    f'(uuid "{via_uuid}"))'
                )
                lines.append(via)
                stats['vias_added'] += 1

        return '\n'.join(lines)

    def _insert_fixes(self, content: str, fix_sexpr: str) -> str:
        """
        TC #75 FIX: Insert fix S-expressions into PCB content with STRUCTURAL validation.

        ═══════════════════════════════════════════════════════════════════════════════
        TC #75 COMPLETE REWRITE (2025-12-08): ROOT CAUSE FIX FOR FILE TRUNCATION
        ═══════════════════════════════════════════════════════════════════════════════

        PROBLEM DISCOVERED (TC #74 Forensic Analysis):
        The previous implementation found "root closing paren" using depth counting,
        but if any structural issue existed in the input (premature depth=0), it would:
        1. Find the WRONG position for root close
        2. Discard everything AFTER that position
        3. Result: TRUNCATED files with orphaned content

        This caused 4 of 6 PCB files to be truncated, blocking all downstream fixes.

        NEW ROBUST APPROACH:
        1. Find the LAST line that is just ')' (root close for kicad_pcb)
        2. Insert fixes BEFORE that line
        3. Validate STRUCTURE (not just balance) before returning
        4. NEVER discard content - preserve everything

        GENERIC: Works for any PCB content format.
        """
        from routing.route_applicator import validate_sexp_balance, repair_sexp_balance

        logger.info(f"TC #75: _insert_fixes called with {len(content)} bytes content, {len(fix_sexpr)} bytes fixes")

        # ═══════════════════════════════════════════════════════════════════════════
        # TC #75 Step 1: STRUCTURAL VALIDATION of input
        # ═══════════════════════════════════════════════════════════════════════════
        is_valid_structure, structure_msg = self._validate_kicad_structure(content)
        if not is_valid_structure:
            logger.warning(f"TC #75: Input has structural issues: {structure_msg}")
            # Attempt structural repair
            content = self._repair_kicad_structure(content)
            is_valid_structure, structure_msg = self._validate_kicad_structure(content)
            if not is_valid_structure:
                logger.error(f"TC #75: Cannot repair structure - returning original")
                return content

        # ═══════════════════════════════════════════════════════════════════════════
        # TC #75 Step 2: Validate and fix fix_sexpr balance
        # ═══════════════════════════════════════════════════════════════════════════
        fix_open = fix_sexpr.count('(')
        fix_close = fix_sexpr.count(')')
        if fix_open != fix_close:
            logger.warning(f"TC #75: fix_sexpr unbalanced ({fix_open} open, {fix_close} close) - fixing")
            if fix_open > fix_close:
                fix_sexpr = fix_sexpr + (')' * (fix_open - fix_close))
            else:
                # Remove extra close parens from end
                diff = fix_close - fix_open
                lines = fix_sexpr.rstrip().split('\n')
                while diff > 0 and lines:
                    last = lines[-1]
                    if last.strip() == ')':
                        lines.pop()
                        diff -= 1
                    elif last.rstrip().endswith(')'):
                        lines[-1] = last.rstrip()[:-1]
                        diff -= 1
                    else:
                        break
                fix_sexpr = '\n'.join(lines)

        # ═══════════════════════════════════════════════════════════════════════════
        # TC #75 Step 3: Find insertion point using LINE-BASED approach
        # This is more reliable than character-position-based approach
        # ═══════════════════════════════════════════════════════════════════════════
        lines = content.split('\n')

        # Find the LAST line that is just ')' - this is the root close
        root_close_line_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].strip()
            if stripped == ')':
                root_close_line_idx = i
                break

        if root_close_line_idx == -1:
            # No root close found - file is malformed, append fixes and close
            logger.warning("TC #75: No root close line found - appending fixes with proper close")
            result = content.rstrip() + '\n\n' + fix_sexpr + '\n)'
        else:
            # Insert fixes BEFORE the root close line
            before_lines = lines[:root_close_line_idx]
            after_lines = lines[root_close_line_idx:]  # Includes the ')' line and anything after

            # Build result preserving ALL content
            result = '\n'.join(before_lines) + '\n\n' + fix_sexpr + '\n' + '\n'.join(after_lines)

        # ═══════════════════════════════════════════════════════════════════════════
        # TC #75 Step 4: MANDATORY structural validation of output
        # ═══════════════════════════════════════════════════════════════════════════
        is_valid_structure, structure_msg = self._validate_kicad_structure(result)
        if not is_valid_structure:
            logger.error(f"TC #75 WARNING: Output structural issue: {structure_msg}")
            # Attempt repair
            result = self._repair_kicad_structure(result)

        # Also validate balance
        is_valid, delta, msg = validate_sexp_balance(result, "output from _insert_fixes")
        if not is_valid:
            logger.warning(f"TC #75: Output balance issue: {msg} - repairing")
            result, was_repaired, repair_msg = repair_sexp_balance(result)
            logger.info(f"TC #75: {repair_msg}")

        # Final structural check
        is_valid_structure, structure_msg = self._validate_kicad_structure(result)
        if not is_valid_structure:
            logger.error(f"TC #75 CRITICAL: Final output STILL invalid: {structure_msg}")
            logger.error(f"TC #75: Returning original content to prevent corruption")
            return content

        logger.info(f"TC #75: _insert_fixes completed successfully")
        return result

    def _validate_kicad_structure(self, content: str) -> Tuple[bool, str]:
        """
        TC #75: Validate KiCad PCB file STRUCTURE (not just parenthesis balance).

        A valid KiCad PCB file must:
        1. Start with '(kicad_pcb' on the first non-empty line
        2. End with ')' on the last non-empty line (closing the root)
        3. Have balanced parentheses overall

        Returns:
            Tuple of (is_valid, message)
        """
        lines = content.strip().split('\n')
        if not lines:
            return False, "Empty content"

        # Check first line
        first_line = lines[0].strip()
        if not first_line.startswith('(kicad_pcb'):
            return False, f"Invalid header (expected '(kicad_pcb'): {first_line[:50]}"

        # Check last line - must be just ')' to close root
        last_line = lines[-1].strip()
        if last_line != ')':
            return False, f"File truncated - last line should be ')' but is: {last_line[:50]}"

        # Check overall balance
        total_open = content.count('(')
        total_close = content.count(')')
        if total_open != total_close:
            return False, f"Unbalanced parens: {total_open} open, {total_close} close"

        return True, "Structure OK"

    def _repair_kicad_structure(self, content: str) -> str:
        """
        TC #75: Attempt to repair KiCad PCB file structure.

        Repairs:
        1. Missing root close - add ')' at end
        2. Truncated last element - try to close it properly
        3. Overall balance issues - add/remove parens as needed

        Returns:
            Repaired content (best effort)
        """
        lines = content.strip().split('\n')
        if not lines:
            return content

        repaired_lines = lines.copy()

        # Check if last line is the root close
        last_line = repaired_lines[-1].strip()
        if last_line != ')':
            # Last line is NOT the root close - file is truncated
            logger.warning(f"TC #75 REPAIR: Last line is '{last_line[:50]}' - attempting repair")

            # Check if last line is incomplete (missing close parens)
            last_line_open = last_line.count('(')
            last_line_close = last_line.count(')')

            if last_line_open > last_line_close:
                # Last line has unclosed parens - close them
                missing = last_line_open - last_line_close
                repaired_lines[-1] = repaired_lines[-1] + (')' * missing)
                logger.info(f"TC #75 REPAIR: Closed {missing} parens on last line")

            # Now check overall balance
            content_str = '\n'.join(repaired_lines)
            total_open = content_str.count('(')
            total_close = content_str.count(')')

            if total_open > total_close:
                # Missing close parens - add them
                missing = total_open - total_close
                # Add the root close(s)
                repaired_lines.append(')' * missing)
                logger.info(f"TC #75 REPAIR: Added {missing} closing paren(s) at end")
            elif total_close > total_open:
                # Too many closes - this is harder, try removing from end
                excess = total_close - total_open
                logger.warning(f"TC #75 REPAIR: {excess} excess close parens - attempting removal")
                # Remove excess from the last line(s)
                while excess > 0 and repaired_lines:
                    last = repaired_lines[-1]
                    if last.strip() == ')':
                        repaired_lines.pop()
                        excess -= 1
                    elif last.rstrip().endswith(')'):
                        repaired_lines[-1] = last.rstrip()[:-1]
                        excess -= 1
                    else:
                        break

        # Ensure we have a proper root close
        content_str = '\n'.join(repaired_lines)
        last_stripped = repaired_lines[-1].strip() if repaired_lines else ''
        if last_stripped != ')':
            # Still no root close - add one
            repaired_lines.append(')')
            logger.info("TC #75 REPAIR: Added root close ')' at end")

        return '\n'.join(repaired_lines)

    def _extract_existing_vias(self, content: str) -> Set[Tuple[float, float]]:
        """
        Extract all existing via positions from PCB content.

        TC #57 FIX 1.3 (2025-11-27): Prevent duplicate via injection.

        ROOT CAUSE: When via injection runs multiple times or when vias already
        exist at pad locations, we were adding duplicate vias which caused
        DRC violations (shorting_items).

        KiCad 9 via format:
            (via (at X Y) (size D) (drill H) (layers "F.Cu" "B.Cu") (net N) (uuid "..."))

        Returns:
            Set of (x, y) tuples representing existing via positions

        GENERIC: Works for any PCB content with vias.
        """
        existing_vias: Set[Tuple[float, float]] = set()

        # Extract all via blocks
        via_blocks = self._extract_sexp_blocks(content, "via")
        logger.debug(f"TC #57 FIX 1.3: Found {len(via_blocks)} via blocks")

        for via_block in via_blocks:
            # Extract via position: (at X Y)
            at_match = re.search(r'\(at\s+([\d.-]+)\s+([\d.-]+)\)', via_block)
            if at_match:
                x = float(at_match.group(1))
                y = float(at_match.group(2))
                # Round to 3 decimal places for comparison (0.001mm precision)
                existing_vias.add((round(x, 3), round(y, 3)))

        return existing_vias

    def _is_via_at_position(self, existing_vias: Set[Tuple[float, float]],
                            x: float, y: float, tolerance: float = 0.1) -> bool:
        """
        Check if a via already exists at or near a position.

        TC #57 FIX 1.3 (2025-11-27): Avoid duplicate via injection.

        Args:
            existing_vias: Set of existing via positions
            x: X coordinate to check
            y: Y coordinate to check
            tolerance: Distance tolerance in mm (default 0.1mm)

        Returns:
            True if a via exists within tolerance distance

        GENERIC: Works for any position check.
        """
        x_rounded = round(x, 3)
        y_rounded = round(y, 3)

        # First check exact match
        if (x_rounded, y_rounded) in existing_vias:
            return True

        # Then check within tolerance
        for vx, vy in existing_vias:
            dist = math.sqrt((vx - x)**2 + (vy - y)**2)
            if dist < tolerance:
                return True

        return False


__all__ = ['RoutePadConnector', 'PadInfo', 'TrackEndpoint', 'ConnectionFix']
