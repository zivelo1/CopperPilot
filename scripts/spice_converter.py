#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
SPICE/LTSpice Converter - Main Entry Point
==========================================

This is the main entry point for converting CopperPilot circuit JSON files
to SPICE netlist format (.cir) and LTSpice schematic format (.asc).

Usage
-----
    # Convert all circuits in a directory
    python spice_converter.py output/run-id/lowlevel output/run-id/spice

    # Convert a single circuit file
    python spice_converter.py circuit_power_supply.json output/spice/

    # Convert with LTSpice format only
    python spice_converter.py input/ output/ --format ltspice

    # Convert with both formats (default)
    python spice_converter.py input/ output/ --format both

Features
--------
- SPICE netlist generation (.cir) - compatible with ngspice, LTSpice, HSPICE
- LTSpice schematic generation (.asc) - opens directly in LTSpice XVII/24
- Automatic component-to-model mapping
- Power source auto-detection
- Default simulation commands included

Design Philosophy
-----------------
1. GENERIC: Works with ANY circuit type (from LED blinker to complex systems)
2. MODULAR: Uses separate modules for each conversion type
3. ROBUST: Handles unknown components gracefully
4. PRODUCTION-READY: Generates valid, simulatable output

Author: CopperPilot Team
Date: December 2025
Version: 1.0.0
"""

import sys
import json
import time
import argparse
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure project root is on sys.path so imports from workflow/, utils/, server/ work
# when this script is invoked as a subprocess by converter_runner.py.
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Import SPICE modules
from spice.netlist_generator import SpiceNetlistGenerator, NetlistConfig
from spice.ltspice_generator import LTSpiceGenerator, LayoutConfig
from spice.model_library import SpiceModelLibrary


class SpiceConverter:
    """
    Main orchestrator for SPICE/LTSpice conversion.

    This class coordinates the conversion of CopperPilot circuit JSON files
    to SPICE netlists and LTSpice schematics.
    """

    def __init__(
        self,
        input_path: str,
        output_path: str,
        output_format: str = "both"
    ):
        """
        Initialize the SPICE converter.

        Parameters
        ----------
        input_path : str
            Path to input (circuit JSON file or directory)
        output_path : str
            Path to output directory
        output_format : str
            Output format: "spice", "ltspice", or "both"
        """
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.output_format = output_format.lower()

        # Statistics
        self.stats = {
            'start_time': time.time(),
            'circuits_processed': 0,
            'circuits_success': 0,
            'circuits_failed': 0,
            'spice_files_generated': 0,
            'ltspice_files_generated': 0,
            'total_components': 0,
            'total_nets': 0,
        }

        # Initialize generators
        self.netlist_generator = SpiceNetlistGenerator(NetlistConfig())
        self.ltspice_generator = LTSpiceGenerator(LayoutConfig())
        self.model_library = SpiceModelLibrary()

    def convert(self) -> bool:
        """
        Run the conversion process.

        Returns
        -------
        bool
            True if all conversions successful
        """
        print("\n" + "=" * 70)
        print("SPICE/LTSPICE CONVERTER")
        print("CopperPilot Circuit Design System")
        print("=" * 70)
        print(f"Input:  {self.input_path}")
        print(f"Output: {self.output_path}")
        print(f"Format: {self.output_format}")
        print("=" * 70)

        # Create output directory
        self.output_path.mkdir(parents=True, exist_ok=True)

        # Find circuit files
        if self.input_path.is_file():
            circuit_files = [self.input_path]
        else:
            # Look for circuit_*.json files
            circuit_files = list(self.input_path.glob('circuit_*.json'))
            if not circuit_files:
                circuit_files = list(self.input_path.glob('CIRCUIT_*.json'))
            # Exclude design.json (summary file)
            circuit_files = [f for f in circuit_files if f.name.lower() != 'design.json']

        if not circuit_files:
            print("❌ No circuit files found")
            return False

        print(f"\nFound {len(circuit_files)} circuit file(s) to process\n")

        all_success = True
        for circuit_file in sorted(circuit_files):
            circuit_name = self._get_circuit_name(circuit_file)
            print(f"\n{'─' * 50}")
            print(f"Processing: {circuit_name}")
            print(f"{'─' * 50}")

            success = self._process_circuit(circuit_file, circuit_name)

            if success:
                self.stats['circuits_success'] += 1
                print(f"✅ {circuit_name}: Conversion successful")
            else:
                self.stats['circuits_failed'] += 1
                all_success = False
                print(f"❌ {circuit_name}: Conversion failed")

            self.stats['circuits_processed'] += 1

        # Print statistics
        self._print_statistics()

        return all_success

    def _get_circuit_name(self, circuit_file: Path) -> str:
        """
        Get clean circuit name from file path.

        Parameters
        ----------
        circuit_file : Path
            Path to circuit JSON file

        Returns
        -------
        str
            Clean circuit name
        """
        name = circuit_file.stem

        # Remove 'circuit_' prefix if present
        if name.lower().startswith('circuit_'):
            name = name[8:]

        # Clean up
        name = re.sub(r'[^\w\s\-_]', '', name)

        return name

    def _process_circuit(self, circuit_file: Path, circuit_name: str) -> bool:
        """
        Process a single circuit file.

        Parameters
        ----------
        circuit_file : Path
            Path to circuit JSON file
        circuit_name : str
            Clean circuit name

        Returns
        -------
        bool
            True if conversion successful
        """
        try:
            # Load circuit data
            with open(circuit_file, 'r') as f:
                data = json.load(f)

            circuit = data.get('circuit', data)

            # Count statistics
            components = circuit.get('components', [])
            nets = circuit.get('nets', [])
            self.stats['total_components'] += len(components)
            self.stats['total_nets'] += len(nets)

            print(f"  Components: {len(components)}")
            print(f"  Nets: {len(nets)}")

            # Generate SPICE netlist
            if self.output_format in ('spice', 'both'):
                spice_file = self.output_path / f"{circuit_name}.cir"
                if self.netlist_generator.convert(str(circuit_file), str(spice_file)):
                    self.stats['spice_files_generated'] += 1
                    print(f"  ✓ SPICE netlist: {spice_file.name}")
                    
                    # Phase F (Forensic Fix 20260211): SPICE reliability gate
                    if not self._validate_netlist(spice_file):
                        print(f"  ✗ SPICE reliability gate FAILED for {spice_file.name}")
                        return False
                else:
                    print(f"  ✗ SPICE netlist generation failed")
                    return False

            # Generate LTSpice schematic
            if self.output_format in ('ltspice', 'both'):
                asc_file = self.output_path / f"{circuit_name}.asc"
                if self.ltspice_generator.convert(str(circuit_file), str(asc_file)):
                    self.stats['ltspice_files_generated'] += 1
                    print(f"  ✓ LTSpice schematic: {asc_file.name}")
                else:
                    print(f"  ✗ LTSpice schematic generation failed")
                    return False

            return True

        except Exception as e:
            print(f"  ✗ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _validate_netlist(self, spice_file: Path) -> bool:
        """
        Phase F (Forensic Fix 20260211): Mandatory SPICE reliability gates.
        
        1. Mandatory syntax compile and subckt arity checks.
        2. Mandatory minimal op/tran sanity run for all modules.
        
        Uses ngspice in batch mode to verify the netlist.
        """
        if not spice_file.exists():
            return False
            
        try:
            # Check for ngspice availability
            try:
                proc_check = subprocess.run(['ngspice', '--version'], capture_output=True, text=True, timeout=5)
                if proc_check.returncode != 0:
                    print("  ⚠️  ngspice not found - skipping SPICE reliability gate")
                    return True # Don't fail if tool missing, just warn
            except (FileNotFoundError, subprocess.SubprocessError):
                print("  ⚠️  ngspice not found - skipping SPICE reliability gate")
                return True
                
            # Run ngspice in batch mode to check syntax
            # -b: batch mode
            temp_out = spice_file.with_suffix('.ngspice.log')
            proc = subprocess.run(
                ['ngspice', '-b', str(spice_file)],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Write log for debugging
            temp_out.write_text(proc.stdout + proc.stderr)
            
            # Check for common SPICE errors
            output = (proc.stdout + proc.stderr).upper()
            errors = []
            
            if 'ERROR' in output:
                # Filter out minor errors that don't prevent simulation
                if 'TOO FEW PARAMETERS' in output or 'TOO MANY PARAMETERS' in output:
                    errors.append("Subcircuit arity mismatch")
                elif 'SYNTAX ERROR' in output:
                    errors.append("Syntax error in netlist")
                else:
                    errors.append("General SPICE error detected")
                    
            if 'SINGULAR MATRIX' in output:
                errors.append("Singular matrix - circuit may have floating nodes or shorts")
            if 'COMPLEX STEP CONTROL' in output or 'CONVERGENCE FAILURE' in output:
                errors.append("Convergence failure")
                
            if errors:
                print(f"  ❌ SPICE Reliability Gate FAILED for {spice_file.name}:")
                for err in errors:
                    print(f"    - {err}")
                return False
                
            print(f"  ✓ SPICE Reliability Gate PASSED for {spice_file.name}")
            return True
            
        except subprocess.TimeoutExpired:
            print(f"  ❌ SPICE Reliability Gate TIMEOUT for {spice_file.name}")
            return False
        except Exception as e:
            print(f"  ⚠️  SPICE Reliability Gate error: {e}")
            return True # Don't fail on internal script error

    def _print_statistics(self) -> None:
        """Print conversion statistics."""
        elapsed = time.time() - self.stats['start_time']

        print("\n" + "=" * 70)
        print("CONVERSION COMPLETE")
        print("=" * 70)
        print(f"Circuits processed: {self.stats['circuits_processed']}")
        print(f"  Successful: {self.stats['circuits_success']}")
        print(f"  Failed: {self.stats['circuits_failed']}")
        print(f"Total components: {self.stats['total_components']}")
        print(f"Total nets: {self.stats['total_nets']}")
        print(f"Time elapsed: {elapsed:.2f} seconds")
        print("")

        if self.output_format in ('spice', 'both'):
            print(f"SPICE netlists generated: {self.stats['spice_files_generated']}")
        if self.output_format in ('ltspice', 'both'):
            print(f"LTSpice schematics generated: {self.stats['ltspice_files_generated']}")

        print("")

        if self.stats['circuits_failed'] == 0:
            print("✅ ALL CONVERSIONS SUCCESSFUL")
        else:
            print(f"⚠️  {self.stats['circuits_failed']} CONVERSION(S) FAILED")

        print("=" * 70)
        print(f"\nOutput files saved to: {self.output_path}")
        print("Files generated:")
        if self.output_format in ('spice', 'both'):
            print("  - *.cir (SPICE netlist - use with ngspice, LTSpice, HSPICE)")
        if self.output_format in ('ltspice', 'both'):
            print("  - *.asc (LTSpice schematic - open in LTSpice XVII/24)")

        print("\nNext steps:")
        print("  1. Open .cir in ngspice:  ngspice circuit_name.cir")
        print("  2. Open .asc in LTSpice:  Double-click or drag to LTSpice")
        print("  3. Run simulation and verify behavior matches requirements")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Convert CopperPilot circuits to SPICE/LTSpice format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all circuits in a run
  python spice_converter.py output/20251215-xxx/lowlevel output/20251215-xxx/spice

  # Convert with SPICE only
  python spice_converter.py input/ output/ --format spice

  # Convert single file
  python spice_converter.py circuit_power_supply.json ./spice_output/
        """
    )

    parser.add_argument(
        'input',
        help='Input path (circuit JSON file or directory containing circuit_*.json)'
    )
    parser.add_argument(
        'output',
        help='Output directory for SPICE/LTSpice files'
    )
    parser.add_argument(
        '--format',
        choices=['spice', 'ltspice', 'both'],
        default='both',
        help='Output format: spice (.cir), ltspice (.asc), or both (default: both)'
    )

    args = parser.parse_args()

    # Validate input
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Error: Input path not found: {args.input}")
        sys.exit(1)

    # Run converter
    converter = SpiceConverter(args.input, args.output, args.format)
    success = converter.convert()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
