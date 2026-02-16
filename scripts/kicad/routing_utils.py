# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Routing Utilities - Helper functions for routing-aware logic
============================================================

PHASE 2 & 3 implementations from KICAD_CONVERTER_FIX_PLAN.md

Author: Claude Code
Date: 2025-11-17
Version: 2.0.0
"""

import math
from typing import Tuple, Dict, Any
from pathlib import Path


def detect_routing_state(pcb_file: Path) -> str:
    """
    Classify routing state to guide fixer selection.

    PHASE 2 TASK 2.2: Routing State Detection

    Returns:
        'no_routing': 0 traces (SES import failed or Freerouting failed)
        'partial_routing': Some traces but incomplete connections
        'full_routing': All connections complete (DRC violations only)
    """
    # Read PCB file and count segments
    with open(pcb_file, 'r') as f:
        pcb_content = f.read()

    segment_count = pcb_content.count('(segment')

    if segment_count == 0:
        return 'no_routing'

    # Check for ratsnest (unrouted connections)
    # If PCB has segments but also has unconnected pads, it's partial
    # This is a simplified check - full check would parse DRC results
    unconnected_count = pcb_content.count('unconnected')

    if unconnected_count > 0:
        return 'partial_routing'
    else:
        return 'full_routing'


def classify_circuit_complexity(component_count: int, net_count: int, pad_count: int) -> str:
    """
    Classify circuit complexity to guide board sizing.

    PHASE 3 TASK 3.3: Complexity Detection

    Returns:
        'simple': <10 components, <20 nets
        'medium': 10-30 components, 20-50 nets
        'complex': >30 components OR >50 nets
    """
    # Check for complex components (high pin count)
    avg_pins_per_component = pad_count / component_count if component_count > 0 else 0
    has_complex_components = avg_pins_per_component > 20

    if component_count < 10 and net_count < 20 and not has_complex_components:
        return 'simple'
    elif component_count < 30 and net_count < 50:
        return 'medium'
    else:
        return 'complex'


def calculate_board_size_with_routing_overhead(
    component_count: int,
    net_count: int,
    pad_count: int,
    base_width: float,
    base_height: float,
    components: list = None
) -> Tuple[float, float]:
    """
    Calculate optimal board size based on ACTUAL component dimensions and routing complexity.

    ENHANCED (2025-11-17 - Forensic Fix #4): Uses actual footprint bounding boxes
    instead of generic formulas. Fixes board sizing being 10-20x too large.

    Factors considered:
    - Actual component footprint areas (not generic estimates)
    - Realistic packing efficiency (60-70%)
    - Number of nets (routing channels needed)
    - Pin density (routing congestion)

    Args:
        component_count: Number of components
        net_count: Number of nets
        pad_count: Total number of pads
        base_width: Legacy parameter (now calculated from components)
        base_height: Legacy parameter (now calculated from components)
        components: List of component dicts with 'footprint' key (REQUIRED for accuracy)

    Returns:
        (width_mm, height_mm) - Optimal board dimensions
    """
    # FIXED (2025-11-17): Use relative import (routing_utils.py is IN scripts/kicad/)
    from .footprint_dimensions_db import get_footprint_bbox

    # NEW: Calculate from actual component footprints if provided
    if components:
        # Calculate total actual component area
        total_component_area = 0.0
        for comp in components:
            footprint = comp.get('footprint', '')
            if footprint:
                width, height = get_footprint_bbox(footprint)
                total_component_area += width * height

        # Use realistic packing efficiency (industry standard: 60-70% for manual placement)
        packing_efficiency = 0.65  # 65% efficiency

        # Base area needed for components
        base_component_area = total_component_area / packing_efficiency

    else:
        # FALLBACK: Use legacy generic calculation if components not provided
        base_component_area = base_width * base_height

    # Step 1: Apply realistic routing overhead based on net count
    # FIXED (2025-11-17): Reduced to realistic values based on professional PCB analysis
    if net_count < 10:
        routing_factor = 1.2  # Simple circuits: 20% overhead for routing
    elif net_count < 30:
        routing_factor = 1.4  # Medium circuits: 40% overhead
    elif net_count < 50:
        routing_factor = 1.6  # Complex circuits: 60% overhead
    else:
        routing_factor = 1.8  # Very complex: 80% overhead

    # Step 2: Adjust for pin density (more pins = more routing congestion)
    if base_component_area > 0:
        pin_density = pad_count / (base_component_area / 100)  # pads per cm²

        if pin_density > 50:  # Very dense (e.g., QFP/QFN ICs)
            routing_factor *= 1.15  # Add 15% for high-density routing
        elif pin_density > 100:  # Extremely dense
            routing_factor *= 1.25  # Add 25% for very high-density

    # Step 3: Calculate required area with routing
    required_area = base_component_area * routing_factor

    # Step 4: Calculate board dimensions (aim for reasonable aspect ratio)
    # Prefer aspect ratios between 1:1 and 2:1 for manufacturability
    aspect_ratio = 1.5  # 3:2 aspect ratio (common for PCBs)
    width = math.sqrt(required_area * aspect_ratio)
    height = math.sqrt(required_area / aspect_ratio)

    # Step 5: Add modest margin (5mm all sides - enough for mounting holes)
    margin = 5  # mm (was 20mm - way too much!)
    width += 2 * margin
    height += 2 * margin

    # Step 6: Round to standard sizes (5mm increments for practicality)
    width = math.ceil(width / 5) * 5
    height = math.ceil(height / 5) * 5

    # Step 7: Enforce REALISTIC minimum sizes
    width = max(width, 30)  # Minimum 30mm (was 60mm - too large!)
    height = max(height, 30)  # Minimum 30mm

    # Step 8: Enforce REALISTIC maximum sizes (prevent runaway board sizes)
    width = min(width, 150)  # Maximum 150mm for typical circuits
    height = min(height, 150)  # Maximum 150mm

    return (width, height)


def calculate_routing_completion_percentage(routing_stats: Dict[str, Any]) -> float:
    """
    Calculate routing completion percentage from Freerouting stats.

    PHASE 2 TASK 2.3: Routing-Aware Validation

    Returns:
        Completion percentage (0-100)
    """
    if not routing_stats:
        return 0.0

    total_connections = routing_stats.get('connections', {}).get('maximum_count', 0)
    incomplete = routing_stats.get('connections', {}).get('incomplete_count', 0)

    if total_connections == 0:
        return 0.0

    completion_pct = ((total_connections - incomplete) / total_connections * 100)
    return completion_pct


# =============================================================================
# TC #69 FIX (2025-12-07): ROUTING COMPLETENESS VALIDATION
# =============================================================================
# The forensic analysis showed that routing fails silently:
# - Freerouting times out on complex circuits (52+ nets)
# - Manhattan router produces partial routes
# - No validation to catch incomplete routing
#
# Solution: Add explicit routing completeness validation functions
# =============================================================================


class RoutingIncompleteError(Exception):
    """
    TC #69: Exception raised when routing is incomplete.

    GENERIC: Raised for ANY circuit that fails routing completeness threshold.
    """
    def __init__(self, message: str, routed_nets: int, total_nets: int,
                 completion_percent: float, unrouted_nets: list = None):
        super().__init__(message)
        self.routed_nets = routed_nets
        self.total_nets = total_nets
        self.completion_percent = completion_percent
        self.unrouted_nets = unrouted_nets or []


def count_nets_in_pcb(pcb_file: Path) -> Dict[str, Any]:
    """
    TC #69 FIX: Count total nets and analyze routing state in PCB file.

    GENERIC: Works for ANY PCB file regardless of circuit complexity.

    Args:
        pcb_file: Path to .kicad_pcb file

    Returns:
        Dict with:
        - total_nets: Total number of nets defined
        - net_names: List of net names
        - segment_count: Number of routing segments
        - via_count: Number of vias
        - nets_with_segments: Set of nets that have at least one segment
        - nets_without_segments: Set of nets that have NO segments
    """
    import re

    result = {
        'total_nets': 0,
        'net_names': [],
        'segment_count': 0,
        'via_count': 0,
        'nets_with_segments': set(),
        'nets_without_segments': set(),
    }

    if not pcb_file.exists():
        return result

    try:
        with open(pcb_file, 'r', errors='ignore') as f:
            pcb_content = f.read()
    except Exception:
        return result

    # Count segments and vias
    result['segment_count'] = pcb_content.count('(segment')
    result['via_count'] = pcb_content.count('(via (at')

    # Extract all net definitions: (net 1 "VCC") or (net 0 "")
    net_pattern = r'\(net\s+(\d+)\s+"([^"]*)"\)'
    net_matches = re.findall(net_pattern, pcb_content)

    for net_id, net_name in net_matches:
        if net_name and net_name not in ['', 'GND']:  # Skip empty and GND (usually connected)
            if net_name not in result['net_names']:
                result['net_names'].append(net_name)

    result['total_nets'] = len(result['net_names'])

    # Find which nets have segments
    # Segments have format: (segment ... (net "NetName") ...)
    segment_net_pattern = r'\(segment[^)]*\(net\s+"([^"]+)"\)'
    segment_nets = set(re.findall(segment_net_pattern, pcb_content))

    # Also check for alternative net reference format in segments
    segment_net_id_pattern = r'\(segment[^)]*\(net\s+(\d+)\)'
    segment_net_ids = set(re.findall(segment_net_id_pattern, pcb_content))

    # Map net IDs to names
    net_id_to_name = {}
    for net_id, net_name in net_matches:
        net_id_to_name[net_id] = net_name

    for net_id in segment_net_ids:
        if net_id in net_id_to_name:
            segment_nets.add(net_id_to_name[net_id])

    result['nets_with_segments'] = segment_nets
    result['nets_without_segments'] = set(result['net_names']) - segment_nets

    return result


def validate_routing_completeness(pcb_file: Path,
                                   threshold_percent: float = 95.0,
                                   raise_on_failure: bool = True) -> Dict[str, Any]:
    """
    TC #69 FIX: Validate that routing is sufficiently complete.

    CRITICAL: This function should be called AFTER routing completes but BEFORE
    running DRC. If routing is incomplete, DRC will report many unconnected pads
    but we should fail earlier with a more actionable message.

    GENERIC: Works for ANY circuit type with configurable threshold.

    Args:
        pcb_file: Path to .kicad_pcb file
        threshold_percent: Minimum acceptable routing completion (default 95%)
        raise_on_failure: If True, raise RoutingIncompleteError when below threshold

    Returns:
        Dict with:
        - passed: True if above threshold
        - completion_percent: Percentage of nets routed
        - routed_nets: Number of nets with routing
        - total_nets: Total number of nets
        - unrouted_nets: List of net names without routing
        - message: Human-readable status message

    Raises:
        RoutingIncompleteError: If raise_on_failure=True and below threshold
    """
    net_analysis = count_nets_in_pcb(pcb_file)

    total_nets = net_analysis['total_nets']
    routed_nets = len(net_analysis['nets_with_segments'])
    unrouted_nets = list(net_analysis['nets_without_segments'])

    # Calculate completion percentage
    if total_nets == 0:
        completion_percent = 100.0  # No nets = trivially complete
    else:
        completion_percent = (routed_nets / total_nets) * 100.0

    passed = completion_percent >= threshold_percent

    # Build result
    result = {
        'passed': passed,
        'completion_percent': round(completion_percent, 1),
        'routed_nets': routed_nets,
        'total_nets': total_nets,
        'unrouted_nets': unrouted_nets[:20],  # Limit to first 20 for readability
        'segment_count': net_analysis['segment_count'],
        'via_count': net_analysis['via_count'],
        'message': ''
    }

    if passed:
        result['message'] = (
            f"Routing COMPLETE: {routed_nets}/{total_nets} nets routed "
            f"({completion_percent:.1f}%), {net_analysis['segment_count']} segments, "
            f"{net_analysis['via_count']} vias"
        )
    else:
        result['message'] = (
            f"Routing INCOMPLETE: Only {routed_nets}/{total_nets} nets routed "
            f"({completion_percent:.1f}% < {threshold_percent}% threshold). "
            f"Unrouted: {unrouted_nets[:5]}{'...' if len(unrouted_nets) > 5 else ''}"
        )

        if raise_on_failure:
            raise RoutingIncompleteError(
                result['message'],
                routed_nets=routed_nets,
                total_nets=total_nets,
                completion_percent=completion_percent,
                unrouted_nets=unrouted_nets
            )

    return result


def get_routing_summary(pcb_file: Path) -> str:
    """
    TC #69 FIX: Get a human-readable routing summary for logging.

    GENERIC: Works for ANY PCB file.

    Args:
        pcb_file: Path to .kicad_pcb file

    Returns:
        Human-readable summary string
    """
    net_analysis = count_nets_in_pcb(pcb_file)

    total = net_analysis['total_nets']
    routed = len(net_analysis['nets_with_segments'])
    segments = net_analysis['segment_count']
    vias = net_analysis['via_count']

    if total == 0:
        return "No nets defined"

    percent = (routed / total) * 100.0

    return (
        f"Routing: {routed}/{total} nets ({percent:.0f}%), "
        f"{segments} segments, {vias} vias"
    )


# =============================================================================
# TC #69 FIX (2025-12-07): TEWL - TOTAL ESTIMATED WIRE LENGTH METRIC
# =============================================================================
# TEWL (Total Estimated Wire Length) is a key metric for:
# - Predicting routing complexity BEFORE routing
# - Evaluating placement quality (lower TEWL = better placement)
# - Guiding board sizing decisions
# - Comparing different placement strategies
#
# The metric estimates total wire length needed to connect all nets based on:
# - Component placement positions
# - Net connectivity (which pads connect to which nets)
# - Manhattan distance approximation (L1 norm for PCB routing)
#
# GENERIC: Works for ANY circuit type by analyzing actual placement data.
# =============================================================================


def calculate_tewl(component_positions: Dict[str, Tuple[float, float]],
                   net_connections: Dict[str, list],
                   use_manhattan: bool = True) -> Dict[str, Any]:
    """
    TC #69 FIX (2025-12-07): Calculate Total Estimated Wire Length (TEWL) metric.

    TEWL is a placement quality metric that estimates the total routing length
    needed to connect all nets. Lower TEWL indicates better placement.

    GENERIC: Works for ANY circuit by analyzing actual component positions
    and net connectivity, without assuming specific circuit structure.

    Args:
        component_positions: Dict mapping component ref to (x, y) position
            Example: {'R1': (10.0, 20.0), 'C1': (15.0, 25.0), ...}

        net_connections: Dict mapping net name to list of (component_ref, pin)
            Example: {'VCC': [('R1', '1'), ('C1', '1')], 'GND': [...]}

        use_manhattan: If True, use Manhattan distance (L1 norm), which is
            more accurate for PCB routing. If False, use Euclidean distance.

    Returns:
        Dict with:
        - total_tewl: Total estimated wire length in mm
        - per_net_tewl: Dict mapping net name to its TEWL contribution
        - net_count: Number of nets analyzed
        - avg_tewl_per_net: Average TEWL per net
        - max_net: (net_name, length) of the longest net
        - complexity_rating: 'low', 'medium', 'high', 'very_high'
        - routing_difficulty: Estimated routing difficulty score (0-100)
    """
    result = {
        'total_tewl': 0.0,
        'per_net_tewl': {},
        'net_count': 0,
        'avg_tewl_per_net': 0.0,
        'max_net': ('', 0.0),
        'complexity_rating': 'unknown',
        'routing_difficulty': 0.0
    }

    if not component_positions or not net_connections:
        return result

    per_net_tewl = {}
    max_net_length = 0.0
    max_net_name = ''

    for net_name, connections in net_connections.items():
        if len(connections) < 2:
            # Single-pin nets don't need routing
            continue

        # Get positions of all pins in this net
        pin_positions = []
        for comp_ref, pin in connections:
            if comp_ref in component_positions:
                # Use component center position (simplified - real impl would use pin offset)
                pin_positions.append(component_positions[comp_ref])

        if len(pin_positions) < 2:
            continue

        # Calculate TEWL for this net using MST approximation
        # For simplicity, use half-perimeter of bounding box as minimum spanning tree estimate
        # This is a well-known lower bound for MST in PCB routing
        net_tewl = _calculate_net_tewl(pin_positions, use_manhattan)

        per_net_tewl[net_name] = net_tewl

        if net_tewl > max_net_length:
            max_net_length = net_tewl
            max_net_name = net_name

    # Calculate totals
    total_tewl = sum(per_net_tewl.values())
    net_count = len(per_net_tewl)

    result['total_tewl'] = round(total_tewl, 2)
    result['per_net_tewl'] = {k: round(v, 2) for k, v in per_net_tewl.items()}
    result['net_count'] = net_count
    result['avg_tewl_per_net'] = round(total_tewl / net_count, 2) if net_count > 0 else 0.0
    result['max_net'] = (max_net_name, round(max_net_length, 2))

    # Classify complexity based on TEWL thresholds
    result['complexity_rating'] = _classify_tewl_complexity(total_tewl, net_count)

    # Calculate routing difficulty score (0-100)
    result['routing_difficulty'] = _calculate_routing_difficulty(
        total_tewl, net_count, max_net_length
    )

    return result


def _calculate_net_tewl(positions: list, use_manhattan: bool = True) -> float:
    """
    TC #69 FIX: Calculate estimated wire length for a single net.

    Uses the half-perimeter bounding box method as a lower bound for MST.
    This is computationally efficient and provides a good estimate for
    placement optimization.

    GENERIC: Works for any number of pin positions.

    Args:
        positions: List of (x, y) tuples for pin positions
        use_manhattan: If True, use Manhattan distance

    Returns:
        Estimated wire length for this net
    """
    if len(positions) < 2:
        return 0.0

    # For 2-pin nets, just calculate direct distance
    if len(positions) == 2:
        x1, y1 = positions[0]
        x2, y2 = positions[1]
        if use_manhattan:
            return abs(x2 - x1) + abs(y2 - y1)
        else:
            return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

    # For multi-pin nets, use bounding box half-perimeter + MST approximation
    # The half-perimeter is a lower bound, and we add a factor for additional
    # connections needed in a spanning tree

    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]

    # Bounding box
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    half_perimeter = (max_x - min_x) + (max_y - min_y)

    # For N pins, MST has N-1 edges. Half-perimeter gives minimum for 2 pins.
    # Add a factor for additional connections (empirical: ~1.2x per additional pin)
    mst_factor = 1.0 + (len(positions) - 2) * 0.2

    return half_perimeter * mst_factor


def _classify_tewl_complexity(total_tewl: float, net_count: int) -> str:
    """
    TC #69 FIX: Classify TEWL complexity rating.

    GENERIC: Based on empirical thresholds from various circuit types.
    """
    if net_count == 0:
        return 'unknown'

    # Average TEWL per net (mm) thresholds
    avg_tewl = total_tewl / net_count

    if avg_tewl < 10:
        return 'low'  # Short nets, easy routing
    elif avg_tewl < 25:
        return 'medium'  # Moderate nets
    elif avg_tewl < 50:
        return 'high'  # Long nets, harder routing
    else:
        return 'very_high'  # Very long nets, likely needs careful placement


def _calculate_routing_difficulty(total_tewl: float, net_count: int,
                                   max_net_length: float) -> float:
    """
    TC #69 FIX: Calculate routing difficulty score (0-100).

    GENERIC: Combines multiple factors to estimate how hard routing will be.

    Factors:
    - Total wire length (more length = harder)
    - Net count (more nets = more congestion potential)
    - Max single net length (very long nets are problematic)
    """
    if net_count == 0:
        return 0.0

    # Base difficulty from total TEWL (normalized to 0-50 scale)
    tewl_score = min(50, total_tewl / 100)

    # Net count contribution (0-25 scale)
    net_score = min(25, net_count * 0.5)

    # Max net length contribution (0-25 scale)
    # Very long nets (>50mm) are problematic
    max_net_score = min(25, max_net_length / 2)

    # Combine scores
    difficulty = tewl_score + net_score + max_net_score

    return min(100, round(difficulty, 1))


def estimate_board_size_from_tewl(tewl_result: Dict[str, Any],
                                   component_count: int) -> Tuple[float, float]:
    """
    TC #69 FIX: Estimate optimal board size based on TEWL metric.

    GENERIC: Uses TEWL to predict required routing area, then calculates
    board dimensions that will accommodate routing without congestion.

    Args:
        tewl_result: Result from calculate_tewl()
        component_count: Number of components

    Returns:
        (width_mm, height_mm) - Recommended board dimensions
    """
    total_tewl = tewl_result.get('total_tewl', 0)
    net_count = tewl_result.get('net_count', 0)
    complexity = tewl_result.get('complexity_rating', 'medium')

    # Base area estimation from TEWL
    # Empirical: routing area ≈ TEWL * trace_width * congestion_factor
    trace_width = 0.25  # mm (standard signal trace)
    congestion_factor = 2.0  # Allow for routing channels and via clearances

    if complexity == 'low':
        congestion_factor = 1.5
    elif complexity == 'high':
        congestion_factor = 2.5
    elif complexity == 'very_high':
        congestion_factor = 3.0

    routing_area = total_tewl * trace_width * congestion_factor

    # Add component footprint area (rough estimate: 25mm² per component average)
    component_area = component_count * 25

    # Total area needed
    total_area = routing_area + component_area

    # Add margin (20% for edges and mounting)
    total_area *= 1.2

    # Calculate dimensions with 1.5:1 aspect ratio
    width = math.sqrt(total_area * 1.5)
    height = math.sqrt(total_area / 1.5)

    # Round to 5mm increments
    width = math.ceil(width / 5) * 5
    height = math.ceil(height / 5) * 5

    # Enforce reasonable minimums and maximums
    width = max(30, min(200, width))
    height = max(30, min(200, height))

    return (width, height)


def compare_placements_by_tewl(placements: list,
                                net_connections: Dict[str, list]) -> Dict[str, Any]:
    """
    TC #69 FIX: Compare multiple placement options using TEWL metric.

    GENERIC: Evaluates any number of placement alternatives and ranks them
    by routing efficiency.

    Args:
        placements: List of placement dicts, each mapping component to (x, y)
        net_connections: Net connectivity (same for all placements)

    Returns:
        Dict with:
        - rankings: List of (index, tewl, improvement_pct) tuples, sorted by TEWL
        - best_placement_index: Index of best (lowest TEWL) placement
        - worst_placement_index: Index of worst (highest TEWL) placement
        - tewl_range: (min_tewl, max_tewl)
        - improvement_potential: Percentage improvement from worst to best
    """
    if not placements:
        return {'rankings': [], 'best_placement_index': -1}

    # Calculate TEWL for each placement
    tewl_results = []
    for i, placement in enumerate(placements):
        tewl = calculate_tewl(placement, net_connections)
        tewl_results.append((i, tewl['total_tewl']))

    # Sort by TEWL (lower is better)
    tewl_results.sort(key=lambda x: x[1])

    best_tewl = tewl_results[0][1]
    worst_tewl = tewl_results[-1][1]

    # Calculate improvement percentages relative to worst
    rankings = []
    for idx, tewl in tewl_results:
        if worst_tewl > 0:
            improvement_pct = ((worst_tewl - tewl) / worst_tewl) * 100
        else:
            improvement_pct = 0.0
        rankings.append((idx, tewl, round(improvement_pct, 1)))

    improvement_potential = 0.0
    if worst_tewl > 0:
        improvement_potential = ((worst_tewl - best_tewl) / worst_tewl) * 100

    return {
        'rankings': rankings,
        'best_placement_index': tewl_results[0][0],
        'worst_placement_index': tewl_results[-1][0],
        'tewl_range': (round(best_tewl, 2), round(worst_tewl, 2)),
        'improvement_potential': round(improvement_potential, 1)
    }


def get_tewl_summary(tewl_result: Dict[str, Any]) -> str:
    """
    TC #69 FIX: Get a human-readable TEWL summary for logging.

    GENERIC: Works for any TEWL calculation result.

    Args:
        tewl_result: Result from calculate_tewl()

    Returns:
        Human-readable summary string
    """
    total = tewl_result.get('total_tewl', 0)
    net_count = tewl_result.get('net_count', 0)
    complexity = tewl_result.get('complexity_rating', 'unknown')
    difficulty = tewl_result.get('routing_difficulty', 0)
    max_net = tewl_result.get('max_net', ('', 0))

    if net_count == 0:
        return "TEWL: No nets to analyze"

    return (
        f"TEWL: {total:.1f}mm total, {net_count} nets, "
        f"complexity={complexity}, difficulty={difficulty:.0f}/100, "
        f"longest net: {max_net[0]} ({max_net[1]:.1f}mm)"
    )


__all__ = [
    'detect_routing_state',
    'classify_circuit_complexity',
    'calculate_board_size_with_routing_overhead',
    'calculate_routing_completion_percentage',
    # TC #69 additions - Routing Completeness
    'RoutingIncompleteError',
    'count_nets_in_pcb',
    'validate_routing_completeness',
    'get_routing_summary',
    # TC #69 additions - TEWL Metric
    'calculate_tewl',
    'estimate_board_size_from_tewl',
    'compare_placements_by_tewl',
    'get_tewl_summary',
]
