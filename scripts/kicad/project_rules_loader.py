# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
KiCad Project Rules Loader
==========================

GENERIC: Load design rules from KiCad's project files (.kicad_pro).
Uses the EXACT same rules that KiCad uses.
NO GUESSING - just copying what KiCad would use.

This module parses KiCad's .kicad_pro files (JSON format) and extracts:
- Design rules (clearance, track width, via dimensions)
- Net classes (different rules for different signal types)
- Manufacturing constraints

Author: Claude Code
Date: 2025-11-27
Version: 1.0.0
Test Cycle: TC #60 - ARCHITECTURAL FIX
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class NetClass:
    """
    Net class definition from KiCad project.

    Defines routing rules for specific net types (power, signal, RF, etc.).
    EXACT copy of what KiCad uses.
    """
    name: str
    clearance: float  # mm
    track_width: float  # mm
    via_diameter: float  # mm
    via_drill: float  # mm
    diff_pair_width: float = 0.2  # mm
    diff_pair_gap: float = 0.25  # mm
    microvia_diameter: float = 0.3  # mm
    microvia_drill: float = 0.1  # mm
    priority: int = 0  # Lower = higher priority

    # Patterns to match nets to this class
    patterns: List[str] = field(default_factory=list)


@dataclass
class DesignRulesKiCad:
    """
    Complete design rules from KiCad project.

    Contains ALL design rule data needed for routing.
    EXACT copy of what KiCad uses - NO GUESSING.
    """
    # Minimum values (hard limits)
    min_clearance: float = 0.15  # mm
    min_track_width: float = 0.1  # mm
    min_via_diameter: float = 0.35  # mm
    min_via_drill: float = 0.2  # mm
    min_via_annular_width: float = 0.075  # mm
    min_hole_to_hole: float = 0.25  # mm
    min_hole_clearance: float = 0.2  # mm
    min_copper_edge_clearance: float = 0.3  # mm
    min_through_hole_diameter: float = 0.3  # mm
    min_microvia_diameter: float = 0.2  # mm
    min_microvia_drill: float = 0.1  # mm

    # Default pad dimensions
    default_pad_width: float = 1.524  # mm
    default_pad_height: float = 1.524  # mm
    default_pad_drill: float = 0.762  # mm

    # Zone settings
    zone_min_clearance: float = 0.2  # mm

    # Net classes (name -> NetClass)
    net_classes: Dict[str, NetClass] = field(default_factory=dict)

    # Track width presets
    track_widths: List[float] = field(default_factory=lambda: [0.1, 0.15, 0.2, 0.25])

    # Via dimension presets
    via_dimensions: List[Dict[str, float]] = field(default_factory=lambda: [
        {'diameter': 0.35, 'drill': 0.2},
        {'diameter': 0.5, 'drill': 0.3},
        {'diameter': 0.6, 'drill': 0.35},
    ])

    def get_default_netclass(self) -> Optional[NetClass]:
        """Get the Default net class."""
        return self.net_classes.get('Default')

    def get_netclass_for_net(self, net_name: str) -> NetClass:
        """
        Get the appropriate net class for a net name.

        Uses pattern matching like KiCad does.
        """
        import fnmatch

        # Check each net class's patterns
        for nc in sorted(self.net_classes.values(), key=lambda x: x.priority):
            for pattern in nc.patterns:
                if fnmatch.fnmatch(net_name.upper(), pattern.upper()):
                    return nc

        # Fall back to Default
        return self.net_classes.get('Default', self._create_default_netclass())

    def _create_default_netclass(self) -> NetClass:
        """Create a default net class from minimum rules."""
        return NetClass(
            name='Default',
            clearance=self.min_clearance,
            track_width=self.min_track_width,
            via_diameter=self.min_via_diameter,
            via_drill=self.min_via_drill,
        )


class KiCadProjectLoader:
    """
    GENERIC: Load design rules from KiCad's project files.

    Uses the EXACT same project files that KiCad uses.
    NO GUESSING - just copying what KiCad would use.

    Usage:
        loader = KiCadProjectLoader()
        rules = loader.load_project('/path/to/project.kicad_pro')
        print(f"Clearance: {rules.min_clearance}mm")
        print(f"Track width: {rules.get_default_netclass().track_width}mm")
    """

    # Default rules based on JLCPCB capabilities (conservative)
    # These are used when no project file is available
    JLCPCB_DEFAULTS = {
        'min_clearance': 0.127,  # 5 mil
        'min_track_width': 0.127,  # 5 mil
        'min_via_diameter': 0.5,  # 0.5mm via
        'min_via_drill': 0.3,  # 0.3mm drill
        'min_via_annular_width': 0.1,
        'min_hole_to_hole': 0.25,
        'min_hole_clearance': 0.25,
    }

    # Default net class based on KiCad's standard defaults
    KICAD_DEFAULT_NETCLASS = {
        'clearance': 0.15,
        'track_width': 0.15,
        'via_diameter': 0.5,
        'via_drill': 0.3,
        'diff_pair_width': 0.2,
        'diff_pair_gap': 0.25,
    }

    def __init__(self):
        """Initialize the loader."""
        self._cache: Dict[str, DesignRulesKiCad] = {}

    def load_project(self, project_path: str) -> DesignRulesKiCad:
        """
        Load design rules from a KiCad project file.

        Args:
            project_path: Path to .kicad_pro file

        Returns:
            DesignRulesKiCad with EXACT rules from project
        """
        path = Path(project_path)

        # Check cache
        cache_key = str(path.resolve())
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Check file exists
        if not path.exists():
            logger.warning(f"Project file not found: {project_path}, using defaults")
            return self._create_defaults()

        # Parse JSON
        try:
            with open(path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {project_path}: {e}")
            return self._create_defaults()
        except Exception as e:
            logger.error(f"Failed to read {project_path}: {e}")
            return self._create_defaults()

        # Extract design rules
        rules = self._parse_design_rules(project_data)

        # Cache and return
        self._cache[cache_key] = rules
        logger.info(f"Loaded design rules from {project_path}")

        return rules

    def _parse_design_rules(self, project_data: Dict[str, Any]) -> DesignRulesKiCad:
        """
        Parse design rules from KiCad project JSON.

        GENERIC: Works for any KiCad project version.
        """
        rules = DesignRulesKiCad()

        # Get board design settings
        board = project_data.get('board', {})
        design_settings = board.get('design_settings', {})

        # Extract minimum rules
        min_rules = design_settings.get('rules', {})
        if min_rules:
            rules.min_clearance = min_rules.get('min_clearance', rules.min_clearance)
            rules.min_track_width = min_rules.get('min_track_width', rules.min_track_width)
            rules.min_via_diameter = min_rules.get('min_via_diameter', rules.min_via_diameter)
            rules.min_via_annular_width = min_rules.get('min_via_annular_width', rules.min_via_annular_width)
            rules.min_hole_to_hole = min_rules.get('min_hole_to_hole', rules.min_hole_to_hole)
            rules.min_hole_clearance = min_rules.get('min_hole_clearance', rules.min_hole_clearance)
            rules.min_copper_edge_clearance = min_rules.get('min_copper_edge_clearance', rules.min_copper_edge_clearance)
            rules.min_through_hole_diameter = min_rules.get('min_through_hole_diameter', rules.min_through_hole_diameter)
            rules.min_microvia_diameter = min_rules.get('min_microvia_diameter', rules.min_microvia_diameter)
            rules.min_microvia_drill = min_rules.get('min_microvia_drill', rules.min_microvia_drill)

        # Extract default pad dimensions
        defaults = design_settings.get('defaults', {})
        pads = defaults.get('pads', {})
        if pads:
            rules.default_pad_width = pads.get('width', rules.default_pad_width)
            rules.default_pad_height = pads.get('height', rules.default_pad_height)
            rules.default_pad_drill = pads.get('drill', rules.default_pad_drill)

        # Extract zone settings
        zones = defaults.get('zones', {})
        if zones:
            rules.zone_min_clearance = zones.get('min_clearance', rules.zone_min_clearance)

        # Extract track width presets
        track_widths = design_settings.get('track_widths', [])
        if track_widths:
            # Filter out 0 values (KiCad uses 0 to mean "use netclass")
            rules.track_widths = [w for w in track_widths if w > 0]

        # Extract via dimension presets
        via_dims = design_settings.get('via_dimensions', [])
        if via_dims:
            # Filter out 0 values
            rules.via_dimensions = [
                v for v in via_dims
                if v.get('diameter', 0) > 0 and v.get('drill', 0) > 0
            ]

        # Extract net classes
        net_settings = project_data.get('net_settings', {})
        net_classes = net_settings.get('classes', [])

        # Also get netclass patterns for pattern matching
        netclass_patterns = net_settings.get('netclass_patterns', [])
        pattern_map: Dict[str, List[str]] = {}
        for pattern_info in netclass_patterns:
            nc_name = pattern_info.get('netclass', '')
            pattern = pattern_info.get('pattern', '')
            if nc_name and pattern:
                if nc_name not in pattern_map:
                    pattern_map[nc_name] = []
                pattern_map[nc_name].append(pattern)

        for nc_data in net_classes:
            nc_name = nc_data.get('name', 'Default')
            nc = NetClass(
                name=nc_name,
                clearance=nc_data.get('clearance', 0.15),
                track_width=nc_data.get('track_width', 0.15),
                via_diameter=nc_data.get('via_diameter', 0.5),
                via_drill=nc_data.get('via_drill', 0.3),
                diff_pair_width=nc_data.get('diff_pair_width', 0.2),
                diff_pair_gap=nc_data.get('diff_pair_gap', 0.25),
                microvia_diameter=nc_data.get('microvia_diameter', 0.3),
                microvia_drill=nc_data.get('microvia_drill', 0.1),
                priority=nc_data.get('priority', 2147483647),
                patterns=pattern_map.get(nc_name, [])
            )
            rules.net_classes[nc_name] = nc

        # Ensure Default net class exists
        if 'Default' not in rules.net_classes:
            rules.net_classes['Default'] = rules._create_default_netclass()

        return rules

    def _create_defaults(self) -> DesignRulesKiCad:
        """
        Create default design rules based on JLCPCB capabilities.

        Used when no project file is available.
        """
        rules = DesignRulesKiCad(
            min_clearance=self.JLCPCB_DEFAULTS['min_clearance'],
            min_track_width=self.JLCPCB_DEFAULTS['min_track_width'],
            min_via_diameter=self.JLCPCB_DEFAULTS['min_via_diameter'],
            min_via_drill=self.JLCPCB_DEFAULTS['min_via_drill'],
            min_via_annular_width=self.JLCPCB_DEFAULTS['min_via_annular_width'],
            min_hole_to_hole=self.JLCPCB_DEFAULTS['min_hole_to_hole'],
            min_hole_clearance=self.JLCPCB_DEFAULTS['min_hole_clearance'],
        )

        # Add default net class
        rules.net_classes['Default'] = NetClass(
            name='Default',
            clearance=self.KICAD_DEFAULT_NETCLASS['clearance'],
            track_width=self.KICAD_DEFAULT_NETCLASS['track_width'],
            via_diameter=self.KICAD_DEFAULT_NETCLASS['via_diameter'],
            via_drill=self.KICAD_DEFAULT_NETCLASS['via_drill'],
            diff_pair_width=self.KICAD_DEFAULT_NETCLASS['diff_pair_width'],
            diff_pair_gap=self.KICAD_DEFAULT_NETCLASS['diff_pair_gap'],
            priority=2147483647,  # Lowest priority (default)
        )

        # Add Power net class (common pattern)
        rules.net_classes['Power'] = NetClass(
            name='Power',
            clearance=0.2,  # Wider clearance for power
            track_width=0.3,  # Wider tracks for current
            via_diameter=0.6,
            via_drill=0.35,
            priority=0,
            patterns=['VCC*', 'VDD*', 'GND*', '+*V', '-*V', '*PWR*', '*POWER*']
        )

        return rules

    def get_default_rules(self) -> DesignRulesKiCad:
        """Get default design rules without a project file."""
        return self._create_defaults()


# Convenience functions
_global_loader: Optional[KiCadProjectLoader] = None


def get_project_loader() -> KiCadProjectLoader:
    """
    Get the global project loader instance.

    Creates a singleton loader on first call for efficiency.
    """
    global _global_loader
    if _global_loader is None:
        _global_loader = KiCadProjectLoader()
    return _global_loader


def load_design_rules(project_path: str) -> DesignRulesKiCad:
    """
    Convenience function to load design rules from a project file.

    Args:
        project_path: Path to .kicad_pro file

    Returns:
        DesignRulesKiCad with rules from project (or defaults)
    """
    return get_project_loader().load_project(project_path)


def get_default_design_rules() -> DesignRulesKiCad:
    """
    Get default design rules without loading a project.

    Based on JLCPCB capabilities and KiCad defaults.
    """
    return get_project_loader().get_default_rules()


def find_project_file(directory: str) -> Optional[str]:
    """
    Find a .kicad_pro file in a directory.

    Args:
        directory: Directory to search

    Returns:
        Path to .kicad_pro file, or None if not found
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        return None

    # Look for .kicad_pro files
    for kicad_pro in dir_path.glob('*.kicad_pro'):
        return str(kicad_pro)

    return None


__all__ = [
    'NetClass',
    'DesignRulesKiCad',
    'KiCadProjectLoader',
    'get_project_loader',
    'load_design_rules',
    'get_default_design_rules',
    'find_project_file',
]
