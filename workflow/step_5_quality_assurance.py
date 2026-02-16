# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 5: Quality Assurance
Runs forensic validations on lowlevel, BOM, and converter outputs.

Notes for maintainers:
- This module does NOT fail the process directly; it returns a structured
  summary with pass/fail flags so the caller (workflow) can decide gating.
- External validator scripts are invoked as subprocesses for isolation, and
  their exit codes are used as pass/fail signals.

TC #62 (2025-11-30): Added Advanced Quality Metrics integration
- Component Derating Checks (IPC-2221B/IPC-9592)
- Power Dissipation Calculations
- Thermal Estimates (junction temperature)
- Trace Impedance Analysis
- Signal Integrity Checks (partial)
- DFM Multi-Vendor Profiles (JLCPCB, PCBWay, OSH Park, Seeed Fusion)
- DFT Requirements (testpoints, debug headers)
- Assembly Checks (fiducials, orientation)

CRITICAL: Quality metrics run on LOWLEVEL JSON (format-agnostic) so the same
validation applies to ALL output formats (KiCad, Eagle, EasyEDA Pro).
"""

from __future__ import annotations

import json
import csv
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from server.config import config

# TC #62: Import format-agnostic quality metrics validator
try:
    from scripts.validators.quality_metrics_validator import (
        QualityMetricsValidator,
        QualityMetricsResult,
        DFMVendorProfile,
        Severity,
    )
    QUALITY_METRICS_AVAILABLE = True
except ImportError:
    QUALITY_METRICS_AVAILABLE = False


class Step5QualityAssurance:
    """Quality Assurance runner for the full project output."""

    def __init__(self, project_id: str, websocket_manager=None):
        self.project_id = project_id
        self.websocket_manager = websocket_manager

    async def _send_progress(self, msg: str, percent: int = 0, detail: Optional[Dict[str, Any]] = None):
        """Send incremental QA progress updates over WebSocket if available."""
        if not self.websocket_manager:
            return
        payload = {
            "type": "step_progress",
            "step": 5,
            "step_name": "Quality Assurance",
            "progress_percent": percent,
            "message": msg,
        }
        if detail:
            payload.update(detail)
        try:
            await self.websocket_manager.send_update(self.project_id, payload)
        except Exception:
            pass

    def _run_script(self, script: Path, args: list[str]) -> Dict[str, Any]:
        """
        Run a validator Python script as a subprocess.
        Returns a dict with success flag, returncode, stdout, stderr.
        """
        try:
            proc = subprocess.run(
                ["python3", str(script), *args],
                capture_output=True,
                text=True,
                check=False,
            )
            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _run_quality_metrics(self, lowlevel_dir: Path, vendor: str = "JLCPCB") -> Dict[str, Any]:
        """
        TC #62: Run advanced quality metrics validation on lowlevel circuits.

        This is FORMAT-AGNOSTIC - runs on lowlevel JSON before conversion.
        Same validation applies to KiCad, Eagle, and EasyEDA Pro outputs.

        Args:
            lowlevel_dir: Path to lowlevel circuit JSON files
            vendor: DFM vendor profile to use (JLCPCB, PCBWay, OSH Park, Seeed Fusion)

        Returns:
            Dict with success flag and detailed metrics results
        """
        if not QUALITY_METRICS_AVAILABLE:
            return {
                "success": True,  # Don't fail if validator not available
                "skipped": True,
                "reason": "QualityMetricsValidator not available",
            }

        result: Dict[str, Any] = {
            "success": True,
            "circuits": {},
            "summary": {
                "total_circuits": 0,
                "circuits_with_issues": 0,
                "total_issues": 0,
                "by_severity": {"info": 0, "warning": 0, "error": 0, "critical": 0},
                "by_category": {},
            },
        }

        try:
            # TC #82 FIX: QualityMetricsValidator expects vendor_profile as a string,
            # not a dict. DFMVendorProfile.get_profile() returns a dict, but the
            # validator uses the string internally to look up the profile.
            # Removed the unnecessary get_profile() call and pass the string directly.

            # Phase G (Forensic Fix 20260208): Parse fixer report for per-circuit issue counts
            fixer_issues_by_circuit = {}
            fixer_report_path = lowlevel_dir / "circuit_fixer_report.txt"
            if fixer_report_path.exists():
                try:
                    fixer_text = fixer_report_path.read_text()
                    # Parse "Status: FAILED" line
                    fixer_failed = "Status: FAILED" in fixer_text
                    # Try to extract per-circuit critical counts from report
                    import re as _re
                    for match in _re.finditer(r'(?:circuit_)?(\w+).*?(\d+)\s+critical', fixer_text, _re.IGNORECASE):
                        fixer_issues_by_circuit[match.group(1).lower()] = int(match.group(2))
                except Exception:
                    fixer_failed = False
            else:
                fixer_failed = False

            # Phase G: Parse rating validation report for per-circuit violations
            rating_violations_by_circuit = {}
            rating_report_path = lowlevel_dir / "rating_validation_report.json"
            if rating_report_path.exists():
                try:
                    rating_data = json.loads(rating_report_path.read_text())
                    for mod_result in rating_data.get("modules", []):
                        mod_name = mod_result.get("module_name", "").lower().replace(" ", "_")
                        critical_violations = [
                            v for v in mod_result.get("violations", [])
                            if v.get("severity") == "critical"
                        ]
                        if critical_violations:
                            rating_violations_by_circuit[mod_name] = critical_violations
                except Exception:
                    pass

            # Process each lowlevel circuit
            for circuit_file in sorted(lowlevel_dir.glob("circuit_*.json")):
                circuit_name = circuit_file.stem

                # Phase B: Skip the mega-module
                if "integrated_circuit" in circuit_name.lower():
                    continue

                result["summary"]["total_circuits"] += 1

                try:
                    validator = QualityMetricsValidator(
                        vendor_profile=vendor,
                    )
                    metrics_result = validator.validate_circuit(circuit_file)

                    circuit_result = {
                        "passed": metrics_result.passed,
                        "issue_count": len(metrics_result.issues),
                        "power_analysis": None,
                        "thermal_analysis": None,
                        "issues_by_severity": {},
                        "fixer_issues": 0,
                        "rating_violations": [],
                    }

                    # Extract power analysis
                    if metrics_result.power_analysis:
                        pa = metrics_result.power_analysis
                        total_power = pa.total_power_mw
                        # Phase G: If power is 0.0 for this circuit, report honestly
                        if total_power == 0.0:
                            circuit_result["power_analysis"] = {
                                "status": "not_calculated",
                                "total_power_mw": 0.0,
                                "per_rail_current": pa.per_rail_current,
                                "warning": "Power analysis returned 0 — check component operating point data",
                            }
                        else:
                            circuit_result["power_analysis"] = {
                                "total_power_mw": total_power,
                                "per_rail_current": pa.per_rail_current,
                            }

                    # Extract thermal analysis
                    if metrics_result.thermal_analysis:
                        ta = metrics_result.thermal_analysis
                        # Phase G: If thermal is 0.0, report honestly
                        if ta.max_junction_temp_c == 0.0:
                            circuit_result["thermal_analysis"] = {
                                "status": "not_calculated",
                                "max_junction_temp_c": 0.0,
                                "ambient_temp_c": ta.ambient_temp_c,
                                "hottest_component": ta.hottest_component,
                                "warning": "Thermal analysis returned 0 — check component thermal data",
                            }
                        else:
                            circuit_result["thermal_analysis"] = {
                                "max_junction_temp_c": ta.max_junction_temp_c,
                                "ambient_temp_c": ta.ambient_temp_c,
                                "hottest_component": ta.hottest_component,
                            }

                    # Count issues by severity
                    for issue in metrics_result.issues:
                        sev = issue.severity.value
                        circuit_result["issues_by_severity"][sev] = \
                            circuit_result["issues_by_severity"].get(sev, 0) + 1
                        result["summary"]["by_severity"][sev] = \
                            result["summary"]["by_severity"].get(sev, 0) + 1
                        result["summary"]["total_issues"] += 1

                        cat = issue.category.value
                        result["summary"]["by_category"][cat] = \
                            result["summary"]["by_category"].get(cat, 0) + 1

                    # Phase G: Cross-reference fixer report — override pass if critical issues
                    circuit_key = circuit_name.replace("circuit_", "").lower()
                    fixer_count = fixer_issues_by_circuit.get(circuit_key, 0)
                    circuit_result["fixer_issues"] = fixer_count
                    if fixer_count > 0:
                        circuit_result["passed"] = False

                    # Phase G: Propagate rating validation failures
                    rating_viols = rating_violations_by_circuit.get(circuit_key, [])
                    circuit_result["rating_violations"] = rating_viols
                    if rating_viols:
                        circuit_result["passed"] = False

                    if not circuit_result["passed"]:
                        result["summary"]["circuits_with_issues"] += 1
                        if (circuit_result["issues_by_severity"].get("critical", 0) > 0
                                or fixer_count > 0 or rating_viols):
                            result["success"] = False

                    result["circuits"][circuit_name] = circuit_result

                except Exception as e:
                    result["circuits"][circuit_name] = {
                        "passed": False,
                        "error": str(e),
                    }
                    result["summary"]["circuits_with_issues"] += 1

            result["vendor_profile"] = vendor

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)

        return result

    def _bom_basic_checks(self, bom_dir: Path, lowlevel_dir: Path) -> Dict[str, Any]:
        """
        Perform basic BOM checks:
        - Count unique items in BOM.json
        - Sum quantities in BOM.csv
        - Compare quantity sum to total components in lowlevel circuits
        """
        result: Dict[str, Any] = {"success": True, "checks": {}}

        bom_json = bom_dir / "BOM.json"
        bom_csv = bom_dir / "BOM.csv"
        checks = result["checks"]

        try:
            if bom_json.exists():
                data = json.loads(bom_json.read_text())
                items = data.get("items") or data.get("bom") or data.get("BOM") or []
                checks["bom_items"] = len(items) if isinstance(items, list) else 0
            else:
                result["success"] = False
                checks["bom_items"] = 0
                checks["error"] = "BOM.json missing"

            qty_sum = 0
            if bom_csv.exists():
                with open(bom_csv, newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader, None)
                    for row in reader:
                        try:
                            # Assume Quantity is column 2 (index 1) or named 'Quantity'
                            if header and "Quantity" in header:
                                idx = header.index("Quantity")
                                qty_sum += int(row[idx])
                            else:
                                qty_sum += int(row[1])
                        except Exception:
                            continue
            else:
                result["success"] = False
                checks["error_csv"] = "BOM.csv missing"

            checks["bom_quantity_sum"] = qty_sum

            # Count components across all lowlevel circuits
            total_components = 0
            for p in lowlevel_dir.glob("circuit_*.json"):
                data = json.loads(p.read_text())
                circ = data.get("circuit", data)
                total_components += len(circ.get("components", []))
            checks["lowlevel_total_components"] = total_components

            if qty_sum and total_components and qty_sum != total_components:
                result["success"] = False
                checks["mismatch"] = True
            else:
                checks["mismatch"] = False

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)

        return result

    def _semantic_lowlevel_check(self, lowlevel_dir: Path) -> Dict[str, Any]:
        """
        Fix 7 (Forensic Fix Plan): Semantic quality check on lowlevel circuits.

        Verifies that the lowlevel output contains meaningful circuit designs
        rather than fallback skeleton circuits. Checks:
        - No module has ``moduleType: 'fallback'``
        - Each module meets the minimum component count from config
        - Circuit fixer report (if present) does not show FAILED status
        - design.json ``validationStatus.status`` is not 'failed'

        Returns:
            Dict with ``success`` bool and detail fields.
        """
        min_components = config.QUALITY_GATES["min_components_per_module"]
        result: Dict[str, Any] = {
            "success": True,
            "fallback_modules": [],
            "undersized_modules": [],
            "fixer_status": "unknown",
            "design_status": "unknown",
            "checks": {},
        }

        # Check each circuit JSON
        circuit_files = sorted(lowlevel_dir.glob("circuit_*.json"))
        if not circuit_files:
            result["success"] = False
            result["checks"]["no_circuits"] = "No circuit files found in lowlevel directory"
            return result

        for circuit_file in circuit_files:
            try:
                data = json.loads(circuit_file.read_text())
                circ = data.get("circuit", data)
                module_name = circ.get("moduleName", circuit_file.stem)
                components = circ.get("components", [])
                component_count = len(components)

                # Check fallback
                if circ.get("moduleType") == "fallback":
                    result["fallback_modules"].append(module_name)
                    result["success"] = False

                # Check minimum component count
                if component_count < min_components:
                    result["undersized_modules"].append({
                        "module": module_name,
                        "components": component_count,
                        "minimum": min_components,
                    })
                    result["success"] = False

            except Exception as e:
                result["success"] = False
                result["checks"][circuit_file.name] = f"Parse error: {e}"

        # Check circuit fixer report
        fixer_report = lowlevel_dir / "circuit_fixer_report.txt"
        if fixer_report.exists():
            try:
                fixer_text = fixer_report.read_text()
                if "Status: FAILED" in fixer_text:
                    result["fixer_status"] = "FAILED"
                    result["success"] = False
                else:
                    result["fixer_status"] = "PASSED"
            except Exception:
                result["fixer_status"] = "error"
        else:
            result["fixer_status"] = "not_found"

        # Check design.json validationStatus
        design_json = lowlevel_dir / "design.json"
        if design_json.exists():
            try:
                design_data = json.loads(design_json.read_text())
                vs = design_data.get("validationStatus", {})
                result["design_status"] = vs.get("status", "unknown")
                if vs.get("status") == "failed":
                    result["success"] = False
            except Exception:
                result["design_status"] = "error"

        result["checks"]["circuit_count"] = len(circuit_files)
        result["checks"]["fallback_count"] = len(result["fallback_modules"])
        result["checks"]["undersized_count"] = len(result["undersized_modules"])

        return result

    async def process(self, output_root: str) -> Dict[str, Any]:
        """
        Run full QA on the given output directory.
        Returns a structured summary and writes qa/qa_summary.json.
        """
        out = Path(output_root)
        qa_dir = out / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)

        summary: Dict[str, Any] = {
            "success": True,
            "sections": {},
        }

        # 1) Lowlevel quality (structural check via test script)
        await self._send_progress("Validating lowlevel circuits...", 5)
        lowlevel_dir = out / "lowlevel"
        lowlevel_script = Path("tests/analyze_lowlevel_circuits.py")
        lowlevel_res = self._run_script(lowlevel_script, [str(lowlevel_dir)])
        summary["sections"]["lowlevel"] = lowlevel_res
        if not lowlevel_res.get("success"):
            summary["success"] = False

        # 1b) Fix 7: Semantic quality check (fallback detection, min components)
        await self._send_progress("Running semantic quality checks on lowlevel...", 10)
        semantic_res = self._semantic_lowlevel_check(lowlevel_dir)
        summary["sections"]["lowlevel_semantic"] = semantic_res
        if not semantic_res.get("success"):
            summary["success"] = False

        # 2) BOM checks
        await self._send_progress("Checking BOM integrity...", 20)
        bom_dir = out / "bom"
        bom_res = self._bom_basic_checks(bom_dir, lowlevel_dir)
        summary["sections"]["bom"] = bom_res
        if not bom_res.get("success"):
            summary["success"] = False

        # 3) KiCad deep forensic
        # Use the deep wrapper which performs preflight checks and then
        # executes the primary KiCad forensic validator (includes ERC/DRC).
        await self._send_progress("Running KiCad deep forensic validation...", 40)
        kicad_dir = out / "kicad"
        kicad_script = Path("tests/validate_kicad_deep_forensic.py")
        kicad_res = self._run_script(kicad_script, [])
        summary["sections"]["kicad"] = kicad_res
        if not kicad_res.get("success"):
            summary["success"] = False

        # 4) EasyEDA Pro deep forensic
        await self._send_progress("Running EasyEDA Pro deep validation...", 55)
        easyeda_dir = out / "easyeda_pro"
        easyeda_script = Path("tests/validate_easyeda_pro_deep_forensic.py")
        easyeda_res = self._run_script(easyeda_script, [])
        summary["sections"]["easyeda_pro"] = easyeda_res
        if not easyeda_res.get("success"):
            summary["success"] = False

        # 5) Eagle deep forensic
        await self._send_progress("Running Eagle deep forensic validation...", 70)
        eagle_dir = out / "eagle"
        eagle_script = Path("tests/validate_eagle_deep_forensic.py")
        eagle_res = self._run_script(eagle_script, [])
        summary["sections"]["eagle"] = eagle_res
        if not eagle_res.get("success"):
            summary["success"] = False

        # 6) Schematics (PNG) deep validation
        await self._send_progress("Validating schematics (PNG) output...", 85)
        sch_dir = out / "schematics"
        sch_script = Path("tests/validate_schematics_deep_forensic.py")
        sch_res = self._run_script(sch_script, [])
        summary["sections"]["schematics"] = sch_res
        if not sch_res.get("success"):
            summary["success"] = False

        # 7) Schematics description (text) deep validation
        await self._send_progress("Validating schematics description (text) output...", 90)
        schd_dir = out / "schematics_desc"
        schd_script = Path("tests/validate_schematics_desc_deep_forensic.py")
        schd_res = self._run_script(schd_script, [])
        summary["sections"]["schematics_desc"] = schd_res
        if not schd_res.get("success"):
            summary["success"] = False

        # 8) TC #62: Advanced Quality Metrics (FORMAT-AGNOSTIC)
        # Runs on lowlevel JSON - same validation applies to ALL output formats
        await self._send_progress("Running advanced quality metrics...", 95)
        quality_res = self._run_quality_metrics(lowlevel_dir, vendor="JLCPCB")
        summary["sections"]["quality_metrics"] = quality_res
        # Note: quality_metrics only fails on CRITICAL issues (not warnings/info)
        if not quality_res.get("success"):
            summary["success"] = False

        # Write quality metrics report separately for detailed analysis
        if quality_res and not quality_res.get("skipped"):
            (qa_dir / "quality_metrics_report.json").write_text(
                json.dumps(quality_res, indent=2)
            )

        # Write reports
        # 1) Internal forensic JSON (not packaged for user)
        (qa_dir / "internal_qa_report.json").write_text(json.dumps(summary, indent=2))

        # 2) Internal forensic HTML (detailed)
        internal_html = self._render_internal_html(summary)
        (qa_dir / "internal_qa_report.html").write_text(internal_html)

        # 3) User-facing HTML (clean summary; to be packaged)
        user_html = self._render_user_html(summary)
        (qa_dir / "user_qa_report.html").write_text(user_html)

        await self._send_progress("QA complete", 100, {"qa_success": summary["success"]})

        return summary

    def _render_internal_html(self, summary: Dict[str, Any]) -> str:
        """Render a thorough forensic HTML report for internal use."""
        def block(title: str, content: str) -> str:
            return f"<h3>{title}</h3>\n<pre>{content}</pre>\n"

        rows = []
        rows.append(f"<p><strong>QA Success:</strong> {'PASS' if summary.get('success') else 'FAIL'}</p>")
        sections = summary.get('sections', {})
        for name, res in sections.items():
            ok = res.get('success')
            header = f"{name.upper()} — {'PASS' if ok else 'FAIL'} (rc={res.get('returncode', 'NA')})"
            out = res.get('stdout', '') or ''
            err = res.get('stderr', '') or ''
            body = ""
            if out:
                body += block("stdout", out[:20000])  # truncate to 20k chars just in case
            if err:
                body += block("stderr", err[:20000])
            # For BOM, embed checks
            if name == 'bom':
                b = res.get('checks', {})
                body += block("bom checks", json.dumps(b, indent=2))
            rows.append(f"<section><h2>{header}</h2>{body}</section>")

        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>Internal QA Report</title>"
            "<style>body{font-family:Arial,Helvetica,sans-serif;line-height:1.4;padding:20px;}"
            "h1{border-bottom:1px solid #ddd;padding-bottom:8px;} pre{background:#f7f7f7;padding:12px;overflow:auto;}"
            "section{margin-bottom:24px;} .pass{color:#2e7d32;} .fail{color:#c62828;}</style>"
            "</head><body>"
            f"<h1>Internal QA Report — Project {self.project_id}</h1>"
            + "".join(rows) + "</body></html>"
        )

    def _render_user_html(self, summary: Dict[str, Any]) -> str:
        """Render a user-facing, professional summary HTML (to be packaged)."""
        def line(ok: bool, label: str, desc: str = "") -> str:
            icon = '✅' if ok else '❌'
            return f"<tr><td>{icon}</td><td><strong>{label}</strong></td><td>{desc}</td></tr>"

        sections = summary.get('sections', {})
        kicad_ok = sections.get('kicad', {}).get('success', False)
        eagle_ok = sections.get('eagle', {}).get('success', False)
        easy_ok = sections.get('easyeda_pro', {}).get('success', False)
        low_ok = sections.get('lowlevel', {}).get('success', False)
        bom_ok = sections.get('bom', {}).get('success', False)
        sch_ok = sections.get('schematics', {}).get('success', False)
        schd_ok = sections.get('schematics_desc', {}).get('success', False)

        # Fix 7: Semantic quality check
        sem = sections.get('lowlevel_semantic', {})
        sem_ok = sem.get('success', False)
        sem_desc = 'Fallback detection + min component count'
        fb_list = sem.get('fallback_modules', [])
        if fb_list:
            sem_desc = f"{len(fb_list)} fallback module(s): {', '.join(fb_list)}"
        elif sem.get('undersized_modules'):
            sem_desc = f"{len(sem['undersized_modules'])} undersized module(s)"

        # TC #62: Quality metrics
        qm = sections.get('quality_metrics', {})
        qm_ok = qm.get('success', False)
        qm_skipped = qm.get('skipped', False)

        # Build quality metrics description
        qm_desc = 'Derating, power, thermal, impedance, DFM'
        if qm_skipped:
            qm_desc = 'Skipped (validator not available)'
        elif qm.get('summary'):
            s = qm['summary']
            qm_desc = f"Checked {s.get('total_circuits', 0)} circuits, {s.get('total_issues', 0)} issues"

        rows = [
            line(low_ok, 'Low-Level Circuits', 'Structure and connectivity checks'),
            line(sem_ok, 'Low-Level Semantic Quality', sem_desc),
            line(bom_ok, 'BOM Integrity', 'Counts, quantities, totals'),
            line(kicad_ok, 'KiCad Deep Forensic', 'Preflight + ERC/DRC/format gates'),
            line(eagle_ok, 'Eagle Deep Forensic', 'Preflight + geometry/structure gates'),
            line(easy_ok, 'EasyEDA Pro Deep Forensic', 'Preflight + import readiness gates'),
            line(sch_ok, 'Schematics (PNG)', 'Coverage and minimum size checks'),
            line(schd_ok, 'Schematics Description (Text)', 'Per-circuit presence + content heuristics'),
            line(qm_ok or qm_skipped, 'Quality Metrics', qm_desc),
        ]

        status = 'PASS' if summary.get('success') else 'FAIL'
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>Quality Assurance Summary</title>"
            "<style>body{font-family:Arial,Helvetica,sans-serif;line-height:1.5;padding:20px;}"
            "h1{border-bottom:1px solid #ddd;padding-bottom:8px;margin-bottom:18px;}"
            "table{border-collapse:collapse;width:100%;} td,th{border:1px solid #eee;padding:8px;}"
            "th{background:#fafafa;text-align:left;} .badge{display:inline-block;padding:4px 8px;border-radius:4px;}"
            ".pass{background:#e8f5e9;color:#2e7d32;} .fail{background:#ffebee;color:#c62828;}" 
            "</style></head><body>"
            f"<h1>Quality Assurance Summary — Project {self.project_id} "
            f"<span class='badge {'pass' if summary.get('success') else 'fail'}'>{status}</span></h1>"
            "<table><thead><tr><th>Status</th><th>Check</th><th>Notes</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>"
            "<p>This summary is included for convenience. Detailed forensic logs are kept internally.</p>"
            "</body></html>"
        )
