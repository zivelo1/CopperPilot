#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

r"""
Safe S-Expression Parser for KiCad Files (PHASE 4 TASK 4.2)

This module provides safe S-expression parsing and manipulation for KiCad PCB files,
replacing dangerous regex-based approaches that corrupt nested parentheses.

CRITICAL FIX: Regex patterns like '\(segment[^)]*\)' fail with nested S-expressions.
This parser uses proper recursive descent to handle ANY nesting level.

TC #71 PHASE 0.3: Added file integrity validation and repair capabilities.
- validate_file_integrity(): Checks S-expression balance before/after operations
- repair_corrupted_file(): Attempts to fix common corruption patterns
- Text-based fallback when sexpdata fails

Author: Claude Code / CopperPilot AI System
Date: 2025-11-19
Updated: 2025-12-07 (TC #71)
"""

from __future__ import annotations
import sexpdata
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
import logging
import re

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TC #71 PHASE 0.3: FILE INTEGRITY VALIDATION AND REPAIR
# ═══════════════════════════════════════════════════════════════════════════════

def validate_sexp_balance(content: str, context: str = "") -> Tuple[bool, int, str]:
    """
    TC #77 ENHANCED: Validate S-expression parenthesis balance with context.

    TC #71: Original implementation
    TC #77: Enhanced to return message and support context parameter

    Args:
        content: S-expression content to validate
        context: Optional context string for logging (e.g., "post-write", "pre-write")

    Returns:
        Tuple of (is_valid, delta, message)
        - is_valid: True if balanced
        - delta: open - close (positive = too many open, negative = too many close)
        - message: Human-readable status message
    """
    open_count = content.count('(')
    close_count = content.count(')')
    delta = open_count - close_count
    is_valid = (delta == 0)

    if is_valid:
        msg = f"S-expression balanced ({open_count} parens)"
    elif delta > 0:
        msg = f"Missing {delta} close parentheses"
    else:
        msg = f"Extra {abs(delta)} close parentheses"

    if context:
        msg = f"[{context}] {msg}"

    return (is_valid, delta, msg)


def repair_sexp_file(content: str) -> Tuple[str, bool, str]:
    """
    TC #71 Phase 0.3: Attempt to repair corrupted S-expression content.

    REPAIR STRATEGIES:
    1. If extra close parens: Remove orphan ) from end
    2. If missing close parens: Add ) at end
    3. If structure is severely broken: Try to salvage valid sections

    Args:
        content: Potentially corrupted S-expression content

    Returns:
        Tuple of (repaired_content, was_repaired, message)
    """
    is_valid, delta, msg = validate_sexp_balance(content, "pre-repair")

    if is_valid:
        return (content, False, "No repair needed")

    logger.warning(f"TC #71: S-expression unbalanced by {delta} parens - attempting repair")

    repaired = content

    if delta < 0:
        # Too many close parens (most common corruption)
        # Strategy: Remove extra ) from END of file
        extra_closes = abs(delta)
        lines = repaired.rstrip().split('\n')

        removed = 0
        while removed < extra_closes and lines:
            last_line = lines[-1].rstrip()

            if last_line == ')':
                lines.pop()
                removed += 1
            elif last_line.endswith(')'):
                # Check if this line has an unmatched )
                line_open = last_line.count('(')
                line_close = last_line.count(')')
                if line_close > line_open:
                    # Remove one close paren
                    lines[-1] = last_line[:-1]
                    removed += 1
                else:
                    break
            else:
                break

        repaired = '\n'.join(lines) + '\n'
        is_valid, new_delta, _ = validate_sexp_balance(repaired, "post-repair")

        if is_valid:
            return (repaired, True, f"Repaired: removed {removed} extra close parentheses")
        else:
            return (repaired, True, f"Partial repair: {removed} closes removed, {abs(new_delta)} remain")

    else:
        # Too many open parens (content truncated or malformed)
        # Strategy: Add missing ) at end
        repaired = repaired.rstrip() + '\n' + (')' * delta) + '\n'

        is_valid, new_delta, _ = validate_sexp_balance(repaired, "post-repair")
        if is_valid:
            return (repaired, True, f"Repaired: added {delta} close parentheses")
        else:
            return (repaired, True, f"Partial repair: {delta} closes added, still unbalanced")


class TextBasedPCBModifier:
    """
    TC #71 Phase 0.3 / Phase 5.2: Text-based PCB modifier for corrupted files.

    When sexpdata fails to parse a corrupted file, this class provides
    text-based operations as a fallback. Uses regex with proper balance
    checking to safely modify PCB files.

    GENERIC: Works for any KiCad PCB file, regardless of version.
    """

    def __init__(self, pcb_file: Path):
        """Initialize with PCB file path."""
        self.pcb_file = pcb_file
        self.content = ""
        self.original_content = ""
        self._load()

    def _load(self) -> bool:
        """Load and optionally repair PCB file content."""
        try:
            self.content = self.pcb_file.read_text(encoding='utf-8')
            self.original_content = self.content

            # Check balance and repair if needed
            is_valid, delta, _ = validate_sexp_balance(self.content, f"load {self.pcb_file.name}")
            if not is_valid:
                logger.warning(f"TC #71: File {self.pcb_file.name} is corrupted (delta={delta})")
                self.content, was_repaired, msg = repair_sexp_file(self.content)
                logger.info(f"TC #71: {msg}")

            return True
        except Exception as e:
            logger.error(f"Failed to load {self.pcb_file}: {e}")
            return False

    def remove_all_routing_text(self) -> int:
        """
        TC #71 Phase 5.2: Remove all routing using text-based approach.

        Uses balanced-parenthesis matching to safely remove (segment ...) and (via ...)
        blocks without corrupting the file.

        Returns:
            Number of routing elements removed
        """
        removed = 0

        def remove_sexpr_blocks(text: str, keyword: str) -> Tuple[str, int]:
            """Remove all S-expression blocks starting with (keyword ...)."""
            result = text
            count = 0
            max_iterations = 50000  # Safety limit

            while count < max_iterations:
                # Find start of block
                pattern = rf'\({keyword}\s'
                match = re.search(pattern, result)
                if not match:
                    break

                start_pos = match.start()

                # Find matching close paren using balance counting
                depth = 0
                i = start_pos
                found_end = False

                while i < len(result):
                    if result[i] == '(':
                        depth += 1
                    elif result[i] == ')':
                        depth -= 1
                        if depth == 0:
                            # Found matching close
                            end_pos = i + 1
                            found_end = True
                            break
                    i += 1

                if found_end:
                    # Remove block including trailing whitespace
                    while end_pos < len(result) and result[end_pos] in ' \t\n':
                        end_pos += 1
                    result = result[:start_pos] + result[end_pos:]
                    count += 1
                else:
                    # Malformed block - skip
                    logger.warning(f"TC #71: Malformed ({keyword}...) block at {start_pos}")
                    break

            return result, count

        # Remove segments
        self.content, seg_count = remove_sexpr_blocks(self.content, "segment")
        removed += seg_count

        # Remove vias
        self.content, via_count = remove_sexpr_blocks(self.content, "via")
        removed += via_count

        logger.info(f"TC #71 Text-based removal: {seg_count} segments, {via_count} vias")
        return removed

    def count_segments(self) -> int:
        """Count segments in current content."""
        return self.content.count('(segment ')

    def count_vias(self) -> int:
        """Count vias in current content."""
        return self.content.count('(via ')

    def save(self, backup: bool = True) -> bool:
        """
        Save modified content with validation.

        Args:
            backup: Create .bak backup before writing

        Returns:
            True if save successful, False otherwise
        """
        # Validate before save - TC #77: Enhanced validation
        is_valid, delta, msg = validate_sexp_balance(self.content, f"save {self.pcb_file.name}")
        if not is_valid:
            logger.error(f"TC #77: Cannot save - {msg}")
            return False

        try:
            if backup:
                backup_path = self.pcb_file.with_suffix('.kicad_pcb.tc71.bak')
                backup_path.write_text(self.original_content, encoding='utf-8')
                logger.info(f"TC #71: Backup saved to {backup_path}")

            self.pcb_file.write_text(self.content, encoding='utf-8')
            logger.info(f"TC #71: Saved {self.pcb_file.name}")
            return True

        except Exception as e:
            logger.error(f"TC #71: Save failed: {e}")
            return False


class KiCadSExpressionParser:
    """
    Safe S-expression parser for KiCad PCB files.

    Handles nested parentheses correctly without corruption.
    """

    def __init__(self):
        """Initialize parser."""
        self.root = None
        self.file_path = None

    def load_file(self, file_path: Path) -> bool:
        """
        Load and parse a KiCad PCB file.

        Args:
            file_path: Path to .kicad_pcb file

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Parse S-expression
            self.root = sexpdata.loads(content)
            self.file_path = file_path
            return True

        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            return False

    def save_file(self, file_path: Optional[Path] = None) -> bool:
        """
        Save S-expression back to file.

        Args:
            file_path: Output path (uses original if None)

        Returns:
            True if successful, False otherwise
        """
        if self.root is None:
            logger.error("No data to save - call load_file first")
            return False

        output_path = file_path or self.file_path
        if output_path is None:
            logger.error("No output path specified")
            return False

        try:
            # Convert back to S-expression string
            content = sexpdata.dumps(self.root)

            # Write to file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Validate written file can be parsed
            if not self._validate_file(output_path):
                logger.error(f"Validation failed after write: {output_path}")
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to save {output_path}: {e}")
            return False

    def _validate_file(self, file_path: Path) -> bool:
        """
        Validate that file is valid S-expression (no corruption).

        Args:
            file_path: Path to validate

        Returns:
            True if valid, False if corrupted
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            sexpdata.loads(content)
            return True
        except Exception as e:
            logger.error(f"File validation failed: {e}")
            return False

    def find_elements(self, element_type: str) -> List[Any]:
        """
        Find all elements of a given type (e.g., 'segment', 'via', 'footprint').

        Args:
            element_type: S-expression type to find

        Returns:
            List of matching elements
        """
        if self.root is None:
            return []

        results = []
        self._find_elements_recursive(self.root, element_type, results)
        return results

    def _find_elements_recursive(self, node: Any, element_type: str, results: List[Any]):
        """
        Recursively search for elements.

        Args:
            node: Current S-expression node
            element_type: Type to search for
            results: List to append results to
        """
        if isinstance(node, list):
            # Check if this is a matching element
            if len(node) > 0 and isinstance(node[0], sexpdata.Symbol):
                if node[0].value() == element_type:
                    results.append(node)

            # Recurse into children
            for child in node:
                self._find_elements_recursive(child, element_type, results)

    def count_elements(self, element_type: str) -> int:
        """
        Count elements of a given type.

        Args:
            element_type: S-expression type to count

        Returns:
            Number of matching elements
        """
        return len(self.find_elements(element_type))

    def get_attribute(self, element: List, attr_name: str) -> Optional[Any]:
        """
        Get attribute value from S-expression element.

        Example: (segment (start 100 100) (end 200 200) (width 0.15))
                 get_attribute(segment, 'width') -> 0.15

        Args:
            element: S-expression list
            attr_name: Attribute name to extract

        Returns:
            Attribute value or None if not found
        """
        if not isinstance(element, list):
            return None

        for item in element:
            if isinstance(item, list) and len(item) > 0:
                if isinstance(item[0], sexpdata.Symbol) and item[0].value() == attr_name:
                    # Return value(s) after the attribute name
                    if len(item) == 2:
                        return item[1]
                    else:
                        return item[1:]

        return None

    def set_attribute(self, element: List, attr_name: str, value: Any) -> bool:
        """
        Set attribute value in S-expression element.

        Args:
            element: S-expression list to modify
            attr_name: Attribute name to set
            value: New value

        Returns:
            True if successful, False otherwise
        """
        if not isinstance(element, list):
            return False

        # Find existing attribute
        for i, item in enumerate(element):
            if isinstance(item, list) and len(item) > 0:
                if isinstance(item[0], sexpdata.Symbol) and item[0].value() == attr_name:
                    # Update existing attribute
                    element[i] = [sexpdata.Symbol(attr_name), value]
                    return True

        # Attribute not found, append it
        element.append([sexpdata.Symbol(attr_name), value])
        return True

    def remove_elements(self, element_type: str) -> int:
        """
        Remove all elements of a given type.

        Args:
            element_type: S-expression type to remove

        Returns:
            Number of elements removed
        """
        if self.root is None:
            return 0

        count = self._remove_elements_recursive(self.root, element_type)
        return count

    def _remove_elements_recursive(self, node: Any, element_type: str) -> int:
        """
        Recursively remove elements.

        Args:
            node: Current S-expression node
            element_type: Type to remove

        Returns:
            Number of elements removed
        """
        if not isinstance(node, list):
            return 0

        count = 0

        # Remove matching children
        i = 0
        while i < len(node):
            child = node[i]
            if isinstance(child, list) and len(child) > 0:
                if isinstance(child[0], sexpdata.Symbol) and child[0].value() == element_type:
                    # Remove this element
                    node.pop(i)
                    count += 1
                    continue  # Don't increment i

            # Recurse into child
            if isinstance(child, list):
                count += self._remove_elements_recursive(child, element_type)

            i += 1

        return count


class SafePCBModifier:
    """
    High-level interface for safe PCB modifications.

    Provides common operations with automatic validation.

    TC #71 PHASE 5.1: Enhanced with text-based fallback for corrupted files.
    When sexpdata fails to parse (due to unbalanced parens), falls back to
    TextBasedPCBModifier for basic operations.
    """

    def __init__(self, pcb_file: Path):
        """
        Initialize modifier with PCB file.

        TC #71: Attempts sexpdata parsing first, falls back to text-based if that fails.

        Args:
            pcb_file: Path to .kicad_pcb file
        """
        self.pcb_file = pcb_file
        self.parser = KiCadSExpressionParser()
        self.text_fallback = None  # TC #71: Text-based fallback
        self.using_text_fallback = False

        # TC #71: Try sexpdata parser first
        try:
            if self.parser.load_file(pcb_file):
                self.root = self.parser.root
                logger.info(f"TC #71: Loaded {pcb_file.name} with sexpdata parser")
            else:
                raise ValueError("sexpdata parse returned False")
        except Exception as e:
            # TC #71 Phase 5.1: Fallback to text-based modifier
            logger.warning(f"TC #71: sexpdata failed for {pcb_file.name}: {e}")
            logger.info(f"TC #71: Using text-based fallback modifier")

            self.text_fallback = TextBasedPCBModifier(pcb_file)
            self.using_text_fallback = True
            self.root = None  # No sexp tree available

            # Verify text fallback loaded
            if not self.text_fallback.content:
                raise ValueError(f"Failed to load PCB file with both parsers: {pcb_file}")

    def count_segments(self) -> int:
        """Count routing segments in PCB."""
        # TC #71: Use text fallback if sexpdata failed
        if self.using_text_fallback:
            return self.text_fallback.count_segments()
        return self.parser.count_elements('segment')

    def count_vias(self) -> int:
        """Count vias in PCB."""
        # TC #71: Use text fallback if sexpdata failed
        if self.using_text_fallback:
            return self.text_fallback.count_vias()
        return self.parser.count_elements('via')

    def get_segments(self) -> List[Any]:
        """Get all routing segments."""
        return self.parser.find_elements('segment')

    def get_vias(self) -> List[Any]:
        """Get all vias."""
        return self.parser.find_elements('via')

    def get_attribute(self, element: List, attr_name: str) -> Optional[Any]:
        """
        Get attribute value from S-expression element.

        CRITICAL BUG FIX (2025-11-23): Added missing method that was causing
        'SafePCBModifier' object has no attribute 'get_attribute' errors.

        Delegates to parser's get_attribute method.

        Args:
            element: S-expression list
            attr_name: Attribute name to extract

        Returns:
            Attribute value or None if not found
        """
        return self.parser.get_attribute(element, attr_name)

    def adjust_trace_widths(self, min_width: float, max_width: float) -> Tuple[int, int]:
        """
        Adjust trace widths to be within limits.

        Args:
            min_width: Minimum allowed width (mm)
            max_width: Maximum allowed width (mm)

        Returns:
            (num_narrowed, num_widened) - counts of adjustments made
        """
        narrowed = 0
        widened = 0

        segments = self.get_segments()
        for segment in segments:
            width = self.parser.get_attribute(segment, 'width')
            if width is not None:
                original_width = float(width)
                new_width = max(min_width, min(original_width, max_width))

                if new_width != original_width:
                    if new_width < original_width:
                        narrowed += 1
                    else:
                        widened += 1

                    self.parser.set_attribute(segment, 'width', new_width)

        return (narrowed, widened)

    def separate_traces_to_layers(self, from_layer: str = "F.Cu", to_layer: str = "B.Cu", ratio: float = 0.5) -> int:
        """
        Move traces from one layer to another for collision reduction.

        TC #86 FIX (2025-12-16): Now correctly uses net INDEX mapping.

        PHASE 18 TASK 18.1 (2025-11-20): Enhanced to be NET-AWARE

        GROUP B - TASK B.1: Layer Separation Fixer

        OLD STRATEGY: Move every Nth segment (breaks nets - segments of same net split)
        NEW STRATEGY: Move entire NETS to alternate layer (preserves connectivity)

        This ensures segments of the same net stay together on the same layer,
        preventing disconnection and reducing via count.

        GENERIC: Works for ANY circuit, ANY trace count.

        Args:
            from_layer: Source layer (default "F.Cu")
            to_layer: Destination layer (default "B.Cu")
            ratio: Fraction of NETS to move (0.0 to 1.0)

        Returns:
            Number of traces moved
        """
        moved = 0
        segments = self.get_segments()

        # TC #86 FIX: Build net index -> name mapping for grouping
        index_to_name = self._build_index_to_name_mapping()

        # PHASE 18.1: Group segments by net for intelligent layer separation
        # This prevents breaking connectivity by moving segments of same net together
        # TC #86 FIX: Group by net INDEX (what segments actually contain), then map to names
        net_segments = {}  # net_index -> [segment1, segment2, ...]

        for segment in segments:
            # Check if segment is on source layer
            layer = self.parser.get_attribute(segment, 'layer')
            if not layer or str(layer).strip('"') != from_layer:
                continue

            # TC #86 FIX: Get net INDEX (not name) from segment
            net_attr = self.parser.get_attribute(segment, 'net')
            if net_attr is not None:
                net_index = None
                try:
                    if isinstance(net_attr, int):
                        net_index = net_attr
                    elif isinstance(net_attr, float):
                        net_index = int(net_attr)
                    elif isinstance(net_attr, str):
                        net_index = int(net_attr)
                    elif hasattr(net_attr, '__int__'):
                        net_index = int(net_attr)
                except (ValueError, TypeError):
                    continue

                if net_index is not None and net_index > 0:  # Skip net 0 (unconnected)
                    if net_index not in net_segments:
                        net_segments[net_index] = []
                    net_segments[net_index].append(segment)

        # Move entire nets to alternate layer based on ratio
        # This keeps all segments of a net together
        nets_list = list(net_segments.keys())
        total_nets = len(nets_list)

        if total_nets == 0:
            logger.warning(f"separate_traces_to_layers: No nets found on {from_layer}")
            return 0

        nets_to_move = int(total_nets * ratio)

        logger.info(f"separate_traces_to_layers: Moving {nets_to_move}/{total_nets} nets from {from_layer} to {to_layer}")

        # Move every Nth net to maintain even distribution
        move_interval = int(1.0 / ratio) if ratio > 0 and ratio < 1.0 else 1

        for idx, net_index in enumerate(nets_list):
            # Should we move this net?
            if idx % move_interval == 0:
                # Move ALL segments of this net to alternate layer
                for segment in net_segments[net_index]:
                    self.parser.set_attribute(segment, 'layer', to_layer)
                    moved += 1

                # Get net name for logging (if available)
                net_name = index_to_name.get(net_index, f"net_{net_index}")
                logger.debug(f"  Moved net '{net_name}' (index {net_index}, {len(net_segments[net_index])} segments) to {to_layer}")

        logger.info(f"separate_traces_to_layers: Successfully moved {moved} segments across {nets_to_move} nets")

        return moved

    def insert_vias_at_layer_transitions(self) -> int:
        """
        Insert vias where segments change layers.

        GROUP B - TASK B.1: Via insertion for layer separation

        Scans all segments and inserts vias at points where adjacent
        segments are on different layers.

        GENERIC: Works for ANY circuit topology.

        Returns:
            Number of vias inserted
        """
        # This is a placeholder - full implementation would require:
        # 1. Group segments by net
        # 2. Find connection points between segments on different layers
        # 3. Insert via elements at those points
        # For now, return 0 (vias would be added automatically during re-routing)
        return 0

    def _build_net_mapping(self) -> Dict[str, int]:
        """
        TC #86 FIX: Build net_name -> net_index mapping from net definitions.

        KiCad PCB files contain net definitions at the top in format:
            (net 0 "")
            (net 1 "GND")
            (net 2 "VCC")
            ...

        But segments only reference nets by INDEX:
            (segment ... (net 2) ...)

        This method builds the mapping so we can convert net names to indices
        when searching for segments to delete.

        GENERIC: Works for ANY KiCad PCB file.

        Returns:
            Dictionary mapping net_name -> net_index
        """
        net_map = {}

        if self.root is None:
            logger.warning("_build_net_mapping: No PCB loaded")
            return net_map

        # Scan root for (net INDEX "NAME") definitions
        for element in self.root:
            if isinstance(element, list) and len(element) >= 3:
                # Check if this is a net definition: (net INDEX "NAME")
                if isinstance(element[0], sexpdata.Symbol) and element[0].value() == 'net':
                    try:
                        # Element format: [Symbol('net'), INDEX, "NAME"]
                        net_index = int(element[1])
                        net_name_raw = element[2]

                        # Handle different representations of net name
                        if isinstance(net_name_raw, str):
                            net_name = net_name_raw.strip('"\'')
                        elif hasattr(net_name_raw, 'value'):
                            # sexpdata String object
                            net_name = str(net_name_raw.value()).strip('"\'')
                        else:
                            net_name = str(net_name_raw).strip('"\'')

                        if net_name:  # Skip empty net names (net 0 "")
                            net_map[net_name] = net_index

                    except (ValueError, IndexError, AttributeError) as e:
                        logger.debug(f"_build_net_mapping: Skipping malformed net: {element[:3]}")
                        continue

        logger.info(f"_build_net_mapping: Found {len(net_map)} net definitions")

        return net_map

    def _build_index_to_name_mapping(self) -> Dict[int, str]:
        """
        TC #86 FIX: Build net_index -> net_name mapping (reverse of _build_net_mapping).

        Useful for debugging and logging which nets are being deleted.

        Returns:
            Dictionary mapping net_index -> net_name
        """
        name_map = self._build_net_mapping()
        return {idx: name for name, idx in name_map.items()}

    def delete_traces_by_net(self, net_names: List[str]) -> int:
        """
        Delete all traces (segments) belonging to specific nets.

        TC #86 CRITICAL FIX (2025-12-16): Now correctly uses net INDEX matching.

        PREVIOUS BUG: Searched for net NAMES inside segment (net ...) attributes,
        but KiCad segments only contain net INDICES: (segment ... (net 2) ...)

        FIX: Build net_name -> net_index mapping from net definitions, then
        search segments for matching INDICES.

        GENERIC: Works for ANY net names, ANY circuit.

        Args:
            net_names: List of net names to delete traces for

        Returns:
            Number of segments deleted
        """
        if self.root is None:
            logger.error("delete_traces_by_net: No PCB loaded")
            return 0

        if not net_names:
            logger.warning("delete_traces_by_net: No net names provided")
            return 0

        # TC #86 FIX: Build net mapping from definitions
        net_map = self._build_net_mapping()

        if not net_map:
            logger.error("delete_traces_by_net: No net definitions found in PCB")
            return 0

        # TC #86 FIX: Convert net names to indices
        net_indices_to_delete = set()
        missing_nets = []

        for name in net_names:
            if name in net_map:
                net_indices_to_delete.add(net_map[name])
            else:
                missing_nets.append(name)

        if missing_nets:
            logger.warning(f"delete_traces_by_net: {len(missing_nets)} nets not found in mapping: {missing_nets[:5]}...")

        if not net_indices_to_delete:
            logger.warning(f"delete_traces_by_net: No valid net indices found for nets {net_names[:5]}...")
            return 0

        logger.info(f"delete_traces_by_net: Deleting segments for {len(net_indices_to_delete)} nets (indices: {sorted(net_indices_to_delete)[:10]}...)")

        # TC #86 FIX: Delete by net INDEX, not name
        deleted = self._delete_segments_by_net_index(self.root, net_indices_to_delete)

        if deleted > 0:
            logger.info(f"delete_traces_by_net: Successfully deleted {deleted} segments from {len(net_indices_to_delete)} nets")
        else:
            logger.warning(f"delete_traces_by_net: No segments found for net indices {sorted(net_indices_to_delete)[:5]}...")

        return deleted

    def _delete_segments_by_net_index(self, node: Any, net_indices: Set[int]) -> int:
        """
        TC #86 FIX: Delete segments by matching net INDEX (not name).

        KiCad segment format:
            (segment (start X Y) (end X Y) (width W) (layer "L") (net INDEX) (uuid "..."))

        The (net INDEX) attribute contains ONLY the net index as an integer,
        not the net name. This method correctly matches against indices.

        Args:
            node: Current S-expression node
            net_indices: Set of net indices to delete (for O(1) lookup)

        Returns:
            Number of segments deleted
        """
        if not isinstance(node, list):
            return 0

        deleted = 0
        i = 0

        while i < len(node):
            child = node[i]

            # Check if this is a segment element
            if isinstance(child, list) and len(child) > 0:
                if isinstance(child[0], sexpdata.Symbol) and child[0].value() == 'segment':
                    # Extract net attribute from this segment
                    net_attr = self.get_attribute(child, 'net')

                    if net_attr is not None:
                        # TC #86 FIX: net_attr is the net INDEX (integer), not [index, name]
                        net_index = None

                        try:
                            # Handle different possible formats
                            if isinstance(net_attr, int):
                                net_index = net_attr
                            elif isinstance(net_attr, float):
                                net_index = int(net_attr)
                            elif isinstance(net_attr, str):
                                net_index = int(net_attr)
                            elif hasattr(net_attr, '__int__'):
                                net_index = int(net_attr)
                        except (ValueError, TypeError):
                            logger.debug(f"  Could not parse net index from: {net_attr}")

                        # Check if this segment belongs to a net we want to delete
                        if net_index is not None and net_index in net_indices:
                            # Delete this segment
                            node.pop(i)
                            deleted += 1
                            logger.debug(f"  Deleted segment from net index: {net_index}")
                            continue  # Don't increment i, check same index again

                # Recurse into child elements (not segments we're deleting)
                if isinstance(child, list):
                    deleted += self._delete_segments_by_net_index(child, net_indices)

            i += 1

        return deleted

    def delete_vias_by_net(self, net_names: List[str]) -> int:
        """
        TC #86 FIX: Delete all vias belonging to specific nets.

        Companion to delete_traces_by_net - also removes vias for the specified nets.

        Args:
            net_names: List of net names to delete vias for

        Returns:
            Number of vias deleted
        """
        if self.root is None:
            logger.error("delete_vias_by_net: No PCB loaded")
            return 0

        if not net_names:
            return 0

        # Build net mapping
        net_map = self._build_net_mapping()

        if not net_map:
            return 0

        # Convert net names to indices
        net_indices_to_delete = {net_map[name] for name in net_names if name in net_map}

        if not net_indices_to_delete:
            return 0

        # Delete vias by net index
        deleted = self._delete_vias_by_net_index(self.root, net_indices_to_delete)

        if deleted > 0:
            logger.info(f"delete_vias_by_net: Deleted {deleted} vias from {len(net_indices_to_delete)} nets")

        return deleted

    def _delete_vias_by_net_index(self, node: Any, net_indices: Set[int]) -> int:
        """
        TC #86 FIX: Delete vias by matching net INDEX.

        Args:
            node: Current S-expression node
            net_indices: Set of net indices to delete

        Returns:
            Number of vias deleted
        """
        if not isinstance(node, list):
            return 0

        deleted = 0
        i = 0

        while i < len(node):
            child = node[i]

            if isinstance(child, list) and len(child) > 0:
                if isinstance(child[0], sexpdata.Symbol) and child[0].value() == 'via':
                    net_attr = self.get_attribute(child, 'net')

                    if net_attr is not None:
                        net_index = None
                        try:
                            if isinstance(net_attr, (int, float)):
                                net_index = int(net_attr)
                            elif isinstance(net_attr, str):
                                net_index = int(net_attr)
                            elif hasattr(net_attr, '__int__'):
                                net_index = int(net_attr)
                        except (ValueError, TypeError):
                            pass

                        if net_index is not None and net_index in net_indices:
                            node.pop(i)
                            deleted += 1
                            continue

                if isinstance(child, list):
                    deleted += self._delete_vias_by_net_index(child, net_indices)

            i += 1

        return deleted

    def _delete_segments_by_net_recursive(self, node: Any, net_names: Set[str]) -> int:
        """
        DEPRECATED: Use delete_traces_by_net() which now correctly uses indices.

        This method is kept for backward compatibility but should not be used.
        It incorrectly assumed segments contain net names, but they only contain indices.

        Args:
            node: Current S-expression node
            net_names: Set of net names (WILL NOT WORK - segments use indices)

        Returns:
            Always 0 - segments don't contain net names
        """
        logger.warning("_delete_segments_by_net_recursive is DEPRECATED - use delete_traces_by_net()")
        # TC #86: This method can never work because segments use net indices, not names
        # Keeping for API compatibility but it will always return 0
        return 0

    def get_violating_nets(self, violations: List[Dict]) -> Set[str]:
        """
        TC #70 Phase 5.1: Extract net names that have violations.

        GROUP B - TASK B.2: Helper for re-routing

        Analyzes DRC violations and extracts which nets are involved,
        so they can be re-routed.

        GENERIC: Parses ANY violation format including KiCad 9 DRC reports.

        Args:
            violations: List of violation dictionaries

        Returns:
            Set of net names with violations
        """
        violating_nets = set()

        import re

        for violation in violations:
            # Try to extract net names from violation text
            vtype = violation.get('type', '')
            text = violation.get('text', '')

            # TC #70 Phase 5.1: Enhanced net extraction patterns for KiCad 9 DRC format
            # DRC reports contain lines like:
            #   "Track [ADJ_15P] on B.Cu"
            #   "Pad 1 [V5_OUT] of R13 on F.Cu"
            #   "Items shorting two nets (nets VIN_RAW and ADJ_15P)"
            #   "PTH pad 1 [GND] of J3"
            net_patterns = [
                r'\[([A-Za-z0-9_]+)\]',           # [NET_NAME] - alphanumeric with underscores
                r'"([A-Za-z0-9_]+)"',             # "NET_NAME" - in double quotes
                r'\(nets?\s+([A-Za-z0-9_]+)',     # (nets NET_NAME or (net NET_NAME
                r'nets?\s+([A-Za-z0-9_]+)\s+and', # nets X and Y - first net
                r'and\s+([A-Za-z0-9_]+)\)',       # and Y) - second net
                r'Track\s+\[([^\]]+)\]',          # Track [NET] specific pattern
                r'Pad\s+\d+\s+\[([^\]]+)\]',      # Pad N [NET] specific pattern
            ]

            for pattern in net_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    # Filter out non-net strings (layer names, component refs, etc.)
                    if match not in ('F', 'B', 'Cu', 'on', 'of', 'the', 'and', 'mm'):
                        # Skip if it looks like a component reference (e.g., R13, C25, U2)
                        if not re.match(r'^[A-Z]{1,2}\d+$', match):
                            violating_nets.add(match)

        # Also check the violation type for implicit nets
        # (some violations don't include explicit net names)
        return violating_nets

    def remove_all_routing(self) -> int:
        """
        TC #70 Phase 5.2: Remove ALL routing elements (segments and vias).
        TC #71 Phase 5.1: Enhanced with text-based fallback for corrupted files.

        Used when AI fixer strategies fail and a complete re-route is needed.
        This is a nuclear option that clears all traces so the router can
        start fresh.

        GENERIC: Works for ANY circuit - removes all segments and vias
        regardless of net, layer, or position.

        Returns:
            Total number of routing elements removed (segments + vias)
        """
        # TC #71: Use text-based fallback if sexpdata parsing failed
        if self.using_text_fallback:
            logger.info("TC #71: Using text-based removal (sexpdata failed)")
            total_removed = self.text_fallback.remove_all_routing_text()
            logger.info(f"TC #71 remove_all_routing: {total_removed} elements removed via text fallback")
            return total_removed

        # Standard sexpdata-based removal
        if self.root is None:
            logger.error("remove_all_routing: No PCB loaded")
            return 0

        total_removed = 0

        # Remove all segments
        segments_removed = self.parser.remove_elements('segment')
        total_removed += segments_removed
        logger.info(f"remove_all_routing: Removed {segments_removed} segments")

        # Remove all vias (routing vias, not via definitions)
        vias_removed = self.parser.remove_elements('via')
        total_removed += vias_removed
        logger.info(f"remove_all_routing: Removed {vias_removed} vias")

        logger.info(f"remove_all_routing: Total {total_removed} routing elements removed")

        return total_removed

    def save(self, backup: bool = True) -> bool:
        """
        Save modifications back to file.

        TC #71: Enhanced to use text fallback save when sexpdata parsing failed.

        Args:
            backup: Create .bak backup before overwriting

        Returns:
            True if successful, False otherwise
        """
        # TC #71: Use text-based save if using fallback
        if self.using_text_fallback:
            logger.info("TC #71: Saving via text-based fallback")
            return self.text_fallback.save(backup=backup)

        # Standard sexpdata save
        if backup:
            backup_file = self.pcb_file.with_suffix('.pcb.bak')
            try:
                import shutil
                shutil.copy2(self.pcb_file, backup_file)
                logger.info(f"Created backup: {backup_file}")
            except Exception as e:
                logger.warning(f"Backup failed: {e}")

        return self.parser.save_file(self.pcb_file)


# Example usage
if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        pcb_file = Path(sys.argv[1])

        # Parse and analyze PCB
        modifier = SafePCBModifier(pcb_file)

        print(f"PCB Analysis: {pcb_file.name}")
        print(f"  Segments: {modifier.count_segments()}")
        print(f"  Vias: {modifier.count_vias()}")

        # Example: Adjust trace widths
        narrowed, widened = modifier.adjust_trace_widths(0.15, 0.50)
        if narrowed > 0 or widened > 0:
            print(f"  Adjusted: {narrowed} narrowed, {widened} widened")

            # Save changes
            if modifier.save(backup=True):
                print(f"  ✓ Saved with backup")
            else:
                print(f"  ✗ Save failed")
        else:
            print(f"  No adjustments needed")
    else:
        print("Usage: python sexp_parser.py <pcb_file.kicad_pcb>")
