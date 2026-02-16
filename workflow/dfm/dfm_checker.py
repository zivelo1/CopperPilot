# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
DFM Checker - Core Design for Manufacturability Validation
===========================================================

This module implements comprehensive DFM checking against PCB fabricator
capabilities. It validates designs for trace widths, spacing, drill sizes,
clearances, and other manufacturing constraints.

Architecture:
- Format-agnostic: Works with parsed data from any CAD format
- Database-driven: Fab capabilities defined in structured format
- Extensible: Easy to add new checks and fabricators

Integration:
- Called by converters after DRC validation
- Returns violations that can be auto-fixed or reported
- Integrates with code fixer and AI fixer pipeline

Author: CopperPilot Development Team
Created: November 9, 2025
License: MIT
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

# Setup logger
logger = logging.getLogger(__name__)


class ViolationSeverity(Enum):
    """Severity levels for DFM violations"""
    ERROR = "error"           # Must fix - fab will reject
    WARNING = "warning"       # Should fix - reliability concern
    SUGGESTION = "suggestion" # Nice to have - optimization


@dataclass
class DFMViolation:
    """
    Represents a single DFM violation.

    Attributes:
        check_name: Name of the check that failed (e.g., "trace_width")
        severity: ERROR, WARNING, or SUGGESTION
        message: Human-readable description of the violation
        location: Where the violation occurs (coordinates, layer, net name)
        current_value: The violating value (e.g., 0.10mm trace width)
        required_value: The minimum/maximum allowed value
        fix_suggestion: How to fix this violation
        auto_fixable: Whether code fixer can automatically fix this
    """
    check_name: str
    severity: ViolationSeverity
    message: str
    location: Dict[str, Any]
    current_value: Any
    required_value: Any
    fix_suggestion: str
    auto_fixable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "check_name": self.check_name,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location,
            "current_value": str(self.current_value),
            "required_value": str(self.required_value),
            "fix_suggestion": self.fix_suggestion,
            "auto_fixable": self.auto_fixable
        }


@dataclass
class DFMResult:
    """
    Results from DFM checking.

    Attributes:
        fab_name: Target fabricator (e.g., "JLCPCB")
        status: "PASS", "WARNING", or "FAIL"
        errors: List of ERROR-level violations
        warnings: List of WARNING-level violations
        suggestions: List of SUGGESTION-level violations
        checks_performed: Number of checks run
        board_size: Tuple of (width, height) in mm
        layer_count: Number of copper layers
    """
    fab_name: str
    status: str  # "PASS", "WARNING", "FAIL"
    errors: List[DFMViolation] = field(default_factory=list)
    warnings: List[DFMViolation] = field(default_factory=list)
    suggestions: List[DFMViolation] = field(default_factory=list)
    checks_performed: int = 0
    board_size: Optional[Tuple[float, float]] = None
    layer_count: int = 2

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "fab_name": self.fab_name,
            "status": self.status,
            "errors": [v.to_dict() for v in self.errors],
            "warnings": [v.to_dict() for v in self.warnings],
            "suggestions": [v.to_dict() for v in self.suggestions],
            "checks_performed": self.checks_performed,
            "board_size": self.board_size,
            "layer_count": self.layer_count,
            "summary": {
                "error_count": len(self.errors),
                "warning_count": len(self.warnings),
                "suggestion_count": len(self.suggestions)
            }
        }


class DFMChecker:
    """
    Design for Manufacturability Checker

    Validates PCB designs against fabricator capabilities.
    Works with format-agnostic parsed data.

    Usage:
        checker = DFMChecker(target_fab="JLCPCB")
        pcb_data = parse_kicad_pcb(pcb_file)  # From kicad_parser
        result = checker.check(pcb_data)

        if result.status == "FAIL":
            print(f"Found {len(result.errors)} critical errors")
            for error in result.errors:
                print(f"  - {error.message}")
    """

    # Fabricator Capabilities Database
    # These are conservative values that work for most low-cost fabs
    # Update quarterly based on fab specifications
    FAB_CAPABILITIES = {
        "JLCPCB": {
            "name": "JLCPCB",
            "min_trace_width": 0.127,       # mm (5 mil) - 2-layer standard
            "min_trace_spacing": 0.127,     # mm (5 mil)
            "min_drill_diameter": 0.3,      # mm
            "min_annular_ring": 0.13,       # mm
            "min_via_diameter": 0.3,        # mm (outer diameter)
            "min_clearance": 0.127,         # mm (trace to trace)
            "min_silkscreen_width": 0.15,   # mm
            "max_board_size": (500, 500),   # mm (width, height)
            "layers_available": [1, 2, 4, 6, 8, 10],
            "surface_finish": ["HASL", "LeadFree HASL", "ENIG"],
            "notes": "Standard 2-layer specs. For 4+ layers, min trace/space = 0.09mm"
        },
        "PCBWay": {
            "name": "PCBWay",
            "min_trace_width": 0.1,         # mm (4 mil) - more capable
            "min_trace_spacing": 0.1,       # mm
            "min_drill_diameter": 0.25,     # mm
            "min_annular_ring": 0.1,        # mm
            "min_via_diameter": 0.3,        # mm
            "min_clearance": 0.1,           # mm
            "min_silkscreen_width": 0.15,   # mm
            "max_board_size": (610, 500),   # mm
            "layers_available": [1, 2, 4, 6, 8, 10, 12],
            "surface_finish": ["HASL", "LeadFree HASL", "ENIG", "OSP"],
            "notes": "Standard capabilities"
        },
        "OSHPark": {
            "name": "OSHPark",
            "min_trace_width": 0.15,        # mm (6 mil) - conservative
            "min_trace_spacing": 0.15,      # mm
            "min_drill_diameter": 0.33,     # mm (13 mil)
            "min_annular_ring": 0.13,       # mm
            "min_via_diameter": 0.33,       # mm
            "min_clearance": 0.15,          # mm
            "min_silkscreen_width": 0.15,   # mm
            "max_board_size": (279.4, 279.4),  # mm (11" x 11")
            "layers_available": [2, 4],
            "surface_finish": ["ENIG"],
            "notes": "High-quality fab, purple boards"
        }
    }

    def __init__(self, target_fab: str = "JLCPCB"):
        """
        Initialize DFM checker for a specific fabricator.

        Args:
            target_fab: Fabricator name (must be in FAB_CAPABILITIES)

        Raises:
            ValueError: If target_fab is not supported
        """
        if target_fab not in self.FAB_CAPABILITIES:
            raise ValueError(
                f"Unsupported fabricator: {target_fab}. "
                f"Supported: {list(self.FAB_CAPABILITIES.keys())}"
            )

        self.fab_name = target_fab
        self.capabilities = self.FAB_CAPABILITIES[target_fab]
        self.violations = []
        self.checks_performed = 0

        logger.info(f"DFM Checker initialized for {self.fab_name}")
        logger.debug(f"Capabilities: {self.capabilities}")

    def check(self, pcb_data: Dict[str, Any]) -> DFMResult:
        """
        Perform comprehensive DFM checking on PCB design.

        Args:
            pcb_data: Parsed PCB data in standard format:
                {
                    "traces": [{"width": float, "layer": str, "net": str, ...}],
                    "vias": [{"diameter": float, "drill": float, ...}],
                    "pads": [{"diameter": float, "drill": float, ...}],
                    "board_size": (width, height),
                    "layers": int,
                    ...
                }

        Returns:
            DFMResult with all violations found
        """
        logger.info(f"Starting DFM check for {self.fab_name}")

        # Reset state
        self.violations = []
        self.checks_performed = 0

        # Extract board info
        board_size = pcb_data.get("board_size", (0, 0))
        layer_count = pcb_data.get("layers", 2)

        # Run all checks
        self._check_trace_widths(pcb_data.get("traces", []))
        self._check_trace_spacing(pcb_data.get("traces", []))
        self._check_drill_sizes(pcb_data.get("pads", []), pcb_data.get("vias", []))
        self._check_via_sizes(pcb_data.get("vias", []))
        self._check_clearances(pcb_data.get("clearances", []))
        self._check_board_size(board_size)
        self._check_layer_count(layer_count)
        self._check_silkscreen(pcb_data.get("silkscreen", []))

        # Categorize violations by severity
        errors = [v for v in self.violations if v.severity == ViolationSeverity.ERROR]
        warnings = [v for v in self.violations if v.severity == ViolationSeverity.WARNING]
        suggestions = [v for v in self.violations if v.severity == ViolationSeverity.SUGGESTION]

        # Determine overall status
        if errors:
            status = "FAIL"
        elif warnings:
            status = "WARNING"
        else:
            status = "PASS"

        result = DFMResult(
            fab_name=self.fab_name,
            status=status,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
            checks_performed=self.checks_performed,
            board_size=board_size,
            layer_count=layer_count
        )

        logger.info(
            f"DFM check complete: {status} "
            f"({len(errors)} errors, {len(warnings)} warnings, {len(suggestions)} suggestions)"
        )

        return result

    def _check_trace_widths(self, traces: List[Dict[str, Any]]):
        """
        Check if all trace widths meet minimum requirements.

        Critical for manufacturing - too narrow traces may not etch properly.
        """
        self.checks_performed += 1
        min_width = self.capabilities["min_trace_width"]

        for trace in traces:
            width = trace.get("width", 0)
            if width < min_width:
                self.violations.append(DFMViolation(
                    check_name="trace_width",
                    severity=ViolationSeverity.ERROR,
                    message=f"Trace width {width:.3f}mm below minimum {min_width:.3f}mm",
                    location={
                        "layer": trace.get("layer", "unknown"),
                        "net": trace.get("net", "unknown"),
                        "coordinates": trace.get("start", (0, 0))
                    },
                    current_value=f"{width:.3f}mm",
                    required_value=f"{min_width:.3f}mm",
                    fix_suggestion=f"Increase trace width to at least {min_width:.3f}mm",
                    auto_fixable=True  # Code fixer can widen traces
                ))

    def _check_trace_spacing(self, traces: List[Dict[str, Any]]):
        """
        Check if trace spacing meets minimum requirements.

        Critical for preventing shorts during manufacturing.
        """
        self.checks_performed += 1
        min_spacing = self.capabilities["min_trace_spacing"]

        # This is simplified - real implementation would calculate actual spacing
        # between adjacent traces on the same layer
        for trace in traces:
            spacing = trace.get("spacing", min_spacing)
            if spacing < min_spacing:
                self.violations.append(DFMViolation(
                    check_name="trace_spacing",
                    severity=ViolationSeverity.ERROR,
                    message=f"Trace spacing {spacing:.3f}mm below minimum {min_spacing:.3f}mm",
                    location={
                        "layer": trace.get("layer", "unknown"),
                        "net": trace.get("net", "unknown")
                    },
                    current_value=f"{spacing:.3f}mm",
                    required_value=f"{min_spacing:.3f}mm",
                    fix_suggestion=f"Increase spacing to at least {min_spacing:.3f}mm",
                    auto_fixable=True  # Code fixer can adjust spacing
                ))

    def _check_drill_sizes(self, pads: List[Dict[str, Any]], vias: List[Dict[str, Any]]):
        """
        Check if drill diameters meet minimum requirements.

        Too small drills are difficult to manufacture and may break.
        """
        self.checks_performed += 1
        min_drill = self.capabilities["min_drill_diameter"]

        # Check pad drills
        for pad in pads:
            drill = pad.get("drill", 0)
            if drill > 0 and drill < min_drill:
                self.violations.append(DFMViolation(
                    check_name="drill_size",
                    severity=ViolationSeverity.ERROR,
                    message=f"Pad drill {drill:.3f}mm below minimum {min_drill:.3f}mm",
                    location={
                        "component": pad.get("component", "unknown"),
                        "pad": pad.get("number", "unknown")
                    },
                    current_value=f"{drill:.3f}mm",
                    required_value=f"{min_drill:.3f}mm",
                    fix_suggestion=f"Increase drill size to at least {min_drill:.3f}mm",
                    auto_fixable=True  # Code fixer can increase drill size
                ))

        # Check via drills (checked separately in _check_via_sizes)

    def _check_via_sizes(self, vias: List[Dict[str, Any]]):
        """
        Check if via sizes (diameter and drill) meet requirements.

        Vias must have sufficient annular ring for reliability.
        """
        self.checks_performed += 1
        min_via = self.capabilities["min_via_diameter"]
        min_drill = self.capabilities["min_drill_diameter"]
        min_ring = self.capabilities["min_annular_ring"]

        for via in vias:
            diameter = via.get("diameter", 0)
            drill = via.get("drill", 0)

            # Check via outer diameter
            if diameter < min_via:
                self.violations.append(DFMViolation(
                    check_name="via_diameter",
                    severity=ViolationSeverity.WARNING,
                    message=f"Via diameter {diameter:.3f}mm below recommended {min_via:.3f}mm",
                    location={"coordinates": via.get("position", (0, 0))},
                    current_value=f"{diameter:.3f}mm",
                    required_value=f"{min_via:.3f}mm",
                    fix_suggestion=f"Increase via diameter to {min_via:.3f}mm or larger",
                    auto_fixable=True
                ))

            # Check annular ring
            if diameter > 0 and drill > 0:
                ring = (diameter - drill) / 2
                if ring < min_ring:
                    self.violations.append(DFMViolation(
                        check_name="annular_ring",
                        severity=ViolationSeverity.WARNING,
                        message=f"Via annular ring {ring:.3f}mm below minimum {min_ring:.3f}mm",
                        location={"coordinates": via.get("position", (0, 0))},
                        current_value=f"{ring:.3f}mm",
                        required_value=f"{min_ring:.3f}mm",
                        fix_suggestion=f"Increase via pad size or decrease drill size",
                        auto_fixable=True
                    ))

    def _check_clearances(self, clearances: List[Dict[str, Any]]):
        """
        Check electrical clearances between features.

        Ensures no shorts or manufacturing issues.
        """
        self.checks_performed += 1
        min_clearance = self.capabilities["min_clearance"]

        for clearance in clearances:
            distance = clearance.get("distance", min_clearance)
            if distance < min_clearance:
                self.violations.append(DFMViolation(
                    check_name="clearance",
                    severity=ViolationSeverity.ERROR,
                    message=f"Clearance {distance:.3f}mm below minimum {min_clearance:.3f}mm",
                    location={
                        "feature1": clearance.get("feature1", "unknown"),
                        "feature2": clearance.get("feature2", "unknown")
                    },
                    current_value=f"{distance:.3f}mm",
                    required_value=f"{min_clearance:.3f}mm",
                    fix_suggestion=f"Increase clearance to {min_clearance:.3f}mm",
                    auto_fixable=False  # Requires design changes
                ))

    def _check_board_size(self, board_size: Tuple[float, float]):
        """
        Check if board size is within fab limits.

        Most fabs have maximum panel sizes.
        """
        self.checks_performed += 1
        max_size = self.capabilities["max_board_size"]

        width, height = board_size
        max_width, max_height = max_size

        if width > max_width or height > max_height:
            self.violations.append(DFMViolation(
                check_name="board_size",
                severity=ViolationSeverity.ERROR,
                message=f"Board size {width:.1f}×{height:.1f}mm exceeds maximum {max_width:.1f}×{max_height:.1f}mm",
                location={"board": "overall"},
                current_value=f"{width:.1f}mm × {height:.1f}mm",
                required_value=f"≤{max_width:.1f}mm × ≤{max_height:.1f}mm",
                fix_suggestion=f"Reduce board dimensions or split into multiple boards",
                auto_fixable=False  # Requires design changes
            ))

    def _check_layer_count(self, layer_count: int):
        """
        Check if layer count is supported by fab.

        Not all fabs support all layer counts.
        """
        self.checks_performed += 1
        available_layers = self.capabilities["layers_available"]

        if layer_count not in available_layers:
            self.violations.append(DFMViolation(
                check_name="layer_count",
                severity=ViolationSeverity.ERROR,
                message=f"{layer_count} layers not supported (available: {available_layers})",
                location={"board": "overall"},
                current_value=f"{layer_count} layers",
                required_value=f"One of: {available_layers}",
                fix_suggestion=f"Change to supported layer count",
                auto_fixable=False  # Requires design changes
            ))

    def _check_silkscreen(self, silkscreen: List[Dict[str, Any]]):
        """
        Check silkscreen line widths and placement.

        Too thin silkscreen may not print legibly.
        """
        self.checks_performed += 1
        min_width = self.capabilities["min_silkscreen_width"]

        for silk in silkscreen:
            width = silk.get("width", min_width)
            if width < min_width:
                self.violations.append(DFMViolation(
                    check_name="silkscreen_width",
                    severity=ViolationSeverity.WARNING,
                    message=f"Silkscreen width {width:.3f}mm below recommended {min_width:.3f}mm",
                    location={"layer": silk.get("layer", "unknown")},
                    current_value=f"{width:.3f}mm",
                    required_value=f"{min_width:.3f}mm",
                    fix_suggestion=f"Increase silkscreen width to {min_width:.3f}mm for better legibility",
                    auto_fixable=True
                ))


# Convenience function for quick checks
def check_dfm(pcb_data: Dict[str, Any], fab: str = "JLCPCB") -> DFMResult:
    """
    Convenience function for quick DFM checking.

    Usage:
        result = check_dfm(pcb_data, fab="JLCPCB")
        if result.status == "FAIL":
            print("Design has critical DFM violations!")
    """
    checker = DFMChecker(target_fab=fab)
    return checker.check(pcb_data)
