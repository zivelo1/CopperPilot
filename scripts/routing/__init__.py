# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Routing Module - Pure Python Manhattan Router
==============================================

TC #81 (2025-12-14): Removed Freerouting dependency, using pure Python Manhattan router.

This module provides a MODULAR, GENERIC, and REUSABLE routing engine
that serves ALL converters (KiCad, Eagle, EasyEDA Pro).

Key Components:
--------------
- board_data: Format-agnostic PCB representation (GENERIC)
- manhattan_router: Pure Python grid-based router with collision detection
- kicad_adapter: Parse KiCad PCB files to BoardData
- route_applicator: Apply routing results back to PCB files

TC #81 Routing Features:
-----------------------
✅ 0.1mm grid for precise collision detection
✅ Wire validation before committing (eliminates track crossings)
✅ Post-routing validation (final safety net)
✅ MST topology (minimizes crossings)
✅ Multi-layer support with automatic via insertion
✅ No Java dependency (pure Python)

Architecture Benefits:
---------------------
✅ SINGLE SOURCE OF TRUTH: One implementation for all converters
✅ CONSISTENCY: Identical routing quality across all formats
✅ MAINTAINABILITY: Fix once, benefits all converters
✅ TESTABILITY: Test engine independently
✅ GENERIC: Works for ANY circuit type, ANY complexity
✅ DETERMINISTIC: No subprocess timeouts, predictable behavior

Usage Example:
-------------
```python
from routing import ManhattanRouter, ManhattanRouterConfig, BoardData

# Create format-agnostic board representation
board = BoardData(
    components=[...],
    nets=[...],
    outline=BoardOutline([...]),
    design_rules=DesignRules(...)
)

# Initialize router with TC #81 defaults
router = ManhattanRouter(ManhattanRouterConfig())

# Route PCB
routing_data = router.route(board)

if routing_data.wires:
    print(f"Generated {len(routing_data.wires)} wires")
```

Author: Claude Code
Date: 2025-12-14
Version: 2.0.0
Status: TC #81 - Pure Python Routing
"""

# Import key classes for convenient access
from .board_data import (
    BoardData,
    Component,
    Pad,
    Net,
    BoardOutline,
    DesignRules,
    Layer,
    PadShape,
    Side
)

# TC #81 (2025-12-14): Removed FreeRoutingEngine import - using pure Python Manhattan router
from .kicad_adapter import KiCadAdapter
from .route_applicator import RouteApplicator
from .manhattan_router import ManhattanRouter, ManhattanRouterConfig

# Keep RoutingData for compatibility with route applicator
from .ses_parser import RoutingData, Wire, Via

__all__ = [
    # Board data structures
    'BoardData',
    'Component',
    'Pad',
    'Net',
    'BoardOutline',
    'DesignRules',
    'Layer',
    'PadShape',
    'Side',

    # TC #81: Primary routing components (Manhattan router)
    'ManhattanRouter',
    'ManhattanRouterConfig',
    'KiCadAdapter',
    'RouteApplicator',

    # Routing data structures (still needed for route applicator)
    'RoutingData',
    'Wire',
    'Via',
]

__version__ = '2.0.0'
__author__ = 'Claude Code'
__date__ = '2025-12-14'
