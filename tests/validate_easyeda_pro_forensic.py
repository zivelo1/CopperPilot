#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Forensic validation of EasyEDA Professional files to ensure they are production-ready.
Checks for all critical issues that would prevent import to EasyEDA Professional.
"""

import sys
import json
import zipfile
from pathlib import Path
from typing import Dict, List, Set, Tuple


class EasyEDAProForensicValidator:
    """Forensic validator for EasyEDA Professional files."""

    def __init__(self, pro_dir: str):
        self.pro_dir = Path(pro_dir)
        self.results = {
            'files': [],
            'errors': [],
            'warnings': [],
            'components': 0,
            'symbols': set(),
            'devices': set(),
            'footprints': set(),
            'duplicate_symbols': set(),
            'duplicate_devices': set(),
            'missing_files': [],
            'nets': 0,
            'wires': 0,
            # Routing metrics – populated from PCB files. These are
            # GENERIC and reflect whether any copper actually exists.
            'tracks': 0,
            'vias': 0,
            'pcb_nets': 0,
        }

    def validate(self) -> bool:
        """Run complete forensic validation."""
        print("=" * 70)
        print("FORENSIC VALIDATION OF EASYEDA PROFESSIONAL FILES")
        print("Production-Ready Quality Check")
        print("=" * 70)
        print(f"Directory: {self.pro_dir}")
        print("=" * 70 + "\n")

        # Ingest conversion summary if present (fail-closed on FAILED circuits)
        summary_path = self.pro_dir / 'pro_conversion_summary.json'
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding='utf-8'))
                circuits = summary.get('circuits', {})
                failed = [name for name, info in circuits.items() if str(info.get('status')) != 'SUCCESS']
                if failed:
                    self._add_error(f"Conversion summary reports FAILED circuits: {', '.join(failed)}")
            except Exception as e:
                self._add_warning(f"Could not parse pro_conversion_summary.json: {e}")

        # Find all .epro files
        epro_files = list(self.pro_dir.glob("*.epro"))

        if not epro_files:
            print("❌ No EasyEDA Professional (.epro) files found!")
            return False

        print(f"Found {len(epro_files)} .epro file(s)\n")

        # Validate each .epro file
        for epro_file in epro_files:
            print(f"Validating: {epro_file.name}")
            print("-" * 50)
            self._validate_epro_file(epro_file)
            print()

        # Require EasyEDA-specific verification artifacts (fail-closed)
        self._check_verification_artifacts()

        # Print summary
        self._print_summary()

        # Return success status
        return len(self.results['errors']) == 0

    def _validate_epro_file(self, epro_file: Path) -> None:
        """Validate a single .epro file."""
        try:
            if not zipfile.is_zipfile(epro_file):
                self._add_error(f"{epro_file.name}: Not a valid ZIP archive")
                return

            with zipfile.ZipFile(epro_file, 'r') as zf:
                # Check for required directories
                self._check_directory_structure(zf, epro_file.name)

                # Validate project.json
                if 'project.json' in zf.namelist():
                    project_data = json.loads(zf.read('project.json'))
                    self._validate_project_json(project_data, epro_file.name)
                else:
                    self._add_error(f"{epro_file.name}: Missing project.json")

                # Validate schematic files
                sheet_files = [f for f in zf.namelist() if f.startswith('SHEET/') and f.endswith('.esch')]
                for sheet_file in sheet_files:
                    raw = zf.read(sheet_file)
                    esch_data = self._load_array_any(raw, kind="SCH", archive=epro_file.name, path=sheet_file)
                    if esch_data is not None:
                        self._validate_esch_file(esch_data, sheet_file, epro_file.name)

                # Validate symbol files
                symbol_files = [f for f in zf.namelist() if f.startswith('SYMBOL/') and f.endswith('.esym')]
                for symbol_file in symbol_files:
                    raw = zf.read(symbol_file)
                    esym_data = self._load_array_any(raw, kind="SYMBOL", archive=epro_file.name, path=symbol_file)
                    if esym_data is not None:
                        self._validate_esym_file(esym_data, symbol_file, epro_file.name)

                # Validate footprint files
                footprint_files = [f for f in zf.namelist() if f.startswith('FOOTPRINT/') and f.endswith('.efoo')]
                for footprint_file in footprint_files:
                    raw = zf.read(footprint_file)
                    efoo_data = self._load_array_any(raw, kind="FOOTPRINT", archive=epro_file.name, path=footprint_file)
                    if efoo_data is not None:
                        self._validate_efoo_file(efoo_data, footprint_file, epro_file.name)

                # Validate PCB files (Pro 1.8 array format)
                pcb_files = [f for f in zf.namelist() if f.startswith('PCB/') and f.endswith('.epcb')]
                for pcb_file in pcb_files:
                    raw = zf.read(pcb_file)
                    epcb_data = self._load_array_any(raw, kind="PCB", archive=epro_file.name, path=pcb_file)
                    if epcb_data is not None:
                        self._validate_epcb_file(epcb_data, pcb_file, epro_file.name)

            self.results['files'].append(epro_file.name)

        except zipfile.BadZipFile as e:
            self._add_error(f"{epro_file.name}: Bad ZIP file - {e}")
        except Exception as e:
            self._add_error(f"{epro_file.name}: Validation error - {e}")

    def _check_directory_structure(self, zf: zipfile.ZipFile, filename: str) -> None:
        """Check for required directory structure."""
        required_dirs = ['SHEET/', 'SYMBOL/', 'FOOTPRINT/']
        namelist = zf.namelist()

        for dir_name in required_dirs:
            if not any(f.startswith(dir_name) for f in namelist):
                self._add_warning(f"{filename}: Missing directory {dir_name}")

    def _validate_project_json(self, project_data: Dict, filename: str) -> None:
        """Validate project.json structure."""
        # Check required fields
        required_fields = ['schematics', 'symbols', 'devices', 'config']
        for field in required_fields:
            if field not in project_data:
                self._add_error(f"{filename}: Missing '{field}' in project.json")

        # Validate symbols
        if 'symbols' in project_data:
            symbols = project_data['symbols']
            symbol_titles = set()

            for sym_uuid, sym_data in symbols.items():
                if not isinstance(sym_data, dict):
                    self._add_error(f"{filename}: Invalid symbol data for {sym_uuid}")
                    continue

                title = sym_data.get('title', '')
                if not title:
                    self._add_error(f"{filename}: Symbol {sym_uuid} has no title")
                elif title in symbol_titles:
                    self._add_error(f"{filename}: Duplicate symbol title: {title}")
                    self.results['duplicate_symbols'].add(title)
                else:
                    symbol_titles.add(title)
                    self.results['symbols'].add(title)

        # Validate devices
        if 'devices' in project_data:
            devices = project_data['devices']
            device_titles = set()

            for dev_uuid, dev_data in devices.items():
                if not isinstance(dev_data, dict):
                    self._add_error(f"{filename}: Invalid device data for {dev_uuid}")
                    continue

                title = dev_data.get('title', '')
                if not title:
                    self._add_error(f"{filename}: Device {dev_uuid} has no title")
                elif title in device_titles:
                    self._add_error(f"{filename}: Duplicate device title: {title}")
                    self.results['duplicate_devices'].add(title)
                else:
                    device_titles.add(title)
                    self.results['devices'].add(title)

                # Check device attributes
                attrs = dev_data.get('attributes', {})
                if not attrs.get('Designator'):
                    self._add_warning(f"{filename}: Device {title} has no Designator")
                if not attrs.get('Symbol'):
                    self._add_error(f"{filename}: Device {title} has no Symbol reference")

        # Validate schematics
        if 'schematics' in project_data:
            schematics = project_data['schematics']
            if not schematics:
                self._add_warning(f"{filename}: No schematics defined")
            else:
                for sch_uuid, sch_data in schematics.items():
                    if 'sheets' not in sch_data or not sch_data['sheets']:
                        self._add_error(f"{filename}: Schematic {sch_uuid} has no sheets")

        # Validate config
        if 'config' in project_data:
            config = project_data['config']
            if not config.get('title'):
                self._add_warning(f"{filename}: Project has no title")

    def _validate_esch_file(self, esch_data: List, filepath: str, archive_name: str) -> None:
        """Validate .esch schematic file structure."""
        if not isinstance(esch_data, list):
            self._add_error(f"{archive_name}: {filepath} is not in array format")
            return

        # Check for DOCTYPE
        if not esch_data or esch_data[0][0] != "DOCTYPE":
            self._add_error(f"{archive_name}: {filepath} missing DOCTYPE")
            return

        if len(esch_data[0]) < 3 or esch_data[0][1] != "SCH":
            self._add_error(f"{archive_name}: {filepath} invalid DOCTYPE")

        # Track components and validate structure
        has_head = False
        components = set()
        wires = 0
        component_refs = {}

        for element in esch_data:
            if not isinstance(element, list) or len(element) < 2:
                continue

            elem_type = element[0]

            if elem_type == "HEAD":
                has_head = True

            elif elem_type == "COMPONENT":
                if len(element) < 3:
                    self._add_error(f"{archive_name}: {filepath} invalid COMPONENT element")
                    continue

                comp_id = element[1]
                device_ref = element[2]

                if comp_id in components:
                    self._add_error(f"{archive_name}: {filepath} duplicate component ID: {comp_id}")
                else:
                    components.add(comp_id)
                    self.results['components'] += 1

                # Check for duplicate device references
                if device_ref in component_refs:
                    self._add_warning(f"{archive_name}: {filepath} duplicate device reference: {device_ref}")
                component_refs[device_ref] = comp_id

            elif elem_type == "WIRE":
                wires += 1
                self.results['wires'] += 1

                # Validate wire structure
                if len(element) < 3:
                    self._add_error(f"{archive_name}: {filepath} invalid WIRE element")
                else:
                    coords = element[2]
                    if not isinstance(coords, list):
                        self._add_error(f"{archive_name}: {filepath} WIRE has invalid coordinates")

            elif elem_type == "NETLABEL" or elem_type == "NET":
                self.results['nets'] += 1

        if not has_head:
            self._add_error(f"{archive_name}: {filepath} missing HEAD element")

        if not components:
            self._add_warning(f"{archive_name}: {filepath} has no components")

        if not wires and components:
            self._add_warning(f"{archive_name}: {filepath} has components but no wires")

    def _validate_esym_file(self, esym_data: List, filepath: str, archive_name: str) -> None:
        """Validate .esym symbol file structure."""
        if not isinstance(esym_data, list):
            self._add_error(f"{archive_name}: {filepath} is not in array format")
            return

        # Check for DOCTYPE
        if not esym_data or esym_data[0][0] != "DOCTYPE":
            self._add_error(f"{archive_name}: {filepath} missing DOCTYPE")
            return

        if len(esym_data[0]) < 3 or esym_data[0][1] != "SYMBOL":
            self._add_error(f"{archive_name}: {filepath} invalid DOCTYPE")

        # Check for HEAD and PART
        has_head = False
        has_part = False
        pin_count = 0

        for element in esym_data:
            if not isinstance(element, list) or len(element) < 2:
                continue

            elem_type = element[0]

            if elem_type == "HEAD":
                has_head = True
            elif elem_type == "PART":
                has_part = True
            elif elem_type == "PIN":
                pin_count += 1

        if not has_head:
            self._add_error(f"{archive_name}: {filepath} missing HEAD element")

        if not has_part:
            self._add_error(f"{archive_name}: {filepath} missing PART element")

        if pin_count == 0:
            self._add_warning(f"{archive_name}: {filepath} has no pins")

    def _validate_efoo_file(self, efoo_data: List, filepath: str, archive_name: str) -> None:
        """Validate .efoo footprint file structure."""
        if not isinstance(efoo_data, list):
            self._add_error(f"{archive_name}: {filepath} is not in array format")
            return

        # Check for DOCTYPE
        if not efoo_data or efoo_data[0][0] != "DOCTYPE":
            self._add_error(f"{archive_name}: {filepath} missing DOCTYPE")
            return

        if len(efoo_data[0]) < 3 or efoo_data[0][1] != "FOOTPRINT":
            self._add_error(f"{archive_name}: {filepath} invalid DOCTYPE")

        # Check for HEAD and PART
        has_head = False
        has_part = False
        pad_count = 0

        for element in efoo_data:
            if not isinstance(element, list) or len(element) < 2:
                continue

            elem_type = element[0]

            if elem_type == "HEAD":
                has_head = True
            elif elem_type == "PART":
                has_part = True
            elif elem_type == "PAD":
                pad_count += 1

        if not has_head:
            self._add_error(f"{archive_name}: {filepath} missing HEAD element")

        if not has_part:
            self._add_error(f"{archive_name}: {filepath} missing PART element")

        if pad_count == 0:
            self._add_error(f"{archive_name}: {filepath} has no pads")

        self.results['footprints'].add(filepath.split('/')[-1].replace('.efoo', ''))

    def _validate_epcb_file(self, epcb_data: List, filepath: str, archive_name: str) -> None:
        """Validate .epcb PCB file structure (EasyEDA Pro 1.8)."""
        if not isinstance(epcb_data, list):
            self._add_error(f"{archive_name}: {filepath} is not in array format")
            return

        # DOCTYPE check
        if not epcb_data or epcb_data[0][0] != "DOCTYPE" or len(epcb_data[0]) < 3 or epcb_data[0][1] != "PCB":
            self._add_error(f"{archive_name}: {filepath} missing/invalid DOCTYPE for PCB")
            return

        # Expect Pro 1.8
        version = epcb_data[0][2]
        if str(version) != "1.8":
            self._add_warning(f"{archive_name}: {filepath} PCB DOCTYPE version is {version}, expected 1.8")

        has_head = False
        has_canvas = False
        layer_count = 0
        net_count = 0
        line_count = 0
        via_count = 0

        for element in epcb_data:
            if not isinstance(element, list) or len(element) < 1:
                continue
            et = element[0]
            if et == "HEAD":
                has_head = True
                # editorVersion/importFlag recommended
                try:
                    if not isinstance(element[1], dict) or 'editorVersion' not in element[1]:
                        self._add_warning(f"{archive_name}: {filepath} HEAD missing editorVersion")
                except Exception:
                    self._add_warning(f"{archive_name}: {filepath} HEAD malformed")
            elif et == "CANVAS":
                has_canvas = True
            elif et == "LAYER":
                layer_count += 1
            elif et == "NET":
                net_count += 1
            elif et == "LINE":
                line_count += 1
            elif et == "VIA":
                via_count += 1

        if not has_head:
            self._add_error(f"{archive_name}: {filepath} missing HEAD element")
        if not has_canvas:
            self._add_error(f"{archive_name}: {filepath} missing CANVAS element")
        if layer_count < 2:
            self._add_error(f"{archive_name}: {filepath} has insufficient LAYER entries ({layer_count})")
        if net_count == 0:
            self._add_error(f"{archive_name}: {filepath} has no NET entries in PCB")
        # Record global routing metrics for summary/quality gate
        self.results['pcb_nets'] += net_count
        self.results['tracks'] += line_count
        self.results['vias'] += via_count

        if line_count == 0:
            # A PCB with components, nets and zero LINE segments is
            # structurally valid but electrically unrouted. We treat this
            # as a hard error at forensic level to keep the gate fail‑closed.
            self._add_error(f"{archive_name}: {filepath} has no LINE (track) segments in PCB – board is unrouted")

    def _load_array_any(self, raw: bytes, kind: str, archive: str, path: str):
        """Parse EasyEDA Pro array-based files that can be either:
        - a single JSON list of arrays, or
        - line-delimited arrays (one array per line).
        Returns a list on success; records an error on failure.
        """
        text = raw.decode('utf-8', errors='ignore').strip()
        # Try as single JSON list first
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        # Fallback: parse line-delimited arrays
        lines = [ln for ln in text.splitlines() if ln.strip()]
        items = []
        try:
            for ln in lines:
                items.append(json.loads(ln))
            return items
        except Exception as e:
            self._add_error(f"{archive}: {path} invalid {kind} content: {e}")
            return None

    def _add_error(self, message: str) -> None:
        """Add error message."""
        self.results['errors'].append(f"❌ ERROR: {message}")

    def _add_warning(self, message: str) -> None:
        """Add warning message."""
        self.results['warnings'].append(f"⚠️  WARNING: {message}")

    def _check_verification_artifacts(self) -> None:
        """Ensure ERC/DRC/DFM artifacts exist; fail-closed if missing."""
        # Prefer collocated results under easyeda_pro; fall back to sibling for legacy runs.
        base = self.pro_dir / "easyeda_results"
        if not base.exists():
            base = self.pro_dir.parent / "easyeda_results"
        erc_dir = base / "ERC"
        drc_dir = base / "DRC"
        dfm_dir = base / "verification"

        def _require(dir_path: Path, label: str) -> None:
            if not dir_path.exists() or not any(dir_path.iterdir()):
                self._add_error(f"Missing {label} artifacts in {dir_path}")

        _require(erc_dir, "ERC")
        _require(drc_dir, "DRC")
        _require(dfm_dir, "DFM")

    def _print_summary(self) -> None:
        """Print validation summary."""
        print("=" * 70)
        print("VALIDATION SUMMARY")
        print("=" * 70)

        print(f"\nFiles validated: {len(self.results['files'])}")
        print(f"Total components: {self.results['components']}")
        print(f"Total wires: {self.results['wires']}")
        print(f"Total nets: {self.results['nets']}")
        print(f"PCB nets: {self.results['pcb_nets']}")
        print(f"Unique symbols: {len(self.results['symbols'])}")
        print(f"Unique devices: {len(self.results['devices'])}")
        print(f"Unique footprints: {len(self.results['footprints'])}")
        print(f"Tracks: {self.results['tracks']}  Vias: {self.results['vias']}")

        # CRITICAL FIX (2025-10-27): Check for completeness, not just structure
        # Fail-closed quality gate like KiCad converter
        if len(self.results['footprints']) == 0:
            self._add_error("No footprints generated - PCB assembly impossible")

        # Check for PCB files in the archive
        pcb_file_count = 0
        for filename in self.results['files']:
            try:
                epro_file = self.pro_dir / filename
                with zipfile.ZipFile(epro_file, 'r') as zf:
                    pcb_files = [f for f in zf.namelist() if f.startswith('PCB/') and f.endswith('.epcb')]
                    pcb_file_count += len(pcb_files)
            except:
                pass

        if pcb_file_count == 0:
            self._add_error("No PCB layout files - Cannot manufacture board")

        # Fail-closed for zero nets or zero copper
        if self.results['nets'] == 0 and self.results['pcb_nets'] == 0:
            self._add_error("No nets detected in schematic or PCB data")
        if self.results['tracks'] == 0:
            self._add_error("No tracks routed in any PCB file (copper missing)")

        # If verification artifacts are missing, errors have already been added. Promote summary status accordingly.
        if self.results['errors']:
            pass  # errors already accumulated; nothing additional needed here

        if self.results['duplicate_symbols']:
            print(f"\n🔁 Duplicate Symbols: {len(self.results['duplicate_symbols'])}")
            for dup in sorted(self.results['duplicate_symbols'])[:5]:
                print(f"  - {dup}")

        if self.results['duplicate_devices']:
            print(f"\n🔁 Duplicate Devices: {len(self.results['duplicate_devices'])}")
            for dup in sorted(self.results['duplicate_devices'])[:5]:
                print(f"  - {dup}")

        if self.results['errors']:
            print(f"\n🛑 CRITICAL ERRORS: {len(self.results['errors'])}")
            for error in self.results['errors'][:10]:  # Show first 10
                print(f"  {error}")
            if len(self.results['errors']) > 10:
                print(f"  ... and {len(self.results['errors']) - 10} more")

        if self.results['warnings']:
            print(f"\n⚠️  WARNINGS: {len(self.results['warnings'])}")
            for warning in self.results['warnings'][:10]:  # Show first 10
                print(f"  {warning}")
            if len(self.results['warnings']) > 10:
                print(f"  ... and {len(self.results['warnings']) - 10} more")

        print("\n" + "=" * 70)
        if self.results['errors']:
            print("❌ VALIDATION FAILED - Files have critical errors")
            if self.results['duplicate_symbols'] or self.results['duplicate_devices']:
                print("   Primary Issue: Duplicate library names detected")
                print("   Solution: Use unique naming for symbols and devices")
            if len(self.results['footprints']) == 0:
                print("   CRITICAL: No footprints - Cannot manufacture PCB")
            if pcb_file_count == 0:
                print("   CRITICAL: No PCB layout - Schematic-only output")
        elif self.results['warnings']:
            print("⚠️  VALIDATION PASSED WITH WARNINGS")
        else:
            print("✅ VALIDATION PERFECT - All files are production ready")

        # Score calculation - FAIL-CLOSED: 0% if missing footprints or PCB
        score = 100

        # CRITICAL: Missing footprints or PCB = automatic FAIL (0%)
        if len(self.results['footprints']) == 0 or pcb_file_count == 0:
            score = 0
        else:
            score -= len(self.results['errors']) * 10
            score -= len(self.results['warnings']) * 2
            score -= len(self.results['duplicate_symbols']) * 5
            score -= len(self.results['duplicate_devices']) * 5
            score = max(0, score)

        print(f"\n🏆 QUALITY SCORE: {score}%")

        if score == 100:
            print("🎉 PRODUCTION READY - Files can be imported to EasyEDA Professional")
        elif score >= 90:
            print("✅ ACCEPTABLE - Minor issues that won't prevent import")
        elif score >= 70:
            print("⚠️  NEEDS ATTENTION - Some issues may cause import problems")
        else:
            print("❌ NOT READY - Critical issues will prevent successful import")

        # Import advice
        print("\n📝 IMPORT CHECKLIST:")
        print("  ✓ No duplicate library names" if not self.results['duplicate_symbols'] and not self.results['duplicate_devices'] else "  ✗ Fix duplicate library names")
        print("  ✓ All files have valid structure" if not self.results['errors'] else "  ✗ Fix structural errors")
        print("  ✓ All components have symbols" if self.results['symbols'] else "  ✗ Add symbol definitions")
        print("  ✓ All devices have references" if self.results['devices'] else "  ✗ Add device definitions")
        print("  ✓ Footprints present" if len(self.results['footprints']) > 0 else "  ✗ CRITICAL: Generate footprints")
        print("  ✓ PCB layout present" if pcb_file_count > 0 else "  ✗ CRITICAL: Generate PCB layout")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        pro_dir = "output/easyeda_pro_fixed"
    else:
        pro_dir = sys.argv[1]

    validator = EasyEDAProForensicValidator(pro_dir)
    success = validator.validate()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
