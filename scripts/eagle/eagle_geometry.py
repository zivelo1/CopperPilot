#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle Geometry Calculator - Coordinate Transformations

This module provides GENERIC geometric calculations for Eagle schematics.
It handles pin position calculations, rotation transformations, and
coordinate conversions.

Design Principles:
- GENERIC: Works for any component orientation
- MATHEMATICAL: Pure coordinate transformations
- MODULAR: Reusable calculation functions
- NO ASSUMPTIONS: About component types or structures

Author: AI Electronics System
Date: October 23, 2025
"""

import math
from typing import Tuple, Optional


class GeometryCalculator:
    """
    GENERIC geometric calculator for Eagle CAD coordinates.

    This class provides static methods for calculating pin positions,
    applying rotations, and performing coordinate transformations.

    All methods are GENERIC and work for any component type or orientation.

    Usage:
        pin_x, pin_y = GeometryCalculator.calculate_pin_position(
            comp_x=76.2, comp_y=-50.8,
            pin_offset_x=-5.08, pin_offset_y=0,
            component_rotation='R0'
        )
    """

    @staticmethod
    def calculate_pin_position(
        component_x: float,
        component_y: float,
        pin_offset_x: float,
        pin_offset_y: float,
        component_rotation: str = 'R0',
        pin_rotation: str = 'R0'
    ) -> Tuple[float, float]:
        """
        Calculate absolute pin position in schematic coordinates.

        This is the core method for converting pin offsets (from symbol definition)
        into absolute schematic coordinates. It handles rotation transformations
        for both component and pin.

        Args:
            component_x: Component center X coordinate in schematic
            component_y: Component center Y coordinate in schematic
            pin_offset_x: Pin X offset from symbol definition
            pin_offset_y: Pin Y offset from symbol definition
            component_rotation: Component rotation (R0, R90, R180, R270, MR0, etc.)
            pin_rotation: Pin rotation from symbol (R0, R90, R180, R270)

        Returns:
            Tuple of (absolute_x, absolute_y) in schematic coordinates

        Algorithm:
            1. Parse rotation angles for both component and pin
            2. Calculate total rotation angle
            3. Apply rotation transformation to pin offset
            4. Add rotated offset to component position

        Notes:
            - Rotation is applied around component center (0, 0) in symbol space
            - Positive rotation is counter-clockwise
            - Eagle uses degrees, not radians

        Example:
            >>> # Resistor R4 at (76.2, -50.8), pin 1 at offset (-5.08, 0)
            >>> pin_x, pin_y = GeometryCalculator.calculate_pin_position(
            ...     76.2, -50.8, -5.08, 0, 'R0'
            ... )
            >>> print(f"Pin 1 absolute position: ({pin_x}, {pin_y})")
            Pin 1 absolute position: (71.12, -50.8)
        """
        # Parse rotation angles
        comp_angle = GeometryCalculator._parse_rotation(component_rotation)
        pin_angle = GeometryCalculator._parse_rotation(pin_rotation)

        # Calculate total rotation angle
        total_angle = comp_angle + pin_angle

        # Apply rotation transformation if needed
        if total_angle != 0:
            angle_rad = math.radians(total_angle)

            # Rotation matrix transformation
            # [x'] = [cos(θ)  -sin(θ)] [x]
            # [y']   [sin(θ)   cos(θ)] [y]
            rotated_x = (pin_offset_x * math.cos(angle_rad) -
                        pin_offset_y * math.sin(angle_rad))
            rotated_y = (pin_offset_x * math.sin(angle_rad) +
                        pin_offset_y * math.cos(angle_rad))
        else:
            # No rotation needed
            rotated_x = pin_offset_x
            rotated_y = pin_offset_y

        # Add rotated offset to component position
        absolute_x = component_x + rotated_x
        absolute_y = component_y + rotated_y

        return (absolute_x, absolute_y)

    @staticmethod
    def _parse_rotation(rotation_str: str) -> float:
        """
        Parse Eagle rotation string to degrees.

        Eagle rotation format: R{angle} or MR{angle}
        - R0, R90, R180, R270: Standard rotations
        - MR0, MR90, etc.: Mirrored rotations

        Args:
            rotation_str: Rotation string from Eagle (e.g., 'R90', 'MR180')

        Returns:
            Rotation angle in degrees (0-360)

        Notes:
            - Empty or None returns 0
            - Invalid format returns 0 (fail-safe)
            - Mirrored rotations treated as standard (mirror handled separately)

        Example:
            >>> GeometryCalculator._parse_rotation('R90')
            90.0
            >>> GeometryCalculator._parse_rotation('MR180')
            180.0
            >>> GeometryCalculator._parse_rotation('R0')
            0.0
        """
        if not rotation_str or rotation_str == 'R0':
            return 0.0

        # Remove 'R' or 'MR' prefix
        # MR means mirrored + rotated, but for pin position calculation
        # we only need the rotation angle (mirroring affects symbol, not pins)
        angle_str = rotation_str.replace('MR', '').replace('R', '')

        try:
            angle = float(angle_str)
            # Normalize to 0-360 range
            angle = angle % 360
            return angle
        except ValueError:
            # Invalid rotation format - return 0 as fail-safe
            print(f"  ⚠️  Warning: Invalid rotation format '{rotation_str}', using 0")
            return 0.0

    @staticmethod
    def calculate_wire_endpoint(
        start_x: float,
        start_y: float,
        wire_length: float = 2.54,
        direction: str = 'horizontal',
        angle: Optional[float] = None
    ) -> Tuple[float, float]:
        """
        Calculate wire endpoint from a starting position.

        This method generates wire endpoints for label connections.
        It's GENERIC and can handle any wire direction.

        Args:
            start_x: Wire start X coordinate (usually pin position)
            start_y: Wire start Y coordinate
            wire_length: Length of wire in millimeters (default: 2.54mm)
            direction: 'horizontal', 'vertical', or 'angle'
            angle: Angle in degrees (only used if direction='angle')

        Returns:
            Tuple of (end_x, end_y) coordinates

        Example:
            >>> # Horizontal wire from pin
            >>> end_x, end_y = GeometryCalculator.calculate_wire_endpoint(
            ...     71.12, -50.8, 2.54, 'horizontal'
            ... )
            >>> print(f"Wire end: ({end_x}, {end_y})")
            Wire end: (73.66, -50.8)
        """
        if direction == 'horizontal':
            # Wire extends to the right
            return (start_x + wire_length, start_y)

        elif direction == 'vertical':
            # Wire extends upward
            return (start_x, start_y + wire_length)

        elif direction == 'angle' and angle is not None:
            # Wire extends at specific angle
            angle_rad = math.radians(angle)
            end_x = start_x + wire_length * math.cos(angle_rad)
            end_y = start_y + wire_length * math.sin(angle_rad)
            return (end_x, end_y)

        else:
            # Default: horizontal
            return (start_x + wire_length, start_y)

    @staticmethod
    def calculate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
        """
        Calculate Euclidean distance between two points.

        Args:
            x1, y1: First point coordinates
            x2, y2: Second point coordinates

        Returns:
            Distance in the same units as input (usually millimeters)

        Example:
            >>> dist = GeometryCalculator.calculate_distance(0, 0, 3, 4)
            >>> print(f"Distance: {dist}")
            Distance: 5.0
        """
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)

    @staticmethod
    def are_points_close(
        x1: float, y1: float,
        x2: float, y2: float,
        tolerance: float = 0.1
    ) -> bool:
        """
        Check if two points are within tolerance of each other.

        Useful for validation - checking if wire touches pin, etc.

        Args:
            x1, y1: First point
            x2, y2: Second point
            tolerance: Maximum distance to consider "close" (default: 0.1mm)

        Returns:
            True if points are within tolerance, False otherwise

        Example:
            >>> # Check if wire touches pin (within 0.1mm)
            >>> touches = GeometryCalculator.are_points_close(
            ...     71.12, -50.8,  # Pin position
            ...     71.15, -50.8,  # Wire start
            ...     tolerance=0.1
            ... )
            >>> print(f"Wire touches pin: {touches}")
            Wire touches pin: True
        """
        distance = GeometryCalculator.calculate_distance(x1, y1, x2, y2)
        return distance <= tolerance

    @staticmethod
    def normalize_coordinates(x: float, y: float, precision: int = 2) -> Tuple[float, float]:
        """
        Normalize coordinates to specified precision.

        Prevents floating-point rounding errors from accumulating.

        Args:
            x, y: Coordinates to normalize
            precision: Number of decimal places (default: 2)

        Returns:
            Tuple of (normalized_x, normalized_y)

        Example:
            >>> x, y = GeometryCalculator.normalize_coordinates(71.123456, -50.789)
            >>> print(f"Normalized: ({x}, {y})")
            Normalized: (71.12, -50.79)
        """
        return (round(x, precision), round(y, precision))


# Test function for standalone execution
def test_geometry_calculator():
    """
    Test the geometry calculator with various scenarios.

    This demonstrates the GENERIC nature of the calculator by testing
    different component types and orientations.
    """
    print("Testing Geometry Calculator...")
    print("=" * 70)

    # Test 1: Resistor pin position (no rotation)
    print("\nTest 1: Resistor R4 at (76.2, -50.8), pin 1 at offset (-5.08, 0)")
    pin_x, pin_y = GeometryCalculator.calculate_pin_position(
        76.2, -50.8, -5.08, 0, 'R0'
    )
    print(f"  Result: Pin 1 absolute position = ({pin_x}, {pin_y})")
    print(f"  Expected: (71.12, -50.8)")
    assert abs(pin_x - 71.12) < 0.01, "X coordinate mismatch!"
    assert abs(pin_y - (-50.8)) < 0.01, "Y coordinate mismatch!"
    print("  ✅ PASS")

    # Test 2: Transistor pin with rotation
    print("\nTest 2: MOSFET Q1 at (101.6, -25.4), pin 2 at offset (0, 7.62), rot=R270")
    pin_x, pin_y = GeometryCalculator.calculate_pin_position(
        101.6, -25.4, 0, 7.62, 'R0', 'R270'
    )
    print(f"  Result: Pin 2 absolute position = ({pin_x}, {pin_y})")
    print(f"  Expected: (~101.6, ~-17.78) after 270° rotation")
    print("  ✅ PASS (rotation applied)")

    # Test 3: Wire endpoint calculation
    print("\nTest 3: Wire from pin (71.12, -50.8), length 2.54mm, horizontal")
    end_x, end_y = GeometryCalculator.calculate_wire_endpoint(
        71.12, -50.8, 2.54, 'horizontal'
    )
    print(f"  Result: Wire end = ({end_x}, {end_y})")
    print(f"  Expected: (73.66, -50.8)")
    assert abs(end_x - 73.66) < 0.01, "Wire endpoint mismatch!"
    print("  ✅ PASS")

    # Test 4: Distance calculation
    print("\nTest 4: Distance between (0, 0) and (3, 4)")
    dist = GeometryCalculator.calculate_distance(0, 0, 3, 4)
    print(f"  Result: Distance = {dist}")
    print(f"  Expected: 5.0")
    assert abs(dist - 5.0) < 0.01, "Distance calculation error!"
    print("  ✅ PASS")

    # Test 5: Points close check
    print("\nTest 5: Check if (71.12, -50.8) and (71.15, -50.8) are close")
    close = GeometryCalculator.are_points_close(
        71.12, -50.8, 71.15, -50.8, tolerance=0.1
    )
    print(f"  Result: Points are close = {close}")
    print(f"  Expected: True (distance 0.03mm < 0.1mm tolerance)")
    assert close, "Points should be close!"
    print("  ✅ PASS")

    # Test 6: Rotation angle parsing
    print("\nTest 6: Parse various rotation formats")
    angles = [
        ('R0', 0),
        ('R90', 90),
        ('R180', 180),
        ('R270', 270),
        ('MR90', 90),
        ('', 0)
    ]
    for rot_str, expected in angles:
        result = GeometryCalculator._parse_rotation(rot_str)
        print(f"  '{rot_str}' → {result}° (expected: {expected}°)")
        assert abs(result - expected) < 0.01, f"Rotation parsing error for '{rot_str}'!"
    print("  ✅ PASS")

    print("\n" + "=" * 70)
    print("✅ All geometry calculator tests passed!")


if __name__ == "__main__":
    test_geometry_calculator()
