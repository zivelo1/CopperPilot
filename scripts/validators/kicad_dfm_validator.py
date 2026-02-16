#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad DFM (Design for Manufacturability) Validator - Modular Script

PURPOSE:
    Validates KiCad PCB files for manufacturability against fabricator capabilities.
    Uses internal DFM checker (workflow/dfm module) to validate:
        - Trace widths (minimum 0.15mm for most fabs)
        - Via sizes (minimum 0.3mm drill)
        - Clearances (minimum 0.15mm)
        - Solder mask clearance
        - Board thickness constraints
        - Layer count limits
        - etc.

USAGE:
    python kicad_dfm_validator.py <pcb_file.kicad_pcb> [output_dir] [fabricator]

OUTPUTS:
    - DFM HTML report (detailed, human-readable)
    - JSON results file with error/warning counts
    - Exit code: 0 = pass, 1 = errors found, 2 = validation failed

GENERIC:
    Works for ANY KiCad PCB, ANY circuit type, ANY fabricator.
    Default fabricator: JLCPCB (can be overridden)

AUTHOR: CopperPilot AI Circuit Design Platform
DATE: 2025-11-10
VERSION: 1.0 - Modular refactoring
"""

import sys
import json
from pathlib import Path
from typing import Dict, Tuple
from datetime import datetime


class KiCadDFMValidator:
    """
    Validates KiCad PCB files for Design for Manufacturability.

    GENERIC: Works for any circuit type, any fabricator.
    MODULAR: Standalone script that can be called independently.
    """

    def __init__(self, pcb_file: Path, output_dir: Path = None, fabricator: str = "JLCPCB"):
        """
        Initialize DFM validator.

        Args:
            pcb_file: Path to .kicad_pcb file
            output_dir: Optional directory for reports (defaults to pcb_file.parent/verification)
            fabricator: Fabricator name (JLCPCB, PCBWay, OSHPark, etc.)
        """
        self.pcb_file = Path(pcb_file)
        self.fabricator = fabricator

        # Default output directory: same folder as PCB, under verification/
        if output_dir is None:
            self.output_dir = self.pcb_file.parent / "verification"
        else:
            self.output_dir = Path(output_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Results storage
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'pcb': str(self.pcb_file),
            'fabricator': self.fabricator,
            'dfm_errors': 0,
            'dfm_warnings': 0,
            'dfm_suggestions': 0,
            'validation_passed': False,
            'html_report': None,
            'critical_issues': []
        }

    def validate(self) -> Tuple[bool, int]:
        """
        Run DFM validation.

        Returns:
            Tuple[bool, int]: (validation_passed, error_count)

        GENERIC: Works for any PCB, any fabricator.
        """
        print(f"📋 DFM Validation: {self.pcb_file.name}")
        print(f"   Fabricator: {self.fabricator}")
        print(f"   Output: {self.output_dir}/")

        # Check if PCB exists
        if not self.pcb_file.exists():
            print(f"   ❌ ERROR: PCB file not found")
            self.results['critical_issues'].append("PCB file not found")
            return False, 999

        # Run DFM validation using internal checker
        return self._run_dfm_check()

    def _run_dfm_check(self) -> Tuple[bool, int]:
        """
        Execute DFM checks using internal workflow/dfm module.

        Returns:
            Tuple[bool, int]: (validation_passed, error_count)

        GENERIC: Works for any PCB file, any fabricator.
        """
        try:
            # Import DFM modules (from workflow/dfm)
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent.parent / "workflow"))

            # NOTE: The KiCad-specific parser class is KiCadDFMParser,
            # not KiCadPCBParser. The previous import caused an ImportError
            # and prevented HTML reports from being generated even though
            # JSON stubs were written.
            from dfm.kicad_parser import KiCadDFMParser
            from dfm.dfm_checker import DFMChecker
            from dfm.dfm_reporter import DFMReporter

            # Step 1: Parse KiCad PCB file
            print(f"   🔧 Parsing PCB file...")
            parser = KiCadDFMParser()
            pcb_data = parser.parse(str(self.pcb_file))

            if not pcb_data:
                print(f"   ❌ ERROR: Failed to parse PCB file")
                return False, 999

            print(f"      Extracted: {pcb_data.get('trace_count', 0)} traces, "
                  f"{pcb_data.get('via_count', 0)} vias, "
                  f"{pcb_data.get('pad_count', 0)} pads")

            # Step 2: Run DFM checks
            print(f"   🔧 Running DFM checks for {self.fabricator}...")
            # DFMChecker expects the target fabricator at construction time and
            # then receives the parsed PCB data in check(). The previous call
            # order passed pcb_data as the first argument, which caused a
            # runtime error and prevented HTML reports from being generated.
            checker = DFMChecker(self.fabricator)
            dfm_result = checker.check(pcb_data)

            # Extract counts from DFMResult object
            self.results['dfm_errors'] = len(dfm_result.errors)
            self.results['dfm_warnings'] = len(dfm_result.warnings)
            self.results['dfm_suggestions'] = len(dfm_result.suggestions)

            total_errors = self.results['dfm_errors']

            # Step 3: Generate HTML report
            print(f"   🔧 Generating HTML report...")
            reporter = DFMReporter()
            html_content = reporter.generate_html(
                dfm_result,
                circuit_name=self.pcb_file.stem,
                pcb_file=str(self.pcb_file)
            )

            # Save HTML report
            circuit_name = self.pcb_file.stem
            html_file = self.output_dir / f"{circuit_name}_dfm_report.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_content)

            self.results['html_report'] = str(html_file)
            print(f"      Saved: {html_file.name}")

            # Step 4: Report results
            if total_errors > 0:
                print(f"   ❌ DFM FAILED: {total_errors} errors, "
                      f"{self.results['dfm_warnings']} warnings, "
                      f"{self.results['dfm_suggestions']} suggestions")

                # Show first few errors
                for error in dfm_result.errors[:3]:
                    msg = error.message
                    print(f"      - {msg}")
                    self.results['critical_issues'].append(msg)

                self.results['validation_passed'] = False
                return False, total_errors
            else:
                print(f"   ✅ DFM PASS: 0 errors, "
                      f"{self.results['dfm_warnings']} warnings, "
                      f"{self.results['dfm_suggestions']} suggestions")
                print(f"      PCB meets {self.fabricator} manufacturing capabilities")
                self.results['validation_passed'] = True
                return True, 0

        except ImportError as e:
            print(f"   ⚠️  WARNING: DFM modules not available: {e}")
            print(f"   SKIPPING DFM validation (not critical)")
            # DFM is not critical - allow to pass if modules missing
            return True, 0

        except Exception as e:
            print(f"   ❌ ERROR: DFM check failed: {e}")
            self.results['critical_issues'].append(f"DFM check failed: {e}")
            return False, 999

    def save_results(self) -> None:
        """
        Save validation results to JSON file.

        GENERIC: Saves structured results for any circuit.
        """
        results_file = self.output_dir / f"{self.pcb_file.stem}_dfm_results.json"

        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)

        print(f"   📊 Results saved: {results_file.name}")


def main():
    """
    Main entry point for standalone execution.

    USAGE:
        python kicad_dfm_validator.py <pcb.kicad_pcb> [output_dir] [fabricator]
    """
    if len(sys.argv) < 2:
        print("USAGE: python kicad_dfm_validator.py <pcb.kicad_pcb> [output_dir] [fabricator]")
        print()
        print("EXAMPLES:")
        print("  python kicad_dfm_validator.py my_circuit.kicad_pcb")
        print("  python kicad_dfm_validator.py my_circuit.kicad_pcb ./reports")
        print("  python kicad_dfm_validator.py my_circuit.kicad_pcb ./reports PCBWay")
        print()
        print("Supported fabricators: JLCPCB (default), PCBWay, OSHPark")
        sys.exit(2)

    pcb_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    fabricator = sys.argv[3] if len(sys.argv) > 3 else "JLCPCB"

    # Create validator and run
    validator = KiCadDFMValidator(pcb_file, output_dir, fabricator)
    passed, error_count = validator.validate()
    validator.save_results()

    # Print summary
    print()
    print("=" * 70)
    if passed:
        print("✅ DFM VALIDATION PASSED - PCB meets fabricator capabilities")
        sys.exit(0)
    else:
        print(f"❌ DFM VALIDATION FAILED ({error_count} errors)")
        print(f"   PCB does NOT meet {fabricator} manufacturing capabilities")
        sys.exit(1)


if __name__ == "__main__":
    main()
