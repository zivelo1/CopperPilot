# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

# Schematic Generator Modules
# Version 6.2 - Domain-Aware Layout + A* Pathfinding
from .utils import (
    SchematicContext,
    Component,
    Wire,
    Net,
    Pin,
    Point,
    Rectangle,
    get_wire_color,
    get_component_type_category
)
from .input_processor import InputProcessor
from .symbol_library import SymbolLibrary
from .layout_engine import LayoutEngine
from .wire_router_astar import WireRouter  # A* pathfinding with obstacle avoidance
from .renderer import Renderer
from .validator import Validator

__all__ = [
    'SchematicContext',
    'Component',
    'Wire',
    'Net',
    'Pin',
    'Point',
    'Rectangle',
    'get_wire_color',
    'get_component_type_category',
    'InputProcessor',
    'SymbolLibrary',
    'LayoutEngine',
    'WireRouter',
    'Renderer',
    'Validator'
]