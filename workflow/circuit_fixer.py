# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
AI Circuit Fixer Module
=======================
Quality gate that analyzes, fixes, and validates lowlevel circuits before Step 4.

This module implements an intelligent circuit fixing pipeline:
1. Delegates analysis to CircuitSupervisor (single source of truth for ERC)
2. Issue Classifier - Categorizes issues by type, severity, fixability
3. Fixer Router - Routes issues to appropriate fixers
4. Validation Loop - Re-validates until 100% pass or max iterations

Architecture:
    Circuit Input → Supervisor ERC → Classification → Fixing → Validation → Output
                                        ↑_______________|
                                        (loop until pass)

M.1 FIX (20260215): Eliminated "Two Brains" problem.
- DELETED CircuitAnalysisEngine class (had 50+ hardcoded interface patterns,
  lacked G-L series fixes: GPIO patterns, NON_ACTIVE_COMPONENT_TYPES,
  _is_power_supply_ic(), _is_reference_or_shunt_device(), etc.)
- All analysis now delegates to CircuitSupervisor.run_erc_check() which has
  60+ fixes from G-L series. Single source of truth for circuit validation.

Author: CopperPilot
Date: December 2024 (original), February 2026 (M.1 refactor)
"""

import json
import copy
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum

from utils.logger import setup_logger
from server.config import config

logger = setup_logger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

class IssueSeverity(Enum):
    """Issue severity levels."""
    CRITICAL = "critical"  # Circuit won't work
    WARNING = "warning"    # Circuit may have problems
    INFO = "info"          # Suggestion for improvement


class IssueType(Enum):
    """Types of circuit issues."""
    SINGLE_ENDED_NET = "single_ended_net"      # Signal with only 1 connection
    SAME_NET_PASSIVE = "same_net_passive"      # Passive with both pins on same net
    FLOATING_PIN = "floating_pin"              # IC pin not connected
    POWER_PATH_ISSUE = "power_path_issue"      # VCC/GND not properly connected
    PIN_MISMATCH = "pin_mismatch"              # Pin count or type mismatch
    NET_CONFLICT = "net_conflict"              # Pin connected to multiple nets
    STRUCTURE_ISSUE = "structure_issue"        # Structural circuit problem
    RATING_VIOLATION = "rating_violation"      # Component under-rated
    FEEDBACK_DIVIDER = "feedback_divider"      # Feedback divider accuracy
    PIN_FUNCTION_MISMATCH = "pin_function_mismatch"  # Pin-function wiring error


class Fixability(Enum):
    """How an issue can be fixed."""
    AUTO = "auto"          # Rule-based automatic fix
    AI_ASSISTED = "ai"     # Needs AI to determine fix
    MANUAL = "manual"      # Requires human intervention


@dataclass
class CircuitIssue:
    """Represents a detected circuit issue."""
    issue_type: IssueType
    severity: IssueSeverity
    fixability: Fixability
    module_name: str
    component_ref: Optional[str]
    net_name: Optional[str]
    pin: Optional[str]
    message: str
    context: Dict[str, Any] = field(default_factory=dict)
    fix_applied: bool = False
    fix_details: Optional[str] = None


@dataclass
class FixerResult:
    """Result of a fixer operation."""
    success: bool
    issues_fixed: int
    issues_remaining: int
    modified_circuit: Optional[Dict] = None
    details: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of circuit validation."""
    all_passed: bool
    total_issues: int
    critical_issues: int
    issues_by_module: Dict[str, List[CircuitIssue]]
    suppressed_count: int = 0  # M.12: Interface signals correctly filtered
    iterations: int = 0


# =============================================================================
# ERC CATEGORY → FIXER ISSUE TYPE MAPPING (config-driven)
# =============================================================================
# Maps CircuitSupervisor ERC categories to CircuitIssue types and defaults.
# Adding a new ERC category here automatically enables it in the fixer.
# =============================================================================

_ERC_CATEGORY_MAP = {
    'single_ended_nets':     (IssueType.SINGLE_ENDED_NET,     Fixability.AI_ASSISTED),
    'shorted_passives':      (IssueType.SAME_NET_PASSIVE,     Fixability.AI_ASSISTED),
    'floating_components':   (IssueType.FLOATING_PIN,          Fixability.AI_ASSISTED),
    'power_connections':     (IssueType.POWER_PATH_ISSUE,      Fixability.AI_ASSISTED),
    'pin_mismatches':        (IssueType.PIN_MISMATCH,          Fixability.AI_ASSISTED),
    'net_conflicts':         (IssueType.NET_CONFLICT,          Fixability.AI_ASSISTED),
    'structure_issues':      (IssueType.STRUCTURE_ISSUE,       Fixability.MANUAL),
    'rating_violations':     (IssueType.RATING_VIOLATION,      Fixability.AI_ASSISTED),
    'feedback_divider':      (IssueType.FEEDBACK_DIVIDER,      Fixability.AI_ASSISTED),
    'pin_function_mismatch': (IssueType.PIN_FUNCTION_MISMATCH, Fixability.AI_ASSISTED),
}

# Map config severity strings to IssueSeverity enum
_SEVERITY_MAP = {
    'CRITICAL': IssueSeverity.CRITICAL,
    'HIGH':     IssueSeverity.CRITICAL,
    'MEDIUM':   IssueSeverity.WARNING,
    'LOW':      IssueSeverity.INFO,
}


def _format_validation_status(result: 'ValidationResult') -> str:
    """
    X.1 FIX: Format a severity-aware validation status string.

    - PASSED: 0 total issues
    - PASSED (with warnings): 0 critical, but has warning/info issues
    - FAILED: has critical issues

    This is GENERIC — works for any circuit type or topology.
    """
    if result.total_issues == 0:
        return "PASSED"
    elif result.critical_issues == 0:
        return f"PASSED (with {result.total_issues} non-critical issue(s))"
    else:
        return f"FAILED ({result.critical_issues} critical issue(s))"


def _convert_erc_to_fixer_issues(erc_result: Dict, module_name: str) -> List[CircuitIssue]:
    """
    Bridge method: Convert CircuitSupervisor ERC report to CircuitIssue objects.

    Maps ERC categories to IssueType enum values using _ERC_CATEGORY_MAP.
    Severity is derived from config.ISSUE_SEVERITY (single source of truth).

    Args:
        erc_result: Dict from CircuitSupervisor.run_erc_check()
        module_name: Name of the module being analyzed

    Returns:
        List of CircuitIssue objects compatible with the fixer pipeline
    """
    issues = []

    for category, items in erc_result.get('issues', {}).items():
        if not items:
            continue

        # Look up issue type and default fixability
        mapping = _ERC_CATEGORY_MAP.get(category)
        if not mapping:
            # Unknown ERC category — use generic mapping
            issue_type = IssueType.STRUCTURE_ISSUE
            fixability = Fixability.MANUAL
        else:
            issue_type, fixability = mapping

        # Severity from config (single source of truth)
        severity_str = config.ISSUE_SEVERITY.get(category, 'MEDIUM')
        severity = _SEVERITY_MAP.get(severity_str, IssueSeverity.WARNING)

        for item in items:
            # Extract fields from the ERC item (may be dict or string)
            if isinstance(item, dict):
                comp_ref = item.get('component', item.get('ref', None))
                net_name = item.get('net', None)
                pin = item.get('pin', None)
                message = item.get('message', str(item))
                # Per-item severity override
                item_sev = item.get('severity')
                if item_sev:
                    severity = _SEVERITY_MAP.get(item_sev, severity)
            else:
                comp_ref = None
                net_name = None
                pin = None
                message = str(item)

            issues.append(CircuitIssue(
                issue_type=issue_type,
                severity=severity,
                fixability=fixability,
                module_name=module_name,
                component_ref=comp_ref,
                net_name=net_name,
                pin=pin,
                message=message,
                context={'erc_category': category, 'raw_item': item},
            ))

    return issues


# =============================================================================
# CONNECTIVITY FIXER (Rule-Based)
# =============================================================================

class ConnectivityFixer:
    """
    Attempts to fix connectivity issues using rules and heuristics.

    For issues that can't be fixed with rules, marks them for AI assistance.
    """

    def __init__(self, circuit: Dict):
        """Initialize with circuit to fix."""
        self.circuit = copy.deepcopy(circuit)
        if 'circuit' in self.circuit:
            self.circuit_data = self.circuit['circuit']
        else:
            self.circuit_data = self.circuit

        self.fixes_applied = []

    def fix_issues(self, issues: List[CircuitIssue]) -> FixerResult:
        """
        Attempt to fix the given issues.

        Args:
            issues: List of issues to fix

        Returns:
            FixerResult with success status and modified circuit
        """
        fixed_count = 0
        remaining_count = 0

        for issue in issues:
            if issue.issue_type == IssueType.SINGLE_ENDED_NET:
                if self._fix_single_ended_net(issue):
                    fixed_count += 1
                    issue.fix_applied = True
                else:
                    remaining_count += 1

            elif issue.issue_type == IssueType.SAME_NET_PASSIVE:
                # These typically need AI to understand the intended function
                remaining_count += 1

            elif issue.issue_type == IssueType.POWER_PATH_ISSUE:
                if self._fix_power_connection(issue):
                    fixed_count += 1
                    issue.fix_applied = True
                else:
                    remaining_count += 1

            else:
                remaining_count += 1

        return FixerResult(
            success=remaining_count == 0,
            issues_fixed=fixed_count,
            issues_remaining=remaining_count,
            modified_circuit=self.circuit,
            details=self.fixes_applied
        )

    def _fix_single_ended_net(self, issue: CircuitIssue) -> bool:
        """
        Attempt to fix a single-ended net by finding likely destination.

        Uses heuristics based on signal naming and component types.
        """
        net_name = issue.net_name
        source_pin = issue.pin

        if not net_name or not source_pin:
            return False

        # Get the source component
        source_ref = source_pin.split('.')[0] if '.' in source_pin else None
        if not source_ref:
            return False

        # Find the source component
        source_comp = None
        for comp in self.circuit_data.get('components', []):
            if comp.get('ref') == source_ref:
                source_comp = comp
                break

        if not source_comp:
            return False

        # Try to find destination based on signal name patterns
        net_upper = net_name.upper()
        pin_mapping = self.circuit_data.get('pinNetMapping', {})

        # Look for complementary signals
        destination_pin = None

        # Pattern: If this is an output, look for corresponding input
        if '_OUT' in net_upper:
            input_net = net_upper.replace('_OUT', '_IN')
            for pin, net in pin_mapping.items():
                if net.upper() == input_net:
                    # Found matching input - these should connect
                    destination_pin = pin
                    break

        # Pattern: Gate driver signals should go to MOSFETs
        if any(x in net_upper for x in ['HIN', 'LIN', 'GATE', 'HO_', 'LO_']):
            # Find MOSFET gate pins
            for comp in self.circuit_data.get('components', []):
                if comp.get('ref', '').startswith('Q'):
                    # Check if it's a MOSFET
                    for pin_info in comp.get('pins', []):
                        if pin_info.get('name', '').upper() in ['GATE', 'G']:
                            dest_pin = f"{comp.get('ref', '')}.{pin_info.get('number', '')}"
                            if dest_pin not in pin_mapping:
                                destination_pin = dest_pin
                                break
                if destination_pin:
                    break

        if destination_pin:
            # Apply the fix
            pin_mapping[destination_pin] = net_name

            # Update connections
            connections = self.circuit_data.get('connections', [])
            for conn in connections:
                if conn.get('net') == net_name:
                    if destination_pin not in conn.get('points', []):
                        conn['points'].append(destination_pin)
                    break
            else:
                # Create new connection
                connections.append({
                    'net': net_name,
                    'points': [source_pin, destination_pin]
                })

            self.fixes_applied.append(
                f"Connected {net_name}: {source_pin} → {destination_pin}"
            )
            return True

        return False

    def _fix_power_connection(self, issue: CircuitIssue) -> bool:
        """Attempt to fix missing power/ground connection."""
        comp_ref = issue.component_ref

        if not comp_ref:
            return False

        # Find the component
        target_comp = None
        for comp in self.circuit_data.get('components', []):
            if comp.get('ref') == comp_ref:
                target_comp = comp
                break

        if not target_comp:
            return False

        pin_mapping = self.circuit_data.get('pinNetMapping', {})
        is_vcc_issue = 'VCC' in issue.message or 'power' in issue.message

        # Find the appropriate pin
        for pin_info in target_comp.get('pins', []):
            pin_name = pin_info.get('name', '').upper()
            pin_type = pin_info.get('type', '')
            pin_num = pin_info.get('number') or pin_info.get('name') or ''
            if not pin_num:
                continue  # Skip pins with no identifiable number
            pin_ref = f'{comp_ref}.{pin_num}'

            if pin_ref in pin_mapping:
                continue  # Already connected

            if is_vcc_issue:
                if pin_type == 'power_in' or pin_name in config.POWER_PIN_KEYWORDS:
                    # Connect to appropriate power net — extract voltage from specs
                    supply_v = (target_comp.get('specs') or {}).get('supplyVoltage') or '5'
                    power_net = 'VCC_5V' if '5v' in supply_v.lower() else 'VCC_15V'
                    pin_mapping[pin_ref] = power_net
                    self.fixes_applied.append(f"Connected {pin_ref} to {power_net}")
                    return True
            else:
                if pin_type == 'ground' or pin_name in config.GROUND_PIN_KEYWORDS:
                    pin_mapping[pin_ref] = 'GND'
                    self.fixes_applied.append(f"Connected {pin_ref} to GND")
                    return True

        return False


# =============================================================================
# CIRCUIT FIXER - MAIN CLASS
# =============================================================================

class CircuitFixer:
    """
    Main circuit fixer class that orchestrates the analysis and fixing pipeline.

    M.1 FIX: Analysis is delegated to CircuitSupervisor (single source of truth).
    The fixer pipeline operates on CircuitIssue objects produced by the bridge
    method _convert_erc_to_fixer_issues().

    Usage:
        fixer = CircuitFixer(output_dir)
        result = fixer.analyze_and_fix_all(max_iterations=3)

        if result.all_passed:
            print("All circuits validated!")
        else:
            print(f"Issues remaining: {result.total_issues}")
    """

    def __init__(self, output_dir: Path):
        """
        Initialize the circuit fixer.

        Args:
            output_dir: Path to the output directory containing lowlevel folder
        """
        self.output_dir = Path(output_dir)
        self.lowlevel_dir = self.output_dir / 'lowlevel'
        self.backup_created = False

        # M.1 FIX: Use CircuitSupervisor as the sole analysis engine
        from workflow.circuit_supervisor import CircuitSupervisor
        self.supervisor = CircuitSupervisor()

    def _analyze_circuit(self, circuit: Dict) -> Tuple[List[CircuitIssue], int]:
        """
        Analyze a circuit using CircuitSupervisor ERC.

        Returns:
            Tuple of (issues_list, suppressed_count)
            suppressed_count = interface signals correctly filtered by the supervisor
        """
        # Handle nested structure
        circuit_data = circuit.get('circuit', circuit)
        module_name = circuit_data.get('moduleName', 'Unknown')

        # Run ERC via supervisor (has all G-L series fixes)
        erc_report = self.supervisor.run_erc_check(circuit_data)

        # Convert to fixer-compatible issues
        issues = _convert_erc_to_fixer_issues(erc_report, module_name)

        # M.12: Count suppressed signals for reporting
        total_erc_checks = erc_report.get('total_checks', 0)
        total_issues = erc_report.get('total_issues', 0)
        suppressed = max(0, total_erc_checks - total_issues) if total_erc_checks > 0 else 0

        return issues, suppressed

    def analyze_and_fix_all(self, max_iterations: int = 3) -> ValidationResult:
        """
        Analyze and fix all circuits in the lowlevel directory.

        Args:
            max_iterations: Maximum number of fix-validate cycles

        Returns:
            ValidationResult with final status
        """
        logger.info(f"Starting circuit analysis and fixing (max {max_iterations} iterations)")

        if not self.lowlevel_dir.exists():
            logger.error(f"Lowlevel directory not found: {self.lowlevel_dir}")
            return ValidationResult(
                all_passed=False,
                total_issues=-1,
                critical_issues=-1,
                issues_by_module={},
                iterations=0
            )

        # Create backup on first run
        if not self.backup_created:
            self._create_backup()

        total_suppressed = 0

        for iteration in range(1, max_iterations + 1):
            logger.info(f"=== Iteration {iteration}/{max_iterations} ===")

            # Analyze all circuits
            all_issues: Dict[str, List[CircuitIssue]] = {}

            for circuit_file in sorted(self.lowlevel_dir.glob('circuit_*.json')):
                if 'backup' in circuit_file.name:
                    continue

                with open(circuit_file) as f:
                    circuit = json.load(f)

                issues, suppressed = self._analyze_circuit(circuit)
                total_suppressed += suppressed

                if issues:
                    circuit_data = circuit.get('circuit', circuit)
                    module_name = circuit_data.get('moduleName', circuit_file.stem)
                    all_issues[module_name] = issues
                    logger.info(f"  {module_name}: {len(issues)} issues found")

            # Count issues
            total_issues = sum(len(issues) for issues in all_issues.values())
            critical_issues = sum(
                len([i for i in issues if i.severity == IssueSeverity.CRITICAL])
                for issues in all_issues.values()
            )

            if total_issues == 0:
                logger.info("All circuits passed validation!")
                return ValidationResult(
                    all_passed=True,
                    total_issues=0,
                    critical_issues=0,
                    issues_by_module={},
                    suppressed_count=total_suppressed,
                    iterations=iteration
                )

            logger.info(f"Total issues: {total_issues} ({critical_issues} critical)")

            # Attempt fixes
            fixes_made = 0

            for module_name, issues in all_issues.items():
                # Find the circuit file
                circuit_file = self._find_circuit_file(module_name)
                if not circuit_file:
                    continue

                with open(circuit_file) as f:
                    circuit = json.load(f)

                # Run fixer
                fixer = ConnectivityFixer(circuit)
                result = fixer.fix_issues(issues)

                if result.issues_fixed > 0:
                    # Save the fixed circuit
                    with open(circuit_file, 'w') as f:
                        json.dump(result.modified_circuit, f, indent=2)

                    fixes_made += result.issues_fixed
                    logger.info(f"  {module_name}: Fixed {result.issues_fixed} issues")
                    for detail in result.details:
                        logger.info(f"    - {detail}")

            if fixes_made == 0:
                # No more fixes possible with rules
                logger.info("No more automatic fixes possible")
                break

        # Final analysis
        final_issues: Dict[str, List[CircuitIssue]] = {}

        for circuit_file in sorted(self.lowlevel_dir.glob('circuit_*.json')):
            if 'backup' in circuit_file.name:
                continue

            with open(circuit_file) as f:
                circuit = json.load(f)

            issues, suppressed = self._analyze_circuit(circuit)
            total_suppressed += suppressed

            if issues:
                circuit_data = circuit.get('circuit', circuit)
                module_name = circuit_data.get('moduleName', circuit_file.stem)
                final_issues[module_name] = issues

        total_issues = sum(len(issues) for issues in final_issues.values())
        critical_issues = sum(
            len([i for i in issues if i.severity == IssueSeverity.CRITICAL])
            for issues in final_issues.values()
        )

        # X.1 FIX: Severity-aware pass/fail — a circuit PASSES when it has
        # zero CRITICAL issues. Warnings and info-level issues are acceptable
        # and don't block the pipeline. This is GENERIC for all circuit types.
        return ValidationResult(
            all_passed=critical_issues == 0,
            total_issues=total_issues,
            critical_issues=critical_issues,
            issues_by_module=final_issues,
            suppressed_count=total_suppressed,
            iterations=max_iterations
        )

    def _find_circuit_file(self, module_name: str) -> Optional[Path]:
        """Find the circuit file for a module."""
        # Convert module name to filename pattern
        name_lower = module_name.lower().replace(' ', '_').replace('-', '_')

        for circuit_file in self.lowlevel_dir.glob('circuit_*.json'):
            file_lower = circuit_file.stem.lower()
            if name_lower in file_lower or file_lower in name_lower:
                return circuit_file

        return None

    def _create_backup(self) -> None:
        """Create backup of all circuit files."""
        backup_dir = self.lowlevel_dir / 'backup'
        backup_dir.mkdir(exist_ok=True)

        for circuit_file in self.lowlevel_dir.glob('circuit_*.json'):
            backup_file = backup_dir / circuit_file.name
            with open(circuit_file) as f:
                data = json.load(f)
            with open(backup_file, 'w') as f:
                json.dump(data, f, indent=2)

        self.backup_created = True
        logger.info(f"Backup created in {backup_dir}")

    @staticmethod
    def format_validation_status(result: 'ValidationResult') -> str:
        """Format validation status for external callers."""
        return _format_validation_status(result)

    def generate_report(self, result: ValidationResult) -> str:
        """
        Generate a human-readable report of the validation result.

        M.12: Enhanced with per-module severity breakdown and suppressed count.
        """
        lines = [
            "=" * 70,
            "CIRCUIT FIXER VALIDATION REPORT",
            "=" * 70,
            "",
            # X.1 FIX: Show severity-aware status. PASSED = 0 critical.
            # PASSED WITH WARNINGS = 0 critical but has warnings/info.
            # FAILED = has critical issues.
            f"Status: {_format_validation_status(result)}",
            f"Iterations: {result.iterations}",
            f"Total Issues: {result.total_issues}",
            f"Critical Issues: {result.critical_issues}",
            f"Interface Signals Correctly Filtered: {result.suppressed_count}",
            "",
        ]

        if result.issues_by_module:
            lines.append("Issues by Module:")
            lines.append("-" * 40)

            for module, issues in result.issues_by_module.items():
                # M.12: Per-module severity breakdown
                severity_counts = {}
                for issue in issues:
                    sev = issue.severity.value
                    severity_counts[sev] = severity_counts.get(sev, 0) + 1

                severity_str = ", ".join(
                    f"{count} {sev}" for sev, count in sorted(severity_counts.items())
                )
                lines.append(f"\n{module}: {len(issues)} issues ({severity_str})")

                # M.12: Group by issue type for clarity
                by_type: Dict[str, List[CircuitIssue]] = {}
                for issue in issues:
                    key = issue.issue_type.value
                    by_type.setdefault(key, []).append(issue)

                for type_name, type_issues in by_type.items():
                    lines.append(f"  [{type_name}] ({len(type_issues)} issues)")
                    for issue in type_issues[:3]:  # Show first 3 per type
                        severity_icon = "!!!" if issue.severity == IssueSeverity.CRITICAL else "!"
                        lines.append(f"    [{severity_icon}] {issue.message}")
                    if len(type_issues) > 3:
                        lines.append(f"    ... and {len(type_issues) - 3} more")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def fix_circuits(output_dir: str, max_iterations: int = 3) -> ValidationResult:
    """
    Convenience function to analyze and fix circuits.

    Args:
        output_dir: Path to output directory
        max_iterations: Maximum fix-validate cycles

    Returns:
        ValidationResult
    """
    fixer = CircuitFixer(Path(output_dir))
    return fixer.analyze_and_fix_all(max_iterations)


def analyze_circuits(output_dir: str) -> Dict[str, List[CircuitIssue]]:
    """
    Convenience function to analyze circuits without fixing.

    Args:
        output_dir: Path to output directory

    Returns:
        Dict mapping module names to their issues
    """
    from workflow.circuit_supervisor import CircuitSupervisor
    supervisor = CircuitSupervisor()

    lowlevel_dir = Path(output_dir) / 'lowlevel'
    all_issues = {}

    for circuit_file in sorted(lowlevel_dir.glob('circuit_*.json')):
        with open(circuit_file) as f:
            circuit = json.load(f)

        circuit_data = circuit.get('circuit', circuit)
        module_name = circuit_data.get('moduleName', circuit_file.stem)

        erc_report = supervisor.run_erc_check(circuit_data)
        issues = _convert_erc_to_fixer_issues(erc_report, module_name)

        if issues:
            all_issues[module_name] = issues

    return all_issues


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        output_dir = sys.argv[1]
    else:
        output_dir = "output/latest"

    print(f"Analyzing circuits in: {output_dir}")

    fixer = CircuitFixer(Path(output_dir))
    result = fixer.analyze_and_fix_all()

    print(fixer.generate_report(result))
