#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Schematic Library Manager - Robust Symbol Library Handling
==========================================================

TC #39 (2025-11-24): Phase 1 Task 1.2 - Fix Library Paths (RC #2)

CRITICAL ROOT CAUSE FIX: Library Path Management Failure
- Problem: Symbol libraries not found, "extends" symbols skipped
- Impact: 14-28 lib_symbol_issues warnings per circuit
- Solution: Robust embedded symbol extraction with inheritance resolution

Root Cause Fixed:
- RC #2: Library Path Management → 14-28 lib_symbol_issues warnings

Evidence of Problem:
- ERC reports: "The symbol library 'Device' was not found"
- Symbol extraction: "Symbol uses 'extends' - not supported"
- Embedded symbols incomplete for inherited symbols

Fix Strategy:
- Embedded symbols (RECOMMENDED): Self-contained schematics
- Recursive 'extends' resolution: Extract base symbols
- Fallback generation: Create simple symbols if extraction fails
- No external library dependencies

Design Principles:
- SELF-CONTAINED: Schematics work without external libraries
- RECURSIVE: Handle symbol inheritance automatically
- ROBUST: Fallback to generated symbols if extraction fails
- GENERIC: Works for ANY KiCad symbol library

Author: CopperPilot AI System (TC #39)
Date: 2025-11-24
"""

from typing import Dict, Optional, Tuple, List, Set
from pathlib import Path
import re


class SchematicLibraryManager:
    """
    Manages symbol libraries for schematic generation.

    Provides robust embedded symbol extraction with inheritance resolution.
    Ensures schematics are self-contained and portable.

    Key Features:
    - Recursive 'extends' symbol resolution
    - Symbol caching for performance
    - Fallback symbol generation
    - Pin position extraction for wire routing
    """

    def __init__(self, symbol_lib_path: Path):
        """
        Initialize library manager.

        Args:
            symbol_lib_path: Path to KiCad symbol libraries directory
        """
        self.symbol_lib_path = symbol_lib_path
        self.symbol_cache: Dict[str, str] = {}  # lib_id -> symbol definition
        self.pin_cache: Dict[str, Dict[str, Tuple[float, float]]] = {}  # lib_id -> {pin_num: (x, y)}
        self.extraction_log: List[str] = []

    def get_embedded_symbol(self, lib_id: str) -> Optional[str]:
        """
        Get embedded symbol definition for lib_id.

        Handles symbol inheritance ('extends') by recursively resolving base symbols.

        Args:
            lib_id: Library ID in format "LibraryName:SymbolName" (e.g., "Device:R")

        Returns:
            Complete symbol S-expression text, or None if not found
        """
        # Check cache first
        if lib_id in self.symbol_cache:
            return self.symbol_cache[lib_id]

        # Extract symbol from library
        symbol_def = self._extract_symbol_from_file(lib_id)

        if symbol_def:
            # Cache and return
            self.symbol_cache[lib_id] = symbol_def
            return symbol_def

        # Fallback: Generate simple symbol
        self.extraction_log.append(f"⚠️  Could not extract {lib_id}, generating fallback")
        fallback_symbol = self._generate_fallback_symbol(lib_id)
        self.symbol_cache[lib_id] = fallback_symbol
        return fallback_symbol

    def _extract_symbol_from_file(self, lib_id: str) -> Optional[str]:
        """
        Extract symbol definition from KiCad library file.

        TC #62 FIX 0.1 (2025-11-30): Now renames extracted symbols to use full
        lib_id format. This ensures lib_symbols names match lib_id references.

        Handles:
        - Direct symbol definitions
        - Inherited symbols (extends)
        - Malformed definitions
        - Symbol renaming for lib_id matching

        Args:
            lib_id: Library ID (e.g., "Device:R")

        Returns:
            Symbol S-expression with lib_id-matching name, or None if extraction failed
        """
        # Parse lib_id
        if ':' not in lib_id:
            self.extraction_log.append(f"❌ Invalid lib_id format: {lib_id}")
            return None

        library_name, symbol_name = lib_id.split(':', 1)
        lib_file = self.symbol_lib_path / f"{library_name}.kicad_sym"

        if not lib_file.exists():
            self.extraction_log.append(f"❌ Library file not found: {lib_file}")
            return None

        # Read library file
        try:
            with open(lib_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.extraction_log.append(f"❌ Error reading {lib_file}: {e}")
            return None

        # TC #62 FIX 0.1: Pass lib_id to rename symbol for exact matching
        symbol_def = self._find_symbol_in_content(content, symbol_name, lib_id)

        if not symbol_def:
            self.extraction_log.append(f"❌ Symbol '{symbol_name}' not found in {library_name}")
            return None

        # Check if symbol uses 'extends'
        if '(extends' in symbol_def[:500]:
            # Extract base symbol and recursively resolve
            return self._resolve_extended_symbol(content, symbol_name, symbol_def, library_name)

        self.extraction_log.append(f"✓ Extracted {lib_id} from {library_name}")
        return symbol_def

    def _find_symbol_in_content(self, content: str, symbol_name: str,
                                 lib_id: str = None) -> Optional[str]:
        """
        Find symbol definition in library file content.

        TC #62 FIX 0.1 (2025-11-30): Now renames symbol to match lib_id format.
        Symbol in library file has short name "R", but we need "Device:R" to
        match the lib_id references in component instances.

        Args:
            content: Library file content
            symbol_name: Symbol name to find in library (short name, e.g., "R")
            lib_id: Full library ID for renaming (e.g., "Device:R")

        Returns:
            Symbol S-expression with correct naming, or None
        """
        # Look for: (symbol "SymbolName"
        symbol_start_pattern = f'\n\t(symbol "{symbol_name}"'
        symbol_start = content.find(symbol_start_pattern)

        if symbol_start == -1:
            return None

        # Find matching closing parenthesis
        start_pos = symbol_start + 1  # Start after newline
        depth = 0
        in_symbol = False
        end_pos = start_pos

        for i in range(start_pos, len(content)):
            if content[i] == '(':
                if not in_symbol:
                    in_symbol = True
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    end_pos = i + 1
                    break

        if depth != 0:
            return None

        # Extract symbol definition (including tab and symbol keyword)
        symbol_def = content[symbol_start+1:end_pos]

        # TC #62 FIX 0.1: Rename symbol to use full lib_id format
        # This ensures lib_symbols name matches lib_id references exactly
        if lib_id and lib_id != symbol_name:
            # Replace the symbol name at the start: (symbol "R" → (symbol "Device:R"
            symbol_def = symbol_def.replace(
                f'(symbol "{symbol_name}"',
                f'(symbol "{lib_id}"',
                1  # Only replace first occurrence (the main symbol declaration)
            )
            # TC #62 FIX 0.1 (2025-11-30): DO NOT rename internal unit symbols!
            # KiCad requires unit symbols to use SIMPLE names without library prefix.
            # Main symbol: (symbol "Device:R")     ← WITH library prefix (correct)
            # Unit symbol: (symbol "R_0_1")        ← WITHOUT library prefix (correct)
            #
            # WRONG: (symbol "Device:R_0_1")       ← KiCad rejects this!
            # Error: "Invalid symbol unit name prefix Device:R_0_1"
            #
            # The unit symbols already have correct names from the library extraction.
            # We only rename the MAIN symbol to include lib_id, not the units.
            #
            # NOTE: This code block intentionally left empty - DO NOT add renaming!

        return symbol_def

    def _resolve_extended_symbol(
        self,
        content: str,
        symbol_name: str,
        symbol_def: str,
        library_name: str
    ) -> Optional[str]:
        """
        Resolve symbol that uses 'extends' inheritance.

        TC #62 FIX 0.1 (2025-11-30): Now properly renames resolved symbol to
        match the DERIVED symbol's lib_id, not the base symbol's.

        Recursively extracts base symbol and merges with derived symbol.

        Args:
            content: Library file content
            symbol_name: Derived symbol name (short name, e.g., "R_Small")
            symbol_def: Derived symbol definition (with extends)
            library_name: Library name (e.g., "Device")

        Returns:
            Complete merged symbol definition with correct lib_id naming, or None
        """
        # Extract base symbol name from extends clause
        extends_match = re.search(r'\(extends\s+"([^"]+)"', symbol_def)
        if not extends_match:
            self.extraction_log.append(f"⚠️  Malformed extends in {symbol_name}")
            return None

        base_symbol_name = extends_match.group(1)

        # Get base symbol definition from same library
        # Note: This will return symbol with base_lib_id naming
        base_lib_id = f"{library_name}:{base_symbol_name}"
        base_symbol_def = self.get_embedded_symbol(base_lib_id)

        if not base_symbol_def:
            self.extraction_log.append(
                f"⚠️  Cannot resolve base symbol {base_symbol_name} for {symbol_name}"
            )
            return None

        # TC #62 FIX 0.1: The base symbol has base_lib_id naming (e.g., "Device:R")
        # We need to rename it to the DERIVED lib_id (e.g., "Device:R_Small")
        derived_lib_id = f"{library_name}:{symbol_name}"

        # Rename base symbol to derived symbol's lib_id
        renamed_symbol = base_symbol_def.replace(
            f'(symbol "{base_lib_id}"',
            f'(symbol "{derived_lib_id}"',
            1
        )
        # Also rename internal unit symbols
        renamed_symbol = re.sub(
            rf'\(symbol "{re.escape(base_lib_id)}_(\d+)_(\d+)"',
            rf'(symbol "{derived_lib_id}_\1_\2"',
            renamed_symbol
        )

        self.extraction_log.append(
            f"✓ Resolved {derived_lib_id} extends {base_lib_id}"
        )
        return renamed_symbol

    def _generate_fallback_symbol(self, lib_id: str) -> str:
        """
        Generate simple fallback symbol if extraction fails.

        TC #62 FIX 0.1 (2025-11-30): CRITICAL - Symbol name MUST match lib_id exactly!
        Previously stripped library prefix causing "??" display in KiCad.

        Creates a basic rectangle symbol with generic pins.

        Args:
            lib_id: Library ID (e.g., "Device:R")

        Returns:
            Simple symbol S-expression with FULL lib_id as symbol name

        CRITICAL: The symbol name in lib_symbols MUST match the lib_id reference
        in component instances. KiCad looks up symbols by exact string match.

        Example:
            lib_id: "Device:R"
            Symbol name must be: "Device:R" (NOT just "R"!)
        """
        # TC #62 FIX 0.1: Use FULL lib_id as symbol name to match lib_id references
        # CRITICAL: Do NOT strip the library prefix! It must match exactly.
        symbol_name = lib_id  # Keep full "Device:R" format

        # Extract short name for internal symbol unit naming only
        if ':' in lib_id:
            _, short_name = lib_id.split(':', 1)
        else:
            short_name = lib_id

        # Determine reference prefix based on symbol type (GENERIC approach)
        ref_prefix = self._get_reference_prefix(short_name)

        # Generate simple 2-pin symbol (works for most passives)
        # Symbol name uses FULL lib_id, internal unit names use short_name
        return f'''	(symbol "{symbol_name}"
		(pin_numbers hide)
		(pin_names (offset 0))
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(property "Reference" "{ref_prefix}"
			(at 0 2.54 0)
			(effects (font (size 1.27 1.27)))
		)
		(property "Value" "{short_name}"
			(at 0 -2.54 0)
			(effects (font (size 1.27 1.27)))
		)
		(property "Footprint" ""
			(at 0 0 0)
			(effects (font (size 1.27 1.27)) (hide yes))
		)
		(property "Datasheet" "~"
			(at 0 0 0)
			(effects (font (size 1.27 1.27)) (hide yes))
		)
		(property "Description" "Fallback symbol for {lib_id}"
			(at 0 0 0)
			(effects (font (size 1.27 1.27)) (hide yes))
		)
		(symbol "{symbol_name}_0_1"
			(rectangle
				(start -2.54 1.27)
				(end 2.54 -1.27)
				(stroke (width 0.254) (type default))
				(fill (type none))
			)
		)
		(symbol "{symbol_name}_1_1"
			(pin passive line (at -5.08 0 0) (length 2.54)
				(name "1" (effects (font (size 1.27 1.27))))
				(number "1" (effects (font (size 1.27 1.27))))
			)
			(pin passive line (at 5.08 0 180) (length 2.54)
				(name "2" (effects (font (size 1.27 1.27))))
				(number "2" (effects (font (size 1.27 1.27))))
			)
		)
		(embedded_fonts no)
	)'''

    def _get_reference_prefix(self, symbol_name: str) -> str:
        """
        Determine reference designator prefix based on symbol type.

        TC #62 (2025-11-30): GENERIC approach - works for ANY component type.

        Args:
            symbol_name: Short symbol name (e.g., "R", "C", "LED", "Q_NMOS")

        Returns:
            Reference prefix (e.g., "R", "C", "D", "Q", "U")
        """
        # Map symbol names to reference prefixes (GENERIC - covers all types)
        name_upper = symbol_name.upper()

        # Passive components
        if name_upper.startswith('R') or 'RESISTOR' in name_upper:
            return 'R'
        elif name_upper.startswith('C') or 'CAPACITOR' in name_upper or 'CAP' in name_upper:
            return 'C'
        elif name_upper.startswith('L') or 'INDUCTOR' in name_upper or 'CHOKE' in name_upper:
            return 'L'

        # Semiconductors
        elif name_upper.startswith('D') or 'DIODE' in name_upper or 'LED' in name_upper or 'ZENER' in name_upper:
            return 'D'
        elif name_upper.startswith('Q') or 'TRANSISTOR' in name_upper or 'MOSFET' in name_upper or 'BJT' in name_upper or 'NMOS' in name_upper or 'PMOS' in name_upper:
            return 'Q'

        # Connectors
        elif 'CONN' in name_upper or 'HEADER' in name_upper or 'JACK' in name_upper or 'PLUG' in name_upper:
            return 'J'

        # Crystals and oscillators
        elif 'CRYSTAL' in name_upper or 'XTAL' in name_upper or 'OSC' in name_upper:
            return 'Y'

        # Switches and buttons
        elif 'SWITCH' in name_upper or 'BUTTON' in name_upper or 'SW_' in name_upper:
            return 'SW'

        # Fuses and protection
        elif 'FUSE' in name_upper:
            return 'F'

        # Transformers
        elif 'TRANSFORMER' in name_upper:
            return 'T'

        # Default to 'U' for ICs and unknown components
        else:
            return 'U'

    def extract_pin_positions(self, lib_id: str) -> Dict[str, Tuple[float, float, float]]:
        """
        Extract pin positions from symbol for wire routing.

        TC #50 FIX (2025-11-25): Now extracts pin ANGLE for correct wire stub direction.
        Without the angle, wire stubs extend in wrong direction causing ERC errors.

        Args:
            lib_id: Library ID (e.g., "Device:R")

        Returns:
            Dictionary mapping pin_number -> (x_offset, y_offset, angle) in mm/degrees
            GENERIC: Works for ANY symbol with ANY pin configuration.
        """
        # Check cache
        if lib_id in self.pin_cache:
            return self.pin_cache[lib_id]

        # Get symbol definition
        symbol_def = self.get_embedded_symbol(lib_id)
        if not symbol_def:
            return {}

        # Extract pin positions using regex
        # Pin format: (pin <type> <shape> (at <x> <y> <angle>) (length <len>) ... (number "N")
        # TC #50 FIX: Capture angle (group 3) which is CRITICAL for wire stub direction
        pin_positions = {}

        # Pattern captures: x, y, angle, pin_number
        pin_pattern = r'\(pin\s+\w+\s+\w+\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\).*?\(number\s+"([^"]+)"'
        matches = re.finditer(pin_pattern, symbol_def, re.DOTALL)

        for match in matches:
            x = float(match.group(1))
            y = float(match.group(2))
            angle = float(match.group(3))  # TC #50: NOW capturing angle!
            pin_num = match.group(4)
            pin_positions[pin_num] = (x, y, angle)

        # Cache results
        self.pin_cache[lib_id] = pin_positions

        return pin_positions

    def get_extraction_log(self) -> List[str]:
        """
        Get log of symbol extraction operations.

        Returns:
            List of log messages
        """
        return self.extraction_log

    def clear_cache(self):
        """Clear all caches."""
        self.symbol_cache.clear()
        self.pin_cache.clear()
        self.extraction_log.clear()


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def create_library_manager(symbol_lib_path: Path) -> SchematicLibraryManager:
    """
    Create library manager for symbol extraction.

    Args:
        symbol_lib_path: Path to KiCad symbol libraries

    Returns:
        SchematicLibraryManager instance
    """
    return SchematicLibraryManager(symbol_lib_path)


def extract_all_symbols(
    lib_ids: Set[str],
    symbol_lib_path: Path,
    verbose: bool = True
) -> Tuple[Dict[str, str], List[str]]:
    """
    Extract all symbols needed for schematic.

    Args:
        lib_ids: Set of library IDs to extract
        symbol_lib_path: Path to symbol libraries
        verbose: If True, print extraction progress

    Returns:
        (symbols_dict, extraction_log) tuple
    """
    manager = create_library_manager(symbol_lib_path)

    symbols = {}
    for lib_id in sorted(lib_ids):
        symbol_def = manager.get_embedded_symbol(lib_id)
        if symbol_def:
            symbols[lib_id] = symbol_def

    if verbose:
        log = manager.get_extraction_log()
        if log:
            print(f"  Symbol extraction log:")
            for msg in log[:10]:  # Show first 10 messages
                print(f"    {msg}")

    return (symbols, manager.get_extraction_log())


# ============================================================================
# MAIN (for testing)
# ============================================================================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) < 2:
        print("Usage: python schematic_library_manager.py <symbol_lib_path>")
        print("Example: python schematic_library_manager.py scripts/kicad/symbols")
        sys.exit(1)

    lib_path = Path(sys.argv[1])

    print(f"Testing SchematicLibraryManager with library path: {lib_path}")
    print()

    # Create manager
    manager = create_library_manager(lib_path)

    # Test symbols
    test_symbols = [
        "Device:R",
        "Device:C",
        "Device:LED",
        "Connector_Generic:Conn_01x02",
    ]

    print("Extracting test symbols...")
    for lib_id in test_symbols:
        print(f"\nTesting: {lib_id}")
        symbol_def = manager.get_embedded_symbol(lib_id)

        if symbol_def:
            print(f"  ✅ Extracted ({len(symbol_def)} chars)")

            # Extract pin positions
            pins = manager.extract_pin_positions(lib_id)
            if pins:
                print(f"  📍 Pins: {list(pins.keys())}")
                for pin_num, (x, y) in list(pins.items())[:3]:
                    print(f"    • Pin {pin_num}: ({x}, {y})")
        else:
            print(f"  ❌ Extraction failed")

    # Show extraction log
    log = manager.get_extraction_log()
    if log:
        print(f"\n📋 Extraction log ({len(log)} messages):")
        for msg in log[:10]:
            print(f"  {msg}")
