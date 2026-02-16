#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
EasyEDA Code-Based Auto-Fixer - GENERIC for ALL circuit types

This module implements algorithmic fixes for common EasyEDA conversion failures,
specifically focusing on Freerouting timeouts and complexity issues.

Strategies:
1. Relax Constraints: Reduce clearance/track width to make routing easier.
2. Expand Board: Increase board dimensions to relieve congestion.
3. Extend Timeout: Increase Freerouting timeout for complex boards.

GENERIC: Works for any circuit type by modifying the configuration used
to generate the PCB/DSN.
"""

import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

class EasyEdaCodeFixer:
    """
    Code-based fixer for EasyEDA Pro conversion.
    Modifies conversion configuration to resolve routing failures.
    """

    def __init__(self):
        self.strategies = {
            1: self._relax_constraints,
            2: self._expand_board,
            3: self._extend_timeout
        }

    def apply_fix(self, config: Dict[str, Any], strategy: int) -> Tuple[bool, str]:
        """
        Apply a specific fix strategy to the configuration.

        Args:
            config: The converter configuration dictionary (modified in-place).
            strategy: Strategy ID (1=Relax, 2=Expand, 3=Timeout).

        Returns:
            Tuple(success: bool, message: str)
        """
        if strategy not in self.strategies:
            return False, f"Unknown strategy {strategy}"

        return self.strategies[strategy](config)

    def _relax_constraints(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Strategy 1: Relax routing constraints (clearance/width)."""
        routing = config.setdefault('routing', {})
        
        # Reduce clearance (min 0.15mm)
        current_clearance = routing.get('clearance', 0.2)
        new_clearance = max(0.15, current_clearance * 0.75)
        routing['clearance'] = new_clearance

        # Reduce track width (min 0.15mm)
        current_width = routing.get('track_width', 0.25)
        new_width = max(0.15, current_width * 0.8)
        routing['track_width'] = new_width

        return True, f"Relaxed constraints: clearance={new_clearance:.3f}mm, width={new_width:.3f}mm"

    def _expand_board(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Strategy 2: Expand board dimensions by 20%."""
        pcb = config.setdefault('pcb', {})
        
        current_w = pcb.get('width', 100)
        current_h = pcb.get('height', 80)
        
        new_w = current_w * 1.2
        new_h = current_h * 1.2
        
        pcb['width'] = new_w
        pcb['height'] = new_h
        
        return True, f"Expanded board to {new_w:.1f}x{new_h:.1f}mm"

    def _extend_timeout(self, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Strategy 3: Increase Freerouting timeout."""
        routing = config.setdefault('routing', {})
        
        # Note: The actual timeout logic in easyeda_converter_pro.py might need 
        # to check this config value. We'll ensure it does.
        current_multiplier = routing.get('timeout_multiplier', 1.0)
        new_multiplier = current_multiplier * 2.0
        routing['timeout_multiplier'] = new_multiplier
        
        return True, f"Increased timeout multiplier to {new_multiplier}x"
