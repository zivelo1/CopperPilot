#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
SPICE Converter Test Suite
==========================

Tests for the SPICE/LTSpice converter to ensure:
1. All circuit types convert successfully
2. Output files are valid SPICE syntax
3. Component mapping is correct
4. Both .cir and .asc formats are generated

Usage
-----
    # Run with pytest
    pytest tests/test_spice_converter.py -v

    # Run standalone
    python tests/test_spice_converter.py

Author: CopperPilot Team
Date: December 2025
"""

import sys
import json
import tempfile
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Import converter modules
from scripts.spice.netlist_generator import SpiceNetlistGenerator, NetlistConfig
from scripts.spice.ltspice_generator import LTSpiceGenerator, LayoutConfig
from scripts.spice.model_library import SpiceModelLibrary, SpiceType


class TestSpiceModelLibrary:
    """Tests for the SPICE model library."""

    def setup_method(self):
        """Set up test fixtures."""
        self.library = SpiceModelLibrary()

    def test_component_type_mapping(self):
        """Test that component types map to correct SPICE types."""
        # Passive components
        assert self.library.get_spice_type('resistor') == SpiceType.RESISTOR
        assert self.library.get_spice_type('capacitor') == SpiceType.CAPACITOR
        assert self.library.get_spice_type('inductor') == SpiceType.INDUCTOR

        # Diodes
        assert self.library.get_spice_type('diode') == SpiceType.DIODE
        assert self.library.get_spice_type('led') == SpiceType.DIODE
        assert self.library.get_spice_type('zener') == SpiceType.DIODE

        # Transistors
        assert self.library.get_spice_type('npn') == SpiceType.BJT
        assert self.library.get_spice_type('pnp') == SpiceType.BJT
        assert self.library.get_spice_type('nmos') == SpiceType.MOSFET
        assert self.library.get_spice_type('pmos') == SpiceType.MOSFET

        # ICs
        assert self.library.get_spice_type('ic') == SpiceType.SUBCIRCUIT
        assert self.library.get_spice_type('opamp') == SpiceType.SUBCIRCUIT

        print("✅ Component type mapping: PASS")

    def test_value_parsing(self):
        """Test component value parsing with SI prefixes."""
        # The parser returns SPICE-compatible strings which SPICE simulators
        # can interpret directly. Numeric conversion is secondary.

        # Resistors
        val, spice = self.library.parse_value("10k")
        assert "10k" in spice.lower(), f"Expected '10k' in spice string, got: {spice}"

        val, spice = self.library.parse_value("4.7M")
        assert "4.7" in spice.lower() or "4.7m" in spice.lower(), f"Expected '4.7' in spice string, got: {spice}"

        # Capacitors
        val, spice = self.library.parse_value("100nF")
        assert "100n" in spice.lower(), f"Expected '100n' in spice string, got: {spice}"

        val, spice = self.library.parse_value("470uF/63V")  # With voltage rating
        assert "470u" in spice.lower(), f"Expected '470u' in spice string, got: {spice}"

        # Inductors
        val, spice = self.library.parse_value("33uH/3A")  # With current rating
        assert "33u" in spice.lower(), f"Expected '33u' in spice string, got: {spice}"

        print("✅ Value parsing: PASS")

    def test_diode_model_detection(self):
        """Test that diode models are detected from part number."""
        # Standard diode
        comp = {"ref": "D1", "type": "diode", "value": "1N4148", "pins": []}
        model = self.library.get_model(comp)
        assert model.model_name == "1N4148"
        assert model.spice_type == SpiceType.DIODE

        # LED
        comp = {"ref": "LED1", "type": "diode", "value": "LED_GREEN", "pins": []}
        model = self.library.get_model(comp)
        assert "LED" in model.model_name

        print("✅ Diode model detection: PASS")

    def test_ic_subcircuit_generation(self):
        """Test that ICs generate subcircuit models."""
        pins = [
            {"number": "1", "name": "IN", "type": "passive"},
            {"number": "2", "name": "GND", "type": "passive"},
            {"number": "3", "name": "OUT", "type": "passive"},
        ]
        comp = {"ref": "U1", "type": "ic", "value": "LM7805", "pins": pins}
        model = self.library.get_model(comp)

        assert model.spice_type == SpiceType.SUBCIRCUIT
        assert "LM7805" in model.model_name
        assert model.model_definition is not None

        print("✅ IC subcircuit generation: PASS")


class TestSpiceNetlistGenerator:
    """Tests for SPICE netlist generation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = SpiceNetlistGenerator()

    def test_simple_rc_circuit(self):
        """Test generation of a simple RC circuit netlist."""
        circuit = {
            "moduleName": "RC_Filter",
            "components": [
                {"ref": "R1", "type": "resistor", "value": "10k",
                 "pins": [{"number": "1"}, {"number": "2"}]},
                {"ref": "C1", "type": "capacitor", "value": "100nF",
                 "pins": [{"number": "1"}, {"number": "2"}]},
            ],
            "connections": [
                {"net": "INPUT", "points": ["R1.1"]},
                {"net": "OUTPUT", "points": ["R1.2", "C1.1"]},
                {"net": "GND", "points": ["C1.2"]},
            ],
            "pinNetMapping": {
                "R1.1": "INPUT",
                "R1.2": "OUTPUT",
                "C1.1": "OUTPUT",
                "C1.2": "GND",
            },
            "nets": ["INPUT", "OUTPUT", "GND"],
        }

        netlist = self.generator.generate_netlist(circuit, "RC_Filter")

        # Check for required elements
        assert "RC_Filter" in netlist
        assert "R1" in netlist or "RR1" in netlist
        assert "C1" in netlist
        assert "10k" in netlist.lower()
        assert "100n" in netlist.lower()
        assert ".end" in netlist

        print("✅ Simple RC circuit netlist: PASS")

    def test_ground_mapping(self):
        """Test that GND is mapped to node 0."""
        circuit = {
            "moduleName": "Test",
            "components": [],
            "connections": [{"net": "GND", "points": []}],
            "pinNetMapping": {},
            "nets": ["GND", "VCC"],
        }

        netlist = self.generator.generate_netlist(circuit, "Test")
        # GND should be node 0 in the mapping
        assert "GND = node 0" in netlist

        print("✅ Ground mapping: PASS")

    def test_power_source_generation(self):
        """Test auto-generation of power sources."""
        circuit = {
            "moduleName": "Power_Test",
            "components": [],
            "connections": [],
            "pinNetMapping": {},
            "nets": ["GND", "V_5V", "V_3V3", "V_PLUS_15V"],
        }

        netlist = self.generator.generate_netlist(circuit, "Power_Test")

        # Should detect power rails and add sources
        assert "Power Sources" in netlist

        print("✅ Power source generation: PASS")


class TestLTSpiceGenerator:
    """Tests for LTSpice schematic generation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = LTSpiceGenerator()

    def test_asc_header(self):
        """Test LTSpice schematic header generation."""
        circuit = {
            "moduleName": "Test",
            "components": [],
            "connections": [],
            "pinNetMapping": {},
            "nets": [],
        }

        schematic = self.generator.generate_schematic(circuit, "Test")

        # Check for required ASC elements
        assert "Version 4" in schematic
        assert "SHEET" in schematic

        print("✅ LTSpice header: PASS")

    def test_component_symbols(self):
        """Test that components get correct LTSpice symbols."""
        circuit = {
            "moduleName": "Symbols_Test",
            "components": [
                {"ref": "R1", "type": "resistor", "value": "10k",
                 "pins": [{"number": "1"}, {"number": "2"}]},
                {"ref": "C1", "type": "capacitor", "value": "100nF",
                 "pins": [{"number": "1"}, {"number": "2"}]},
            ],
            "connections": [],
            "pinNetMapping": {},
            "nets": [],
        }

        schematic = self.generator.generate_schematic(circuit, "Symbols_Test")

        # Check for symbol statements
        assert "SYMBOL res" in schematic
        assert "SYMBOL cap" in schematic
        assert "SYMATTR InstName R1" in schematic
        assert "SYMATTR InstName C1" in schematic

        print("✅ Component symbols: PASS")


class TestEndToEndConversion:
    """End-to-end conversion tests."""

    def test_full_circuit_conversion(self):
        """Test conversion of a complete circuit."""
        # Find a real circuit file
        output_dirs = list(PROJECT_ROOT.glob("output/*/lowlevel"))
        if not output_dirs:
            print("⏭️ No output directories found - skipping E2E test")
            return

        # Find a circuit file
        circuit_files = []
        for output_dir in output_dirs:
            circuit_files.extend(output_dir.glob("circuit_*.json"))

        if not circuit_files:
            print("⏭️ No circuit files found - skipping E2E test")
            return

        # Test conversion
        circuit_file = circuit_files[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Generate SPICE netlist
            spice_out = temp_path / "test.cir"
            netlist_gen = SpiceNetlistGenerator()
            success = netlist_gen.convert(str(circuit_file), str(spice_out))
            assert success, "SPICE netlist conversion failed"
            assert spice_out.exists(), "SPICE file not created"
            assert spice_out.stat().st_size > 100, "SPICE file too small"

            # Generate LTSpice schematic
            asc_out = temp_path / "test.asc"
            ltspice_gen = LTSpiceGenerator()
            success = ltspice_gen.convert(str(circuit_file), str(asc_out))
            assert success, "LTSpice schematic conversion failed"
            assert asc_out.exists(), "LTSpice file not created"
            assert asc_out.stat().st_size > 100, "LTSpice file too small"

        print(f"✅ Full circuit conversion ({circuit_file.stem}): PASS")


def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "=" * 60)
    print("SPICE CONVERTER TEST SUITE")
    print("=" * 60 + "\n")

    tests_passed = 0
    tests_failed = 0

    # Model Library Tests
    print("--- Model Library Tests ---")
    try:
        test_lib = TestSpiceModelLibrary()
        test_lib.setup_method()
        test_lib.test_component_type_mapping()
        test_lib.test_value_parsing()
        test_lib.test_diode_model_detection()
        test_lib.test_ic_subcircuit_generation()
        tests_passed += 4
    except Exception as e:
        tests_failed += 1
        print(f"❌ Model Library Test FAILED: {e}")

    # Netlist Generator Tests
    print("\n--- Netlist Generator Tests ---")
    try:
        test_gen = TestSpiceNetlistGenerator()
        test_gen.setup_method()
        test_gen.test_simple_rc_circuit()
        test_gen.test_ground_mapping()
        test_gen.test_power_source_generation()
        tests_passed += 3
    except Exception as e:
        tests_failed += 1
        print(f"❌ Netlist Generator Test FAILED: {e}")

    # LTSpice Generator Tests
    print("\n--- LTSpice Generator Tests ---")
    try:
        test_lt = TestLTSpiceGenerator()
        test_lt.setup_method()
        test_lt.test_asc_header()
        test_lt.test_component_symbols()
        tests_passed += 2
    except Exception as e:
        tests_failed += 1
        print(f"❌ LTSpice Generator Test FAILED: {e}")

    # End-to-End Tests
    print("\n--- End-to-End Tests ---")
    try:
        test_e2e = TestEndToEndConversion()
        test_e2e.test_full_circuit_conversion()
        tests_passed += 1
    except Exception as e:
        tests_failed += 1
        print(f"❌ E2E Test FAILED: {e}")

    # Summary
    print("\n" + "=" * 60)
    print(f"RESULTS: {tests_passed} passed, {tests_failed} failed")
    if tests_failed == 0:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60)

    return tests_failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
