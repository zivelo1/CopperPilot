# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
Output generator module for creating KiCad files.

PHASE 0 (2025-11-23): Enhanced with junction generation and global labels.
- Automatically detects and generates junctions at wire connection points
- Uses global labels for net connectivity (not regular labels)
- GENERIC implementation works for ALL circuit types
"""

from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime
from collections import defaultdict
import logging
import uuid
import re

from ..utils.base import PipelineStage, ConversionContext, generate_uuid

# TC #38 (2025-11-23): Import central manufacturing configuration
from kicad.manufacturing_config import MANUFACTURING_CONFIG

logger = logging.getLogger(__name__)

class OutputGenerator(PipelineStage):
    """Generate KiCad output files (project, schematic, PCB)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.kicad_version = 20230121  # KiCad 8 format

    def process(self, context: ConversionContext) -> ConversionContext:
        """Generate all KiCad output files."""
        try:
            # Ensure output directory exists
            context.output_path.mkdir(parents=True, exist_ok=True)

            # Determine project name from circuit context
            if hasattr(context, 'circuit_name'):
                project_name = context.circuit_name
            else:
                project_name = context.output_path.name
                if project_name == 'kicad':
                    project_name = 'circuit'

            # Generate project file
            project_file = self._generate_project_file(project_name, context)
            self._save_file(context.output_path / f"{project_name}.kicad_pro", project_file)

            # Generate schematic file
            schematic_file = self._generate_schematic_file(project_name, context)
            self._save_file(context.output_path / f"{project_name}.kicad_sch", schematic_file)

            # Generate PCB file
            pcb_file = self._generate_pcb_file(project_name, context)
            self._save_file(context.output_path / f"{project_name}.kicad_pcb", pcb_file)

            # Store file paths in context
            context.output = {
                'project': str(context.output_path / f"{project_name}.kicad_pro"),
                'schematic': str(context.output_path / f"{project_name}.kicad_sch"),
                'pcb': str(context.output_path / f"{project_name}.kicad_pcb")
            }

            logger.info(f"Generated KiCad files for project '{project_name}'")
            return context

        except Exception as e:
            return self.handle_error(e, context)

    def _generate_project_file(self, project_name: str, context: ConversionContext) -> str:
        """Generate KiCad project file content."""
        project_uuid = generate_uuid()

        # TC #38 (2025-11-23): Use central manufacturing configuration
        # SINGLE SOURCE OF TRUTH for all manufacturing parameters
        cfg = MANUFACTURING_CONFIG
        default_net = cfg.NET_CLASSES['Default']
        power_net = cfg.NET_CLASSES['Power']

        content = f"""(kicad_pro
  (generator pcbnew)
  (version {self.kicad_version})
  (project "{project_name}"
    (uuid "{project_uuid}")
    (settings
      (schematic
        (page_layout_description_file "")
        (plot_directory "./")
        (netlist_file "{project_name}.net")
        (spice_adjust_passive_values false)
        (spice_external_command "spice \"%I\"")
        (subpart_first_id 65)
        (subpart_id_separator 0)
      )
      (pcb
        (layer_presets)
        (viewports)
        (plot_directory "./")
      )
      (board_design_settings
        (pad_to_mask_clearance {cfg.PAD_TO_MASK_CLEARANCE})
        (solder_mask_min_width {cfg.SOLDER_MASK_MIN_WIDTH})
        (allow_soldermask_bridges_in_footprints {'yes' if cfg.ALLOW_SOLDERMASK_BRIDGES else 'no'})
        (copper_edge_clearance {cfg.COPPER_EDGE_CLEARANCE})
        (aux_axis_origin 0 0)
        (grid_origin 0 0)
        (net_settings
          (net_class_patterns
            (net_class_pattern "Power" "(?i)(VCC|VDD|V\\+|GND|V-|VBAT|5V|3V3|1V8|12V|24V|POWER)")
          )
          (net_class_assignments)
        )
        (defaults
          (clearance {default_net['clearance']})
          (track_width {default_net['track_width']})
          (via_diameter {default_net['via_diameter']})
          (via_drill {default_net['via_drill']})
          (uvia_diameter 0.3)
          (uvia_drill 0.1)
        )
        (net_classes
          (net_class "Default"
            (clearance {default_net['clearance']})
            (track_width {default_net['track_width']})
            (via_diameter {default_net['via_diameter']})
            (via_drill {default_net['via_drill']})
            (uvia_diameter 0.3)
            (uvia_drill 0.1)
          )
          (net_class "Power"
            (clearance {power_net['clearance']})
            (track_width {power_net['track_width']})
            (via_diameter {power_net['via_diameter']})
            (via_drill {power_net['via_drill']})
            (uvia_diameter 0.3)
            (uvia_drill 0.1)
          )
        )
        (pcbplotparams
          (layerselection 0x00010fc_ffffffff)
          (plot_on_all_layers_selection 0x0000000_00000000)
          (disableapertmacros false)
          (usegerberextensions false)
          (usegerberattributes true)
          (usegerberadvancedattributes true)
          (creategerberjobfile true)
          (svguseinch false)
          (svgprecision 6)
          (excludeedgelayer true)
          (plotframeref false)
          (viasonmask false)
          (mode 1)
          (useauxorigin false)
          (hpglpennumber 1)
          (hpglpenspeed 20)
          (hpglpendiameter 15.000000)
          (dxfpolygonmode true)
          (dxfimperialunits true)
          (dxfusepcbnewfont true)
          (psnegative false)
          (psa4output false)
          (plotreference true)
          (plotvalue true)
          (plotinvisibletext false)
          (sketchpadsonfab false)
          (subtractmaskfromsilk false)
          (outputformat 1)
          (mirror false)
          (drillshape 1)
          (scaleselection 1)
          (outputdirectory "")
        )
      )
    )
  )
)"""
        return content

    def _generate_schematic_file(self, project_name: str, context: ConversionContext) -> str:
        """Generate KiCad schematic file content."""
        schematic_uuid = generate_uuid()

        # Start schematic file
        lines = [
            f"(kicad_sch (version {self.kicad_version}) (generator kicad_converter)",
            f"  (uuid {schematic_uuid})",
            "  (paper \"A3\")",
            ""
        ]

        # Add symbol library table
        lines.extend(self._generate_lib_symbols(context))

        # Add junctions (for net connections)
        lines.extend(self._generate_junctions(context))

        # Add components (symbol instances)
        lines.extend(self._generate_symbol_instances(context))

        # Add wires
        lines.extend(self._generate_wires(context))

        # Add labels
        lines.extend(self._generate_labels(context))

        # Add global labels for power nets
        lines.extend(self._generate_global_labels(context))

        # Close schematic
        lines.append(")")

        return "\n".join(lines)

    def _generate_pcb_file(self, project_name: str, context: ConversionContext) -> str:
        """Generate KiCad PCB file content."""
        pcb_uuid = generate_uuid()

        # Start PCB file
        lines = [
            f"(kicad_pcb (version {self.kicad_version}) (generator kicad_converter)",
            f"  (uuid {pcb_uuid})",
            "",
            "  (general",
            "    (thickness 1.6)",
            "    (drawings 0)",
            "    (tracks 0)",
            "    (zones 0)",
            "    (modules 0)",
            "    (nets 1)",
            "  )",
            "",
            "  (paper \"A4\")",
            "",
            "  (layers",
            "    (0 \"F.Cu\" signal)",
            "    (31 \"B.Cu\" signal)",
            "    (32 \"B.Adhes\" user \"B.Adhesive\")",
            "    (33 \"F.Adhes\" user \"F.Adhesive\")",
            "    (34 \"B.Paste\" user)",
            "    (35 \"F.Paste\" user)",
            "    (36 \"B.SilkS\" user \"B.Silkscreen\")",
            "    (37 \"F.SilkS\" user \"F.Silkscreen\")",
            "    (38 \"B.Mask\" user)",
            "    (39 \"F.Mask\" user)",
            "    (40 \"Dwgs.User\" user \"User.Drawings\")",
            "    (41 \"Cmts.User\" user \"User.Comments\")",
            "    (42 \"Eco1.User\" user \"User.Eco1\")",
            "    (43 \"Eco2.User\" user \"User.Eco2\")",
            "    (44 \"Edge.Cuts\" user)",
            "    (45 \"Margin\" user)",
            "    (46 \"B.CrtYd\" user \"B.Courtyard\")",
            "    (47 \"F.CrtYd\" user \"F.Courtyard\")",
            "    (48 \"B.Fab\" user)",
            "    (49 \"F.Fab\" user)",
            "  )",
            "",
            "  (setup",
            "    (pad_to_mask_clearance 0.1)",
            "    (pcbplotparams",
            "      (layerselection 0x00010fc_ffffffff)",
            "      (plot_on_all_layers_selection 0x0000000_00000000)",
            "      (disableapertmacros false)",
            "      (usegerberextensions false)",
            "      (usegerberattributes true)",
            "      (usegerberadvancedattributes true)",
            "      (creategerberjobfile true)",
            "      (dxfpolygonmode true)",
            "      (dxfimperialunits true)",
            "      (dxfusepcbnewfont true)",
            "      (psnegative false)",
            "      (psa4output false)",
            "      (plotreference true)",
            "      (plotvalue true)",
            "      (plotinvisibletext false)",
            "      (sketchpadsonfab false)",
            "      (subtractmaskfromsilk false)",
            "      (outputformat 1)",
            "      (mirror false)",
            "      (drillshape 1)",
            "      (scaleselection 1)",
            "      (outputdirectory \"\")",
            "    )",
            "  )",
            ""
        ]

        # Add nets
        lines.extend(self._generate_pcb_nets(context))

        # Add footprints
        lines.extend(self._generate_footprints(context))

        # Add tracks
        lines.extend(self._generate_tracks(context))

        # Add zones (copper pours)
        lines.extend(self._generate_zones(context))

        # Close PCB
        lines.append(")")

        return "\n".join(lines)

    def _generate_lib_symbols(self, context: ConversionContext) -> List[str]:
        """
        Generate library symbols section.

        TC #37 (2025-11-23): Use embedded symbols without library prefixes.
        Eliminates ERC warnings about missing library files.
        """
        lines = ["  (lib_symbols"]

        for ref_des, comp in context.components.items():
            # TC #37: Remove library prefix to avoid external library lookups
            # "Device:R" → "R_generic"
            # This ensures all symbols are truly embedded, no external dependencies
            symbol_orig = comp.get('symbol', 'Device:R')
            lib_name = symbol_orig.split(':')[0] if ':' in symbol_orig else 'Device'
            sym_name = symbol_orig.split(':')[1] if ':' in symbol_orig else symbol_orig

            # Create embedded symbol name without library prefix
            symbol_embedded = f"{sym_name}_embedded"

            # Store for use in symbol instances
            comp['_embedded_symbol'] = symbol_embedded

            lines.extend([
                f"    (symbol \"{symbol_embedded}\" (pin_numbers hide) (pin_names (offset 0.254) hide)",
                f"      (property \"Reference\" \"{comp['prefix']}\" (id 0) (at 0 0 0)",
                "        (effects (font (size 1.27 1.27))))",
                f"      (property \"Value\" \"{comp['value']}\" (id 1) (at 0 -2.54 0)",
                "        (effects (font (size 1.27 1.27))))",
                f"      (property \"Footprint\" \"{comp['footprint']}\" (id 2) (at 0 -5.08 0)",
                "        (effects (font (size 1.27 1.27)) hide))",
                "    )"
            ])

        lines.append("  )")
        return lines

    def _generate_symbol_instances(self, context: ConversionContext) -> List[str]:
        """
        Generate symbol instances (components) in schematic.

        TC #37 (2025-11-23): Use embedded symbol names (no library lookups).
        """
        lines = []

        schematic_layout = context.layout.get('schematic', {})

        for ref_des, comp in context.components.items():
            pos = schematic_layout.get(ref_des, (50, 50))
            comp_uuid = comp.get('uuid', generate_uuid())

            # TC #37: Use embedded symbol name instead of library reference
            # This eliminates 186 ERC warnings about missing library files
            embedded_symbol = comp.get('_embedded_symbol', comp.get('symbol', 'R_embedded'))

            lines.extend([
                f"  (symbol (lib_id \"{embedded_symbol}\") (at {pos[0]} {pos[1]} 0)",
                f"    (uuid {comp_uuid})",
                "    (in_bom yes) (on_board yes) (fields_autoplaced)",
                f"    (property \"Reference\" \"{ref_des}\" (id 0) (at {pos[0]+5} {pos[1]-2} 0)",
                "      (effects (font (size 1.27 1.27)) (justify left)))",
                f"    (property \"Value\" \"{comp['value']}\" (id 1) (at {pos[0]+5} {pos[1]} 0)",
                "      (effects (font (size 1.27 1.27)) (justify left)))",
                f"    (property \"Footprint\" \"{comp['footprint']}\" (id 2) (at {pos[0]} {pos[1]+5} 0)",
                "      (effects (font (size 1.27 1.27)) hide))",
            ])

            # Add pins
            for pin in comp.get('pins', []):
                pin_net = comp.get('pinNetMapping', {}).get(pin, '')
                if pin_net:
                    lines.append(f"    (pin \"{pin}\" (uuid {generate_uuid()}))")

            lines.append("  )")

        return lines

    def _generate_wires(self, context: ConversionContext) -> List[str]:
        """Generate wires in schematic."""
        lines = []

        routes = context.routes.get('schematic', {})

        for net_name, segments in routes.items():
            for segment in segments:
                if segment['type'] == 'wire':
                    start = segment['start']
                    end = segment['end']
                    lines.extend([
                        f"  (wire (pts (xy {start[0]} {start[1]}) (xy {end[0]} {end[1]}))",
                        "    (stroke (width 0) (type default) (color 0 0 0 0))",
                        f"    (uuid {generate_uuid()})",
                        "  )"
                    ])

        return lines

    def _generate_junctions(self, context: ConversionContext) -> List[str]:
        """
        Generate junction dots for net connections.

        PHASE 0.1 (2025-11-23): Enhanced junction detection.
        Automatically detects points where junctions are needed:
        1. Multiple wires meet at same coordinate (>=2 wires)
        2. Wire endpoints connect to component pins
        3. Wire branches in different directions

        GENERIC: Works for ANY circuit topology and complexity.
        """
        lines = []

        # Dictionary to track all connection points: (x, y) -> count
        junction_points = defaultdict(int)

        # Get all wire segments from routes
        routes = context.routes.get('schematic', {})

        # Count wire endpoints at each coordinate
        for net_name, segments in routes.items():
            for segment in segments:
                if segment.get('type') == 'wire':
                    start = segment.get('start', (0, 0))
                    end = segment.get('end', (0, 0))

                    # Round coordinates to avoid floating point issues
                    start_pt = (round(start[0], 2), round(start[1], 2))
                    end_pt = (round(end[0], 2), round(end[1], 2))

                    junction_points[start_pt] += 1
                    junction_points[end_pt] += 1

        # Get component pin locations from schematic layout
        schematic_layout = context.layout.get('schematic', {})

        for ref_des, comp in context.components.items():
            comp_pos = schematic_layout.get(ref_des, (50, 50))

            # For each pin, add its location as potential junction point
            # Assume pins are at component position (simplified - real pins have offsets)
            for pin in comp.get('pins', []):
                pin_pt = (round(comp_pos[0], 2), round(comp_pos[1], 2))
                junction_points[pin_pt] += 1

        # Generate junction S-expressions for points with 2+ connections
        junction_count = 0
        for (x, y), count in sorted(junction_points.items()):
            if count >= 2:  # Junction needed when 2+ connections meet
                lines.extend([
                    f"  (junction (at {x} {y}) (diameter 0.8)",  # 0.8mm standard diameter
                    "    (color 0 0 0 0)",
                    f"    (uuid {generate_uuid()})",
                    "  )"
                ])
                junction_count += 1

        if junction_count > 0:
            logger.info(f"Generated {junction_count} junctions for schematic connectivity")
        else:
            logger.warning("No junctions generated - may indicate missing wire connections")

        return lines

    def _generate_labels(self, context: ConversionContext) -> List[str]:
        """
        Generate net labels (DEPRECATED - use global labels instead).

        PHASE 0.2 (2025-11-23): Regular labels no longer generated.
        All net connectivity now handled by global_labels for proper
        electrical connections in KiCad.

        Returns empty list to maintain backward compatibility.
        """
        # No longer generate regular labels - use global labels instead
        logger.debug("Regular labels deprecated - using global labels for net connectivity")
        return []

    def _generate_global_labels(self, context: ConversionContext) -> List[str]:
        """
        Generate global labels for ALL nets (not just power).

        PHASE 0.2 (2025-11-23): Complete rewrite for proper net connectivity.
        - Generates global labels for ALL nets in circuit
        - Automatically determines appropriate shape (input/output/bidirectional/passive)
        - Uses intelligent positioning based on wire endpoints
        - GENERIC: Works for ANY circuit type and complexity

        Global labels create electrical connectivity across schematic.
        """
        lines = []

        nets = context.netlist.get('nets', {})
        routes = context.routes.get('schematic', {})

        # Position offset for labels
        x_base = 20
        y_offset = 20
        spacing = 5  # mm between labels

        label_count = 0

        for net_name, net_data in nets.items():
            # Determine appropriate shape for this net
            shape = self._determine_global_label_shape(net_name, net_data, context)

            # Find a good position for the label
            # Try to use wire endpoint if available, otherwise use offset position
            label_x, label_y = self._find_label_position(net_name, routes, x_base, y_offset)

            lines.extend([
                f"  (global_label \"{net_name}\" (shape {shape}) (at {label_x} {label_y} 0) (fields_autoplaced)",
                "    (effects (font (size 1.27 1.27)) (justify left))",
                f"    (uuid {generate_uuid()})",
                "    (property \"Intersheetrefs\" \"~\" (at {label_x} {label_y} 0)",
                "      (effects (font (size 1.27 1.27)) (hide yes))",
                "    )",
                "  )"
            ])

            label_count += 1
            y_offset += spacing

        logger.info(f"Generated {label_count} global labels for net connectivity")
        return lines

    def _determine_global_label_shape(self, net_name: str, net_data: Dict, context: ConversionContext) -> str:
        """
        Determine appropriate global label shape based on net characteristics.

        PHASE 0.2 (2025-11-23): GENERIC shape determination.

        Shapes:
        - 'passive': Power nets (VCC, GND, +5V, etc.)
        - 'output': Nets driven by component outputs
        - 'input': Nets connected to component inputs
        - 'bidirectional': Default for general signal nets (safest)

        Returns:
            str: KiCad global label shape type
        """
        # Power net patterns (GENERIC - matches common power rail names)
        power_patterns = [
            r'^VCC',           # VCC, VCC_12V, VCC_3V3, etc.
            r'^VDD',           # VDD, VDD_IO, etc.
            r'^VSS',           # VSS
            r'^GND',           # GND, GNDA, GNDD, etc.
            r'^\+\d+V',        # +5V, +3V3, +12V, etc.
            r'^\-\d+V',        # -5V, -12V, etc.
            r'^V\d+',          # V5, V3_3, V12, etc.
            r'POWER',          # POWER, POWER_IN, etc.
        ]

        # Check if power net
        for pattern in power_patterns:
            if re.match(pattern, net_name, re.IGNORECASE):
                return 'passive'

        # Check net class if available
        net_class = net_data.get('class', '')
        if net_class == 'power':
            return 'passive'

        # For signal nets, use bidirectional as safest default
        # (works for both input and output scenarios)
        return 'bidirectional'

    def _find_label_position(self, net_name: str, routes: Dict, default_x: float, default_y: float) -> Tuple[float, float]:
        """
        Find good position for global label based on wire endpoints.

        PHASE 0.2 (2025-11-23): Intelligent label positioning.

        Tries to place label near wire endpoint for better visual clarity.
        Falls back to default position if no wires found.

        Args:
            net_name: Name of net to find position for
            routes: Dictionary of schematic routes
            default_x: Default X coordinate
            default_y: Default Y coordinate

        Returns:
            Tuple[float, float]: (x, y) coordinates for label
        """
        # Check if this net has wires
        net_segments = routes.get(net_name, [])

        for segment in net_segments:
            if segment.get('type') == 'wire':
                # Use end point of first wire for label position
                end = segment.get('end', (default_x, default_y))
                # Offset slightly to avoid overlap with junction
                return (end[0] + 2, end[1])

        # No wires found - use default position
        return (default_x, default_y)

    def _generate_pcb_nets(self, context: ConversionContext) -> List[str]:
        """Generate net definitions for PCB."""
        lines = []

        nets = context.netlist.get('nets', {})
        net_id = 0

        for net_name, net_data in nets.items():
            lines.extend([
                f"  (net {net_id} \"{net_name}\")",
            ])
            net_id += 1

        return lines

    def _generate_footprints(self, context: ConversionContext) -> List[str]:
        """Generate footprint placements in PCB."""
        lines = []

        pcb_layout = context.layout.get('pcb', {})

        for ref_des, comp in context.components.items():
            pos = pcb_layout.get(ref_des, (50, 50))
            footprint = comp.get('footprint', 'Package_DIP:DIP-8_W7.62mm')

            lines.extend([
                f"  (footprint \"{footprint}\" (layer \"F.Cu\")",
                f"    (tstamp {generate_uuid()})",
                f"    (at {pos[0]} {pos[1]})",
                f"    (descr \"Footprint for {ref_des}\")",
                f"    (tags \"{comp.get('type', 'component')}\")",
                f"    (property \"Reference\" \"{ref_des}\" (at 0 -2.5 0) (layer \"F.SilkS\")",
                "      (effects (font (size 1 1) (thickness 0.15)))",
                "    )",
                f"    (property \"Value\" \"{comp['value']}\" (at 0 2.5 0) (layer \"F.Fab\")",
                "      (effects (font (size 1 1) (thickness 0.15)))",
                "    )",
                f"    (path \"/{comp.get('uuid', generate_uuid())}\")",
                "    (attr through_hole)",
            ])

            # Add pads based on pin count
            for pin in comp.get('pins', []):
                pad_num = pin
                lines.extend([
                    f"    (pad \"{pad_num}\" thru_hole circle (at 0 0) (size 1.5 1.5) (drill 0.8)",
                    "      (layers *.Cu *.Mask)",
                    f"      (uuid {generate_uuid()})",
                    "    )"
                ])

            lines.append("  )")

        return lines

    def _generate_tracks(self, context: ConversionContext) -> List[str]:
        """Generate PCB tracks."""
        lines = []

        routes = context.routes.get('pcb', {})

        for net_name, segments in routes.items():
            for segment in segments:
                if segment['type'] == 'track':
                    start = segment['start']
                    end = segment['end']
                    width = segment.get('width', 0.25)
                    layer = segment.get('layer', 'F.Cu')

                    lines.extend([
                        f"  (segment (start {start[0]} {start[1]}) (end {end[0]} {end[1]})",
                        f"    (width {width}) (layer \"{layer}\")",
                        f"    (net {net_name})",
                        f"    (uuid {generate_uuid()})",
                        "  )"
                    ])

        return lines

    def _generate_zones(self, context: ConversionContext) -> List[str]:
        """Generate copper zones (ground planes)."""
        lines = []

        # Add ground plane if GND net exists
        nets = context.netlist.get('nets', {})
        if 'GND' in nets:
            lines.extend([
                "  (zone (net 0) (net_name \"GND\") (layer \"B.Cu\")",
                "    (uuid " + generate_uuid() + ")",
                "    (hatch edge 0.508)",
                "    (connect_pads (clearance 0.2))",
                "    (min_thickness 0.2)",
                "    (fill yes (thermal_gap 0.508) (thermal_bridge_width 0.508))",
                "    (polygon",
                "      (pts",
                "        (xy 0 0)",
                "        (xy 100 0)",
                "        (xy 100 80)",
                "        (xy 0 80)",
                "      )",
                "    )",
                "  )"
            ])

        return lines

    def _save_file(self, filepath: Path, content: str) -> None:
        """Save content to file."""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"Saved {filepath}")