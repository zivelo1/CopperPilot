#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
GENERIC Placement Optimizer - Professional critical-first component placement

This module implements professional PCB placement strategy:
1. Connectors FIRST (board edges, fixed positions)
2. ICs SECOND (central locations, optimal for routing)
3. Passives LAST (around ICs they support)

GENERIC: Works for ANY circuit type by analyzing component priorities and connectivity.

Author: Claude Code / CopperPilot AI System
Date: 2025-11-18
Version: 1.0 - Phase 3 implementation
"""

from __future__ import annotations
import logging
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

# TC #38 (2025-11-23): Import central manufacturing configuration
# SINGLE SOURCE OF TRUTH for all manufacturing parameters
from kicad.manufacturing_config import MANUFACTURING_CONFIG

logger = logging.getLogger(__name__)


class PlacementOptimizer:
    """
    GENERIC placement optimizer using critical-first strategy.

    Places components in priority order for professional PCB layout:
    - Connectors at board edges
    - ICs in central areas
    - Passives clustered around ICs they support
    """

    def __init__(self, board_width: float, board_height: float):
        """
        Initialize placement optimizer.

        Args:
            board_width: Board width in mm
            board_height: Board height in mm
        """
        self.board_width = board_width
        self.board_height = board_height

        # TC #38 (2025-11-23): Use central manufacturing configuration
        # SINGLE SOURCE OF TRUTH - no more hardcoded values
        self.margin = MANUFACTURING_CONFIG.BOARD_EDGE_MARGIN
        self.min_component_clearance = MANUFACTURING_CONFIG.MIN_COMPONENT_CLEARANCE
        self.min_pad_clearance = MANUFACTURING_CONFIG.MIN_PAD_CLEARANCE
        self.edge_clearance = MANUFACTURING_CONFIG.COPPER_EDGE_CLEARANCE

        # Component priority levels (lower = place first)
        self.priority_map = {
            'connector': 1,
            'header': 1,
            'terminal': 1,
            'jack': 1,
            'socket': 1,
            'mcu': 2,
            'cpu': 2,
            'fpga': 2,
            'ic': 3,
            'opamp': 3,
            'regulator': 3,
            'resistor': 4,
            'capacitor': 4,
            'inductor': 4,
            'led': 4,
            'diode': 4,
            'crystal': 3,
        }

    def optimize_placement(self, groups: Dict[str, List[Dict]],
                          footprint_db=None) -> List[Dict]:
        """
        Optimize component placement using critical-first strategy (GENERIC).

        Args:
            groups: Component groups from ComponentGrouper
            footprint_db: Optional footprint database for dimension lookup

        Returns:
            List of components with optimized 'brd_x', 'brd_y', 'rotation' fields
        """
        logger.info(f"🎯 Optimizing placement with critical-first strategy...")

        # STEP 1: Flatten groups and assign priorities
        all_components = []
        for group_name, group_comps in groups.items():
            for comp in group_comps:
                comp['_group'] = group_name
                comp['_priority'] = self._get_component_priority(comp)
                all_components.append(comp)

        # STEP 2: Sort by priority (critical components first)
        sorted_components = sorted(all_components, key=lambda c: c.get('_priority', 999))

        # STEP 3: Enrich with dimensions
        if footprint_db:
            for comp in sorted_components:
                footprint = comp.get('footprint', '')
                pin_count = len(comp.get('pins', []))
                width, height = footprint_db.get_dimensions(footprint, pin_count)
                comp['_width'] = width
                comp['_height'] = height
        else:
            # Fallback dimensions
            for comp in sorted_components:
                comp['_width'] = 10.0
                comp['_height'] = 10.0

        # STEP 4: Place components in priority order
        placed_components = self._place_in_priority_order(sorted_components)

        logger.info(f"✅ Optimized placement: {len(placed_components)} components")

        return placed_components

    def _get_component_priority(self, comp: Dict) -> int:
        """
        Get placement priority for component (GENERIC).

        Args:
            comp: Component dictionary

        Returns:
            Priority value (lower = place first)
        """
        ref = comp.get('ref', '').lower()
        comp_type = comp.get('type', '').lower()
        footprint = comp.get('footprint', '').lower()

        # Check reference designator prefix
        for keyword, priority in self.priority_map.items():
            if keyword in ref or keyword in comp_type or keyword in footprint:
                return priority

        # Default priority for unknown components
        return 5

    def _place_in_priority_order(self, components: List[Dict]) -> List[Dict]:
        """
        Place components in priority order (GENERIC).

        Strategy:
        - Priority 1 (connectors): Board edges
        - Priority 2 (MCUs/critical ICs): Central area
        - Priority 3 (supporting ICs): Around MCUs
        - Priority 4+ (passives): Clustered near ICs they support

        Args:
            components: Sorted list of components with priorities

        Returns:
            Components with 'brd_x', 'brd_y', 'rotation' assigned
        """
        placed = []
        occupied_regions = []

        # Define placement zones
        # Edge zone: for connectors (priority 1)
        edge_positions = self._generate_edge_positions()
        edge_index = 0

        # Central zone: for critical ICs (priority 2-3)
        central_x = self.board_width / 2
        central_y = self.board_height / 2

        # Grid tracking for other components
        grid_x = self.margin
        grid_y = self.margin
        row_height = 0

        for comp in components:
            priority = comp.get('_priority', 5)
            width = comp.get('_width', 10.0)
            height = comp.get('_height', 10.0)

            # TC #38: Use central config clearance to match pre-routing validation
            x = None
            y = None
            clearance = self.min_component_clearance  # From MANUFACTURING_CONFIG

            if priority == 1:
                # Connectors: try edge positions, validate each for collisions
                placed_successfully = False
                while edge_index < len(edge_positions) and not placed_successfully:
                    test_x, test_y = edge_positions[edge_index]
                    edge_index += 1

                    # Validate this edge position
                    if not self._collides(test_x, test_y, width, height, occupied_regions, clearance):
                        x, y = test_x, test_y
                        placed_successfully = True

                if not placed_successfully:
                    # All edge positions occupied, fallback to grid
                    x, y = self._find_next_grid_position(grid_x, grid_y, width, height,
                                                         occupied_regions)
                    # TC #38: Update grid position after fallback placement
                    grid_x = x + width + self.min_component_clearance
                    row_height = max(row_height, height)
                    if grid_x + width > self.board_width - self.margin:
                        grid_x = self.margin
                        grid_y += row_height + self.min_component_clearance
                        row_height = 0

            elif priority == 2:
                # Critical ICs (MCUs): try central area with collision validation
                placed_successfully = False
                mcu_count = len([c for c in placed if c.get('_priority') == 2])

                # Try multiple central positions
                for offset_mult in range(10):  # Try up to 10 positions
                    test_x = central_x + (offset_mult * 20.0) - width / 2
                    test_y = central_y - height / 2

                    # Keep within board bounds
                    test_x = max(self.margin, min(test_x, self.board_width - width - self.margin))
                    test_y = max(self.margin, min(test_y, self.board_height - height - self.margin))

                    if not self._collides(test_x, test_y, width, height, occupied_regions, clearance):
                        x, y = test_x, test_y
                        placed_successfully = True
                        break

                if not placed_successfully:
                    # Central area full, fallback to grid
                    x, y = self._find_next_grid_position(grid_x, grid_y, width, height,
                                                         occupied_regions)
                    # TC #38: Update grid position after fallback placement
                    grid_x = x + width + self.min_component_clearance
                    row_height = max(row_height, height)
                    if grid_x + width > self.board_width - self.margin:
                        grid_x = self.margin
                        grid_y += row_height + self.min_component_clearance
                        row_height = 0

            else:
                # Other components: use grid placement with collision detection
                x, y = self._find_next_grid_position(grid_x, grid_y, width, height,
                                                     occupied_regions)
                # TC #37: Update grid position with manufacturing clearance
                grid_x = x + width + self.min_component_clearance
                row_height = max(row_height, height)

                # Move to next row if needed
                if grid_x + width > self.board_width - self.margin:
                    grid_x = self.margin
                    grid_y += row_height + self.min_component_clearance
                    row_height = 0

            # Verify position was assigned
            if x is None or y is None:
                # Emergency fallback: place at margin
                logger.warning(f"⚠️  Emergency fallback placement for {comp.get('ref', '?')}")
                x = self.margin
                y = self.margin

            # Assign position (KiCad uses center coordinates)
            comp['brd_x'] = x + width / 2
            comp['brd_y'] = y + height / 2
            comp['rotation'] = 0  # Default rotation

            # Mark as occupied
            occupied_regions.append((x, y, width, height))
            placed.append(comp)

        return placed

    def _generate_edge_positions(self) -> List[Tuple[float, float]]:
        """
        Generate positions along board edges for connectors (GENERIC).

        Returns:
            List of (x, y) positions (top-left corner coordinates)
        """
        positions = []

        # Left edge (vertical spacing)
        num_left = 4
        for i in range(num_left):
            y = self.margin + (i * (self.board_height - 2 * self.margin) / num_left)
            positions.append((self.margin, y))

        # Right edge
        num_right = 4
        for i in range(num_right):
            y = self.margin + (i * (self.board_height - 2 * self.margin) / num_right)
            positions.append((self.board_width - self.margin - 10.0, y))

        # Top edge
        num_top = 4
        for i in range(num_top):
            x = self.margin + (i * (self.board_width - 2 * self.margin) / num_top)
            positions.append((x, self.margin))

        # Bottom edge
        num_bottom = 4
        for i in range(num_bottom):
            x = self.margin + (i * (self.board_width - 2 * self.margin) / num_bottom)
            positions.append((x, self.board_height - self.margin - 10.0))

        return positions

    def _find_next_grid_position(self, start_x: float, start_y: float,
                                  width: float, height: float,
                                  occupied: List[Tuple[float, float, float, float]]
                                  ) -> Tuple[float, float]:
        """
        Find next available grid position (GENERIC collision avoidance).
        TC #37: Enhanced with manufacturing clearances.

        Args:
            start_x: Starting x position
            start_y: Starting y position
            width: Component width
            height: Component height
            occupied: List of occupied (x, y, w, h) rectangles

        Returns:
            (x, y) position (top-left corner)
        """
        # TC #38: Use central config clearance (from MANUFACTURING_CONFIG)
        clearance = self.min_component_clearance
        search_step = 2.54  # mm - finer grid for better packing

        # IMPROVED ALGORITHM: Search in expanding spiral from start position
        for y_offset in range(0, int(self.board_height), int(height + clearance)):
            y = start_y + y_offset

            if y + height + self.margin > self.board_height:
                break  # Exceeded board height

            for x in range(int(self.margin), int(self.board_width - width - self.margin), int(search_step)):
                # Check if this position is collision-free
                if not self._collides(float(x), float(y), width, height, occupied, clearance):
                    return (float(x), float(y))

        # Fallback: try absolute bottom-right corner
        fallback_x = self.board_width - width - self.margin
        fallback_y = self.board_height - height - self.margin

        if not self._collides(fallback_x, fallback_y, width, height, occupied, clearance):
            return (fallback_x, fallback_y)

        # Last resort: return start position (will cause overlap)
        logger.warning(f"⚠️  Could not find collision-free position, using fallback")
        return (start_x, start_y)

    def _collides(self, x: float, y: float, w: float, h: float,
                  occupied: List[Tuple[float, float, float, float]],
                  clearance: float) -> bool:
        """
        Check if position collides with occupied regions (GENERIC).

        Args:
            x, y: Position to test (top-left corner)
            w, h: Component dimensions
            occupied: List of occupied rectangles
            clearance: Required clearance

        Returns:
            True if collision detected
        """
        for occ_x, occ_y, occ_w, occ_h in occupied:
            # Check rectangle overlap with clearance
            if not (x + w + clearance < occ_x or
                    x > occ_x + occ_w + clearance or
                    y + h + clearance < occ_y or
                    y > occ_y + occ_h + clearance):
                return True

        return False


# GENERIC helper function
def optimize_component_placement(groups: Dict[str, List[Dict]],
                                 board_width: float,
                                 board_height: float,
                                 footprint_db=None) -> List[Dict]:
    """
    One-function interface for placement optimization (GENERIC).

    Args:
        groups: Component groups from ComponentGrouper
        board_width: Board width in mm
        board_height: Board height in mm
        footprint_db: Optional footprint database

    Returns:
        List of components with optimized placement
    """
    optimizer = PlacementOptimizer(board_width, board_height)
    return optimizer.optimize_placement(groups, footprint_db)
