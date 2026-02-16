#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Routing Module Package
GENERIC MODULE - Works for ANY circuit

Provides comprehensive PCB auto-routing functionality.

Main components:
- GridOccupancy: Spatial tracking for collision detection
- PathRouter: Single and multi-point routing algorithms
- PCBRouter: Main orchestrator
- SegmentGenerator: KiCad format output

Author: Electronics Automation System
Date: 2025-10-27
"""

from .grid_occupancy import GridOccupancy, Point, Rectangle, Layer
from .path_routing import (PathRouter, MultiPointRouter, RoutingConfig,
                           RoutingStrategy)
from .segment_generator import (SegmentGenerator, Segment, Via,
                                RoutingStatistics)
# OLD ROUTER REMOVED (2025-11-16): Replaced with Freerouting integration
# from .pcb_router import PCBRouter, route_circuit_pcb

__all__ = [
    # Core classes
    'GridOccupancy',
    'Point',
    'Rectangle',
    'Layer',
    'PathRouter',
    'MultiPointRouter',
    'RoutingConfig',
    'RoutingStrategy',
    'SegmentGenerator',
    'Segment',
    'Via',
    'RoutingStatistics',
    # OLD ROUTER REMOVED: 'PCBRouter', 'route_circuit_pcb',
]

__version__ = '1.0.0'
