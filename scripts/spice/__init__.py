#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
SPICE/LTSpice Converter Package
===============================

This package provides functionality to convert CopperPilot circuit JSON files
into SPICE netlist format (.cir) and LTSpice schematic format (.asc).

Modules
-------
- model_library: Component to SPICE model mapping (GENERIC for any circuit type)
- netlist_generator: SPICE .cir netlist generation
- ltspice_generator: LTSpice .asc schematic generation
- simulation_validator: Parse simulation results and validate against requirements
- spice_utils: Shared utility functions (V.4: canonical name sanitization)

Design Philosophy
-----------------
This converter is designed to be:
- GENERIC: Works with any circuit type (simple LED to complex multi-board systems)
- MODULAR: Each module has a single responsibility
- DYNAMIC: Handles unknown components gracefully with fallback models

Usage
-----
    from scripts.spice import SpiceNetlistGenerator, LTSpiceGenerator

    # Generate SPICE netlist
    generator = SpiceNetlistGenerator()
    generator.convert(input_path, output_path)

    # Generate LTSpice schematic
    ltspice = LTSpiceGenerator()
    ltspice.convert(input_path, output_path)

Author: CopperPilot Team
Date: December 2025
Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "CopperPilot Team"

# V.4 FIX: Import canonical sanitization from spice_utils (no circular import)
from .spice_utils import spice_safe_name

# Public API exports
from .model_library import SpiceModelLibrary, ComponentModel
from .netlist_generator import SpiceNetlistGenerator
from .ltspice_generator import LTSpiceGenerator
from .simulation_validator import SimulationValidator

__all__ = [
    "SpiceModelLibrary",
    "ComponentModel",
    "SpiceNetlistGenerator",
    "LTSpiceGenerator",
    "SimulationValidator",
    "spice_safe_name",
]
