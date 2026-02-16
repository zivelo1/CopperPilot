# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Schematic Validator Module

PHASE 0.3 (2025-11-23): Validate KiCad schematics for common connectivity issues.
Ensures schematics have proper junctions, global labels, and connections
BEFORE PCB generation begins.

GENERIC: Works for ANY circuit type and complexity.
"""

from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass
import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """
    Results from schematic validation.

    Attributes:
        errors: List of critical errors that must be fixed
        warnings: List of warnings that should be addressed
        info: List of informational messages
        passed: Boolean indicating if validation passed (no errors)
    """
    errors: List[str]
    warnings: List[str]
    info: List[str]

    @property
    def passed(self) -> bool:
        """Validation passes if there are no critical errors."""
        return len(self.errors) == 0


class SchematicValidator:
    """
    GENERIC schematic validator for ANY circuit type.

    Validates:
    1. Junction presence and reasonable count
    2. Label types (prefer global labels)
    3. Component connectivity (no floating components)
    4. Wire-to-junction ratio
    5. Net connectivity completeness

    PHASE 0.3 (2025-11-23): Comprehensive schematic validation.
    """

    def __init__(self):
        """Initialize schematic validator with standard thresholds."""
        # Expected wire-to-junction ratio for healthy circuits
        self.min_wire_junction_ratio = 2.0
        self.max_wire_junction_ratio = 10.0

        # Minimum junctions expected for circuits with wires
        self.min_junctions_threshold = 10  # If 10+ wires, expect some junctions

    def validate_schematic_file(self, sch_file: Path) -> ValidationResult:
        """
        Validate a KiCad schematic file (.kicad_sch).

        PHASE 0.3 (2025-11-23): File-based validation.

        Args:
            sch_file: Path to .kicad_sch file

        Returns:
            ValidationResult with errors, warnings, and info
        """
        errors = []
        warnings = []
        info = []

        # Read schematic file
        try:
            with open(sch_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            errors.append(f"Schematic file not found: {sch_file}")
            return ValidationResult(errors=errors, warnings=warnings, info=info)
        except Exception as e:
            errors.append(f"Failed to read schematic: {str(e)}")
            return ValidationResult(errors=errors, warnings=warnings, info=info)

        # Count schematic elements using regex
        counts = self._count_schematic_elements(content)

        info.append(f"Schematic: {sch_file.name}")
        info.append(f"  Components: {counts['symbols']}")
        info.append(f"  Wires: {counts['wires']}")
        info.append(f"  Junctions: {counts['junctions']}")
        info.append(f"  Global labels: {counts['global_labels']}")
        info.append(f"  Regular labels: {counts['labels']}")

        # VALIDATION CHECK 1: Junction presence
        if counts['wires'] > self.min_junctions_threshold and counts['junctions'] == 0:
            errors.append(
                f"CRITICAL: {counts['wires']} wires but 0 junctions - "
                f"connections will fail in KiCad"
            )
        elif counts['wires'] > 0 and counts['junctions'] == 0:
            warnings.append(
                f"No junctions found despite {counts['wires']} wires - "
                f"may indicate connectivity issues"
            )

        # VALIDATION CHECK 2: Wire-to-junction ratio
        if counts['junctions'] > 0:
            ratio = counts['wires'] / counts['junctions']
            if ratio < self.min_wire_junction_ratio:
                warnings.append(
                    f"Unusually low wire-to-junction ratio: {ratio:.2f} "
                    f"(expected: {self.min_wire_junction_ratio}-{self.max_wire_junction_ratio}) - "
                    f"may have too many junctions"
                )
            elif ratio > self.max_wire_junction_ratio:
                warnings.append(
                    f"Unusually high wire-to-junction ratio: {ratio:.2f} "
                    f"(expected: {self.min_wire_junction_ratio}-{self.max_wire_junction_ratio}) - "
                    f"may be missing junctions"
                )
            else:
                info.append(f"  Wire-to-junction ratio: {ratio:.2f} ✓ (healthy)")

        # VALIDATION CHECK 3: Label types
        if counts['labels'] > 0 and counts['global_labels'] == 0:
            warnings.append(
                f"Using {counts['labels']} regular labels with no global labels - "
                f"consider global labels for better net connectivity"
            )
        elif counts['labels'] > counts['global_labels']:
            warnings.append(
                f"More regular labels ({counts['labels']}) than global labels ({counts['global_labels']}) - "
                f"global labels provide better connectivity"
            )

        # VALIDATION CHECK 4: Floating components
        if counts['symbols'] > 0 and counts['wires'] == 0 and counts['global_labels'] == 0:
            errors.append(
                f"CRITICAL: {counts['symbols']} components but no connections "
                f"(no wires and no global labels) - circuit not connected"
            )

        # VALIDATION CHECK 5: Net connectivity (approximate)
        if counts['symbols'] > 0:
            expected_min_labels = max(counts['symbols'] // 2, 5)  # Heuristic
            if counts['global_labels'] < expected_min_labels:
                warnings.append(
                    f"Only {counts['global_labels']} global labels for {counts['symbols']} components - "
                    f"expected at least {expected_min_labels} for proper connectivity"
                )

        # VALIDATION CHECK 6: No-connect markers (informational)
        if counts['no_connects'] > 0:
            info.append(f"  No-connect markers: {counts['no_connects']} (intentionally unconnected pins)")

        return ValidationResult(errors=errors, warnings=warnings, info=info)

    def _count_schematic_elements(self, content: str) -> Dict[str, int]:
        """
        Count schematic elements using regex patterns.

        Args:
            content: Schematic file content as string

        Returns:
            Dictionary with counts of various elements
        """
        counts = {
            'symbols': len(re.findall(r'\(symbol\s+\(lib_id', content)),
            'wires': len(re.findall(r'\(wire\s+\(pts', content)),
            'junctions': len(re.findall(r'\(junction', content)),
            'labels': len(re.findall(r'\(label\s+"', content)),
            'global_labels': len(re.findall(r'\(global_label\s+"', content)),
            'hierarchical_labels': len(re.findall(r'\(hierarchical_label', content)),
            'no_connects': len(re.findall(r'\(no_connect', content)),
        }

        return counts

    def validate_schematic_context(self, context) -> ValidationResult:
        """
        Validate schematic from ConversionContext before file generation.

        PHASE 0.3 (2025-11-23): Context-based validation.
        Validates schematic data structures before they're written to file.

        Args:
            context: ConversionContext with circuit data

        Returns:
            ValidationResult with errors, warnings, and info
        """
        errors = []
        warnings = []
        info = []

        # Get component count
        component_count = len(context.components)
        info.append(f"Components in context: {component_count}")

        # Get net count
        nets = context.netlist.get('nets', {})
        net_count = len(nets)
        info.append(f"Nets in context: {net_count}")

        # Get wire count from routes
        routes = context.routes.get('schematic', {})
        wire_count = 0
        for net_name, segments in routes.items():
            for segment in segments:
                if segment.get('type') == 'wire':
                    wire_count += 1
        info.append(f"Wires in routes: {wire_count}")

        # VALIDATION: Reasonable net-to-component ratio
        if component_count > 0:
            expected_min_nets = max(component_count // 3, 2)  # Heuristic
            if net_count < expected_min_nets:
                warnings.append(
                    f"Only {net_count} nets for {component_count} components - "
                    f"expected at least {expected_min_nets}"
                )

        # VALIDATION: Components have nets
        components_without_nets = 0
        for ref_des, comp in context.components.items():
            pin_net_mapping = comp.get('pinNetMapping', {})
            if not pin_net_mapping:
                components_without_nets += 1

        if components_without_nets > 0:
            warnings.append(
                f"{components_without_nets} components have no net assignments - "
                f"will be floating in schematic"
            )

        return ValidationResult(errors=errors, warnings=warnings, info=info)


def validate_schematic_directory(directory: Path) -> Dict[str, ValidationResult]:
    """
    Validate all schematic files in a directory.

    PHASE 0.3 (2025-11-23): Batch validation for testing.

    Args:
        directory: Path to directory containing .kicad_sch files

    Returns:
        Dictionary mapping filename to ValidationResult
    """
    validator = SchematicValidator()
    results = {}

    # Find all .kicad_sch files
    sch_files = list(directory.glob('*.kicad_sch'))

    if not sch_files:
        logger.warning(f"No .kicad_sch files found in {directory}")
        return results

    logger.info(f"Validating {len(sch_files)} schematic files in {directory}")

    for sch_file in sch_files:
        result = validator.validate_schematic_file(sch_file)
        results[sch_file.name] = result

        # Log results
        if result.passed:
            logger.info(f"✓ {sch_file.name}: PASSED")
        else:
            logger.error(f"✗ {sch_file.name}: FAILED with {len(result.errors)} errors")
            for error in result.errors:
                logger.error(f"  - {error}")

        # Log warnings
        for warning in result.warnings:
            logger.warning(f"  - {warning}")

    # Summary
    passed = sum(1 for r in results.values() if r.passed)
    total = len(results)
    logger.info(f"Validation complete: {passed}/{total} passed")

    return results


if __name__ == "__main__":
    """
    Command-line validation tool.

    Usage:
        python schematic_validator.py <path_to_kicad_folder>
    """
    import sys

    if len(sys.argv) < 2:
        print("Usage: python schematic_validator.py <path_to_kicad_folder>")
        sys.exit(1)

    directory = Path(sys.argv[1])

    if not directory.exists():
        print(f"Error: Directory not found: {directory}")
        sys.exit(1)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    # Run validation
    results = validate_schematic_directory(directory)

    # Print summary
    print("\n" + "="*70)
    print("VALIDATION SUMMARY")
    print("="*70)

    passed = sum(1 for r in results.values() if r.passed)
    failed = len(results) - passed

    print(f"Total schematics: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        print("\nFailed schematics:")
        for name, result in results.items():
            if not result.passed:
                print(f"  - {name}: {len(result.errors)} errors")
        sys.exit(1)
    else:
        print("\n✓ All schematics passed validation!")
        sys.exit(0)
