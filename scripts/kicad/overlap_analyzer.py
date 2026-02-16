#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Component Overlap Analyzer - Forensic analysis of PCB component placement

This tool parses KiCad PCB files to:
- Extract component positions and dimensions
- Calculate clearances between components
- Identify overlapping components
- Generate detailed overlap reports

PHASE 1 TASK 1.1: Analyze component overlaps in generated PCBs

Author: Claude Code / CopperPilot AI System
Date: 2025-11-19
"""

from __future__ import annotations
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class Component:
    """Component data extracted from PCB file"""
    reference: str
    footprint: str
    x: float  # mm
    y: float  # mm
    rotation: float  # degrees
    width: float  # mm (bounding box)
    height: float  # mm (bounding box)
    layer: str


@dataclass
class Overlap:
    """Overlap between two components"""
    comp1: str
    comp2: str
    distance: float  # mm (negative = overlap)
    severity: str  # 'critical', 'warning', 'acceptable'


class OverlapAnalyzer:
    """Analyze component overlaps in KiCad PCB files"""

    def __init__(self):
        self.min_clearance = 0.5  # mm - minimum acceptable clearance
        self.warning_clearance = 2.0  # mm - clearance that triggers warning
        self.critical_clearance = 0.0  # mm - actual overlap

    def parse_pcb_file(self, pcb_file: Path) -> List[Component]:
        """
        Parse .kicad_pcb file and extract component information.

        Returns:
            List of Component objects with position and dimension data
        """
        if not pcb_file.exists():
            raise FileNotFoundError(f"PCB file not found: {pcb_file}")

        with open(pcb_file, 'r', encoding='utf-8') as f:
            content = f.read()

        components = []

        # Extract footprints using regex
        # Pattern: (footprint "Library:Footprint" (layer "F.Cu") ... (at x y rotation) ...)
        footprint_pattern = r'\(footprint\s+"([^"]+)"\s+\(layer\s+"([^"]+)"\)\s+.*?\(at\s+([\d.-]+)\s+([\d.-]+)(?:\s+([\d.-]+))?\)'

        # Also need to extract the reference designator
        # Pattern: (fp_text reference "R1" ...)

        # More comprehensive pattern to capture entire footprint block
        footprint_blocks = re.finditer(r'\(footprint\s+"([^"]+)".*?\n(?:.*?\n)*?\)', content, re.DOTALL)

        for match in footprint_blocks:
            block = match.group(0)

            # Extract footprint name
            footprint_match = re.search(r'\(footprint\s+"([^"]+)"', block)
            if not footprint_match:
                continue
            footprint = footprint_match.group(1)

            # Extract layer
            layer_match = re.search(r'\(layer\s+"([^"]+)"\)', block)
            layer = layer_match.group(1) if layer_match else "F.Cu"

            # Extract position (at x y rotation)
            at_match = re.search(r'\(at\s+([\d.-]+)\s+([\d.-]+)(?:\s+([\d.-]+))?\)', block)
            if not at_match:
                continue
            x = float(at_match.group(1))
            y = float(at_match.group(2))
            rotation = float(at_match.group(3)) if at_match.group(3) else 0.0

            # Extract reference designator
            ref_match = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', block)
            reference = ref_match.group(1) if ref_match else "Unknown"

            # Estimate dimensions from footprint name (will be improved with footprint database)
            width, height = self._estimate_dimensions(footprint)

            components.append(Component(
                reference=reference,
                footprint=footprint,
                x=x,
                y=y,
                rotation=rotation,
                width=width,
                height=height,
                layer=layer
            ))

        return components

    def _estimate_dimensions(self, footprint: str) -> Tuple[float, float]:
        """
        Estimate component dimensions from footprint name.

        This is a simplified estimation. For accurate dimensions, use footprint database.

        Returns:
            (width, height) in mm
        """
        # Common footprint patterns

        # SMD passive components (e.g., R_0805, C_1206)
        match = re.search(r'_(\d{4})(?:_|$)', footprint)
        if match:
            size_code = match.group(1)
            # Decode metric size code (e.g., 0805 = 0.08" x 0.05" = 2.0mm x 1.25mm)
            try:
                length_mils = int(size_code[:2]) * 10  # First 2 digits * 10
                width_mils = int(size_code[2:]) * 10   # Last 2 digits * 10
                length_mm = length_mils * 0.0254
                width_mm = width_mils * 0.0254
                return (length_mm, width_mm)
            except ValueError:
                pass

        # SOIC packages
        if 'SOIC' in footprint:
            # Extract pin count if possible
            pin_match = re.search(r'SOIC[-_](\d+)', footprint)
            if pin_match:
                pins = int(pin_match.group(1))
                width = 3.9  # SOIC standard width
                length = 1.27 * (pins / 2) + 1.0  # 1.27mm pitch + margin
                return (length, width)
            return (6.0, 3.9)  # Default SOIC-8

        # DIP packages
        if 'DIP' in footprint:
            pin_match = re.search(r'DIP[-_](\d+)', footprint)
            if pin_match:
                pins = int(pin_match.group(1))
                width = 7.62  # Standard DIP width
                length = 2.54 * (pins / 2) + 1.0  # 2.54mm (0.1") pitch
                return (length, width)
            return (15.24, 7.62)  # Default DIP-14

        # QFP packages
        if 'QFP' in footprint or 'LQFP' in footprint:
            # Try to extract dimensions from name (e.g., QFP-64_10x10mm)
            dim_match = re.search(r'(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)mm', footprint)
            if dim_match:
                return (float(dim_match.group(1)), float(dim_match.group(2)))
            return (10.0, 10.0)  # Default QFP

        # Connectors
        if 'Pin_Header' in footprint or 'Connector' in footprint:
            return (20.0, 5.0)  # Rough estimate for headers/connectors

        # Default fallback for unknown footprints
        return (5.0, 5.0)

    def calculate_clearance(self, comp1: Component, comp2: Component) -> float:
        """
        Calculate minimum clearance between two components (bounding boxes).

        Returns:
            Clearance in mm (negative = overlap)
        """
        # Calculate bounding box edges
        comp1_left = comp1.x - comp1.width / 2
        comp1_right = comp1.x + comp1.width / 2
        comp1_bottom = comp1.y - comp1.height / 2
        comp1_top = comp1.y + comp1.height / 2

        comp2_left = comp2.x - comp2.width / 2
        comp2_right = comp2.x + comp2.width / 2
        comp2_bottom = comp2.y - comp2.height / 2
        comp2_top = comp2.y + comp2.height / 2

        # Calculate horizontal and vertical distances
        if comp1_right < comp2_left:
            # comp1 is to the left of comp2
            h_distance = comp2_left - comp1_right
        elif comp2_right < comp1_left:
            # comp2 is to the left of comp1
            h_distance = comp1_left - comp2_right
        else:
            # Horizontal overlap
            h_distance = min(
                comp1_right - comp2_left if comp1_right < comp2_right else comp2_right - comp1_left,
                0
            ) if comp1_right >= comp2_left and comp2_right >= comp1_left else 0
            h_distance = -abs(h_distance) if h_distance != 0 else -min(
                abs(comp1_right - comp2_left),
                abs(comp2_right - comp1_left)
            )

        if comp1_top < comp2_bottom:
            # comp1 is below comp2
            v_distance = comp2_bottom - comp1_top
        elif comp2_top < comp1_bottom:
            # comp2 is below comp1
            v_distance = comp1_bottom - comp2_top
        else:
            # Vertical overlap
            v_distance = -min(
                abs(comp1_top - comp2_bottom),
                abs(comp2_top - comp1_bottom)
            )

        # If both h and v have positive distance, calculate Euclidean distance
        if h_distance > 0 and v_distance > 0:
            return (h_distance**2 + v_distance**2)**0.5

        # If one or both overlap, return the maximum (least negative) overlap
        return max(h_distance, v_distance)

    def analyze_overlaps(self, components: List[Component]) -> List[Overlap]:
        """
        Analyze all component pairs for overlaps/close spacing.

        Returns:
            List of Overlap objects sorted by severity
        """
        overlaps = []

        for i, comp1 in enumerate(components):
            for comp2 in components[i+1:]:
                # Skip if on different layers (unless both are through-hole)
                if comp1.layer != comp2.layer:
                    continue

                clearance = self.calculate_clearance(comp1, comp2)

                # Determine severity
                if clearance < self.critical_clearance:
                    severity = 'critical'  # Actual overlap
                elif clearance < self.min_clearance:
                    severity = 'warning'  # Too close
                elif clearance < self.warning_clearance:
                    severity = 'acceptable'  # Close but OK
                else:
                    continue  # Sufficient clearance, skip

                overlaps.append(Overlap(
                    comp1=comp1.reference,
                    comp2=comp2.reference,
                    distance=clearance,
                    severity=severity
                ))

        # Sort by severity then distance
        severity_order = {'critical': 0, 'warning': 1, 'acceptable': 2}
        overlaps.sort(key=lambda o: (severity_order[o.severity], o.distance))

        return overlaps

    def generate_report(self, pcb_file: Path) -> Dict:
        """
        Generate comprehensive overlap analysis report for a PCB file.

        Returns:
            Dictionary with analysis results
        """
        components = self.parse_pcb_file(pcb_file)
        overlaps = self.analyze_overlaps(components)

        # Count by severity
        critical_count = sum(1 for o in overlaps if o.severity == 'critical')
        warning_count = sum(1 for o in overlaps if o.severity == 'warning')
        acceptable_count = sum(1 for o in overlaps if o.severity == 'acceptable')

        return {
            'pcb_file': str(pcb_file),
            'component_count': len(components),
            'total_pairs_analyzed': len(components) * (len(components) - 1) // 2,
            'overlap_summary': {
                'critical_overlaps': critical_count,  # Actual overlaps
                'warning_clearances': warning_count,  # <0.5mm clearance
                'acceptable_clearances': acceptable_count,  # 0.5-2.0mm clearance
                'total_issues': len(overlaps)
            },
            'overlaps': [
                {
                    'comp1': o.comp1,
                    'comp2': o.comp2,
                    'clearance_mm': round(o.distance, 3),
                    'severity': o.severity
                }
                for o in overlaps
            ],
            'components': [
                {
                    'reference': c.reference,
                    'footprint': c.footprint,
                    'position': {'x': round(c.x, 3), 'y': round(c.y, 3)},
                    'dimensions': {'width': round(c.width, 3), 'height': round(c.height, 3)},
                    'layer': c.layer
                }
                for c in components
            ]
        }

    def analyze_directory(self, kicad_dir: Path) -> Dict:
        """
        Analyze all PCB files in a directory.

        Returns:
            Dictionary with analysis results for all PCBs
        """
        results = {
            'analyzed_at': Path(__file__).parent.parent.parent.name,
            'directory': str(kicad_dir),
            'circuits': []
        }

        pcb_files = list(kicad_dir.glob('*.kicad_pcb'))

        for pcb_file in sorted(pcb_files):
            try:
                circuit_report = self.generate_report(pcb_file)
                results['circuits'].append(circuit_report)
            except Exception as e:
                results['circuits'].append({
                    'pcb_file': str(pcb_file),
                    'error': str(e)
                })

        # Generate summary across all circuits
        total_components = sum(c.get('component_count', 0) for c in results['circuits'] if 'component_count' in c)
        total_critical = sum(c.get('overlap_summary', {}).get('critical_overlaps', 0) for c in results['circuits'] if 'overlap_summary' in c)
        total_warnings = sum(c.get('overlap_summary', {}).get('warning_clearances', 0) for c in results['circuits'] if 'overlap_summary' in c)

        results['summary'] = {
            'total_circuits': len(pcb_files),
            'total_components': total_components,
            'total_critical_overlaps': total_critical,
            'total_warning_clearances': total_warnings,
            'circuits_with_critical_overlaps': sum(1 for c in results['circuits'] if c.get('overlap_summary', {}).get('critical_overlaps', 0) > 0)
        }

        return results


def main():
    """Run overlap analysis on latest output directory"""
    import sys

    if len(sys.argv) > 1:
        kicad_dir = Path(sys.argv[1])
    else:
        # Find latest output directory
        output_dir = Path(__file__).parent.parent.parent / 'output'
        subdirs = [d for d in output_dir.iterdir() if d.is_dir()]
        if not subdirs:
            print("Error: No output directories found")
            sys.exit(1)
        latest = max(subdirs, key=lambda d: d.name)
        kicad_dir = latest / 'kicad'

    if not kicad_dir.exists():
        print(f"Error: Directory not found: {kicad_dir}")
        sys.exit(1)

    print(f"Analyzing PCB files in: {kicad_dir}")
    print()

    analyzer = OverlapAnalyzer()
    results = analyzer.analyze_directory(kicad_dir)

    # Print summary
    print("=" * 80)
    print("COMPONENT OVERLAP ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"Total circuits analyzed: {results['summary']['total_circuits']}")
    print(f"Total components: {results['summary']['total_components']}")
    print(f"Critical overlaps (actual overlap): {results['summary']['total_critical_overlaps']}")
    print(f"Warning clearances (<0.5mm): {results['summary']['total_warning_clearances']}")
    print(f"Circuits with critical overlaps: {results['summary']['circuits_with_critical_overlaps']}")
    print()

    # Print per-circuit details
    for circuit in results['circuits']:
        if 'error' in circuit:
            print(f"❌ {Path(circuit['pcb_file']).stem}: ERROR - {circuit['error']}")
            continue

        summary = circuit['overlap_summary']
        print(f"📋 {Path(circuit['pcb_file']).stem}:")
        print(f"   Components: {circuit['component_count']}")
        print(f"   Critical overlaps: {summary['critical_overlaps']}")
        print(f"   Warning clearances: {summary['warning_clearances']}")

        # Show worst overlaps
        if summary['critical_overlaps'] > 0:
            critical_overlaps = [o for o in circuit['overlaps'] if o['severity'] == 'critical']
            print(f"   Worst overlaps:")
            for overlap in critical_overlaps[:5]:  # Show top 5
                print(f"      - {overlap['comp1']} ↔ {overlap['comp2']}: {overlap['clearance_mm']}mm")
        print()

    # Save full report to JSON
    report_file = kicad_dir / 'overlap_analysis_report.json'
    with open(report_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"Full report saved to: {report_file}")


if __name__ == '__main__':
    main()
