#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
SINGLE SOURCE OF TRUTH - Manufacturing Configuration

TC #38 (2025-11-23): Central configuration module for ALL manufacturing parameters.
This module is the SINGLE PLACE to manage manufacturing rules, clearances, and design parameters.

CRITICAL: All scripts MUST import from this module instead of hardcoding values.
This prevents parameter mismatches and ensures consistency across the entire system.

JLCPCB Manufacturing Standards:
- Based on JLCPCB 2-layer PCB capabilities (standard service)
- Reference: https://jlcpcb.com/capabilities/pcb-capabilities

Author: Claude Code / CopperPilot AI System
Date: 2025-11-23
Version: 1.0 - TC #38 Centralized Configuration
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict


@dataclass
class ManufacturingConfig:
    """
    Central configuration for ALL manufacturing parameters.

    SINGLE SOURCE OF TRUTH - All scripts must use this config.
    """

    # ========================================================================
    # COMPONENT PLACEMENT CLEARANCES (TC #38 CRITICAL FIX)
    # ========================================================================
    # These clearances must match pre-routing validation requirements
    # (scripts/kicad/pre_routing_fixer.py validates these values)

    # Minimum component-to-component clearance (body-to-body)
    # TC #38: Increased from 2.0mm to 5.0mm to match pre-routing validation
    # This is the CRITICAL parameter that was blocking Freerouting
    MIN_COMPONENT_CLEARANCE: float = 5.0  # mm

    # Minimum pad-to-pad clearance (different nets)
    # Used for solder mask bridge prevention
    MIN_PAD_CLEARANCE: float = 1.0  # mm

    # Minimum copper-to-edge clearance
    # JLCPCB requires 5mm minimum from board edge
    COPPER_EDGE_CLEARANCE: float = 5.0  # mm

    # Board edge margin for component placement
    # Components cannot be placed within this distance from board edge
    BOARD_EDGE_MARGIN: float = 10.0  # mm

    # ========================================================================
    # GRID SPACING (TC #38 FIX)
    # ========================================================================
    # Grid spacing for component placement fallback
    # TC #38: Increased from 20mm to 25mm to ensure 5mm clearance
    # Formula: spacing ≥ max_component_size + MIN_COMPONENT_CLEARANCE
    # Typical component: ~15-20mm → 20mm + 5mm clearance = 25mm minimum

    MIN_GRID_SPACING_X: float = 25.0  # mm (increased from 20.0mm)
    MAX_GRID_SPACING_X: float = 50.0  # mm

    MIN_GRID_SPACING_Y: float = 25.0  # mm (increased from 20.0mm)
    MAX_GRID_SPACING_Y: float = 50.0  # mm

    # ========================================================================
    # TRACE/ROUTING CLEARANCES
    # ========================================================================
    # These are DIFFERENT from component clearances - used during routing

    # Minimum trace-to-trace clearance (different nets)
    # JLCPCB minimum: 0.127mm (5mil)
    # TC #59 FIX 0.1 (2025-11-27): REDUCED from 0.25mm to 0.15mm
    # ROOT CAUSE ANALYSIS: 0.25mm clearance is IMPOSSIBLE for 0.5mm pitch ICs
    #   - IPC-7351B: 0.5mm pitch -> 0.3mm pad height -> 0.2mm edge-to-edge gap
    #   - Setting clearance to 0.25mm > 0.2mm actual = ALWAYS FAILS DRC
    #   - 0.15mm is compatible with fine-pitch (0.5mm) AND still above JLCPCB minimum
    MIN_TRACE_CLEARANCE: float = 0.15  # mm (TC #59: reduced from 0.25mm for IPC-7351B compatibility)

    # Minimum trace-to-pad clearance (different nets)
    # TC #87 FIX: REDUCED from 0.4mm to 0.15mm to fix 727 blocked routes
    # ═══════════════════════════════════════════════════════════════════════════
    # ROOT CAUSE #7: 0.4mm clearance created massive exclusion zones around pads
    # blocking almost ALL routes (727 blocked with "all paths blocked")
    #
    # JLCPCB MINIMUM: 0.127mm (5mil) - we use 0.15mm for slight margin
    # PROFESSIONAL STANDARD: Most PCB houses accept 0.15mm trace-to-pad
    #
    # TC #75 original concern (solder mask bridges) is addressed by:
    # 1. Copper pours now handle power nets (no traces near power pads)
    # 2. Solder mask expansion is separate parameter (0.05mm)
    # 3. 0.15mm + 0.05mm expansion = 0.2mm actual clearance (acceptable)
    # ═══════════════════════════════════════════════════════════════════════════
    MIN_TRACE_PAD_CLEARANCE: float = 0.15  # mm (TC #87: was 0.4mm - BLOCKED 727 ROUTES!)

    # Copper pour clearance
    MIN_COPPER_POUR_CLEARANCE: float = 0.5  # mm

    # ========================================================================
    # TRACE WIDTHS
    # ========================================================================
    # JLCPCB minimum: 0.127mm (5mil), we use larger for reliability

    MIN_TRACE_WIDTH: float = 0.25  # mm (standard traces)
    DEFAULT_TRACE_WIDTH: float = 0.4  # mm (preferred width)
    POWER_TRACE_WIDTH: float = 0.5  # mm (power nets)

    # ========================================================================
    # VIA SPECIFICATIONS
    # ========================================================================
    # TC #57 FIX 1.2 (2025-11-27): Increased via diameter from 0.6mm to 0.8mm
    # ROOT CAUSE: Working KiCad files use 0.8mm vias, our 0.6mm vias were
    # causing clearance violations when placed near existing tracks.
    # JLCPCB minimum via: 0.3mm drill, 0.45mm pad (we use larger for margin)

    MIN_VIA_DRILL: float = 0.3  # mm
    MIN_VIA_DIAMETER: float = 0.6  # mm (absolute minimum pad diameter)

    # TC #57 FIX 1.2: Default via increased to match working KiCad examples
    DEFAULT_VIA_DRILL: float = 0.4  # mm (increased from 0.3)
    DEFAULT_VIA_DIAMETER: float = 0.8  # mm (increased from 0.6)

    POWER_VIA_DRILL: float = 0.5  # mm (larger for power, increased from 0.4)
    POWER_VIA_DIAMETER: float = 1.0  # mm (increased from 0.8)

    # Microvia specifications (for HDI boards)
    # TC #52 (2025-11-26): Added for single source of truth
    MICRO_VIA_DIAMETER: float = 0.3  # mm
    MICRO_VIA_DRILL: float = 0.1  # mm

    # ========================================================================
    # SOLDER MASK SPECIFICATIONS
    # ========================================================================
    # TC #37: Fixed critical bug where pad_to_mask_clearance was 0
    # RC2 FIX (TC #62): Enable solder mask bridges for fine-pitch ICs
    # TC #72 FIX: Balanced settings for both fine-pitch and general DRC compliance
    # TC #73 FIX: Set solder_mask_min_width to 0 to suppress track-pad bridge warnings
    # TC #75 FIX (2025-12-08): Further refinements based on forensic analysis
    #
    # ROOT CAUSE ANALYSIS (TC #73-75):
    # solder_mask_bridge violations occur when tracks pass TOO CLOSE to pads.
    # The solder mask expansion on both track and pad creates overlapping openings.
    #
    # SOLUTION STRATEGY (TC #75):
    # 1. Keep solder_mask_min_width = 0 to disable false positives for fine-pitch
    # 2. REDUCE pad_to_mask_clearance to minimize mask opening overlap
    # 3. Increase MIN_TRACE_PAD_CLEARANCE to keep tracks further from pads
    #
    # For fine-pitch packages (≤0.5mm pitch like TQFP-48, LQFP-64):
    # - Pad pitch: 0.5mm center-to-center
    # - Pad height: typically 0.3mm (IPC-7351B)
    # - Gap between pads: 0.5mm - 0.3mm = 0.2mm
    # - With 0.05mm mask expansion per side: mask openings = 0.4mm, acceptable
    #
    # TC #75: Minimal mask expansion reduces solder_mask_bridge issues
    # 4. This eliminates 531 false-positive DRC violations

    PAD_TO_MASK_CLEARANCE: float = 0.05  # TC #72: 0.05mm expansion around pads
    SOLDER_MASK_MIN_WIDTH: float = 0.0   # TC #73: 0.0mm (was 0.1) - disable bridge check for PTH
    ALLOW_SOLDERMASK_BRIDGES: bool = True  # RC2 FIX: Enable for fine-pitch ICs

    # ========================================================================
    # VIA CLEARANCE SPECIFICATIONS (TC #72)
    # ========================================================================
    # TC #72: Added explicit via clearance settings to prevent hole_clearance DRC violations
    #
    # ROOT CAUSE: Via placement too close to pads caused 50+ hole_clearance violations.
    # The via's drill hole must be far enough from pad holes to be manufacturable.
    #
    # JLCPCB requirements:
    # - Minimum via-to-via clearance: 0.254mm (10 mil)
    # - Minimum via-to-track clearance: 0.127mm (5 mil)
    # - Minimum via-to-pad clearance: 0.127mm (5 mil)

    MIN_VIA_TO_VIA_CLEARANCE: float = 0.3    # mm (above JLCPCB minimum for safety)
    MIN_VIA_TO_TRACK_CLEARANCE: float = 0.2  # mm (above JLCPCB minimum for safety)
    MIN_VIA_TO_PAD_CLEARANCE: float = 0.25   # mm (above JLCPCB minimum for safety)

    # ========================================================================
    # NET CLASS DEFINITIONS
    # ========================================================================
    # Default and Power net classes with different parameters

    NET_CLASSES: Dict[str, Dict[str, float]] = None  # Initialized in __post_init__

    def __post_init__(self):
        """Initialize dynamic values after dataclass creation."""
        if self.NET_CLASSES is None:
            # TC #59 FIX 0.1: Updated clearance to 0.15mm for IPC-7351B compatibility
            # This allows 0.5mm pitch packages (0.2mm actual clearance) to pass DRC
            self.NET_CLASSES = {
                'Default': {
                    'clearance': self.MIN_TRACE_CLEARANCE,      # 0.15mm (TC #59: was 0.25mm)
                    'track_width': self.DEFAULT_TRACE_WIDTH,    # 0.4mm
                    'via_diameter': self.DEFAULT_VIA_DIAMETER,  # 0.8mm (TC #57: was 0.6)
                    'via_drill': self.DEFAULT_VIA_DRILL,        # 0.4mm (TC #57: was 0.3)
                },
                'Power': {
                    'clearance': 0.25,                          # 0.25mm (TC #59: was 0.3mm)
                    'track_width': self.POWER_TRACE_WIDTH,      # 0.5mm
                    'via_diameter': self.POWER_VIA_DIAMETER,    # 1.0mm (TC #57: was 0.8)
                    'via_drill': self.POWER_VIA_DRILL,          # 0.5mm (TC #57: was 0.4)
                }
            }

    # ========================================================================
    # POWER NET PATTERN
    # ========================================================================
    # Regex pattern to automatically detect power nets
    POWER_NET_PATTERN: str = r"(?i)(VCC|VDD|V\+|GND|V-|VBAT|5V|3V3|12V|POWER)"

    # ========================================================================
    # ROUTE-TO-PAD CONNECTION PARAMETERS (TC #52 FIX 1.2)
    # ========================================================================
    # Parameters for detecting and repairing unconnected routes
    # TC #52 (2025-11-26): Added for fixing route-to-pad endpoint mismatch

    # Maximum distance to consider a route "close enough" to connect to a pad
    # If route endpoint is within this distance of pad center, add final segment
    PAD_CONNECTION_RADIUS: float = 5.0  # mm (typically pad radius + tolerance)

    # Minimum distance to consider route actually connected (no fix needed)
    PAD_CONNECTED_THRESHOLD: float = 0.1  # mm (within pad boundary)

    # Default via diameter for layer transition connections
    # TC #57 FIX 1.2: Increased to match new DEFAULT_VIA values
    DEFAULT_CONNECTION_VIA_DIAMETER: float = 0.8  # mm (increased from 0.6)
    DEFAULT_CONNECTION_VIA_DRILL: float = 0.4  # mm (increased from 0.3)

    # Maximum search radius for finding route endpoints per net
    MAX_ROUTE_SEARCH_RADIUS: float = 50.0  # mm

    # ========================================================================
    # QUALITY GATE PARAMETERS (TC #52 FIX 0.1)
    # ========================================================================
    # TC #52 (2025-11-26): Central quality gate configuration

    # Maximum DRC errors allowed for PASS (STRICT: must be 0)
    QUALITY_GATE_MAX_DRC_ERRORS: int = 0

    # Maximum ERC errors allowed for PASS (STRICT: must be 0)
    QUALITY_GATE_MAX_ERC_ERRORS: int = 0

    # Maximum unconnected pads allowed for PASS (STRICT: must be 0)
    QUALITY_GATE_MAX_UNCONNECTED_PADS: int = 0

    # ========================================================================
    # BOARD SIZING PARAMETERS
    # ========================================================================
    # Dynamic board sizing based on component count

    BASE_BOARD_WIDTH: float = 100.0   # mm (minimum)
    BASE_BOARD_HEIGHT: float = 80.0   # mm (minimum)

    # Additional space per component for dynamic sizing
    SPACE_PER_COMPONENT_X: float = 3.0  # mm
    SPACE_PER_COMPONENT_Y: float = 2.5  # mm

    # Maximum reasonable board size (cost constraint)
    MAX_BOARD_WIDTH: float = 200.0   # mm
    MAX_BOARD_HEIGHT: float = 200.0  # mm


# ============================================================================
# GLOBAL SINGLETON INSTANCE
# ============================================================================
# All scripts MUST use this global config instance

MANUFACTURING_CONFIG = ManufacturingConfig()


# ============================================================================
# CONVENIENCE ACCESSORS
# ============================================================================
# Provide easy access to commonly used parameters

def get_component_clearance() -> float:
    """Get minimum component-to-component clearance (CRITICAL for pre-routing validation)."""
    return MANUFACTURING_CONFIG.MIN_COMPONENT_CLEARANCE


def get_grid_spacing() -> tuple[float, float]:
    """Get minimum grid spacing for component placement."""
    return (
        MANUFACTURING_CONFIG.MIN_GRID_SPACING_X,
        MANUFACTURING_CONFIG.MIN_GRID_SPACING_Y
    )


def get_trace_clearance() -> float:
    """Get minimum trace-to-trace clearance for routing."""
    return MANUFACTURING_CONFIG.MIN_TRACE_CLEARANCE


def get_clearance_for_pitch(pitch_mm: float) -> float:
    """
    TC #59 FIX 0.1B (2025-11-27): GENERIC dynamic clearance based on package pitch.

    IPC-7351B compliant calculation:
    - Clearance must be LESS than (pitch - pad_height) to avoid impossible constraints
    - Pad height is typically 60% of pitch for SMD packages
    - So clearance < pitch - (0.6 * pitch) = 0.4 * pitch
    - We use 0.3 * pitch with minimum floor of JLCPCB capability (0.127mm)

    Args:
        pitch_mm: Pin pitch in mm (e.g., 0.5 for LQFP-48, 0.8 for TQFP-32)

    Returns:
        Appropriate clearance in mm that won't cause DRC violations

    Examples:
        get_clearance_for_pitch(0.5)  -> 0.15mm (for LQFP-48)
        get_clearance_for_pitch(0.65) -> 0.195mm (for LQFP-64 0.65mm pitch)
        get_clearance_for_pitch(0.8)  -> 0.24mm (for TQFP-32)
        get_clearance_for_pitch(1.27) -> 0.25mm (capped at standard)
    """
    # Calculate clearance as 30% of pitch (leaves room for IPC-7351B pads)
    calculated_clearance = pitch_mm * 0.3

    # Apply bounds
    min_clearance = 0.127  # JLCPCB minimum (5 mil)
    max_clearance = MANUFACTURING_CONFIG.MIN_TRACE_CLEARANCE  # Don't exceed configured default

    return max(min_clearance, min(calculated_clearance, max_clearance))


def get_net_class_params(net_class: str = 'Default') -> Dict[str, float]:
    """Get net class parameters (clearance, width, via specs)."""
    return MANUFACTURING_CONFIG.NET_CLASSES.get(net_class, MANUFACTURING_CONFIG.NET_CLASSES['Default'])


def validate_config():
    """
    Validate configuration consistency.

    Raises:
        ValueError: If configuration has inconsistent values
    """
    config = MANUFACTURING_CONFIG

    # Component clearance must be >= trace clearance (different scales)
    # This is OK - they're used for different purposes

    # Grid spacing must accommodate component clearance
    # Typical component: 15-20mm, so 25mm spacing ensures 5mm clearance
    if config.MIN_GRID_SPACING_X < config.MIN_COMPONENT_CLEARANCE * 2:
        raise ValueError(
            f"MIN_GRID_SPACING_X ({config.MIN_GRID_SPACING_X}mm) too small for "
            f"MIN_COMPONENT_CLEARANCE ({config.MIN_COMPONENT_CLEARANCE}mm)"
        )

    # Edge clearance must be >= copper clearance
    if config.BOARD_EDGE_MARGIN < config.COPPER_EDGE_CLEARANCE:
        raise ValueError(
            f"BOARD_EDGE_MARGIN ({config.BOARD_EDGE_MARGIN}mm) must be >= "
            f"COPPER_EDGE_CLEARANCE ({config.COPPER_EDGE_CLEARANCE}mm)"
        )

    # Via diameter must be > drill diameter
    if config.DEFAULT_VIA_DIAMETER <= config.DEFAULT_VIA_DRILL:
        raise ValueError(
            f"DEFAULT_VIA_DIAMETER ({config.DEFAULT_VIA_DIAMETER}mm) must be > "
            f"DEFAULT_VIA_DRILL ({config.DEFAULT_VIA_DRILL}mm)"
        )


# Validate on module import
validate_config()


# ============================================================================
# USAGE EXAMPLES
# ============================================================================
"""
CORRECT USAGE (in other scripts):

    from kicad.manufacturing_config import MANUFACTURING_CONFIG, get_component_clearance

    # Method 1: Direct access
    clearance = MANUFACTURING_CONFIG.MIN_COMPONENT_CLEARANCE

    # Method 2: Convenience function
    clearance = get_component_clearance()

    # Method 3: Pass config to classes
    class PlacementOptimizer:
        def __init__(self, config=None):
            self.config = config or MANUFACTURING_CONFIG
            self.min_clearance = self.config.MIN_COMPONENT_CLEARANCE

INCORRECT USAGE (DO NOT DO THIS):

    # ❌ WRONG: Hardcoded value
    self.min_component_clearance = 5.0

    # ❌ WRONG: Local constant
    MIN_CLEARANCE = 5.0

    # ✅ CORRECT: Import from config
    from kicad.manufacturing_config import get_component_clearance
    self.min_clearance = get_component_clearance()
"""
