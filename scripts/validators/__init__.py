# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Modular Validators for CopperPilot Converters
==============================================

Standalone, reusable validators that can be used independently or
imported by converter scripts.

Available Validators:
--------------------

FORMAT-SPECIFIC VALIDATORS:

Eagle Format:
- EagleERCValidator: ERC validation for Eagle .sch files
- EagleDRCValidator: DRC validation for Eagle .brd files
- EagleDFMValidator: DFM validation for Eagle .brd files

KiCad Format:
- KiCadERCValidator: ERC validation for KiCad .kicad_sch files
- KiCadDRCValidator: DRC validation for KiCad .kicad_pcb files
- KiCadDFMValidator: DFM validation for KiCad .kicad_pcb files

FORMAT-AGNOSTIC VALIDATORS (TC #62):
- QualityMetricsValidator: Advanced quality metrics (works with lowlevel JSON)
  - Component Derating Checks (IPC-2221B/IPC-9592)
  - Power Dissipation Calculations
  - Thermal Estimates (junction temperature)
  - Trace Impedance Analysis
  - Signal Integrity Checks (partial)
  - DFM Multi-Vendor Profiles (JLCPCB, PCBWay, OSH Park, Seeed Fusion)
  - DFT Requirements (testpoints, debug headers)
  - Assembly Checks (fiducials, orientation)

Usage:
------
  # Format-specific validators
  from validators.eagle_erc_validator import EagleERCValidator
  from validators.eagle_drc_validator import EagleDRCValidator
  from validators.eagle_dfm_validator import EagleDFMValidator
  from validators.kicad_erc_validator import KiCadERCValidator
  from validators.kicad_drc_validator import KiCadDRCValidator
  from validators.kicad_dfm_validator import KiCadDFMValidator

  # Format-agnostic validators (work with lowlevel JSON)
  from validators.quality_metrics_validator import (
      QualityMetricsValidator,
      QualityMetricsResult,
      DFMVendorProfile,
      Severity,
      MetricCategory,
  )

Author: CopperPilot AI Circuit Design Platform
Version: 2.0.0 (TC #62 - Added quality_metrics_validator)
Date: 2025-11-30
"""

# Eagle validators
from .eagle_erc_validator import EagleERCValidator
from .eagle_drc_validator import EagleDRCValidator
from .eagle_dfm_validator import EagleDFMValidator

# KiCad validators
from .kicad_erc_validator import KiCadERCValidator
from .kicad_drc_validator import KiCadDRCValidator
from .kicad_dfm_validator import KiCadDFMValidator

# Format-agnostic quality metrics validator (TC #62)
from .quality_metrics_validator import (
    QualityMetricsValidator,
    QualityMetricsResult,
    ValidationIssue,
    DFMVendorProfile,
    Severity,
    MetricCategory,
    PowerAnalysis,
    ThermalAnalysis,
    ImpedanceAnalysis,
)

__all__ = [
    # Eagle validators
    'EagleERCValidator',
    'EagleDRCValidator',
    'EagleDFMValidator',
    # KiCad validators
    'KiCadERCValidator',
    'KiCadDRCValidator',
    'KiCadDFMValidator',
    # Format-agnostic quality metrics (TC #62)
    'QualityMetricsValidator',
    'QualityMetricsResult',
    'ValidationIssue',
    'DFMVendorProfile',
    'Severity',
    'MetricCategory',
    'PowerAnalysis',
    'ThermalAnalysis',
    'ImpedanceAnalysis',
]
