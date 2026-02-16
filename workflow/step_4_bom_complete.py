# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Step 4: Complete BOM Generation Implementation
Ready for production use without AI initially
"""

import json
import csv
import re
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import html
from workflow.mouser_api import MouserAPI

class Step4BOMGeneration:
    """
    Complete BOM Generation implementation that works without AI
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.output_dir = None
        self.mouser_api = MouserAPI()

    def extract_components(self, circuits: List[Dict]) -> List[Dict]:
        """Extract all components from circuits"""
        components = []

        for circuit in circuits:
            circuit_name = circuit.get('name', 'Unknown')

            # Extract components from the circuit
            for comp in circuit.get('components', []):
                component = {
                    'reference': comp.get('id', ''),
                    'type': comp.get('type', ''),
                    'value': comp.get('value', ''),
                    'package': comp.get('package', 'SMD'),
                    'circuit': circuit_name,
                    'specifications': comp.get('specifications', {}),
                    'quantity': 1
                }
                components.append(component)

        return components

    def group_components(self, components: List[Dict]) -> List[Dict]:
        """Group identical components and count quantities with Mouser API integration"""
        grouped = defaultdict(lambda: {
            'quantity': 0,
            'references': [],
            'circuits': set()
        })

        for comp in components:
            # Create a key for grouping (type + value + package)
            key = f"{comp['type']}_{comp['value']}_{comp['package']}"

            grouped[key]['quantity'] += comp['quantity']
            grouped[key]['references'].append(comp['reference'])
            grouped[key]['circuits'].add(comp['circuit'])

            # Store the component data (will be same for all grouped items)
            if 'type' not in grouped[key]:
                grouped[key].update({
                    'type': comp['type'],
                    'value': comp['value'],
                    'package': comp['package'],
                    'specifications': comp['specifications']
                })

        # Convert to list format and enhance with Mouser data
        bom_list = []
        for key, data in grouped.items():
            data['circuits'] = list(data['circuits'])  # Convert set to list

            # Try to find real part from Mouser
            mouser_part = self.mouser_api.find_best_match(
                data['type'],
                data['value'],
                data['package']
            )

            if mouser_part:
                # Use real Mouser data
                data['part_number'] = mouser_part['part_number']
                data['manufacturer'] = mouser_part['manufacturer']
                data['unit_price'] = mouser_part['unit_price']
                data['mouser_part_number'] = mouser_part['mouser_part_number']
                data['stock'] = mouser_part['stock']
                data['datasheet'] = mouser_part.get('datasheet', '')
            else:
                # Fallback to estimates
                data['part_number'] = f"{data['type']}-{data['value']}"
                data['manufacturer'] = 'Generic'
                data['unit_price'] = self._estimate_price(data['type'], data['value'])
                data['mouser_part_number'] = ''
                data['stock'] = 0
                data['datasheet'] = ''

            data['total_price'] = data['unit_price'] * data['quantity']
            bom_list.append(data)

        return sorted(bom_list, key=lambda x: (x['type'], x['value']))

    def _estimate_price(self, component_type: str, value: str) -> float:
        """Estimate component price based on type (placeholder)"""
        # Basic price estimation
        price_map = {
            'RESISTOR': 0.02,
            'CAPACITOR': 0.05,
            'INDUCTOR': 0.50,
            'LED': 0.10,
            'TRANSISTOR': 0.15,
            'MOSFET': 0.75,
            'IC': 2.50,
            'CONNECTOR': 1.00,
            'CRYSTAL': 0.50,
            'DIODE': 0.10,
            'OPAMP': 1.50,
            'REGULATOR': 0.75
        }

        for key in price_map:
            if key in component_type.upper():
                return price_map[key]

        return 0.50  # Default price

    def generate_csv(self, bom_list: List[Dict], output_path: str):
        """Generate CSV format BOM"""
        csv_path = Path(output_path) / 'bom.csv'

        with open(csv_path, 'w', newline='') as csvfile:
            fieldnames = [
                'Item', 'Quantity', 'References', 'Type', 'Value',
                'Package', 'Manufacturer', 'Part Number',
                'Unit Price', 'Total Price', 'Circuits'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for idx, item in enumerate(bom_list, 1):
                writer.writerow({
                    'Item': idx,
                    'Quantity': item['quantity'],
                    'References': ', '.join(item['references']),
                    'Type': item['type'],
                    'Value': item['value'],
                    'Package': item['package'],
                    'Manufacturer': item['manufacturer'],
                    'Part Number': item['part_number'],
                    'Unit Price': f"${item['unit_price']:.2f}",
                    'Total Price': f"${item['total_price']:.2f}",
                    'Circuits': ', '.join(item['circuits'])
                })

        return str(csv_path)

    def generate_html(self, bom_list: List[Dict], output_path: str):
        """Generate HTML format BOM"""
        html_path = Path(output_path) / 'bom.html'

        total_cost = sum(item['total_price'] for item in bom_list)
        total_parts = sum(item['quantity'] for item in bom_list)

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Bill of Materials - {self.project_id}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        .summary {{ background: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ background: #667eea; color: white; padding: 10px; text-align: left; }}
        td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
        tr:hover {{ background: #f5f5f5; }}
        .total-row {{ font-weight: bold; background: #f0f0f0; }}
    </style>
</head>
<body>
    <h1>Bill of Materials</h1>
    <div class="summary">
        <p><strong>Project:</strong> {self.project_id}</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Total Components:</strong> {total_parts}</p>
        <p><strong>Unique Parts:</strong> {len(bom_list)}</p>
        <p><strong>Estimated Total Cost:</strong> ${total_cost:.2f}</p>
    </div>

    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Qty</th>
                <th>References</th>
                <th>Type</th>
                <th>Value</th>
                <th>Package</th>
                <th>Manufacturer</th>
                <th>Part Number</th>
                <th>Unit Price</th>
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
"""

        for idx, item in enumerate(bom_list, 1):
            refs = html.escape(', '.join(item['references'][:5]))
            if len(item['references']) > 5:
                refs += '...'

            html_content += f"""            <tr>
                <td>{idx}</td>
                <td>{item['quantity']}</td>
                <td title="{html.escape(', '.join(item['references']))}">{refs}</td>
                <td>{html.escape(item['type'])}</td>
                <td>{html.escape(item['value'])}</td>
                <td>{html.escape(item['package'])}</td>
                <td>{html.escape(item['manufacturer'])}</td>
                <td>{html.escape(item['part_number'])}</td>
                <td>${item['unit_price']:.2f}</td>
                <td>${item['total_price']:.2f}</td>
            </tr>
"""

        html_content += f"""        </tbody>
        <tfoot>
            <tr class="total-row">
                <td colspan="8">TOTAL</td>
                <td colspan="2">${total_cost:.2f}</td>
            </tr>
        </tfoot>
    </table>
</body>
</html>"""

        with open(html_path, 'w') as f:
            f.write(html_content)

        return str(html_path)

    def generate_json(self, bom_list: List[Dict], output_path: str):
        """Generate JSON format BOM"""
        json_path = Path(output_path) / 'bom.json'

        total_cost = sum(item['total_price'] for item in bom_list)

        bom_data = {
            'project_id': self.project_id,
            'generated': datetime.now().isoformat(),
            'summary': {
                'total_components': sum(item['quantity'] for item in bom_list),
                'unique_parts': len(bom_list),
                'total_cost': total_cost
            },
            'components': bom_list
        }

        with open(json_path, 'w') as f:
            json.dump(bom_data, f, indent=2, default=str)

        return str(json_path)

    async def process(self, circuits: List[Dict], output_dir: str = None) -> Dict[str, Any]:
        """
        Main processing function for Step 4
        """
        try:
            self.output_dir = Path(output_dir) if output_dir else Path('output')
            bom_dir = self.output_dir / 'bom'
            bom_dir.mkdir(parents=True, exist_ok=True)

            # Extract components from all circuits
            components = self.extract_components(circuits)

            if not components:
                return {
                    'success': False,
                    'message': 'No components found in circuits'
                }

            # Group components
            bom_list = self.group_components(components)

            # Generate output formats
            csv_path = self.generate_csv(bom_list, bom_dir)
            html_path = self.generate_html(bom_list, bom_dir)
            json_path = self.generate_json(bom_list, bom_dir)

            return {
                'success': True,
                'bom': bom_list,
                'total_cost': sum(item['total_price'] for item in bom_list),
                'total_components': sum(item['quantity'] for item in bom_list),
                'unique_parts': len(bom_list),
                'files': {
                    'csv': csv_path,
                    'html': html_path,
                    'json': json_path
                }
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }