# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Validator module for checking KiCad output files."""

import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
import logging

from ..utils.base import PipelineStage, ConversionContext, ValidationError

logger = logging.getLogger(__name__)

class Validator(PipelineStage):
    """Validate KiCad output files and circuit integrity."""

    def process(self, context: ConversionContext) -> ConversionContext:
        """Run validation checks on generated files."""
        try:
            validation_results = {
                'erc': self._run_erc_checks(context),
                'drc': self._run_drc_checks(context),
                'connectivity': self._check_connectivity(context),
                'files': self._validate_files(context),
                'summary': {}
            }

            # Generate summary
            total_errors = sum(len(v.get('errors', [])) for v in validation_results.values() if isinstance(v, dict))
            total_warnings = sum(len(v.get('warnings', [])) for v in validation_results.values() if isinstance(v, dict))

            validation_results['summary'] = {
                'passed': total_errors == 0,
                'total_errors': total_errors,
                'total_warnings': total_warnings
            }

            context.validation = validation_results

            # Log results
            if total_errors > 0:
                logger.error(f"Validation failed with {total_errors} errors")
                for check_name, check_results in validation_results.items():
                    if isinstance(check_results, dict) and check_results.get('errors'):
                        for error in check_results['errors']:
                            logger.error(f"  {check_name}: {error}")
            else:
                logger.info(f"Validation passed with {total_warnings} warnings")

            # Generate validation report
            self._generate_validation_report(context)

            return context

        except Exception as e:
            return self.handle_error(e, context)

    def _run_erc_checks(self, context: ConversionContext) -> Dict[str, Any]:
        """Run Electrical Rules Check."""
        errors = []
        warnings = []

        components = context.components
        nets = context.netlist.get('nets', {})

        # Check 1: All component pins connected
        for ref_des, comp in components.items():
            pins = comp.get('pins', [])
            pin_net_mapping = comp.get('pinNetMapping', {})

            for pin in pins:
                if str(pin) not in pin_net_mapping:
                    # Check if pin is in any net
                    pin_connected = False
                    for net_data in nets.values():
                        for node in net_data.get('nodes', []):
                            if node['ref'] == ref_des and str(node['pin']) == str(pin):
                                pin_connected = True
                                break
                        if pin_connected:
                            break

                    if not pin_connected:
                        # Check if it's a power pin that might be implicitly connected
                        if comp.get('type') in ['ic', 'opamp'] and pin in ['7', '14', '4', '8']:
                            warnings.append(f"{ref_des} pin {pin} appears unconnected (may be power pin)")
                        else:
                            errors.append(f"{ref_des} pin {pin} is not connected")

        # Check 2: No floating nets (single-node nets)
        for net_name, net_data in nets.items():
            nodes = net_data.get('nodes', [])
            if len(nodes) == 1:
                if net_data.get('incomplete'):
                    warnings.append(f"Net {net_name} has only one connection")
                else:
                    errors.append(f"Net {net_name} is floating (only one connection)")

        # Check 3: Power supply connectivity
        power_components = [c for c, d in components.items() if d.get('type') in ['regulator', 'transformer']]
        if power_components and 'VCC' not in nets and '+5V' not in nets:
            warnings.append("No VCC or +5V net found despite presence of power components")

        # Check 4: Ground connectivity
        if 'GND' not in nets:
            warnings.append("No GND net found - circuit may lack ground reference")

        # Check 5: Duplicate connections
        pin_to_nets = {}
        for net_name, net_data in nets.items():
            for node in net_data.get('nodes', []):
                pin_key = f"{node['ref']}.{node['pin']}"
                if pin_key not in pin_to_nets:
                    pin_to_nets[pin_key] = []
                pin_to_nets[pin_key].append(net_name)

        # Only report actual duplicates (same pin in different nets)
        for pin_key, net_list in pin_to_nets.items():
            unique_nets = list(set(net_list))
            if len(unique_nets) > 1:
                errors.append(f"Pin {pin_key} connected to multiple nets: {', '.join(unique_nets)}")

        return {
            'errors': errors,
            'warnings': warnings,
            'passed': len(errors) == 0
        }

    def _run_drc_checks(self, context: ConversionContext) -> Dict[str, Any]:
        """Run Design Rules Check."""
        errors = []
        warnings = []

        pcb_layout = context.layout.get('pcb', {})
        routes = context.routes.get('pcb', {})

        # Check 1: Component placement overlaps
        positions = {}
        for ref_des, pos in pcb_layout.items():
            grid_pos = (round(pos[0]), round(pos[1]))
            if grid_pos in positions:
                errors.append(f"Components {ref_des} and {positions[grid_pos]} overlap at position {grid_pos}")
            positions[grid_pos] = ref_des

        # Check 2: Track width compliance
        min_track_width = 0.15  # mm
        for net_name, segments in routes.items():
            for segment in segments:
                if segment.get('type') == 'track':
                    width = segment.get('width', 0)
                    if width < min_track_width:
                        errors.append(f"Track width {width}mm in net {net_name} below minimum {min_track_width}mm")

        # Check 3: Board dimensions
        if pcb_layout:
            x_coords = [pos[0] for pos in pcb_layout.values()]
            y_coords = [pos[1] for pos in pcb_layout.values()]

            board_width = max(x_coords) - min(x_coords) if x_coords else 0
            board_height = max(y_coords) - min(y_coords) if y_coords else 0

            if board_width > 200:  # mm
                warnings.append(f"Board width {board_width}mm exceeds typical limit of 200mm")
            if board_height > 200:  # mm
                warnings.append(f"Board height {board_height}mm exceeds typical limit of 200mm")

        # Check 4: Via specifications
        min_via_size = 0.5  # mm
        min_via_drill = 0.3  # mm

        # Since we don't explicitly generate vias yet, this is a placeholder
        # for future enhancement

        return {
            'errors': errors,
            'warnings': warnings,
            'passed': len(errors) == 0
        }

    def _check_connectivity(self, context: ConversionContext) -> Dict[str, Any]:
        """Check overall circuit connectivity."""
        errors = []
        warnings = []
        statistics = {}

        components = context.components
        nets = context.netlist.get('nets', {})

        # Count connected vs unconnected components
        connected_components = set()
        for net_data in nets.values():
            for node in net_data.get('nodes', []):
                connected_components.add(node['ref'])

        unconnected = set(components.keys()) - connected_components

        if unconnected:
            for ref_des in unconnected:
                comp_type = components[ref_des].get('type')
                if comp_type in ['test_point', 'mounting_hole']:
                    # These don't need connections
                    pass
                else:
                    errors.append(f"Component {ref_des} has no connections")

        statistics['total_components'] = len(components)
        statistics['connected_components'] = len(connected_components)
        statistics['unconnected_components'] = len(unconnected)
        statistics['total_nets'] = len(nets)
        statistics['connectivity_percentage'] = (len(connected_components) / len(components) * 100) if components else 0

        return {
            'errors': errors,
            'warnings': warnings,
            'statistics': statistics,
            'passed': len(errors) == 0
        }

    def _validate_files(self, context: ConversionContext) -> Dict[str, Any]:
        """Validate generated file syntax."""
        errors = []
        warnings = []

        output_files = context.output

        for file_type, filepath in output_files.items():
            if filepath:
                path = Path(filepath)
                if not path.exists():
                    errors.append(f"{file_type} file does not exist: {filepath}")
                else:
                    # Check file syntax
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            content = f.read()

                        if file_type == 'schematic':
                            if not self._validate_schematic_syntax(content):
                                errors.append(f"Schematic file has invalid syntax")
                        elif file_type == 'pcb':
                            if not self._validate_pcb_syntax(content):
                                errors.append(f"PCB file has invalid syntax")
                        elif file_type == 'project':
                            if not self._validate_project_syntax(content):
                                errors.append(f"Project file has invalid syntax")

                    except Exception as e:
                        errors.append(f"Error reading {file_type} file: {e}")

        return {
            'errors': errors,
            'warnings': warnings,
            'passed': len(errors) == 0
        }

    def _validate_schematic_syntax(self, content: str) -> bool:
        """Validate KiCad schematic file syntax."""
        # Check for required elements
        required = [
            r'\(kicad_sch',
            r'\(version \d+\)',
            r'\(uuid [a-f0-9-]+\)',
            r'\)'
        ]

        for pattern in required:
            if not re.search(pattern, content, re.IGNORECASE):
                return False

        # Check parentheses balance
        open_count = content.count('(')
        close_count = content.count(')')
        if open_count != close_count:
            logger.error(f"Unbalanced parentheses: {open_count} open, {close_count} close")
            return False

        return True

    def _validate_pcb_syntax(self, content: str) -> bool:
        """Validate KiCad PCB file syntax."""
        # Check for required elements
        required = [
            r'\(kicad_pcb',
            r'\(version \d+\)',
            r'\(uuid [a-f0-9-]+\)',
            r'\(layers',
            r'\)'
        ]

        for pattern in required:
            if not re.search(pattern, content, re.IGNORECASE):
                return False

        # Check parentheses balance
        open_count = content.count('(')
        close_count = content.count(')')
        if open_count != close_count:
            logger.error(f"Unbalanced parentheses: {open_count} open, {close_count} close")
            return False

        return True

    def _validate_project_syntax(self, content: str) -> bool:
        """Validate KiCad project file syntax."""
        # Check for required elements
        required = [
            r'\(kicad_pro',
            r'\(version \d+\)',
            r'\(project',
            r'\)'
        ]

        for pattern in required:
            if not re.search(pattern, content, re.IGNORECASE):
                return False

        return True

    def _generate_validation_report(self, context: ConversionContext) -> None:
        """Generate validation report file."""
        report_path = context.output_path / "validation_report.txt"

        lines = [
            "KiCad Converter Validation Report",
            "=" * 50,
            f"Generated: {Path(context.output_path).name}",
            "",
            "VALIDATION SUMMARY",
            "-" * 30,
            f"Status: {'PASSED' if context.validation['summary']['passed'] else 'FAILED'}",
            f"Total Errors: {context.validation['summary']['total_errors']}",
            f"Total Warnings: {context.validation['summary']['total_warnings']}",
            ""
        ]

        # ERC Results
        lines.extend([
            "ELECTRICAL RULES CHECK (ERC)",
            "-" * 30
        ])
        erc = context.validation.get('erc', {})
        if erc.get('errors'):
            lines.append("Errors:")
            for error in erc['errors']:
                lines.append(f"  - {error}")
        else:
            lines.append("No errors found")

        if erc.get('warnings'):
            lines.append("Warnings:")
            for warning in erc['warnings']:
                lines.append(f"  - {warning}")
        lines.append("")

        # DRC Results
        lines.extend([
            "DESIGN RULES CHECK (DRC)",
            "-" * 30
        ])
        drc = context.validation.get('drc', {})
        if drc.get('errors'):
            lines.append("Errors:")
            for error in drc['errors']:
                lines.append(f"  - {error}")
        else:
            lines.append("No errors found")

        if drc.get('warnings'):
            lines.append("Warnings:")
            for warning in drc['warnings']:
                lines.append(f"  - {warning}")
        lines.append("")

        # Connectivity Results
        lines.extend([
            "CONNECTIVITY CHECK",
            "-" * 30
        ])
        conn = context.validation.get('connectivity', {})
        stats = conn.get('statistics', {})
        lines.extend([
            f"Total Components: {stats.get('total_components', 0)}",
            f"Connected: {stats.get('connected_components', 0)}",
            f"Unconnected: {stats.get('unconnected_components', 0)}",
            f"Connectivity: {stats.get('connectivity_percentage', 0):.1f}%",
            f"Total Nets: {stats.get('total_nets', 0)}"
        ])

        if conn.get('errors'):
            lines.append("\nErrors:")
            for error in conn['errors']:
                lines.append(f"  - {error}")
        lines.append("")

        # File Validation
        lines.extend([
            "FILE VALIDATION",
            "-" * 30
        ])
        files = context.validation.get('files', {})
        if files.get('errors'):
            lines.append("Errors:")
            for error in files['errors']:
                lines.append(f"  - {error}")
        else:
            lines.append("All files valid")

        # Write report
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"Validation report saved to {report_path}")