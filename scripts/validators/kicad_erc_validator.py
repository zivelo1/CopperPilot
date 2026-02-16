#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad ERC (Electrical Rules Check) Validator - Modular Script

PURPOSE:
    Validates KiCad schematic files for electrical rule violations.
    Runs kicad-cli ERC and parses the results.

USAGE:
    python kicad_erc_validator.py <schematic_file.kicad_sch> [output_dir]

OUTPUTS:
    - ERC report file (.erc.rpt)
    - JSON results file with error counts
    - Exit code: 0 = pass, 1 = errors found, 2 = validation failed

GENERIC:
    Works for ANY KiCad schematic, ANY circuit type, ANY complexity.

AUTHOR: CopperPilot AI Circuit Design Platform
DATE: 2025-11-10
VERSION: 1.0 - Modular refactoring
"""

import sys
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Tuple
from datetime import datetime


class KiCadERCValidator:
    """
    Validates KiCad schematic files for electrical rule violations.

    GENERIC: Works for any circuit type, any ERC violation pattern.
    MODULAR: Standalone script that can be called independently.

    TC #52 FIX 3.1 (2025-11-26): Added EXPECTED_WARNINGS list for multi-board designs.
    Global labels that connect across circuits will appear as "dangling" when
    validated individually - this is expected behavior, not an error.
    """

    # ═══════════════════════════════════════════════════════════════════════
    # TC #52 FIX 3.1 (2025-11-26): Expected ERC warnings for multi-board designs
    # ═══════════════════════════════════════════════════════════════════════
    # These warning types are EXPECTED in CopperPilot's multi-board architecture
    # and should NOT count as errors. Global labels connect circuits together,
    # so they naturally appear "dangling" when each circuit is validated alone.
    # ═══════════════════════════════════════════════════════════════════════
    EXPECTED_WARNINGS = {
        'global_label_dangling',  # Global labels are inter-circuit connectors
        'label_dangling',         # Some labels may be output-only
    }

    # ═══════════════════════════════════════════════════════════════════════
    # TC #69 FIX (2025-12-07): CRITICAL WARNINGS - Require Attention
    # ═══════════════════════════════════════════════════════════════════════
    # These warning types indicate REAL problems with net connectivity that
    # should NOT be ignored. While KiCad classifies them as "warnings", they
    # indicate data integrity issues that will cause problems downstream.
    #
    # CRITICAL: These warnings should trigger investigation even if ERC "passes".
    # ═══════════════════════════════════════════════════════════════════════
    CRITICAL_WARNINGS = {
        'multiple_net_names',     # Two nets merged - indicates wire collision or topology error
        'pin_not_connected',      # Unconnected pin - may be intentional but should be verified
        'power_pin_not_driven',   # Power pin without source - serious issue
        'wire_dangling',          # Wire not connected to anything - grid alignment issue
    }

    def __init__(self, schematic_file: Path, output_dir: Path = None):
        """
        Initialize ERC validator.

        Args:
            schematic_file: Path to .kicad_sch file
            output_dir: Optional directory for reports (defaults to schematic_file.parent/ERC)
        """
        self.schematic_file = Path(schematic_file)

        # Default output directory: same folder as schematic, under ERC/
        if output_dir is None:
            self.output_dir = self.schematic_file.parent / "ERC"
        else:
            self.output_dir = Path(output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # KiCad CLI path (can be overridden via environment variable)
        import os
        self.kicad_cli = Path(os.environ.get(
            'KICAD_CLI_PATH',
            '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli'
        ))

        # Results storage
        # TC #69: Added critical_warnings tracking
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'schematic': str(self.schematic_file),
            'erc_errors': 0,
            'erc_warnings': 0,
            'erc_critical_warnings': 0,  # TC #69: Track warnings that need attention
            'kicad_cli_available': self.kicad_cli.exists(),
            'validation_passed': False,
            'needs_attention': False,    # TC #69: True if critical warnings present
            'report_file': None,
            'error_details': [],
            'critical_warning_details': []  # TC #69: List of critical warnings
        }

    def validate(self) -> Tuple[bool, int]:
        """
        Run ERC validation.

        Returns:
            Tuple[bool, int]: (validation_passed, error_count)

        GENERIC: Works for any schematic, any ERC error type.
        """
        print(f"📋 ERC Validation: {self.schematic_file.name}")
        print(f"   Output: {self.output_dir}/")

        # Check if schematic exists
        if not self.schematic_file.exists():
            print(f"   ❌ ERROR: Schematic file not found")
            self.results['error_details'].append("Schematic file not found")
            return False, 999

        # Check if KiCad CLI is available
        if not self.kicad_cli.exists():
            print(f"   ⚠️  WARNING: KiCad CLI not found at {self.kicad_cli}")
            print(f"   OFFLINE MODE: Parsing existing reports only")
            return self._parse_existing_report()

        # Run ERC via kicad-cli
        return self._run_kicad_erc()

    def _run_kicad_erc(self) -> Tuple[bool, int]:
        """
        Execute kicad-cli ERC command and parse results.

        Returns:
            Tuple[bool, int]: (validation_passed, error_count)

        GENERIC: Handles all ERC output formats, all error types.
        """
        report_file = self.output_dir / f"{self.schematic_file.stem}.erc.rpt"
        self.results['report_file'] = str(report_file)

        try:
            # Execute ERC command
            # GENERIC: Works for any schematic file
            cmd = [
                str(self.kicad_cli),
                "sch", "erc",
                "--severity-error",
                "--output", str(report_file),
                str(self.schematic_file)
            ]

            print(f"   🔧 Running: kicad-cli sch erc...")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Parse the generated report file
            # CRITICAL: KiCad ERC returns exit code 0 even with violations!
            # Must ALWAYS parse the report file for actual error counts
            return self._parse_erc_report(report_file)

        except subprocess.TimeoutExpired:
            print(f"   ❌ ERROR: ERC timeout (>30s)")
            self.results['error_details'].append("ERC timeout")
            return False, 999

        except Exception as e:
            print(f"   ❌ ERROR: ERC execution failed: {e}")
            self.results['error_details'].append(f"ERC execution failed: {e}")
            return False, 999

    def _parse_erc_report(self, report_file: Path) -> Tuple[bool, int]:
        """
        Parse ERC report file for error/warning counts.

        Args:
            report_file: Path to .erc.rpt file

        Returns:
            Tuple[bool, int]: (validation_passed, error_count)

        TC #52 FIX 3.1 (2025-11-26): Now filters out EXPECTED_WARNINGS.
        Global labels that appear "dangling" are expected in multi-board designs.

        GENERIC: Parses KiCad ERC format for ANY error type:
            - duplicate_reference
            - pin_not_connected
            - pin_not_driven
            - power_pin_not_driven
            - conflicting_net_classes
            - etc.
        """
        if not report_file.exists():
            print(f"   ❌ ERROR: ERC report not generated")
            return False, 999

        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # ═══════════════════════════════════════════════════════════════════
            # TC #52 FIX 3.1 (2025-11-26): Count errors by type, filtering expected
            # TC #69 FIX (2025-12-07): Also track CRITICAL WARNINGS
            # ═══════════════════════════════════════════════════════════════════
            # Instead of just parsing the summary line, we now parse each error
            # type and filter out expected warnings. We also track critical
            # warnings that need investigation even if ERC "passes".
            # ═══════════════════════════════════════════════════════════════════

            # Extract all error types and their counts
            # TC #66 FIX: Check KiCad's own severity classification, not just type name
            error_counts_by_type = {}
            expected_warning_count = 0
            real_error_count = 0
            kicad_warning_count = 0
            critical_warning_count = 0  # TC #69
            critical_warning_details = []  # TC #69

            lines = content.split('\n')
            for i, line in enumerate(lines):
                # Match error lines like: [duplicate_reference]: ...
                error_match = re.match(r'\[([a-z_]+)\]:', line)
                if error_match:
                    error_type = error_match.group(1)
                    error_counts_by_type[error_type] = error_counts_by_type.get(error_type, 0) + 1

                    # TC #66 FIX: Check if KiCad marked this as "warning" on the next line
                    # KiCad format: "[error_type]: message\n    ; warning" or "; error"
                    is_kicad_warning = False
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        if next_line == '; warning':
                            is_kicad_warning = True
                            kicad_warning_count += 1

                    # TC #69: Check if this is a CRITICAL WARNING
                    if error_type in self.CRITICAL_WARNINGS:
                        critical_warning_count += 1
                        # Extract the full warning message (rest of line after type)
                        warning_msg = line[len(f'[{error_type}]:'):].strip()
                        critical_warning_details.append({
                            'type': error_type,
                            'message': warning_msg[:100],  # Limit message length
                            'line': i + 1
                        })

                    # Check if this is an expected warning type OR KiCad classified it as warning
                    if error_type in self.EXPECTED_WARNINGS or is_kicad_warning:
                        expected_warning_count += 1
                    else:
                        real_error_count += 1

            # Also get the summary line for reference
            erc_match = re.search(
                r'\*\*\s*ERC messages:\s*\d+\s+Errors\s+(\d+)\s+Warnings\s+(\d+)',
                content
            )

            if erc_match:
                raw_error_count = int(erc_match.group(1))
                raw_warning_count = int(erc_match.group(2))
            else:
                # Fallback: count from parsed errors
                raw_error_count = real_error_count + expected_warning_count
                raw_warning_count = 0

            # Store both raw and filtered counts
            # TC #66 FIX: Store KiCad's own warning classification
            # TC #69 FIX: Store critical warning counts
            self.results['erc_errors'] = real_error_count
            self.results['erc_errors_raw'] = raw_error_count
            self.results['erc_warnings'] = raw_warning_count
            self.results['erc_expected_warnings'] = expected_warning_count
            self.results['erc_kicad_warnings'] = kicad_warning_count
            self.results['erc_critical_warnings'] = critical_warning_count
            self.results['critical_warning_details'] = critical_warning_details[:20]  # Limit stored
            self.results['error_counts_by_type'] = error_counts_by_type

            # TC #69: Set needs_attention flag if critical warnings present
            self.results['needs_attention'] = critical_warning_count > 0

            # Report results
            # TC #66 FIX: Report KiCad warnings separately from expected warnings
            # TC #69 FIX: Report critical warnings prominently
            if real_error_count > 0:
                print(f"   ❌ ERC FAILED: {real_error_count} errors")
                print(f"      (raw: {raw_error_count}, KiCad warnings: {kicad_warning_count}, expected: {expected_warning_count})")

                # List real errors only (not warnings, not expected)
                real_error_types = []
                for error_type, count in error_counts_by_type.items():
                    if error_type not in self.EXPECTED_WARNINGS:
                        # Check if ANY instance was a KiCad warning (crude approximation)
                        # Real errors are types not in EXPECTED_WARNINGS and not KiCad warnings
                        real_error_types.append(error_type)
                if real_error_types:
                    print(f"      Error types: {', '.join(sorted(real_error_types)[:5])}")
                    self.results['error_details'] = real_error_types

                self.results['validation_passed'] = False
                return False, real_error_count
            else:
                if expected_warning_count > 0:
                    print(f"   ✅ ERC PASS: 0 real errors ({expected_warning_count} warnings filtered)")
                    if kicad_warning_count > 0:
                        print(f"      KiCad warnings (benign): {kicad_warning_count}")
                    expected_types = [t for t in error_counts_by_type if t in self.EXPECTED_WARNINGS]
                    if expected_types:
                        print(f"      Expected warning types: {', '.join(expected_types)}")
                else:
                    print(f"   ✅ ERC PASS: 0 errors, {raw_warning_count} warnings")

                # TC #69: Report critical warnings even when ERC passes
                if critical_warning_count > 0:
                    print(f"   ⚠️  TC #69 CRITICAL WARNINGS: {critical_warning_count} issues need attention!")
                    # Group by type
                    critical_types = {}
                    for cw in critical_warning_details:
                        t = cw['type']
                        critical_types[t] = critical_types.get(t, 0) + 1
                    for ctype, count in sorted(critical_types.items()):
                        print(f"      - {ctype}: {count}")
                    print(f"   ℹ️  These may indicate net connectivity issues (investigate before production)")

                self.results['validation_passed'] = True
                return True, 0

        except Exception as e:
            print(f"   ❌ ERROR: Failed to parse ERC report: {e}")
            return False, 999

    def _parse_existing_report(self) -> Tuple[bool, int]:
        """
        Parse existing ERC report when kicad-cli is not available (offline mode).

        Returns:
            Tuple[bool, int]: (validation_passed, error_count)

        GENERIC: Works with any existing ERC report.
        """
        report_file = self.output_dir / f"{self.schematic_file.stem}.erc.rpt"

        if report_file.exists():
            print(f"   📄 Found existing report: {report_file.name}")
            return self._parse_erc_report(report_file)
        else:
            print(f"   ❌ ERROR: No ERC report found (offline mode)")
            print(f"   FAIL-CLOSED: Cannot validate without report")
            return False, 999

    def save_results(self) -> None:
        """
        Save validation results to JSON file.

        GENERIC: Saves structured results for any circuit.
        """
        results_file = self.output_dir / f"{self.schematic_file.stem}_erc_results.json"

        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"   📊 Results saved: {results_file.name}")


def main():
    """
    Main entry point for standalone execution.

    USAGE:
        python kicad_erc_validator.py <schematic.kicad_sch> [output_dir]
    """
    if len(sys.argv) < 2:
        print("USAGE: python kicad_erc_validator.py <schematic.kicad_sch> [output_dir]")
        print()
        print("EXAMPLE:")
        print("  python kicad_erc_validator.py my_circuit.kicad_sch")
        print("  python kicad_erc_validator.py my_circuit.kicad_sch ./reports")
        sys.exit(2)

    schematic_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    # Create validator and run
    validator = KiCadERCValidator(schematic_file, output_dir)
    passed, error_count = validator.validate()
    validator.save_results()

    # Print summary
    print()
    print("=" * 70)
    if passed:
        print("✅ ERC VALIDATION PASSED")
        sys.exit(0)
    else:
        print(f"❌ ERC VALIDATION FAILED ({error_count} errors)")
        sys.exit(1)


if __name__ == "__main__":
    main()
