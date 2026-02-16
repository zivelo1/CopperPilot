# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""JLCPCB integration module for EasyEDA converter."""
from typing import Dict, List, Any
from .utils import EasyEDAContext

class JLCPCBIntegrator:
    """Add JLCPCB manufacturing data to EasyEDA project."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.assembly_enabled = config.get('enable_assembly', False)

    def execute(self, context: EasyEDAContext) -> EasyEDAContext:
        """Add JLCPCB integration data."""
        print("\n=== Stage 6: JLCPCB Integration ===")

        # Add LCSC part numbers
        lcsc_count = self._add_lcsc_parts(context)

        # Generate BOM for JLCPCB
        bom = self._generate_bom(context)

        # Generate pick and place data if assembly enabled
        if self.assembly_enabled:
            pnp = self._generate_pick_and_place(context)
            context.stats['pick_and_place'] = pnp

        # Add manufacturing notes
        notes = self._generate_manufacturing_notes(context)

        # Store JLCPCB data
        context.stats['jlcpcb'] = {
            'bom': bom,
            'lcsc_parts': lcsc_count,
            'manufacturing_notes': notes
        }

        print(f"Added {lcsc_count} LCSC part numbers")
        print(f"Generated BOM with {len(bom)} items")

        return context

    def _add_lcsc_parts(self, context: EasyEDAContext) -> int:
        """Add LCSC part numbers to components."""
        lcsc_count = 0

        for comp_ref, comp_data in context.components.items():
            if 'lcsc' in comp_data and comp_data['lcsc']:
                lcsc_count += 1
                continue

            # Try to find LCSC part
            lcsc_part = self._lookup_lcsc_part(comp_data)
            if lcsc_part:
                comp_data['lcsc'] = lcsc_part
                lcsc_count += 1

        return lcsc_count

    def _lookup_lcsc_part(self, comp_data: Dict) -> str:
        """Lookup LCSC part number for component."""
        comp_type = comp_data['type'].lower()
        value = comp_data.get('value', '').lower()

        # Common LCSC parts database
        lcsc_db = {
            # Resistors
            'resistor_10k': 'C25804',
            'resistor_1k': 'C21190',
            'resistor_100': 'C22775',
            'resistor_4.7k': 'C25905',
            'resistor_2.2k': 'C25879',
            'resistor_470': 'C25117',
            'resistor_220': 'C22962',
            'resistor_330': 'C23138',

            # Capacitors
            'capacitor_100nf': 'C14663',
            'capacitor_10uf': 'C19702',
            'capacitor_1uf': 'C15849',
            'capacitor_22uf': 'C59461',
            'capacitor_100uf': 'C16133',
            'capacitor_10nf': 'C57112',
            'capacitor_1nf': 'C46653',
            'capacitor_22pf': 'C1588',

            # LEDs
            'led_red': 'C2286',
            'led_green': 'C72043',
            'led_blue': 'C72041',
            'led_yellow': 'C72038',
            'led_white': 'C72044',

            # Transistors
            '2n3904': 'C20526',
            '2n3906': 'C20527',
            'bc547': 'C713613',
            'bc557': 'C713614',
            '2n7000': 'C20917',

            # Common ICs
            'lm358': 'C5251',
            'ne555': 'C7593',
            'lm7805': 'C58069',
            'lm317': 'C22714',
            'atmega328p': 'C14877',
            'stm32f103c8t6': 'C8734',
            'ch340g': 'C14267',

            # Diodes
            '1n4148': 'C14516',
            '1n4007': 'C53929',
            '1n5819': 'C8598',
            'bat54': 'C30952'
        }

        # Build lookup key
        key = f"{comp_type}_{value}".replace(' ', '_').replace('ω', '').replace('ω', '')

        # Direct lookup
        if key in lcsc_db:
            return lcsc_db[key]

        # Try without type prefix
        if value in lcsc_db:
            return lcsc_db[value]

        # Try suggested part
        if 'specs' in comp_data and 'suggestedPart' in comp_data['specs']:
            suggested = comp_data['specs']['suggestedPart'].lower()
            if suggested in lcsc_db:
                return lcsc_db[suggested]

        return ""

    def _generate_bom(self, context: EasyEDAContext) -> List[Dict]:
        """Generate BOM for JLCPCB."""
        bom = []
        bom_dict = {}

        # Group components by value and package
        for comp_ref, comp_data in context.components.items():
            # Create BOM key
            key = f"{comp_data['type']}_{comp_data.get('value', '')}_{comp_data.get('package', '')}"

            if key not in bom_dict:
                bom_dict[key] = {
                    'comment': comp_data.get('value', ''),
                    'designator': [],
                    'footprint': comp_data.get('package', ''),
                    'lcsc': comp_data.get('lcsc', ''),
                    'type': comp_data['type'],
                    'quantity': 0
                }

            bom_dict[key]['designator'].append(comp_ref)
            bom_dict[key]['quantity'] += 1

        # Convert to list format
        for key, item in bom_dict.items():
            bom.append({
                'Comment': item['comment'],
                'Designator': ','.join(sorted(item['designator'])),
                'Footprint': item['footprint'],
                'LCSC': item['lcsc'],
                'Type': item['type'],
                'Quantity': item['quantity']
            })

        # Sort by designator
        bom.sort(key=lambda x: x['Designator'])

        return bom

    def _generate_pick_and_place(self, context: EasyEDAContext) -> List[Dict]:
        """Generate pick and place data for assembly."""
        pnp = []

        # Get component positions from PCB data
        if hasattr(context, 'pcb_data') and context.pcb_data and 'shape' in context.pcb_data:
            for shape in context.pcb_data['shape']:
                if shape.get('type') == 'FOOTPRINT':
                    pnp.append({
                        'Designator': shape.get('refDes', ''),
                        'Mid X': shape.get('x', 0) / 10,  # Convert to mm
                        'Mid Y': shape.get('y', 0) / 10,  # Convert to mm
                        'Layer': 'Top',
                        'Rotation': 0
                    })

        return pnp

    def _generate_manufacturing_notes(self, context: EasyEDAContext) -> Dict:
        """Generate manufacturing notes for JLCPCB."""
        notes = {
            'pcb_specifications': {
                'layers': 2,
                'dimension': '100mm x 80mm',
                'pcb_thickness': 1.6,
                'pcb_color': 'Green',
                'silkscreen': 'White',
                'surface_finish': 'HASL',
                'copper_weight': '1oz',
                'min_hole_size': 0.3,
                'min_track_width': 0.15,
                'min_clearance': 0.15
            },
            'assembly_options': {
                'assembly_service': self.assembly_enabled,
                'assembly_side': 'Top',
                'tooling_holes': 'Added by JLCPCB',
                'confirm_parts': 'Yes',
                'component_source': 'LCSC'
            },
            'special_requirements': [
                'Please use lead-free solder',
                'Components should be sourced from LCSC where available',
                'Ensure all ICs have proper orientation marks'
            ]
        }

        # Add statistics
        notes['statistics'] = {
            'total_components': len(context.components),
            'smd_components': sum(1 for c in context.components.values()
                                  if 'smd' in c.get('package', '').lower()),
            'tht_components': sum(1 for c in context.components.values()
                                  if 'tht' in c.get('package', '').lower() or
                                  'dip' in c.get('package', '').lower()),
            'components_with_lcsc': sum(1 for c in context.components.values()
                                        if c.get('lcsc')),
            'unique_parts': len(set(f"{c['type']}_{c.get('value', '')}"
                                    for c in context.components.values()))
        }

        return notes