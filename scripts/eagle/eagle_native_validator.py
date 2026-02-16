#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle Native Tool Validator - External CAD Tool Integration

This module provides integration with native CAD tools (KiCad) for validation.
It runs actual ERC/DRC checks using external CAD software.

Design Principles:
- GENERIC: Works on multiple platforms (macOS, Linux, Windows)
- EXTERNAL: Uses actual CAD tools, not simulation
- ULTIMATE: Real-world validation from actual software
- EXPERT: ONE job - run external tools and report results

Author: AI Electronics System
Date: October 23, 2025
"""

import subprocess
import re
from pathlib import Path
from typing import Tuple, List, Optional


class NativeToolValidator:
    """
    GENERIC validator using native CAD tools.

    This class runs actual KiCad ERC/DRC on generated files to validate
    they work correctly in real CAD software.

    Architecture:
    - Finds KiCad CLI executable
    - Runs kicad-cli sch erc on schematics
    - Parses ERC reports for errors
    - Returns structured results

    Usage:
        validator = NativeToolValidator()
        success, errors = validator.validate_schematic('circuit.sch')
        if not success:
            print(f"ERC failed: {errors}")
    """

    def __init__(self):
        """
        Initialize validator and locate KiCad CLI.

        Raises:
            RuntimeError: If KiCad CLI cannot be found
        """
        try:
            self.kicad_cli = self._find_kicad_cli()
        except RuntimeError as e:
            print(f"⚠️  Native validation unavailable: {e}")
            self.kicad_cli = None

    def _find_kicad_cli(self) -> str:
        """
        Find KiCad CLI executable on this system.

        Returns:
            Path to kicad-cli executable

        Raises:
            RuntimeError: If KiCad CLI not found

        Notes:
            - Tries platform-specific paths first
            - Falls back to PATH search
            - Works on macOS, Linux, Windows
        """
        # Platform-specific paths
        possible_paths = [
            # macOS
            '/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli',
            # Linux
            '/usr/bin/kicad-cli',
            '/usr/local/bin/kicad-cli',
            # Windows
            'C:\\Program Files\\KiCad\\bin\\kicad-cli.exe',
            'C:\\Program Files (x86)\\KiCad\\bin\\kicad-cli.exe',
        ]

        # Try each path
        for path in possible_paths:
            if Path(path).exists():
                print(f"  ℹ️  Found KiCad CLI: {path}")
                return path

        # Try PATH
        try:
            result = subprocess.run(
                ['kicad-cli', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print("  ℹ️  Found KiCad CLI in PATH")
                return 'kicad-cli'
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        raise RuntimeError(
            "KiCad CLI not found. Please install KiCad or set path manually. "
            "Native validation will be skipped."
        )

    def is_available(self) -> bool:
        """
        Check if native validation is available.

        Returns:
            True if KiCad CLI is available
        """
        return self.kicad_cli is not None

    def validate_schematic(self, sch_path: str) -> Tuple[bool, List[str]]:
        """
        Run KiCad ERC on a schematic file.

        This is the ULTIMATE validation - it imports the file into actual
        KiCad and runs native ERC checks.

        Args:
            sch_path: Path to .sch (Eagle) file

        Returns:
            Tuple of (success, error_list)
            - success: True if 0 ERC errors
            - error_list: List of error messages from ERC

        Notes:
            - KiCad can import Eagle files directly
            - ERC report is parsed for error count
            - Timeout is 60 seconds per file
        """
        if not self.is_available():
            return False, ["KiCad CLI not available - native validation skipped"]

        sch_file = Path(sch_path)
        if not sch_file.exists():
            return False, [f"File not found: {sch_path}"]

        print(f"\n  🔍 Running KiCad ERC on {sch_file.name}...")

        try:
            # Create temporary directory for ERC output
            output_dir = sch_file.parent / f".erc_temp_{sch_file.stem}"
            output_dir.mkdir(exist_ok=True)
            erc_report = output_dir / "erc_report.txt"

            # Run ERC command
            # Note: KiCad can read Eagle .sch files directly
            cmd = [
                self.kicad_cli,
                'sch', 'erc',
                '--format', 'report',
                '--output', str(erc_report),
                str(sch_file)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            # Parse results
            if erc_report.exists():
                errors = self._parse_erc_report(erc_report)

                # Cleanup
                import shutil
                shutil.rmtree(output_dir, ignore_errors=True)

                if len(errors) == 0:
                    print(f"    ✅ 0 ERC errors")
                    return True, []
                else:
                    print(f"    ❌ {len(errors)} ERC errors")
                    return False, errors
            else:
                # ERC report not generated - might be an error
                error_msg = f"ERC report not generated. "
                if result.stderr:
                    error_msg += f"Error: {result.stderr}"
                return False, [error_msg]

        except subprocess.TimeoutExpired:
            return False, ["ERC timed out after 60 seconds"]
        except Exception as e:
            return False, [f"ERC failed: {str(e)}"]

    def _parse_erc_report(self, report_path: Path) -> List[str]:
        """
        Parse KiCad ERC report for errors.

        Args:
            report_path: Path to ERC report file

        Returns:
            List of error messages

        Notes:
            - Looks for error patterns in report
            - Extracts error count if available
            - Returns generic message if parsing fails
        """
        errors = []

        try:
            with open(report_path, 'r') as f:
                content = f.read()

            # Look for error patterns
            error_patterns = [
                r'\[pin_not_connected\]:.*',
                r'\[label_dangling\]:.*',
                r'\[unconnected_items\]:.*',
                r'\[pin_to_pin\]:.*',
                r'\[power_pin_not_driven\]:.*',
            ]

            for pattern in error_patterns:
                matches = re.findall(pattern, content, re.MULTILINE)
                if matches:
                    # Limit to first 5 matches per type
                    errors.extend(matches[:5])

            # Also check error count summary
            error_count_match = re.search(r'Errors\s+(\d+)', content)
            if error_count_match:
                error_count = int(error_count_match.group(1))
                if error_count > 0 and not errors:
                    errors.append(
                        f"ERC reported {error_count} errors but details not parsed"
                    )

        except Exception as e:
            errors.append(f"Failed to parse ERC report: {e}")

        return errors


# Test function
def test_native_validator():
    """Test the native validator."""
    print("Testing Native Tool Validator...")

    try:
        validator = NativeToolValidator()

        if validator.is_available():
            print("✅ KiCad CLI found - native validation available")
        else:
            print("⚠️  KiCad CLI not found - native validation unavailable")
            print("   This is OK for development, but recommended for production")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    test_native_validator()
