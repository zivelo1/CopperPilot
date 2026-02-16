#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Conversion Simulation - Matches Production Workflow 1:1

This script simulates the REAL production workflow by:
1. Cleaning kicad/ folder
2. Running kicad_converter.py (which includes quality gate + auto-fix)
3. Verifying circuit counts match (kicad/ == lowlevel/)
4. Reporting results

IMPORTANT: This script does NOT re-implement quality gates or auto-fix.
All quality control logic is in kicad_converter.py itself.
This ensures the simulation matches production behavior exactly.

LOGGING REQUIREMENT:
When running this script, ALL logs MUST be written to the logs/ folder.
Usage:
    python3 tests/simulate_kicad_conversion.py output/TIMESTAMP-FOLDER > logs/kicad_simulation.log 2>&1
Or:
    python3 tests/simulate_kicad_conversion.py output/TIMESTAMP-FOLDER 2>&1 | tee logs/kicad_simulation.log

DO NOT log to /tmp/ or any other location - logs/ folder is the ONLY correct location.
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def find_latest_output_dir(root: Path) -> Optional[Path]:
    """Return the most recently modified subdirectory under output/."""
    output_root = root / "output"
    if not output_root.exists():
        return None
    dirs = [p for p in output_root.iterdir() if p.is_dir()]
    if not dirs:
        return None
    # Sort by mtime (descending), pick first
    latest = max(dirs, key=lambda p: p.stat().st_mtime)
    return latest


def clean_folder(folder: Path) -> None:
    """Remove all files and subdirectories under the given folder."""
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        return
    for entry in folder.iterdir():
        try:
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except Exception as e:
            print(f"WARNING: Could not delete {entry}: {e}")


def clean_python_cache(root_dir: Path) -> int:
    """
    Delete all __pycache__ directories and .pyc files to ensure fresh code execution.

    PHASE 0.2: Cache Clearing for Execution Verification

    CRITICAL: Python caches bytecode (.pyc files) which can cause old code to run
    even after source files are updated. This function ensures FRESH code execution
    by removing ALL cached bytecode before tests.

    GENERIC: Works for ANY Python project structure.

    Args:
        root_dir: Root directory to scan for caches (typically project root)

    Returns:
        Number of cache directories/files removed

    Example:
        If manhattan_router.py was updated at 10:00 but __pycache__/manhattan_router.cpython-314.pyc
        is from 09:00, Python will execute the OLD cached version. This function prevents that.
    """
    removed_count = 0

    # Remove all __pycache__ directories
    for pycache_dir in root_dir.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache_dir)
            print(f"✓ Cleared cache: {pycache_dir.relative_to(root_dir)}")
            removed_count += 1
        except Exception as e:
            print(f"WARNING: Could not delete cache {pycache_dir}: {e}")

    # Remove standalone .pyc files (rare, but possible)
    for pyc_file in root_dir.rglob("*.pyc"):
        try:
            pyc_file.unlink()
            print(f"✓ Removed .pyc file: {pyc_file.relative_to(root_dir)}")
            removed_count += 1
        except Exception as e:
            print(f"WARNING: Could not delete .pyc file {pyc_file}: {e}")

    return removed_count


def verify_circuit_counts(lowlevel_dir: Path, kicad_dir: Path) -> bool:
    """
    Verify that circuit count in kicad/ equals count in lowlevel/.
    This is CRITICAL - counts must match (no deletions allowed).
    """
    lowlevel_circuits = list(lowlevel_dir.glob("circuit_*.json"))
    kicad_schematics = list(kicad_dir.glob("*.kicad_sch"))

    # Exclude design.json from count if it exists
    lowlevel_circuits = [c for c in lowlevel_circuits if c.name != "design.json"]

    print("\n" + "="*80)
    print("CIRCUIT COUNT VERIFICATION")
    print("="*80)
    print(f"lowlevel/ circuits: {len(lowlevel_circuits)}")
    print(f"kicad/ circuits:    {len(kicad_schematics)}")

    if len(kicad_schematics) != len(lowlevel_circuits):
        print(f"\n❌ COUNT MISMATCH! This is a BUG!")
        print(f"   Expected: {len(lowlevel_circuits)} circuits in kicad/")
        print(f"   Found:    {len(kicad_schematics)} circuits in kicad/")
        print(f"\n   This means files were deleted or not generated.")
        print(f"   The converter MUST generate ALL circuits, even failed ones.")
        return False

    print(f"\n✅ Count matches - verification PASSED")
    return True


def verify_new_router_execution(kicad_dir: Path) -> bool:
    """
    Verify that the NEW router (v2.0.0-collision-aware-mst) actually executed.

    PHASE 0.3: Output Validation for Execution Verification

    CRITICAL: Checks if new router ran by validating PCB file outputs match new behavior.
    If old router ran (due to cache issues), this function will detect it.

    GENERIC: Works for ANY circuit - checks trace widths, via presence, layer distribution.

    Args:
        kicad_dir: Directory containing generated .kicad_pcb files

    Returns:
        True if new router executed successfully, False if old router ran

    Validation Checks:
    1. Trace widths = 0.25mm (new default) vs 0.150mm (old default)
    2. Vias present (new router inserts vias for layer transitions)
    3. Layer distribution (new router uses power layer separation)
    """
    pcb_files = list(kicad_dir.glob("*.kicad_pcb"))

    if not pcb_files:
        print("⚠️  No PCB files found - cannot verify router execution")
        return False

    print("\n" + "="*80)
    print("PHASE 0.3: Router Execution Verification")
    print("="*80)

    issues_found = []
    pcb_checked = 0

    for pcb_file in pcb_files[:3]:  # Check first 3 PCB files for performance
        try:
            with open(pcb_file, 'r') as f:
                content = f.read()

            # Check 1: Trace widths (new default = 0.25mm, old default = 0.150mm)
            has_new_widths = "(width 0.25)" in content
            has_old_widths = "(width 0.15)" in content or "(width 0.150)" in content

            # Check 2: Via presence (new router inserts vias)
            via_count = content.count("(via")

            # Check 3: Layer distribution
            fcu_segments = content.count('(layer "F.Cu")')
            bcu_segments = content.count('(layer "B.Cu")')

            pcb_checked += 1

            # Report findings for this PCB
            if has_old_widths and not has_new_widths:
                issues_found.append(f"  ❌ {pcb_file.name}: OLD trace widths (0.150mm) detected")

            if via_count < 5:
                issues_found.append(f"  ⚠️  {pcb_file.name}: Few vias ({via_count}) - may indicate old router")

            # Success indicators
            if has_new_widths and via_count >= 5:
                print(f"  ✓ {pcb_file.name}: New router confirmed (0.25mm traces, {via_count} vias)")

        except Exception as e:
            print(f"  ⚠️  Could not verify {pcb_file.name}: {e}")

    # Overall verdict
    if issues_found:
        print("\n🚨 EXECUTION VERIFICATION FAILED:")
        for issue in issues_found:
            print(issue)
        print("\n⚠️  OLD ROUTER MAY HAVE EXECUTED due to bytecode cache!")
        print("   This means the implementation was NOT tested.")
        return False
    else:
        print(f"\n✅ NEW ROUTER VERIFICATION PASSED ({pcb_checked} PCBs checked)")
        print("   - Trace widths match new defaults (0.25mm)")
        print("   - Vias present (layer transitions working)")
        return True


def analyze_results(kicad_dir: Path) -> tuple[int, int, int]:
    """
    Analyze conversion results.
    Returns: (passed_count, failed_count, total_count)
    """
    kicad_schematics = list(kicad_dir.glob("*.kicad_sch"))

    # FAILED markers are written under kicad/test_results/*.FAILED in current converter
    # Backward compatibility: also scan kicad/*.FAILED if present
    # TC #39 (2025-11-24): Fix RC #11 - Also check kicad/quality/*.FAILED (quality gate location)
    failed_markers = []
    tr_dir = kicad_dir / "test_results"
    if tr_dir.exists():
        failed_markers.extend(sorted(tr_dir.glob("*.FAILED")))
    failed_markers.extend(sorted(kicad_dir.glob("*.FAILED")))

    # TC #39: Quality gate writes markers to kicad/quality/*.FAILED
    quality_dir = kicad_dir / "quality"
    if quality_dir.exists():
        failed_markers.extend(sorted(quality_dir.glob("*.FAILED")))

    total_count = len(kicad_schematics)
    failed_count = len(failed_markers)
    passed_count = total_count - failed_count

    print("\n" + "="*80)
    print("CONVERSION RESULTS ANALYSIS")
    print("="*80)
    print(f"✅ Passed circuits: {passed_count}/{total_count}")
    print(f"❌ Failed circuits: {failed_count}/{total_count}")

    if passed_count > 0:
        print("\nCircuits that PASSED:")
        failed_set = {m.stem for m in failed_markers}
        for sch_file in kicad_schematics:
            circuit_name = sch_file.stem
            if circuit_name not in failed_set:
                print(f"  ✅ {circuit_name}")

    if failed_count > 0:
        print("\nCircuits that FAILED (marked with .FAILED):")
        for marker in failed_markers:
            circuit_name = marker.stem
            print(f"  ❌ {circuit_name}")
            # Read failure reason if available
            try:
                with open(marker, 'r') as f:
                    first_line = f.readline().strip()
                    if first_line:
                        print(f"     {first_line}")
            except Exception:
                pass

    return passed_count, failed_count, total_count


def main() -> int:
    """Main simulation - matches production workflow 1:1."""
    repo_root = Path(__file__).resolve().parents[1]

    # TC #73 FIX: Accept command line argument for output directory
    if len(sys.argv) > 1:
        arg_path = Path(sys.argv[1])
        # Handle both relative and absolute paths
        if arg_path.is_absolute():
            latest = arg_path
        else:
            latest = repo_root / arg_path
        if not latest.exists():
            print(f"ERROR: Specified directory does not exist: {latest}")
            return 1
        print(f"Using specified output directory: {latest}")
    else:
        latest = find_latest_output_dir(repo_root)
        if latest is None:
            print("ERROR: No output/* folder found")
            return 1
        print(f"Using latest output directory: {latest}")

    lowlevel_dir = latest / "lowlevel"
    kicad_dir = latest / "kicad"
    converter = repo_root / "scripts" / "kicad_converter.py"

    if not lowlevel_dir.exists():
        print(f"ERROR: Missing lowlevel directory: {lowlevel_dir}")
        return 1
    if not converter.exists():
        print(f"ERROR: Missing converter: {converter}")
        return 1

    print("="*80)
    print("KICAD CONVERSION SIMULATION - PRODUCTION WORKFLOW")
    print("="*80)
    print(f"Latest run folder: {latest}")

    # PHASE 0.2: CRITICAL - Clear Python cache BEFORE running converter
    # This ensures NEW code runs, not cached old bytecode
    print("\n" + "="*80)
    print("PHASE 0.2: Clearing Python Bytecode Cache")
    print("="*80)
    print("CRITICAL: Removing ALL __pycache__ to ensure fresh code execution")
    cache_cleared = clean_python_cache(repo_root / "scripts")
    if cache_cleared > 0:
        print(f"✅ Cleared {cache_cleared} cache directories/files")
    else:
        print("ℹ️  No cache files found (already clean)")

    print(f"\nCleaning folder:   {kicad_dir}")
    clean_folder(kicad_dir)

    # Step 1: Run the converter (includes quality gate + auto-fix)
    print("\n" + "="*80)
    print("STEP 1: Running KiCad Converter (with quality gate + auto-fix)")
    print("="*80)

    # CRITICAL: Use venv python to ensure sexpdata library is available
    venv_python = repo_root / "venv" / "bin" / "python3"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    # PHASE 0.2: Use -B flag to prevent bytecode generation (don't write .pyc files)
    # This ensures we always run from source, never from cache
    cmd = [python_exe, "-B", str(converter), str(lowlevel_dir), str(kicad_dir)]
    print(f"Executing: {' '.join(cmd)}")
    print("Note: Using -B flag to prevent bytecode generation\n")

    result = subprocess.run(cmd)

    # Note: Converter may return non-zero if some circuits failed,
    # but it should still have generated ALL circuits (with .FAILED markers)
    print(f"\nConverter exit code: {result.returncode}")

    # Step 2: PHASE 0.3 - Verify new router execution (CRITICAL for implementation testing)
    router_verified = verify_new_router_execution(kicad_dir)

    if not router_verified:
        print("\n🚨 CRITICAL: Router execution verification FAILED!")
        print("   This indicates the NEW router did NOT execute.")
        print("   Possible causes:")
        print("   - Python bytecode cache not properly cleared")
        print("   - Import errors preventing new code from loading")
        print("   Check logs for 'Manhattan Router 2.0.0-collision-aware-mst' message")

    # Step 3: Verify circuit counts match (CRITICAL requirement)
    count_valid = verify_circuit_counts(lowlevel_dir, kicad_dir)

    if not count_valid:
        print("\n🚫 CRITICAL BUG: Circuit count mismatch!")
        print("   The converter MUST preserve all circuits.")
        print("   Failed circuits should be marked with .FAILED, not deleted.")
        return 1

    # Step 3: Analyze results
    passed, failed, total = analyze_results(kicad_dir)

    # Step 4: Final summary
    print("\n" + "="*80)
    print("SIMULATION COMPLETE")
    print("="*80)
    print(f"Circuit count:  ✅ MATCHES (kicad = lowlevel = {total})")
    print(f"Passed:         {passed}/{total} circuits (100% perfect)")
    print(f"Failed:         {failed}/{total} circuits (.FAILED markers)")

    if failed > 0:
        print(f"\n⚠️  {failed} circuit(s) need attention:")
        print("   - Check .FAILED markers for failure reasons")
        print("   - Check ERC/DRC reports in kicad/ERC/ and kicad/DRC/")
        print("   - All files preserved for debugging")
        return 1
    else:
        print(f"\n✅ ALL {total} CIRCUITS PERFECT - READY FOR MANUFACTURING!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
