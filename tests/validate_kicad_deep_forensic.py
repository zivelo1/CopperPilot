#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Deep KiCad Validation (Forensic Level)

This script performs an end-to-end, production-readiness validation for the
latest output run's KiCad artifacts. It combines light preflight checks with
the existing forensic validator, ensuring ERC/DRC coverage and structural
consistency before declaring the design fabrication-ready.

What it does:
- Locates the most recent output/[UNIQUE] folder
- Runs preflight sanity checks on .kicad_pro/.kicad_sch/.kicad_pcb files
- Invokes tests/validate_kicad_forensic.py (ERC/DRC + format checks)
- Exits non-zero if any gate fails

This script intentionally does not generate files; use the corresponding
simulation script (tests/simulate_kicad_conversion.py) first.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
import subprocess


def _find_latest_output_dir(root: Path) -> Path | None:
    output_root = root / "output"
    if not output_root.exists():
        return None
    dirs = [p for p in output_root.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


def _count_vias_in_pcb(pcb_text: str) -> int:
    """
    Count the number of vias in a PCB file.

    TC #54 FIX D.2: Enhanced validation for via injection.
    """
    return pcb_text.count("(via (at")


def _validate_symbol_references(sch_text: str) -> dict:
    """
    TC #62 FIX 2.1 (2025-11-30): Validate symbol reference matching.

    CRITICAL: Symbol names in lib_symbols MUST match lib_id references exactly.
    If they don't match, KiCad displays "??" instead of component symbols.

    This function catches the root cause of the "??" display issue:
    - lib_symbols might have: (symbol "R"
    - lib_id might reference: "Device:R"
    - Mismatch = KiCad can't find symbol = "??"

    Args:
        sch_text: Schematic file content

    Returns:
        dict with:
            - lib_symbols: List of symbols defined in lib_symbols section
            - lib_ids: List of lib_id references in component instances
            - matched: Number of lib_ids that have matching lib_symbols
            - unmatched: List of lib_ids that have NO matching lib_symbol
            - match_percent: Percentage of lib_ids with matching symbols
            - status: 'PASS' if 100% match, 'FAIL' otherwise
    """
    result = {
        'lib_symbols': [],
        'lib_ids': [],
        'matched': 0,
        'unmatched': [],
        'match_percent': 0.0,
        'status': 'UNKNOWN',
    }

    # RC5 FIX (TC #62): Fixed lib_symbols extraction
    # OLD BUG: The regex r'\(lib_symbols\s*(.*?)\n\s*\)' failed because:
    #   - lib_symbols section has NESTED parentheses (thousands of lines)
    #   - The non-greedy .*? stops at first ) which is inside the section
    #   - Result: 0 symbols found, 0% match
    #
    # NEW APPROACH: Extract symbols directly from lib_symbols section
    # - Find the start of (lib_symbols and end of that section
    # - Use balanced parenthesis counting to find section boundaries
    # - Then extract symbol names from that section

    # Find lib_symbols section using parenthesis counting
    lib_start = sch_text.find('(lib_symbols')
    if lib_start != -1:
        # Find the matching closing parenthesis
        depth = 0
        lib_end = lib_start
        for i, char in enumerate(sch_text[lib_start:]):
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    lib_end = lib_start + i + 1
                    break

        lib_section = sch_text[lib_start:lib_end]

        # Top-level symbols start with tab + (symbol "NAME"
        # They don't have _0_1, _1_1, etc. suffix (those are units)
        top_symbols = re.findall(r'^\t\(symbol\s+"([^"]+)"', lib_section, re.MULTILINE)
        # Filter out unit definitions (e.g., "Device:R_0_1", "Device:R_1_1")
        result['lib_symbols'] = [s for s in top_symbols if not re.search(r'_\d+_\d+$', s)]

    # Extract lib_id references from component instances
    # Pattern: (lib_id "LibraryName:SymbolName")
    lib_ids = re.findall(r'\(lib_id\s+"([^"]+)"\)', sch_text)
    result['lib_ids'] = list(set(lib_ids))  # Unique lib_ids only

    # Check for matches
    lib_symbol_set = set(result['lib_symbols'])
    for lib_id in result['lib_ids']:
        if lib_id in lib_symbol_set:
            result['matched'] += 1
        else:
            result['unmatched'].append(lib_id)

    # Calculate percentage
    total_ids = len(result['lib_ids'])
    if total_ids > 0:
        result['match_percent'] = 100.0 * result['matched'] / total_ids

    # Determine status
    if total_ids == 0:
        result['status'] = 'N/A'
    elif result['match_percent'] == 100.0:
        result['status'] = 'PASS'
    else:
        result['status'] = 'FAIL'

    return result


def _detect_wire_topology(sch_text: str) -> dict:
    """
    TC #57 FIX 3.2: Detect wire topology type in schematic.

    Analyzes wire patterns to determine if schematic uses:
    - stub topology: Short isolated wires with labels (problematic)
    - star topology: Central junction with wires radiating to pins (TC #57 fix)
    - chain topology: Point-to-point wires connecting pins in sequence

    Returns dict with:
        - type: 'stub', 'star', 'chain', or 'mixed'
        - wire_count: Total number of wires
        - junction_count: Number of junctions (star indicators)
        - avg_wire_length: Average wire length in mm
        - label_count: Number of global labels
    """
    result = {
        'type': 'unknown',
        'wire_count': 0,
        'junction_count': 0,
        'avg_wire_length': 0.0,
        'label_count': 0,
    }

    # Count wires
    wire_matches = re.findall(r'\(wire\s+\(pts', sch_text)
    result['wire_count'] = len(wire_matches)

    # Count junctions (star topology indicator)
    junction_matches = re.findall(r'\(junction\s+\(at', sch_text)
    result['junction_count'] = len(junction_matches)

    # Count global labels
    label_matches = re.findall(r'\(global_label\s+"', sch_text)
    result['label_count'] = len(label_matches)

    # Calculate average wire length from wire coordinates
    wire_coords = re.findall(
        r'\(wire\s+\(pts\s+\(xy\s+([\d.-]+)\s+([\d.-]+)\)\s+\(xy\s+([\d.-]+)\s+([\d.-]+)\)\)',
        sch_text
    )
    if wire_coords:
        total_length = 0.0
        for x1, y1, x2, y2 in wire_coords:
            length = ((float(x2) - float(x1))**2 + (float(y2) - float(y1))**2)**0.5
            total_length += length
        result['avg_wire_length'] = total_length / len(wire_coords)

    # Determine topology type based on patterns
    if result['junction_count'] > 0 and result['junction_count'] >= result['label_count'] // 2:
        result['type'] = 'star'
    elif result['avg_wire_length'] < 5.0 and result['label_count'] > result['wire_count'] * 0.5:
        result['type'] = 'stub'
    elif result['avg_wire_length'] > 10.0:
        result['type'] = 'chain'
    else:
        result['type'] = 'mixed'

    return result


def _analyze_layer_distribution(pcb_text: str) -> dict:
    """
    TC #57 FIX 3.2: Analyze layer distribution of tracks.

    Returns dict with:
        - total_tracks: Total track segment count
        - fcu_tracks: Tracks on F.Cu (top copper)
        - bcu_tracks: Tracks on B.Cu (bottom copper)
        - fcu_percent: Percentage on F.Cu
        - bcu_percent: Percentage on B.Cu
    """
    result = {
        'total_tracks': 0,
        'fcu_tracks': 0,
        'bcu_tracks': 0,
        'fcu_percent': 0.0,
        'bcu_percent': 0.0,
    }

    # Count tracks by layer
    all_segments = re.findall(r'\(segment\s+.*?\(layer\s+"([^"]+)"\)', pcb_text)
    result['total_tracks'] = len(all_segments)

    for layer in all_segments:
        if layer == 'F.Cu':
            result['fcu_tracks'] += 1
        elif layer == 'B.Cu':
            result['bcu_tracks'] += 1

    # Calculate percentages
    if result['total_tracks'] > 0:
        result['fcu_percent'] = 100.0 * result['fcu_tracks'] / result['total_tracks']
        result['bcu_percent'] = 100.0 * result['bcu_tracks'] / result['total_tracks']

    return result


def _check_grid_alignment(sch_text: str, grid_mm: float = 1.27) -> dict:
    """
    TC #57 FIX 3.2: Check if coordinates are aligned to KiCad grid.

    KiCad standard grid is 1.27mm (50 mil). Components and wires
    should be snapped to grid for clean schematics.

    Args:
        sch_text: Schematic content
        grid_mm: Expected grid spacing (default 1.27mm)

    Returns dict with:
        - total_coordinates: Total coordinates checked
        - aligned: Coordinates aligned to grid
        - misaligned: Coordinates not on grid
        - alignment_percent: Percentage aligned
        - misaligned_examples: Up to 5 examples of misaligned coordinates
    """
    result = {
        'total_coordinates': 0,
        'aligned': 0,
        'misaligned': 0,
        'alignment_percent': 0.0,
        'misaligned_examples': [],
    }

    # Extract all (at X Y) coordinates
    coords = re.findall(r'\(at\s+([\d.-]+)\s+([\d.-]+)', sch_text)

    for x_str, y_str in coords:
        x, y = float(x_str), float(y_str)
        result['total_coordinates'] += 1

        # Check if both X and Y are on grid
        x_on_grid = abs(x % grid_mm) < 0.01 or abs(x % grid_mm - grid_mm) < 0.01
        y_on_grid = abs(y % grid_mm) < 0.01 or abs(y % grid_mm - grid_mm) < 0.01

        if x_on_grid and y_on_grid:
            result['aligned'] += 1
        else:
            result['misaligned'] += 1
            if len(result['misaligned_examples']) < 5:
                result['misaligned_examples'].append(f"({x:.3f}, {y:.3f})")

    # Calculate percentage
    if result['total_coordinates'] > 0:
        result['alignment_percent'] = 100.0 * result['aligned'] / result['total_coordinates']

    return result


def _analyze_layer_mismatches(drc_report_path: Path) -> dict:
    """
    Analyze DRC report for layer mismatch patterns.

    TC #54 FIX D.2: Count how many unconnected_items are layer transitions.

    Returns dict with:
        - total_unconnected: Total unconnected_items errors
        - layer_mismatches: Number that are layer transitions (F.Cu vs B.Cu at same coords)
        - same_layer: Number on same layer (genuine routing failures)
    """
    result = {
        'total_unconnected': 0,
        'layer_mismatches': 0,
        'same_layer': 0,
    }

    if not drc_report_path.exists():
        return result

    content = drc_report_path.read_text()

    # Find all unconnected_items blocks
    # Pattern: coordinates followed by layer info
    blocks = re.findall(
        r'\[unconnected_items\].*?(?=\[\w|$)',
        content,
        re.DOTALL
    )

    for block in blocks:
        result['total_unconnected'] += 1

        # Check if both F.Cu and B.Cu are mentioned in the same block
        has_fcu = 'on F.Cu' in block or 'F.Cu' in block
        has_bcu = 'on B.Cu' in block or 'B.Cu' in block

        if has_fcu and has_bcu:
            # Layer transition - should be fixed by via injection
            result['layer_mismatches'] += 1
        else:
            # Same layer - genuine routing failure
            result['same_layer'] += 1

    return result


def _enhanced_pcb_validation(kicad_dir: Path, base: str) -> tuple[list[str], dict]:
    """
    TC #54 FIX D.2: Enhanced validation for PCB files.
    TC #57 FIX 3.2: Added comprehensive metrics.

    Checks:
    1. Via count vs layer mismatch count (after route-to-pad repair)
    2. Track endpoint connectivity analysis
    3. Layer transition coverage
    4. Layer distribution analysis (TC #57)

    Returns:
        Tuple of (warnings_list, metrics_dict)
    """
    warnings: list[str] = []
    metrics: dict = {}

    pcb_path = kicad_dir / f"{base}.kicad_pcb"
    sch_path = kicad_dir / f"{base}.kicad_sch"
    drc_path = kicad_dir / "DRC" / f"{base}.drc.rpt"

    if not pcb_path.exists():
        return warnings, metrics

    pcb_text = pcb_path.read_text(errors='ignore')
    via_count = _count_vias_in_pcb(pcb_text)
    metrics['via_count'] = via_count

    # TC #57 FIX 3.2: Layer distribution analysis
    layer_dist = _analyze_layer_distribution(pcb_text)
    metrics['layer_distribution'] = layer_dist

    # Analyze DRC for layer mismatches
    drc_analysis = _analyze_layer_mismatches(drc_path)
    metrics['drc_analysis'] = drc_analysis

    # TC #57 FIX 3.2: Wire topology analysis (from schematic)
    if sch_path.exists():
        sch_text = sch_path.read_text(errors='ignore')
        topology = _detect_wire_topology(sch_text)
        metrics['wire_topology'] = topology

        # TC #57 FIX 3.2: Grid alignment check
        grid_check = _check_grid_alignment(sch_text)
        metrics['grid_alignment'] = grid_check

        # Warn if using problematic stub topology
        if topology['type'] == 'stub':
            warnings.append(
                f"{base}: Using STUB wire topology ({topology['wire_count']} wires, "
                f"avg {topology['avg_wire_length']:.1f}mm) - may cause ERC dangling wire errors"
            )

    # Report findings (informational, not blocking)
    if drc_analysis['total_unconnected'] > 0:
        if drc_analysis['layer_mismatches'] > 0 and via_count < drc_analysis['layer_mismatches']:
            warnings.append(
                f"{base}: Via count ({via_count}) < layer mismatches ({drc_analysis['layer_mismatches']}) - "
                "route_pad_connector may not have run or failed"
            )

    return warnings, metrics


def _preflight_kicad(kicad_dir: Path) -> list[str]:
    """Run lightweight structural checks not guaranteed by ERC/DRC.

    Returns a list of error strings; empty list means pass.

    TC #54 FIX D.2: Enhanced with via/layer mismatch validation.
    TC #57 FIX 3.2: Added comprehensive metrics reporting.
    """
    errors: list[str] = []

    pro = sorted(kicad_dir.glob("*.kicad_pro"))
    sch = sorted(kicad_dir.glob("*.kicad_sch"))
    pcb = sorted(kicad_dir.glob("*.kicad_pcb"))

    if not pro or not sch or not pcb:
        errors.append("Missing KiCad outputs (pro/sch/pcb)")
        return errors

    # TC #53: Check that symbols folder exists and is NOT empty
    symbols_dir = kicad_dir / "symbols"
    if not symbols_dir.exists():
        errors.append("Missing symbols folder - KiCad projects won't find libraries")
    else:
        sym_files = list(symbols_dir.glob("*.kicad_sym"))
        if not sym_files:
            errors.append(f"Symbols folder is EMPTY - KiCad projects won't find libraries (expected 4+ .kicad_sym files)")
        elif len(sym_files) < 4:
            errors.append(f"Symbols folder incomplete - only {len(sym_files)} .kicad_sym files (expected 4+)")

    if not (len(pro) == len(sch) == len(pcb)):
        errors.append(f"File count mismatch: pro={len(pro)} sch={len(sch)} pcb={len(pcb)}")

    # For each project base, verify basic markers in files
    bases = {p.stem for p in pro} & {s.stem for s in sch} & {b.stem for b in pcb}
    enhanced_warnings = []
    all_metrics: dict[str, dict] = {}

    for base in sorted(bases):
        sch_text = (kicad_dir / f"{base}.kicad_sch").read_text(errors='ignore')
        pcb_text = (kicad_dir / f"{base}.kicad_pcb").read_text(errors='ignore')

        # Required S-expression headers
        if not sch_text.strip().startswith("(kicad_sch"):
            errors.append(f"{base}.kicad_sch: Invalid header")
        if not pcb_text.strip().startswith("(kicad_pcb"):
            errors.append(f"{base}.kicad_pcb: Invalid header")

        # Generator metadata should exist
        if 'generator "' not in sch_text or 'generator_version' not in sch_text:
            errors.append(f"{base}.kicad_sch: Missing generator metadata")
        if 'generator "' not in pcb_text or 'generator_version' not in pcb_text:
            errors.append(f"{base}.kicad_pcb: Missing generator metadata")

        # UUIDs should be present
        if '(uuid "' not in sch_text:
            errors.append(f"{base}.kicad_sch: Missing UUIDs")
        if '(uuid "' not in pcb_text:
            errors.append(f"{base}.kicad_pcb: Missing UUIDs")

        # Sanity: components > 0 implies nets/wires > 0
        comp_count = sch_text.count('(symbol (lib_id')
        net_count = len(re.findall(r'\(net\s+\d+\s+"', pcb_text))
        wire_count = sch_text.count('(wire')
        if comp_count > 1 and (net_count == 0 or wire_count == 0):
            errors.append(f"{base}: Components present but nets/wires appear missing (comp={comp_count}, nets={net_count}, wires={wire_count})")

        # TC #62 FIX 2.1: Validate symbol reference matching
        # CRITICAL: This catches the "??" display issue BEFORE ERC/DRC
        symbol_validation = _validate_symbol_references(sch_text)
        if symbol_validation['status'] == 'FAIL':
            errors.append(
                f"{base}.kicad_sch: Symbol reference mismatch - "
                f"{len(symbol_validation['unmatched'])}/{len(symbol_validation['lib_ids'])} lib_ids have no matching lib_symbol. "
                f"Unmatched: {symbol_validation['unmatched'][:5]}..."
            )

        # TC #54 FIX D.2 + TC #57 FIX 3.2: Enhanced validation with metrics
        warnings, metrics = _enhanced_pcb_validation(kicad_dir, base)
        enhanced_warnings.extend(warnings)

        # TC #62: Add symbol validation to metrics
        metrics['symbol_validation'] = symbol_validation
        all_metrics[base] = metrics

    # TC #57 FIX 3.2: Display comprehensive metrics report
    print("\n" + "=" * 60)
    print("TC #57 ENHANCED VALIDATION METRICS")
    print("=" * 60)

    for base, metrics in all_metrics.items():
        print(f"\n📊 {base}:")

        # Via count
        if 'via_count' in metrics:
            print(f"   Vias: {metrics['via_count']}")

        # Wire topology
        if 'wire_topology' in metrics:
            topo = metrics['wire_topology']
            topo_emoji = {'star': '⭐', 'stub': '⚠️', 'chain': '🔗', 'mixed': '🔀'}.get(topo['type'], '❓')
            print(f"   Wire Topology: {topo_emoji} {topo['type'].upper()}")
            print(f"      Wires: {topo['wire_count']}, Junctions: {topo['junction_count']}, Labels: {topo['label_count']}")
            if topo['avg_wire_length'] > 0:
                print(f"      Avg Wire Length: {topo['avg_wire_length']:.1f}mm")

        # Layer distribution
        if 'layer_distribution' in metrics:
            ld = metrics['layer_distribution']
            print(f"   Layer Distribution: {ld['total_tracks']} tracks")
            print(f"      F.Cu (top): {ld['fcu_tracks']} ({ld['fcu_percent']:.1f}%)")
            print(f"      B.Cu (bottom): {ld['bcu_tracks']} ({ld['bcu_percent']:.1f}%)")

        # Grid alignment
        if 'grid_alignment' in metrics:
            ga = metrics['grid_alignment']
            alignment_emoji = '✓' if ga['alignment_percent'] > 95 else '⚠️' if ga['alignment_percent'] > 80 else '❌'
            print(f"   Grid Alignment: {alignment_emoji} {ga['alignment_percent']:.1f}% ({ga['aligned']}/{ga['total_coordinates']} on 1.27mm grid)")
            if ga['misaligned_examples']:
                print(f"      Off-grid examples: {', '.join(ga['misaligned_examples'][:3])}")

        # TC #62 FIX 2.1: Symbol reference validation
        if 'symbol_validation' in metrics:
            sv = metrics['symbol_validation']
            symbol_emoji = '✅' if sv['status'] == 'PASS' else '❌' if sv['status'] == 'FAIL' else '❓'
            print(f"   Symbol References: {symbol_emoji} {sv['status']} ({sv['match_percent']:.1f}% matched)")
            print(f"      lib_symbols defined: {len(sv['lib_symbols'])}")
            print(f"      lib_ids referenced: {len(sv['lib_ids'])}")
            if sv['unmatched']:
                unmatched_preview = sv['unmatched'][:3]
                print(f"      Unmatched lib_ids: {unmatched_preview}{'...' if len(sv['unmatched']) > 3 else ''}")

    print("\n" + "=" * 60)

    # Report enhanced validation warnings (informational)
    if enhanced_warnings:
        print("\n⚠️  Enhanced Validation Warnings (informational):")
        for warn in enhanced_warnings:
            print(f"    - {warn}")

    return errors


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    
    # Phase G.3 (Forensic Fix 20260211): Support explicit target path
    if len(sys.argv) > 1:
        latest = Path(sys.argv[1])
        if not latest.is_absolute():
            latest = repo / latest
    else:
        latest = _find_latest_output_dir(repo)
        
    if not latest or not latest.exists():
        print(f"ERROR: Target directory not found: {latest}")
        return 1

    kicad_dir = latest / "kicad"
    if not kicad_dir.exists():
        print(f"ERROR: KiCad folder not found: {kicad_dir}")
        return 1

    print("=" * 80)
    print("KICAD DEEP FORENSIC VALIDATION")
    print("=" * 80)
    print(f"Run folder: {latest}")
    print(f"Target dir: {kicad_dir}\n")

    # Preflight
    pre_errors = _preflight_kicad(kicad_dir)
    if pre_errors:
        print("Preflight checks failed:")
        for i, err in enumerate(pre_errors, 1):
            print(f"  {i}. {err}")
        return 1
    else:
        print("Preflight: PASS")

    # Forensic validator (includes ERC/DRC gate via internal logic)
    validator = repo / "tests" / "validate_kicad_forensic.py"
    cmd = [sys.executable, str(validator), str(kicad_dir)]
    print(f"\nExecuting: {' '.join(cmd)}\n")
    res = subprocess.run(cmd)
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())

