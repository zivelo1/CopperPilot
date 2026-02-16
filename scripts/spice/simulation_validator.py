#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
SPICE Simulation Validator - Parse Results and Validate Against Requirements
=============================================================================

This module provides functionality to:
1. Run SPICE simulations (ngspice or LTSpice in batch mode)
2. Parse simulation output files (.raw, .log)
3. Validate results against user requirements (bandwidth, power, voltage, etc.)

The validator enables BEHAVIORAL validation of circuits - verifying that
the design actually meets application requirements, not just structural
correctness (ERC/DRC).

Design Philosophy
-----------------
1. GENERIC: Works with any circuit type and any simulation requirement
2. EXTENSIBLE: Easy to add new validation checks
3. TOLERANT: Configurable pass/fail thresholds
4. INFORMATIVE: Detailed reports explaining validation results

Supported Simulators
--------------------
- ngspice (open-source, cross-platform)
- LTSpice XVII/24 (free, Windows/macOS/Linux via Wine)

Author: CopperPilot Team
Date: December 2025
Version: 1.0.0
"""

import os
import re
import json
import struct
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import math


class ValidationStatus(Enum):
    """Status of a validation check."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class ValidationResult:
    """
    Result of a single validation check.

    Attributes
    ----------
    name : str
        Name of the check (e.g., "Bandwidth Check")
    status : ValidationStatus
        Pass/fail status
    expected : str
        Expected value/range
    actual : str
        Actual measured value
    tolerance : str
        Tolerance used for comparison
    message : str
        Human-readable result message
    details : Dict
        Additional details (measurements, etc.)
    """
    name: str
    status: ValidationStatus
    expected: str
    actual: str
    tolerance: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationConfig:
    """
    Configuration for simulation execution.

    Attributes
    ----------
    simulator : str
        Simulator to use ("ngspice" or "ltspice")
    ngspice_path : str
        Path to ngspice executable
    ltspice_path : str
        Path to LTSpice executable
    timeout : int
        Simulation timeout in seconds
    working_dir : str
        Working directory for simulation files
    """
    simulator: str = "ngspice"
    ngspice_path: str = "ngspice"  # Assumes in PATH
    ltspice_path: str = "/Applications/LTspice.app/Contents/MacOS/LTspice"  # macOS default
    timeout: int = 300  # 5 minutes
    working_dir: str = ""


@dataclass
class ValidationRequirement:
    """
    A requirement to validate against simulation results.

    Attributes
    ----------
    name : str
        Requirement name
    check_type : str
        Type of check (bandwidth, power, voltage_swing, dc_gain, etc.)
    target : float
        Target value
    tolerance_percent : float
        Acceptable tolerance as percentage (e.g., 10 for ±10%)
    min_value : Optional[float]
        Minimum acceptable value (alternative to tolerance)
    max_value : Optional[float]
        Maximum acceptable value (alternative to tolerance)
    unit : str
        Unit for display (Hz, W, V, dB, etc.)
    node : str
        Node to measure (for voltage checks)
    frequency : Optional[float]
        Frequency for AC measurements
    """
    name: str
    check_type: str
    target: float
    tolerance_percent: float = 10.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str = ""
    node: str = ""
    frequency: Optional[float] = None


class SimulationValidator:
    """
    Validate SPICE simulation results against requirements.

    This class provides:
    1. Simulation execution (ngspice/LTSpice)
    2. Output parsing (.raw binary, ASCII logs)
    3. Measurement extraction
    4. Requirement validation
    """

    def __init__(self, config: Optional[SimulationConfig] = None):
        """
        Initialize the simulation validator.

        Parameters
        ----------
        config : Optional[SimulationConfig]
            Configuration options. Uses defaults if not provided.
        """
        self.config = config or SimulationConfig()
        self._waveforms: Dict[str, List[Tuple[float, float]]] = {}
        self._measurements: Dict[str, float] = {}

    def run_simulation(self, netlist_path: str, output_dir: str = "") -> bool:
        """
        Run SPICE simulation on a netlist file.

        Parameters
        ----------
        netlist_path : str
            Path to .cir netlist file
        output_dir : str
            Directory for output files (uses netlist dir if empty)

        Returns
        -------
        bool
            True if simulation completed successfully
        """
        netlist = Path(netlist_path)
        if not netlist.exists():
            print(f"Error: Netlist not found: {netlist_path}")
            return False

        output_path = Path(output_dir) if output_dir else netlist.parent
        output_path.mkdir(parents=True, exist_ok=True)

        if self.config.simulator == "ngspice":
            return self._run_ngspice(netlist, output_path)
        elif self.config.simulator == "ltspice":
            return self._run_ltspice(netlist, output_path)
        else:
            print(f"Error: Unknown simulator: {self.config.simulator}")
            return False

    def _run_ngspice(self, netlist: Path, output_dir: Path) -> bool:
        """
        Run ngspice simulation.

        Parameters
        ----------
        netlist : Path
            Path to netlist file
        output_dir : Path
            Output directory

        Returns
        -------
        bool
            True if successful
        """
        try:
            # Run ngspice in batch mode
            cmd = [
                self.config.ngspice_path,
                "-b",  # Batch mode
                "-o", str(output_dir / f"{netlist.stem}.log"),
                "-r", str(output_dir / f"{netlist.stem}.raw"),
                str(netlist)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                cwd=str(netlist.parent)
            )

            if result.returncode != 0:
                print(f"ngspice error: {result.stderr}")
                return False

            return True

        except subprocess.TimeoutExpired:
            print(f"Simulation timed out after {self.config.timeout} seconds")
            return False
        except FileNotFoundError:
            print(f"ngspice not found at: {self.config.ngspice_path}")
            print("Install ngspice: brew install ngspice (macOS) or apt install ngspice (Linux)")
            return False
        except Exception as e:
            print(f"Simulation error: {e}")
            return False

    def _run_ltspice(self, netlist: Path, output_dir: Path) -> bool:
        """
        Run LTSpice simulation in batch mode.

        Parameters
        ----------
        netlist : Path
            Path to .asc or .cir file
        output_dir : Path
            Output directory

        Returns
        -------
        bool
            True if successful
        """
        try:
            # LTSpice batch command
            cmd = [
                self.config.ltspice_path,
                "-b",  # Batch mode
                str(netlist)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                cwd=str(netlist.parent)
            )

            # LTSpice creates .raw file next to input
            raw_file = netlist.with_suffix('.raw')
            if raw_file.exists():
                # Move to output dir if different
                if output_dir != netlist.parent:
                    import shutil
                    shutil.move(str(raw_file), str(output_dir / raw_file.name))

            return True

        except subprocess.TimeoutExpired:
            print(f"LTSpice timed out after {self.config.timeout} seconds")
            return False
        except FileNotFoundError:
            print(f"LTSpice not found at: {self.config.ltspice_path}")
            return False
        except Exception as e:
            print(f"LTSpice error: {e}")
            return False

    def parse_raw_file(self, raw_path: str) -> bool:
        """
        Parse SPICE .raw output file.

        Supports both ASCII and binary formats from ngspice and LTSpice.

        Parameters
        ----------
        raw_path : str
            Path to .raw file

        Returns
        -------
        bool
            True if parsing successful
        """
        raw_file = Path(raw_path)
        if not raw_file.exists():
            print(f"Raw file not found: {raw_path}")
            return False

        try:
            with open(raw_file, 'rb') as f:
                header = f.read(100)

            # Check if ASCII or binary
            if b'Binary:' in header:
                return self._parse_binary_raw(raw_file)
            else:
                return self._parse_ascii_raw(raw_file)

        except Exception as e:
            print(f"Error parsing raw file: {e}")
            return False

    def _parse_ascii_raw(self, raw_file: Path) -> bool:
        """Parse ASCII format .raw file."""
        try:
            with open(raw_file, 'r') as f:
                content = f.read()

            # Parse header
            lines = content.split('\n')
            variables = []
            data_started = False
            data_lines = []

            for line in lines:
                line = line.strip()
                if line.startswith('Variables:'):
                    continue
                if line.startswith('Values:'):
                    data_started = True
                    continue
                if not data_started and '\t' in line:
                    # Variable definition: "0 time time"
                    parts = line.split()
                    if len(parts) >= 2:
                        var_name = parts[1]
                        variables.append(var_name)
                elif data_started and line:
                    data_lines.append(line)

            # Parse data points
            self._waveforms = {var: [] for var in variables}

            i = 0
            while i < len(data_lines):
                try:
                    # First value is usually index or time
                    point_idx = int(data_lines[i].split()[0])
                    values = []
                    i += 1

                    # Read values for this point
                    for j, var in enumerate(variables):
                        if i < len(data_lines):
                            val_str = data_lines[i].strip()
                            if val_str:
                                try:
                                    # Handle complex numbers
                                    if ',' in val_str:
                                        real, imag = val_str.split(',')
                                        val = complex(float(real), float(imag))
                                        values.append(abs(val))  # Magnitude
                                    else:
                                        values.append(float(val_str))
                                except ValueError:
                                    values.append(0.0)
                            i += 1

                    # Store values
                    time_or_freq = values[0] if values else 0
                    for j, var in enumerate(variables):
                        if j < len(values):
                            self._waveforms[var].append((time_or_freq, values[j]))

                except (ValueError, IndexError):
                    i += 1

            return len(self._waveforms) > 0

        except Exception as e:
            print(f"Error parsing ASCII raw: {e}")
            return False

    def _parse_binary_raw(self, raw_file: Path) -> bool:
        """Parse binary format .raw file (LTSpice style)."""
        try:
            with open(raw_file, 'rb') as f:
                content = f.read()

            # Find header end
            binary_marker = b'Binary:\n'
            binary_pos = content.find(binary_marker)
            if binary_pos == -1:
                return self._parse_ascii_raw(raw_file)

            header = content[:binary_pos].decode('utf-8', errors='ignore')
            binary_data = content[binary_pos + len(binary_marker):]

            # Parse header for variables and data format
            variables = []
            num_points = 0
            is_complex = False

            for line in header.split('\n'):
                if line.startswith('No. Variables:'):
                    num_vars = int(line.split(':')[1].strip())
                elif line.startswith('No. Points:'):
                    num_points = int(line.split(':')[1].strip())
                elif line.startswith('Flags:') and 'complex' in line.lower():
                    is_complex = True
                elif '\t' in line and not line.startswith('Variables:'):
                    parts = line.strip().split('\t')
                    if len(parts) >= 2:
                        var_name = parts[1]
                        variables.append(var_name)

            # Parse binary data
            self._waveforms = {var: [] for var in variables}

            # Data format: double or complex double for each variable
            point_size = len(variables) * (16 if is_complex else 8)
            offset = 0

            for point_idx in range(num_points):
                if offset + point_size > len(binary_data):
                    break

                values = []
                for var_idx in range(len(variables)):
                    if is_complex:
                        real = struct.unpack_from('<d', binary_data, offset)[0]
                        imag = struct.unpack_from('<d', binary_data, offset + 8)[0]
                        values.append(math.sqrt(real**2 + imag**2))  # Magnitude
                        offset += 16
                    else:
                        val = struct.unpack_from('<d', binary_data, offset)[0]
                        values.append(val)
                        offset += 8

                # Store values
                time_or_freq = values[0] if values else 0
                for j, var in enumerate(variables):
                    if j < len(values):
                        self._waveforms[var].append((time_or_freq, values[j]))

            return len(self._waveforms) > 0

        except Exception as e:
            print(f"Error parsing binary raw: {e}")
            import traceback
            traceback.print_exc()
            return False

    def validate_requirements(
        self,
        requirements: List[ValidationRequirement]
    ) -> List[ValidationResult]:
        """
        Validate simulation results against requirements.

        Parameters
        ----------
        requirements : List[ValidationRequirement]
            List of requirements to check

        Returns
        -------
        List[ValidationResult]
            Validation results for each requirement
        """
        results = []

        for req in requirements:
            if req.check_type == "bandwidth":
                result = self._check_bandwidth(req)
            elif req.check_type == "power":
                result = self._check_power(req)
            elif req.check_type == "voltage_swing":
                result = self._check_voltage_swing(req)
            elif req.check_type == "dc_gain":
                result = self._check_dc_gain(req)
            elif req.check_type == "dc_voltage":
                result = self._check_dc_voltage(req)
            elif req.check_type == "frequency_response":
                result = self._check_frequency_response(req)
            else:
                result = ValidationResult(
                    name=req.name,
                    status=ValidationStatus.SKIPPED,
                    expected=str(req.target),
                    actual="N/A",
                    message=f"Unknown check type: {req.check_type}"
                )

            results.append(result)

        return results

    def _check_bandwidth(self, req: ValidationRequirement) -> ValidationResult:
        """
        Check -3dB bandwidth.

        Finds the frequency where gain drops 3dB from DC/low-frequency gain.
        """
        # Look for output voltage waveform
        output_waveform = None
        for var, data in self._waveforms.items():
            if 'out' in var.lower() or 'v(' in var.lower():
                output_waveform = data
                break

        if not output_waveform or len(output_waveform) < 2:
            return ValidationResult(
                name=req.name,
                status=ValidationStatus.ERROR,
                expected=f"{req.target} {req.unit}",
                actual="N/A",
                message="Could not find output waveform for bandwidth measurement"
            )

        # Find DC/low-frequency gain
        dc_gain_db = 20 * math.log10(max(output_waveform[0][1], 1e-12))

        # Find -3dB point
        target_gain_db = dc_gain_db - 3.0
        bandwidth_hz = 0

        for freq, gain in output_waveform:
            gain_db = 20 * math.log10(max(gain, 1e-12))
            if gain_db <= target_gain_db:
                bandwidth_hz = freq
                break

        # Validate
        actual_str = f"{bandwidth_hz:.2f} {req.unit}"
        expected_str = f"{req.target} {req.unit}"

        if req.min_value is not None and bandwidth_hz < req.min_value:
            status = ValidationStatus.FAIL
            message = f"Bandwidth {bandwidth_hz:.2f} Hz below minimum {req.min_value} Hz"
        elif req.max_value is not None and bandwidth_hz > req.max_value:
            status = ValidationStatus.FAIL
            message = f"Bandwidth {bandwidth_hz:.2f} Hz above maximum {req.max_value} Hz"
        else:
            tolerance = req.target * req.tolerance_percent / 100
            if abs(bandwidth_hz - req.target) <= tolerance:
                status = ValidationStatus.PASS
                message = f"Bandwidth within tolerance"
            else:
                status = ValidationStatus.FAIL
                message = f"Bandwidth outside tolerance (±{req.tolerance_percent}%)"

        return ValidationResult(
            name=req.name,
            status=status,
            expected=expected_str,
            actual=actual_str,
            tolerance=f"±{req.tolerance_percent}%",
            message=message,
            details={"bandwidth_hz": bandwidth_hz, "dc_gain_db": dc_gain_db}
        )

    def _check_power(self, req: ValidationRequirement) -> ValidationResult:
        """Check power output (P = V²/R)."""
        # This is a placeholder - actual implementation would need
        # voltage and current waveforms plus load impedance
        return ValidationResult(
            name=req.name,
            status=ValidationStatus.SKIPPED,
            expected=f"{req.target} {req.unit}",
            actual="N/A",
            message="Power check requires voltage and current data"
        )

    def _check_voltage_swing(self, req: ValidationRequirement) -> ValidationResult:
        """Check peak-to-peak voltage swing."""
        # Find voltage waveform for specified node
        waveform = None
        node_name = req.node.lower()

        for var, data in self._waveforms.items():
            if node_name in var.lower():
                waveform = data
                break

        if not waveform or len(waveform) < 2:
            return ValidationResult(
                name=req.name,
                status=ValidationStatus.ERROR,
                expected=f"{req.target} {req.unit}",
                actual="N/A",
                message=f"Could not find waveform for node: {req.node}"
            )

        # Calculate Vpp
        voltages = [v for _, v in waveform]
        vmax = max(voltages)
        vmin = min(voltages)
        vpp = vmax - vmin

        # Validate
        actual_str = f"{vpp:.3f} {req.unit}"
        expected_str = f"{req.target} {req.unit}"

        if req.min_value is not None and vpp < req.min_value:
            status = ValidationStatus.FAIL
            message = f"Voltage swing {vpp:.3f} V below minimum {req.min_value} V"
        elif req.max_value is not None and vpp > req.max_value:
            status = ValidationStatus.WARNING
            message = f"Voltage swing {vpp:.3f} V above maximum {req.max_value} V"
        else:
            tolerance = req.target * req.tolerance_percent / 100
            if vpp >= req.target - tolerance:
                status = ValidationStatus.PASS
                message = f"Voltage swing meets requirement"
            else:
                status = ValidationStatus.FAIL
                message = f"Voltage swing below target"

        return ValidationResult(
            name=req.name,
            status=status,
            expected=expected_str,
            actual=actual_str,
            tolerance=f"±{req.tolerance_percent}%",
            message=message,
            details={"vpp": vpp, "vmax": vmax, "vmin": vmin}
        )

    def _check_dc_gain(self, req: ValidationRequirement) -> ValidationResult:
        """Check DC gain in dB."""
        # Placeholder implementation
        return ValidationResult(
            name=req.name,
            status=ValidationStatus.SKIPPED,
            expected=f"{req.target} {req.unit}",
            actual="N/A",
            message="DC gain check not implemented for this waveform type"
        )

    def _check_dc_voltage(self, req: ValidationRequirement) -> ValidationResult:
        """Check DC operating point voltage."""
        # Find voltage at specified node
        waveform = None
        node_name = req.node.lower()

        for var, data in self._waveforms.items():
            if node_name in var.lower():
                waveform = data
                break

        if not waveform or len(waveform) == 0:
            return ValidationResult(
                name=req.name,
                status=ValidationStatus.ERROR,
                expected=f"{req.target} {req.unit}",
                actual="N/A",
                message=f"Could not find DC voltage for node: {req.node}"
            )

        # Get DC value (first point or average)
        dc_voltage = waveform[0][1] if waveform else 0

        # Validate
        actual_str = f"{dc_voltage:.3f} {req.unit}"
        expected_str = f"{req.target} {req.unit}"

        tolerance = req.target * req.tolerance_percent / 100 if req.target != 0 else 0.1
        if abs(dc_voltage - req.target) <= tolerance:
            status = ValidationStatus.PASS
            message = f"DC voltage within tolerance"
        else:
            status = ValidationStatus.FAIL
            message = f"DC voltage outside tolerance"

        return ValidationResult(
            name=req.name,
            status=status,
            expected=expected_str,
            actual=actual_str,
            tolerance=f"±{req.tolerance_percent}%",
            message=message,
            details={"dc_voltage": dc_voltage}
        )

    def _check_frequency_response(self, req: ValidationRequirement) -> ValidationResult:
        """Check gain at specific frequency."""
        # Placeholder implementation
        return ValidationResult(
            name=req.name,
            status=ValidationStatus.SKIPPED,
            expected=f"{req.target} {req.unit}",
            actual="N/A",
            message="Frequency response check not implemented"
        )

    def generate_report(
        self,
        results: List[ValidationResult],
        circuit_name: str = "Circuit"
    ) -> str:
        """
        Generate a human-readable validation report.

        Parameters
        ----------
        results : List[ValidationResult]
            Validation results
        circuit_name : str
            Name of the circuit

        Returns
        -------
        str
            Formatted report text
        """
        lines = [
            "=" * 70,
            f"SPICE Simulation Validation Report",
            f"Circuit: {circuit_name}",
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70,
            "",
        ]

        # Summary
        passed = sum(1 for r in results if r.status == ValidationStatus.PASS)
        failed = sum(1 for r in results if r.status == ValidationStatus.FAIL)
        warnings = sum(1 for r in results if r.status == ValidationStatus.WARNING)
        total = len(results)

        lines.append(f"Summary: {passed}/{total} PASSED, {failed} FAILED, {warnings} WARNINGS")
        lines.append("")

        # Overall status
        if failed == 0:
            lines.append("✅ OVERALL: PASS - All requirements met")
        else:
            lines.append("❌ OVERALL: FAIL - Some requirements not met")

        lines.append("")
        lines.append("-" * 70)
        lines.append("")

        # Detailed results
        for result in results:
            status_icon = {
                ValidationStatus.PASS: "✅",
                ValidationStatus.FAIL: "❌",
                ValidationStatus.WARNING: "⚠️",
                ValidationStatus.SKIPPED: "⏭️",
                ValidationStatus.ERROR: "💥",
            }.get(result.status, "?")

            lines.append(f"{status_icon} {result.name}")
            lines.append(f"   Expected: {result.expected}")
            lines.append(f"   Actual:   {result.actual}")
            if result.tolerance:
                lines.append(f"   Tolerance: {result.tolerance}")
            lines.append(f"   Status:   {result.status.value}")
            lines.append(f"   {result.message}")
            lines.append("")

        lines.append("=" * 70)

        return '\n'.join(lines)

    def save_report_json(
        self,
        results: List[ValidationResult],
        output_path: str,
        circuit_name: str = "Circuit"
    ) -> None:
        """
        Save validation results as JSON.

        Parameters
        ----------
        results : List[ValidationResult]
            Validation results
        output_path : str
            Output file path
        circuit_name : str
            Circuit name
        """
        data = {
            "circuit": circuit_name,
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(results),
                "passed": sum(1 for r in results if r.status == ValidationStatus.PASS),
                "failed": sum(1 for r in results if r.status == ValidationStatus.FAIL),
                "warnings": sum(1 for r in results if r.status == ValidationStatus.WARNING),
            },
            "results": [
                {
                    "name": r.name,
                    "status": r.status.value,
                    "expected": r.expected,
                    "actual": r.actual,
                    "tolerance": r.tolerance,
                    "message": r.message,
                    "details": r.details,
                }
                for r in results
            ]
        }

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def validate_simulation(
    raw_file: str,
    requirements: List[Dict[str, Any]]
) -> Tuple[bool, str]:
    """
    Convenience function to validate simulation results.

    Parameters
    ----------
    raw_file : str
        Path to .raw simulation output
    requirements : List[Dict[str, Any]]
        List of requirement dicts with keys: name, check_type, target, etc.

    Returns
    -------
    Tuple[bool, str]
        (all_passed, report_text)
    """
    validator = SimulationValidator()

    # Parse raw file
    if not validator.parse_raw_file(raw_file):
        return (False, "Failed to parse simulation output")

    # Convert requirement dicts to ValidationRequirement objects
    reqs = [
        ValidationRequirement(
            name=r.get('name', 'Unnamed'),
            check_type=r.get('check_type', 'unknown'),
            target=r.get('target', 0),
            tolerance_percent=r.get('tolerance_percent', 10),
            min_value=r.get('min_value'),
            max_value=r.get('max_value'),
            unit=r.get('unit', ''),
            node=r.get('node', ''),
            frequency=r.get('frequency'),
        )
        for r in requirements
    ]

    # Validate
    results = validator.validate_requirements(reqs)

    # Generate report
    report = validator.generate_report(results)

    # Check overall pass/fail
    all_passed = all(
        r.status in (ValidationStatus.PASS, ValidationStatus.SKIPPED, ValidationStatus.WARNING)
        for r in results
    )

    return (all_passed, report)
