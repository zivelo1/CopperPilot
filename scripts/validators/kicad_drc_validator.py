#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad DRC (Design Rules Check) Validator - Modular Script

PURPOSE:
    Validates KiCad PCB files for manufacturing rule violations.
    Runs kicad-cli DRC and parses the results.

USAGE:
    python kicad_drc_validator.py <pcb_file.kicad_pcb> [output_dir]

OUTPUTS:
    - DRC report file (.drc.rpt)
    - JSON results file with violation counts
    - Exit code: 0 = pass, 1 = violations found, 2 = validation failed

GENERIC:
    Works for ANY KiCad PCB, ANY circuit type, ANY complexity.
    Handles ALL DRC violation types:
        - tracks_crossing (tracks crossing on same layer)
        - shorting_items (items physically shorting different nets)
        - clearance (insufficient spacing between items)
        - hole_clearance (via/drill holes too close)
        - solder_mask_bridge (solder mask bridging different nets)
        - unconnected_items (pads without physical connections)
        - etc.

AUTHOR: CopperPilot AI Circuit Design Platform
DATE: 2025-11-10
VERSION: 1.0 - Modular refactoring
"""

import sys
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Tuple, List
from datetime import datetime
from collections import Counter


class KiCadDRCValidator:
    """
    Validates KiCad PCB files for manufacturing rule violations.

    GENERIC: Works for any circuit type, any DRC violation pattern.
    MODULAR: Standalone script that can be called independently.
    """

    def __init__(self, pcb_file: Path, output_dir: Path = None):
        """
        Initialize DRC validator.

        Args:
            pcb_file: Path to .kicad_pcb file
            output_dir: Optional directory for reports (defaults to pcb_file.parent/DRC)
        """
        self.pcb_file = Path(pcb_file)

        # Default output directory: same folder as PCB, under DRC/
        if output_dir is None:
            self.output_dir = self.pcb_file.parent / "DRC"
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
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'pcb': str(self.pcb_file),
            'drc_violations': 0,
            'unconnected_pads': 0,
            'footprint_errors': 0,
            'total_errors': 0,
            'kicad_cli_available': self.kicad_cli.exists(),
            'validation_passed': False,
            'report_file': None,
            'violation_types': {},  # Count of each violation type
            'critical_issues': []
        }

    def validate(self) -> Tuple[bool, int]:
        """
        Run DRC validation.

        Returns:
            Tuple[bool, int]: (validation_passed, total_error_count)

        GENERIC: Works for any PCB, any DRC error type.
        """
        print(f"📋 DRC Validation: {self.pcb_file.name}")
        print(f"   Output: {self.output_dir}/")

        # Check if PCB exists
        if not self.pcb_file.exists():
            print(f"   ❌ ERROR: PCB file not found")
            self.results['critical_issues'].append("PCB file not found")
            return False, 999

        # Check if KiCad CLI is available
        if not self.kicad_cli.exists():
            print(f"   ⚠️  WARNING: KiCad CLI not found at {self.kicad_cli}")
            print(f"   OFFLINE MODE: Parsing existing reports only")
            return self._parse_existing_report()

        # Run DRC via kicad-cli
        return self._run_kicad_drc()

    def _run_kicad_drc(self) -> Tuple[bool, int]:
        """
        Execute kicad-cli DRC command and parse results.

        Returns:
            Tuple[bool, int]: (validation_passed, total_error_count)

        GENERIC: Handles all DRC output formats, all violation types.
        """
        report_file = self.output_dir / f"{self.pcb_file.stem}.drc.rpt"
        self.results['report_file'] = str(report_file)

        try:
            # Execute DRC command
            # GENERIC: Works for any PCB file
            cmd = [
                str(self.kicad_cli),
                "pcb", "drc",
                "--severity-error",
                "--output", str(report_file),
                str(self.pcb_file)
            ]

            print(f"   🔧 Running: kicad-cli pcb drc...")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            # Parse the generated report file
            # CRITICAL: KiCad DRC returns exit code 0 even with violations!
            # Must ALWAYS parse the report file for actual violation counts
            return self._parse_drc_report(report_file)

        except subprocess.TimeoutExpired:
            print(f"   ❌ ERROR: DRC timeout (>30s)")
            self.results['critical_issues'].append("DRC timeout")
            return False, 999

        except Exception as e:
            print(f"   ❌ ERROR: DRC execution failed: {e}")
            self.results['critical_issues'].append(f"DRC execution failed: {e}")
            return False, 999

    def _parse_drc_report(self, report_file: Path) -> Tuple[bool, int]:
        """
        Parse DRC report file for violation counts and types.

        Args:
            report_file: Path to .drc.rpt file

        Returns:
            Tuple[bool, int]: (validation_passed, total_error_count)

        GENERIC: Parses KiCad DRC format for ANY violation type:
            - tracks_crossing (most common)
            - shorting_items (electrical shorts)
            - clearance (spacing violations)
            - hole_clearance (drill/via clearance)
            - solder_mask_bridge (mask issues)
            - unconnected_items (incomplete routing)
            - footprint_errors (component issues)
            - etc.
        """
        if not report_file.exists():
            print(f"   ❌ ERROR: DRC report not generated")
            return False, 999

        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse DRC summary lines (GENERIC for all violation types)
            # "** Found N DRC violations **"
            drc_match = re.search(
                r'\*\*\s*Found\s+(\d+)\s+DRC violations\s*\*\*',
                content
            )

            # "** Found N unconnected pads **"
            unconnected_match = re.search(
                r'\*\*\s*Found\s+(\d+)\s+unconnected pads\s*\*\*',
                content
            )

            # "** Found N Footprint errors **"
            footprint_match = re.search(
                r'\*\*\s*Found\s+(\d+)\s+Footprint errors\s*\*\*',
                content
            )

            # Extract counts
            drc_violations = int(drc_match.group(1)) if drc_match else 0
            unconnected_pads = int(unconnected_match.group(1)) if unconnected_match else 0
            footprint_errors = int(footprint_match.group(1)) if footprint_match else 0

            total_errors = drc_violations + unconnected_pads + footprint_errors

            self.results['drc_violations'] = drc_violations
            self.results['unconnected_pads'] = unconnected_pads
            self.results['footprint_errors'] = footprint_errors
            self.results['total_errors'] = total_errors

            # Extract violation types for detailed reporting (GENERIC)
            violation_types = self._extract_violation_types(content)
            self.results['violation_types'] = violation_types

            if total_errors > 0:
                print(f"   ❌ DRC FAILED: {total_errors} total errors")
                if drc_violations > 0:
                    print(f"      - DRC violations: {drc_violations}")
                    # Show top 5 violation types
                    top_types = sorted(violation_types.items(), key=lambda x: x[1], reverse=True)[:5]
                    for vtype, count in top_types:
                        print(f"        * {vtype}: {count}")
                if unconnected_pads > 0:
                    print(f"      - Unconnected pads: {unconnected_pads} (incomplete routing)")
                    self.results['critical_issues'].append(f"{unconnected_pads} unconnected pads")
                if footprint_errors > 0:
                    print(f"      - Footprint errors: {footprint_errors}")

                print(f"   ⚠️  PCB is NOT MANUFACTURABLE - requires fixes!")
                self.results['validation_passed'] = False
                return False, total_errors
            else:
                print(f"   ✅ DRC PASS: 0 violations, 0 unconnected, 0 footprint errors")
                print(f"      PCB is PERFECT and READY FOR MANUFACTURING")
                self.results['validation_passed'] = True
                return True, 0

        except Exception as e:
            print(f"   ❌ ERROR: Failed to parse DRC report: {e}")
            return False, 999

    def _extract_violation_types(self, content: str) -> Dict[str, int]:
        """
        Extract and count all violation types from DRC report.

        Args:
            content: Full DRC report content

        Returns:
            Dict[str, int]: Violation type → count

        GENERIC: Extracts ALL violation types from KiCad DRC format.
        """
        violation_types = Counter()

        # Match lines like: [tracks_crossing]: Tracks crossing
        # GENERIC: Works for any violation type name
        for line in content.split('\n'):
            match = re.match(r'\[([a-z_]+)\]:', line)
            if match:
                violation_type = match.group(1)
                violation_types[violation_type] += 1

        return dict(violation_types)

    def _parse_existing_report(self) -> Tuple[bool, int]:
        """
        Parse existing DRC report when kicad-cli is not available (offline mode).

        Returns:
            Tuple[bool, int]: (validation_passed, total_error_count)

        GENERIC: Works with any existing DRC report.
        """
        report_file = self.output_dir / f"{self.pcb_file.stem}.drc.rpt"

        if report_file.exists():
            print(f"   📄 Found existing report: {report_file.name}")
            return self._parse_drc_report(report_file)
        else:
            print(f"   ❌ ERROR: No DRC report found (offline mode)")
            print(f"   FAIL-CLOSED: Cannot validate without report")
            return False, 999

    def save_results(self) -> None:
        """
        Save validation results to JSON file.

        GENERIC: Saves structured results for any circuit.
        """
        results_file = self.output_dir / f"{self.pcb_file.stem}_drc_results.json"

        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"   📊 Results saved: {results_file.name}")


def main():
    """
    Main entry point for standalone execution.

    USAGE:
        python kicad_drc_validator.py <pcb.kicad_pcb> [output_dir]
    """
    if len(sys.argv) < 2:
        print("USAGE: python kicad_drc_validator.py <pcb.kicad_pcb> [output_dir]")
        print()
        print("EXAMPLE:")
        print("  python kicad_drc_validator.py my_circuit.kicad_pcb")
        print("  python kicad_drc_validator.py my_circuit.kicad_pcb ./reports")
        sys.exit(2)

    pcb_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    # Create validator and run
    validator = KiCadDRCValidator(pcb_file, output_dir)
    passed, error_count = validator.validate()
    validator.save_results()

    # Print summary
    print()
    print("=" * 70)
    if passed:
        print("✅ DRC VALIDATION PASSED - PCB is MANUFACTURABLE")
        sys.exit(0)
    else:
        print(f"❌ DRC VALIDATION FAILED ({error_count} errors)")
        print(f"   PCB is NOT READY FOR MANUFACTURING")
        sys.exit(1)


if __name__ == "__main__":
    main()
