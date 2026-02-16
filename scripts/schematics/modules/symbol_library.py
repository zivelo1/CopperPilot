# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Symbol library module for schematic generator."""
from typing import Dict, List, Tuple, Any
from PIL import Image, ImageDraw
from .utils import Component, Point, Rectangle, Pin

class SymbolLibrary:
    """Library of IEEE/ANSI standard electronic symbols."""

    def __init__(self, theme_config: Dict = None):
        # Use theme from config.py if available, otherwise use provided or default
        from server.config import config as main_config
        self.theme = theme_config or getattr(main_config, 'SCHEMATIC_THEME', {})
        self.colors = self.theme.get('colors', {})
        self.dims = self.theme.get('dimensions', {})
        
        self.pin_database = self._load_pin_database()
        self.symbol_definitions = self._load_symbol_definitions()

    def _load_pin_database(self) -> Dict:
        """Load component pin mapping database."""
        return {
            # Voltage Regulators
            'LM7805': {'1': 'IN', '2': 'GND', '3': 'OUT'},
            'LM7812': {'1': 'IN', '2': 'GND', '3': 'OUT'},
            'LM7905': {'1': 'GND', '2': 'IN', '3': 'OUT'},
            'LM317': {'1': 'ADJ', '2': 'OUT', '3': 'IN'},
            'LM337': {'1': 'ADJ', '2': 'IN', '3': 'OUT'},

            # Timers
            'NE555': {'1': 'GND', '2': 'TRIG', '3': 'OUT', '4': 'RST', '5': 'CTRL', '6': 'THR', '7': 'DIS', '8': 'VCC'},
            'LM555': {'1': 'GND', '2': 'TRIG', '3': 'OUT', '4': 'RST', '5': 'CTRL', '6': 'THR', '7': 'DIS', '8': 'VCC'},

            # Op-Amps (8-pin DIP)
            'LM358': {'1': 'OUT1', '2': 'IN1-', '3': 'IN1+', '4': 'V-', '5': 'IN2+', '6': 'IN2-', '7': 'OUT2', '8': 'V+'},
            'TL072': {'1': 'OUT1', '2': 'IN1-', '3': 'IN1+', '4': 'V-', '5': 'IN2+', '6': 'IN2-', '7': 'OUT2', '8': 'V+'},
            'LM324': {
                '1': 'OUT1', '2': 'IN1-', '3': 'IN1+', '4': 'V+', '5': 'IN2+', '6': 'IN2-', '7': 'OUT2',
                '8': 'OUT3', '9': 'IN3-', '10': 'IN3+', '11': 'V-', '12': 'IN4+', '13': 'IN4-', '14': 'OUT4'
            },

            # Logic Gates
            '74HC00': {
                '1': '1A', '2': '1B', '3': '1Y', '4': '2A', '5': '2B', '6': '2Y', '7': 'GND',
                '8': '3Y', '9': '3A', '10': '3B', '11': '4Y', '12': '4A', '13': '4B', '14': 'VCC'
            },
            '74HC04': {
                '1': '1A', '2': '1Y', '3': '2A', '4': '2Y', '5': '3A', '6': '3Y', '7': 'GND',
                '8': '4Y', '9': '4A', '10': '5Y', '11': '5A', '12': '6Y', '13': '6A', '14': 'VCC'
            },

            # PWM Controllers
            'UC3842': {'1': 'COMP', '2': 'FB', '3': 'CS', '4': 'RT/CT', '5': 'GND', '6': 'OUT', '7': 'VCC', '8': 'VREF'},
            'UC3843': {'1': 'COMP', '2': 'FB', '3': 'CS', '4': 'RT/CT', '5': 'GND', '6': 'OUT', '7': 'VCC', '8': 'VREF'},
            'UC3844': {'1': 'COMP', '2': 'FB', '3': 'CS', '4': 'RT/CT', '5': 'GND', '6': 'OUT', '7': 'VCC', '8': 'VREF'},
            'UC3845': {'1': 'COMP', '2': 'FB', '3': 'CS', '4': 'RT/CT', '5': 'GND', '6': 'OUT', '7': 'VCC', '8': 'VREF'},

            # PFC Controllers
            'L6562': {'1': 'INV', '2': 'COMP', '3': 'MULT', '4': 'CS', '5': 'ZCD', '6': 'GND', '7': 'GD', '8': 'VCC'},
            'L6563': {'1': 'INV', '2': 'COMP', '3': 'MULT', '4': 'CS', '5': 'ZCD', '6': 'GND', '7': 'GD', '8': 'VCC'},

            # Bridge Rectifiers
            'GBU406': {'1': 'AC1', '2': 'AC2', '3': 'DC+', '4': 'DC-'},
            'DB107': {'1': 'AC1', '2': 'AC2', '3': 'DC+', '4': 'DC-'},
            'KBP307': {'1': 'AC1', '2': 'AC2', '3': 'DC+', '4': 'DC-'},

            # Microcontrollers (common)
            'ATMEGA328P': {str(i): f'PIN{i}' for i in range(1, 29)},  # 28-pin
            'PIC16F877A': {str(i): f'PIN{i}' for i in range(1, 41)},  # 40-pin
            'STM32F103': {str(i): f'PIN{i}' for i in range(1, 49)},   # 48-pin
        }

    def _load_symbol_definitions(self) -> Dict:
        """Load symbol drawing definitions from theme config."""
        return self.theme.get('standard_symbols', {
            'resistor': {'width': 80, 'height': 30},
            'capacitor': {'width': 60, 'height': 40},
            'capacitor_pol': {'width': 60, 'height': 40},
            'inductor': {'width': 80, 'height': 30},
            'diode': {'width': 60, 'height': 40},
            'led': {'width': 60, 'height': 40},
            'transistor_npn': {'width': 60, 'height': 60},
            'transistor_pnp': {'width': 60, 'height': 60},
            'mosfet_n': {'width': 60, 'height': 60},
            'mosfet_p': {'width': 60, 'height': 60},
            'ic': {'width': 120, 'height': 80},
            'connector': {'width': 60, 'height': 100},
            'crystal': {'width': 60, 'height': 40},
            'transformer': {'width': 100, 'height': 80},
            'switch': {'width': 60, 'height': 40},
            'fuse': {'width': 80, 'height': 30},
            'bridge_rectifier': {'width': 80, 'height': 80},
            'voltage_regulator': {'width': 100, 'height': 60},
            'opamp': {'width': 100, 'height': 80},
            'ground': {'width': 40, 'height': 40},
            'power': {'width': 40, 'height': 40},
        })

    def get_symbol_for_component(self, comp_type: str) -> str:
        """Get appropriate symbol name for component type."""
        comp_lower = comp_type.lower()

        if 'resistor' in comp_lower or comp_lower.startswith('r_'):
            return 'resistor'
        elif 'capacitor' in comp_lower or comp_lower.startswith('c_'):
            if 'electrolytic' in comp_lower or 'polarized' in comp_lower:
                return 'capacitor_pol'
            return 'capacitor'
        elif 'inductor' in comp_lower or comp_lower.startswith('l_'):
            return 'inductor'
        elif 'transformer' in comp_lower:
            return 'transformer'
        elif 'diode' in comp_lower or comp_lower.startswith('d_'):
            if 'led' in comp_lower:
                return 'led'
            elif 'bridge' in comp_lower or 'rectifier' in comp_lower:
                return 'bridge_rectifier'
            return 'diode'
        elif 'transistor' in comp_lower or 'bjt' in comp_lower:
            if 'pnp' in comp_lower:
                return 'transistor_pnp'
            return 'transistor_npn'
        elif 'mosfet' in comp_lower or 'fet' in comp_lower:
            if 'p-channel' in comp_lower or 'pmos' in comp_lower:
                return 'mosfet_p'
            return 'mosfet_n'
        elif 'ic' in comp_lower or 'chip' in comp_lower or comp_lower.startswith('u'):
            if 'regulator' in comp_lower:
                return 'voltage_regulator'
            elif 'opamp' in comp_lower or 'op-amp' in comp_lower:
                return 'opamp'
            return 'ic'
        elif 'connector' in comp_lower or 'jack' in comp_lower or comp_lower.startswith('j'):
            return 'connector'
        elif 'crystal' in comp_lower or 'xtal' in comp_lower:
            return 'crystal'
        elif 'switch' in comp_lower or 'button' in comp_lower:
            return 'switch'
        elif 'fuse' in comp_lower:
            return 'fuse'
        else:
            return 'ic'  # Default to IC symbol

    def get_symbol_size(self, symbol: str) -> Tuple[int, int]:
        """Get width and height for symbol."""
        if symbol in self.symbol_definitions:
            sym_def = self.symbol_definitions[symbol]
            return sym_def['width'], sym_def['height']
        return 80, 60  # Default size

    def draw_symbol(self, draw: ImageDraw.Draw, component: Component):
        """Draw component symbol on schematic."""
        symbol = component.symbol
        x, y = component.position.x, component.position.y
        width, height = self.get_symbol_size(symbol)

        if symbol == 'resistor':
            self._draw_resistor(draw, x, y, width, height)
        elif symbol == 'capacitor':
            self._draw_capacitor(draw, x, y, width, height)
        elif symbol == 'capacitor_pol':
            self._draw_capacitor_polarized(draw, x, y, width, height)
        elif symbol == 'inductor':
            self._draw_inductor(draw, x, y, width, height)
        elif symbol == 'diode':
            self._draw_diode(draw, x, y, width, height)
        elif symbol == 'led':
            self._draw_led(draw, x, y, width, height)
        elif symbol == 'transistor_npn':
            self._draw_transistor_npn(draw, x, y, width, height)
        elif symbol == 'transistor_pnp':
            self._draw_transistor_pnp(draw, x, y, width, height)
        elif symbol == 'mosfet_n':
            self._draw_mosfet_n(draw, x, y, width, height)
        elif symbol == 'mosfet_p':
            self._draw_mosfet_p(draw, x, y, width, height)
        elif symbol == 'connector':
            self._draw_connector(draw, x, y, width, height, len(component.pins))
        elif symbol == 'crystal':
            self._draw_crystal(draw, x, y, width, height)
        elif symbol == 'transformer':
            self._draw_transformer(draw, x, y, width, height)
        elif symbol == 'switch':
            self._draw_switch(draw, x, y, width, height)
        elif symbol == 'fuse':
            self._draw_fuse(draw, x, y, width, height)
        elif symbol == 'bridge_rectifier':
            self._draw_bridge_rectifier(draw, x, y, width, height)
        elif symbol == 'voltage_regulator':
            self._draw_voltage_regulator(draw, x, y, width, height)
        elif symbol == 'opamp':
            self._draw_opamp(draw, x, y, width, height)
        else:
            # Default IC symbol
            self._draw_ic(draw, x, y, width, height, len(component.pins))

    def _draw_resistor(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw resistor symbol (zigzag)."""
        # Horizontal zigzag pattern
        points = []
        segments = 6
        seg_width = w // segments

        for i in range(segments + 1):
            px = x + i * seg_width
            py = y + h // 2 + (h // 3 if i % 2 else -h // 3)
            points.append((px, py))

        # Draw zigzag
        for i in range(len(points) - 1):
            draw.line([points[i], points[i + 1]], fill='black', width=2)

        # Connection lines
        draw.line([(x - 10, y + h // 2), (x, y + h // 2)], fill='black', width=2)
        draw.line([(x + w, y + h // 2), (x + w + 10, y + h // 2)], fill='black', width=2)

    def _draw_capacitor(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw capacitor symbol (two parallel lines)."""
        # Two vertical parallel lines
        gap = w // 3
        line1_x = x + gap
        line2_x = x + 2 * gap

        draw.line([(line1_x, y), (line1_x, y + h)], fill='black', width=3)
        draw.line([(line2_x, y), (line2_x, y + h)], fill='black', width=3)

        # Connection lines
        draw.line([(x - 10, y + h // 2), (line1_x, y + h // 2)], fill='black', width=2)
        draw.line([(line2_x, y + h // 2), (x + w + 10, y + h // 2)], fill='black', width=2)

    def _draw_capacitor_polarized(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw polarized capacitor symbol."""
        # Similar to capacitor but with + sign
        self._draw_capacitor(draw, x, y, w, h)
        # Add + sign
        draw.text((x + w // 4, y - 15), '+', fill='black')

    def _draw_inductor(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw inductor symbol (coils)."""
        # Draw 4 semicircles
        coils = 4
        coil_width = w // coils
        cy = y + h // 2

        for i in range(coils):
            cx = x + i * coil_width + coil_width // 2
            draw.arc([(cx - coil_width // 2, cy - h // 2),
                     (cx + coil_width // 2, cy + h // 2)],
                    0, 180, fill='black', width=2)

        # Connection lines
        draw.line([(x - 10, cy), (x, cy)], fill='black', width=2)
        draw.line([(x + w, cy), (x + w + 10, cy)], fill='black', width=2)

    def _draw_diode(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw diode symbol."""
        cy = y + h // 2
        # Triangle
        triangle = [(x + w // 3, cy), (x + 2 * w // 3, cy - h // 2),
                    (x + 2 * w // 3, cy + h // 2), (x + w // 3, cy)]
        draw.polygon(triangle, outline='black', width=2)
        # Vertical bar
        draw.line([(x + 2 * w // 3, cy - h // 2), (x + 2 * w // 3, cy + h // 2)],
                 fill='black', width=3)
        # Connection lines
        draw.line([(x - 10, cy), (x + w // 3, cy)], fill='black', width=2)
        draw.line([(x + 2 * w // 3, cy), (x + w + 10, cy)], fill='black', width=2)

    def _draw_led(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw LED symbol (diode with arrows)."""
        self._draw_diode(draw, x, y, w, h)
        # Add light arrows
        arrow1_start = (x + w // 2, y - 5)
        arrow1_end = (x + w // 2 + 10, y - 15)
        draw.line([arrow1_start, arrow1_end], fill='black', width=2)
        draw.polygon([(arrow1_end[0], arrow1_end[1]),
                     (arrow1_end[0] - 3, arrow1_end[1] + 3),
                     (arrow1_end[0] - 3, arrow1_end[1] - 3)],
                    fill='black')

    def _draw_transistor_npn(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw NPN transistor symbol."""
        cx = x + w // 2
        cy = y + h // 2

        # Vertical line (base)
        draw.line([(cx - w // 4, cy - h // 3), (cx - w // 4, cy + h // 3)],
                 fill='black', width=3)

        # Emitter line with arrow
        draw.line([(cx - w // 4, cy + h // 6), (cx + w // 4, cy + h // 3)],
                 fill='black', width=2)
        # Arrow on emitter
        arrow_end = (cx + w // 4, cy + h // 3)
        draw.polygon([arrow_end,
                     (arrow_end[0] - 5, arrow_end[1] - 3),
                     (arrow_end[0] - 3, arrow_end[1] - 5)],
                    fill='black')

        # Collector line
        draw.line([(cx - w // 4, cy - h // 6), (cx + w // 4, cy - h // 3)],
                 fill='black', width=2)

        # Connection points
        # Base (left)
        draw.line([(x - 10, cy), (cx - w // 4, cy)], fill='black', width=2)
        # Collector (top)
        draw.line([(cx + w // 4, cy - h // 3), (cx + w // 4, y - 10)],
                 fill='black', width=2)
        # Emitter (bottom)
        draw.line([(cx + w // 4, cy + h // 3), (cx + w // 4, y + h + 10)],
                 fill='black', width=2)

    def _draw_transistor_pnp(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw PNP transistor symbol."""
        cx = x + w // 2
        cy = y + h // 2

        # Vertical line (base)
        draw.line([(cx - w // 4, cy - h // 3), (cx - w // 4, cy + h // 3)],
                 fill='black', width=3)

        # Emitter line with arrow pointing in
        draw.line([(cx - w // 4, cy + h // 6), (cx + w // 4, cy + h // 3)],
                 fill='black', width=2)
        # Arrow on emitter (pointing toward base)
        arrow_start = (cx - w // 4, cy + h // 6)
        draw.polygon([arrow_start,
                     (arrow_start[0] + 5, arrow_start[1] + 3),
                     (arrow_start[0] + 3, arrow_start[1] + 5)],
                    fill='black')

        # Collector line
        draw.line([(cx - w // 4, cy - h // 6), (cx + w // 4, cy - h // 3)],
                 fill='black', width=2)

        # Connection points
        draw.line([(x - 10, cy), (cx - w // 4, cy)], fill='black', width=2)
        draw.line([(cx + w // 4, cy - h // 3), (cx + w // 4, y - 10)],
                 fill='black', width=2)
        draw.line([(cx + w // 4, cy + h // 3), (cx + w // 4, y + h + 10)],
                 fill='black', width=2)

    def _draw_mosfet_n(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw N-channel MOSFET symbol."""
        cx = x + w // 2
        cy = y + h // 2

        # Gate vertical line (dashed)
        for i in range(0, h, 4):
            draw.line([(cx - w // 3, y + i), (cx - w // 3, y + i + 2)],
                     fill='black', width=2)

        # Channel lines
        draw.line([(cx - w // 4, cy - h // 3), (cx - w // 4, cy + h // 3)],
                 fill='black', width=3)

        # Source and Drain lines
        draw.line([(cx - w // 4, cy - h // 4), (cx + w // 3, cy - h // 4)],
                 fill='black', width=2)
        draw.line([(cx - w // 4, cy + h // 4), (cx + w // 3, cy + h // 4)],
                 fill='black', width=2)

        # Arrow showing n-channel
        draw.line([(cx - w // 4, cy), (cx, cy)], fill='black', width=2)
        draw.polygon([(cx, cy), (cx - 5, cy - 3), (cx - 5, cy + 3)],
                    fill='black')

        # Connections
        # Gate (left)
        draw.line([(x - 10, cy), (cx - w // 3, cy)], fill='black', width=2)
        # Drain (top)
        draw.line([(cx + w // 3, cy - h // 4), (cx + w // 3, y - 10)],
                 fill='black', width=2)
        # Source (bottom)
        draw.line([(cx + w // 3, cy + h // 4), (cx + w // 3, y + h + 10)],
                 fill='black', width=2)

    def _draw_mosfet_p(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw P-channel MOSFET symbol."""
        cx = x + w // 2
        cy = y + h // 2

        # Gate vertical line (dashed)
        for i in range(0, h, 4):
            draw.line([(cx - w // 3, y + i), (cx - w // 3, y + i + 2)],
                     fill='black', width=2)

        # Channel lines
        draw.line([(cx - w // 4, cy - h // 3), (cx - w // 4, cy + h // 3)],
                 fill='black', width=3)

        # Source and Drain lines
        draw.line([(cx - w // 4, cy - h // 4), (cx + w // 3, cy - h // 4)],
                 fill='black', width=2)
        draw.line([(cx - w // 4, cy + h // 4), (cx + w // 3, cy + h // 4)],
                 fill='black', width=2)

        # Arrow showing p-channel (pointing opposite direction)
        draw.line([(cx, cy), (cx - w // 4, cy)], fill='black', width=2)
        draw.polygon([(cx - w // 4, cy), (cx - w // 4 + 5, cy - 3),
                     (cx - w // 4 + 5, cy + 3)], fill='black')

        # Connections
        draw.line([(x - 10, cy), (cx - w // 3, cy)], fill='black', width=2)
        draw.line([(cx + w // 3, cy - h // 4), (cx + w // 3, y - 10)],
                 fill='black', width=2)
        draw.line([(cx + w // 3, cy + h // 4), (cx + w // 3, y + h + 10)],
                 fill='black', width=2)

    def _draw_ic(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int, pin_count: int):
        """Draw generic IC symbol."""
        # Main rectangle
        draw.rectangle([(x, y), (x + w, y + h)], outline='black', width=2)

        # Notch at top
        notch_size = 10
        draw.arc([(x + w // 2 - notch_size, y - notch_size // 2),
                 (x + w // 2 + notch_size, y + notch_size // 2)],
                180, 0, fill='black', width=2)

    def _draw_connector(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int, pin_count: int):
        """Draw connector symbol."""
        # Rectangle with rounded corners
        draw.rectangle([(x, y), (x + w, y + h)], outline='black', width=2)

        # Draw pins as small circles
        if pin_count > 0:
            pin_spacing = h / (pin_count + 1)
            for i in range(pin_count):
                py = y + (i + 1) * pin_spacing
                draw.ellipse([(x - 5, py - 3), (x + 5, py + 3)],
                            outline='black', fill='white', width=2)

    def _draw_crystal(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw crystal oscillator symbol."""
        cy = y + h // 2
        # Crystal body (rectangle)
        draw.rectangle([(x + w // 3, y + h // 4), (x + 2 * w // 3, y + 3 * h // 4)],
                      outline='black', width=2)
        # Plates on sides
        draw.line([(x + w // 4, y), (x + w // 4, y + h)], fill='black', width=2)
        draw.line([(x + 3 * w // 4, y), (x + 3 * w // 4, y + h)], fill='black', width=2)
        # Connections
        draw.line([(x - 10, cy), (x + w // 4, cy)], fill='black', width=2)
        draw.line([(x + 3 * w // 4, cy), (x + w + 10, cy)], fill='black', width=2)

    def _draw_transformer(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw transformer symbol."""
        cx = x + w // 2
        # Primary coil (left)
        for i in range(3):
            cy = y + (i + 1) * h // 4
            draw.arc([(x + w // 4 - 10, cy - 8), (x + w // 4 + 10, cy + 8)],
                    0, 180, fill='black', width=2)
        # Secondary coil (right)
        for i in range(3):
            cy = y + (i + 1) * h // 4
            draw.arc([(x + 3 * w // 4 - 10, cy - 8), (x + 3 * w // 4 + 10, cy + 8)],
                    0, 180, fill='black', width=2)
        # Core lines (vertical)
        draw.line([(cx - 2, y), (cx - 2, y + h)], fill='black', width=2)
        draw.line([(cx + 2, y), (cx + 2, y + h)], fill='black', width=2)

    def _draw_switch(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw switch symbol."""
        cy = y + h // 2
        # Fixed contact
        draw.ellipse([(x + w // 4 - 3, cy - 3), (x + w // 4 + 3, cy + 3)],
                    outline='black', fill='black')
        draw.ellipse([(x + 3 * w // 4 - 3, cy - 3), (x + 3 * w // 4 + 3, cy + 3)],
                    outline='black', fill='black')
        # Moving contact (open position)
        draw.line([(x + w // 4, cy), (x + 3 * w // 4 - 5, cy - h // 3)],
                 fill='black', width=2)
        # Connections
        draw.line([(x - 10, cy), (x + w // 4, cy)], fill='black', width=2)
        draw.line([(x + 3 * w // 4, cy), (x + w + 10, cy)], fill='black', width=2)

    def _draw_fuse(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw fuse symbol."""
        cy = y + h // 2
        # Rectangle for fuse body
        draw.rectangle([(x + w // 4, cy - h // 4), (x + 3 * w // 4, cy + h // 4)],
                      outline='black', width=2)
        # Connection lines
        draw.line([(x - 10, cy), (x + w // 4, cy)], fill='black', width=2)
        draw.line([(x + 3 * w // 4, cy), (x + w + 10, cy)], fill='black', width=2)

    def _draw_bridge_rectifier(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw bridge rectifier symbol."""
        cx = x + w // 2
        cy = y + h // 2
        # Diamond shape
        diamond = [(cx, y), (x + w, cy), (cx, y + h), (x, cy), (cx, y)]
        draw.polygon(diamond, outline='black', width=2)
        # Diodes inside
        # Top diode
        draw.line([(cx - 10, y + 15), (cx + 10, y + 15)], fill='black', width=2)
        draw.polygon([(cx, y + 10), (cx - 5, y + 20), (cx + 5, y + 20)],
                    outline='black')
        # Add more diode symbols as needed

    def _draw_voltage_regulator(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw voltage regulator symbol."""
        # Rectangle with pins
        draw.rectangle([(x, y), (x + w, y + h)], outline='black', width=2)
        # Label
        draw.text((x + w // 2 - 10, y + h // 2 - 5), 'REG', fill='black')

    def _draw_opamp(self, draw: ImageDraw.Draw, x: int, y: int, w: int, h: int):
        """Draw operational amplifier symbol."""
        # Triangle
        triangle = [(x, y), (x + w, y + h // 2), (x, y + h), (x, y)]
        draw.polygon(triangle, outline='black', width=2)
        # Input symbols
        draw.text((x + 10, y + h // 3 - 5), '+', fill='black')
        draw.text((x + 10, y + 2 * h // 3 - 5), '-', fill='black')

    def get_pin_mapping(self, component_value: str) -> Dict[str, str]:
        """Get pin mapping for a specific component."""
        # Try exact match first
        if component_value in self.pin_database:
            return self.pin_database[component_value]

        # Try partial match
        for key in self.pin_database:
            if key in component_value or component_value in key:
                return self.pin_database[key]

        return {}