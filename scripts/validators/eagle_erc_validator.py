#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle ERC Validator - Standalone Electrical Rule Check Validator
=================================================================

MODULAR, STANDALONE, REUSABLE validator for Eagle .sch files.

Features:
- Can be run standalone from CLI
- Can be imported and used programmatically
- Validates actual generated .sch files
- Produces standardized .erc.rpt reports
- Works independently of eagle_converter.py

Usage:
  # CLI mode:
  python3 eagle_erc_validator.py path/to/file.sch

  # Programmatic mode:
  from validators.eagle_erc_validator import EagleERCValidator
  validator = EagleERCValidator()
  passed, errors = validator.validate("file.sch")

Author: Claude Code (2025-11-11)
Version: 1.0.0
"""

import sys
import argparse
from pathlib import Path
from typing import Tuple, List
import xml.etree.ElementTree as ET

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eagle.eagle_geometric_validator import GeometricValidator
from eagle.eagle_symbol_library import EagleSymbolLibrary


class EagleERCValidator:
    """
    Standalone ERC validator for Eagle schematic files.

    Validates:
    - Geometric accuracy: Wire endpoints match pin positions
    - Electrical connectivity: All pins properly connected
    - Component placement: No floating components
    - Net integrity: All nets properly formed
    """

    def __init__(self, symbol_library=None):
        """
        Initialize ERC validator.

        Args:
            symbol_library: Optional EagleSymbolLibrary instance. If None, creates default.
        """
        self.symbol_library = symbol_library or EagleSymbolLibrary()

    def validate(self, sch_file: str, output_report: str = None) -> Tuple[bool, List[str]]:
        """
        Validate an Eagle schematic file.

        Args:
            sch_file: Path to .sch file to validate
            output_report: Optional path for .erc.rpt file. If None, auto-generates.

        Returns:
            Tuple of (passed: bool, errors: List[str])
            - passed: True if validation passes, False otherwise
            - errors: List of error messages
        """
        sch_path = Path(sch_file)
        errors = []

        # Validate file exists
        if not sch_path.exists():
            errors.append(f"Schematic file not found: {sch_path}")
            return (False, errors)

        # Use GeometricValidator for comprehensive validation
        validator = GeometricValidator(self.symbol_library)

        try:
            validation_passed = validator.validate_schematic_file(str(sch_path))

            # Determine report path
            if output_report is None:
                # Auto-generate: place report next to .sch file in ERC/ subdirectory
                erc_dir = sch_path.parent / "ERC"
                erc_dir.mkdir(exist_ok=True)
                report_path = erc_dir / f"{sch_path.stem}.erc.rpt"
            else:
                report_path = Path(output_report)
                report_path.parent.mkdir(parents=True, exist_ok=True)

            # Write standardized report
            self._write_report(sch_path, validator, validation_passed, report_path)

            # Extract error messages
            if not validation_passed:
                for err in validator.errors:
                    errors.append(str(err))

            return (validation_passed, errors)

        except Exception as e:
            errors.append(f"ERC validation exception: {e}")
            return (False, errors)

    def _write_report(self, sch_path: Path, validator, passed: bool, report_path: Path):
        """Write standardized ERC report."""
        with open(report_path, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("EAGLE ERC REPORT\n")
            f.write("=" * 80 + "\n")
            f.write(f"File: {sch_path.name}\n")
            f.write(f"Path: {sch_path}\n")
            f.write(f"Validator: GeometricValidator (eagle_geometric_validator.py)\n")
            f.write("=" * 80 + "\n\n")

            if passed:
                f.write("Status: ✅ PASSED\n\n")
                if validator.warnings:
                    f.write(f"Warnings: {len(validator.warnings)}\n\n")
                    f.write("WARNINGS:\n")
                    for warn in validator.warnings:
                        f.write(f"  - {warn}\n")
                else:
                    f.write("No errors or warnings found.\n")
                    f.write("Geometric accuracy verified.\n")
            else:
                f.write("Status: ❌ FAILED\n\n")
                f.write(f"Errors: {len(validator.errors)}\n")
                f.write(f"Warnings: {len(validator.warnings)}\n\n")

                if validator.errors:
                    f.write("ERRORS:\n")
                    for err in validator.errors:
                        f.write(f"  - {err}\n")
                    f.write("\n")

                if validator.warnings:
                    f.write("WARNINGS:\n")
                    for warn in validator.warnings:
                        f.write(f"  - {warn}\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write(f"Report saved: {report_path}\n")
            f.write("=" * 80 + "\n")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Eagle ERC Validator - Standalone Electrical Rule Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate single file
  python3 eagle_erc_validator.py schematic.sch

  # Validate with custom report location
  python3 eagle_erc_validator.py schematic.sch -o /path/to/report.erc.rpt

  # Validate multiple files
  python3 eagle_erc_validator.py *.sch
        """
    )

    parser.add_argument(
        'schematic',
        nargs='+',
        help='Path(s) to Eagle .sch file(s) to validate'
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

    args = parser.parse_args()

    # Initialize validator
    validator = EagleERCValidator()

    # Track results
    total_files = len(args.schematic)
    passed_files = 0
    failed_files = 0

    print("=" * 80)
    print("EAGLE ERC VALIDATOR - STANDALONE MODE")
    print("=" * 80)
    print(f"Files to validate: {total_files}\n")

    # Validate each file
    for sch_file in args.schematic:
        print(f"Validating: {sch_file}")

        # Use custom output only for single file
        output_report = args.output if total_files == 1 else None

        passed, errors = validator.validate(sch_file, output_report)

        if passed:
            passed_files += 1
            warnings_count = len(errors) if errors else 0
            if warnings_count > 0:
                print(f"  ✅ PASSED with {warnings_count} warning(s)")
            else:
                print(f"  ✅ PASSED")
        else:
            failed_files += 1
            print(f"  ❌ FAILED with {len(errors)} error(s)")
            if args.verbose and errors:
                for err in errors[:5]:  # Show first 5 errors
                    print(f"     - {err}")
                if len(errors) > 5:
                    print(f"     ... and {len(errors) - 5} more errors")
        print()

    # Summary
    print("=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print(f"Total files:  {total_files}")
    print(f"Passed:       {passed_files} ({passed_files/total_files*100:.1f}%)")
    print(f"Failed:       {failed_files} ({failed_files/total_files*100:.1f}%)")
    print("=" * 80)

    # Exit code: 0 if all passed, 1 if any failed
    sys.exit(0 if failed_files == 0 else 1)


if __name__ == "__main__":
    main()
