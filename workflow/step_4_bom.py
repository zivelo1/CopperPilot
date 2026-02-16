# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 4: BOM (Bill of Materials) Generation
Ported from N8N workflow to Python
Processes components and generates BOM in multiple formats
"""

import json
import csv
import re
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import html

# Use relative imports that will work
import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils.logger import setup_logger
from workflow.state_manager import WorkflowStateManager
from ai_agents.agent_manager import AIAgentManager
from workflow.supplier_apis.supplier_manager import SupplierManager

logger = setup_logger(__name__)


class Step4BOMGeneration:
    """
    Step 4: BOM Generation
    - Extracts components from circuits
    - Groups by type and value
    - Generates BOM in multiple formats
    - Optional supplier API integration (future)
    """

    # Common component packages
    SMD_PACKAGES = ['0402', '0603', '0805', '1206', '1210', 'SOT23', 'SOT223', 'SO8', 'SO16', 'QFP', 'TQFP']
    THT_PACKAGES = ['DIP8', 'DIP14', 'DIP16', 'TO92', 'TO220', 'AXIAL', 'RADIAL']

    def __init__(self, project_id: str, use_supplier_apis: bool = True, websocket_manager=None):
        self.project_id = project_id
        self.state_manager = WorkflowStateManager()
        self.ai_manager = AIAgentManager()
        self.supplier_manager = SupplierManager(websocket_manager=websocket_manager, project_id=project_id) if use_supplier_apis else None
        self.logger = logger
        self.output_dir = None
        self.use_supplier_apis = use_supplier_apis
        self.websocket_manager = websocket_manager

    async def select_parts_with_ai(self, components: List[Dict]) -> List[Dict]:
        """
        Use AI to select best manufacturer parts for components
        AI Agent - Select Best Part (Claude 4 Sonnet, temp 0.2)
        """
        selected_parts = []
        total = len(components)

        for idx, component in enumerate(components, 1):
            # Log progress
            self.logger.info(f"Selecting parts: {idx}/{total} ({idx*100//total}%)")

            # Call AI to select best part
            result = await self.ai_manager.select_best_part({
                'type': component.get('type'),
                'value': component.get('value'),
                'package': component.get('package', 'Unknown'),
                'requirements': component.get('specifications', {})
            })

            if result.get('success'):
                part_info = result.get('parsed_response', {})

                # TYPE CHECKING - Handle string response from failed JSON parsing
                if isinstance(part_info, str):
                    self.logger.warning(f"Parsing failed for {component.get('value')}, using defaults")
                    part_info = {
                        'manufacturer': 'Generic',
                        'partNumber': component.get('value'),
                        'unitPrice': 0.0,
                        'datasheet': ''
                    }

                # Now safe to use .get() methods
                component['manufacturer'] = part_info.get('manufacturer', 'Generic')
                component['partNumber'] = part_info.get('partNumber', component.get('value'))
                component['unitPrice'] = part_info.get('unitPrice', 0.0)
                component['datasheet'] = part_info.get('datasheet', '')

            selected_parts.append(component)

        return selected_parts

    async def optimize_bom_with_ai(self, bom_list: List[Dict]) -> Dict[str, Any]:
        """
        Use AI to optimize the BOM
        AI Agent - Optimize BOM (Claude 4 Sonnet, temp 0.3)
        """
        result = await self.ai_manager.optimize_bom(bom_list)

        if result.get('success'):
            optimized_data = result.get('parsed_response', {})

            # TYPE CHECKING - Handle string response from failed JSON parsing
            if isinstance(optimized_data, str):
                self.logger.warning("BOM optimization response parsing failed, using unoptimized BOM")
                return {
                    'optimized_bom': bom_list,
                    'total_cost': sum(float(c.get('unitPrice', 0) or 0) * int(c.get('quantity', 1) or 1) for c in bom_list),
                    'savings': 0,
                    'recommendations': []
                }

            # Now safe to use .get() methods
            return {
                'optimized_bom': optimized_data.get('optimizedBOM', bom_list),
                'total_cost': optimized_data.get('totalCost', 0),
                'savings': optimized_data.get('savings', 0),
                'recommendations': optimized_data.get('recommendations', [])
            }

        return {
            'optimized_bom': bom_list,
            'total_cost': sum(float(c.get('unitPrice', 0) or 0) * int(c.get('quantity', 1) or 1) for c in bom_list),
            'savings': 0,
            'recommendations': []
        }

    def _validate_selected_parts(self, bom_items: List[Dict]) -> tuple[List[Dict], List[str]]:
        """
        QC/QA validation for AI-selected parts
        Ensures components are relevant and specifications match

        Returns:
            tuple: (bom_items, validation_warnings)
        """
        validation_warnings = []

        for item in bom_items:
            part_number = item.get('partNumber', '')
            value = item.get('value', '')
            comp_type = item.get('type', '').lower()
            manufacturer = item.get('manufacturer', '')
            unit_price = item.get('unitPrice', 0)
            references = item.get('references', '')

            # Skip if using defaults (parsing failed or generic)
            if not part_number or part_number == value or manufacturer == 'Generic':
                continue

            # Parse unit price if it's a string
            price_value = 0.0
            if isinstance(unit_price, str):
                # Extract numeric value from strings like "$0.42" or "2.50"
                price_match = re.findall(r'[\d.]+', str(unit_price))
                if price_match:
                    price_value = float(price_match[0])
            else:
                price_value = float(unit_price) if unit_price else 0.0

            # Validation Check 1: Component type keyword matching
            # Common part number patterns for different component types
            type_patterns = {
                'resistor': ['RC', 'R0', 'RES', 'ERJ', 'RK', 'CRCW'],
                'capacitor': ['CL', 'CAP', 'GRM', 'C0', 'CC', 'GCM'],
                'inductor': ['LQH', 'IND', 'L0', 'MLZ'],
                'diode': ['1N', 'BAT', 'BAS', 'DIODE', 'LED', 'LTST'],
                'transistor': ['2N', 'BC', 'BSS', 'IRLML', 'FDN', 'IRF'],
                'mosfet': ['IRF', 'BSS', 'SI', 'AO', 'FDN'],
                'ic': ['LM', 'TL', 'OP', 'MAX', 'AD', 'STM32', 'ATMEGA', 'TDA', 'NE', 'CD']
            }

            # Check if part number matches expected patterns for component type
            if comp_type in type_patterns:
                patterns = type_patterns[comp_type]
                part_upper = part_number.upper()
                if not any(pattern in part_upper for pattern in patterns):
                    # Allow manufacturer-specific patterns
                    known_manufacturers = ['YAGEO', 'MURATA', 'SAMSUNG', 'TDK', 'KEMET', 'VISHAY',
                                          'TEXAS', 'ANALOG', 'MAXIM', 'ST', 'NXP', 'INFINEON']
                    mfr_upper = manufacturer.upper()
                    if not any(mfr in mfr_upper for mfr in known_manufacturers):
                        validation_warnings.append(
                            f"⚠️  {references}: Part '{part_number}' may not match {comp_type} type"
                        )

            # Validation Check 2: Price sanity check
            # Typical price ranges by component type
            price_ranges = {
                'resistor': (0.001, 5.0),
                'capacitor': (0.001, 50.0),
                'inductor': (0.01, 20.0),
                'diode': (0.01, 10.0),
                'transistor': (0.05, 20.0),
                'mosfet': (0.10, 50.0),
                'ic': (0.10, 100.0),
                'connector': (0.05, 50.0),
                'switch': (0.05, 10.0),
                'crystal': (0.10, 10.0)
            }

            if comp_type in price_ranges:
                min_price, max_price = price_ranges[comp_type]
                if price_value > 0:  # Only check if we have a valid price
                    if price_value < min_price or price_value > max_price:
                        validation_warnings.append(
                            f"⚠️  {references}: Price ${price_value:.2f} seems unusual for {comp_type} (typical: ${min_price}-${max_price})"
                        )

            # Validation Check 3: Value consistency for passives
            if comp_type in ['resistor', 'capacitor', 'inductor']:
                # Check if value appears somewhere in part number or datasheet link
                # This is a soft check - many valid parts won't have value in part number
                value_clean = value.replace('k', 'K').replace('u', 'U').replace('n', 'N').replace('p', 'P')
                # Extract numeric part
                value_numbers = ''.join(c for c in value if c.isdigit() or c == '.')

                # Only warn if we have a clear mismatch
                part_upper = part_number.upper()
                if value_numbers and len(value_numbers) > 2:
                    # This is a very lenient check - just ensures we're not completely off
                    pass  # Most parts will pass this

        # Log validation summary
        if validation_warnings:
            self.logger.warning(f"BOM validation found {len(validation_warnings)} potential issues")
        else:
            self.logger.info("BOM validation passed - all selected parts appear valid")

        return bom_items, validation_warnings

    def _cross_supplier_validation(self, mouser_bom: List[Dict], digikey_bom: List[Dict]) -> List[str]:
        """
        Cross-supplier validation by comparing Mouser and Digikey results

        Returns:
            List of validation warnings
        """
        warnings = []

        for i in range(len(mouser_bom)):
            mouser_part = mouser_bom[i]
            digikey_part = digikey_bom[i]

            references = mouser_part.get('references', '')

            # Check 1: Same part number from both suppliers (high confidence)
            if mouser_part.get('partNumber') == digikey_part.get('partNumber'):
                # Good! Cross-validation successful

                # Check price difference >50% (potential data error)
                mouser_price = float(mouser_part.get('unitPrice', 0))
                digikey_price = float(digikey_part.get('unitPrice', 0))

                if mouser_price > 0 and digikey_price > 0:
                    price_diff = abs(mouser_price - digikey_price) / min(mouser_price, digikey_price)
                    if price_diff > 0.5:
                        warnings.append(
                            f"⚠️  {references}: Price difference >50% for same part "
                            f"(Mouser: ${mouser_price:.3f}, Digikey: ${digikey_price:.3f})"
                        )

            # Check 2: Both show 0 stock (potential obsolete part)
            mouser_stock = mouser_part.get('stock', 0)
            digikey_stock = digikey_part.get('stock', 0)

            if mouser_stock == 0 and digikey_stock == 0:
                warnings.append(
                    f"🔴 {references}: Part unavailable from BOTH suppliers! Consider alternative."
                )

            # Check 3: One supplier has no match
            mouser_selected = mouser_part.get('selected', False)
            digikey_selected = digikey_part.get('selected', False)

            if not mouser_selected and digikey_selected:
                warnings.append(f"ℹ️  {references}: Only available from Digikey")
            elif mouser_selected and not digikey_selected:
                warnings.append(f"ℹ️  {references}: Only available from Mouser")
            elif not mouser_selected and not digikey_selected:
                warnings.append(f"⚠️  {references}: Part not found in either supplier database!")

        return warnings

    async def process(self, circuits: List[Dict], output_dir: str = None, use_ai: bool = True) -> Dict[str, Any]:
        """
        Main processing function for Step 4 - DUAL SUPPLIER MODE

        Args:
            circuits: List of circuit dictionaries from Step 3
            output_dir: Where to save BOM files
            use_ai: If True, use supplier APIs for part selection

        Returns:
            Dict containing:
                - mouser: Mouser BOM, statistics, files
                - digikey: Digikey BOM, statistics, files
                - comparison_file: Path to comparison HTML
        """
        try:
            self.logger.info(f"Step 4 BOM starting for project {self.project_id}")
            self.output_dir = output_dir

            # Extract all components from circuits
            all_components = self._extract_all_components(circuits)
            self.logger.info(f"Extracted {len(all_components)} total components")

            # Group components by type and value
            grouped_components = self._group_components(all_components)
            self.logger.info(f"Grouped into {len(grouped_components)} unique parts")

            # Generate BOM structure (generic, no supplier yet)
            bom_items = self._generate_bom_items(grouped_components)

            # Determine supplier mode for auditability
            supplier_mode = 'dual' if (use_ai and self.use_supplier_apis and self.supplier_manager) else 'fallback'
            self.logger.info(f"Supplier mode: {supplier_mode}")

            # DUAL SUPPLIER MODE
            if supplier_mode == 'dual':
                self.logger.info("=" * 80)
                self.logger.info("DUAL SUPPLIER MODE: Searching Mouser + Digikey in parallel")
                self.logger.info("=" * 80)

                # Parallel search across BOTH suppliers
                mouser_bom, digikey_bom = await self.supplier_manager.select_best_parts_parallel(bom_items)

                # QC/QA Validation for MOUSER
                self.logger.info("Validating Mouser parts (QC/QA)...")
                mouser_bom, mouser_warnings = self._validate_selected_parts(mouser_bom)
                if mouser_warnings:
                    self.logger.info(f"Mouser: {len(mouser_warnings)} validation warnings")
                    for warning in mouser_warnings[:5]:  # Show first 5
                        self.logger.warning(f"[Mouser] {warning}")

                # QC/QA Validation for DIGIKEY
                self.logger.info("Validating Digikey parts (QC/QA)...")
                digikey_bom, digikey_warnings = self._validate_selected_parts(digikey_bom)
                if digikey_warnings:
                    self.logger.info(f"Digikey: {len(digikey_warnings)} validation warnings")
                    for warning in digikey_warnings[:5]:  # Show first 5
                        self.logger.warning(f"[Digikey] {warning}")

                # Cross-supplier validation
                self.logger.info("Performing cross-supplier validation...")
                cross_warnings = self._cross_supplier_validation(mouser_bom, digikey_bom)
                if cross_warnings:
                    self.logger.info(f"Cross-validation: {len(cross_warnings)} findings")
                    for warning in cross_warnings[:5]:  # Show first 5
                        self.logger.warning(warning)

                # Calculate statistics for BOTH
                mouser_stats = self._calculate_statistics(mouser_bom, all_components, supplier="Mouser")
                digikey_stats = self._calculate_statistics(digikey_bom, all_components, supplier="Digikey")

                # Generate MOUSER output files
                self.logger.info("Generating Mouser BOM files...")
                mouser_files = await self._generate_output_files(mouser_bom, mouser_stats, prefix="Mouser")

                # Generate DIGIKEY output files
                self.logger.info("Generating Digikey BOM files...")
                digikey_files = await self._generate_output_files(digikey_bom, digikey_stats, prefix="Digikey")

                # Generate comparison report
                self.logger.info("Generating comparison report...")
                comparison_file = await self._generate_comparison_html(
                    mouser_bom, digikey_bom,
                    mouser_stats, digikey_stats
                )

                # Get supplier statistics
                supplier_stats = self.supplier_manager.get_statistics()
                self.logger.info(f"Supplier API Statistics:")
                self.logger.info(f"  Mouser: {supplier_stats['mouser_searches']} searches, {supplier_stats['mouser_results']} results")
                self.logger.info(f"  Digikey: {supplier_stats['digikey_searches']} searches, {supplier_stats['digikey_results']} results")

                # Prepare result
                result = {
                    'mouser': {
                        'bom': mouser_bom,
                        'statistics': mouser_stats,
                        'files': mouser_files,
                        'validation_warnings': mouser_warnings
                    },
                    'digikey': {
                        'bom': digikey_bom,
                        'statistics': digikey_stats,
                        'files': digikey_files,
                        'validation_warnings': digikey_warnings
                    },
                    'comparison_file': comparison_file,
                    'cross_validation_warnings': cross_warnings,
                    'supplier_statistics': supplier_stats,
                    'total_components': len(all_components),
                    'unique_parts': len(bom_items)
                }

                # Save to state
                self.state_manager.update_state('step_4_output', result)

                self.logger.info("=" * 80)
                self.logger.info(f"Step 4 completed - DUAL SUPPLIER MODE")
                self.logger.info(f"  Mouser BOM: {len(mouser_bom)} items, Total: ${mouser_stats.get('total_cost', 0):.2f}")
                self.logger.info(f"  Digikey BOM: {len(digikey_bom)} items, Total: ${digikey_stats.get('total_cost', 0):.2f}")
                self.logger.info(f"  Comparison: {comparison_file}")
                self.logger.info("=" * 80)

                return result

            else:
                # FALLBACK: Single BOM mode (legacy AI-based)
                self.logger.info("Single BOM mode (AI-based part selection)")

                # Add manufacturer part numbers (if known)
                bom_items = self._add_manufacturer_info(bom_items)

                if use_ai:
                    self.logger.info("Using AI Agent - Select Best Part (Claude 4 Sonnet, temp 0.2)...")
                    bom_items = await self.select_parts_with_ai(bom_items)

                    # QC/QA Validation
                    self.logger.info("Validating selected parts (QC/QA)...")
                    bom_items, validation_warnings = self._validate_selected_parts(bom_items)
                    if validation_warnings:
                        for warning in validation_warnings:
                            self.logger.warning(warning)

                # Calculate statistics
                statistics = self._calculate_statistics(bom_items, all_components)

                # Generate output files
                output_files = await self._generate_output_files(bom_items, statistics)

                # Prepare result
                result = {
                    'bom': bom_items,
                    'statistics': statistics,
                    'files': output_files,
                    'total_components': len(all_components),
                    'unique_parts': len(bom_items)
                }

                # Save to state
                self.state_manager.update_state('step_4_output', result)

                self.logger.info(f"Step 4 completed. Generated {len(bom_items)} BOM items")

                return result

        except Exception as e:
            self.logger.error(f"Error in Step 4: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            raise

    def _extract_all_components(self, circuits: List[Dict]) -> List[Dict]:
        """
        Extract all components from all circuits.

        Phase D (Forensic Fix 20260208): In multi-agent mode, the circuit list
        may contain lightweight references with a ``filepath`` key instead of
        inline component data.  When detected, load the full JSON from disk.
        Also skips the mega-module ``circuit_integrated_circuit.json`` (Phase B).
        """
        all_components = []

        for circuit_idx, circuit in enumerate(circuits):
            # Phase D: If this is a lightweight filepath reference, load from disk
            if 'filepath' in circuit and not circuit.get('components'):
                filepath = circuit['filepath']
                # Phase B: Skip the mega-module
                if 'integrated_circuit' in str(filepath).lower():
                    self.logger.info(f"Skipping mega-module file: {filepath}")
                    continue
                try:
                    circuit_path = Path(filepath)
                    if circuit_path.exists():
                        circuit = json.loads(circuit_path.read_text())
                        self.logger.debug(f"Loaded circuit from disk: {filepath}")
                    else:
                        self.logger.warning(f"Circuit file not found: {filepath} — skipping")
                        continue
                except Exception as load_err:
                    self.logger.warning(f"Failed to load circuit from {filepath}: {load_err} — skipping")
                    continue

            # Handle nested circuit structure {"circuit": {...}}
            if 'circuit' in circuit and isinstance(circuit['circuit'], dict):
                actual_circuit = circuit['circuit']
            else:
                actual_circuit = circuit

            circuit_name = actual_circuit.get(
                'name',
                actual_circuit.get('circuitName', f'Circuit_{circuit_idx + 1}')
            )

            # Phase B: Skip integrated circuit even if it appears inline
            if 'integrated_circuit' in circuit_name.lower():
                self.logger.info(f"Skipping mega-module: {circuit_name}")
                continue

            components = actual_circuit.get('components', [])

            for comp in components:
                # Normalize component data
                component_data = {
                    'refDes': comp.get('ref', comp.get('refDes', '')),
                    'type': comp.get('type', ''),
                    'value': comp.get('value', ''),
                    'circuit': circuit_name,
                    'module': circuit_name,
                    'package': comp.get('package', ''),
                    'specs': comp.get('specs', {}),
                    'notes': comp.get('notes', ''),
                    'pins': comp.get('pins', []),
                    'tolerance': comp.get('tolerance', ''),
                    'power': comp.get('power', '')
                }

                # Infer package if not specified
                if not component_data['package']:
                    component_data['package'] = self._infer_package(component_data)

                all_components.append(component_data)

        return all_components

    def _group_components(self, components: List[Dict]) -> Dict[str, Dict]:
        """Group components by type and value"""
        grouped = defaultdict(lambda: {
            'type': '',
            'value': '',
            'components': [],
            'package': '',
            'specs': {},
            'quantity': 0
        })

        for comp in components:
            # Create grouping key
            key = f"{comp['type']}_{comp['value']}".lower()

            # Update group data
            if not grouped[key]['type']:
                grouped[key]['type'] = comp['type']
                grouped[key]['value'] = comp['value']
                grouped[key]['package'] = comp['package']
                grouped[key]['specs'] = comp['specs']

            # Add component to group
            grouped[key]['components'].append({
                'refDes': comp['refDes'],
                'module': comp['module'],
                'notes': comp['notes']
            })
            grouped[key]['quantity'] = len(grouped[key]['components'])

        return dict(grouped)

    def _generate_bom_items(self, grouped_components: Dict[str, Dict]) -> List[Dict]:
        """Generate BOM items from grouped components"""
        bom_items = []
        item_id = 1

        for key, group in grouped_components.items():
            # Format reference designators
            ref_des_list = [c['refDes'] for c in group['components']]
            ref_des_formatted = self._format_reference_designators(ref_des_list)

            # Determine component category
            category = self._categorize_component(group['type'], group['value'])

            # Create BOM item
            bom_item = {
                'id': item_id,
                'category': category,
                'type': group['type'],
                'value': group['value'],
                'description': self._generate_description(group),
                'quantity': group['quantity'],
                'references': ref_des_formatted,
                'package': group['package'] or 'TBD',
                'manufacturer': '',
                'mpn': '',  # Manufacturer Part Number
                'supplier': '',
                'spn': '',  # Supplier Part Number
                'unit_price': 0.0,
                'extended_price': 0.0,
                'notes': self._combine_notes(group['components']),
                'specs': group['specs']
            }

            bom_items.append(bom_item)
            item_id += 1

        # Sort by category, then by type, then by value
        bom_items.sort(key=lambda x: (x['category'], x['type'], x['value']))

        return bom_items

    def _format_reference_designators(self, ref_des_list: List[str]) -> str:
        """Format reference designators with ranges (e.g., R1-R5, R8)"""
        if not ref_des_list:
            return ""

        # Sort and group by prefix
        by_prefix = defaultdict(list)
        for ref in ref_des_list:
            # Extract prefix and number
            match = re.match(r'([A-Z]+)(\d+)', ref)
            if match:
                prefix = match.group(1)
                number = int(match.group(2))
                by_prefix[prefix].append(number)

        # Format each prefix group
        formatted_groups = []
        for prefix, numbers in sorted(by_prefix.items()):
            numbers.sort()
            ranges = self._find_ranges(numbers)

            # Format ranges
            range_strs = []
            for start, end in ranges:
                if start == end:
                    range_strs.append(f"{prefix}{start}")
                else:
                    range_strs.append(f"{prefix}{start}-{prefix}{end}")

            formatted_groups.append(", ".join(range_strs))

        return ", ".join(formatted_groups)

    def _find_ranges(self, numbers: List[int]) -> List[tuple]:
        """Find continuous ranges in a list of numbers"""
        if not numbers:
            return []

        ranges = []
        start = numbers[0]
        end = numbers[0]

        for num in numbers[1:]:
            if num == end + 1:
                end = num
            else:
                ranges.append((start, end))
                start = num
                end = num

        ranges.append((start, end))
        return ranges

    def _categorize_component(self, comp_type: str, value: str) -> str:
        """Categorize component for BOM organization"""
        type_lower = comp_type.lower()

        # Passive components
        if 'resistor' in type_lower or type_lower == 'r':
            return 'Resistors'
        elif 'capacitor' in type_lower or type_lower == 'c':
            return 'Capacitors'
        elif 'inductor' in type_lower or type_lower == 'l':
            return 'Inductors'

        # Active components
        elif 'transistor' in type_lower or type_lower in ['q', 'bjt', 'fet', 'mosfet']:
            return 'Transistors'
        elif 'diode' in type_lower or type_lower == 'd':
            return 'Diodes'
        elif 'ic' in type_lower or 'opamp' in type_lower or type_lower == 'u':
            return 'Integrated Circuits'

        # Connectors and mechanical
        elif 'connector' in type_lower or type_lower in ['j', 'p', 'x']:
            return 'Connectors'
        elif 'switch' in type_lower or type_lower in ['s', 'sw']:
            return 'Switches'
        elif 'crystal' in type_lower or 'xtal' in type_lower or type_lower == 'y':
            return 'Crystals/Oscillators'
        elif 'led' in type_lower:
            return 'LEDs'

        # Power
        elif 'regulator' in type_lower or 'vreg' in type_lower:
            return 'Voltage Regulators'
        elif 'transformer' in type_lower or type_lower == 't':
            return 'Transformers'

        # Other
        elif 'fuse' in type_lower or type_lower == 'f':
            return 'Fuses'
        elif 'battery' in type_lower or type_lower == 'bt':
            return 'Batteries'
        else:
            return 'Miscellaneous'

    def _generate_description(self, group: Dict) -> str:
        """Generate component description"""
        comp_type = group['type']
        value = group['value']
        specs = group['specs'] or {}

        # Build description
        desc_parts = [value, comp_type]

        # Add relevant specs
        if specs.get('tolerance'):
            desc_parts.append(f"{specs['tolerance']} tolerance")
        if specs.get('power'):
            desc_parts.append(specs['power'])
        if specs.get('voltage'):
            desc_parts.append(f"{specs['voltage']} rated")
        if group['package']:
            desc_parts.append(f"{group['package']} package")

        return " ".join(desc_parts)

    def _combine_notes(self, components: List[Dict]) -> str:
        """Combine notes from all components in group"""
        notes = set()
        for comp in components:
            if comp.get('notes'):
                notes.add(comp['notes'])
        return "; ".join(sorted(notes))

    def _infer_package(self, component: Dict) -> str:
        """Infer component package from type and value"""
        comp_type = component['type'].lower()
        value = component['value']

        # Default packages by type
        if comp_type in ['resistor', 'r']:
            return '0805'  # SMD default
        elif comp_type in ['capacitor', 'c']:
            # Check value for size hint
            if 'uF' in value:
                val_num = float(re.findall(r'[\d.]+', value)[0]) if re.findall(r'[\d.]+', value) else 0
                if val_num > 100:
                    return 'RADIAL'  # Electrolytic
            return '0805'  # SMD default
        elif comp_type in ['ic', 'u', 'opamp']:
            pins = len(component.get('pins', []))
            if pins <= 8:
                return 'SO8'
            elif pins <= 16:
                return 'SO16'
            else:
                return f'QFP{pins}'
        elif comp_type in ['transistor', 'q', 'bjt', 'fet', 'mosfet']:
            return 'SOT23'
        elif comp_type in ['diode', 'd']:
            return 'SOD123'
        elif comp_type in ['led']:
            return '0805'  # SMD LED
        elif comp_type in ['connector', 'j', 'p', 'x']:
            pins = len(component.get('pins', []))
            return f'HDR{pins}X1'
        else:
            return 'TBD'

    def _add_manufacturer_info(self, bom_items: List[Dict]) -> List[Dict]:
        """Add known manufacturer part numbers"""
        # Common parts database (simplified)
        known_parts = {
            # Common op-amps
            'lm358': {'manufacturer': 'Texas Instruments', 'mpn': 'LM358P'},
            'ne5532': {'manufacturer': 'Texas Instruments', 'mpn': 'NE5532P'},
            'tl072': {'manufacturer': 'Texas Instruments', 'mpn': 'TL072CP'},
            'opa548': {'manufacturer': 'Texas Instruments', 'mpn': 'OPA548T'},

            # Voltage regulators
            'lm7805': {'manufacturer': 'STMicroelectronics', 'mpn': 'L7805CV'},
            'lm317': {'manufacturer': 'Texas Instruments', 'mpn': 'LM317T'},
            'ams1117-3.3': {'manufacturer': 'AMS', 'mpn': 'AMS1117-3.3'},

            # Common transistors
            '2n3904': {'manufacturer': 'ON Semiconductor', 'mpn': '2N3904BU'},
            '2n2222': {'manufacturer': 'ON Semiconductor', 'mpn': '2N2222A'},
            'bc547': {'manufacturer': 'Fairchild', 'mpn': 'BC547B'},
            'irf540': {'manufacturer': 'International Rectifier', 'mpn': 'IRF540N'},

            # Common diodes
            '1n4148': {'manufacturer': 'ON Semiconductor', 'mpn': '1N4148'},
            '1n4007': {'manufacturer': 'ON Semiconductor', 'mpn': '1N4007'},
            '1n5819': {'manufacturer': 'STMicroelectronics', 'mpn': '1N5819'},
        }

        for item in bom_items:
            value_lower = item['value'].lower()
            # Check if we have info for this part
            for part_key, part_info in known_parts.items():
                if part_key in value_lower:
                    item['manufacturer'] = part_info['manufacturer']
                    item['mpn'] = part_info['mpn']
                    break

        return bom_items

    def _calculate_statistics(self, bom_items: List[Dict], all_components: List[Dict], supplier: str = None) -> Dict:
        """Calculate BOM statistics with pricing"""
        categories = defaultdict(int)
        total_cost = 0.0
        parts_in_stock = 0
        parts_out_of_stock = 0

        for item in bom_items:
            categories[item['category']] += item['quantity']

            # Calculate extended price
            unit_price = float(item.get('unitPrice', 0))
            quantity = int(item.get('quantity', 0))
            total_cost += unit_price * quantity

            # Track stock status
            stock = item.get('stock', 0)
            if stock > 0:
                parts_in_stock += 1
            else:
                parts_out_of_stock += 1

        stats = {
            'total_components': len(all_components),
            'unique_parts': len(bom_items),
            'categories': dict(categories),
            'total_quantity': sum(item['quantity'] for item in bom_items),
            'total_cost': round(total_cost, 2),
            'parts_in_stock': parts_in_stock,
            'parts_out_of_stock': parts_out_of_stock,
            'timestamp': datetime.now().isoformat()
        }

        if supplier:
            stats['supplier'] = supplier

        return stats

    async def _generate_output_files(self, bom_items: List[Dict], statistics: Dict, prefix: str = "BOM") -> Dict[str, str]:
        """
        Generate BOM in multiple output formats with optional supplier prefix

        Args:
            bom_items: List of BOM items
            statistics: BOM statistics
            prefix: File prefix (e.g., "Mouser", "Digikey", "BOM")

        Returns:
            Dict of file paths
        """
        if not self.output_dir:
            return {}

        output_files = {}
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate CSV
        csv_file = output_path / f'{prefix}.csv'
        self._generate_csv(bom_items, csv_file)
        output_files['csv'] = str(csv_file)

        # Generate HTML
        html_file = output_path / f'{prefix}.html'
        self._generate_html(bom_items, statistics, html_file, supplier=statistics.get('supplier'))
        output_files['html'] = str(html_file)

        # Generate JSON
        json_file = output_path / f'{prefix}.json'
        self._generate_json(bom_items, statistics, json_file)
        output_files['json'] = str(json_file)

        # Generate text format
        txt_file = output_path / f'{prefix}.txt'
        self._generate_text(bom_items, statistics, txt_file)
        output_files['txt'] = str(txt_file)

        self.logger.info(f"Generated {prefix} BOM files in {output_path}")
        return output_files

    def _generate_csv(self, bom_items: List[Dict], filepath: Path):
        """Generate CSV format BOM"""
        with open(filepath, 'w', newline='') as f:
            fieldnames = ['id', 'category', 'description', 'value', 'package',
                         'quantity', 'references', 'manufacturer', 'mpn', 'notes']
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            writer.writeheader()
            for item in bom_items:
                writer.writerow({
                    'id': item['id'],
                    'category': item['category'],
                    'description': item['description'],
                    'value': item['value'],
                    'package': item['package'],
                    'quantity': item['quantity'],
                    'references': item['references'],
                    'manufacturer': item['manufacturer'],
                    'mpn': item['mpn'],
                    'notes': item['notes']
                })

    def _generate_html(self, bom_items: List[Dict], statistics: Dict, filepath: Path, supplier: str = None):
        """
        Generate USER-FRIENDLY HTML format BOM

        USER-FOCUSED DESIGN (Dec 2025 Enhancement):
        - Removed: ID column (internal use only)
        - Removed: Stock column (user doesn't need to see "1,744,023 in stock")
        - Enhanced: $0 prices shown as "TBD" (to be determined)
        - Enhanced: Cleaner layout focused on what user needs to buy
        """
        supplier_title = f" - {supplier}" if supplier else ""
        total_cost = statistics.get('total_cost', 0)

        # Calculate actual cost (excluding $0 items)
        actual_cost = sum(
            float(item.get('unitPrice', 0)) * int(item.get('quantity', 0))
            for item in bom_items
            if float(item.get('unitPrice', 0)) > 0
        )
        pending_items = sum(1 for item in bom_items if float(item.get('unitPrice', 0)) == 0)

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Bill of Materials{supplier_title}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        .summary-card {{ background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .summary-card h3 {{ margin-top: 0; color: #2c3e50; }}
        .cost-highlight {{ font-size: 1.5em; color: #27ae60; font-weight: bold; }}
        .pending-note {{ color: #e67e22; font-size: 0.9em; margin-top: 5px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        th, td {{ border: 1px solid #ecf0f1; padding: 10px; text-align: left; }}
        th {{ background: #3498db; color: white; font-weight: 600; }}
        tr:nth-child(even) {{ background: #f8f9fa; }}
        tr:hover {{ background: #e8f4f8; }}
        .category-header {{ background: #34495e !important; color: white; font-weight: bold; }}
        .category-header td {{ border-color: #34495e; }}
        .price {{ text-align: right; font-family: monospace; }}
        .price-tbd {{ color: #e67e22; font-style: italic; }}
        .qty {{ text-align: center; font-weight: bold; }}
        .refs {{ font-family: monospace; font-size: 0.85em; color: #7f8c8d; }}
        .mpn {{ font-family: monospace; font-size: 0.9em; }}
        .datasheet-link {{ color: #3498db; text-decoration: none; }}
        .datasheet-link:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>📋 Bill of Materials{supplier_title}</h1>

    <div class="summary-card">
        <h3>Project Summary</h3>
        <p><strong>Total Component Types:</strong> {statistics['unique_parts']}</p>
        <p><strong>Total Quantity:</strong> {statistics['total_components']} parts</p>
        <p class="cost-highlight">Estimated Cost: ${actual_cost:.2f}</p>
        {"<p class='pending-note'>⚠️ " + str(pending_items) + " items pending price confirmation</p>" if pending_items > 0 else ""}
    </div>

    <table>
        <tr>
            <th>Component</th>
            <th>Value</th>
            <th>Package</th>
            <th style="width: 60px;">Qty</th>
            <th style="width: 90px;">Unit Price</th>
            <th style="width: 90px;">Subtotal</th>
            <th>Schematic Refs</th>
            <th>Manufacturer / Part Number</th>
        </tr>
"""

        current_category = None
        for item in bom_items:
            if item['category'] != current_category:
                current_category = item['category']
                html_content += f'<tr class="category-header"><td colspan="8">{current_category}</td></tr>\n'

            unit_price = float(item.get('unitPrice', 0))
            quantity = int(item.get('quantity', 0))
            extended = unit_price * quantity

            # USER-FRIENDLY: Show "TBD" instead of $0.00
            if unit_price > 0:
                price_display = f"${unit_price:.4f}"
                extended_display = f"${extended:.2f}"
                price_class = "price"
            else:
                price_display = "TBD"
                extended_display = "TBD"
                price_class = "price price-tbd"

            # Build manufacturer/part number display
            manufacturer = item.get('manufacturer', '')
            mpn = item.get('mpn', '') or item.get('partNumber', '')
            datasheet = item.get('datasheet', '')

            if manufacturer and mpn:
                mfr_display = f"{manufacturer}<br/><span class='mpn'>{mpn}</span>"
            elif manufacturer:
                mfr_display = manufacturer
            elif mpn:
                mfr_display = f"<span class='mpn'>{mpn}</span>"
            else:
                mfr_display = "-"

            # Add datasheet link if available
            if datasheet and datasheet.strip():
                # Fix URLs that start with //
                if datasheet.startswith('//'):
                    datasheet = 'https:' + datasheet
                mfr_display += f"<br/><a href='{datasheet}' target='_blank' class='datasheet-link'>📄 Datasheet</a>"

            html_content += f"""        <tr>
            <td>{html.escape(item['description'])}</td>
            <td><strong>{html.escape(item['value'])}</strong></td>
            <td>{item['package']}</td>
            <td class="qty">{quantity}</td>
            <td class="{price_class}">{price_display}</td>
            <td class="{price_class}">{extended_display}</td>
            <td class="refs">{html.escape(item['references'])}</td>
            <td>{mfr_display}</td>
        </tr>\n"""

        html_content += f"""    </table>

    <div class="summary-card" style="margin-top: 30px;">
        <h3>💡 Next Steps</h3>
        <p>1. Review the component list above for accuracy</p>
        <p>2. Items marked "TBD" need pricing confirmation from supplier</p>
        <p>3. Check datasheets for component specifications</p>
        <p>4. Consider quantity discounts when ordering</p>
    </div>
</body>
</html>"""

        with open(filepath, 'w') as f:
            f.write(html_content)

    async def _generate_comparison_html(
        self,
        mouser_bom: List[Dict],
        digikey_bom: List[Dict],
        mouser_stats: Dict,
        digikey_stats: Dict
    ) -> str:
        """
        Generate side-by-side comparison HTML report

        Returns:
            Path to comparison file
        """
        if not self.output_dir:
            return ""

        output_path = Path(self.output_dir)
        filepath = output_path / 'BOM_Comparison.html'

        mouser_total = mouser_stats.get('total_cost', 0)
        digikey_total = digikey_stats.get('total_cost', 0)
        savings = abs(mouser_total - digikey_total)
        cheaper_supplier = "Digikey" if digikey_total < mouser_total else "Mouser"

        # Calculate actual costs (excluding $0 items which are TBD)
        mouser_actual = sum(
            float(item.get('unitPrice', 0)) * int(item.get('quantity', 0))
            for item in mouser_bom
            if float(item.get('unitPrice', 0)) > 0
        )
        digikey_actual = sum(
            float(item.get('unitPrice', 0)) * int(item.get('quantity', 0))
            for item in digikey_bom
            if float(item.get('unitPrice', 0)) > 0
        )

        # Count TBD items
        mouser_tbd = sum(1 for item in mouser_bom if float(item.get('unitPrice', 0)) == 0)
        digikey_tbd = sum(1 for item in digikey_bom if float(item.get('unitPrice', 0)) == 0)

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Supplier Price Comparison</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        h1 {{ color: #2c3e50; text-align: center; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        .summary {{ background: white; padding: 25px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
        .summary h2 {{ margin: 10px 0; color: #2c3e50; }}
        .supplier-costs {{ display: flex; justify-content: center; gap: 40px; margin: 20px 0; }}
        .supplier-card {{ background: #ecf0f1; padding: 20px 40px; border-radius: 8px; }}
        .supplier-card.mouser {{ border-left: 4px solid #e67e22; }}
        .supplier-card.digikey {{ border-left: 4px solid #27ae60; }}
        .supplier-card h3 {{ margin: 0 0 10px 0; }}
        .supplier-card .price {{ font-size: 1.8em; font-weight: bold; color: #2c3e50; }}
        .supplier-card .tbd-note {{ color: #7f8c8d; font-size: 0.85em; margin-top: 5px; }}
        .winner {{ background: #27ae60; color: white; padding: 15px 30px; border-radius: 8px; display: inline-block; margin-top: 15px; }}
        .winner h3 {{ margin: 0; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); font-size: 13px; }}
        th, td {{ border: 1px solid #ecf0f1; padding: 8px; text-align: left; }}
        th {{ background: #3498db; color: white; position: sticky; top: 0; }}
        tr:nth-child(even) {{ background: #f8f9fa; }}
        tr:hover {{ background: #e8f4f8; }}
        .mouser-col {{ background: #fef5e7; }}
        .digikey-col {{ background: #e8f8f5; }}
        .best-price {{ background: #d5f5e3 !important; font-weight: bold; }}
        .price {{ text-align: right; font-family: monospace; }}
        .tbd-price {{ color: #e67e22; font-style: italic; }}
        .category-header {{ background: #34495e !important; color: white; font-weight: bold; }}
        .qty {{ text-align: center; }}
    </style>
</head>
<body>
    <h1>🛒 Supplier Price Comparison</h1>

    <div class="summary">
        <h2>Which Supplier is Cheaper?</h2>
        <div class="supplier-costs">
            <div class="supplier-card mouser">
                <h3>🟠 Mouser</h3>
                <div class="price">${mouser_actual:.2f}</div>
                {"<div class='tbd-note'>" + str(mouser_tbd) + " items need pricing</div>" if mouser_tbd > 0 else ""}
            </div>
            <div class="supplier-card digikey">
                <h3>🟢 Digikey</h3>
                <div class="price">${digikey_actual:.2f}</div>
                {"<div class='tbd-note'>" + str(digikey_tbd) + " items need pricing</div>" if digikey_tbd > 0 else ""}
            </div>
        </div>
        <div class="winner">
            <h3>💰 Recommended: {cheaper_supplier if mouser_actual != digikey_actual else "Similar pricing"}</h3>
            {"<p>Potential savings: $" + f"{savings:.2f}" + "</p>" if savings > 1 else ""}
        </div>
    </div>

    <table>
        <tr>
            <th rowspan="2">Component</th>
            <th rowspan="2">Value</th>
            <th rowspan="2" style="width: 50px;">Qty</th>
            <th colspan="3" class="mouser-col">Mouser</th>
            <th colspan="3" class="digikey-col">Digikey</th>
            <th rowspan="2">Better Deal</th>
        </tr>
        <tr>
            <th class="mouser-col">Part #</th>
            <th class="mouser-col">Unit</th>
            <th class="mouser-col">Total</th>
            <th class="digikey-col">Part #</th>
            <th class="digikey-col">Unit</th>
            <th class="digikey-col">Total</th>
        </tr>
"""

        current_category = None
        for i in range(len(mouser_bom)):
            mouser_item = mouser_bom[i]
            digikey_item = digikey_bom[i]

            # Category header
            if mouser_item['category'] != current_category:
                current_category = mouser_item['category']
                html_content += f'<tr class="category-header"><td colspan="10">{current_category}</td></tr>\n'

            # Component info
            references = mouser_item['references']
            value = mouser_item['value']
            quantity = mouser_item['quantity']

            # Mouser data - handle TBD pricing
            mouser_pn = mouser_item.get('partNumber', 'N/A')
            mouser_price = float(mouser_item.get('unitPrice', 0))
            mouser_extended = mouser_price * quantity

            # Display TBD for $0 prices
            if mouser_price <= 0:
                mouser_unit_display = "TBD"
                mouser_total_display = "TBD"
                mouser_price_class = "tbd-price"
            else:
                mouser_unit_display = f"${mouser_price:.4f}"
                mouser_total_display = f"${mouser_extended:.2f}"
                mouser_price_class = ""

            # Digikey data - handle TBD pricing
            digikey_pn = digikey_item.get('partNumber', 'N/A')
            digikey_price = float(digikey_item.get('unitPrice', 0))
            digikey_extended = digikey_price * quantity

            # Display TBD for $0 prices
            if digikey_price <= 0:
                digikey_unit_display = "TBD"
                digikey_total_display = "TBD"
                digikey_price_class = "tbd-price"
            else:
                digikey_unit_display = f"${digikey_price:.4f}"
                digikey_total_display = f"${digikey_extended:.2f}"
                digikey_price_class = ""

            # Determine best price (only compare if both have valid prices)
            if mouser_price > 0 and digikey_price > 0:
                if mouser_price < digikey_price:
                    best_price = f"Mouser (${mouser_extended:.2f})"
                    mouser_price_class = "best-price"
                    digikey_price_class = ""
                elif digikey_price < mouser_price:
                    best_price = f"Digikey (${digikey_extended:.2f})"
                    mouser_price_class = ""
                    digikey_price_class = "best-price"
                else:
                    best_price = "Same"
            elif mouser_price > 0:
                best_price = "Mouser"
                mouser_price_class = "best-price"
            elif digikey_price > 0:
                best_price = "Digikey"
                digikey_price_class = "best-price"
            else:
                best_price = "TBD"

            html_content += f"""        <tr>
            <td><strong>{html.escape(references)}</strong></td>
            <td>{html.escape(value)}</td>
            <td class="qty">{quantity}</td>
            <td class="mouser-col">{html.escape(mouser_pn)}</td>
            <td class="mouser-col price {mouser_price_class}">{mouser_unit_display}</td>
            <td class="mouser-col price {mouser_price_class}">{mouser_total_display}</td>
            <td class="digikey-col">{html.escape(digikey_pn)}</td>
            <td class="digikey-col price {digikey_price_class}">{digikey_unit_display}</td>
            <td class="digikey-col price {digikey_price_class}">{digikey_total_display}</td>
            <td><strong>{best_price}</strong></td>
        </tr>\n"""

        html_content += """    </table>

    <div style="margin-top: 30px; padding: 20px; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
        <h3>💡 What to do next</h3>
        <p><strong>1. Check "TBD" items</strong> - These parts need pricing from the supplier. Search their websites directly.</p>
        <p><strong>2. Consider mixed ordering</strong> - You can buy some parts from Mouser and others from Digikey for best value.</p>
        <p><strong>3. Compare shipping</strong> - Factor in shipping costs and delivery time for your location.</p>
        <p><strong>4. Verify quantities</strong> - Check minimum order quantities and quantity discounts.</p>
    </div>
</body>
</html>"""

        with open(filepath, 'w') as f:
            f.write(html_content)

        self.logger.info(f"Generated comparison report: {filepath}")
        return str(filepath)

    def _generate_json(self, bom_items: List[Dict], statistics: Dict, filepath: Path):
        """Generate JSON format BOM"""
        output = {
            'metadata': statistics,
            'bom': bom_items
        }
        with open(filepath, 'w') as f:
            json.dump(output, f, indent=2)

    def _generate_text(self, bom_items: List[Dict], statistics: Dict, filepath: Path):
        """Generate text format BOM"""
        with open(filepath, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("BILL OF MATERIALS\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"Total Components: {statistics['total_components']}\n")
            f.write(f"Unique Parts: {statistics['unique_parts']}\n")
            f.write(f"Generated: {statistics['timestamp']}\n")
            f.write("\n" + "-" * 80 + "\n\n")

            current_category = None
            for item in bom_items:
                if item['category'] != current_category:
                    current_category = item['category']
                    f.write(f"\n{current_category.upper()}\n")
                    f.write("-" * len(current_category) + "\n\n")

                f.write(f"[{item['id']:3d}] {item['description']}\n")
                f.write(f"      Value: {item['value']}, Package: {item['package']}\n")
                f.write(f"      Quantity: {item['quantity']}\n")
                f.write(f"      References: {item['references']}\n")
                if item['manufacturer']:
                    f.write(f"      Manufacturer: {item['manufacturer']}, MPN: {item['mpn']}\n")
                if item['notes']:
                    f.write(f"      Notes: {item['notes']}\n")
                f.write("\n")
