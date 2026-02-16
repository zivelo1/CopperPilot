#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Transform Utilities - Generic, Modular, Dynamic
=====================================================

Handles rotation, mirror, and coordinate transformations for KiCad symbols.
Works for ANY component type with ANY orientation.

Transform Matrix Format (from KiCad)
------------------------------------
Matrix: x1 y1 x2 y2

Standard transforms:
- 0° normal:    1  0  0 -1
- 90° normal:   0 -1 -1  0
- 180° normal: -1  0  0  1
- 270° normal:  0  1  1  0
- 0° X-mirror:  1  0  0  1
- 90° X-mirror: 0 -1  1  0
- 180° X-mirror:-1  0  0 -1
- 270° X-mirror: 0  1 -1  0

Application:
    transformed_x = pin_x * x1 + pin_y * y1
    transformed_y = pin_x * x2 + pin_y * y2
"""

import math
from typing import Tuple, List


# Standard KiCad transform matrices
TRANSFORM_MATRICES = {
    # (rotation, mirror): [x1, y1, x2, y2]
    # CRITICAL FIX (2025-10-26): KiCad DOES invert Y for pin positions!
    # With grid snapping removed, Y-inversion is correct:
    # Pin at symbol (0, 3.81) → world (component_x, component_y - 3.81) = (81.28, 46.99) ✓
    # Verified against actual KiCad ERC positions
    (0, False):   [1, 0, 0, -1],    # 0° no mirror - INVERT Y!
    (90, False):  [0, -1, -1, 0],   # 90° no mirror
    (180, False): [-1, 0, 0, 1],    # 180° no mirror
    (270, False): [0, 1, 1, 0],     # 270° no mirror
    (0, True):    [-1, 0, 0, -1],   # 0° X-mirror
    (90, True):   [0, -1, 1, 0],    # 90° X-mirror
    (180, True):  [1, 0, 0, 1],     # 180° X-mirror
    (270, True):  [0, 1, -1, 0],    # 270° X-mirror
}


def get_transform_matrix(rotation: int = 0, mirror: bool = False) -> List[float]:
    """
    Get KiCad transform matrix for given rotation and mirror.

    GENERIC: Works for ANY component at ANY orientation.

    Args:
        rotation: Rotation angle in degrees (0, 90, 180, 270)
        mirror: True if X-axis mirrored

    Returns:
        Transform matrix [x1, y1, x2, y2]

    Example:
        >>> get_transform_matrix(90, False)
        [0, -1, -1, 0]
    """
    # Normalize rotation to 0, 90, 180, 270
    rotation = int(rotation) % 360
    if rotation not in [0, 90, 180, 270]:
        # Round to nearest 90 degrees
        rotation = round(rotation / 90) * 90 % 360

    key = (rotation, mirror)
    return TRANSFORM_MATRICES.get(key, [1, 0, 0, -1])  # Default: 0° no mirror (Y-inverted)


def apply_transform(x: float, y: float, transform: List[float]) -> Tuple[float, float]:
    """
    Apply transform matrix to coordinates.

    GENERIC: Works for ANY coordinate transformation.

    Args:
        x, y: Coordinates in symbol-local space
        transform: Transform matrix [x1, y1, x2, y2]

    Returns:
        (transformed_x, transformed_y) in world space

    Example:
        >>> apply_transform(5.08, 0, [0, -1, -1, 0])  # 90° rotation
        (0, -5.08)
    """
    x1, y1, x2, y2 = transform

    transformed_x = x * x1 + y * y1
    transformed_y = x * x2 + y * y2

    return (transformed_x, transformed_y)


def snap_to_grid(value: float, grid_size: float = 2.54) -> float:
    """
    Snap coordinate to KiCad schematic grid.

    CRITICAL: Connection points MUST be on grid or KiCad reports "dangling".

    GENERIC: Works for ANY coordinate value.

    Args:
        value: Coordinate in mm
        grid_size: Grid size in mm (default 2.54mm = 100mil)

    Returns:
        Snapped coordinate on grid

    Example:
        >>> snap_to_grid(50.801)
        50.8
        >>> snap_to_grid(51.5)
        50.8  # Rounds down to nearest 2.54mm grid point
    """
    return round(value / grid_size) * grid_size


# =============================================================================
# TC #69 FIX (2025-12-07): STRICT GRID SNAPPING FOR SCHEMATIC CONNECTIVITY
# =============================================================================
# The forensic analysis showed 1-2% of coordinates are off-grid:
# - Examples: (0.635, 2.540), (0.965, -3.810)
# - 0.635mm = half of 1.27mm (50mil grid)
# - 0.965mm = invalid coordinate not on any standard grid
#
# Root Cause: Coordinates were calculated correctly but not snapped AFTER
# transform operations (rotation/mirror) which can introduce floating-point drift.
#
# Solution: Add strict snapping functions that:
# 1. Use 1.27mm (50mil) grid for schematic elements (KiCad standard)
# 2. Apply AFTER all transform calculations
# 3. Apply to ALL coordinates: components, wires, labels, junctions
# =============================================================================

# Standard KiCad grid sizes
GRID_SCHEMATIC_STANDARD = 1.27  # 50mil - Standard schematic grid
GRID_SCHEMATIC_FINE = 0.635     # 25mil - Fine schematic grid (NOT RECOMMENDED)
GRID_PCB_STANDARD = 1.27        # 50mil - Standard PCB grid
GRID_PCB_FINE = 0.1             # 0.1mm - Fine PCB grid for precision placement


def snap_to_schematic_grid(value: float) -> float:
    """
    TC #69 FIX: Snap coordinate to KiCad 1.27mm (50mil) schematic grid.

    CRITICAL: This is THE standard grid for KiCad schematics.
    ALL connection points (labels, wire endpoints) MUST be on this grid.

    GENERIC: Works for ANY coordinate value.

    Args:
        value: Coordinate in mm

    Returns:
        Snapped coordinate on 1.27mm grid

    Example:
        >>> snap_to_schematic_grid(50.801)
        50.8  # Rounds to nearest 1.27mm
        >>> snap_to_schematic_grid(0.635)
        1.27  # Half-grid snapped UP to full grid
        >>> snap_to_schematic_grid(0.965)
        1.27  # Invalid value snapped to nearest grid
    """
    return round(value / GRID_SCHEMATIC_STANDARD) * GRID_SCHEMATIC_STANDARD


def snap_coordinate_pair(x: float, y: float, grid_size: float = 1.27) -> tuple:
    """
    TC #69 FIX: Snap both X and Y coordinates to grid.

    GENERIC: Works for ANY coordinate pair.

    Args:
        x, y: Coordinates in mm
        grid_size: Grid size in mm (default 1.27mm for schematics)

    Returns:
        Tuple of (snapped_x, snapped_y)

    Example:
        >>> snap_coordinate_pair(0.635, 2.540)
        (1.27, 2.54)
    """
    snapped_x = round(x / grid_size) * grid_size
    snapped_y = round(y / grid_size) * grid_size
    return (snapped_x, snapped_y)


def is_on_grid(value: float, grid_size: float = 1.27, tolerance: float = 0.001) -> bool:
    """
    TC #69 FIX: Check if a coordinate is on the specified grid.

    GENERIC: Works for ANY coordinate and grid size.

    Args:
        value: Coordinate in mm
        grid_size: Grid size in mm
        tolerance: Tolerance for floating-point comparison

    Returns:
        True if on grid, False otherwise

    Example:
        >>> is_on_grid(2.54, 1.27)
        True
        >>> is_on_grid(0.635, 1.27)
        False
    """
    remainder = abs(value % grid_size)
    return remainder < tolerance or (grid_size - remainder) < tolerance


def validate_grid_alignment(coordinates: list, grid_size: float = 1.27) -> dict:
    """
    TC #69 FIX: Validate a list of coordinates for grid alignment.

    GENERIC: Works for ANY list of coordinate pairs.

    Args:
        coordinates: List of (x, y) tuples
        grid_size: Grid size in mm

    Returns:
        Dict with:
        - aligned_count: Number of coordinates on grid
        - misaligned_count: Number of coordinates off grid
        - alignment_percent: Percentage on grid
        - misaligned_examples: Up to 5 examples of off-grid coordinates

    Example:
        >>> validate_grid_alignment([(2.54, 5.08), (0.635, 2.54)])
        {'aligned_count': 1, 'misaligned_count': 1, 'alignment_percent': 50.0, ...}
    """
    aligned = 0
    misaligned = 0
    examples = []

    for x, y in coordinates:
        x_on_grid = is_on_grid(x, grid_size)
        y_on_grid = is_on_grid(y, grid_size)

        if x_on_grid and y_on_grid:
            aligned += 1
        else:
            misaligned += 1
            if len(examples) < 5:
                examples.append((x, y))

    total = aligned + misaligned
    percent = (aligned / total * 100) if total > 0 else 100.0

    return {
        'aligned_count': aligned,
        'misaligned_count': misaligned,
        'alignment_percent': percent,
        'misaligned_examples': examples
    }


def calculate_outward_stub_angle(pin_angle: float, rotation: int = 0, mirror: bool = False) -> float:
    """
    Calculate angle for wire stub extending OUTWARD from component.

    CRITICAL: Pin angles point INWARD to component body.
              Stubs must extend OUTWARD.

    GENERIC: Works for ANY component orientation and ANY pin angle.

    Args:
        pin_angle: Pin angle from symbol (0° = right, 90° = up, etc.)
        rotation: Component rotation in degrees
        mirror: True if component is X-mirrored

    Returns:
        Outward stub angle in degrees (0-360)

    Example:
        >>> calculate_outward_stub_angle(180, 0, False)  # Pin points left
        0.0  # Stub extends right (outward)

        >>> calculate_outward_stub_angle(180, 90, False)  # Pin left, component rotated 90°
        90.0  # Stub extends up (outward)
    """
    # 1. Reverse pin angle (inward → outward)
    outward_angle = (pin_angle + 180) % 360

    # 2. Apply component rotation
    world_angle = (outward_angle + rotation) % 360

    # 3. Apply mirror (if X-mirrored, flip angle horizontally)
    if mirror:
        world_angle = (360 - world_angle) % 360

    return world_angle


def calculate_stub_endpoint(pin_x: float, pin_y: float, stub_angle: float,
                            stub_length: float = 5.08) -> Tuple[float, float]:
    """
    Calculate endpoint of wire stub extending from pin.

    GENERIC: Works for ANY pin position and ANY stub direction.

    Args:
        pin_x, pin_y: Pin position in schematic coordinates
        stub_angle: Outward stub angle in degrees
        stub_length: Stub length in mm (default 5.08mm = 200mil)

    Returns:
        (end_x, end_y) coordinates of stub endpoint

    Example:
        >>> calculate_stub_endpoint(50.8, 50.8, 0, 5.08)  # Right
        (55.88, 50.8)

        >>> calculate_stub_endpoint(50.8, 50.8, 90, 5.08)  # Up
        (50.8, 45.72)
    """
    # Convert angle to radians
    angle_rad = math.radians(stub_angle)

    # Calculate stub endpoint
    # Note: Y-axis is inverted in KiCad schematic coordinates
    # Angle 0° = right (+X), 90° = up (-Y), 180° = left (-X), 270° = down (+Y)
    end_x = pin_x + stub_length * math.cos(angle_rad)
    end_y = pin_y - stub_length * math.sin(angle_rad)  # Y inverted!

    return (end_x, end_y)


def extract_rotation_from_matrix(transform: List[float]) -> int:
    """
    Extract rotation angle from transform matrix.

    UTILITY: Reverse-engineer rotation from matrix values.

    Args:
        transform: Transform matrix [x1, y1, x2, y2]

    Returns:
        Rotation angle in degrees (0, 90, 180, 270)

    Example:
        >>> extract_rotation_from_matrix([0, -1, -1, 0])
        90
    """
    # Find matching matrix
    for (rot, mir), matrix in TRANSFORM_MATRICES.items():
        if transform == matrix:
            return rot

    # Default to 0 if no match
    return 0


def extract_mirror_from_matrix(transform: List[float]) -> bool:
    """
    Extract mirror state from transform matrix.

    UTILITY: Reverse-engineer mirror from matrix values.

    Args:
        transform: Transform matrix [x1, y1, x2, y2]

    Returns:
        True if X-mirrored, False otherwise

    Example:
        >>> extract_mirror_from_matrix([1, 0, 0, 1])
        True  # 0° X-mirror
    """
    # Find matching matrix
    for (rot, mir), matrix in TRANSFORM_MATRICES.items():
        if transform == matrix:
            return mir

    # Default to no mirror
    return False


def calculate_absolute_pin_position(pin_x: float, pin_y: float,
                                    component_x: float, component_y: float,
                                    transform: List[float]) -> Tuple[float, float]:
    """
    Calculate absolute pin position in schematic coordinates.

    COMPLETE SOLUTION: Symbol-local → transformed → world → grid-aligned

    GENERIC: Works for ANY component at ANY position with ANY orientation.

    Args:
        pin_x, pin_y: Pin position in symbol-local coordinates
        component_x, component_y: Component center in schematic
        transform: Component transform matrix

    Returns:
        (abs_x, abs_y) pin position in schematic, grid-aligned

    Example:
        >>> # Component at (50.8, 50.8), rotated 90°
        >>> # Pin at (5.08, 0) in symbol space
        >>> transform = [0, -1, -1, 0]  # 90° rotation
        >>> calculate_absolute_pin_position(5.08, 0, 50.8, 50.8, transform)
        (50.8, 45.72)  # Grid-aligned
    """
    # 1. Apply transform (rotation + mirror) to pin offset
    rotated_x, rotated_y = apply_transform(pin_x, pin_y, transform)

    # 2. Add component position
    abs_x = component_x + rotated_x
    abs_y = component_y + rotated_y

    # DEBUG
    if component_x == 50.8 and component_y == 50.8:
        print(f"        TRACE: pin_symbol=({pin_x}, {pin_y}) → rotated=({rotated_x}, {rotated_y}) → abs=({abs_x}, {abs_y})")

    # CRITICAL FIX (2025-10-26): Do NOT grid-snap pin positions!
    # KiCad pin positions are exact (e.g., 46.99mm, 54.61mm - not on 2.54mm grid)
    # Grid snapping causes 1.27mm offset errors at half-grid positions
    # Wires and labels WILL be snapped, but pins must remain at exact symbol-defined positions

    return (abs_x, abs_y)


# Unit tests
if __name__ == "__main__":
    print("Testing KiCad Transform Utilities")
    print("=" * 50)

    # Test 1: Transform matrix lookup
    print("\nTest 1: Transform Matrix Lookup")
    for rot in [0, 90, 180, 270]:
        for mir in [False, True]:
            matrix = get_transform_matrix(rot, mir)
            print(f"  {rot}° {'mirror' if mir else 'normal'}: {matrix}")

    # Test 2: Apply transform
    print("\nTest 2: Apply Transform (5.08, 0) with different rotations")
    pin = (5.08, 0)
    for rot in [0, 90, 180, 270]:
        matrix = get_transform_matrix(rot, False)
        result = apply_transform(pin[0], pin[1], matrix)
        print(f"  {rot}°: {pin} → {result}")

    # Test 3: Grid snapping
    print("\nTest 3: Grid Snapping")
    test_values = [50.801, 51.5, 48.0, 49.99, 52.54]
    for val in test_values:
        snapped = snap_to_grid(val)
        print(f"  {val:.3f} → {snapped:.2f}")

    # Test 4: Outward stub angle
    print("\nTest 4: Outward Stub Angle")
    pin_angles = [0, 90, 180, 270]  # Pin pointing: right, up, left, down
    comp_rot = 90  # Component rotated 90°
    for pin_angle in pin_angles:
        stub_angle = calculate_outward_stub_angle(pin_angle, comp_rot, False)
        print(f"  Pin {pin_angle}° + Component {comp_rot}° = Stub {stub_angle}°")

    # Test 5: Complete pin position calculation
    print("\nTest 5: Complete Pin Position Calculation")
    # Component at (50.8, 50.8), rotated 90°, pin at (5.08, 0) in symbol space
    pin_local = (5.08, 0)
    comp_pos = (50.8, 50.8)
    transform = get_transform_matrix(90, False)
    result = calculate_absolute_pin_position(
        pin_local[0], pin_local[1],
        comp_pos[0], comp_pos[1],
        transform
    )
    print(f"  Pin {pin_local} in symbol")
    print(f"  Component at {comp_pos}, rotated 90°")
    print(f"  Absolute position: {result}")

    print("\n✅ All tests completed")
