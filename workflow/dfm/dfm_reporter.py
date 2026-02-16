# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
DFM Reporter - HTML Report Generation
======================================

Generates professional HTML reports for DFM check results.

Features:
- Color-coded violations (red=error, orange=warning, blue=suggestion)
- Summary statistics with visual indicators
- Detailed violation list with fix suggestions
- Ready/Not Ready badge for manufacturing
- Fabricator-specific information
- Responsive design for desktop and mobile

Output:
- Self-contained HTML file (inline CSS, no dependencies)
- Professional appearance matching CopperPilot brand
- Print-friendly styling

Author: CopperPilot Development Team
Created: November 9, 2025
"""

from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import logging

from .dfm_checker import DFMResult, DFMViolation, ViolationSeverity

logger = logging.getLogger(__name__)


class DFMReporter:
    """
    Generate professional HTML reports for DFM check results.

    Usage:
        reporter = DFMReporter()
        html = reporter.generate_html(dfm_result, circuit_name="Power Supply")
        Path("dfm_report.html").write_text(html)
    """

    def __init__(self):
        """Initialize DFM reporter"""
        self.logger = logger

    def generate_html(self,
                     dfm_result: DFMResult,
                     circuit_name: str = "Circuit",
                     pcb_file: Optional[str] = None) -> str:
        """
        Generate HTML report from DFM check results.

        Args:
            dfm_result: DFM check results
            circuit_name: Name of the circuit (for title)
            pcb_file: Optional path to PCB file (for reference)

        Returns:
            Complete HTML document as string
        """
        logger.info(f"Generating DFM HTML report for {circuit_name}")

        # Build HTML sections
        html_parts = []

        # Header
        html_parts.append(self._generate_header())

        # Title and summary
        html_parts.append(self._generate_title(circuit_name, pcb_file))
        html_parts.append(self._generate_summary(dfm_result))

        # Violations by severity
        if dfm_result.errors:
            html_parts.append(self._generate_violations_section(
                "Critical Errors (Must Fix)",
                dfm_result.errors,
                "error"
            ))

        if dfm_result.warnings:
            html_parts.append(self._generate_violations_section(
                "Warnings (Should Fix)",
                dfm_result.warnings,
                "warning"
            ))

        if dfm_result.suggestions:
            html_parts.append(self._generate_violations_section(
                "Suggestions (Optional Improvements)",
                dfm_result.suggestions,
                "suggestion"
            ))

        # Passed checks (if no violations)
        if dfm_result.status == "PASS":
            html_parts.append(self._generate_passed_checks(dfm_result))

        # Fabricator info
        html_parts.append(self._generate_fab_info(dfm_result))

        # Footer
        html_parts.append(self._generate_footer())

        # Combine all parts
        html = '\n'.join(html_parts)

        logger.info(f"Generated {len(html)} character HTML report")
        return html

    def _generate_header(self) -> str:
        """Generate HTML header with inline CSS"""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DFM Check Report - CopperPilot</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #1B1D21 0%, #2A2D33 100%);
            color: #1B1D21;
            line-height: 1.6;
            padding: 2rem 1rem;
            min-height: 100vh;
        }

        .container {
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }

        .header {
            background: linear-gradient(135deg, #B87333 0%, #8C4A1E 100%);
            color: white;
            padding: 2rem;
            text-align: center;
        }

        .header h1 {
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .header .subtitle {
            font-size: 1rem;
            opacity: 0.9;
        }

        .content {
            padding: 2rem;
        }

        .summary {
            background: #f9fafb;
            border-left: 4px solid #B87333;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border-radius: 8px;
        }

        .status-badge {
            display: inline-block;
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-weight: 700;
            font-size: 1.1rem;
            margin-bottom: 1rem;
        }

        .status-pass {
            background: #10b981;
            color: white;
        }

        .status-warning {
            background: #f59e0b;
            color: white;
        }

        .status-fail {
            background: #ef4444;
            color: white;
        }

        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }

        .stat-item {
            background: white;
            padding: 1rem;
            border-radius: 8px;
            border: 1px solid #e5e7eb;
        }

        .stat-value {
            font-size: 2rem;
            font-weight: 700;
            color: #B87333;
        }

        .stat-label {
            font-size: 0.875rem;
            color: #6b7280;
            margin-top: 0.25rem;
        }

        .section {
            margin-bottom: 2rem;
        }

        .section h2 {
            font-size: 1.5rem;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #e5e7eb;
        }

        .violation {
            background: white;
            border: 1px solid #e5e7eb;
            border-left: 4px solid;
            padding: 1rem;
            margin-bottom: 1rem;
            border-radius: 8px;
        }

        .violation.error {
            border-left-color: #ef4444;
            background: #fef2f2;
        }

        .violation.warning {
            border-left-color: #f59e0b;
            background: #fffbeb;
        }

        .violation.suggestion {
            border-left-color: #3b82f6;
            background: #eff6ff;
        }

        .violation-header {
            font-weight: 700;
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .violation-icon {
            font-size: 1.2rem;
        }

        .violation-details {
            margin: 0.5rem 0;
            color: #4b5563;
        }

        .violation-location {
            font-size: 0.875rem;
            color: #6b7280;
            font-family: 'Courier New', monospace;
            background: #f9fafb;
            padding: 0.5rem;
            border-radius: 4px;
            margin: 0.5rem 0;
        }

        .fix-suggestion {
            background: #dbeafe;
            border-left: 3px solid #3b82f6;
            padding: 0.75rem;
            margin-top: 0.5rem;
            border-radius: 4px;
        }

        .fix-suggestion strong {
            color: #1e40af;
        }

        .auto-fixable {
            display: inline-block;
            background: #10b981;
            color: white;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 700;
            margin-left: 0.5rem;
        }

        .fab-info {
            background: #f9fafb;
            padding: 1.5rem;
            border-radius: 8px;
            margin-top: 2rem;
        }

        .fab-info h3 {
            margin-bottom: 1rem;
        }

        .fab-specs {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
        }

        .fab-spec {
            font-size: 0.875rem;
        }

        .fab-spec strong {
            color: #B87333;
        }

        .footer {
            background: #f9fafb;
            padding: 1.5rem;
            text-align: center;
            color: #6b7280;
            font-size: 0.875rem;
            border-top: 1px solid #e5e7eb;
        }

        @media print {
            body {
                background: white;
                padding: 0;
            }

            .container {
                box-shadow: none;
            }
        }
    </style>
</head>
<body>
<div class="container">
"""

    def _generate_title(self, circuit_name: str, pcb_file: Optional[str]) -> str:
        """Generate title section"""
        file_info = f"<div class='subtitle'>File: {Path(pcb_file).name}</div>" if pcb_file else ""

        return f"""
    <div class="header">
        <h1>Design for Manufacturability Report</h1>
        <div class="subtitle">Circuit: {circuit_name}</div>
        {file_info}
        <div class="subtitle">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>
"""

    def _generate_summary(self, result: DFMResult) -> str:
        """Generate summary section with status and statistics"""
        # Determine status badge
        if result.status == "PASS":
            badge_class = "status-pass"
            badge_icon = "✅"
            badge_text = "READY FOR MANUFACTURING"
        elif result.status == "WARNING":
            badge_class = "status-warning"
            badge_icon = "⚠️"
            badge_text = "WARNINGS PRESENT"
        else:
            badge_class = "status-fail"
            badge_icon = "❌"
            badge_text = "NOT READY - ERRORS MUST BE FIXED"

        return f"""
    <div class="content">
        <div class="summary">
            <div class="status-badge {badge_class}">
                {badge_icon} {badge_text}
            </div>
            <div class="stats">
                <div class="stat-item">
                    <div class="stat-value">{len(result.errors)}</div>
                    <div class="stat-label">Critical Errors</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{len(result.warnings)}</div>
                    <div class="stat-label">Warnings</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{len(result.suggestions)}</div>
                    <div class="stat-label">Suggestions</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">{result.checks_performed}</div>
                    <div class="stat-label">Checks Performed</div>
                </div>
            </div>
            <div style="margin-top: 1rem;">
                <strong>Target Fabricator:</strong> {result.fab_name}<br>
                <strong>Board Size:</strong> {result.board_size[0]:.1f}mm × {result.board_size[1]:.1f}mm<br>
                <strong>Layers:</strong> {result.layer_count}
            </div>
        </div>
"""

    def _generate_violations_section(self,
                                     title: str,
                                     violations: List[DFMViolation],
                                     severity_class: str) -> str:
        """Generate section for violations of a specific severity"""
        violations_html = []

        for i, violation in enumerate(violations, 1):
            # Icon based on severity
            if severity_class == "error":
                icon = "❌"
            elif severity_class == "warning":
                icon = "⚠️"
            else:
                icon = "ℹ️"

            # Auto-fixable badge
            auto_fix_badge = '<span class="auto-fixable">AUTO-FIXABLE</span>' if violation.auto_fixable else ""

            # Location info
            location_parts = []
            for key, value in violation.location.items():
                location_parts.append(f"{key}: {value}")
            location_str = " | ".join(location_parts)

            violation_html = f"""
        <div class="violation {severity_class}">
            <div class="violation-header">
                <span class="violation-icon">{icon}</span>
                <span>{i}. {violation.message}</span>
                {auto_fix_badge}
            </div>
            <div class="violation-details">
                <strong>Current Value:</strong> {violation.current_value}<br>
                <strong>Required Value:</strong> {violation.required_value}
            </div>
            <div class="violation-location">{location_str}</div>
            <div class="fix-suggestion">
                <strong>💡 Fix:</strong> {violation.fix_suggestion}
            </div>
        </div>
"""
            violations_html.append(violation_html)

        return f"""
        <div class="section">
            <h2>{title}</h2>
            {''.join(violations_html)}
        </div>
"""

    def _generate_passed_checks(self, result: DFMResult) -> str:
        """Generate section showing all checks passed"""
        return """
        <div class="section">
            <h2>✅ All Checks Passed</h2>
            <div style="background: #d1fae5; border-left: 4px solid #10b981; padding: 1.5rem; border-radius: 8px;">
                <p style="font-size: 1.1rem; color: #065f46;">
                    <strong>Excellent!</strong> This design meets all DFM requirements for manufacturing.
                    The board can be sent to fabrication without design changes.
                </p>
            </div>
        </div>
"""

    def _generate_fab_info(self, result: DFMResult) -> str:
        """Generate fabricator capabilities section"""
        from .dfm_checker import DFMChecker

        fab_caps = DFMChecker.FAB_CAPABILITIES.get(result.fab_name, {})

        return f"""
        <div class="fab-info">
            <h3>{result.fab_name} Specifications</h3>
            <div class="fab-specs">
                <div class="fab-spec">
                    <strong>Min Trace Width:</strong> {fab_caps.get('min_trace_width', 'N/A')}mm
                </div>
                <div class="fab-spec">
                    <strong>Min Spacing:</strong> {fab_caps.get('min_trace_spacing', 'N/A')}mm
                </div>
                <div class="fab-spec">
                    <strong>Min Drill:</strong> {fab_caps.get('min_drill_diameter', 'N/A')}mm
                </div>
                <div class="fab-spec">
                    <strong>Min Via:</strong> {fab_caps.get('min_via_diameter', 'N/A')}mm
                </div>
                <div class="fab-spec">
                    <strong>Max Board Size:</strong> {fab_caps.get('max_board_size', ('N/A', 'N/A'))[0]}mm × {fab_caps.get('max_board_size', ('N/A', 'N/A'))[1]}mm
                </div>
                <div class="fab-spec">
                    <strong>Available Layers:</strong> {', '.join(map(str, fab_caps.get('layers_available', [])))}
                </div>
            </div>
        </div>
"""

    def _generate_footer(self) -> str:
        """Generate footer"""
        return """
        <div class="footer">
            Generated by <strong>CopperPilot</strong> - AI-Powered PCB Design Automation<br>
            For more information, visit the CopperPilot documentation
        </div>
    </div>
</body>
</html>
"""

    def save_report(self,
                   dfm_result: DFMResult,
                   output_path: Path,
                   circuit_name: str = "Circuit",
                   pcb_file: Optional[str] = None) -> Path:
        """
        Generate and save HTML report to file.

        Args:
            dfm_result: DFM check results
            output_path: Path to save HTML file
            circuit_name: Name of circuit
            pcb_file: Optional PCB file path

        Returns:
            Path to saved report
        """
        html = self.generate_html(dfm_result, circuit_name, pcb_file)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding='utf-8')

        logger.info(f"DFM report saved to: {output_path}")
        return output_path


# Convenience function
def generate_dfm_report(dfm_result: DFMResult,
                       output_file: str,
                       circuit_name: str = "Circuit") -> Path:
    """
    Convenience function to generate DFM HTML report.

    Usage:
        report_path = generate_dfm_report(
            dfm_result,
            "output/circuit_DFM.html",
            circuit_name="Power Supply"
        )
        print(f"Report saved to: {report_path}")
    """
    reporter = DFMReporter()
    return reporter.save_report(dfm_result, Path(output_file), circuit_name)
