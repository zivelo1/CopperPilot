#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Footprint Dimensions Database - COMPREHENSIVE
==============================================

Provides accurate bounding box dimensions for KiCad footprints.

PHASE 2 (2025-11-18): Migrated to use FootprintLibraryParser for comprehensive coverage.
Now uses 1000+ footprint database with intelligent pattern matching.

Author: Claude Code / CopperPilot AI System
Date: 2025-11-18
Version: 2.0 - Uses comprehensive FootprintLibraryParser
"""

from typing import Tuple
from kicad.footprint_library_parser import get_footprint_dimensions


def get_footprint_bbox(footprint: str, pin_count: int = 2) -> Tuple[float, float]:
    """
    Get bounding box dimensions for a KiCad footprint.

    PHASE 2 (2025-11-18): Now uses comprehensive FootprintLibraryParser with 1000+ footprints.

    Args:
        footprint: KiCad footprint name (e.g., "R_0805_2012Metric")
        pin_count: Number of pins (used for intelligent fallback estimation)

    Returns:
        (width, height) tuple in millimeters

    GENERIC: Works for ANY footprint through comprehensive database + intelligent pattern matching.
    Covers:
    - SMD passive components (resistors, capacitors, LEDs, diodes)
    - SMD IC packages (SOIC, TSSOP, QFP, QFN, BGA)
    - Through-hole packages (DIP, SIP, pin headers, terminal blocks)
    - Specialized components (crystals, oscillators, connectors, power modules)
    """
    # Use comprehensive FootprintLibraryParser (1000+ footprints + intelligent fallback)
    return get_footprint_dimensions(footprint, pin_count)


__all__ = ['get_footprint_bbox']
