#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Power Pour Generator - TC #87 Phase 1

Generates copper pours (zones) for power nets (GND, VCC) instead of routing them as traces.
This is the PROFESSIONAL approach used by real PCB designers.

Why Power Pours Instead of Traces:
1. Power nets (GND, VCC) have many pads (20-40+) creating routing congestion
2. Routing GND as traces creates 27+ competing routes that block each other
3. Professional PCBs use copper pours for power distribution
4. Pours provide lower impedance, better EMI shielding, thermal dissipation

Design:
- Ground pour on B.Cu (bottom copper layer)
- Power net (VCC) as wide traces or secondary pour on F.Cu
- Via connections from top-side pads to ground pour

GENERIC: Works for ANY circuit by:
1. Finding board outline (gr_rect on Edge.Cuts)
2. Finding power net indices (GND, VCC, etc.)
3. Creating zone elements with correct polygon coordinates
4. Inserting zones into PCB file before routing

Author: Claude Opus 4.5
Date: 2025-12-16
Version: 1.0 (TC #87 Phase 1)
"""

import re
import uuid
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass

# Setup logging
logger = logging.getLogger(__name__)

# Import manufacturing config for clearances
try:
    from manufacturing_config import MANUFACTURING_CONFIG
except ImportError:
    MANUFACTURING_CONFIG = None


@dataclass
class BoardOutline:
    """Board outline coordinates."""
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


@dataclass
class ZoneConfig:
    """Configuration for a copper pour zone."""
    net_index: int
    net_name: str
    layer: str
    clearance: float = 0.3  # mm - zone to track clearance
    min_thickness: float = 0.2  # mm - minimum zone width
    thermal_gap: float = 0.3  # mm - thermal relief gap
    thermal_bridge_width: float = 0.4  # mm - thermal spoke width
    priority: int = 0  # Higher priority zones fill first
    fill_type: str = "solid"  # solid or hatch


class PowerPourGenerator:
    """
    Generates copper pour zones for power nets.

    GENERIC: Works for any circuit by parsing board outline and net definitions.
    """

    # Default power net names to create pours for
    DEFAULT_GROUND_NETS = {'GND', 'DGND', 'AGND', 'PGND', 'VSS', 'GNDA', 'GNDD'}
    DEFAULT_POWER_NETS = {'VCC', 'VDD', 'V5', 'V3V3', '3V3', '5V', 'V12', '12V', 'VBAT', 'VIN'}

    def __init__(self, pcb_file: Path):
        """
        Initialize power pour generator.

        Args:
            pcb_file: Path to .kicad_pcb file
        """
        self.pcb_file = Path(pcb_file)
        self.content = ""
        self.net_mapping: Dict[str, int] = {}  # name -> index
        self.board_outline: Optional[BoardOutline] = None

        # Load and parse PCB file
        self._load_pcb()
        self._parse_nets()
        self._parse_board_outline()

    def _load_pcb(self):
        """Load PCB file content."""
        if not self.pcb_file.exists():
            raise FileNotFoundError(f"PCB file not found: {self.pcb_file}")

        self.content = self.pcb_file.read_text(encoding='utf-8')
        logger.info(f"TC #87: Loaded PCB file: {self.pcb_file.name}")

    def _parse_nets(self):
        """Parse net definitions to build name -> index mapping."""
        # Pattern: (net INDEX "NAME")
        net_pattern = re.compile(r'\(net\s+(\d+)\s+"([^"]+)"\)')

        for match in net_pattern.finditer(self.content):
            net_index = int(match.group(1))
            net_name = match.group(2)
            self.net_mapping[net_name] = net_index

        logger.info(f"TC #87: Found {len(self.net_mapping)} net definitions")

    def _parse_board_outline(self):
        """Parse board outline from gr_rect on Edge.Cuts layer."""
        # Pattern: (gr_rect (start X Y) (end X Y) ... (layer "Edge.Cuts"))
        rect_pattern = re.compile(
            r'\(gr_rect\s*'
            r'\(start\s+([-\d.]+)\s+([-\d.]+)\)\s*'
            r'\(end\s+([-\d.]+)\s+([-\d.]+)\).*?'
            r'\(layer\s+"Edge\.Cuts"\)',
            re.DOTALL
        )

        match = rect_pattern.search(self.content)
        if match:
            x1, y1 = float(match.group(1)), float(match.group(2))
            x2, y2 = float(match.group(3)), float(match.group(4))

            self.board_outline = BoardOutline(
                min_x=min(x1, x2),
                min_y=min(y1, y2),
                max_x=max(x1, x2),
                max_y=max(y1, y2)
            )

            logger.info(f"TC #87: Board outline: {self.board_outline.width:.1f}x{self.board_outline.height:.1f}mm")
        else:
            logger.warning("TC #87: No board outline found (gr_rect on Edge.Cuts)")

    def identify_power_nets(self) -> Tuple[List[str], List[str]]:
        """
        Identify ground and power nets from the circuit.

        Returns:
            Tuple of (ground_nets, power_nets) lists
        """
        ground_nets = []
        power_nets = []

        for net_name in self.net_mapping.keys():
            net_upper = net_name.upper()

            # Check for ground nets
            if net_upper in self.DEFAULT_GROUND_NETS or 'GND' in net_upper:
                ground_nets.append(net_name)
            # Check for power nets
            elif net_upper in self.DEFAULT_POWER_NETS or any(p in net_upper for p in ['VCC', 'VDD', 'V5', 'V3V3', 'V12']):
                power_nets.append(net_name)

        logger.info(f"TC #87: Identified {len(ground_nets)} ground nets, {len(power_nets)} power nets")
        return ground_nets, power_nets

    def _generate_zone_sexp(self, config: ZoneConfig, outline: BoardOutline, inset: float = 0.5) -> str:
        """
        Generate S-expression for a copper pour zone.

        Args:
            config: Zone configuration
            outline: Board outline
            inset: Inset from board edge (mm)

        Returns:
            S-expression string for the zone
        """
        # Calculate zone polygon (inset from board edge)
        x1 = outline.min_x + inset
        y1 = outline.min_y + inset
        x2 = outline.max_x - inset
        y2 = outline.max_y - inset

        # Generate unique timestamp
        zone_uuid = str(uuid.uuid4())
        tstamp = uuid.uuid4().hex[:8]

        # KiCad 9 zone format
        zone_sexp = f'''  (zone
    (net {config.net_index})
    (net_name "{config.net_name}")
    (layer "{config.layer}")
    (uuid "{zone_uuid}")
    (hatch edge 0.5)
    (priority {config.priority})
    (connect_pads
      (clearance {config.clearance})
    )
    (min_thickness {config.min_thickness})
    (filled_areas_thickness no)
    (fill yes
      (thermal_gap {config.thermal_gap})
      (thermal_bridge_width {config.thermal_bridge_width})
    )
    (polygon
      (pts
        (xy {x1:.4f} {y1:.4f})
        (xy {x2:.4f} {y1:.4f})
        (xy {x2:.4f} {y2:.4f})
        (xy {x1:.4f} {y2:.4f})
      )
    )
  )
'''
        return zone_sexp

    def generate_ground_pour(self,
                            ground_net_name: str = "GND",
                            layer: str = "B.Cu",
                            clearance: float = 0.3) -> bool:
        """
        Generate a ground pour zone on the specified layer.

        GENERIC: Works for any circuit with a ground net.

        Args:
            ground_net_name: Name of the ground net (default: "GND")
            layer: Layer for the pour (default: "B.Cu" - bottom)
            clearance: Zone-to-track clearance (mm)

        Returns:
            True if pour was generated successfully
        """
        # Find ground net index
        net_index = self.net_mapping.get(ground_net_name)
        if net_index is None:
            # Try case-insensitive search
            for name, idx in self.net_mapping.items():
                if name.upper() == ground_net_name.upper():
                    net_index = idx
                    ground_net_name = name
                    break

        if net_index is None:
            logger.warning(f"TC #87: Ground net '{ground_net_name}' not found in circuit")
            return False

        if self.board_outline is None:
            logger.warning("TC #87: Cannot create pour without board outline")
            return False

        # Create zone configuration
        config = ZoneConfig(
            net_index=net_index,
            net_name=ground_net_name,
            layer=layer,
            clearance=clearance,
            priority=0,  # Ground has lowest priority (fills around everything)
            thermal_gap=0.3,
            thermal_bridge_width=0.4
        )

        # Generate zone S-expression
        zone_sexp = self._generate_zone_sexp(config, self.board_outline, inset=0.5)

        # Insert zone into PCB file (before first footprint or at end of header)
        self._insert_zone(zone_sexp)

        logger.info(f"TC #87: Generated {ground_net_name} pour on {layer}")
        return True

    def generate_power_pour(self,
                           power_net_name: str,
                           layer: str = "F.Cu",
                           clearance: float = 0.4,
                           priority: int = 1) -> bool:
        """
        Generate a power pour zone (VCC, V5, etc.).

        Power pours have higher priority than ground and use larger clearances.

        Args:
            power_net_name: Name of the power net
            layer: Layer for the pour (default: "F.Cu" - top)
            clearance: Zone-to-track clearance (mm)
            priority: Fill priority (higher fills first)

        Returns:
            True if pour was generated successfully
        """
        net_index = self.net_mapping.get(power_net_name)
        if net_index is None:
            logger.warning(f"TC #87: Power net '{power_net_name}' not found")
            return False

        if self.board_outline is None:
            return False

        config = ZoneConfig(
            net_index=net_index,
            net_name=power_net_name,
            layer=layer,
            clearance=clearance,
            priority=priority,
            thermal_gap=0.4,
            thermal_bridge_width=0.5
        )

        zone_sexp = self._generate_zone_sexp(config, self.board_outline, inset=1.0)
        self._insert_zone(zone_sexp)

        logger.info(f"TC #87: Generated {power_net_name} pour on {layer}")
        return True

    def _insert_zone(self, zone_sexp: str):
        """Insert zone S-expression into PCB content."""
        # Find good insertion point - after nets, before footprints
        # Look for first (footprint or first (segment or end of file

        footprint_match = re.search(r'\n\s*\(footprint\s', self.content)
        segment_match = re.search(r'\n\s*\(segment\s', self.content)

        if footprint_match:
            insert_pos = footprint_match.start()
        elif segment_match:
            insert_pos = segment_match.start()
        else:
            # Insert before final closing paren
            insert_pos = self.content.rfind(')')

        self.content = self.content[:insert_pos] + "\n" + zone_sexp + self.content[insert_pos:]

    def save(self) -> bool:
        """
        Save modified PCB file.

        Returns:
            True if saved successfully
        """
        try:
            self.pcb_file.write_text(self.content, encoding='utf-8')
            logger.info(f"TC #87: Saved PCB file with power pours: {self.pcb_file.name}")
            return True
        except Exception as e:
            logger.error(f"TC #87: Failed to save PCB file: {e}")
            return False

    def get_power_net_names(self) -> Set[str]:
        """
        Get set of all power net names (ground + power).

        Used by router to skip these nets (they're handled by pours).

        Returns:
            Set of power net names
        """
        ground_nets, power_nets = self.identify_power_nets()
        return set(ground_nets + power_nets)


def add_power_pours_to_pcb(pcb_file: Path,
                           add_ground: bool = True,
                           add_power: bool = False) -> Tuple[bool, Set[str]]:
    """
    Add power pour zones to a PCB file.

    GENERIC: Automatically identifies power nets and creates appropriate pours.

    Args:
        pcb_file: Path to .kicad_pcb file
        add_ground: Whether to add ground pour (default: True)
        add_power: Whether to add power pours for VCC etc. (default: False)

    Returns:
        Tuple of (success, power_net_names) where power_net_names should be
        excluded from trace routing
    """
    try:
        generator = PowerPourGenerator(pcb_file)
        ground_nets, power_nets = generator.identify_power_nets()

        poured_nets = set()

        # Add ground pour on B.Cu (bottom layer)
        if add_ground and ground_nets:
            primary_gnd = ground_nets[0]  # Usually just "GND"
            if generator.generate_ground_pour(primary_gnd, layer="B.Cu"):
                poured_nets.add(primary_gnd)

        # Optionally add power pours on F.Cu (top layer)
        if add_power and power_nets:
            for i, power_net in enumerate(power_nets[:2]):  # Max 2 power pours
                if generator.generate_power_pour(power_net, layer="F.Cu", priority=i+1):
                    poured_nets.add(power_net)

        # Save modified PCB
        if poured_nets:
            generator.save()
            logger.info(f"TC #87: Added pours for nets: {poured_nets}")

        # Return all power nets (whether poured or not) for router to skip
        return True, generator.get_power_net_names()

    except Exception as e:
        logger.error(f"TC #87: Failed to add power pours: {e}")
        import traceback
        traceback.print_exc()
        return False, set()


def get_power_nets_from_pcb(pcb_file: Path) -> Set[str]:
    """
    Get set of power net names from a PCB file.

    Used by router to identify which nets should be skipped (handled by pours).

    Args:
        pcb_file: Path to .kicad_pcb file

    Returns:
        Set of power net names
    """
    try:
        generator = PowerPourGenerator(pcb_file)
        return generator.get_power_net_names()
    except Exception as e:
        logger.warning(f"TC #87: Could not identify power nets: {e}")
        # Return common defaults
        return {'GND', 'VCC', 'VDD', 'V5', 'V3V3'}


# Module test
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    if len(sys.argv) < 2:
        print("Usage: python power_pour.py <pcb_file.kicad_pcb>")
        sys.exit(1)

    pcb_path = Path(sys.argv[1])
    success, power_nets = add_power_pours_to_pcb(pcb_path, add_ground=True, add_power=False)

    if success:
        print(f"✓ Added power pours successfully")
        print(f"  Power nets (skip in router): {power_nets}")
    else:
        print(f"✗ Failed to add power pours")
        sys.exit(1)
