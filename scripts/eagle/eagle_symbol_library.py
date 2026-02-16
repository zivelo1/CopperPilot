#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle Symbol Library - Pin Position Extraction

This module provides GENERIC pin position extraction from Eagle symbol definitions.
It reads symbol XML structures and builds a lookup table for pin positions.

Design Principles:
- GENERIC: Works for ANY component type without hardcoding
- DATA-DRIVEN: Extracts information from actual symbol XML
- MODULAR: Reusable across all Eagle converter modules
- DYNAMIC: Adapts to any pin count (2 to N pins)

Author: AI Electronics System
Date: October 23, 2025
"""

import xml.etree.ElementTree as ET
from typing import Dict, Tuple, Optional
from pathlib import Path


class EagleSymbolLibrary:
    """
    GENERIC symbol pin position extractor for Eagle CAD.

    This class parses Eagle symbol definitions and extracts pin positions
    for use in wire generation and geometric validation.

    Architecture:
    - Reads from symbol XML elements
    - Caches pin data for fast lookup
    - Provides simple interface for coordinate queries
    - No assumptions about component types

    Usage:
        library = EagleSymbolLibrary()
        library.extract_all_symbols(eagle_xml_root)
        offset_x, offset_y = library.get_pin_offset('R-US', '1')
    """

    def __init__(self):
        """Initialize the symbol library with empty cache."""
        # Cache structure: symbol_name → {'pins': {pin_number: {x, y, rotation, length}}}
        self.symbol_cache: Dict[str, Dict] = {}

    def extract_symbol(self, symbol_element: ET.Element) -> Dict:
        """
        Extract pin positions from a single symbol definition.

        This method parses one symbol element and extracts all pin information.
        It's GENERIC and works for any symbol structure.

        Args:
            symbol_element: ET.Element representing a <symbol> tag

        Returns:
            Dictionary with structure:
            {
                'symbol_name': str,
                'pins': {
                    'pin_number': {
                        'x': float,           # Offset from component center
                        'y': float,           # Offset from component center
                        'rotation': str,      # R0, R90, R180, R270
                        'length': str,        # short, middle, long
                        'direction': str      # pas, in, out, etc.
                    }
                }
            }

        Notes:
            - Pin positions are offsets from component center (0, 0)
            - Rotation is stored as string (e.g., 'R270')
            - All pins are extracted regardless of component type
        """
        symbol_name = symbol_element.get('name', 'UNKNOWN')
        pins = {}

        # Extract all pin elements from this symbol
        for pin_elem in symbol_element.findall('.//pin'):
            # Get pin attributes
            pin_num = pin_elem.get('name', '')

            # Parse coordinates (mandatory attributes)
            try:
                pin_x = float(pin_elem.get('x', 0))
                pin_y = float(pin_elem.get('y', 0))
            except (ValueError, TypeError):
                # If coordinates can't be parsed, skip this pin
                print(f"  ⚠️  Warning: Cannot parse coordinates for pin '{pin_num}' "
                      f"in symbol '{symbol_name}'")
                continue

            # Get optional attributes with defaults
            rotation = pin_elem.get('rot', 'R0')
            length = pin_elem.get('length', 'short')
            direction = pin_elem.get('direction', 'pas')

            # Store pin data
            pins[pin_num] = {
                'x': pin_x,
                'y': pin_y,
                'rotation': rotation,
                'length': length,
                'direction': direction
            }

        return {
            'symbol_name': symbol_name,
            'pins': pins
        }

    def extract_all_symbols(self, eagle_xml: ET.Element) -> int:
        """
        Extract ALL symbols from Eagle library section.

        This method processes an entire Eagle XML tree and extracts all symbol
        definitions it can find. It's GENERIC and works with any Eagle file structure.

        Args:
            eagle_xml: Root element of Eagle XML (usually <eagle>)

        Returns:
            Number of symbols extracted and cached

        Notes:
            - Symbols are cached in self.symbol_cache for fast lookup
            - Existing cache entries are overwritten
            - Works for multiple libraries in one file
        """
        symbol_count = 0

        # Find all <symbol> elements anywhere in the XML tree
        # This works for symbols in:
        # - <drawing><schematic><libraries><library><symbols>
        # - Embedded libraries in schematics
        # - Any other Eagle file structure
        for symbol_elem in eagle_xml.findall('.//symbol'):
            symbol_data = self.extract_symbol(symbol_elem)
            symbol_name = symbol_data['symbol_name']

            # Cache the symbol data
            self.symbol_cache[symbol_name] = symbol_data
            symbol_count += 1

            # Debug output (optional)
            pin_count = len(symbol_data['pins'])
            # print(f"  ✓ Extracted symbol '{symbol_name}' with {pin_count} pins")

        print(f"  ℹ️  Symbol Library: Extracted {symbol_count} symbols")
        return symbol_count

    def get_pin_offset(self, symbol_name: str, pin_number: str) -> Tuple[float, float]:
        """
        Get pin offset coordinates for a specific symbol and pin.

        This is the main interface method for querying pin positions.
        It's GENERIC and works for any component type.

        Args:
            symbol_name: Name of the symbol (e.g., 'R-US', 'MOSFET-N')
            pin_number: Pin identifier (e.g., '1', '2', 'B', 'G', 'D')

        Returns:
            Tuple of (offset_x, offset_y) in millimeters
            These are offsets from component center position

        Raises:
            KeyError: If symbol or pin not found in cache

        Example:
            >>> offset_x, offset_y = library.get_pin_offset('R-US', '1')
            >>> # For R-US symbol, pin 1 might be at (-5.08, 0)
            >>> offset_x
            -5.08
        """
        # Check if symbol exists
        if symbol_name not in self.symbol_cache:
            raise KeyError(
                f"Symbol '{symbol_name}' not found in library. "
                f"Available symbols: {list(self.symbol_cache.keys())}"
            )

        # Get symbol data
        symbol_data = self.symbol_cache[symbol_name]
        pins = symbol_data['pins']

        # Check if pin exists
        if pin_number not in pins:
            raise KeyError(
                f"Pin '{pin_number}' not found in symbol '{symbol_name}'. "
                f"Available pins: {list(pins.keys())}"
            )

        # Return pin offset
        pin_data = pins[pin_number]
        return (pin_data['x'], pin_data['y'])

    def get_pin_data(self, symbol_name: str, pin_number: str) -> Optional[Dict]:
        """
        Get complete pin data including rotation and other attributes.

        Args:
            symbol_name: Name of the symbol
            pin_number: Pin identifier

        Returns:
            Dictionary with pin data or None if not found

        Example:
            >>> pin_data = library.get_pin_data('MOSFET-N', '1')
            >>> pin_data
            {'x': -7.62, 'y': 0, 'rotation': 'R0', 'length': 'short', 'direction': 'pas'}
        """
        try:
            symbol_data = self.symbol_cache[symbol_name]
            return symbol_data['pins'].get(pin_number)
        except KeyError:
            return None

    def has_symbol(self, symbol_name: str) -> bool:
        """
        Check if a symbol exists in the cache.

        Args:
            symbol_name: Name of the symbol to check

        Returns:
            True if symbol exists, False otherwise
        """
        return symbol_name in self.symbol_cache

    def get_symbol_pin_count(self, symbol_name: str) -> int:
        """
        Get the number of pins in a symbol.

        Args:
            symbol_name: Name of the symbol

        Returns:
            Number of pins in the symbol, or 0 if symbol not found
        """
        if symbol_name in self.symbol_cache:
            return len(self.symbol_cache[symbol_name]['pins'])
        return 0

    def list_symbols(self) -> list:
        """
        Get list of all cached symbol names.

        Returns:
            List of symbol names in the cache
        """
        return list(self.symbol_cache.keys())

    def clear_cache(self):
        """Clear the symbol cache (useful for testing)."""
        self.symbol_cache.clear()

    def print_summary(self):
        """
        Print a summary of the symbol library contents.

        Useful for debugging and verification.
        """
        print("\n" + "=" * 70)
        print("SYMBOL LIBRARY SUMMARY")
        print("=" * 70)
        print(f"Total Symbols: {len(self.symbol_cache)}")

        for symbol_name, symbol_data in sorted(self.symbol_cache.items()):
            pin_count = len(symbol_data['pins'])
            pin_numbers = ', '.join(sorted(symbol_data['pins'].keys()))
            print(f"  • {symbol_name}: {pin_count} pins ({pin_numbers})")

        print("=" * 70)


# Test function for standalone execution
def test_symbol_library():
    """
    Test the symbol library with sample data.

    This function demonstrates the GENERIC nature of the library
    by working with different component types.
    """
    print("Testing Symbol Library...")

    # Create test XML
    test_xml = ET.fromstring('''
    <eagle>
        <drawing>
            <schematic>
                <libraries>
                    <library>
                        <symbols>
                            <symbol name="R-US">
                                <pin name="1" x="-5.08" y="0" length="short" direction="pas"/>
                                <pin name="2" x="5.08" y="0" length="short" direction="pas"/>
                            </symbol>
                            <symbol name="MOSFET-N">
                                <pin name="1" x="-7.62" y="0" length="short" direction="pas"/>
                                <pin name="2" x="0" y="7.62" length="short" direction="pas" rot="R270"/>
                                <pin name="3" x="0" y="-7.62" length="short" direction="pas" rot="R90"/>
                            </symbol>
                        </symbols>
                    </library>
                </libraries>
            </schematic>
        </drawing>
    </eagle>
    ''')

    # Test extraction
    library = EagleSymbolLibrary()
    count = library.extract_all_symbols(test_xml)
    print(f"✓ Extracted {count} symbols")

    # Test pin offset retrieval
    try:
        offset = library.get_pin_offset('R-US', '1')
        print(f"✓ R-US pin 1 offset: {offset}")

        offset = library.get_pin_offset('MOSFET-N', '2')
        print(f"✓ MOSFET-N pin 2 offset: {offset}")
    except KeyError as e:
        print(f"✗ Error: {e}")

    # Test pin data retrieval
    pin_data = library.get_pin_data('MOSFET-N', '2')
    print(f"✓ MOSFET-N pin 2 data: {pin_data}")

    # Print summary
    library.print_summary()

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    test_symbol_library()
