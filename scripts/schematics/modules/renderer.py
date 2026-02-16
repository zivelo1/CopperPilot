# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""Rendering module for schematic generator."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from .utils import SchematicContext, Component, Wire, Point
from .symbol_library import SymbolLibrary

class Renderer:
    """High-quality schematic rendering to PNG."""

    def __init__(self, theme_config: Dict = None):
        from server.config import config as main_config
        self.theme = theme_config or getattr(main_config, 'SCHEMATIC_THEME', {})
        self.colors = self.theme.get('colors', {})
        self.dims = self.theme.get('dimensions', {})
        
        self.symbol_library = SymbolLibrary(self.theme)
        self.dpi = 300  # High resolution
        self.background_color = self.colors.get('background', 'white')
        self.grid_color = '#f0f0f0'
        self.text_color = self.colors.get('text', 'black')

    def execute(self, context: SchematicContext) -> SchematicContext:
        """Render schematic to image."""
        print("\n=== Stage 4: Rendering ===")

        # Create image and drawing context
        self._create_image(context)

        # Draw grid
        self._draw_grid(context)

        # Draw title block
        self._draw_title_block(context)

        # Draw components
        for component in context.components.values():
            self._draw_component(component, context)

        # Draw wires
        for wire in context.wires:
            self._draw_wire(wire, context)

        # Draw junction dots
        self._draw_junctions(context)

        # Draw labels
        self._draw_labels(context)

        # Statistics
        context.stats['rendering'] = {
            'image_width': context.canvas_width,
            'image_height': context.canvas_height,
            'components_drawn': len(context.components),
            'wires_drawn': len(context.wires)
        }

        print(f"Rendered {len(context.components)} components and {len(context.wires)} wires")

        return context

    def _create_image(self, context: SchematicContext):
        """Create image and drawing context."""
        # Create white background image
        context.image = Image.new('RGB',
                                 (context.canvas_width, context.canvas_height),
                                 self.background_color)
        context.draw = ImageDraw.Draw(context.image)

        # Load fonts
        try:
            context.font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
            context.font_small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 10)
        except:
            try:
                context.font = ImageFont.truetype("arial.ttf", 14)
                context.font_small = ImageFont.truetype("arial.ttf", 10)
            except:
                context.font = ImageFont.load_default()
                context.font_small = ImageFont.load_default()

    def _draw_grid(self, context: SchematicContext):
        """Draw background grid."""
        # Major grid lines every 100 pixels
        major_grid = 100
        # Minor grid lines every 25 pixels
        minor_grid = 25

        # Draw minor grid
        for x in range(0, context.canvas_width, minor_grid):
            context.draw.line([(x, 0), (x, context.canvas_height)],
                            fill=self.grid_color, width=1)

        for y in range(0, context.canvas_height, minor_grid):
            context.draw.line([(0, y), (context.canvas_width, y)],
                            fill=self.grid_color, width=1)

        # Draw major grid (darker)
        for x in range(0, context.canvas_width, major_grid):
            context.draw.line([(x, 0), (x, context.canvas_height)],
                            fill='#d0d0d0', width=1)

        for y in range(0, context.canvas_height, major_grid):
            context.draw.line([(0, y), (context.canvas_width, y)],
                            fill='#d0d0d0', width=1)

        # Draw grid references (A1, B1, etc.)
        cols = context.canvas_width // major_grid
        rows = context.canvas_height // major_grid

        for col in range(cols):
            letter = chr(ord('A') + col)
            x = col * major_grid + major_grid // 2
            context.draw.text((x - 5, 5), letter, fill='gray', font=context.font_small)
            context.draw.text((x - 5, context.canvas_height - 20), letter,
                            fill='gray', font=context.font_small)

        for row in range(rows):
            number = str(row + 1)
            y = row * major_grid + major_grid // 2
            context.draw.text((5, y - 5), number, fill='gray', font=context.font_small)
            context.draw.text((context.canvas_width - 20, y - 5), number,
                            fill='gray', font=context.font_small)

    def _draw_title_block(self, context: SchematicContext):
        """Draw title block with circuit information."""
        # Title block position (bottom right)
        block_width = 400
        block_height = 150
        x = context.canvas_width - block_width - 20
        y = context.canvas_height - block_height - 20

        # Draw border
        context.draw.rectangle([(x, y), (x + block_width, y + block_height)],
                              outline='black', width=2)

        # Draw internal lines
        context.draw.line([(x, y + 30), (x + block_width, y + 30)],
                        fill='black', width=1)
        context.draw.line([(x, y + 60), (x + block_width, y + 60)],
                        fill='black', width=1)
        context.draw.line([(x, y + 90), (x + block_width, y + 90)],
                        fill='black', width=1)
        context.draw.line([(x, y + 120), (x + block_width, y + 120)],
                        fill='black', width=1)

        # Add text
        circuit_name = context.input_path.stem if context.input_path else "Circuit"
        context.draw.text((x + 10, y + 5), f"Title: {circuit_name}",
                        fill='black', font=context.font)
        context.draw.text((x + 10, y + 35), f"Date: {datetime.now().strftime('%Y-%m-%d')}",
                        fill='black', font=context.font_small)
        context.draw.text((x + 10, y + 65), f"Components: {len(context.components)}",
                        fill='black', font=context.font_small)
        context.draw.text((x + 10, y + 95), f"Nets: {len(context.nets)}",
                        fill='black', font=context.font_small)
        context.draw.text((x + 10, y + 125), "Generated by Schematic Converter v2.0",
                        fill='black', font=context.font_small)

    def _draw_component(self, component: Component, context: SchematicContext):
        """Draw a component with professional styling using centralized theme."""
        # Draw symbol
        self.symbol_library.draw_symbol(context.draw, component)

        # Draw reference designator (Centralized size and color)
        text_x = component.position.x + 20
        text_y = component.position.y - 20
        context.draw.text((text_x, text_y), component.ref_des,
                        fill=self.colors.get('component', 'black'), 
                        font=context.font)

        # Draw value (Centralized size and color)
        if component.value:
            value_y = component.position.y + component.bounds.height + 5
            context.draw.text((text_x, value_y), component.value,
                            fill=self.colors.get('text', 'gray'), 
                            font=context.font_small)

        # Draw pin indicators
        pin_radius = self.dims.get('pin_radius', 3)
        for pin in component.pins.values():
            context.draw.ellipse([
                (pin.position.x - pin_radius, pin.position.y - pin_radius),
                (pin.position.x + pin_radius, pin.position.y + pin_radius)
            ], fill=self.colors.get('pin', 'red'), outline='black')

            # Pin numbers in professional blue
            context.draw.text((pin.position.x + 5, pin.position.y - 10),
                            pin.number, fill='#0000FF', font=context.font_small)

    def _draw_wire(self, wire: Wire, context: SchematicContext):
        """Draw a wire segment."""
        # Draw the wire line
        context.draw.line([
            (wire.start.x, wire.start.y),
            (wire.end.x, wire.end.y)
        ], fill=wire.color, width=wire.width)

    def _draw_junctions(self, context: SchematicContext):
        """Draw junction dots where multiple wires meet."""
        # Get junction points from wire router
        from .wire_router_production import WireRouter

        # Find all wire intersection points
        junction_points = {}

        for wire in context.wires:
            for point in [wire.start, wire.end]:
                key = (point.x, point.y)
                if key not in junction_points:
                    junction_points[key] = []
                junction_points[key].append(wire)

        # Draw dots where 3 or more wires meet (T-junctions and crosses)
        for (x, y), wires in junction_points.items():
            if len(wires) >= 3:
                # Draw larger junction dot for visibility
                r = 5
                context.draw.ellipse([(x - r, y - r), (x + r, y + r)],
                                    fill='black', outline='black', width=2)

    def _draw_labels(self, context: SchematicContext):
        """Draw net labels on important signals."""
        # Label power and ground nets
        labeled_nets = set()

        for wire in context.wires:
            net_name = wire.net

            # Only label important nets once
            if net_name in labeled_nets:
                continue

            net_lower = net_name.lower()
            if any(x in net_lower for x in ['vcc', 'vdd', 'gnd', 'ground', '+5v', '+12v', '+3.3v']):
                # Find a good position for the label
                mid_x = (wire.start.x + wire.end.x) // 2
                mid_y = (wire.start.y + wire.end.y) // 2

                # Draw label background
                bbox = context.draw.textbbox((mid_x, mid_y), net_name, font=context.font_small)
                padding = 2
                context.draw.rectangle(
                    [(bbox[0] - padding, bbox[1] - padding),
                     (bbox[2] + padding, bbox[3] + padding)],
                    fill='white', outline='black'
                )

                # Draw label text
                context.draw.text((mid_x, mid_y), net_name,
                                fill=wire.color, font=context.font_small)

                labeled_nets.add(net_name)

    def save_image(self, context: SchematicContext):
        """Save the rendered image to file."""
        if context.image and context.output_path:
            # Ensure output directory exists
            context.output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save as PNG with high quality
            context.image.save(context.output_path, 'PNG', dpi=(self.dpi, self.dpi))
            print(f"Saved schematic to: {context.output_path}")

    def add_annotations(self, context: SchematicContext):
        """Add additional annotations and notes to schematic."""
        # Add circuit statistics
        stats_text = [
            f"Total Components: {len(context.components)}",
            f"Total Nets: {len(context.nets)}",
            f"Total Connections: {sum(len(net.pins) for net in context.nets.values())}"
        ]

        y_offset = 50
        for text in stats_text:
            context.draw.text((50, y_offset), text,
                            fill='gray', font=context.font_small)
            y_offset += 20

        # Add warnings if any
        if context.warnings:
            y_offset += 20
            context.draw.text((50, y_offset), "Warnings:",
                            fill='orange', font=context.font)
            y_offset += 20

            for warning in context.warnings[:5]:  # Show first 5 warnings
                context.draw.text((70, y_offset), f"• {warning}",
                                fill='orange', font=context.font_small)
                y_offset += 15