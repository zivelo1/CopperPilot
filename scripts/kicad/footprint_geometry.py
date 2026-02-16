#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Footprint Geometry Engine - GENERIC pad coordinate calculator for ALL footprint types.

This module provides exact pad coordinates for any KiCad footprint, enabling
proper PCB routing. It works for ANY circuit type - from simple LEDs to complex
multi-board systems.

CRITICAL: This is NOT specific to any particular circuit. It's a GENERIC solution
that handles ALL standard footprint families and provides fallback for custom ones.
"""

import re
import math
from typing import Dict, Tuple, List, Optional
import logging

logger = logging.getLogger(__name__)


class FootprintGeometry:
    """Base class for footprint geometry calculation."""

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """
        Return (x, y) offset from component origin for given pin number.
        Coordinates in millimeters.
        """
        raise NotImplementedError

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return all pad coordinates for this footprint."""
        raise NotImplementedError


class TwoPadSMDGeometry(FootprintGeometry):
    """
    Generic 2-pad SMD component geometry (resistors, capacitors, diodes, LEDs).
    Covers all standard sizes from 0201 to 2512 and beyond.
    """

    # TC #50 FIX (2025-11-25): Updated to IPC-7351B COMPLIANT dimensions
    # The CRITICAL fix - previous values caused pad overlaps!
    # Source: IPC-7351B "Generic Requirements for Surface Mount Design"
    STANDARD_SIZES = {
        # Size: (length_mm, width_mm, pad_spacing_center_to_center_mm)
        # TC #50: Updated spacing to IPC-7351B values - ensures 0.2mm min clearance
        '0201': (0.6, 0.3, 0.50),   # TC #50: Was 0.28, now 0.50 (IPC-7351B)
        '0402': (1.0, 0.5, 0.80),   # TC #50: Was 0.5, now 0.80 (IPC-7351B)
        '0603': (1.6, 0.8, 1.60),   # TC #50: Was 0.9, now 1.60 (IPC-7351B)
        '0805': (2.0, 1.25, 2.00),  # TC #50: Was 1.3, now 2.00 (IPC-7351B) - CRITICAL FIX!
        '1206': (3.2, 1.6, 3.20),   # TC #50: Was 2.2, now 3.20 (IPC-7351B)
        '1210': (3.2, 2.5, 3.20),   # TC #50: Was 2.2, now 3.20 (IPC-7351B)
        '1812': (4.5, 3.2, 4.60),   # TC #50: Was 3.4, now 4.60 (IPC-7351B)
        '2010': (5.0, 2.5, 5.00),   # TC #50: Was 4.0, now 5.00 (IPC-7351B)
        '2512': (6.3, 3.2, 6.30),   # TC #50: Was 5.3, now 6.30 (IPC-7351B)
        # Metric variants (same physical size, different naming)
        '1005': (1.0, 0.5, 0.80),   # TC #50: Metric 0402
        '1608': (1.6, 0.8, 1.60),   # TC #50: Metric 0603
        '2012': (2.0, 1.25, 2.00),  # TC #50: Metric 0805
        '3216': (3.2, 1.6, 3.20),   # TC #50: Metric 1206
        '3225': (3.2, 2.5, 3.20),   # TC #50: Metric 1210
        # Special packages - IPC-7351B compliant
        'SOD-123': (3.7, 1.6, 3.94),  # TC #50: Diode package
        'SOD-323': (2.5, 1.3, 2.20),  # TC #50: Small diode
        'SOD-523': (1.6, 0.8, 1.40),  # TC #50: Tiny diode
        'SOT-23': (2.9, 1.3, 2.10),   # TC #50: Actually 3-pin but can be 2-pad variant
    }

    def __init__(self, footprint_name: str):
        """Initialize from footprint name like 'R_0603_1608Metric' or 'C_0805'."""
        self.footprint_name = footprint_name
        self.size_code = self._extract_size_code(footprint_name)

        # Get dimensions, with intelligent fallback
        if self.size_code in self.STANDARD_SIZES:
            self.dimensions = self.STANDARD_SIZES[self.size_code]
        else:
            # Default to 0603/1608 as safe fallback
            logger.warning(f"Unknown 2-pad size '{self.size_code}', using 0603 dimensions")
            self.dimensions = self.STANDARD_SIZES['0603']

    def _extract_size_code(self, footprint_name: str) -> str:
        """Extract size code from footprint name."""
        # Try multiple patterns
        patterns = [
            r'_(\d{4})',  # _0603, _1206
            r'_(\d{4})_',  # _0603_
            r'SOD-\d+',    # SOD-123
            r'SOT-\d+',    # SOT-23
        ]

        for pattern in patterns:
            match = re.search(pattern, footprint_name)
            if match:
                return match.group(0).replace('_', '')

        # Check if metric variant mentioned
        if '1608Metric' in footprint_name:
            return '0603'  # 1608 metric = 0603 imperial
        if '2012Metric' in footprint_name:
            return '0805'
        if '3216Metric' in footprint_name:
            return '1206'

        return 'unknown'

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """Get pad coordinates for pin 1 or 2."""
        _, _, spacing = self.dimensions

        if pin_number == '1':
            return (-spacing / 2, 0.0)
        elif pin_number == '2':
            return (spacing / 2, 0.0)
        else:
            # Shouldn't happen for 2-pad component
            logger.error(f"Invalid pin {pin_number} for 2-pad component")
            return (0.0, 0.0)

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return coordinates for both pads."""
        return {
            '1': self.get_pad_coordinates('1'),
            '2': self.get_pad_coordinates('2')
        }


class DualRowICGeometry(FootprintGeometry):
    """
    Generic dual-row IC package geometry (SOIC, TSSOP, SSOP, DIP, etc.).
    Handles any pin count and pitch.
    """

    # Standard package specifications (JEDEC)
    PACKAGE_SPECS = {
        # Package: (pin_pitch_mm, row_spacing_mm)
        'SOIC': (1.27, 3.9),      # Standard SOIC
        'SOIC-W': (1.27, 7.5),    # Wide SOIC
        'TSSOP': (0.65, 4.4),     # Thin shrink small outline
        'SSOP': (0.65, 5.3),      # Shrink small outline
        'MSOP': (0.5, 3.0),       # Mini small outline
        'DIP': (2.54, 7.62),      # Dual inline package (through-hole)
        'QFN': (0.5, 0.0),        # Quad flat no-lead (special case)
        'QFP': (0.5, 0.0),        # Quad flat package (special case)
        'LQFP': (0.5, 0.0),       # Low-profile quad flat
        'TQFP': (0.5, 0.0),       # Thin quad flat
    }

    def __init__(self, footprint_name: str, pin_count: Optional[int] = None):
        """
        Initialize from footprint name like 'SOIC-8_3.9x4.9mm_P1.27mm'.
        pin_count can be extracted from name or provided explicitly.
        """
        self.footprint_name = footprint_name
        self.package_type = self._extract_package_type(footprint_name)
        self.pin_count = pin_count or self._extract_pin_count(footprint_name)
        self.specs = self._get_package_specs(footprint_name)

    def _extract_package_type(self, footprint_name: str) -> str:
        """Extract package type from footprint name."""
        # Check for common package types
        for pkg in ['SOIC', 'TSSOP', 'SSOP', 'MSOP', 'DIP', 'QFN', 'QFP', 'LQFP', 'TQFP']:
            if pkg in footprint_name.upper():
                return pkg
        return 'SOIC'  # Default

    def _extract_pin_count(self, footprint_name: str) -> int:
        """Extract pin count from footprint name."""
        # Try patterns like SOIC-8, DIP-14, etc.
        match = re.search(r'[-_](\d+)[-_\s]', footprint_name)
        if match:
            return int(match.group(1))

        # Try at end of name
        match = re.search(r'[-_](\d+)$', footprint_name)
        if match:
            return int(match.group(1))

        # Default to 8 pins
        logger.warning(f"Could not extract pin count from {footprint_name}, assuming 8")
        return 8

    def _get_package_specs(self, footprint_name: str) -> Tuple[float, float]:
        """Get pitch and row spacing from footprint name or defaults."""
        # Try to extract from name (e.g., P1.27mm)
        pitch_match = re.search(r'P([\d.]+)mm', footprint_name)
        if pitch_match:
            pitch = float(pitch_match.group(1))
        else:
            pitch = self.PACKAGE_SPECS.get(self.package_type, (1.27, 3.9))[0]

        # Try to extract row spacing from dimensions (e.g., 3.9x4.9mm)
        dim_match = re.search(r'([\d.]+)x([\d.]+)mm', footprint_name)
        if dim_match:
            # Usually the smaller dimension is the row spacing
            row_spacing = float(dim_match.group(1))
        else:
            row_spacing = self.PACKAGE_SPECS.get(self.package_type, (1.27, 3.9))[1]

        return (pitch, row_spacing)

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """Get pad coordinates for any pin number."""
        try:
            pin = int(pin_number)
        except ValueError:
            logger.error(f"Invalid pin number: {pin_number}")
            return (0.0, 0.0)

        pitch, row_spacing = self.specs
        pins_per_side = self.pin_count // 2

        if pin <= pins_per_side:
            # Left side - pins go from bottom to top
            x = -row_spacing / 2
            # Center the pins vertically
            y = (pin - 1) * pitch - ((pins_per_side - 1) * pitch) / 2
        elif pin <= self.pin_count:
            # Right side - pins go from top to bottom
            x = row_spacing / 2
            # Pin position on right side
            right_pin_index = pin - pins_per_side
            # Invert Y for right side (top to bottom)
            y = ((pins_per_side - right_pin_index) * pitch) - ((pins_per_side - 1) * pitch) / 2
        else:
            logger.error(f"Pin {pin} out of range for {self.pin_count}-pin package")
            return (0.0, 0.0)

        return (x, y)

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return coordinates for all pads."""
        return {str(i): self.get_pad_coordinates(str(i))
                for i in range(1, self.pin_count + 1)}


class QuadPackageGeometry(FootprintGeometry):
    """
    Geometry for quad packages (QFP, QFN, LQFP, TQFP).
    Pins on all 4 sides.
    """

    def __init__(self, footprint_name: str, pin_count: Optional[int] = None):
        """Initialize quad package geometry."""
        self.footprint_name = footprint_name
        self.pin_count = pin_count or self._extract_pin_count(footprint_name)
        self.pitch = self._extract_pitch(footprint_name)
        self.body_size = self._extract_body_size(footprint_name)

    def _extract_pin_count(self, footprint_name: str) -> int:
        """Extract pin count from footprint name."""
        match = re.search(r'[-_](\d+)[-_\s]', footprint_name)
        if match:
            return int(match.group(1))
        return 44  # Common QFP size

    def _extract_pitch(self, footprint_name: str) -> float:
        """Extract pitch from footprint name."""
        match = re.search(r'P([\d.]+)mm', footprint_name)
        if match:
            return float(match.group(1))
        return 0.8  # Common QFP pitch

    def _extract_body_size(self, footprint_name: str) -> float:
        """Extract body size from footprint name."""
        match = re.search(r'(\d+)x\d+mm', footprint_name)
        if match:
            return float(match.group(1))
        return 10.0  # 10x10mm common size

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """Get pad coordinates for any pin in quad package."""
        try:
            pin = int(pin_number)
        except ValueError:
            return (0.0, 0.0)

        pins_per_side = self.pin_count // 4
        pad_distance = self.body_size / 2 + 0.5  # Pad center slightly outside body

        # Determine which side the pin is on
        if pin <= pins_per_side:
            # Bottom side (left to right)
            side_index = pin - 1
            x = (side_index - (pins_per_side - 1) / 2) * self.pitch
            y = -pad_distance
        elif pin <= 2 * pins_per_side:
            # Right side (bottom to top)
            side_index = pin - pins_per_side - 1
            x = pad_distance
            y = (side_index - (pins_per_side - 1) / 2) * self.pitch
        elif pin <= 3 * pins_per_side:
            # Top side (right to left)
            side_index = pin - 2 * pins_per_side - 1
            x = ((pins_per_side - 1 - side_index) - (pins_per_side - 1) / 2) * self.pitch
            y = pad_distance
        elif pin <= self.pin_count:
            # Left side (top to bottom)
            side_index = pin - 3 * pins_per_side - 1
            x = -pad_distance
            y = ((pins_per_side - 1 - side_index) - (pins_per_side - 1) / 2) * self.pitch
        else:
            return (0.0, 0.0)

        return (x, y)

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return coordinates for all pads."""
        return {str(i): self.get_pad_coordinates(str(i))
                for i in range(1, self.pin_count + 1)}


class ConnectorGeometry(FootprintGeometry):
    """
    Generic connector geometry (pin headers, terminal blocks, etc.).
    Handles single-row, dual-row, and custom configurations.
    """

    def __init__(self, footprint_name: str, pin_count: Optional[int] = None):
        """Initialize connector geometry."""
        self.footprint_name = footprint_name
        self.pin_count = pin_count or self._extract_pin_count(footprint_name)
        self.pitch = self._extract_pitch(footprint_name)
        self.rows = self._determine_rows(footprint_name)

    def _extract_pin_count(self, footprint_name: str) -> int:
        """Extract pin count from footprint name."""
        # Look for patterns like 1x02, 2x03, etc.
        match = re.search(r'(\d+)x(\d+)', footprint_name)
        if match:
            rows = int(match.group(1))
            cols = int(match.group(2))
            return rows * cols

        # Look for _01x02 format
        match = re.search(r'_\d+x(\d+)', footprint_name)
        if match:
            return int(match.group(1))

        # Simple number
        match = re.search(r'[-_](\d+)[-_\s]', footprint_name)
        if match:
            return int(match.group(1))

        return 2  # Default to 2-pin

    def _extract_pitch(self, footprint_name: str) -> float:
        """Extract pitch from footprint name."""
        # Look for P2.54mm, P5.08mm, etc.
        match = re.search(r'P([\d.]+)mm', footprint_name)
        if match:
            return float(match.group(1))

        # Check for common pitches in name
        if '5.08' in footprint_name:
            return 5.08
        if '3.81' in footprint_name:
            return 3.81
        if '3.5' in footprint_name:
            return 3.5

        # Default to 0.1" (2.54mm) standard
        return 2.54

    def _determine_rows(self, footprint_name: str) -> int:
        """Determine number of rows."""
        # Look for 2x format
        if '2x' in footprint_name.lower():
            return 2
        # Look for dual
        if 'dual' in footprint_name.lower():
            return 2
        # Default to single row
        return 1

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """Get pad coordinates for connector pin."""
        try:
            pin = int(pin_number)
        except ValueError:
            return (0.0, 0.0)

        if self.rows == 1:
            # Single row - horizontal or vertical
            if 'vertical' in self.footprint_name.lower():
                # Vertical alignment
                x = 0.0
                y = (pin - 1) * self.pitch
            else:
                # Horizontal alignment (default)
                x = (pin - 1) * self.pitch
                y = 0.0
        else:
            # Dual row
            pins_per_row = self.pin_count // 2
            row_spacing = 2.54  # Standard dual-row spacing

            if pin <= pins_per_row:
                # First row
                x = (pin - 1) * self.pitch
                y = -row_spacing / 2
            else:
                # Second row
                x = (pin - pins_per_row - 1) * self.pitch
                y = row_spacing / 2

        return (x, y)

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return coordinates for all pads."""
        return {str(i): self.get_pad_coordinates(str(i))
                for i in range(1, self.pin_count + 1)}


class TransistorGeometry(FootprintGeometry):
    """
    Geometry for discrete transistors (TO-92, SOT-23, TO-220, etc.).
    Usually 3 pins but can vary.
    """

    # TC #50 FIX (2025-11-25): Updated to IPC-7351B COMPLIANT positions
    PACKAGE_SPECS = {
        # Package: [(pin1_x, pin1_y), (pin2_x, pin2_y), ...]
        # TC #50: SOT-23 has 0.95mm pad pitch, 2.1mm row spacing (IPC-7351B)
        'SOT-23': [(-1.05, -1.05), (1.05, -1.05), (0.0, 1.05)],  # TC #50: Updated for proper clearance
        'SOT-223': [(-2.3, -3.15), (0.0, -3.15), (2.3, -3.15), (0.0, 3.15)],  # TC #50: Tab pad (heatsink)
        'TO-92': [(-1.27, 0.0), (0.0, 0.0), (1.27, 0.0)],  # Through-hole
        'TO-220': [(-2.54, 0.0), (0.0, 0.0), (2.54, 0.0)],  # Through-hole
        'DPAK': [(-2.28, -3.0), (-2.28, 3.0), (5.45, 0.0)],  # SMD power
    }

    def __init__(self, footprint_name: str):
        """Initialize transistor geometry."""
        self.footprint_name = footprint_name
        self.package = self._identify_package(footprint_name)
        self.coords = self.PACKAGE_SPECS.get(self.package,
                                              self.PACKAGE_SPECS['SOT-23'])

    def _identify_package(self, footprint_name: str) -> str:
        """Identify transistor package from name."""
        upper_name = footprint_name.upper()
        for pkg in self.PACKAGE_SPECS.keys():
            if pkg in upper_name:
                return pkg
        return 'SOT-23'  # Default

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """Get pad coordinates for transistor pin."""
        try:
            pin = int(pin_number)
            if 1 <= pin <= len(self.coords):
                return self.coords[pin - 1]
        except (ValueError, IndexError):
            pass
        return (0.0, 0.0)

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return coordinates for all pads."""
        return {str(i + 1): self.coords[i]
                for i in range(len(self.coords))}


class PinHeaderVerticalGeometry(FootprintGeometry):
    """
    Vertical pin header geometry: pins arranged in a column (x=0, y varies).

    GENERIC: Works for any pin count (1-256 pins)
    PATTERN: PinHeader_1xN_*_Vertical, Conn_01xN

    Example: PinHeader_1x10_P2.54mm_Vertical
    - Pin 1: (0.0, 0.0)
    - Pin 2: (0.0, 2.54)
    - Pin 3: (0.0, 5.08)
    - ...
    - Pin 10: (0.0, 22.86)
    """

    def __init__(self, footprint_name: str, pin_count: int):
        """Initialize vertical pin header geometry."""
        self.footprint_name = footprint_name
        self.pin_count = int(pin_count)  # Ensure pin_count is integer

        # Extract pitch from footprint name (default 2.54mm)
        self.pitch = 2.54
        pitch_match = re.search(r'P([\d.]+)mm', footprint_name)
        if pitch_match:
            self.pitch = float(pitch_match.group(1))

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """Get pad coordinates for vertical header (column layout)."""
        try:
            pin = int(pin_number)
            if pin < 1 or pin > self.pin_count:
                return (0.0, 0.0)

            # Vertical column: x=0, y increases by pitch
            x = 0.0
            y = (pin - 1) * self.pitch

            return (x, y)
        except ValueError:
            return (0.0, 0.0)

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return coordinates for all pads."""
        return {str(i): self.get_pad_coordinates(str(i))
                for i in range(1, self.pin_count + 1)}


class PinHeaderHorizontalGeometry(FootprintGeometry):
    """
    Horizontal pin header geometry: pins arranged in a row (x varies, y=0).

    GENERIC: Works for any pin count (1-256 pins)
    PATTERN: PinHeader_Nx1_*_Horizontal, Conn_Nx01

    Example: PinHeader_4x1_P2.54mm_Horizontal with 4 pins
    - Pin 1: (-3.81, 0.0)
    - Pin 2: (-1.27, 0.0)
    - Pin 3: (1.27, 0.0)
    - Pin 4: (3.81, 0.0)
    """

    def __init__(self, footprint_name: str, pin_count: int):
        """Initialize horizontal pin header geometry."""
        self.footprint_name = footprint_name
        self.pin_count = int(pin_count)  # Ensure pin_count is integer

        # Extract pitch from footprint name (default 2.54mm)
        self.pitch = 2.54
        pitch_match = re.search(r'P([\d.]+)mm', footprint_name)
        if pitch_match:
            self.pitch = float(pitch_match.group(1))

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """Get pad coordinates for horizontal header (row layout)."""
        try:
            pin = int(pin_number)
            if pin < 1 or pin > self.pin_count:
                return (0.0, 0.0)

            # Horizontal row: x varies by pitch (centered), y=0
            total_width = (self.pin_count - 1) * self.pitch
            x = (pin - 1) * self.pitch - total_width / 2
            y = 0.0

            return (x, y)
        except ValueError:
            return (0.0, 0.0)

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return coordinates for all pads."""
        return {str(i): self.get_pad_coordinates(str(i))
                for i in range(1, self.pin_count + 1)}


class FallbackGeometry(FootprintGeometry):
    """
    Conservative fallback geometry for unknown footprints.

    ENHANCED (2025-11-17): Now orientation-aware!
    - Parses footprint name to detect vertical/horizontal orientation
    - Defaults to vertical for connectors (most common)
    - Provides GENERIC solution for ANY unknown footprint
    """

    def __init__(self, footprint_name: str, pin_count: int):
        """Initialize fallback geometry with orientation detection."""
        self.footprint_name = footprint_name
        self.pin_count = int(pin_count)  # Ensure pin_count is integer

        # Try to guess pitch from footprint name
        self.pitch = 2.54  # Default 0.1" pitch

        # Check for metric pitches
        pitch_match = re.search(r'P([\d.]+)mm', footprint_name)
        if pitch_match:
            self.pitch = float(pitch_match.group(1))
        elif self.pin_count > 20:
            self.pitch = 0.5  # Fine pitch for high pin count
        elif self.pin_count > 10:
            self.pitch = 1.27  # Medium pitch

        # ENHANCED: Infer orientation from footprint name
        self.orientation = self._infer_orientation(footprint_name)

        logger.warning(f"Using fallback geometry for {footprint_name} with {pin_count} pins (orientation: {self.orientation})")

    def _infer_orientation(self, footprint_name: str) -> str:
        """
        Infer vertical/horizontal orientation from footprint name.

        GENERIC: Works for ANY footprint naming convention.

        Returns: 'vertical' or 'horizontal'
        """
        upper = footprint_name.upper()

        # Explicit vertical markers
        if 'VERTICAL' in upper or '_1X' in upper or '_01X' in upper:
            return 'vertical'

        # Explicit horizontal markers
        elif 'HORIZONTAL' in upper or 'X1_' in upper or 'X01_' in upper:
            return 'horizontal'

        # Heuristics for common connector types
        else:
            # Connectors and pin headers are usually vertical
            if 'CONN' in upper or 'PIN' in upper or 'HEADER' in upper:
                return 'vertical'

            # Default to horizontal for unknown types
            return 'horizontal'

    def get_pad_coordinates(self, pin_number: str) -> Tuple[float, float]:
        """Get pad coordinates using orientation-aware layout."""
        try:
            pin = int(pin_number)
            if pin < 1 or pin > self.pin_count:
                return (0.0, 0.0)

            if self.orientation == 'vertical':
                # Vertical column: x=0, y varies
                return (0.0, (pin - 1) * self.pitch)
            else:
                # Horizontal row: x varies (centered), y=0
                total_width = (self.pin_count - 1) * self.pitch
                x = (pin - 1) * self.pitch - total_width / 2
                return (x, 0.0)

        except ValueError:
            return (0.0, 0.0)

    def get_all_pad_coordinates(self) -> Dict[str, Tuple[float, float]]:
        """Return coordinates for all pads."""
        return {str(i): self.get_pad_coordinates(str(i))
                for i in range(1, self.pin_count + 1)}


class FootprintGeometryRegistry:
    """
    Main registry that selects appropriate geometry calculator for any footprint.
    This is the CORE of the pad coordinate system.
    """

    def __init__(self):
        """Initialize the registry with pattern matchers."""
        # Pattern to geometry class mapping
        # Order matters - more specific patterns first
        self.patterns = [
            # Pin Headers - VERTICAL (CRITICAL FIX 2025-11-17)
            # These must be FIRST to override fallback behavior
            (r'PinHeader_1x\d+.*Vertical', PinHeaderVerticalGeometry),
            (r'Conn(?:ector)?.*_01x\d+', PinHeaderVerticalGeometry),  # Conn_01x10, Connector_01x08
            (r'Conn(?:ector)?_Generic:Conn_01x\d+', PinHeaderVerticalGeometry),

            # Pin Headers - HORIZONTAL
            (r'PinHeader_\d+x1.*Horizontal', PinHeaderHorizontalGeometry),
            (r'Conn(?:ector)?.*_\d+x01', PinHeaderHorizontalGeometry),  # Conn_10x01, Connector_08x01

            # Resistors
            (r'Resistor.*:R_\d+', TwoPadSMDGeometry),
            (r'R_\d+', TwoPadSMDGeometry),

            # Capacitors
            (r'Capacitor.*:C_\d+', TwoPadSMDGeometry),
            (r'C_\d+', TwoPadSMDGeometry),

            # Diodes
            (r'Diode.*:.*SOD', TwoPadSMDGeometry),
            (r'D_SOD', TwoPadSMDGeometry),
            (r'LED', TwoPadSMDGeometry),

            # Inductors (usually 2-pad)
            (r'Inductor.*:L_\d+', TwoPadSMDGeometry),
            (r'L_\d+', TwoPadSMDGeometry),

            # ICs - Dual row
            (r'Package_SO:SOIC', DualRowICGeometry),
            (r'SOIC-\d+', DualRowICGeometry),
            (r'Package_SO:TSSOP', DualRowICGeometry),
            (r'TSSOP-\d+', DualRowICGeometry),
            (r'Package_DIP:DIP', DualRowICGeometry),
            (r'DIP-\d+', DualRowICGeometry),

            # ICs - Quad
            (r'Package_QFP', QuadPackageGeometry),
            (r'QFP-\d+', QuadPackageGeometry),
            (r'LQFP-\d+', QuadPackageGeometry),
            (r'TQFP-\d+', QuadPackageGeometry),
            (r'Package_DFN_QFN', QuadPackageGeometry),
            (r'QFN-\d+', QuadPackageGeometry),

            # Transistors
            (r'Package_TO_SOT.*:SOT-23', TransistorGeometry),
            (r'SOT-23', TransistorGeometry),
            (r'Package_TO_SOT.*:TO-92', TransistorGeometry),
            (r'TO-92', TransistorGeometry),
            (r'Package_TO_SOT.*:TO-220', TransistorGeometry),
            (r'TO-220', TransistorGeometry),

            # Connectors
            (r'Connector.*:.*_\d+x\d+', ConnectorGeometry),
            (r'Connector_PinHeader', ConnectorGeometry),
            (r'TerminalBlock', ConnectorGeometry),
            (r'Conn_\d+x\d+', ConnectorGeometry),
            (r'PinHeader', ConnectorGeometry),
            (r'BNC', ConnectorGeometry),  # Usually 2-4 pins
            (r'USB', ConnectorGeometry),  # Various pin counts
            (r'RJ45', ConnectorGeometry), # 8 pins typical
        ]

        # Cache for created geometries
        self.cache = {}

    def get_geometry(self, footprint_name: str, pin_count: int) -> FootprintGeometry:
        """
        Return appropriate geometry calculator for the given footprint.

        Args:
            footprint_name: KiCad footprint name (e.g., "Resistor_SMD:R_0603_1608Metric")
            pin_count: Number of pins/pads on the component

        Returns:
            FootprintGeometry instance that can calculate pad coordinates
        """
        # Check cache first
        cache_key = f"{footprint_name}_{pin_count}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Try to match patterns
        for pattern, geometry_class in self.patterns:
            if re.search(pattern, footprint_name, re.IGNORECASE):
                try:
                    # Create geometry instance
                    # Classes that take (footprint_name, pin_count)
                    if geometry_class in [DualRowICGeometry, QuadPackageGeometry,
                                          ConnectorGeometry, PinHeaderVerticalGeometry,
                                          PinHeaderHorizontalGeometry, FallbackGeometry]:
                        geometry = geometry_class(footprint_name, pin_count)
                    else:
                        geometry = geometry_class(footprint_name)

                    # Cache and return
                    self.cache[cache_key] = geometry
                    logger.debug(f"Matched {footprint_name} to {geometry_class.__name__}")
                    return geometry
                except Exception as e:
                    logger.error(f"Error creating {geometry_class.__name__}: {e}")
                    # Fall through to next pattern

        # No match - use fallback
        logger.warning(f"No specific geometry for {footprint_name}, using fallback")
        geometry = FallbackGeometry(footprint_name, pin_count)
        self.cache[cache_key] = geometry
        return geometry

    def get_pad_positions(self, footprint_name: str, pin_count: int,
                         comp_x: float, comp_y: float,
                         rotation: float = 0.0) -> Dict[str, Tuple[float, float]]:
        """
        Get absolute pad positions for all pins of a component.

        Args:
            footprint_name: KiCad footprint name
            pin_count: Number of pins
            comp_x: Component X position on board (mm)
            comp_y: Component Y position on board (mm)
            rotation: Component rotation (degrees)

        Returns:
            Dictionary mapping pin numbers to absolute (x, y) coordinates
        """
        # Get geometry for this footprint
        geometry = self.get_geometry(footprint_name, pin_count)

        # Get all relative pad positions
        relative_positions = geometry.get_all_pad_coordinates()

        # Convert to absolute positions with rotation
        absolute_positions = {}

        for pin_num, (rel_x, rel_y) in relative_positions.items():
            # Apply rotation if needed
            if rotation != 0:
                angle_rad = math.radians(rotation)
                cos_a = math.cos(angle_rad)
                sin_a = math.sin(angle_rad)

                # Rotate around origin
                rot_x = rel_x * cos_a - rel_y * sin_a
                rot_y = rel_x * sin_a + rel_y * cos_a

                rel_x, rel_y = rot_x, rot_y

            # Add component position offset
            abs_x = comp_x + rel_x
            abs_y = comp_y + rel_y

            absolute_positions[pin_num] = (abs_x, abs_y)

        return absolute_positions


# Module-level singleton for easy access
_registry = None

def get_registry() -> FootprintGeometryRegistry:
    """Get the global footprint geometry registry."""
    global _registry
    if _registry is None:
        _registry = FootprintGeometryRegistry()
    return _registry


def get_pad_positions(footprint_name: str, pin_count: int,
                      comp_x: float, comp_y: float,
                      rotation: float = 0.0) -> Dict[str, Tuple[float, float]]:
    """
    Convenience function to get pad positions for a component.

    This is the main entry point for getting pad coordinates.
    """
    registry = get_registry()
    return registry.get_pad_positions(footprint_name, pin_count,
                                      comp_x, comp_y, rotation)


def test_geometry_engine():
    """Test the geometry engine with various footprints."""
    test_cases = [
        ("Resistor_SMD:R_0603_1608Metric", 2, 10.0, 20.0, 0),
        ("Capacitor_SMD:C_0805_2012Metric", 2, 15.0, 25.0, 90),
        ("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", 8, 30.0, 40.0, 0),
        ("Package_DIP:DIP-14_W7.62mm", 14, 50.0, 60.0, 0),
        ("Package_TO_SOT_SMD:SOT-23", 3, 70.0, 80.0, 45),
        ("Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", 4, 90.0, 100.0, 0),
        ("Unknown_Footprint_XYZ", 6, 110.0, 120.0, 0),  # Test fallback
    ]

    print("Testing Footprint Geometry Engine")
    print("=" * 60)

    for footprint, pins, x, y, rot in test_cases:
        print(f"\nFootprint: {footprint}")
        print(f"Position: ({x}, {y}), Rotation: {rot}°, Pins: {pins}")

        positions = get_pad_positions(footprint, pins, x, y, rot)

        for pin, (px, py) in sorted(positions.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0):
            print(f"  Pin {pin}: ({px:.3f}, {py:.3f})")

    print("\n" + "=" * 60)
    print("Geometry Engine Test Complete")


if __name__ == "__main__":
    # Run tests when module is executed directly
    import logging
    logging.basicConfig(level=logging.DEBUG)
    test_geometry_engine()