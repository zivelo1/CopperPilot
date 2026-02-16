#!/usr/bin/env python3
# Copyright (c) 2024-2026 Ziv Elovitch. All rights reserved.
# Licensed under the MIT License. See LICENSE file for details.

"""
EasyEDA AI-Based Fixer - Diagnoses failures and recommends strategies.

Similar to KiCad AI Fixer, this module analyzes failure patterns (logs, stats)
to determine the root cause and select the best fix strategy.

Diagnoses:
- ROUTING_FAILURE: Freerouting timed out or produced 0 segments.
- PLACEMENT_FAILURE: Components could not be placed (not yet implemented).
- VALIDATION_FAILURE: ERC/DRC failed (not yet implemented).
"""

import os
import logging
from typing import Dict, List, Tuple, Optional

# Import Anthropic client
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)

class EasyEdaAiFixer:
    """
    AI-powered diagnosis for EasyEDA Pro conversion failures.
    """

    def __init__(self):
        self.client = None
        if ANTHROPIC_AVAILABLE:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                self.client = anthropic.Anthropic(api_key=api_key)

    def diagnose_failure(self, error_log: List[str], routing_stats: Optional[Dict], validator_results: Optional[Dict] = None) -> str:
        """
        Diagnose the primary failure reason.
        
        Args:
            error_log: List of error messages.
            routing_stats: Dictionary of routing statistics (if available).
            validator_results: Dictionary of validation results (ERC/DRC) (if available).
            
        Returns:
            Diagnosis string (e.g. "ROUTING_FAILURE")
        """
        # Check Validator Results (Most Specific)
        if validator_results:
            # Check for specific DRC failures
            drc_warnings = validator_results.get('warnings', [])
            drc_errors = validator_results.get('errors', [])
            
            all_msgs = drc_errors + drc_warnings
            all_text = " ".join(all_msgs).lower()
            
            if "board size" in all_text and ("below" in all_text or "small" in all_text):
                return "BOARD_TOO_SMALL"
            
            if "zero line (track) segments" in all_text or "unrouted" in all_text:
                return "ROUTING_FAILURE"

        # Check for routing timeout / zero segments
        if routing_stats:
            if routing_stats.get('total_segments', 0) == 0:
                return "ROUTING_FAILURE"
        
        for err in error_log:
            if "Freerouting failed" in err or "produced no segments" in err:
                return "ROUTING_FAILURE"
            if "timeout" in err.lower():
                return "ROUTING_FAILURE"

        # Default
        return "UNKNOWN_FAILURE"

    def recommend_strategies(self, diagnosis: str, attempt: int) -> List[Tuple[int, str]]:
        """
        Recommend fix strategies based on diagnosis and attempt number.
        
        Strategies:
        1: Relax Constraints
        2: Expand Board
        3: Extend Timeout
        """
        strategies = []
        
        if diagnosis == "ROUTING_FAILURE":
            if attempt == 1:
                # Try relaxing rules first (least invasive)
                strategies.append((1, "Relax routing constraints to ease pathfinding"))
                # Also try expanding board slightly
                strategies.append((2, "Expand board to relieve congestion"))
            elif attempt == 2:
                # Try extending timeout
                strategies.append((3, "Extend routing timeout"))
                # And expand board more
                strategies.append((2, "Expand board further"))
        
        elif diagnosis == "BOARD_TOO_SMALL":
            strategies.append((2, "Expand board dimensions"))
        
        return strategies
