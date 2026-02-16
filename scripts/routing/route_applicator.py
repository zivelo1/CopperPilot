# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Route Applicator - Apply SES Routing to KiCad PCB
=================================================

Takes routing data from Freerouting (parsed SES) and applies it to .kicad_pcb files.
Generates KiCad S-Expression format for traces (segments) and vias.

TC #51 FIX (2025-11-25): Intermittent Routing Failure Fix
=========================================================
ROOT CAUSES FIXED:
1. Net mapping mismatch - unknown nets defaulted to 0 (may be invalid)
2. Regex-based file insertion failing on edge cases
3. No retry mechanism when apply fails
4. No detailed logging for debugging failures

GENERIC Design: Works for ANY circuit routed by Freerouting.

Author: Claude Code
Date: 2025-11-16
Version: 1.1.0 + TC #76 Via Enhancement (2025-12-09)

TC #76 FIX (2025-12-09): Via Dataclass Enhancement Support
==========================================================
- Added _generate_via_enhanced() method to use explicit drill_mm and layers
- Updated all via generation loops to use getattr() for backward compatibility
- Supports new Via dataclass fields from ses_parser.py
"""

from pathlib import Path
from typing import List, Dict, Optional, Tuple
import uuid
import re
import logging
from .ses_parser import RoutingData, Wire, Via

# TC #52 FIX 1.2 (2025-11-26): Import route-pad connector for final segment repair
from .route_pad_connector import RoutePadConnector

# TC #51: Add proper logging
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TC #71 PHASE 0: FILE INTEGRITY - S-EXPRESSION BALANCE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════
# ROOT CAUSE: PCB files were being corrupted with unbalanced parentheses.
# This BLOCKED all downstream fixes because SafePCBModifier couldn't parse them.
#
# SOLUTION: Add mandatory balance validation before AND after every file write.
# If imbalance detected, attempt repair OR abort to prevent corruption propagation.
# ═══════════════════════════════════════════════════════════════════════════════

def validate_sexp_balance(content: str, context: str = "") -> Tuple[bool, int, str]:
    """
    TC #71 Phase 0.1: Validate S-expression parenthesis balance.

    CRITICAL: This MUST be called before every PCB file write to prevent corruption.

    Args:
        content: S-expression content to validate
        context: Description for logging (e.g., "after trace insertion")

    Returns:
        Tuple of (is_valid, delta, message)
        - is_valid: True if balanced, False if corrupted
        - delta: open_count - close_count (positive = missing closes, negative = extra closes)
        - message: Human-readable status message
    """
    open_count = content.count('(')
    close_count = content.count(')')
    delta = open_count - close_count

    if delta == 0:
        msg = f"✓ S-expression balance OK {context}: {open_count} parens"
        return (True, 0, msg)
    elif delta > 0:
        msg = f"✗ CORRUPTION {context}: {delta} missing close parentheses (open={open_count}, close={close_count})"
        return (False, delta, msg)
    else:
        msg = f"✗ CORRUPTION {context}: {abs(delta)} extra close parentheses (open={open_count}, close={close_count})"
        return (False, delta, msg)


def repair_sexp_balance(content: str) -> Tuple[str, bool, str]:
    """
    TC #71 Phase 0.3: Attempt to repair unbalanced S-expressions.
    TC #73 ENHANCEMENT: Full repair loop until balanced.

    REPAIR STRATEGY:
    1. If too many close parens: Find and remove orphan ')' from end of file
    2. If too many open parens: Add missing ')' at end of file
    3. TC #73: Loop until FULLY balanced, not just one iteration

    This is a CONSERVATIVE repair - it only fixes common corruption patterns.
    Complex corruption may require manual intervention.

    Args:
        content: Potentially corrupted S-expression content

    Returns:
        Tuple of (repaired_content, was_repaired, message)
    """
    is_valid, delta, _ = validate_sexp_balance(content, "before repair")

    if is_valid:
        return (content, False, "No repair needed - already balanced")

    repaired = content
    total_removed = 0
    total_added = 0
    max_iterations = 20  # Safety limit to prevent infinite loops

    # TC #73: Loop until fully balanced
    for iteration in range(max_iterations):
        is_valid, delta, _ = validate_sexp_balance(repaired, f"repair iteration {iteration}")

        if is_valid:
            break  # Successfully balanced!

        if delta < 0:
            # Too many close parens - remove from end
            # TC #73: More aggressive search for orphan close parens
            lines = repaired.rstrip().split('\n')
            removed_this_iter = 0
            parens_to_remove = abs(delta)

            # Strategy 1: Remove standalone ')' lines from end
            while removed_this_iter < parens_to_remove and lines:
                last_line = lines[-1].rstrip()
                if last_line == ')':
                    lines.pop()
                    removed_this_iter += 1
                elif last_line.endswith(')') and last_line.strip() == ')':
                    # Line is just whitespace + )
                    lines.pop()
                    removed_this_iter += 1
                elif last_line.endswith('))'):
                    # Remove one ) from double-close
                    lines[-1] = last_line[:-1]
                    removed_this_iter += 1
                elif last_line.endswith(')'):
                    # Remove one ) from end of line
                    lines[-1] = last_line[:-1]
                    removed_this_iter += 1
                else:
                    # Can't remove from this line, try searching backwards
                    break

            # Strategy 2: TC #73 - Search backwards through lines for orphan close parens
            if removed_this_iter < parens_to_remove and len(lines) > 1:
                for line_idx in range(len(lines) - 1, -1, -1):
                    if removed_this_iter >= parens_to_remove:
                        break
                    line = lines[line_idx]
                    # Count parens on this line
                    line_open = line.count('(')
                    line_close = line.count(')')
                    if line_close > line_open and line.rstrip().endswith(')'):
                        # This line has more closes than opens - safe to remove one
                        lines[line_idx] = line.rstrip()[:-1]
                        removed_this_iter += 1

            repaired = '\n'.join(lines)
            total_removed += removed_this_iter

            if removed_this_iter == 0:
                # Can't make progress - stop trying
                break

        elif delta > 0:
            # Too many open parens - add closes at end
            repaired = repaired.rstrip() + '\n' + (')' * delta)
            total_added += delta
            # After adding, we should be balanced, but verify

    # Final validation
    is_valid, final_delta, _ = validate_sexp_balance(repaired, "after full repair")

    if is_valid:
        if total_removed > 0 and total_added > 0:
            return (repaired, True, f"Repaired: removed {total_removed} and added {total_added} parentheses")
        elif total_removed > 0:
            return (repaired, True, f"Repaired: removed {total_removed} extra close parentheses")
        elif total_added > 0:
            return (repaired, True, f"Repaired: added {total_added} close parentheses")
        else:
            return (repaired, True, "Repaired: balanced through adjustments")
    else:
        # Partial repair
        if final_delta < 0:
            return (repaired, True, f"Partial repair: removed {total_removed} close parens, {abs(final_delta)} extra remain")
        else:
            return (repaired, True, f"Partial repair: added {total_added} close parens, {final_delta} missing remain")


def validate_kicad_structure(content: str) -> Tuple[bool, str]:
    """
    TC #75: Validate KiCad PCB file STRUCTURE (not just parenthesis balance).

    A valid KiCad PCB file must:
    1. Start with '(kicad_pcb' on the first non-empty line
    2. End with ')' on the last non-empty line (closing the root)
    3. Have balanced parentheses overall

    Returns:
        Tuple of (is_valid, message)
    """
    lines = content.strip().split('\n')
    if not lines:
        return False, "Empty content"

    # Check first line
    first_line = lines[0].strip()
    if not first_line.startswith('(kicad_pcb'):
        return False, f"Invalid header (expected '(kicad_pcb'): {first_line[:50]}"

    # Check last line - must be just ')' to close root
    last_line = lines[-1].strip()
    if last_line != ')':
        return False, f"File truncated - last line should be ')' but is: {last_line[:50]}"

    # Check overall balance
    total_open = content.count('(')
    total_close = content.count(')')
    if total_open != total_close:
        return False, f"Unbalanced parens: {total_open} open, {total_close} close"

    return True, "Structure OK"


def repair_kicad_structure(content: str) -> str:
    """
    TC #75: Attempt to repair KiCad PCB file structure.

    Repairs:
    1. Missing root close - add ')' at end
    2. Truncated last element - try to close it properly
    3. Overall balance issues - add/remove parens as needed

    Returns:
        Repaired content (best effort)
    """
    lines = content.strip().split('\n')
    if not lines:
        return content

    repaired_lines = lines.copy()

    # Check if last line is the root close
    last_line = repaired_lines[-1].strip()
    if last_line != ')':
        # Last line is NOT the root close - file is truncated
        logger.warning(f"TC #75 REPAIR: Last line is '{last_line[:50]}' - attempting repair")

        # Check if last line is incomplete (missing close parens)
        last_line_open = last_line.count('(')
        last_line_close = last_line.count(')')

        if last_line_open > last_line_close:
            # Last line has unclosed parens - close them
            missing = last_line_open - last_line_close
            repaired_lines[-1] = repaired_lines[-1] + (')' * missing)
            logger.info(f"TC #75 REPAIR: Closed {missing} parens on last line")

        # Now check overall balance
        content_str = '\n'.join(repaired_lines)
        total_open = content_str.count('(')
        total_close = content_str.count(')')

        if total_open > total_close:
            # Missing close parens - add them
            missing = total_open - total_close
            # Add the root close(s)
            repaired_lines.append(')' * missing)
            logger.info(f"TC #75 REPAIR: Added {missing} closing paren(s) at end")
        elif total_close > total_open:
            # Too many closes - this is harder, try removing from end
            excess = total_close - total_open
            logger.warning(f"TC #75 REPAIR: {excess} excess close parens - attempting removal")
            # Remove excess from the last line(s)
            while excess > 0 and repaired_lines:
                last = repaired_lines[-1]
                if last.strip() == ')':
                    repaired_lines.pop()
                    excess -= 1
                elif last.rstrip().endswith(')'):
                    repaired_lines[-1] = last.rstrip()[:-1]
                    excess -= 1
                else:
                    break

    # Ensure we have a proper root close
    content_str = '\n'.join(repaired_lines)
    last_stripped = repaired_lines[-1].strip() if repaired_lines else ''
    if last_stripped != ')':
        # Still no root close - add one
        repaired_lines.append(')')
        logger.info("TC #75 REPAIR: Added root close ')' at end")

    return '\n'.join(repaired_lines)


class RouteApplicator:
    """
    Apply routing data from Freerouting to KiCad PCB files.

    Takes parsed SES data (wires, vias) and generates KiCad S-Expression
    format segments and via definitions to insert into .kicad_pcb.

    GENERIC: Works for ANY routing complexity.
    """

    def apply(
        self,
        pcb_file: Path,
        routing_data: RoutingData,
        net_mapping: Dict[str, int]
    ) -> bool:
        """
        Apply routing data to KiCad PCB file.

        TC #51 FIX (2025-11-25): ROBUST application with retry and validation
        ═══════════════════════════════════════════════════════════════════════
        ROOT CAUSES FIXED:
        1. Net mapping mismatch - now builds dynamic mapping from PCB if missing
        2. File insertion failing - now uses multiple insertion strategies
        3. No detailed diagnostics - now logs all net mismatches
        ═══════════════════════════════════════════════════════════════════════

        Args:
            pcb_file: Path to .kicad_pcb file to modify
            routing_data: Parsed routing data from SES file
            net_mapping: Map of net_name → net_index for KiCad format

        Returns:
            True if successful, False otherwise

        Strategy:
        1. Read existing .kicad_pcb content
        2. Remove old traces/vias (if any)
        3. Validate/augment net mapping
        4. Generate new KiCad S-Expression for traces/vias
        5. Insert using robust multi-strategy approach
        6. Write back to file and validate

        GENERIC: Works for ANY PCB file.
        """
        print(f"[RouteApplicator] DEBUG: Applying routing to {pcb_file.name}")
        print(f"[RouteApplicator] DEBUG: Input: {len(routing_data.wires)} wires, {len(routing_data.vias)} vias")
        print(f"[RouteApplicator] DEBUG: Net mapping has {len(net_mapping)} entries")
        logger.info(f"Applying routing: {len(routing_data.wires)} wires, {len(routing_data.vias)} vias")

        if not routing_data.wires and not routing_data.vias:
            print(f"[RouteApplicator] WARNING: No routing data to apply (0 wires, 0 vias)")
            return True  # Not an error, just nothing to do

        try:
            # Read existing PCB content
            if not pcb_file.exists():
                print(f"[RouteApplicator] ERROR: PCB file does not exist: {pcb_file}")
                logger.error(f"PCB file does not exist: {pcb_file}")
                return False

            content = pcb_file.read_text()
            print(f"[RouteApplicator] DEBUG: Read PCB file, size: {len(content)} bytes")

            # ═══════════════════════════════════════════════════════════════════
            # TC #71 Phase 0.1: MANDATORY INPUT VALIDATION
            # Validate input file is not already corrupted
            # ═══════════════════════════════════════════════════════════════════
            is_valid, delta, msg = validate_sexp_balance(content, "input file")
            logger.info(f"TC #71: {msg}")
            print(f"[RouteApplicator] TC #71: {msg}")

            if not is_valid:
                logger.warning(f"TC #71: Input PCB file has unbalanced parens - attempting repair")
                content, was_repaired, repair_msg = repair_sexp_balance(content)
                logger.info(f"TC #71: {repair_msg}")
                print(f"[RouteApplicator] TC #71: {repair_msg}")

                # Re-validate after repair
                is_valid, delta, msg = validate_sexp_balance(content, "after repair")
                if not is_valid:
                    logger.error(f"TC #71: Could not repair input file - aborting to prevent further corruption")
                    print(f"[RouteApplicator] ERROR: TC #71 - Input file corrupted beyond repair")
                    return False

            # TC #51: Validate and augment net mapping
            net_mapping, missing_nets = self._validate_net_mapping(
                routing_data, net_mapping, content
            )
            if missing_nets:
                print(f"[RouteApplicator] WARNING: {len(missing_nets)} nets not in mapping: {missing_nets[:5]}...")
                logger.warning(f"Missing nets in mapping: {missing_nets}")

            # Remove existing segments and vias (if any)
            content_before = content
            content = self._remove_existing_traces(content)
            removed_count = content_before.count('(segment') - content.count('(segment')
            print(f"[RouteApplicator] DEBUG: Removed {removed_count} existing segments")

            # Generate new routing S-Expressions with detailed logging
            routing_sexpr, generation_stats = self._generate_routing_sexpr_robust(
                routing_data, net_mapping
            )
            segments_generated = routing_sexpr.count('(segment')
            vias_generated = routing_sexpr.count('(via')
            print(f"[RouteApplicator] DEBUG: Generated {segments_generated} segments, {vias_generated} vias")
            print(f"[RouteApplicator] DEBUG: Generation stats: {generation_stats}")

            if segments_generated == 0 and vias_generated == 0:
                print(f"[RouteApplicator] WARNING: No S-Expressions generated from routing data!")
                print(f"[RouteApplicator] DEBUG: Sample wire data: {routing_data.wires[:2] if routing_data.wires else 'NONE'}")
                print(f"[RouteApplicator] DEBUG: Net mapping sample: {list(net_mapping.items())[:5]}")
                logger.warning("No S-Expressions generated from routing data")

            # TC #51: Use robust insertion with multiple strategies
            content = self._insert_routing_robust(content, routing_sexpr)

            # ═══════════════════════════════════════════════════════════════════
            # TC #71 Phase 0.2: MANDATORY OUTPUT VALIDATION BEFORE WRITE
            # NEVER write a corrupted file - this prevents cascade failures
            # ═══════════════════════════════════════════════════════════════════
            is_valid, delta, msg = validate_sexp_balance(content, "before write")
            logger.info(f"TC #71: {msg}")
            print(f"[RouteApplicator] TC #71: {msg}")

            if not is_valid:
                logger.error(f"TC #71 CRITICAL: Content corrupted during routing insertion!")
                logger.error(f"TC #71: Attempting repair before write...")
                print(f"[RouteApplicator] TC #71 WARNING: Attempting repair before write...")

                content, was_repaired, repair_msg = repair_sexp_balance(content)
                logger.info(f"TC #71: {repair_msg}")
                print(f"[RouteApplicator] TC #71: {repair_msg}")

                # Final validation
                is_valid, delta, msg = validate_sexp_balance(content, "after repair")
                if not is_valid:
                    logger.error(f"TC #71 CRITICAL: Cannot repair - ABORTING WRITE to prevent corruption")
                    logger.error(f"TC #71: Original file preserved, routing NOT applied")
                    print(f"[RouteApplicator] TC #71 ERROR: Write aborted - file would be corrupted")
                    return False

                logger.info(f"TC #71: Repair successful - proceeding with write")
                print(f"[RouteApplicator] TC #71: Repair successful")

            # ═══════════════════════════════════════════════════════════════════
            # TC #75: STRUCTURAL VALIDATION before write
            # ═══════════════════════════════════════════════════════════════════
            is_valid_structure, structure_msg = validate_kicad_structure(content)
            if not is_valid_structure:
                logger.error(f"TC #75: Structural issue before write: {structure_msg}")
                print(f"[RouteApplicator] TC #75 ERROR: {structure_msg}")
                # Attempt repair
                content = repair_kicad_structure(content)
                is_valid_structure, structure_msg = validate_kicad_structure(content)
                if not is_valid_structure:
                    logger.error(f"TC #75: Cannot repair structure - aborting write")
                    return False

            # Write back (only if valid)
            pcb_file.write_text(content)
            print(f"[RouteApplicator] DEBUG: Successfully wrote PCB file")

            # PRIORITY 5 FIX: Post-import validation
            actual_segments = content.count('(segment')
            actual_vias = content.count('(via')

            # Calculate expected counts
            # Each wire generates (path_points - 1) segments
            expected_segments = sum(len(wire.path_points) - 1 for wire in routing_data.wires if len(wire.path_points) > 1)
            expected_vias = len(routing_data.vias)

            print(f"[RouteApplicator] DEBUG: VALIDATION RESULTS:")
            print(f"[RouteApplicator] DEBUG:   Expected: {expected_segments} segments, {expected_vias} vias")
            print(f"[RouteApplicator] DEBUG:   Actual:   {actual_segments} segments, {actual_vias} vias")

            # Check for significant mismatches
            segment_mismatch = abs(actual_segments - expected_segments) / max(expected_segments, 1)
            via_mismatch = abs(actual_vias - expected_vias) / max(expected_vias, 1) if expected_vias > 0 else 0

            if segment_mismatch > 0.2:  # >20% mismatch
                print(f"[RouteApplicator] ERROR: Segment count mismatch > 20%!")
                print(f"[RouteApplicator] ERROR: This indicates SES import failure or net mapping issues")
                logger.error(f"Segment count mismatch: {segment_mismatch*100:.1f}%")
                return False

            if expected_segments > 0 and actual_segments == 0:
                print(f"[RouteApplicator] ERROR: Expected {expected_segments} segments but got ZERO!")
                print(f"[RouteApplicator] ERROR: This is a CRITICAL import failure")
                logger.error("CRITICAL: Expected segments but got zero")
                return False

            if segment_mismatch > 0.05:  # >5% mismatch (warning only)
                print(f"[RouteApplicator] WARNING: Segment count differs by {segment_mismatch*100:.1f}%")
                print(f"[RouteApplicator] WARNING: Some traces may not have been imported correctly")

            print(f"[RouteApplicator] SUCCESS: Routing validation passed")
            logger.info(f"Routing applied successfully: {actual_segments} segments, {actual_vias} vias")

            # ═══════════════════════════════════════════════════════════════════════
            # TC #52 FIX 1.2 (2025-11-26): ROUTE-TO-PAD CONNECTION REPAIR
            # ═══════════════════════════════════════════════════════════════════════
            # ROOT CAUSE: Freerouting routes terminate at intermediate points, NOT at
            # pad centers. This causes "unconnected_items" DRC errors even though
            # routes technically exist.
            #
            # SOLUTION: After applying Freerouting routes, run the RoutePadConnector
            # to add final segments from route endpoints to pad centers, plus vias
            # for layer transitions.
            #
            # GENERIC: Works for ANY circuit, ANY routing complexity.
            # ═══════════════════════════════════════════════════════════════════════
            print(f"\n[RouteApplicator] Running route-to-pad connection repair...")
            try:
                connector = RoutePadConnector()
                repair_success, repair_stats = connector.repair_connections(pcb_file)

                if repair_success:
                    print(f"[RouteApplicator] Repair stats:")
                    print(f"[RouteApplicator]   - Pads total: {repair_stats['pads_total']}")
                    print(f"[RouteApplicator]   - Already connected: {repair_stats['pads_connected']}")
                    print(f"[RouteApplicator]   - Fixed: {repair_stats['pads_fixed']}")
                    print(f"[RouteApplicator]   - Unfixable: {repair_stats['pads_unfixable']}")
                    print(f"[RouteApplicator]   - Segments added: {repair_stats['segments_added']}")
                    print(f"[RouteApplicator]   - Vias added: {repair_stats['vias_added']}")

                    if repair_stats['pads_unfixable'] > 0:
                        print(f"[RouteApplicator] WARNING: {repair_stats['pads_unfixable']} pads could not be connected")
                        print(f"[RouteApplicator] WARNING: These may cause DRC unconnected_items errors")
                else:
                    print(f"[RouteApplicator] WARNING: Route-to-pad repair encountered errors")
                    if repair_stats.get('errors'):
                        for error in repair_stats['errors']:
                            print(f"[RouteApplicator] ERROR: {error}")
            except Exception as e:
                print(f"[RouteApplicator] WARNING: Route-to-pad repair failed: {e}")
                logger.warning(f"Route-to-pad repair failed: {e}")
                # Don't fail the entire routing - the routes are applied, just may have DRC issues

            # ═══════════════════════════════════════════════════════════════════════
            # TC #75: FINAL STRUCTURAL VALIDATION after all modifications
            # This is the LAST line of defense against truncated files
            # ═══════════════════════════════════════════════════════════════════════
            final_content = pcb_file.read_text()
            is_valid_final, final_msg = validate_kicad_structure(final_content)
            if not is_valid_final:
                logger.error(f"TC #75 FINAL CHECK FAILED: {final_msg}")
                print(f"[RouteApplicator] TC #75 CRITICAL: Final file validation failed: {final_msg}")
                # Attempt repair
                repaired_content = repair_kicad_structure(final_content)
                is_valid_repaired, repaired_msg = validate_kicad_structure(repaired_content)
                if is_valid_repaired:
                    pcb_file.write_text(repaired_content)
                    logger.info(f"TC #75: Final file repaired and saved")
                    print(f"[RouteApplicator] TC #75: File repaired successfully")
                else:
                    logger.error(f"TC #75: Could not repair final file: {repaired_msg}")
                    print(f"[RouteApplicator] TC #75 ERROR: File may be corrupted: {repaired_msg}")
            else:
                logger.info(f"TC #75: Final file validation PASSED")
                print(f"[RouteApplicator] TC #75: Final structural validation PASSED")

            return True

        except Exception as e:
            print(f"[RouteApplicator] ERROR: Failed to apply routes: {e}")
            logger.exception(f"Failed to apply routes: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _validate_net_mapping(
        self,
        routing_data: RoutingData,
        net_mapping: Dict[str, int],
        pcb_content: str
    ) -> Tuple[Dict[str, int], List[str]]:
        """
        TC #51 FIX: Validate and augment net mapping.

        ROOT CAUSE: Nets from SES file may not match net_mapping keys exactly
        (different quoting, case sensitivity, etc.)

        SOLUTION: Try to find matches and build dynamic mapping from PCB content.

        Returns:
            Tuple of (augmented_mapping, missing_net_names)
        """
        augmented = dict(net_mapping)
        missing = []

        # Collect all net names from routing data
        all_nets = set()
        for wire in routing_data.wires:
            all_nets.add(wire.net_name)
        for via in routing_data.vias:
            all_nets.add(via.net_name)

        # TC #51: Extract net definitions from PCB content for dynamic mapping
        # Pattern: (net INDEX "NAME") or (net INDEX NAME)
        pcb_nets = {}
        net_pattern = r'\(net\s+(\d+)\s+"?([^")\s]+)"?\)'
        for match in re.finditer(net_pattern, pcb_content):
            idx = int(match.group(1))
            name = match.group(2)
            pcb_nets[name] = idx
            pcb_nets[name.lower()] = idx  # Also add lowercase

        # Check each routing net against mapping
        for net_name in all_nets:
            if net_name not in augmented:
                # Try case-insensitive match
                found = False
                for key in augmented:
                    if key.lower() == net_name.lower():
                        augmented[net_name] = augmented[key]
                        found = True
                        break

                # Try PCB content extraction
                if not found and net_name in pcb_nets:
                    augmented[net_name] = pcb_nets[net_name]
                    found = True

                # Try lowercase in PCB nets
                if not found and net_name.lower() in pcb_nets:
                    augmented[net_name] = pcb_nets[net_name.lower()]
                    found = True

                if not found:
                    missing.append(net_name)
                    # TC #51: Assign a fallback net index (use 1 for unrouted, not 0)
                    # Net 0 is typically "unconnected" in KiCad which may cause issues
                    augmented[net_name] = 1

        return augmented, missing

    def _insert_routing_robust(self, content: str, routing_sexpr: str) -> str:
        """
        TC #71 Phase 0.2: Robust routing insertion with MANDATORY balance validation.

        CRITICAL FIX: Validates parenthesis balance before and after insertion.
        Uses precise S-expression insertion to prevent corruption.

        ROOT CAUSE: Simple content.rstrip()[:-1] fails on various edge cases:
        - Extra whitespace after final )
        - Multiple trailing newlines
        - Comments after content
        - Unbalanced parens from failed trace removal

        SOLUTION: Find exact insertion point using paren counting, validate result.
        """
        # TC #71: Log routing_sexpr stats for debugging
        routing_open = routing_sexpr.count('(')
        routing_close = routing_sexpr.count(')')
        logger.info(f"TC #71: Routing S-expr has {routing_open} open, {routing_close} close parens")

        if routing_open != routing_close:
            logger.error(f"TC #71 CRITICAL: Generated routing S-expr is unbalanced!")
            logger.error(f"TC #71: This will corrupt the file - fixing...")
            # Fix by adding/removing parens
            if routing_open > routing_close:
                routing_sexpr = routing_sexpr + (')' * (routing_open - routing_close))
            else:
                # Remove extra close parens from end
                diff = routing_close - routing_open
                lines = routing_sexpr.rstrip().split('\n')
                while diff > 0 and lines:
                    last = lines[-1]
                    if last.strip() == ')':
                        lines.pop()
                        diff -= 1
                    elif last.rstrip().endswith(')'):
                        lines[-1] = last.rstrip()[:-1]
                        diff -= 1
                    else:
                        break
                routing_sexpr = '\n'.join(lines)

        # TC #71: Find the EXACT insertion point
        # The KiCad PCB format is: (kicad_pcb ... <content> )
        # We need to insert BEFORE the final closing paren

        # Strategy: Find the position of the LAST balanced ) that closes the (kicad_pcb
        # This is more reliable than regex

        # Find the start of kicad_pcb block
        kicad_start = content.find('(kicad_pcb')
        if kicad_start == -1:
            logger.error("TC #71: Not a valid KiCad PCB file - missing (kicad_pcb header")
            return content + '\n' + routing_sexpr

        # Count parens to find the matching close for (kicad_pcb
        depth = 0
        in_string = False
        escape_next = False
        root_close_pos = -1

        for i, char in enumerate(content):
            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    # Found the root closing paren
                    root_close_pos = i
                    break

        if root_close_pos == -1:
            # Fallback: use last ) position
            logger.warning("TC #71: Could not find root closer via counting - using regex fallback")
            last_paren_match = re.search(r'\)\s*$', content)
            if last_paren_match:
                root_close_pos = last_paren_match.start()
            else:
                # Ultimate fallback
                root_close_pos = content.rfind(')')

        if root_close_pos == -1:
            logger.error("TC #71: Cannot find insertion point - appending routing")
            return content + '\n' + routing_sexpr

        # Insert routing BEFORE the root closing paren
        # Format: <existing content> + newlines + routing + newline + )
        before_close = content[:root_close_pos].rstrip()
        after_close = content[root_close_pos + 1:]  # Anything after the )

        # Build result with proper formatting
        result = before_close + '\n\n' + routing_sexpr + '\n)' + after_close

        # TC #71: Validate result balance
        result_open = result.count('(')
        result_close = result.count(')')

        if result_open != result_close:
            logger.warning(f"TC #71: Result unbalanced after insertion: {result_open} open, {result_close} close")
            # This will be caught by the caller's validation

        return result

    def _remove_existing_traces(self, content: str) -> str:
        """
        TC #70 Phase 0.1: Remove existing (segment ...) and (via ...) blocks from PCB content.

        CRITICAL FIX: Uses balanced parenthesis matching instead of regex.

        The previous regex `r'(segment.*?)\n'` was BROKEN because:
        - Non-greedy `.*?` stops at FIRST `)` inside nested `(start X Y)`
        - Leaves partial S-expressions causing unbalanced parentheses

        NEW APPROACH: Count balanced parentheses to find complete S-expressions.

        GENERIC: Works for any PCB content structure.
        """
        def remove_sexpr_blocks(text: str, keyword: str) -> str:
            """
            Remove all S-expression blocks starting with (keyword ...) using balanced paren matching.

            This is the CORRECT way to remove nested S-expressions without corruption.
            """
            result = text
            iterations = 0
            max_iterations = 10000  # Safety limit

            while iterations < max_iterations:
                iterations += 1

                # Find start of (keyword with word boundary
                # Using \( followed by keyword and whitespace
                import re
                pattern = rf'\({keyword}\s'
                match = re.search(pattern, result)

                if not match:
                    break  # No more blocks to remove

                start_pos = match.start()

                # Now find the matching closing parenthesis by counting
                paren_count = 0
                i = start_pos
                found_end = False

                while i < len(result):
                    char = result[i]
                    if char == '(':
                        paren_count += 1
                    elif char == ')':
                        paren_count -= 1
                        if paren_count == 0:
                            # Found the matching closing paren
                            end_pos = i + 1
                            found_end = True
                            break
                    i += 1

                if found_end:
                    # Remove the entire S-expression block
                    # Also remove trailing whitespace/newline if present
                    while end_pos < len(result) and result[end_pos] in ' \t\n':
                        end_pos += 1
                    result = result[:start_pos] + result[end_pos:]
                else:
                    # Malformed S-expression - skip to avoid infinite loop
                    logger.warning(f"Malformed ({keyword} ...) block at position {start_pos} - skipping")
                    break

            if iterations >= max_iterations:
                logger.error(f"Safety limit reached while removing ({keyword} ...) blocks")

            return result

        # Validate parenthesis balance BEFORE removal
        open_before = content.count('(')
        close_before = content.count(')')

        # Remove all segment blocks
        content = remove_sexpr_blocks(content, "segment")

        # Remove all via blocks (but NOT via definitions in setup section)
        # We only want to remove routing vias, not via definitions in design rules
        content = remove_sexpr_blocks(content, "via")

        # Validate parenthesis balance AFTER removal
        open_after = content.count('(')
        close_after = content.count(')')

        # Log balance check
        if open_after != close_after:
            logger.error(f"TC #70 CRITICAL: Unbalanced parentheses after trace removal!")
            logger.error(f"  Before: {open_before} open, {close_before} close")
            logger.error(f"  After:  {open_after} open, {close_after} close")
            logger.error(f"  Delta:  {open_after - close_after} (should be 0)")
        else:
            logger.debug(f"TC #70: Parenthesis balance OK after trace removal")

        return content

    def _generate_routing_sexpr_robust(
        self,
        routing_data: RoutingData,
        net_mapping: Dict[str, int]
    ) -> Tuple[str, Dict]:
        """
        TC #51 FIX: Generate KiCad S-Expression with detailed statistics.

        Returns both the S-Expression string and generation statistics
        for debugging intermittent failures.

        Args:
            routing_data: Parsed routing from SES
            net_mapping: Net name → net index mapping

        Returns:
            Tuple of (S-Expression string, statistics dict)

        GENERIC: Works for ANY number of traces/vias.
        """
        lines = []
        stats = {
            'wires_processed': 0,
            'wires_skipped': 0,
            'segments_generated': 0,
            'vias_generated': 0,
            'unknown_nets': [],
            'unknown_layers': [],
            'zero_length_segments': 0,
        }

        # Generate segments from wires
        for wire in routing_data.wires:
            stats['wires_processed'] += 1

            # TC #51: Track unknown nets
            if wire.net_name not in net_mapping:
                stats['unknown_nets'].append(wire.net_name)

            net_idx = net_mapping.get(wire.net_name, 1)  # TC #51: Default to 1, not 0
            layer = self._convert_layer_name(wire.layer)

            # TC #51: Track unknown layers
            if wire.layer not in ['F.Cu', 'B.Cu', 'TOP', 'BOTTOM', 'Front', 'Back']:
                if wire.layer not in stats['unknown_layers']:
                    stats['unknown_layers'].append(wire.layer)

            # Validate path points
            if len(wire.path_points) < 2:
                stats['wires_skipped'] += 1
                logger.warning(f"Wire {wire.net_name} has < 2 points, skipping")
                continue

            # Each wire has multiple points - create segments between consecutive points
            for i in range(len(wire.path_points) - 1):
                x1, y1 = wire.path_points[i]
                x2, y2 = wire.path_points[i + 1]

                # TC #51: Skip zero-length segments
                if abs(x1 - x2) < 0.001 and abs(y1 - y2) < 0.001:
                    stats['zero_length_segments'] += 1
                    continue

                segment = self._generate_segment(
                    x1, y1, x2, y2,
                    layer,
                    wire.width_mm,
                    net_idx
                )
                lines.append(segment)
                stats['segments_generated'] += 1

        # Generate vias
        for via in routing_data.vias:
            # TC #51: Track unknown nets for vias too
            if via.net_name not in net_mapping:
                if via.net_name not in stats['unknown_nets']:
                    stats['unknown_nets'].append(via.net_name)

            net_idx = net_mapping.get(via.net_name, 1)  # TC #51: Default to 1, not 0
            # TC #76: Use drill_mm and layers from Via dataclass if available
            drill_mm = getattr(via, 'drill_mm', via.diameter_mm * 0.5)
            layers = getattr(via, 'layers', ["F.Cu", "B.Cu"])
            via_sexpr = self._generate_via_enhanced(
                via.x_mm,
                via.y_mm,
                via.diameter_mm,
                drill_mm,
                layers,
                net_idx
            )
            lines.append(via_sexpr)
            stats['vias_generated'] += 1

        # TC #51: Log statistics for debugging
        if stats['unknown_nets']:
            logger.warning(f"Unknown nets during generation: {stats['unknown_nets'][:10]}")
        if stats['wires_skipped'] > 0:
            logger.warning(f"Skipped {stats['wires_skipped']} invalid wires")
        if stats['zero_length_segments'] > 0:
            logger.info(f"Skipped {stats['zero_length_segments']} zero-length segments")

        return '\n'.join(lines), stats

    def _generate_routing_sexpr(
        self,
        routing_data: RoutingData,
        net_mapping: Dict[str, int]
    ) -> str:
        """
        Generate KiCad S-Expression for all routing (segments + vias).

        NOTE: This is the legacy method. Use _generate_routing_sexpr_robust()
        for better diagnostics.

        Args:
            routing_data: Parsed routing from SES
            net_mapping: Net name → net index mapping

        Returns:
            S-Expression string for all traces and vias

        GENERIC: Works for ANY number of traces/vias.
        """
        lines = []

        # Generate segments from wires
        for wire in routing_data.wires:
            net_idx = net_mapping.get(wire.net_name, 1)  # TC #51: Default to 1, not 0
            layer = self._convert_layer_name(wire.layer)

            # Each wire has multiple points - create segments between consecutive points
            for i in range(len(wire.path_points) - 1):
                x1, y1 = wire.path_points[i]
                x2, y2 = wire.path_points[i + 1]

                segment = self._generate_segment(
                    x1, y1, x2, y2,
                    layer,
                    wire.width_mm,
                    net_idx
                )
                lines.append(segment)

        # Generate vias
        # TC #76: Use enhanced via generation with explicit drill and layers
        for via in routing_data.vias:
            net_idx = net_mapping.get(via.net_name, 1)  # TC #51: Default to 1, not 0
            drill_mm = getattr(via, 'drill_mm', via.diameter_mm * 0.5)
            layers = getattr(via, 'layers', ["F.Cu", "B.Cu"])
            via_sexpr = self._generate_via_enhanced(
                via.x_mm,
                via.y_mm,
                via.diameter_mm,
                drill_mm,
                layers,
                net_idx
            )
            lines.append(via_sexpr)

        return '\n'.join(lines)

    def _generate_segment(
        self,
        x1: float, y1: float,
        x2: float, y2: float,
        layer: str,
        width: float,
        net: int
    ) -> str:
        """
        Generate KiCad segment S-Expression.

        Format:
          (segment (start x1 y1) (end x2 y2) (width w) (layer "L") (net n) (uuid u))

        GENERIC: Works for any segment.
        """
        uid = str(uuid.uuid4())
        return f'  (segment (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) (width {width:.3f}) (layer "{layer}") (net {net}) (uuid "{uid}"))'

    def _generate_via(
        self,
        x: float,
        y: float,
        diameter: float,
        net: int
    ) -> str:
        """
        Generate KiCad via S-Expression.

        Format:
          (via (at x y) (size diameter) (drill drill) (layers "F.Cu" "B.Cu") (net n) (uuid u))

        GENERIC: Works for any via.
        """
        uid = str(uuid.uuid4())
        drill = diameter * 0.5  # Drill = 50% of diameter (typical)
        return f'  (via (at {x:.3f} {y:.3f}) (size {diameter:.3f}) (drill {drill:.3f}) (layers "F.Cu" "B.Cu") (net {net}) (uuid "{uid}"))'

    def _generate_via_enhanced(
        self,
        x: float,
        y: float,
        diameter: float,
        drill: float,
        layers: list,
        net: int
    ) -> str:
        """
        TC #76 FIX (2025-12-09): Enhanced via generation with explicit drill and layers.

        Generate KiCad via S-Expression using explicit parameters instead of defaults.
        This ensures vias created by the Manhattan router (with specific drill_mm and
        layers) are correctly represented in the PCB file.

        Format:
          (via (at x y) (size diameter) (drill drill) (layers "L1" "L2") (net n) (uuid u))

        Args:
            x: X position in mm
            y: Y position in mm
            diameter: Via pad diameter in mm
            drill: Via drill hole diameter in mm
            layers: List of two layer names (e.g., ["F.Cu", "B.Cu"])
            net: Net index number

        Returns:
            KiCad S-expression string for the via

        GENERIC: Works for any via configuration.
        """
        uid = str(uuid.uuid4())
        # Ensure layers list has exactly 2 elements
        layer1 = layers[0] if len(layers) > 0 else "F.Cu"
        layer2 = layers[1] if len(layers) > 1 else "B.Cu"
        return f'  (via (at {x:.3f} {y:.3f}) (size {diameter:.3f}) (drill {drill:.3f}) (layers "{layer1}" "{layer2}") (net {net}) (uuid "{uid}"))'

    def _convert_layer_name(self, ses_layer: str) -> str:
        """
        Convert SES layer name to KiCad layer name.

        SES uses different layer naming than KiCad.

        GENERIC: Maps any common layer name.
        """
        # Common mappings
        layer_map = {
            "F.Cu": "F.Cu",
            "B.Cu": "B.Cu",
            "TOP": "F.Cu",
            "BOTTOM": "B.Cu",
            "Front": "F.Cu",
            "Back": "B.Cu"
        }

        return layer_map.get(ses_layer, "F.Cu")  # Default to F.Cu


__all__ = ['RouteApplicator']
