# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Design for Manufacturability (DFM) Module
==========================================

This module provides comprehensive DFM checking capabilities for PCB designs
across multiple CAD formats (KiCad, Eagle, EasyEDA Pro).

Architecture:
-------------
1. dfm_checker.py - Core DFM validation logic (format-agnostic)
2. kicad_parser.py - Extract design parameters from KiCad PCB files
3. eagle_parser.py - Extract design parameters from Eagle board files
4. easyeda_parser.py - Extract design parameters from EasyEDA Pro files
5. dfm_code_fixer.py - Automated fixes for common DFM violations
6. dfm_reporter.py - HTML report generation

Integration:
------------
DFM checks are integrated into the converter validation pipeline:
  Convert → ERC → DRC → DFM → Code Fixer → AI Fixer (if needed)

All violations are logged, reported, and can be auto-fixed when possible.

Author: CopperPilot Development Team
Created: November 9, 2025
Version: 1.0
"""

__version__ = "1.0.0"
__author__ = "CopperPilot Development Team"

# Export main classes for easy importing
from .dfm_checker import DFMChecker, DFMResult, DFMViolation, ViolationSeverity

__all__ = [
    'DFMChecker',
    'DFMResult',
    'DFMViolation',
    'ViolationSeverity',
]

