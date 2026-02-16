#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Forensic validation of KiCad files to ensure they are production-ready.
Checks for all critical issues including version compatibility.

FIXED 2025-11-10: Now validates actual ERC/DRC/DFM outcomes, not just syntax.
GENERIC: Works for any circuit type, any error pattern.
"""

import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple


class KiCadForensicValidator:
    """Forensic validator for KiCad files - now validates REAL electrical/manufacturing correctness."""

    def __init__(self, kicad_dir: str):
        self.kicad_dir = Path(kicad_dir)
        self.results = {
            'files': [],
            'errors': [],
            'warnings': [],
            'components': 0,
            'nets': 0,
            'wires': 0,
            'traces': 0,
            'footprints': 0,
            'version_issues': [],
            'format_issues': [],
            'erc_errors': 0,           # NEW: Track actual ERC errors
            'drc_violations': 0,       # NEW: Track actual DRC violations
            'missing_dfm_reports': []  # NEW: Track missing DFM reports
        }

    def validate(self) -> bool:
        """Run complete forensic validation."""
        print("=" * 70)
        print("FORENSIC VALIDATION OF KICAD FILES")
        print("Production-Ready Quality Check")
        print("=" * 70)
        print(f"Directory: {self.kicad_dir}")
        print("=" * 70 + "\n")

        # Find all KiCad files
        pro_files = list(self.kicad_dir.glob("*.kicad_pro"))
        sch_files = list(self.kicad_dir.glob("*.kicad_sch"))
        pcb_files = list(self.kicad_dir.glob("*.kicad_pcb"))

        if not (pro_files or sch_files or pcb_files):
            print("❌ No KiCad files found!")
            return False

        print(f"Found {len(pro_files)} project(s), {len(sch_files)} schematic(s), {len(pcb_files)} PCB(s)\n")

        # Validate each project
        projects = {}
        for pro_file in pro_files:
            base_name = pro_file.stem
            projects[base_name] = {
                'pro': pro_file,
                'sch': self.kicad_dir / f"{base_name}.kicad_sch",
                'pcb': self.kicad_dir / f"{base_name}.kicad_pcb"
            }

        for project_name, files in projects.items():
            print(f"Validating Project: {project_name}")
            print("-" * 50)
            self._validate_project(project_name, files)
            print()

        # Print summary
        self._print_summary()

        # Return success status
        return len(self.results['errors']) == 0

    def _validate_project(self, project_name: str, files: Dict) -> None:
        """
        Validate a complete KiCad project.

        FIXED 2025-11-10: Now validates REAL ERC/DRC/DFM outcomes, not just syntax.
        GENERIC: Works for any circuit, any error type.
        """

        # Validate project file
        if files['pro'].exists():
            self._validate_pro_file(files['pro'])
        else:
            self._add_error(f"{project_name}: Missing project file (.kicad_pro)")

        # Validate schematic file
        if files['sch'].exists():
            self._validate_sch_file(files['sch'])
        else:
            self._add_error(f"{project_name}: Missing schematic file (.kicad_sch)")

        # Validate PCB file
        if files['pcb'].exists():
            self._validate_pcb_file(files['pcb'])
        else:
            self._add_error(f"{project_name}: Missing PCB file (.kicad_pcb)")

        # NEW FIX (2025-11-10): Validate REAL ERC/DRC/DFM reports
        # This is CRITICAL for production-ready validation
        self._validate_erc_report(project_name)
        self._validate_drc_report(project_name)
        self._validate_dfm_report(project_name)

        self.results['files'].append(project_name)

    def _validate_pro_file(self, pro_file: Path) -> None:
        """Validate KiCad project file."""
        try:
            with open(pro_file, 'r') as f:
                data = json.load(f)

            # Check for required sections
            required_sections = ['board', 'schematic', 'net_settings']
            for section in required_sections:
                if section not in data:
                    self._add_error(f"{pro_file.name}: Missing '{section}' section")

            # Check design settings
            if 'board' in data and 'design_settings' in data['board']:
                settings = data['board']['design_settings']
                if 'track_widths' in settings:
                    tracks = settings['track_widths']
                    if tracks and min(tracks) < 0.15:
                        self._add_warning(f"{pro_file.name}: Track width below 0.15mm manufacturing limit")

        except json.JSONDecodeError as e:
            self._add_error(f"{pro_file.name}: Invalid JSON format - {e}")
        except Exception as e:
            self._add_error(f"{pro_file.name}: Validation error - {e}")

    def _validate_sch_file(self, sch_file: Path) -> None:
        """Validate KiCad schematic file."""
        try:
            with open(sch_file, 'r') as f:
                content = f.read()

            # Check file structure
            if not content.strip().startswith('(kicad_sch'):
                self._add_error(f"{sch_file.name}: Invalid schematic file header")
                return

            # Extract and validate version
            version_match = re.search(r'\(version\s+(\d+)\)', content)
            if version_match:
                version = version_match.group(1)
                self._check_version(version, sch_file.name, 'schematic')
            else:
                self._add_error(f"{sch_file.name}: Missing version information")

            # Check generator and generator_version
            if '(generator "' not in content:
                self._add_error(f"{sch_file.name}: Missing generator information")

            generator_version_match = re.search(r'\(generator_version\s+"([^"]+)"\)', content)
            if generator_version_match:
                gen_version = generator_version_match.group(1)
                # Validate it's a reasonable version (e.g., "8.0", "9.0")
                if not re.match(r'^\d+\.\d+', gen_version):
                    self._add_warning(f"{sch_file.name}: Unusual generator_version format: {gen_version}")
            else:
                self._add_warning(f"{sch_file.name}: Missing generator_version")

            # Count components
            component_count = content.count('(symbol (lib_id')
            self.results['components'] += component_count

            # Count wires
            wire_count = content.count('(wire')
            self.results['wires'] += wire_count

            # Check for unannotated components
            if 'Reference" "?"' in content:
                self._add_error(f"{sch_file.name}: Contains unannotated components")

            # Check for floating nets
            if wire_count == 0 and component_count > 1:
                self._add_warning(f"{sch_file.name}: No wires connecting components")

            # Check parentheses balance
            open_parens = content.count('(')
            close_parens = content.count(')')
            if open_parens != close_parens:
                self._add_error(f"{sch_file.name}: Unbalanced parentheses ({open_parens} open, {close_parens} close)")

            # Check for required UUIDs
            if '(uuid "' not in content:
                self._add_error(f"{sch_file.name}: Missing UUID definitions")

        except Exception as e:
            self._add_error(f"{sch_file.name}: Validation error - {e}")

    def _validate_pcb_file(self, pcb_file: Path) -> None:
        """Validate KiCad PCB file."""
        try:
            with open(pcb_file, 'r') as f:
                content = f.read()

            # Check file structure
            if not content.strip().startswith('(kicad_pcb'):
                self._add_error(f"{pcb_file.name}: Invalid PCB file header")
                return

            # Extract and validate version
            version_match = re.search(r'\(version\s+(\d+)\)', content)
            if version_match:
                version = version_match.group(1)
                self._check_version(version, pcb_file.name, 'PCB')
            else:
                self._add_error(f"{pcb_file.name}: Missing version information")

            # Check generator and generator_version
            if '(generator "' not in content:
                self._add_error(f"{pcb_file.name}: Missing generator information")

            generator_version_match = re.search(r'\(generator_version\s+"([^"]+)"\)', content)
            if generator_version_match:
                gen_version = generator_version_match.group(1)
                if not re.match(r'^\d+\.\d+', gen_version):
                    self._add_warning(f"{pcb_file.name}: Unusual generator_version format: {gen_version}")
            else:
                self._add_warning(f"{pcb_file.name}: Missing generator_version")

            # Count footprints
            footprint_count = content.count('(footprint "')
            self.results['footprints'] += footprint_count

            # Count traces/segments
            segment_count = content.count('(segment')
            self.results['traces'] += segment_count

            # Count nets
            net_count = len(re.findall(r'\(net\s+\d+\s+"[^"]+"\)', content))
            self.results['nets'] += net_count

            # Check for board outline
            if '(gr_rect' not in content and '(gr_line' not in content and '(gr_arc' not in content:
                self._add_warning(f"{pcb_file.name}: No board outline (Edge.Cuts) found")

            # Check for unconnected pads
            if segment_count == 0 and footprint_count > 1:
                self._add_error(f"{pcb_file.name}: No traces connecting footprints")

            # Check layers definition
            if '(layers' not in content:
                self._add_error(f"{pcb_file.name}: Missing layers definition")

            # Check for proper net assignments
            pad_with_net = content.count('(net ')
            if footprint_count > 0 and pad_with_net == 0:
                self._add_warning(f"{pcb_file.name}: No pads connected to nets")

            # Check parentheses balance
            open_parens = content.count('(')
            close_parens = content.count(')')
            if open_parens != close_parens:
                self._add_error(f"{pcb_file.name}: Unbalanced parentheses ({open_parens} open, {close_parens} close)")

        except Exception as e:
            self._add_error(f"{pcb_file.name}: Validation error - {e}")

    def _validate_erc_report(self, project_name: str) -> None:
        """
        Validate ERC report file for electrical rule violations.

        ADDED 2025-11-10: Parse actual ERC report to catch electrical errors.
        GENERIC: Works for any ERC violation type.
        """
        erc_report_path = self.kicad_dir / "ERC" / f"{project_name}.erc.rpt"

        if not erc_report_path.exists():
            # Phase E (Forensic Fix 20260211): Treat missing report as ERROR
            self._add_error(f"{project_name}: ERC report missing (kicad-cli may not have run or failed)")
            return

        try:
            with open(erc_report_path, 'r') as f:
                content = f.read()

            # Parse ERC report format: "** ERC messages: N  Errors M  Warnings K"
            erc_match = re.search(r'\*\*\s*ERC messages:\s*\d+\s+Errors\s+(\d+)\s+Warnings\s+(\d+)', content)

            if erc_match:
                error_count = int(erc_match.group(1))
                warning_count = int(erc_match.group(2))

                self.results['erc_errors'] += error_count

                if error_count > 0:
                    self._add_error(f"{project_name}: ERC FAILED with {error_count} electrical errors")
                    # Show first few errors for debugging
                    error_lines = [line for line in content.split('\n') if 'error' in line.lower() or 'duplicate_reference' in line.lower()]
                    for error_line in error_lines[:3]:
                        if error_line.strip():
                            print(f"    - {error_line.strip()}")
                else:
                    print(f"  ✓ ERC: PASS (0 errors, {warning_count} warnings)")

                if warning_count > 5:
                    self._add_warning(f"{project_name}: ERC has {warning_count} warnings")

        except Exception as e:
            self._add_error(f"{project_name}: Failed to parse ERC report - {e}")

    def _validate_drc_report(self, project_name: str) -> None:
        """
        Validate DRC report file for manufacturing rule violations.

        ADDED 2025-11-10: Parse actual DRC report to catch manufacturing errors.
        GENERIC: Works for any DRC violation type (shorts, clearance, crossings, etc.).
        """
        drc_report_path = self.kicad_dir / "DRC" / f"{project_name}.drc.rpt"

        if not drc_report_path.exists():
            # Phase E (Forensic Fix 20260211): Treat missing report as ERROR
            self._add_error(f"{project_name}: DRC report missing (kicad-cli may not have run or failed)")
            return

        try:
            with open(drc_report_path, 'r') as f:
                content = f.read()

            # Parse DRC report format: "** Found N DRC violations **"
            drc_match = re.search(r'\*\*\s*Found\s+(\d+)\s+DRC violations\s*\*\*', content)
            unconnected_match = re.search(r'\*\*\s*Found\s+(\d+)\s+unconnected pads\s*\*\*', content)
            footprint_match = re.search(r'\*\*\s*Found\s+(\d+)\s+Footprint errors\s*\*\*', content)

            drc_violations = int(drc_match.group(1)) if drc_match else 0
            unconnected_pads = int(unconnected_match.group(1)) if unconnected_match else 0
            footprint_errors = int(footprint_match.group(1)) if footprint_match else 0

            total_drc_errors = drc_violations + unconnected_pads + footprint_errors
            self.results['drc_violations'] += total_drc_errors

            if total_drc_errors > 0:
                self._add_error(f"{project_name}: DRC FAILED with {total_drc_errors} manufacturing violations")
                if drc_violations > 0:
                    print(f"    - DRC violations: {drc_violations} (tracks_crossing, clearance, shorts, etc.)")
                    # Show first few violations for debugging
                    violation_types = set()
                    for line in content.split('\n'):
                        if line.strip().startswith('['):
                            violation_type = line.split(']')[0].strip('[')
                            violation_types.add(violation_type)
                            if len(violation_types) <= 5:
                                print(f"      * {violation_type}")
                if unconnected_pads > 0:
                    print(f"    - Unconnected pads: {unconnected_pads} (incomplete routing)")
                if footprint_errors > 0:
                    print(f"    - Footprint errors: {footprint_errors}")
                self._add_error(f"{project_name}: PCB is NOT MANUFACTURABLE - requires fixes!")
            else:
                print(f"  ✓ DRC: PASS (0 violations, 0 unconnected, 0 footprint errors)")
                print(f"    PCB is PERFECT and READY FOR MANUFACTURING")

        except Exception as e:
            self._add_error(f"{project_name}: Failed to parse DRC report - {e}")

    def _validate_dfm_report(self, project_name: str) -> None:
        """
        Validate DFM (Design for Manufacturability) report presence.

        ADDED 2025-11-10: Check for DFM validation output.
        GENERIC: Works for any circuit.
        """
        dfm_report_path = self.kicad_dir / "verification" / f"{project_name}_dfm_report.html"

        if not dfm_report_path.exists():
            # DFM reports are often missing in offline mode - warn but don't fail
            self._add_warning(f"{project_name}: DFM report missing (verification/{project_name}_dfm_report.html)")
            self.results['missing_dfm_reports'].append(project_name)
        else:
            print(f"  ✓ DFM: Report found at verification/{project_name}_dfm_report.html")

    def _check_version(self, version: str, filename: str, file_type: str):
        """Check if version string is valid for KiCad 8/9."""
        # Known good versions for KiCad 8 and 9
        known_versions = [
            # KiCad 9 versions
            "20250114",  # KiCad 9.0.5 (Official)
            "20250101",  # KiCad 9.0.0
            # KiCad 8 versions
            "20240108",  # KiCad 8.0
            "20231120",  # KiCad 8.0 RC
            "20230121",  # Earlier KiCad 8 development
        ]

        # Check if it's a valid version
        try:
            version_int = int(version)
            # Check if version is in the future (after October 2025)
            # We're in October 2025, so versions up to 20251031 are valid
            if version_int > 20251231:
                self._add_error(f"{filename}: Version {version} is from the future (post-2025)")
                self.results['version_issues'].append(f"{filename}: Future version {version}")
            elif version_int < 20230000:
                self._add_warning(f"{filename}: Version {version} is very old (pre-2023)")
            elif version not in known_versions:
                # It's not a known version but within reasonable range
                # This is just a warning, not an error
                pass  # Don't warn about unknown but reasonable versions
        except ValueError:
            self._add_error(f"{filename}: Invalid version format: {version}")

    def _add_error(self, message: str) -> None:
        """Add error message."""
        self.results['errors'].append(f"❌ ERROR: {message}")

    def _add_warning(self, message: str) -> None:
        """Add warning message."""
        self.results['warnings'].append(f"⚠️  WARNING: {message}")

    def _print_summary(self) -> None:
        """
        Print validation summary.

        UPDATED 2025-11-10: Now includes REAL ERC/DRC/DFM validation results.
        """
        print("=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)

        print(f"\nProjects validated: {len(self.results['files'])}")
        print(f"Total components: {self.results['components']}")
        print(f"Total nets: {self.results['nets']}")
        print(f"Total schematic wires: {self.results['wires']}")
        print(f"Total PCB traces: {self.results['traces']}")
        print(f"Total footprints: {self.results['footprints']}")

        # NEW (2025-11-10): Show REAL electrical/manufacturing validation results
        print(f"\n📊 REAL VALIDATION RESULTS (from KiCad ERC/DRC):")
        print(f"  ERC Errors: {self.results['erc_errors']} (electrical rule violations)")
        print(f"  DRC Violations: {self.results['drc_violations']} (manufacturing rule violations)")
        if self.results['missing_dfm_reports']:
            print(f"  DFM Reports Missing: {len(self.results['missing_dfm_reports'])} circuits")

        if self.results['version_issues']:
            print(f"\n🔢 Version Issues: {len(self.results['version_issues'])}")
            for issue in self.results['version_issues']:
                print(f"  - {issue}")

        if self.results['errors']:
            print(f"\n🛑 CRITICAL ERRORS: {len(self.results['errors'])}")
            for error in self.results['errors'][:10]:  # Show first 10
                print(f"  {error}")
            if len(self.results['errors']) > 10:
                print(f"  ... and {len(self.results['errors']) - 10} more")

        if self.results['warnings']:
            print(f"\n⚠️  WARNINGS: {len(self.results['warnings'])}")
            for warning in self.results['warnings'][:10]:  # Show first 10
                print(f"  {warning}")
            if len(self.results['warnings']) > 10:
                print(f"  ... and {len(self.results['warnings']) - 10} more")

        print("\n" + "=" * 70)

        # NEW (2025-11-10): FAIL if ERC/DRC errors exist (FAIL-CLOSED quality gate)
        has_erc_drc_errors = (self.results['erc_errors'] > 0 or self.results['drc_violations'] > 0)

        if has_erc_drc_errors:
            print("❌ VALIDATION FAILED - ERC/DRC violations detected")
            if self.results['erc_errors'] > 0:
                print(f"   🔴 {self.results['erc_errors']} ERC errors (electrical rules) - circuits will NOT work")
            if self.results['drc_violations'] > 0:
                print(f"   🔴 {self.results['drc_violations']} DRC violations (manufacturing rules) - PCBs are NOT MANUFACTURABLE")
            print("   Solution: Fix all ERC/DRC errors before manufacturing")
        elif self.results['errors']:
            print("❌ VALIDATION FAILED - Files have critical errors")
            if self.results['version_issues']:
                print("   Primary Issue: Version compatibility problems detected")
                print("   Solution: Ensure version strings are compatible with KiCad 9")
        elif self.results['warnings']:
            print("⚠️  VALIDATION PASSED WITH WARNINGS")
        else:
            print("✅ VALIDATION PERFECT - All files are production ready")

        # Score calculation (UPDATED to include ERC/DRC)
        score = 100
        score -= self.results['erc_errors'] * 20        # NEW: ERC errors are CRITICAL (-20 per error)
        score -= self.results['drc_violations'] * 10    # NEW: DRC violations are CRITICAL (-10 per violation)
        score -= len(self.results['errors']) * 10
        score -= len(self.results['warnings']) * 2
        score -= len(self.results['version_issues']) * 5
        score = max(0, score)

        print(f"\n🏆 QUALITY SCORE: {score}%")

        if score == 100:
            print("🎉 PRODUCTION READY - Files can be opened in KiCad 8")
        elif score >= 90:
            print("✅ ACCEPTABLE - Minor issues that won't prevent usage")
        elif score >= 70:
            print("⚠️  NEEDS ATTENTION - Some issues may cause problems")
        else:
            print("❌ NOT READY - Critical issues will prevent usage")

        # Connectivity check
        if self.results['traces'] > 0 and self.results['wires'] > 0:
            print("\n📊 CONNECTIVITY STATUS:")
            print(f"  ✓ Schematic: {self.results['wires']} wires connecting components")
            print(f"  ✓ PCB: {self.results['traces']} traces routing signals")
        elif self.results['components'] > 0:
            print("\n📊 CONNECTIVITY WARNING:")
            if self.results['wires'] == 0:
                print("  ✗ Schematic: No wires found - components not connected!")
            if self.results['traces'] == 0:
                print("  ✗ PCB: No traces found - pads not routed!")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        kicad_dir = "output/20251012-075031-05f4278f/kicad"
    else:
        kicad_dir = sys.argv[1]

    validator = KiCadForensicValidator(kicad_dir)
    success = validator.validate()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()