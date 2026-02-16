#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Eagle File Validator - UNIVERSAL for ANY circuit type
Validates that generated Eagle XML files are correct for KiCad/EasyEDA import
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Tuple

class EagleValidator:
    """Validates Eagle XML files for KiCad/EasyEDA compatibility."""

    def __init__(self, eagle_dir: str):
        self.eagle_dir = Path(eagle_dir)
        self.errors = []
        self.warnings = []
        self.stats = {
            'files_checked': 0,
            'total_libraries': 0,
            'total_devicesets': 0,
            'total_parts': 0,
            'device_mismatches': 0,
            'package_issues': 0,
            'pin_pad_mismatches': 0
        }

    def validate_all(self) -> bool:
        """Validate all Eagle schematic files."""
        sch_files = list(self.eagle_dir.glob("*.sch"))

        if not sch_files:
            self.errors.append("No .sch files found in eagle directory")
            return False

        print(f"=" * 70)
        print(f"EAGLE FILE VALIDATOR - UNIVERSAL")
        print(f"Validating {len(sch_files)} schematic file(s)")
        print(f"=" * 70)

        for sch_file in sch_files:
            print(f"\n📄 {sch_file.name}")
            self._validate_schematic(sch_file)
            self.stats['files_checked'] += 1

        return len(self.errors) == 0

    def _validate_schematic(self, sch_file: Path) -> None:
        """Validate a single schematic file."""
        try:
            tree = ET.parse(sch_file)
            root = tree.getroot()
        except Exception as e:
            self.errors.append(f"  ❌ {sch_file.name}: Failed to parse XML: {e}")
            return

        # Build library index
        lib_index = self._build_library_index(root)

        # Validate parts against library
        self._validate_parts(root, lib_index, sch_file.name)

        # Validate package pin counts
        self._validate_package_pin_counts(lib_index, sch_file.name)

    def _build_library_index(self, root: ET.Element) -> Dict:
        """Build index of all libraries, devicesets, devices, packages."""
        lib_index = {}

        libraries = root.findall('.//drawing/libraries/library')
        for lib in libraries:
            lib_name = lib.get('name')
            lib_index[lib_name] = {
                'packages': {},
                'symbols': {},
                'devicesets': {}
            }
            self.stats['total_libraries'] += 1

            # Index packages
            for pkg in lib.findall('packages/package'):
                pkg_name = pkg.get('name')
                pads = pkg.findall('pad')
                smds = pkg.findall('smd')
                lib_index[lib_name]['packages'][pkg_name] = {
                    'pad_count': len(pads) + len(smds),
                    'pads': [p.get('name') for p in pads],
                    'smds': [s.get('name') for s in smds]
                }

            # Index symbols
            for sym in lib.findall('symbols/symbol'):
                sym_name = sym.get('name')
                pins = sym.findall('pin')
                lib_index[lib_name]['symbols'][sym_name] = {
                    'pin_count': len(pins),
                    'pins': [p.get('name') for p in pins]
                }

            # Index devicesets
            for ds in lib.findall('devicesets/deviceset'):
                ds_name = ds.get('name')
                self.stats['total_devicesets'] += 1

                # Get gates
                gates = []
                for gate in ds.findall('gates/gate'):
                    gates.append({
                        'name': gate.get('name'),
                        'symbol': gate.get('symbol')
                    })

                # Get devices
                devices = []
                for dev in ds.findall('devices/device'):
                    dev_name = dev.get('name', '')
                    dev_pkg = dev.get('package')

                    # Get connects
                    connects = []
                    for conn in dev.findall('connects/connect'):
                        connects.append({
                            'gate': conn.get('gate'),
                            'pin': conn.get('pin'),
                            'pad': conn.get('pad')
                        })

                    devices.append({
                        'name': dev_name,
                        'package': dev_pkg,
                        'connects': connects
                    })

                lib_index[lib_name]['devicesets'][ds_name] = {
                    'gates': gates,
                    'devices': devices
                }

        return lib_index

    def _validate_parts(self, root: ET.Element, lib_index: Dict, filename: str) -> None:
        """Validate that all parts reference valid devicesets and devices."""
        parts = root.findall('.//schematic/parts/part')

        for part in parts:
            part_name = part.get('name')
            lib_name = part.get('library')
            deviceset_name = part.get('deviceset')
            device_name = part.get('device', '')

            self.stats['total_parts'] += 1

            # Check 1: Library exists
            if lib_name not in lib_index:
                self.errors.append(
                    f"  ❌ Part '{part_name}': Library '{lib_name}' not found"
                )
                continue

            # Check 2: Deviceset exists
            if deviceset_name not in lib_index[lib_name]['devicesets']:
                self.errors.append(
                    f"  ❌ Part '{part_name}': Deviceset '{deviceset_name}' "
                    f"not found in library '{lib_name}'"
                )
                continue

            # Check 3: Device exists in deviceset
            deviceset = lib_index[lib_name]['devicesets'][deviceset_name]
            device_found = False
            matching_device = None

            for dev in deviceset['devices']:
                if dev['name'] == device_name:
                    device_found = True
                    matching_device = dev
                    break

            if not device_found:
                self.errors.append(
                    f"  ❌ Part '{part_name}': Device '{device_name}' not found in "
                    f"deviceset '{deviceset_name}'. Available devices: "
                    f"{[d['name'] for d in deviceset['devices']]}"
                )
                self.stats['device_mismatches'] += 1
                continue

            # Check 4: Package exists
            pkg_name = matching_device['package']
            if pkg_name not in lib_index[lib_name]['packages']:
                self.errors.append(
                    f"  ❌ Part '{part_name}': Package '{pkg_name}' "
                    f"not found in library '{lib_name}'"
                )
                self.stats['package_issues'] += 1

        if not self.errors:
            print(f"  ✅ All {len(parts)} parts validated successfully")

    def _validate_package_pin_counts(self, lib_index: Dict, filename: str) -> None:
        """Validate that packages have correct pad counts for their symbols."""
        for lib_name, lib_data in lib_index.items():
            for ds_name, ds_data in lib_data['devicesets'].items():
                for device in ds_data['devices']:
                    pkg_name = device['package']

                    if pkg_name not in lib_data['packages']:
                        continue  # Already reported above

                    package = lib_data['packages'][pkg_name]
                    connects = device['connects']

                    # Check that all pads have connections
                    package_pads = set(package['pads'] + package['smds'])
                    connected_pads = set([c['pad'] for c in connects])

                    unconnected = package_pads - connected_pads
                    if unconnected:
                        self.warnings.append(
                            f"  ⚠️  Deviceset '{ds_name}', package '{pkg_name}': "
                            f"Pads {unconnected} have no connections"
                        )

                    # Check that all connections point to valid pads
                    invalid_pads = connected_pads - package_pads
                    if invalid_pads:
                        self.errors.append(
                            f"  ❌ Deviceset '{ds_name}', package '{pkg_name}': "
                            f"Connections reference non-existent pads {invalid_pads}"
                        )
                        self.stats['pin_pad_mismatches'] += 1

    def print_summary(self) -> None:
        """Print validation summary."""
        print("\n" + "=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)

        print(f"\n📊 Statistics:")
        print(f"  Files checked: {self.stats['files_checked']}")
        print(f"  Total libraries: {self.stats['total_libraries']}")
        print(f"  Total devicesets: {self.stats['total_devicesets']}")
        print(f"  Total parts: {self.stats['total_parts']}")

        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for err in self.errors[:20]:  # Limit to first 20
                print(err)
            if len(self.errors) > 20:
                print(f"  ... and {len(self.errors) - 20} more errors")

        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warn in self.warnings[:10]:  # Limit to first 10
                print(warn)
            if len(self.warnings) > 10:
                print(f"  ... and {len(self.warnings) - 10} more warnings")

        if not self.errors:
            print("\n✅ ALL VALIDATIONS PASSED!")
            print("   Files are ready for KiCad/EasyEDA import")
        else:
            print("\n❌ VALIDATION FAILED!")
            print(f"   Found {len(self.errors)} error(s) that must be fixed")

        print("=" * 70)

def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python validate_eagle_files.py <eagle_directory>")
        sys.exit(1)

    eagle_dir = sys.argv[1]
    validator = EagleValidator(eagle_dir)

    success = validator.validate_all()
    validator.print_summary()

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
