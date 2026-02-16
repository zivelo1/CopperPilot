# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Component library module for EasyEDA converter."""
from typing import Dict, List, Any
from .utils import EasyEDAContext, generate_id, mm_to_easyeda

class ComponentLibrary:
    """Generate EasyEDA symbols and footprints for components."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.symbol_db = self._load_symbol_database()
        self.footprint_db = self._load_footprint_database()
        self.lcsc_db = self._load_lcsc_database()

    def execute(self, context: EasyEDAContext) -> EasyEDAContext:
        """Generate symbols and footprints for all components."""
        print("\n=== Stage 2: Component Library ===")

        for comp_ref, comp_data in context.components.items():
            # Generate symbol
            symbol = self._generate_symbol(comp_data)
            context.symbols[comp_ref] = symbol

            # Generate footprint
            footprint = self._generate_footprint(comp_data)
            context.footprints[comp_ref] = footprint

            # Find LCSC part if possible
            lcsc_part = self._find_lcsc_part(comp_data)
            if lcsc_part:
                comp_data['lcsc'] = lcsc_part

        print(f"Generated {len(context.symbols)} symbols")
        print(f"Generated {len(context.footprints)} footprints")

        return context

    def _load_symbol_database(self) -> Dict:
        """Load symbol templates."""
        return {
            "resistor": {
                "width": 60,
                "height": 20,
                "pins": [
                    {"id": "1", "x": 0, "y": 10, "type": "passive"},
                    {"id": "2", "x": 60, "y": 10, "type": "passive"}
                ],
                "shapes": [
                    {"type": "rect", "x": 10, "y": 5, "width": 40, "height": 10, "fill": "none"}
                ]
            },
            "capacitor": {
                "width": 40,
                "height": 20,
                "pins": [
                    {"id": "1", "x": 0, "y": 10, "type": "passive"},
                    {"id": "2", "x": 40, "y": 10, "type": "passive"}
                ],
                "shapes": [
                    {"type": "line", "x1": 15, "y1": 0, "x2": 15, "y2": 20},
                    {"type": "line", "x1": 25, "y1": 0, "x2": 25, "y2": 20}
                ]
            },
            "inductor": {
                "width": 60,
                "height": 20,
                "pins": [
                    {"id": "1", "x": 0, "y": 10, "type": "passive"},
                    {"id": "2", "x": 60, "y": 10, "type": "passive"}
                ],
                "shapes": [
                    {"type": "arc", "cx": 20, "cy": 10, "r": 5},
                    {"type": "arc", "cx": 30, "cy": 10, "r": 5},
                    {"type": "arc", "cx": 40, "cy": 10, "r": 5}
                ]
            },
            "diode": {
                "width": 40,
                "height": 20,
                "pins": [
                    {"id": "A", "x": 0, "y": 10, "type": "passive"},
                    {"id": "K", "x": 40, "y": 10, "type": "passive"}
                ],
                "shapes": [
                    {"type": "polygon", "points": [[15, 5], [15, 15], [25, 10]]},
                    {"type": "line", "x1": 25, "y1": 5, "x2": 25, "y2": 15}
                ]
            },
            "led": {
                "width": 40,
                "height": 30,
                "pins": [
                    {"id": "A", "x": 0, "y": 15, "type": "passive"},
                    {"id": "K", "x": 40, "y": 15, "type": "passive"}
                ],
                "shapes": [
                    {"type": "polygon", "points": [[15, 10], [15, 20], [25, 15]]},
                    {"type": "line", "x1": 25, "y1": 10, "x2": 25, "y2": 20},
                    {"type": "arrow", "x1": 20, "y1": 5, "x2": 28, "y2": 0},
                    {"type": "arrow", "x1": 25, "y1": 5, "x2": 33, "y2": 0}
                ]
            },
            "transistor": {
                "width": 40,
                "height": 40,
                "pins": [
                    {"id": "B", "x": 0, "y": 20, "type": "input"},
                    {"id": "C", "x": 30, "y": 5, "type": "passive"},
                    {"id": "E", "x": 30, "y": 35, "type": "passive"}
                ],
                "shapes": [
                    {"type": "circle", "cx": 20, "cy": 20, "r": 10, "fill": "none"},
                    {"type": "line", "x1": 10, "y1": 20, "x2": 15, "y2": 20},
                    {"type": "line", "x1": 15, "y1": 15, "x2": 15, "y2": 25},
                    {"type": "line", "x1": 15, "y1": 17, "x2": 25, "y2": 10},
                    {"type": "line", "x1": 15, "y1": 23, "x2": 25, "y2": 30}
                ]
            },
            "ic": {
                "width": 80,
                "height": 60,
                "pins": [],  # Dynamic based on pin count
                "shapes": [
                    {"type": "rect", "x": 10, "y": 10, "width": 60, "height": 40, "fill": "white"}
                ]
            }
        }

    def _load_footprint_database(self) -> Dict:
        """Load footprint templates."""
        return {
            "0402": {"type": "smd", "width": 1.0, "height": 0.5},
            "0603": {"type": "smd", "width": 1.6, "height": 0.8},
            "0805": {"type": "smd", "width": 2.0, "height": 1.25},
            "1206": {"type": "smd", "width": 3.2, "height": 1.6},
            "SOT23": {"type": "smd", "pins": 3, "pitch": 0.95},
            "SOT223": {"type": "smd", "pins": 4, "pitch": 2.3},
            "SOIC8": {"type": "smd", "pins": 8, "pitch": 1.27},
            "SOIC14": {"type": "smd", "pins": 14, "pitch": 1.27},
            "SOIC16": {"type": "smd", "pins": 16, "pitch": 1.27},
            "TQFP32": {"type": "smd", "pins": 32, "pitch": 0.8},
            "TQFP44": {"type": "smd", "pins": 44, "pitch": 0.8},
            "DIP8": {"type": "tht", "pins": 8, "pitch": 2.54},
            "DIP14": {"type": "tht", "pins": 14, "pitch": 2.54},
            "DIP16": {"type": "tht", "pins": 16, "pitch": 2.54}
        }

    def _load_lcsc_database(self) -> Dict:
        """Load LCSC part number database."""
        return {
            "resistor_10k_0603": "C25804",
            "resistor_1k_0603": "C21190",
            "resistor_100_0603": "C22775",
            "capacitor_100nf_0603": "C14663",
            "capacitor_10uf_0603": "C19702",
            "capacitor_1uf_0603": "C15849",
            "led_red_0603": "C2286",
            "led_green_0603": "C72043",
            "transistor_2n3904": "C20526",
            "transistor_2n3906": "C20527",
            "lm358": "C5251",
            "ne555": "C7593",
            "atmega328p": "C14877"
        }

    def _generate_symbol(self, comp_data: Dict) -> Dict:
        """Generate EasyEDA symbol for component."""
        comp_type = comp_data['type'].lower()

        # Get base symbol template
        template = None
        if comp_type in self.symbol_db:
            template = self.symbol_db[comp_type]
        elif 'resistor' in comp_type:
            template = self.symbol_db['resistor']
        elif 'capacitor' in comp_type:
            template = self.symbol_db['capacitor']
        elif 'inductor' in comp_type:
            template = self.symbol_db['inductor']
        elif 'diode' in comp_type:
            template = self.symbol_db['diode']
        elif 'led' in comp_type:
            template = self.symbol_db['led']
        elif 'transistor' in comp_type or 'bjt' in comp_type:
            template = self.symbol_db['transistor']
        elif 'ic' in comp_type or comp_data.get('package', '').startswith('DIP'):
            template = self._generate_ic_symbol(comp_data)
        else:
            # Default rectangle symbol
            template = self.symbol_db['ic']

        # Create symbol with unique ID
        symbol = {
            "id": generate_id("sym"),
            "type": "symbol",
            "refDes": comp_data['refDes'],
            "value": comp_data['value'],
            "template": template,
            "pins": template.get('pins', []),
            "bbox": {
                "x": 0,
                "y": 0,
                "width": template.get('width', 80),
                "height": template.get('height', 60)
            }
        }

        return symbol

    def _generate_ic_symbol(self, comp_data: Dict) -> Dict:
        """Generate IC symbol with dynamic pins."""
        # Get pin count
        pin_count = 8  # Default
        if 'pins' in comp_data:
            pin_count = len(comp_data['pins'])
        elif 'specs' in comp_data and 'pinCount' in comp_data['specs']:
            pin_count = int(comp_data['specs']['pinCount'])

        # Calculate dimensions
        height = max(60, (pin_count // 2) * 15 + 30)
        width = 80

        # Generate pins
        pins = []
        pins_per_side = pin_count // 2

        # Left side pins
        for i in range(pins_per_side):
            pins.append({
                "id": str(i + 1),
                "x": 0,
                "y": 20 + i * 15,
                "type": "passive"
            })

        # Right side pins
        for i in range(pins_per_side):
            pins.append({
                "id": str(pins_per_side + i + 1),
                "x": width,
                "y": height - 20 - i * 15,
                "type": "passive"
            })

        return {
            "width": width,
            "height": height,
            "pins": pins,
            "shapes": [
                {"type": "rect", "x": 10, "y": 10, "width": width - 20, "height": height - 20, "fill": "white"}
            ]
        }

    def _generate_footprint(self, comp_data: Dict) -> Dict:
        """Generate EasyEDA footprint for component."""
        # Determine package
        package = comp_data.get('package', '')
        if not package:
            package = self._guess_package(comp_data)

        # Get footprint template
        footprint_template = self.footprint_db.get(package, {})

        footprint = {
            "id": generate_id("fp"),
            "type": "footprint",
            "package": package,
            "refDes": comp_data['refDes'],
            "template": footprint_template
        }

        return footprint

    def _guess_package(self, comp_data: Dict) -> str:
        """Guess package based on component type and value."""
        comp_type = comp_data['type'].lower()

        # SMD passives
        if comp_type in ['resistor', 'capacitor']:
            return '0603'  # Default SMD size
        elif comp_type == 'inductor':
            return '1206'
        elif comp_type in ['led', 'diode']:
            return '0603'
        elif comp_type in ['transistor', 'bjt']:
            return 'SOT23'
        elif comp_type == 'mosfet':
            return 'SOT23'
        elif comp_type == 'fuse':
            return '1206'
        elif comp_type == 'mov' or 'varistor' in comp_type:
            return 'DISC'
        elif comp_type == 'bridge_rectifier' or comp_type == 'bridge rectifier':
            return 'DIP4'
        elif comp_type == 'transformer':
            return 'TRANSFORMER'
        elif comp_type == 'relay':
            return 'DIP8'
        elif comp_type == 'crystal' or comp_type == 'oscillator':
            return 'HC49'
        elif comp_type == 'switch' or comp_type == 'button':
            return 'TACTILE'
        elif comp_type == 'connector':
            pin_count = len(comp_data.get('pins', [2]))
            return f'HDR-{pin_count}'
        elif 'ic' in comp_type:
            # Guess based on pin count
            pin_count = len(comp_data.get('pins', []))
            if pin_count <= 8:
                return 'SOIC8'
            elif pin_count <= 14:
                return 'SOIC14'
            elif pin_count <= 16:
                return 'SOIC16'
            else:
                return f'TQFP{pin_count}'

        return '0603'  # Default

    def _find_lcsc_part(self, comp_data: Dict) -> str:
        """Find LCSC part number for component."""
        comp_type = comp_data['type'].lower()
        value = comp_data.get('value', '').lower()
        package = comp_data.get('package', '0603').lower()

        # Build lookup key
        key = f"{comp_type}_{value}_{package}".replace(' ', '_')

        # Check database
        if key in self.lcsc_db:
            return self.lcsc_db[key]

        # Check for specific parts
        if comp_data.get('specs', {}).get('suggestedPart'):
            part = comp_data['specs']['suggestedPart']
            if part.upper() in self.lcsc_db:
                return self.lcsc_db[part.upper()]

        return ""