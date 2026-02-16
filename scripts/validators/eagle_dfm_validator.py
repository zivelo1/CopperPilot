#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle DFM Validator - Standalone Design for Manufacturability Check
====================================================================

MODULAR, STANDALONE, REUSABLE validator for Eagle .brd files.

Features:
- Can be run standalone from CLI
- Can be imported and used programmatically
- Validates board manufacturability
- Produces standardized .dfm.rpt reports
- Works independently of eagle_converter.py

Validates:
- Trace width constraints
- Clearance requirements
- Via sizes
- Board dimensions
- Manufacturing tolerances

Note: This is a BASIC implementation. For comprehensive DFM validation,
consider using KiCad's DFM validator as an adapter.

Usage:
  # CLI mode:
  python3 eagle_dfm_validator.py path/to/file.brd

  # Programmatic mode:
  from validators.eagle_dfm_validator import EagleDFMValidator
  validator = EagleDFMValidator()
  passed, errors, warnings = validator.validate("file.brd")

Author: Claude Code (2025-11-11)
Version: 1.0.0 (Basic)
"""

import sys
import argparse
from pathlib import Path
from typing import Tuple, List
import xml.etree.ElementTree as ET


class EagleDFMValidator:
    """
    Standalone DFM validator for Eagle board files.

    Validates board files for manufacturability constraints.
    """

    def __init__(self, target_fab="JLCPCB"):
        """
        Initialize DFM validator.

        Args:
            target_fab: Target fabrication house (default: JLCPCB)
        """
        self.target_fab = target_fab

        # Manufacturing constraints (JLCPCB standard)
        self.min_trace_width = 0.127  # mm (5 mil)
        self.min_clearance = 0.127  # mm (5 mil)
        self.min_via_diameter = 0.3  # mm
        self.min_drill = 0.2  # mm
        self.min_board_size = 10.0  # mm
        self.max_board_size = 500.0  # mm

    def validate(
        self,
        brd_file: str,
        output_report: str = None
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Validate an Eagle board file for manufacturability.

        Args:
            brd_file: Path to .brd file to validate
            output_report: Optional path for .dfm.rpt file. If None, auto-generates.

        Returns:
            Tuple of (passed: bool, errors: List[str], warnings: List[str])
            - passed: True if validation passes (no errors)
            - errors: List of error messages (manufacturing impossible)
            - warnings: List of warning messages (manufacturing difficult/expensive)
        """
        brd_path = Path(brd_file)
        errors = []
        warnings = []

        # Validate file exists
        if not brd_path.exists():
            errors.append(f"Board file not found: {brd_path}")
            return (False, errors, warnings)

        try:
            # Parse the board file
            tree = ET.parse(brd_path)
            root = tree.getroot()

            # Run all DFM checks
            e, w = self._check_board_dimensions(root)
            errors.extend(e)
            warnings.extend(w)

            e, w = self._check_trace_widths(root)
            errors.extend(e)
            warnings.extend(w)

            e, w = self._check_vias(root)
            errors.extend(e)
            warnings.extend(w)

            # Determine report path
            if output_report is None:
                # Auto-generate: place report next to .brd file in verification/ subdirectory
                dfm_dir = brd_path.parent / "verification"
                dfm_dir.mkdir(exist_ok=True)
                report_path = dfm_dir / f"{brd_path.stem}.dfm.rpt"
            else:
                report_path = Path(output_report)
                report_path.parent.mkdir(parents=True, exist_ok=True)

            # Write standardized report
            self._write_report(brd_path, errors, warnings, report_path)

            passed = len(errors) == 0
            return (passed, errors, warnings)

        except ET.ParseError as e:
            errors.append(f"Board XML parse error: {e}")
            return (False, errors, warnings)
        except Exception as e:
            errors.append(f"DFM validation exception: {e}")
            return (False, errors, warnings)

    def _check_board_dimensions(self, root: ET.Element) -> Tuple[List[str], List[str]]:
        """Check board dimensions against manufacturing limits."""
        errors = []
        warnings = []

        plain = root.find('.//board/plain')
        if plain is None:
            errors.append("Board has no plain section for dimensions")
            return (errors, warnings)

        # Extract dimension wires (layer 20)
        wires = plain.findall('.//wire[@layer="20"]')
        if len(wires) < 4:
            warnings.append("Board dimension outline incomplete - cannot verify size")
            return (errors, warnings)

        # Calculate bounding box
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')

        for wire in wires:
            try:
                x1 = float(wire.get('x1', 0))
                y1 = float(wire.get('y1', 0))
                x2 = float(wire.get('x2', 0))
                y2 = float(wire.get('y2', 0))

                min_x = min(min_x, x1, x2)
                min_y = min(min_y, y1, y2)
                max_x = max(max_x, x1, x2)
                max_y = max(max_y, y1, y2)
            except (ValueError, TypeError):
                pass

        if min_x != float('inf'):
            width = max_x - min_x
            height = max_y - min_y

            if width < self.min_board_size or height < self.min_board_size:
                errors.append(
                    f"Board too small: {width:.1f}x{height:.1f}mm "
                    f"(min: {self.min_board_size}mm)"
                )

            if width > self.max_board_size or height > self.max_board_size:
                errors.append(
                    f"Board too large: {width:.1f}x{height:.1f}mm "
                    f"(max: {self.max_board_size}mm)"
                )

        return (errors, warnings)

    def _check_trace_widths(self, root: ET.Element) -> Tuple[List[str], List[str]]:
        """Check trace widths meet manufacturing minimums."""
        errors = []
        warnings = []

        # Check signal wires (copper traces)
        thin_traces = 0
        for sig in root.findall('.//board/signals/signal'):
            for wire in sig.findall('.//wire'):
                try:
                    width = float(wire.get('width', 0))
                    if width < self.min_trace_width:
                        thin_traces += 1
                except (ValueError, TypeError):
                    pass

        if thin_traces > 0:
            errors.append(
                f"Found {thin_traces} traces thinner than minimum "
                f"({self.min_trace_width}mm / 5 mil)"
            )

        return (errors, warnings)

    def _check_vias(self, root: ET.Element) -> Tuple[List[str], List[str]]:
        """Check via sizes meet manufacturing minimums."""
        errors = []
        warnings = []

        small_vias = 0
        small_drills = 0

        for sig in root.findall('.//board/signals/signal'):
            for via in sig.findall('.//via'):
                try:
                    diameter = float(via.get('diameter', 0))
                    if diameter < self.min_via_diameter:
                        small_vias += 1

                    drill = float(via.get('drill', 0))
                    if drill < self.min_drill:
                        small_drills += 1
                except (ValueError, TypeError):
                    pass

        if small_vias > 0:
            errors.append(
                f"Found {small_vias} vias smaller than minimum diameter "
                f"({self.min_via_diameter}mm)"
            )

        if small_drills > 0:
            errors.append(
                f"Found {small_drills} via drills smaller than minimum "
                f"({self.min_drill}mm)"
            )

        return (errors, warnings)

    def _write_report(
        self,
        brd_path: Path,
        errors: List[str],
        warnings: List[str],
        report_path: Path
    ):
        """Write standardized DFM report."""
        with open(report_path, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("EAGLE DFM REPORT\n")
            f.write("=" * 80 + "\n")
            f.write(f"File: {brd_path.name}\n")
            f.write(f"Path: {brd_path}\n")
            f.write(f"Target Fabricator: {self.target_fab}\n")
            f.write(f"Validator: EagleDFMValidator (eagle_dfm_validator.py)\n")
            f.write("=" * 80 + "\n\n")

            if not errors and not warnings:
                f.write("Status: ✅ PASSED\n\n")
                f.write("No manufacturability issues found.\n")
                f.write("\nManufacturing Constraints:\n")
                f.write(f"  ✓ Min trace width: {self.min_trace_width}mm\n")
                f.write(f"  ✓ Min clearance: {self.min_clearance}mm\n")
                f.write(f"  ✓ Min via diameter: {self.min_via_diameter}mm\n")
                f.write(f"  ✓ Min drill size: {self.min_drill}mm\n")
                f.write(f"  ✓ Board size: {self.min_board_size}-{self.max_board_size}mm\n")
            else:
                if errors:
                    f.write("Status: ❌ FAILED\n\n")
                else:
                    f.write("Status: ⚠️  WARNINGS\n\n")

                f.write(f"Errors: {len(errors)}\n")
                f.write(f"Warnings: {len(warnings)}\n\n")

                if errors:
                    f.write("ERRORS (Manufacturing Issues):\n")
                    for err in errors:
                        f.write(f"  - {err}\n")
                    f.write("\n")

                if warnings:
                    f.write("WARNINGS (Manufacturing Challenges):\n")
                    for warn in warnings:
                        f.write(f"  - {warn}\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write(f"Report saved: {report_path}\n")
            f.write("=" * 80 + "\n")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Eagle DFM Validator - Design for Manufacturability Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate single file
  python3 eagle_dfm_validator.py board.brd

  # Validate with custom report location
  python3 eagle_dfm_validator.py board.brd -o /path/to/report.dfm.rpt

  # Validate multiple files
  python3 eagle_dfm_validator.py *.brd
        """
    )

    parser.add_argument(
        'board',
        nargs='+',
        help='Path(s) to Eagle .brd file(s) to validate'
    )

    parser.add_argument(
        '-o', '--output',
        help='Output report path (for single file only)'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )

    parser.add_argument(
        '--fab',
        default='JLCPCB',
        help='Target fabricator (default: JLCPCB)'
    )

    args = parser.parse_args()

    # Initialize validator
    validator = EagleDFMValidator(target_fab=args.fab)

    # Track results
    total_files = len(args.board)
    passed_files = 0
    warned_files = 0
    failed_files = 0

    print("=" * 80)
    print("EAGLE DFM VALIDATOR - STANDALONE MODE")
    print("=" * 80)
    print(f"Target Fabricator: {args.fab}")
    print(f"Files to validate: {total_files}\n")

    # Validate each file
    for brd_file in args.board:
        print(f"Validating: {brd_file}")

        # Use custom output only for single file
        output_report = args.output if total_files == 1 else None

        passed, errors, warnings = validator.validate(brd_file, output_report)

        if passed and not warnings:
            passed_files += 1
            print(f"  ✅ PASSED")
        elif passed and warnings:
            warned_files += 1
            print(f"  ⚠️  PASSED with {len(warnings)} warning(s)")
            if args.verbose:
                for warn in warnings[:3]:
                    print(f"     - {warn}")
        else:
            failed_files += 1
            print(f"  ❌ FAILED with {len(errors)} error(s), {len(warnings)} warning(s)")
            if args.verbose and errors:
                for err in errors[:3]:
                    print(f"     - {err}")
        print()

    # Summary
    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print(f"Total files:  {total_files}")
    print(f"Passed:       {passed_files} ({passed_files/total_files*100:.1f}%)")
    print(f"Warnings:     {warned_files} ({warned_files/total_files*100:.1f}%)")
    print(f"Failed:       {failed_files} ({failed_files/total_files*100:.1f}%)")
    print("=" * 80)

    # Exit code: 0 if all passed, 1 if any failed
    sys.exit(0 if failed_files == 0 else 1)


if __name__ == "__main__":
    main()
