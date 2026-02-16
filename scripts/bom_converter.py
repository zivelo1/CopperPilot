#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

# -*- coding: utf-8 -*-
"""
BOM (Bill of Materials) Converter v1.0 - Professional Component Documentation
=============================================================================
Converts components.csv into comprehensive, production-ready BOM files with:
- Professional formatting and categorization
- Complete component specifications
- Manufacturer part numbers (where available)
- Quantity consolidation and optimization
- Multiple export formats (Excel, CSV, HTML, JSON)
- Cost estimation placeholders
- Assembly notes and special requirements

Author: Professional EE
Version: 1.0.0
Date: 2025-01-14
"""

import csv
import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict, OrderedDict
import logging
import argparse
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# COMPONENT DATABASE WITH TYPICAL PARTS
# ============================================================================

COMPONENT_DATABASE = {
    # Voltage Regulators
    'LM7805': {'category': 'Voltage Regulator', 'package': 'TO-220', 'manufacturer': 'STMicroelectronics', 'mpn': 'L7805CV'},
    'LM7812': {'category': 'Voltage Regulator', 'package': 'TO-220', 'manufacturer': 'STMicroelectronics', 'mpn': 'L7812CV'},
    'LM7912': {'category': 'Voltage Regulator', 'package': 'TO-220', 'manufacturer': 'STMicroelectronics', 'mpn': 'L7912CV'},
    'LM2596': {'category': 'Switching Regulator', 'package': 'TO-263', 'manufacturer': 'Texas Instruments', 'mpn': 'LM2596S-ADJ'},
    
    # Microcontrollers
    'STM32H743ZIT6': {'category': 'Microcontroller', 'package': 'LQFP-144', 'manufacturer': 'STMicroelectronics', 'mpn': 'STM32H743ZIT6'},
    'STM32F103C8T6': {'category': 'Microcontroller', 'package': 'LQFP-48', 'manufacturer': 'STMicroelectronics', 'mpn': 'STM32F103C8T6'},
    
    # Op Amps
    'OPA2134': {'category': 'Op Amp', 'package': 'DIP-8', 'manufacturer': 'Texas Instruments', 'mpn': 'OPA2134PA'},
    'OPA2192': {'category': 'Op Amp', 'package': 'SOIC-8', 'manufacturer': 'Texas Instruments', 'mpn': 'OPA2192ID'},
    'AD8065': {'category': 'Op Amp', 'package': 'SOIC-8', 'manufacturer': 'Analog Devices', 'mpn': 'AD8065ARZ'},
    
    # DDS ICs
    'AD9833': {'category': 'DDS IC', 'package': 'MSOP-10', 'manufacturer': 'Analog Devices', 'mpn': 'AD9833BRMZ'},
    'AD9910': {'category': 'DDS IC', 'package': 'TQFP-100', 'manufacturer': 'Analog Devices', 'mpn': 'AD9910BSVZ'},
    
    # PWM Controllers
    'UC3845': {'category': 'PWM Controller', 'package': 'DIP-8', 'manufacturer': 'Texas Instruments', 'mpn': 'UC3845N'},
    'UCC28019A': {'category': 'PFC Controller', 'package': 'SOIC-8', 'manufacturer': 'Texas Instruments', 'mpn': 'UCC28019ADR'},
    
    # Communication ICs
    'FT232RL': {'category': 'USB UART', 'package': 'SSOP-28', 'manufacturer': 'FTDI', 'mpn': 'FT232RL-REEL'},
    'MAX3232': {'category': 'RS232 Transceiver', 'package': 'SOIC-16', 'manufacturer': 'Maxim', 'mpn': 'MAX3232CSE+'},
    'LAN8742A': {'category': 'Ethernet PHY', 'package': 'QFN-24', 'manufacturer': 'Microchip', 'mpn': 'LAN8742A-CZ'},
    
    # ADCs
    'ADS131M08': {'category': 'ADC', 'package': 'TQFP-32', 'manufacturer': 'Texas Instruments', 'mpn': 'ADS131M08IPBSR'},
    
    # Memory
    'IS62WV51216BLL': {'category': 'SRAM', 'package': 'TSOP-44', 'manufacturer': 'ISSI', 'mpn': 'IS62WV51216BLL-55TLI'},
    
    # Controllers
    'PCF8574': {'category': 'I/O Expander', 'package': 'DIP-16', 'manufacturer': 'NXP', 'mpn': 'PCF8574N'},
    'EMC2301': {'category': 'Fan Controller', 'package': 'MSOP-8', 'manufacturer': 'Microchip', 'mpn': 'EMC2301-1-AIZL-TR'},
    'TMP102': {'category': 'Temperature Sensor', 'package': 'SOT-563', 'manufacturer': 'Texas Instruments', 'mpn': 'TMP102AIDRLT'},
    
    # VGAs
    'AD8338': {'category': 'VGA', 'package': 'LFCSP-16', 'manufacturer': 'Analog Devices', 'mpn': 'AD8338ACPZ'},
    'AD8367': {'category': 'VGA', 'package': 'LFCSP-24', 'manufacturer': 'Analog Devices', 'mpn': 'AD8367ARUZ'},
}


class BOMConverter:
    """Professional BOM converter for electronic circuits"""
    
    def __init__(self, input_file: str, output_dir: str):
        """
        Initialize BOM converter
        
        Args:
            input_file: Path to components.csv file
            output_dir: Directory for output BOM files
        """
        self.input_file = Path(input_file)
        self.output_dir = Path(output_dir)
        self.components = []
        self.bom_data = OrderedDict()
        self.statistics = {
            'total_components': 0,
            'unique_parts': 0,
            'categories': set(),
            'modules': set(),
            'total_quantity': defaultdict(int)
        }
        
    def read_components(self) -> bool:
        """Read and parse the components CSV file"""
        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                row_num = 1
                for row in reader:
                    row_num += 1
                    # Check for Reference or RefDes column
                    ref = row.get('Reference') or row.get('RefDes')

                    # VALIDATION: Skip completely empty rows
                    if not ref and not row.get('Type') and not row.get('Value'):
                        continue

                    # VALIDATION: Warn about components with empty reference designators
                    if not ref or not ref.strip():
                        logger.warning(f"Row {row_num}: Component with empty reference designator - Type={row.get('Type')}, Value={row.get('Value')} - SKIPPING")
                        continue

                    # Normalize column names
                    normalized_row = {
                        'RefDes': ref.strip(),
                        'Type': row.get('Type', ''),
                        'Value': row.get('Value', ''),
                        'Package': row.get('Package', ''),
                        'Module': row.get('Module', ''),
                        'Circuit': row.get('Circuit', ''),
                        'Notes': row.get('Notes', ''),
                        'Part Number': row.get('Part Number', '')
                    }
                    self.components.append(normalized_row)
                    self.statistics['total_components'] += 1
                    self.statistics['modules'].add(normalized_row['Module'] or 'Unknown')

            logger.info(f"Read {self.statistics['total_components']} components from {self.input_file}")
            return True

        except Exception as e:
            logger.error(f"Error reading components file: {e}")
            return False
    
    def categorize_component(self, comp_type: str) -> str:
        """Categorize component based on type"""
        type_lower = comp_type.lower()
        
        # Passive components
        if 'resistor' in type_lower:
            return 'Resistors'
        elif 'capacitor' in type_lower:
            return 'Capacitors'
        elif 'inductor' in type_lower:
            return 'Inductors'
        elif 'crystal' in type_lower:
            return 'Crystals/Oscillators'
        elif 'transformer' in type_lower:
            return 'Transformers'
        
        # Active components
        elif 'diode' in type_lower or 'led' in type_lower or 'tvs' in type_lower:
            return 'Diodes/LEDs'
        elif 'transistor' in type_lower or 'mosfet' in type_lower or 'bjt' in type_lower:
            return 'Transistors/MOSFETs'
        elif 'op_amp' in type_lower or 'amplifier' in type_lower:
            return 'Operational Amplifiers'
        elif 'voltage_regulator' in type_lower or 'regulator' in type_lower:
            return 'Voltage Regulators'
        elif 'microcontroller' in type_lower or 'mcu' in type_lower:
            return 'Microcontrollers'
        elif 'bridge_rectifier' in type_lower:
            return 'Power Components'
        
        # ICs
        elif 'ic' in type_lower or 'controller' in type_lower or 'driver' in type_lower:
            return 'Integrated Circuits'
        elif 'adc' in type_lower or 'dac' in type_lower or 'dds' in type_lower:
            return 'Data Converters'
        elif 'memory' in type_lower or 'sram' in type_lower or 'flash' in type_lower:
            return 'Memory'
        elif 'phy' in type_lower or 'transceiver' in type_lower or 'ethernet' in type_lower:
            return 'Communication ICs'
        
        # Electromechanical
        elif 'connector' in type_lower or 'jack' in type_lower or 'header' in type_lower:
            return 'Connectors'
        elif 'switch' in type_lower or 'button' in type_lower:
            return 'Switches/Buttons'
        elif 'relay' in type_lower:
            return 'Relays'
        elif 'fuse' in type_lower:
            return 'Protection Devices'
        elif 'varistor' in type_lower or 'mov' in type_lower:
            return 'Protection Devices'
        elif 'potentiometer' in type_lower or 'pot' in type_lower:
            return 'Potentiometers'
        elif 'display' in type_lower or 'lcd' in type_lower:
            return 'Displays'
        elif 'fan' in type_lower:
            return 'Thermal Management'
        elif 'sensor' in type_lower:
            return 'Sensors'
        elif 'vga' in type_lower:
            return 'Variable Gain Amplifiers'
        
        else:
            return 'Miscellaneous'
    
    def get_package_from_value(self, comp_type: str, value: str) -> str:
        """Estimate package based on component type and value"""
        type_lower = comp_type.lower()
        
        if 'resistor' in type_lower:
            # Parse power rating if present
            if 'W' in value.upper():
                power = re.search(r'(\d+(?:\.\d+)?)\s*W', value.upper())
                if power:
                    watts = float(power.group(1))
                    if watts >= 5:
                        return '2512'
                    elif watts >= 2:
                        return '2010'
                    elif watts >= 1:
                        return '1206'
                    elif watts >= 0.5:
                        return '0805'
                    elif watts >= 0.25:
                        return '0603'
            
            # Default SMD for most resistors
            return '0805'
        
        elif 'capacitor' in type_lower:
            # Parse capacitance value
            if 'uF' in value or 'µF' in value:
                cap_value = re.search(r'(\d+(?:\.\d+)?)', value)
                if cap_value:
                    microfarads = float(cap_value.group(1))
                    if microfarads >= 100:
                        return 'Electrolytic'
                    elif microfarads >= 10:
                        return '1210'
                    elif microfarads >= 1:
                        return '0805'
            elif 'nF' in value:
                return '0603'
            elif 'pF' in value:
                return '0402'
            
            return '0805'
        
        elif 'inductor' in type_lower:
            # Check for current rating or inductance
            if 'mH' in value:
                return 'Through-hole'
            elif 'uH' in value or 'µH' in value:
                ind_value = re.search(r'(\d+(?:\.\d+)?)', value)
                if ind_value:
                    microhenries = float(ind_value.group(1))
                    if microhenries >= 100:
                        return 'SMD Power'
                    else:
                        return '1210'
            elif 'nH' in value:
                return '0603'
            
            return 'SMD'
        
        elif 'mosfet' in type_lower:
            # Check voltage rating
            if 'V' in value:
                voltage = re.search(r'(\d+)\s*V', value)
                if voltage and int(voltage.group(1)) >= 200:
                    return 'TO-220'
                else:
                    return 'SOT-23'
            return 'TO-220'
        
        elif 'diode' in type_lower:
            # Check current/voltage rating
            if 'A' in value and not 'CA' in value:
                current = re.search(r'(\d+)\s*A', value)
                if current and int(current.group(1)) >= 3:
                    return 'DO-201'
                else:
                    return 'SOD-123'
            return 'SOD-123'
        
        else:
            # Default packages for other types
            if 'connector' in type_lower:
                return 'Through-hole'
            elif 'crystal' in type_lower:
                return 'HC-49'
            elif 'switch' in type_lower:
                return 'Through-hole'
            elif 'led' in type_lower:
                return '0805'
            elif 'display' in type_lower:
                return 'Module'
            else:
                return 'SMD'
    
    def process_components(self):
        """
        Process components and create BOM structure.

        TC #95 FIX: Properly groups components by (type, value, package) to avoid
        merging components with different packages. This ensures accurate BOM entries.
        """

        # Group components by type, value, AND package
        component_groups = defaultdict(list)

        for comp in self.components:
            ref_des = comp.get('RefDes', '')
            comp_type = comp.get('Type', '')
            value = comp.get('Value', '')
            package = comp.get('Package', '')  # TC #95: Include package in grouping
            module = comp.get('Module', '')
            circuit = comp.get('Circuit', '')
            notes = comp.get('Notes', '')

            # Get category
            category = self.categorize_component(comp_type)
            self.statistics['categories'].add(category)

            # Look up in database for known parts
            part_info = COMPONENT_DATABASE.get(value, {})

            # Determine package (TC #95: Use provided package if available)
            if not package or package.strip() == '':
                if part_info:
                    package = part_info.get('package', self.get_package_from_value(comp_type, value))
                else:
                    package = self.get_package_from_value(comp_type, value)

            # TC #95 FIX: Create unique key including package to avoid incorrect merging
            # Two 10k resistors in 0402 and 0603 packages are different BOM items!
            group_key = f"{comp_type}_{value}_{package}"

            # TC #95: Get manufacturer/MPN from database (package already determined above)
            if part_info:
                manufacturer = part_info.get('manufacturer', 'Generic')
                mpn = part_info.get('mpn', '')
            else:
                manufacturer = 'Generic'
                mpn = ''
            
            # Add to group
            component_groups[group_key].append({
                'ref_des': ref_des,
                'type': comp_type,
                'value': value,
                'category': category,
                'package': package,
                'manufacturer': manufacturer,
                'mpn': mpn,
                'module': module,
                'circuit': circuit,
                'notes': notes
            })
        
        # Create BOM entries
        bom_id = 1
        for group_key, components in component_groups.items():
            # Sort reference designators
            ref_des_list = sorted([c['ref_des'] for c in components])
            ref_des_str = self.format_ref_des_list(ref_des_list)
            
            # Get representative component
            rep_comp = components[0]
            
            # Calculate quantity
            quantity = len(components)
            self.statistics['total_quantity'][rep_comp['category']] += quantity
            
            # Create BOM entry
            bom_entry = OrderedDict([
                ('Item', bom_id),
                ('Quantity', quantity),
                ('Reference', ref_des_str),
                ('Value', rep_comp['value']),
                ('Type', rep_comp['type']),
                ('Category', rep_comp['category']),
                ('Package', rep_comp['package']),
                ('Manufacturer', rep_comp['manufacturer']),
                ('MPN', rep_comp['mpn']),
                ('Description', self.generate_description(rep_comp)),
                ('Notes', rep_comp['notes']),
                ('Unit Price', ''),  # Placeholder for pricing
                ('Ext. Price', ''),  # Placeholder for extended pricing
                ('Supplier', ''),    # Placeholder for supplier
                ('Supplier PN', '')  # Placeholder for supplier part number
            ])
            
            self.bom_data[bom_id] = bom_entry
            bom_id += 1
        
        self.statistics['unique_parts'] = len(self.bom_data)
        logger.info(f"Processed {self.statistics['total_components']} components into {self.statistics['unique_parts']} unique BOM items")
    
    def format_ref_des_list(self, ref_des_list: List[str]) -> str:
        """Format reference designator list with ranges"""
        if not ref_des_list:
            return ''
        
        if len(ref_des_list) == 1:
            return ref_des_list[0]
        
        # Group by prefix
        groups = defaultdict(list)
        for ref in ref_des_list:
            match = re.match(r'([A-Z]+)(\d+)', ref)
            if match:
                prefix = match.group(1)
                number = int(match.group(2))
                groups[prefix].append(number)
        
        # Format each group
        formatted = []
        for prefix, numbers in sorted(groups.items()):
            numbers = sorted(numbers)
            
            # Find ranges
            ranges = []
            start = numbers[0]
            end = numbers[0]
            
            for i in range(1, len(numbers)):
                if numbers[i] == end + 1:
                    end = numbers[i]
                else:
                    if start == end:
                        ranges.append(f"{prefix}{start}")
                    else:
                        ranges.append(f"{prefix}{start}-{prefix}{end}")
                    start = numbers[i]
                    end = numbers[i]
            
            # Add last range
            if start == end:
                ranges.append(f"{prefix}{start}")
            else:
                ranges.append(f"{prefix}{start}-{prefix}{end}")
            
            formatted.extend(ranges)
        
        return ', '.join(formatted)
    
    def generate_description(self, comp: Dict) -> str:
        """Generate component description"""
        comp_type = comp['type'].replace('_', ' ').title()
        value = comp['value']
        package = comp['package']
        
        # Build description
        desc_parts = []
        
        if comp_type:
            desc_parts.append(comp_type)
        
        if value and value != comp_type:
            desc_parts.append(value)
        
        if package and package not in ['SMD', 'Through-hole']:
            desc_parts.append(f"({package})")
        
        # Add special attributes based on type
        if 'resistor' in comp['type'].lower():
            # Add tolerance if standard value
            desc_parts.append("±5%")
        elif 'capacitor' in comp['type'].lower():
            # Add voltage rating if not specified
            if 'V' not in value:
                if 'uF' in value or 'µF' in value:
                    desc_parts.append("25V")
                else:
                    desc_parts.append("50V")
        
        return ' '.join(desc_parts)
    
    def export_csv(self):
        """Export BOM as CSV file"""
        csv_path = self.output_dir / 'BOM.csv'
        
        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                if self.bom_data:
                    fieldnames = list(self.bom_data[1].keys())
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    
                    # Write header
                    writer.writeheader()
                    
                    # Write data
                    for entry in self.bom_data.values():
                        writer.writerow(entry)
            
            logger.info(f"Exported CSV BOM to {csv_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}")
            return False
    
    def export_html(self):
        """Export BOM as HTML file with professional formatting"""
        html_path = self.output_dir / 'BOM.html'
        
        # Create HTML content
        html = []
        html.append('<!DOCTYPE html>')
        html.append('<html lang="en">')
        html.append('<head>')
        html.append('    <meta charset="UTF-8">')
        html.append('    <meta name="viewport" content="width=device-width, initial-scale=1.0">')
        html.append('    <title>Bill of Materials</title>')
        html.append('    <style>')
        html.append('        body { font-family: Arial, sans-serif; margin: 20px; }')
        html.append('        h1 { color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }')
        html.append('        h2 { color: #666; margin-top: 30px; }')
        html.append('        table { border-collapse: collapse; width: 100%; margin: 20px 0; }')
        html.append('        th { background-color: #4CAF50; color: white; padding: 12px; text-align: left; }')
        html.append('        td { padding: 10px; border-bottom: 1px solid #ddd; }')
        html.append('        tr:hover { background-color: #f5f5f5; }')
        html.append('        .category-header { background-color: #e8f5e9; font-weight: bold; }')
        html.append('        .summary { background-color: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }')
        html.append('        .footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #ccc; color: #666; font-size: 0.9em; }')
        html.append('    </style>')
        html.append('</head>')
        html.append('<body>')
        
        # Title and project info
        project_name = self.input_file.parent.parent.name
        html.append(f'    <h1>Bill of Materials - {project_name}</h1>')
        html.append(f'    <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>')
        
        # Summary statistics
        html.append('    <div class="summary">')
        html.append('        <h2>Summary</h2>')
        html.append(f'        <p><strong>Total Components:</strong> {self.statistics["total_components"]}</p>')
        html.append(f'        <p><strong>Unique Parts:</strong> {self.statistics["unique_parts"]}</p>')
        html.append(f'        <p><strong>Categories:</strong> {len(self.statistics["categories"])}</p>')
        html.append(f'        <p><strong>Modules:</strong> {len(self.statistics["modules"])}</p>')
        html.append('    </div>')
        
        # BOM table grouped by category
        html.append('    <h2>Component List</h2>')
        
        # Group BOM by category
        categories = defaultdict(list)
        for entry in self.bom_data.values():
            categories[entry['Category']].append(entry)
        
        for category in sorted(categories.keys()):
            html.append(f'    <h3>{category}</h3>')
            html.append('    <table>')
            html.append('        <thead>')
            html.append('            <tr>')
            html.append('                <th>Item</th>')
            html.append('                <th>Qty</th>')
            html.append('                <th>Reference</th>')
            html.append('                <th>Value</th>')
            html.append('                <th>Description</th>')
            html.append('                <th>Package</th>')
            html.append('                <th>Manufacturer</th>')
            html.append('                <th>MPN</th>')
            html.append('            </tr>')
            html.append('        </thead>')
            html.append('        <tbody>')
            
            for entry in categories[category]:
                html.append('            <tr>')
                html.append(f'                <td>{entry["Item"]}</td>')
                html.append(f'                <td>{entry["Quantity"]}</td>')
                html.append(f'                <td>{entry["Reference"]}</td>')
                html.append(f'                <td>{entry["Value"]}</td>')
                html.append(f'                <td>{entry["Description"]}</td>')
                html.append(f'                <td>{entry["Package"]}</td>')
                html.append(f'                <td>{entry["Manufacturer"]}</td>')
                html.append(f'                <td>{entry["MPN"]}</td>')
                html.append('            </tr>')
            
            html.append('        </tbody>')
            html.append('    </table>')
        
        # Component count by category
        html.append('    <h2>Component Count by Category</h2>')
        html.append('    <table>')
        html.append('        <thead>')
        html.append('            <tr>')
        html.append('                <th>Category</th>')
        html.append('                <th>Quantity</th>')
        html.append('            </tr>')
        html.append('        </thead>')
        html.append('        <tbody>')
        
        for category, count in sorted(self.statistics['total_quantity'].items()):
            html.append('            <tr>')
            html.append(f'                <td>{category}</td>')
            html.append(f'                <td>{count}</td>')
            html.append('            </tr>')
        
        html.append('        </tbody>')
        html.append('    </table>')
        
        # Footer
        html.append('    <div class="footer">')
        html.append('        <p>Generated by BOM Converter v1.0</p>')
        html.append('        <p>Part of the Circuit Design Automation System</p>')
        html.append('    </div>')
        
        html.append('</body>')
        html.append('</html>')
        
        # Write HTML file
        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(html))
            
            logger.info(f"Exported HTML BOM to {html_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting HTML: {e}")
            return False
    
    def export_json(self):
        """Export BOM as JSON file"""
        json_path = self.output_dir / 'BOM.json'
        
        # Create JSON structure
        json_data = {
            'metadata': {
                'project': str(self.input_file.parent.parent.name),
                'generated': datetime.now().isoformat(),
                'version': '1.0',
                'total_components': self.statistics['total_components'],
                'unique_parts': self.statistics['unique_parts']
            },
            'statistics': {
                'categories': list(self.statistics['categories']),
                'modules': list(self.statistics['modules']),
                'quantity_by_category': dict(self.statistics['total_quantity'])
            },
            'bom': []
        }
        
        # Add BOM entries
        for entry in self.bom_data.values():
            json_data['bom'].append(dict(entry))
        
        # Write JSON file
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2)
            
            logger.info(f"Exported JSON BOM to {json_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting JSON: {e}")
            return False
    
    def export_text(self):
        """Export BOM as formatted text file"""
        txt_path = self.output_dir / 'BOM.txt'
        
        lines = []
        lines.append('=' * 80)
        lines.append(f'BILL OF MATERIALS - {self.input_file.parent.parent.name}')
        lines.append('=' * 80)
        lines.append(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        lines.append('')
        lines.append('SUMMARY')
        lines.append('-' * 40)
        lines.append(f'Total Components: {self.statistics["total_components"]}')
        lines.append(f'Unique Parts: {self.statistics["unique_parts"]}')
        lines.append(f'Categories: {len(self.statistics["categories"])}')
        lines.append(f'Modules: {len(self.statistics["modules"])}')
        lines.append('')
        lines.append('=' * 80)
        lines.append('COMPONENT LIST')
        lines.append('=' * 80)
        
        # Group by category
        categories = defaultdict(list)
        for entry in self.bom_data.values():
            categories[entry['Category']].append(entry)
        
        for category in sorted(categories.keys()):
            lines.append('')
            lines.append(f'[{category}]')
            lines.append('-' * 40)
            
            for entry in categories[category]:
                lines.append(f"Item {entry['Item']:3d}: {entry['Quantity']:3d}x {entry['Value']:20s} - {entry['Description']}")
                lines.append(f"         Ref: {entry['Reference']}")
                if entry['MPN']:
                    lines.append(f"         MPN: {entry['MPN']}")
                lines.append('')
        
        lines.append('=' * 80)
        lines.append('COMPONENT COUNT BY CATEGORY')
        lines.append('=' * 80)
        
        for category, count in sorted(self.statistics['total_quantity'].items()):
            lines.append(f'{category:30s}: {count:4d}')
        
        lines.append('')
        lines.append('=' * 80)
        lines.append('Generated by BOM Converter v1.0')
        lines.append('Part of the Circuit Design Automation System')
        lines.append('=' * 80)
        
        # Write text file
        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            logger.info(f"Exported text BOM to {txt_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting text: {e}")
            return False
    
    def convert(self) -> bool:
        """Main conversion process"""
        logger.info(f"Starting BOM conversion for {self.input_file}")
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Read components
        if not self.read_components():
            return False
        
        # Process into BOM
        self.process_components()
        
        # Export all formats
        success = True
        success &= self.export_csv()
        success &= self.export_html()
        success &= self.export_json()
        success &= self.export_text()
        
        if success:
            logger.info("BOM conversion completed successfully!")
            logger.info(f"Output files in: {self.output_dir}")
        else:
            logger.warning("BOM conversion completed with some errors")
        
        return success


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Convert components.csv to professional BOM')
    parser.add_argument('input_file', help='Path to components.csv file')
    parser.add_argument('-o', '--output', help='Output directory (default: next to lowlevel folder)', 
                       default=None)
    
    args = parser.parse_args()
    
    # Determine output directory
    input_path = Path(args.input_file)
    if args.output:
        output_dir = Path(args.output)
    else:
        # Create 'bom' folder next to 'lowlevel' folder
        if 'lowlevel' in input_path.parts:
            output_dir = input_path.parent.parent / 'bom'
        else:
            output_dir = input_path.parent / 'bom'
    
    # Run conversion
    converter = BOMConverter(args.input_file, output_dir)
    success = converter.convert()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())