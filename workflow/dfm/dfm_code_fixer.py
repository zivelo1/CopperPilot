# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
DFM Code Fixer - Automated Fixes for DFM Violations
====================================================

Automatically fixes common DFM violations that don't require design changes.

Capabilities:
- Widen narrow traces to meet minimum width requirements
- Increase via diameters to meet minimum size
- Increase drill sizes to meet minimum diameter
- Adjust spacing (where possible without design changes)
- Update silkscreen widths

Limitations:
- Cannot fix violations requiring layout changes (clearances, board size)
- Cannot fix violations requiring design decisions (layer count)
- Works on parsed PCB data, then writes back to file

Integration:
- Called after DFM checking finds violations
- Attempts fixes on auto-fixable violations only
- Re-validates after fixes to ensure compliance

Author: CopperPilot Development Team
Created: November 9, 2025
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
import logging
import copy

from .dfm_checker import DFMChecker, DFMResult, DFMViolation, ViolationSeverity

logger = logging.getLogger(__name__)


class DFMCodeFixer:
    """
    Automated fixer for DFM violations.

    Usage:
        fixer = DFMCodeFixer(target_fab="JLCPCB")

        # Get DFM violations
        checker = DFMChecker(target_fab="JLCPCB")
        result = checker.check(pcb_data)

        # Attempt automatic fixes
        if result.errors:
            fixed_data, fix_report = fixer.fix(pcb_data, result)

            # Re-validate
            new_result = checker.check(fixed_data)
    """

    def __init__(self, target_fab: str = "JLCPCB"):
        """
        Initialize DFM code fixer.

        Args:
            target_fab: Target fabricator (must match DFMChecker)
        """
        self.fab_name = target_fab
        self.checker = DFMChecker(target_fab=target_fab)
        self.capabilities = self.checker.capabilities
        self.logger = logger

    def fix(self, pcb_data: Dict[str, Any], dfm_result: DFMResult) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Attempt to automatically fix DFM violations.

        Args:
            pcb_data: Original PCB data (will not be modified)
            dfm_result: DFM check results with violations

        Returns:
            Tuple of (fixed_pcb_data, fix_report):
            - fixed_pcb_data: Modified PCB data with fixes applied
            - fix_report: Dictionary with fix statistics and details
        """
        logger.info(f"Starting DFM auto-fix for {len(dfm_result.errors)} errors, {len(dfm_result.warnings)} warnings")

        # Deep copy to avoid modifying original
        fixed_data = copy.deepcopy(pcb_data)

        # Track fixes
        fixes_applied = []
        fixes_failed = []

        # Combine errors and warnings that are auto-fixable
        fixable_violations = [
            v for v in (dfm_result.errors + dfm_result.warnings)
            if v.auto_fixable
        ]

        logger.info(f"Found {len(fixable_violations)} auto-fixable violations")

        # Apply fixes by type
        for violation in fixable_violations:
            try:
                success = self._apply_fix(fixed_data, violation)
                if success:
                    fixes_applied.append({
                        "check": violation.check_name,
                        "severity": violation.severity.value,
                        "message": violation.message,
                        "fix": violation.fix_suggestion
                    })
                else:
                    fixes_failed.append({
                        "check": violation.check_name,
                        "message": violation.message,
                        "reason": "Fix logic returned False"
                    })
            except Exception as e:
                logger.error(f"Error fixing {violation.check_name}: {str(e)}")
                fixes_failed.append({
                    "check": violation.check_name,
                    "message": violation.message,
                    "reason": str(e)
                })

        # Generate fix report
        fix_report = {
            "total_violations": len(fixable_violations),
            "fixes_applied": len(fixes_applied),
            "fixes_failed": len(fixes_failed),
            "success_rate": len(fixes_applied) / len(fixable_violations) * 100 if fixable_violations else 0,
            "details": {
                "applied": fixes_applied,
                "failed": fixes_failed
            }
        }

        logger.info(
            f"Auto-fix complete: {len(fixes_applied)}/{len(fixable_violations)} fixes applied "
            f"({fix_report['success_rate']:.1f}% success rate)"
        )

        return fixed_data, fix_report

    def _apply_fix(self, pcb_data: Dict[str, Any], violation: DFMViolation) -> bool:
        """
        Apply specific fix based on violation type.

        Args:
            pcb_data: PCB data to modify (modified in-place)
            violation: The violation to fix

        Returns:
            True if fix was successfully applied, False otherwise
        """
        check_name = violation.check_name

        if check_name == "trace_width":
            return self._fix_trace_width(pcb_data, violation)
        elif check_name == "via_diameter":
            return self._fix_via_diameter(pcb_data, violation)
        elif check_name == "drill_size":
            return self._fix_drill_size(pcb_data, violation)
        elif check_name == "annular_ring":
            return self._fix_annular_ring(pcb_data, violation)
        elif check_name == "silkscreen_width":
            return self._fix_silkscreen_width(pcb_data, violation)
        elif check_name == "trace_spacing":
            return self._fix_trace_spacing(pcb_data, violation)
        else:
            logger.warning(f"No fix logic for check: {check_name}")
            return False

    def _fix_trace_width(self, pcb_data: Dict[str, Any], violation: DFMViolation) -> bool:
        """
        Fix trace width violation by widening traces.

        Increases all traces below minimum width to the minimum required width.
        """
        min_width = self.capabilities["min_trace_width"]
        fixed_count = 0

        traces = pcb_data.get("traces", [])
        for trace in traces:
            if trace.get("width", 0) < min_width:
                trace["width"] = min_width
                fixed_count += 1

        logger.debug(f"Widened {fixed_count} traces to {min_width}mm")
        return fixed_count > 0

    def _fix_via_diameter(self, pcb_data: Dict[str, Any], violation: DFMViolation) -> bool:
        """
        Fix via diameter violation by increasing via size.

        Increases all vias below minimum diameter to the minimum required size.
        """
        min_diameter = self.capabilities["min_via_diameter"]
        fixed_count = 0

        vias = pcb_data.get("vias", [])
        for via in vias:
            if via.get("diameter", 0) < min_diameter:
                via["diameter"] = min_diameter
                fixed_count += 1

        logger.debug(f"Increased {fixed_count} via diameters to {min_diameter}mm")
        return fixed_count > 0

    def _fix_drill_size(self, pcb_data: Dict[str, Any], violation: DFMViolation) -> bool:
        """
        Fix drill size violation by increasing drill diameter.

        Increases all drills below minimum to the minimum required diameter.
        """
        min_drill = self.capabilities["min_drill_diameter"]
        fixed_count = 0

        # Fix pad drills
        pads = pcb_data.get("pads", [])
        for pad in pads:
            drill = pad.get("drill", 0)
            if drill > 0 and drill < min_drill:
                pad["drill"] = min_drill
                fixed_count += 1

        # Fix via drills
        vias = pcb_data.get("vias", [])
        for via in vias:
            drill = via.get("drill", 0)
            if drill > 0 and drill < min_drill:
                via["drill"] = min_drill
                fixed_count += 1

        logger.debug(f"Increased {fixed_count} drill sizes to {min_drill}mm")
        return fixed_count > 0

    def _fix_annular_ring(self, pcb_data: Dict[str, Any], violation: DFMViolation) -> bool:
        """
        Fix annular ring violation by increasing via diameter.

        Ensures via pad is large enough to provide minimum annular ring.
        """
        min_ring = self.capabilities["min_annular_ring"]
        fixed_count = 0

        vias = pcb_data.get("vias", [])
        for via in vias:
            diameter = via.get("diameter", 0)
            drill = via.get("drill", 0)

            if diameter > 0 and drill > 0:
                current_ring = (diameter - drill) / 2
                if current_ring < min_ring:
                    # Increase diameter to achieve minimum ring
                    via["diameter"] = drill + (2 * min_ring)
                    fixed_count += 1

        logger.debug(f"Fixed annular ring on {fixed_count} vias")
        return fixed_count > 0

    def _fix_silkscreen_width(self, pcb_data: Dict[str, Any], violation: DFMViolation) -> bool:
        """
        Fix silkscreen width violation by increasing line width.

        Increases all silkscreen lines below minimum to recommended width.
        """
        min_width = self.capabilities["min_silkscreen_width"]
        fixed_count = 0

        silkscreen = pcb_data.get("silkscreen", [])
        for silk in silkscreen:
            if silk.get("width", 0) < min_width:
                silk["width"] = min_width
                fixed_count += 1

        logger.debug(f"Increased {fixed_count} silkscreen widths to {min_width}mm")
        return fixed_count > 0

    def _fix_trace_spacing(self, pcb_data: Dict[str, Any], violation: DFMViolation) -> bool:
        """
        Fix trace spacing violation.

        NOTE: This is complex and requires layout changes.
        For now, we just log and return False - manual intervention needed.
        """
        logger.warning("Trace spacing violations require manual layout changes")
        return False

    def fix_and_validate(self, pcb_data: Dict[str, Any]) -> tuple[Dict[str, Any], DFMResult, Dict[str, Any]]:
        """
        Comprehensive fix-and-validate cycle.

        1. Check PCB for DFM violations
        2. Apply automatic fixes
        3. Re-validate to confirm fixes worked
        4. Return fixed data and final validation results

        Args:
            pcb_data: Original PCB data

        Returns:
            Tuple of (fixed_data, final_result, fix_report)
        """
        logger.info("Starting fix-and-validate cycle")

        # Initial check
        initial_result = self.checker.check(pcb_data)
        logger.info(
            f"Initial check: {len(initial_result.errors)} errors, "
            f"{len(initial_result.warnings)} warnings"
        )

        # Apply fixes
        fixed_data, fix_report = self.fix(pcb_data, initial_result)

        # Re-validate
        final_result = self.checker.check(fixed_data)
        logger.info(
            f"After fixes: {len(final_result.errors)} errors, "
            f"{len(final_result.warnings)} warnings"
        )

        # Update fix report with before/after comparison
        fix_report["before"] = {
            "errors": len(initial_result.errors),
            "warnings": len(initial_result.warnings),
            "status": initial_result.status
        }
        fix_report["after"] = {
            "errors": len(final_result.errors),
            "warnings": len(final_result.warnings),
            "status": final_result.status
        }
        fix_report["improvement"] = {
            "errors_fixed": len(initial_result.errors) - len(final_result.errors),
            "warnings_fixed": len(initial_result.warnings) - len(final_result.warnings)
        }

        return fixed_data, final_result, fix_report


# Convenience function
def auto_fix_dfm(pcb_data: Dict[str, Any], fab: str = "JLCPCB") -> tuple[Dict[str, Any], DFMResult, Dict[str, Any]]:
    """
    Convenience function for one-shot DFM fix-and-validate.

    Usage:
        fixed_data, result, report = auto_fix_dfm(pcb_data, fab="JLCPCB")

        if result.status == "PASS":
            print(f"✅ All DFM issues fixed! ({report['fixes_applied']} fixes applied)")
        else:
            print(f"⚠️ {len(result.errors)} errors remain after auto-fix")
    """
    fixer = DFMCodeFixer(target_fab=fab)
    return fixer.fix_and_validate(pcb_data)
